# The iXon Ultra 897 cooler does not stop on `CoolerOFF` (rig, 2026-10-30 evening)

**What happened.** The owner closed the program after an experiment; the EMCCD step of the shutdown dialog waited the
full 15-min warm-up twice and failed ("sensor still below -20 C"). The camera body was warm to the touch; no Solis
on the PC. Before the Python program the owner had used the LabVIEW program, whose close path may not switch the
cooler off (owner 2026-10-31: "아마 랩뷰에 close connection 부분이 코딩 안되었는지도 모르겠네").

**Probes** (SDK only, no motion, under the rig lock; the GUI's stale lock taken over on the owner's word
"락 넘겨받아도 됨"; full log in the session scratchpad `ixon_cooler_probe.log`):

| probe | sent | sensor (GetTemperatureF) | IsCoolerOn | GetTemperature status |
|---|---|---|---|---|
| 1, 20:38 | nothing, 2 min | -78.83 -> -78.82 C | 1 | off |
| 1, 20:40 | `CoolerOFF`, 3 min | -78.82 -> -78.80 C | 1 | off |
| 2, 20:57 | `SetCoolerMode(0)` + `CoolerOFF`, 3 min | -79.04 -> -81.19 C | 1 | off |
| 3, 21:49 | `SetTemperature(20)` + `CoolerON` | -80.06 -> +13.26 C in 4 min (about 30 C/min at first) | 1 | off |
| 3, 21:53 | `SetCoolerMode(0)`, `CoolerOFF`, 30 s, `ShutDown` | +17.1 C | 1 | off |

**Findings.**
1. `CoolerOFF` returns success and changes nothing on this camera; `SetCoolerMode(0)` neither.
2. The camera warms itself when the set point is raised: `SetTemperature(top of range)` + `CoolerON` is the
   controlled warm-up (the SDK release notes say the Ultra keeps its cooler always on, so the set point is the only
   handle).
3. `IsCoolerOn` read 1 throughout and the `GetTemperature` status read "off" while the sensor sat at -80 C: neither
   flag is usable; only the temperature trajectory is.
4. The SDK 2.104 manual marks the "warm above -20 C before `ShutDown`" notes "Classic & ICCD only"; the Ultra 897
   hardware guide has no warm-up instruction. The -20 C rule is kept for now (owner's call).
5. Who cooled the camera to -80 C before the 18:47 session is not established (it was warm at 17:0x; cold within
   30 s of the next connect). The LabVIEW program run in between is the likely owner.

**Changes made (commit after this doc).** `IxonCamera.open` reads the temperature first, records it in the identity
(`found_at_open`) and adopts a sensor below -20 C as the set point; `close` warms up through the set point, judged by
the temperature only, and fails within `stall_s` (60 s) when the reading does not move instead of after 15 min.

**GUI (2026-10-31).** "Close anyway" from the Disconnect button now ends the program like the window X. A device
whose close failed stays listed and is reopened by the next close on purpose (the cleanup must really happen); with
the stall check that retry costs about a minute, not fifteen. The motors already reset their state at
open (PI: limits written, reference, readback; ASI: limits from the current position), so the owner's "check, reset,
then connect" rule holds there; a COM port held by another process still fails the open with its error.

**Rig check 2026-10-31 17:35.** The owner's MT Tracker left running (MT mode, started 16:15) was closed by WM_CLOSE on
the owner's word; the shutdown sequence finished and released the lock within 5 s. Then `api.devices.connect` in MT
mode (EMCCD powered off): 5/5 connected in 20 s, `disconnect` clean in 1.0 s (PI home with the ERR? drain), lock
released. The iXon open/close path is still unverified on the camera (powered off today).
