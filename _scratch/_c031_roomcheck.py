# -*- coding: utf-8 -*-
"""c031 房间提取质检(dry): 多边形面积 vs 图注面积 + 7/8语义核对。只读不写。"""
import sys
sys.path.insert(0, r"D:\gym3d")
sys.path.insert(0, r"D:\gym3d\backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from shapely.geometry import Point, Polygon
from run_building import load_profile
from recognizer.classify import classify
from recognizer.geometry import detect_doors
from recognizer.floor import reference_outline_for, unify_floor_set, outline_for_floor
from recognizer.profile import to_local, floor_of
from backend.extract import extract_rooms_generic as E

p = load_profile("c031")
doc = ezdxf.readfile(p.dxf, encoding=E.ENCODING)
msp = doc.modelspace()
walls, _, _, _ = classify(msp, p)

# c031 图层: 7使用单位(dept) / 8房间用途(purpose) — 与默认(7=purpose,8=dept)相反
role_map = dict(E.LAYER_ROLE); role_map.update({"7": "dept", "8": "purpose"})
labels = E.read_labels(msp, role_map)
print("label counts:", {k: len(v) for k, v in labels.items()})

floors = sorted({floor_of(p, sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
                 for pts in walls})
ref_F, ref_o = reference_outline_for(p, walls, floors)
unify_set = unify_floor_set(p, floors)

def declared_area(entry):
    """找离房间质心最近的 5面积 标注值(带㎡字样)。"""
    poly = Polygon(entry["boundary"])
    cx, cy = poly.centroid.x, poly.centroid.y
    best = None
    for (x, y, t) in labels["area"]:
        if floor_of(p, x, y) != entry["floor"]:
            continue
        lx, ly = to_local(p, x, y, entry["floor"])
        d = (lx - cx) ** 2 + (ly - cy) ** 2
        if best is None or d < best[0]:
            best = (d, t)
    return best[1] if best else None

tot = 0; bad = 0; examples = []
for F in floors:
    override = outline_for_floor(p, ref_F, ref_o, F) if F in unify_set else None
    polys = E.floor_rooms(F, walls, None, p, outline_override=override)
    n_holes = len(polys)
    for g in polys:
        number = E.label_in(g, labels["number"], F, p)
        if not number:
            continue
        a = g.area
        tot += 1
        decl = declared_area({"floor": F, "boundary": list(g.exterior.coords)})
        import re
        dm = re.search(r"([\d.]+)", decl or "")
        da = float(dm.group(1)) if dm else None
        ok = da is not None and abs(a - da) / max(da, 1e-9) < 0.30
        if not ok:
            bad += 1
            if len(examples) < 10:
                b = g.bounds
                examples.append((F, number, round(a, 1), da, round(b[2]-b[0], 1), round(b[3]-b[1], 1)))
print("\n抽查房间总数=%d  面积不符(>30%%偏差)=%d" % (tot, bad))
for ex in examples:
    print("  F%d %-4s poly=%.1f㎡ 注=%.1f㎡  bbox=%.1fx%.1f"
          % (ex[0], ex[1], ex[2], ex[3] if ex[3] else -1, ex[4], ex[5]))
