# -*- coding: utf-8 -*-
"""人工标注数据域：把「人指出的问题」变成能聚合的数。

## 这个域要连上的是全仓唯一一处真正断掉的链

`annotate_defects.py`（8150 标注台）从 2026-09-14 起就在往 `_qa/annotations.json`
里写标注，30 条、10 栋楼。**而它全仓没有第二个读者。**

后果不是「少了点功能」，是用户第一句话里的那半句回答不了：
> 「我们怎么针对某个 cad 图进行修改，指出问题，然后**看是不是通用问题**」

⇒ 「是不是通用问题」= 同一个毛病在 **N 栋 M 层**出现。
   这需要**聚合**，而聚合需要有人读那个文件。本域就是那个读者。

## 口径：沿用旧格式，一个字段都不加

现有记录形状（实测 2026-10-02，30 条）：

    {"building": "c018", "f": "0", "kind": "src", "type": "wall_wrong",
     "note": "", "box": {"x0":..,"y0":..,"x1":..,"y1":..}, "ts": "2026-09-11T16:06:21"}

★ `f` 是**字符串**不是整数（旧写口就这么存的）—— 归一化成 int 会让
  旧 30 条的 sha256 全变，N6 当场红。**保持字符串**。

★ `box` 是 **0..1 图幅比例**，不是像素、不是米。
  它与 `defects.json` 的 `pos`（米制工程坐标 x∈[−66.95,221.73]）**不是一回事**
  ⇒ 本域**只聚合计数，绝不把两者画到同一张图上**（见 `summary()` 的 `why_not_merged`）。

## 不吞异常

旧的 `load_ann()` 把「文件坏了」和「文件是空的」都变成 `[]`。
这两件事的下一步动作**相反**（一个是「还没人标过」，一个是「标过的全丢了，快查备份」），
屏幕上却都是「0 条」⇒ 本域坏文件一律抛，由路由翻成 5xx 并带上原因。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

# 与 annotate_defects.py:TYPES 逐字一致（key 进 JSON，label 给人看）。
# ★ 这两份清单必须**成对**——加了一边没加另一边，新类型会被拒或被静默丢掉。
#   本仓铁律 043：两份清单成对时，兜底会把「漏了一条」变成「安静地走默认」。
TYPES: list[tuple[str, str]] = [
    ("wall_missing", "墙缺（图里有、模型没有）"),
    ("wall_blob", "墙糊了（多面墙粘成一坨实心块）"),
    ("wall_wrong", "墙位置/形状不对"),
    ("wall_extra", "墙多（模型有、图里没有）"),
    ("floor_misalign", "楼层错位 / 悬空 / 穿模"),
    ("outline_wrong", "整栋轮廓不对"),
    ("door", "门不对（缺 / 多 / 位置）"),
    ("window", "窗不对（缺 / 多 / 位置）"),
    ("stair", "楼梯不对（缺 / 位置 / 形状）"),
    ("other", "其他（在备注里写）"),
]
TYPE_KEYS = tuple(k for k, _ in TYPES)
KINDS = ("src", "recog")           # 与左屏那两个模式一一对应，不新增维度
TYPE_LABEL = dict(TYPES)


class BadStore(RuntimeError):
    """标注库在盘上但读不出来。★ 消息带上路径与原因，别退化成空表。"""


def store_path(cfg) -> Path:
    return cfg.root / "_qa" / "annotations.json"


def load(cfg) -> list[dict[str, Any]]:
    p = store_path(cfg)
    if not p.is_file():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                    # noqa: BLE001
        raise BadStore(
            "标注库读不出来（%s）：%s。**不要**当成「还没人标过」处理 —— "
            "去 _qa/ 找 .bak" % (p, type(exc).__name__)) from exc
    if not isinstance(d, list):
        raise BadStore("标注库应当是一个 JSON 数组，实际是 %s（%s）" % (type(d).__name__, p))
    return d


def _norm(rec: dict[str, Any]) -> dict[str, Any]:
    """校验并归一化一条新标注。**返回新字典，不改入参**（本仓不可变约定）。"""
    if not isinstance(rec, dict):
        raise ValueError("一条标注应当是个对象")

    b = str(rec.get("building") or "").strip()
    if not b:
        raise ValueError("缺 building")
    f = str(rec.get("f") if rec.get("f") is not None else "0").strip()     # ★ 字符串
    kind = str(rec.get("kind") or "").strip()
    if kind not in KINDS:
        raise ValueError("kind 只能是 %s，收到 %r" % ("/".join(KINDS), kind))
    typ = str(rec.get("type") or "").strip()
    if typ not in TYPE_KEYS:
        # ★ 出声列出允许值 —— 静默改成 "other" 会让「类型写错了」看起来像「标了一条 other」。
        raise ValueError("type 只能是 %s，收到 %r" % ("/".join(TYPE_KEYS), typ))

    box = rec.get("box") or {}
    try:
        x0, y0 = float(box["x0"]), float(box["y0"])
        x1, y1 = float(box["x1"]), float(box["y1"])
    except Exception as exc:                    # noqa: BLE001
        raise ValueError("box 要 {x0,y0,x1,y1} 四个数") from exc
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    for v in (x0, y0, x1, y1):
        if not (0.0 <= v <= 1.0):
            # ★ 出界不许夹到 [0,1]：夹了以后「框到画布外面去了」就变成一个合法的小框。
            raise ValueError("box 是 0..1 的图幅比例，越界：%r" % (v,))
    if x1 - x0 < 1e-6 or y1 - y0 < 1e-6:
        raise ValueError("框的宽或高是 0 —— 拖一下没拖动，别存成一条空标注")

    return {
        "building": b,
        "f": f,
        "kind": kind,
        "type": typ,
        "note": str(rec.get("note") or ""),
        "box": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "ts": str(rec.get("ts") or datetime.now().isoformat(timespec="seconds")),
    }


def append(cfg, rec: dict[str, Any]) -> dict[str, Any]:
    """追加一条。原子写（临时文件 + `os.replace`），与 `annotate_defects.save_ann`
    同一个套路、同一个 `indent=2` —— 于是**旧 30 条重写后逐条不变**（N6）。

    ★ 沿用**同一个文件、同一种形状**，不另开一个新库：
      两个库意味着「我这页看到的和 8150 看到的不是同一批」，
      而那种分叉在屏幕上是「那边少标了几条」，看着像人偷懒。
    """
    item = _norm(rec)
    items = load(cfg) + [item]

    p = store_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)                      # 原子替换，写一半断电不会毁掉已有标注
    return item


# ────────────────────────────────────────────────────────────────
# 聚合：「是不是通用问题」
# ────────────────────────────────────────────────────────────────

def summary(cfg) -> dict[str, Any]:
    """两个轴**各自聚合、并排摆**，绝不相加。

    轴 A（人圈的，flag）：`_qa/annotations.json`  —— 键 `type` × `kind`
    轴 B（机器找的，code）：`_qa/defects.json`     —— 键 `code` × `group`

    ★ 两轴的坐标系不同（0..1 图幅比例 vs 米制工程坐标），所以这一版
      **不做「机器框叠到层图上」**，也不把两个数加成「共 N 个问题」。
      那句话印在 `why_not_merged` 里，页面上必须显示。
    """
    ann = load(cfg)
    by_type: dict[str, dict[str, Any]] = {}
    for r in ann:
        k = str(r.get("type") or "?")
        s = by_type.setdefault(k, {"type": k, "label": TYPE_LABEL.get(k, k),
                                   "n": 0, "buildings": set(), "floors": set(),
                                   "kinds": {}})
        s["n"] += 1
        s["buildings"].add(str(r.get("building")))
        s["floors"].add("%s:floor%s" % (r.get("building"), r.get("f")))
        kk = str(r.get("kind") or "?")
        s["kinds"][kk] = s["kinds"].get(kk, 0) + 1

    rows = []
    for s in by_type.values():
        rows.append({
            "type": s["type"], "label": s["label"], "n": s["n"],
            "n_buildings": len(s["buildings"]),
            "n_floors": len(s["floors"]),
            "kinds": s["kinds"],
            # ★ 「通用」的判据就这一句：**同一毛病出现在几栋楼上**。
            #   1 栋是「这栋的偶发」，N 栋才是「通用」—— 但门槛由人定，这里只给数。
            "common_guess": "通用" if len(s["buildings"]) >= 3 else
                            ("苗头" if len(s["buildings"]) == 2 else "孤例"),
        })
    rows.sort(key=lambda r: (-r["n_buildings"], -r["n"]))

    dep = cfg.root / "_qa" / "defects.json"
    code_rows, code_n = [], None
    if dep.is_file():
        try:
            d = json.loads(dep.read_text(encoding="utf-8"))
            if isinstance(d, list):
                code_n = len(d)
                g: dict[str, dict[str, Any]] = {}
                for r in d:
                    k = str(r.get("code") or "?")
                    s = g.setdefault(k, {"code": k, "group": r.get("group"), "n": 0,
                                         "buildings": set(), "sev": {}})
                    s["n"] += 1
                    s["buildings"].add(str(r.get("building")))
                    sv = str(r.get("sev") or "?")
                    s["sev"][sv] = s["sev"].get(sv, 0) + 1
                for s in g.values():
                    s["n_buildings"] = len(s["buildings"])
                    del s["buildings"]
                    code_rows.append(s)
                code_rows.sort(key=lambda r: (-r["n_buildings"], -r["n"]))
        except Exception as exc:                # noqa: BLE001
            code_rows, code_n = [], "读不出来：%s" % type(exc).__name__

    return {
        "axis_a": {
            "name": "人圈的（flag 轴）",
            "source": str(store_path(cfg)),
            "n": len(ann),
            "n_buildings": len({str(r.get("building")) for r in ann}),
            "rows": rows,
            "types": [{"key": k, "label": v} for k, v in TYPES],
        },
        "axis_b": {
            "name": "机器找的（code 轴）",
            "source": str(dep),
            "n": code_n,
            "rows": code_rows,
        },
        "why_not_merged": (
            "**两个轴不许相加**：annotations 的 box 是 0..1 图幅比例，"
            "defects 的 pos 是米制工程坐标（x∈[−66.95,221.73]）—— "
            "两者之间还差一个「图幅↔工程坐标」变换，而那正是同一类锚点问题。"
            "所以这一版只把两个轴**并排摆**，不做「机器框叠到层图上」。"),
    }


def by_building(cfg, name: str, floor: str | None = None) -> list[dict[str, Any]]:
    out = [r for r in load(cfg) if str(r.get("building")) == name]
    if floor is not None:
        out = [r for r in out if str(r.get("f")) == str(floor)]
    return out
