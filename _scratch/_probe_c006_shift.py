# -*- coding: utf-8 -*-
"""c006 统一轮廓回归第二步: 各层「自己轮廓」之间到底是平移还是形状不同(只读)。

前一步实测: F0 与 F2 轮廓面积几乎相等(5699.3 / 5694.4)但对称差双向各 ~558㎡
—— 疑似平移 ~1m。本探针直接量质心差 / bbox 差 / 最优平移量(用平移后对称差最小化),
并给出 floor_plans 的 (cx, cy) 与质心对比,定位平移从哪来。
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]
import ezdxf
from shapely.geometry import Polygon
from run_building import load_profile
from backend.recognizer import floor as FL
from backend.recognizer.classify_line import classify_line

p = load_profile("c006")
doc = ezdxf.readfile(p.dxf)
walls, _d, _s, _c = classify_line(doc.modelspace(), p)
floors = sorted({FL.floor_of(p, sum(q[0] for q in pts) / len(pts),
                            sum(q[1] for q in pts) / len(pts)) for pts in walls})

own, wl = {}, {}
for F in [0, 1, 2, 3, 4, 5]:
    tr = (p.transition or {}).get(F)
    pts = FL.wall_pts_for_floor(F, walls, p, tr.get("wall_x") if tr else None,
                                tr.get("wall_x_clip") if tr else None)
    o, g, t = FL.derive_walls_and_outline(pts, p)
    own[F] = o.buffer(0)
    wl[F] = list(zip([list(x.exterior.coords) for x in g], t))

print("-- floor_plans (原始图纸 mm) 与 轮廓质心 --")
for F in [0, 1, 2, 3, 4, 5]:
    cx, cy = p.floor_plans[F][0], p.floor_plans[F][1]
    print("  F%-2d  plan cx=%9.1f cy=%9.1f   轮廓质心 (%7.3f, %7.3f)  bbox x[%7.2f,%7.2f] y[%7.2f,%7.2f]"
          % (F, cx, cy, own[F].centroid.x, own[F].centroid.y,
             own[F].bounds[0], own[F].bounds[2], own[F].bounds[1], own[F].bounds[3]))

print("\n-- 相对 F0 的质心差 / 最优平移量(最小化对称差) --")
ref = own[0]
for F in [1, 2, 3, 4, 5]:
    o = own[F]
    dx0 = o.centroid.x - ref.centroid.x
    dy0 = o.centroid.y - ref.centroid.y
    best = None
    for ix in range(-250, 251, 10):
        for iy in range(-250, 251, 10):
            from shapely.affinity import translate
            d = translate(o, ix / 100.0, iy / 100.0).symmetric_difference(ref).area
            if best is None or d < best[0]:
                best = (d, ix / 100.0, iy / 100.0)
    d0 = o.symmetric_difference(ref).area
    print("  F%-2d  质心差 (%+6.3f, %+6.3f) | 不平移对称差 %7.1f -> 最优平移(%+5.2f,%+5.2f)后 %7.1f"
          % (F, dx0, dy0, d0, best[1], best[2], best[0]))

print("\n-- 各层自己轮廓的「自越界」(墙 vs 自己的轮廓) --")
for F in [0, 1, 2, 3, 4, 5]:
    tot = out = 0.0
    for poly, _t in wl[F]:
        P = Polygon(poly)
        if not P.is_valid:
            P = P.buffer(0)
        if P.is_empty or P.area <= 1e-9:
            continue
        tot += P.area
        out += P.area - P.intersection(own[F]).area
    print("  F%-2d  %5.2f%%" % (F, 100.0 * out / tot if tot else 0))
