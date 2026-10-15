# -*- coding: utf-8 -*-
"""A1：把**通用墙链**（sheet_grid 自动图幅 + generic_wall 建墙打分 + cols 多路柱）扫过全库。

这是 A1 出口门的**交付件复算尺**（闸2）：不读任何中间日志，逐份 DXF **现场**算
「图幅 / 墙段 / 柱块 / IoU / 墙线覆盖」，并如实记**崩了还是没量到**（六态口径）。

用法: python batch_wall.py [dxf目录] [--json out.json] [--limit N]
     [--pos <dxf>]   正对照：一份确知能建的图，必须 ≥1 图幅且墙线覆盖不空。

★ 量具盲区（必须声明）：
  ① `IoU` 与「墙线覆盖」都**由 `4.2墙体` 派生** ⇒ 只能证「没漏几何」，**不是「墙对不对」的真值**
     （正对照=墙厚 2 倍假件才会掉；见方案 A1 行）。
  ② 无柱层 64 栋**不是链的缺陷**，是 CAD 里没画柱（已全库核过：只两种柱层名）。
  ③ 「崩了」只覆盖本脚本捕获的异常；**进程被杀/超时不在此列**（要另记）。
  ④ 只覆盖有 `1图框` 层的图（其余 `n_sheets=0`，本尺说不出是「没平面图」还是「尺子漏」）。
  ⑤ `n_sheets` **含空模板框**（见 `one()` 内注）⇒ 判「平面图张数」要看 `n_real`
     （墙段 ≥ `MIN_SEG`）。本尺以 `n_real ≥ 1` 为「这栋真有平面图」的最弱判词。
"""
import sys
import os
import json
import glob
import time
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sheet_grid as SG   # noqa: E402
import generic_wall as GW  # noqa: E402

MIN_SEG = 50   # 一张图幅里墙段 ≥ 此数 ⇒ 它是**真平面图**（`a1/wall_per_sheet.py` 的判据，同阈值）


def plan_state(n_real):
    """★ 内容闸，与几何闸 `state` **分开记**（两把尺子，各自会错，不许互相盖章）。
      `state=OK` 只说「几何上凑出了 ≥2 张同尺寸图幅的条带」；
      `plan_state` 才说「这栋**真有**几张带墙的平面图」：
        PLANS_OK   n_real ≥ 2 —— 有**序列**（楼层平面图序列的前提）
        SINGLE      n_real == 1 —— 只有 1 张平面图（可建模，但**不构成层序**）
        NO_PLAN     n_real == 0 —— 一张都没有（图幅全是空模板框）
    实测分歧（2026-10-12）：C066-珙桐餐厅 state=OK 但 n_real=1；L002-风景园林生态观测场 state=OK 但 n_real=0。
    """
    return "PLANS_OK" if n_real >= 2 else ("SINGLE" if n_real == 1 else "NO_PLAN")


def one(path, margin):
    t0 = time.time()
    try:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
    except Exception as e:
        return {"dxf": os.path.basename(path), "state": "READ_FAIL",
                "err": type(e).__name__, "sec": round(time.time() - t0, 1)}
    # 图幅
    try:
        layer = SG.find_frame_layer(msp, None)
        if not layer:
            return {"dxf": os.path.basename(path), "state": "NO_FRAME",
                    "sec": round(time.time() - t0, 1)}
        sheets = SG.merge_pairs(SG.collect_frames(msp, layer))
        modal, std, others = SG.classify(sheets)
        if len(std) < 1:
            return {"dxf": os.path.basename(path), "state": "NO_GRID", "layer": layer,
                    "n_sheets": len(sheets), "sec": round(time.time() - t0, 1)}
    except Exception as e:
        return {"dxf": os.path.basename(path), "state": "GRID_FAIL",
                "err": type(e).__name__, "sec": round(time.time() - t0, 1)}
    # 建墙打分
    try:
        ALLW, ALLC, LABELS = GW.load_walls_and_cols_msp(msp)
        tr = tm = ti = 0.0
        lcs = []
        for c in std:
            x0, y0, x1, y1 = c["bbox"]
            r, m, i, lc, nq, nu = GW.score_cell(ALLW, ALLC, x0, x1, y0, y1, margin)
            tr += r; tm += m; ti += i; lcs.append(lc)
        valid = [x for x in lcs if x == x]      # 去掉 NaN（没量到的图幅）
        # ★ 2026-10-12：`n_sheets` **不是「平面图张数」**。行列对称后，每尺寸组会吸进一个**空模板框**
        #   （实测 C006 那个 x[225300,389100] y[8100,119100]、0 条墙；C007/C019/C066/L002 同款
        #   在 x[95400,211800] y[5400,84600]）。几何上分不开「一排真平面图」(C002) 与「一排图框」，
        #   ⇒ 只好留宽规则 + **配一条内容判据**：数每张图幅里的墙段，≥MIN_SEG 的才算真平面图。
        mids = [((s.bounds[0] + s.bounds[2]) / 2, (s.bounds[1] + s.bounds[3]) / 2) for s in ALLW]
        per = [sum(1 for x, y in mids if c["bbox"][0] <= x <= c["bbox"][2]
                   and c["bbox"][1] <= y <= c["bbox"][3]) for c in std]
        n_real = sum(1 for v in per if v >= MIN_SEG)
        return {"dxf": os.path.basename(path), "state": "OK", "layer": layer,
                "plan_state": plan_state(n_real),
                "n_sheets": len(std), "n_real": n_real, "n_empty_frame": len(std) - n_real,
                "per_sheet_wall": per, "n_other": len(others),
                "n_wall_seg": len(ALLW), "n_col": len(ALLC), "n_label": len(LABELS),
                "ref": round(tr, 1), "mod": round(tm, 1), "inter": round(ti, 1),
                "iou": round(100 * ti / max(tr + tm - ti, 1e-9), 2),
                "cov_min": round(min(valid), 2) if valid else None,
                "n_unmeasured": len(lcs) - len(valid),
                "cov_all100": bool(valid) and all(x >= 99.999 for x in valid),
                "sec": round(time.time() - t0, 1)}
    except Exception as e:
        return {"dxf": os.path.basename(path), "state": "BUILD_FAIL",
                "err": type(e).__name__, "msg": str(e)[:120], "sec": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=r"D:\项目\gym3d\材料\dxf_output")
    ap.add_argument("--json", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--margin", type=float, default=8000.0)
    ap.add_argument("--pos", default=None, help="正对照 DXF（必须状态 OK 且图幅≥1）")
    a = ap.parse_args()

    if a.pos:
        r = one(a.pos, a.margin)
        print("=== 正对照 ===", os.path.basename(a.pos), "->", r.get("state"),
              "图幅", r.get("n_sheets"), "覆盖min", r.get("cov_min"))
        if r.get("state") != "OK" or r.get("n_sheets", 0) < 1:
            print("  ✗ 正对照未触发 ⇒ 否定判词不算证据")
            return 1
        print("  ✓ 正对照触发")

    files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
    if a.limit:
        files = files[:a.limit]
    if not files:
        print("!! 无 dxf:", a.dir); return 2
    print("\n扫 %d 份（通用墙链）...\n" % len(files))
    res = []
    for i, f in enumerate(files, 1):
        r = one(f, a.margin)
        res.append(r)
        st = r["state"]
        if st == "OK":
            cov = "—" if r["cov_min"] is None else "%.2f%%" % r["cov_min"]
            print("%3d %-40s OK 图幅%2d(真%2d 空%2d) 墙段%6d 柱%5d IoU%6.2f%% 覆盖min%8s 未量到%d%s  %ss"
                  % (i, r["dxf"][:40], r["n_sheets"], r["n_real"], r["n_empty_frame"],
                     r["n_wall_seg"], r["n_col"],
                     r["iou"], cov, r["n_unmeasured"], "" if r["cov_all100"] else " ★", r["sec"]))
        else:
            print("%3d %-40s ** %-10s %s %s" % (i, r["dxf"][:40], st, r.get("err", ""), r.get("msg", "")))

    ok = [r for r in res if r["state"] == "OK"]
    if not ok:
        print("\n!! 没有一份 OK ⇒ 判据无意义（非空断言失败）")
        return 3

    print("\n===== 汇总（六态） =====")
    st = collections.Counter(r["state"] for r in res)
    for k, v in st.most_common():
        print("  %-12s %d" % (k, v))
    cov100 = [r for r in ok if r["cov_all100"]]
    cov_lt = [r for r in ok if not r["cov_all100"]]
    print("\n  建出墙的栋: %d/%d" % (len(ok), len(res)))
    print("  墙线覆盖 满100%%: %d   不满: %d" % (len(cov100), len(cov_lt)))
    if cov_lt:
        print("    ★ 覆盖不满（逐张看）:")
        for r in sorted(cov_lt, key=lambda x: (x["cov_min"] is None, x["cov_min"])):
            print("      %-40s 覆盖min %8s 未量到%d 图幅%d"
                  % (r["dxf"][:40], "—" if r["cov_min"] is None else "%.2f%%" % r["cov_min"],
                     r["n_unmeasured"], r["n_sheets"]))
    print("  ★ 真平面图张数（墙段≥%d）: 合计 %d / 图幅合计 %d（空模板框 %d）"
          % (MIN_SEG, sum(r["n_real"] for r in ok), sum(r["n_sheets"] for r in ok),
             sum(r["n_empty_frame"] for r in ok)))
    ps = collections.Counter(r["plan_state"] for r in ok)
    print("  ★ 内容闸（与 state 分开）: " + "  ".join("%s %d" % (k, v) for k, v in ps.most_common()))
    dis = [r for r in ok if r["plan_state"] != "PLANS_OK"]
    if dis:
        print("    ★ 几何 OK 但**内容闸不过**（几何 2 张 ≠ 真的有 2 张平面图）:")
        for r in dis:
            print("      %-40s %-9s 图幅%d 真%d 逐张墙段%s"
                  % (r["dxf"][:40], r["plan_state"], r["n_sheets"], r["n_real"],
                     sorted(r["per_sheet_wall"], reverse=True)[:6]))
    ncol = sum(1 for r in ok if r["n_col"] > 0)
    print("  建出柱的栋: %d/%d" % (ncol, len(ok)))
    print("  墙段合计: %d   柱块合计: %d" % (sum(r["n_wall_seg"] for r in ok), sum(r["n_col"] for r in ok)))

    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": a.dir, "n": len(res), "states": dict(st), "rows": res},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
