# -*- coding: utf-8 -*-
"""A1 **出口门**：同口径 IoU ≥ 95% **且**「墙厚 2 倍假件」在同一把尺子上**显著变红**。

为什么两件事都要量（方案 §9 A1 行）：
  · 交付件 IoU 恒 100% —— 因为参照足迹与模型足迹**由同一个 `fp` 列表**填出来 ⇒ 只能证
    「实现忠实于规则」，**证不了「墙对不对」**。单靠它会假绿（任何楼只要规则跑得动就是 100%）。
  · 所以出口门必须配一条**同一把尺子上的假件**：把模型那一半的墙身**向外膨胀 240 mm**
    （名义墙厚 ×2），参照那一半保持真件 ⇒ IoU **必须掉下来**。掉不下来 = 这把尺没牙。

判词：
  IoU_real  : 全部选中图幅的并集 IoU（**必须 ≥95%**；实测恒 100%，除非有真缺陷）
  IoU_fake  : 同一批图幅、同一把尺子，把模型换成 2 倍厚假件的并集 IoU（**必须显著 < IoU_real**）
  delta     : IoU_real − IoU_fake（**判的是掉下来，不是掉到某个数** —— 值随楼栋会变）

用法: python gate_exit.py <dxf> [--margin 8000] [--floor 75]
      （`--floor` 只用来印「过/不过」，**它不在证据链上** —— 证据是 delta 的方向与量级）
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent))
import sheet_grid as SG      # noqa: E402
import generic_wall as GW    # noqa: E402
import ezdxf                 # noqa: E402


def iou_over_cells(segs, cols, cells, margin, inflate=0.0):
    """把若干图幅的 (refA, modA, interA) 累加后算**并集 IoU**（不是逐格平均）。

    ★ 用并集而不是平均：逐格平均会让**只有一张图幅**的楼与十几张的楼等权，
      且空格（NaN）无法参与平均。并集口径与 c006 链的 `iou` 同口径（`ti/(tr+tm-ti)`）。
    """
    tr = tm = ti = 0.0
    for c in cells:
        x0, y0, x1, y1 = c["bbox"]
        r, m, i, _lc, _nq, _nu = GW.score_cell(segs, cols, x0, x1, y0, y1, margin, inflate=inflate)
        tr += r; tm += m; ti += i
    return {"ref": round(tr, 1), "mod": round(tm, 1), "inter": round(ti, 1),
            "iou": round(100 * ti / max(tr + tm - ti, 1e-9), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--margin", type=float, default=8000.0)
    ap.add_argument("--floor", type=float, default=75.0, help="只用于印过/不过，不在证据链上")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    p = Path(a.dxf)
    if not p.is_file():
        p = Path(r"D:\项目\gym3d\材料\dxf_output") / a.dxf
    doc = ezdxf.readfile(str(p)); msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    sheets = SG.merge_pairs(SG.collect_frames(msp, layer))
    _modal, std, _others = SG.classify(sheets)
    if not std:
        print("!! 该图无选中图幅 ⇒ 本门对它无结论（盲区：先过几何闸）"); return 2
    ALLW, ALLC, _LAB = GW.load_walls_and_cols_msp(msp)

    real = iou_over_cells(ALLW, ALLC, std, a.margin, 0.0)
    fake = iou_over_cells(ALLW, ALLC, std, a.margin, GW.WALL_T / 2)
    delta = real["iou"] - fake["iou"]

    print("DXF %s   选中图幅 %d   墙段 %d   margin %.0f"
          % (p.name, len(std), len(ALLW), a.margin))
    print("  %-22s %12s %12s %12s   IoU" % ("条件", "ref(m²)", "mod(m²)", "inter(m²)"))
    print("  %-22s %12.1f %12.1f %12.1f   %6.2f%%"
          % ("交付件", real["ref"], real["mod"], real["inter"], real["iou"]))
    print("  %-22s %12.1f %12.1f %12.1f   %6.2f%%"
          % ("墙厚2倍假件(模型+240mm)", fake["ref"], fake["mod"], fake["inter"], fake["iou"]))

    g1 = real["iou"] >= 95.0
    g2 = delta > 5.0
    print("\n  闸1 交付件 IoU ≥95%%          : %6.2f%%   %s" % (real["iou"], "PASS" if g1 else "FAIL"))
    print("  闸2 假件显著变红（Δ>5 点）      : %6.2f 点  %s   ← 判据的**牙**"
          % (delta, "PASS" if g2 else "FAIL ⇒ 这把尺逮不住背离规则的件"))
    print("  （参考：c006 链同口径实测假件掉到 57.48%%；`--floor %.0f` 只用于印'不过'，不在证据链上）" % a.floor)
    ok = g1 and g2
    print("\n★ 出口门 %s" % ("PASS" if ok else "FAIL"))
    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        json.dump({"dxf": p.name, "n_cells": len(std), "n_wall_seg": len(ALLW),
                   "real": real, "fake": fake, "delta": round(delta, 2),
                   "gate_iou>=95": g1, "gate_drop>5": g2, "pass": bool(ok)},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0 if ok else 1


sys.exit(main())
