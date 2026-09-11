# -*- coding: utf-8 -*-
"""LINE+INSERT 约定分类器（第六教学楼 C006 逸夫楼）。

与 classify.py 的 LWPOLYLINE 基线并列，不改基线逻辑。返回相同的四元组：
  walls        —— 点序列列表（CAD 毫米坐标）
  doors        —— 点序列列表（CAD 毫米坐标）
  stairs       —— 点序列列表（CAD 毫米坐标）
  columns_raw  —— (min_x, min_y, max_x, max_y) 包围盒列表（CAD 毫米坐标）

C006 约定（4.2墙体 图层）：
  - 墙   = LINE（双线平行，轴对齐）＋ 2 点 LWPOLYLINE（短墙段，等同 LINE）
  - 门   = INSERT 块 $DorLib2D$*：块名定窗/门，abs(xscale) 定门宽（单扇 700/900/1000、
           双扇 1500mm），旋转角定朝向（从图读，不强制 profile 值）
  - 台阶 = LWPOLYLINE 5 点（⊓）或 >=20 点（楼梯踏步折线）
  4.1结构柱 图层：
  - 柱   = INSERT 块 _FZHK（方柱）/_YZHK（圆柱），块定义单位 1×1，实际边长由
           xscale/yscale 编码（本图全 600×600mm），位置取插入点 → 包围盒 (±scale/2)。
"""
from .classify import _in_x_range, CURVE_MIN_R
from .curve_walls import pair_arc_bands

# 柱块名（方柱 _FZHK / 圆柱 _YZHK），块定义单位 1×1，实际尺寸由 INSERT xscale/yscale 编码
_COLUMN_BLOCKS = {"_FZHK", "_YZHK"}

# 窗块：xscale=窗宽、yscale=墙厚(240)。窗户按用户约定合成，不进 doors
_WINDOW_BLOCKS = {"$DorLib2D$00000130"}


def _door_points(ix, iy, horiz, w):
    """把一扇门编码成 2 点（沿朝向跨度 = 实际门宽 w，毫米），供 floor.py 消费。

    centroid=插入点；floor.py 用点列跨度读出门宽（真实值），朝向由旋转角定。
    w 来自 INSERT 的 abs(xscale)：单扇 700/900/1000mm、双扇 1500mm。
    """
    half = w / 2.0
    if horiz:
        return [(ix - half, iy), (ix + half, iy)]
    return [(ix, iy - half), (ix, iy + half)]


def _step_tread_mask(pairs):
    """室外台阶踏步识别：2 点 LWPOLYLINE 中「≥3 条平行线、垂直间距 ≤0.45m（踏步深 ~0.3m）、
    走向重叠」的连通簇 = 台阶踏步，应从墙里剔除（室外台阶暂不建模）。

    双线墙是 2 条平行线 0.24m 间距成对（簇大小 2），不满足 ≥3 → 不会被误删；
    单条短墙段簇大小 1，也不误删。返回与输入同序的 bool 列表（True=踏步）。
    """
    n = len(pairs)
    is_tread = [False] * n
    if n < 3:
        return is_tread
    info = []
    for (x0, y0), (x1, y1) in pairs:
        horiz = abs(y1 - y0) <= abs(x1 - x0)
        perp = y0 if horiz else x0
        lo, hi = (min(x0, x1), max(x0, x1)) if horiz else (min(y0, y1), max(y0, y1))
        info.append((horiz, perp, lo, hi))

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        hi_, pi, loi, hii = info[i]
        for j in range(i + 1, n):
            hj, pj, loj, hij = info[j]
            if hi_ != hj:
                continue
            if abs(pi - pj) <= 450.0 and max(loi, loj) < min(hii, hij):
                union(i, j)

    from collections import Counter
    size = Counter(find(i) for i in range(n))
    return [size[find(i)] >= 3 for i in range(n)]


def classify_line(msp, p):
    walls, doors, stairs, columns_raw = [], [], [], []
    two_pt = []   # 2 点 LWPOLYLINE：短墙段 OR 室外台阶踏步，需聚簇区分后决定去留
    arcs = []     # ARC 曲墙：圆心/半径/起止角（毫米、度），配对成墙带后进 walls

    for e in msp:
        if e.dxf.layer != p.wall_layer:
            continue
        t = e.dxftype()
        if t == "LINE":
            pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            if _in_x_range(pts, p):
                walls.append(pts)
        elif t == "LWPOLYLINE":
            pts = [tuple(pt[:2]) for pt in e.get_points()]
            if not _in_x_range(pts, p):
                continue
            n = len(pts)
            if n == 2:
                two_pt.append(pts)             # 2 点 = 短墙段 OR 台阶踏步（聚簇后区分）
            elif n in (5, 6):
                stairs.append(pts)             # 台阶：入口坡道/踏步折线
            # 其余（4 点矩形、>=20 点楼梯井踏步折线）忽略：
            #   门由 INSERT 承载；室内楼梯井由 detect_stairwells 从 LINE 短水平段聚类得出
            #   >=20 点折线是楼梯井踏步轮廓，与 detect_stairwells 冗余，且会让 hw 退化为整栋楼宽
        elif t == "INSERT":
            name = e.dxf.name
            if not name.startswith("$DorLib2D"):
                continue
            if name in _WINDOW_BLOCKS:
                continue                 # 窗块（xscale=窗宽、yscale=墙厚240），窗按约定合成
            ix, iy = e.dxf.insert.x, e.dxf.insert.y
            if not _in_x_range([(ix, iy)], p):
                continue
            rot = round(e.dxf.rotation) % 180
            horiz = rot == 0                 # 0/180 → 水平门（开口沿 X）；90 → 垂直
            w = abs(e.dxf.xscale)            # 实际门宽（毫米），从图读，不强制 profile 值
            doors.append(_door_points(ix, iy, horiz, w))
        elif t == "ARC":
            # 弧形外墙：逸夫楼 54 条同心双皮弧(r 8.30~12.35m, 两皮差 240mm = 真墙厚)。
            # 旧版整条丢弃, 靠 outline 的缓冲/凸包「兜个大概」—— 结果弧形墙面在模型里
            # 根本没长出来(用户 2026-09-10: 「弧形的墙面没有出来」)。这里只收集, 配对
            # 见下方 pair_arc_bands。
            # 半径 < CURVE_MIN_R(2m) 的是门扇开启弧/装饰弧, 必须排除, 否则每扇门长一堵墙。
            if e.dxf.radius < CURVE_MIN_R * 1000.0:
                continue
            c = e.dxf.center
            arcs.append((c.x, c.y, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle))
        # TEXT/MTEXT/CIRCLE 标注忽略

    # 室外台阶踏步：2 点 LWPOLYLINE 聚簇（≥3 条平行线 ~0.3m 间距）从墙里剔除（室外台阶暂不建模）
    tread = _step_tread_mask(two_pt)
    for pts, is_t in zip(two_pt, tread):
        if not is_t:
            walls.append(pts)

    # 曲墙：同圆心 + 半径差 = 墙厚 的两条同心弧配成「环形墙带」，以闭合折线进 walls。
    # 闭合(首尾同点)是关键：geometry.derive_line_walls_and_outline 把「>=4 点闭合折线」
    # 当已成形实心墙直接采纳，不再走双线配对（弧带的内外皮是弧、拆成弦段去配对会被
    # 贪心拆成 240/100 混厚）。
    for band, _t in pair_arc_bands(arcs, p):
        pts = [[round(x, 3), round(y, 3)] for x, y in band.exterior.coords]
        if len(pts) >= 4 and _in_x_range(pts, p):
            walls.append(pts)

    for e in msp:
        if e.dxftype() == "INSERT" and e.dxf.layer == p.column_layer:
            if e.dxf.name not in _COLUMN_BLOCKS:
                continue
            ix, iy = e.dxf.insert.x, e.dxf.insert.y
            if not _in_x_range([(ix, iy)], p):
                continue
            hx = abs(e.dxf.xscale) / 2.0    # 柱边长从图读：块定义单位 1×1，scale 编码实际尺寸
            hy = abs(e.dxf.yscale) / 2.0
            columns_raw.append((ix - hx, iy - hy, ix + hx, iy + hy))

    return walls, doors, stairs, columns_raw
