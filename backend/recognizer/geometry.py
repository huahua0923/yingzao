# -*- coding: utf-8 -*-
"""通用几何算法：墙皮配对 / 楼板轮廓推导 / 楼梯井检测。

这些函数不知道具体是哪栋楼，只接收 profile 里的参数，是「逐模块改算法」的主战场。
"""
import math
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import unary_union, polygonize

from .profile import to_local, floor_of
from .component_library import SLAB_RATIO, DOOR_LEAF_MIN, DOOR_LEAF_MAX, DOOR_SPAN_MAX
from . import outline as OUT


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


# 踏步线簇判据参数（米）：相邻线间距落在踏面档、整簇间距均匀、至少 3 条。
TREAD_GAP_LO, TREAD_GAP_HI = 0.15, 0.50
TREAD_GAP_TOL, TREAD_MIN_RUN, TREAD_MIN_OVERLAP = 0.06, 3, 0.5


def split_2pt(wall_pts):
    """把点列摊平成 2 点线段（多段线逐段拆开）。pair_wall_faces 内部本就这么拆，
    这里提前摊平是为了能**按段**剔踏步线 —— 一段的外皮折线里往往混着真墙与外台阶。"""
    segs = []
    for pts in wall_pts:
        if len(pts) < 2:
            continue
        if len(pts) == 2:
            segs.append([tuple(pts[0]), tuple(pts[1])])
        else:
            segs.extend([[tuple(pts[k]), tuple(pts[k + 1])] for k in range(len(pts) - 1)])
    return segs


def _axis_groups(segs):
    """把线段按走向分成 (horizontal, vertical) 两组，各条为 (跨向坐标, 走向 lo, 走向 hi, 下标)。

    斜段（两个方向都显著）不参与 —— 斜踏步另有判据，不在这里猜。
    """
    h, v = [], []
    for i, (a, b) in enumerate(segs):
        (x0, y0), (x1, y1) = a, b
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        if dx < 1e-9 and dy < 1e-9:
            continue
        if min(dx, dy) > 0.25 and min(dx, dy) > 0.3 * max(dx, dy):
            continue
        if dx >= dy:
            h.append((y0, min(x0, x1), max(x0, x1), i))
        else:
            v.append((x0, min(y0, y1), max(y0, y1), i))
    return h, v


def _parallel_clusters(group):
    """同走向线段的**平行紧邻**连通簇：两条线「跨向间距 ∈ [0.15, 0.50]m 且走向重叠 >50%」
    即相连；返回连通分量（各自按跨向坐标升序）。

    用连通分量而不是「相邻逐条推进」：图上踏步区间常混进别的同向线（c006 F0 的室外台阶
    两边就夹着 57.73/57.97 两条相距 0.12m 的线），逐条推进会被它们打断，整簇检测不到
    —— 这一版是踩过这个坑改的。
    """
    n = len(group)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        ci, loi, hii, _ii = group[i]
        for j in range(i + 1, n):
            cj, loj, hij, _jj = group[j]
            d = abs(cj - ci)
            if d > TREAD_GAP_HI:
                continue
            if d < TREAD_GAP_LO:
                continue
            ov = min(hii, hij) - max(loi, loj)
            if ov > TREAD_MIN_OVERLAP * min(hii - loi, hij - loj):
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[ra] = rb
    buckets = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(group[i])
    return [sorted(v) for v in buckets.values()]


def _dedupe_cluster(cluster, tol=1e-3):
    """合并「同一条线画了两遍/画成两段」的重复项（跨向坐标相同）：走向取并集。

    不合并会让「等距」判据自己把自己判死：c006 F0 外侧那道台阶边线在同一 x 上放了两个实体，
    间距表变成 [0.35×6, 0.00] → 极差 0.35 > 容差 → 整簇判不出踏步（踩过这个坑）。
    """
    out = []
    for item in cluster:
        if out and abs(item[0] - out[-1][0]) <= tol:
            prev = out[-1]
            out[-1] = (prev[0], min(prev[1], item[1]), max(prev[2], item[2]), prev[3])
        else:
            out.append(item)
    return out


def _is_tread_cluster(cluster):
    """簇是不是踏步：≥3 个**不同位置** + 跨向间距均匀（极差 ≤ TREAD_GAP_TOL）。"""
    uniq = _dedupe_cluster(cluster)
    if len(uniq) < TREAD_MIN_RUN:
        return False
    gaps = [uniq[k + 1][0] - uniq[k][0] for k in range(len(uniq) - 1)]
    return max(gaps) - min(gaps) <= TREAD_GAP_TOL


def tread_face_indices(segs):
    """**踏步线**（楼梯/室外台阶）识别：同走向 + 平行紧邻 + **等距** + 彼此重叠的 ≥3 条线。

    为什么必须有这条判据：踏步线间距 0.27~0.35m 正好落在墙厚档里（本图 0.27/0.35 都是
    真实墙厚），双线配对会把**相邻两条踏步线配成一堵 0.35m 假墙**，再把整片台阶包进楼板轮廓。
    用户判例（2026-09-15）：「室外的就是室外台阶」（c006 F0 东西两侧各 7 步的室外大台阶，
    7 条线 ×0.35m 等距 → 被配成 6 堵 0.35 假墙 + 一圈假轮廓）。

    真墙只有**两条**线（两皮）；≥3 条**等距**且互相重叠的，只可能是踏步。三条保底，
    等距容差 0.06m 挡住「一堵墙旁边恰好贴着另一堵墙」这类非等距组合。
    返回要剔除的下标集合。
    """
    h, v = _axis_groups(segs)
    drop = set()
    for group in (h, v):
        for cluster in _parallel_clusters(group):
            if _is_tread_cluster(cluster):
                drop.update(item[3] for item in cluster)
    return drop


def tread_terraces(segs, wall_min=0.05, wall_max=0.42):
    """踏步簇 → **室外台阶/平台**的外接矩形（沿踏步走向 × 从最外侧踏步到邻近的平行墙线）。

    为什么必须是矩形而不是只剔踏步线：室外台阶是「台阶 + 平台 + 两侧挡墙」一整套，图上画成
    一个由真墙围合、内部排踏步线的方盒子（c006 F0 东西各一处：9.3m×14.2m，内含 7 步）。
    只剔踏步线的话，围合墙仍会把这一整块包进楼板轮廓（`Polygon(exterior)` 会把 U 形围合的
    里腔填实）—— 实测 F0 轮廓就从 5900 涨到 6488㎡、并在模型里多出一圈悬空挡墙。
    用户判例（2026-09-15）：「室外的就是室外台阶」。

    返回 [{horiz, along, across}]（本地米）：along = 踏步走向上的极值，across = (内侧, 外侧)，
    内侧取「与踏步平行、在踏步近侧、且沿走向与之重叠 ≥50% 的最近一条线」= 建筑外墙皮。
    """
    h, v = _axis_groups(segs)

    def _enclosed(perp, along_lo, along_hi, a_lo, a_hi, tol=0.30):
        """两端各有「垂直于踏步」的围合线，且跨向重叠 ≥50% ⇒ 这是一个**被围合的台阶平台**。

        没有这道闸门会把「几根恰好等距的平行线」（如楼梯间踏步、栏杆组、中庭栏板）都当成台阶
        平台，把大片楼板挖掉 —— c006 F0 实测误报 15 处。
        """
        need = [False, False]
        for c, lo, hi, _i in perp:
            ov = min(hi, a_hi) - max(lo, a_lo)
            if ov <= TREAD_MIN_OVERLAP * (a_hi - a_lo):
                continue
            if abs(c - along_lo) <= tol:
                need[0] = True
            if abs(c - along_hi) <= tol:
                need[1] = True
        return need[0] and need[1]

    out = []
    for group, perp, horiz in ((h, v, True), (v, h, False)):
        for cluster in _parallel_clusters(group):
            if not _is_tread_cluster(cluster):
                continue
            cluster = _dedupe_cluster(cluster)
            along = (min(r[1] for r in cluster), max(r[2] for r in cluster))
            outer = max(r[0] for r in cluster)
            near = min(r[0] for r in cluster)
            inner = None
            for c, lo, hi, _i in group:          # 踏步近侧最近的平行线 = 建筑外墙皮
                if c >= near - 1e-9:
                    continue
                ov = min(hi, along[1]) - max(lo, along[0])
                if ov <= TREAD_MIN_OVERLAP * min(hi - lo, along[1] - along[0]):
                    continue
                inner = c if inner is None else max(inner, c)
            if inner is None or near - inner <= 1.0:
                continue
            if not _enclosed(perp, along[0], along[1], inner, outer):
                continue
            # **外侧（远离建筑的一端）必须是「一条边线」，不能是墙** —— 这是「室外台阶」与
            # 「室内楼梯间」的唯一可靠分界：室内楼梯间四周都是真墙（外侧那端也有 0.24/0.35
            # 的配对墙），室外台阶的外沿只是台阶边线（单线，没有第二皮）。
            # 判据要在**排除踏步线之后**做：踏步线彼此间距 0.35 会被误当成「墙的配对」。
            tread_idx = {r[3] for r in cluster}
            outer_is_wall = False
            for c, lo, hi, i in group:
                if i in tread_idx:
                    continue
                d = abs(c - outer)
                if not (wall_min <= d <= wall_max):
                    continue
                ov = min(hi, along[1]) - max(lo, along[0])
                if ov > TREAD_MIN_OVERLAP * (along[1] - along[0]):
                    outer_is_wall = True
                    break
            if outer_is_wall:
                continue
            out.append({"horiz": horiz, "along": along,
                        "across": (inner, outer)})
    return out


def drop_terrace_faces(segs, boxes, tol=0.40):
    """剔掉室外台阶的全部图线：围合挡墙、踏步、贴角斜线。

    判据：线段**任一端点**落在外接矩形内（矩形朝建筑一侧不外扩、其余三边外扩 tol）——
    台阶挡墙、踏步线、以及从台阶角点甩出去的斜向剖断线都至少有一个端点在盒内；
    建筑自身那道外墙皮是**穿过去**的，两端都在盒外，不受影响。
    """
    if not boxes:
        return list(range(len(segs)))
    keep = []
    for i, (a, b) in enumerate(segs):
        pts = (a, b)
        hit = False
        for bx in boxes:
            lo_a, hi_a = bx["across"]
            lo_l, hi_l = bx["along"]
            for (px, py) in pts:
                if bx["horiz"]:
                    across, along = py, px
                else:
                    across, along = px, py
                if (lo_a - 1e-9 <= across <= hi_a + tol
                        and lo_l - tol <= along <= hi_l + tol):
                    hit = True
                    break
            if hit:
                break
        if not hit:
            keep.append(i)
    return keep


def pair_wall_faces(wall_pts, p):
    """把 2 点墙皮线配成「真实厚度」墙矩形（双线墙的两皮），返回 (rects, singles)。

    CAD 双线墙 = 两条平行线（两皮），两线间距 = 真实墙厚（C006 实测 240/270/120/60mm，
    楼梯间剪力墙 350/380mm）。C006 每皮还被画成多段共线/重复 LINE，先 _merge_collinear
    合并成极大段，再配对（配对判据：同向 + 中心距 ∈ [wall_min, wall_max] + 投影重叠 >0.3m）。
    配对 → 4 点矩形（两皮实际端点围成的 bbox，厚度 = 真实间距）。
    单线（无平行近邻：门垛 / 短段 / 女儿墙）→ singles，不冒充有厚度的墙。
    这是「以实际线条建模」的核心：墙厚读出来，不是 buffer 猜出来。
    """
    hsegs, vsegs, dsegs = [], [], []
    for pts in wall_pts:
        if len(pts) == 2:
            pairs = [(pts[0], pts[1])]
        elif len(pts) > 2:
            # 多段折线**逐段拆开**再配对。旧实现是 `if len(pts) != 2: continue` ——
            # 把整条折线**静默丢掉**：不配对、也不当单线，图纸上实有的一整面外墙从模型里
            # 凭空消失。ny27 判例：西外皮在图上是一条 12 点阶梯折线
            # （x[-23.520,-15.480] y[-8.758,3.482]），经此 continue 后整个西立面 12m
            # 一根墙都不剩（拆开后它才配出 x[-23.520,-23.280] 的 0.24 真厚外墙）。
            # 拆出的共线碎段由下面的 _merge_collinear 重新并成极大段，不会碎片化。
            pairs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
        else:
            continue
        for (x0, y0), (x1, y1) in pairs:
            if abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9:
                continue                                   # 零长段（重复点）
            _dx, _dy = abs(x1 - x0), abs(y1 - y0)
            # ★ 斜段**不按轴对齐建**（2026-09-14 c006）：旧口径用起点坐标当中心线，
            #   45° 段会被建成"竖墙/横墙"—— 八角厅左下角「竖段+斜段」因此拼成一条直墙，
            #   墙脚偏出图纸 2.5m（反向量具：F0-F3 各 17~25 块墙偏离 >0.5m，全在八角厅）。
            #   斜段改为**按图纸那条线各建一条**（位置以图纸为准）；c006 实测偏离块 94 -> 2，
            #   图纸覆盖率 92.0% -> 93.8%（同向改善）。
            if min(_dx, _dy) > 0.25 and min(_dx, _dy) > 0.3 * max(_dx, _dy):
                dsegs.append([(x0, y0), (x1, y1)])
                continue
            if _dx >= _dy:
                lo, hi = (x0, x1) if x0 <= x1 else (x1, x0)
                hsegs.append((y0, lo, hi))   # (center_y, lo_x, hi_x)
            else:
                lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
                vsegs.append((x0, lo, hi))   # (center_x, lo_y, hi_y)

    def _pair(segs, horiz):
        segs = sorted(segs, key=lambda s: s[0])
        n = len(segs)
        # ① 收齐合法候选（同向 + 中心距 ∈ [wall_min, wall_max] + 投影重叠 > 0.3m），
        #    按「重叠长 > 距离近」排序；② 全局贪心取优（先占用者胜），最后按首成员下标
        #    升序发射，保持与旧实现相同的输出顺序语义。
        # 旧实现是「按中心坐标从左到右、先到先得」——致命处在图上贴着墙画的短符号段
        # （洁具/管道井小方盒的一条边，0.49m）中心坐标更靠左时会先挑走真墙皮的 mate，
        # 真墙另一皮只好去配另一侧的同款符号段：一根 240 墙被劈成两根 260 假墙、中间留
        # 一条 240 空槽，模型上就是「一根墙显示成两根」（c018 每层 14 处、六层 168 根）。
        # 按重叠排序后，6.60m 的真配对恒压过 0.49m 的符号段，与坐标先后无关。
        cand = []
        for i in range(n):
            c1, lo1, hi1 = segs[i]
            j = i + 1
            while j < n and segs[j][0] - c1 <= p.wall_max:
                c2, lo2, hi2 = segs[j]
                d = abs(c2 - c1)
                if d >= p.wall_min:
                    ov = min(hi1, hi2) - max(lo1, lo2)
                    # ★ 重叠判据（2026-09-14 c006 实测）：旧版要求「绝对重叠 > 0.3m」，
                    #   图纸里大量墙皮是「一长一短」（长皮跨门洞、短皮只在墙段内），
                    #   经 _merge_collinear 切碎后重叠常只有 0.15~0.29m → 配不上对 →
                    #   退化成单线墙（薄一半）。实测每层 98~110 条（单线墙的 16~21%）
                    #   旁边 0.4m 内就有平行线却没配上。
                    #   改为「绝对 0.3m 或 短线长的 30%」二者满足其一。
                    if ov > 0.3 or (ov > 0.12 and ov > 0.3 * min(hi1 - lo1, hi2 - lo2)):
                        cand.append((-ov, d, i, j))
                j += 1
        cand.sort()
        used = [False] * n
        chosen = []
        for _, _, i, j in cand:
            if used[i] or used[j]:
                continue
            used[i] = used[j] = True
            chosen.append((i, j))
        rects, singles = [], []
        for i, j in sorted(chosen):
            c1, lo1, hi1 = segs[i]
            c2, lo2, hi2 = segs[j]
            t = abs(c2 - c1)   # 真实墙厚（两皮间距）
            if horiz:
                # 长度方向取两皮实际端点的最大跨度 [min(lo), max(hi)]，厚度取 [min(c), max(c)]
                rects.append((box(min(lo1, lo2), min(c1, c2), max(hi1, hi2), max(c1, c2)), t))
            else:
                rects.append((box(min(c1, c2), min(lo1, lo2), max(c1, c2), max(hi1, hi2)), t))
        min_len = getattr(p, "single_min_len", 0.35)
        for i in range(n):
            if used[i]:
                continue
            used[i] = True
            c1, lo1, hi1 = segs[i]
            # 短到「墙厚量级」的单线不是墙，是**门/墙端头的画法**：双线墙画到头时用一条
            # 垂直于墙的短封口线收口（长度 = 墙厚，240/300mm），门洞两侧还各画一个小方盒
            # （门垛）。这些线在图上真实存在，但模型里不该有独立墙体 —— 用户判例 c018
            # 「2层内墙 #346」：x=-2.07 一根 0.24m 竖线被 buffer 成 0.10×0.34 的薄片。
            # 量级证据：c018 F0 配对矩形 204 块 ↔ 短单线 419 根 ≈ 2×204，正是「每堵墙两端
            # 各一条封口线」。阈值取 0.35m（吃掉 0.24/0.30 两类，放行 0.5m 及以上）。
            if hi1 - lo1 < min_len:
                continue
            if horiz:
                singles.append([(lo1, c1), (hi1, c1)])
            else:
                singles.append([(c1, lo1), (c1, hi1)])
        singles = list(singles) + [list(seg) for seg in dsegs]   # 斜段：按图纸线各建一条
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
    _fix_idx = fixture_indices(wall_pts, getattr(p, "fixture_max", 0.8))
    # ↓ 与 `derive_drawing_walls_and_outline`(:370) 和 `_wall_thin_batch`(:171) 对齐的**四剔**。
    # 本函数原先**只剔洁具**，于是 c006（全库唯一 classifier=line）的踏步线（2 点短线、间距
    # 0.3m）被下面同一个 `pair_wall_faces` 贪心配成 0.27m 厚的「墙」塞满楼梯井 —— 落盘实测
    # F1 的 404 面墙里 215 面（53.2%）被 `stairs.is_fragment` 判为碎片，厚 0.27 的占 105 面。
    # 另两条实现都有这道剔除，只有这条漏了；而 c006 在 `_wall_thin_batch` 的 FROZEN 里
    # （"冻结楼永不碰"），唯一会做清理的批量器因此从不来清 —— 两个缺口叠在一起。
    # ⚠️ 只影响**建墙**：楼梯井由 `floor.detect_stairwells(F, walls, p)` 用未过滤的原始线算，
    #    且在 derive 之后调用，所以剔踏步线不会让井消失。
    _tread_idx = _stair_tread_indices(wall_pts)
    _mid_idx, _band_idx = _stair_mid_band_indices(wall_pts, _tread_idx,
                                                  getattr(p, "wall_min", 0.08))
    drop = set(_tread_idx) | set(_mid_idx) | set(_band_idx) | set(_fix_idx)
    for i, pts in enumerate(wall_pts):
        if i in drop:
            continue                                   # 洁具/踏步线/中缝/中带 —— 都不是墙
        closed = (len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) <= 1e-6
                  and abs(pts[0][1] - pts[-1][1]) <= 1e-6)
        (solid if closed else lined).append(pts)
    # ⚠️ **踏步线不在主链剔**（2026-09-15 反复实测后的结论，别再把 `tread_face_indices` 挂上来）：
    #   踏步线间距 0.27~0.35m 与墙厚档重叠，确实会被双线配对配成 0.35m 假墙；但**整簇剔除
    #   踏步线会把楼梯间的轮廓闭合力拆掉** —— 楼梯间的围合墙上有门洞缺口，平时靠踏步线补上
    #   那几米，剔掉后缺口 > outline_close_r，外环不再闭合：实测 c006 F0 轮廓 6487→881㎡、
    #   F1 5900→1825㎡、房间 34→6 间（灾难性回归）。
    #   所以：室内楼梯踏步交给上面那套「四剔」里的 `_stair_tread_indices/_stair_mid_band_indices`
    #   （它们只剔短踏步线、不动围合），**室外台阶**走 profile 具名口子 `outdoor_steps`
    #   （在 floor.extract_floor 里按层切楼板 + 丢盒内墙）。
    #   识别函数 `tread_face_indices / tread_terraces` 保留，供诊断脚本查图用。
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
    # ★ 2026-09-15 **换算法**（用户判例：「墙角凹进去的楼板还是多了点，这样不对」）：
    #   楼板 = 墙实体 ∪ **被墙围住的各个面**（`polygonize`），不再走「每个墙块外环填实再并」。
    #   旧法为什么凹角会多铺：墙体在图上被门洞/绘图缝切成**多块**（实测 c006 F1/F4/F6 的墙环
    #   都是 MultiPolygon，`ring.exterior` 根本不存在），`blocks_to_outline` 对每块取
    #   `Polygon(exterior)` 填实 —— 凹角那侧的开口被当成里腔一并填掉，两翼之间、塔楼与裙楼之间
    #   的凹口就被凭空补上楼板。
    #   新法：先把墙按 `outline_close_r` 做闭运算桥接门洞/小缝得到「围合物」，再 `polygonize`
    #   取被围住的**有界面**（无界的外面不会成为面），楼板 = 墙 ∪ 这些面 ⇒ 边界严格贴墙，
    #   凹角一个不多、一个不少。
    sealed = region.buffer(close_r).buffer(-close_r) if close_r else region
    faces = [f for f in polygonize(sealed.boundary) if f.area >= 1.0] if not sealed.is_empty else []
    slab = unary_union([region.buffer(0)] + faces) if faces else region.buffer(0)
    # ★ 凹角小口袋（2026-09-15 用户判例：「墙角凹进去的楼板还是多了点，多出是不对的」）：
    #   上面那道闭运算会把凹口上 ≤1.2m 的开口桥接掉，于是凹角被当成里腔填进楼板。
    #   实测 c006：F1/F4 各在南侧两翼内凹角多出 8.5~10.0㎡ 两块（x[29.4,36.3] y[−34.8,−28.2]
    #   及镜像），**超出图纸外皮**。判据：以图上真实画的**外皮折线**（>=7 点的那几条，即建筑
    #   外轮廓）为界，把楼板伸到外皮之外、且**面积 ≤ SMALL_POCKET** 的口袋切掉。
    #   为什么带面积上限：同一层还合法地存在「比外皮大」的整片板 —— F4 的八角厅屋面（532㎡）、
    #   F6 的裙楼屋面（2219㎡×2），面积上限保证不动它们。
    SMALL_POCKET = 100.0
    # 换用「外沿折线封闭拉出」轮廓时，要挖回的内院洞的最小面积（㎡）。
    # 取 100：图纸内院/天井实测 1306.5(c054)、1808+1245(c009)、1318.7(c072)，都远大于它；
    # 而墙 union 里 <100㎡ 的"里腔"多是识别碎片（管道井/门斗），挖出来反而把楼板啃出小洞。
    ROOF_MIN_HOLE_AREA = 100.0
    _skin_pts = [s for s in split_2pt(wall_pts) if len(s) >= 2]
    _skin = [list(map(tuple, w)) for w in wall_pts if len(w) >= 7]
    _pockets = []
    if _skin:
        try:
            skin = unary_union([Polygon(w if w[0] == w[-1] else w + [w[0]])
                                for w in _skin]).buffer(0.35)
            outside = slab.difference(skin)
            _pockets = [g for g in ([outside] if outside.geom_type == "Polygon"
                                    else list(getattr(outside, "geoms", [])))
                        if g.geom_type == "Polygon" and g.area <= SMALL_POCKET]
        except Exception:
            _pockets = []
    # 「保留 >= 主楼 2% 的分量」+ 60m 副本闸门仍走 `outline.blocks_of`；不同之处是现在填实的
    # 是**已经贴墙的楼板面**，不再是「墙块各自的外环」。
    blocks = OUT.blocks_of(slab, close_r=0.0)
    # `keep_courtyard_holes`（按楼开关）：回字形平面的**内院/天井**保留成内环，不填实
    outline = OUT.blocks_to_outline(
        blocks, keep_holes=bool(getattr(p, "keep_courtyard_holes", False))) \
        if blocks else Polygon()
    if outline.is_empty:
        return Polygon(), [], []
    # ⚠️ 口袋必须在 `blocks_to_outline`（= 每块外环**填实**）**之后**切：填实会把围成里腔的
    #    凹角一并补回来，切在前面等于白切（实测：切完 18.5㎡ 又原样回来）。切在最后才是终态。
    if _pockets:
        _cut = unary_union(_pockets)
        trimmed = outline.difference(_cut).buffer(0)
        if not trimmed.is_empty:
            print("    [%s] 凹角小口袋（超出图纸外皮、≤%.0f㎡）切掉 %d 块 %.1f㎡"
                  % (p.name, SMALL_POCKET, len(_pockets), _cut.area))
            outline = trimmed
    # ★★ 2026-09-15 **改用「外沿折线封闭拉出」**（用户判据：「楼板应该由外沿线封闭拉出」）：
    #   图纸上建筑外轮廓本来就是画成一条（几条）**长折线**（外墙外皮，本图 45/55/31 点那种）。
    #   把它们各自首尾闭合 → 并起来，就是楼板 —— 边界严格等于图纸画的外沿线，
    #   两面墙交接处不会像"墙相并再填实"那样鼓出一个三角形（用户判例：墙角多出三角）。
    #   实测（F7/F8/F9 塔楼）：这个口径 = **912.7㎡，与图纸自带面积表 912.70 分毫不差**。
    #   闸门（0.6~1.5 倍墙法轮廓）只用来挡住"这层外沿折线本身是碎的/混进别的长线"的楼层
    #   （实测 F2/F3 只有 6.4㎡ 碎片、F10 混进 2274.8㎡ 的长线）→ 那些仍走墙法。
    _skin_polys = []
    for _w in wall_pts:
        if len(_w) < 7:
            continue
        try:
            _p = Polygon(list(_w) if _w[0] == _w[-1] else list(_w) + [list(_w)[0]])
        except Exception:
            continue
        if not _p.is_valid:
            _p = _p.buffer(0)
        if not _p.is_empty and _p.area >= 1.0:
            _skin_polys.append(_p)
    if _skin_polys:
        _skin_u = unary_union(_skin_polys)
        if 0.6 * outline.area <= _skin_u.area <= 1.5 * outline.area:
            # ⚠️ 外沿折线是分片画的（西半/东半/中段各一条），闭合后得到的是**沿边相接**的
            #    MultiPolygon。交付编码 `outline_fields` 靠"钥匙孔桥接"把多块写成单环，
            #    对**相接**的块桥不出来 → 退回只写最大一块（实测 F1 5845.9 → 交付 2216.0，
            #    F1~F5 全塌）。先做一次 ±5cm 的 buffer 把相接块并成单块（形变 ≤5cm）。
            _merged = _skin_u.buffer(0.05).buffer(-0.05)
            if not _merged.is_empty:
                _skin_u = _merged
            print("    [%s] 楼板改用「外沿折线封闭拉出」：%.1f㎡（墙法 %.1f㎡）"
                  % (p.name, _skin_u.area, outline.area))
            # ★ 2026-09-16 保留内院洞（用户判据「每层的楼板是怎么生成的」）：
            #   外沿折线闭合出来的是**填实的**多边形，换上去会把这层的**内院/天井洞**一起抹掉
            #   —— 楼板就把内院铺满，比图纸自带面积表多出的正好是内院面积
            #   （实测 c054/c055 F0 内院 1306.5㎡ → 模型 +1205.3㎡；c009 同款两处大洞）。
            #   所以：把**墙法轮廓里已经按 keep_courtyard_holes 判过**的内环再挖回外沿轮廓。
            _keep = []
            for _pp in ([outline] if outline.geom_type == "Polygon" else list(outline.geoms)):
                for _h in _pp.interiors:
                    _hp = Polygon(_h).buffer(0)
                    if not _hp.is_empty and _hp.area >= ROOF_MIN_HOLE_AREA:
                        _keep.append(_hp)
            outline = _skin_u.difference(unary_union(_keep)).buffer(0) if _keep else _skin_u
    if not outline.is_valid:
        outline = outline.buffer(0)
    outline = outline.simplify(0.2)
    return outline, wall_geoms, wall_ts


def derive_drawing_walls_and_outline(wall_pts, p, is_top=False):
    """读图成图：墙与轮廓都从图上读，**不合成外环**。

    **LWPOLYLINE 楼的唯一路径**（用户 2026-09-12：「建筑的做法全部用一个方案，没有特殊」；
    只有两种真正不同的图纸约定另走他路：`door_by_points` 与 `classifier == "line"`）。

    用户判据：「你不能臆想的创造墙，而是严格按照图纸来」。旧的 LWPOLYLINE 路径
    把每条 2 点墙线按 `wall_fallback`=0.15 各缓冲成一条 0.30 带，于是：
      · 轮廓 = 「墙中线 ± 0.15」的外缘 —— ny27 实测西/东/南三边比图上最外线**外扩 0.145m**，
        北边反而被切掉 0.370m，四条边没有一条对得上；
      · 外墙 = `outline.buffer(-outer_wall_t)` 的合成环 —— 图上根本没有这条线，它的内皮
        y=−8.60 与图上内皮 y=−8.518 差 8cm；配对出的真外墙面（−8.90…−8.52）被这圈裁剩
        6cm 纸皮，交付成「内墙 #5」。
    这里改成和 C006「line 约定」同源的做法：**双线配对读真厚矩形**，轮廓就是这些矩形的外环。

    两处与 `derive_line_walls_and_outline` 不同，都是有意的：
      · 轮廓的**质量**多一路 —— 没配对的单线（内隔墙中线）按 `wall_fallback` 缓冲后一起进
        并集，足迹才封得住。只拿配对矩形去并，ny27 会得到 137.6㎡ 的**梳子**（墙带网络）
        而不是 561㎡ 的楼板足迹。外皮不会因此外扩：最外那两皮是**配对**的，被缓冲的都在室内。
      · 配对前先剔楼梯踏步线/中缝带/洁具（同 `_wall_thin_batch`）：不剔会配出 0.30/0.10 的
        假墙塞满楼梯井（用户「楼梯识别成内墙」根因）。

    返回 (outline, wall_geoms, wall_ts)；`wall_geoms/wall_ts` 是**交付用**的墙（配对矩形 +
    单线薄墙），不含只用来封足迹的那层缓冲。
    """
    _fix_idx = fixture_indices(wall_pts, getattr(p, "fixture_max", 0.8))
    _tread_idx = _stair_tread_indices(wall_pts)
    _mid_idx, _band_idx = _stair_mid_band_indices(wall_pts, _tread_idx,
                                                  getattr(p, "wall_min", 0.08))
    drop = set(_tread_idx) | set(_mid_idx) | set(_band_idx) | set(_fix_idx)
    solid, lined = [], []
    for i, pts in enumerate(wall_pts):
        if i in drop:
            continue
        closed = (len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) <= 1e-6
                  and abs(pts[0][1] - pts[-1][1]) <= 1e-6)
        if closed:
            # 闭合折线有两义，**不能一律当实心墙带填充**：
            #  · 实心墙带（矩形 / L 形，等效厚 = 2×面积/周长 ≤ 0.5m）→ 填充，就是它本身；
            #  · 外皮环（把整栋圈起来的**细带**，如 c022 那两条相隔 0.20m 的 9/11 点闭合
            #    折线 = 外墙的两皮）→ 填充出来的是**盖住整栋的一块实心墙**（c022 实测
            #    2028㎡「墙」> 1011㎡ 楼板，c041 1035>937，c104 4951>3880 都是这条）。
            #    环的边界周长 ≈ 2×建筑周长、却只有墙厚那么细，故按**皮线**逐段配对，
            #    两条环自然配出真厚外墙（c022 的两环间距 0.20m 就是它的外墙厚）。
            try:
                P = Polygon(pts)
                if not P.is_valid:
                    P = P.buffer(0)
            except Exception:                                          # noqa: BLE001
                continue
            if not P.is_empty and P.length > 1e-6 and P.area / P.length > 0.25:
                lined.append(pts)
                continue
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
        except Exception:                                          # noqa: BLE001
            continue
        if not P.is_valid:
            P = P.buffer(0)
        if P.is_empty or P.area <= 1e-6:
            continue
        wall_geoms.append(P)
        wall_ts.append(round(2.0 * P.area / P.length, 3) if P.length else st)
    if not wall_geoms:
        return Polygon(), [], []

    # 轮廓：**旧轮廓内缩 wall_fallback 再并回真厚墙矩形**，不做第二套围合。
    #
    # 为什么内缩就够：旧轮廓是「墙中线 ± wall_fallback」的外缘（2 点墙线各 buffer 0.15），
    # 所以它在每一条边上都比**图纸墙外皮**多出 wall_fallback —— ny27 实测南 −8.903 vs 图上
    # −8.758、西 −23.667 vs −23.520，差就是 0.15。内缩 0.15 正好退回图上的外皮
    # （实测 bbox 与图上墙线差 ≤7mm，余量来自内缩的圆角与 simplify(0.2)）。
    # 不能改成「只拿配对矩形去并」：那会得到 137.6㎡ 的**梳子**（墙带网络），足迹没了 ——
    # 填充靠的是全图墙线的密度，不是配对矩形本身。
    # 并回 `rect_union` 是为了让**图上真有的外挑**（凹口外的墙垛/壁柱）不被内缩切掉。
    outline, _, _ = _derive_buffer_walls_and_outline(wall_pts, p, is_top)
    if outline.is_empty:
        return Polygon(), [], []
    rect_union = unary_union([poly for poly, _ in rects]) if rects else None
    outline = outline.buffer(-p.wall_fallback)
    if rect_union is not None and not rect_union.is_empty:
        outline = outline.union(rect_union).buffer(0)
    if outline.is_empty:
        return Polygon(), [], []
    if not outline.is_valid:
        outline = outline.buffer(0)
    return outline.simplify(0.2), wall_geoms, wall_ts


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


JOG_MIN_LEG = 0.35   # 与 `single_min_len` 同源的「短单线不成墙」量级（见 `_is_wall_jog`）


def _is_wall_jog(pts, min_leg=JOG_MIN_LEG):
    """开口 **3 点**折线是不是「墙端头的 L 形转折 / 外挑构件转角」—— 该当墙，不是门符号。

    为什么单列一条：兜底分支原来用 `不闭合 + span < DOOR_SPAN_MAX(3.0) → continue`
    一刀切，把门符号和**真几何**一起丢了。实测（`_scratch/_a0_jog_census.py`，全库各楼前 3 层）：
    开口 + span<3 的折线 6523 条，其中 3 点 L 形 1570 条、1137 条 span >= 1.0m。

    **门符号不可能是 3 点** —— 门要「闭位扇 + 开位扇」两段另加摆动弧或门垛，点数 >= 4。
    3 点 L 的物理含义只有两种：墙端头收口的转折、外挑构件（阳台栏板 / 雨篷）的转角。

    剩下 9.2% 的 3 点 L 恰好两腿等长垂直（`_hinge_leaf > 0`，如 c046 每层 12 处 2.76×2.76
    的外挑转角），那是画法撞车，仍按墙处理：同一条线也会被 `detect_doors` 认成门，
    两条路各自成立、互不吞没（墙里有洞 = 门）。
    """
    if len(pts) != 3:
        return False
    if abs(pts[0][0] - pts[-1][0]) <= 1e-6 and abs(pts[0][1] - pts[-1][1]) <= 1e-6:
        return False
    legs = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            for i in range(2)]
    return min(legs) >= min_leg


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
    """楼梯踏步折线的下标（配对成墙之前先剔掉，否则配出 0.3m 假墙塞满楼梯井）。

    ⚠️ 判据全部搬进 `stairs.tread_indices`（唯一实现，识别/剔除共用一份）。
    旧实现在这里按「y 差 ≤0.35 且 x 中心差 ≤3.0」并段，既会把楼梯两侧 240mm 的
    墙双线吃成踏步，又**只收水平段**（东西向梯段的踏步线一直漏剔）。
    """
    from . import stairs as _stairs
    return _stairs.tread_indices(wall_pts)


def _stair_midline_indices(wall_pts, tread_idx):
    """识别踏步端点连线（对称三线中间竖线）的下标。仅返回中线（兼容旧调用）。"""
    return frozenset(_stair_mid_band_indices(wall_pts, tread_idx)[0])


def fixture_indices(wall_pts, max_size=0.8):
    """洁具/家具画法的下标：**开口**折线且 bbox 两边都 < max_size。

    CAD 上洁具（坐便/蹲位/洗手台）画成开口矩形，且和墙挤在同一图层 —— c018 的图层名
    就叫 `4.2墙体`，墙/门/洁具捆在一起。c018 卫生间实测原始折线：
        [(2.94,7.69),(3.22,7.69),(3.22,7.20),(2.94,7.20)]   n=4 closed=False 0.28×0.49
    拆段后两条 0.49m 竖边 > single_min_len(0.35) 活了下来，各 buffer 成 0.10×0.60 的
    胶囊薄片，模型里就是卫生间正中凭空多出两根短墙（`w0-i182`/`w0-i184`，66 顶点=单线
    buffer 指纹）。用户判例 c018 8150 标注：**"这代表厕所，不用画了"**。

    判据三件套缺一不可：
      · **几何开口**（边集里没有环，`_has_edge_cycle`）—— 闭合的 4 点小环是**门垛/柱**的
        画法，另有归属，不动；
      · ≥3 点 —— 2 点短线是墙端封口/门垛，由 single_min_len 管，不在这里处理
        （这条也是它和「残留 1334 根 0.35~0.45m 短薄墙」的分界：那些是 2 点线）；
      · bbox 两边都 < max_size —— 房间/楼梯/管井都远大于 0.8m。

    ⚠️ 第一条**不能用「首点≠末点」代替**（2026-09-12 实测 c025 F0 全中假阳性）：
    国标柱/壁柱的「方框打叉」写成一条 8 点折线 —— 四角 + 两条对角线，**以对角线收尾**，
    首末点天然不等，比首末点的判据形同虚设（c025 F0 87 条命中里 85 条是柱、真洁具 0 条）。
    所以这里按**边集并查集**判环：任何一条边的两端若已连通，就是几何闭合。
    """
    out = set()
    for i, pts in enumerate(wall_pts):
        if len(pts) < 3:
            continue
        if _has_edge_cycle(pts):
            continue                                   # 几何闭合 = 门垛/柱，不是洁具
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        if max(xs) - min(xs) < max_size and max(ys) - min(ys) < max_size:
            out.add(i)
    return frozenset(out)


def _has_edge_cycle(pts, tol=1e-4):
    """折线的**边集**里是否含环（真几何闭合），而非只看首末点是否相等。

    「方框打叉」的 8 点折线边集 = 四边 + 两条对角线（还多一条重复边），
    四边那一段本身就是个闭环 → 并查集在合并最后一条边时两端已连通，判出环。
    开口矩形 `[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]` 只有 3 条边、无环 → 不判环（真洁具）。
    """
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def key(q):
        return (int(round(q[0] / tol)), int(round(q[1] / tol)))

    for i in range(len(pts) - 1):
        a, b = key(pts[i]), key(pts[i + 1])
        if a == b:
            continue
        for k in (a, b):
            parent.setdefault(k, k)
        ra, rb = find(a), find(b)
        if ra == rb:
            return True                                # 两端已连通 → 这条边成环
        parent[ra] = rb
    return False


def _stair_mid_band_indices(wall_pts, tread_idx, wall_min=0.08):
    """识别「楼梯中缝三线」：返回 (中线下标集, 整组下标集)。

    双跑/双分楼梯的中缝带画成「左皮 + 中点线 + 右皮」三条平行线（间距各 ~0.1m），
    合起来是一个 **0.20m 宽带**。中线不是墙（旧实现只剔中线），但 **两条皮也不是墙** ——
    用户判例 c018 一层内墙 #94：`w0-i92` 就是这块 0.20×3.20 的带，整条落在楼梯井里
    （井 x[-25.08,-21.72]，两跑在 x=-23.50 相接），用户原话「**这个位置就是楼梯的位置**」。
    它是梯段分界/扶手，不是隔墙。

    返回第二项 = 中线 + 左右两皮，供调用方整组剔除。左右皮的判定与中线同一套对称性：
    中线两侧各 0.06~0.14m 处各有一条平行线、且互相重叠 >0.3m。
    ⚠️ 两个走向都要查：中缝线垂直于**跑向** —— 南北向梯段（跑沿 y）的中缝是竖线，
    东西向梯段（跑沿 x）的中缝是横线。旧实现只查竖线，东西向梯段的中缝一直是漏剔的。

    ⚠️ 还有**第二种画法**：中缝画成一条**闭合细带**（本函数末尾那个分支），
    不是三条独立线。旧实现第一行 `len(pts) != 2: continue` 把它整条放过，
    拆段后成两条相距 0.06m 的长竖线（< wall_min，配不成对），各 buffer 成一根
    0.10m 胶囊假墙（ny27/28/29 每层 3~4 条，见 `w0-i104`/`w0-i105`）。
    """
    fams = {"v": [], "h": []}       # (c, lo, hi, idx)：c = 垂直向坐标
    for i, pts in enumerate(wall_pts):
        if i in tread_idx or len(pts) != 2:
            continue
        (x0, y0), (x1, y1) = pts
        dx, dy = x1 - x0, y1 - y0
        if min(abs(dx), abs(dy)) > 0.02:
            continue
        if abs(dy) >= abs(dx):
            fams["v"].append((round((x0 + x1) / 2, 3), min(y0, y1), max(y0, y1), i))
        else:
            fams["h"].append((round((y0 + y1) / 2, 3), min(x0, x1), max(x0, x1), i))
    # 「三线对称」不是楼梯独有的画法 —— 锯齿形飘窗也画成三条（外皮/窗台/内皮，同样 ~±0.12）。
    # 所以整组剔除必须再叠一条**位置**判据：只认**落在踏步线范围内**的那一组（梯段分界带）。
    # 不叠这条会连带删掉全楼每一樘飘窗的墙（c018 F0 实测 63 个假组里有 60 个是飘窗）。
    treads = []
    for i in tread_idx:
        if len(wall_pts[i]) >= 2:
            treads += list(wall_pts[i])
    if not treads:
        return frozenset(), frozenset()
    tx0 = min(q[0] for q in treads); tx1 = max(q[0] for q in treads)
    ty0 = min(q[1] for q in treads); ty1 = max(q[1] for q in treads)

    def _in_treads(vertical, c, lo, hi):
        a0, a1, b0, b1 = (tx0, tx1, ty0, ty1) if vertical else (ty0, ty1, tx0, tx1)
        span = b1 - b0
        if span <= 0.3:
            return False
        if not (a0 - 0.2 <= c <= a1 + 0.2):
            return False
        return (min(hi, b1) - max(lo, b0)) / span >= 0.8

    mid, band = set(), set()
    for kind, lines in fams.items():
        vertical = (kind == "v")
        for c, lo, hi, i in lines:
            left = right = None
            for c2, lo2, hi2, j in lines:
                if j == i:
                    continue
                d = c2 - c
                if abs(d) < 0.02:
                    continue
                if min(hi, hi2) - max(lo, lo2) <= 0.3:
                    continue
                if 0.06 <= abs(d) <= 0.14:
                    if d < 0:
                        left = (d, j)
                    else:
                        right = (d, j)
            if left and right and abs(left[0] + right[0]) < 0.02:
                mid.add(i)
                if _in_treads(vertical, c, lo, hi):
                    band.update((i, left[1], right[1]))
    # ---- 第二种画法：闭合细带 ----
    # 判据：几何闭合（边集含环，不是「首=尾」）+ 短边 < wall_min + 落在踏步范围内。
    # 短边 < wall_min 是关键的一条：比最薄的双线墙(0.08)还薄，本来就是**成不了墙**的
    # 图形 —— 实测 ny27/28 每层 3 条 0.060×2.220、ny29 每层 4 条，全部落在梯段范围内。
    # 位置判据与上面的三线族共用（`_in_treads`），不会碰到飘窗那类同一走向的组。
    for i, pts in enumerate(wall_pts):
        if i in tread_idx or i in band or len(pts) < 4:
            continue
        if not _has_edge_cycle(pts):
            continue
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if min(w, h) >= wall_min:
            continue                                   # 够厚，可能是真墙，不动
        if h >= w:
            vert, c, lo, hi = True, (min(xs) + max(xs)) / 2.0, min(ys), max(ys)
        else:
            vert, c, lo, hi = False, (min(ys) + max(ys)) / 2.0, min(xs), max(xs)
        if _in_treads(vert, c, lo, hi):
            band.add(i)
    return frozenset(mid), frozenset(band)


def _derive_paired_walls_and_outline(wall_pts, p, is_top=False, synth_outer=True):
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
    # `synth_outer=False`（LWPOLYLINE 读图路径）**必须**连检测都不做：`_detect_outer_skin`
    # 在 ny27 上会误配出 87.7㎡ 的「外皮环」（它把两条不相干的折线闭合起来），一旦检出，
    # 下面就会长出 `外皮 − 内缩 outer_t` 这条**图上没有的合成外墙环** —— 正是用户
    # 2026-09-12「你不能臆想的创造墙，而是严格按照图纸来」要拆掉的东西。同时 `outer_idx`
    # 里那两条折线还得回到配对池里（它们是真墙线，不是外皮）。
    outer_poly, outer_idx = _detect_outer_skin(wall_pts) if synth_outer else (None, frozenset())
    # 楼梯踏步线（水平短段）与踏步端点连线（对称三线中间竖线）不是墙，剔除后再配对，
    # 否则会配出 0.3m/0.1m 假墙塞满楼梯井（「楼梯间墙体不对」根因）。
    tread_idx = _stair_tread_indices(wall_pts)
    _mid_idx, _band_idx = _stair_mid_band_indices(wall_pts, tread_idx,
                                                  getattr(p, "wall_min", 0.08))
    _fix_idx = fixture_indices(wall_pts, getattr(p, "fixture_max", 0.8))
    inner_polys = [pts for i, pts in enumerate(wall_pts)
                   if i not in outer_idx and i not in tread_idx and i not in _mid_idx
                   and i not in _band_idx and i not in _fix_idx]

    wall_geoms, wall_ts = [], []
    wf = p.wall_fallback
    outer_t = getattr(p, "outer_wall_t", 0.24)

    # —— 外墙：周边折线（左右半）拼接成闭合外皮环，外墙 = 外皮 − 内缩 ——
    # 只在 synth_outer（door_by_points 理化楼约定）下成立：那栋楼的外墙在图上确实画成
    # 「周边折线 + 内皮线」，环是照图拼的。LWPOLYLINE 读图路径（ny27）不走这条 —— 它的外墙
    # 就是下面配对出的真矩形，图上没有环就没有环。
    if synth_outer and outer_poly is not None:
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
    blocks = OUT.blocks_of(region, close_r=close_r)
    outline = OUT.blocks_to_outline(
        blocks, keep_holes=bool(getattr(p, "keep_courtyard_holes", False))) \
        if blocks else Polygon()
    if outline.is_empty:
        return Polygon(), [], []
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

      门符号 = 4+ 点「不闭合」折线（leaf + swing arc，跨度 < 3m）。shapely Polygon()
      会把不闭合折线强行闭合成一个扇形面，混进 union 会把门洞桥接成假墙、把轮廓撑大
      （c041/c022 的 outline 729~1000㎡ 而真墙只有 70~370m 的根因）。
      判据边界有两条例外，都靠**点数**分：
        · 跨度 >= 3m 的不闭合折线 = 带门洞缺口的墙折线（c041 常见，最长 45.7m）→ 按线 buffer；
        · 跨度 < 3m 的 **3 点** L = 墙端头转折 / 外挑构件转角（c086 阳台栏板）→ 按线 buffer，
          见 `_is_wall_jog`。门符号要 leaf+arc（或两扇+门垛）至少 4 点，3 点不可能是门。
    """
    if getattr(p, "classifier", "lwpolyline") == "line":
        return derive_line_walls_and_outline(wall_pts, p)
    # 理化楼（door_by_points）：外墙在图上画成「周边折线」（8 点单线外皮 + 2 点内皮），
    # 配对池里没有它的外皮，只能照图把周边折线拼成闭合外皮再内缩 —— 见 synth_outer。
    if getattr(p, "door_by_points", False):
        return _derive_paired_walls_and_outline(wall_pts, p, is_top, synth_outer=True)
    # ★ 其余楼（LWPOLYLINE）统一走「读图成图」：墙 = 双线配对**真厚**矩形，轮廓 = 图上墙外皮。
    # 旧的「每条 2 点墙线各 buffer wall_fallback」不再是主路径 —— 它把墙中线的膨胀当墙，
    # 外皮虚胖 0.145m、外墙还是 `outline.buffer(-outer_wall_t)` 合成出来的环（图上没有这条线）。
    # 用户 2026-09-12：「你不能臆想的创造墙，而是严格按照图纸来」；「建筑的做法全部用一个方案，
    # 没有特殊」—— 所以这里是**唯一**的方案，不是按楼开关。
    return derive_drawing_walls_and_outline(wall_pts, p, is_top)


def _derive_buffer_walls_and_outline(wall_pts, p, is_top=False):
    """旧路径（保留作 `derive_drawing_walls_and_outline` 的轮廓底稿与回退）。

    2 点=墙皮线（buffer 半墙厚成实体墙）、3+ 点=已填充墙矩形，全部 union 后取外环填实。
    它仍是**轮廓填充**的来源：墙线密度的围合效果只有全缓冲这一版有（配对矩形太细，
    并出来是梳子）。它的问题在外皮和墙厚，不在填充 —— 所以轮廓拿它内缩，墙用配对矩形。
    """
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
                # 不闭合折线三种：
                #   · 大跨度(>=3m) = 带门洞缺口的墙折线 → 按线 buffer；
                #   · 3 点 L 形且两腿都不短 = **墙端头转折 / 阳台栏板转角** → 按线 buffer
                #     （见 `_is_wall_jog`，用户判例 c086 F1「阳台」）；
                #   · 其余小跨度(<3m) = 门符号 / 洁具 / 门垛 → 丢。
                if span < DOOR_SPAN_MAX and not _is_wall_jog(pts):
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

    # 轮廓来源：填充区 vs 墙 union，取「较大」者。
    #   大块填充区（area/length>1）常是楼板足迹（c009/c114，100~3900㎡），此时填充区比
    #   碎内墙大得多 → 用填充区。
    #   但 c104 这类裙楼+塔楼：塔楼每层画「填充楼板」（155㎡）当底，裙楼主体反而用墙画
    #   （358㎡ 墙 union 成 1171㎡ 足迹）。此时填充区（塔楼 155㎡）比墙 union 小得多，
    #   盲目用填充区会把轮廓塌成塔楼 → 应取较大者（裙楼墙 union）。
    #
    # ★ 2026-09-12：这里原先是 `max(region.geoms, key=area)` —— **只留最大一块**。
    #   全库实测 **21 栋 53 层**是多块楼层（`_scratch/_de_multiblock_census.log`）：
    #   c086 F3/F4/F5 是两栋塔楼（图纸中段一条折线都没有），max 只留东翼 843㎡；
    #   c079/c080/c083/c084/c085 的 F3~F5 是两~三块 257.8/258.2㎡ 的翼；
    #   c086 F1 的阳台栏板（配对正确、厚 0.17/0.20m）因为轮廓缺阳台被
    #   `interior_mask` 裁成 0.0000㎡。丢块 = D（多块塌一块）与 E（轮廓缺外挑）同根。
    #   现在改为**保留所有实体块**（判据见 `outline.blocks_of`：面积 ≥2㎡ 且 ≥最大块 2%，
    #   且离已留块 ≤60m —— 超过 60m 的是同一张图上画的另一栋/重复副本，仍要丢）。
    def _floor_outline(geoms, close_r=0.0):
        if not geoms:
            return None
        region = unary_union(geoms)
        # 闭运算桥接墙带缺口（c006 LINE 墙角点/门洞把墙带断开成几十段不相连的碎带，
        # union 后仍是 MultiPolygon）。close_r>0 时先 buffer 桥接再回缩，碎带连成整块。
        blocks = OUT.blocks_of(region, close_r=close_r)
        if not blocks:
            return None
        # 内院/天井：keep_courtyard_holes（按楼开关）→ 保留内环（见 outline.blocks_to_outline）
        o = OUT.blocks_to_outline(
            blocks, keep_holes=bool(getattr(p, "keep_courtyard_holes", False)))
        return o if not o.is_empty else None

    slab_outline = _floor_outline(slab_geoms)
    wall_outline = _floor_outline(wall_geoms, close_r=p.outline_close_r)
    # ⚠️ 试过用「大半径桥接（2.5m）把墙轮廓先闭合成环」再比大小 —— **实测无效且有害**：
    #   c054/c055/c009 首层的墙是真碎片（墙轮廓仍远小于填充 ⇒ 判据不咬合，面积不变），
    #   而 c072 F1 反而被改到 2980.1㎡（图纸面积表 3280.19，偏差从 +279 变成 −300）⇒ 已回退。
    #   结论：这三栋首层的问题不在"桥接半径"，而在**填充轮廓里那部分根本没有墙**
    #   （c054 村子院子 + 阳台带、c009 整片场地）⇒ 正确做法是把填充轮廓**裁到有墙支撑的部分**，
    #   判据：轮廓内的区域，其"到最近墙的距离 > R(≈6m) 且内部无房间"的大片空白 = 室外/院子，
    #   从楼板里挖掉（c054 院子 1232㎡、c009 首层 3918㎡）。这一步待做。
    # ★ 2026-09-16 **楼板必须由墙界定**（用户判据：「结合建筑的标准、建筑的样子」）：
    #   旧口径是「图纸填充轮廓 vs 墙 union 轮廓，**取大的**」—— 建筑上没有这条依据。
    #   首层图上常有一片"地坪/场地填充"（室外场地、内院、道路），一取大就把**院子当成了楼板**：
    #   实测 c054/c055 首层 +1205.3㎡（两张条形楼中间那个院子，图上【一根墙线都没有】）、
    #   c009 首层 +3918.3㎡、c103 首层 +1284.5㎡ —— 全是"场地填充比墙轮廓大"这一条造成的。
    #   新口径：**以墙轮廓为准**；只有当墙轮廓明显不完整（面积不到填充轮廓的 55%）时才回落到
    #   填充轮廓（那种情况是真·墙被切碎，用填充兜底才不会塌）。
    if wall_outline is not None and (
            slab_outline is None
            or wall_outline.area >= 0.55 * slab_outline.area):
        outline = wall_outline
    elif slab_outline is not None:
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
    """【已删除 · 2026-09-12】旧轮廓推导（hsegs/vsegs 版本），全库零调用点。

    留着它有害：里面 `max(comps, key=area)`（只取最大连通块）正是根因 D 的源头 ——
    多块楼层（c086 双塔、c079/c083 双翼）会被它塌成单片，接手的人照抄就复发。
    现行实现是 `_floor_outline()`（`OUT.blocks_of` 保留所有实体块 + `OUT.blocks_to_outline`），
    `derive_walls_and_outline()` 用它。要看旧实现：`git show HEAD:backend/recognizer/geometry.py`。
    """
    raise NotImplementedError("旧 derive_outline 已删除，见 docstring；用 _floor_outline()")


def detect_stairwells(F, walls, p):
    """楼梯井检测：按「x 重叠分列 → 列内级距均匀才成跑 → 跑相邻成井」识别。

    ⚠️ 判据全部搬进 `stairs.wells_of`（唯一实现，普查/识别/踏步剔除共用）。
    旧实现在这里按「中心距 ≤3.0m」并段，把楼梯两侧 240mm 的**墙双线**也吃成踏步
    —— ny27 F0 井宽被撑到 6.54m（真实梯段 2.46m）。详见 `stairs._columns` 的注释。
    """
    segs = []
    for pts in walls:
        cx = sum(pt[0] for pt in pts) / len(pts)
        # floor_of 可能返回 None（floor_y_bands 窗口外）—— 用 None 安全的写法
        _fs = [floor_of(p, cx, pt[1]) for pt in pts]
        if not any(f is not None and abs(f - F) < 0.5 for f in _fs):
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        for i in range(len(local) - 1):
            a, b = local[i], local[i + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L < 0.05 or min(abs(dx), abs(dy)) > 0.02:
                continue
            if 0.8 <= L <= 3.0:
                # 两个走向都收：`stairs._segs_from` 按 axis 各取一半
                # （旧实现只收 |dx|>=|dy|，东西向梯段整栋漏检）
                segs.append([(a[0], a[1]), (b[0], b[1])])
    from . import stairs as _stairs
    return _stairs.wells_of(segs)


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
