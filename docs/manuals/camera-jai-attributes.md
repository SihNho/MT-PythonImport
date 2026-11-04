# JAI SP-5000M-USB: the attribute catalogue as NI-IMAQdx reports it (rig 2026-11-04)

`api.camera.catalogue()` on the rig: 156 attributes; values as read at 2026-11-04 21:40 (90 Hz full frame, the .icd defaults). The GenICam file's view is [camera-jai-features.md](camera-jai-features.md); the program's generic panel (Setup -> Camera settings) is built from this catalogue. vis: beginner / expert / guru as NI MAX; access rw / ro / wo.

## AcquisitionControl (14)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| AcquisitionMode | enum | rw | B | Continuous | Single Frame / Multi Frame / Continuous | Sets the acquisition mode of the device. |
| AcquisitionFrameCount | int | rw | B | 1 | 1 .. 65535 step 1 | Number of frames to acquire in MultiFrame Acquisition mode. |
| AcquisitionFrameRate | float | rw | B | 90.0009 | 0.125 .. 247.9544 | Controls the acquisition rate(in Hertz) at which the frames are captured. |
| AcquisitionFrameRateRaw | int | rw | B | 11111 | 4033 .. 8000000 step 1 | Controls the acquisition rate(in us) at which the frames are captured. |
| TriggerSelector | enum | rw | B | Frame Start | Acquisition Start / Acquisition End / Frame Start / Acquisition Transfer Start | Selects the type of trigger to configure. |
| TriggerMode | enum | rw | B | Off | Off / On | Controls if the selected trigger is active. |
| TriggerSoftware | command | wo | B |  |  | Generates an internal trigger. |
| TriggerSource | enum | rw | B | Low | Low / High / Software / Pulse Generator 0 / Pulse Generator 1 / User Output 0 / User Output 1 / User Output 2 / User Output 3 / Line 4 - TTL In 1 ... | Specifies the internal signal or physical input Line to use as the trigger source. The selected trig |
| TriggerActivation | enum | rw | B | Rising Edge | Rising Edge / Falling Edge / Level High / Level Low | Specifies the activation mode of the trigger. |
| TriggerOverLap | enum | rw | E | Read Out | Off / Read Out | Specifies the type trigger overlap permitted with the previous frame. |
| ExposureMode | enum | rw | B | Timed | Off / Timed / Trigger Width | Sets the operation mode of the Exposure (or shutter). |
| ExposureTime | float | rw | B | 1909 | 10.0 .. 11053.0 | Sets the Exposure time (in microseconds) when ExposureMode is Timed. |
| ExposureTimeRaw | int | rw | B | 1909 | 10 .. 11053 step 1 | Sets the Exposure time (in microseconds) when ExposureMode is Timed. |
| ExposureAuto | enum | rw | B | Continuous | Off / Once / Continuous | Sets the automatic exposure mode when ExposureMode is Timed. |

## AnalogControl (11)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| GainSelector | enum | rw | B | Digital All | Digital All | Selects which Gain is controlled by the various Gain features |
| Gain | float | rw | B | 16 | 1.0 .. 16.0 | Controls the selected gain as an absolute physical value. |
| GainRaw | int | rw | G | 1600 | 100 .. 1600 step 1 | Controls the selected gain as a raw integer value. |
| GainAuto | enum | rw | B | Continuous | Off / Once / Continuous | Sets the automatic gain control (AGC) mode. |
| AnalogBaseGainSelector | enum | rw | E | All | All | Select Analog Base Gain channel. |
| AnalogBaseGain | enum | rw | E | 0dB | 0dB / 6dB / 12dB | Set Analog Gain of CMOS sensor. |
| BlackLevelSelector | enum | rw | E | Digital All | Digital All | Selects which Black Level is controlled by the various Black Level features. |
| BlackLevelRaw | int | rw | E | 37 | -256 .. 255 step 1 | Controls the selected gain as an absolute physical value. |
| JAILUTMode | enum | rw | E | Off | Off / Gamma / LUT | Select Gamma or LUT to control. |
| JAIGamma | int | ro | B | 8 | 0 .. 8 step 1 | Controls the gamma correction of pixel intensity. |
| Gamma | float | ro | B | 0.45 | 0.45 .. 1.0 | Controls the Gamma correction of pixel intensity. |

## DeviceControl (19)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| DeviceVendorName | string | ro | B | JAI Corporation |  | Device Vendor Name from the Bootstrap Register |
| DeviceModelName | string | ro | B | SP-5000M-USB |  | Device Model Name from the Bootstrap Register |
| DeviceManufacturerInfo | string | ro | B | See the possibilities |  | Device Manufacturer Info from the Bootstrap Register |
| DeviceVersion | string | ro | B | 0.3.0.0 |  | Device Version from the Bootstrap Register |
| DeviceFirmwareVersion | string | ro | B | 0.2.0.0 |  | DeviceFirmwareVersion |
| DeviceSFNCVersionMajor | int | ro | B | 2 | -9223372036854775808 .. 9223372036854775807 step 1 | Major Version of the Standard Features Naming Convention |
| DeviceSFNCVersionMinor | int | ro | B | 0 | -9223372036854775808 .. 9223372036854775807 step 1 | Minor Version of the Standard Features Naming Convention |
| DeviceSFNCVersionSubMinor | int | ro | B | 0 | -9223372036854775808 .. 9223372036854775807 step 1 | Sub Minor Version of the Standard Features Naming Convention |
| DeviceManifestXMLMajorVersion | int | ro | G | 0 | 0 .. 4294967295 step 1 | Indicates the major version number of the XML file of the selected manifest entry.  |
| DeviceManifestXMLMinorVersion | int | ro | G | 6 | 0 .. 4294967295 step 1 | Indicates the minor version number of the XML file of the selected manifest entry.  |
| DeviceManifestXMLSubMinorVersion | int | ro | G | 1 | 0 .. 4294967295 step 1 | Indicates the sub minor version number of the XML file of the selected manifest entry.  |
| DeviceID | string | ro | E | U500336 |  | Device ID from the Bootstrap Register |
| DeviceFpgaVersion | string | ro | B | 055 |  | DeviceFpgaVersion |
| DeviceUserID | string | rw | B | None |  | Device User ID |
| DeviceScanType | enum | ro | E | Areascan | Areascan | DeviceScanType |
| DeviceTemperatureSelector | enum | rw | E | Mainboard | Mainboard | DeviceTemperatureSelector |
| DeviceTemperature | float | ro | E | 32.8047 | -3.4028234663852886e+38 .. 3.4028234663852886e+38 | DeviceTemperature |
| DeviceClockSelector | enum | rw | E | Sensor | Sensor | DeviceClockSelector |
| DeviceClockFrequency | float | ro | E | 3.23881e-37 | -3.4028234663852886e+38 .. 3.4028234663852886e+38 | DeviceClockFrequency |

## DigitalIOControl (8)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| LineSelector | enum | rw | E | Line1 - TTL Out 1 | Line1 - TTL Out 1 / Line2 - Opt Out 1 / Line4 - TTL In 1 / Line5 - Opt In 1 / Line8 - TTL Out 2(Option) / Line9 - TTL Out 3(Option) / Line10 - TTL In 2(Option) / Line11 - LVDS In(Option) / NAND Gate 0 In 1 / NAND Gate 0 In 2 ... | Selects the physical line (or pin) of the external device connector to configure. |
| LineMode | enum | ro | E | Output | Input / Output | Controls if the physical Line is used to Input or Output a signal. |
| LineInverter | bool | rw | E | False |  | Controls if the signal line is inverted. False means "Active High" and True for "Active Low". |
| LineStatus | bool | ro | E | False |  | Line Status |
| LineSource | enum | rw | E | Exposure Active | Low / High / Acquisition Trigger Wait / Acquisition Active / Frame Trigger Wait / Frame Active / Exposure Active / FVAL / Pulse Generator 0 / Pulse Generator 1 ... | Selects which internal acquisition or I/O source signal to output on the selected Line. |
| LineFormat | enum | ro | E | TTL | No Connect / Internal Signal / TTL / LVDS / Opto Coupled | Controls the current electrical format of the selected physical input or output Line. |
| UserOutputSelector | enum | rw | E | User Output 0 | User Output 0 / User Output 1 / User Output 2 / User Output 3 | Selects User Output. |
| UserOutputValue | bool | rw | E | False |  | Sets the value of the selected User Output. |

## ImageFormatControl (13)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| SensorWidth | int | ro | E | 2560 | 0 .. 4294967295 step 1 | Width of the image sensor in pixels |
| SensorHeight | int | ro | E | 2048 | 0 .. 4294967295 step 1 | Height of the image sensor in pixels |
| WidthMax | int | ro | E | 2560 | 0 .. 4294967295 step 1 | Width Max |
| HeightMax | int | ro | E | 2048 | 0 .. 4294967295 step 1 | Height Max |
| Width | int | rw | B | 1280 | 8 .. 1280 step 8 | Width of the image in pixels |
| Height | int | rw | B | 1024 | 8 .. 1024 step 2 | Height of the image in pixels |
| OffsetX | int | rw | B | 0 | 0 .. 0 step 8 | X Offset of the image in pixels |
| OffsetY | int | rw | B | 0 | 0 .. 0 step 2 | Y Offset of the image in pixels |
| BinningHorizontal | int | rw | E | 2 | 1 .. 2 step 1 | BinningHorizontal |
| BinningVertical | int | rw | E | 2 | 1 .. 2 step 1 | Vertical Binning |
| JaiBinningGainEnable | bool | rw | E | False |  | Specifies whether or not to Gain Up by Binning operation. |
| PixelFormat | enum | rw | B | 8 Bit Monochrome | 8 Bit Monochrome / 10 Bit Monochrome / 10 Bit Monochrome Packed / 12 Bit Monochrome / 12 Bit Monochrome Packed | Pixel Format as specified in GigE Vision standard |
| TestImageSelector | enum | rw | B | Off | Off / Grey Horizontal Ramp / Grey Vertical Ramp / Grey Horizontal Ramp Moving | This feature selects the type of test image that is expelled by the camera. |

## JAICustomControl (67)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| VideoProcessBypass | bool | rw | E | False |  | Bypass Video Process. |
| ALCReference | int | rw | B | 50 | 10 .. 100 step 1 | AGC/Auto-Shutter Reference |
| ALCAreaSelector | enum | rw | E | Low Right | Low Right / Low Mid-Right / Low Mid-Left / Low Left / Mid-Low Right / Mid-Low Mid-Right / Mid-Low Mid-Left / Mid-Low Left / Mid-High Right / Mid-High Mid-Right ... | ALC Area Selector |
| ALCAreaEnable | bool | rw | E | True |  | ALC Area Enable |
| ALCAreaEnableAll | enum | rw | E | Off | Off / On | ALC Area Enable All |
| AutoShutterControlExposureMin | int | rw | B | 100 | 100 .. 14999 step 1 | Auto Shutter Control Exposure Value Min. |
| AutoShutterControlExposureMax | int | rw | B | 15000 | 101 .. 8000000 step 1 | Auto Shutter Control Exposure Value Max. |
| AutoGainControlGainRawMin | int | rw | B | 100 | 100 .. 1599 step 1 | Auto Gain Control GainRaw Value Min. |
| AutoGainControlGainRawMax | int | rw | B | 1600 | 101 .. 1600 step 1 | Auto Gain Control GainRaw Value Max. |
| ALCControlSpeed | int | rw | B | 4 | 1 .. 8 step 1 | AGC/ASC Control Speed |
| ALCStatus | enum | ro | E | ASC | Off / AIC / ASC / AGC | Indicate ALC Status. |
| TriggerOption | enum | rw | E | Off | Off / RCT / PIV | Select RCT or PIV to control. |
| BlemishReductionEnable | bool | rw | E | True |  | Blemish Reduction Enable |
| BlemishReductionCalibration | command | wo | E |  |  | Perform White Blemish Reduction Calibration |
| BlemishDetectThreshold | int | rw | E | 20 | 0 .. 100 step 1 | Blemish Detect Threshold |
| BlemishDataIndex | int | rw | E | 1 | 1 .. 512 step 1 | Blemish Data Index |
| BlemishDataPositionX | int | rw | E | -1 | -1 .. 2559 step 1 | Blemish Data Position X Value |
| BlemishDataPositionY | int | rw | E | -1 | -1 .. 2047 step 1 | Blemish Data Position Y Value |
| BlemishNum | int | ro | E | 0 | 0 .. 4294967295 step 1 | Number of the Blemish Compensation pixels |
| ShadingCorrectionMode | enum | rw | E | Flat Shading | Flat Shading | Shading Correction Mode |
| ShadingMode | enum | rw | B | Off | Off / User 1 / User 2 / User 3 | Shading Mode |
| ShadingCalibration | command | wo | B |  |  | Perform Shading Calibration |
| LensSelect | enum | rw | E | None | None / P-IRIS Lens / Motor Lens / Video Iris Lens(Option) / DC Iris Lens(Option) | Lens Select |
| IrisStateControl | enum | rw | E | Iris Video Control | Iris Video Control / Iris Close / Iris Open | Iris State control |
| PIrisStepMax | int | ro | E | 72 | 0 .. 255 step 1 | P-IRIS Step Max |
| PIrisPositionLimit | int | ro | E | 74 | 0 .. 200 step 1 | P-IRIS Position Limit |
| PIrisPosition | int | rw | E | 72 | 0 .. 72 step 1 | P-IRIS Position |
| PIrisLensSelect | enum | rw | E | LM16JC5MM | LM16JC5MM / LM35JC5MM / CINEGON1.9/10 / CINEGON1.8/4.8 / SCHNEIDER COMPACT IRIS / MG3518KC / OTHERS | P-IRIS Lens Select |
| PIrisAutoStepMin | int | ro | E | 0 | 0 .. 74 step 1 | P-IRIS Auto Minimum Step No |
| PIrisAutoStepMax | int | ro | E | 60 | 0 .. 74 step 1 | P-IRIS Auto Maximum Step No |
| PIrisAutoMin | enum | rw | E | F 5.6 | Open / F 1.4 / F 2.0 / F 2.8 / F 4.0 / F 5.6 / F 8.0 / F 11.0 / F 16.0 / F 22.0 ... | P-IRIS Auto Minimum F_No |
| PIrisAutoMax | enum | rw | E | F 1.4 | Open / F 1.4 / F 2.0 / F 2.8 / F 4.0 / F 5.6 / F 8.0 / F 11.0 / F 16.0 / F 22.0 ... | P-IRIS Auto Maximum F_No |
| PIrisCurrentFvalue | enum | ro | E | Close | Open / F 1.4 / F 2.0 / F 2.8 / F 4.0 / F 5.6 / F 8.0 / F 11.0 / F 16.0 / F 22.0 ... | Indicate current P-IRIS F_No |
| JAIDcIrisReference | int | rw | E | 50 | 10 .. 95 step 1 | DC IRIS Reference |
| JAIDcIrisGain | float | rw | E | 1 | 0.5 .. 4.0 | Feedback gain for DC IRIS. |
| AutoIrisLensControlSignalOutput | enum | rw | E | Off | Off / On | Auto Iris Lens Control Signal Output |
| MotorLensIris | enum | rw | E | Stop | Stop / Open / Close | Motor Lens Iris |
| MotorLensZoom | enum | rw | E | Stop | Stop / Wide / Tele | Motor Lens Zoom |
| MotorLensFocus | enum | rw | E | Stop | Stop / Near / Far | Motor Lens Focus |
| VideoSendMode | enum | rw | E | Normal Mode | Normal Mode / Trigger Sequence Mode / Command Sequence Mode / Multi Roi Mode | Video Send Mode Selector |
| SequenceRoiIndex | enum | rw | E | Index 1 | Index 1 / Index 2 / Index 3 / Index 4 / Index 5 / Index 6 / Index 7 / Index 8 / Index 9 / Index 10 | Sequence Roi Index |
| SequenceRoiFrameCount | int | rw | E | 1 | 1 .. 255 step 1 | Sequence Roi Frame Count |
| SequenceRoiNextIndex | enum | rw | E | Index 1 | Index 1 / Index 2 / Index 3 / Index 4 / Index 5 / Index 6 / Index 7 / Index 8 / Index 9 / Index 10 ... | Sequence Roi Next Index |
| SequenceRoiWidth | int | rw | E | 2560 | 16 .. 2560 step 16 | Sequence Roi Width |
| SequenceRoiHeight | int | rw | E | 2048 | 8 .. 2048 step 1 | Sequence Roi Height |
| SequenceRoiOffsetX | int | rw | E | 0 | 0 .. 0 step 16 | Sequence Roi Offset X |
| SequenceRoiOffsetY | int | rw | E | 0 | 0 .. 0 step 1 | Sequence Roi Offset Y |
| SequenceRoiGain | int | rw | E | 100 | 100 .. 1600 step 1 | Sequence Roi Gain |
| SequenceRoiExposureTime | int | rw | E | 15000 | 10 .. 8000000 step 1 | Sequence Roi Exposure Time |
| SequenceRoiHBinning | int | rw | E | 1 | 1 .. 2 step 1 | Sequence Roi H Binning |
| SequenceRoiVBinning | int | rw | E | 1 | 1 .. 2 step 1 | Sequence Roi V Binning |
| SequenceRoiLutEnable | bool | rw | E | False |  | Sequence Roi Lut Enable |
| SequenceRoiBlackLevel | int | rw | E | 0 | -256 .. 255 step 1 | Sequence Roi Black Level |
| SequenceRepetition | int | rw | E | 255 | 1 .. 255 step 1 | Sequence Repetition. |
| CommandSequenceIndex | enum | rw | E | Index 1 | Index 1 / Index 2 / Index 3 / Index 4 / Index 5 / Index 6 / Index 7 / Index 8 / Index 9 / Index 10 | Command Sequence Index |
| CurrentSequenceIndex | enum | ro | E | Index 1 | Index 1 / Index 2 / Index 3 / Index 4 / Index 5 / Index 6 / Index 7 / Index 8 / Index 9 / Index 10 | Current Sequence Index |
| SequenceLutMode | enum | rw | E | Gamma | Gamma / LUT | Select Sequence LUT mode. |
| SequenceReset | command | wo | B |  |  | Reset Sequence Index |
| MultiRoiIndex | enum | rw | E | Index 1 | Index 1 / Index 2 / Index 3 / Index 4 / Index 5 / Index 6 / Index 7 / Index 8 | Multi Roi Index |
| MultiRoiWidth | int | rw | E | 1280 | 16 .. 2560 step 16 | Multi Roi Width |
| MultiRoiHeight | int | rw | E | 128 | 1 .. 2048 step 1 | Multi Roi Height |
| MultiRoiOffsetX | int | rw | E | 0 | 0 .. 1280 step 16 | Multi Roi Offset X |
| MultiRoiOffsetY | int | rw | E | 0 | 0 .. 1920 step 1 | Multi Roi Offset Y |
| MultiRoiIndexMax | enum | rw | E | Index 8 | Index 1 / Index 2 / Index 3 / Index 4 / Index 5 / Index 6 / Index 7 / Index 8 | Multi Roi Index Max |
| HighDynamicRangeMode | bool | rw | E | False |  | Set High Dynamic Range Mode. |
| HighDynamicRangeSlope | enum | rw | E | Level 1 | Level 1 / Level 2 / Level 3 / Level 4 | Set High Dynamic Range Slope. |
| DarkCompression | enum | rw | E | Linear | Linear / Dark Compression | Dark Compression |

## LUTControl (3)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| LUTSelector | enum | rw | E | Luminance | Luminance | This feature selects which LUT is controlled by the various LUT features. |
| LUTIndex | int | rw | G | 0 | 0 .. 255 step 1 | This feature provides the index (offset) of the coefficient to access in the selected LUT. |
| LUTValue | int | rw | G | 0 | 0 .. 4095 step 1 | This feature represents the Value found at entry LUTIndex of the LUT selected by LUTSelector. |

## PulseGenerators (16)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| ClockPreScaler | int | rw | E | 100 | 1 .. 4096 step 1 | Clock Pre-scaler for the Pulse Generators |
| PulseGeneratorClock | float | rw | B | 0.72 | 0.017578125 .. 72.0 | Pulse Generator Clock (MHz). |
| PulseGeneratorSelector | enum | rw | B | Pulse Generator 0 | Pulse Generator 0 / Pulse Generator 1 | Pulse Generator Selector |
| PulseGeneratorLength | int | rw | E | 1 | 1 .. 1048575 step 1 | Pulse Generator Length in Pulse Generator Clock ticks. |
| PulseGeneratorLengthMs | float | rw | B | 0.00138889 | 0.001388888888888889 .. 1456.3541666666667 | Pulse Generator Length in milliseconds. |
| PulseGeneratorFrequency | float | rw | B | 720000 | 0.6866461626493097 .. 720000.0 | Pulse Generator Frequency in Hz. |
| PulseGeneratorStartPoint | int | rw | E | 0 | 0 .. 1048574 step 1 | Pulse Generator Start Point in Pulse Generator Clock ticks. |
| PulseGeneratorStartPointMs | float | rw | B | 0 | 0.0 .. 1456.3527777777779 | Pulse Generator Start Point in milliseconds. |
| PulseGeneratorEndPoint | int | rw | E | 15000 | 1 .. 1048575 step 1 | Pulse Generator End Point in Pulse Generator Clock ticks. |
| PulseGeneratorEndPointMs | float | rw | B | 20.8333 | 0.001388888888888889 .. 1456.3541666666667 | Pulse Generator End Point in milliseconds. |
| PulseGeneratorPulseWidthMs | float | ro | B | 20.8333 | -1.7976931348623157e+308 .. 1.7976931348623157e+308 | Pulse Generator pulse-width in milliseconds. |
| PulseGeneratorRepeatCount | int | rw | B | 0 | 0 .. 255 step 1 | Pulse Generator Repeat Count |
| PulseGeneratorClearActivation | enum | rw | E | Off | Off / High Level / Low Level / Rising Edge / Falling Edge | Selects the activation mode of the input to clear the Pulse Generator. |
| PulseGeneratorClearSource | enum | rw | B | Low | Low / High / Acquisition Trigger Wait / Acquisition Active / Frame Trigger Wait / Frame Active / Exposure Active / FVAL / Pulse Generator 0 / Pulse Generator 1 ... | Selects the source to clear the Pulse Generator. |
| PulseGeneratorClearInverter | bool | rw | E | False |  | Controls if the pulse generator clear signal is inverted. |
| PulseGeneratorClearSyncMode | enum | rw | E | Async Mode | Async Mode / Sync Mode | Selects the sync mode of the input to clear the Pulse Generator. |

## TransportLayerControl (2)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| PayloadSize | int | ro | B | 1310720 | 0 .. 4294967295 step 1 | Size of the payload in bytes |
| TestPendingAck | int | rw | B | 0 | 0 .. 10000 step 1 | Pending Ack timeout Value |

## UserSetControl (3)

| attribute | type | access | vis | value now | range / values | description |
|---|---|---|---|---|---|---|
| UserSetSelector | enum | rw | B | User Set1 | Default / User Set1 / User Set2 / User Set3 | Selects the feature User Set to load, save or configure. |
| UserSetLoad | command | wo | B |  |  | Loads the User Set specified by UserSetSelector to the device and makes it active. |
| UserSetSave | command | wo | B |  |  | Save the User Set specified by UserSetSelector to the non-volatile memory of the device. |
