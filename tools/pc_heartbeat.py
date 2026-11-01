"""PC heartbeat log (owner 2026-11-01: the rig PC dies while idle about once a week, no bugcheck, no sleep).

Every 10 s one line into G:\\l2s_rig_data\\pc_heartbeat\\YYYY-MM-DD.log: time, uptime, CPU %, free memory. Files older
than 7 days are deleted. After an unexpected shutdown the last lines show whether the PC stopped at once (10 s
spacing to the end) or slowed / hung first (growing gaps, high CPU). Costs a few ms every 10 s on one core; runs
at below-normal priority so it never competes with tracking.

    python tools/pc_heartbeat.py            # run (the scheduled task does this at logon)
    python tools/pc_heartbeat.py --report   # the last unexpected shutdown (event 6008) and the log around it
"""
import contextlib
import ctypes
import datetime as dt
import os
import subprocess
import sys
import time

DIR = r"G:\l2s_rig_data\pc_heartbeat"
PERIOD_S, KEEP_DAYS = 10, 7


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _mem_free_mb():
    m = _MemStatus()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys // 2**20


class _Cpu:
    """System CPU % between two calls, from GetSystemTimes (no psutil)."""

    def __init__(self):
        self.prev = self._times()

    @staticmethod
    def _times():
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        return idle.value, kernel.value + user.value

    def percent(self):
        idle, total = self._times()
        d_idle, d_total = idle - self.prev[0], total - self.prev[1]
        self.prev = (idle, total)
        return 0.0 if d_total <= 0 else 100.0 * (1 - d_idle / d_total)


def run():
    os.makedirs(DIR, exist_ok=True)
    with contextlib.suppress(Exception):        # priority is a nicety
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL
    cpu = _Cpu()
    last_day = None
    while True:
        now = dt.datetime.now()
        day = now.strftime("%Y-%m-%d")
        if day != last_day:
            for f in os.listdir(DIR):
                try:
                    if f.endswith(".log") and (now - dt.datetime.strptime(f[:10], "%Y-%m-%d")).days > KEEP_DAYS:
                        os.remove(os.path.join(DIR, f))
                except (ValueError, OSError):
                    pass
            last_day = day
        up_s = ctypes.windll.kernel32.GetTickCount64() / 1000.0
        line = f"{now:%Y-%m-%d %H:%M:%S}  up {up_s / 3600:8.3f} h  cpu {cpu.percent():5.1f} %  free {_mem_free_mb():6d} MB\n"
        with open(os.path.join(DIR, day + ".log"), "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())                      # the line must be on disk before the power can go
        time.sleep(PERIOD_S)


def report():
    """The last unexpected shutdown (System log event 6008) and the heartbeat lines before it."""
    ps = ("Get-WinEvent -FilterHashtable @{LogName='System'; Id=6008} -MaxEvents 1 | "
          "ForEach-Object { $_.Message }")
    msg = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False).stdout
    print("last 6008:", " ".join(msg.split())[:120])
    files = sorted(f for f in os.listdir(DIR) if f.endswith(".log")) if os.path.isdir(DIR) else []
    if not files:
        print("no heartbeat files yet")
        return
    with open(os.path.join(DIR, files[-1]), encoding="utf-8") as f:
        lines = f.read().splitlines()
    print(f"{files[-1]}: {len(lines)} lines; the last 12:")
    prev = None
    for ln in lines[-12:]:
        t = dt.datetime.strptime(ln[:19], "%Y-%m-%d %H:%M:%S")
        gap = "" if prev is None else f"   (+{(t - prev).total_seconds():.0f} s)"
        print(ln + gap)
        prev = t


if __name__ == "__main__":
    report() if "--report" in sys.argv else run()
