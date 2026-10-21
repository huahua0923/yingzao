# -*- coding: utf-8 -*-
"""Move root-level one-off operations artifacts into the cold archive.

This is intentionally not a delete tool.  Every moved file is recorded with
size and SHA-256 in a manifest under `_archive/ops-2026-10-21/`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "_archive" / "ops-2026-10-21"
FILES = (
    "_archive_bak_2026-10-20.zip",
    "_code_bak_2026-10-20.zip",
    "_chain_rerun_2026-10-20.log",
    "_gates_rerun_2026-10-20.log",
    "_state_before.json",
    "_state_after.json",
    "_g00.txt",
    "_evidence_baseline_before_regen_20261015.txt",
    "_cleanup_manifest_2026-10-20.json",
    "_cleanup_verified_2026-10-20.json",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inside(path: Path, base: Path) -> bool:
    p, b = path.resolve(), base.resolve()
    return p != b and b in p.parents


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    rows = []
    for name in FILES:
        src = ROOT / name
        if not src.is_file():
            continue
        dst = DEST / name
        row = {
            "name": name,
            "bytes": src.stat().st_size,
            "sha256": sha256(src),
            "from": str(src),
            "to": str(dst),
        }
        rows.append(row)
        print("%-48s %10d B" % (name, row["bytes"]))
    if not rows:
        print("没有可归档的根目录运行件")
        return 0
    if not args.apply:
        print("DRY-RUN：加 --apply 才会移动")
        return 0
    DEST.mkdir(parents=True, exist_ok=True)
    for row in rows:
        src, dst = Path(row["from"]), Path(row["to"])
        if not inside(dst, DEST):
            print("拒绝：目标越界 %s" % dst, file=sys.stderr)
            return 2
        if dst.exists():
            print("拒绝：目标已存在 %s" % dst, file=sys.stderr)
            return 2
        shutil.move(str(src), str(dst))
        if not dst.is_file() or dst.stat().st_size != row["bytes"]:
            print("拒绝：移动后大小不符 %s" % dst, file=sys.stderr)
            return 2
    manifest = {
        "schema": "cdut3d-ops-archive/1",
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "files": rows,
    }
    (DEST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8",
        newline="\n",
    )
    print("已归档 %d 件 -> %s" % (len(rows), DEST))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
