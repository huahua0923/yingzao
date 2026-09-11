# -*- coding: utf-8 -*-
"""量 pair_arc_bands 的原始输出(只读) —— 顶点数/弧长/厚度/圆心。

判断「17 顶点 / 26.8m」是配对阶段就粗, 还是下游(clip/clean)削掉的:
这里直接看 1) 原始 ARC 收集结果 2) 配对后的每个 band 的顶点数与弧长。
"""
import sys, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

import ezdxf
from run_building import load_profile
from backend.recognizer.classify import CURVE_MIN_R
from backend.recognizer.curve_walls import pair_arc_bands, _annular

p = load_profile("c006")
doc = ezdxf.readfile(p.dxf)
msp = doc.modelspace()

arcs = []
for e in msp:
    if e.dxftype() != "ARC" or e.dxf.layer != p.wall_layer:
        continue
    if e.dxf.radius < CURVE_MIN_R * 1000.0:
        continue
    c = e.dxf.center
    arcs.append((c.x, c.y, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle))

print("ARC 实体(半径>=%.0fm) %d 条" % (CURVE_MIN_R, len(arcs)))
groups = {}
for cx, cy, r, a0, a1 in arcs:
    groups.setdefault((round(cx), round(cy)), []).append((r, a0, a1))
for k in sorted(groups):
    print("  圆心(%9.1f,%9.1f): %d 条  半径 %s"
          % (k[0], k[1], len(groups[k]),
             " ".join("%.1f" % r for r, _a, _b in sorted(groups[k]))))

bands = pair_arc_bands(arcs, p, sag_mm=10.0)
print("\npair_arc_bands -> %d 条" % len(bands))
for P, t in bands:
    co = list(P.exterior.coords)
    L = 0.0
    for i in range(len(co) - 1):
        L += math.hypot(co[i + 1][0] - co[i][0], co[i + 1][1] - co[i][1])
    c = P.centroid
    print("  厚度%.3fm 顶点%3d 外环周长%7.2fm 长(估)%7.2fm 面积%8.1f㎡ 质心(%9.1f,%9.1f) bbox x[%.0f,%.0f] y[%.0f,%.0f]"
          % (t, len(co), L, (L - 2 * t * 1000) / 2.0, P.area, c.x, c.y,
             P.bounds[0], P.bounds[2], P.bounds[1], P.bounds[3]))
