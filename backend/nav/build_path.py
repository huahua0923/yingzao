# -*- coding: utf-8 -*-
"""几何行走路径：从 floor JSON 生成占用网格，A* 求两房间间最短可通行折线。

与 build_graph.py（拓扑图）互补：拓扑图给出「房间→门→走廊」的连通关系，
这里给出「人实际走的折线」（栅格 A* 穿门洞、走走廊）。

同层：直接 A*。跨层：经楼梯井过渡（楼梯井是连续竖向空间，同一井贯通各层，
坐标逐层几乎一致，故楼层间距任意都能直穿，无需在中间层重新寻路）。

核心函数 compute_path(src, dst) 返回 3D 折线 [x, y, z]（z = 楼层 × 层高），
供 serve_rooms.py 的 /api/path 端点与 CLI 共用。

CLI 用法:
  python build_path.py --from 05-01-01 --to 05-03-16 [--out path.json] [--png path.png]
"""
import argparse
import heapq
import json
import os
import sys

import numpy as np
from PIL import Image
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data"))
RES = 0.1      # 栅格分辨率（米）
FLOOR_H = 4.2  # 层高（米）


def load_floor(F):
    return json.load(open(os.path.join(DATA, "floors", f"floor{F}.json"), encoding="utf-8"))


def load_rooms():
    return json.load(open(os.path.join(DATA, "rooms.json"), encoding="utf-8"))


# ---------- 占用网格 ----------

def build_grid(floor):
    """floor JSON → (grid, meta)。grid=True 可通行。meta 含 world↔grid 变换。"""
    outline = Polygon(floor["outline"])
    walls = unary_union([Polygon(w["poly"]) for w in floor["walls"] if w["type"] != "parapet"])
    cols = unary_union([box(c["x"] - c["w"] / 2, c["y"] - c["d"] / 2,
                            c["x"] + c["w"] / 2, c["y"] + c["d"] / 2)
                        for c in floor.get("columns", [])])
    walkable = outline.difference(walls)
    if not cols.is_empty:
        walkable = walkable.difference(cols)

    minx, miny, maxx, maxy = outline.bounds
    nx = int((maxx - minx) / RES) + 1
    ny = int((maxy - miny) / RES) + 1
    xs = minx + (np.arange(nx) + 0.5) * RES
    ys = miny + (np.arange(ny) + 0.5) * RES
    X, Y = np.meshgrid(xs, ys)
    from shapely import contains_xy
    grid = contains_xy(walkable, X, Y)  # shape (ny, nx)，grid[i,j] ↔ (xs[j], ys[i])

    meta = {"minx": minx, "miny": miny, "res": RES, "nx": nx, "ny": ny}
    return grid, meta


def world_to_grid(x, y, meta):
    j = int((x - meta["minx"]) / meta["res"])
    i = int((y - meta["miny"]) / meta["res"])
    return i, j


def grid_to_world(i, j, meta):
    return meta["minx"] + (j + 0.5) * meta["res"], meta["miny"] + (i + 0.5) * meta["res"]


# ---------- A* ----------

def astar(grid, start, goal):
    """8 连通 A*（禁止对角穿墙）。返回 [(i,j), ...] 或 None。"""
    H, W = grid.shape
    start, goal = tuple(start), tuple(goal)
    if not (grid[start] and grid[goal]):
        return None

    def h(p):
        di, dj = abs(p[0] - goal[0]), abs(p[1] - goal[1])
        return max(di, dj) + 0.414 * min(di, dj)  # octile 距离

    open_set = [(0.0, start)]
    g = {start: 0.0}
    came = {}
    while open_set:
        _, cur = heapq.heappop(open_set)
        if cur == goal:
            break
        gi, gj = cur
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ni, nj = gi + di, gj + dj
                if not (0 <= ni < H and 0 <= nj < W and grid[ni, nj]):
                    continue
                if di != 0 and dj != 0 and not (grid[gi + di, gj] and grid[gi, gj + dj]):
                    continue  # 对角需两个正交邻格都可行
                cost = 1.414 if di != 0 and dj != 0 else 1.0
                t = g[cur] + cost
                if t < g.get((ni, nj), float("inf")):
                    g[(ni, nj)] = t
                    came[(ni, nj)] = cur
                    heapq.heappush(open_set, (t + h((ni, nj)), (ni, nj)))
    if goal not in came and goal != start:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(came[path[-1]])
    return path[::-1]


def simplify(path):
    """去共线点，返回折线折点（栅格坐标）。"""
    if len(path) < 3:
        return path
    out = [path[0]]
    for a, b, c in zip(path, path[1:], path[2:]):
        if (b[0] - a[0]) * (c[1] - b[1]) != (b[1] - a[1]) * (c[0] - b[0]):
            out.append(b)
    out.append(path[-1])
    return out


# ---------- 房间 / 楼梯井 ----------

def find_room(rooms, number):
    """按房间号搜索所有楼层，返回 (floor, cx, cy, id)。找不到抛 ValueError。"""
    for r in rooms:
        if r.get("number") == number:
            c = Polygon(r["boundary"]).centroid
            return r["floor"], c.x, c.y, r["id"]
    raise ValueError(f"未找到房间 {number}")


def stairwell_centers(floor):
    """每个楼梯井在〔该楼层〕的中心 (cx, cy)，顺序稳定（双分/东双跑/西双跑）。"""
    return [((s["x0"] + s["x1"]) / 2, (s["yBot"] + s["yTop"]) / 2)
            for s in floor.get("stairwells", [])]


def plan_on_floor(floor_json, sx, sy, gx, gy):
    """同层 A*，返回 (折线世界坐标, grid, meta)；失败返回 (None, grid, meta)。"""
    grid, meta = build_grid(floor_json)
    start = world_to_grid(sx, sy, meta)
    goal = world_to_grid(gx, gy, meta)
    p = astar(grid, start, goal)
    if p is None:
        return None, grid, meta
    p = simplify(p)
    return [grid_to_world(i, j, meta) for i, j in p], grid, meta


def path_length(world):
    return sum(np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(world, world[1:]))


# ---------- 核心：计算路径 ----------

def compute_path(src, dst):
    """两房间号 → 3D 折线。

    返回 {"from", "to", "length_m", "path": [[x,y,z], ...],
          "src": {floor,id}, "dst": {floor,id}, "stairwell": int|None}。
    z = 楼层 × FLOOR_H；跨层垂直段逐层插落点。找不到房间/路径抛 ValueError。
    """
    rooms = load_rooms()
    sf, sx, sy, sid = find_room(rooms, src)
    df, gx, gy, gid = find_room(rooms, dst)

    if sf == df:
        world, _, _ = plan_on_floor(load_floor(sf), sx, sy, gx, gy)
        if world is None:
            raise ValueError(f"同层无路径 {src} -> {dst}")
        length = path_length(world)
        path3d = [[round(x, 2), round(y, 2), round(sf * FLOOR_H, 2)] for x, y in world]
        return {"from": src, "to": dst, "length_m": round(length, 2), "path": path3d,
                "src": {"floor": sf, "id": sid}, "dst": {"floor": df, "id": gid},
                "stairwell": None}

    src_floor, dst_floor = load_floor(sf), load_floor(df)
    sc = stairwell_centers(src_floor)
    dc = stairwell_centers(dst_floor)
    best = None
    for k in range(min(len(sc), len(dc))):
        sxc, syc = sc[k]
        dxc, dyc = dc[k]
        seg1, _, _ = plan_on_floor(src_floor, sx, sy, sxc, syc)
        seg2, _, _ = plan_on_floor(dst_floor, dxc, dyc, gx, gy)
        if seg1 is None or seg2 is None:
            continue
        total = path_length(seg1) + path_length(seg2) + abs(df - sf) * FLOOR_H
        if best is None or total < best[0]:
            best = (total, k, seg1, seg2, sxc, syc, dxc, dyc)
    if best is None:
        raise ValueError(f"跨层无路径 {src} -> {dst}（楼梯井不可达？）")

    total, k, seg1, seg2, sxc, syc, dxc, dyc = best
    path3d = [[round(x, 2), round(y, 2), round(sf * FLOOR_H, 2)] for x, y in seg1]
    for f in range(sf + 1, df + 1):  # 楼梯井逐层落点（井中心微漂，线性插值）
        t = (f - sf) / (df - sf)
        path3d.append([round(sxc + (dxc - sxc) * t, 2),
                       round(syc + (dyc - syc) * t, 2),
                       round(f * FLOOR_H, 2)])
    path3d += [[round(x, 2), round(y, 2), round(df * FLOOR_H, 2)] for x, y in seg2]
    return {"from": src, "to": dst, "length_m": round(total, 2), "path": path3d,
            "src": {"floor": sf, "id": sid}, "dst": {"floor": df, "id": gid},
            "stairwell": k}


def render_png(grid, meta, path_pts, start, goal, out):
    """白=可通行 黑=障碍，路径红色叠加，起绿终蓝。"""
    img = (grid.astype(np.uint8) * 255)[::-1]
    rgb = np.stack([img, img, img], axis=-1)
    for x, y in path_pts:
        i, j = world_to_grid(x, y, meta)
        rgb[meta["ny"] - 1 - i, j] = [255, 60, 60]
    rgb[meta["ny"] - 1 - start[0], start[1]] = [0, 200, 80]
    rgb[meta["ny"] - 1 - goal[0], goal[1]] = [60, 120, 255]
    Image.fromarray(rgb).save(out)


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--to", dest="dst", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--png", default=None)
    args = ap.parse_args()

    result = compute_path(args.src, args.dst)
    sf, df = result["src"]["floor"], result["dst"]["floor"]
    p = result["path"]

    if sf == df:
        print(f"同层 floor{sf}: {args.src}(id={result['src']['id']}) -> {args.dst}(id={result['dst']['id']})")
        print(f"  路径长={result['length_m']} m  折点={len(p)}")
        if args.png:
            rooms = load_rooms()
            _, sx, sy, _ = find_room(rooms, args.src)
            _, gx, gy, _ = find_room(rooms, args.dst)
            world, grid, meta = plan_on_floor(load_floor(sf), sx, sy, gx, gy)
            render_png(grid, meta, world, world_to_grid(sx, sy, meta),
                       world_to_grid(gx, gy, meta), args.png)
            print(f"  已存 {args.png}")
    else:
        print(f"跨层 floor{sf}->floor{df}: {args.src}(id={result['src']['id']}) -> {args.dst}(id={result['dst']['id']})")
        print(f"  经楼梯井#{result['stairwell']}  路径长={result['length_m']} m  折点={len(p)}")
        if args.png:
            print("  （跨层不画 PNG，需前端 3D 高亮）")

    if args.out:
        json.dump(result, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  已存 {args.out}")


if __name__ == "__main__":
    main()
