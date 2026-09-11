# -*- coding: utf-8 -*-
"""把某层建筑平面图渲染成 PNG（局部坐标，单位米），供视觉模型读图。

颜色约定：墙=黑、门=红、柱=蓝、楼梯=绿。与 archive/scripts/render_dxf.py 的「按图层」
渲染不同，这里走 recognizer 的分类结果（墙/门/柱/楼梯已分好），并统一 to_local 到本地米，
视觉模型看到的是跟流水线一致、且尺度真实的平面图。
"""
import io

import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from recognizer.profile import to_local, floor_of
from recognizer.classify import classify
from recognizer.floor import wall_pts_for_floor


def _local_poly(points, p, F):
    """原始 CAD 坐标点列 → 本地米坐标点列。"""
    return [to_local(p, x, y, F) for x, y in points]


def render_floor_png(p, F, out_path=None, figsize=(22, 11), dpi=110):
    """渲染 p 楼的 F 层平面图，返回 PNG bytes；out_path 非空则同时落盘。"""
    doc = ezdxf.readfile(p.dxf)
    walls, doors, stairs, cols = classify(doc.modelspace(), p)

    wpts = wall_pts_for_floor(F, walls, p)   # 已是本地米

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    # 墙（黑）
    for pts in wpts:
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        ax.plot(xs, ys, color="#111", lw=1.4, solid_capstyle="round", solid_joinstyle="round")

    # 门（红）
    for dpts in doors:
        cx = sum(q[0] for q in dpts) / len(dpts)
        cy = sum(q[1] for q in dpts) / len(dpts)
        if floor_of(p, cx, cy) != F:
            continue
        L = _local_poly(dpts, p, F)
        ax.plot([q[0] for q in L], [q[1] for q in L], color="#e11", lw=1.2, alpha=0.9)

    # 柱（蓝）：cols 是 (x0, y0, x1, y1) 矩形
    for (x0, y0, x1, y1) in cols:
        if floor_of(p, (x0 + x1) / 2, (y0 + y1) / 2) != F:
            continue
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        L = _local_poly(corners, p, F)
        ax.plot([q[0] for q in L], [q[1] for q in L], color="#16c", lw=1.6)

    # 楼梯（绿）
    for spts in stairs:
        if floor_of(p, spts[0][0], spts[0][1]) != F:
            continue
        L = _local_poly(spts, p, F)
        ax.plot([q[0] for q in L], [q[1] for q in L], color="#0a8", lw=1.6)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    buf.seek(0)
    png = buf.getvalue()

    if out_path:
        with open(out_path, "wb") as f:
            f.write(png)
    return png
