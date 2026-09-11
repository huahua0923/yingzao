# -*- coding: utf-8 -*-
"""探针(只读): 为什么弧墙采样只采到一点点。

对墙层上每条「含 r>=2m 弧段」的 LWPOLYLINE 打印:
  原始点数 / make_path 是否抛异常 / flatten 点数 / 偏离弦 >1mm 的点数
"""
import sys, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from shapely.geometry import LineString, Point
from ezdxf.path import make_path
from run_building import load_profile
from backend.recognizer.classify import _seg_radius, CURVE_MIN_R

for nm in (sys.argv[1:] or ["c072", "c009", "c041"]):
    p = load_profile(nm)
    doc = ezdxf.readfile(p.dxf)
    n_poly = n_curved = n_exc = 0
    tot_pts = tot_flat = tot_filt = 0
    ex = []
    for e in doc.modelspace():
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != p.wall_layer:
            continue
        n_poly += 1
        pts = list(e.get_points("xyseb"))
        if len(pts) < 2:
            continue
        curved = False
        rmax = 0.0
        for i in range(len(pts) - 1):
            b = pts[i][4] if len(pts[i]) > 4 else 0.0
            r = _seg_radius((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]), b)
            if r is not None and r >= CURVE_MIN_R * 1000.0:
                curved = True
                rmax = max(rmax, r)
        if not curved:
            continue
        n_curved += 1
        try:
            flat = [(float(q.x), float(q.y)) for q in make_path(e).flattening(250.0)]
        except Exception as ex1:  # noqa: BLE001
            n_exc += 1
            if len(ex) < 5:
                ex.append("EXC %s" % str(ex1)[:60])
            continue
        chords = LineString([(float(a), float(b)) for a, b in [(q[0], q[1]) for q in pts]])
        filt = [q for q in flat if chords.distance(Point(q)) > 1.0]
        tot_pts += len(pts)
        tot_flat += len(flat)
        tot_filt += len(filt)
        if len(filt) == 0 and len(ex) < 8:
            ex.append("过滤后0点: 原始%d点 flat%d点 rmax=%.1fm 闭合=%s"
                      % (len(pts), len(flat), rmax / 1000.0, e.closed))
    print("%-6s 墙层多段线 %d 条, 含弧 %d 条; make_path 异常 %d 条" %
          (nm, n_poly, n_curved, n_exc))
    print("        原始点 %d -> flatten %d -> 偏离>1mm 保留 %d  (≈%.0fm)"
          % (tot_pts, tot_flat, tot_filt, tot_filt * 0.25))
    for x in ex:
        print("        " + x)
