# -*- coding: utf-8 -*-
"""门符号判据（**唯一一份**）—— 档案 `drawing` → 「这条墙层折线是不是门符号」。

★ 2026-10-19 查 c005「原始图不对」时挖出来的真问题：原先 `recognize.wall_segments`
  与 `overlay_check.raw_struct_segs` 各自写死「墙层折线 ≥16 点 ⇒ 门符号」。
  芙蓉园/银杏园这一族图正好反过来：**门符号 14 点、真墙链 22 点** ——
  c034 2 层实测 40 条真墙链被当门丢掉（模型里没有内墙），78 个门符号反被当墙留着。
  两处同时错还让覆盖判据**看不见**缺失（分母同样丢了那些墙 —— 铁律 192）。

★ 尚未收口：`redraw.door_candidates` 里**还留着同一套四条判定的第二份拷贝**
  （2026-10-19 批量重建跑着，没敢中途改它）。两份目前逐条同口径（`<1e-9` 与 `<1e-6`
  的 bulge 阈值差在这里量不出差别）；下次动 redraw 时应收成调用本谓词。

判据与 `redraw.door_candidates` 逐条同口径：
  · 点数 ≥ `doors_min_pts`（档案没写 = 16）；
  · `doors_need_arc` 为真 ⇒ 至少一段非零 bulge；
  · `doors_width_mm` ⇒ 外包长边落在 [lo, hi]；
  · `doors_shape_ratio` ⇒ 短边/长边 ≥ ratio。
★ 后三项档案一件都没写的楼（c005/c001）**保持老口径「≥16 点」**，既有读数不变。
★ 盲区：只按 bbox 和点数判，不判「是否贴墙」；一条恰好近方形、落在门宽窗内、
  又带一段弧的**短曲墙**会被当门跳过（本仓 376 层实测 0 例）。
"""
from __future__ import annotations


def make_predicate(drawing):
    """`drawing` = 楼栋档案的 `drawing` 段 → `is_door(xs, ys, has_arc) -> bool`。"""
    d = drawing or {}
    mp = int(d.get("doors_min_pts", 16))
    ww = d.get("doors_width_mm") or None
    ratio = float(d.get("doors_shape_ratio") or 0.0)
    need_arc = bool(d.get("doors_need_arc", False))
    shaped = bool(ww or ratio or need_arc)
    if ww:
        ww = (float(ww[0]), float(ww[1]))

    def is_door(xs, ys, has_arc):
        # 老口径：档案没写形状三项 ⇒ 就是「≥16 点」（c005/c001 原样）
        if not shaped:
            return len(xs) >= 16
        if len(xs) < mp:
            return False
        if need_arc and not has_arc:
            return False
        if not xs or not ys:
            return False
        long_ = max(max(xs) - min(xs), max(ys) - min(ys))
        short = min(max(xs) - min(xs), max(ys) - min(ys))
        if ww and not (ww[0] <= long_ <= ww[1]):
            return False
        if ratio and (long_ <= 0 or short / long_ < ratio):
            return False
        return True

    return is_door


def door_symbol_geom(doc, drawing):
    """墙层上属于**门符号**的几何：开启弧 + 与弧配对的扇线。→ (弧键集, 扇线键集)

    ★ 2026-10-20 从 `recognize.door_symbol_geom` **搬到这里**（口径不变，一字未改）：
      反查 c004 时发现覆盖判据把**门扇线**当成「必须被墙盖住的原始墙」，
      1 层覆盖率因此被拉到 0.808（真值 0.847 同因）。`overlay_check` 也要用这份判据，
      而它不能 import recognize（recognize 在 import 期就把**本进程的**档案读死了）。
      ⇒ 判据只留这一份，`recognize` 变成薄包装（铁律 174：同一个量不许两个估计器）。

    `drawing` = 楼栋档案的 `drawing` 段；没有 `doors_arc_r_mm` 的图（symbols/block 62+ 栋）
    直接返回空集 —— 整段不执行，逐位不变。
    判据：ARC 半径落在档案窗内 = 开启弧；另有一条 LINE/折线段**长度 = 半径**
    且**一端落在弧心上** ⇒ 扇线（实测 c004 1 层 26/26 配上、0 条误配）。
    """
    import math

    d = drawing or {}
    rs = [float(x) for x in (d.get("doors_arc_r_mm") or [])]
    if not rs:
        return set(), set()
    lo, hi = min(rs), max(rs)
    tol = float(d.get("doors_arc_tol_mm", 100.0))
    arcs = [e for e in doc.modelspace()
            if e.dxftype() == "ARC" and lo <= e.dxf.radius <= hi]
    if not arcs:
        return set(), set()
    arc_keys = set()
    for e in arcs:
        c, r = e.dxf.center, e.dxf.radius
        arc_keys.add((round(c[0], 1), round(c[1], 1), round(r, 1)))
    leaf_keys = set()
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "LINE":
            a, b = e.dxf.start, e.dxf.end
            pairs = [((a.x, a.y), (b.x, b.y))]
        elif t == "LWPOLYLINE":
            # ★ 逐段判（c004 有一条 13 点多段线把「柱子矩形 + 扇线」画在一起）
            pts = list(e.get_points("xyseb"))
            pairs = [((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]))
                     for i in range(len(pts) - 1) if abs(pts[i][4]) < 1e-9]
            if e.closed and len(pts) > 2 and abs(pts[-1][4]) < 1e-9:
                pairs.append(((pts[-1][0], pts[-1][1]), (pts[0][0], pts[0][1])))
        else:
            continue
        for p, q in pairs:
            ln = math.hypot(q[0] - p[0], q[1] - p[1])
            for ce in arcs:
                c, r = ce.dxf.center, ce.dxf.radius
                if abs(ln - r) > tol:
                    continue
                if (math.hypot(p[0] - c[0], p[1] - c[1]) <= tol
                        or math.hypot(q[0] - c[0], q[1] - c[1]) <= tol):
                    leaf_keys.add((round(p[0], 1), round(p[1], 1),
                                   round(q[0], 1), round(q[1], 1)))
                    leaf_keys.add((round(q[0], 1), round(q[1], 1),
                                   round(p[0], 1), round(p[1], 1)))
                    break
    return arc_keys, leaf_keys


def from_profile(bid):
    """按楼栋号取谓词（读不到档案 ⇒ 老口径，与 recognize 的默认一致）。"""
    try:
        import building as B
        return make_predicate((B.profile(bid).get("drawing") or {}))
    except Exception:
        return make_predicate({})
