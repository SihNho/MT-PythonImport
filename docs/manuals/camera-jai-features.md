# JAI SP-5000M-USB: every GenICam feature the camera exposes (from the camera's XML, 2026-11-04)

Owner 2026-11-04: "the camera has far more controls than exposure, rate and gain: ROI, even TTL; list them from NI
MAX". This is the camera's own feature file as NI-IMAQdx cached it (`C:/Users/Public/Documents/National Instruments/NI-IMAQdx/Data/XML/JAI Corporation_SP-5000_SP-5000M-USB_0.3.0.0_...xml`),
the same tree NI MAX shows. 193 user-facing features in 12 categories; vis B = beginner, E = expert, G = guru (NI MAX's
levels). What the program exposes today: exposure, frame rate, gain (read-only), ROI (`api.camera`); the panel plan is
in [design/gui.md](../design/gui.md).

## DeviceControl (20)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| DeviceVendorName | StringReg | B |  |  | Device Vendor Name from the Bootstrap Register |
| DeviceModelName | StringReg | B |  |  | Device Model Name from the Bootstrap Register |
| DeviceManufacturerInfo | StringReg | B |  |  | Device Manufacturer Info from the Bootstrap Register |
| DeviceVersion | StringReg | B |  |  | Device Version from the Bootstrap Register |
| DeviceFirmwareVersion | StringReg | B |  |  | DeviceFirmwareVersion |
| DeviceSFNCVersionMajor | Integer | B |  |  | Major Version of the Standard Features Naming Convention |
| DeviceSFNCVersionMinor | Integer | B |  |  | Minor Version of the Standard Features Naming Convention |
| DeviceSFNCVersionSubMinor | Integer | B |  |  | Sub Minor Version of the Standard Features Naming Convention |
| DeviceManifestXMLMajorVersion | Integer | G |  |  | Indicates the major version number of the XML file of the selected manifest entry.  |
| DeviceManifestXMLMinorVersion | Integer | G |  |  | Indicates the minor version number of the XML file of the selected manifest entry.  |
| DeviceManifestXMLSubMinorVersion | Integer | G |  |  | Indicates the sub minor version number of the XML file of the selected manifest entry.  |
| DeviceID | StringReg | E |  |  | Device ID from the Bootstrap Register |
| DeviceFpgaVersion | StringReg | B |  |  | DeviceFpgaVersion |
| DeviceUserID | StringReg | B |  |  | Device User ID |
| DeviceScanType | Enumeration | E |  | Areascan | DeviceScanType |
| DeviceTemperatureSelector | Enumeration | E |  | Mainboard | DeviceTemperatureSelector |
| DeviceTemperature | Float | E |  |  | DeviceTemperature |
| DeviceClockSelector | Enumeration | E |  | Sensor | DeviceClockSelector |
| DeviceClockFrequency | Float | E |  |  | DeviceClockFrequency |
| DeviceReset | Command | G |  |  | Resets the device to its power up state. |

## ImageFormatControl (13)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| SensorWidth | Integer | E |  |  | Width of the image sensor in pixels |
| SensorHeight | Integer | E |  |  | Height of the image sensor in pixels |
| WidthMax | Integer | E |  |  | Width Max |
| HeightMax | Integer | E |  |  | Height Max |
| Width | Integer | B |  |  | Width of the image in pixels |
| Height | Integer | B |  |  | Height of the image in pixels |
| OffsetX | Integer | B |  |  | X Offset of the image in pixels |
| OffsetY | Integer | B |  |  | Y Offset of the image in pixels |
| BinningHorizontal | Integer | E | 1..2 |  | BinningHorizontal |
| BinningVertical | Integer | E | 1..2 |  | Vertical Binning |
| JaiBinningGainEnable | Boolean | E |  |  | Specifies whether or not to Gain Up by Binning operation. |
| PixelFormat | Enumeration | B |  | Mono8 / Mono10 / Mono10p / Mono12 / Mono12p | Pixel Format as specified in GigE Vision standard |
| TestImageSelector | Enumeration | B |  | Off / GreyHorizontalRamp / GreyVerticalRamp / GreyHorizontalRampMoving | This feature selects the type of test image that is expelled by the camera. |

## AcquisitionControl (15)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| AcquisitionMode | Enumeration | B |  | SingleFrame / MultiFrame / Continuous | Sets the acquisition mode of the device. |
| AcquisitionStop | Command | B |  |  | Stops the Acquisition of the device at the end of the current Frame. |
| AcquisitionFrameCount | Integer | B | 1..65535 |  | Number of frames to acquire in MultiFrame Acquisition mode. |
| AcquisitionFrameRate | Float | B |  |  | Controls the acquisition rate(in Hertz) at which the frames are captured. |
| AcquisitionFrameRateRaw | Integer | B |  |  | Controls the acquisition rate(in us) at which the frames are captured. |
| TriggerSelector | Enumeration | B |  | AcquisitionStart / AcquisitionEnd / FrameStart / JAIAcquisitionTransferStart | Selects the type of trigger to configure. |
| TriggerMode | Enumeration | B |  | Off / On | Controls if the selected trigger is active. |
| TriggerSoftware | Command | B |  |  | Generates an internal trigger. |
| TriggerSource | Enumeration | B |  | Low / High / Software / JAIPulseGenerator0 / JAIPulseGenerator1 / JAIUserOutput0 / JAIUserOutput1 / JAIUserOutput2 ... | Specifies the internal signal or physical input Line to use as the trigger source. The sel |
| TriggerActivation | Enumeration | B |  | RisingEdge / FallingEdge / LevelHigh / LevelLow | Specifies the activation mode of the trigger. |
| TriggerOverLap | Enumeration | E |  | Off / ReadOut | Specifies the type trigger overlap permitted with the previous frame. |
| ExposureMode | Enumeration | B |  | Off / Timed / TriggerWidth | Sets the operation mode of the Exposure (or shutter). |
| ExposureTime | Float | B |  |  | Sets the Exposure time (in microseconds) when ExposureMode is Timed. |
| ExposureTimeRaw | Integer | B |  |  | Sets the Exposure time (in microseconds) when ExposureMode is Timed. |
| ExposureAuto | Enumeration | B |  | Off / Once / Continuous | Sets the automatic exposure mode when ExposureMode is Timed. |

## DigitalIOControl (8)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| LineSelector | Enumeration | E |  | Line1 / Line2 / Line4 / Line5 / Line8 / Line9 / Line10 / Line11 ... | Selects the physical line (or pin) of the external device connector to configure. |
| LineMode | Enumeration | E |  | Input / Output | Controls if the physical Line is used to Input or Output a signal. |
| LineInverter | Boolean | E |  |  | Controls if the signal line is inverted. False means "Active High" and True for "Active Lo |
| LineStatus | Boolean | E |  |  | Line Status |
| LineSource | Enumeration | E |  | Low / High / AcquisitionTriggerWait / AcquisitionActive / FrameTriggerWait / FrameActive / ExposureActive / JAIFVAL ... | Selects which internal acquisition or I/O source signal to output on the selected Line. |
| LineFormat | Enumeration | E |  | NoConnect / InternalSignal / TTL / LVDS / OptoCoupled | Controls the current electrical format of the selected physical input or output Line. |
| UserOutputSelector | Enumeration | E |  | UserOutput0 / UserOutput1 / UserOutput2 / UserOutput3 | Selects User Output. |
| UserOutputValue | Boolean | E |  |  | Sets the value of the selected User Output. |

## AnalogControl (10)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| GainSelector | Enumeration | B |  | DigitalAll | Selects which Gain is controlled by the various Gain features |
| Gain | Float | B |  |  | Controls the selected gain as an absolute physical value. |
| GainRaw | Integer | G |  |  | Controls the selected gain as a raw integer value. |
| GainAuto | Enumeration | B |  | Off / Once / Continuous | Sets the automatic gain control (AGC) mode. |
| AnalogBaseGainSelector | Enumeration | E |  | All / Red / Green / Blue | Select Analog Base Gain channel. |
| AnalogBaseGain | Enumeration | E |  | AnalogBaseGain0dB / AnalogBaseGain6dB / AnalogBaseGain12dB | Set Analog Gain of CMOS sensor. |
| BlackLevelSelector | Enumeration | E |  | DigitalAll | Selects which Black Level is controlled by the various Black Level features. |
| BlackLevelRaw | Integer | E | -256..255 |  | Controls the selected gain as an absolute physical value. |
| JAILUTMode | Enumeration | E |  | Off / Gamma / LUT | Select Gamma or LUT to control. |
| JAIGamma | Integer | B | 0..8 |  | Controls the gamma correction of pixel intensity. |

## PulseGenerators (16)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| ClockPreScaler | Integer | E | 1..4096 |  | Clock Pre-scaler for the Pulse Generators |
| PulseGeneratorClock | Float | B |  |  | Pulse Generator Clock (MHz). |
| PulseGeneratorSelector | Enumeration | B |  | PulseGenerator0 / PulseGenerator1 | Pulse Generator Selector |
| PulseGeneratorLength | Integer | E | 1..1048575 |  | Pulse Generator Length in Pulse Generator Clock ticks. |
| PulseGeneratorLengthMs | Float | B |  |  | Pulse Generator Length in milliseconds. |
| PulseGeneratorFrequency | Float | B |  |  | Pulse Generator Frequency in Hz. |
| PulseGeneratorStartPoint | Integer | E | 0..1048574 |  | Pulse Generator Start Point in Pulse Generator Clock ticks. |
| PulseGeneratorStartPointMs | Float | B |  |  | Pulse Generator Start Point in milliseconds. |
| PulseGeneratorEndPoint | Integer | E | 1..1048575 |  | Pulse Generator End Point in Pulse Generator Clock ticks. |
| PulseGeneratorEndPointMs | Float | B |  |  | Pulse Generator End Point in milliseconds. |
| PulseGeneratorPulseWidthMs | SwissKnife | B |  |  | Pulse Generator pulse-width in milliseconds. |
| PulseGeneratorRepeatCount | Integer | B | 0..255 |  | Pulse Generator Repeat Count |
| PulseGeneratorClearActivation | Enumeration | E |  | Off / HighLevel / LowLevel / RisingEdge / FallingEdge | Selects the activation mode of the input to clear the Pulse Generator. |
| PulseGeneratorClearSource | Enumeration | B |  | Low / High / AcquisitionTriggerWait / AcquisitionActive / FrameTriggerWait / FrameActive / ExposureActive / JAIFVAL ... | Selects the source to clear the Pulse Generator. |
| PulseGeneratorClearInverter | Boolean | E |  |  | Controls if the pulse generator clear signal is inverted. |
| PulseGeneratorClearSyncMode | Enumeration | E |  | AsyncMode / SyncMode | Selects the sync mode of the input to clear the Pulse Generator. |

## LUTControl (3)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| LUTSelector | Enumeration | E |  | Luminance / Green / Blue | This feature selects which LUT is controlled by the various LUT features. |
| LUTIndex | Integer | G | 0..255 |  | This feature provides the index (offset) of the coefficient to access in the selected LUT. |
| LUTValue | Integer | G | 0..4095 |  | This feature represents the Value found at entry LUTIndex of the LUT selected by LUTSelect |

## TransportLayerControl (2)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| PayloadSize | Integer | B |  |  | Size of the payload in bytes |
| TestPendingAck | Integer | B | 0..10000 |  | Pending Ack timeout Value |

## UserSetControl (3)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| UserSetSelector | Enumeration | B |  | Default / UserSet1 / UserSet2 / UserSet3 | Selects the feature User Set to load, save or configure. |
| UserSetLoad | Command | B |  |  | Loads the User Set specified by UserSetSelector to the device and makes it active. |
| UserSetSave | Command | B |  |  | Save the User Set specified by UserSetSelector to the non-volatile memory of the device. |

## JAICustomControl (71)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| VideoProcessBypass | Boolean | E |  |  | Bypass Video Process. |
| ALCReference | Integer | B | 10..100 |  | AGC/Auto-Shutter Reference |
| ALCAreaSelector | Enumeration | E |  | LowRight / LowMidRight / LowMidLeft / LowLeft / MidLowRight / MidLowMidRight / MidLowMidLeft / MidLowLeft ... | ALC Area Selector |
| ALCAreaEnable | Boolean | E |  |  | ALC Area Enable |
| ALCAreaEnableAll | Enumeration | E |  | Off / On | ALC Area Enable All |
| AutoShutterControlExposureMin | Integer | B |  |  | Auto Shutter Control Exposure Value Min. |
| AutoShutterControlExposureMax | Integer | B |  |  | Auto Shutter Control Exposure Value Max. |
| AutoGainControlGainRawMin | Integer | B |  |  | Auto Gain Control GainRaw Value Min. |
| AutoGainControlGainRawMax | Integer | B |  |  | Auto Gain Control GainRaw Value Max. |
| ALCControlSpeed | Integer | B | 1..8 |  | AGC/ASC Control Speed |
| ALCStatus | Enumeration | E |  | Off / AIC / ASC / AGC | Indicate ALC Status. |
| AWBAreaSelector | Enumeration | E |  | LowRight / LowMidRight / LowMidLeft / LowLeft / MidLowRight / MidLowMidRight / MidLowMidLeft / MidLowLeft ... | AWB Area Selector |
| AWBAreaEnable | Boolean | E |  |  | AWB Area Enable |
| AWBAreaEnableAll | Enumeration | E |  | Off / On | AWB Area Enable All |
| TriggerOption | Enumeration | E |  | Off / RCT / PIV | Select RCT or PIV to control. |
| BlemishReductionEnable | Boolean | E |  |  | Blemish Reduction Enable |
| BlemishReductionCalibration | Command | E |  |  | Perform White Blemish Reduction Calibration |
| BlemishDetectThreshold | Integer | E | 0..100 |  | Blemish Detect Threshold |
| BlemishDataIndex | Integer | E | 1..512 |  | Blemish Data Index |
| BlemishDataPositionX | Integer | E | -1..2559 |  | Blemish Data Position X Value |
| BlemishDataPositionY | Integer | E | -1..2047 |  | Blemish Data Position Y Value |
| BlemishNum | Integer | E |  |  | Number of the Blemish Compensation pixels |
| ShadingCorrectionMode | Enumeration | E |  | FlatShading / ColorShading | Shading Correction Mode |
| ShadingMode | Enumeration | B |  | Off / User1 / User2 / User3 | Shading Mode |
| ShadingCalibration | Command | B |  |  | Perform Shading Calibration |
| LensSelect | Enumeration | E |  | None / PIrisLens / MotorLens / VideoIrisLens / DCIrisLens | Lens Select |
| IrisStateControl | Enumeration | E |  | Video / Close / Open | Iris State control |
| PIrisStepMax | Integer | E | 0..255 |  | P-IRIS Step Max |
| PIrisPositionLimit | Integer | E | 0..200 |  | P-IRIS Position Limit |
| PIrisPosition | Integer | E |  |  | P-IRIS Position |
| PIrisLensSelect | Enumeration | E |  | LM16JC5MM / LM35JC5MM / CNG1P9M10 / CNG1P8M48 / CNGCOMPACTIRIS / MG3518KC / OTHERS | P-IRIS Lens Select |
| PIrisAutoStepMin | Integer | E |  |  | P-IRIS Auto Minimum Step No |
| PIrisAutoStepMax | Integer | E |  |  | P-IRIS Auto Maximum Step No |
| PIrisAutoMin | Enumeration | E |  | F_OPEN / F_14 / F_20 / F_28 / F_40 / F_56 / F_80 / F_110 ... | P-IRIS Auto Minimum F_No |
| PIrisAutoMax | Enumeration | E |  | F_OPEN / F_14 / F_20 / F_28 / F_40 / F_56 / F_80 / F_110 ... | P-IRIS Auto Maximum F_No |
| PIrisCurrentFvalue | Enumeration | E |  | F_OPEN / F_14 / F_20 / F_28 / F_40 / F_56 / F_80 / F_110 ... | Indicate current P-IRIS F_No |
| JAIDcIrisReference | Integer | E | 10..95 |  | DC IRIS Reference |
| JAIDcIrisGain | Float | E | 0.5..4.0 |  | Feedback gain for DC IRIS. |
| AutoIrisLensControlSignalOutput | Enumeration | E |  | Off / On | Auto Iris Lens Control Signal Output |
| MotorLensIris | Enumeration | E |  | Stop / Open / Close | Motor Lens Iris |
| MotorLensZoom | Enumeration | E |  | Stop / Wide / Tele | Motor Lens Zoom |
| MotorLensFocus | Enumeration | E |  | Stop / Near / Far | Motor Lens Focus |
| VideoSendMode | Enumeration | E |  | NormalMode / TriggerSequenceMode / CommandSequenceMode / MultiRoiMode | Video Send Mode Selector |
| SequenceRoiIndex | Enumeration | E |  | Index1 / Index2 / Index3 / Index4 / Index5 / Index6 / Index7 / Index8 ... | Sequence Roi Index |
| SequenceRoiFrameCount | Integer | E | 1..255 |  | Sequence Roi Frame Count |
| SequenceRoiNextIndex | Enumeration | E |  | Index1 / Index2 / Index3 / Index4 / Index5 / Index6 / Index7 / Index8 ... | Sequence Roi Next Index |
| SequenceRoiWidth | Integer | E |  |  | Sequence Roi Width |
| SequenceRoiHeight | Integer | E |  |  | Sequence Roi Height |
| SequenceRoiOffsetX | Integer | E |  |  | Sequence Roi Offset X |
| SequenceRoiOffsetY | Integer | E |  |  | Sequence Roi Offset Y |
| SequenceRoiGain | Integer | E | 100..1600 |  | Sequence Roi Gain |
| SequenceRoiGainR | Integer | E | -4533..17713 |  | Sequence Roi Gain Red |
| SequenceRoiGainB | Integer | E | -4533..17713 |  | Sequence Roi Gain Blue |
| SequenceRoiExposureTime | Integer | E | 10..8000000 |  | Sequence Roi Exposure Time |
| SequenceRoiHBinning | Integer | E | 1..2 |  | Sequence Roi H Binning |
| SequenceRoiVBinning | Integer | E | 1..2 |  | Sequence Roi V Binning |
| SequenceRoiLutEnable | Boolean | E |  |  | Sequence Roi Lut Enable |
| SequenceRoiBlackLevel | Integer | E | -256..255 |  | Sequence Roi Black Level |
| SequenceRepetition | Integer | E | 1..255 |  | Sequence Repetition. |
| CommandSequenceIndex | Enumeration | E |  | Index1 / Index2 / Index3 / Index4 / Index5 / Index6 / Index7 / Index8 ... | Command Sequence Index |
| CurrentSequenceIndex | Enumeration | E |  | Index1 / Index2 / Index3 / Index4 / Index5 / Index6 / Index7 / Index8 ... | Current Sequence Index |
| SequenceLutMode | Enumeration | E |  | Gamma / LUT | Select Sequence LUT mode. |
| SequenceReset | Command | B |  |  | Reset Sequence Index |
| MultiRoiIndex | Enumeration | E |  | Index1 / Index2 / Index3 / Index4 / Index5 / Index6 / Index7 / Index8 | Multi Roi Index |
| MultiRoiWidth | Integer | E |  |  | Multi Roi Width |
| MultiRoiHeight | Integer | E |  |  | Multi Roi Height |
| MultiRoiOffsetX | Integer | E |  |  | Multi Roi Offset X |
| MultiRoiOffsetY | Integer | E |  |  | Multi Roi Offset Y |
| MultiRoiIndexMax | Enumeration | E |  | Index1 / Index2 / Index3 / Index4 / Index5 / Index6 / Index7 / Index8 | Multi Roi Index Max |
| HighDynamicRangeMode | Boolean | E |  |  | Set High Dynamic Range Mode. |
| HighDynamicRangeSlope | Enumeration | E |  | DynamicRangeLevel1 / DynamicRangeLevel2 / DynamicRangeLevel3 / DynamicRangeLevel4 | Set High Dynamic Range Slope. |

## JAICustomFactorySetting (32)

| feature | type | vis | range | values | description |
|---|---|---|---|---|---|
| FactoryStoreAll | Command | G |  |  | Factory Store All |
| FactoryDeviceModelName | StringReg | G |  |  | Factory Device Model Name |
| FactoryDeviceVersion | StringReg | E |  |  | For editing the Device Version |
| FactoryDeviceID | StringReg | E |  |  | Factory Device ID |
| FactorySensorVersion | Enumeration | G |  | Version1V0 / Version1V1 / Version1V2 | Sensor Version |
| FactoryAuxSelect | Enumeration | G |  | MotorPIris / VideoDCIris / OptionalGPIO | Selection of auxiliary board. |
| FactoryBlemishWhiteDetect | Command | E |  |  | Perform White Blemish Reduction Calibration |
| FactoryBlemishWhiteThreshold | Integer | E | 0..100 |  | White Blemish Detect Threshold |
| FactoryBlemishWhiteDataIndex | Integer | E | 1..511 |  | White Blemish Data Index |
| FactoryBlemishWhiteDataPositionX | Integer | E | -1..2559 |  | White Blemish Data Position X |
| FactoryBlemishWhiteDataPositionY | Integer | E | -1..2047 |  | White Blemish Data Position Y |
| FactoryBlemishWhiteNum | Integer | E |  |  | Number of the Factory White Blemish Compensation pixels |
| FactoryBlemishBlackDetect | Command | E |  |  | Perform Black Blemish Reduction Calibration |
| FactoryBlemishBlackThreshold | Integer | E | 0..100 |  | Black Blemish Detect Threshold |
| FactoryBlemishBlackDataIndex | Integer | E | 1..511 |  | Black Blemish Data Index |
| FactoryBlemishBlackDataPositionX | Integer | E | -1..2559 |  | Black Blemish Data Position X |
| FactoryBlemishBlackDataPositionY | Integer | E | -1..2047 |  | Black Blemish Data Position Y |
| FactoryBlemishBlackNum | Integer | E |  |  | Number of the Factory Black Blemish Compensation pixels |
| FactoryInGain | Integer | E | 8192..24576 |  | Factory Gain Compensation Value of All Channels. |
| FactoryInGainAdjust | Integer | E | -4533..4533 |  | Factory Gain Compensation Value of All Channels. |
| FactoryBlackSetupLR | Integer | E | 0..255 |  | Setup Level of Black for Linear mode |
| FactoryBlackSetupDC | Integer | E | 0..255 |  | Setup Level of Black for Dark Compression mode |
| FactoryBlackOffsetAllLR | Integer | E | 0..1023 |  | Factory Black Offset Compensation Value of All Channels for Linear mode. |
| FactoryBlackOffsetAllDC | Integer | E | 0..1023 |  | Factory Black Offset Compensation Value of All Channels for Dark Compression mode. |
| FactoryTemperatureFactor | Float | E | 0.2..16.0 |  |  |
| FactorySensorGlobalOffset | Integer | E | -1000..1000 |  |  |
| FactoryHighDynamicRangePoint | Integer | E | 16..30 |  | Set High Dynamic Range Point. |
| FactoryBootAreaSet | Enumeration | G |  | Default / Update |  |
| FactorySensorBlackLevelSrc | Integer | E | -2048..2047 |  |  |
| FactorySensorBlackLevelDst | Integer | E | -2048..2047 |  |  |
| FactorySensorBlackLevelDstR | Integer | E | -2048..2047 |  |  |
| FactorySensorBlackLevelDstB | Integer | E | -2048..2047 |  |  |
