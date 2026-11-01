"""`python -m mtpy.engine [--host H --port P] [--config DIR]`: run the engine until a client calls `engine.exit`
(or Ctrl+C). --config: the rig config folder (safety profile) to use instead of the repository's."""
import argparse
import os
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--config", default=None)
    a = p.parse_args()
    # rig 2026-11-01 (0029 step 3): numba on every core made the 256-bead frame wait for the thread the GUI's
    # drawing displaced (p50 6.4 -> 11.0 ms); two cores left to the GUI and the OS keep it at 7.4 ms either way
    os.environ.setdefault("NUMBA_NUM_THREADS", str(max(1, (os.cpu_count() or 4) - 2)))
    if a.config:
        from mtpy.api import safety
        safety.CONFIG = Path(a.config)
        safety.load_active()
    from mtpy.engine import serve
    try:
        serve((a.host, a.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
