# -*- coding: utf-8 -*-
"""_door_boxes 与旧内联代码的等价性单测（只读）。

理化楼（door_by_points）路径的门洞盒已验收，抽成共用 helper 后必须逐位不变。
本探针把「旧内联逻辑」原样复制一份，在随机门 + 真实轮廓上对比 helper 输出：
外门判定 d["outer"]、盒 d["box"].bounds 全部必须一致（浮点按 1e-9 容差）。
detect_doors 路径无旧实现可比，只打印几条样例直觉检查（外门盒外缘贴轮廓）。

用法: python _probe_doorbox_equiv.py
"""
import sys, random
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

from shapely.geometry import Polygon, box, Point
from shapely.ops import nearest_points
from backend.recognizer import floor as FL

# 一个 40x20 的矩形楼 + 从轮廓内缩出的外墙厚
OUTLINE = Polygon([(0, 0), (40, 0), (40, 20), (0, 20)])
S = {"outer_wall_t": 0.30, "inner_wall_t": 0.24}


class P:
    outer_wall_t = 0.24


def old_way(door_candidates, outline, p, S):
    """2026-09-10 之前 floor.py 里内联的那段（逐字复制，只把 door_by_points 门去掉）。"""
    outer_wt = getattr(p, "outer_wall_t", S["outer_wall_t"])
    depth = max(outer_wt, S["inner_wall_t"]) + 0.05
    for d in door_candidates:
        c = Point(d["x"], d["y"])
        raw_bbox = box(d["bx0"], d["by0"], d["bx1"], d["by1"])
        d["outer"] = raw_bbox.distance(outline.exterior) < 0.25
        half = d["w"] / 2
        cx, cy = d["x"], d["y"]
        if d["outer"]:
            facade = nearest_points(outline.boundary, c)[0]
            vx, vy = facade.x - c.x, facade.y - c.y
            dist = (vx * vx + vy * vy) ** 0.5
            if dist > 1e-6:
                k = (dist - depth / 2) / dist
                cx, cy = c.x + vx * k, c.y + vy * k
        if d["horiz"]:
            d["box"] = box(cx - half, cy - depth / 2, cx + half, cy + depth / 2)
        else:
            d["box"] = box(cx - depth / 2, cy - half, cx + depth / 2, cy + half)
        d["bx0"], d["by0"], d["bx1"], d["by1"] = d["box"].bounds


random.seed(20260910)
cands = []
for _ in range(4000):
    w = round(random.uniform(0.7, 2.4), 3)
    horiz = random.random() < 0.5
    # 一半贴边（外门候选），一半散在内部
    if random.random() < 0.5:
        if horiz:
            x = random.uniform(0.5, 39.5); y = random.choice([0.0, 20.0]) + random.uniform(-0.3, 0.3)
        else:
            x = random.choice([0.0, 40.0]) + random.uniform(-0.3, 0.3); y = random.uniform(0.5, 19.5)
    else:
        x = random.uniform(2.0, 38.0); y = random.uniform(2.0, 18.0)
    hw = w / 2 if horiz else 0.1
    hh = 0.1 if horiz else w / 2
    cands.append({
        "x": round(x, 3), "y": round(y, 3), "w": w, "horiz": horiz,
        "bx0": round(x - hw, 3), "by0": round(y - hh, 3),
        "bx1": round(x + hw, 3), "by1": round(y + hh, 3),
    })

import copy
A = copy.deepcopy(cands)
B = copy.deepcopy(cands)
old_way(A, OUTLINE, P(), S)
FL._door_boxes(B, OUTLINE, P(), S)

bad = 0
for i, (a, b) in enumerate(zip(A, B)):
    if a["outer"] != b["outer"]:
        bad += 1
        if bad <= 3:
            print("  外门判定不符 #%d: old=%s new=%s" % (i, a["outer"], b["outer"]))
        continue
    da = [a["bx0"], a["by0"], a["bx1"], a["by1"]]
    db = [b["bx0"], b["by0"], b["bx1"], b["by1"]]
    if any(abs(u - v) > 1e-9 for u, v in zip(da, db)):
        bad += 1
        if bad <= 3:
            print("  盒不符 #%d: old=%s new=%s" % (i, da, db))

n_out = sum(1 for b in B if b["outer"])
print("理化楼路径等价性: %d 例, 外门 %d, 不符 %d -> %s"
      % (len(A), n_out, bad, "PASS" if bad == 0 else "FAIL"))

# detect_doors 路径直觉检查：门心贴边的门，盒外缘应贴到轮廓上（不相交外轮廓之外）
D = [
    {"x": 20.0, "y": 0.30, "w": 1.2, "horiz": True},     # 南墙外门（门心内移 0.30）
    {"x": 20.0, "y": 10.0, "w": 1.2, "horiz": True},     # 内部内门
    {"x": 0.30, "y": 10.0, "w": 1.2, "horiz": False},    # 西墙外门
    {"x": 20.0, "y": 19.70, "w": 1.2, "horiz": True},    # 北墙外门
]
FL._door_boxes(D, OUTLINE, P(), S)
print("\ndetect_doors 路径样例（外墙厚 0.24, depth=0.29）:")
for d in D:
    print("  (%5.2f,%5.2f) w=%.1f %s -> outer=%-5s 盒 y/x 跨度 %s"
          % (d["x"], d["y"], d["w"], "横" if d["horiz"] else "竖", d["outer"],
             "%.3f~%.3f" % (d["by0"], d["by1"]) if d["horiz"] else "%.3f~%.3f" % (d["bx0"], d["bx1"])))
