"""Put the rig back where an interrupted bench left it (2026-11-03 20:14: the PC lost power 13 s into a GUI bench run,
during the focus steps; owner 2026-11-04: "clean up the stale lock, finish before the experiment"). Reads the stage,
magnet and the beads' ring radius, moves the stage to STAGE_MM (the last completed run's start, absolute ASI mm),
the magnet to MAGNET_MM and the focus to the bench focus (ring radius RING_PX through rig_accuracy.focus_match),
and disconnects. Every move goes through the API (gate, lock); nothing else is touched.
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_accuracy as A
from rig_refbead_track import say

from mtpy import api
from mtpy.api import events, zscan

STAGE_MM = tuple(float(v) for v in os.environ.get("STAGE_MM", "3.0059,-0.8554").split(","))
MAGNET_MM = float(os.environ.get("MAGNET_MM", "0"))


def main():
    with open(A.LATEST, encoding="utf-8") as f:
        picks = json.load(f)["picks"]
    with events.as_caller("script:rig-restore@1"):
        st = api.devices.connect({"backend": "real-motors", "mode": "MT-TIRF"})
        say("connected:", {k: v["state"] for k, v in st.items()})
        try:
            xy = api.stage.position()
            mag = api.magnet.position()
            say(f"RESULT found: stage {xy} mm (target {STAGE_MM}), magnet {mag:.2f} mm (target {MAGNET_MM}), "
                f"camera {api.devices.info('camera')['settings']}")
            if max(abs(xy[0] - STAGE_MM[0]), abs(xy[1] - STAGE_MM[1])) > 0.0003:
                say("stage ->", api.stage.move_to(*STAGE_MM).wait(10))
            if abs(mag - MAGNET_MM) > 0.05:
                say("magnet ->", api.magnet.move_to(MAGNET_MM).wait(30))
            api.acq.start(record=False, name="restore")
            try:
                img = api.acq.average(10, timeout_s=10)
                xy_b = A.find_picks(img, picks)
                r0 = float(np.median([A.ring_radius(zscan.bead_profile(img, x, y, 120)[2]) for x, y in xy_b[1:]]))
                say(f"RESULT ring radius now {r0:.2f} px (bench focus 12.2; owner's rough focus of 19:06 was 13.8)")
                r, z = A.focus_match(xy_b[1:])
                say(f"RESULT focus matched: ring {r:.2f} px, moved {z:+.3f} um from where it stood")
            finally:
                api.acq.stop()
            say(f"RESULT now: stage {api.stage.position()} mm, magnet {api.magnet.position():.2f} mm")
        finally:
            api.devices.disconnect()
            say(f"RESULT disconnected; lock {api.rig.status()}")


if __name__ == "__main__":
    main()
