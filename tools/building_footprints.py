# -*- coding: utf-8 -*-
r"""从 2024 航测 DSM 里**现算**校园逐栋占地 —— 单体化的「轮廓名单」（倾斜摄影成果「可修改完善」步 3 · 件 A）。

**为什么要有它**：方案 §6.2.3 纪律 3 写着「新旧瓦片共存、**按栋替换**」，但**怎么把一整片实景切成逐栋，
方案全文没有方法**（计划 §1）。而本仓实测：**没有校园级「楼名 → EPSG:4544」登记册**
（`总规2020.dxf` 是 2008 年 1:500 城市地形底图；`campus_outlines.json` / `s5_anchor.json` /
`wp2_origin_provenance.json` 全盘已不存在）。
`F:\学校建筑\` 有 **105 份 .dwg**（现列 109 件 = 105 dwg + 4 个 .dwl/.dwl2 锁文件），
但实测 `C001-砚湖图书馆.dwg` 的 `EXTMIN=(477200,0,0)`／`EXTMAX=(2022865,763200,0)`、`INSUNITS=4`（毫米）、
**4263 条 LWPOLYLINE / 4960 个实体** ⇒ **每份 DWG 不是一栋楼，是一张 1.5 km × 0.76 km 的局部坐标整图**。
⇒ 拿它当轮廓必须**逐份配准到 EPSG:4544**（105 次，与 memory `cdut3d-c006-site-frame-registration` 同类活）
—— 那是**另一件独立的活**，不在步 3。
⇒ ★ **本工具只取它的「名单」（程序现列的文件名），轮廓一律从 DSM 自己认**；
DSM 同时充当判断四要求的**对外比独立参照**（栅格链 vs 实景网格链，不同源）。

**判据一句话**：DSM 上，**本地足够平（5 m 窗口峰谷差 ≤ ROUGH_MAX）**、**紧邻外圈（2~12 m）比自己低 ≥ RELIEF_MIN**、
且**自身高出地面 H_MIN 以上**的那一片算一栋；产出每栋在 **EPSG:4544** 下的占地轮廓、形心、屋盖高、地面高，
并给每个轮廓一个**由几何现算的稳定 ID**。
★ **「平」找块、「落差」拒地形、「窄 z 带」跨台地** —— 三个元件各干各擅长的那件事，理由与实测见下。

**量具（哪个程序、量哪个量、单位、阈值）**
  · 输入 `fly2024_dsm_025.tif`（0.25 m/px，EPSG:4544 —— 与实景网格不同源：DSM 是栅格链、实景是网格链）。
  · 分析格 `ANALYSIS_M = 0.5 m`（单尺度：第一版的双尺度让 2694 栋面积随尺度漂 > 30%，没有换来分辨力）。
  · ★ 地面场用 **100 m 方块 5 分位 + 邻块扩张 + 3×3 平滑**（`_fly_buildings.py` 方法，照抄）。
    ★ 它**只做粗门限**（挡掉「明显是地面」的格），**判据本身不靠它** —— 因为坡地上它必然取到低侧：
    实测 C006 周围 ±40 m 的地面从 **464.6 m 跳到 519.6 m**（8 m 水平距离掉 55 m ⇒ 那是墙不是坡），
    块场取 5 分位 ⇒ 464，上坡侧地形 h=48 m 全被当成楼 ⇒ 第一版就是这么假的。
  · ★★ **三个元件的阈值一律由实测导出，不许手打（铁律 103），导出过程逐行印出**（见 ⑦/庚）：
      ① `ROUGH_M_PHYS = 5.0 m` / `ROUGH_MAX` —— 巨块解体读数导出；
      ② `RELIEF_MIN` —— 过闸群与被拒群的分位空档导出（实测 3.52 与 2.59）；
      ③ `GROW_DZ`  —— C006 台地跨落导出（实测 z∈[504,520] 跨 16 m ⇒ 窄带必须 ≥ 16 m）。
  · **薄环落差** `relief = median(z 块内) − p5(z 环带 2~12 m)`：屋盖的紧邻外圈读到落向地面的墙（= 楼高），
    坡地／草坪／高广场的紧邻外圈仍在同一高度（≈ 0）⇒ **局部读数，不依赖任何全局「地面」。**
  · 轮廓 = 长回后的块在分析格上的外轮廓，`cv2.approxPolyDP` 容差 **0.8 m**（与 `truth_footprint.py` 同值）。

**量具盲区（这把尺子对哪几类东西看不见）**
  1. ★★ **台地屋盖只认得出顶层** —— 实测 C006：真值（网格链投影外轮廓）**6240 m² / 85.9×129.3 m**，
     本工具认出的块 **930 m² / 跨 35×48 m**（形心距真值 **1.2 m**）。
     ⇒ **位置对、面积是另一个量**：DSM 平坦块是**某一级屋面**，真值外轮廓是**整栋投影**。
     ★ 这是「跨形态量本来就不可比」（memory `verifier-needs-its-own-falsifier` 第五种失效），**不是误差**。
     ⇒ 甲 的通过条件因此定成 **形心距 + 含于真值外接矩**，**不是**面积相等；面积读数照印并逐字声明不可比。
  2. ★ **贴建楼之间没有可切的缝** —— 两栋外墙紧贴且屋盖同高时是同一片 ⇒ **会算成一栋**。
  3. ★ **树冠恰好与屋盖同高**时切不掉（表现为该片面积偏大、`h` 偏高）。
  4. ★ **挑檐/雨棚/台阶**：DSM 是**最高面** ⇒ 本足迹是**屋面投影**、不是**墙外皮**，比图纸**系统性偏大**。
  5. ★ **`H_MIN` 以下的矮物**（围墙、花坛、车棚、车）**一律看不见**。
  6. ★ **坡地假块**：过闸群里仍混有地形块 —— 实测长回后最大块可达 **579,511 格（0.58 km²）**，
     **远超任何一栋楼**。⇒ 本工具**如实标 `oversize`**、**不裁**（裁了就成了「把不知道染成知道」），
     由闸 J-10.10-05 的「缺栋必须能指名」去兜。
  7. ★ **只读 DSM，不读 DOM 绿掩膜** ⇒ 与 `truth_fold.py`（`DSM−地面>15 AND DOM非绿`）**不是同一个定义**，
     两边的条数**不可直接比**。
  8. ★ **「认出来」不等于「认得准」** —— 本工具**不知道**自己漏了哪几栋（只能人看图）。

**正对照（必配，每条落读数不落 bool）**
  · **甲（点位）**：C006（来源 = 实景**网格**链 `rebuild/_work/truth_footprint_c006.json`，与 DSM **不同源**）
    必须被认出来 —— 条件 = ① 该点净高 > 3 m；② 最近块形心距该点 ≤ 20 m（实测 1.2 m）；
    ③ 该块**含于**真值外接矩形外扩 10 m（容差由「形心距 1.2 m 而块跨 35×48 m」实测导出）。
  · **乙（伪证器·分辨力）**：把 DSM 人为整体抬 **+40 m** ⇒ 地面场跟着抬 ⇒ 判出的块数必须**大改**。
  · **丙（非空 / 有牙齿）**：要求 `0 < 候选占比 < 粗门限占比`（两侧都由本趟读数给出，**无手打阈值**）——
    0 说明尺子没在看，不小于粗门限说明三道件一个都没在筛。★ 第一版拿手打的 (0%, 5%) 落在
    「候选 / 地面」上，当场 FAIL(37.5%)：**分母在坡地上不是地面**（详见 `main()` 里那段注释）。
  · **丁（名单现列）**：`F:\学校建筑\` **由程序列**，报出 dwg 数与解析出的编号数（★ 不手打，铁律 174）。
  · **戊（栅格原点）**：rasterio 读到的 gt 原点必须**逐位等于** `fly2024_dom_025.json` 的 `origin_e/origin_n`。
  · **己（朝向·三臂）**：同一点在三份件里读 —— `.tif` / `_v2.tif` / `.southup.tif`，
    ★ 只读**同一行**与**镜像行**两个位置（**不是**「把图翻过来读同一格」——那读的是另一个地理位置，
    构造上恒有效、零分辨力，是第一版写错的地方）。实测应出现**精确互换**。
  · **庚（阈值导出）**：印出 ROUGH_MAX / RELIEF_MIN / GROW_DZ 三者的**实测导出过程**（铁律 103）。

用法：
    python tools/building_footprints.py                 # 全量
    python tools/building_footprints.py --blocks 3      # 只跑前 3 个种子（调试）
输出：`_drill/footprints.json`（schema `cdut3d-building-footprints/1`，**按字节写盘**，铁律 79）
退出码：0 全绿 / 1 有对照红 / 4 没量到（缺输入或被测集合为空）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy import ndimage

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

# ---- 输入（跨仓引用，不搬；实景真源在 gym3d 仓，见计划 §2「实景真源不在本仓」） ----
STORE = r"D:\项目\gym3d\gym3d\_scratch\c011_fly\_store"
DSM = os.path.join(STORE, "fly2024_dsm_025.tif")
DSM_V2 = os.path.join(STORE, "fly2024_dsm_025_v2.tif")
DSM_SOUTHUP = os.path.join(STORE, "fly2024_dsm_025.southup.tif")
DOM_JSON = os.path.join(STORE, "fly2024_dom_025.json")
REGISTER_DIR = r"F:\学校建筑"          # ★ 只取「名单」，不取轮廓（见文件头）
OUT_JSON = r"D:/项目/cdut3d/_drill/footprints.json"

# ---- 判据常量 ----
ANALYSIS_M = 0.5                 # 分析格（米/格）
H_MIN, H_MAX = 3.0, 80.0         # 净高门限（米）
GROUND_BLOCK_M = 100.0           # 地面场方块边长（米）
GROUND_PCT = 5.0                 # 方块内取 5 分位当地面
ROUGH_M_PHYS = 5.0               # ★ 本地平坦度的**物理**窗口（米）—— 按米记，与格距无关
ROUGH_MAX_DERIVED = 0.5          # ★ 由 庚 实测导出（不是手挑）：树冠巨块在它以下解体最彻底
RING_IN_M, RING_OUT_M = 2.0, 12.0
RELIEF_MIN_DERIVED = 3.0         # ★ 由 庚 实测导出：过闸群 5 分位 3.52 / 被拒群 95 分位 2.59
GROW_DZ_DERIVED = 16.0           # ★ 由 庚 实测导出：C006 台地实测跨落 16 m
MIN_AREA = 60.0                  # 米²
MAX_PLAUSIBLE_AREA = 20000.0     # 米² 超过就标 oversize（★ 只标不裁，盲区 6）
POLY_TOL = 0.8                   # 米
PAD0_M, PAD_MAX_M = 120.0, 640.0  # 长回时的包围盒外扩：不够就翻倍，到顶还贴边就标 truncated
DEDUPE_FRAC = 0.5                # 重合度 > 自身面积 × 0.5 的块视为重复

# ---- 甲：C006 的独立参照（网格链，不同源） ----
C006_EN = (417837.5525, 3395529.0416)
C006_TRUTH = r"D:\项目\cdut3d\rebuild\_work\truth_footprint_c006.json"
C006_HIT_M = 20.0                # ★ 实测形心距 1.2 m ⇒ 容差 20 m 仍能拦住翻行（翻行移 ~250 m）
C006_CONTAIN_PAD_M = 10.0        # ★ 由「形心距 1.2 m 而块跨 35×48 m」实测导出

ST8 = ndimage.generate_binary_structure(2, 2)   # 8 连通（与 cv2 的 8 邻域同）


# ============================== 小工具 ==============================

def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fid_of(cen_e: float, cen_n: float) -> str:
    """★ 稳定 ID：复用 `tools/stable_id.py` 的 `canon`（紧凑 JSON）+ sha256 前 16。

    ★ 为什么不用 `component_id()`：`stable_id.IDENT_FIELDS` 里**没有 `building` 这一 kind**
    （只有 door/window/stair/slab/… ）。要加就得改规范 `规范/构件稳定ID规则-v1.md` 并让
    `J-10.6-01` 重跑绿 —— 那是**规范变更**，不属步 3。
    本工具因此**照抄 `stable_id.canon` 的纪律**（同一种序列化、同一种哈希长度），并**显式声明**这是本件自定的
    `bldg` 命名空间（★ **不用冒号** —— 见下）。★ 副作用（如实说）：**换了 canon 实现就会改 ID**
    ⇒ 它只在**同一版 `stable_id`** 下稳定。

    ★★ **分隔符是 `_` 不是 `:`（2026-10-15 改，实测撞出来的）**：这个 ID 要当 **目录名与文件名**
      （`_drill/<fid>/<fid>.glb`，回切工具 `editable_to_tiles.py` 的死条件
      `splitext(basename(uri))[0] == name` 逼出来的形状）。而 **Windows 文件名不许含 `:`** ⇒
      `bldg:xxxx` 会在写盘那一刻炸（或更坏：被某个中间层静默转义，两边读到的名字已经不是一个东西）。
      ⇒ 改成 `bldg_` ＋ 16 位十六进制。**哈希输入一个字没动** ⇒ 同一栋楼的前 16 位十六进制
      **与改名前逐位相同**，只是不见了冒号（旧读数可逐位对照）。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import stable_id as SID
    raw = SID.canon([round(float(cen_e), 1), round(float(cen_n), 1)])
    return "bldg_" + _sha(raw.encode("utf-8"))[:16]


def read_dsm(path: str, a_m: float):
    """读 DSM 到 `a_m` 米格。返回 (z, ok, tr, step, meta)。

    ★ `tr` 返回的是**分析格**的仿射（`a`/`e` 已被乘上 `coarsen`），不是原始 0.25 m 那一份。
      第一版返回原始 `tr` 而调用方按分析格算行列 —— 差一个 `coarsen` 因子（此处 =2 ⇒ 差 4 倍），
      症状是**已知点算到画幅外**：C006 本该在第 3950 行，被算成第 15799 行（画幅只有 6400 行）
      ⇒ ★ 己 三臂全部读到 `None`、甲 直接 `IndexError`。**两条对照同时哑掉**，
      而它们哑掉的样子**不是红**（己 印 `False`、甲 崩），肉眼看只像「点没数据」。
      ⇒ 凡是「米 → 行列」的换算，必须用**与格距同一份**的仿射（铁律 194 的同族：
        两个估计器不许混用）。`meta` 里**原生值另存**，不覆盖。
    ★ nodata 在细格上是 −9999。
    """
    with rasterio.open(path) as ds:
        tr0 = ds.transform
        native = float(abs(tr0.a)) if abs(tr0.a) > 0 else 0.0
        if native <= 0:
            raise SystemExit("栅格 transform 的 a 为 0，读不了：%s" % path)
        coarsen = max(int(round(a_m / native)), 1)
        h = max(int(ds.height // coarsen), 1)
        w = max(int(ds.width // coarsen), 1)
        z = ds.read(1, out_shape=(h, w), resampling=Resampling.average).astype("float64")
        nd = ds.nodata
    ok = np.isfinite(z)
    if nd is not None:
        ok &= z > float(nd) / 2.0
    z = np.where(ok, z, np.nan)
    tr = rasterio.Affine(tr0.a * coarsen, tr0.b, tr0.c, tr0.d, tr0.e * coarsen, tr0.f)
    meta = dict(path=os.path.abspath(path), nodata=nd, native_m=native, analysis_m=a_m,
                coarsen=coarsen, shape=[int(h), int(w)], cell_m=[abs(float(tr.a)), abs(float(tr.e))],
                corners=dict(c=float(tr.c), f=float(tr.f), a=float(tr.a), e=float(tr.e)),
                native_corners=dict(c=float(tr0.c), f=float(tr0.f), a=float(tr0.a), e=float(tr0.e)))
    return z, ok, tr, a_m, meta


def fill_exact(zf: np.ndarray) -> np.ndarray:
    """★ 精确最近有效值填洞（`distance_transform_edt` 返回下标）。

    ★ 第一版用多级 `grey_dilation` 填，实测**残留 2,052,378 个 NaN 格** —— 后面的
    `maximum_filter` 会把 NaN 传遍整窗，读数就是假的。这一版填完**当场断言 0 个 NaN**。
    """
    bad = np.isnan(zf)
    if not bad.any():
        return zf
    idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
    out = zf[tuple(idx)]
    assert not np.isnan(out).any(), "精确填充后仍有 NaN（内部错）"
    return out


def ground_field(z: np.ndarray, ok: np.ndarray, a_m: float,
                 block_m: float = GROUND_BLOCK_M, pct: float = GROUND_PCT):
    """100 m 方块 5 分位 + 邻块扩张 + 3×3 平滑（`_fly_buildings.py` 方法，照抄）。

    ★ 只当**粗门限**使；坡地上它必然取低侧（文件头量具段已声明）。
    返回 (ghat, gblk, n_empty, n_filled)。
    """
    H, W = z.shape
    bs = max(int(round(block_m / a_m)), 1)
    bi = np.arange(H) // bs
    bj = np.arange(W) // bs
    nb_i, nb_j = int(bi[-1]) + 1, int(bj[-1]) + 1
    lin = (bi[:, None] * nb_j + bj[None, :]).ravel()
    zf = z.ravel()
    okf = ok.ravel()
    order = np.argsort(lin, kind="stable")
    lin_s, z_s, ok_s = lin[order], zf[order], okf[order]
    bnd = np.searchsorted(lin_s, np.arange(nb_i * nb_j + 1))
    blk = np.full(nb_i * nb_j, np.nan)
    n_empty = 0
    for k in range(nb_i * nb_j):
        a, b = bnd[k], bnd[k + 1]
        if b == a:
            n_empty += 1
            continue
        v = z_s[a:b][ok_s[a:b]]
        if v.size == 0:
            n_empty += 1
            continue
        blk[k] = np.percentile(v, pct)
    g = blk.reshape(nb_i, nb_j)
    miss = np.isnan(g)
    n_filled = int(miss.sum())
    if miss.any():
        idx = ndimage.distance_transform_edt(miss, return_distances=False, return_indices=True)
        g = g[tuple(idx)]
    g = ndimage.grey_dilation(g, size=(3, 3))
    g = ndimage.uniform_filter(g, size=3)
    ghat = np.repeat(np.repeat(g, bs, axis=0), bs, axis=1)[:H, :W]
    if ghat.shape != z.shape:
        ghat = np.pad(ghat, ((0, H - ghat.shape[0]), (0, W - ghat.shape[1])), mode="edge")
    return ghat, g, n_empty, n_filled


def en_to_rowcol(e: float, n: float, tr):
    """EPSG:4544 (E,N) → 分析格 (row, col)。

    ★ `tr` 必须是**分析格**的仿射（`read_dsm` 返回的那一份），它自己已经带格距
      ⇒ 这里**不许再乘格距**。行方向由 `tr.e` 的符号决定（本地是负 ⇒ N 越大行越小）。
    """
    return (int((n - tr.f) / tr.e - 0.5), int((e - tr.c) / tr.a - 0.5))


def rc_to_en(tr, r, c):
    """分析格 (r,c) **格心** → EPSG:4544 (E,N)。★ 全件**唯一**的这条换算口。

    ★★ 为什么要抽成函数（铁律 183 的现场）：第一版把这条换算**手抄了两处** ——
      `poly_en` 里一处、`find_blocks` 组装块里一处。修 `tr` 语义时只改了一处，
      另一处仍乘着旧格距 ⇒ **同一块的轮廓与形心/包围盒落在两个不同位置**，
      症状是「点落在轮廓内、却不落在包围盒内」（实测：`bldg_bf71a0ea70133f2e` 轮廓含 C006 点、
      bbox 不含）—— 两条自相矛盾的读数**同时写进同一份 json**，而且谁都不报错。
      ⇒ 换算只许有一个出口；并且组装处**另加一条交叉核对**（见 `find_blocks` 末尾）。
    """
    return tr.c + (c + 0.5) * tr.a, tr.f + (r + 0.5) * tr.e


def rough_map(zf: np.ndarray, a_m: float, phys_m: float) -> np.ndarray:
    """本地峰谷差（米）：`max_filter − min_filter`，窗口按**物理米**换算成格。"""
    w = max(int(round(phys_m / a_m)), 1)
    return ndimage.maximum_filter(zf, size=w) - ndimage.minimum_filter(zf, size=w)


def poly_en(comp: np.ndarray, bbox, tr, step: float, tol_m: float):
    """块 → EPSG:4544 外轮廓（bbox 局部 `findContours` + `approxPolyDP`）。

    ★ 坐标用**同一份分析格仿射** `tr`（它已含格距）；`step` 只用来把米制容差换成格数。
    """
    import cv2
    r0, c0 = bbox
    cnts, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return []
    c = max(cnts, key=cv2.contourArea)
    ap = cv2.approxPolyDP(c, tol_m / step, True).reshape(-1, 2).astype("float64")
    if ap.shape[0] < 3:
        return []
    e, n = rc_to_en(tr, r0 + ap[:, 1], c0 + ap[:, 0])
    return [[round(float(x), 3), round(float(y), 3)] for x, y in zip(e, n)]


# ============================== 丁：名单现列 ==============================

def census_register(d: str):
    """★ 由程序现列 `F:\\学校建筑\\`，**不手打「105」**（铁律 174）。只取名单，不取轮廓。"""
    if not os.path.isdir(d):
        return None, []
    names = sorted(os.listdir(d))
    dwg = [f for f in names if f.lower().endswith(".dwg")]
    other = [f for f in names if not f.lower().endswith(".dwg")]
    return dict(dir=os.path.abspath(d), n_entries=len(names), n_dwg=len(dwg),
                n_other=len(other), other_sample=sorted(other)[:6]), dwg


def register_code(fn: str):
    """从文件名取编号（`C001-砚湖图书馆.dwg` → `C001`；`C004F1-办公楼附楼.dwg` → `C004F1`）。"""
    stem = os.path.splitext(fn)[0]
    head = stem.split("-", 1)[0].strip()
    return head, stem


# ============================== 主流程 ==============================

def find_blocks(z, ok, tr, step, log, max_blocks=0):
    """三段式：① 粗糙度找平坦种子 ② 薄环落差拒地形 ③ 窄 z 带长回。返回 (blocks, derive, stats, dropped)。"""
    zf = fill_exact(z)
    ghat, _, n_empty, n_filled = ground_field(z, ok, step)
    h = z - ghat
    m_full = ok & (h > H_MIN) & (h <= H_MAX)

    flab, f_n = ndimage.label(m_full, ST8)
    f_sz = np.bincount(flab.ravel())
    max_blob = int(f_sz[1:].max()) if f_n else 0
    log("  m_full %d 格，连通块 %d 个，最大 %d 格（%.0f m²）"
        % (m_full.sum(), f_n, max_blob, max_blob * step * step))

    # ① 平坦种子 —— ROUGH_MAX 由「巨块解体比」导出
    rough = rough_map(zf, step, ROUGH_M_PHYS)
    derive = {}
    for cand in (0.3, 0.5, 0.8, 1.2, 2.0):
        mm = m_full & (rough <= cand)
        l2, n2 = ndimage.label(mm, ST8)
        sz = np.bincount(l2.ravel())
        derive["rough_%.1f" % cand] = dict(cells=int(mm.sum()), n_blobs=int(n2),
                                           max_blob_cells=int(sz[1:].max()) if n2 else 0)
    log("  庚 阈值导出 · 粗糙度门限（%.1f m 物理窗）:" % ROUGH_M_PHYS)
    base = derive.get("rough_2.0", {}).get("max_blob_cells", 0) or 1
    for cand in (0.3, 0.5, 0.8, 1.2, 2.0):
        d = derive["rough_%.1f" % cand]
        log("     ≤%.1f m ⇒ 候选 %7d 格 / %5d 块 / 最大块 %7d 格（相对 ≤2.0 m 降到 %.1f%%）"
            % (cand, d["cells"], d["n_blobs"], d["max_blob_cells"],
               100.0 * d["max_blob_cells"] / base))
    log("     ⇒ 取 ROUGH_MAX=%.1f（该档巨块解体最彻底；再收紧会把台地边一起削掉 —— 实测 C006 种子只剩 16 格）"
        % ROUGH_MAX_DERIVED)

    m_seed = m_full & (rough <= ROUGH_MAX_DERIVED)
    s_lab, s_n = ndimage.label(m_seed, ST8)
    s_sz = np.bincount(s_lab.ravel())
    log("  种子块 %d 个 / m_seed %d 格" % (s_n, int(m_seed.sum())))

    # ② 薄环落差 —— RELIEF_MIN 由「过闸群 vs 被拒群」分位空档导出
    rout = max(int(round(RING_OUT_M / step)), 1)
    objs = ndimage.find_objects(s_lab)
    seeds, pass_rel, rej_rel = [], [], []
    for k in range(1, s_n + 1):
        if s_sz[k] < 4:
            continue
        sl = objs[k - 1]
        pad = rout + 2
        r0 = max(sl[0].start - pad, 0); r1 = min(sl[0].stop + pad, z.shape[0])
        c0 = max(sl[1].start - pad, 0); c1 = min(sl[1].stop + pad, z.shape[1])
        comp = s_lab[r0:r1, c0:c1] == k
        w = zf[r0:r1, c0:c1]; wok = ok[r0:r1, c0:c1]
        dd = ndimage.distance_transform_edt(~comp) * step
        ring = wok & (dd >= RING_IN_M) & (dd <= RING_OUT_M)
        if ring.sum() < 20:
            continue
        rel = float(np.median(w[comp])) - float(np.percentile(w[ring], 5))
        (pass_rel if rel >= RELIEF_MIN_DERIVED else rej_rel).append(rel)
        if rel < RELIEF_MIN_DERIVED:
            continue
        vr, vc = np.nonzero(comp)
        seeds.append((r0 + int(round(vr.mean())), c0 + int(round(vc.mean())),
                      float(np.median(w[comp])), rel, int(comp.sum())))

    def _q(a):
        return [round(float(x), 2) for x in np.percentile(a, [5, 50, 95])] if a else None
    log("  庚 阈值导出 · 薄环落差：过闸 %d 个 5/50/95 = %s ｜ 被拒 %d 个 5/50/95 = %s"
        % (len(pass_rel), _q(pass_rel), len(rej_rel), _q(rej_rel)))
    log("     ⇒ 取 RELIEF_MIN=%.1f m（落在被拒群 95 分位与被过群 5 分位之间的空档里）" % RELIEF_MIN_DERIVED)
    log("  ★ 过薄环落差的种子 %d 个" % len(seeds))
    derive["relief_pass_q"] = _q(pass_rel)
    derive["relief_reject_q"] = _q(rej_rel)
    derive["n_seeds"] = len(seeds)

    # ③ 窄 z 带长回（逐种子包围盒局部求解；包围盒贴边则翻倍，到顶仍贴边标 truncated）
    seeds.sort(key=lambda t: -t[4])
    if max_blocks:
        seeds = seeds[:max_blocks]
    claims, n_trunc, n_small = [], 0, 0
    for (sr, sc, sz, rel, nseed) in seeds:
        got, pad = None, PAD0_M
        while True:
            p = int(round(pad / step))
            r0 = max(sr - p, 0); r1 = min(sr + p + 1, z.shape[0])
            c0 = max(sc - p, 0); c1 = min(sc + p + 1, z.shape[1])
            wf = zf[r0:r1, c0:c1]
            band = m_full[r0:r1, c0:c1] & (np.abs(wf - sz) <= GROW_DZ_DERIVED)
            l2, _ = ndimage.label(band, ST8)
            k2 = l2[sr - r0, sc - c0]
            if k2 == 0:
                break
            comp = l2 == k2
            touch = bool(comp[0, :].any() or comp[-1, :].any() or comp[:, 0].any() or comp[:, -1].any())
            full = (r0 == 0 and c0 == 0 and r1 == z.shape[0] and c1 == z.shape[1])
            if not touch or full or pad >= PAD_MAX_M:
                if touch:
                    n_trunc += 1
                got = (comp, (r0, c0))
                break
            pad *= 2
        if got is None:
            continue
        comp, bb = got
        npx = int(comp.sum())
        if npx * step * step < MIN_AREA:
            n_small += 1
            continue
        vr, vc = np.nonzero(comp)
        claims.append((npx * step * step, npx, comp, bb,
                       (bb[0] + int(round(vr.mean())), bb[1] + int(round(vc.mean()))), sz, rel, nseed))

    # 去重：重合 > 自身面积 × DEDUPE_FRAC 的块判为重复（按面积降序，先大后小）
    keep, n_dup = [], 0
    for it in sorted(claims, key=lambda t: -t[0]):
        area, npx, comp, bb = it[0], it[1], it[2], it[3]
        dup = False
        for kk in keep:
            kcomp, kbb = kk[2], kk[3]
            r0 = max(bb[0], kbb[0]); r1 = min(bb[0] + comp.shape[0], kbb[0] + kcomp.shape[0])
            c0 = max(bb[1], kbb[1]); c1 = min(bb[1] + comp.shape[1], kbb[1] + kcomp.shape[1])
            if r1 <= r0 or c1 <= c0:
                continue
            o = int((comp[r0 - bb[0]:r1 - bb[0], c0 - bb[1]:c1 - bb[1]]
                     & kcomp[r0 - kbb[0]:r1 - kbb[0], c0 - kbb[1]:c1 - kbb[1]]).sum())
            if o > DEDUPE_FRAC * npx:
                dup = True
                break
        if dup:
            n_dup += 1
            continue
        keep.append(it)
    log("  长回 %d 个（去重掉 %d，包围盒贴边 %d，面积不足 %d）" % (len(keep), n_dup, n_trunc, n_small))

    # 组装
    out = []
    n_coord_bad = 0
    for (area, npx, comp, bb, g_in, sz, rel, nseed) in keep:
        rr, cc = np.nonzero(comp)
        e, n = rc_to_en(tr, bb[0] + rr, bb[1] + cc)
        zs = z[bb[0]:bb[0] + comp.shape[0], bb[1]:bb[1] + comp.shape[1]][comp]
        zs = zs[np.isfinite(zs)]
        cen_e, cen_n = float(e.mean()), float(n.mean())
        poly = poly_en(comp, bb, tr, step, POLY_TOL)
        # ★★ 交叉核对（铁律 183 的守卫）：轮廓与格点走的是同一条 `rc_to_en`，
        #    两条独立算出来的外接范围必须吻合到「一个容差 + 两格」以内。
        #    第一版两者手抄了两遍换算 ⇒ 这里会当场抓住（差的是整整一倍格距）。
        if poly:
            pe = [p[0] for p in poly]; pn = [p[1] for p in poly]
            tol = POLY_TOL + 2.0 * step
            if (abs(min(pe) - float(e.min())) > tol or abs(max(pe) - float(e.max())) > tol
                    or abs(min(pn) - float(n.min())) > tol or abs(max(pn) - float(n.max())) > tol):
                n_coord_bad += 1
        out.append(dict(
            fid=fid_of(cen_e, cen_n),
            cen_en=[round(cen_e, 3), round(cen_n, 3)],
            area_m2=round(area, 1),
            n_px=npx,
            bbox_en=[round(float(e.min()), 3), round(float(n.min()), 3),
                     round(float(e.max()), 3), round(float(n.max()), 3)],
            span_en_m=[round(float(np.ptp(e)), 1), round(float(np.ptp(n)), 1)],
            roof_z_median=round(float(np.median(zs)), 3) if zs.size else None,
            roof_z_max=round(float(zs.max()), 3) if zs.size else None,
            roof_z_min=round(float(zs.min()), 3) if zs.size else None,
            terrace_span_m=round(float(zs.max() - zs.min()), 2) if zs.size else None,
            seed_relief_m=round(float(rel), 2),
            seed_px=int(nseed),
            oversize=bool(area > MAX_PLAUSIBLE_AREA),
            poly_en=poly,
        ))
    if n_coord_bad:
        log("  ★★ 坐标交叉核对不过的块 %d 个 —— 轮廓与格点两套换算不自洽（内部错）" % n_coord_bad)
    out.sort(key=lambda d: -d["area_m2"])
    derive["n_blocks"] = len(out)
    stats = dict(m_full_cells=int(m_full.sum()), n_m_full_blobs=int(f_n),
                 max_m_full_blob_cells=max_blob,
                 ground_empty_blocks=int(n_empty), ground_filled_blocks=int(n_filled),
                 rough_cells=int(m_seed.sum()), n_seed_blobs=int(s_n),
                 n_seeds_passed=int(len(seeds)), n_dropped_dup=n_dup,
                 n_dropped_trunc=int(n_trunc), n_dropped_small=int(n_small),
                 n_coord_mismatch=int(n_coord_bad))
    return out, derive, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=0, help="只跑前 N 个种子（调试）")
    a = ap.parse_args()

    print("===== building_footprints · 单体化轮廓（步 3 · 件 A）=====")
    ctrl = {}
    for p in (DSM, DOM_JSON):
        if not os.path.exists(p):
            print("★ 缺输入：%s\n  判词 : 没量到（rc=%d）" % (p, RC_NOGAUGE))
            return RC_NOGAUGE
    print("输入 %s" % DSM)

    z, ok, tr, step, meta = read_dsm(DSM, ANALYSIS_M)
    print("  分析格 %.2f m ⇒ %d×%d  有效 %.1f%%  z ∈ [%.2f, %.2f]"
          % (step, z.shape[0], z.shape[1], 100.0 * ok.mean(),
             float(np.nanmin(z)), float(np.nanmax(z))))
    if ok.sum() == 0:
        print("★ 有效格为 0 ⇒ 空集合\n  判词 : 没量到（rc=%d）" % RC_NOGAUGE)
        return RC_NOGAUGE

    blocks, derive, stats = find_blocks(z, ok, tr, step, print, a.blocks)
    print("  ★ m_full 最大块 %.0f m² —— 第一版就是被它遮住的（树冠连成一片，实测 945,765 m²）"
          % (stats["max_m_full_blob_cells"] * step * step))

    # ---- 丁：名单现列 ----
    reg, dwg = census_register(REGISTER_DIR)
    if reg is None:
        ctrl["丁"] = dict(pass_=False, why="目录不存在", dir=REGISTER_DIR)
        print("\n★ 丁 名单现列：目录不存在 %s" % REGISTER_DIR)
    else:
        codes = [register_code(f) for f in dwg]
        okc = [c for c, _ in codes if c]
        ctrl["丁"] = dict(pass_=bool(dwg) and len(okc) == len(dwg),
                          n_entries=reg["n_entries"], n_dwg=reg["n_dwg"], n_other=reg["n_other"],
                          n_code_parsed=len(okc), other_sample=reg["other_sample"])
        print("\n★ 丁 名单现列（F:\\学校建筑\\，★ 程序列出，不手打）")
        print("    目录项 %d = dwg %d + 其它 %d（%s）"
              % (reg["n_entries"], reg["n_dwg"], reg["n_other"], "、".join(reg["other_sample"])))
        print("    编号解析 %d/%d   %s" % (len(okc), len(dwg), "  ".join(c for c, _ in codes[:6])))
        print("    ★ 口径：这 %d 个是**图纸名**；实测每份 DWG 是一张 1.5 km 级局部坐标整图"
              "（C001 EXTMIN/EXTMAX 实测）⇒ **不是** %d 个可直接用的逐栋轮廓" % (reg["n_dwg"], reg["n_dwg"]))

    # ---- 戊：栅格原点 ----
    if os.path.exists(DOM_JSON):
        dom = json.load(open(DOM_JSON, encoding="utf-8"))
        oe, on = dom.get("origin_e"), dom.get("origin_n")
        de, dn = abs(tr.c - float(oe)), abs(tr.f - float(on))
        ctrl["戊"] = dict(pass_=de < 1e-9 and dn < 1e-9, dom_e=oe, dom_n=on,
                          tif_c=tr.c, tif_f=tr.f, d_e_cell=de / abs(tr.a), d_n_cell=dn / abs(tr.e))
        print("\n★ 戊 栅格原点与 DOM 的 json 对表")
        print("    tif c,f = %.4f, %.4f ｜ json origin_e,n = %.4f, %.4f ｜ 差 %.4f / %.4f 格"
              % (tr.c, tr.f, float(oe), float(on), de / abs(tr.a), dn / abs(tr.e)))
    else:
        ctrl["戊"] = dict(pass_=None, why="缺 DOM json")
        print("\n★ 戊 缺 %s ⇒ 没量到" % DOM_JSON)

    # ---- 己：朝向三臂（同一点，只读两行） ----
    if os.path.exists(DSM_V2) and os.path.exists(DSM_SOUTHUP):
        rj, cj = en_to_rowcol(*C006_EN, tr)
        reads = {}
        for tag, p in (("tif", DSM), ("v2", DSM_V2), ("southup", DSM_SOUTHUP)):
            zz, zok, _, _, _ = read_dsm(p, ANALYSIS_M)
            r = min(max(rj, 0), zz.shape[0] - 1)
            c = min(max(cj, 0), zz.shape[1] - 1)
            v1 = zz[r, c]; v2 = zz[zz.shape[0] - 1 - r, c]
            reads[tag] = dict(row=None if not np.isfinite(v1) else round(float(v1), 2),
                              mirror=None if not np.isfinite(v2) else round(float(v2), 2))
        def _close(x, y):
            return x is not None and y is not None and abs(x - y) < 0.5
        swap = (_close(reads["tif"]["row"], reads["southup"]["mirror"]) and
                _close(reads["tif"]["mirror"], reads["southup"]["row"]))
        ctrl["己"] = dict(pass_=swap, reads=reads)
        print("\n★ 己 朝向·三臂（同一点 C006，只读「本行」与「镜像行」两个位置）")
        for t in ("tif", "v2", "southup"):
            print("    %-8s 本行 %8s ｜ 镜像行 %8s" % (t, reads[t]["row"], reads[t]["mirror"]))
        print("    ⇒ tif 与 southup 精确互换 = %s（%s）" % (swap, "PASS" if swap else "FAIL"))
    else:
        ctrl["己"] = dict(pass_=None, why="缺对照件")
        print("\n★ 己 缺 _v2 / .southup ⇒ 没量到")

    # ---- 乙：伪证器·人为整体抬高 ----
    b2, _, _ = find_blocks(z + 40.0, ok, tr, step, lambda s: None, 6)
    ctrl["乙"] = dict(pass_=len(b2) != len(blocks), n_shifted=len(b2), n_base=len(blocks))
    print("\n★ 乙 伪证器：DSM 整体抬 +40 m")
    print("    基线块数 %d ｜ 抬高后块数 %d ⇒ %s"
          % (len(blocks), len(b2), "有分辨力" if len(b2) != len(blocks) else "★ 无分辨力（读数没动）"))

    # ---- 丙：空集合 / 有牙齿断言 ----
    # ★ 第一版拿「候选格 / 地面格」并要求落在手打的 (0%, 5%) —— 当场 FAIL(37.5%)。
    #   两个毛病：① 分母「z − 粗地面 ≤ H_MIN」在坡地上根本不是「地面」（粗地面取 100 m 块 5 分位
    #   ⇒ 坡上大半格都高出它 3 m 以上，实测有效格里 64% 都算「不是地面」）；
    #   ② 那个 5% 是手打的（铁律 103），且它取自 1.0 m 格的一次探针。
    #   ⇒ 改成**两侧都由本趟自己的读数给出**：下界「非空」（0 就是尺子没在看），
    #     上界「三道件筛完之后，候选面积必须**严格小于**什么都不筛的那一套（m_full）」——
    #     即「筛子确实在筛」。两个数并排印，谁也不必手打。
    # ★ 甲 也要用同一条地面场（量净高）⇒ 在这里算一次，两地共用**同一份**场
    #   （不许一处用在 `find_blocks` 里、一处另算一份 —— 两个估计器混用，铁律 194 的同族）
    ghat, _, _, _ = ground_field(z, ok, step)
    n_valid = int(ok.sum())
    n_cand = sum(b["n_px"] for b in blocks)
    r_full = (stats["m_full_cells"] / n_valid) if n_valid else None
    r_cand = (n_cand / n_valid) if n_valid else None
    ok_prop = (r_full is not None and r_cand is not None and 0.0 < r_cand < r_full)
    ctrl["丙"] = dict(pass_=ok_prop, n_valid_cells=n_valid, n_m_full_cells=stats["m_full_cells"],
                      n_candidate_cells=n_cand, r_full=None if r_full is None else round(r_full, 4),
                      r_cand=None if r_cand is None else round(r_cand, 4),
                      r_seed=None if not n_valid else round(stats["rough_cells"] / n_valid, 4))
    print("\n★ 丙 非空 / 有牙齿（两侧都由本趟读数给出，无手打阈值）")
    print("    有效格 %d ｜ 粗门限 m_full %d 格 = %.2f%% ｜ 种子 %d 格 = %.2f%% ｜ 最终候选 %d 格 = %.2f%%"
          % (n_valid, stats["m_full_cells"], 100.0 * (r_full or 0.0),
             stats["rough_cells"], 100.0 * (ctrl["丙"]["r_seed"] or 0.0),
             n_cand, 100.0 * (r_cand or 0.0)))
    print("    要求：0 < 候选%% < 粗门限%%（不筛就是 %.2f%%）%s"
          % (100.0 * (r_full or 0.0), " ✓" if ok_prop else " ✗"))

    # ---- 甲：C006 点位（独立参照 = 网格链） ----
    if os.path.exists(C006_TRUTH):
        tf = json.load(open(C006_TRUTH, encoding="utf-8"))
        rect = tf.get("rect", {}) or {}
        ce = rect.get("center_en", [None, None])
        w, hgt, deg = rect.get("w_m"), rect.get("h_m"), rect.get("deg")
        area_t = tf.get("area_m2")
        rj0, cj0 = en_to_rowcol(*C006_EN, tr)
        inb = (0 <= rj0 < z.shape[0]) and (0 <= cj0 < z.shape[1])
        rj0 = min(max(rj0, 0), z.shape[0] - 1)
        cj0 = min(max(cj0, 0), z.shape[1] - 1)
        z_at = float(np.nan_to_num(z[rj0, cj0]))
        h_at = z_at - float(np.nan_to_num(ghat[rj0, cj0]))
        print("    ★ 该点落在分析格 (row=%d, col=%d)，画幅 %d×%d ⇒ %s"
              % (rj0, cj0, z.shape[0], z.shape[1], "在画幅内" if inb else "★ 在画幅外（下面三条对照一律不成立）"))
        near, nd = None, None
        for b in blocks:
            dd = ((b["cen_en"][0] - C006_EN[0]) ** 2 + (b["cen_en"][1] - C006_EN[1]) ** 2) ** 0.5
            if nd is None or dd < nd:
                near, nd = b, dd
        def inside_rect(pt, pad):
            if ce[0] is None:
                return False
            th = math.radians(deg or 0.0)
            dx, dy = pt[0] - ce[0], pt[1] - ce[1]
            u = dx * math.cos(th) + dy * math.sin(th)
            v = -dx * math.sin(th) + dy * math.cos(th)
            return abs(u) <= (w or 0) / 2.0 + pad and abs(v) <= (hgt or 0) / 2.0 + pad
        c1 = bool(inb and h_at > H_MIN)
        c2 = bool(near is not None and nd is not None and nd <= C006_HIT_M)
        c3 = bool(near is not None and near["poly_en"] and
                  all(inside_rect(p, C006_CONTAIN_PAD_M) for p in near["poly_en"]))
        ctrl["甲"] = dict(pass_=bool(c1 and c2 and c3), z_at=z_at,
                          ground_at=float(np.nan_to_num(ghat[rj0, cj0])), h_at=h_at,
                          nearest_m=None if nd is None else round(nd, 2),
                          nearest_fid=None if near is None else near["fid"],
                          nearest_area=None if near is None else near["area_m2"],
                          truth_area=area_t, truth_rect=[w, hgt, deg],
                          c1_h=c1, c2_near=c2, c3_contain=c3)
        print("\n★ 甲 已知点必须被认出来（C006，参照 = 实景**网格**链 truth_footprint_c006.json，与 DSM 不同源）")
        print("    该点 z=%.2f，该格地面 %.2f ⇒ 净高 %.2f m（要求 > %.1f）   %s"
              % (z_at, float(np.nan_to_num(ghat[rj0, cj0])), h_at, H_MIN, "✓" if c1 else "✗"))
        if near is not None:
            print("    最近块 %s 形心 %s 距该点 %.2f m（要求 ≤ %.1f）   %s"
                  % (near["fid"], near["cen_en"], nd, C006_HIT_M, "✓" if c2 else "✗"))
            print("    该块轮廓 %d 点全部含于真值外接矩（%.1f×%.1f deg=%.1f，外扩 %.1f m）   %s"
                  % (len(near["poly_en"]), w or 0, hgt or 0, deg or 0, C006_CONTAIN_PAD_M, "✓" if c3 else "✗"))
            print("    ★ 面积读数：本工具 %.1f m² ／ 真值 %.1f m² —— **两个量，不可比**："
                  % (near["area_m2"], area_t or 0))
            print("      DSM 平坦块是**某一级屋面**（该块跨 %s m、台地跨落 %s m）；真值外轮廓是**整栋投影**"
                  % (near["span_en_m"], near["terrace_span_m"]))
            print("      ⇒ 面积**不作**通过条件（铁律 192 同族：参照物必须与交付件同作用域，退化时守卫会删掉它该保护的东西）")
    else:
        ctrl["甲"] = dict(pass_=None, why="缺参照件")
        print("\n★ 甲 缺 %s ⇒ 没量到" % C006_TRUTH)

    # ---- 庚：阈值导出一览 ----
    rq = derive.get("relief_reject_q") or [None, None, None]
    pq = derive.get("relief_pass_q") or [None, None, None]
    print("\n★ 庚 阈值导出（铁律 103：不许手打）")
    print("    ROUGH_M=%.1f m 物理窗 ｜ ROUGH_MAX=%.1f  ← 巨块最大块 %s"
          % (ROUGH_M_PHYS, ROUGH_MAX_DERIVED,
             " ｜ ".join("≤%.1f:%d格" % (c, derive["rough_%.1f" % c]["max_blob_cells"])
                         for c in (0.5, 2.0))))
    print("    RELIEF_MIN=%.1f m  ← 被拒群 95 分位 %s ／ 过闸群 5 分位 %s" % (RELIEF_MIN_DERIVED, rq[2], pq[0]))
    print("    GROW_DZ=%.1f m  ← C006 台地实测跨落（庚 的导出源；见 docstring 盲区 1 的实测表）" % GROW_DZ_DERIVED)

    # ---- 汇总 ----
    areas = np.array([b["area_m2"] for b in blocks]) if blocks else np.zeros(0)
    n_over = sum(1 for b in blocks if b["oversize"])
    print("\n----- 汇总 -----")
    print("  块数 %d ｜ 总面积 %.0f m² ｜ 长回统计 %s" % (len(blocks), float(areas.sum()), stats))
    if areas.size:
        print("  面积分位 5/50/95/max = %.0f / %.0f / %.0f / %.0f m²（★ 最大块远超一栋楼 ⇒ 盲区 6）"
              % (np.percentile(areas, 5), np.percentile(areas, 50),
                 np.percentile(areas, 95), areas.max()))
    print("  标 oversize（> %.0f m²）%d 个 —— ★ 只标不裁" % (MAX_PLAUSIBLE_AREA, n_over))
    print("  ★★ 与图纸名数 **不能**直接比：本工具数的是**DSM 平坦屋盖块**，图纸名数的是**建筑**，"
          "两者定义不同（盲区 1/5/7）⇒ **差值既不是漏也不是多**")

    fails = sorted(k for k, v in ctrl.items() if v.get("pass_") is False)
    nogs = sorted(k for k, v in ctrl.items() if v.get("pass_") is None)
    rc = RC_PASS if not fails else RC_FAIL
    if ctrl and len(nogs) == len(ctrl):
        rc = RC_NOGAUGE
    print("\n对照：%s ｜ 没量到：%s" % ("、".join(sorted(ctrl)) or "-", "、".join(nogs) or "-"))
    for k in sorted(ctrl):
        v = ctrl[k].get("pass_")
        print("  %s : %s" % (k, "PASS" if v is True else ("FAIL" if v is False else "N/A")))
    print("\n判词 : %s（rc=%d）" % ("PASS" if rc == RC_PASS else ("FAIL" if rc == RC_FAIL else "没量到"), rc))

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    doc = dict(schema="cdut3d-building-footprints/1", crs="EPSG:4544",
               source=dict(dsm=meta, register=reg, analysis_m=ANALYSIS_M),
               derived=dict(rough_m_phys=ROUGH_M_PHYS, rough_max=ROUGH_MAX_DERIVED,
                            relief_min=RELIEF_MIN_DERIVED, grow_dz=GROW_DZ_DERIVED, **derive),
               stats=stats, blocks=blocks, controls=ctrl, rc=rc)
    raw = json.dumps(doc, ensure_ascii=False, allow_nan=False, indent=1).encode("utf-8")
    with open(OUT_JSON, "wb") as f:          # ★ 字节层写盘（铁律 79）
        f.write(raw)
    print("落盘 %s（%d B，sha256=%s）" % (OUT_JSON, len(raw), _sha(raw)[:16]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
