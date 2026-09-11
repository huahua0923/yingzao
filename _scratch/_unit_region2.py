# -*- coding: utf-8 -*-
"""带洞用例的深挖：三角化面积对不对？网格闭不闭合？

有向体积是个「闭合才有意义」的量。若网格有开口，散度定理算出来的值还跟
原点位置有关 —— 所以 1/6 这种零头八成不是朝向问题，是**有洞没补上**。
这里逐项拆：earcut 铺出来的三角面积、每条边被几个面用到（1 次=边界洞）。
"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from glb_common import MeshBuilder, _triangulate  # noqa: E402

poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)],
               [[(.25, .25), (.75, .25), (.75, .75), (.25, .75)]])

tris = _triangulate(poly)
ar = sum(abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2.0
         for a, b, c in tris)
print("多边形面积 %.6f   earcut 三角总面积 %.6f   三角数 %d"
      % (poly.area, ar, len(tris)))
print("三角化是否填了洞 :", "**是（多出 %.6f）**" % (ar - poly.area) if abs(ar - poly.area) > 1e-9 else "否")

b = MeshBuilder()
b.add_region(poly, 0.0, 1.0, [200, 200, 200])
v = np.asarray(b.verts, dtype=float)
f = np.asarray(b.faces, dtype=int)
vol = float(np.einsum("ij,ij->i", v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])).sum() / 6.0)
print("面=%d 顶点=%d  有向体积 %.6f  期望 %.6f" % (len(f), len(v), vol, poly.area))

# 边流形性：每个无向边被几个三角形用到。闭合体每条边恰好 2 次。
# 用**坐标**而不是顶点下标做键 —— 新旧实现都会重复建顶点，下标不可比。
key = {}
for tri in f:
    pts = [tuple(np.round(v[i], 9)) for i in tri]
    for i in range(3):
        e = tuple(sorted((pts[i], pts[(i + 1) % 3])))
        key[e] = key.get(e, 0) + 1
cnt = Counter(key.values())
print("边的使用次数分布 :", dict(sorted(cnt.items())), "  (1 次=开口边)")
opens = [e for e, c in key.items() if c != 2]
print("非 2 次的边 %d 条" % len(opens))
for e in opens[:6]:
    print("    ", e)
