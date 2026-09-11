# -*- coding: utf-8 -*-
"""c009 首层轮廓为什么小: 逐层量「墙点列 -> 推导轮廓」的中间量(只读)。

疑问: outline_unify 统一层集里挑「面积最大」的层当基准, c009 首层落选 → 它的翼楼
弧形外墙被判域外。要修就得让首层自己推出来的轮廓够大, 所以先看清首层推导的哪一步塌了:
  A. 墙点列太少(分类阶段就丢了)         -> 看 polylines / 总长
  B. 墙 union 碎成多块(轮廓取到小碎块)   -> 看 union 连通块数 / 各块面积
  C. 薄厚判别把墙误判成楼板填充剔掉      -> 看被剔的"厚"几何体量

用法: python _probe_c009_floor0.py [c009]
"""
import sys, os, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import floor_of, to_local
from backend.recognizer.floor import wall_pts_for_floor, unify_floor_set, reference_outline_for
from backend.recognizer.geometry import derive_walls_and_outline

nm = sys.argv[1] if len(sys.argv) > 1 else "c009"
p = load_profile(nm)
doc = ezdxf.readfile(p.dxf)
walls_dxf, doors, stairs, cols = classify.classify(doc.modelspace(), p)
print("== %s 分类: 墙实体 %d 条, 门 %d, 楼梯 %d, 柱 %d ==" % (nm, len(walls_dxf), len(doors), len(stairs), len(cols)))

floors = sorted({int(floor_of(p, sum(q[0] for q in w) / len(w), sum(q[1] for q in w) / len(w)))
                 for w in walls_dxf if len(w)})
print("  分类出的墙落在层: %s" % floors)
print("  统一层集 = %s" % sorted(unify_floor_set(p, floors)))

print("\n  %-4s %-8s %-10s %-10s %-9s %-9s %s"
      % ("层", "折线数", "墙点总长m", "轮廓面积㎡", "轮廓顶点", "union块", "最大块占union"))
for F in floors:
    tr = (p.transition or {}).get(F)
    wall_x = tr.get("wall_x") if tr else None
    wp = wall_pts_for_floor(F, walls_dxf, p, wall_x)
    L = sum(sum(math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1])
                for i in range(len(q) - 1)) for q in wp if len(q) > 1)
    o, wg, _extra = derive_walls_and_outline(wp, p)
    oa = o.area if o is not None and not o.is_empty else 0.0
    ov = len(o.exterior.coords) if o is not None and not o.is_empty else 0
    # union 连通块
    U = unary_union([g for g in wg]) if wg else None
    nparts, bigshare = 0, 0.0
    if U is not None and not U.is_empty:
        gs = [U] if U.geom_type == "Polygon" else list(U.geoms)
        gs = [g for g in gs if g.area > 0.5]
        nparts = len(gs)
        ta = sum(g.area for g in gs)
        bigshare = (max(g.area for g in gs) / ta) if ta else 0.0
    print("  %-4d %-8d %-10.0f %-10.1f %-9d %-9d %.0f%%"
          % (F, len(wp), L, oa, ov, nparts, 100 * bigshare))

# 首层 vs 典型层: 墙点列的 X 跨度对比(看首层是不是整条翼没进墙点列)
print("\n  -- 墙点列 X 跨度对比(看首层翼楼是否根本没进墙点列) --")
for F in floors:
    tr = (p.transition or {}).get(F)
    wp = wall_pts_for_floor(F, walls_dxf, p, tr.get("wall_x") if tr else None)
    if not wp:
        print("     层%-3d 无墙点" % F); continue
    xs = [q[0] for w in wp for q in w]
    ys = [q[1] for w in wp for q in w]
    print("     层%-3d X[%7.1f, %7.1f] 跨度%6.1f   Y[%7.1f, %7.1f] 跨度%6.1f"
          % (F, min(xs), max(xs), max(xs) - min(xs), min(ys), max(ys), max(ys) - min(ys)))
