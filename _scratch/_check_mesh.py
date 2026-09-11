# -*- coding: utf-8 -*-
"""交付 GLB 的网格体检：闭合性 + 有向体积 + 包围盒。

**闭合性才是硬指标**：闭合实体每条无向边恰好被 2 个三角形用到。老交付件里
quad() 的翻面 bug 会让同一张四边形劈出两个朝向相反的面，那些面在体积上互相
抵消、在渲染上有一半朝里 —— 只看「能打开、面数正常」是发现不了的。
这里用坐标（取整到微米）而不是顶点下标做边的键：导出时顶点是重复建的，
下标天然不相等，用了会得出「全是开口边」的假阳性。

用法：python _check_mesh.py <glb> [<glb> ...]
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import trimesh  # noqa: E402


def edge_counts(v, f):
    pts = np.round(v, 6)
    a = f[:, [0, 1, 2]]
    b = f[:, [1, 2, 0]]
    e = np.stack([pts[a], pts[b]], axis=2).reshape(-1, 2, 3)
    k0, k1 = e[:, 0], e[:, 1]
    less = ((k0[:, 0] < k1[:, 0])
            | ((k0[:, 0] == k1[:, 0])
               & ((k0[:, 1] < k1[:, 1])
                  | ((k0[:, 1] == k1[:, 1]) & (k0[:, 2] < k1[:, 2])))))
    first = np.where(less[:, None], k0, k1)
    second = np.where(less[:, None], k1, k0)
    key = np.ascontiguousarray(np.concatenate([first, second], axis=1))
    _, cnt = np.unique(key, axis=0, return_counts=True)
    return cnt


for path in sys.argv[1:]:
    m = trimesh.load(path, force="mesh", process=False)
    v = np.asarray(m.vertices, dtype=float)
    f = np.asarray(m.faces, dtype=int)
    vol = float(np.einsum("ij,ij->i", v[f[:, 0]],
                          np.cross(v[f[:, 1]], v[f[:, 2]])).sum() / 6.0)
    cnt = edge_counts(v, f)
    used1 = int((cnt == 1).sum())
    other = int((cnt > 2).sum())
    lo, hi = m.bounds
    print("=== %s" % os.path.basename(path))
    print("  字节 %.1f MB   三角面 %d   顶点 %d"
          % (os.path.getsize(path) / 1048576.0, len(f), len(v)))
    print("  有向体积 %.1f m³    bbox %s -> %s"
          % (vol, [round(x, 2) for x in lo], [round(x, 2) for x in hi]))
    print("  边总数 %d   只用 1 次(开口) %d (%.3f%%)   用了 >2 次(重叠) %d"
          % (len(cnt), used1, 100.0 * used1 / len(cnt), other))
    print("  闭合性 :", "PASS 全闭合" if used1 == 0 and other == 0
          else ("**开口 %.3f%%**" % (100.0 * used1 / len(cnt))))
