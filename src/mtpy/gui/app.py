"""Main window (docs/mockups/2026-10-23-main-window, requirements U1-U6, U8, U13, U15, U17-U21, U30): one screen,
step bar, camera view with the bead boxes, any-axis live graphs, status bar and the emergency stop. Every device
action is an `mtpy.api` call made as caller "gui"; long ones run on a worker thread. The window reads the display tap
(api.acq.display) on a 30 Hz timer and can never slow acquisition.
shortcut: the GUI shares the API's process (plan phase 8 says its own process); move it out if phase 6 shows the
camera thread losing frames while the window is dragged.
"""
import contextlib
import time
import traceback
from collections import deque
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtpy import api
from mtpy.api import estop, events
from mtpy.lvfiles import read_cal
from mtpy.track import Z_METHODS

from . import zscan

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


def _row(*widgets):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        h.addWidget(x)
    return w


class MainWindow(QMainWindow):
    event_in = Signal(object)

    def __init__(self, fixture, out, sim_dev=None):
        super().__init__()
        self.fixture, self.out, self.sim_dev = Path(fixture), Path(out), sim_dev
        self.pool = QThreadPool.globalInstance()
        self._workers = set()                          # alive until done / failed: the pool would delete them first
        self.history = deque(maxlen=20000)            # (t, mag, force, xyz (nb, 3))
        self.t0 = time.time()
        self.bead_ids, self.roles, self.cal_path = [], {}, None
        self.display_on = True
        self.setWindowTitle("MT Tracker (Python) - simulators" + ("  [SIM-DEV PROFILE]" if sim_dev else ""))
        self.resize(1500, 950)
        self._build()
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
        body.addWidget(self.panel, 0)
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
        self.view = pg.GraphicsLayoutWidget()
        vb = self.view.addViewBox(lockAspect=True, invertY=True)
        self.img_item = pg.ImageItem()
        vb.addItem(self.img_item)
        self.boxes = []
        self.vb = vb
        self.cam_label = pg.LabelItem("no frame", justify="left")
        self.view.addItem(self.cam_label, row=1, col=0)
        return self.view

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
        self.ed_fixture = QLineEdit(str(self.fixture))
        f.addRow("Simulator fixture", _row(self.ed_fixture, QPushButton("Browse...", clicked=self._browse_fixture)))
        f.addRow(_row(QPushButton("Connect (sim)", clicked=self._connect),
                      QPushButton("Disconnect", clicked=self._disconnect),
                      QPushButton("Run self-check", clicked=self._self_check)))
        self.dev_table = QTableWidget(0, 3)
        self.dev_table.setHorizontalHeaderLabels(["Device", "State", "Last error / detail"])
        self.dev_table.horizontalHeader().setStretchLastSection(True)
        self.dev_table.setMinimumHeight(180)
        f.addRow(self.dev_table)
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
        f.addRow(g)
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
        self.touch_mm = _spin(0.0, 60.0, 0.1, 40.0, 2, " mm")
        g3f.addRow("Magnet position when touching the glass", _row(self.touch_mm, QPushButton(
            "Set", clicked=lambda: self._call(lambda: api.magnet.set_touch_position(self.touch_mm.value()),
                                              "touch position set"))))
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
        self.mag_pos = _spin(0.0, 39.0, 0.1, 0.0, 3, " mm")
        self.mag_slider = QSlider(Qt.Horizontal)
        self.mag_slider.setRange(0, 390)
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
        self.ed_cal = QLineEdit("")
        f.addRow(".cal file", _row(self.ed_cal, QPushButton("Browse...", clicked=self._browse_cal),
                                   QPushButton("Load list", clicked=self._load_cal_list)))
        self.bead_list = QListWidget()
        self.bead_list.setMinimumHeight(220)
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
        preset = {"backend": "sim"}
        fx = Path(self.ed_fixture.text())
        if fx.is_dir():
            preset["fixture"] = str(fx)
            cals = sorted(fx.glob("cal*"))
            if cals and not self.ed_cal.text():
                self.ed_cal.setText(str(cals[0]))
        self._call(lambda: (estop.clear(), api.devices.connect(preset))[1], "connect", self._show_devices)

    def _disconnect(self):
        self._call(api.devices.disconnect, "disconnect", lambda _: self._show_devices({}))

    def _self_check(self):
        def show(res):
            lines = [f"{d}: " + ", ".join(f"{s['step']} {'ok' if s['ok'] else 'FAIL'}" + (f" ({s['detail']})"
                     if s.get("detail") else "") for s in steps) for d, steps in res.items()]
            self._info("Self-check", "\n".join(lines))
        self._call(api.devices.self_check, "self-check", show)

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
        self._call(lambda: api.camera.apply_preset(preset, confirm=True), "camera preset",
                   lambda r: self.readback.setText(f"camera: {r}"))

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
        if beads is None:
            self._fail("z scan", "select beads first (their positions are scanned)")
            return
        if not api.acq.running():
            self._fail("z scan", "start acquisition first (frames come from the display)")
            return
        path = Path(self.cal_out.text())
        path.parent.mkdir(parents=True, exist_ok=True)
        slices, step, avg, cross = (self.cal_slices.value(), self.cal_step.value(), self.cal_avg.value(),
                                    self.cal_cross.value())
        xy = beads.xy0.copy()
        self.cal_status.setText("running...")

        def job():
            return zscan.run(path, xy, slices, step, avg, cross,
                             progress=lambda i, n: self.cal_status.setText(f"slice {i} / {n}"))

        def done(cal):
            self.cal_status.setText(f"done: {len(cal['xy'])} beads, {slices} slices x {step:.0f} nm -> {path}")
            self.ed_cal.setText(str(path))
            self._load_cal_list()
        self._call(job, "z scan", done)

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
        if snap is None:
            return
        res = snap.result
        if self.display_on:
            self.img_item.setImage(snap.image, autoLevels=False, levels=(0, 255))
            if res is not None and res.xyz is not None:
                self._draw_boxes(res.xyz[:, :2], res.good)
            r = snap.record
            self.cam_label.setText(f"frame {r.buffer_number}  seg {r.segment}  t {r.t_camera_s:.3f} s  "
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
            parts.append("E-STOP ENGAGED")
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
        self.timer.stop()
        self.slow.stop()
        with contextlib.suppress(Exception):
            self._unsub()
        try:
            with events.as_caller("gui"):
                if api.protocol.running():
                    api.protocol.stop()
                    api.protocol.wait(10)
                if api.acq.running():
                    api.acq.stop()
                api.devices.disconnect()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        super().closeEvent(e)
