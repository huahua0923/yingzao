# -*- coding: utf-8 -*-
"""逐面算体积贡献，把「哪个面不对」钉死。

V = (1/6) Σ a·(b×c)，每个三角形贡献一个带符号的四面体体积。
打印 32 个面里贡献最大的几条，连同它的法线指向和所在高度。
"""
import sys

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from glb_common import MeshBuilder  # noqa: E402

poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)],
               [[(.25, .25), (.75, .25), (.75, .75), (.25, .75)]])

b = MeshBuilder()
b.add_region(poly, 0.0, 1.0, [200, 200, 200])
v = np.asarray(b.verts, dtype=float)
f = np.asarray(b.faces, dtype=int)

contrib = np.einsum("ij,ij->i", v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])) / 6.0
print("总面数 %d   有向体积合计 %.6f" % (len(f), contrib.sum()))

# 每个面的几何法线（右手定则），y 分量 >0 朝上、<0 朝下、≈0 竖直
nrm = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
area = np.linalg.norm(nrm, axis=1) / 2.0
print("\n竖直面（法线接近水平）里，朝内/朝外的分布：")
cx = (v[f[:, 0]] + v[f[:, 1]] + v[f[:, 2]]) / 3.0
outside = np.array([0.5, 0.5, -0.5])       # 实体外的一点（世界系质心方向）
vertical = area > 1e-9
# 只用几何法线判断不了内外，直接看贡献值最省事
order = np.argsort(-np.abs(contrib))
print("\n贡献最大的 10 个面（面积 / 法线 / 贡献）：")
for i in order[:10]:
    print("  面积%7.4f  法线(%6.3f,%6.3f,%6.3f)  贡献 %+8.5f  顶点 %s"
          % (area[i], nrm[i][0], nrm[i][1], nrm[i][2], contrib[i],
             [tuple(np.round(p, 3)) for p in v[f[i]]]))
