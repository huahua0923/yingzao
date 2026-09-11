# -*- coding: utf-8 -*-
"""把某个 GLB 的**开边**按位置聚类打出来，好判断是哪类图元漏了面。

开边 = 只被 1 个三角形用到的无向边。打印每条开边的中点坐标，
再按楼层高度分段统计，就能看出是墙、女儿墙还是窗框。

用法：python _scratch/_diag_open_pos.py c103
"""
import json
import os
import sys
from collections import Counter

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"


def load(name):
    raw = open(os.path.join(B, name, "%s-building.glb" % name), "rb").read()
    jlen = int.from_bytes(raw[12:16], "little")
    js = json.loads(raw[20:20 + jlen].decode("utf-8"))
    boff = 20 + jlen + 8
    pos, idx, name_of = [], [], []
    for m in js.get("meshes", []):
        for pr in m["primitives"]:
            acc = js["accessors"][pr["attributes"]["POSITION"]]
            bv = js["bufferViews"][acc["bufferView"]]
            st = boff + bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            n = acc["count"]
            a = np.frombuffer(raw, dtype="<f4", count=n * 3, offset=st)
            pos.append(a.reshape(n, 3).astype(np.float64))
            if "indices" in pr:
                ia = js["accessors"][pr["indices"]]
                ibv = js["bufferViews"][ia["bufferView"]]
                ist = boff + ibv.get("byteOffset", 0) + ia.get("byteOffset", 0)
                dt = {5121: "<u1", 5123: "<u2", 5125: "<u4"}[ia["componentType"]]
                f = np.frombuffer(raw, dtype=dt, count=ia["count"],
                                  offset=ist).astype(np.int64).reshape(-1, 3)
                idx.append(f)
                name_of += [m.get("name", "?")] * len(f)
    return np.concatenate(pos), np.concatenate(idx), name_of


for name in sys.argv[1:]:
    V, F, mn = load(name)
    qi = np.round(np.round(V, 5) * 1e5).astype(np.int64)
    tri = qi[F]
    key = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]),
                  axis=1)
    uniq, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    openmask = cnt == 1
    owner = np.array(mn)[np.repeat(np.arange(len(F)), 3)[:len(inv)]] if len(inv) == 3 * len(F) else None
    print("== %s  开边 %d / %d" % (name, int(openmask.sum()), len(uniq)))
    oe = uniq[openmask]
    if not len(oe):
        continue
    pts = oe.astype(np.float64) / 1e5          # (N, 2, 3)：端点对
    a, b_ = pts[:, 0], pts[:, 1]
    mid = (a + b_) / 2.0
    print("   开边中点范围 x[%.2f,%.2f] y[%.2f,%.2f] z[%.2f,%.2f]"
          % (mid[:, 0].min(), mid[:, 0].max(), mid[:, 1].min(), mid[:, 1].max(),
             mid[:, 2].min(), mid[:, 2].max()))
    h = 4.2
    seg = Counter(np.floor((mid[:, 2] - 0) / h).astype(int))
    print("   按层高 4.2 分段（floor0=0~4.2）:",
          dict(sorted(seg.items())[:20]))
    # 竖直边（两个端点只有 y 不同）= 竖直缝；水平边 = 上下盖面漏
    d = np.abs(a - b_)
    vert = (d[:, 1] > 1e-6) & (d[:, 0] < 1e-6) & (d[:, 2] < 1e-6)
    horiz = (d[:, 1] < 1e-6)
    print("   竖直边 %d  水平边 %d  斜/其他 %d"
          % (int(vert.sum()), int(horiz.sum()), int(len(oe) - vert.sum() - horiz.sum())))
    print("   样例 5 条（端点）：")
    for pa, pb in zip(a[:5], b_[:5]):
        print("      (%.3f, %.3f, %.3f) → (%.3f, %.3f, %.3f)"
              % (pa[0], pa[1], pa[2], pb[0], pb[1], pb[2]))
