# -*- coding: utf-8 -*-
"""开口边从哪来：三角化的边界边 vs _extrude_ring 走的环边，对不上吗？

假设：earcut 会丢掉共线点，于是盖面的边界跳过某个顶点，而侧壁环还带着它，
那条边就只有侧壁用了一次 → 开口。若成立，对多边形先做 simplify(0)（只去
共线/重复点、不改形状）后两边就应该完全吻合。
"""
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon  # noqa: E402
from glb_common import _triangulate  # noqa: E402


def ring_edges(poly):
    out = []
    for r in [poly.exterior] + list(poly.interiors):
        c = [(round(x, 6), round(y, 6)) for x, y in r.coords]
        if len(c) > 1 and c[0] == c[-1]:
            c.pop()
        for i in range(len(c)):
            out.append(tuple(sorted((c[i], c[(i + 1) % len(c)]))))
    return out


def cap_edges(tris):
    out = []
    for a, b, c in tris:
        p = [(round(a[0], 6), round(a[1], 6)), (round(b[0], 6), round(b[1], 6)),
             (round(c[0], 6), round(c[1], 6))]
        for i in range(3):
            out.append(tuple(sorted((p[i], p[(i + 1) % 3]))))
    return out


tot = miss = miss_s = 0
bad_sample = None
for fp in sorted(glob.glob(r"D:\gym3d\data\buildings\c018\floors\floor*.json"))[:2]:
    fl = json.load(open(fp, encoding="utf-8"))
    for w in fl["walls"]:
        poly = Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4])
        if not poly.is_valid or poly.is_empty:
            continue
        re_ = ring_edges(poly)
        ce = Counter(cap_edges(_triangulate(poly)))
        m = sum(1 for e in re_ if ce.get(e, 0) != 1)
        tot += len(re_)
        miss += m
        # 去共线后再看
        sp = poly.simplify(0, preserve_topology=True)
        if sp.geom_type == "Polygon" and not sp.is_empty:
            re2 = ring_edges(sp)
            ce2 = Counter(cap_edges(_triangulate(sp)))
            miss_s += sum(1 for e in re2 if ce2.get(e, 0) != 1)
        if m and bad_sample is None:
            bad_sample = (len(w["poly"]), m, len(re_), poly.area)
print("原始多边形 : 环边 %d 条，其中盖面没用到的 %d 条（%.2f%%）"
      % (tot, miss, 100.0 * miss / tot))
print("simplify(0): 环边没用到的 %d 条（%.2f%%，分母同上）"
      % (miss_s, 100.0 * miss_s / tot))
if bad_sample:
    print("样例：墙顶点 %d，环边 %d 条中 %d 条对不上，面积 %.3f m²" % bad_sample)
