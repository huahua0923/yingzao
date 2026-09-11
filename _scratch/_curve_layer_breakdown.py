# -*- coding: utf-8 -*-
"""弧要素按图层拆分(只读): 搞清普查 3851m 与体检 77m 的口径差在哪。

对每栋列出: 每个图层上的 ARC(半径>=2m) 根数/弧长, 以及 LWPOLYLINE 上半径>=2m 的
bulge 段数/弧长。生产墙层用 ★ 标出。
"""
import os, sys, math, json, glob

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf
from run_building import load_profile

ROOT = r"D:\gym3d\data\buildings"
MIN_R = 2.0


def bulge_rc(p0, p1, b):
    dx = (p1[0] - p0[0]) / 1000.0
    dy = (p1[1] - p0[1]) / 1000.0
    c = math.hypot(dx, dy)
    if c < 1e-9 or abs(b) < 1e-9:
        return None
    th = 4.0 * math.atan(abs(b))
    s = math.sin(th / 2.0)
    if s < 1e-9:
        return None
    r = c / (2.0 * s)
    return r, r * th


def report(name):
    try:
        p = load_profile(name)
    except Exception as e:  # noqa: BLE001
        print("%s profile 失败 %s" % (name, str(e)[:50]))
        return
    doc = ezdxf.readfile(p.dxf)
    arc = {}      # layer -> [n, len_m]
    bl = {}       # layer -> [n, len_m]
    other_pts = {}  # 非墙层上的几何要素计数, 防止漏源
    for e in doc.modelspace():
        lay = e.dxf.layer
        t = e.dxftype()
        if t == "ARC":
            r = e.dxf.radius / 1000.0
            if r >= MIN_R:
                sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360 or 360
                k = arc.setdefault(lay, [0, 0.0])
                k[0] += 1
                k[1] += r * math.radians(sweep)
        elif t == "LWPOLYLINE":
            for i, (p0, p1) in enumerate(zip(e.get_points("xyseb")[:-1],
                                             e.get_points("xyseb")[1:])):
                b = p0[4] if len(p0) > 4 else 0.0
                g = bulge_rc((p0[0], p0[1]), (p1[0], p1[1]), b)
                if g and g[0] >= MIN_R:
                    k = bl.setdefault(lay, [0, 0.0])
                    k[0] += 1
                    k[1] += g[1]
    print("\n=== %s  (生产墙层 = %r) ===" % (name, p.wall_layer))
    rows = []
    for lay in set(arc) | set(bl):
        a = arc.get(lay, [0, 0.0])
        b = bl.get(lay, [0, 0.0])
        rows.append((a[1] + b[1], lay, a, b))
    for tot, lay, a, b in sorted(rows, reverse=True):
        mark = " ★生产墙层" if lay == p.wall_layer else ""
        hasqiang = "" if "墙" in lay else "  (图层名不含『墙』)"
        print("  %-28s ARC %3d根/%-8.0fm  bulge %3d段/%-8.0fm  合计%6.0fm%s%s"
              % (lay, a[0], a[1], b[0], b[1], tot, mark, hasqiang))
    prod = sum(t for t, lay, a, b in rows if lay == p.wall_layer)
    print("  合计 %.0fm, 其中生产墙层 %.0fm, 其他图层 %.0fm" %
          (sum(r[0] for r in rows), prod, sum(r[0] for r in rows) - prod))


for nm in (sys.argv[1:] or ["c009", "c104", "c006", "c103", "c041", "c072", "c073"]):
    report(nm)
