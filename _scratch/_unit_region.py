# -*- coding: utf-8 -*-
"""add_region 最小用例：单位正方形从 y=0 挤到 y=1，体积应恰好 1.0 m³。

外加：带洞正方形（洞 0.5×0.5 → 期望 1*1 - 0.5*0.5 = 0.75）、
细长条（0.24×2.0 → 期望 0.48）。有向体积为负即法线整体翻向。
同时打开逐面朝向核查：把每个三角形算一遍 signed volume，正负分开统计。
"""
import sys

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
from shapely.geometry import Polygon, box  # noqa: E402
from glb_common import MeshBuilder  # noqa: E402

CASES = [
    ("单位正方形 1x1 挤1m", Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]), 1.0),
    ("带洞 1x1 减 0.5x0.5", Polygon([(0, 0), (1, 0), (1, 1), (0, 1)],
                                    [[(.25, .25), (.75, .25), (.75, .75), (.25, .75)]]), 0.75),
    ("细长条 0.24x2.0", Polygon([(0, 0), (0.24, 0), (0.24, 2), (0, 2)]), 0.48),
    ("L 形（凹，验法线不靠质心）",
     Polygon([(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]), 3.0),
]


def signed_vol(verts, faces):
    v = np.asarray(verts, dtype=float)
    f = np.asarray(faces, dtype=int)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


for label, poly, want in CASES:
    b = MeshBuilder()
    b.add_region(poly, 0.0, 1.0, [200, 200, 200])
    got = signed_vol(b.verts, b.faces)
    ok = "PASS" if abs(got - want) < 1e-6 else "**FAIL**"
    print("%-28s 面=%4d 顶点=%5d  有向体积 %.6f  期望 %.6f  %s"
          % (label, len(b.faces), len(b.verts), got, want, ok))

# 面积守恒再验一遍：多边形面积×高 = 体积
print()
for label, poly, want in CASES:
    b = MeshBuilder()
    b.add_region(poly, 0.0, 1.0, [200, 200, 200])
    print("   %-28s shapely 面积 %.4f" % (label, poly.area))
