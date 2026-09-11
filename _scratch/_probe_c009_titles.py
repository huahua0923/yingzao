# -*- coding: utf-8 -*-
"""读 c009 图纸上各列的标题文字, 定出「哪一列是哪层平面」(只读)。

依据用户的原则: 图纸自带层数标注, 应当读图而不是猜。c009 图幅宽 1626m、含多列,
x_range 只圈住一列, 导致首层平面被裁掉。这里把图上的 TEXT/MTEXT 按 X 列聚类,
挑出含「层/平面/图/剖面/立面」的标题, 给出「列 -> 标题」映射与推荐 floor_plans。

用法: python _probe_c009_titles.py [c009]
"""
import sys, os, collections, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from run_building import load_profile

nm = sys.argv[1] if len(sys.argv) > 1 else "c009"
p = load_profile(nm)
doc = ezdxf.readfile(p.dxf)
print("== %s  墙层=%r  x_range=%s ==" % (nm, p.wall_layer, p.x_range))

KEY = re.compile(r"(层|平面|剖面|立面|总平|屋顶|地下|夹层|机房|楼梯|图)")
COL = 120000.0

rows = []
for e in doc.modelspace():
    t = e.dxftype()
    if t not in ("TEXT", "MTEXT"):
        continue
    try:
        txt = (e.dxf.text if t == "TEXT" else e.text).strip()
        ins = e.dxf.insert
        x, y = float(ins.x), float(ins.y)
    except Exception:
        continue
    if not txt or not KEY.search(txt):
        continue
    rows.append((int(x // COL), x, y, e.dxf.layer, txt))

print("  命中标题类文字 %d 条" % len(rows))
bycol = collections.defaultdict(list)
for c, x, y, lay, txt in rows:
    bycol[c].append((x, y, lay, txt))

for c in sorted(bycol):
    xs = [r[0] for r in bycol[c]]
    ys = [r[1] for r in bycol[c]]
    print("\n  --- 列@%dm  (x %.0f..%.0f m, y %.0f..%.0f m, 标题 %d 条) ---"
          % (c * COL / 1000, min(xs) / 1000, max(xs) / 1000,
             min(ys) / 1000, max(ys) / 1000, len(bycol[c])))
    seen = set()
    for x, y, lay, txt in sorted(bycol[c], key=lambda r: -r[1])[:14]:
        k = txt[:40]
        if k in seen:
            continue
        seen.add(k)
        print("      (%8.1f,%8.1f) %-14s %s" % (x / 1000, y / 1000, lay, txt[:60]))
