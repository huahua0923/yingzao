# -*- coding: utf-8 -*-
"""量一量：墙多段线在 X 上的「排序-合并间隙」到底有多大？

目的：给 cluster_x 的 gap 阈值找实测依据，而不是拍脑袋 20m。
c108 的列1 在 600m 外（真·另开一块图纸）；若多数楼的最大间隙只有几十米，
那阈值必须远大于楼宽，否则会把正常楼体的稀疏墙也切成两块。
"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\recognizer")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf  # noqa: E402
import detect_params as dp  # noqa: E402

BUILDINGS = r"D:\gym3d\data\buildings"
rows = []

for name in sorted(os.listdir(BUILDINGS)):
    pj = os.path.join(BUILDINGS, name, "profile.json")
    if not os.path.exists(pj):
        continue
    prof = json.load(open(pj, encoding="utf-8"))
    dxf = prof.get("dxf")
    if not dxf or not os.path.exists(dxf):
        continue
    wl = prof.get("wall_layer")
    if not wl:
        continue
    try:
        msp = ezdxf.readfile(dxf).modelspace()
    except Exception:
        continue
    boxes = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wl:
            pts = [tuple(p[:2]) for p in e.get_points()]
            if pts:
                pxs = [p[0] for p in pts]
                boxes.append((min(pxs), max(pxs)))
    if not boxes:
        continue
    bs = sorted(boxes)
    gaps = []
    hi = bs[0][1]
    for lo, h in bs[1:]:
        if lo > hi:
            gaps.append(lo - hi)
            hi = h
        else:
            hi = max(hi, h)
    gaps.sort(reverse=True)
    span = bs[-1][1] - bs[0][0]
    rows.append((name, span / 1000.0, len(boxes),
                 [round(g / 1000.0, 1) for g in gaps[:4]]))

print("%-8s %10s %6s  %s" % ("楼", "X总跨(m)", "墙数", "最大间隙(m) 前4"))
print("-" * 72)
for r in sorted(rows, key=lambda r: -(r[3][0] if r[3] else 0)):
    print("%-8s %10.1f %6d  %s" % (r[0], r[1], r[2], r[3]))
