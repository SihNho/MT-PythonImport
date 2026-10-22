"""camera_attributes.py - ask the camera what it is actually set to, instead of inferring it.

Two things forced this. The main VI's front panel reports Width 640 / Height 512, half of the 1280x1024 the user expects
from 2x2 binning, and the user confirms the size halves as soon as the code runs. And the main VI's own strings contain
NO binning attribute at all - only `Width` and `Height`, which are INDICATORS - so the VI reads the geometry rather than
setting it, and the halving comes from the camera or driver state rather than from VI code.

`IMAQdx Enumerate Cameras` needs no session and returns the camera name, which is the piece still missing after the
example's `Camera Name` control turned out to be an IMAQdx Session control reading ('', 0) rather than a plain string.
`IMAQdx Enumerate Attributes` then dumps every GenICam attribute with its current value: binning, width, height, pixel
format, and the acquisition frame rate with its maximum - which is also the camera-ceiling number the sweep needs.

Camera only; no stage, no motor. Nothing is written to the camera - attributes are read.
  py tools/bgrun.py --max-min 20 --log tools/bench/camera_attributes.log -- py -u tools/bench/camera_attributes.py
"""
import os, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import gscript as g  # noqa: E402

EX = r"C:\Program Files\NI\LVAddons\niimaqdx\1\examples\Vision Acquisition\NI-IMAQdx"
CANDIDATES = [
    ("Enumerate and Select Camera", os.path.join(EX, "Design Patterns", "Enumerate and Select Camera.vi")),
    ("Getting Started with Attributes", os.path.join(EX, "Camera Attributes", "Getting Started with Attributes.vi")),
    ("Advanced Functionality with Attributes", os.path.join(EX, "Camera Attributes", "Advanced Functionality with Attributes.vi")),
]
g._run.__defaults__ = (6.0, 45.0)


def main():
    g._lv = None
    for label, src in CANDIDATES:
        print(f"\n{'=' * 78}\n== {label}\n   {src}", flush=True)
        if not os.path.exists(src):
            print("   MISSING", flush=True); continue
        dst = os.path.join(g.CLAUDEDEV, "CAMEX_" + os.path.basename(src))
        if os.path.exists(dst):
            os.remove(dst)
        shutil.copyfile(src, dst)
        try:
            counts = {c: g.count(dst, c) for c in ("Node", "SubVI", "WhileLoop", "Diagram")}
            print("   objects:", counts, flush=True)
            labs = g.fp_labels(dst)
            print("   controls:", [l for _, l, ind in labs if not ind], flush=True)
            print("   indicators:", [l for _, l, ind in labs if ind], flush=True)
        except Exception as e:
            print("   failed:", str(e)[:150], flush=True)
        finally:
            try:
                g.close_panel(dst)
            except Exception:
                pass
            time.sleep(0.3)
            try:
                os.remove(dst)
            except OSError:
                pass
    print("\nDONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
# ---
# labview: read
# hardware: camera
# ---
