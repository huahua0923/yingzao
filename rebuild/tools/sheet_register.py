# -*- coding: utf-8 -*-
r"""逐层配准 —— 把每张图幅搬进**同一个楼栋基准**（同一栋楼的所有层共用一套坐标）。

## 为什么要有这一步（2026-10-20 用户「办公楼副楼 3 楼和 4 楼错开了」）

`export_sheet.py` 原来把每张图幅**左下角**（窗口角 `w["x0"], w["y0"]`）挪到原点
（`dx, dy = -w["x0"], -w["y0"]`），这里默认了「窗口角就是楼栋原点」。
实测：源 DXF 里各层平面**在各自窗口里放的位置并不一致**——
c004f1 第 4 张图整张比第 2、3 张高 **1700 mm**（中央楼梯对不上，
`档案室` 标注也从 y=27915 跑到 y=29615）。窗内局部坐标直接当楼栋坐标
⇒ 第 4 层整层平移 1.7 m，屏上就是用户说的「3 楼和 4 楼错开」。
**单层内部**所有判据（墙/房/门/面积）都绿 —— 它们量的都是同一张图里的相对关系。

## 判据：只信**两把互相独立的尺子**，不信「看着差不多」

1. **楼梯**（`recognize.stair_zones`）：楼梯井必须上下连通，跨层同一座楼梯的位置差
   就是这一层的平移量。最硬的锚。
2. **房间文字标注的位置**（`5面积/6房间号/7用途/8单位` 等）：只在**两边都没有楼梯**时
   才用；标注随房间走，同一套平面重复出现时点阵重合。用「两两点差取众数」找平移。

墙族 FFT（±5 m 找峰）**只是旁证**：楼层本来就可以退台/变小，光看墙会把退台当错位。
两把尺子结论差 > `TOL` ⇒ **不动**，记冲突，交给人看。

参考系 = **多数派**（连通分量内平移量取中位数归零）；不是「永远信第 1 张」——
c035 就是第 1 张偏、2~4 张对。

## 出件

  `<根>/01_cad/raw/<层>.dxf`   **原地平移**（平移前整份备份到 `<根>/_archive/raw_before_register_*`）
  `<根>/01_cad/raw/_registration.json`
      { "sheets": [{"floor":"1","dx_mm":0,"dy_mm":-1085,"anchor":"stair",...}], ... }

用法：
  python rebuild/tools/sheet_register.py --all            # 量 + 应用（幂等：先退回上一次的平移）
  python rebuild/tools/sheet_register.py --all --dry      # 只量，不动盘
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
import time

import ezdxf
import numpy as np
from ezdxf import path as ezpath
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B                                                     # noqa: E402
import recognize as R                                                    # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = B.ROOT
RAW = os.path.join(ROOT, "01_cad", "raw")
OUT = os.path.join(RAW, "_registration.json")
RES = 100.0            # 互相关栅格（mm）
SEARCH = 5000.0        # 互相关搜索半径（mm）—— 只用于**核对**近邻锚（窄窗）
# ★★ 2026-10-20（用户「第二办公楼地下室和一楼也是错开的」「第三教学楼一楼和二楼错开」）：
#   旧口径下这一对**根本没有边**：楼梯最近 3 m、柱最近 2 m 的配对在 11.8 / 12.6 m 的整层
#   错位下一个都对不上，宽 5 m 的墙族互相关也搜不到 ⇒ `solve_sheets` 把这一层当「没有锚」，
#   静默停在原地，D-25 也就看不见它（症状：楼层错开，判据全绿）。
#   新增：本边一条近邻锚都没有时，**宽搜**（柱心平移众数 → 墙族互相关 ±30 m）。
SEARCH_WIDE = 30000.0  # 宽搜半径（mm）
COL_WIDE_BIN = 100.0   # 柱心平移众数的格子（mm）
COL_WIDE_TOL = 300.0   # 落在这个峰容差内的点对才算支持（mm）
COL_WIDE_SHARE = 0.80  # 支持率 ≥ 这个数才认（网格柱会有多个峰：c020 真峰 14/16=0.88）
# ★ 试过又拿掉的：墙族宽搜当兜底。c017 实测它在长条重复立面上给出 (23100,−21700)、
#   得分 0.68 —— 那是「挪 23 m 后墙正好又对上」的自相似假峰，而 D1 的楼梯与楼层只差 210 mm。
#   大位移的假锚比不动更坏；兜底只留「柱心众数」和「两段拼」这两种有刚性依据的。
TOL = 150.0            # 两把尺子允许的最大差（mm）
STAIR_MATCH = 3000.0   # 跨层判「同一座楼梯」的最大中心距（mm）
COL_MATCH = 2000.0     # 跨层判「同一根柱」的最大中心距（mm）
COL_MIN = 3            # 柱锚至少配几根
COL_SHARE = 0.5        # 配对率低于这个数 ⇒ 两层不是同一种平面（裙房/顶层），柱锚作废
TOL_REL = 0.15         # 两把尺子差多少算「同一个量」：max(TOL, TOL_REL × 位移) mm
MIN_MOVE = 100.0       # 小于这个数的平移不落盘（图上量不出，挪了只是让下次再挪回来）
TEXT_BIN = 100.0       # 文字点阵取众数的格子（mm）
TEXT_MIN = 4           # 文字锚至少要有几对点落在同一格

WALL_LAYER = B.layer("wall", "4.2墙体")


# ---------------------------------------------------------------- 几何 → 栅格
def _wall_points(doc):
    pts = []
    for e in doc.modelspace():
        try:
            if e.dxf.layer != WALL_LAYER:
                continue
        except Exception:                                                # noqa: BLE001
            continue
        t = e.dxftype()
        try:
            if t == "LINE":
                a, b = e.dxf.start, e.dxf.end
                pts.append((a.x, a.y))
                pts.append((b.x, b.y))
            elif t == "LWPOLYLINE":
                # ★ ezdxf 1.4 的 LWPolyline **没有** `.flattening()`（2026-10-20 实测：
                #   AttributeError 被下面的 except 吃掉 ⇒ 只剩 ARC/CIRCLE 进栅格，
                #   而 c004f1 第 4 张图没有圆弧 ⇒ 栅格全空、FFT 峰落在搜索区角落。
                #   统一走 `ezdxf.path.make_path(...).flattening()`。
                pts.extend((v.x, v.y) for v in ezpath.make_path(e).flattening(150.0))
            elif t in ("ARC", "CIRCLE"):
                c, r = e.dxf.center, e.dxf.radius
                a0 = 0.0 if t == "CIRCLE" else np.deg2rad(e.dxf.start_angle)
                a1 = 2 * np.pi if t == "CIRCLE" else np.deg2rad(e.dxf.end_angle)
                n = 48 if t == "CIRCLE" else 24
                pts.extend((c.x + r * np.cos(a0 + (a1 - a0) * i / n),
                            c.y + r * np.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1))
        except Exception:                                                # noqa: BLE001
            continue
    return pts


def _raster(pts, x0, y0, w, h):
    g = np.zeros((h, w), np.float32)
    for x, y in pts:
        ix, iy = int((x - x0) / RES), int((y - y0) / RES)
        if 0 <= ix < w and 0 <= iy < h:
            g[iy, ix] = 1.0
    return g


def _fft_shift(a, b, search=None):
    """b 挪 (dx,dy) 后与 a 最重合；正 = 往 +轴挪。

    `search` 默认 `SEARCH`（窄窗，核对近邻锚用）；宽搜传 `SEARCH_WIDE`。
    """
    c = signal.fftconvolve(a, b[::-1, ::-1], mode="same")
    m = int((SEARCH if search is None else search) / RES)
    cy, cx = c.shape[0] // 2, c.shape[1] // 2
    sub = c[cy - m:cy + m + 1, cx - m:cx + m + 1]
    iy, ix = np.unravel_index(np.argmax(sub), sub.shape)
    return (ix - m) * RES, (iy - m) * RES, float(sub[iy, ix]) / (float(min(a.sum(), b.sum())) or 1.0)


# ---------------------------------------------------------------- 两把尺子
def _stairs(path):
    try:
        return [((a + c) / 2.0, (b + d) / 2.0) for a, b, c, d in R.stair_zones(path)]
    except Exception:                                                    # noqa: BLE001
        return []


def _cols(path):
    """柱心（mm）：两种画法各认一遍、取认出来的多的 —— 与建件/判据**同一个认法**。

    ★★ 2026-10-20：`measure()` 以前**根本不读柱**（只读楼梯和文字）。柱是刚体、逐层
      一模一样、数量最多，是唯一能在整层错开十几米时还认得出「谁跟谁是一根」的东西；
      不读柱 ⇒ 11.85 / 12.60 m 的错位一条锚都没有，配准原地不动、判据也看不见。
    """
    try:
        import redraw as RD
        doc = ezdxf.readfile(path)
        lc = RD.cols_lwpolyline(doc, layer=RD.COL_LAYER)
        bc = RD.blocks_wcs(path, layer=RD.COL_LAYER)
        cols = bc if len(bc) > len(lc) else lc
        out = []
        for p, _closed in cols:
            xs = [q[0] for q in p]
            ys = [q[1] for q in p]
            if xs and ys:
                out.append(((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0))
        return out
    except Exception:                                                    # noqa: BLE001
        return []


def _stair_edge(ci, cj):
    """两层都有楼梯 ⇒ 返回 (dx,dy)，含义：把 i 挪 (dx,dy) 后与 j 的楼梯重合。"""
    if not ci or not cj:
        return None
    ds = []
    for x, y in ci:
        d, best = 1e18, None
        for x2, y2 in cj:
            dd = ((x - x2) ** 2 + (y - y2) ** 2) ** 0.5
            if dd < d:
                d, best = dd, (x - x2, y - y2)
        if d <= STAIR_MATCH:
            ds.append(best)
    if not ds:
        return None
    return float(np.median([a for a, _ in ds])), float(np.median([b for _, b in ds]))


def _col_edge(ci, cj):
    """柱心对柱心 ⇒ (dx,dy)；配对率不足（两层平面根本不是一种）就作废。

    ★ 为什么要柱（2026-10-20 实测）：柱是刚体，逐层一模一样，且数量多；
      楼梯区的中心随「这一层有没有半跑/出屋面梯段」飘 —— c004 的楼梯说偏 478 mm，
      而两层的柱心逐一对上（差 0.0 mm）、墙族互相关也说 0。柱在，就先信柱。
    """
    if not ci or not cj or min(len(ci), len(cj)) < COL_MIN:
        return None
    ds = []
    for x, y in ci:
        d, best = 1e18, None
        for x2, y2 in cj:
            dd = ((x - x2) ** 2 + (y - y2) ** 2) ** 0.5
            if dd < d:
                d, best = dd, (x - x2, y - y2)
        if d <= COL_MATCH:
            ds.append(best)
    if len(ds) < max(COL_MIN, COL_SHARE * min(len(ci), len(cj))):
        return None
    mx = float(np.median([a for a, _ in ds]))
    my = float(np.median([b for _, b in ds]))
    # ★ 2026-10-20：配对率高 ≠ 配对正确。c020 的 D1（35 根、格距 6 m）配 2 层（16 根）
    #   有 8~10 个「碰巧落在 2 m 内」的假配对，中位数被拉成 (0,−1050)；真位移是 +11850，
    #   而宽搜众数 14/16 一票就点了出来。真配对的位移必须**聚成一团**：中位数附近
    #   300 mm 内至少 80% —— 散开的配对不是锚，是噪声（宁可不动，不许动错）。
    near = sum(1 for a, b in ds
               if abs(a - mx) <= COL_WIDE_TOL and abs(b - my) <= COL_WIDE_TOL)
    if near < max(COL_MIN, COL_WIDE_SHARE * len(ds)):
        return None
    return mx, my


def _agrees(g, e):
    """两把尺子量的是不是同一个位移：差 ≤ max(TOL, TOL_REL × 位移)。"""
    mag = max(abs(e[0]), abs(e[1]))
    lim = max(TOL, TOL_REL * mag)
    return abs(g[0] - e[0]) <= lim and abs(g[1] - e[1]) <= lim


def _texts(doc, layers):
    out = []
    for e in doc.modelspace():
        try:
            if e.dxf.layer not in layers or e.dxftype() not in ("TEXT", "MTEXT"):
                continue
        except Exception:                                                # noqa: BLE001
            continue
        try:
            p = e.dxf.insert
            out.append((p.x, p.y))
        except Exception:                                                # noqa: BLE001
            continue
    return out


def _text_edge(pi, pj):
    """两页文字点阵取众数差；落同一格的点对 ≥ TEXT_MIN 才算数。"""
    if len(pi) < TEXT_MIN or len(pj) < TEXT_MIN:
        return None
    cnt = collections.Counter()
    for x, y in pi:
        for x2, y2 in pj:
            cnt[(round((x - x2) / TEXT_BIN), round((y - y2) / TEXT_BIN))] += 1
    (kx, ky), n = cnt.most_common(1)[0]
    if n < TEXT_MIN:
        return None
    return kx * TEXT_BIN, ky * TEXT_BIN


def _mode_edge(pi, pj, tol=COL_WIDE_TOL, bin_mm=COL_WIDE_BIN):
    """**宽搜**点对平移众数 ⇒ (dx,dy,支持数)；没有点对返回 None。

    与 `_col_edge` 的差别只在「配对半径」：近邻配对要求两点相距 ≤ COL_MATCH，
    整层错开 11~13 m 时一一对不上（c020 / c027 就是这么被漏掉的）。
    这里不预判哪个跟哪个配，先把**所有点对的平移**扔进格子数票，票最多的那个平移
    再用 tol 收一次内点取中位数。网格柱会产生多个峰（差一整跨也算一票），
    所以调用方必须看**支持数占两层的比例**再决定认不认。
    """
    if not pi or not pj:
        return None
    cnt = collections.Counter()
    for x, y in pi:
        for x2, y2 in pj:
            cnt[(round((x - x2) / bin_mm), round((y - y2) / bin_mm))] += 1
    (kx, ky), _n = cnt.most_common(1)[0]
    cx, cy = kx * bin_mm, ky * bin_mm
    ds = [(x - x2, y - y2) for x, y in pi for x2, y2 in pj
          if abs((x - x2) - cx) <= tol and abs((y - y2) - cy) <= tol]
    if not ds:
        return None
    return (float(np.median([a for a, _ in ds])),
            float(np.median([b for _, b in ds])), len(ds))


def _mode_cols(ci, cj):
    """宽搜柱心平移众数，支持率达标才返回 (dx, dy, 支持数, 需要数)。"""
    if not ci or not cj or min(len(ci), len(cj)) < COL_MIN:
        return None
    ce = _mode_edge(ci, cj)
    if ce is None:
        return None
    need = max(COL_MIN, COL_WIDE_SHARE * min(len(ci), len(cj)))
    if ce[2] < need:
        return None
    return (ce[0], ce[1], ce[2], need)


# ---------------------------------------------------------------- 解平移量
def _components(n, edges):
    """edges: {i: (j, dx, dy)}（只连相邻层）→ 按连通分量分组。"""
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, j in edges:
        ra, rb = find(i), find(j)
        if ra != rb:
            parent[ra] = rb
    grp = collections.defaultdict(list)
    for i in range(n):
        grp[find(i)].append(i)
    return list(grp.values())


def measure(floors):
    docs = [(nm, p, ezdxf.readfile(p)) for nm, p in floors]
    st = [_stairs(p) for _, p, _ in docs]
    txt_layers = set(B.profile().get("keep_layers") or []) - {WALL_LAYER}
    tx = [_texts(d, txt_layers) for _, _, d in docs]
    allpts = [_wall_points(d) for _, _, d in docs]
    cols = [_cols(p) for _, p in floors]
    return solve_sheets([nm for nm, _ in floors], allpts, st, tx, cols=cols)


def solve_sheets(names, allpts, st, tx=None, enforce_fft=True, cols=None):
    """**唯一**的定案逻辑：楼梯/文字定案，墙族互相关只做旁证。

    配准工具（读 raw DXF）与判据 D-25（读 contours）都调这里 —— 两处写同一个决定，
    必然漂移（铁律 018/174）。输入是「每层的点集 + 每层的楼梯中心 + 每层的文字点」。

    `enforce_fft=True`（配准用）：旁证不一致 ⇒ 这一层**不动**（宁可不动，不许动错）。
    `enforce_fft=False`（判据用）：旁证不一致也把楼梯算出来的量**报出来**，
       只在 `conflict` 里写明两条尺子打架 —— 判据的职责是点名，不是替人决定。
    """
    n = len(names)
    tx = tx or [[] for _ in range(n)]
    xs = [x for pts in allpts for x, _ in pts]
    ys = [y for pts in allpts for _, y in pts]
    if not xs:
        raise SystemExit("★ 墙层一条线都没读到")
    x0, y0 = min(xs) - 6000, min(ys) - 6000
    w = int((max(xs) - x0) / RES) + 1
    h = int((max(ys) - y0) / RES) + 1
    grids = [_raster(p, x0, y0, w, h) for p in allpts]
    # 旁证两路：
    #   ① `fft[i]` = i **相对第 0 层**（老口径，只用来显示）；
    #   ② `gp[(i,j)]` = j 相对 i（**逐条相邻边**）—— 2026-10-20 实测：c017 的 4 层
    #      相对 3、5 层都偏 (+1200,−500)，但第 0 层是地下室、它自己也在飘，
    #      只比「相对 0」就会把两条一致的真证据判成「打架」⇒ 冲突必须逐边比。
    fft = [(0.0, 0.0, 1.0)] + [_fft_shift(grids[0], grids[i]) for i in range(1, n)]

    # ① 相邻层建边：柱 > 楼梯 > 文字（前两把都缺才用文字）
    #    ★ 有柱的层不用楼梯定案（柱是刚体、数量多；楼梯区会随半跑/出屋面梯段飘）。
    #      楼梯/文字仍存进 `alts`，逐边当**第二把尺子**用：与柱差出 max(TOL,15%×位移)
    #      就记冲突（2026-10-20 实测 c004：柱 0、墙 0、楼梯 478 ⇒ 楼梯是坏的，不许它定案）。
    edges, kinds, alts = {}, {}, {}
    wide = {}                 # 宽搜兜底边的读数（给 L- 判据/人看）
    wide_kind = {}            # 这条边是宽搜出来的（旁证核对改用宽窗）

    def _pair_edge(i, j):
        """层 i 相对层 j 的位移（把 i 挪这么多就与 j 重合）：近邻锚 → 宽搜。

        跳层也能用（j 不必与 i 相邻）：c020 的 D1↔1 两条近邻锚都断了
        （D1 有 35 根柱、1 层一根都没识别到；楼梯差 11.5 m 超出 3 m 配对半径），
        但 D1↔2 柱心 14/16 对上、1↔2 楼梯一对 —— 两段一减就是 D1↔1。
        """
        ci = (cols or [None] * n)[i]
        cj = (cols or [None] * n)[j]
        for k, e in (("col", _col_edge(ci, cj)), ("stair", _stair_edge(st[i], st[j]))):
            if e is not None:
                return (k, e, "")
        mc = _mode_cols(ci, cj)
        if mc is not None:
            return ("colwide", (mc[0], mc[1]), "柱 %d/%d" % (mc[2], mc[3]))
        ms = _mode_edge(st[i], st[j]) if (st[i] and st[j]) else None
        # ★ 至少两对楼梯同票才算锚：1 对是「挑了个最近的」，票数打平就按插入次序取胜
        #   （2026-10-20 c017 实测：D1 一座梯、1 层三座梯 ⇒ 随手配出一票 23.1 m 的位移）。
        if ms is not None and ms[2] >= 2 and max(abs(ms[0]), abs(ms[1])) > STAIR_MATCH:
            return ("stairwide", (ms[0], ms[1]), "楼梯 %d 对" % ms[2])
        return None

    for i in range(n - 1):
        ij = (i, i + 1)
        cand = []
        ce = _col_edge((cols or [None] * n)[i], (cols or [None] * n)[i + 1]) \
            if cols else None
        se = _stair_edge(st[i], st[i + 1])
        te = _text_edge(tx[i], tx[i + 1]) if (not st[i] and not st[i + 1]) else None
        for k, e in (("col", ce), ("stair", se), ("text", te)):
            if e is not None:
                cand.append((k, e))
        if not cand:
            # ★★ 2026-10-20：本边一条近邻锚都没有 —— 旧口径在这里直接 `continue`：
            #   这一层没有边、`s` 停在 0、**静默不动**；D-25 从轮廓读同一套逻辑，
            #   于是判据也看不见它 ⇒「楼层错开，判据全绿」。
            #   兜底只在**没有锚**时触发，有锚的边仍走近邻口径（不改变既有配准结果）。
            #   次序：直接宽搜柱 > 借邻层拼 > 楼梯宽搜（最弱，要 ≥2 对同票）。
            ci = (cols or [None] * n)[i]
            cj = (cols or [None] * n)[i + 1]
            mc = _mode_cols(ci, cj)
            if mc is not None:
                cand.append(("colwide", (mc[0], mc[1])))
                wide[ij] = "柱 %d/%d 对上 (%.0f,%.0f)" % (mc[2], mc[3], mc[0], mc[1])
            if not cand:
                for k in (i - 1, i + 2, i - 2, i + 3):
                    if not (0 <= k < n) or k in (i, i + 1):
                        continue
                    a = _pair_edge(i, k)
                    b = _pair_edge(i + 1, k)
                    if a is None or b is None:
                        continue
                    cand.append(("compose", (a[1][0] - b[1][0], a[1][1] - b[1][1])))
                    wide[ij] = "借 %s 拼：(%s %s%.0f,%.0f) − (%s %s%.0f,%.0f)" % (
                        names[k], a[0], (a[2] + " ") if a[2] else "", a[1][0], a[1][1],
                        b[0], (b[2] + " ") if b[2] else "", b[1][0], b[1][1])
                    break
            if not cand and st[i] and st[i + 1]:
                ms = _mode_edge(st[i], st[i + 1])
                if ms is not None and ms[2] >= 2 \
                        and max(abs(ms[0]), abs(ms[1])) > STAIR_MATCH:
                    cand.append(("stairwide", (ms[0], ms[1])))
                    wide[ij] = "楼梯宽搜 %d 对 (%.0f,%.0f)，弱证据" % (ms[2], ms[0], ms[1])
            if not cand:
                continue
            wide_kind[ij] = True
        edges[ij] = cand[0][1]
        kinds[ij] = cand[0][0]
        alts[ij] = cand[1:]
    # 旁证逐边量（约定：`_fft_shift(a,b)` 给出 s_b − s_a；与 `fft[i]` 的老口径一致）
    #   宽搜出来的边：窄窗（5 m）对它的位移**天然看不见**，拿窄窗去核等于拿错了尺子
    #   ⇒ 这些边用同一个宽窗函数复查（同一个量只有一个估计器，铁律 018/174）。
    gp = {ij: _fft_shift(grids[ij[0]], grids[ij[1]],
                         search=SEARCH_WIDE if ij in wide_kind else SEARCH)
          for ij in edges}
    # ★★ 2026-10-20 实测（c006 8~11 层）：楼梯锚在 7↔8 上给 −243 mm，整条墙族说 0 ——
    #   如果只要求「有一条相邻边对得上」就放行，这条坏边会把后面 4 层一起拖走 328 mm。
    #   定案只认**本边有墙族作证**的位移；没作证的边：
    #     · 配准（enforce_fft=True）⇒ 该边按 0 算（宁可不动，不许动错）；
    #     · 判据（enforce_fft=False）⇒ 仍算出位移，但在行上记冲突 ⇒ 出提示交人看。
    edge_ok = {ij: (True if ij in wide_kind
                    else _agrees((gp[ij][0], gp[ij][1]), e))
               for ij, e in edges.items()}
    edge_raw = dict(edges)
    if enforce_fft:
        for ij, ok in edge_ok.items():
            if not ok:
                edges[ij] = (0.0, 0.0)

    # ② 每个连通分量解一条链，再按中位数归零（多数派）
    s = [(0.0, 0.0)] * n
    anchor = ["none"] * n
    for comp in _components(n, [k for k in edges]):
        if len(comp) < 2:
            continue
        vals = {comp[0]: (0.0, 0.0)}
        for i in comp:                       # 沿相邻边推
            if i + 1 in comp and (i, i + 1) in edges:
                dx, dy = edges[(i, i + 1)]   # = c_i − c_j
                bx, by = vals[i]
                # 约定 s_i − s_j = c_j − c_i ⇒ s_j = s_i + (c_i − c_j)
                vals[i + 1] = (bx + dx, by + dy)
        mx = float(np.median([vals[i][0] for i in comp]))
        my = float(np.median([vals[i][1] for i in comp]))
        for i in comp:
            s[i] = (vals[i][0] - mx, vals[i][1] - my)
            anchor[i] = kinds.get((i - 1, i)) or kinds.get((i, i + 1)) or "none"

    rows = []
    for i, nm in enumerate(names):
        sdx, sdy = s[i]
        conf = None
        if abs(sdx) >= 100 or abs(sdy) >= 100:
            inc = [e for e in ((i - 1, i), (i, i + 1)) if e in edges]
            if inc:
                # 本层的位移是沿相邻边攒出来的：**任何一条没被墙族作证的边**都算冲突
                bad = [ij for ij in inc if not edge_ok[ij]]
                # 第二把「位移尺子」（柱定案时是楼梯，反之亦然）：差得远也算冲突
                alt_bad = []
                for a, b in inc:
                    eb = (s[b][0] - s[a][0], s[b][1] - s[a][1])
                    for k2, e2 in alts.get((a, b), []):
                        # alts 与 edges 同口径：e2 = s_b − s_a
                        if not _agrees(e2, eb):
                            alt_bad.append((k2, e2[0], e2[1], eb[0], eb[1]))
                            break
                if bad:
                    ij = bad[0]
                    e0 = edge_raw[ij]
                    gx, gy, _sc = gp[ij]
                    conf = ("%s↔%s：锚 (%+.0f,%+.0f) vs 墙族 (%+.0f,%+.0f) 差 > max(%.0f, %.0f%%)%s"
                            % (names[ij[0]], names[ij[1]], e0[0], e0[1], gx, gy,
                               TOL, TOL_REL * 100,
                               " ⇒ 该边按 0 算" if enforce_fft else "（两条尺子打架）"))
                elif alt_bad:
                    k2, ax, ay, ex, ey = alt_bad[0]
                    conf = ("%s 锚与锚打架：(%+.0f,%+.0f) vs 定案 (%+.0f,%+.0f)%s"
                            % (k2, ax, ay, ex, ey,
                               " ⇒ 不动" if enforce_fft else "（两条尺子打架）"))
                    if enforce_fft:
                        sdx = sdy = 0.0
            else:
                # 孤立层（没有锚边）：退回老口径「相对第 0 层」，只做旁证
                ex, ey = sdx - s[0][0], sdy - s[0][1]
                if abs(fft[i][0] - ex) > TOL or abs(fft[i][1] - ey) > TOL:
                    conf = ("与墙相关 (%+.0f,%+.0f) 差 > %.0f mm%s"
                            % (fft[i][0], fft[i][1], TOL,
                               " ⇒ 不动" if enforce_fft else "（两条尺子打架）"))
                    if enforce_fft:
                        sdx = sdy = 0.0
        sdx, sdy = round(sdx), round(sdy)
        if abs(sdx) < 1:
            sdx = 0.0
        if abs(sdy) < 1:
            sdy = 0.0
        # ★ 没有锚的相邻边要**点名**（2026-10-20）：旧口径下这种边不存在，
        #   这一层静默停在原地，判据连一行读数都没有 ⇒ 楼层错开也全绿。
        _pairs = [p for p in ((i - 1, i), (i, i + 1)) if p[0] >= 0 and p[1] < n]
        rows.append({"floor": nm, "dx_mm": float(sdx), "dy_mm": float(sdy),
                     "anchor": anchor[i], "fft_dx": float(fft[i][0]), "fft_dy": float(fft[i][1]),
                     "fft_score": round(fft[i][2], 3),
                     "stairs": len(st[i]), "texts": len(tx[i]), "conflict": conf,
                     "edge": kinds.get((i - 1, i)) or kinds.get((i, i + 1)),
                     "no_edge": ["%s↔%s" % (names[p[0]], names[p[1]])
                                 for p in _pairs if p not in edges],
                     "wide": wide.get((i - 1, i)) or wide.get((i, i + 1))})
    return rows, edges


# ---------------------------------------------------------------- 应用
def _translate_dxf(path, dx, dy):
    doc = ezdxf.readfile(path)
    for e in doc.modelspace():
        try:
            e.translate(dx, dy, 0)
        except Exception:                                                # noqa: BLE001
            pass
    doc.saveas(path)


def _undo_previous(rows_prev):
    for r in rows_prev:
        p = os.path.join(RAW, r["floor"] + ".dxf")
        if os.path.exists(p) and (r.get("dx_mm") or r.get("dy_mm")):
            _translate_dxf(p, -float(r["dx_mm"]), -float(r["dy_mm"]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    # ★ 2026-10-20：地下室也是层（用户「地下室和一楼也是错开的」）。以前这里只拿地上层，
    #   D1 图幅躺在 raw 里却从不参与配准 —— c020 的地下室就这么一直错着 11.85 m。
    _base = B.profile().get("basement")
    names = ([_base] if _base else []) + B.floor_names()
    floors = [(nm, os.path.join(RAW, nm + ".dxf")) for nm in names]
    miss = [p for _, p in floors if not os.path.exists(p)]
    if miss:
        print("★ 缺图幅：%s（先跑 export_sheet.py）" % miss)
        return 2
    # ★ 幂等：**先退回上一次的平移，再量**（2026-10-20 实测踩过：量在前、退在后 ⇒
    #   第二次跑量到「已对齐」（全 0），然后把上一次的平移退回去，结果盘上又变回没配准，
    #   而记录写着「0 层要动」——量具与动作的次序反了，症状是「修了又坏」。）
    prev = None
    if not a.dry and os.path.exists(OUT):
        try:
            with open(OUT, encoding="utf-8") as fh:
                prev = json.load(fh)
        except Exception:                                                # noqa: BLE001
            prev = None
    if prev and prev.get("sheets"):
        _undo_previous(prev["sheets"])
    rows, edges = measure(floors)
    print("%-8s %10s %10s %-6s %-24s %s" % ("层", "dx(mm)", "dy(mm)", "锚", "墙相关", "读数"))
    for r in rows:
        print("%-8s %+10.0f %+10.0f %-6s fft=(%+.0f,%+.0f) %.2f  梯%d 文字%d%s"
              % (r["floor"], r["dx_mm"], r["dy_mm"], r["anchor"],
                 r["fft_dx"], r["fft_dy"], r["fft_score"],
                 r["stairs"], r["texts"], ("  ★ " + r["conflict"]) if r["conflict"] else ""))
    # 小于 MIN_MOVE 的平移不落盘：图上量不出，挪了只是下次再挪回来（还会让 raw 无端改指纹）
    for r in rows:
        if max(abs(r["dx_mm"]), abs(r["dy_mm"])) < MIN_MOVE:
            if r["dx_mm"] or r["dy_mm"]:
                r["note"] = "位移 %.0f mm < %.0f ⇒ 不落盘" % (
                    max(abs(r["dx_mm"]), abs(r["dy_mm"])), MIN_MOVE)
            r["dx_mm"] = r["dy_mm"] = 0.0
    moved = [r for r in rows if r["dx_mm"] or r["dy_mm"]]
    print("配准：%d 层要动，%d 条边（%s）" % (len(moved), len(edges),
          ", ".join("%s↔%s" % (names[i], names[j]) for i, j in sorted(edges)) or "无"))
    if a.dry:
        print("（--dry：不写盘）")
        return 0
    arch = os.path.join(ROOT, "_archive", "raw_before_register_%s" % time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(arch, exist_ok=True)
    for _nm, p in floors:
        shutil.copy2(p, os.path.join(arch, os.path.basename(p)))
    for r in rows:
        if r["dx_mm"] or r["dy_mm"]:
            _translate_dxf(os.path.join(RAW, r["floor"] + ".dxf"), r["dx_mm"], r["dy_mm"])
        # 元数据里的原点跟着挪（原来写的是「图幅左下角 → 原点」的平移量）
        meta_p = os.path.join(RAW, r["floor"] + ".json")
        if os.path.exists(meta_p):
            try:
                with open(meta_p, encoding="utf-8") as fh:
                    mj = json.load(fh)
            except Exception:                                            # noqa: BLE001
                continue
            org = mj.get("origin") or [0.0, 0.0]
            old = ((mj.get("register") or {}).get("dx_mm") or 0.0,
                   (mj.get("register") or {}).get("dy_mm") or 0.0)
            mj["origin"] = [org[0] + r["dx_mm"] - old[0], org[1] + r["dy_mm"] - old[1]]
            mj["register"] = {"dx_mm": r["dx_mm"], "dy_mm": r["dy_mm"],
                              "anchor": r["anchor"], "conflict": r["conflict"]}
            with open(meta_p, "w", encoding="utf-8") as fh:
                json.dump(mj, fh, ensure_ascii=False)
    reg = {"schema": "cdut3d-registration/1",
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "rule": ("柱>楼梯>文字定案；本边墙族不作证 ⇒ 该边按 0（不动）；"
                    "差 > max(%.0f mm, %.0f%%) 算不作证；< %.0f mm 不落盘"
                    % (TOL, TOL_REL * 100, MIN_MOVE)),
           "sheets": rows}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=1)
    print("写 %s（平移前备份 %s）" % (OUT, arch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
