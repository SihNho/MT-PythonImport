"""`python -m mtpy.gui [--backend sim|real] [--fixture DIR] [--out DIR] [--sim-dev] [--screenshot PNG]`

--backend   sim (default): every device simulated; real: the JAI camera (IMAQdx) and the Andor iXon EMCCD (SDK2), motors simulated
            (phase 6); real-motors: camera + PI / ASI / Autonics through the motion gate (phase 7). Both real
            backends take the shared rig lock themselves at Connect (decision 0026).

--fixture   folder of recorded frames (img*.tif) and a `cal*` file for the simulated camera (default: $MTPY_DATA/test)
--out       folder for run files (default: <cwd>/runs)
--sim-dev   SIMULATOR ONLY: work on a copy of config/ whose focus and rotor limits are TEST values (as the tests do),
            so the whole flow - z scan included - runs without the rig; the shipped config is never written
--screenshot  save a picture of the window after 3 s and quit (smoke test)
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TEST_LIMITS = {"magnet_speed_mm_s": (0.0, 10.0), "rotor_turns": (-5.0, 5.0), "rotor_speed_turns_s": (0.0, 10.0),
               "focus_z_um": (-50.0, 50.0)}       # = tests/test_devices.py TEST_LIMITS


def sim_dev_config():
    """A temporary copy of the shipped config with TEST-ONLY limits; returns its path (never the repository's)."""
    from mtpy.api import safety
    src = Path(safety.CONFIG).resolve()
    dst = Path(tempfile.mkdtemp(prefix="mtpy_gui_simdev_")) / "config"
    shutil.copytree(src, dst)
    path = dst / "safety_profile.json"
    p = json.loads(path.read_text(encoding="utf-8"))
    for q, (lo, hi) in TEST_LIMITS.items():
        p["limits"][q].update(min=lo, max=hi, verified=True, source="TEST ONLY (mtpy.gui --sim-dev)")
    p["unverified"], p["by"] = [], "TEST ONLY (mtpy.gui --sim-dev)"
    path.write_text(json.dumps(p), encoding="utf-8")
    safety.CONFIG = dst
    safety.load_active()
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mtpy.gui", description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixture", default=os.environ.get("MTPY_FIXTURE") or str(Path(os.environ.get(
        "MTPY_DATA", r"G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch")) / "test"))
    ap.add_argument("--out", default=str(Path.cwd() / "runs"))
    ap.add_argument("--sim-dev", action="store_true")
    ap.add_argument("--backend", choices=("sim", "real", "real-motors"), default="sim")
    ap.add_argument("--screenshot", default=None)
    a = ap.parse_args(argv)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .app import MainWindow
    cfg = sim_dev_config() if a.sim_dev else None
    app = QApplication(sys.argv[:1])
    w = MainWindow(fixture=a.fixture, out=a.out, sim_dev=cfg, backend=a.backend)
    w.show()
    if a.screenshot:
        def shot():
            w.grab().save(a.screenshot)
            w.close()
            app.quit()
        QTimer.singleShot(3000, shot)
    rc = app.exec()
    if cfg is not None:
        shutil.rmtree(cfg.parent, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
