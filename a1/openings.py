# -*- coding: utf-8 -*-
"""A1：**通用门窗洞口识别** —— 门窗在墙层里按**几何**认（本库没有独立门窗层，见下）。

背景（A1 全库普查 2026-10-12，`a1/probe_openings.py` 出的 `_out/openings_census.json`）：
  · 105 份里 **墙层有 INSERT 的只有 5 栋**；块名 `$DorLib2D$*`（门库，684+36+36）／`$plan$*`(300)
    ／`_ArchTick`(14，**标注斜线，不是门**)。
  · **多段线口径**：洞口候选散布 **95/105 栋**，全库 26788 条；顶点数 14-顶点 16233、13-顶点 4908…
    ⇒ **同一构件在不同栋用不同顶点数画**（C011=13、C009=14），**没有统一签名**。
  · 有 `ARC` 画门的（C075 墙层 151 个 ARC）。
⇒ 只能**多路识别**：把每种「像洞口的自足小图形」收成足迹，**如实报每种收了多少、剩多少没收**。

★ 多路（各自计数，互不冒充）：
    INSERT        墙层块，展开后 bbox 落在洞口尺寸窗 ⇒ 足迹 = 该 bbox 矩形
    LWPOLYLINE    顶点 ≥`MINV` 且 bbox 落在窗口 ⇒ `Polygon(pts).buffer(0)`
    ARC           半径在 `ARC_R`（门扇开启弧）⇒ 足迹 = **弧线本身**缓冲（如实：它是开启弧，不是门洞）

★ 量具盲区（必须声明；盲区内的**否定**判词不算证据）：
  ① 只按 `OPEN_LAYERS`（=四种墙层名）过滤。门画在别的层 ⇒ **全盲**（本库实测：`4.3门标注` 是
     **MTEXT 文字**不是几何；`4.3门窗`/`WINDOW_TEXT` 只在个别栋）。「没找到」≠「没有」。
  ② 判的是「墙层里像洞口的**自足小图形**有几块」，**不判它是不是门**、不判是不是窗、不判开在哪面墙。
  ③ 参数 `MINV`/`OPEN_LONG`/`OPEN_SHORT`/`ARC_R` 是**判据参数**（按建筑常用门宽 0.7~1.5 m 定），
     不是从任何规范抄的；改参数会改数。**窗**（可宽到 3 m）与**门**共用同一窗口，本尺**不分**。
  ④ **一块洞口可能由多个实体拼出**（门=扇线+开启弧+门垛标记）⇒ 单看 `hits` 会**高估**；`n_clusters`
     （并集连通块）才是「几处洞口」。两个数都要报，**不许只报一个**。
  ⑤ 墙线上的**门垛小方块**（400×350）会被短边窗滤掉，但**真实尺寸的柱/家具**若落在窗内会被算进来
     —— 本尺对「这图形是什么用途」全盲。

用法: python openings.py <dxf> [--json o.json]
"""
import sys
import os
import json
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union

OPEN_LAYERS = ("4.2墙体", "4墙体", "4.3封墙", "4.3新封墙")

MINV = 8                        # 多段线顶点下限：墙线=2 点，洞口符号=多点
OPEN_LONG = (700.0, 3000.0)     # 长边窗（mm）：门 0.7~1.5 m、窗可到 3 m
OPEN_SHORT = (150.0, 3000.0)    # 短边窗
ARC_R = (600.0, 1600.0)         # 门扇开启弧半径窗（mm）
LINE_W = 30.0                   # 弧线缓冲半宽（画一条线，不是为了算面积）


def _in_box(w, h):
    lo, hi = min(w, h), max(w, h)
    return OPEN_LONG[0] <= hi <= OPEN_LONG[1] and OPEN_SHORT[0] <= lo <= OPEN_SHORT[1]


def _pts_of(e):
    try:
        return [(p[0], p[1]) for p in e.get_points()]
    except Exception:
        return []


def _box_of_pts(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return max(xs) - min(xs), max(ys) - min(ys)


def _rect(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def openings_of(e, hits, depth=0):
    """一个实体 → 洞口足迹列表；命中/未决都记进 hits。"""
    t = e.dxftype()
    if t == "INSERT":
        hits["INSERT"] += 1
        if depth > 4:
            return []
        pts = []
        for v in e.virtual_entities():
            vt = v.dxftype()
            if vt in ("LWPOLYLINE", "POLYLINE"):
                pts += _pts_of(v)
            else:
                for a in ("start", "end", "center", "insert"):
                    if hasattr(v.dxf, a):
                        q = getattr(v.dxf, a)
                        pts.append((q.x, q.y))
                if vt == "LINE":
                    pts += [(v.dxf.start.x, v.dxf.start.y), (v.dxf.end.x, v.dxf.end.y)]
        if len(pts) < 2:
            hits["INS_empty"] += 1
            return []
        w, h = _box_of_pts(pts)
        if not _in_box(w, h):
            hits["INS_out"] += 1
            return []
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return [_rect(min(xs), min(ys), max(xs), max(ys))]
    if t in ("LWPOLYLINE", "POLYLINE"):
        pts = _pts_of(e)
        if len(pts) < MINV:
            hits["PLY_short"] += 1
            return []
        w, h = _box_of_pts(pts)
        if not _in_box(w, h):
            hits["PLY_out"] += 1
            return []
        g = Polygon(pts).buffer(0)
        if g.is_empty:
            return []
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        return [g]
    if t == "ARC":
        hits["ARC"] += 1
        r = e.dxf.radius
        if not (ARC_R[0] <= r <= ARC_R[1]):
            hits["ARC_out"] += 1
            return []
        try:
            ln = LineString(list(e.flattening(distance=20.0)))
        except Exception:
            return []
        return [ln.buffer(LINE_W)]
    key = "UNRESOLVED:" + t
    hits[key] += 1
    return []


def load_openings_from_msp(msp):
    lc = collections.Counter(e.dxf.layer for e in msp)
    layer_hit = [l for l in OPEN_LAYERS if l in lc]
    hits = collections.Counter()
    polys = []
    for e in msp:
        if e.dxf.layer not in OPEN_LAYERS:
            continue
        polys += openings_of(e, hits)
    return polys, layer_hit, hits


def load_openings(dxf):
    doc = ezdxf.readfile(dxf)
    return load_openings_from_msp(doc.modelspace())


def n_clusters(polys):
    if not polys:
        return 0, 0.0
    u = unary_union(polys)
    gs = list(getattr(u, "geoms", [u]))
    return len(gs), sum(g.area for g in gs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if not os.path.isfile(a.dxf):
        print("MISSING:", a.dxf); return 2
    polys, layer_hit, hits = load_openings(a.dxf)
    nc, area = n_clusters(polys)
    print("DXF       :", os.path.basename(a.dxf))
    print("命中墙层  :", layer_hit or "**无**（本尺全盲，盲区①）")
    print("实体构成  :", dict(hits))
    print("足迹块数  : %d   （★ 不是洞口数：一块洞口可能多个实体，盲区④）" % len(polys))
    print("洞口簇数  : %d   并集面积 %.2f m²" % (nc, area / 1e6))
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dxf": a.dxf, "layer_hit": layer_hit, "hits": dict(hits),
                   "n_polys": len(polys), "n_clusters": nc, "area_m2": area / 1e6},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
