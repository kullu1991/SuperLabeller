"""Create the example design and the README screenshots.

    python tools/make_screenshots.py

Writes examples/products.csv, examples/garment-2up.tlabel and docs/screenshots/*.png.
"""
import csv
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")

from superlabeller.mainwindow import MainWindow  # noqa: E402
from superlabeller.mockprinter import MockPrinterDialog  # noqa: E402
from superlabeller.wizard import LabelSetupWizard  # noqa: E402

EX = os.path.join(ROOT, "examples")
SHOTS = os.path.join(ROOT, "docs", "screenshots")
os.makedirs(EX, exist_ok=True)
os.makedirs(SHOTS, exist_ok=True)

rows = [
    ("SKU", "Name", "Size", "Price", "Fabric", "Qty"),
    ("TS-1001", "Classic Crew T-Shirt", "M", "499", "100% Cotton", "2"),
    ("TS-1002", "Classic Crew T-Shirt", "L", "499", "100% Cotton", "2"),
    ("PL-2001", "Pique Polo", "XL", "899", "60% Cotton 40% Poly", "1"),
    ("HD-3001", "Fleece Hoodie", "L", "1499", "80% Cotton 20% Poly", "3"),
    ("JN-4001", "Slim Fit Jeans", "32", "1799", "98% Cotton 2% Elastane", "1"),
]
with open(os.path.join(EX, "products.csv"), "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerows(rows)

w = MainWindow()
w.resize(1500, 920)
w.move(-4000, 0)
w.show()
app.processEvents()

L = w.doc["label"]
L.update(width_mm=40, height_mm=30, columns=2, column_gap_mm=3, side_margin_mm=1.5, fill="next",
         density=12, speed=3)
w.canvas.rebuild()
w._update_info()
design_path = os.path.join(EX, "garment-2up.tlabel")
w.path = design_path
w.doc["data"]["source"] = {"kind": "csv", "path": "products.csv", "delimiter": "auto",
                           "encoding": "auto", "header": True}
w._load_source(quiet=False)


def add(kind, text=None, **props):
    if kind == "text":
        w.add_field_text(text)
    else:
        w.add_element(kind)
    el = w.doc["elements"][-1]
    el.update(props)
    w.canvas.refresh_element(el)
    return el


add("text", "{Name}", x=2, y=1.5, size_pt=8, bold=True, box_width_mm=36)
add("text", "SIZE", x=2, y=6, size_pt=6)
add("text", "{Size}", x=2, y=8.5, size_pt=16, bold=True)
add("text", "{Fabric}", x=13, y=7, size_pt=6, box_width_mm=25)
add("box", x=1, y=5.5, w_mm=10, h_mm=11, thickness_mm=0.3, radius_mm=1)
add("barcode", x=2, y=18, data="{SKU}", height_mm=6, narrow=1)
add("text", "MRP Rs. {Price:.2f}", x=15, y=25, size_pt=7, bold=True, box_width_mm=23, align="right")
add("qr", x=31, y=11.5, data="{SKU}|{Name}|{Size}", cell=2, ecc="M")
w.canvas.scene().clearSelection()
w._on_record_changed()
w.canvas.zoom_fit()
w.update_code()
app.processEvents()
w.save_file()
# keep the data path relative in the published example
doc = json.load(open(design_path, encoding="utf-8"))
doc["data"]["source"]["path"] = "products.csv"
json.dump(doc, open(design_path, "w", encoding="utf-8"), indent=1)
w.modified = False

w.statusBar().clearMessage()
app.processEvents()
w.grab().save(os.path.join(SHOTS, "main-window.png"))

wiz = LabelSetupWizard(None, L, new=True)
wiz.move(-4000, 0)
wiz.show()
app.processEvents()
wiz.grab().save(os.path.join(SHOTS, "setup-wizard.png"))
wiz.close()

slots = w._job_slots([0, 1, 2, 3, 4], 1, None)
mock = MockPrinterDialog(w, w.doc, slots, w.data_panel.rows)
mock.move(-4000, 0)
mock.show()
mock.view.set_speed(40)
end = time.time() + 2.9
while time.time() < end:
    app.processEvents()
    time.sleep(0.005)
mock.grab().save(os.path.join(SHOTS, "mock-printer.png"))
mock.close()
w.modified = False
w.close()
print("examples and screenshots written")
