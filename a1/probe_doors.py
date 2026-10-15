# -*- coding: utf-8 -*-
"""A1 侦察：门到底画在哪、怎么画；`门标注` 的 TEXT 能不能当**外部量**（不来自 `4.2墙体` 几何）。

背景（A1 实测）：105 份里**只有 3 份**有名字带「门」的层，且主力是 `4.3门标注` = **MTEXT 文字**；
窗/电梯/楼梯/楼板/梁/台阶**一份独立层都没有** ⇒ 这些构件全在 `4.2墙体` 里，只能按**几何**分。

本尺量三样：
  ① 全图「门」类 MTEXT 文本（`4.3门标注` / 任意层）—— 候选**外部量**（人写文字，不由墙线派生）
  ② `4.2墙体` 里 LWPOLYLINE 的**顶点数分布** —— 验 gym3d「门≥10 点」那条老启发式还成不成立
  ③ `4.2墙体` 里 INSERT 块名前缀 —— 门/窗可能是块

用法: python probe_doors.py <dxf> [...]   （可给多份）
"""
import sys
import os
import re
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

DOOR_NUM = re.compile(r"\s*[A-Za-z]{0,3}\d{2,4}\s*$")   # 形如「M0921」「1024」「C1」的门窗编号


def probe(path):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    # ① 门类文本
    txt_layers = collections.Counter()
    door_nums = []
    for e in msp:
        t = e.dxftype()
        if t not in ("TEXT", "MTEXT"):
            continue
        s = (e.dxf.text if t == "TEXT" else e.text) or ""
        s = s.strip()
        if not s:
            continue
        if "门" in e.dxf.layer:
            txt_layers[e.dxf.layer] += 1
        if DOOR_NUM.match(s):
            door_nums.append((s, e.dxf.layer))
    # ② 墙层顶点数分布 + ③ 墙层块
    W = "4.2墙体"
    vtx = collections.Counter()
    blk = collections.Counter()
    for e in msp:
        if e.dxf.layer != W:
            continue
        if e.dxftype() == "LWPOLYLINE":
            n = len(list(e.get_points()))
            vtx[min(n, 30)] += 1
        elif e.dxftype() == "INSERT":
            blk[(e.dxf.name or "")[:16]] += 1
    return {"dxf": os.path.basename(path), "txt_layers": dict(txt_layers),
            "n_door_num": len(door_nums), "door_num_layers": dict(collections.Counter(l for _, l in door_nums)),
            "wall_vtx": dict(sorted(vtx.items())), "wall_blocks": dict(blk.most_common(8)),
            "sample_nums": [s for s, _ in door_nums[:25]]}


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    for p in sys.argv[1:]:
        if not os.path.isfile(p):
            print("MISSING:", p); continue
        r = probe(p)
        print("\n===== %s =====" % r["dxf"])
        print("  门类文本层      :", r["txt_layers"] or "无")
        print("  门编号式文本    : %d 条  层分布:%s" % (r["n_door_num"], r["door_num_layers"]))
        print("    样例          :", r["sample_nums"][:15])
        print("  4.2墙体 顶点数分布(封顶30):", r["wall_vtx"])
        print("  4.2墙体 块前缀  :", r["wall_blocks"] or "无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
