"""Data source dialog and the Data panel (fields, records, preview navigation)."""
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                             QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStackedWidget, QTableView,
                             QToolButton, QVBoxLayout, QWidget)

from . import datasource
from .merge import format_value
from .model import FILL_OPTIONS

class RecordsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns, self.rows = [], []

    def set_data(self, columns, rows):
        self.beginResetModel()
        self.columns, self.rows = list(columns), rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if role in (Qt.DisplayRole, Qt.ToolTipRole) and index.isValid():
            return format_value(self.rows[index.row()].get(self.columns[index.column()]))
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section] if section < len(self.columns) else None
        return section + 1


def _table_view(model):
    v = QTableView()
    v.setModel(model)
    v.setSelectionBehavior(QAbstractItemView.SelectRows)
    v.setEditTriggers(QAbstractItemView.NoEditTriggers)
    v.setAlternatingRowColors(True)
    v.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    v.horizontalHeader().setDefaultSectionSize(110)
    v.verticalHeader().setDefaultSectionSize(22)
    return v


# ============================================================================ dialog
class DataSourceDialog(QDialog):
    """Pick a CSV / Excel / SQLite / ODBC source, preview it and load it."""

    def __init__(self, parent, source=None):
        super().__init__(parent)
        self.setWindowTitle("Data source")
        self.resize(720, 560)
        self.loaded = None  # (columns, rows) after a successful load
        src = source or {}

        self.kind = QComboBox()
        for _, name in datasource.KINDS:
            self.kind.addItem(name)
        self.stack = QStackedWidget()

        # ---- CSV
        page = QWidget()
        f = QFormLayout(page)
        self.csv_path = self._path_row(f, "CSV files (*.csv *.txt *.tsv);;All files (*)")
        self.csv_delim = QComboBox()
        self._delims = ["auto", ",", ";", "\t", "|"]
        self.csv_delim.addItems(["Auto-detect", "Comma ,", "Semicolon ;", "Tab", "Pipe |"])
        self.csv_enc = QComboBox()
        self._encs = ["auto", "utf-8", "cp1252", "utf-16"]
        self.csv_enc.addItems(["Auto (UTF-8 / Windows)", "UTF-8", "Windows-1252", "UTF-16"])
        self.csv_header = QCheckBox("First row has column names")
        self.csv_header.setChecked(True)
        f.addRow("Separator", self.csv_delim)
        f.addRow("Encoding", self.csv_enc)
        f.addRow("", self.csv_header)
        self.stack.addWidget(page)

        # ---- Excel
        page = QWidget()
        f = QFormLayout(page)
        self.xlsx_path = self._path_row(f, "Excel workbooks (*.xlsx *.xlsm);;All files (*)", self._load_sheets)
        self.xlsx_sheet = QComboBox()
        self.xlsx_header = QCheckBox("First row has column names")
        self.xlsx_header.setChecked(True)
        f.addRow("Sheet", self.xlsx_sheet)
        f.addRow("", self.xlsx_header)
        self.stack.addWidget(page)

        # ---- SQLite
        page = QWidget()
        f = QFormLayout(page)
        self.sqlite_path = self._path_row(f, "SQLite databases (*.db *.sqlite *.sqlite3 *.db3);;All files (*)",
                                          self._load_sqlite_tables)
        self.sqlite_table = QComboBox()
        self.sqlite_table.activated.connect(lambda _: self._table_chosen("sqlite"))
        self.sqlite_cols = self._columns_label()
        self.sqlite_query = QPlainTextEdit()
        self.sqlite_query.setPlaceholderText("SELECT * FROM products")
        self.sqlite_query.setMaximumHeight(70)
        f.addRow("Table", self.sqlite_table)
        f.addRow("Columns", self.sqlite_cols)
        f.addRow("Query", self.sqlite_query)
        self.stack.addWidget(page)

        # ---- ODBC database with credentials
        page = QWidget()
        f = QFormLayout(page)
        self.odbc_driver = QComboBox()
        drivers = datasource.odbc_drivers()
        self.odbc_driver.addItems(drivers)
        if not drivers:
            self.odbc_driver.addItem("(no ODBC drivers found)")
        self.odbc_driver.currentIndexChanged.connect(lambda _: self._driver_changed())
        self.odbc_server = QLineEdit()
        self.odbc_server.setPlaceholderText("e.g. localhost\\SQLEXPRESS or 192.168.1.10")
        self.odbc_port = QLineEdit()
        self.odbc_port.setPlaceholderText("default")
        self.odbc_port.setMaximumWidth(80)
        srow = QHBoxLayout()
        srow.addWidget(self.odbc_server, 1)
        srow.addWidget(QLabel("Port"))
        srow.addWidget(self.odbc_port)
        self.odbc_db = QLineEdit()
        self.odbc_trusted = QCheckBox("Windows authentication (no password)")
        self.odbc_trusted.toggled.connect(lambda _: self._driver_changed())
        self.odbc_user = QLineEdit()
        self.odbc_pass = QLineEdit()
        self.odbc_pass.setEchoMode(QLineEdit.Password)
        self.odbc_save_pw = QCheckBox("Save password in the design file")
        self.odbc_save_pw.setToolTip("If unticked, you are asked for the password when the design is opened.")
        trow = QHBoxLayout()
        self.odbc_table = QComboBox()
        self.odbc_table.setMinimumWidth(200)
        self.odbc_table.activated.connect(lambda _: self._table_chosen("odbc"))
        list_btn = QPushButton("Connect && list tables")
        list_btn.clicked.connect(self._load_odbc_tables)
        trow.addWidget(self.odbc_table, 1)
        trow.addWidget(list_btn)
        self.odbc_cols = self._columns_label()
        self.odbc_query = QPlainTextEdit()
        self.odbc_query.setPlaceholderText("SELECT * FROM products   (add WHERE / ORDER BY as needed)")
        self.odbc_query.setMaximumHeight(70)
        self.odbc_custom = QLineEdit()
        self.odbc_custom.setPlaceholderText("Optional: full ODBC connection string (overrides the fields above)")
        f.addRow("Driver", self.odbc_driver)
        self._server_label = QLabel("Server")
        f.addRow(self._server_label, srow)
        self._db_label = QLabel("Database")
        f.addRow(self._db_label, self.odbc_db)
        f.addRow("", self.odbc_trusted)
        f.addRow("User", self.odbc_user)
        f.addRow("Password", self.odbc_pass)
        f.addRow("", self.odbc_save_pw)
        f.addRow("Table", trow)
        f.addRow("Columns", self.odbc_cols)
        f.addRow("Query", self.odbc_query)
        f.addRow("Advanced", self.odbc_custom)
        self.stack.addWidget(page)
        self._driver_changed()

        self.kind.currentIndexChanged.connect(self.stack.setCurrentIndex)

        # ---- preview
        self.preview_model = RecordsModel(self)
        self.preview = _table_view(self.preview_model)
        self.status = QLabel("Click Preview to check the data.")
        preview_btn = QPushButton("Preview")
        preview_btn.clicked.connect(self._preview)
        prow = QHBoxLayout()
        prow.addWidget(self.status, 1)
        prow.addWidget(preview_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Use this data")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        top = QFormLayout()
        top.addRow("Source type", self.kind)
        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.stack)
        root.addLayout(prow)
        root.addWidget(self.preview, 1)
        root.addWidget(buttons)

        self._apply(src)

    # ------------------------------------------------------------------ helpers
    def _path_row(self, form, filt, on_change=None):
        row = QHBoxLayout()
        edit = QLineEdit()
        btn = QPushButton("Browse...")

        def browse():
            path, _ = QFileDialog.getOpenFileName(self, "Choose file", edit.text(), filt)
            if path:
                edit.setText(path)
                if on_change:
                    on_change()

        btn.clicked.connect(browse)
        if on_change:
            edit.editingFinished.connect(on_change)
        row.addWidget(edit, 1)
        row.addWidget(btn)
        form.addRow("File", row)
        return edit

    def _error(self, e):
        QMessageBox.warning(self, "Data source", str(e))

    def _load_sheets(self):
        current = self.xlsx_sheet.currentText()
        self.xlsx_sheet.clear()
        try:
            self.xlsx_sheet.addItems(datasource.sheet_names(self.xlsx_path.text()))
        except Exception as e:
            self.status.setText(f"Could not read sheets: {e}")
            return
        if current:
            self.xlsx_sheet.setCurrentText(current)

    @staticmethod
    def _columns_label():
        lab = QLabel("-")
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setStyleSheet("color: #2a5d9f;")
        return lab

    def _load_sqlite_tables(self):
        self.sqlite_table.clear()
        try:
            tables = datasource.sqlite_tables(self.sqlite_path.text())
        except Exception as e:
            self.status.setText(f"Could not read tables: {e}")
            return
        self.sqlite_table.addItems(tables)
        if tables and not self.sqlite_query.toPlainText().strip():
            self._table_chosen("sqlite")

    def _load_odbc_tables(self):
        current = self.odbc_table.currentText()
        self.odbc_table.clear()
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                tables = datasource.odbc_tables(self.source())
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as e:
            self._error(e)
            return
        self.odbc_table.addItems(tables)
        if current in tables:
            self.odbc_table.setCurrentText(current)
        self.status.setText(f"Connected - {len(tables)} tables / views found. Pick a table.")

    def _table_chosen(self, kind):
        """Show the table's columns (they become the label fields) and fill in the query."""
        src = self.source()
        if kind == "sqlite":
            table, cols_label, query = self.sqlite_table.currentText(), self.sqlite_cols, self.sqlite_query
        else:
            table, cols_label, query = self.odbc_table.currentText(), self.odbc_cols, self.odbc_query
        if not table:
            return
        try:
            if kind == "sqlite":
                cols = datasource.sqlite_columns(src["path"], table)
            else:
                cols = datasource.odbc_columns(src, table)
            cols_label.setText(", ".join(cols) or "-")
        except Exception as e:
            cols_label.setText(f"(could not read columns: {e})")
        query.setPlainText(f"SELECT * FROM {datasource.quote_table(src, table)}")

    def _driver_changed(self):
        fam = datasource.driver_family(self.odbc_driver.currentText())
        access = fam == "access"
        self._server_label.setVisible(not access)
        for w in (self.odbc_server, self.odbc_port):
            w.setVisible(not access)
        self._db_label.setText("Database file" if access else "Database")
        self.odbc_trusted.setVisible(fam == "mssql")
        windows_auth = fam == "mssql" and self.odbc_trusted.isChecked()
        for w in (self.odbc_user, self.odbc_pass):
            w.setEnabled(not windows_auth)

    # ------------------------------------------------------------------ source
    def _apply(self, src):
        kinds = [k for k, _ in datasource.KINDS]
        kind = src.get("kind", "csv")
        self.kind.setCurrentIndex(kinds.index(kind) if kind in kinds else 0)
        self.stack.setCurrentIndex(self.kind.currentIndex())
        if kind == "csv":
            self.csv_path.setText(src.get("path", ""))
            d = src.get("delimiter", "auto")
            self.csv_delim.setCurrentIndex(self._delims.index(d) if d in self._delims else 0)
            e = src.get("encoding", "auto")
            self.csv_enc.setCurrentIndex(self._encs.index(e) if e in self._encs else 0)
            self.csv_header.setChecked(src.get("header", True))
        elif kind == "xlsx":
            self.xlsx_path.setText(src.get("path", ""))
            self._load_sheets()
            if src.get("sheet"):
                self.xlsx_sheet.setCurrentText(src["sheet"])
            self.xlsx_header.setChecked(src.get("header", True))
        elif kind == "sqlite":
            self.sqlite_path.setText(src.get("path", ""))
            self.sqlite_query.setPlainText(src.get("query", ""))
            self._load_sqlite_tables()
        elif kind == "odbc":
            if src.get("driver"):
                if self.odbc_driver.findText(src["driver"]) < 0:
                    self.odbc_driver.addItem(src["driver"])
                self.odbc_driver.setCurrentText(src["driver"])
            self.odbc_server.setText(src.get("server", ""))
            self.odbc_port.setText(str(src.get("port", "")))
            self.odbc_db.setText(src.get("database", ""))
            self.odbc_trusted.setChecked(src.get("trusted", False))
            self.odbc_user.setText(src.get("user", ""))
            self.odbc_pass.setText(src.get("password", ""))
            self.odbc_save_pw.setChecked(src.get("save_password", False))
            if src.get("table"):
                self.odbc_table.addItem(src["table"])
            self.odbc_query.setPlainText(src.get("query", ""))
            self.odbc_custom.setText(src.get("connection", ""))
            self._driver_changed()

    def source(self):
        kind = datasource.KINDS[self.kind.currentIndex()][0]
        if kind == "csv":
            return {"kind": kind, "path": self.csv_path.text().strip(),
                    "delimiter": self._delims[self.csv_delim.currentIndex()],
                    "encoding": self._encs[self.csv_enc.currentIndex()],
                    "header": self.csv_header.isChecked()}
        if kind == "xlsx":
            return {"kind": kind, "path": self.xlsx_path.text().strip(),
                    "sheet": self.xlsx_sheet.currentText(), "header": self.xlsx_header.isChecked()}
        if kind == "sqlite":
            return {"kind": kind, "path": self.sqlite_path.text().strip(),
                    "query": self.sqlite_query.toPlainText().strip()}
        return {"kind": kind, "driver": self.odbc_driver.currentText(),
                "server": self.odbc_server.text().strip(), "port": self.odbc_port.text().strip(),
                "database": self.odbc_db.text().strip(), "trusted": self.odbc_trusted.isChecked(),
                "user": self.odbc_user.text().strip(), "password": self.odbc_pass.text(),
                "save_password": self.odbc_save_pw.isChecked(), "table": self.odbc_table.currentText(),
                "query": self.odbc_query.toPlainText().strip(), "connection": self.odbc_custom.text().strip()}

    def _try_load(self):
        try:
            cols, rows = datasource.load(self.source())
        except Exception as e:
            self._error(e)
            return None
        self.preview_model.set_data(cols, rows[:200])
        self.status.setText(f"{len(rows)} records, {len(cols)} columns"
                            + (" (showing first 200)" if len(rows) > 200 else ""))
        return cols, rows

    def _preview(self):
        self._try_load()

    def _accept(self):
        result = self._try_load()
        if result is None:
            return
        if not result[1]:
            self._error("The data source has no records.")
            return
        self.loaded = result
        self.accept()


# ============================================================================ panel
class DataPanel(QWidget):
    """Records of the data source, with the record shown on the label."""
    record_changed = pyqtSignal()       # current record or preview toggle changed
    fill_changed = pyqtSignal(str)      # "next" / "same" for labels across

    NO_SOURCE = ("No data source. Use <b>Data &gt; Data Source...</b> to print one label per row "
                 "of an Excel / CSV file or a database table.")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns, self.rows = [], []

        self.source_label = QLabel(self.NO_SOURCE)
        self.source_label.setWordWrap(True)

        self.show_preview = QCheckBox("Show record on label")
        self.show_preview.setChecked(True)
        self.show_preview.toggled.connect(lambda _: self.record_changed.emit())
        self.b_prev = QToolButton()
        self.b_prev.setArrowType(Qt.LeftArrow)
        self.b_prev.clicked.connect(lambda: self.set_current(self.current_index() - 1))
        self.b_next = QToolButton()
        self.b_next.setArrowType(Qt.RightArrow)
        self.b_next.clicked.connect(lambda: self.set_current(self.current_index() + 1))
        self.record_spin = QSpinBox()
        self.record_spin.setRange(1, 1)
        self.record_spin.valueChanged.connect(self._on_spin)
        self.count_label = QLabel("of 0")
        self.fill_label = QLabel("Labels across:")
        self.fill = QComboBox()
        for value, text in FILL_OPTIONS:
            self.fill.addItem(text, value)
        self.fill.setToolTip("For 2-up / 3-up media: give each label in a row the next record, "
                             "or print the same record on every label of the row.")
        self.fill.currentIndexChanged.connect(lambda i: self.fill_changed.emit(self.fill.itemData(i)))
        top = QHBoxLayout()
        top.addWidget(self.source_label, 1)
        top.addWidget(self.fill_label)
        top.addWidget(self.fill)
        top.addSpacing(12)
        top.addWidget(self.show_preview)
        top.addSpacing(12)
        top.addWidget(QLabel("Record"))
        top.addWidget(self.b_prev)
        top.addWidget(self.record_spin)
        top.addWidget(self.b_next)
        top.addWidget(self.count_label)

        self.model = RecordsModel(self)
        self.table = _table_view(self.model)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.selectionModel().currentRowChanged.connect(
            lambda cur, _: cur.isValid() and self.set_current(cur.row(), from_table=True))

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addLayout(top)
        root.addWidget(self.table, 1)
        self.set_data([], [], None)

    def set_data(self, columns, rows, description):
        self.columns, self.rows = list(columns), rows
        self.model.set_data(columns, rows)
        has = bool(rows)
        self.source_label.setText(f"<b>{description}</b> - {len(rows)} records" if description
                                  else self.NO_SOURCE)
        for w in (self.show_preview, self.b_prev, self.b_next, self.record_spin):
            w.setEnabled(has)
        self.record_spin.blockSignals(True)
        self.record_spin.setRange(1, max(1, len(rows)))
        self.record_spin.setValue(1)
        self.record_spin.blockSignals(False)
        self.count_label.setText(f"of {len(rows)}")
        if has:
            self.table.selectRow(0)
        self.record_changed.emit()

    def set_fill(self, fill, columns):
        """Show the labels-across choice only for multi-up media."""
        self.fill.blockSignals(True)
        self.fill.setCurrentIndex(max(0, self.fill.findData(fill)))
        self.fill.blockSignals(False)
        self.fill.setVisible(columns > 1)
        self.fill_label.setVisible(columns > 1)

    def current_index(self):
        return self.record_spin.value() - 1

    def current_record(self):
        if self.rows and self.show_preview.isChecked():
            return self.rows[self.current_index()]
        return None

    def set_current(self, index, from_table=False):
        if not self.rows:
            return
        if getattr(self, "_moving", False):
            return
        index = max(0, min(len(self.rows) - 1, index))
        self._moving = True
        try:
            self.record_spin.blockSignals(True)
            self.record_spin.setValue(index + 1)
            self.record_spin.blockSignals(False)
            if not from_table:
                self.table.selectRow(index)
        finally:
            self._moving = False
        self.record_changed.emit()

    def _on_spin(self, value):
        self.set_current(value - 1)

    def selected_indices(self):
        return sorted({i.row() for i in self.table.selectionModel().selectedRows()})
