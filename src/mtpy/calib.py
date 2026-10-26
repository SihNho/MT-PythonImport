"""Calibration cluster from a `.cal` file: what `Load and prep N cal images.vi` hands the tracking kernel.

Ported from MT_LabVIEW's CUDA v3 loader (`cal_file.inc`, `make_win_*` in `mt_track.cu`, pinned in third_party/MANIFEST),
which was checked against LabVIEW's own clusters. Per bead the `.cal` stores (LOW, HIGH, forget): the band-pass range in
frequency bins of the mirrored profile and the forget radius in pixels. Both can be overridden to compare settings.
"""
import numpy as np

# Initial values offered for a new calibration at 50x (decision 0022): forget removes the INNER radii, and at
# 203 nm / px the first bright ring sits at 15-16 px, so forget 10 keeps it. The user still picks them per bead.
DEFAULT_LOW, DEFAULT_HIGH, DEFAULT_FORGET = 0, 40, 10


def windows(cross):
    """`make both cosine bandpass.vi`: the real-space cosine window (XY profiles) and the Hilbert band-pass (XY spectra)."""
    i = np.arange(cross)
    half = cross // 2
    win_rs = 0.5 * (1 - np.cos(2 * np.pi * i / (cross - 1)))
    win_h = np.where(i <= half, 0.5 * (1 - np.cos(2 * np.pi * (i + half) / (2 * half))), 0.0)
    return win_rs, win_h


def cosband(low, high, cross):
    """`proc cal image-make bandpass.vi`: a raised-cosine band over bins LOW..HIGH, zero elsewhere."""
    i = np.arange(cross)
    return np.where((i >= low) & (i <= high), 0.5 * (1 - np.cos(2 * np.pi * (i - low) / (high - low))), 0.0)


def prep_bead(stack, low, high, forget, z_step, cross):
    """`prep cal image.vi` for one bead. stack: (S, L) mirrored radial profiles, L = cross - 1."""
    half = cross // 2
    band = cosband(low, high, cross)
    L = stack.shape[1]
    cork = np.fft.ifft(np.fft.fft(stack, axis=1) * band[:L], axis=1)[:, half - 1 + forget:]
    return {"forget_radius": forget, "z_step": z_step, "cosband": band, "ampl": np.abs(cork), "cork": cork,
            "real": cork.real.copy()}


def clusters(cal, low=None, high=None, forget=None):
    """One calibration cluster per bead from `lvfiles.read_cal` output. low / high / forget: a number for every bead or
    a per-bead sequence; None keeps the value stored in the file."""
    cross = cal["stack"].shape[2] + 1
    n = len(cal["stack"])

    def pick(v, col):
        return cal["bead_i32"][:, col] if v is None else np.broadcast_to(v, n)

    lo, hi, fg = pick(low, 0), pick(high, 1), pick(forget, 2)
    return [prep_bead(cal["stack"][b], int(lo[b]), int(hi[b]), int(fg[b]), cal["z_step"], cross) for b in range(n)]
