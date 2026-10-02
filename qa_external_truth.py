# -*- coding: utf-8 -*-
"""qa_external_truth.py — **外部真值**门禁：把「模型的竖向分层与底面轮廓」拿去和
**影像/DSM 实测出来的那一份**比，而不是和自己比。

## 为什么要单独一个文件（同族的 I1–I18 为什么不够）

`qa_structural.py` 的 I1–I18 量的全是**内部自洽**：柱在不在自己的轮廓里、房间有没有外溢、
同构平面各层有没有叠加。这些判据**在被测对象整体错位时全部会绿**——
c006 实测就是这一种：11 层 / 39.6 m 的体量，几何内部一切正常，
而影像上这是**约 16 层 / 52 m**的楼。**自己跟自己比，永远看不出自己站错了位置。**
⇒ 这一族要的输入是**屋外**的（正射影像 + DSM），与 I1–I18 的输入不重叠，所以另开一个模块
（也符合本仓「每个功能的模块代码要分开写」）。

## 判据的骨架（两侧用**同一条规则**，这很要紧）

  · 真值侧：`hyps`（各高度以上的水平截面面积）→ 按「面积相对上一档掉 ≥20%」切出**级**；
  · 模型侧：`floors/floor*.json` 的顶面标高 + `outline` 鞋带面积 → **同一条规则**切出级。
  ⇒ 两侧都由**同一条规则**推出级数，所以「少了几级」不是我在数，是规则在数。

## 三条不许省的事

  1. **真值是一次带时刻的测量**（铁律 50）：登记里必须带 来源路径 + 字节 + sha12 + 量它的日期。
     依据变了（sha 不符）⇒ 退出码 2「需重签」，**不许**当绿。
  2. **没登记 ⇒ 「不适用」，不许当 0 也不许当通过**（铁律 60/76）：退出码 3，
     与 0（通过）在屏幕上必须不是同一个字。
  3. **红的时候要说清缺的是哪张图**：层数/层高这条**卡在图纸上，不是卡在代码上**
     （建施-剖面图本机没有）⇒ 每条 ERROR 的尾巴和报告 footer 都要写出来。
     否则下一个人会去改代码，而代码没错。

## 分辨率预算（判「量到了」与「判不出来」的分界，来自实测不是估计）

  · DSM 对 10 个地面控制点：**mean +0.071 m / sd 0.044 m** ⇒ 3σ = 0.132 m
  · DTM 对同一批：mean +0.201 / sd 0.193
  · 正射影像：**0.4 m/像素** ⇒ 女儿墙 0.5 m 级细节**永久判不出来**（写死在 caveat 里）
  · `hyps` 的高度档位不是等距：2,5,10,15,20,24,25,26,28,30,35,40,45,50,52
    ⇒ 28 m 以上档距 ≥ 2 m，**档内不可分辨** ⇒ 判「级顶落在这个档里」只能给**区间**，不能给点值。

## 用法
    python qa_external_truth.py c006              # 判一栋
    python qa_external_truth.py --all             # 所有已登记外部真值的楼
    python qa_external_truth.py --snapshot c006   # 从测量产物刷新真值登记（只读产物，只写登记）
    python qa_external_truth.py --selftest        # 两端对照（改坏必须红、对上真值必须绿）

## 退出码
    0 = 该判的项全过
    1 = 有 ERROR（真差异）
    2 = 尺子坏了：登记在、但依据文件没了 / sha 不符 / 对照没如期
    3 = **不适用**：这栋楼没有外部真值登记 ⇒ 本项**没量过**，不是通过
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"D:\gym3d\data\buildings"
REG_DIR = r"D:\gym3d\_qa\external_truth"
REPORT_DIR = r"D:\gym3d\_qa"

# ── 判据参数（每一个都要能回答「为什么是这个数」）
DROP_REL = 0.20        # 面积相对上一档掉这么多 ⇒ 算一「级」收进
AREA_TOL_REL = 0.05    # 底面轮廓面积相对差：>5% WARN、>10% ERROR
#                       为什么 5%：真值是**下界**（掩膜不含挑檐/遮挡），不是等值；
#                       而量具本身的散布是 0.04%（三把尺 B/C 差 2.5 ㎡）⇒ 容差是量具的 ~100 倍
PARAPET_MIN = 0.0      # 女儿墙高度取自 floor 的 roof.parapetH，不设下限（0 就是不判）
Z3 = 3.0               # 3σ 系数，配 DSM 的 sd 0.044 m ⇒ 0.132 m

# ── 真值产物在哪（`--snapshot` 用；只读）
SNAPSHOT_SOURCES = {
    "c006": [
        (r"D:\gym3d\_scratch\_c006cmp\_22_tiers.json", "影像/DSM 实测分层"),
        (r"D:\gym3d\_scratch\_c006cmp\_21_two_gauge.json", "两种测量口径对照(面积)"),
    ],
}
RESOLUTION = {
    "dsm_vs_gcp": {"n": 10, "mean_m": 0.071, "sd_m": 0.044},
    "dtm_vs_gcp": {"n": 10, "mean_m": 0.201, "sd_m": 0.193},
    "ortho_m_per_px": 0.4,
}

# ★ 量具散布只许在**同类**量之间取 —— 这是本模块自己踩过的一个坑，记在这里当判据：
#   三个口径里 A几何 是**另一种测量**（纯几何多边形），B/C 才是一对**重复测量**
#   （同一张颜色掩膜，补洞 / 不补洞）。把 A 和 C 相减得到的 5784 ㎡（97.9%）**不是量具散布**，
#   它量的是「两种方法差多少」，拿它当分母会让容差/散布的比值算成 0.05 倍 ——
#   **读数会从「容差比量具宽 100 倍」变成「容差比量具紧」，方向正好相反**，而屏幕上
#   两种都是一句通顺的话（铁律 42(a)：取 max/min 之前先问各成员是不是同一个量）。
#   ⇒ 所以「谁是重复测量、谁是不相干的那一把」由**登记声明**，不在判据里猜。
GAUGE_FAMILY = {
    "c006": {
        "replicates": ["B颜色", "C颜色+补洞"],
        "odd_one_out": "A几何",
        "why": "A几何 是纯几何多边形(126.75㎡，只圈到塔楼)，与颜色掩膜不是同一个量；"
               "B/C 是同一张颜色掩膜的补洞/不补洞两版 ⇒ 只有 B 与 C 之差才是量具散布",
    },
}
CAVEAT = [
    "面积是**下界**：影像掩膜不含挑檐/遮挡区 ⇒ 只判「模型比实测大」，不判「模型小」",
    "地面基准 ground_m 是 DSM 低分位，不是测量控制点 ⇒ 一切「离地多少米」都带同一项系统偏移",
    "0.4 m/像素 ⇒ 女儿墙(≈0.5 m)级细节**永久判不出来**，不要拿它当依据",
    "hyps 档距在 28 m 以上 ≥2 m ⇒ 级顶只能给**区间**，点值无意义",
]


def sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def _pts(raw) -> list[tuple[float, float]]:
    out = []
    for p in raw or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            out.append((float(p[0]), float(p[1])))
        elif isinstance(p, dict) and "x" in p and "y" in p:
            out.append((float(p["x"]), float(p["y"])))
    return out


def _area(pts: list[tuple[float, float]]) -> float:
    """鞋带公式（不依赖 shapely，也不受环闭合与否影响）。"""
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


# ══════════════════════════════════════════════════════════════════════════
#  真值侧 / 模型侧：各自切「级」，用**同一条规则**
# ══════════════════════════════════════════════════════════════════════════
def tiers_from_samples(samples: list[tuple[float, float]]) -> list[dict]:
    """samples = [(标高, 该标高以上的水平截面面积)] 按标高升序 ⇒ 掉 ≥DROP_REL 的档。

    返回 [{'y_lo','y_hi','a_above','a_below','drop'}] —— y_lo/y_hi 是**区间**：
    档位之间的真实级顶落在这个区间里，**档内不可分辨**（不要报点值）。
    """
    out = []
    s = sorted(samples, key=lambda t: t[0])
    for i in range(1, len(s)):
        y0, a0 = s[i - 1]
        y1, a1 = s[i]
        if a0 <= 0:
            continue
        d = (a0 - a1) / a0
        if d >= DROP_REL:
            out.append({"y_lo": y0, "y_hi": y1, "a_above": a1, "a_below": a0, "drop": d})
    return out


def model_sections(floors: list[dict]) -> tuple[list[tuple[float, float]], float, float]:
    """模型侧的截面序列 + 最高点。

    顶面标高 = 以下各层 `layer_height` 之和（floor JSON **没有**标高字段，实测确认）。
    最高点 = 最高一层的顶面 + roof.roofT + roof.parapetH（floor10 的 roof 块）。
    """
    fs = sorted(floors, key=lambda g: int(g.get("floor", 0)))
    y, sec, top = 0.0, [], 0.0
    for g in fs:
        lh = float(g.get("layer_height") or 0.0)
        y += lh
        sec.append((round(y, 3), _area(_pts(g.get("outline")))))
        top = y
    r = (fs[-1].get("roof") or {}) if fs else {}
    top_roof = top + float(r.get("roofT") or 0.0)
    top_par = top_roof + float(r.get("parapetH") or 0.0)
    return sec, top_par, top


# ══════════════════════════════════════════════════════════════════════════
#  登记（真值）读写
# ══════════════════════════════════════════════════════════════════════════
def reg_path(name: str) -> str:
    return os.path.join(REG_DIR, name + ".json")


def load_reg(name: str) -> dict | None:
    p = reg_path(name)
    if not os.path.isfile(p):
        return None
    return json.load(io.open(p, encoding="utf-8"))


def verify_reg_sources(reg: dict) -> list[str]:
    """依据（测量产物）此刻还在不在、字节还对不对 ⇒ 不符的逐条点名。"""
    bad = []
    for s in reg.get("_provenance", {}).get("sources", []):
        p = s.get("path", "")
        if not os.path.isfile(p):
            bad.append("依据文件不在了：%s（%s）" % (p, s.get("role", "")))
            continue
        raw = io.open(p, "rb").read()
        if len(raw) != s.get("bytes") or sha12(raw) != s.get("sha12"):
            bad.append("依据**变了**：%s 现 %d 字节 / sha12 %s，登记是 %d / %s（%s）"
                       % (os.path.basename(p), len(raw), sha12(raw),
                          s.get("bytes"), s.get("sha12"), s.get("role", "")))
    return bad


def build_snapshot(name: str) -> int:
    """从测量产物刷出真值登记（只读产物、只写登记）。"""
    srcs = SNAPSHOT_SOURCES.get(name)
    if not srcs:
        print("[FATAL] 没有为 %s 登记测量产物的位置（SNAPSHOT_SOURCES）—— 不许猜。" % name)
        return 2
    tiers = json.load(io.open(srcs[0][0], encoding="utf-8"))
    gauge = json.load(io.open(srcs[1][0], encoding="utf-8"))
    hyps = {float(k): float(v) for k, v in tiers["hyps"].items()}
    src_meta = []
    for p, role in srcs:
        raw = io.open(p, "rb").read()
        src_meta.append({"path": p, "role": role, "bytes": len(raw), "sha12": sha12(raw),
                         "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
    reg = {
        "_provenance": {
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "builder": "qa_external_truth.py --snapshot " + name,
            "sources": src_meta,
            "resolution": RESOLUTION,
            "caveat": CAVEAT,
        },
        "ground_m": tiers["ground_m"],
        "footprint_area_m2": tiers["area_m2"],
        "pca_L_m": tiers["pca_L"],
        "pca_W_m": tiers["pca_W"],
        "anchor_dsm_m": tiers["anchor_dsm"],
        "top_m": gauge["nd_max"],
        "gauge_areas_m2": {g["tag"]: g["area"] for g in (gauge["gaugeA_strict"], gauge["gaugeB"], gauge["gaugeC"])},
        "gauge_family": GAUGE_FAMILY.get(name),
        "hyps": {("%g" % k): v for k, v in sorted(hyps.items())},
        "tiers": tiers_from_samples(sorted(hyps.items())),
        "model_claimed": tiers.get("model"),
    }
    os.makedirs(REG_DIR, exist_ok=True)
    p = reg_path(name)
    io.open(p, "wb").write(json.dumps(reg, ensure_ascii=False, indent=1).encode("utf-8"))
    print("已写登记：%s（%d 字节）" % (p, os.path.getsize(p)))
    for s in src_meta:
        print("  依据 %-46s %9d B  sha12 %s  %s"
              % (os.path.basename(s["path"]), s["bytes"], s["sha12"], s["role"]))
    print("  切出 %d 级：%s" % (len(reg["tiers"]),
                              " / ".join("(%.0f,%.0f]−%.0f%%" % (t["y_lo"], t["y_hi"], t["drop"] * 100)
                                         for t in reg["tiers"])))
    return 0


# ══════════════════════════════════════════════════════════════════════════
#  判据本体
# ══════════════════════════════════════════════════════════════════════════
def check(name: str, floors: list[dict] | None, reg: dict | None,
          verbose: bool = True) -> tuple[str, list[dict], list[str]]:
    """→ (severity 最高档, findings, 打印行)

    findings: [{'sev':'ERROR'|'WARN'|'INFO', 'code':..., 'msg':...}]
    """
    F: list[dict] = []
    L: list[str] = []

    def add(sev, code, msg):
        F.append({"sev": sev, "code": code, "msg": msg})

    if reg is None:
        add("NA", "T0", "未登记外部真值 ⇒ 本项**不适用**（没量过，不是通过）")
        L.append("  [不适用] T0  %s 没有外部真值登记（%s）" % (name, reg_path(name)))
        L.append("           ⇒ 要判这一项，先跑：python qa_external_truth.py --snapshot %s" % name)
        return "NA", F, L

    res = reg["_provenance"]["resolution"]
    sd = res["dsm_vs_gcp"]["sd_m"]
    tol_m = max(Z3 * sd, 0.132)          # 3σ，且不小于量具自身下限
    L.append("  分辨率预算：DSM 对 %d 个 GCP mean %+0.3f / sd %.3f m ⇒ 3σ = %.3f m；"
             "正射 %.1f m/px" % (res["dsm_vs_gcp"]["n"], res["dsm_vs_gcp"]["mean_m"], sd, tol_m,
                               res["ortho_m_per_px"]))
    if floors is None:
        floors = load_floors(name)
    if not floors:
        add("ERROR", "T0", "读不到 floors/floor*.json ⇒ 模型侧没有可比的东西")
        L.append("  [ERROR] T0  读不到 floors/floor*.json")
        return "ERROR", F, L

    sec, top_par, top_last = model_sections(floors)
    m_tiers = tiers_from_samples(sec)
    t_tiers = reg["tiers"]
    if not t_tiers:
        # ★ 显式的「不适用」出口，**不许**靠下游某条判据碰巧红来兜底：
        #   空 tiers 若走正常流程，T1 会打出「级数一致：真值 0 级」这种**看着像结论**的字，
        #   而它实际是「这份登记不足以判」。铁律 60/76：「没量过」与「量过了没问题」
        #   在屏幕上必须不是同一行字。
        add("NA", "T1", "登记里 0 级 ⇒ 这份外部真值**不足以判**级数（不是「一致」，是「没得判」）")
        L.append("  [不适用] T1  登记里 tiers 为空 ⇒ 级数这一项**没有可判的对象**。"
                 "（重跑 --snapshot 若仍为空 ⇒ 是 hyps 或切级规则出了问题，先查那把尺子。）")
        return "NA", F, L

    # ── T1 级数：两侧同一条规则切出来的级，逐级点名缺了哪一级
    L.append("")
    L.append("  T1  竖向分级（两侧同一条规则：截面面积相对上一档掉 ≥%.0f%%）" % (DROP_REL * 100))
    L.append("      真值 %d 级：" % len(t_tiers))
    for t in t_tiers:
        L.append("        y∈(%6.2f,%6.2f]  %10.1f → %10.1f ㎡  −%5.1f%%"
                 % (t["y_lo"], t["y_hi"], t["a_below"], t["a_above"], t["drop"] * 100))
    L.append("      模型 %d 级：" % len(m_tiers))
    for t in m_tiers:
        L.append("        y∈(%6.2f,%6.2f]  %10.1f → %10.1f ㎡  −%5.1f%%"
                 % (t["y_lo"], t["y_hi"], t["a_below"], t["a_above"], t["drop"] * 100))
    matched = set()
    missing = []
    for t in t_tiers:
        hit = None
        for j, m in enumerate(m_tiers):
            # ★ **严格**相交（区间长度 > 0），不是「不分离」。
            #   级界本来就是**区间**（真实级顶落在 y_lo 与 y_hi 之间，档内不可分辨），
            #   所以两个区间**只在端点上相碰**时它们说的是两处不同的收进 —— 把它算作
            #   「同一级」会让真存在的那一级**被判成已覆盖**（实测：会少报一条）。
            if max(m["y_lo"], t["y_lo"]) < min(m["y_hi"], t["y_hi"]):
                hit = j
                break
        if hit is None:
            missing.append(t)
        else:
            matched.add(hit)
    if missing:
        add("ERROR", "T1", "真值切出 %d 级、模型只有 %d 级 ⇒ **缺 %d 级收进**（逐级见下）"
            % (len(t_tiers), len(m_tiers), len(missing)))
        for t in missing:
            add("ERROR", "T1", "缺一级：y∈(%.2f,%.2f] 处屋面面积由 %.1f 掉到 %.1f ㎡（−%.1f%%），"
                               "模型在该区间没有任何体量收进"
                % (t["y_lo"], t["y_hi"], t["a_below"], t["a_above"], t["drop"] * 100))
        L.append("      ✗ 真值有、模型没有的级：")
        for t in missing:
            L.append("        y∈(%6.2f,%6.2f]  −%5.1f%%  （模型此区间无收进）"
                     % (t["y_lo"], t["y_hi"], t["drop"] * 100))
    else:
        add("INFO", "T1", "级数一致：真值 %d 级 / 模型 %d 级，逐级区间都相交"
            % (len(t_tiers), len(m_tiers)))
        L.append("      ✓ 逐级区间都相交（真值 %d / 模型 %d）" % (len(t_tiers), len(m_tiers)))

    # ── T2 最高点
    truth_top = float(reg["top_m"])
    d_top = top_par - truth_top
    L.append("")
    L.append("  T2  最高点  模型 %.2f m（最高层顶 %.2f + roofT + parapetH）  真值 %.2f m  Δ=%+.2f m"
             % (top_par, top_last, truth_top, d_top))
    if abs(d_top) > tol_m:
        add("ERROR", "T2", "最高点差 %+.2f m（模型 %.2f / 实测 %.2f），远超 3σ=%.3f m ⇒ **量到了**"
            % (d_top, top_par, truth_top, tol_m))
        L.append("      ✗ Δ=%+.2f m  > 3σ=%.3f m" % (d_top, tol_m))
    else:
        L.append("      ✓ Δ 在 3σ 之内（%.3f m）" % tol_m)

    # ── T3 底面轮廓面积（真值是下界 ⇒ 只判「模型更大」）
    truth_a = float(reg["footprint_area_m2"])
    m_a = sec[0][1] if sec else 0.0
    rel = (m_a - truth_a) / truth_a if truth_a else 0.0
    L.append("")
    L.append("  T3  底面轮廓面积  模型 %.1f ㎡  真值 %.1f ㎡（**下界**）  相对差 %+.2f%%"
             % (m_a, truth_a, rel * 100))
    ga = reg.get("gauge_areas_m2", {})
    fam = reg.get("gauge_family") or {}
    if ga:
        L.append("      三种口径：%s"
                 % " / ".join("%s=%.2f ㎡" % (k, v) for k, v in ga.items()))
    reps = fam.get("replicates") or []
    if len(reps) == 2 and all(r in ga for r in reps):
        lo, hi = sorted((ga[reps[0]], ga[reps[1]]))
        spread = (hi - lo) / hi * 100 if hi else 0.0
        L.append("      ★ 量具散布（只取**同类**的 %s）：%.2f ㎡（%.3f%%）"
                 % (" vs ".join(reps), hi - lo, spread))
        L.append("         %s 不算进来：%s" % (fam.get("odd_one_out", "?"), fam.get("why", "")))
        L.append("      ⇒ 容差 %.0f%% ÷ 散布 %.3f%% = **%.0f 倍** ⇒ 这个容差判的是"
                 "「模型与实测的**质量团块**差多少」，不是尺子抖动"
                 % (AREA_TOL_REL * 100, spread, AREA_TOL_REL * 100 / max(spread, 1e-9)))
    else:
        # 铁律 60/76：没声明就**不印比值** —— 让「没有可比的对象」长得和「比值很小」不一样
        L.append("      [不适用] 登记里没有声明「哪两把是重复测量」（gauge_family.replicates）"
                 " ⇒ **量具散布这一项不判**（没印比值，不是比值为 0）")
    if rel > 2 * AREA_TOL_REL:
        add("ERROR", "T3", "底面轮廓比实测大 %+.2f%%（>%.0f%%）" % (rel * 100, 2 * AREA_TOL_REL * 100))
        L.append("      ✗ %+.2f%%  >  %.0f%%" % (rel * 100, 2 * AREA_TOL_REL * 100))
    elif rel > AREA_TOL_REL:
        add("WARN", "T3", "底面轮廓比实测大 %+.2f%%（>%.0f%%，但真值是**下界** ⇒ 可能是挑檐，不判 ERROR）"
            % (rel * 100, AREA_TOL_REL * 100))
        L.append("      ⚠ %+.2f%%  >  %.0f%%（下界 ⇒ 不判 ERROR）" % (rel * 100, AREA_TOL_REL * 100))
    else:
        L.append("      ✓ / 或落在下界之内")

    # ── T4 只登记不判的量（说清为什么不判，别让人以为漏了）
    L.append("")
    L.append("  T4  只登记、不判（说清为什么）")
    L.append("      pca 长宽 实测 %.1f × %.1f m —— 模型侧**没有同口径**的量"
             "（顶点加权 ≠ 面积加权），拿去比就是两个东西" % (reg["pca_L_m"], reg["pca_W_m"]))
    L.append("      地面基准 %.2f m / 锚点 DSM %.4f m ⇒ 锚点离地 %.2f m（点值，非最高点）"
             % (reg["ground_m"], reg["anchor_dsm_m"], reg["anchor_dsm_m"] - reg["ground_m"]))
    mc = reg.get("model_claimed")
    if mc:
        L.append("      模型自报分层（测量产物里记着的，仅对照）：%s"
                 % " / ".join("%s @%.1f" % (r[0], r[1]) for r in mc))

    # ── 成因归属：这一条卡在图上，不卡在代码上
    errs = [f for f in F if f["sev"] == "ERROR"]
    if errs:
        L.append("")
        L.append("  ── 成因归属（每条 ERROR 都挂这一条）" + "─" * 30)
        L.append("     层数/层高这一族的**判据侧**已经量到了（差远超 3σ），"
                 "但**修它需要的输入本机没有**：")
        L.append("       · 建施-剖面图（定层数与各层层高）")
        L.append("       · 建施-立面图（定女儿墙/机房/水箱等的真实标高）")
        L.append("       · 建施-总平面图 或 1:500 图廓点坐标（定正负零）")
        L.append("     ⇒ 所以**不许**去改 `data/buildings/c006/**` 或 GLB —— "
                 "在缺图的前提下改，就是把模型挪成一个同样没有依据的样子。")
        L.append("     ⇒ 这一条正确的动作是**要图**，不是改代码。")
    return (errs and "ERROR") or (any(f["sev"] == "WARN" for f in F) and "WARN") or "OK", F, L


def load_floors(name: str) -> list[dict]:
    fs = sorted(glob.glob(os.path.join(BASE, name, "floors", "floor*.json")))
    out = []
    for p in fs:
        try:
            out.append(json.load(io.open(p, encoding="utf-8")))
        except Exception as e:
            print("  [警告] 读不动 %s：%s" % (p, e))
    return out


def run(name: str, verbose: bool = True) -> tuple[int, str]:
    reg = load_reg(name)
    if reg is not None:
        bad = verify_reg_sources(reg)
        if bad:
            print("  [FATAL] 外部真值的**依据**对不上 ⇒ 退出码 2（需重签），不是红也不是绿：")
            for b in bad:
                print("    " + b)
            return 2, "STALE"
    sev, F, L = check(name, None, reg, verbose)
    if verbose:
        print("\n".join(L))
    if sev == "NA":
        return 3, sev
    # 报告落盘（与 qa_structural.py 分开一个文件名，绝不覆盖它的报告）
    os.makedirs(REPORT_DIR, exist_ok=True)
    rp = os.path.join(REPORT_DIR, name + "_exttruth.txt")
    with io.open(rp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("外部真值门禁 %s  %s\n" % (name, time.strftime("%Y-%m-%d %H:%M")))
        fh.write("依据：" + " / ".join("%s(%s)" % (os.path.basename(s["path"]), s["sha12"])
                                     for s in reg["_provenance"]["sources"]) + "\n")
        fh.write("\n".join(L) + "\n")
        fh.write("\n判定：%s\n" % sev)
        for f in F:
            fh.write("  [%s] %s %s\n" % (f["sev"], f["code"], f["msg"]))
    if verbose:
        print("\n  判定：%s   报告：%s" % (sev, rp))
    return (1 if sev == "ERROR" else 0), sev


# ══════════════════════════════════════════════════════════════════════════
#  自证：改坏必须红、对上真值必须绿、空登记不许绿
# ══════════════════════════════════════════════════════════════════════════
def selftest() -> int:
    print("=" * 74)
    print("自证：① 真模型（改坏的那一份）必须红 ② 按真值造的模型必须绿 "
          "③ 空登记不许绿 ④ 依据 sha 不符必须 2")
    reg = load_reg("c006")
    if reg is None:
        print("[FATAL] 没有 c006 登记 ⇒ 自证做不了（先 --snapshot c006）")
        return 2
    real = load_floors("c006")
    n_all = len(real)

    # ① 真模型必须红（且红在 T1 级数上）
    s1, F1, _ = check("c006", real, reg, verbose=False)
    codes1 = sorted({f["code"] for f in F1 if f["sev"] == "ERROR"})
    print("\n① 真模型（11 层 / %.1f m）⇒ %s，ERROR 档位 %s" % (model_sections(real)[1], s1, codes1))
    if s1 != "ERROR" or "T1" not in codes1 or "T2" not in codes1:
        print("   ✗ 对照没如期：真模型本该在 T1/T2 上红 ⇒ 这把尺子看不见真错。")
        return 2
    print("   ✓ 如预期：%d 条 ERROR" % sum(1 for f in F1 if f["sev"] == "ERROR"))

    # ② 按真值造一份模型：把真值切出来的**每一级**都长出来 ⇒ 必须绿
    #   造法是直接从真值的级反推采样点：底面轮廓取真值面积，逐级顶面取该级的 y_hi、
    #   面积取该级的 a_above —— 于是**同一条规则**在模型侧必然切出同样多的级
    #   （这是「对照」，不是「抄答案」：它验的是「规则能不能把对的认成对的」）。
    truth_a = float(reg["footprint_area_m2"])
    top_want = float(reg["top_m"])
    #  ★ 每一级要给它**两个**端点（y_lo/a_below 与 y_hi/a_above）。只给 y_hi 的话，
    #    模型侧的收进会落到「上一级的 y_hi」那一侧 —— 于是真值 (45,50] 在模型里变成
    #    (35,50]，两区间只**在端点相碰** ⇒ 严格相交判据说它们不是同一处收进。
    #    第一版就是这么写的，它把「按真值造的模型」判成缺一级（假红）。
    d: dict[float, float] = {float(reg["tiers"][0]["y_lo"]) - 1.0: truth_a}
    for t in reg["tiers"]:
        d[float(t["y_lo"])] = float(t["a_below"])
        d[float(t["y_hi"])] = float(t["a_above"])
    samples = sorted(d.items())
    # 末段：把最高点抬到实测的 top_m（多出来的那一段由一个 roofT=0.2 的顶板承担）
    samples.append((top_want - 0.2, samples[-1][1]))
    fake, prev = [], 0.0
    for i, (y, a) in enumerate(samples):
        side = (truth_a * (a / samples[0][1])) ** 0.5
        fake.append({"floor": i, "layer_height": y - prev,
                     "outline": _rect(side), "rooms": []})
        prev = y
    fake[-1]["roof"] = {"roofT": 0.2, "parapetH": 0.0}
    s2, F2, L2 = check("c006", fake, reg, verbose=False)
    m2 = model_sections(fake)
    print("\n② 按真值造的模型（%d 层 / 最高点 %.2f m）⇒ %s" % (len(fake), m2[1], s2))
    for f in F2:
        if f["sev"] in ("ERROR", "WARN"):
            print("   [%s] %s %s" % (f["sev"], f["code"], f["msg"]))
    if s2 == "ERROR":
        print("   ✗ 对照没如期：对上真值的模型本该绿 ⇒ 这把尺子会把对的判成错的。")
        return 2
    print("   ✓ 如预期：绿/仅 INFO")

    # ③ 空登记不许绿（也不许报「通过」）
    #   ★ 这里喂的是 ②里那份**已经绿了的**模型 —— 否则 T2/T3 自己的红会把这条断言顶掉，
    #     于是它「红」了，而红的原因跟「空登记」一点关系都没有（铁律 26：对照必须把
    #     要验的那个变量孤立出来；否则它要么假红、要么是空的）。
    reg0 = dict(reg)
    reg0["tiers"] = []
    s3, F3, _ = check("c006", fake, reg0, verbose=False)
    print("\n③ 空 tiers 的登记 ⇒ %s" % s3)
    if s3 == "OK":
        print("   ✗ 空登记被判「通过」 ⇒ 「没量过」与「量过了没问题」在屏幕上同形（铁律 60）。")
        return 2
    print("   ✓ 如预期：不是 OK")

    # ④ 依据 sha 不符必须 2
    reg1 = json.loads(json.dumps(reg))
    reg1["_provenance"]["sources"][0]["sha12"] = "000000000000"
    io_ok = _stale_probe(reg1)
    print("\n④ 依据 sha 不符 ⇒ %s" % ("退出码 2" if io_ok else "★ 没拦住"))
    if not io_ok:
        print("   ✗ 依据变了而判据没喊 ⇒ 会拿着过期真值判活模型。")
        return 2
    print("   ✓ 如预期")

    print("\n" + "=" * 74)
    print("四端都如期：① 真错会红 ② 对的会绿 ③ 空登记不冒充通过 ④ 依据变了会拒判。")
    print("（模型层数 %d；真值级数 %d）" % (n_all, len(reg["tiers"])))
    return 0


def _rect(side: float) -> list[list[float]]:
    h = side / 2.0
    return [[-h, -h], [h, -h], [h, h], [-h, h]]


def _stale_probe(reg: dict) -> bool:
    """把「依据 sha 不符」这条路径**真的走一遍** —— 不靠读代码相信它。"""
    p = os.path.join(REG_DIR, "_stale_probe.json")
    io.open(p, "wb").write(json.dumps(reg, ensure_ascii=False).encode("utf-8"))
    try:
        back = json.load(io.open(p, encoding="utf-8"))
        return bool(verify_reg_sources(back))
    finally:
        os.remove(p)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if "--selftest" in argv:
        return selftest()
    if "--snapshot" in argv:
        if not args:
            print("[FATAL] --snapshot 要一个楼名")
            return 2
        rc = 0
        for n in args:
            rc = max(rc, build_snapshot(n))
        return rc
    if "--all" in argv:
        names = sorted(os.path.splitext(os.path.basename(p))[0]
                       for p in glob.glob(os.path.join(REG_DIR, "*.json"))
                       if not os.path.basename(p).startswith("_"))
        if not names:
            print("[不适用] 一份外部真值登记都没有 ⇒ 本门禁**没量过任何一栋**。"
                  "（这与「全部通过」不是同一句话。）")
            return 3
        worst = 0
        tally = {"OK": 0, "WARN": 0, "ERROR": 0, "NA": 0, "STALE": 0}
        for n in names:
            print("\n" + "─" * 74 + "\n■ " + n)
            rc, sev = run(n, verbose=("-v" in argv))
            tally[sev] = tally.get(sev, 0) + 1
            worst = max(worst, rc)
        print("\n" + "=" * 74)
        print("外部真值门禁：适用 %d 栋 %s；**不适用** %d 栋（未登记 ≠ 通过）"
              % (len(names) - tally["NA"], {k: v for k, v in tally.items() if k != "NA" and v},
                 tally["NA"]))
        return worst
    if not args:
        print(__doc__)
        return 2
    worst = 0
    for n in args:
        print("■ " + n)
        rc, _sev = run(n)
        worst = max(worst, rc)
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
