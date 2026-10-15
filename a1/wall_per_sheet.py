# -*- coding: utf-8 -*-
"""逐图幅数**墙实体** —— 这是判「是不是平面图」的外部量，与 gridify 无关。

争点：C002/C003 的 11 张同尺寸图幅排成**一行**，`gridify` 只认列 ⇒ 判它 NO_GRID。
      但那 11 张到底是 **11 张楼层平面图**（⇒ 尺子漏），还是 11 张排在一起的**详图/说明**（⇒ 尺子没漏）？
      几何分不开这两种 —— 得换一把**看内容**的尺子：平面图里必有墙线，详图/说明页没有（或极少）。

本脚本：把每张图幅的 bbox 当成窗口，数 **墙图层实体**（含别名）落在窗口里的条数，逐图幅报。
  平凡件：C010-银杏体育场（1 张）应≈0；C006（12 张真平面图）应张张有份量。

★ 盲区：① 只数墙层实体，**对「图幅里画的是别人的图」无免疫力**（本库未见图幅重叠，暂时接受）；
        ② 窗口按 bbox 取**矩形**，若两图幅 bbox 相交会把墙算进两张（故同时报 n_overlap）。
"""
import collections
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
import sheet_grid as SG                                    # noqa: E402
import ezdxf                                               # noqa: E402

SRC = Path(r"D:\项目\gym3d\材料\dxf_output")
WALL_LAYERS_HINT = ("墙体", "封墙", "4墙体")


def ent_mid(e):
    t = e.dxftype()
    try:
        if t == "LINE":
            return ((e.dxf.start.x + e.dxf.end.x) / 2, (e.dxf.start.y + e.dxf.end.y) / 2)
        if t == "LWPOLYLINE":
            p = list(e.get_points())
            if not p:
                return None
            return (sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p))
        if t in ("CIRCLE", "ARC"):
            return (e.dxf.center.x, e.dxf.center.y)
        if t in ("TEXT", "MTEXT", "INSERT"):
            return (e.dxf.insert.x, e.dxf.insert.y)
    except Exception:                                       # noqa: BLE001
        return None
    return None


def inside(bb, x, y):
    return bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]


def sheets_of(path):
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    frames = SG.collect_frames(msp, layer) if layer else []
    return msp, layer, SG.merge_pairs(frames)


def main(targets):
    for name in targets:
        msp, layer, sheets = sheets_of(SRC / name)
        wall_layers = {e.dxf.layer for e in msp if any(h in e.dxf.layer for h in WALL_LAYERS_HINT)}
        pts = [(e.dxf.layer, ent_mid(e)) for e in msp
               if e.dxf.layer in wall_layers and ent_mid(e) is not None]
        print("\n=== %s ===  图框层 %s  图幅 %d  墙层 %s  墙实体 %d"
              % (name, layer, len(sheets), sorted(wall_layers), len(pts)))
        # 图幅按面积排序，报前 16 张的窗口内墙实体数
        rows = []
        for s in sorted(sheets, key=lambda s: -((s["bbox"][2] - s["bbox"][0]) *
                                                (s["bbox"][3] - s["bbox"][1]))):
            bb = s["bbox"]
            n = sum(1 for _l, p in pts if inside(bb, p[0], p[1]))
            rows.append((round((bb[2] - bb[0])), round((bb[3] - bb[1])), n))
        # 重叠计数：两张图幅 bbox 相交的条数
        ov = sum(1 for i in range(len(sheets)) for j in range(i + 1, len(sheets))
                 if SG.inter_area(sheets[i]["bbox"], sheets[j]["bbox"]) > 0)
        print("   重叠图幅对 %d ；逐图幅（尺寸 × 墙实体数）：" % ov)
        for w, h, n in rows[:16]:
            print("      %8d × %-8d  墙 %6d  %s" % (w, h, n, "#" * min(n // 200, 40)))
        n_plan = sum(1 for _w, _h, n in rows if n >= 50)
        print("   ⇒ 墙实体≥50 的图幅 **%d / %d** 张" % (n_plan, len(rows)))
    return 0


sys.exit(main([
    "C002-南翼楼.dxf",          # 争点：11 张一行
    "C066-珙桐餐厅.dxf",         # 争点：2 张一行
    "C010-银杏体育场.dxf",        # 平凡件：1 张，应≈0
    "C006-第六教学楼（逸夫楼）.dxf",   # 正对照：12 张真平面图
]))
