"""Main application window."""
import base64
import copy
import io
import json
import os
import time
import uuid

from PIL import Image
from PyQt5.QtCore import QRectF, QSettings, Qt, QTimer
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QDialog, QDockWidget, QFileDialog, QLabel,
                             QInputDialog, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog,
                             QStyle, QToolBar)

from . import APP_NAME, AUTHOR, REPO_URL, __version__, datasource, merge, printing, render, tspl
from .canvas import Canvas
from .datapanel import DataPanel, DataSourceDialog
from .dialogs import PrintDialog
from .forms import PropertyPanel
from .mockprinter import MockPrinterDialog
from .insertpanel import ARRANGE, InsertPanel, arrange_icon, printer_icon
from .model import columns, dpm, element_col, is_individual, label_size_dots, label_summary, new_document, new_element, normalise_document
from .wizard import LabelSetupWizard

FILE_FILTER = "Super Labeller designs (*.tlabel);;All files (*)"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;All files (*)"
MAX_HISTORY = 200


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("SuperLabeller", "Super Labeller")
        self.doc = new_document()
        self.path = None
        self.modified = False
        self._clipboard = []
        self._history, self._hidx = [], -1
        self._last_key, self._last_time = None, 0.0

        self.canvas = Canvas(self)
        self.setCentralWidget(self.canvas)
        self.insert_panel = InsertPanel()
        self.props = PropertyPanel()
        self.code_view = QPlainTextEdit()
        self.code_view.setReadOnly(True)
        self.code_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(9)
        self.code_view.setFont(mono)

        self.data_panel = DataPanel()
        self._loaded_source = None  # JSON of the source whose records are loaded
        self._passwords = {}        # database passwords for this session only

        self._dock("Insert", self.insert_panel, Qt.LeftDockWidgetArea)
        self._dock("Properties", self.props, Qt.RightDockWidgetArea)
        self.data_dock = self._dock("Data", self.data_panel, Qt.BottomDockWidgetArea)
        self.code_dock = self._dock("TSPL output", self.code_view, Qt.BottomDockWidgetArea)
        self.tabifyDockWidget(self.data_dock, self.code_dock)
        self.data_dock.raise_()

        self._code_timer = QTimer(self)
        self._code_timer.setSingleShot(True)
        self._code_timer.setInterval(250)
        self._code_timer.timeout.connect(self.update_code)

        self._build_actions()
        self.props.set_arrange_actions(self.arrange_actions)
        self._build_menus()
        self._build_toolbars()
        self.pos_label = QLabel()
        self.zoom_label = QLabel()
        self.info_label = QLabel()
        for w in (self.info_label, self.pos_label, self.zoom_label):
            self.statusBar().addPermanentWidget(w)

        self.canvas.committed.connect(self.commit)
        self.canvas.live_changed.connect(self._on_live_change)
        self.canvas.selection_changed.connect(self._on_selection)
        self.canvas.cursor_moved.connect(lambda x, y: self.pos_label.setText(f"  X {x:.1f}  Y {y:.1f} mm  "))
        self.canvas.zoom_changed.connect(lambda z: self.zoom_label.setText(f"  Zoom {z:.0f}%  "))
        self.props.changed.connect(self._on_prop_changed)
        self.props.button_clicked.connect(self._on_prop_button)
        self.insert_panel.insert.connect(lambda k: self.add_image() if k == "image" else self.add_element(k))
        self.insert_panel.label_setup.connect(self.label_setup)
        self.insert_panel.insert_field.connect(self.insert_field)
        self.insert_panel.add_field_text.connect(self.add_field_text)
        self.data_panel.record_changed.connect(self._on_record_changed)
        self.data_panel.fill_changed.connect(self._on_fill_changed)

        self.resize(1360, 860)
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = self.settings.value("window_state_v2")
        if state is not None:
            self.restoreState(state)
        self._load(self.doc, None)

    # ================================================================= setup
    def _dock(self, title, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(title.replace(" ", "_"))
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _act(self, text, slot, shortcut=None, icon=None, tip=None, checkable=False, checked=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if icon is not None:
            a.setIcon(self.style().standardIcon(icon))
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(tip)
        if checkable:
            a.setCheckable(True)
            a.setChecked(checked)
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda _=False: slot())
        return a

    def _build_actions(self):
        S = QStyle
        self.a_new = self._act("&New Label...", self.new_file, QKeySequence.New, S.SP_FileIcon)
        self.a_label_setup = self._act("&Label Setup...", self.label_setup, "Ctrl+L", S.SP_FileDialogDetailedView,
                                       "Label size, media and printer settings")
        self.a_open = self._act("&Open...", self.open_file, QKeySequence.Open, S.SP_DialogOpenButton)
        self.a_save = self._act("&Save", self.save_file, QKeySequence.Save, S.SP_DialogSaveButton)
        self.a_save_as = self._act("Save &As...", self.save_file_as, QKeySequence.SaveAs)
        self.a_export = self._act("&Export TSPL (.prn)...", self.export_tspl, "Ctrl+E")
        self.a_print = self._act("&Print...", self.print_labels, QKeySequence.Print, None,
                                 "Send the labels to the printer")
        self.a_print.setIcon(printer_icon())
        self.a_quit = self._act("E&xit", self.close, QKeySequence.Quit)

        self.a_undo = self._act("&Undo", self.undo, QKeySequence.Undo, S.SP_ArrowBack)
        self.a_redo = self._act("&Redo", self.redo, QKeySequence.Redo, S.SP_ArrowForward)
        self.a_copy = self._act("&Copy", self.copy_selection, QKeySequence.Copy)
        self.a_paste = self._act("&Paste", self.paste, QKeySequence.Paste)
        self.a_dup = self._act("&Duplicate", self.duplicate, "Ctrl+D")
        self.a_delete = self._act("De&lete", self.delete_selection, QKeySequence.Delete, S.SP_TrashIcon)
        self.a_select_all = self._act("Select &All", self.canvas.select_all, QKeySequence.SelectAll)
        self.a_front = self._act("Bring to &Front", lambda: self.reorder(True), "Ctrl+]")
        self.a_back = self._act("Send to &Back", lambda: self.reorder(False), "Ctrl+[")
        self.a_center_h = self._act("Center &Horizontally on Label", lambda: self.center(True, False))
        self.a_center_v = self._act("Center &Vertically on Label", lambda: self.center(False, True))
        self.arrange_actions = []
        for key, text in ARRANGE:
            dist = key.startswith("dist")
            a = self._act(text, (lambda k=key: self.distribute(k == "dist_h")) if dist else
                          (lambda k=key: self.align(k)),
                          tip=f"{text} (3 or more items: spaced evenly)" if dist else
                          f"{text} (one item: aligns to the label)")
            a.setIcon(arrange_icon(key))
            a.setData(key)
            self.arrange_actions.append(a)

        self.insert_actions = [
            self._act("Text", lambda: self.add_element("text"), "Ctrl+Shift+T", tip="Add text"),
            self._act("Barcode", lambda: self.add_element("barcode"), "Ctrl+Shift+B", tip="Add a barcode"),
            self._act("QR code", lambda: self.add_element("qr"), "Ctrl+Shift+Q", tip="Add a QR code"),
            self._act("Box", lambda: self.add_element("box"), tip="Add a rectangle"),
            self._act("Line", lambda: self.add_element("line"), tip="Add a line"),
            self._act("Ellipse", lambda: self.add_element("ellipse"), tip="Add a circle / ellipse"),
            self._act("Image", self.add_image, "Ctrl+Shift+I", tip="Add a picture or logo"),
        ]

        self.a_zoom_in = self._act("Zoom &In", lambda: self.canvas.zoom_by(1.25), QKeySequence.ZoomIn)
        self.a_zoom_out = self._act("Zoom &Out", lambda: self.canvas.zoom_by(0.8), QKeySequence.ZoomOut)
        self.a_zoom_fit = self._act("&Fit Label", self.canvas.zoom_fit, "Ctrl+0")
        self.a_zoom_100 = self._act("Actual &Size", self.canvas.zoom_actual, "Ctrl+1")
        self.a_grid = self._act("Show &Grid", self._toggle_grid, checkable=True, checked=True)
        self.a_snap = self._act("S&nap to Grid", self._toggle_snap, checkable=True, checked=True)

        self.a_printer_setup = self._act("Printer &Connection...", self.printer_setup)
        self.a_feed = self._act("&Feed One Label", lambda: self.send_command("FORMFEED"))
        self.a_calibrate = self._act("&Calibrate Media (GAPDETECT)", lambda: self.send_command("GAPDETECT"))
        self.a_selftest = self._act("&Self Test", lambda: self.send_command("SELFTEST"))
        self.a_send_file = self._act("Send TSPL &File...", self.send_file)
        self.a_data_connect = self._act("Data &Source...", self.connect_data, "Ctrl+Shift+D",
                                        tip="Excel, CSV or database to print one label per row")
        self.a_data_reload = self._act("&Reload Data", self.reload_data, "F5")
        self.a_data_disconnect = self._act("&Disconnect Data", self.disconnect_data)
        self.a_about = self._act("&About", self.about)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as, None, self.a_label_setup, None,
                  self.a_export, self.a_print,
                  None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_copy, self.a_paste, self.a_dup, self.a_delete,
                  self.a_select_all, None, self.a_front, self.a_back):
            m.addSeparator() if a is None else m.addAction(a)
        arrange = m.addMenu("&Arrange")
        arrange.addActions(self.arrange_actions[:6])
        arrange.addSeparator()
        arrange.addActions(self.arrange_actions[6:])
        arrange.addSeparator()
        arrange.addActions([self.a_center_h, self.a_center_v])
        m = mb.addMenu("&Insert")
        m.addActions(self.insert_actions)
        m = mb.addMenu("&Data")
        m.addActions([self.a_data_connect, self.a_data_reload, self.a_data_disconnect])
        m.addSeparator()
        m.addAction(self.a_print)
        m = mb.addMenu("&View")
        m.addActions([self.a_zoom_in, self.a_zoom_out, self.a_zoom_fit, self.a_zoom_100])
        m.addSeparator()
        m.addActions([self.a_grid, self.a_snap])
        grid_menu = m.addMenu("Grid Size")
        group = QActionGroup(self)
        for size in (0.25, 0.5, 1.0, 2.0, 5.0):
            a = QAction(f"{size:g} mm", self, checkable=True, checked=size == 1.0)
            a.triggered.connect(lambda _=False, s=size: self._set_grid(s))
            group.addAction(a)
            grid_menu.addAction(a)
        m.addSeparator()
        for dock in self.findChildren(QDockWidget):
            m.addAction(dock.toggleViewAction())
        m = mb.addMenu("&Printer")
        m.addActions([self.a_print, self.a_printer_setup])
        m.addSeparator()
        m.addActions([self.a_feed, self.a_calibrate, self.a_selftest, self.a_send_file])
        m = mb.addMenu("&Help")
        m.addAction(self.a_about)

    def _build_toolbars(self):
        tb = QToolBar("File", self)
        tb.setObjectName("file_toolbar")
        tb.addActions([self.a_new, self.a_open, self.a_save])
        tb.addSeparator()
        tb.addAction(self.a_label_setup)
        tb.addSeparator()
        tb.addActions([self.a_undo, self.a_redo, self.a_delete])
        tb.addSeparator()
        tb.addAction(self.a_print)
        self.addToolBar(tb)
        tb = QToolBar("Arrange", self)
        tb.setObjectName("arrange_toolbar")
        tb.addActions(self.arrange_actions[:6])
        tb.addSeparator()
        tb.addActions(self.arrange_actions[6:])
        self.addToolBar(tb)
        tb = QToolBar("View", self)
        tb.setObjectName("view_toolbar")
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        tb.addActions([self.a_zoom_out, self.a_zoom_in, self.a_zoom_fit])
        self.addToolBar(tb)

    # ================================================================= document / history
    def _snapshot(self):
        return json.dumps(self.doc, separators=(",", ":"))

    def _load(self, doc, path):
        self.doc = doc
        self.path = path
        self.canvas.set_document(doc)
        self._history, self._hidx = [self._snapshot()], 0
        self._last_key = None
        self.modified = False
        self._update_title()
        self._update_info()
        self._update_history_actions()
        self._sync_data_source(quiet=True)
        self.update_code()
        QTimer.singleShot(0, self.canvas.zoom_fit)

    def commit(self, key=""):
        """Record an undo step. Rapid edits of the same field merge into one step."""
        snap = self._snapshot()
        if snap == self._history[self._hidx]:
            return
        del self._history[self._hidx + 1:]
        now = time.monotonic()
        if key and key == self._last_key and now - self._last_time < 1.5 and self._hidx > 0:
            self._history[self._hidx] = snap
        else:
            self._history.append(snap)
            if len(self._history) > MAX_HISTORY:
                self._history.pop(0)
            self._hidx = len(self._history) - 1
        self._last_key, self._last_time = key, now
        self.modified = True
        self._update_title()
        self._update_history_actions()
        self._code_timer.start()

    def _restore(self, idx):
        selected = self.canvas.selected_ids()
        self._hidx = idx
        self.doc = json.loads(self._history[idx])
        self._last_key = None
        self.canvas.set_document(self.doc, selected)
        self.modified = True
        self._update_title()
        self._update_info()
        self._update_history_actions()
        self._sync_data_source(quiet=True)
        self._on_record_changed()

    def undo(self):
        if self._hidx > 0:
            self._restore(self._hidx - 1)

    def redo(self):
        if self._hidx < len(self._history) - 1:
            self._restore(self._hidx + 1)

    def _update_history_actions(self):
        self.a_undo.setEnabled(self._hidx > 0)
        self.a_redo.setEnabled(self._hidx < len(self._history) - 1)

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.setWindowTitle(f"{name}{' *' if self.modified else ''} - {APP_NAME}")

    def _update_info(self):
        L = self.doc["label"]
        w, h = label_size_dots(L)
        extra = ", mirrored" if L["mirror"] else ""
        method = "thermal transfer" if L["ribbon"] else "direct thermal"
        self.info_label.setText(f"  {L['width_mm']:g} x {L['height_mm']:g} mm  |  {w} x {h} dots @ "
                                f"{L['dpi']} dpi  |  {method}{extra}  ")
        self.insert_panel.set_summary(label_summary(L))

    def _preview_args(self):
        """(record, index, count) currently shown on the label."""
        rows = self.data_panel.rows
        return self.data_panel.current_record(), self.data_panel.current_index(), max(1, len(rows))

    def _row_slots(self):
        """Record index for each label in the previewed row (None = no record).

        A list shorter than the number of labels across means the rest stay blank.
        """
        L = self.doc["label"]
        n = columns(L)
        rows = self.data_panel.rows
        if self.data_panel.current_record() is None:
            return [None] * n
        i = self.data_panel.current_index()
        if L.get("fill") in ("same", "individual"):
            return [i] * n
        return list(range(i, min(i + n, len(rows))))

    def _preview_job(self):
        return tspl.batch(self.doc, self._row_slots(), self.data_panel.rows)

    def update_code(self):
        try:
            text = tspl.to_text(self._preview_job())
        except Exception as e:  # never let a preview problem crash the editor
            text = f"Error generating TSPL: {e}"
        bar = self.code_view.verticalScrollBar()
        pos = bar.value()
        self.code_view.setPlainText(text)
        bar.setValue(pos)

    # ================================================================= reacting to edits
    def _on_live_change(self):
        self.props.refresh_values()
        self._code_timer.start()

    def _on_selection(self, elements):
        if len(elements) == 1:
            self.props.set_element(elements[0])
        else:
            self.props.set_element(None, f"{len(elements)} elements selected" if elements else
                                   "Nothing selected - click an element, or use Insert")
        self.props.show_arrange(len(elements) > 1)
        has = bool(elements)
        for a in (self.a_copy, self.a_dup, self.a_delete, self.a_front, self.a_back, self.a_center_h,
                  self.a_center_v):
            a.setEnabled(has)
        for a in self.arrange_actions:
            a.setEnabled(len(elements) >= (3 if a.data().startswith("dist") else 1))

    def _on_prop_changed(self, key):
        el = self.props.element
        if el is None:
            return
        if el["type"] == "image" and el["keep_aspect"] and el.get("aspect"):
            if key == "w_mm":
                el["h_mm"] = round(el["w_mm"] / el["aspect"], 2)
                self.props.refresh_values()
            elif key in ("h_mm", "keep_aspect"):
                el["w_mm"] = round(el["h_mm"] * el["aspect"], 2)
                self.props.refresh_values()
        self.canvas.refresh_element(el)
        self.commit(f"{el['id']}.{key}")

    def _on_prop_button(self, key):
        if key == "image" and self.props.element is not None:
            self._load_image_into(self.props.element)

    def label_setup(self):
        """Edit label size, media and printer settings in the setup wizard."""
        wiz = LabelSetupWizard(self, self.doc["label"], new=False)
        if wiz.exec_() != QDialog.Accepted or wiz.label == self.doc["label"]:
            return
        resized = any(wiz.label[k] != self.doc["label"][k] for k in ("width_mm", "height_mm", "dpi", "columns"))
        was_individual = is_individual(self.doc["label"])
        self.doc["label"].update(wiz.label)
        self._designs_changed(was_individual)
        self.canvas.rebuild()
        if resized:
            QTimer.singleShot(0, self.canvas.zoom_fit)
        self._update_info()
        self._on_record_changed()
        self.commit()

    # ================================================================= elements
    def _place_center(self, el):
        """Centre a new element on the label being edited (the active one with individual designs)."""
        L = self.doc["label"]
        el["col"] = self.canvas.active_col if is_individual(L) else 0
        k = dpm(L)
        w, h = label_size_dots(L)
        r = render.local_rect(self.canvas.view_el(el), L)
        el["x"] = round(max(0.0, (w - r.width()) / 2) / k, 1)
        el["y"] = round(max(0.0, (h - r.height()) / 2) / k, 1)

    def _insert(self, elements):
        self.doc["elements"].extend(elements)
        self.canvas.rebuild([e["id"] for e in elements])
        self.commit()
        self.canvas.setFocus()

    def add_element(self, kind):
        el = new_element(kind)
        L = self.doc["label"]
        if kind == "line":
            el["length_mm"] = round(L["width_mm"] * 0.8, 1)
        elif kind == "box":
            el["w_mm"] = round(L["width_mm"] * 0.5, 1)
            el["h_mm"] = round(L["height_mm"] * 0.4, 1)
        self._place_center(el)
        self._insert([el])

    def _read_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose image", self.settings.value("image_dir", ""),
                                              IMAGE_FILTER)
        if not path:
            return None
        self.settings.setValue("image_dir", os.path.dirname(path))
        try:
            im = Image.open(path)
            im.load()
            if im.mode not in ("RGB", "RGBA", "L", "LA"):
                im = im.convert("RGBA")
            im.thumbnail((2000, 2000))  # keep design files small
            buf = io.BytesIO()
            im.save(buf, "PNG")
        except Exception as e:
            QMessageBox.warning(self, "Image", f"Could not open the image:\n{e}")
            return None
        return base64.b64encode(buf.getvalue()).decode("ascii"), im.width / max(1, im.height)

    def _load_image_into(self, el):
        result = self._read_image()
        if result is None:
            return
        el["image"], el["aspect"] = result
        el["h_mm"] = round(el["w_mm"] / el["aspect"], 2)
        self.props.refresh_values()
        self.canvas.refresh_element(el)
        self.commit()

    def add_image(self):
        result = self._read_image()
        if result is None:
            return
        L = self.doc["label"]
        el = new_element("image")
        el["image"], el["aspect"] = result
        el["w_mm"] = round(min(L["width_mm"] * 0.6, L["height_mm"] * 0.6 * el["aspect"]), 1)
        el["h_mm"] = round(el["w_mm"] / el["aspect"], 2)
        self._place_center(el)
        self._insert([el])

    def delete_selection(self):
        ids = set(self.canvas.selected_ids())
        if not ids:
            return
        self.doc["elements"] = [e for e in self.doc["elements"] if e["id"] not in ids]
        self.canvas.rebuild([])
        self.commit()

    def _copies(self, elements, offset):
        out = []
        for e in elements:
            c = copy.deepcopy(e)
            c["id"] = uuid.uuid4().hex
            c["x"] = round(c["x"] + offset, 3)
            c["y"] = round(c["y"] + offset, 3)
            out.append(c)
        return out

    def copy_selection(self):
        self._clipboard = copy.deepcopy([it.el for it in self.canvas.selected_items()])
        self._paste_count = 0

    def paste(self):
        if not self._clipboard:
            return
        self._paste_count = getattr(self, "_paste_count", 0) + 1
        self._insert(self._copies(self._clipboard, 2.0 * self._paste_count))

    def duplicate(self):
        items = self.canvas.selected_items()
        if items:
            self._insert(self._copies([it.el for it in items], 2.0))

    def reorder(self, to_front):
        ids = set(self.canvas.selected_ids())
        if not ids:
            return
        sel = [e for e in self.doc["elements"] if e["id"] in ids]
        rest = [e for e in self.doc["elements"] if e["id"] not in ids]
        self.doc["elements"] = rest + sel if to_front else sel + rest
        self.canvas.rebuild()
        self.commit()

    def center(self, horizontal, vertical):
        L = self.doc["label"]
        k = dpm(L)
        w, h = label_size_dots(L)
        for it in self.canvas.selected_items():
            r = it.scene_content_rect().translated(-it.dx(), 0)  # relative to its own label
            if horizontal:
                it.el["x"] = round(it.el["x"] + ((w - r.width()) / 2 - r.left()) / k, 3)
            if vertical:
                it.el["y"] = round(it.el["y"] + ((h - r.height()) / 2 - r.top()) / k, 3)
            it.refresh()
        self.props.refresh_values()
        self.commit()

    def _move_items(self, moves):
        """moves: [(item, dx_dots, dy_dots)]"""
        k = dpm(self.doc["label"])
        changed = False
        for it, dx, dy in moves:
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                continue
            it.el["x"] = round(it.el["x"] + dx / k, 3)
            it.el["y"] = round(it.el["y"] + dy / k, 3)
            it.refresh()
            changed = True
        if changed:
            self.props.refresh_values()
            self.commit()

    def align(self, edge):
        """Align selected items to each other, or a single item to the label."""
        items = self.canvas.selected_items()
        if not items:
            return
        rects = [it.scene_content_rect() for it in items]
        if len(items) == 1:
            w, h = label_size_dots(self.doc["label"])
            bounds = QRectF(items[0].dx(), 0, w, h)  # the item's own label
        else:
            bounds = rects[0]
            for r in rects[1:]:
                bounds = bounds.united(r)
        moves = []
        for it, r in zip(items, rects):
            dx = {"left": bounds.left() - r.left(), "right": bounds.right() - r.right(),
                  "hcenter": bounds.center().x() - r.center().x()}.get(edge, 0.0)
            dy = {"top": bounds.top() - r.top(), "bottom": bounds.bottom() - r.bottom(),
                  "vcenter": bounds.center().y() - r.center().y()}.get(edge, 0.0)
            moves.append((it, dx, dy))
        self._move_items(moves)

    def distribute(self, horizontal):
        """Equal spacing between 3+ items; the outermost items stay where they are."""
        items = self.canvas.selected_items()
        if len(items) < 3:
            return
        pairs = [(it, it.scene_content_rect()) for it in items]
        if horizontal:
            pairs.sort(key=lambda p: p[1].left())
            span = pairs[-1][1].right() - pairs[0][1].left()
            gap = (span - sum(r.width() for _, r in pairs)) / (len(pairs) - 1)
            pos, moves = pairs[0][1].left(), []
            for it, r in pairs:
                moves.append((it, pos - r.left(), 0.0))
                pos += r.width() + gap
        else:
            pairs.sort(key=lambda p: p[1].top())
            span = pairs[-1][1].bottom() - pairs[0][1].top()
            gap = (span - sum(r.height() for _, r in pairs)) / (len(pairs) - 1)
            pos, moves = pairs[0][1].top(), []
            for it, r in pairs:
                moves.append((it, 0.0, pos - r.top()))
                pos += r.height() + gap
        self._move_items(moves)

    # ================================================================= data source
    def _source(self):
        return self.doc.setdefault("data", {"source": None}).get("source")

    @staticmethod
    def _pw_key(src):
        return (src.get("driver"), src.get("server"), src.get("database"), src.get("user"))

    def _set_records(self, columns, rows):
        self._loaded_source = json.dumps(self._source(), sort_keys=True)
        description = datasource.describe(self._source()) if self._source() else None
        self.data_panel.set_data(columns, rows, description)
        self.insert_panel.set_fields(columns, description)

    def _load_source(self, quiet):
        """Load records for the document's source. Asks for a password if one is needed."""
        src = self._source()
        if src is None:
            self._set_records([], [])
            return True
        src = dict(src)
        if src.get("path") and not os.path.isabs(src["path"]) and self.path:
            # Relative data file paths are relative to the design file (e.g. the bundled examples).
            src["path"] = os.path.join(os.path.dirname(os.path.abspath(self.path)), src["path"])
        key = self._pw_key(src)
        if datasource.needs_password(src):
            pw = self._passwords.get(key)
            if pw is None:
                pw, ok = QInputDialog.getText(self, "Database password",
                                              f"Password for {src.get('user')} on {datasource.describe(src)}:",
                                              QLineEdit.Password)
                if not ok:
                    self._set_records([], [])
                    return False
            src["password"] = pw
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                cols, rows = datasource.load(src)
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as e:
            self._set_records([], [])
            self.data_panel.source_label.setText(f"<b>{datasource.describe(src)}</b> - "
                                                 f"<span style='color:#b00'>could not load: {e}</span>")
            if not quiet:
                QMessageBox.warning(self, "Data", str(e))
            return False
        if src.get("password"):
            self._passwords[key] = src["password"]
        self._set_records(cols, rows)
        self.statusBar().showMessage(f"Loaded {len(rows)} records from {datasource.describe(src)}", 5000)
        return True

    def _sync_data_source(self, quiet=True):
        """Reload records if the document's source differs from what is loaded."""
        if json.dumps(self._source(), sort_keys=True) != self._loaded_source:
            self._load_source(quiet)

    def connect_data(self):
        dlg = DataSourceDialog(self, self._source())
        if dlg.exec_() != QDialog.Accepted:
            return
        src = dlg.source()
        if src.get("password"):
            self._passwords[self._pw_key(src)] = src["password"]  # remembered for this session
            if not src.get("save_password"):
                src["password"] = ""  # keep it out of the design file
        self.doc.setdefault("data", {})["source"] = src
        self._set_records(*dlg.loaded)
        self.data_dock.show()
        self.data_dock.raise_()
        self.commit("data.source")

    def reload_data(self):
        if self._source() is None:
            self.connect_data()
            return
        current = self.data_panel.current_index()
        if self._load_source(quiet=False):
            self.data_panel.set_current(current)

    def disconnect_data(self):
        if self._source() is None:
            return
        self.doc["data"]["source"] = None
        self._set_records([], [])
        self.commit("data.source")

    def _on_record_changed(self):
        rows = self.data_panel.rows
        n = columns(self.doc["label"])
        slots = self._row_slots()
        count = max(1, len(rows))
        row = [(rows[s] if s is not None else None, s or 0, count) for s in slots] + [None] * (n - len(slots))
        captions = []
        if rows and self.data_panel.current_record() is not None:
            captions = [f"Record {s + 1}" for s in slots] + ["blank"] * (n - len(slots))
        if is_individual(self.doc["label"]):
            captions = [f"Label {c + 1}" + (f"  -  record {slots[c] + 1}" if captions else "")
                        for c in range(n)]
        self.canvas.set_preview(*self._preview_args(), row=row, captions=captions)
        self.data_panel.set_fill(self.doc["label"].get("fill", "next"), n)
        self.props.refresh_values()
        self._code_timer.start()

    def _on_fill_changed(self, fill):
        if self.doc["label"].get("fill") != fill:
            was_individual = is_individual(self.doc["label"])
            self.doc["label"]["fill"] = fill
            self._designs_changed(was_individual)
            self.canvas.rebuild()
            self._on_record_changed()
            self.commit("label.fill")

    def _designs_changed(self, was_individual):
        """Handle switching to / from a separate design on each label across."""
        L = self.doc["label"]
        n = columns(L)
        now = is_individual(L)
        others = [e for e in self.doc["elements"] if element_col(e) > 0]
        if now and not was_individual:
            base = [e for e in self.doc["elements"] if element_col(e) == 0]
            empty = [c for c in range(1, n) if not any(element_col(e) == c for e in others)]
            if base and empty:
                answer = QMessageBox.question(
                    self, "Different design on each label",
                    f"Start label {', '.join(str(c + 1) for c in empty)} as a copy of label 1?\n\n"
                    "Yes: copy the design, then change each label as needed.\n"
                    "No: start with empty labels.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if answer == QMessageBox.Yes:
                    for c in empty:
                        for e in base:
                            dup = copy.deepcopy(e)
                            dup["id"] = uuid.uuid4().hex
                            dup["col"] = c
                            self.doc["elements"].append(dup)
            self.statusBar().showMessage("Each label has its own design - click a label to edit it.", 6000)
        elif was_individual and not now and others:
            self.statusBar().showMessage(
                "Designs of labels 2+ are kept in the file and come back when you choose "
                "'Different design on each label' again.", 8000)

    def insert_field(self, placeholder):
        """Put placeholder text such as "{SKU}" or "{SKU}\\n{Name}" into the selected element."""
        el = self.props.element
        if el is None or el["type"] not in merge.MERGE_KEYS:
            self.add_field_text(placeholder)
            return
        key = merge.MERGE_KEYS[el["type"]][0]
        if el["type"] == "barcode":
            placeholder = placeholder.replace("\n", " ").replace("\t", " ")  # barcodes are one line
        if el["type"] == "text" and el[key] not in ("", "Text"):
            el[key] += placeholder
        else:
            el[key] = placeholder
        self.props.refresh_values()
        self.canvas.refresh_element(el)
        self.commit()

    def add_field_text(self, placeholder):
        el = new_element("text")
        el["text"] = placeholder
        self._place_center(el)
        self._insert([el])

    # ================================================================= view
    def _toggle_grid(self, on):
        self.canvas.show_grid = on
        self.canvas.viewport().update()

    def _toggle_snap(self, on):
        self.canvas.snap = on

    def _set_grid(self, size):
        self.canvas.grid_mm = size
        self.canvas.viewport().update()

    # ================================================================= files
    def _confirm_discard(self):
        if not self.modified:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to the current label?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_file()
        return r == QMessageBox.Discard

    def new_file(self):
        """Start a new label: the setup wizard comes first."""
        if not self._confirm_discard():
            return False
        last = self.settings.value("last_label", "")
        label = copy.deepcopy(self.doc["label"])
        if last:
            try:
                label.update(json.loads(last))  # start from the previous project's setup
            except ValueError:
                pass
        wiz = LabelSetupWizard(self, label, new=True)
        if wiz.exec_() != QDialog.Accepted:
            return False
        self.settings.setValue("last_label", json.dumps(wiz.label))
        doc = new_document()
        doc["label"] = wiz.label
        self._load(doc, None)
        return True

    def open_file(self, path=None):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open label", self.settings.value("dir", ""), FILE_FILTER)
            if not path:
                return
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = normalise_document(json.load(f))
        except Exception as e:
            QMessageBox.critical(self, "Open", f"Could not open {path}:\n{e}")
            return
        self.settings.setValue("dir", os.path.dirname(path))
        self._load(doc, path)

    def save_file(self):
        if not self.path:
            return self.save_file_as()
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.doc, f, indent=1)
        except OSError as e:
            QMessageBox.critical(self, "Save", f"Could not save:\n{e}")
            return False
        self.modified = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    def save_file_as(self):
        start = self.path or os.path.join(self.settings.value("dir", ""), "label.tlabel")
        path, _ = QFileDialog.getSaveFileName(self, "Save label", start, FILE_FILTER)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += ".tlabel"
        self.settings.setValue("dir", os.path.dirname(path))
        self.path = path
        return self.save_file()

    def export_tspl(self):
        base = os.path.splitext(self.path)[0] + ".prn" if self.path else "label.prn"
        path, _ = QFileDialog.getSaveFileName(self, "Export TSPL", base, "Printer files (*.prn);;All files (*)")
        if not path:
            return
        try:
            data = tspl.to_bytes(self._preview_job(), self.doc["label"])
            with open(path, "wb") as f:
                f.write(data)
        except Exception as e:
            QMessageBox.critical(self, "Export", f"Could not export:\n{e}")
            return
        self.statusBar().showMessage(f"Exported {len(data)} bytes to {path}", 5000)

    # ================================================================= printing
    def _target(self):
        raw = self.settings.value("print_target", "")
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    def _save_target(self, target):
        self.settings.setValue("print_target", json.dumps(target))

    def _send(self, data, what, offer_mock=None):
        """Send raw data to the configured printer. On failure, `offer_mock` (if given) is offered."""
        target = self._target()
        if target and target.get("kind") == "mock":
            self.statusBar().showMessage(f"Mock printer received {what} ({len(data)} bytes)", 6000)
            return True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            printing.send(target, data)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            msg = f"Could not send to {printing.describe(target)}:\n{e}"
            if offer_mock and QMessageBox.question(
                    self, "Print", msg + "\n\nShow the job on the mock printer instead?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                offer_mock()
            elif not offer_mock:
                QMessageBox.critical(self, "Print", msg)
            return False
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"Sent {what} to {printing.describe(target)} ({len(data)} bytes)", 6000)
        return True

    def print_labels(self):
        copies = int(self.settings.value("copies", 1))
        rows = self.data_panel.rows
        info = None
        if rows:
            info = dict(count=len(rows), current=self.data_panel.current_index(),
                        selected=self.data_panel.selected_indices(), columns=self.data_panel.columns)
        elif merge.fields_used(self.doc) and any(not f.startswith("_") for f in merge.fields_used(self.doc)):
            if QMessageBox.question(self, "Print", "The label uses data fields but no data source is "
                                    "connected. Print anyway with the field names as text?") != QMessageBox.Yes:
                return
        across = columns(self.doc["label"]) > 1
        same = across and self.doc["label"].get("fill") in ("same", "individual")
        copies_label = ("Rows per record" if same else "Labels per record") if (across and info) else None
        dlg = PrintDialog(self, self._target(), copies, records=info, copies_label=copies_label)
        if dlg.exec_() != QDialog.Accepted:
            return
        self._save_target(dlg.target())
        self.settings.setValue("copies", dlg.copies())
        slots = self._job_slots(dlg.record_indices(), dlg.copies(), dlg.quantity_column())
        if not slots:
            QMessageBox.information(self, "Print", "Nothing to print (all quantities are 0).")
            return
        if dlg.target()["kind"] == "mock":
            self.run_mock(slots)
            return
        try:
            data, total = self._build_job(slots)
        except Exception as e:
            QMessageBox.critical(self, "Print", f"Could not generate TSPL:\n{e}")
            return
        if data is None:
            return  # cancelled
        self._send(data, f"{total} label(s)", offer_mock=lambda: self.run_mock(slots))

    def run_mock(self, slots):
        """Play the job on the animated mock printer."""
        dlg = MockPrinterDialog(self, copy.deepcopy(self.doc), slots, self.data_panel.rows)
        dlg.exec_()
        self.statusBar().showMessage(f"Mock printer: {dlg.view.printed} of {len(slots)} label(s) printed", 6000)

    def _job_slots(self, indices, copies, qty_column):
        """One entry per label to print: a record index (or None without data)."""
        rows = self.data_panel.rows
        label = self.doc["label"]
        slots = []
        for i in indices:
            qty = copies
            if qty_column and i is not None:
                try:
                    qty = int(float(str(rows[i].get(qty_column, "")).strip() or 0))
                except ValueError:
                    qty = 0
            # "same": every label of a row shows the record, so each copy is a whole row
            per = columns(label) if label.get("fill") in ("same", "individual") else 1
            slots += [i] * (max(0, qty) * per)
        return slots

    def _build_job(self, slots):
        """TSPL for a batch of label slots. Returns (bytes, label count), or (None, 0) if cancelled."""
        rows = self.data_panel.rows
        label = self.doc["label"]
        if not slots:
            return b"", 0
        progress = None
        if len(slots) > 20 * columns(label):
            progress = QProgressDialog("Preparing labels...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(300)

        def report(done, total):
            if progress:
                progress.setValue(int(done * 100 / total))
                return not progress.wasCanceled()

        chunks = tspl.batch(self.doc, slots, rows, report)
        if chunks is None:
            return None, 0
        return tspl.to_bytes(chunks, label), len(slots)

    def printer_setup(self):
        dlg = PrintDialog(self, self._target(), setup_only=True)
        if dlg.exec_() == QDialog.Accepted:
            self._save_target(dlg.target())
            return True
        return False

    def send_command(self, cmd):
        if self._target() is None and not self.printer_setup():
            return
        self._send(tspl.command(cmd), cmd)

    def send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Send TSPL file", "", "Printer files (*.prn *.txt);;All files (*)")
        if not path:
            return
        if self._target() is None and not self.printer_setup():
            return
        with open(path, "rb") as f:
            self._send(f.read(), os.path.basename(path))

    # ================================================================= misc
    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}", f"<h3>{APP_NAME} {__version__}</h3>"
                          "Design thermal / heat-transfer labels and print them on TSPL / TSPL2 printers "
                          "(TSC and compatible), from Excel, CSV or databases.<br><br>"
                          "Tips:<ul><li>Ctrl + mouse wheel zooms</li>"
                          "<li>Arrow keys nudge the selection (Shift = 10x)</li>"
                          "<li>Drag the blue corner handle to resize</li>"
                          "<li>Turn on <i>Mirror image</i> for heat-transfer film applied face-down</li>"
                          "<li>No printer? Print to the <i>Mock printer</i></li></ul>"
                          f"&copy; 2026 {AUTHOR}. Free software under the GNU GPL v3.<br>"
                          f'<a href="{REPO_URL}">{REPO_URL}</a>')

    def closeEvent(self, e):
        if not self._confirm_discard():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state_v2", self.saveState())
        e.accept()
