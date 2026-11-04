"""A settings panel generated from a device's attribute catalogue (owner 2026-11-04: "the camera has far more
controls than exposure, rate and gain, and one page cannot hold them"): a category tree with search and a
visibility level (NI MAX's beginner / expert / guru), each attribute edited by a control of its type, a favourites
group on top (the few an experiment changes, kept per device in a JSON file next to the touch position), every write
read back. The same panel serves the EMCCD from `api.emccd.catalogue()`."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

LEVELS = ("beginner", "expert", "guru")


def make_control(entry, value):
    """A control for one catalogue entry holding `value`; `.value()` gives what to write (None for a command)."""
    t, ro = entry["type"], entry["access"] == "ro"
    if ro:
        w = QLabel(str(value))
        w.value = lambda: None
        return w
    if t == "int":
        w = QSpinBox()
        w.setRange(int(entry.get("min", -2**31)), int(min(entry.get("max", 2**31 - 1), 2**31 - 1)))
        w.setSingleStep(int(entry.get("step") or 1))
        if value is not None:
            w.setValue(int(value))
        return w
    if t == "float":
        w = QDoubleSpinBox()
        w.setDecimals(3)
        w.setRange(float(entry.get("min", -1e12)), float(entry.get("max", 1e12)))
        w.setSingleStep(float(entry.get("step") or 1.0))
        if value is not None:
            w.setValue(float(value))
        return w
    if t == "enum":
        w = QComboBox()
        for v in entry.get("values") or []:
            w.addItem(str(v), v)
        if value is not None and w.findData(value) >= 0:
            w.setCurrentIndex(w.findData(value))
        w.value = w.currentData
        return w
    if t == "bool":
        w = QCheckBox()
        w.setChecked(bool(value))
        w.value = w.isChecked
        return w
    if t == "command":
        w = QLabel("(command)")
        w.value = lambda: True
        return w
    w = QLineEdit(str(value if value is not None else ""))
    w.value = w.text
    return w


class AttrPanel(QWidget):
    """catalogue_fn() -> entries; get_fn(name) -> value; set_fn(name, value) -> read-back (raises on a refusal);
    call(fn, what, done) runs fn off the GUI thread (MainWindow._call); favourites: the JSON file of this device."""

    def __init__(self, title, catalogue_fn, get_fn, set_fn, call, favourites):
        super().__init__()
        self.title, self.catalogue_fn, self.get_fn, self.set_fn, self.call = title, catalogue_fn, get_fn, set_fn, call
        self.favourites_file = Path(favourites)
        self.entries, self.values, self.favourites = {}, {}, self._load_favourites()
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("search attributes")
        self.search.textChanged.connect(self._fill_tree)
        self.level = QComboBox()
        for lv in LEVELS:
            self.level.addItem(lv, lv)
        self.level.currentIndexChanged.connect(self._fill_tree)
        self.btn_load = QPushButton("Load from device", clicked=self.load)
        for w in (QLabel(f"{title} attributes"), self.search, QLabel("level"), self.level, self.btn_load):
            top.addWidget(w)
        lay.addLayout(top)
        self.fav_group = QGroupBox("Favourites (kept per device; the experiment's few)")
        self.fav_form = QFormLayout(self.fav_group)
        lay.addWidget(self.fav_group)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Attribute", "Value", "Description"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 140)
        self.tree.setMinimumHeight(260)
        self.tree.itemClicked.connect(self._pick)
        lay.addWidget(self.tree, 1)
        self.detail = QGroupBox("Selected")
        self.detail_form = QFormLayout(self.detail)
        lay.addWidget(self.detail)
        self.status = QLabel("not loaded: Load from device")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.selected, self.control = None, None

    # --- favourites -------------------------------------------------------------------------------------------------
    def _load_favourites(self):
        try:
            return list(json.loads(self.favourites_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _save_favourites(self):
        try:
            self.favourites_file.parent.mkdir(parents=True, exist_ok=True)
            self.favourites_file.write_text(json.dumps(self.favourites, indent=1), encoding="utf-8")
        except OSError:
            pass

    def toggle_favourite(self, name):
        if name in self.favourites:
            self.favourites.remove(name)
        else:
            self.favourites.append(name)
        self._save_favourites()
        self._fill_favourites()

    # --- loading ----------------------------------------------------------------------------------------------------
    def load(self):
        """Read the catalogue and every readable value (one worker; the camera answers ~200 reads in well under a
        second), then fill the tree and the favourites."""
        self.status.setText("loading...")

        def job():
            cat = self.catalogue_fn()
            vals = {}
            for e in cat:
                if e["access"] != "wo" and e["type"] != "command":
                    try:
                        vals[e["name"]] = self.get_fn(e["name"])
                    except Exception as ex:  # noqa: BLE001 - one unreadable attribute must not hide the rest
                        vals[e["name"]] = f"? {type(ex).__name__}"
            return cat, vals

        def done(res):
            cat, vals = res
            self.entries = {e["name"]: e for e in cat}
            self.values = vals
            self._fill_tree()
            self._fill_favourites()
            self.status.setText(f"{len(cat)} attributes in {len({e['category'] for e in cat})} categories")
        self.call(job, f"{self.title} attributes", done)

    def _visible(self, e):
        q = self.search.text().strip().lower()
        lv = LEVELS.index(self.level.currentData() or "beginner")
        return (LEVELS.index(e.get("visibility", "beginner")) <= lv
                and (not q or q in e["name"].lower() or q in e["category"].lower() or q in (e.get("description") or "").lower()))

    def _fill_tree(self):
        self.tree.clear()
        by_cat = {}
        for e in self.entries.values():
            if self._visible(e):
                by_cat.setdefault(e["category"], []).append(e)
        for cat, rows in by_cat.items():
            node = QTreeWidgetItem([cat, "", ""])
            node.setFlags(node.flags() & ~Qt.ItemIsSelectable)
            for e in rows:
                item = QTreeWidgetItem([e["name"], self._fmt(self.values.get(e["name"])), e.get("description") or ""])
                item.setData(0, Qt.UserRole, e["name"])
                node.addChild(item)
            self.tree.addTopLevelItem(node)
            node.setExpanded(bool(self.search.text().strip()))

    @staticmethod
    def _fmt(v):
        return "" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v))

    def _fill_favourites(self):
        while self.fav_form.rowCount():
            self.fav_form.removeRow(0)
        for name in [n for n in self.favourites if n in self.entries]:
            e = self.entries[name]
            ctl = make_control(e, self.values.get(name))
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(ctl)
            h.addWidget(QPushButton("Set" if e["type"] != "command" else "Run",
                                    clicked=lambda _=False, n=name, c=ctl: self.write(n, c.value())))
            h.addWidget(QPushButton("remove", clicked=lambda _=False, n=name: self.toggle_favourite(n)))
            self.fav_form.addRow(f"{name} ({e['category']})", row)

    # --- one attribute ----------------------------------------------------------------------------------------------
    def _pick(self, item, _col):
        name = item.data(0, Qt.UserRole)
        if name:
            self.select(name)

    def select(self, name):
        e = self.entries[name]
        self.selected = name
        while self.detail_form.rowCount():
            self.detail_form.removeRow(0)
        self.detail.setTitle(f"{name}  ({e['category']}, {e['type']}, {e['access']}, {e.get('visibility', '')})")
        desc = QLabel(e.get("description") or "")
        desc.setWordWrap(True)
        self.detail_form.addRow(desc)
        rng = " .. ".join(str(e[k]) for k in ("min", "max") if e.get(k) is not None)
        if rng:
            self.detail_form.addRow("range", QLabel(rng + (f", step {e['step']}" if e.get("step") else "")))
        self.control = make_control(e, self.values.get(name))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.control)
        if e["access"] != "ro":
            h.addWidget(QPushButton("Set" if e["type"] != "command" else "Run",
                                    clicked=lambda: self.write(name, self.control.value())))
        h.addWidget(QPushButton("remove from favourites" if name in self.favourites else "add to favourites",
                                clicked=lambda: (self.toggle_favourite(name), self.select(name))))
        self.detail_form.addRow("value", row)

    def write(self, name, value):
        def done(got):
            self.values[name] = got
            self.status.setText(f"{name} = {self._fmt(got)} (read back)")
            self._fill_tree()
            self._fill_favourites()
        self.call(lambda: self.set_fn(name, value), f"{self.title} {name}", done)
