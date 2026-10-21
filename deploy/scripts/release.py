# -*- coding: utf-8 -*-
"""Build and verify a deployment release for cdut3d.

The script never uploads and never contains credentials.  It materialises one
versioned directory, writes a SHA-256 manifest, and can verify an existing
release before or after transfer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
SKIP_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "_archive",
    "_scratch",
    "_bad_packs",
    "node_modules",
    ".venv",
    "venv",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".blend1"}

DISPLAY_PATHS = [
    "workbench/server.py",
    "workbench/ui",
    "pipeline",
    "demo",
    "packs",
    "reality",
    "gates/_out",
    "rebuild/tools",
    "rebuild/构件库",
    "过程/_layers",
    "docs",
    "规范",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_NAMES for part in rel.parts):
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def iter_files(root: Path, selected: Iterable[str] | None = None) -> Iterable[Path]:
    """Yield regular files under root, respecting skip rules and selected paths."""
    root = root.resolve()
    paths = [root / x for x in selected] if selected else [root]
    seen: set[Path] = set()
    for start in paths:
        if not start.exists():
            raise FileNotFoundError(str(start))
        candidates = [start] if start.is_file() else start.rglob("*")
        for p in candidates:
            if not p.is_file() or _skip(p, root):
                continue
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                yield rp


def copy_release(root: Path, dest: Path, selected: Iterable[str] | None = None) -> list[dict]:
    """Copy selected files and return manifest rows."""
    root = root.resolve()
    dest = dest.resolve()
    if dest.exists():
        raise FileExistsError(str(dest))
    rows = []
    for src in iter_files(root, selected):
        rel = src.relative_to(root)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        rows.append(
            {
                "path": rel.as_posix(),
                "bytes": out.stat().st_size,
                "sha256": sha256_file(out),
            }
        )
    return rows


def _git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def build_release(root: Path, output: Path, profile: str = "display") -> dict:
    if profile != "display":
        raise ValueError("当前只实现 display 发布档；admin/full 需另立发布清单")
    dest = output.resolve()
    rows = copy_release(root, dest, DISPLAY_PATHS)
    manifest = {
        "schema": "cdut3d-release/1",
        "profile": profile,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "git_commit": _git_commit(root),
        "file_count": len(rows),
        "total_bytes": sum(x["bytes"] for x in rows),
        "files": sorted(rows, key=lambda x: x["path"]),
    }
    (dest / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return manifest


def verify_release(dest: Path) -> list[str]:
    dest = dest.resolve()
    manifest_path = dest / "release-manifest.json"
    problems: list[str] = []
    if not manifest_path.is_file():
        return ["release-manifest.json 不在"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ["release-manifest.json 读不动：%s" % exc]

    expected = {row["path"]: row for row in manifest.get("files") or []}
    actual = {
        p.relative_to(dest).as_posix()
        for p in dest.rglob("*")
        if p.is_file() and p.name != "release-manifest.json"
    }
    for rel, row in expected.items():
        p = dest / rel
        if not p.is_file():
            problems.append("缺：%s" % rel)
            continue
        if p.stat().st_size != row["bytes"]:
            problems.append("大小不符：%s" % rel)
            continue
        if sha256_file(p) != row["sha256"]:
            problems.append("SHA-256 不符：%s" % rel)
    for rel in sorted(actual - set(expected)):
        problems.append("多出：%s" % rel)
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build", "verify"])
    ap.add_argument("target", help="build 时为输出目录；verify 时为发布目录")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--profile", choices=["display"], default="display")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if args.command == "build":
        try:
            m = build_release(Path(args.root), target, args.profile)
        except (OSError, ValueError) as exc:
            print("发布构建失败：%s" % exc, file=sys.stderr)
            return 1
        print("发布已生成：%s" % target)
        print("  files=%d bytes=%d profile=%s" % (m["file_count"], m["total_bytes"], m["profile"]))
        return 0

    problems = verify_release(target)
    if problems:
        for x in problems:
            print("✗ " + x)
        return 1
    print("✓ 发布清单、文件集合与 SHA-256 全部一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
