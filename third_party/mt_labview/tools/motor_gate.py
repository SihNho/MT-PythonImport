"""motor_gate.py - THE ONE GATEWAY for any motion command to the PI magnet motor, the ASI stage or the rotor.

WHY IT EXISTS (user ruling, 2026-09-17, rig = 조립/assembled): motors are allowed while the rig is assembled
**only inside a safe envelope, and only if the envelope is really enforced by code**. A survey found ~65 files
under tools/ that can reach a motor with no choke point. This file is the choke point; `tools/hooks/guard_bash.py`
refuses the other routes.

REWORKED 2026-09-18 (user present at the rig, verbatim intent): **THE REAL LIMITS ARE NOW IN THE CONTROLLERS,
NOT IN THIS SCRIPT.** P2 measured both (docs/motor-limit-assurance-plan.md "P2 live findings"):
  * PI C-863.11: `SPA 1 0x15 <hi>` / `SPA 1 0x30 <lo>` set TMX/TMN; `MOV 1 40` past TMX 39 answers ERR 7 and the
    axis does not move. RAM only (lost at controller power-cycle) - **never WPA**.
  * ASI Tiger: `SL`/`SU` (ABSOLUTE mm) stop motion at the boundary, joystick and HOME included, and persist across
    power cycles - **never SS Z** (nothing of ours saves settings).
So the script-level numeric envelope (the old PI 0..39 test and the old ASI 1.0 mm radial test, with the fixed
reference point and the "fresh position read" it needed) is DELETED: a second, weaker copy of a limit that the
hardware now enforces was only a place for the two to disagree. What this file still enforces:
  1. RIG STATE from STATUS.md (`rig-state:`): 실험중 => refuse everything; unreadable => refuse (default-deny).
  2. COMMAND CLASS default-deny. Refused for good: every ASI home/origin/zero/save/reset command and every PI
     home/reference/define command - **because a controller limit is ABSOLUTE, so shifting the coordinate zero
     would move the fence without changing a number in this file**. Read-only queries pass.
     ROTOR (user 2026-10-19, "-5바퀴 에서 + 5바퀴", "기계 리턴은 펄스로 주는지라 각도로 환산해야함"): a RELATIVE
     envelope enforced by THIS script (docs/rotor-protocol.md "Envelope design" says why not the controller's own
     EEPROM soft limit yet): `--session start` reads the rotor POS (read-only) and records start_pos; a move is
     allowed only if start_pos - half_width <= target <= start_pos + half_width pulses (2500 = 5 turns at
     0.72 deg/pulse), relative targets from a FRESH POS read inside the same port open as the transmit
     (tools/motor_rotor_io.ps1). X axis only; speed <= rotor.max_speed; counter clear / home / EEPROM write /
     program / jog / reset refused (they would move or bypass the fence).
  3. THE SESSION CONTRACT. `--session start` writes the limits from tools/bench/motor_limits.json into both
     controllers and verifies them by readback; `--session end` releases them (PI 0..52, ASI +-500). `--execute`
     refuses unless a session file exists AND a FRESH readback of the controller limits, taken inside the same
     port open as the transmit and before it, matches the file within 0.001.
     MAGNET RETURN (Q2, user 2026-10-21 "Q2 동의함"): with a session open, `--session end` first sends `MOV 1 0`
     through the same send path as --execute (0 mm = the ceiling, the magnet farthest from the sample) while the
     limits are still set, and verifies POS within MAGNET_HOME_TOL_MM; not verified -> nothing is released and the
     session file is kept (the rig lock holder then keeps the lock). Also in the experiment state. The rotor is left
     where it is (not decided).
An abnormal exit therefore leaves the limits ON in the controllers, which is the safe direction.

UNITS - stated explicitly because getting this wrong is the whole risk:
  ASI  motion commands are in 0.1 um  =>  1.0 mm = 10 000 units, `M X=8000` is +0.8 mm.
       ASI SL/SU limits are in **mm, absolute**.
  PI   native unit = mm (M-126.PD1 through GCS `POS?`/`MOV`); SPA 0x15/0x30 are mm as well.
  rotor native unit = pulses, 0.72 deg/pulse (500 pulses = 1 turn); PAB/PIC/SPD arguments are signed DECIMAL,
       the POS reply is 8 HEX digits per axis, two's complement ('FFFFFFF6' = -10 pulses = -7.2 deg).

  py tools/motor_gate.py --session start | end
  py tools/motor_gate.py --device asi --command "M X=8000" [--dry-run | --execute]
  exit 0 = ALLOW/OK, 3 = REFUSE, 4 = usage error, 5 = transmit not implemented, else the sender's own code.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIMITS_PATH = os.path.join(ROOT, "tools", "bench", "motor_limits.json")
SESSION_PATH = os.path.join(ROOT, "tools", "bench", "motor_session.json")
LOG_PATH = os.path.join(ROOT, "tools", "bench", "motor_gate.log")
STATUS_PATH = os.path.join(ROOT, "STATUS.md")
PI_SENDER = os.path.join(HERE, "motor_send_pi.ps1")
ASI_IO = os.path.join(HERE, "motor_asi_io.ps1")
ROTOR_IO = os.path.join(HERE, "motor_rotor_io.ps1")

DEFAULT_TOL = 0.001
REF_ATTEMPTS = 3   # user 2026-09-23: reference + verify at session start, retried; refuse only after all attempts

PORTS = {"pi": ("COM3", 115200, "ASRL3::INSTR / alias PI"),
         "asi": ("COM4", 115200, "ASRL4::INSTR / alias ASI_Piezo"),
         "rotor": ("COM5", 9600, "ASRL5::INSTR / alias Rotor")}

# ---------------------------------------------------------------- command sets
# ASI: from archive/peer/2026-09-12-asi-tiger-readonly-commands.md. Bare-form queries only; any argument carrying
# '=' , '+' or '-' turns a "query" into a write (`BU Y=#`, `BU Z+` ...), which is the looks-like-a-query trap.
ASI_QUERIES = {"/", "STATUS", "W", "WHERE", "BU", "BUILD", "V", "VERSION", "RB", "RDSBYTE"}
ASI_ABS = {"M", "MOVE"}
ASI_REL = {"R", "MOVREL"}
# Named so the refusal says WHY, though default-deny would catch them anyway. A zero shift MOVES THE FENCE:
# SL/SU are absolute coordinates, so HOME/HERE/ZERO/AZERO/SETHOME would relocate the protected window.
ASI_ORIGIN = {"!": "HOME", "HOME": "HOME", "H": "HERE", "HERE": "HERE", "Z": "ZERO", "ZERO": "ZERO",
              "HM": "SETHOME", "SETHOME": "SETHOME", "AZ": "AZERO", "AZERO": "AZERO",
              "SP": "SAVEPOS", "SAVEPOS": "SAVEPOS", "SS": "SAVESET", "SAVESET": "SAVESET",
              "~": "RESET", "RESET": "RESET", "\\": "HALT", "HALT": "HALT",
              "MC": "MOTCTRL", "MOTCTRL": "MOTCTRL", "@": "SPIN", "SPIN": "SPIN",
              "MM": "MULTIMV", "MULTIMV": "MULTIMV", "VE": "VECTOR", "VECTOR": "VECTOR",
              "SN": "SCAN", "SCAN": "SCAN", "NR": "SCANR", "NV": "SCANV",
              "SL": "SETLOW limit", "SU": "SETUP limit"}   # SL/SU writes belong to --session only

# PI GCS (Mercury, M-126.PD1). Query list = the one already proven on this port by serial_roundtrip.ps1.
PI_QUERIES = {"POS?", "TMN?", "TMX?", "ERR?", "*IDN?", "VEL?", "SVO?", "ONT?", "HLP?", "RON?", "FRF?",
              "SPA?", "SAI?"}
PI_ABS = {"MOV"}
PI_REL = {"MVR"}
PI_HOME = {"GOH": "go to home", "FRF": "reference move", "FNL": "negative-limit move",
           "FPL": "positive-limit move", "DFH": "define home", "RON": "referencing mode",
           "POS": "define the current position - would SHIFT the coordinate zero under the absolute "
                  "controller limits (allowed only inside the session-start hook, which does not use it; the "
                  "axis is RON 0 with its position already defined - do not change it)",
           "SPA": "set a stage parameter, incl. the soft limits themselves (session hook only)",
           "WPA": "write parameters to non-volatile memory - NEVER (the controller limits are RAM by design)"}

# Autonics PMC-2HS serial commands (manual DRW170814AB ch. 8, pp. 67-78; docs/rotor-protocol.md). The rotor is the
# X axis of a TWO-axis controller; nothing is known about Y, so any Y component is refused.
# Read-only queries, with the exact argument form each one takes (None = no argument):
ROTOR_QUERIES = {"POS": None, "SPD": None, "VER": None, "SCI": None,
                 "ERD": r"^X$", "INR": r"^X$", "IDC": r"^X$",
                 "IHR": r"^X[0-9A-F]{1,2}$", "IXR": r"^X[0-9A-F]{1,2}$"}
ROTOR_ABS = {"PAB"}
ROTOR_REL = {"PIC"}
ROTOR_SPEED = {"SPD"}            # with an argument it is a WRITE of the drive speed (capped by rotor.max_speed)
# Named so the refusal says WHY (default-deny would catch them anyway). The envelope is measured in the controller's
# position counter, so anything that clears/redefines that counter or homes the axis MOVES THE FENCE.
ROTOR_FENCE = {"CLL": "clear the active position counter - shifts the coordinate the envelope is measured in",
               "CLR": "clear the actual position counter - shifts the coordinate the envelope is measured in",
               "HOM": "home search - drives to the home sensor, ignores the soft limit, may clear the counter",
               "OGE": "force-end a home search",
               "RST": "reset the motion-control IC (counter state not documented)",
               "IHS": "EEPROM write (2-byte parameters: mode bits incl. soft-limit enable, speed multiplier ...)",
               "IXS": "EEPROM write (4-byte parameters: soft limits, home offset, position data)",
               "PRG": "run a stored program - its moves are not bounded by this gate",
               "PST": "step a stored program", "PRS": "restart a stored program",
               "EDP": "force-end a program", "PSP": "pause a program/drive",
               "JOG": "continuous drive with no end point - cannot be bounded",
               "SSM": "select stored drive speed 1-4 - bypasses the speed cap",
               "OUT": "drive output bits",
               "STO": "stop - not transmittable through this gate (default-deny; a stop needs no envelope but the "
                      "gate implements only the bounded move path)"}

AXES = ("X", "Y", "Z")


class Decision(object):
    def __init__(self, allowed, reason, detail=None):
        self.allowed = bool(allowed)
        self.reason = reason
        self.detail = detail or {}

    def __repr__(self):
        return "<%s %s>" % ("ALLOW" if self.allowed else "REFUSE", self.reason)


# ---------------------------------------------------------------- rig state / files
def rig_state(status_text):
    """'disassembled' | 'assembled' | 'experiment' | 'unknown'.

    ONE machine-readable key, `rig-state: <value>`, is the source of truth - a substring search for 실험중 cannot
    work because the permission TABLE in STATUS.md contains that word on every rig state. A line that *starts* a
    STATUS banner with EXPERIMENT RUNNING still forces 'experiment': default-deny beats a stale key."""
    if re.search(r"(?m)^#+\s*\S*\s*EXPERIMENT RUNNING", status_text):
        return "experiment"
    m = re.search(r"(?m)^\s*(?:#\s*)?rig-state:\s*([^\s#]+)", status_text)
    if not m:
        return "unknown"
    v = m.group(1).strip().lower()
    if v in ("분해", "disassembled"):
        return "disassembled"
    if v in ("조립", "assembled"):
        return "assembled"
    if v in ("실험중", "experiment", "experiment-running"):
        return "experiment"
    return "unknown"


def read_status(path=None):
    try:
        with open(path or STATUS_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_limits(path=None):
    """The user-editable limit file. Returns None if missing/unreadable -> everything is refused."""
    try:
        with open(path or LIMITS_PATH, encoding="utf-8-sig") as f:
            lim = json.load(f)
    except (OSError, ValueError):
        return None
    try:
        float(lim["pi"]["lo_mm"]), float(lim["pi"]["hi_mm"]), float(lim["pi"]["release_hi_mm"])
        for k in ("sl", "su"):
            float(lim["asi"][k]["X"]), float(lim["asi"][k]["Y"])
        float(lim["asi"]["release"]["sl"]), float(lim["asi"]["release"]["su"])
    except (KeyError, TypeError, ValueError):
        return None
    if lim["asi"].get("mode", "absolute") not in ("absolute", "relative"):
        return None
    if lim["asi"].get("mode") == "relative":
        try:
            hw = lim["asi"]["half_width_mm"]
            if not (0 < float(hw["X"]) <= 5 and 0 < float(hw["Y"]) <= 5):
                return None
        except (KeyError, TypeError, ValueError):
            return None
    if "rotor" in lim and not rotor_block_ok(lim["rotor"]):
        return None
    lim.setdefault("tolerance", DEFAULT_TOL)
    return lim


ROTOR_DEG_PER_PULSE = 0.72        # measured 2026-09-14 (docs/rotor-sign-diagnosis.md:115): 500 pulses per turn
ROTOR_MAX_HALF_WIDTH = 2500       # user 2026-10-19: -5 .. +5 turns = +-2500 pulses; the file may narrow, never widen
ROTOR_MAX_SPEED = 100             # the main VI's 'Rot \nSpeed' default, sent unscaled by SetCommand.vi's SetSpeed


def rotor_block_ok(r):
    """The optional "rotor" block of motor_limits.json. Anything malformed -> the whole file is refused."""
    try:
        return (r.get("mode") == "relative"
                and type(r.get("half_width_pulses")) is int and 0 < r["half_width_pulses"] <= ROTOR_MAX_HALF_WIDTH
                and abs(float(r["deg_per_pulse"]) - ROTOR_DEG_PER_PULSE) < 1e-9
                and type(r.get("max_speed")) is int and 0 < r["max_speed"] <= ROTOR_MAX_SPEED)
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def rotor_hex_to_pulses(h):
    """One 8-hex-digit POS field -> signed pulses (two's complement, 32 bit). 'FFFFFFF6' -> -10. None if malformed:
    the manual (p. 70) and the 2026-09-14 hardware reads both give exactly 8 digits per axis."""
    if not re.match(r"^[0-9A-Fa-f]{8}$", h or ""):
        return None
    v = int(h, 16)
    return v - (1 << 32) if v & 0x80000000 else v


def parse_rotor_pos_reply(text):
    """'POS hhhhhhhh,hhhhhhhh' (2-axis PMC-2HS) or 'POS hhhhhhhh' -> X pulses (signed), or None."""
    m = re.search(r"POS\s+([0-9A-Fa-f]{8})(?:\s*,\s*[0-9A-Fa-f]{8})?\s*$", (text or "").strip())
    return rotor_hex_to_pulses(m.group(1)) if m else None


def parse_rotor_fresh(text):
    """The sender's 'FRESH RAW=<reply> POS=<int>' line -> pulses, ONLY if the gate's own parse of the raw reply
    agrees with the sender's number (the sign conversion is checked twice, in two languages). Last line wins."""
    ms = list(re.finditer(r"(?m)^FRESH RAW='([^']*)' POS=(-?\d+)\s*$", text or ""))
    if not ms:
        return None
    raw, pos = ms[-1].group(1), int(ms[-1].group(2))
    mine = parse_rotor_pos_reply(raw)
    return pos if mine is not None and mine == pos else None


def rotor_window_from_pos(limits, pos):
    hw = int(limits["rotor"]["half_width_pulses"])
    return {"mode": "relative", "center_pulses": int(pos), "lo_pulses": int(pos) - hw, "hi_pulses": int(pos) + hw,
            "half_width_pulses": hw, "deg_per_pulse": float(limits["rotor"]["deg_per_pulse"])}


def rotor_target_check(window, kind, value, fresh_pos=None):
    """(ok, target_pulses, message). kind 'abs' (PAB value) or 'rel' (PIC value, needs fresh_pos)."""
    if not window or window.get("mode") != "relative":
        return False, None, "no rotor window recorded by an open session"
    lo, hi = int(window["lo_pulses"]), int(window["hi_pulses"])
    if kind == "abs":
        target = int(value)
    else:
        if fresh_pos is None:
            return False, None, "relative rotor move needs a FRESH position read"
        target = int(fresh_pos) + int(value)
    k = float(window.get("deg_per_pulse", ROTOR_DEG_PER_PULSE))
    if lo <= target <= hi:
        return True, target, ("rotor target %d pulses (%.2f deg) inside the session window %d..%d"
                              % (target, target * k, lo, hi))
    return False, target, ("rotor target %d pulses (%.2f deg) OUTSIDE the session window %d..%d pulses "
                           "(start %d +- %d = +-%g turns)" % (target, target * k, lo, hi, window["center_pulses"],
                                                              window["half_width_pulses"],
                                                              window["half_width_pulses"] * k / 360.0))


ASI_UNIT_MM = 1e-4   # see UNITS above: ASI positions are 0.1 um


def parse_asi_fresh(text):
    """'FRESH X=<units> Y=<units>' (motor_asi_io.ps1 -Mode read) -> (x_units, y_units) or None."""
    m = re.search(r"FRESH\s+X=(-?[\d.]+)\s+Y=(-?[\d.]+)", text or "")
    return (float(m.group(1)), float(m.group(2))) if m else None


def relative_window(limits, x_units, y_units):
    """User 2026-10-15 ("그냥 실행 당시 위치를 기준으로 하자"): the ASI window is the stage position at session start
    +- half_width_mm per axis (absolute mm, as SL/SU take). -> (sl, su)."""
    hw = limits["asi"]["half_width_mm"]
    cx, cy = x_units * ASI_UNIT_MM, y_units * ASI_UNIT_MM
    sl = {"X": round(cx - float(hw["X"]), 6), "Y": round(cy - float(hw["Y"]), 6)}
    su = {"X": round(cx + float(hw["X"]), 6), "Y": round(cy + float(hw["Y"]), 6)}
    return sl, su


def asi_window(limits, sess=None):
    """The ASI SL/SU in force: the file's absolute window, or (relative mode) the one the open session recorded."""
    if limits["asi"].get("mode") == "relative":
        sess = sess if sess is not None else session_info()
        if not sess:
            return None, None
        w = sess.get("limits_file", {}).get("asi", {})
        return w.get("sl"), w.get("su")
    return limits["asi"]["sl"], limits["asi"]["su"]


def session_info(path=None):
    try:
        with open(path or SESSION_PATH, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- helpers
def _tokens(command):
    c = command.strip().strip("\r\n")
    if not c:
        return None, []
    # A leading '/' or '!' or '~' or '\' is a whole command on its own in the ASI set.
    if c[0] in "/!~\\@" and (len(c) == 1 or c[1] == " "):
        return c[0], c[1:].split()
    parts = c.split()
    return parts[0].upper(), parts[1:]


def _compound(command):
    """More than one command in one string is refused: the gate must decide exactly one thing."""
    return ("\r" in command.strip("\r\n")) or ("\n" in command.strip("\r\n")) or (";" in command)


def _axis_pairs(args):
    """['X=8000','Y=-200'] -> {'X': 8000.0, 'Y': -200.0}; None if anything is not AXIS=<number>."""
    out = {}
    for a in args:
        m = re.match(r"^([XYZ])\s*=\s*([+-]?\d+(?:\.\d+)?)$", a.strip().upper())
        if not m:
            return None
        out[m.group(1)] = float(m.group(2))
    return out or None


# ---------------------------------------------------------------- per-device decisions
def decide_asi(cmd, args, raw):
    if cmd is None:
        return Decision(False, "empty command")
    if cmd in ASI_ORIGIN:
        return Decision(False, "ASI home/origin/zero/save/reset class command %r (%s) - NEVER permitted: the "
                               "controller SL/SU limits are ABSOLUTE coordinates, so shifting the zero would move "
                               "the fence" % (cmd, ASI_ORIGIN[cmd]))
    if cmd in ASI_QUERIES:
        for a in args:
            if any(ch in a for ch in "=+-"):
                return Decision(False, "ASI %r with argument %r: an argument carrying '=', '+' or '-' is a WRITE, "
                                       "not a query (BU Y=#, BU Z+ ...)" % (cmd, a))
        if cmd in ("W", "WHERE", "RB", "RDSBYTE"):
            for a in args:
                if a.strip().upper() not in AXES:
                    return Decision(False, "ASI %r takes axis letters only, got %r" % (cmd, a))
        return Decision(True, "ASI read-only query %r" % cmd, {"kind": "query"})
    if cmd not in ASI_ABS and cmd not in ASI_REL:
        return Decision(False, "ASI command %r is not on the allow-list (default-deny)" % cmd)

    pairs = _axis_pairs(args)
    if not pairs:
        return Decision(False, "ASI %r: arguments must be AXIS=<number> in tenths of microns, got %r" % (cmd, args))
    relative = cmd in ASI_REL
    return Decision(True, "ASI %s move %s - the CONTROLLER's SL/SU limits bound it (verified by readback at "
                          "transmit time)" % ("relative" if relative else "absolute", pairs),
                    {"kind": "move", "axes": pairs, "relative": relative})


def decide_pi(cmd, args, raw):
    if cmd is None:
        return Decision(False, "empty command")
    if cmd in PI_HOME:
        return Decision(False, "PI %r (%s) - never permitted through this gate" % (cmd, PI_HOME[cmd]))
    if cmd in PI_QUERIES:
        return Decision(True, "PI read-only query %r" % cmd, {"kind": "query"})
    if cmd not in PI_ABS and cmd not in PI_REL:
        return Decision(False, "PI command %r is not on the allow-list (default-deny)" % cmd)
    nums = [float(t) for t in args if re.match(r"^[+-]?\d+(?:\.\d+)?$", t)]
    if not nums:
        return Decision(False, "PI %r: no numeric target found in %r" % (cmd, args))
    relative = cmd in PI_REL
    return Decision(True, "PI %s move to %s - the CONTROLLER's TMN/TMX soft limits bound it (verified by readback "
                          "at transmit time; a target outside them answers ERR 7 and does not move)"
                    % ("relative" if relative else "absolute", nums),
                    {"kind": "move", "targets_mm": nums, "relative": relative})


_ROTOR_X_ONLY = re.compile(r"^([+-]?\d{1,8})\s*,?\s*$")


def decide_rotor(cmd, args, raw, limits=None, session=None, fresh_pos=None):
    """Rotor = PMC-2HS X axis. Unlike PI/ASI the NUMERIC envelope is decided here (and again by the sender inside
    the transmit's port open), because the controller's own soft limit is not installed (docs/rotor-protocol.md).
    `limits`/`session` are loaded from disk when None; `fresh_pos` (pulses) lets a caller decide a PIC fully."""
    if cmd is None:
        return Decision(False, "empty command")
    if cmd in ROTOR_FENCE:
        return Decision(False, "rotor %r (%s) - never permitted through this gate" % (cmd, ROTOR_FENCE[cmd]))
    if cmd in ROTOR_QUERIES and not args:
        return Decision(True, "rotor read-only query %r" % cmd, {"kind": "query"})
    if cmd in ROTOR_QUERIES and ROTOR_QUERIES[cmd] and len(args) == 1 \
            and re.match(ROTOR_QUERIES[cmd], args[0].strip().upper()):
        return Decision(True, "rotor read-only query %r %s" % (cmd, args[0]), {"kind": "query"})
    if cmd not in ROTOR_ABS and cmd not in ROTOR_REL and cmd not in ROTOR_SPEED:
        return Decision(False, "rotor command %r (args %r) is not on the allow-list (default-deny)" % (cmd, args))
    m = _ROTOR_X_ONLY.match(" ".join(args).strip())
    if not m:
        return Decision(False, "rotor %r: exactly one signed decimal X value expected (the rotor is the X axis; a Y "
                               "component or any other form is refused), got %r" % (cmd, " ".join(args)))
    value = int(m.group(1))
    limits = limits if limits is not None else load_limits()
    if not limits or "rotor" not in limits:
        return Decision(False, "rotor %r refused: tools/bench/motor_limits.json has no valid \"rotor\" block" % cmd)
    rot = limits["rotor"]
    if cmd in ROTOR_SPEED:
        if 1 <= value <= int(rot["max_speed"]):
            return Decision(True, "rotor drive speed SPD %d (cap %d)" % (value, rot["max_speed"]),
                            {"kind": "speed", "speed": value})
        return Decision(False, "rotor SPD %d outside 1..%d (the cap is the main VI's default 'Rot Speed'; "
                               "docs/rotor-protocol.md)" % (value, rot["max_speed"]))
    session = session if session is not None else session_info()
    window = (session or {}).get("rotor_window")
    if not window:
        return Decision(False, "rotor %r refused: no open session with a rotor window - run `py tools/motor_gate.py "
                               "--session start` (it reads the rotor POS and records start +- %d pulses)"
                        % (cmd, rot["half_width_pulses"]))
    if int(window.get("half_width_pulses", -1)) != int(rot["half_width_pulses"]):
        return Decision(False, "rotor %r refused: the session window half width %r does not match the limits file "
                               "%r - restart the session" % (cmd, window.get("half_width_pulses"),
                                                             rot["half_width_pulses"]))
    relative = cmd in ROTOR_REL
    detail = {"kind": "move", "relative": relative, "value_pulses": value,
              "value_deg": round(value * ROTOR_DEG_PER_PULSE, 6), "window": window}
    if not relative or fresh_pos is not None:
        ok, target, msg = rotor_target_check(window, "rel" if relative else "abs", value, fresh_pos)
        detail["target_pulses"] = target
        return Decision(ok, "rotor %s %s" % (cmd, msg), detail)
    # PIC without a position: only a step that could never fit is refused now; the sender re-decides with a FRESH
    # POS read inside the transmit's port open (rotor_target_check, tools/motor_rotor_io.ps1).
    if abs(value) > 2 * int(window["half_width_pulses"]):
        return Decision(False, "rotor PIC %d: a step larger than the whole window (%d pulses) can never stay inside "
                               "it" % (value, 2 * int(window["half_width_pulses"])), detail)
    detail["needs_fresh_pos"] = True
    return Decision(True, "rotor PIC %d - allowed by class; the target (FRESH POS + %d) is checked against the "
                          "session window %d..%d inside the transmit's port open"
                    % (value, value, window["lo_pulses"], window["hi_pulses"]), detail)


DEVICES = {"asi": decide_asi, "pi": decide_pi, "rotor": decide_rotor}


def decide(device, command, state=None, limits=None, session=None, fresh_pos=None):
    """The whole command-class decision, with no I/O to a port. `state` is injected so the self-test can run every
    case without touching hardware or the live STATUS.md. NUMERIC bounds are NOT decided here for PI/ASI - the
    controllers hold them, and --execute proves by readback that they are in force. The ROTOR's numeric envelope IS
    decided here (`limits`/`session`/`fresh_pos` injectable; PI/ASI ignore them)."""
    device = (device or "").lower()
    if device not in DEVICES:
        return Decision(False, "unknown device %r (expected one of %s)" % (device, ", ".join(sorted(DEVICES))))
    if state is None:
        state = rig_state(read_status())
    if state == "experiment":
        # ASCII ONLY in every message: this machine's console is cp949 and a UnicodeEncodeError inside the gate
        # would turn a REFUSAL into a crash with a different exit code.
        return Decision(False, "STATUS.md says the rig state is EXPERIMENT RUNNING (experiment in progress) - no "
                               "motor and no instrument access at all (CLAUDE.md rule 1b)")
    if state == "unknown":
        return Decision(False, "STATUS.md carries no machine-readable `rig-state:` line - default-deny "
                               "(only the user announces a state change)")
    if _compound(command):
        return Decision(False, "compound command %r (contains ';' or an embedded terminator) - one command per "
                               "decision" % command)
    cmd, args = _tokens(command)
    if device == "rotor":
        d = decide_rotor(cmd, args, command, limits=limits, session=session, fresh_pos=fresh_pos)
    else:
        d = DEVICES[device](cmd, args, command)
    if d.allowed and state == "assembled" and d.detail.get("kind") == "move":
        d.detail["state_note"] = ("rig assembled: motion allowed by the user's 2026-09-17 ruling, bounded by the "
                                  "CONTROLLER limits this gate installs and re-verifies")
    return d


# ---------------------------------------------------------------- limit readback parsing / checking
def parse_pi_limits(text):
    """'LIMITS TMN=0 TMX=39 SPA15=39 SPA30=0' -> dict, or None.  This is the POST-WRITE readback.

    ANCHORED at the START OF A LINE since 2026-09-18: motor_send_pi.ps1:52 now also prints
    'PRELIMITS TMN=<n> TMX=<n>' (the PRE-write limits), and an unanchored search would match the
    substring 'LIMITS TMN=0 TMX=39' inside 'PRE' + that line - and match it FIRST, because PRELIMITS
    is printed before the SPA write.  The gate would then verify the limits the controller had on
    arrival instead of the ones it just installed.  Case '2b' of
    tools/bench/selftest_motor_gate2.py asserts exactly that (STATUS.md OPEN 55).

    The LAST '^LIMITS' line is judged (cycle 69 repair (b)): limits-set prints one after the write
    (motor_send_pi.ps1:96) and another after the reference move + verify (:147); the last is the state the
    controller is left in."""
    ms = list(re.finditer(r"(?m)^LIMITS\s+TMN=([-+0-9.eE]+)\s+TMX=([-+0-9.eE]+)"
                          r"(?:\s+SPA15=([-+0-9.eE]+)\s+SPA30=([-+0-9.eE]+))?", text or ""))
    if not ms:
        return None
    m = ms[-1]
    out = {"TMN": float(m.group(1)), "TMX": float(m.group(2))}
    if m.group(3) is not None:
        out["SPA15"], out["SPA30"] = float(m.group(3)), float(m.group(4))
    return out


def parse_pi_ref(text):
    """'REFSTATE RON=0 FRF=1 POS=0.00000 POS_BEFORE=0.00000 ERR=0' -> dict, or None.

    The session-start hook performs a REAL reference move (SVO 1 1, RON 1 1, FNL 1 to the negative limit switch),
    requires FRF? 1 and POS 0, then a commanded-vs-readback verify move (0 -> 2 mm -> 0, tol 0.05 mm) - the
    user's 2026-09-23 rule. The retired restore that declared the current counter as zero was removed after it
    drove the magnet into the hard limit (tools/bench/pi_testmove_20260923e.log, ERR 216). Writing SPA 0x15/0x30
    leaves the axis UNREFERENCED (tools/bench/motor_gate2_live.log L2/L3), which is why the reference follows it."""
    m = re.search(r"REFSTATE\s+RON=([-+0-9.eE]+)\s+FRF=([-+0-9.eE]+)\s+POS=([-+0-9.eE]+)"
                  r"\s+POS_BEFORE=([-+0-9.eE]+)", text or "")
    if not m:
        return None
    return {"RON": float(m.group(1)), "FRF": float(m.group(2)),
            "POS": float(m.group(3)), "POS_BEFORE": float(m.group(4))}


def parse_asi_limits(text):
    """'LIMITS SL X=-3.847494 Y=-4.774393 SU X=0.152497 Y=-0.774402' -> dict, or None."""
    m = re.search(r"LIMITS\s+SL\s+X=([-+0-9.eE]+)\s+Y=([-+0-9.eE]+)\s+SU\s+X=([-+0-9.eE]+)\s+Y=([-+0-9.eE]+)",
                  text or "")
    if not m:
        return None
    return {"SL": {"X": float(m.group(1)), "Y": float(m.group(2))},
            "SU": {"X": float(m.group(3)), "Y": float(m.group(4))}}


def check_pi_readback(rb, lo, hi, tol=DEFAULT_TOL):
    """(ok, message). rb = parse_pi_limits() output. Every readback field present must match."""
    if not rb:
        return False, "PI limit readback unreadable (no 'LIMITS TMN=.. TMX=..' line)"
    bad = []
    for key, want in (("TMN", lo), ("TMX", hi), ("SPA30", lo), ("SPA15", hi)):
        if key in rb and abs(rb[key] - want) > tol:
            bad.append("%s=%.4f != %.4f" % (key, rb[key], want))
    if bad:
        return False, "PI controller limits do not match tools/bench/motor_limits.json: " + ", ".join(bad)
    return True, "PI controller limits match the file (TMN %.4f / TMX %.4f, tol %g)" % (lo, hi, tol)


def check_asi_readback(rb, sl, su, tol=DEFAULT_TOL):
    if not rb:
        return False, "ASI limit readback unreadable (no 'LIMITS SL .. SU ..' line)"
    bad = []
    for key, want in (("SL", sl), ("SU", su)):
        for ax in ("X", "Y"):
            if abs(rb[key][ax] - float(want[ax])) > tol:
                bad.append("%s %s=%.6f != %.6f" % (key, ax, rb[key][ax], float(want[ax])))
    if bad:
        return False, "ASI controller limits do not match tools/bench/motor_limits.json: " + ", ".join(bad)
    return True, "ASI controller limits match the file (SL %s / SU %s mm, tol %g)" % (sl, su, tol)


# ---------------------------------------------------------------- session hooks
def _run_ps(script, args, timeout=120):
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script] + args,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _pi_limits_call(mode, lo, hi):
    return _run_ps(PI_SENDER, ["-Mode", mode, "-ExpectLo", "%g" % lo, "-ExpectHi", "%g" % hi])


def _asi_limits_call(mode, sl, su):
    return _run_ps(ASI_IO, ["-Mode", mode, "-ExpectSlX", "%g" % float(sl["X"]), "-ExpectSlY", "%g" % float(sl["Y"]),
                            "-ExpectSuX", "%g" % float(su["X"]), "-ExpectSuY", "%g" % float(su["Y"])])


def _asi_read_call():
    return _run_ps(ASI_IO, ["-Mode", "read"])


def _rotor_read_call():
    return _run_ps(ROTOR_IO, ["-Mode", "read"])


def session_start(limits, pi_call=None, asi_call=None, session_path=None, out=print, asi_read=None,
                  rotor_read=None):
    """Write the file's limits into BOTH controllers and verify by readback. rc 0 = both verified, else 3.
    `pi_call`/`asi_call`/`asi_read` are injected by the self-test: (mode, ...) -> (rc, text).
    ASI relative mode (user 2026-10-15): the window is the stage position read at session start +- half_width_mm."""
    pi_call = pi_call or (lambda mode, lo, hi: _pi_limits_call(mode, lo, hi))
    asi_call = asi_call or (lambda mode, sl, su: _asi_limits_call(mode, sl, su))
    asi_read = asi_read or _asi_read_call
    tol = float(limits.get("tolerance", DEFAULT_TOL))
    lo, hi = float(limits["pi"]["lo_mm"]), float(limits["pi"]["hi_mm"])
    sl, su = limits["asi"]["sl"], limits["asi"]["su"]
    # PI: limits written, then a REAL reference move (FNL 1) and a commanded-vs-readback VERIFY, all inside the
    # sender's limits-set mode (user 2026-09-23: "원점 복귀하여 복원 시키고 사이클 시작한다 … 여러 차례 복원 시도해도
    # 문제가 생긴다면 그 때는 사이클 종료"). Up to REF_ATTEMPTS attempts; only when all fail is the session refused.
    pi_rb, pi_ref, ok_pi, rc, text, attempt = None, None, False, 3, "", 0
    for attempt in range(1, REF_ATTEMPTS + 1):
        rc, text = pi_call("limits-set", lo, hi)
        out(text.strip())
        pi_rb = parse_pi_limits(text)
        ok_lim, msg_pi = check_pi_readback(pi_rb, lo, hi, tol)
        pi_ref = parse_pi_ref(text)
        ok_ref = bool(pi_ref) and pi_ref["FRF"] == 1.0 and abs(pi_ref["POS"]) <= tol
        ok_ver = "VERIFY-RESULT: OK" in (text or "")
        out("PI  : %s (sender code=%d)" % (msg_pi, rc))
        out("PI  : reference %s -> %s; verify %s (attempt %d/%d)"
            % (json.dumps(pi_ref, sort_keys=True) if pi_ref else "NOT REPORTED",
               "REFERENCED at 0" if ok_ref else "NOT REFERENCED", "OK" if ok_ver else "FAILED", attempt, REF_ATTEMPTS))
        ok_pi = ok_lim and ok_ref and ok_ver and rc == 0
        if ok_pi:
            break
        out("PI  : reference/verify attempt %d failed - retrying" % attempt if attempt < REF_ATTEMPTS
            else "PI  : reference/verify failed %d times - giving up" % REF_ATTEMPTS)
        time.sleep(2)
    if not ok_pi:
        # cycle 69 repair (a): a PI refusal after all REF_ATTEMPTS ends the session here - the ASI port is not
        # opened and no ASI limits are written.
        out("ASI : not contacted - PI refused after %d attempts" % REF_ATTEMPTS)
        out("SESSION START REFUSED - no session file written, --execute stays closed")
        return 3
    window = {"mode": "absolute"}
    if limits["asi"].get("mode") == "relative":
        rcr, textr = asi_read()
        out(textr.strip())
        pos = parse_asi_fresh(textr)
        if rcr != 0 or pos is None:
            out("ASI : position read FAILED (rc %s) - the relative window cannot be computed" % rcr)
            out("SESSION START REFUSED - no session file written, --execute stays closed")
            return 3
        sl, su = relative_window(limits, pos[0], pos[1])
        window = {"mode": "relative", "center_units": {"X": pos[0], "Y": pos[1]},
                  "half_width_mm": limits["asi"]["half_width_mm"]}
        out("ASI : relative window around X=%d Y=%d units (%.4f / %.4f mm) +- %s mm -> SL %s / SU %s"
            % (pos[0], pos[1], pos[0] * ASI_UNIT_MM, pos[1] * ASI_UNIT_MM, limits["asi"]["half_width_mm"], sl, su))
    rc2, text2 = asi_call("limits-set", sl, su)
    out(text2.strip())
    asi_rb = parse_asi_limits(text2)
    ok_asi, msg_asi = check_asi_readback(asi_rb, sl, su, tol)
    out("ASI : %s (sender code=%d)" % (msg_asi, rc2))
    if not (ok_pi and rc == 0 and ok_asi and rc2 == 0):
        out("SESSION START REFUSED - no session file written, --execute stays closed")
        return 3
    rec = {"started": time.strftime("%Y-%m-%d %H:%M:%S"),
           "pi_reference": pi_ref, "pi_reference_attempts": attempt, "pi_verify": "OK",
           "limits_readback": {"pi": pi_rb, "asi": asi_rb},
           "limits_file": {"pi": {"lo_mm": lo, "hi_mm": hi}, "asi": {"sl": sl, "su": su}},
           "asi_window": window,
           "tolerance": tol}
    if "rotor" in limits:
        # ROTOR (user 2026-10-19): read-only POS, no write to the controller. A failed read does NOT refuse the PI/ASI
        # session - it records no rotor window, so every rotor move stays refused (decide_rotor) until a new start.
        try:
            rcr, textr = (rotor_read or _rotor_read_call)()
        except (OSError, subprocess.SubprocessError) as e:
            rcr, textr = 6, "ROTOR READ ERROR: %s" % e
        out(textr.strip())
        rpos = parse_rotor_fresh(textr)
        if rcr != 0 or rpos is None:
            rec["rotor_window"] = None
            out("ROTOR: position read FAILED (rc %s) - no rotor window recorded; rotor moves stay refused" % rcr)
        else:
            rec["rotor_window"] = rotor_window_from_pos(limits, rpos)
            w = rec["rotor_window"]
            out("ROTOR: window = start %d pulses (%.2f deg) +- %d -> %d..%d pulses"
                % (rpos, rpos * w["deg_per_pulse"], w["half_width_pulses"], w["lo_pulses"], w["hi_pulses"]))
    with open(session_path or SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, sort_keys=True)
    out("SESSION START OK -> %s" % (session_path or SESSION_PATH))
    return 0


MAGNET_HOME_MM = 0.0        # Q2 (user 2026-10-21): 0 mm = the ceiling, the magnet farthest from the sample
MAGNET_HOME_TOL_MM = 0.01   # the PI sender's own "reached" test (motor_send_pi.ps1, |final - target| < 0.01)


def parse_pi_pos(text, prefix):
    """The POS? value on the FIRST line starting with `prefix` ('after:' of a send, 'before:' of a limits mode); the
    controller answers '1=<value>'. -> float or None."""
    m = re.search(r"(?m)^%s\s+POS\?=(?:1=)?([-+0-9.eE]+)" % re.escape(prefix), text or "")
    return float(m.group(1)) if m else None


def _pi_send_call(canon, lo, hi, tol):
    """ONE 'MOV 1 <n>' through motor_send_pi.ps1 send mode: one-shot token file, the controller limits read back inside
    the same port open BEFORE the transmit (refused, exit 7, unless they are lo..hi), then poll POS? until settled."""
    tok = _token_file(canon)
    try:
        return _run_ps(PI_SENDER, ["-Mode", "send", "-Command", canon, "-TokenFile", tok,
                                   "-ExpectLo", "%g" % lo, "-ExpectHi", "%g" % hi, "-Tol", "%g" % tol], timeout=180)
    finally:
        if os.path.exists(tok):
            os.remove(tok)


def magnet_home(limits, pi_send=None, out=print):
    """Q2 (user 2026-10-21 "Q2 동의함"): the PI magnet back to MAGNET_HOME_MM while the session limits are still set,
    through the --execute send path (class decision, token, limit readback inside the port open, settle poll).
    Verified = sender rc 0 + its 'RESULT: reached' + the limits it read back are the session's + POS after within
    MAGNET_HOME_TOL_MM. `pi_send` (canon, lo, hi, tol) -> (rc, text) is injected by the self-test. -> (ok, why, pos)."""
    canon = "MOV 1 %g" % MAGNET_HOME_MM
    d = decide_pi("MOV", ["1", "%g" % MAGNET_HOME_MM], canon)
    if not d.allowed:
        return False, "the gate's class decision refused %r: %s" % (canon, d.reason), None
    tol = float(limits.get("tolerance", DEFAULT_TOL))
    lo, hi = float(limits["pi"]["lo_mm"]), float(limits["pi"]["hi_mm"])
    try:
        rc, text = (pi_send or _pi_send_call)(canon, lo, hi, tol)
    except (OSError, subprocess.SubprocessError) as e:
        return False, "sender failed to run (%s: %s)" % (type(e).__name__, e), None
    out(text.strip())
    log("pi", canon, d, dry=False)
    _append_log("PI-MAGNET-HOME", rc, text)
    ok_lim, msg_lim = check_pi_readback(parse_pi_limits(text), lo, hi, tol)
    pos = parse_pi_pos(text, "after:")
    why = []
    if rc != 0:
        why.append("sender code %d (%s)" % (rc, EXIT_MEANING.get(rc, "sender's own code")))
    if "RESULT: reached" not in (text or ""):
        why.append("no 'RESULT: reached' line")
    if not ok_lim:
        why.append(msg_lim)
    if pos is None or abs(pos - MAGNET_HOME_MM) > MAGNET_HOME_TOL_MM:
        why.append("POS after = %s, not within %g mm of %g" % (pos, MAGNET_HOME_TOL_MM, MAGNET_HOME_MM))
    if why:
        return False, "NOT verified: " + "; ".join(why), pos
    return True, "verified at %g mm (POS %s, tol %g; limits %g..%g still set during the move)" % (
        MAGNET_HOME_MM, pos, MAGNET_HOME_TOL_MM, lo, hi), pos


def session_end(limits, pi_call=None, asi_call=None, session_path=None, out=print, pi_send=None):
    """With a session open: the PI magnet back to 0 mm and verified (magnet_home) BEFORE anything is released (Q2); then
    release the controller limits (PI lo..release_hi, ASI +-release) and delete the session file. No session file = no
    gate motion was possible since the last verified end -> release only (the PI position is in the 'before:' line).
    A return that fails or is not verified releases NOTHING and keeps the session file (rc 3)."""
    pi_call = pi_call or (lambda mode, lo, hi: _pi_limits_call(mode, lo, hi))
    asi_call = asi_call or (lambda mode, sl, su: _asi_limits_call(mode, sl, su))
    tol = float(limits.get("tolerance", DEFAULT_TOL))
    lo, hi = 0.0, float(limits["pi"]["release_hi_mm"])
    rel = limits["asi"]["release"]
    sl = {"X": float(rel["sl"]), "Y": float(rel["sl"])}
    su = {"X": float(rel["su"]), "Y": float(rel["su"])}
    path = session_path or SESSION_PATH
    sess = session_info(path)
    homed = bool(sess) and bool(sess.get("magnet_home"))
    if sess and not homed:
        ok_home, why_home, pos = magnet_home(limits, pi_send, out)
        out("PI  : magnet return to %g mm: %s" % (MAGNET_HOME_MM, why_home))
        if not ok_home:
            out("SESSION END INCOMPLETE - the magnet return was not verified, so NO limit was released and the session "
                "file is KEPT; the user must look before the rig is used")
            return 3
        # recorded, so a retry after a later failed release does not need the (by then released) session limits
        sess["magnet_home"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "pos_mm": pos}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sess, f, indent=2, sort_keys=True)
    elif homed:
        out("PI  : magnet return already verified at %s (POS %s) by an earlier end attempt"
            % (sess["magnet_home"].get("at"), sess["magnet_home"].get("pos_mm")))
    else:
        out("PI  : no open session file - magnet return skipped (no gate motion was possible since the last verified "
            "end); PI position: see the 'before:' line below")
    rc, text = pi_call("limits-release", lo, hi)
    out(text.strip())
    ok_pi, msg_pi = check_pi_readback(parse_pi_limits(text), lo, hi, tol)
    out("PI  : %s (sender code=%d)" % (msg_pi, rc))
    ok_pos = True
    if sess:      # a second, independent POS read (new port open, before the release write) must still say 0
        p2 = parse_pi_pos(text, "before:")
        ok_pos = p2 is not None and abs(p2 - MAGNET_HOME_MM) <= MAGNET_HOME_TOL_MM
        out("PI  : magnet POS re-read before the release = %s -> %s" % (p2, "at 0 mm" if ok_pos else "NOT at 0 mm"))
    rc2, text2 = asi_call("limits-release", sl, su)
    out(text2.strip())
    ok_asi, msg_asi = check_asi_readback(parse_asi_limits(text2), sl, su, tol)
    out("ASI : %s (sender code=%d)" % (msg_asi, rc2))
    if not (ok_pi and rc == 0 and ok_asi and rc2 == 0 and ok_pos):
        out("SESSION END INCOMPLETE - the session file is KEPT so the mismatch stays visible; --execute will "
            "refuse anyway because the readback no longer matches the file")
        return 3
    if os.path.exists(path):
        os.remove(path)
    out("SESSION END OK - %scontroller limits released, %s deleted"
        % ("magnet at 0 mm, " if sess else "", path))
    return 0


# ---------------------------------------------------------------- transmit
def log(device, command, d, dry):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\tcmd=%r\t%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), device.upper(),
                "ALLOW" if d.allowed else "REFUSE", "DRY" if dry else "LIVE", command, d.reason))
    except OSError:
        pass


def _token_file(canon):
    fd, tok = tempfile.mkstemp(prefix="motor_gate_", suffix=".tok")
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(canon)
    return tok


def transmit(device, command, d, limits):
    """Send ONE decided motion command. The SENDER re-reads the controller limits inside the same port open,
    before the transmit, and refuses if they do not match the file (exit 7)."""
    tol = float(limits.get("tolerance", DEFAULT_TOL))
    if device == "rotor":
        return transmit_rotor(command, d, limits)
    if device == "asi":
        cmd_tok, cmd_args = _tokens(command)
        pairs = _axis_pairs(cmd_args) or {}
        if cmd_tok not in ASI_ABS or len(pairs) != 1 or "Z" in pairs:
            sys.stderr.write("TRANSMIT NOT IMPLEMENTED for this ASI command (only absolute single-axis "
                             "'M X=<int>' or 'M Y=<int>'; Z has no controller limit and is not transmittable "
                             "from here).\n")
            return 5
        axis, val = list(pairs.items())[0]
        canon = "M %s=%d" % (axis, int(round(val)))
        sl, su = asi_window(limits)
        if sl is None or su is None:
            sys.stderr.write("REFUSED: ASI relative window - no open session records it\n")
            return 3
        tok = _token_file(canon)
        try:
            rc, text = _run_ps(ASI_IO, ["-Mode", "send", "-Command", canon, "-TokenFile", tok,
                                        "-ExpectSlX", "%g" % float(sl["X"]), "-ExpectSlY", "%g" % float(sl["Y"]),
                                        "-ExpectSuX", "%g" % float(su["X"]), "-ExpectSuY", "%g" % float(su["Y"]),
                                        "-Tol", "%g" % tol])
        finally:
            if os.path.exists(tok):
                os.remove(tok)
        print(text.strip())
        ok, msg = check_asi_readback(parse_asi_limits(text), sl, su, tol)
        print("GATE re-check of the sender's readback: %s" % msg)
        _append_log("ASI", rc, text)
        return rc if ok else (rc or 3)
    if device != "pi" or d.detail.get("kind") != "move" or d.detail.get("relative"):
        sys.stderr.write("TRANSMIT NOT IMPLEMENTED for this device/command (only PI absolute 'MOV 1 <n>').\n")
        return 5
    lo, hi = float(limits["pi"]["lo_mm"]), float(limits["pi"]["hi_mm"])
    canon = "MOV 1 %s" % ("%.4f" % d.detail["targets_mm"][-1]).rstrip("0").rstrip(".")
    rc, text = _pi_send_call(canon, lo, hi, tol)
    print(text.strip())
    ok, msg = check_pi_readback(parse_pi_limits(text), lo, hi, tol)
    print("GATE re-check of the sender's readback: %s" % msg)
    _append_log("PI", rc, text)
    return rc if ok else (rc or 3)


def transmit_rotor(command, d, limits, session=None, run=None):
    """Send ONE rotor PAB/PIC (X only) through tools/motor_rotor_io.ps1. The SENDER, inside one port open: reads POS
    twice (must be stationary), computes the target (PIC: FRESH POS + step), refuses (exit 7) unless it lies in the
    session window, sets SPD <= max_speed, transmits, watches the position (STO X if it leaves the window) and reports
    the final POS. The gate then re-parses the sender's FRESH line and re-checks the target itself."""
    run = run or _run_ps
    if d.detail.get("kind") != "move":
        sys.stderr.write("TRANSMIT NOT IMPLEMENTED for this rotor command (only PAB <int> / PIC <int>, X axis).\n")
        return 5
    sess = session if session is not None else session_info()
    window = (sess or {}).get("rotor_window")
    if not window:
        sys.stderr.write("REFUSED: rotor - no open session records a rotor window\n")
        return 3
    cmd_tok = "PIC" if d.detail.get("relative") else "PAB"
    value = int(d.detail["value_pulses"])
    canon = "%s %d" % (cmd_tok, value)
    speed = int(limits["rotor"]["max_speed"])
    tok = _token_file(canon)
    try:
        rc, text = run(ROTOR_IO, ["-Mode", "send", "-Command", canon, "-TokenFile", tok,
                                  "-Lo", "%d" % int(window["lo_pulses"]), "-Hi", "%d" % int(window["hi_pulses"]),
                                  "-Speed", "%d" % speed], timeout=150)
    finally:
        if os.path.exists(tok):
            os.remove(tok)
    print(text.strip())
    # The gate's own re-check: the first FRESH line (before the transmit) must parse identically in Python and must
    # put the target inside the window. A sender that transmitted anyway is reported as a gate refusal (rc 3).
    m = re.search(r"(?m)^FRESH RAW='([^']*)' POS=(-?\d+)\s*$", text or "")
    fresh = parse_rotor_fresh(m.group(0)) if m else None
    ok, target, msg = rotor_target_check(window, "rel" if cmd_tok == "PIC" else "abs", value, fresh)
    print("GATE re-check of the sender's fresh read: %s" % (msg if fresh is not None else
                                                            "NO parseable FRESH line (sign check failed or no read)"))
    _append_log("ROTOR", rc, text)
    if fresh is None or not ok:
        return rc or 3
    return rc


def _append_log(tag, rc, text):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s\t%s\tSENT\trc=%d\t%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), tag, rc,
                                                  " | ".join(text.strip().splitlines()[-2:])))
    except OSError:
        pass


# ---------------------------------------------------------------- CLI
RIG_DIR = r"G:\Codes\rig"     # the shared rig lock module + file (user 2026-10-21; not an env var on purpose)
RIG_STATES_OK = ("assembled", "disassembled")


def rig_state_agree(status_text=None):
    """B2 (user 2026-10-21 "승인", debate l2s-conflict-01 C1): V6 reads the rig state from STATUS.md `rig-state:`,
    LabVIEW2Scr from rig_lock.json. NEW device work is refused unless both say the same known state. Cleanup is not
    gated by this (it only needs ownership). Fails CLOSED on any read error. -> (ok, why)."""
    st = rig_state(read_status() if status_text is None else status_text)
    try:
        if RIG_DIR not in sys.path:
            sys.path.insert(0, RIG_DIR)
        import riglock
        lk = (riglock.status().get("rig_state") or {}).get("value") or "missing"
    except Exception as e:                                   # noqa: BLE001 - fail closed
        return False, "rig_lock.json unreadable (%s: %s) - cannot compare the rig state" % (type(e).__name__, e)
    if st == lk and st in ("assembled", "disassembled", "experiment"):
        return True, "rig state agrees: %s" % st
    return False, ("rig state DISAGREES: STATUS.md says %s, rig_lock.json says %s - no new device work until the "
                   "chat records the user's word in both (riglock.py set-state + STATUS.md rig-state)" % (st, lk))


def rig_lock_ok(kind, states=RIG_STATES_OK, status_text=None):
    """The shared rig lock (user 2026-10-21, debate riglock-v6 item 6). The caller's token comes in RIGLOCK_TOKEN from
    the lock holder (the lean queue, or rig_session.py). kind 'end' = cleanup (limits release): ownership only, also in
    the experiment state (user item 9: the rig is returned to its initial condition). Anything else (session start,
    reference move, --execute): riglock.permitted - holder AND state in `states` (the gate: assembled / disassembled;
    the lean cycle hooks pass assembled only); experiment always no; and (B2) STATUS.md and rig_lock.json must agree
    (`status_text` = the STATUS.md text the caller decided on; None = read STATUS.md).
    Fails CLOSED: no token, module or lock file unreadable -> refused. -> (ok, why)."""
    token = os.environ.get("RIGLOCK_TOKEN", "").strip()
    if not token:
        return False, "no RIGLOCK_TOKEN - the rig lock is not held by this process tree (lean queue / rig_session.py)"
    if kind != "end":
        agree, why = rig_state_agree(status_text)
        if not agree:
            return False, why
    try:
        if RIG_DIR not in sys.path:
            sys.path.insert(0, RIG_DIR)
        import riglock
        ok = riglock.check(token) if kind == "end" else riglock.permitted(token, tuple(states))
    except Exception as e:                                   # noqa: BLE001 - fail closed
        return False, "rig lock unreadable (%s: %s)" % (type(e).__name__, e)
    if ok:
        return True, "rig lock held"
    if kind == "end":
        return False, "this token is not the rig lock holder (or the holder process is gone)"
    return False, "rig lock does not permit work: not the holder, or rig state not in %s" % "/".join(states)


def main(argv=None):
    p = argparse.ArgumentParser(description="the single gateway for motion commands to PI / ASI / rotor")
    p.add_argument("--session", choices=["start", "end"], default=None,
                   help="start: write the controller limits from tools/bench/motor_limits.json and verify them; "
                        "end: release them (PI 0..release_hi, ASI +-500) and delete the session file")
    p.add_argument("--device", default=None, help="pi | asi | rotor")
    p.add_argument("--command", default=None, help="one raw controller command, e.g. 'M X=8000' or 'MOV 1 12.5'")
    p.add_argument("--dry-run", action="store_true", default=True, help="decide only, open no port (the DEFAULT)")
    p.add_argument("--execute", action="store_true", help="transmit (needs an open session and a matching readback)")
    p.add_argument("--limits", default=None, help="override the limits file path (tests)")
    p.add_argument("--status", default=None, help="override STATUS.md (tests)")
    p.add_argument("--journal", default=None, help="override the decision journal tools/bench/motor_gate.log (tests; "
                                                   "cycle 70 F6a: self-test rows had landed in the production journal)")
    p.add_argument("--reference", default=None, metavar="USER_ORDER",
                   help="USER-ORDERED PI reference move (FNL 1: 0 = negative limit switch). The value is the user's "
                        "own words ordering it, logged verbatim. Never automatic; the session hooks never call it.")
    a = p.parse_args(argv)
    if a.journal:
        global LOG_PATH
        LOG_PATH = a.journal

    limits = load_limits(a.limits)
    if limits is None:
        sys.stderr.write("REFUSED: limits file %s is missing, unreadable or incomplete - the gate installs and "
                         "verifies the CONTROLLER limits from it, so nothing is permitted without it\n"
                         % (a.limits or LIMITS_PATH))
        return 3
    status_text = read_status(a.status)
    state = rig_state(status_text)
    if a.session:
        # --session end is the CLEANUP (magnet back to 0 mm, limits released): also in the experiment state, for the
        # lock holder only (user 2026-10-21 item 9 "초기 조건으로 돌려줘야" and Q2 "Q2 동의함" - an experiment declared
        # mid-job still returns the rig to its initial condition). Start stays refused there; unknown refuses both.
        ok_states = ("assembled", "disassembled") + (("experiment",) if a.session == "end" else ())
        if state not in ok_states:
            sys.stderr.write("REFUSED: rig state %r - the session hook opens both motor ports (CLAUDE.md 1b)\n"
                             % state)
            return 3
        lok, lwhy = rig_lock_ok(a.session, status_text=status_text)
        if not lok:
            sys.stderr.write("REFUSED: %s - --session %s needs the shared rig lock\n" % (lwhy, a.session))
            return 3
        return session_start(limits) if a.session == "start" else session_end(limits)
    if a.reference:
        # 2026-09-23: a power-cycled C-863 restarts with POS 0 at the stage's physical spot; the session-start hook
        # then cemented that false zero (RON 1 0 + POS 1 <current>) and a MOV +30 ran into the hard limit (ERR 216).
        # The only correct repair is a real reference move, which PI_HOME forbids on every other route.
        if state != "assembled" and state != "disassembled":
            sys.stderr.write("REFUSED: rig state %r - no reference move in this state\n" % state)
            return 3
        if len(a.reference.strip()) < 4:
            sys.stderr.write("REFUSED: --reference needs the user's order text\n")
            return 3
        lok, lwhy = rig_lock_ok("reference", status_text=status_text)
        if not lok:
            sys.stderr.write("REFUSED: %s - a reference move needs the shared rig lock\n" % lwhy)
            return 3
        print("USER-ORDERED REFERENCE MOVE: %r" % a.reference)
        rc, text = _run_ps(PI_SENDER, ["-Mode", "reference", "-SettleTimeoutS", "120"], timeout=180)
        print(text.strip())
        _append_log("PI-REFERENCE(user: %s)" % a.reference[:60], rc, text)
        return rc

    if not a.device or not a.command:
        sys.stderr.write("usage: --session start|end, or --device <d> --command <c> [--execute]\n")
        return 4
    d = decide(a.device, a.command, state=state, limits=limits)
    log(a.device, a.command, d, dry=not a.execute)
    if not d.allowed:
        sys.stderr.write("REFUSED (%s): %s\n" % (a.device, d.reason))
        return 3
    print("ALLOWED (%s): %s" % (a.device, d.reason))
    if d.detail:
        print(json.dumps(d.detail, sort_keys=True))
    if not a.execute:
        return 0
    if d.detail.get("kind") != "move":
        print("(query decisions are not transmitted by this gate)")
        return 5
    sess = session_info()
    if not sess:
        sys.stderr.write("REFUSED: no session file %s - run `py tools/motor_gate.py --session start` first, which "
                         "installs the CONTROLLER limits and verifies them\n" % SESSION_PATH)
        return 3
    lok, lwhy = rig_lock_ok("execute", status_text=status_text)
    if not lok:
        sys.stderr.write("REFUSED: %s - --execute needs the shared rig lock\n" % lwhy)
        return 3
    print("session opened %s" % sess.get("started"))
    return transmit(a.device.lower(), a.command, d, limits)


EXIT_MEANING = {3: "REFUSED by the gate (rig state / command class / session / limit readback)",
                4: "usage error", 5: "transmit not implemented for this command",
                6: "sender could not read the controller", 7: "sender REFUSED (token / limits mismatch / servo)",
                8: "motion ended NOT at target", 9: "REJECTED BY THE CONTROLLER (ERR after send) or reference incomplete"}


def fail_line(rc):
    """One `FAIL:` line for a non-zero exit (cycle 69, device-failed repair). pi_testmove_20260923e.log:23/34 held a
    NOT-at-target and a REJECTED result, yet the chained bash run ended `BGRUN END rc=0` (:51) because a later command
    in the chain succeeded, so bgrun, audit_cycle and guard_peer never saw the failure. `^FAIL\\b` is the form all three
    scanners already match. Printed at PROCESS exit only, not inside main(), so in-process self-tests that call main()
    on purpose-refused commands do not print it. ASCII only (cp949 console)."""
    return "FAIL: motor_gate exit %d - %s" % (rc, EXIT_MEANING.get(rc, "sender's own non-zero code"))


def result_line(rc):
    """C6 (docs/session-protocol.md, user-approved 2026-09-24): the gate's verdict as its LAST line. bgrun's body scan
    for `RESULT: REJECTED` / `NOT at target` / `ERR?=N` / `FAIL:` was REMOVED the same day, so a refused, rejected or
    missed move is now caught by THIS line (and by the non-zero exit). A chained command prints one RESULT per call;
    a run fails when ANY of them fails (protocol.run_verdict), so a later passing call cannot hide a rejected move.
    Printed at PROCESS exit only, like fail_line(), so in-process self-tests of main() print neither."""
    sys.path.insert(0, HERE)
    import protocol
    return protocol.result_line(protocol.make_result(0 if rc else 1, 1 if rc else 0,
                                                     fail_line(rc) if rc else None))


if __name__ == "__main__":
    _rc = main()
    if _rc:
        print(fail_line(_rc), flush=True)
    print(result_line(_rc), flush=True)
    sys.exit(_rc)
# ---
# labview: none
# hardware: motor
# offline-args: --dry-run --help
# evidence: tools/motor_gate.py:1
# ---
