# -*- coding: utf-8 -*-
"""定位任意楼任意层「直墙源线漏检段」：跑在哪、多长、聚在哪、像什么。
用法: python _wallmiss_locate.py <name> [F0, F1, ...]    F 内部0-based
修复后口径：只算 LWPOLYLINE/LINE、剔除闭口填充面与曲要素。输出前 N 大漏段。
"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import ezdxf
import shapely.geometry as sg
import _dxf_audit as A
import _dxf_cad_render as R
import run_step
from recognizer.profile import to_local, floor_of

BASE = r"D:\gym3d\data\buildings"


def locate(name, F, topn=24):
    p = run_step.load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    fj = os.path.join(BASE, name, "floors", f"floor{F}.json")
    fl = json.load(open(fj, encoding="utf-8"))
    ol = fl["outline"]
    box = (min(q[0] for q in ol), min(q[1] for q in ol),
           max(q[0] for q in ol), max(q[1] for q in ol))
    cov = A._walls_geom(fl)
    if cov is None or cov.is_empty:
        print(f"{name} F{F+1}: 无识别墙"); return
    layer = p.wall_layer or "4.2墙体"
    x0, y0, x1, y1 = box; bw, bh = (x1 - x0) + 5.0, (y1 - y0) + 5.0
    outl = sg.Polygon(ol)
    CURVED = ("ARC", "CIRCLE", "SPLINE")
    runs = []
    for e in doc.modelspace():
        if e.dxftype() in CURVED or (getattr(e.dxf, "layer", "") or "") != layer:
            continue
        xy = R._entity_floor(e)
        if xy is None or int(round(floor_of(p, xy[0], xy[1]))) != F:
            continue
        pts = R._sampled_pts(e, p, F, A.SAMP)
        if not pts:
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        ax = min(q[0] for q in local); bx = max(q[0] for q in local)
        ay = min(q[1] for q in local); by = max(q[1] for q in local)
        if (bx - ax) > bw or (by - ay) > bh or bx < x0 - 1.5 or ax > x1 + 1.5 or by < y0 - 1.5 or ay > y1 + 1.5:
            continue
        if e.dxftype() == "LWPOLYLINE" and getattr(e, "closed", False):
            try:
                pg = sg.Polygon(local)
                if pg.is_valid and pg.area > 1e-6 and pg.area / pg.length > 1.0:
                    continue
            except Exception:
                pass
        for run in A._split_runs(local):
            L = sum(((run[i + 1][0] - run[i][0]) ** 2 + (run[i + 1][1] - run[i][1]) ** 2) ** 0.5
                    for i in range(len(run) - 1))
            if L < A.MIN_ENTITY or A._sagitta(run) > 0.12:
                continue
            miss = 0.0
            for (x, y) in run:
                if cov.distance(sg.Point(x, y)) > A.WALL_DIST:
                    miss += A.SAMP
            if miss > 0.5:
                mid = sg.LineString(run).interpolate(0.5, normalized=True)
                runs.append(dict(miss=miss, L=L, x=mid.x, y=mid.y,
                                 dout=mid.distance(outl.exterior)))
    runs.sort(key=lambda r: -r["miss"])
    tot = sum(r["miss"] for r in runs)
    print(f"\n=== {name} F{F+1} 直墙漏检>=0.5m 段 {len(runs)} 条 / 合计 {tot:.1f}m ===")
    print(f"  {'漏':>5}{'段长':>6}{'中点x':>9}{'中点y':>9}{'距外':>6}  判读")
    for r in runs[:topn]:
        kind = "近外(<0.6)" if r["dout"] < 0.6 else "楼内"
        print(f"  {r['miss']:>5.1f}{r['L']:>6.1f}{r['x']:>9.2f}{r['y']:>9.2f}"
              f"{r['dout']:>6.2f}   {kind}")
    return runs


if __name__ == "__main__":
    name = sys.argv[1]
    for F in [int(x) for x in (sys.argv[2:] or ["1"])]:
        locate(name, F)
