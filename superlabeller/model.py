"""Label document model.

Everything is kept as plain dicts and lists, so a design saves straight to JSON
(.tlabel files) and the property editor can work from a schema.

Units: positions and sizes are in millimetres. Printer-native sizes (barcode
module width, QR cell size, built-in font multipliers) are in printer dots.
"""
import copy
import uuid

FILE_VERSION = 1


def dpm(label):
    """Printer dots per millimetre."""
    return label["dpi"] / 25.4


def label_size_dots(label):
    """Size of one label (the design area) in dots."""
    k = dpm(label)
    return int(round(label["width_mm"] * k)), int(round(label["height_mm"] * k))


def columns(label):
    return max(1, int(label.get("columns", 1)))


def is_individual(label):
    """Every label across has its own design."""
    return columns(label) > 1 and label.get("fill") == "individual"


def element_col(el):
    return int(el.get("col", 0))


def column_doc(doc, col):
    """The document with only the elements printed on label column `col`.

    Without individual designs every column prints the elements of label 1; elements that belong
    to other columns are kept in the file but not used.
    """
    use = col if is_individual(doc["label"]) else 0
    out = dict(doc)
    out["elements"] = [e for e in doc["elements"] if element_col(e) == use]
    return out


def media_width_mm(label):
    """Full liner width: side margins + labels across + gaps between them."""
    n = columns(label)
    return (2 * label.get("side_margin_mm", 0.0) + n * label["width_mm"]
            + (n - 1) * label.get("column_gap_mm", 0.0))


def column_offset_dots(label, col):
    """X offset (dots) of label column `col` from the left edge of the liner."""
    k = dpm(label)
    return int(round((label.get("side_margin_mm", 0.0)
                      + col * (label["width_mm"] + label.get("column_gap_mm", 0.0))) * k))


# --------------------------------------------------------------------------
# Label setup
# --------------------------------------------------------------------------
LABEL_DEFAULTS = {
    "width_mm": 50.0,
    "height_mm": 30.0,
    "columns": 1,              # labels across the liner (2-up, 3-up...)
    "column_gap_mm": 2.0,      # gap between labels side by side
    "side_margin_mm": 0.0,     # liner edge to first label (and last label to the other edge)
    "fill": "next",            # labels across: "next" record on each label, or the "same" record
    "dpi": 203,
    "media": "gap",            # gap | bline | continuous
    "gap_mm": 2.0,
    "gap_offset_mm": 0.0,
    "ribbon": True,            # True = thermal transfer (ribbon), False = direct thermal
    "mirror": False,
    "direction": 1,
    "speed": 4,
    "density": 8,
    "post_action": "tear",     # tear | peel | cutter | none
    "shift_dots": 0,
    "ref_x": 0,
    "ref_y": 0,
    "codepage": "UTF-8",
    "full_bitmap": False,
    "bitmap_zero_black": True,
}

# (group, name, width mm, height mm, gap mm)
LABEL_PRESETS = [
    ("Product / general", "25 x 15 mm", 25, 15, 2),
    ("Product / general", "30 x 20 mm", 30, 20, 2),
    ("Product / general", "32 x 25 mm", 32, 25, 2),
    ("Product / general", "38 x 25 mm", 38, 25, 2),
    ("Product / general", "40 x 30 mm", 40, 30, 2),
    ("Product / general", "50 x 25 mm", 50, 25, 2),
    ("Product / general", "50 x 30 mm", 50, 30, 2),
    ("Product / general", "50 x 50 mm", 50, 50, 2),
    ("Product / general", "57 x 32 mm", 57, 32, 2),
    ("Product / general", "60 x 40 mm", 60, 40, 2),
    ("Product / general", "70 x 50 mm", 70, 50, 3),
    ("Product / general", "75 x 50 mm", 75, 50, 3),
    ("Product / general", "100 x 50 mm", 100, 50, 3),
    ("Product / general", "100 x 75 mm", 100, 75, 3),
    ("Product / general", "100 x 100 mm", 100, 100, 3),
    ("Shipping (inch)", "2 x 1 in", 50.8, 25.4, 3),
    ("Shipping (inch)", "3 x 2 in", 76.2, 50.8, 3),
    ("Shipping (inch)", "4 x 2 in", 101.6, 50.8, 3),
    ("Shipping (inch)", "4 x 3 in", 101.6, 76.2, 3),
    ("Shipping (inch)", "4 x 4 in", 101.6, 101.6, 3),
    ("Shipping (inch)", "4 x 6 in (shipping)", 101.6, 152.4, 3),
    ("Garment / heat transfer", "Neck label 30 x 20 mm", 30, 20, 3),
    ("Garment / heat transfer", "Neck label 40 x 30 mm", 40, 30, 3),
    ("Garment / heat transfer", "Neck label 50 x 25 mm", 50, 25, 3),
    ("Garment / heat transfer", "Neck label 50 x 50 mm", 50, 50, 3),
    ("Garment / heat transfer", "Neck label 60 x 40 mm", 60, 40, 3),
    ("Garment / heat transfer", "Care label 25 x 50 mm", 25, 50, 3),
    ("Garment / heat transfer", "Care label 30 x 60 mm", 30, 60, 3),
    ("Garment / heat transfer", "Care label 35 x 70 mm", 35, 70, 3),
    ("Garment / heat transfer", "Care label 40 x 80 mm", 40, 80, 3),
]

# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------
ELEMENT_NAMES = {
    "text": "Text",
    "barcode": "Barcode",
    "qr": "QR code",
    "box": "Box",
    "line": "Line",
    "ellipse": "Ellipse",
    "image": "Image",
}

ELEMENT_DEFAULTS = {
    "text": {
        "text": "Text", "mode": "bitmap", "font_family": "Arial", "size_pt": 12.0,
        "bold": False, "italic": False, "underline": False, "align": "left",
        "box_width_mm": 0.0, "inverse": False,
        "printer_font": "3", "xmul": 1, "ymul": 1, "rotation": 0,
    },
    "barcode": {
        "data": "123456789012", "symbology": "128", "height_mm": 10.0,
        "narrow": 2, "wide": 2, "readable": "center", "rotation": 0,
    },
    "qr": {"data": "https://example.com", "ecc": "M", "cell": 4, "rotation": 0},
    "box": {"w_mm": 20.0, "h_mm": 10.0, "thickness_mm": 0.3, "radius_mm": 0.0, "filled": False},
    "line": {"orientation": "h", "length_mm": 30.0, "thickness_mm": 0.3},
    "ellipse": {"w_mm": 15.0, "h_mm": 15.0, "thickness_mm": 0.3, "filled": False},
    "image": {
        "image": "", "aspect": 1.0, "w_mm": 20.0, "h_mm": 20.0, "keep_aspect": True,
        "dither": True, "threshold": 128, "invert": False, "rotation": 0,
    },
}

# TSPL barcode type -> (display name, python-barcode name used for the preview)
BARCODE_TYPES = [
    ("128", "Code 128 (auto)", "code128"),
    ("128M", "Code 128 (manual)", "code128"),
    ("EAN128", "GS1-128 / EAN-128", "code128"),
    ("39", "Code 39", "code39"),
    ("39C", "Code 39 + check digit", "code39"),
    ("93", "Code 93", None),
    ("EAN13", "EAN-13 (12 digits)", "ean13"),
    ("EAN8", "EAN-8 (7 digits)", "ean8"),
    ("UPCA", "UPC-A (11 digits)", "upca"),
    ("UPCE", "UPC-E", None),
    ("25", "Interleaved 2 of 5", "itf"),
    ("ITF14", "ITF-14", "itf"),
    ("CODA", "Codabar", None),
    ("MSI", "MSI", None),
]
BARCODE_PYMAP = {t: py for t, _, py in BARCODE_TYPES}


def new_document():
    return {"version": FILE_VERSION, "label": copy.deepcopy(LABEL_DEFAULTS), "elements": [],
            "data": {"source": None}}


def new_element(kind):
    el = {"id": uuid.uuid4().hex, "type": kind, "x": 0.0, "y": 0.0}
    el.update(copy.deepcopy(ELEMENT_DEFAULTS[kind]))
    return el


def normalise_document(doc):
    """Fill in keys missing from older files and drop unknown element types."""
    label = copy.deepcopy(LABEL_DEFAULTS)
    label.update(doc.get("label", {}))
    elements = []
    for el in doc.get("elements", []):
        kind = el.get("type")
        if kind not in ELEMENT_DEFAULTS:
            continue
        full = new_element(kind)
        full.update(el)
        elements.append(full)
    data = {"source": None}
    data.update(doc.get("data") or {})
    return {"version": FILE_VERSION, "label": label, "elements": elements, "data": data}


# --------------------------------------------------------------------------
# Property schemas (drive the generic property editor)
# --------------------------------------------------------------------------
def F(key, label, kind, **opts):
    return dict(key=key, label=label, kind=kind, **opts)


ROTATIONS = [(0, "0°"), (90, "90°"), (180, "180°"), (270, "270°")]
PRINTER_FONT_OPTIONS = [
    ("1", "1   (8 x 12 dots)"), ("2", "2   (12 x 20 dots)"), ("3", "3   (16 x 24 dots)"),
    ("4", "4   (24 x 32 dots)"), ("5", "5   (32 x 48 dots)"), ("6", "6   (14 x 19 dots, OCR-B)"),
    ("7", "7   (21 x 27 dots, OCR-B)"), ("8", "8   (14 x 25 dots, OCR-A)"),
    ("0", "0   Scalable (size in points)"),
]


def _bitmap_text(e):
    return e["mode"] == "bitmap"


def _printer_text(e):
    return e["mode"] == "printer"


POS = [F("x", "X", "mm", min=-500, max=2000), F("y", "Y", "mm", min=-500, max=2000)]

SCHEMAS = {
    "text": POS + [
        F("text", "Text", "text"),
        F("mode", "Render as", "choice", options=[
            ("bitmap", "Bitmap (any font / language)"), ("printer", "Printer built-in font")],
          tip="Bitmap is exactly what you see. Printer fonts print faster but only support plain Latin text."),
        F("font_family", "Font", "font", when=_bitmap_text),
        F("size_pt", "Size", "float", min=2, max=400, step=0.5, decimals=1, suffix=" pt", when=_bitmap_text),
        F("bold", "Bold", "bool", when=_bitmap_text),
        F("italic", "Italic", "bool", when=_bitmap_text),
        F("underline", "Underline", "bool", when=_bitmap_text),
        F("align", "Align", "choice", options=[("left", "Left"), ("center", "Center"), ("right", "Right")],
          when=_bitmap_text),
        F("box_width_mm", "Box width", "mm", min=0, max=2000, when=_bitmap_text,
          tip="0 = automatic width. Otherwise text wraps inside this width."),
        F("inverse", "White on black", "bool", when=_bitmap_text),
        F("printer_font", "Printer font", "choice", options=PRINTER_FONT_OPTIONS, when=_printer_text),
        F("xmul", "Width x", "int", min=1, max=100, when=_printer_text,
          tip="Width multiplier 1-10. For font 0 this is the width in points."),
        F("ymul", "Height x", "int", min=1, max=100, when=_printer_text,
          tip="Height multiplier 1-10. For font 0 this is the height in points."),
        F("rotation", "Rotation", "choice", options=ROTATIONS),
    ],
    "barcode": POS + [
        F("data", "Data", "str"),
        F("symbology", "Type", "choice", options=[(t, n) for t, n, _ in BARCODE_TYPES]),
        F("height_mm", "Bar height", "mm", min=1, max=500),
        F("narrow", "Narrow bar", "int", min=1, max=20, suffix=" dots",
          tip="Width of the narrowest bar (module) in printer dots."),
        F("wide", "Wide bar", "int", min=1, max=40, suffix=" dots",
          tip="Wide bar width for Code 39 / 2of5 / Codabar. Ignored by Code 128 and EAN/UPC."),
        F("readable", "Human readable", "choice", options=[
            ("none", "None"), ("left", "Left"), ("center", "Center"), ("right", "Right")]),
        F("rotation", "Rotation", "choice", options=ROTATIONS),
    ],
    "qr": POS + [
        F("data", "Data", "text"),
        F("ecc", "Error correction", "choice", options=[
            ("L", "L (7%)"), ("M", "M (15%)"), ("Q", "Q (25%)"), ("H", "H (30%)")]),
        F("cell", "Cell size", "int", min=1, max=20, suffix=" dots"),
        F("rotation", "Rotation", "choice", options=ROTATIONS),
    ],
    "box": POS + [
        F("w_mm", "Width", "mm", min=0.1, max=2000),
        F("h_mm", "Height", "mm", min=0.1, max=2000),
        F("thickness_mm", "Line thickness", "mm", min=0.1, max=50, step=0.1),
        F("radius_mm", "Corner radius", "mm", min=0, max=100),
        F("filled", "Filled", "bool"),
    ],
    "line": POS + [
        F("orientation", "Orientation", "choice", options=[("h", "Horizontal"), ("v", "Vertical")]),
        F("length_mm", "Length", "mm", min=0.1, max=2000),
        F("thickness_mm", "Thickness", "mm", min=0.1, max=50, step=0.1),
    ],
    "ellipse": POS + [
        F("w_mm", "Width", "mm", min=0.1, max=2000),
        F("h_mm", "Height", "mm", min=0.1, max=2000),
        F("thickness_mm", "Line thickness", "mm", min=0.1, max=50, step=0.1),
        F("filled", "Filled", "bool"),
    ],
    "image": POS + [
        F("image", "Image", "button", text="Load image..."),
        F("w_mm", "Width", "mm", min=0.5, max=2000),
        F("h_mm", "Height", "mm", min=0.5, max=2000),
        F("keep_aspect", "Keep aspect ratio", "bool"),
        F("dither", "Dither (photos)", "bool"),
        F("threshold", "Threshold", "int", min=0, max=255, when=lambda e: not e["dither"],
          tip="Grey levels below this print black."),
        F("invert", "Invert", "bool"),
        F("rotation", "Rotation", "choice", options=ROTATIONS),
    ],
}


LABEL_SIZE_KEYS = ("width_mm", "height_mm", "columns", "column_gap_mm", "side_margin_mm", "fill", "dpi")
FILL_OPTIONS = [("next", "Next record on each label"),
                ("same", "Same record on every label in a row"),
                ("individual", "Different design on each label (same record)")]
FILL_HELP = {
    "next": "One design. Each label in a row gets the next record (serial printing).",
    "same": "One design. Every label in a row prints the same record; copies count whole rows.",
    "individual": "Each label in the row has its own design. All of them print the same record; "
                  "copies count whole rows. Click a label on the canvas to edit it.",
}
LABEL_MEDIA_KEYS = ("media", "gap_mm", "gap_offset_mm", "ribbon", "mirror", "direction", "speed", "density",
                    "post_action")
LABEL_ADVANCED_KEYS = ("shift_dots", "ref_x", "ref_y", "codepage", "full_bitmap", "bitmap_zero_black")


def label_schema(keys):
    return [f for f in LABEL_SCHEMA if f["key"] in keys]


def label_summary(label):
    method = "thermal transfer" if label["ribbon"] else "direct thermal"
    media = {"gap": "gap labels", "bline": "black mark", "continuous": "continuous"}[label["media"]]
    across = f", {columns(label)} across" if columns(label) > 1 else ""
    return (f"{label['width_mm']:g} x {label['height_mm']:g} mm{across}, {label['dpi']} dpi\n"
            f"{method}, {media}{', mirrored' if label['mirror'] else ''}")


def _not_continuous(l):
    return l["media"] != "continuous"


LABEL_SCHEMA = [
    F("width_mm", "Width", "mm", min=5, max=500),
    F("height_mm", "Height", "mm", min=5, max=2000),
    F("columns", "Labels across", "int", min=1, max=10,
      tip="Labels side by side on the roll, e.g. 2 for 2-up or 3 for 3-up media."),
    F("column_gap_mm", "Gap between labels", "mm", min=0, max=50, when=lambda l: l["columns"] > 1,
      tip="Horizontal gap between labels in the same row."),
    F("fill", "Fill labels with", "choice", when=lambda l: l["columns"] > 1,
      options=FILL_OPTIONS,
      tip="With data: give each label in a row its own record, or repeat one record across the row."),
    F("side_margin_mm", "Side margin", "mm", min=0, max=50,
      tip="Liner (backing paper) from its edge to the first label. The same margin is assumed on the right."),
    F("dpi", "Resolution", "choice", options=[
        (203, "203 dpi (8 dots/mm)"), (300, "300 dpi (12 dots/mm)"), (600, "600 dpi (24 dots/mm)")]),
    F("media", "Media", "choice", options=[
        ("gap", "Gap (die-cut labels)"), ("bline", "Black mark"), ("continuous", "Continuous")]),
    F("gap_mm", "Gap / mark size", "mm", min=0, max=50, when=_not_continuous),
    F("gap_offset_mm", "Gap offset", "mm", min=-50, max=50, when=_not_continuous),
    F("ribbon", "Print method", "choice", options=[
        (True, "Thermal transfer (ribbon)"), (False, "Direct thermal")],
      tip="Heat transfer / thermal transfer printing uses a ribbon: SET RIBBON ON."),
    F("mirror", "Mirror image", "bool",
      tip="Print mirrored. Usually needed for heat-transfer film that is pressed face-down onto fabric."),
    F("direction", "Direction", "choice", options=[(0, "0 (normal)"), (1, "1 (rotated 180°)")]),
    F("speed", "Speed", "choice", options=[(s, f"{s:g} ips") for s in (1.5, 2, 3, 4, 5, 6, 8, 10, 12)]),
    F("density", "Darkness", "int", min=0, max=15,
      tip="0-15. Heat-transfer film and resin ribbons usually need 10-15."),
    F("post_action", "After print", "choice", options=[
        ("tear", "Tear off"), ("peel", "Peel"), ("cutter", "Cut each label"), ("none", "Printer default")]),
    F("shift_dots", "Vertical shift", "int", min=-500, max=500, suffix=" dots"),
    F("ref_x", "Reference X", "int", min=0, max=5000, suffix=" dots"),
    F("ref_y", "Reference Y", "int", min=0, max=5000, suffix=" dots"),
    F("codepage", "Codepage", "choice", options=[
        ("UTF-8", "UTF-8"), ("1252", "1252 (Western)"), ("437", "437 (US)"), ("850", "850 (Multilingual)")]),
    F("full_bitmap", "Send as one bitmap", "bool",
      tip="Rasterise the whole label into one BITMAP. Exact output on any TSPL printer, but larger data."),
    F("bitmap_zero_black", "Bitmap: 0 bit = black", "bool",
      tip="TSC standard. Untick if images and bitmap text print inverted on your printer."),
]
