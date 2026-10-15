# -*- coding: utf-8 -*-
"""判据 J-09.2-A1b：**门窗洞口能按几何识别出来**，且**有一个不来自 `4.2墙体` 的外部量能核它**。

对应方案 §9.2 轨A·A1「逐类构件覆盖率（墙/柱/门/梯）」的门/窗那一条。四件套（§10.0.1）：
  ① 量交付件本身 —— 现场读 DXF、现场识别洞口、现场读人写门号；不读任何中间日志/快照
  ② 量具写明      —— `a1/openings.py`（多路识别）+ `a1/check_doors_ext.py`（外部量对账）
  ③ 盲区声明      —— 见下
  ④ 正对照必配    —— **四条**（B/C②/C①/D）

★ 背景：门窗在本库**不是图层**（105 份里 0 份有独立门窗层；只有 3 份有名字带「门」的层，且是 MTEXT
  文字）。它们全在 `4.2墙体` 里、**同一构件三栋三种画法**（C006=`$DorLib2D$` 块 754 / C011=13 顶点
  多段线 / C009=14 顶点多段线 / C075=ARC）⇒ 旧链 `build8:242` **主动把门剔掉**，覆盖率 0。

★ 判据（全部为真才算过）：
  A. **洞口几何覆盖率**：全库 ≥ `COV_MIN`(=90%) 的栋能识别出 ≥1 处洞口几何（实测 **97/105 = 92.4%**）
  B. **正对照（确有门的图）**：C109-十公寓 识别簇数 **== 142 == 人写门号数**（不是 ≥1，是相等）
  C. **外部量一一对应**（`check_doors_ext`）：C109 门号 142 = 簇 142，一一对应、宽度吻合 142/142；
     ★ 两条对照必须全响 —— ① 门号平移 **10 km** ⇒ 命中 **0**；② 门号宽度整体 **+500** ⇒ 吻合 **0**
  D. **合成缺陷对照**：把 C109 的墙层里所有「洞口候选多段线」删掉再识别 ⇒ 簇数必须**掉到 0**
     （证明识别器**确实在读那些几何**；喂坏输入不响 = 判据没分辨力，铁律 137）
  E. **非空断言**：扫到的 DXF 数 == 0 ⇒ 判**不成立**（遍历型判据扫空集合会恒绿）

★ 盲区（必须声明，盲区内的否定判词不算证据）：
  ① 判的是「墙层里像洞口的**自足小图形**」，**不判它是不是门、也不分门窗**（窗可宽到 3 m，与门共用
     同一尺寸窗）。故判据 A 叫「**洞口几何**覆盖率」，**不叫「门覆盖率」**。
  ② 外部量**只有 C109 一栋在线**（全库 6 栋有门号，仅 C109 的号落在门位上；C075 的 541 条是**门表**，
     到最近几何中位 10.1 m ⇒ 不给判词）。⇒ **其余 104 栋的门「识别得对不对」本条不给结论**。
  ③ 本尺只读 `openings.OPEN_LAYERS` 四种墙层名 + 尺寸窗/顶点数/弧半径三组**判据参数**；改参数改数。
  ④ 只覆盖 `--dir` 里的 *.dxf；只说「识别出几何」，**不说几何进没进三维模型**（那是建链的事）。
  ⑤ 判据 A 的分母是**目录里的 DXF 份数**，不是「有墙层的份数」（本库 105/105 都有墙层）。

用法: python gates/J-09.2-A1b_openings.py            # 全库扫（~3 min）
     python gates/J-09.2-A1b_openings.py --quick     # 只跑样板（~30 s）
     python gates/J-09.2-A1b_openings.py --json gates/_out/J-09.2-A1b.json
"""
import sys
import os
import glob
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
A1 = os.path.join(ROOT, "a1")
sys.path.insert(0, A1)
import openings as OP                # noqa: E402
import batch_openings as BO          # noqa: E402
import check_doors_ext as CEX        # noqa: E402

DXF_DIR = r"D:\项目\gym3d\材料\dxf_output"
QUICK = ["C006-第六教学楼（逸夫楼）", "C009-第九教学楼", "C011-银杏体育馆",
         "C075-综合实验大楼", "C109-十公寓", "C001-砚湖图书馆"]
C109 = os.path.join(DXF_DIR, "C109-十公寓.dxf")
N_C109_DOORS = 142          # 人写门号数（实测；见 check_doors_ext 输出）
COV_MIN = 90.0


def control_erase(dxf):
    """D：删掉墙层里所有 ≥MINV 的多段线（= 洞口候选）⇒ 簇数必须掉到 0。"""
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    n = 0
    for e in list(msp):
        if e.dxf.layer in OP.OPEN_LAYERS and e.dxftype() in ("LWPOLYLINE", "POLYLINE") \
                and len(OP._pts_of(e)) >= OP.MINV:
            msp.delete_entity(e)
            n += 1
    polys, _lh, _h = OP.load_openings_from_msp(msp)
    nc, _ = OP.n_clusters(polys)
    return n, nc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DXF_DIR)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", default=os.path.join(HERE, "_out", "J-09.2-A1b.json"))
    a = ap.parse_args()

    fails = []
    print("判据 J-09.2-A1b  门窗洞口几何识别 + 外部量对账")
    print("  DXF 目录:", a.dir)

    # ---- A 覆盖率 ----
    if a.quick:
        files = [os.path.join(a.dir, n + ".dxf") for n in QUICK]
        print("\n== A 洞口几何覆盖率（--quick：样板 %d 块，非全库）==" % len(files))
        full = False
    else:
        files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
        print("\n== A 洞口几何覆盖率（全库）==")
        full = True
    if not files:
        print("  ★ 扫到 0 份 DXF ⇒ 判据**不成立**（E 非空断言）")
        return 3                              # E
    n_hit = 0
    seen = []
    for f in files:
        r = BO.one(f)
        if "err" in r:
            print("   !! %s %s" % (r["dxf"][:40], r["err"])); continue
        seen.append(r)
        if r["n_clusters"] > 0:
            n_hit += 1
        print("   %-42s 簇 %5d" % (r["dxf"][:42], r["n_clusters"]))
    cov = 100.0 * n_hit / max(len(seen), 1)
    print("  ⇒ 识别出洞口几何: %d / %d = %.1f%%（阈值 %.0f%%）%s"
          % (n_hit, len(seen), cov, COV_MIN, "✓" if cov >= COV_MIN else "✗"))
    if full and cov < COV_MIN:
        fails.append("A 洞口几何覆盖率 %.1f%% < %.0f%%" % (cov, COV_MIN))

    # ---- B 正对照：确有门的图，簇数 == 人写门号数 ----
    print("\n== B 正对照（C109 确有门）==")
    rb = BO.one(C109)
    nb = rb.get("n_clusters", -1)
    print("   C109 识别簇 = %d，人写门号 = %d ⇒ %s"
          % (nb, N_C109_DOORS, "✓ 相等" if nb == N_C109_DOORS else "✗ 不等（应相等）"))
    if nb != N_C109_DOORS:
        fails.append("B C109 簇 %d ≠ 门号 %d" % (nb, N_C109_DOORS))

    # ---- C 外部量一一对应 + 两条对照（复用 check_doors_ext）----
    print("\n== C 外部量（人写门号 M1000 ↔ 识别门几何）==")
    marks, polys = CEX.marks_and_polys(C109)
    nm = sum(1 for m in marks if m[2] == "M")
    n, hits, bij = CEX.match(marks, polys)
    wok = [h for h in hits if abs(h[2] - h[3]) <= CEX.W_TOL]
    nc_shift, _, _ = CEX.match(marks, polys, shift=CEX.SHIFT)
    widths_bad = [None] * len(marks)
    for i, m in enumerate(marks):
        if m[2] == "M":
            widths_bad[i] = m[3] + 500
    _, hits_bad, _ = CEX.match(marks, polys, widths=widths_bad)
    wok_bad = [h for h in hits_bad if abs(h[2] - h[3]) <= CEX.W_TOL]
    print("   A 一一对应: 命中 %d / 门号 %d / 簇 %d ⇒ %s" % (n, nm, len(polys), "✓" if bij else "✗"))
    print("   B 宽度吻合: %d / %d" % (len(wok), len(hits)))
    print("   对照① 平移 10 km ⇒ 命中 %d（应 0）%s" % (nc_shift, "✓" if nc_shift == 0 else "✗"))
    print("   对照② 宽度+500 ⇒ 吻合 %d（应 0）%s" % (len(wok_bad), "✓" if len(wok_bad) == 0 else "✗"))
    if not bij:
        fails.append("C 一一对应不成立")
    if len(wok) != len(hits):
        fails.append("C 宽度吻合 %d/%d" % (len(wok), len(hits)))
    if nc_shift != 0:
        fails.append("C 对照① 平移 10km 仍命中 %d（应 0）" % nc_shift)
    if len(wok_bad) != 0:
        fails.append("C 对照② 宽度+500 仍吻合 %d（应 0）" % len(wok_bad))

    # ---- D 合成缺陷对照 ----
    print("\n== D 合成缺陷对照（删掉洞口候选多段线）==")
    ne, nc0 = control_erase(C109)
    print("   删掉 %d 条候选多段线 ⇒ 簇数 %d ⇒ %s"
          % (ne, nc0, "✓ 掉到 0（识别器确实在读这些几何）" if nc0 == 0 else "✗ 未掉到 0"))
    if ne == 0 or nc0 != 0:
        fails.append("D 合成缺陷未触发（删 %d 条 ⇒ 簇 %d）" % (ne, nc0))

    print("\n===== 判词 =====")
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
        rc = 1
    else:
        print("  PASS  rc=0   洞口几何 %.1f%%（%d/%d）；C109 外部量 142=142 一一对应、"
              "四条对照全响" % (cov, n_hit, len(seen)))
        rc = 0
    print("  ★ 盲区：外部量只在 C109 一栋在线；其余栋「门识别对不对」本条不给结论（盲区②）")
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"pass": rc == 0, "full": full, "n_files": len(seen),
                   "n_hit": n_hit, "coverage_pct": cov, "cov_min": COV_MIN,
                   "c109_clusters": nb, "c109_marks": nm, "bijection": bij,
                   "width_ok": len(wok), "shift_hits": nc_shift, "bad_w_ok": len(wok_bad),
                   "erase_deleted": ne, "erase_clusters": nc0, "fails": fails},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
