# -*- coding: utf-8 -*-
"""判据 J-10.8-04 —— **叠加比对**：生成轮廓 vs 原始 CAD 墙/柱，两个方向各一个率。

用户 2026-10-19 明令：
  「这个dxf是生成的，原始的也要同时显示，这样比对就知道哪里有问题了。」
  「叠加比对后，你要作为判据。」

★ 为什么是闸而不是「看一眼图」：肉眼看图只说得出「这里怪」，说不出**哪一层、差多少、
  是多了还是少了**。这里把同一件事量成两个数（唯一实现在 `rebuild/tools/overlay_check.py`，
  本闸与 `/api/dxf/compare` 共用，不许另写一份 JS 距离 —— 铁律 174）：

  ① `贴源率`：生成件 WALL/COL 采样点里，距**原始**墙/柱线 ≤ 300 mm 的比例。
     抓「图上没画、生成件却有的墙」（凭空多出来的墙带 / 整体偏移）。
  ② `覆盖`：原始墙/柱采样点里，距**生成件** ≤ 300 mm 的比例。
     覆盖源 = 生成 **WALL + COL + STAIR + ROOF + PARAPET**（原始墙层上还画着踏步线和
     顶层屋面/女儿墙轮廓；只拿 WALL/COL 会把楼梯间和屋面报成缺墙 —— 2026-10-19 实测
     c006 7 层假低 13 个百分点、c005 5 层假低到 0.843）。抓「图上画了、
     生成件没盖上的墙」（用户报的墙体缺失那一类）。

阈值（★ 来源是**全仓 376 层的实测分布**，不是拍的；`_scratch/probe_overlay_all.py`，
2026-10-19 修掉 bulge 按弦取点之后重跑）：
  · `贴源率` 下限 0.95 —— 分布 min 0.956 / p01 0.976 / p05 0.988 / 中位 1.000；
    最低的 c017 地下 1 层那 2.2% 是门上方的弧形墙边（图上看得到，生成件跟着画了），不是噪声；
  · `覆盖`   下限 0.85 —— 分布 min 0.728 / p01 0.740 / p05 0.862 / 中位 0.936。
  两条线都落在长尾之外；**改阈值必须连读数一起改**（铁律 018）。

正对照（本闸必须有伪证器，铁律 137）：拿本栋**量过的一层**，把生成边整体平移
1000 mm 再量 —— 平移后必须掉到 0.95 之下。掉不下去 ⇒ 说明这把尺子对「凭空偏移」
没有分辨力，本闸的绿不作数。

盲区（**声明**，否定判词必须带 —— 铁律 158）：
  · 只量**距离**，不量**拓扑**：墙带归并错、把两个房间并成一条，两个方向可能仍是高比例。
  · 原始侧跳过墙层 INSERT（门符号块）与门弧（r≤3000 且张角 60~120°；曲墙 ARC 不跳）；
    `doors="symbols"` 的图按 **`door_rule.make_predicate`** 跳门符号折线
    （与 `recognize.wall_segments`、`redraw` 同一个判据、同一份代码 —— 2026-10-19）。
    判据只按点数/宽度窗/近方形/带弧判，不看是否贴墙：一条恰好落在门宽窗内的短曲墙
    会被当门跳过（本仓 376 层实测 0 例）。
  · 折线 bulge（弧段）按真实弧长展开；仍量不到「弧被削成多段弦且每段都小于容差」这类形制错。
  · 原始件是**按窗裁**的：窗外本来就不在 raw 里，不会被算成缺失。
  · 覆盖方向的原始源包含踏步线 ⇒ **楼梯没生成会报成「覆盖不足」**（那是真缺失，
    但判词要读成「楼梯/踏步」而不是「墙」—— 本闸在明细里给聚类坐标，不猜类型）。
  · 只读 DXF 的几何，不读文字/标注；房间名、面积标注不在量程内。
"""
from __future__ import annotations

import os
import sys
from collections import deque

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(CDUT, "rebuild", "tools"))
import _verdict as VD                                            # noqa: E402
import overlay_check as O                                        # noqa: E402
import _items as I                                               # noqa: E402

GATE = "J-10.8-04"
BID = VD.bid_from()
_P = VD.paths(BID)
RUNDIR = os.path.join(HERE, "_out")
JSON_OUT = os.path.join(RUNDIR, "%s.%s.json" % (GATE, BID))
_LOG = []

MIN_TIE = 0.95          # 贴源率下限（实测 min = 0.956，p01 = 0.976）
MIN_COV = 0.85          # 覆盖下限（实测 p05 = 0.862）
PROBE_MM = 1000.0       # 正对照平移量
CLUSTER_MM = 5000       # 覆盖缺口聚类网格
CLUSTER_TOP = 6         # 每层最多报几个缺口聚类

BLIND = [
    "只量距离不量拓扑：墙带归并错/房间并成一条，两个方向可能仍是高比例",
    "原始侧跳过墙层 INSERT（门符号）与门弧（r≤3000 且张角 60~120°），曲墙 ARC 不跳",
    "doors=\"symbols\" 的图按 door_rule.make_predicate 跳门符号折线（与 recognize 同一份代码）；"
    "判据只看点数/门宽窗/近方形/带弧，不看是否贴墙 ⇒ 恰好落在门宽窗内的短曲墙会被当门跳过（实测 0 例）",
    "覆盖方向原始源含踏步线 ⇒ 楼梯没生成会报成覆盖不足（判词按坐标给，不猜类型）",
    "原始件按窗裁：窗外不在 raw 里，不会被算成缺失",
    "只读几何不读文字：房间名/面积标注不在量程内",
    "阈值绑在 2026-10-19 全仓 376 层的分布上；上游合法地改变几何时要连读数一起改",
]


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def _cluster(points, cell=CLUSTER_MM):
    """未覆盖点 → 网格连通聚类（只用于判词定位，不参与判否）。"""
    cells = {}
    for x, y in points:
        cells[(int(x // cell), int(y // cell))] = True
    seen, comps = set(), []
    for c in cells:
        if c in seen:
            continue
        q = deque([c])
        seen.add(c)
        pts = []
        while q:
            cx, cy = q.popleft()
            pts.append((cx, cy))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (cx + dx, cy + dy)
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        q.append(nb)
        comps.append((len(pts), pts))
    comps.sort(key=lambda t: -t[0])
    out = []
    for n, pts in comps[:CLUSTER_TOP]:
        xs = [p[0] * cell for p in pts]
        ys = [p[1] * cell for p in pts]
        out.append([int(min(xs)), int(min(ys)),
                    int(max(xs) + cell), int(max(ys) + cell), n])
    return out


def _uncovered_points(floor, door, cell):
    """原始侧未覆盖点（供聚类定位；与 compare_floor 同一实现取几何）。"""
    import shapely
    from shapely import STRtree
    from shapely.geometry import LineString
    gsegs = O.gen_struct_segs(os.path.join(_P["root"], "06_su", "contours", floor + ".dxf"),
                              O.COVER_KINDS)
    rsegs, _ = O.raw_struct_segs(os.path.join(_P["root"], "01_cad", "raw", floor + ".dxf"),
                                 door_mode=door, drawing=O.drawing_of(BID))
    tree = STRtree([LineString(s) for s in gsegs])
    xs, ys = O._sample(rsegs)
    if not xs or not len(tree.geometries):
        return []
    geoms = shapely.points(xs, ys)
    d = shapely.distance(geoms, tree.geometries[tree.nearest(geoms)])
    return [(x, y) for x, y, dd in zip(xs, ys, d) if dd > O.TOL_MM]


def _positive_control(bid, floor):
    """伪证器：把生成边整体平移 PROBE_MM，贴源率必须掉到 MIN_TIE 之下。"""
    from shapely import STRtree
    from shapely.geometry import LineString
    root = _P["root"]
    gp = os.path.join(root, "06_su", "contours", floor + ".dxf")
    rp = os.path.join(root, "01_cad", "raw", floor + ".dxf")
    if not (os.path.exists(gp) and os.path.exists(rp)):
        return None
    gsegs = O.gen_struct_segs(gp)
    rsegs, _ = O.raw_struct_segs(rp, door_mode=O.door_mode_of(bid),
                                 drawing=O.drawing_of(bid))
    if not gsegs or not rsegs:
        return None
    rtree = STRtree([LineString(s) for s in rsegs])
    xs, ys = O._sample(gsegs)
    base = O._rate(O._nearest_dist((xs, ys), rtree), O.TOL_MM)[0]
    moved = [((a[0] + PROBE_MM, a[1]), (b[0] + PROBE_MM, b[1])) for a, b in gsegs]
    xs2, ys2 = O._sample(moved)
    after = O._rate(O._nearest_dist((xs2, ys2), rtree), O.TOL_MM)[0]
    return base, after


# ---------------- 判据清单（一条一个函数） ----------------
_M = {}


def _量():
    """把 main 里原样的测量循环跑一遍（**逻辑一行未改**），读数存 `_M` 供各条共用。"""
    if "_rows" in _M:
        return _M
    floors = VD.floors(BID)
    door = O.door_mode_of(BID)
    rows, fails, skipped = [], [], []
    for f in floors:
        rec = O.compare_floor(BID, f, _P["root"], door_mode=door,
                              drawing=O.drawing_of(BID))
        if not rec.get("ok"):
            skipped.append((f, rec.get("why") or "没量到"))
            continue
        rows.append(rec)
        tie, cov = rec["贴源率"], rec["覆盖"]
        if tie < MIN_TIE:
            fails.append("② %s 贴源率 %.3f < %.2f：生成件有 %s 段边落在原始图 %.0f mm 之外"
                          "（凭空多出来的墙 / 整体偏移 —— 先看工作台叠加图上的红边）"
                          % (f, tie, MIN_TIE, rec.get("未贴边_总") or "?", O.TOL_MM))
        if cov < MIN_COV:
            cl = _cluster(_uncovered_points(f, door, CLUSTER_MM))
            rec["_cluster"] = cl
            fails.append("③ %s 覆盖 %.3f < %.2f：原始图上有画线没被生成件盖上，"
                          "缺口聚成 %d 处（坐标见证据段）" % (f, cov, MIN_COV, len(cl)))

    ctl = None
    for rec in rows:
        ctl = _positive_control(BID, rec["floor"])
        if ctl:
            break

    _M.update(_rows=rows, _fails=fails, _skipped=skipped, _ctl=ctl)
    return _M


def _hit(rule):
    """同一份 `fails` 里以该规则号开头的条（不另算一遍 —— 铁律 018）。"""
    return [x for x in _M["_fails"] if x.startswith(rule)]


def _rows_or_skip():
    _量()
    if _M["_skipped"] and not _M.get("_said_skips"):
        for f, why in _M["_skipped"]:
            log("  ★ %-6s 没量到：%s（不算过、也不假报红 —— 铁律 199）" % (f, why))
        _M["_said_skips"] = True
    if not _M["_rows"]:
        raise I.没量到("本栋一层都没量到 —— 「没量到」不算过、也不假报红（铁律 199）")
    return _M["_rows"]


def c1_贴源率():
    rows = _rows_or_skip()
    for rec in rows:
        tie, cov = rec["贴源率"], rec["覆盖"]
        log("  %-6s 生成 %6d 段 / 原始 %5d 段  贴源 %.3f  覆盖 %.3f  "
            "P95 %.0f / %.0f mm%s"
            % (rec["floor"], rec["生成段"], rec["原始段"], tie, cov,
               rec["生成_P95距"], rec["原始_P95距"],
               "" if (tie >= MIN_TIE and cov >= MIN_COV) else "   ★"))
    fs = _hit("②")
    worst = min(rows, key=lambda r: r["贴源率"])
    return I.结果(not fs, "最低 %.3f" % worst["贴源率"],
                  "；".join(fs) if fs else "≥ %.2f（最低 %s %.3f）"
                  % (MIN_TIE, worst["floor"], worst["贴源率"]),
                  参数=[
                      I.参数("贴源率下限", "%.2f" % MIN_TIE,
                             "全仓 376 层实测分布（_scratch/overlay_all.json，"
                             "过程/_scratch/probe_overlay_all.py 2026-10-19）："
                             "min 0.956 / p01 0.976 / p05 0.988 / 中位 1.000",
                             "最低 %s %.3f" % (worst["floor"], worst["贴源率"]),
                             "贴源率低了 ⇒ 先查 contours→DXF 的投影/容差，再重跑 J-10.8-01"),
                      I.参数("容差", "%.0f mm" % O.TOL_MM,
                             "rebuild/tools/overlay_check.py::TOL_MM（与 /api/dxf/compare 共用）",
                             "%s 生成_P95距 %.0f mm" % (worst["floor"], worst["生成_P95距"]),
                             "容差是比对口径，改动必须连读数一起改 ⇒ 只改 TOL_MM 后重跑 J-10.8-01"),
                  ])


def c2_覆盖():
    rows = _rows_or_skip()
    fs = _hit("③")
    ev = []
    for rec in rows:
        for c in rec.get("_cluster") or []:
            ev.append("%s 覆盖缺口  x %d–%d  y %d–%d  （%d 个 %d m 网格）"
                      % (rec["floor"], c[0], c[2], c[1], c[3], c[4],
                         CLUSTER_MM // 1000))
    worst = min(rows, key=lambda r: r["覆盖"])
    return I.结果(not fs, "最低 %.3f" % worst["覆盖"],
                  "；".join(fs) if fs else "≥ %.2f（最低 %s %.3f）"
                  % (MIN_COV, worst["floor"], worst["覆盖"]),
                  证据=ev,
                  参数=[
                      I.参数("覆盖率下限", "%.2f" % MIN_COV,
                             "全仓 376 层实测分布（_scratch/overlay_all.json，"
                             "过程/_scratch/probe_overlay_all.py 2026-10-19）："
                             "min 0.728 / p01 0.740 / p05 0.862 / 中位 0.936",
                             "最低 %s %.3f" % (worst["floor"], worst["覆盖"]),
                             "覆盖率低了 ⇒ 先查 06_su/contours 出件缺的墙/楼梯/屋面，再重跑 J-10.8-01"),
                      I.参数("覆盖源", "+".join(O.COVER_KINDS),
                             "rebuild/tools/overlay_check.py::COVER_KINDS"
                             "（原始墙层上还画着踏步线/屋面/女儿墙）",
                             "%s 原始 %d 段 / 生成覆盖源 %d 段"
                             % (worst["floor"], worst["原始段"], worst["覆盖段"]),
                             "覆盖源变了会整层假低 ⇒ 只认 COVER_KINDS，别在闸里另加图层"),
                      I.参数("容差", "%.0f mm" % O.TOL_MM,
                             "rebuild/tools/overlay_check.py::TOL_MM（与 /api/dxf/compare 共用）",
                             "%s 原始_P95距 %.0f mm" % (worst["floor"], worst["原始_P95距"]),
                             "容差是比对口径，改动必须连读数一起改 ⇒ 只改 TOL_MM 后重跑 J-10.8-01"),
                  ])


def c3_正对照():
    _rows_or_skip()
    ctl = _M["_ctl"]
    if ctl is None:
        log("  ★ 正对照没量到：没有一层的两份件能同时读出几何 ⇒ 本闸的绿不作数")
        return I.结果(False, "—",
                      "没有一层的两份件能同时读出几何；本闸的绿不作数",
                      参数=[
                          I.参数("平移量", "%.0f mm" % PROBE_MM, "本闸正对照",
                                 "没量到（无同层两份几何）",
                                 "对照没红 ⇒ 判据没分辨力，先查对照输入"),
                          I.参数("期望掉到", "< %.2f" % MIN_TIE, "本闸正对照",
                                 "没量到",
                                 "对照没红 ⇒ 判据没分辨力，先查对照输入"),
                      ])
    base, after = ctl
    good = after < MIN_TIE
    log("  正对照：生成边整体平移 %.0f mm ⇒ 贴源率 %.3f → %.3f（必须 < %.2f）：%s"
        % (PROBE_MM, base, after, MIN_TIE, "按预期" if good else "★没有分辨力"))
    return I.结果(good, "%.3f → %.3f" % (base, after),
                  "按预期（平移后 < %.2f）" % MIN_TIE if good
                  else "没有分辨力：平移 %.0f mm 后仍 ≥ %.2f"
                  % (PROBE_MM, MIN_TIE),
                  参数=[
                      I.参数("平移量", "%.0f mm" % PROBE_MM, "本闸正对照",
                             "整体平移 %.0f mm" % PROBE_MM,
                             "对照没红 ⇒ 判据没分辨力，先查对照输入"),
                      I.参数("期望掉到", "< %.2f" % MIN_TIE, "本闸正对照",
                             "平移后 %.3f（原 %.3f）" % (after, base),
                             "对照没红 ⇒ 判据没分辨力，先查对照输入"),
                  ])


CHECKS = [
    ("②", "贴源率 ≥ 阈值", c1_贴源率),
    ("③", "覆盖 ≥ 阈值", c2_覆盖),
    ("④", "正对照：平移要掉下阈值", c3_正对照),
]


def main():
    floors = VD.floors(BID)
    log("判据 %s —— 叠加比对：生成轮廓 vs 原始 CAD 墙/柱（%s，%d 层）"
        % (GATE, BID, len(floors)))
    log("  ★ 唯一实现 `rebuild/tools/overlay_check.py`；本闸与服务端 `/api/dxf/compare` 共用")
    log("  ★ 阈值：贴源率 ≥ %.2f、覆盖 ≥ %.2f（全仓 376 层实测：贴源 min %.3f / p01 %.3f / "
        "中位 %.3f；覆盖 min %.3f / p05 %.3f / 中位 %.3f）"
        % (MIN_TIE, MIN_COV, 0.956, 0.976, 1.000, 0.728, 0.862, 0.936))

    rep = I.跑(GATE, CHECKS, log=log, 宽=26,
               fix_of=lambda r: VD.fix_of(GATE, r) or "")
    return _write(rep.rc, rep.items)


def _write(rc, items=None):
    os.makedirs(RUNDIR, exist_ok=True)
    pass_ = None if rc == 4 else (rc == 0)
    VD.emit(GATE, BID, pass_, rc, _LOG, blind=BLIND,
            files={"gen": os.path.join(_P["root"], "06_su", "contours"),
                   "raw": _P["raw"]},
            extra={"阈值_贴源": MIN_TIE, "阈值_覆盖": MIN_COV,
                   "容差_mm": O.TOL_MM, "门模式": O.door_mode_of(BID)},
            items=items)
    print("  写出:", JSON_OUT)
    return rc


if __name__ == "__main__":
    sys.exit(main())
