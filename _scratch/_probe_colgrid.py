# -*- coding: utf-8 -*-
"""在 DXF 图纸坐标里比较各层柱网格：F0(裙楼) vs F1+(塔楼) 的 X 网格是否一致。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d")
sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, r"D:\gym3d\backend\recognizer")
import ezdxf
from run_building import load_profile

def cols_raw(name):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    layer = getattr(p, "column_layer", None)
    out = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == layer:
            pts = [tuple(pt[:2]) for pt in e.get_points()]
            if len(pts) < 4:
                continue
            xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
            cx = sum(xs) / len(xs); cy = sum(ys) / len(ys)
            out.append((cx, cy))
    return out

def cluster_rows(cols):
    """按 Y 中心行距聚类 → 每层一根 list of (cx, cy)。"""
    cols = sorted(cols, key=lambda c: c[1])
    clusters = []
    cur = []
    last = None
    for x, y in cols:
        if last is None or y - last < 50000:
            cur.append((x, y)); last = y
        else:
            clusters.append(cur); cur = [(x, y)]; last = y
    if cur:
        clusters.append(cur)
    return clusters

def report(name):
    p = load_profile(name)
    print("=" * 74)
    print(f"{name} ({p.title})  DXF 柱网格按行聚类   column_layer={getattr(p,'column_layer',None)}")
    cl = cluster_rows(cols_raw(name))
    prev_x = prev_y = None
    for i, cl_ in enumerate(cl):
        xs = sorted(c[0] for c in cl_)
        ys = sorted(c[1] for c in cl_)
        ymid = sum(ys) / len(ys)
        xuniq = sorted(set(round(x, 1) for x in xs))
        yuniq = sorted(set(round(y, 1) for y in ys))
        n = len(cl_)
        if n < 3:
            continue
        dx = ""
        if prev_x is not None:
            s = set(round(x) for x in xuniq); sp = set(round(x) for x in prev_x)
            inter = len(s & sp)
            dx = f"  X与上行重合{inter}/{len(sp)}  Y中心差{(ymid-prev_y)/1000:+.2f}m"
        print(f"  行{i}: 柱{n}  Y中{ymid:9.0f}  Xuniq={[round(x/1000,2) for x in xuniq][:12]}")
        if dx:
            print(f"        {dx}")
        prev_x = xuniq; prev_y = ymid

for b in sys.argv[1:]:
    report(b)
