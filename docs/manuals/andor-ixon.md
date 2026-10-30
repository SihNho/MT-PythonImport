# Andor iXon Ultra EMCCD through Andor SDK2 (`atmcd64d.dll`)

## Purpose on the rig

Not on the rig yet. Planned for MT-TIRF: the iXon records fluorescence **at the same time** as the JAI tracks beads.
It does not free-run: it is triggered externally by the Arduino frame divider, one EMCCD frame per N JAI frames
(decision 0005, [arduino-sync.md](arduino-sync.md)). The PC never generates its frame triggers.

## Connection

| item | value | evidence |
|---|---|---|
| interface | USB (Andor kernel driver `atmcd.inf` "AndorWDM" 4.33.0.0 and Andor `libusb0` 1.2.6.0 in the driver store) | `pnputil /enum-drivers`, read 2026-10-22 |
| camera | **connected on USB since 2026-10-30**: `DU897_BV` serial 10233, 512 x 512, found and initialised by `mtpy.devices.ixon` ([results/2026-10-30-emccd-first-contact.md](../results/2026-10-30-emccd-first-contact.md)); on 2026-10-22 `GetAvailableCameras` had returned 0 cameras | rig probe 2026-10-30 |
| trigger input | EXT TRIG (TTL) from the Arduino D9 output; level and connector not checked | decision 0005 |
| model | **iXon Ultra 897** (512 × 512, 16 µm pixels) per the owner's optical schematic of 2026-10-06 ([hardware/mt-tirf-optical-layout.svg](../hardware/mt-tirf-optical-layout.svg), read 2026-10-24); earlier entry "exact model unknown" | owner's schematic |

## Driver / SDK

- **Andor Driver Pack 2 v2.104.30065.0**, `C:\Program Files\Andor Driver Pack 2\` - `atmcd64d.dll` (file version
  2.104.30065.0), `atmcd32d.dll`, `ATMCD64CS.dll`, `ATSpectrograph\`, device drivers. It **loads on this PC**.
- No C header (`ATMCD32D.H`) is installed; it ships with the full Andor SDK2. The function list below is from the
  Andor SDK2 manual.
- LabVIEW wrappers: `C:\Program Files\National Instruments\LabVIEW 2026\instr.lib\atmcd64d.llb` (and
  `atmcd64d_internal.llb`, `AndorUtils.llb`).
- Every SDK2 function returns an unsigned int: **20002 = `DRV_SUCCESS`**; anything else is an error code.

## Command table

"4.4 VI" = `G:\Codes\LabVIEW_Codes\MinLab\zz_LabView VI\AAA_UNIST\2. Tracking\Min_Track N beads
4.4_KimLabMTroom_EMCCD.vi`, an older EMCCD version of the program. Its subVI list names these Andor VIs (read from the
file bytes on 2026-10-22, no LabVIEW; **names only - its wiring was never read**). The running program
(4.5 3StateClamping) uses no Andor function.

| function | meaning | arguments + units | response | LabVIEW use | level + evidence |
|---|---|---|---|---|---|
| `GetAvailableCameras(int* n)` | count cameras (works before `Initialize`) | - | rc 20002, n | 4.4 VI | **V2** - rc 20002, n = 0 (camera not connected) |
| `GetCameraHandle(index, int* handle)` / `SetCurrentCamera(handle)` | select a camera | index 0.. | rc, handle | 4.4 VI (`GetCameraHandle`) | **V0** - SDK2 manual |
| `Initialize(char* dir)` | open the camera, load firmware/config (takes seconds) | directory of the `.cof` files (`""` = DLL folder) | rc 20002 | 4.4 VI | **V0** |
| `GetDetector(int* x, int* y)` | sensor size | - | pixels | 4.4 VI | **V0** |
| `GetCameraSerialNumber(int*)` | serial number | - | number | not seen | **V0** |
| `SetTemperature(int degC)` / `CoolerON()` / `CoolerOFF()` | cooling set point and cooler | deg C | rc | 4.4 VI | **V0** |
| `GetTemperature(int* degC)` | sensor temperature and cooling state | - | rc 20036 `DRV_TEMP_STABILIZED`, 20037 `NOT_REACHED`, 20035 `NOT_STABILIZED`, 20034 `TEMP_OFF` | 4.4 VI | **V0** |
| `SetFanMode(int)` | 0 full, 1 low, 2 off | - | rc | 4.4 VI | **V0** |
| `SetAcquisitionMode(int)` | 1 single scan, 2 accumulate, 3 kinetics, 4 fast kinetics, 5 run till abort | - | rc | 4.4 VI (`Single Scan`, `Kinetics`, `Fast Kinetics` appear as strings) | **V0** |
| `SetReadMode(int)` | 4 = image | - | rc | 4.4 VI | **V0** |
| `SetImage(hbin, vbin, hstart, hend, vstart, vend)` | binning and ROI | pixels, 1-based, inclusive | rc | 4.4 VI | **V0** |
| `SetExposureTime(float s)` | exposure | **seconds** | rc | 4.4 VI (panel `Exposure (ms)`) | **V0** |
| `SetTriggerMode(int)` | 0 internal, 1 external, 6 external start, 7 external exposure (bulb), 10 software | - | rc | 4.4 VI (`External Exposure (Bulb)` string) | **V0** |
| `SetFrameTransferMode(int)` | 0 off, 1 on | - | rc | 4.4 VI | **V0** |
| `SetEMGainMode(int)` / `SetEMAdvanced(int)` / `SetEMCCDGain(int)` / `GetEMGainRange(int*, int*)` / `GetEMCCDGain(int*)` | EM gain mode, unlock gain > 300, set / read gain | gain units per mode | rc | 4.4 VI | **V0** |
| `SetHSSpeed(type, index)` / `SetVSSpeed(index)` / `GetNumberVSSpeeds(int*)` / `SetADChannel(int)` | readout speeds | indices | rc | 4.4 VI | **V0** |
| `SetShutter(type, mode, closingMs, openingMs)` | internal shutter: mode 0 auto, 1 open, 2 closed | ms | rc | 4.4 VI | **V0** |
| `GetAcquisitionTimings(float* exp, float* acc, float* kin)` | the timings the camera will really use | seconds | rc | 4.4 VI | **V0** |
| `PrepareAcquisition()` / `StartAcquisition()` / `AbortAcquisition()` | arm, start, stop | - | rc | 4.4 VI | **V0** |
| `GetStatus(int*)` | 20073 `DRV_IDLE`, 20072 `DRV_ACQUIRING` | - | rc, status | not seen | **V0** |
| `GetTotalNumberImagesAcquired(long*)` / `GetNumberNewImages(long*, long*)` | frame counters (for the per-frame alignment with JAI buffers) | - | counts | not seen | **V0** |
| `GetOldestImage16` / `GetMostRecentImage16` / `GetImages16(first, last, buf, size, validFirst*, validLast*)` | read frames from the SDK ring as uint16 | buffer, pixel count | rc 20002, 20024 `DRV_NO_NEW_DATA` | 4.4 VI uses `GetNewData` (older, int32) | **V0** |
| `ShutDown()` | close the camera | - | rc | 4.4 VI | **V0** |

## Units, signs and offsets

- Exposure in **seconds** (`float`), not ms. Temperatures in deg C. Image coordinates are 1-based and inclusive.
- Alignment with the JAI (decision 0005): EMCCD frame m belongs to absolute JAI buffer numbers [mN, (m+1)N); the
  data file stores the absolute JAI buffer number. Totals are checked as EMCCD frames = JAI buffers / N.

## Safety envelope and what to restore after a job

- No motion. The rig lock applies (the iXon is listed as a rig device in RULES.md section 2).
- **Before `ShutDown`**: `AbortAcquisition`, close the shutter, then warm the sensor above -20 deg C **through the
  set point** (`SetTemperature(top of range)` + `CoolerON`; the camera regulates the rate), then `CoolerOFF`,
  `ShutDown`. On the rig's Ultra 897 `CoolerOFF` (also after `SetCoolerMode(0)`) returned success and the sensor
  stayed at -80 C for 30 min; `IsCoolerOn` stayed 1 and the `GetTemperature` status said "off" while cooling, so
  only the temperature trajectory is trusted (results/2026-10-30-ixon-cooler.md). The -20 C rule is marked
  "Classic & ICCD only" in the SDK 2.104 manual; kept for the Ultra until the owner decides otherwise.
- **At open**: read `GetTemperature` first; a sensor below -20 C (left cooling by LabVIEW or a crashed process) is
  adopted as the set point and recorded in the identity (`found_at_open`), so the read-back is true and the close
  warms it up (owner 2026-10-31).
- Light: high EM gain with bright light can damage the EM register; keep EM gain off or low until the light level is
  known, and keep gain > 300 locked (`SetEMAdvanced` off) unless the owner decides otherwise.
- Restore: shutter closed, cooler off and warmed, `ShutDown` called, process gone. A crashed process that never called
  `ShutDown` can block the next `Initialize`.

## Known pitfalls

1. `Initialize` takes several seconds and must be followed by `ShutDown` in every exit path.
2. One process owns the camera. Andor Solis or a LabVIEW VI holding it blocks the port.
3. Use the 64-bit `atmcd64d.dll` from 64-bit Python; `atmcd32d.dll` is for 32-bit processes.
4. External-trigger semantics differ by mode (External, External Exposure, Frame Transfer + External): in
   External Exposure the pulse width from the Arduino (k JAI frames) sets the exposure.
5. The 4.4 VI contains the string "EMCCD has problem. Restart computer." - past failures needed a reboot; the cause is
   not recorded.

## Open questions for the owner

1. ~~The exact iXon model~~ answered: **iXon Ultra 897** (owner's optical schematic, see the table above). Still
   open: cooling (air or liquid)?
2. Which trigger mode (External, External Exposure, or Frame Transfer + External)? It decides what k means.
3. Voltage levels: Arduino D9 is 5 V TTL; does the iXon EXT TRIG input accept it as wired?
4. Is the 4.4 VI's EMCCD set-up (gain, speeds, temperature) the reference for the port, and should its wiring be read?
5. Is there a licensed full SDK2 (header, examples) somewhere, or only the Driver Pack?
