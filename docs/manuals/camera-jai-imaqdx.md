# JAI SP-5000M-USB camera through NI-IMAQdx

## Purpose on the rig

The bead-tracking camera. It free-runs on its own clock (no trigger) and every frame is tracked in x, y, z. It is also
the master clock of the planned MT-TIRF synchronisation: its exposure output drives the Arduino frame divider, which
triggers the iXon (decision 0005, [arduino-sync.md](arduino-sync.md)). Nothing on the camera moves, but a session left
acquiring keeps the sensor and USB link busy; every job must stop acquisition and close the session.

## Connection

| item | value | evidence |
|---|---|---|
| interface | USB 3.0 (SuperSpeed), USB3 Vision; Windows device "NI-IMAQdx USB3 Vision Device", VID_14FB (JAI) PID_1006 | V6: `docs/camera-acquisition-facts.md:640-643` |
| IMAQdx name | **`cam1`** (not `cam0`) | `IMAQdxEnumerateCameras`, V6: `docs/camera-acquisition-facts.md:16` |
| identity | JAI Corporation SP-5000M-USB, serial `000014FB0067A270`, DeviceVersion `0.3.0.0`, firmware `0.2.0.0` | V6: `tools/bench/imaqdx_attributes.txt` |
| sensor | e2v Lince5M CMOS, 2560 x 2048, 5 um pixels, global shutter, mono | V6: `docs/camera-acquisition-facts.md:640-643` |
| camera file | `C:\Users\Public\Documents\National Instruments\NI-IMAQdx\Data\JAI Corporation SP-5000M-USB (#000014FB0067A270).icd` - reloaded by **every** `IMAQdxOpenCamera` | V6: `docs/camera-acquisition-facts.md:643-647` (`tools/bench/diag_camrate_persist83.log`) |
| default timeout | `AcquisitionAttributes::Timeout` = 5000 ms (wait for a buffer); `AdvancedGenicam::CommandTimeout` = 100 ms | V6: `tools/bench/imaqdx_attributes.txt` |
| only one owner | a camera opened in Controller mode by one process (LabVIEW, NI MAX, a script) cannot be opened by another; close LabVIEW first | V6: `tools/bench/imaqdx_ctypes.py` message "not held by another process" |

## Driver / SDK

- **NI-IMAQdx 26.3** (part of NI Vision Acquisition Software 26.3). `C:\Windows\System32\niimaqdx.dll`, file version
  26.3.0f141. C header `C:\Program Files (x86)\National Instruments\NI-IMAQdx\include\NIIMAQdx.h`. LabVIEW VIs
  `C:\Program Files\NI\LVAddons\niimaqdx\1\vi.lib\vision\driver\IMAQdx.llb`.
- Calling convention (header lines 108-120): ordinary functions are `NI_FUNC` = `__stdcall`; `IMAQdxSetAttribute` and
  `IMAQdxGetAttribute` are `NI_FUNCC` = `__cdecl` and **variadic** (`IMAQdxSetAttribute(id, name, type, ...)`). On
  64-bit Windows both conventions are the same ABI; from Python use `ctypes.windll.LoadLibrary("niimaqdx.dll")`.
- Preserved ctypes reference: `third_party/mt_labview/tools/bench/imaqdx_ctypes.py` (structures `CameraInformation`,
  `AttributeInformation`, `EnumItem`; value-type codes U32 0, I64 1, F64 2, STR 3, ENUM 4, BOOL 5, CMD 6, BLOB 7).
- The C API needs no LabVIEW and opens no dialog; NI's example VIs with an empty camera name block on a modal dialog.
- **USB3 Vision driver binding (rig 2026-10-31/11-01).** The owner installed JAI's eBUS SDK 6.5.3.7155 (64-bit; the
  PC had 6.3.0 before) to look at it as the alternative of decision 0021. The installer re-bound the camera
  (`USB\VID_14FB&PID_1006`) to Pleora's USB3 Vision driver (`ebuniversalproforu3v.inf` = oem87.inf, 7.2.5.5600,
  installed 23:59:26). From then on IMAQdx enumerates no camera ("no camera enumerated", the program's connect at
  00:00:25 left the camera disconnected; the motors were fine), and LabVIEW would see the same. NI's own driver
  (`niu3vk.inf` = oem11.inf, 26.3.0) is still in the driver store, so the camera can be bound back (eBUS Driver
  Installation Tool, Device Manager "Update driver", or removing oem87.inf) - a system change the owner decides.
  The eBUS 6.5.3 package has C++ and .NET APIs only; the Python API is a separate Pleora download.

## Command table - C API functions

| command | meaning | arguments + units | response | LabVIEW program use | level + evidence |
|---|---|---|---|---|---|
| `IMAQdxEnumerateCameras(info*, count*, connectedOnly)` | list cameras; no session needed | call once with `info=NULL` for the count, then with an array of `CameraInformation` | `InterfaceName` `cam1`, vendor, model, serial `000014FB0067A270` | not used (the VI holds the name as a constant) | **V2** - V6: `docs/camera-acquisition-facts.md:16-17` |
| `IMAQdxOpenCamera(name, mode, session*)` | open a session | `name` = `b"cam1"`; `mode` 0 = Controller, 1 = Listener | rc 0, session id | `IMAQdx Open Camera.vi`, startup frame d87 (#33151) | **V3** - open resets ROI to 1280 x 1024 and exposure to `Continuous` / 1909 us, read back (V6: `docs/camera-acquisition-facts.md:418-440`, `tools/bench/imaqdx_reset_test.py`, `camera_contract.py`) |
| `IMAQdxConfigureAcquisition(session, continuous, bufferCount)` | set up the driver ring | `continuous` 1; `bufferCount` = ring depth (buffers of `PayloadSize` bytes) | rc 0 | `IMAQdx Configure Grab.vi` d87 (#13962) = continuous + start; its `Number of Buffers` value was not read | **V3** - 10 and 50 buffers measured (V6: `docs/camera-acquisition-facts.md:83-90`, `tools/bench/p1_bufmode_121.log`) |
| `IMAQdxStartAcquisition(session)` | start streaming | - | rc 0 | inside `Configure Grab.vi` | **V2** - V6: `tools/bench/p1_bufmode_121.log` |
| `IMAQdxGetImageData(session, buf, size, mode, desired, actual*)` | copy one buffer into caller memory | `mode`: 0 Next, 1 Last, 2 BufferNumber, 3 Every, 4 LastNew (header 178-185); `desired` = buffer number (mode 2); `size` = `PayloadSize` | rc 0, pixels in `buf`, the buffer number actually returned in `actual` | `IMAQdx Get Image.vi` inside `get buff image-lost frames.vi` (d157 #22692), called with `Buffer to extract` = `LastBufferNumber + 1`; the mode constant was not read | **V3** - all five modes at 90 and 150 Hz (V6: `docs/camera-acquisition-facts.md:728-759`, `tools/bench/p1_bufmode_121.log`) |
| `IMAQdxGrab(session, image*, waitForNext, actual*)` | grab into an NI Vision `Image` | needs NI Vision `Image*`; `waitForNext` default Yes | image, buffer number | `IMAQdx Grab.vi` in the display loop d99 (#15403) | **V1** - V6: `docs/main-vi-subvi-identity.md:62,112` |
| `IMAQdxStopAcquisition(session)` | stop streaming | - | rc 0 | `IMAQdx Stop Acquisition.vi`, end frame d83 (#1839) | **V2** - V6: `tools/bench/p1_bufmode_121.log` |
| `IMAQdxUnconfigureAcquisition(session)` | free the ring | - | rc 0 | not separately (Close does it) | **V2** - V6: `tools/bench/p1_bufmode_121.log` |
| `IMAQdxCloseCamera(session)` | close the session | - | rc 0 | `IMAQdx Close Camera.vi`, end frame d83 (#2078) | **V3** - a setting written before close is gone after reopen, also after `os._exit()` (V6: `docs/camera-acquisition-facts.md:418-470`, `tools/bench/imaqdx_dirty_exit.py`) |
| `IMAQdxGetAttribute(session, name, type, value*)` | read one attribute | full name, e.g. `CameraAttributes::ImageFormatControl::Width`; `type` code as above | value | property node #9775 on d87 **reads** `Height` and `Width` (only attribute access found) | **V3** - V6: `docs/camera-acquisition-facts.md:479-500` |
| `IMAQdxSetAttribute(session, name, type, value)` | write one attribute | as above; F64 passed as `c_double` | rc 0 (also when the value is silently clamped/accepted) | none found (the main VI writes no camera attribute; "the VI never writes one" is not proven VI-wide) | **V3** - `Width` 640 accepted and read back; `ExposureAuto` Off and `ExposureTime` 5555 us read back; rate 149.993 Hz measured 149.7-149.9 (V6: `docs/camera-acquisition-facts.md:418-440,756`) |
| `IMAQdxEnumerateAttributes2(session, info*, count*, root, visibility)` | list attributes | `visibility` 0x1000 Simple, 0x2000 Intermediate, 0x4000 Advanced | 198 attributes with readable/writable flags | not used | **V2** - V6: `tools/bench/imaqdx_attributes.txt` |
| `IMAQdxGetErrorString(code, buf, size)` | error text for an rc | rc, buffer | text | not used | **V0** - NIIMAQdx.h |

## Command table - camera attributes the port needs

Prefix `CameraAttributes::` omitted unless the attribute is an `AcquisitionAttributes::` one. "After open" = the value
the `.icd` file gives every new session.

| attribute | meaning | arguments + units | value after open (response) | LabVIEW program use | level + evidence |
|---|---|---|---|---|---|
| `ImageFormatControl::Width` / `Height` | ROI size | binned pixels; Width 8..1280 step 8, Height 8..1024 step 2 | 1280 / 1024 | read by #9775 (d87), shown on panel indicators | **V3** - write 640 x 512 gave `PayloadSize` 327 680 (V6: `docs/camera-acquisition-facts.md:418-425`) |
| `ImageFormatControl::OffsetX` / `OffsetY` | ROI origin | binned pixels | 0 / 0 | not used | **V2** - V6: `docs/camera-acquisition-facts.md:19` |
| `ImageFormatControl::BinningHorizontal` / `BinningVertical` | binning | 1 or 2 | 2 / 2 (`JaiBinningGainEnable` False) | never written (string `Binning` absent from the VI) | **V2** - V6: `docs/camera-acquisition-facts.md:18,620-623` |
| `ImageFormatControl::PixelFormat` | pixel format | enum | `8 Bit Monochrome` (`OutputImageType` `Grayscale (U8)`) | not written | **V2** - V6: `tools/bench/imaqdx_attributes.txt` |
| `AcquisitionControl::AcquisitionFrameRate` | frame rate | F64, Hz; max 247.9544 at 1280 x 1024 | 90.0009 | not written (panel `Frame rate` = 25 is the autofocus interval, not the camera rate) | **V3** - 149.993 Hz set, 149.7-149.9 measured (V6: `docs/camera-acquisition-facts.md:756`) |
| `AcquisitionControl::AcquisitionFrameRateRaw` | frame period | U32 / I64, **us**; min 4033 | 11 111 | not used | **V3** - swept 90-247 Hz (V6: `docs/camera-acquisition-facts.md:44-62`) |
| `AcquisitionControl::ExposureAuto` | auto exposure | `Off` / `Continuous` | `Continuous` | not written, so experiments run with auto exposure (not proven VI-wide) | **V3** - V6: `docs/camera-acquisition-facts.md:427-447` |
| `AcquisitionControl::ExposureTime` | exposure | F64, us, 1 us steps | 1909 | not written | **V3** - 5555 written, 5555 read back (same) |
| `AcquisitionControl::ExposureMode` | exposure mode | enum | `Timed` | not used | **V2** - V6: `tools/bench/imaqdx_attributes.txt` |
| `JAICustomControl::AutoShutterControlExposureMax` | auto-exposure ceiling | us | 15 000 (would cap the rate near 66 Hz) | not used | **V2** - same |
| `AcquisitionControl::TriggerMode` / `TriggerSelector` / `TriggerSource` | external trigger | enums | `Off` / `Frame Start` / `Low` - free-running | not used | **V2** - same |
| `DigitalIOControl::LineSelector` / `LineSource` / `LineInverter` / `LineFormat` | output line for the sync | enums | `Line1 - TTL Out 1` / `Exposure Active` / False / `TTL` (`LineMode` Output) | not used | **V2** - same; the electrical signal was never measured |
| `TransportLayerControl::PayloadSize` | bytes per buffer | read only | 1 310 720 at 1280 x 1024 x 8 bit | not used | **V3** - follows the ROI (327 680 at 640 x 512) |
| `AcquisitionAttributes::OverwriteMode` | what the ring does when full | enum | `Get Newest` | not used | **V2** - V6: `tools/bench/imaqdx_attributes.txt` |
| `AcquisitionAttributes::ChunkDataDecoding::*`, `ReceiveTimestampMode` | chunk data / timestamps | - | chunk decoding False, timestamps `None`; the camera offers no chunk, counter or hardware-timestamp feature | not used | **V2** - same; decision 0005 |

## Units, signs and offsets

- Geometry is in **binned** pixels (2 x 2 binning: 1280 x 1024 frame from the 2560 x 2048 sensor); `WidthMax` /
  `HeightMax` report unbinned units.
- Pixel size in the sample: front-panel control `pixel distance (nm)` = **84.0 nm** per binned pixel (V1; V6:
  `docs/camera-acquisition-facts.md:537-550`). It is a calibration constant of the optics, not a camera attribute.
- **Buffer numbers** count every frame the camera produced since acquisition start, including frames the PC missed.
  They are the time axis of the data (decision 0005, decision 0006); a gap = returned number - previous number - 1.
- The panel shows a 640 x 512 display area = camera size / 2 (constant 2 on d97). That is the display, not the ROI.

## Safety envelope and what to restore after a job

- No motion, so no envelope. The rig lock is still required (the camera is a rig device; RULES.md section 2).
- After every job: stop acquisition, unconfigure, close the session, and confirm the process that owned it is gone
  (user, 2026-09-24: continuous acquisition left running is bad for the machine).
- Settings written in a session vanish at close, so the camera returns to the `.icd` state by itself. **Never edit or
  save the `.icd` file** without the owner's decision (it changes what LabVIEW gets at every open; V6 decision
  D-2026-09-25-05). If a job changed the frame rate, verify a fresh open reads 90.0009 Hz and 1280 x 1024.

## Known pitfalls

1. **`cam0` is wrong; the name is `cam1`.** Enumerate instead of guessing.
2. **Every open reloads the `.icd` file**, so ROI, exposure and frame rate written by one process are gone for the next.
   The program that owns the acquisition must write its operating condition right after `IMAQdxOpenCamera` and read it
   back into the run record.
3. **Auto exposure is on by default** (`Continuous`, ceiling 15 000 us). The achievable frame rate then depends on how
   bright the field is. For a fixed rate, write `ExposureAuto = Off` and an `ExposureTime` shorter than the period.
4. **`Next` mode has a cliff, not a slope**: a consumer 0.3 ms too slow processes exactly 1/2 (or 1/3) of the frames.
   The per-frame budget is the period minus about 1 ms (6 ms at 150 Hz). A deeper ring absorbs jitter only.
5. **`Last` mode never waits**: polling it with no sleep re-reads the newest buffer ~25 000 times/s at 100 % of a core.
   Add a 1 ms wait, or use `LastNew`.
6. **`BufferNumber` mode may return a different buffer than requested without an error** - always use `actual`.
7. **A ROI write is accepted with rc 0** even when it changes the field of view; read the geometry back.
8. **Variadic `IMAQdxSetAttribute` and doubles**: one V6 script (`camera_budget_sweep.py:45`) avoided F64 writes on the
   grounds that ctypes cannot place a variadic double correctly on x64; later scripts passed `ctypes.c_double` and the
   value read back correctly. Always read an F64 write back, or write the integer `...Raw` attribute instead.
9. Opening the camera while LabVIEW (or NI MAX) holds it fails; LabVIEW must be closed and verified gone first.
10. Unexplained once: a fresh session read 640 x 512 on 2026-09-12; every later test reads 1280 x 1024. Binning was
    unchanged, so calibration was not affected (V6: `docs/camera-acquisition-facts.md:460-477`).

## Open questions for the owner

1. Which `Number of Buffers` does the original `Configure Grab` use, and which buffer-number mode does
   `get buff image-lost frames.vi` pass to `Get Image` (the enum constant was not read)?
2. Should the port keep auto exposure (as the original apparently does) or fix the exposure? A fixed value changes the
   image statistics compared with the original.
3. Is `LineSource = Exposure Active` on Line1 the signal the Arduino should count (decision 0005 asks for an
   exposure-start signal)? Its voltage level and pulse width at 90/150 Hz have not been measured.
4. Is the `.icd` file allowed to change (for example to a 150 Hz default), or must every program set its condition
   after opening?
