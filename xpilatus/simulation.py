"""Small in-process detector for demonstrations and GUI regression tests."""

from types import SimpleNamespace

import numpy as np
from PyQt5 import QtCore


class Signal:
    """Subset of the ophyd signal protocol used by the monitor."""

    def __init__(self, value):
        self._value = value
        self._callbacks = []

    def get(self):
        return self._value

    def put(self, value):
        self._value = value
        for callback in tuple(self._callbacks):
            callback(value=value)

    def subscribe(self, callback):
        self._callbacks.append(callback)
        callback(value=self._value)

    def clear_sub(self, callback):
        self._callbacks.remove(callback)


class SimulatedDetector(QtCore.QObject):
    """Generate synthetic Pilatus frames without EPICS or beamline access."""

    def __init__(self, shape=(195, 487), parent=None):
        super().__init__(parent)
        self.shape = shape
        self.cam = SimpleNamespace(
            **{
                key: Signal(value)
                for key, value in {
                    "acquire_time": 0.1,
                    "num_images": 1,
                    "set_energy": 12.0,
                    "threshold_energy": 6.0,
                    "gain_menu": 0,
                    "image_mode": 0,
                    "trigger_mode": 0,
                    "detector_state": 0,
                    "acquire": 0,
                }.items()
            }
        )
        self.image = SimpleNamespace(array_data=Signal(np.zeros(shape, dtype=np.float32).ravel()))
        for index in range(1, 5):
            setattr(
                self,
                f"roi{index}",
                SimpleNamespace(
                    min_xyz=SimpleNamespace(min_x=Signal(index * 30), min_y=Signal(index * 15)),
                    size=SimpleNamespace(x=Signal(40), y=Signal(30)),
                ),
            )
            setattr(self, f"stats{index}", SimpleNamespace(total=Signal(0)))
        y, x = np.indices(shape, dtype=np.float32)
        self._profile = 100 * np.exp(-((x - shape[1] / 2) ** 2 + (y - shape[0] / 2) ** 2) / 2000)
        self._rng = np.random.default_rng(0)
        self._remaining = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.cam.acquire.subscribe(self._acquire)

    def get_roi_coords(self, index):
        roi = getattr(self, f"roi{index}")
        return roi.min_xyz.min_x.get(), roi.min_xyz.min_y.get(), roi.size.x.get(), roi.size.y.get()

    def _acquire(self, value, **kwargs):
        self.cam.detector_state.put(int(bool(value)))
        if value:
            self._remaining = max(1, int(self.cam.num_images.get()))
            self.timer.start(max(1, round(1000 * self.cam.acquire_time.get())))
        else:
            self.timer.stop()

    def advance(self):
        frame = self._rng.poisson(self._profile + 2).astype(np.float32)
        self.image.array_data.put(frame.ravel())
        for index in range(1, 5):
            x, y, dx, dy = self.get_roi_coords(index)
            getattr(self, f"stats{index}").total.put(int(frame[y : y + dy, x : x + dx].sum()))
        if self.cam.image_mode.get() != 2:
            self._remaining -= 1
            if self._remaining <= 0:
                self.cam.acquire.put(0)
