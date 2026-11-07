"""Put the field back after a bench walked off (2026-11-07 04:00: a false pick lock built a LUT 40 px off and the drift
hold then moved the stage 26 um and the focus 7.7 um): move the stage and the focus to the given values, take a frame,
find the owner's picks from the given picks file (templates checked) and report. Nothing else moves; no LUT.

  STAGE_MM=x,y FOCUS_UM=z [PICKS=<json>] [PICK_IDS=1,2,3] py tools/rig_field_restore.py
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_accuracy as A
import rig_refbead_track as T

from mtpy import api
from mtpy.api import events

say = T.say
OUT = os.environ.get("OUT", r"G:\l2s_rig_data\restore_" + time.strftime("%m%d_%H%M"))


def main():
    x, y = (float(v) for v in os.environ["STAGE_MM"].split(","))
    z = float(os.environ["FOCUS_UM"])
    with open(os.environ.get("PICKS", A.LATEST), encoding="utf-8") as f:
        picks = json.load(f)["picks"]
    os.makedirs(OUT, exist_ok=True)
    with events.as_caller("script:rig-field-restore@1"):
        T.connect()
        try:
            say(f"stage {api.stage.position()} -> {(x, y)}: read back {api.stage.move_to(x, y).wait(30)}")
            say(f"focus {api.focus.position():.3f} -> {z}: read back {api.focus.move_to(z).wait(10)}")
            api.acq.start(record=False, name="restore")
            try:
                img = api.acq.average(10, timeout_s=10)
            finally:
                api.acq.stop()
            np.save(os.path.join(OUT, "frame.npy"), np.clip(np.rint(img), 0, 255).astype(np.uint8))
            templates = np.load(A.TEMPLATES) if os.path.exists(A.TEMPLATES) else {}
            try:
                xy = A.find_picks(img, [np.array(picks[i - 1]) for i in A.PICK_IDS],
                                  templates=[templates.get(f"p{i}") for i in A.PICK_IDS])
                say("RESULT picks found:", np.round(xy, 1).tolist())
            except RuntimeError as e:
                say("RESULT picks NOT found:", e)
        finally:
            api.devices.disconnect()
            say("RESULT disconnect clean")


if __name__ == "__main__":
    main()
