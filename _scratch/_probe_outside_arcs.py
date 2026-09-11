# -*- coding: utf-8 -*-
"""把「落在交付轮廓外的弧墙」按空间聚成簇(只读), 回答「到底缺了哪一块」。

轮廓外的弧点若是零散装饰(场地弧/图框弧), 会散成很多小簇; 若是一整条翼楼的
外侧墙, 会聚成 1~2 个大簇并带明确尺寸。输出每簇: 弧长 / 包围盒尺寸 / 位置
(相对该层轮廓中心)。

用法: python _probe_outside_arcs.py [c006 c009 c103 c104]
"""
import sys, os, json, glob, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

from shapely.geometry import Polygon, Point
from run_building import load_profile
from backend.recognizer.profile import floor_of, to_local
from _curve_delivered_check import curve_points_mm
from _diag_frozen_outline import load_floors, outline_of

ROOT = r"D:\gym3d\data\buildings"
GRID = 3.0        # 聚类栅格(m)
MIN_CLUSTER = 5.0  # 小于此长度的簇归入「零散」


def analyse(name):
    p = load_profile(name)
    fl = load_floors(name)
    arcs, _ = curve_points_mm(p)
    out = {}
    for (x, y, d) in arcs:
        if d <= 0:
            continue
        try:
            F = int(round(floor_of(p, x, y)))
        except Exception:  # noqa: BLE001
            continue
        if F not in fl:
            continue
        O = outline_of(fl[F])
        if O is None:
            continue
        lx, ly = to_local(p, x, y, F)
        if O.contains(Point(lx, ly)):
            continue
        out.setdefault(F, []).append((lx, ly, d, O.boundary.distance(Point(lx, ly))))

    print("\n===== %s =====" % name)
    if not out:
        print("  无域外弧点")
        return
    tot = sum(sum(q[2] for q in v) for v in out.values())
    print("  域外弧总长 %.1fm, 分布在 %d 层" % (tot / 1000.0, len(out)))
    for F in sorted(out, key=lambda f: -sum(q[2] for q in out[f])):
        qs = out[F]
        L = sum(q[2] for q in qs) / 1000.0
        if L < 2.0:
            continue
        # 栅格聚类: 同格或相邻格合并
        cells = {}
        for (a, b, d, dist) in qs:
            cells.setdefault((int(math.floor(a / GRID)), int(math.floor(b / GRID))), []).append((a, b, d, dist))
        # 并查集合并相邻格
        keys = list(cells)
        idx = {k: i for i, k in enumerate(keys)}
        par = list(range(len(keys)))

        def find(i):
            while par[i] != i:
                par[i] = par[par[i]]
                i = par[i]
            return i

        for (gx, gy) in keys:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (gx + dx, gy + dy)
                    if n in idx:
                        a, b = find(idx[(gx, gy)]), find(idx[n])
                        if a != b:
                            par[a] = b
        groups = {}
        for k in keys:
            groups.setdefault(find(idx[k]), []).extend(cells[k])
        rows = []
        for g in groups.values():
            gl = sum(q[2] for q in g) / 1000.0
            xs = [q[0] for q in g]
            ys = [q[1] for q in g]
            dmax = max(q[3] for q in g)
            dmean = sum(q[2] * q[3] for q in g) / max(1e-9, sum(q[2] for q in g))
            rows.append((gl, max(xs) - min(xs), max(ys) - min(ys),
                         (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, dmean, dmax, len(g)))
        rows.sort(reverse=True)
        big = [r for r in rows if r[0] >= MIN_CLUSTER]
        small = sum(r[0] for r in rows if r[0] < MIN_CLUSTER)
        print("  -- 层%d 域外 %.1fm: 大簇 %d 个, 零散 %.1fm --" % (F, L, len(big), small))
        for (gl, w, h, cx, cy, dmean, dmax, n) in big[:6]:
            print("      弧%6.1fm  范围%6.1f x %6.1fm  中心(%7.1f,%7.1f)  平均越界%.2fm 最远%.2fm  %d点"
                  % (gl, w, h, cx, cy, dmean, dmax, n))


for nm in (sys.argv[1:] or ["c006", "c009", "c103", "c104"]):
    analyse(nm.strip())
