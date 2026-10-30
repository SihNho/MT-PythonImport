"""What the three real motor drivers share (phase 7; docs/design/motion-gate.md): the rig-lock check and one serial
line with a lock, so the emergency stop can write from any thread while the service thread talks.

The drivers (`pi.py`, `asi.py`, `autonics.py`) are the project's motion gate: each can only write the command strings
it builds itself, re-reads the controller limits inside the same port session before every move, and sets / releases
the limits at open / close with readback. Nothing here sends anything by itself.
"""
import os
import sys
import threading

RIG_DIR = r"G:\Codes\rig"
MOTOR_STATES = ("assembled", "disassembled")      # RULES.md 1: motors in both; experiment never


def permitted(what="the device"):
    """PermissionError unless this process runs under the rig lock in a state that allows `what`."""
    token = os.environ.get("RIGLOCK_TOKEN")
    if not token:
        raise PermissionError(f"no RIGLOCK_TOKEN: {what} opens only under the rig lock "
                              "(api.devices.connect takes it, decision 0026)")
    if RIG_DIR not in sys.path:
        sys.path.insert(0, RIG_DIR)
    import riglock
    if not riglock.permitted(token, MOTOR_STATES):
        raise PermissionError(f"rig lock refuses {what}: experiment declared, lock lost, or not the holder")


class Line:
    """One serial port, one command at a time. `ask` writes a line and returns the reply line (stripped, '' on a
    timeout); `say` writes without reading (controllers whose writes have no reply). `port` is a pyserial Serial or
    a test double with write / readline / reset_input_buffer / close."""

    def __init__(self, port, eol_out, timeout_s):
        self.port, self.eol_out, self.timeout_s = port, eol_out, timeout_s
        self.lock = threading.RLock()

    @classmethod
    def open(cls, name, baud, eol_out, eol_in, timeout_s):
        import serial
        port = serial.Serial(name, baud, bytesize=8, parity="N", stopbits=1, timeout=timeout_s)
        line = cls(port, eol_out, timeout_s)
        line.eol_in = eol_in
        return line

    eol_in = b"\n"

    def say(self, cmd):
        with self.lock:
            self.port.reset_input_buffer()
            self.port.write(cmd.encode("ascii") + self.eol_out)

    def ask(self, cmd):
        with self.lock:
            self.say(cmd)
            return self._readline()

    def _readline(self):
        # pyserial's readline stops only at b"\n"; the ASI replies end in CR LF and the rotor in CR
        buf = bytearray()
        while True:
            c = self.port.read(1)
            if not c:
                break
            buf += c
            if buf.endswith(self.eol_in):
                break
        return buf.decode("ascii", "replace").strip()

    def close(self):
        with self.lock:
            self.port.close()
