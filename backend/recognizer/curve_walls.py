# -*- coding: utf-8 -*-
"""斜墙 / 曲墙的「方向无关」墙皮配对。

背景: geometry.pair_wall_faces 只在轴对齐段上工作——它把每段按
`abs(dx) >= abs(dy)` 塞进「水平/垂直」两桶, 再用同一坐标轴上的间距配对。
`_flatten_wall_segments` 更直接: `min(|dx|,|dy|) > 0.02` 的段(斜段)**全部丢弃**。
于是 classify 把弧离散出来的短弦、以及图上本来就有的斜墙, 到这一步全部消失 ——
这是「斜墙/曲墙识别不出来」的根因。

本模块只做两件事, 且**不改动既有函数**:
  _flatten_all_segments(wall_pts) -> (axis_segs, diag_segs)
      与 _flatten_wall_segments 同样的拆分, 但把斜段单独返回而不是丢掉。
  pair_curved_faces(segs, p) -> (rects, singles)
      同一套配对判据(近似平行 + 垂距∈[wall_min,wall_max] + 投影重叠>0.3m), 但用
      线段自身方向做投影; 墙矩形 = 重叠区间两端在两条线上落点围成的四边形。
      弧墙由一串小梯形拼成, 斜墙是一块平行四边形。

调用方(如 _wall_thin_batch)按楼开关决定是否启用, 不启用的楼一个字节都不变。
"""
import math

from shapely.geometry import Polygon

# 与 _flatten_wall_segments 一致: 任一方向增量 <= 此值(米)即算「轴对齐」
AXIS_TOL = 0.02


def _flatten_all_segments(wall_pts):
    """把墙折线拆成 2 点直段, 按轴对齐/斜段分两桶返回。轴桶与旧版逐段一致。"""
    axis, diag = [], []
    for pts in wall_pts:
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            if math.hypot(bx - ax, by - ay) < 1e-6:
                continue
            seg = ((float(ax), float(ay)), (float(bx), float(by)))
            if min(abs(bx - ax), abs(by - ay)) > AXIS_TOL:
                diag.append(seg)
            else:
                axis.append(seg)
    return axis, diag


def pair_curved_faces(segs, p, angle_tol_deg=12.0, min_overlap=0.3):
    """方向无关的墙皮配对。返回 (rects, singles)。

    rects = [(Polygon, 厚度)]; singles = [[(x,y),(x,y)]] 未配上的单线段。
    判据与轴对齐版对齐: 近似平行、垂距 ∈ [wall_min, wall_max]、投影重叠 > min_overlap。
    """
    items = []
    for pts in segs:
        if len(pts) != 2:
            continue
        (x0, y0), (x1, y1) = pts
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1e-6:
            continue
        u = ((x1 - x0) / L, (y1 - y0) / L)
        n = (-u[1], u[0])
        items.append({"p0": (x0, y0), "p1": (x1, y1), "u": u, "n": n, "L": L,
                      "m": ((x0 + x1) / 2.0, (y0 + y1) / 2.0)})

    cos_tol = math.cos(math.radians(angle_tol_deg))
    used = [False] * len(items)
    rects, singles = [], []

    def _proj(pt, base, u):
        return (pt[0] - base[0]) * u[0] + (pt[1] - base[1]) * u[1]

    for i in range(len(items)):
        if used[i]:
            continue
        a = items[i]
        best = None      # (厚度, j)
        for j in range(len(items)):
            if j == i or used[j]:
                continue
            b = items[j]
            if abs(a["u"][0] * b["u"][0] + a["u"][1] * b["u"][1]) < cos_tol:
                continue
            # 垂距: b 中点在 a 法线上的投影
            d = abs((b["m"][0] - a["m"][0]) * a["n"][0]
                    + (b["m"][1] - a["m"][1]) * a["n"][1])
            if not (p.wall_min <= d <= p.wall_max):
                continue
            # 沿 a 的投影重叠
            t0 = _proj(b["p0"], a["p0"], a["u"])
            t1 = _proj(b["p1"], a["p0"], a["u"])
            lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
            ov = min(a["L"], hi) - max(0.0, lo)
            if ov <= min_overlap:
                continue
            if best is None or d < best[0]:
                best = (d, j)
        if best is None:
            used[i] = True
            singles.append([a["p0"], a["p1"]])
            continue
        t, j = best
        used[i] = used[j] = True
        b = items[j]
        # 重叠区间 → a 上两点, 再投到 b 上得另外两点 → 四边形
        los = max(0.0, _proj(b["p0"], a["p0"], a["u"]))
        his = min(a["L"], max(_proj(b["p1"], a["p0"], a["u"]), los))
        A0 = (a["p0"][0] + los * a["u"][0], a["p0"][1] + los * a["u"][1])
        A1 = (a["p0"][0] + his * a["u"][0], a["p0"][1] + his * a["u"][1])
        s0 = _proj(A0, b["p0"], b["u"])
        s1 = _proj(A1, b["p0"], b["u"])
        B0 = (b["p0"][0] + s0 * b["u"][0], b["p0"][1] + s0 * b["u"][1])
        B1 = (b["p0"][0] + s1 * b["u"][0], b["p0"][1] + s1 * b["u"][1])
        poly = Polygon([A0, A1, B1, B0])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 1e-4:
            singles.append([a["p0"], a["p1"]])
            continue
        rects.append((poly, t))
    return rects, singles


def _annular(c, r_in, r_out, a0, a1, sag_mm):
    """环形扇区闭合多边形(mm)：外弧 a0→a1 逆时针, 再接内弧 a1→a0 回来。

    离散步长由「弦到弧的最大偏差 = sag_mm」反解(不是弦长), 所以半径越大段越长、
    精度恒定。c = 圆心(mm), r_in/r_out = 内/外皮半径(mm), a0/a1 = 角度(度)。
    """
    def step(r):
        v = max(-1.0, min(1.0, 1.0 - sag_mm / r))
        return max(math.degrees(2.0 * math.acos(v)), 0.5)

    pts = []
    n = max(1, int(math.ceil((a1 - a0) / step(r_out))))
    for k in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * k / float(n))
        pts.append((c[0] + r_out * math.cos(a), c[1] + r_out * math.sin(a)))
    n = max(1, int(math.ceil((a1 - a0) / step(r_in))))
    for k in range(n, -1, -1):
        a = math.radians(a0 + (a1 - a0) * k / float(n))
        pts.append((c[0] + r_in * math.cos(a), c[1] + r_in * math.sin(a)))
    try:
        P = Polygon(pts)
        if not P.is_valid:
            P = P.buffer(0)
    except Exception:
        return None
    return None if P.is_empty else P


def pair_arc_bands(arcs, p, sag_mm=10.0):
    """ARC 实体（曲墙）按「同圆心 + 半径差 = 墙厚」配内外皮, 直接生成环形墙带。

    为什么不用 pair_curved_faces: 那是「弦段级」贪心配对, 两皮弧的角向分割不齐时
    会把一堵墙拆成 240/100 混厚(c006 实测 52 块 + 30 条单线)。而图纸约定是明确的:
    曲墙 = 一对同心弧, 半径差 = 墙厚(c006 逸夫楼实测 8298.9/8538.9, 差 240mm 整)。
    按约定配对 → 厚度精确、几何按弧算、不受贪心顺序影响。

    arcs = [(cx, cy, r, a0_deg, a1_deg)] 图纸毫米坐标。返回 [(Polygon, 厚度 m)]，
    Polygon 为毫米坐标(与其它 wall_pts 同口径, 由调用方 to_local)。
    """
    items = []
    for cx, cy, r, a0, a1 in arcs:
        d = (a1 - a0) % 360.0
        if d < 1e-6:
            continue
        items.append({"c": (cx, cy), "r": r, "a0": a0, "a1": a0 + d})
    groups = {}
    for it in items:
        groups.setdefault((round(it["c"][0]), round(it["c"][1])), []).append(it)

    lo = p.wall_min * 1000.0
    hi = p.wall_max * 1000.0
    bands = []
    for key in groups:
        g = sorted(groups[key], key=lambda t: t["r"])
        used = [False] * len(g)
        for i in range(len(g)):
            if used[i]:
                continue
            for j in range(i + 1, len(g)):
                if used[j]:
                    continue
                dr = g[j]["r"] - g[i]["r"]
                if dr < lo:
                    continue
                if dr > hi:
                    break                      # 半径已排序, 再往后只会更厚
                t0 = max(g[i]["a0"], g[j]["a0"])
                t1 = min(g[i]["a1"], g[j]["a1"])
                if t1 - t0 < 1e-6:             # 两皮无角向重叠 = 不是同一段墙
                    continue
                P = _annular((float(key[0]), float(key[1])),
                             g[i]["r"], g[j]["r"], t0, t1, sag_mm)
                if P is None or P.area <= 1.0:
                    continue
                bands.append((P, dr / 1000.0))
                used[i] = used[j] = True
                break
    return bands
