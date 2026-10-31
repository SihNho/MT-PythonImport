"""Main window (docs/mockups/2026-10-23-main-window, requirements U1-U6, U8, U13, U15, U17-U21, U30): one screen,
step bar, camera view with the bead boxes, any-axis live graphs, status bar and the emergency stop. Every device
action is an `mtpy.api` call made as caller "gui"; long ones run on a worker thread. The window reads the display tap
(api.acq.display) on a 30 Hz timer and can never slow acquisition.
shortcut: the GUI shares the API's process (plan phase 8 says its own process); move it out if phase 6 shows the
camera thread losing frames while the window is dragged.
"""
import contextlib
import json
import time
from collections import deque
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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
    QVBoxLayout,
    QWidget,
)

from mtpy import api
from mtpy.api import estop, events, safety
from mtpy.lvfiles import read_cal
from mtpy.track import Z_METHODS

from . import zscan
from .shutdown import run_shutdown

pg.setConfigOptions(imageAxisOrder="row-major", background="k", foreground="w")

STEPS = [("setup", "Setup"), ("explore", "Explore"), ("beads", "Beads"), ("cal", "Calibrate"),
         ("exp", "Experiment"), ("save", "Save")]
TITLES = {"setup": "Setup: devices, camera, analysis", "explore": "Explore (no recording)",
          "beads": "Beads: select from a .cal", "cal": "Calibrate: z scan -> .cal", "exp": "Experiment: protocol",
          "save": "Save and export"}
AXES = {"t": "Time (s)", "mag": "Magnet (mm)", "force": "Force (pN)", "z": "z (um)", "x": "x (px)", "y": "y (px)"}
COLORS = ["#60A5FA", "#F472B6", "#34D399", "#FBBF24", "#A78BFA", "#F87171", "#2DD4BF", "#FB923C"]
EXAMPLE_PROTOCOL = """grammar 0.1
protocol "example"
# edit freely; Check validates against the API and the rig safety profile
hold f=1 t=2
ramp from=1 to=5 t=5
mark "high force"
hold f=5 t=2
zero t=1
end protocol
"""


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


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


def load_touch_mm():
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
        return float(json.loads(TOUCH_FILE.read_text(encoding="utf-8"))["touch_mm"])
    return TOUCH_DEFAULT_MM


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
        self.pool = QThreadPool.globalInstance()
        self._workers = set()                          # alive until done / failed: the pool would delete them first
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

    def _top_bar(self):
        w = QFrame()
        h = QHBoxLayout(w)
        self.dev_summary = QLabel("Devices: not connected")
        h.addWidget(self.dev_summary, 1)
        self.btn_display = QPushButton("Pause display", clicked=self._toggle_display)
        self.btn_live = QPushButton("Start acquisition", clicked=self._toggle_acq)
        self.btn_rec = QPushButton("Record", clicked=self._toggle_rec)
        self.btn_rec.setCheckable(True)
        self.btn_stop = QPushButton("STOP", clicked=self._estop)
        self.btn_stop.setStyleSheet("background:#B91C1C;color:white;font-weight:bold;padding:6px 18px")
        self.btn_ack = QPushButton("Acknowledge", clicked=self._estop_clear)
        for b in (self.btn_display, self.btn_live, self.btn_rec, self.btn_stop, self.btn_ack):
            h.addWidget(b)
        return w

    def _step_bar(self):
        w = QFrame()
        h = QHBoxLayout(w)
        self.step_group = QButtonGroup(self)
        self.step_group.setExclusive(True)
        for i, (_, label) in enumerate(STEPS):
            b = QPushButton(f"{i + 1}. {label}")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self._set_step(i))
            self.step_group.addButton(b, i)
            h.addWidget(b)
        self.step_title = QLabel("")
        h.addWidget(self.step_title, 1)
        return w

    def _set_step(self, i):
        self.panel.setCurrentIndex(i)
        self.step_group.button(i).setChecked(True)
        self.step_title.setText(TITLES[STEPS[i][0]])

    def _camera_view(self):
        """Two screens side by side (owner 2026-10-30: the JAI and the EMCCD each on their own): left the tracking
        camera with the bead boxes, right the iXon (snap, or live while its Live button is down)."""
        self.view = pg.GraphicsLayoutWidget()
        vb = self.view.addViewBox(lockAspect=True, invertY=True)
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
        for k, label in AXES.items():
            self.ax_y.addItem(label, k)
            if k in ("t", "mag", "force"):
                self.ax_x.addItem(label, k)
        self.ax_y.setCurrentIndex(3)
        self.follow = QCheckBox("Follow 30 s")
        self.follow.setChecked(True)
        self.auto_scale = QCheckBox("Auto scale")
        self.auto_scale.setChecked(True)
        self.bead_chips = QHBoxLayout()
        for lab, wdg in (("Y", self.ax_y), ("X", self.ax_x)):
            ctl.addWidget(QLabel(lab))
            ctl.addWidget(wdg)
        ctl.addWidget(self.follow)
        ctl.addWidget(self.auto_scale)
        ctl.addLayout(self.bead_chips)
        ctl.addStretch(1)
        v.addLayout(ctl)
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
        self.backend = QComboBox()
        self.backend.addItem("sim: every device simulated", "sim")
        self.backend.addItem("real: JAI camera + Andor iXon EMCCD (SDK2) under the rig lock; motors simulated", "real")
        self.backend.addItem("rig: JAI + iXon + motors through the motion gate", "real-motors")
        self.backend.setCurrentIndex(self.backend.findData(self.backend_arg))
        f.addRow("Backend", self.backend)
        self.mode = QComboBox()          # owner 2026-10-30: MT and MT-TIRF are distinct modes of the program
        self.mode.addItem("MT: tracking (JAI, motors)", "MT")
        self.mode.addItem("MT-TIRF: tracking + EMCCD, Arduino sync, lasers, light gating (phase 10a)", "MT-TIRF")
        self.mode.setCurrentIndex(self.mode.findData(api.devices.DEFAULT_MODE))
        self.mode.currentIndexChanged.connect(self._apply_mode)
        f.addRow("Mode", self.mode)
        self.cam_sdk = QComboBox()       # owner 2026-11-01: the JAI's SDK is chosen here; it must match the USB3 Vision driver bound
        self.cam_sdk.addItem("IMAQdx (NI driver - LabVIEW can share the camera)", "imaqdx")
        self.cam_sdk.addItem("eBUS (JAI / Pleora driver - LabVIEW cannot open the camera)", "ebus")
        f.addRow("Camera SDK", self.cam_sdk)
        self.ed_fixture = QLineEdit(str(self.fixture))
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
        cams = QWidget()
        cams_lay = QVBoxLayout(cams)
        self.cam_panel = _Panel(self, "Camera settings", cams)
        f.addRow(QPushButton("Camera settings...", clicked=self.cam_panel.open_))
        g = QGroupBox("Camera preset (U15)")
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
        cams_lay.addWidget(g4)
        g2 = QGroupBox("Analysis (decision 0024)")
        g2f = QFormLayout(g2)
        self.z_method = QComboBox()
        self.z_method.addItems(list(Z_METHODS))
        self.gpu = QCheckBox("Z, XY and radial on the GPU (fused CUDA kernel)")
        g2f.addRow("Z method", self.z_method)
        g2f.addRow(self.gpu)
        f.addRow(g2)
        g3 = QGroupBox("Force equation (decision 0018)")
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

    def _panel_explore(self):
        w = QWidget()
        f = QFormLayout(w)
        hi = float(safety.profile()["limits"]["magnet_position_mm"]["max"])      # 40.9 mm since profile v9
        self.mag_pos = _spin(0.0, hi, 0.1, 0.0, 3, " mm")
        self.mag_slider = QSlider(Qt.Horizontal)
        self.mag_slider.setRange(0, round(hi * 10))
        self.mag_slider.valueChanged.connect(lambda v: self.mag_pos.setValue(v / 10))
        f.addRow("Magnet position", _row(self.mag_pos, QPushButton("Move", clicked=self._move_magnet)))
        f.addRow(self.mag_slider)
        self.force_pn = _spin(0.0, 100.0, 0.1, 1.0, 2, " pN")
        f.addRow("Force", _row(self.force_pn, QPushButton("Set force", clicked=self._set_force)))
        self.rotor_turns = _spin(-50.0, 50.0, 1.0, 1.0, 1, " turns")
        f.addRow("Rotor (relative)", _row(self.rotor_turns, QPushButton("Rotate", clicked=self._rotate)))
        self.focus_um = _spin(-1000.0, 1000.0, 0.1, 0.0, 2, " um")
        f.addRow("Focus z", _row(self.focus_um, QPushButton("Move", clicked=self._move_focus)))
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
        f.addRow("Pick on image", _row(self.picks_info, QPushButton("Clear picks", clicked=self._clear_picks)))
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
        self.cal_slices.setRange(3, 512)
        self.cal_slices.setValue(60)
        self.cal_step = _spin(10.0, 1000.0, 10.0, 100.0, 0, " nm")
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
        self.cal_out = QLineEdit(str(self.out / "cal_gui"))
        f.addRow("Write .cal to", self.cal_out)
        f.addRow(QPushButton("Run z scan (beads of the current selection)", clicked=self._run_zscan))
        self.cal_status = QLabel("not run")
        self.cal_status.setWordWrap(True)
        f.addRow(self.cal_status)
        return w

    def _panel_exp(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.prot_edit = QPlainTextEdit(EXAMPLE_PROTOCOL)
        self.prot_edit.setStyleSheet("font-family:Consolas,monospace")
        v.addWidget(self.prot_edit, 1)
        v.addWidget(_row(QPushButton("Load...", clicked=self._load_protocol),
                         QPushButton("Save as...", clicked=self._save_protocol),
                         QPushButton("Check", clicked=self._check_protocol)))
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
        f.addRow("Run folder", _row(self.ed_out, QPushButton("Browse...", clicked=self._browse_out)))
        self.ed_name = QLineEdit(time.strftime("run_%Y%m%d_%H%M%S"))
        f.addRow("Run name (next acquisition)", self.ed_name)
        lab = QLabel("Acquisition writes <folder>/<name>.h5; Record (top bar) switches recording on and off inside it.")
        lab.setWordWrap(True)
        f.addRow(lab)
        self.ed_h5 = QLineEdit("")
        f.addRow("Run file", _row(self.ed_h5, QPushButton("Browse...", clicked=self._browse_h5)))
        f.addRow(_row(QPushButton("Export .tra", clicked=lambda: self._export("tra")),
                      QPushButton("Export .cal", clicked=lambda: self._export("cal")),
                      QPushButton("Open run (summary)", clicked=self._open_run)))
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
        if "protocol" in what or what in ("check", "run protocol", "apply edits"):
            self.prot_status.setText(f"{what}: {msg}")
        self.events_list.addItem(f"[gui] {what}: {msg}")
        self.events_list.scrollToBottom()

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
        lay.addWidget(w)
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

    def _controls_camera(self, f, d, c):
        s = d["settings"]
        c["exposure_ms"] = _spin(0.001, 1000.0, 0.1, float(s["exposure_ms"]), 3, " ms")
        c["gain_dB"] = _spin(0.0, 48.0, 0.5, float(s["gain_dB"]), 1, " dB")
        c["rate_Hz"] = _spin(0.1, 1000.0, 1.0, float(s["rate_Hz"]), 3, " Hz")
        for key, label, fn in (("exposure_ms", "Exposure", api.camera.set_exposure),
                               ("gain_dB", "Gain", api.camera.set_gain), ("rate_Hz", "Frame rate", api.camera.set_rate)):
            f.addRow(label, _row(c[key], QPushButton("Set", clicked=lambda _=False, k=key, fn=fn, lb=label: self._dev_act(
                "camera", f"camera {lb.lower()}", lambda: fn(c[k].value())))))

    def _controls_emccd(self, f, d, c):
        f.addRow(QPushButton("Camera settings... (EMCCD parameters)", clicked=self.cam_panel.open_))

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
        p = self.mag_pos.value()
        self._call(lambda: api.magnet.move_to(p).wait(60), f"magnet -> {p:.3f} mm")

    def _set_force(self):
        f = self.force_pn.value()
        self._call(lambda: api.magnet.set_force(f).wait(60), f"force -> {f:.2f} pN")

    def _rotate(self):
        n = self.rotor_turns.value()
        self._call(lambda: api.rotor.rotate(n).wait(60), f"rotor {n:+.1f} turns")

    def _move_focus(self):
        z = self.focus_um.value()
        self._call(lambda: api.focus.move_to(z).wait(30), f"focus -> {z:.2f} um")

    # ------------------------------------------------------------------ beads
    def _browse_cal(self):
        p, _ = QFileDialog.getOpenFileName(self, "Calibration (.cal) file", self.ed_fixture.text())
        if p:
            self.ed_cal.setText(p)
            self._load_cal_list()

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
        self.beads_info.setText(f"{len(cal['xy'])} beads, {cal['n_slices']} slices x {cal['z_step'] * 1000:.0f} nm, "
                                f"{cal['date']}")

    def _select_beads(self):
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
        self._call(lambda: api.beads.select(ids, cal_path=path), "select beads", done)

    def _rebuild_chips(self):
        while self.bead_chips.count():
            w = self.bead_chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.chips = {}
        for k, i in enumerate(self.bead_ids):
            c = QCheckBox(f"b{i}")
            c.setChecked(True)
            c.setStyleSheet(f"color:{COLORS[k % len(COLORS)]}")
            self.bead_chips.addWidget(c)
            self.chips[i] = c
        self.plot.clear()
        self.plot.addLegend(offset=(10, 10))
        self.curves = {}

    def _on_view_click(self, ev):
        """Pick beads on the JAI image (owner 2026-10-30: tracking before the TIRF set-up): left click adds a bead
        at the click, right click removes the nearest pick; the picks are what the z scan calibrates."""
        if not self.vb.sceneBoundingRect().contains(ev.scenePos()) or self.bead_ids:
            return
        pt = self.vb.mapSceneToView(ev.scenePos())
        x, y = float(pt.x()), float(pt.y())
        if ev.button() == Qt.RightButton:
            if self.picks:
                k = min(range(len(self.picks)), key=lambda i: (self.picks[i][0] - x) ** 2 + (self.picks[i][1] - y) ** 2)
                if abs(self.picks[k][0] - x) < 40 and abs(self.picks[k][1] - y) < 40:
                    del self.picks[k]
        elif ev.button() == Qt.LeftButton:
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

    def _clear_picks(self):
        self.picks = []
        self._draw_picks()

    def _draw_boxes(self, xy, good):
        for b in self.boxes:
            self.vb.removeItem(b)
        self.boxes = []
        h = 36
        for k, ((x, y), g) in enumerate(zip(xy, good)):
            if x < 0:
                continue
            pen = pg.mkPen(COLORS[k % len(COLORS)] if g else "#9CA3AF", width=2)
            r = pg.QtWidgets.QGraphicsRectItem(x - h, y - h, 2 * h, 2 * h)
            r.setPen(pen)
            self.vb.addItem(r)
            t = pg.TextItem(f"b{self.bead_ids[k] if k < len(self.bead_ids) else k + 1}", color=pen.color())
            t.setPos(x - h, y - h - 18)
            self.vb.addItem(t)
            self.boxes += [r, t]

    # ------------------------------------------------------------------ calibration
    def _run_zscan(self):
        beads = api.beads.selected()
        if not self.picks and beads is None:
            self._fail("z scan", "pick beads on the image or select beads first (their positions are scanned)")
            return
        if not api.acq.running():
            self._fail("z scan", "start acquisition first (frames come from the display)")
            return
        path = Path(self.cal_out.text())
        path.parent.mkdir(parents=True, exist_ok=True)
        slices, step, avg, cross = (self.cal_slices.value(), self.cal_step.value(), self.cal_avg.value(),
                                    self.cal_cross.value())
        xy = np.array(self.picks, dtype=np.float64) if self.picks else beads.xy0.copy()
        self.cal_status.setText("running...")

        def job():
            return zscan.run(path, xy, slices, step, avg, cross,
                             progress=lambda i, n: self.cal_status.setText(f"slice {i} / {n}"))

        def done(cal):
            self.cal_status.setText(f"done: {len(cal['xy'])} beads, {slices} slices x {step:.0f} nm -> {path}")
            self.ed_cal.setText(str(path))
            self._load_cal_list()
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
            self._call(api.acq.stop, "stop acquisition", lambda _: self.btn_live.setText("Start acquisition"))
            return
        folder, name = Path(self.ed_out.text()), self.ed_name.text().strip() or None
        folder.mkdir(parents=True, exist_ok=True)
        zm, gpu, roles = self.z_method.currentText(), self.gpu.isChecked(), dict(self.roles)
        self.history.clear()
        self.t0 = time.time()

        def done(st):
            self.btn_live.setText("Stop acquisition")
            self.ed_h5.setText(str(folder / f"{name}.h5") if name else "")
            self.ed_name.setText(time.strftime("run_%Y%m%d_%H%M%S"))
        self._call(lambda: api.acq.start(record=False, name=name, folder=folder, roles=roles, z_method=zm, gpu=gpu),
                   "start acquisition", done)

    def _toggle_rec(self):
        on = self.btn_rec.isChecked()
        self._call(lambda: api.acq.set_recording(on), "recording on" if on else "recording off",
                   lambda _: self.btn_rec.setText("* Recording" if on else "Record"))

    def _toggle_display(self):
        self.display_on = not self.display_on
        self.btn_display.setText("Pause display" if self.display_on else "Resume display")

    def _estop(self):
        with events.as_caller("gui"):
            estop.engage("GUI STOP button")
        self.statusBar().showMessage("EMERGENCY STOP engaged: moves are void until Acknowledge", 0)

    def _estop_clear(self):
        with events.as_caller("gui"):
            estop.clear()
        self.statusBar().showMessage("emergency stop released", 5000)

    def _mark(self):
        text = self.mark_text.text()
        self._call(lambda: api.acq.mark(text), f"mark '{text}'")

    # ------------------------------------------------------------------ protocol
    def _load_protocol(self):
        p, _ = QFileDialog.getOpenFileName(self, "Protocol", self.ed_out.text(), "Protocol (*.mtprot);;All (*)")
        if p:
            self.prot_edit.setPlainText(Path(p).read_text(encoding="utf-8"))

    def _save_protocol(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save protocol as", self.ed_out.text(), "Protocol (*.mtprot)")
        if p:
            Path(p).write_text(self.prot_edit.toPlainText(), encoding="utf-8")

    def _check_protocol(self):
        text = self.prot_edit.toPlainText()

        def job():
            rep = api.protocol.check(api.protocol.load(text), devices=True)
            return rep
        self._call(job, "check", lambda rep: self.prot_status.setText(
            ("OK" if rep["ok"] else "ERRORS") + (f"; coerced {len(rep['coerced'])}" if rep.get("coerced") else "")
            + ("\n" + "\n".join(str(e) for e in rep["errors"]) if rep.get("errors") else "")))

    def _run_protocol(self):
        st = api.protocol.status()
        if st["state"] == "paused":
            self._call(api.protocol.resume, "resume")
            return
        text = self.prot_edit.toPlainText()
        self._call(lambda: api.protocol.run(api.protocol.load(text)), "run protocol")

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

    def _browse_h5(self):
        p, _ = QFileDialog.getOpenFileName(self, "Run file", self.ed_out.text(), "HDF5 (*.h5)")
        if p:
            self.ed_h5.setText(p)

    def _export(self, kind):
        h5 = self.ed_h5.text()
        self._call(lambda: api.data.export(kind, h5), f"export .{kind}",
                   lambda paths: self.save_info.setPlainText(f"exported .{kind}:\n" + "\n".join(map(str, paths))))

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
            snap = api.acq.display() if api.acq.running() else None
        except api.NotReady:
            snap = None
        self._em_tick()
        if snap is None:
            return
        res = snap.result
        if self.display_on:
            self.img_item.setImage(snap.image, autoLevels=False, levels=(0, 255))
            if res is not None and res.xyz is not None:
                self._draw_boxes(res.xyz[:, :2], res.good)
            r = snap.record
            self.cam_label.setText(f"JAI frame {r.buffer_number}  seg {r.segment}  t {r.t_camera_s:.3f} s  "
                                   f"{r.rate_Hz:.1f} Hz  {'REC' if r.recording else ''}")
        if res is not None and res.xyz is not None and getattr(self, "_last_seq", None) != snap.seq:
            self._last_seq = snap.seq
            self.history.append((time.time() - self.t0, self._mag, self._force, res.xyz.copy()))
            self._update_plot()

    _mag = _force = float("nan")

    def _slow_tick(self):
        """2 Hz: motor read-backs and the status line (device calls, cheap on the simulator)."""
        try:
            st = api.devices.status()
        except Exception:  # noqa: BLE001
            st = {}
        if st and st.get("magnet", {}).get("state") == "connected":
            try:
                self._mag = api.magnet.position()
                lf = api.magnet.live_force(self._mag)          # None until the force calibration is ready
                self._force = lf["force_pN"] if lf else float("nan")
            except Exception as e:  # noqa: BLE001
                self._mag = self._force = float("nan")
                self.readback.setText(f"magnet read: {type(e).__name__}: {e}")
        if st and st.get("emccd", {}).get("state") == "connected" and not self._workers:
            try:
                e = api.emccd.settings()
                self.em_readback.setText(f"emccd: {e['exposure_ms']:.3f} ms, {e['rate_Hz']:.3f} Hz, gain mode "
                                         f"{e['em_gain_mode']}, gain {e['em_gain']}, set {e['temperature_C']} C, "
                                         f"sensor {e['sensor_temperature_C']} C ({e['cooler']})")
            except Exception as ex:  # noqa: BLE001
                self.em_readback.setText(f"emccd read: {type(ex).__name__}: {ex}")
        parts = []
        if api.acq.running():
            a = api.acq.status()
            parts.append(f"acq: {a.get('frames_received', 0)} frames, {a.get('fps_measured', a.get('fps', 0)) or 0:.1f} fps"
                         f"{', REC' if a.get('recording') else ''}")
        else:
            parts.append("acq: stopped")
        try:
            fc = api.magnet.force_calibration()
            parts.append(f"magnet {self._mag:.3f} mm = {self._force:.2f} pN" if fc["ready"] else
                         f"magnet {self._mag:.3f} mm (force: set the touch position in Setup)")
        except Exception:  # noqa: BLE001
            parts.append("magnet: not connected")
        p = api.protocol.status()
        parts.append(f"protocol: {p['state']}" + (f" ({p['reason']})" if p.get("reason") else ""))
        self.btn_run.setText("Resume" if p["state"] == "paused" else "Start")
        if p["state"] != "idle":
            self.prot_status.setText(f"{p['state']}" + (f": {p['reason']}" if p.get("reason") else ""))
        if estop.active():
            parts.append(f"E-STOP ENGAGED ({estop.reason()})")
        self.statusBar().showMessage("   |   ".join(parts))

    def _update_plot(self):
        if not self.history or not self.bead_ids:
            return
        kx, ky = self.ax_x.currentData(), self.ax_y.currentData()
        h = list(self.history)
        if self.follow.isChecked() and kx == "t":
            tmax = h[-1][0]
            h = [r for r in h if r[0] >= tmax - 30]
        t = np.array([r[0] for r in h])
        mag = np.array([r[1] for r in h])
        force = np.array([r[2] for r in h])
        xyz = np.array([r[3] for r in h])          # (n, nb, 3)
        base = {"t": t, "mag": mag, "force": force}
        xs = base[kx]
        self.plot.setLabel("bottom", AXES[kx])
        self.plot.setLabel("left", AXES[ky])
        if ky in base:
            ys = {None: base[ky]}
        else:
            col = {"x": 0, "y": 1, "z": 2}[ky]
            ys = {i: xyz[:, k, col] for k, i in enumerate(self.bead_ids) if self.chips.get(i) and
                  self.chips[i].isChecked()}
        for key in list(self.curves):
            if key not in ys:
                self.plot.removeItem(self.curves.pop(key))
        for key, y in ys.items():
            if key not in self.curves:
                k = self.bead_ids.index(key) if key is not None else 0
                self.curves[key] = self.plot.plot(pen=pg.mkPen(COLORS[k % len(COLORS)], width=1.5),
                                                  name=f"b{key}" if key is not None else AXES[ky])
            y = np.where(y == -1.0, np.nan, y)
            self.curves[key].setData(xs, y, connect="finite")
        if self.auto_scale.isChecked():
            self.plot.enableAutoRange()

    # ------------------------------------------------------------------ events
    def _on_event(self, ev):
        kind = getattr(ev, "kind", "?")
        if kind == "motor_reading":
            return
        extra = {k: v for k, v in vars(ev).items() if k not in ("t", "kind", "caller", "event_id") and v not in (None, {})}
        self.events_list.addItem(f"{time.strftime('%H:%M:%S', time.localtime(ev.t))}  {kind}  "
                                 f"{str(extra)[:160]}")
        if self.events_list.count() > 500:
            self.events_list.takeItem(0)
        self.events_list.scrollToBottom()
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
