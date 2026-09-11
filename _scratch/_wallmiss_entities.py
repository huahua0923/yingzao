# -*- coding: utf-8 -*-
"""把每层漏点归因到源图直run，打印过半漏的run与几何。用法: python _wallmiss_entities.py <name> <F>"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import _dxf_audit as A
import _dxf_cad_render as R
import run_step
import ezdxf
import shapely.geometry as sg
from recognizer.profile import to_local, floor_of

name, F = sys.argv[1], int(sys.argv[2])
p = run_step.load_profile(name)
doc = ezdxf.readfile(p.dxf)
fl = json.load(open(f"data/buildings/{name}/floors/floor{F}.json", encoding="utf-8"))
ol = fl["outline"]
box = (min(q[0] for q in ol), min(q[1] for q in ol),
       max(q[0] for q in ol), max(q[1] for q in ol))
cov = A._walls_geom(fl)
import shapely as _sh
prep = _sh.prepared.prep(cov.buffer(A.WALL_DIST)) if (cov is not None and not cov.is_empty) else None
mask = A._door_zone_mask(fl)
layer = getattr(p, "wall_layer", None) or "4.2墙体"

pool = []
for e in doc.modelspace():
    if e.dxftype() == "INSERT":
        pool.extend(e.virtual_entities() or [])
    elif e.dxftype() in ("LWPOLYLINE", "LINE", "ARC", "CIRCLE", "SPLINE"):
        pool.append(e)

res = []
for e in pool:
    if (getattr(e.dxf, "layer", "") or "") != layer:
        continue
    if e.dxftype() in ("ARC", "CIRCLE", "SPLINE"):
        continue
    try:
        if e.dxftype() == "LINE":
            rv = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        else:
            rv = list(e.get_points("xy"))
    except Exception:
        continue
    if len(rv) < 2:
        continue
    try:
        fs = {int(round(floor_of(p, float(a), float(b)))) for a, b in rv[:20]}
    except Exception:
        continue
    if fs != {F}:
        continue
    lv = [to_local(p, float(a), float(b), F) for a, b in rv]
    # 主副本过滤(同 audit): 先在原始顶点 bBox 过滤, 拒绝的实体不再密化
    x0, y0, x1, y1 = box
    bw = (x1 - x0) + 5.0
    bh = (y1 - y0) + 5.0
    ax = min(q[0] for q in lv)
    bx = max(q[0] for q in lv)
    ay = min(q[1] for q in lv)
    by = max(q[1] for q in lv)
    if (bx - ax) > bw or (by - ay) > bh:
        continue
    if bx < x0 - 1.5 or ax > x1 + 1.5 or by < y0 - 1.5 or ay > y1 + 1.5:
        continue
    closedf = (e.dxftype() == "LWPOLYLINE" and bool(getattr(e, "closed", False)))
    local = A._dense_local(lv, A.SAMP, closedf)
    if not local:
        continue
    for run in A._split_runs(local):
        L = sum(((run[i + 1][0] - run[i][0]) ** 2 +
                 (run[i + 1][1] - run[i][1]) ** 2) ** 0.5
                for i in range(len(run) - 1))
        if L < A.MIN_ENTITY or A._sagitta(run) > 0.12:
            continue
        nm = 0.0
        for (x, y) in run:
            if mask and A._in_any_door_zone(x, y, mask):
                continue
            if prep is None or not prep.covers(sg.Point(x, y)):
                nm += A.SAMP
        if nm >= 0.3:
            xs = [q[0] for q in run]
            ys = [q[1] for q in run]
            res.append(dict(nm=nm, L=L, cx=(min(xs) + max(xs)) / 2,
                            cy=(min(ys) + max(ys)) / 2,
                            x0=min(xs), x1=max(xs), y0=min(ys), y1=max(ys),
                            t=e.dxftype(), npt=len(run)))
res.sort(key=lambda r: -r["nm"])
print(f"{name} F{F} 漏run(>=1m且过半漏) {len(res)} 条 总漏 {sum(r['nm'] for r in res):.1f}m")
for r in res:
    print("  漏%.1f/%.1fm 中心(%.1f,%.1f) bbox x[%.1f,%.1f] y[%.1f,%.1f] %s pts%d"
          % (r["nm"], r["L"], r["cx"], r["cy"], r["x0"], r["x1"], r["y0"], r["y1"],
             r["t"], r["npt"]))
