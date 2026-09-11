# -*- coding: utf-8 -*-
"""门被墙吞掉的量化探针(只读) —— 用户「门有的夹在墙里看不到」的验收指标。

对每层: 取交付 walls(内墙+外墙, 含 holes) 的并集 W, 对每个 door 中心点 p:
  - swallowed : p 落在 W 内部(即门洞位置被实体墙覆盖) —— 用户看到的「门夹在墙里」
  - near      : p 到 W 的距离 < 0.15m(贴墙但未完全覆盖)
并报告吞门墙的尺寸(若是 1.1~1.5m×0.1m 的假墙 → 门符号被当墙的实锤)。

用法: python _probe_doors_swallowed.py c019 [c034 ...]
"""
import sys, os, glob, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

ROOT = r"D:\gym3d\data\buildings"


def walls_union(fl):
    polys = []
    for w in fl.get("walls", []):
        p = w.get("poly") or []
        if len(p) < 3:
            continue
        try:
            P = Polygon(p)
        except Exception:
            continue
        if not P.is_valid:
            P = P.buffer(0)
        if P.is_empty:
            continue
        for h in w.get("holes", []) or []:
            if len(h) >= 3:
                try:
                    H = Polygon(h)
                    if H.is_valid and not H.is_empty:
                        P = P.difference(H)
                except Exception:
                    pass
        if not P.is_empty:
            polys.append(P)
    if not polys:
        return None
    U = unary_union(polys)
    return U.buffer(0) if not U.is_valid else U


def run(name):
    fd = os.path.join(ROOT, name, "floors")
    files = sorted(glob.glob(os.path.join(fd, "floor*.json")), key=lambda f: int(os.path.basename(f)[5:-5]))
    tot_d = tot_sw = tot_near = 0
    for fp in files:
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        W = walls_union(fl)
        ds = fl.get("doors", [])
        if W is None or not ds:
            continue
        sw = near = 0
        for d in ds:
            pt = Point(d["x"], d["y"])
            if W.contains(pt):
                sw += 1
            elif W.distance(pt) < 0.15:
                near += 1
        tot_d += len(ds); tot_sw += sw; tot_near += near
        flag = "  <<<" if sw else ""
        print("  F%-2d 门%3d  吞门%3d  贴墙%3d%s" % (F, len(ds), sw, near, flag))
    pct = 100.0 * tot_sw / tot_d if tot_d else 0.0
    print("%-6s 合计 门%4d  吞门%4d (%.1f%%)  贴墙%4d" % (name, tot_d, tot_sw, pct, tot_near))
    return tot_d, tot_sw


for nm in sys.argv[1:]:
    print("===== %s =====" % nm)
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        print("  %s 失败: %s" % (nm, e))
