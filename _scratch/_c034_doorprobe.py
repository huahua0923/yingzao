# -*- coding: utf-8 -*-
"""c034 F1 门距分布探针(只读, 不写): 重建薄墙后, 门心到最近墙的距离直方图。
判据: 若失败门大多在 0.5-1.3m(门洞内/贴墙), 是门洞间隙非浮门; >1.3m 才是真浮门。"""
import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import floor_of, to_local
from backend.recognizer import geometry as G
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union

NAME, F = "c034", 1
p = load_profile(NAME)
doc = ezdxf.readfile(p.dxf)
msp = doc.modelspace()
walls_dxf, doors, stairs, cols = classify.classify(msp, p)
segs = []
for w in walls_dxf:
    cx = sum(a for a, b in w) / len(w); cy = sum(b for a, b in w) / len(w)
    lv = int(round(floor_of(p, cx, cy)))
    if lv != F:
        continue
    loc = [(float(a), float(b)) for a, b in [to_local(p, a, b, F) for a, b in w]]
    segs += G._flatten_wall_segments([loc])
rects, singles = G.pair_wall_faces(segs, p)

fl = json.load(open(r"D:\gym3d\data\buildings\c034\floors\floor%d.json" % F, encoding="utf-8"))
oline = Polygon(fl["outline"])
interior = Polygon(fl["walls"][0]["holes"][0]).buffer(-0.01)
polys = []
for poly, t in rects:
    pc = poly.intersection(interior).buffer(0)
    if pc.is_empty:
        continue
    polys.extend(list(pc.geoms) if pc.geom_type == "MultiPolygon" else [pc])
for s in singles:
    pc = LineString(s).buffer(p.single_wall_t / 2).intersection(interior).buffer(0)
    if pc.is_empty:
        continue
    polys.extend(list(pc.geoms) if pc.geom_type == "MultiPolygon" else [pc])
wallU = unary_union([P.buffer(0) for P in polys if P.is_valid])
# 也含外墙环
outerP = Polygon(fl["walls"][0]["poly"])
wallU = unary_union([wallU, outerP])

buckets = {}
worst = []
for dd in fl["doors"]:
    d = wallU.distance(Point(dd["x"], dd["y"]))
    b = int(d * 4)  # 0.25m bins
    buckets[b] = buckets.get(b, 0) + 1
    if d > 1.3:
        worst.append((round(d, 2), round(dd["x"], 1), round(dd["y"], 1)))
nd = len(fl["doors"])
print("c034 F1 门=%d, 重建薄墙后门心距分布:" % nd)
for b in sorted(buckets):
    print("  %.2f-%.2fm: %d 门" % (b / 4, (b + 1) / 4, buckets[b]))
print(">1.3m 真浮门数: %d" % len(worst), worst[:10])
