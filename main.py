"""Start Super Labeller.  Usage:  python main.py [design.tlabel]"""
import os
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

from superlabeller import APP_NAME, __version__
from superlabeller.mainwindow import MainWindow


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))  # _MEIPASS when frozen
    icon = os.path.join(base, "assets", "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        win.open_file(sys.argv[1])
    else:
        QTimer.singleShot(0, win.new_file)  # start with the label setup wizard
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
