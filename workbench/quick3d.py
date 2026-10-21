# -*- coding: utf-8 -*-
"""快速立体块：**一张 DXF → 一堆盒子**（没有立面图也能看个形体）。

★ 2026-10-19 用户：「输入一个 cad 就可以生成立体图，虽然没有立面图，
  但是至少看起来是那么一回事」。

它**不是**正式建模链（那要档案 + 十步 + 判据）。它只做一件事：
  把墙层/柱层的线段按固定层高拉成盒子，给页面一个能转的体量。
  ⇒ 不写 05_build/06_su，不碰包，不进判据。产物只落在 `workbench/_quick/`。

约定：
  · 墙 = 层名含「墙」；柱 = 层名含「柱」；其余层默认忽略（可用 layers 参数覆盖）。
  · 单位：包围盒最大边 > 500 ⇒ 按 mm；否则按 m（×1000）。
  · bulge（圆弧段）按弦线处理 —— 体量看形状，不看弧。
  · 盒子数上限 30000，超了按面积从大到小截断，并在 `counts.truncated` 里如实写。
"""
from __future__ import annotations

import math
import os

MAX_BOXES = 30000
WALL_T = 240.0          # mm
LEVEL_H = 4000.0        # mm


def _poly_points(e):
    """实体 → [(x, y), ...]；认 LINE / LWPOLYLINE / POLYLINE(2D)。认不出返回 []。"""
    t = e.dxftype()
    if t == "LINE":
        s, d = e.dxf.start, e.dxf.end
        return [(s.x, s.y), (d.x, d.y)]
    if t == "LWPOLYLINE":
        return [(p[0], p[1]) for p in e.get_points("xy")]
    if t == "POLYLINE":
        try:
            if e.is_3d_polyline:
                return []
            return [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        except Exception:
            return []
    return []


def _closed(e):
    try:
        return bool(e.closed)
    except Exception:
        return False


def _segments(pts, closed):
    out = []
    for i in range(len(pts) - 1):
        out.append((pts[i], pts[i + 1]))
    if closed and len(pts) > 2:
        out.append((pts[-1], pts[0]))
    return out


def _box_from_seg(p, q, thick, h, layer):
    dx, dy = q[0] - p[0], q[1] - p[1]
    ln = math.hypot(dx, dy)
    if ln < 1e-6:
        return None
    return {"x": (p[0] + q[0]) / 2.0, "z": (p[1] + q[1]) / 2.0,
            "w": ln, "d": thick, "h": h, "rot": math.atan2(dy, dx), "layer": layer}


def _box_from_poly(pts, h, layer):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    if w <= 0 or d <= 0:
        return None
    return {"x": (max(xs) + min(xs)) / 2.0, "z": (max(ys) + min(ys)) / 2.0,
            "w": w, "d": d, "h": h, "rot": 0.0, "layer": layer}


def parse(path, layer_filter=None, level_h=LEVEL_H, wall_t=WALL_T):
    """DXF → `{schema, bbox, boxes, counts}`。失败抛异常，调用方负责解释。"""
    import ezdxf
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    boxes = []
    skipped_layers = set()
    n_ent = 0
    for e in msp:
        n_ent += 1
        lay = (e.dxf.layer or "")
        is_wall = ("墙" in lay)
        is_col = ("柱" in lay)
        if layer_filter:
            keep = lay in layer_filter
        else:
            keep = is_wall or is_col
        if not keep:
            skipped_layers.add(lay)
            continue
        pts = _poly_points(e)
        if len(pts) < 2:
            continue
        if is_col and not layer_filter:
            b = _box_from_poly(pts, level_h, lay)
            if b:
                boxes.append(b)
            continue
        closed = _closed(e)
        for p, q in _segments(pts, closed):
            b = _box_from_seg(p, q, wall_t, level_h, lay)
            if b:
                boxes.append(b)

    # 单位判定：先看原始坐标跨度（mm 图里一栋楼是几万；m 图里是几十）
    if boxes:
        xs = [b["x"] for b in boxes]
        zs = [b["z"] for b in boxes]
        span = max(max(xs) - min(xs), max(zs) - min(zs))
    else:
        span = 0.0
    scaled = False
    if span and span < 500.0:
        for b in boxes:
            b["x"] *= 1000.0
            b["z"] *= 1000.0
            b["w"] *= 1000.0
            b["d"] *= 1000.0
        span *= 1000.0
        scaled = True

    truncated = 0
    if len(boxes) > MAX_BOXES:
        boxes.sort(key=lambda b: b["w"] * b["d"], reverse=True)
        truncated = len(boxes) - MAX_BOXES
        boxes = boxes[:MAX_BOXES]

    if not boxes:
        raise ValueError("这张图里没读到墙/柱层（层名含「墙」或「柱」）。"
                         "图里的层有：%s" % "、".join(sorted(skipped_layers)[:20]))
    x0 = min(b["x"] - b["w"] / 2 for b in boxes)
    x1 = max(b["x"] + b["w"] / 2 for b in boxes)
    z0 = min(b["z"] - b["d"] / 2 for b in boxes)
    z1 = max(b["z"] + b["d"] / 2 for b in boxes)
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    for b in boxes:
        b["x"] -= cx
        b["z"] -= cz

    return {"schema": "cdut3d-quick3d/1",
            "source": os.path.basename(path),
            "unit_scaled_from_m": scaled,
            "level_h": level_h, "wall_t": wall_t,
            "counts": {"boxes": len(boxes), "entities": n_ent,
                       "truncated": truncated,
                       "layers": sorted({b["layer"] for b in boxes})},
            "bbox": {"w": x1 - x0, "d": z1 - z0},
            "boxes": boxes}
