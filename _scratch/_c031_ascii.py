# -*- coding: utf-8 -*-
"""c031 floor0 墙 ASCII 俯视 (R8 目视用, 纯文本)。只读。"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon

fl = json.load(open("data/buildings/c031/floors/floor0.json", encoding="utf-8"))
wallpolys = []
for w in fl["walls"]:
    p = Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4]).buffer(0)
    wallpolys.append((w["type"], p))

xs0, ys0, xs1, ys1 = 1e9, 1e9, -1e9, -1e9
for _, p in wallpolys:
    b = p.bounds
    xs0, ys0 = min(xs0, b[0]), min(ys0, b[1])
    xs1, ys1 = max(xs1, b[2]), max(ys1, b[3])

CELL = 0.5  # 每格 0.5m
W = int((xs1 - xs0) / CELL) + 1
H = int((ys1 - ys0) / CELL) + 1
grid = [[" " for _ in range(W)] for _ in range(H)]

def sample(x, y):
    pt = Polygon([(x, y), (x + CELL * 0.5, y), (x + CELL * 0.5, y + CELL * 0.5), (x, y + CELL * 0.5)])
    for tp, p in wallpolys:
        if p.intersects(pt):
            return "#" if tp == "outer" else "+"
    return " "

for iy in range(H):
    y = ys0 + iy * CELL
    for ix in range(W):
        x = xs0 + ix * CELL
        grid[iy][ix] = sample(x, y)

# 每 2 行取 1 行压缩
for iy in range(0, H, 1):
    print("".join(grid[iy]))
