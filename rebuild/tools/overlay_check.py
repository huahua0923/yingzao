# -*- coding: utf-8 -*-
"""叠加比对判据 —— **生成件轮廓 vs 原始 CAD 墙/柱** 的唯一实现。

用户 2026-10-19：「这个dxf是生成的，原始的也要同时显示，这样比对就知道哪里有问题了」
                「叠加比对后，你要作为判据」。

★ 为什么不是「看一眼图」：肉眼看图只能看见**这一屏**，说不出哪一层、哪个方向、
  差多少；同一个比对一旦由程序量，就能当判据（工作台矩阵 + 逐层红点定位）。
★ 本文件是**唯一实现**：闸 `gates/J-10.8-04_overlay.py` 与服务端 `/api/dxf/compare`
  都调它 —— 不许服务端另写一份 JS 距离（铁律 174：同一个量两个估计器必有一个错）。

量的是什么：
  · 生成侧：`06_su/contours/<层>.dxf` 的 **WALL / COL** 两类环（结构面）；
  · 原始侧：`01_cad/raw/<层>.dxf` 的**墙层线段 + 柱层几何**（同坐标系，raw 是从源图按窗裁的）。
  · 两个方向各一个率：
      ① `贴源率` = 生成件上的采样点里，距最近原始结构线 ≤ TOL 的比例
                   （生成的东西必须落在图上画过的地方 ⇒ 抓「凭空多出来的墙」）；
      ② `源图覆盖` = 原始结构线上的采样点里，距最近生成件边 ≤ TOL 的比例
                   （图上画过的墙必须被生成件盖上 ⇒ 抓「墙体缺失」，用户报的那一类）。
                   覆盖源 = 生成侧 **WALL + COL + STAIR + ROOF + PARAPET**（原始墙层上画着
                   踏步线和屋面/女儿墙轮廓，只拿 WALL/COL 会把楼梯间与顶层屋面报成缺墙：
                   c006 7 层假低 13 个点、c005 5 层假低到 0.843，均 2026-10-19 实测）。
  · 还给出中位距 / P95 距，便于判断阈值是不是被一批系统性偏移顶穿的。

量具盲区（**声明**，否定判词必须带）：
  · 原始侧**跳过**墙层 INSERT（门符号块）与**门弧**（几何判据：半径 ≤3000 且张角 60~120°，
    见 `_is_door_arc`）。墙层上的曲墙 ARC / 圆柱 CIRCLE **算参照**（不跳），
    否则整栋曲线的楼（c105）会被报成大面积缺失。柱层 INSERT 会 explode。
    `doors="symbols"` 的图把门画成 ≥16 点多段线，本模块也跳过它（与
    `recognize.wall_segments` 同一条经验规则，但**不是同一份代码**）。
  · 折线上的 **bulge（弧段）按真实弧长展开**（2026-10-19 修正；按弦取点会把
    曲墙两侧互相报成「没贴上」，c041 6 层实测假低到 0.907）。
  · 只量 **WALL / COL**：楼板、门、梯、门头墙不在本判据里（它们的真值另有闸）。
  · 原始件是**按窗裁**的：窗外的墙本来就不在 raw 里，不会被算成缺失。
  · 只量**距离**，不量**拓扑**：墙带归并错、把房间并成一条，两个方向都可能仍是高比例。
"""
from __future__ import annotations

import math
import os
import sys
from collections import Counter

# `-I`（隔离模式）不把脚本目录放进 sys.path ⇒ 这里显式补一次（与 redraw.py 同法）
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ezdxf
import numpy as np
import shapely
import door_rule as DR
from shapely import STRtree
from shapely.geometry import LineString

# 采样步长（mm）与默认容差（mm）。★ 阈值来源见 main 的实测分布，不凭空定。
STEP_MM = 100.0
TOL_MM = 300.0
# 每条边最多采几个点（防止一条超长线把采样表撑爆）
MAX_PER_EDGE = 2000
# 回传的「未贴」片段上限（页面高亮用；计数永远是全量的）
SHOW_MAX = 80
# 覆盖方向的**生成侧类别**：原始墙层上的线不一定长成 WALL。
#   STAIR  —— 楼梯踏步画在墙层（c006 7 层因此假低 13 个点）；
#   ROOF / PARAPET —— 顶层图上把下层屋面/女儿墙画在墙层，而生成件把它们归成这两类
#                     （c005 5 层因此假低到 0.843，2026-10-19 实测 8 条 17~29 m 的长边全是屋面轮廓）。
#   ★ 贴源方向**不用**这张表：生成的台阶/屋面不该被要求落在一堵「墙」上。
COVER_KINDS = ("WALL", "COL", "STAIR", "ROOF", "PARAPET")


def _edges(pts, closed):
    out = []
    n = len(pts)
    for i in range(n - 1):
        out.append((pts[i], pts[i + 1]))
    if closed and n > 2:
        out.append((pts[-1], pts[0]))
    return out


def _sample(segs, step=STEP_MM):
    """把线段表采样成点表（端点必采，中间按 step 插）。"""
    xs, ys = [], []
    for (x1, y1), (x2, y2) in segs:
        xs.append(x1)
        ys.append(y1)
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy)
        if d < 1e-9:
            continue
        k = min(int(d // step), MAX_PER_EDGE)
        for i in range(1, k + 1):
            t = i / (k + 1)
            xs.append(x1 + dx * t)
            ys.append(y1 + dy * t)
    return xs, ys


def _ladder_count(segs):
    """每条线段是「等距、等长、同向的一排线」里的第几条（0 = 不成排）。

    ★ 用户 2026-10-20：「除去门以外，墙的覆盖率为啥低」。实测：覆盖率低的大头
      不是墙建歪了，而是**图上的台阶/踏步线**（画在墙层）—— 它们成排、等距
      300~350 mm、两端对齐，模型按墙/楼板建，本来就没有对应的墙。
    ★ 判据要能分开「成排踏步」与「双线墙」：只数等距兄弟会把 240 厚的双线墙、
      一排柱子都算进来（c036 3 层实测 9.69 m 外墙、240 见方柱被误判）。
      因此三个条件同时成立才算一排：①同向（≤2°）；②间距落在 150~450 mm 的
      **同一等距网格**上（误差 ≤30 mm）；③**两端对齐**（沿向两个端点各差 ≤200 mm）。
    ★ 盲区（否定判词必须带）：弯折踏步（转折梯）、斜梯段只有在同一方向上的
      那几条会成排；成排的平行管线/龙骨在图上也长这样。
    """
    from shapely.geometry import LineString as _LS
    gs = [_LS(s) for s in segs]
    if not gs:
        return []
    tr = STRtree(gs)
    out = [0] * len(gs)
    for i, g in enumerate(gs):
        if g.length < 200:
            continue
        x1, y1 = g.coords[0]
        x2, y2 = g.coords[1]
        ux, uy = (x2 - x1) / g.length, (y2 - y1) / g.length
        offs = []
        for j in tr.query(g, predicate="dwithin", distance=1300.0):
            j = int(j)
            if j == i:
                continue
            h = gs[j]
            if h.length < 200:
                continue
            vx = h.coords[1][0] - h.coords[0][0]
            vy = h.coords[1][1] - h.coords[0][1]
            vx, vy = vx / h.length, vy / h.length
            if abs(ux * vy - uy * vx) > math.sin(math.radians(2)):
                continue
            d = (h.coords[0][0] - x1) * uy - (h.coords[0][1] - y1) * ux
            if not (150.0 <= abs(d) <= 1300.0):
                continue
            b0 = (h.coords[0][0] - x1) * ux + (h.coords[0][1] - y1) * uy
            b1 = (h.coords[1][0] - x1) * ux + (h.coords[1][1] - y1) * uy
            b0, b1 = min(b0, b1), max(b0, b1)
            if abs(b0) > 200.0 or abs(b1 - g.length) > 200.0:
                continue
            offs.append(abs(d))
        cand = [o for o in offs if 150.0 <= o <= 450.0]
        if not cand:
            continue
        s = min(cand)
        ks = {round(o / s) for o in offs if abs(o - round(o / s) * s) <= 30.0}
        ks.discard(0)
        if len(ks) >= 2:                 # 自己 + 至少 2 条等距等长的兄弟 ⇒ 一排 ≥3 条
            out[i] = max(ks) + 1
    return out


def _layer_pick(cnt, kind):
    """原始件里挑墙层 / 柱层（与档案同一经验规则；raw 已裁过，直接在这份文件里数）。"""
    if kind == "wall":
        cand = [n for n in cnt if "墙体" in n] or [n for n in cnt if n.endswith("墙")]
    else:
        cand = [n for n in cnt if "柱" in n]
    if not cand:
        return ""
    return max(cand, key=lambda n: cnt[n])


def _arc_span_pts(c, r, a0, a1, step=STEP_MM):
    """圆心 + 起止角（弧度）→ 弧上折线点。"""
    if a1 <= a0:
        a1 += 2 * math.pi
    k = max(2, min(int(r * (a1 - a0) // step), MAX_PER_EDGE))
    return [(c.x + r * math.cos(a0 + (a1 - a0) * i / k),
             c.y + r * math.sin(a0 + (a1 - a0) * i / k)) for i in range(k + 1)]


def _poly_segs(e):
    """LWPOLYLINE → 线段表，**bulge（弧段）按弧展开**，不按弦。

    ★ 2026-10-19：c041 6 层 贴源率 0.907，红的两处正是曲墙 —— 生成件与原始件
      都把弧画成 bulge，按弦取值时弦中点离真实弧线可达数百 mm（半径越大越明显），
      于是同一栋楼两个方向互相「没贴上」。这是量具的盲区，不是模型的缺陷。
    """
    pts = list(e.get_points("xyb"))
    out = []
    n = len(pts)
    for i in range(n - 1 if not e.closed else n):
        x1, y1, b = pts[i]
        x2, y2, _ = pts[(i + 1) % n]
        if abs(b) > 1e-9:
            try:
                from ezdxf.math import bulge_to_arc
                c, a0, a1, r = bulge_to_arc((x1, y1), (x2, y2), b)
                ap = _arc_span_pts(c, r, a0, a1)
                out.extend(_edges(ap, False))
                continue
            except Exception:
                pass                      # 算不出就退回弦（与旧行为一致）
        out.append(((x1, y1), (x2, y2)))
    return out


def _circle_pts(c, r, n=16):
    return [(c.x + r * math.cos(2 * math.pi * i / n),
             c.y + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _arc_pts(e, step=STEP_MM):
    """ARC → 折线点（按弧长采样）。★ 曲线的墙不许被当成「没画」。"""
    return _arc_span_pts(e.dxf.center, e.dxf.radius,
                          math.radians(e.dxf.start_angle),
                          math.radians(e.dxf.end_angle), step)


def _is_door_arc(e):
    """门弧判据（几何，不靠档案）：**半径小 + 张角像一扇门**。

    ★ 2026-10-19 实测：c006 1 层墙层 12 条 ARC 半径 8299 / 张角 45°、c105 54 条
      半径 29~41 m / 张角 24~36° —— 这些是**曲墙**，原来「墙层上 ARC 一律当门弧跳过」
      把它们整段丢出参照 ⇒ c105 3 层贴源率假低到 0.857。门弧实测半径 451~600、
      张角 84~90°（c001 3 条 90°），用 r≤3000 & 60°≤张角≤120° 分得开。
    """
    span = (e.dxf.end_angle - e.dxf.start_angle) % 360
    return e.dxf.radius <= 3000.0 and 60.0 <= span <= 120.0


def _insert_edges(e, out):
    """柱块展开成边（只取 LINE / LWPOLYLINE / CIRCLE；CIRCLE 用 16 边形近似）。"""
    try:
        sub = list(e.explode())
    except Exception:
        return
    for s in sub:
        t = s.dxftype()
        if t == "LINE":
            a, b = s.dxf.start, s.dxf.end
            out.append(((a.x, a.y), (b.x, b.y)))
        elif t == "LWPOLYLINE":
            out.extend(_poly_segs(s))
        elif t == "CIRCLE":
            out.extend(_edges(_circle_pts(s.dxf.center, s.dxf.radius), True))


def raw_struct_segs(path, door_mode="block", drawing=None, steps=None):
    """原始件的结构边（墙层线段 + 柱层几何）。返回 (segs, meta)。

    `steps`：档案 `台阶` 的矩形表（mm）。**用户 2026-10-18 明令**「台阶从墙带扣掉」，
    所以台阶区里的原始线**本来就不该有对应墙**；原样进参照会让覆盖率永远够不着阈值
    （c004 1 层实测：缺 80.5 m 里 46.6 m 全在台阶区）。只有**两端都落在矩形内**的线才排除，
    穿过的墙照留（不拿矩形当遮罩）。

    ★ `door_mode` 必须与 `recognize.WALL_SEG` 同口径：**只有** `doors="symbols"` 的图
      才跳门符号折线（c006 是 `block`，它墙层上的 20 点多段线是**真墙**；
      无条件跳会把真墙报成「生成件凭空多出来」——2026-10-19 实测 c006 1 层因此假红 9%）。
    ★★ 2026-10-19：门符号的**判据本身**也与 `recognize.wall_segments` 共用
      `door_rule.make_predicate`（点数 + 宽度窗 + 近方形 + 必须带弧）。原先这里写死
      「≥16 点」—— c034 2 层 40 条真墙链（22 点）因此从**分母里**被删掉，
      覆盖判据看不见「模型没有内墙」（铁律 192）。`drawing=None` 时退回老口径。
    """
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    cnt = Counter(e.dxf.layer for e in msp)
    wall = _layer_pick(cnt, "wall")
    col = _layer_pick(cnt, "column")
    segs = []
    n_skip_arc = n_skip_poly = n_skip_block = n_skip_leaf = 0
    _is_door_poly = DR.make_predicate(drawing) if drawing is not None else None
    # ★★ 2026-10-20（反查 c004 实测）：**门扇线也是「原始墙」的假成员**。
    #   c004 的门画成「开启弧 + 扇线」，扇线落在墙层上，原样进参照 ⇒ 要求生成件盖住它，
    #   可那里本来就是门洞。1 层覆盖率 0.808（红）的主因就是它，不是漏墙。
    #   判据用 `door_rule.door_symbol_geom`（与生成侧**同一份**，档案 doors_arc_r_mm 驱动）；
    #   只按**键**跳过（弧心 + 半径 + 端点逐位对上），不做长度启发式 ⇒ 不误伤真墙。
    _leaf_keys = DR.door_symbol_geom(doc, drawing or {})[1]

    def _is_leaf(p, q):
        return (round(p[0], 1), round(p[1], 1),
                round(q[0], 1), round(q[1], 1)) in _leaf_keys

    _steps = [tuple(r) for r in (steps or []) if len(r) == 4]
    n_skip_step = 0

    def _in_steps(p, q):
        for (x0, y0, x1, y1) in _steps:
            if (x0 <= p[0] <= x1 and y0 <= p[1] <= y1
                    and x0 <= q[0] <= x1 and y0 <= q[1] <= y1):
                return True
        return False

    for e in msp:
        lay = e.dxf.layer
        t = e.dxftype()
        if lay == wall:
            if t == "LINE":
                a, b = e.dxf.start, e.dxf.end
                if _leaf_keys and _is_leaf((a.x, a.y), (b.x, b.y)):
                    n_skip_leaf += 1
                    continue
                if _steps and _in_steps((a.x, a.y), (b.x, b.y)):
                    n_skip_step += 1
                    continue
                segs.append(((a.x, a.y), (b.x, b.y)))
            elif t == "LWPOLYLINE":
                p5 = list(e.get_points("xyb"))
                pts = [(q[0], q[1]) for q in p5]
                # symbols 模式：与 recognize.wall_segments **同一判据**（door_rule）。
                # 没有档案 `drawing` 时退回老口径「≥16 点」。
                if door_mode == "symbols":
                    hit = (_is_door_poly([q[0] for q in pts], [q[1] for q in pts],
                                         any(abs(q[2]) > 1e-9 for q in p5))
                           if _is_door_poly is not None else len(pts) >= 16)
                    if hit:
                        n_skip_poly += 1
                        continue
                _ps = _poly_segs(e)
                if _leaf_keys:
                    _keep = [s for s in _ps if not _is_leaf(*s)]
                    n_skip_leaf += len(_ps) - len(_keep)
                    _ps = _keep
                if _steps:
                    _keep = [s for s in _ps if not _in_steps(*s)]
                    n_skip_step += len(_ps) - len(_keep)
                    _ps = _keep
                segs.extend(_ps)
            elif t == "ARC":
                if _is_door_arc(e):
                    n_skip_arc += 1       # 门扇开启弧
                    continue
                segs.extend(_edges(_arc_pts(e), False))   # 曲墙
            elif t == "CIRCLE":
                segs.extend(_edges(_circle_pts(e.dxf.center, e.dxf.radius), True))  # 圆柱
            elif t == "INSERT":
                n_skip_block += 1     # 门符号块
        elif lay == col:
            if t == "LINE":
                a, b = e.dxf.start, e.dxf.end
                segs.append(((a.x, a.y), (b.x, b.y)))
            elif t == "LWPOLYLINE":
                segs.extend(_poly_segs(e))
            elif t == "INSERT":
                _insert_edges(e, segs)
            elif t == "CIRCLE":
                segs.extend(_edges(_circle_pts(e.dxf.center, e.dxf.radius), True))
    meta = {"墙层": wall, "柱层": col, "段": len(segs), "门模式": door_mode,
            "跳过_门弧": n_skip_arc, "跳过_门符号折线": n_skip_poly,
            "跳过_门块": n_skip_block, "跳过_门扇线": n_skip_leaf,
            "跳过_台阶": n_skip_step}
    return segs, meta


def gen_struct_segs(path, kinds=("WALL", "COL")):
    """生成件的结构边（contours DXF 的 WALL / COL 环）。"""
    doc = ezdxf.readfile(path)
    segs = []
    for e in doc.modelspace():
        if e.dxf.layer not in kinds or e.dxftype() != "LWPOLYLINE":
            continue
        segs.extend(_poly_segs(e))
    return segs


def _nearest_dist(pts_xy, tree):
    """点表 → 最近线段距离（numpy 数组）。"""
    xs, ys = pts_xy
    if not xs or len(tree.geometries) == 0:
        return None
    geoms = shapely.points(np.asarray(xs), np.asarray(ys))
    idx = tree.nearest(geoms)
    return shapely.distance(geoms, tree.geometries[idx])


def _rate(d, tol):
    """(≤tol 的比例, 中位距, P95 距)。空表返回 (None, None, None)。"""
    if d is None or len(d) == 0:
        return None, None, None
    d = np.asarray(d, dtype=float)
    return (float((d <= tol).mean()),
            float(np.median(d)),
            float(np.percentile(d, 95)))


def _unmatched(segs, tree, tol, cap=SHOW_MAX):
    """没贴上的生成边（整条边的距离都 > tol），给页面高亮。"""
    out = []
    for (a, b) in segs:
        g = LineString([a, b])
        idx = tree.nearest(g)
        if idx is None:
            continue
        if g.distance(tree.geometries[idx]) > tol:
            out.append([round(a[0], 1), round(a[1], 1), round(b[0], 1), round(b[1], 1)])
            if len(out) >= cap:
                break
    return out


def door_mode_of(bid):
    """档案 `drawing.doors`（读不到按 block —— 与 `recognize` 的默认值一致）。"""
    try:
        import building as B
        return str(((B.profile(bid).get("drawing") or {}).get("doors")) or "block")
    except Exception:
        return "block"


def drawing_of(bid):
    """档案 `drawing` 段（门符号判据的输入）；读不到返回 None = 老口径。"""
    try:
        import building as B
        return (B.profile(bid).get("drawing") or {})
    except Exception:
        return None


def steps_of(bid):
    """档案 `台阶` 的矩形表（mm）→ [(x0, y0, x1, y1)]。

    用户 2026-10-18 令「台阶从墙带扣掉」，所以台阶矩形里的原始线**本来就不该有对应墙**。
    覆盖判据拿它当参照会把「按令扣掉」报成「漏墙」（c004 1 层实测：漏 80.5 m 里 46.6 m）。
    读不到档案 ⇒ 空表（分母不变，读数与旧版逐位一致）。
    """
    try:
        import building as B
        pr = B.profile(bid)
    except Exception:
        return []
    out = []
    for s in (pr.get("台阶") or []):
        r = s.get("rect") if isinstance(s, dict) else None
        if r and len(r) == 4:
            out.append((float(r[0]), float(r[1]), float(r[2]), float(r[3])))
    return out


def compare_floor(bid, floor, root, tol=TOL_MM, door_mode=None, drawing=None,
                  steps=None):
    """一层比对。件缺时 `ok=False` 且 `why` 说明是「没量到」（不许当成 0）。"""
    if door_mode is None:
        door_mode = door_mode_of(bid)
    if drawing is None:
        drawing = drawing_of(bid)
    if steps is None:
        steps = steps_of(bid)
    gen_p = os.path.join(root, "06_su", "contours", floor + ".dxf")
    raw_p = os.path.join(root, "01_cad", "raw", floor + ".dxf")
    rec = {"bid": bid, "floor": floor, "tol": tol, "gen": gen_p, "raw": raw_p}
    if not os.path.exists(gen_p):
        rec.update({"ok": False, "why": "生成件缺：contours/%s.dxf" % floor})
        return rec
    if not os.path.exists(raw_p):
        rec.update({"ok": False, "why": "原始件缺：01_cad/raw/%s.dxf" % floor})
        return rec
    gsegs = gen_struct_segs(gen_p)
    rsegs, rmeta = raw_struct_segs(raw_p, door_mode=door_mode, drawing=drawing,
                                   steps=steps)
    rec["raw_meta"] = rmeta
    rec["生成段"] = len(gsegs)
    rec["原始段"] = len(rsegs)
    if not gsegs:
        rec.update({"ok": False, "why": "生成件里 WALL/COL 为 0 条"})
        return rec
    if not rsegs:
        rec.update({"ok": False, "why": "原始件里墙/柱结构线为 0 条（层名：%s / %s）"
                                       % (rmeta.get("墙层"), rmeta.get("柱层"))})
        return rec
    # ★ 覆盖方向要把 **STAIR** 也算进生成侧：原始墙层上画着踏步线（同一图层），
    #   而生成侧它们是 STAIR 类、不是 WALL。只拿 WALL/COL 当覆盖源会把四个楼梯间
    #   报成「墙缺失」——2026-10-19 实测 c006 7 层因此假低 13 个百分点
    #   （0.812 → 0.945）。**贴源方向仍只认 WALL/COL**：台阶不该被要求落在墙上。
    gcov = gen_struct_segs(gen_p, kinds=COVER_KINDS)
    gtree = STRtree([LineString(s) for s in gcov])
    rtree = STRtree([LineString(s) for s in rsegs])
    gd = _nearest_dist(_sample(gsegs), rtree)
    rd = _nearest_dist(_sample(rsegs), gtree)
    g_rate, g_med, g_p95 = _rate(gd, tol)
    r_rate, r_med, r_p95 = _rate(rd, tol)
    rec.update({
        "ok": True,
        "贴源率": g_rate, "覆盖": r_rate, "覆盖段": len(gcov),
        "生成_中位距": g_med, "生成_P95距": g_p95,
        "原始_中位距": r_med, "原始_P95距": r_p95,
        "未贴边": _unmatched(gsegs, rtree, tol),
        "未贴边_总": int((np.asarray(gd) > tol).sum()) if gd is not None else None,
        "生成_点数": None if gd is None else int(len(gd)),
        "原始_点数": None if rd is None else int(len(rd)),
    })
    return rec


def _pts_dist(xy, tree):
    """点表 (xs, ys) → 到最近线段的距离（tree 为空时给 1e9）。"""
    n = len(xy[0])
    if tree is None or n == 0:
        return np.full(n, 1e9)
    geoms = shapely.points(np.column_stack(xy))
    return shapely.distance(geoms, tree.geometries[tree.nearest(geoms)])


def cov_causes(gen_p, raw_p, door_mode="block", drawing=None, steps=None, tol=TOL_MM):
    """源图覆盖率的漏点**按原因拆开**（用户 2026-10-20：「除去门以外，墙的覆盖率为啥低」）。

    与 `compare_floor` 共用同一份 `_sample` / `_nearest_dist` / `TOL_MM`，不另写尺子。
    分类**互斥**，优先序：门洞边 → 成排踏步 → 楼梯附近 → 那里没有件 → 有件但偏了。

      · 门洞边：≤300 mm 内有生成的门扇/门线 —— 洞口本来就不该有墙，量具把它算漏是口径问题；
      · 成排踏步：源线属于一排等距等长线（间距 150~450 mm）—— 台阶/踏步，不是墙；
      · 楼梯附近：≤1.5 m 内有生成踏步 —— 位置对、形状不对；
      · 那里没有件：>1 m 内什么都没有 —— **真漏**；
      · 有件但偏了：0.3~1 m 内有件 —— 墙在，位置/厚度不对。

    另给两个反向读数（抓「凭空多出来的墙」）：
      · `生成点`/`多墙点`：生成件采样点里，300 mm 内没有原始结构线的点数。

    返回 dict；任何一侧结构线为 0 时 `ok=False`（没量到 ≠ 0）。
    """
    gcov_s = gen_struct_segs(gen_p, kinds=COVER_KINDS)
    gsegs = gen_struct_segs(gen_p)
    rsegs, meta = raw_struct_segs(raw_p, door_mode=door_mode, drawing=drawing, steps=steps)
    if not gcov_s or not rsegs:
        return {"ok": False, "why": "生成件或原始件的结构线为 0（没量到，不是 0）",
                "墙层": meta.get("墙层"), "柱层": meta.get("柱层")}
    gtree = STRtree([LineString(s) for s in gcov_s])
    rtree = STRtree([LineString(s) for s in rsegs])
    dsegs = gen_struct_segs(gen_p, kinds=("DOOR",))
    ssegs = gen_struct_segs(gen_p, kinds=("STAIR",))
    dtree = STRtree([LineString(s) for s in dsegs]) if dsegs else None
    stree = STRtree([LineString(s) for s in ssegs]) if ssegs else None

    xs, ys, owner = [], [], []
    for s in rsegs:
        px, py = _sample([s])
        xs.extend(px)
        ys.extend(py)
        owner.extend([s] * len(px))
    pts = (xs, ys)                       # `_nearest_dist` 吃 list（不是 ndarray）
    dd = _nearest_dist(pts, gtree)
    bad = np.where(np.asarray(dd) > tol)[0]
    bx = [xs[i] for i in bad]
    by = [ys[i] for i in bad]
    bd = _pts_dist((bx, by), dtree)
    bs = _pts_dist((bx, by), stree)
    lad = _ladder_count(rsegs)
    sib = dict(zip(rsegs, lad))
    cnt = Counter()
    for k in range(len(bad)):
        if bd[k] <= tol:
            c = "门洞边"
        elif sib.get(owner[bad[k]], 0) >= 3:
            c = "成排"
        elif bs[k] <= 1500.0:
            c = "楼梯附近"
        elif dd[bad[k]] > 1000.0:
            c = "无件"
        else:
            c = "偏了"
        cnt[c] += 1
    gx, gy = _sample(gsegs)
    gd = _nearest_dist((gx, gy), rtree)
    n_src = len(pts[0])
    n_bad = int(len(bad))
    return {
        "ok": True, "tol": tol, "墙层": meta.get("墙层"), "柱层": meta.get("柱层"),
        "源点": n_src, "漏点": n_bad, "覆盖": 1.0 - n_bad / n_src if n_src else None,
        "门洞边": cnt["门洞边"], "成排": cnt["成排"], "楼梯附近": cnt["楼梯附近"],
        "无件": cnt["无件"], "偏了": cnt["偏了"],
        "生成点": int(len(gx)),
        "多墙点": int((np.asarray(gd) > tol).sum()) if gd is not None else None,
    }


def compare_building(bid, root=None, tol=TOL_MM, floors=None, door_mode=None):
    """一栋楼逐层比对。`floors` 为空时用档案的层名表。"""
    import building as B
    if root is None:
        root = B.root_for(bid)
    if door_mode is None:
        door_mode = door_mode_of(bid)
    if floors is None:
        pr = B.profile(bid)
        base = pr.get("basement")
        floors = ([base] if base else []) + list(pr.get("floor_names") or [])
    steps = steps_of(bid)
    rows = [compare_floor(bid, f, root, tol, door_mode=door_mode, steps=steps)
            for f in floors]
    return {"bid": bid, "root": root, "tol": tol, "门模式": door_mode, "层": rows}


def _main():
    import argparse
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--bid", default="c006")
    ap.add_argument("--tol", type=float, default=TOL_MM)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = compare_building(a.bid, tol=a.tol)
    for f in r["层"]:
        if not f["ok"]:
            print("%-8s 没量到：%s" % (f["floor"], f["why"]))
            continue
        print("%-8s 生成 %5d 段 / 原始 %5d 段  贴源 %.3f  覆盖 %.3f  "
              "P95 %.1f / %.1f mm"
              % (f["floor"], f["生成段"], f["原始段"], f["贴源率"], f["覆盖"],
                 f["生成_P95距"], f["原始_P95距"]))


if __name__ == "__main__":
    _main()
