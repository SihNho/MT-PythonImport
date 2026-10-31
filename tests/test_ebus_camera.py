"""The eBUS camera driver (decision 0028) against a fake PvDotNet: enumeration, settings read / write with the SFNC
names, the frame thread (BlockID -> buffer number, camera ticks -> seconds since the first frame, one copy out of the
buffer memory) and a clean stop."""
import threading
import time

import numpy as np
import pytest

from mtpy.devices import ebus


class _Res:
    def __init__(self, ok=True):
        self.IsOK = ok


class _Params:
    def __init__(self):
        self.v = {"ExposureTime": 1909.0, "Gain": 16.0, "AcquisitionFrameRate": 90.0009, "OffsetX": 0, "OffsetY": 0,
                  "Width": 1280, "Height": 1024, "ExposureAuto": "Continuous", "DeviceFirmwareVersion": "0.2.0.0"}
        self.commands = []

    def GetFloatValue(self, k):
        return self.v[k]

    def GetIntegerValue(self, k):
        return self.v[k]

    def GetEnumValueAsString(self, k):
        return self.v[k]

    def GetStringValue(self, k):
        return self.v[k]

    def SetFloatValue(self, k, x):
        self.v[k] = float(x)

    def SetIntegerValue(self, k, x):
        self.v[k] = int(x)

    def SetEnumValue(self, k, x):
        self.v[k] = x

    def ExecuteCommand(self, c):
        self.commands.append(c)


class _Info:
    ModelName, SerialNumber, U3VSerialNumber, DisplayID = "SP-5000M-USB", "", "U500336", "SP-5000M-USB [14FB0067A270]"


class _Interface:
    DeviceCount = 1

    def GetDeviceInfo(self, j):
        return _Info()


class _System:
    InterfaceCount = 1

    def Find(self):
        pass

    def GetInterface(self, i):
        return _Interface()


class _Device:
    PayloadSize = 1280 * 1024

    def __init__(self):
        self.Parameters, self.streaming, self.connected = _Params(), False, True

    def StreamEnable(self):
        self.streaming = True

    def StreamDisable(self):
        self.streaming = False

    def Disconnect(self):
        self.connected = False


class _Image:
    def __init__(self, arr):
        self.arr, self.Width, self.Height = arr, arr.shape[1], arr.shape[0]


class _Buffer:
    def __init__(self, block, ticks, arr):
        self.BlockID, self.Timestamp, self.Image, self.OperationResult = block, ticks, _Image(arr), _Res()


class _Pipeline:
    """Delivers 8 x 6 frames with BlockID 0, 1, 3 (one camera-side gap) 10 ms apart, then times out."""
    def __init__(self, stream):
        self.frames = [_Buffer(b, 454180755071670 + i * 10_000_000, np.full((6, 8), 10 * b, np.uint8))
                       for i, b in enumerate((0, 1, 3))]
        self.released, self.started = [], None

    def Start(self):
        self.started = True

    def Stop(self):
        self.started = False

    def RetrieveNextBuffer(self, buf, timeout_ms):
        if self.frames:
            return _Res(True), self.frames.pop(0)
        time.sleep(min(timeout_ms, 50) / 1000.0)
        return _Res(False), buf

    def ReleaseBuffer(self, buf):
        self.released.append(buf.BlockID)


class _Stream:
    closed = False

    def Close(self):
        self.closed = True


class _Pv:
    PvSystem = _System

    class PvBuffer:
        BlockID = -1

    class PvDevice:
        @staticmethod
        def CreateAndConnect(info):
            return _Device()

    class PvStream:
        @staticmethod
        def CreateAndOpen(info):
            return _Stream()

    PvPipeline = _Pipeline


class _Helper:
    @staticmethod
    def ImageAddress(im):
        return im.arr.ctypes.data


@pytest.fixture
def cam(monkeypatch):
    monkeypatch.setattr(ebus, "_load", lambda: (_Pv, _Helper))
    monkeypatch.setattr(ebus, "_permitted", lambda: None)
    c = ebus.EbusCamera()
    c.open()
    yield c
    c.close()


def test_identity_settings_and_sfnc_writes(cam):
    assert cam.identity()["serial"] == "U500336" and cam.identity()["model"] == "SP-5000M-USB"
    s = cam.settings()
    assert s["exposure_ms"] == pytest.approx(1.909) and s["rate_Hz"] == pytest.approx(90.0009) and s["roi"] == (0, 0, 1280, 1024)
    cam.set("exposure_ms", 2.5)
    assert cam.dev.Parameters.v["ExposureTime"] == 2500.0 and cam.dev.Parameters.v["ExposureAuto"] == "Off"
    cam.set("roi", (64, 32, 640, 480))
    assert [cam.dev.Parameters.v[k] for k in ("OffsetX", "OffsetY", "Width", "Height")] == [64, 32, 640, 480]
    with pytest.raises(RuntimeError, match="read-only"):
        cam.set("gain_dB", 3.0)


def test_frames_carry_block_id_camera_time_and_pixels_then_stop_is_clean(cam):
    cam.start_acquisition()
    assert cam.acquiring() and cam.dev.streaming and cam.dev.Parameters.commands == ["AcquisitionStart"]
    frames = [cam.next_frame(2.0) for _ in range(3)]
    assert [f.buffer_number for f in frames] == [0, 1, 3]                      # the gap is the pipeline's to count
    assert [round(f.t_camera_s, 6) for f in frames] == [0.0, 0.01, 0.02]      # 1 GHz ticks -> s since the first frame
    assert frames[2].image.shape == (6, 8) and int(frames[2].image[0, 0]) == 30
    assert cam.next_frame(0.1) is None and cam.error is None
    with pytest.raises(RuntimeError, match="while acquiring"):
        cam.set("rate_Hz", 150.0)
    stream, pipe = cam._stream
    cam.stop_acquisition()
    assert not cam.acquiring() and not cam.dev.streaming and stream.closed and pipe.started is False
    assert cam.dev.Parameters.commands[-1] == "AcquisitionStop" and pipe.released == [0, 1, 3]
    assert not threading.active_count() > 50


def test_camera_sdk_preset_key_selects_the_driver_imaqdx_by_default():
    """Owner 2026-11-01: IMAQdx stays the default (LabVIEW experiments share the camera on NI's driver); eBUS is chosen
    by the preset key the Setup panel sets."""
    from mtpy import devices
    from mtpy.devices.jai import JaiCamera
    assert isinstance(devices._camera({"backend": "real"}), JaiCamera)
    assert isinstance(devices._camera({"backend": "real", "camera_sdk": "imaqdx"}), JaiCamera)
    assert isinstance(devices._camera({"backend": "real", "camera_sdk": "ebus"}), ebus.EbusCamera)
    with pytest.raises(NotImplementedError, match="camera_sdk"):
        devices._camera({"backend": "real", "camera_sdk": "gentl"})
