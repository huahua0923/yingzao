# -*- coding: utf-8 -*-
"""按新引擎口径重算交付 floors/*.json 里的 doors 数组(仅改 doors, 不碰墙/轮廓)。

背景(2026-09-10): detect_doors(geometry.py) 已从「不闭合 + 最长段 ∈ [0.6,3.0)」改成
「折线里含门扇铰对」结构判据。旧口径把**窗**(240mm 厚 × 开口宽细长矩形, 最长边就是开口宽)
和**墙垛/墙段**(没设 closed 标志的 4 点矩形)都判成了门 —— 前者是用户报的「把窗户识别成
门」, 后者顶点质心正落在墙体里, 就是「门夹在墙里看不到」。老口径下 c019 首层 87 个门里
只有 6 个是真的。

本脚本只重算 doors 数组, 墙不动(墙的假墙剔除由 _wall_thin_force.py 负责)。旧 doors 备份到
<楼>/.orig/doors.before_hinge/。写盘前打印 旧→新 计数与「门心落墙里」比例, 供人工判定。

用法: python _doors_rebuild.py c019 [c054 ...] [--dry]
"""
import json, glob, os, sys, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]
import ezdxf
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer import floor as FL

ROOT = r"D:\gym3d\data\buildings"


def wall_union(fl):
    """交付楼层全部墙的并集(扣掉 holes) —— 判「门心是不是埋在墙里」用。"""
    polys = []
    for w in fl.get("walls", []):
        p = w.get("poly") or []
        if len(p) < 3:
            continue
        P = Polygon(p)
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


def swallowed(fl, doors, tol=0.15):
    """返回 (埋在墙内的个数, 贴墙 0.15m 内的个数, 总数)。"""
    W = wall_union(fl)
    if W is None or not doors:
        return 0, 0, len(doors)
    n_in = n_near = 0
    for d in doors:
        pt = Point(d["x"], d["y"])
        if W.contains(pt):
            n_in += 1
        elif W.distance(pt) < tol:
            n_near += 1
    return n_in, n_near, len(doors)


def run(name, dry=False):
    p = load_profile(name)
    d = os.path.join(ROOT, name)
    doc = ezdxf.readfile(p.dxf)
    walls_dxf, _dr, _st, _co = classify.classify(doc.modelspace(), p)
    bak = os.path.join(d, ".orig", "doors.before_hinge")
    if not dry:
        os.makedirs(bak, exist_ok=True)
    print("\n===== %s =====" % name)
    for fp in sorted(glob.glob(os.path.join(d, "floors", "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        old = fl.get("doors", [])
        outline = Polygon(fl["outline"])
        if not outline.is_valid:
            outline = outline.buffer(0)

        wall_pts = FL.wall_pts_for_floor(F, walls_dxf, p)
        sym = [q for q in wall_pts if FL.is_door_symbol_pts(q)]
        wall_pts = [q for q in wall_pts if not FL.is_door_symbol_pts(q)]

        def near(pts):
            return Point(sum(q[0] for q in pts) / len(pts),
                         sum(q[1] for q in pts) / len(pts)).distance(outline) <= 1.0

        wall_pts = [q for q in wall_pts if near(q)]
        sym = [q for q in sym if near(q)]
        new = FL.detect_doors(wall_pts + sym, outline, p)

        oi, on, ot = swallowed(fl, old)
        ni, nn, nt = swallowed(fl, new)
        print("  F%d  门 %3d -> %3d   埋墙里 %3d(%4.1f%%) -> %3d(%4.1f%%)   贴墙内 %s"
              % (F, ot, nt, oi, 100.0 * oi / ot if ot else 0, ni,
                 100.0 * ni / nt if nt else 0,
                 "%d(%.1f%%) -> %d(%.1f%%)" % (on, 100.0 * on / ot if ot else 0,
                                               nn, 100.0 * nn / nt if nt else 0))
              , flush=True)
        if dry:
            continue
        if not os.path.exists(os.path.join(bak, os.path.basename(fp))):
            shutil.copy2(fp, os.path.join(bak, os.path.basename(fp)))
        fl["doors"] = new
        json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    print("  备份: %s" % bak)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    for nm in args:
        try:
            run(nm, dry)
        except Exception as e:  # noqa: BLE001
            print("  %s 失败: %s" % (nm, e))
