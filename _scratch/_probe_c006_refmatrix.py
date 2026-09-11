# -*- coding: utf-8 -*-
"""c006 统一轮廓回归第三步: 全 6x6 越界矩阵 + 各层轮廓的洞(只读)。

前两步结论: 各层自洽(0.82~1.66%), 但互相之间对称差 ~1120㎡ 且非平移(best shift=(0,0)),
bbox 几乎相同 —— 疑内部洞结构不同。本步量:
  (1) 选哪一层当基准, 六层总越界最小 —— 现引擎按「面积最大」选到 F0(5699.3);
  (2) 各层轮廓有几个洞、洞面积多少、洞在哪 —— 定位 1120㎡ 差异的来源。
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
SET = [0, 1, 2, 3, 4, 5]

own, wl = {}, {}
for F in SET:
    tr = (p.transition or {}).get(F)
    pts = FL.wall_pts_for_floor(F, walls, p, tr.get("wall_x") if tr else None,
                                tr.get("wall_x_clip") if tr else None)
    o, g, t = FL.derive_walls_and_outline(pts, p)
    own[F] = o.buffer(0)
    wl[F] = [Polygon(x) if Polygon(x).is_valid else Polygon(x).buffer(0) for x in g]


def outpct(polys, T):
    tot = out = 0.0
    for P in polys:
        if P.is_empty or P.area <= 1e-9:
            continue
        tot += P.area
        out += P.area - P.intersection(T).area
    return 100.0 * out / tot if tot else 0.0


print("-- 6x6 越界矩阵 (行=楼层墙, 列=基准层轮廓), 单位 % --")
print("         " + "".join("   ref F%-2d" % c for c in SET) + "   行合计")
best = None
rows = {}
for F in SET:
    row = [outpct(wl[F], own[c]) for c in SET]
    rows[F] = row
    s = sum(row)
    print("  F%-2d  " % F + "".join("   %6.2f " % v for v in row) + "  %7.2f" % s)
    if best is None or s < best[0]:
        best = (s, F)
print("  => 最优基准层 F%d (总越界 %.2f%%),  现引擎按面积最大选 F0 (总越界 %.2f%%)"
      % (best[1], best[0], sum(rows[F][0] for F in SET)))
print("  各层自己轮廓面积: " + "  ".join("F%d=%.1f" % (F, own[F].area) for F in SET))

print("\n-- 各层轮廓的洞 --")
for F in SET:
    o = own[F]
    holes = sorted([Polygon(r).area for r in o.interiors], reverse=True)
    print("  F%-2d  外环面 %.1f㎡   洞 %d 个%s" % (F, o.area, len(holes),
          ("  " + " ".join("%.1f" % h for h in holes[:6])) if holes else ""))
    for r in o.interiors[:3]:
        P = Polygon(r)
        print("        洞 面积%8.1f  质心(%7.2f,%7.2f)  bbox x[%7.2f,%7.2f] y[%7.2f,%7.2f]"
              % (P.area, P.centroid.x, P.centroid.y, P.bounds[0], P.bounds[2], P.bounds[1], P.bounds[3]))
