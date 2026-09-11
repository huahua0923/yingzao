# -*- coding: utf-8 -*-
"""宿舍「闭合门符号」普查(只读): 墙层上闭合多段线里哪些是门(门扇+摆动弧回起点)。

背景(_wall_thin_batch 会话): detect_doors(geometry.py:677) 只收「不闭合」折线,
而 c019 等宿舍的门符号是 **闭合环路** 画的(门扇线 + 摆动弧摆回起点) → 既认不出门,
又被 buffer 成 ~1.5m 假墙糊进内墙。

本探针只做证据采集, 不改任何东西:
  Q1 墙层上有多少闭合多段线? 顶点数/bbox 跨度/最长段 分布?
  Q2 若用「最长段 = 门扇线 ∈ [0.6,3.0)m, 其余点落在以铰点为中心、半径=门扇长的圆上」判,
     命中多少? 和闭合矩形的区分度如何?
  Q3 这些符号在楼层上怎么分布?

用法: python _probe_closed_door.py c019 [c054 ...]
"""
import sys, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from backend.recognizer import classify as C
from backend.recognizer.component_library import DOOR_LEAF_MIN, DOOR_LEAF_MAX


def seg_len(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def leaf_and_arc(pts, tol=150.0):
    """闭合环是不是「门扇线 + 摆动弧」符号(mm 单位)。

    判据: 存在一条段长 L ∈ [DOOR_LEAF_MIN, DOOR_LEAF_MAX) m 当门扇, 取它一端当铰点,
    其余点到铰点的距离都 ≈ L(摆动弧半径=门扇长)。tol = 允许偏差(mm)。
    返回 (L, hinge_idx, max_dev) 或 None。
    """
    n = len(pts)
    if n < 3:
        return None
    lo, hi = DOOR_LEAF_MIN * 1000.0, DOOR_LEAF_MAX * 1000.0
    best = None
    for i in range(n - 1):
        L = seg_len(pts[i], pts[i + 1])
        if not (lo <= L < hi):
            continue
        for hinge, far in ((pts[i], pts[i + 1]), (pts[i + 1], pts[i])):
            devs = []
            for j, q in enumerate(pts):
                if j in (i, i + 1):
                    continue
                devs.append(abs(seg_len(hinge, q) - L))
            if not devs:
                continue
            md = max(devs)
            hit = sum(1 for d in devs if d <= tol) / len(devs)
            if hit >= 0.8 and (best is None or md < best[2]):
                best = (L, i, md)
    return best


def run(name):
    from run_building import load_profile
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    closed, open_ = [], []
    for e in msp:
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != p.wall_layer:
            continue
        raw = [tuple(q[:2]) for q in e.get_points()]
        if len(raw) < 3:
            continue
        if not C._in_x_range(raw, p):
            continue
        is_cl = abs(raw[0][0] - raw[-1][0]) <= 1e-6 and abs(raw[0][1] - raw[-1][1]) <= 1e-6
        (closed if is_cl else open_).append(raw)

    print("\n===== %s  墙层=%s =====" % (name, p.wall_layer))
    print("  闭合多段线 %d 条, 不闭合 %d 条" % (len(closed), len(open_)))
    if not closed:
        return
    span_hist = collections.Counter()
    nv_hist = collections.Counter()
    hits, misses = [], []
    for pts in closed:
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        span_hist[round(span / 1000.0 * 2) / 2] += 1     # 0.5m 分桶
        nv_hist[len(pts)] += 1
        r = leaf_and_arc(pts)
        (hits if r else misses).append((pts, span, r))
    print("  按 bbox 跨度分桶(m):  %s" % dict(sorted(span_hist.items())))
    print("  按顶点数分桶:        %s" % dict(sorted(nv_hist.items())))
    print("  「门扇+摆动弧」判据命中 %d / %d" % (len(hits), len(closed)))
    if hits:
        ls = sorted(h[2][0] for h in hits)
        print("     命中门扇长(m): %.2f ~ %.2f 中位 %.2f"
              % (ls[0] / 1000, ls[-1] / 1000, ls[len(ls) // 2] / 1000))
        print("     命中样例(跨度m, 扇长m, 顶点, 最大弧偏差mm):")
        for pts, span, r in hits[:8]:
            print("        span %.2f  扇 %.2f  顶点%3d  偏差 %5.0f" % (span / 1000, r[0] / 1000, len(pts), r[2]))
    if misses:
        ms = sorted(misses, key=lambda t: -t[1])
        print("     未命中 %d 条, 跨度最大 8 条:" % len(misses))
        for pts, span, _ in ms[:8]:
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            mx = 0.0
            for i in range(len(pts) - 1):
                mx = max(mx, seg_len(pts[i], pts[i + 1]))
            print("        span %.2f  顶点%3d  最长段 %.2f m" % (span / 1000, len(pts), mx / 1000))


for nm in (sys.argv[1:] or ["c019"]):
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        print("  %s 失败: %s" % (nm, e))
