# -*- coding: utf-8 -*-
"""从 DXF 的 ACAD_TABLE 标题栏读出「哪张图幅是哪一层」，并按楼层号排好序。

★ 为什么要这把尺子
  `a1/sheet_grid.py` 只能给出图幅的**几何位置**，其文档第 ③ 条写明：
  「说不出哪张是哪层 ⇒ 层→图幅 的映射仍需每楼一份小配置」。
  而每张平面图图幅里都有一个 ACAD_TABLE 标题栏，格子里就写着「楼层」。
  按**语义**（楼层号）排序，比按 y 坐标排序可靠：多列排布（如 C105 cols=3）
  按 y 排序会把上下两层的列搞混，按楼层号则天然正确。

★ 量具盲区（必须声明）
  ① 只认 **modelspace 里的 ACAD_TABLE**。若某楼标题栏是炸开的 TEXT/MTEXT，
     或画在图纸空间（paper space）⇒ 本尺**全盲**，返回空列表（不是「这楼没有楼层」）。
  ② 只认「楼层」这两个字做锚。标题栏换行/改字（如「层数」「楼层号」）⇒ 该表读不出。
  ③ 楼栋表（*T0 那类）可能写错楼名（实测 C001 写成「水上图书团」），
     **本尺只把楼名当参考，不据此判楼层**。
  ④ 负数层只认 `D1`/`B1`/`-1` 这类写法；`地下一层` 走中文数字分支。

用法：
  python floor_from_title.py <dxf> [--json out.json]
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

_A1 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "过程", "a1"))
if _A1 not in sys.path:
    sys.path.insert(0, _A1)
import sheet_grid as SG  # noqa: E402

_RTF = re.compile(r"\\[A-Za-z][^;\\]*;")
_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
       "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_ANCHORS = ("建筑编号", "建筑名称", "楼层", "建筑面积")


def plain(s):
    """去掉 DXF 的 RTF 控制码与花括号，返回纯文本。"""
    s = (s or "").replace("\n", " ").replace("\r", " ")
    s = _RTF.sub("", s)
    s = s.replace("{", "").replace("}", "")
    return s.strip()


def _block_by_record(doc, handle):
    """ACAD_TABLE 存的是 block **record** 的 handle，而 doc.blocks 按块名索引
    （实测 `doc.blocks['1DD8F']` 抛 DXFKeyError）⇒ 先按 block_record 的 handle 找到块名。"""
    for blk in doc.blocks:
        try:
            if blk.block_record.dxf.handle.upper() == handle.upper():
                return blk
        except Exception:
            continue
    return None


def table_cells(doc, table):
    """ACAD_TABLE 的格子文字：读它引用的匿名块里的 MTEXT（按实体顺序）。"""
    out = []
    blk = _block_by_record(doc, table.dxf.block_record_handle)
    if blk is None:
        return out
    for e in blk:
        if e.dxftype() == "MTEXT":
            t = plain(e.text)
            if t:
                out.append(t)
    return out


def table_meta(doc, msp):
    """modelspace 里每张标题栏：插入点 + 各字段。"""
    rows = []
    for e in msp:
        if e.dxftype() != "ACAD_TABLE":
            continue
        cells = table_cells(doc, e)
        f = {}
        for i, c in enumerate(cells[:-1]):
            if c in _ANCHORS and c not in f:
                f[c] = cells[i + 1]
        ins = e.dxf.insert
        rows.append({"insert": (float(ins[0]), float(ins[1])),
                     "fields": f, "cells": cells})
    return rows


def ordinal(name):
    """楼层名 → 序号（地下为负）。认不出返回 None。"""
    if not name:
        return None
    s = name.strip().upper().replace("　", "").replace(" ", "")
    m = re.match(r"^(?:D|B|-)(\d+)$", s)
    if m:
        return -int(m.group(1))
    m = re.match(r"^(\d+)(?:F|层)?$", s)
    if m:
        return int(m.group(1))
    if "地下" in s:
        m = re.search(r"([一二三四五六七八九十])", s)
        if m:
            return -_CN[m.group(1)]
    if "首" in s:
        return 1
    m = re.match(r"^([一二三四五六七八九十])\s*层$", s)
    if m:
        return _CN[m.group(1)]
    return None


def _inside(pt, bb, pad=1.0):
    return (bb[0] - pad <= pt[0] <= bb[2] + pad) and (bb[1] - pad <= pt[1] <= bb[3] + pad)


def area_num(s):
    """'6446.17m' → 6446.17；认不出返回 0。"""
    m = re.search(r"([\d.]+)", s or "")
    try:
        return float(m.group(1)) if m else 0.0
    except ValueError:
        return 0.0


MIN_PLAN_AREA = 200.0   # ★ 样板/示例标题栏一律写 100.00m²（实测 C006 有 3 张），真图 ≥ 1500


def read_sheets(dxf_path, frame_layer=None, min_area=MIN_PLAN_AREA, content_score=None):
    """返回按楼层号排好序的标准层图幅。

    ★ 为什么要两道筛（实测 C006）：
      同一份 DXF 里混着**样板标题栏**（建筑面积 100.00m、房间数 2、图号留空）
      甚至**别的楼**的样表（C006 文件里有一张 `建筑编号 C105`，面积 8954.43m）。
      真图：① 面积 ≥ 200 m²；② 建筑编号 = 本楼的主号（取候选里出现最多的那个）。
      两道筛后 C006 = 12 张（D1 + 1..11），与已知真值一致；C005 = 5 张。
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    lay = SG.find_frame_layer(msp, frame_layer)
    sheets = SG.merge_pairs(SG.collect_frames(msp, lay)) if lay else []
    metas = table_meta(doc, msp)

    cand = []
    for s in sheets:
        hit = [m for m in metas if _inside(m["insert"], s["bbox"])]
        if not hit:
            continue
        f = hit[0]["fields"]
        o = ordinal(f.get("楼层"))
        a = area_num(f.get("建筑面积"))
        if o is None or a < min_area:
            continue
        cand.append({"bbox": s["bbox"], "ordinal": o, "floor": f.get("楼层"),
                     "building": f.get("建筑名称", ""),
                     "no": (f.get("建筑编号") or "").strip().upper(),
                     "area": f.get("建筑面积", ""), "area_num": a})

    # 本楼主号 = 候选里出现最多的建筑编号；只有一号多张时才用它筛（单调表不筛）
    cnt = {}
    for c in cand:
        cnt[c["no"]] = cnt.get(c["no"], 0) + 1
    modal = max(cnt, key=cnt.get) if cnt else ""
    if modal and cnt[modal] >= 2:
        cand = [c for c in cand if c["no"] == modal]

    # 同一楼层若仍有多张 ⇒ 先看**窗口里有没有内容**（`content_score`，调用方给的小尺子），
    # 一样多再取面积最大那张（真图 > 样板），并如实计数。
    # ★★ 2026-10-17 C022 实测：图里有一张**冒牌「1层」** —— 只有图框+标题栏、0 条墙线，
    #   而它的「建筑面积」与真 1 层**一字不差**（1122.12m）⇒ 只按面积去重先到先得，
    #   拿到的是空壳，真 1 层被丢掉（下游「图幅 6 张 ≠ 档案层数 7」才炸）。
    #   面积是**图上写的字**，墙线是**画出来的东西**：两者相争，画出来的赢。
    by_floor = {}
    for c in cand:
        cur = by_floor.get(c["ordinal"])
        if cur is None:
            by_floor[c["ordinal"]] = c
            continue
        if content_score is not None:
            a, b = content_score(c["bbox"]), content_score(cur["bbox"])
            if a != b:
                if a > b:
                    by_floor[c["ordinal"]] = c
                continue
        if c["area_num"] > cur["area_num"]:
            by_floor[c["ordinal"]] = c
    floors = sorted(by_floor.values(), key=lambda c: c["ordinal"])

    return {"dxf": os.path.abspath(dxf_path), "frame_layer": lay,
            "n_sheets": len(sheets), "n_with_floor": len(floors),
            "n_candidates": len(cand), "building_no": modal,
            "sheets": [{"bbox": [round(v, 1) for v in s["bbox"]],
                        "floor": s["floor"], "ordinal": s["ordinal"],
                        "building": s["building"], "no": s["no"],
                        "area": s["area"]} for s in floors]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--layer", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    r = read_sheets(a.dxf, a.layer)
    txt = json.dumps(r, ensure_ascii=False, indent=1)
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt + "\n")
    print(txt)
    print("图幅 %d 张，读到楼层 %d 张：%s" % (
        r["n_sheets"], r["n_with_floor"],
        ", ".join("%s(%s)" % (s["floor"], s["area"]) for s in r["sheets"])))
    return 0 if r["n_with_floor"] else 4


if __name__ == "__main__":
    sys.exit(main())
