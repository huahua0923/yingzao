# -*- coding: utf-8 -*-
"""c009 主楼列(X 在 x_range 内)的墙实体 Y 分布直方图(只读)。

目的: 判断「首层只有 145 条墙线」到底是
  (a) 每一层平面各有自己的 Y 带, 只是首层那条带内容确实少; 还是
  (b) 图纸上有 6 条 Y 带, 但首层平面画在别处, 它那条带被别的东西占了。
按 offset(层间距) 切带, 统计每条带的实体数 / X 跨度 / Y 跨度。
"""
import sys, os, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from run_building import load_profile
from backend.recognizer.profile import floor_of, to_local, in_floor_x_range

nm = sys.argv[1] if len(sys.argv) > 1 else "c009"
p = load_profile(nm)
doc = ezdxf.readfile(p.dxf)
print("== %s  offset=%.0fmm cy=%.0fmm x_range=%s ==" % (nm, p.offset, p.cy, p.x_range))

per = collections.defaultdict(list)
for e in doc.modelspace():
    if e.dxf.layer != p.wall_layer or e.dxftype() != "LWPOLYLINE":
        continue
    q = list(e.get_points("xyseb"))
    if not q:
        continue
    xs = [float(a[0]) for a in q]
    ys = [float(a[1]) for a in q]
    cx = (min(xs) + max(xs)) / 2.0
    cyv = (min(ys) + max(ys)) / 2.0
    if not in_floor_x_range(p, cx):
        continue
    F = int(round(floor_of(p, cx, cyv)))
    per[F].append((cx, cyv))

print("\n  %-4s %-8s %-26s %-26s %s" % ("层", "实体数", "原始X范围(m)", "原始Y范围(m)", "层中心Y(m)"))
for F in sorted(per):
    v = per[F]
    xs = [a for a, b in v]
    ys = [b for a, b in v]
    fy = (F * p.offset + p.cy) / 1000.0
    print("  %-4d %-8d [%7.1f, %7.1f] 跨%6.1f   [%7.1f, %7.1f] 跨%6.1f   %7.1f"
          % (F, len(v), min(xs) / 1000, max(xs) / 1000, (max(xs) - min(xs)) / 1000,
             min(ys) / 1000, max(ys) / 1000, (max(ys) - min(ys)) / 1000, fy))

# 全部实体的原始 Y 直方图(不套 floor_of), 看有几条带
ally = sorted(b for F in per for a, b in per[F])
print("\n  -- 全部墙实体原始 Y 分布(20m 一档, 只列有内容的档) --")
h = collections.Counter(int(b // 20000.0) * 20 for b in ally)
for k in sorted(h):
    print("     Y ~%5d m: %4d  %s" % (k, h[k], "#" * min(60, h[k] // 10)))
