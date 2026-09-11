# -*- coding: utf-8 -*-
"""c006 为何 392 个窗命中多面墙？区分两种可能：

  A) 同一道墙被切成了几段共线段 → 多命中无害（都该挖，窗跨在断口上）
  B) 相邻的平行墙             → 真误伤（会在邻墙上开洞）

判据：看多命中那几面墙的「形心距离」和「墙厚」。
  共线段 → 形心很近(≈窗在段内的位置)、墙厚相同、且各段互相共线
  平行墙 → 形心距离≈墙间距(0.2~5m)、方向平行但位置不同
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
D = r"D:\gym3d\data\buildings\c006\floors"

thick = []
cases = []
for fp in sorted(glob.glob(os.path.join(D, "floor*.json"))):
    fl = json.load(open(fp, encoding="utf-8"))
    walls = [w for w in (fl.get("walls") or []) if w.get("type") != "parapet"]
    wins = fl.get("windows") or []
    polys = [Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4])
             for w in walls]
    bounds = [p.bounds for p in polys]
    areas = [p.area for p in polys]
    for win in wins:
        half = win["w"] / 2.0
        pt = Point(win["x"], win["y"])
        pb = (win["x"] - half, win["y"] - half, win["x"] + half, win["y"] + half)
        hits = []
        for i, (p, wb) in enumerate(zip(polys, bounds)):
            if bsg._bbox_hit(wb, pb) and p.distance(pt) <= TOL:
                hits.append(i)
        if len(hits) > 1:
            ds = [polys[i].distance(polys[j])
                  for a, i in enumerate(hits) for j in hits[a + 1:]]
            cases.append((len(hits), min(ds), [round(areas[i], 3) for i in hits],
                          [round(bounds[i][0], 2) for i in hits]))

print("c006 多命中窗 %d 个" % len(cases))
print("%-6s %-10s %s" % ("命中数", "墙间最小距(m)", "各命中墙面积(m²) 与 xmin"))
uniq = {}
for n, dmin, ar, bx in cases:
    uniq.setdefault((n, round(dmin, 2)), 0)
    uniq[(n, round(dmin, 2))] += 1
for (n, dmin), c in sorted(uniq.items(), key=lambda kv: -kv[1])[:12]:
    print("  %-6d %-12.3f 出现 %d 次" % (n, dmin, c))

print()
touching = [c for c in cases if c[1] < 0.01]
apart = [c for c in cases if c[1] >= 0.01]
print("互相接触/重叠(共线分段或贴邻) %d 个 | 有间隙 %d 个"
      % (len(touching), len(apart)))
if apart:
    print("有间隙的样例（前5）:")
    for n, dmin, ar, bx in sorted(apart, key=lambda c: -c[1])[:5]:
        print("   命中%d 面 间距%.3fm 面积%s xmin%s" % (n, dmin, ar, bx))
