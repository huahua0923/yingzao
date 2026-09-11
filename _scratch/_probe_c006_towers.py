# -*- coding: utf-8 -*-
"""c006 弧形楼梯间(本地 ±33,-36) 为什么不在交付轮廓里(只读)。

交付轮廓 5365.9㎡ 但 bbox 129x84(=10800㎡), 说明轮廓是凹的, 两个塔落在缺口。
分工况:
  A. 各层「自己派生」的轮廓就不含塔 -> 病灶在派生(墙没进 union / 轮廓只取最大连通块)
  B. 某层自己含塔, 但被选中当基准的是另一层 -> 病灶在 reference_outline_for 的「最大面积」挑法
逐层报: 该层派生轮廓面积 / 是否含塔点 / union 块数 / 最大块占比。

用法: python _probe_c006_towers.py [c006]
"""
import sys, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from run_building import load_profile
from backend.recognizer.profile import floor_of
from backend.recognizer.floor import (wall_pts_for_floor, unify_floor_set,
                                      reference_outline_for)
from backend.recognizer.geometry import derive_walls_and_outline

nm = sys.argv[1] if len(sys.argv) > 1 else "c006"
p = load_profile(nm)


def classify_walls(msp, p):
    """按生产同款分派(recognize.recognize)。classifier='line' 的楼(如六教 c006)
    必须走 classify_line——用它之外的入口会得到完全错误的墙集(实测 c006 少一个数量级)。"""
    if getattr(p, "classifier", "lwpolyline") == "line":
        from backend.recognizer.classify_line import classify_line
        return classify_line(msp, p)
    from backend.recognizer import classify
    return classify.classify(msp, p)


import ezdxf
doc = ezdxf.readfile(p.dxf)
walls, doors, stairs, cols = classify_walls(doc.modelspace(), p)
print("== %s  classifier=%s  墙 %d / 门 %d / 楼梯 %d / 柱 %d =="
      % (nm, getattr(p, "classifier", "lwpolyline"), len(walls), len(doors), len(stairs), len(cols)))

floors = sorted({int(round(floor_of(p, sum(q[0] for q in w) / len(w), sum(q[1] for q in w) / len(w))))
                 for w in walls if len(w)})
print("  分类出的墙落在层: %s" % floors)
sub = unify_floor_set(p, floors)
print("  统一层集 = %s" % sorted(sub))

# 被测点(本地米): 两个塔的中心
TESTS = [(33.0, -36.0), (-33.0, -36.0), (27.0, -36.0), (-27.0, -36.0)]

print("\n  %-4s %-10s %-11s %-9s %-9s %-8s %s"
      % ("层", "折线数", "轮廓面积㎡", "轮廓顶点", "union块", "最大块%", "含塔点"))
for F in floors:
    tr = (p.transition or {}).get(F)
    wall_x = tr.get("wall_x") if tr else None
    wp = wall_pts_for_floor(F, walls, p, wall_x)
    o, wg, _x = derive_walls_and_outline(wp, p)
    oa = o.area if o is not None and not o.is_empty else 0.0
    ov = len(o.exterior.coords) if o is not None and not o.is_empty else 0
    U = unary_union([g for g in wg]) if wg else None
    nparts, bigshare = 0, 0.0
    if U is not None and not U.is_empty:
        gs = [U] if U.geom_type == "Polygon" else list(U.geoms)
        gs = [g for g in gs if g.area > 0.5]
        nparts = len(gs)
        ta = sum(g.area for g in gs)
        bigshare = (max(g.area for g in gs) / ta) if ta else 0.0
    if o is not None and not o.is_empty:
        inside = [("(%.0f,%.0f)" % t) for t in TESTS if o.contains(Point(*t))]
    else:
        inside = []
    print("  %-4d %-10d %-11.1f %-9d %-9d %-8.0f %s"
          % (F, len(wp), oa, ov, nparts, 100 * bigshare, " ".join(inside) or "无"))

ref_F, ref_o = reference_outline_for(p, walls, floors)
if ref_o is not None:
    print("\n  基准层 = %d, 基准轮廓面积 %.1f㎡" % (ref_F, ref_o.area))
    print("  基准轮廓含塔点: %s" % (["(%.0f,%.0f)" % t for t in TESTS if ref_o.contains(Point(*t))] or "无"))
