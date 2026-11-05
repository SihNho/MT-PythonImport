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
"""
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtpy.devices.autonics import PULSES_PER_TURN

ROWS = ("Force (pN)", "Wait (s)", "Motor (mm/s)", "Rotor (degree)", "Rotor speed (SPD)")
SPD_TO_TURNS_S = 10.0 / PULSES_PER_TURN     # shortcut: the Autonics multiplier assumed 10 as in devices/autonics.py, upgrade when read
EXAMPLE = [[1, 0, 0.1, -3600, 50], [1, 0, 0.1, 3600, 50], [1, 0, 0.1, 0, 0], [50, 0, 0.03, 0, 0], [1, 0, 0.1, 0, 0]]


def compile_table(columns, name="table", repeat=1):
    """columns: [[force_pN, wait_s, motor_mm_s, rotor_deg, rotor_spd], ...] -> the protocol script text; repeat > 1
    wraps the columns in `loop n=repeat` (owner 2026-11-05: cycle repeat).
    A rotation column turns by the degrees at the SPD speed (the force set first, as `rotate` does); a column whose
    force differs from the previous one ramps to it at the motor speed (`hold` when no speed is given); a wait
    follows when given; an empty column is a comment. ValueError names the column of a bad value."""
    lines = ["grammar 0.1", f'protocol "{name}"']
    repeat = int(repeat)
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    if repeat > 1:
        lines.append(f"loop n={repeat}")
    prev_f, turns = None, 0.0
    for k, col in enumerate(columns, 1):
        try:
            f, w, v, deg, spd = (float(x) if str(x).strip() != "" else 0.0 for x in col)
        except (TypeError, ValueError) as e:
            raise ValueError(f"column {k}: not a number ({e})") from None
        if f < 0 or w < 0 or v < 0 or spd < 0:
            raise ValueError(f"column {k}: force, wait, motor speed and rotor speed must be >= 0")
        done = []
        if deg != 0:
            if spd <= 0:
                raise ValueError(f"column {k}: a rotation of {deg:g} degrees needs a rotor speed (SPD > 0)")
            dt = abs(deg / 360.0) / (spd * SPD_TO_TURNS_S)
            done.append(f"rotate from={turns:g} to={turns + deg / 360.0:g} f={f:g} t={dt:g}")
            turns += deg / 360.0
            prev_f = f
        elif prev_f is None:
            done.append(f"hold f={f:g} t={w:g}")
            w = 0.0
        elif f != prev_f:
            done.append(f"ramp from={prev_f:g} to={f:g} speed={v:g}" if v > 0 else f"hold f={f:g} t=0")
        prev_f = f
        if w > 0:
            done.append(f"wait t={w:g}")
        lines.append(f"# column {k}" + ("" if done else ": nothing to do"))
        lines += done
    if repeat > 1:
        lines.append("end")
    lines.append("end protocol")
    return "\n".join(lines) + "\n"


class ExpTable(QWidget):
    """The table with add / remove column buttons; `columns()` reads it, `to_script()` compiles it."""

    def __init__(self, on_script, on_start):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(len(ROWS), 0)
        self.table.setVerticalHeaderLabels(ROWS)
        self.table.setMinimumHeight(190)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.btn_add = QPushButton("+ column", clicked=lambda: self.add_column())
        self.btn_del = QPushButton("- column", clicked=self.remove_column)
        self.btn_script = QPushButton("Table -> script", clicked=on_script)
        self.btn_start = QPushButton("Start from table", clicked=on_start)
        self.btn_example = QPushButton("Load example", clicked=lambda: self.set_columns(EXAMPLE))
        self.repeat = QSpinBox()              # owner 2026-11-05: cycle repeat -> loop n=
        self.repeat.setRange(1, 100000)
        self.repeat.setPrefix("repeat ")
        self.repeat.setSuffix(" x")
        self.info = QLabel("columns = steps: a force change at the motor speed, or a rotation at the rotor speed, then the wait")
        self.info.setWordWrap(True)
        for w in (self.btn_add, self.btn_del, self.btn_example, self.repeat):
            row.addWidget(w)
        lay.addLayout(row)
        row2 = QHBoxLayout()               # design critique review 2026-11-05: one row cut the button texts off
        for w in (self.btn_script, self.btn_start):
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

    def to_script(self, name="table"):
        return compile_table(self.columns(), name, self.repeat.value())
