# -*- coding: utf-8 -*-
r"""J-10.10-08 顶部三个「推的数」对照 2024 实景 —— 步 5 ①（与 CAD 链融合）

【判据】`rebuild/构件库/参数.json` 里三个标着**假设**的顶部数，拿 **2024 航测 DSM**
  （`fly2024_dsm_025.tif`，0.25 m/px，EPSG:4544，**与交付件不同源**）在**同一栋楼内**量一遍：
    ① **女儿墙高**   声明 **1.2 m**（`构件/顶部/女儿墙高`）
    ② **楼梯房高**   声明 **3.0 m**（`构件/顶部/楼梯房高`）
    ③ **台阶屋面高** 声明 **相对模型 ±0.000 的 24.5 m**（＝ 7 层板顶，**由 `c006_catalog.json` 表现算**）
  ★ ③ 的口径已改过一次（铁律 28，代价写在旁边）：原口径是「相对**塔楼顶** −14.0 m」，
    而塔楼顶在本闸里**量不出来**（见下）⇒ ③ 改量**裙房屋面 − 地面**，与声明量同义、且**不依赖塔楼顶**。
    ★ 它的差**分不开**两件事：「层高其实是 4.0」与「模型 ±0.000 不在实测地面上」（**同一读数**）——
      **必须由用户裁**，本闸不自行改口径（写进盲区）。

  **位姿**：整栋**一个**位姿，只用 `_work/regbest_1层.json`（转角 110°、不拟合比例尺、质心对质心）。
   ★ 开闸第一件事是**复算** `outline_en` 并与盘上存的那份逐位比（< 1e-6 m）——
     位姿要是读错了，本闸当场 rc=4，不许拿错的位姿去量（否则读数全对不上却看着像「模型错了」）。

  **判定规则**（每条落读数，不只落 bool）：
    容差 `tol_m = 参考面自己的 p90 − p10`（**栅格上实测的离散**，不手打，铁律 103）；
    ③ 再加**地面估计器之间的跨度**（三个估计器取中位，分歧也算进容差）。
    · 区域栅格化成空 ⇒ `未量到`（不是「相符」）
    · **② 的基准面不够格**（候选面跨度 > `ROOF_LEVEL_TOL`）⇒ `未量到`，**不挑一块报出来**
    · **构件厚度 < 一个格（0.25 m）** ⇒ 尺子**结构上看不见**它 ⇒ **未决**（女儿墙厚 0.2 m 正属此类）
    · `|读 − 声明| ≤ tol` ⇒ **相符**；否则 ⇒ **不符**

【量具】`rasterio` 读 DSM 窗口（±140 m）；`PIL.ImageDraw` 把 `rebuild/06_su/c006_catalog.json`
  里每个构件的 `ring`（模型平面 mm）按位姿搬进像素格；`scipy.ndimage` 腐蚀出「内部」与
  「外圈带」；读数 = **区域里最大那块「平地连通块」** 的 DSM 中位之差。
  ★ 一处改了三轮才定下来的口径：**读数取连通块、不取整个区域的中位** ——
    一个 ROOF 环里**同时**躺着屋面板、楼梯房、屋顶设备、以及配准误差带进来的邻面；
    它们的**中位**会被拽走、离散会变成「区域里所有东西的高度跨度」（实测 p10~p90 = **54 m**
    ⇒ 容差大到把 +0.9 m 与 −5.4 m 都判「相符」）。**一块面只有一个高度**，连通性才是它的定义。
  区域**全部取自交付件自己的表**，不手打坐标。

【量具盲区】本闸对下面这几类**一个字都不给结论**：
  · **DSM ＝ 最高面**：树冠/旗杆/女儿墙顶上多出来的东西都算进去 ⇒ 读数**偏正**；本闸不做树/屋分类。
  · ★★ **② 塔楼顶结构上量不了**：塔楼环的掩膜里同时躺着屋面板 / 楼梯房 / 屋顶设备 /
    配准误差带进来的邻面（实测四档 465.6 / 485.8 / 512.0 / 519.6 m，跨度 54 m）
    ⇒ **「取最大那块」只是运气**（换个阈值或挪 5 m，答案从 +3.9 跳到 −33.9 m）。
    本闸因此**拒绝出 ② 的数**，而不是挑一块报出来（正对照·丁 证明这份「不稳定」是可复现的）。
  · ★★ **③ 的差本闸分不开三件事**（**同一个读数**，铁律 018：「两个数对上不能证明它们对」）：
    「层高其实是 4.0 m」/「模型 ±0.000 不在实测地面上」/「**裙房层数少了 1 层**」。
    ★ 只有第三条与既有命令「**层高定 3.5 m**」相容（实测 28.103 ÷ 3.5 = **8.03 层** ⇒ 裙房应为 **8 层**，
      交付件现在是 7 层）⇒ 但**口径是用户的**，本闸**不自行改**，只把三条并列摆出来。
  · **「平地」阈值 `FLAT_TOL_M = 1.0 m` 与 `_scratch/dsm_roofs_c006.py:91` 同口径**
    （★ 该脚本 `:83` 的 `rng3 < 0.40` 是**铺装**判据，不是平屋面判据 —— 早前照抄错过一次，
    代价：塔楼板被切成 14.1 / 9.9 m² 两块、都掉到 `LEVEL_MIN_AREA` 以下，候选面全变杂物）。
    ⇒ 口径已对齐，**但两把尺子的窗口/掩膜仍不同，绝对值不可比**。
  · **0.25 m 格 vs 0.20 m 女儿墙厚**：①**结构性亚格**。只有 DSM 生产真的「取最高面」才看得见那条边；
    看不见时本闸报 **未决**，**不报「没有女儿墙」**。
  · **位姿只有一条，且它自己有平面误差**：`boundary_median_m 2.06` / `p90 6.98`（同一份 `regbest` 里）
    ⇒ 掩膜会跨到地面/邻栋。本闸因此只把**大面**（裙房 1970 m²）的读数当判据 ——
    它对侧向误差不敏感；窄构件的读数会把**平面偏差放大成高度偏差**。
  · **地面基准**：`_work/zcheck.py` 写 466.60、`_scratch/dsm_roofs_c006.py` 实测 464.66（差 1.94 m）。
    本闸**不裁谁对**，只把三个估计器取中位、把跨度算进 ③ 的容差。
  · ★ **「全窗平地按高程分层」表是普查表、不是判据**：只收 ≥150 px（＝9.4 m²）的连通块、
    高程按 0.5 m 一档归并 ⇒ **小块面看不见**、**同档两块面会被并成一行**。它回答的是
    「这栋楼在影像上有哪几层水平面、各在哪儿」，**不回答**「模型这一环对不对」。
  · ★ **环平移搜索（±20 m / 步 5 m）只做诊断、不参与判定**：它分的是
    「**环圈错地方**」与「**这栋楼真的不止一块面**」这两件在**每一个读数上都同形**的事（铁律 183）。
    它的结论**不回写位姿** —— 位姿来自 1 层轮廓的独立拟合（`regbest_1层.json`），
    拿塔楼顶去调位姿就是拿被测物去校尺子（铁律 192）。
  · **不判厚度、不判位置、不判纹理**；不判女儿墙**顶上有没有压顶/栏杆**。
  · 参照链只用了 **DSM 栅格链**（0.25 m），**没有**用 `campus2024.glb` 实景网格链 ⇒
    两条链之间的差别本闸看不见。
  · ★ **本闸量的是「影像上那个台阶有多高」，不是「该不该是那么高」**——合规性是另一件事。

【正对照】（每条落**读数**不只落 bool）★ 计划文件里逐字写的「**把模型整体平移 1 m ⇒ 偏差读数必须跟着变**」
  —— **实测作废，已换掉**：本尺子量的是 44 m 宽的区域的中位差，**1 m 平移只动 2% 的样本**，
  读数本来就不该变；拿它当伪证器是**给尺子测它量不出的东西**（铁律 28：决定完把代价写在旁边）。
  换成与量具分辨力相称的四条：
  甲 **裙房掩膜平移 5 m** ⇒ ③ 必须**基本不动**（≤ tol3）—— 1970 m² 的大面，答案不靠运气。
     ★ 旧版甲是「平移后 ② 必须变」；② 现在**已拒绝出数** ⇒ 那条对照没有靶子了，
     按铁律 28 换掉，代价（「窄构件对平移敏感」这一面）**改由丁承担**。
  乙 **把「台阶屋面」区整体搬出楼外** ⇒ ③ 必须变得 ≥5 m ——
     证明这个数是从**这块地**上量出来的，不是常数。偏移量先按固定表试，取第一个与真值轮廓重叠 <5% 的。
  丙 **同一掩膜自减** ⇒ 必须**恰好 0.0** —— 证明这条尺子不会凭空造出差。
  丁 **塔楼掩膜平移 5 m** ⇒ 掩膜里**仍**躺着不止一块面（跨度仍 > `ROOF_LEVEL_TOL`）——
     ★ 把「不稳定」本身变成一条**通过**的对照：没有它，② 的「未量到」与「尺子抽风」永远同形（铁律 183）。

三态：`RC_PASS=0 / RC_FAIL=1 / RC_NOGAUGE=4`。
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from scipy import ndimage  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
PARAMS = os.path.join(REPO, "rebuild", "构件库", "参数.json")
CATALOG = os.path.join(REPO, "rebuild", "06_su", "c006_catalog.json")
MODEL_FP = os.path.join(REPO, "rebuild", "_work", "model_footprint_c006.json")
REGBEST = os.path.join(REPO, "rebuild", "_work", "regbest_1层.json")
# ★ 跨仓引用（gym3d 仓）：只读、不搬（计划 §2 纪律）
DSM = r"D:\项目\gym3d\gym3d\_scratch\c011_fly\_store\fly2024_dsm_025.tif"
HALF_M = 140.0            # 采样窗半宽（楼 129×83.7 m ⇒ 必须罩得住）
ERODE_ROOF_M = 1.5        # 「屋面内部」离边多远（避开女儿墙带）
FLAT_TOL_M = 1.0          # 「平地」判据：3 m 邻域极差 < 此值。
# ★ 出处是**行号**，不是文件名：`_scratch/dsm_roofs_c006.py:91` 写的是 `rng3 < 1.0`（平屋面），
#   同文件 `:83` 那个 `0.40` 是**铺装**判据（还叠了「低于 30 分位」）。本闸原来抄的是 0.40、
#   注释却写「沿用 dsm_roofs_c006.py」⇒ **引对了文件、抄错了行**，实测后果：塔楼那块
#   干净大面被切碎成 14.1 / 9.9 m² 两块（都掉到 LEVEL_MIN_AREA 以下），基准面候选全变杂物。
#   ⇒ 两个同名判据（平屋面 / 铺装）**死了 0.40 那个**（铁律 018/174）。
ERODE_STAIR_M = 0.5
ERODE_STEP_M = 4.0
STEPS_UNION_M = 1.0       # 从台阶屋面上扣掉的「塔楼足迹外扩」
LEVEL_MIN_AREA = 20.0     # 「候选面」最小面积 m²（≠ `parts` 的 20 px 门限：那是 1.25 m²，两个数不是一回事）
ROOF_LEVEL_TOL = 2.0      # 塔楼顶「算一块面」的高度跨度上限 m —— 超过 ⇒ **拒绝出数**，不挑一块
OFFSET_SEARCH_M = 20      # 环平移搜索半径 m（只诊断「环圈错地方 vs 楼不止一块面」，不参与判定）
OFFSET_STEP_M = 5         # 搜索步长 m

GID = "J-10.10-08"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

_LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def _write_json(rc, **kv):
    d = {"pass": rc == 0, "rc": rc}
    d.update(kv)
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, GID + ".json")
    with open(p, "wb") as f:                        # 字节层写盘（铁律 79）
        f.write(json.dumps(d, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8"))
    log("  写出:", p)


def _finish(rc, **kv):
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    _write_json(rc, **kv)
    return rc


# ------------------------------------------------------------------ 位姿（唯一：regbest_1层.json）

def load_placement():
    """读位姿，**并当场复算 `outline_en` 逐位核对**。返回 (to_en, info) 或 (None, 原因)。"""
    with open(REGBEST, encoding="utf-8") as f:
        R = json.load(f)
    with open(MODEL_FP, encoding="utf-8") as f:
        MF = json.load(f)["1层"]
    P = np.asarray(MF["outline_mm"], float) / 1000.0          # 模型 1 层轮廓，米
    oe = np.asarray(R["outline_en"], float)                   # 盘上存的落位后轮廓
    if P.shape != oe.shape:
        return None, "outline_mm 与 outline_en 点数不一致：%s vs %s" % (P.shape, oe.shape)
    t = math.radians(float(R["theta_deg"]))
    Rm = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    c1 = P.mean(0)
    tr = oe.mean(0)
    got = (P - c1) @ Rm.T + tr
    err = float(np.abs(got - oe).max())
    if err > 1e-6:
        return None, ("位姿复算不上：用 theta=%.4f° + 质心对质心 复算 outline_en，最大差 %.3e m "
                      "（> 1e-6）⇒ regbest 与 model_footprint 不是同一对" % (R["theta_deg"], err))

    def to_en(xy_mm_arr, dx=0.0, dy=0.0):
        q = np.asarray(xy_mm_arr, float) / 1000.0
        return (q - c1) @ Rm.T + tr + np.array([dx, dy])

    info = dict(theta_deg=float(R["theta_deg"]), yflip=R.get("yflip"),
                best_iou=R.get("best_iou"), boundary_median_m=R.get("boundary_median_m"),
                boundary_p90_m=R.get("boundary_p90_m"),
                selfcheck_max_err_m=err,
                tr_en=[float(tr[0]), float(tr[1])],
                model_ctr_m_from_mm_origin=[float(c1[0]), float(c1[1])],
                outline_en=oe.tolist(),
                src=os.path.relpath(REGBEST, REPO).replace("\\", "/"))
    return to_en, info


# ------------------------------------------------------------------ 交付侧：声明值（全部现读）

def load_decls():
    with open(PARAMS, encoding="utf-8") as f:
        o = json.load(f)["构件"]

    def g(path):
        d = o
        for k in path:
            d = d[k]
        return float(d["值"]), d["标注"]

    par_h, par_h_mark = g(["顶部", "女儿墙高"])
    par_t, par_t_mark = g(["顶部", "女儿墙厚"])
    st_h, st_h_mark = g(["顶部", "楼梯房高"])
    storey, storey_mark = g(["共用", "层高"])
    return dict(parapet_h_mm=par_h, parapet_h_mark=par_h_mark,
                parapet_t_mm=par_t, parapet_t_mark=par_t_mark,
                roof_stair_h_mm=st_h, roof_stair_h_mark=st_h_mark,
                storey_mm=storey, storey_mark=storey_mark)


def load_regions(to_en):
    """从交付件自己的 `c006_catalog.json` 取构件的 `ring`（模型平面 mm）。★ 不手打任何坐标。"""
    with open(CATALOG, encoding="utf-8") as f:
        C = json.load(f)
    with open(MODEL_FP, encoding="utf-8") as f:
        MF = json.load(f)

    def blocks(floor, layer):
        for fl in C["floors"]:
            if fl["name"] == floor:
                return [b for b in fl["blocks"] if b["layer"] == layer], fl
        return [], None

    roof, f11 = blocks("11层", "ROOF")
    stair, _ = blocks("11层", "ROOF_STAIR")
    par, _ = blocks("11层", "PARAPET")
    step, f07 = blocks("7层", "ROOF_STEP")

    def ztop(bs, fl):
        """块顶绝对标高（mm，模型帧）＝ 层 z0 + 块 z + 块 h。逐块现算。"""
        return sorted({float(fl["z0_mm"]) + float(b["z"]) + float(b["h"]) for b in bs})

    d = dict(
        n_roof=len(roof), n_parapet=len(par), n_roof_stair=len(stair), n_roof_step=len(step),
        z_roof_top_mm=ztop(roof, f11), z_parapet_top_mm=ztop(par, f11),
        z_roof_stair_top_mm=ztop(stair, f11), z_roof_step_top_mm=ztop(step, f07),
        push_parapet_mm=sorted({float(b["h"]) for b in par}),
        push_roof_stair_mm=sorted({float(b["h"]) for b in stair}),
        rings=dict(roof=[b["ring"] for b in roof], stair=[b["ring"] for b in stair],
                   step=[b["ring"] for b in step]),
        outline8_mm=MF["8层"]["outline_mm"],
        outline1_mm=MF["1层"]["outline_mm"],
        # 构件bbox短边（用来判「亚格」）——现算，不手打
        stair_min_side_m=min(min(float(b["bbox"][2] - b["bbox"][0]),
                                 float(b["bbox"][3] - b["bbox"][1])) for b in stair) / 1000.0,
        step_min_side_m=min(min(float(b["bbox"][2] - b["bbox"][0]),
                                float(b["bbox"][3] - b["bbox"][1])) for b in step) / 1000.0,
    )
    return d


# ------------------------------------------------------------------ DSM 采样

class Dsm:
    def __init__(self, to_en, ctr):
        self.to_en = to_en
        # ★ 窗口中心**必须**是落位后的质心（＝ `outline_en` 的质心），
        #   **不是** `to_en((0,0))` —— 后者是「模型原点落位后在哪」，离质心 |c1| ≈ 100 m。
        #   取错时**不报错、只出错数**（症状与「模型错了」同形，铁律 183）⇒ 下面还有一道自检挡住。
        self.ctr = (float(ctr[0]), float(ctr[1]))
        with rasterio.open(DSM) as ds:
            self.mpp = abs(float(ds.transform.a))
            nod = float(ds.nodata) if ds.nodata is not None else -9999.0
            E, N = self.ctr
            self.E_LO, self.E_HI = E - HALF_M, E + HALF_M
            self.N_LO, self.N_HI = N - HALF_M, N + HALF_M
            win = from_bounds(self.E_LO, self.N_LO, self.E_HI, self.N_HI, ds.transform)
            a = ds.read(1, window=win, boundless=True, fill_value=nod).astype(float)
            self.crs = str(ds.crs)
            self.src_transform = ds.transform
        self.arr = np.where(a <= nod + 1.0, np.nan, a)
        self.shape = self.arr.shape
        # 窗口中心在栅格里的 (row, col) —— 只用于把连通块块心换算成「离质心多远」，
        # 好让「量到的那块面是不是我要量的那块」肉眼可查（配准误差 2 m 量级，块心必须落在 0 附近）。
        self.ctr_px = ((self.shape[0] - 1) / 2.0, (self.shape[1] - 1) / 2.0)
        g = np.isfinite(self.arr)
        self.good = g
        self.n_valid_frac = float(g.mean())
        # 3 m 邻域极差（判「平地」用；口径沿用 `_scratch/dsm_roofs_c006.py`）
        # ★ 必须先填掉 NaN：`maximum_filter` 遇 NaN 会把整个邻域染成 NaN
        #   （0.8% 的洞 ⇒ 12×12 窗有 68% 概率含 NaN ⇒ 大半栅格读不出极差）。
        _f = np.where(g, self.arr, float(np.nanmedian(self.arr)))
        self.rng3 = (ndimage.maximum_filter(_f, 12, mode="nearest")
                     - ndimage.minimum_filter(_f, 12, mode="nearest"))
        # ★★ 「屋面」掩膜里混着楼梯房与屋顶杂物 ⇒ 它**不是一块平面**，直接取中位得到的
        #   离散度是「屋顶上所有东西的高度跨度」而不是噪声底（实测 p10~p90 = 54 m，
        #   用它会得到一个把一切都判「相符」的哑巴容差）。⇒ 基准面**只取平地**。
        self.flat = g & (self.rng3 < FLAT_TOL_M)
        self.n_flat_frac = float(self.flat.mean())

    def px(self, ring_mm, dx=0.0, dy=0.0):
        en = self.to_en(np.asarray(ring_mm, float).reshape(-1, 2), dx, dy)
        col = (en[:, 0] - self.E_LO) / self.mpp
        row = (self.N_HI - en[:, 1]) / self.mpp
        return list(zip(col.tolist(), row.tolist()))

    def mask(self, rings, dx=0.0, dy=0.0):
        im = Image.new("L", (self.shape[1], self.shape[0]), 0)
        dr = ImageDraw.Draw(im)
        for r in rings:
            dr.polygon(self.px(r, dx, dy), fill=1)
        return np.asarray(im, bool)

    def med(self, m):
        """区域中位（DSM 值）。★ 空或有效点太少 ⇒ None（＝「未量到」，不许当成 0）。"""
        v = self.arr[m & self.good]
        if v.size < 20:
            return None, int(v.size)
        return float(np.median(v)), int(v.size)


def erode(m, meters, mpp):
    k = int(round(meters / mpp))
    if k <= 0:
        return m.copy()
    return ndimage.binary_erosion(m, structure=np.ones((3, 3), bool), iterations=k, border_value=0)


def band(m, outer_m, mpp):
    """`m` 的外圈带（离边 ≤ outer_m）。k 至少 1 ⇒ 至少一圈。"""
    k = max(1, int(round(outer_m / mpp)))
    return m & ~ndimage.binary_erosion(m, structure=np.ones((3, 3), bool),
                                       iterations=k, border_value=0)


def overlay_png(dsm, R, pinfo, out_path):
    """把**模型自己的环**画在 DSM 上，出一张图。

    ★ 为什么非要有这张图：直方图能告诉你「这块地上躺着几层」，**但告诉不了你
      「模型的那个环画到哪儿去了」**。而「环圈错地方」与「这栋楼真的不止一块面」
      在读数上**完全同形**（铁律 183）—— 表格和 ASCII 图都分不出，只有叠图能分。
    """
    a = dsm.arr
    lo, hi = np.nanpercentile(a[dsm.good], [2, 98])
    g = np.where(dsm.good, np.clip((a - lo) / max(1e-6, hi - lo), 0, 1), 0.0)
    rgb = np.zeros((dsm.shape[0], dsm.shape[1], 3), np.uint8)
    rgb[..., 0] = (255 * np.clip(g * 1.1, 0, 1)).astype(np.uint8)
    rgb[..., 1] = (255 * np.clip(g * 1.5 - 0.25, 0, 1)).astype(np.uint8)
    rgb[..., 2] = (200 * (1 - g)).astype(np.uint8)
    rgb[~dsm.good] = (0, 0, 0)
    rgb = (rgb * 0.45).astype(np.uint8)          # ★ 底图压暗：线要能一眼看见，不靠盯
    im = Image.fromarray(rgb)
    dr = ImageDraw.Draw(im)
    # ★ 真值轮廓是 **EN 米**，模型环是 **模型 mm** —— 两套单位，两条转换路径。
    #   混用一次，画出来的线就整体转 110°、平移 100 m，而**图上照旧有线**（铁律 183）。
    def en_px(en):
        en = np.asarray(en, float).reshape(-1, 2)
        return list(zip(((en[:, 0] - dsm.E_LO) / dsm.mpp).tolist(),
                        ((dsm.N_HI - en[:, 1]) / dsm.mpp).tolist()))

    def ring(pts, col, w):
        dr.line(list(pts) + list(pts)[:1], fill=col, width=w)

    ring(en_px(pinfo["outline_en"]), (255, 255, 255), 3)     # 真值 2024
    ring(dsm.px(R["outline1_mm"]), (0, 128, 255), 3)         # 模型 1 层
    for rg in R["rings"]["roof"]:
        ring(dsm.px(rg), (255, 0, 0), 2)                      # 11 层 ROOF
    for rg in R["rings"]["stair"]:
        ring(dsm.px(rg), (0, 255, 0), 2)                      # 11 层楼梯房
    for rg in R["rings"]["step"]:
        ring(dsm.px(rg), (255, 0, 255), 2)                    # 7 层台阶屋面
    im.save(out_path)
    return out_path


def dilate(m, meters, mpp):
    k = int(round(meters / mpp))
    if k <= 0:
        return m.copy()
    return ndimage.binary_dilation(m, structure=np.ones((3, 3), bool), iterations=k, border_value=0)


# ------------------------------------------------------------------ 主

def main() -> int:
    to_en, pinfo = load_placement()
    if to_en is None:
        log("★ 位姿没读成：%s" % pinfo)
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE（尺子本身没立起来）" % GID)
        return _finish(RC_NOGAUGE, reason=pinfo, blind=["位姿读错 ⇒ 本闸拒绝出任何读数"])

    D = load_decls()
    R = load_regions(to_en)

    log("%s 顶部三个「推的数」对照 2024 实景（步 5 ①）" % GID)
    log("位姿：%s ｜ theta=%.4f° ｜ yflip=%s ｜ 复算 outline_en 最大差 %.3e m ✓"
        % (os.path.relpath(REGBEST, REPO), pinfo["theta_deg"], pinfo["yflip"],
           pinfo["selfcheck_max_err_m"]))
    log("      IoU %.4f ｜ 边界中位 %.2f m / p90 %.2f m（**位姿自己带的平面误差**，见盲区）"
        % (pinfo["best_iou"], pinfo["boundary_median_m"], pinfo["boundary_p90_m"]))
    log("DSM ：%s" % DSM)
    log("交付侧声明（`rebuild/构件库/参数.json`，唯一真源）—— 标注逐条印出：")
    log("      ① 女儿墙高 %.0f mm [%s] ｜ 厚 %.0f mm [%s]"
        % (D["parapet_h_mm"], D["parapet_h_mark"], D["parapet_t_mm"], D["parapet_t_mark"]))
    log("      ② 楼梯房高 %.0f mm [%s]" % (D["roof_stair_h_mm"], D["roof_stair_h_mark"]))
    log("      ③ 台阶屋面高：7 层板顶 %s mm **相对模型 ±0.000**（catalog `1层 z0=0.0`；"
        "±0.000 下方的 `地下1层 z0=-3500` 不算）｜ 层高 %.0f mm [%s]"
        % (R["z_roof_step_top_mm"], D["storey_mm"], D["storey_mark"]))
    log("         ★ 同一次飞行里另一条链出的 11 层板顶 = %s mm（**不用**作 ③ 的声明，"
        "塔楼顶本闸量不出来；只印出来备查）" % R["z_roof_top_mm"])

    # ---- 非空断言（铁律 137）----
    need = [("11层/ROOF", R["n_roof"]), ("11层/PARAPET", R["n_parapet"]),
            ("11层/ROOF_STAIR", R["n_roof_stair"]), ("7层/ROOF_STEP", R["n_roof_step"])]
    empty = [n for n, c in need if c <= 0]
    if empty:
        log("★ 被测集合为空：%s ⇒ 本闸没量到（不是「相符」）" % empty)
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason="构件集合为空：%s" % empty, counts=dict(need),
                       blind=["构件表里找不到要量的构件 ⇒ 拒绝出读数"])
    if not (len(R["z_roof_top_mm"]) == len(R["z_roof_step_top_mm"]) == 1
            and len(R["z_parapet_top_mm"]) == 1 and len(R["z_roof_stair_top_mm"]) == 1):
        log("★ 同类构件的顶标高不唯一 ⇒ 模型自己就没说清，「相符」无从谈起")
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason="同类构件顶标高不唯一",
                       z_top=dict(roof=R["z_roof_top_mm"], parapet=R["z_parapet_top_mm"],
                                  stair=R["z_roof_stair_top_mm"], step=R["z_roof_step_top_mm"]),
                       blind=["同类构件自身标高不一致 ⇒ 本闸不出读数"])
    log("构件：ROOF %d ｜ PARAPET %d ｜ ROOF_STAIR %d ｜ ROOF_STEP %d（**非空**）"
        % (R["n_roof"], R["n_parapet"], R["n_roof_stair"], R["n_roof_step"]))

    # ---- 采样 ----
    dsm = Dsm(to_en, pinfo["tr_en"])
    log("\nDSM：%s ｜ %s ｜ %.2f m/px ｜ 窗口 %d×%d ｜ 有效 %.1f%%"
        % (os.path.basename(DSM), dsm.crs, dsm.mpp, dsm.shape[1], dsm.shape[0],
           100 * dsm.n_valid_frac))
    log("      窗口中心 = 落位后质心 (%.3f, %.3f)（**不是模型原点落位后在哪**）"
        % (dsm.ctr[0], dsm.ctr[1]))
    _w = dsm.arr[dsm.good]
    log("      窗口全幅：5/50/95 分位 = [%.2f, %.2f, %.2f] ｜ min %.2f ｜ max %.2f"
        % (np.percentile(_w, 5), np.percentile(_w, 50), np.percentile(_w, 95),
           _w.min(), _w.max()))
    _g0 = float(np.percentile(_w, 5))    # 字符图的色标地面（实测）。★ 三条判据读数都与它无关（同景内的差）

    # ★ 自检：窗口必须**整只罩住**真值轮廓与模型轮廓。中心取错时读数照出、不报错 ⇒ 在这里挡住。
    _oe = np.asarray(pinfo["outline_en"], float)
    _me = np.asarray(to_en(np.asarray(R["outline1_mm"], float).reshape(-1, 2)), float)
    _allp = np.vstack([_oe, _me])
    _in = (dsm.E_LO <= _allp[:, 0].min() and _allp[:, 0].max() <= dsm.E_HI
           and dsm.N_LO <= _allp[:, 1].min() and _allp[:, 1].max() <= dsm.N_HI)
    if not _in:
        b = [round(float(_allp[:, 0].min()), 1), round(float(_allp[:, 0].max()), 1),
             round(float(_allp[:, 1].min()), 1), round(float(_allp[:, 1].max()), 1)]
        log("★ 窗口没罩住轮廓：轮廓 EN bbox=%s，窗口 E[%.1f,%.1f] N[%.1f,%.1f] ⇒ 尺子没立对，不出读数"
            % (b, dsm.E_LO, dsm.E_HI, dsm.N_LO, dsm.N_HI))
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason="采样窗没罩住轮廓（中心/位姿错）", outline_en_bbox=b,
                       window=[dsm.E_LO, dsm.E_HI, dsm.N_LO, dsm.N_HI],
                       blind=["窗口没罩住被测物 ⇒ 拒绝出读数（这一类的症状是「照出数但全是别人的地物）」"])

    STAIR_FULL = dsm.mask(R["rings"]["stair"])
    # ★ 模型自证（**不碰 DSM**）：ROOF 环必须落在 1 层轮廓之内。★ 先排除这一条，再谈配准 ——
    #   模型自己不自洽时，在栅格上的症状是「掩膜跨到地面/邻栋」，与「配准错了」**同形**（铁律 183）。
    _m_o = dsm.mask([R["outline1_mm"]])
    _m_r = dsm.mask(R["rings"]["roof"])
    _n_out = int((_m_r & ~_m_o).sum())
    _n_all = max(1, int(_m_r.sum()))
    log("      [模型自证] ROOF 环落在 1 层轮廓**之外**的：%.1f / %.1f m² = %.2f%%"
        % (_n_out * dsm.mpp ** 2, _n_all * dsm.mpp ** 2, 100.0 * _n_out / _n_all))
    log("         —— 该比例大 ⇒ **模型自己不自洽**（塔楼环不在裙房轮廓里），"
        "不是配准错；两者在栅格上同形，必须先分开")
    # ★★ [落位独立复核] —— 位姿是**按 1 层轮廓质心对质心**拟合的，拿它自己复算质心＝循环论证
    #   （`load_placement` 里那道 1e-6 m 的自检只证明「算得对」，不证明「位姿对」）。
    #   独立的那把尺子是 **DSM 自己量出来的屋面**：3 m 邻域平 + 高于地面 6 m 的像素。
    #   ★ 上一版写的是「> 地面+6 m 的全部连通体」，实测 **21410 m²** —— 比楼自己的 6719 m²
    #     还大 3 倍：**树冠也高于 6 m，且彼此连成一片**，量出来的质心 (E−49.2, N+46.7) 是
    #     「树+楼的质心」（铁律 137：判据名单漏掉主体 ⇒ 数照出、没人发现错）。
    #   ⇒ 屋顶面**不平的树**用「平」这一条挡掉；再取**最大那一丛**（＝楼自己）挡掉邻栋。
    _tf = dsm.flat & dsm.good & (dsm.arr > _g0 + 6.0)
    _tl, _tn = ndimage.label(_tf, structure=np.ones((3, 3), int))
    if _tn > 0:
        _tc = np.bincount(_tl.ravel())
        _tc[0] = 0
        _tf = _tl == int(np.argmax(_tc))
    _tf_n = max(1, int(_tf.sum()))
    _f_cen = np.argwhere(_tf).mean(axis=0)
    log("      [落位独立复核] DSM 屋面丛（3 m 邻域平 且 > 地面+6 m，取最大连通丛）：%.1f m² ｜ "
        "质心离窗口中心 (E%+.1f, N%+.1f) m"
        % (_tf_n * dsm.mpp ** 2,
           (_f_cen[1] - dsm.ctr_px[1]) * dsm.mpp, (dsm.ctr_px[0] - _f_cen[0]) * dsm.mpp))
    _c0 = float((dsm.mask([R["outline1_mm"]]) & _tf).sum())
    _bt = (_c0, 0, 0)
    for _dy in range(-25, 26, 5):
        for _dx in range(-25, 26, 5):
            _c = float((dsm.mask([R["outline1_mm"]], float(_dx), float(_dy)) & _tf).sum())
            if _c > _bt[0]:
                _bt = (_c, _dx, _dy)
    log("         模型 1 层轮廓在 0 m 处盖住其中 %.1f%%；±25 m/步 5 m 网格最优 = Δ(E%+d, N%+d) "
        "⇒ 盖住 %.1f%%" % (100.0 * _c0 / _tf_n, _bt[1], _bt[2], 100.0 * _bt[0] / _tf_n))
    if _bt[0] > _c0 * 1.05:
        log("         ⇒ **落位平移残差 ≈ (E%+d, N%+d) m**（挪过去多盖 %.1f 个百分点）"
            % (_bt[1], _bt[2], 100.0 * (_bt[0] - _c0) / _tf_n))
    else:
        log("         ⇒ **落位平移已在 5 m 网格内最优**（挪不动 ⇒ 平移没有残差）；"
            "那么 11 层环离塔楼 12 m 就**不是位姿的账**，是**模型里塔楼画偏了**（铁律 196）")

    # ★ 叠图：**必须落成文件**（不是一次性探针）。「环圈错地方」与「这栋楼真的不止一块面」
    #   在每一个读数上都同形；只有「模型自己的环」画在「实景高程」上才分得开。
    _ov = os.path.join(REPO, "gates", "_out", "%s_叠加.png" % GID)
    try:
        overlay_png(dsm, R, pinfo, _ov)
        log("      [叠图] 底图=2024 DSM（压暗），线：白=真值轮廓 蓝=模型1层轮廓 "
            "红=11层ROOF 绿=11层楼梯房 品红=7层台阶屋面 ⇒ %s"
            % os.path.relpath(_ov, REPO).replace("\\", "/"))
    except Exception as _e:
        log("      [叠图] 没画成：%s" % _e)

    # ★ 交付件的 4 个 `ROOF` 块**没有挖楼梯房的洞** ⇒ 屋面并集里含高 3 m 的楼梯房占地。
    #   量「屋面基准」时**必须扣掉它**，否则 `tol_m` 被它撑到 3 m 量级 ⇒ ② 的判定当场失去分辨力。
    S = dsm.mask(R["rings"]["roof"]) & ~dilate(STAIR_FULL, ERODE_STAIR_M, dsm.mpp)
    S_in = erode(S, ERODE_ROOF_M, dsm.mpp)
    ST = erode(STAIR_FULL, ERODE_STAIR_M, dsm.mpp)
    SP = dsm.mask(R["rings"]["step"])
    SP = erode(SP, ERODE_STEP_M, dsm.mpp) & ~dilate(dsm.mask([R["outline8_mm"]]), STEPS_UNION_M, dsm.mpp)

    def parts(m, min_px=20):
        """区域里的**平地连通块**清单，按面积降序。

        ★ 读数取「**最大那一块**」，不取整个区域的中位 —— 这是本闸改了三轮才定下来的一处。
        一个 ROOF 环里**同时**躺着屋面板、楼梯房、屋顶设备、以及配准误差带进来的邻面；
        它们的**中位**会被拽走、它们的**离散**会变成「区域里所有东西的高度跨度」
        （实测 p10~p90 = **54 m** ⇒ 容差大到把 +0.9 m 与 −5.4 m 都判「相符」）。
        连通性才是「这一块面」的定义 —— **一块面只有一个高度，两块面才让中位失效**。
        栅格上落在同一块面上的像素必然 8 连通，所以按连通块取，量到的是面、不是混合物。
        """
        mm = m & dsm.flat
        if not mm.any():
            return []
        lab, n = ndimage.label(mm, structure=np.ones((3, 3), int))
        if n == 0:
            return []
        cnt = np.bincount(lab.ravel())
        cnt[0] = 0
        out = []
        for k in np.argsort(cnt[1:])[::-1] + 1:
            if cnt[k] < min_px:
                break
            sel = lab == k
            v = dsm.arr[sel]
            g = np.argwhere(sel).mean(axis=0)
            out.append(dict(n=int(v.size), area_m2=float(v.size) * dsm.mpp ** 2,
                            z=float(np.median(v)),
                            p10=float(np.percentile(v, 10)), p90=float(np.percentile(v, 90)),
                            mad=float(np.median(np.abs(v - np.median(v)))),
                            cen=(float(g[0]), float(g[1]))))
        return out

    def medf(m):
        """**只取平地**、且只取其中**最大那一块连通面**的中位 —— 见 `parts` 那段。"""
        ps = parts(m)
        return (None, 0) if not ps else (ps[0]["z"], ps[0]["n"])

    # ★ 几何自证：多边形**落位后**的 EN 外接与鞋带面积。光看栅格外接/面积**分不出**
    #   「环本身就小」与「栅格化丢了面」—— 这两件事的症状同形（铁律 183）。
    _pr = [np.asarray(to_en(np.asarray(rg, float).reshape(-1, 2)), float) for rg in R["rings"]["roof"]]
    _pa = np.vstack(_pr)
    _sa = sum(float(0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], -1))
                              - np.dot(p[:, 1], np.roll(p[:, 0], -1)))) for p in _pr)
    log("      [几何自证] ROOF 环落位后：EN 外接 %.1f × %.1f m ｜ 鞋带面积合计 %.1f m²"
        "（栅格实测 %.1f m²）｜ DSM transform b=%.6f d=%.6f"
        % (float(_pa[:, 0].max() - _pa[:, 0].min()), float(_pa[:, 1].max() - _pa[:, 1].min()),
           _sa, float(S.sum()) * dsm.mpp ** 2,
           float(dsm.src_transform.b), float(dsm.src_transform.d)))

    for _nm, _m in (("S(屋面·扣楼梯房)", S), ("S_in(屋面内部)", S_in),
                    ("ST(楼梯房内部)", ST), ("SP(台阶屋面)", SP)):
        _n = int(_m.sum())
        if _n == 0:
            log("      %-18s **空**" % _nm)
            continue
        _rr, _cc = np.nonzero(_m)
        _vv = dsm.arr[_m & dsm.good]
        log("      %-18s %7d px = %8.1f m² ｜ 像素 bbox r[%d,%d] c[%d,%d] ｜ 平地占 %.0f%% ｜ z 中位 %s"
            % (_nm, _n, _n * dsm.mpp ** 2, _rr.min(), _rr.max(), _cc.min(), _cc.max(),
               100.0 * float((_m & dsm.flat).sum()) / _n,
               "未量到" if _vv.size == 0 else "%.2f m" % np.median(_vv)))

    # ★★ 高程直方图 —— **表格给不出「这块地上躺着几层」**。没有它，分不出
    #   「尺子选错了面」与「这栋楼真的不止一块面」（铁律 183：症状同形）。
    #   ★ 一层的占比够大 ⇒ 该层就是这块地的面；分成两半 ⇒ 本闸**不许**在这块地上出读数。
    def hist(m, title, bin_m=1.0):
        v = dsm.arr[m & dsm.good]
        if v.size == 0:
            log("      %s：无值" % title)
            return
        lo = math.floor(float(v.min()) / bin_m) * bin_m
        hi = math.ceil(float(v.max()) / bin_m) * bin_m + bin_m
        edges_ = np.arange(lo, hi + bin_m, bin_m)
        c, _ = np.histogram(v, bins=edges_)
        log("      %s（%d px）—— **每 1.0 m 一层**，占比 = 该层像素/全区："
            % (title, int(v.size)))
        for i in np.argsort(c)[::-1][:6]:
            if c[i] == 0:
                continue
            log("        %4.0f~%4.0f m  %6d px  %5.1f%%  %s"
                % (edges_[i], edges_[i + 1], int(c[i]), 100.0 * c[i] / v.size,
                   "#" * max(1, int(round(40 * c[i] / v.size)))))

    for _nm, _m in (("S_in(屋面内部)", S_in), ("ST(楼梯房内部)", ST), ("SP(台阶屋面)", SP)):
        hist(_m, _nm)

    lv = parts(S_in)
    # ★ 全窗口的平地分层 —— 这把尺子的「自重」。★ 没有它，**掩膜圈错地方也看不出来**：
    #   圈错时读数照样有值、照样稳定，只是量的是别人家的屋顶（铁律 183/192 的形状）。
    #   所以判读之前先看「我要量的那块面」在不在上面这张表里。
    # ★ 全窗「平地」**按高程分层** —— 这栋楼到底有哪些水平面，一次列全。
    #   原来这张表是「按面积降序前 10」，**量具本身是坏的**：地面块（4911 m²）永远霸榜，
    #   实测第 10 名已经 349 m² ⇒ 47 m 那块 184 m² 的塔楼面**根本进不了前十**，
    #   而它恰恰是本闸要量的面 ⇒ 「不在表里」会被误读成「没有这块面」（铁律 183 的形状）。
    #   按**高程**分组才是「有哪些面」的正确量具；面积只用来排序组内的块。
    _by_level = {}
    _gl_max = None                                           # 全窗最大的一块平地（地面估计器之一）
    for _p in parts(dsm.flat & dsm.good, min_px=150):
        _k = round(_p["z"] * 2.0) / 2.0                      # 0.5 m 一档
        _de = (_p["cen"][1] - dsm.ctr_px[1]) * dsm.mpp       # 该块块心相对窗口中心的偏移
        _dn = (dsm.ctr_px[0] - _p["cen"][0]) * dsm.mpp
        _b = _by_level.setdefault(_k, [0.0, 0, None, 0.0, 0.0])
        _b[0] += _p["area_m2"]
        _b[1] += 1
        _b[3] += _de * _p["area_m2"]                         # 面积加权 ⇒ 「这一层在哪」
        _b[4] += _dn * _p["area_m2"]
        if _b[2] is None or _p["area_m2"] > _b[2]["area_m2"]:
            _b[2] = _p
        if _gl_max is None or _p["area_m2"] > _gl_max["area_m2"]:
            _gl_max = _p
    log("      全窗平地**按高程分层**（0.5 m 一档，只收 ≥150 px＝%.1f m² 的块）—— 有哪些水平面："
        % (150 * dsm.mpp ** 2))
    for _k in sorted(_by_level, reverse=True)[:14]:
        _a, _n, _p, _se, _sn = _by_level[_k]
        log("         z %7.2f m ｜ 合计 %8.1f m² ｜ %2d 块 ｜ 最大块 %7.1f m² ｜ "
            "**层心**(面积加权) (E%+.1f, N%+.1f) m"
            % (_k, _a, _n, _p["area_m2"], _se / max(1e-9, _a), _sn / max(1e-9, _a)))

    # ★ 模型自己的环**在哪** —— 与上表的「层心」逐层对照，才谈得上「环圈对没圈对」。
    #   栅格质心（＝上面那些块心的同一种量）而不是顶点平均，两边才是同一把尺子。
    _mring = []
    for _nm, _rs in (("1层轮廓", [R["outline1_mm"]]), ("8层轮廓", [R["outline8_mm"]]),
                     ("11层ROOF", R["rings"]["roof"]), ("11层楼梯房", R["rings"]["stair"]),
                     ("7层台阶屋面", R["rings"]["step"])):
        _mm = dsm.mask(_rs)
        _ma = float(_mm.sum()) * dsm.mpp ** 2
        _g2 = np.argwhere(_mm).mean(axis=0)
        _mring.append((_nm, _ma,
                       (_g2[1] - dsm.ctr_px[1]) * dsm.mpp, (dsm.ctr_px[0] - _g2[0]) * dsm.mpp))
    log("      [环心自证] 模型各环（栅格质心）离窗口中心：" +
        " ｜ ".join("%s(%.0f m²) (E%+.1f, N%+.1f)" % t for t in _mring))

    # ★ 掩膜的高程图 —— **表格给不出空间**，而「北半边是地面、南半边是屋面」这种形状
    #   只有摆出来才看得见。没有这张图，「掩膜圈错地方」与「尺子没分辨力」永远同形（铁律 183）。
    #   ★ 印**绝对高程**（整数米），不用色标 —— 色标要靠图例翻译，翻译错一次就白折腾三轮。
    def amap(m, title, cell_px=8):
        rr, cc = np.where(m)
        if rr.size == 0:
            log("      %s：（空）" % title)
            return
        r0, r1, c0, c1 = int(rr.min()), int(rr.max()), int(cc.min()), int(cc.max())
        log("      %s —— 图上是**每格 %d px（%.1f m）的中位绝对高程，单位 m**；'...' 无值。"
            % (title, cell_px, cell_px * dsm.mpp))
        log("         图幅 %d×%d px = %.0f×%.0f m（南在上：第 1 行是最南，每行往北走 %.1f m）"
            % (r1 - r0 + 1, c1 - c0 + 1, (c1 - c0 + 1) * dsm.mpp, (r1 - r0 + 1) * dsm.mpp,
               cell_px * dsm.mpp))
        for r in range(r1, r0 - 1, -cell_px):          # ★ 栅格行号越小越靠北 ⇒ 倒着印才是「北在上」
            line = []
            for c in range(c0, c1 + 1, cell_px):
                rb = slice(max(r0, r - cell_px + 1), r + 1)
                mb = m[rb, c:c + cell_px]
                vb = dsm.arr[rb, c:c + cell_px]
                gb = dsm.good[rb, c:c + cell_px]
                v = vb[mb & gb]
                line.append("..." if v.size == 0 else "%3d" % int(round(float(np.median(v)))))
            log("          |%s|" % " ".join(line))

    amap(S, "S（屋面·已扣楼梯房）")
    if not lv:
        why = "屋面内部找不到 ≥20 px 的平地连通块"
        log("★ %s ⇒ 没量到" % why)
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason=why,
                       blind=["区域里找不出平地连通块 ⇒ 拒绝出读数（不是「相符」）"])
    z_stair, n_stair_px = medf(ST)
    z_step, n_step_px = medf(SP)
    if z_stair is None or z_step is None:
        why = "楼梯房 %s / 台阶屋面 %s（平地连通块）" % (n_stair_px, n_step_px)
        log("★ 采样区里平地连通块太少 ⇒ 没量到：%s" % why)
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason="采样区平地连通块不足：" + why,
                       blind=["区域里找不出足够的平地连通块 ⇒ 拒绝出读数（不是「相符」）"])

    # ★ 「屋面内部」里到底躺着几个高度 —— 分层印出来。不印就分不出
    #   「尺子没分辨力」与「这块地上真的不止一块面」（铁律 183：症状同形）。
    log("      「屋面内部」的平地分层（连通块 ≥20 px，按面积降序）：")
    for _i, _p in enumerate(lv):
        log("         #%d %8.1f m²  %3d%% ｜ z 中位 %.3f ｜ p10~p90 %.3f ｜ 块心离质心 (E%+.1f, N%+.1f) m"
            % (_i + 1, _p["area_m2"], round(100.0 * _p["n"] / max(1, lv[0]["n"])),
               _p["z"], _p["p90"] - _p["p10"],
               (_p["cen"][1] - dsm.ctr_px[1]) * dsm.mpp, (dsm.ctr_px[0] - _p["cen"][0]) * dsm.mpp))

    # ★★ 塔楼顶够不够格叫「一块面」 —— 本闸最要紧的一次**拒绝**（铁律 183/192 的形状）。
    #   掩膜里只要躺着不止一块面（实测 519.6 / 512.0 / 485.8 / 465.6 四档），
    #   「取最大那块」就只是运气：换个阈值、把掩膜挪 5 m，答案会从 +3.9 跳到 −33.9 m。
    #   ⇒ 判据不是「挑一块」，而是**先问这里够不够格当基准面**；不够就拒绝出数，不挑。
    lv_big = [p for p in lv if p["area_m2"] >= LEVEL_MIN_AREA]
    _zs = [p["z"] for p in lv_big]
    roof_spread = None if len(_zs) < 2 else float(max(_zs) - min(_zs))
    roof_ok = bool(lv_big) and (roof_spread is None or roof_spread <= ROOF_LEVEL_TOL)
    _ref = max(lv_big, key=lambda p: p["area_m2"]) if lv_big else lv[0]
    log("      ★ 塔楼顶可用性：候选面（≥%.0f m²）%d 块 ｜ 高度跨度 %s ｜ 阈值 %.1f m ⇒ **%s**"
        % (LEVEL_MIN_AREA, len(lv_big),
           "只有 1 块（跨度无意义）" if roof_spread is None else "%.2f m" % roof_spread,
           ROOF_LEVEL_TOL, "可用" if roof_ok else "不可用"))
    if not roof_ok:
        log("         ⇒ 掩膜里**不止一块面**：基准面取哪一块，读数就换一个数 ⇒ **塔楼顶一律拒绝出数**")

    # ★★ 「环圈错地方」还是「这栋楼真的不止一块面」—— 判据本身给不出这两者的差别（铁律 183）。
    #   能分开它们的只有**动一下环再量**：把 11 层 ROOF 环整体平移 (dx,dy)，看它下面
    #   **最大的一块平地**变多大。
    #     · 挪 0 m 就最大      ⇒ 环没圈错，这块地上确实躺着好几块面（拒绝出数是对的）
    #     · 挪 ±十几米才最大   ⇒ 环圈错了，**错多少米当场读出来**（不是猜、也不是「配准背锅」）
    #   ★ 只报空间事实，**不参与判定**：本闸不因为这条去挪位姿（位姿来自 1 层轮廓的独立拟合）。
    _os = []
    for _dy in range(-OFFSET_SEARCH_M, OFFSET_SEARCH_M + 1, OFFSET_STEP_M):
        for _dx in range(-OFFSET_SEARCH_M, OFFSET_SEARCH_M + 1, OFFSET_STEP_M):
            _m = erode(dsm.mask(R["rings"]["roof"], dx=float(_dx), dy=float(_dy))
                       & ~dilate(dsm.mask(R["rings"]["stair"], dx=float(_dx), dy=float(_dy)),
                                 ERODE_STAIR_M, dsm.mpp),
                       ERODE_ROOF_M, dsm.mpp)
            _p = parts(_m, min_px=20)
            _os.append((_p[0]["area_m2"] if _p else 0.0,
                        0.0 if not _p else _p[0]["z"], _dx, _dy, len(_p)))
    _os.sort(key=lambda t: -t[0])
    log("      ★ 环平移搜索（把 11 层 ROOF 环整体平移，看它下面**最大一块平地**变多大）：")
    for _a, _z, _dx, _dy, _n in _os[:5]:
        log("         Δ(E%+3d, N%+3d) m ⇒ 最大平地 %7.1f m² ｜ z %8.2f ｜ 面数 %d"
            % (_dx, _dy, _a, _z, _n))
    _a0 = [t for t in _os if t[2] == 0 and t[3] == 0]
    if _a0 and _os[0][0] > _a0[0][0] * 1.25:
        log("         ⇒ **环在 0 m 处不是最大**：挪 %+d/%+d m 才最大（%.1f → %.1f m²）"
            % (_os[0][2], _os[0][3], _a0[0][0], _os[0][0]))
        log("            ⇒ 环（或模型自带的塔楼位置）在 ±%d m 网格内确有更贴的落点；"
            "但本闸**不挪**位姿（位姿来自 1 层轮廓的独立拟合）⇒ 塔楼顶照旧拒绝出数" % OFFSET_SEARCH_M)
    else:
        log("         ⇒ **环在 0 m 处已最大**：不是环圈错了，是这块地上真的躺着好几块面")

    # ★ 容差 = **参考面自身的离散**（实测，不手打）；下限取一格（＝这把尺子的量化步长，
    #   从栅格读出来的，不是手打的数）。**不是**整个区域所有平地像素的 p10~p90 ——
    #   那量的是「区域里所有东西的高度跨度」，会得到 54 m 的哑巴容差。
    tol = max(_ref["p90"] - _ref["p10"], dsm.mpp)
    z_roof = None if not roof_ok else float(_ref["z"])
    log("参考面（最大候选平地连通面，%.1f m²，z=%.3f）：自身 p10~p90 = %.3f m"
        % (_ref["area_m2"], _ref["z"], _ref["p90"] - _ref["p10"]))
    log("      ⇒ **tol_m = %.3f m**（＝该面自身离散，下限一格 %.2f m；后面所有判定用它，不手打）"
        % (tol, dsm.mpp))

    # ---- 地面估计器（★ ③ 要用它：③ 的口径＝**裙房屋面相对地面的标高**，与声明量同义）----
    r_out = dilate(dsm.mask([R["outline1_mm"]]), 10.0, dsm.mpp) & ~dilate(
        dsm.mask([R["outline1_mm"]]), 3.0, dsm.mpp)
    cand = r_out & dsm.flat
    g_ring = None
    if cand.sum() > 50:
        thr = float(np.percentile(dsm.arr[cand], 30.0))
        paved = cand & (dsm.arr < thr)
        if paved.sum() > 50:
            g_ring = float(np.median(dsm.arr[paved]))
    g_est = [g for g in (g_ring, _g0, (_gl_max["z"] if _gl_max else None)) if g is not None]
    g_med = None if not g_est else float(np.median(g_est))
    g_spread = None if len(g_est) < 2 else float(max(g_est) - min(g_est))
    log("      地面估计器（%d 个，取中位）：贴楼铺装环 %s ｜ 窗口 5%% 分位 %.2f ｜ 最大平地块 %s"
        " ⇒ g = %s ｜ 跨度 %s"
        % (len(g_est), "未量到" if g_ring is None else "%.2f" % g_ring, _g0,
           "未量到" if not _gl_max else "%.2f" % _gl_max["z"],
           "未量到" if g_med is None else "%.2f m" % g_med,
           "—" if g_spread is None else "%.2f m" % g_spread))

    # ---- 三条读数 ----
    edges = {}
    for w in (0.25, 0.5, 0.75, 1.0):
        zz, npz = medf(band(S, w, dsm.mpp))
        # ★ 带扫描的参照取**参考面 `_ref`**（最大候选面），**不是** `z_roof` ——
        #   `z_roof` 在「塔楼顶不可用」时是 None，会把这条证据整条抹掉（尺子一退化就沉默，铁律 192）。
        edges[w] = None if zz is None else float(zz - _ref["z"])

    d1 = D["parapet_h_mm"] / 1000.0
    d2 = D["roof_stair_h_mm"] / 1000.0
    z_top_step = R["z_roof_step_top_mm"][0] / 1000.0
    d3 = float(z_top_step)          # 台阶屋面相对**模型 ±0.000**（catalog: 1 层 z0=0.0）⇒ 与 ③ 同义
    # ★ ① 的读数是 `带 − 塔楼顶`：**塔楼顶立不起来（`z_roof=None`）⇒ 未量到**。
    #   一度写成「拿兜底的 `_ref`（最大候选面）当参照」，结果参照面是**屋顶设备**（519.56），
    #   带里量到的是 21 m 的屋面 ⇒ 报出 −33.894 的假「不符」（铁律 192 的原意是
    #   「尺子退化时不许沉默」，**不是**「随便换一把尺子接着出数」——换错了参照，读数比沉默更坏）。
    #   带扫描本身照旧逐宽度印出来（证据不丢），但**只作诊断**，不进判词表。
    _b25, _ = medf(band(S, 0.25, dsm.mpp))
    r1 = None if (z_roof is None or _b25 is None) else float(_b25 - z_roof)
    r2 = None if (z_roof is None or z_stair is None) else float(z_stair - z_roof)
    r3 = None if (z_step is None or g_med is None) else float(z_step - g_med)

    # 亚格：构件厚度 < 一格 ⇒ 尺子结构上看不见
    sub1 = (D["parapet_t_mm"] / 1000.0) < dsm.mpp

    def judge(read, decl, subgrid, tol_u):
        if read is None:
            return "未量到"
        if subgrid and abs(read) < 2 * tol_u:
            return "未决"
        return "相符" if abs(read - decl) <= tol_u else "不符"

    _roof_note = "" if roof_ok else (
        "塔楼顶基准面不唯一（候选面跨度 %s > %.1f m）⇒ **拒绝出数**，不挑一块"
        % ("%.2f m" % roof_spread if roof_spread is not None else "—", ROOF_LEVEL_TOL))
    items = [
        dict(no="①", name="女儿墙高", read=r1, decl=d1, sub=sub1, tol=tol,
             feat_m=D["parapet_t_mm"] / 1000.0,
             note=("带厚 %.2f m < 一格 %.2f m ⇒ 结构上量不到；且**参照面（塔楼顶）立不起来**"
                   "⇒ 未量到（带扫描只作诊断）" % (D["parapet_t_mm"] / 1000.0, dsm.mpp))
             if z_roof is None else
             "带厚 %.2f m < 一格 %.2f m ⇒ 结构上量不到" % (D["parapet_t_mm"] / 1000.0, dsm.mpp)),
        dict(no="②", name="楼梯房高(梯房顶−塔楼顶)", read=r2, decl=d2, sub=False, tol=tol,
             feat_m=R["stair_min_side_m"], note=_roof_note),
        dict(no="③", name="台阶屋面高(裙房顶−地面)", read=r3, decl=d3, sub=False,
             feat_m=R["step_min_side_m"], tol=tol + (g_spread or 0.0),
             note="容差已含地面估计器跨度 %.2f m" % (g_spread or 0.0)),
    ]
    for it in items:
        it["delta"] = None if it["read"] is None else float(it["read"] - it["decl"])
        it["verdict"] = judge(it["read"], it["decl"], it["sub"], it["tol"])

    log("\n[读数] 外圈带宽度扫描（① —— 若女儿墙真被 DSM 看见，0.25 m 带应当最高、随后衰减）：")
    log("      ★ **只作诊断**：① 的读数用 `z_roof`（塔楼顶），它不是 None 才有读数。"
        "下表为省事拿兜底参照面 z=%.3f m 相减 —— 那个数是**屋顶设备**不是塔楼顶，"
        "所以差值恒在 −34 m 量级，**别当成女儿墙读数**（换错参照比沉默更坏）" % _ref["z"])
    for w in (0.25, 0.5, 0.75, 1.0):
        log("      带宽 %.2f m ⇒ 比参考面高 %s"
            % (w, "未量到" if edges[w] is None else "%.3f m" % edges[w]))
    log("\n[判词表]  tol_m = %.3f m" % tol)
    log("  %s %-24s %10s %10s %10s %7s %8s   %s"
        % ("", "构件", "实景读数", "交付声明", "差", "容差", "构件宽", "判定"))
    for it in items:
        log("  %s %-24s %9s %10.3f %10s %6.3f %6.2fm   %s"
            % (it["no"], it["name"],
               "未量到" if it["read"] is None else "%.3f m" % it["read"], it["decl"],
               "未量到" if it["delta"] is None else "%+.3f m" % it["delta"],
               it["tol"], it["feat_m"], it["verdict"]))

    # ---- 旁证 ③b：与地面基准（★ 不属于判据，只印出来）----
    g_p05 = float(np.nanpercentile(dsm.arr[dsm.good], 5.0))
    frac_above5 = None
    if g_ring is not None:
        vv = dsm.arr[SP & dsm.good]
        if vv.size:
            frac_above5 = float(np.mean(vv > g_ring + 5.0))
    log("\n[旁证 ③b]（**不参与判定**，只为对账地面基准那 1.94 m 的分歧）")
    log("      `zcheck.py` 写的 466.60 与 `dsm_roofs_c006.py` 实测 464.66 相差 1.94 m ⇒ "
        "本闸把三个估计器**摆在一起取中位**，跨度 %s 已经算进 ③ 的容差（不裁谁对）"
        % ("—" if g_spread is None else "%.2f m" % g_spread))
    log("      台阶屋面区高于「地面+5 m」的像素比例 = %s（原口径记「98%% 高于 5 m」）"
        % ("未量到" if frac_above5 is None else "%.1f%%" % (100 * frac_above5)))
    if g_med is not None and z_step is not None:
        # ★★ 一句必须说清的话：③ 的差**分不开两件事，两者给出同一个读数** ——
        #   ① 「层高」：影像反算 ≈4.0 m/层，交付侧写 3500 mm；
        #   ② 「模型 z=0 在不在实测地面上」：catalog 里 `1层 z0=0.0` ＋ `地下1层 z0=−3500`，
        #      ⇒ ±0.000 是**模型自己的约定**，本闸**没有任何办法**验证它就落在 464.5 m。
        #   铁律 018：两个数对上不能证明它们对；同理两个错法给出同一个读数也不能互证。
        _n_pod = int(round(z_top_step / (D["storey_mm"] / 1000.0)))       # 7（由表现算，不手打）
        log("      ★ ③ 反算层高：%.3f m ÷ %d 层（模型口径 %.1f ÷ %.1f） = **%.2f m/层**"
            % (r3, _n_pod, z_top_step, D["storey_mm"] / 1000.0, r3 / _n_pod))
        log("        而交付侧写 **%.0f mm [%s]** ｜ 差 %.3f m（÷%d 层 = %.2f m/层 的缺口）"
            % (D["storey_mm"], D["storey_mark"], r3 - d3, _n_pod, (r3 - d3) / _n_pod))
        # ★★ 第三个读法（★ 这条与 2026-10-15 的「层高都不管了，到默认 3.5 m 建设」相容）：
        #   层高**不动**，问「这个 28.103 m 是几层」⇒ 28.103 ÷ 3.5 = 8.03 层 ⇒ **裙房是 8 层**。
        #   实测支持：本窗 0.5 m 分层的层心 492.50 / 496.00 / 485.50 m 减去地面 464.52
        #   = 27.98 / 31.48 / 20.98 m，与模型 层高3.5 的 8 层顶 28.0 / 9 层顶 31.5 / 6 层顶 21.0
        #   **逐一对上（≤0.5 m）** —— 这是「层高 3.5 成立、层数才是错的那一项」的独立旁证。
        _n_if35 = r3 / (D["storey_mm"] / 1000.0)     # ★ 用**读到的** r3，不是声明的 z_top_step
        log("      ★ 第三个读法（与「层高定 3.5 m」相容）：层高不动 ⇒ %.3f ÷ %.1f = **%.2f 层** "
            "⇒ 裙房应为 **%d 层**（差正好一层）"
            % (r3, D["storey_mm"] / 1000.0, _n_if35, int(round(_n_if35))))
        log("      ⇒ ★ 本闸**分不开**「层高其实是 4.0」/「模型 ±0.000 不在实测地面上」/"
            "「裙房层数少了 1 层」：三者给出**同一个读数**（铁律 018 的形状）⇒ **必须由用户裁**，"
            "本闸不自行改口径。★ 注意其中只有第三条与既有命令「层高定 3.5 m」相容")

    # ---- 正对照 ----
    ctl = []

    def rec(case, expect, fired, **kw):
        ctl.append(dict(case=case, expect=expect, fired=bool(fired), **kw))

    SHIFT_M = 5.0
    TOL3 = tol + (g_spread or 0.0)

    # 甲 —— ★ 现在量的是「③ 稳不稳」：裙房 1970 m² 远大于 5 m 的平移 ⇒ 读数必须基本不动。
    #   旧版甲是「平移后 ② 必须变」，而 ② 现在**已经拒绝出数** ⇒ 那条对照没有靶子了，
    #   按铁律 28：把它换掉，并把代价写在旁边（旧的判据「窄构件对平移敏感」改由丁承担）。
    SP2 = dsm.mask(R["rings"]["step"], dx=SHIFT_M) & ~dilate(
        dsm.mask([R["outline8_mm"]], dx=SHIFT_M), STEPS_UNION_M, dsm.mpp)
    z2p, _ = medf(erode(SP2, ERODE_STEP_M, dsm.mpp))
    d3r = None if z2p is None else float(z2p - g_med)
    rec("甲 裙房掩膜平移 %.0f m（1970 m² 的面）：③ 必须基本不动" % SHIFT_M,
        "|Δ③| ≤ tol3 = %.3f m ⇒ 这个读数是从**一大块面**上量出来的，不靠运气" % TOL3,
        (d3r is not None and r3 is not None and abs(d3r - r3) <= TOL3),
        read3_shifted=d3r, delta3=(None if (d3r is None or r3 is None) else float(d3r - r3)))

    # 丁 —— ★ 把「不稳定」本身变成一条**通过**的对照：塔楼掩膜平移 5 m 后，
    #   如果平地档仍然不止一块、跨度仍然 > 阈值，那 ② 的拒答就是**有据的**，
    #   而不是「尺子抽风」。（★ 没有这条，② 的未量到与「尺子坏了」永远同形，铁律 183。）
    S_in2 = erode(dsm.mask(R["rings"]["roof"], dx=SHIFT_M)
                  & ~dilate(dsm.mask(R["rings"]["stair"], dx=SHIFT_M), ERODE_STAIR_M, dsm.mpp),
                  ERODE_ROOF_M, dsm.mpp)
    lv2 = [p for p in parts(S_in2) if p["area_m2"] >= LEVEL_MIN_AREA]
    _zs2 = [p["z"] for p in lv2]
    sp2 = None if len(_zs2) < 2 else float(max(_zs2) - min(_zs2))
    rec("丁 塔楼掩膜平移 %.0f m：掩膜里仍躺着不止一块面 ⇒ ② 的拒答有据" % SHIFT_M,
        "平移后候选面 ≥2 块且跨度 > %.1f m（与不移动时同形）" % ROOF_LEVEL_TOL,
        (sp2 is not None and sp2 > ROOF_LEVEL_TOL),
        n_levels_before=len(lv_big), spread_before=roof_spread,
        n_levels_shifted=len(lv2), spread_shifted=sp2)

    # 乙 把台阶屋面区搬出楼外（偏移量按固定表试，取第一个与真值轮廓重叠 <5% 的）
    truth = dsm.mask([np.asarray(pinfo["outline_en"], float).ravel()])
    chosen, off = None, None
    for ox, oy in ((90.0, 70.0), (110.0, 60.0), (70.0, 110.0)):
        m = erode(dsm.mask(R["rings"]["step"], dx=ox, dy=oy), ERODE_STEP_M, dsm.mpp)
        if m.sum() < 20:
            continue
        ov = float((m & truth).sum()) / float(m.sum())
        if ov < 0.05:
            chosen, off = m, (ox, oy, ov)
            break
    if chosen is None:
        rec("乙 搬出楼外：台阶屋面区不再该是 %.1f m" % d3, "需要一个与真值轮廓重叠<5%的偏移", False,
            reason="固定表里的偏移都还压在楼上 ⇒ 靶子没搬出去（不是尺子没分辨力）")
    else:
        zb, nb = medf(chosen)
        rb = None if zb is None else float(zb - g_med)
        rec("乙 搬出楼外：台阶屋面区不再该是 %.1f m" % d3,
            "|Δ③| ≥ 5 m（证明这个数是从**这块地**上量出来的，不是常数）",
            (rb is not None and abs(rb - r3) >= 5.0),
            offset_m=list(off[:2]), overlap_with_truth=round(off[2], 4),
            read3_offbuilding=rb, delta3=(None if rb is None else float(rb - r3)))

    zp_c, _ = medf(SP)
    rec("丙 同一掩膜自减", "必须恰好 0.0（尺子不会凭空造出差）",
        (zp_c is not None and abs((zp_c - g_med) - r3) == 0.0), reread=r3)

    n_fired = sum(1 for c in ctl if c["fired"])
    log("\n[正对照]")
    for c in ctl:
        log("   %s %s ｜ 读数 %s"
            % ("✓" if c["fired"] else "★没红！", c["case"],
               {k: v for k, v in c.items() if k not in ("case", "expect", "fired")}))

    # ---- 收口 ----
    n_bad = sum(1 for it in items if it["verdict"] == "不符")
    n_ok = sum(1 for it in items if it["verdict"] == "相符")
    n_und = sum(1 for it in items if it["verdict"] in ("未决", "未量到"))
    ok = (n_bad == 0) and (n_ok >= 1) and (n_fired == len(ctl))

    log("\n===== 判词 =====")
    log("三个「推的数」对照 2024 实景：相符 %d ｜ 不符 %d ｜ **仍未决/未量到 %d**（tol_m = %.3f m）"
        % (n_ok, n_bad, n_und, tol))
    for it in items:
        log("   %s %-24s 实景 %s vs 声明 %.3f ⇒ **%s**%s"
            % (it["no"], it["name"],
               "未量到" if it["read"] is None else "%.3f m" % it["read"], it["decl"], it["verdict"],
               ("（%s）" % it["note"]) if it["note"] else ""))
    log("   塔楼顶基准面：%s（候选面 %d 块，跨度 %s，阈值 %.1f m）"
        % ("可用" if roof_ok else "**不可用 ⇒ 拒绝出数**", len(lv_big),
           "—" if roof_spread is None else "%.2f m" % roof_spread, ROOF_LEVEL_TOL))
    log("   地面：%s m（%d 个估计器，跨度 %s）"
        % ("未量到" if g_med is None else "%.2f" % g_med, len(g_est),
           "—" if g_spread is None else "%.2f m" % g_spread))
    log("正对照 %d/%d 按预期 ｜ ★ 计划文件里那条「平移 1 m ⇒ 读数必须变」**实测作废**，"
        "已换成与分辨力相称的甲/乙/丙/丁（见 docstring）" % (n_fired, len(ctl)))
    log("%s 总判 : %s" % (GID, "PASS" if ok else "FAIL"))

    blind = [
        "**DSM＝最高面**：树冠/旗杆/女儿墙顶上多出来的都算进去 ⇒ 读数偏正；本闸不做树/屋分类",
        "**0.25 m 格 vs %.2f m 女儿墙厚**：① 结构性亚格；看不见时本闸报**未决**，"
        "**不报「没有女儿墙」**" % (D["parapet_t_mm"] / 1000.0),
        "**② 塔楼顶本闸结构上量不了**：塔楼环的掩膜里同时躺着屋面板 / 楼梯房 / 屋顶设备 /"
        "配准误差带进来的邻面（实测四档 465.6~519.6 m）⇒ 「取最大那块」只是运气；"
        "本闸因此**拒绝出 ② 的数**，而不是挑一块报出来",
        "**③ 的差本闸分不开三件事**（同一个读数，铁律 018）：「层高其实是 4.0 m」/"
        "「模型 ±0.000 不在实测地面上」/「**裙房层数少了 1 层**」（实测与声明差 %.2f m）⇒ "
        "三条并列报给用户裁，本闸不自行改口径；★ 只有第三条与既有命令「层高定 3.5 m」相容"
        % (r3 - d3 if (r3 is not None) else 0.0),
        "**「平地」阈值 %.2f m 与 `_scratch/dsm_roofs_c006.py:91` 同口径**（`:83` 的 0.40 是铺装判据）"
        "⇒ 但两把尺子的窗口/掩膜不同，**不比绝对值**" % FLAT_TOL_M,
        "**位姿自带平面误差**：boundary_median %.2f m / p90 %.2f m（同一份 regbest）⇒ "
        "掩膜会跨到地面/邻栋；本闸因此只把**大面**（裙房 1970 m²）的读数当判据，"
        "对侧向误差不敏感" % (pinfo["boundary_median_m"], pinfo["boundary_p90_m"]),
        "**地面基准**：zcheck.py 写 466.60、dsm_roofs_c006.py 实测 464.66（差 1.94 m）——"
        "本闸不裁谁对，只把三个估计器取中位、把跨度算进 ③ 的容差（实测跨度 %.2f m）"
        % (g_spread or 0.0),
        "**「全窗平地按高程分层」表是普查表不是判据**：只收 ≥150 px（＝9.4 m²）的块、"
        "高程按 0.5 m 一档归并 ⇒ 小块面看不见、同档两块面会并成一行",
        "**环平移搜索（±%d m / 步 %d m）只做诊断**：它分的是「环圈错地方」与「楼真的不止一块面」"
        "这两件在每个读数上都同形的事；**不回写位姿**（拿被测的塔楼顶去调位姿＝拿被测物校尺子）"
        % (OFFSET_SEARCH_M, OFFSET_STEP_M),
        "**不判厚度、不判位置、不判纹理**；不判女儿墙顶上有没有压顶/栏杆",
        "参照链只用了 DSM 栅格链（0.25 m），**没用** campus2024.glb 实景网格链 ⇒ 两链差别本闸看不见",
        "**本闸量的是「影像上那个台阶有多高」，不是「该不该是那么高」**——合规性是另一件事",
    ]
    return _finish(RC_PASS if ok else RC_FAIL,
                   dsm=dict(path=DSM, crs=dsm.crs, mpp=dsm.mpp, half_m=HALF_M,
                            n_valid_frac=dsm.n_valid_frac),
                   placement=pinfo, decls=D, region_counts=dict(need),
                   z_top_mm=dict(roof=R["z_roof_top_mm"], parapet=R["z_parapet_top_mm"],
                                 stair=R["z_roof_stair_top_mm"], step=R["z_roof_step_top_mm"]),
                   z_roof_median_m=z_roof, tol_m=tol, tol_mad_m=_ref["mad"], roof_levels=lv,
                   roof_level_candidates=lv_big, roof_spread_m=roof_spread, roof_ok=roof_ok,
                   ground_estimators_m=g_est, ground_median_m=g_med, ground_spread_m=g_spread,
                   edge_band_scan=edges,
                   # ★ 全窗「平地按高程分层」普查表 —— 这是本闸给用户的**空间事实**（有哪些面、各在哪），
                   #   不是判据；落进 JSON 才谈得上「判词带着读数」（否则只活在 stdout 里）。
                   flat_by_level=[dict(z=_k, area_m2=round(_a, 1), n=_n,
                                       max_m2=round(_p["area_m2"], 1),
                                       cen_de=round(_se / max(1e-9, _a), 2),
                                       cen_dn=round(_sn / max(1e-9, _a), 2))
                                  for _k, (_a, _n, _p, _se, _sn)
                                  in sorted(_by_level.items(), reverse=True)],
                   # 模型各环自己的栅格质心（与上表「层心」同一把尺子，才可比）
                   ring_centroids=[dict(ring=_nm, area_m2=round(_ma, 1),
                                        cen_de=round(_de, 2), cen_dn=round(_dn, 2))
                                   for (_nm, _ma, _de, _dn) in _mring],
                   # 环平移搜索：只诊断「环圈错地方 vs 楼不止一块面」，**不回写位姿**
                   offset_search=dict(radius_m=OFFSET_SEARCH_M, step_m=OFFSET_STEP_M,
                                      at_zero_m2=(_a0[0][0] if _a0 else None),
                                      best=dict(de=_os[0][2], dn=_os[0][3], max_m2=round(_os[0][0], 1),
                                                z=round(_os[0][1], 2), n_faces=_os[0][4]),
                                      zero_is_max=bool(not (_a0 and _os[0][0] > _a0[0][0] * 1.25)),
                                      note="诊断量，不参与判定、不回写位姿（位姿来自 1 层轮廓独立拟合）"),
                   items=items,
                   n_ok=n_ok, n_bad=n_bad, n_undecided=n_und,
                   aux_ground_ring_m=g_ring, aux_ground_p05_m=g_p05,
                   aux_step_frac_above_ground_plus5=frac_above5,
                   n_controls=len(ctl), n_controls_fired=n_fired, controls=ctl,
                   blind=blind)


if __name__ == "__main__":
    raise SystemExit(main())
