# -*- coding: utf-8 -*-
"""c031 墙折线 y 质心分簇取证: 图纸到底几层堆叠、真实层距 vs profile offset。只读。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
import numpy as np

DXF = r"D:\dxf_output\C031-芙蓉园3号公寓.dxf"
doc = ezdxf.readfile(DXF)
msp = doc.modelspace()

cy_all = []
cx_all = []
for e in msp:
    if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "4.2墙体":
        pts = [tuple(pt[:2]) for pt in e.get_points()]
        if len(pts) < 2:
            continue
        cy_all.append(sum(q[1] for q in pts) / len(pts))
        cx_all.append(sum(q[0] for q in pts) / len(pts))

cy = np.array(sorted(cy_all))
print("墙折线数=%d  y范围 %.0f..%.0f" % (len(cy), cy.min(), cy.max()))

# 分簇: 相邻间隙 > pitch/2 处切开
gaps = np.diff(cy)
thr = 20000  # 20m 切簇
cuts = np.where(gaps > thr)[0]
bounds = []
start = 0
for c in cuts:
    bounds.append((cy[start], cy[c]))
    start = c + 1
bounds.append((cy[start], cy[-1]))
print("层带数=%d" % len(bounds))
for i, (a, b) in enumerate(bounds):
    n = np.sum((cy >= a) & (cy <= b))
    print("  band %d: y %.0f..%.0f  中位 %.0f  墙数=%d  宽 %.0f"
          % (i, a, b, (a + b) / 2, n, b - a))
if len(bounds) >= 2:
    mids = [(a + b) / 2 for a, b in bounds]
    print("相邻带间距:", [round(mids[i+1] - mids[i]) for i in range(len(mids) - 1)])
print("profile offset=63600")
