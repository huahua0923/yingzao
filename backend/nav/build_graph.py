# -*- coding: utf-8 -*-
"""空间邻接图：房间=节点，门=边（Topologic 的 Cell/共享 Face 思路落地）。

对每个门，向墙两侧采样，判定归属：
  room      → 该房间
  stairwell → 楼梯井（竖向交通）
  outside   → 室外（外墙门）
  corridor  → 走廊/门厅（轮廓内但未登记为房间的空间，暂按每层一个走廊节点）

输出 adjacency.json：nodes / edges，供室内导航 A* 使用。
"""
import json
import sys
from shapely.geometry import Point, Polygon

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOMS = r"D:\gym3d\data\rooms.json"
FLOORS_DIR = r"D:\gym3d\data\floors"
OUT = r"D:\gym3d\data\adjacency.json"

SAMPLE_OFF = (0.6, 0.9, 1.3)   # 门中心向两侧偏移采样距离(m)：越过门洞凹口(~0.25m)进入房间

rooms = json.load(open(ROOMS, encoding="utf-8"))
room_by_id = {}
for r in rooms:
    b = r["boundary"]
    if len(b) < 3:
        continue
    room_by_id[(r["floor"], r["id"])] = {
        "poly": Polygon(b),
        "number": r.get("number") or "",
        "purpose": r.get("purpose") or "",
        "name": r.get("name") or "",
    }

doors_by_floor, stairwells_by_floor, outline_by_floor = {}, {}, {}
for F in range(5):
    d = json.load(open(f"{FLOORS_DIR}/floor{F}.json", encoding="utf-8"))
    doors_by_floor[F] = d.get("doors", [])
    stairwells_by_floor[F] = d.get("stairwells", [])
    outline_by_floor[F] = Polygon(d["outline"])


def classify(F, x, y):
    """点归属：('room',id) / ('stairwell',None) / ('outside',None) / ('corridor',None)。"""
    p = Point(x, y)
    for (f, rid), info in room_by_id.items():
        if f == F and info["poly"].contains(p):
            return ("room", rid)
    for s in stairwells_by_floor[F]:
        if s["x0"] <= x <= s["x1"] and s["yBot"] <= y <= s["yTop"]:
            return ("stairwell", None)
    if not outline_by_floor[F].contains(p):
        return ("outside", None)
    return ("corridor", None)


def side_kind(F, x, y, horiz, sign):
    """门某侧归属：依次加大偏移找房间，找不到则返回最后的非房间分类。"""
    last = None
    for off in SAMPLE_OFF:
        px = x + (0 if horiz else sign * off)
        py = y + (sign * off if horiz else 0)
        r = classify(F, px, py)
        if r[0] == "room":
            return r
        last = r
    return last


def node_key(kind, rid, F):
    if kind == "room":
        return f"f{F}-r{rid}"
    return f"f{F}-{kind}"


nodes, edges = {}, {}


def add_node(kind, rid, F):
    k = node_key(kind, rid, F)
    if k in nodes:
        return k
    nodes[k] = {"id": k, "type": kind, "floor": F}
    if kind == "room":
        info = room_by_id[(F, rid)]
        nodes[k].update({
            "roomId": rid, "number": info["number"],
            "purpose": info["purpose"], "name": info["name"],
        })
    return k


def add_edge(ka, kb, F, kind, extra=None):
    if ka == kb:
        return  # 自环（同一走廊节点两侧都判为走廊的门）对寻路无意义，丢弃
    key = tuple(sorted([ka, kb]))
    if key not in edges:
        edges[key] = {"from": key[0], "to": key[1], "type": kind, "floor": F, "doors": []}
    e = edges[key]
    if extra:
        e.setdefault("via", []).extend(extra)
    return e


for F in range(5):
    for d in doors_by_floor[F]:
        x, y, horiz = d["x"], d["y"], d["horiz"]
        a = side_kind(F, x, y, horiz, +1)
        b = side_kind(F, x, y, horiz, -1)
        ka = add_node(a[0], a[1], F)
        kb = add_node(b[0], b[1], F)
        e = add_edge(ka, kb, F, "door")
        if e:
            e["doors"].append({"x": d["x"], "y": d["y"], "w": d["w"], "horiz": horiz})

# 竖向交通：楼梯井跨层 → 走廊(f) ↔ 走廊(f+1)（楼梯井为开放式，归属走廊空间）
def stair_x(F):
    return [((s["x0"] + s["x1"]) / 2, s["x0"], s["x1"]) for s in stairwells_by_floor[F]]


for F in range(4):
    for cx, x0, x1 in stair_x(F):
        for cx2, x02, x12 in stair_x(F + 1):
            if min(x1, x12) - max(x0, x02) > 1.0:  # 同一竖向井(x 重叠)
                add_edge(node_key("corridor", None, F), node_key("corridor", None, F + 1),
                         F, "stair", extra=[{"x": round(cx, 1), "from": F, "to": F + 1}])
                break

model = {
    "nodes": sorted(nodes.values(), key=lambda n: (n["floor"], n["id"])),
    "edges": list(edges.values()),
}
json.dump(model, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

from collections import Counter
nt = Counter(n["type"] for n in model["nodes"])
et = Counter(e["type"] for e in model["edges"])
print(f"节点={len(model['nodes'])} {dict(nt)}")
print(f"边={len(model['edges'])}  门连接={sum(len(e['doors']) for e in model['edges'])}")
print("边类型:", dict(et))
print("已存", OUT)
