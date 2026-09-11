# -*- coding: utf-8 -*-
"""任意楼/层区域叠加图：源直墙线(修复后口径, 蓝) vs 识别墙 poly(floor.json, 红)
用法: python _overlay_region.py <name> <F> <x0> <y0> <x1> <y1> [out.png]
坐标=本地米（本地 x 向右, y 向【上】→ 用 -y 画让建筑上南下北? 按 floor 约定）。
"""
import os, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import ezdxf
import shapely.geometry as sg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly
import _dxf_audit as A
import _dxf_cad_render as R
import run_step
from recognizer.profile import to_local, floor_of

BASE = r"D:\gym3d\data\buildings"


def main():
    name, F = sys.argv[1], int(sys.argv[2])
    x0, y0, x1, y1 = [float(v) for v in sys.argv[3:7]]
    out = sys.argv[7] if len(sys.argv) > 7 else f"_ov_{name}_F{F+1}.png"
    p = run_step.load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    fl = json.load(open(os.path.join(BASE, name, "floors", f"floor{F}.json"),
                        encoding="utf-8"))
    layer = p.wall_layer or "4.2墙体"
    CURVED = ("ARC", "CIRCLE", "SPLINE")
    fig, ax = plt.subplots(figsize=(10, 8))
    # 源直墙线：蓝
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
        axx = [q[0] for q in local]; ayy = [-q[1] for q in local]
        for run in A._split_runs(local):
            L = sum(((run[i + 1][0] - run[i][0]) ** 2 + (run[i + 1][1] - run[i][1]) ** 2) ** 0.5
                    for i in range(len(run) - 1))
            if L < A.MIN_ENTITY or A._sagitta(run) > 0.12:
                continue
            if e.dxftype() == "LWPOLYLINE" and getattr(e, "closed", False):
                try:
                    pg = sg.Polygon(run)
                    if pg.is_valid and pg.area > 1e-6 and pg.area / pg.length > 1.0:
                        continue
                except Exception:
                    pass
            xs = [q[0] for q in run]; ys = [-q[1] for q in run]
            ax.plot(xs, ys, "-", color="#2277cc", lw=1.1,
                    solid_capstyle="butt")
    # 识别墙 poly：红(半透明填 + 边)
    for w in fl.get("walls", []):
        ring = [(float(q[0]), -float(q[1])) for q in w.get("poly", [])]
        if len(ring) < 3:
            continue
        try:
            ax.add_patch(MplPoly(ring, closed=True, fill=True,
                                 facecolor="#e63a3a", alpha=0.35,
                                 edgecolor="#a11", lw=0.6))
        except Exception:
            pass
    ax.set_xlim(x0, x1); ax.set_ylim(-y1, -y0)
    ax.set_aspect("equal")
    ax.set_title(f"{name} F{F+1} 本地 x∈[{x0},{x1}] y∈[{-y1},{-y0}] 蓝=源直墙 红=模型")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print(out)


if __name__ == "__main__":
    main()
