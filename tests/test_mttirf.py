"""MT-TIRF pieces that need no measurement (owner 2026-11-21 "implement what can be implemented first"): the
JAI <-> EMCCD map (mtpy.mapping), the bead-box EMCCD storage of the run file, and the offline analysis
(mtpy.fluor: intensity-z correlation, depth from the PSF widths). All on synthetic data."""
import h5py
import numpy as np
import pytest
from test_data import T0, ev, rec_on

from mtpy import fluor, mapping
from mtpy.acq import Beads
from mtpy.data import HDF5Writer


def _affine_truth(xy):
    """A plausible JAI -> EMCCD relation: half the scale, mirrored in x, rotated 3 deg, shifted."""
    a = np.deg2rad(3.0)
    m = 0.5 * np.array([[-np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return xy @ m.T + np.array([400.0, 30.0])


def test_map_fit_both_ways_every_model():
    rng = np.random.default_rng(1)
    src = rng.uniform(0, 1000, (40, 2))
    dst = _affine_truth(src) + rng.normal(0, 0.05, (40, 2))
    t = mapping.fit(src, dst, "affine")
    assert t["rms_px"] < 0.1 and t["n_points"] == 40
    assert np.allclose(mapping.apply(t, mapping.apply(t, src[:5]), inverse=True), src[:5], atol=0.3)
    s = mapping.fit(src, dst, "similarity")                    # a mirror is not a similarity: it must not fit
    assert s["rms_px"] > 10
    bent = dst + 1e-4 * (src - 500) ** 2 / 10                   # a little curvature: poly3 takes it, affine not
    assert mapping.fit(src, bent, "poly3")["rms_px"] < 0.1 < mapping.fit(src, bent, "affine")["rms_px"]
    assert mapping.fit(src, src + [3.0, -2.0], "translation")["forward"]["matrix"][0][2] == pytest.approx(3.0)
    with pytest.raises(ValueError, match="at least 16"):
        mapping.fit(src[:10], dst[:10], "poly3")


def test_map_pairs_unpaired_spot_lists_from_a_rough_guess(tmp_path):
    rng = np.random.default_rng(2)
    src = rng.uniform(0, 1000, (30, 2))
    dst = _affine_truth(src) + rng.normal(0, 0.05, (30, 2))
    dst = np.r_[dst[3:], rng.uniform(0, 500, (8, 2))][rng.permutation(35)]   # 3 not seen, 8 extra spots, any order
    rough = mapping.fit(src[:3], _affine_truth(src[:3]) + [4.0, -3.0], "affine")    # three pairs, a few px off
    t = mapping.fit_pairs(src, dst, rough, "affine", max_px=8.0)
    assert t["n_points"] >= 25 and t["rms_px"] < 0.2
    m = mapping.make("test-map", [{"from": "jai", "to": "emccd", **t}], rig={"jai_binning": 2})
    p = mapping.save(m, tmp_path / "m.json")
    with pytest.raises(FileExistsError):
        mapping.save(m, p)
    back = mapping.load(p)
    assert np.allclose(mapping.to_emccd(back, [[100.0, 200.0]]), _affine_truth(np.array([[100.0, 200.0]])), atol=0.2)
    t2, inv = mapping.transform(back, "emccd", "jai")
    assert inv and t2["from"] == "jai"


def _gauss(shape, x, y, sx, sy, amp):
    yy, xx = np.indices(shape)
    return amp * np.exp(-((xx - x) ** 2) / (2 * sx ** 2) - ((yy - y) ** 2) / (2 * sy ** 2))


def test_find_spots_sub_pixel_and_threshold():
    rng = np.random.default_rng(3)
    truth = [(30.3, 40.7), (80.6, 20.2), (60.1, 90.9)]
    img = 100 + rng.normal(0, 3, (128, 128))
    for x, y in truth:
        img += _gauss(img.shape, x, y, 1.3, 1.3, 200)
    got = mapping.find_spots(img, radius=3)
    assert len(got) == 3
    for x, y in truth:
        d = np.hypot(got[:, 0] - x, got[:, 1] - y).min()
        assert d < 0.25, (x, y, got)


def _beads(xy):
    xy = np.asarray(xy, dtype=np.float64)
    return Beads(tuple(range(1, len(xy) + 1)), xy, [], 0, np.zeros(0), np.zeros(0))


def _emccd_run(tmp_path, storage, n=30, beads=True):
    """A synthetic run file with n EMCCD frames (64 x 64, frame k has the value k) in one recording."""
    m = mapping.make("shift", [{"from": "jai", "to": "emccd", **mapping.fit([[0, 0], [10, 0]], [[5, 7], [15, 7]],
                                                                               "translation")}])
    st = dict(storage, map=m) if storage.get("mode") == "boxes" else storage
    w = HDF5Writer(tmp_path / "f.h5", beads=_beads([[10.0, 10.0], [55.0, 50.0]]) if beads else None,
                   emccd_storage=st)
    w.write_event(rec_on(0.05))
    frames = np.broadcast_to(np.arange(n, dtype=np.uint16)[:, None, None], (n, 64, 64)).copy()
    for a in range(0, n, 7):                                  # batches of 7, as the recorder reads them
        b = frames[a: a + 7]
        w.write_emccd({"first": a + 1, "frames": b, "t_read": T0 + 1.0 + a * 0.05, "exposure_s": 0.03,
                       "t_last": T0 + 1.0 + (a + len(b) - 1) * 0.05, "period_s": 0.05, "jai_segment": 1,
                       "jai_buffer": a})
    w.write_event(ev(2.0, "recording", action="off", name="r1", segment=1, buffer_number=99))
    w.close()
    return tmp_path / "f.h5"


def test_bead_box_storage_keeps_boxes_and_some_whole_frames(tmp_path):
    p = _emccd_run(tmp_path, {"mode": "boxes", "size": 9, "first_full": 5, "every_full": 10})
    with h5py.File(p, "r") as f:
        g = f["fluorescence"]
        assert g["boxes"].shape == (30, 2, 9, 9) and list(g["box_bead_id"][()]) == [1, 2]
        assert g["box_x0y0"][()].tolist() == [[11, 13], [55, 53]]       # (15, 17) - 4; (60, 57) - 4 clipped to 55
        assert (g["boxes"][12, 1] == 12).all()
        whole = [k for k in range(30) if k < 5 or k % 10 == 0]
        assert g["images"].shape[0] == len(whole)
        idx = g["image_index"][()]
        assert [k for k in range(30) if idx[k] >= 0] == whole and (g["images"][idx[20]] == 20).all()
        assert '"map"' not in g.attrs["storage"] and "shift" in g.attrs["map"]


def test_full_storage_and_boxes_without_beads_fall_back_to_whole_frames(tmp_path):
    with h5py.File(_emccd_run(tmp_path, {"mode": "full"}), "r") as f:
        assert f["fluorescence/images"].shape[0] == 30 and "boxes" not in f["fluorescence"]
    (tmp_path / "f.h5").unlink()
    p = _emccd_run(tmp_path, {"mode": "boxes", "size": 9, "first_full": 5, "every_full": 10}, beads=False)
    with h5py.File(p, "r") as f:
        assert f["fluorescence/images"].shape[0] == 30 and "no beads" in f["fluorescence"].attrs["storage"]


def test_set_storage_refuses_what_cannot_work():
    from mtpy import api
    from mtpy.api.errors import SafetyRefused
    with pytest.raises(SafetyRefused, match="need a JAI -> EMCCD map"):
        api.emccd.set_storage("boxes")
    other = mapping.make("ch", [{"from": "ch2", "to": "ch1", **mapping.fit([[0, 0]], [[1, 1]], "translation")}])
    with pytest.raises(SafetyRefused, match="no transform between"):
        api.emccd.set_storage("boxes", other)
    good = mapping.make("j", [{"from": "jai", "to": "emccd", **mapping.fit([[0, 0]], [[1, 1]], "translation")}])
    with pytest.raises(SafetyRefused, match="odd integer"):
        api.emccd.set_storage("boxes", good, size=8)
    assert api.emccd.set_storage("boxes", good)["size"] == 15
    assert api.emccd.set_storage("full") == {"mode": "full"}


def test_correlation_map_finds_the_dye_that_follows_the_bead():
    """The owner's idea: a dye a little above the surface moves with the bead; under TIRF its intensity follows
    exp(-height / depth). Two surface dyes beside it do not."""
    rng = np.random.default_rng(4)
    n = 400
    z = 0.5 + 0.3 * (np.arange(n) // 50 % 2) + rng.normal(0, 0.01, n)      # pulled and released every 50 frames
    stack = np.empty((n, 15, 15))
    for k in range(n):
        dye = 300 * np.exp(-(0.3 * z[k]) / 0.15)                            # the dye at 30 % of the extension
        stack[k] = (100 + _gauss((15, 15), 7, 7, 1.3, 1.3, dye) + _gauss((15, 15), 3, 11, 1.3, 1.3, 150)
                    + _gauss((15, 15), 11, 3, 1.3, 1.3, 150) + rng.normal(0, 5, (15, 15)))
    z[::37] = np.nan                                                        # lost frames
    r = fluor.correlation_map(stack, z)
    assert r[7, 7] < -0.9                                                    # brighter when lower: negative
    assert abs(r[11, 3]) < 0.3 and abs(r[3, 11]) < 0.3


def test_depth_from_the_psf_widths_astigmatism():
    rng = np.random.default_rng(5)
    zs = np.linspace(-0.4, 0.4, 33)

    def spot(z):
        sx = 1.3 * np.sqrt(1 + ((z - 0.2) / 0.35) ** 2)                     # x focus 200 nm above, y 200 nm below
        sy = 1.3 * np.sqrt(1 + ((z + 0.2) / 0.35) ** 2)
        return 50 + _gauss((21, 21), 10, 10, sx, sy, 2000) + rng.normal(0, 2, (21, 21))
    w = [fluor.widths(spot(z)) for z in zs]
    cal = fluor.astig_calibration(zs, [x["sx"] for x in w], [x["sy"] for x in w])
    assert cal["rms_um"] < 0.02
    test = [fluor.widths(spot(z)) for z in (-0.25, 0.0, 0.3)]
    got = fluor.z_from_widths(cal, [x["sx"] for x in test], [x["sy"] for x in test])
    assert np.allclose(got, [-0.25, 0.0, 0.3], atol=0.03)
    assert np.isnan(fluor.z_from_widths(cal, 10.0, 1.0))                     # far outside the calibration


def test_widths_of_a_dim_spot_are_fitted_not_inflated():
    rng = np.random.default_rng(6)
    got = [fluor.widths(100 + _gauss((21, 21), 10.3, 9.6, 1.5, 2.2, 40) + rng.normal(0, 5, (21, 21)))
           for _ in range(20)]
    sx, sy = np.median([g["sx"] for g in got]), np.median([g["sy"] for g in got])
    assert sx == pytest.approx(1.5, rel=0.1) and sy == pytest.approx(2.2, rel=0.1)
    assert np.median([g["x"] for g in got]) == pytest.approx(10.3, abs=0.1)
    assert np.isnan(fluor.widths(np.full((9, 9), 7.0))["sx"])                # no signal


def test_bead_z_extension_from_a_run_file(tmp_path):
    p = tmp_path / "r.h5"
    with h5py.File(p, "w") as f:
        f["beads/bead_id"] = np.array([1, 3], dtype=np.int32)
        f["mt/t_host"] = np.arange(5, dtype=np.float64)
        f["mt/z_um"] = np.array([[1.0, 2.0], [1.0, 2.5], [1.0, -1.0], [1.1, 3.1], [1.0, 3.0]])
        f["mt/bead_lost"] = np.array([[0, 0], [0, 0], [0, 1], [0, 0], [0, 0]], dtype=np.uint8)
    _, v = fluor.bead_z(p, 3, reference_bead=1)
    assert np.isnan(v[2]) and v[3] == pytest.approx(2.0)
    assert fluor.bead_z(p, 3, [0.5, 2.0, 9.0], reference_bead=1)[:2] == pytest.approx([1.25, 1.75])
