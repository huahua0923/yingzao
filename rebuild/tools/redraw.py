# -*- coding: utf-8 -*-
"""把**识别结果**重画成一张图纸（PNG + DXF），给用户「框问题」用；并对外暴露**纯几何**。

重画的四样（都来自图上已有的东西，没有一处是我编的）：
  · 墙  —— `recognize.analyze()` 判出的墙带（栅格 → 闭合多段线，外环 + 内洞）
  · 柱  —— 图层 `4.1结构柱` 的 INSERT 块（`_FZHK` 方 / `_YZHK` 圆），按块展开
  · 门  —— 图层 `4.2墙体` 的 INSERT 块 `$DorLib2D$*`（门扇 + 开启弧），按块展开
  · 梯  —— `recognize.stair_zones()` 圈定的踏步线（短平行线）

★ 拆成 `geometry()` / `draw()` / `render()` 三级，**只允许一份几何实现**：
  · `geometry(floor)`：纯数据（mm 坐标的多边形/折线），**不碰 matplotlib** —— 三维建模直接吃它；
  · `draw(floor)`：     把几何画进一个坐标轴（数据坐标 = mm），返回 `(fig, ax, v)`；
  · `render(floor)`：   画 + 存 PNG + 写 DXF。
  拆开的第一动机是审图框：`review_index` 的红虚框必须与墙在**同一数据坐标系**里。第一版把
  画好的 PNG 再 `imread` 贴回来、在**像素**轴上按 mm 坐标画框 ⇒ 框落在 116000 像素处（画布外），
  **图上看不见却不报错**（静默假绿）。所以绘图只能有一份实现，叠加与出图共用它。
  第二动机：三维拉伸要与审图**吃同一份墙带**，不许另起炉灶再判一次墙。

输出：
  rebuild/03_redraw/<层名>_plan.png   审图
  rebuild/03_redraw/<层名>_full.dxf   重画图（层 WALL/COL/DOOR/STAIR）
用法：python rebuild/tools/redraw.py --floor 8层     # 单层
      python rebuild/tools/redraw.py --all           # 全部楼层，一个进程（实测 12 层 72.2 s → 57.1 s）
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import ezdxf
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import recognize as R                                                   # noqa: E402

RAW = os.path.join(ROOT, "01_cad", "raw")
OUT = os.path.join(ROOT, "03_redraw")
COL_LAYER = "4.1结构柱"
DOOR_PREFIX = "$DorLib2D$"
# ★ 楼板轮廓：墙带**不闭合**（门窗洞口）+ 直接填洞＝填不出来（实测＝墙面积）。
#   先按此直径闭运算**桥接洞口**，再填洞 ⇒ 得到整层楼面外轮廓。
PLATE_CLOSE_MM = 2500.0


# ------------------------------------------------------------------ 取块（柱 / 门）
def blocks_wcs(path, layer=None, prefix=None):
    """把符合条件的 INSERT 展开成 WCS 下的折线列表 [(pts, closed)]。

    ★ 一律走 `ezdxf.path.make_path` 再 flatten —— 不是自己读 `dxf.center`。
      为什么：块里的 ARC/CIRCLE 的 `center` 是 **OCS** 坐标；门块大量带**负缩放**
      （镜像开门方向），OCS↔WCS 一翻，自己算的圆心就飞到图纸外
      （实测飞到 x≈−100000）。make_path 自己处理 OCS，一次解决。
    """
    from ezdxf import path as ezpath

    doc = ezdxf.readfile(path)
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "INSERT":
            continue
        if layer and e.dxf.layer != layer:
            continue
        if prefix and not e.dxf.name.startswith(prefix):
            continue
        try:
            vs = list(e.virtual_entities())
        except Exception:
            continue
        for v in vs:
            try:
                p = ezpath.make_path(v)
            except Exception:
                continue
            pts = [(q.x, q.y) for q in p.flattening(15.0)]
            if len(pts) >= 2:
                out.append((pts, False))
    return out


def _contour_mm(c, res, ox, oy):
    """cv2 像素轮廓 → mm 坐标点列。"""
    return [tuple(p) for p in (c[:, 0, :].astype(float) * res + [ox, oy])]


def lift_rects(doc, layer=None):
    """竖井井口（旧称电梯井）：墙层上的**闭合矩形** LWPOLYLINE，面积 1–8 m²。

    ★ 实测：**全 12 层各 3 个、位置逐位相同**（含地下1层）⇒ 三个井贯穿全楼，
      这是本仓唯一「井道」的客观来源（源图**无**块、**无**文字点名电梯）。
    ★ 盲区：这是个**规则**（闭合矩形+面积区间），别的楼可能误抓小房间；此处逐层实测定为 3。
    """
    lay = layer or R.WALL_LAYER
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != lay:
            continue
        pts = [(p[0], p[1]) for p in e.vertices()]
        if len(pts) < 4:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if w <= 0 or h <= 0:
            continue
        a = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                    - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2.0
        if abs(a - w * h) / (w * h) < 0.05 and 1.0e6 < a < 8.0e6:
            out.append([(min(xs), min(ys)), (max(xs), min(ys)),
                        (max(xs), max(ys)), (min(xs), max(ys))])
    return out


def plate_contours(wmask, res, ox, oy):
    """楼板外轮廓：墙带闭运算桥接洞口 → 填洞 → 取外环（mm）。

    ★ 为什么不能直接填洞：墙带在门窗处**断开**（实测 1层/8层 直接 `binary_fill_holes`
      面积比 = 1.00，即一点没填上）。先按 `PLATE_CLOSE_MM` 闭运算把洞口桥起来，再填。
    ★ 盲区：内天井 / 中庭 也是「洞」，会被一起填掉（此处不单独识别）。
    """
    m = (np.asarray(wmask) > 0).astype(np.uint8)
    r = int(round(PLATE_CLOSE_MM / float(res))) | 1        # 核取奇数（偶数不居中会整体偏移）
    # ★ 核**必须方形**：椭圆核会把转角磨成圆弧 —— 实测出图后楼板四周一圈弧线，
    #   用户当场看出「楼面不对，还是有弧线」。方形核 + 折线化简 ⇒ 保留直边直角。
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (r, r))
    c = cv2.morphologyEx(m, cv2.MORPH_CLOSE, ker)
    try:
        from scipy.ndimage import binary_fill_holes
        f = binary_fill_holes(c > 0).astype(np.uint8)
    except Exception:
        f = c
    cnts, hier = cv2.findContours(f, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for j in range(len(cnts)):
        if hier[0][j][3] != -1:
            continue
        ap = cv2.approxPolyDP(cnts[j], 3.0, True)          # ★ 折线化简：直边，不留栅格台阶
        if len(ap) < 3:
            ap = cnts[j]
        shell = _contour_mm(ap, res, ox, oy)
        if len(shell) >= 3:
            out.append(shell)
    return out


# ------------------------------------------------------------------ 纯几何（唯一一份）
def geometry(floor):
    """一层的几何数据，**mm 坐标**，不碰 matplotlib。返回 dict：
      walls  : [(shell_pts, [hole_pts, ...]), ...]   墙带（外环 + 内洞）
      cols   : [(pts, closed), ...]                 柱块折线
      doors  : [(pts, closed), ...]                 门块折线
      treads : [ [(x0,y0),(x1,y1)], ... ]           踏步线
      plate  : [ [pt, ...], ... ]                   楼板外轮廓（墙带闭运算桥洞口后填洞，mm）
      A_wall : 识别判出的墙面积 m²（栅格口径，供对账）
      res/ox/oy : 栅格↔mm 的换算（像素 = (mm−[ox,oy])/res）
    """
    src = os.path.join(RAW, floor + ".dxf")
    a = R.analyze(floor)
    wmask, (ox, oy, res) = a["wmask"], a["geo"]
    doc = ezdxf.readfile(src)

    cols = blocks_wcs(src, layer=COL_LAYER)
    doors = blocks_wcs(src, prefix=DOOR_PREFIX)

    # ★ 踏步线：**判据只有一份**，在 `recognize.tread_lines` 里
    #   （同角度 + 共享一条边 + 步距落在 [180,400]，且长于 600 mm）。
    #   旧版这里自己写了一遍「墙层 ∩ 100<L<3000 ∩ 中点在锚区内」——同一条错判据同时出现在
    #   这里和 `recognize.drop_treads` 里，实测 12 层被它剔掉 4448 条墙层线（其中真踏步只有 964 条）
    #   ⇒ 短墙被当成踏步删掉 = 用户报的「部分墙体缺失」；同时踏步数虚高、踏高被挤到 70 mm
    #   = 用户报的「楼梯不对」。两处现在都调同一个函数，不会再各写一遍。
    treads = R.tread_lines(doc, a["zones"])

    cnts, hier = cv2.findContours(wmask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    walls = []
    for j in range(len(cnts)):
        if hier[0][j][3] != -1:                          # 只取外环
            continue
        shell = _contour_mm(cnts[j], res, ox, oy)
        if len(shell) < 3:
            continue
        holes = [_contour_mm(cnts[k], res, ox, oy) for k in R._children(hier, j)]
        holes = [h for h in holes if len(h) >= 3]
        walls.append((shell, holes))

    plate = plate_contours(wmask, res, ox, oy)
    lifts = lift_rects(doc)

    return {"walls": walls, "cols": cols, "doors": doors, "treads": treads,
            "plate": plate, "lifts": lifts,
            "n_seg": len(walls), "n_col": len(cols), "n_door": len(doors),
            "A_wall": a["A_wall"], "res": res, "ox": ox, "oy": oy,
            "zones": a["zones"]}


# ------------------------------------------------------------------ 画（共用一份几何）
def draw(floor):
    """把一层的几何画进一个坐标轴，**数据坐标 = mm**。返回 (fig, ax, v)。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Polygon
    from matplotlib.path import Path
    from matplotlib.collections import LineCollection

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    v = geometry(floor)
    fig, ax = plt.subplots(figsize=(22, 15), dpi=100)
    ax.set_facecolor("white")

    # 墙：填实（外环 + 内洞同属一个 PathPatch）
    for shell, holes in v["walls"]:
        verts, codes = [], []
        for p in [shell] + holes:
            if len(p) < 3:
                continue
            verts += p + [p[0]]
            codes += [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
        if verts:
            ax.add_patch(PathPatch(Path(verts, codes), facecolor="#39404a",
                                   edgecolor="#1b1f24", linewidth=0.5))

    # 柱
    for pts, cl in v["cols"]:
        if len(pts) < 3:
            continue
        ax.add_patch(Polygon(pts, closed=True, facecolor="#1f6feb",
                             edgecolor="#0b3d91", linewidth=1.0))

    # 门
    segs_door = [pts for pts, cl in v["doors"] if len(pts) >= 2]
    if segs_door:
        ax.add_collection(LineCollection(segs_door, colors="#e08b00", linewidths=1.6))

    # 梯
    if v["treads"]:
        ax.add_collection(LineCollection(v["treads"], colors="#111111", linewidths=0.9))

    # 房间号（只作参考底字）
    src = os.path.join(RAW, floor + ".dxf")
    for e in ezdxf.readfile(src).modelspace():
        if e.dxf.layer == "6房间号" and e.dxftype() == "MTEXT":
            p = e.dxf.insert
            ax.text(p.x, p.y, e.text.strip()[:12], fontsize=5, color="#8a8f98",
                    ha="center", va="center")

    ax.set_aspect("equal")
    ax.autoscale()
    ax.grid(True, lw=0.2, alpha=0.3)
    for s in ax.spines.values():
        s.set_visible(False)
    return fig, ax, v


def render(floor):
    fig, ax, v = draw(floor)
    ax.set_title("%s 重画  |  墙 %d 段 柱 %d 门 %d 踏步线 %d  |  墙面积 %.1f m²"
                 % (floor, v["n_seg"], v["n_col"], v["n_door"], len(v["treads"]),
                    v["A_wall"]), fontsize=14)
    os.makedirs(OUT, exist_ok=True)
    png = os.path.join(OUT, "%s_plan.png" % floor)
    fig.savefig(png, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)

    # ---- 同时写一份重画 DXF（层分好，给 SU/Blender 与人工审）
    out = ezdxf.new("R2013", setup=True)
    for lay, col in [("WALL", 8), ("COL", 5), ("DOOR", 30), ("STAIR", 7)]:
        out.layers.add(lay, color=col)
    ms = out.modelspace()
    for shell, holes in v["walls"]:
        ms.add_lwpolyline(shell, close=True, dxfattribs={"layer": "WALL"})
        for h in holes:
            ms.add_lwpolyline(h, close=True, dxfattribs={"layer": "WALL"})
    for pts, cl in v["cols"]:
        if len(pts) >= 3:
            ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "COL"})
    for pts, cl in v["doors"]:
        if len(pts) >= 2:
            ms.add_lwpolyline(pts, close=False, dxfattribs={"layer": "DOOR"})
    for s in v["treads"]:
        ms.add_line(s[0], s[1], dxfattribs={"layer": "STAIR"})
    dxfp = os.path.join(OUT, "%s_full.dxf" % floor)
    out.saveas(dxfp)

    print("墙 %d 段 / 柱 %d / 门实体 %d / 踏步线 %d"
          % (v["n_seg"], v["n_col"], v["n_door"], len(v["treads"])))
    print("写 %s" % png)
    print("写 %s" % dxfp)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor")
    ap.add_argument("--all", action="store_true",
                    help="全部楼层，一个进程跑完（层表与 recognize 同一份：raw_floors）")
    a = ap.parse_args()
    if a.all:
        rc = 0
        for f in R.raw_floors():
            print("── %s" % f)
            rc = max(rc, render(f))
        return rc
    if not a.floor:
        print("给 --floor 或 --all")
        return 2
    return render(a.floor)


if __name__ == "__main__":
    sys.exit(main())
