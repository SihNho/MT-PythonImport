"""imaqdx_ctypes.py - talk to the camera through niimaqdx.dll directly, with no LabVIEW in the way.

Why not LabVIEW: three attempts to drive NI's example VIs over COM all ended the same way. Their `Camera Name` control
is an IMAQdx Session control that reads back as ('', 0) rather than a string, so it could not be set from Python, and
each run with an empty name popped a modal dialog that blocked every later COM call until LabVIEW was killed. The C API
has no front panel and therefore no dialog.

What this answers, all of it currently guesswork:
  * the camera's IMAQdx interface NAME (the "cam0"-style string every other tool needs);
  * what the camera is ACTUALLY set to - binning, Width, Height, OffsetX, OffsetY, PixelFormat - which decides whether
    the user's "first run halves the image, second run restores it" is a ROI clamp (field of view shrinks, nm-per-pixel
    unchanged, calibration safe) or a binning change (nm-per-pixel doubles, so the first run's distances are wrong by
    2x, which is a correctness problem rather than a performance one);
  * the acquisition frame rate and its maximum at those settings, i.e. the ceiling behind the 150 Hz question.

SAFETY: read-only. Attributes are READ, never written, and no acquisition is started. Opening a camera session does not
move or reconfigure anything.
  py tools/bgrun.py --max-min 10 --log tools/bench/imaqdx_ctypes.log -- py -u tools/bench/imaqdx_ctypes.py
"""
import ctypes as C
import os, sys

MAXSTR = 512
dx = C.windll.LoadLibrary("niimaqdx.dll")

# value types, from NI-IMAQdx.h
U32, I64, F64, STR, ENUM, BOOL, CMD, BLOB = range(8)
VIS = {"Simple": 0x00001000, "Intermediate": 0x00002000, "Advanced": 0x00004000}
WANT = ("width", "height", "offsetx", "offsety", "binning", "pixelformat", "framerate",
        "payload", "devicemodel", "devicevendor", "sensor", "decimation", "exposure", "reverse")


class CameraInformation(C.Structure):
    _fields_ = [("Type", C.c_uint32), ("Version", C.c_uint32), ("Flags", C.c_uint32),
                ("SerialNumberHi", C.c_uint32), ("SerialNumberLo", C.c_uint32), ("BusType", C.c_uint32),
                ("InterfaceName", C.c_char * MAXSTR), ("VendorName", C.c_char * MAXSTR),
                ("ModelName", C.c_char * MAXSTR), ("CameraFileName", C.c_char * MAXSTR),
                ("CameraAttributeURL", C.c_char * MAXSTR)]


class AttributeInformation(C.Structure):
    _fields_ = [("Type", C.c_uint32), ("Readable", C.c_uint32), ("Writable", C.c_uint32),
                ("Name", C.c_char * MAXSTR)]


class EnumItem(C.Structure):
    _fields_ = [("Value", C.c_uint32), ("Reserved", C.c_uint32), ("Name", C.c_char * MAXSTR)]


def err(code, what):
    if code != 0:
        buf = C.create_string_buffer(MAXSTR)
        try:
            dx.IMAQdxGetErrorString(C.c_int32(code), buf, C.c_uint32(MAXSTR))
            msg = buf.value.decode("latin-1", "replace")
        except Exception:
            msg = ""
        print(f"   !! {what}: error {code} (0x{code & 0xFFFFFFFF:08X}) {msg}", flush=True)
        return True
    return False


def enumerate_cameras():
    n = C.c_uint32(0)
    dx.IMAQdxEnumerateCameras(None, C.byref(n), C.c_uint32(1))
    print(f"cameras connected: {n.value}", flush=True)
    if not n.value:
        return []
    arr = (CameraInformation * n.value)()
    if err(dx.IMAQdxEnumerateCameras(arr, C.byref(n), C.c_uint32(1)), "EnumerateCameras"):
        return []
    out = []
    for c in arr[:n.value]:
        d = {k: getattr(c, k).decode("latin-1", "replace")
             for k in ("InterfaceName", "VendorName", "ModelName", "CameraFileName")}
        d["Serial"] = f"{c.SerialNumberHi:08X}{c.SerialNumberLo:08X}"
        out.append(d)
        print(f"   {d['InterfaceName']!r}: {d['VendorName']} {d['ModelName']} serial {d['Serial']}", flush=True)
    return out


def read_attr(sess, name, atype):
    """Read one attribute using the type the enumeration reported."""
    try:
        if atype == U32:
            v = C.c_uint32(); dx.IMAQdxGetAttribute(sess, name.encode(), C.c_uint32(U32), C.byref(v)); return v.value
        if atype == I64:
            v = C.c_int64(); dx.IMAQdxGetAttribute(sess, name.encode(), C.c_uint32(I64), C.byref(v)); return v.value
        if atype == F64:
            v = C.c_double(); dx.IMAQdxGetAttribute(sess, name.encode(), C.c_uint32(F64), C.byref(v)); return v.value
        if atype == BOOL:
            v = C.c_uint32(); dx.IMAQdxGetAttribute(sess, name.encode(), C.c_uint32(BOOL), C.byref(v)); return bool(v.value)
        if atype == STR:
            b = C.create_string_buffer(MAXSTR)
            dx.IMAQdxGetAttribute(sess, name.encode(), C.c_uint32(STR), b); return b.value.decode("latin-1", "replace")
        if atype == ENUM:
            it = EnumItem(); dx.IMAQdxGetAttribute(sess, name.encode(), C.c_uint32(ENUM), C.byref(it))
            return it.Name.decode("latin-1", "replace")
    except Exception as e:
        return f"(read failed: {e})"
    return "(unsupported type %d)" % atype


def main():
    cams = enumerate_cameras()
    if not cams:
        print("no camera enumerated - is it connected and not held by another process?", flush=True)
        return 3
    name = cams[0]["InterfaceName"]
    sess = C.c_uint32(0)
    if err(dx.IMAQdxOpenCamera(name.encode(), C.c_uint32(0), C.byref(sess)), f"OpenCamera({name})"):
        return 4
    print(f"\nopened {name!r}, session {sess.value}", flush=True)
    try:
        for vis_name, vis in VIS.items():
            n = C.c_uint32(0)
            dx.IMAQdxEnumerateAttributes2(sess, None, C.byref(n), b"", C.c_uint32(vis))
            if not n.value:
                continue
            arr = (AttributeInformation * n.value)()
            if err(dx.IMAQdxEnumerateAttributes2(sess, arr, C.byref(n), b"", C.c_uint32(vis)), "EnumerateAttributes2"):
                continue
            print(f"\n=== visibility {vis_name}: {n.value} attributes; the relevant ones ===", flush=True)
            rows = []
            for a in arr[:n.value]:
                nm = a.Name.decode("latin-1", "replace")
                if not any(k in nm.lower() for k in WANT):
                    continue
                val = read_attr(sess, nm, a.Type) if a.Readable else "(not readable)"
                rows.append((nm, val, bool(a.Writable)))
            for nm, val, w in rows:
                print(f"   {'W' if w else ' '} {nm:<62} = {val!r}", flush=True)
            if vis_name == "Advanced":
                out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imaqdx_attributes.txt")
                with open(out, "w", encoding="utf-8") as f:
                    for a in arr[:n.value]:
                        nm = a.Name.decode("latin-1", "replace")
                        v = read_attr(sess, nm, a.Type) if a.Readable else "(not readable)"
                        f.write(f"{'W' if a.Writable else ' '} {nm} = {v!r}\n")
                print("   full attribute list ->", out, flush=True)
    finally:
        dx.IMAQdxCloseCamera(sess)
        print("\nclosed the camera session", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
# ---
# labview: none
# hardware: camera
# ---
