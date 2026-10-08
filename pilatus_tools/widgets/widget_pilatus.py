"""Pilatus monitor with bounded rendering and Qt-thread-safe subscriptions."""

import json
import logging
import os
from functools import partial
from importlib.resources import as_file, files
from pathlib import Path
from threading import Lock

import numpy as np
import pyqtgraph as pg
from PyQt5 import QtCore, uic
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)
with as_file(files("pilatus_tools").joinpath("ui/ui_pilatus.ui")) as ui_path:
    _Ui, _Base = uic.loadUiType(str(ui_path))


class UIPilatusMonitor(_Base, _Ui):
    """Monitor an ophyd-compatible detector supplied as ``{'Pilatus 100k': {'device': det}}``.

    ``image_shape`` is (rows, columns); the display retains the legacy orientation.
    Frames are coalesced at ``refresh_interval_ms`` without polling the detector.
    Polygon persistence is opt-in via ``polygon_roi_path`` or XPILATUS_POLYGON_ROI_PATH.
    Close the widget to release its subscriptions before discarding it.
    """

    _dispatch = QtCore.pyqtSignal(object, object)

    def __init__(
        self,
        detector_dict=None,
        hhm=None,
        parent=None,
        *,
        polygon_roi_path=None,
        image_shape=(195, 487),
        refresh_interval_ms=50,
    ):
        if detector_dict is None or "Pilatus 100k" not in detector_dict:
            raise ValueError("detector_dict must contain a 'Pilatus 100k' device")
        if refresh_interval_ms < 1:
            raise ValueError("refresh_interval_ms must be positive")
        if len(image_shape) != 2 or any(size <= 0 for size in image_shape):
            raise ValueError("image_shape must contain two positive dimensions")
        super().__init__(parent)
        self.setupUi(self)
        self.detector_dict = detector_dict
        self.hhm = hhm
        self.pilatus100k_dict = detector_dict["Pilatus 100k"]
        self.pilatus100k_device = self.pilatus100k_dict["device"]
        self.image_shape = tuple(image_shape)
        self._subscriptions = []
        self._closed = False
        self._frame_lock = Lock()
        self._pending_frame = None
        self._min, self._max = 0, 5
        self._dispatch.connect(self._apply_update, QtCore.Qt.QueuedConnection)
        path = polygon_roi_path or os.environ.get("XPILATUS_POLYGON_ROI_PATH")
        self.polygon_roi_path = Path(path).expanduser() if path else None
        self.pilatus_polygon_roi = {}
        if self.polygon_roi_path and self.polygon_roi_path.exists():
            with self.polygon_roi_path.open() as stream:
                self.pilatus_polygon_roi = json.load(stream)

        self.gain_menu = dict(
            enumerate(
                [
                    "7-30keV/Fast/LowG",
                    "5-18keV/Med/MedG",
                    "3-6keV/Slow/HighG",
                    "2-5keV/Slow/UltraG",
                ]
            )
        )
        self.comboBox_shapetime.addItems(self.gain_menu.values())
        self.comboBox_shapetime.currentIndexChanged.connect(self.change_pilatus_gain)
        self.radioButton_single_exposure.toggled.connect(self.update_acquisition_mode)
        self.radioButton_continuous_exposure.toggled.connect(self.update_acquisition_mode)
        self.pushButton_start.clicked.connect(self.acquire_image)
        self.pushButton_stop.clicked.connect(self.stop_acquire_image)
        self.checkBox_detector_settings.toggled.connect(self.open_detector_setting)
        self.checkBox_enable_energy_change.toggled.connect(self.open_energy_change)
        self.pushButton_move_energy.clicked.connect(self.set_mono_energy)
        self.checkBox_enable_energy_change.setEnabled(hhm is not None)
        self.pushButton_move_energy.setEnabled(hhm is not None)
        self.label_current_energy.setText("Unavailable" if hhm is None else "Connecting…")
        self.checkBox_detector_flying.setEnabled(False)  # Display-only legacy control.
        self.lineEdit_min.returnPressed.connect(self.update_min_range)
        self.lineEdit_max.returnPressed.connect(self.update_max_range)
        self.horizontalSlider_min.sliderReleased.connect(self.update_slider_min_range)
        self.horizontalSlider_max.sliderReleased.connect(self.update_slider_max_range)
        self.checkBox_auto_scale.toggled.connect(self.auto_scale_image)
        self.label_x.setText("▴ ▾")
        self.label_y.setText("◂  ▸")
        for label in (self.label_x, self.label_y):
            label.setFont(QFont("Arial", 16))
        self._sync_levels()
        self.create_plot_widget()
        self.checkBox_show_polygon_rois.toggled.connect(self.add_polygon_rois)

        cam = self.pilatus100k_device.cam
        self.subscription_dict = {
            "exposure": cam.acquire_time,
            "num_of_images": cam.num_images,
            "set_energy": cam.set_energy,
            "cutoff_energy": cam.threshold_energy,
        }
        # All widgets and ROIs exist before subscribe() can deliver an initial value.
        for i in range(1, 5):
            self.add_roi_parameters(i)
        for key in self.subscription_dict:
            self.add_pilatus_attribute(key)
        self._subscribe(cam.gain_menu, self.update_gain_combobox)
        self._subscribe(cam.image_mode, self._update_mode)
        self._subscribe(cam.detector_state, self._update_detector_state)
        for ch in range(1, 5):
            self._subscribe(
                getattr(self.pilatus100k_device, f"stats{ch}").total, partial(self._update_counts, ch)
            )
        if hhm is not None:
            self._subscribe(hhm.energy.user_readback, self._update_energy)
        self._subscribe(self.pilatus100k_device.image.array_data, self._receive_frame, queued=False)
        self.update_image_timer = QtCore.QTimer(self)
        self.update_image_timer.setInterval(refresh_interval_ms)
        self.update_image_timer.timeout.connect(self.plot_this)
        self.update_image_timer.start()

    def _subscribe(self, signal, callback, *, queued=True):
        def receive(value, **kwargs):
            if not self._closed:
                if queued:
                    self._dispatch.emit(callback, value)
                else:
                    callback(value)

        signal.subscribe(receive)
        self._subscriptions.append((signal, receive))

    @QtCore.pyqtSlot(object, object)
    def _apply_update(self, callback, value):
        if not self._closed:
            callback(value)

    def _receive_frame(self, value):
        # Copy once: some producers reuse their buffers after a callback returns.
        frame = np.asarray(value)
        if frame.size != np.prod(self.image_shape):
            logger.warning("Ignoring image with %s pixels; expected %s", frame.size, self.image_shape)
            return
        with self._frame_lock:
            self._pending_frame = frame.reshape(self.image_shape).copy()

    def plot_this(self):
        with self._frame_lock:
            frame, self._pending_frame = self._pending_frame, None
        if frame is not None:
            auto = self.checkBox_auto_scale.isChecked()
            self.image.setImage(frame, autoLevels=auto, levels=None if auto else (self._min, self._max))

    def create_plot_widget(self):
        self.window = pg.GraphicsLayoutWidget()
        self.verticalLayout_pilatus_image.addWidget(self.window)
        self.plot = self.window.addPlot()
        self.plot.setAspectLocked(True)
        self.plot.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        # Explicit axis order preserves detector/ROI coordinates regardless of global pg settings.
        self.image = pg.ImageItem(axisOrder="col-major")
        self.image.setColorMap(pg.colormap.getFromMatplotlib("jet"))
        self.plot.addItem(self.image)
        self.colors = {"1": "red", "2": "cyan", "3": "lime", "4": "yellow"}
        self.roi_boxes = {}
        for index, color in self.colors.items():
            x, y, dx, dy = self.pilatus100k_device.get_roi_coords(int(index))
            roi = pg.ROI([y, x], [dy, dx], pen=pg.mkPen(color, width=3), rotatable=False)
            roi.addScaleHandle([0.5, 0], [0.5, 1])
            roi.addScaleHandle([0, 0.5], [1, 0.5])
            self.roi_boxes[index] = roi
            checkbox = getattr(self, f"checkBox_roi{index}")
            checkbox.setStyleSheet(f"QCheckBox::checked {{background-color: {color};}}")
            checkbox.toggled.connect(partial(self.add_roi_box, index))
            roi.sigRegionChangeFinished.connect(partial(self.read_new_pos_n_size, index))
            self.add_roi_box(index, checkbox.isChecked())
        self.colors_polygon = dict(
            zip(
                ("main", "aux2", "aux3", "aux4", "aux5"),
                ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"),
                strict=True,
            )
        )
        self.gui_polygon_roi, self.gui_polygon_label = {}, {}
        for crystal, vertices in self.pilatus_polygon_roi.items():
            color = self.colors_polygon.get(crystal, "white")
            polygon = pg.PolyLineROI([[y, x] for x, y in vertices], closed=True, pen=pg.mkPen(color, width=3))
            polygon.sigRegionChangeFinished.connect(self.save_polygon_roi_coords)
            self.gui_polygon_roi[crystal] = polygon
            label = pg.TextItem(crystal, color=color, fill="w", anchor=(0.5, 0.5))
            label.setFont(QFont("Arial", 16, QFont.Bold))
            self.gui_polygon_label[crystal] = label
        self.set_polygon_roi_label_positions()

    def add_roi_box(self, index, checked):
        operation = self.plot.addItem if checked else self.plot.removeItem
        operation(self.roi_boxes[index])

    def read_new_pos_n_size(self, roi_indx):
        box = self.roi_boxes[roi_indx]
        y, x = box.pos()
        dy, dx = box.size()
        rows, columns = self.image_shape
        x, y = int(np.clip(round(x), 0, columns - 1)), int(np.clip(round(y), 0, rows - 1))
        dx, dy = int(np.clip(round(dx), 1, columns - x)), int(np.clip(round(dy), 1, rows - y))
        roi = getattr(self.pilatus100k_device, f"roi{roi_indx}")
        for signal, value in zip(
            (roi.min_xyz.min_x, roi.min_xyz.min_y, roi.size.x, roi.size.y), (x, y, dx, dy), strict=True
        ):
            signal.put(value)

    def add_polygon_rois(self, checked_state):
        operation = self.plot.addItem if checked_state else self.plot.removeItem
        for item in (*self.gui_polygon_roi.values(), *self.gui_polygon_label.values()):
            operation(item)

    def set_polygon_roi_label_positions(self, dy=25):
        for crystal, polygon in self.gui_polygon_roi.items():
            rect = polygon.mapRectToParent(polygon.boundingRect())
            self.gui_polygon_label[crystal].setPos(rect.center().x(), rect.bottom() + dy)

    @property
    def gui_polygon_roi_coords(self):
        return {
            crystal: [
                [round(point.y(), 1), round(point.x(), 1)]
                for _, point in polygon.getLocalHandlePositions()
                for point in [polygon.mapToParent(point)]
            ]
            for crystal, polygon in self.gui_polygon_roi.items()
        }

    def save_polygon_roi_coords(self):
        self.set_polygon_roi_label_positions()
        if self.polygon_roi_path:
            try:
                with self.polygon_roi_path.open("w") as stream:
                    json.dump(self.gui_polygon_roi_coords, stream)
            except OSError as exc:
                self.label_message.setText(f"Could not save polygon ROIs: {exc}")

    def add_roi_parameters(self, ch):
        index = str(ch)
        roi = getattr(self.pilatus100k_device, f"roi{ch}")
        for field, signal in {
            "min_x": roi.min_xyz.min_x,
            "min_y": roi.min_xyz.min_y,
            "width": roi.size.x,
            "height": roi.size.y,
        }.items():
            spin = getattr(self, f"spinBox_roi{ch}_{field}")
            spin.editingFinished.connect(partial(self._write_spin, signal, spin))
            self._subscribe(signal, partial(self._update_roi, index, field))

    @staticmethod
    def _write_spin(signal, spin):
        signal.put(spin.value())

    def _update_roi(self, index, field, value):
        getattr(self, f"spinBox_roi{index}_{field}").setValue(int(value))
        box = self.roi_boxes[index]
        # Readback must never feed back into hardware writes through ROI signals.
        with QtCore.QSignalBlocker(box):
            if field in ("min_x", "min_y"):
                position = list(box.pos())
                position[1 if field == "min_x" else 0] = value
                box.setPos(position)
            else:
                size = list(box.size())
                size[1 if field == "width" else 0] = value
                box.setSize(size)

    def _sync_levels(self):
        for name, value in (("min", self._min), ("max", self._max)):
            getattr(self, f"label_{name}").setText(str(value))
            getattr(self, f"lineEdit_{name}").setText(str(value))
            slider = getattr(self, f"horizontalSlider_{name}")
            slider.setRange(min(slider.minimum(), value), max(slider.maximum(), value))
            slider.setValue(value)

    def _set_level(self, name, value):
        try:
            value = int(value)
        except (ValueError, TypeError):
            self.label_message.setText("Enter an integer intensity.")
            return
        low, high = (value, self._max) if name == "min" else (self._min, value)
        if low >= high:
            self.label_message.setText("Minimum must be smaller than maximum.")
            return
        self._min, self._max = low, high
        self.checkBox_auto_scale.setChecked(False)
        self.image.setLevels((low, high))
        self._sync_levels()
        self.label_message.clear()

    def update_min_range(self):
        self._set_level("min", self.lineEdit_min.text())

    def update_max_range(self):
        self._set_level("max", self.lineEdit_max.text())

    def update_slider_min_range(self):
        self._set_level("min", self.horizontalSlider_min.value())

    def update_slider_max_range(self):
        self._set_level("max", self.horizontalSlider_max.value())

    def auto_scale_image(self):
        if self.checkBox_auto_scale.isChecked() and self.image.image is not None:
            self.image.setLevels(self.image.quickMinMax())
        else:
            self.image.setLevels((self._min, self._max))

    def _update_counts(self, ch, value):
        getattr(self, f"label_counts_roi{ch}").setText(f"{value} cts")

    def _update_energy(self, value):
        self.label_current_energy.setText(f"{value:4.1f} eV")

    def _update_detector_state(self, value):
        acquiring = value == 1
        self.label_detector_state.setText("Acquiring" if acquiring else "Idle")
        self.label_detector_state.setStyleSheet(
            "background-color: rgb(95,249,95)" if acquiring else "background-color: rgb(255,0,0)"
        )

    def set_mono_energy(self):
        if self.hhm is not None and self.checkBox_enable_energy_change.isChecked():
            self.hhm.energy.user_setpoint.put(self.spinBox_mono_energy.value())

    def open_energy_change(self):
        self.spinBox_mono_energy.setEnabled(
            self.hhm is not None and self.checkBox_enable_energy_change.isChecked()
        )

    def open_detector_setting(self):
        enabled = self.checkBox_detector_settings.isChecked()
        self.lineEdit_set_energy.setEnabled(enabled)
        self.lineEdit_cutoff_energy.setEnabled(enabled)

    def stop_acquire_image(self):
        self.pilatus100k_device.cam.acquire.put(0)

    def acquire_image(self):
        self.pilatus100k_device.cam.acquire.put(1)

    def _update_mode(self, value):
        with (
            QtCore.QSignalBlocker(self.radioButton_single_exposure),
            QtCore.QSignalBlocker(self.radioButton_continuous_exposure),
        ):
            if value in (0, 2):
                self.radioButton_single_exposure.setChecked(value == 0)
                self.radioButton_continuous_exposure.setChecked(value == 2)

    def update_acquisition_mode(self, checked=True):
        if checked:
            continuous = self.radioButton_continuous_exposure.isChecked()
            self.pilatus100k_device.cam.image_mode.put(2 if continuous else 0)
            self.pilatus100k_device.cam.trigger_mode.put(4 if continuous else 0)

    def add_pilatus_attribute(self, attribute_key):
        signal = self.subscription_dict[attribute_key]
        edit = getattr(self, f"lineEdit_{attribute_key}")
        edit.returnPressed.connect(partial(self._write_attribute, attribute_key, signal, edit))
        self._subscribe(signal, partial(self._update_attribute, attribute_key))

    def _write_attribute(self, key, signal, edit):
        try:
            value = float(edit.text())
            if (
                not np.isfinite(value)
                or value < 0
                or (key == "num_of_images" and (value < 1 or not value.is_integer()))
            ):
                raise ValueError
        except ValueError:
            self.label_message.setText("Enter a nonnegative number (a positive integer for image count).")
            return
        signal.put(int(value) if key == "num_of_images" else value)
        self.label_message.clear()

    def _update_attribute(self, key, value):
        unit = "s" if key == "exposure" else "" if key == "num_of_images" else "keV"
        getattr(self, f"label_{key}").setText(f"{value:2.3f} {unit}")
        edit = getattr(self, f"lineEdit_{key}")
        if not edit.hasFocus():
            edit.setText(f"{value:2.3f}")

    def change_pilatus_gain(self, index):
        self.pilatus100k_device.cam.gain_menu.put(index)

    def update_gain_combobox(self, value, **kwargs):
        self.label_gain.setText(self.gain_menu.get(value, str(value)))
        with QtCore.QSignalBlocker(self.comboBox_shapetime):
            self.comboBox_shapetime.setCurrentIndex(int(value))

    def closeEvent(self, event):
        self._closed = True
        self.update_image_timer.stop()
        for signal, callback in self._subscriptions:
            try:
                signal.clear_sub(callback)
            except Exception:
                logger.exception("Could not remove detector subscription")
        self._subscriptions.clear()
        with self._frame_lock:
            self._pending_frame = None
        super().closeEvent(event)
