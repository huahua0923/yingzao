# -*- coding: utf-8 -*-
"""隔离测 glb_common 的构面吞吐：不碰交付目录，纯内存建 2 万个三角柱计时。

给出「面/秒」这个基准数，用来判断 c116 的 18 分钟是正常的还是病态的。
另附一个「缓存版 quad」的对照，量化 numpy 逐次建数组的开销占比。
"""
import sys
import time

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                     # noqa: E402
import glb_common as gc                # noqa: E402


class B(gc.MeshBuilder):
    """原版，一字不改。"""


class Cached(B):
    """对照：用 float 三元组直接算，不建 numpy 数组。"""

    def quad(self, a, b, c, d, n, col):
        v = self.verts
        p0, p1, p2 = v[a], v[b], v[c]
        cr = ((p1[1] - p0[1]) * (p2[2] - p0[2]) - (p1[2] - p0[2]) * (p2[1] - p0[1]),
              (p1[2] - p0[2]) * (p2[0] - p0[0]) - (p1[0] - p0[0]) * (p2[2] - p0[2]),
              (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]))
        if cr[0] * n[0] + cr[1] * n[1] + cr[2] * n[2] < 0:
            b, c = c, b
        self.faces.append([a, b, c])
        self.faces.append([a, c, d])

    def tri_f(self, a, b, c, n, col):
        v = self.verts
        p0, p1, p2 = v[a], v[b], v[c]
        cr = ((p1[1] - p0[1]) * (p2[2] - p0[2]) - (p1[2] - p0[2]) * (p2[1] - p0[1]),
              (p1[2] - p0[2]) * (p2[0] - p0[0]) - (p1[0] - p0[0]) * (p2[2] - p0[2]),
              (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]))
        if cr[0] * n[0] + cr[1] * n[1] + cr[2] * n[2] < 0:
            b, c = c, b
        self.faces.append([a, b, c])


N = 20000
for cls in (B, Cached):
    b = cls()
    t = time.time()
    for k in range(N):
        x = (k % 100) * 3.0
        y = (k // 100) * 3.0
        b.add_prism((x, y), (x + 2, y), (x + 1, y + 2), 0.0, 3.0, [200, 180, 160])
    d = time.time() - t
    # 每个三角柱 = 顶1 + 底1 + 侧3×2 = 8 个三角形
    print("%-8s %d 个三角柱 = %d 面  用时 %.2fs → %.0f 面/秒"
          % (cls.__name__, N, N * 8, d, N * 8 / d))
