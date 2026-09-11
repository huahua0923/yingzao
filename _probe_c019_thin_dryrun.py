# -*- coding: utf-8 -*-
"""c019 生产链干跑（**全程不写盘**）：recognize 临时产物 → rebuild_floor(含门洞) → verify。

交付链 = recognize() -> _wall_thin_force.py（内墙重建，会覆盖 recognize 的内墙）。
本探针在内存里对 _tmp_<name>_door 的楼层跑 rebuild_floor + _punch_doors，
逐层报 verify 四条门槛 + 门洞挖穿率（±0.4m 沿墙走向出墙），确认可交付。

用法: python _probe_c019_thin_dryrun.py [name=c019]
"""
import os, sys, glob, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from shapely.geometry import Polygon, Point
import _wall_thin_batch as B

NAME = sys.argv[1] if len(sys.argv) > 1 else "c019"
TMP = r"D:\gym3d\_tmp_%s_door" % NAME


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


def cut_stats(walls, doors):
    P = [W(w) for w in walls]
    n = nc = nt = 0
    for d in doors:
        n += 1
        c = Point(d["x"], d["y"])
        if any(Q.contains(c) for Q in P):
            continue
        nc += 1
        ok = True
        for sgn in (1, -1):
            q = (Point(d["x"] + sgn * 0.4, d["y"]) if d["horiz"]
                 else Point(d["x"], d["y"] + sgn * 0.4))
            if any(Q.contains(q) for Q in P):
                ok = False
                break
        if ok:
            nt += 1
    return n, nc, nt


def main():
    p = B.load_profile(NAME)
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    walls_dxf, _doors, _stairs, _cols = B.classify.classify(msp, p)
    raw_by_floor = B.wall_lines_by_floor(p, walls_dxf)

    print("%-4s | %-38s | %-38s" % ("层", "recognize 原始内墙: 条/覆盖/门挖穿", "重建+门洞后: 条/覆盖/门挖穿/verify"))
    tot = totc = 0
    for fp in sorted(glob.glob(os.path.join(TMP, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        ol = Polygon(fl["outline"])
        if not ol.is_valid:
            ol = ol.buffer(0)
        raw = raw_by_floor.get(F, [])
        inner, rect = B.rebuild_floor(fl, p, raw, F)
        if inner is None:
            print("  F%-2d | rebuild_floor 返回 None（无墙线）" % F)
            continue
        keep = [w for w in fl["walls"] if w["type"] != "inner"]
        new_walls = keep + inner
        ol_ = Polygon(fl["outline"])
        _ok, nw, cover, big, dgood, ovm = B.verify_floor(fl, inner, ol_, ol_.area)
        n0, c0, t0 = cut_stats(fl["walls"], fl.get("doors", []))
        n1, c1, t1 = cut_stats(new_walls, fl.get("doors", []))
        tot += n1; totc += t1
        print("  F%-2d | 内墙%3d 门挖穿%2d/%2d            | 内墙%3d 覆盖%4.0f%% 挖穿%2d/%2d rect%3.0f%% | "
              "条>8:%s 覆盖<=20:%s 大块0:%s 贴墙>=85:%s 房叠<=10:%s -> %s"
              % (F, sum(1 for w in fl["walls"] if w["type"] == "inner"), t0, n0,
                 nw, cover, t1, n1, 100 * rect,
                 nw > 8, cover <= 20, big == 0, dgood >= 85, ovm <= 10,
                 "PASS" if _ok else "FAIL"))
    print("\n总门 %d, 重建后挖穿 %d (%.0f%%)" % (tot, totc, 100.0 * totc / max(tot, 1)))


if __name__ == "__main__":
    main()
