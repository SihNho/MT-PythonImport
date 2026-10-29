"""Fake serial controllers for the motion-gate tests: they answer like the real ones (replies taken from V6 logs and
manuals, see docs/manuals/pi-c863.md, asi-tiger.md, rotor-autonics-pmc2hs.md) and move instantly. Each is a pyserial
stand-in: write / read(1) / reset_input_buffer / close. `log` keeps every command received, so a test can assert
that nothing was written before a refusal."""


class _Port:
    eol_in = b"\n"

    def __init__(self):
        self.log, self._out, self.closed = [], bytearray(), False

    def write(self, data):
        cmd = data.decode().strip()
        self.log.append(cmd)
        r = self.handle(cmd)
        if r is not None:
            self._out += r.encode() + self.eol_in

    def read(self, n=1):
        if not self._out:
            return b""
        b, self._out = bytes(self._out[:n]), self._out[n:]
        return b

    def reset_input_buffer(self):
        self._out = bytearray()

    def close(self):
        self.closed = True


class FakePi(_Port):
    """C-863.11: GCS, '1=<v>' replies, ERR 7 outside TMN/TMX, ERR 5 with the servo off or unreferenced."""

    def __init__(self, pos=12.0, tmn=0.0, tmx=52.0, referenced=False):
        super().__init__()
        self.pos, self.tmn, self.tmx, self.vel = pos, tmn, tmx, 15.0
        self.svo, self.ron, self.frf, self.err = 0, 0, int(referenced), 0
        self.halted = 0

    def handle(self, c):
        q = {"POS?": lambda: f"1={self.pos:.5f}", "TMN?": lambda: f"1={self.tmn:.5f}",
             "TMX?": lambda: f"1={self.tmx:.5f}", "VEL?": lambda: f"1={self.vel:.5f}",
             "SVO?": lambda: f"1={self.svo}", "RON?": lambda: f"1={self.ron}", "FRF?": lambda: f"1={self.frf}",
             "ONT?": lambda: "1=1", "SPA? 1 0x15": lambda: f"1 0X15={self.tmx:.5f}",
             "SPA? 1 0x30": lambda: f"1 0X30={self.tmn:.5f}",
             "*IDN?": lambda: "(c)2013 Physik Instrumente(PI) Karlsruhe, C-863.11,0,1.3.0.7"}
        if c in q:
            return q[c]()
        if c == "ERR?":
            e, self.err = self.err, 0
            return str(e)
        w = c.split()
        if w[0] == "SPA" and w[2] == "0x15":
            self.tmx = float(w[3])
        elif w[0] == "SPA" and w[2] == "0x30":
            self.tmn = float(w[3])
        elif w[0] == "SVO":
            self.svo = int(w[2])
        elif w[0] == "RON":
            self.ron = int(w[2])
        elif w[0] == "FNL":
            self.pos, self.frf = 0.0, 1
        elif w[0] == "VEL":
            self.vel = float(w[2])
        elif w[0] == "HLT":
            self.halted += 1
        elif w[0] == "MOV":
            t = float(w[2])
            if not self.svo or not self.frf:
                self.err = 5
            elif not self.tmn <= t <= self.tmx:
                self.err = 7
            else:
                self.pos = t
        else:
            self.err = 2          # unknown command
        return None


class FakeAsi(_Port):
    """Tiger: CR-terminated commands, ':A ...' replies with CR LF, SL/SU clamp the motion (no error)."""
    eol_in = b"\r\n"

    def __init__(self, x=-18475, y=-27744, z=100, sl=(-500.0, -500.0), su=(500.0, 500.0), zsl=-0.05, zsu=0.05):
        super().__init__()
        self.p = {"X": float(x), "Y": float(y), "Z": float(z)}
        self.sl, self.su = {"X": sl[0], "Y": sl[1], "Z": zsl}, {"X": su[0], "Y": su[1], "Z": zsu}
        self.halted = 0

    def handle(self, c):
        w = c.split()
        if w[0] == "W":
            return f":A {self.p[w[1]]:.0f}"
        if w[0] == "/":
            return "N"
        if w[0] == "V":
            return ":A Version: 3.30"
        if w[0] in ("SL", "SU"):
            d = self.sl if w[0] == "SL" else self.su
            if all(a.endswith("?") for a in w[1:]):
                return ":A " + " ".join(f"{a[0]}={d[a[0]]:.4f}" for a in w[1:])
            for a in w[1:]:
                d[a[0]] = float(a[2:])
            return ":A"
        if w[0] == "M":
            for a in w[1:]:
                ax, t = a[0], float(a[2:])
                self.p[ax] = min(max(t, self.sl[ax] * 1e4), self.su[ax] * 1e4)
            return ":A"
        if c == "\\":
            self.halted += 1
            return ":A"
        return ":N-1"


class FakeRotor(_Port):
    """PMC-2HS: CR-terminated, writes have no reply, POS = 8 hex digits per axis (two's complement)."""
    eol_in = b"\r"

    def __init__(self, pos=-10):
        super().__init__()
        self.pos, self.spd, self.stopped = pos, 100, 0

    def handle(self, c):
        w = c.split()
        if c == "POS":
            return f"POS {self.pos & 0xFFFFFFFF:08X},00000000"
        if c == "SPD":
            return f"SPD {self.spd},100"
        if c == "VER":
            return "VER 1.00"
        if w[0] == "SPD":
            self.spd = int(w[1])
        elif w[0] == "PAB":
            self.pos = int(w[1])
        elif w[0] == "PIC":
            self.pos += int(w[1])
        elif w[0] == "STO":
            self.stopped += 1
        return None
