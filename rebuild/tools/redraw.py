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
import math  # ★ 2026-10-18：`door_symbols` 量扇线段长要用（原先只有函数内局部 import）
import os
import sys

import cv2
import ezdxf
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B  # noqa: E402
import recognize as R  # noqa: E402

# ★ 2026-10-17：数据根与「柱/门怎么画」改从楼栋档案读（不设环境变量 = c006，行为不变）。
ROOT = B.ROOT
RAW = os.path.join(ROOT, "01_cad", "raw")
OUT = os.path.join(ROOT, "03_redraw")
_DRAW = B.profile().get("drawing", {})
COL_MODE = _DRAW.get("columns", "block")     # block=INSERT 块；lwpolyline=图层上的多段线
DOOR_MODE = _DRAW.get("doors", "block")      # block=INSERT 块；symbols=墙层上的多点多段线
# ★ 2026-10-17：柱层/门层名逐栋不同（`4.1结构柱` 40 张 / `4.1柱子` 1 张）⇒ 从源图现认。
COL_LAYER = B.layer("column", "4.1结构柱")
DOOR_PREFIX = "$DorLib2D$"
DOOR_LAYER = B.layer("door", "4.2墙体")
# ★ 2026-10-17：门符号的**画法**逐楼不同，四个数从档案读（不设 = C005 原值）：
#   C005 = 16/23 点、门框 150、净宽 1100/2400；
#   C001 = 13/14/18 点、端部刻度 100/125/150（三种不等）⇒ 不扣门框（jamb=0）、
#          外包宽 1050~1255（单扇）与 1488~1519（双扇）。
DOOR_MIN_PTS = int(_DRAW.get("doors_min_pts", 16))
DOOR_JAMB_MM = float(_DRAW.get("doors_jamb_mm", 150.0))
DOOR_OPEN_MM = tuple(float(x) for x in _DRAW.get("doors_open_mm", [1100.0, 2400.0]))
DOOR_OPEN_TOL = float(_DRAW.get("doors_open_tol", 60.0))
# 门候选的「等墙向长边」窗口（mm，扣门框之前）；空 = 不筛（c001/c005 的既有读数不变）
DOOR_WIDTH_MM = tuple(float(x) for x in _DRAW.get("doors_width_mm") or ()) or None
# 栅格墙带斜边的台阶幅值约半个像素；20 mm 可把 25 mm 栅格的斜边拉直，
# 同时不改变 90° 墙角和门洞位置。只作用于栅格轮廓，不碰源图多段线。
WALL_STRAIGHTEN_MM = 20.0
# ★★ 2026-10-17 剩下 60 多栋楼的实测：门符号是**近方形**的（含门扇+开启弧），
#   而**窗**符号是**贴墙的长条**（C025/C028 实测 2250×250、C114 2100×300 = 墙厚带）。
#   只按点数筛会把这批窗当门抠出全高洞口 ⇒ 用「短边/长边」下限再筛一道。
#   不写 = 不筛（c005/c001 的既有读数一字不变）。
DOOR_SHAPE_RATIO = float(_DRAW.get("doors_shape_ratio", 0.0)) or None
# ★★ 2026-10-17 逐族实测（C025/C028/C114/C041/C009/C001/C105）：
#   **真门符号 100% 带非零 bulge**（门扇的开启弧），而同样落在「近方形 + 600~2500」窗口里的
#   假门符号 **bulge 全 0** —— C114 的 6 点族 **580 个 725×440 全无弧**（某种房间内符号），
#   若只按点数+形状筛，它会被当成 580 扇门抠墙。⇒ 可写 `drawing.doors_need_arc: true`
#   要求「至少一段是弧」。不写 = 不筛（c001/c105/c005 的既有读数一字不变）。
DOOR_NEED_ARC = bool(_DRAW.get("doors_need_arc", False))
# ★ 2026-10-17 C105 1~5 层：门画成**开启弧**（墙层上的 ARC，半径 = 门扇净宽），
#   与 D1 的「多点多段线符号」是两种画法，同一栋楼里并存 ⇒ 档案可写 `doors: "auto"`。
DOOR_ARC_R_MM = tuple(float(x) for x in _DRAW.get("doors_arc_r_mm", [650.0, 1700.0]))
DOOR_ARC_SNAP_MM = float(_DRAW.get("doors_arc_snap_mm", 250.0))
DOOR_ARC_PAD_MM = float(_DRAW.get("doors_arc_pad_mm", 300.0))
# 门块补条的跨墙半厚（mm）：墙厚 240 ⇒ 半厚 120 + 30 余量。
# ★ 只用于「分区时把门洞盖住」（`block_door_plugs`），**不**参与抠模型门洞。
DOOR_PLUG_HALF_MM = float(_DRAW.get("doors_plug_half_mm", 150.0))
DOOR_ARC_UNRESOLVED = []      # 开启弧里「两端都没贴到墙」的那些（没认出来，不是没有）
# ★★ 2026-10-18「办公楼和理化楼的门少了」的一半病灶就在这里：
#   `doors_arc_r_mm` 是 `author_profiles._door_census` 按**常见半径（≥20 根）**作者化的，
#   它挑的是「这栋楼的门扇宽」，不是「这栋楼所有的门扇宽」。同一张图上另一种扇宽
#   （c004 的 895、c112 的 1100）会被整窗挡掉 ⇒ 那一**樘**门在图上消失、房间封死。
#   兜底判据：窗口外但落在门尺度（600~3000 mm）、张角 80~100°、并且**成对**
#   （同半径 ±5、两圆心相距 2r±80、两扇关闭位端点重合 ≤150）⇒ 是对开门的两片扇。
#   ★ 为什么必须「成对」：c105 窗口外有成片 r=301~585、84~89° 的**墙倒角**，
#   单条弧看不出是门还是倒角；对开门的两片扇中心距恰为 2r、关闭位端点同点，这是倒角不会有的。
DOOR_ARC_SOFT_R_MM = (600.0, 3000.0)
DOOR_ARC_SOFT_SWEEP = (80.0, 100.0)
DOOR_ARC_PAIR_MM = 80.0       # 圆心距与 2r 的容差
DOOR_ARC_PAIR_ENDS = 150.0    # 两扇关闭位端点重合容差
DOOR_ARC_SOFT_PAIRS = []      # 本次兜底认出来的对开门（打日志用：不许无声多门）
# ★ 2026-10-18：门扇线**单扇最长** 1800 mm（= 源图门扇块最长边）。更宽的洞口等分成多片，
#   2.4 m 正门 ⇒ 2 片 1.2 m，与 c006 的双扇同形。
LEAF_SPLIT_MM = 1800.0
# ★★ 2026-10-21（c116 用户「门和墙错开了，门没在墙中」）：近方形门符号
#   **不能只看 bbox 长边判墙向**。c116 的 1000×1020 / 1020×1100 门符号，
#   高度只比宽度多 20~80 mm（这段差值来自开启弧），bbox 长边恰好与墙向垂直；
#   旧口径把门洞框竖过来，和水平墙带只交出一条 30 mm 薄片，门扇自然悬在墙外。
#   近方形时用洞口两端墙带的延续量判墙向：墙继续向左右 ⇒ x，向上下 ⇒ y。
DOOR_AXIS_AMBIGUOUS_RATIO = 1.15
DOOR_AXIS_PROBE_MM = 600.0
DOOR_AXIS_DOMINANCE = 1.35
# ★ 楼板轮廓：墙带**不闭合**（门窗洞口）+ 直接填洞＝填不出来（实测＝墙面积）。
#   先按此直径闭运算**桥接洞口**，再填洞 ⇒ 得到整层楼面外轮廓。
PLATE_CLOSE_MM = 2500.0


# ------------------------------------------------------------------ 取块（柱 / 门）
def blocks_grouped_wcs(path, layer=None, prefix=None):
    """同下，但**按 INSERT 分组**返回 —— 一个块一条记录（真值尺要「一樘门」这个单位）。

    返回 `[{"name", "layer", "ins": (x, y), "polys": [(pts, closed), …]}, …]`。
    ★ 与 `blocks_wcs` 是**同一个循环、同一个顺序**（`blocks_wcs` 就是把它摊平），
      所以两把尺子量的是同一批块 —— 不会出现「按块数」与「按折线数」对不上的假分歧。
      OCS 的教训见 `blocks_wcs` 的注释，两处共用（不是各写一份）。

    ★ 为什么要「按块」：2026-10-16 门头墙真值尺要判「**这一樘**门上方有没有板」，
      单位是**块**（`$DorLib2D$` 一樘一个 INSERT）；摊平之后一樘门变成 2 条折线
      （门扇 + 开启弧）⇒ 摊平列表里数不出「樘」。
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
        polys = []
        for v in vs:
            try:
                p = ezpath.make_path(v)
            except Exception:
                continue
            pts = [(q.x, q.y) for q in p.flattening(15.0)]
            if len(pts) >= 2:
                polys.append((pts, False))
        try:
            ins = (e.dxf.insert.x, e.dxf.insert.y)
        except Exception:
            ins = (float("nan"), float("nan"))
        out.append({"name": e.dxf.name, "layer": e.dxf.layer, "ins": ins, "polys": polys})
    return out


def cols_lwpolyline(doc, layer=None):
    """柱：图层上的**闭合多段线**（C005 画法——`4.1结构柱` 8 个 6 点 500×500）。

    返回形状与 `blocks_wcs` 一致：`[(pts, closed), …]`，下游不区分柱是怎么画的。
    ★ 盲区：这是「图层名 + 多段线」这条规则；若别的楼把柱画成 LINE 矩形，本函数**全盲**
      （会返回 0 根）—— 所以 `geometry()` 的 `n_col` 在 build.json 里是要人对账的读数。
    """
    lay = layer or COL_LAYER
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != lay:
            continue
        pts = [(float(p[0]), float(p[1])) for p in e.get_points()]
        if len(pts) >= 3:
            out.append((pts, True))
    return out


def _door_wall_axis(x0, y0, x1, y1, W):
    """近方形门符号的墙向：看门洞两端外侧墙带往哪边延续。

    返回 ``"x"`` / ``"y"``；两侧都不足以判定时返回 ``None``（保持 bbox 长边口径）。
    只读当前层墙带，不依赖门符号自己是否带开启弧。
    """
    if W is None or W.is_empty:
        return None
    from shapely.geometry import box

    p = DOOR_AXIS_PROBE_MM
    sx = (box(x0 - p, y0 - p, x0, y1 + p).intersection(W).area
          + box(x1, y0 - p, x1 + p, y1 + p).intersection(W).area)
    sy = (box(x0 - p, y0 - p, x1 + p, y0).intersection(W).area
          + box(x0 - p, y1, x1 + p, y1 + p).intersection(W).area)
    if sx <= 0 and sy <= 0:
        return None
    if sx >= DOOR_AXIS_DOMINANCE * max(sy, 1e-9):
        return "x"
    if sy >= DOOR_AXIS_DOMINANCE * max(sx, 1e-9):
        return "y"
    return None


def door_symbols(doc, layer=None, min_pts=None, walls=None):
    """门：画在墙层上的**多点多段线符号**（C005 画法；墙层上还有 2~8 点的墙线，不能混）。

    每个符号返回 `{"pts", "rect", "width_mm", "axis", "bbox"}`：
      · `rect`      = **门洞**（横跨墙厚、沿墙向 1100/2400 的矩形，mm）—— build3d 拿它抠墙；
      · `width_mm`  = 净宽 = 符号沿墙向总长 **两端各去掉 `DOOR_JAMB_MM` 的门框标记**。
    ★ 方向规则：门洞所在的那条轴 = 符号 bbox 的**长边**（单扇 1400×1220 / 双扇 2700×1320，
      实测两种都是「等墙向」更长）。短边是门扇+开启弧探出去的那一边，不参与洞口宽度。
    ★ 自检（不静默）：净宽必须落在 `DOOR_OPEN_MM` ± `DOOR_OPEN_TOL` 里；否则该樘
      的 `width_mm` 照样报出来，由调用方判红 —— 这里不替它挑选一个「看起来对」的值。
    """
    lay = layer or DOOR_LAYER
    mp = DOOR_MIN_PTS if min_pts is None else min_pts
    W = None
    if walls:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union

        _polys = []
        for s, h in walls:
            q = Polygon(s, h)
            if not q.is_valid:
                q = q.buffer(0)
            if not q.is_empty:
                _polys.append(q)
        W = unary_union(_polys) if _polys else None
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != lay:
            continue
        raw = e.get_points()
        pts = [(float(p[0]), float(p[1])) for p in raw]
        if len(pts) < mp:
            continue
        if DOOR_NEED_ARC and not any(abs(float(p[4])) > 1e-6 for p in raw):
            # 全直线、一段弧都没有 ⇒ 这不是门符号（实测：真门符号 100% 带开启弧）
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        # ★ 2026-10-17 C105 实测：墙层上还有些**几十个点的大轮廓**（11 条，宽 27～187 m），
        #   `>=min_pts` 会把它们当门，抠出天大的洞。档案可给 `drawing.doors_width_mm: [lo,hi]`
        #   声明「门的等墙向长边」合理窗口（mm，**扣门框之前**的量）；不声明 = 不过滤（c001/c005 不变）。
        if DOOR_WIDTH_MM:
            _long = max(x1 - x0, y1 - y0)
            if not (DOOR_WIDTH_MM[0] <= _long <= DOOR_WIDTH_MM[1]):
                continue
        if DOOR_SHAPE_RATIO:
            _long = max(x1 - x0, y1 - y0)
            _short = min(x1 - x0, y1 - y0)
            if _long <= 0 or (_short / _long) < DOOR_SHAPE_RATIO:
                continue
        horiz = (x1 - x0) >= (y1 - y0)          # 默认墙向 = bbox 长边
        _short, _long = sorted((x1 - x0, y1 - y0))
        if W is not None and _short > 0 and _long / _short < DOOR_AXIS_AMBIGUOUS_RATIO:
            # 近方形符号的长边可能只是开启弧多出来的 20~80 mm；墙向以墙带延续为准。
            _axis = _door_wall_axis(x0, y0, x1, y1, W)
            if _axis is not None:
                horiz = _axis == "x"
        u0, u1 = (x0, x1) if horiz else (y0, y1)
        v0, v1 = (y0, y1) if horiz else (x0, x1)
        ou0, ou1 = u0 + DOOR_JAMB_MM, u1 - DOOR_JAMB_MM
        if horiz:
            rect = [(ou0, v0), (ou1, v0), (ou1, v1), (ou0, v1)]
        else:
            rect = [(v0, ou0), (v0, ou1), (v1, ou1), (v1, ou0)]
        # ★★ 2026-10-18 用户「六教的门样式比较好，现在的门不好」实测：
        #   扇线的**真位置在符号里**。c005 一个 16 点符号（bbox 1400×1220）里，
        #   第 2→3 点是 y=47560 的 1100 mm 直段（= 净宽），正好落在墙厚
        #   47440~47680 的**中线上** —— 那就是**关门姿态的扇线**。
        #   旧口径取 bbox 中线（短边含开启弧，到 48660）⇒ 中线落在房间里
        #   0.32~0.37 m，全库门扇悬在门洞中间（c005 实测 49 扇中位 0.320 m，
        #   c006 走块路径 181 扇中位 0.000 m —— 这就是「样式不一样」的量）。
        #   改为**从源图取**：bulge=0、沿墙向、长度 ≈ 净宽 ±15%。
        #   取不到才退回 bbox 中线，并记 `leaf_src`（不许静默）。
        leaf_segs, _seen = [], set()
        _w = ou1 - ou0
        for i in range(len(pts) - 1):
            if abs(float(raw[i][4])) > 1e-6:
                continue
            q0, q1 = pts[i], pts[i + 1]
            seg = math.dist(q0, q1)
            # 单扇 = 1×净宽；双扇 = 2 段 ½ 净宽（c005 23 点双门实测：1200+1200）。
            # k 只到 2：更宽的洞由 `LEAF_SPLIT_MM` 在下游等分。
            if _w <= 0 or not any(0.85 * _w / k <= seg <= 1.15 * _w / k for k in (1, 2)):
                continue
            _ax = abs(q1[0] - q0[0]) if horiz else abs(q1[1] - q0[1])
            if seg <= 0 or _ax / seg < 0.99:           # 必须平行于墙向
                continue
            _k = tuple(sorted((q0, q1)))               # 源图把同一扇画了 2~3 遍
            if _k in _seen:
                continue
            _seen.add(_k)
            leaf_segs.append([q0, q1])
        # ★ 2026-10-18 用户弹窗定案：「三个 V 符号是门，踏步是台阶」——
        #   那三组 2.4 m 符号照常当门认（抠洞+门扇+门头墙）；
        #   台阶是它们**外侧**画在 4.2墙体 层上的踏步，见 `build3d.wall_polys` 的扣除。
        out.append({"pts": pts, "closed": False, "rect": rect,
                    "width_mm": round(ou1 - ou0, 1),
                    "axis": "x" if horiz else "y",
                    "leaf_segs": leaf_segs,
                    "leaf_src": "符号" if leaf_segs else "bbox",
                    "bbox": (x0, y0, x1, y1)})
    return out


def block_door_plugs(doc):
    """门 INSERT 块 → **跨墙补条**矩形（mm）：`[(x0, y0, x1, y1), …]`。

    为什么有它（2026-10-18 用户「色块就是不对」实测量出来的）：
      本楼门全画成 `$DorLib2D$` 块，一根块里**两根开启弧**，圆心落在块插入点两侧
      各一个半径处、两弧外切于插入点 ⇒ **门洞中心 = 插入点，门洞方向 = 两弧心连线**。
      弧的两个端点**都不贴墙**（都是「开着的位置」），`door_arcs` 那套
      「圆心=合页、关闭位端点贴墙」的判据对这个符号不成立（1 层只认出 71/189 根），
      于是 `door_voids` 补不满墙上的缺口 ⇒ 33 个房间号挤进 4 个连通区。
      本函数只做一件事：把**门洞跨过的那段墙**用补条盖住（只给分区用，不抠模型）。

    判据（1 层实测：116 个门块 113 个补上，房间号 33/33 各落一个区）：
      · 弧心集就是门洞两端；沿门洞方向**不外扩**（多扩就会吃进房间）；
      · 横墙向各让 `DOOR_PLUG_HALF_MM`（墙厚 240 mm 的半厚 120 + 30 mm 余量）；
      · 只有一根弧的块（实测 37 个）：另一半按「插入点对称」补出 `2·I − C`。
    ★ 盲区：一根弧都没有的门块（实测 3 个）**不补**，由调用方按读数报出 ——
      不许与「这一层没有门」同形（铁律 199）。
    """
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "INSERT" or not str(e.dxf.name).startswith(DOOR_PREFIX):
            continue
        cs = []
        for ve in e.virtual_entities():
            if ve.dxftype() == "ARC":
                c = ve.ocs().to_wcs(ve.dxf.center)
                cs.append((c.x, c.y))
        if not cs:
            continue
        if len(cs) >= 2:
            pts = cs
        else:
            ins = (e.dxf.insert.x, e.dxf.insert.y)
            pts = [cs[0], (2 * ins[0] - cs[0][0], 2 * ins[1] - cs[0][1])]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # ★ 四边都让 T：探针实测（1 层 33/33）用的就是这个形状。试过「门洞方向不外扩」
        #   （认为弧心已在门洞两端、不该多吃）—— 结果补条端头与墙端头留了 150 mm 缝，
        #   连通没断开：1 层分区 85→51、房 33→14。端头必须压进墙里才算「封住」。
        T = DOOR_PLUG_HALF_MM
        out.append((min(xs) - T, min(ys) - T, max(xs) + T, max(ys) + T))
    return out


def _block_arcs(doc, lay=None):
    """门 INSERT 块**块内**的 ARC（块内实体几乎都在 `0` 层 ⇒ 只能按块名前缀认）。

    ★ 2026-10-18 c006 1 层实测：模型空间一根门弧都没有（门全是 `$DorLib2D$` 块，
      116 个），而块里 189 根弧**半径 100% 落在 `doors_arc_r_mm` 窗内**（中位 731 mm）。
      旧逻辑只扫模型空间 ⇒ `door_voids` 恒空 ⇒ 装包器「门口不封」⇒ 33 个房间号
      挤进 4 个连通区、一层只出 4 片房垫。这里的判据（半径窗、贴墙、门洞框）
      与模型空间那条**一个字都不改** —— 只是把候选弧的来源补上块内这一路。
    """
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "INSERT":
            continue
        if not str(e.dxf.name).startswith(DOOR_PREFIX):
            continue
        try:
            out.extend(v for v in e.virtual_entities() if v.dxftype() == "ARC")
        except Exception:                                  # noqa: BLE001
            continue                    # 坏块：当「没认到」，由调用方按读数报出
    return out


def door_arcs(doc, layer=None, r_mm=None, snap_mm=None, include_blocks=False):
    """门：墙层上的**开启弧**（ARC，半径 = 门扇净宽）—— C105 1~5 层的画法。

    判据（全部从图元自身读出，不按图幅/楼层硬编码）：
      · 墙层上半径落在 `doors_arc_r_mm` 的 ARC 是**开启弧**；大半径弧（实测 96~107 m）
        是**弧形墙**，小半径（31~200 mm）是刻度，都落在窗口外；
      · 圆心 = 合页；弧的两个端点一个是「门扇关闭位」（落在墙线上），另一个是
        「门扇开启位」（伸进房间）⇒ **门洞 = 圆心 → 落在墙线上那个端点**；
      · 净宽 = 半径，与 `doors_open_mm` ± tol 的对账仍由 build3d 打印（这里不替它挑值）。

    返回字段与 `door_symbols` 相同（`pts`/`rect`/`width_mm`/`axis`/`bbox`）。
    ★ 盲区：两个端点都离墙线远于 `doors_arc_snap_mm` 的弧**不认**，计入模块级
      `DOOR_ARC_UNRESOLVED`（由 `geometry()` 打印）——「没认出来」不许同形于「没有门」。
    """
    import math

    lay = layer or DOOR_LAYER
    lo, hi = r_mm or DOOR_ARC_R_MM
    snap = DOOR_ARC_SNAP_MM if snap_mm is None else snap_mm

    # 墙线（判「门扇关闭位」的参照物）。逐段展平成 numpy 数组，按点-线段距离查最近。
    segs = []
    for e in doc.modelspace():
        if e.dxf.layer != lay:
            continue
        t = e.dxftype()
        if t == "LINE":
            a, b = e.dxf.start, e.dxf.end
            if (a.x, a.y) != (b.x, b.y):
                segs.append((a.x, a.y, b.x, b.y))
        elif t == "LWPOLYLINE":
            # ★ OCS→WCS：多段线顶点是 OCS 坐标（镜像块的 extrusion=(0,0,-1) 会把 x 取反）。
            try:
                pts = [(v.x, v.y) for v in e.vertices_in_wcs()]
            except Exception:                              # noqa: BLE001
                pts = [(float(p[0]), float(p[1])) for p in e.get_points()]
            for i in range(len(pts) - 1):
                segs.append((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))
            if e.closed and len(pts) > 2:
                segs.append((pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]))
    A = np.array(segs, float) if segs else np.zeros((0, 4))

    def _d(px, py):
        if not len(A):
            return float("inf")
        x1, y1, x2, y2 = A[:, 0], A[:, 1], A[:, 2], A[:, 3]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        L2[L2 == 0] = 1e-9
        t = np.clip(((px - x1) * dx + (py - y1) * dy) / L2, 0.0, 1.0)
        return float(np.hypot(px - (x1 + t * dx), py - (y1 + t * dy)).min())

    out = []
    DOOR_ARC_UNRESOLVED.clear()
    DOOR_ARC_SOFT_PAIRS.clear()
    # ★ 候选弧来源：模型空间同层 ARC；`include_blocks=True` 时**加上门块内的 ARC**
    #   （块内实体在 `0` 层，不能按层筛，由 `_block_arcs` 按块名前缀认）。
    cands = [e for e in doc.modelspace()
             if e.dxftype() == "ARC" and e.dxf.layer == lay]
    if include_blocks:
        cands += _block_arcs(doc, lay)

    # ── 第一趟：每条弧先算出「圆心 / 两端点 / 贴墙距离」，再决定准不准入。
    #   ★★ ARC 的 `dxf.center` / 起止角都是 **OCS** 坐标，不是 WCS。
    #   C105 1 层实测：353 条门弧里有一批 extrusion=(0,0,−1)（镜像画法），
    #   OCS 的 x 与 WCS 反号（圆心读到 −205903，实际在窗内 +876224）
    #   ⇒ 直接读 dxf.center 会把**真门**判成「没贴到墙」（79/146 全在这一批）。
    #   一律经 `ocs()` 换算；起止点同理，逐点在 OCS 里算完再 to_wcs。
    info = []
    for e in cands:
        r = float(e.dxf.radius)
        ocs = e.ocs()
        c0 = e.dxf.center
        a0 = math.radians(e.dxf.start_angle)
        a1 = math.radians(e.dxf.end_angle)

        def _pt(ang, _o=ocs, _c=c0, _r=r):
            q = _o.to_wcs((_c.x + _r * math.cos(ang), _c.y + _r * math.sin(ang), _c.z))
            return (q.x, q.y)

        cw = ocs.to_wcs(c0)
        c = (cw.x, cw.y)
        p1, p2 = _pt(a0), _pt(a1)
        d1, d2 = _d(*p1), _d(*p2)
        info.append({"e": e, "r": r, "a0": a0, "pt": _pt, "c": c,
                     "p1": p1, "p2": p2, "d1": d1, "d2": d2,
                     "span": (e.dxf.end_angle - e.dxf.start_angle) % 360.0,
                     "win": lo <= r <= hi})

    # ── 兜底准入：门尺度的 90° 弧，**成对**才算门（对开双扇的两片扇）。
    #   作者化窗口按「常见半径」挑的是门扇宽，会把另一种扇宽整窗挡掉；
    #   对开门的几何签名（圆心距 = 2r、两扇关闭位端点同点）倒角不会有。
    # ★★ 2026-10-20：**窗内**的对开双扇也必须走配对。c006 7 层实测 20 樘
    #   `$DorLib2D$00000002`（r=731.25、88.5°）：两扇关闭位在**洞口正中**相接
    #   （圆心距 1462.5 恰 = 2r、端点距 0.0），两个关闭位都不落在任何墙线上——
    #   洞口处墙线本来就断开。旧判据只在窗外才允许配对，窗内一律按
    #   `min(d1,d2) > snap` 拒（实测 612/750 mm）⇒ 7 层只认出 14/36 樘门洞，
    #   6 间房永久封死（`J-10.9-09` 的 A 类）。
    #   配对签名比单弧贴墙更硬，所以这里只放「反正会被拒」的那批进来：
    #   贴墙的仍走单弧（不掺进配对池），窗外仍受半径软窗约束。
    def _needs_pair(it):
        if not (DOOR_ARC_SOFT_SWEEP[0] <= it["span"] <= DOOR_ARC_SOFT_SWEEP[1]):
            return False
        if not it["win"]:
            return DOOR_ARC_SOFT_R_MM[0] <= it["r"] <= DOOR_ARC_SOFT_R_MM[1]
        return min(it["d1"], it["d2"]) > snap

    soft = [it for it in info if _needs_pair(it)]
    for i, it in enumerate(soft):
        if it.get("paired"):
            continue
        for jt in soft[i + 1:]:
            if jt.get("paired") or abs(it["r"] - jt["r"]) > 5.0:
                continue
            dc = math.hypot(it["c"][0] - jt["c"][0], it["c"][1] - jt["c"][1])
            if abs(dc - 2.0 * it["r"]) > DOOR_ARC_PAIR_MM:
                continue
            # 关闭位端点 = **离对面合页最近的那个端点**。不能用「离墙近」挑：
            #   c004 3 层实测四个端点贴墙距离全是 0.0（墙线在洞口处也画通了），
            #   按 d1<=d2 挑会挑到开启位，两扇的「关闭位」相距 2r 而永远配不上。
            q1 = min((it["p1"], it["p2"]),
                     key=lambda p: math.hypot(p[0] - jt["c"][0], p[1] - jt["c"][1]))
            q2 = min((jt["p1"], jt["p2"]),
                     key=lambda p: math.hypot(p[0] - it["c"][0], p[1] - it["c"][1]))
            if math.hypot(q1[0] - q2[0], q1[1] - q2[1]) > DOOR_ARC_PAIR_ENDS:
                continue
            it["win"] = jt["win"] = True          # 两片扇必须一起准入
            it["paired"] = jt["paired"] = True
            it["pair_pend"] = q1
            jt["pair_pend"] = q2
            DOOR_ARC_SOFT_PAIRS.append({"r": it["r"], "c": (it["c"], jt["c"]),
                                        "seam": q1})

    for it in info:
        if not it["win"]:
            continue
        e, r, c = it["e"], it["r"], it["c"]
        p1, p2, d1, d2 = it["p1"], it["p2"], it["d1"], it["d2"]
        _pt = it["pt"]
        a0 = it["a0"]
        if it.get("pair_pend") is not None:
            # 对开双扇：两片扇的「关闭位」在**洞口正中相接**，不在任一段墙线上，
            # 那一半洞口的宽度就是 r；由配对那一趟直接给定，不再按贴墙距离挑。
            pend = it["pair_pend"]
        elif min(d1, d2) > snap:
            DOOR_ARC_UNRESOLVED.append({"center": c, "r": r,
                                        "d": (round(d1, 1), round(d2, 1))})
            continue
        else:
            pend = p1 if d1 <= d2 else p2                   # 门扇关闭位（贴墙）
        axis = "x" if abs(pend[0] - c[0]) >= abs(pend[1] - c[1]) else "y"
        P = DOOR_ARC_PAD_MM
        if axis == "x":
            u0, u1 = sorted((c[0], pend[0]))
            v0, v1 = c[1] - P, c[1] + P
        else:
            u0, u1 = c[0] - P, c[0] + P
            v0, v1 = sorted((c[1], pend[1]))
        rect = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        # 开启弧折线（多点多段线，与 symbols 同形；下游只对 2 点线做门扇配对 ⇒ 不会被误当门扇）
        n = 8
        span = (e.dxf.end_angle - e.dxf.start_angle) % 360.0
        pts = [_pt(a0 + math.radians(span * i / n)) for i in range(n + 1)]
        # ★ 2026-10-18 同前：弧门的扇线也**从源图取** —— 合页 `c` → 贴墙端点
        #   `pend` 就是关门姿态的那一条（`pend` 的定义本身就是「落在墙线上」）。
        #   旧口径取 rect 中线，`v0/v1` 是 ±DOOR_ARC_PAD_MM 的**垫边**，
        #   中线未必落在墙厚中线上 ⇒ 门扇同样会浮。取不到的仍退回 rect 中线。
        out.append({"pts": pts, "closed": False, "rect": rect,
                    "width_mm": round(r, 1), "axis": axis,
                    "leaf_segs": [[c, pend]], "leaf_src": "开启弧",
                    "bbox": (min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1))})
    return out


def blocks_wcs(path, layer=None, prefix=None):
    """把符合条件的 INSERT 展开成 WCS 下的折线列表 [(pts, closed)]。

    ★ 一律走 `ezdxf.path.make_path` 再 flatten —— 不是自己读 `dxf.center`。
      为什么：块里的 ARC/CIRCLE 的 `center` 是 **OCS** 坐标；门块大量带**负缩放**
      （镜像开门方向），OCS↔WCS 一翻，自己算的圆心就飞到图纸外
      （实测飞到 x≈−100000）。make_path 自己处理 OCS，一次解决。
    """
    return [it for g in blocks_grouped_wcs(path, layer, prefix) for it in g["polys"]]


def _contour_mm(c, res, ox, oy):
    """cv2 像素轮廓 → mm 坐标点列。"""
    return [tuple(p) for p in (c[:, 0, :].astype(float) * res + [ox, oy])]


def _ring_area(pts):
    """鞋带公式（mm²，带符号）。"""
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _column_loop(pts):
    """柱折线 → **一个简单外轮廓**（把折线当成一张线段网，取所有围成的小面**并起来**）。

    ★ 2026-10-19 用户「你看看接触处，还不是直角」：源图把柱子画成**方框 + 框内打叉**
      （8 点，实测 c001 1 层：`A,B,C,A,D,C,D,B` = 四条方框边 + 两条对角线）。
      整串直接 `Polygon()` 是**自交多边形**，`buffer(0)` 会把顶边中段切出一个
      100 mm 深的 45° V —— 三维里就是柱子与墙相接处长出一块斜面。
    ★★ 2026-10-19 晚 用户「柱子怎么是三角的，都是正方形的」：第一版按「顶点重复」
      切子环、**取面积最大的那个** —— 这个画法切出来的是 `(A,B,C)` 与 `(A,D,B)`
      两个**各占一半**的三角形（面积打平，`max` 取到前一个）⇒ 每根柱子都成了三角形。
      第二版改成「子环并集」仍不对：切环时把 `D→C` 那条左边吃进了退化环，
      漏掉真正闭合的 `A,D,C` ⇒ 并集缺了左边一块（实测剩 0.27 m²，应为 0.36 m²）。
    ★ 正解：**不按顶点重复切**，直接把每对相邻点当线段，`polygonize` 找出所有闭合小面
      （`A,B,C` / `A,D,C` / `C,D,B` …），再把这些面**并起来** —— 方框四条边都在，
      并集就是原方框；对角线只切面、不改变并集。简单闭环（无叉）也走同一条路。
    ★ 返回并集里**面积最大那块的外环**坐标（去掉闭合重复点）；一条面都围不出来时原样返回。
      盲区：真实就画成两个分离块的柱（图中不存在）只会留下面积大的那块。
    """
    if not pts or len(pts) < 3:
        return pts

    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    def _k(p):
        return (round(p[0], 3), round(p[1], 3))

    segs, seen = [], set()
    pairs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    if _k(pts[-1]) != _k(pts[0]):                    # 没写闭合点的（DXF 的 closed 标志）
        pairs.append((pts[-1], pts[0]))
    for a, b in pairs:
        if _k(a) == _k(b):
            continue
        # ★ 反向重复的线段必须去重：这个画法里左边 `D→C` 与 `C→D` 各出现一次、
        #   上下底 `A→B`/`B→A` 也重（闭合点补的），GEOS Polygonizer 拿到重复边
        #   会**一条面都围不出来**（实测 0 面，函数退回原 8 点 ⇒ 还是三角/自交）。
        key = frozenset((_k(a), _k(b)))
        if key in seen:
            continue
        seen.add(key)
        segs.append(LineString([a, b]))
    if not segs:
        return pts
    try:
        faces = list(polygonize(segs))
    except Exception:                                                  # noqa: BLE001
        return pts
    if not faces:
        return pts
    merged = unary_union(faces)
    best = max(list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged],
               key=lambda g: g.area)
    return [(float(x), float(y)) for x, y in best.exterior.coords[:-1]]


def _straighten_wall_ring(pts, res):
    """把栅格化墙带留下的阶梯斜边拉成直线。

    c001 的斜墙在 5 层图上表现为 75 mm 横步 + 25 mm 竖步的连续阶梯：
    20 mm 容差可把轮廓点从 14,583 个降到约 7,900 个并拉直斜边，同时保留直墙拐角。
    只对栅格轮廓使用；源图 LWPOLYLINE 墙不走这里。
    """
    if len(pts) < 8:
        return pts, 0
    from shapely.geometry import Polygon

    try:
        poly = Polygon(pts)
        if not poly.is_valid or poly.area <= 0:
            return pts, 0
        tol = max(12.0, min(WALL_STRAIGHTEN_MM, float(res) * 0.8))
        simplified = poly.simplify(tol, preserve_topology=True)
        if simplified.geom_type != "Polygon" or simplified.is_empty:
            return pts, 0
        q = [(float(x), float(y)) for x, y in simplified.exterior.coords[:-1]]
        if len(q) < 3 or abs(_ring_area(q)) <= 0:
            return pts, 0
        return q, max(0, len(pts) - len(q))
    except Exception:
        return pts, 0


def _square_pixel_steps(pts, res):
    """把栅格描边留下的 1~2 px 45° 台阶折成直角。

    只处理短 45° 段，且要求前后两段都轴对齐：把段的两端换成交点 ⇒ 拐点回到 90°。
    真斜墙的长 45° 边、以及前后有斜边的段一律不动。

    ★ 2026-10-21 性能修复：旧版每修一处都从环起点重新扫描，c105 的 2 万处修改
      退化成 O(n²)，单层卡住 20 分钟以上。现在只回看两个相邻位置，线性扫描。
    """
    if len(pts) < 4:
        return pts, 0
    closed = abs(pts[0][0] - pts[-1][0]) < 1e-9 and abs(pts[0][1] - pts[-1][1]) < 1e-9
    q = [tuple(t) for t in (pts[:-1] if closed else pts)]
    eps = res * 0.25
    cap = res * 2.0 + 1e-6
    fixed = 0
    i = 0
    while len(q) >= 4 and i < len(q):
        m = len(q)
        a, b = q[i], q[(i + 1) % m]
        dx, dy = b[0] - a[0], b[1] - a[1]
        short_45 = (
            max(abs(dx), abs(dy)) <= cap
            and min(abs(dx), abs(dy)) > eps
            and abs(abs(dx) - abs(dy)) <= eps
        )
        if not short_45:
            i += 1
            continue
        p0 = q[(i - 1) % m]
        p2 = q[(i + 2) % m]
        pv = (a[0] - p0[0], a[1] - p0[1])
        nv = (p2[0] - b[0], p2[1] - b[1])
        ph, pvv = abs(pv[1]) <= eps, abs(pv[0]) <= eps
        nh, nvv = abs(nv[1]) <= eps, abs(nv[0]) <= eps
        if not ((ph or pvv) and (nh or nvv)):
            i += 1
            continue
        j = (i + 1) % m
        if pvv and nvv:
            q[j] = (b[0], a[1])
        elif ph and nh:
            q[j] = (a[0], b[1])
        else:
            corner = (a[0], b[1]) if pvv else (b[0], a[1])
            q[i] = corner
            if j == 0:
                del q[0]
            else:
                del q[j]
        fixed += 1
        i = max(0, i - 2)
    if not q:
        return pts, 0
    if closed:
        q.append(q[0])
    return q, fixed


LIFT_MIN_SIDE_MM = 500.0      # 井口短边下限：几百毫米厚的长条是墙，不是电梯井
LIFT_MAX_ASPECT = 10.0        # 井口长宽比上限
LIFT_VERTICAL_ALIGN_MM = 200.0
LIFT_VERTICAL_SIZE_MM = 200.0
_LIFT_FLOOR_CACHE = {}


def _wall_rect_candidates(doc, layer=None):
    """墙层上面积 1–8 m²、短边足够、长宽比合理的闭合矩形。"""
    lay = layer or R.WALL_LAYER
    rects = []
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
        _mn, _mx = sorted((w, h))
        if (abs(a - w * h) / (w * h) < 0.05
                and 1.0e6 < a < 8.0e6
                and _mn >= LIFT_MIN_SIDE_MM
                and _mx / _mn <= LIFT_MAX_ASPECT):
            rects.append((min(xs), min(ys), max(xs), max(ys)))
    return rects


def _wall_rect_groups(rects):
    """按重叠分成组，并标出单件 / 重复件 / 同心井壁 / 共用边台阶。"""
    # ★★ 2026-10-21（c116 用户「那是门口的台阶」）：
    #   同一组矩形若共用一条边、只向另一侧层层缩小，那就是**台阶/楼梯踏面**，
    #   不是井道；同心且四边都缩的是井壁，只保留外框；完全重合的是同一构件的重复。
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a

    for i in range(n):
        ax0, ay0, ax1, ay1 = rects[i]
        for j in range(i + 1, n):
            bx0, by0, bx1, by1 = rects[j]
            ix0, iy0 = max(ax0, bx0), max(ay0, by0)
            ix1, iy1 = min(ax1, bx1), min(ay1, by1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            amin = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
            if amin > 0 and inter / amin > 0.5:
                union(i, j)
    groups = {}
    for i, r in enumerate(rects):
        groups.setdefault(find(i), []).append(r)
    out = []
    for g in groups.values():
        if len(g) == 1:
            out.append(("single", g))
            continue
        g = sorted(g, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)
        same = all(abs(a - b) <= 20 for a, b in zip(g[0], g[1]))
        if same:
            out.append(("duplicate", g))
            continue
        shared = any(
            abs(g[0][k] - r[k]) <= 30 for k in range(4) for r in g[1:]
        )
        if shared:
            out.append(("steps", g))
            continue
        out.append(("concentric", g))
    return out


def lift_rects(doc, layer=None):
    """竖井井口（旧称电梯井）：只保留单件、重复件去重、同心井壁留外框。"""
    out = []
    for kind, g in _wall_rect_groups(_wall_rect_candidates(doc, layer)):
        if kind == "steps":
            continue
        x0, y0, x1, y1 = g[0]
        out.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    return out


def step_rects(doc, layer=None):
    """墙层上共用一条边、逐级缩小的矩形组 → 入口台阶外框。"""
    out = []
    for kind, g in _wall_rect_groups(_wall_rect_candidates(doc, layer)):
        if kind != "steps":
            continue
        x0, y0, x1, y1 = g[0]
        out.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    return out


def _floor_lift_rects(floor):
    if floor not in _LIFT_FLOOR_CACHE:
        p = os.path.join(RAW, floor + ".dxf")
        _LIFT_FLOOR_CACHE[floor] = lift_rects(ezdxf.readfile(p)) if os.path.exists(p) else []
    return _LIFT_FLOOR_CACHE[floor]


def _keep_vertical_lifts(lifts, floor):
    """只保留在**至少两层**同一位置重复出现的井道；只在一层出现的按台阶/平台处理。"""
    if not lifts:
        return lifts, []
    floors = B.floor_names()
    if len(floors) <= 1:
        return lifts, []
    others = [f for f in floors if f != floor]
    keep = []
    dropped = []
    for r in lifts:
        xs = [p[0] for p in r]
        ys = [p[1] for p in r]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        w, h = x1 - x0, y1 - y0
        hit = False
        for f in others:
            for q in _floor_lift_rects(f):
                qx = [p[0] for p in q]
                qy = [p[1] for p in q]
                qx0, qy0, qx1, qy1 = min(qx), min(qy), max(qx), max(qy)
                if (abs((qx0 + qx1) / 2.0 - cx) <= LIFT_VERTICAL_ALIGN_MM
                        and abs((qy0 + qy1) / 2.0 - cy) <= LIFT_VERTICAL_ALIGN_MM
                        and abs((qx1 - qx0) - w) <= LIFT_VERTICAL_SIZE_MM
                        and abs((qy1 - qy0) - h) <= LIFT_VERTICAL_SIZE_MM):
                    hit = True
                    break
            if hit:
                break
        if hit:
            keep.append(r)
        else:
            dropped.append(r)
    return keep, dropped


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


# ------------------------------------------------------------------ 门名单（唯一一份）
def _rect_hit(r1, r2, ratio=0.35):
    """两个门框是不是**同一樘门**：bbox 交集面积 / 较小面积 > ratio。

    入参是**门字典里的 `bbox`**（扁四元组 x0,y0,x1,y1），不是 `rect`
    —— `rect` 是**四点多边形** `[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]`，
    拿它当下标取的「x0/y0/x1/y1」是点不是数：`max/min` 按元组比大小仍能跑，
    减一下就 `TypeError: tuple - tuple`（c112 实测），**判重则在无声地永远返回 False**
    ⇒ 补收的门一樘都不去重（2026-10-18 我自己踩的：第一轮扫描数全是「未去重」的）。
    只用框重叠一种判据，不掺距离/朝向 —— 同一扇门无论用符号还是开启弧画，
    两种量法给出的 bbox 都叠在一起；不同门之间的框实测互不相交。
    """
    x0, y0 = max(r1[0], r2[0]), max(r1[1], r2[1])
    x1, y1 = min(r1[2], r2[2]), min(r1[3], r2[3])
    if x1 <= x0 or y1 <= y0:
        return False
    a1 = (r1[2] - r1[0]) * (r1[3] - r1[1])
    a2 = (r2[2] - r2[0]) * (r2[3] - r2[1])
    m = min(a1, a2)
    return m > 0 and (x1 - x0) * (y1 - y0) / m > ratio


def _leaf_lines(picked, max_len_mm=None):
    """每樘门补一条**关门姿态**的门扇线（两点），建件时按名义厚 50 mm 张成门扇。

    为什么要有（2026-10-18 用户「你画的门，每个楼要一样」）：
      c006 走 INSERT 块路径，块里自带两点扇线 ⇒ 建出 门扇 34/181/164/160 片；
      其余 66 栋走「符号 / 开启弧」路径，门只有**多边形轮廓**（`door_leafs` 不收）
      ⇒ 建出 **门扇 0 片**，模型上只有洞没有门。同一套链，两种楼两种长相。

    口径（**只此一条，全库同一长相**）：沿洞口**长轴**、过洞口短轴中线画一条线，
      长度 = 洞口净宽；净宽超过 `max_len_mm`（默认取源图门扇块最长边的 1800 mm）
      就等分 —— 2.4 m 正门出 2 片 1.2 m（与 c006 的双扇同形）。
      ★ 不取「开启姿态」：符号门的扇线在 16/23 点带 bulge 的多段线里，取不出来；
        弧门的铰点要另算一套几何。关门姿态三种画法都能从 `bbox` 直接得到，
        **判据只有一份**，各栋不会长成两样。
    ★ 用 `bbox`（扁四元组 x0,y0,x1,y1）**不是** `rect`（四点多边形）—— 见 `_rect_hit`。
    """
    if max_len_mm is None:
        max_len_mm = LEAF_SPLIT_MM
    out = []
    for d in picked:
        # ★★ 2026-10-18：**源图里就有扇线**（symbols 的直段 / arcs 的合页→贴墙端），
        #   优先直接取；只有源图画法里找不到时才退回「bbox 中线」那一档。
        #   c005 实测：退回档 49 扇离墙中位 0.320 m；源图档贴着墙中线（= c006 的长相）。
        segs = d.get("leaf_segs") or []
        if segs:
            for s in segs:
                out.append([tuple(s[0]), tuple(s[1])])
            continue
        x0, y0, x1, y1 = d["bbox"]
        w, h = x1 - x0, y1 - y0
        L, T = (w, h) if w >= h else (h, w)
        if L <= 0 or T <= 0:
            continue
        n = max(1, int(-(-L // max_len_mm)))          # 向上取整，不引 math
        step = L / n
        if w >= h:                                    # 长轴沿 x
            yc = (y0 + y1) / 2.0
            for i in range(n):
                out.append([(x0 + i * step, yc), (x0 + (i + 1) * step, yc)])
        else:                                         # 长轴沿 y
            xc = (x0 + x1) / 2.0
            for i in range(n):
                out.append([(xc, y0 + i * step), (xc, y0 + (i + 1) * step)])
    return out


def doors_for_floor(doc, src, floor="", union=True, verbose=True, walls=None):
    """一层的门名单 —— **画法判据只有这一份**（`geometry()` 与 `scan_door_union.py` 同调）。

    返回 `(doors, door_voids, door_widths, door_leaves)`：
      doors       [(pts, closed)]  门块折线（建件用）
      door_voids  [rect]           **门洞框**（抠洞用；INSERT 块路径没有框 ⇒ 空表）
      door_widths [mm]             净宽
      door_leaves [ [p0, p1] ]     门扇线（`_leaf_lines` 现算；块路径为空 —— 块自带扇线）

    ★ 三种画法（符号 / 开启弧 / INSERT 块）各认一遍；档案 `drawing.doors` 指定**主画法**，
      另外两种认到的门**只要与已收的门框不重叠就补收**。
      2026-10-18 用户「c004 的门不对」实测：c004 1 层有 26 樘开启弧（走廊墙）
      + 南侧正门 **3 樘 2.4 m 双开门符号**（x 35650~47150，与弧不重叠）。旧逻辑
      「当前画法认到 0 樘才换画法」同层有 26 ≠ 0 ⇒ 那 3 樘正门**从来没被认过**，
      模型上正门无洞。兜底改成「补收」后，既不改已认到的那批，也不漏另一种画法。
    ★ `union=False` = 旧口径（只走档案画法），供 `scan_door_union.py` 量「补收几樘」。
    """
    _s = door_symbols(doc, layer=DOOR_LAYER, walls=walls)
    _a = door_arcs(doc, layer=DOOR_LAYER)
    # 主画法优先序：档案钉死的那一种在前；auto = 开启弧 > 符号（c009 实测：弧判据最硬，
    # 符号里混着窗的画法）。块只在两种都 0 樘时才用 —— 块没有门洞框，不能与框混收。
    if DOOR_MODE == "symbols":
        order = [("符号", _s), ("开启弧", _a)]
    elif DOOR_MODE in ("arcs", "auto"):
        order = [("开启弧", _a), ("符号", _s)]
    else:
        order = []

    _prim_name, _prim = next(((n, v) for n, v in order if v), (None, []))
    if _prim:
        picked = list(_prim)
        added = []
        if union:
            for _n, _v in order:
                if _n == _prim_name:
                    continue
                for _d in _v:
                    if not any(_rect_hit(_d["bbox"], _e["bbox"]) for _e in picked):
                        picked.append(_d)
                        added.append(_n)
        if verbose:
            _msg = ("  ▷ %s 门画法[%s]：符号 %d / 开启弧 %d → 主画法 %s %d 樘"
                    % (floor, DOOR_MODE, len(_s), len(_a), _prim_name, len(_prim)))
            if added:
                _c = {n: added.count(n) for n in dict.fromkeys(added)}
                _msg += "，补收 %d 樘（%s，与主画法不重叠）" % (
                    len(added), "、".join("%s %d" % kv for kv in _c.items()))
            if DOOR_ARC_UNRESOLVED:
                _msg += "；开启弧没贴到墙 %d 条" % len(DOOR_ARC_UNRESOLVED)
            print(_msg)
        _leaves = _leaf_lines(picked)
        if verbose:
            # ★ 扇线来路必须印出来：源图取到 / 退回 bbox 中线，两种长相不同（铁律 028）。
            _n_src = sum(len(d.get("leaf_segs") or []) for d in picked)
            _n_fb = sum(1 for d in picked if not (d.get("leaf_segs") or []))
            if _n_src or _n_fb:
                print("  ▷ %s 门扇线[%s]：源图直段 %d 段 · 退回中线 %d 樘"
                      % (floor, DOOR_MODE, _n_src, _n_fb))
        return ([(d["pts"], False) for d in picked],
                [d["rect"] for d in picked],
                [d["width_mm"] for d in picked],
                _leaves)

    # 主画法一樘都没有 ⇒ 才轮到 INSERT 块（与旧行为一致）
    _b = blocks_wcs(src, prefix=DOOR_PREFIX)
    # ★★ 2026-10-18（用户「色块就是不对」「后面其他的建筑就不能再出现这些问题」）：
    #   块画法原来返回 `door_voids=[]` —— 于是装包器「门口补条」那一步**从不执行**，
    #   c006 1 层 33 个房间号挂在 4 个连通区里（14/14/4/1），一层只出 4 片房垫。
    #   块里其实画着开启弧（1 层 116 块 / 189 根弧，半径全在 `doors_arc_r_mm` 窗内）：
    #   门洞框改由 `door_arcs(include_blocks=True)` 现算，**判据与弧画法同一份**。
    #   `doors` 仍用块折线 —— 建件的口径（门扇/门头墙）一个字不动。
    _av = door_arcs(doc, layer=DOOR_LAYER, include_blocks=True) if _b else []
    if verbose:
        if _b:
            print("  ▷ %s 符号/开启弧都 0 樘，INSERT 块 %d 樘 → 采用块"
                  "（块内开启弧认出门洞 %d 樘）" % (floor, len(_b), len(_av)))
        else:
            print("  ▷ %s 三种画法各 0 樘：这一层图上没有可认的门 —— 按无门建" % floor)
    return (_b, [d["rect"] for d in _av], [d["width_mm"] for d in _av], [])


# ------------------------------------------------------------------ 扇线贴墙
LEAF_SNAP_MAX_MM = 1000.0      # 扇线离墙超过这个距离 ⇒ 认定「不在这层墙上」，不动它
WALL_CENTER_MAX_MM = 600.0     # 穿墙找中线时，墙带超过这个厚度就当量不到（不做插值猜）


def _snap_leaves_to_wall(leaves, walls):
    """把**没贴墙**的扇线平移到墙带的中心线上（2026-10-19 用户「c086 门错了位置」）。

    退回档（`_leaf_lines` 里没有 `leaf_segs` 的门）= 门符号 bbox 长轴过中心；
    而符号 bbox **含开启弧** ⇒ 中心落在房间里：c086 1 层 67 樘里 39 樘走退回档，
    扇线离墙 285~400 mm，模型上门立在空中（用户看到的就是这个）。
    ★ 只动**不与墙带相交**的线；源图档/块档本来就贴墙，一个像素不动。
    ★ 平移到**墙带中心线**（不是墙面）：沿扇线**法向**穿墙取两端中点。
      2026-10-21（c116「门没在墙中」）：旧实现沿「中点到最近墙面」的方向平移，
      这个方向在洞口附近会被墙端头带斜，产生 470~480 mm 的沿墙错位；
      门扇只能沿自己的法向移动，沿扇线方向必须保持源图位置。
    ★ 离墙 > `LEAF_SNAP_MAX_MM` 或墙带量不出中线 ⇒ 原样保留并计数（不静默）。
    返回 `(新扇线表, 平移条数)`。
    """
    if not leaves or not walls:
        return leaves, 0
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    def _p(pts, holes=()):
        g = Polygon(pts, holes)
        return g if g.is_valid else g.buffer(0)

    W = unary_union([_p(s, h) for s, h in walls])
    if W.is_empty:
        return leaves, 0
    out, moved = [], 0
    for a, b in leaves:
        ln = LineString([a, b])
        d = ln.distance(W)
        # ★★ 2026-10-21 第二错（c116「门还是没有和墙齐平」实测）：
        #   旧判断用 `距离墙=0` 当「已经在墙里」。可门扇线沿墙皮走、末端碰到
        #   一道垂直墙时，距离同样是 0 —— 实际扇线仍贴在墙**表面**，一半在房间外。
        #   判据必须看「这条线有多少长度真的落在墙带内部」：
        #   整条线基本被墙带覆盖才算已对齐；仅在端点擦到墙不算。
        try:
            covered = ln.intersection(W).length
        except Exception:                                 # noqa: BLE001
            covered = 0.0
        if ln.length > 0 and covered >= 0.90 * ln.length:
            out.append((a, b))
            continue
        if d > LEAF_SNAP_MAX_MM:           # 这扇门不在这层墙上 ⇒ 不动，交给上层记账
            out.append((a, b))
            continue
        mp = ln.interpolate(0.5, normalized=True)
        (x0, y0), (x1, y1) = ln.coords[0], ln.coords[-1]
        L = math.hypot(x1 - x0, y1 - y0)
        if L <= 0:
            out.append((a, b))
            continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        nx, ny = -uy, ux                  # 沿扇线法向穿墙
        probe = LineString([(mp.x - 2000 * nx, mp.y - 2000 * ny),
                            (mp.x + 2000 * nx, mp.y + 2000 * ny)])
        inter = probe.intersection(W)
        segs = [inter] if inter.geom_type == "LineString" else list(getattr(inter, "geoms", []))
        candidates = []
        for s in segs:
            if (s.geom_type != "LineString" or s.length <= 0
                    or s.length > WALL_CENTER_MAX_MM or len(s.coords) < 2):
                continue
            cx = (s.coords[0][0] + s.coords[-1][0]) / 2.0
            cy = (s.coords[0][1] + s.coords[-1][1]) / 2.0
            candidates.append((math.hypot(cx - mp.x, cy - mp.y), cx, cy))
        if not candidates:
            out.append((a, b))
            continue
        _, cx, cy = min(candidates)
        # 只允许沿扇线法向移动；沿扇线方向保持源图坐标（否则门会沿墙滑开）。
        t = (cx - mp.x) * nx + (cy - mp.y) * ny
        dx, dy = t * nx, t * ny
        out.append(((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy)))
        moved += 1
    return out, moved


def _planter_wall_poly(shell, holes):
    """首层孤立、矮胖、空心比例高的墙块 → 花台/景墙（统一按 20 cm 建）。"""
    from shapely.geometry import Polygon

    try:
        p = Polygon(shell, holes)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty or p.geom_type != "Polygon":
            return None
    except Exception:                                     # noqa: BLE001
        return None
    x0, y0, x1, y1 = p.bounds
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return None
    area = p.area / 1e6
    bbox_area = w * h / 1e6
    ratio = area / bbox_area if bbox_area > 0 else 0.0
    aspect = max(w, h) / max(min(w, h), 1e-9)
    if 1.5 <= area <= 12.0 and 3.0 <= bbox_area <= 60.0 \
            and 0.18 <= ratio <= 0.75 and 1.8 <= aspect <= 8.0:
        return p
    return None


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
    wmask, (ox, oy, res) = np.array(a["wmask"], copy=True), a["geo"]
    doc = ezdxf.readfile(src)

    # ★★ 2026-10-21 用户令：一层入口台阶被墙层闭运算吃进墙带，必须在**描墙之前**
    #   把它们从墙掩膜里挖掉；否则台阶会被拉成整层高的墙。
    steps = step_rects(doc)
    lifts_all = lift_rects(doc)
    lifts, lift_dropped = _keep_vertical_lifts(lifts_all, floor)
    steps.extend(lift_dropped)
    # 人工指认的花台/台阶（坐标来自已复核的 WALL 块）：同样先从墙掩膜剔除，
    # 再按 STEP_H_M 统一出件。数据写在楼栋档案 `planter_walls`，不改代码常量。
    _manual_steps = (B.profile().get("planter_walls") or []) if floor == B.floor_names()[0] else []
    for ring in _manual_steps:
        if isinstance(ring, list) and len(ring) >= 3:
            steps.append([[float(pt[0]), float(pt[1])] for pt in ring])
    if _manual_steps:
        print("  ▷ %s 人工花台/平台：%d 组" % (floor, len(_manual_steps)))
    for rect in steps:
        pts = np.asarray([[(round((x - ox) / res), round((y - oy) / res))
                           for x, y in rect]], dtype=np.int32)
        cv2.fillPoly(wmask, pts, 0)
    if steps:
        print("  ▷ %s 台阶/平台：%d 组，已从墙掩膜剔除（统一按 20 cm 高建）"
              % (floor, len(steps)))

    if COL_MODE == "auto":
        # ★ 2026-10-17：柱也有两种画法（INSERT 块 / 图层上的多段线），而**同一栋楼里**
        #   可能两种都用。auto = 两种各认一遍，取认出来的多的；两边读数都打出来。
        _lc = cols_lwpolyline(doc, layer=COL_LAYER)
        _bc = blocks_wcs(src, layer=COL_LAYER)
        cols = _bc if len(_bc) > len(_lc) else _lc
        print("  ▷ %s 柱画法：块 %d / 多段线 %d → 采用 %s"
              % (floor, len(_bc), len(_lc), "块" if cols is _bc else "多段线"))
    elif COL_MODE == "lwpolyline":
        cols = cols_lwpolyline(doc, layer=COL_LAYER)
    else:
        cols = blocks_wcs(src, layer=COL_LAYER)
    # ★ 2026-10-19：柱「方框+打叉」是自交折线 ⇒ 只留面积最大的那个子环（详见 `_column_loop`）。
    _n_col0 = len(cols)
    _cols2 = []
    _n_cut = 0
    for _p, _cl in cols:
        _q = _column_loop(_p)
        if len(_q) != len(_p):
            _n_cut += 1
        _cols2.append((_q, _cl))
    cols = _cols2
    if _n_cut:
        print("  ▷ %s 柱折线去内叉：%d/%d 根" % (floor, _n_cut, _n_col0))

    # ★★ 2026-10-20（用生成 DXF 反查原始图时发现）：**墙层上的全圆是圆柱，此前一根都没建**。
    #   `recognize.wall_segments` 里 `CIRCLE` 只有 `keep_circle=True` 才取，而全仓**没有人传 True**
    #   （2026-10-20 全仓 grep），于是这些圆两头落空：不当墙、也不当柱。
    #   实测：40 栋墙层上有全圆（c005 四角 4 根 r=600；c062 5 根 r=350…），
    #   而它们正是「柱」——没有柱层的楼（48 栋）柱数因此恒为 0。
    #   半径窗口 100~1000 mm：c009 的 r=3600（圆形中庭，7.2 m 直径）与 c105 的 r=34.8
    #   不是柱，必须排除；窗口外只打读数不建件。
    _r_lo, _r_hi = 100.0, 1000.0
    _n_circ = _n_circ_skip = 0
    _circ_cols = []
    for _e in doc.modelspace():
        if _e.dxftype() != "CIRCLE" or _e.dxf.layer != R.WALL_LAYER:
            continue
        _rr = float(_e.dxf.radius)
        if not (_r_lo <= _rr <= _r_hi):
            _n_circ_skip += 1
            continue
        _cx, _cy = float(_e.dxf.center.x), float(_e.dxf.center.y)
        _q = [(_cx + _rr * math.cos(2 * math.pi * k / 16.0),
               _cy + _rr * math.sin(2 * math.pi * k / 16.0)) for k in range(16)]
        _circ_cols.append((_q, True))
        _n_circ += 1
    if _circ_cols:
        cols = list(cols) + _circ_cols
    if _n_circ or _n_circ_skip:
        print("  ▷ %s 墙层全圆：建圆柱 %d 根（r %.0f~%.0f mm）· 窗口外跳过 %d（不是柱）"
              % (floor, _n_circ, _r_lo, _r_hi, _n_circ_skip))
    # ★ 踏步线：**判据只有一份**，在 `recognize.tread_lines` 里
    #   （同角度 + 共享一条边 + 步距落在 [180,400]，且长于 600 mm）。
    #   旧版这里自己写了一遍「墙层 ∩ 100<L<3000 ∩ 中点在锚区内」——同一条错判据同时出现在
    #   这里和 `recognize.drop_treads` 里，实测 12 层被它剔掉 4448 条墙层线（其中真踏步只有 964 条）
    #   ⇒ 短墙被当成踏步删掉 = 用户报的「部分墙体缺失」；同时踏步数虚高、踏高被挤到 70 mm
    #   = 用户报的「楼梯不对」。两处现在都调同一个函数，不会再各写一遍。
    treads = R.tread_lines(doc, a["zones"])

    cnts, hier = cv2.findContours(wmask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    walls = []
    n_sq = 0
    n_straight = 0
    for j in range(len(cnts)):
        if hier[0][j][3] != -1:                          # 只取外环
            continue
        shell = _contour_mm(cnts[j], res, ox, oy)
        if len(shell) < 3:
            continue
        # ★ 2026-10-21 用户「斜的墙面不是直线，c001 比较明显」：
        #   栅格斜边是一条条 25 mm 台阶；先用容差化简拉直，再处理丁字口的小 45° 台阶。
        shell, _n_straight = _straighten_wall_ring(shell, res)
        n_straight += _n_straight
        # ★ 2026-10-19 用户「墙和墙接触的地方为啥不是直角」：栅格 8 连通描边留下的
        #   1~2 px 45° 台阶在这里折成直角。墙与墙相接的丁字口全部落在这条路上。
        shell, _n1 = _square_pixel_steps(shell, res)
        n_sq += _n1
        holes = []
        for k in R._children(hier, j):
            _h0 = _contour_mm(cnts[k], res, ox, oy)
            _h1, _n_h_straight = _straighten_wall_ring(_h0, res)
            n_straight += _n_h_straight
            h, _n2 = _square_pixel_steps(_h1, res)
            n_sq += _n2
            if len(h) >= 3:
                holes.append(h)
        walls.append((shell, holes))
    if n_straight:
        print("  ▷ %s 墙轮廓斜边拉直：%d 个栅格台阶点" % (floor, n_straight))
    if n_sq:
        print("  ▷ %s 墙轮廓像素台阶折直角：%d 处" % (floor, n_sq))

    # ★★ 2026-10-21 用户指认 c005「1层-墙体-008」是花台：
    #   首层孤立、矮胖、面积 1.5–12 m²、外框填充率 18–75% 的墙块不是建筑墙，
    #   而是花台/景墙的围边。从 WALL 中移出，统一并与台阶一起按 20 cm 高建。
    if floor == B.floor_names()[0]:
        _kept_walls = []
        _n_planter = 0
        for shell, holes in walls:
            q = _planter_wall_poly(shell, holes)
            if q is None:
                _kept_walls.append((shell, holes))
                continue
            _n_planter += 1
            steps.append([[round(float(x), 1), round(float(y), 1)]
                          for x, y in q.exterior.coords])
        if _n_planter:
            walls = _kept_walls
            print("  ▷ %s 花台/景墙：%d 块已从 WALL 移出（按 20 cm 高建）"
                  % (floor, _n_planter))

    # ★ 门符号的墙向要在墙带算出之后判定：近方形门符号的 bbox 长边可能被开启弧带偏。
    #   墙带与门候选互不依赖，先算墙再认门不会改变墙本身的读数。
    doors, door_voids, door_widths, door_leaves = doors_for_floor(
        doc, src, floor, walls=walls)

    plate = plate_contours(wmask, res, ox, oy)
    # ★ 2026-10-19：退回档扇线立在房间里（用户「c086 门错了位置」）⇒ 统一贴回墙带中线。
    #   放在这里是因为墙带刚算出来；源图档/块档本来贴墙，这一步是空操作。
    door_leaves, _lm = _snap_leaves_to_wall(door_leaves, walls)
    if _lm:
        print("  ▷ %s 扇线没贴墙：%d 条已平移到墙带中线" % (floor, _lm))

    return {"walls": walls, "cols": cols, "doors": doors, "treads": treads,
            "plate": plate, "lifts": lifts, "steps": steps,
            # ★ 2026-10-17：门洞（仅 `doors="symbols"` 的图非空）—— 源图墙线不断，
            #   build3d 必须拿它显式抠墙；`door_widths` 是净宽读数（自检用）。
            "door_voids": door_voids, "door_widths": door_widths,
            # ★ 2026-10-18：块画法的门洞**补条**（`door_voids` 对块恒空）。只喂「楼板−墙带」
            #   分区，**绝不**并进 `door_voids` —— 那条路是 build3d 显式抠模型的，口径不同。
            #   ★ 不带 `if not door_voids` 的条件：块分支现在也能从**部分**贴墙的弧
            #     认出 71/189 根（位置还不对），拿它当「已经有框了」就会把补条清空 ——
            #     1 层实测正是这样：door_voids=71、door_plugs=0 ⇒ 分区仍是 21/4 片。
            "door_plugs": block_door_plugs(doc),
            # ★ 2026-10-18：门扇线（全库同一长相，见 `_leaf_lines`）。块路径为空表。
            "door_leaf_lines": door_leaves,
            "door_mode": DOOR_MODE,
            "n_seg": len(walls), "n_col": len(cols), "n_door": len(doors),
            "A_wall": a["A_wall"], "res": res, "ox": ox, "oy": oy,
            "zones": a["zones"]}


# ------------------------------------------------------------------ 画（共用一份几何）
def draw(floor):
    """把一层的几何画进一个坐标轴，**数据坐标 = mm**。返回 (fig, ax, v)。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.patches import PathPatch, Polygon
    from matplotlib.path import Path

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
