# -*- coding: utf-8 -*-
"""最终版参数探测：为每栋教学楼写 profile.json（含 x_range 主列隔离 + offset + cx/cy + 图层）。

算法：
  1. 墙层 LWPOLYLINE 顶点 → X 聚类(10000mm 阈值)得 X 列（>20m 宽才算列）
  2. 主列 = 楼层带数最多的列（并列取首个）
  3. 主列内 Y 聚类(30000mm 阈值)得楼层带 → offset = 相邻中心距中位数
  4. cx = 主列 X 中心；cy = 主列 0 层 Y 中心
  5. 柱层 = 名字含「柱」且 LWPOLYLINE>0 的最多者（无则空）
"""
import json
import os
import statistics
import sys
import ezdxf
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BUILDINGS = [
    ("c009", "C009-第九教学楼", "第九教学楼"),
    ("c022", "C022-第七教学楼（致远楼）", "第七教学楼（致远楼）"),
    ("c025", "C025-第一教学楼", "第一教学楼"),
    ("c026", "C026-第四教学楼", "第四教学楼"),
    ("c027", "C027-第三教学楼", "第三教学楼"),
    ("c028", "C028-第二教学楼", "第二教学楼"),
    ("c041", "C041-第八教学楼（学研楼）", "第八教学楼（学研楼）"),
    ("c103", "C103-第十一教学楼（东1教）", "第十一教学楼（东1教）"),
    ("c104", "C104-第十二教学楼（东2教）", "第十二教学楼（东2教）"),
    ("c114", "C114-第十教学楼（启智楼）", "第十教学楼（启智楼）"),
]
DXF_DIR = r"D:\dxf_output"
BUILD_DIR = r"D:\gym3d\data\buildings"

ALGO_DEFAULTS = {
    "door_min_points": 10, "stair_points": 5,
    "wall_min": 0.08, "wall_max": 0.35, "wall_extend": 0.15, "wall_fallback": 0.15,
    "door_w_single": 1.1, "door_w_double": 2.4, "door_depth": 0.5,
    "outline_buf": 0.15, "open_r": 0.35, "parapet_margin": 0.5,
    "layer_height": 4.2, "slab": 0.2,
}
WALL_KW = ("墙体", "4.2", "4墙", "4.3", "封墙")
COL_KW = ("结构柱", "4.1柱", "柱")


def cluster(vals, gap):
    v = sorted(set(round(x) for x in vals))
    if not v:
        return []
    bands = [[v[0]]]
    for x in v[1:]:
        if x - bands[-1][-1] > gap:
            bands.append([x])
        else:
            bands[-1].append(x)
    return bands


def detect(dxf_path, name, title):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    layer_etype = {}
    for e in msp:
        t = e.dxftype()
        lay = e.dxf.layer if hasattr(e.dxf, "layer") else "(none)"
        layer_etype.setdefault(lay, Counter())[t] += 1
    wall_layers = [l for l in layer_etype
                   if any(k in l for k in WALL_KW) and layer_etype[l].get("LWPOLYLINE", 0) > 0]
    wall_layer = max(wall_layers, key=lambda l: layer_etype[l]["LWPOLYLINE"]) if wall_layers else ""
    col_layers = [l for l in layer_etype
                  if any(k in l for k in COL_KW) and layer_etype[l].get("LWPOLYLINE", 0) > 0]
    column_layer = max(col_layers, key=lambda l: layer_etype[l]["LWPOLYLINE"]) if col_layers else ""

    pts = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wall_layer:
            pts += [tuple(p[:2]) for p in e.get_points()]
    if not pts:
        return {"error": "墙层无数据"}

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    # X 列
    xcols = [(min(b), max(b)) for b in cluster(xs, 10000) if (max(b) - min(b)) / 1000 > 20]
    if not xcols:
        xcols = [(min(xs), max(xs))]

    # 主列 = 楼层带数最多（Y 用 5000mm 阈值，楼间边距约 5~25m 也能分开）
    best_col, best_centers, best_n = None, [], -1
    for (x0, x1) in xcols:
        cy_vals = [y for x, y in pts if x0 <= x <= x1]
        yb = cluster(cy_vals, 5000)
        yw = [b for b in yb if (max(b) - min(b)) / 1000 > 10]
        if len(yw) > best_n:
            best_n = len(yw)
            best_col = (x0, x1)
            best_centers = [(min(b) + max(b)) / 2 for b in yw]

    x0, x1 = best_col
    gaps = [best_centers[i + 1] - best_centers[i] for i in range(len(best_centers) - 1)]
    big_gaps = [g for g in gaps if g > 15000]
    offset = round(statistics.median(big_gaps)) if big_gaps else None
    cx = round((x0 + x1) / 2, 1)
    cy = round(best_centers[0], 1)

    return {
        "name": name, "title": title, "dxf": dxf_path,
        "wall_layer": wall_layer, "column_layer": column_layer,
        "x_range": [round(x0), round(x1)], "x_cols": len(xcols),
        "offset": offset, "cx": cx, "cy": cy, "floor_centers": [round(c) for c in best_centers],
    }


for name, file, title in BUILDINGS:
    dxf = os.path.join(DXF_DIR, file + ".dxf")
    d = detect(dxf, name, title)
    if "error" in d:
        print(f"{name} | ERROR: {d['error']}")
        continue
    profile = dict(d)
    profile.pop("x_cols", None)
    profile.pop("floor_centers", None)
    profile["rooms"] = os.path.join(BUILD_DIR, name, "rooms.json")
    profile["out_dir"] = os.path.join(BUILD_DIR, name, "floors")
    profile.update(ALGO_DEFAULTS)
    os.makedirs(os.path.join(BUILD_DIR, name), exist_ok=True)
    with open(os.path.join(BUILD_DIR, name, "profile.json"), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=1)
    print(f"{name} | x_cols={d['x_cols']} x_range={d['x_range']} offset={d['offset']} "
          f"cx={d['cx']} cy={d['cy']} wall={d['wall_layer']!r} col={d['column_layer']!r} "
          f"floors={d['floor_centers']}")

print("\n完成。")
