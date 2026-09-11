# -*- coding: utf-8 -*-
"""c006 弧墙带加入后「轮廓外墙体」回归的定位探针(只读, 不写盘)。

现象: 交付 c006 各层「轮廓外墙体」仅 0.2~0.6%; 新引擎(ARC → pair_arc_bands → 实心墙带)
跑 _tmp_c006_arc 后 F2/F3 = 8.7%, F4 = 6.9%, F5 = 7.7%。同时轮廓面积还变大了
(裙楼 5365.9 → 5699.4 ㎡)。轮廓变大却让更多墙落到外面 —— 说明新轮廓不是旧轮廓的超集。

三个量(逐层):
  A 旧口径: 关掉 pair_arc_bands（模拟交付版）→ 各层自己算轮廓
  B 新·独立: 开弧带, 但**不统一**, 每层用自己的轮廓 → 看弧带本身是否自洽
  C 新·统一: 开弧带 + 复用基准轮廓(现实生产路径) → 复现 8.7%

再打印: 统一集合每层自己轮廓的面积 / 基准层是谁 / 基准轮廓面积, 以及
B 情形下每层轮廓与基准轮廓的双向差(谁多出哪块)。

用法: python _probe_c006_outline.py [c006]
"""
import os, sys, io, contextlib
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

import ezdxf
from shapely.geometry import Polygon
from shapely.ops import unary_union
from run_building import load_profile
from backend.recognizer import floor as FL
from backend.recognizer import recognize as RC


def wall_area_pt(poly, T):
    """墙多边形(poly 为点列)在 T 之外的部分面积 / 总面积。"""
    P = Polygon(poly)
    if not P.is_valid:
        P = P.buffer(0)
    if P.is_empty or P.area <= 1e-9:
        return 0.0, 0.0
    inter = P.intersection(T)
    return P.area - inter.area, P.area


def outside_pct(pts_list, outline):
    if outline is None or outline.is_empty:
        return 100.0, 0
    T = outline.buffer(0)
    tot_out = tot = 0.0
    n_bad = 0
    for poly, _t in pts_list:
        o, a = wall_area_pt(poly, T)
        tot_out += o
        tot += a
        if a > 1e-6 and o / a > 0.5:
            n_bad += 1
    return (100.0 * tot_out / tot if tot else 0.0), n_bad


def build(p, walls, F, with_bands=True):
    """返回 (墙多边形列表[(pts, t)], 该层自己的轮廓)。with_bands=False 模拟旧口径。"""
    tr = (p.transition or {}).get(F)
    wall_x = tr.get("wall_x") if tr else None
    clip = tr.get("wall_x_clip") if tr else None
    pts = FL.wall_pts_for_floor(F, walls, p, wall_x, clip)

    from backend.recognizer import geometry as G
    if not with_bands:
        # 旧口径：curved_walls 关掉(生产的 switch), 且 classify_line 不产弧带 ——
        # 这里直接在 wall_pts 里剔除「>=4 点闭合」实心带, 等价还原交付时输入。
        pts = [q for q in pts
               if not (len(q) >= 4 and abs(q[0][0] - q[-1][0]) <= 1e-6
                       and abs(q[0][1] - q[-1][1]) <= 1e-6)]
    o, geoms, ts = FL.derive_walls_and_outline(pts, p)
    return list(zip([list(g.exterior.coords) if hasattr(g, "exterior") else list(g.coords) for g in geoms],
                    ts)), o


def main(name):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    from backend.recognizer.classify_line import classify_line
    walls, _d, _s, _c = classify_line(doc.modelspace(), p)

    floors = sorted({FL.floor_of(p, sum(q[0] for q in pts) / len(pts),
                                sum(q[1] for q in pts) / len(pts)) for pts in walls})
    unify = FL.unify_floor_set(p, floors)
    print("===== %s  层=%s  统一集合=%s =====" % (name, floors, sorted(unify)))

    own = {}
    print("\n-- B) 新·独立：每层用自己的轮廓 --")
    for F in floors:
        wb, ob = build(p, walls, F, True)
        wo, oo = build(p, walls, F, False)
        own[F] = ob
        pb, nb = outside_pct(wb, ob)
        po, no = outside_pct(wo, oo)
        mark = "  <-- 统一集合" if F in unify else ""
        print("  F%-2d  旧: 轮廓%9.1f㎡ 越界%5.2f%%(%d)   新: 轮廓%9.1f㎡ 越界%5.2f%%(%d)%s"
              % (F, oo.area if oo else 0, po, no, ob.area if ob else 0, pb, nb, mark))

    ref_F, ref_out = FL.reference_outline_for(p, walls, floors)
    print("\n-- C) 新·统一：基准层 F%s 面积 %.1f ㎡ --" % (ref_F, ref_out.area if ref_out else 0))
    for F in sorted(unify):
        wb, _ob = build(p, walls, F, True)
        pc, ncb = outside_pct(wb, ref_out)
        print("  F%-2d  统一轮廓越界 %5.2f%%  (%d 块过半在外)" % (F, pc, ncb))

    # 谁跟基准不一样
    print("\n-- B vs C：各层自己轮廓 与 基准轮廓 的双向差 --")
    for F in sorted(unify):
        o = own.get(F)
        if o is None or ref_out is None:
            continue
        a, b = o.buffer(0), ref_out.buffer(0)
        add = b.difference(a).area     # 基准比本层多(本层墙会落在基准里, 不越界)
        cut = a.difference(b).area     # 本层比基准多(这部分墙必然越界)
        print("  F%-2d  本层%8.1f  基准%8.1f  |  基准多出 %7.1f ㎡   本层多出 %7.1f ㎡"
              % (F, a.area, b.area, add, cut))


if __name__ == "__main__":
    for nm in (sys.argv[1:] or ["c006"]):
        try:
            main(nm)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print("  %s 失败: %s" % (nm, e))
