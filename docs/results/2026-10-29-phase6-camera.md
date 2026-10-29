# Phase 6: the real JAI camera through `mtpy.api` on the rig (2026-10-29)

Owner's go-ahead in chat ("Yes, go ahead"; LabVIEW closed; pixel-size re-measure skipped). Rig state `assembled`,
no experiment; channel mounted (H2A tailless, aggregated: bench use only). Every run inside V6
`tools/rig_session.py --no-motor-session` (lock holder `V6-chat`, `permitted` polled every 30 s, job tree killed and
verified gone at the end, lock released). Nothing moved; the motors stayed simulated.

Code: commit 31bdfef + this one (`src/mtpy/devices/jai.py`, `devices.make({"backend": "real"})`, GUI Setup
"Backend" combo / `--backend real`, `tools/phase6_camera.py`).

## 1. The camera as the API sees it

| item | value (read from the camera) |
|---|---|
| identity | SP-5000M-USB, serial 000014FB0067A270, firmware 0.2.0.0, port `cam1`, driver NI-IMAQdx niimaqdx.dll |
| after open (.icd) | 1280 x 1024, binning 2, 90.0009 Hz, exposure auto `Continuous` 1909 us, payload 1 310 720 B |
| preset "tracking 150 Hz" {rate_Hz 150, exposure_ms 1.909} read back | rate **150.0** Hz (the camera reads back the request exactly; the simulator's 149.9925 came from a 1 us period quantisation that the real one does not show), exposure 1.909 ms, ExposureAuto `Off` |
| timings (probe under the lock) | `IMAQdxOpenCamera` **10.7 s** (reloads the .icd); readback 0.01 s; configure + start 0.2 s; first frame 0.01 s; stop 0.07 s; close 0.0 s |

The 10.7 s open exceeded the device service's 5 s reply timeout on the first attempt (camera shown as "no reply for
5 s", U8). `Device.open_timeout_s` (30 s for the JAI) now covers the open; every other call is far under 5 s.

## 2. The measurement: 150 Hz, 5 min, GUI running, three window drags

`tools/phase6_camera.py --minutes 5` (run 2, 22:10:51): the GUI window open with the live camera view and the
2 Hz status tick, recording to HDF5 (`bench_out/phase6/phase6_20261029_221051.h5`, local, git-ignored), no beads
tracked (no calibration for this channel), motor poller reading the simulated magnet and rotor at 20 Hz. The window
was dragged three times by real mouse input on its title bar (3.7 s each, the Windows modal move loop on the UI
thread: the case where LabVIEW loses frames, decision 0008).

| quantity | value |
|---|---|
| frames received / buffer span | **44 984 / 44 984** (buffers 0..44983, 300 s) |
| camera gaps (`lost_before` sum) | **0** |
| gaps during the three drags (638 / 636 / 635 frames each) | **0 / 0 / 0** |
| pipeline drops, frames not written | 0, 0 |
| frame-rate triple in the run file (preset / read back / measured) | 150.0 / 150.0 / 149.944 Hz |
| PC receive interval | mean 6.669 ms, p50 6.668, p99 7.22, max 23.2 ms (5 intervals > 10 ms, 1 > 20 ms; absorbed by the 100-buffer ring, no gap) |
| receive -> result latency (no tracking) | p50 0.08 ms, p99 0.17 ms |
| display updates | 9000 (30 per second) |
| cleanup | acquisition stopped, session closed, devices disconnected; rig_session: job gone, no LabVIEW, lock released |

Measured rate 149.944 Hz against 150.0 read back (0.04 % low): the PC receive clock over 300 s against the camera's
own period; the same 149.7-149.9 seen in V6 (`camera-acquisition-facts.md`). Not a loss (the buffer numbers are
contiguous).

## 3. Compared with MT_LabVIEW

MT_LabVIEW's own recordings at 90 Hz with 5-7 beads tracked on the frame loop (`.tra` frame column = buffer number,
gaps = lost frames; counted with `mtpy.lvfiles.read_tra`):

| file (2026-09-06 data) | rows | buffer span | lost | lost share | gaps | largest gap |
|---|---|---|---|---|---|---|
| `test/tra002-000` | 10 043 | 11 821 | 1 778 | 15 % | 124 | 40 |
| `tra001-000` | 100 081 | 127 346 | 27 265 | 21 % | 13 381 | 16 |

Python, this run: 0 of 44 984 at 150 Hz, display on, window dragged. The earlier Python recorder (`refbead_record.py`,
30 min at 150 Hz, no GUI) lost 76 of 269 824 in three bursts ([2026-10-26-refbead.md](2026-10-26-refbead.md) section
9); this 5 min run saw none, so the long-run burst cause stays open (a 30 min run with the GUI is the next soak).

**Plan phase 6 criterion met for the camera path:** frame loss at 150 Hz is zero against MT_LabVIEW's 15-21 % at
90 Hz, and dragging the window loses no frames. **Not covered:** the same with beads tracked (needs a calibration on
this channel: the tracking kernel then adds about 1-6 ms per frame on the worker thread, which the ring decouples
from the camera thread, but it is unmeasured on the rig); a run longer than 5 min.

## 4. Pixel size at 50x

Already measured on 2026-10-26: about 203 nm/px (X 204.6 / Y 200.5; [2026-10-26-refbead.md](2026-10-26-refbead.md)
section 1, `docs/rig/core-parameters.md`). A re-measure needs ASI moves (phase 7); skipped on the owner's word.

## 5. Open points carried

1. **Gain** is read-only on the real camera: `AnalogControl::Gain` reads 16.0 with `GainAuto Continuous` and
   `GainSelector Digital All`; its unit against the API's `gain_dB` is not verified. The GUI preset leaves gain out
   on the real backend. Owner decision needed before gain is written.
2. **ROI writes** (`OffsetX/Y`, `Width/Height`) are implemented as the manual describes but were not exercised on the
   rig in this phase (the run used the full 1280 x 1024).
3. `phase6_camera.py`'s `QApplication.quit()` from the job thread did not end the Qt loop on the rig (both runs hung
   after the summary until the wrapper's time limit killed the process; the camera was already closed). The driver
   now ends with `os._exit` after the summary.
4. Auto exposure: the preset writes `ExposureAuto Off` with the exposure; the original program leaves auto exposure
   on (manual, open question 2).
