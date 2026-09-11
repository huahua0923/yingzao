# -*- coding: utf-8 -*-
"""11 栋教学楼侦查：实体类型分布 / 图层 / LWPOLYLINE&LINE 的 Y 聚类(楼层+OFFSET) / 中心。
只输出写 BuildingProfile 需要的关键字段，供后续分组+派子代理建模。"""
import os
import sys
import ezdxf
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DXF_DIR = r"D:\dxf_output"
BUILDINGS = [
    "C006-第六教学楼（逸夫楼）",
    "C009-第九教学楼",
    "C022-第七教学楼（致远楼）",
    "C025-第一教学楼",
    "C026-第四教学楼",
    "C027-第三教学楼",
    "C028-第二教学楼",
    "C041-第八教学楼（学研楼）",
    "C103-第十一教学楼（东1教）",
    "C104-第十二教学楼（东2教）",
    "C114-第十教学楼（启智楼）",
]


def y_clusters(ys, gap=5000):
    """Y(mm) 排序去重后按 gap 聚类，返回每簇中心 + 相邻间距。"""
    wy = sorted(set(round(y) for y in ys))
    if not wy:
        return [], []
    clusters = [[wy[0]]]
    for y in wy[1:]:
        if y - clusters[-1][-1] > gap:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    centers = [sum(c) / len(c) for c in clusters]
    gaps = [round(centers[i + 1] - centers[i]) for i in range(len(centers) - 1)]
    return centers, gaps


for name in BUILDINGS:
    path = os.path.join(DXF_DIR, name + ".dxf")
    if not os.path.exists(path):
        print(f"\n===== {name}  [DXF 缺失] =====")
        continue
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    etypes = Counter()
    layers = Counter()
    layer_types = {}
    lw_x, lw_y = [], []      # LWPOLYLINE 顶点
    ln_x, ln_y = [], []      # LINE 端点
    inserts = Counter()      # INSERT 块名
    for e in msp:
        t = e.dxftype()
        etypes[t] += 1
        lay = e.dxf.layer if hasattr(e.dxf, "layer") else "(none)"
        layers[lay] += 1
        layer_types.setdefault(lay, Counter())[t] += 1
        if t == "LWPOLYLINE":
            try:
                for x, y in [tuple(p[:2]) for p in e.get_points()]:
                    lw_x.append(x)
                    lw_y.append(y)
            except Exception:
                pass
        elif t == "LINE":
            ln_x += [e.dxf.start.x, e.dxf.end.x]
            ln_y += [e.dxf.start.y, e.dxf.end.y]
        elif t == "INSERT":
            inserts[e.dxf.name] += 1

    print(f"\n===== {name} =====")
    print(f"  实体类型: {dict(etypes.most_common())}")
    # 墙/柱候选图层（含墙/柱/墙体/结构 关键字，按实体量降序）
    wall_layers = [(l, c) for l, c in layers.most_common()
                   if any(k in l for k in ("墙", "WALL", "柱", "COL"))]
    print(f"  墙/柱候选图层: {wall_layers[:12]}")
    # 数量最多的 8 个图层
    print(f"  Top图层: {[(l, c) for l, c in layers.most_common(8)]}")

    # LWPOLYLINE 几何
    if lw_x:
        cx = (min(lw_x) + max(lw_x)) / 2
        cy = (min(lw_y) + max(lw_y)) / 2
        cents, gaps = y_clusters(lw_y)
        print(f"  LWPOLYLINE: X[{min(lw_x):.0f},{max(lw_x):.0f}] 宽{(max(lw_x)-min(lw_x))/1000:.0f}m "
              f"Y[{min(lw_y):.0f},{max(lw_y):.0f}] 高{(max(lw_y)-min(lw_y))/1000:.0f}m")
        print(f"    center=({cx:.0f},{cy:.0f})  Y聚类={len(cents)}层 中心={[round(c) for c in cents]} 间距={gaps}")
    else:
        print("  LWPOLYLINE: 无")

    # LINE 几何
    if ln_x:
        cx = (min(ln_x) + max(ln_x)) / 2
        cy = (min(ln_y) + max(ln_y)) / 2
        cents, gaps = y_clusters(ln_y)
        print(f"  LINE: X[{min(ln_x):.0f},{max(ln_x):.0f}] 宽{(max(ln_x)-min(ln_x))/1000:.0f}m "
              f"Y[{min(ln_y):.0f},{max(ln_y):.0f}] 高{(max(ln_y)-min(ln_y))/1000:.0f}m")
        print(f"    center=({cx:.0f},{cy:.0f})  Y聚类={len(cents)}层 中心={[round(c) for c in cents]} 间距={gaps}")
    else:
        print("  LINE: 无")

    if inserts:
        print(f"  INSERT块: {dict(inserts.most_common(8))}")
