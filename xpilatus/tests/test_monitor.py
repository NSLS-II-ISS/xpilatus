import json
from threading import Thread
from unittest.mock import Mock

import numpy as np
import pytest

from pilatus_tools.widgets.widget_pilatus import UIPilatusMonitor


def test_startup_does_not_write_detector(qtbot, detector):
    detector.cam.image_mode.put(2)
    detector.cam.trigger_mode.put(4)
    signals = [
        detector.cam.image_mode,
        detector.cam.trigger_mode,
        detector.cam.gain_menu,
        detector.roi1.min_xyz.min_x,
        detector.roi1.size.x,
    ]
    for signal in signals:
        signal.put = Mock(wraps=signal.put)
    widget = UIPilatusMonitor({"Pilatus 100k": {"device": detector}})
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.radioButton_continuous_exposure.isChecked())
    for signal in signals:
        signal.put.assert_not_called()


def test_frames_are_coalesced_and_idle_does_not_read(monitor, detector):
    monitor.plot_this()
    monitor.image.setImage = Mock(wraps=monitor.image.setImage)
    detector.image.array_data.get = Mock(side_effect=AssertionError("unexpected polling"))
    frame = np.ones((195, 487), dtype=np.float32)
    for value in range(10):
        frame.fill(value)
        detector.image.array_data.put(frame.ravel())
    frame.fill(-1)  # The producer may reuse its own buffer.
    monitor.plot_this()
    monitor.plot_this()
    monitor.image.setImage.assert_called_once()
    np.testing.assert_array_equal(monitor.image.image, np.full((195, 487), 9))
    assert monitor.image.axisOrder == "col-major"


def test_invalid_frame_does_not_replace_valid_frame(monitor, detector):
    detector.image.array_data.put(np.ones(195 * 487))
    detector.image.array_data.put(np.zeros(2))
    monitor.plot_this()
    assert monitor.image.image.shape == (195, 487)
    assert monitor.image.image.min() == 1


def test_background_callbacks_run_on_qt_thread(monitor, detector, qtbot):
    detector.roi1.min_xyz.min_x.put = Mock(wraps=detector.roi1.min_xyz.min_x.put)
    thread = Thread(target=lambda: detector.roi1.min_xyz.min_x.put(72))
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: monitor.spinBox_roi1_min_x.value() == 72)
    assert monitor.roi_boxes["1"].pos().y() == 72
    detector.roi1.min_xyz.min_x.put.assert_called_once_with(72)


def test_roi_drag_writes_integer_detector_coordinates(monitor, detector, qtbot):
    monitor.roi_boxes["1"].setPos((20.2, 80.8))
    qtbot.waitUntil(lambda: monitor.spinBox_roi1_min_x.value() == 81)
    assert detector.get_roi_coords(1) == (81, 20, 40, 30)


def test_manual_and_auto_levels(monitor, detector):
    detector.image.array_data.put(np.arange(195 * 487))
    monitor.plot_this()
    monitor.checkBox_auto_scale.setChecked(True)
    assert monitor.image.levels[1] > 5
    monitor.checkBox_auto_scale.setChecked(False)
    np.testing.assert_array_equal(monitor.image.levels, [0, 5])
    monitor.lineEdit_max.setText("20")
    monitor.update_max_range()
    np.testing.assert_array_equal(monitor.image.levels, [0, 20])
    monitor.lineEdit_min.setText("bad")
    monitor.update_min_range()
    assert monitor._min == 0
    monitor.lineEdit_min.setText("30")
    monitor.update_min_range()
    assert monitor._min == 0


def test_no_monochromator_still_updates_counts(monitor, detector, qtbot):
    detector.stats1.total.put(123)
    qtbot.waitUntil(lambda: monitor.label_counts_roi1.text() == "123 cts")
    assert not monitor.checkBox_enable_energy_change.isEnabled()


def test_close_removes_subscriptions(monitor, detector, qtbot):
    signal = detector.image.array_data
    assert signal._callbacks
    detector.stats1.total.put(321)  # Queue an update before closing.
    monitor.close()
    qtbot.wait(10)
    assert not signal._callbacks
    assert not detector.stats1.total._callbacks
    assert not monitor.update_image_timer.isActive()
    assert monitor.label_counts_roi1.text() != "321 cts"


def test_polygon_translation_is_saved(qtbot, detector, tmp_path):
    path = tmp_path / "polygons.json"
    path.write_text(json.dumps({"main": [[0, 0], [10, 0], [10, 10]]}))
    widget = UIPilatusMonitor({"Pilatus 100k": {"device": detector}}, polygon_roi_path=path)
    qtbot.addWidget(widget)
    widget.gui_polygon_roi["main"].setPos((5, 7))
    widget.save_polygon_roi_coords()
    assert json.loads(path.read_text())["main"] == [[7, 5], [17, 5], [17, 15]]


@pytest.mark.parametrize("text", ["oops", "nan", "inf", "-1", "1.5", "0"])
def test_invalid_image_count_does_not_write(monitor, detector, text):
    monitor.lineEdit_num_of_images.setText(text)
    monitor.lineEdit_num_of_images.returnPressed.emit()
    assert detector.cam.num_images.get() == 1


def test_acquisition_controls(monitor, detector, qtbot):
    monitor.radioButton_continuous_exposure.click()
    assert detector.cam.image_mode.get() == 2
    assert detector.cam.trigger_mode.get() == 4
    monitor.pushButton_start.click()
    qtbot.waitUntil(lambda: monitor.label_detector_state.text() == "Acquiring")
    assert detector.timer.isActive()
    monitor.pushButton_stop.click()
    qtbot.waitUntil(lambda: monitor.label_detector_state.text() == "Idle")
    assert not detector.timer.isActive()
    monitor.radioButton_single_exposure.click()
    assert detector.cam.image_mode.get() == 0
    assert detector.cam.trigger_mode.get() == 0


def test_monochromator_readback_and_write(qtbot, detector):
    from types import SimpleNamespace

    from xpilatus.simulation import Signal

    hhm = SimpleNamespace(energy=SimpleNamespace(user_readback=Signal(9000), user_setpoint=Signal(9000)))
    widget = UIPilatusMonitor({"Pilatus 100k": {"device": detector}}, hhm=hhm)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.label_current_energy.text() == "9000.0 eV")
    widget.checkBox_enable_energy_change.setChecked(True)
    widget.spinBox_mono_energy.setValue(9500)
    widget.pushButton_move_energy.click()
    assert hhm.energy.user_setpoint.get() == 9500


def test_frame_from_background_thread(monitor, detector):
    thread = Thread(target=lambda: detector.image.array_data.put(np.full(195 * 487, 42)))
    thread.start()
    thread.join()
    monitor.plot_this()
    assert np.all(monitor.image.image == 42)
