# -*- coding: utf-8 -*-
"""快速验证窗-墙几何匹配判据（不建 GLB，秒级）。

正确性判据：**每个窗应恰好匹配 1 面墙**。
  · 匹配 0 面 → 窗悬空，墙上没洞（窗被埋进实心墙）
  · 匹配 >1 面 → 误伤邻墙（凹口伸 0.4m 判相交时就会这样）
顺带对比旧判据（凹口相交）在同一份数据上会误伤多少面。
"""
import glob
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon, Point  # noqa: E402
import build_standard_glb as bsg             # noqa: E402

S = bsg.load_spec()
TOL = bsg.NOTCH_TOL

print("NOTCH_TOL=%.2f  win_in_depth=%.2f  win_out=%.2f"
      % (TOL, S["win_in_depth"], S["win_out"]))
print()

for name in ("c116", "c019", "c006", "c046"):
    d = os.path.join(r"D:\gym3d\data\buildings", name, "floors")
    if not os.path.isdir(d):
        continue
    n0 = n1 = n_multi = 0
    old_multi = 0
    worst = 0
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json"))):
        fl = json.load(open(fp, encoding="utf-8"))
        walls = [w for w in (fl.get("walls") or []) if w.get("type") != "parapet"]
        wins = fl.get("windows") or []
        if not wins:
            continue
        polys = [Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4])
                 for w in walls]
        bounds = [p.bounds for p in polys]
        for win in wins:
            half = win["w"] / 2.0
            pt = Point(win["x"], win["y"])
            pb = (win["x"] - half, win["y"] - half, win["x"] + half, win["y"] + half)
            notch = bsg.window_notch(win, S)
            hit_new = hit_old = 0
            for p, wb in zip(polys, bounds):
                if not bsg._bbox_hit(wb, pb) and not bsg._bbox_hit(wb, notch.bounds):
                    continue
                if bsg._bbox_hit(wb, pb) and p.distance(pt) <= TOL:
                    hit_new += 1
                if bsg._bbox_hit(wb, notch.bounds) and p.intersects(notch):
                    hit_old += 1
            if hit_new == 0:
                n0 += 1
            elif hit_new == 1:
                n1 += 1
            else:
                n_multi += 1
            if hit_old > 1:
                old_multi += 1
            worst = max(worst, hit_old)

    tot = n0 + n1 + n_multi
    print("%-6s 窗 %4d | 新判据: 恰1面 %4d (%.1f%%)  悬空 %d  误伤 %d"
          % (name, tot, n1, 100.0 * n1 / tot if tot else 0, n0, n_multi))
    print("        旧判据(凹口相交): 误伤多面的窗 %d 个，单窗最多命中 %d 面"
          % (old_multi, worst))
