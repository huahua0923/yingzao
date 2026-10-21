# -*- coding: utf-8 -*-
"""Conservative cleanup for proven-generatable artifacts.

Default mode is dry-run.  Only byte-code caches and one orphaned snapshot
directory are in scope.  Geometry, packs, rebuild inputs and archives are never
deleted here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORPHANS = (ROOT / "项目cdut3drebuild_scratchgatebase",)
CACHE_NAMES = {"__pycache__", ".pytest_cache"}


def _inside(path: Path) -> bool:
    rp = path.resolve()
    root = ROOT.resolve()
    return rp != root and root in rp.parents


def _on_remove_error(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*") if p.is_file())


def find_cache_dirs() -> list[Path]:
    found = []
    for p in ROOT.rglob("*"):
        if not p.is_dir() or p.name not in CACHE_NAMES:
            continue
        if ".git" in p.parts or not _inside(p):
            continue
        found.append(p)
    return sorted(set(found))


def _archive_orphan(path: Path, stamp: str) -> tuple[Path, list[dict]]:
    out_dir = ROOT / "_archive" / ("cleanup-" + stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / (path.name + ".zip")
    rows = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in _tree_files(path):
            rel = f.relative_to(ROOT).as_posix()
            rows.append({"path": rel, "bytes": f.stat().st_size, "sha256": _sha256(f)})
            z.write(f, rel)
    with zipfile.ZipFile(zip_path) as z:
        if z.testzip() is not None:
            raise RuntimeError("归档校验失败：%s" % zip_path)
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {"schema": "cdut3d-cleanup/1", "archive": zip_path.name, "files": rows},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return zip_path, rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    cache_dirs = find_cache_dirs()
    cache_files = sum(len(_tree_files(p)) for p in cache_dirs)
    cache_bytes = sum(f.stat().st_size for p in cache_dirs for f in _tree_files(p))
    orphan_rows = []
    orphan_bytes = 0
    for p in ORPHANS:
        if p.is_dir():
            fs = _tree_files(p)
            orphan_bytes += sum(f.stat().st_size for f in fs)
            orphan_rows.append({"path": p.name, "files": len(fs), "bytes": sum(f.stat().st_size for f in fs)})

    print("模式：%s" % ("APPLY" if args.apply else "DRY-RUN"))
    print("字节码缓存：%d 目录 / %d 文件 / %d bytes" % (len(cache_dirs), cache_files, cache_bytes))
    for row in orphan_rows:
        print("孤儿快照：%s / %d 文件 / %d bytes" % (row["path"], row["files"], row["bytes"]))

    if not args.apply:
        return 0

    archive = None
    for p in ORPHANS:
        if p.is_dir():
            if not _inside(p):
                print("拒绝：路径越界 %s" % p, file=sys.stderr)
                return 2
            archive, rows = _archive_orphan(p, stamp)
            shutil.rmtree(p, onerror=_on_remove_error)
            print("已归档并删除孤儿快照：%s" % p)
            print("  归档：%s（%d 文件）" % (archive, len(rows)))

    for p in cache_dirs:
        if not _inside(p):
            print("拒绝：路径越界 %s" % p, file=sys.stderr)
            return 2
        shutil.rmtree(p, onerror=_on_remove_error)

    record = {
        "schema": "cdut3d-cleanup/1",
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "cache_dirs_removed": len(cache_dirs),
        "cache_files_removed": cache_files,
        "cache_bytes_removed": cache_bytes,
        "orphan_archive": str(archive) if archive else None,
        "orphan_bytes": orphan_bytes,
    }
    out = ROOT / "_scratch" / ("cleanup-%s.json" % stamp)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print("清理记录：%s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
