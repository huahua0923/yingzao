# -*- coding: utf-8 -*-
"""为 detect_doors 路径定「外门/内门」判据(只读) —— 量门心到轮廓外环的距离分布。

door_by_points 路径用门符号 bbox 到轮廓的距离 < 0.25 判外门；detect_doors 路径没有 bbox，
只能用门心。本探针在若干 LWPOLYLINE 楼上量距离直方图，找外门(≈半墙厚 ~0.15~0.30)与
内门(远离轮廓)之间的空档，据此定阈值。

用法: python _probe_c019_outerdist.py [c019 c054 c055]
"""
import sys, json, glob, os, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

import ezdxf
from shapely.geometry import Polygon, Point
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer import floor as FL

ROOT = r"D:\gym3d\data\buildings"


def run(name):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    walls_dxf, _a, _b, _c = classify.classify(doc.modelspace(), p)
    outer_t = getattr(p, "outer_wall_t", 0.30)
    print("\n===== %s  outer_wall_t=%.2f  wall_min=%.2f wall_max=%.2f ====="
          % (name, outer_t, p.wall_min, p.wall_max))
    for fp in sorted(glob.glob(os.path.join(ROOT, name, "floors", "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        outline = Polygon(fl["outline"])
        if not outline.is_valid:
            outline = outline.buffer(0)
        pts = FL.wall_pts_for_floor(F, walls_dxf, p)
        sym = [q for q in pts if FL.is_door_symbol_pts(q)]
        pts = [q for q in pts if not FL.is_door_symbol_pts(q)]

        def near(q):
            return Point(sum(t[0] for t in q) / len(q),
                         sum(t[1] for t in q) / len(q)).distance(outline) <= 1.0
        pts = [q for q in pts if near(q)]
        sym = [q for q in sym if near(q)]
        doors = FL.detect_doors(pts + sym, outline, p)
        ds = sorted(round(Point(d["x"], d["y"]).distance(outline.exterior), 3) for d in doors)
        if not ds:
            print("  F%d 无门" % F)
            continue
        # 0.1m 分桶
        h = collections.Counter(round(x * 10) / 10.0 for x in ds)
        near_n = sum(1 for x in ds if x < outer_t + 0.15)
        print("  F%-2d 门%3d  距轮廓: min%.2f 中位%.2f max%.2f | <%.2f(外门?) %3d 个 | 桶 %s"
              % (F, len(ds), ds[0], ds[len(ds) // 2], ds[-1], outer_t + 0.15, near_n,
                 dict(sorted(h.items()))))


for nm in (sys.argv[1:] or ["c019"]):
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        print("  %s 失败: %s" % (nm, e))
