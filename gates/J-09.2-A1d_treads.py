# -*- coding: utf-8 -*-
r"""判据 J-09.2-A1d：**梯（踏步）这一类构件** —— 踏步线不许被当成墙建进模型，且剔的是**同一批线**。

对应方案 §9.2 轨A·A1「逐类构件的覆盖率（墙/柱/门/梯各建出来没有）」里 **梯** 那一条（A1 第三个缺口）。
四件套（§10.0.1）：
  ① 量交付件本身 —— **链自己喂给下游的那份墙输入**（`load_walls_and_cols_msp` 的返回），不是日志
  ② 量具写明      —— 冻结基线的 `libs3d/c006/treadlib.py`（**唯一真源**）+ `a1/treads.py`（只做「在哪收锚」）
  ③ 盲区声明      —— 见下（★ 本条只在**有锚**的栋上有牙，这是实测结果不是免责声明）
  ④ 正对照必配    —— 四条（① 锚平移 10 km ／ ② 只喂踏步线 ／ ③ 合成破坏守恒 ／ ④ 空输入）

★ 背景（全部为实测，见 `_scratch/probe_tread*.py` 与 `probe_stair*.py`）：
  · 踏步线住在 `4.2墙体` 里（全库 0 份独立层），几何上就是**一跑平行的短线**（间距 270 mm）
    —— 与 `wire()` 认墙的规则（平行、垂距 40~400 mm）**重合** ⇒ 不剔就会被**配成墙身四边形**。
  · 冻结基线**四处**都在剔：`build6.py:191`／`build7.py:123`／`build8.py:169`（建）＋
    `score6.py:112`／`score8.py:149`（**参照侧也剔**，`score6.py` 首行原话：「与 build6 共用 treadlib，
    同一批复判据」）。而 `a1/generic_wall.py` 自称「打分侧逐行照抄 score8.py」，
    `import treadlib` 却在**全文件里一次都没调用**（铁律 17）⇒ 通用化时丢了这一行。
  · 后果实测（C006，精确并集 `unary_joined`）：墙输入含踏步足迹 **4472.648 m²** → 剔后 **3765.317 m²**，
    **Δ=707.331 m²（15.81%）**、逐图幅 Δ 12/12 全为正。这不是「面积大一点」：
    被建出来的是**楼梯间里 270 mm 一道的假墙**（面积尺对位置全盲，故另见盲区⑤）。
  · 检测器的锚是人写的 `上`/`下`：全库**只有 4 栋**有（C006 136／C074 17／C113 5 在墙层内；
    **C105 178 条全在非墙层** ⇒ 冻结基线与通用链**都看不见**）。

★ 判据（全部为真才算过）：
  A. **守恒**：链喂给下游的墙输入 == 原始墙段 − `treadlib` 检出集（**按坐标键的多重集逐条比**，
     不是比条数；多一条少一条、或换了一条都要红）。
  B. **正对照①**（离开锚区）：把全部锚整体平移 **10 km** ⇒ 检出组必须 **0**、剔除必须 **0**
     （证明「只保留锚 2.5 m 内」这道外科手术真在起过滤作用，不是恒真）。
  C. **正对照②**（只喂踏步线）：只用检出集里的线建墙 ⇒ 足迹必须 **>0** 且 **< 含踏步足迹**
     （证明被剔的那批线**确实在造墙**，剔它不是空操作）。
  D. **正对照③**（合成破坏守恒）：把检出集里**人为漏掉一组** ⇒ 判据必须报出「还有 N 条线留在墙输入里」
     （喂确有缺陷的输入，证明 A 有分辨力；铁律 137）。
  E. **非空断言**：DXF 0 份 / 墙段 0 条 / 全库锚 0 条 ⇒ 判**不成立**（遍历型判据扫空集合恒绿）。
  F. **反事实**：C006 剔踏步后足迹**严格变小**且仍 >0（不许把墙全剔光），并把 Δ 落进 json。

★ 盲区（必须声明；盲区内的否定判词不算证据）：
  ① **锚只在 4 栋**（基线口径 3 栋）。其余 101 栋本条**不给结论**：实测 C001/C009/C011 无锚，
     但同云的无锚几何候选有 **79／143／66 组**（占墙段 19.7%／7.3%／17.9%）——
     **候选≠确证**（C006 上无锚比有锚多出 16 组），没有外部量能核它是不是楼梯 ⇒ 既不剔也不判。
  ② **C105 的 178 条锚全在非墙层**，基线口径（只收墙层内）下链**看不见**；把收锚放宽到全层实测
     多认 **125 组／1397 条线**。本判据**不默认启用**放宽口径（那是对基线的偏离），只报这个数。
  ③ 只判「踏步线有没有从墙输入里剔掉」，**不判梯段建没建出来**（`libs3d/c006/build7.py` 那件事）。
  ④ 逐图幅足迹只对**有 grid json** 的栋算（现在只有 C006）；C074/C113/C105 只判守恒、不判面积。
  ⑤ 面积尺对**位置**全盲：Δ=707 m² 说的是「面积」，说的是哪一片墙**不是本判据**给的。
  ⑥ **板/梁不给结论**：全库带结构字样的层只有 `4.1结构柱`（40 份），**没有板层也没有梁层**
     ⇒ 图上无几何可建；「板」是靠 `libs3d` 逐层件提供的（另有判据管），梁无来源。
  ⑦ **组数 ≠ 注释数**（C006：193 组 / 136 注释）——两个量名字不同，**不判相等**（铁律 174）。

用法: python gates/J-09.2-A1d_treads.py                 # 只跑有锚的 3 栋 + C105 对照（~2 min）
     python gates/J-09.2-A1d_treads.py --dir <dxf目录>
     python gates/J-09.2-A1d_treads.py --json gates/_out/J-09.2-A1d.json
"""
import sys
import os
import json
import argparse
import importlib.util
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
A1 = os.path.join(ROOT, "过程/a1")
LIBS3D = r"D:\项目\libs3d\c006"
sys.path.insert(0, A1)
sys.path.insert(0, LIBS3D)
import generic_wall as GW            # noqa: E402  ★ 链自己那份加载器（被测对象）
import treadlib as TL                # noqa: E402  ★ 冻结基线：判据的唯一真源

DXF_DIR = r"D:\项目\gym3d\材料\dxf_output"
# 有锚的栋（实测：全库 105 栋里只有这 4 栋有 `上`/`下`）
ANCHORED = ["C006-第六教学楼（逸夫楼）", "C074-师生活动中心", "C113-艺术楼"]
WIDEN_PROBE = "C105-图书馆"          # ★ 178 条锚全在非墙层 ⇒ 基线口径看不见（盲区②）
# ★★ 正对照① 的平移量：DXF 坐标是 **mm**，所以要移 10 km 得写 1e7 而不是 1e4。
#   第一版写成 10000.0（= **10 m**）实测**漏了一组**：C006 模型空间横跨 ~90 m，
#   离锚 10~14 m 的那一组被平移后反而**贴近**了另一个锚（≈0 mm）⇒ 仍然保留。
#   这正是方案里记过的那条（「正对照扰动要跨出重复结构：10 m 不够 ⇒ 10 km」）。
SHIFT_MM = 10000000.0                # 10 km（mm）
TOL_M2 = 1e-6                        # 面积相等判据：1 mm²（浮点尾数级）

# ★ 逐图幅精确足迹复用 J-07.9.4-03 里那份**同一实现**（`folds`），不抄第三遍
_spec = importlib.util.spec_from_file_location(
    "g03", os.path.join(HERE, "J-07.9.4-03_residual_to_model.py"))
g03 = importlib.util.module_from_spec(_spec)


def load_g03():
    if not hasattr(g03, "folds"):
        _spec.loader.exec_module(g03)
    return g03


def raw_walls(msp):
    """**逐行复刻** `GW.load_walls_and_cols_msp` 里「读墙」的那一半（判据不许用被测实现取证）。

    只在墙层里取几何、跳过 INSERT、TEXT/MTEXT 不算墙段 —— 与 `a1/generic_wall.py:157-166` 同规则。
    """
    out = []
    for e in msp:
        if e.dxf.layer not in GW.WALL_LAYERS:
            continue
        if e.dxftype() == "INSERT":
            continue
        if e.dxftype() in ("TEXT", "MTEXT"):
            continue
        GW.segs_of(e, out)
    return out


def keys(segs):
    """坐标键（多重集用）：端点四舍五入到 1e-6。★ 不设会被变换改掉的键（本判据无变换）。"""
    return [(round(s.coords[0][0], 6), round(s.coords[0][1], 6),
             round(s.coords[-1][0], 6), round(s.coords[-1][1], 6)) for s in segs]


def anchored(path):
    """一栋：读原始墙段 + 链喂下游的墙输入 + 检出组。返回 dict（**不判**，判在 main 里）。"""
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    raw = raw_walls(msp)
    kept, cols, labels = GW.load_walls_and_cols_msp(msp)   # ★ 被测的那一份
    groups = TL.detect_tread_groups(raw, labels)
    idx = set()
    for g in groups:
        idx.update(g["idx"])
    return dict(raw=raw, kept=kept, cols=cols, labels=labels, groups=groups, idx=idx, msp=msp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DXF_DIR)
    ap.add_argument("--json", default=os.path.join(HERE, "_out", "J-09.2-A1d.json"))
    a = ap.parse_args()

    fails = []
    rec = {}
    print("判据 J-09.2-A1d  梯（踏步）：踏步不许当墙建 + 剔的是同一批线")
    print("  真源: libs3d/c006/treadlib.py（冻结基线）   被测: a1/generic_wall.py 的墙输入")

    # ---------- E 非空断言 ----------
    print("\n== E 非空 ==")
    paths = [(nm, os.path.join(a.dir, nm + ".dxf")) for nm in ANCHORED]
    paths = [(nm, p) for nm, p in paths if os.path.isfile(p)]
    print("   有锚的栋（存在 %d 份）: %s" % (len(paths), [nm[:6] for nm, _ in paths]))
    if not paths:
        print("   ★ 一份 DXF 都没读到 ⇒ 判**不成立**（E）"); return 3
    R = {}
    for nm, p in paths:
        R[nm] = anchored(p)
        r = R[nm]
        print("   %-14s 原始墙段 %6d   链喂下游 %6d   锚 %3d   检出组 %3d（线 %5d = %.1f%%）"
              % (nm[:14], len(r["raw"]), len(r["kept"]), len(r["labels"]),
                 len(r["groups"]), len(r["idx"]),
                 100.0 * len(r["idx"]) / max(len(r["raw"]), 1)))
        if not r["raw"]:
            print("   ★ 原始墙段 0 条 ⇒ 判**不成立**（E）"); return 3

    # ---------- A 守恒（逐条，多重集） ----------
    print("\n== A 守恒：链喂下游 == 原始 − 检出集（按坐标键多重集，逐条） ==")
    n_drop_tot = 0
    for nm, _ in paths:
        r = R[nm]
        want = collections.Counter(keys([s for i, s in enumerate(r["raw"]) if i not in r["idx"]]))
        got = collections.Counter(keys(r["kept"]))
        # ★ 两个方向的偏差**名字必须分开**（第一版把这两个词写反了，实测被正对照 D 抓出来）：
        still_in = sum((got - want).values())    # 链留着、本该剔 = **该剔未剔**
        over_drop = sum((want - got).values())   # 链剔了、本该留 = **剔多了**
        n_drop_tot += len(r["idx"])
        ok = (still_in == 0 and over_drop == 0)
        print("   %-14s 期望保留 %6d  实得 %6d   该剔未剔 %4d   剔多了 %4d  %s"
              % (nm[:14], sum(want.values()), sum(got.values()), still_in, over_drop,
                 "✓" if ok else "✗"))
        rec[nm[:6]] = {"raw": len(r["raw"]), "kept": len(r["kept"]),
                       "labels": len(r["labels"]), "groups": len(r["groups"]),
                       "dropped": len(r["idx"]), "still_in": still_in, "over_drop": over_drop}
        if not ok:
            fails.append("A %s 守恒不成立（该剔未剔 %d / 剔多了 %d）"
                         % (nm[:6], still_in, over_drop))
    if n_drop_tot == 0:
        print("   ★ 三栋检出合计 0 ⇒ 判**不成立**（E：尺子这一趟没读到任何踏步）")
        return 3

    # ---------- B 正对照①：锚平移 10 km ⇒ 检出必为 0 ----------
    print("\n== B 正对照①：把锚整体平移 %.0f km ⇒ 检出组必须 0 ==" % (SHIFT_MM / 1e6))
    nm0, _ = paths[0]
    r0 = R[nm0]
    lab_shift = [(x + SHIFT_MM, y + SHIFT_MM) for (x, y) in r0["labels"]]
    g_shift = TL.detect_tread_groups(r0["raw"], lab_shift)
    n_shift = sum(len(g["idx"]) for g in g_shift)
    print("   %s：原件 %d 组 → 平移后 %d 组（%d 条线）  %s"
          % (nm0[:6], len(r0["groups"]), len(g_shift), n_shift,
             "✓" if (len(g_shift) == 0 and n_shift == 0) else "✗ 锚没起作用"))
    if len(g_shift) != 0 or n_shift != 0:
        fails.append("B 锚平移 %.0f km 仍检出 %d 组" % (SHIFT_MM / 1e6, len(g_shift)))

    # ---------- C 正对照②：只喂踏步线 ⇒ 足迹 >0 且 < 含踏步 ----------
    print("\n== C 正对照②：只拿检出集里的线建墙 ==")
    gj = os.path.join(ROOT, "过程/a1", "_out", "c006_grid.json")
    rc_area = None
    if nm0.startswith("C006") and os.path.isfile(gj):
        g = load_g03()
        cells = json.load(open(gj, encoding="utf-8"))["sheets"]
        treads = [s for i, s in enumerate(r0["raw"]) if i in r0["idx"]]
        kept = r0["kept"]
        A_all = sum(x[1] for x in g.folds(cells, r0["raw"], r0["cols"]))
        A_keep = sum(x[1] for x in g.folds(cells, kept, r0["cols"]))
        A_tread = sum(x[1] for x in g.folds(cells, treads, r0["cols"]))
        d_ft = A_all - A_keep
        print("   含踏步 %.3f m² ／ 剔踏步 %.3f m² ／ **只踏步** %.3f m²" % (A_all, A_keep, A_tread))
        print("   Δ足迹 = %.3f m²（%.2f%%）  %s" % (d_ft, 100.0 * d_ft / max(A_all, 1e-9),
              "✓ 剔完严格变小且仍 >0" if (d_ft > TOL_M2 and A_keep > TOL_M2) else "✗"))
        print("   只踏步建出来的足迹 %.3f m² %s"
              % (A_tread, "✓ >0（那批线确实在造墙）" if A_tread > TOL_M2 else "✗ 剔的不是墙"))
        rc_area = {"a_all": A_all, "a_keep": A_keep, "a_tread": A_tread, "d_ft": d_ft}
        if not (d_ft > TOL_M2 and A_keep > TOL_M2):
            fails.append("C 剔踏步后足迹没严格变小（Δ=%.6f）" % d_ft)
        if not (A_tread > TOL_M2):
            fails.append("C 正对照② 只踏步足迹 =0（被剔的不是墙？）")
    else:
        print("   ★ 没量到 %s 的 grid json ⇒ 本条「没量到」（不判）" % nm0[:6])

    # ---------- D 正对照③：合成破坏守恒（人为把一组的期望值改坏） ----------
    # ★ 第一版只数**一个方向**（该剔未剔）⇒ 修好链之后反而报 0（链确实剔了，偏差落到了
    #   另一个方向）⇒ 实测抓出的第二个尺子 bug。守恒检查必须**两个方向都数**。
    # ★ 牙要求的是**偏差恰好等于那一组的条数**（不是「非零即可」）——
    #   这样才证明这把尺子连「少算/多算几条」都分得出来。
    print("\n== D 正对照③：人为漏剔一组 ⇒ 守恒必须报出偏差 ==")
    if len(r0["groups"]) >= 2:
        g1 = r0["groups"][0]
        idx_bad = set()
        for g in r0["groups"][1:]:
            idx_bad.update(g["idx"])
        want_bad = collections.Counter(
            keys([s for i, s in enumerate(r0["raw"]) if i not in idx_bad]))
        got = collections.Counter(keys(r0["kept"]))
        dev_in = sum((got - want_bad).values())      # 链留着、按坏期望该剔
        dev_out = sum((want_bad - got).values())     # 链剔了、按坏期望该留
        dev = dev_in + dev_out
        print("   漏掉第 1 组（n=%d 条）⇒ 偏差 %d 条（该剔未剔 %d ／ 期望外被剔 %d）  %s"
              % (g1["n"], dev, dev_in, dev_out,
                 "✓ 有分辨力" if dev > 0 else "✗ 无分辨力"))
        if dev != g1["n"]:
            fails.append("D 偏差 %d ≠ 该组条数 %d（对偏差**大小**没分辨力）" % (dev, g1["n"]))
    else:
        print("   ★ %s 检出组 <2 ⇒ 本条「没量到」（不判）" % nm0[:6])

    # ---------- 盲区② 的读数：放宽收锚到「全层」能多认出多少（**不启用**，只报） ----------
    print("\n== 盲区② 读数（**不启用**）：把收锚从「墙层内」放宽到「全层」 ==")
    wp = os.path.join(a.dir, WIDEN_PROBE + ".dxf")
    widen = None
    if os.path.isfile(wp):
        doc = ezdxf.readfile(wp)
        msp = doc.modelspace()
        raw_w = raw_walls(msp)
        lab_all = []
        for e in msp:
            if e.dxftype() not in ("TEXT", "MTEXT"):
                continue
            s = (e.dxf.text if e.dxftype() == "TEXT" else e.text) or ""
            if s.strip() in ("上", "下"):
                p = e.dxf.insert; lab_all.append((p.x, p.y))
        g_w = TL.detect_tread_groups(raw_w, lab_all)
        n_w = sum(len(g["idx"]) for g in g_w)
        _, _, lab_wall = GW.load_walls_and_cols_msp(msp)
        g_wall = TL.detect_tread_groups(raw_w, lab_wall)
        widen = {"dxf": WIDEN_PROBE, "raw": len(raw_w), "labels_wall": len(lab_wall),
                 "labels_all": len(lab_all), "groups_all": len(g_w), "lines_all": n_w,
                 "groups_wall": len(g_wall)}
        print("   %s：墙层内锚 %d ⇒ 基线口径检出 %d 组；全层锚 %d ⇒ 检出 %d 组（%d 条线）"
              % (WIDEN_PROBE[:6], len(lab_wall), len(g_wall), len(lab_all), len(g_w), n_w))
        print("   ⇒ 这一栋现在**没被剔**（已量、未修）：放宽口径才看得见（盲区②）")
    else:
        print("   ★ 没读到 %s ⇒ 本条「没量到」" % WIDEN_PROBE[:6])

    # ---------- 判词 ----------
    print("\n===== 判词 =====")
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
        rc = 1
    else:
        print("  PASS  rc=0   守恒 3/3 栋成立（合计剔踏步 %d 条）；四条正对照全响" % n_drop_tot)
        rc = 0
    print("  ★ 盲区：锚只在 4/105 栋（基线口径 3 栋）⇒ 其余 101 栋「有没有踏步」本条**不给结论**")
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"pass": rc == 0, "shift_mm": SHIFT_MM, "dropped_total": n_drop_tot,
                   "per_building": rec, "c006_area": rc_area, "widen_c105": widen,
                   "fails": fails},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
