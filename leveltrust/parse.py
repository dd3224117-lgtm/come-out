"""Parse DNA03 'For M5' raw-record files (GBK text, pipe-delimited fixed-width fields)."""
import re
from dataclasses import dataclass, field
from datetime import timedelta

ENCODINGS = ("gbk", "utf-8")


@dataclass
class Rec:
    line_no: int
    adr: int
    kind: str          # TO / KD1 / KD2
    label: str         # point name, or TO text
    t: timedelta | None
    code: str          # reading type: Rb Rf Rz Sh Db ...
    val: float | None  # reading in m
    code2: str
    val2: float | None  # HD / dz / Df
    z: float | None
    raw: str = ""
    field_lens: tuple = ()


@dataclass
class Record:
    path: str
    raw_bytes: bytes
    text: str
    encoding: str
    header: dict = field(default_factory=dict)
    recs: list = field(default_factory=list)
    unparsed: list = field(default_factory=list)


_TIME = re.compile(r"(\d\d):(\d\d):(\d\d)")
_NUM = re.compile(r"^\s*([A-Za-z]+)\s+(-?\d+\.\d+)\s*m\s*$")
_ZNUM = re.compile(r"^\s*Z\s+(-?\d+\.\d+)\s*m\s*$")


def decode(raw: bytes):
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _hdr(text):
    h = {}
    for ln in text.splitlines():
        if ln.startswith("For M5"):
            break
        for key, pat in (
            ("project", r"工程名称:\s*(.*)"),
            ("instrument", r"仪器型号:\s*(\S+)"),
            ("serial", r"出厂编号:\s*(\S+)"),
            ("date", r"观测日期:\s*(\d{4}-\d\d-\d\d)\s+(\d\d:\d\d)\s*-\s*(\d\d:\d\d)"),
            ("observer", r"观测者:\s*(\S+)"),
            ("checker", r"检查者:\s*(\S+)"),
            ("temp", r"温度:\s*(\d+)"),
        ):
            m = re.search(pat, ln)
            if m:
                h[key] = m.groups() if key == "date" else m.group(1)
        if "观测者" in ln:
            m = re.search(r"检查者:\s*(\S+)", ln)
            if m:
                h["checker"] = m.group(1)
    return h


def parse_file(path: str) -> Record:
    raw = open(path, "rb").read()
    text, enc = decode(raw)
    rec = Record(path=path, raw_bytes=raw, text=text, encoding=enc, header=_hdr(text))
    for i, ln in enumerate(text.splitlines(), 1):
        if not ln.startswith("For M5"):
            continue
        p = ln.split("|")
        try:
            adr = int(re.search(r"Adr\s+(\d+)", p[1]).group(1))
            c1 = p[2]
            kind = c1.split()[0]
            m = _TIME.search(c1)
            t = timedelta(hours=int(m[1]), minutes=int(m[2]), seconds=int(m[3])) if m else None
            toks = c1.split()
            label = " ".join(toks[1:]) if kind == "TO" else (toks[1] if len(toks) > 1 else "")
            code = code2 = ""
            val = val2 = z = None
            a = _NUM.match(p[3])
            if a:
                code, val = a[1], float(a[2])
            b = _NUM.match(p[4])
            if b:
                code2, val2 = b[1], float(b[2])
            zz = _ZNUM.match(p[5])
            if zz:
                z = float(zz[1])
            rec.recs.append(Rec(i, adr, kind, label, t, code, val, code2, val2, z, ln, tuple(len(x) for x in p)))
        except Exception:
            rec.unparsed.append((i, ln))
    return rec


def stations(rec: Record):
    """Group Rb/Rf readings into stations: a station closes at the Z-only line after its readings."""
    out, cur = [], []
    for r in rec.recs:
        if r.kind == "KD1" and r.code in ("Rb", "Rf"):
            cur.append(r)
        elif r.kind == "KD1" and r.z is not None and not r.code and cur:
            out.append((cur, r))
            cur = []
    return out
