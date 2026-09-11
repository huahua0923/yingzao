# -*- coding: utf-8 -*-
"""墙层-only 的楼层聚类诊断：每栋楼输出各层 Y 中心 + 相邻间距 + 各层 X 范围。
据此定 offset(层间距=相邻中心距中位数) / cx(X中心) / cy(0层Y中心)。
"""
import os
import sys
import statistics
import ezdxf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BUILDINGS = [
    ("c009", "C009-第九教学楼", "4.2墙体"),
    ("c022", "C022-第七教学楼（致远楼）", "4.2墙体"),
    ("c025", "C025-第一教学楼", "4墙体"),
    ("c026", "C026-第四教学楼", "4.2墙体"),
    ("c027", "C027-第三教学楼", "4.2墙体"),
    ("c028", "C028-第二教学楼", "4.2墙体"),
    ("c041", "C041-第八教学楼（学研楼）", "4.2墙体"),
    ("c103", "C103-第十一教学楼（东1教）", "4.2墙体"),
    ("c104", "C104-第十二教学楼（东2教）", "4.2墙体"),
    ("c114", "C114-第十教学楼（启智楼）", "4.2墙体"),
]
DXF_DIR = r"D:\dxf_output"


def cluster(ys, gap=5000):
    wy = sorted(set(round(y) for y in ys))
    if not wy:
        return []
    clusters = [[wy[0]]]
    for y in wy[1:]:
        if y - clusters[-1][-1] > gap:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    return clusters


for name, file, wl in BUILDINGS:
    dxf = os.path.join(DXF_DIR, file + ".dxf")
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    pts = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wl:
            pts += [tuple(p[:2]) for p in e.get_points()]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cl = cluster(ys)
    centers = [sum(c) / len(c) for c in cl]
    gaps = [round(centers[i + 1] - centers[i]) for i in range(len(centers) - 1)]
    big = [g for g in gaps if g > 15000]
    med = statistics.median(big) if big else None
    # 各层 X 范围（按聚簇归属）
    csets = [set(c) for c in cl]
    print(f"\n{name} {file}  wall={wl}")
    print(f"  层数(聚类)={len(cl)}  中心Y={[round(c) for c in centers]}")
    print(f"  相邻间距={gaps}")
    print(f"  >15m 大间距={big}  中位数(→offset)={med}")
    print(f"  X范围=[{min(xs):.0f},{max(xs):.0f}]  cx={(min(xs)+max(xs))/2:.0f}  Y范围=[{min(ys):.0f},{max(ys):.0f}]")
