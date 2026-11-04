"""The calibration viewer (owner 2026-11-04 / 05: the LabVIEW program shows the bead's PSF and the processing result,
and the band-pass and the forget radius are chosen there; here nothing was visible). For one bead of a .cal:

- the raw stack as an image, slice (z) against radius: the bead's PSF through focus (`cal["stack"][b]`);
- the band-passed stack after the forget radius, Re of the corkscrew (`calib.prep_bead(...)["real"]`): what a live
  profile is matched against;
- the self-fit: every slice's own profile put through the z method against this LUT (`track.z_phase`), z found
  against z scanned, and the residual in nm - how linear and how clean the LUT is with these values.

LOW / HIGH are the band-pass bins (a raised cosine over FFT bins LOW..HIGH of the mirrored profile, `calib.cosband`),
the forget radius the inner pixels dropped from the profile. "Save to .cal" writes them into the file's bead_i32,
the one place the tracker reads them from (decision 0008); the beads must be selected again to track with them.
"""
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from mtpy import calib, track
from mtpy.lvfiles import read_cal, write_cal


def self_fit(cal, b, low, high, forget):
    """(z_scanned_um, z_found_um) of every slice of bead b (0-based) with the band LOW..HIGH and the forget radius:
    the slice's own profile through the z method against the LUT built with these values. nan where the method
    fails (the stack's edges)."""
    stack = cal["stack"][b]
    cross = stack.shape[1] + 1
    half = cross // 2
    cl = calib.prep_bead(stack, low, high, forget, cal["z_step"], cross)
    found = np.full(len(stack), np.nan)
    for s, mir in enumerate(stack):
        rad = mir[half - 1:]                    # the mirrored profile's right half, r = 0 at its first bin
        try:
            zi, _idx = track.z_phase(rad, half, cl, track.DEFAULT)
            found[s] = zi * cal["z_step"]
        except (ValueError, IndexError, FloatingPointError):
            pass
    return np.arange(len(stack)) * cal["z_step"], found


class CalView(QWidget):
    """load(path) shows the file; the spins re-process the shown bead live; Save writes them to the file."""

    def __init__(self, on_saved=None):
        super().__init__()
        self.cal, self.path, self.on_saved = None, None, on_saved
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        f = QFormLayout()
        self.bead = QComboBox()
        self.bead.currentIndexChanged.connect(lambda _i: self._show_bead())
        f.addRow("Bead", self.bead)
        self.low, self.high, self.forget = QSpinBox(), QSpinBox(), QSpinBox()
        for sp, hi, v in ((self.low, 200, calib.DEFAULT_LOW), (self.high, 200, calib.DEFAULT_HIGH),
                          (self.forget, 60, calib.DEFAULT_FORGET)):
            sp.setRange(0, hi)
            sp.setValue(v)
            sp.valueChanged.connect(lambda _v: self.show())
        f.addRow("Band-pass LOW (bin)", self.low)
        f.addRow("Band-pass HIGH (bin)", self.high)
        f.addRow("Forget radius (px)", self.forget)
        self.all_beads = QCheckBox("save these values for every bead of the file")
        f.addRow(self.all_beads)
        self.btn_save = QPushButton("Save to .cal (then select the beads again to track with them)", clicked=self.save)
        f.addRow(self.btn_save)
        self.info = QLabel("no .cal loaded: run a z scan or Load list (Beads)")
        self.info.setWordWrap(True)
        f.addRow(self.info)
        lay.addLayout(f)
        g = pg.GraphicsLayoutWidget()
        g.setMinimumHeight(560)
        self.p_psf = g.addPlot(row=0, col=0, title="PSF: radial profile stack (x radius px, y slice)")
        self.i_psf = pg.ImageItem()
        self.p_psf.addItem(self.i_psf)
        self.p_band = g.addPlot(row=1, col=0, title="band-passed, after the forget radius (what z is matched against)")
        self.i_band = pg.ImageItem()
        self.p_band.addItem(self.i_band)
        self.p_fit = g.addPlot(row=2, col=0, title="self-fit: z found (um) and residual (nm) against z scanned (um)")
        self.p_fit.addLegend(offset=(10, 10))
        self.c_found = self.p_fit.plot(pen=pg.mkPen("#60A5FA", width=1.5), name="z found (um)")
        self.c_ideal = self.p_fit.plot(pen=pg.mkPen("#9CA3AF", width=1, style=pg.QtCore.Qt.DashLine), name="ideal")
        self.c_res = self.p_fit.plot(pen=pg.mkPen("#F87171", width=1.5), name="residual (nm) / 100")
        lay.addWidget(g)

    def load(self, path):
        self.cal, self.path = read_cal(path), str(path)
        self.bead.blockSignals(True)
        self.bead.clear()
        for i in range(len(self.cal["stack"])):
            self.bead.addItem(f"bead {i + 1}", i)
        self.bead.blockSignals(False)
        self._show_bead()

    def _show_bead(self):
        """The file's own values of the chosen bead into the spins, then the pictures."""
        if self.cal is None or self.bead.currentIndex() < 0:
            return
        lo, hi, fg = (int(v) for v in self.cal["bead_i32"][self.bead.currentIndex()])
        for sp, v in ((self.low, lo), (self.high, hi), (self.forget, fg)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self.show()

    def values(self):
        return self.low.value(), self.high.value(), self.forget.value()

    def show(self):
        if self.cal is None or self.bead.currentIndex() < 0:
            return
        b = self.bead.currentIndex()
        low, high, forget = self.values()
        if high <= low:
            self.info.setText("HIGH must be above LOW")
            return
        stack = self.cal["stack"][b]
        cross = stack.shape[1] + 1
        self.i_psf.setImage(stack.T, autoLevels=True)
        self.i_band.setImage(calib.prep_bead(stack, low, high, forget, self.cal["z_step"], cross)["real"].T, autoLevels=True)
        z, found = self_fit(self.cal, b, low, high, forget)
        res_nm = (found - z) * 1000.0
        self.c_found.setData(z, found)
        self.c_ideal.setData(z, z)
        self.c_res.setData(z, res_nm / 100.0)
        mid = slice(len(z) // 4, max(len(z) // 4 + 1, 3 * len(z) // 4))
        ok = np.isfinite(res_nm[mid])
        stored = tuple(int(v) for v in self.cal["bead_i32"][b])
        self.info.setText(f"bead {b + 1}: {len(z)} slices x {self.cal['z_step'] * 1000:.0f} nm; in the file LOW {stored[0]} "
                          f"HIGH {stored[1]} forget {stored[2]}; shown LOW {low} HIGH {high} forget {forget}: self-fit "
                          f"residual over the middle half {np.nanmedian(np.abs(res_nm[mid])):.1f} nm median, "
                          f"{np.nanmax(np.abs(res_nm[mid])) if ok.any() else float('nan'):.1f} nm max")

    def save(self):
        if self.cal is None:
            return
        low, high, forget = self.values()
        if high <= low:
            self.info.setText("HIGH must be above LOW; nothing saved")
            return
        rows = range(len(self.cal["stack"])) if self.all_beads.isChecked() else [self.bead.currentIndex()]
        for b in rows:
            self.cal["bead_i32"][b] = (low, high, forget)
        write_cal(self.path, self.cal)
        self.info.setText(f"saved LOW {low} HIGH {high} forget {forget} for bead(s) {[b + 1 for b in rows]} to {self.path}; "
                          "select the beads again (Beads) to track with them")
        if self.on_saved:
            self.on_saved(self.path)
