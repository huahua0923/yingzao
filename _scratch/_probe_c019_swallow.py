# -*- coding: utf-8 -*-
"""c019「门夹在墙里」的几何取证(只读) —— 看清吞掉门的到底是哪块墙、什么形状。

对新判据(_hinge_leaf)算出的门, 逐个找包含它的墙, 打印:
  门(x,y,w,horiz) | 墙 type/厚度/顶点/bbox | 门心到该墙边界的「深度」(米)
  该墙在门心 3m 邻域内的顶点(看清是长条墙横穿, 还是别的)

用法: python _probe_c019_swallow.py [c019] [楼层=0] [样例数=6]
"""
import sys, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

import ezdxf
from shapely.geometry import Polygon, Point
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer import floor as FL

ROOT = r"D:\gym3d\data\buildings"


def W(w):
    P = Polygon(w["poly"])
    if not P.is_valid:
        P = P.buffer(0)
    for h in w.get("holes") or []:
        if len(h) >= 3:
            H = Polygon(h)
            if H.is_valid and not H.is_empty:
                P = P.difference(H)
    return P


def main(name, F, nshow):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    walls_dxf, _a, _b, _c = classify.classify(doc.modelspace(), p)
    import json, os
    fl = json.load(open(os.path.join(ROOT, name, "floors", "floor%d.json" % F), encoding="utf-8"))
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
    walls = [W(w) for w in fl["walls"]]
    print("===== %s F%d  新门 %d  旧墙 %d =====" % (name, F, len(doors), len(walls)))

    n_in = 0
    shown = 0
    for d in doors:
        pt = Point(d["x"], d["y"])
        hit = None
        for w, P in zip(fl["walls"], walls):
            if P.contains(pt):
                hit = (w, P)
                break
        if hit is None:
            continue
        n_in += 1
        if shown >= nshow:
            continue
        shown += 1
        w, P = hit
        depth = P.exterior.distance(pt)          # 到外环的距离(>0 = 在内部)
        xs = [q[0] for q in w["poly"]]
        ys = [q[1] for q in w["poly"]]
        print("\n  门 (%7.2f,%7.2f) w=%.2f horiz=%s outer=%s"
              % (d["x"], d["y"], d.get("w", 0), d.get("horiz"), d.get("outer")))
        print("     吞它的墙: type=%s 厚%.2f 顶点%d 洞%d  bbox %6.2f x %6.2f  面积%.2f"
              % (w["type"], w.get("thickness", 0), len(w["poly"]),
                 len(w.get("holes") or []), max(xs) - min(xs), max(ys) - min(ys), P.area))
        print("     门心在墙内 %.2f m 深(到外环)" % depth)
        # 门心 3m 邻域内的墙顶点(看形状)
        loc = [(round(x, 2), round(y, 2)) for x, y in w["poly"]
               if math.hypot(x - d["x"], y - d["y"]) <= 3.0]
        print("     3m 邻域墙顶点 %d 个: %s" % (len(loc), loc[:14]))
        # 门中轴扫线: 沿 horiz 方向 ±2m 看墙是否连续穿过
        for sgn, lab in ((1, "+"), (-1, "-")):
            for r in (0.3, 0.8, 1.5, 2.5):
                q = (d["x"] + sgn * r, d["y"]) if d.get("horiz") else (d["x"], d["y"] + sgn * r)
                if P.contains(Point(*q)):
                    print("     沿%s方向 %.1fm 处仍在墙内" % (lab, r))
                    break
    print("\n  新门里落在墙内的: %d / %d" % (n_in, len(doors)))


if __name__ == "__main__":
    nm = sys.argv[1] if len(sys.argv) > 1 else "c019"
    ff = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    ns = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    main(nm, ff, ns)
