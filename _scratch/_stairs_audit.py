# -*- coding: utf-8 -*-
"""全宿舍公寓楼梯井真伪审计(只读): 真楼梯=DXF里画了踏板梯列; 假井=检测器链式合并无踏板证据。

对每栋: 每层在 DXF 找密集竖直踏板梯列(真楼梯签名) -> 聚成"井"(x近邻<=3.5);
对照 floor JSON 现有井: 井质心 2m 内有无踏板梯列 => confirmed(真) / 无证据(fake)。
"""
import sys, math, os, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import to_local, floor_of

SCOPE = ["c017","c018","c019","c026","c031","c032","c033","c043","c044","c045",
         "c046","c054","c055","c056","c057","c072","c073","c079","c080","c083",
         "c084","c085","c086","c109","c041","c029","c030","c034","c059","c060",
         "c061","c062","c063","c064","c065","c116"]

def cands_for(p, walls, F):
    out = []
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        if not any(abs(floor_of(p, cx, y) - F) < 0.5 for y in [q[1] for q in pts]):
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        for i in range(len(local) - 1):
            a, b = local[i], local[i + 1]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            if L < 0.05 or min(abs(dx), abs(dy)) > 0.02:
                continue
            if abs(dx) >= abs(dy) and 0.8 <= L <= 3.0:
                out.append(((a[0] + b[0]) / 2, a[1], min(a[0], b[0]), max(a[0], b[0])))
    return out

def find_ladders(cands, xwin=2.2, maxrowgap=0.42, minrows=5):
    cands = sorted(cands, key=lambda c: c[1])
    cols = []
    for cx, cy, x0, x1 in cands:
        placed = False
        for col in cols:
            if abs(cy - col[-1][0]) <= maxrowgap and abs(cx - col[-1][1]) <= xwin:
                col.append((cy, cx)); placed = True; break
        if not placed:
            cols.append([(cy, cx)])
    found = []
    for col in cols:
        if len(col) >= minrows:
            ys = [c for c, _ in col]; xs = [cx for _, cx in col]
            sp = max(ys) - min(ys)
            if sp >= 1.5:
                found.append([min(ys), max(ys), min(xs), max(xs)])
    return found

def ladders_to_shafts(lads):
    wells = []
    for y0, y1, x0, x1 in sorted(lads, key=lambda v: (v[0] + v[1]) / 2):
        cy = (y0 + y1) / 2
        hit = False
        for i, (wy0, wy1, wx0, wx1) in enumerate(wells):
            if abs(cy - (wy0 + wy1) / 2) < 1.2 and abs((x0 + x1) / 2 - (wx0 + wx1) / 2) <= 4.0:
                wells[i] = (min(wy0, y0), max(wy1, y1), min(wx0, x0), max(wx1, x1)); hit = True; break
        if not hit:
            wells.append((y0, y1, x0, x1))
    return wells

for name in SCOPE:
    d = r"D:\gym3d\data\buildings\%s" % name
    if not os.path.isdir(d):
        continue
    fd = os.path.join(d, "floors")
    if not os.path.isdir(fd):
        continue
    # floor JSON 现有井(逐层)
    exist_by_floor = {}
    for F in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        fn = os.path.basename(F)[5:-5]
        try:
            fl = json.load(open(F, encoding="utf-8"))
        except Exception:
            continue
        exist_by_floor[fn] = [(w["x0"], w["x1"], w["yBot"], w["yTop"]) for w in fl.get("stairwells", [])]
    total_exist = sum(len(v) for v in exist_by_floor.values())
    # DXF 踏板梯列
    try:
        p = load_profile(name)
        doc = ezdxf.readfile(p.dxf)
        walls, doors, stairs, cols = classify.classify(doc.modelspace(), p)
        floors = sorted({floor_of(p, sum(q[0] for q in w) / len(w), sum(q[1] for q in w) / len(w)) for w in walls})
    except Exception as e:
        print("%-5s DXF读取失败 %s" % (name, e)); continue
    n_lad = 0
    shafts_per = {}
    for F in floors:
        lads = find_ladders(cands_for(p, walls, F))
        n_lad += len(lads)
        shafts_per[F] = ladders_to_shafts(lads)
    # 确认率: 逐层现有井质心是否有踏板列证据
    conf = 0
    for F, wells in exist_by_floor.items():
        for w in wells:
            cx, cy = (w[0] + w[1]) / 2, (w[2] + w[3]) / 2
            if any(abs(cy - (y0 + y1) / 2) <= 1.6 and abs(cx - (x0 + x1) / 2) <= 3.0
                   for (y0, y1, x0, x1) in shafts_per.get(int(F), [])):
                conf += 1
    # 楼板内墙房间洞对井的覆盖率(高=井压在房间上=假)
    ov = 0
    for F, wells in exist_by_floor.items():
        try:
            fl = json.load(open(os.path.join(fd, "floor%s.json" % F), encoding="utf-8"))
        except Exception:
            continue
        from shapely.geometry import Polygon, box
        from shapely.ops import unary_union
        holU = None
        for w in fl["walls"]:
            if w["type"] != "inner":
                continue
            P = Polygon(w["poly"])
            hs = [Polygon(h) for h in w.get("holes", [])]
            for h in hs:
                holU = h if holU is None else unary_union([holU, h])
        if holU is None:
            continue
        for w in wells:
            b = box(w[0], w[2], w[1], w[3]).buffer(-0.05)
            if b.area > 0.3:
                ov += b.intersection(holU).area / b.area
    ovpct = 100 * ov / total_exist if total_exist else 0
    tag = "OK" if (total_exist and conf >= total_exist * 0.5) else ("部分" if conf else "假/无")
    print("%-5s 现井=%d 踏板证据井=%d 平均压房率=%.0f%%   => %s" % (name, total_exist, conf, ovpct, tag))
