# -*- coding: utf-8 -*-
import sys
import ezdxf
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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


for name, f, wl in [("c103", "C103-第十一教学楼（东1教）", "4.2墙体"),
                    ("c104", "C104-第十二教学楼（东2教）", "4.2墙体")]:
    doc = ezdxf.readfile("D:\\dxf_output\\" + f + ".dxf")
    msp = doc.modelspace()
    xs, ys = [], []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wl:
            for x, y in [tuple(p[:2]) for p in e.get_points()]:
                xs.append(x)
                ys.append(y)
    wide = [(min(b), max(b)) for b in cluster(xs, 5000) if (max(b) - min(b)) / 1000 > 15]
    print(f"\n{name}: X宽列={len(wide)}")
    for i, (x0, x1) in enumerate(wide):
        cy = [y for x, y in zip(xs, ys) if x0 <= x <= x1]
        cw = [b for b in cluster(cy, 5000) if (max(b) - min(b)) / 1000 > 10]
        cents = [round((min(b) + max(b)) / 2) for b in cw]
        gaps = [cents[j + 1] - cents[j] for j in range(len(cents) - 1)]
        print(f"  列{i}: X[{x0:.0f},{x1:.0f}] 宽{(x1-x0)/1000:.0f}m Y带={len(cw)}")
        print(f"      中心={cents}")
        print(f"      间距={gaps}")
