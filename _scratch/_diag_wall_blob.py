# -*- coding: utf-8 -*-
"""量化「墙融合块」：单墙面积占楼层面积的比值。

背景（来自既有诊断）：单线墙被按默认 lwpolyline 缓冲成整层大块，
一块能占楼板面积 20~30%，渲染出来是实心疙瘩，也是本次 GLB 体积暴涨的根源。
c006 已做过薄墙化（平均 8 顶点/墙），拿它当健康基准。

判据：
  · 单墙最大面积 / 楼层面积 < 5%  → 健康（真墙是一条一条的）
  · 出现 >15% 的巨块              → 该层仍有未解融的融合块
"""
import glob
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon  # noqa: E402

B = r"D:\gym3d\data\buildings"


def area(poly):
    try:
        p = Polygon(poly)
        return p.area if p.is_valid else p.buffer(0).area
    except Exception:
        return 0.0


print("%-6s %6s %8s %10s %12s %10s" %
      ("楼栋", "层数", "墙均顶点", "最大墙顶点", "单墙最大占比", "巨块(>15%)层数"))
for name in ("c006", "c018", "c116", "c046", "c054", "c055", "c056",
             "c044", "c045", "c060", "c109", "c019", "c017"):
    d = os.path.join(B, name, "floors")
    if not os.path.isdir(d):
        continue
    rows = []
    blob_floors = 0
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json"))):
        fl = json.load(open(fp, encoding="utf-8"))
        slab = area(fl["outline"])
        walls = fl.get("walls") or []
        if not walls or slab <= 0:
            continue
        verts = [len(w.get("poly") or []) for w in walls]
        areas = [area(w["poly"]) for w in walls]
        mx_a = max(areas) if areas else 0
        frac = mx_a / slab
        rows.append((sum(verts) / len(verts), max(verts), frac))
        if frac > 0.15:
            blob_floors += 1
    if not rows:
        continue
    print("%-6s %6d %8.1f %10d %11.1f%% %10d/%d"
          % (name, len(rows),
             sum(r[0] for r in rows) / len(rows),
             max(r[1] for r in rows),
             100 * max(r[2] for r in rows),
             blob_floors, len(rows)))
