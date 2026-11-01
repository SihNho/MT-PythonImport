"""Rig 2026-11-01 (owner: check what comes back after a sudden program end): connect MT (camera + motors), record a run,
then wait to be killed (taskkill /F) - never exits on its own. The partner rig_kill_restart.py runs afterwards."""
import os
import sys
import time

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
from mtpy import api
from mtpy.api import events

OUT = r"G:\l2s_rig_data\2026-11-01_kill_restart"
os.makedirs(OUT, exist_ok=True)
with events.as_caller("script:rig-kill-victim@1"):
    st = api.devices.connect({"backend": "real-motors", "mode": "MT"})
    print(time.strftime("%H:%M:%S"), "pid", os.getpid(), "connect:", {k: v["state"] for k, v in st.items()}, flush=True)
    print("magnet:", api.devices.info("magnet").get("controller_limits"), "position", api.magnet.position(), flush=True)
    api.acq.start(record=True, name="victim", folder=OUT)
    print(time.strftime("%H:%M:%S"), "recording; waiting to be killed", flush=True)
    print("READY", flush=True)
    while True:
        time.sleep(1)
        s = api.acq.status()
        print(time.strftime("%H:%M:%S"), "frames", s["frames_received"], "recording", s["recording"], flush=True)
