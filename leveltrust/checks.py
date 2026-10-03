"""Authenticity checks, grouped by evidence layer.

L1 container/file-system  L2 text layer  L3 arithmetic redundancy
L4 procedure & physics    L5 cross-file  L6 statistics (informational)
Every finding carries an `innocent` explanation: a flag is a lead, not a verdict.
"""
import collections
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta

from .parse import Record, stations

HIGH, MED, LOW, INFO = "HIGH", "MED", "LOW", "INFO"
ORDER = {HIGH: 0, MED: 1, LOW: 2, INFO: 3}


@dataclass
class Finding:
    file: str
    layer: str
    level: str
    title: str
    detail: str
    innocent: str = ""


def _hm(td):
    m = round(td.total_seconds() / 60)
    return f"{m // 60}h{m % 60:02d}m"


def _mean(v):
    return sum(v) / len(v)


def _build(rec: Record):
    """Station table: one entry per closed BFFB station."""
    sts = []
    for readings, zline in stations(rec):
        rb = [r.val for r in readings if r.code == "Rb"]
        rf = [r.val for r in readings if r.code == "Rf"]
        if not rb or not rf:
            continue
        hb = [r.val2 for r in readings if r.code == "Rb"]
        hf = [r.val2 for r in readings if r.code == "Rf"]
        sts.append(dict(first=readings[0], last=readings[-1], zline=zline, rb=rb, rf=rf,
                        dh=_mean(rb) - _mean(rf), hdb=_mean(hb), hdf=_mean(hf), z=zline.z))
    return sts


# ------------------------------------------------------------ L1 container
def container_checks(rec: Record, zip_path=None, entry=None):
    out, name = [], os.path.basename(rec.path)
    hdr = rec.header.get("date")
    mtime = None
    if zip_path and entry:
        zf = zipfile.ZipFile(zip_path)
        zi = zf.getinfo(entry)
        mtime = datetime(*zi.date_time)
        if zf.testzip() is not None:
            out.append(Finding(name, "L1", HIGH, "ZIP 内部 CRC 校验失败", "压缩包有损坏或被改写过。"))
        if zi.extra:
            out.append(Finding(name, "L1", INFO, "ZIP 条目带扩展字段", f"extra={zi.extra[:32].hex()},可含精确时间,可交叉印证。"))
    elif os.path.exists(rec.path):
        mtime = datetime.fromtimestamp(os.stat(rec.path).st_mtime)
    if mtime and hdr:
        day, _t0, t1 = hdr
        end = datetime.strptime(f"{day} {t1}", "%Y-%m-%d %H:%M")
        d = (mtime - end).total_seconds() / 60
        if d < -2:
            out.append(Finding(name, "L1", MED, "文件最后保存时间早于表头声称的观测结束时间",
                               f"保存 {mtime:%H:%M:%S},表头结束 {t1},早 {-d:.0f} 分钟。",
                               "压缩包时间的时区与表头不同,或表头时间是后填的。"))
        elif d > 30:
            out.append(Finding(name, "L1", MED, "观测结束后被再次保存",
                               f"保存 {mtime:%H:%M:%S},晚于表头结束 {t1} 约 {d / 60:.1f} 小时。",
                               "仪器导出/拷贝/格式转换也会更新时间,需追问保存原因。"))
    return out


# ------------------------------------------------------------ L2 text layer
def text_checks(rec: Record):
    out, name = [], os.path.basename(rec.path)
    raw = rec.raw_bytes
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    cr = raw.count(b"\r") - crlf
    if (lf and crlf) or cr:
        out.append(Finding(name, "L2", MED, "换行符混用", f"CRLF={crlf} LF={lf} 孤立CR={cr}。",
                           "不同软件拼接过内容,是手工编辑的典型痕迹。"))
    if raw[:3] == b"\xef\xbb\xbf" or b"\t" in raw:
        out.append(Finding(name, "L2", LOW, "出现 BOM 或制表符", "仪器原始导出通常没有;文本编辑器保存时常加入。"))
    if rec.unparsed:
        out.append(Finding(name, "L2", MED, f"{len(rec.unparsed)} 行无法按仪器格式解析",
                           "; ".join(f"L{n}" for n, _ in rec.unparsed[:8])))
    sig = collections.defaultdict(collections.Counter)
    for r in rec.recs:
        sig[r.kind][r.field_lens] += 1
    odd = [r.line_no for r in rec.recs if r.field_lens != sig[r.kind].most_common(1)[0][0]]
    if odd:
        out.append(Finding(name, "L2", HIGH, "有记录的列宽与同类记录不一致", f"行号 {odd[:10]}。",
                           "手工改数字、少/多打空格会破坏仪器的固定列宽。"))
    else:
        out.append(Finding(name, "L2", INFO, "文本层未见手工编辑痕迹",
                           "全部记录列宽一致、换行符统一、编码单一。这只能排除'用记事本改了几个数字',"
                           "排除不了程序生成、或改后重新导出。"))
    return out


# ------------------------------------------------------------ L3 arithmetic redundancy
def arithmetic_checks(rec: Record, tol=0.000021):
    out, name = [], os.path.basename(rec.path)
    sts = _build(rec)
    z_prev = next((r.z for r in rec.recs if r.kind == "KD1" and r.z is not None and not r.code), 0.0)
    bad = []
    for i, s in enumerate(sts, 1):
        exp = z_prev + s["dh"]
        if abs(exp - s["z"]) > tol:
            bad.append((i, s["zline"].line_no, round(exp, 5), s["z"]))
        z_prev = s["z"]
    if bad:
        out.append(Finding(name, "L3", HIGH, "测站高程与读数不自洽",
                           "; ".join(f"站{i}(行{ln}) 重算{e} 记录{z}" for i, ln, e, z in bad[:6]),
                           "改了读数没同步改 Z,或改了 Z 没改读数;仪器现场写出的数据不会这样。"))
    else:
        out.append(Finding(name, "L3", INFO, f"{len(sts)} 个测站的高程全部与读数重算一致",
                           "冗余字段互相吻合。若有人同时改读数与 Z 并按公式重算,这一项发现不了。"))
    # intermediate sights: Z = Hi - Rz, Hi = Z_fore + mean(Rf)
    by_zline = {id(s["zline"]): s for s in sts}
    hi, badi, n = None, [], 0
    for r in rec.recs:
        if id(r) in by_zline:
            s = by_zline[id(r)]
            hi = s["z"] + _mean(s["rf"])
        if r.kind == "KD1" and r.code == "Rz" and hi is not None and r.z is not None:
            n += 1
            if abs((hi - r.val) - r.z) > tol:
                badi.append((r.line_no, round(hi - r.val, 5), r.z))
    if badi:
        dmm = [(z - e) * 1000 for _, e, z in badi]
        whole = len(dmm) >= 3 and all(abs(d - round(d)) < 0.03 for d in dmm)
        extra = (f"偏差分别为 {', '.join(f'{d:+.2f}' for d in dmm)} mm,全部是整毫米:"
                 "仪器舍入误差只会是 ≤0.02 mm,整毫米偏差是手工改动 mm 位的典型特征(无法判断改的是读数还是 Z)。") if whole else ""
        out.append(Finding(name, "L3", HIGH, f"{len(badi)} 个中间视点的高程与读数不自洽(Z ≠ 仪器高 − Rz)",
                           "; ".join(f"行{ln} 重算{e} 记录{z}" for ln, e, z in badi[:8]) + (" 。" + extra if extra else ""),
                           "仪器现场写出的数据没有这种情况;唯一正常解释是后处理软件改过,需看改动记录。"))
    elif n:
        out.append(Finding(name, "L3", INFO, f"{n} 个中间视点高程重算一致", ""))
    d2 = [r for r in rec.recs if r.kind == "KD2"]
    if d2 and sts:
        db, df = sum(s["hdb"] for s in sts), sum(s["hdf"] for s in sts)
        if abs(db - d2[0].val) > 0.02 or abs(df - d2[0].val2) > 0.02:
            out.append(Finding(name, "L3", HIGH, "总视距与逐站视距之和不符",
                               f"汇总 Db={d2[0].val} Df={d2[0].val2},逐站重算 {db:.2f}/{df:.2f}。",
                               "删过测站记录会留下这种差。"))
    adrs = [r.adr for r in rec.recs]
    gaps = [(a + 1, b - 1) for a, b in zip(adrs, adrs[1:]) if b != a + 1]
    if gaps:
        miss = sum(b - a + 1 for a, b in gaps)
        span = adrs[-1] - adrs[0] + 1
        out.append(Finding(name, "L3", MED, f"记录编号断档,缺 {miss} 条({miss / span:.0%})", f"缺失区间 {gaps}。",
                           "仪器上手工删除超限/重测数据可造成;规范通常要求保留并注明。需对照仪器内存。"))
    ts = [r.t for r in rec.recs if r.t is not None]
    if any(b < a for a, b in zip(ts, ts[1:])):
        out.append(Finding(name, "L3", HIGH, "记录时间倒流", "记录顺序与时间戳矛盾。"))
    return out


# ------------------------------------------------------------ L4 procedure & physics
def physics_checks(rec: Record, min_move_s=30, zero_dh=0.0005, max_sight_diff=5.0, max_cum_diff=10.0, max_sight=50.0):
    out, name = [], os.path.basename(rec.path)
    sts = _build(rec)
    zero, fast = [], []
    for i, s in enumerate(sts):
        same = abs(s["dh"]) <= zero_dh and abs(s["hdb"] - s["hdf"]) <= 0.02
        gap = (s["first"].t - sts[i - 1]["last"].t).total_seconds() if i else None
        if same:
            zero.append(i + 1)
        if gap is not None and 0 <= gap < min_move_s:
            fast.append((i + 1, gap, same))
    if fast:
        out.append(Finding(name, "L4", HIGH, "站间时间不足以搬站",
                           "; ".join(f"第{i}站距上一站仅{g:.0f}秒" + ("(且高差≈0、前后视距相同)" if sm else "") for i, g, sm in fast),
                           "搬仪器+立尺+整平至少需几十秒到数分钟。若是对同一把尺的重复测量,不应记成不同测站。"))
    if zero:
        out.append(Finding(name, "L4", MED, f"{len(zero)} 个测站前后视读数与视距几乎相同(高差≈0)",
                           "第" + "、".join(map(str, zero)) + "站。读数差<0.5mm且视距差<2cm,前后视可能是同一尺位。",
                           "i 角检验/重复观测,但应单独标注,不应计入水准线测站。"))
    cum = worst = longest = 0.0
    for s in sts:
        d = s["hdb"] - s["hdf"]
        cum += d
        worst = max(worst, abs(d))
        longest = max(longest, s["hdb"], s["hdf"])
    msg = f"单站视距差最大 {worst:.2f} m,累计视距差 {cum:+.2f} m,最长视距 {longest:.1f} m。"
    if worst > max_sight_diff or abs(cum) > max_cum_diff or longest > max_sight:
        out.append(Finding(name, "L4", MED, "视距指标超出设定限差",
                           msg + f"(阈值 站差{max_sight_diff}/累计{max_cum_diff}/视距{max_sight} m,可用参数调整,请对照项目规范)",
                           "监测项目可能采用较宽的限差;但要核实观测等级与此是否相符。"))
    else:
        out.append(Finding(name, "L4", INFO, "视距指标在设定限差内", msg))
    cl = [r for r in rec.recs if r.code == "Sh"]
    if cl and len(sts) >= 4:
        c = cl[-1].val
        if abs(c) < 0.0000051:
            out.append(Finding(name, "L4", LOW, "闭合差恰为 0.00000 m",
                               f"{len(sts)} 站闭合环,读数分辨率 0.01mm、典型闭合差约 0.1–0.3mm,恰为 0 的概率约 1%。",
                               "小概率事件,单独不足为据;与其它疑点叠加时才有分量。"))
        else:
            out.append(Finding(name, "L4", INFO, f"闭合差 {c * 1000:+.2f} mm", ""))
    return out


# ------------------------------------------------------------ L5 cross-file / header
def header_checks(recs):
    out, info = [], []
    for r in recs:
        h = r.header.get("date")
        ts = [x.t for x in r.recs if x.t is not None]
        if not h or not ts:
            continue
        _day, t0, t1 = h
        hs = timedelta(hours=int(t0[:2]), minutes=int(t0[3:]))
        he = timedelta(hours=int(t1[:2]), minutes=int(t1[3:]))
        info.append(dict(name=os.path.basename(r.path), serial=r.header.get("serial"), obs=r.header.get("observer"),
                         hs=hs, he=he, off_s=hs - ts[0], off_e=he - ts[-1], rec_dur=ts[-1] - ts[0]))
    for i in info:
        if abs((i["off_s"] - i["off_e"]).total_seconds()) > 300:
            out.append(Finding(i["name"], "L5", MED, "表头时段与仪器时间戳不吻合",
                               f"表头声称 {(i['he'] - i['hs']).seconds // 60} 分钟,仪器记录实际跨度 {i['rec_dur'].seconds // 60} 分钟;"
                               f"(表头−仪器时间)起点 {_hm(i['off_s'])}、终点 {_hm(i['off_e'])},应为同一个常数。",
                               "表头是手填或被后期改过;仪器时区也可能没设。"))
    by_serial = collections.defaultdict(list)
    for i in info:
        by_serial[i["serial"]].append(i)
    for ser, grp in by_serial.items():
        if len({round(x["off_s"].total_seconds() / 3600) for x in grp}) > 1:
            out.append(Finding("、".join(x["name"] for x in grp), "L5", HIGH, f"同一台仪器({ser})的时钟偏差在不同文件间不一致",
                               "各文件(表头−仪器时间): " + ", ".join(f"{x['name']}:{_hm(x['off_s'])}" for x in grp)
                               + "。同一天内仪器时钟不会跳变数小时。",
                               "不同文件在时区设置不同的电脑上转换导出,也能造成,需查导出记录。"))
        g = sorted(grp, key=lambda x: x["hs"])
        for a, b in zip(g, g[1:]):
            if b["hs"] < a["he"]:
                out.append(Finding(f"{a['name']}、{b['name']}", "L5", HIGH, f"同一台仪器({ser})的观测时段重叠",
                                   f"{a['name']}: {a['hs']}–{a['he']};{b['name']}: {b['hs']}–{b['he']}。一台仪器不能同时测两条线。"))
    by_obs = collections.defaultdict(list)
    for i in info:
        by_obs[i["obs"]].append(i)
    for obs, grp in by_obs.items():
        g = sorted(grp, key=lambda x: x["hs"])
        ov = [f"{a['name']}、{b['name']}" for a, b in zip(g, g[1:]) if b["hs"] < a["he"]]
        if ov:
            out.append(Finding("; ".join(ov), "L5", MED, f"同一观测者({obs})的表头时段重叠", "需要多名助手同时作业才可能。",
                               "多人多仪器同时观测、仅署名观测者一人。"))
    return out


# ------------------------------------------------------------ L6 digit statistics
def digit_checks(rec: Record):
    name = os.path.basename(rec.path)
    d = collections.Counter(("%.5f" % r.val)[-1] for r in rec.recs if r.code in ("Rb", "Rf", "Rz"))
    n = sum(d.values())
    if n < 100:
        return [Finding(name, "L6", INFO, f"读数末位检验:样本 {n} 个,太少,不下结论", "")]
    chi = sum((d.get(str(k), 0) - n / 10) ** 2 / (n / 10) for k in range(10))
    return [Finding(name, "L6", LOW if chi > 21.7 else INFO, f"读数末位均匀性 χ²={chi:.1f}(df=9,p<0.01 临界 21.7)", "")]


def run_all(recs, zip_path=None, entries=None, **kw):
    out = []
    for r in recs:
        entry = entries.get(r.path) if entries else None
        out += container_checks(r, zip_path, entry)
        out += text_checks(r)
        out += arithmetic_checks(r)
        out += physics_checks(r, **kw)
        out += digit_checks(r)
    out += header_checks(recs)
    out.sort(key=lambda f: (ORDER[f.level], f.file))
    return out
