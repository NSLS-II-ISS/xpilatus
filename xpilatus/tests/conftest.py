import pytest

from pilatus_tools.widgets.widget_pilatus import UIPilatusMonitor
from xpilatus.simulation import SimulatedDetector


@pytest.fixture
def detector(qapp):
    device = SimulatedDetector()
    yield device
    device.timer.stop()


@pytest.fixture
def monitor(qtbot, detector):
    widget = UIPilatusMonitor({"Pilatus 100k": {"device": detector}})
    qtbot.addWidget(widget)
    widget.update_image_timer.stop()
    qtbot.waitUntil(lambda: widget.label_exposure.text() == "0.100 s")
    return widget
