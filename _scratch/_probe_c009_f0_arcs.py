# -*- coding: utf-8 -*-
"""查清 c009 首层那 390m「轮廓外弧墙」到底是什么东西(只读)。

疑问: 开了 pair_curved 后首层弧墙识别率 75%, 剩下 25% 全在统一轮廓之外。但关掉
outline_unify 让轮廓盖住它们时, 墙数反而塌了(层1 41->17)且 ERROR 37->121。所以
这 390m 很可能不是「被轮廓切掉的真墙」, 而是柱廊/雨棚之类的非围护弧。

逐条 dump 墙层上落在首层轮廓外的弧实体: 图层 / 实体类型 / 半径 / 弧长 / 是否闭合 /
弧两端点间距, 并统计「成对(两条平行弧组成一条带)」的比例 —— 真墙皮会成对出现。
"""
import sys, os, json, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from shapely.geometry import Polygon, Point, LineString
from run_building import load_profile
from backend.recognizer.profile import floor_of, to_local, in_floor_x_range
from backend.recognizer.classify import _seg_radius, CURVE_MIN_R
from _diag_frozen_outline import load_floors, outline_of

nm = sys.argv[1] if len(sys.argv) > 1 else "c009"
F0 = int(sys.argv[2]) if len(sys.argv) > 2 else 0
p = load_profile(nm)
fl = load_floors(nm)
O = outline_of(fl[F0])
print("== %s 层%d 轮廓 面积%.1f㎡ 顶点%d ==" % (nm, F0, O.area, len(fl[F0]["outline"])))

doc = ezdxf.readfile(p.dxf)
rows = []
for e in doc.modelspace():
    if e.dxf.layer != p.wall_layer:
        continue
    t = e.dxftype()
    if t == "ARC":
        if e.dxf.radius < CURVE_MIN_R * 1000.0:
            continue
        pts = [(float(q[0]), float(q[1])) for q in e.flattening(50.0)]
        r = e.dxf.radius
        sag = abs(e.dxf.start_angle - e.dxf.end_angle)
        kind = "ARC"
    elif t == "LWPOLYLINE":
        raw = list(e.get_points("xyseb"))
        curves = []
        for i in range(len(raw) - 1):
            b = raw[i][4] if len(raw[i]) > 4 else 0.0
            rr = _seg_radius((raw[i][0], raw[i][1]), (raw[i + 1][0], raw[i + 1][1]), b)
            if rr is not None and rr >= CURVE_MIN_R * 1000.0:
                curves.append(rr)
        if not curves:
            continue
        from ezdxf.path import make_path
        pts = [(float(q.x), float(q.y)) for q in make_path(e).flattening(1.0)]
        r = sum(curves) / len(curves)
        kind = "LWPOLY(n=%d弧)" % len(curves)
    else:
        continue
    xs = [a for a, b in pts]
    ys = [b for a, b in pts]
    cx = (min(xs) + max(xs)) / 2.0
    if not in_floor_x_range(p, cx):
        continue
    # 逐点判轮廓内外
    inside = sum(1 for (a, b) in pts if O.contains(Point(*to_local(p, a, b, F0))))
    if inside == len(pts) or inside > 0:
        continue           # 只看完全落在轮廓外的
    loc = [to_local(p, a, b, F0) for a, b in pts]
    L = sum(math.hypot(loc[i + 1][0] - loc[i][0], loc[i + 1][1] - loc[i][1])
            for i in range(len(loc) - 1))
    x0 = min(a for a, b in loc); x1 = max(a for a, b in loc)
    y0 = min(b for a, b in loc); y1 = max(b for a, b in loc)
    dmax = max(O.boundary.distance(Point(*q)) for q in loc)
    rows.append((L, kind, r, x1 - x0, y1 - y0, (x0 + x1) / 2, (y0 + y1) / 2,
                 dmax, getattr(e, "closed", False)))

rows.sort(reverse=True)
print("轮廓外弧实体 %d 条, 总弧长 %.1fm" % (len(rows), sum(r[0] for r in rows)))
print("  %-8s %-14s %-8s %-16s %-18s %s" % ("弧长m", "类型", "半径m", "范围W x H(m)", "中心(x,y)", "最远越界m 闭合"))
for (L, kind, r, w, h, cx, cy, dmax, cl) in rows[:20]:
    print("  %-8.1f %-14s %-8.0f %-16s %-18s %.2f  %s"
          % (L, kind, r / 1000.0, "%.1f x %.1f" % (w, h), "(%.1f, %.1f)" % (cx, cy), dmax, cl))
print("\n半径分布: %s" % ", ".join("%.0fm x%d" % (r, sum(1 for q in rows if abs(q[2] - r) < 100))
                                   for r in sorted({round(q[2]) for q in rows})))
