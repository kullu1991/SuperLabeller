"""Label setup wizard: shown for a new label, and from File > Label Setup."""
import copy

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget, QWizard,
                             QWizardPage)

from .forms import FieldForm
from .model import (FILL_HELP, LABEL_ADVANCED_KEYS, LABEL_MEDIA_KEYS, LABEL_PRESETS, LABEL_SIZE_KEYS, columns, label_schema,
                    media_width_mm)


class LabelPreview(QWidget):
    """Proportional drawing of the label size."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.label = label
        self.setMinimumSize(220, 180)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        L = self.label
        w, h = L["width_mm"], L["height_mm"]
        n = columns(L)
        gap, margin = L["column_gap_mm"], L["side_margin_mm"]
        total_w = media_width_mm(L)
        area = QRectF(self.rect()).adjusted(20, 14, -20, -30)
        s = min(area.width() / total_w, area.height() / (h + 4))
        liner = QRectF(0, 0, total_w * s, (h + 4) * s)
        liner.moveCenter(area.center())
        if n > 1 or margin > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(236, 230, 214))
            p.drawRect(liner)
        for col in range(n):
            r = QRectF(liner.left() + (margin + col * (w + gap)) * s, liner.top() + 2 * s, w * s, h * s)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 50))
            p.drawRoundedRect(r.translated(3, 3), 6, 6)
            p.setBrush(Qt.white)
            p.setPen(QPen(QColor(120, 130, 145), 1))
            p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor(60, 60, 60))
        text = f"{w:g} x {h:g} mm"
        if n > 1:
            text += f",  {n} across  (liner {total_w:g} mm wide)"
        p.drawText(QRectF(0, liner.bottom() + 4, self.width(), 22), Qt.AlignHCenter, text)


class LabelSetupWizard(QWizard):
    def __init__(self, parent, label, new=True):
        super().__init__(parent)
        self.label = copy.deepcopy(label)
        self.setWindowTitle("New label" if new else "Label setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.HaveFinishButtonOnEarlyPages, True)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setButtonText(QWizard.FinishButton, "Create label" if new else "Apply")
        self.resize(680, 520)

        # ---- page 1: size
        page = QWizardPage()
        page.setTitle("Label size")
        page.setSubTitle("Pick a common size or enter the size of your labels.")
        self.presets = QListWidget()
        self._preset_items = []
        # Selected whenever the size matches no preset. Without it Qt would make the first preset
        # current when the list gets focus, silently changing a custom size.
        self._custom_item = QListWidgetItem("Custom size (enter width and height)")
        f = self._custom_item.font()
        f.setItalic(True)
        self._custom_item.setFont(f)
        self.presets.addItem(self._custom_item)
        group = None
        for i, (g, name, w, h, gap) in enumerate(LABEL_PRESETS):
            if g != group:
                group = g
                head = QListWidgetItem(g)
                head.setFlags(Qt.NoItemFlags)
                f = head.font()
                f.setBold(True)
                head.setFont(f)
                head.setForeground(QColor(40, 80, 140))
                self.presets.addItem(head)
            item = QListWidgetItem("    " + name)
            item.setData(Qt.UserRole, i)
            self.presets.addItem(item)
            self._preset_items.append(item)
        self.presets.currentItemChanged.connect(self._preset_chosen)
        self.size_form = FieldForm()
        self.size_form.set_target(self.label, label_schema(LABEL_SIZE_KEYS))
        self.size_form.changed.connect(self._size_changed)
        self.preview = LabelPreview(self.label)
        self.fill_help = QLabel()
        self.fill_help.setWordWrap(True)
        self.fill_help.setStyleSheet("color: #444; padding: 6px; background: #eef4fb; border-radius: 4px;")
        right = QVBoxLayout()
        right.addWidget(self.size_form)
        right.addWidget(self.fill_help)
        right.addWidget(self.preview, 1)
        lay = QHBoxLayout(page)
        lay.addWidget(self.presets, 1)
        lay.addLayout(right, 1)
        self.addPage(page)

        # ---- page 2: media and printing
        page = QWizardPage()
        page.setTitle("Media and printing")
        page.setSubTitle("How the labels are fed and printed.")
        form = FieldForm()
        form.set_target(self.label, label_schema(LABEL_MEDIA_KEYS))
        hint = QLabel("Heat-transfer labels: use <b>Thermal transfer (ribbon)</b>. Tick <b>Mirror image</b> "
                      "for film that is pressed face-down onto fabric. Film and resin ribbons usually "
                      "need darkness 10-15 and speed 2-3 ips.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; padding: 6px; background: #f3f6fa; border-radius: 4px;")
        lay = QVBoxLayout(page)
        lay.addWidget(form)
        lay.addStretch(1)
        lay.addWidget(hint)
        self.addPage(page)

        # ---- page 3: advanced
        page = QWizardPage()
        page.setTitle("Advanced")
        page.setSubTitle("The defaults suit most TSPL printers. Change these only if needed.")
        form = FieldForm()
        form.set_target(self.label, label_schema(LABEL_ADVANCED_KEYS))
        lay = QVBoxLayout(page)
        lay.addWidget(form)
        lay.addStretch(1)
        self.addPage(page)

        for pid in self.pageIds():  # allow finishing from any page
            self.page(pid).setFinalPage(True)
        self._size_changed()

    def _preset_chosen(self, item, _prev=None):
        if item is None or item.data(Qt.UserRole) is None or self._syncing:
            return
        _, _, w, h, gap = LABEL_PRESETS[item.data(Qt.UserRole)]
        self.label.update(width_mm=float(w), height_mm=float(h), gap_mm=float(gap))
        self.size_form.refresh_values()
        self.preview.update()

    def _size_changed(self, key=None):
        self._sync_preset()
        self.preview.update()
        multi = columns(self.label) > 1
        self.fill_help.setVisible(multi)
        if multi:
            self.fill_help.setText("<b>Labels across:</b> " + FILL_HELP[self.label.get("fill", "next")])

    _syncing = False

    def _sync_preset(self):
        self._syncing = True
        try:
            for item in self._preset_items:
                _, _, w, h, _ = LABEL_PRESETS[item.data(Qt.UserRole)]
                if abs(self.label["width_mm"] - w) < 0.01 and abs(self.label["height_mm"] - h) < 0.01:
                    self.presets.setCurrentItem(item)
                    break
            else:
                self.presets.setCurrentItem(self._custom_item)
        finally:
            self._syncing = False
