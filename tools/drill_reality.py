# -*- coding: utf-8 -*-
r"""单体化：把**按瓦片块**切的主件，重切成**按楼栋**切的可指名栋块（步 3 的 B 段）。

判据一句话
    主件里的每一张面，**要么**落到恰好一个「栋」的轮廓里、**要么**被如实计进「未分配」；
    两侧相加**逐面等于**输入主件的面数（守恒），且每个有面的栋都**写出盘并能被读回**。

量具（哪个程序、量哪个量、单位、阈值）
    · 落位 = **约定 B**（`reality_placement.enu_to_4544_grid`，2026-10-15 定案）：
      `E = E4544_锚 + e_enu`、`N = N4544_锚 + n_enu`。**锚点由 `anchor(tileset)` 现解**，
      **不许手打 416281 / 3393904 / 422**（铁律 174：同一个量只许有一个来源）。
    · 轮廓 = `_drill/footprints.json`（**另一件**、另一条链：2024 DSM 平坦屋盖提取，schema
      `cdut3d-building-footprints/1`）。**本件不自己造轮廓**。
    · 面归属 = 面心（`triangles_center`）的 (E,N) 落进哪个多边形（`shapely.contains_xy`）；
      落不进任何轮廓时，取**最近的轮廓**，距离 ≤ `ASSIGN_MAX_M` 才收。
    · ★★ `ASSIGN_MAX_M` **不许手打、也不许从本趟直方图「找谷」** —— 本趟直方图**没有谷**（见盲区 8），
      从它取数只会取到某个 bin 的边界值（第一版就是这么错的：规则**返回 0.50 m**，
      而那是 `HIST_STEP_M` 的两倍，即「尖峰之后的第一格」，不是任何物理量）。
      ★ 第二版把「无谷」的判据写成「门槛之上连续段之后不再有格越门」，在全量上印出「有膝盖 0.75 m」——
      **那是曲线穿过 3×本底刻度线的地方，不是谷**（单调衰减的曲线必然有且只有一个这样的交点）。
      ⇒ 现判据要求**先落地（≤本底）再爬回来（≥1.5×）**，两条都过才算谷；见 `VALLEY_*` 常量处注释。
      ⇒ 阈值**读另一条链记下来的配准残差**：`rebuild/_work/regbest_1层.json` 的
      **`boundary_median_m`**（`J-10.8-01`：独立来源＝**CAD 模型轮廓 vs 2024 DOM** 的边界偏差中位）。
      语义：**「真墙面可能落在 DSM 提的轮廓外多远」** ⇒ 容差就该取它。
      ★ 路径与字段名写死在 `MISREG_JSON` / `MISREG_FIELD`，**读不到就 rc=4**（不许退回手打数）。
    · 守恒：`Σ 主件面数 = Σ 已分配 + Σ 未分配`（**逐面**，不是「差不多」）。
      并按来源拆开记：`dist == 0`（面心真在轮廓内 ⇒ **确定**）／`0 < dist ≤ ASSIGN_MAX_M`（**近场，存疑**）。
    · 面积读数：`trimesh.area_faces` 求和，m²。**本件与回读件比**（同一形态：都是 glb）。

盲区（这把尺子对哪几类东西看不见 —— 逐条如实声明）
    1. ★ **轮廓只覆盖「平坦屋盖」**（`building_footprints.py` 盲区 1/5/6/7 逐条继承）。
       其后果直接落在本件上：**被树冠遮住的屋顶、坡屋顶、连片裙楼会被并成一块或干脆提不出来**；
       5 个 `oversize`（>20000 m²）的块**大概率是地形不是楼**，本件**照切不误、只标注**。
    2. ★ **立面靠「距离容差」捞回来**，不是靠轮廓：竖直墙面的面心水平位置**恰好压在**
       轮廓边界线上（DSM 屋盖边界＝外墙面），所以「在不在轮廓内」对墙是**掷硬币**。
       ⇒ `ASSIGN_MAX_M` 是**必需**的，它同时也是**最大的误差来源**：余量给大了，
       会把紧贴楼的**地面、道路、树**一起收进栋块；给小了，**墙会被切掉一半**。
       本件把直方图与来源**全部印出来**，让这个取舍可复核，但不承诺它是对的。
       ★ 阈值现在取自 `boundary_median_m` —— 那是 **2D 栅格**上的边界中位，本件拿它当
       **3D 面心到多边形边的距离**用 ⇒ **量纲同、语义只是代理**（见盲区 8）。
    8. ★★ **本件已实测：这条直方图没有「谷」。** 两趟读数（**全量那趟为准**）：
       ① 单块 `Tile_+003_+005`：`[0,0.25)` = **4945**（面心真在轮廓内／压在边上），`[0.25,0.50)` = 150，
          其后 **0.5 m→4 m 是一段宽平台**（110/106/107/103/108/115/123/128…），
          直到 ≈4 m 才落到「本底」（6–12 m 区中位 46）。
       ② 全量 13 块（400k 采样）：`[0,0.25)` = **1353769** → `[0.25,0.50)` = 53510 → `[0.50,0.75)` = 30780
          → `[0.75,1.00)` = 20419 → 17421 → 18325 → 19996 …（**平台 ~12–20k 一直铺到 ≈6 m**），
          本底 6–12 m 中位 **9702.5**；过渡段最低格是本底的 **1.22 倍**、其后只回升 **1.04 倍**
          ⇒ **曲线是单调衰减到本底，中间没有谷**（①不过：没落到本底；②不过：没爬回来）。
       ⇒ **「真墙面」与「紧邻地面/树」在距离上分不开**。
       根因是**轮廓自己的位置误差与这个距离同量级**（2.06 m），它把本该存在的谷填平了。
       **后果**：任何 `ASSIGN_MAX_M` 都同时切进一部分地面（多收）与漏掉一部分墙（少收），
       **这是定义差不是调参能修的**。⇒ 出件里**逐栋记 `n_f_inside` / `n_f_near`**，
       让「哪一栋靠容差捞回来的比例高」一眼可见；修这个的活留给编辑器（本仓既定口径：
       「不承诺自动单体化干净」）。
    3. ★ **未分配 ≠ 错**：不属于任何楼的实景（地面、道路、树、旗杆、围墙）**本来**就该未分配。
       本件只报数，**不把「未分配多」读成「切坏了」**。
    4. ★ **只覆盖 13 个瓦片块**（`_edit/` 下现列的），不是全校区 124 块。
       ⇒ 区域外的楼**本来就没有网格**，`n_faces=0` 的栋必须**按「不在覆盖区」与「在覆盖区却零面」
       分开报**，否则「没量到」与「量到 0」同形（铁律 199）。
    5. ★ **一张面只归一个栋**：面心落进两个轮廓时（贴建、轮廓重叠）取**第一个**（按 fid 排序）
       并**计数**。⇒ 贴建楼之间**没有可切的缝**，切出来的两块合起来才是那一坨。
    6. ★ **构件的名字不是「建筑名」**：`bldg_<16 位十六进制>` 是**几何稳定 ID**（`fid_of`），
       不是 `F:\学校建筑\` 里的 `C001-砚湖图书馆`。**两者没有登记表可查**（实测：那份图纸是
       全校区 ~1.5 km 局部框架图，不是逐栋轮廓）⇒ 本件**不做**「楼名 ↔ bldg_ID」映射。
    7. ★ **本件只管几何、不管纹理重投影**：贴图按源片**逐字节搬**（`restore_glb_images`），
       所以切出来的栋**沿用已烘焙的图集** —— 被切走的部分不会重投，**接缝处会有鬼影**。

正对照（必配 —— 没有它，上面每一条判据都可能是恒绿的）
    · **P1 守恒的牙齿**：人为从 `_drill/` 里**藏一个栋文件**，回读那一遍**必须点名报出它**
      （`--hide <fid>`；判据不是「不相等」，是**报出那一个 fid**）。
    · **P2 未分配非空**：未分配面数必须 **> 0** —— 一块实景里**必然**有地面/道路/树，
      如果「未分配＝0」说明归属判据**把所有东西都塞进了某个轮廓**（尺子没牙齿），
      阅读数即判作废。
    · **P3 轮廓被用上**：`(E,N)` 落进的栋数必须 > 0，且 `Σ 已分配 > 0`；
      否则「149 个轮廓一个都没命中」会以「全绿」的样子出现。
    · **P4 落位约定 B 的现场复核**：把主件几何按 B 落到 4544 后取 ENU 包围盒，
      与谱系表里**记的** `master_bbox_enu` 比 —— 两个读数（记录值 vs 现算值）必须一致
      （≤ 1e-2 m）。不一致 ⇒ 主件不是「根 ENU 帧」⇒ **拒绝出件（rc=4）**，不许硬切。
    · **P5 回读是第二把尺子**：写完后**重新从盘上读回**每个 glb，核
      ① 几何名集合 == 谱系 `pieces[].name` 集合（双向点名）；
      ② 逐片面数与面积 —— 与**分配那一遍**记下的读数比（铁律 187：两次不同读数）。
    · **P6 阈值有分辨力**：把 `ASSIGN_MAX_M` 人为改成 **0**（＝只收轮廓内的）再数一遍，
      已分配面数**必须显著下降**。若不降 ⇒ 阈值对结果**毫无影响**（要么 `(0, 2.06]` 里
      真的一张面都没有，要么归属判据根本没在用它）⇒ 盲区 2/8 那两条自我描述正在说假话。
      ★ 这不是同义反复：`dist<=0`（只余 `dist==0`）与 `dist<=2.06` 是两个**真不同**的集合，
      读数由数据给出，不由推导保证。

三态
    OK  = 全部通过                        ⇒ `RC_PASS = 0`
    FAIL= 有不通过项（**判词逐条点名**）    ⇒ `RC_FAIL = 1`
    SKIP= 量具不成立（输入缺、锚定不同源、主件帧不对）⇒ `RC_NOGAUGE = 4`（**不是 0**）

★ 本件**只写 `_drill/`**，**不动** `_edit/`（主件是上游产物）。跨仓件只**引用**
  （tileset / DSM 在 gym3d 的 `_scratch` 下），不搬。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import reality_placement as RP          # noqa: E402  —— 落位（约定 B）的唯一来源
import scene_to_editable as S2E         # noqa: E402  —— 读回/写盘/贴图 工具的既有实现
import editable_to_tiles as E2T         # noqa: E402  —— master_images / lod_of 的既有实现

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

REPO = os.path.dirname(_HERE)
EDIT = os.path.join(REPO, "_edit")
OUT = os.path.join(REPO, "_drill")
FOOT = os.path.join(REPO, "_drill", "footprints.json")

FOOT_SCHEMA = "cdut3d-building-footprints/1"
SCHEMA = E2T.SCHEMA                                   # "cdut3d-reality-master/1"
PREFIX = "bldg_"          # ★ 不许带冒号：Windows 文件名（见 building_footprints.fid_of）

CAND_M = 12.0             # 候选预筛半径：只决定「哪些轮廓参与比距离」，**不决定归属**（越大越安全，只慢）

# ★★ 阈值来源：**另一条链**记下来的配准残差（`J-10.8-01`），不是本件现算、更不是手打。
#    读不到 ⇒ rc=4（不许退回一个「看起来合理」的数）。
MISREG_JSON = os.path.join(REPO, "rebuild", "_work", "regbest_1层.json")
MISREG_FIELD = "boundary_median_m"          # 边界偏差**中位**（m）——容差取它
MISREG_P90_FIELD = "boundary_p90_m"          # 一并记录，供人判「余量够不够」
MISREG_NOTE = "J-10.8-01：CAD 模型轮廓 vs 2024 DOM 的边界偏差（与本件不同源）"

# 直方图：**只作诊断上报**，不参与取数（见 docstring 盲区 8）
HIST_STEP_M = 0.25
HIST_MAX_M = 12.0
AMBIENT_LO_M, AMBIENT_HI_M = 6.0, 12.0   # 「环境本底」取数区间：那里的计数＝「远处零散面」的速率
KNEE_MULT = 3.0           # 「门槛之上」段：3 × 本底中位。★ 只是**刻度线**，不是谷
# ★ 「谷」的判据要**两步**，缺一步就退化成「越过门槛线」（第一版就是这么错的）：
#   ① 段内最低一格的计数必须 **≤ 本底中位 × VALLEY_DIP_MAX**（真落到远场地板）
#   ② 该格之后必须 **回升 ≥ VALLEY_RISE_MIN 倍**（先落地、再爬回来，才叫谷）
VALLEY_LO_M = 0.50        # 跳过尖峰头两格：尖峰自身不是谷
VALLEY_DIP_MAX = 1.0      # ① 的最低格必须低到本底水平
VALLEY_RISE_MIN = 1.5     # ② 回升倍率下限
FRAME_TOL_M = 1e-2        # P4：记录值 vs 现算值的容差
AREA_TOL_REL = 1e-6       # P5：面积相对差
DIST_SAMPLE_MAX = 400_000  # 直方图抽样上限（超过就随机抽，随机种子固定 ⇒ 可复现）


# --------------------------------------------------------------------------- 小工具

def _sha_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _dump_bytes(path: str, obj) -> None:
    """★ 字节层写盘（铁律 79：文本模式会把 LF 翻成 CRLF，读起来像「修好了」）。
    ★ `allow_nan=False`（铁律 123：裸 `Infinity`/`NaN` 能落盘、浏览器 `JSON.parse` 抛错）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)


# --------------------------------------------------------------------------- 轮廓

def load_footprints(path: str, log) -> dict:
    """读轮廓名单。★ 名单**不是**本件造的 —— schema 必须对得上，否则拒绝。"""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if d.get("schema") != FOOT_SCHEMA:
        raise SystemExit("[FATAL] 轮廓件 schema=%r ≠ %r ⇒ 拒绝" % (d.get("schema"), FOOT_SCHEMA))
    fids = [b["fid"] for b in d["blocks"]]
    if len(set(fids)) != len(fids):
        raise SystemExit("[FATAL] 轮廓名单里有重复 fid ⇒ 拒绝（名字不唯一则「点名」无从谈起）")
    bad = [f for f in fids if not f.startswith(PREFIX) or ":" in f]
    if bad:
        raise SystemExit("[FATAL] %d 个 fid 不是 `%s<hex>` 形状（含冒号？）⇒ 拒绝：%s"
                         % (len(bad), PREFIX, bad[:3]))
    log("轮廓名单 %s：%d 个轮廓（schema %s）" % (os.path.basename(path), len(fids), d["schema"]))
    return d


def build_index(foot: dict, log) -> dict:
    """轮廓 → shapely 多边形 + 预筛树。★ 自相交多边形先 `make_valid` 并**计数报出**。"""
    import shapely
    from shapely.geometry import Polygon
    from shapely.geometry import box as _box
    from shapely.validation import make_valid

    fids = [b["fid"] for b in foot["blocks"]]
    polys, n_fixed, n_empty, n_multi = [], 0, 0, []
    for b in foot["blocks"]:
        ring = [(float(e), float(n)) for e, n in b["poly_en"]]
        p = Polygon(ring)
        if not p.is_valid:
            p2 = make_valid(p)
            if p2.geom_type == "MultiPolygon":
                n_multi.append(b["fid"])
                p2 = max(p2.geoms, key=lambda g: g.area)
            p = p2
            n_fixed += 1
        if p.is_empty or p.area <= 0:
            n_empty += 1
            p = Polygon()
        polys.append(p)
    log("多边形：%d 个 ｜ 自相交已 make_valid %d 个（其中 MultiPolygon 取最大块 %d 个）｜ 空/退化 %d 个"
        % (len(polys), n_fixed, len(n_multi), n_empty))
    # ★ 预筛树建在「外扩 CAND_M 的包围盒」上：`STRtree.query(点)` 是**包围盒相交**，
    #   拿原多边形建树会漏掉「在轮廓外 CAND_M 内」的候选 ⇒ 近邻永远捞不回来。
    bufs = []
    for p in polys:
        if p.is_empty:
            bufs.append(_box(0, 0, -1, -1))          # 空多边形 ⇒ 永不命中（显式，不靠 NaN）
            continue
        x0, y0, x1, y1 = p.bounds
        bufs.append(_box(x0 - CAND_M, y0 - CAND_M, x1 + CAND_M, y1 + CAND_M))
    tree = shapely.STRtree(bufs)
    return {"fids": fids, "polys": polys, "tree": tree, "n_fixed": n_fixed,
            "n_multi": n_multi, "n_empty": n_empty}


def assign_block(E, N, idxd) -> tuple:
    """(E, N) → 每个点归属的轮廓下标（-1＝没有），外加**到最近轮廓的距离**（已归属＝0）。

    ★ 距离**如实返回**（没候选的点保持 inf）—— 直方图靠它导出，不许在这里截断。
    """
    import shapely

    polys = idxd["polys"]
    m = len(E)
    out = np.full(m, -1, np.int32)
    dist = np.full(m, np.inf, np.float64)
    stats = {"n_multi_hit": 0, "n_pairs": 0}
    if m == 0:
        return out, dist, stats

    ii, jj = idxd["tree"].query(shapely.points(E, N))       # 包围盒预筛（点 × 轮廓）
    stats["n_pairs"] = int(len(ii))
    if len(ii) == 0:
        return out, dist, stats

    order = np.lexsort((jj, ii))
    ii, jj = ii[order], jj[order]

    # ① 先判「在轮廓内」：一个点可能落进多个 ⇒ 取下标最小者，并把多命中**计数**
    for j in np.unique(jj):
        p = polys[j]
        if p.is_empty:
            continue
        sel = ii[jj == j]
        inside = np.asarray(shapely.contains_xy(p, E[sel], N[sel]), dtype=bool)
        hit = sel[inside]
        if not len(hit):
            continue
        free = out[hit] < 0
        stats["n_multi_hit"] += int((~free).sum())
        first = hit[free]
        out[first] = j
        dist[first] = 0.0

    # ② 未命中的点，在候选里取**最近**的轮廓（收不收由调用方按 ASSIGN_MAX_M 裁）
    # ★ 掩码必须**翻译到「对」的定义域上**：`rest` 是**每点**一个 bool（长 m），
    #   而 `ii/jj` 是**每候选对**一个（长 n_pairs）。直接写 `ii[rest]` 只在
    #   「每点恰有一个候选」（⇒ 排序后 ii==0,1,2,…）时才侥幸成立；
    #   一旦有点零候选/多候选，长度就对不上 ⇒ IndexError（实测 +003_+006 崩在这）。
    rest = out < 0
    pair_rest = rest[ii]
    if pair_rest.any():
        ri, rj = ii[pair_rest], jj[pair_rest]
        for j in np.unique(rj):
            p = polys[j]
            if p.is_empty:
                continue
            sel = ri[rj == j]
            if not len(sel):
                continue
            d = shapely.distance(p, shapely.points(E[sel], N[sel]))
            better = d < dist[sel]
            tgt = sel[better]
            if len(tgt):
                dist[tgt] = d[better]
                out[tgt] = j
    return out, dist, stats


def scan_hist(dist_samples: np.ndarray, log) -> dict:
    """把「面心 → 最近轮廓」的距离直方图**印出来并如实描述它有没有膝盖**。

    ★ 这个函数**不产出阈值**（第一版让它产出，结果是错的：规则返回 0.50 m = 两格边界，
      因为它把「尖峰之后第一格」当成了膝盖，而当时 0.5–4 m 那段宽平台整段都在门限之上）。
    ★ 它只回答一个问题：**这条直方图上有没有一个「谷」把「真墙面」和「紧邻地面」分开？**
    ★★ 判据**两步都要过**，缺一步就会退化成「越过刻度线」——**第二版就是这么错的**：
      第二版写「门槛之上的连续段之后不再有格越门 ⇒ 有膝盖」，在全量 13 块上印出「有膝盖 0.75 m」，
      而实测序列是 1353769→53510→30780→20419→17421…→~13k→本底 9.7k，**单调衰减、从未回升**
      ⇒ 0.75 m 只是**曲线穿过 3×本底这条线的地方**，不是谷。所以现在：
      ① 段内最低格必须**低到本底水平**（≤ 本底 × `VALLEY_DIP_MAX`）；
      ② 该格之后必须**回升 ≥ `VALLEY_RISE_MIN` 倍**（先落地再爬回来才叫谷）。
      ⇒ 单调衰减的曲线两条都过不了 ⇒ `knee_found = False`（实测 13 块：dip/ambient=1.22、rise/dip=1.04）。
      底为 0 或段太短 ⇒ `valley_bin_left_m = None`，判语写「**没量到**」，不写「没有谷」（铁律 199）。
    """
    edges = np.arange(0.0, HIST_MAX_M + 1e-9, HIST_STEP_M)
    h, _ = np.histogram(dist_samples, bins=edges)
    n_amb = max(1, int(round((AMBIENT_HI_M - AMBIENT_LO_M) / HIST_STEP_M)))
    ambient = float(np.median(h[-n_amb:])) if len(h) >= n_amb else 0.0
    thr = KNEE_MULT * ambient
    # 「门槛之上」段：**只是刻度线**，报出来当参照，不当结论
    cross_end = 0.0
    for k, cnt in enumerate(h):
        if cnt > thr and edges[k] < AMBIENT_LO_M:
            cross_end = float(edges[k + 1])
        else:
            break
    # 谷＝「先落地再爬回来」，两步都要过（见文件头常量处注释）
    lo_k = int(round(VALLEY_LO_M / HIST_STEP_M))
    hi_k = int(round(AMBIENT_LO_M / HIST_STEP_M))
    seg = h[lo_k:hi_k]
    valley_k, valley_dip, valley_rise = -1, 0.0, 0.0
    knee_found = False
    if len(seg) >= 3 and ambient > 0:
        valley_k = int(np.argmin(seg)) + lo_k
        valley_dip = float(h[valley_k])
        tail = h[valley_k + 1:hi_k]
        valley_rise = float(np.max(tail)) if len(tail) else 0.0
        knee_found = bool(valley_dip <= ambient * VALLEY_DIP_MAX
                          and valley_rise >= VALLEY_RISE_MIN * valley_dip and valley_dip > 0)
    log("  ★ 距离直方图（面心 → 最近轮廓）  格宽 %.2f m ｜ 本底区[%.1f,%.1f) 中位 %.1f ｜ 刻度线 %.1f"
        % (HIST_STEP_M, AMBIENT_LO_M, AMBIENT_HI_M, ambient, thr))
    for k, cnt in enumerate(h):
        if edges[k] < AMBIENT_LO_M:
            tag = "  ← 门槛之上" if cnt > thr else ""
        else:
            tag = "  ← 本底区"
        if k == valley_k:
            tag += "  ← **段内最低格**"
        log("    [%5.2f,%5.2f) %9d%s" % (edges[k], edges[k + 1], cnt, tag))
    if valley_k < 0:
        log("  ⇒ 本底中位为 0 或段太短 ⇒ **这条直方图量不出谷**（不是「没有谷」，是**没量到**）")
    elif knee_found:
        log("  ⇒ 段内最低格 [%.2f,%.2f) 计数 %d（本底 %.1f 的 %.2f 倍），其后回升到 %d（%.2f 倍）"
            % (edges[valley_k], edges[valley_k + 1], valley_dip, ambient,
               valley_dip / ambient, valley_rise, valley_rise / max(1.0, valley_dip)))
        log("     ⇒ **有膝盖**（先落地、再爬回来）")
    else:
        log("  ⇒ 「门槛之上」段止于 %.2f m —— ★ 这只是**越过刻度线**，不是谷" % cross_end)
        log("     段内最低格 [%.2f,%.2f) 计数 %d（本底 %.1f 的 %.2f 倍），其后回升到 %d（%.2f 倍）"
            % (edges[valley_k], edges[valley_k + 1], valley_dip, ambient,
               valley_dip / ambient, valley_rise, valley_rise / max(1.0, valley_dip)))
        log("     ⇒ **没有膝盖**：底没落到本底（①不过）／没爬回来（②不过）⇒ 曲线只是**单调衰减到本底**")
        log("     ⇒ 这把距离尺子分不开「真墙面」与「紧邻地面/树」；本件**不从直方图取数**"
            "（见 docstring 盲区 8），阈值改从另一条链的配准残差读。")
    return {"hist_edges": [round(float(x), 4) for x in edges],
            "hist_counts": [int(x) for x in h],
            "ambient_median": ambient, "knee_mult": KNEE_MULT, "threshold_count": thr,
            "cross_end_m": cross_end, "knee_found": knee_found,
            "valley_bin_left_m": (round(float(edges[valley_k]), 4) if valley_k >= 0 else None),
            "valley_dip": valley_dip, "valley_dip_over_ambient": (valley_dip / ambient if ambient else None),
            "valley_rise": valley_rise, "valley_rise_over_dip": (valley_rise / valley_dip if valley_dip else None),
            "valley_dip_max": VALLEY_DIP_MAX, "valley_rise_min": VALLEY_RISE_MIN,
            "n_samples": int(len(dist_samples))}


def resolve_max_m(log) -> dict:
    """读**另一条链**记下来的配准残差，作为 `ASSIGN_MAX_M`。

    ★ 为什么是它：面归属的容差要的是「**真墙面可能落在 DSM 提的轮廓外多远**」。
      轮廓自己的位置误差就是这个量，而它由 `J-10.8-01`（CAD 模型轮廓 vs 2024 DOM，
      与本件不同源）记在盘上 ⇒ 取 `boundary_median_m`。
    ★ 读不到 / 不是有限正数 ⇒ `ok=False` ⇒ 调用方判 rc=4。**不许**退回一个手打数。
    """
    if not os.path.isfile(MISREG_JSON):
        log("  ★ 配准残差件不在盘上：%s ⇒ 没量到（rc=4，不是 0）" % MISREG_JSON)
        return {"ok": False, "why": "file missing", "path": MISREG_JSON}
    with open(MISREG_JSON, "r", encoding="utf-8") as f:
        d = json.load(f)
    v, p90 = d.get(MISREG_FIELD), d.get(MISREG_P90_FIELD)
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0
    log("  ★ 阈值来源 %s（%s）" % (os.path.relpath(MISREG_JSON, REPO), MISREG_NOTE))
    log("     %s = %s m ｜ %s = %s m ｜ %s"
        % (MISREG_FIELD, v, MISREG_P90_FIELD, p90, "可读" if ok else "★读不出/不是正数"))
    return {"ok": bool(ok), "path": MISREG_JSON, "field": MISREG_FIELD, "value": v,
            "p90_field": MISREG_P90_FIELD, "p90_value": p90, "note": MISREG_NOTE}


# --------------------------------------------------------------------------- 落位自检（P4）

def check_frame(blk: str, lg: dict, sc, log) -> dict:
    """P4：主件几何按 B 落到 4544 后取 ENU 包围盒，与谱系**记的** `master_bbox_enu` 比。

    ★ 这是**两个读数**：`master_bbox_enu` 是上游提取那一刻写的，这里是**现算**的。
      一致 ⇒ 主件的坐标帧就是「根 ENU 翻转帧」，B 的平移式才成立。
    """
    lo = np.array([np.asarray(g.bounds)[0] for g in sc.geometry.values()]).min(axis=0)
    hi = np.array([np.asarray(g.bounds)[1] for g in sc.geometry.values()]).max(axis=0)
    now = list(S2E.enu_bbox(np.stack([lo, hi])))
    rec = lg.get("master_bbox_enu")
    if not rec:
        return {"ok": None, "why": "谱系里没有 master_bbox_enu ⇒ 没量到（不是通过）"}
    d = float(np.max(np.abs(np.asarray(now, float) - np.asarray(rec, float))))
    ok = d <= FRAME_TOL_M
    log("  P4 帧核对 %-16s 现算 %s ／ 记录 %s ⇒ max|Δ|=%.6f m  %s"
        % (blk, [round(v, 3) for v in now], [round(v, 3) for v in rec], d, "OK" if ok else "★不一致"))
    return {"ok": bool(ok), "now_enu": [round(v, 6) for v in now], "recorded_enu": rec,
            "max_abs_delta_m": d, "tol_m": FRAME_TOL_M}


def src_meta(lg: dict, name: str) -> tuple:
    for p in lg["pieces"]:
        if p["name"] == name:
            return list(p.get("ancestors") or []), p.get("depth"), p.get("lod")
    return [], None, None


def restore_images(dst: str, order_src: list, img_cache: dict) -> dict:
    """把 trimesh 重编码过的贴图**换回原始字节**。

    ★ 次序**走 glTF 结构现读**（mesh → primitive → material → baseColorTexture → textures[i].source），
      **不按写入顺序猜**（规范 §3.3：「猜是循环论证」）。
    ★ 任一位填不上 ⇒ **一个都不换**（宁可保留有损，也不许错位换）—— 既有件口径，照抄。
    """
    import pygltflib as P
    g = P.GLTF2().load(dst)
    if not g.images:
        return {"status": "NO_IMAGE"}
    src_of = {nn: (blk, nm) for nn, blk, nm in order_src}
    claim: dict = {}
    for m in g.meshes or []:
        js = set()
        for pr in m.primitives:
            mat = g.materials[pr.material] if pr.material is not None else None
            pbr = getattr(mat, "pbrMetallicRoughness", None) if mat is not None else None
            bct = getattr(pbr, "baseColorTexture", None) if pbr is not None else None
            if bct is None:
                continue
            st = getattr(g.textures[bct.index], "source", None)
            js.add(st)
        claim[m.name] = js
    ordered: list = [None] * len(g.images)
    why = []
    for nn in src_of:
        js = sorted(x for x in claim.get(nn, set()) if x is not None)
        if len(js) != 1:
            why.append("%s: 影像下标 %s" % (nn, js))
            continue
        blk, nm = src_of[nn]
        rec = (img_cache.get(blk) or {}).get(nm)
        if not rec or rec[0] is None:
            why.append("%s: 源无原始字节" % nn)
            continue
        if ordered[js[0]] is not None:
            why.append("%s: 影像位 %d 被两片争用" % (nn, js[0]))
            continue
        ordered[js[0]] = rec[0]
    if why or any(x is None for x in ordered):
        return {"status": "NOT_RESTORED", "n_images": len(g.images), "why": why[:6]}
    try:
        return S2E.restore_glb_images(dst, ordered)
    except Exception as exc:                                  # noqa: BLE001 —— 读不动要如实报
        return {"status": "ERROR", "error": "%s: %s" % (type(exc).__name__, exc)}


# --------------------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="单体化：主件 → 按栋切块（步 3-B）")
    ap.add_argument("--edit", default=EDIT)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--foot", default=FOOT)
    ap.add_argument("--blocks", default="", help="逗号分隔的块名；缺省＝现列全部")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--hide", default="", help="★ 正对照 P1：写完把这个 fid 的文件藏起来，回读必须点名")
    ap.add_argument("--assign-max-m", type=float, default=None,
                    help="★ 覆盖归属容差（m）。**默认不填**＝读 %s:%s；"
                         "填了会记进 _index 的 assign_max_source.overridden"
                         % (os.path.relpath(MISREG_JSON, REPO), MISREG_FIELD))
    ap.add_argument("--no-write", action="store_true", help="只分配不写盘（调参用）")
    a = ap.parse_args()

    t0 = datetime.datetime.now()
    L: list = []

    def log(s=""):
        print(s)
        L.append(s)

    log("=" * 100)
    log("单体化（步 3-B）  %s" % t0.strftime("%Y-%m-%d %H:%M:%S"))
    log("  主件 %s\n  轮廓 %s\n  出件 %s" % (a.edit, a.foot, a.out))

    if not os.path.isfile(a.foot):
        log("[FATAL] 轮廓件不存在：%s ⇒ 没量到（rc=4，不是 0）" % a.foot)
        return RC_NOGAUGE
    foot = load_footprints(a.foot, log)
    idxd = build_index(foot, log)

    # ---------- 选块：真源＝程序现列文件系统（与 editable_to_tiles 同一条判据）----------
    disk = sorted(n for n in os.listdir(a.edit)
                  if os.path.isdir(os.path.join(a.edit, n))
                  and os.path.exists(os.path.join(a.edit, n, n + ".lineage.json")))
    blocks = ([b.strip() for b in a.blocks.split(",") if b.strip()] or disk)
    if a.limit:
        blocks = blocks[:a.limit]
    log("主件块（程序现列 %s）：%d 块 ｜ 本次处理 %d 块" % (a.edit, len(disk), len(blocks)))
    if not blocks:
        log("[FATAL] 一块主件都没有 ⇒ 没量到（rc=4）")
        return RC_NOGAUGE

    ts = RP.load_tileset()
    anc = RP.anchor(ts)
    log("落位=约定 B ｜ 锚点（由 root.transform 平移现解，非手打）："
        " E4544=%.3f N4544=%.3f h=%.3f  lat=%.9f lon=%.9f"
        % (anc["E4544"], anc["N4544"], anc["h"], anc["lat"], anc["lon"]))

    import shapely                                     # noqa: F401 —— 供 assign_block 用（显式）
    import trimesh
    from shapely.geometry import box as _box

    # ---------- 第一遍：读主件 + 落位 + 面归属 ----------
    per_block: dict = {}
    frame_checks: dict = {}
    src_sha: dict = {}
    dist_sample: list = []
    rng = np.random.default_rng(20261015)

    for blk in blocks:
        d = os.path.join(a.edit, blk)
        glb = os.path.join(d, blk + ".glb")
        with open(os.path.join(d, blk + ".lineage.json"), "r", encoding="utf-8") as f:
            lg = json.load(f)
        if lg.get("schema") != SCHEMA:
            log("[FATAL] %s 谱系 schema=%r ≠ %r ⇒ 拒绝（rc=4）" % (blk, lg.get("schema"), SCHEMA))
            return RC_NOGAUGE
        src_sha[blk] = (lg.get("src_tileset") or {}).get("sha256")
        sc = trimesh.load(glb, force="scene")
        frame_checks[blk] = check_frame(blk, lg, sc, log)

        names = sorted(sc.geometry)
        parts, spans = [], []
        for nm in names:
            g = sc.geometry[nm]
            c = np.asarray(g.triangles_center, np.float64)
            E, N, _h = RP.glb_to_4544_grid(c, anc)
            parts.append(np.c_[E, N])
            spans.append((nm, int(len(c))))
        pts = np.vstack(parts) if parts else np.zeros((0, 2))
        idx, dist, ast = assign_block(pts[:, 0], pts[:, 1], idxd)

        fin = np.nonzero(np.isfinite(dist))[0]
        if len(fin):
            sel = fin if len(fin) <= DIST_SAMPLE_MAX else rng.choice(fin, DIST_SAMPLE_MAX, replace=False)
            dist_sample.append(dist[sel])

        per_block[blk] = {"pieces": spans, "idx": idx, "dist": dist, "ast": ast,
                          "lg": lg, "n_faces": int(len(pts))}
        log("  %-16s 片 %3d ｜ 面 %7d ｜ 命中轮廓 %7d ｜ 多命中 %d"
            % (blk, len(names), len(pts), int((idx >= 0).sum()), ast["n_multi_hit"]))
        del sc

    # ---------- 锚定同源：各块 src_tileset.sha256 必须一模一样 ----------
    snaps = set(src_sha.values())
    if len(snaps) != 1 or None in snaps:
        log("[FATAL] 各块 src_tileset.sha256 不一致（%s）⇒ 不同源，拒绝（rc=4）"
            % sorted(map(str, snaps)))
        return RC_NOGAUGE
    log("锚定同源：%d 块的 src_tileset.sha256 全等 %s…" % (len(snaps), list(snaps)[0][:16]))

    bad_frame = [b for b, r in frame_checks.items() if r.get("ok") is not True]
    if bad_frame:
        log("[FATAL] P4 帧核对不过：%s ⇒ 落位 B 的前提（主件＝根 ENU 翻转帧）不成立，拒绝（rc=4）"
            % bad_frame)
        return RC_NOGAUGE

    # ---------- 未分配读数 + 定 ASSIGN_MAX_M（直方图只诊断；阈值读另一条链）----------
    n_faces_all = int(sum(v["n_faces"] for v in per_block.values()))
    all_dist = np.concatenate(dist_sample) if dist_sample else np.zeros(0)
    log("")
    log("★ 距离直方图（**只上报，不取数**）")
    hist = scan_hist(all_dist, log)
    log("")
    mis = resolve_max_m(log)
    if not mis["ok"]:
        log("[FATAL] ASSIGN_MAX_M 的来源不可用 ⇒ 拒绝出件（rc=4，不是 0）")
        return RC_NOGAUGE
    if a.assign_max_m is not None:
        log("  ★ 命令行覆盖（--assign-max-m）：%.4f m —— 记进 _index.assign_max_source.overridden"
            % a.assign_max_m)
    assign_max = float(a.assign_max_m) if a.assign_max_m is not None else float(mis["value"])
    log("  ⇒ ASSIGN_MAX_M = %.4f m ｜ 来源＝%s ｜ 覆盖＝%s"
        % (assign_max, os.path.relpath(MISREG_JSON, REPO) + ":" + MISREG_FIELD,
           a.assign_max_m is not None))

    for v in per_block.values():
        v["final"] = np.where((v["idx"] >= 0) & (v["dist"] <= assign_max), v["idx"], -1).astype(np.int32)
        # P6：把阈值压到 0（＝只收面心真在轮廓内的）再数一遍，供分辨力对照
        v["final0"] = np.where((v["idx"] >= 0) & (v["dist"] <= 0.0), v["idx"], -1).astype(np.int32)
    n_assigned = int(sum(int((v["final"] >= 0).sum()) for v in per_block.values()))
    n_assigned0 = int(sum(int((v["final0"] >= 0).sum()) for v in per_block.values()))
    n_unassigned = n_faces_all - n_assigned
    log("   其中面心**真在轮廓内**（dist==0，不靠容差）%d ｜ **靠容差捞回**（0 < dist ≤ %.2f）%d"
        % (n_assigned0, assign_max, n_assigned - n_assigned0))
    log("")
    log("★ 面归属（ASSIGN_MAX_M=%.2f m）：总 %d ｜ 已分配 %d（%.2f%%）｜ 未分配 %d（%.2f%%）"
        % (assign_max, n_faces_all, n_assigned, 100.0 * n_assigned / max(1, n_faces_all),
           n_unassigned, 100.0 * n_unassigned / max(1, n_faces_all)))
    for blk in blocks:
        v = per_block[blk]
        nu = int((v["final"] < 0).sum())
        log("   %-16s 未分配 %7d / %7d（%.2f%%）"
            % (blk, nu, v["n_faces"], 100.0 * nu / max(1, v["n_faces"])))

    # ---------- 第二遍：按栋装配（只收集「哪些面归谁」，先不切几何）----------
    fid_all = idxd["fids"]
    plan: dict = {}                # fid → [(blk, srcpiece, np.array(block-local face idx)), ...]
    for blk in blocks:
        v = per_block[blk]
        idx = v["final"]
        if not (idx >= 0).any():
            continue
        starts, off = [], 0
        for nm, n in v["pieces"]:
            starts.append(off)
            off += n
        for pi, (nm, n) in enumerate(v["pieces"]):
            s = starts[pi]
            sub = idx[s:s + n]
            if not (sub >= 0).any():
                continue
            subd = v["dist"][s:s + n]
            for j in np.unique(sub[sub >= 0]):
                m = np.nonzero(sub == j)[0]
                # ★ 名字**不许**叫 `n_in`：那是上面「覆盖区内轮廓数」的名字，重了就会
                #   把它改成最后一片的张数（实测印出 2051，而轮廓只有 149 个）。
                n_in_piece = int((subd[m] <= 0.0).sum())
                plan.setdefault(int(j), []).append((blk, nm, m, n_in_piece))

    log("")
    log("★ 出件：%d 个栋有面（轮廓共 %d 个）" % (len(plan), len(fid_all)))

    # 覆盖区（各块 ENU bbox 平移到 4544；★ B 是纯平移 ⇒ ENU 轴对齐矩形在 4544 里**仍是轴对齐矩形**）
    cov = None
    for blk in blocks:
        b = per_block[blk]["lg"].get("master_bbox_enu")
        if not b:
            continue
        r = _box(anc["E4544"] + b[0], anc["N4544"] + b[1], anc["E4544"] + b[3], anc["N4544"] + b[4])
        cov = r if cov is None else cov.union(r)
    in_region = {}
    for f, p in zip(fid_all, idxd["polys"]):
        in_region[f] = bool(cov is not None and not p.is_empty and p.intersects(cov))
    n_in = int(sum(in_region.values()))
    zero = [f for f in fid_all if f not in {fid_all[j] for j in plan}]
    zero_in = [f for f in zero if in_region[f]]
    zero_out = [f for f in zero if not in_region[f]]
    log("   轮廓落在覆盖区（%d 块主件的 ENU 包围盒并集）内：%d / %d" % (len(blocks), n_in, len(fid_all)))
    log("   ★ 零面栋 %d 个 ｜ 其中**在覆盖区内却零面** %d 个 ⇒ 逐个点名（见 _index）｜ 覆盖区外 %d 个"
        % (len(zero), len(zero_in), len(zero_out)))
    if zero_in:
        log("     在覆盖区内却零面：%s%s"
            % (", ".join(zero_in[:12]), " …" if len(zero_in) > 12 else ""))

    t_src = {blk: trimesh.load(os.path.join(a.edit, blk, blk + ".glb"), force="scene")
             for blk in blocks}
    img_cache = {blk: E2T.master_images(os.path.join(a.edit, blk, blk + ".glb"))["images"]
                 for blk in blocks}

    # ---------- 写件 ----------
    records: list = []
    for j in sorted(plan):
        fid = fid_all[j]
        scene = trimesh.Scene()
        order_src, pieces, area_plan = [], [], 0.0
        n_f_inside = 0
        n_f_pick = 0
        for blk, nm, m, n_in_piece in plan[j]:
            n_f_inside += n_in_piece
            n_f_pick += int(len(m))
            g = t_src[blk].geometry[nm]
            sub = g.submesh([m], append=True)
            if len(sub.faces) == 0:
                continue                                  # ★ 不许写出空几何（名字/面数会对不上）
            newname = "%s__%s" % (fid, nm)
            scene.add_geometry(sub, node_name=newname, geom_name=newname)
            anc_s, depth, lod = src_meta(per_block[blk]["lg"], nm)
            order_src.append((newname, blk, nm))
            pieces.append({
                "name": newname,
                "uri": "Data/%s/%s.glb" % (fid, newname),
                "lod": lod if lod is not None else E2T.S2E.lod_of(nm),
                "depth": depth,
                "ancestors": ["%s__%s" % (fid, x) for x in anc_s],
                "bytes": None, "n_v": int(len(sub.vertices)), "n_f": int(len(sub.faces)),
                "bounds": [[round(float(x), 6) for x in np.asarray(sub.bounds)[0]],
                           [round(float(x), 6) for x in np.asarray(sub.bounds)[1]]],
                "has_uv": bool(getattr(sub.visual, "uv", None) is not None),
                "texture": S2E.tex_info(sub)})
            area_plan += float(np.asarray(sub.area_faces, np.float64).sum())

        d = os.path.join(a.out, fid)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, fid + ".glb")
        with open(dst, "wb") as f:                        # ★ 字节层写
            f.write(scene.export(file_type="glb"))
        del scene

        # ★ 贴图换回**原始字节**（走 glTF 结构定次序，不猜顺序）
        img_restore = restore_images(dst, order_src, img_cache)
        records.append({"fid": fid, "path": dst, "n_geom": len(order_src),
                        "order_src": [(x[0], x[1], x[2]) for x in order_src],
                        "area_plan": area_plan, "img_restore": img_restore, "pcs": pieces,
                        "n_f_inside": n_f_inside, "n_f_near": n_f_pick - n_f_inside})

    log("   写出 %d 个栋件" % len(records))

    # ---------- 第三遍：读回（P5，第二把尺子 —— 铁律 187 两次不同读数）----------
    log("")
    log("★ P5 回读核对（重新从盘上读，与装配那一遍比）")
    bad = []
    for rec in records:
        back = trimesh.load(rec["path"], force="scene")
        m_names = set(back.geometry)
        l_names = {p["name"] for p in rec["pcs"]}
        only_m, only_l = sorted(m_names - l_names), sorted(l_names - m_names)
        nf = int(sum(len(g.faces) for g in back.geometry.values()))
        ar = float(sum(float(np.asarray(g.area_faces, np.float64).sum())
                       for g in back.geometry.values()))
        nf_plan = int(sum(p["n_f"] for p in rec["pcs"]))
        d_ar = abs(ar - rec["area_plan"]) / max(1e-12, rec["area_plan"])
        uv_bad = [nm for nm, g in back.geometry.items()
                  if getattr(g.visual, "uv", None) is None
                  or len(g.visual.uv) != len(g.vertices)]
        rec.update({"readback_n_f": nf, "readback_area": ar, "readback_n_geom": len(m_names),
                    "name_only_in_master": only_m, "name_only_in_lineage": only_l,
                    "uv_missing": uv_bad, "area_rel_delta": d_ar, "delta_f": nf - nf_plan})
        if only_m or only_l or nf != nf_plan or d_ar > AREA_TOL_REL or uv_bad:
            bad.append(rec["fid"])
            log("   ★ %-24s 名差(读回/谱系) %d/%d ｜ 面 %d vs %d ｜ 面积相对差 %.3e ｜ UV 缺 %d"
                % (rec["fid"], len(only_m), len(only_l), nf, nf_plan, d_ar, len(uv_bad)))
    if not bad:
        log("   %d 个栋件：几何名双向全等 ｜ 逐片面数相等 ｜ 面积相对差 ≤ %.0e ｜ UV 齐全 ⇒ 全过"
            % (len(records), AREA_TOL_REL))

    # ---------- P1 正对照：藏一个栋文件，回读必须点名 ----------
    log("")
    log("★ P1 正对照：藏一个栋文件，回读必须**点名**报出它（不是只报「数量不等」）")
    p1 = None
    if a.hide:
        want = a.hide if a.hide.startswith(PREFIX) else PREFIX + a.hide
        rec = next((r for r in records if r["fid"] == want), None)
        if rec is None:
            log("   ★ 指定的 fid 不在本次出件里：%s ⇒ 没量到（对照**未执行**，不算通过）" % want)
        else:
            bak = rec["path"] + ".hidden"
            os.replace(rec["path"], bak)
            try:
                on_disk = sorted(n for n in os.listdir(a.out)
                                 if os.path.isdir(os.path.join(a.out, n))
                                 and os.path.exists(os.path.join(a.out, n, n + ".glb")))
                expected = sorted(r["fid"] for r in records)
                missing = [f for f in expected if f not in on_disk]
                hit = missing == [want]
                log("   藏起 %s ⇒ 盘上 %d / 应有 %d ｜ 点名报出：%s ｜ %s"
                    % (want, len(on_disk), len(expected), missing,
                       "✓ 恰好就是它" if hit else "★ 没点上名（或点了别的）⇒ 这条判据没有分辨力"))
                p1 = {"hidden": want, "named": missing, "n_on_disk": len(on_disk),
                      "n_expected": len(expected), "ok": bool(hit)}
            finally:
                os.replace(bak, rec["path"])              # ★ finally：任何异常都要还原
    else:
        log("   未指定 --hide ⇒ 这条正对照**没跑**（如实记 None，不记 True）")

    # ---------- 汇总 ----------
    ctrl = {
        "P2_unassigned_nonzero": {"n": n_unassigned, "ok": bool(n_unassigned > 0)},
        "P3_footprints_used": {"n_fids_with_faces": len(records), "n_fids": len(fid_all),
                               "n_assigned": n_assigned,
                               "ok": bool(len(records) > 0 and n_assigned > 0)},
        "P4_frame_match": {"n_bad": len(bad_frame), "ok": len(bad_frame) == 0},
        "P5_readback": {"n_bad": len(bad), "bad": bad, "ok": len(bad) == 0},
        "P6_threshold_has_effect": {"n_at_0": n_assigned0, "n_at_max": n_assigned,
                                    "delta": n_assigned - n_assigned0,
                                    "ok": bool(n_assigned - n_assigned0 > 0)},
        "P1_hide": p1,
    }
    failed = [k for k, v in ctrl.items() if not isinstance(v, dict) or v.get("ok") is not True]

    index = {
        "schema": "cdut3d-reality-drill/1",
        "when": t0.isoformat(timespec="seconds"),
        "edit_dir": a.edit, "out_dir": a.out, "footprints": a.foot,
        "footprints_sha256": _sha_file(a.foot),
        "placement": {"convention": "B", "impl": "reality_placement.enu_to_4544_grid",
                      "decided": "2026-10-15",
                      "anchor": {k: anc[k] for k in ("E4544", "N4544", "h", "lat", "lon")},
                      "anchor_source": "root.transform 平移现解（非手打）"},
        "crs": "EPSG:4544（E, N 米）+ 椭球高 h 米",
        "blocks_used": blocks, "n_blocks_total_on_disk": len(disk),
        "src_tileset_sha256": list(snaps)[0],
        "assign_max_m": assign_max,
        "assign_max_source": {
            "path": os.path.relpath(MISREG_JSON, REPO).replace("\\", "/"),
            "field": MISREG_FIELD, "value": mis["value"], "p90_value": mis.get("p90_value"),
            "note": MISREG_NOTE, "overridden_by_cli": a.assign_max_m is not None,
            "why_not_from_histogram": "本趟直方图**没有谷**（节 `dist_histogram`：段内最低格 %.4g 是本底的 %.4g 倍、"
                                      "其后只回升到 %.4g 倍，两条谷的判据都不过）⇒ 曲线是**单调衰减到本底**，"
                                      "从它取数只会取到 bin 边界值，见 docstring 盲区 8"
                                      % (hist["valley_dip"], hist["valley_dip_over_ambient"] or float("nan"),
                                         hist["valley_rise_over_dip"] or float("nan"))},
        "dist_histogram": hist,
        "n_faces_total": n_faces_all, "n_faces_assigned": n_assigned,
        "n_faces_assigned_inside": n_assigned0, "n_faces_assigned_near": n_assigned - n_assigned0,
        "n_faces_unassigned": n_unassigned,
        "n_faces_multi_hit": int(sum(v["ast"]["n_multi_hit"] for v in per_block.values())),
        "unassigned_by_block": {b: int((per_block[b]["final"] < 0).sum()) for b in blocks},
        "n_fids": len(fid_all), "n_fids_in_region": n_in,
        "n_fids_zero_faces": len(zero),
        "fids_zero_faces_in_region": zero_in,
        "fids_zero_faces_outside_region": zero_out,
        "footprint_repair": {"n_poly": len(idxd["polys"]), "n_make_valid": idxd["n_fixed"],
                             "n_multipolygon": idxd["n_multi"], "n_empty": idxd["n_empty"]},
        "frame_checks": frame_checks,
        "controls": ctrl,
        "blocks": [{
            "fid": r["fid"],
            "path": os.path.relpath(r["path"], a.out).replace("\\", "/"),
            "bytes": os.path.getsize(r["path"]) if os.path.exists(r["path"]) else None,
            "sha256": (_sha_file(r["path"]) if os.path.exists(r["path"]) else None),
            "n_geom": r["n_geom"], "n_f": r["readback_n_f"], "n_v": int(sum(p["n_v"] for p in r["pcs"])),
            "n_f_inside": r["n_f_inside"], "n_f_near": r["n_f_near"],
            "area_m2": round(r["readback_area"], 4),
            "src_blocks": sorted({x[1] for x in r["order_src"]}),
            "pieces": r["pcs"],
            "src_map": [{"geom": x[0], "src_block": x[1], "src_piece": x[2]} for x in r["order_src"]],
            "texture_restore": r["img_restore"],
        } for r in records],
        "rc": None,
    }

    if not a.no_write:
        for rec in records:
            fid = rec["fid"]
            src_lg = per_block[rec["order_src"][0][1]]["lg"]
            lo = [min(p["bounds"][0][i] for p in rec["pcs"]) for i in range(3)]
            hi = [max(p["bounds"][1][i] for p in rec["pcs"]) for i in range(3)]
            lg_out = {
                "schema": SCHEMA,
                "block": fid,
                "src_tileset": src_lg.get("src_tileset"),      # ★ 逐字复制 ⇒ sha256 闸能过
                "frame": src_lg.get("frame"),
                "n_pieces": len(rec["pcs"]),
                "pieces": rec["pcs"],
                "missing_on_disk": [],
                "errors": [],
                "master": {"n_geom": rec["n_geom"], "n_f": rec["readback_n_f"],
                           "n_v": int(sum(p["n_v"] for p in rec["pcs"])),
                           "bounds": [lo, hi],
                           "bytes": os.path.getsize(rec["path"]),
                           "sha256": _sha_file(rec["path"]),
                           "image_restore": rec["img_restore"]},
                "master_bbox_enu": list(S2E.enu_bbox(np.asarray([lo, hi], float))),
                "ok": True,
                # ★ 新件专有：这一栋是怎么切出来的（可追溯，不是黑箱）
                "origin": {"tool": "cdut3d/tools/drill_reality.py",
                           "footprints_file": os.path.basename(a.foot),
                           "footprints_sha256": index["footprints_sha256"],
                           "placement": "B（enu_to_4544_grid）",
                           "assign_max_m": assign_max,
                           "assign_max_source": "%s:%s"
                                                % (os.path.relpath(MISREG_JSON, REPO).replace("\\", "/"),
                                                   MISREG_FIELD),
                           "n_f_inside": rec["n_f_inside"], "n_f_near": rec["n_f_near"],
                           "src": [{"block": x[1], "src_piece": x[2], "geom": x[0]}
                                   for x in rec["order_src"]]},
            }
            _dump_bytes(os.path.join(a.out, fid, fid + ".lineage.json"), lg_out)
        _dump_bytes(os.path.join(a.out, "_index.json"), index)

    # ---------- 判词 ----------
    log("")
    log("===== 判词 =====")
    log("单体化 : %s ｜ 面 %d = 已分配 %d + 未分配 %d ｜ 栋 %d（轮廓 %d／覆盖区内 %d／零面 %d）"
        % ("PASS" if not failed else "FAIL " + str(failed), n_faces_all, n_assigned,
           n_unassigned, len(records), len(fid_all), n_in, len(zero)))
    log("  落位 B ｜ ASSIGN_MAX_M=%.4f m（**读 %s:%s**，非手打、非直方图）｜ 多命中面 %d"
        % (assign_max, os.path.relpath(MISREG_JSON, REPO), MISREG_FIELD,
           index["n_faces_multi_hit"]))
    log("  直方图谷：%s ｜ 不靠容差 %d ／ 靠容差捞回 %d"
        % ("有（谷在 [%.2f,%.2f)）" % (hist["valley_bin_left_m"], hist["valley_bin_left_m"] + HIST_STEP_M)
           if hist["knee_found"] else
           ("**没量到**（底为 0 或段太短）" if hist["valley_bin_left_m"] is None else
            "★没有（过渡段最低格是本底的 %.2f 倍、其后只回升 %.2f 倍 ⇒ 单调衰减，阈值因此不取自它）"
            % (hist["valley_dip_over_ambient"], hist["valley_rise_over_dip"])),
           n_assigned0, n_assigned - n_assigned0))
    log("  对照：%s" % " ｜ ".join(
        "%s=%s" % (k, (v.get("ok") if isinstance(v, dict) else v)) for k, v in ctrl.items()))
    rc = RC_FAIL if failed else RC_PASS
    log("  判词 : %s（rc=%d）" % ("PASS" if rc == RC_PASS else "FAIL", rc))
    log("  耗时 %.1f s" % (datetime.datetime.now() - t0).total_seconds())

    if not a.no_write:
        index["rc"] = rc
        index["verdict"] = {"rc": rc, "failed": failed}
        _dump_bytes(os.path.join(a.out, "_index.json"), index)
        with open(os.path.join(a.out, "_drill.run.txt"), "wb") as f:
            f.write(("\n".join(L) + "\n").encode("utf-8"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
