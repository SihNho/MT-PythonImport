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
  "id": "2026-10-23_2ch_Cy3Cy5_50x",
  "created": "2026-10-23T14:00:00+09:00",
  "user": "SiHyeong",
  "rig": {"objective": "50x oil", "jai_binning": 2, "emccd_model": "iXon Ultra [model]"},
  "channels": [
    {"id": "ch1", "name": "Donor Cy3", "region_px": [0, 0, 256, 512], "excitation_nm": 532, "emission": "585/40", "color": "#22C55E"},
    {"id": "ch2", "name": "Acceptor Cy5", "region_px": [256, 0, 256, 512], "excitation_nm": 638, "emission": "680/40", "color": "#EF4444"}
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
  "control_points": "2026-10-23_2ch_Cy3Cy5_50x_points.csv",
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

## Open
- How to make JAI <-> EMCCD control points: (a) targets visible in both bright field and fluorescence (large
  fluorescent beads), (b) a grid / stage micrometer imaged by both cameras, or (c) one stuck bead stepped by the stage
  by known distances and tracked in both cameras. Depends on the optical path; owner to choose.
- Agreement on JSON vs HDF5, and on the field names.
