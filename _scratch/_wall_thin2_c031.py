# -*- coding: utf-8 -*-
"""R11/R12 c031 内墙解融(双线配对重建) —— 原型。
把内墙从「整层blob(净139㎡)」重建为「双线配对读真实厚度 0.1-0.3m 的独立薄墙」。
方法复用 geometry.pair_wall_faces(C006 已验证): 折线拆段->平行皮配对->真实厚矩形+单线薄墙。
外墙(0.3m 环, 已正确)与女儿墙保留不动。内墙剪到外墙内空间, 避免双覆盖。
逐层备份(.orig/floors.before_wallthin, 首次原型已建) + 数值验收 + 不通过回滚。
验收: A 内墙条数>8  B 内墙净覆盖<=16%  C 无>楼板40%单墙  D 门贴墙>=90%  E 房∩墙均值<=3%
"""
import json, glob, os, sys, math, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import floor_of, to_local
from backend.recognizer import geometry as G
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union

NAME = "c031"
p = load_profile(NAME)
doc = ezdxf.readfile(p.dxf)
walls_dxf, doors, stairs, cols = classify.classify(doc.modelspace(), p)

raw_by_floor = {}
for w in walls_dxf:
    cx = sum(a for a, b in w) / len(w); cy = sum(b for a, b in w) / len(w)
    F = int(round(floor_of(p, cx, cy)))
    raw_by_floor.setdefault(F, []).append(w)

floors_dir = r"D:\gym3d\data\buildings\%s\floors" % NAME
bak_dir = r"D:\gym3d\data\buildings\%s\.orig\floors.before_wallthin" % NAME
os.makedirs(bak_dir, exist_ok=True)

results = []
for fp in sorted(glob.glob(os.path.join(floors_dir, "floor*.json")), key=lambda s: int(s.split("floor")[-1][:-5])):
    F = int(os.path.basename(fp)[5:-5])
    fl = json.load(open(fp, encoding="utf-8"))
    if not os.path.exists(os.path.join(bak_dir, os.path.basename(fp))):
        shutil.copy2(fp, os.path.join(bak_dir, os.path.basename(fp)))

    oline = Polygon(fl["outline"])
    ol_area = oline.area
    outer = [w for w in fl["walls"] if w["type"] == "outer"]
    parapet = [w for w in fl["walls"] if w["type"] == "parapet"]
    # 外墙内空间(剪内墙用)
    interior_mask = None
    if outer and outer[0].get("holes"):
        interior_mask = Polygon(outer[0]["holes"][0]).buffer(-0.01)
    if interior_mask is None:
        interior_mask = oline.buffer(-0.16)
    if not interior_mask.is_valid:
        interior_mask = interior_mask.buffer(0)

    raw = raw_by_floor.get(F, [])
    segpolys = []
    for w in raw:
        cx2 = sum(a for a, b in w) / len(w); cy2 = sum(b for a, b in w) / len(w)
        if abs(floor_of(p, cx2, cy2) - F) > 0.5:
            continue
        loc = [(float(a), float(b)) for a, b in [to_local(p, a, b, F) for a, b in w]]
        segpolys.append(loc)
    segs = []
    for loc in segpolys:
        segs += G._flatten_wall_segments([loc])
    rects, singles = G.pair_wall_faces(segs, p)

    inner_walls = []
    for poly, t in rects:
        pc = poly.intersection(interior_mask).buffer(0)
        if pc.is_empty:
            continue
        for P in ([pc] if pc.geom_type == "Polygon" else list(pc.geoms)):
            if P.area > 0.03:
                ext = [[round(x, 3), round(y, 3)] for x, y in P.exterior.coords][:-1]
                inner_walls.append({"type": "inner", "poly": ext, "holes": [],
                                    "thickness": round(t, 2), "height": 4.2})
    for s in singles:
        pc = LineString(s).buffer(p.single_wall_t / 2).intersection(interior_mask).buffer(0)
        if pc.is_empty:
            continue
        for P in ([pc] if pc.geom_type == "Polygon" else list(pc.geoms)):
            if P.area > 0.03:
                ext = [[round(x, 3), round(y, 3)] for x, y in P.exterior.coords][:-1]
                inner_walls.append({"type": "inner", "poly": ext, "holes": [],
                                    "thickness": round(p.single_wall_t, 2), "height": 4.2})

    # ---- 验收 ----
    innerU = unary_union([Polygon(w["poly"]) for w in inner_walls]) if inner_walls else None
    inner_area = innerU.area if innerU else 0
    cover = 100 * inner_area / ol_area
    big = sum(1 for w in inner_walls if Polygon(w["poly"]).area > 0.4 * ol_area)
    # D 门贴墙(含外墙)
    wallU = unary_union([Polygon(w["poly"]) for w in fl["walls"] if w["type"] != "inner"]
                        + [Polygon(w["poly"]) for w in inner_walls]) if inner_walls else None
    nd = len(fl.get("doors", []))
    dgood = 0
    if wallU is not None and nd:
        for dd in fl["doors"]:
            if wallU.distance(Point(dd["x"], dd["y"])) < 0.5:
                dgood += 1
        dgood_pct = 100 * dgood / nd
    else:
        dgood_pct = 100
    # E 房重叠
    ovl = []
    for r in fl.get("rooms", []):
        P = Polygon(r["poly"])
        if P.is_valid and P.area > 0.5 and innerU is not None:
            ovl.append(100 * P.intersection(innerU).area / P.area)
    ov_mean = sum(ovl) / len(ovl) if ovl else 0

    ok = (len(inner_walls) > 8 and cover <= 16 and big == 0 and dgood_pct >= 90 and ov_mean <= 3)
    if ok:
        keep = [w for w in fl["walls"] if w["type"] == "inner"]
        fl["walls"] = outer + parapet + inner_walls
        json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        status = "PASS-写入"
    else:
        status = "FAIL-回滚"
    results.append((F, len(inner_walls), round(cover, 1), big, round(dgood_pct, 0), round(ov_mean, 1), ok))
    print("%s F%d: 内墙=%d 净覆盖=%.1f%% 大blob=%d 门贴墙=%.0f%% 房∩墙均=%.1f%%  %s"
          % (NAME, F, len(inner_walls), cover, big, dgood_pct, ov_mean, status))

print("通过并写入 %d/%d 层" % (sum(1 for r in results if r[-1]), len(results)))
