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
| 4 (r3) | WP4 | 914338e | l2s-wp4-r3 ([Google doc](https://docs.google.com/document/d/1hs6jGvpEvh0N2d9uUsL77EhevEOXLbq9avWSx-eVW6Y/edit)) | **converged in 2 rounds: continue** -> WP5. Fix 1 confirmed (settings check before sink, ROI and pipeline); the 3 agreed tests confirmed. Carry: driver - settings-read failure contract at the initial start (error + event). Static review (136 tests re-run by the chat). Cost (Claude side) about $27.5 so far |
| 4 (r2) | WP4 | f3dee01 | l2s-wp4-r2 ([Google doc](https://docs.google.com/document/d/1zm60v1WRcf9JC7n1LwSISUK46AcRIslkdA-pFDOhRr4/edit)) | converged in 3 rounds: **change** for fix 1 only - start(record=True) builds the sink and uses the ROI (acq.py:71-85) before the four-settings check (:87); move the check first + tests for missing roi and missing gain (refused event, NotReady, not running, no file), plus a late-off test with frames_outside_recordings > 0. Fixes 2-7 confirmed. Then re-review fix 1 only -> WP5. Carries: WP5 - max_pending overflow status test; WP6 - back-fill across several blocks; driver - late .cal ignored when cal_path missing, record=False with roi missing raises KeyError. 133 tests pass (re-run by the chat) |
| 4 | WP4 | ee020a9 | l2s-wp4-r1 ([Google doc](https://docs.google.com/document/d/19CSNOOKROkbgB9uOXM2p5vsG4H63rhkfs-iUXYSJdyE/edit)) | converged in 4 rounds: **change** (7 fixes: API checks the four settings before setting the flag; writer checks frames against the on..off interval by (segment, buffer), out-of-range reported at close; late .cal applied and /beads rebuilt each flush; late motor event back-filled + small-flush test; crash test right after a new group is created; libver ('earliest','v108') instead of latest; crash-bound wording limited to tested points), then re-review. WP6 carries: crash during a flush incl. back-fill, real MATLAB run, per-frame motor reading, sink_error in the file, .tra column-0 origin. Owner: MATLAB version; .tra frame column = buffer minus first RECORDED buffer? (origin unchanged until answered). 126 tests pass (re-run by the chat once) |
| 3 (r2) | WP3 | 2e95f15 | l2s-wp3-r2 ([Google doc](https://docs.google.com/document/d/1qLI-M7pEL1j30HNwixSzicP6SLLPZ4GKkSCR_MKVzCU/edit)) | **converged in 3 rounds: continue** -> WP4. Refusing recording-on on a settings-read failure agreed (U15). Carries: WP4 - writer refuses a recording-on event missing any of the four settings, recording-on precedes the acquisition-start event (do not assume arrival order); driver/WP6 - stop_acquisition failure still clears _pipe (check camera stopped separately); WP6/U23 - store the ROI at bead selection and compare the origin at start. Static review only (tests not re-run by the debaters). Cost (Claude side) so far about $20.5 |
| 3 | WP3 | 9660bce | l2s-wp3-r1 ([Google doc](https://docs.google.com/document/d/1TTXkahIVa0xUTsG-BFHAK-haFJznJ2mo8OFeZ8cmKZI/edit)) | not converged in 6 rounds (verdict change agreed; open: recording-on when the settings read fails -> chat chose refuse) -> fixes in 2e95f15 (108 tests pass x3, ruff clean on changed files); carried list in docs/design/api.md |
