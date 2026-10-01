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

    **单线段也要过 `single_min_len`**（与 `pair_wall_faces` 同一条铁律）。原先这里不过滤，
    于是图上「墙端头封口线 / 门垛 / 斜向短符号」被一条条 buffer 成 0.10m 薄墙：全库干跑
    （`_scratch/_a_dryrun_curve_all.py`）c018 每层 158 → 418 条内墙，**418 正是
    `single_min_len` 那道修复之前的旧数字**（见 geometry.py:246 的判例），等于把修好的病
    从斜段这条侧门又放回来。长度用段自身的 L（斜段没有「沿轴投影」这回事）。
    """
    min_len = getattr(p, "single_min_len", 0.35)
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
    rects, singles = [], []

    def _proj(pt, base, u):
        return (pt[0] - base[0]) * u[0] + (pt[1] - base[1]) * u[1]

    def _ov(a, b):
        """b 在 a 方向上的投影落在 a 上的长度（沿 a 的局部坐标，再夹到 [0, a.L]）。"""
        t0 = _proj(b["p0"], a["p0"], a["u"])
        t1 = _proj(b["p1"], a["p0"], a["u"])
        lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
        return min(a["L"], hi) - max(0.0, lo)

    # ① 收齐合法候选（近似平行 + 垂距∈[wall_min,wall_max] + 投影重叠>min_overlap），
    #    ② 按「重叠长 > 垂距近」全局贪心取优。
    #    与 `pair_wall_faces` 同一条铁律（那边 200~229 行写明了判例）：**先比重叠、再比距离**。
    #    逐段「就近取优」会让贴着墙画的短符号段先挑走真墙皮的 mate，一根墙被劈成两根、
    #    中间留一条空槽（c018 每层 14 处、六层 168 根）。斜段这边同样是贪心，必须同规矩。
    cand = []
    for i in range(len(items)):
        a = items[i]
        for j in range(i + 1, len(items)):
            b = items[j]
            if abs(a["u"][0] * b["u"][0] + a["u"][1] * b["u"][1]) < cos_tol:
                continue
            # 垂距: b 中点在 a 法线上的投影
            d = abs((b["m"][0] - a["m"][0]) * a["n"][0]
                    + (b["m"][1] - a["m"][1]) * a["n"][1])
            if not (p.wall_min <= d <= p.wall_max):
                continue
            ov = _ov(a, b)
            if ov <= min_overlap:
                continue
            cand.append((-ov, d, i, j))
    cand.sort()

    paired = set()
    for _, _d, i, j in cand:
        if i in paired or j in paired:
            continue
        paired.add(i)
        paired.add(j)
        a, b = items[i], items[j]
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
            # 配对结果退化（两皮几乎共线/零重叠）：此处两条都已进 `paired`，直接 continue
            # 就是**连人带己一起丢**（旧写法就是如此）。退回单线段，一条都不许凭空消失。
            for it in (a, b):
                if it["L"] >= min_len:
                    singles.append([it["p0"], it["p1"]])
            continue
        rects.append((poly, _d))

    # 剩下没配上的逐条兜底。短于 single_min_len 的不是墙（墙端封口/门垛），直接丢。
    for i, a in enumerate(items):
        if i in paired or a["L"] < min_len:
            continue
        singles.append([a["p0"], a["p1"]])
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
        # ★ 单皮兜底（2026-09-14 c006 实测）：图纸上有些层的曲墙**只画一皮**
        #   （A 翼 F0/F1 的 r=8.30 就没有配对的 r=8.54，B 翼同层却有）。
        #   旧实现把它静默丢掉 → 那两层的弧形外墙整段没有，楼板在弧线处露空
        #   （反向量具：F0 楼板外环 9.1% 的点离最近墙 >0.35m，最远 6.26m @(-31.5,-33.1)）。
        #   按中心线生成环带，厚度用 profile.wall_fallback×2（外墙口径），与单线墙一致。
        for i in range(len(g)):
            if used[i]:
                continue
            used[i] = True
            _t = float(getattr(p, "wall_fallback", 0.15)) * 2.0
            _it = g[i]
            try:
                _P = _annular((float(key[0]), float(key[1])),
                              _it["r"] - _t * 500.0, _it["r"] + _t * 500.0,
                              _it["a0"], _it["a1"], sag_mm)
            except Exception:
                continue
            if _P is None or _P.area <= 1.0:
                continue
            bands.append((_P, _t))
    return bands
