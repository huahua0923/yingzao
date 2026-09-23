# -*- coding: utf-8 -*-
"""「图纸自己声明的楼层」 vs 「模型里实际有的层」 —— B4 的读数层。

## 这条判据为什么必须存在

2026-09-23 用户点了一句「水上图书馆，f0其实是两层」。查下去不是标注错、也不是
房间漏抽，是**整层没进模型**：c001 图纸自带面积表写着 6 层（`D1` + `1`~`5`），
模型只有 5 层，`D1` 那层（6 间房、建筑面积 1540.50㎡、图号 C001-D1）压根不在。

再往后量全库：**95 栋里 17 栋**图纸层数 > 模型层数，而且是**成类**的 ——
    · 少一个 `D1`（地下一层）：c001 c006 c011 c020 c074 c075 c107
    · 少一层夹层 `J`：c015（`1,1J,2,2J,3,3J` = 3 层 + 3 夹层，模型只有 3 层）、c115
    · 少 `H`：c009
    · 被并成 1 层：c002 c003 c081 c105 c115 c118
共同点是**层号不是纯数字**（`D1`/`J11`/`H`），而发现楼层的代码按纯整数认 ——
于是「图纸有 D1」和「图纸没有 D1」在产物里长得一模一样（CLAUDE.md 铁律 16）。

## 两把曾经的错量具（写在这里，别再走回头路）

1. **把全图的面积表都当自己的**。统一出图的图册里，一张 DXF 装了多栋的表：
   实测 c002/c003/c009 的图里都躺着 `图号=C105-01`、`C00X-05` 的行，**数值一模一样**。
   不按图号归属过滤，就会报出一堆别人家的层。
   ⇒ 只认 **图号前缀 == 本栋编号** 的行。
2. **把「表插入点的 Y」当成「层的 Y」**。c001 恰好一层一张表，y 与层带下界逐个相等；
   但 c002 十层挤在**一张**表里（同一个 insert y=66395）。以一栋的巧合当通则，
   全库就会算错。⇒ 用**层号标签**，不用 y。

## 也量不到的情况必须能说出口

读不到源 DXF、图上没有本栋图号的表 —— 一律走 UNAVAILABLE，**不许默认成"对齐"**。
没量过和全对长得一样，正是这个项目栽过多次的坑。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# 图册模板里的示例行：建筑面积刚好 100.00㎡。
# ★ 这是 `_scratch/_area_audit.py` 里既有的口径（它自己做 99.5~100.5 的过滤），
#   本模块与它保持一致；但**不过滤掉就静默**，剔了几行要报出来。
TEMPLATE_AREA = (99.5, 100.5)

# 汇总行（不是层）："标准层"是整栋的典型层指标，图号常写成 C0NN-X
SUMMARY_LABELS = ("标准层", "合计", "总计")


def own_prefix(name: str) -> str:
    """本栋编号前缀：c002 → C002；m281 → M281；c004f1 → C004（同一个图册）。"""
    m = re.match(r"([cmCM]\d{3})", str(name))
    return (m.group(1) if m else str(name)).upper()


def _clean(s) -> str:
    s = re.sub(r"[\\][A-Za-z][^;]*;", "", str(s))
    s = re.sub(r"[\\][Pp]", " ", s)
    s = re.sub(r"[\^][Jj]", " ", s)
    return re.sub(r"\s+", " ", s.replace("{", "").replace("}", "")).strip()


def _num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group(0)) if m else None


def read_area_rows(dxf_path) -> list[dict]:
    """全图所有 ACAD_TABLE 的行（**带图号**，供按图号归属过滤）。

    ezdxf 这个版本把 ACAD_TABLE 当代理实体（读不出 n_rows/n_cols），
    所以靠 `virtual_entities()` 拿单元格文字，再按 `键,值,键,值…` 配对。
    """
    import ezdxf

    doc = ezdxf.readfile(str(dxf_path))
    out = []
    for t in doc.modelspace():
        if t.dxftype() != "ACAD_TABLE":
            continue
        vals = []
        try:
            for v in t.virtual_entities():
                if v.dxftype() in ("TEXT", "MTEXT"):
                    vals.append(_clean(v.dxf.text if v.dxftype() == "TEXT" else v.text))
        except Exception:                       # noqa: BLE001 —— 读不出的表跳过，
            continue                            # 但"一张表都没读到"由上层报 UNAVAILABLE
        d = {vals[i]: vals[i + 1] for i in range(0, len(vals) - 1, 2)}
        out.append({"label": d.get("楼层"), "m2": _num(d.get("建筑面积", "")),
                    "rooms": _num(d.get("房间数", "")), "sheet": str(d.get("图号") or ""),
                    "bname": d.get("建筑名称")})
    return out


def drawing_levels(rows: list[dict], prefix: str) -> tuple[list[str], dict]:
    """图纸自己声明的楼层标签（保留原文：`D1`/`J11`/`H` 不许被 int() 吃掉）。

    返回 (labels, stats)。labels 按**首次出现顺序**去重（图册顺序 = 层序）。
    stats 记下剔掉了什么 —— 剔行必须能被看见，否则又是"静默丢"。
    """
    own, foreign = [], 0
    for r in rows:
        if str(r["sheet"]).upper().startswith(prefix):
            own.append(r)
        else:
            foreign += 1

    labels, n_template, n_summary = [], 0, 0
    for r in own:
        lab = (r["label"] or "").strip()
        if not lab:
            continue
        if lab in SUMMARY_LABELS:
            n_summary += 1
            continue
        a = r["m2"]
        if a is not None and TEMPLATE_AREA[0] <= a <= TEMPLATE_AREA[1]:
            n_template += 1
            continue                        # 图册示例行
        if lab not in labels:
            labels.append(lab)
    stats = {"own_rows": len(own), "foreign_rows": foreign,
             "dropped_template": n_template, "dropped_summary": n_summary}
    return labels, stats


def model_floors(data_dir, name: str) -> tuple[list[int], int | None]:
    """模型里的层：优先数 `floors/floorN.json`（那才是实际交付的平面），
    没有就退回 profile 的层声明（floor_ys / floor_y_bands / floor_plans）。"""
    bdir = Path(data_dir) / "buildings" / name
    floors: list[int] = []
    fdir = bdir / "floors"
    if fdir.is_dir():
        for p in fdir.glob("floor*.json"):
            m = re.fullmatch(r"floor(-?\d+)\.json", p.name)
            if m:
                floors.append(int(m.group(1)))
    declared = None
    try:
        prof = json.loads((bdir / "profile.json").read_text(encoding="utf-8"))
    except Exception:                           # noqa: BLE001
        prof = {}
    for k in ("floor_ys", "floor_y_bands", "floor_plans"):
        v = prof.get(k)
        if v:
            declared = len(v)
            break
    return sorted(floors), declared


def diagnose(data_dir, name: str) -> dict:
    """一条结论 + 全部证据。调用方（B4）负责翻译成 Finding。

    返回 outcome ∈ {ok, drawing_more, model_more, no_model, unreadable}
    """
    bdir = Path(data_dir) / "buildings" / name
    try:
        prof = json.loads((bdir / "profile.json").read_text(encoding="utf-8"))
    except Exception as ex:                     # noqa: BLE001
        return {"outcome": "unreadable", "why": "profile.json 读不了：%s" % ex,
                "name": name}
    dxf = Path(str(prof.get("dxf") or ""))
    if not dxf.is_file():
        return {"outcome": "unreadable", "why": "源 DXF 不在：%s" % dxf, "name": name,
                "dxf": str(dxf)}

    prefix = own_prefix(name)
    try:
        rows = read_area_rows(dxf)
    except Exception as ex:                     # noqa: BLE001
        return {"outcome": "unreadable", "why": "DXF 读不了：%s: %s"
                % (type(ex).__name__, ex), "name": name, "dxf": str(dxf)}

    labels, stats = drawing_levels(rows, prefix)
    floors, declared = model_floors(data_dir, name)
    base = {"name": name, "dxf": str(dxf), "prefix": prefix,
            "labels": labels, "n_drawing": len(labels), "floors": floors,
            "declared": declared, **stats}

    if not labels:
        return {**base, "outcome": "unreadable",
                "why": "图上没有本栋图号（%s）的面积表行 —— 量不到" % prefix}
    if not floors and declared is None:
        return {**base, "outcome": "no_model", "why": "模型里既没有 floors/ 也没有层声明"}

    n_model = len(floors) if floors else int(declared or 0)
    base["n_model"] = n_model
    if len(labels) > n_model:
        return {**base, "outcome": "drawing_more"}
    if len(labels) < n_model:
        return {**base, "outcome": "model_more"}
    return {**base, "outcome": "ok"}
