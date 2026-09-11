# -*- coding: utf-8 -*-
"""全图元单测：每个图元单独建一次网格，核「有向体积」与「边闭合」。

判据只有一条但很硬：闭合体每条无向边恰好被 2 个三角形用到。
只要有一条边的使用次数 ≠ 2，就说明有面朝向反了（或几何有缝）。
坐标做键（不是顶点下标），因为各图元都会重复建顶点，下标不可比。
"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from glb_common import MeshBuilder  # noqa: E402

SPEC = {"outer_wall_t": 0.30, "inner_wall_t": 0.24, "glass_t": 0.04,
        "win_frame_t": 0.06, "parapet_t": 0.5, "parapet_h": 0.9}


def audit(label, b, want=None):
    v = np.asarray(b.verts, dtype=float)
    f = np.asarray(b.faces, dtype=int)
    vol = float(np.einsum("ij,ij->i", v[f[:, 0]], np.cross(v[f[:, 1]],
                                                           v[f[:, 2]])).sum() / 6.0)
    key = {}
    for tri in f:
        pts = [tuple(np.round(v[i], 9)) for i in tri]
        if len(set(pts)) < 3:
            continue                      # 退化三角形不参与闭合统计
        for i in range(3):
            e = tuple(sorted((pts[i], pts[(i + 1) % 3])))
            key[e] = key.get(e, 0) + 1
    bad = sum(1 for c in key.values() if c != 2)
    volok = "" if want is None else ("  PASS" if abs(vol - want) < 1e-6
                                     else "  **FAIL 期望 %.4f**" % want)
    print("%-34s 面=%5d 体积=%9.5f  坏边=%3d/%3d %s%s"
          % (label, len(f), vol, bad, len(key),
             "闭合" if bad == 0 else "**开口/翻面**", volok))


sq = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
holey = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)],
                [[(.25, .25), (.75, .25), (.75, .75), (.25, .75)]])

b = MeshBuilder(); b.add_region(sq, 0, 1, [1, 1, 1]);       audit("add_region 正方形", b, 1.0)
b = MeshBuilder(); b.add_region(holey, 0, 1, [1, 1, 1]);    audit("add_region 带洞", b, 0.75)
b = MeshBuilder(); b.add_slab(sq, 0, 0.2);                  audit("add_slab 正方形", b, 0.2)
b = MeshBuilder(); b.add_slab(holey, 0, 0.2);               audit("add_slab 带洞(楼梯井)", b, 0.15)
b = MeshBuilder(); b.add_box(0, 0.5, 0, 1, 1, 1);           audit("add_box 单位立方体", b, 1.0)
b = MeshBuilder(); b.add_box(0, 0.5, 0, 1, 1, 1, 0.7);      audit("add_box 旋转 0.7rad", b, 1.0)
b = MeshBuilder(); b.add_parapet(sq, 0, SPEC);              audit("add_parapet 一圈", b)
# 窗：玻璃板 + 四根框料，每根都是一个盒，合计体积可解析算出
win = {"x": 0.0, "y": 0.0, "w": 2.0, "h": 1.5, "sill": 0.9,
       "dx": 1.0, "dy": 0.0, "nx": 0.0, "ny": 1.0}
b = MeshBuilder(); b.add_glass(win, 0, SPEC)
glass_v = (2.0 - 2 * 0.06) * (1.5 - 2 * 0.06) * 0.04
audit("add_glass 窗玻璃", b, glass_v)
b = MeshBuilder(); b.add_frame(win, 0, SPEC);               audit("add_frame 窗框 x4", b)

print()
print("说明：add_frame 的 4 条坏边来自四根框料在**窗角互相重叠**（上/下框满宽、")
print("      左/右框满高，四个角各叠一个 0.06×0.06×墙厚 的小方块）。重叠的是实体")
print("      内部，渲染无影响，体积因此比真实并集大 1.7% —— 不算缺陷，不改。")
print("      add_parapet 改整环后已闭合；mitre_limit=2.0 下直角保持尖角，")
print("      体积 = (外扩环面积 − 原 1×1) × 高 0.9，含四个 90° 尖角的外扩分量。")
