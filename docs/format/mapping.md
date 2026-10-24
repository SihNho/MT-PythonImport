# Mapping file format — PROPOSAL (not yet decided)

Status: proposed 2026-10-23 in chat; waiting for the owner's agreement. Requirements: [ui-requirements.md](../spec/ui-requirements.md) U22.

Owner 2026-10-23: "Mapping의 경우 single channel, 2 channel, 3 channel로 사용할 것 같고 각 채널 정체를 define할 수 있고
그 정보를 프리셋 저장도 가능해야겠음. 동시에 magnetic bead와 EMCCD 사이의 mapping 역시 필요함. 사전의 mapping을 통해서
데이터를 불러오는게 맞겠고, mapping 데이터 형식은 어떻게 할지도 정하면 좋을듯"

## Two parts
1. **Channel layout** (a preset, U13 / U15): 1, 2 or 3 channels; per channel: name, region on the EMCCD sensor, excitation
   laser, emission filter, display colour. Examples: "2ch Cy3/Cy5 (left/right)", "3ch (thirds)".
2. **Map file** (measured beforehand, loaded at the start of a run): the transforms between coordinate frames:
   every channel -> the reference channel, and the JAI (magnetic-bead tracking camera) -> the EMCCD reference channel.

## Use
- At run start the user picks a map; the program checks it matches the channel layout and warns when it is old or its
  rms error is large.
- The data file stores the map's id **and full content** (U16) and the raw (unmapped) coordinates, so data can be
  re-mapped later with a better map.

## Format: one JSON file per map (+ a CSV of control points)
JSON because it is small, human-readable, diff-able and read by MATLAB `jsondecode`; no large arrays need HDF5.

```json
{
  "schema": "mt-map/1",
  "id": "2026-10-23_2ch_Cy3Cy5_60x",
  "created": "2026-10-23T14:00:00+09:00",
  "user": "SiHyeong",
  "rig": {"objective": "60x/1.50 oil", "jai_binning": 2, "emccd_model": "iXon Ultra 897"},
  "channels": [
    {"id": "ch1", "name": "Donor Cy3", "region_px": [0, 0, 256, 512], "excitation_nm": 532, "emission": "585/40", "color": "#22C55E"},
    {"id": "ch2", "name": "Acceptor Cy5", "region_px": [256, 0, 256, 512], "excitation_nm": 637, "emission": "680/40", "color": "#EF4444"}
  ],
  "reference": "ch1",
  "transforms": [
    {"from": "ch2", "to": "ch1", "model": "poly3",
     "forward": {"x": ["16 coefficients"], "y": ["16 coefficients"]},
     "inverse": {"x": ["16"], "y": ["16"]},
     "rms_px": 0.08, "n_points": 152},
    {"from": "jai", "to": "ch1", "model": "affine",
     "forward": [[1, 0, 0], [0, 1, 0]], "inverse": [[1, 0, 0], [0, 1, 0]],
     "rms_px": 0.6, "n_points": 24}
  ],
  "control_points": "2026-10-23_2ch_Cy3Cy5_60x_points.csv",
  "notes": ""
}
```

- Models: `translation`, `similarity`, `affine`, `poly2`, `poly3`. Defaults: `poly3` between channels (chromatic
  distortion; as smCamera's maps), `affine` for JAI -> EMCCD (two cameras, different magnification).
- Both directions are stored (smCamera's maps did the same).
- Control points (paired coordinates) are kept in a CSV so any map can be refitted or its model changed.
- `region_px` = [x0, y0, width, height] on the EMCCD sensor; coordinates in pixels of the frame named in `from` / `to`.
- Legacy `map_Andor1_*.txt` (smCamera) import into this format; the exact meaning of its 16 coefficients is to be
  confirmed from the smCamera paper (Lee & Ha 2024) before relying on it.

## Detection differs by target (owner 2026-10-23)
Owner: "detection 알고리즘이 각각 달라야할거임. Fluorescence channel 끼리는 그냥 peak detection으로 될지 모르나 magnetic
bead의 auto-fluorescence를 활용한다면 덩치가 조금 있을거임."
- Fluorescence channel <-> channel (single molecules, small fluorescent beads): **peak detection** of
  diffraction-limited spots (local maximum + threshold; sub-pixel by 2D Gaussian or centroid, as smCamera).
- JAI <-> EMCCD: **the magnetic beads' autofluorescence** on the EMCCD (M-270, 2.8 µm: an extended blob of several to
  tens of pixels, possibly uneven) -> **blob detection** (LoG / DoG at the bead's scale, or a disc template; centre
  from the segmented blob's centroid or a circle fit), paired with the same beads' **ring detection** on the JAI.
- Pairing: an initial transform from the optics (magnification ratio, flips, rotation), nearest-neighbour pairing,
  outlier rejection (e.g. RANSAC), then the fit.
- Benefit: the map uses the very beads of the experiment, so it can be checked in situ before each run (one
  autofluorescence frame -> residual of the stored map).
- Detectors are per-channel plug-ins (peak / blob / ring) with their parameters in presets (U23).

## Open
- JAI <-> EMCCD control points: the owner proposes magnetic-bead autofluorescence (above). Whether it is bright
  enough on the EMCCD, and the other options ((b) a grid / stage micrometer, (c) a stuck bead stepped by the stage), to
  be checked on the rig.
- Agreement on JSON vs HDF5, and on the field names.
