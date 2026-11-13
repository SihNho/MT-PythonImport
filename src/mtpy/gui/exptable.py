"""The Experiment table (owner 2026-11-04: rows = parameters, columns = iterations, as the LabVIEW program's table)
and its compiler to the protocol script. Each column is one step: a force change at the motor speed (`ramp ...
speed=`), or a rotation at the rotor speed (`rotate`), then a wait. The script text is what runs, so the check,
the engine and the recording stay as they are; the text box below stays the advanced view.

Owner's example (five columns):
    Force (pN)          1      1      1     50      1
    Wait (s)            0      0      0      0      0
    Motor (mm/s)        0.1    0.1    0.1    0.03   0.1
    Rotor (degree)   -3600   3600      0      0      0
    Rotor speed (SPD)   50     50      0      0      0
A sixth row, Focus (um) (owner 2026-11-12: piezo steps at a fixed force, to measure the bead calibration's accuracy),
is the focus offset from the protocol's start, as `focus um=`; a column whose value differs from the previous one
moves the focus after the force change and before the wait.
"""
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

ROWS = ("Force (pN)", "Wait (s)", "Motor (mm/s)", "Rotor (degree)", "Rotor speed (SPD)", "Focus (um)")
LOADING = ("Motor (mm/s)", "Force rate (pN/s)")   # owner 2026-11-06: magnet loading or force loading, one or the other
EXAMPLE = [[1, 0, 0.1, -3600, 50], [1, 0, 0.1, 3600, 50], [1, 0, 0.1, 0, 0], [50, 0, 0.03, 0, 0], [1, 0, 0.1, 0, 0]]


def compile_table(columns, name="table", repeat=1, force_rate=False):
    """columns: [[force_pN, wait_s, loading, rotor_deg, rotor_spd, focus_um], ...] (focus_um may be left out: 0)
    -> the protocol script text; repeat > 1
    wraps the columns in `loop n=repeat` (owner 2026-11-05: cycle repeat). loading is the magnet speed in mm/s
    (`ramp speed=`), or with force_rate=True the force loading rate in pN/s (`ramp rate=`; owner 2026-11-06: the
    two are exclusive, the table's Loading choice).
    A rotation column turns by the degrees at the SPD speed (the force set first, as `rotate` does); a column whose
    force differs from the previous one ramps to it at the loading value (`hold` when it is 0); a wait follows when
    given; an empty column is a comment. ValueError names the column of a bad value."""
    lines = ["grammar 0.1", f'protocol "{name}"', f"loading {'force' if force_rate else 'magnet'}"]
    repeat = int(repeat)
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    if repeat > 1:
        lines.append(f"loop n={repeat}")
    prev_f, turns, prev_foc = None, 0.0, 0.0
    for k, col in enumerate(columns, 1):
        try:
            f, w, v, deg, spd, foc = (float(x) if str(x).strip() != "" else 0.0 for x in (list(col) + [0.0])[:6])
        except (TypeError, ValueError) as e:
            raise ValueError(f"column {k}: not a number ({e})") from None
        if f < 0 or w < 0 or v < 0 or spd < 0:
            raise ValueError(f"column {k}: force, wait, loading and rotor speed must be >= 0")
        done = []
        if deg != 0:
            if spd <= 0:
                raise ValueError(f"column {k}: a rotation of {deg:g} degrees needs a rotor speed (SPD > 0)")
            done.append(f"rotate from={turns:g} to={turns + deg / 360.0:g} f={f:g} spd={spd:g}")
            turns += deg / 360.0
            prev_f = f
        elif prev_f is None:
            done.append(f"hold f={f:g} t={0.0 if foc != prev_foc else w:g}")
            w = w if foc != prev_foc else 0.0
        elif f != prev_f:
            key = "rate" if force_rate else "speed"
            done.append(f"ramp from={prev_f:g} to={f:g} {key}={v:g}" if v > 0 else f"hold f={f:g} t=0")
        prev_f = f
        if foc != prev_foc:
            done.append(f"focus um={foc:g}")
            prev_foc = foc
        if w > 0:
            done.append(f"wait t={w:g}")
        lines.append(f"# column {k}" + ("" if done else ": nothing to do"))
        lines += done
    if repeat > 1:
        lines.append("end")
    lines.append("end protocol")
    return "\n".join(lines) + "\n"


def parse_script(text):
    """The reverse of compile_table (owner 2026-11-10: "script -> table"): the script text -> (columns, repeat,
    force_rate). Only a script of the table's shape fits: hold / ramp / rotate / focus / wait lines, one loop around
    all of them. ValueError names the first line the table cannot hold. A value the script does not carry (the
    loading of a hold or rotate column) is 0."""
    cols, repeat, rate, prev_f, turns, in_loop, closed, foc = [], 1, None, None, 0.0, False, False, 0.0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        word, _, rest = line.partition(" ")
        bad = f"line {n} ({line})"
        if line.startswith("#"):
            if "nothing to do" in line and prev_f is not None:
                cols.append([prev_f, 0.0, 0.0, 0.0, 0.0, foc])
            continue
        if not line or word in ("grammar", "protocol") or line == "end protocol":
            continue
        if word == "loading":
            rate = rest.strip() == "force"
            continue
        if closed:
            raise ValueError(f"{bad}: the table holds one loop around every step, nothing after it")
        if line == "end" and in_loop:
            closed = True
            continue
        try:
            a = {k: float(v) for k, v in (tok.split("=", 1) for tok in rest.split())}
        except ValueError:
            raise ValueError(f"{bad}: the table holds plain numbers only") from None
        if word == "loop" and not cols and not in_loop and set(a) == {"n"}:
            in_loop, repeat = True, int(a["n"])
        elif word == "hold" and set(a) == {"f", "t"}:
            cols.append([a["f"], a["t"], 0.0, 0.0, 0.0, foc])
            prev_f = a["f"]
        elif word == "ramp" and set(a) in ({"from", "to", "speed"}, {"from", "to", "rate"}):
            if a["from"] != prev_f:
                raise ValueError(f"{bad}: a table ramp starts at the previous force ({prev_f})")
            if rate is not None and rate != ("rate" in a):
                raise ValueError(f"{bad}: the table has one loading kind (speed= or rate=) for every ramp")
            rate = "rate" in a
            cols.append([a["to"], 0.0, a.get("speed", a.get("rate")), 0.0, 0.0, foc])
            prev_f = a["to"]
        elif word == "rotate" and set(a) == {"from", "to", "f", "spd"}:
            if a["from"] != turns:
                raise ValueError(f"{bad}: a table rotation starts where the last one ended ({turns:g} turns)")
            cols.append([a["f"], 0.0, 0.0, (a["to"] - a["from"]) * 360.0, a["spd"], foc])
            prev_f, turns = a["f"], a["to"]
        elif word == "focus" and set(a) == {"um"} and cols:
            if cols[-1][1] or cols[-1][5] != foc:      # the column already waited, or already moved the focus
                cols.append([prev_f, 0.0, 0.0, 0.0, 0.0, a["um"]])
            else:
                cols[-1][5] = a["um"]
            foc = a["um"]
        elif word == "wait" and set(a) == {"t"} and cols:
            if cols[-1][1]:
                cols.append([prev_f, a["t"], 0.0, 0.0, 0.0, foc])
            else:
                cols[-1][1] = a["t"]
        else:
            raise ValueError(f"{bad}: the table cannot hold this line")
    if not cols:
        raise ValueError("no hold / ramp / rotate / focus / wait line in the script")
    return cols, repeat, bool(rate)


class ExpTable(QWidget):
    """The table with add / remove column buttons; `columns()` reads it, `to_script()` compiles it."""

    def __init__(self, on_script, on_start, on_table):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(len(ROWS), 0)
        self.table.setVerticalHeaderLabels(ROWS)
        self.table.setMinimumHeight(220)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.btn_add = QPushButton("+ column", clicked=lambda: self.add_column())
        self.btn_del = QPushButton("- column", clicked=self.remove_column)
        self.btn_script = QPushButton("Table -> script", clicked=on_script)
        self.btn_table = QPushButton("Script -> table", clicked=on_table)
        self.btn_table.setToolTip("Fill the table from the script below (replaces the table). Only a script of the "
                                  "table's shape fits: hold / ramp / rotate / focus / wait, one loop around them "
                                  "at most.")
        self.btn_start = QPushButton("Start from table", clicked=on_start)
        self.btn_example = QPushButton("Load example", clicked=lambda: self.set_columns(EXAMPLE))
        self.repeat = QSpinBox()              # owner 2026-11-05: cycle repeat -> loop n=
        self.repeat.setRange(1, 100000)
        self.repeat.setPrefix("repeat ")
        self.repeat.setSuffix(" x")
        self.loading = QComboBox()            # owner 2026-11-06: magnet loading (mm/s) or force loading (pN/s)
        self.loading.addItems(LOADING)
        self.loading.currentIndexChanged.connect(self._loading_changed)
        self.info = QLabel("columns = steps: a force change at the loading value (Motor mm/s, or Force rate pN/s: the "
                           "true loading rate), or a rotation at the rotor speed; then the focus step (um from "
                           "the protocol's start, when it changes); then the wait")
        self.info.setWordWrap(True)
        for w in (self.btn_add, self.btn_del, self.btn_example, self.repeat, QLabel("Loading"), self.loading):
            row.addWidget(w)
        lay.addLayout(row)
        row2 = QHBoxLayout()               # design critique review 2026-11-05: one row cut the button texts off
        for w in (self.btn_script, self.btn_table, self.btn_start):
            row2.addWidget(w)
        lay.addLayout(row2)
        lay.addWidget(self.info)
        self.add_column()     # design critique 2026-11-05 #1: the table opens empty (one zero column), never pre-filled

    def add_column(self, values=None):
        c = self.table.columnCount()
        self.table.insertColumn(c)
        self.table.setHorizontalHeaderItem(c, QTableWidgetItem(str(c + 1)))
        last = [self.table.item(r, c - 1).text() if c and self.table.item(r, c - 1) else "0" for r in range(len(ROWS))]
        for r, v in enumerate(values if values is not None else last):
            self.table.setItem(r, c, QTableWidgetItem(f"{v:g}" if isinstance(v, (int, float)) else str(v)))
        self.table.setColumnWidth(c, 70)

    def remove_column(self):
        if self.table.columnCount():
            self.table.removeColumn(self.table.columnCount() - 1)

    def columns(self):
        return [[(self.table.item(r, c).text() if self.table.item(r, c) else "0") for r in range(len(ROWS))]
                for c in range(self.table.columnCount())]

    def set_columns(self, columns):
        while self.table.columnCount():
            self.table.removeColumn(0)
        for col in columns:
            self.add_column(col)

    def from_script(self, text):
        columns, repeat, force_rate = parse_script(text)       # raises before the table is touched
        self.set_columns(columns)
        self.repeat.setValue(repeat)
        self.loading.setCurrentIndex(int(force_rate))

    def highlight(self, col):
        """Colour the running column (owner 2026-11-06); None clears."""
        for c in range(self.table.columnCount()):
            for r in range(len(ROWS)):
                it = self.table.item(r, c)
                if it is not None:
                    it.setBackground(QBrush(QColor("#ffd54f")) if c == col else QBrush())
                    it.setForeground(QBrush(QColor("black")) if c == col else QBrush())

    def _loading_changed(self, i):
        self.table.setVerticalHeaderItem(2, QTableWidgetItem(LOADING[i]))

    @property
    def force_rate(self):
        return self.loading.currentIndex() == 1

    def to_script(self, name="table"):
        return compile_table(self.columns(), name, self.repeat.value(), self.force_rate)
