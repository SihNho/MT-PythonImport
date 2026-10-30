# The Andor iXon Ultra through `api.emccd` on the rig: first contact (2026-10-30)

Owner in chat, 2026-10-30: "모터 연결작업이랑 EMCCD 연결작업 지금 해보자" and, for the iXon Ultra, "핵심 파라미터들 조절 가능할 것 [exposure time, frame rate, gain mode, gain, temperature]" and later "모든 파라미터들을 조절 가능해야함" (the JAI too).
The motors were already on the rig that morning ([2026-10-30-phase7-motors.md](2026-10-30-phase7-motors.md)); this
note is the EMCCD. Rig state `assembled`, no experiment; four probe runs of `tools/emccd_probe.py` inside V6
`tools/rig_session.py --no-motor-session` (lock holder `V6-chat`, released after each; logs V6
`tools/bench/l2s_emccd_probe{,2,3,4}.log`). Nothing moved; the motors stayed simulated (`real` backend).

Code: `src/mtpy/devices/ixon.py` (`IxonCamera`, device "emccd", Andor SDK2 `atmcd64d.dll` through ctypes; the
simulator `SimEmccd` is the same driver on `FakeAndor`), `src/mtpy/api/emccd.py` (set_exposure, set_rate,
set_gain_mode, set_gain, set_temperature, apply_preset, settings, snap), the GUI Setup group "EMCCD", tests
`tests/test_emccd.py`.

## 1. The camera as the API sees it (run 4, 09:14)

| item | value (read from the camera) |
|---|---|
| identity | `DU897_BV`, serial 10233, 512 x 512, USB; the Driver Pack 2 `atmcd64d.dll` v2.104 loads and finds it (the manual's "not connected" entry of 2026-10-22 is outdated: the camera is on USB now) |
| open | `Initialize` + set-up about 4 s (the `real` backend's connect, JAI included, 13.7-15.9 s) |
| after open | exposure 0.001 ms, rate 40.665 Hz (= 1 / readout), EM gain mode 0, EM gain 0, cooler off, sensor 14 C |
| readout time | **24.59 ms** per frame at 512 x 512, EM amplifier, HS speed index 0, fastest recommended VS speed (measured at open as kinetic cycle - exposure with the cycle at its fastest) |
| ranges | EM gain 1..222 in mode 0 (0 = off is accepted; the camera reads 0 at open), temperature -120..20 C |
| shutter | `SetShutter(1, 0, 0, 0)` and `(1, 0, 10, 10)` answer 20068 (`DRV_P3INVALID`): no internal shutter is set; recorded in the identity, not an error |

## 2. The five parameters, set and read back (run 4)

| step | result |
|---|---|
| preset {gain mode 0, gain 0, exposure 30 ms, rate 18 Hz, temperature 0 C} | read back 0 / 0 / 29.99999933 ms / **17.989 Hz** / 0 C; cooler on, status `not reached` |
| snap (acquisition started by the snap) | 512 x 512 uint16, min 124, max 278, mean 201.4 (no light; bias about 200 counts) |
| exposure 15 ms while acquiring | abort, apply, restart: read back 14.9999997 ms, rate still 17.994 Hz, acquiring |
| disconnect | cooler off, sensor 15 C (above -20 C: no wait), `ShutDown`, 1.2 s; rig_session: job gone, lock released |

**Frame transfer is OFF** so exposure and rate are independent: frame period = exposure + 24.59 ms readout. Run 3
asked 20 Hz with 30 ms and the camera read back 18.318 Hz (= 1 / 54.6 ms): the API now refuses a rate above
1 / (exposure + readout) and an exposure above period - readout with the allowed range in the message, instead of a
silent lengthening of the period (U15). With frame transfer ON the 897 would reach 1 / max(exposure, readout) but the
exposure then equals the period; the owner decides which mode MT-TIRF needs (manual open question 2, trigger mode).

## 3. What the probe did not exercise

- EM gain above 0 and modes 1-3 on the real camera (sim only): the light level on the sensor is unknown; the manual's
  safety envelope keeps EM gain low until it is. Gain above the range stays locked (`SetEMAdvanced` never called).
- Real cooling: the set point was 0 C (sensor 14 -> cooler on, not reached, cooler off). A -70 C session ends with
  the warm-up wait before `ShutDown` (close waits until the sensor is above -20 C, up to 15 min
  (`close_timeout_s`); the GUI's Disconnect blocks for that time).
- External trigger from the Arduino (decision 0005), the acquisition pipeline and recording: plan phase 10a.
- The other parameters (ROI, binning, readout speeds, pre-amp gain, fan, baseline clamp) stay at smCamera's fixed
  set-up; "every parameter adjustable" (owner) is the next step after the afternoon's JAI + iXon measurement.

## 4. Using it this afternoon

GUI with both cameras under the rig lock (from the V6 folder; the motors stay simulated):

```
py tools/rig_session.py --purpose "JAI + iXon" --no-motor-session --max-min 180 -- G:\Codes\LabVIEW2Scr\.venv\Scripts\python.exe -m mtpy.gui --backend real --out G:\Codes\LabVIEW2Scr\runs
```

Setup tab: Connect; the "EMCCD" group sets the five parameters with read-back and snaps one frame into the image
view; the 2 Hz status line shows exposure, rate, gain mode, gain, set point, sensor temperature and cooler status.
`--backend real-motors` adds the real motors through the motion gate (decision 0025).
