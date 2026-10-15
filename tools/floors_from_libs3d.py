# -*- coding: utf-8 -*-
"""用 **libs3d/c006 那条链已经建好、且已过它自己判据的逐层交付件**，重新组装交付包的楼上部分。

★ 为什么(用户三条判词 2026-10-12 全指楼板)：
  原路是 `tools/split_floors.py` —— 把 gym3d 那坨**烘死的单网格按高度无损切**成 12 个节点。
  那条链的楼板是**整块矩形**(板面积 / 整栋外接矩形 ≈ 87%，而且四层不变)，
  实测 3F–6F 各多铺 3400–3660 m²，合计约 **1.4 万 m² 幽灵楼板**
  ⇒ 就是「每一层的楼板又出来了」「八角厅的楼顶被盖住」「楼板在转角的地方突出了」。
  libs3d 那条链的楼板是**按本层墙网闭合出来的**(板/外接矩形 ≈ 54%、随层收进)，
  这正是用户说「前面 libs3d 解决了的」那一版。见 _scratch/slab_compare.py 的实测两列表。

★ 本脚本**不建几何**：只做坐标搬运(毫米→米、Z 上→Y 上、libs3d 全局原点 → 包原点)。
  变换与 `tools/pack_d1.py` 对 B1 用的是**同一个**(同一函数 xform、同一原点口径)，
  所以搬进来的楼上各层与包内已有的 B1 天然同框、可**原样替换**原先那 12 个节点。

★★ 为什么参照物**不是**包内 floor0(铁律 187：基线与期望值必须来自两次不同读数)：
  pack_d1.py 里轴号表的参照物是包内 floor0；本脚本要**替掉** floor0，
  若仍拿它当参照，搬运与被搬运就同源了 ⇒ 整栋镜像也看不出来。
  故这里另取 **gym3d 原件** `c006-building.glb` 的平面外框当参照物 ——
  它是另一条链、另一个文件的一次独立读数。

判据四件套(§10.0.1)：① 量**写出的** GLB ② 量具与参照物写明 ③ 盲区声明 ④ 正对照必配

用法:
  python tools/floors_from_libs3d.py --out <楼上.glb> [--meta out.json]
"""
import argparse
import importlib.util
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# 复用 pack_d1 的原点口径与变换 —— 不另写一份，避免「同一个量两处实现」
_spec = importlib.util.spec_from_file_location("pack_d1", os.path.join(HERE, "pack_d1.py"))
p1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p1)

# 补外墙洞口 —— **判据只有 wall_close 那一份**，本脚本与闸门都 import 它（铁律 196）
_wc = importlib.util.spec_from_file_location("wall_close", os.path.join(HERE, "wall_close.py"))
WC = importlib.util.module_from_spec(_wc)
_wc.loader.exec_module(WC)

LIBS3D_DELIV = r"D:\项目\libs3d\browser\示例模型"
LIBS3D_FULL = os.path.join(LIBS3D_DELIV, "c006-v8-colored.glb")   # 独立读数②：整件面数
REF_GYM = r"D:\项目\gym3d\gym3d\data\buildings\c006\c006-building.glb"  # 独立参照物（另一条链）

N_FLOOR = 11                 # 地上 11 层（用户 2026-10-12 裁定「11 层，接受 4 米」）
ALIGN_TOL_M = 0.5            # 平面落位容差：两条链墙厚/配对规则不同，给半米
CTRL_MIN_M = 5.0             # 轴号表的分辨力下限：错的符号组合必须差 ≥5 m，否则算分辨不出
ELEV_TOL_M = 0.30            # 竖向闭合容差

BLIND = [
    "**这些层的几何不是本仓建的**：来自 libs3d 的交付件，对错由 libs3d 那条链自己的判据背书"
    "（并集体积 = 足迹 × 层高、IoU 98.8%）。本包**没有**独立复算过那两条 —— 本节只判「搬对了地方没有」。",
    "轴号（x 是否取反、z 是否取反）靠**与 gym3d 原件的平面外框对齐**定出，参照物是**另一条链**的一次独立读数。"
    "四条边在 ±0.5 m 内、其余三种符号组合都差 ≥5 m ⇒ 这条判据对**轴号**有力；"
    "对**几米以内的平移误差**无力（那由 DXF 原点口径定，见 pack_d1.py）。",
    "平面外框一致**证明不了层高一致**：libs3d 的 H=3600 mm 是该链的常量，DXF 里一处标高文字都没有"
    "⇒ 3.6 m 是**假设**，本包沿用，没有独立证据。用户裁定的设计口径是 4.0 m（见 meta/c006-basement.json），"
    "两者不是同一个量。",
    "逐层件里不止墙，还含**楼板 / 门 / 电梯 / 楼梯平台**（它就是那一层的完整交付）；"
    "本节量的「平面矩形」是**整个件的包围盒**，不是「墙线覆盖」，别与别的判据互相减。",
    "竖向的 y 带**故意重叠 120 mm**（本层墙顶 = 上层楼板底），所以「层高」不能拿两者的差去读；"
    "重叠正是板与墙接得上的证据，不是误差。",
    "★ **补外墙洞口是 cdut3d 侧做的加法**（tools/wall_close.py），libs3d 冻结基线**一个字没动**。"
    "判据只认「同一面墙被挖了个洞」（两端相望面同厚、中线对齐、同竖向跨度，且实测厚 120~400 mm）；"
    "「两堵墙之间本来就空着」（外廊、天井、中庭）按设计**不补**。"
    "★ 判据对**>6 m** 的口子一律不补（当厅），这条阈值是决定不是测量：代价写进 meta 的 wall_close。",
    "★ 判据只看**几何**，不看**用途**：它分不出「窗洞」与「本该通着的内部门洞」。"
    "实测 F1：942 条成对候选里补 183 条、跳过 748 条（跳过的主因是「一端取不到相望面」112 条与"
    "「厚 600/240 不在墙的档」33 条 —— 即外廊柱那一类）。跳过清单逐条落在 meta 里，谁不同意可以点着看。",
    "★ 独立校核**只做了 F1**（拿 DXF 的 `4.2墙体` 240 宽墙带量补块落位），其余 10 层只判闭包与守恒，"
    "**没有第二来源**核它们的补块落位。",
]


def pieces():
    return {("floor%d" % (k - 1)): os.path.join(LIBS3D_DELIV, "c006-v8-f%d-colored.glb" % k)
            for k in range(1, N_FLOOR + 1)}


def ref_rect():
    """独立参照物：gym3d 原件的平面外框（另一条链、另一份文件）。"""
    g = p1.load_mesh(REF_GYM)
    b = g.bounds
    return {"x": (float(b[0][0]), float(b[1][0])), "z": (float(b[0][2]), float(b[1][2])),
            "_y": (float(b[0][1]), float(b[1][1])), "_span": (float(b[1][0] - b[0][0]), float(b[1][2] - b[0][2]))}


def axis_table(lib, pk, ref):
    """四种符号组合各搬一份 F1 进来，量四边残差。**恰好一种**落在容差内才算定得下来。"""
    f1 = p1.load_mesh(pieces()["floor0"])
    rows = []
    for sx in (1, -1):
        for sz in (1, -1):
            r = p1.plan_rect(p1.apply_T(f1, p1.xform(sx, sz, lib, pk)))
            e = max(abs(r["x"][0] - ref["x"][0]), abs(r["x"][1] - ref["x"][1]),
                    abs(r["z"][0] - ref["z"][0]), abs(r["z"][1] - ref["z"][1]))
            rows.append({"sx": sx, "sz": sz, "edge_err_m": round(e, 3)})
    good = [r for r in rows if r["edge_err_m"] <= ALIGN_TOL_M]
    return rows, good


def judge(nodes, ref):
    """J1 每件的平面矩形落在参照物外框内 · J2 竖向无缝隙覆盖 · J3 面数并集守恒。"""
    fails = []
    rects = {}
    for name, m in nodes.items():
        r = p1.plan_rect(m)
        rects[name] = r
        for ax in ("x", "z"):
            lo, hi = r[ax]
            rlo, rhi = ref[ax]
            if lo < rlo - ALIGN_TOL_M or hi > rhi + ALIGN_TOL_M:
                fails.append("J1:%s 平面 %s %.3f..%.3f 越出参照物 %.3f..%.3f"
                             % (name, ax, lo, hi, rlo, rhi))
    band = sorted(((p1.plan_rect(m)["y"][0], p1.plan_rect(m)["y"][1], n) for n, m in nodes.items()))
    if abs(band[0][0]) > ELEV_TOL_M:
        fails.append("J2:最低件底面 %.3f m，不贴 ±0.000" % band[0][0])
    top = max(b[1] for b in band)
    for lo, hi, n in band:
        if lo > top:
            continue
        prev = max((b[1] for b in band if b[0] < lo - 1e-9), default=None)
        if prev is not None and lo > prev + ELEV_TOL_M:
            fails.append("J2:%s 底面 %.3f m 与下一件顶面 %.3f m 之间有空档" % (n, lo, prev))
    res = sum(abs(m.volume) for m in nodes.values())
    return fails, {"plan": rects, "bands": band, "top_m": top, "sum_volume_m3": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", default=None)
    a = ap.parse_args()

    need = [REF_GYM, LIBS3D_FULL, p1.LIBS3D_F1, p1.LIBS3D_D1, p1.LIBS3D_BUILD, p1.DXF, p1.PROF]
    need += list(pieces().values())
    miss = [p for p in need if not os.path.exists(p)]
    if miss:
        print("!! 缺输入："); [print("   ", m) for m in miss]; return 2

    lib = p1.libs3d_d1_origin()
    pk = p1.pack_d1_origin()
    ref = ref_rect()
    print("libs3d 原点 : (%.0f, %.0f) mm  H=%.0f / BH=%.0f mm   ← %s"
          % (lib["x_mm"], lib["y_mm"], lib["h_mm"], lib["bh_mm"], os.path.basename(p1.LIBS3D_BUILD)))
    print("cdut3d 原点 : (%.0f, %.0f) mm（图框中心y − plan_y中心 = %.1f，11 层一致）"
          % (pk["ox"], pk["oy"], pk["delta_mm"]))
    print("参照物      : gym3d 原件 %s  平面 x %.3f..%.3f  z %.3f..%.3f（外框 %.2f × %.2f m）"
          % (os.path.basename(REF_GYM), ref["x"][0], ref["x"][1], ref["z"][0], ref["z"][1],
             ref["_span"][0], ref["_span"][1]))

    # ---- ③ 轴号 ----
    rows, good = axis_table(lib, pk, ref)
    print("\n轴号表（libs3d 的 F1 按四种符号组合搬进来，量与 gym3d 原件外框的四边残差）")
    for r in rows:
        print("   x%s z%s   四边最大残差 %7.3f m   %s"
              % ("+" if r["sx"] > 0 else "−", "+" if r["sz"] > 0 else "−", r["edge_err_m"],
                 "✓ 对齐" if r["edge_err_m"] <= ALIGN_TOL_M else "✗"))
    if len(good) != 1:
        print("!! 轴号定不下来（落在容差内的组合有 %d 个）⇒ 不猜，停" % len(good)); return 1
    sx, sz = good[0]["sx"], good[0]["sz"]
    margin = min(r["edge_err_m"] for r in rows if r is not good[0]) - good[0]["edge_err_m"]
    if margin < CTRL_MIN_M:
        print("!! 分辨力只有 %.3f m（<%.1f m）⇒ 这条轴号判据没牙，不采信" % (margin, CTRL_MIN_M)); return 1
    print("   ⇒ 定死 x%s z%s（其余组合最近 %.3f m ⇒ 分辨力 %.3f m）"
          % ("+" if sx > 0 else "−", "+" if sz > 0 else "−",
             min(r["edge_err_m"] for r in rows if r is not good[0]), margin))

    T = p1.xform(sx, sz, lib, pk)
    print("\n搬运量      : Δ=(%.3f, %.3f) m  ×0.001  x%s z%s"
          % (T[0, 3], T[2, 3], "+" if sx > 0 else "−", "+" if sz > 0 else "−"))

    # ---- 搬运 + 补外墙洞口 ----
    # ★ 补平在**件自己的坐标系**里做（wall_close 自己认竖轴），补完再 apply_T。
    #   顺序不能反：判据里的 GAP_MIN_MM / PAD_MM 都是**毫米**，而 T 含 ×0.001。
    nodes, closes, f_wall = {}, [], []
    for n, f in pieces().items():
        m0 = p1.load_mesh(f)
        m1, ci = WC.close(m0)
        _, resid = WC.residual_on(m0, m1, ci["filled"])
        rec = {"node": n, "piece": os.path.basename(f),
               "gaps_wall_wall": ci["n_pairs"], "filled": len(ci["filled"]),
               "skipped": len(ci["skipped"]), "unmeasured": ci["n_unmeasured"],
               "faces_in": int(len(m0.faces)), "faces_added": int(len(m1.faces) - len(m0.faces)),
               "residual_after_close": len(resid),
               "added_volume_m3": round(sum(abs(float(q["mesh"].volume)) for q in ci["filled"]) / 1e9, 3)}
        closes.append(rec)
        if resid:
            f_wall.append("J4:%s 补完仍有 %d 条原件墙之间的缝没被跨过去" % (n, len(resid)))
        if ci["n_unmeasured"]:
            f_wall.append("J4:%s 有 %d 条缝的表面距量不出（退化三角），没复核就放过了"
                          % (n, ci["n_unmeasured"]))
        nodes[n] = p1.apply_T(m1, T)
    n_fill = sum(c["filled"] for c in closes)
    print("\n补外墙洞口  : 11 件共补 **%d 根**（+%d m³）  跳过 %d 条  未复核 %d"
          % (n_fill, sum(c["added_volume_m3"] for c in closes),
             sum(c["skipped"] for c in closes), sum(c["unmeasured"] for c in closes)))
    print("            : 补完复量「原件墙之间还剩几条没被跨过去的缝」：%s"
          % ("**0 条**（一趟即闭包）" if not any(c["residual_after_close"] for c in closes)
             else "**%d 条**（判据没做完）" % sum(c["residual_after_close"] for c in closes)))
    fails, info = judge(nodes, ref)
    fails += f_wall

    # ---- J3 面数并集守恒：与**整件**（另一次独立读数）比 ----
    # ★ 量的是**输入件**（原始逐层件）的面数，补块**不掺进来** —— 否则守恒式两边不同源，
    #   成了「我加的面 = 我加的面」。补块自己另有 J5 守恒（输出 = 输入 + 该层计划补块）。
    full_tri = len(p1.load_mesh(LIBS3D_FULL).faces)
    in_tri = {c["node"]: c["faces_in"] for c in closes}
    sum_tri = sum(in_tri.values())
    # 整件含地下 1 层 ⇒ 逐层只对地上那 11 件求和，得加上 D1 才等于整件
    d1_tri = len(p1.load_mesh(p1.LIBS3D_D1).faces)
    ok3 = (sum_tri + d1_tri) == full_tri
    print("\n竖向闭合    : 底 %.3f m  顶 %.3f m（11 件）" % (info["bands"][0][0], info["top_m"]))
    print("J3 面数     : 地上 11 件(输入) %d + 地下 %d = %d  vs  整件 %d  %s"
          % (sum_tri, d1_tri, sum_tri + d1_tri, full_tri, "✓ 无损" if ok3 else "✗ 有丢件"))
    if not ok3:
        fails.append("J3:逐层面数和 %d ≠ 整件 %d" % (sum_tri + d1_tri, full_tri))

    # ---- J5 补块守恒：输出件面数 == 输入件面数 + 该层计划补块面数（按层逐条比，不比总数）----
    bad5 = [c["node"] for c in closes
            if len(nodes[c["node"]].faces) != c["faces_in"] + c["faces_added"]]
    ok5 = not bad5
    print("J5 补块     : 输出 = 输入 + 计划补块（逐层 11/11）  %s"
          % ("✓" if ok5 else "✗ 对不上: %s" % bad5))
    if not ok5:
        fails.append("J5:这些层「输出面数 ≠ 输入 + 补块」%s" % bad5)

    okj = not fails
    print("判词        :", "PASS" if okj else "FAIL %s" % fails[:3])
    if not okj:
        return 1

    # ---- 正对照：每条点名它该红哪条判据 ----
    ctrl = []
    for name, cm, expect in [
        ("平移 +8 m（x）", p1._xlate(next(iter(nodes.values())), [8.0, 0.0, 0.0]), "J1"),
        ("抬高 3 m", p1._xlate(next(iter(nodes.values())), [0.0, 3.0, 0.0]), "J2"),
    ]:
        probe = dict(nodes); probe["floor0"] = cm
        cf, _ = judge(probe, ref)
        got = sorted({f[:2] for f in cf})
        ctrl.append({"name": name, "expect_judge": expect, "fired_judges": got,
                     "ok": bool(expect in got)})
        print("正对照      : %-16s 该红 %s  实红 %-8s %s"
              % (name, expect, ",".join(got) or "无", "✓" if expect in got else "✗ 没红到点子上"))
        if expect not in got:
            fails.append("对照「%s」该红 %s 而实红 %s" % (name, expect, got))
    ctrl.append({"name": "轴号其余三种符号组合", "expect_judge": "J1",
                 "fired_judges": ["J1"], "ok": margin >= CTRL_MIN_M,
                 "why": "其余组合四边残差最近 %.3f m ⇒ 分辨力 %.3f m" % (
                     min(r["edge_err_m"] for r in rows if r is not good[0]), margin)})

    # ★ J4 的**正对照**：拿「补之前」的件当补后件喂给 residual_on，必须红出 >0。
    #   没有这一条，J4 恒绿的两种坏法都看不出来（尺子没牙 / 缝本来就没有）。
    pn, pf = next(iter(pieces().items()))
    pm0 = p1.load_mesh(pf)
    _, ctl_resid = WC.residual_on(pm0, pm0, [])
    okc4 = len(ctl_resid) > 0
    ctrl.append({"name": "拿补前的 %s 冒充补后件" % pn, "expect_judge": "J4",
                 "fired_judges": ["J4"] if okc4 else [],
                 "residual_found": len(ctl_resid), "ok": okc4,
                 "why": "同一把尺子对**未补**的件必须报 %d 条 ⇒ 有分辨力（喂确有缺陷的输入，铁律 137）"
                        % len(ctl_resid)})
    print("正对照      : %-16s 该红 J4  实红 %-8s %s（未补件上量到 %d 条）"
          % ("补前件冒充补后件", "J4" if okc4 else "无", "✓" if okc4 else "✗ 没红到点子上", len(ctl_resid)))
    if not okc4:
        fails.append("对照「补前件冒充补后件」该红 J4 而实红 无（残留 %d）⇒ J4 无分辨力" % len(ctl_resid))

    if fails:
        print("!! 有正对照没红到点子上 ⇒ 判据无分辨力：", fails); return 1

    # ---- 写出 ----
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sc = trimesh.Scene()
    for n in sorted(nodes, key=lambda s: int(s[5:])):
        sc.add_geometry(nodes[n], node_name=n, geom_name=n)
    sc.export(a.out)

    # ---- 重读文件核（不读内存中间量）----
    chk = trimesh.load(a.out, force="scene")
    gn = sorted(chk.geometry.keys())
    b = chk.dump(concatenate=True).bounds
    print("\n写出         :", a.out)
    print("重读核       : 节点 %d 个 %s" % (len(gn), gn))
    print("              bbox x %.3f..%.3f  y %.3f..%.3f  z %.3f..%.3f"
          % (b[0][0], b[1][0], b[0][1], b[1][1], b[0][2], b[1][2]))

    # ★ 过写盘这一关：重读的每一层面数与 bbox 必须与写出前**逐层一致**（补块没在导出里丢/挪）。
    #   ★ 不许拿「竖向跨度」当尺子：补块都在层内，丢了跨度也不变 ⇒ 那尺子对**它该量的那件事**恒绿（铁律 137）。
    lost = []
    for c in closes:
        n = c["node"]
        if n not in chk.geometry:
            lost.append("%s 整个节点没了" % n); continue
        if int(len(chk.geometry[n].faces)) != int(len(nodes[n].faces)):
            lost.append("%s 面数 %d≠%d" % (n, len(chk.geometry[n].faces), len(nodes[n].faces)))
        elif not np.allclose(np.asarray(chk.geometry[n].bounds, float),
                             np.asarray(nodes[n].bounds, float), atol=1e-6):
            lost.append("%s bbox 变了" % n)
    print("重读核·补平 : 11 层重读的**面数与 bbox** 与写出前逐层一致  %s"
          % ("✓" if not lost else "✗ %s" % lost))
    if lost:
        fails.append("J6:过写盘后这些层对不上（补块丢/挪）%s" % lost)

    meta = {
        "schema": "cdut3d-floors/1",
        "source": {"kind": "libs3d 交付件逐层件", "dir": LIBS3D_DELIV,
                   "pattern": "c006-v8-f{k}-colored.glb  k=1..%d" % N_FLOOR,
                   "role": "原样搬入，cdut3d 不建几何",
                   "libs3d_chain": os.path.basename(p1.LIBS3D_BUILD)},
        "supersedes": {
            "what": "tools/split_floors.py 对 gym3d 烘死单网格的「按高度无损切」",
            "why": "那条链的楼板是整块矩形（板/整栋外接矩形 ≈87% 且四层不变），"
                   "3F–6F 各多铺 3400–3660 m²、合计约 1.4 万 m² 幽灵楼板 —— 用户三条判词"
                   "（逐层楼板又出来 / 八角厅楼顶被盖住 / 转角突出）全指这里。",
            "gauge": "_scratch/probe_slabs.py + slab_compare.py 的实测对照（朝上水平面按标高对齐）",
            "replaces_nodes": ["floor0..floor10", "roof"],
            "now_nodes": ["floor0..floor10"],
            "note": "原 roof 节点不再单列：libs3d 那条链的 11 层板就是各层自己的天花板，"
                    "11 层（floor10）的板即塔楼屋面；裙房屋面是 floor6 那张屋面层自己的板，本来就该露天。"},
        "transform": {"axis_sign": {"x": sx, "z": sz}, "scale": 0.001,
                      "dx_m": round(float(T[0, 3]), 3), "dz_m": round(float(T[2, 3]), 3),
                      "how": "与 tools/pack_d1.py 搬 B1 用的是同一个 xform（同一原点口径）",
                      "cdut3d_origin_mm": [round(pk["ox"], 1), round(pk["oy"], 1)],
                      "libs3d_origin_mm": [lib["x_mm"], lib["y_mm"]]},
        "reference": {"file": REF_GYM, "chain": "gym3d（另一条链的一次独立读数，非本次要覆盖的件）",
                      "plan_x_m": [round(v, 3) for v in ref["x"]],
                      "plan_z_m": [round(v, 3) for v in ref["z"]],
                      "span_m": [round(v, 2) for v in ref["_span"]]},
        "axis_table": rows,
        "margin_m": round(margin, 3),
        "layers": [{"name": n, "lo_m": round(p1.plan_rect(m)["y"][0], 3),
                    "hi_m": round(p1.plan_rect(m)["y"][1], 3), "faces": int(len(m.faces))}
                   for n, m in sorted(nodes.items(), key=lambda kv: int(kv[0][5:]))],
        "faces": {"sum_above_ground": int(sum_tri), "full_model": int(full_tri),
                  "d1": int(d1_tri), "lossless": bool(ok3),
                  "added_by_wall_close": int(sum(c["faces_added"] for c in closes))},
        "wall_close": {
            "tool": "tools/wall_close.py",
            "role": "按交付口径（实景三维 LOD1.3 棱柱体·外墙闭合·不表达门窗洞）补平外墙洞口",
            "why": "libs3d 链 `build8.py::bridge_gaps` 原文注释「墙实体仍按图纸不补」⇒ "
                   "逐层件里量到 709 条 ≥50 mm 的缝、逐条在 z=1000/2850/3300 三个高度上问"
                   "**100% 是整层高的洞、0 条有门头**。用户判词「墙与墙之间没有接上」。",
            "criterion_version": "wall_close/1",
            "gaps_vs_filled": {"gaps_wall_wall": sum(c["gaps_wall_wall"] for c in closes),
                               "filled": n_fill,
                               "skipped": sum(c["skipped"] for c in closes)},
            "residual_after_close": sum(c["residual_after_close"] for c in closes),
            "unmeasured": sum(c["unmeasured"] for c in closes),
            "per_floor": closes},
        "bbox_m": {"x": [round(float(b[0][0]), 3), round(float(b[1][0]), 3)],
                   "y": [round(float(b[0][1]), 3), round(float(b[1][1]), 3)],
                   "z": [round(float(b[0][2]), 3), round(float(b[1][2]), 3)]},
        "judge": {"J1_inside_reference": not any(f.startswith("J1") for f in fails),
                  "J2_vertical_closure": not any(f.startswith("J2") for f in fails),
                  "J3_faces_lossless": ok3,
                  "J4_wall_closed": not any(f.startswith("J4") for f in fails),
                  "J5_fill_conservation": ok5,
                  "J6_reload_identity": not any(f.startswith("J6") for f in fails),
                  "pass": bool(okj)},
        "controls": ctrl,
        "blind_spots": BLIND,
    }
    if a.meta:
        os.makedirs(os.path.dirname(os.path.abspath(a.meta)), exist_ok=True)
        data = json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n")
        open(a.meta, "wb").write(data)
        print("meta         :", a.meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
