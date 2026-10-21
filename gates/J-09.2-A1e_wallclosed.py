# -*- coding: utf-8 -*-
r"""判据 J-09.2-A1e：**外墙按交付口径闭合了没有** —— 墙与墙之间还漏不漏。

对应方案 §9.2 轨A·A1「逐类构件覆盖率」之后的一件：**墙这一类自己要接得上**。
来源是用户判词「有个问题，墙与墙之间没有接上」（看的是交付包里的 C006 模型）。

四件套（§10.0.1）：
  ① 量交付件本身 —— `demo/_gen/c006-floors.glb`（链的产物）与包内 model 件，不是日志
  ② 量具写明      —— `tools/wall_close.py`（**判据只有这一份**，本闸门 import 它，铁律 196）
                     ＋ **独立来源**：图纸 DXF 的 `4.2墙体` 层（另一条链的产物）
  ③ 盲区声明      —— 见下（★ 图纸那一路**只做了 F1**，这是实测范围不是免责声明）
  ④ 正对照必配    —— 三条：合成两墩一缝（必补 1）／合成两柱（必补 0）／补前件冒充补后件（必报 >0）

★ 背景（全部实测）：libs3d 链 `build8.py::bridge_gaps` 原文注释「**墙实体仍按图纸不补**」，
  它只给门造门头（754 扇门 / 754 个门头），**窗洞一个都不补**
  ⇒ 交付逐层件里量到 **709 条 ≥50 mm 的缝**，逐条在 z=1000/2850/3300 三个高度上问，
  **100% 是整层高的洞、0 条有门头**（=过程/_scratch/probe_gap_height.py）。
  交付口径（实景三维 LOD1.3 = 棱柱体）要求外墙闭合、不表达门窗洞 ⇒ 该补。

★ 判据（本闸门查的）：
  A. **补块守恒**：交付件每层的面数 == 链 meta 记的「输入面数 + 该层计划补块面数」（逐层比，不比总数）。
  B. **原件没丢**：交付件每层的包围盒必须落在**原件搬过来之后**的包围盒里（补块是加法，不许把墙改小）。
  C. **图纸校核（独立来源，只做 F1）**：先按墙足迹把该层对应的**图幅**测出来（要写分辨力），
     再量「交付件的墙足迹」比「原件的墙足迹」在图纸 240 宽墙带里**多盖了多少**。
  D. **正对照三条**（缺一不可）。
  E. **非空断言**：层数 0 / 面数 0 / 补块 0 ⇒ rc=4「没量到」，不当成绿。

★ 盲区（必须声明；盲区内的否定判词不算证据）：
  ① **图纸那一路只做了 F1**：图幅阵 L/R × 11 行的识别要 22 次并集（~40 s/层），
     其余 10 层只判守恒与包络，**没有第二来源**核它们的补块落位。
  ② **判据只看几何、不看用途**：它分不出「窗洞」与「本该通着的门洞」，也分不出「外墙」与「内墙」
     —— 凡是两端相望面同厚同高的口子都补（含内墙上的洞）。本条**不给「补的都是窗」这个结论**。
  ③ **>6 m 的口子一律不补**（当厅/中庭），这是**决定不是测量**：代价 = 那 9 条 5.5~6 m 的缝留着。
  ④ **补的是棱柱体**，不是门窗扇/过梁/雨篷（那是近景构件，方案 §6.8.5，本工具不做）。
  ⑤ 交付件是**合并后**的 GLB：`split()` 按**共享边**分块，重合但不共享边的两块仍算两块
     ⇒ 「块数」这个量在本判据里**不用**（用了会把补块自己数进去）。
  ⑥ 独立校核的能量**只到「离最近的图纸墙线多远」**：它证明补块没落在空地上，
     **不能**证明那一处图纸上画的就是窗。

用法: python gates/J-09.2-A1e_wallclosed.py                      # 默认量 demo/_gen/c006-floors.glb
     python gates/J-09.2-A1e_wallclosed.py --json gates/_out/J-09.2-A1e.json
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
TOOLS = os.path.join(CDUT, "tools")
sys.path.insert(0, TOOLS)


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    md = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(md)
    return md


WC = _load("wall_close", os.path.join(TOOLS, "wall_close.py"))
p1 = _load("pack_d1", os.path.join(TOOLS, "pack_d1.py"))

DELIV = os.path.join(CDUT, "demo", "_gen", "c006-floors.glb")
META = os.path.join(CDUT, "demo", "_gen", "c006-floors-meta.json")
# ★ 2026-10-13：墙闭合之后**又过了一手**（把 floor0 的板换成 AutoCAD 那条链画的，
#   tools/slab_into_floor.py）。它只动 floor0 的**一块板**，墙闭合的加法全在。
#   F 那条判据要核的是「用户打开的那件」，参照物必须是**这一手之后**的产物；
#   拿 DELIV 当参照物，会把「如实换了板」报成「不同源」（铁律 192 的形状：参照物退化）。
DELIV_POST = os.path.join(CDUT, "demo", "_gen", "c006-floors-slab.glb")
SLAB_NODE = "floor0"
PACK_MODEL = os.path.join(CDUT, "packs", "cdut-main", "c006", "model",
                          "c006-building.glb")
# ★★ 2026-10-14 换链：包内件**不再是上面那条 libs3d 链的产物**。用户 2026-10-14 裁定
#    包内件真源 = **正式件** `rebuild/06_su/c006_su.glb`（重建链 export_sheet→recognize→
#    redraw→build3d→su_step2_build.rb 出的 SU 件，再由 tools/su_obj_to_glb.py 只转格式）。
#    ⇒ F 的参照物必须换成它（铁律 192：参照物与交付件**同作用域**）。
#    旧写法把参照物定成 DELIV_POST ⇒ 换链后必然报「包内缺节点 floor0」——
#    那是**参照物错了**，不是件错了：libs3d 链每层是**一个**几何叫 `floor0`，
#    正式件是每层拆成 `floor0__WALL` / `floor0__SLAB` … **六个**子几何。
#    ★ A/B/C 三条量的仍是 libs3d 那条链的产物（demo/_gen/c006-floors.glb）—— 它仍该死守，
#      但**它已经不喂包了**：这一条写进盲区，不许读者默认包内件被 A/B/C 保过。
# ★ 2026-10-17 换链（用户令「现在开工换 FreeCAD」）：正式件 = **FreeCAD 出的**
#   `c006_fc.glb`（contours → contours_to_fc.py → fc_obj_to_glb.py）。F 腿比的仍是
#   「包内件 == 正式件」这一件事，只是参照物跟着换到同作用域（铁律 192）。
#   SU 件 `c006_su.glb` 仍在盘上作退路；要拿它当参照物设 `CDUT_FORMAL_GLB=c006_su.glb`。
FORMAL_GLB = os.path.join(CDUT, "rebuild", "06_su",
                          os.environ.get("CDUT_FORMAL_GLB") or "c006_fc.glb")
N_FLOOR = 11
F1_TILE = ("L", 0)          # F1 对应的图幅：由 过程/_scratch/_ident_tile.py 实测选出（88.7% vs 60.0%）


def synth(thick, run, gap, height=3600.0):
    """合成「一段墙」：厚 thick、长 run、高 height 的方盒，放在 x∈[0,thick]、z∈[0,run]。"""
    b = trimesh.creation.box(extents=[thick, height, run])
    b.apply_translation([thick / 2.0, height / 2.0, run / 2.0])
    return b


def stub_pair(thick, gap, run=6000.0, plate=(30000.0, 30000.0)):
    """两段**共线**的墙中间留 gap 的缝 + 一块薄楼板 —— 「同一面墙被挖了个洞」的**逐层件形状**。

    ★ 那块板不是装饰，是**判据能工作的前提**：`vertical_axis()` 按「跨度最小」认竖直轴
      （逐层件实测 129 × 3.72 × 84 m ⇒ 最小的是层高）。孤零零一对墙垛的最小跨度是**墙厚 240**
      ⇒ 竖直轴被认成厚度方向，整条判据在合成件上无分辨力 ——
      实测后果：正对照①第一版就是这么报「该补 1 根，实补 0 根」的假红。
      补上 30×30 m 的板之后跨度 = x 30000 / y 3720 / z 30000，最小是 y ⇒ 与真件同形。
    ★ 板**不参与**候选：`wall_components` 只认 ext ≥ 0.8×层高 的块，板厚 120 认不成墙；
      且它和墙垛不共享边 ⇒ `split()` 把它们分开（见盲区⑤）。
    """
    a = synth(thick, run, gap)
    b = synth(thick, run, gap)
    b.apply_translation([0.0, 0.0, run + gap])
    slab = trimesh.creation.box(extents=[plate[0], 120.0, plate[1]])
    slab.apply_translation([plate[0] / 2.0 - thick / 2.0, -60.0, (2 * run + gap) / 2.0])
    return trimesh.util.concatenate([a, b, slab])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliv", default=DELIV)
    ap.add_argument("--meta", default=META)
    ap.add_argument("--json", default=os.path.join(HERE, "_out", "J-09.2-A1e.json"))
    a = ap.parse_args()

    fails, rec = [], {}
    ctrl = []

    # ---------- ① 交付件本身：非空断言 ----------
    if not os.path.exists(a.deliv):
        print("!! 没有交付件 %s ⇒ **没量到**（不是通过）" % a.deliv)
        return 4
    sc = trimesh.load(a.deliv, force="scene")
    gn = sorted(sc.geometry.keys(), key=lambda s: int(s[5:]) if s.startswith("floor") else 99)
    if len(gn) != N_FLOOR:
        print("!! 交付件楼层数 %d ≠ %d ⇒ **没量到**" % (len(gn), N_FLOOR))
        return 4
    if not os.path.exists(a.meta):
        print("!! 没有链 meta %s ⇒ 判据 A 的期望值取不到 ⇒ **没量到**" % a.meta)
        return 4
    meta = json.load(open(a.meta, encoding="utf-8"))
    wc_meta = meta.get("wall_close") or {}
    per = {r["node"]: r for r in wc_meta.get("per_floor", [])}
    if len(per) != N_FLOOR:
        print("!! meta 里逐层记录 %d 条 ≠ %d ⇒ **没量到**" % (len(per), N_FLOOR))
        return 4

    print("交付件      : %s（%d 层）" % (a.deliv, len(gn)))
    print("链 meta     : 补 %d 根 / 跳 %d 条 / 未复核 %d / 补后残留 %d"
          % (wc_meta.get("gaps_vs_filled", {}).get("filled", -1),
             wc_meta.get("gaps_vs_filled", {}).get("skipped", -1),
             wc_meta.get("unmeasured", -1), wc_meta.get("residual_after_close", -1)))
    if per.get("floor0", {}).get("filled", 0) == 0:
        print("!! 一层补块都没有 ⇒ 遍历型判据会扫空集合恒绿 ⇒ **没量到**")
        return 4

    # ---------- A 补块守恒（逐层）----------
    badA = []
    for n in gn:
        got = int(len(sc.geometry[n].faces))
        want = int(per[n]["faces_in"]) + int(per[n]["faces_added"])
        if got != want:
            badA.append("%s 面数 %d ≠ 输入%d + 补块%d = %d"
                        % (n, got, per[n]["faces_in"], per[n]["faces_added"], want))
    rec["A_faces"] = {"ok": not badA, "bad": badA,
                      "total_added": int(sum(per[n]["faces_added"] for n in gn))}
    print("\nA 补块守恒  : 逐层「输出面数 = 输入 + 计划补块」 %s（共补 %d 面）"
          % ("✓ 11/11" if not badA else "✗ %s" % badA[:3], rec["A_faces"]["total_added"]))
    if badA:
        fails.append("A:交付件某层面数与链 meta 对不上 %s" % badA[:3])

    # ---------- B 原件没丢：交付件的包络必须落在「原件搬过来之后」的包络里 ----------
    # ★ 参照物必须与交付件**同作用域**（铁律 192）：T 只能问链要，不许在本闸门里第二次实现它。
    #   本闸门第一版手搓 T（只填 T[0,0]/T[2,2]/平移）**漏了 T[1,1]=0.001** ——
    #   竖直方向没缩比例，参照物被撑成 1000 倍高 ⇒ floor1..floor10 全报「包络超出原件」；
    #   floor0 之所以“过”，只是因为它 hi 那头的超出量是**负数**（把两处都盖住了），
    #   也就是「判据在整屏上假红、在单点上假绿」的同一形状（铁律 196）。
    tr = meta.get("transform", {})
    lib_o, pk_o = tr.get("libs3d_origin_mm"), tr.get("cdut3d_origin_mm")
    if not lib_o or not pk_o:
        print("!! meta 里没有 libs3d/cdut3d 两个原点 ⇒ 参照物的口径取不到 ⇒ **没量到**")
        return 4
    sx = tr.get("axis_sign", {}).get("x", 1)
    sz = tr.get("axis_sign", {}).get("z", 1)
    T = p1.xform(sx, sz, {"x_mm": lib_o[0], "y_mm": lib_o[1]},
                 {"ox": pk_o[0], "oy": pk_o[1]})
    # 独立复核：xform 由**原点对**算出的数，必须与 meta 记的那几个标量一致
    # （两处写同一个数一致证明不了它是对的，但**不一致**一定有一处错 —— 铁律 018）
    # 容差按**记录自己的精度**给：meta 的 dx_m/dz_m 是 `round(...,3)` 的米 ⇒ 末位 1 mm，
    # 舍入误差上限 0.5 mm = 5e-4 m（实测：dz 真值 36.994400 记成 36.994，差 0.4 mm）。
    # ★ 这不是「判据松了」：比的就是那条**记录**，它的精度就到 mm。
    TOL_REC_M = 5e-4
    meta_vs_xform = []
    for got, want, tol, nm in (
            (float(T[0, 0]), float(sx) * float(tr.get("scale", 0.001)), 1e-9, "scale·sx"),
            (float(T[1, 1]), float(tr.get("scale", 0.001)), 1e-9, "scale·sy"),
            (float(T[0, 3]), float(tr.get("dx_m", 0.0)), TOL_REC_M, "dx"),
            (float(T[2, 3]), float(tr.get("dz_m", 0.0)), TOL_REC_M, "dz")):
        if abs(got - want) > tol:
            meta_vs_xform.append("%s: xform 给 %.6f，meta 记 %.6f（超 %.0e）"
                                 % (nm, got, want, tol))
    rec["B_meta_vs_xform"] = {"ok": not meta_vs_xform, "bad": meta_vs_xform,
                              "tol_note": "记录精度 1 mm（round(...,3) 米），容差 5e-4 m"}
    if meta_vs_xform:
        fails.append("B:meta 的变换标量与 xform(原点对) 对不上 %s" % meta_vs_xform)

    badB = []
    for k, n in enumerate(gn):
        src = os.path.join(p1.LIBS3D_DELIV, "c006-v8-f%d-colored.glb" % (k + 1))
        if not os.path.exists(src):
            badB.append("%s 找不到原件 %s" % (n, os.path.basename(src)))
            continue
        m0 = p1.apply_T(p1.load_mesh(src), T)
        b1 = np.asarray(sc.geometry[n].bounds, float)
        b0 = np.asarray(m0.bounds, float)
        tol = 1e-3          # 1 mm：mm→m 的浮点尾数；补块只往墙里压（PAD_MM<墙厚），不许撑出去
        if not (np.all(b1[0] >= b0[0] - tol) and np.all(b1[1] <= b0[1] + tol)):
            over = np.maximum(np.maximum(b0[0] - b1[0], b1[1] - b0[1]), 0.0)
            badB.append("%s 包络超出原件 %s（补块是加法，不许把墙改小）"
                        % (n, np.round(over, 4).tolist()))
    rec["B_envelope"] = {"ok": not badB, "bad": badB}
    print("B 原件没丢  : 交付件逐层包络落在原件包络内 %s"
          % ("✓ 11/11" if not badB else "✗ %s" % badB[:3]))
    if badB:
        fails.append("B:%s" % badB[:3])

    # ---------- C 图纸校核（独立来源，只做 F1）----------
    src1 = os.path.join(p1.LIBS3D_DELIV, "c006-v8-f1-colored.glb")
    m0 = p1.load_mesh(src1)
    fills0 = WC.analyze(m0)["filled"]
    # 原件与补后件在**件自己的坐标系（毫米）**里各量一次图纸覆盖率
    m1, _ = WC.close(m0)
    cov = {}
    for tag, mesh in (("orig", m0), ("closed", m1)):
        cov[tag] = WC.dwg_band_check(mesh, fills0 if tag == "closed" else [],
                                     F1_TILE[0], F1_TILE[1])
    if cov["orig"] is None or cov["closed"] is None:
        print("\nC 图纸校核  : **没量到**（取不到图纸墙带）")
        rec["C_dwg"] = {"measured": False}
        fails.append("C:图纸校核没量到")
    else:
        # 交叠率：墙足迹盖住图纸墙带的比例（原件 vs 补后件）
        rec["C_dwg"] = {"tile": "%s%d" % F1_TILE, "measured": True,
                        "orig": cov["orig"], "closed": cov["closed"]}
        print("\nC 图纸校核  : 图幅 %s%d（按墙足迹实测选出）" % F1_TILE)
        print("   原件墙足迹落在墙带里 %5.1f%%   补后 %5.1f%%"
              % (cov["orig"]["orig_on_band_pct"], cov["closed"]["orig_on_band_pct"]))
        print("   补块 %d 块 / %.1f m²，落图纸墙带 **%.1f%%**（整层随机点地板 %.2f%% ⇒ %.1f×）"
              % (cov["closed"]["blocks"], cov["closed"]["filler_area_m2"],
                 cov["closed"]["on_band_pct"], cov["closed"]["random_floor_pct"],
                 cov["closed"]["on_band_pct"] / max(cov["closed"]["random_floor_pct"], 1e-9)))
        print("   离最近图纸墙线 中位 %.0f mm / max %.0f mm，超 2000 mm 的块 **%d**"
              % (cov["closed"]["dist_to_drawn_line_mm"]["median"],
                 cov["closed"]["dist_to_drawn_line_mm"]["max"],
                 cov["closed"]["dist_to_drawn_line_mm"]["over_2000"]))
        d = cov["closed"]["dist_to_drawn_line_mm"]
        if cov["closed"]["on_band_pct"] < 4.0 * cov["closed"]["random_floor_pct"]:
            fails.append("C:补块落图纸墙带只 %.1f%%，不足地板的 4 倍（%.2f%%）"
                         % (cov["closed"]["on_band_pct"], cov["closed"]["random_floor_pct"]))
        if d["over_2000"]:
            fails.append("C:有 %d 块补块离最近图纸墙线超 2000 mm（落在空地上）" % d["over_2000"])

    # ---------- D 正对照 ----------
    # ① 合成两墩一缝：必须**恰好补 1 根**，且宽度≈缝宽
    g = 2000.0
    mi = WC.analyze(stub_pair(240.0, g))
    ok1 = len(mi["filled"]) == 1 and abs(mi["filled"][0]["d_mm"] - g) < 60.0
    ctrl.append({"name": "合成两墩一缝（240 厚 / 缝 %.0f）" % g, "expect": "恰好补 1 根",
                 "got": "补 %d 根" % len(mi["filled"]), "ok": ok1})
    print("\n正对照①     : 合成两墩一缝 %4.0f mm ⇒ 该补 1 根，实补 %d 根  %s"
          % (g, len(mi["filled"]), "✓" if ok1 else "✗ 判据无分辨力"))
    if not ok1:
        fails.append("对照①:合成两墩一缝该补 1 根实补 %d 根" % len(mi["filled"]))

    # ② 合成两柱（厚 600）：厚度闸必须拦下 ⇒ 补 0 根
    mj = WC.analyze(stub_pair(600.0, 3000.0))
    ok2 = len(mj["filled"]) == 0
    ctrl.append({"name": "合成两柱（600 厚 / 缝 3000）", "expect": "补 0 根",
                 "got": "补 %d 根" % len(mj["filled"]), "ok": ok2})
    print("正对照②     : 合成两柱 600 厚缝 3000 ⇒ 该补 0 根，实补 %d 根  %s"
          % (len(mj["filled"]), "✓" if ok2 else "✗ 厚度闸没牙（会把外廊柱堵死）"))
    if not ok2:
        fails.append("对照②:合成两柱该补 0 根实补 %d 根（外廊会被堵）" % len(mj["filled"]))

    # ③ 拿**补前**的件冒充补后件 ⇒ 闭包尺子必须报 >0
    _, resid0 = WC.residual_on(m0, m0, [])
    ok3 = len(resid0) > 0
    ctrl.append({"name": "F1 补前件冒充补后件", "expect": "闭包尺子报 >0",
                 "got": "报 %d 条" % len(resid0), "ok": ok3})
    print("正对照③     : 拿 F1 **补前**件冒充补后件 ⇒ 该报 >0，实报 %d 条  %s"
          % (len(resid0), "✓" if ok3 else "✗ 闭包尺子恒绿"))
    if not ok3:
        fails.append("对照③:补前件上闭包尺子报 0 ⇒ 恒绿，没分辨力")

    rec["controls"] = ctrl

    # ---------- F 量的是不是**用户打开的那一件** ----------
    # ★ 「量交付件本身」（§10.0.1 ①）：demo/index.html 读的是包目录，用户看到的是
    #   packs/cdut-main/c006/model/c006-building.glb。A/B 量的是链产物
    #   demo/_gen/c006-floors.glb —— 若两者不同源，A/B 全绿也证明不了用户打开的那件是对的。
    #   第一版这里只写了 `os.path.exists`：存在≠同源（铁律 17 的同一形状）。
    #   ★ 2026-10-13 起，墙闭合之后还有一手换楼板（只动 floor0 的一块板）⇒ 参照物换成
    #     DELIV_POST。**同时守住**：DELIV_POST 与 DELIV 之间除 floor0 外必须逐位相同 ——
    #     否则「参照物被换掉」本身就成了新的逃逸口。
    #   ★★ 2026-10-14 换链（用户裁定包内件真源 = 正式件 06_su）后，上面那套**前提变了**：
    #     包内件与 demo/_gen/ 那两件**不再有上下游关系** ⇒ F 不能拿它们当参照物。
    #     现在 F = 「包内件 == rebuild/06_su/c006_su.glb」：腿一逐字节、腿二逐 (层,类) 子几何。
    #     而 A/B/C 三条仍只对 **libs3d 那条链的产物**发言 —— 那是**已知的覆盖缺口**，
    #     写在下面盲区里，不许默认读者以为包内件也被 A/B/C 保过。
    def f_bad(ref_scene, pack_scene, names):
        """逐节点核「包内件 == 链产物」：面数 + 包络。返回不符的清单（空 = 同源）。"""
        out = []
        for n in names:
            if n not in pack_scene.geometry:
                out.append("包内缺节点 %s" % n); continue
            ga, gb = ref_scene.geometry[n], pack_scene.geometry[n]
            if int(len(ga.faces)) != int(len(gb.faces)):
                out.append("%s 包内面数 %d ≠ 链产物 %d" % (n, len(gb.faces), len(ga.faces))); continue
            if not np.allclose(np.asarray(ga.bounds, float),
                               np.asarray(gb.bounds, float), atol=1e-9):
                out.append("%s 包内包络 ≠ 链产物包络" % n)
        return out

    def f_bad_su(su_scene, pack_scene):
        """逐 **(层,类)** 子几何核「包内件 == 正式件 06_su」：名字集合 + 面数 + 包络。

        ★ 与上面 `f_bad` 的区别是**键不一样**：libs3d 链每层一个几何叫 `floor0`，
          正式件每层拆成 `floor0__WALL` / `floor0__SLAB` … 六个。拿旧键去查新件，
          报出来的会是「包内缺节点 floor0」——**看着像件缺东西，其实是尺子换了对象**。
        """
        out = []
        na, nb = set(su_scene.geometry), set(pack_scene.geometry)
        for n in sorted(na - nb):
            out.append("包内缺节点 %s" % n)
        for n in sorted(nb - na):
            out.append("包内多节点 %s" % n)
        for n in sorted(na & nb):
            ga, gb = su_scene.geometry[n], pack_scene.geometry[n]
            if int(len(ga.faces)) != int(len(gb.faces)):
                out.append("%s 包内面数 %d ≠ 正式件 %d" % (n, len(gb.faces), len(ga.faces))); continue
            if not np.allclose(np.asarray(ga.bounds, float),
                               np.asarray(gb.bounds, float), atol=1e-6):
                out.append("%s 包内包络 ≠ 正式件包络" % n)
        return out

    badF, bad_swap = [], []
    ref_path = DELIV
    if os.path.exists(DELIV_POST):
        ref_path = DELIV_POST
        sp_pre = sc                                    # 墙闭合那一步的产物（A/B/C 量的就是它）
        sp_post = trimesh.load(DELIV_POST, force="scene")
        for n in gn:
            if n == SLAB_NODE:
                continue
            if n not in sp_post.geometry:
                bad_swap.append("%s 不在换板产物里 %s" % (n, os.path.basename(DELIV_POST)))
                continue
            ga, gb = sp_pre.geometry[n], sp_post.geometry[n]
            if int(len(ga.faces)) != int(len(gb.faces)):
                bad_swap.append("换板这一步动了 %s（面数 %d→%d）—— 它只该动 %s"
                                % (n, len(ga.faces), len(gb.faces), SLAB_NODE))
            elif not np.allclose(np.asarray(ga.bounds, float),
                                 np.asarray(gb.bounds, float), atol=1e-9):
                bad_swap.append("换板这一步动了 %s 的包络" % n)
        sc = sp_post
        badF += bad_swap
    ctrlF_ok = None
    same_bytes = None
    if not os.path.exists(PACK_MODEL):
        badF.append("包内 model 件不存在 %s" % PACK_MODEL)
    elif not os.path.exists(FORMAL_GLB):
        # ★ 参照物不在 ⇒ 这是「**没量到**」，不是「绿」（铁律 199/137 的同一形状）。
        badF.append("正式件不在 %s ⇒ F **没量到**（不许当绿）" % FORMAL_GLB)
    else:
        # 腿一：逐字节同源。包内件就是正式件的副本（build_pack ②.5 是搬、不是再造）。
        same_bytes = (hashlib.sha256(open(PACK_MODEL, "rb").read()).hexdigest()
                      == hashlib.sha256(open(FORMAL_GLB, "rb").read()).hexdigest())
        if not same_bytes:
            badF.append("包内件与正式件**不是同一份字节**")
        # 腿二：逐 (层,类) 子几何 —— 名字集合 + 面数 + 包络。防「两份一起被换成同一个错东西」
        #   （纯粹的同源检查对「两边同错」是瞎的；这条腿至少把「结构变了」捅出来）。
        su_sc = trimesh.load(FORMAL_GLB, force="scene")
        sp = trimesh.load(PACK_MODEL, force="scene")
        badF += f_bad_su(su_sc, sp)
        # 正对照④：把包内 `floor0__SLAB` 挪 1 m 冒充 ⇒ 腿二必须红（证明它有分辨力）
        try:
            sp_bad = trimesh.load(PACK_MODEL, force="scene")
            _keys = sorted(sp_bad.geometry)
            _k = "floor0__SLAB" if "floor0__SLAB" in sp_bad.geometry else _keys[0]
            sp_bad.geometry[_k].apply_translation([1.0, 0.0, 0.0])
            ctrlF_ok = bool(f_bad_su(su_sc, sp_bad))
            _ctrl_key = _k
        except Exception as e:
            ctrlF_ok = False
            _ctrl_key = "?"
            print("  正对照④ 跑不起来：%s" % e)
    rec["F_pack_same_source"] = {"ok": not badF, "bad": badF,
                                 "pack_model": PACK_MODEL,
                                 "reference": os.path.basename(FORMAL_GLB),
                                 "same_bytes_sha256": same_bytes,
                                 "swap_touched_only_%s" % SLAB_NODE: not bad_swap,
                                 "control_shift_1m_fired": ctrlF_ok,
                                 "note": "2026-10-14 换链后 F 的参照物 = **正式件 06_su**"
                                         "（原先比的是 libs3d 链产物 c006-floors-slab.glb，"
                                         "换链后那件**已经不喂包**）。A/B/C 三条量的仍是 libs3d 那条链。"}
    print("\nF 同源      : 包内 model vs 正式件（%s）%s"
          % (os.path.basename(FORMAL_GLB),
             "✓ 逐字节同一份 + 逐 (层,类) 子几何全等（%s）" % os.path.basename(PACK_MODEL)
             if not badF else "✗ %s" % badF[:3]))
    print("  参照物守门  : 换板那一步只动了 %s、其余 10 层没碰 %s（★ 那是 libs3d 链的产物，"
          "与本包已无上下游关系，只作那条链的自检）"
          % (SLAB_NODE, "✓" if not bad_swap else "✗ %s" % bad_swap[:2]))
    if ctrlF_ok is not None:
        print("  正对照④     : 把包内 %s 挪 1 m 冒充 ⇒ 该红，实红 %s"
              % (_ctrl_key, "✓" if ctrlF_ok else "✗ 没红"))
    if badF:
        fails.append("F:包内 model 与正式件不同源 %s" % badF[:3])
    if ctrlF_ok is False:
        fails.append("F 的正对照（挪 1 m）该红而没红 ⇒ 这条判据没牙")

    # ---------- 判词 ----------
    print("\n===== 判词 =====")
    printed = [c for c in ctrl if not c["ok"]]
    if fails or printed:
        print("  FAIL  rc=1   未过项:", (fails + ["对照:%s" % c["name"] for c in printed])[:5])
        rc = 1
    else:
        print("  PASS  rc=0   补块守恒 11/11 · 包络 11/11 · 图纸校核取自 %s%d · 三条正对照全响"
              % F1_TILE)
        rc = 0
    print("  ★ 盲区：图纸校核**只做了 F1**（其余 10 层无第二来源）；判据只看几何、不看用途；"
          ">6 m 的口子按决定不补")
    print("  ★★ 覆盖缺口（2026-10-14 换链引入）：A/B/C 三条量的都是 **libs3d 那条链的产物**"
          "（demo/_gen/c006-floors.glb）；包内件现在是**正式件 06_su**（另一条链），"
          "F 只证「包内件 == 正式件的副本」，**不证**包内件的墙闭合。"
          "包内件的几何由重建链自己的判据（J-10.8-01 build3d / J-10.8-02 su / J-10.2-02 层错位）保证。")

    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        doc = {"schema": "cdut3d-gate/1", "gate": "J-09.2-A1e", "pass": rc == 0,
               "deliv": a.deliv, "meta": a.meta,
               "pack_model": PACK_MODEL,
               "pack_model_sha256": (hashlib.sha256(open(PACK_MODEL, "rb").read()).hexdigest()
                                     if os.path.exists(PACK_MODEL) else None),
               "checks": rec, "fails": fails,
               # ★ 顶层再铺一份**只含 bool** 的 controls：`demo/sys.html` 的「正对照」那一格
               #   数的是 `json["controls"]` 里的 bool 叶子（见 `tools/build_sys_page.py::ctl_count`）。
               #   只把详细清单放 `checks.controls`（list）⇒ 页面按 dict 取，取不到就记「—」，
               #   于是一条**有三条对照**的判据在页面上看着像没有对照。
               "controls": {"合成两墩一缝该补1根": ok1, "合成两柱该补0根": ok2,
                            "补前件冒充补后件该报>0": ok3},
               "blind": ["图纸校核只做 F1", "只看几何不看用途", ">6 m 不补是决定",
                         "补的是棱柱体，不是门窗扇",
                         "★ A/B/C 只量 libs3d 链产物 demo/_gen/c006-floors.glb；"
                         "2026-10-14 换链后包内件是正式件 06_su（另一条链）⇒ 本闸不判包内件的墙闭合"]}
        open(a.json, "wb").write(
            json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n"))
        print("  写出:", a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
