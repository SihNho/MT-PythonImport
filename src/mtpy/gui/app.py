"""Main window (docs/mockups/2026-10-23-main-window, requirements U1-U6, U8, U13, U15, U17-U21, U30): one screen,
step bar, camera view with the bead boxes, any-axis live graphs, status bar and the emergency stop. Every device
action is an `mtpy.api` call made as caller "gui"; long ones run on a worker thread. The window reads the display tap
(api.acq.display) on a 30 Hz timer and can never slow acquisition.
shortcut: the GUI shares the API's process (plan phase 8 says its own process); move it out if phase 6 shows the
camera thread losing frames while the window is dragged.
"""
import contextlib
import json
import re
import time
import warnings
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mtpy import api
from mtpy.api import estop, events, safety
from mtpy.lvfiles import read_cal
from mtpy.track import Z_METHODS

from . import shutdown as _shutdown
from . import zscan
from .attrs import AttrPanel
from .calview import CalView
from .exptable import ExpTable
from .shutdown import run_shutdown


def use_client(client):
    """Decision 0029: run the window as a client of an engine process. Every `api.` / `events.` / `estop.` /
    `safety.` name in this module and in the shutdown sequence becomes the client's; nothing else changes."""
    global api, events, estop, safety
    api, events, estop, safety = client.api, client.events, client.api.estop, client.api.safety
    _shutdown.api, _shutdown.events = client.api, client.events


def use_inprocess():
    """Back to the in-process API (tests)."""
    global api, events, estop, safety
    from mtpy import api as a
    api, events, estop, safety = a, a.events, a.estop, a.safety
    _shutdown.api, _shutdown.events = a, a.events

pg.setConfigOptions(imageAxisOrder="row-major", background="k", foreground="w")

STEPS = [("setup", "Setup"), ("run", "Run"), ("exp", "Experiment"), ("plot", "Plot"), ("beads", "Beads"),
         ("cal", "Calibrate"), ("save", "Save")]       # Request2 (owner 2026-11-06): Explore lives inside the Run page
DETAILS = ("beads", "cal", "save")              # owner 2026-11-05: the pages the Run page duplicates stay behind "More"
DATA_ROOT = Path(r"G:\Data")                     # owner 2026-11-05: every data dialog starts here
CAL_ROOT = DATA_ROOT                             # owner 2026-11-11: "G:\Data" (Request2 had the Dropbox data folder)
PROTOCOLS_DIR = DATA_ROOT / "protocols"          # the owner's own protocols (.mtprot), listed on the Experiment page
TITLES = {"setup": "Setup: devices, camera, analysis", "explore": "Explore (no recording)",
          "run": "Run: camera -> beads -> calibrate -> track -> save, in that order",
          "beads": "Beads: select from a .cal", "cal": "Calibrate: z scan -> .cal", "exp": "Experiment: protocol",
          "plot": "Plot: a second, tall graph with its own axes",
          "save": "Save and export"}
AXES = {"t": "Time (s)", "mag": "Magnet (mm)", "force": "Force (pN)", "z": "z (um)", "x": "x (px)", "y": "y (px)"}
COLORS = ["#60A5FA", "#F472B6", "#34D399", "#FBBF24", "#A78BFA", "#F87171", "#2DD4BF", "#FB923C"]
CHIPS_PER_ROW = 8                      # bead check boxes wrap after this many (G16; 8 x CHIP_W fits any screen)
CHIP_W = 104                           # a chip's fixed width: "b16 3.3/5.9"; Request1 item 2: a chip that changed
                                       # width with its text ("lost" <-> the z) re-laid the window out every tick
EDGE_SLICES = 10                       # owner 2026-11-06: a bead this close to a LUT end is shown orange (box, chip)
PLOT_HZ = 10.0                         # default plot refresh; the user sets it in the plot bar (owner 2026-11-01)
GUIDE = Path(__file__).resolve().parents[3] / "docs" / "guide" / "protocol-scripts.ko.md"   # the script guide
RUN_DOC = Path(__file__).resolve().parents[3] / "docs" / "format" / "run-file.ko.html"       # what the .h5 holds


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


def next_free(path):
    """cal001 -> the first of cal001, cal002, ... that does not exist; a name without a number gets 001 appended
    when taken. shortcut: a name with a suffix (cal001.cal) is numbered after the suffix, upgrade if such names come."""
    m = re.fullmatch(r"(.*?)(\d+)", path.name)
    stem, n = (m.group(1), int(m.group(2))) if m else (path.name, 0)
    while path.exists():
        n += 1
        path = path.with_name(f"{stem}{n:03d}")
    return path


def next_tra(folder):
    """LabVIEW's run name: tra001, tra002, ... the first with neither traNNN.h5 nor traNNN-000 in the folder."""
    n = 1
    while (Path(folder) / f"tra{n:03d}.h5").exists() or (Path(folder) / f"tra{n:03d}-000").exists():
        n += 1
    return f"tra{n:03d}"


def _sentence(extra):
    """One readable line from an event's fields: the action first, then the named things, then the rest flattened
    ('open emccd', 'start name tra001, beads [1, 2], cal ...')."""
    x = dict(extra)
    x.update(x.pop("extra", {}) if isinstance(x.get("extra"), dict) else {})
    parts = [str(x.pop("action"))] if "action" in x else []
    for k in ("device", "name", "quantity", "request", "readback", "reason", "error"):
        if k in x:
            v = x.pop(k)
            parts.append(f"{v}" if k == "device" else f"{k} {v}")
    parts += [f"{k} {v}" for k, v in x.items()]
    return ", ".join(parts)[:160]


class Worker(QRunnable):
    """Run fn() on the thread pool as caller "gui"; done(result) or failed(text) back on the GUI thread."""

    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, _Signals()

    def run(self):
        try:
            with events.as_caller("gui"):
                r = self.fn()
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.signals.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.signals.done.emit(r)


def _spin(lo, hi, step, value, decimals=2, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


# 'Mag pos when touched to glass': the magnet's travel end (PI Max Trans Pos.vi = 40.94 mm; the tethered-calibration
# protocol uses 40.94). Owner 2026-10-31: start from the LabVIEW value, change it only through its own button, and keep
# the value across program restarts (a value that differs at every start invites mistakes).
TOUCH_DEFAULT_MM = 40.94
TOUCH_FILE = Path(__file__).resolve().parents[3] / "config" / "touch_position.json"
PRESETS_FILE = TOUCH_FILE.with_name("explore_presets.json")   # owner 2026-11-04: two PI presets, "Cal+" / "Cal-"


# owner 2026-11-14: the pre-calibration references, {name (the bead type): {"cal": path, "bead": n}} - paths only; the
# camera conditions and the objective are read from the run metadata beside the .cal (api.zscan.reference_conditions)
PRECAL_FILE = TOUCH_FILE.with_name("precal_references.json")


def load_precal():
    try:
        refs = json.loads(PRECAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return refs if isinstance(refs, dict) else {}


def match_camera(want):
    """Set the camera's exposure / rate / gain to `want` (keys left out stay; out-of-range values are coerced by the
    API) and return what they were before, for the way back."""
    s = api.devices.info("camera")["settings"]
    before = {k: s[k] for k in ("rate_Hz", "exposure_ms", "gain_dB") if k in want and k in s}
    fns = {"exposure_ms": api.camera.set_exposure, "rate_Hz": lambda v: api.camera.set_rate(v, confirm=True),
           "gain_dB": api.camera.set_gain}
    shorter = want.get("exposure_ms", float("inf")) <= s.get("exposure_ms", 0.0)    # a rate needs its exposure to fit
    for k in (("exposure_ms", "rate_Hz") if shorter else ("rate_Hz", "exposure_ms")) + ("gain_dB",):
        if k in want:
            fns[k](want[k])
    return before


def match_binning(want):
    """Set the camera's binning to `want` ({"horizontal", "vertical"}); return the binning before when it was
    changed, else None. The write pauses the acquisition (api.camera.set_attribute)."""
    now = api.camera.binning()
    if not want or now == want:
        return None
    for name, key in (("BinningHorizontal", "horizontal"), ("BinningVertical", "vertical")):
        if now[key] != want[key]:
            api.camera.set_attribute(name, int(want[key]), confirm=True)
    return now


def load_touch_mm():
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
        return float(json.loads(TOUCH_FILE.read_text(encoding="utf-8"))["touch_mm"])
    return TOUCH_DEFAULT_MM


def load_presets():
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {}


def save_presets(values):
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(json.dumps(values, indent=1), encoding="utf-8")


def save_touch_mm(mm):
    TOUCH_FILE.write_text(json.dumps({"touch_mm": mm, "set_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                      "by": "gui (Change / Set)"}, indent=1) + "\n", encoding="utf-8")


class _Panel(QDialog):
    """A non-modal side panel for what does not belong in the step column (owner 2026-10-31: the camera settings
    open in their own panel on a click; the device table opens a device's information the same way)."""

    def __init__(self, parent, title, widget):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        lay = QVBoxLayout(self)
        lay.addWidget(widget)

    def open_(self):
        self.show()
        self.raise_()
        self.activateWindow()


def _row(*widgets):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    return w


class MainWindow(QMainWindow):
    _closed_anyway = False      # "Close anyway" pressed: the window closes without running the sequence again
    event_in = Signal(object)

    def __init__(self, fixture, out, sim_dev=None, backend="sim"):
        super().__init__()
        self.fixture, self.out, self.sim_dev = Path(fixture), Path(out), sim_dev
        self.backend_arg = backend
        # an .ini, never the registry: QSettings(org, app) ignored setDefaultFormat on this PySide, so the tests had
        # been writing the user's real registry settings (design critique #3; found 2026-11-06 with scan_dir)
        self.settings = QSettings(QSettings.IniFormat, QSettings.UserScope, "KimLab", "MT Tracker")
        self.pool = QThreadPool.globalInstance()
        self._workers = set()                          # alive until done / failed: the pool would delete them first
        self._slow_busy, self._acq_running = False, False
        self.history = deque(maxlen=20000)            # (t, mag, force, xyz (nb, 3))
        self.t0 = time.time()
        self.bead_ids, self.roles, self.cal_path = [], {}, None
        self.display_on = True
        self.base_title = "MT Tracker (Python) - " + ("REAL CAMERA, other devices simulated" if backend == "real" else "REAL CAMERA AND MOTORS" if backend == "real-motors"
                                                        else "simulators") + ("  [SIM-DEV PROFILE]" if sim_dev else "")
        self.resize(1500, 950)
        self._build()
        self._apply_mode()
        self.event_in.connect(self._on_event)
        self._unsub = events.subscribe(self.event_in.emit)
        self.timer = QTimer(self, interval=33, timeout=self._tick)
        self.timer.start()
        self.slow = QTimer(self, interval=500, timeout=self._slow_tick)
        self.slow.start()

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.addWidget(self._top_bar())
        self.estop_banner = self._estop_banner()
        v.addWidget(self.estop_banner)
        v.addWidget(self._step_bar())
        body = QHBoxLayout()
        v.addLayout(body, 1)
        centre = QVBoxLayout()
        body.addLayout(centre, 3)
        centre.addWidget(self._camera_view(), 3)
        centre.addWidget(self._graphs(), 2)
        self.panel = QStackedWidget()
        self.panel.setMinimumWidth(420)
        self.panel.setMaximumWidth(520)
        scroll = QScrollArea()           # the Setup page is taller than a 1080-px screen: scroll instead of hiding the status bar
        scroll.setWidget(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(440)
        body.addWidget(scroll, 0)
        for key, _ in STEPS:
            self.panel.addWidget(getattr(self, f"_panel_{key}")())
        self.events_list = QListWidget()
        self.events_list.setMaximumHeight(110)
        v.addWidget(self.events_list)
        self.statusBar().showMessage("not connected")
        self._set_step(0)

    def _profile_label(self):
        """Owner 2026-11-05 ("where is that set? the user must know, and see the state"): the profile file and its
        limits, read at the program's start; changed with tools/rig_set_limit.py (the rig-admin), then a restart."""
        p = safety.profile()
        cfg = getattr(safety, "CONFIG", None)             # a path in-process; the engine's own when a client
        where = f"{Path(cfg) / 'safety_profile.json'}" if isinstance(cfg, (str, Path)) else "config/safety_profile.json (the engine's)"
        rows = "".join(f"<tr><td>{q}</td><td align=right>{lim.get('min')}</td><td align=right>{lim.get('max')}</td>"
                       f"<td>{lim.get('unit', '')}</td><td>{'' if lim.get('verified') else 'UNVERIFIED'}"
                       f"{' (max None: every request refused)' if lim.get('max') is None else ''}</td></tr>"
                       for q, lim in p["limits"].items())
        lab = QLabel(f"<b>Rig safety profile v{p.get('version')}</b> (read at start)<table cellspacing=0 cellpadding=2>"
                     f"<tr><th>quantity</th><th>min</th><th>max</th><th>unit</th><th></th></tr>{rows}</table>")
        lab.setToolTip(f"{where}\nTo change a limit: python tools/rig_set_limit.py <quantity> --max ... --reason \"...\", "
                       "then restart the program (design critique 2026-11-05 #9: the path and the command live here)")
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return lab

    def _top_bar(self):
        w = QFrame()
        h = QHBoxLayout(w)
        self.dev_summary = QLabel("Devices: not connected")
        h.addWidget(self.dev_summary, 1)
        self.prot_badge = QLabel("no protocol")           # owner 2026-11-05: is a protocol running? visible everywhere
        self.prot_badge.setToolTip("The protocol's state (Experiment panel). Start replaces a running protocol.")
        h.addWidget(self.prot_badge)
        self.rec_badge = QLabel("not recording")          # owner 2026-11-10: recording or not, seen at a glance
        self.rec_badge.setToolTip("Whether the frames are being written to the run file now.")
        h.addWidget(self.rec_badge)
        # owner 2026-11-10: "are frames being dropped? show the count" - since the camera start, red when not 0
        self.lost_label = QLabel("Lost frames: -")
        self.lost_label.setToolTip("Since the camera start. camera = frames the camera never delivered (gaps in its "
                                   "frame numbers); queue = frames received but not tracked because tracking fell "
                                   "behind (the ring was full). p99 = the slowest 1 % of the tracking times per frame.")
        h.addWidget(self.lost_label)
        self.btn_display = QPushButton("Pause display", clicked=self._toggle_display)
        self.btn_stop = QPushButton("EMERGENCY STOP  (Shift+Esc)", clicked=self._estop)
        self.btn_stop.setShortcut("Shift+Esc")
        self.btn_stop.setToolTip("Emergency stop: every motor halts, the protocol ends, and every move is refused until "
                                 "Acknowledge is pressed. Not for ending an acquisition (Stop acquisition) or a protocol (Stop).")
        self.btn_stop.setStyleSheet("background:#B91C1C;color:white;font-weight:bold;padding:6px 18px")
        self.btn_ack = QPushButton("Acknowledge", clicked=self._estop_clear)
        self.btn_ack.setToolTip("Clears the emergency stop after STOP (owner 2026-11-05: 'what are these'). Needed only "
                                "after STOP; Connect refuses while the stop is engaged.")
        h.addWidget(self.btn_display)   # owner 2026-11-05: the camera and Record buttons live on the Run page only
        h.addSpacing(60)                 # design critique 2026-11-05 #4: apart from the other stops, far right
        h.addWidget(self.btn_stop)
        return w

    def _estop_banner(self):
        """Red banner between the top bar and the steps while the emergency stop is engaged, Acknowledge inside it
        (the mock-up's banner; design critique 2026-11-05 #4). Hidden otherwise."""
        w = QFrame()
        w.setStyleSheet("background:#B91C1C;color:white;font-weight:bold")
        h = QHBoxLayout(w)
        self.estop_text = QLabel("EMERGENCY STOP ENGAGED")
        h.addWidget(self.estop_text, 1)
        h.addWidget(self.btn_ack)
        w.setVisible(False)
        return w

    def _step_bar(self):
        w = QFrame()
        h = QHBoxLayout(w)
        self.step_group = QButtonGroup(self)
        self.step_group.setExclusive(True)
        self.detail_buttons = []
        for i, (key, label) in enumerate(STEPS):
            b = QPushButton(label if key in DETAILS else f"{i + 1}. {label}")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self._set_step(i))
            self.step_group.addButton(b, i)
            if key in DETAILS:
                b.setVisible(False)
                self.detail_buttons.append(b)
            else:
                h.addWidget(b)
        self.btn_more = QPushButton("More...", checkable=True, toggled=self._show_details)
        self.btn_more.setToolTip("The detail pages the Run page covers: Explore (move by hand), Beads (the list behind "
                                 "Run), Calibrate (scan settings, the LUT viewer), Save (run files, exports)")
        h.addWidget(self.btn_more)
        for b in self.detail_buttons:
            h.addWidget(b)
        self.step_title = QLabel("")
        h.addWidget(self.step_title, 1)
        return w

    def _show_details(self, on):
        for b in self.detail_buttons:
            b.setVisible(on)
        self.btn_more.setText("Less" if on else "More...")

    def _set_step(self, i):
        if STEPS[i][0] in DETAILS and not self.btn_more.isChecked():
            self.btn_more.setChecked(True)
        self.panel.setCurrentIndex(i)
        self.step_group.button(i).setChecked(True)
        self.step_title.setText(TITLES[STEPS[i][0]])

    def _camera_view(self):
        """Two screens side by side (owner 2026-10-30: the JAI and the EMCCD each on their own): left the tracking
        camera with the bead boxes, right the iXon (snap, or live while its Live button is down)."""
        self.view = pg.GraphicsLayoutWidget()
        vb = self.view.addViewBox(lockAspect=True, invertY=True, enableMenu=False)   # owner 2026-11-05: right click removes a pick, no menu
        self.img_item = pg.ImageItem()
        vb.addItem(self.img_item)
        self.boxes = []
        self.vb = vb
        self.picks, self.pick_items = [], []            # bead positions picked by clicking (px), their boxes
        self.view.scene().sigMouseClicked.connect(self._on_view_click)
        self.cam_label = pg.LabelItem("JAI: no frame", justify="left")
        self.view.addItem(self.cam_label, row=1, col=0)
        self.em_view = pg.GraphicsLayoutWidget()
        evb = self.em_view.addViewBox(lockAspect=True, invertY=True)
        self.em_img = pg.ImageItem()
        evb.addItem(self.em_img)
        self.em_label = pg.LabelItem("EMCCD: no frame", justify="left")
        self.em_view.addItem(self.em_label, row=1, col=0)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.view)
        split.addWidget(self.em_view)
        split.setSizes([3, 2])
        self._em_busy = False
        return split

    def _graphs(self):
        w = QWidget()
        v = QVBoxLayout(w)
        ctl = QHBoxLayout()
        self.ax_y = QComboBox()
        self.ax_x = QComboBox()
        for k, label in AXES.items():          # Request1 item 3: the X axis offers every Y option
            self.ax_y.addItem(label, k)
            self.ax_x.addItem(label, k)
        self.ax_y.setCurrentIndex(3)
        self.follow = QCheckBox("Follow last")     # owner 2026-11-10: the length is the user's, not a fixed 30 s
        self.follow.setChecked(True)
        self.follow_s = _spin(1.0, 600.0, 10.0, 30.0, 0, " s")   # the history holds 20000 display frames (~11 min)
        self.auto_scale = QCheckBox("Auto scale")
        # owner 2026-11-06: the reference beads' mean x / y / z is subtracted from the tethered beads (thermal drift
        # out); the reference beads themselves stay raw, so their drift is seen
        self.sub_ref = QCheckBox("Subtract reference")
        self.sub_ref.setChecked(True)
        # owner 2026-11-01: the plot's refresh rate is the user's (the data keep arriving at the display rate; only
        # the redraw is paced) - 16:00 isolation: the plot was the GUI's largest cost per tick
        self.plot_hz = _spin(1.0, 30.0, 1.0, PLOT_HZ, 0, " Hz")
        self._next_plot = 0.0
        self.auto_scale.setChecked(True)
        self.bead_chips = QGridLayout()      # G16 (rig 2026-11-01): 256 chips in one row stretched the window to 14 726 px
        for lab, wdg in (("Y", self.ax_y), ("X", self.ax_x)):
            ctl.addWidget(QLabel(lab))
            ctl.addWidget(wdg)
        ctl.addWidget(self.follow)
        ctl.addWidget(self.follow_s)
        ctl.addWidget(self.auto_scale)
        ctl.addWidget(self.sub_ref)
        # owner 2026-11-14: "a button sets that position as the zero" - the z each bead shows now becomes 0 on the
        # graphs (the plot only; the run file keeps the raw z)
        self.z_zero, self._zero_now = None, False
        self.btn_zero = QPushButton("Set zero (z)", clicked=lambda: setattr(self, "_zero_now", True))
        self.btn_zero.setToolTip("The z every bead shows now becomes 0 on the graphs; the data keep the raw z")
        ctl.addWidget(self.btn_zero)
        ctl.addWidget(QPushButton("Clear zero", clicked=lambda: setattr(self, "z_zero", None)))
        ctl.addWidget(QLabel("Plot refresh"))
        ctl.addWidget(self.plot_hz)
        ctl.addStretch(1)
        v.addLayout(ctl)
        chips_row = QHBoxLayout()           # the chips under the controls, never widening the window (Request1 item 2)
        chips_row.addLayout(self.bead_chips)
        chips_row.addStretch(1)
        v.addLayout(chips_row)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.addLegend(offset=(10, 10))
        self.curves = {}
        v.addWidget(self.plot, 1)
        self.chips = {}
        return w

    # ------------------------------------------------------------------ panels
    def _panel_setup(self):
        w = QWidget()
        f = QFormLayout(w)
        f.addRow("Safety profile", self._profile_label())
        # owner 2026-11-05: the user sees the rig only; the backend and the simulator fixture are the developer's
        # (--backend sim on the command line, the tests) and stay off the panel otherwise
        self.backend = QComboBox()
        self.backend.addItem("sim: every device simulated", "sim")
        self.backend.addItem("real: JAI camera + Andor iXon EMCCD (SDK2) under the rig lock; motors simulated", "real")
        self.backend.addItem("rig: JAI + iXon + motors through the motion gate", "real-motors")
        self.backend.setCurrentIndex(self.backend.findData(self.backend_arg))
        dev = self.backend_arg == "sim"
        if dev:
            f.addRow("Backend (developer)", self.backend)
        self.mode = QComboBox()          # owner 2026-10-30: MT and MT-TIRF are distinct modes of the program
        self.mode.addItem("MT: tracking (JAI, motors)", "MT")
        self.mode.addItem("MT-TIRF: tracking + EMCCD", "MT-TIRF")
        self.mode.setCurrentIndex(self.mode.findData(api.devices.default_mode()))
        self.mode.currentIndexChanged.connect(self._apply_mode)
        f.addRow("Mode", self.mode)
        # owner 2026-11-12: the lens in use and its refractive-index (focal-shift) factor go into every run file
        self.objective = QComboBox()
        for name, p in api.devices.rig_presets().items():
            self.objective.addItem(f"{name}: {p.get('objective')}  (focal shift {p.get('focal_shift_factor')}, z stored raw)", name)
        self.objective.setCurrentIndex(max(0, self.objective.findData(self.settings.value("objective", ""))))
        self.objective.setToolTip("Written into the run file (metadata/presets/rig) at the next Connect. z is stored "
                                  "raw: the factor is recorded, never applied. The list is config/rig_presets.json.")
        f.addRow("Objective", self.objective)
        self.cam_sdk = QComboBox()       # owner 2026-11-01: the JAI's SDK is chosen here; it must match the USB3 Vision driver bound
        self.cam_sdk.addItem("IMAQdx (NI driver - LabVIEW can share the camera)", "imaqdx")
        self.cam_sdk.addItem("eBUS (JAI / Pleora driver - LabVIEW cannot open the camera)", "ebus")
        f.addRow("Camera SDK", self.cam_sdk)
        self.ed_fixture = QLineEdit(str(self.fixture))
        if dev:
            f.addRow("Simulator fixture", _row(self.ed_fixture, QPushButton("Browse...", clicked=self._browse_fixture)))
        f.addRow(_row(QPushButton("Connect", clicked=self._connect),
                      QPushButton("Disconnect", clicked=self._disconnect),
                      QPushButton("Run self-check", clicked=self._self_check)))
        self.dev_table = QTableWidget(0, 3)
        self.dev_table.setHorizontalHeaderLabels(["Device", "State", "Last error / detail"])
        self.dev_table.horizontalHeader().setStretchLastSection(True)
        self.dev_table.setMinimumHeight(120)
        self.dev_table.cellClicked.connect(self._device_info)
        f.addRow(self.dev_table)
        self.dev_info = QLabel("")                      # identity line; the rows and controls are built per device
        self.dev_info.setWordWrap(True)
        self.dev_form, self.dev_controls = None, {}
        self.dev_panel = _Panel(self, "Device", self.dev_info)
        self.dev_panel.resize(640, 520)
        # owner 2026-11-13: no separate "Camera settings..." panel - a click on the camera / emccd row of the device
        # table opens that camera's settings inside the device panel (one place per setting)
        self.cam_box, self.em_box = QWidget(), QWidget()
        cams_lay, em_lay = QVBoxLayout(self.cam_box), QVBoxLayout(self.em_box)
        for box, lay in ((self.cam_box, cams_lay), (self.em_box, em_lay)):
            lay.setContentsMargins(0, 0, 0, 0)
            self.dev_panel.layout().addWidget(box, 1)
            box.hide()
        g = QGroupBox("Camera preset")
        gf = QFormLayout(g)
        self.cam_rate = QComboBox()
        for r in ("90", "150"):
            self.cam_rate.addItem(f"{r} Hz", float(r))
        self.cam_exp = _spin(0.1, 11.0, 0.1, 2.0, 2, " ms")
        self.cam_gain = _spin(0.0, 12.0, 0.5, 0.0, 1, " dB")
        gf.addRow("Frame rate (needs a short pause)", self.cam_rate)
        gf.addRow("Exposure", self.cam_exp)
        gf.addRow("Gain", self.cam_gain)
        gf.addRow(QPushButton("Apply preset and read back", clicked=self._apply_preset))
        cams_lay.addWidget(g)
        # owner 2026-11-04: every camera attribute, generated from the device's catalogue; favourites per device
        self.cam_attrs = AttrPanel("Camera", lambda: api.camera.catalogue(), lambda n: api.camera.get_attribute(n),
                                   self._set_cam_attribute, self._call, TOUCH_FILE.with_name("camera_favourites.json"))
        self.cam_attrs_confirm = QCheckBox("allow a frame-producing change while recording (confirm=True)")
        self.cam_attrs.layout().insertWidget(1, self.cam_attrs_confirm)
        cams_lay.addWidget(self.cam_attrs, 1)
        g4 = self.em_group = QGroupBox("EMCCD (Andor iXon Ultra): core parameters, each read back")
        g4f = QFormLayout(g4)
        self.em_exp = _spin(0.01, 10000.0, 1.0, 30.0, 2, " ms")
        self.em_rate = _spin(0.01, 1000.0, 1.0, 18.0, 2, " Hz")     # 30 ms + 24.59 ms readout (frame transfer off) -> 18.3 Hz max
        self.em_mode = QComboBox()
        for i, m in enumerate(("8 bit DAC", "12 bit DAC", "linear", "real EM gain")):
            self.em_mode.addItem(f"{i}: {m}", i)
        self.em_gain = _spin(0, 1000, 1, 0, 0, "")
        self.em_temp = _spin(-120, 20, 1, -70, 0, " C")
        g4f.addRow("Exposure", self.em_exp)
        g4f.addRow("Frame rate", self.em_rate)
        g4f.addRow("EM gain mode", self.em_mode)
        g4f.addRow("EM gain", self.em_gain)
        g4f.addRow("Temperature set point (cooler on)", self.em_temp)
        self.btn_em_live = QPushButton("Live", checkable=True, clicked=self._toggle_emccd_live)
        g4f.addRow(_row(QPushButton("Apply and read back", clicked=self._apply_emccd),
                        QPushButton("Snap one frame", clicked=self._snap_emccd), self.btn_em_live))
        self.em_cycles = _spin(1, 1000, 10, 100, 0, " cycles")
        self.em_pause = _spin(0.0, 5.0, 0.1, 0.1, 2, " s")
        g4f.addRow("Shutter", _row(QPushButton("Open", clicked=lambda: self._shutter(1)),
                                   QPushButton("Close", clicked=lambda: self._shutter(2)),
                                   self.em_cycles, self.em_pause,
                                   QPushButton("Exercise (open / close)", clicked=self._exercise_emccd)))
        self.em_readback = QLabel("emccd: not connected")
        self.em_readback.setWordWrap(True)
        g4f.addRow(self.em_readback)
        em_lay.addWidget(g4)
        self.em_attrs = AttrPanel("EMCCD", lambda: api.emccd.catalogue(), lambda n: api.emccd.get_attribute(n),
                                  lambda n, v: api.emccd.set_attribute(n, v), self._call,
                                  TOUCH_FILE.with_name("emccd_favourites.json"))
        em_lay.addWidget(self.em_attrs, 1)
        g2 = QGroupBox("Tracking")
        g2f = QFormLayout(g2)
        self.z_method = QComboBox()
        self.z_method.addItems(list(Z_METHODS))
        self.gpu = QCheckBox("Z, XY and radial on the GPU (fused CUDA kernel, FP32; decision 0030)")
        g2f.addRow("Z method", self.z_method)
        g2f.addRow(self.gpu)
        f.addRow(g2)
        g3 = QGroupBox("Force from magnet position")
        g3f = QFormLayout(g3)
        self.touch_mm = _spin(0.0, 60.0, 0.01, load_touch_mm(), 2, " mm")
        self.touch_mm.setEnabled(False)                 # locked: Change... unlocks, Set applies, saves and locks again
        self.btn_touch_set = QPushButton("Set", enabled=False, clicked=self._set_touch)
        g3f.addRow("Magnet position when touching the glass", _row(
            self.touch_mm, QPushButton("Change...", clicked=self._unlock_touch), self.btn_touch_set))
        self.touch_info = QLabel(f"kept in {TOUCH_FILE.name}; applied to the force equation at every Connect")
        self.touch_info.setWordWrap(True)
        g3f.addRow(self.touch_info)
        f.addRow(g3)
        if self.sim_dev:
            lab = QLabel("SIM-DEV: TEST-ONLY limits on a temporary config copy (focus +-50 um, rotor). Simulators only.")
            lab.setStyleSheet("color:#B45309;font-weight:bold")
            lab.setWordWrap(True)
            f.addRow(lab)
        return w

    def _panel_run(self):
        """Owner 2026-11-05 ("the usual experiment: watch the camera, pick beads, calibrate, choose where to save,
        track, save - here it is scattered"): the experiment in its order on one page, each step a button or the
        words of what to do; the other pages keep the settings."""
        w = QWidget()
        f = QFormLayout(w)
        self.run_cam = QLabel("1. Start the camera and watch the JAI image; no file is written while no beads are "
                              "selected")
        self.btn_run_cam = self.btn_live = QPushButton("1. Start the camera", clicked=self._toggle_acq)
        self.btn_rec = QPushButton("4. Record on", clicked=self._toggle_rec)      # the one Record button (owner 2026-11-05)
        self.btn_rec.setCheckable(True)
        self.run_beads = QLabel("2. Left click the beads on the image (right click removes a pick): 0 picked")
        self.run_cal = QLabel("3. asks for the data folder once (the calibration cal001, cal002, ... and the run file "
                              "tra001.h5, tra002.h5, ... go there), scans the picked beads DOWN from the current focus: "
                              "start with the beads just BELOW the focus (small pattern), the sample goes down per slice "
                              "and the pattern grows; the LUT is stored bottom-up so z rises with the bead; its middle is "
                              "2.9 um below the start at 60 x 100 nm and the focus goes there after the scan. Then it tracks every bead of the .cal (bead 1 = "
                              "reference) from the next frame on; the camera never stops. Reset calibration drops the "
                              "beads so the image takes picks again.")
        self.run_track = QLabel("4. not tracking")
        self.run_save = QLabel("5. the traces go next to the run file as tra001-000, tra001-001, ... (LabVIEW's files)")
        for lab in (self.run_cam, self.run_beads, self.run_cal, self.run_track, self.run_save):
            lab.setWordWrap(True)
        f.addRow(_row(self.run_cam, self.btn_run_cam))
        f.addRow(_row(self.run_beads, QPushButton("Clear picks", clicked=self._clear_picks)))
        f.addRow(_row(QPushButton("3. Calibrate the picked beads...", clicked=self._flow_calibrate),
                      QPushButton("Reset calibration", clicked=self._new_calibration)))
        f.addRow(self.run_cal)
        # owner 2026-11-14: pre-calibration - no z scan and no reference bead: the picked beads get the LUT of a saved
        # reference .cal (Calibrate page) for a rough z, e.g. to see a tether's extension before the real calibration
        self.precal = QComboBox()
        self.precal.addItems(sorted(load_precal()))
        self.precal_info = QLabel("3b. rough z without a z scan: the picked beads get the LUT of a saved reference "
                                  "(More... > Calibrate). The camera's binning, rate, exposure and gain are set "
                                  "to the reference's until Reset calibration; check only that the objective is the "
                                  "same.")
        self.precal_info.setWordWrap(True)
        f.addRow(_row(QPushButton("3b. Pre-calibrate (no z scan) with", clicked=self._flow_precal), self.precal))
        f.addRow(self.precal_info)
        f.addRow(_row(self.run_track, self.btn_rec))
        # owner 2026-11-06: autofocus through the piezo (spec F4.06): the focus holds the reference bead's tracked z at
        # the LUT's middle; off by default, off again at Reset calibration and when the camera stops
        self.autofocus = QCheckBox("Autofocus: the piezo holds the reference bead's z at")
        self.autofocus.toggled.connect(self._toggle_autofocus)
        # owner 2026-11-12: the target is the user's, in percent of the LUT (0 = the largest pattern), default 30;
        # a protocol's `autofocus on` uses this value
        self.af_target = _spin(0.0, 100.0, 5.0, float(self.settings.value("af_target", 30.0)),
                               0, " % of the LUT")
        self.af_target.setToolTip("0 % = LUT index 0, the largest pattern (the last slice scanned); 100 % = the scan's "
                                  "start. Applied at once, also while the autofocus is on (+-0.2 um steps).")
        self.af_target.valueChanged.connect(self._set_af_target)
        self.af_status = QLabel("")
        f.addRow(_row(self.autofocus, self.af_target, self.af_status))
        f.addRow(QPushButton("5. Save the traces (.tra)", clicked=lambda: self._export("tra")))
        f.addRow(self.run_save)
        explore = QGroupBox("Explore: move by hand (no recording)")     # Request2: on the Run page itself
        QVBoxLayout(explore).addWidget(self._panel_explore())
        f.addRow(explore)
        return w

    def _flow_calibrate(self):
        """Step 3 of the Run page: the data folder is asked for once (design critique 2026-11-05 #2), the names are
        LabVIEW's next free ones in it, the z scan runs, then _track_from_cal."""
        if not self.picks or not api.acq.running():
            self._fail("calibrate", "start the camera and left click the beads on the image first")
            return
        start = CAL_ROOT if CAL_ROOT.is_dir() else Path(self.cal_out.text()).parent     # the data root (owner 2026-11-11)
        d = QFileDialog.getExistingDirectory(self, "Data folder: the calibration (cal001, ...) and the run file "
                                             "(tra001.h5, ...) are written here", str(start))
        if not d:
            return
        self.settings.setValue("data_dir", d)
        cal = next_free(Path(d) / "cal001")
        self.cal_out.setText(str(cal))
        self._flow = Path(d)
        self.run_cal.setText(f"3. scanning -> {cal.name}; then tracking into {next_tra(d)}.h5 in {d}")
        self._run_zscan()

    def _flow_precal(self):
        """Step 3b of the Run page: track the picked beads with a saved reference's LUT (api.zscan.from_reference)."""
        name = self.precal.currentText()
        ref = load_precal().get(name)
        if not self.picks or not api.acq.running():
            self._fail("pre-calibration", "start the camera and left click the beads on the image first")
            return
        if not ref:
            self._fail("pre-calibration", "no reference: save one on the Calibrate page (More...) first")
            return
        cond = api.zscan.reference_conditions(ref["cal"])
        obj = self.objective.currentData()
        if cond.get("objective") and obj and cond["objective"] != obj:
            self._fail("pre-calibration", f"the reference {name!r} was taken with the objective {cond['objective']!r}; "
                                          f"Setup says {obj!r} - another objective needs its own reference")
            return
        start = CAL_ROOT if CAL_ROOT.is_dir() else Path(self.cal_out.text()).parent
        d = QFileDialog.getExistingDirectory(self, "Data folder: the pre-calibration (precal001, ...) and the run file "
                                             "(tra001.h5, ...) are written here", str(start))
        if not d:
            return
        self.settings.setValue("data_dir", d)
        path, picks = next_free(Path(d) / "precal001"), [tuple(p) for p in self.picks]

        def job():
            # owner 2026-11-14: "without the binning it is meaningless" (the pixel pitch is the LUT's radial scale):
            # the binning is set to the reference's first; that rescales the image, so the picks are taken again
            was = match_binning(cond.get("binning"))
            if was:
                return "repick", was
            before = match_camera(cond.get("camera", {}))
            api.zscan.from_reference(str(path), picks, ref["cal"], int(ref["bead"]))
            return "tracking", before

        def done(r):
            if r[0] == "repick":
                self._precal_binning = getattr(self, "_precal_binning", None) or r[1]
                self._clear_picks()
                self.precal_info.setText(
                    f"3b. the binning was {r[1]} and is now the reference's {cond['binning']}: the image scale "
                    "changed - click the beads again, then press Pre-calibrate again. Reset calibration puts the "
                    "binning back.")
                return
            before = r[1]
            self._precal_before = getattr(self, "_precal_before", None) or before
            self._flow = Path(d)
            self._track_from_cal(path, ref="")
            self._flow = None
            cam = ", ".join(f"{k} {v:g}" for k, v in cond.get("camera", {}).items())
            self.precal_info.setText(
                f"3b. pre-calibrated with {name!r} (bead {ref['bead']} of {ref['cal']}) -> {path.name}: z is rough, no "
                "reference bead. " + (f"Camera set to the reference's {cam}; Reset calibration puts it back."
                                      if cam else "No run metadata beside the reference: the camera was not changed."))
        self._call(job, "pre-calibration", done)

    def _browse_precal(self):
        p, _ = QFileDialog.getOpenFileName(self, "Reference calibration (.cal)", str(CAL_ROOT), "Calibration (*cal*);;All (*)")
        if p:
            self.precal_cal.setText(p)

    def _save_precal(self):
        name, cal, bead = self.precal_name.text().strip(), self.precal_cal.text().strip(), self.precal_bead.value()
        try:
            n = len(read_cal(cal)["stack"])
        except Exception as e:  # noqa: BLE001
            self._fail("save reference", f"{type(e).__name__}: {e}")
            return
        if not name or not 1 <= bead <= n:
            self._fail("save reference", f"give a name and a bead 1..{n} of {Path(cal).name}")
            return
        refs = {**load_precal(), name: {"cal": cal, "bead": bead}}
        PRECAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        PRECAL_FILE.write_text(json.dumps(refs, indent=1), encoding="utf-8")
        self.precal.clear()
        self.precal.addItems(sorted(refs))
        self.precal.setCurrentText(name)
        cond = api.zscan.reference_conditions(cal)
        self.precal_status.setText(
            f"saved {name!r} -> bead {bead} of {cal}. " + (
                f"Taken with {cond['camera']}, binning {cond['binning']}, objective {cond['objective']!r} "
                f"({Path(cond['source']).name})" if cond else
                "No run metadata (*.meta.json) beside it: the camera will not be matched, the objective not checked."))

    def _track_from_cal(self, path, ref="1"):
        """After the Run page's scan: the run file is the next free tra00N.h5 in the folder chosen before the scan;
        every bead of the .cal is selected (bead 1 the reference) and tracked from the next frame on."""
        folder = self._flow
        self.ed_out.setText(str(folder))
        self.ed_name.setText(next_tra(folder))
        self.ed_cal.setText(str(path))
        self.role_ref.setText(ref)                       # "" = the pre-calibration: no reference bead
        self._load_cal_list()
        self._select_beads()

    def _panel_explore(self):
        w = QWidget()
        f = QFormLayout(w)
        hi = float(safety.profile()["limits"]["magnet_position_mm"]["max"])      # 40.9 mm since profile v9
        self.mag_pos = _spin(0.0, hi, 0.1, 0.0, 3, " mm")
        self.mag_slider = QSlider(Qt.Horizontal)
        self.mag_slider.setRange(0, round(hi * 10))
        self.mag_slider.valueChanged.connect(lambda v: self.mag_pos.setValue(v / 10))
        # owner 2026-11-04 (from the experiment): every motor's position and the force, live; the motor speed; two
        # PI presets ("Cal+" / "Cal-"); a relative move's entry returns to 0 once the move is done
        self.positions = QLabel("positions: connect first")
        self.positions.setStyleSheet("font-family: Consolas, monospace")
        self.positions.setWordWrap(True)                 # owner 2026-11-04: one line was cut off
        f.addRow("Now", self.positions)
        shi = float(safety.profile()["limits"].get("magnet_speed_mm_s", {}).get("max") or 15.0)
        self.mag_speed = _spin(0.01, shi, 0.1, shi, 2, " mm/s")      # owner 2026-11-05: starts at the limit (15 mm/s)
        f.addRow("Magnet speed", self.mag_speed)
        f.addRow("Magnet position", _row(self.mag_pos, QPushButton("Move", clicked=self._move_magnet)))
        f.addRow(self.mag_slider)
        self.mag_by = _spin(-hi, hi, 0.1, 0.0, 3, " mm")
        f.addRow("Magnet move by", _row(self.mag_by, QPushButton("Move", clicked=self._move_magnet_by)))
        presets = load_presets()
        self.preset_mm = {}
        for key in ("Cal+", "Cal-"):
            self.preset_mm[key] = sp = _spin(0.0, hi, 0.1, float(presets.get(key, 0.0)), 3, " mm")
            sp.valueChanged.connect(lambda _v=None: save_presets({k: v.value() for k, v in self.preset_mm.items()}))
            f.addRow(f"Preset {key}", _row(sp, QPushButton(f"Go {key}", clicked=lambda _=False, k=key: self._go_preset(k))))
        self.force_pn = _spin(0.0, 100.0, 0.1, 1.0, 2, " pN")
        f.addRow("Force", _row(self.force_pn, QPushButton("Set force", clicked=self._set_force)))
        self.rotor_speed = _spin(0.1, 10.0, 0.1, 1.0, 1, " turns/s")
        f.addRow("Rotor speed", self.rotor_speed)
        self.rotor_turns = _spin(-50.0, 50.0, 1.0, 0.0, 1, " turns")
        # rig 2026-11-15: wired as clicked=self._rotate the button passed its `checked` (False) as the turns -> 0, no move
        self.btn_rotate = QPushButton("Rotate", clicked=lambda: self._rotate())
        f.addRow("Rotor (relative)", _row(self.rotor_turns, self.btn_rotate,
                                          QPushButton("+1 turn", clicked=lambda: self._rotate(1.0)),
                                          QPushButton("-1 turn", clicked=lambda: self._rotate(-1.0))))
        self.focus_um = _spin(-1000.0, 1000.0, 0.1, 0.0, 2, " um")
        # owner 2026-11-14: "the piezo stage on Explore" - the focus IS the piezo (ASI Tiger Z); named so, plus its speed
        f.addRow("Piezo z (focus)", _row(self.focus_um, QPushButton("Move", clicked=self._move_focus)))
        self.focus_by = _spin(-100.0, 100.0, 0.1, 0.0, 2, " um")
        f.addRow("Piezo move by", _row(self.focus_by, QPushButton("Move", clicked=self._move_focus_by)))
        self.focus_speed = _spin(0.01, 10000.0, 1.0, 1.0, 2, " um/s")
        self.focus_speed.setToolTip("The piezo's speed for every focus move until changed (restored when the device "
                                    "closes); above the opening speed it is lowered to it")
        f.addRow("Piezo speed", _row(self.focus_speed, QPushButton("Set", clicked=lambda: self._call(
            lambda: api.focus.set_speed(self.focus_speed.value() / 1000.0) * 1000.0, "piezo speed (um/s)", self.focus_speed.setValue))))   # the read-back
        self.exp_now = _spin(0.1, 11.0, 0.1, 2.0, 2, " ms")
        self.gain_now = _spin(0.0, 12.0, 0.5, 0.0, 1, " dB")
        f.addRow("Exposure (immediate)", _row(self.exp_now, QPushButton(
            "Set", clicked=lambda: self._call(lambda: api.camera.set_exposure(self.exp_now.value()), "exposure"))))
        f.addRow("Gain (immediate)", _row(self.gain_now, QPushButton(
            "Set", clicked=lambda: self._call(lambda: api.camera.set_gain(self.gain_now.value()), "gain"))))
        self.readback = QLabel("-")
        self.readback.setWordWrap(True)
        f.addRow("Read back", self.readback)
        return w

    def _panel_beads(self):
        w = QWidget()
        f = QFormLayout(w)
        self.picks_info = QLabel("no picks: left click beads on the JAI image (acquisition running, no beads selected)")
        self.picks_info.setWordWrap(True)
        f.addRow("Picks", self.picks_info)
        self.ed_cal = QLineEdit("")
        f.addRow(".cal file", _row(self.ed_cal, QPushButton("Browse...", clicked=self._browse_cal),
                                   QPushButton("Load list", clicked=self._load_cal_list)))
        self.bead_list = QListWidget()
        self.bead_list.setMinimumHeight(120)
        f.addRow(self.bead_list)
        self.role_ref = QLineEdit("1")
        f.addRow("Reference bead ids (comma)", self.role_ref)
        f.addRow(QPushButton("Select checked beads", clicked=self._select_beads))
        self.beads_info = QLabel("no beads selected")
        self.beads_info.setWordWrap(True)
        f.addRow(self.beads_info)
        return w

    def _panel_cal(self):
        w = QWidget()
        f = QFormLayout(w)
        self.cal_slices = QSpinBox()
        self.cal_slices.setRange(5, 512)                 # the z fit reads 5 slices (api.beads refuses a shorter LUT)
        self.cal_slices.setValue(60)
        self.cal_step = _spin(-1000.0, 1000.0, 10.0, 100.0, 0, " nm")   # negative: the sample goes UP (bead above the focus; owner 2026-11-07)
        self.cal_avg = QSpinBox()
        self.cal_avg.setRange(1, 200)
        self.cal_avg.setValue(20)
        self.cal_cross = QSpinBox()
        self.cal_cross.setRange(40, 128)
        self.cal_cross.setSingleStep(2)
        self.cal_cross.setValue(120)
        f.addRow("Slices", self.cal_slices)
        f.addRow("Step", self.cal_step)
        f.addRow("Frames averaged", self.cal_avg)
        f.addRow("Cross (px)", self.cal_cross)
        self.cal_settle = _spin(0.0, 5.0, 0.1, zscan.SETTLE_S, 2, " s")
        f.addRow("Settle after each move", self.cal_settle)
        data_dir = str(CAL_ROOT) if CAL_ROOT.is_dir() else self.settings.value("data_dir", str(self._data_root()))
        data_dir = data_dir if Path(data_dir).is_dir() else str(self._data_root())
        self.cal_out = QLineEdit(str(Path(data_dir) / "cal001"))   # owner 2026-11-05: browsed, not typed; the next free name at Run
        row = QHBoxLayout()
        row.addWidget(self.cal_out)
        row.addWidget(QPushButton("Browse...", clicked=self._browse_cal_out))
        f.addRow("Write .cal to", row)
        f.addRow(QPushButton("Run z scan (beads of the current selection)", clicked=self._run_zscan))
        self.cal_status = QLabel("not run")
        self.cal_status.setWordWrap(True)
        f.addRow(self.cal_status)
        self.calview = CalView(on_saved=lambda path: (self.ed_cal.setText(path), self._load_cal_list()))
        f.addRow(self.calview)
        g = QGroupBox("Pre-calibration references: a name (the bead type) -> one bead of a .cal (the path is saved)")
        gf = QFormLayout(g)
        self.precal_name, self.precal_cal = QLineEdit(), QLineEdit()
        self.precal_name.setPlaceholderText("e.g. M270")
        self.precal_bead = QSpinBox()
        self.precal_bead.setRange(1, 9999)
        self.precal_status = QLabel(f"saved in {PRECAL_FILE.name} (config); the camera conditions and the objective "
                                    "come from the run metadata beside the .cal")
        self.precal_status.setWordWrap(True)
        gf.addRow("Name", self.precal_name)
        gf.addRow("Reference .cal", _row(self.precal_cal, QPushButton("Browse...", clicked=self._browse_precal)))
        gf.addRow("Bead of that .cal", self.precal_bead)
        gf.addRow(QPushButton("Save reference", clicked=self._save_precal))
        gf.addRow(self.precal_status)
        f.addRow(g)
        return w

    def _panel_plot(self):
        """Owner 2026-11-10: a second graph, tall, on its own page; its own axes, the wide graph's beads and options."""
        w = QWidget()
        v = QVBoxLayout(w)
        self.ax_y2, self.ax_x2 = QComboBox(), QComboBox()
        for k, label in AXES.items():
            self.ax_y2.addItem(label, k)
            self.ax_x2.addItem(label, k)
        self.ax_y2.setCurrentIndex(3)
        self.last2 = QCheckBox("Only the last")    # owner 2026-11-10: a chosen span, on any X axis (z against force)
        self.last2.setChecked(True)
        self.last2_s = _spin(1.0, 600.0, 10.0, 30.0, 0, " s")
        v.addWidget(_row(QLabel("Y"), self.ax_y2, QLabel("X"), self.ax_x2, self.last2, self.last2_s))
        v.addWidget(QLabel("Beads, Auto scale, Subtract reference and the refresh rate: the bar above the wide graph."))
        self.plot2 = pg.PlotWidget()
        self.plot2.showGrid(x=True, y=True, alpha=0.3)
        self.plot2.addLegend(offset=(10, 10))
        self.plot2.setMinimumHeight(500)
        self.curves2 = {}
        v.addWidget(self.plot2, 1)
        return w

    def _panel_exp(self):
        w = QWidget()
        v = QVBoxLayout(w)
        # owner 2026-11-04: the experiment as a table (rows = parameters, columns = iterations) that compiles to the
        # script below; the text stays the advanced view
        self.exp_table = ExpTable(self._table_to_script, self._start_from_table, self._script_to_table)
        v.addWidget(self.exp_table)
        self.prot_edit = QPlainTextEdit()        # design critique 2026-11-05 #1: opens empty, never a runnable example
        self.prot_edit.setPlaceholderText("The protocol script (the table above compiles to it; pick one of your saved "
                                          "protocols below; Script guide explains the lines)")
        self.prot_edit.setStyleSheet("font-family:Consolas,monospace")
        v.addWidget(self.prot_edit, 1)
        self.prot_files = QComboBox()            # owner 2026-11-05: the protocols used again and again, one click
        self.prot_files.currentIndexChanged.connect(self._pick_protocol)
        self._list_protocols()
        v.addWidget(_row(self.prot_files, QPushButton("Load...", clicked=self._load_protocol),
                         QPushButton("Save as...", clicked=self._save_protocol),
                         QPushButton("Check", clicked=self._check_protocol),
                         QPushButton("Script guide", clicked=self._show_guide)))
        self.btn_run = QPushButton("Start", clicked=self._run_protocol)
        self.btn_pause = QPushButton("Pause", clicked=self._pause_protocol)
        v.addWidget(_row(self.btn_run, self.btn_pause, QPushButton("Stop", clicked=self._stop_protocol),
                         QPushButton("Apply edits", clicked=self._apply_edits)))
        self.prot_status = QLabel("idle")
        self.prot_status.setWordWrap(True)
        v.addWidget(self.prot_status)
        self.mark_text = QLineEdit("mark")
        v.addWidget(_row(self.mark_text, QPushButton("Mark", clicked=self._mark)))
        return w

    def _panel_save(self):
        w = QWidget()
        f = QFormLayout(w)
        self.ed_out = QLineEdit(str(self.out))
        f.addRow("Run folder (the .cal's folder unless browsed)", _row(self.ed_out, QPushButton("Browse...", clicked=self._browse_out)))
        self.ed_name = QLineEdit(next_tra(self.out))     # owner 2026-11-05: LabVIEW's names, tra001 with cal001
        f.addRow("Run name (next acquisition)", self.ed_name)
        lab = QLabel("The run file <folder>/<name>.h5 is the raw data: every frame's record, the traces, the events and the "
                     ".cal used. Names follow the LabVIEW program (owner 2026-11-05): calibration cal001, cal002, ...; the "
                     "run tra001, tra002, ... (the next free one is filled in at every acquisition start). Record (top bar) "
                     "switches recording on and off inside the run file. Export .tra writes the LabVIEW trace files of the "
                     "run named in the box, tra001-000, tra001-001, ... (one per 2,000,000 frames), for the existing analysis.")
        lab.setWordWrap(True)
        f.addRow(lab)
        self.ed_h5 = QLineEdit("")
        f.addRow("Run file", _row(self.ed_h5, QPushButton("Browse...", clicked=self._browse_h5)))
        f.addRow(_row(QPushButton("Export .tra", clicked=lambda: self._export("tra")),
                      QPushButton("Export .cal", clicked=lambda: self._export("cal")),
                      QPushButton("Open run (summary)", clicked=self._open_run),
                      QPushButton("What the run file holds", clicked=self._show_run_doc)))
        self.save_info = QPlainTextEdit()
        self.save_info.setReadOnly(True)
        f.addRow(self.save_info)
        return w

    # ------------------------------------------------------------------ helpers
    def _call(self, fn, what, done=None):
        """Run an API call on the pool; report NotReady / SafetyRefused / DeviceError in the status bar."""
        wk = Worker(fn)
        wk.setAutoDelete(False)
        self._workers.add(wk)
        wk.signals.failed.connect(lambda msg: (self._workers.discard(wk), self._fail(what, msg)))
        wk.signals.done.connect(lambda r: (self._workers.discard(wk), self.statusBar().showMessage(f"{what}: ok", 4000),
                                           done and done(r)))
        self.pool.start(wk)

    def _fail(self, what, msg):
        self.statusBar().showMessage(f"{what}: {msg}", 15000)
        if what == "connect" and "STALE lock" in msg:
            self._offer_stale_takeover(msg)
        if "protocol" in what or what in ("check", "run protocol", "apply edits"):
            self.prot_status.setText(f"{what}: {msg}")
        self._log(f"[gui] {what}: {msg}")

    def _log(self, line, detail=""):
        """The log pane and, so a refusal survives the window (owner 2026-11-04), gui_events.log in the output folder
        (with `detail`, the event's fields, which the pane leaves out: design critique 2026-11-05 #12)."""
        self.events_list.addItem(line)
        if self.events_list.count() > 500:
            self.events_list.takeItem(0)
        self.events_list.scrollToBottom()
        try:
            out = Path(self.ed_out.text() or ".")
            out.mkdir(parents=True, exist_ok=True)
            with open(out / "gui_events.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d ") + line + ("  " + detail if detail else "") + "\n")
        except OSError:
            pass

    def _info(self, title, text):
        QMessageBox.information(self, title, text)

    # ------------------------------------------------------------------ setup
    def _browse_fixture(self):
        d = QFileDialog.getExistingDirectory(self, "Simulator fixture folder", self.ed_fixture.text())
        if d:
            self.ed_fixture.setText(d)

    def _connect(self):
        preset = {"backend": self.backend.currentData(), "mode": self.mode.currentData(),
                  "camera_sdk": self.cam_sdk.currentData()}
        if self.objective.currentData():
            preset["objective"] = self.objective.currentData()
            self.settings.setValue("objective", preset["objective"])
        fx = Path(self.ed_fixture.text())
        if preset["backend"] == "sim" and fx.is_dir():
            preset["fixture"] = str(fx)
            cals = sorted(fx.glob("cal*"))
            if cals and not self.ed_cal.text():
                self.ed_cal.setText(str(cals[0]))
        if estop.active():                              # fault list G15 (owner 2026-10-31): never cleared by Connect
            self._fail("connect", "emergency stop engaged: press Acknowledge first")
            return
        self._call(lambda: api.devices.connect(preset), "connect", self._connected)

    def _offer_stale_takeover(self, msg):
        """Owner 2026-11-04: after a crash or a power loss the rig lock stays with the dead process; the owner takes
        it over here, on their own click (the words riglock logs), and Connect runs again."""
        st = api.rig.status()
        h = st.get("holder") or {}
        why = ""
        try:                                     # the last "Close anyway" of this program, if that is what left it
            note = json.loads(_shutdown.CLOSE_ANYWAY_FILE.read_text(encoding="utf-8"))
            why = f"This program was closed with 'Close anyway' at {note.get('time')} (failed step: {note.get('failed_step')}).\n\n"
        except (OSError, ValueError):
            pass
        try:
            faults = _shutdown.windows_faults(datetime.fromisoformat(str(h.get("since"))))
        except (TypeError, ValueError):
            faults = []
        why += ("Windows recorded after the lock was taken:\n  " + "\n  ".join(faults) + "\n\n" if faults else
                "Windows recorded no crash or hang of python.exe after the lock was taken: the program was killed, its "
                "console window closed, or the PC lost power.\n\n")
        ans = QMessageBox.question(
            self, "Rig lock left by a dead program",
            f"The rig lock is held by {h.get('name')} (pid {h.get('pid')}, since {h.get('since')}), a process that no "
            "longer runs - a program ended without its cleanup (a crash, a power loss, Close anyway).\n\n" + why +
            "Take the lock over and connect? The program then opens every device fresh and reads it back (the PI "
            "limits are rewritten at open). If you are not sure what state the rig is in, look at it first.\n\n"
            f"({msg[:300]})",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        reason = f"owner via GUI 'Take over' at {time.strftime('%Y-%m-%d %H:%M:%S')}: {h.get('name')} pid {h.get('pid')} is gone"
        def taken(_):
            with contextlib.suppress(OSError):
                _shutdown.CLOSE_ANYWAY_FILE.unlink()
            self._connect()
        self._call(lambda: api.rig.recover_stale(reason), "rig lock take-over", taken)

    def _connected(self, st):
        self._show_devices(st)
        if "magnet" in st:                              # the kept touch position is the session's from the start
            mm = self.touch_mm.value()
            self._call(lambda: api.magnet.set_touch_position(mm), "touch position",
                       lambda _: self.touch_info.setText(f"touch position {mm:.2f} mm in force (kept in {TOUCH_FILE.name})"))

    def _unlock_touch(self):
        self.touch_mm.setEnabled(True)
        self.btn_touch_set.setEnabled(True)
        self.touch_info.setText("edit the value, then Set; it is saved and used at every Connect from then on")

    def _set_touch(self):
        mm = round(self.touch_mm.value(), 2)
        self.touch_mm.setEnabled(False)
        self.btn_touch_set.setEnabled(False)
        save_touch_mm(mm)
        if "magnet" in api.devices.status():
            self._call(lambda: api.magnet.set_touch_position(mm), "touch position set")
        self.touch_info.setText(f"touch position {mm:.2f} mm saved to {TOUCH_FILE.name}; applied at every Connect")

    def _apply_mode(self):
        """MT hides the EMCCD screen and group; the device set follows at the next Connect."""
        tirf = self.mode.currentData() == "MT-TIRF"
        self.em_view.setVisible(tirf)
        self.em_group.setVisible(tirf)
        self.setWindowTitle(self.base_title + f"  [{self.mode.currentData()}]")
        if api.devices.status():
            self.statusBar().showMessage("mode applies to the devices at the next Connect (Disconnect first)", 8000)

    def _disconnect(self):
        # rig 2026-10-30: "Close anyway" from here left the window, the devices and the lock alive (the owner then
        # closed by the X and the sequence ran again); it now ends the program like the X does
        if not run_shutdown(self):
            self._closed_anyway = True
            self.close()
            return
        self._show_devices(api.devices.status())

    def _self_check(self):
        def show(res):
            lines = [f"{d}: " + ", ".join(f"{s['step']} {'ok' if s['ok'] else 'FAIL'}" + (f" ({s['detail']})"
                     if s.get("detail") else "") for s in steps) for d, steps in res.items()]
            self._info("Self-check", "\n".join(lines))
        self._call(api.devices.self_check, "self-check", show)

    def _device_info(self, row, _col):
        """A click on a device row opens that device's panel: information as rows and its settable values as
        numeric fields (owner 2026-10-31: a control panel, not a raw dump)."""
        item = self.dev_table.item(row, 0)
        if item is None:
            return
        self._refresh_device(item.text())

    def _refresh_device(self, name):
        self.dev_panel.setWindowTitle(f"Device: {name}")
        self._call(lambda: api.devices.info(name), f"info {name}", lambda d: self._fill_device_panel(name, d))

    def _fill_device_panel(self, name, d):
        w = QWidget()
        f = QFormLayout(w)
        ident = d.get("identity") or {}
        self.dev_info.setText("; ".join(f"{k}: {v}" for k, v in ident.items() if not isinstance(v, (dict, list))))
        for k, v in (d.get("settings") or {}).items():
            f.addRow(f"{k} (read back)", QLabel(str(v)))
        for k, v in (d.get("limits") or {}).items():
            f.addRow(f"limit {k}", QLabel(str(v)))
        for q, e in (d.get("profile_limits") or {}).items():
            f.addRow(f"profile {q}", QLabel(f"{e.get('min')} .. {e.get('max')} {e.get('unit', '')}"
                                            + (" from the session start" if e.get("relative_to") else "")))
        errs = d.get("recent_errors") or []
        if errs:
            f.addRow("recent errors", QLabel("\n".join(f"{x.get('command')}: {x.get('hint')}" for x in errs[-3:])))
        self.dev_controls = {}
        build = getattr(self, f"_controls_{name}", None)
        if build is not None and d.get("settings") is not None:
            build(f, d, self.dev_controls)
        lay = self.dev_panel.layout()
        if self.dev_form is not None:
            lay.removeWidget(self.dev_form)
            self.dev_form.deleteLater()
        self.dev_form = w
        lay.insertWidget(1, w)                           # under the identity line, above the camera boxes
        self.cam_box.setVisible(name == "camera")
        self.em_box.setVisible(name == "emccd")
        self.dev_panel.resize(*((900, 900) if name in ("camera", "emccd") else (640, 520)))
        self.dev_panel.open_()

    def _dev_act(self, name, what, fn):
        """A device-panel action: run it, then read the device back into the panel."""
        self._call(fn, what, lambda _: self._refresh_device(name))

    @staticmethod
    def _window(e, origin, lo_default, hi_default):
        lo, hi = e.get("min"), e.get("max")
        if e.get("relative_to") and origin is not None and lo is not None and hi is not None:
            lo, hi = origin + lo, origin + hi
        return (lo_default if lo is None else lo), (hi_default if hi is None else hi)

    def _controls_magnet(self, f, d, c):
        pl, s = d.get("profile_limits") or {}, d["settings"]
        lo, hi = self._window(pl.get("magnet_position_mm", {}), None, 0.0, 40.9)
        slo, shi = self._window(pl.get("magnet_speed_mm_s", {}), None, 0.1, 15.0)
        c["position_mm"] = _spin(lo, hi, 0.1, float(s["position"]), 3, " mm")
        c["speed_mm_s"] = _spin(max(slo, 0.01), shi, 0.5, float(s["speed"]), 2, " mm/s")
        f.addRow("Position, speed", _row(c["position_mm"], c["speed_mm_s"], QPushButton("Move", clicked=lambda: self._dev_act(
            "magnet", "magnet move",
            lambda: api.magnet.move_to(c["position_mm"].value(), c["speed_mm_s"].value()).wait(60)))))

    def _controls_rotor(self, f, d, c):
        pl, s = d.get("profile_limits") or {}, d["settings"]
        slo, shi = self._window(pl.get("rotor_speed_turns_s", {}), None, 0.01, 3.0)
        c["turns"] = _spin(-100.0, 100.0, 1.0, 1.0, 2, " turns")
        c["speed_turns_s"] = _spin(max(slo, 0.01), shi, 0.1, float(s["speed"]), 2, " turns/s")
        f.addRow("Rotate (relative), speed", _row(c["turns"], c["speed_turns_s"], QPushButton("Rotate", clicked=lambda: self._dev_act(
            "rotor", "rotor rotate",
            lambda: api.rotor.rotate(c["turns"].value(), c["speed_turns_s"].value()).wait(60)))))

    def _controls_stage(self, f, d, c):
        pl, (x, y) = d.get("profile_limits") or {}, d["settings"]["position"]
        origin = d.get("origin") or (None, None)
        xlo, xhi = self._window(pl.get("stage_x_mm", {}), origin[0], -500.0, 500.0)
        ylo, yhi = self._window(pl.get("stage_y_mm", {}), origin[1], -500.0, 500.0)
        c["x_mm"], c["y_mm"] = _spin(xlo, xhi, 0.01, float(x), 4, " mm"), _spin(ylo, yhi, 0.01, float(y), 4, " mm")
        f.addRow("X, Y", _row(c["x_mm"], c["y_mm"], QPushButton("Move", clicked=lambda: self._dev_act(
            "stage", "stage move", lambda: api.stage.move_to(c["x_mm"].value(), c["y_mm"].value()).wait(30)))))

    def _controls_focus(self, f, d, c):
        pl, s = d.get("profile_limits") or {}, d["settings"]
        lo, hi = self._window(pl.get("focus_z_um", {}), d.get("origin"), -5000.0, 5000.0)
        c["z_um"] = _spin(lo, hi, 0.1, float(s["position"]), 3, " um")
        f.addRow("Z", _row(c["z_um"], QPushButton("Move", clicked=lambda: self._dev_act(
            "focus", "focus move", lambda: api.focus.move_to(c["z_um"].value()).wait(30)))))

    def _controls_arduino(self, f, d, c):
        lim = (d.get("limits") or {}).get("ratio", [1, 65536])
        c["ratio"] = QSpinBox()
        c["ratio"].setRange(int(lim[0]), int(lim[1]))
        c["ratio"].setValue(int(d["settings"]["ratio"]))
        f.addRow("Frame divider ratio", _row(c["ratio"], QPushButton("Set", clicked=lambda: self._dev_act(
            "arduino", "sync ratio", lambda: api.sync.set_ratio(c["ratio"].value())))))

    def _controls_light(self, f, d, c):
        for laser, on in d["settings"].items():
            c[laser] = QCheckBox(f"{laser} nm on")
            c[laser].setChecked(bool(on))
            c[laser].toggled.connect(lambda v, k=laser: self._dev_act("light", f"laser {k}", lambda: api.light.set(k, v)))
            f.addRow(c[laser])

    def _show_devices(self, st):
        self.dev_table.setRowCount(len(st))
        for i, (name, d) in enumerate(sorted(st.items())):
            self.dev_table.setItem(i, 0, QTableWidgetItem(name))
            self.dev_table.setItem(i, 1, QTableWidgetItem(str(d.get("state"))))
            self.dev_table.setItem(i, 2, QTableWidgetItem(str(d.get("last_error") or "")))
        ok = sum(1 for d in st.values() if d.get("state") == "connected")
        self.dev_summary.setText(f"Devices: {ok} / {len(st)} connected" if st else "Devices: not connected")

    def _set_cam_attribute(self, name, value):
        """Runs on the worker: an attribute that changes how frames are produced needs confirm=True while recording;
        the refusal names it, so retry confirmed only when the owner said yes beforehand (the panel's checkbox)."""
        return api.camera.set_attribute(name, value, confirm=self.cam_attrs_confirm.isChecked())

    def _apply_preset(self):
        preset = {"name": "gui", "roi": (0, 0, 1280, 1024), "rate_Hz": self.cam_rate.currentData(),
                  "exposure_ms": self.cam_exp.value(), "gain_dB": self.cam_gain.value()}
        if self.backend.currentData() == "real":
            preset.pop("gain_dB")                  # read-only on the JAI until its gain unit is verified (jai.py)
        if api.acq.status().get("recording") and QMessageBox.question(
                self, "Recording is on", "Rate and ROI changes alter how the recorded data are read and are logged "
                "into the run as a guarded change. Apply anyway?") != QMessageBox.StandardButton.Yes:
            return                                 # fault list G5: confirm=True below is the operator's yes, not a default
        self._call(lambda: api.camera.apply_preset(preset, confirm=True), "camera preset",
                   lambda r: self.readback.setText(f"camera: {r}"))

    def _apply_emccd(self):
        preset = {"name": "gui", "em_gain_mode": self.em_mode.currentData(), "em_gain": int(self.em_gain.value()),
                  "exposure_ms": self.em_exp.value(), "rate_Hz": self.em_rate.value(),
                  "temperature_C": int(self.em_temp.value())}
        self._call(lambda: api.emccd.apply_preset(preset), "emccd preset",
                   lambda r: self.em_readback.setText(f"emccd read back: {r}"))

    def _shutter(self, mode):
        self._call(lambda: api.emccd.set_shutter(mode), f"emccd shutter {'open' if mode == 1 else 'closed'}",
                   lambda r: self.em_readback.setText(f"emccd shutter: {'open' if r == 1 else 'closed'}"))

    def _exercise_emccd(self):
        n, pause = int(self.em_cycles.value()), self.em_pause.value()
        self.em_readback.setText(f"emccd shutter exercise: {n} cycles at {pause:g} s running...")
        self._call(lambda: api.emccd.exercise_shutter(n, pause), "emccd shutter exercise",
                   lambda r: self.em_readback.setText(
                       f"emccd shutter exercise: {r['calls_ok']} of {2 * r['cycles']} calls ok"
                       + (f"; STOPPED at cycle {r['stopped_at'][0]} ({r['stopped_at'][1]}): {r['stopped_at'][2]}"
                          if r["stopped_at"] else "; every call returned DRV_SUCCESS; shutter closed")))

    def _snap_emccd(self):
        def show(img):
            self._show_emccd(img, "snap")
            self.em_readback.setText(f"emccd frame {img.shape[1]} x {img.shape[0]}: min {img.min()} max {img.max()} "
                                     f"mean {img.mean():.1f}")
        self._call(api.emccd.snap, "emccd snap", show)

    def _show_emccd(self, img, what):
        self.em_img.setImage(img.T, autoLevels=True)
        self.em_label.setText(f"EMCCD {what}  {img.shape[1]} x {img.shape[0]}  mean {img.mean():.1f}")

    def _toggle_emccd_live(self):
        if self.btn_em_live.isChecked():
            self._call(api.emccd.start, "emccd live")
        else:
            self._call(api.emccd.stop, "emccd live stop")

    def _em_tick(self):
        """Part of the 30 Hz tick: while Live is down, fetch the frames not yet read and show the last one."""
        if not self.btn_em_live.isChecked() or self._em_busy:
            return
        self._em_busy = True

        def show(r):
            self._em_busy = False
            if r is not None:
                _first, last, frames = r
                self._show_emccd(frames[-1], f"live  frame {last}  (+{len(frames)})")

        def failed(msg):
            self._em_busy = False
            self.btn_em_live.setChecked(False)
            self._fail("emccd live", msg)
        wk = Worker(api.emccd.read_new)
        wk.setAutoDelete(False)
        self._workers.add(wk)
        wk.signals.failed.connect(lambda msg: (self._workers.discard(wk), failed(msg)))
        wk.signals.done.connect(lambda r: (self._workers.discard(wk), show(r)))
        self.pool.start(wk)

    # ------------------------------------------------------------------ explore
    def _move_magnet(self):
        p, v = self.mag_pos.value(), self.mag_speed.value()
        self._call(lambda: api.magnet.move_to(p, v).wait(120), f"magnet -> {p:.3f} mm at {v:g} mm/s")

    def _move_magnet_by(self):
        d, v = self.mag_by.value(), self.mag_speed.value()
        if d == 0:
            return
        self._call(lambda: api.magnet.move_to(api.magnet.position() + d, v).wait(120), f"magnet {d:+.3f} mm",
                   lambda _: self.mag_by.setValue(0.0))          # the entry returns to 0 once the move is done

    def _go_preset(self, key):
        p, v = self.preset_mm[key].value(), self.mag_speed.value()
        self._call(lambda: api.magnet.move_to(p, v).wait(120), f"magnet -> {key} {p:.3f} mm")

    def _set_force(self):
        f = self.force_pn.value()
        self._call(lambda: api.magnet.set_force(f).wait(60), f"force -> {f:.2f} pN")

    def _rotate(self, n=None):
        """n: the turns of the +1 / -1 buttons (owner 2026-11-05: one turn at a click), else the entry, which goes
        back to 0 after the move."""
        v = self.rotor_speed.value()
        from_entry = n is None
        n = self.rotor_turns.value() if from_entry else n
        if n == 0:
            return
        self._call(lambda: api.rotor.rotate(n, v).wait(60), f"rotor {n:+.1f} turns at {v:g} turns/s",
                   lambda _: from_entry and self.rotor_turns.setValue(0.0))

    def _move_focus(self):
        z = self.focus_um.value()
        self._call(lambda: api.focus.move_to(z).wait(30), f"focus -> {z:.2f} um")

    def _move_focus_by(self):
        d = self.focus_by.value()
        if d == 0:
            return
        self._call(lambda: api.focus.move_to(api.focus.position() + d).wait(30), f"focus {d:+.2f} um",
                   lambda _: self.focus_by.setValue(0.0))

    # ------------------------------------------------------------------ beads
    def _browse_cal(self):
        p, _ = QFileDialog.getOpenFileName(self, "Calibration (.cal) file", str(Path(self.cal_out.text()).parent))
        if p:
            self.ed_cal.setText(p)
            self._follow_cal_folder(p)
            self._load_cal_list()

    _out_browsed = False          # the user chose the run folder by hand (Save page): the .cal's folder no longer wins

    def _follow_cal_folder(self, cal_path):
        """Owner 2026-11-06: the run file goes next to the calibration unless the user browsed a run folder."""
        if not self._out_browsed:
            folder = Path(cal_path).parent
            self.ed_out.setText(str(folder))
            self.ed_name.setText(next_tra(folder))

    def _load_cal_list(self):
        path = Path(self.ed_cal.text())
        try:
            cal = read_cal(path)
        except Exception as e:  # noqa: BLE001
            self._fail("read .cal", f"{type(e).__name__}: {e}")
            return
        self.bead_list.clear()
        for i, (x, y) in enumerate(cal["xy"][:, :2], start=1):
            it = QListWidgetItem(f"bead {i}: x {x:.1f}, y {y:.1f} px")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, i)
            self.bead_list.addItem(it)
        self.lut = (int(cal["n_slices"]), float(cal["z_step"]))     # z = index x step: 0 .. (n - 1) x step
        self.beads_info.setText(f"{len(cal['xy'])} beads, {cal['n_slices']} slices x {cal['z_step'] * 1000:.0f} nm "
                                f"(z 0 .. {(cal['n_slices'] - 1) * cal['z_step']:.1f} um, middle "
                                f"{(cal['n_slices'] // 2) * cal['z_step']:.1f}), "
                                f"{cal['date']}")
        with contextlib.suppress(Exception):           # the viewer (Calibrate) shows the same file
            self.calview.load(path)

    def _new_calibration(self):
        """Owner 2026-11-05: to calibrate again while tracking, the beads must go: the selection is dropped, the
        acquisition goes on without beads (the run file closes; no camera restart), and left clicks pick on the
        image."""
        self.autofocus.setChecked(False)
        self.bead_ids, self.roles, self.cal_path = [], {}, None
        self._clear_picks()
        self._rebuild_chips()
        self.history.clear()
        self.z_zero = None
        before, self._precal_before = getattr(self, "_precal_before", None), None
        binning, self._precal_binning = getattr(self, "_precal_binning", None), None

        def dropped(_):
            self.beads_info.setText("no beads selected: left click beads on the image, then Calibrate")
            self.ed_h5.setText("")
            self.run_track.setText("4. camera running, no beads: nothing is written")
            self._draw_boxes(np.empty((0, 2)), np.empty(0, bool))

        def job():
            api.beads.clear()
            if api.acq.running():
                api.acq.retarget()
            if binning:                          # the camera as it was before the pre-calibration matched it
                match_binning(binning)
            if before:
                match_camera(before)
        self._call(job, "new calibration", dropped)

    def _select_beads(self):
        """With acquisition running the beads are tracked from the next frame on, into the run file named in Save
        (owner 2026-11-05: no camera restart); otherwise they wait for Start acquisition."""
        self._clear_picks()
        ids = [self.bead_list.item(i).data(Qt.UserRole) for i in range(self.bead_list.count())
               if self.bead_list.item(i).checkState() == Qt.Checked]
        refs = {int(s) for s in self.role_ref.text().replace(" ", "").split(",") if s}
        path = self.ed_cal.text()

        def done(pos):
            self.bead_ids = list(ids)
            self.roles = {i: ("reference" if i in refs else "tethered") for i in ids}
            self.cal_path = path
            self.beads_info.setText(f"selected {ids}; reference {sorted(refs & set(ids))}")
            self._rebuild_chips()
            self._draw_boxes(np.array([[pos[i]["x_px"], pos[i]["y_px"]] for i in ids]), np.ones(len(ids), bool))
            if running:
                self.history.clear()
                self.t0 = time.time()
                self.ed_h5.setText(str(folder / f"{name}.h5"))
                self.ed_name.setText(next_tra(folder))
                self.run_track.setText(f"4. tracking {len(ids)} beads -> {self.ed_h5.text()}; Record writes into it")

        running = api.acq.running()
        folder, name = Path(self.ed_out.text()), self.ed_name.text().strip() or next_tra(Path(self.ed_out.text()))
        roles = {i: ("reference" if i in refs else "tethered") for i in ids}
        zm, gpu = self.z_method.currentText(), self.gpu.isChecked()

        def job():
            pos = api.beads.select(ids, cal_path=path)
            if running:
                folder.mkdir(parents=True, exist_ok=True)
                api.acq.retarget(folder=folder, name=name, roles=roles, z_method=zm, gpu=gpu)
            return pos
        self._call(job, "select beads", done)

    def _chip_texts(self, xyz):
        """'b3 z 5.4/5.9': the raw z (never reference-subtracted) against the LUT's top (owner 2026-11-06: is the bead
        near the calibration boundary?); orange when near, 'lost' when the row is the kernel's (-1, -1, -1) marker
        (tested on x: with a negative z step, the mirror test, z <= 0 is a value)."""
        if self.lut is None:
            return
        top = (self.lut[0] - 1) * self.lut[1]
        for k, i in enumerate(self.bead_ids):
            c = self.chips.get(i)
            if c is None or k >= len(xyz):
                continue
            lost, zk = xyz[k][0] < 0, float(xyz[k][2])
            c.setText(f"b{i} lost" if lost else f"b{i} {zk:.1f}/{top:.1f}")
            near = not lost and self._near_edge(zk)
            if getattr(c, "_near", None) != near:
                c._near = near
                c.setStyleSheet(f"color:{'#F97316' if near else COLORS[k % len(COLORS)]}")

    def _rebuild_chips(self):
        while self.bead_chips.count():
            w = self.bead_chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.chips = {}
        for k, i in enumerate(self.bead_ids):
            c = QCheckBox(f"b{i}")
            c.setChecked(True)
            c.setFixedWidth(CHIP_W)
            c.setStyleSheet(f"color:{COLORS[k % len(COLORS)]}")
            self.bead_chips.addWidget(c, k // CHIPS_PER_ROW, k % CHIPS_PER_ROW)
            self.chips[i] = c
        for plot in (self.plot, self.plot2):
            plot.clear()
            plot.addLegend(offset=(10, 10))
        self.curves, self.curves2 = {}, {}

    def _on_view_click(self, ev):
        """Pick beads on the JAI image (owner 2026-10-30: tracking before the TIRF set-up): left click adds a bead
        at the click, right click removes the nearest pick; the picks are what the z scan calibrates."""
        if not self.vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        if self.bead_ids:                 # owner 2026-11-05: "clicking did nothing" - say why
            self.statusBar().showMessage("beads are selected from a .cal: press 'Reset calibration' (Run) to pick again", 8000)
            return
        pt = self.vb.mapSceneToView(ev.scenePos())
        x, y = float(pt.x()), float(pt.y())
        if ev.button() == Qt.RightButton:
            if self.picks:
                k = min(range(len(self.picks)), key=lambda i: (self.picks[i][0] - x) ** 2 + (self.picks[i][1] - y) ** 2)
                if abs(self.picks[k][0] - x) < 40 and abs(self.picks[k][1] - y) < 40:
                    del self.picks[k]
        elif ev.button() == Qt.LeftButton:
            img = self.img_item.image
            why = zscan.outside_margin(img.shape, [(x, y)], self.cal_cross.value()) if img is not None else []
            if why:                           # owner 2026-11-04: a pick near the edge broke the z scan after 60 slices
                self._fail("pick", why[0].replace("bead 1 ", ""))
                return
            self.picks.append((x, y))
        self._draw_picks()

    def _draw_picks(self):
        for it in self.pick_items:
            self.vb.removeItem(it)
        self.pick_items = []
        h = 36
        for k, (x, y) in enumerate(self.picks):
            pen = pg.mkPen("#FBBF24", width=2, style=Qt.DashLine)
            r = pg.QtWidgets.QGraphicsRectItem(x - h, y - h, 2 * h, 2 * h)
            r.setPen(pen)
            t = pg.TextItem(f"pick {k + 1}", color="#FBBF24")
            t.setPos(x - h, y - h - 18)
            self.vb.addItem(r)
            self.vb.addItem(t)
            self.pick_items += [r, t]
        self.picks_info.setText(f"{len(self.picks)} picked (left click on the image adds, right click removes); "
                                "Calibrate scans them" if self.picks else
                                "no picks: left click beads on the JAI image (acquisition running, no beads selected)")
        self.run_beads.setText(f"2. Left click the beads on the image (right click removes a pick): {len(self.picks)} picked")

    def _clear_picks(self):
        self.picks = []
        self._draw_picks()

    lut = None                     # (n_slices, z_step um) of the .cal in use

    def _near_edge(self, z):
        """Owner 2026-11-06: z within EDGE_SLICES of either LUT end (the tracker drops the bead 2-3 slices from it)."""
        if self.lut is None or z is None:
            return False
        n, step = self.lut
        i = z / step                                  # the LUT index; a negative step (the mirror test) has z <= 0
        return i < EDGE_SLICES or i > n - 1 - EDGE_SLICES

    def _draw_boxes(self, xy, good, z=None):
        for b in self.boxes:
            self.vb.removeItem(b)
        self.boxes = []
        h = 36
        for k, ((x, y), g) in enumerate(zip(xy, good)):
            if x < 0:                                 # lost: the kernel's (-1, -1, -1) row
                continue
            near = z is not None and self._near_edge(float(z[k]))
            pen = pg.mkPen("#9CA3AF" if not g else "#F97316" if near else COLORS[k % len(COLORS)], width=2)
            r = pg.QtWidgets.QGraphicsRectItem(x - h, y - h, 2 * h, 2 * h)
            r.setPen(pen)
            self.vb.addItem(r)
            t = pg.TextItem(f"b{self.bead_ids[k] if k < len(self.bead_ids) else k + 1}", color=pen.color())
            t.setPos(x - h, y - h - 18)
            self.vb.addItem(t)
            self.boxes += [r, t]

    # ------------------------------------------------------------------ calibration
    def _browse_cal_out(self):
        p, _ = QFileDialog.getSaveFileName(self, "Write .cal to (LabVIEW names them cal001, cal002, ...)",
                                           self.cal_out.text(), "Calibration (cal*);;All (*)")
        if p:
            self.cal_out.setText(p)
            self._follow_cal_folder(p)

    def _run_zscan(self):
        beads = api.beads.selected()
        if not self.picks and beads is None:
            self._fail("z scan", "pick beads on the image or select beads first (their positions are scanned)")
            return
        if not api.acq.running():
            self._fail("z scan", "start acquisition first (frames come from the display)")
            return
        path = Path(self.cal_out.text())
        if path.exists():                 # owner 2026-11-05: a calibration is often redone; the typed name overwrites on a yes
            if QMessageBox.question(self, "Overwrite the calibration?", f"{path} exists. Overwrite it with this z scan?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            path.unlink()
            self._log(f"[gui] z scan: {path} overwritten on the owner's yes")
        path.parent.mkdir(parents=True, exist_ok=True)
        slices, step, avg, cross, settle = (self.cal_slices.value(), self.cal_step.value(), self.cal_avg.value(),
                                            self.cal_cross.value(), self.cal_settle.value())
        xy = np.array(self.picks, dtype=np.float64) if self.picks else beads.xy0.copy()
        self.cal_status.setText("running...")

        def job():
            return api.zscan.run(str(path), xy.tolist(), slices, step, avg, cross, settle_s=settle)

        def done(cal):
            self.cal_status.setText(f"done: {len(cal['xy'])} beads, {slices} slices x {step:.0f} nm -> {path}; "
                                    "the focus is at the LUT's middle - track from here")
            self.ed_cal.setText(str(path))
            self.cal_out.setText(str(next_free(path)))        # the next scan gets the next number unless told otherwise
            self._follow_cal_folder(path)
            self._load_cal_list()
            self.calview.load(path)
            if getattr(self, "_flow", None):
                self._track_from_cal(path)
                self._flow = None
        wk = Worker(job)                 # a failed scan is shown in the Calibrate label, not only in the status bar
        wk.setAutoDelete(False)
        self._workers.add(wk)
        wk.signals.failed.connect(lambda msg: (self._workers.discard(wk), self.cal_status.setText(f"FAILED: {msg}"),
                                               self._fail("z scan", msg)))
        wk.signals.done.connect(lambda r: (self._workers.discard(wk), done(r)))
        self.pool.start(wk)

    # ------------------------------------------------------------------ acquisition / recording
    def _toggle_acq(self):
        if api.acq.running():
            self._call(api.acq.stop, "stop acquisition",
                       lambda _: (self._live_text(False), self.run_track.setText("4. not tracking")))
            return
        tracking = bool(self.bead_ids)   # owner 2026-11-05: watching the camera writes no run file; the file is asked
        folder = Path(self.ed_out.text()) if tracking else None   # for when tracking starts (Run page step 3)
        name = (self.ed_name.text().strip() or None) if tracking else None
        if folder:
            folder.mkdir(parents=True, exist_ok=True)
        zm, gpu, roles = self.z_method.currentText(), self.gpu.isChecked(), dict(self.roles)
        self.history.clear()
        self.t0 = time.time()

        def done(st):
            self._live_text(True)
            self.ed_h5.setText(str(folder / f"{name}.h5") if folder and name else "")
            if folder:
                self.ed_name.setText(next_tra(folder))
            self.run_track.setText(f"4. tracking {len(self.bead_ids)} beads -> {self.ed_h5.text()}; Record writes into it"
                                   if tracking else "4. camera running, no beads: nothing is written")
        self._call(lambda: api.acq.start(record=False, name=name, folder=folder, roles=roles, z_method=zm, gpu=gpu),
                   "start acquisition", done)

    def _toggle_autofocus(self, on):
        refs = [i for i in self.bead_ids if self.roles.get(i) == "reference"]
        if on and not refs:
            self.autofocus.setChecked(False)
            self._fail("autofocus", "no reference bead is tracked: calibrate and select beads with a reference first")
            return
        pct = self.af_target.value()

        def switch():
            if on:
                api.focus.set_autofocus_target(pct)
            return api.focus.autofocus(on, bead_id=refs[0] if on else None)
        self._call(switch, "autofocus", self._af_text)

    def _set_af_target(self, pct):
        self.settings.setValue("af_target", pct)
        self._call(lambda: api.focus.set_autofocus_target(pct), "autofocus target", self._af_text)

    def _af_text(self, st):
        self.af_status.setText(f"holding bead {st['bead']} at z {st['z_center_um']:.2f} um" if st["on"] else "off")
        if self.autofocus.isChecked() != st["on"]:     # a protocol's `autofocus on / off` (owner 2026-11-12)
            self.autofocus.blockSignals(True)
            self.autofocus.setChecked(st["on"])
            self.autofocus.blockSignals(False)

    def _live_text(self, on):
        self.btn_run_cam.setText("Stop the camera" if on else "1. Start the camera")
        if not on:
            self.autofocus.setChecked(False)

    def _toggle_rec(self):
        on = self.btn_rec.isChecked()
        self._call(lambda: api.acq.set_recording(on), "recording on" if on else "recording off",
                   lambda _: self.btn_rec.setText("* Recording (press to stop)" if on else "4. Record on"))

    def _toggle_display(self):
        self.display_on = not self.display_on
        self.btn_display.setText("Pause display" if self.display_on else "Resume display")

    def _estop(self):
        with events.as_caller("gui"):
            estop.engage("GUI STOP button")
        self.estop_banner.setVisible(True)
        self.statusBar().showMessage("EMERGENCY STOP engaged: moves are void until Acknowledge", 0)

    def _estop_clear(self):
        with events.as_caller("gui"):
            estop.clear()
        self.estop_banner.setVisible(False)
        self.statusBar().showMessage("emergency stop released", 5000)

    def _mark(self):
        text = self.mark_text.text()
        self._call(lambda: api.acq.mark(text), f"mark '{text}'")

    # ------------------------------------------------------------------ protocol
    def _data_root(self):
        """Where data dialogs start: the owner's G:\\Data when it exists, else the run folder."""
        return DATA_ROOT if DATA_ROOT.is_dir() else Path(self.out)

    def _protocols_dir(self):
        return self._data_root() / "protocols"

    def _list_protocols(self):
        """The combo on the Experiment page: every .mtprot in the protocols folder (owner 2026-11-05: the protocols
        used again and again, one click instead of typing)."""
        self.prot_files.blockSignals(True)
        self.prot_files.clear()
        files = sorted(self._protocols_dir().glob("*.mtprot")) if self._protocols_dir().is_dir() else []
        self.prot_files.addItem(f"my protocols ({self._protocols_dir()})" if files else
                                f"no saved protocols yet: Save as... puts them in {self._protocols_dir()}", None)
        for f in files:
            self.prot_files.addItem(f.stem, str(f))
        self.prot_files.blockSignals(False)

    def _pick_protocol(self, _i):
        p = self.prot_files.currentData()
        if p:
            self.prot_edit.setPlainText(Path(p).read_text(encoding="utf-8"))
            self.prot_status.setText(f"{Path(p).name} loaded; {self._estimate_text(self.prot_edit.toPlainText())}")

    def _load_protocol(self):
        p, _ = QFileDialog.getOpenFileName(self, "Protocol", str(self._protocols_dir()), "Protocol (*.mtprot);;All (*)")
        if p:
            self.prot_edit.setPlainText(Path(p).read_text(encoding="utf-8"))

    def _save_protocol(self):
        self._protocols_dir().mkdir(parents=True, exist_ok=True)
        p, _ = QFileDialog.getSaveFileName(self, "Save protocol as", str(self._protocols_dir()), "Protocol (*.mtprot)")
        if p:
            Path(p).write_text(self.prot_edit.toPlainText(), encoding="utf-8")
            self._list_protocols()
            self.prot_files.setCurrentIndex(max(0, self.prot_files.findData(p)))

    def _estimate_text(self, text):
        """'estimated 4 min 10 s' for the script text: the hold / wait / ramp t= times with the loops expanded, plus
        each ramp's magnet travel at its speed (needs the force calibration: connected). Unparseable: ''."""
        try:
            script = api.protocol.load(text)
        except Exception:    # noqa: BLE001 - Check names the error; here only the estimate is wanted
            return ""
        from mtpy.protocol.check import duration

        def travel(body):
            total = 0.0
            for st in body:
                if st.kind == "loop":
                    total += st.args["n"].value * travel(st.body)
                elif st.kind == "ramp" and "speed" in st.args:
                    try:
                        p0 = api.magnet.force_position(st.args["from"].value)
                        p1 = api.magnet.force_position(st.args["to"].value)
                        total += abs(p1 - p0) / st.args["speed"].value
                    except Exception:    # noqa: BLE001, S110 - no calibration yet: the ramp is not counted
                        pass
            return total
        total = duration(script.body) + travel(script.body)
        return f"estimated {int(total // 60)} min {total % 60:.0f} s (t=, speed= and rate= moves; the rest not counted)"

    def _show_guide(self):
        """The script guide inside the program (owner 2026-11-05: the .md opened in another application)."""
        if not hasattr(self, "guide_panel"):
            tb = QTextBrowser()
            tb.setOpenExternalLinks(True)
            tb.setMarkdown(GUIDE.read_text(encoding="utf-8"))
            self.guide_panel = _Panel(self, "Script guide", tb)
            self.guide_panel.resize(760, 820)
        self.guide_panel.open_()

    def _show_run_doc(self):
        """Owner 2026-11-06: what the .h5 holds and what its metadata is, as a page inside the program
        (docs/format/run-file.ko.html, generated by tools/run_file_doc.py from a real run)."""
        if not hasattr(self, "run_doc_panel"):
            tb = QTextBrowser()
            tb.setOpenExternalLinks(True)
            tb.setHtml(RUN_DOC.read_text(encoding="utf-8"))
            self.run_doc_panel = _Panel(self, "The run file (.h5)", tb)
            self.run_doc_panel.resize(900, 820)
        self.run_doc_panel.open_()

    def _check_protocol(self):
        text = self.prot_edit.toPlainText()

        def job():
            rep = api.protocol.check(api.protocol.load(text), devices=True)
            return rep
        self._call(job, "check", lambda rep: self.prot_status.setText(
            ("OK" if rep["ok"] else "ERRORS") + (f"; coerced {len(rep['coerced'])}" if rep.get("coerced") else "")
            + ("; " + self._estimate_text(text) if rep["ok"] else "")
            + ("\n" + "\n".join(str(e) for e in rep["errors"]) if rep.get("errors") else "")))

    def _table_to_script(self):
        try:
            self.prot_edit.setPlainText(self.exp_table.to_script())
            self.prot_status.setText(f"script from the table; Check or Start. {self._estimate_text(self.prot_edit.toPlainText())}")
            return True
        except ValueError as e:
            self._fail("table", str(e))
            return False

    def _script_to_table(self):
        try:
            self.exp_table.from_script(self.prot_edit.toPlainText())
            self.prot_status.setText("table from the script")
        except ValueError as e:
            self._fail("script -> table", str(e))

    def _start_from_table(self):
        if self._table_to_script():
            self._run_protocol()

    def _run_protocol(self):
        st = api.protocol.status()
        if st["state"] == "paused":
            self._call(api.protocol.resume, "resume")
            return
        text = self.prot_edit.toPlainText()

        def go():                 # owner 2026-11-05: a new Start ends the protocol that runs and runs this one
            if api.protocol.running():
                api.protocol.stop()
                api.protocol.wait(30)
            return api.protocol.run(api.protocol.load(text))
        self._call(go, "run protocol")

    def _pause_protocol(self):
        self._call(api.protocol.pause, "pause")

    def _stop_protocol(self):
        self._call(api.protocol.stop, "stop protocol")

    def _apply_edits(self):
        text = self.prot_edit.toPlainText()
        self._call(lambda: (api.protocol.edit(api.protocol.load(text)), api.protocol.apply_edits())[1], "apply edits")

    # ------------------------------------------------------------------ save
    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "Run folder", self.ed_out.text())
        if d:
            self.ed_out.setText(d)
            self.ed_name.setText(next_tra(Path(d)))
            self._out_browsed = True

    def _browse_h5(self):
        p, _ = QFileDialog.getOpenFileName(self, "Run file", self.ed_out.text(), "HDF5 (*.h5)")
        if p:
            self.ed_h5.setText(p)

    def _export(self, kind):
        h5 = self.ed_h5.text()
        out = None if kind == "tra" else str(next_free(Path(h5).parent / "cal001"))   # tra: <run>-000 next to the .h5
        if not h5:
            self._fail(f"export .{kind}", "no run file: track with a run file first (Run page) or choose one in Save")
            return

        def done(paths):
            paths = paths if isinstance(paths, list) else [paths]
            self.save_info.setPlainText(f"exported .{kind}:\n" + "\n".join(map(str, paths)))
            self.run_save.setText(f"5. saved: {', '.join(Path(p).name for p in paths)} in {Path(paths[0]).parent}")
        self._call(lambda: api.data.export(kind, h5, out), f"export .{kind}", done)

    def _open_run(self):
        h5 = self.ed_h5.text()

        def done(run):
            a = run["attrs"]
            ev = run.get("events", {})
            lines = [f"{k}: {a[k]}" for k in sorted(a)][:40]
            lines.append("events: " + ", ".join(f"{k} x{len(v.get('event_id', []))}" for k, v in ev.items()))
            self.save_info.setPlainText("\n".join(lines))
        self._call(lambda: api.data.open_run(h5), "open run", done)

    # ------------------------------------------------------------------ periodic
    def _tick(self):
        """30 Hz: the display tap (image, bead boxes) and the live graphs."""
        try:
            snap = api.acq.display() if self._acq_running else None      # the flag: no engine call at 30 Hz
        except api.NotReady:
            snap = None
        self._em_tick()
        if snap is None:
            return
        res = snap.result
        if self.display_on:
            self.img_item.setImage(snap.image, autoLevels=False, levels=(0, 255))
            if res is not None and res.xyz is not None:
                self._draw_boxes(res.xyz[:, :2], res.good, res.xyz[:, 2])
            r = snap.record
            self.cam_label.setText(f"JAI frame {r.buffer_number}  seg {r.segment}  t {r.t_camera_s:.3f} s  "
                                   f"{r.rate_Hz:.1f} Hz  {'REC' if r.recording else ''}")
        if res is not None and res.xyz is not None and getattr(self, "_last_seq", None) != snap.seq:
            self._last_seq = snap.seq
            self.history.append((time.time() - self.t0, self._mag, self._force, res.xyz.copy()))
            now = time.monotonic()
            if now >= self._next_plot:
                self._next_plot = now + 1.0 / self.plot_hz.value()
                self._update_plot()
                self._chip_texts(res.xyz)

    _mag = _force = float("nan")

    def _positions_text(self, st):
        """One line: every connected motor's position read back and the force (owner 2026-11-04)."""
        parts = []
        reads = (("stage", lambda: "stage x {:.4f} y {:.4f} mm".format(*api.stage.position())),
                 ("focus", lambda: f"focus {api.focus.position():.3f} um"),
                 ("rotor", lambda: f"rotor {api.rotor.position():.2f} turns"),
                 ("magnet", lambda: f"magnet {self._mag:.3f} mm" + (f" = {self._force:.2f} pN" if self._force == self._force else "")))
        for name, read in reads:
            if st.get(name, {}).get("state") == "connected":
                try:
                    parts.append(read())
                except Exception as e:  # noqa: BLE001
                    parts.append(f"{name}: {type(e).__name__}")
        return chr(10).join(parts) if parts else "positions: no motor connected"

    def _slow_tick(self):
        """2 Hz: motor read-backs and the status line. The device calls run on a worker and the labels are set when
        they return, so a slow read never freezes the window (2026-11-04 22:28: the window hung, Windows closed it as
        not responding, and the engine was killed with it - the rig lock went stale)."""
        if self._slow_busy:
            return
        self._slow_busy = True
        want_zscan, quiet = self.cal_status.text().startswith(("running", "slice")), not self._workers
        wk = Worker(lambda: self._slow_read(want_zscan, quiet))
        wk.setAutoDelete(False)
        self._slow_worker = wk
        wk.signals.done.connect(self._slow_apply)
        wk.signals.failed.connect(lambda msg: setattr(self, "_slow_busy", False))
        self.pool.start(wk)

    def _slow_read(self, want_zscan, quiet):
        """The reads of one slow tick (worker thread) -> the texts _slow_apply puts on the labels."""
        d = {}
        try:
            d["st"] = st = api.devices.status()
        except Exception:  # noqa: BLE001
            d["st"] = st = {}
        if want_zscan:
            with contextlib.suppress(Exception):
                i, n = api.zscan.progress()
                if n:
                    d["zscan"] = f"slice {i} / {n}"
                    d["prof"] = api.zscan.last_profiles()
        if st and st.get("magnet", {}).get("state") == "connected":
            try:
                self._mag = api.magnet.position()
                lf = api.magnet.live_force(self._mag)          # None until the force calibration is ready
                self._force = lf["force_pN"] if lf else float("nan")
            except Exception as e:  # noqa: BLE001
                self._mag = self._force = float("nan")
                d["readback"] = f"magnet read: {type(e).__name__}: {e}"
        if st and quiet:
            d["positions"] = self._positions_text(st)
        if st and st.get("emccd", {}).get("state") == "connected" and quiet:
            try:
                e = api.emccd.settings()
                d["em"] = (f"emccd: {e['exposure_ms']:.3f} ms, {e['rate_Hz']:.3f} Hz, gain mode "
                           f"{e['em_gain_mode']}, gain {e['em_gain']}, set {e['temperature_C']} C, "
                           f"sensor {e['sensor_temperature_C']} C ({e['cooler']})")
            except Exception as ex:  # noqa: BLE001
                d["em"] = f"emccd read: {type(ex).__name__}: {ex}"
        parts = []
        d["acq_running"] = api.acq.running()
        d["rec"] = False
        if d["acq_running"]:
            a = api.acq.status()
            parts.append(f"acq: {a.get('frames_received', 0)} frames, {a.get('fps_measured', a.get('fps', 0)) or 0:.1f} fps"
                         f"{', REC' if a.get('recording') else ''}")
            d["rec"] = bool(a.get("recording"))
            d["lost"] = (a.get("camera_gaps", 0), a.get("pipeline_drops", 0), a.get("frames_not_written") or 0,
                         a.get("track_ms_p99"))
        else:
            parts.append("acq: stopped")
        try:
            fc = api.magnet.force_calibration()
            parts.append(f"magnet {self._mag:.3f} mm = {self._force:.2f} pN" if fc["ready"] else
                         f"magnet {self._mag:.3f} mm (force: set the touch position in Setup)")
        except Exception:  # noqa: BLE001
            parts.append("magnet: not connected")
        d["protocol"], d["parts"] = api.protocol.status(), parts
        with contextlib.suppress(Exception):
            d["af"] = api.focus.autofocus_status()
        return d

    def _slow_apply(self, d):
        self._slow_busy = False
        try:
            if d.get("prof"):
                self._plot_profiles(d["prof"])
            for key, label in (("zscan", self.cal_status), ("readback", self.readback), ("positions", self.positions),
                               ("em", self.em_readback)):
                if d.get(key):
                    label.setText(d[key])
            self._acq_running = d["acq_running"]
            if d.get("af") is not None and d.get("protocol", {}).get("state") in ("running", "paused"):
                self._af_text(d["af"])            # only a protocol switches it behind the checkbox
            self.rec_badge.setText("\u25cf RECORDING" if d["rec"] else "not recording")
            self.rec_badge.setStyleSheet("background:#B91C1C;color:white;font-weight:bold;padding:2px 8px" if d["rec"] else "")
            if "lost" in d:                       # stopped: the last count stays
                gaps, drops, unwritten, p99 = d["lost"]
                self.lost_label.setText(f"Lost frames: {gaps + drops} (camera {gaps}, queue {drops})"
                                        + (f", NOT WRITTEN {unwritten}" if unwritten else "")
                                        + (f"   track p99 {p99:.1f} ms" if p99 is not None else ""))
                self.lost_label.setStyleSheet("background:#B91C1C;color:white;font-weight:bold;padding:2px 8px"
                                              if gaps + drops + unwritten else "")
            p, parts = d["protocol"], d["parts"]
            parts.append(f"protocol: {p['state']}" + (f" ({p['reason']})" if p.get("reason") else ""))
            self.btn_run.setText("Resume" if p["state"] == "paused" else "Start")
            running = p["state"] in ("running", "paused")
            self.prot_badge.setText(f"PROTOCOL {p['state']}" + (f" ({p.get('name')})" if running and p.get("name") else "")
                                    if running else "no protocol")
            self.prot_badge.setStyleSheet("background: #ffd54f; padding: 2px 8px; font-weight: bold" if running else "")
            cur = p.get("current") if running else None
            if p["state"] != "idle":
                self.prot_status.setText(f"{p['state']}" + (f": {p['reason']}" if p.get("reason") else "")
                                         + (f" - step {cur['step']} line {cur['line']}: {cur['statement']}" if cur else ""))
            self._show_current(cur)
            active = estop.active()
            if active:
                parts.append(f"E-STOP ENGAGED ({estop.reason()})")
                self.estop_text.setText(f"EMERGENCY STOP ENGAGED ({estop.reason()}): every motor halted, every move "
                                        "refused until Acknowledge")
            self.estop_banner.setVisible(bool(active))
            self.statusBar().showMessage("   |   ".join(parts))
        except RuntimeError:                  # the window is closing (widgets deleted) while a read was in flight
            pass

    def _show_current(self, cur):
        """Owner 2026-11-06: the running statement is highlighted in the script and its column in the table (the
        `# column k` comment above the line names the column). The plan that runs is the text as it was at Start."""
        line = cur["line"] if cur else None
        if getattr(self, "_shown_line", None) == line:
            return
        self._shown_line = line
        sel, col = [], None
        if line:
            block = self.prot_edit.document().findBlockByNumber(line - 1)
            if block.isValid():
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(QColor("#ffd54f"))
                s.format.setForeground(QColor("black"))
                s.format.setProperty(QTextFormat.FullWidthSelection, True)
                s.cursor = QTextCursor(block)
                sel.append(s)
            for txt in reversed(self.prot_edit.toPlainText().splitlines()[:line]):
                m = re.match(r"#\s*column\s+(\d+)", txt.strip())
                if m:
                    col = int(m.group(1)) - 1
                    break
        self.prot_edit.setExtraSelections(sel)
        self.exp_table.highlight(col)

    def _plot_profiles(self, p):
        """During a z scan the graph shows every pick's radial profile of the slice just taken (owner 2026-11-05)."""
        if getattr(self, "_prof_slice", None) == p["slice"]:
            return
        self._prof_slice = p["slice"]
        for key in list(self.curves):
            self.plot.removeItem(self.curves.pop(key))
        self.plot.setLabel("bottom", "radial profile bin (mirrored; the middle is the bead centre)")
        self.plot.setLabel("left", f"intensity, slice {p['slice']}")
        for k, prof in enumerate(p["profiles"]):
            self.curves[("prof", k)] = self.plot.plot(np.asarray(prof, dtype=np.float64),
                                                      pen=pg.mkPen(COLORS[k % len(COLORS)], width=1.5), name=f"pick {k + 1}")

    def _update_plot(self):
        if not self.history or not self.bead_ids:
            return
        kx = self.ax_x.currentData()
        self._draw(self.plot, self.curves, kx, self.ax_y.currentData(),
                   self.follow_s.value() if self.follow.isChecked() and kx == "t" else None)
        if self.panel.currentWidget() is self.plot2.parent():     # the tall graph costs nothing while its page is hidden
            # shortcut: the history is turned into arrays once per graph, share them if two graphs cost too much
            self._draw(self.plot2, self.curves2, self.ax_x2.currentData(), self.ax_y2.currentData(),
                       self.last2_s.value() if self.last2.isChecked() else None)

    def _draw(self, plot, curves, kx, ky, last_s):
        """One graph from the history; last_s = only the rows of the last so many seconds (None: all of it)."""
        # a frame tracked before the selection changed has another bead count: it cannot share the array
        h = [r for r in self.history if len(r[3]) == len(self.bead_ids)]
        if not h:
            return
        if last_s is not None:
            tmax = h[-1][0]
            h = [r for r in h if r[0] >= tmax - last_s]
        t = np.array([r[0] for r in h])
        mag = np.array([r[1] for r in h])
        force = np.array([r[2] for r in h])
        xyz = np.array([r[3] for r in h])          # (n, nb, 3)
        xyz = np.where((xyz == -1.0).all(axis=2, keepdims=True), np.nan, xyz)   # lost = the (-1, -1, -1) row
        refs = [k for k, i in enumerate(self.bead_ids) if self.roles.get(i) == "reference"]
        if self.sub_ref.isChecked() and refs:
            with warnings.catch_warnings():            # a frame with every reference lost: NaN, no warning
                warnings.simplefilter("ignore", RuntimeWarning)
                ref = np.nanmean(xyz[:, refs, :], axis=1, keepdims=True)
            xyz = np.where(np.isin(np.arange(len(self.bead_ids)), refs)[None, :, None], xyz, xyz - ref)
        if self._zero_now and xyz.ndim == 3:
            self.z_zero, self._zero_now = np.nan_to_num(xyz[-1, :, 2]), False
        zero = self.z_zero is not None and xyz.ndim == 3 and xyz.shape[1] == len(self.z_zero)
        if zero:
            xyz[:, :, 2] -= self.z_zero
        base = {"t": t, "mag": mag, "force": force}
        cols = {"x": 0, "y": 1, "z": 2}
        sub = self.sub_ref.isChecked() and bool(refs)
        for side, key in (("bottom", kx), ("left", ky)):
            plot.setLabel(side, AXES[key] + (" - reference" if sub and key in cols else "")
                          + (" - zero" if zero and key == "z" else ""))
        if getattr(plot, "_ky", None) != (kx, ky, sub):   # rig 2026-11-05: the legend kept the old axis's name
            for c in curves.values():
                plot.removeItem(c)
            curves.clear()
            plot._ky = (kx, ky, sub)
        if kx in base and ky in base:
            series = {None: (base[kx], base[ky])}
        else:                                   # Request1 item 3: a per-bead axis is each bead's own x / y / z
            series = {i: (base[kx] if kx in base else xyz[:, k, cols[kx]], base[ky] if ky in base else xyz[:, k, cols[ky]])
                      for k, i in enumerate(self.bead_ids) if self.chips.get(i) and self.chips[i].isChecked()}
        for key in list(curves):
            if key not in series:
                plot.removeItem(curves.pop(key))
        for key, (x, y) in series.items():
            if key not in curves:
                k = self.bead_ids.index(key) if key is not None else 0
                name = AXES[ky] if key is None else f"b{key}" + (" (ref, raw)" if sub and self.roles.get(key) == "reference"
                                                                  else " - ref" if sub else "")
                curves[key] = plot.plot(pen=pg.mkPen(COLORS[k % len(COLORS)], width=1.5), name=name)
            curves[key].setData(x, y, connect="finite")
        if self.auto_scale.isChecked():
            plot.enableAutoRange()

    # ------------------------------------------------------------------ events
    def _on_event(self, ev):
        kind = getattr(ev, "kind", "?")
        if kind == "motor_reading":
            if getattr(ev, "device", None) == "magnet" and isinstance(getattr(ev, "readback", None), (int, float)):
                self._mag = float(ev.readback)          # the poller's rate (10 Hz), as the run file has it
                try:
                    self._force = api.magnet.force_at(self._mag)
                except Exception:    # noqa: BLE001, S110 - no calibration: the 2 Hz tick keeps its value
                    pass
            return
        extra = {k: v for k, v in vars(ev).items() if k not in ("t", "kind", "caller", "event_id") and v not in (None, {})}
        self._log(f"{time.strftime('%H:%M:%S', time.localtime(ev.t))}  {kind}  {_sentence(extra)}", detail=str(extra)[:400])
        if kind == "magnet_stall":
            QMessageBox.critical(self, "Magnet stall (decision 0019)",
                                 "The magnet stalled. The move and the protocol were stopped and the magnet returned "
                                 "to 0 mm once; if it is locked, clear it with api.magnet.clear_stall().\n\n"
                                 f"{extra}")

    def closeEvent(self, e):
        # the shutdown sequence (gui/shutdown.py) runs with the window still open; "Close anyway" closes it uncleaned
        self.timer.stop()
        self.slow.stop()
        if api.devices.status() and not self._closed_anyway:
            run_shutdown(self)
            self._show_devices(api.devices.status())
        if api.devices.status():                # closed anyway: the rig lock is kept, the log says so
            events.log("gui", action="closed_uncleaned", devices=sorted(api.devices.status()))
        with contextlib.suppress(Exception):
            self._unsub()
        super().closeEvent(e)
