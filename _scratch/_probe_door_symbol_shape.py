# -*- coding: utf-8 -*-
"""墙层「闭合门符号」形状普查(只读) —— 为 #90 设计判据, 并检查会不会误吞窗户。

c019 实测的门符号(单条 flag-closed LWPOLYLINE, 13 顶点):
    2 个 240×150mm 小方框(门垛) + 1~2 条 1100mm 直线(门扇, 画在开启位) + 闭合斜段
判据候选: 闭合 + bbox 跨度 <= 2.6m + 恰好含 2 个 0.1~0.4m 的子方框 + 含 >=1 条 0.6~1.5m 直段。

**窗户**画法完全不同(墙线上 3~4 条平行线 / 细长矩形), 不该命中 —— 本探针按「跨度分桶 ×
子方框数 × 长段数」打表, 用证据确认区分度, 而不是拍脑袋定阈值。

用法: python _probe_door_symbol_shape.py [c019 c054 ...]   # 默认扫全部非冻结宿舍
"""
import sys, os, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from backend.recognizer import classify as C

ROOT = r"D:\gym3d\data\buildings"


def sub_box_count(pts, lo=100.0, hi=400.0):
    """点列里「小方框」(门垛块)个数: 连续 4~5 点回到起点、且各边长都落在 [lo,hi] mm。"""
    n = len(pts)
    cnt = 0
    i = 0
    while i < n:
        hit = 0
        for k in (4, 5):
            if i + k >= n or seg(pts[i], pts[i + k]) > 1e-6:
                continue
            sides = [seg(pts[i + j], pts[i + j + 1]) for j in range(k)]
            if all(lo <= s <= hi for s in sides[:4]) and sides[0] > 1e-6:
                hit = k
                break
        if hit:
            cnt += 1
            i += hit
            continue
        i += 1
    return cnt


def seg(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def runs(pts, lo=600.0, hi=1500.0):
    """连续段里长度落在 [lo,hi] mm 的条数(含闭合段)。"""
    n = len(pts)
    c = 0
    for i in range(n):
        j = (i + 1) % n
        if lo <= seg(pts[i], pts[j]) <= hi:
            c += 1
    return c


def run(name):
    from run_building import load_profile
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    closed = []
    for e in msp:
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != p.wall_layer:
            continue
        raw = [tuple(q[:2]) for q in e.get_points()]
        if len(raw) < 4:
            continue
        dup = abs(raw[0][0] - raw[-1][0]) <= 1e-6 and abs(raw[0][1] - raw[-1][1]) <= 1e-6
        if not (e.closed or dup):
            continue
        if not C._in_x_range(raw, p):
            continue
        xs = [q[0] for q in raw]
        ys = [q[1] for q in raw]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        if span > 3000:
            continue
        closed.append((span, len(raw), sub_box_count(raw), runs(raw)))
    if not closed:
        print("%-6s 墙层无跨度过小闭合线" % name)
        return
    tab = collections.Counter((round(s / 500) * 0.5, nb, nr > 0) for s, nv, nb, nr in closed)
    print("%-6s 小闭合线 %3d 条   (跨度桶, 门垛方框数, 有无0.6~1.5m长段) -> 条数" % (name, len(closed)))
    for k in sorted(tab):
        print("         span~%.1fm 方框%d 长段=%s : %d" % (k[0], k[1], "有" if k[2] else "无", tab[k]))


names = sys.argv[1:]
if not names:
    names = [n for n in sorted(os.listdir(ROOT))
             if n.startswith("c") and n[1:].isdigit() and n not in ("c006", "c009", "c103", "c104")]
for nm in names:
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        print("%-6s 失败: %s" % (nm, e))
