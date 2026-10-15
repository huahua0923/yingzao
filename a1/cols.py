# -*- coding: utf-8 -*-
"""A1：**通用柱加载** —— 把 `4.1结构柱` 的各种画法都吃进来，返回柱的二维足迹。

背景（A1 实测，全库 105 份 `4.1结构柱` 实体构成）：
    65 栋**根本没有柱层** ｜ 34 栋 LWPOLYLINE ｜ 2 栋 LWPOLYLINE,CIRCLE ｜ **1 栋 INSERT（= C006）**
    1 栋 CIRCLE ｜ 1 栋 ARC,CIRCLE,LWPOLYLINE ｜ 1 栋 LWPOLYLINE,LINE
⇒ 旧链（`generic_wall.py` / `build8.py`）**只认 INSERT 块** ⇒ 柱覆盖 **1/105**。本模块补成多路。

★ 支持的画法 → 足迹：
    INSERT          递归 `virtual_entities()`（块展开），内部同下面各支
    LWPOLYLINE/POLYLINE  顶点 ≥3 ⇒ `Polygon(pts).buffer(0)`（自交先修）
    CIRCLE          圆心 + 半径 ⇒ `Point.buffer(r, quad_segs=16)`
    SOLID/HATCH     取顶点/边界环 ⇒ Polygon（少数图用实心填充画柱）
    LINE            4 条围成矩形的常见画法：本模块**不做自动闭环**（会与墙线混淆），
                    只登记条数并记进 `unresolved`，**如实报「没建出来」不假装建了**。
    ARC/ELLIPSE/SPLINE  同上，登记不建（柱极少用这些画；真要用先看那 1 栋长什么样）。

★ 量具盲区（必须声明）：
  ① **只按图层名过滤**（`COL_LAYERS`）。柱画在别的层（如 `4.1柱子` 之外的别名）⇒ 本尺**全盲**；
     实测别名已列在 `COL_LAYERS`，但「没找到」≠「没有」。
  ② **判的是「建出了几块足迹」，不是「那块是不是柱」** —— 门垛/装饰柱也会中；几何对不对归 §10.1。
  ③ 不开 `LINE` 自动闭环 ⇒ **用 LINE 画的柱一律算没建出来**（那 1 栋）。
  ④ 单位按图纸毫米；面积阈值 `MIN_AREA` 写死，**阈值以下的细柱会被当噪声丢掉**。

用法: python cols.py <dxf>            # 单份，打印图层名/各类型计数/建出块数
     python cols.py <dxf> --json o.json
"""
import sys
import os
import json
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

# 图层别名：实测主名是 4.1结构柱；其余为可迁移的常见写法（找不到就是没有，不许当证据）
COL_LAYERS = ("4.1结构柱", "4.1柱子", "结构柱", "柱", "4.1-结构柱", "柱网")

MIN_AREA = 1e3      # mm²。100×100 mm 以下的当噪声（实测 c006 柱是 400~800 见方 = 1.6e5~6.4e5）


def _poly_from_pts(pts):
    if len(pts) < 3:
        return None
    g = Polygon(pts).buffer(0)
    if g.is_empty:
        return None
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda p: p.area)
    if g.geom_type != "Polygon" or g.area < MIN_AREA:
        return None
    return g


def polys_of(e, hits, depth=0):
    """把一个实体 → 足迹列表；命中/未决都记进 hits（供如实报）。"""
    t = e.dxftype()
    if t == "INSERT":
        hits["INSERT"] += 1
        if depth > 4:
            return []
        out = []
        for v in e.virtual_entities():
            out += polys_of(v, hits, depth + 1)
        return out
    if t in ("LWPOLYLINE", "POLYLINE"):
        hits["LWPOLYLINE"] += 1
        pts = [(p[0], p[1]) for p in e.get_points()]
        g = _poly_from_pts(pts)
        if g is None:
            hits["poly_bad"] += 1
            return []
        return [g]
    if t == "CIRCLE":
        hits["CIRCLE"] += 1
        c, r = e.dxf.center, e.dxf.radius
        if r <= 0:
            return []
        g = Point(c.x, c.y).buffer(r, quad_segs=16)
        return [g] if g.area >= MIN_AREA else []
    if t == "SOLID":
        hits["SOLID"] += 1
        p = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3, e.dxf.vtx2]
        g = _poly_from_pts([(q.x, q.y) for q in p])
        return [g] if g else []
    if t == "HATCH":
        hits["HATCH"] += 1
        try:
            paths = e.paths
        except Exception:
            paths = []
        ss = e.dxf.solid_fill if hasattr(e.dxf, "solid_fill") else 1
        return [] if not ss else _hatch_loops(e)
    # 未决画法：登记、不建（不许假装建了）
    key = "UNRESOLVED:" + t
    hits[key] += 1
    return []


def _hatch_loops(e):
    out = []
    for p in getattr(e, "paths", []):
        try:
            pts = [(v[0], v[1]) for v in p.vertices]
        except Exception:
            continue
        g = _poly_from_pts(pts)
        if g:
            out.append(g)
    return out


def load_cols_from_msp(msp):
    """从已打开的模型空间取柱 —— 让调用方**不必重读 DXF**（`generic_wall` 用这条）。"""
    lc = collections.Counter(e.dxf.layer for e in msp)
    layer_hit = [l for l in COL_LAYERS if l in lc]
    hits = collections.Counter()
    polys = []
    for e in msp:
        if e.dxf.layer not in COL_LAYERS:
            continue
        polys += polys_of(e, hits)
    return polys, layer_hit, hits


def load_cols(dxf):
    """返回 (col_polys, layer_hit, hits_counter)。col_polys = 已修好的 Polygon 列表。"""
    doc = ezdxf.readfile(dxf)
    return load_cols_from_msp(doc.modelspace())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if not os.path.isfile(a.dxf):
        print("MISSING:", a.dxf)
        return 2
    polys, layer_hit, hits = load_cols(a.dxf)
    u = unary_union(polys) if polys else None
    area = 0.0
    if u is not None:
        gs = u.geoms if hasattr(u, "geoms") else [u]
        area = sum(g.area for g in gs)
    print("DXF      :", os.path.basename(a.dxf))
    print("命中柱层 :", layer_hit or "**无**（本尺对该图全盲，见盲区①）")
    print("实体构成 :", dict(hits))
    print("建出柱块 :", len(polys), " 并后:", (len(u.geoms) if u is not None and hasattr(u, "geoms") else (0 if u is None else 1)))
    print("柱足迹面积: %.2f m²" % (area / 1e6))
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dxf": a.dxf, "layer_hit": layer_hit, "hits": dict(hits),
                   "n_polys": len(polys), "area_m2": area / 1e6},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
