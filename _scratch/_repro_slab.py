# -*- coding: utf-8 -*-
"""最小复现：把 c114 F1 的楼板多边形摊开看，到底哪条边盖面和侧壁对不上。"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon, box  # noqa: E402
import glb_common as gc  # noqa: E402

B = r"D:\gym3d\data\buildings"
name = sys.argv[1] if len(sys.argv) > 1 else "c114"
fi = int(sys.argv[2]) if len(sys.argv) > 2 else 1
d = os.path.join(B, name)
fl = json.load(open(os.path.join(d, "floors", "floor%d.json" % fi),
                   encoding="utf-8"))

slab = Polygon(fl["outline"])
print("原始 outline: 外环 %d 点, 洞 %d 个"
      % (len(slab.exterior.coords) - 1, len(slab.interiors)))
for s in fl["stairwells"]:
    bx = box(s["x0"], s["yBot"], s["x1"], s["yTop"])
    slab = slab.difference(bx)
    print("  减去井 x[%.2f,%.2f] y[%.2f,%.2f] → %s 外环 %d 洞 %d"
          % (s["x0"], s["x1"], s["yBot"], s["yTop"], slab.geom_type,
             len(slab.exterior.coords) - 1, len(slab.interiors)))

print("slab.is_valid =", slab.is_valid)

for g in gc._clean(slab):
    print("-- _clean 后：外环 %d 点 洞 %d 个"
          % (len(g.exterior.coords) - 1, len(g.interiors)))
    print("   外环:", [(round(x, 3), round(y, 3)) for x, y in g.exterior.coords])
    for h in g.interiors:
        print("   洞  :", [(round(x, 3), round(y, 3)) for x, y in h.coords])

    # 盖面用到的边界边（只被 1 个三角形用的边）
    tris = gc._triangulate(g)
    from collections import Counter
    e = Counter()
    for tri in tris:
        pts = [tuple(round(c, 6) for c in p) for p in tri]
        for i in range(3):
            e[tuple(sorted((pts[i], pts[(i + 1) % 3])))] += 1
    capb = [k for k, v in e.items() if v == 1]
    print("   盖面边界边 %d 条" % len(capb))

    # 侧壁环用的边
    def ring_edges(coords):
        pts = [(float(x), float(y)) for x, y in coords]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        out = []
        for i in range(len(pts)):
            a = tuple(round(c, 6) for c in pts[i])
            b = tuple(round(c, 6) for c in pts[(i + 1) % len(pts)])
            out.append(tuple(sorted((a, b))))
        return out

    re_ = set(ring_edges(g.exterior.coords))
    for h in g.interiors:
        re_ |= set(ring_edges(h.coords))
    cs = set(capb)
    miss = re_ - cs
    extra = cs - re_
    print("   侧壁有、盖面没有 %d 条：" % len(miss))
    for k in list(miss)[:6]:
        print("      ", k)
    print("   盖面有、侧壁没有 %d 条：" % len(extra))
    for k in list(extra)[:6]:
        print("      ", k)
