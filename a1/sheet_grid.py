# -*- coding: utf-8 -*-
"""A1 量具：从 DXF 自动发现「平面图图幅」的排布，替掉 c006 链写死的 XBOX/XB/Y0/Y1 网格。

★ 原理（2026-10-12 实测发现，见方案 §9.2 A1 行）：
   这些 DWG 出自同一间办公室（图框统一），每张图纸的外框画在 `1图框` 层，
   且每张画成**两圈同心矩形**（内框 + 外框）。⇒
     ① 收集该层的闭合多段线；② 按 bbox 相交把内外框并成一张「图幅」；
     ③ 按尺寸众数分出「标准平面图幅」（其余是大样/总平面/说明）；
     ④ 图幅 bbox 本身即「层→图纸矩形」的通用锚，不再需要写死网格。

用法： python sheet_grid.py <dxf> [--layer 1图框] [--json out.json]

★ 量具盲区（必须声明）：
  ① 只认 `1图框` 层的**闭合多段线**。若某图把外框画成 LINE / 或画在别的层 ⇒ 本尺**全盲**（报 0 张）。
  ② 「标准尺寸」是**看谁能凑出最大的规则网格**（不是尺寸众数 —— 详图常同尺寸且数量压过平面图）。
     若某楼只有 1~2 张平面图，任何尺寸都凑不出 ≥2 的条带 ⇒ 落回众数并如实标注，**分类不稳**。
  ⑤ ★ **只有 1 张平面图的楼必然判 NO_GRID**，而 NO_GRID 把「这楼只有一层平面图」与「尺子没看见」印成同一个字。
     要分开得换一把**看内容**的尺子（数图幅里有没有墙实体，见 `a1/nogrid_wall_table.py`）。
  ⑥ ★ 行列对称后，**偶然与某一「行」同 Y 的孤立图框会被吸进来**（实测 C006 由 12 张变 13 张：多出
     x[225300,389100] 那一个，其实靠近原点的说明/图签框）。**几何上分不开「一整排平面图」与
     「一排互不相干的图」**（C002 就是前者）⇒ 只好取宽规则。代价有限：这类空图框进不了下游
     ——`generic_wall.score_cell` 对它返回覆盖率 **NaN**（无取样点），`batch_wall` 已按 NaN 滤掉，
     面积贡献也是 0。**要「真平面图张数」得配 `a1/nogrid_wall_table.py` 的内容尺子。**
  ③ 只报「图幅的几何位置与尺寸」，**说不出哪张是哪层**（标题不在模型空间，见下）。
     ⇒ 「层→图幅」的映射仍需**每楼一份小配置**（链里 SHEETS 那一项），本尺只自动给出**候选格子**。
  ④ 内外框**大小写死 2 圈**；3 圈或 1 圈的图框会并错。
"""
import sys
import os
import json
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

FRAME_LAYER_HINT = ("图框", "frame", "border", "图纸", "TK")


def bbox_of(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def inter_area(a, b):
    x0 = max(a[0], b[0]); y0 = max(a[1], b[1])
    x1 = min(a[2], b[2]); y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def area(a):
    return (a[2] - a[0]) * (a[3] - a[1])


def find_frame_layer(msp, forced):
    if forced:
        return forced
    lc = collections.Counter(e.dxf.layer for e in msp)
    hits = [l for l in lc if any(h in l.lower() or h in l for h in FRAME_LAYER_HINT)]
    if not hits:
        return None
    # 取候选里「闭合四点多段线」占比最高的那个
    best, best_ratio = None, -1.0
    for l in hits:
        tot = quad = 0
        for e in msp:
            if e.dxf.layer != l:
                continue
            tot += 1
            if e.dxftype() in ("LWPOLYLINE", "POLYLINE"):
                pts = list(e.get_points())
                if len(pts) == 4:
                    quad += 1
        r = quad / max(tot, 1)
        if r > best_ratio:
            best, best_ratio = l, r
    return best


MIN_SIDE = 5000.0      # 单位同图纸（C006 图幅 163800×111000）⇒ 小于 5 千的当退化/符号，不是图幅


def collect_frames(msp, layer):
    out = []
    for e in msp:
        if e.dxf.layer != layer:
            continue
        if e.dxftype() not in ("LWPOLYLINE", "POLYLINE"):
            continue
        pts = list(e.get_points())
        if len(pts) < 4:
            continue
        bb = bbox_of(pts)
        # ★ 退化过滤：实测 C037 有 33 条 (14200×0) 的零高多段线，不过滤会被当成 33 张图幅（假阳性）
        if (bb[2] - bb[0]) < MIN_SIDE or (bb[3] - bb[1]) < MIN_SIDE:
            continue
        closed = getattr(e, "closed", None)
        if closed is None:
            closed = getattr(e.dxf, "flags", 0) & 1
        out.append({"bbox": bb, "closed": bool(closed), "pts": len(pts)})
    return out


def merge_pairs(frames):
    """把内外框并成一张图幅：小框若被大框包含（重叠面积 > 小框 70%）就并进大框。"""
    frames = sorted(frames, key=lambda f: -area(f["bbox"]))
    merged = []
    for f in frames:
        placed = False
        for m in merged:
            ov = inter_area(f["bbox"], m["bbox"])
            if ov > 0.7 * area(f["bbox"]):
                x0 = min(f["bbox"][0], m["bbox"][0]); y0 = min(f["bbox"][1], m["bbox"][1])
                x1 = max(f["bbox"][2], m["bbox"][2]); y1 = max(f["bbox"][3], m["bbox"][3])
                m["bbox"] = (x0, y0, x1, y1)
                m["n"] += 1
                placed = True
                break
        if not placed:
            merged.append({"bbox": f["bbox"], "n": 1})
    return merged


def classify(sheets, min_col=2):
    """选「标准平面图幅」的尺寸：**看谁的规则网格最大**，不看谁张数最多。

    ★ 为什么不用尺寸众数：详情/大样图也常常同一尺寸、且数量能压过平面图（实测 C002 有 11 张
      小详图 vs 少数平面图）⇒ 众数会选错。平面图的定义特征是**成列成行地排**（≥2 行/列），
      详图则零零散散 ⇒ 取「按 X 分列、列内 ≥min_col 张」后**存留张数最多**的那个尺寸。
    返回 (modal_size, grid 列表, 全部 sheets 里不在 grid 里的 others)。
    """
    size = collections.Counter()
    for s in sheets:
        size[(round(s["bbox"][2] - s["bbox"][0]), round(s["bbox"][3] - s["bbox"][1]))] += 1
    by_size = {}
    for s in sheets:
        k = (round(s["bbox"][2] - s["bbox"][0]), round(s["bbox"][3] - s["bbox"][1]))
        by_size.setdefault(k, []).append(s)
    best = None
    for k, grp in by_size.items():
        kept = gridify(grp, min_col)
        score = (len(kept), k[0] * k[1])      # 存留张数优先，其次面积大
        if best is None or score > best[0]:
            best = (score, k, kept)
    if not best or not best[2]:
        # 全落单（如整张图只有 1~2 个平面图幅）⇒ 退回张数众数，但如实标注
        modal = size.most_common(1)[0][0] if size else None
        return modal, [], sheets
    _, modal, kept = best
    keep_ids = {id(s) for s in kept}
    return modal, kept, [s for s in sheets if id(s) not in keep_ids]


def _xov(a, b):
    """X 区间重叠长度（纵向排布的图幅在 Y 上不重叠，只能按 X 判同列）。"""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _bands(sheets, axis, min_span=2, frac=0.5):
    """把图幅按**某一轴上的区间重叠**聚成条带（axis='x' → 列；'y' → 行），只留 ≥min_span 张的。

    ★ 2026-10-12 补（一个实测到的**尺子漏**）：原 `gridify` 只聚**列**（X 重叠），
      于是「整套平面图横着排成一行」（同尺寸、X 各不相交、Y 相同）会被看成 N 个「1 张的列」而全被否
      ⇒ 判 NO_GRID。实测 **C002-南翼楼 / C003-北翼楼**：11 张 82800×56400 图幅横排成一行，
      `gridify` 报 0 列；而逐图幅数墙证明其中 **10 张各有 300+ 条墙实体** —— 那是**尺子漏**，不是没图。
      （C004F2-砚湖会议厅 同形：2 张带墙。）⇒ 改成**行列对称**地聚，任一方向成条带即保留。
    """
    def lo(b):
        return b[0] if axis == "x" else b[1]

    def hi(b):
        return b[2] if axis == "x" else b[3]

    bands = []
    for s in sorted(sheets, key=lambda s: lo(s["bbox"])):
        for b in bands:
            ov = max(0.0, min(hi(s["bbox"]), hi(b["box"])) - max(lo(s["bbox"]), lo(b["box"])))
            span = min(hi(s["bbox"]) - lo(s["bbox"]), hi(b["box"]) - lo(b["box"]))
            if ov > frac * span:
                b["box"] = (min(b["box"][0], s["bbox"][0]), min(b["box"][1], s["bbox"][1]),
                            max(b["box"][2], s["bbox"][2]), max(b["box"][3], s["bbox"][3]))
                b["m"].append(s)
                break
        else:
            bands.append({"box": s["bbox"], "m": [s]})
    return [b for b in bands if len(b["m"]) >= min_span]


def gridify(std, min_col=2, min_row=2):
    """给标准图幅编列/行号。**列或行**任一方向成条带（≥2 张）即保留，孤张详图两向皆落单才踢出。"""
    if not std:
        return []
    cols = sorted(_bands(std, "x", min_col), key=lambda c: c["box"][0])
    rows = sorted(_bands(std, "y", min_row), key=lambda r: -r["box"][3])
    idx = {}
    for ci, c in enumerate(cols):
        for s in c["m"]:
            idx.setdefault(id(s), {})["col"] = ci
    for ri, r in enumerate(rows):
        for s in r["m"]:
            idx.setdefault(id(s), {})["row"] = ri
    out = []
    for s in std:
        if id(s) in idx:
            s["col"] = idx[id(s)].get("col", 0)
            s["row"] = idx[id(s)].get("row", 0)
            out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--layer", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    if not os.path.isfile(a.dxf):
        print("MISSING:", a.dxf); return 2
    doc = ezdxf.readfile(a.dxf)
    msp = doc.modelspace()
    layer = find_frame_layer(msp, a.layer)
    print("DXF   :", os.path.basename(a.dxf))
    print("图框层:", layer)
    if not layer:
        print("!! 找不到图框层 ⇒ 本尺对该图全盲（见盲区①）")
        return 1
    frames = collect_frames(msp, layer)
    print("该层闭合/多段线 :", len(frames))
    sheets = merge_pairs(frames)
    print("并成图幅       :", len(sheets))
    modal, std, others = classify(sheets)
    n_by_size = collections.Counter(
        (round(s["bbox"][2] - s["bbox"][0]), round(s["bbox"][3] - s["bbox"][1])) for s in sheets)
    print("各尺寸张数     :", dict(n_by_size.most_common(4)))
    print("选中标准图幅   :", modal, "→", len(std), "张成网格")
    print("非标准/落单    :", len(others))
    print("\n== 标准平面图幅（列,行 → bbox） ==")
    for s in std:
        x0, y0, x1, y1 = s["bbox"]
        print("  col%d row%d  x[%9.0f,%9.0f] y[%9.0f,%9.0f]  %.0f×%.0f mm"
              % (s["col"], s["row"], x0, x1, y0, y1, x1 - x0, y1 - y0))
    for s in others:
        x0, y0, x1, y1 = s["bbox"]
        print("  [非标准]    x[%9.0f,%9.0f] y[%9.0f,%9.0f]  %.0f×%.0f mm"
              % (x0, x1, y0, y1, x1 - x0, y1 - y0))
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dxf": a.dxf, "layer": layer, "modal_mm": modal,
                   "n_std": len(std), "n_all": len(sheets),
                   "sheets": [{"col": s["col"], "row": s["row"],
                               "bbox": list(s["bbox"]), "n_frame_lines": s["n"]} for s in std],
                   "others": [list(s["bbox"]) for s in others]},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
