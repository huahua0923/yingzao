# -*- coding: utf-8 -*-
"""交付 floor JSON 里, 塔点(本地 ±33,-36)附近到底有没有墙(只读)。

_curve_delivered_check 的 outside 只统计「轮廓外的弧」并不看交付墙, 所以要单独问:
  Q1 交付 JSON 在该处有没有墙? 有多少条 / 多大面积?
  Q2 这些墙在交付 outline 内还是外?
  Q3 该层 outline 的实心面积 vs bbox 面积(缺口有多大)。
用法: python _probe_delivered_towers.py c006 [4]
"""
import sys, os, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

from shapely.geometry import Polygon, Point

ROOT = r"D:\gym3d\data\buildings"
nm = sys.argv[1] if len(sys.argv) > 1 else "c006"
want = [int(a) for a in sys.argv[2:]] or None
TESTS = [(33.0, -36.0), (-33.0, -36.0), (27.0, -36.0), (-27.0, -36.0), (55.0, 10.0), (-55.0, 10.0)]
R = 12.0

print("===== %s 交付 floors =====" % nm)
for fp in sorted(glob.glob(os.path.join(ROOT, nm, "floors", "floor*.json"))):
    F = int(os.path.basename(fp)[5:-5])
    if want and F not in want:
        continue
    fl = json.load(open(fp, encoding="utf-8"))
    O = None
    if fl.get("outline") and len(fl["outline"]) >= 3:
        O = Polygon(fl["outline"])
        if not O.is_valid:
            O = O.buffer(0)
    ob = O.bounds if O is not None else None
    bbox_area = (ob[2] - ob[0]) * (ob[3] - ob[1]) if ob else 0.0
    print("\n  层%-3d 墙%4d  轮廓面积%8.1f㎡  bbox%8.1f㎡  缺口%s"
          % (F, len(fl.get("walls", [])), O.area if O is not None else 0.0, bbox_area,
             ("%.0f%%" % (100 * (1 - O.area / bbox_area)) if bbox_area else "-")))
    # 逐测试点: 附近有哪些墙, 在轮廓内还是外
    for t in TESTS:
        near = []
        for w in fl.get("walls", []):
            try:
                G = Polygon(w["poly"], w.get("holes") or [])
            except Exception:
                continue
            if G.is_empty:
                continue
            cxg, cyg = G.centroid.x, G.centroid.y
            if (cxg - t[0]) ** 2 + (cyg - t[1]) ** 2 <= R * R:
                # 用面积重叠率而不是质心: 环状墙的质心落在自己的洞里
                overlap = (G.intersection(O).area / G.area) if O is not None and G.area else 0.0
                inside = overlap > 0.5
                per = G.length
                near.append((w.get("type", "?"), G.area, 2 * G.area / per if per > 0 else float("nan"), inside))
        if not near:
            continue
        tin = O.contains(Point(*t)) if O is not None else None
        print("     点(%.0f,%.0f) 该点在轮廓内=%s  附近墙%d条: %s"
              % (t[0], t[1], tin, len(near),
                 ", ".join("%s %.1f㎡ 厚%.2f %s" % (a, b, c, "内" if d else "外") for a, b, c, d in near[:5])))
