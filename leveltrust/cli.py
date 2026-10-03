import argparse
import glob
import json
import os
import sys
import tempfile
import zipfile

from . import checks, parse, report, seal as sealmod


def _collect(inputs):
    """Accept .DAT files, directories, or a .zip; return (paths, zip_path, entries)."""
    paths, zip_path, entries = [], None, {}
    for inp in inputs:
        if inp.lower().endswith(".zip"):
            zip_path = inp
            tmp = tempfile.mkdtemp(prefix="leveltrust_")
            zf = zipfile.ZipFile(inp)
            for zi in zf.infolist():
                if zi.filename.lower().endswith(".dat"):
                    out = zf.extract(zi, tmp)
                    paths.append(out)
                    entries[out] = zi.filename
        elif os.path.isdir(inp):
            paths += sorted(glob.glob(os.path.join(inp, "*.DAT")) + glob.glob(os.path.join(inp, "*.dat")))
        else:
            paths.append(inp)
    return sorted(paths), zip_path, entries


def main(argv=None):
    ap = argparse.ArgumentParser(prog="leveltrust", description="DNA03 水准原始记录真实性筛查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("check", help="筛查")
    a.add_argument("inputs", nargs="+")
    a.add_argument("--json", action="store_true")
    a.add_argument("--max-sight-diff", type=float, default=5.0)
    a.add_argument("--max-cum-diff", type=float, default=10.0)
    a.add_argument("--max-sight", type=float, default=50.0)
    s = sub.add_parser("seal", help="生成基线清单(原始导出后立刻做)")
    s.add_argument("inputs", nargs="+")
    s.add_argument("-o", "--out", default="leveltrust.manifest.json")
    s.add_argument("--key")
    v = sub.add_parser("verify", help="与基线比对,指出变动行")
    v.add_argument("manifest")
    v.add_argument("inputs", nargs="+")
    v.add_argument("--key")
    ns = ap.parse_args(argv)

    paths, zip_path, entries = _collect(ns.inputs)
    if ns.cmd == "check":
        recs = [parse.parse_file(p) for p in paths]
        fs = checks.run_all(recs, zip_path, entries, max_sight_diff=ns.max_sight_diff,
                            max_cum_diff=ns.max_cum_diff, max_sight=ns.max_sight)
        print(report.to_json(fs) if ns.json else report.to_markdown(fs, [os.path.basename(p) for p in paths]))
        return 2 if any(f.level == checks.HIGH for f in fs) else 0
    if ns.cmd == "seal":
        json.dump(sealmod.seal(paths, ns.key), open(ns.out, "w"), ensure_ascii=False, indent=1)
        print(f"已封存 {len(paths)} 个文件 -> {ns.out}")
        return 0
    problems = sealmod.verify(json.load(open(ns.manifest)), paths, ns.key)
    print("\n".join(problems) if problems else "全部文件与基线一致。")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
