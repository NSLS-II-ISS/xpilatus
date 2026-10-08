"""Launch the standalone hardware-free demo."""

import argparse
import math
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pilatus detector monitor")
    parser.add_argument("--demo", action="store_true", help="run with a simulated detector")
    parser.add_argument("--quit-after", type=float, metavar="SECONDS", help="close the demo automatically")
    args = parser.parse_args(argv)
    if not args.demo:
        parser.error("use --demo, or construct UIPilatusMonitor with your beamline detector in Python")
    if args.quit_after is not None and (not math.isfinite(args.quit_after) or args.quit_after <= 0):
        parser.error("--quit-after must be a finite positive number")

    from PyQt5 import QtCore, QtWidgets

    from pilatus_tools.widgets.widget_pilatus import UIPilatusMonitor
    from xpilatus.simulation import SimulatedDetector

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    detector = SimulatedDetector()
    detector.cam.image_mode.put(2)
    widget = UIPilatusMonitor({"Pilatus 100k": {"device": detector}})
    widget.setWindowTitle("Pilatus monitor — simulated detector")
    widget.checkBox_auto_scale.setChecked(True)
    widget.show()
    detector.cam.acquire.put(1)
    if args.quit_after is not None:
        QtCore.QTimer.singleShot(round(args.quit_after * 1000), widget.close)
    result = app.exec()
    detector.timer.stop()
    widget.close()
    return result


if __name__ == "__main__":
    sys.exit(main())
