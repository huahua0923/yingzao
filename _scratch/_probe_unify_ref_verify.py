# -*- coding: utf-8 -*-
"""验证改后的 reference_outline_for：走生产函数，对照旧「面积最大」口径(只读)。

对每栋用 unify 的楼，分别取:
  旧口径 ref = 面积最大的层（模拟改前逻辑）
  新口径 ref = FL.reference_outline_for(...)  ← 生产函数
再按同一套墙几何算出「统一集合各层总越界」，对比。期望: 新 ≤ 旧, 且 20 栋里只有
c006/c072/c073 的基准层变化。
"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

import ezdxf
from shapely.geometry import Polygon
from run_building import load_profile
from backend.recognizer import floor as FL

ROOT = r"D:\gym3d\data\buildings"


def wall_geoms_of(p, walls, F):
    tr = (p.transition or {}).get(F)
    pts = FL.wall_pts_for_floor(F, walls, p, tr.get("wall_x") if tr else None)
    _o, geoms, _t = FL.derive_walls_and_outline(pts, p)
    return [g for g in geoms if g is not None and not g.is_empty]


def cost(polys_by_F, T):
    tot = 0.0
    for _F, polys in polys_by_F.items():
        a = out = 0.0
        for g in polys:
            if g.area <= 1e-9:
                continue
            a += g.area
            out += g.area - g.intersection(T).area
        tot += (out / a) if a > 0 else 1.0
    return tot


def run(name):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    if getattr(p, "classifier", "lwpolyline") == "line":
        from backend.recognizer.classify_line import classify_line
        walls, _d, _s, _c = classify_line(doc.modelspace(), p)
    else:
        from backend.recognizer import classify
        walls, _d, _s, _c = classify.classify(doc.modelspace(), p)

    floors = sorted({FL.floor_of(p, sum(q[0] for q in pts) / len(pts),
                                sum(q[1] for q in pts) / len(pts)) for pts in walls})
    unify = sorted(FL.unify_floor_set(p, floors))
    if not unify:
        return None
    own, polys = {}, {}
    for F in unify:
        o, geoms, _t = FL.derive_walls_and_outline(
            FL.wall_pts_for_floor(F, walls, p,
                                 ((p.transition or {}).get(F) or {}).get("wall_x")), p)
        if o is None or o.is_empty:
            continue
        own[F] = o
        polys[F] = [g for g in geoms if g is not None and not g.is_empty]
    if not own:
        return None
    old_ref = max(own, key=lambda F: own[F].area)
    new_ref, new_out = FL.reference_outline_for(p, walls, floors)
    co, cn = cost(polys, own[old_ref]), cost(polys, new_out)
    return name, old_ref, co, new_ref, cn


print("%-6s %-8s %-10s | %-8s %-10s | %s" % ("楼", "旧基准", "旧总越界", "新基准", "新总越界", "判定"))
worse = 0
for n in sorted(os.listdir(ROOT)):
    fp = os.path.join(ROOT, n, "profile.json")
    if not os.path.exists(fp):
        continue
    d = json.load(open(fp, encoding="utf-8"))
    if not (d.get("outline_unify") or d.get("outline_unify_floors")):
        continue
    try:
        r = run(n)
    except Exception as e:  # noqa: BLE001
        print("%-6s 失败: %s" % (n, e))
        continue
    if r is None:
        print("%-6s (无轮廓)" % n)
        continue
    nm, of, co, nf, cn = r
    verdict = "不变" if nf == of else ("改善" if cn <= co + 1e-9 else "*** 变差 ***")
    if cn > co + 1e-9:
        worse += 1
    print("%-6s %-8s %9.2f%% | %-8s %9.2f%% | %s" % (nm, "F%d" % of, co * 100, "F%d" % nf, cn * 100, verdict))
print("\n变差的楼: %d 栋" % worse)
