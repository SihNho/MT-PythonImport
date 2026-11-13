"""The bench of decision 0031 (owner 2026-11-07, after the night's bench: "design v2 and, if possible, bench it at the
current position, the same position reference as the bench"): the method versions spline_v2 / phase_spline_v2 on the
four beads left (three in the half ROI), the LUT at Cal+ and the drift hold as on 11-07 (rig_bench_1107.py).

Per rate: `w` = one current_v1 numba run that keeps every frame's bead windows (rig_accuracy WINDOWS=1) for the fair
comparison offline (tools/offline_windows.py: every version on numba and the FP32 GPU on the same frames); `v` = the
v2 methods x numba / gpu x 4 (3) and 50 beads for the throughput, drops and the accuracy columns beside the 11-07 tables.

  py tools/rig_bench_v2.py [block ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\tools")
import rig_bench_matrix as R

COMMON = {"PICK_IDS": "1,2,3,4", "RING_PX": "", "CAL_MAGNET_MM": "37.4", "MAGNET_MM": "30,10,0", "HOLD_S": "2"}
ROI = {"ROI": "360,200,640,512", "PICK_IDS": "1,2,3"}
WINDOWS = {"WINDOWS": "1", "ZMETHODS": "current_v1", "EXEC": "numba"}
V2 = {"ZMETHODS": "spline_v2,phase_spline_v2"}
R.BLOCKS = []
for rate, fps, extra, n in (("90", "90", {}, "4"), ("150", "150", {}, "4"), ("248", "max", {}, "4"), ("555", "max", ROI, "3")):
    R.BLOCKS += [(f"w{rate}", "rig_accuracy.py", {**COMMON, **extra, **WINDOWS, "FPS": fps, "COUNTS": n}),
                 (f"v{rate}", "rig_accuracy.py", {**COMMON, **extra, **V2, "FPS": fps, "COUNTS": f"{n},50"})]
R.DATA = r"G:\l2s_rig_data\2026-11-07c_"
R.LOGS = Path(r"G:\Codes\LabVIEW2Scr\bench_out\v2\matrix")

if __name__ == "__main__":
    R.main()
