# Development cycles WP1-WP6 (AI working notes)

Owner 2026-10-24: "WP6까지 쭉 진행해볼래? 각 순서마다 싸이클로 돌고, 진행 경과를 토론 돌릴 것" and "각 싸이클은
(예를 들어, WP1) 토론에서 수렴할 때 다음 단계로 넘어가고 아니라면 다시 루프".

## Rule
1. Implement and test the work package (branch `phase5-skeleton`, no push without the owner's word).
2. Claude-GPT discussion on the progress (V6 `tools/debate_gdoc.py run --mode rounds --auto-end --max-rounds 6`,
   folder V6 `tools/bench/debate/l2s-wp<N>-r<k>/`).
3. Converged on "continue" -> next work package.
4. Not converged, or agreed changes -> apply them and run the same work package's discussion again.
5. The same issue repeating three times -> stop and ask the owner.

## Work packages (plan.md phase 5)
WP1 API skeleton + rig safety profile · WP2 simulators · WP3 acquisition pipeline · WP4 data (HDF5 v1 + .tra/.cal) ·
WP5 grammar parser + protocol engine · WP6 walking skeleton end to end.

## Carried to later packages (agreed in discussions)
- WP6: wait_arrival generation check; a send applied after a reply timeout.
- Phase 6: order of the speed check during an e-stop (magnet refusal reason priority).
- Phase 6/7: rotor omitted-speed check (with the package that opens rotor ranges); the real drivers' direct stop path
  on the serial port.
- Owner decisions pending: allow_unverified re-commissioning policy; unset limits (magnet force / speed max, rotor
  speed, focus window, laser powers); rotor ±5 turns; real JAI timestamp (PC receive time?).

## Log
| Cycle | WP | Commit | Discussion | Result |
|---|---|---|---|---|
| 1 | WP1 | 30c42cf | l2s-wp1-r1 ([Google doc](https://docs.google.com/document/d/1IhyVLq0rUGJypYqIRZ7QzHd_LGl6p3IDxJFTYSDSplk/edit)) | not converged (Claude side auth failed; GPT: change x3 + unverified policy) -> fixes in b72b428 |
| 1 (r2) | WP1 | b72b428 | l2s-wp1-r2 ([Google doc](https://docs.google.com/document/d/1PNIoqJtAW975szARW7uHbmLuz1ySAmtFOypshjsCf1E/edit)) | converged in 3 rounds: change (a)-(e) then continue -> fixes in 1137dd0 (57 tests pass, ruff clean on changed files); owner decisions pending: allow_unverified report policy, unset limits, rotor ±5 turns |
| 2 | WP2 | 1bea316 | l2s-wp2-r1 ([Google doc](https://docs.google.com/document/d/1JUNcL7JcZjTC-I_R6z-wmM4rn4PzgYb3cCCDBfWBhqk/edit)) | converged in 5 rounds: change (e-stop order, send-window checks, direct cancel, omitted-speed check, divider reset rule, WP3 frame contract), then re-review -> fixes in f4bfc35 (82 tests pass x3, ruff clean on changed files); WP1 fixes (a)-(e) confirmed in 1137dd0; owner decision pending: magnet_speed_mm_s max (v1 refuses every magnet move) |
| 2 (r3) | WP2 | 31f69d7 | l2s-wp2-r3 ([Google doc](https://docs.google.com/document/d/1R9gl2lrgBWDJD47FM7ZdMI1LDKa8Ppks1Q5b0E_yeEo/edit)) | **converged in 4 rounds: continue** -> WP3. Not the "same issue three times" case (fixes completed). Note: the debaters did not run pytest / ruff themselves. Discussion cost so far (Claude side): about $13.3 |
| 2 (r2) | WP2 | f4bfc35 | l2s-wp2-r2 ([Google doc](https://docs.google.com/document/d/1PC2i0Kpwb_HOhfnO-fToIiY5aWkpWbwBrbVEUeNo40E/edit)) | converged in 4 rounds: change (generation recorded before pre-reads; void check + re-stop after any send end) then re-review -> fixes in 31f69d7 (87 tests pass x3, ruff clean on changed files); deferred: rotor omitted-speed check (to the package that opens rotor ranges), wait_arrival generation check (later) |
