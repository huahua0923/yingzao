# -*- coding: utf-8 -*-
"""Build a per-building status matrix from packs, verdicts and model headers."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs" / "cdut-main"
OUT_JSON = ROOT / "workbench" / "ui" / "building-status.json"
OUT_MD = ROOT / "docs" / "楼房状态矩阵-2026-10-21.md"
GATE_LABELS = {
    "J-10.8-00": "轮廓可喂 SU",
    "J-10.8-01": "白模形体",
    "J-10.8-04": "原始 DXF 叠加",
    "J-10.9-07": "构件类闭合",
}


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def glb_header(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            magic, version, length = struct.unpack("<4sII", f.read(12))
            if magic != b"glTF":
                return {"ok": False, "error": "not glTF"}
            chunk_len, chunk_type = struct.unpack("<II", f.read(8))
            raw = f.read(chunk_len)
            doc = json.loads(raw.rstrip(b" \t\r\n\0").decode("utf-8"))
    except (OSError, ValueError, struct.error, UnicodeDecodeError) as exc:
        return {"ok": False, "error": str(exc)}
    accessors = doc.get("accessors") or []
    meshes = doc.get("meshes") or []
    tri = 0
    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            idx = prim.get("indices")
            pos = (prim.get("attributes") or {}).get("POSITION")
            aid = idx if idx is not None else pos
            if isinstance(aid, int) and 0 <= aid < len(accessors):
                tri += int(accessors[aid].get("count") or 0) // 3
    bounds = []
    for acc in accessors:
        if acc.get("type") == "VEC3" and acc.get("min") and acc.get("max"):
            bounds.append((acc["min"], acc["max"]))
    return {
        "ok": True,
        "version": version,
        "nodes": len(doc.get("nodes") or []),
        "meshes": len(meshes),
        "materials": len(doc.get("materials") or []),
        "images": len(doc.get("images") or []),
        "triangles": tri,
        "bounds_v3": len(bounds),
    }


def room_count(bid: str) -> int:
    p = PACKS / bid / "ledger" / "rooms.json"
    d = load_json(p)
    return len(d) if isinstance(d, list) else 0


def gate_cell(matrix: dict, gate: str, bid: str) -> dict:
    cell = ((matrix.get("cells") or {}).get(gate) or {}).get(bid) or {}
    return {
        "pass": cell.get("pass"),
        "rc": cell.get("rc"),
        "red": cell.get("red"),
        "unmeasured": cell.get("unmeasured"),
        "note": cell.get("note") or cell.get("crashed") or "",
    }


def verdict_items(gate: str, bid: str) -> list[dict]:
    p = ROOT / "gates" / "_out" / f"{gate}.{bid}.json"
    d = load_json(p, {})
    return [x for x in (d.get("items") or []) if x.get("status") == "fail"]


def build() -> dict:
    idx = load_json(ROOT / "packs" / "index.json", {}) or {}
    matrix = load_json(ROOT / "gates" / "_out" / "matrix.json", {}) or {}
    gates = list(matrix.get("gates") or GATE_LABELS)
    rows = []
    for pack in idx.get("packs") or []:
        bid = pack.get("id")
        if not bid:
            continue
        pdir = PACKS / bid
        manifest = load_json(pdir / "manifest.json", {}) or {}
        model = pdir / "model" / f"{bid}-building.glb"
        actual_sha = sha256(model) if model.is_file() else ""
        arts = manifest.get("artifacts") or {}
        if isinstance(arts, dict):
            expect_sha = (arts.get("model") or {}).get("sha256")
        else:
            expect_sha = next((a.get("sha256") for a in arts if a.get("role") == "model"), None)
        hdr = glb_header(model) if model.is_file() else {"ok": False, "error": "model missing"}
        cells = {g: gate_cell(matrix, g, bid) for g in gates}
        red_gates = []
        for g, c in cells.items():
            if c.get("pass") is False:
                red_gates.append(
                    {
                        "gate": g,
                        "label": GATE_LABELS.get(g, g),
                        "items": verdict_items(g, bid)[:8],
                    }
                )
        audit = []
        if not model.is_file():
            audit.append("模型文件不在")
        elif expect_sha and actual_sha != expect_sha:
            audit.append("模型 SHA-256 与 manifest 不一致")
        if hdr.get("ok") is False:
            audit.append("GLB 头读不动：%s" % hdr.get("error"))
        elif hdr.get("meshes", 0) <= 0 or hdr.get("nodes", 0) <= 0:
            audit.append("GLB 没有 mesh/node")
        rooms = room_count(bid)
        if rooms <= 0:
            audit.append("房间台账为空")
        if any(c.get("pass") is False for c in cells.values()) or audit:
            status = "red"
        elif any(c.get("pass") is None for c in cells.values()):
            status = "unknown"
        else:
            status = "green"
        rows.append(
            {
                "id": bid,
                "title": pack.get("title") or bid,
                "status": status,
                "created_at": pack.get("created_at"),
                "floors": (pack.get("floors") or {}).get("n_floors"),
                "floor_h_m": (pack.get("floors") or {}).get("floor_h_m"),
                "qc": (pack.get("qc") or {}).get("level"),
                "positive_control": (pack.get("qc") or {}).get("positive_control_value"),
                "blind_spots": (pack.get("qc") or {}).get("n_blind_spots"),
                "rooms": rooms,
                "model_bytes": model.stat().st_size if model.is_file() else 0,
                "pack_bytes": pack.get("bytes") or 0,
                "model_sha256": actual_sha,
                "model_sha_ok": bool(expect_sha and actual_sha == expect_sha),
                "glb": hdr,
                "gates": cells,
                "red_gates": red_gates,
                "audit_issues": audit,
            }
        )
    order = {"red": 0, "unknown": 1, "green": 2}
    rows.sort(key=lambda r: (order[r["status"]], r["id"]))
    summary = {
        "total": len(rows),
        "green": sum(r["status"] == "green" for r in rows),
        "red": sum(r["status"] == "red" for r in rows),
        "unknown": sum(r["status"] == "unknown" for r in rows),
        "overlay_pass": sum(r["gates"].get("J-10.8-04", {}).get("pass") is True for r in rows),
        "rooms": sum(r["rooms"] for r in rows),
        "model_bytes": sum(r["model_bytes"] for r in rows),
    }
    return {
        "schema": "cdut3d-building-status/1",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "matrix_generated_at": matrix.get("generated_at"),
        "summary": summary,
        "gates": gates,
        "buildings": rows,
    }


def markdown(doc: dict) -> str:
    s = doc["summary"]
    lines = [
        "# 楼房状态矩阵 2026-10-21",
        "",
        "> 生成：%s；判据矩阵：%s" % (doc["generated_at"], doc.get("matrix_generated_at")),
        "",
        "## 总览",
        "",
        "| 总数 | 绿 | 红 | 没量到 | 原始 DXF 叠加通过 | 房间数 | 模型体积 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
        "| %(total)d | %(green)d | %(red)d | %(unknown)d | %(overlay_pass)d | %(rooms)d | %(model_mb).1f MB |"
        % {**s, "model_mb": s["model_bytes"] / 1048576.0},
        "",
        "## 每栋楼",
        "",
        "| 状态 | 楼栋 | 名称 | 层数 | QC | 房间 | "
        "J-10.8-00 | J-10.8-01 | J-10.8-04 | J-10.9-07 | 主要问题 |",
        "|---|---|---|---:|---|---:|---|---|---|---|---|",
    ]
    for r in doc["buildings"]:
        marks = []
        for g in doc["gates"]:
            c = r["gates"].get(g) or {}
            marks.append("✔" if c.get("pass") is True else ("✗" if c.get("pass") is False else "?"))
        issues = list(r["audit_issues"])
        for x in r["red_gates"]:
            if x["items"]:
                issues.append("%s：%s" % (x["label"], x["items"][0].get("text", "")[:90]))
            else:
                issues.append("%s：判红" % x["label"])
        lines.append(
            "| %s | %s | %s | %s | %s | %d | %s | %s |"
            % (
                {"green": "绿", "red": "红", "unknown": "没量到"}[r["status"]],
                r["id"],
                r["title"],
                r["floors"],
                r["qc"],
                r["rooms"],
                " | ".join(marks),
                "；".join(issues[:3]) or "—",
            )
        )
    lines += [
        "",
        "## 口径",
        "",
        "- 状态只来自当前 `packs/` 与当前判据矩阵，不拿旧读数冒充今天。",
        "- `J-10.8-04` 是原始 DXF 叠加比对；它绿表示宏观轮廓与源图能对上，不代表局部构件无误。",
        "- `?` 是没量到，不是通过。",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(OUT_JSON))
    ap.add_argument("--md", default=str(OUT_MD))
    args = ap.parse_args(argv)
    doc = build()
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    Path(args.md).write_text(markdown(doc), encoding="utf-8", newline="\n")
    s = doc["summary"]
    print(json.dumps(s, ensure_ascii=False))
    print("json:", args.json)
    print("md:", args.md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
