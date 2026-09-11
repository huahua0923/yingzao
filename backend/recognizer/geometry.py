# -*- coding: utf-8 -*-
"""通用几何算法：墙皮配对 / 楼板轮廓推导 / 楼梯井检测。

这些函数不知道具体是哪栋楼，只接收 profile 里的参数，是「逐模块改算法」的主战场。
"""
import math
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import unary_union

from .profile import to_local, floor_of
from .component_library import SLAB_RATIO, DOOR_LEAF_MIN, DOOR_LEAF_MAX, DOOR_SPAN_MAX


def r2(seq):
    return [[float(round(x, 3)), float(round(y, 3))] for x, y in seq]


def nearest_parallel(c1, lo1, hi1, segs):
    """同向墙段 (c, lo, hi) 的最近平行间距；无重叠邻居返回 None。"""
    best = None
    for c2, lo2, hi2 in segs:
        if min(hi1, hi2) - max(lo1, lo2) <= 0.01:  # 无重叠
            continue
        d = abs(c1 - c2)
        if d < 1e-6:
            continue
        if best is None or d < best:
            best = d
    return best


def pair_rects(segs, horiz, p):
    """墙段配成矩形（双线墙）+ 厚度；无配对用单边厚度兜底。

    沿走向外延 wall_extend 闭合缝隙；返回 [(rect, thickness)]，去重
    （同一堵墙的两条边只配一次）。
    """
    used = set()
    out = []
    for i, (c1, lo1, hi1) in enumerate(segs):
        if i in used:
            continue
        best = None  # (d, j, c2)
        for j, (c2, lo2, hi2) in enumerate(segs):
            if i == j or j in used:
                continue
            d = abs(c1 - c2)
            if not (p.wall_min <= d <= p.wall_max) or min(hi1, hi2) - max(lo1, lo2) < 0.3:
                continue
            if best is None or d < best[0]:
                best = (d, j, c2)
        if best is not None:
            d, j, c2 = best
            used.add(i)
            used.add(j)
            rect = box(lo1 - p.wall_extend, min(c1, c2), hi1 + p.wall_extend, max(c1, c2)) if horiz \
                else box(min(c1, c2), lo1 - p.wall_extend, max(c1, c2), hi1 + p.wall_extend)
            out.append((rect, d, True))
        else:
            used.add(i)
            rect = box(lo1 - p.wall_extend, c1 - p.wall_fallback, hi1 + p.wall_extend, c1 + p.wall_fallback) if horiz \
                else box(c1 - p.wall_fallback, lo1 - p.wall_extend, c1 + p.wall_fallback, hi1 + p.wall_extend)
            out.append((rect, p.wall_fallback * 2, False))
    return out


def recenter_rect(rect, thickness):
    """墙段矩形按「中心线不变、只改厚度」归一化到目标墙厚。

    rect 是 pair_rects 产出的轴向对齐矩形（门洞/楼梯井尚未挖掉，bounds 干净）。
    长轴为墙走向、短轴为墙厚：沿短轴中心线对称缩放厚度，保留沿走向的长度与外延。
    """
    minx, miny, maxx, maxy = rect.bounds
    w = maxx - minx
    h = maxy - miny
    if w >= h:  # 水平墙：长轴 x，厚度在 y
        cy = (miny + maxy) / 2
        return box(minx, cy - thickness / 2, maxx, cy + thickness / 2)
    # 垂直墙：长轴 y，厚度在 x
    cx = (minx + maxx) / 2
    return box(cx - thickness / 2, miny, cx + thickness / 2, maxy)


def _snap_thickness(t, allowed):
    """把检测到的墙厚 snap 到最近的真实墙厚（allowed 升序米值列表）。"""
    return min(allowed, key=lambda a: abs(a - t))


def facade_windows(wall_poly, outline_poly, spec):
    """在外墙直段外立面等距布窗（合成数据，DXF 无窗）。

    判据沿用 build_lihua_full.py：
      - 只取长直段（>= win_min_seg）——墙端 / 门洞切出的短边跳过；
      - 只取贴建筑外轮廓的外立面（边中点距轮廓边界 < 0.35，内立面距轮廓约一个墙厚，天然排除）；
      - 沿墙两端各留 win_margin，剩余 run 按 win_spacing 均布。
    返回 [{x, y, w, h, sill, horiz, dx, dy, nx, ny}]，坐标均为本地米。
    """
    windows = []
    centroid = outline_poly.centroid
    coords = list(wall_poly.exterior.coords)
    for i in range(len(coords) - 1):
        ax, ay = coords[i]
        bx, by = coords[i + 1]
        L = math.hypot(bx - ax, by - ay)
        if L < spec["win_min_seg"]:
            continue
        mx, my = (ax + bx) / 2, (ay + by) / 2
        if outline_poly.boundary.distance(Point(mx, my)) >= 0.35:
            continue  # 非外立面（内立面 / 内墙直段）
        dx, dy = (bx - ax) / L, (by - ay) / L
        nx, ny = dy, -dx  # 沿墙方向旋 90° 得法线
        # 法线翻到朝外（远离质心）
        if (centroid.x - mx) * nx + (centroid.y - my) * ny < 0:
            nx, ny = -nx, -ny
        margin = spec["win_margin"]
        run = L - 2 * margin
        if run < spec["win_min_run"]:
            continue
        nwin = int(run // spec["win_spacing"]) + 1
        step = run / nwin
        for k in range(nwin):
            s = margin + step * k + step / 2
            cx, cy = ax + dx * s, ay + dy * s
            windows.append({
                "x": round(cx, 3),
                "y": round(cy, 3),
                "w": spec["win_w"],
                "h": spec["win_h"],
                "sill": spec["win_sill"],
                "horiz": abs(dx) >= abs(dy),
                "dx": round(dx, 3),
                "dy": round(dy, 3),
                "nx": round(nx, 3),
                "ny": round(ny, 3),
            })
    return windows


def _merge_intervals(intervals, gap_tol=0.05):
    """把重叠/相邻（间隙 < gap_tol）的一维区间合并成极大区间。"""
    if not intervals:
        return []
    merged = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1] + gap_tol:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def _merge_collinear(segs, tol=0.02):
    """把同一根线（center 差 ≤ tol）画出的碎片/重复段合并成极大段，返回 [(c, lo, hi)]。

    C006 每堵墙的一皮被画成 2~30 段共线/重叠 LINE（每到门/柱/拐角断一段，还常有整段
    重复），直接配对会漏掉一半墙（碎片各自找不到 mate → 当单线薄墙 → 轮廓塌/房间丢）。
    先按 center 聚类（tol=0.02m 远小于最薄 60mm 墙，不会把两皮并成一根），簇内用
    _merge_intervals 把重叠与 ≤5cm 缝隙（绘图误差）并成一段；真正的门洞/柱缺口 >5cm 保留。
    """
    if not segs:
        return []
    clusters = []   # [[c...], [(lo,hi)...]]
    for c, lo, hi in sorted(segs, key=lambda s: s[0]):
        if clusters and c - clusters[-1][0][-1] <= tol:
            clusters[-1][0].append(c)
            clusters[-1][1].append((lo, hi))
        else:
            clusters.append([[c], [(lo, hi)]])
    out = []
    for cs, intervals in clusters:
        c = sum(cs) / len(cs)
        for lo, hi in _merge_intervals(intervals, gap_tol=0.05):
            out.append((c, lo, hi))
    return out


def pair_wall_faces(wall_pts, p):
    """把 2 点墙皮线配成「真实厚度」墙矩形（双线墙的两皮），返回 (rects, singles)。

    CAD 双线墙 = 两条平行线（两皮），两线间距 = 真实墙厚（C006 实测 240/270/120/60mm，
    楼梯间剪力墙 350/380mm）。C006 每皮还被画成多段共线/重复 LINE，先 _merge_collinear
    合并成极大段，再配对（配对判据：同向 + 中心距 ∈ [wall_min, wall_max] + 投影重叠 >0.3m）。
    配对 → 4 点矩形（两皮实际端点围成的 bbox，厚度 = 真实间距）。
    单线（无平行近邻：门垛 / 短段 / 女儿墙）→ singles，不冒充有厚度的墙。
    这是「以实际线条建模」的核心：墙厚读出来，不是 buffer 猜出来。
    """
    hsegs, vsegs = [], []
    for pts in wall_pts:
        if len(pts) != 2:
            continue
        (x0, y0), (x1, y1) = pts
        if abs(x1 - x0) >= abs(y1 - y0):
            lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
            hsegs.append((y0, lo, hi))   # (center_y, lo_x, hi_x)
        else:
            lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
            vsegs.append((x0, lo, hi))   # (center_x, lo_y, hi_y)

    def _pair(segs, horiz):
        segs = sorted(segs, key=lambda s: s[0])
        used = [False] * len(segs)
        rects, singles = [], []
        for i in range(len(segs)):
            if used[i]:
                continue
            c1, lo1, hi1 = segs[i]
            best = None
            j = i + 1
            while j < len(segs) and segs[j][0] - c1 <= p.wall_max:
                if not used[j]:
                    c2, lo2, hi2 = segs[j]
                    d = abs(c2 - c1)
                    overlap = min(hi1, hi2) - max(lo1, lo2)
                    if p.wall_min <= d <= p.wall_max and overlap > 0.3:
                        if best is None or d < best[0]:
                            best = (d, j)
                j += 1
            if best is not None:
                _, j = best
                used[i] = used[j] = True
                c2, lo2, hi2 = segs[j]
                t = abs(c2 - c1)   # 真实墙厚（两皮间距）
                if horiz:
                    # 长度方向取两皮实际端点的最大跨度 [min(lo), max(hi)]，厚度取 [min(c), max(c)]
                    rects.append((box(min(lo1, lo2), min(c1, c2), max(hi1, hi2), max(c1, c2)), t))
                else:
                    rects.append((box(min(c1, c2), min(lo1, lo2), max(c1, c2), max(hi1, hi2)), t))
            else:
                used[i] = True
                if horiz:
                    singles.append([(lo1, c1), (hi1, c1)])
                else:
                    singles.append([(c1, lo1), (c1, hi1)])
        return rects, singles

    r1, s1 = _pair(_merge_collinear(hsegs), horiz=True)
    r2, s2 = _pair(_merge_collinear(vsegs), horiz=False)
    rects = r1 + r2
    allowed = getattr(p, "wall_thicknesses", None)
    if allowed:
        # 误配对 artifact：两皮来自不同墙，间距落在真实墙厚之间（如 300/340/360mm）。
        # snap 到最近真实墙厚 + recenter（中心线不变只改厚度），消除「有的墙很厚」。
        snapped = []
        for rect, t in rects:
            tt = _snap_thickness(t, allowed)
            snapped.append((recenter_rect(rect, tt), tt))
        rects = snapped
    return rects, s1 + s2


def derive_line_walls_and_outline(wall_pts, p):
    """line 约定（C006）：双线配对 → 真实厚度墙矩形 → union 外环 = 轮廓。

    不用凸包 / 2m 闭运算 / max(area) 硬凑：
      - 轮廓 = 实际墙线围成的闭合外边界（union 外环）。
      - 门洞缺口（外墙门）用小尺度闭合（outline_close_r，约门宽 0.6~0.8m）平滑楼板，
        不 2m 桥接、不填庭院。
      - 碎片化时不静默丢翼：保留 >= 主楼 2% 面积的分量。
    返回 (outline, wall_geoms)，wall_geoms = 配对墙矩形 + 单线薄墙。
    """
    # 「>=4 点闭合折线」= 图上直接画好的实心墙(如曲墙环形带, 由 classify_line.pair_arc_bands
    # 生成)：不再拆成弦段去配对 —— 弧带的内外皮是弧, 拆成短弦后贪心配对会把一堵 240mm 墙
    # 拆成 240/100 混厚(实测 c006 52块+30条单线)。直接当实心墙采纳。
    solid, lined = [], []
    for pts in wall_pts:
        closed = (len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) <= 1e-6
                  and abs(pts[0][1] - pts[-1][1]) <= 1e-6)
        (solid if closed else lined).append(pts)
    rects, singles = pair_wall_faces(lined, p)
    st = getattr(p, "single_wall_t", 0.10)
    wall_geoms = [poly for poly, _ in rects]
    wall_ts = [t for _, t in rects]
    wall_geoms += [LineString(pts).buffer(st / 2) for pts in singles]
    wall_ts += [st] * len(singles)
    for pts in solid:
        try:
            P = Polygon(pts)
        except Exception:
            continue
        if not P.is_valid:
            P = P.buffer(0)
        if P.is_empty or P.area <= 1e-6:
            continue
        wall_geoms.append(P)
        # 厚度 = 等效厚度 2*面积/周长(环带 = 真实墙厚)
        wall_ts.append(round(2.0 * P.area / P.length, 3) if P.length else st)
    if not wall_geoms:
        return Polygon(), [], []

    region = unary_union(wall_geoms)
    close_r = getattr(p, "outline_close_r", 0.0)
    if close_r > 0:
        region = region.buffer(close_r).buffer(-close_r)
    if region.geom_type == "MultiPolygon":
        comps = sorted(region.geoms, key=lambda g: g.area, reverse=True)
        kept = [g for g in comps if g.area >= comps[0].area * 0.02]
        region = unary_union(kept)
    if region.geom_type == "MultiPolygon":
        region = max(region.geoms, key=lambda g: g.area)

    outline = Polygon(region.exterior)
    if not outline.is_valid:
        outline = outline.buffer(0)
    outline = outline.simplify(0.2)
    return outline, wall_geoms, wall_ts


def _flatten_wall_segments(wall_pts):
    """把任意墙折线（2/3/4/8 点）拆成轴对齐 2 点直段（每个相邻点对 = 一段墙皮）。

    理化楼墙全是「双线墙」：外皮是 8 点连续折线、内皮是 2 点断线、凹槽是 4 点 U 形、
    转角是 3 点 L 形。旧逻辑只给 2 点线配对，多段线墙皮漏配（外皮被当单线 0.30m buffer、
    内皮落成 0.10m 假墙、凹槽双皮各 buffer 0.15 加厚到 0.60m）。统一拆成直段再配对，
    对齐 build_lihua_full.py 原始逻辑。斜线段跳过。
    """
    segs = []
    for pts in wall_pts:
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            if math.hypot(bx - ax, by - ay) < 1e-6:
                continue
            if min(abs(bx - ax), abs(by - ay)) > 0.02:
                continue
            segs.append(((float(ax), float(ay)), (float(bx), float(by))))
    return segs


def _detect_outer_skin(wall_pts):
    """识别外墙「周边折线对」：非闭合折线两两闭合成环，取闭合面积最大（= 楼板足迹）那对。

    理化楼外墙 = 两条「周边折线」（单线外皮，无内皮厚度信息），合起来是完整楼板周长，
    首尾不闭合、左右半在 cx 处衔接。低层是 8 点（含翼楼）、顶层是 4 点塔楼——wall_x_clip
    把 8 点翼楼折线裁成 4 点后与塔楼自身的 4 点外皮并存，旧 len>=8 阈值在顶层失效，把 4 点
    外皮当内墙配对，顶层东/西外墙碎成 0.12m 假条 + 0.24m 断片。这里按几何语义「两半折线
    闭合成楼板周长」识别，对点数不敏感。

    返回 (outer_poly, outer_idx)：outer_poly 是闭合环 Polygon（未内缩），outer_idx 是参与
    成环的折线下标集合（调用方据此从内墙配对里剔除，避免外皮再被当内墙）。无外皮返回
    (None, frozenset())。
    """
    cands = []
    for i, pts in enumerate(wall_pts):
        if len(pts) < 3:
            continue
        if abs(pts[0][0] - pts[-1][0]) > 1e-6 or abs(pts[0][1] - pts[-1][1]) > 1e-6:
            cands.append((i, pts))
    if len(cands) < 2:
        return None, frozenset()

    def _pt_close(u, v, tol=0.05):
        return abs(u[0] - v[0]) <= tol and abs(u[1] - v[1]) <= tol

    def _close(pa, pb):
        """两半折线闭合成环；端点对不上（不是一对半周长）返回 None。"""
        af, al = pa[0], pa[-1]
        bf, bl = pb[0], pb[-1]
        if _pt_close(af, bf) and _pt_close(al, bl):
            return list(pa) + list(reversed(pb))[1:]
        if _pt_close(af, bl) and _pt_close(al, bf):
            return list(pa) + list(pb)[1:]
        return None

    best = None  # (area, poly, idx_set)
    for a in range(len(cands)):
        ia, pa = cands[a]
        for b in range(a + 1, len(cands)):
            ib, pb = cands[b]
            for closed in (_close(pa, pb), _close(pb, pa)):
                if closed is None:
                    continue
                try:
                    poly = Polygon(closed)
                    if not poly.is_valid:
                        poly = poly.buffer(0)
                except Exception:
                    continue
                if poly.is_empty or poly.geom_type != "Polygon":
                    continue
                if best is None or poly.area > best[0]:
                    best = (poly.area, poly, frozenset((ia, ib)))
    if best is None:
        return None, frozenset()
    return best[1], best[2]


def _stair_tread_indices(wall_pts):
    """识别楼梯踏步折线（2 点水平短段 0.8~3.0m，同 y 密集聚成 >=4 段）的下标。

    踏步线不是墙（楼梯踏步的画法），配对时会与相邻踏步（间距 0.3m 落在 wall_min~wall_max
    内）误配成 0.3m 假墙，把楼梯井塞满（「楼梯间墙体不对」根因）。按 detect_stairwells 同款
    聚类：y 差 <=0.35 且 x 中心差 <=3.0 的短水平段 merge，聚成 >=4 段即一跑踏步。
    """
    cands = []  # (cy, cx, idx)
    for i, pts in enumerate(wall_pts):
        if len(pts) != 2:
            continue
        (x0, y0), (x1, y1) = pts
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 0.05:
            continue
        if min(abs(dx), abs(dy)) > 0.02:
            continue
        if abs(dx) >= abs(dy) and 0.8 <= L <= 3.0:
            cands.append(((y0 + y1) / 2, (x0 + x1) / 2, i))
    n = len(cands)
    parent = list(range(n))

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _merge(x, y):
        rx, ry = _find(x), _find(y)
        if rx != ry:
            parent[rx] = ry

    for a in range(n):
        cya, cxa, _ = cands[a]
        for b in range(a + 1, n):
            cyb, cxb, _ = cands[b]
            if abs(cya - cyb) <= 0.35 and abs(cxa - cxb) <= 3.0:
                _merge(a, b)
    groups = {}
    for i in range(n):
        groups.setdefault(_find(i), []).append(cands[i][2])
    return frozenset(i for g in groups.values() if len(g) >= 4 for i in g)


def _stair_midline_indices(wall_pts, tread_idx):
    """识别踏步端点连线（对称三线中间竖线）的下标。

    双跑/双分楼梯中缝墙画成「左皮 + 踏步中点线 + 右皮」三条竖线（间距各 ~0.1m），中间那条
    是踏步端点连线（非墙）。若不剔除，左右皮各自贪心配到中间线，读出 0.1m 假墙（snap 0.12m）
    而非 0.2m 中缝墙。判据：竖线两侧 ~0.1m 对称各有一条平行竖线（重叠 >0.3m）。返回中间线
    下标 frozenset。
    """
    vlines = []  # (cx, ylo, yhi, idx)
    for i, pts in enumerate(wall_pts):
        if i in tread_idx or len(pts) != 2:
            continue
        (x0, y0), (x1, y1) = pts
        dx, dy = x1 - x0, y1 - y0
        if min(abs(dx), abs(dy)) > 0.02:
            continue
        if abs(dy) < abs(dx):
            continue
        vlines.append((round((x0 + x1) / 2, 3), min(y0, y1), max(y0, y1), i))
    mid = set()
    for cx, ylo, yhi, i in vlines:
        left = right = None
        for cx2, ylo2, yhi2, j in vlines:
            if j == i:
                continue
            d = cx2 - cx
            if abs(d) < 0.02:
                continue
            if min(yhi, yhi2) - max(ylo, ylo2) <= 0.3:
                continue
            if 0.06 <= abs(d) <= 0.14:
                if d < 0:
                    left = d
                else:
                    right = d
        if left is not None and right is not None and abs(left + right) < 0.02:
            mid.add(i)
    return frozenset(mid)


def _derive_paired_walls_and_outline(wall_pts, p, is_top=False):
    """理化楼（door_by_points）墙推导：对齐 build_lihua_full.py「墙皮配对 → 真矩形」。

    原始 builder 核心：所有墙折线拆成直段 → 每段独立找最近平行邻段配对（wall_min~wall_max、
    重叠>0.3m），不标记 used（多对一）。这样连续外皮能和每一段断开的内皮都配对，union 后成
    完整墙；无配对的单段 buffer wall_fallback 成单线墙。墙厚从图上两条平行皮间距读出来
    （0.24 内墙 / 0.30 外墙），不是 buffer 猜出来。
    返回 (outline, wall_geoms, wall_ts)，wall_ts 供 extract_floor 按真实墙厚分外墙/内墙。
    """
    # 外墙 = 图上两条「周边折线」（单线外皮，无内皮厚度信息，合起来是完整楼板周长，
    # 首尾不闭合、左右半在 cx 处衔接）。门垛实测墙厚 240mm → 外墙 = 外皮往建筑内侧单向
    # buffer outer_wall_t 成实体墙。若把它拆段和内墙皮线配对，会读出 0.175m 假墙厚（外皮
    # y=24265 配到内墙皮 y=24440）；再 recenter 按「外皮+内墙皮中点」当墙中线，把外墙往外
    # 偏 32.5mm → 外墙被 facade_bnd 误分类成内墙、门洞挖不到外墙（「门缺失/墙像单线」根因）。
    #
    # 周边折线低层是 8 点（含翼楼）、顶层是 4 点塔楼（wall_x_clip 把 8 点翼楼折线裁成 4 点，
    # 与塔楼自身的 4 点外皮并存）——旧 len>=8 阈值在顶层失效，把 4 点外皮当内墙配对，顶层
    # 东/西外墙碎成 0.12m 假条 + 0.24m 断片（「5层外墙 #4/#5 不要」根因）。改用几何语义：
    # 非闭合折线两两闭合成环，取闭合面积最大（= 楼板足迹）的那对当外皮。
    outer_poly, outer_idx = _detect_outer_skin(wall_pts)
    # 楼梯踏步线（水平短段）与踏步端点连线（对称三线中间竖线）不是墙，剔除后再配对，
    # 否则会配出 0.3m/0.1m 假墙塞满楼梯井（「楼梯间墙体不对」根因）。
    tread_idx = _stair_tread_indices(wall_pts)
    mid_idx = _stair_midline_indices(wall_pts, tread_idx)
    inner_polys = [pts for i, pts in enumerate(wall_pts)
                   if i not in outer_idx and i not in tread_idx and i not in mid_idx]

    wall_geoms, wall_ts = [], []
    wf = p.wall_fallback
    outer_t = getattr(p, "outer_wall_t", 0.24)

    # —— 外墙：周边折线（左右半）拼接成闭合外皮环，外墙 = 外皮 − 内缩 ——
    if outer_poly is not None:
        # 外墙环带 = 外皮多边形 − 外皮内缩 outer_t（转角自动闭合，无 0.24×0.24 漏缝）
        ring = outer_poly.difference(outer_poly.buffer(-outer_t, join_style=2))
        if not ring.is_empty:
            wall_geoms.append(ring)
            wall_ts.append(outer_t)

    # —— 内墙：2/3/4 点折线拆段后双皮配对读真实墙厚，无配对单段 buffer 兜底 ——
    # 外墙在图上画成「8 点外皮 + 2 点内皮」，内皮线距轮廓 = outer_t（外皮-内皮真实墙厚）。
    # 这些内皮线是外墙的内侧面，已被上面的外墙环带覆盖；若不剔除，会被 buffer 成 0.30 假墙
    # 与外环重叠 → 门洞只挖到外环、假墙把门洞从里侧封死（正视图实墙/门扇不见的根因）。
    hsegs, vsegs = [], []
    outer_ext = outer_poly.exterior if outer_poly is not None else None
    for (ax, ay), (bx, by) in _flatten_wall_segments(inner_polys):
        if outer_ext is not None:
            seg = LineString([(ax, ay), (bx, by)])
            # 只剔除「中点贴外皮」的段——内皮线平行于外皮、整段距外皮≈outer_t（浮点下
            # 0.2399/0.2401），+0.02 容差。不能用 seg.distance(outer_ext)（段到外皮的
            # 最小距离）：垂直隔墙一端顶在外皮上、最小距离为 0，会被误当成内皮线整条
            # 剔掉 → 每层内墙少一半以上（「墙面修少了、每层都少」根因）。改用段中点距
            # 外皮：内皮线中点仍在 0.24m 处被剔，垂直隔墙中点已深入房间（>outer_t）保留。
            if seg.centroid.distance(outer_ext) <= outer_t + 0.02:
                continue   # 外墙内皮线，已被外墙环带覆盖
            # 仅顶层（有翼楼屋面）才剔除「塔楼足迹外」的段：顶层外皮=塔楼，外皮外=翼楼
            # 南侧外臂（女儿墙层，不当塔楼墙）。低层外皮是简化的「周边折线」足迹（漏东侧凸台），
            # 段中点同样在外皮外，同判据会误删低层合法外墙 → 只用 is_top 闸住。
            if is_top and outer_poly is not None and not outer_poly.contains(seg.centroid):
                continue
        if abs(bx - ax) >= abs(by - ay):
            lo, hi = (ax, bx) if ax <= bx else (bx, ax)
            hsegs.append((ay, lo, hi))   # (center_y, lo_x, hi_x)
        else:
            lo, hi = (ay, by) if ay <= by else (by, ay)
            vsegs.append((ax, lo, hi))   # (center_x, lo_y, hi_y)

    allowed = getattr(p, "wall_thicknesses", None)

    def _pair(segs, horiz):
        for (c1, lo1, hi1) in segs:
            best_d, best_c = None, None
            for (c2, lo2, hi2) in segs:
                d = abs(c1 - c2)
                if not (p.wall_min <= d <= p.wall_max):
                    continue
                if min(hi1, hi2) - max(lo1, lo2) < 0.3:
                    continue
                if best_d is None or d < best_d:
                    best_d, best_c = d, c2
            if best_d is not None:
                # 墙厚 = 两皮真实间距，矩形跨两皮实际位置（非居中 buffer）。
                if horiz:
                    g = box(lo1, min(c1, best_c), hi1, max(c1, best_c))
                else:
                    g = box(min(c1, best_c), lo1, max(c1, best_c), hi1)
                t = best_d
            else:
                if horiz:
                    g = box(lo1, c1 - wf, hi1, c1 + wf)
                else:
                    g = box(c1 - wf, lo1, c1 + wf, hi1)
                t = wf * 2
            # 双皮配对中心线 = 真实墙中线，recenter 只改厚度不移位，安全；snap 消 0.23/0.175 假厚。
            if allowed:
                t = _snap_thickness(t, allowed)
                g = recenter_rect(g, t)
            wall_ts.append(t)
            wall_geoms.append(g)

    _pair(hsegs, True)
    _pair(vsegs, False)

    if not wall_geoms:
        return Polygon(), [], []
    region = unary_union(wall_geoms)
    close_r = getattr(p, "outline_close_r", 0.0)
    if close_r > 0:
        region = region.buffer(close_r).buffer(-close_r)
    if region.geom_type == "MultiPolygon":
        region = max(region.geoms, key=lambda g: g.area)
    outline = Polygon(region.exterior)
    if not outline.is_valid:
        outline = outline.buffer(0)
    outline = outline.simplify(0.2)
    if not outline.is_valid:
        outline = outline.buffer(0)
    return outline, wall_geoms, wall_ts


def derive_walls_and_outline(wall_pts, p, is_top=False):
    """统一墙几何：2 点=墙皮线（双线墙的一面，buffer 半墙厚成实体墙）、
    3+ 点=已填充墙矩形，全部 union 后取外环填实为楼板轮廓。

    这是「读图成图」的唯一主路径，消除两个脆弱假设：
      - 轴对齐（pair_rects 假设墙横平竖直，斜墙/旋转墙直接丢）；
      - 双线配对（单线墙无配对 → 被误判女儿墙 → 轮廓塌成碎块）。
    union 对旋转、单线、双线、LINE 约定全兼容。返回 (outline, wall_geoms)。

    关键区分（c104/c009/c114 等楼）：
      墙是「薄」的（厚 0.08~0.35m，面积/周长 ≈ 半厚 ≈ 0.04~0.18m）；
      楼板/地坪/剖面填充是「厚」的（面积/周长 > 1m，常 100~3900㎡）。
      填充区不是墙，混进墙 union 会把轮廓撑成整片楼板 + 把真墙拆碎。
      填充区若存在，其外环就是权威楼板足迹 → 直接当 outline。

      门符号 = 3+ 点「不闭合」折线（leaf + swing arc，跨度 < 3m）。shapely Polygon()
      会把不闭合折线强行闭合成一个扇形面，混进 union 会把门洞桥接成假墙、把轮廓撑大
      （c041/c022 的 outline 729~1000㎡ 而真墙只有 70~370m 的根因）。
      但「跨度 >= 3m 的不闭合折线」是带门洞缺口的墙折线（c041 常见，最长 45.7m），
      按线 buffer 成墙带，不能当门符号丢弃。
    """
    if getattr(p, "classifier", "lwpolyline") == "line":
        return derive_line_walls_and_outline(wall_pts, p)
    # 理化楼（door_by_points）：墙 = 2 点「双皮线」+ 3+ 点「单线墙」。
    # 双皮线必须配对读真实墙厚（0.24/0.30），不能各 buffer 0.15（会把 0.30 外墙撑成 0.60、
    # 0.24 内墙撑成 0.54，且外墙皮向外多伸半厚）。对齐 SU「双线墙直接成面」。
    if getattr(p, "door_by_points", False):
        return _derive_paired_walls_and_outline(wall_pts, p, is_top)
    wall_geoms = []
    slab_geoms = []
    for pts in wall_pts:
        n = len(pts)
        if n == 2:
            g = LineString(pts).buffer(p.wall_fallback)   # 半墙厚 ~0.15m
        elif n >= 3:
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            span = max(max(xs) - min(xs), max(ys) - min(ys))
            closed = abs(pts[0][0] - pts[-1][0]) <= 1e-6 and abs(pts[0][1] - pts[-1][1]) <= 1e-6
            if not closed:
                # 不闭合折线：小跨度(<3m)=门符号跳过；大跨度=带门洞缺口的墙折线 → 按线 buffer
                if span < DOOR_SPAN_MAX:
                    continue
                g = LineString(pts).buffer(p.wall_fallback)
            else:
                try:
                    g = Polygon(pts)
                    if not g.is_valid:
                        # 自交/退化环（c104 裙楼 3959㎡ 楼板、多栋楼外墙环）→ buffer(0) 清洗成有效面，
                        # 否则整片被丢弃（当无效 → None），轮廓塌掉、墙漏画。
                        g = g.buffer(0)
                    if not (g.is_valid and g.area > 0.001):
                        g = None
                    elif g.area / g.length > SLAB_RATIO:
                        slab_geoms.append(g)   # 大块填充 → 当楼板足迹，不当墙
                        g = None
                    else:
                        g = g.buffer(0.05)   # 桥接双线墙两皮之间的缝隙
                except Exception:
                    g = None
        else:
            continue
        if g is not None and not g.is_empty and g.area > 0.001:
            wall_geoms.append(g)

    # 轮廓来源：填充区外环 vs 墙 union 外环，取「较大」者。
    #   大块填充区（area/length>1）常是楼板足迹（c009/c114，100~3900㎡），此时填充区比
    #   碎内墙大得多 → 用填充区。
    #   但 c104 这类裙楼+塔楼：塔楼每层画「填充楼板」（155㎡）当底，裙楼主体反而用墙画
    #   （358㎡ 墙 union 成 1171㎡ 足迹）。此时填充区（塔楼 155㎡）比墙 union 小得多，
    #   盲目用填充区会把轮廓塌成塔楼 → 应取较大者（裙楼墙 union）。
    def _biggest_outline(geoms, close_r=0.0):
        if not geoms:
            return None
        region = unary_union(geoms)
        # 闭运算桥接墙带缺口（c006 LINE 墙角点/门洞把墙带断开成几十段不相连的碎带，
        # union 后仍是 MultiPolygon，max(area) 只留最大一翼 → 足迹塌成 314㎡）。
        # close_r>0 时先 buffer 桥接再回缩，碎带连成封闭足迹，再取 exterior。
        if close_r > 0:
            region = region.buffer(close_r).buffer(-close_r)
        if region.geom_type == "MultiPolygon":
            region = max(region.geoms, key=lambda g: g.area)
        o = Polygon(region.exterior)
        return o if not o.is_empty else None

    slab_outline = _biggest_outline(slab_geoms)
    wall_outline = _biggest_outline(wall_geoms, close_r=p.outline_close_r)
    if slab_outline is not None and (wall_outline is None or slab_outline.area >= wall_outline.area):
        outline = slab_outline
    elif wall_outline is not None:
        outline = wall_outline
    else:
        return Polygon(), [], []

    if not outline.is_valid:
        outline = outline.buffer(0)      # 凹/自交外环 → 清洗成有效多边形
    # 磨掉 union 产生的亚米级锯齿：真实建筑轮廓只有几十个角，2800 顶点的"锯齿"是噪声。
    # 简化后三角面数下降 10~30 倍（否则外墙带 buffer 圆角会把每个顶点扩成圆弧 → 百万面）。
    outline = outline.simplify(0.2)
    if not outline.is_valid:
        outline = outline.buffer(0)
    return outline, wall_geoms, None


LEAF_TOL = 1e-6          # 门扇长判据的浮点容差(m)，抵消大坐标转米后的相减误差


def _hinge_leaf(pts, tol=0.02, eq=0.05):
    """折线里的「门扇铰对」长度(m)：两条轴对齐、等长(相对差 <= eq)、互相垂直、
    共享一个端点的段。返回 0 表示不存在。

    为什么是它：门符号 = 「闭位门扇 + 开位门扇」两条等长垂直段绕铰点张开，各家画法
    (点数 3~17、有无门垛、有无摆动弧)都不同，只有这个结构不变 ——
    c019 2×1100、c034/c054 2×750、c006 系 2×900、c044 2×700，实测全中。
    """
    n = len(pts)
    segs = []
    for i in range(n - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        if min(abs(dx), abs(dy)) > tol:
            continue
        L = (dx * dx + dy * dy) ** 0.5
        # 长度上下界必须带浮点容差：图纸坐标是 mm 级大数(如 1294605)，除 1000 转米后相减会丢
        # 有效位 —— c041 的 600mm 扇线算成 0.5999999999999978，卡在 DOOR_LEAF_MIN 下界外被整条
        # 丢掉（实测同一形状 152 个里 135 个判否、17 个判是，就是这个）。
        if L < DOOR_LEAF_MIN - LEAF_TOL or L >= DOOR_LEAF_MAX + LEAF_TOL:
            continue
        segs.append((L, abs(dx) >= abs(dy), pts[i], pts[i + 1]))
    best = 0.0
    for a in range(len(segs)):
        L1, h1, p1, q1 = segs[a]
        for b in range(a + 1, len(segs)):
            L2, h2, p2, q2 = segs[b]
            if h1 == h2 or abs(L1 - L2) > eq * L1:
                continue
            if not any(abs(u[0] - v[0]) <= tol and abs(u[1] - v[1]) <= tol
                       for u in (p1, q1) for v in (p2, q2)):
                continue
            if L1 > best:
                best = L1
    return best


def detect_doors(wall_pts, outline, p):
    """从墙折线里识别门：折线含「门扇铰对」(见 _hinge_leaf)，门宽 = 铰对长度。

    历史口径「不闭合 + 最长段 ∈ [0.6,3.0)」有两个致命误判(2026-09-10 实测 c019/c044)：
      1) **墙垛/墙段被当门** —— 4 点轴对齐闭合矩形(如 1480×240、630×120，只是没设 closed
         标志也没复制首点)的最长段就是它的长边 → 被当成 1.48m/0.63m 的「门」，而它的
         顶点质心正落在墙里 = 用户报的「门夹在墙里看不到」。c019 首层 87 个门里 86 个是它。
      2) **窗户被当门** —— 窗 = 240mm 厚 × 开口宽的细长矩形 + 玻璃/窗扇线，最长段同样是
         开口宽 → 「把窗户识别成门」。
    另外闭合回边(对角引线)常比门扇线还长(c034 是 1134 vs 真扇 750)，取「最长段」还会把
    门宽算大 50%。

    改用结构判据后：墙垛/窗没有「等长垂直且共享铰点」的两条扇线，天然排除；闭合引线即使
    更长也不参与(只取轴对齐段并两两配对)；门宽直接 = 扇线长(c034 由 1.13/1.34 回到 0.75/0.90)。
    返回 [{x, y, w, horiz}]（本地米坐标，x/y = 顶点质心，沿用旧口径）。
    """
    doors = []
    for pts in wall_pts:
        n = len(pts)
        if n < 3:
            continue
        closed = abs(pts[0][0] - pts[-1][0]) <= 1e-6 and abs(pts[0][1] - pts[-1][1]) <= 1e-6
        if closed:
            continue
        leaf = _hinge_leaf(pts)
        if leaf <= 0.0:
            continue
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        doors.append({
            "x": round(sum(xs) / n, 3),
            "y": round(sum(ys) / n, 3),
            "w": round(min(leaf, p.door_w_double), 3),   # 门宽夹到双门上限，避免异常大扇
            "horiz": (max(xs) - min(xs)) >= (max(ys) - min(ys)),
        })
    return doors


def derive_outline(hsegs, vsegs, p):
    """根据墙体位置推导本层楼板轮廓（不依赖手工 outline 文件）。

    思路：
      1) 全高墙 = 有平行近邻（双线）的墙段；女儿墙 = 无平行近邻的单线墙。
      2) 全高墙中心线缓冲成墙带并 union → 外墙成闭合环。
      3) 取最大连通块外环填实 → 连续楼板；再开运算磨掉翼楼残支。
    兜底：斜墙楼（垂直墙斜、水平墙轴对齐）只剩单方向段时，缓冲会被 open 磨成空，
    改用全部墙段端点的凸包出轮廓，避免 outline 为空 → floor JSON 空 → 崩溃。
    """
    all_pts = []
    for c1, lo1, hi1 in hsegs:
        all_pts += [(lo1, c1), (hi1, c1)]
    for c1, lo1, hi1 in vsegs:
        all_pts += [(c1, lo1), (c1, hi1)]
    if not all_pts:
        return Polygon()
    hull = MultiPoint(all_pts).convex_hull

    full_lines = []
    for c1, lo1, hi1 in hsegs:
        nd = nearest_parallel(c1, lo1, hi1, hsegs)
        if nd is not None and nd <= p.wall_max:
            full_lines.append(LineString([(lo1, c1), (hi1, c1)]))
    for c1, lo1, hi1 in vsegs:
        nd = nearest_parallel(c1, lo1, hi1, vsegs)
        if nd is not None and nd <= p.wall_max:
            full_lines.append(LineString([(c1, lo1), (c1, hi1)]))
    if not full_lines:
        return hull.simplify(0.3) if hull.geom_type == "Polygon" else Polygon()

    band = unary_union([ln.buffer(p.outline_buf) for ln in full_lines])
    comps = band.geoms if band.geom_type == "MultiPolygon" else [band]
    filled = Polygon(max(comps, key=lambda g: g.area).exterior)
    opened = filled.buffer(-p.open_r).buffer(p.open_r)
    if opened.geom_type == "MultiPolygon":
        opened = max(opened.geoms, key=lambda g: g.area)
    opened = opened.simplify(0.3)
    # 开运算磨成空 / 薄条带（斜墙楼只有单方向段）→ 凸包兜底
    if opened.is_empty or opened.area < 1.0 or opened.area < hull.area * 0.3:
        return hull.simplify(0.3) if hull.geom_type == "Polygon" else Polygon()
    return opened


def detect_stairwells(F, walls, p):
    """楼梯井检测：一列短水平段（踏步）聚类成跑，>=4 段算楼梯。返回包围盒列表。"""
    cands = []
    for pts in walls:
        cx = sum(pt[0] for pt in pts) / len(pts)
        if not any(abs(floor_of(p, cx, y) - F) < 0.5 for y in [pt[1] for pt in pts]):
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        for i in range(len(local) - 1):
            a, b = local[i], local[i + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L < 0.05 or min(abs(dx), abs(dy)) > 0.02:
                continue
            if abs(dx) >= abs(dy) and 0.8 <= L <= 3.0:
                x0, x1 = min(a[0], b[0]), max(a[0], b[0])
                cands.append(((x0 + x1) / 2, a[1], x0, x1))

    n = len(cands)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def merge(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        cxi, cyi, _, _ = cands[i]
        for j in range(i + 1, n):
            cxj, cyj, _, _ = cands[j]
            if abs(cyi - cyj) <= 0.35 and abs(cxi - cxj) <= 3.0:
                merge(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cands[i])

    out = []
    for g in groups.values():
        if len(g) < 4:
            continue
        xs = [c[2] for c in g] + [c[3] for c in g]
        ys = [c[1] for c in g]
        # 假阳性过滤：真楼梯井「踏步纵向跨度」>=1.5m（单跑 11 级×0.27m≈3m）。
        # 深<1.5m 的浅薄带(0~1.2m)是「⊓」踏步符号的几段平行线/栏杆/立面线，不是楼梯井
        # (c114 每层 28~30 个假井、c103/c022/c104/c009/c027 均 36~146 个假井，会把楼板挖满洞)。
        if max(ys) - min(ys) < 1.5:
            continue
        # 一井内按 x 聚成 flight 列（踏步列），跑数决定楼梯类型：
        #   1 列=直跑，2 列=双跑平行，>=3 列=双分式（中宽两侧窄）
        flights = cluster_flights(g)
        nf = len(flights)
        stype = "straight" if nf == 1 else ("double" if nf == 2 else "bifurcated")
        out.append({
            "x0": round(min(xs), 3), "x1": round(max(xs), 3),
            "yBot": round(min(ys), 3), "yTop": round(max(ys), 3),
            "steps": len(set(round(c[1], 2) for c in g)),
            "type": stype,
            "flights": flights,
        })
    return out


def cluster_flights(cands):
    """把一井内的踏步按 x（cx）聚成 flight 列，返回 [{x0, x1}]（按 x 升序）。

    同一列的所有踏步 x0/x1 相同，取 min(x0)/max(x1) 得该跑的跨度。
    """
    cols = []
    for cx, cy, x0, x1 in cands:
        for col in cols:
            if abs(col["cx"] - cx) <= 0.3:
                col["x0"] = min(col["x0"], x0)
                col["x1"] = max(col["x1"], x1)
                break
        else:
            cols.append({"cx": cx, "x0": x0, "x1": x1})
    cols.sort(key=lambda c: (c["x0"] + c["x1"]) / 2)
    return [{"x0": round(c["x0"], 3), "x1": round(c["x1"], 3)} for c in cols]
