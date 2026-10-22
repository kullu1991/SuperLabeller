"""Printer connection / print dialog."""
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox,
                             QStackedWidget, QVBoxLayout, QWidget)

from . import printing

KINDS = [
    ("cups" if not printing.IS_WINDOWS else "windows", "Installed printer"),
    ("network", "Network (TCP port 9100)"),
    ("serial", "Serial / COM port"),
    ("file", "Save to file (.prn)"),
    ("mock", "Mock printer (animation, no printer needed)"),
]


class PrintDialog(QDialog):
    def __init__(self, parent, target, copies=1, setup_only=False, records=None, copies_label=None):
        """records: None, or dict(count, current, selected, columns) when a data source is loaded."""
        super().__init__(parent)
        self.setWindowTitle("Printer connection" if setup_only else "Print labels")
        self.setMinimumWidth(440)
        target = target or {}

        self.kind = QComboBox()
        for _, name in KINDS:
            self.kind.addItem(name)
        self.stack = QStackedWidget()

        # Installed printer
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.printer = QComboBox()
        self.printer.setEditable(True)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._load_printers)
        lay.addWidget(self.printer, 1)
        lay.addWidget(refresh)
        self.stack.addWidget(page)
        self._load_printers()
        if target.get("printer"):
            self.printer.setCurrentText(target["printer"])

        # Network
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.host = QLineEdit(target.get("host", ""))
        self.host.setPlaceholderText("e.g. 192.168.1.50")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(target.get("port", 9100)) if target.get("kind") == "network" else 9100)
        form.addRow("IP address", self.host)
        form.addRow("Port", self.port)
        self.stack.addWidget(page)

        # Serial
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.serial_port = QComboBox()
        self.serial_port.setEditable(True)
        self.serial_port.addItems(printing.list_serial_ports())
        if target.get("kind") == "serial":
            self.serial_port.setCurrentText(target.get("port", ""))
        self.baud = QComboBox()
        self.baud.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baud.setCurrentText(str(target.get("baud", 9600)))
        form.addRow("Port", self.serial_port)
        form.addRow("Baud rate", self.baud)
        self.stack.addWidget(page)

        # File
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        self.path = QLineEdit(target.get("path", ""))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        lay.addWidget(self.path, 1)
        lay.addWidget(browse)
        self.stack.addWidget(page)

        # Mock printer
        page = QLabel("No printer needed: watch the labels come out of an animated printer, with the "
                      "real text, barcodes and records. Handy for checking a job before using real labels.")
        page.setWordWrap(True)
        page.setStyleSheet("color: #555;")
        self.stack.addWidget(page)

        self.kind.currentIndexChanged.connect(self.stack.setCurrentIndex)
        kinds = [k for k, _ in KINDS]
        self.kind.setCurrentIndex(kinds.index(target["kind"]) if target.get("kind") in kinds else 0)
        self.stack.setCurrentIndex(self.kind.currentIndex())

        self.copies_box = QSpinBox()
        self.copies_box.setRange(1, 99999)
        self.copies_box.setValue(copies)

        form = QFormLayout()
        form.addRow("Connection", self.kind)
        form.addRow("", self.stack)
        self.records = records
        if records and not setup_only:
            form.addRow(self._records_box(records))
        if not setup_only:
            form.addRow(copies_label or ("Copies per record" if records else "Copies"), self.copies_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save" if setup_only else "Print")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(buttons)

    def _records_box(self, info):
        box = QGroupBox("Records")
        grid = QGridLayout(box)
        n = info["count"]
        self.r_all = QRadioButton(f"All records ({n})")
        self.r_current = QRadioButton(f"Current record (#{info['current'] + 1})")
        self.r_selected = QRadioButton(f"Selected rows ({len(info['selected'])})")
        self.r_selected.setEnabled(len(info["selected"]) > 1)
        self.r_range = QRadioButton("From record")
        self.r_all.setChecked(True)
        self.range_from = QSpinBox()
        self.range_to = QSpinBox()
        for s in (self.range_from, self.range_to):
            s.setRange(1, n)
            s.valueChanged.connect(lambda _: self.r_range.setChecked(True))
        self.range_from.setValue(1)
        self.range_to.setValue(n)
        self.r_all.setChecked(True)
        rng = QHBoxLayout()
        rng.addWidget(self.r_range)
        rng.addWidget(self.range_from)
        rng.addWidget(QLabel("to"))
        rng.addWidget(self.range_to)
        rng.addStretch(1)
        self.qty_column = QComboBox()
        self.qty_column.addItem("(none - use Copies per record)")
        self.qty_column.addItems(info["columns"])
        self.qty_column.setToolTip("Take the number of labels for each record from this column")
        grid.addWidget(self.r_all, 0, 0)
        grid.addWidget(self.r_current, 0, 1)
        grid.addWidget(self.r_selected, 1, 0)
        grid.addLayout(rng, 1, 1)
        q = QHBoxLayout()
        q.addWidget(QLabel("Quantity from column"))
        q.addWidget(self.qty_column, 1)
        grid.addLayout(q, 2, 0, 1, 2)
        return box

    def record_indices(self):
        info = self.records
        if not info:
            return [None]
        if self.r_current.isChecked():
            return [info["current"]]
        if self.r_selected.isChecked():
            return list(info["selected"])
        if self.r_range.isChecked():
            a, b = sorted((self.range_from.value(), self.range_to.value()))
            return list(range(a - 1, b))
        return list(range(info["count"]))

    def quantity_column(self):
        if not self.records or self.qty_column.currentIndex() <= 0:
            return None
        return self.qty_column.currentText()

    def _load_printers(self):
        current = self.printer.currentText()
        self.printer.clear()
        names = printing.list_printers()
        self.printer.addItems(names)
        if current:
            self.printer.setCurrentText(current)
        elif printing.default_printer() in names:
            self.printer.setCurrentText(printing.default_printer())

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save printer file", self.path.text() or "label.prn",
                                              "Printer files (*.prn);;All files (*)")
        if path:
            self.path.setText(path)

    def _accept(self):
        t = self.target()
        missing = {"windows": "printer", "cups": "printer", "network": "host",
                   "serial": "port", "file": "path", "mock": None}[t["kind"]]
        if missing and not str(t.get(missing, "")).strip():
            {"printer": self.printer, "host": self.host, "port": self.serial_port,
             "path": self.path}[missing].setFocus()
            return
        self.accept()

    def target(self):
        kind = KINDS[self.kind.currentIndex()][0]
        if kind in ("windows", "cups"):
            return {"kind": kind, "printer": self.printer.currentText().strip()}
        if kind == "network":
            return {"kind": kind, "host": self.host.text().strip(), "port": self.port.value()}
        if kind == "serial":
            return {"kind": kind, "port": self.serial_port.currentText().strip(),
                    "baud": int(self.baud.currentText())}
        if kind == "mock":
            return {"kind": kind}
        return {"kind": kind, "path": self.path.text().strip()}

    def copies(self):
        return self.copies_box.value()
