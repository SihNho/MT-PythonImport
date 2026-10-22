# 0010 — Magnet position is the raw record; force is derived and recomputable

**Decided:** 2026-10-22 (owner, chat)

Owner: "힘 보정은 사실 리소스 절약을 위해 사전에 계산된 표를 사용하는 방식을 취하고 있음. 만약 병렬화가 성공적이라면 그냥
실시간 force 계산도 괜찮을 것 같음. raw data는 어차피 force가 아닌 magnet position을 기록할 거라, calibration을 아무리
바꿔도 타격이 없는 것이 목표."

## Decision
1. **Data files store the magnet position, never force, as the raw quantity.** Force is always derived, so any
   calibration can be replaced later without touching raw data.
2. **Default force = a precomputed calibration table** (as today). The table used (name, version, content or hash) is
   written into the data file, so force can be recomputed exactly or with a newer table.
3. **Live per-bead force estimation may be added** for display and cross-checking once the parallel tracking leaves
   enough headroom (it costs little compared with tracking).

## Consequences
- Live force estimates from bead fluctuations need long windows at low force (slow fluctuations) and a correction for
  camera exposure averaging at 90-150 Hz (Wong & Halvorsen 2006; [literature survey](../literature/reports/Bead%20tracking%20algorithms%20review.md)).
  They are shown with their window length and are not the default force.
- Analysis code takes "position -> force" as a swappable function, like the tracking stages (0003).
