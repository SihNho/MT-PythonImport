"""Deterministic parser for the three script kinds of docs/format/grammar.md (draft v0, grammar 0.1).

    script = parse(text, file="fe-ramp.mtprot")       # raises ScriptError with every error found
    script.body                                         # list of Stmt (blocks nested)

Parsing never executes anything and never calls a device. It checks the lexical rules (section 2), the statement
keys, their fixed units (a value written with a unit suffix such as `7pN` is an error) and the grammar ranges of the
key tables, and the block structure (`loop` / `if` / `on` ... `end`; `header` / `body` / `footer` ... `end`).
Checks against the public API and the rig safety profile are in `mtpy.protocol.check`.

Every error is a `Diagnostic` printed as `<file>:<line>:<column>: <message>` (grammar section 8); columns are 1-based.
"""
import hashlib
import re
from dataclasses import dataclass, field

from mtpy.api.errors import ScriptError

GRAMMAR_VERSIONS = ("0.1",)
KINDS = {"protocol": ".mtprot", "sequence": ".mtseq", "recipe": ".mtrec"}
MAX_T_S = 36000.0                          # longest time any key accepts (the ramp's range in the draft)


@dataclass(frozen=True)
class Diagnostic:
    file: str
    line: int
    col: int
    message: str
    severity: str = "error"                # "error" | "warning"

    def __str__(self):
        w = "warning: " if self.severity == "warning" else ""
        return f"{self.file}:{self.line}:{self.col}: {w}{self.message}"


@dataclass(frozen=True)
class Arg:
    value: object
    line: int
    col: int
    text: str = ""


@dataclass
class Expr:
    """op: num | name | call | event | kw | cmp | and | or | not. items: the operands (cmp: [op, left, right])."""
    op: str
    items: list
    col: int

    def names(self):
        """Every (name, col) used as a value, and every (function, col) called."""
        if self.op == "name":
            yield ("name", self.items[0], self.col)
        elif self.op == "call":
            yield ("call", self.items[0], self.col)
            for a in self.items[1]:
                yield from a.names()
        elif self.op == "kw":
            if isinstance(self.items[1], Expr):
                yield from self.items[1].names()
        elif self.op == "cmp":
            yield from self.items[1].names()
            yield from self.items[2].names()
        elif self.op in ("and", "or", "not"):
            for x in self.items:
                yield from x.names()


@dataclass
class Stmt:
    kind: str                              # the keyword: hold, loop, frame, observable, ...
    line: int
    col: int
    text: str                              # the source line without its comment
    args: dict = field(default_factory=dict)      # key -> Arg
    pos: list = field(default_factory=list)       # positional Args (record on, mark "text", lights 532 637, ...)
    expr: Expr = None
    body: list = field(default_factory=list)
    orelse: list = None                    # `if` only
    form: str = ""                         # variant: record on|off|timed, light seq|off, wait time|until, ...


@dataclass
class Script:
    kind: str                              # protocol | sequence | recipe
    name: str
    grammar: str
    file: str
    text: str
    sha256: str
    meta: dict = field(default_factory=dict)      # protocol: {"type"}; sequence: {"lights", "ratio"}
    body: list = field(default_factory=list)
    rules: list = field(default_factory=list)     # screening rules (protocol)
    warnings: list = field(default_factory=list)

    @property
    def caller(self):
        """The caller name its run logs: script:<name>@<first 12 hex of the sha256>."""
        name = re.sub(r"[^A-Za-z0-9_.\-]+", "_", self.name).strip("_") or self.kind
        return f"script:{name}@{self.sha256[:12]}"


@dataclass(frozen=True)
class Key:
    """A key of a statement: type num | int | str | onoff | name, fixed unit, grammar range, required."""
    type: str = "num"
    unit: str = ""
    lo: float = None
    hi: float = None
    required: bool = True
    lo_open: bool = False                  # lo excluded (t > 0)


# --- protocol statements (grammar section 3.2), ranges from the draft; WP5 decisions marked in grammar.md ------------
def _t(lo=0.0, hi=MAX_T_S, required=True, lo_open=False):
    return Key("num", "s", lo, hi, required, lo_open)


PN = Key("num", "pN", 0.0)                 # forces >= 0; the upper bound is the force table's at the position limit (0017)
PROTOCOL_KEYS = {
    "zero": {"t": _t(0.1, 600.0)},
    "ramp": {"from": PN, "to": PN, "t": _t(0.1)},
    "hold": {"f": PN, "t": _t()},
    "move": {"mm": Key("num", "mm"), "t": _t(required=False)},
    "rotate": {"from": Key("num", "turns"), "to": Key("num", "turns"), "f": PN, "t": _t(0.1)},
    "focus": {"um": Key("num", "um")},
    "record": {"t": _t(0.1)},
    "light": {"seq": Key("str")},
    "wait": {"t": _t()},
    "loop": {"n": Key("int", "", 1, 10000)},
}
BLOCK_OPENERS = {"protocol": ("loop", "if", "on"), "sequence": ("header", "body", "footer"), "recipe": ()}
LIVE_NAMES = ("force_pN", "extension_um", "z_um", "turns", "t_s")          # grammar section 6
LIBRARY = ("fret", "present", "fell", "rose", "mean", "sd", "rel", "at_start", "fraction")   # section 7

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"[^"]*")
  | (?P<badstr>"[^"]*$)
  | (?P<num>-?\d+(?:\.\d+)?)(?P<suffix>[A-Za-zµ%][A-Za-z0-9_/µ%]*)?
  | (?P<word>[A-Za-z][A-Za-z0-9_]*)
  | (?P<op>>=|<=|==|!=|>|<)
  | (?P<eq>=)
  | (?P<lp>\() | (?P<rp>\)) | (?P<comma>,)
""", re.VERBOSE)


@dataclass(frozen=True)
class Tok:
    kind: str                              # str num numunit word op eq lp rp comma
    text: str
    value: object
    col: int


class _LineError(Exception):
    def __init__(self, col, message):
        super().__init__(message)
        self.col, self.message = col, message


def _strip_comment(s):
    quoted = False
    for i, c in enumerate(s):
        if c == '"':
            quoted = not quoted
        elif c == "#" and not quoted:
            return s[:i]
    return s


def _tokenize(text):
    toks, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if m is None:
            raise _LineError(i + 1, f"unexpected character {text[i]!r} (numbers are written like 7, 1.5 or -10)")
        col, kind = i + 1, m.lastgroup
        i = m.end()
        if kind == "ws":
            continue
        if kind == "badstr":
            raise _LineError(col, "the quoted string is not closed (missing \")")
        if kind == "suffix" or m.group("suffix"):
            toks.append(Tok("numunit", m.group(0), m.group("num"), col))
        elif kind == "num":
            toks.append(Tok("num", m.group(0), float(m.group(0)), col))
        elif kind == "str":
            toks.append(Tok("str", m.group(0), m.group(0)[1:-1], col))
        else:
            toks.append(Tok(kind, m.group(0), m.group(0), col))
    return toks


class _Cursor:
    def __init__(self, toks, line, text):
        self.toks, self.i, self.line, self.text, self.within = toks, 0, line, text, False

    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def at_end(self):
        return self.i >= len(self.toks)

    def end_col(self):
        return len(self.text.rstrip()) + 1

    def col(self):
        t = self.peek()
        return t.col if t is not None else self.end_col()

    def is_word(self, w, k=0):
        t = self.peek(k)
        return t is not None and t.kind == "word" and t.text == w

    def expect_word(self, w, what):
        if not self.is_word(w):
            raise _LineError(self.col(), f"expected {what}")
        return self.next()

    def done(self, what):
        if not self.at_end():
            t = self.peek()
            raise _LineError(t.col, f"unexpected {t.text!r} after {what}")


def _num_text(tok):
    return tok.text if tok.kind == "num" else tok.value


def _value(tok, key, spec, line):
    """The Arg for `key=<tok>` checked against its Key spec (type, unit, grammar range)."""
    unit = f" ({spec.unit})" if spec.unit else ""
    if tok is None:
        raise _LineError(None, f"'{key}=' needs a value")
    if tok.kind == "numunit":
        raise _LineError(tok.col, f"'{key}' is written with a unit ({tok.text!r}); units are fixed per key and never "
                                  f"written in the value: write {key}={tok.value}{unit}")
    if spec.type in ("num", "int"):
        if tok.kind != "num":
            raise _LineError(tok.col, f"'{key}' must be a number{unit}, not {tok.text!r}")
        v = tok.value
        if spec.type == "int":
            if "." in tok.text:
                raise _LineError(tok.col, f"'{key}' must be a whole number, not {tok.text}")
            v = int(v)
        lo_bad = spec.lo is not None and (v <= spec.lo if spec.lo_open else v < spec.lo)
        hi_bad = spec.hi is not None and v > spec.hi
        if lo_bad or hi_bad:
            if spec.lo_open:
                rng = f"more than {spec.lo:g}" + (f" and at most {spec.hi:g}" if spec.hi is not None else "")
            elif spec.lo is not None and spec.hi is not None:
                rng = f"{spec.lo:g}-{spec.hi:g}"
            elif spec.lo is not None:
                rng = f"{spec.lo:g} or more"
            else:
                rng = f"at most {spec.hi:g}"
            raise _LineError(tok.col, f"'{key}' is {tok.text}{unit}; the grammar allows {rng}{unit}")
        return Arg(v, line, tok.col, tok.text)
    if spec.type == "str":
        if tok.kind not in ("str", "word"):
            raise _LineError(tok.col, f"'{key}' must be a name or a quoted string, not {tok.text!r}")
        return Arg(tok.value, line, tok.col, tok.text)
    if spec.type == "onoff":
        if tok.kind != "word" or tok.text not in ("on", "off"):
            raise _LineError(tok.col, f"'{key}' must be on or off, not {tok.text!r}")
        return Arg(tok.text == "on", line, tok.col, tok.text)
    raise AssertionError(spec.type)


def _keyvals(cur, specs, stmt, what, key_kinds=("word",)):
    """Parse `key=value ...` to the end of the line into stmt.args; unknown, repeated and missing keys are errors."""
    while not cur.at_end():
        k = cur.next()
        if k.kind not in key_kinds or cur.peek() is None or cur.peek().kind != "eq":
            raise _LineError(k.col, f"expected key=value after '{what}', got {k.text!r}")
        cur.next()
        key = k.text
        spec = specs.get(key)
        if spec is None:
            allowed = ", ".join(f"{x}=" for x in specs) or "none"
            raise _LineError(k.col, f"'{what}' has no key '{key}' (keys: {allowed})")
        if key in stmt.args:
            raise _LineError(k.col, f"'{key}' is given twice")
        v = cur.next()
        try:
            stmt.args[key] = _value(v, key, spec, cur.line)
        except _LineError as e:
            raise _LineError(e.col or cur.end_col(), e.message) from None
    missing = [k for k, s in specs.items() if s.required and k not in stmt.args]
    if missing:
        raise _LineError(cur.end_col(), f"'{what}' needs {', '.join(f'{m}=' for m in missing)}")


# --- expressions (grammar section 6) --------------------------------------------------------------------------------
_RESERVED = {"and", "or", "not", "within", "timeout", "then", "do", "when"}


def parse_expr(cur):
    """expr := and_expr {"or" and_expr}; and_expr := term {"and" term}  (WP5: `and` binds tighter than `or`)."""
    left = _and(cur)
    while cur.is_word("or"):
        c = cur.next().col
        left = Expr("or", [left, _and(cur)], c)
    return left


def _and(cur):
    left = _term(cur)
    while cur.is_word("and"):
        c = cur.next().col
        left = Expr("and", [left, _term(cur)], c)
    return left


def _term(cur):
    if cur.is_word("not"):
        c = cur.next().col
        return Expr("not", [_term(cur)], c)
    return _factor(cur)


def _factor(cur):
    t = cur.peek()
    if t is not None and t.kind == "lp":
        cur.next()
        e = parse_expr(cur)
        if cur.peek() is None or cur.peek().kind != "rp":
            raise _LineError(cur.col(), "expected ')'")
        cur.next()
        return e
    left = _operand(cur)
    t = cur.peek()
    if t is not None and (t.kind == "op" or (cur.within and t.kind == "word" and t.text == "within")):
        cur.next()
        return Expr("cmp", [t.text, left, _operand(cur)], t.col)
    return left


def _operand(cur):
    t = cur.next()
    if t is None:
        raise _LineError(cur.end_col(), "expected a number, a name or a function call")
    if t.kind == "numunit":
        raise _LineError(t.col, f"{t.text!r}: write numbers without a unit (units are fixed per quantity)")
    if t.kind == "num":
        return Expr("num", [t.value], t.col)
    if t.kind == "word" and t.text not in _RESERVED:
        if cur.peek() is not None and cur.peek().kind == "lp":
            return _call(cur, t)
        return Expr("name", [t.text], t.col)
    raise _LineError(t.col, f"expected a number, a name or a function call, got {t.text!r}")


def _call(cur, name):
    cur.next()                                                    # (
    args = []
    if cur.peek() is not None and cur.peek().kind == "rp":
        cur.next()
        return Expr("call", [name.text, args], name.col)
    while True:
        t = cur.peek()
        if t is None:
            raise _LineError(cur.end_col(), f"'{name.text}(' is not closed")
        if cur.is_word("event") and cur.peek(1) is not None and cur.peek(1).kind == "word":
            cur.next()
            ev = cur.next()
            args.append(Expr("event", [ev.text], ev.col))
        elif t.kind == "word" and cur.peek(1) is not None and cur.peek(1).kind == "eq":
            cur.next()
            cur.next()
            args.append(Expr("kw", [t.text, _operand(cur)], t.col))
        else:
            args.append(parse_expr(cur))
        t = cur.next()
        if t is None:
            raise _LineError(cur.end_col(), f"'{name.text}(' is not closed")
        if t.kind == "rp":
            return Expr("call", [name.text, args], name.col)
        if t.kind != "comma":
            raise _LineError(t.col, f"expected ',' or ')' in '{name.text}(...)', got {t.text!r}")


# --- the parser ------------------------------------------------------------------------------------------------------
class _Parser:
    def __init__(self, text, file):
        self.text, self.file = text, file
        self.diags, self.warnings = [], []
        self.script = None
        self.stack = []                     # open blocks: (Stmt, which list: "body" | "orelse")

    def err(self, line, col, msg):
        self.diags.append(Diagnostic(self.file, line, col or 1, msg))

    def warn(self, line, col, msg):
        self.warnings.append(Diagnostic(self.file, line, col or 1, msg, "warning"))

    def target(self):
        if not self.stack:
            return self.script.body
        st, which = self.stack[-1]
        return st.body if which == "body" else st.orelse

    def run(self):
        lines = self.text.splitlines()
        header_seen = 0                     # 0: expect grammar, 1: expect protocol/sequence/recipe, 2: statements
        version, kind, name = None, None, None
        for n, raw in enumerate(lines, 1):
            body = _strip_comment(raw)
            if not body.strip():
                continue
            try:
                toks = _tokenize(body)
            except _LineError as e:
                self.err(n, e.col, e.message)
                if header_seen < 2:
                    header_seen += 1
                continue
            cur = _Cursor(toks, n, body)
            first = toks[0]
            try:
                if header_seen == 0:
                    header_seen = 1
                    if first.kind != "word" or first.text != "grammar":
                        raise _LineError(first.col, "the first line must be 'grammar 0.1' (the grammar version the "
                                                    "file was written for)")
                    cur.next()
                    v = cur.next()
                    if v is None or v.kind != "num" or v.text not in GRAMMAR_VERSIONS:
                        raise _LineError(v.col if v else cur.end_col(), f"grammar version must be one of "
                                         f"{', '.join(GRAMMAR_VERSIONS)}, got {v.text if v else 'nothing'!r}")
                    cur.done("the grammar version")
                    version = v.text
                    continue
                if header_seen == 1:
                    header_seen = 2
                    if first.kind != "word" or first.text not in KINDS:
                        raise _LineError(first.col, "the second line must name the script: 'protocol \"name\"', "
                                                    "'sequence \"name\"' or 'recipe \"name\"'")
                    cur.next()
                    t = cur.next()
                    if t is None or t.kind not in ("str", "word"):
                        raise _LineError(t.col if t else cur.end_col(), f"'{first.text}' needs a name (a word or a "
                                                                         "quoted string)")
                    cur.done(f"the {first.text} name")
                    kind, name = first.text, t.value
                    ext = KINDS[kind]
                    if "." in self.file and not self.file.endswith(ext) and self.file.rsplit(".", 1)[-1].startswith(
                            "mt"):
                        raise _LineError(first.col, f"a {kind} belongs in a {ext} file, not {self.file!r}")
                    continue
                if kind is None:                    # the header is wrong: statements cannot be read
                    continue
                if self.script is None:
                    self.script = Script(kind, name, version, self.file, self.text, "")
                    if kind == "protocol":
                        self.script.meta["type"] = None
                self.statement(cur, body)
            except _LineError as e:
                self.err(n, e.col, e.message)
        if self.script is None:
            if header_seen < 2:
                self.err(max(1, len(lines)), 1, "the file has no 'grammar 0.1' line and script name line")
            if kind is None:
                return None
            self.script = Script(kind, name, version, self.file, self.text, "", meta={"type": None} if kind ==
                                 "protocol" else {})
        for st, _ in self.stack:
            self.err(st.line, st.col, f"'{st.kind}' is not closed: add 'end'")
        self.finish()
        return self.script

    # -- statements -----------------------------------------------------------------------------------------------
    def statement(self, cur, text):
        t = cur.peek()
        if t.kind != "word":
            raise _LineError(t.col, f"a statement starts with a keyword, not {t.text!r}")
        kw = t.text
        st = Stmt(kw, cur.line, t.col, text.strip())
        end_st = self.script.meta.get("_end")
        if end_st is not None and kw != "rule":            # screening rules may follow (they are not actions)
            raise _LineError(t.col, f"nothing may follow 'end protocol' (line {end_st.line}); it is the last statement")
        if kw == "end":
            cur.next()
            if self.script.kind == "protocol" and cur.is_word("protocol"):     # decision 0016 item 3
                cur.next()
                cur.done("'end protocol'")
                if self.stack:
                    raise _LineError(t.col, "'end protocol' belongs at the top level, as the last statement (close "
                                            "the open blocks with 'end' first)")
                self.script.meta["_end"] = Stmt("end_protocol", cur.line, t.col, text.strip())
                return
            cur.done("'end'")
            if not self.stack:
                raise _LineError(t.col, "'end' without an open block")
            self.stack.pop()
            return
        if kw == "else":
            cur.next()
            cur.done("'else'")
            if not self.stack or self.stack[-1][0].kind != "if" or self.stack[-1][1] != "body":
                raise _LineError(t.col, "'else' without an open 'if'")
            self.stack[-1][0].orelse = []
            self.stack[-1] = (self.stack[-1][0], "orelse")
            return
        try:
            getattr(self, f"_{self.script.kind}")(cur, st)
        except _LineError:
            if kw in BLOCK_OPENERS[self.script.kind]:     # keep the block open so its 'end' still matches
                self.stack.append((st, "body"))
            raise
        if self.script.meta.get("_tail"):
            raise _LineError(t.col, "'repeat n' must be the last statement of the file")
        if st.kind == "_header":
            return
        if st.kind == "rule":
            self.script.rules.append(st)
        elif st.kind == "repeat":
            self.script.meta["_tail"] = st
        else:
            self.target().append(st)
        if st.kind in BLOCK_OPENERS[self.script.kind]:
            self.stack.append((st, "body"))

    def _protocol(self, cur, st):
        kw = st.kind
        cur.next()
        if kw == "kind":
            t = cur.next()
            if self.script.meta["type"] is not None:
                raise _LineError(st.col, "'kind' is given twice")
            if self.script.body or self.stack:
                raise _LineError(st.col, "'kind' belongs in the header, before the first action")
            if t is None or t.kind != "word" or t.text not in ("experiment", "screening"):
                raise _LineError(t.col if t else cur.end_col(), "kind must be experiment or screening")
            cur.done("the kind")
            self.script.meta["type"] = t.text
            st.kind = "_header"
        elif kw in ("zero", "ramp", "hold", "move", "rotate", "focus", "loop"):
            _keyvals(cur, PROTOCOL_KEYS[kw], st, kw)
            if kw == "rotate" and st.args["from"].value == st.args["to"].value:
                raise _LineError(st.args["to"].col, "'rotate' needs from= and to= to differ (use 'hold' to stay)")
        elif kw == "record":
            if cur.is_word("on") or cur.is_word("off"):
                st.form = cur.next().text
                cur.done(f"'record {st.form}'")
            else:
                st.form = "timed"
                _keyvals(cur, PROTOCOL_KEYS["record"], st, "record")
        elif kw == "light":
            if cur.is_word("off"):
                cur.next()
                st.form = "off"
                cur.done("'light off'")
            else:
                st.form = "seq"
                _keyvals(cur, PROTOCOL_KEYS["light"], st, "light")
        elif kw == "mark":
            t = cur.next()
            if t is None or t.kind != "str":
                raise _LineError(t.col if t else cur.end_col(), 'mark needs a quoted text: mark "text"')
            cur.done("the mark text")
            st.pos.append(Arg(t.value, cur.line, t.col, t.text))
        elif kw == "wait":
            if cur.is_word("until"):
                cur.next()
                st.form = "until"
                st.expr = parse_expr(cur)
                _keyvals_partial(cur, st, {"timeout": Key("num", "s", 0.0, 86400.0, True, True)}, "wait until")
                if cur.is_word("then"):
                    cur.next()
                    t = cur.next()
                    if t is None or t.kind != "word" or t.text not in ("stop", "continue"):
                        raise _LineError(t.col if t else cur.end_col(), "'then' must be followed by stop or continue")
                    st.pos.append(Arg(t.text, cur.line, t.col, t.text))
                cur.done("'wait until'")
                if "timeout" not in st.args:
                    raise _LineError(cur.end_col(), "'wait until' needs timeout= (s)")
            else:
                st.form = "time"
                _keyvals(cur, PROTOCOL_KEYS["wait"], st, "wait")
        elif kw == "if":
            st.expr = parse_expr(cur)
            cur.done("the condition")
        elif kw == "on":
            st.expr = parse_expr(cur)
            cur.expect_word("do", "'do' after the condition: on <expr> do")
            cur.done("'do'")
        elif kw == "stop":
            cur.done("'stop'")
        elif kw == "repeat":
            t = cur.next()
            if t is None or t.kind != "num" or "." in t.text or not 1 <= t.value <= 10000:
                raise _LineError(t.col if t else cur.end_col(), "'repeat' needs a whole number 1-10000: repeat 3")
            cur.done("'repeat n'")
            if self.stack:
                raise _LineError(st.col, "'repeat n' belongs at the end of the file, outside every block")
            st.args["n"] = Arg(int(t.value), cur.line, t.col, t.text)
        elif kw == "rule":
            if self.script.meta.get("type") != "screening":
                raise _LineError(st.col, "'rule' is allowed only in a protocol of kind screening")
            if self.stack:
                raise _LineError(st.col, "'rule' belongs at the top level, not inside a block")
            cur.within = True
            st.expr = parse_expr(cur)
            cur.done("the rule")
            if st.expr.op != "cmp":
                raise _LineError(st.expr.col, "a rule is a comparison: metric op threshold, e.g. rule angle_deg <= 20")
        else:
            known = ("zero ramp hold move rotate focus record light mark wait loop if else on stop end repeat rule "
                     "kind; 'end protocol' last")
            raise _LineError(st.col, f"unknown statement '{kw}' (protocol statements: {known})")

    def _sequence(self, cur, st):
        kw, m = st.kind, self.script.meta
        cur.next()
        if kw == "lights":
            if "lights" in m:
                raise _LineError(st.col, "'lights' is given twice")
            while not cur.at_end():
                t = cur.next()
                if t.kind != "num" or "." in t.text:
                    raise _LineError(t.col, f"a light is its wavelength in nm (a whole number), not {t.text!r}")
                if t.text in [a.text for a in st.pos]:
                    raise _LineError(t.col, f"light {t.text} is listed twice")
                st.pos.append(Arg(int(t.value), cur.line, t.col, t.text))
            if not st.pos:
                raise _LineError(cur.end_col(), "'lights' needs at least one wavelength: lights 532 637")
            m["lights"] = [a.text for a in st.pos]
            st.kind = "_header"
        elif kw == "ratio":
            _keyvals(cur, {"n": Key("int", "", 1, 65536)}, st, "ratio")
            if "ratio" in m:
                raise _LineError(st.col, "'ratio' is given twice")
            m["ratio"] = st.args["n"].value
            st.kind = "_header"
        elif kw in ("header", "body", "footer"):
            if self.stack:
                raise _LineError(st.col, f"'{kw}' cannot be inside another block")
            if any(s.kind == kw for s in self.script.body):
                raise _LineError(st.col, f"'{kw}' is given twice")
            if "lights" not in m:
                raise _LineError(st.col, "'lights' must come before the frames")
            _keyvals(cur, {"repeat": Key("int", "", 1, 10**7, required=False)} if kw == "body" else {}, st, kw)
        elif kw == "frame":
            if not self.stack:
                raise _LineError(st.col, "'frame' belongs inside header, body or footer")
            lights = m.get("lights", [])
            specs = {lt: Key("onoff") for lt in lights} | {"count": Key("int", "", 1, 10**7, required=False)}
            _keyvals(cur, specs, st, "frame", key_kinds=("word", "num"))
        else:
            raise _LineError(st.col, f"unknown statement '{kw}' (sequence statements: lights ratio header body footer "
                                     "frame end)")

    def _recipe(self, cur, st):
        kw = st.kind
        cur.next()
        if kw == "signals":
            while not cur.at_end():
                t = cur.next()
                if t.kind != "word" or t.text in _RESERVED:
                    raise _LineError(t.col, f"a signal is a name, not {t.text!r}")
                st.pos.append(Arg(t.text, cur.line, t.col, t.text))
            if not st.pos:
                raise _LineError(cur.end_col(), "'signals' needs at least one name")
        elif kw == "observable":
            t = cur.next()
            if t is None or t.kind != "word":
                raise _LineError(t.col if t else cur.end_col(), "observable needs a name: observable E = fret(...)")
            st.pos.append(Arg(t.text, cur.line, t.col, t.text))
            if cur.peek() is None or cur.peek().kind != "eq":
                raise _LineError(cur.col(), "expected '=' after the observable name")
            cur.next()
            st.expr = parse_expr(cur)
            cur.done("the observable")
        elif kw == "select":
            st.expr = parse_expr(cur)
            cur.done("the selection")
        elif kw == "event":
            t = cur.next()
            if t is None or t.kind != "word":
                raise _LineError(t.col if t else cur.end_col(), "event needs a name: event cleavage when ...")
            st.pos.append(Arg(t.text, cur.line, t.col, t.text))
            cur.expect_word("when", "'when' after the event name")
            st.expr = parse_expr(cur)
            cur.done("the event condition")
        elif kw == "export":
            t = cur.next()
            if t is None or t.kind != "word" or t.text not in ("events", "traces"):
                raise _LineError(t.col if t else cur.end_col(), "export events to <target> | export traces <names> "
                                                                 "to <target>")
            st.form = t.text
            while not cur.is_word("to"):
                x = cur.next()
                if x is None:
                    raise _LineError(cur.end_col(), "expected 'to <target>'")
                if st.form == "events" or x.kind != "word":
                    raise _LineError(x.col, f"unexpected {x.text!r} in export")
                st.pos.append(Arg(x.text, cur.line, x.col, x.text))
            cur.next()
            tgt = cur.next()
            if tgt is None or tgt.kind != "word" or tgt.text not in ("matlab", "hdf5", "csv"):
                raise _LineError(tgt.col if tgt else cur.end_col(), "export target must be matlab, hdf5 or csv")
            st.args["to"] = Arg(tgt.text, cur.line, tgt.col, tgt.text)
            cur.done("the export")
        else:
            raise _LineError(st.col, f"unknown statement '{kw}' (recipe statements: signals observable select event "
                                     "export)")

    # -- whole-file checks ------------------------------------------------------------------------------------------
    def finish(self):
        s = self.script
        tail = s.meta.pop("_tail", None)
        end = s.meta.pop("_end", None)
        if s.kind == "protocol":
            if s.meta["type"] is None:
                s.meta["type"] = "experiment"
            if tail is not None:                    # `repeat n` = the whole list in `loop n=`
                loop = Stmt("loop", tail.line, tail.col, tail.text, args={"n": tail.args["n"]}, body=s.body)
                s.body = [loop]
            if s.rules and s.meta["type"] != "screening":
                self.err(s.rules[0].line, s.rules[0].col, "rules need kind screening")
            if not s.body:
                self.err(1, 1, "the protocol has no action")
            if end is not None:                     # after the `repeat n` wrap: runs once, as the last statement
                s.body.append(end)
        elif s.kind == "sequence":
            if "lights" not in s.meta:
                self.err(1, 1, "the sequence needs a 'lights' line")
            if "ratio" not in s.meta:
                self.err(1, 1, "the sequence needs a 'ratio n=' line (JAI frames per EMCCD frame)")
            if not any(b.kind == "body" for b in s.body):
                self.err(1, 1, "the sequence needs a 'body' block")
            for b in s.body:                # every frame sets every listed light: required keys of 'frame'
                if not b.body:
                    self.err(b.line, b.col, f"'{b.kind}' has no frame")
        elif s.kind == "recipe":
            self._recipe_names()

    def _recipe_names(self):
        s = self.script
        known = set(LIVE_NAMES)
        for st in s.body:
            if st.kind == "signals":
                known.update(a.value for a in st.pos)
                continue
            if st.expr is not None:
                for what, name, col in st.expr.names():
                    if what == "call" and name not in LIBRARY:
                        self.err(st.line, col, f"unknown function '{name}' (library: {', '.join(LIBRARY)})")
                    elif what == "name" and name not in known:
                        self.err(st.line, col, f"unknown name '{name}': not a signal, an observable or a live "
                                               "quantity defined above")
            if st.kind == "observable":
                known.add(st.pos[0].value)
            if st.kind == "export":
                for a in st.pos:
                    if a.value not in known:
                        self.err(st.line, a.col, f"export of unknown '{a.value}'")


def _keyvals_partial(cur, st, specs, what):
    """key=value pairs until a word that is not followed by '=' (the `then stop` of `wait until`)."""
    while cur.peek() is not None and cur.peek().kind == "word" and cur.peek(1) is not None and cur.peek(1).kind == "eq":
        k = cur.next()
        cur.next()
        spec = specs.get(k.text)
        if spec is None:
            raise _LineError(k.col, f"'{what}' has no key '{k.text}' (keys: {', '.join(specs)})")
        if k.text in st.args:
            raise _LineError(k.col, f"'{k.text}' is given twice")
        try:
            st.args[k.text] = _value(cur.next(), k.text, spec, cur.line)
        except _LineError as e:
            raise _LineError(e.col or cur.end_col(), e.message) from None


def parse(text, file="<text>"):
    """Parse a script (protocol, sequence or recipe) and return its `Script`; raise ScriptError listing every error.
    Nothing is executed. Example: `parse(open("x.mtprot").read(), "x.mtprot")`."""
    text = text.removeprefix("﻿")
    p = _Parser(text, file)
    script = p.run()
    if p.diags:
        raise ScriptError(sorted(p.diags, key=lambda d: (d.line, d.col)), p.warnings)
    script.sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    script.warnings = list(p.warnings)
    return script
