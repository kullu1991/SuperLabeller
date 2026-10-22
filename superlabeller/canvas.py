"""The label design canvas. Scene units are printer dots."""
from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from . import merge, render
from .model import (column_doc, column_offset_dots, columns, dpm, element_col, is_individual, label_size_dots,
                    media_width_mm)

SELECT_COLOR = QColor(0, 120, 215)


class ElementItem(QGraphicsItem):
    def __init__(self, el, canvas):
        super().__init__()
        self.el = el
        self.canvas = canvas
        self._rect = QRectF()
        self._sync = False
        self._resizing = False
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.refresh()

    @property
    def label(self):
        return self.canvas.doc["label"]

    def refresh(self):
        """Re-read geometry from the element dict."""
        self.prepareGeometryChange()
        self._view = self.canvas.view_el(self.el)  # placeholders filled in for display
        self._rect = render.local_rect(self._view, self.label)
        self._sync = True
        self.setRotation(render.rotation(self.el))
        self.setPos(render.anchor(self.el, self.label) + QPointF(self.dx(), 0))
        self._sync = False
        self.update()

    def dx(self):
        """Scene offset of the label column this element belongs to."""
        return self.canvas.col_dx(element_col(self.el)) if self.canvas.individual else 0

    def content_rect(self):
        return self._rect

    def scene_content_rect(self):
        return self.mapRectToScene(self._rect)

    # ------------------------------------------------------------- geometry
    def _handle_size(self):
        return 9.0 / max(0.01, self.canvas.transform().m11())

    def _handle_rect(self):
        hs = self._handle_size()
        r = self._rect
        return QRectF(r.right() - hs / 2, r.bottom() - hs / 2, hs, hs)

    def boundingRect(self):
        hs = self._handle_size()
        return self._rect.adjusted(-hs / 2, -hs / 2, hs, hs)

    def shape(self):
        path = QPainterPath()
        path.addRect(self._rect)
        if self.isSelected() and self.resize_keys():
            path.addRect(self._handle_rect())
        return path

    def resize_keys(self):
        """(width key, height key) changed by the resize handle, or None."""
        t = self.el["type"]
        if t in ("box", "ellipse", "image"):
            return ("w_mm", "h_mm")
        if t == "text" and self.el["mode"] == "bitmap":
            return ("box_width_mm", None)
        if t == "line":
            return ("length_mm", None) if self.el["orientation"] == "h" else (None, "length_mm")
        if t == "barcode":
            return (None, "height_mm")
        return None

    # ------------------------------------------------------------- painting
    def paint(self, painter, option, widget=None):
        render.paint(painter, self._view, self.label)
        if self.isSelected():
            pen = QPen(SELECT_COLOR, 1, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._rect)
            if self.resize_keys():
                painter.fillRect(self._handle_rect(), SELECT_COLOR)

    # ------------------------------------------------------------- interaction
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and not self._sync:
            k = dpm(self.label)
            dx = self.dx()  # snap relative to the element's own label
            if self.canvas.snap:
                g = self.canvas.grid_mm * k
                return QPointF(round(round((value.x() - dx) / g) * g) + dx, round(round(value.y() / g) * g))
            return QPointF(round(value.x()), round(value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged and not self._sync:
            k = dpm(self.label)
            self.el["x"] = round((self.pos().x() - self.dx()) / k, 3)
            self.el["y"] = round(self.pos().y() / k, 3)
            self.canvas.item_edited()
        return super().itemChange(change, value)

    def _on_handle(self, pos):
        return self.isSelected() and self.resize_keys() and self._handle_rect().contains(pos)

    def hoverMoveEvent(self, e):
        self.setCursor(Qt.SizeFDiagCursor if self._on_handle(e.pos()) else Qt.SizeAllCursor)
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._on_handle(e.pos()):
            self._resizing = True
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if not self._resizing:
            super().mouseMoveEvent(e)
            return
        k = dpm(self.label)
        kx, ky = self.resize_keys()
        g = self.canvas.grid_mm if self.canvas.snap else 0.1

        def snap(v):
            return max(g, round(round(v / g) * g, 3))

        if self.el["type"] == "barcode":
            # Handle drags bar height; human-readable text sits below the bars.
            extra = self._rect.height() - round(self.el["height_mm"] * k)
            self.el["height_mm"] = snap((e.pos().y() - extra) / k)
        else:
            if kx:
                self.el[kx] = snap(e.pos().x() / k)
            if ky:
                self.el[ky] = snap(e.pos().y() / k)
            if self.el["type"] == "image" and self.el["keep_aspect"] and self.el.get("aspect"):
                self.el["h_mm"] = round(self.el["w_mm"] / self.el["aspect"], 2)
        self.refresh()
        self.canvas.item_edited()

    def mouseReleaseEvent(self, e):
        if self._resizing:
            self._resizing = False
            e.accept()
            return
        super().mouseReleaseEvent(e)


class Canvas(QGraphicsView):
    committed = pyqtSignal(str)          # an undoable edit finished
    live_changed = pyqtSignal()          # geometry is changing (dragging)
    selection_changed = pyqtSignal(object)  # list of element dicts; 'object' avoids Qt copying them
    cursor_moved = pyqtSignal(float, float)
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.items_by_id = {}
        self.snap = True
        self.grid_mm = 1.0
        self.show_grid = True
        self._dirty = False
        self.preview = (None, 0, 1)   # (record, index, count) shown in placeholders
        self.row_preview = []         # the same for each label across (None = blank label)
        self.captions = []            # text under each label across
        self.active_col = 0           # label that receives new elements (individual designs)

        self.setScene(QGraphicsScene(self))
        self.scene().selectionChanged.connect(self._on_selection)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor(90, 95, 102))

    # ------------------------------------------------------------- document
    @property
    def label(self):
        return self.doc["label"]

    @property
    def individual(self):
        return is_individual(self.label)

    def col_dx(self, col):
        return column_offset_dots(self.label, col) - column_offset_dots(self.label, 0)

    def column_at(self, x):
        """Label column under scene x (nearest one)."""
        n = columns(self.label)
        w = label_size_dots(self.label)[0]
        centres = [self.col_dx(c) + w / 2 for c in range(n)]
        return min(range(n), key=lambda c: abs(centres[c] - x))

    def set_active_col(self, col):
        col = max(0, min(columns(self.label) - 1, col)) if self.individual else 0
        if col != self.active_col:
            self.active_col = col
            self.viewport().update()

    def set_document(self, doc, select_ids=()):
        self.doc = doc
        self.rebuild(select_ids)

    def rebuild(self, select_ids=None):
        if select_ids is None:
            select_ids = self.selected_ids()
        scene = self.scene()
        scene.blockSignals(True)
        scene.clear()
        self.items_by_id = {}
        n = columns(self.label)
        self.active_col = min(self.active_col, n - 1) if self.individual else 0
        for z, el in enumerate(self.doc["elements"]):
            col = element_col(el)
            if col != 0 and not (self.individual and col < n):
                continue  # belongs to a label design that is not in use
            it = ElementItem(el, self)
            it.setZValue(z)
            scene.addItem(it)
            self.items_by_id[el["id"]] = it
        for i in select_ids:
            if i in self.items_by_id:
                self.items_by_id[i].setSelected(True)
        scene.blockSignals(False)
        self.update_scene_rect()
        self._on_selection()

    def update_scene_rect(self):
        w, h = label_size_dots(self.label)
        k = dpm(self.label)
        m = 25 * k
        full = (media_width_mm(self.label) - self.label["side_margin_mm"]) * k  # to the liner's right edge
        self.setSceneRect(-m, -m, max(w, full) + 2 * m, h + 2 * m)
        self.viewport().update()

    def view_el(self, el):
        return merge.merge_element(el, *self.preview)

    def set_preview(self, record, index=0, count=1, row=None, captions=None):
        """Record shown on the label being edited; `row` gives (record, index, count) or None (blank)
        for every label across, `captions` a text under each one."""
        self.preview = (record, index, count)
        self.row_preview = row or []
        self.captions = captions or []
        for it in self.items_by_id.values():
            it.refresh()
        self.viewport().update()

    def refresh_element(self, el):
        it = self.items_by_id.get(el["id"])
        if it:
            it.refresh()

    def items_in_order(self):
        return sorted(self.items_by_id.values(), key=lambda it: it.zValue())

    def selected_items(self):
        return sorted((it for it in self.scene().selectedItems() if isinstance(it, ElementItem)),
                      key=lambda it: it.zValue())

    def selected_ids(self):
        return [it.el["id"] for it in self.selected_items()]

    def select_all(self):
        for it in self.items_by_id.values():
            it.setSelected(True)

    def item_edited(self):
        self._dirty = True
        self.live_changed.emit()

    def _on_selection(self):
        items = self.selected_items()
        if items and self.individual:
            self.set_active_col(element_col(items[-1].el))
        self.selection_changed.emit([it.el for it in items])

    # ------------------------------------------------------------- zoom
    def zoom_percent(self):
        screen_px_per_mm = self.logicalDpiX() / 25.4
        return self.transform().m11() * dpm(self.label) / screen_px_per_mm * 100

    def zoom_by(self, factor):
        s = self.transform().m11() * factor
        if 0.03 <= s <= 60:
            self.scale(factor, factor)
            self._after_zoom()

    def zoom_fit(self):
        w, h = label_size_dots(self.label)
        k = dpm(self.label)
        m = 4 * k
        if columns(self.label) > 1:  # show the whole row so every label can be checked
            left = -self.label["side_margin_mm"] * k
            full = media_width_mm(self.label) * k
            self.fitInView(QRectF(left - m, -m, full + 2 * m, h + 8 * k), Qt.KeepAspectRatio)
        else:
            self.fitInView(QRectF(-m, -m, w + 2 * m, h + 2 * m), Qt.KeepAspectRatio)
        self._after_zoom()

    def zoom_actual(self):
        s = (self.logicalDpiX() / 25.4) / dpm(self.label)
        self.setTransform(QTransform.fromScale(s, s))
        self._after_zoom()

    def _after_zoom(self):
        for it in self.items_by_id.values():
            it.prepareGeometryChange()  # handle size depends on zoom
        self.zoom_changed.emit(self.zoom_percent())

    # ------------------------------------------------------------- events
    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.15 ** (e.angleDelta().y() / 120))
        else:
            super().wheelEvent(e)

    def mouseMoveEvent(self, e):
        p = self.mapToScene(e.pos())
        k = dpm(self.label)
        self.cursor_moved.emit(p.x() / k, p.y() / k)
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if self.doc is not None and self.individual:
            self.set_active_col(self.column_at(self.mapToScene(e.pos()).x()))
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self._dirty and self.individual:
            # An element dropped onto another label now belongs to that label's design.
            k = dpm(self.label)
            for it in self.selected_items():
                col = self.column_at(it.scene_content_rect().center().x())
                old = element_col(it.el)
                if col != old:
                    x = it.el["x"] + (self.col_dx(old) - self.col_dx(col)) / k
                    if self.snap:
                        x = round(x / self.grid_mm) * self.grid_mm
                    it.el["x"] = round(x, 3)
                    it.el["col"] = col
                    it.refresh()
                    self.set_active_col(col)
        if self._dirty:
            self._dirty = False
            self.committed.emit("")

    def keyPressEvent(self, e):
        steps = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        items = self.selected_items()
        if e.key() in steps and items:
            step = self.grid_mm if self.snap else 0.1
            if e.modifiers() & Qt.ShiftModifier:
                step *= 10
            dx, dy = steps[e.key()]
            for it in items:
                it.el["x"] = round(it.el["x"] + dx * step, 3)
                it.el["y"] = round(it.el["y"] + dy * step, 3)
                it.refresh()
            self.live_changed.emit()
            self.committed.emit("nudge")
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------- drawing
    def _draw_page(self, painter, page, radius, rect, grid=True):
        k = dpm(self.label)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawRoundedRect(page.translated(0.8 * k, 0.8 * k), radius, radius)
        painter.setBrush(Qt.white)
        painter.drawRoundedRect(page, radius, radius)
        step = self.grid_mm * k
        if not (grid and self.show_grid and step * self.transform().m11() >= 5):
            return
        visible = rect.intersected(page)
        if visible.isEmpty():
            return
        minor = QPen(QColor(232, 236, 241), 0)
        major = QPen(QColor(205, 212, 222), 0)
        for i in range(max(0, int((visible.left() - page.left()) / step)),
                       int((visible.right() - page.left()) / step) + 1):
            x = page.left() + i * step
            painter.setPen(major if (i * self.grid_mm) % 10 < 1e-6 else minor)
            painter.drawLine(QPointF(x, page.top()), QPointF(x, page.bottom()))
        for j in range(max(0, int(visible.top() / step)), int(visible.bottom() / step) + 1):
            y = j * step
            painter.setPen(major if (j * self.grid_mm) % 10 < 1e-6 else minor)
            painter.drawLine(QPointF(page.left(), y), QPointF(page.right(), y))

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        if self.doc is None:
            return
        k = dpm(self.label)
        w, h = label_size_dots(self.label)
        page = QRectF(0, 0, w, h)
        radius = 1.5 * k
        n = columns(self.label)
        painter.save()
        if n > 1 or self.label["side_margin_mm"] > 0:
            left = -self.label["side_margin_mm"] * k
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(236, 230, 214))  # liner (backing paper)
            painter.drawRect(QRectF(left, -1.5 * k, media_width_mm(self.label) * k, h + 3 * k))
        self._draw_page(painter, page, radius, rect)
        design = column_doc(self.doc, 0)["elements"]
        for col in range(1, n):
            r = page.translated(self.col_dx(col), 0)
            if self.individual:  # every label is edited directly
                self._draw_page(painter, r, radius, rect)
                continue
            self._draw_page(painter, r, radius, rect, grid=False)
            args = self.row_preview[col] if col < len(self.row_preview) else self.preview
            if args is None:  # no record left for this label: it stays blank
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(215, 218, 224), Qt.BDiagPattern))
                painter.drawRoundedRect(r, radius, radius)
                continue
            for el in design:  # live preview of what this label will print
                v = merge.merge_element(el, *args)
                painter.save()
                painter.translate(self.col_dx(col), 0)
                painter.setTransform(render.element_transform(v, self.label), True)
                render.paint(painter, v, self.label)
                painter.restore()
        if any(self.captions):
            f = painter.font()
            f.setPixelSize(max(1, int(2.6 * k)))
            painter.setFont(f)
            painter.setPen(QColor(225, 230, 238))
            for col, text in enumerate(self.captions[:n]):
                painter.drawText(QRectF(self.col_dx(col), h + 2 * k, w, 4 * k),
                                 Qt.AlignHCenter | Qt.AlignTop, text)
        painter.restore()

    def drawForeground(self, painter, rect):
        if self.doc is None:
            return
        k = dpm(self.label)
        w, h = label_size_dots(self.label)
        n = columns(self.label)
        painter.setBrush(Qt.NoBrush)
        for col in range(n):
            r = QRectF(self.col_dx(col), 0, w, h)
            if self.individual and col == self.active_col and n > 1:
                pen = QPen(SELECT_COLOR, 2.5)
                pen.setCosmetic(True)
            elif col == 0 or self.individual:
                pen = QPen(QColor(120, 130, 145), 0)
            else:
                pen = QPen(QColor(150, 160, 175), 0, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(r, 1.5 * k, 1.5 * k)
