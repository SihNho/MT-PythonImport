# Camera parameters: everything the two cameras expose, and what the GUI should offer

Owner 2026-10-30: "카메라 컨트롤에 관한 파라미터가 너무 적음. NIMax 및 EMCCD 내부 함수들 참고해서 컨트롤 가능한 파라미터 (JAI 및 EMCCD) 리스트업 하도록."

Written with no hardware (rig state `experiment` since 10:05:30). Sources: the IMAQdx attribute dump of the JAI as
NI-MAX shows it (V6 `tools/bench/imaqdx_attributes.txt`, 198 attributes, `W` = writable), the JAI manual note
[manuals/camera-jai-imaqdx.md](../manuals/camera-jai-imaqdx.md), the Andor SDK2 function list in
[manuals/andor-ixon.md](../manuals/andor-ixon.md), smCamera's use of it
([manuals/smcamera-emccd-parameters.md](../manuals/smcamera-emccd-parameters.md), the "smCamera" column), the
Andor SDK2 manual (function semantics and enumerations, marked **[M]** where not confirmed on this camera), and the
values read on the rig this week ([results/2026-10-30-emccd-first-contact.md](../results/2026-10-30-emccd-first-contact.md),
[results/2026-10-30-emccd-50fps.md](../results/2026-10-30-emccd-50fps.md)). "read from camera, not now (experiment)"
= the range or enumeration is only known by asking the camera, which is not allowed during the experiment.

Columns: **driver** = exposed by `src/mtpy/devices/jai.py` / `ixon.py` today (`settings()` / `set()` name, `id` =
read in the identity, `-` = not touched, `fixed` = written to a constant at open); **GUI** = worth a control in the
program (tick) with the reason, or `-` (leave to a settings file / expert dialog) or `never` (not for this rig).

Decision rule for the tick: the parameter changes what a run measures (exposure, rate, gain, geometry, cooling,
trigger, shutter) or what the owner adjusts between samples. Calibration-type parameters (blemish, shading, LUT,
iris, lens motors) and transport-layer settings stay out of the GUI.

---

## A. JAI SP-5000M-USB (NI-IMAQdx, GenICam `CameraAttributes::` tree)

Geometry is in binned pixels (2 x 2 binning: 1280 x 1024 of the 2560 x 2048 sensor). Every open reloads the `.icd`
file, so every value below returns to its "after open" value at each session (manual pitfall 2).

### A1. Exposure / timing

| attribute | unit / range or enum | what it does | after open | driver | GUI |
|---|---|---|---|---|---|
| `AcquisitionControl::ExposureTime` | us, F64, 1 us steps; <= frame period; max set by the camera (read, not now) | exposure of every frame | 1909 | `exposure_ms` | **tick**: the main run parameter (U15) |
| `AcquisitionControl::ExposureTimeRaw` | us, integer | the same value as an integer (exact write, pitfall 8) | 1909 | - | - (driver detail) |
| `AcquisitionControl::ExposureAuto` | `Off`, `Continuous` | auto exposure (the original program leaves it on, manual open question 2) | `Continuous` | written `Off` with the exposure; read back `exposure_auto` | **tick**: on / off switch, shown with the exposure (auto changes the image statistics run to run) |
| `AcquisitionControl::ExposureMode` | `Timed`, `TriggerWidth` [M, read not now] | exposure from the timer or from the trigger pulse width | `Timed` | - | - (with trigger mode, phase 10a) |
| `AcquisitionControl::AcquisitionFrameRate` | Hz, F64, 1 .. 247.9544 at 1280 x 1024 (max follows the ROI) | frame rate when free-running | 90.0009 | `rate_Hz` | **tick**: run parameter; needs a pause (U17) |
| `AcquisitionControl::AcquisitionFrameRateRaw` | us (frame period), integer, min 4033 | the same as a period (exact write) | 11111 | - | - |
| `AcquisitionControl::AcquisitionMode` | `Continuous`, `SingleFrame`, `MultiFrame` [M] | how many frames a start produces | `Continuous` | fixed by the driver (continuous grab) | - |
| `AcquisitionControl::AcquisitionFrameCount` | integer | frames per start in MultiFrame | 1 | - | - |
| `JAICustomControl::AutoShutterControlExposureMin` / `Max` | us | the auto-exposure window (the Max caps the rate near 66 Hz when auto is on) | 100 / 15 000 | - | - (set with ExposureAuto if it is ever used) |
| `JAICustomControl::ALCReference`, `ALCAreaSelector`, `ALCAreaEnable`, `ALCAreaEnableAll`, `ALCControlSpeed`, `ALCStatus` (ro) | 0..100 %, area enum, bool, enum, 1..8, status | automatic level control (auto exposure + auto gain target and area) | 50, Low Right, True, Off, 4, ASC | - | - |
| `PulseGenerators::*` (ClockPreScaler, PulseGeneratorClock, Selector 0..3, Length, LengthMs, Frequency, StartPoint, EndPoint, PulseWidthMs, RepeatCount, ClearActivation, ClearSource, ClearInverter, ClearSyncMode) | clock ticks / ms / enums | the camera's own pulse generators (can drive a TTL line or a trigger) | prescaler 100, 0.72 MHz, generator 0, length 1 | - | - (phase 10a: a candidate for the EMCCD trigger instead of the Arduino, decision 0005 says the camera's exposure line + Arduino divider) |

### A2. Gain / readout / pixel

| attribute | unit / range or enum | what it does | after open | driver | GUI |
|---|---|---|---|---|---|
| `AnalogControl::Gain` | factor, F64; with `GainRaw` 100..1600 the factor is 1.0 .. 16.0 (0 .. 24 dB); the dump reads 16.0 = GainRaw 1600 | digital gain (`GainSelector` `Digital All`) | 16.0 (auto gain on) | `gain_dB` read-only (unit not verified: the 16.0 is a factor, not dB - see the note below) | **tick**: run parameter, once the unit is settled |
| `AnalogControl::GainRaw` | 100 .. 1600 (from `AutoGainControlGainRawMin/Max`) | the same as an integer | 1600 | - | - |
| `AnalogControl::GainAuto` | `Off`, `Continuous` [M: `Once` possible] | auto gain | `Continuous` | - | **tick**: on / off with the gain (auto gain on means the gain the run file records is not what ran) |
| `AnalogControl::GainSelector` | `Digital All` [others: read, not now] | which gain `Gain` addresses | `Digital All` | - | - |
| `AnalogControl::AnalogBaseGainSelector` / `AnalogBaseGain` | `All`; `0dB`, `+6dB`, `+12dB` [M] | analog base gain of the sensor | All / 0dB | - | - (expert; changes noise, keep 0 dB) |
| `AnalogControl::BlackLevelSelector` / `BlackLevelRaw` | `Digital All`; integer (range: read, not now) | black level offset | Digital All / 37 | - | - (expert) |
| `AnalogControl::JAILUTMode` | `Off`, `Gamma`, `LUT` [M] | LUT / gamma on the output | Off | - | never (tracking needs linear pixels) |
| `AnalogControl::JAIGamma` (ro), `Gamma` (ro) | 8 / 0.45 | gamma value when the LUT mode is Gamma | - | - | never |
| `LUTControl::LUTSelector` / `LUTIndex` / `LUTValue` | Luminance; index; value | user LUT entries | 0 / 0 | - | never |
| `ImageFormatControl::PixelFormat` | `8 Bit Monochrome` [M: 10 / 12 bit modes, read not now] | bit depth of the stream (the tracking kernel and the display take 8 bit) | 8 Bit Monochrome | fixed (8 bit) | - (12 bit would double the payload and change the tracking input; owner decision, not a GUI knob) |
| `AcquisitionAttributes::OutputImageType` | `Grayscale (U8)` and others | what IMAQdx hands to the program | Grayscale (U8) | fixed | - |
| `JAICustomControl::VideoProcessBypass` | bool | bypass the in-camera processing (LUT, shading, blemish) | False | - | - |
| `JAICustomControl::HighDynamicRangeMode` / `HighDynamicRangeSlope` | bool; `Level 1..n` | HDR knee | False | - | never |
| `JAICustomControl::DarkCompression` | `Linear`, ... | dark-level compression | Linear | - | never |
| `JAICustomControl::BlemishReduction*` (Enable, Calibration cmd, DetectThreshold, DataIndex, PositionX/Y, Num ro) | bool, cmd, int | defect-pixel correction | True, 20 | - | - (calibration dialog, not a run control) |
| `JAICustomControl::Shading*` (CorrectionMode, Mode, Calibration cmd) | `Flat Shading`; `Off` | shading correction | Flat Shading / Off | - | - |

Gain unit note: the dump reads `Gain` 16.0 with `GainRaw` 1600 and the auto-gain window 100 .. 1600, so `Gain` is
a linear factor (1.0 = raw 100 = 0 dB, 16.0 = raw 1600 = 24.1 dB). The API's `gain_dB` therefore needs the
conversion 20 log10(factor) before the JAI gain can be written; the driver keeps it read-only until the owner
confirms (decision pending since the first-contact note).

### A3. Geometry

| attribute | unit / range or enum | what it does | after open | driver | GUI |
|---|---|---|---|---|---|
| `ImageFormatControl::Width` / `Height` | binned px; W 8 .. 1280 step 8, H 8 .. 1024 step 2 | ROI size (payload follows) | 1280 / 1024 (the dump of 2026-09-12 read 640 x 512 once, pitfall 10) | `roi` (x, y, w, h) | **tick**: a smaller ROI raises the rate ceiling; needs a pause and bead re-selection (U17, WP3 rule) |
| `ImageFormatControl::OffsetX` / `OffsetY` | binned px, >= 0, x + w <= 1280 | ROI origin | 0 / 0 | `roi` | **tick** (with the size) |
| `ImageFormatControl::BinningHorizontal` / `BinningVertical` | 1 or 2 | binning (the calibration's pixel size assumes 2) | 2 / 2 | - | - (changing it invalidates every `.cal`; owner decision, settings file) |
| `ImageFormatControl::JaiBinningGainEnable` | bool | gain compensation when binning | False | - | - |
| `ImageFormatControl::SensorWidth/Height`, `WidthMax/HeightMax` (ro) | 2560 / 2048 | sensor size | - | - | - (shown in Info) |
| `ImageFormatControl::TestImageSelector` | `Off`, test patterns (read, not now) | synthetic test image from the camera | Off | - | - (a test tool, not a run control) |
| `JAICustomControl::MultiRoi*` (Index 1..8, Width, Height, OffsetX/Y, IndexMax), `VideoSendMode` (`Normal Mode`, multi-ROI, sequence) | px, enums | up to 8 ROIs sent in one frame | Normal Mode | - | - (phase 10a candidate for two-channel layouts, U22) |
| `JAICustomControl::SequenceRoi*` (Index, FrameCount, NextIndex, Width, Height, OffsetX/Y, Gain, ExposureTime, H/VBinning, LutEnable, BlackLevel, Repetition, CommandSequenceIndex, CurrentSequenceIndex ro, SequenceLutMode, SequenceReset cmd) | px, us, enums | per-frame sequence of ROI / exposure / gain | index 1, 2560 x 2048, exposure 15 000 | - | - |
| `TransportLayerControl::PayloadSize` (ro) | bytes | bytes per frame (1 310 720 at 1280 x 1024 x 8 bit) | - | id (ring sizing) | - |

### A4. Trigger / sync lines

| attribute | unit / range or enum | what it does | after open | driver | GUI |
|---|---|---|---|---|---|
| `AcquisitionControl::TriggerSelector` | `Frame Start` [M: `Acquisition Start`] | which trigger the next three address | Frame Start | - | - |
| `AcquisitionControl::TriggerMode` | `Off`, `On` | external triggering of frames (the JAI free-runs on this rig, decision 0005: it is the master) | Off | - | **tick** (phase 10a; off / on with the source, so a triggered mode is visible and reversible) |
| `AcquisitionControl::TriggerSource` | `Low`, `High`, lines, `Pulse Generator 0..3`, `Software`, user outputs [M, read not now] | where the trigger comes from | Low | - | **tick** (with TriggerMode) |
| `AcquisitionControl::TriggerActivation` | `Rising Edge`, `Falling Edge`, `Level High`, `Level Low` [M] | edge / level | Rising Edge | - | - |
| `AcquisitionControl::TriggerOverLap` | `Off`, `Read Out` | whether a trigger may overlap the readout | Read Out | - | - |
| `AcquisitionControl::TriggerSoftware` | command | fire a software trigger | - | - | - |
| `JAICustomControl::TriggerOption` | `Off`, ... (read, not now) | JAI trigger options (e.g. RCT) | Off | - | - |
| `DigitalIOControl::LineSelector` | `Line1 - TTL Out 1`, other lines (read, not now) | which line the next ones address | Line1 | - | - |
| `DigitalIOControl::LineSource` | `Exposure Active`, pulse generators, user outputs, ... (read, not now) | what the output line carries (the Arduino counts `Exposure Active`, decision 0005) | Exposure Active | - | **tick** (phase 10a: shown read-only with the sync status, so a wrong line source is visible; writable only in the sync set-up) |
| `DigitalIOControl::LineInverter` | bool | invert the line | False | - | - |
| `DigitalIOControl::LineMode` (ro), `LineFormat` (ro), `LineStatus` (ro) | Output / TTL / bool | line facts | - | - | - (Info) |
| `DigitalIOControl::UserOutputSelector` / `UserOutputValue` | `User Output 0..n`; bool | software-driven output lines | 0 / False | - | - |

### A5. Thermal / device

| attribute | unit / range or enum | what it does | after open | driver | GUI |
|---|---|---|---|---|---|
| `DeviceControl::DeviceTemperatureSelector` / `DeviceTemperature` (ro) | `Mainboard` [M: `Sensor`]; deg C | board temperature (the dump read 33.7 C) | Mainboard | - | **tick** (read-only in the status line: a hot camera drifts; cheap to show) |
| `DeviceControl::DeviceVendorName`, `ModelName`, `ManufacturerInfo`, `Version`, `FirmwareVersion`, `FpgaVersion`, `ID`, `SFNCVersion*`, `ManifestXML*`, `ScanType` (ro) | strings | identity | - | id (model, serial, firmware) | - (Info) |
| `DeviceControl::DeviceUserID` | string | a user label stored in the camera | None | - | - |
| `DeviceControl::DeviceClockSelector` / `DeviceClockFrequency` (ro) | `Sensor`; Hz (the dump read a garbage float) | sensor clock | - | - | - |
| `UserSetControl::UserSetSelector` / `UserSetLoad` / `UserSetSave` | `User Set1` ...; commands | camera-side presets (the `.icd` reload at open makes them moot, pitfall 2) | User Set1 | - | - |

### A6. Lens / iris (not fitted on this rig)

`JAICustomControl::LensSelect`, `IrisStateControl`, `PIris*` (StepMax, PositionLimit, Position, LensSelect,
AutoStepMin/Max, AutoMin/Max, CurrentFvalue), `JAIDcIrisReference`, `JAIDcIrisGain`, `AutoIrisLensControlSignalOutput`,
`MotorLensIris` / `Zoom` / `Focus`: motorised-lens control for a C-mount lens. The rig uses the microscope; **never**
in the GUI.

### A7. IMAQdx driver-side attributes (`AcquisitionAttributes::`, `CameraInformation::`, `StatusInformation::`)

| attribute | unit / range or enum | what it does | after open | driver | GUI |
|---|---|---|---|---|---|
| `AcquisitionAttributes::Timeout` | ms | wait for a buffer before an error | 5000 | - (the producer thread uses the SDK default) | - |
| `AcquisitionAttributes::OverwriteMode` | `Get Newest`, `Fail` [M] | what the ring does when full | Get Newest | - | - |
| `AcquisitionAttributes::IncompleteBufferMode` | `Ignore`, `Fail` [M] | partial frames | Ignore | - | - (should be `Fail` or counted; review item) |
| `AcquisitionAttributes::HardwareMaximumQueuedBufferCount`, `HardwareRequeueBufferListThreshold`, `ImageDecoderCopyMode`, `BitsPerPixel`, `ShiftPixelBits`, `SwapPixelBytes`, `Bayer::*`, `ChunkDataDecoding::*`, `ReceiveTimestampMode`, `AdvancedGenicam::*`, `AdvancedUSB3Vision::*` | - | transport and decoding details (no chunk data, no hardware timestamp on this camera, decision 0005) | - | ring depth 100 (`RING_DEPTH`) | - |
| `CameraInformation::*` (ro) | strings | bus, model, serial, USB speed (SuperSpeed) | - | id | - (Info) |
| `StatusInformation::AcqInProgress`, `LastBufferNumber`, `LastBufferCount`, `LostBufferCount`, `IncompleteBufferCount`, `HandledEventCount`, `LostEventCount` (ro) | counters | acquisition status (the lost-buffer counters are the driver's own loss accounting) | - | buffer numbers from `GetImageData`; `LostBufferCount` not read | **tick** (read-only: `LostBufferCount` and `IncompleteBufferCount` in the acquisition status, beside the pipeline's own gap count) |

---

## B. Andor iXon Ultra 897 (SDK2 `atmcd64d.dll`)

Every `Set*` takes effect at the next `StartAcquisition` (or `PrepareAcquisition`); most are refused while
acquiring (`DRV_ACQUIRING`), so the driver aborts, applies and restarts (`ixon.py set()`). Values marked "read
2026-10-30" came from this camera; everything else is the SDK2 manual.

### B1. Exposure / timing / acquisition structure

| function | unit / range or enum | what it does | smCamera | driver | GUI |
|---|---|---|---|---|---|
| `SetExposureTime(float s)` / `GetAcquisitionTimings` | s; granularity: the camera's clock (reads back the real value); `GetMaximumExposure` for the ceiling (read, not now) | exposure; in frame-transfer mode it equals the kinetic cycle | Movie Recorder "Exposure Time [ms]" | `exposure_ms` | **tick** |
| `SetKineticCycleTime(float s)` | s, 0 = as fast as possible; >= exposure + readout (FT off) or >= readout (FT on; 21.05 ms read 2026-10-30) | the frame period in kinetics / run-till-abort | read only (`GetAcquisitionTimings`) | `rate_Hz` (= 1 / cycle) | **tick** (as frame rate) |
| `SetFrameTransferMode(int)` | 0 off, 1 on | frame transfer: exposure overlaps readout (period = max(exposure, readout)); off: period = exposure + readout (24.59 ms read 2026-10-30) | fixed 1 | `frame_transfer` | **tick** (it changes what exposure and rate mean; show it beside them) |
| `SetAcquisitionMode(int)` | 1 single scan, 2 accumulate, 3 kinetics, 4 fast kinetics, 5 run till abort | the acquisition structure (the pipeline needs 5; a timed recording could use 3) | fixed 5 | fixed 5 | - |
| `SetReadMode(int)` | 0 full vertical binning, 1 multi-track, 2 random-track, 3 single-track, 4 image | readout geometry mode (the program needs image) | fixed 4 | fixed 4 | - |
| `SetNumberKinetics(int)` | frames | frames per kinetic series (mode 3) | - | - | - (a timed recording length belongs to the acquisition, not the camera) |
| `SetNumberAccumulations(int)` / `SetAccumulationCycleTime(float s)` | count; s | on-chip accumulation of several exposures per frame (modes 2 / 3) | fixed 1 | - | - (expert: accumulation is a longer exposure with more read noise; keep 1) |
| `SetFastKinetics(exposedRows, seriesLength, time, mode, hbin, vbin)` / `SetFastKineticsEx` / `GetFKExposureTime` | rows, frames, s | fast kinetics: sub-frame bursts stored on the sensor (mode 4) | - | - | never (not the MT-TIRF mode) |
| `SetKeepCleanTime(float s)` / `GetKeepCleanTime` | s | the keep-clean cycle between triggered frames (external trigger modes) | - | - | - (phase 10a, set with the trigger mode) |
| `GetReadOutTime(float*)` | s | the readout time the SDK computes (the driver measures it instead: `readout_ms`) | - | measured | - (Info: show the readout time, it explains the rate ceiling) |
| `SetDualExposureMode` / `SetDualExposureTimes` | 0 / 1; s, s | two alternating exposures | - | - | never |
| `PrepareAcquisition()`, `StartAcquisition()`, `AbortAcquisition()`, `GetStatus()` (20073 idle, 20072 acquiring) | - | run control | Start / Abort | start / stop (shutter open first) | **tick** (start / stop is the acquisition button) |
| `WaitForAcquisition*`, `CancelWait`, `SetDriverEvent`, `SetAcqStatusEvent`, `SetSaturationEvent` | handles | event-driven waiting; saturation event ("potentially damaging level") | `SetSaturationEvent` used | - (polling `GetNumberNewImages`) | - (the saturation event should become a `device_fault`; review item) |
| `GetNumberNewImages`, `GetImages16`, `GetOldestImage16`, `GetMostRecentImage16`, `GetTotalNumberImagesAcquired`, `GetSizeOfCircularBuffer`, `GetNumberAvailableImages`, `GetAcquisitionProgress` | frame numbers; counts | reading the SDK ring; frame counters for the JAI alignment | `GetImages` (32 bit) | `read_new()`, `total_acquired()`, `snap()` | - |
| `SetMetaData(int)` / `GetMetaDataInfo(SYSTEMTIME*, float* timeFromStart, index)` | 0 / 1; ms | per-frame timestamps from the camera's clock in the data stream [M: Ultra supports it] | - | - | **tick** (read-only flag; a camera timestamp would replace the PC receive time for the EMCCD, decision 0005: test on the rig) |

### B2. Gain / readout speed / amplifier

| function | unit / range or enum | what it does | smCamera | driver | GUI |
|---|---|---|---|---|---|
| `SetEMGainMode(int)` | 0 8-bit DAC (0..255), 1 12-bit DAC (0..4095), 2 linear, 3 real EM gain [M] | the meaning of the EM gain number; the range follows (`GetEMGainRange`) | best supported (3 Real) | `em_gain_mode` | **tick** (mode 3 "real" is what a user means by gain x100) |
| `SetEMCCDGain(int)` / `GetEMCCDGain` / `GetEMGainRange` | mode 0: 1 .. 222 read 2026-10-30 (0 = off accepted); mode 3: read, not now (typically 1 .. 300 [M]) | EM multiplication gain | Movie Recorder "Gain" | `em_gain` | **tick** |
| `SetEMAdvanced(int)` | 0 / 1 | unlock EM gain above the normal range (register damage risk with bright light; manual safety envelope) | not used | never called | never (owner's explicit decision only) |
| `SetOutputAmplifier(int)` / `GetNumberAmp` / `IsAmplifierAvailable` / `GetAmpDesc` | 0 EM, 1 conventional | which readout amplifier (conventional = no EM gain, lower speed, less noise at high light) | fixed 0 | fixed 0 | **tick** (EM / conventional switch: the two use cases - single molecules vs bright beads - differ) |
| `SetHSSpeed(typ, index)` / `GetNumberHSSpeeds` / `GetHSSpeed` | EM amplifier: index 0..3 = 17.0, 10.0, 5.0, 1.0 MHz read 2026-10-30; conventional: read, not now | horizontal readout speed: rate ceiling vs read noise | fastest | fixed index 0; list in id | **tick** (a dropdown; 17 MHz for speed, 1 MHz for the lowest noise) |
| `SetVSSpeed(index)` / `GetNumberVSSpeeds` / `GetVSSpeed` / `GetFastestRecommendedVSSpeed` | index 0..4 = 0.3, 0.5, 0.9, 1.7, 3.3 us per row read 2026-10-30; "fastest recommended" = index 4 on this camera | vertical shift speed: frame-transfer time and the rate ceiling (3.3 us gives 47.5 fps; 0.5 us about 55 fps) vs clock-induced charge | fastest recommended | fixed (fastest recommended); list in id | **tick** (needed for 50 fps; dropdown with the us value) |
| `SetVSAmplitude(int)` / `GetNumberVSAmplitudes` / `GetVSAmplitudeString` | 0 normal, 1..4 = +1 .. +4 [M] | vertical clock amplitude (needed for the fastest VS speeds on some heads) | fixed 0 | - | - (expert; set with the VS speed if the camera demands it) |
| `SetPreAmpGain(index)` / `GetNumberPreAmpGains` / `GetPreAmpGain` / `IsPreAmpGainAvailable` | index; values read, not now (typically 1x, 2x, 3x on the 897 [M]) | pre-amplifier gain (electrons per count) | smallest available | - | **tick** (dropdown; the counts-per-electron scale a user quotes) |
| `SetADChannel(int)` / `GetNumberADChannels` / `GetBitDepth` | 0; 14 or 16 bit [M] | A/D channel and its bit depth | fixed 0 | fixed 0 | - (Info: bit depth) |
| `SetBaselineClamp(int)` / `GetBaselineClamp` | 0 / 1 | keep the bias level constant frame to frame | 0 when supported | - | - (expert; on is the usual choice for quantitative work: review item) |
| `SetBaselineOffset(int)` | -1000 .. +1000 in steps of 100 [M] | shift the bias level | - | - | - |
| `SetCountConvertMode(int)` / `SetCountConvertWavelength(float nm)` | 0 counts, 1 electrons, 2 photons; nm | the SDK converts counts to electrons / photons using the gain and QE [M] | - | - | - (the analysis does its own conversion; keep raw counts) |
| `SetPhotonCounting(int)` / `SetPhotonCountingThreshold(min, max)` / `SetPhotonCountingDivisions` | 0 / 1; counts | on-camera photon counting (thresholded frames) | - | - | - (special mode; not for this rig's FRET recordings) |
| `SetReadoutRegisterPacking(int)` | 0 / 1 [M] | pack the readout register (faster, lower full well) | - | - | - |
| `SetCameraStatusEnable` | mask | status bits in the data | - | - | - |

### B3. Geometry

| function | unit / range or enum | what it does | smCamera | driver | GUI |
|---|---|---|---|---|---|
| `SetImage(hbin, vbin, hstart, hend, vstart, vend)` | binning 1..n; px 1-based inclusive within 512 x 512 (`GetDetector`) | ROI and binning (image read mode) | camera dialog "Imaging Area", "Binning" | fixed full frame 1 x 1 | **tick** (ROI and 2 x 2 binning raise the rate ceiling and the signal per pixel; phase 10a channel layout U22) |
| `SetIsolatedCropMode(active, cropheight, cropwidth, vbin, hbin)` / `SetIsolatedCropModeEx` / `SetIsolatedCropModeType` | 0 / 1; px | crop mode: only a corner of the sensor is read, the fastest sub-frame rates | - | - | - (phase 10a option if a small ROI at high rate is wanted; expert) |
| `SetCropMode(active, cropheight, reserved)` | 0 / 1; rows | older crop mode | - | - | - |
| `SetImageFlip(h, v)` / `SetImageRotate(0 / 1 / 2)` | bool; none / +90 / -90 | flip and rotate in the SDK | dialog | - | - (the mapping files handle orientation; never in the data path) |
| `SetFVBHBin`, `SetSingleTrack`, `SetMultiTrack`, `SetRandomTracks`, `SetCustomTrackHBin` | rows | the non-image read modes | - | - | never |
| `GetDetector`, `GetPixelSize`, `GetMinimumImageLength` | px; um (16 um [M]) | sensor facts | - | id (512 x 512) | - (Info) |

### B4. Trigger / sync

| function | unit / range or enum | what it does | smCamera | driver | GUI |
|---|---|---|---|---|---|
| `SetTriggerMode(int)` | 0 internal, 1 external, 6 external start, 7 external exposure (bulb), 9 external FVB EM, 10 software, 12 external charge shifting [M] | how frames are triggered; MT-TIRF uses an external trigger from the Arduino divider (decision 0005; which mode is manual open question 2) | fixed 0 | fixed 0 | **tick** (internal / external / external exposure; the heart of phase 10a) |
| `SetFastExtTrigger(int)` | 0 / 1 | skip the keep-clean cycle before an external trigger (lower latency, more dark charge) [M] | - | - | - (set with the trigger mode) |
| `SetTriggerInvert(int)` | 0 / 1 | trigger polarity (the Arduino D9 is 5 V TTL, rising) | - | - | - (sync set-up) |
| `SetTriggerLevel(float V)` / `IsTriggerModeAvailable(mode)` | V; - | trigger threshold (heads that support it) [M] | - | - | - |
| `SendSoftwareTrigger()` | command | fire one frame in mode 10 | - | - | - (a "snap" alternative) |
| `SetExternalExposure` [M, older], `SetOverlapMode` | - | external exposure variants | - | - | - |
| `GetIOLevel`, `SetIOLevel`, `SetIODirection`, `GetNumberIO` | - | the camera's auxiliary I/O lines (Fire / Shutter outputs are fixed-function on the iXon) [M] | - | - | - |

### B5. Thermal

| function | unit / range or enum | what it does | smCamera | driver | GUI |
|---|---|---|---|---|---|
| `SetTemperature(int C)` / `GetTemperatureRange` | -120 .. 20 C read 2026-10-30 (air cooling reaches about -70 C [M]) | cooling set point | minimum of the range at start | `temperature_C` (set point kept in the driver; no SDK getter) | **tick** |
| `CoolerON()` / `CoolerOFF()` / `IsCoolerOn` | - | the cooler | on at start | on with the set point; off at close | **tick** (on / off beside the set point; the close waits for a warm-up above -20 C) |
| `GetTemperature(int*)` / `GetTemperatureF(float*)` / `GetTemperatureStatus` | C; status 20034 off, 20035 not stabilized, 20036 stabilized, 20037 not reached, 20040 drift | sensor temperature and cooling state | dialog | `sensor_temperature_C`, `cooler` | **tick** (read-only in the status line, already shown) |
| `SetCoolerMode(int)` | 0 cooler off at ShutDown, 1 temperature maintained at ShutDown [M] | whether the camera keeps cooling after the program exits | - | - | - (owner decision: 1 would avoid the warm-up wait between sessions but leaves the head cooling unattended) |
| `SetFanMode(int)` | 0 full, 1 low, 2 off | fan (off for vibration-sensitive work; the head warms) | "Fan On" (0 / 2) | - | **tick** (full / low / off: fan vibration matters on an MT rig) |

### B6. Shutter

| function | unit / range or enum | what it does | smCamera | driver | GUI |
|---|---|---|---|---|---|
| `SetShutter(typ, mode, closingMs, openingMs)` | typ 0 TTL low / 1 TTL high to open; mode 0 auto, 1 permanently open, 2 permanently closed, 4 open for FVB series, 5 open for any series [M]; transfer times in ms: 0 and 10 refused (20068), 50 accepted on this head 2026-10-30 | the internal mechanical shutter (present: `IsInternalMechanicalShutter` = 1) | open (1,1,1,1) / close (1,2,1,1) | `shutter` 0 / 1 / 2; opened at start, closed at stop and close; `cycle_shutter` | **tick** (Open / Close / Exercise exist since commit 3192af7) |
| `SetShutterEx(typ, intMode, closingMs, openingMs, extMode)` | as above + the external shutter mode | internal and external shutter together | not imported | tried at open (accepted) | - |
| `SetShutters` [M, dual], `IsInternalMechanicalShutter`, `GetCapabilities().ulFeatures` bits SHUTTER / SHUTTEREX | - | shutter facts | - | id | - (Info) |
| `GetShutterMinTimes(int* closing, int* opening)` [M] | ms | the minimum transfer times the head accepts (would explain the refused 0 / 10 ms) | - | - | - (read from camera, not now; add to the identity when the rig is free) |

### B7. Misc / storage / identity

| function | unit / range or enum | what it does | smCamera | driver | GUI |
|---|---|---|---|---|---|
| `SetSpool(active, method, path, framebuffersize)` | 0 / 1; method 0 .. 7 (text, binary, FITS, SIF, TIFF, ...) [M] | the SDK writes frames to disk itself | not imported | - | - (the pipeline writes HDF5; never two writers) |
| `SaveAsSif` / `SaveAsTiff` / `SaveAsBmp` / `SaveAsRaw` / `SaveAsFITS` / `SaveAsEDF` | path | export from the SDK buffer | - | - | - |
| `GetHeadModel`, `GetCameraSerialNumber`, `GetHardwareVersion`, `GetSoftwareVersion`, `GetControllerCardModel`, `GetCapabilities` | strings / struct | identity and capability bits | `GetHeadModel`, `GetControllerCardModel`, `GetCapabilities` | id (model DU897_BV, serial 10233, shutter bits) | - (Info) |
| `GetAvailableCameras`, `GetCameraHandle`, `SetCurrentCamera`, `Initialize(dir)`, `ShutDown` | - | open / close (Initialize about 4 s; ShutDown after the warm-up) | all | open / close | - |
| `GetNumberDevices`, `GetCameraInformation`, `GetCameraEventStatus` | - | multi-camera and event facts | - | - | never |
| `SetDDG*`, `SetGateMode`, `SetMCPGain*`, `GetMCPGain*` | - | intensifier / gater functions (iStar only) | - | - | never (not this head) |
| `SetFilterMode`, `Filter_Set*` | - | the SDK's cosmic-ray filter [M] | - | - | - (analysis side instead) |
| `SetUserEvent`, `SetAcqStatusEvent`, `SetPCIMode`, `SetDMAParameters`, `SetMessageWindow` | - | driver plumbing | - | - | never |

---

## C. What this list asks for next (no code in this commit)

1. **JAI gain**: confirm the factor-to-dB reading above on the rig (write `GainRaw` 100 and read `Gain`), then
   open `gain_dB` for writing with `GainAuto Off`.
2. **JAI auto exposure / auto gain switches** in the GUI beside their values; both are on after every open and
   silently change what a run records.
3. **iXon readout controls** in the GUI: output amplifier, HS speed, VS speed (needed for 50 fps), pre-amp gain,
   fan mode, cooler on / off, ROI + binning, trigger mode; `SetMetaData` timestamps to be tested for decision 0005.
4. **Read from the camera when the rig is free**: the JAI enumerations marked "read, not now" (pixel formats, trigger
   sources, line sources, gain selectors), the iXon pre-amp gains, conventional-amplifier HS speeds, real-EM-gain
   range, `GetShutterMinTimes`, `GetMaximumExposure`.
5. Settings file vs GUI: everything marked `-` above stays in a per-rig settings file (phase 11 installer) with an
   expert dialog; everything ticked becomes a control in the Setup tab's camera groups, each applied with read-back
   (U15) and the "needs a pause" rule (U17).
