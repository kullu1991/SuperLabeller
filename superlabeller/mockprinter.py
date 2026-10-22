"""Mock printer: an animation of the labels coming out of a printer, for testing without hardware.

Each row of labels is rendered exactly as it would print (same records, same designs), then fed out of
a cartoon printer one dot-line at a time, torn off and dropped onto a pile.
"""
import math
import random

from PyQt5.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                         QRadialGradient)
from PyQt5.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
                             QWidget)

from . import render, tspl
from .merge import merge_doc
from .model import column_doc, column_offset_dots, columns, dpm, label_size_dots, media_width_mm

LINER = QColor(236, 228, 205)
FALL_TIME = 0.7     # seconds for a torn-off label to land on the pile
TEAR_PAUSE = 0.25   # seconds the printer waits before the next label
PILE_SIZE = 14      # labels kept visible on the pile


def build_row(doc, row, records):
    """Image of one printed row (all labels across, on transparent liner) and its TSPL text lines."""
    label = doc["label"]
    k = dpm(label)
    n = columns(label)
    lw, lh = label_size_dots(label)
    width = int(round(media_width_mm(label) * k))
    img = QImage(width, lh, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    count = max(1, len(records))
    docs = []
    for c in range(n):
        x = column_offset_dots(label, c)
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, 0, lw, lh), 1.5 * k, 1.5 * k)
        p.fillPath(path, Qt.white)
        if c >= len(row):
            docs.append(None)  # part-filled last row: this label stays blank
            continue
        s = row[c]
        d = merge_doc(column_doc(doc, c), records[s] if s is not None else None, s or 0, count)
        docs.append(d)
        # Thermal print look: pure black dots.
        printed = render.render_label(d).convertToFormat(QImage.Format_Mono, Qt.ThresholdDither)
        p.save()
        p.setClipPath(path)
        p.drawImage(x, 0, printed.convertToFormat(QImage.Format_ARGB32))
        p.restore()
    p.end()
    try:
        lines = tspl.to_text(tspl.body(docs, 1)).splitlines()
    except Exception:
        lines = ["CLS", "PRINT 1,1"]
    return img, lines


class MockPrinterView(QWidget):
    status = pyqtSignal(str)
    finished = pyqtSignal(int)  # labels printed

    def __init__(self, doc, slots, records, parent=None):
        super().__init__(parent)
        self.doc, self.records = doc, records
        self.label = doc["label"]
        n = columns(self.label)
        self.rows = [tuple(slots[i:i + n]) for i in range(0, len(slots), n)]
        self.total_labels = len(slots)
        self.row_h = self.label["height_mm"]
        self.gap = self.label["gap_mm"] if self.label["media"] != "continuous" else 0.0
        self.gap = max(self.gap, 1.0)
        self.media_w = media_width_mm(self.label)

        self.cur = 0            # row being printed
        self.pos = 0.0          # mm of the current row fed out of the slot
        self.wait = 0.0         # tear-off pause
        self.speed = 30.0       # mm per second
        self.paused = False
        self.fast = False
        self.done = False
        self.printed = 0
        self.falling, self.pile = [], []
        self._cache = {}
        self._rng = random.Random(7)
        self.setMinimumSize(760, 600)

        self.clock = QElapsedTimer()
        self.clock.start()
        self._last = 0
        self._t = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._announce()

    # ------------------------------------------------------------------ data
    def _row(self, i):
        key = self.rows[i]
        if key not in self._cache:
            if len(self._cache) > 40:
                self._cache.clear()
            self._cache[key] = build_row(self.doc, key, self.records)
        return self._cache[key]

    def _labels_in_row(self, i):
        return len(self.rows[i])

    def _announce(self):
        if self.done:
            self.status.emit(f"Done - {self.printed} label(s) printed on the mock printer.")
            return
        row = self.rows[self.cur]
        recs = [f"#{s + 1}" for s in row if s is not None]
        rec_text = f"  -  record {', '.join(dict.fromkeys(recs))}" if recs else ""
        first = self.printed + 1
        last = self.printed + self._labels_in_row(self.cur)
        which = f"label {first}" if first == last else f"labels {first}-{last}"
        self.status.emit(f"Printing {which} of {self.total_labels}{rec_text}")

    # ------------------------------------------------------------------ animation
    def _tick(self):
        now = self.clock.elapsed()
        dt = min(0.05, (now - self._last) / 1000.0)
        self._last = now
        self._t += dt
        if not self.paused:
            self._advance(dt)
        for f in self.falling:
            f["t"] += dt * (4 if self.fast else 1)
        landed = [f for f in self.falling if f["t"] >= FALL_TIME]
        for f in landed:
            self.falling.remove(f)
            self.pile.append(f)
            del self.pile[:-PILE_SIZE]
        self.update()

    def _advance(self, dt):
        if self.done:
            return
        if self.wait > 0:
            self.wait -= dt * (6 if self.fast else 1)
            return
        speed = self.speed * (25 if self.fast else 1)
        self.pos += speed * dt
        if self.pos >= self.row_h + self.gap:
            self._tear()

    def _tear(self):
        img, _ = self._row(self.cur)
        self.falling.append({
            "img": img, "t": 0.0,
            "dx": self._rng.uniform(-60, 60), "dy": self._rng.uniform(-14, 14),
            "angle": self._rng.uniform(-14, 14),
        })
        self.printed += self._labels_in_row(self.cur)
        self.cur += 1
        self.pos = 0.0
        self.wait = TEAR_PAUSE
        if self.cur >= len(self.rows):
            self.done = True
            self.finished.emit(self.printed)
        self._announce()

    def set_speed(self, mm_per_s):
        self.speed = float(mm_per_s)

    def finish_now(self):
        self.fast = True

    # ------------------------------------------------------------------ painting
    def _scale(self):
        """Pixels per mm so the strip fits nicely."""
        return max(0.5, min(self.width() * 0.5 / self.media_w, 200.0 / (self.row_h + self.gap)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor(214, 220, 228))
        bg.setColorAt(1, QColor(150, 158, 170))
        p.fillRect(self.rect(), bg)
        # desk
        p.fillRect(QRectF(0, h - 70, w, 70), QColor(120, 98, 78))
        p.fillRect(QRectF(0, h - 70, w, 4), QColor(150, 124, 100))

        s = self._scale()
        strip_w = self.media_w * s
        cx = w * 0.40  # printer left of centre; the data panel sits on the right
        body = QRectF(cx - strip_w / 2 - 80, 18, strip_w + 160, 128)
        slot_y = body.bottom()

        self._draw_pile(p, s, cx, h)
        self._draw_strip(p, s, cx, slot_y, strip_w)
        self._draw_printer(p, body, strip_w, slot_y)
        for f in self.falling:
            self._draw_falling(p, f, s, cx, slot_y, h)
        self._draw_ticker(p, w, slot_y)

    def _draw_piece(self, p, img, s, liner=True):
        """A torn-off row: liner gap on top, then the labels. Origin = top-left of the piece."""
        pw = self.media_w * s
        if liner:
            p.fillRect(QRectF(0, 0, pw, (self.gap + self.row_h) * s), LINER)
        p.drawImage(QRectF(0, self.gap * s, pw, self.row_h * s), img)

    def _draw_strip(self, p, s, cx, slot_y, strip_w):
        if self.done or self.cur >= len(self.rows):
            return
        img, _ = self._row(self.cur)
        left = cx - strip_w / 2
        visible = min(self.pos, self.row_h + self.gap)
        p.save()
        p.setClipRect(QRectF(left - 2, slot_y, strip_w + 4, visible * s + 2))
        p.fillRect(QRectF(left, slot_y, strip_w, visible * s), LINER)
        # The bottom edge of the label leaves the printer first; the head prints line by line.
        top = slot_y + (self.pos - self.row_h) * s
        p.drawImage(QRectF(left, top, strip_w, self.row_h * s), img)
        p.restore()
        printing = self.pos < self.row_h and not self.paused and self.wait <= 0
        if printing:  # glowing print head line
            for i, a in enumerate((40, 70, 140, 230)):
                p.setPen(QPen(QColor(255, 120 + i * 25, 40, a), 7 - i * 1.6))
                p.drawLine(QPointF(left - 4, slot_y + 1), QPointF(left + strip_w + 4, slot_y + 1))

    def _draw_printer(self, p, body, strip_w, slot_y):
        # shadow + body
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(body.translated(5, 6), 18, 18)
        grad = QLinearGradient(body.topLeft(), body.bottomLeft())
        grad.setColorAt(0, QColor(88, 96, 110))
        grad.setColorAt(1, QColor(48, 54, 64))
        p.setBrush(grad)
        p.drawRoundedRect(body, 18, 18)
        lid = QRectF(body.left() + 10, body.top() + 8, body.width() - 20, 46)
        p.setBrush(QColor(66, 74, 88))
        p.drawRoundedRect(lid, 12, 12)
        p.setPen(QColor(205, 212, 222))
        f = QFont("Arial", 11, QFont.Bold)
        p.setFont(f)
        p.drawText(lid.adjusted(16, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   f"SUPER LABELLER  MOCK-{self.label['dpi']}")
        # LCD
        lcd = QRectF(body.right() - 190, body.top() + 64, 150, 34)
        p.setPen(QPen(QColor(30, 34, 40), 2))
        p.setBrush(QColor(150, 190, 120))
        p.drawRoundedRect(lcd, 4, 4)
        p.setPen(QColor(30, 50, 25))
        p.setFont(QFont("Consolas", 10, QFont.Bold))
        if self.done:
            text = f"READY   {self.printed}/{self.total_labels}"
        elif self.paused:
            text = "PAUSED"
        else:
            text = f"PRINTING {min(self.printed + 1, self.total_labels)}/{self.total_labels}"
        p.drawText(lcd, Qt.AlignCenter, text)
        # LED: blinking green while printing, steady when done, amber when paused
        if self.paused:
            on, color = True, QColor(255, 180, 40)
        elif self.done:
            on, color = True, QColor(80, 220, 100)
        else:
            on, color = int(self._t * 4) % 2 == 0, QColor(80, 220, 100)
        led_c = QPointF(body.left() + 34, body.top() + 82)
        if on:
            glow = QRadialGradient(led_c, 16)
            glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 160))
            glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(led_c, 16, 16)
        p.setBrush(color if on else QColor(40, 60, 45))
        p.setPen(QPen(QColor(20, 20, 20), 1))
        p.drawEllipse(led_c, 6, 6)
        # feed button
        p.setBrush(QColor(110, 118, 132))
        p.drawRoundedRect(QRectF(body.left() + 54, body.top() + 72, 44, 20), 6, 6)
        p.setPen(QColor(220, 225, 232))
        p.setFont(QFont("Arial", 7, QFont.Bold))
        p.drawText(QRectF(body.left() + 54, body.top() + 72, 44, 20), Qt.AlignCenter, "FEED")
        # paper slot
        slot = QRectF(body.center().x() - strip_w / 2 - 12, slot_y - 9, strip_w + 24, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 17, 20))
        p.drawRoundedRect(slot, 3, 3)

    def _pile_origin(self, s, cx, h):
        ps = s * 0.75
        piece_h = (self.row_h + self.gap) * ps
        return ps, QPointF(cx - self.media_w * ps / 2, h - 58 - piece_h)

    def _draw_pile(self, p, s, cx, h):
        ps, origin = self._pile_origin(s, cx, h)
        for i, f in enumerate(self.pile):
            self._draw_at(p, f["img"], ps, origin + QPointF(f["dx"], f["dy"] - i * 1.2), f["angle"])

    def _draw_falling(self, p, f, s, cx, slot_y, h):
        ps, end = self._pile_origin(s, cx, h)
        t = min(1.0, f["t"] / FALL_TIME)
        e = t * t  # gravity-ish ease in
        start = QPointF(cx - self.media_w * s / 2, slot_y)
        target = end + QPointF(f["dx"], f["dy"] - len(self.pile) * 1.2)
        pos = start + (target - start) * e
        scale = s + (ps - s) * t
        wobble = math.sin(t * math.pi * 2) * 6 * (1 - t)
        self._draw_at(p, f["img"], scale, pos, f["angle"] * t + wobble)

    def _draw_at(self, p, img, scale, top_left, angle):
        pw = self.media_w * scale
        ph = (self.row_h + self.gap) * scale
        p.save()
        p.translate(top_left + QPointF(pw / 2, ph / 2))
        p.rotate(angle)
        p.translate(-pw / 2, -ph / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRect(QRectF(3, 4, pw, ph))
        self._draw_piece(p, img, scale)
        p.restore()

    def _draw_ticker(self, p, w, top):
        """The TSPL the 'printer' received for the current row, appearing as it prints."""
        if self.done or self.cur >= len(self.rows):
            lines = ["", "-- job complete --"]
        else:
            _, all_lines = self._row(self.cur)
            frac = min(1.0, self.pos / max(0.1, self.row_h))
            lines = all_lines[:max(1, int(math.ceil(len(all_lines) * frac)))]
        box = QRectF(w * 0.71, top + 14, w * 0.29 - 12, 12 * 15 + 22)
        chars = max(12, int((box.width() - 40) / 6.2))
        lines = [ln if len(ln) <= chars else ln[:chars - 3] + "..." for ln in lines][-12:]
        p.setPen(QPen(QColor(30, 40, 30), 1))
        p.setBrush(QColor(12, 20, 14, 215))
        p.drawRoundedRect(box, 6, 6)
        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(110, 230, 130))
        p.drawText(box.adjusted(8, 4, -8, 0), Qt.AlignTop | Qt.AlignLeft, "RX  " + "\n    ".join(lines))


class MockPrinterDialog(QDialog):
    def __init__(self, parent, doc, slots, records):
        super().__init__(parent)
        self.setWindowTitle("Mock printer")
        self.resize(980, 760)
        self.view = MockPrinterView(doc, slots, records, self)
        self.status = QLabel()
        self.status.setStyleSheet("font-weight: bold;")
        self.view.status.connect(self.status.setText)
        self.view._announce()

        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(5, 200)
        self.speed.setValue(30)
        self.speed.setFixedWidth(160)
        self.speed_label = QLabel()
        self.speed.valueChanged.connect(self._speed)
        self.real = QCheckBox(f"Real speed ({doc['label']['speed']:g} ips)")
        self.real.toggled.connect(lambda on: self._speed(self.speed.value()))
        self._speed(self.speed.value())

        self.pause = QPushButton("Pause")
        self.pause.clicked.connect(self._toggle_pause)
        finish = QPushButton("Finish now")
        finish.clicked.connect(self.view.finish_now)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.view.finished.connect(lambda n: (self.pause.setEnabled(False), finish.setEnabled(False)))

        row = QHBoxLayout()
        row.addWidget(QLabel("Speed"))
        row.addWidget(self.speed)
        row.addWidget(self.speed_label)
        row.addWidget(self.real)
        row.addStretch(1)
        row.addWidget(self.pause)
        row.addWidget(finish)
        row.addWidget(close)
        root = QVBoxLayout(self)
        root.addWidget(self.view, 1)
        root.addWidget(self.status)
        root.addLayout(row)

    def _speed(self, value):
        if self.real.isChecked():
            mm = self.view.label["speed"] * 25.4
            self.speed.setEnabled(False)
        else:
            mm = value
            self.speed.setEnabled(True)
        self.view.set_speed(mm)
        self.speed_label.setText(f"{mm:.0f} mm/s")

    def _toggle_pause(self):
        self.view.paused = not self.view.paused
        self.pause.setText("Resume" if self.view.paused else "Pause")
