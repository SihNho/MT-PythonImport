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

## Log
| Cycle | WP | Commit | Discussion | Result |
|---|---|---|---|---|
| 1 | WP1 | 30c42cf | l2s-wp1-r1 ([Google doc](https://docs.google.com/document/d/1IhyVLq0rUGJypYqIRZ7QzHd_LGl6p3IDxJFTYSDSplk/edit)) | not converged (Claude side auth failed; GPT: change x3 + unverified policy) -> fixes in b72b428 |
| 1 (r2) | WP1 | b72b428 | l2s-wp1-r2 ([Google doc](https://docs.google.com/document/d/1PNIoqJtAW975szARW7uHbmLuz1ySAmtFOypshjsCf1E/edit)) | converged in 3 rounds: change (a)-(e) then continue -> fixes in 1137dd0 (57 tests pass, ruff clean on changed files); owner decisions pending: allow_unverified report policy, unset limits, rotor ±5 turns |
| 2 | WP2 | 1bea316 | l2s-wp2-r1 ([Google doc](https://docs.google.com/document/d/1JUNcL7JcZjTC-I_R6z-wmM4rn4PzgYb3cCCDBfWBhqk/edit)) | converged in 5 rounds: change (e-stop order, send-window checks, direct cancel, omitted-speed check, divider reset rule, WP3 frame contract), then re-review -> fixes in f4bfc35 (82 tests pass x3, ruff clean on changed files); WP1 fixes (a)-(e) confirmed in 1137dd0; owner decision pending: magnet_speed_mm_s max (v1 refuses every magnet move) |
