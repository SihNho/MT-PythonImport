# Fault scenarios (owner 2026-10-31: "세션 여러개 돌려서 고장 리스트 뽑은 다음 테스트해보기")

Three independent review sessions each read the code with one lens (GUI operation, devices and process death, data and
protocol) and listed what can go wrong; this page merges their lists, with what was then **verified** (code read, or a
probe on the simulators) and what was done. Line numbers are those of 2026-10-31. "Not covered" = no automated test.
Status: `fixed` (code + test in the commit of this page), `confirmed` (true, open), `refuted`, `design` (the current
behaviour is on purpose), `owner` (needs the owner's decision).

## Fixed on 2026-10-31
| id | scenario | what was found | fix |
|---|---|---|---|
| G1 | Connect clicked twice quickly (real backend) | **confirmed on the sim:** both connects ran, two device sets were built, the second overwrote the first in the registry: open ports (PI limits set, iXon cooling) that no close reaches | `api.devices.connect` is one at a time (lock); the second gets NotReady. Test `test_two_connects_at_once_build_one_rig` |
| G7 | Start acquisition clicked twice quickly | **confirmed on the sim:** both starts ran, two pipelines | `api.acq.start` under a lock; the second gets NotReady. Test `test_two_acquisition_starts_at_once_build_one_pipeline` |
| D5 | the rig-lock heartbeat's `permitted()` raises (lock file unreadable, share gone) | **confirmed (code):** no try in `rig._heartbeat`: the thread died and lock monitoring stopped silently for the session | a raising check is a lost lock: `rig_lock lost` event + emergency stop. Test `test_heartbeat_treats_a_raising_permitted_as_a_lost_lock` |
| D7 | PI serial cable pulled mid-move | **confirmed (code):** `PiMagnet.moving` read a silent `ONT?` as "still moving" until the move timeout (60 s) | no reply to `ONT?` raises at once (DeviceError through the service). Test `test_pi_no_reply_to_ont_is_an_error_not_still_moving` |
| D1 / G14 / D11 | a failed device close is retried (shutdown dialog Retry, `api.devices.close` again) | **confirmed on the sim:** the retry re-OPENED the device before closing it: for the PI limits written + FNL reference move, for the iXon Initialize + a cold set point adopted again | owner "둘 다 고쳐": the PI, ASI and iXon drivers keep their handle on a failed close, and `api.devices.close` repeats the cleanup on the still-open device, never `open()`. Tests `test_close_retry_repeats_the_cleanup_without_reopening`, `test_pi_failed_home_keeps_the_port_and_limits_for_the_retry`, cooler test extended |
| G15 | Connect clears an engaged emergency stop | **confirmed (code):** `_connect` called `estop.clear()` unconditionally | Connect is refused while the stop is engaged ("press Acknowledge first"); only the Acknowledge button clears. Test `test_connect_is_refused_while_the_emergency_stop_is_engaged` |
| - | z scan with an empty pick list (happened on the rig the same evening) | 60 slices scanned, then `write_cal` crashed | `gui/zscan.run` refuses before any move. Test `test_zscan_refuses_an_empty_pick_list` |

## Fixed on 2026-11-01 (owner: "진행해야")
| id | scenario | what was found | fix |
|---|---|---|---|
| P5 / G5 | camera settings applied during a z scan (owner queued 2026-10-30) | **confirmed (code):** nothing blocked exposure / rate / ROI between slices; the GUI sent `confirm=True` always | the z scan sets `scanning` on the camera service and `api.camera` refuses every setting meanwhile (released also after a failed scan); the GUI asks before a guarded change while recording. Tests `test_zscan_locks_the_camera_settings_while_it_runs`, `test_apply_preset_asks_before_a_guarded_change_while_recording` |
| P4 / G6 | touch position changed while a protocol runs | **confirmed (code):** `set_touch_position` had no guard | refused (SafetyRefused + `refused` event) while `protocol.running()`; while recording the `calibration` event already goes into the run. Test `test_touch_position_is_fixed_while_a_protocol_runs` |
| P1 | disk full / I/O error while recording | **confirmed (code):** only counted in `sink_failures`; recording went on | the pipeline reports its first sink failure to `api.acq._fault`: an `acquisition fault` event, and an `OSError` while recording switches recording off (acquisition and display go on). Pending rows were already bounded (`max_pending`). Test `test_sink_io_failure_switches_recording_off_with_an_event` |
| D13 | camera frame thread dies | **confirmed (code):** no try in `_camera_loop`; `running()` stayed True with no frames | caught: `camera_error` in `acq.status()`, an `acquisition fault` event; the stop-time drain tolerates the dead path. Test `test_camera_thread_death_is_visible_in_status_and_as_an_event` |
| D6 | lock lost during acquisition | only the e-stop engaged, with no visible reason | `estop.reason()` ("rig lock lost", "GUI STOP button", ...) shown in the GUI status bar. Cleanup policy stays the user's (experiment = touch nothing). Heartbeat test extended |
| D4 / G4 | process killed while recording | no atexit; power loss and taskkill cannot be handled | `atexit` in `api.acq` closes the run file when the process ends normally (sys.exit, Ctrl+C in a script); the rig-lock refusal names the recovery (a person checks the rig, RULES.md). taskkill / power loss: HDF5 loses at most the unflushed second (tested earlier) |

## Confirmed, open (ranked by risk)
| id | scenario | finding | proposed |
|---|---|---|---|
| G2 | window closed during a z scan | the scan worker is not a shutdown step; its `finally` moves the focus back while "close focus" may run; `progress` sets a label from a worker thread | add "stop the calibration scan" as step 0 of the shutdown; progress through a signal |
| G3 | Close / Disconnect pressed while a GUI-started move waits (`move_to().wait(60)`) | the `_call` workers are never joined; devices close under a move | cancel pending motions (e-stop generation) or wait for `_workers` before the close steps |
| D18 | rotor open fails after the port opened | `self.line = L` is set after the first read; a timeout there leaks the port | set `line` before the reads, or close `L` on failure |
| G9 | exception in a Worker callback or a `BaseException` in `Worker.run` | callback errors go to stderr only (status bar says ok); a stuck worker disables the EMCCD readback for good; `_tick` catches NotReady only | wrap callbacks with `_fail`; catch BaseException |
| G10 | picks made, ROI changed, Run z scan | picks are not bounds-checked; `bead_profile` slices out of range after the focus moved | clear picks on an ROI change, or check before the first move |
| P7 | `acq.stop` under a running protocol | the protocol ends `failed`, not `stopped` | stop the protocol first, or a distinct end state |
| P8 | recording toggled rapidly | `set_recording` has no lock | lock + GUI debounce |
| P11 | two runs with the default name within one second | NotReady on a quick restart | auto-suffix |
| P12 | beads lost for a long stretch | no event, protocol keeps applying force | a `bead_lost` event after N frames (owner: pause?) |
| P6, P10, P13, P14, D8, D9, D10, D14, D15, D17, G8, G11, G12, G13, G16 | smaller items (error masking in the z-scan `finally`, no "recovered" warning on export, nm_per_px not compared at select, per-flush time-source attribute, stall inside a run scope, PI power loss hint, ASI silent during a scan, camera reconnect status, a non-DeviceError raised inside disconnect, stale button texts after Disconnect) | as listed by the sessions; low risk or already partly covered | one by one, with a test each |

## Refuted or by design
| id | claim | verdict |
|---|---|---|
| D2 | `PiMagnet.close` leaks the COM port after a failed home | **refuted:** `finally` calls `L.close()` (`pi.py` close) |
| D3 | a failed `disconnect()` forgets its devices, so the retry cannot finish | **design:** `disconnect` clears the registry and keeps the lock; the GUI's shutdown retries per device through `api.devices.close(name)` and calls `disconnect` last. `test_disconnect_reports_a_failed_close` asserts the empty status. Script callers of `disconnect()` get one attempt |
| D12, D16, P2, P16, P17 | iXon found cold, e-stop with a motion in flight, kill mid-recording, stall during a ramp, late .cal / motor rows | already tested; behave as specified |

## How the list was made
Three `general-purpose` review sessions (one lens each, read-only, graph query first) returned 16-18 scenarios each
with file:line, expected behaviour and a sim test idea. Their claims were then checked here by reading the cited code
and by `scratchpad/probe_faults.py` on the simulators (D1, G1, G7). The sessions' line numbers were approximate in
places; the claims that mattered were all checkable.
