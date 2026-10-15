# -*- coding: utf-8 -*-
"""构件稳定 ID —— 防「叠加层脱锚」的地基（规范见 规范/构件稳定ID规则-v1.md）。

病根（实测）：现有 floors/floor*.json 里，墙的 id 是 **位置型** 的 `w<层>-<序号>`（如 `w0-4`），
门 / 柱大多**根本没有 id**。位置型 id 一旦在序号前面插入或删掉一个构件，**其后所有 id 整体平移**
—— 界面上标注还在、却挂到了隔壁墙上，**症状静默**。

本模块的做法：id 由构件**自身的内容**算出，与它在列表里的位置无关。
    id = <campus>:<building>:<kind>:<h16>
    h16 = sha256( kind | 规范序列化的各身份字段 ) 的前 16 个十六进制字符
身份字段里**不含** `id` 本身、不含序号、不含任何位置量；浮点按 QUANT 量化后再入哈希
⇒ 同一次建模重跑（逐字节一致）ID 必然相同；构件真的变了（超过 QUANT）ID 才变，
   **变了的地方由 resolve() 报出条数**，绝不静默重挂。

★ 已知取舍（写在这里，别忘）：
  · 墙的 thickness/height 进身份 ⇒ 厚度改一点点，该墙 **脱锚**（报数、要人重锚）。
    这是**有意的**：宁可报「这条要重看」，也不静默挂到「看着像同一堵」的墙上。
  · QUANT=1e-4 m（0.1 mm）是**容差**，不是显示精度。超过它才算「变了」。
  · 房间的身份暂取 (楼层, number)，**number 自身跨重跑的稳定性本轮未核**（见规范「未核项」）。
"""
from __future__ import annotations

import hashlib
import json
import os

QUANT = 1e-4  # 0.1 mm

# 各构件的**身份字段**（顺序即序列化顺序，改顺序会改 ID ⇒ 规范里已写「不许随手改」）
IDENT_FIELDS = {
    "wall":     ("type", "thickness", "height", "poly", "holes"),
    "door":     ("x", "y", "w", "h", "outer", "horiz"),
    "window":   ("x", "y", "w", "h", "sill", "horiz"),
    "column":   ("x", "y", "w", "d"),
    "elevator": ("x0", "y0", "x1", "y1"),
    "stairwell": ("x0", "x1", "yBot", "yTop", "steps", "pitch", "type", "axis"),
}


def _num(v):
    """浮点量化后转固定串；-0.0 归一成 0.0（否则会造出两个只在符号上不同的 ID）。"""
    f = round(float(v) / QUANT) * QUANT
    if f == 0:
        f = 0.0
    return "%.4f" % f


def canon(v):
    """把任意值写成**确定**的字节串。同值必同串、异值必异串；不依赖 dict 插入序。"""
    if v is None:
        return "~"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return str(int(v))
    if isinstance(v, float):
        return _num(v)
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(canon(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join("%s:%s" % (k, canon(v[k])) for k in sorted(v)) + "}"
    raise TypeError("canon 不支持的类型: %r" % type(v))


def component_id(campus: str, building: str, kind: str, obj: dict) -> str:
    """单件 → 稳定 ID。缺身份字段按 None 处理（None 也是身份的一部分）。"""
    body = "|".join(canon(obj.get(f)) for f in IDENT_FIELDS[kind])
    payload = ("%s|%s" % (kind, body)).encode("utf-8")
    return "%s:%s:%s:%s" % (campus, building, kind, hashlib.sha256(payload).hexdigest()[:16])


def room_id(campus: str, building: str, room: dict) -> str:
    """房间：优先用图纸 / 台账的房间号（语义键）；无号则退回内容哈希。"""
    num = (room.get("number") or "").strip()
    if num:
        payload = ("room|%s" % num).encode("utf-8")
    else:
        payload = canon(["room", room.get("floor"), room.get("poly") or room.get("boundary"),
                         room.get("purpose")]).encode("utf-8")
    return "%s:%s:room:%s" % (campus, building, hashlib.sha256(payload).hexdigest()[:16])


def legacy_id(kind: str, floor: int, index: int) -> str:
    """复刻现有产物里的**位置型** id（`w0-4` / `win0-0`…），只用于对照演示它不稳定。"""
    prefix = {"wall": "w", "window": "win", "door": "d", "column": "c"}.get(kind, kind)
    return "%s%s-%s" % (prefix, floor, index)


# 楼层 JSON 里「件列表」的键 → 规范 kind（键名与产物一致）
FLOOR_KEYS = (("walls", "wall"), ("doors", "door"), ("windows", "window"), ("columns", "column"))


def ids_of_floor(campus: str, building: str, floor_obj: dict) -> dict:
    """一层 → {stable_id: {...元信息}}；同时给出位置型 id 供对照。"""
    F = floor_obj.get("floor")
    out = {}
    for key, kind in FLOOR_KEYS:
        for i, obj in enumerate(floor_obj.get(key) or []):
            if not isinstance(obj, dict):
                continue
            sid = component_id(campus, building, kind, obj)
            out[sid] = {"kind": kind, "floor": F, "idx": i, "legacy": legacy_id(kind, F, i)}
    for room in floor_obj.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        sid = room_id(campus, building, room)
        out[sid] = {"kind": "room", "floor": F, "idx": None,
                    "legacy": room.get("id")}
    return out


def ids_of_building(campus: str, building: str, floors_dir: str) -> dict:
    """整栋 → {stable_id: {...}}。只读 floor*.json，按文件名排序保证确定性。"""
    merged = {}
    for fn in sorted(os.listdir(floors_dir)):
        if not (fn.startswith("floor") and fn.endswith(".json")):
            continue
        with open(os.path.join(floors_dir, fn), encoding="utf-8") as f:
            merged.update(ids_of_floor(campus, building, json.load(f)))
    return merged


def resolve(stored: dict, current: dict) -> dict:
    """±锚点解析（集合口径）：把「上一版存下的 id」拿到「这一版模型」上找。

    ★ 只对**内容型 id**成立（此时 id 就等于内容身份，集合差即脱锚）。
      **位置型 id 用它必瞎** —— 见 resolve_mapped 的说明。
    """
    s, c = set(stored), set(current)
    miss = sorted(s - c)
    add = sorted(c - s)
    return {
        "stored": len(s),
        "current": len(c),
        "resolved": len(s & c),
        "missing": len(miss),
        "added": len(add),
        "missing_sample": miss[:5],
        "added_sample": add[:5],
    }


def resolve_mapped(stored: dict, current: dict) -> dict:
    """±锚点解析（**对齐口径**）—— stored/current 是 {id: 内容键}。

    ★ 为什么必须有这一版：位置型 id（`w0-4`）在一个构件前面插一件后，**id 集合几乎不变**
      （只是末尾多一个），但**同一个 `w0-4` 已经指到隔壁那堵墙**了 —— 集合差**完全看不见**这种重挂。
      所以判「有没有脱锚」只能**按 id 对齐、再比内容**，不能只比 id 集合。
    返回：resolved（同 id 同内容）/ reassigned（同 id 内容变了=**静默重挂**）/
          gone（id 没了）/ added（新 id）；**脱锚条数 = reassigned + gone**。
    """
    reassigned, gone, resolved = [], [], 0
    for k, v in stored.items():
        if k not in current:
            gone.append(k)
        elif current[k] != v:
            reassigned.append(k)
        else:
            resolved += 1
    added = sorted(k for k in current if k not in stored)
    return {
        "stored": len(stored), "current": len(current),
        "resolved": resolved,
        "reassigned": len(reassigned), "gone": len(gone), "added": len(added),
        "detached": len(reassigned) + len(gone),          # ★ 脱锚条数
        "reassigned_sample": sorted(reassigned)[:5],
    }
