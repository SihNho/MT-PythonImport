"""Maps between coordinate frames: JAI <-> EMCCD and EMCCD channel <-> channel (U22; format docs/format/mapping.md,
schema mt-map/1). Pure numpy and offline: fit a transform from paired control points, apply it both ways, pair two
spot lists, find spots in an image, save / load one JSON file per map.

    t = mapping.fit(jai_xy, emccd_xy, "affine")              # -> {"model", "forward", "inverse", "rms_px", ...}
    m = mapping.make("2026-11-21_jai_60x", [{"from": "jai", "to": "emccd", **t}], rig={"jai_binning": 2})
    mapping.save(m, "maps/2026-11-21_jai_60x.json")
    mapping.to_emccd(mapping.load("maps/2026-11-21_jai_60x.json"), bead_xy)

Coordinates are pixels (x, y) of the frame named in "from" / "to": the JAI image of the ROI in force, the EMCCD
full sensor. The control points are kept inside the JSON (not a CSV beside it), so one file holds the whole map.
"""
import json
import time
from pathlib import Path

import numpy as np

SCHEMA = "mt-map/1"
MODELS = ("translation", "similarity", "affine", "poly2", "poly3")
MIN_POINTS = {"translation": 1, "similarity": 2, "affine": 3, "poly2": 9, "poly3": 16}


def _xy(a):
    return np.asarray(a, dtype=np.float64).reshape(-1, 2)


def _terms(u, degree):
    """x^i y^j for i, j in 0..degree (the full tensor: 16 terms for poly3, as smCamera's map files)."""
    return np.stack([u[:, 0] ** i * u[:, 1] ** j for i in range(degree + 1) for j in range(degree + 1)], axis=1)


def _fit_one(src, dst, model):
    n = len(src)
    if model == "translation":
        tx, ty = (dst - src).mean(axis=0)
        return {"matrix": [[1.0, 0.0, tx], [0.0, 1.0, ty]]}
    if model == "similarity":                       # dst = [a -b; b a] src + t
        a = np.zeros((2 * n, 4))
        a[0::2] = np.c_[src[:, 0], -src[:, 1], np.ones(n), np.zeros(n)]
        a[1::2] = np.c_[src[:, 1], src[:, 0], np.zeros(n), np.ones(n)]
        p = np.linalg.lstsq(a, dst.reshape(-1), rcond=None)[0]
        return {"matrix": [[p[0], -p[1], p[2]], [p[1], p[0], p[3]]]}
    if model == "affine":
        m = np.linalg.lstsq(np.c_[src, np.ones(n)], dst, rcond=None)[0]       # 3 x 2
        return {"matrix": m.T.tolist()}
    degree = int(model[-1])
    centre = src.mean(axis=0)
    scale = float(max(np.abs(src - centre).max(), 1e-12))     # normalised: x^3 y^3 of raw pixels is ill-conditioned
    t = _terms((src - centre) / scale, degree)
    cx, cy = (np.linalg.lstsq(t, dst[:, k], rcond=None)[0] for k in (0, 1))
    return {"degree": degree, "centre": centre.tolist(), "scale": scale, "x": cx.tolist(), "y": cy.tolist()}


def _apply_one(f, xy):
    if "matrix" in f:
        m = np.asarray(f["matrix"], dtype=np.float64)
        return xy @ m[:, :2].T + m[:, 2]
    t = _terms((xy - np.asarray(f["centre"])) / f["scale"], f["degree"])
    return np.c_[t @ np.asarray(f["x"]), t @ np.asarray(f["y"])]


def fit(src, dst, model="affine"):
    """The transform `model` from the points `src` to their partners `dst` (n x 2 each), and its inverse (fitted on
    its own, as smCamera did). Returns {"model", "forward", "inverse", "rms_px" (in dst pixels), "max_px",
    "n_points", "control_points": {"from", "to"}}."""
    src, dst = _xy(src), _xy(dst)
    if model not in MODELS:
        raise ValueError(f"map model {model!r} is not one of {MODELS}")
    if len(src) != len(dst) or len(src) < MIN_POINTS[model]:
        raise ValueError(f"{model} needs at least {MIN_POINTS[model]} point pairs of equal count; got {len(src)} / {len(dst)}")
    fwd, inv = _fit_one(src, dst, model), _fit_one(dst, src, model)
    err = np.hypot(*(_apply_one(fwd, src) - dst).T)
    return {"model": model, "forward": fwd, "inverse": inv, "rms_px": float(np.sqrt(np.mean(err ** 2))),
            "max_px": float(err.max()), "n_points": len(src), "control_points": {"from": src.tolist(), "to": dst.tolist()}}


def apply(t, xy, inverse=False):
    """Map the points xy (n x 2) with the transform t (from fit); inverse=True maps "to" -> "from"."""
    return _apply_one(t["inverse"] if inverse else t["forward"], _xy(xy))


def pair(src, dst, guess=None, max_px=3.0):
    """(i_src, i_dst): mutual nearest neighbours closer than max_px after mapping src with `guess` (a transform from
    fit, or None = the frames coincide)."""
    src, dst = _xy(src), _xy(dst)
    if not len(src) or not len(dst):
        return np.empty(0, int), np.empty(0, int)
    p = apply(guess, src) if guess is not None else src
    d = np.hypot(p[:, None, 0] - dst[None, :, 0], p[:, None, 1] - dst[None, :, 1])
    j = d.argmin(axis=1)
    i = np.arange(len(src))
    keep = (d.argmin(axis=0)[j] == i) & (d[i, j] <= max_px)
    return i[keep], j[keep]


def fit_pairs(src, dst, guess, model="affine", max_px=3.0, rounds=5, reject=3.0):
    """Pair two unpaired spot lists starting from a rough `guess` (e.g. a similarity from three hand-picked pairs),
    fit, drop pairs farther than `reject` x rms (at least 0.5 px), pair again with the fit; repeat until the pairs
    stop changing. Returns the transform of fit (its control points are the pairs kept)."""
    src, dst = _xy(src), _xy(dst)
    t, last = guess, None
    for _ in range(rounds):
        i, j = pair(src, dst, t, max_px)
        if len(i) < MIN_POINTS[model]:
            raise ValueError(f"only {len(i)} pairs within {max_px} px; {model} needs {MIN_POINTS[model]} - a better "
                             "guess or a larger max_px")
        t = fit(src[i], dst[j], model)
        err = np.hypot(*(apply(t, src[i]) - dst[j]).T)
        ok = err <= max(reject * t["rms_px"], 0.5)
        if not ok.all():
            i, j = i[ok], j[ok]
            t = fit(src[i], dst[j], model)
        key = (tuple(i), tuple(j))
        if key == last:
            break
        last = key
    return t


def _box_mean(img, r):
    """Mean over a (2r+1)^2 window, edges by replication (cumulative sums: no scipy on the rig)."""
    k = 2 * r + 1
    p = np.pad(img, r + 1, mode="edge")
    c = p.cumsum(axis=0).cumsum(axis=1)
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s[: img.shape[0], : img.shape[1]] / (k * k)


def _window_max(a, r):
    k = 2 * r + 1
    p = np.pad(a, r, mode="constant", constant_values=-np.inf)
    v = np.lib.stride_tricks.sliding_window_view(p, k, axis=0).max(axis=-1)
    return np.lib.stride_tricks.sliding_window_view(v, k, axis=1).max(axis=-1)


def find_spots(img, radius=2, k=5.0, edge=None):
    """Bright spots in an image: local maxima of the (2 radius + 1) box mean higher than median + k x noise (noise
    from the median absolute deviation), each placed at the background-subtracted centroid of its window. radius
    ~ the spot's half width: 2 for single molecules, the bead's radius for bead autofluorescence (U22). Spots
    closer than `edge` (default radius) to the border are left out. Returns n x 3 (x, y, signal), brightest first."""
    img = np.asarray(img, dtype=np.float64)
    r = int(radius)
    edge = max(r, int(r if edge is None else edge))     # the centroid window stays inside
    sm = _box_mean(img, r)
    med = np.median(sm)
    noise = 1.4826 * np.median(np.abs(sm - med)) or 1e-12
    peak = (sm == _window_max(sm, r)) & (sm > med + k * noise)
    h, w = img.shape
    out = []
    for y, x in zip(*np.nonzero(peak)):
        if not (edge <= x < w - edge and edge <= y < h - edge):
            continue
        win = img[y - r: y + r + 1, x - r: x + r + 1]
        border = np.r_[win[0], win[-1], win[1:-1, 0], win[1:-1, -1]]
        wgt = np.clip(win - np.median(border), 0.0, None)
        tot = wgt.sum()
        if tot <= 0:
            continue
        yy, xx = np.mgrid[-r: r + 1, -r: r + 1]
        out.append((x + (wgt * xx).sum() / tot, y + (wgt * yy).sum() / tot, tot))
    out = np.array(out, dtype=np.float64).reshape(-1, 3)
    return out[np.argsort(-out[:, 2])]


def make(map_id, transforms, rig=None, channels=None, reference="emccd", notes=""):
    """A map (schema mt-map/1): transforms = [{"from", "to", **fit(...)}]; rig = what it was measured with (objective,
    jai_binning, jai_roi, jai_tube, emccd model, ...) - a map is valid only for that."""
    for t in transforms:
        if not {"from", "to", "forward", "inverse", "model"} <= set(t):
            raise ValueError(f"a map transform needs from, to and a fit result; got {sorted(t)}")
    return {"schema": SCHEMA, "id": str(map_id), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rig": dict(rig or {}),
            "channels": list(channels or []), "reference": reference, "transforms": list(transforms), "notes": notes}


def save(m, path):
    """Write the map as JSON; an existing file is never overwritten (a map in use by data is a record)."""
    p = Path(path)
    if p.exists():
        raise FileExistsError(f"{p} exists; a map file is never overwritten - give the new map another id")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8")
    return p


def load(path):
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(m, dict) or m.get("schema") != SCHEMA:
        raise ValueError(f"{path} is not a {SCHEMA} map file")
    return m


def transform(m, frm, to):
    """(transform, inverse) that maps `frm` -> `to` in map m: a stored to -> frm is used backwards."""
    for t in m["transforms"]:
        if (t["from"], t["to"]) == (frm, to):
            return t, False
        if (t["from"], t["to"]) == (to, frm):
            return t, True
    raise KeyError(f"map {m.get('id')!r} has no transform between {frm!r} and {to!r}")


def to_emccd(m, xy_jai):
    """JAI image pixels -> EMCCD pixels of the map's reference frame."""
    t, inv = transform(m, "jai", m.get("reference", "emccd"))
    return apply(t, xy_jai, inverse=inv)
