r"""refbead_record.py - raw-image recordings of a reference-bead-only field (owner 2026-10-26): noise, field-position
pattern map and pixel scale, magnet-position ramp, rotation. Records raw data only; tracking and analysis run offline.

  py tools/refbead_record.py show  --plan magnet                     print the expanded steps (no device)
  py tools/refbead_record.py run   --plan magnet --dry               fake camera + motor_gate --dry-run (no device)
  py tools/refbead_record.py snap  --out <dir>                       RIG: one full frame -> frame.npy + beads.json
  py tools/refbead_record.py run   --plan magnet --out <dir>         RIG: inside V6 tools/rig_session.py only

Rig rules (G:\Codes\rig\RULES.md): the camera opens only under rig_session (RIGLOCK_TOKEN set; LabVIEW closed - it owns
the camera); every motion is one V6 `motor_gate.py --execute` call in a SEPARATE process, so no serial call is on the
frame path (rule 6); a refused or failed gate call stops the plan and rig_session cleans up.

Output per run directory: `meta.json` (camera read-back, beads, plan), `events.jsonl` (every step and gate call with
PC time and the newest buffer number), per stream segment `<name>.crops.u8` (frames x beads x 2h x 2h, raw uint8) +
`<name>.index.npy` (buffer number, PC time s), per snapshot `<name>.full.npy` (n x 1024 x 1280 uint8).
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
V6 = r"G:\Codes\LabVIEW_Codes\MinLab\zz_LabView VI\AAA_UNIST\2. Tracking\V6_ParallelLoop"
GATE = os.path.join(V6, "tools", "motor_gate.py")
FAKE_FRAME = r"G:\m8_replay_frames\f00000.tif"
HALF = 80                 # crop half size (px): the tracker needs a 144 px sub-image at cross 120 (h = 72) + room
EDGE = HALF + 8
MIN_SEP = 2 * HALF        # nearest other spot (px); --min-sep lowers it for a sparse field (crops then overlap)

# ---------------------------------------------------------------- plans (numbers for the owner's approval)
MAG_STEPS = [0, 10, 20, 25, 28, 30, 32, 34, 35, 36, 37, 38, 39]     # mm; 0 = farthest from the sample
FIELD_UM = (35.0, 28.0)   # 3 x 3 grid half-span (x, y) in um, ~1/3 of the 107 x 86 um field
SCALE_UM = [5, 10, 20, 35]  # single-axis steps for the pixel-scale line


def asi(axis, um):
    """A relative ASI step as a list (empty for a zero step); unit 0.1 um."""
    return [{"do": "gate", "device": "asi", "command": f"R {axis}={round(um * 10)}"}] if round(um * 10) else []


def plan(name, exposure_us):
    cam = {"do": "camera", "rate_hz": 150.0, "exposure_us": exposure_us}
    if name == "static":                      # 1. noise: auto vs fixed exposure, 150 and 90 Hz, magnet far
        return [{"do": "gate", "device": "pi", "command": "MOV 1 0"},
                {"do": "camera", "rate_hz": 150.0, "exposure_us": None}, {"do": "hold", "name": "s150_auto", "s": 60},
                cam, {"do": "hold", "name": "s150_fixed", "s": 60},
                {"do": "camera", "rate_hz": 90.0, "exposure_us": exposure_us}, {"do": "hold", "name": "s90_fixed", "s": 60}]
    if name == "field":                       # 2. same beads at 3 x 3 field positions + single-axis scale line
        steps, at = [cam, {"do": "snap", "name": "f_start", "n": 30}], (0.0, 0.0)
        for j in (-1, 0, 1):
            for i in (-1, 0, 1):
                tx, ty = i * FIELD_UM[0], j * FIELD_UM[1]
                steps += [*asi("X", tx - at[0]), *asi("Y", ty - at[1]), {"do": "settle", "s": 2},
                          {"do": "snap", "name": f"f_{i}_{j}", "n": 30}]
                at = (tx, ty)
        steps += [*asi("X", -at[0]), *asi("Y", -at[1]), {"do": "settle", "s": 2}]
        for axis in ("X", "Y"):
            for um in SCALE_UM:
                steps += [*asi(axis, um), {"do": "settle", "s": 2}, {"do": "snap", "name": f"sc_{axis}{um}", "n": 30},
                          *asi(axis, -um), {"do": "settle", "s": 2}, {"do": "snap", "name": f"sc_{axis}{um}_back", "n": 30}]
        return steps
    if name == "magnet":                      # 3. pattern / z / xy vs magnet position, up then down (hysteresis)
        steps = [cam, {"do": "stream", "name": "ramp"}]
        for mm in MAG_STEPS + MAG_STEPS[-2::-1]:
            steps += [{"do": "gate", "device": "pi", "command": f"MOV 1 {mm}"}, {"do": "settle", "s": 1},
                      {"do": "mark", "name": f"hold_{mm}mm"}, {"do": "wait", "s": 20},
                      {"do": "snap", "name": f"m{mm}", "n": 5}]
        return steps + [{"do": "stream", "name": None}]
    if name == "rotation":                    # 4. +-4 turns twice at the gate speed (SPD 100), four magnet positions
        steps = [cam]
        for mm in (0, 30, 36, 39):
            steps += [{"do": "gate", "device": "pi", "command": f"MOV 1 {mm}"}, {"do": "stream", "name": f"rot_{mm}mm"},
                      {"do": "wait", "s": 5}]
            for _ in range(2):                     # the gate sends every rotor move at its SPD cap (100) itself
                steps += [{"do": "gate", "device": "rotor", "command": "PIC 2000"}, {"do": "wait", "s": 2},
                          {"do": "gate", "device": "rotor", "command": "PIC -2000"}, {"do": "wait", "s": 2}]
            steps += [{"do": "wait", "s": 5}, {"do": "stream", "name": None}]
        return steps + [{"do": "gate", "device": "pi", "command": "MOV 1 0"}]
    if name == "exposure":                    # 5. noise vs exposure at 150 Hz, magnet far
        steps = [{"do": "gate", "device": "pi", "command": "MOV 1 0"}]
        for us in (500, 1000, 1500, 1909):
            steps += [{"do": "camera", "rate_hz": 150.0, "exposure_us": us}, {"do": "hold", "name": f"e{us}", "s": 30}]
        return steps
    if name == "exposure2":                   # 5b. shuffled and repeated, down to 100 us (owner 2026-10-27)
        steps = [{"do": "gate", "device": "pi", "command": "MOV 1 0"},
                 {"do": "camera", "rate_hz": 150.0, "exposure_us": 1909}, {"do": "wait", "s": 30}]   # settle first
        for k, us in enumerate((1909, 200, 1000, 100, 500, 1909, 500, 100, 1000, 200)):
            steps += [{"do": "camera", "rate_hz": 150.0, "exposure_us": us}, {"do": "hold", "name": f"x{k}_e{us}", "s": 20}]
        return steps
    if name == "drift":                       # 6. 30 min at rest: drift, Allan variance, long-run frame loss
        return [{"do": "gate", "device": "pi", "command": "MOV 1 0"}, cam, {"do": "snap", "name": "d_start", "n": 5},
                {"do": "hold", "name": "drift", "s": 1800}, {"do": "snap", "name": "d_end", "n": 5}]
    if name == "zscan":                       # 7. LUT stack: current focus +-5 um in 100 nm (1 ASI unit) steps
        return [cam, {"do": "gate", "device": "pi", "command": "MOV 1 0"}] + zscan("zscan") + [{"do": "stream", "name": None}]
    if name == "zscan_field":                 # 8. the same z-scan with the field moved to each 3 x 3 position
        steps, at = [cam, {"do": "gate", "device": "pi", "command": "MOV 1 0"}], (0.0, 0.0)
        for j in (-1, 0, 1):
            for i in (-1, 0, 1):
                tx, ty = i * FIELD_UM[0], j * FIELD_UM[1]
                steps += [*asi("X", tx - at[0]), *asi("Y", ty - at[1]), {"do": "settle", "s": 2}, {"do": "repick"}]
                steps += zscan(f"zf_{i}_{j}") + [{"do": "stream", "name": None}]
                at = (tx, ty)
        return steps + [*asi("X", -at[0]), *asi("Y", -at[1])]
    if name in ("zfine50", "zfine20"):         # 9. sub-100 nm focus steps (decimal ASI units), up then back down
        step, half = (0.5, 50) if name == "zfine50" else (0.2, 20)   # 50 nm over +-5 um, 20 nm over +-2 um
        return ([cam, {"do": "gate", "device": "pi", "command": "MOV 1 0"}] + zscan_fine(name, step, half)
                + [{"do": "stream", "name": None}])
    if name == "search":                      # 10. find a field with many reference beads: 5 x 5 grid, 300 um pitch
        steps, at = [cam], (0.0, 0.0)
        for j in range(-2, 3):
            for i in range(-2, 3):
                tx, ty = i * 300.0, j * 300.0
                steps += [*asi("X", tx - at[0]), *asi("Y", ty - at[1]), {"do": "settle", "s": 1.5},
                          {"do": "snap", "name": f"g_{i}_{j}", "n": 3}]
                at = (tx, ty)
        return steps + [*asi("X", -at[0]), *asi("Y", -at[1])]
    if name == "zfine_at":                    # 11. at the chosen field: 100 nm LUT, then 50 nm and 20 nm scans
        dx, dy = AT_UM
        steps = [cam, {"do": "gate", "device": "pi", "command": "MOV 1 0"}, *asi("X", dx), *asi("Y", dy),
                 {"do": "settle", "s": 2}, {"do": "repick"}]
        steps += zscan("zscan") + [{"do": "stream", "name": None}]
        steps += zscan_fine("zfine50", 0.5, 50) + [{"do": "stream", "name": None}]
        steps += zscan_fine("zfine20", 0.2, 20) + [{"do": "stream", "name": None}]
        return steps + [*asi("X", -dx), *asi("Y", -dy)]
    if name == "tether":                      # 12. tethered beads under force clamp (owner 2026-10-28). HIGH force
        # first, low force last ("high-force에서 low-force로 내려가는 걸 추천"): a bead left near the surface at low
        # force may bind non-specifically, and such a trace is cut away more easily when it comes at the end. The
        # magnet visits every calibration position from the highest down (default 38 then 36.4 mm); at each, every
        # exposure gets 20 s at rest (fluctuations = the measurement noise at that force) and a 100 nm z-scan with
        # 0.5 s per slice (+ a 50 nm scan). Offline: the noise at one force with the LUT taken at the same or at the
        # other position / exposure. Only at the end the magnet returns to 0 mm, with a 10 s rest that shows which
        # beads respond to the force (= tethered).
        steps = [{"do": "camera", "rate_hz": 150.0, "exposure_us": TETHER_EXPOSURES_US[0]}]
        for mm in sorted(TETHER_CALIB_MM, reverse=True):
            steps += [{"do": "gate", "device": "pi", "command": f"MOV 1 {mm:g}"}, {"do": "settle", "s": 3}]
            for us in TETHER_EXPOSURES_US:
                tag = f"m{mm:g}_e{us:g}"
                steps += [{"do": "camera", "rate_hz": 150.0, "exposure_us": us},
                          {"do": "hold", "name": f"clamp_{tag}", "s": 20}]
                steps += zscan(f"zs_{tag}", 50, 0.5) + [{"do": "stream", "name": None}]
                if TETHER_FINE:
                    steps += zscan_fine(f"zf_{tag}", 0.5, 30, 0.5) + [{"do": "stream", "name": None}]
        tag = f"e{TETHER_EXPOSURES_US[0]:g}"
        steps += [{"do": "camera", "rate_hz": 150.0, "exposure_us": TETHER_EXPOSURES_US[0]},
                  {"do": "hold", "name": f"clamp_end_{tag}", "s": 10},
                  {"do": "gate", "device": "pi", "command": "MOV 1 0"}, {"do": "settle", "s": 3},
                  {"do": "hold", "name": f"rest0_{tag}", "s": 10}]
        return steps
    raise SystemExit(f"unknown plan {name!r}")


# tether plan parameters, set by --magnet-mm / --exposures / --no-fine. 36.4 mm = about 7 pN with the M-270 v3
# equation when the touch position is 40.94 mm (F = 48.8 e^(-d/1.135) + 22.8 e^(-d/3.684) - 0.46, d = touch - pos);
# the owner gives the position that pulls the tether to about 1600 nm.
TETHER_MAGNET_MM = 36.4
TETHER_CALIB_MM = (38.0, 36.4)    # calibration (and rest) positions, visited from the highest force down
TETHER_EXPOSURES_US = (1909.0, 1000.0, 500.0)
TETHER_FINE = True
AT_UM = (0.0, 0.0)            # field offset for zfine_at, set by --at-um


def zscan_fine(seg, step_units, half_units, hold_s=0.2):
    """Relative focus steps of `step_units` (0.1 um units, may be decimal) from -half to +half and back to -half,
    then to the start. Every slice is marked with its commanded z (units) and direction; the way back cancels a
    linear focus drift when the two passes are averaged."""
    n = round(2 * half_units / step_units)
    st = f"{step_units:g}"
    steps = [{"do": "stream", "name": seg}, {"do": "gate", "device": "asi", "command": f"R Z={-half_units}"},
             {"do": "settle", "s": 1}]
    for way, sign in (("up", 1), ("dn", -1)):
        for i in range(n + 1):
            if i:
                steps.append({"do": "gate", "device": "asi", "command": f"R Z={st if sign > 0 else '-' + st}"})
            z = round(-half_units + (i if sign > 0 else n - i) * step_units, 3)
            steps += [{"do": "settle", "s": 0.3}, {"do": "mark", "name": f"{seg}_{way}{i}_start", "z_units": z},
                      {"do": "wait", "s": hold_s}, {"do": "mark", "name": f"{seg}_{way}{i}_end", "z_units": z}]
    return steps + [{"do": "gate", "device": "asi", "command": f"R Z={half_units}"}, {"do": "settle", "s": 1}]


def zscan(seg, half_units=50, hold_s=0.2):
    """Relative focus steps of 1 ASI unit (0.1 um) from -half to +half and back to the start; every slice is marked
    in events.jsonl (buffer numbers) and holds 0.2 s (30 frames at 150 Hz) after a 0.3 s settle."""
    steps = [{"do": "stream", "name": seg}, {"do": "gate", "device": "asi", "command": f"R Z={-half_units}"},
             {"do": "settle", "s": 1}]
    for k in range(2 * half_units + 1):
        if k:
            steps.append({"do": "gate", "device": "asi", "command": "R Z=1"})
        steps += [{"do": "settle", "s": 0.3}, {"do": "mark", "name": f"{seg}_z{k - half_units}_start"},
                  {"do": "wait", "s": hold_s}, {"do": "mark", "name": f"{seg}_z{k - half_units}_end"}]
    return steps + [{"do": "gate", "device": "asi", "command": f"R Z={-half_units}"}, {"do": "settle", "s": 1}]


# ---------------------------------------------------------------- camera stand-in for --dry
class FakeCamera:
    """Replays one recorded frame with noise at the set rate; buffer numbers like IMAQdx."""
    def __init__(self):
        from PIL import Image
        self.base = np.asarray(Image.open(FAKE_FRAME)).astype(np.int16)
        self.rate, self.exp, self.acquiring = 90.0009, 1909.0, False

    def open(self):
        pass

    def configure(self, rate_hz=None, exposure_us=None):
        self.rate = rate_hz or self.rate
        self.exp = exposure_us or self.exp
        return self.readback()

    def readback(self):
        return {"camera": "fake", "width": 1280, "height": 1024, "rate_hz": self.rate,
                "exposure_auto": "Off", "exposure_us": self.exp}

    def start(self, n_buffers=50):
        self.t0, self.acquiring = time.time(), True

    def frame(self, b):
        t_due = self.t0 + b / self.rate
        while time.time() < t_due:
            time.sleep(0.0005)
        img = np.clip(self.base + np.random.randint(-3, 4, self.base.shape), 0, 255).astype(np.uint8)
        return b, time.time(), img

    def stop(self):
        self.acquiring = False

    def close(self):
        self.stop()


# ---------------------------------------------------------------- acquisition thread (no serial I/O here)
class Recorder(threading.Thread):
    def __init__(self, cam, beads, out):
        super().__init__(daemon=True)
        self.cam, self.out = cam, out
        self.yx = [(int(b["y"]), int(b["x"])) for b in beads]
        self.lock = threading.Lock()
        self.seg, self.f, self.idx = None, None, []
        self.snap_req, self.snap_done = None, threading.Event()
        self.last_buffer, self.gaps, self.error = -1, 0, None
        self.running = True

    def run(self):
        b = 0
        try:
            while self.running:
                act, t, img = self.cam.frame(b)
                if self.last_buffer >= 0 and act > self.last_buffer + 1:
                    self.gaps += act - self.last_buffer - 1
                self.last_buffer, b = act, act + 1
                with self.lock:
                    if self.f is not None:
                        self.f.write(np.stack([img[y - HALF:y + HALF, x - HALF:x + HALF] for y, x in self.yx]).tobytes())
                        self.idx.append((act, t))
                    if self.snap_req is not None:
                        self.snap_req["frames"].append(img.copy())
                        self.snap_req["t"].append((act, t))
                        if len(self.snap_req["frames"]) >= self.snap_req["n"]:
                            self.snap_req, _ = None, self.snap_done.set()
        except Exception as e:  # noqa: BLE001 - any failure stops the plan: the main thread reads it
            self.error = repr(e)

    def stream(self, name):
        with self.lock:
            if self.f is not None:
                self.f.close()
                np.save(os.path.join(self.out, f"{self.seg}.index.npy"), np.array(self.idx, dtype=np.float64))
                self.f, self.idx = None, []
            self.seg = name
            if name:
                dump({"beads": [{"y": y, "x": x} for y, x in self.yx], "half": HALF},
                     os.path.join(self.out, f"{name}.beads.json"))
                self.f = open(os.path.join(self.out, f"{name}.crops.u8"), "wb", buffering=8 << 20)  # noqa: SIM115

    def snap(self, name, n, timeout_s=30):
        req = {"n": n, "frames": [], "t": []}
        self.snap_done.clear()
        with self.lock:
            self.snap_req = req
        if not self.snap_done.wait(timeout_s):
            raise RuntimeError(f"snapshot {name}: only {len(req['frames'])}/{n} frames in {timeout_s} s")
        np.save(os.path.join(self.out, f"{name}.full.npy"), np.stack(req["frames"]))
        np.save(os.path.join(self.out, f"{name}.full_index.npy"), np.array(req["t"], dtype=np.float64))


# ---------------------------------------------------------------- the sequencer
def find_beads(img):
    """Reference beads in one full frame, via the V6 bead-map finder (all stable round singles, away from the edge).
    shortcut: imports the V6 dev tool; upgrade to a mtpy bead finder with phase 8 (U7, U23)."""
    sys.path.insert(0, os.path.join(V6, "tools", "bench", "lean_bench"))
    import p64_beadmap
    found = p64_beadmap.find(img)
    h, w = img.shape
    beads = [b for b in found["beads"] if EDGE <= b["x"] < w - EDGE and EDGE <= b["y"] < h - EDGE
             and (b["nearest"] is None or b["nearest"] >= MIN_SEP)]
    return beads, found


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(d, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def asi_start():
    """ASI X/Y (and Z, when a Z window is open) start position in 0.1 um that the open motor session recorded
    (read-only file of the V6 gate)."""
    with open(os.path.join(V6, "tools", "bench", "motor_session.json"), encoding="utf-8-sig") as f:
        sess = json.load(f)
    c = sess["asi_window"]["center_units"]
    out = {"X": int(c["X"]), "Y": int(c["Y"])}
    if (sess.get("asi_z_window") or {}).get("start_units") is not None:
        out["Z"] = float(sess["asi_z_window"]["start_units"])
    return out


def gate(step, dry, log, asi_pos=None):
    command = step["command"]
    if step["device"] == "asi" and command[:4] in ("R X=", "R Y="):
        # the gate transmits only absolute X/Y moves: a plan step 'R X=<d>' becomes 'M X=<start + sum of d>'
        axis = command[2]
        asi_pos[axis] += int(command[4:])
        command = f"M {axis}={asi_pos[axis]}"
    elif step["device"] == "asi" and command[:4] == "R Z=" and "Z" in asi_pos:
        # focus steps go absolute from the session's start Z, so no rounded fresh read can lose a decimal step
        asi_pos["Z"] = round(asi_pos["Z"] + float(command[4:]), 3)
        command = f"M Z={asi_pos['Z']:g}"
    cmd = [sys.executable, "-u", GATE, "--device", step["device"], "--command", command,
           "--dry-run" if dry else "--execute"]
    if step["device"] == "pi" and step["command"].startswith("MOV") and not dry:
        cmd.append("--fastpoll")                   # waits for 'RESULT: reached' (V6 card pistall2)
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    log({"gate": command, "plan_step": step["command"], "device": step["device"], "rc": p.returncode, "t0": t0, "t1": time.time(),
         "out": p.stdout[-2000:], "err": p.stderr[-1000:]})
    if p.returncode != 0:
        raise RuntimeError(f"motor_gate refused or failed (rc {p.returncode}) on {command!r}")


def run(args):
    if not args.dry and not os.environ.get("RIGLOCK_TOKEN"):
        raise SystemExit("REFUSED: rig runs only inside V6 tools/rig_session.py (no RIGLOCK_TOKEN)")
    out = os.path.join(args.out, args.plan)
    os.makedirs(out, exist_ok=False)                # never overwrite a recording
    steps = plan(args.plan, args.exposure_us)
    ev = open(os.path.join(out, "events.jsonl"), "w", encoding="utf-8")  # noqa: SIM115 - closed in finally
    cam = FakeCamera() if args.dry else __import__("mtpy.devices.imaqdx", fromlist=["x"]).ImaqdxCamera()
    rec, meta, asi_pos = None, {"plan": args.plan, "result": "failed"}, None
    k = 0.05 if args.dry else 1.0                   # --dry runs the waits 20x faster

    def log(d):
        d.setdefault("t", time.time())
        d["buffer"] = rec.last_buffer if rec else None
        ev.write(json.dumps(d) + "\n")
        ev.flush()
    try:
        cam.open()
        cam.start()
        _, _, img = cam.frame(0)
        beads, _ = find_beads(img) if not args.beads else (load(args.beads)["beads"], None)
        cam.stop()
        if not beads and args.plan not in ("search", "zfine_at"):   # these two pick (or need) no bead at the start
            raise RuntimeError("no reference bead found")
        meta.update({"plan": args.plan, "steps": steps, "beads": beads, "half": HALF, "dry": args.dry,
                "camera_open": cam.readback(), "started": time.strftime("%Y-%m-%d %H:%M:%S")})
        for i, s in enumerate(steps):
            log({"step": i, **s})
            if rec and rec.error:
                raise RuntimeError("acquisition failed: " + rec.error)
            if s["do"] == "camera":                 # rate / exposure need a stopped acquisition (U17 'needs pause')
                seg = rec.seg if rec else None
                if rec:
                    rec.stream(None)
                    rec.running = False
                    rec.join(10)
                cam.stop()
                rb = cam.configure(s["rate_hz"], s["exposure_us"])
                meta.setdefault("camera", []).append({"step": i, **rb})
                log({"camera_readback": rb})
                cam.start()
                rec = Recorder(cam, beads, out)
                rec.start()
                if seg:
                    rec.stream(seg + f"_s{i}")
            elif s["do"] == "gate":
                if s["device"] == "asi" and asi_pos is None:
                    asi_pos = {"X": 0, "Y": 0} if args.dry else asi_start()
                    meta["asi_start_units"] = dict(asi_pos)
                gate(s, args.dry, log, asi_pos)
            elif s["do"] in ("settle", "wait"):
                time.sleep(s["s"] * k)
            elif s["do"] == "stream":
                rec.stream(s["name"])
            elif s["do"] == "hold":
                rec.stream(s["name"])
                time.sleep(s["s"] * k)
                rec.stream(None)
            elif s["do"] == "snap":
                rec.snap(s["name"], s["n"])
            elif s["do"] == "mark":
                pass
            elif s["do"] == "repick":               # the field moved: find the beads again, new crops
                rec.stream(None)
                rec.running = False
                rec.join(10)
                cam.stop()
                cam.start()
                _, _, img = cam.frame(0)
                beads, _ = find_beads(img)
                meta.setdefault("repicks", []).append({"step": i, "beads": beads})
                log({"repick": len(beads)})
                if not beads:
                    raise RuntimeError("repick: no reference bead found")
                rec = Recorder(cam, beads, out)
                rec.start()
        meta["result"] = "ok"
        print(f"RESULT ok: {len(steps)} steps, {len(beads)} beads, gaps {rec.gaps if rec else None} -> {out}", flush=True)
        return 0
    finally:
        if rec:
            rec.stream(None)
            rec.running = False
            rec.join(10)
        cam.close()                                 # camera back to its .icd state; motors are rig_session's cleanup
        meta.update({"gaps": rec.gaps if rec else None, "finished": time.strftime("%Y-%m-%d %H:%M:%S")})
        dump(meta, os.path.join(out, "meta.json"))
        ev.close()


def snap(args):
    if not os.environ.get("RIGLOCK_TOKEN"):
        raise SystemExit("REFUSED: rig runs only inside V6 tools/rig_session.py (no RIGLOCK_TOKEN)")
    from mtpy.devices.imaqdx import ImaqdxCamera
    cam = ImaqdxCamera()
    try:
        cam.open()
        rb = cam.readback()
        cam.start()
        _, _, img = cam.frame(5)
    finally:
        cam.close()
    os.makedirs(args.out, exist_ok=True)
    np.save(os.path.join(args.out, "frame.npy"), img)
    beads, found = find_beads(img)
    dump({"camera": rb, "beads": beads, "n_spots": len(found["spots"]), "rejected": found["rejected"]},
         os.path.join(args.out, "beads.json"))
    print(f"RESULT ok: {len(beads)} beads of {len(found['spots'])} spots; mean grey {img.mean():.1f}; {rb}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("show", "run", "snap"))
    ap.add_argument("--plan", choices=("static", "field", "magnet", "rotation", "exposure", "drift", "zscan", "zscan_field", "zfine50", "zfine20", "exposure2", "search", "zfine_at", "tether"))
    ap.add_argument("--out", default=r"G:\l2s_rig_data\2026-10-26_refbead")
    ap.add_argument("--exposure-us", type=float, default=1909.0)   # = the .icd auto value; 3000 would saturate (max grey 200 at 1909)
    ap.add_argument("--beads", help="beads.json from `snap` (default: find them in the first frame)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--min-sep", type=float, help="minimum distance to the nearest other spot (px)")
    ap.add_argument("--at-um", default="0,0", help="zfine_at: field offset dx,dy in um from the session start")
    ap.add_argument("--magnet-mm", type=float, default=36.4, help="tether: the measurement clamp position (about 7 pN)")
    ap.add_argument("--calib-mm", default="38,36.4", help="tether: calibration positions, visited high to low")
    ap.add_argument("--exposures", default="1909,1000,500", help="tether: exposure times in us")
    ap.add_argument("--no-fine", action="store_true", help="tether: skip the 50 nm scans")
    a = ap.parse_args()
    global AT_UM, MIN_SEP, TETHER_MAGNET_MM, TETHER_CALIB_MM, TETHER_EXPOSURES_US, TETHER_FINE
    TETHER_MAGNET_MM = a.magnet_mm
    TETHER_CALIB_MM = tuple(sorted({float(v) for v in a.calib_mm.split(",")} | {a.magnet_mm}, reverse=True))
    TETHER_EXPOSURES_US = tuple(float(v) for v in a.exposures.split(","))
    TETHER_FINE = not a.no_fine
    AT_UM = tuple(float(v) for v in a.at_um.split(","))
    MIN_SEP = a.min_sep if a.min_sep is not None else MIN_SEP
    if a.cmd == "show":
        for i, s in enumerate(plan(a.plan, a.exposure_us)):
            print(i, s)
        return 0
    return run(a) if a.cmd == "run" else snap(a)


if __name__ == "__main__":
    sys.exit(main())
