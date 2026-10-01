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

# 门扇半径区间：与 geometry._hinge_leaf 同一口径（门扇线长度区间）。
# 半径落在这里的墙层 ARC = 门扇开启弧，是**门**的证据而非墙（见 classify 里的 ARC 循环）。
from .component_library import DOOR_LEAF_MAX, DOOR_LEAF_MIN           # noqa: E402


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


# 墙层「小尺寸整圆椭圆」= 符号，不是墙。实测 c009 0.24m/72 条（张角全 360°）、c026 0.26m/24 条、
# c108 0.40m/10 条，三栋的尺寸分布**完全分离**：符号最长 0.40m，真曲墙最短也在米级
# （CURVE_MIN_R=2m）。门槛取长半轴 1.0m，落在两簇之间，实测只剩 c009 会变。
SYMBOL_ELLIPSE_MAX_MM = 1000.0

# 柱层圆柱最小半径（mm）：比任何真实柱都小（Φ160），用于剔标识圆/装饰点。
COLUMN_MIN_R_MM = 80.0


def _flatten_curve_ent(e, step_mm=CURVE_STEP_MM):
    """ELLIPSE / SPLINE → 点列（图纸单位）；失败返回 None（调用方跳过）。

    ezdxf 1.4 的 `Ellipse.flattening` / `Spline.flattening` 都是按**最大弦长**细分，
    与 `_flatten_curve` 对 LWPOLYLINE bulge 用的同一口径（CURVE_STEP_MM=0.25m）。
    """
    try:
        return [(float(q[0]), float(q[1])) for q in e.flattening(step_mm)]
    except Exception:
        return None


def _ellipse_major_mm(e):
    """ELLIPSE 长半轴长度（图纸单位）。major_axis 是**向量**，长度即长半轴。"""
    mj = e.dxf.major_axis
    return math.hypot(float(mj[0]), float(mj[1]))


def _in_x_range(pts, p):
    """X 隔离：floor_plans 两列布局按各层 X 区间并集过滤；否则按 x_range；均无则全保留。"""
    if not p.floor_plans and not p.x_range:
        return True
    xs = [pt[0] for pt in pts]
    cx = (min(xs) + max(xs)) / 2
    from .profile import in_floor_x_range
    return in_floor_x_range(p, cx)


def _arc_doors(door_arcs, wvset):
    """门扇开启弧 → 门候选 `[贴墙端, 弧心, 扇尖]`（CAD 图纸单位，与 `doors` 同口径）。

    **哪一端贴墙**：用墙层画出来的顶点做**哈希**判定，不做距离搜索（全楼 1.2 万顶点 ×
    98 弧 × 2 端的长距离计算没必要）。这个捷径不是猜的 —— 实测 c009 96/98 条弧恰好
    一端命中墙顶点(0.1mm 网格内)、另一端离铰点一个半径，比值 1.00。
    两端命中状态**相同**（都命中=弧跨在两面墙之间；都不命中=墙顶点没画出来）的一律丢弃
    并计数：宁可少画一扇门，也不猜一个门心 —— 门心猜错会沿法向偏 r/3，门洞盒切不到墙，
    结果是「门夹在墙里看不到」，比少一扇门更难查。

    顶点按 0.1mm 网格量化后比对（浮点大数相减会丢有效位，同 DOOR_SYMBOL_TOL 的教训）。
    """
    out, n_amb = [], 0
    for c, (p0, p1) in door_arcs:
        h0 = (round(p0[0], 1), round(p0[1], 1)) in wvset
        h1 = (round(p1[0], 1), round(p1[1], 1)) in wvset
        if h0 == h1:
            n_amb += 1
            continue
        wall_end, tip = (p0, p1) if h0 else (p1, p0)
        out.append([wall_end, c, tip])
    if n_amb:
        print("   ⚠ 门弧两端贴墙状态相同，丢弃 %d 条（无法定门心，见 _arc_doors 说明）" % n_amb)
    return out


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
    wvset = set()                     # 墙层折线**画出来的顶点**，用于判门弧哪一端贴墙
    by_points = getattr(p, "door_by_points", False)
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == p.wall_layer:
            raw = [tuple(pt[:2]) for pt in e.get_points()]
            if len(raw) < 2:
                continue
            if not _in_x_range(raw, p):
                continue
            wvset.update((round(q[0], 1), round(q[1], 1)) for q in raw)
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

    # ARC / ELLIPSE / SPLINE 三种「曲线」图元都在墙层上，按几何分三类：
    #   ① 大半径（r >= CURVE_MIN_R）弧、以及**够大的**椭圆/样条 → 曲墙，离散后进 walls；
    #   ② 半径落在门扇区间的 ARC      → **门扇开启弧**，进 door_arcs 由 floor.py 还原成门；
    #   ③ 小尺寸整圆椭圆              → 符号（见 SYMBOL_ELLIPSE_MAX_MM），丢弃并计数。
    #
    # ELLIPSE / SPLINE 必须读 —— 这是 c009 一层（学术报告厅）的**整圈外弧**：
    #   图纸把弧墙画成 ELLIPSE(长半轴 14.15/15.70m 短半轴 10.50m) + SPLINE(48~110 控制点)
    #   成对的**两条平行曲线**（= 双线墙的两皮，实测间距 ~0.4m，端点一一对应）。
    #   旧代码只认 LWPOLYLINE/ARC → 整圈外弧丢失 → 墙 union 碎成 19 块、`_biggest_outline`
    #   的 max(area) 只留 129.5㎡ 的小环 → 该层轮廓塌成 33.6×60.1m 的**单翼**(192.7㎡)，
    #   其余各翼的墙被「质心距 outline >1m」全部滤掉 → 该层交付 walls=8、rooms=0、
    #   floor0.json 只有 33KB（同楼其他层 330~390KB）。
    # ② 的门弧说明（c009 墙层 98 条这样的弧）：96 条的**一个端点精确落在墙顶点上**、另一个
    #   恰好离铰点一个半径（比值 1.00）。据此还原：门宽 = 半径，门心 = 贴墙端与弧心的中点
    #   （正落在墙中线上）。旧代码把 ② 直接 continue 丢掉 —— 这是 c009 F2~F5 门=0 的根因。
    #   **绝不能塞进 walls**：0.75m 的半径段会在每扇门的位置长出一堵假墙（"每扇门都长出一堵
    #   墙"），还会把轮廓 union 顶出去。改塞 `doors`，由 floor.py 还原成门。
    door_arcs, n_sym = [], 0
    for e in msp:
        t = e.dxftype()
        if t not in ("ARC", "ELLIPSE", "SPLINE") or e.dxf.layer != p.wall_layer:
            continue
        if t == "ARC":
            r = float(e.dxf.radius)
            if r >= CURVE_MIN_R * 1000.0:
                tp = [(float(q[0]), float(q[1])) for q in e.flattening(CURVE_STEP_MM)]
                if len(tp) < 2 or not _in_x_range(tp, p):
                    continue
                walls.append(tp)
                continue
            if not (DOOR_LEAF_MIN * 1000.0 <= r < min(CURVE_MIN_R, DOOR_LEAF_MAX) * 1000.0):
                continue                  # 比门扇还小 = 装饰弧/柱圈，两边都不要
            c = e.dxf.center
            if not _in_x_range([(float(c[0]), float(c[1]))], p):
                continue
            rs = (float(e.dxf.start_angle), float(e.dxf.end_angle))
            ends = [(float(c[0]) + r * math.cos(math.radians(a)),
                     float(c[1]) + r * math.sin(math.radians(a))) for a in rs]
            door_arcs.append(((float(c[0]), float(c[1])), ends))
            continue
        if t == "ELLIPSE" and _ellipse_major_mm(e) < SYMBOL_ELLIPSE_MAX_MM:
            n_sym += 1                    # ③ 符号：不是墙，也不是门
            continue
        tp = _flatten_curve_ent(e)
        if tp is None or len(tp) < 2 or not _in_x_range(tp, p):
            continue
        walls.append(tp)

    if n_sym:
        print("   ⚠ 墙层小尺寸椭圆(符号) %d 条，未当墙（门槛长半轴 %.1fm，见 classify 说明）"
              % (n_sym, SYMBOL_ELLIPSE_MAX_MM / 1000.0))

    if door_arcs:
        doors.extend(_arc_doors(door_arcs, wvset))

    # 柱层两种画法：
    #   · LWPOLYLINE → 矩形柱，取包围盒；第 5 位 0.0 = 方柱。
    #   · CIRCLE     → **圆柱**，取外接方盒 + 第 5 位记半径。图纸用圆画柱时，旧代码只认
    #     LWPOLYLINE，这些柱一根都读不到 —— c009 一层 40 根 Φ848（r=0.424m）、二层 21、
    #     三层 19，正是用户点名的「独立的柱子结构」。实测 49 栋里只有 c009 用 CIRCLE 画柱。
    # 第 5 位（半径 mm）由 recognize.localize_columns 转成 JSON 的 `round` 字段，
    # GLB 按圆（16 边形）出柱而不是方盒 —— 方盒比同外径圆柱多 27% 面积，看得出是假的。
    columns_raw = []
    for e in msp:
        if e.dxf.layer != p.column_layer:
            continue
        t = e.dxftype()
        if t == "CIRCLE":
            c = e.dxf.center
            r = float(e.dxf.radius)
            if r < COLUMN_MIN_R_MM:
                continue
            if not _in_x_range([(float(c[0]), float(c[1]))], p):
                continue
            columns_raw.append((float(c[0]) - r, float(c[1]) - r,
                                float(c[0]) + r, float(c[1]) + r, r))
            continue
        if t != "LWPOLYLINE":
            continue
        pts = [tuple(pt[:2]) for pt in e.get_points()]
        if not _in_x_range(pts, p):
            continue
        xs = [pt[0] for pt in pts]
        ys = [pt[1] for pt in pts]
        columns_raw.append((min(xs), min(ys), max(xs), max(ys), 0.0))

    return walls, doors, stairs, columns_raw
