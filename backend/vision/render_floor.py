# -*- coding: utf-8 -*-
"""把某层建筑平面图渲染成 PNG（局部坐标，单位米），供视觉模型读图。

颜色约定：墙=黑、门=红、柱=蓝、楼梯=绿。与 archive/scripts/render_dxf.py 的「按图层」
渲染不同，这里走 recognizer 的分类结果（墙/门/柱/楼梯已分好），并统一 to_local 到本地米，
视觉模型看到的是跟流水线一致、且尺度真实的平面图。
"""
import io
import math

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

    # 柱（蓝）：`classify` 给的是 **(x0, y0, x1, y1, r_mm) —— 五位，不是一个矩形**。
    # ★ 这个元组的形状就是本文件原先的 500 之源：注释和解包都写着"四位矩形"，
    #   而第 5 位是半径（`recognizer/classify.py:244,254`：CIRCLE 柱记半径、
    #   LWPOLYLINE 柱记 0.0）。于是**只要这栋楼有柱**就 `too many values to unpack`，
    #   而 0 根柱的宿舍楼照常出图 —— 它就是这么躲过全库普查的。
    #   2026-09-25 实测：8130（`control.py:166` 同一个函数）与 8140 都是 500
    #   ⇒ 这是**搬过来的既存缺陷**，不是这次搬出来的。
    # ★ 有半径的按**圆**画（16 边形），不画外接方盒：方盒比同外径圆多 27% 面积，
    #   平面图上一眼是假的（与 GLB 那边 `recognize.localize_columns` 的 `round`
    #   字段同一约定）。c009 一层 40 根 Φ848 正是这一档。
    for (x0, y0, x1, y1, r) in cols:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if floor_of(p, cx, cy) != F:
            continue
        if r:
            corners = [(cx + r * math.cos(2 * math.pi * i / 16),
                        cy + r * math.sin(2 * math.pi * i / 16))
                       for i in range(17)]      # 17 点 = 闭合回起点
        else:
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
