# -*- coding: utf-8 -*-
"""把一栋楼每个环节分别建到独立 MeshBuilder 里，各自核闭合，定位开边来源。

用法：python _scratch/_isolate_open.py c114
"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
import build_standard_glb as bsg  # noqa: E402
from glb_common import MeshBuilder  # noqa: E402

B = r"D:\gym3d\data\buildings"


def open_edges(b):
    if not b.faces:
        return 0, 0
    v = np.asarray(b.verts, dtype=float)
    f = np.asarray(b.faces, dtype=int)
    qi = np.round(np.round(v, 5) * 1e5).astype(np.int64)
    tri = qi[f]
    key = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]),
                  axis=1)
    uniq, cnt = np.unique(key, axis=0, return_counts=True)
    return int((cnt == 1).sum()), len(uniq)


name = sys.argv[1]
d = os.path.join(B, name)
S = json.load(open(os.path.join(d, "spec.json"), encoding="utf-8"))
bsg.DATA = d
floors = bsg.load_floors()
st = S.get("style", {})
wall_col = bsg.hex_to_rgb(st.get("facade"))
inner_col = bsg.hex_to_rgb(st.get("inner"))
roof_col = bsg.hex_to_rgb(st.get("roof"))
parapet_col = bsg.hex_to_rgb(st.get("parapet") or st.get("roof"))
door_col = bsg.hex_to_rgb(st.get("door") or "#8a5a38")

STEPS = [
    ("slab", lambda b, fl, z, top: bsg.build_slab(b, fl, z, S)),
    ("rooms", lambda b, fl, z, top: bsg.build_rooms(b, fl, z, S)),
    ("walls", lambda b, fl, z, top: bsg.build_walls(b, fl, z, S, wall_col,
                                                    inner_col, roof_col)),
    ("doors", lambda b, fl, z, top: bsg.build_doors(b, fl, z, S, wall_col,
                                                    inner_col, door_col)),
    ("columns", lambda b, fl, z, top: bsg.build_columns(b, fl, z, S)),
    ("stairs", lambda b, fl, z, top: bsg.build_indoor_stairs(b, fl, z, S, top)),
]

top = max(f["floor"] for f in floors)
for i, fl in enumerate(floors):
    z = i * S["floor_h"]
    is_top = fl["floor"] == top
    for label, fn in STEPS:
        b = MeshBuilder()
        try:
            fn(b, fl, z, is_top)
        except Exception as e:                              # noqa: BLE001
            print("F%-2s %-8s 炸了 %s" % (fl["floor"], label, e))
            continue
        oe, tot = open_edges(b)
        if oe:
            print("F%-2s %-8s 面=%6d 开边=%4d/%6d  <== 有问题"
                  % (fl["floor"], label, len(b.faces), oe, tot))

# 屋顶三件套
for label, fn in (("roof_slab", lambda b: b.add_slab(
        bsg.Polygon(floors[-1]["outline"]), len(floors) * S["floor_h"],
        S["roof_t"], roof_col)),
                  ("parapet", lambda b: b.add_parapet(
        bsg.Polygon(floors[-1]["outline"]), len(floors) * S["floor_h"], S,
        parapet_col))):
    b = MeshBuilder()
    fn(b)
    oe, tot = open_edges(b)
    if oe:
        print("屋顶   %-8s 面=%6d 开边=%4d/%6d  <== 有问题"
              % (label, len(b.faces), oe, tot))
print("（只列有问题项）")
