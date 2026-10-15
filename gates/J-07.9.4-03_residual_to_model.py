# -*- coding: utf-8 -*-
r"""判据 J-07.9.4-03：闭合 → 残段 → **buffer 成墙足迹** → 最终模型（把 -02 只证到的中间量接到交付件上）。

对应方案 §7.10「CAD 命令行实体化」行的**新出口门**，即 `-02` 自己写下的盲区②：
  「`residual` 的下游去向没量：残段在 `score_cell` 里被 buffer 成墙足迹，
    +300 mm 的足迹 vs +123.6 m 的足迹，**最终模型**差多少？」

★ 与 `-01` / `-02` 的分工（三条判据不许互相盖章）：
  · `-01` 量 **DXF 本身**（无损伤、有界、可重复）。
  · `-02` 量 **链里的中间量**（`load_walls_and_cols` + `wire` 的 `segs/quads/residual`）。
  · `-03` 量 **最终模型**：把 `wire()` 的第三条通路（残段）按**链自己的规则** buffer 成墙足迹
    （`a1/generic_wall.py:230-232` / `build_glb:262` 的 `s.buffer(WALL_T/2, cap_style=2)`），
    并成「模型足迹」，报出「残段涨了多少」→「模型足迹/体积涨了多少」。
    足迹再乘层高即立体体积（纯竖向挤出 ⇒ 体积 = 面积 × H，不需要真跑 trimesh）。

★★ 本判据存在的理由（先写下来，别等跑完才想）：
  `-02` 把闭合的代价归到「残段长度」上（定向 +300.0 mm / 盲扫 +123 621.6 mm，**412 倍**）。
  但**残段长度不是交付件**——交付件是模型。这条判据就是要问：
  **412 倍在最终模型上还剩多少倍？** 若最终模型上两臂几乎一样，那「412 倍」就只是中间量的放大镜，
  不能拿去当结论用（铁律 137 的邻里：**在中间量上有分辨力的尺子，到了交付件上未必还有**）。
  ★ 实测答案（2026-10-12）：**定向臂 Δ足迹 = 0**（那 300 mm 整个落在既有墙足迹里）⇒ 比值
    **分母为 0**，既不是 412 倍也不是「无穷倍」；盲扫臂 Δ足迹 **+28.507 m² / +102.6 m³**
    （占源件足迹 **0.757%**）。⇒ 「412 倍」**不能**搬到交付件上说。
    ★ 记账：比值的分母不是一个「恰好 0」——逐图幅并集的浮点尾数把它落成 **−6.139e-11 m²**
      （换基准那一趟是 4.866e-10 —— **尾数本身不是读数**）；拿盲扫臂的 28.507 m² 去除它，
      直接除会印出 **5.86e10** 这种**像结论的数**（早先一趟实测印出 58 587 484 510.8×，
      见 §10.0.5 第 25 条） ⇒ 低于 1e-6 m² 一律判为「分母为 0」。

★★ **同日二轮（2026-10-12）：被判的 Δ 一律改在「两个都过了一手 AutoCAD 的文件」之间取**
  —— 链补上「剔踏步」（A1 第五个缺口，判据 `J-09.2-A1d`）之后，本判据**由 PASS 变 FAIL**：
  定向臂 Δ足迹 **−1.263 m²**、C 覆盖率 99.96% < 源件 100.00%、零刺激地板 **−1.263 m²**
  （残段地板 **−1917.653718 mm**）。根因与 `-02` **同一条**：`DXFOUT` 过一手只让每个坐标动
  ~1.16e-9 mm（几何保真），却足以让冻结基线 `treadlib.py` **多剔 4 条**踏步线（组数 193 一条不变）。
  ⇒ 真正被测到的不是「闭合改了多少」，而是**交付链自己的足迹对 DXF 往返不中性**：
     源件 vs 过手件差 **−1.263 m²（−0.034%）**、残段差 **−1917.653718 mm**。
  ★ 地板（1.263 m²）比信号（A 条上限 0.072 m²）**大 18 倍**（1.263 ÷ 0.072 = 17.5，判词取整）
    ⇒ 「扣地板」会把 A 条的分辨力整条吃掉
    （同 §10.0.5 第 30 条：**口径的容差必须与地板同量级**）。
  ⇒ 正解 = **换基线**（不是改冻结基线，那是臆造）：
     · 新增基线臂 `neg` = **过一手 AutoCAD 但零刺激**（`TOL=−1` ⇒ 谁都不点名）那一份；
       `tgt`（定向）/`bln`（盲扫）的 Δ **一律相对 `neg` 取** ⇒ 那 4 条踏步的抖动
       **在两边结构性地抵消**（两臂的踏步集完全相同）；
     · 源件降为**并列读数**，其偏移（−1.263 m² / −1917.653718 mm）当场量出来、写进 json 与盲区⑦，
       **不许**拿它做分母或做差；
     · 正对照③ 随之改口径：**另起一次**零刺激（独立一次 AutoCAD 运行）⇒ `Δ足迹` 必须为 0
       —— 这比原来那条**更硬**：原来量的是「源件 vs 过手」，把往返本身的偏移也算成了噪声。

四件套（§10.0.1）：
  ① 量交付件本身 —— 量的是**按链自己的规则建出来的模型足迹**（逐图幅并集 / 覆盖率），不读日志、不读 rc
  ② 量具写明     —— `a1/generic_wall.py` 的 `wire()` + `WALL_T` + `a1/sheet_grid.py` 的图幅定位；
                    足迹并入用 `shapely.unary_union`（**精确**，不栅格 —— 栅格 50 mm 会把 0.07 m² 量没）
  ③ 盲区声明     —— 见下
  ④ 正对照必配   —— **五条**（见下）

★ 判据（全部为真才算过）：
  A. **残段真的变成了模型足迹（守恒 + 有界）**：两臂里
     `0 ≤ Δ足迹 ≤ Δ残段(≥50 mm 那一档) × WALL_T`；且 `Δ残段` 与**独立枚举**的
     「源件直读的缺口合计」同数（那一路不过 AutoCAD）。★ 上限是**由实测数算出来的**，不是拍的。
     ★ 不要求「定向臂必须改模型」—— 若 `Δ足迹(定向) = 0.000`（那 300 mm 整个落在既有墙足迹里），
       那是**发现**，不是失败；判据只要求它 ≤ 上限且**盲扫臂严格大于它**。
     ★ 二轮起这里的 Δ **相对基线臂 `neg`（过手零刺激）**，不相对源件（见上：口径）。
  B. **两臂在最终模型上分得开（分辨力）**：`Δ足迹(盲扫) > Δ足迹(定向)` 且
     `精确率(盲扫) < 精确率(基线)`、`IoU(盲扫) < IoU(基线)`（精确算术 ⇒ 严格不等即有效）。
  C. **覆盖率不因闭合而下降**（这是本条唯一的外部量：取样点来自**源件**全量墙线，`ref_segs`）
     —— `覆盖率min(定向) ≥ 覆盖率min(基线)`、`覆盖率min(盲扫) ≥ 覆盖率min(基线)`。
     ★★ **本条在本栋上结构性饱和**：**过手那三臂**（基线/定向/盲扫）读数恒相同（取样点来自源件墙线，而模型足迹按构造
        含这些墙线）⇒ **单看读数它是一条恒绿的判据**（铁律 137）。它的**牙在正对照②**
        （抽掉 90% 墙段 ⇒ 覆盖率必掉到一半以下）；② 一红，本门就 rc=1。判词里这一点必须印出来。
  D. 五条正对照**全部触发**。
  E. 有界：**两臂**（定向/盲扫）图幅数 == 源件图幅数；两份产出件在盘且下游载得动；耗时 < 预算；重跑逐位相同。

★ 正对照（不变红 = 判据没分辨力）：
  ① **假件（inflate）**：把**模型那一半**每条墙向外膨 120 mm（名义墙厚翻倍）⇒ 足迹必**涨**、精确率必**掉**。
     （这是 `score_cell` docstring 指定的假件开关：`refi` 与 `modi` 平时同源 ⇒ 只有膨模型那一半才有牙。）
  ② **缺件（抽 90% 墙段）**：足迹必**大跌**（≥ 一半）**且**覆盖率必掉到一半以下 —— 一条对照给
     **两把尺子**同时装牙：足迹尺（判据 A/B）与覆盖率尺（判据 C，否则 C 恒绿）。
  ③ **零刺激（TOL=−1 ⇒ 谁都不点名）**：**另起一次** AutoCAD 运行，产出的件必须与基线臂 `neg`
     （同样零刺激、另一次运行）**逐位相同** ⇒ `Δ足迹` 落在**零容差** `ZERO_STIM_TOL` 内。
     ★ 二轮改口径（原先是「源件 vs 这一次零刺激」，把往返偏移 −1.263 m² 也算成噪声）：
       现在被测的是**基线这份件自己可不可复现** —— 全判据的 Δ 都拿它当基准，
       它不可复现的话下面每个数都不算数。
     ★ 它也**不是「恰好 0」**：逐图幅 `unary_union` 有算术残差 ⇒ 容差由这条对照自己的残差地板定
       （取 1e-9 m² = 1 mm²），判词**照实印科学计数法**，不印 `+0.000000000`。
     （`TOL=0` 不是零：C006 有 12 条缺口本来就是 0.0 ⇒ 拿它当零刺激是错的。）
  ④ **坏输入可分**：喂**存在但不是 DXF 的**文件 ⇒ 六态必须 `!= OK`（不许静默成功，铁律 199）。
  ⑤ **可重复**：同参数**另开一个目录**再跑一遍 ⇒ 足迹/覆盖率**逐位相同**。
  ★ 另有一条**跨判据互证**（不是正对照）：本判据的盲扫臂用**冻结工具**
    `cad_close_walls.close_walls(..., tol_mm=1e9)` 造（TOL→∞ 即「凡是未闭合、顶点>2 的都闭」），
    而 `-02` 的盲扫是**自己内联**的 `_PEDIT _M _C` 全扫 ⇒ 两条**互不派生**的实现
    必须在同一根中间量（Δ残段）上同数。对不上就报出来。

★ 盲区（必须声明，盲区内的否定判词不算证据）：
  ① ★★ **足迹面积是「多少」的尺子，不是「对不对」的尺子** —— 盲扫那条最长 46.4 m 的幽灵墙
     在**面积**上只值几个 m²，它真正的危害是**横穿整层**（位置错）。本判据因此**不设**「面积占比 < x%」这种门，
     只报数 + 逐条指名的**长度**，并把它列成盲区。
  ② 只量**二维足迹**。体积由 `面积 × H` 换算（`build_glb` 是纯竖向挤出 ⇒ 等价）；
     将来若改成逐件不同高/带收分，这条换算失效。
  ③ 只走 `4.2墙体`（`WALL_LAYERS` 是四个层名，本判据只喂 C006 的墙层）+ 只 C006 一栋 + 本机 AutoCAD 2022。
  ④ **libs3d 那条链不量**：`D:\项目\libs3d\c006\wall_solid.py:46` 把**每一条**墙线都直接
     `buffer(120)` 成墙带（没有「残段」这一档）⇒ 新增段在那边的效果只会**更大**（不必再并集）；
     但它是**冻结基线**、脚本把路径写死在原目录，跑它会覆盖基线产物 ⇒ **本判据不跑它**（只作方向引用）。
  ⑤ `-02` 已有的「四边形数在 C006 上无分辨力」继续成立：本判据也**不**拿四边形数当判据。
  ⑥ ★★ **量具自身的口径偏差（本轮实测发现，已写进 json 的 `gauge_defect`）**：
     `score_cell` 的 `modA/refA/inter` 用 `fillg` → `ImageDraw.polygon(...)` 填栅格，
     **PIL 把边界像素一起填** ⇒ 每个多边形被**膨胀约半格**（25 mm）⇒ 面积系统性**偏大**。
     C006 四臂实测膨胀 **+20.70% ~ +20.82%**、`(栅格−精确) / (周长 × CELL/2) = 1.066 ~ 1.073`（规律吻合）。
     ★ **百分比不是常数** —— 它 ≈ (CELL/2)×周长 ÷ 面积，随足迹变：**剔踏步前**（墙输入含踏步
       4472.648 m² / 周长 28 780 m）同一律读 **+17.05% / k=1.060**。**k 稳定、百分比动** ⇒
       引用这个数必须连它那一版的足迹一起说（铁律 174：两个同名的量会印出像结论的数）。
     ⇒ 本判据的面积**一律用精确并集**（`unary_union`），栅格只用来做这条规律的交叉核对。
     ★ 连带风险（**本判据不判、只点名**）：方案 §10.1 若用 `score_cell` 的口径做
       「按列算的面积 vs 台账/图纸面积逐层对账」，会**整体带这一层偏高**。
  ⑦ ★★ **交付链的足迹对「DXF 过一手」不中性**（二轮新发现，读数：源件 vs 过手基线差
     **−1.263 m²（−0.034%）**、残段 **−1917.653718 mm**）：根因是冻结基线 `treadlib.py` 的
     踏步组判据（「窗口取连续段 + 散布 ≤0.35」）在**精确同偏移的重线**上是**刀口** ——
     1.16e-9 mm 的坐标抖动就能让 4 组踏步 11→12 条。本判据**不去改冻结基线**（那是臆造），
     只把基线换成**同样过手的件**让这层偏置结构性抵消，并**当场量出它的读数**。
     ★ 这个偏置**不是判据的噪声**，是**链的性质**：任何「拿源件当基准比交付件」的判据都会吃到它，
       量级 ~0.03%；若某天某条判据的上限小于它，那条判据就必须照这里的方式换基线。

用法: python J-07.9.4-03_residual_to_model.py            # 跑判据（约 6~8 min，起 6 次 AutoCAD）
     python J-07.9.4-03_residual_to_model.py --json o.json
"""
import os
import sys
import json
import time
import shutil
import tempfile
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf                        # noqa: E402
from shapely.ops import unary_union  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "a1"))
import cad_close_walls as CC      # noqa: E402
import generic_wall as GW         # noqa: E402
import sheet_grid as SG           # noqa: E402
import stage2_prepare_dxf as S2   # noqa: E402

SRC = r"D:\项目\gym3d\材料\dxf_output\C006-第六教学楼（逸夫楼）.dxf"
WORK = os.path.join(ROOT, "_out", "J-07.9.4-03")
OUT_02 = os.path.join(ROOT, "gates", "_out", "J-07.9.4-02.json")
TOL = 480.0
BLIND_TOL = 1e9        # 「盲扫」= TOL 取无穷大（凡未闭合、顶点 > 2 的都闭）
PREFIX = "4.2"
MARGIN = 8000.0        # 与 J-09.2-A1 同一取值（该值在那边是过闸的）
WALL_T = GW.WALL_T     # 240.0 mm，未配对线的缓冲墙厚
H = GW.H               # 3600.0 mm 层高（只影响体积换算）
MIN_SEG_MM = 50.0      # 链自己的门：残段短于它就不缓冲（`generic_wall.py:210/231`）
SEC_BUDGET = 1800.0
#   ★ 判「两个足迹是不是同一个」的零容差 —— 由正对照③（真零刺激）自己的**实测残差地板**定，
#     不是拍的：足迹由逐图幅 `unary_union` 求和，纯算术残差实测 ~2.5e-10 m²（判词里印出来）。
#     取 1e-9 m²（= 1 mm²）：在 ~3764 m² 的模型上相对量 2.7e-13 ⇒ 物理上无意义，真实几何远大于它。
ZERO_STIM_TOL = 1e-9
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4


# ----------------------------------------------------------------- 尺子（链自己的建模规则，精确版）
def cell_foot(segs, cols, box, marg, inflate=0.0):
    """一个图幅矩形：返回 (并集几何, 足迹 m², 被缓冲的残段总长 mm)。

    ★ 这是 `a1/generic_wall.py:226-236`（`score_cell` 里 `modi`/`fp` 那一半）的**逐行复刻**。
      复刻是**故意**的：栅格版（`score_cell` 返回的 `modA`）拿不到精确面积，而本判据要量的
      正是「+0.07 m²」这种小数（50 mm 栅格一格就是 0.0025 m² ⇒ 28 格就把信号量没一半）。
      复刻的正确性**不由我担保**，由下面 `arm_metrics` 里那行**两条独立实现同数**的交叉核对来守。
    """
    x0, y0, x1, y1 = box
    x0 -= marg
    x1 += marg
    y0 -= marg
    y1 += marg

    def inbox(g):
        b = g.bounds
        return b[0] <= x1 and b[2] >= x0 and b[1] <= y1 and b[3] >= y0

    sgs = [s for s in segs if inbox(s)]
    quads, unp = GW.wire(sgs)
    fp = [g for g in quads if g.is_valid and not g.is_empty]
    resid_mm = 0.0
    for s in unp:
        if s.length >= MIN_SEG_MM:
            resid_mm += s.length
            fp.append(s.buffer(WALL_T / 2.0, cap_style=2, join_style=2))
    for c in cols:
        if inbox(c):
            fp.append(c)
    if inflate:
        fp = [g.buffer(inflate, join_style=2) for g in fp]
    fp = [g for g in fp if g.is_valid and not g.is_empty]
    if not fp:
        return None, 0.0, resid_mm
    u = unary_union(fp)
    return u, float(u.area) / 1e6, resid_mm


def folds(cells, segs, cols, inflate=0.0):
    """逐图幅的 (并集, 面积, 残段长)。C006 的 13 张图框**平铺不重叠**（实测：无 margin 时重叠对 0
    ⇒ 加 8 m margin 后行距 25 m > 16 m 仍不重叠）⇒ 逐图幅求和是**真分割**，不会重复计数。"""
    return [cell_foot(segs, cols, c["bbox"], MARGIN, inflate) for c in cells]


def cover_min(segs, cols, ref_segs, cells, marg=None):
    """链自己的覆盖率读数（`score_cell` 的 `lc`），取逐图幅最小值。

    ★ 单独抽出来是**为了给判据 C 配正对照**：C 条在本栋上过手三臂读数恒相同（结构性饱和 ——
      取样点来自源件墙线，而模型足迹里按构造就含这些墙线）⇒ 它**天生没有分辨力**（铁律 137）。
      只有喂进一个「模型缺件」的输入证明它**会掉**，C 才不是一条恒绿的判据。
    """
    m = MARGIN if marg is None else marg
    lcs = []
    for c in cells:
        x0, y0, x1, y1 = c["bbox"]
        _rr, _mm, _ii, lc, _nq, _nu = GW.score_cell(segs, cols, x0, x1, y0, y1, m,
                                                   ref_segs=ref_segs)
        if lc == lc:
            lcs.append(lc)
    return (min(lcs) if lcs else None), len(lcs)


def arm_metrics(dxf, cells, ref_segs, ref_cols, before, inflate=0.0):
    """一个臂的模型读数。`before` = 源件模型的逐图幅并集（各臂共用 ⇒ 只算一次）。"""
    segs, cols, _lab = GW.load_walls_and_cols(dxf)
    F = folds(cells, segs, cols, inflate)
    foot = sum(a for (_u, a, _r) in F)
    perim_m = sum((u.length / 1000.0) for (u, _a, _r) in F if u is not None)
    prev = sum(a for (_u, a, _r) in before)
    inter = 0.0
    for (u, _a, _r), (ub, _ab, _rb) in zip(F, before):
        if u is not None and ub is not None:
            inter += float(u.intersection(ub).area) / 1e6
    # 链自己的覆盖率（`lc`，取样点来自 `ref_segs`）＋ 交叉核对用的栅格 modA（`refi`/`modi` 同源）
    lcs, _raster = [], 0.0
    for c in cells:
        x0, y0, x1, y1 = c["bbox"]
        _rr, m, _ii, lc, _nq, _nu = GW.score_cell(segs, cols, x0, x1, y0, y1, MARGIN,
                                                  ref_segs=ref_segs)
        _raster += m
        if lc == lc:               # 去 NaN（该图幅没有墙线取样点 ⇒ 「没量到」，不是「量到 0」）
            lcs.append(lc)
    return {"n_segs": len(segs), "n_cols": len(cols),
            "foot_m2": foot, "vol_m3": foot * H / 1000.0,
            "perim_m": perim_m,
            "resid_mm": sum(r for (_u, _a, r) in F),
            "before_m2": prev, "inter_m2": inter,
            "recall": (100.0 * inter / prev) if prev else None,
            "prec": (100.0 * inter / foot) if foot else None,
            "iou": (100.0 * inter / (prev + foot - inter)) if (prev + foot - inter) else None,
            "raster_modA": _raster,
            "cov_min": (min(lcs) if lcs else None), "cov_n": len(lcs),
            "cells": len(cells)}


def whole_resid(dxf):
    """**全模型空间**口径的残段总长（不切图幅、不按长度过滤）—— 与 `-02` 的 `measure()` 同口径，
    只用于跨判据互证。

    ★ 它与 `arm_metrics` 的 `resid_mm` **不是同一个量**（那个是逐图幅、且只计 ≥50 mm 的可缓冲段）
      —— 铁律 174：同名的两个量必须死掉一个，这里给它们分开的名字（`resid_whole_mm` / `resid_cell_mm`）。
    """
    segs, _c, _l = GW.load_walls_and_cols(dxf)
    return float(sum(s.length for s in GW.wire(segs)[1]))


def gaps_from_source(tol_mm):
    """**独立来源**：直接从源 DXF 枚举会被点名的缺口（不过 AutoCAD）。
    与实测那条路唯一的共同点是「都读源 DXF 的几何」。"""
    ps = CC.wall_polys(SRC, PREFIX)
    gs = [CC.gap_mm(p) for (_h, p, cl) in ps if not cl and len(p) > 2 and CC.gap_mm(p) <= tol_mm]
    return gs


def run_close(outdir, tol_mm):
    """跑一步闭合（冻结工具 `stage2_prepare_dxf`）。`tol_mm=1e9` 就是盲扫。"""
    return S2.prepare(SRC, outdir, tol_mm, PREFIX)


# ----------------------------------------------------------------- 正对照
def ctl_zero(tmp, neg_arm, cells, ref_segs, ref_cols, before):
    """③ 零刺激：TOL=−1 ⇒ `gap <= -1` 恒假 ⇒ 谁都不点名。这是**真零**。

    ★★ 二轮改口径：**另起一次** AutoCAD 运行的零刺激件，必须与基线臂 `neg`（另一次零刺激运行）
      在**被判的量**上逐位相同 —— 全判据的 Δ 都以 `neg` 为基准，它不可复现的话下面每个数都不算数。
      （原来量的是「源件 vs 这一次零刺激」，把 **DXF 往返本身的偏置**（−1.263 m² / −1917.653718 mm）
        也算成了噪声 ⇒ 地板比 A 条上限大 18 倍，见 docstring 二轮。）
    """
    r = S2.prepare(SRC, os.path.join(tmp, "zero"), -1.0, PREFIX)
    if r["state"] != S2.OK:
        return False, {}, "零刺激没跑成（state=%s）" % r["state"]
    m = arm_metrics(r["out_dxf"], cells, ref_segs, ref_cols, before)
    d_foot = m["foot_m2"] - neg_arm["foot_m2"]
    d_res = m["resid_mm"] - neg_arm["resid_mm"]
    ok = (r["picked"] == 0 and abs(d_foot) <= ZERO_STIM_TOL and abs(d_res) <= 1e-6)
    return bool(ok), {"picked": r["picked"], "out": r["out_dxf"],
                      "d_foot_m2": d_foot, "d_resid_mm": d_res,
                      "foot_m2": m["foot_m2"]}, \
        ("点名 %d 条 ⇒ %s；Δ足迹（相对基线）%+.3e m² / Δ残段 %+.6f mm，"
         "容差 %.0e m²（本对照自己的浮点残差地板）⇒ %s"
         % (r["picked"], "真零 ✓" if r["picked"] == 0 else "★ 不是零 ✗", d_foot, d_res,
            ZERO_STIM_TOL, "基线可复现 ✓" if ok else "★ 基线两遍不一样 ✗"))


def ctl_bad_input(tmp):
    """④ 坏输入可分：喂**存在但不是 DXF 的**文件（喂不存在的路径会被前置检查拦成 SKIP，测的是我们的 if）。"""
    bad = os.path.join(tmp, "not_a_dxf.dxf")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("这不是 DXF，只是一段文本。\n")
    r = S2.prepare(bad, os.path.join(tmp, "bad"), TOL, PREFIX)
    ok = r["state"] != S2.OK
    return bool(ok), {"state": r["state"]}, ("状态 = %s ⇒ %s" % (r["state"], "可分 ✓" if ok else "★ 静默成功 ✗"))


def cross_check_02(blind_resid_mm):
    """跨判据互证（不是正对照）：本判据的盲扫臂 vs `-02` 记录的盲扫 Δ残段。"""
    if not os.path.isfile(OUT_02):
        return None, "`-02` 的 json 不在盘上 ⇒ **没量到**（不是「不一致」）"
    age_h = (time.time() - os.path.getmtime(OUT_02)) / 3600.0
    try:
        d = json.load(open(OUT_02, encoding="utf-8"))
        ref = float(d["blind"]["d_resid"])
    except Exception as e:
        return None, "`-02` 的 json 读不动（%s）⇒ **没量到**" % type(e).__name__
    ok = abs(blind_resid_mm - ref) <= 1e-6
    return bool(ok), ("`-02` 记的盲扫 Δ残段 %.1f mm ／ 本次 %.1f mm（该 json 已 %.1f h）⇒ %s"
                      % (ref, blind_resid_mm, age_h, "同数 ✓" if ok else "★ 两个实现不同数 ✗"))


# ----------------------------------------------------------------- tee
class _Tee(object):
    def __init__(self, *paths):
        self.fs = [open(p, "w", encoding="utf-8") for p in paths]

    def write(self, s):
        for f in self.fs:
            f.write(s)

    def flush(self):
        for f in self.fs:
            f.flush()


def _run(a):
    t_all = time.time()
    if not os.path.isfile(SRC):
        print("★ 没量到：源 DXF 不在盘上 ⇒ %s" % SRC)
        return RC_NOGAUGE
    if not os.path.isfile(CC.EXE):
        print("★ 没量到：accoreconsole 不在盘上 ⇒ %s" % CC.EXE)
        return RC_NOGAUGE
    os.makedirs(WORK, exist_ok=True)
    fails = []

    # ---- 图幅（取源件一次，四臂共用；臂自己的图幅数另行核对，见 E）
    msp = ezdxf.readfile(SRC).modelspace()
    layer = SG.find_frame_layer(msp, None)
    cells = SG.classify(SG.merge_pairs(SG.collect_frames(msp, layer)))[1]
    print("== 源件图幅（`a1/sheet_grid.py` 认的） ==")
    print("  C006 墙层图幅 %d 张（平铺不重叠 ⇒ 逐图幅求和是真分割）" % len(cells))

    # ---- 源件模型（= 「闭合前」的参照，各臂共用）
    ref_segs, ref_cols, _lab = GW.load_walls_and_cols(SRC)
    print("\n== 建「闭合前」的模型足迹（各臂共用的参照） ==")
    t = time.time()
    before = folds(cells, ref_segs, ref_cols)
    before_m2 = sum(x[1] for x in before)
    print("  墙段 %d 柱 %d ⇒ 足迹 %.1f m²（%.1fs）" % (len(ref_segs), len(ref_cols),
                                                      before_m2, time.time() - t))

    # ---- 四臂（`neg` = 过手零刺激基线，二轮新增）
    arms = {}
    print("\n== 四臂（`neg` = 过手零刺激基线） ==")
    src = {"dxf": SRC, "picked": 0, "secs": 0.0}
    r_t = run_close(os.path.join(WORK, "run"), TOL)
    if r_t["state"] != S2.OK:
        print("  ★ 定向臂没跑成：state=%s detail=%s" % (r_t["state"], str(r_t.get("detail"))[:80]))
        print("\n★ 判词：**没量到**（不是判红）—— 没跑出可比的前后两份件，A~E 无从落判")
        return RC_NOGAUGE
    r_b = run_close(os.path.join(WORK, "blind"), BLIND_TOL)
    if r_b["state"] != S2.OK:
        print("  ★ 盲扫臂没跑成：state=%s detail=%s" % (r_b["state"], str(r_b.get("detail"))[:80]))
        print("\n★ 判词：**没量到**（不是判红）")
        return RC_NOGAUGE
    # ---- 基线臂 `neg`：**过一手 AutoCAD 但零刺激**（TOL=−1 ⇒ 谁都不点名）。
    #   ★★ 被判的 Δ 一律相对它取：那 4 条踏步的刀口抖动在两个**都过手**的文件之间结构性抵消。
    #      拿源件当基准会把「交付链对 DXF 往返不中性」这层偏置（−1.263 m² / −1917.653718 mm）
    #      算成噪声地板，而它比 A 条的上限（0.072 m²）大 18 倍 ⇒ 分辨力整条丢掉（见 docstring 二轮）。
    r_n = run_close(os.path.join(WORK, "neg"), -1.0)
    if r_n["state"] != S2.OK or r_n["picked"] != 0:
        print("  ★ 基线臂没跑成/不是零刺激：state=%s picked=%s" % (r_n["state"], r_n.get("picked")))
        print("\n★ 判词：**没量到**（不是判红）—— 没有可比对的同口径基线，A~E 无从落判")
        return RC_NOGAUGE
    print("  定向 点名 %d 条（TOL=%g）  %.1fs   盲扫 点名 %d 条（TOL=1e9）  %.1fs   "
          "基线 点名 %d 条（TOL=−1，过手零刺激）"
          % (r_t["picked"], TOL, r_t.get("secs", -1), r_b["picked"], r_b.get("secs", -1),
             r_n["picked"]))
    print("  ★ 盲扫臂由**冻结工具** `close_walls(tol_mm=1e9)` 造（TOL→∞ 即全闭），"
          "与 `-02` 内联的全扫是两套互不派生的实现。")

    t = time.time()
    for nm, dxf in (("src", SRC), ("neg", r_n["out_dxf"]),
                    ("tgt", r_t["out_dxf"]), ("bln", r_b["out_dxf"])):
        arms[nm] = arm_metrics(dxf, cells, ref_segs, ref_cols, before)
        am = arms[nm]        # ★ 不叫 `a`：外层 argparse 命名空间叫 `a`，遮蔽后会炸在写 json 那一步
        print("  %-4s 墙段%6d  足迹 %10.3f m²  体积 %10.1f m³  残段 %13.1f mm  覆盖率min %s"
              % (nm, am["n_segs"], am["foot_m2"], am["vol_m3"], am["resid_mm"],
                 "—" if am["cov_min"] is None else "%.2f%%" % am["cov_min"]))
    print("  （四臂建模用时 %.1fs）" % (time.time() - t))

    # ---- 交叉核对：**不是**要求「相等」，而是要求差被一条几何规律解释掉
    #   ★★ 实测发现：`score_cell` 的 `modA` 系统性**偏大**（C006 上 +17%），原因是
    #      `fillg` 用 `ImageDraw.polygon(...)`，PIL 把**边界像素一起填** ⇒ 每个多边形被
    #      膨胀约半格（CELL/2 = 25 mm）⇒ Δ面积 ≈ (CELL/2) × 周长。这不是噪声，是**口径偏差**
    #      （细构件偏得最狠：240 mm 墙带只有 4.8 格）。
    #   ⇒ 判据：`k = (栅格 − 精确) / (周长 × CELL/2)` 必须落在 [0.5, 1.6]
    #      （= 每边膨胀 0.25~0.8 格）。若我复刻时**漏了一整类构件**，精确值会偏小 ⇒ k 冲过 1.6。
    print("\n== 交叉核对：精确并集 vs `score_cell` 的栅格 modA（差必须被「半格膨胀 × 周长」解释掉） ==")
    devs = {}
    okX = True
    for nm in ("src", "neg", "tgt", "bln"):
        am = arms[nm]
        e, g_, pm = am["foot_m2"], am["raster_modA"], am["perim_m"]
        k = ((g_ - e) / (pm * GW.CELL / 2.0 / 1000.0)) if pm else None
        devs[nm] = {"exact_m2": e, "raster_m2": g_, "perim_m": pm,
                    "inflation_pct": (100.0 * (g_ - e) / e) if e else None, "k": k}
        good = (k is not None) and (0.5 <= k <= 1.6)
        okX &= good
        print("  %-4s 精确 %10.3f  栅格 %10.3f  （%+.2f%%）  周长 %8.1f m  ⇒ k=%.3f %s"
              % (nm, e, g_, devs[nm]["inflation_pct"], pm, k if k is not None else float("nan"),
                 "✓" if good else "✗"))
    print("  ★★ 结论：栅格面积**不是**精确面积，它多出一层「半格膨胀」；本判据的面积一律用精确并集，"
          "栅格只作交叉核对。")
    if not okX:
        fails.append("X 精确/栅格差未被半格膨胀规律解释（复刻可能漏件）")

    # ---- 独立来源：源件直读的缺口
    gaps_t = gaps_from_source(TOL)
    gaps_b = gaps_from_source(BLIND_TOL)
    sum_t, sum_b = sum(gaps_t), sum(gaps_b)
    pred_t = sum(g for g in gaps_t if g >= MIN_SEG_MM) * WALL_T / 1e6
    pred_b = sum(g for g in gaps_b if g >= MIN_SEG_MM) * WALL_T / 1e6
    print("\n== 独立来源（源件直读、不过 AutoCAD） ==")
    print("  定向 缺口 %d 条 / 合计 %.1f mm（其中 ≥50 mm 的 %d 条）⇒ 足迹上限 %.3f m²"
          % (len(gaps_t), sum_t, sum(g >= MIN_SEG_MM for g in gaps_t), pred_t))
    print("  盲扫 缺口 %d 条 / 合计 %.1f mm（最长 %.1f m）⇒ 足迹上限 %.3f m²"
          % (len(gaps_b), sum_b, (max(gaps_b) / 1000.0 if gaps_b else 0.0), pred_b))

    #   ★★ 二轮：Δ 相对**基线臂 `neg`**（过手零刺激），不相对源件。
    d_ft = arms["tgt"]["foot_m2"] - arms["neg"]["foot_m2"]
    d_fb = arms["bln"]["foot_m2"] - arms["neg"]["foot_m2"]
    d_rt = arms["tgt"]["resid_mm"] - arms["neg"]["resid_mm"]
    d_rb = arms["bln"]["resid_mm"] - arms["neg"]["resid_mm"]
    #   ★ 源件那一份照报（并列读数，**不判**）：它包含「交付链对 DXF 往返不中性」这层偏置。
    src_floor_f = arms["neg"]["foot_m2"] - arms["src"]["foot_m2"]
    src_floor_r = arms["neg"]["resid_mm"] - arms["src"]["resid_mm"]
    print("\n== 基线口径声明（被判的 Δ 一律相对 `neg`，**不**相对源件） ==")
    print("  基线臂 `neg` = 过一手 AutoCAD 但零刺激（TOL=−1）。源件 vs 它：Δ足迹 %+.3f m²（%+.4f%%）、"
          "Δ残段 %+.6f mm"
          % (src_floor_f, 100.0 * src_floor_f / arms["src"]["foot_m2"] if arms["src"]["foot_m2"] else 0.0,
             src_floor_r))
    print("  ★ 这一层是**链对 DXF 往返的不中性**（冻结基线 `treadlib.py` 过手多剔 4 条踏步，盲区⑦），"
          "不是算术噪声：它比 A 条上限 %.3f m² 大 %.0f 倍 ⇒ 拿源件当基准会把 A 条的分辨力整条吃掉。"
          % (pred_t, (abs(src_floor_f) / pred_t) if pred_t else float("nan")))
    print("\n== Δ（相对基线 `neg`） ==")
    print("  %-4s %12s %12s %14s %12s" % ("臂", "Δ足迹 m²", "Δ体积 m³", "Δ残段 mm", "足迹上限 m²"))
    for nm, d_f, d_r, p in (("tgt", d_ft, d_rt, pred_t), ("bln", d_fb, d_rb, pred_b)):
        print("  %-4s %12.3f %12.3f %14.1f %12.3f"
              % (nm, d_f, d_f * H / 1000.0, d_r, p))
    print("  ★ 定向臂残段 Δ %.1f mm ⇒ 足迹 Δ %.3f m²；盲扫臂残段 Δ %.1f mm ⇒ 足迹 Δ %.3f m²"
          % (d_rt, d_ft, d_rb, d_fb))
    #   ★★ 比值的分母必须点名（铁律 197 的同族）：`d_ft` 实测不是**恰好** 0 而是 ~1e-13 m²
    #      （逐图幅并集的浮点尾数）⇒ 直接除会印出 5.9e10 这种「像结论的数」。低于 1e-6 m²
    #      一律当 0 处理，判词写「分母为 0」，不印比值。
    ZERO_M2 = 1e-6
    foot_ratio_t = None if abs(d_ft) < ZERO_M2 else (d_fb / d_ft)
    print("  ★ 中间量上的倍数 %.1f× ⇒ 最终模型上的倍数 %s"
          % ((d_rb / d_rt) if d_rt else float("inf"),
             ("%.1f×" % foot_ratio_t) if foot_ratio_t is not None
             else "**分母为 0**（定向臂 Δ足迹 %.3e m² < %.0e ⇒ 它是浮点尾数，不是比值）"
                  % (d_ft, ZERO_M2)))

    # ---- A
    print("\n== A. 残段真的变成了模型足迹（守恒 + 有界） ==")
    okA = True
    for nm, d_f, d_r, p in (("tgt", d_ft, d_rt, pred_t), ("bln", d_fb, d_rb, pred_b)):
        good = (d_f >= -1e-9) and (d_f <= p + 1e-9)
        if nm == "bln":
            good = good and d_f > 0.0          # 盲扫必改模型（否则这条判据无从落判）
        okA &= good
        print("  %-4s Δ足迹 %+.3f m²，且 ≤ 上限 %.3f m²（=%d 条缺口 ≥50 mm × 240 mm）⇒ %s"
              % (nm, d_f, p, sum(x >= MIN_SEG_MM for x in (gaps_t if nm == "tgt" else gaps_b)),
                 "✓" if good else "✗"))
    # 实测 Δ残段 与 独立枚举 必须同数
    tolA = 1e-3 * max(sum_t, 1.0)
    okD = (abs(d_rt - sum(g for g in gaps_t if g >= MIN_SEG_MM)) <= tolA
           and abs(d_rb - sum(g for g in gaps_b if g >= MIN_SEG_MM)) <= tolA)
    okA &= okD
    print("  独立枚举 vs 实测 Δ残段：定向 %.6f vs %.6f ／ 盲扫 %.6f vs %.6f（容差 %.6f）⇒ %s"
          % (sum(g for g in gaps_t if g >= MIN_SEG_MM), d_rt,
             sum(g for g in gaps_b if g >= MIN_SEG_MM), d_rb, tolA, "✓" if okD else "✗"))
    if not okA:
        fails.append("A 残段→足迹不守恒/不同数")

    # ---- B
    print("\n== B. 两臂在最终模型上分得开（分辨力） ==")
    p_s, p_t, p_b = arms["src"]["prec"], arms["tgt"]["prec"], arms["bln"]["prec"]
    i_s, i_t, i_b = arms["src"]["iou"], arms["tgt"]["iou"], arms["bln"]["iou"]
    p_n, i_n = arms["neg"]["prec"], arms["neg"]["iou"]
    okB = (d_fb > d_ft) and (p_b < p_n) and (i_b < i_n)
    for nm in ("src", "neg", "tgt", "bln"):
        am = arms[nm]
        print("  %-4s 召回 %.4f%%  精确 %.4f%%  IoU %.4f%%"
              % (nm, am["recall"], am["prec"], am["iou"]))
    print("  Δ足迹 盲扫 %.3f > 定向 %.3f ；精确率 盲扫 %.4f%% < 基线 %.4f%% ；"
          "IoU 盲扫 %.4f%% < 基线 %.4f%% ⇒ %s"
          % (d_fb, d_ft, p_b, p_n, i_b, i_n, "✓" if okB else "✗"))
    print("  ★ 「精确率/IoU」的分母是**模型足迹**、基准是源件模型（`before`）⇒ 这一条不受基线选择影响；"
          "源件臂读数（精确 %.4f%% / IoU %.4f%%）照印，不判。" % (p_s, i_s))
    if not okB:
        fails.append("B 最终模型上分不开两臂")

    # ---- C
    print("\n== C. 覆盖率（唯一外部量：取样点来自源件全量墙线）不因闭合下降 ==")
    cs, ct, cb = arms["src"]["cov_min"], arms["tgt"]["cov_min"], arms["bln"]["cov_min"]
    cn = arms["neg"]["cov_min"]
    okC = (ct is not None) and (cb is not None) and cn is not None and ct >= cn and cb >= cn
    print("  源件 %s ／ **基线** %s ／ 定向 %s ／ 盲扫 %s（@ %d 图幅）⇒ %s"
          % ("%.2f%%" % cs if cs is not None else "—",
             "%.2f%%" % cn if cn is not None else "—",
             "%.2f%%" % ct if ct is not None else "—",
             "%.2f%%" % cb if cb is not None else "—", arms["src"]["cov_n"],
             "✓" if okC else "✗"))
    print("  ★ 判的是「定向/盲扫 ≥ **基线**」；源件那一格比基线**高** %.4f 个百分点，是因为"
          "**取样点取自源件的未过手墙线**，而那 4 条踏步线过手后已被剔 ⇒ 差不是闭合造成的（盲区⑦）；"
          "拿源件当基准会把这条差记到闭合头上。"
          % (cs - cn))
    print("  ★ 过手那三臂（基线/定向/盲扫）读数**相同** ⇒ 本条在**本栋上无分辨力**（结构性饱和）："
          "取样点来自源件墙线，而模型足迹按构造含这些墙线（过手那三臂的踏步集相同）。"
          "它的**牙**在正对照②（抽掉 90% 段 ⇒ 覆盖率必掉）；② 不过则本门 rc=1。")
    if not okC:
        fails.append("C 覆盖率因闭合下降")

    # ---- 正对照
    print("\n== 正对照 ==")
    tmp = tempfile.mkdtemp(prefix="j03ctl_")
    # ① 假件
    infl = arm_metrics(SRC, cells, ref_segs, ref_cols, before, inflate=WALL_T / 2.0)
    d_inf = infl["foot_m2"] - arms["src"]["foot_m2"]
    c1 = (d_inf >= 0.05 * arms["src"]["foot_m2"]) and (infl["prec"] < p_s)
    print("  ① 假件（模型墙各膨 %.0f mm）: %s  足迹 %+.1f m²（%+.2f%%）、精确率 %.4f%% < %.4f%%"
          % (WALL_T / 2.0, "✓" if c1 else "✗", d_inf,
             100.0 * d_inf / arms["src"]["foot_m2"], infl["prec"], p_s))
    # ② 缺件 —— ★ 一条对照同时给**两把尺子**装上牙：足迹尺（判据 A/B）与覆盖率尺（判据 C）
    keep = ref_segs[::10]
    F_d = folds(cells, keep, ref_cols)
    foot_d = sum(x[1] for x in F_d)
    cov_d, cov_d_n = cover_min(keep, ref_cols, ref_segs, cells)
    c2f = foot_d <= 0.5 * arms["src"]["foot_m2"]
    c2c = (cov_d is not None) and (cov_d <= 0.5 * cs)
    c2 = c2f and c2c
    print("  ② 缺件（抽掉 90%% 墙段）  : %s  足迹 %.1f m² ≤ 一半 %.1f m²（%s）"
          "；覆盖率 %.2f%% ≤ 一半 %.2f%%（%s）"
          % ("✓" if c2 else "✗", foot_d, 0.5 * arms["src"]["foot_m2"], "✓" if c2f else "✗",
             cov_d if cov_d is not None else float("nan"), 0.5 * cs, "✓" if c2c else "✗"))
    print("     ★★ 这条对照是判据 C 的**牙**：C 的过手三臂读数**相同**（取样点来自源件墙线，"
          "按构造就在模型足迹里）⇒ 不喂缺件，C 是一条**恒绿**的判据（铁律 137）。")
    # ③ 零刺激（另起一次；必须与基线臂 `neg` 逐位相同）
    c3, d3, t3 = ctl_zero(tmp, arms["neg"], cells, ref_segs, ref_cols, before)
    zero_foot = d3.get("d_foot_m2")
    print("  ③ 零刺激（TOL=−1，另起一次）: %s  %s" % ("✓" if c3 else "✗", t3))
    # ④ 坏输入
    c4, d4, t4 = ctl_bad_input(tmp)
    print("  ④ 坏输入可分             : %s  %s" % ("✓" if c4 else "✗", t4))
    # ⑤ 可重复
    r2 = run_close(os.path.join(WORK, "run2"), TOL)
    if r2["state"] == S2.OK:
        a2 = arm_metrics(r2["out_dxf"], cells, ref_segs, ref_cols, before)
        c5 = (abs(a2["foot_m2"] - arms["tgt"]["foot_m2"]) <= 1e-9
              and abs(a2["resid_mm"] - arms["tgt"]["resid_mm"]) <= 1e-6
              and a2["cov_min"] == arms["tgt"]["cov_min"])
        t5 = "第二遍 足迹 %.9f m² 残段 %.6f mm ⇒ %s" % (a2["foot_m2"], a2["resid_mm"],
                                                       "逐位相同 ✓" if c5 else "★ 两遍不一样 ✗")
    else:
        c5, t5 = False, "第二遍没跑成（state=%s）" % r2["state"]
    print("  ⑤ 可重复                 : %s  %s" % ("✓" if c5 else "✗", t5))
    shutil.rmtree(tmp, ignore_errors=True)
    for c, tag in ((c1, "C1"), (c2, "C2"), (c3, "C3"), (c4, "C4"), (c5, "C5")):
        if not c:
            fails.append("对照%s 未触发" % tag)

    # ---- 跨判据互证（读数，不是正对照）—— 必须与 -02 **同口径**（全模型空间），不是逐图幅那个
    print("\n== 跨判据互证（不是正对照；须与 `-02` 同口径） ==")
    rw_src = whole_resid(SRC)
    rw_neg = whole_resid(r_n["out_dxf"])
    rw_bln = whole_resid(r_b["out_dxf"])
    d_rb_whole = rw_bln - rw_neg      # ★ 二轮：相对**过手基线**，与 -02 的纯墙口径同口径
    print("  全模型空间口径 Δ残段 %+.6f mm（相对基线的**同口径**读数 = `-02` 的纯墙口径）；"
          "逐图幅口径(≥50 mm) %+.6f mm —— ★ 两个同名的量，别混"
          % (d_rb_whole, d_rb))
    print("  并列读数（不判）：源件 vs 基线 Δ残段 %+.6f mm ＝ 那条踏步刀口的偏置（盲区⑦）"
          % (rw_neg - rw_src))
    x_ok, x_txt = cross_check_02(d_rb_whole)
    print("  ", x_txt)

    # ---- E
    print("\n== E. 有界 ==")
    n_src = len(cells)
    counts = {}
    for nm, dxf in (("tgt", r_t["out_dxf"]), ("bln", r_b["out_dxf"])):
        m = ezdxf.readfile(dxf).modelspace()
        lay = SG.find_frame_layer(m, None)
        counts[nm] = len(SG.classify(SG.merge_pairs(SG.collect_frames(m, lay)))[1])
    secs = (r_t.get("secs") or 0) + (r_b.get("secs") or 0) + (r2.get("secs") or 0)
    okE = (counts["tgt"] == n_src == counts["bln"]
           and os.path.exists(r_t["out_dxf"]) and os.path.exists(r_b["out_dxf"])
           and bool(r_t.get("downstream")) and bool(r_b.get("downstream"))
           and secs < SEC_BUDGET)
    print("  图幅数 源件 %d ／ 定向 %d ／ 盲扫 %d ；产出件在盘 %s/%s ；下游载得动 %s/%s ；"
          "AutoCAD %.1fs < %.0fs ⇒ %s"
          % (n_src, counts["tgt"], counts["bln"],
             os.path.exists(r_t["out_dxf"]), os.path.exists(r_b["out_dxf"]),
             bool(r_t.get("downstream")), bool(r_b.get("downstream")), secs, SEC_BUDGET,
             "✓" if okE else "✗"))
    if not okE:
        fails.append("E 时间/图幅数/产出件")

    print("\n===== 判词 =====")
    rc = RC_FAIL if fails else RC_PASS
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
    else:
        print("  PASS  rc=0   A/B/C/D/E 全绿，五条正对照全触发")
        print("  ★ 基线口径：被判的 Δ 相对 `neg`（过手零刺激）；源件那一份只报不判"
              "（它含 %.3f m² 的往返偏置，盲区⑦）" % src_floor_f)
        print("  ★ C 条四臂（源件那一格除外）同为 %.2f%% ⇒ **读数无分辨力**，"
              "它的牙是正对照②（覆盖率 %.2f%% ≤ 一半 %.2f%%）"
              % ((cn if cn is not None else float("nan")),
                 cov_d if cov_d is not None else float("nan"), 0.5 * cs))
    print("  用时 %.1fs" % (time.time() - t_all))

    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        json.dump({
            "pass": rc == 0,
            "spec": {"wall_t_mm": WALL_T, "H_mm": H, "margin_mm": MARGIN,
                     "min_seg_mm": MIN_SEG_MM, "tol_targeted": TOL, "tol_blind": BLIND_TOL,
                     "n_cells": n_src, "src": SRC,
                     "raster_cell_mm": GW.CELL},
            "arms": {nm: dict(
                {k: arms[nm][k] for k in
                 ("n_segs", "foot_m2", "vol_m3", "perim_m", "before_m2",
                  "inter_m2", "recall", "prec", "iou", "raster_modA", "cov_min", "cov_n")},
                resid_cell_mm=arms[nm]["resid_mm"]) for nm in ("src", "neg", "tgt", "bln")},
            "baseline": {"arm": "neg",
                         "what": "过一手 AutoCAD 但零刺激（TOL=−1）那一份；被判的 Δ 一律相对它取"
                                 "（两臂的踏步集相同 ⇒ 刀口抖动结构性抵消）",
                         "source_floor_foot_m2": src_floor_f,
                         "source_floor_resid_mm": src_floor_r,
                         "why": "源件 vs 过手件差 %+.3f m²、%+.6f mm —— 这是**链对 DXF 往返的不中性**"
                                "（treadlib 过手多剔 4 条），地板比 A 条上限 %.3f m² 大 %.0f 倍 ⇒ "
                                "拿源件当基准会吃掉分辨力（盲区⑦）"
                                % (src_floor_f, src_floor_r, pred_t,
                                   (abs(src_floor_f) / pred_t) if pred_t else 0.0)},
            "resid_whole_mm": {"src": rw_src, "neg": rw_neg, "bln": rw_bln, "delta_bln": d_rb_whole,
                               "delta_src_floor": rw_neg - rw_src,
                               "note": "全模型空间口径，相对基线 `neg` 的那一格 = `-02` 的纯墙口径；"
                                       "与 arms[].resid_cell_mm 不同量"},
            "delta": {"tgt": {"foot_m2": d_ft, "vol_m3": d_ft * H / 1000.0, "resid_mm": d_rt,
                              "pred_foot_m2": pred_t},
                      "bln": {"foot_m2": d_fb, "vol_m3": d_fb * H / 1000.0, "resid_mm": d_rb,
                              "pred_foot_m2": pred_b},
                      "ratio_resid": (d_rb / d_rt) if d_rt else None,
                      "ratio_foot": foot_ratio_t,
                      "ratio_foot_note": "定向臂 Δ足迹（**相对基线 `neg`**）低于 1e-6 m² ⇒ 记 null（分母为 0），"
                                         "不记一个由浮点尾数除出来的假倍数"},
            "gaps_from_source": {"targeted": {"n": len(gaps_t), "sum_mm": sum_t},
                                 "blind": {"n": len(gaps_b), "sum_mm": sum_b,
                                           "max_mm": (max(gaps_b) if gaps_b else None)}},
            # ★★ 本轮发现的**量具缺陷**：`score_cell` 的面积口径含「半格膨胀」，C006 上 +17%。
            "gauge_defect": {"what": "score_cell 的 modA/refA/inter 用 ImageDraw.polygon 填"
                                     "栅格，PIL 连边界像素一起填 ⇒ 每个多边形膨胀约半格",
                             "law": "Δ面积 ≈ (CELL/2) × 周长",
                             "k": {nm: devs[nm]["k"] for nm in devs},
                             "inflation_pct": {nm: devs[nm]["inflation_pct"] for nm in devs}},
            "controls": {"inflate_fake": bool(c1), "drop_90pct": bool(c2),
                         "zero_stimulus": bool(c3), "bad_input": bool(c4), "repeatable": bool(c5),
                         # ★ 每条对照都要落**读数**，不只落一个 bool：bool 是推导出来的，
                         #   读数才是「这一趟真量到了什么」；下游（演示页/文档）也只许引读数。
                         #   ① 假件
                         "inflate_fake_dfoot_m2": d_inf,
                         "inflate_fake_prec": infl["prec"],
                         "inflate_fake_src_prec": p_s,
                         # ② 缺件两把尺子的读数（判据 C 的牙就在这）
                         "drop_90pct_foot_m2": foot_d, "drop_90pct_cov_min": cov_d,
                         "drop_90pct_cov_n": cov_d_n,
                         "drop_90pct_half_foot_m2": 0.5 * arms["src"]["foot_m2"],
                         "drop_90pct_half_cov": 0.5 * cs,
                         # ③ 零刺激
                         "zero_stimulus_dfoot_m2": zero_foot,
                         "zero_stimulus_dresid_mm": d3.get("d_resid_mm"),
                         # ⑤ 可重复
                         "repeatable_foot_m2": (a2["foot_m2"] if r2.get("state") == S2.OK else None),
                         "repeatable_resid_mm": (a2["resid_mm"] if r2.get("state") == S2.OK else None)},
            "cross_check_02": {"ok": x_ok, "detail": x_txt},
            "fails": fails}, open(a.json, "w", encoding="utf-8"),
            ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc          # ★ 不是 `RC`：本文件只有 `RC_PASS/RC_FAIL/RC_NOGAUGE` 三个常量，没有 `RC`。
                       #   这个笔误在「判词全绿 + json 已写出」之后才炸 ⇒ 产出物说 pass、进程 rc=1。


def main():
    ap = argparse.ArgumentParser()
    # ★ 默认落**正规名**（理由同 `-01`；本件读 `-02` 的 json 做互证并印出它的**年龄** ——
    #   自己那份 json 更不能留上一趟的）。
    ap.add_argument("--json",
                    default=os.path.join(HERE, "_out", "J-07.9.4-03.json"))
    a = ap.parse_args()
    outd = os.path.join(HERE, "_out")
    os.makedirs(outd, exist_ok=True)
    tee = _Tee(os.path.join(outd, "J-07.9.4-03.run.txt"))
    old = sys.stdout
    sys.stdout = tee
    try:
        rc = _run(a)
    finally:
        sys.stdout = old
        tee.flush()
        for f in tee.fs:
            f.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
