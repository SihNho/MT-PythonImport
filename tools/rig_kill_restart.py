"""After rig_kill_victim.py was killed: what the restarted program sees. Lock status, the connect attempt (expected:
refused, STALE lock - the rules never take it over here), the run file the victim left, the COM ports."""
import glob
import json
import os
import sys
import time

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
sys.path.insert(0, r"G:\Codes\rig")
import riglock

from mtpy import api
from mtpy.api import events

OUT = r"G:\l2s_rig_data\2026-11-01_kill_restart"
print("riglock:", json.dumps(riglock.status(), default=str))
with events.as_caller("script:rig-kill-restart@1"):
    t0 = time.monotonic()
    try:
        st = api.devices.connect({"backend": "real-motors", "mode": "MT"})
        print(f"RESULT connect went through in {time.monotonic() - t0:.1f} s:", {k: v["state"] for k, v in st.items()})
        print("magnet:", api.devices.info("magnet").get("controller_limits"), "position", api.magnet.position())
        api.devices.disconnect()
        print("RESULT disconnected; lock", api.rig.status())
    except Exception as e:  # noqa: BLE001
        print(f"RESULT connect refused after {time.monotonic() - t0:.1f} s: {type(e).__name__}: {e}")
    print("devices:", api.devices.status())
for f in sorted(glob.glob(os.path.join(OUT, "*"))):
    print("left file:", os.path.basename(f), os.path.getsize(f), "bytes")
try:
    import h5py
    with h5py.File(os.path.join(OUT, "victim.h5"), "r") as h:
        n = h["frames"].shape[0] if "frames" in h else None
        print("RESULT victim.h5 opens; frames rows:", n, "; keys:", list(h.keys()))
except Exception as e:  # noqa: BLE001
    print(f"RESULT victim.h5: {type(e).__name__}: {e}")
