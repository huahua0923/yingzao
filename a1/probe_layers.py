# -*- coding: utf-8 -*-
"""A1 侦察：**全库图层名普查**（可复用）—— 回答「某类构件到底有没有独立图层」。

背景：A1 反复栽在同一处 —— 把某个**图层名/块名**当成全库统一，实测却不是：
  `4.2墙体` 只有 101/105（另有 `4墙体`5/`4.3封墙`1/`4.3新封墙`1）；柱层 41/105；
  门/窗/梯/板/梁**一份独立层都没有**。⇒ 立一条纪律：**凡写死的图层名，先全库普查它的分布**。

本尺量（只读）：
  · 全库所有图层名 → 出现在**几份**图里（`n_files`）、累计实体数（`n_ent`）、实体类型构成
  · 按关键词分组（墙/柱/门/窗/梯/板/梁/轴/注/标/图框/层号…）打印

★ 量具盲区：只按**图层名字符串**归类；构件画在名字看不出用途的层（如 `0`/`A-WALL`）⇒ 本尺全盲；
  「某关键词 0 命中」≠「该构件不存在」，只等于「没有名字带这个词的层」。

用法: python probe_layers.py <dxf目录> [--json out.json] [--top N]
"""
import sys
import os
import glob
import json
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

GROUPS = {
    "墙": ("墙体", "封墙", "墙"),
    "柱": ("结构柱", "柱子", "柱"),
    "门": ("门",),
    "窗": ("窗",),
    "楼梯": ("楼梯", "梯", "STAIR"),
    "楼板": ("楼板", "板", "SLAB", "FLOOR"),
    "梁": ("梁", "BEAM"),
    "轴网": ("轴", "AXIS", "GRID"),
    "标注": ("标注", "注释", "尺寸", "DIM", "TEXT"),
    "图框": ("图框", "图签", "标题"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=r"D:\项目\gym3d\材料\dxf_output")
    ap.add_argument("--json", default=None)
    ap.add_argument("--top", type=int, default=60)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
    if not files:
        print("!! 无 *.dxf:", a.dir); return 2

    per_file = collections.Counter()      # 层名 → 出现在几份
    n_ent = collections.Counter()         # 层名 → 实体数
    types = collections.defaultdict(collections.Counter)
    for i, f in enumerate(files, 1):
        try:
            doc = ezdxf.readfile(f)
        except Exception as e:
            print("  !!", os.path.basename(f), type(e).__name__); continue
        seen = set()
        for e in doc.modelspace():
            lay = e.dxf.layer
            seen.add(lay)
            n_ent[lay] += 1
            types[lay][e.dxftype()] += 1
        for lay in seen:
            per_file[lay] += 1
        if i % 20 == 0:
            print("  ... %d/%d" % (i, len(files)))

    print("\n===== 全库图层名普查（分母 %d 份）=====" % len(files))
    print("%-28s %6s %10s  %s" % ("图层名", "n_files", "n_ent", "主要实体类型"))
    for lay, nf in per_file.most_common(a.top):
        tt = types[lay].most_common(3)
        print("%-28s %6d %10d  %s" % (lay[:28], nf, n_ent[lay],
                                      ", ".join("%s:%d" % t for t in tt)))

    print("\n===== 按关键词分组（n_files 分布）=====")
    for g, kws in GROUPS.items():
        hit = {lay: nf for lay, nf in per_file.items() if any(k.lower() in lay.lower() for k in kws)}
        tot = sorted(hit.values(), reverse=True)
        print("  %-6s 命中层 %2d 种，n_files Top: %s"
              % (g, len(hit), [(k, v) for k, v in sorted(hit.items(), key=lambda x: -x[1])[:6]]))

    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": a.dir, "n_files": len(files),
                   "layers": {lay: {"n_files": per_file[lay], "n_ent": n_ent[lay],
                                    "types": dict(types[lay])} for lay in per_file}},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
