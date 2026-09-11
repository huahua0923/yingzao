# -*- coding: utf-8 -*-
"""c019「门符号不进墙 + 新门判据」的**纯内存模拟**(只读, 不写盘)。

为什么要有它: _doors_rebuild.py --dry 只换了门、墙还是旧的, 而 c019 那 213~290 块/层
假墙**正是门符号自己配出来的** —— 门符号质心当然落在这堆假墙里, 所以「埋墙里」这个指标
在墙重建之前不可能下降(实测仍 84~98%)。必须把「新墙 + 新门」拼在一起量才有意义。

流程(逐层, 全部在内存):
  raw        = B.wall_lines_by_floor(p, walls_dxf)          # 已剔除门符号
  new_inner  = B.rebuild_floor(fl, p, raw[F], F)            # 新内墙
  walls_new  = [type != inner 的原墙] + new_inner           # 外墙不动
  doors_new  = FL.detect_doors(wall_pts + door_sym_pts)     # 新门(与生产同源)
量三个数: 新门 × 旧墙 / 新门 × 新墙 / 旧门 × 新墙 的「埋墙里」「贴墙内」比例。

用法: python _probe_door_fix_sim.py c019
"""
import json, glob, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]
import ezdxf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer import floor as FL
import _wall_thin_batch as B

ROOT = r"D:\gym3d\data\buildings"


def walls_union(wall_list):
    polys = []
    for w in wall_list:
        q = w.get("poly") or []
        if len(q) < 3:
            continue
        P = Polygon(q)
        if not P.is_valid:
            P = P.buffer(0)
        if P.is_empty:
            continue
        for h in w.get("holes", []) or []:
            if len(h) >= 3:
                H = Polygon(h)
                if H.is_valid and not H.is_empty:
                    P = P.difference(H)
        if not P.is_empty:
            polys.append(P)
    if not polys:
        return None
    U = unary_union(polys)
    return U.buffer(0) if not U.is_valid else U


def stat(W, doors, tol=0.15):
    if W is None or not doors:
        return 0, 0, 0
    ni = nn = 0
    for d in doors:
        pt = Point(d["x"], d["y"])
        if W.contains(pt):
            ni += 1
        elif W.distance(pt) < tol:
            nn += 1
    return ni, nn, len(doors)


def main(name):
    p = load_profile(name)
    d = os.path.join(ROOT, name)
    doc = ezdxf.readfile(p.dxf)
    walls_dxf, _a, _b, _c = classify.classify(doc.modelspace(), p)
    raw_by_floor = B.wall_lines_by_floor(p, walls_dxf)
    print("===== %s =====" % name)
    print("  层  旧门  新门 | 旧门×旧墙  新门×旧墙  新门×新墙   新内墙数 内墙覆盖")
    for fp in sorted(glob.glob(os.path.join(d, "floors", "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        outline = Polygon(fl["outline"])
        if not outline.is_valid:
            outline = outline.buffer(0)

        wall_pts = FL.wall_pts_for_floor(F, walls_dxf, p)
        sym = [q for q in wall_pts if FL.is_door_symbol_pts(q)]
        wall_pts = [q for q in wall_pts if not FL.is_door_symbol_pts(q)]

        def near(q):
            return Point(sum(t[0] for t in q) / len(q),
                         sum(t[1] for t in q) / len(q)).distance(outline) <= 1.0

        wall_pts = [q for q in wall_pts if near(q)]
        sym = [q for q in sym if near(q)]
        doors_new = FL.detect_doors(wall_pts + sym, outline, p)
        doors_old = fl.get("doors", [])

        raw = raw_by_floor.get(F, [])
        try:
            new_inner, rect_share = B.rebuild_floor(fl, p, raw, F)
        except Exception as e:  # noqa: BLE001
            print("  F%d  rebuild 异常: %s" % (F, e))
            continue
        if new_inner is None:
            print("  F%d  无墙线, 跳过" % F)
            continue
        keep = [w for w in fl["walls"] if w["type"] != "inner"]
        walls_new = keep + new_inner

        W_old = walls_union(fl["walls"])
        W_new = walls_union(walls_new)
        a = stat(W_old, doors_old)
        b = stat(W_old, doors_new)
        c = stat(W_new, doors_new)
        innerU = walls_union(new_inner)
        cover = 100.0 * innerU.area / outline.area if innerU is not None else 0
        print("  F%-2d %4d %5d | %3d/%3d   %3d/%3d   %3d/%3d     %4d   %5.1f%%"
              % (F, len(doors_old), len(doors_new),
                 a[0], a[2], b[0], b[2], c[0], c[2], len(new_inner), cover))
        print("        门符号 %d 条 / 墙线 %d 条 / 旧内墙 %d 条"
              % (len(sym), len(raw), sum(1 for w in fl["walls"] if w["type"] == "inner")))


if __name__ == "__main__":
    for nm in sys.argv[1:]:
        try:
            main(nm)
        except Exception as e:  # noqa: BLE001
            print("  %s 失败: %s" % (nm, e))
