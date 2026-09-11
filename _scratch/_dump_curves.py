# -*- coding: utf-8 -*-
"""逐条 dump 墙层上「含 r>=2m 弧段」的多段线(只读), 定案普查与采样的口径差。

每条打印: 原始点数 / 每个弧段的 (弦长m, 凸度b, 半径m, 弧长m, 矢高m) / flatten 点数
"""
import sys, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from ezdxf.path import make_path
from run_building import load_profile

MIN_R = 2.0


def seg(p0, p1, b):
    c = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 1000.0
    if c < 1e-9 or abs(b) < 1e-9:
        return None
    th = 4.0 * math.atan(abs(b))
    s = math.sin(th / 2.0)
    if s < 1e-9:
        return None
    r = c / (2.0 * s)
    sag = r * (1.0 - math.cos(th / 2.0))
    return c, th, r, r * th, sag


for nm in (sys.argv[1:] or ["c072"]):
    p = load_profile(nm)
    doc = ezdxf.readfile(p.dxf)
    print("=== %s (墙层 %r) ===" % (nm, p.wall_layer))
    k = 0
    for e in doc.modelspace():
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != p.wall_layer:
            continue
        pts = list(e.get_points("xyseb"))
        segs = []
        for i in range(len(pts) - 1):
            b = pts[i][4] if len(pts[i]) > 4 else 0.0
            g = seg((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]), b)
            if g and g[2] >= MIN_R:
                segs.append(g)
        if not segs:
            continue
        k += 1
        try:
            nflat = len(list(make_path(e).flattening(250.0)))
        except Exception:  # noqa: BLE001
            nflat = -1
        print(" [%d] 原始%d点 弧段%d 个 flatten%d点 闭合=%s" %
              (k, len(pts), len(segs), nflat, e.closed))
        for c, th, r, L, sag in segs:
            print("      弦%7.2fm 凸度%7.4f 半径%8.2fm 弧长%8.2fm 矢高%7.3fm"
                  % (c, th / 4.0 if False else math.tan(th / 4.0), r, L, sag))
        if k >= 12:
            print("  ...(截断)")
            break
    print("  含弧多段线共 %d 条" % k)
