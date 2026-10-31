# 0028 — The JAI camera runs through JAI's eBUS SDK; the camera is bound to Pleora's USB3 Vision driver

**Decided:** 2026-11-01 (owner, in chat): "eBUS로 간다", after installing the eBUS SDK 6.5.3 ("설치함") and being told that
the installer had bound the camera to Pleora's driver so IMAQdx (and LabVIEW) no longer see it.

## Decision
1. **The real JAI SP-5000M-USB is driven through the eBUS SDK's .NET API** (`PvDotNet.dll`, pythonnet) by
   `src/mtpy/devices/ebus.py` (`EbusCamera`). It is the default camera of the `real` and `real-motors` backends.
   The IMAQdx driver (`jai.py`, decision 0021) stays in the tree and is selected with the preset key
   `"camera_sdk": "imaqdx"`; it works only while the camera is bound to NI's USB3 Vision driver.
2. **The camera stays bound to Pleora's USB3 Vision driver** (`ebuniversalproforu3v.inf` 7.2.5, bound by the eBUS
   installer 2026-10-31 23:59). Consequence, accepted by the owner: **LabVIEW and NI-IMAQdx cannot open the camera**
   until the binding is changed back (NI's `niu3vk.inf` 26.3 is still in the driver store; eBUS Driver Installation
   Tool or Device Manager). The LabVIEW program is the baseline for numbers (0023), not a tool that must keep running.
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
