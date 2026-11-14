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
    """Set the focus drive's speed (mm/s); faster than the speed the device opened with is lowered to that speed
    (`coerced`), a very low speed is rounded by the controller (the read-back is returned); the device restores the
    opening speed at close. Owner 2026-11-01: the bench compares the current speed with 1/10 of it. Returns the read-back."""
    if not (isinstance(mm_s, (int, float)) and not isinstance(mm_s, bool) and mm_s > 0):
        raise ValueError(f"focus speed {mm_s!r} must be a positive number (mm/s)")
    svc = service("focus")
    cap = getattr(svc.require(), "speed0", None)
    if cap and mm_s > cap:                      # owner 2026-11-13: out of range is coerced, not refused
        events.log("coerced", request={"quantity": "focus_speed_mm_s", "value": mm_s}, applied=cap,
                   reason=f"the focus speed is at most the speed the session opened with ({cap} mm/s)")
        mm_s = cap
    got = svc.call(svc.require().set_speed, mm_s, what=f"S Z={mm_s}")
    events.log("setting", device="focus", speed_mm_s=mm_s, readback=got)
    return got


# --- autofocus (spec F4.06; owner 2026-11-06: "autofocus through the piezo stage is not built - fix it") -------------
AUTOFOCUS_PERIOD_S = 0.3        # LabVIEW fires every 25 frames (~3.6 /s at 90 Hz); here on its own thread (RULES 6)
AUTOFOCUS_MAX_STEP_UM = 0.2     # LabVIEW's +-0.2 clamp per firing (units open, Q4.06: taken as um)
AUTOFOCUS_DEAD_UM = 0.01        # below this error nothing is sent (LabVIEW had none; spares the serial line)
AUTOFOCUS_TARGET_PCT = 30.0     # owner 2026-11-12: "초기화 값은 30% (패턴 큰 방향으로)"; it was the LUT's middle
_af = None
_target_pct = AUTOFOCUS_TARGET_PCT


def _target_z(cal, pct):
    """The reference bead's target z (um) at pct % of the LUT: 0 % = LUT index 0, the last slice scanned = the
    largest pattern for either sign of the step (api.zscan), 100 % = index n - 1, the scan's start."""
    return pct / 100.0 * (cal["n_slices"] - 1) * float(cal["z_step"])


def set_autofocus_target(percent):
    """Where the autofocus holds the reference bead, in percent of the LUT (0 = index 0, the largest pattern;
    100 = the scan's start; default 30). Takes effect at once when the autofocus is on. Returns autofocus_status().
    Example: `api.focus.set_autofocus_target(30)`."""
    global _target_pct
    if not (isinstance(percent, (int, float)) and not isinstance(percent, bool) and 0 <= percent <= 100):
        raise ValueError(f"autofocus target {percent!r} must be a number in 0..100 (percent of the LUT)")
    _target_pct = float(percent)
    if _af is not None and _af.cal is not None:
        _af.z_center_um = _target_z(_af.cal, _target_pct)
    events.log("autofocus_target", request={"percent": _target_pct}, z_center_um=None if _af is None else _af.z_center_um)
    return autofocus_status()


class _AutoFocus:
    """Hold the reference bead's tracked z at the LUT's middle by moving the focus, as the LabVIEW program (F4.06:
    move = clamp(slice index - n_slices / 2, +-0.2) relative). Runs on its own thread: each period it takes the
    display tap's newest result (never the frame path), and sends ONE relative focus move through api.focus.move_to
    (the profile window and the e-stop apply as to a manual move). A lost bead (-1) or a stale frame sends nothing.
    The sign: the LUT's z rises with the sample (api.zscan stores the slices in sample order, LUT index k = the
    sample k x step above index 0), so a bead reading above the middle is too high and the sample must go DOWN:
    SIGN = -1. Rig 2026-11-06 18:03: bead 1 was held at 3.00 +- 0.03 um with SIGN -1 and a LUT whose z rose with
    the sample (the log's autofocus_move lines), so the derivation holds; devices/asi.py Z_SIGN cancels between
    the scan and the correction."""

    SIGN = -1.0

    def __init__(self, bead_id, z_center_um, period_s, max_step_um, dead_um):
        self.bead_id, self.z_center_um = int(bead_id), float(z_center_um)
        self.period_s, self.max_step_um, self.dead_um = float(period_s), float(max_step_um), float(dead_um)
        self.moves, self.last, self.error = 0, None, None
        self.cal = None                          # {n_slices, z_step} when the target is a percent (set_autofocus_target)
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
        row = snap.result.xyz[ids.index(self.bead_id)]
        if row[0] == -1.0 and row[2] == -1.0:    # lost, the kernel's (-1, -1, -1) row (the tracker reseeds it; F4.05)
            return None
        z = float(row[2])
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
                "target_percent": _target_pct if self.cal is not None else None,
                "moves": self.moves, "last": self.last, "error": self.error, "period_s": self.period_s,
                "max_step_um": self.max_step_um}


def autofocus(on, bead_id=None, z_center_um=None, period_s=AUTOFOCUS_PERIOD_S, max_step_um=AUTOFOCUS_MAX_STEP_UM,
              dead_um=AUTOFOCUS_DEAD_UM):
    """Switch the autofocus on (hold bead `bead_id`'s tracked z at `z_center_um` by moving the focus) or off.
    bead_id None = the first selected bead with the role reference (the roles of api.acq.start / retarget);
    z_center None = the target set by set_autofocus_target (percent of the LUT, default 30). Returns
    autofocus_status(). Example: `api.focus.autofocus(True, bead_id=1)`."""
    global _af
    if _af is not None:
        _af.stop()
        _af = None
    if on:
        from . import beads as _beads
        b = _beads.selected()
        if b is None:
            raise NotReady("no beads selected: the autofocus follows a tracked bead")
        if bead_id is None:                      # a protocol's `autofocus on`: the reference bead being tracked
            from . import acq as _acq
            refs = [i for i in b.ids if _acq._roles.get(i, _acq._roles.get(str(i))) == "reference"]
            if not refs:
                raise NotReady("the autofocus needs a reference bead: none of the tracked beads has that role")
            bead_id = refs[0]
        if bead_id not in b.ids:
            raise ValueError(f"bead_id must be one of the selected beads {list(b.ids)}; got {bead_id!r}")
        cal = None
        if z_center_um is None:
            from mtpy.lvfiles import read_cal
            c = read_cal(b.source)
            cal = {"n_slices": c["n_slices"], "z_step": float(c["z_step"])}
            z_center_um = _target_z(cal, _target_pct)
        service("focus").require()
        _af = _AutoFocus(bead_id, z_center_um, period_s, max_step_um, dead_um)
        _af.cal = cal
        _af.start()
    events.log("autofocus", request={"on": bool(on)}, bead=bead_id, z_center_um=z_center_um)
    return autofocus_status()


def autofocus_status():
    """{"on", "bead", "z_center_um", "moves", "last", "error", ...}; {"on": False} when never switched on."""
    return {"on": False, "target_percent": _target_pct} if _af is None else _af.status()
