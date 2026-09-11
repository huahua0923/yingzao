# -*- coding: utf-8 -*-
"""构件分类：把 DXF 实体分成墙 / 门 / 台阶 / 柱四类。

【理化楼基线】约定：墙/门/台阶都在同一图层，用 LWPOLYLINE 点数区分；柱在独立图层。
【六教 C006】约定不同（墙=LINE+ARC，门=4 点矩形，柱=INSERT），见 profiles/j6.py 的说明，
后续在「逐模块改算法」阶段为六教单独实现分类器。
"""


import math

from ezdxf.path import make_path

# ---- 弧要素(曲墙) ----
# 图上「弧」有两种来源: ARC 实体, 以及 LWPOLYLINE 段上的 bulge(凸度)。
# 半径小于 CURVE_MIN_R 的弧 = 门扇开启弧 / 装饰弧(实测各楼门弧 0.5~1.5m), 不是墙;
# 半径 >= CURVE_MIN_R 的弧 = 曲墙(实测 c006 逸夫楼 8.3~12.4m、c041 26~29m、c103 16~24m)。
# 曲墙要按弧离散成密集短段再交下游: 默认路径 derive_walls_and_outline 本身方向无关
# (2 点线 buffer 后 union), 能吃任意方向段; 旧代码把 ARC 整体丢弃、把 bulge 段当直弦,
# 才是「曲墙识别不出来」的根因。
CURVE_MIN_R = 2.0        # 米: 判定「曲墙」而非「门弧」的半径阈值
CURVE_STEP_MM = 250.0    # 弧离散步长(mm): 0.25m 一段


def _seg_radius(p0, p1, bulge):
    """一段(两端点 + 凸度)的半径(图纸单位, 通常 mm)。非弧段返回 None。"""
    b = abs(bulge)
    if b < 1e-9:
        return None
    chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if chord < 1e-9:
        return None
    theta = 4.0 * math.atan(b)      # 圆心角
    s = math.sin(theta / 2.0)
    if s < 1e-9:
        return None
    return chord / (2.0 * s)


def _has_curve(e, min_r_mm=CURVE_MIN_R * 1000.0):
    """LWPOLYLINE 是否含「曲墙级」弧段(半径 >= min_r_mm)。"""
    try:
        pts = list(e.get_points("xyseb"))
    except Exception:
        return False
    for i in range(len(pts) - 1):
        b = pts[i][4] if len(pts[i]) > 4 else 0.0
        r = _seg_radius((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]), b)
        if r is not None and r >= min_r_mm:
            return True
    return False


def _flatten_curve(e, step_mm=CURVE_STEP_MM):
    """把带 bulge 的 LWPOLYLINE 离散成点列; 失败返回 None(调用方回退原顶点)。"""
    try:
        return [(float(q.x), float(q.y)) for q in make_path(e).flattening(step_mm)]
    except Exception:
        return None


def _in_x_range(pts, p):
    """X 隔离：floor_plans 两列布局按各层 X 区间并集过滤；否则按 x_range；均无则全保留。"""
    if not p.floor_plans and not p.x_range:
        return True
    xs = [pt[0] for pt in pts]
    cx = (min(xs) + max(xs)) / 2
    from .profile import in_floor_x_range
    return in_floor_x_range(p, cx)


def classify(msp, p):
    """返回 (walls, doors, stairs, columns_raw)。

    「读图成图唯一主路径」：墙 = 墙层上所有 >=2 点的 LWPOLYLINE（含 2 点墙皮线、
    3+ 点填充墙、带门洞缺口/弧线的复杂墙多边形）。
    默认门/台阶不按点数区分——点数阈值会误把「带门洞缺口的外墙」判成门
    （c022 的 16 点外墙被误删后轮廓塌陷），门/台阶改由几何尺寸在后续阶段判定。

    例外：p.door_by_points=True（理化楼）恢复「按点数分门/台阶」。理化楼的门符号是
    16/23 点多段线，其中 23 点双门是「闭合」的（摆动弧回到起点），通用几何判定
    （不闭合折线）会把 72 个双门全部漏掉、且闭合双门被当墙 blob 糊进墙 union——
    必须在此阶段按点数把门/台阶从墙里剥出来，门洞后续再挖进墙。
    """
    walls, doors, stairs = [], [], []
    by_points = getattr(p, "door_by_points", False)
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == p.wall_layer:
            raw = [tuple(pt[:2]) for pt in e.get_points()]
            if len(raw) < 2:
                continue
            if not _in_x_range(raw, p):
                continue
            if by_points:
                # 点数判定必须在「原始点数」上做: 离散会把点数翻十几倍, 否则墙会被判成门
                lp = len(raw)
                if lp >= p.door_min_points:
                    doors.append(raw)
                    continue
                if lp == p.stair_points:
                    stairs.append(raw)
                    continue
            if _has_curve(e):
                # 曲墙: 按弧离散成 0.25m 短段(LWPolyline 无 flattening, 走 ezdxf.path)
                tp = _flatten_curve(e)
                if tp and len(tp) >= 2:
                    walls.append(tp)
                continue
            walls.append(raw)

    # ARC 实体: 墙层上「曲墙级」半径的弧 = 曲墙(c006 逸夫楼 54 段圆弧外墙)。
    # 同一层上还画着门扇开启弧(半径 0.5~1.5m), 必须排除, 否则每扇门都长出一堵墙。
    for e in msp:
        if e.dxftype() != "ARC" or e.dxf.layer != p.wall_layer:
            continue
        if e.dxf.radius < CURVE_MIN_R * 1000.0:
            continue
        tp = [(float(q[0]), float(q[1])) for q in e.flattening(CURVE_STEP_MM)]
        if len(tp) < 2 or not _in_x_range(tp, p):
            continue
        walls.append(tp)

    columns_raw = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == p.column_layer:
            pts = [tuple(pt[:2]) for pt in e.get_points()]
            if not _in_x_range(pts, p):
                continue
            xs = [pt[0] for pt in pts]
            ys = [pt[1] for pt in pts]
            columns_raw.append((min(xs), min(ys), max(xs), max(ys)))

    return walls, doors, stairs, columns_raw
