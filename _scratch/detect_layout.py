# -*- coding: utf-8 -*-
"""判断每栋楼的平面排版：单列 Y 堆叠 vs 网格(X多列) vs 阶梯(间距不齐)。
对墙层 LWPOLYLINE 顶点做 X 聚类(10000mm 阈值) 与 Y 聚类(自适应)，
输出 X 列数 / Y 带数 / 每带 X 范围，据此定管线策略。
"""
import os
import sys
import ezdxf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BUILDINGS = [
    ("c009", "C009-第九教学楼", "4.2墙体"),
    ("c022", "C022-第七教学楼（致远楼）", "4.2墙体"),
    ("c025", "C025-第一教学楼", "4墙体"),
    ("c026", "C026-第四教学楼", "4.2墙体"),
    ("c027", "C027-第三教学楼", "4.2墙体"),
    ("c028", "C028-第二教学楼", "4.2墙体"),
    ("c041", "C041-008教学楼（学研楼）", "4.2墙体"),
    ("c103", "C103-011教学楼（东1教）", "4.2墙体"),
    ("c104", "C104-012教学楼（东2教）", "4.2墙体"),
    ("c114", "C114-010教学楼（启智楼）", "4.2墙体"),
]
DXF_DIR = r"D:\dxf_output"


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


for name, file, wl in BUILDINGS:
    dxf = os.path.join(DXF_DIR, file + ".dxf")
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    xs, ys = [], []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wl:
            for x, y in [tuple(p[:2]) for p in e.get_points()]:
                xs.append(x)
                ys.append(y)
    xbands = cluster(xs, 10000)
    # X 列：跨度>20m 的才算独立列
    xcols = []
    for b in xbands:
        w = (max(b) - min(b)) / 1000
        if w > 20:
            xcols.append((min(b), max(b)))
    ybands = cluster(ys, 30000)
    ywide = [b for b in ybands if (max(b) - min(b)) / 1000 > 10]
    print(f"{name}  X列(>20m宽)={len(xcols)}  Y带(>10m高)={len(ywide)}")
    for i, (x0, x1) in enumerate(xcols):
        print(f"    列{i}: X[{x0:.0f},{x1:.0f}] 宽{(x1-x0)/1000:.0f}m")
    # 每 X 列内的 Y 带数（判断是否每列独立堆叠）
    for i, (x0, x1) in enumerate(xcols):
        cy = [y for x, y in zip(xs, ys) if x0 <= x <= x1]
        yb = cluster(cy, 30000)
        yw = [b for b in yb if (max(b)-min(b))/1000 > 10]
        print(f"    列{i} 内 Y带数={len(yw)} 中心Y={[round((min(b)+max(b))/2) for b in yw]}")
