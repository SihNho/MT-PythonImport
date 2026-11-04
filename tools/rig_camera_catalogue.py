"""The JAI's attribute catalogue as the driver reports it (owner 2026-11-04: "list them from NI MAX"): connect, read
`api.camera.catalogue()` and every readable value, write docs/manuals/camera-jai-attributes.md, round-trip one
harmless attribute (TriggerMode set to its own value) through api.camera.set_attribute, disconnect. Camera only;
no motor moves.
"""
import os
import sys
import time

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")

from mtpy import api
from mtpy.api import events

OUT = os.environ.get("OUT", r"G:\Codes\LabVIEW2Scr\docs\manuals\camera-jai-attributes.md")


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main():
    with events.as_caller("script:rig-camera-catalogue@1"):
        st = api.devices.connect({"backend": "real-motors", "mode": "MT-TIRF"})
        say("connected:", {k: v["state"] for k, v in st.items()})
        try:
            t0 = time.monotonic()
            cat = api.camera.catalogue()
            say(f"catalogue: {len(cat)} attributes in {time.monotonic() - t0:.2f} s")
            t0 = time.monotonic()
            vals = {}
            for e in cat:
                if e["access"] != "wo" and e["type"] != "command":
                    try:
                        vals[e["name"]] = api.camera.get_attribute(e["name"])
                    except Exception as ex:  # noqa: BLE001
                        vals[e["name"]] = f"? {type(ex).__name__}: {str(ex)[:60]}"
            say(f"values: {len(vals)} reads in {time.monotonic() - t0:.2f} s")
            tm = api.camera.get_attribute("TriggerMode")
            say("round trip TriggerMode:", tm, "->", api.camera.set_attribute("TriggerMode", tm))
            lines = ["# JAI SP-5000M-USB: the attribute catalogue as NI-IMAQdx reports it (rig 2026-11-04)", "",
                     (f"`api.camera.catalogue()` on the rig: {len(cat)} attributes; values as read at "
                     f"{time.strftime('%Y-%m-%d %H:%M')} (90 Hz full frame, the .icd defaults). The GenICam file's view "
                     "is [camera-jai-features.md](camera-jai-features.md); the program's generic panel (Setup -> Camera "
                     "settings) is built from this catalogue. vis: beginner / expert / guru as NI MAX; access rw / ro / wo."), ""]
            for cat_name in sorted({e["category"] for e in cat}):
                rows = [e for e in cat if e["category"] == cat_name]
                lines += [f"## {cat_name} ({len(rows)})", "", "| attribute | type | access | vis | value now | range / values | description |",
                          "|---|---|---|---|---|---|---|"]
                for e in rows:
                    rng = ""
                    if e.get("min") is not None:
                        rng = f"{e['min']} .. {e['max']}" + (f" step {e['step']}" if e.get("step") else "")
                    if e.get("values"):
                        rng = " / ".join(str(v) for v in e["values"][:10]) + (" ..." if len(e["values"]) > 10 else "")
                    v = vals.get(e["name"], "")
                    v = f"{v:.6g}" if isinstance(v, float) else str(v)
                    lines.append(f"| {e['name']} | {e['type']} | {e['access']} | {e['visibility'][0].upper()} | {v} | {rng} | "
                                 f"{(e.get('description') or '').replace('|', '/')[:100]} |")
                lines.append("")
            with open(OUT, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines))
            say("written", OUT)
        finally:
            api.devices.disconnect()
            say(f"disconnected; lock {api.rig.status()}")


if __name__ == "__main__":
    main()
