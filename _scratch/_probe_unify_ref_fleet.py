# -*- coding: utf-8 -*-
"""outline_unify 基准层「换目标函数」的舰队影响面(只读, 不写盘)。

背景: c006 加弧墙带后, reference_outline_for 按「面积最大」把基准层从 F2 翻成 F0
(F0 5699.3 vs F2 5694.4, 只差 0.09%), 而两层形状对称差 1120㎡(边界均值摆动 1.3m),
导致 F2~F5「轮廓外墙体」从 0.5% 涨到 10%。按「六层总越界最小」选则是 F2, 总越界
42.0% → 16.4%。

「面积最大」是「墙最完整」的代理指标, 会在面积接近时抛硬币, 与真正要保的不变量
(墙落在轮廓内)脱钩。本探针量: 改成「候选层里总越界最小」后, 20 栋用 unify 的楼
各自基准层会不会变、总越界变好还是变差。

候选过滤: 面积 >= AREA_GUARD * 最大面积 (防止选中碎片化塌成的怪轮廓)。

用法: python _probe_unify_ref_fleet.py            # 全部 unify 楼
      python _probe_unify_ref_fleet.py c006 c009
"""
import os, sys, traceback
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

import ezdxf
from shapely.geometry import Polygon
from run_building import load_profile
from backend.recognizer import floor as FL

ROOT = r"D:\gym3d\data\buildings"
AREA_GUARD = 0.70


def derive(p, walls, F):
    tr = (p.transition or {}).get(F)
    pts = FL.wall_pts_for_floor(F, walls, p, tr.get("wall_x") if tr else None,
                                tr.get("wall_x_clip") if tr else None)
    o, g, _t = FL.derive_walls_and_outline(pts, p)
    polys = []
    for x in g:
        # g 里可能是 MultiPolygon（曲墙带 union 后），逐片拆开
        if hasattr(x, "geoms"):
            parts = list(x.geoms)
        else:
            parts = [Polygon(x)]
        for part in parts:
            if not isinstance(part, Polygon):
                part = Polygon(part)
            if not part.is_valid:
                part = part.buffer(0)
            if not part.is_empty and part.area > 1e-9:
                polys.append(part)
    return (o.buffer(0) if o is not None else None), polys


def outpct(polys, T):
    if T is None or T.is_empty:
        return 100.0
    tot = out = 0.0
    for P in polys:
        tot += P.area
        out += P.area - P.intersection(T).area
    return 100.0 * out / tot if tot else 0.0


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
        print("%-6s 无 unify 集合, 跳过" % name)
        return

    own, polys = {}, {}
    for F in unify:
        try:
            o, pl = derive(p, walls, F)
        except Exception as e:  # noqa: BLE001
            print("%-6s F%d 派生失败: %s" % (name, F, e))
            return
        if o is None or o.is_empty:
            continue
        own[F], polys[F] = o, pl
    Fs = sorted(own)
    if not Fs:
        print("%-6s unify 集合无有效轮廓" % name)
        return

    max_area = max(own[F].area for F in Fs)
    old_ref = max(Fs, key=lambda F: own[F].area)
    colsum = {R: sum(outpct(polys[F], own[R]) for F in Fs) for R in Fs}
    cand = [R for R in Fs if own[R].area >= AREA_GUARD * max_area]
    new_ref = min(cand, key=lambda R: colsum[R]) if cand else old_ref

    flag = "  基准层变了!" if new_ref != old_ref else ""
    print("%-6s 层%s | 旧基准 F%-2d 总越界 %7.2f%% | 新基准 F%-2d 总越界 %7.2f%%%s"
          % (name, Fs, old_ref, colsum[old_ref], new_ref, colsum[new_ref], flag))
    if new_ref != old_ref:
        print("       逐层(对照新基准): " + "  ".join(
            "F%d=%.2f%%" % (F, outpct(polys[F], own[new_ref])) for F in Fs))
        print("       面积: " + "  ".join("F%d=%.0f" % (F, own[F].area) for F in Fs))


names = [a for a in sys.argv[1:] if not a.startswith("--")]
if not names:
    names = []
    for n in sorted(os.listdir(ROOT)):
        fp = os.path.join(ROOT, n, "profile.json")
        if not os.path.exists(fp):
            continue
        import json
        d = json.load(open(fp, encoding="utf-8"))
        if d.get("outline_unify") or d.get("outline_unify_floors"):
            names.append(n)
for nm in names:
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print("%-6s 失败: %s" % (nm, e))
