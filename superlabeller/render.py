"""Drawing of label elements.

The same painting code draws the on-screen preview and rasterises elements
into TSPL BITMAP data, so the screen matches the printed label.
All coordinates here are printer dots, relative to the element's anchor
(its top-left corner before rotation).
"""
import base64
import io
import math
from functools import lru_cache

from PIL import Image, ImageOps
from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QTransform

from .model import BARCODE_PYMAP, dpm, label_size_dots

try:
    import barcode as _pybarcode
except ImportError:  # preview falls back to a placeholder
    _pybarcode = None
try:
    import qrcode as _qrcode
except ImportError:
    _qrcode = None

BLACK = QColor(0, 0, 0)
WHITE = QColor(255, 255, 255)
INVALID = QColor(210, 40, 40)

# Built-in TSPL bitmap fonts at 203 dpi: (char width, char height) in dots.
PRINTER_FONTS = {"1": (8, 12), "2": (12, 20), "3": (16, 24), "4": (24, 32),
                 "5": (32, 48), "6": (14, 19), "7": (21, 27), "8": (14, 25)}
_ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


def rotation(el):
    return int(el.get("rotation", 0)) % 360


def anchor(el, label):
    k = dpm(label)
    return QPointF(round(el["x"] * k), round(el["y"] * k))


def element_transform(el, label):
    a = anchor(el, label)
    t = QTransform()
    t.translate(a.x(), a.y())
    t.rotate(rotation(el))
    return t


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------
def bitmap_font(el, label):
    f = QFont(el["font_family"])
    f.setPixelSize(max(1, round(el["size_pt"] * label["dpi"] / 72)))
    f.setBold(el["bold"])
    f.setItalic(el["italic"])
    f.setUnderline(el["underline"])
    return f


def printer_cell(el, label):
    """Approximate size of one character of a built-in printer font, in dots."""
    if el["printer_font"] == "0":
        h = el["ymul"] * label["dpi"] / 72
        return el["xmul"] * label["dpi"] / 72 * 0.6, h
    w, h = PRINTER_FONTS.get(el["printer_font"], (16, 24))
    s = label["dpi"] / 203
    return w * s * el["xmul"], h * s * el["ymul"]


def _text_flags(el):
    flags = _ALIGN.get(el["align"], Qt.AlignLeft) | Qt.AlignTop
    if el["box_width_mm"] > 0:
        flags |= Qt.TextWordWrap
    return int(flags)


def _text_geom(el, label):
    """Return (outer rect, rect the text is drawn in)."""
    if el["mode"] == "printer":
        cw, ch = printer_cell(el, label)
        lines = el["text"].split("\n")
        w = max(1, max(len(s) for s in lines)) * cw
        r = QRectF(0, 0, round(w), round(len(lines) * ch))
        return r, r
    fm = QFontMetricsF(bitmap_font(el, label))
    text = el["text"] or " "
    bw = el["box_width_mm"] * dpm(label)
    if bw > 0:
        br = fm.boundingRect(QRectF(0, 0, bw, 1e6), int(Qt.AlignLeft | Qt.TextWordWrap), text)
        w = bw
    else:
        br = fm.boundingRect(QRectF(0, 0, 1e6, 1e6), int(Qt.AlignLeft), text)
        w = br.width()
    pad = round(0.6 * dpm(label)) if el["inverse"] else 0
    inner = QRectF(pad, pad, math.ceil(w), math.ceil(br.height()))
    return QRectF(0, 0, inner.width() + 2 * pad, inner.height() + 2 * pad), inner


def _paint_text(p, el, label):
    outer, inner = _text_geom(el, label)
    if el["mode"] == "printer":
        cw, ch = printer_cell(el, label)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        f.setPixelSize(max(1, round(ch * 0.95)))
        fm = QFontMetricsF(f)
        adv = fm.horizontalAdvance("M") or 1.0
        p.setFont(f)
        p.setPen(BLACK)
        for i, line in enumerate(el["text"].split("\n")):
            p.save()
            p.translate(0, i * ch)
            p.scale(cw / adv, 1.0)
            p.drawText(QPointF(0, fm.ascent() + (ch - fm.height()) / 2), line)
            p.restore()
        return
    if el["inverse"]:
        p.fillRect(outer, BLACK)
    p.setFont(bitmap_font(el, label))
    p.setPen(WHITE if el["inverse"] else BLACK)
    p.drawText(inner, _text_flags(el), el["text"])


# --------------------------------------------------------------------------
# Barcodes
# --------------------------------------------------------------------------
_ITF_DIGITS = ["nnwwn", "wnnnw", "nwnnw", "wwnnn", "nnwnw",
               "wnwnn", "nwwnn", "nnnww", "wnnwn", "nwnwn"]


def _itf_runs(data, narrow, wide):
    if not data.isdigit():
        return None
    if len(data) % 2:
        data = "0" + data
    runs = [narrow] * 4                       # start: bar space bar space
    for a, b in zip(data[0::2], data[1::2]):
        for bar, space in zip(_ITF_DIGITS[int(a)], _ITF_DIGITS[int(b)]):
            runs += [wide if bar == "w" else narrow, wide if space == "w" else narrow]
    runs += [wide, narrow, narrow]            # stop: wide bar, space, bar
    return runs


@lru_cache(maxsize=256)
def barcode_runs(sym, data, narrow, wide):
    """Widths in dots of alternating bars and spaces (starting with a bar), or None."""
    name = BARCODE_PYMAP.get(sym)
    if not data or not name:
        return None
    if name == "itf":
        return _itf_runs(data, narrow, wide)
    if _pybarcode is None:
        return None
    try:
        kwargs = {"add_checksum": sym == "39C"} if name == "code39" else {}
        modules = _pybarcode.get_barcode_class(name)(data, **kwargs).build()[0]
    except Exception:
        return None
    runs, prev, count = [], "1", 0
    for m in modules:
        bit = "0" if m == "0" else "1"
        if bit == prev:
            count += 1
        else:
            runs.append(count * narrow)
            prev, count = bit, 1
    runs.append(count * narrow)
    return runs


def _hr_px(label):
    return max(8, round(2.5 * dpm(label)))


def _barcode_geom(el, label):
    data = el["data"].strip()
    runs = barcode_runs(el["symbology"], data, el["narrow"], el["wide"])
    width = sum(runs) if runs else max(30, 11 * len(data) + 35) * el["narrow"]
    bar_h = max(1, round(el["height_mm"] * dpm(label)))
    text_h = _hr_px(label) + 2 if el["readable"] != "none" else 0
    return QRectF(0, 0, width, bar_h + text_h), runs, bar_h


def _paint_barcode(p, el, label):
    rect, runs, bar_h = _barcode_geom(el, label)
    bars = QRectF(0, 0, rect.width(), bar_h)
    if runs is None:
        if el["symbology"] in ("93", "UPCE", "CODA", "MSI") and el["data"].strip():
            # No preview encoder: show a neutral striped placeholder.
            p.fillRect(bars, QBrush(BLACK, Qt.VerPattern))
        else:
            p.fillRect(bars, QBrush(INVALID, Qt.BDiagPattern))
            p.setPen(INVALID)
            p.drawRect(bars)
    else:
        x = 0
        for i, w in enumerate(runs):
            if i % 2 == 0:
                p.fillRect(QRectF(x, 0, w, bar_h), BLACK)
            x += w
    if el["readable"] != "none":
        f = QFont("Arial")
        f.setPixelSize(_hr_px(label))
        p.setFont(f)
        p.setPen(BLACK)
        p.drawText(QRectF(0, bar_h + 2, rect.width(), rect.height() - bar_h),
                   int(_ALIGN[el["readable"]] | Qt.AlignTop), el["data"].strip())


# --------------------------------------------------------------------------
# QR code
# --------------------------------------------------------------------------
@lru_cache(maxsize=128)
def qr_matrix(data, ecc):
    if not data or _qrcode is None:
        return None
    try:
        q = _qrcode.QRCode(error_correction=getattr(_qrcode.constants, "ERROR_CORRECT_" + ecc),
                           box_size=1, border=0)
        q.add_data(data)
        q.make(fit=True)
        return tuple(tuple(bool(c) for c in row) for row in q.get_matrix())
    except Exception:
        return None


def _qr_geom(el):
    m = qr_matrix(el["data"], el["ecc"])
    n = len(m) if m else 21
    return QRectF(0, 0, n * el["cell"], n * el["cell"]), m


def _paint_qr(p, el):
    rect, m = _qr_geom(el)
    if m is None:
        p.fillRect(rect, QBrush(INVALID, Qt.BDiagPattern))
        return
    c = el["cell"]
    for y, row in enumerate(m):
        x = 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                p.fillRect(QRectF(start * c, y * c, (x - start) * c, c), BLACK)
            else:
                x += 1


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
@lru_cache(maxsize=32)
def mono_image(b64, w, h, dither, threshold, invert):
    """Decode, scale and convert an image to the 1-bit look it will print with."""
    if not b64:
        return None
    try:
        im = Image.open(io.BytesIO(base64.b64decode(b64)))
        im.load()
        if im.mode in ("RGBA", "LA", "P", "PA"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            bg.alpha_composite(im)
            im = bg
        im = im.convert("L").resize((w, h), Image.LANCZOS)
        if invert:
            im = ImageOps.invert(im)
        if dither:
            im = im.convert("1")
        else:
            im = im.point(lambda v: 255 if v >= threshold else 0).convert("1", dither=Image.Dither.NONE)
        # Black dots on a transparent background, so anything underneath stays visible.
        alpha = ImageOps.invert(im.convert("L"))
        rgba = Image.merge("RGBA", (Image.new("L", (w, h), 0),) * 3 + (alpha,))
        return QImage(rgba.tobytes(), w, h, w * 4, QImage.Format_RGBA8888).copy()
    except Exception:
        return None


def _paint_image(p, el, label):
    r = local_rect(el, label)
    img = mono_image(el["image"], int(r.width()), int(r.height()),
                     el["dither"], el["threshold"], el["invert"])
    if img is None:
        p.fillRect(r, QBrush(QColor(150, 150, 150), Qt.Dense6Pattern))
        p.setPen(QColor(90, 90, 90))
        p.drawText(r, int(Qt.AlignCenter), "No image")
        return
    p.drawImage(r, img)


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------
def _ring_path(rect, t, radius=0.0, ellipse=False):
    path = QPainterPath()
    inner = rect.adjusted(t, t, -t, -t)
    if ellipse:
        path.addEllipse(rect)
        if inner.width() > 0 and inner.height() > 0:
            path.addEllipse(inner)
    else:
        path.addRoundedRect(rect, radius, radius)
        if inner.width() > 0 and inner.height() > 0:
            r2 = max(0.0, radius - t)
            path.addRoundedRect(inner, r2, r2)
    return path  # QPainterPath defaults to odd-even fill, so the inner shape is a hole


def _thickness(el, label):
    return max(1, round(el["thickness_mm"] * dpm(label)))


def _paint_shape(p, el, label):
    r = local_rect(el, label)
    t = el["type"]
    if t == "line":
        p.fillRect(r, BLACK)
        return
    radius = el.get("radius_mm", 0) * dpm(label)
    ellipse = t == "ellipse"
    if el["filled"]:
        path = QPainterPath()
        if ellipse:
            path.addEllipse(r)
        else:
            path.addRoundedRect(r, radius, radius)
    else:
        path = _ring_path(r, _thickness(el, label), radius, ellipse)
    if radius or ellipse:
        p.fillPath(path, BLACK)
    else:  # sharp boxes: fill exact dot rectangles, no anti-aliased edges
        th = _thickness(el, label)
        if el["filled"]:
            p.fillRect(r, BLACK)
        else:
            for rr in (QRectF(r.x(), r.y(), r.width(), th),
                       QRectF(r.x(), r.bottom() - th, r.width(), th),
                       QRectF(r.x(), r.y(), th, r.height()),
                       QRectF(r.right() - th, r.y(), th, r.height())):
                p.fillRect(rr, BLACK)


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
def local_rect(el, label):
    """Unrotated bounding rect of an element in dots, origin at its anchor."""
    t = el["type"]
    k = dpm(label)
    if t == "text":
        return _text_geom(el, label)[0]
    if t == "barcode":
        return _barcode_geom(el, label)[0]
    if t == "qr":
        return _qr_geom(el)[0]
    if t == "line":
        length = max(1, round(el["length_mm"] * k))
        th = _thickness(el, label)
        return QRectF(0, 0, length, th) if el["orientation"] == "h" else QRectF(0, 0, th, length)
    return QRectF(0, 0, max(1, round(el["w_mm"] * k)), max(1, round(el["h_mm"] * k)))


def paint(p, el, label):
    t = el["type"]
    if t == "text":
        _paint_text(p, el, label)
    elif t == "barcode":
        _paint_barcode(p, el, label)
    elif t == "qr":
        _paint_qr(p, el)
    elif t == "image":
        _paint_image(p, el, label)
    else:
        _paint_shape(p, el, label)


# --------------------------------------------------------------------------
# Rasterising for the printer
# --------------------------------------------------------------------------
def _new_canvas(w, h):
    img = QImage(max(1, w), max(1, h), QImage.Format_RGB32)
    img.fill(WHITE)
    return img


def _begin(img):
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    return p


def render_element(el, label):
    """Rasterise one element. Returns (QRect in label dots, QImage), clipped to the label, or None."""
    t = element_transform(el, label)
    bounds = t.mapRect(local_rect(el, label)).toAlignedRect()
    lw, lh = label_size_dots(label)
    clip = bounds.intersected(QRect(0, 0, lw, lh))
    if clip.isEmpty():
        return None
    img = _new_canvas(clip.width(), clip.height())
    p = _begin(img)
    p.translate(-clip.left(), -clip.top())
    p.setTransform(t, True)
    paint(p, el, label)
    p.end()
    return clip, img


def render_label(doc):
    """Rasterise the whole label into one image."""
    label = doc["label"]
    lw, lh = label_size_dots(label)
    img = _new_canvas(lw, lh)
    p = _begin(img)
    for el in doc["elements"]:
        p.save()
        p.setTransform(element_transform(el, label), True)
        paint(p, el, label)
        p.restore()
    p.end()
    return img


def to_mono_bits(img, zero_black=True, threshold=128):
    """Pack an image as TSPL BITMAP rows: MSB first, rows padded to whole bytes.

    Returns (width in bytes, height, data). With zero_black, a 0 bit prints a dot
    (the TSC convention); padding bits are always white.
    """
    g = img.convertToFormat(QImage.Format_Grayscale8)
    w, h, bpl = g.width(), g.height(), g.bytesPerLine()
    ptr = g.constBits()
    ptr.setsize(bpl * h)
    src = Image.frombuffer("L", (w, h), bytes(ptr), "raw", "L", bpl, 1)
    w8 = (w + 7) // 8 * 8
    padded = Image.new("L", (w8, h), 255)
    padded.paste(src, (0, 0))
    bw = padded.point(lambda v: 255 if v >= threshold else 0)
    if not zero_black:
        bw = ImageOps.invert(bw)
    return w8 // 8, h, bw.convert("1", dither=Image.Dither.NONE).tobytes()
