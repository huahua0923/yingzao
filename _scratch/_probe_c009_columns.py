# -*- coding: utf-8 -*-
"""c009 是否「首层平面画在另一列」(只读)。

_probe_c009_raw 显示: 首层墙层只有 145 条 LWPOLYLINE(1~5 层各 759~888), 但全图有
2484 条 LWPOLYLINE 落在 x_range 之外。怀疑首层平面画在另一个 X 列, 而 c009 没有
floor_plans(只有单个 x_range), 于是那一列被整体裁掉 → 首层只剩零星内容。

本探针不套 x_range, 把墙层实体按 (层, X 列) 计数。X 列用 120m 栅格聚类。
"""
import sys, os, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from run_building import load_profile
from backend.recognizer.profile import floor_of

nm = sys.argv[1] if len(sys.argv) > 1 else "c009"
p = load_profile(nm)
doc = ezdxf.readfile(p.dxf)
print("== %s  x_range=%s  offset=%s  cy=%s ==" % (nm, p.x_range, p.offset, p.cy))

COL = 120000.0   # 120m 一列
cells = collections.Counter()
xmin_all, xmax_all = None, None
for e in doc.modelspace():
    if e.dxf.layer != p.wall_layer or e.dxftype() != "LWPOLYLINE":
        continue
    q = list(e.get_points("xyseb"))
    if not q:
        continue
    xs = [float(a[0]) for a in q]
    ys = [float(a[1]) for a in q]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    xmin_all = cx if xmin_all is None else min(xmin_all, cx)
    xmax_all = cx if xmax_all is None else max(xmax_all, cx)
    F = int(round(floor_of(p, cx, cy)))
    cells[(F, int(cx // COL))] += 1

cols = sorted({c for (f, c) in cells})
print("  图幅 X 跨度: %.0f .. %.0f m (%.0f m 宽)" % (xmin_all / 1000, xmax_all / 1000,
                                                  (xmax_all - xmin_all) / 1000))
print("  列(X栅格 %dm) 起点(m): %s" % (COL / 1000, [int(c) for c in cols]))
xl = p.x_range
print("\n  %-4s %s" % ("层", " ".join("%-18s" % ("列@%dm" % (c * COL / 1000)) for c in cols)))
for F in sorted({f for (f, c) in cells}):
    row = []
    for c in cols:
        n = cells.get((F, c), 0)
        lo, hi = c * COL, (c + 1) * COL
        inx = xl and not (hi < xl[0] or lo > xl[1])
        row.append("%-18s" % ("%d%s" % (n, " ←x_range内" if inx else "")))
    print("  %-4d %s" % (F, " ".join(row)))
print("\n  注: 同一列里某层实体数远高于其他层 = 该层平面单独画在一列")
