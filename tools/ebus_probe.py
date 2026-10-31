"""Rig probe 2026-11-01 (owner: "eBUS로 간다"): the JAI SP-5000M-USB through JAI's eBUS SDK 6.5.3 .NET API (PvDotNet via
pythonnet). Under the shared rig lock (api.rig). Enumerate, identity, GenICam parameters, then stream 10 s at the
current rate and 10 s at 150 Hz / 1.9 ms: frame count, BlockID gaps, dropped flags, copy time. Restores the settings.
"""
import ctypes
import json
import sys
import time

import numpy as np

sys.path.insert(0, r"G:\Codes\LabVIEW2Scr\src")
import clr  # noqa: E402

clr.AddReference(r"C:\Program Files\Common Files\Pleora\eBUS SDK\PvDotNet.dll")
clr.AddReference(r"G:\Codes\LabVIEW2Scr\src\mtpy\devices\ebus_helper\MtpyEbus.dll")
import PvDotNet as Pv  # noqa: E402
from Mtpy import MtpyEbus as H  # noqa: E402

from mtpy.api import events, rig  # noqa: E402


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def find_device():
    sysm = Pv.PvSystem()
    sysm.Find()
    found = []
    for i in range(sysm.InterfaceCount):
        itf = sysm.GetInterface(i)
        for j in range(itf.DeviceCount):
            d = itf.GetDeviceInfo(j)
            found.append((itf.Name, d))
            say(f"  interface {itf.Name!r}: {d.VendorName} {d.ModelName} sn {d.SerialNumber} id {d.ConnectionID} class {d.Class}")
    if not found:
        raise RuntimeError("eBUS finds no device")
    return sysm, found[0][1]


def gen(params, name):
    p = params.Get(name)
    if p is None:
        return None
    t = type(p).__name__
    try:
        if t == "PvGenFloat":
            return p.Value
        if t == "PvGenInteger":
            return int(p.Value)
        if t == "PvGenEnum":
            return p.ValueString
        if t == "PvGenString":
            return p.Value
        if t == "PvGenBoolean":
            return bool(p.Value)
    except Exception as e:  # noqa: BLE001
        return f"<{t}: {e}>"
    return f"<{t}>"


def stream(dev, info, seconds, label):
    params = dev.Parameters
    st = Pv.PvStream.CreateAndOpen(info)
    pipe = Pv.PvPipeline(st)
    pipe.BufferSize = dev.PayloadSize
    pipe.BufferCount = 64
    pipe.Start()
    dev.StreamEnable()
    params.ExecuteCommand("AcquisitionStart")
    n, gaps, dropped, first, last, t_copy, errs = 0, 0, 0, None, None, [], {}
    t0 = time.perf_counter()
    img0 = None
    try:
        while time.perf_counter() - t0 < seconds:
            res, buf = pipe.RetrieveNextBuffer(Pv.PvBuffer(), 1000)      # ref arg: pass an instance, get the real one back
            opres = buf.OperationResult if res.IsOK else None
            if not res.IsOK:
                errs[res.CodeString] = errs.get(res.CodeString, 0) + 1
                continue
            try:
                if opres.IsOK:
                    bid = int(buf.BlockID)
                    if last is not None and bid != last + 1:
                        gaps += bid - last - 1
                    if first is None:
                        first = bid
                    last = bid
                    im = buf.Image
                    if im.IsImageDropped:
                        dropped += 1
                    tc = time.perf_counter()
                    ptr = None
                    addr = H.ImageAddress(im)
                    arr = np.frombuffer(ctypes.string_at(addr, im.Width * im.Height), dtype=np.uint8).reshape(im.Height, im.Width)
                    t_copy.append(time.perf_counter() - tc)
                    if img0 is None:
                        img0 = arr.copy()
                        say(f"  first frame: {im.Width} x {im.Height} {im.PixelType} BlockID {bid} ts {buf.Timestamp} "
                            f"mean {arr.mean():.1f} DataPointer type {type(ptr).__name__}")
                    n += 1
                else:
                    errs[opres.CodeString] = errs.get(opres.CodeString, 0) + 1
            finally:
                pipe.ReleaseBuffer(buf)
    finally:
        params.ExecuteCommand("AcquisitionStop")
        dev.StreamDisable()
        pipe.Stop()
        st.Close()
    dt = time.perf_counter() - t0
    say(f"RESULT {label}: {n} frames in {dt:.1f} s = {n / dt:.2f} Hz; BlockID {first}..{last}, gaps {gaps}, dropped {dropped}, "
        f"copy ms p50/p99 {np.percentile(t_copy, 50) * 1000:.2f}/{np.percentile(t_copy, 99) * 1000:.2f}, errors {errs}")
    return img0


def main():
    with events.as_caller("script:ebus-probe@1"):
        rig.acquire("eBUS probe (owner 2026-11-01: eBUS)")
        try:
            sysm, info = find_device()
            u3v = Pv.PvDeviceInfoU3V
            say("device info:", {k: str(getattr(info, k, None)) for k in ("DisplayID", "ManufacturerInfo", "Version", "UniqueID")})
            if isinstance(info, u3v):
                say("U3V:", {k: str(getattr(info, k)) for k in ("DeviceGUID", "Speed", "IsPleoraDriverInstalled", "U3VSerialNumber")})
            dev = Pv.PvDevice.CreateAndConnect(info)
            say("connected:", dev.IsConnected, "payload", dev.PayloadSize)
            P = dev.Parameters
            names = ["DeviceVendorName", "DeviceModelName", "DeviceSerialNumber", "DeviceFirmwareVersion", "DeviceVersion",
                     "Width", "Height", "OffsetX", "OffsetY", "WidthMax", "HeightMax", "PixelFormat", "BinningHorizontal",
                     "AcquisitionMode", "AcquisitionFrameRate", "AcquisitionFrameRateEnable", "ExposureMode", "ExposureTime",
                     "ExposureAuto", "Gain", "GainAuto", "GainRaw", "GainSelector", "TriggerMode", "TriggerSelector",
                     "TimestampLatch", "TimestampLatchValue", "DeviceTemperature", "GevTimestampTickFrequency",
                     "TimestampTickFrequency"]
            read = {k: gen(P, k) for k in names}
            say("params:", json.dumps(read, default=str))
            # ranges of the ones the program sets
            for k in ("ExposureTime", "AcquisitionFrameRate", "Gain"):
                p = P.Get(k)
                if p is not None and hasattr(p, "Min"):
                    say(f"  {k}: {p.Min} .. {p.Max} {getattr(p, 'Unit', '')}")
            say("category count:", P.CategoryCount, "param count:", P.Count)
            all_names = [P.Get(i).Name for i in range(P.Count)]
            say("all params:", ", ".join(all_names))
            saved = {k: gen(P, k) for k in ("AcquisitionFrameRate", "ExposureTime", "ExposureAuto")}
            img = stream(dev, info, 10.0, f"as found ({saved})")
            if img is not None:
                np.save(r"G:\l2s_rig_data\2026-10-31_refbead_track\ebus_frame.npy", img)
            try:
                P.SetEnumValue("ExposureAuto", "Off")
                P.SetFloatValue("ExposureTime", 1909.0)
                P.SetFloatValue("AcquisitionFrameRate", 150.0)
                say("set 150 Hz / 1.909 ms -> read back", gen(P, "AcquisitionFrameRate"), gen(P, "ExposureTime"))
                stream(dev, info, 10.0, "150 Hz, 1.909 ms")
            finally:
                for k, v in saved.items():
                    try:
                        if k == "ExposureAuto":
                            P.SetEnumValue(k, str(v))
                        else:
                            P.SetFloatValue(k, float(v))
                    except Exception as e:  # noqa: BLE001
                        say(f"  restore {k}={v} failed: {e}")
                say("restored:", {k: gen(P, k) for k in saved})
            dev.Disconnect()
            say("disconnected")
        finally:
            rig.release()
            say("rig lock released:", rig.status())


if __name__ == "__main__":
    main()
