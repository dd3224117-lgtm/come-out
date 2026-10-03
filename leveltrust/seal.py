"""Baseline sealing: the only check that can PROVE a file changed.

`seal` records SHA-256 of each file plus a hash of every line (so `verify` can name the
changed lines), optionally authenticated with HMAC-SHA256 so the manifest itself can't be
quietly regenerated. Commit/e-mail/timestamp the manifest right after export from the
instrument -- the later the baseline is taken, the less it proves.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone


def _lines(raw: bytes):
    return [hashlib.sha256(l).hexdigest()[:16] for l in raw.split(b"\n")]


def seal(paths, key=None):
    files = {}
    for p in paths:
        raw = open(p, "rb").read()
        files[os.path.basename(p)] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), lines=_lines(raw))
    body = dict(version=1, sealed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), files=files)
    if key:
        body["hmac"] = hmac.new(key.encode(), json.dumps(files, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    return body


def verify(manifest, paths, key=None):
    """Return list of human-readable problems; empty list means every file matches the baseline."""
    problems = []
    if "hmac" in manifest:
        if not key:
            problems.append("清单带 HMAC 但未提供 --key,无法确认清单本身未被重写。")
        else:
            want = hmac.new(key.encode(), json.dumps(manifest["files"], sort_keys=True).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(want, manifest["hmac"]):
                problems.append("清单 HMAC 不匹配:清单被改过,或密钥不对。")
    seen = set()
    for p in paths:
        n = os.path.basename(p)
        seen.add(n)
        base = manifest["files"].get(n)
        if base is None:
            problems.append(f"{n}: 不在基线清单中(新增文件)。")
            continue
        raw = open(p, "rb").read()
        if hashlib.sha256(raw).hexdigest() == base["sha256"]:
            continue
        cur, old = _lines(raw), base["lines"]
        diff = [i + 1 for i in range(max(len(cur), len(old))) if (cur[i] if i < len(cur) else None) != (old[i] if i < len(old) else None)]
        problems.append(f"{n}: 与基线不符,大小 {base['size']}→{len(raw)},变动行 {diff[:20]}{'…' if len(diff) > 20 else ''}。")
    for n in manifest["files"]:
        if n not in seen:
            problems.append(f"{n}: 基线中有、现场缺失。")
    return problems
