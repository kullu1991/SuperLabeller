"""Schema-driven property editors for elements and the label setup."""
from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFontComboBox, QFormLayout, QGridLayout,
                             QGroupBox, QLabel, QToolButton,
                             QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
                             QWidget)

from .model import ELEMENT_NAMES, SCHEMAS


class _NoWheelUnlessFocused(QObject):
    """Stop spin boxes and combos changing value when the panel is scrolled."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return False


class FieldForm(QWidget):
    changed = pyqtSignal(str)          # key of the field the user edited
    button_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.obj = None
        self._rows = {}
        self._loading = False
        self._wheel = _NoWheelUnlessFocused(self)
        self._form = QFormLayout(self)
        self._form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_target(self, obj, schema):
        while self._form.rowCount():
            self._form.removeRow(0)
        self._rows = {}
        self.obj = obj
        if obj is None:
            return
        for f in schema:
            editor = self._make_editor(f)
            lab = QLabel(f["label"])
            if f.get("tip"):
                lab.setToolTip(f["tip"])
                editor.setToolTip(f["tip"])
            self._form.addRow(lab, editor)
            self._rows[f["key"]] = (lab, editor, f)
        self.refresh_values()
        self._update_visibility()

    # ----------------------------------------------------------------- editors
    def _make_editor(self, f):
        kind, key = f["kind"], f["key"]
        if kind in ("mm", "float"):
            w = QDoubleSpinBox()
            w.setRange(f.get("min", 0), f.get("max", 1000))
            w.setDecimals(f.get("decimals", 2))
            w.setSingleStep(f.get("step", 0.5 if kind == "mm" else 1))
            w.setSuffix(f.get("suffix", " mm" if kind == "mm" else ""))
            w.valueChanged.connect(lambda v, k=key: self._set(k, round(v, 3)))
        elif kind == "int":
            w = QSpinBox()
            w.setRange(f.get("min", 0), f.get("max", 1000))
            w.setSuffix(f.get("suffix", ""))
            w.valueChanged.connect(lambda v, k=key: self._set(k, int(v)))
        elif kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda v, k=key: self._set(k, bool(v)))
        elif kind == "choice":
            w = QComboBox()
            w.values = [v for v, _ in f["options"]]
            for _, text in f["options"]:
                w.addItem(text)
            w.currentIndexChanged.connect(lambda i, k=key, c=w: i >= 0 and self._set(k, c.values[i]))
        elif kind == "str":
            w = QLineEdit()
            w.textChanged.connect(lambda v, k=key: self._set(k, v))
        elif kind == "text":
            w = QPlainTextEdit()
            w.setFixedHeight(72)
            w.textChanged.connect(lambda k=key, c=w: self._set(k, c.toPlainText()))
        elif kind == "font":
            w = QFontComboBox()
            w.currentFontChanged.connect(lambda font, k=key: self._set(k, font.family()))
        elif kind == "button":
            w = QPushButton(f.get("text", "..."))
            w.clicked.connect(lambda _=False, k=key: self.button_clicked.emit(k))
        else:
            raise ValueError(kind)
        if kind in ("mm", "float", "int", "choice", "font"):
            w.setFocusPolicy(Qt.StrongFocus)
            w.installEventFilter(self._wheel)
        return w

    def _set(self, key, value):
        if self._loading or self.obj is None:
            return
        self.obj[key] = value
        self._update_visibility()
        self.changed.emit(key)

    def refresh_values(self):
        """Copy values from the target into the editors (without emitting changes)."""
        if self.obj is None:
            return
        self._loading = True
        try:
            for key, (_, w, f) in self._rows.items():
                v = self.obj.get(key)
                kind = f["kind"]
                if kind in ("mm", "float", "int"):
                    if abs(w.value() - v) > 1e-9:
                        w.setValue(v)
                elif kind == "bool":
                    w.setChecked(bool(v))
                elif kind == "choice":
                    idx = next((i for i, cv in enumerate(w.values) if cv == v), -1)
                    if idx != w.currentIndex():
                        w.setCurrentIndex(idx)
                elif kind == "str":
                    if w.text() != v:
                        w.setText(v)
                elif kind == "text":
                    if w.toPlainText() != v:
                        w.setPlainText(v)
                elif kind == "font":
                    if w.currentFont().family() != v:
                        w.setCurrentFont(QFont(v))
        finally:
            self._loading = False
        self._update_visibility()

    def _update_visibility(self):
        for lab, w, f in self._rows.values():
            cond = f.get("when")
            visible = cond(self.obj) if cond else True
            lab.setVisible(visible)
            w.setVisible(visible)


def _scrolled(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class PropertyPanel(QWidget):
    """Properties of the selected element."""
    changed = pyqtSignal(str)
    button_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.element = None
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold; padding: 4px;")
        self.form = FieldForm()
        self.form.changed.connect(self.changed)
        self.form.button_clicked.connect(self.button_clicked)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.form)
        lay.addStretch(1)
        self.arrange_box = QGroupBox("Align && distribute")
        self._arrange_grid = QGridLayout(self.arrange_box)
        self.arrange_box.hide()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(self.title)
        outer.addWidget(self.arrange_box)
        outer.addWidget(_scrolled(inner))
        self.set_element(None)
        self.setMinimumWidth(270)

    def set_arrange_actions(self, actions):
        for i, a in enumerate(actions):
            b = QToolButton()
            b.setDefaultAction(a)
            short = {"dist_h": "Distribute\nacross", "dist_v": "Distribute\ndown"}.get(a.data())
            if short:
                b.setText(short)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setAutoRaise(True)
            b.setMinimumWidth(80)
            self._arrange_grid.addWidget(b, i // 3, i % 3)

    def show_arrange(self, visible):
        self.arrange_box.setVisible(visible)

    def set_element(self, el, message="Nothing selected"):
        if el is not None and el is self.element:
            self.form.refresh_values()
            return
        self.element = el
        if el is None:
            self.title.setText(message)
            self.form.set_target(None, [])
        else:
            self.title.setText(ELEMENT_NAMES[el["type"]])
            self.form.set_target(el, SCHEMAS[el["type"]])

    def refresh_values(self):
        self.form.refresh_values()
