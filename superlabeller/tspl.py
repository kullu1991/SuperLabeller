"""TSPL / TSPL2 command generation.

build() returns a list of chunks. A chunk is either a command string, or a
(prefix, bytes) tuple for BITMAP commands that carry binary data. to_bytes()
turns the chunks into what is sent to the printer; to_text() makes a readable
listing for the on-screen preview.

Elements the printer can draw itself (printer-font text, barcodes, QR codes,
boxes, lines, ellipses) become native commands. Everything else (bitmap text,
images, filled rounded shapes) is rasterised and sent as BITMAP. Bitmaps are
sent first and native commands after, because BITMAP in overwrite mode would
blank out anything already drawn underneath it.
"""
from PyQt5.QtCore import QPointF, QRect
from PyQt5.QtGui import QTransform

from . import merge, render
from .model import column_doc, column_offset_dots, columns, dpm, label_size_dots, media_width_mm

BITMAP_MODE = 0  # 0 = overwrite, 1 = OR, 2 = XOR
READABLE = {"none": 0, "left": 1, "center": 2, "right": 3}
CRLF = b"\r\n"


def _n(v):
    """Format a number without trailing zeros."""
    return f"{float(v):g}"


def esc(s):
    """Escape a string for use inside TSPL double quotes."""
    return s.replace('"', '\\["]')


def header(label):
    L = label
    out = [f"SIZE {_n(round(media_width_mm(L), 2))} mm,{_n(L['height_mm'])} mm"]
    if L["media"] == "gap":
        out.append(f"GAP {_n(L['gap_mm'])} mm,{_n(L['gap_offset_mm'])} mm")
    elif L["media"] == "bline":
        out.append(f"BLINE {_n(L['gap_mm'])} mm,{_n(L['gap_offset_mm'])} mm")
    else:
        out.append("GAP 0,0")
    out.append(f"DIRECTION {L['direction']},{1 if L['mirror'] else 0}")
    out.append(f"REFERENCE {L['ref_x']},{L['ref_y']}")
    if L["shift_dots"]:
        out.append(f"SHIFT {L['shift_dots']}")
    out.append(f"SPEED {_n(L['speed'])}")
    out.append(f"DENSITY {L['density']}")
    out.append(f"SET RIBBON {'ON' if L['ribbon'] else 'OFF'}")
    action = {"tear": "SET TEAR ON", "peel": "SET PEEL ON", "cutter": "SET CUTTER 1"}.get(L["post_action"])
    if action:
        out.append(action)
    out.append(f"CODEPAGE {L['codepage']}")
    return out


def _native(el, label, dx=0):
    """Native TSPL commands for an element (shifted right by dx dots), or None if it must be a bitmap."""
    t = el["type"]
    k = dpm(label)
    a = render.anchor(el, label)
    x, y = int(a.x()) + dx, int(a.y())
    rot = render.rotation(el)

    if t == "text":
        if el["mode"] != "printer":
            return None
        _, ch = render.printer_cell(el, label)
        turn = QTransform().rotate(rot)
        out = []
        for i, line in enumerate(el["text"].split("\n")):
            if not line:
                continue
            o = turn.map(QPointF(0, i * ch))
            out.append(f'TEXT {round(x + o.x())},{round(y + o.y())},"{el["printer_font"]}",{rot},'
                       f'{el["xmul"]},{el["ymul"]},"{esc(line)}"')
        return out

    if t == "barcode":
        data = " ".join(el["data"].split("\n")).strip()
        if not data:
            return []
        h = max(1, round(el["height_mm"] * k))
        return [f'BARCODE {x},{y},"{el["symbology"]}",{h},{READABLE[el["readable"]]},{rot},'
                f'{el["narrow"]},{el["wide"]},"{esc(data)}"']

    if t == "qr":
        if not el["data"]:
            return []
        data = esc(el["data"]).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\[L]")
        return [f'QRCODE {x},{y},{el["ecc"]},{el["cell"]},A,{rot},"{data}"']

    r = render.local_rect(el, label)
    w, h = int(r.width()), int(r.height())

    if t == "line":
        return [f"BAR {x},{y},{w},{h}"]

    if t == "box":
        th = max(1, round(el["thickness_mm"] * k))
        rad = round(el["radius_mm"] * k)
        if el["filled"]:
            return None if rad else [f"BAR {x},{y},{w},{h}"]
        return [f"BOX {x},{y},{x + w},{y + h},{th}" + (f",{rad}" if rad else "")]

    if t == "ellipse":
        if el["filled"]:
            return None
        th = max(1, round(el["thickness_mm"] * k))
        if w == h:
            return [f"CIRCLE {x},{y},{w},{th}"]
        return [f"ELLIPSE {x},{y},{w},{h},{th}"]

    return None  # images


def _bitmap_chunk(rect, img, label, dx=0):
    wb, h, data = render.to_mono_bits(img, label["bitmap_zero_black"])
    blank = 0xFF if label["bitmap_zero_black"] else 0x00
    if data.count(blank) == len(data):
        return None  # nothing printable
    return (f"BITMAP {rect.left() + dx},{rect.top()},{wb},{h},{BITMAP_MODE},", data)


def build(doc, copies=1, record=None, index=0, count=1):
    """Complete job for one row: every label in the row shows `record`. `copies` = rows."""
    n = columns(doc["label"])
    return header(doc["label"]) + body([merge.merge_doc(column_doc(doc, c), record, index, count)
                                        for c in range(n)], copies)


def body(row, copies=1):
    """CLS ... PRINT for one row of labels.

    `row` holds one already-merged document per label column (None leaves that label blank).
    """
    label = next(d for d in row if d is not None)["label"]
    chunks = ["CLS"]
    bitmaps, native = [], []
    for col, doc in enumerate(row):
        if doc is None:
            continue
        dx = column_offset_dots(label, col)
        if label["full_bitmap"]:
            lw, lh = label_size_dots(label)
            c = _bitmap_chunk(QRect(0, 0, lw, lh), render.render_label(doc), label, dx)
            if c:
                bitmaps.append(c)
            continue
        for el in doc["elements"]:
            cmds = _native(el, label, dx)
            if cmds is None:
                r = render.render_element(el, label)
                c = _bitmap_chunk(*r, label, dx) if r else None
                if c:
                    bitmaps.append(c)
            else:
                native.extend(cmds)
    chunks += bitmaps + native
    chunks.append(f"PRINT 1,{max(1, int(copies))}")
    return chunks


def batch(doc, slots, records, progress=None):
    """Job for many labels.

    slots: one entry per label to print, in order - a record index, or None for "no record".
    Labels fill each row left to right; identical consecutive rows are printed with one PRINT.
    progress(done, total) may return False to cancel (then None is returned).
    """
    label = doc["label"]
    n = columns(label)
    count = max(1, len(records))
    rows = [tuple(slots[i:i + n]) for i in range(0, len(slots), n)]
    designs = [column_doc(doc, c) for c in range(n)]
    chunks = header(label)
    i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1] == rows[i]:
            j += 1
        row = [merge.merge_doc(designs[c], records[s] if s is not None else None, s or 0, count)
               for c, s in enumerate(rows[i])]
        row += [None] * (n - len(row))  # part-filled last row: remaining labels stay blank
        chunks += body(row, j - i + 1)
        i = j + 1
        if progress and progress(i, len(rows)) is False:
            return None
    return chunks


def _encoding(label):
    return "utf-8" if label["codepage"] == "UTF-8" else "cp" + label["codepage"]


def to_bytes(chunks, label):
    enc = _encoding(label)
    out = bytearray()
    for c in chunks:
        if isinstance(c, str):
            out += c.encode(enc, "replace") + CRLF
        else:
            out += c[0].encode("ascii") + c[1] + CRLF
    return bytes(out)


def to_text(chunks):
    return "\n".join(c if isinstance(c, str) else f"{c[0]}<{len(c[1])} bytes of bitmap data>"
                     for c in chunks)


def command(cmd):
    """A single raw command, e.g. 'GAPDETECT', ready to send."""
    return cmd.encode("ascii") + CRLF
