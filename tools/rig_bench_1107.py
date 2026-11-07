"""The bench of 2026-11-07 (owner, before sleeping: "run the bench while I am away; improve the GPU code first; hold a
reference point against the thermal drift"; then, after the side chat and decision 0030: "stop the bench, apply the
changes, redo the overlapping tests and run the ones never seen"). The owner's six picked beads
(G:\\l2s_rig_data\\bead_picks_latest.json, located on the frame of 01:20), the LUT made with the magnet at Cal+
(37.4 mm) and centred on the current focus, the drift hold before every run's steps (rig_accuracy.hold), the method
names versioned and the GPU executor FP32 (`gpu`; `gpu64` is the FP64 baseline kernel).

Two stages (0030): stage 1 screens the method versions x executors in the standard condition (m90: 90 Hz, 20 beads,
3 methods x numba / gpu / gpu64); stage 2 expands over rate x bead count x ROI for the zero-drop boundary (numba and
gpu), the rate-matched LUT frame counts, the 1 um/s focus blocks and the GUI client at the four rates. Blocks run as
rig_bench_matrix runs them (logs bench_out/1107/matrix, data G:\\l2s_rig_data\\2026-11-07b_<block>; a STOP file ends
the run after the current block; a block whose data folder exists is skipped). The two blocks of the first attempt
(2026-11-07_s90 / s150: the FP64 kernel before the versions) stay as the "cuda fp64" baseline in the report.

  py tools/rig_bench_1107.py [block ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_bench_matrix as R

# 03:58: the owner's pick 5 came loose at ~03:35 (s248 run 4; lost in 37% of its frames from then on) and the blocks
# after s248 failed on it; 04:00: pick 3 came loose too, the pick search locked 40 px off (n248: a LUT on the fringes,
# the hold walked the stage 26 um and the focus 7.7 um; the field restored at 04:15 by rig_field_restore.py). The
# picks file now holds the owner's 1, 2, 4, 6 as picks 1-4 (the 6-bead file kept as bead_picks_6_before_bead5_lost.json);
# m90 / s90 / s150 / s248 ran on the six, the rest on these four (three in the ROI).
COMMON = {"PICK_IDS": "1,2,3,4", "RING_PX": "", "CAL_MAGNET_MM": "37.4", "MAGNET_MM": "30,10,0", "HOLD_S": "2"}
ROI = {"ROI": "360,200,640,512", "PICK_IDS": "1,2,3"}           # the owner's 1, 2, 4 with >= 112 px of margin; 6 is outside
METHODS = ("current_v1", "spline_v1", "phase_spline_v1")
CASES = ",".join(f"{n}:{ex}:{zm}" for n in (4, 50) for zm in METHODS for ex in ("numba", "gpu"))
CASES3 = ",".join(f"{n}:{ex}:{zm}" for n in (3, 50) for zm in METHODS for ex in ("numba", "gpu"))
GUI = {"CLIENT": "1", "STEPS": "1", "MAKE_CAL": "1", "CONDITIONS": "normal", "CASES": CASES}
R.BLOCKS = [
    # stage 1: the standard condition, every method version x executor x precision
    ("m90", "rig_accuracy.py", {**COMMON, "FPS": "90", "COUNTS": "20", "EXEC": "numba,gpu,gpu64"}),         # ran on 6
    # stage 2: rate x bead count (the zero-drop boundary), numba and the FP32 GPU
    ("s90", "rig_accuracy.py", {**COMMON, "FPS": "90", "COUNTS": "6,50,100,200"}),                           # ran on 6
    ("s150", "rig_accuracy.py", {**COMMON, "FPS": "150", "COUNTS": "6,50,100,200"}),                         # ran on 6
    ("s248", "rig_accuracy.py", {**COMMON, "FPS": "max", "COUNTS": "6,50,100,200"}),                         # ran on 6
    ("s555", "rig_accuracy.py", {**COMMON, **ROI, "FPS": "max", "COUNTS": "3,20,50,100"}),
    ("n150", "rig_accuracy.py", {**COMMON, "FPS": "150", "COUNTS": "4", "N_AVG": "17"}),
    ("n248", "rig_accuracy.py", {**COMMON, "FPS": "max", "COUNTS": "4", "N_AVG": "28"}),
    ("n555", "rig_accuracy.py", {**COMMON, **ROI, "FPS": "max", "COUNTS": "3", "N_AVG": "62"}),
    *[(f"p{nm}_v1um", "rig_accuracy.py",
       {**COMMON, "FPS": "90", "COUNTS": "4", "HOLD_S": "3", "STEP_NM": str(nm), "SPEED_MM_S": "0.001"})
      for nm in (20, 50, 100)],
    ("ppm1_v1um", "rig_accuracy.py", {**COMMON, "FPS": "90", "COUNTS": "4", "SPEED_MM_S": "0.001"}),
    ("g90", "gui_rig_isolate.py", {**COMMON, **GUI, "FPS": "90"}),
    ("g150", "gui_rig_isolate.py", {**COMMON, **GUI, "FPS": "150"}),
    ("g248", "gui_rig_isolate.py", {**COMMON, **GUI, "FPS": "max"}),
    ("g555", "gui_rig_isolate.py", {**COMMON, **GUI, **ROI, "FPS": "max", "CASES": CASES3}),
]
R.DATA = r"G:\l2s_rig_data\2026-11-07b_"
R.LOGS = Path(r"G:\Codes\LabVIEW2Scr\bench_out\1107\matrix")

if __name__ == "__main__":
    R.main()
