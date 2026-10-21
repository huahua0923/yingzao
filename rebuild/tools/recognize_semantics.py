# -*- coding: utf-8 -*-
r"""语义识别：把源图上的**文字标注**挂到「楼板 − 墙带」分出的分区上。

为什么要有这一步（2026-10-19 用户「你先做识别这个事情」「阳台、屋檐等」）：
  现在的链只认**几何**（墙/柱/门/梯），图上的 `5面积 / 6房间号 / 7用途分类 / 8使用单位`
  四层文字**全被丢掉**。可是「露台」就写在 `5面积` 层里（c001 实测 4 处：4 层 2、
  5 层 2），它决定了那块楼板**该不该有屋顶**——这正是 CAD 识别件与手建件最大的差别
  之一（手建件 ts4 有挑空/露台，识别件每层都是整块楼板）。

怎么挂（不新造判据）：
  · 分区 = `redraw.geometry(层)` 的 `plate − 墙带`（与 `build3d.top_roof_zone` 同一算
    法：连通开敞区 > 1 m²）。**不自己判墙**，墙的改动会跟着整条链走。
  · 文字锚点外扩 200 mm（与 `build3d.ROOF_LABEL_R_MM` 同口径，实测 r=0 命中 0 个：
    MTEXT 的 insert 常压在墙线上）→ 命中的分区 = 这条文字所属的房间。
  · 一条文字命中多个分区 ⇒ 取**面积最小**的那个（大的那个通常是走廊/大堂）。
  · 一句都挂不上的文字 ⇒ **照样输出**并标 `未落区`，不许静默丢（铁律 137/158）。

识别得出的两类语义：
  · **露台**（`5面积` 文字里含「露台」）：出件时是**开敞平台**，不建墙不建顶。
  · **无标注大区**：分区面积 ≥ `BIG_REGION_M2` 且一句文字都没有 ⇒ 只是**候选**
    （走廊、大堂、挑空都会落进来），不是结论；挑空要另一把尺子（DSM/手建件）证。

★ 盲区（必须与结论分开读）：
    · 这张图**没有窗图层**（12 层只有 0/3轴线/4.1结构柱/4.2墙体/5面积/6房间号/
      7用途/8单位/Defpoints）⇒ 本模块对**外立面开窗、屋檐、雨篷一无所知**；
      这三样只能由影像/倾斜摄影给（用户 2026-10-19 原话「通过图片或者倾斜摄影来
      解决外立面的问题」）。
    · `6房间号` 层里混着面积文字（c001 4 层实测 4 条 `17.50m2^`）⇒ 房间号按
      「像编号」判（含 `-`），不像编号的并入面积列，读数印出来。
    · `5面积` 的文字是**申报面积**，与分区现算面积不一定相等（墙体口径不同）；
      两个数并列输出，不做谁对谁错的判断。

输出：rebuild/<栋>/02_recognize/语义.json（字节层写盘，铁律 79）
用法：CDUT_BUILDING=c001 python -X utf8 -I rebuild/tools/recognize_semantics.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import shapely.geometry as sg
from shapely.ops import unary_union

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B                                                     # noqa: E402
import redraw as RD                                                      # noqa: E402

LABEL_R_MM = 200.0          # 文字锚点外扩（与 build3d.ROOF_LABEL_R_MM 同口径）
MIN_REG_M2 = 1.0            # 分区最小面积（与 top_roof_zone 同口径）
BIG_REGION_M2 = 50.0        # 「无标注大区」候选阈值（只用于报告，不用于出件）
TEXT_SUFFIXES = (("面积", "面积"), ("房间号", "房间号"),
                 ("用途", "用途"), ("单位", "使用单位"))


def _poly(ring, holes=None):
    try:
        p = sg.Polygon(ring, [h for h in (holes or []) if len(h) >= 3])
    except Exception:                                                  # noqa: BLE001
        return None
    if not p.is_valid:
        p = p.buffer(0)
    return None if p.is_empty else p


def _flat(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [q for q in g.geoms if q.geom_type == "Polygon" and not q.is_empty]
    return [g]


def _ring(g):
    return [[round(x, 1), round(y, 1)] for x, y in g.exterior.coords[:-1]]


def floor_list():
    """楼层名：地下室在前，然后按档案的地上层层表。只取 raw 里真有 dxf 的。"""
    d = os.path.join(B.ROOT, "01_cad", "raw")
    have = {f[:-4] for f in os.listdir(d) if f.endswith(".dxf")}
    names = [n for n in B.floor_names() if n in have]
    under = sorted(n for n in have if n not in names and not n.endswith("层"))
    return under + names


def read_labels(floor, layers):
    """该层 raw DXF 的四类文字 → [(kind, text, x, y)]（模型坐标 mm）。"""
    import ezdxf
    path = os.path.join(B.ROOT, "01_cad", "raw", "%s.dxf" % floor)
    if not os.path.exists(path):
        return []
    out = []
    for e in ezdxf.readfile(path).modelspace():
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        lay = e.dxf.layer
        kind = next((k for k, L in layers.items() if L and lay == L), None)
        if kind is None:
            continue
        try:
            text = e.plain_text().strip() if e.dxftype() == "MTEXT" else str(e.dxf.text).strip()
        except Exception:                                              # noqa: BLE001
            continue
        if not text:
            continue
        p = e.dxf.insert
        out.append((kind, text, float(p.x), float(p.y)))
    return out


_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*m", re.I)


def _area_of(text):
    m = _NUM.search(text.replace("^", " "))
    return float(m.group(1)) if m else None


def _is_room_no(text):
    return bool(re.search(r"\d+-\d+", text))


def floors_geometry(floor):
    """→ (分区列表, 读数)。分区 = plate − 墙带，与 build3d.top_roof_zone 同算法。"""
    v = RD.geometry(floor)
    plate = unary_union([p for p in (_poly(s) for s in (v.get("plate") or [])) if p])
    walls = unary_union([p for p in (_poly(s, h) for s, h in (v.get("walls") or [])) if p])
    if plate.is_empty:
        return [], {"plate_m2": 0.0, "wall_bands": 0}
    regs = [g for g in _flat(plate.difference(walls)) if g.area > MIN_REG_M2 * 1e6]
    return regs, {"plate_m2": round(plate.area / 1e6, 2), "wall_bands": len(v.get("walls") or [])}


def assign(regs, labels):
    """文字锚点 → 分区（命中多个取面积最小）。返回 (每区标注, 未落区)。"""
    per = [dict(房间号=[], 用途=[], 单位=[], 面积=[], 露台=False) for _ in regs]
    loose = []
    for kind, text, x, y in labels:
        b = sg.Point(x, y).buffer(LABEL_R_MM)
        hit = [i for i, g in enumerate(regs) if g.intersects(b)]
        if not hit:
            loose.append([kind, text, round(x, 1), round(y, 1)])
            continue
        i = min(hit, key=lambda j: regs[j].area)
        if kind == "面积":
            per[i]["露台"] = per[i]["露台"] or ("露台" in text)
            a = _area_of(text)
            if a is not None:
                per[i]["面积"].append(a)
        elif kind == "房间号":
            if _is_room_no(text):
                per[i]["房间号"].append(text)
            else:                                                      # 混进来的面积字
                a = _area_of(text)
                if a is not None:
                    per[i]["面积"].append(a)
        elif kind == "用途":
            per[i]["用途"].append(text)
        else:
            per[i]["单位"].append(text)
    return per, loose


def run():
    layers = {}
    for suffix, kind in TEXT_SUFFIXES:
        layers[kind] = B.keep_layer(suffix, None)
    out = dict(栋=B.BID, 读法=dict(
        标签层=layers, 锚点外扩_mm=LABEL_R_MM, 分区最小面积_m2=MIN_REG_M2,
        无标注大区阈值_m2=BIG_REGION_M2,
        盲区="无窗图层/无屋檐图层：外立面开窗、雨篷、挑檐一律不在本文件的识别范围内",
    ), 层=[])
    n_all = n_lab = n_terr = 0
    for floor in floor_list():
        regs, diag = floors_geometry(floor)
        labels = read_labels(floor, layers)
        per, loose = assign(regs, labels)
        rows, big = [], []
        for i, g in enumerate(regs):
            r = per[i]
            tagged = bool(r["房间号"] or r["用途"] or r["单位"] or r["面积"] or r["露台"])
            row = dict(
                房间号="、".join(r["房间号"]), 用途="、".join(r["用途"]),
                单位="、".join(r["单位"]),
                声明面积_m2=(round(sum(r["面积"]) / len(r["面积"]), 2) if r["面积"] else None),
                现算面积_m2=round(g.area / 1e6, 2),
                露台=bool(r["露台"]), 已标注=tagged, ring=_ring(g),
            )
            rows.append(row)
            n_all += 1
            if tagged:
                n_lab += 1
            if r["露台"]:
                n_terr += 1
            if not tagged and g.area / 1e6 >= BIG_REGION_M2:
                b = g.bounds
                big.append(dict(面积_m2=round(g.area / 1e6, 2),
                                bbox_m=[round(b[2] - b[0], 1), round(b[3] - b[1], 1)]))
        out["层"].append(dict(层=floor, 读数=diag, 分区=len(regs),
                              已标注=sum(1 for q in rows if q["已标注"]),
                              露台=[q["现算面积_m2"] for q in rows if q["露台"]],
                              房间=rows, 无标注大区=big, 未落区=loose))
        print("%-4s 分区 %3d · 已标注 %3d · 露台 %d %s · 未落区 %d · 无标注大区 %d"
              % (floor, len(regs), sum(1 for q in rows if q["已标注"]),
                 len(out["层"][-1]["露台"]), out["层"][-1]["露台"], len(loose), len(big)))
        for q in loose:
            print("      未落区：%s「%s」 at (%.0f, %.0f)" % (q[0], q[1], q[2], q[3]))

    path = os.path.join(B.ROOT, "02_recognize", "语义.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False).encode("utf-8")
    with open(path, "wb") as fh:                                       # 字节层写盘（铁律 79）
        fh.write(data)
    print("合计 分区 %d · 已标注 %d · 露台 %d ⇒ %s" % (n_all, n_lab, n_terr, path))
    return 0


if __name__ == "__main__":
    sys.exit(run())
