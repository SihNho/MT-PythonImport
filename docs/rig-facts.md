# Rig facts from the owner

Facts about the rig and the samples that the code cannot tell us. Each line gives its source and date. When a fact
changes, add the new line with its date and keep the old one marked "superseded".

## Optics and camera

| Fact | Value | Source |
|---|---|---|
| Camera | JAI SP-5000M-USB (USB3 Vision, via NI-IMAQdx `cam1`), 1280 x 1024 used (binning 2) | owner 2026-10-22; V6 `docs/instrument-libraries.md` |
| Sensor pixel | 5.0 x 5.0 µm (2560 x 2048, Lince5M) | JAI product page, accessed 2026-10-22 |
| Microscope / JAI position | Olympus **IX73**; the JAI sits at the turret position directly below the objective (owner 2026-10-24: "현재 JAI 위치는 IX73 현미경 시스템 상에서 렌즈 바로 밑에 위치한 터렛."). It has its own tube lens (model unknown), **completely separate from the TIRF path** (owner 2026-10-24: "현재 튜브렌즈가 있기는 한데, 제품명을 확인할 수 없음", "튜브는 TIRF 경로와는 완전히 분리되어 있음") | owner 2026-10-24 |
| TIRF illumination | laser beam sent into the IX73 back port from outside; the TIRF angle (penetration depth) can be set by adjusting that beam path (owner 2026-10-24: "TIRF 각도는 IX73 외부에서 backport로 쏴주는 레이저 빔 경로를 조정하면 컨트롤 가능할듯") | owner 2026-10-24 |
| Dye height (planned samples) | about 300-400 nm above the surface (owner's estimate 2026-10-24) | owner 2026-10-24 |
| Objective | **50x oil immersion** since the field of view was widened; **100x oil** before | owner 2026-10-22 |
| Image pixel, nominal | 5.0 µm x 2 (binning) / 50 ≈ **200 nm/px** (assumes the objective's matching tube lens) | computed 2026-10-22, not measured |
| `pixel distance (nm)` in the calibration file | **84 nm/px** (last DBL of the `cal002` tail; also the panel default) — stale, from the 100x objective | `cal002`; `spec/3-calibration.md` F3.01; owner 2026-10-22 |

**84 nm/px is a value left from the 100x objective** (owner 2026-10-22: "예전 렌즈 사용할 때 기록인듯. (100X)"), so it
is stale for 50x data. Note: 100x with binning 2 is 100 nm/px nominally, not 84; if 84 was measured, the real
magnification is about 1.19x the nominal one, and the same ratio would put 50x at about **168 nm/px** rather than 200.
Both figures are inferences; **measure the 50x pixel size** (stage micrometer, or move the ASI stage by a known
distance and track a stuck bead) before converting pixels to nm. **LabVIEW does not use this number**: tracking
works in pixels, and analysis is done in MATLAB with its own parameters (owner 2026-10-22, Q3.07).

## MT-TIRF optical layout (owner's schematic "2026-10-06_MT-TIRF_Optical_Schematic_paper_style_v1", read 2026-10-24)

Owner: "현재로서는 셋업인데, 나중에 바뀔 예정. 그래도 이거 보면 이해가 쉬울듯. Ingest 하고 나중에 갱신하게 될테니 source에
두지는 말도록" and then "아니 저장소에는 둬. 다만 수정 가능하도록 저장하라는 뜻." The drawing is kept as an **editable
document**: [hardware/mt-tirf-optical-layout.svg](hardware/mt-tirf-optical-layout.svg) (plain SVG text; edit it in place
when the setup changes, git keeps the old versions; update this table with it). Not part of the program source.

| Part | As drawn |
|---|---|
| Excitation lasers | **532 nm** and **637 nm**; polarisers, combined on a PBS (its 2nd output unused); two irises |
| TIRF optics | L1 f = 35 mm + L2 f = 300 mm = ≈8.6× beam expander; L3 f = 500 mm focuses on the objective back focal plane; **L3 and the last mirror share a translation stage that sets the TIRF angle**; beam enters the IX73 back port |
| Turret | DM1 = ZT532/640rpc-UF3 (excitation / emission); DM2 = "IR turret" (sends 850 nm to the JAI) |
| Objective (as drawn) | 100×/oil, UPlanSApo — **superseded**: owner 2026-10-24 (photo of the lens): "당분간 MT-TIRF 용도로는 위의 렌즈 사용할 것" = **Olympus UPlanApo 60x / 1.50 Oil HR**, ∞ / cover glass 0.13-0.19 mm (correction collar) / OFN 22, temperature collar 23-37 °C. Owner is considering using it for MT alone too: "그냥 50x low NAA 사용할 필요 없이 이거 그대로 지금 MT에 사용해도 될까 싶네" (open; see below) |
| Tracking light | **850 nm LED** above the sample, through the gap of the magnet pair |
| Magnets | antiparallel pair; z translation; rotation about z (±) |
| Tracking camera | JAI SP-5000M-USB, "z tracking, 60–150 Hz" |
| Emission path | DM1 → mirror → **slit** → L4 f = 100 mm → DM3 640rdc-UF1 (**Cy5 channel planned**, not built) → mirror → L5 f = 150 mm → notch filters NF 537/635 → **EMCCD = Andor iXon Ultra 897** |
| Synchronisation | JAI → Arduino → EMCCD trigger, frame ratio ≈ 3:1 (decision 0005) |

Consequences (inference, to be confirmed by a pixel-size measurement):
- L4 → L5 adds ≈1.5× after the slit, so the EMCCD magnification ≈ objective × 1.5 (assuming the standard Olympus tube
  lens): 50x → ≈75x, ≈213 nm/px (iXon 897: 16 µm pixels, 512 × 512); 100x → ≈150x, ≈107 nm/px. This is why the
  fluorescence field is narrow; changing the L4/L5 ratio is the direct way to widen it (U27).
- With the 60x/1.50: EMCCD ≈ 90x, ≈178 nm/px (16 µm / 90; estimate); JAI ≈ 167 nm/px at binning 2 and a field of
  ≈213 × 171 µm, about 0.69× the 50x field (estimates, standard tube lens assumed).
- **60x for MT alone too? (open, decide by one rig comparison, same sample and field, 50x vs 60x):** usable beads per
  field (the 50x was chosen for field size), reference-bead noise and Allan deviation, z-calibration quality
  (error-vs-height map), measured pixel size and **focal-shift factor** (high-NA oil into water can be well below 0.88).
  Also: record the **correction-collar settings** (cover glass, temperature) in the rig preset and data, and
  recalibrate z after changing them; check 850 nm transmission and the 850 nm vs visible focal offset (handled by the
  JAI camera position, U31). Pros of one lens: one rig preset and comparable data for MT and MT-TIRF, no lens swaps;
  likely better XY (more pixels per bead) and z sensitivity (higher NA).
- **Decided (owner 2026-10-24): MT-TIRF uses the 60x/1.50.** "어쨌든 MT-TIRF 할 때는 저걸 확실히 사용할거임. 보정이야
  Refractive index 보정 factor 있으니 나중에 적용하면 되는 부분이고." So raw z is stored uncorrected and the
  refractive-index (focal-shift) factor is applied in analysis from the recorded preset value and its source (U13,
  decision 0010's raw-first rule); measuring this lens's factor once remains worthwhile, since it scales extension.
- **Decided (owner 2026-10-24): the running MT (nucleosome) project keeps the 50x** for data continuity: "현재 MT
  프로젝트 (nucleosome) 실험에서는 렌즈 갑자기 바꿔버리면 안되니까 우선은 50X 계속 써야겠네. 데이터 연속성을 위해서".
  So for now two rig presets: "MT, 50x oil" (current nucleosome project) and "MT-TIRF, 60x/1.50". The program proposes
  the matching preset per experiment type and records the objective in every data file. The 50x vs 60x comparison is
  not urgent; it informs the lens choice for future projects.
- The TIRF-angle stage (L3 + mirror) position should be recorded automatically per run (motor, or manual + digital
  readout), as for the JAI camera position (U31).

## Samples

| Fact | Value | Source |
|---|---|---|
| Reference beads | Every measurement includes **non-paramagnetic streptavidin polystyrene beads** stuck to the surface, used as the reference | owner 2026-10-22 |
| Magnetic beads | **M-270 amine** (Dynabeads, 2.8 µm diameter) | owner 2026-10-22 |
| Sample | nucleosomes (owner's current work); extension varies by condition, about 800-1400 nm | owner 2026-10-22 |
| Focal-shift (refractive-index) factor | 0.88 in use, believed to be the oil-to-water correction; source (assumed or measured) not recorded | owner 2026-10-22 |
| "16X" in data folder names | the **DNA construct's name**, not a magnification | owner 2026-10-22 |

## Calibration (z look-up table)

| Fact | Value | Source |
|---|---|---|
| Slice step | 100 nm | owner 2026-10-22; `cal002` (0.1 µm) |
| Range used | about 6 µm (60 slices) | owner 2026-10-22; `cal002` |

## The recorded fixture (`G:\Data\SiHyeong\20260906 Kimlab - 50bp 16X WT 90Hz 1p2 Ramp_Newbatch\test`)

Taken with the **50x** objective (owner 2026-10-22). From the original program's own output `tra002-000`
(10 043 frames at 90 Hz; frame-to-frame noise = standard deviation of successive differences / √2; computed
2026-10-22):

| Bead | z range | x noise per frame | z noise per frame | Reading |
|---|---|---|---|---|
| 1 | 0.21 µm | 0.0085 px | 4.1 nm | **reference bead** (does not follow the magnet; the 0.21 µm is drift over ~112 s) |
| 2, 3, 4 | 2.0-2.2 µm, follows the magnet (r = 0.93) | ~0.10 px | ~12 nm | DNA-tethered |
| 5 | 3.7 µm | 0.067 px | 14.8 nm | tethered; leaves the stack range at the end |

Bead 1 is identified from the data (it does not follow the magnet ramp), not from the click order.
