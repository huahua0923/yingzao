# -*- coding: utf-8 -*-
"""12 个图幅窗口 —— 从图里的 `1图框` **量**出来，不手打、不猜行距。

★ 为什么要有这个文件：每层的平面图坐在**哪一段坐标**里，是后续一切（搬线、灌满、拉伸）
  的前提。上一轮我按 `Y1-Y0 = 87500` 当行距算，结果 11 层窗口里只剩 20 条墙 —— 错的。
  真实行距是 **135000**（图框高 104700 + 30000 间隙），`87500` 是**图幅内容高**，不是行距。
  现在改成从 `1图框` 的实测外框分组，**行距由数据给出**，源件一换窗口自动跟着变。

★ 图框成对出现（标题栏边框 + 绘图边框，宽 162000/163800、高 104700/111000），
  故每行取**这一对的外包框**，不取单个。

输出：`rebuild/windows.json`
  { "units": "mm", "src": "...", "n": 12,
    "sheets": [ {"name":"1层","col":"L","row":0,
                 "x0":..,"x1":..,"y0":..,"y1":..,"wall":1623,"label":33}, ... ] }
  `wall`/`label` 是窗口内 `4.2墙体` / `5面积` 的实体数 —— **正对照**：
  任何一层的 wall 数为 0，说明窗口错位，本文件即判「没量到」并 rc=4。
"""
from __future__ import annotations

import json
import os
import sys

import ezdxf
from ezdxf import bbox

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SRC = r"D:\项目\gym3d\材料\dxf_output\C006-第六教学楼（逸夫楼）.dxf"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "windows.json")

# 两列各自的 x 走廊（取自实测：L 列图框 x∈[996705,1158705]，R 列 x∈[1465480,1629280]，
# 中间留出余量；这两个常数只是**分组用**，不参与窗口边界计算）
COL_X = {"L": (960000.0, 1200000.0), "R": (1430000.0, 1660000.0)}

# 层名 → (列, 行)。行号 0 = **最下面那一行**。
# 依据：1 层图幅内容 y∈[47500,135000]（libs3d `build8.py` SHEETS + `_scratch/acad.py` 实测），
# 而它落在最低那行图框内 ⇒ row 0 = 最低行。
SHEETS = ([("地下1层", "R", 5)]
          + [("%d层" % i, "L", i - 1) for i in range(1, 7)]
          + [("7层", "R", 0)]
          + [("%d层" % i, "R", i - 7) for i in range(8, 12)])

WALL_LAYER = "4.2墙体"
LABEL_LAYER = "5面积"
MIN_WALL = 1          # 窗口内墙层实体数下限；低于此判「没量到」


def frame_bands(doc):
    """把 `1图框` 按列分组、按 y 升序两两合并 ⇒ 每列 6 条行带。"""
    fr = []
    for e in doc.modelspace():
        if e.dxf.layer != "1图框" or e.dxftype() != "LWPOLYLINE":
            continue
        bb = bbox.extents([e])
        if bb.has_data:
            fr.append((bb.extmin.x, bb.extmin.y, bb.extmax.x, bb.extmax.y))

    bands = {}
    for col, (cx0, cx1) in COL_X.items():
        mine = [f for f in fr if cx0 <= (f[0] + f[2]) / 2.0 <= cx1]
        mine.sort(key=lambda f: (f[1] + f[3]) / 2.0)
        if len(mine) != 12:
            raise AssertionError("列 %s 的图框数 %d ≠ 12（图框成对，应为 6 行 × 2）"
                                 % (col, len(mine)))
        rows = []
        for k in range(6):
            a, b = mine[2 * k], mine[2 * k + 1]
            rows.append((min(a[0], b[0]), min(a[1], b[1]),
                         max(a[2], b[2]), max(a[3], b[3])))
        bands[col] = rows
    return bands


def counts(doc, band):
    """窗口内的墙层 / 标签实体数（正对照用）。按**要素 bbox 与窗口相交**判，不按插入点。"""
    x0, y0, x1, y1 = band
    nw = nl = 0
    for e in doc.modelspace():
        bb = bbox.extents([e])
        if not bb.has_data:
            continue
        if not (bb.extmin.x <= x1 and bb.extmax.x >= x0
                and bb.extmin.y <= y1 and bb.extmax.y >= y0):
            continue
        if e.dxf.layer == WALL_LAYER:
            nw += 1
        elif e.dxf.layer == LABEL_LAYER:
            nl += 1
    return nw, nl


def build(src=SRC):
    doc = ezdxf.readfile(src)
    bands = frame_bands(doc)
    out = []
    for name, col, row in SHEETS:
        x0, y0, x1, y1 = bands[col][row]
        nw, nl = counts(doc, (x0, y0, x1, y1))
        out.append({"name": name, "col": col, "row": row,
                    "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "wall": nw, "label": nl})
    return {"units": "mm", "src": src, "n": len(out), "sheets": out}


def main():
    r = build()
    bad = [s for s in r["sheets"] if s["wall"] < MIN_WALL]
    for s in r["sheets"]:
        print("%-8s %s%d  x[%.0f,%.0f] y[%.0f,%.0f]  墙 %4d 标签 %3d"
              % (s["name"], s["col"], s["row"], s["x0"], s["x1"],
                 s["y0"], s["y1"], s["wall"], s["label"]))
    if bad:
        print("★ 没量到：%s 窗口内墙层实体 < %d"
              % ([s["name"] for s in bad], MIN_WALL))
        return 4                                    # 没量到 ≠ 判红
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    print("写 %s：%d 层" % (OUT, r["n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
