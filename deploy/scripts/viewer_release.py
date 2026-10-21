# -*- coding: utf-8 -*-
"""Build and verify the server-only 3D viewer release."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "release-manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_file(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build(dst: Path):
    if dst.exists() and any(dst.iterdir()):
        raise SystemExit("目标目录已存在且非空：%s" % dst)
    dst.mkdir(parents=True, exist_ok=True)

    files = [
        "workbench/server.py",
        "workbench/ui/login.html",
        "workbench/ui/login.css",
        "workbench/ui/login.js",
        "workbench/ui/viewer.html",
        "workbench/ui/space.html",
        "workbench/ui/space.css",
        "workbench/ui/space.js",
        "workbench/ui/building-status.json",
        "workbench/ui/assets/logo.svg",
        "workbench/ui/assets/campus-hero.webp",
        "demo/building.html",
        "demo/index.html",
        "packs/index.json",
        "deploy/systemd/cdut3d.service",
        "deploy/nginx/cdut3d.conf",
        "deploy/scripts/healthcheck.py",
        "deploy/scripts/viewer_release.py",
        "README.md",
        "CHANGELOG.md",
    ]
    for rel in files:
        src = ROOT / rel
        if not src.is_file():
            raise SystemExit("缺少发布件：%s" % src)
        _copy_file(src, dst / rel)

    for tree in ("demo/vendor", "packs/cdut-main"):
        src = ROOT / tree
        if not src.is_dir():
            raise SystemExit("缺少发布目录：%s" % src)
        shutil.copytree(src, dst / tree, copy_function=shutil.copy2)

    rows = []
    for p in sorted(dst.rglob("*")):
        if p.is_file() and p.name != MANIFEST:
            rows.append({
                "path": p.relative_to(dst).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            })
    manifest = {
        "schema": "cdut3d-viewer-release/1",
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "viewer",
        "files": rows,
        "total_files": len(rows),
        "total_bytes": sum(x["bytes"] for x in rows),
    }
    (dst / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("total_files", "total_bytes")}, ensure_ascii=False))


def verify(dst: Path):
    manifest = json.loads((dst / MANIFEST).read_text(encoding="utf-8"))
    bad = []
    for row in manifest.get("files", []):
        p = dst / row["path"]
        if not p.is_file():
            bad.append((row["path"], "missing"))
            continue
        if p.stat().st_size != row["bytes"]:
            bad.append((row["path"], "size"))
            continue
        if sha256(p) != row["sha256"]:
            bad.append((row["path"], "sha256"))
    if bad:
        print(json.dumps({"ok": False, "bad": bad[:30]}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "files": len(manifest.get("files", []))}, ensure_ascii=False))
    return 0


def archive(src: Path, out: Path):
    with tarfile.open(out, "w:gz", compresslevel=1) as tf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                tf.add(p, arcname=p.relative_to(src).as_posix())
    print(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("dest")
    v = sub.add_parser("verify")
    v.add_argument("dest")
    a = sub.add_parser("archive")
    a.add_argument("src")
    a.add_argument("out")
    ns = ap.parse_args(argv)
    if ns.cmd == "build":
        build(Path(ns.dest).resolve())
        return 0
    if ns.cmd == "verify":
        return verify(Path(ns.dest).resolve())
    archive(Path(ns.src).resolve(), Path(ns.out).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
