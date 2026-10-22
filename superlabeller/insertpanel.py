"""Left column: label summary, element palette and data fields."""
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QListWidget, QPushButton, QToolButton, QVBoxLayout, QWidget)

from .merge import SPECIAL_FIELDS
from .model import ELEMENT_NAMES

PALETTE = ["text", "barcode", "qr", "image", "box", "line", "ellipse"]
JOINERS = [("New line", "\n"), ("Space", " "), ("Comma  ,", ", "), ("Semicolon  ;", ";"),
           ("Pipe  |", "|"), ("Tab", "\t"), ("Dash  -", " - "), ("Nothing", "")]
SPECIAL_HELP = {"_row": "record number", "_count": "number of records",
                "_date": "today's date", "_time": "current time"}
INK = QColor(45, 55, 70)


def element_icon(kind, size=32):
    """Small drawn icon for an element type."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 32.0
    p.scale(s, s)
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    if kind == "text":
        f = QFont("Times New Roman")
        f.setPixelSize(28)
        f.setBold(True)
        p.setFont(f)
        p.setPen(INK)
        p.drawText(QRectF(0, 0, 32, 32), Qt.AlignCenter, "T")
    elif kind == "barcode":
        x = 4
        for w in (2, 1, 3, 1, 2, 1, 1, 3, 2, 1):
            p.drawRect(QRectF(x, 6, w, 20))
            x += w + 1.2
    elif kind == "qr":
        for x, y in ((4, 4), (19, 4), (4, 19)):
            p.setBrush(INK)
            p.drawRect(QRectF(x, y, 9, 9))
            p.setBrush(Qt.white)
            p.drawRect(QRectF(x + 2, y + 2, 5, 5))
            p.setBrush(INK)
            p.drawRect(QRectF(x + 3, y + 3, 3, 3))
        for x, y in ((19, 19), (24, 24), (19, 25), (25, 19), (15, 15)):
            p.drawRect(QRectF(x, y, 3, 3))
    elif kind == "image":
        p.setPen(QPen(INK, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(3, 6, 26, 20), 2, 2)
        path = QPainterPath(QPointF(5, 24))
        path.lineTo(13, 14)
        path.lineTo(19, 20)
        path.lineTo(22, 17)
        path.lineTo(27, 24)
        p.setPen(Qt.NoPen)
        p.setBrush(INK)
        p.drawPath(path)
        p.drawEllipse(QPointF(22, 11), 2.5, 2.5)
    elif kind == "box":
        p.setPen(QPen(INK, 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(4, 7, 24, 18), 2, 2)
    elif kind == "line":
        p.setPen(QPen(INK, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(4, 16), QPointF(28, 16))
    elif kind == "ellipse":
        p.setPen(QPen(INK, 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(4, 6, 24, 20))
    p.end()
    return QIcon(pm)


ARRANGE = [
    ("left", "Align Left"), ("hcenter", "Align Centers"), ("right", "Align Right"),
    ("top", "Align Top"), ("vcenter", "Align Middles"), ("bottom", "Align Bottom"),
    ("dist_h", "Distribute Horizontally"), ("dist_v", "Distribute Vertically"),
]


def arrange_icon(kind, size=24):
    """Icons for align / distribute. Vertical variants are the horizontal ones turned 90°."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    base = {"top": "left", "vcenter": "hcenter", "bottom": "right", "dist_v": "dist_h"}.get(kind, kind)
    if base != kind:
        p.translate(24, 0)
        p.rotate(90)
    guide = QPen(QColor(0, 120, 215), 1.6)
    p.setBrush(INK)
    if base == "dist_h":
        p.setPen(guide)
        p.drawLine(QPointF(2, 3), QPointF(2, 21))
        p.drawLine(QPointF(22, 3), QPointF(22, 21))
        p.setPen(Qt.NoPen)
        for x, w in ((4, 4), (10, 4), (16, 4)):
            p.drawRect(QRectF(x, 7, w, 10))
    else:
        bars = [(14, 5), (8, 13)]  # (length, y)
        for length, y in bars:
            x = {"left": 4, "right": 20 - length, "hcenter": 12 - length / 2}[base]
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(x, y, length, 5))
        lx = {"left": 3, "right": 21, "hcenter": 12}[base]
        p.setPen(guide)
        p.drawLine(QPointF(lx, 2), QPointF(lx, 22))
    p.end()
    return QIcon(pm)


def printer_icon(size=32):
    """A label printer: body, paper slot and a label coming out."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 32.0, size / 32.0)
    body = QColor(60, 72, 90)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(245, 245, 245))
    p.setPen(QPen(QColor(120, 125, 135), 1))
    p.drawRect(QRectF(9, 3, 14, 10))              # paper going in at the back
    p.setPen(Qt.NoPen)
    p.setBrush(body)
    p.drawRoundedRect(QRectF(3, 11, 26, 13), 3, 3)  # printer body
    p.setBrush(QColor(110, 200, 120))
    p.drawEllipse(QPointF(24.5, 15), 1.6, 1.6)      # status light
    p.setBrush(QColor(30, 36, 46))
    p.drawRect(QRectF(7, 19, 18, 2))                # output slot
    p.setBrush(Qt.white)
    p.setPen(QPen(QColor(120, 125, 135), 1))
    p.drawRect(QRectF(9, 20, 14, 10))               # printed label coming out
    p.setPen(QPen(QColor(60, 72, 90), 1.2))
    for y in (23, 25.5):
        p.drawLine(QPointF(11, y), QPointF(21 if y == 23 else 17, y))
    p.end()
    return QIcon(pm)


class InsertPanel(QWidget):
    insert = pyqtSignal(str)          # element type
    label_setup = pyqtSignal()
    insert_field = pyqtSignal(str)    # placeholder text ("{A}" or "{A}<sep>{B}") for the selected element
    add_field_text = pyqtSignal(str)  # new text element with that placeholder text

    def __init__(self, parent=None):
        super().__init__(parent)

        # ---- label summary
        label_box = QGroupBox("Label")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        setup = QPushButton("Label setup...")
        setup.clicked.connect(self.label_setup)
        lay = QVBoxLayout(label_box)
        lay.addWidget(self.summary)
        lay.addWidget(setup)

        # ---- element palette
        insert_box = QGroupBox("Insert")
        grid = QGridLayout(insert_box)
        grid.setSpacing(4)
        for i, kind in enumerate(PALETTE):
            b = QToolButton()
            b.setText(ELEMENT_NAMES[kind])
            b.setIcon(element_icon(kind))
            b.setIconSize(QSize(28, 28))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setAutoRaise(True)
            b.setMinimumSize(78, 58)
            b.setToolTip(f"Add {ELEMENT_NAMES[kind].lower()} to the label")
            b.clicked.connect(lambda _=False, k=kind: self.insert.emit(k))
            grid.addWidget(b, i // 3, i % 3)

        # ---- data fields
        fields_box = QGroupBox("Data fields")
        self.fields_hint = QLabel()
        self.fields_hint.setWordWrap(True)
        self.fields_hint.setStyleSheet("color: #555;")
        self.fields = QListWidget()
        self.fields.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.fields.setToolTip("Ctrl+click or Shift+click to pick several fields.\n"
                               "Double-click inserts into the selected text, barcode or QR code.")
        self.fields.itemDoubleClicked.connect(lambda _: self._emit(self.insert_field))

        self.joiner = QComboBox()
        self.joiner.setEditable(True)
        self.joiner.setInsertPolicy(QComboBox.NoInsert)
        for text, sep in JOINERS:
            self.joiner.addItem(text, sep)
        self.joiner.setToolTip("Separator placed between several fields. Pick one or type your own "
                               "(\\n = new line, \\t = tab).")
        self.with_names = QCheckBox("Include field names  (SKU: {SKU})")
        join_row = QHBoxLayout()
        join_row.addWidget(QLabel("Separator"))
        join_row.addWidget(self.joiner, 1)

        b_insert = QPushButton("Insert into selected")
        b_insert.clicked.connect(lambda: self._emit(self.insert_field))
        b_add = QPushButton("Add as text")
        b_add.clicked.connect(lambda: self._emit(self.add_field_text))
        row = QHBoxLayout()
        row.addWidget(b_insert)
        row.addWidget(b_add)
        lay = QVBoxLayout(fields_box)
        lay.addWidget(self.fields_hint)
        lay.addWidget(self.fields, 1)
        lay.addLayout(join_row)
        lay.addWidget(self.with_names)
        lay.addLayout(row)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(label_box)
        root.addWidget(insert_box)
        root.addWidget(fields_box, 1)
        self.set_fields([], None)

    def separator(self):
        i = self.joiner.currentIndex()
        if i >= 0 and self.joiner.currentText() == self.joiner.itemText(i):
            return self.joiner.itemData(i)
        return self.joiner.currentText().replace("\\n", "\n").replace("\\t", "\t")

    def placeholder_text(self):
        """Selected fields as {Field} placeholders, in list order, joined by the separator."""
        names = [it.data(Qt.UserRole) for it in
                 sorted(self.fields.selectedItems(), key=lambda it: self.fields.row(it))]
        if not names:
            return ""
        parts = [f"{n}: {{{n}}}" if self.with_names.isChecked() else f"{{{n}}}" for n in names]
        return self.separator().join(parts)

    def _emit(self, signal):
        text = self.placeholder_text()
        if text:
            signal.emit(text)

    def set_summary(self, text):
        self.summary.setText(text)

    def set_fields(self, columns, description):
        self.fields.clear()
        for name in list(columns) + SPECIAL_FIELDS:
            text = f"{name}   ({SPECIAL_HELP[name]})" if name in SPECIAL_HELP else name
            self.fields.addItem(text)
            self.fields.item(self.fields.count() - 1).setData(Qt.UserRole, name)
        if description:
            self.fields_hint.setText(f"From <b>{description}</b>. Fields appear as {{Name}} and are "
                                     "filled from each record when printing.")
        else:
            self.fields_hint.setText("To print from Excel, CSV or a database, use "
                                     "<b>Data &gt; Data Source...</b>")
