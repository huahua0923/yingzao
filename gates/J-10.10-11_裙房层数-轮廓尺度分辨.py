# -*- coding: utf-8 -*-
r"""J-10.10-11 裙房层数 —— 用逐层平面图的轮廓尺度分辨甲 / 丙（第四把尺子）

【判据】`J-10.10-10` 把三把尺子跑完，结论是**分不开**：
  · T1 间距尺：h=4.0 以 2:1 胜，但 leave-one-out 剔 1 个间距就翻 2/5，换掩膜 7 配置 4:2:1；
  · T2 绝对尺：甲与丙**预测同一个 δ**（+3.5000）⇒ **任何**量 δ 的尺子结构上分不开它俩；
  · T3 图纸尺：12 份 DXF 是**二维**的（z ≠ 0 的顶点 0 个），五类载体里一条标高注记都没有。

  ⇒ 用户裁定：**先立第四把尺子再定**。本条就是那第四把，且它是**唯一不碰 DSM** 的一把。

  **甲 / 丙之争与 T1/T2 完全不同**：两说争的不是「数是多少」，是**「图上的层号数到第几层为止」**——
    甲 裙房 **7** 层（第 7 层顶 = 28.0 m 是裙房屋面）
    丙 裙房 **8** 层（第 8 层顶 = 28.0 m 是裙房屋面）
  ⇒ 图纸上「裙房屋面」是**哪一个层号**，就把两说分开了。
  ⇒ 而**裙房与塔楼在平面上尺度差一个量级**（DSM 实测：裙房屋面 2108.6 m² vs 塔楼约 260 m²）
    ⇒ **逐层平面图的轮廓尺度本身**就能数出「大轮廓到第几层为止」。

  **被测声明**：`rebuild/构件库/参数.json` 的 `构件.共用.层高 = 4000 mm`（标注 **假设**）⇒ **地上 11 层**。
    ★ 2026-10-16：用户裁定「**按甲定案 · 重算整条链**」后，层高声明由 3500 改 4000。
      ★★ **但本闸的判词一个字都不变** —— 它量的是**逐层平面图上的层号**，与「一层多高」无关；
        读数 `k* = 7`、`rho_max = 4.447 / 9.802 / 4.158` 是**图纸自己的**性质。
        ⇒ 改的是上面这句「被测声明」的**引用值**，不是判据。
  **判定**：三个独立口径（见【量具】）若**都**量出同一个断崖位置 `k*`，且 `k*` 是**尖锐**的
    （`rho_max ≥ RHO_MIN` 且 `rho_max / rho_2nd ≥ SHARP_MIN`）⇒ **分得开**，`k*` 就是裙房层数。
    否则 ⇒ **分不开**（既不许说成「相符」，也不许把一次脆弱的胜出说成「已否定」，铁律 197）。

【量具】三个口径，**同一次读盘、同一份顶点集**，只换统计量（分开报、不合成一个 bool，铁律 174）：

  · **口径 A（主）**：全部几何实体的顶点做 **x/y 各自 p1–p99 分位裁剪**后的**轴对齐包围盒面积**。
    分位裁剪是为了挡掉画在楼外的标注/轴号离群点；轴对齐 bbox 对**楼的转角免疫**
    （各层同等"撑大"⇒ 比值仍可比，这正是「用比值不用绝对值」的用处，与 T1 间距尺对基准面偏移免疫同构）。
  · **口径 B（敏感性）**：同顶点集，换 **p5–p95** 分位 ⇒ 与 A 差多少，就是「离群点有没有把框撑开」的读数。
  · **口径 C（对文字免疫）**：**几何总长度**（LINE 线段长 + 多段线各段长 + 圆周长 + 弧长），单位 m。
    文字/标注的点**贡献 0 长度** ⇒ 这一口径**结构上不被文字污染**（A/B 会被 TEXT 的插入点撑框）。

  · **口径 D（旁证，不同族）**：**实体计数** `n_ent` —— 它既不是面积也不是长度，是**计数**。
    ★ D **不参与**「三口径是否一致」的判定（它是**佐证**不是**主口径**）。理由：本闸主判要的是
      「**尺度**」，而计数会被「画得细不细」左右（裙房标准层画得比塔楼繁）⇒ 它自己分不清
      「大→中」与「中→小」两级（实测尖锐度 1.02）⇒ 它**自己不敢出数**，只能当**旁证**。

  ★★ **三口径不是三族**（这一条必须写在前面，否则会把同源的两个量当两个独立证据，铁律 174）：
    **A 与 B 是同一个顶点集、只换分位** ⇒ 它们**同源**。真正**独立**的族只有两族 ——
    **包围盒族**（A/B）与**长度族**（C）；再加**计数族**（D，旁证）。⇒ 判词里
    「三口径一致」的正确读法是「**两族主口径 ＋ 一族旁证**都指向同一个 k\*」。

  **断崖判据**（`podium_of`，纯函数，正对照全打在它上面）：
    地上部分按层号升序得序列 `v[1..n]`，相邻比 `rho[i] = v[i] / v[i+1]`；
    `k* = argmax(rho) + 1`（＝断崖**前**的层数＝裙房层数）；`rho_max / rho_2nd = 尖锐度`。
    ★ `RHO_MIN` 是**选择不是测量** ⇒ 四个阈值 `{1.3, 1.5, 2.0, 2.5}` 下各自的赢家**并排报**（铁律 28）。

【量具盲区】本闸对下面这几类**一个字都不给结论**：
  · ★★ **它量的是"图上的编号"，不是"物理的层"**。若图纸制作者自己把裙房顶层编成 7 或 8，
    本闸跟着图纸走 —— 而「图纸编号 = 交付侧编号」这件事**本闸不证**（那是另一把尺子的事）。
    本闸只回答：**在这份图纸自己的编号体系里，大轮廓到第几层为止**。
  · ★ **"大轮廓"是尺度不是一个物理属性**。若裙房顶层的屋面图画得比标准层简略（女儿墙 / 屋面构造另图），
    该层线条数会**掉下来**而面积不掉 ⇒ **面积口径与长度口径会分歧**。三个口径分歧时本闸报「分不开」，
    **不挑一个当答案**。
  · **INSERT 展开只到 3 层**（`MAX_XREF_DEPTH`）：更深的外部参照 / 嵌套块**看不见**；
    展开失败的 INSERT **单独计数**（`n_insert_fail`，铁律 199：崩了与没量到分开报）。
  · **HATCH（填充）不取边界**：它算实体但**不进顶点集也不进长度**，只计数（`n_skip` 的 `skip_kind`）。
    若某层用地坪填充表达轮廓，本闸会**低估**它 —— 这是本闸已知的、**未修**的盲。
  · **轴网 / 轴号圈**若画得比楼还大，A/B 的框会被撑开、C 也会被撑大；本闸把每个图层的读数记进
    JSON（`per_floor[].by_layer` 未导出，见 `scan_dxf`）供人看，但**不自动判哪个图层是"主体"**
    ——那是选择不是测量。
  · **单位**：本闸只用**比值**（层间比），对图纸单位（mm/m）**结构上免疫**；因此**不报**绝对尺寸当结论。
  · 不判楼的形状、不判面积真值、不判裙房与塔楼层号在**别的**图纸里怎么编。

【正对照】全部打在**纯函数** `podium_of()` 上（不碰 DXF）—— 每条落**读数**不只落 bool：
  甲 **合成 7 大 + 4 小**（比 5×）⇒ 必须 `k* = 7`、`resolved=True`。
  乙 ★★ **合成 8 大 + 3 小**          ⇒ 必须 `k* = 8`、`resolved=True`
     —— 与「甲」**成对**：同一把尺子喂 7 报 7、喂 8 报 8 ⇒ 这才叫**有分辨力**（铁律 137）。
  丙 **合成 6 大 + 5 小**          ⇒ 必须 `k* = 6`（证明它不是恒报 7 或 8 的尺子）。
  丁 **两级断崖·分得开的**（8 大(1000) + 2 中(250) + 1 小(100)：大→中 = 4.0、中→小 = 2.5
     ⇒ 尖锐度 1.6 ≥ `SHARP_MIN`）⇒ 必须取**最大**那一处，`k* = 8`、`resolved=True`。
  丁2 ★ **两级断崖·挤在一起的**（8 大(1000) + 2 中(400) + 1 小(200)：大→中 = 2.5、中→小 = 2.0
     ⇒ 尖锐度 1.25 < `SHARP_MIN`）⇒ 必须 `resolved=False`
     —— 两级断崖**肩并肩**时分不清哪一级才是裙房顶，尺子**必须拒绝出数**。
     ★ 这一条是**首跑实测补上的**：第一版把「丁」的期望手打成 `resolved=True`，实得 `False`
       ⇒ 查下来**尺子是对的、我的期望是错的**（按我自己定的尖锐度门限，1.25 < 1.5 就该 False）。
       按仓规「修测试，如果测试错了」⇒ 把它**改判成否定对照**并单列，而不是把门限放松去迁就它。
  戊 **否定对照·无断崖**（等比 1.05 递减）⇒ 必须 `resolved=False`，不许硬凑一个 k*。
  己 **否定对照·全同**（各层一样）      ⇒ 必须 `resolved=False`。
  庚 ★ **否定对照·弱断崖**（7 大 + 4 小，但只差 1.15 倍）⇒ 必须 `resolved=False`
     —— 这一条筛掉「只要有一点点差就报一个 k*」的假尺子（与「甲」成对：强断崖报、弱断崖不报）。
  辛 **噪声**（固定种子随机）⇒ 只落读数（`rho_max` 与 `resolved`），**不作断言**，供人看它多不稳。

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

import ezdxf  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
DXF_DIR = os.path.join(REPO, "rebuild", "01_cad", "raw")

GID = "J-10.10-11"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

MAX_XREF_DEPTH = 3                    # INSERT（块引用）展开深度上限
PCT_MAIN = (1.0, 99.0)                # 口径 A：p1–p99
PCT_ALT = (5.0, 95.0)                 # 口径 B：p5–p95
RHO_MIN_SET = (1.3, 1.5, 2.0, 2.5)    # ★ 断崖门限是**选择不是测量** ⇒ 四个并排报（铁律 28）
RHO_MIN_MAIN = 2.0                    # 主门限（写进判词的那一个）
SHARP_MIN = 1.5                       # 尖锐度门限：rho_max / rho_2nd ≥ 此值才算「尖」
LANES = ("A_bbox_p1p99", "B_bbox_p5p95", "C_total_len_m")
# ★ 旁证口径：**不参与**「主口径是否一致」的判定，只旁列（理由见 docstring【量具】）。
SIDE_LANES = ("D_n_entities",)

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


# ------------------------------------------------------------------ 纯函数：断崖判决（正对照全打在它上面）

def podium_of(vals, rho_min):
    """地上各层（按层号升序）的一个尺度序列 ⇒ 断崖判决。

    返回 dict：
      ratios  相邻比 rho[i] = v[i]/v[i+1]（i 从 0 起，对应「第 i+1 层与第 i+2 层之间」）
      k_star  断崖**前**的层数（＝裙房层数）；无有效比时为 None
      rho_max / rho_2nd  最大比 / 次大比（后者用来量「断崖有多尖」）
      sharp   rho_max / rho_2nd（次大不存在时记为 None）
      resolved  rho_max ≥ rho_min 且（无次大 或 sharp ≥ SHARP_MIN）
    ★ 只返回读数，不下「是甲还是丙」的结论 —— 那是 main 的事。
    """
    v = [float(x) for x in vals]
    ratios, pairs = [], []
    for i in range(len(v) - 1):
        a, b = v[i], v[i + 1]
        if b > 0 and math.isfinite(a) and math.isfinite(b):
            ratios.append(a / b)
            pairs.append((a / b, i))
        else:
            ratios.append(None)
    if not pairs:
        return dict(ratios=ratios, k_star=None, rho_max=None, rho_2nd=None,
                    sharp=None, resolved=False, n_usable=0)
    j = max(range(len(pairs)), key=lambda t: pairs[t][0])
    rho_max, i_max = pairs[j]
    others = [r for t, (r, _) in enumerate(pairs) if t != j]
    rho_2nd = max(others) if others else None
    sharp = (rho_max / rho_2nd) if (rho_2nd and rho_2nd > 0) else None
    ok = (rho_max >= rho_min) and (sharp is None or sharp >= SHARP_MIN)
    return dict(ratios=ratios, k_star=int(i_max + 1), rho_max=float(rho_max),
                rho_2nd=(float(rho_2nd) if rho_2nd is not None else None),
                sharp=(float(sharp) if sharp is not None else None),
                resolved=bool(ok), n_usable=len(pairs))


def positives():
    """★ 正 / 否定对照表（铁律 137：判据有无分辨力，必须喂**确有缺陷**的输入去试）。

    每条给出：合成序列、期望 k*（None＝只要求 resolved 为 False/不断言）、期望 resolved
    （None＝只落读数不作断言）。
    """
    big, small = 1000.0, 200.0
    cases = []
    cases.append(("甲 7大+4小 (5.0×)", [big] * 7 + [small] * 4, 7, True))
    cases.append(("乙 8大+3小 (5.0×)", [big] * 8 + [small] * 3, 8, True))
    cases.append(("丙 6大+5小 (5.0×)", [big] * 6 + [small] * 5, 6, True))
    cases.append(("丁 两级断崖·分得开 8大+2中(250)+1小(100)",
                  [big] * 8 + [250.0] * 2 + [100.0] * 1, 8, True))
    # ★ 否定对照：两级断崖**肩并肩**（2.5 vs 2.0，尖锐度 1.25 < SHARP_MIN）⇒ 必须拒绝出数。
    #   ★ 这一条是**首跑实测补上的**：第一版把「丁」的期望手打成 resolved=True，实得 False
    #     ⇒ 查下来**尺子是对的、期望是错的**（按我自己定的尖锐度门限 1.25 < 1.5 就该 False）。
    cases.append(("丁2 否定·两级断崖挤在一起 8大+2中(400)+1小(200)",
                  [big] * 8 + [400.0] * 2 + [200.0] * 1, 8, False))
    cases.append(("戊 否定·无断崖 (等比1.05)", [1000.0 * (1.05 ** -i) for i in range(11)],
                  None, False))
    cases.append(("己 否定·全同", [1000.0] * 11, None, False))
    cases.append(("庚 否定·弱断崖 7大+4小 (1.15×)", [1000.0] * 7 + [869.5652] * 4,
                  None, False))
    rng = np.random.RandomState(20261016)
    cases.append(("辛 噪声 (固定种子)", list(800.0 + rng.uniform(0, 400, 11)), None, None))
    return cases


def run_positives(rho_min):
    rows, bad = [], []
    for name, vals, want_k, want_res in positives():
        r = podium_of(vals, rho_min)
        ok = None
        if want_res is not None:
            if want_res:
                ok = bool(r["resolved"]) and (r["k_star"] == want_k)
            else:
                ok = (r["resolved"] is False)
        rows.append(dict(name=name, want_k=want_k, want_resolved=want_res,
                         got_k=r["k_star"], got_resolved=r["resolved"],
                         rho_max=r["rho_max"], sharp=r["sharp"], ok=ok))
        if ok is False:
            bad.append(rows[-1])
    return rows, bad


# ------------------------------------------------------------------ 读 DXF（顶点集 + 长度 + 图层分解）

def _entity_geom(e):
    """一个实体的 (点表, 长度 m)。取不到几何 ⇒ None（调用方**分开计数**，铁律 199）。"""
    t = e.dxftype()
    if t == "LINE":
        a, b = e.dxf.start, e.dxf.end
        p = [(a.x, a.y), (b.x, b.y)]
        return p, math.dist(p[0], p[1])
    if t == "LWPOLYLINE":
        p = [(float(x), float(y)) for x, y in e.get_points("xy")]
        if len(p) < 2:
            return (p, 0.0) if p else None
        L = sum(math.dist(p[i], p[i + 1]) for i in range(len(p) - 1))
        if e.closed:
            L += math.dist(p[-1], p[0])
        return p, L
    if t == "POLYLINE":
        p = [(float(v[0]), float(v[1])) for v in e.points()]
        if len(p) < 2:
            return (p, 0.0) if p else None
        L = sum(math.dist(p[i], p[i + 1]) for i in range(len(p) - 1))
        if e.is_closed:
            L += math.dist(p[-1], p[0])
        return p, L
    if t == "CIRCLE":
        c, r = e.dxf.center, float(e.dxf.radius)
        return [(c.x - r, c.y), (c.x + r, c.y), (c.x, c.y - r), (c.x, c.y + r)], 2 * math.pi * r
    if t == "ARC":
        c, r = e.dxf.center, float(e.dxf.radius)
        span = (float(e.dxf.end_angle) - float(e.dxf.start_angle)) % 360.0
        return [(c.x - r, c.y), (c.x + r, c.y), (c.x, c.y - r), (c.x, c.y + r)], \
            r * math.radians(span)
    if t == "ELLIPSE":
        c = e.dxf.center
        mj = e.dxf.major_axis
        return [(c.x, c.y), (c.x + mj.x, c.y + mj.y), (c.x - mj.x, c.y - mj.y)], 0.0
    if t == "SPLINE":
        pts = list(e.control_points) or list(e.fit_points)
        p = [(float(v[0]), float(v[1])) for v in pts]
        L = sum(math.dist(p[i], p[i + 1]) for i in range(len(p) - 1)) if len(p) > 1 else 0.0
        return (p, L) if p else None
    if t in ("SOLID", "TRACE", "3DFACE"):
        p = []
        for n in ("vtx0", "vtx1", "vtx2", "vtx3"):
            try:
                v = getattr(e.dxf, n)
                p.append((v.x, v.y))
            except Exception:
                pass
        L = sum(math.dist(p[i], p[i + 1]) for i in range(len(p) - 1)) if len(p) > 1 else 0.0
        return (p, L) if p else None
    if t == "POINT":
        v = e.dxf.location
        return [(v.x, v.y)], 0.0
    if t in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
        v = e.dxf.insert
        return [(v.x, v.y)], 0.0              # ★ 文字**贡献 0 长度**（口径 C 对文字免疫）
    if t == "DIMENSION":
        for n in ("defpoint", "text_midpoint", "defpoint2", "defpoint3"):
            try:
                v = getattr(e.dxf, n)
                return [(v.x, v.y)], 0.0
            except Exception:
                continue
        return None
    return None


def scan_dxf(path):
    """读一份 DXF：全实体顶点集、几何总长度、**按图层的分解**、以及各**跳过/失败**计数。"""
    acc = {"pts": [], "len": 0.0, "n_ent": 0, "n_insert": 0, "n_insert_fail": 0,
           "n_skip": 0, "skip_kind": {}, "insunits": None, "by_layer": {}}
    doc = ezdxf.readfile(path)
    try:
        acc["insunits"] = int(doc.header.get("$INSUNITS", 0))
    except Exception:
        acc["insunits"] = None
    msp = doc.modelspace()

    def walk(e, depth):
        t = e.dxftype()
        if t == "INSERT":
            acc["n_insert"] += 1
            if depth >= MAX_XREF_DEPTH:
                acc["n_skip"] += 1
                acc["skip_kind"]["INSERT(depth)"] = acc["skip_kind"].get("INSERT(depth)", 0) + 1
                return
            try:
                for v in e.virtual_entities():
                    walk(v, depth + 1)
            except Exception:
                acc["n_insert_fail"] += 1          # ★ 展开崩了 ≠ 没量到（铁律 199）
            return
        g = _entity_geom(e)
        if g is None:
            acc["n_skip"] += 1
            acc["skip_kind"][t] = acc["skip_kind"].get(t, 0) + 1
            return
        p, L = g
        acc["pts"].extend(p)
        acc["len"] += L
        acc["n_ent"] += 1
        lay = str(getattr(e.dxf, "layer", "?"))
        d = acc["by_layer"].setdefault(lay, {"n": 0, "L": 0.0, "pts": []})
        d["n"] += 1
        d["L"] += L
        d["pts"].extend(p)

    for e in msp:
        walk(e, 0)
    return acc


def pct_bbox(pts, lo, hi):
    """x/y 各自 [lo,hi] 分位裁剪后的轴对齐 bbox：(宽, 高, 面积)。"""
    a = np.asarray(pts, float)
    x0, x1 = np.percentile(a[:, 0], lo), np.percentile(a[:, 0], hi)
    y0, y1 = np.percentile(a[:, 1], lo), np.percentile(a[:, 1], hi)
    w, h = float(x1 - x0), float(y1 - y0)
    return w, h, w * h


def floor_no(stem):
    """`1层`→1 … `11层`→11 ｜ `地下1层`→-1 ｜ 认不出→None（**不默认 0**，铁律 158）。"""
    s = stem.strip()
    if s.startswith("地下"):
        m = re.search(r"(\d+)", s)
        return -(int(m.group(1)) if m else 1)
    m = re.fullmatch(r"(\d+)\s*层", s)
    return int(m.group(1)) if m else None


def main() -> int:
    log("%s 裙房层数 —— 逐层平面图轮廓尺度（甲 7 层 vs 丙 8 层）" % GID)
    log("  仓: %s" % REPO)
    log("  输入: %s/*.dxf（ezdxf %s）" % (DXF_DIR, ezdxf.__version__))

    files = sorted(glob.glob(os.path.join(DXF_DIR, "*.dxf")))
    if not files:
        log("  ★ 一份 DXF 都没有 ⇒ 无被测集合，判据**不作数**（铁律 174：n=0 恒绿）")
        return _finish(RC_NOGAUGE, n_files=0, verdict="NO_INPUT")

    recs, unrecognized = [], []
    log("")
    log("[逐层普查] 每份 DXF 的实体/顶点/长度（★ 跳过与失败**分开计**，铁律 199）")
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        fn = floor_no(stem)
        if fn is None:
            unrecognized.append(stem)
        try:
            acc = scan_dxf(f)
        except Exception as ex:
            log("  ✗ %-10s **读取崩了**：%s（与「没量到」分开报）" % (stem, ex))
            recs.append(dict(stem=stem, floor=fn, crashed=str(ex)))
            continue
        w1, h1, area1 = pct_bbox(acc["pts"], *PCT_MAIN) if acc["pts"] else (0.0, 0.0, 0.0)
        w2, h2, area2 = pct_bbox(acc["pts"], *PCT_ALT) if acc["pts"] else (0.0, 0.0, 0.0)
        rec = dict(stem=stem, floor=fn, n_pts=len(acc["pts"]), n_ent=acc["n_ent"],
                   n_insert=acc["n_insert"], n_insert_fail=acc["n_insert_fail"],
                   n_skip=acc["n_skip"], skip_kind=acc["skip_kind"],
                   insunits=acc["insunits"],
                   w_main=w1, h_main=h1, area_main=area1,
                   w_alt=w2, h_alt=h2, area_alt=area2,
                   total_len_m=acc["len"],
                   by_layer={k: dict(n=v["n"], L=v["L"],
                                     area=(pct_bbox(v["pts"], *PCT_MAIN)[2] if v["pts"] else 0.0))
                             for k, v in acc["by_layer"].items()})
        recs.append(rec)
        log("  %-10s 层号 %-3s ｜ 实体 %6d ｜ 顶点 %6d ｜ 长度 %11.1f m ｜ "
            "A(bbox p1-99) %12.1f ｜ B(p5-95) %12.1f"
            % (stem, fn, rec["n_ent"], rec["n_pts"], rec["total_len_m"],
               rec["area_main"], rec["area_alt"]))
        if rec["n_insert_fail"] or rec["n_skip"]:
            log("      ★ INSERT 展开崩了 %d 个（不是「没有」）｜跳过 %d 个：%s"
                % (rec["n_insert_fail"], rec["n_skip"],
                   ", ".join("%s×%d" % (k, v) for k, v in sorted(rec["skip_kind"].items()))))
    if unrecognized:
        log("  ★ 文件名认不出层号（**单列，不并进任何一层**）：%s" % ", ".join(unrecognized))

    # ---------------------------------------------------------- 地上各层
    above = sorted([r for r in recs if r.get("floor") is not None and r["floor"] >= 1
                    and "crashed" not in r], key=lambda r: r["floor"])
    if len(above) < 3:
        log("  ★ 地上可用层数 %d < 3 ⇒ 数不出断崖，判据**不作数**" % len(above))
        return _finish(RC_NOGAUGE, n_files=len(files), n_above=len(above), verdict="TOO_FEW")
    log("")
    log("  地上层序: %s" % " / ".join("%d层" % r["floor"] for r in above))
    seq = {
        "A_bbox_p1p99": [r["area_main"] for r in above],
        "B_bbox_p5p95": [r["area_alt"] for r in above],
        "C_total_len_m": [r["total_len_m"] for r in above],
        "D_n_entities": [r["n_ent"] for r in above],
    }

    # ---------------------------------------------------------- 三口径 × 多阈值
    log("")
    log("[断崖判决] 主口径各自报、不合成一个 bool（铁律 174）")
    log("           ★ A 与 B **同源**（同一顶点集、只换分位）⇒ 独立族只有 包围盒族(A/B) 与 长度族(C)；"
        "D 是旁证")
    lanes = {}
    for lane in LANES:
        vals = seq[lane]
        log("  · 口径 %s" % lane)
        log("      相邻比 rho: %s"
            % " ".join(("%.3f" % v) if v is not None else "—"
                       for v in podium_of(vals, RHO_MIN_MAIN)["ratios"]))
        by_thr = {}
        for thr in RHO_MIN_SET:
            r = podium_of(vals, thr)
            by_thr[str(thr)] = dict(k_star=r["k_star"], rho_max=r["rho_max"],
                                    sharp=r["sharp"], resolved=r["resolved"])
        r0 = podium_of(vals, RHO_MIN_MAIN)
        lanes[lane] = dict(readings=by_thr, main=r0)
        for thr in RHO_MIN_SET:
            b = by_thr[str(thr)]
            log("      阈 %-4s ⇒ k* = %-4s ｜ rho_max = %-8s ｜ 尖锐度 = %-8s ｜ %s"
                % (thr, b["k_star"],
                   ("%.3f" % b["rho_max"]) if b["rho_max"] else "—",
                   ("%.3f" % b["sharp"]) if b["sharp"] else "—",
                   "**出数**" if b["resolved"] else "不出数（断崖不够尖/不够大）"))

    # ---------------------------------------------------------- 旁证口径 D（不参与 agree）
    side = {}
    log("")
    log("  [旁证] 口径 D_n_entities —— **计数**族；★ 不参与「主口径是否一致」的判定（它自己分不清"
        "「大→中」与「中→小」两级）")
    for ln in SIDE_LANES:
        vals = seq[ln]
        r0 = podium_of(vals, RHO_MIN_MAIN)
        side[ln] = dict(k_star=r0["k_star"], rho_max=r0["rho_max"],
                        sharp=r0["sharp"], resolved=r0["resolved"], ratios=r0["ratios"])
        log("    · %s" % ln)
        log("        相邻比 rho: %s"
            % " ".join(("%.3f" % v) if v is not None else "—" for v in r0["ratios"]))
        log("        阈 %.1f ⇒ k* = %-4s ｜ rho_max = %-8s ｜ 尖锐度 = %-8s ｜ %s"
            % (RHO_MIN_MAIN, r0["k_star"],
               ("%.3f" % r0["rho_max"]) if r0["rho_max"] else "—",
               ("%.3f" % r0["sharp"]) if r0["sharp"] else "—",
               "**出数**" if r0["resolved"] else "不出数（断崖不够尖/不够大）"))

    # ---------------------------------------------------------- 正/否定对照
    log("")
    log("  正 / 否定对照（全部打在纯函数 `podium_of` 上，不碰 DXF）：")
    rows, bad = run_positives(RHO_MIN_MAIN)
    for r in rows:
        tag = "按预期" if r["ok"] else ("**不符**" if r["ok"] is False else "（只落读数）")
        log("    %-34s 期望 k*=%-4s resolved=%-5s ⇒ 实得 k*=%-4s resolved=%-5s "
            "rho_max=%-7s %s"
            % (r["name"], r["want_k"], r["want_resolved"], r["got_k"],
               r["got_resolved"],
               ("%.3f" % r["rho_max"]) if r["rho_max"] else "—", tag))
    n_assert = sum(1 for r in rows if r["ok"] is not None)
    log("  正/否定对照 %d/%d 按预期" % (n_assert - len(bad), n_assert))

    # ---------------------------------------------------------- 判定
    log("")
    log("  判定：")
    main_k = {ln: lanes[ln]["main"]["k_star"] for ln in LANES}
    main_ok = {ln: lanes[ln]["main"]["resolved"] for ln in LANES}
    log("    · 三口径（阈 %.1f）主读数：%s"
        % (RHO_MIN_MAIN,
           " ｜ ".join("%s ⇒ k*=%s%s" % (ln, main_k[ln], "" if main_ok[ln] else "(不出数)")
                       for ln in LANES)))
    resolved_lanes = [ln for ln in LANES if main_ok[ln]]
    agree = (len(resolved_lanes) == len(LANES) and len(set(main_k.values())) == 1)
    k_star = main_k[LANES[0]] if agree else None

    verdict_lines = []
    if agree:
        who = {7: "甲（裙房 7 层）", 8: "丙（裙房 8 层）"}.get(k_star, "**两说都不符**（第三说）")
        verdict_lines.append("三口径一致、且断崖够尖 ⇒ **分得开**：裙房 = **%d 层** ⇒ 支持 %s"
                             % (k_star, who))
        d_txt = "、".join("%s k*=%s" % (ln, side[ln]["k_star"]) for ln in SIDE_LANES)
        verdict_lines.append(
            "  · 旁证 %s（它自己%s ⇒ 只作旁证、不进判据；★ 但**方向与主口径一致**才算旁证）"
            % (d_txt, "够尖" if all(side[ln]["resolved"] for ln in SIDE_LANES) else "**不够尖**"))
    else:
        verdict_lines.append(
            "★ **分不开**：能出数的口径 %d/%d 个%s ⇒ 不许说成「相符」，也不许把一次脆弱的胜出"
            "说成「已否定」（铁律 197）"
            % (len(resolved_lanes), len(LANES),
               ("，且 k* 不一致（%s）" % sorted(set(main_k.values()))) if resolved_lanes else ""))
    for ln in LANES:
        verdict_lines.append("  · %s ⇒ k*=%s，rho_max=%s，尖锐度=%s，%s"
                             % (ln, main_k[ln],
                                ("%.3f" % lanes[ln]["main"]["rho_max"])
                                if lanes[ln]["main"]["rho_max"] else "—",
                                ("%.3f" % lanes[ln]["main"]["sharp"])
                                if lanes[ln]["main"]["sharp"] else "—",
                                "出数" if main_ok[ln] else "**不出数**"))
    for v in verdict_lines:
        log("    " + v)

    rc = RC_PASS if agree else RC_FAIL
    if bad:
        rc = RC_NOGAUGE
        log("    ★ 正/否定对照没全过 ⇒ 本尺子本身可疑，总判降为 NOGAUGE")
    log("")
    log("===== 判词 =====")
    log("%s 总判 : %s" % (GID, {RC_PASS: "PASS", RC_FAIL: "FAIL",
                                RC_NOGAUGE: "NOGAUGE"}[rc]))
    for v in verdict_lines:
        log("  " + v)

    return _finish(rc,
                   n_files=len(files), n_above=len(above),
                   unrecognized=unrecognized,
                   floors=[r["floor"] for r in above],
                   seq={k: [float(x) for x in v] for k, v in seq.items()},
                   lanes={ln: dict(readings=lanes[ln]["readings"],
                                   k_star=lanes[ln]["main"]["k_star"],
                                   rho_max=lanes[ln]["main"]["rho_max"],
                                   rho_2nd=lanes[ln]["main"]["rho_2nd"],
                                   sharp=lanes[ln]["main"]["sharp"],
                                   ratios=lanes[ln]["main"]["ratios"],
                                   resolved=lanes[ln]["main"]["resolved"])
                          for ln in LANES},
                   per_floor=[{k: r.get(k) for k in
                               ("stem", "floor", "n_ent", "n_pts", "n_insert",
                                "n_insert_fail", "n_skip", "insunits",
                                "w_main", "h_main", "area_main",
                                "w_alt", "h_alt", "area_alt", "total_len_m",
                                "crashed")}
                              for r in recs],
                   controls=rows,
                   side={ln: dict(side[ln]) for ln in SIDE_LANES},
                   verdict="; ".join(verdict_lines),
                   agree=bool(agree), k_star=(int(k_star) if k_star else None),
                   rho_min_main=RHO_MIN_MAIN, sharp_min=SHARP_MIN)


if __name__ == "__main__":
    sys.exit(main())
