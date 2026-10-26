# smCamera (the lab's old fluorescence program): EMCCD parameters and their Andor SDK2 calls

Owner request 2026-10-23: "EMCCD 관련해서는, Andor SDK 하고 smCamera2 뜯어서 어떤 파라미터들이 들어가는지 한번
분석해줄래?" This note answers it by **static analysis only**: file bytes, PE import/export tables, strings and a few
hand-decoded x86 instruction sequences. No program was run, no DLL was loaded, no camera function was called.

Evidence labels used below:

- **[F]** read in file - the quoted string, line or byte sequence is in the file named.
- **[D]** read in file by disassembly - the bytes were decoded by hand around the `call [IAT]` site; the instruction
  reading is mine, so treat it as strong inference, not as a run.
- **[M]** SDK2 manual knowledge - from the Andor SDK2 manual, not verified here.
- **[I]** inference.

## 1. What was read

| input | what it is | key facts |
|---|---|---|
| `G:\Codes\EMCCD control code\smCamera\Run\smCamera.exe` | 32-bit MFC program, PE timestamp **2012-12-06** [F] | version resource `FileVersion 1.0.0.1`, About box "smCamera Version 1.0", "Copyright (C) 2008" [F]. PDB path `c:\Experiments\Source Code\smCamera\exe\smCamera.pdb` [F]. **Nothing in the file says "2"**: the owner's "smCamera2" is this program, version 1.0 by its own strings [F]; "2" may be a lab nickname [I]. |
| `Run\ATMCD32D.DLL` | Andor SDK2, 32-bit, PE timestamp 2007-12-19 [F] | 402 exported functions [F] |
| `C:\Program Files\Andor Driver Pack 2\atmcd64d.dll` | Andor SDK2 v2.104.30065.0, 64-bit, PE timestamp 2021-08-31 [F] | 2163 exported names [F] |
| `Run\Detector.ini` | stock Andor head/controller database (22 kB) | see section 6 |
| `Run\smCamera.setup` | one line: the program root `C:\Users\HJKIM\Desktop\TIR Programs\smCamera programs for installation\smCamera` [F] | |
| `Common\FrameSequence\*.txt` (16 files), `Common\map_Andor1_130100.txt`, `map_Andor1_170725.txt`, `Common\*.tbl` | analysis inputs | sections 4, 5 |
| `Tools\{Histogram,MovieAnalysis,MovieMapper,Trace}\*.save` | last-used analysis settings | section 5 |
| `G:\Codes\EMCCD control code\ShutterManager\` | separate shutter program (PE timestamp 2010-08-26) + sequence files | section 7 |

**Not present in the copy** (so the last-used camera values are unknown): `camera.save` (camera dialog) and
`recorder.save` (Movie Recorder dialog) - the exe names both [F], the program creates them under its `Devices\Camera\`
and `Tools\MovieRecorder\` folders [I], and neither folder is in the copy [F].

## 2. Andor functions smCamera imports

smCamera imports **55 functions from `ATMCD32D.DLL`, all by ordinal** [F]. Ordinals were resolved to names with the
export table of the `ATMCD32D.DLL` shipped next to it (ordinal base 1) [F]; every resolved name is an SDK2 name and
matches a call-name string in the exe such as `"SetEMCCDGain()"` [F], so the resolution is consistent.
**All 55 are exported by the 64-bit `atmcd64d.dll` v2.104** [F].

| group | imported functions [F] |
|---|---|
| open / close | `GetAvailableCameras`, `GetCameraHandle`, `SetCurrentCamera`, `Initialize`, `ShutDown` |
| information | `GetCapabilities`, `GetHeadModel`, `GetDetector`, `GetPixelSize`, `GetBitDepth`, `GetControllerCardModel`, `GetSizeOfCircularBuffer`, `GetEMGainRange`, `GetTemperatureRange` |
| cooling | `CoolerON`, `CoolerOFF`, `SetTemperature`, `GetTemperature`, `SetFanMode` |
| readout | `SetADChannel`, `SetOutputAmplifier`, `GetNumberHSSpeeds`, `GetHSSpeed`, `SetHSSpeed`, `GetNumberVSSpeeds`, `GetVSSpeed`, `SetVSSpeed`, `GetFastestRecommendedVSSpeed`, `SetVSAmplitude`, `GetNumberPreAmpGains`, `GetPreAmpGain`, `IsPreAmpGainAvailable`, `SetPreAmpGain`, `SetBaselineClamp` |
| EM gain | `SetEMGainMode`, `SetEMCCDGain`, `GetEMCCDGain` |
| acquisition set-up | `SetReadMode`, `SetAcquisitionMode`, `SetTriggerMode`, `SetFrameTransferMode`, `SetNumberAccumulations`, `SetExposureTime`, `GetAcquisitionTimings`, `SetImage`, `SetImageFlip`, `SetImageRotate`, `SetShutter`, `SetSaturationEvent` |
| acquisition run | `StartAcquisition`, `AbortAcquisition`, `WaitForAcquisitionTimeOut`, `CancelWait`, `GetNumberNewImages`, `GetImages` |

**Not imported** (so smCamera never calls them) [F]: `SetKineticCycleTime`, `SetNumberKinetics`,
`SetAccumulationCycleTime`, `SetEMAdvanced`, `SetFastExtTrigger`, `SetTriggerInvert`, `PrepareAcquisition`,
`GetStatus`, `GetImages16` / `GetOldestImage16` / `GetMostRecentImage16`, `SetBaselineOffset`, `SetCropMode`,
`SetIsolatedCropMode`, `SetShutterEx`, `SetSpool`, `SetCoolerMode`. Consequences: the kinetic cycle is never set, only
read back (section 3); EM gain above the normal range is never unlocked; frames are read as 32-bit integers
(`GetImages`) [F] (`GetImages` returns `at_32` data [M]).

Other imports of smCamera.exe [F]: `libtiff3.dll` (10 functions, TIFF export), Windows system DLLs (KERNEL32, USER32,
GDI32, comdlg32, ADVAPI32, ole32, ...). **No serial port, no NI-DAQ, no laser DLL** - smCamera itself drives no laser
and no shutter other than the camera's own (section 7).

## 3. EMCCD parameters: smCamera -> SDK2 function

"Fixed" means the value is a constant in smCamera; the user cannot change it. Fixed values were read from the
initialised `.data` globals each `Set...()` call pushes (`.data` raw-initialised, no instruction that writes them was
found) [D].

| parameter | where in smCamera | SDK2 function | value / default / example | in atmcd64d | evidence |
|---|---|---|---|---|---|
| Camera choice | automatic | `GetAvailableCameras`, `GetCameraHandle(0)`, `SetCurrentCamera`, `Initialize` | "%ld %s Camera(s) were found. The first one will be used." | yes | [F] string; index 0 [I] |
| Read mode | fixed | `SetReadMode` | **4 = image** | yes | [D] global 0x4960f0 = 4; meaning [M] |
| Acquisition mode | fixed | `SetAcquisitionMode` | **5 = run till abort** | yes | [D] global 0x4960f8 = 5; meaning [M] |
| Frame transfer | fixed | `SetFrameTransferMode` | **1 = on** | yes | [D] global 0x4960fc = 1 |
| Trigger mode | fixed | `SetTriggerMode` | **0 = internal** | yes | [D] global 0x4989b8 = 0, no writer found; meaning [M] |
| Accumulations | fixed | `SetNumberAccumulations` | 1 | yes | [D] global 0x4960f4 = 1 |
| A/D channel | fixed | `SetADChannel` | 0 | yes | [D] global 0x4989ac = 0 |
| Output amplifier | fixed | `SetOutputAmplifier`; also the `type` argument of `SetHSSpeed` | **0 = EM amplifier** | yes | [D] global 0x4989b0 = 0 is pushed to both; 0 = EM [M] |
| VS clock amplitude | fixed | `SetVSAmplitude` | 0 = normal | yes | [D] global 0x4989b4 = 0; meaning [M] |
| Baseline clamp | automatic | `SetBaselineClamp` | **0 (off)** when the camera reports the capability | yes | [D] tests capability bit 0x20, pushes 0; [F] "This camera supports baseline clamp - so it was turned off." |
| EM gain mode | automatic | `SetEMGainMode` | best mode the camera reports: **3 Real** if supported, else 2 Linear, else 1 12-bit, else 0 8-bit | yes | [D] tests EM-gain capability bits 8/4/2; [F] "Real EM gain mode.", "Linear EM gain mode.", "12 Bit EM gain mode.", "(Default) 8 Bit EM gain mode." |
| EM gain | Movie Recorder "Gain", camera dialog | `SetEMCCDGain(int)`, `GetEMCCDGain`, range from `GetEMGainRange` | checked against the range; example values not on disk | yes | [F] "Gain[%d] Out of Range : %d ~ %d"; [D] compares with two members filled by `GetEMGainRange` |
| Exposure time | Movie Recorder "Exposure Time [ms]" | `SetExposureTime(float s)` then `GetAcquisitionTimings` | entered in ms, multiplied by 0.001 before the call | yes | [D] `fmul` by the double 0.001 at 0x479ba8; [F] "Closest Available Exposure Time was %.3f sec." |
| Kinetic cycle | Movie Recorder "Kinetic Cycle [ms]" (display) | **read only**: `GetAcquisitionTimings` | the frame period that results from exposure + readout | yes | [F] label and "Exposure Time[%.3f ms] Kinetice Cycle[%.3f ms]"; `SetKineticCycleTime` not imported [F] |
| Fastest exposure hint | message | `GetAcquisitionTimings` | "At this readout speed, fastest available exposure time is [%.3f] ms : Exposure/Kinetic Cycle = %.3f%%" | yes | [F] |
| HS (readout) speed | camera dialog "Readout", list "%d. %.3f MHz" | `GetNumberHSSpeeds`, `GetHSSpeed`, `SetHSSpeed(0, index)` | at start: **the fastest** HS speed of the EM amplifier | yes | [D] init loop keeps the index with the largest `GetHSSpeed` value; [F] "HSSpeed is set at [%d. %.3f MHz]" |
| Pre-amp gain | automatic after HS choice | `GetNumberPreAmpGains`, `GetPreAmpGain`, `IsPreAmpGainAvailable`, `SetPreAmpGain(index)` | the **smallest available** pre-amp gain for that HS speed | yes | [D] loop starts with best = -1.0 and keeps a smaller value; [F] "PreAmpGain[ %d of %d : %f]" |
| VS (vertical shift) speed | camera dialog, list "%d. %.1f us" | `GetNumberVSSpeeds`, `GetVSSpeed`, `GetFastestRecommendedVSSpeed`, `SetVSSpeed(index)` | at start: the **fastest recommended** VS speed | yes | [F] "Fastest Recommended VSSpeed is [%d. %.3f us/pixel]", "VSSpeed is set at ..."; [D] called in the init sequence |
| Cooler | camera dialog "Fan / Cooler", "Cooler On" | `CoolerON` / `CoolerOFF` | at start: cooler **on** | yes | [D] init calls the cooler routine with 1 |
| Temperature set point | camera dialog "Set Temperature ['C]" with range "( %d 'C ~ %d 'C )" | `GetTemperatureRange`, `SetTemperature(int)` | at start: set to the **minimum of the range** | yes | [D] the value pushed is the first output of `GetTemperatureRange` (= min [M]); exact range not on disk |
| Temperature read-out | camera dialog | `GetTemperature` | status texts "Temperature has stabilized at set point." etc. | yes | [F] |
| Fan | camera dialog "Fan On" | `SetFanMode` | on = 0 (full), off = 2 | yes | [D] pushes 0 and 2; meaning [M] |
| Safe shutdown | automatic | `CoolerOFF`, wait, `ShutDown` | waits until the sensor warms: "Waiting until the camera temperature rise sufficiently. T[%d'C]-->[%d'C]" | yes | [F]; threshold value not decoded |
| ROI (imaging area) | camera dialog "Imaging Area" - Left/Right/Bottom/Top | `SetImage(hbin, vbin, hstart, hend, vstart, vend)` | validated "left >= right or bottom >= top" | yes | [F] |
| Binning | camera dialog "Binning", "# of Pixels To Bin" Horizontal/Vertical | `SetImage` (second call site) | must divide the area: "Binning should be positive integer ..." | yes | [F] |
| Flip / rotate | camera dialog "Horizontal Flip", "Vertical Flip", "Rotate 0' / +90' / -90'" | `SetImageFlip`, `SetImageRotate` | rotation needs a square frame | yes | [F] "RotateImage Failed : Frame Width != Frame Height" |
| Camera shutter | automatic | `SetShutter(type, mode, closeMs, openMs)` | open = `SetShutter(1, 1, 1, 1)`, close = `SetShutter(1, 2, 1, 1)` (TTL high, permanently open / closed, 1 ms) | yes | [D] four `push imm8` before each call; meanings [M] |
| Saturation guard | automatic | `SetSaturationEvent(handle)` | event from `CreateEventA`; message "The sensor has been saturated to a potentially damaging level." | yes | [D] + [F] |
| Frame read-out | Movie Recorder | `StartAcquisition`, `WaitForAcquisitionTimeOut`, `GetNumberNewImages`, `GetImages` (32-bit), `AbortAcquisition`, `CancelWait` | circular buffer; lost frames are reported | yes | [F] "Some images were lost and can not be recovered.", "Fatal Error : Image retrieval overtook image acquisition." |
| Buffering | Movie Recorder "Buffering": "In Camera :" (images), "In Memory [MB] :" | `GetSizeOfCircularBuffer`; a shared-memory ring (`CCAQServer`) | "[%u]MB is too small for CAQServer" | yes | [F] |
| Recording length | Movie Recorder "Set Max Length : ... Frames" | none (program side) | | - | [F] |
| 8-bit saving | Movie Recorder "Save as PMA files", "Save a Pixel in 8 Bit", "Data Scaler", "Background" | none (program side) | 16/32-bit -> 8-bit by scaler and background [I] | - | [F] labels |

## 4. FrameSequence files — frame masks for analysis, also used to label excitation per frame (see correction)

Format [F]: plain text, one integer per line (`\r\n`), `1` or `0`; line i = frame i. Examples:

| file | lines | ones | content [F] |
|---|---|---|---|
| `default.txt` | 12 | 12 | all `1` |
| `1-10.txt` | 10 | 10 | all `1` |
| `1-10 of 100.txt` | 100 | 10 | frames 1-10 = 1, 11-100 = 0 |
| `12-50 of 50.txt` | 50 | 39 | frames 1-11 = 0, 12-50 = 1 |
| `6-15.txt` | 15 | 10 | frames 6-15 = 1 |

Meaning: **which frames of a movie are used** when finding peaks / building the averaged image in Movie Analysis and
Movie Mapper, and when reading frames in the FRET Histogram. Evidence: the class is `CFrameSequence::Load` with
default `Default.txt` [F]; the buttons "Load Sequence", "Apply Sequence" sit in the "Frame Sequence" boxes of Movie
Analysis and of Movie Mapper, which has separate "CH1 Frame Sequence" and "CH2 Frame Sequence" [F]; the message
"Analysis : Searching Frames [ %u ~ %u ]" [F]; `analysis.save`, `histogram.save` and `mapper.save` store a
FrameSequence path (`6-15.txt`, `1-5.txt`) [F]. smCamera's recorder never reads it, and smCamera has no laser output
[F, section 2]. So it is an analysis-side mask [I, strong]. In an ALEX movie it is how the user picks "the
green-excited frames" for peak finding (e.g. `11-20.txt` = 10 of 20) [I]. The per-frame laser/shutter pattern lives in
ShutterManager (section 7).

**Correction from the owner's account (2026-10-23, from an explanation by a smCamera user):** in the `.smm` -> `.smt`
conversion a shutter `.txt` such as `0;0;0;0;1;1;1;1` (frames 5-8) assigns each frame of the movie to green or red
excitation, and FRET is computed as Red/(Red+Green) with a pre-defined map applied. So a frame sequence file also
labels **which laser excited each frame**, not only which frames analysis uses. The `;`-separated layout differs from
the one-value-per-line files read here (format [F] above): to be checked against the owner's example data. The
pipeline continues `.smt` -> several formats (`.trace` among ~7) -> MATLAB on `.trace`.

## 5. map_Andor1_*.txt - CH2 <-> CH1 registration (donor/acceptor halves)

Format [F] (`map_Andor1_170725.txt`):

```
Frame Width & Height
512 512
Mapping from CH2 onto CH1 X
-250.662 0.00776815 1.01417e-005 ... (16 numbers)
Mapping Error
0.065
Mapping from CH2 onto CH1 Y      (16 numbers, Mapping Error 0.104)
Mapping from CH1 onto CH2 X      (16 numbers, Mapping Error 0.067)
Mapping from CH1 onto CH2 Y      (16 numbers, Mapping Error 0.106)
```

- Written by `CMapping::DoMapping` from picked bead pairs ("Mapping with [%d] point pairs", "Use 3 point pairs",
  "Mapping Error(rms) : CH1X[%f] CH1Y[%f] CH2X[%f] CH2Y[%f]") [F]. Mapping Error = rms residual in pixels [F label "RMSErr[px]"].
- 16 coefficients = a 2-D cubic polynomial, `x' = sum c[4i+j] * x^i * y^j` (i, j = 0..3) [I]: in "CH1 onto CH2 X"
  the constant is 253.0 and c[4] (the x term) is 1.017; in "CH1 onto CH2 Y" c[1] (the y term) is 1.023 [F values].
- **Frame 512 x 512, CH1 = left half, CH2 = right half**, shifted by about 250-258 px in x [I from the constants
  -250.7 / +253.0 and -188 / +257.8 in the 2013 file]. The 2013 map has rms 0.38-0.53 px, the 2017 map 0.065-0.106 px [F].
- Used by Movie Analysis ("Load Map", `analysis.save` -> `map_Andor1_130100.txt`), Movie Mapper (`mapper.save` ->
  `map_Andor1_170725.txt`), FRET Trace ("Use Mapping", "1 to 2", "2 to 1") and the converter ("Convert Maps") [F].
- The name "Andor1" and the 512 x 512 frame suggest the camera was a 512 x 512 iXon (e.g. 897/887) [I].

`.tbl` files [F]: 236 or 256 lines of "R G B" integers - display colour tables (`CH%d_color0.tbl`, `CH%d_color1.tbl`,
`tiff_colormap.tbl`, BW, gamma). Not camera settings.

`.save` files [F] (one value per line, no keys; meanings from the dialog labels [I]):

| file | content |
|---|---|
| `histogram.save` | FrameSequence path x2, `0.940000`, `0.000000` (likely leakage correction "ID in CH1" / "IA in CH1" or axis values [I]) |
| `analysis.save` | map path, FrameSequence path, `3.0`, `5.0` (peak radius / sigma [I]), `1`, `1`, `1.7` (threshold / data scaler [I]), `10`, last data folder `E:\Kang\20170725\...` |
| `mapper.save` | data folder, CH1 FrameSequence, `3.0`, `3.0`, CH2 FrameSequence, `3.0`, `5.0`, map path, `1.0`, `4` |
| `trace.save` | `1.000`, `0.000`, `10`, `10` (scales / R1, R2 radii [I]), data folder |

File formats named in the exe [F]: films `.smm` (new) and `.pma` ("Old Film", 8-bit), `.tif`/`.tiff` ("Gray TIFF",
"8bit Color TIFF"), peaks `.pks` / `.bgpks` / `.pkt`, traces `.smt` / `.smt2` / `.bgsmt` / `.bgsmt2` and old
`.traces`, logs `.log` / `.tlog` / `.bgtlog` (pairing of extension to role is [I] from their position next to the
reader/writer class names). The film header stores [F]: "Num Channels", "Frame Resolution", "Active Area", "Lag
Beetween Images [ms]", "Kinetic Cycle Time [ms]", "Exposure Time [ms]", "Gain", "Camera Bit Depth", "Camera
Information", "Byte Per Pixel", "Data Scaler", "Background", "Server Index", "Filming Date and Time". **This is
already the U15 idea: the settings travel with the movie.**

## 6. Detector.ini - stock Andor file, not this rig's camera

[F]: `[System] Controller=CCI-22, Head=DV860`; `[Cooling]` profiles; ~70 head sections (CCD, iDus, iXon).
`[DV860]` = 128 x 128, 24 um, `Ixon=1`; `[DV887]` = 512 x 512, 16 um, `EMCCDRegisterSize=568`. The 512 x 512 maps
(section 5) do not fit a DV860 [F values], so this is the default file of an old Andor installation, read by the
2007 driver for PCI controllers [I]. Not useful for the new program; the SDK reports the head itself
(`GetHeadModel`, `GetDetector`) [M].

## 7. ShutterManager - the old per-frame laser alternation

- Separate program, PE timestamp 2010-08-26, "ShutterManager Version 1.0" [F]. Imports from **`nicaiu.dll`
  (NI-DAQmx)** only `DAQmxCreateTask`, `DAQmxCreateDOChan`, `DAQmxWriteDigitalU16`, `DAQmxStopTask`,
  `DAQmxClearTask`, `DAQmxGetExtendedErrorInfo` [F] - digital output only, no counter or trigger input.
- Controller **NI PCI-6503** [F], `controller.save` = `Dev1`, `1`, `4`, `7`, `0` [F] -> device, Shutter1/2/3 lines
  (1, 4, 7) and "Shutter Delay [ms]" 0 [I from the dialog labels "Device :", "Shutter1 : / Line", ..., "Shutter Delay
  [ms] :"]. Channel string "%s/line%u:%u" [F].
- Sequence files [F]: one line per frame, three 0/1 characters = the three shutters, e.g.
  `1 frame - 1 green.txt` = `001`, `1 frame - 1 red.txt` = `010`, `2 frames - 1green1red.txt` = `010`,`001`,
  `4 frames - 1dark1green1dark1red.txt` = `000 010 000 001`. **Note:** the last two file names put green first but
  the first line is `010` (= "red" in the 1-frame files) - either the names or the files are inconsistent [F]; which
  column is which laser must be checked on the rig.
- `shutter.save` holds three sequence paths [F] = "Header :", "Body :", "Footer :" in the dialog [F]: a start part,
  a repeated body (the alternation), an end part [I].
- **Synchronisation is software**: both programs contain a shared-memory name `SHUTTER` and `Global\%s` [F];
  ShutterManager shows "Shutter Count", "Shutter Cycle Time: [%.4f] sec", "Last Shutter: [%2x] %.3f sec ago" [F].
  smCamera, which owns the frames, presumably signals each new frame through that shared memory and ShutterManager
  writes the next pattern to the DIO lines [I]. With the camera on internal trigger (section 3) the laser change is
  timed by the PC, not by the camera.

## 8. What this means for the new program (LabVIEW2Scr)

1. **Trigger mode differs on purpose.** smCamera free-runs (trigger 0 internal, run till abort, frame transfer on).
   Decision 0005 needs `SetTriggerMode(1)` External, or 7 External Exposure, with frame transfer [M]; `SetTriggerMode`
   is exported by atmcd64d [F]. Use `IsTriggerModeAvailable` before setting [M, exported F].
2. **Per-frame laser alternation (used as a FRET correction, U28) moves into hardware.** The old way (ShutterManager, PC-timed DIO per frame) is exactly what decision 0005
   forbids. Decision 0013's "illumination sequence" replaces ShutterManager's header/body/footer files; their format
   (one row per EMCCD frame, one 0/1 column per light source) is a ready model for the sequence description, executed
   by the Arduino instead of the PC [I].
3. **Settings to expose in the iXon preset (U15)**, all present in atmcd64d [F]: exposure (s), EM gain + EM gain mode,
   HS speed index (+ output amplifier, A/D channel), pre-amp gain index, VS speed index (+ VS amplitude), frame
   transfer, trigger mode, acquisition mode, ROI + binning (`SetImage`), flip/rotate, temperature set point + cooler +
   fan, shutter mode, baseline clamp. smCamera's automatic choices (fastest HS, lowest pre-amp gain, fastest
   recommended VS, best EM gain mode, baseline clamp off, coldest set point) are reasonable **defaults**, to be written
   explicitly into the preset rather than chosen silently [I].
4. **Read back what the camera really uses** (`GetAcquisitionTimings`, `GetEMCCDGain`, `GetTemperature`) and store it,
   as smCamera's film header already did (section 5) - matches U15 [F/I].
5. **Channel split**: CH1 = left half, CH2 = right half of a 512 x 512 frame, registered by a 3rd-order polynomial
   with ~0.1 px rms; the new analysis plug-in (0013) can read the existing `map_Andor1_*.txt` directly [I].
6. Use `GetImages16` (or `GetOldestImage16`) and the 64-bit DLL; smCamera used the 32-bit `GetImages` [F].
7. smCamera never raised EM gain beyond the normal range (`SetEMAdvanced` not imported) [F] - keep that lock (andor-ixon.md).

## 9. Open questions

Update 2026-10-26: the live install in `G:\Data\SiHyeong\Dropbox\_config\smCameraRelated` has the same `smCamera.exe`
(SHA-256 identical) but `atmcd32d.dll` **2.97.30007.0** (not 2.79), and it contains `camera.save` and `recorder.save`
(a raw memory dump and a 4-line text file). The `.save` meanings above are now read from the dialogs on the
colleague's slides; see [smcamera-files.md](smcamera-files.md) sections 11-12 (it also decodes `.smm` and `.smt`,
answering the `.smm` part of item 6).

1. Is "smCamera2" a different build than this 2012 `smCamera.exe` 1.0? Nothing named 2 was found.
2. Last-used EM gain, exposure, temperature and HS index: `camera.save` / `recorder.save` are missing; are they on the
   old acquisition PC (`C:\Users\HJKIM\Desktop\TIR Programs\...`)?
3. ~~Which iXon is the old camera?~~ Answered: the MT-TIRF EMCCD is an **iXon Ultra 897** (512 x 512, 16 µm; owner's
   optical schematic, [andor-ixon.md](andor-ixon.md)), consistent with the 512 x 512 maps.
4. ShutterManager columns -> lasers: the file names and contents disagree (section 7).
5. Did the lab ever run smCamera with an external trigger? The binary has no path for it (trigger fixed at 0).
6. Not decoded: the warm-up temperature threshold before `ShutDown`, the `WaitForAcquisitionTimeOut` timeout, and the
   exact layout of the `.smm` / `.pma` binary headers.
7. The published paper (reference 1) was **not read in full** (see below). Could the owner download the PDF in a
   browser? It is CC BY 4.0, so a copy can sit in `docs/manuals/` and the [I] items above (FrameSequence meaning, file
   extensions, map polynomial order, ShutterManager columns) can be checked against the authors' own description.

## References

1. Kyung Suk Lee, Taekjip Ha, "smCamera: all-in-one software package for single-molecule data acquisition and data
   analysis", *Journal of the Korean Physical Society* 86(1), 1-13 (online 2024-12-06), DOI
   [10.1007/s40042-024-01243-z](https://doi.org/10.1007/s40042-024-01243-z), licence CC BY 4.0.
   **Evidence level: metadata and abstract only** (Crossref record `api.crossref.org/works/10.1007/s40042-024-01243-z`,
   read 2026-10-23). The Springer PDF and HTML URLs redirect to a Springer login (`idp.springer.com/authorize`), which
   was not followed; Europe PMC has no record; web searches found no other open copy. What the abstract supports: smCamera
   is one program covering the whole smFRET workflow, from recording movies to extracting smFRET time series, without
   other software or programming; it had been distributed informally before the paper. This matches the menus found in
   the exe (Movie Recorder, Movie Mapper, Movie Analysis, FRET Histogram, FRET Trace, File Format Converter) [F]. The
   exe's library paths `\Experiments\Source Code\LKSLib\...` [F] fit the first author's initials (L. K. S.) [I].
   **No parameter value, file format or ALEX detail in this note comes from the paper.**
2. Andor SDK2 manual (function meanings marked [M]); not re-read for this note.
3. Project notes: [andor-ixon.md](andor-ixon.md), [arduino-sync.md](arduino-sync.md), decisions 0005 and 0013,
   `docs/spec/ui-requirements.md` U15.
