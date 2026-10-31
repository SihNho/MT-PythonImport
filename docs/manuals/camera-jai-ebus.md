# JAI SP-5000M-USB through the eBUS SDK (decision 0028)

What `src/mtpy/devices/ebus.py` needs and what the rig showed on 2026-11-01. The camera itself (optics, units, pitfalls
of the sensor) is in [camera-jai-imaqdx.md](camera-jai-imaqdx.md); only the SDK path differs.

## Installation on the rig PC
- JAI "eBUS SDK 64-bit for JAI" 6.5.3.7155 (download from jai.com, product page SP-5000M-USB), installed by the owner
  2026-10-31. Runtime: `C:\Program Files\Common Files\Pleora\eBUS SDK\` (`PvDotNet.dll`, `Pv*64.dll`,
  `EBusDriverInstallationTool64.exe`), SDK: `C:\Program Files\JAI\eBUS SDK\` (C++ headers, samples, `eBUSPlayerJAI64.exe`).
- **The installer binds the camera to Pleora's USB3 Vision driver** (`ebuniversalproforu3v.inf`, class
  `PleoraU3VClass`). NI-IMAQdx and LabVIEW then enumerate no camera. To go back: eBUS Driver Installation Tool or
  Device Manager -> Update driver -> NI's `niu3vk.inf` (still in the driver store).
- Python side: `pythonnet` (pip) and the .NET Framework 4.x (`PvDotNet.dll` targets v4.0.30319; `csc.exe` of
  `C:\Windows\Microsoft.NET\Framework64\v4.0.30319` builds the helper).

## API pattern used (PvDotNet)
```
system = PvSystem(); system.Find(); info = system.GetInterface(i).GetDeviceInfo(j)      # PvDeviceInfoU3V
dev = PvDevice.CreateAndConnect(info); P = dev.Parameters                              # GenICam, SFNC names
stream = PvStream.CreateAndOpen(info); pipe = PvPipeline(stream)
pipe.BufferSize = dev.PayloadSize; pipe.BufferCount = 100; pipe.Start()
dev.StreamEnable(); P.ExecuteCommand("AcquisitionStart")
res, buf = pipe.RetrieveNextBuffer(PvBuffer(), 1000)      # pythonnet: a ref arg takes an instance, returns the real one
  buf.OperationResult.IsOK, buf.BlockID, buf.Timestamp, buf.Image (Width, Height, DataPointer) ... pipe.ReleaseBuffer(buf)
P.ExecuteCommand("AcquisitionStop"); dev.StreamDisable(); pipe.Stop(); stream.Close(); dev.Disconnect()
```
- `RetrieveNextBuffer` with a third `PvResult` ref argument cannot be called from pythonnet (`PvResult` has no
  parameterless constructor); the two-argument form plus `buf.OperationResult` is used.
- `DataPointer` (`Byte*`) arrives as an opaque `System.Reflection.Pointer`; neither `int()`, `IntPtr` nor `Attach`
  with an `IntPtr` work. The helper `Mtpy.MtpyEbus.ImageAddress(PvImage) -> long` (C#, `unsafe`) gives the address;
  the frame is copied with `ctypes.string_at(addr, w * h)` (0.33 ms per 1280 x 1024 frame). `MtpyEbus.Attach` can
  attach numpy memory to a `PvBuffer` (zero-copy, not used yet).

## Parameters (GenICam, as read on the rig)
| name | value / range | used as |
|---|---|---|
| `ExposureTime` | 1909 us; 10 .. 11053 us | `exposure_ms` x 1000; writing sets `ExposureAuto` = Off first |
| `ExposureAuto` | Continuous (as found) | read back |
| `AcquisitionFrameRate` | 90.0009 Hz; 0.125 .. 247.9544 Hz | `rate_Hz` |
| `Gain` / `GainRaw` / `GainAuto` | 16.0 (1 .. 16) / 1600 / Continuous | `gain_dB` read-only (unit unverified, as with IMAQdx) |
| `OffsetX`, `OffsetY`, `Width`, `Height` | 0, 0, 1280, 1024 (`WidthMax` 2560, `HeightMax` 2048: binning 2) | `roi` |
| `PixelFormat` | Mono8 | one byte per pixel |
| `DeviceFirmwareVersion` / `DeviceVersion` | 0.2.0.0 / 0.3.0.0 | identity |
| `DeviceTemperature` | 33.7 C | - |
| `PvBuffer.Timestamp` | 1 GHz ticks (10.18 s of wall time = 10 182 052 020 ticks) | `t_camera_s` since the first frame |
| `PvBuffer.BlockID` | 0-based per acquisition, consecutive | `buffer_number`; a gap = a frame the PC missed |

## Measured
| condition | frames / 10 s | gaps | dropped | copy ms p50 / p99 |
|---|---|---|---|---|
| probe, 90.0009 Hz, 1909 us | 900 (88.8 Hz incl. start-up) | 0 | 0 | 0.33 / 0.51 |
| probe, 150 Hz, 1909 us | 1500 (149.0 Hz) | 0 | 0 | 0.32 / 0.47 |
| program `api.acq`, 90 Hz | 901, fps 89.98 (camera clock) | 0 | 0 | latency 0.08 / 0.19 ms |
| program `api.acq`, 150 Hz | 1500, fps 149.95 | 0 | 0 | latency 0.09 / 0.20 ms |

## Open
- `Gain` unit and whether the program should write it.
- A longer run (minutes) for loss statistics; the IMAQdx path had 0 of 44 984 frames lost at 150 Hz.
- Hardware trigger / strobe lines (`LineSelector`, `PulseGenerator*`) for the Arduino sync (decision 0005).
