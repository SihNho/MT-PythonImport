"""One averaged frame of the current channel and the isolated ring beads on it, numbered for the owner to pick from
(owner 2026-11-03: a new channel, "reference beads and magnetic beads together"). Template: a bead window from the
11-01 frame (the owner's bead 2 at the owner's focus), normalised cross-correlation over the frame, local maxima
away from the frame edge (the 120-px tracking window) and from each other. Output in OUT: frame.npy,
candidates_numbered.png, candidates.json. Camera only (the rig lock is taken by api.devices.connect).

    python tools/rig_candidates.py            # on the rig
    FRAME=path.npy python tools/rig_candidates.py   # offline, on a saved frame
"""
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")

OUT = os.environ.get("OUT", r"G:\l2s_rig_data\2026-11-03_candidates")
TEMPLATE_FRAME, TEMPLATE_XY = r"G:\l2s_rig_data\2026-11-01_accuracy\frame.npy", (693.61, 701.25)   # owner's bead 2, 11-01 focus
MARGIN, APART, N_MAX, THRESH = 80, 70, 20, float(os.environ.get("THRESH", "0.55"))


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def ncc(img, tpl):
    """Normalised cross-correlation of tpl over img (same-size output, zero at the borders)."""
    img = img.astype(np.float64)
    tpl = tpl.astype(np.float64) - tpl.mean()
    h, w = tpl.shape
    ones = np.ones_like(tpl)
    f = np.fft.rfft2(img)
    cross = np.fft.irfft2(f * np.conj(np.fft.rfft2(tpl, img.shape)), img.shape)
    local_sum = np.fft.irfft2(f * np.conj(np.fft.rfft2(ones, img.shape)), img.shape)
    local_sq = np.fft.irfft2(np.fft.rfft2(img ** 2) * np.conj(np.fft.rfft2(ones, img.shape)), img.shape)
    var = np.maximum(local_sq - local_sum ** 2 / (h * w), 1e-9)
    out = cross / np.sqrt(var * (tpl ** 2).sum())
    return np.roll(out, (h // 2, w // 2), axis=(0, 1))     # peak at the template's centre


def candidates(frame):
    tpl_img = np.load(TEMPLATE_FRAME)
    tx, ty = round(TEMPLATE_XY[0]), round(TEMPLATE_XY[1])
    tpl = tpl_img[ty - 20:ty + 20, tx - 20:tx + 20]
    c = ncc(frame, tpl)
    W = frame.shape[1]
    c[:MARGIN], c[-MARGIN:], c[:, :MARGIN], c[:, -MARGIN:] = -1, -1, -1, -1
    picks = []
    flat = np.argsort(c.ravel())[::-1]
    for idx in flat[:5000]:
        y, x = divmod(int(idx), W)
        if c[y, x] < THRESH:
            break
        if all(np.hypot(x - px, y - py) > APART for px, py, _ in picks):
            # a neighbour peak within the window means a cluster: skip (the cross-correlation of clusters is high too)
            win = c[max(0, y - 35):y + 36, max(0, x - 35):x + 36]
            if (win > 0.45).sum() > 25:
                continue
            picks.append((x, y, float(c[y, x])))
        if len(picks) >= N_MAX:
            break
    return picks


def magnet_check(frame, picks):
    """Ring radius of every candidate at the magnet's current position and 20 mm away (then back): a tethered magnetic
    bead changes its z, so its ring; a stuck reference bead does not. Acquisition must be running."""
    from rig_accuracy import ring_radius

    from mtpy import api
    from mtpy.api import zscan
    p0 = api.magnet.position()
    p1 = p0 + 20.0 if p0 < 15 else p0 - 20.0
    say(f"magnet check: {p0:.1f} -> {p1:.1f} mm")
    r0 = [ring_radius(zscan.bead_profile(frame, x, y, 120)[2]) for x, y, _ in picks]
    api.magnet.move_to(p1).wait(30)
    time.sleep(1.0)
    img = api.acq.average(10, timeout_s=10)
    r1 = [ring_radius(zscan.bead_profile(img, x, y, 120)[2]) for x, y, _ in picks]
    api.magnet.move_to(p0).wait(30)
    say(f"magnet back at {api.magnet.position():.1f} mm")
    for i, (a, b) in enumerate(zip(r0, r1), 1):
        say(f"  {i:2d}: ring {a:.2f} -> {b:.2f} px  ({b - a:+.2f}{'  MAGNETIC?' if abs(b - a) > 0.3 else ''})")
    return r0, r1


def draw(frame, picks, path):
    im = Image.fromarray(frame).convert("RGB")
    d = ImageDraw.Draw(im)
    for i, (x, y, s) in enumerate(picks, 1):
        d.ellipse([x - 30, y - 30, x + 30, y + 30], outline=(255, 60, 60), width=2)
        d.text((x + 32, y - 10), f"{i} ({s:.2f})", fill=(255, 255, 0))
    im.save(path)


def main():
    os.makedirs(OUT, exist_ok=True)
    if os.environ.get("FRAME"):
        frame = np.load(os.environ["FRAME"])
    else:
        from mtpy import api
        from mtpy.api import events
        with events.as_caller("script:rig-candidates@1"):
            api.devices.connect({"backend": "real-motors", "mode": "MT-TIRF"})
            try:
                api.acq.start(record=False, name="candidates")
                try:
                    frame = np.clip(np.rint(api.acq.average(10, timeout_s=10)), 0, 255).astype(np.uint8)
                    if os.environ.get("MAGNET_CHECK"):      # owner 2026-11-03: "pull with the magnet and watch the pattern"
                        magnet_check(frame, candidates(frame))
                finally:
                    api.acq.stop()
            finally:
                api.devices.disconnect()
                say(f"disconnected; lock {api.rig.status()}")
        np.save(os.path.join(OUT, "frame.npy"), frame)
    picks = candidates(frame)
    draw(frame, picks, os.path.join(OUT, "candidates_numbered.png"))
    with open(os.path.join(OUT, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump([{"n": i, "x": x, "y": y, "score": s} for i, (x, y, s) in enumerate(picks, 1)], f, indent=1)
    say(f"{len(picks)} candidates -> {OUT}")
    for i, (x, y, s) in enumerate(picks, 1):
        say(f"  {i:2d}: ({x}, {y})  score {s:.2f}")


if __name__ == "__main__":
    main()
