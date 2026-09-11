# -*- coding: utf-8 -*-
"""R11 门错位扫描(只读): 找出"门集与房间几何整层错位"的楼。
判据: 该层有房有门, 但 门贴房界(<0.4m)的服务房数 base < 85%; 若能找到整层平移使服务房>=90% => 可平移修正。
只报不改。冻结楼 c006/c009/c103/c104 仅报不修。
"""
import sys, json, glob, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import LineString, Point

FROZEN = {"c006", "c009", "c103", "c104"}
ALL = sorted(os.listdir(r"D:\gym3d\data\buildings"))

def served_count(rings, doors_xy, shift=(0.0, 0.0)):
    sx, sy = shift
    n = 0
    for ring in rings:
        best = 999.0
        for (dx, dy) in doors_xy:
            b = ring.distance(Point(dx + sx, dy + sy))
            if b < best:
                best = b
            if best < 0.4:
                break
        if best < 0.4:
            n += 1
    return n

def best_shift(rings, doors_xy):
    n_room = len(rings)
    best = (0.0, 0.0, served_count(rings, doors_xy))
    if n_room <= 1:
        return best
    for i in range(-15, 16):
        dx = i / 5.0                      # -3.0..3.0 step .2
        for j in range(-15, 16):
            dy = j / 5.0
            s = served_count(rings, doors_xy, (dx, dy))
            if s > best[2]:
                best = (dx, dy, s)
                if s >= n_room:
                    return best
    return best

for name in ALL:
    if name in FROZEN:
        continue
    d = r"D:\gym3d\data\buildings\%s\floors" % name
    if not os.path.isdir(d):
        continue
    fprobs = []
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json")), key=lambda s: int(s.split("floor")[-1][:-5])):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        doors_xy = [(p["x"], p["y"]) for p in fl.get("doors", [])]
        rings = []
        for r in fl.get("rooms", []):
            poly = r.get("poly", [])
            if len(poly) < 3:
                continue
            try:
                if __import__("shapely.geometry", fromlist=["Polygon"]).Polygon(poly).area < 0.5:
                    continue
                rings.append(LineString(poly))
            except Exception:
                continue
        if len(rings) < 3 or len(doors_xy) < 5:
            continue
        base = served_count(rings, doors_xy)
        if base >= 0.85 * len(rings):
            continue
        dx, dy, ns = best_shift(rings, doors_xy)
        tag = "可平移修正" if ns >= 0.9 * len(rings) else "平移也救不回"
        fprobs.append((F, len(rings), len(doors_xy), base, dx, dy, ns, tag))
        print("%s F%-2d 房=%d 门=%d base=%d 平移(%.1f,%.1f)->%d %s" %
              (name, F, len(rings), len(doors_xy), base, dx, dy, ns, tag), flush=True)
    if fprobs and name not in FROZEN:
        print("==> %s 需修正楼层 %d 个" % (name, len(fprobs)), flush=True)
