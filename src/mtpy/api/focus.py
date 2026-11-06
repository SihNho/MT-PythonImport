"""The focus z (ASI Tiger Z), in um. Focus moves invalidate nothing but are logged (U35).

    api.focus.move_to(3.5).wait(timeout_s=5)     # -> z read back, um
"""
import threading
import time

from . import events
from .devices import _move, service
from .errors import MtpyError, NotReady


def move_to(z_um):
    """Move the focus to z_um and return a Motion.

    Safety: z_um inside the profile's `focus_z_um` window around the session-start position (kept by the device
    layer). The shipped profile v1 has no focus window yet, so every focus move is refused until a rig-admin sets
    one. Example: `api.focus.move_to(3.5).wait(5)`.
    """
    svc = service("focus")
    dev = svc.require()
    return _move("focus", "focus_z_um", z_um, dev.position, origin=svc.origin)


def position():
    """The focus z read back, um. Example: `api.focus.position()`."""
    svc = service("focus")
    return svc.call(svc.require().position, what="WHERE Z")


def speed():
    """The focus drive's speed read back (mm/s on the ASI Tiger)."""
    svc = service("focus")
    return svc.call(svc.require().speed, what="S Z?")


def set_speed(mm_s):
    """Set the focus drive's speed (mm/s); the device refuses faster than the speed it opened with and restores that
    speed at close. Owner 2026-11-01: the bench compares the current speed with 1/10 of it. Returns the read-back."""
    if not (isinstance(mm_s, (int, float)) and not isinstance(mm_s, bool) and mm_s > 0):
        raise ValueError(f"focus speed {mm_s!r} must be a positive number (mm/s)")
    svc = service("focus")
    got = svc.call(svc.require().set_speed, mm_s, what=f"S Z={mm_s}")
    events.log("setting", device="focus", speed_mm_s=mm_s, readback=got)
    return got


# --- autofocus (spec F4.06; owner 2026-11-06: "autofocus through the piezo stage is not built - fix it") -------------
AUTOFOCUS_PERIOD_S = 0.3        # LabVIEW fires every 25 frames (~3.6 /s at 90 Hz); here on its own thread (RULES 6)
AUTOFOCUS_MAX_STEP_UM = 0.2     # LabVIEW's +-0.2 clamp per firing (units open, Q4.06: taken as um)
AUTOFOCUS_DEAD_UM = 0.01        # below this error nothing is sent (LabVIEW had none; spares the serial line)
_af = None


class _AutoFocus:
    """Hold the reference bead's tracked z at the LUT's middle by moving the focus, as the LabVIEW program (F4.06:
    move = clamp(slice index - n_slices / 2, +-0.2) relative). Runs on its own thread: each period it takes the
    display tap's newest result (never the frame path), and sends ONE relative focus move through api.focus.move_to
    (the profile window and the e-stop apply as to a manual move). A lost bead (-1) or a stale frame sends nothing.
    The sign follows the z scan's direction (api.zscan.SCAN_DIR): slice s = focus start + SCAN_DIR * s * step, so a
    bead reading above the middle means the focus is SCAN_DIR-wards of where it should be. Rig 2026-11-06 18:03:
    with the upward scan and SIGN -1 bead 1 was held at 3.00 +- 0.03 um (the log's autofocus_move lines), so the
    derivation holds; the downward scan (Request1) flips it to +1."""

    SIGN = None               # set per instance: -(the scan direction of the .cal in use)

    def __init__(self, bead_id, z_center_um, period_s, max_step_um, dead_um, sign=None):
        from . import zscan
        self.SIGN = float(-zscan.SCAN_DIR if sign is None else sign)
        self.bead_id, self.z_center_um = int(bead_id), float(z_center_um)
        self.period_s, self.max_step_um, self.dead_um = float(period_s), float(max_step_um), float(dead_um)
        self.moves, self.last, self.error = 0, None, None
        self._seq = None
        self._stop = threading.Event()
        self._thread = None

    def once(self):
        """One correction, if the newest tracked frame is new and the bead is found. Returns the move sent (um) or
        None."""
        from . import acq as _acq
        snap = _acq.display()
        if snap is None or snap.result is None or snap.result.xyz is None or snap.seq == self._seq:
            return None
        self._seq = snap.seq
        ids = list(_acq._pipe.bead_ids) if _acq._pipe is not None else []
        if self.bead_id not in ids:
            return None
        z = float(snap.result.xyz[ids.index(self.bead_id), 2])
        if z == -1.0:                            # lost (the tracker reseeds it; F4.05)
            return None
        err = z - self.z_center_um
        if abs(err) < self.dead_um:
            return None
        step = max(-self.max_step_um, min(self.max_step_um, self.SIGN * err))
        z_now = position()
        m = move_to(z_now + step)
        m.wait(5.0)
        self.moves, self.last = self.moves + 1, time.time()
        events.log("autofocus_move", request={"quantity": "focus_z_um", "value": z_now + step}, bead=self.bead_id,
                   z_um=z, z_center_um=self.z_center_um, step_um=step, seq=snap.seq)
        return step

    def _loop(self):
        while not self._stop.wait(self.period_s):
            try:
                self.once()
            except MtpyError as e:               # refused / device error: reported in status, the thread goes on
                self.error = f"{type(e).__name__}: {e}"

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="autofocus", daemon=True)
        self._thread.start()

    def stop(self, timeout_s=6.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout_s)

    def status(self):
        return {"on": not self._stop.is_set(), "bead": self.bead_id, "z_center_um": self.z_center_um, "sign": self.SIGN,
                "moves": self.moves, "last": self.last, "error": self.error, "period_s": self.period_s,
                "max_step_um": self.max_step_um}


def autofocus(on, bead_id=None, z_center_um=None, period_s=AUTOFOCUS_PERIOD_S, max_step_um=AUTOFOCUS_MAX_STEP_UM,
              dead_um=AUTOFOCUS_DEAD_UM, scan_direction=None):
    """Switch the autofocus on (hold bead `bead_id`'s tracked z at `z_center_um` by moving the focus; z_center None =
    the middle of the selected beads' calibration, n_slices // 2 * z_step) or off. scan_direction: the direction
    the .cal in use was scanned in (+1 / -1; None = zscan.SCAN_DIR), the correction's sign is its opposite.
    Returns autofocus_status(). Example: `api.focus.autofocus(True, bead_id=1)`."""
    global _af
    if _af is not None:
        _af.stop()
        _af = None
    if on:
        from . import beads as _beads
        b = _beads.selected()
        if b is None:
            raise NotReady("no beads selected: the autofocus follows a tracked bead")
        if bead_id is None or bead_id not in b.ids:
            raise ValueError(f"bead_id must be one of the selected beads {list(b.ids)}; got {bead_id!r}")
        if z_center_um is None:
            from mtpy.lvfiles import read_cal
            cal = read_cal(b.source)
            z_center_um = (cal["n_slices"] // 2) * float(cal["z_step"])
        service("focus").require()
        _af = _AutoFocus(bead_id, z_center_um, period_s, max_step_um, dead_um,
                         None if scan_direction is None else -float(scan_direction))
        _af.start()
    events.log("autofocus", request={"on": bool(on)}, bead=bead_id, z_center_um=z_center_um)
    return autofocus_status()


def autofocus_status():
    """{"on", "bead", "z_center_um", "moves", "last", "error", ...}; {"on": False} when never switched on."""
    return {"on": False} if _af is None else _af.status()
