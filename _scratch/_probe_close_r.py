# -*- coding: utf-8 -*-
"""c006 主体与弧形塔块之间到底隔多远? 闭运算半径取多少能并进来?(只读)

_biggest_outline 在 union 仍是 MultiPolygon 时只取 max(area), 卫星块(塔)被丢。
本探针不改引擎, 只把派生出的 wall_geoms 拿来重放: 对一组 close_r 值报
  轮廓面积 / 是否含塔点 / 连通块数 / 塔块与主体的最小间距。
用法: python _probe_close_r.py [c006] [层号...]
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from run_building import load_profile
from backend.recognizer.profile import floor_of
from backend.recognizer.floor import wall_pts_for_floor
from backend.recognizer.geometry import derive_walls_and_outline

nm = sys.argv[1] if len(sys.argv) > 1 else "c006"
want = [int(a) for a in sys.argv[2:]]
p = load_profile(nm)

if getattr(p, "classifier", "lwpolyline") == "line":
    from backend.recognizer.classify_line import classify_line as _cf
else:
    from backend.recognizer.classify import classify as _cf
doc = ezdxf.readfile(p.dxf)
walls = _cf(doc.modelspace(), p)[0]

TESTS = [(33.0, -36.0), (-33.0, -36.0), (27.0, -36.0), (-27.0, -36.0), (55.0, 10.0), (-55.0, 10.0)]
floors = sorted({int(round(floor_of(p, sum(q[0] for q in w) / len(w), sum(q[1] for q in w) / len(w))))
                 for w in walls if len(w)})
R = 12.0

for F in (want or [2, 4]):
    if F not in floors:
        continue
    tr = (p.transition or {}).get(F)
    wp = wall_pts_for_floor(F, walls, p, tr.get("wall_x") if tr else None)
    _o, wg, _x = derive_walls_and_outline(wp, p)
    U0 = unary_union(wg)
    gs0 = [U0] if U0.geom_type == "Polygon" else list(U0.geoms)
    gs0 = sorted(gs0, key=lambda g: -g.area)
    print("\n===== %s 层%d: wall_geoms %d 块, 最大 %.1f㎡, 次大 %.1f㎡ ====="
          % (nm, F, len(gs0), gs0[0].area if gs0 else 0,
             gs0[1].area if len(gs0) > 1 else 0))
    # 塔点所在块(半径 R 内最近的块)与最大块的最小间距
    main = gs0[0] if gs0 else None
    for t in TESTS:
        cand = [g for g in gs0 if g.distance(Point(*t)) <= R]
        if not cand:
            continue
        near = min(cand, key=lambda g: g.distance(Point(*t)))
        if near is main:
            print("   点%-12s 就在最大块里(面积%.1f㎡)" % (str(t), near.area))
            continue
        print("   点%-12s 所在块 %.1f㎡  与最大块最小间距 %.2fm  块内=%s"
              % (str(t), near.area, near.distance(main), near.contains(Point(*t))))
    print("   %-8s %-12s %-10s %s" % ("close_r", "轮廓面积㎡", "连通块", "含塔点"))
    for r in (0.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0):
        region = U0
        if r > 0:
            region = region.buffer(r).buffer(-r)
        n = 1 if region.geom_type == "Polygon" else len(region.geoms)
        if region.geom_type == "MultiPolygon":
            region = max(region.geoms, key=lambda g: g.area)
        if region.is_empty:
            print("   %-8.1f %-12s %-10d -" % (r, "-", 0))
            continue
        o = Polygon(region.exterior)
        hit = [("(%.0f,%.0f)" % t) for t in TESTS if o.contains(Point(*t))]
        print("   %-8.1f %-12.1f %-10d %s" % (r, o.area, n, " ".join(hit) or "无"))
