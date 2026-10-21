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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B                                                    # noqa: E402

# ★ 2026-10-17：源件/数据根/层名改从楼栋档案读（`rebuild/构件库/楼栋.json`）。
#   不设环境变量时 = c006，行为与改之前一字不差。
SRC = B.profile()["src_dxf"]
ROOT = B.ROOT
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

# ★ 2026-10-17：与 recognize/redraw/build_rooms 同一份认定（墙层别写死）
WALL_LAYER = B.layer("wall", "4.2墙体")
LABEL_LAYER = B.keep_layer("面积", "5面积")
MIN_WALL = 1          # 窗口内墙层实体数下限；低于此判「没量到」

# ★ 2026-10-17：切图方式从楼栋档案读。
#   grid2col = c006 的两列 × 6 行写死网格（`frame_bands` + `SHEETS`）；
#   auto     = 复用 `a1/sheet_grid.py` 的通用尺子：找图框层 → 并内外框 → 分标准图幅 → 按 y 升序。
MODE = B.profile().get("sheet_mode", "grid2col")
A1 = os.path.join(os.path.dirname(B.REBUILD), "过程", "a1")


def frames_auto(doc, src):
    """图幅 → 楼层。先按**标题栏语义**排，读不到再退回几何排序。

    返回 (图框层, [{"bbox","floor"?}], 非楼层图幅数, 用哪把尺子)。

    ★ 2026-10-17：优先 `floor_from_title`（ACAD_TABLE 的「楼层」格 + 按楼层号排序）。
      原因：几何排序对**多列排布**会把上下层串开（C105 三列）；楼层号是图上写死的语义。
    ★ 两种「没读到」分开报（铁律 199）：
        title=0 张 ⇒ 标题栏不是 ACAD_TABLE（该尺盲区①）⇒ 退回几何尺，并**明说**退回了；
        title>0 张 ⇒ 用语义顺序；非楼层图幅（总平面/说明）按张数如实报出。
    """
    if A1 not in sys.path:
        sys.path.insert(0, A1)
    import sheet_grid as SG                                            # noqa: E402
    import floor_from_title as FT                                      # noqa: E402

    msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    if not layer:
        raise AssertionError("找不到图框层 ⇒ a1/sheet_grid 对本图全盲（盲区①）")

    res = FT.read_sheets(src, layer, content_score=lambda bb: counts(doc, bb)[0])
    if res["n_with_floor"]:
        # ★★ 2026-10-17 C022 实测：图里有**冒牌的「1层」图幅** —— 只有图框+标题栏、
        #   一张墙线都没有（x[1041765,1124565]，与真 1 层同面积 1122.12m、同楼层号），
        #   而 `read_sheets` 按面积去重、两张一样大 ⇒ 先到先得 ⇒ 拿到的是那张空壳，
        #   于是真 1 层根本没进窗口（症状：`1` 窗口 0 条墙，rc=4）。
        #   判据用**内容**：窗口里没有墙线的图幅不是平面图（与末尾 MIN_WALL 同一把尺子）。
        keep = [s for s in res["sheets"] if counts(doc, s["bbox"])[0] >= MIN_WALL]
        drop = [s for s in res["sheets"] if counts(doc, s["bbox"])[0] < MIN_WALL]
        if drop:
            print("★ 丢掉 %d 张没有墙线的图幅（冒牌/样板标题栏）：%s"
                  % (len(drop), [(s.get("floor"), [round(v) for v in s["bbox"]])
                                 for s in drop]))
        return layer, keep, res["n_sheets"] - res["n_with_floor"], "title"

    sheets = SG.merge_pairs(SG.collect_frames(msp, layer))
    modal, std, others = SG.classify(sheets)
    std = sorted(std, key=lambda s: (s["bbox"][1], s["bbox"][0]))   # 自下而上 = 1层起
    print("★ 标题栏尺子读到 0 层（ACAD_TABLE 盲区①）⇒ 退回几何排序，%d 张" % len(std))
    return layer, [{"bbox": s["bbox"]} for s in std], len(others), "grid"


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
    out = []
    if MODE == "auto":
        layer, std, n_other, how = frames_auto(doc, src)
        base = B.profile().get("basement")
        want = ([base] if base else []) + B.floor_names()
        if len(std) != len(want):
            raise AssertionError("图幅 %d 张 ≠ 档案层数 %d（%s；图上读到 %s）"
                                 % (len(std), len(want), want,
                                    [s.get("floor") for s in std]))
        for i, (name, s) in enumerate(zip(want, std)):
            x0, y0, x1, y1 = s["bbox"]
            nw, nl = counts(doc, (x0, y0, x1, y1))
            out.append({"name": name, "col": "C", "row": i,
                        "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                        "wall": nw, "label": nl,
                        "title_floor": s.get("floor")})
        print("图框层 %s ｜ 图幅 %d（尺子=%s）｜ 非楼层图幅 %d"
              % (layer, len(std), how, n_other))
    else:
        bands = frame_bands(doc)
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
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    print("写 %s：%d 层" % (OUT, r["n"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
