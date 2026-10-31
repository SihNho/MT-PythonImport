# 0028 — Two camera SDKs, chosen in Setup: IMAQdx (default, NI driver, shared with LabVIEW) and JAI's eBUS SDK (Pleora driver)

**Decided:** 2026-11-01 (owner, in chat): "eBUS로 간다", after installing the eBUS SDK 6.5.3 ("설치함") and being told that
the installer had bound the camera to Pleora's driver so IMAQdx (and LabVIEW) no longer see it.

**Amended the same day** (owner: "우선은 그럼 NI 드라이브로 돌리고, IMAQdx 경로로 되돌리자. eBUS 경로 및 IMAQdx 경로를 장비
셋업창에서 선택할 수 있으면 좋을듯"): the LabVIEW program is still the one the experiments run on, and a USB device
carries one driver, so the camera goes back to NI's driver, IMAQdx is the default again, and the Setup panel chooses
the SDK. eBUS stays ready for the day the program replaces LabVIEW (switch the driver, pick eBUS).

## Decision
1. **Both SDKs are in the tree; the Setup panel's "Camera SDK" box (preset key `camera_sdk`) chooses:**
   `imaqdx` (default; `jai.py`, decision 0021; the camera bound to NI's USB3 Vision driver, which LabVIEW shares) or
   `ebus` (`src/mtpy/devices/ebus.py`, `EbusCamera`, the eBUS SDK's .NET API `PvDotNet.dll` via pythonnet; the camera
   bound to Pleora's driver). The chosen SDK must match the driver the camera is bound to; the other one enumerates
   no camera and says so.
2. **The driver binding is the owner's system setting.** The eBUS installer bound the camera to Pleora's
   `ebuniversalproforu3v.inf` 7.2.5 (2026-10-31 23:59); the owner binds it back to NI's `niu3vk.inf` 26.3 (eBUS Driver
   Installation Tool or Device Manager) for the LabVIEW experiments. While it is on Pleora's driver, **LabVIEW and
   NI-IMAQdx cannot open the camera**.
3. **Pointer access through a 10-line C# helper** (`src/mtpy/devices/ebus_helper/MtpyEbus.cs`): pythonnet exposes
   `Byte*` as an opaque `System.Reflection.Pointer`, so the helper returns the buffer address as a long; it is built
   on first use with the .NET Framework's own `csc.exe` (the built DLL is git-ignored). `pythonnet` becomes a project
   dependency.
4. **Frame contract (decision 0005 amended for this camera):** `buffer_number` = the U3V `BlockID` (0-based per
   acquisition), `t_camera_s` = the camera's own timestamp (`PvBuffer.Timestamp`, 1 GHz ticks on this camera) relative
   to the first frame of the acquisition. The JAI does have a hardware timestamp; IMAQdx did not expose it.

## Evidence (rig, 2026-11-01 00:07-00:12)
- eBUS enumerates `SP-5000M-USB [14FB0067A270]`, serial U500336, SuperSpeed, Pleora driver installed.
- Probe (PvPipeline, 64 buffers): as found 90.0009 Hz / 1909 us: 900 frames in 10.1 s, BlockID 0..899, gaps 0,
  dropped 0, copy 0.33 / 0.51 ms (p50 / p99). 150 Hz / 1.909 ms: 1500 frames, BlockID 0..1499, gaps 0, dropped 0.
- Through the program (`api.devices.connect` real-motors MT, `api.acq`): 90 Hz 901 frames, 150 Hz 1500 frames, camera
  gaps 0, pipeline drops 0, latency 0.08 / 0.19 ms; connect 8.3 s, disconnect 1.1 s, lock released.
- GenICam names used: `ExposureTime` (us, 10..11053), `ExposureAuto`, `AcquisitionFrameRate` (0.125..247.95 Hz),
  `Gain` (1..16, own unit; `GainRaw` 100..1600), `OffsetX/Y`, `Width/Height`, `DeviceFirmwareVersion`.

## Follows
- Manual: [manuals/camera-jai-imaqdx.md](../manuals/camera-jai-imaqdx.md) "Driver / SDK" (binding) and a new
  [manuals/camera-jai-ebus.md](../manuals/camera-jai-ebus.md).
- Open: the `Gain` unit (read-only until the owner decides, as before); the hardware timestamp against the PC clock
  (fps measured 149.95 from it, consistent); the eBUS GenTL / Python packages Pleora ships separately were not needed.
