# -*- coding: utf-8 -*-
r"""实景瓦片的**落位**——把瓦片里的局部坐标落到 EPSG:4544 与椭球高上。

为什么要单独一件：探针 / 压平工具 / 判据**三处都要用它**，抄三份就是三份会各自漂的副本
（铁律 174：同一个量只许有一个来源）。
★ 现状：`_scratch/_probe_压平.py` 里内联了一份同用途逻辑（`rot_enu2ecef` 等）——
  本件是把它**收成单一来源**；探针保留不动（它是当时的原始读数现场）。

★★ 本件的每一条约定都是**探针实测**出来的（`_scratch/_probe_压平.py`），**不是照抄规范**：

  ① `root.transform` 的 16 元组必须按 **glTF 列主序**读（`reshape(4,4).T`）。
     按行主序读：平移会掉到最后一行（非标准），且落点跑到荒唐处。
     ★ 判据：列主序读出的旋转部分与「**只用平移量反算出的锚点经纬度**搭出的 ENU→ECEF」
       `max|ΔR| = 1.110e-16`。**反算只用平移、完全不看旋转** ⇒ 这是**两把独立的尺子**（铁律 187）。
  ② glTF 内容（`asset.gltfUpAxis = "Y"`）→ 瓦片 ENU（Z-up）：**`(x, y, z) → (x, −z, y)`**。
     实测坐实：叶件翻转后 ENU bbox 中心与 `tileset.json` 该块 `boundingVolume.box` 中心吻合
     （`Tile_+003_+005`：`(784.05, 1185.88, 42.67)` vs `(784.08, 1185.85, 42.66)`）。
  ③ ENU 原点 = `root.transform` 的平移量，其大地坐标 **lat 30.662695421° / lon 104.126476341° /
     h 422.000 m**；投到 4544 恰好 **E 416281.000 / N 3393904.000**
     ⇒ ★★ **与 `理工模型202408` 的局部原点逐位相同**（瓦片与 CAD 模型**共用同一个原点**；
       计划 §2 里「两套锚定方式不同」那句，指的是**朝向约定**，**原点是一套** —— 已被实测改写）。
  ④ 高程**没有大地水准面常数差**（DSM 5 分位 454.31 对网格最低点 454.47，差 0.16 m）
     ⇒ 两边同基准，差值里不含常数项。

  ★★★ ★ **但 ④ 不等于「可以拿 DSM 逐点量残差」—— 那是错的，已实测（2026-10-15）**：
     · 本块网格低区 454.5 / 高区 467.1，而 **DSM 在这两个位置都读到 466**（`_probe_对齐.py` ⑧）。
     · **同一 (E,N) 上网格跨 454.5→467**（含竖直外墙、块边裙边、挑檐），**DSM 只给一个数**。
     · ★ DSM ＝ **表面最高面**，实景网格 ＝ **完整表面**。**这不是误差，是定义差。**
     ⇒ **任何「逐点残差必须下降」的阈值都会被这个定义差主导**，
       不能作为判据（计划步 2 那句出口门「压平后对 DSM 残差必须下降」**据此作废**）。
     ⇒ 可用的替代口径见 `_probe_残差.py`④：**先把「朝上面 ∩ 低 z 带」选出的地面顶点挑出来**，
       只在那批点上量（那里网格与 DSM 是同一曲面）；**楼边竖直面上一律不许量**。

  ★★★ ★★ **落位本身尚未定案 —— 两个候选落法差 11.2 m，证据互相矛盾**（2026-10-15）：
     · 候选 A「真 ENU」（本件现行）：`E,N,h = enu_to_4544(...)`。
     · 候选 B「4544 格网偏移」：`E = E4544_锚 + x_glb`、`N = N4544_锚 − z_glb`、`h = h_锚 + y_glb`。
       动机：**ENU 的北＝大地北，4544 的北＝格网北**，差**子午线收敛角** γ ≈ (λ−λ₀)·sinφ。
       锚点离内容 √(767.9²+1171.6²) ≈ 1400 m ⇒ 预期差 1400·|γ| ≈ **10.9 m**，实测两法差
       (dE −9.3, dN +6.2) = **11.2 m**（差 3%，吻合）。
     · B 在**固定支撑**（两法都落在 DSM 有效像元上的 2201 个顶点）上略好：
       |Δ|中位 **4.541 → 3.075**、|Δ|<1m 23.8% → 36.9%、RMS 7.356 → 6.298。
     · ★ **但反证三条**：① B 之后**残余平移搜索给 (0,0)**（支撑一个不少）；
       ② ⑥ 里「带符号中位居中于 0」的漂亮签名**在固定支撑上消失**（+0.069 → −1.200）
          —— 那是**换靶子**的产物（铁律 197），不是改善；
       ③ 关键的低区读数**几乎没动**（11.39 → 11.32）。
     ⇒ **不得据 B 改写落位**（改了就是过拟合）。定案需要**独立于 DSM 覆盖形状**的尺子，
       DOM 二维配准（`rebuild/_work/regbest_1层.json`，`J-10.8-01` IoU 0.7487）是候补。
     · ★★ **第四把尺子（面积加权顶面掩膜）曾给出唯一一个域内峰，也已作废 —— 而且这次废得最彻底**
       （`_scratch/_probe_顶面掩膜.py`，2026-10-15）。读数：填块包含度 (0,0)=0.3449 →
       峰 **0.4158 @ (dE−8, dN+7) m**（+20.6%）、*形状*伪证器（转 180°）**0.0003**（尺子不哑）。
       看似第一次指向 B（A→B 差向量 (dE−9.3, dN+6.2)，与峰位同向）。
       ⇒ **但三件事同时成立，把它压回弱信号**：
         ① 四象限一致性检验**本身退化**：象限分母仍是整块 `d_roof`（3384 px），
            而象限面积只有 976/229/231/1007 px ⇒ 各自**上限** = 0.288/0.068/0.068/0.298，
            实测四峰 0.2772/0.0671/0.0606/0.1575 中有三个落在**上限的 89% 以上**、
            且四个峰有三个压在**搜索域边界**上 ⇒ **既没确认也没否证**（用坏尺子下的结论同样不许采）。
         ② **填块包含度的上限本来就不是 1**：|网格顶面| = 461.0 m² 是 |DSM 屋顶| = 211.5 m² 的
            **2.2 倍**，且 DSM 在足迹上只有 **28.2%** 有值 ⇒ 0.34~0.42 这个量级读不出「对上一半」。
         ③ ★★★ **最根本的一条：A 与 B 的差别在单块窗口内是「亚像元」的。**
            γ ≈ 0.446°；块窗半径 ≈ 35 m ⇒ 顶点位移 ≈ 35 × 0.0078 = **0.27 m ≈ 1 个像元**，
            而两法的**平移**差 11.2 m 与 γ 在同一窗口内**互相退化**（都能拟合同一个位移）。
            ⇒ **任何只用一个瓦片块、只扫平移的尺子，在原理上就不可能分开 A 与 B。**
            以 2.4 km 校区为准，γ 才折成 **18.7 m** —— 量 γ 必须用**长基线**。
       ⇒ ⇒ **落位定案的正确形状 = 用全校区网格（`campus2024.glb`，1.92 M 顶点）对全幅 DSM，
         扫「绕锚点的方位角 θ + 平移」，θ*≈0 ⇒ A / θ*≈−0.446° ⇒ B**；伪证器必须让
         **期望答案本身随数据变**（人为把网格转 1.0° ⇒ θ* 必须跟着移 1.0°）。
         ★ 在此之前，**不许**把任何「有水平位移」写进任何件。
     · ★ **第三把尺子（块名格网）也已作废**（`_scratch/_probe_瓦片格网.py`，2026-10-15）：块中心在局部 ENU 里成
       ~199.8 m 网格、与 ENU 轴对齐到 **0.02°**（正对照 27.9×，尺子没坏）—— 但**分区是在瓦片自己的帧里切的**，
       `boundingVolume.sphere` 是**内容拟合球**落在**格心**上 ⇒ 它量的是**分区所在的帧**，
       **量不到内容有没有被转过 γ** ⇒ **构造上不敏感**，既不支持 B 也不支持 A。
       上一轮「块名格网＝4544」的猜测据此**推翻**。
       ★ 已排查并否掉的一条：`regbest_1层.json` 的**转角 110°** 是 **CAD 局部轴**的约定，
         不是瓦片的 —— 把本块 ENU 转 110° 会把它推出 DSM 范围（E≈414898 < DSM 左界 416881）。

  ★ **本块 DSM 窗口只有 33.5% 有效**（nodata 集中在南侧/右下），且**有效像元质心相对图幅中心
     本身就偏 (dE +8.9, dN +17.8)** ⇒ ★ **任何「挪网格去找 DSM 有值处」的判据都自带
     向有值方向偏的系统偏差**（`_probe_对齐.py` ③ 实测）。质心类比较**必须先证明覆盖本身不偏**。

  ★★★ ★★★ **落位定案（2026-10-15 晚）：B 成立、A 被排除 —— 上面「未决」那一段到此结束。**
     量具＝上面第 62 行自己写下的「正确形状」：13 块主件的**立面面心 7366 个**绕锚点转 θ，
     `S(θ)` ＝落在 DSM `|∇h|` 上的均值（**固定支撑 4331 点**，支撑数一并印）。
     ★ **长基线**（样点跨全校区，非单块 35 m 窗）⇒ 正是为了绕开 59–61 行那个
       「单块窗口内 A 与 B 互相退化」的死角。
     · 读数 **θ\* = +0.44°**；理论 **γ**（探针 ② 现算）与之差 **0.006°** < 一格 0.02°。
     · θ=0（＝A 的坐标**原样**）处立面点落在 **DSM 平地**（`S(0)=2.106` ≈ 全栅格均值 2.199）
       ⇒ **A 当场被否**，不是「略差一点」。
     · ★ **θ=+0.44° 与 B 是同一件事**：B − A 实测差向量 **(dE −9.3, dN +6.2)**，对照
       「把 A 的坐标绕锚点转 +0.44°」的解析值 **(−θ·N, +θ·E) = (−9.16, +5.90)** ⇒ 两者差
       **0.3 m**（在 1.4 km 基线上）。**符号由这组对照钉死**（原「未决：符号不由本探针分辨」关闭）。
     · 五档对照全过（探针 ⑤–⑨）：4 组互斥子集全落 **+0.44°、彼此差 0.00°**；20 m 抖动
       显著度 **10.68 → 2.99**（峰塌）；峰/零角 **10.5×**；截尾99均值与中位数**都仍 +0.44°**；
       双线性采样**也 +0.44°**。
     ⇒ **本件据此提供 `enu_to_4544_grid()`（＝B）**。`enu_to_4544()`（＝A）**保留不动**，理由：
       ① 锚点处两法同解，A 是「走瓦片自己那条链」的参考实现，删了就丢了对照；
       ② 仓规「**多把尺子只要目标一致就是资产**」。
       ⇒ **凡要落位的件一律用 B**（`drill_reality.py`、后续判据）；A 只作对照。

★ 本件**只读、不写盘**；跨仓只**引用**（`TILES`/`DSM` 在 gym3d 仓的 `_scratch` 下），**不搬**
（搬了会断锚 —— 仓规：源件只引用 + 记 sha256）。
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
import pyproj

# ★ 跨仓引用（gym3d 仓的 `_scratch`）——只引用不搬。版本由调用方各自记 sha256。
TILES = r"D:\项目\gym3d\gym3d\_scratch\_fly2024_tiles"
DSM = r"D:\项目\gym3d\gym3d\_scratch\c011_fly\_store\fly2024_dsm_025.tif"

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

_TF_GEODETIC = pyproj.Transformer.from_crs(4978, 4979, always_xy=True)   # ECEF → 经纬高
_TF_4544 = pyproj.Transformer.from_crs(4978, 4544, always_xy=True)       # ECEF → 4544


def rot_enu2ecef(lat_deg: float, lon_deg: float) -> np.ndarray:
    """ENU→ECEF 旋转：**列** ＝ E / N / U 三轴在 ECEF 里的指向。"""
    la, lo = np.radians(lat_deg), np.radians(lon_deg)
    sl, cl = np.sin(la), np.cos(la)
    so, co = np.sin(lo), np.cos(lo)
    return np.array([[-so, -sl * co, cl * co],
                     [co, -sl * so, cl * so],
                     [0.0, cl, sl]])


def m4(raw16) -> np.ndarray:
    """tileset 的 16 元组 → 4x4 数学矩阵。★ **列主序**（glTF 规范）；见本文件 docstring ①。

    ★ 为什么不用 `reshape(4,4)`：那样平移会落进最后一行。本函数**只在行末列**给出平量，
      且它与「只用平移反算经纬度」那条独立路互相对上（`max|ΔR| = 1.1e-16`）。
    """
    return np.asarray(raw16, dtype=float).reshape(4, 4).T


def gltf_yup_to_enu(v) -> np.ndarray:
    """glTF(Y-up) → 瓦片 ENU(Z-up)：`(x, y, z) → (x, −z, y)`；见 docstring ②。"""
    v = np.asarray(v, dtype=float)
    return np.c_[v[:, 0], -v[:, 2], v[:, 1]]


def enu_to_gltf_yup(e) -> np.ndarray:
    """`gltf_yup_to_enu` 的**逆**：瓦片 ENU → glTF(Y-up)：`(E, N, U) → (E, U, −N)`。

    ★ 必须与本文件的 `gltf_yup_to_enu` **成对**（同一个约定的两个方向，铁律 174：
      同一个量只留一份）—— 别在用得着逆变换的地方各写一份。

    ★ 用途（实测）：`修模·压平` 只改**高程** U ⇒ 落到 glb 里就是**只改第 1 个分量（y）**，
      x=E、z=−N **逐位不动**。这条使「改了哪些点」可以**按位**核，不必引入容差。
    """
    e = np.asarray(e, dtype=float)
    return np.c_[e[:, 0], e[:, 2], -e[:, 1]]


def load_tileset(path: str = None) -> dict:
    p = path or os.path.join(TILES, "tileset.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def anchor(ts: dict) -> dict:
    """由 `root.transform` 的**平移量**反解 ENU 锚点。★ 只用平移，**不看旋转**。

    返回 `R_enu2ecef` 是**自己搭的** —— 它不依赖 tileset 的矩阵约定，
    所以可以拿去**独立校验** `m4()` 的读法（两条路必须对得上）。
    """
    raw = ts["root"]["transform"]
    t = np.asarray(raw, dtype=float).reshape(4, 4)[3, :3]      # 行主序末行 ＝ 列主序末列（同值）
    lon, lat, h = (float(x) for x in _TF_GEODETIC.transform(*t))
    E, N, _z = (float(x) for x in _TF_4544.transform(*t))
    return {"ecef": [float(x) for x in t], "lat": lat, "lon": lon, "h": h,
            "E4544": E, "N4544": N, "R_enu2ecef": rot_enu2ecef(lat, lon)}


def find_content_node(node: dict, uri_sub: str, chain=None):
    """根→内容叶的节点链。返回 (chain, node)；chain 含各层 transform（可能为 None）。"""
    chain = (chain or []) + [node.get("transform")]
    u = (node.get("content") or {}).get("uri")
    if u and uri_sub in u:
        return chain, node
    for ch in node.get("children") or []:
        r = find_content_node(ch, uri_sub, chain)
        if r:
            return r
    return None


def block_to_ecef(ts: dict, block: str) -> np.ndarray:
    """块的 `内容叶局部 → ECEF` 4x4。

    ★ 链上任一层带非单位 transform 都由本函数乘进去 —— 今天实测各块**中间层没有** transform，
      但「今天没有」不是「永远没有」（源件是被人手工改过的件）⇒ 写成通用的，不省这一步。
    """
    hit = find_content_node(ts["root"], block + ".glb")
    if not hit:
        raise KeyError("tileset 里找不到块的 content：%s" % block)
    chain, _node = hit
    M = m4(ts["root"]["transform"])
    for c in chain[1:]:
        if c is not None:
            M = M @ m4(c)
    return M


def block_enu_of_glb(ts: dict, block: str, glb_path: str):
    """读块的 glb，返回 **(瓦片 ENU 坐标, 4x4 局部→ECEF)**。调用方自己决定要不要聚合。"""
    import trimesh
    sc = trimesh.load(glb_path, force="scene")
    lv = np.vstack([np.asarray(g.vertices, dtype=float) for g in sc.geometry.values()])
    return gltf_yup_to_enu(lv), block_to_ecef(ts, block)


def enu_to_4544(enu, M_ecef: np.ndarray):
    """ENU 坐标 → (E, N, 椭球高 h)。★ 走 ECEF，与 tileset 自己的链一致。

    ★ 4544 的 `transform()` **返回 3 个值**（东 / 北 / 高程），不是 2 个 —— 解包必须收 3 个。
    """
    enu = np.asarray(enu, dtype=float)
    P = (M_ecef @ np.c_[enu, np.ones(len(enu))].T).T[:, :3]
    lon, lat, h = _TF_GEODETIC.transform(P[:, 0], P[:, 1], P[:, 2])
    E, N, _z = _TF_4544.transform(P[:, 0], P[:, 1], P[:, 2])
    return np.asarray(E), np.asarray(N), np.asarray(h)


def enu_to_4544_grid(enu, anc: dict):
    """**候选 B（已定案，2026-10-15）**：ENU 偏移量**直接加**到锚点的 4544 坐标上。

        E = E4544_锚 + e_enu ／ N = N4544_锚 + n_enu ／ h = h_锚 + u_enu

    物理含义：**内容是「被切进 4544 平面网格」的，没有做子午线收敛角 γ 的转动**；
    而 A（`enu_to_4544`）等价于**把 B 的坐标绕锚点转 −γ**（`θ\\* = +0.44° ≈ |γ| = 0.446°`
    的实测，见本件 docstring「落位定案」段）。

    ★ 为什么不做「投影」：B 根本不需要 ECEF —— 它只要锚点的一个 4544 读数（`anchor()` 反解）。
      **越少的中间量 ⇒ 越少的可错处**；而 A 要先经 ECEF 再投影，链长一倍。
    ★ 盲区（如实说）：
      ① 锚点附近 A 与 B **同解**（|θ|·|offset| → 0）⇒ **拿锚点附近的点做对照，两法永远分不开**；
         要分辨必须用**长基线**（1.4 km 才 11 m）。
      ② 本式是**线性平移**，对「距锚 1.4 km」的尺度成立；**拉到全校区 2.4 km 级**时
         γ 折成 18.7 m，仍按本式处理，**但没有实测覆盖到那个尺度**（探针样点跨度见探针 ①）。
      ③ 高程 u_enu 是**椭球高**方向的分量，不是 4544 的 `_z` —— 两者在锚点处同为 422.000，
         但**没有沿基线逐点核对过**。
    """
    enu = np.asarray(enu, dtype=float)
    E = anc["E4544"] + enu[:, 0]
    N = anc["N4544"] + enu[:, 1]
    h = float(anc["h"]) + enu[:, 2]
    return np.asarray(E), np.asarray(N), np.asarray(h)


def glb_to_4544_grid(v, anc: dict):
    """**glb 帧顶点 → (E, N, h)**，全程走 B。＝ `gltf_yup_to_enu` ∘ `enu_to_4544_grid`。

    ★ 单独出来是为了让调用方**不许自己拼**这两步（拼错了是铁律 183 的现场：一处改了、兄弟没改，
      两个量摆在同一个 JSON 里而不报错）。**凡把主件几何落到 4544 的件，一律调本函数。**
    """
    return enu_to_4544_grid(gltf_yup_to_enu(np.asarray(v, dtype=float)), anc)


def sample_dsm(path: str, E, N):
    """在 DSM 上按 (E, N) 取高程。**无量到的点返回 nan**（不返 0、不返 nodata 原值）。

    ★ 落在影像外、或落在 nodata 上的点一律 nan —— 「没量到」不许与「量到 0」同形（铁律 199）。
    """
    import rasterio
    E = np.asarray(E, dtype=float)
    N = np.asarray(N, dtype=float)
    out = np.full(E.shape, np.nan, dtype=float)
    with rasterio.open(path) as ds:
        nod = float(ds.nodata) if ds.nodata is not None else -9999.0
        r, c = rasterio.transform.rowcol(ds.transform, E, N)
        r = np.asarray(r)
        c = np.asarray(c)
        ok = (r >= 0) & (r < ds.height) & (c >= 0) & (c < ds.width)
        if ok.any():
            r0, c0 = int(r[ok].min()), int(c[ok].min())
            h = int(r[ok].max() - r0 + 1)
            w = int(c[ok].max() - c0 + 1)
            a = ds.read(1, window=rasterio.windows.Window(c0, r0, w, h)).astype(float)
            v = a[r[ok] - r0, c[ok] - c0]
            out[ok] = np.where(v <= nod + 1.0, np.nan, v)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# ★★★ 模型（CAD / 白模）一侧的落位 —— 步 5 ②「近景白模叠远景实景」的同帧前提
#
# ★ 为什么放在**本件**而不是新起一件：本件已经是「落位」这件事的唯一来源
#   （docstring 开头那句「三处都要用它，抄三份就是三份会各自漂的副本」）。
#   模型落位与实景落位必须**同帧**才谈得上叠加 ⇒ 两者放在一起才守得住这条。
#
# ★★ 与实景落位（B）的关系：**不是同一个变换，来源也不同**。
#   · 实景侧的落位来自**瓦片自己的 tileset**（`root.transform` ⇒ 锚点），
#     **不与 DSM 配准**；读数由 `RP.anchor()` 现解。
#   · 模型侧的落位来自 **`rebuild/_work/regbest_1层.json`** ——
#     它是 `reg_search.py` 把**模型 1 层轮廓**拿去和 **2024 DOM 真值轮廓**做
#     180° 转角 × 全平移 穷举搜出来的（`J-10.8-01`：IoU 0.7487、边界中位 2.06 m）。
#     **参照物是 DOM ⇒ 对外，不是自证**。
#   ⇒ 两侧各自独立落到 4544 上；叠起来对不对，是**两个来源比对**，不是同义反复。
#
# ★★★ 竖向（h）**不在 2D 配准里**，本件**不猜**：2D 配准只定平面四自由度，
#   模型 `y`（＝相对 ±0.000 的高度，米）要变成椭球高还得**再加一个锚** `h0`。
#   本件**只提供两个候选锚的读数**，由调用方（`tools/place_white_model.py` / 判据）显式选，
#   并把两个锚的差印出来。原因：这两个锚给出的答案**差 3.60 m**，而
#   **「层高其实是 4.0 m」与「模型 ±0.000 不在实测地面上」给出同一个读数**（铁律 018）——
#   那不是本件能裁的，`gates/J-10.10-08` 已把这条单列为**必须由用户裁**。
# ══════════════════════════════════════════════════════════════════════════════

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_FP = os.path.join(REPO, "rebuild", "_work", "model_footprint_c006.json")
REGBEST = os.path.join(REPO, "rebuild", "_work", "regbest_1层.json")
WHITE_GLB = os.path.join(REPO, "rebuild", "05_build", "c006_white.glb")
J101008 = os.path.join(REPO, "gates", "_out", "J-10.10-08.json")
_PLACEMENT_TOL_M = 1e-6            # 与 J-10.10-08 同一口径：复算 max 差的上限


def model_placement(key: str = "1层") -> dict:
    """**模型一侧的 2D 落位**：读 `regbest_1层.json` + `model_footprint_c006.json`，
    复算 `outline_en` 并**当场逐位核对**。算不过就抛 `ValueError`，**不返回半个答案**。

        (E, N) = R(θ) · (P − P̄) + tr_en        P ＝ `outline_mm` / 1000（米）
        h      = h0 + y                        h0 由调用方给（见本节抬头 ★★★）

    ★ `θ` **只从盘上读**（`theta_deg`），**不手打 110**；`tr_en` **不读存好的数**，
      而是用「P 已按自身质心居中 ⇒ 整体平移就等于目标质心」这条恒等式**现算**
      （`P̄` 居中后恒为 0 ⇒ 无需反解线性系统）。两条都落盘可核。
    ★ 自证：复算出的 `outline_en` 与盘上那份的最大逐点差必须 ≤ 1e-6 m。
      这是**同一件事的两条路**（存下来的轮廓 vs 现算的刚体变换），不是自说自话。
    """
    with open(REGBEST, encoding="utf-8") as f:
        R = json.load(f)
    with open(MODEL_FP, encoding="utf-8") as f:
        MF = json.load(f)[key]
    P = np.asarray(MF["outline_mm"], dtype=float) / 1000.0     # 米；(x, −z) 平面
    oe = np.asarray(R["outline_en"], dtype=float)
    if P.shape != oe.shape:
        raise ValueError("outline_mm 与 outline_en 点数不一致：%s vs %s" % (P.shape, oe.shape))
    th = math.radians(float(R["theta_deg"]))
    Rm = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    ctr = P.mean(0)
    tr = oe.mean(0)                                            # ＝ reg_search 的模板平移
    err = float(np.abs((P - ctr) @ Rm.T + tr - oe).max())
    if not (err <= _PLACEMENT_TOL_M):
        raise ValueError("模型落位复算不上：theta=%.4f° 复算 outline_en 最大差 %.3e m > %.0e "
                         "⇒ regbest 与 model_footprint 不是同一对（拒绝出数）"
                         % (R["theta_deg"], err, _PLACEMENT_TOL_M))
    return {"key": key, "theta_deg": float(R["theta_deg"]), "yflip": R.get("yflip"),
            "R": Rm, "plan_ctr_m": ctr, "tr_en": tr, "outline_en": oe,
            "best_iou": float(R["best_iou"]),
            "boundary_median_m": float(R["boundary_median_m"]),
            "boundary_p90_m": float(R["boundary_p90_m"]),
            "selfcheck_max_err_m": err,
            "src": {"regbest": os.path.relpath(REGBEST, REPO).replace("\\", "/"),
                    "model_footprint": os.path.relpath(MODEL_FP, REPO).replace("\\", "/")}}


def model_glb_to_en(v, mp: dict):
    """**白模 glb 顶点 → (E, N, y)**。`y` 仍是**相对 ±0.000** 的米，**不是椭球高**。

    ★ 模型的 glb 与瓦片的 glb **同为 `gltfUpAxis:Y`**（实测：模型 bbox 的 y 跨 **−3.5…47.0 m**
      ＝ 4.0 m 口径，2026-10-16 用户裁定「按甲定案 · 重算整条链」后重跑读数；
      与 `catalog` 的「地下1层 z0=−3500 / 1层 z0=0」逐位对上）⇒ 平面轴是 `(x, z)`，
      而 `model_footprint` 的轮廓用的是 `(x, −z)`（实测：`outline_mm[:,1]` 跨 15.155…98.855，
      而 glb 的 z 跨 −99…−15 ⇒ 二者互为相反数）。
    ⇒ **`(x, y, z) → 平面 (x, −z)`，高度取 `y`**。这一步**不许调用方自己拼**
      （拼错就是铁律 183 的现场：一处改了、兄弟没改，两个量躺在同一个 JSON 里还不报错）。
    """
    v = np.asarray(v, dtype=float)
    plan = np.c_[v[:, 0], -v[:, 2]]
    en = (plan - mp["plan_ctr_m"]) @ mp["R"].T + mp["tr_en"]
    return en[:, 0], en[:, 1], v[:, 1].copy()


def vertical_anchors() -> dict:
    """**竖向锚的两个候选读数**，全部从 `gates/_out/J-10.10-08.json` 现读，**不手打**。

        h0_地面 : 模型 ±0.000 落在**实景地面估计值**上        ＝ `ground_median_m`
        h0_裙房顶: 模型 ±0.000 落在**让裙房顶对齐**的那个高度上
                  ＝ h0_地面 + (③ 的实测读数 − ③ 的声明)

    ★ 两个锚的差**恒等于** `J-10.10-08` 里 ③ 的偏差（本函数**断言**这条恒等式）——
      它是同一件事的两个说法，不是两个独立证据（铁律 018）。
    ★ 本函数**不挑**。挑哪一个是**用户的裁决**（见 `J-10.10-08` 的判词与盲区）。
    """
    with open(J101008, encoding="utf-8") as f:
        J = json.load(f)
    it = [x for x in J["items"] if x.get("no") == "③"]
    if not it:
        raise ValueError("J-10.10-08.json 里找不到 ③（台阶屋面高）⇒ 竖向锚无来源，拒绝出数")
    it = it[0]
    if it.get("read") is None or it.get("decl") is None:
        raise ValueError("J-10.10-08.json 的 ③ 读数/声明为空 ⇒ 竖向锚无来源，拒绝出数")
    g = float(J["ground_median_m"])
    delta = float(it["read"]) - float(it["decl"])
    return {"h0_ground_m": g, "h0_roof_m": g + delta,
            "delta_m": delta, "ground_spread_m": float(J.get("ground_spread_m") or 0.0),
            "item3": {"no": it["no"], "read": float(it["read"]), "decl": float(it["decl"]),
                      "tol": float(it["tol"]), "verdict": it.get("verdict")},
            "src": os.path.relpath(J101008, REPO).replace("\\", "/")}


if __name__ == "__main__":
    # ★ 自带对照：B 与 A 的差向量，必须等于「把 A 的坐标绕锚点转 +θ」的解析值。
    #   伪证器（廉价版）：把 θ 当自由量去拟合该差向量 —— 若拟合出的 θ 与探针 ④ 的 +0.44° 不符，
    #   说明两法之间的差**不是**一个纯转动，那么 docstring 里「θ* 与 B 是同一件事」这句就作废。
    import math
    _ts = load_tileset()
    _anc = anchor(_ts)
    _o = np.array([[0.0, 0.0, 0.0], [1000.0, 1000.0, 0.0], [0.0, 2000.0, 0.0]])
    _M = m4(_ts["root"]["transform"])
    _aE, _aN, _ah = enu_to_4544(_o, _M)
    _bE, _bN, _bh = enu_to_4544_grid(_o, _anc)
    print("锚点 E4544=%.3f N4544=%.3f h=%.3f" % (_anc["E4544"], _anc["N4544"], _anc["h"]))
    for i, (e, n) in enumerate(_o[:, :2]):
        dE, dN = float(_bE[i] - _aE[i]), float(_bN[i] - _aN[i])
        # 解析：把 A 的点绕锚点转 +θ ⇒ (ΔE, ΔN) = (c·e − s·n − e, s·e + c·n − n)
        th = math.atan2(-dE, n) if n else 0.0
        pred = (-th * n, th * e)
        print("  ENU(%6.0f,%6.0f)  A→B 实测 (%+.3f, %+.3f)  解析(θ=%+.4f°) (%+.3f, %+.3f)"
              % (e, n, dE, dN, math.degrees(th), pred[0], pred[1]))
    print("  |h_B − h_A| 最大 %.6f m（高程不经转动，应当极小）" % float(np.max(np.abs(_bh - _ah))))
