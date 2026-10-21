# -*- coding: utf-8 -*-
r"""J-10.10-10 层高与基准面 —— 三说分辨（步 5 ① 的续：把「分不开」换成「分得开」）

【判据】`J-10.10-08` 把台阶屋面读成 28.103 m、**当时的**模型声明 24.500 m，差 δ = +3.603 m，
  并**当场声明它分不开三件事**（同一个读数，铁律 018）：
  ★ 该 δ 是**旧口径（3500 mm）下的读数**；2026-10-16 用户裁定「按甲定案 · 重算整条链」后
    交付口径改成 4000 mm，同一个面在 `-08` 里现在读 **δ = +0.101 m**。本闸的三把尺子**不受影响**
    （T1 只用**间距**、与声明值无关；T2/T3 各自独立）。

    甲 **层高其实是 4.0 m**       ⇒ 7 层 × 4.0 = 28.0
    乙 **模型 ±0.000 不在实测地面上**（整体抬高 δ）
    丙 **裙房层数少了 1 层**       ⇒ 8 层 × 3.5 = 28.0

  ★ 甲乙丙**在那一块面上给出同一个数**（28.0）⇒ 单块面原理上分不开。本闸换一个量：
  量 **一整族水平面之间的「间距」**，因为
    · **甲 改变的是间距**（相邻整层的差从 3.5 变 4.0）；
    · **乙 只平移，一个间距都不改**（纯偏移 ⇒ 间距尺对 乙 **结构性免疫**）。
  ⇒ 「层高 3.5 还是 4.0」交给**间距尺**判；「δ 是 3.5 还是别的」交给**绝对尺**报；
  再叠第三把与 DSM 无关的尺子：**图纸自己的文字**（12 份 DXF 里有没有标高注记）。
  ★ 三把尺子**分开报、不合成一个 bool**（铁律 174）。

  **被测声明**：`rebuild/构件库/参数.json` 的 `构件.共用/层高 = 4000 mm`（标注 **假设**）。
    ★ 2026-10-16 **口径已翻过一次**：原声明 **3500 mm**，用户裁定「**按甲定案 · 重算整条链**」后改成 4000。
      翻口径的**不是本闸**（本闸三把尺子全在 DSM 上、结构上分不开甲丙）—— 是**另源**的第四把尺子
      `J-10.10-11_裙房层数-轮廓尺度分辨.py`（量 12 份逐层平面图的轮廓尺度，7→8 层之间断崖，三口径 k\* 全 = 7）。
      ⇒ 本闸此后读的是**已裁定的那个值**，它的角色从「裁判」降为「**校验**」：问 4.0 在 DSM 上站不站得住。
  **竞争层高不手打**（铁律 103）：由**甲丙两说的自洽**算出 ——
    甲说「n 层 × H0」、丙说「n+1 层 × h_alt」，两者都必须等于同一个实测标高 ⇒
    `h_alt = H0 × n_podium / (n_podium + 1)`（**与地面无关**，这是间距尺该用的对手）。
    ★★ 旧式是 `H0 × (n+1)/n` —— 它假定**声明是小的那一支**（3500 时确实如此）。声明改成 4000 后，
      旧式会算出 **4571.4 mm**，那不是任何一说的候选（那是「7 层 × 4.571」），属**结构性失效**：
      比例方向错了，出来的对手是个没人提过的数。⇒ 本次翻成 `n/(n+1)` ⇒ h_alt = **3500 mm**（＝丙）。

  **判定**：间距尺下「声明层高 H0 解释掉的间距数」必须**严格多于**`h_alt` 解释掉的，
    且该胜势在 **leave-one-out** 与 **换并层阈/掩膜/门限**下**都不翻** ⇒ **相符**；否则 ⇒ **不符**。
    ★ 两说**打平**、或**胜得不稳**（LOO 一剔就翻 / 换掩膜配置就翻）⇒ **不是「不符」，是 `NOGAUGE`**。
      ★★ 这是 2026-10-16 修的一处**判词映射错**（铁律 197 的对称面 + 199）：
        原版把「ok_claim 不成立」一律印成 `FAIL` —— 可本闸自己的判词会印出
        「**本尺子在这栋楼上分不开两说**（既不能说相符，也不能说已否定）」，
        那**正是 `NOGAUGE` 的定义**（尺子在这件上出不了数）。把「没分开」印成「交付件不合格」，
        就是**拿一把出不了数的尺子去否定交付件** —— 197 明令禁止的形状。
      ⇒ 现分三态：**PASS** ＝ 声明严格胜出且经得起 LOO/换配置；
        **FAIL** ＝ 声明在**全部**配置里都被竞争层高打败（尺子**确实给出了否定**）；
        **NOGAUGE** ＝ 其余（打平 / 胜得脆 / 无赢家常见）—— 尺子出不了数，不裁。

【量具】三把尺子各自独立：

  · **T1 间距尺**（DSM，**对基准面偏移免疫**）：`fly2024_dsm_025.tif`（0.25 m/px，跨仓只读）在
    **模型自己的 1 层轮廓内**、3 m 邻域极差 < `FLAT_TOL_M` 的**平地连通块**，取每块 **DSM 中位**
    （**全精度、不分箱**）为一族面标高；★ 再把这些块**按 z 近邻并成「层」**（见 `levels_of`）——
    0.25 m 栅格下**同一块物理屋面**会被屋顶设备/女儿墙切成好几段、各段中位差 < 0.1 m，
    不并的话间距表里全是 0.02~0.05 m 的假间距。相邻**层**高差记作 `g`；
    对候选层高 `h` 算 `r = min_k |g − k·h|`（`k ≥ 1`），**半格 = mpp/2 = 0.125 m**（由栅格算出，不手打）内算「解释掉」。
    ★ 只用**差值** ⇒ 与地面基准无关 ⇒ **对「基准面偏移」完全免疫**（正对照·丙证明这一点）。

  · **T2 绝对尺**（DSM）：把**面积最大的那一层**的**离地高**与模型 7 层板顶相减得 δ。
    ★ 地面用**三个窄环带**（0–3 / 3–8 / 8–15 m 楼外）各取 **p10**（不是中位：本场地有树有邻栋，
    宽环带的中位被树冠抬走 —— 实测过一次，见「量具盲区」）。
    ★ 另引**跨闸读数** `gates/_out/J-10.10-08.json` 已发布的**三个**地面估计器（在**顶层**键
    `ground_estimators_m`／`ground_median_m`，**不在** `ground` 子对象里 —— 第一版按后者读，
    读到 None 还照样往下跑，是我把键名写错了）。
    ⇒ 「地面估计器**名单**」= 本闸 3 个窄环带 p10 ＋ 跨闸 3 个；**每一个都各算一遍 δ**，
      名单的**极差**就是 T2 的分辨率上界。
    ★★ 名单**不含**「楼内最低层」—— 那是**楼自己的面**（勒脚/台阶，离地 +1.1 m），
      把它算成地面会把分辨率**假性放大**（第一版实测 1.118 m，真值 0.69 m 量级）。
    ★★ 但 δ 这把尺子**结构上分不开甲与丙**：两说预测的是**同一个** δ。这条必须写在判词里。

  · **T3 图纸尺**（与 DSM **无关**）：`rebuild/01_cad/raw/*.dxf` 里找标高类注记，**载体五类**：
    自由文字 `TEXT`/`MTEXT` · **块属性 `ATTRIB`**（标高符号几乎都是「带属性的块」插进来的）·
    **`DIMENSION`**（`text` 与现成的 `measurement` 数）· **图层名** · **块名**
    （`标高 / ±0.000 / EL / 层高 / 檐高 / 屋面 / 室外地坪 / 绝对高程`）。
    ★★ 第一版**只扫 TEXT/MTEXT** 就说「没有标高注记」—— 那等于**把最可能的载体全排除在外**
      还说找不到（铁律 158 的形状）。本版把五类全扫，并逐类报命中数。
    ★ 另出一条**比「有没有命中」更硬**的读数：**这份图纸到底是不是三维的** —— 取到 z 的实体数、
      z 跨度、z ≠ 0 的顶点数、以及**取不到 z 的实体数（单列，不许并进 z=0）**。
      全为二维 ⇒ 「图纸结构上给不出竖向锚」是**确定**的结论，而不是「我的正则没命中」；
      三维却无注记 ⇒ z 的取值本身是唯一载体（本闸不判，另立尺子）。

【量具盲区】本闸对下面这几类**一个字都不给结论**：
  · ★★ **乙（基准面偏移）在两把 DSM 尺子上都否不掉**：间距尺**免疫**偏移（这是它的长处，也正是它的盲）；
    绝对尺里 δ 本来就是乙的自由参数。要否掉乙，必须知道「模型 ±0.000 落在实测地面的哪个高度」——
    而 **DSM 是最高面，永远看不见楼的底面** ⇒ **DSM 结构上给不出竖向锚 h0**。⇒ 这一条**只能由用户裁**。
  · ★★ **T2 的分辨率** = 地面估计器**名单**（本闸 3 个窄环带 p10 ＋ 跨闸 `-08` 的 3 个估计器）的极差。
    名单**不含**「楼内最低层」—— 那是楼自己的勒脚面，不是地面；混进去会把分辨率假性放大。
  · ★★★ **更根本的一条：甲乙丙之争本来就不在 δ 上。** 甲预测 δ = (4.000−3.500)×7 = **+3.500 m**、
    丙预测 δ = 1 层 = **+3.500 m** —— **同一个数**。⇒ **任何**量 δ 的尺子（哪怕分辨率到毫米）
    都分不开甲与丙；而乙把「模型 ±0.000 不在地面上」的偏移量当**自由参数**，对任意 δ 都能吸收
    ⇒ T2 对乙也无分辨力。本闸把 δ 与它在新旧两版地面估计器下的**全部**取值并排报，不挑一个当答案。
  · **族里混着不属于本栋的面**：掩膜是 1 层轮廓，树冠 / 邻栋挑台只要落在轮廓内就算进来；
    配准中位 2.06 m / p90 6.98 m ⇒ 楼脚还会带进一条**地面条带**（读出来就是离地 ≈0 那一层）。
    本闸**不判一块面是不是这栋楼的**，只报面积与质心偏移，并把**两掩膜**×**两面积门限**各报一次。
  · **并层阈是个选择，不是测量**：`MERGE_TOL_M = MERGE_K 格`。太小 ⇒ 假间距复活；太大 ⇒ 真间距被吞。
    本闸把 `MERGE_K ∈ {1,2,4}` 三个阈下**各自的赢家**并排报（铁律 28：选择的代价写旁边）。
  · **0.25 m 格**：半格 0.125 m 以下的差别分不开；两块面靠得比一格还近时会被并成一块。
  · **「台阶屋面是第几层板顶」是推的**（离地高 ÷ 层高），不是量的；本闸不指认层号。
  · 不判纹理、不判材质、不判女儿墙顶、不判楼的底面；只用 DSM 栅格链，看不见 `campus2024.glb` 网格链。

【正对照】（每条落**读数**不只落 bool）—— 全部打在**纯函数** `best_h()` 上，不碰 DSM：
  甲 **合成本身就是 H0 的一族**（间距 7.0 / 3.5 / 3.5）⇒ 赢家必须 = **H0**（分辨力是喂出来的）。
  乙 **合成本身就是 h_alt 的一族**（间距 2h / h / h）⇒ 赢家必须 = **h_alt**，且**不许**是 H0
     —— 这一条同时钉住「尺子认得出真周期」与「尺子不会把对手认成 H0」。
  丙 ★★ **把甲那族的绝对标高整体 +3.603 m 再取间距** ⇒ 间距**逐位不变**、赢家**仍 H0**
     —— 这是「间距尺免疫基准面偏移」的**证明**（同时也是它盲区的证明，铁律 28：代价写旁边）。
  丁 **leave-one-out**：逐个剔掉一个间距重跑 ⇒ 报出**去掉哪一个会翻**（量「赢家靠几个间距赢的」）。
  戊 **喂一组两个层高都落不上的间距**（5.25 / 4.60 / 6.20）⇒ 必须报 **n_ok 全 0 / 无解**，不许硬凑赢家。
  己 **两说混在一族**（H0 / h_alt / H0）⇒ 必须报 **2:1、赢家 H0** —— 量「多数能赢但不一致」。

三态：`RC_PASS=0 / RC_FAIL=1 / RC_NOGAUGE=4`。
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
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
BUILD = os.path.join(REPO, "rebuild", "05_build", "build.json")
MODEL_FP = os.path.join(REPO, "rebuild", "_work", "model_footprint_c006.json")
REGBEST = os.path.join(REPO, "rebuild", "_work", "regbest_1层.json")
DXF_DIR = os.path.join(REPO, "rebuild", "01_cad", "raw")
# ★ 跨仓引用（gym3d 仓）：只读、不搬
DSM = r"D:\项目\gym3d\gym3d\_scratch\c011_fly\_store\fly2024_dsm_025.tif"

HALF_M = 140.0            # 采样窗半宽（楼 129×83.7 m ⇒ 必须罩得住）
FLAT_TOL_M = 1.0          # 「平地」：3 m 邻域极差 < 此值（与 J-10.10-08 同口径）
LEVEL_MIN_AREA = 20.0     # 「一块面」最小面积 m²（与 J-10.10-08 同一个门槛）
ERODE_M = 1.5             # 内缩掩膜：把轮廓边界那一圈（配准误差带）让出去
# ★ 地面环带**收窄**：宽环带在本场地量到的是「地表（树冠/邻栋）」不是「地面」
GND_BANDS_M = ((0.0, 3.0), (3.0, 8.0), (8.0, 15.0))
GND_PCT = 10.0            # 每带取 p10 当「地面」候选（中位会被树冠抬走）；中位**照报**作对照
MERGE_K = 2               # 「层」的并合阈 = MERGE_K 格（0.25 m 格 ⇒ 0.50 m）；敏感性另测 {1,2,4}
MIN_PX = 20               # 连通块最小像素（＝1.25 m²，与面积门限不是一回事）
GND_REF_GATE = os.path.join(OUTDIR, "J-10.10-08.json")   # 跨闸读一个已发布地面值当第三方估计器
ELEV_PAT = re.compile(r"标高|±\s*0?\.000|EL\b|层高|檐高|屋面|室外地坪|绝对高程")
MERGE_SENS = (1, 2, 4)

GID = "J-10.10-10"
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


# ------------------------------------------------------------------ 纯函数：间距尺（正对照全打在它上面）

def gap_fit(gaps, h, half_grid):
    """每个间距 `g` 到 `h` 最近整数倍（k ≥ 1）的残差。返回 (残差表, 残差 ≤ 半格 的个数)。"""
    rs = []
    for g in gaps:
        k = max(1, int(math.floor(g / h + 0.5)))
        rs.append(abs(float(g) - k * float(h)))
    return rs, sum(1 for r in rs if r <= half_grid)


def best_h(gaps, hs, half_grid):
    """候选层高各自的表现 + 赢家。★ 只有**严格**多解释掉一个间距才算赢；打平/全零 ⇒ 赢家 None。"""
    out = {}
    for h in hs:
        rs, n_ok = gap_fit(gaps, h, half_grid)
        out[float(h)] = dict(rs=[float(x) for x in rs], n_ok=int(n_ok),
                             max_r=(float(max(rs)) if rs else None), n_gap=len(rs))
    order = sorted(out, key=lambda h: (-out[h]["n_ok"],
                                       out[h]["max_r"] if out[h]["max_r"] is not None else 1e9))
    win = None
    if order:
        if len(order) == 1 or out[order[0]]["n_ok"] > out[order[1]]["n_ok"]:
            win = float(order[0])
    return out, win


# ------------------------------------------------------------------ 位姿（唯一：regbest_1层.json）

def load_placement():
    """读位姿，**并当场复算 `outline_en` 逐位核对**（铁律 187：基线与期望值两次读数）。"""
    with open(REGBEST, encoding="utf-8") as f:
        R = json.load(f)
    with open(MODEL_FP, encoding="utf-8") as f:
        MF = json.load(f)["1层"]
    P = np.asarray(MF["outline_mm"], float) / 1000.0
    oe = np.asarray(R["outline_en"], float)
    if P.shape != oe.shape:
        return None, "outline_mm 与 outline_en 点数不一致：%s vs %s" % (P.shape, oe.shape)
    t = math.radians(float(R["theta_deg"]))
    Rm = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    c1 = P.mean(0)
    tr = oe.mean(0)
    got = (P - c1) @ Rm.T + tr
    err = float(np.abs(got - oe).max())
    if err > 1e-6:
        return None, ("位姿复算不上：最大差 %.3e m（> 1e-6）⇒ regbest 与 model_footprint 不是同一对" % err)

    def to_en(xy_mm_arr, dx=0.0, dy=0.0):
        q = np.asarray(xy_mm_arr, float) / 1000.0
        return (q - c1) @ Rm.T + tr + np.array([dx, dy])

    info = dict(theta_deg=float(R["theta_deg"]), yflip=R.get("yflip"),
                best_iou=R.get("best_iou"), selfcheck_max_err_m=err,
                boundary_median_m=R.get("boundary_median_m"),
                boundary_p90_m=R.get("boundary_p90_m"),
                tr_en=[float(tr[0]), float(tr[1])],
                outline_en=oe.tolist(), src=os.path.relpath(REGBEST, REPO).replace("\\", "/"))
    return to_en, info


# ------------------------------------------------------------------ 交付侧：层表 / 声明层高 / 构件顶

def load_model():
    """模型自己的一族**候选标高** —— 全部现读交付件，**不手打任何数**。

    ★ 「裙房层数」也不手打：由 `c006_catalog.json` 的 `7层/ROOF_STEP` 块顶 ÷ 声明层高算，
      不是整数就 NOGAUGE（那意味着模型自己不自洽，本闸无从谈起）。
    """
    with open(BUILD, encoding="utf-8") as f:
        B = json.load(f)
    with open(PARAMS, encoding="utf-8") as f:
        storey_mm = float(json.load(f)["构件"]["共用"]["层高"]["值"])
    with open(CATALOG, encoding="utf-8") as f:
        C = json.load(f)
    with open(MODEL_FP, encoding="utf-8") as f:
        MF = json.load(f)

    fl = [f for f in B["floors"] if float(f["z0"]) >= 0.0]        # 地上层
    if not fl:
        return None, "build.json 层表里没有地上层"
    n_tot = len(fl)                                               # 地上总层数（含塔楼）

    def blocks(floor, layer):
        for x in C["floors"]:
            if x["name"] == floor:
                return [b for b in x["blocks"] if b["layer"] == layer], x
        return [], None

    step, f07 = blocks("7层", "ROOF_STEP")
    roof, f11 = blocks("11层", "ROOF")
    if not step or not roof:
        return None, "catalog 里找不到 7层/ROOF_STEP 或 11层/ROOF ⇒ 模型自证不了"

    def ztop(bs, f):
        return max(float(f["z0_mm"]) + float(b["z"]) + float(b["h"]) for b in bs)

    z_step = ztop(step, f07)          # 台阶屋面顶（模型 mm，相对模型 ±0.000）
    z_roof = ztop(roof, f11)          # 塔楼顶
    np_f = z_step / storey_mm
    if abs(np_f - round(np_f)) > 1e-6:
        return None, ("台阶屋面 %d mm ÷ 声明层高 %d mm = %.4f 不是整数 ⇒ 模型自证不了裙房层数"
                      % (z_step, storey_mm, np_f))
    return dict(storey_mm=storey_mm, n_tot=n_tot, n_podium=int(round(np_f)),
                z_step_mm=float(z_step), z_roof_mm=float(z_roof),
                outline1_mm=MF["1层"]["outline_mm"]), None


# ------------------------------------------------------------------ DSM 采样

class Dsm:
    def __init__(self, to_en, ctr):
        self.to_en = to_en
        # ★ 窗口中心**必须**是落位后的质心（＝ outline_en 的质心），**不是** to_en((0,0))——
        #   后者是「模型原点落位后在哪」，离质心 |c1| ≈ 100 m。取错时**不报错、只出错数**。
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
        self.arr = np.where(a <= nod + 1.0, np.nan, a)
        self.shape = self.arr.shape
        self.ctr_px = ((self.shape[0] - 1) / 2.0, (self.shape[1] - 1) / 2.0)
        g = np.isfinite(self.arr)
        self.good = g
        self.n_valid_frac = float(g.mean())
        # ★ 必须先填掉 NaN：maximum_filter 遇 NaN 会把整个邻域染成 NaN（0.8% 的洞 ⇒ 12×12 窗 68% 含 NaN）
        _f = np.where(g, self.arr, float(np.nanmedian(self.arr)))
        k = max(1, int(round(3.0 / self.mpp)))
        self.rng3 = (ndimage.maximum_filter(_f, k, mode="nearest")
                     - ndimage.minimum_filter(_f, k, mode="nearest"))
        self.flat = g & (self.rng3 < FLAT_TOL_M)
        self.half_grid = self.mpp / 2.0     # ★ 半格：由栅格算出，不手打

    def px(self, ring_mm, dx=0.0, dy=0.0):
        en = self.to_en(np.asarray(ring_mm, float).reshape(-1, 2), dx, dy)
        col = (en[:, 0] - self.E_LO) / self.mpp
        row = (self.N_HI - en[:, 1]) / self.mpp
        return list(zip(col.tolist(), row.tolist()))

    def mask(self, rings):
        im = Image.new("L", (self.shape[1], self.shape[0]), 0)
        dr = ImageDraw.Draw(im)
        for r in rings:
            dr.polygon(self.px(r), fill=1)
        return np.asarray(im, bool)


def erode(m, meters, mpp):
    k = int(round(meters / mpp))
    if k <= 0:
        return m.copy()
    return ndimage.binary_erosion(m, structure=np.ones((3, 3), bool), iterations=k, border_value=0)


def dilate(m, meters, mpp):
    k = int(round(meters / mpp))
    if k <= 0:
        return m.copy()
    return ndimage.binary_dilation(m, structure=np.ones((3, 3), bool), iterations=k, border_value=0)


def parts(dsm, m, min_px=MIN_PX):
    """区域里的**平地连通块**清单，按面积降序。

    ★ 读数取「**一块面**」而不是整个区域的中位 —— 一个轮廓里同时躺着屋面板、台阶屋面、屋顶设备、
      以及配准误差带进来的地面条带；它们的**中位**会被拽走、**离散**会变成「区域里所有东西的高度跨度」。
      连通性才是「这一块面」的定义：**一块面只有一个高度，两块面才让中位失效**。
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
                        cen_dn=float((dsm.ctr_px[0] - g[0]) * dsm.mpp),
                        cen_de=float((g[1] - dsm.ctr_px[1]) * dsm.mpp)))
    return out


def levels_of(fam, tol):
    """把「平地连通块」按 z **单链**近邻（阈 `tol`）并成「层」。

    ★ 必须有这一步（本闸第一版漏了，症状：间距表里 0.047/0.028/0.024/0.021 一片假间距、
      真间距被淹，两说都 0/14）：0.25 m 栅格下**同一块物理屋面**会被屋顶设备/女儿墙切成好几段，
      各段中位只差 0.074 m —— 那不是两个标高，是同一块面。
    ★ tol 的两端：下界 = 1 格（同面切片的抖动 < 1 格）；上界 ≪ 最小可能层高（3.5 m）。
      它是一个**选择**不是测量 ⇒ 本闸另把 {1,2,4} 格三个阈下各自的赢家并排报（铁律 28）。
    """
    out = []
    for p in sorted(fam, key=lambda q: q["z"]):
        if out and abs(p["z"] - out[-1]["z_last"]) <= tol:
            out[-1]["planes"].append(p)
            out[-1]["z_last"] = p["z"]
        else:
            out.append(dict(z_last=p["z"], planes=[p]))
    for L in out:
        zz = [q["z"] for q in L["planes"]]
        L["z"] = float(np.median(zz))
        L["n_plane"] = len(zz)
        L["area_m2"] = float(sum(q["area_m2"] for q in L["planes"]))
        L["span_m"] = float(max(zz) - min(zz))
        L["cen_de"] = float(np.mean([q["cen_de"] for q in L["planes"]]))
        L["cen_dn"] = float(np.mean([q["cen_dn"] for q in L["planes"]]))
        del L["z_last"], L["planes"]
    return out


def ground_estimators(dsm, M1):
    """楼外三圈**窄**环带的地面标高候选。★ 每带同时报 p10 与 p50。

    ★ 为什么不用中位：本场地**有树、有邻栋**，DSM 是「地表」模型 ⇒ 环带里很大一部分像素是
      树冠/邻栋屋面（实测：宽环带 6–20 m 的中位 475.9 m，而楼脚平地只有 465.6 m ⇒ 被抬了 10 m）。
      p10 取的是「这片环带的低处」，才是地面的候选。中位**照报**，好让人看见它被抬了多少。
    ★ 三个带都报，把 p10 的**跨度**算进绝对尺容差（铁律 103：期望值由实测算出）。
    """
    out = {}
    for lo, hi in GND_BANDS_M:
        m = dilate(M1, hi, dsm.mpp) & ~dilate(M1, lo, dsm.mpp)
        v = dsm.arr[m & dsm.good]
        key = "%g-%gm" % (lo, hi)
        out[key] = dict(n=int(v.size),
                        p10=(None if v.size < 50 else float(np.percentile(v, GND_PCT))),
                        p50=(None if v.size < 50 else float(np.median(v))))
    p10s = [d["p10"] for d in out.values() if d["p10"] is not None]
    p50s = [d["p50"] for d in out.values() if d["p50"] is not None]
    if not p10s:
        return out, None, None, None
    return (out, float(np.median(p10s)),
            float(max(p10s) - min(p10s)),
            (float(max(p50s) - min(p50s)) if p50s else None))


def cross_gate_ground():
    """★ 跨闸引用：`J-10.10-08` 已发布的**地面读数**，当**另外几个独立估计器**。

    它**不是**「更权威的答案」，是**另几个估计器** —— 全部并排报，它们的**极差**就是 T2 的分辨率上界。
    ★ 键名按**实测**：`-08` 把地面读数放在**顶层**（`ground_estimators_m` / `ground_median_m` /
      `ground_spread_m`），**不在 `ground` 子对象里**。第一版按 `J["ground"][...]` 读 ⇒ 读到 None，
      **而它照样往下跑**、只在日志里印一行「读不到」——
      症状像个无害的小缺口，其实是我把键名写错了（铁律 199：「读不到」必须把
      **「键名错了」**与**「那份闸确实没发布」**分开报，否则两者同形）。
    """
    src = os.path.basename(GND_REF_GATE)
    try:
        with open(GND_REF_GATE, encoding="utf-8") as f:
            J = json.load(f)
    except Exception as e:
        return dict(ok=False, z=None, spread=None, zs=[],
                    why="**读不到文件**：%s" % e, src=src)
    g = J.get("ground") if isinstance(J.get("ground"), dict) else {}
    z_med = J.get("ground_median_m", g.get("ground_median_m"))
    spr = J.get("ground_spread_m", g.get("ground_spread_m"))
    zs = [float(x) for x in (J.get("ground_estimators_m") or []) if x is not None]
    if z_med is None and not zs:
        return dict(ok=False, z=None, spread=None, zs=[],
                    why="**文件读到了，但里面没有地面读数** ｜ 顶层键 = %s"
                        % ",".join(list(J)[:14]), src=src)
    return dict(ok=True, why=None, z=(None if z_med is None else float(z_med)),
                spread=(None if spr is None else float(spr)), zs=zs, src=src)


# ------------------------------------------------------------------ T3 图纸尺（与 DSM 无关）

_Z_ATTRS = (
    ("LINE", ("start", "end")),
    ("3DFACE", ("vtx0", "vtx1", "vtx2", "vtx3")),
    ("SOLID", ("vtx0", "vtx1", "vtx2", "vtx3")),
    ("TEXT", ("insert",)),
    ("MTEXT", ("insert",)),
    ("INSERT", ("insert",)),
    ("CIRCLE", ("center",)),
    ("ARC", ("center",)),
    ("POINT", ("location",)),
    ("DIMENSION", ("defpoint", "defpoint2", "defpoint3", "text_midpoint")),
)


def _zs_of(e):
    """尽力取一个实体的 z 值清单。★ 取不到就返回**空表** —— **不许**当成 z=0（铁律 199）。"""
    out, t = [], e.dxftype()
    for name, attrs in _Z_ATTRS:
        if name != t:
            continue
        for a in attrs:
            v = getattr(e.dxf, a, None)
            if v is None:
                continue
            try:
                out.append(float(v[2]))
            except Exception:
                pass
    if t == "LWPOLYLINE":
        try:
            out.append(float(e.dxf.elevation))
        except Exception:
            pass
    if t == "POLYLINE":
        try:
            for v in e.vertices:
                out.append(float(v.dxf.location[2]))
        except Exception:
            pass
    return out


def scan_dxf_text():
    """12 份 DXF 里找**标高载体** —— 与 DSM **不同源**，是第三把独立的尺子。

    ★★ 载体名单**必须是宽的**（铁律 158：**否定**判词必须声明量具对哪几类元素不盲）。
      第一版只扫 `TEXT`/`MTEXT` 两种自由文字，就下「图纸里没有标高注记」——
      而 CAD 里的标高注记**最常见**的载体恰恰**不是**自由文字：

        · **块属性** `ATTRIB`（标高符号几乎都是「带属性的块」插入的）
        · **尺寸标注** `DIMENSION`（本身带 `measurement` ＝ **现成的数字**）
        · **图层名 / 块名**（`标高` / `EL` / `BM` / `室外` …）

      ⇒ 只扫自由文字，等于**把最可能的载体全排除在外还说「找不到」**（这正是铁律 158 的形状）。
    ★★ 再加一条**比「有没有命中」更硬的**读数：**图纸到底是不是三维的**。
      若全部实体 z ≡ 0，则这份图纸**结构上**不携带任何竖向信息 —— 「本支不出数」就是
      **确定的**结论，而不是「我的正则没命中」。反之若 z 有跨度，z 的**取值本身**就是高程载体。
      ★ 取不到 z 的实体**单独计数**（`n_ent_z_unknown`），不许并进 z=0（铁律 199）。
    """
    try:
        import ezdxf  # noqa: PLC0415
    except Exception as e:                                     # pragma: no cover
        return dict(ok=False, why="ezdxf 没装上：%s" % e, n_text=0, n_hit=0, hits=[])
    fs = sorted(glob.glob(os.path.join(DXF_DIR, "*.dxf")))
    if not fs:
        return dict(ok=False, why="%s 下一份 dxf 都没有" % DXF_DIR, n_text=0, n_hit=0, hits=[])

    census, hits, layers, blocks = {}, [], set(), set()
    n_text = n_ent = n_z_ent = n_z_unknown = 0
    n_dim_meas = n_dim_bad = 0
    z_abs_max = 0.0
    z_vals: list[float] = []

    def _hit(kind, f, layer, s):
        """★★ 这里**必须**过一遍 `ELEV_PAT` —— 第一版忘了，`_hit()` 变成**无条件入账**，
        于是 `n_hit == n_text`（1853 == 1853）、**判词变成「命中 1853 条」**。
        症状不是报错，是**这把尺子对任何输入都报「有」**（铁律 137：判据有无分辨力，
        必须喂**确有缺陷**的输入去试；铁律 183：同形状换个函数还会再犯）。"""
        if not ELEV_PAT.search(s or ""):
            return False
        hits.append(dict(kind=kind, file=os.path.basename(f),
                         layer=str(layer), text=(s or "")[:120]))
        return True

    for f in fs:
        try:
            doc = ezdxf.readfile(f)
            msp = doc.modelspace()
        except Exception as e:
            return dict(ok=False, why="%s 读不了：%s" % (os.path.basename(f), e),
                        n_text=n_text, n_hit=0, hits=[])
        layers.update(str(x.dxf.name) for x in doc.layers)
        blocks.update(str(b.name) for b in doc.blocks)
        for e in msp:
            n_ent += 1
            t = e.dxftype()
            census[t] = census.get(t, 0) + 1
            layer = getattr(e.dxf, "layer", "")
            # --- 载体 1/2：自由文字
            if t == "TEXT":
                n_text += 1
                _hit("TEXT", f, layer, e.dxf.text)
            elif t == "MTEXT":
                n_text += 1
                _hit("MTEXT", f, layer, e.text)
            # --- 载体 3：块属性（标高符号几乎都是带属性的块）
            elif t == "INSERT":
                for a in getattr(e, "attribs", ()) or ():
                    n_text += 1
                    _hit("ATTRIB@%s" % str(e.dxf.name), f, a.dxf.layer, a.dxf.text)
            # --- 载体 4：尺寸标注（带现成的 measurement）
            #     ★ measurement 只是一个**长度数字**（4000 是墙长还是标高？本尺子分不开）
            #       ⇒ 它**算载体、不算命中**：只记数，命中仍必须靠 `ELEV_PAT` 落在文字上。
            elif t == "DIMENSION":
                n_text += 1
                _hit("DIMENSION(text)", f, layer, e.dxf.text)
                try:
                    float(e.get_measurement())
                    n_dim_meas += 1
                except Exception:
                    n_dim_bad += 1
            # --- z：这份图纸到底有没有竖向信息
            zz = _zs_of(e)
            if not zz:
                n_z_unknown += 1
            else:
                n_z_ent += 1
                m = max(abs(v) for v in zz)
                z_abs_max = max(z_abs_max, m)
                z_vals.extend(zz)
    n_z_nonzero = sum(1 for v in z_vals if abs(v) > 1e-6)
    n_layer_hit = sum(1 for x in layers if ELEV_PAT.search(x))
    n_block_hit = sum(1 for x in blocks if ELEV_PAT.search(x))
    for x in sorted(layers):
        if ELEV_PAT.search(x):
            _hit("LAYER", "-", x, x)
    for x in sorted(blocks):
        if ELEV_PAT.search(x):
            _hit("BLOCK", "-", x, x)
    return dict(ok=True, why=None, n_dxf=len(fs), n_ent=int(n_ent),
                census={k: int(v) for k, v in sorted(census.items(), key=lambda kv: -kv[1])},
                n_text=int(n_text), n_hit=len(hits), hits=hits[:24],
                n_z_ent=int(n_z_ent), n_ent_z_unknown=int(n_z_unknown),
                z_abs_max_m=float(z_abs_max), n_z_nonzero=int(n_z_nonzero),
                z_min=(None if not z_vals else float(min(z_vals))),
                z_max=(None if not z_vals else float(max(z_vals))),
                n_layer=int(len(layers)), n_block=int(len(blocks)),
                n_layer_hit=int(n_layer_hit), n_block_hit=int(n_block_hit),
                n_dim_meas=int(n_dim_meas), n_dim_bad=int(n_dim_bad))


def t3_positive_control():
    """★ T3 的**正对照**（铁律 137/183）：喂**确有缺陷**的输入，看这把尺子分不分得开。

    第一版 `_hit()` 无条件入账 ⇒ 对**任何**字符串都报「命中」，而正对照**只打在 T1 上**，
    于是这个缺陷一路走到判词里（「命中 1853 条」）。⇒ 本尺子必须自带正/负两例。
    """
    must = [("±0.000 室外地坪", True), ("标高 28.000", True), ("檐高 44.0", True),
            ("EL. +3.600", True), ("绝对高程 464.55", True), ("屋面结构标高", True)]
    must_not = [("4.2墙体            上", False), ("WINDOW_TEXT", False),
                ("10层.dxf", False), ("C25 混凝土", False), ("", False),
                ("KZ1 400x400", False), ("ELEVATOR", False)]
    bad = []
    for s, want in must + must_not:
        got = bool(ELEV_PAT.search(s))
        if got != want:
            bad.append(dict(s=s, want=want, got=got))
    return dict(ok=(not bad),
                n=len(must) + len(must_not), n_pos=len(must), n_neg=len(must_not),
                n_bad=len(bad), bad=bad, ctl=[dict(s=s, want=w, got=bool(ELEV_PAT.search(s)))
                                              for s, w in must + must_not])


# ------------------------------------------------------------------ 主

def main() -> int:
    to_en, pinfo = load_placement()
    if to_en is None:
        log("★ 位姿没读成：%s" % pinfo)
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE（尺子本身没立起来）" % GID)
        return _finish(RC_NOGAUGE, reason=pinfo, blind=["位姿读错 ⇒ 本闸拒绝出任何读数"])

    M, why = load_model()
    if M is None:
        log("★ 交付侧读不成：%s" % why)
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason=why, blind=["模型自己不自洽 ⇒ 本闸无从谈起"])

    H0 = M["storey_mm"] / 1000.0
    # ★ 竞争层高**不手打**（铁律 103）：由甲丙两说的**自洽**算出，且**与地面无关** ——
    #   甲说「n 层 × H0」、丙说「n+1 层 × h_alt」，两者都必须等于同一个实测标高 ⇒
    #   h_alt = H0 × n_podium / (n_podium + 1)。间距尺只用差值 ⇒ 它的对手也必须与地面无关。
    #   ★★ 2026-10-16 口径翻转：声明由 3500 改 4000（用户裁定「按甲定案 · 重算整条链」）⇒
    #      **声明变成大的那一支**，旧的 (n+1)/n 会算出 4571.4 mm（没有任何一说提过这个数）
    #      ⇒ 结构性失效：比例方向反了。本次改成 n/(n+1) ⇒ h_alt = 3500 mm（＝丙）。
    h_alt = H0 * M["n_podium"] / (M["n_podium"] + 1.0)
    H = [H0, h_alt]

    log("%s 层高与基准面 —— 三说分辨" % GID)
    log("  仓: %s" % REPO)
    log("  位姿 %s（转角 %.4f°，复算最大差 %.3e m）"
        % (pinfo["src"], pinfo["theta_deg"], pinfo["selfcheck_max_err_m"]))
    log("  交付侧：声明层高 %.3f m（假设）｜地上 %d 层｜台阶屋面顶 %.3f m（模型 mm 相对 ±0.000）"
        " ⇒ 裙房 %d 层｜塔楼顶 %.3f m"
        % (H0, M["n_tot"], M["z_step_mm"] / 1000.0, M["n_podium"], M["z_roof_mm"] / 1000.0))
    log("  竞争层高 h_alt = %.3f × %d/(%d+1) = **%.4f m**（甲丙两说自洽算出，与地面无关）"
        % (H0, M["n_podium"], M["n_podium"], h_alt))

    dsm = Dsm(to_en, pinfo["tr_en"])
    MERGE_TOL_M = MERGE_K * dsm.mpp
    log("\nDSM：%s ｜ %s ｜ %.2f m/px ｜ 窗口 %d×%d ｜ 有效 %.1f%% ｜ 半格 %.3f m ｜ 并层阈 %d 格 = %.3f m"
        % (os.path.basename(DSM), dsm.crs, dsm.mpp, dsm.shape[1], dsm.shape[0],
           100 * dsm.n_valid_frac, dsm.half_grid, MERGE_K, MERGE_TOL_M))

    _oe = np.asarray(pinfo["outline_en"], float)
    _me = np.asarray(to_en(np.asarray(M["outline1_mm"], float).reshape(-1, 2)), float)
    _allp = np.vstack([_oe, _me])
    if not (dsm.E_LO <= _allp[:, 0].min() and _allp[:, 0].max() <= dsm.E_HI
            and dsm.N_LO <= _allp[:, 1].min() and _allp[:, 1].max() <= dsm.N_HI):
        log("★ 窗口没罩住轮廓 ⇒ 尺子没立对，不出读数")
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason="采样窗没罩住轮廓（中心/位姿错）",
                       blind=["窗口没罩住被测物 ⇒ 拒绝出读数"])

    # ---------------------------------------------------------- 三个地面估计器 + 跨闸参照
    M1 = dsm.mask([M["outline1_mm"]])
    gnd, G, G_SPREAD, G_SPREAD50 = ground_estimators(dsm, M1)
    xg = cross_gate_ground()
    log("\n地面估计器（楼外窄环带 p10；中位一并报，好看见被树/邻栋抬了多少）：")
    for k, d in gnd.items():
        log("    %-8s p10=%s  p50=%s  n=%d"
            % (k, ("%.3f" % d["p10"]) if d["p10"] is not None else "未量到",
               ("%.3f" % d["p50"]) if d["p50"] is not None else "未量到", d["n"]))
    if xg["ok"]:
        log("    跨闸 %s：中位 %.3f m ｜ 它自己那批估计器 %s（它自报跨度 %s）"
            % (xg["src"], xg["z"],
               (" / ".join("%.3f" % v for v in xg["zs"])) if xg["zs"] else "未发布",
               "未发布" if xg["spread"] is None else "%.3f" % xg["spread"]))
    else:
        log("    跨闸 %s：%s" % (xg["src"], xg["why"]))
    if G is None:
        log("★ 三个环带一个都没量到 ⇒ 绝对尺立不起来")
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason="地面估计器全空", ground=gnd,
                       blind=["没有地面基准 ⇒ 绝对尺不出数"])
    log("  ⇒ 本次取 G = p10 的中位 = %.3f m ｜ p10 跨度 %.3f m ｜ p50 跨度 %s m"
        % (G, G_SPREAD, "未量到" if G_SPREAD50 is None else "%.3f" % G_SPREAD50))
    # ★ 「地面估计器」的**名单**（铁律 137：名单漏掉主体则判据永远绿）：
    #   本闸三个窄环带的 p10 ＋ 跨闸 `-08` 已发布的那几个估计器。
    #   ★★ 名单**不含**「楼内最低层」—— 那是**楼自己的面**（离地 +1.1 m 的勒脚/台阶），**不是地面**。
    #     第一版把它也算成「换地面」，于是 T2 的分辨率上界从真值被抬到 1.118 m：
    #     症状是「读起来像尺子很粗」，真因是**我把一把不是地面的尺子放进了地面名单**。
    #     本版把它**另列**并逐字标「不是地面」，只当参照。
    gnd_zs = ([float(d["p10"]) for d in gnd.values() if d["p10"] is not None]
              + [float(v) for v in xg.get("zs", [])])
    log("  ★ 地面估计器名单（%d 个）：%s"
        % (len(gnd_zs), " / ".join("%.3f" % v for v in gnd_zs)))

    # ---------------------------------------------------------- 平地族（两掩膜 × 两门限）
    VARIANTS = [("轮廓", M1, LEVEL_MIN_AREA), ("轮廓·小面", M1, 0.0),
                ("内缩%.1fm" % ERODE_M, erode(M1, ERODE_M, dsm.mpp), LEVEL_MIN_AREA),
                ("内缩%.1fm·小面" % ERODE_M, erode(M1, ERODE_M, dsm.mpp), 0.0)]
    fams, lvls = {}, {}
    for name, mk, amin in VARIANTS:
        ps = [p for p in parts(dsm, mk) if p["area_m2"] >= amin]
        fams[name] = ps
        ls = levels_of(ps, MERGE_TOL_M)
        lvls[name] = ls
        log("\n[平地族·%s] %d 块面（≥ %.0f m²）⇒ 并成 **%d 层**（阈 %.3f m）"
            % (name, len(ps), amin, len(ls), MERGE_TOL_M))
        for L in ls:
            log("    层 z=%.3f  离地 %8.3f m ｜ %8.1f m² ｜ 由 %d 块面并成（内跨 %.3f m）"
                " ｜ 质心离楼心 (E%+.1f, N%+.1f) m"
                % (L["z"], L["z"] - G, L["area_m2"], L["n_plane"], L["span_m"],
                   L["cen_de"], L["cen_dn"]))

    MAIN = "轮廓"
    fam, lv = fams[MAIN], lvls[MAIN]
    if len(lv) < 2:
        log("\n★ %s 掩膜下「层」不足 2 个（%d）⇒ 间距尺立不起来" % (MAIN, len(lv)))
        log("===== 判词 =====")
        log("%s 总判 : NOGAUGE" % GID)
        return _finish(RC_NOGAUGE, reason="层不足 2 个", n_level=len(lv),
                       families={k: len(v) for k, v in fams.items()},
                       blind=["族里少于两层 ⇒ 没有间距可量"])

    gaps = [float(lv[i + 1]["z"] - lv[i]["z"]) for i in range(len(lv) - 1)]

    # ---------------------------------------------------------- T2 绝对尺
    top = max(lv, key=lambda L: L["area_m2"])           # 面积最大的那一层（＝裙房屋面）
    top_ag = float(top["z"] - G)
    delta = float(top_ag - M["z_step_mm"] / 1000.0)
    gr, gs = float(top["z"]), float(M["z_step_mm"] / 1000.0)
    # ★ 名单里**每一个**地面估计器各算一遍 δ（不是一个，也不是挑一个）
    delta_by_g = {"地面 %.3f" % v: float(gr - v - gs) for v in gnd_zs}
    d_span = (max(gnd_zs) - min(gnd_zs)) if len(gnd_zs) >= 2 else None
    d_delta_span = ((max(delta_by_g.values()) - min(delta_by_g.values()))
                    if len(delta_by_g) >= 2 else None)
    # ★ 楼脚那条低平台**另列**（它不是地面，是楼自己的面）：只作参照报，不进地面名单
    lows = [L for L in lv if (L["z"] - G) < 3.0 and L is not top]
    low_ref = None
    if lows:
        _L0 = max(lows, key=lambda L: L["z"])
        low_ref = dict(z=float(_L0["z"]), above_ground_m=float(_L0["z"] - G),
                       delta_if_used_as_datum_m=float(gr - _L0["z"] - gs))
    # ★★ 两条候选的 δ 预测（2026-10-16 重写）。δ ≡ 实测屋面高 − **交付口径声明的屋面高**。
    #   甲（本闸的被测声明）= n 层 × H0；丙（竞争）= (n+1) 层 × h_alt。
    #   ★ 两个**总高**由 h_alt 的构造保证相等 ⇒ 两条候选预测**同一个 δ**
    #     —— 这正是铁律 018 的形状：两说给出同一个读数，任何量 δ 的尺子都分不开它俩。
    tot_decl = float(H0 * M["n_podium"])             # 甲的总高（现算，不手打）
    tot_alt = float(h_alt * (M["n_podium"] + 1))     # 丙的总高（现算，不手打）
    pred_jia = float(tot_decl - tot_decl)            # 甲：真实总高 = 声明总高 ⇒ δ = 0
    pred_bing = float(tot_alt - tot_decl)            # 丙：真实总高 = 竞争总高，声明仍是 tot_decl
    _in = None

    log("\n[T2 绝对尺] 面积最大的一层：%.1f m²（由 %d 块面并成）｜ 离地 %.3f m ｜ 模型 7 层板顶 %.3f m"
        % (top["area_m2"], top["n_plane"], top_ag, gs))
    log("  ⇒ **δ = %+.4f m**（本次 G）" % delta)
    for k, v in delta_by_g.items():
        log("     换地面 %-16s ⇒ δ = %+.4f m" % (k, v))
    if low_ref is not None:
        log("     ★ 楼内最低层（z=%.3f，离地 %+.3f m）**不是地面**（是楼脚勒脚/台阶）⇒ 只作参照："
            "若拿它当基准则 δ = %+.4f m —— **不进地面名单**，否则分辨率会被假性放大"
            % (low_ref["z"], low_ref["above_ground_m"], low_ref["delta_if_used_as_datum_m"]))
    log("  ⇒ ★ T2 的**分辨率上界** = 地面名单极差 = **%s m**（%d 个估计器%s）"
        % ("未量到" if d_span is None else "%.3f" % d_span, len(gnd_zs),
           "，少于 2 个 ⇒ 估不出上界" if d_span is None
           else "，δ 同幅 %s m" % ("未量到" if d_delta_span is None else "%.3f" % d_delta_span)))
    log("  甲（声明）总高 = %.3f × %d = %.3f m ｜ 丙（竞争）总高 = %.4f × %d = %.3f m"
        % (H0, M["n_podium"], tot_decl, h_alt, M["n_podium"] + 1, tot_alt))
    log("  甲 预测 δ = %+.4f m ｜ 丙 预测 δ = %+.4f m" % (pred_jia, pred_bing))
    _same = abs(pred_jia - pred_bing) < 1e-9
    log("  ★ %s ⇒ %s；乙 对**任意** δ 都能吸收 ⇒ **T2 对乙无分辨力**（如实报，不假装量到了）"
        % ("甲与丙预测**同一个数**（两个总高构造上相等）" if _same
           else "★ 两说这次预测**不同的数**（差 %+.4f m）⇒ T2 可分开" % (pred_bing - pred_jia),
           "**任何量 δ 的尺子都分不开它俩**" if _same else "T2 对甲丙**有**分辨力"))
    if delta_by_g:
        _lo, _hi = min(delta_by_g.values()), max(delta_by_g.values())
        _in = bool(_lo <= pred_jia <= _hi and _lo <= pred_bing <= _hi)
        log("  ★ 实测 δ 覆盖 [%+.4f, %+.4f] m ⇒ 甲 %+.4f 与 丙 %+.4f **%s**"
            % (_lo, _hi, pred_jia, pred_bing,
               "都落在带内（T2 与两说都不矛盾，也分不开）" if _in
               else "至少一个落在带外（T2 与那一说相矛盾）"))

    # ---------------------------------------------------------- T1 间距尺
    log("\n[T1 间距尺] 层间高差（按高度排序）：%s" % " / ".join("%.3f" % g for g in gaps))
    fit, win = best_h(gaps, H, dsm.half_grid)
    for h in H:
        f = fit[h]
        log("  h=%.4f m ⇒ 解释掉 %d/%d ｜ 残差 %s"
            % (h, f["n_ok"], f["n_gap"], " ".join("%.3f" % r for r in f["rs"])))
    log("  ⇒ 赢家 = %s" % ("**%.4f m**" % win if win is not None else "**（打平/无解，没有赢家）**"))

    loo = []
    for i in range(len(gaps)):
        g2 = [g for j, g in enumerate(gaps) if j != i]
        f2, w2 = best_h(g2, H, dsm.half_grid)
        loo.append(dict(dropped_gap=float(gaps[i]),
                        n_ok_H0=int(f2[H0]["n_ok"]), n_ok_alt=int(f2[h_alt]["n_ok"]),
                        winner=(None if w2 is None else float(w2)),
                        flipped=bool((w2 is None) != (win is None)
                                     or (w2 is not None and win is not None and abs(w2 - win) > 1e-9))))
    n_flip = sum(1 for r in loo if r["flipped"])
    log("  [leave-one-out] %d 种剔法，翻盘 %d 种：" % (len(loo), n_flip))
    for r in loo:
        log("    剔掉 %.3f ⇒ %.3f 解 %d / %.4f 解 %d ｜ 赢家 %s%s"
            % (r["dropped_gap"], H0, r["n_ok_H0"], h_alt, r["n_ok_alt"],
               "无" if r["winner"] is None else "%.4f" % r["winner"],
               "  ← **翻**" if r["flipped"] else ""))

    # ---------------------------------------------------------- 并层阈 + 掩膜/门限 敏感性
    sens = {}
    for k in MERGE_SENS:
        ls = levels_of(fam, k * dsm.mpp)
        zz = [L["z"] for L in ls]
        g2 = [float(zz[i + 1] - zz[i]) for i in range(len(zz) - 1)]
        if not g2:
            sens["%d格" % k] = dict(tol_m=float(k * dsm.mpp), n_level=len(ls), n_gap=0, winner=None)
            continue
        f2, w2 = best_h(g2, H, dsm.half_grid)
        sens["%d格" % k] = dict(tol_m=float(k * dsm.mpp), n_level=len(ls), n_gap=len(g2),
                                n_ok_H0=int(f2[H0]["n_ok"]), n_ok_alt=int(f2[h_alt]["n_ok"]),
                                winner=(None if w2 is None else float(w2)),
                                gaps=[round(x, 3) for x in g2])
    variants_t1 = {}
    for name, ps in fams.items():
        ls = lvls[name]
        z2 = [L["z"] for L in ls]
        g2 = [float(z2[i + 1] - z2[i]) for i in range(len(z2) - 1)]
        if not g2:
            variants_t1[name] = dict(n_level=len(ls), n_gap=0, winner=None)
            continue
        f2, w2 = best_h(g2, H, dsm.half_grid)
        variants_t1[name] = dict(n_level=len(ls), n_gap=len(g2),
                                 n_ok_H0=int(f2[H0]["n_ok"]),
                                 n_ok_alt=int(f2[h_alt]["n_ok"]),
                                 winner=(None if w2 is None else float(w2)),
                                 gaps=[round(x, 3) for x in g2])
    log("\n[并层阈敏感性]（同一掩膜 %s，只改并层阈）" % MAIN)
    for name, v in sens.items():
        log("  %-5s 阈%-6s %2d 层 / %2d 间距 ｜ %.3f 解 %s ｜ %.4f 解 %s ｜ 赢家 %s"
            % (name, "%.2fm" % v.get("tol_m", 0.0), v["n_level"], v["n_gap"], H0,
               v.get("n_ok_H0", "-"), h_alt, v.get("n_ok_alt", "-"),
               "无" if v.get("winner") is None else "%.4f" % v["winner"]))
    log("\n[掩膜/门限稳定性]（并层阈固定 %d 格）" % MERGE_K)
    for name, v in variants_t1.items():
        log("  %-14s %2d 层 / %2d 间距 ｜ %.3f 解 %s ｜ %.4f 解 %s ｜ 赢家 %s"
            % (name, v["n_level"], v["n_gap"], H0, v.get("n_ok_H0", "-"), h_alt,
               v.get("n_ok_alt", "-"),
               "无" if v.get("winner") is None else "%.4f" % v["winner"]))
    winners = [v.get("winner") for v in list(sens.values()) + list(variants_t1.values())]
    n_win_H0 = sum(1 for w in winners if w is not None and abs(w - H0) < 1e-9)
    n_win_alt = sum(1 for w in winners if w is not None and abs(w - h_alt) < 1e-9)
    n_win_none = sum(1 for w in winners if w is None)
    n_cfg = len(winners)
    log("  ⇒ %d 种配置里：%.3f 赢 %d ｜ %.4f 赢 %d ｜ 无赢家 %d"
        % (n_cfg, H0, n_win_H0, h_alt, n_win_alt, n_win_none))

    # ---------------------------------------------------------- T3 图纸尺
    dx = scan_dxf_text()
    t3pc = t3_positive_control()
    log("\n[T3 图纸尺] %s 份 DXF ｜ 实体 %d 个 ｜ 文字类载体 %d 条"
        % (dx.get("n_dxf", 0), dx.get("n_ent", 0), dx["n_text"]))
    if dx.get("census"):
        log("    实体类型普查（前 8）：%s"
            % " ｜ ".join("%s=%d" % (k, v) for k, v in list(dx["census"].items())[:8]))
    log("    ★ 载体覆盖：TEXT / MTEXT / **ATTRIB（块属性）** / **DIMENSION** /"
        " **图层名** / **块名** ｜ 图层 %d 个、块 %d 个"
        % (dx.get("n_layer", 0), dx.get("n_block", 0)))
    log("      ★ DIMENSION 的 `measurement` 只是**一个长度数字**（4000 是墙长还是标高？"
        "本尺子分不开）⇒ 它**算载体不算命中**：%d 条取到、%d 条取不到（分开计）"
        % (dx.get("n_dim_meas", 0), dx.get("n_dim_bad", 0)))
    log("    ★ 竖向信息：取到 z 的实体 %d 个（z 跨度 %s）｜取不到 z 的 %d 个（**单独计数**，不算 z=0）"
        % (dx.get("n_z_ent", 0),
           "无" if dx.get("z_min") is None else "%.6g ~ %.6g" % (dx["z_min"], dx["z_max"]),
           dx.get("n_ent_z_unknown", 0)))
    log("      其中 z ≠ 0 的顶点 %d 个 ｜ |z| 最大 %.6g" % (dx.get("n_z_nonzero", 0),
                                                          dx.get("z_abs_max_m", 0.0)))
    if not dx["ok"]:
        log("  ⇒ 本支**不出数**（%s）" % dx["why"])
    else:
        log("    标高类命中 %d 条（其中图层名 %d ｜ 块名 %d）"
            % (dx["n_hit"], dx.get("n_layer_hit", 0), dx.get("n_block_hit", 0)))
        for h in dx["hits"][:10]:
            log("      [%s] %s ｜ %-16s %s" % (h["kind"], h["file"], h["layer"], h["text"]))
        if dx["n_hit"] == 0 and dx.get("n_z_nonzero", 0) == 0:
            log("  ⇒ ★★ **这份图纸是二维的**：取到 z 的 %d 个实体里，z ≠ 0 的顶点 **0** 个"
                % dx.get("n_z_ent", 0))
            log("     ⇒ 「图纸结构上给不出竖向锚」是**确定的**结论，不是「我的正则没命中」——"
                "本尺子已把 自由文字/块属性/尺寸标注/图层名/块名 **五类载体**全扫过。")
        elif dx["n_hit"] == 0:
            log("  ⇒ ★ 图纸**是三维的**（z ≠ 0 的顶点 %d 个，z 跨度 %s），却**没有一条标高注记**"
                % (dx.get("n_z_nonzero", 0),
                   "无" if dx.get("z_min") is None else "%.6g ~ %.6g" % (dx["z_min"], dx["z_max"])))
            log("     ⇒ z 的**取值本身**是这里唯一的竖向载体，要另立一把尺子去判（本闸不判）")
        log("     ⇒ 对「层高是多少」，本支%s"
            % ("**不出数**（如实报，不装成量到了）" if dx["n_hit"] == 0 else "**出了数**（见上）"))
    log("    ★ 本尺子自己的正/负对照（%d 例，%d 正 %d 负）：%s"
        % (t3pc["n"], t3pc["n_pos"], t3pc["n_neg"],
           "**全按预期**" if t3pc["ok"] else "**有 %d 例不符** ⇒ 尺子本身有问题"
           % t3pc["n_bad"]))
    for b in t3pc["bad"]:
        log("      ✗ 「%s」 期望 %s 实得 %s" % (b["s"], b["want"], b["got"]))

    # ---------------------------------------------------------- 正对照（纯函数）
    ctl = []

    def _ctl(nm, expect, got, ok):
        ctl.append(dict(name=nm, expect=expect, got=got, fired=bool(ok)))

    fA, wA = best_h([2 * H0, H0, H0], H, dsm.half_grid)
    _ctl("甲 合成 H0 族 ⇒ 赢家必为 H0", H0, (None if wA is None else wA), wA == H0)
    fB, wB = best_h([2 * h_alt, h_alt, h_alt], H, dsm.half_grid)
    _ctl("乙 合成 h_alt 族 ⇒ 赢家必为 h_alt 且**不许**是 H0",
         dict(winner=round(h_alt, 4), not_H0=True),
         dict(winner=(None if wB is None else wB), not_H0=(wB is None or abs(wB - H0) > 1e-9)),
         wB is not None and abs(wB - h_alt) < 1e-9)
    _b = 3.60296630859375
    zsA = [0.0, 2 * H0, 3 * H0, 4 * H0]
    gA = [zsA[i + 1] - zsA[i] for i in range(3)]
    gB = [(zsA[i + 1] + _b) - (zsA[i] + _b) for i in range(3)]
    fC, wC = best_h(gB, H, dsm.half_grid)
    _ctl("丙 +3.603 m 平移 ⇒ 间距逐位不变、赢家仍 H0",
         dict(gaps_same=True, winner=H0),
         dict(gaps_same=all(abs(a - b) < 1e-12 for a, b in zip(gA, gB)),
              winner=(None if wC is None else wC)),
         all(abs(a - b) < 1e-12 for a, b in zip(gA, gB)) and wC == H0)
    _ctl("丁 leave-one-out 翻盘数", "≤ 一半", {"n_flip": n_flip, "n": len(loo)},
         n_flip <= max(1, len(loo) // 2))
    fE, wE = best_h([5.25, 4.60, 6.20], H, dsm.half_grid)
    _ctl("戊 喂两说都落不上的间距 ⇒ 无解（不许硬凑赢家）",
         dict(winner=None, n_ok_all_zero=True),
         dict(winner=(None if wE is None else wE),
              n_ok_all_zero=all(fE[h]["n_ok"] == 0 for h in H)),
         wE is None and all(fE[h]["n_ok"] == 0 for h in H))
    fF, wF = best_h([H0, h_alt, H0], H, dsm.half_grid)
    _ctl("己 两说混在一族 ⇒ 报 2:1、赢家 H0（多数能赢但不一致）",
         dict(winner=H0, n_ok_H0=2, n_ok_alt=1),
         dict(winner=(None if wF is None else wF), n_ok_H0=fF[H0]["n_ok"],
              n_ok_alt=fF[h_alt]["n_ok"]),
         wF == H0 and fF[H0]["n_ok"] == 2 and fF[h_alt]["n_ok"] == 1)
    n_fired = sum(1 for c in ctl if c["fired"])
    log("\n  正对照：")
    for c in ctl:
        log("    %-46s ⇒ %s" % (c["name"], "按预期" if c["fired"] else "**没按预期** %s" % (c["got"],)))
    log("  正对照 %d/%d 按预期" % (n_fired, len(ctl)))

    # ---------------------------------------------------------- 判定
    robust = (n_cfg > 0 and n_win_H0 == n_cfg and n_win_none == 0 and n_win_alt == 0)
    ok_claim = bool(win is not None and abs(win - H0) < 1e-9 and n_flip == 0 and robust)
    verdict = []
    if win is None:
        verdict.append("**未分辨**：两个层高解释掉的间距数打平 ⇒ 不许说成「相符」")
    elif abs(win - H0) < 1e-9:
        verdict.append("声明层高 %.3f 在间距尺上胜出（%d : %d）"
                       % (H0, fit[H0]["n_ok"], fit[h_alt]["n_ok"]))
    else:
        verdict.append("声明层高 %.3f **被竞争层高 %.4f 打败**（%d : %d）"
                       % (H0, h_alt, fit[h_alt]["n_ok"], fit[H0]["n_ok"]))
    # ★ 不管谁「赢」，只要不稳就必须把不稳说出来。
    #   铁律 197 只说了「不许把『没分开』说成『相符』」；本题还有**对称的一面**：
    #   也**不许**把一次脆弱的胜出说成「已否定」。
    if n_flip or not robust:
        verdict.append("★ 但**谁都没赢稳**：leave-one-out 里剔掉 1 个间距就翻的有 %d/%d 种；"
                       "换掩膜/面积门限后 %d 种配置里判给 %.3f 的 %d 种、判给 %.4f 的 %d 种、"
                       "无赢家 %d 种 ⇒ **本尺子在这栋楼上分不开两说**"
                       "（既不能说「相符」，也不能说「已否定」）"
                       % (n_flip, len(loo), n_cfg, H0, n_win_H0, h_alt, n_win_alt, n_win_none))
    verdict.append("T2：δ 在地面名单（%d 个）下极差 %s m；甲/丙 预测的 δ 与之 %s "
                   "⇒ T2 报得出 δ，但**分不开甲丙、也否不掉乙**"
                   % (len(gnd_zs), "未量到" if d_span is None else "%.3f" % d_span,
                      "在带内" if _in else ("不在带内" if _in is False else "未量到")))
    if dx.get("n_hit", 0) > 0:
        verdict.append("图纸这一支**出了数**：%d 条载体里命中 %d 条标高类注记（见上）"
                       % (dx["n_text"], dx["n_hit"]))
    elif dx.get("n_z_nonzero", 0) == 0:
        verdict.append("图纸这一支**确定不出数**：12 份 DXF 是**二维**的（z ≠ 0 的顶点 0 个），"
                       "且五类载体（自由文字/块属性/尺寸标注/图层名/块名）里一条标高注记都没有")
    else:
        verdict.append("图纸这一支**不出数但不确定**：图纸是三维的（z ≠ 0 的顶点 %d 个）却无标高注记 "
                       "⇒ 唯一可能的竖向载体是 z 取值本身，本闸不判" % dx["n_z_nonzero"])
    log("\n  判定：")
    for v in verdict:
        log("    · %s" % v)

    # ★ 三态映射（2026-10-16 修一处**判词映射错**，铁律 197 的对称面 + 199）：
    #   PASS    = 声明严格胜出，且 leave-one-out 不翻、换并层阈/掩膜/门限都不翻；
    #   FAIL    = 声明在**全部**配置里都被竞争层高打败 ⇒ 尺子**确实给出了否定**（这才叫「不符」）；
    #   NOGAUGE = 其余（打平 / 胜得脆 / 无赢家常见）⇒ **尺子在这件上出不了数**，不裁。
    #   ★ 原版把「ok_claim 不成立」一律印成 FAIL —— 那正是把「没分开」说成「已否定」（197 禁止的形状）。
    robust_reject = bool(n_cfg > 0 and n_win_alt == n_cfg
                         and n_win_H0 == 0 and n_win_none == 0)
    if ok_claim:
        rc = RC_PASS
    elif robust_reject:
        rc = RC_FAIL
        log("    ★ 声明在**全部 %d 种配置**里都输给竞争层高 %.4f ⇒ 尺子**确实给出了否定**"
            % (n_cfg, h_alt))
    else:
        rc = RC_NOGAUGE
        log("    ★ 既没胜出、也没被稳定否定（打平 / 胜得脆）⇒ **尺子在这件上出不了数**，本闸不裁")
    if n_fired < len(ctl):
        rc = RC_NOGAUGE
        log("    ★ 有正对照没按预期 ⇒ 尺子本身可疑，总判降为 NOGAUGE")
    if not t3pc["ok"]:
        rc = RC_NOGAUGE
        log("    ★ T3 自己的正/负对照没全过 ⇒ 图纸尺可疑，总判降为 NOGAUGE")
    log("===== 判词 =====")
    log("%s 总判 : %s" % (GID, {RC_PASS: "PASS", RC_FAIL: "FAIL", RC_NOGAUGE: "NOGAUGE"}[rc]))
    return _finish(
        rc,
        claim="参数.json 构件.共用.层高 = 4000 mm（假设）｜ 间距尺下须严格胜出、leave-one-out 不翻、"
              "且换并层阈/掩膜/门限都不翻",
        declared_storey_mm=float(M["storey_mm"]), n_floor_above_ground=int(M["n_tot"]),
        n_podium=int(M["n_podium"]), z_step_model_m=float(M["z_step_mm"] / 1000.0),
        z_roof_model_m=float(M["z_roof_mm"] / 1000.0),
        h_candidates={"声明": float(H0), "竞争_甲丙自洽": float(h_alt)},
        t3_positive_control=t3pc,
        half_grid_m=float(dsm.half_grid), flat_tol_m=float(FLAT_TOL_M),
        merge_k=int(MERGE_K), merge_tol_m=float(MERGE_TOL_M),
        ground=gnd, ground_G_m=float(G), ground_p10_spread_m=float(G_SPREAD),
        ground_p50_spread_m=G_SPREAD50, ground_cross_gate=xg,
        ground_estimator_list_m=[float(v) for v in gnd_zs],
        ground_estimator_spread_m=d_span, low_level_reference=low_ref,
        mask_variant=MAIN, n_plane=len(fam), n_level=len(lv),
        levels={k: [dict(z=float(L["z"]), area_m2=float(L["area_m2"]), n_plane=int(L["n_plane"]),
                        span_m=float(L["span_m"]), above_ground_m=float(L["z"] - G),
                        cen_de=float(L["cen_de"]), cen_dn=float(L["cen_dn"])) for L in v]
                for k, v in lvls.items()},
        gaps_m=[float(g) for g in gaps],
        t1=dict(h_candidates=[float(x) for x in H],
                fit={("%.4f" % h): fit[h] for h in H},
                winner=(None if win is None else float(win)),
                leave_one_out=loo, n_flip=int(n_flip),
                merge_sensitivity=sens, variants=variants_t1,
                config_winners={"n_config": int(n_cfg), "win_H0": int(n_win_H0),
                                "win_alt": int(n_win_alt), "none": int(n_win_none)}),
        t2=dict(delta_m=float(delta), delta_by_ground=delta_by_g,
                delta_span_across_ground_m=d_delta_span,
                ground_spread_across_estimators_m=d_span,
                top_level_area_m2=float(top["area_m2"]),
                top_level_above_ground_m=float(top_ag),
                low_level_reference=low_ref,
                pred_delta={"甲": pred_jia, "丙": pred_bing},
                inside_band=bool(_in) if _in is not None else None,
                note="甲与丙预测同一个 δ ⇒ 任何量 δ 的尺子都分不开它俩；"
                     "乙对任意 δ 都能吸收 ⇒ T2 对乙无分辨力"),
        t3_dxf=dx,
        verdict=verdict,
        n_controls=len(ctl), n_controls_fired=int(n_fired), controls=ctl,
        blind=[
            "乙（基准面偏移）在两把 DSM 尺子上都否不掉：间距尺免疫偏移、绝对尺里 δ 是它的自由参数；"
            "DSM 是最高面、看不见楼底面 ⇒ **DSM 结构上给不出竖向锚 h0**，只能由用户裁",
            "★ T2 的分辨率 = 地面估计器名单（%d 个：本闸 3 个窄环带 p10 ＋ 跨闸 -08 的 3 个估计器）"
            "的极差 = %s m；名单**不含**「楼内最低层」（那是楼自己的勒脚面，不是地面，已另列）"
            % (len(gnd_zs), "未量到" if d_span is None else "%.3f" % d_span),
            "★★ 但 T2 分不开甲与丙是**结构性的、与分辨率无关**：甲预测 δ=%+.4f、丙预测 δ=%+.4f，"
            "**同一个数** ⇒ 任何量 δ 的尺子都分不开它俩；乙 把偏移量当自由参数 ⇒ 对任意 δ 都能吸收。"
            "★ 本场地有坡有树（实测：窄环带 8–15 m 的 p50 = 475.474 m，而 3–8 m 的 p10 = 464.528 m，"
            "被抬 10 m 量级）⇒ 拿宽环带当「地面」会把 δ 算成 −7.83 m（第一版实测）——那是**量具错**不是模型错"
            % (pred_jia, pred_bing),
            "族里混着不属于本栋的面（树冠/邻栋挑台只要落在 1 层轮廓内就算进来）；配准中位 %s m、"
            "p90 %s m ⇒ 楼脚还会带进一条地面条带（读出来就是离地 ≈0 那一层）"
            % (pinfo.get("boundary_median_m"), pinfo.get("boundary_p90_m")),
            "★ 并层阈（%d 格 = %.3f m）是个**选择**不是测量；本闸把 {1,2,4} 格三个阈下的赢家并排报，"
            "但阈的**取值本身**没有独立来源" % (MERGE_K, MERGE_TOL_M),
            "0.25 m 格 ⇒ 半格 %.3f m 以下的差别分不开；两块面靠得比一格还近时会被并成一块" % dsm.half_grid,
            "「台阶屋面是第几层板顶」是**推**的（离地高 ÷ 层高），不是量的；本闸不指认层号",
            "平地阈值/邻域与 J-10.10-08 同口径但**窗口与掩膜不同** ⇒ 连通块切法仍可能不同",
            "★ T3 图纸尺只读 `rebuild/01_cad/raw/*.dxf` 的**模型空间**：对**外部参照（XREF）**里的注记、"
            "**图纸空间（layout/视口）**里的注记、**图片型/扫描件底图**上的标高、以及**块定义内部**"
            "（未 explode 的匿名块里嵌的自由文字）**全盲** ⇒ 「一条都没有」只在"
            "「五类载体 × 模型空间」这个范围内成立",
            "不判纹理、不判材质、不判女儿墙顶、不判楼的底面；只用 DSM 栅格链，看不见 campus2024.glb 网格链",
        ])


if __name__ == "__main__":
    sys.exit(main())
