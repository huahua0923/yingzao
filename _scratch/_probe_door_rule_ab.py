# -*- coding: utf-8 -*-
"""detect_doors 新旧口径 A/B(只读) —— 新=门扇铰对判据, 旧=最长段 ∈[0.6,3.0)。

对每栋: 用同一份墙层折线(含 flag-closed) 分别跑新旧判据, 比较门数与门宽分布。
门宽分布是验收关键: 真门应集中在 0.6~1.5m 且与楼型自洽;
出现 1.48/1.13/1.34/0.99 这种「墙厚×长边」「对角线」值 = 旧口径的假门。

用法: python _probe_door_rule_ab.py [c019 ...]
"""
import sys, os, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from backend.recognizer import classify as C
from backend.recognizer import geometry as G
from backend.recognizer.component_library import DOOR_LEAF_MIN, DOOR_LEAF_MAX

ROOT = r"D:\gym3d\data\buildings"
FROZEN = {"c006", "c009", "c103", "c104"}


def old_rule(pts):
    n = len(pts)
    if n < 3:
        return None
    if abs(pts[0][0] - pts[-1][0]) <= 1e-6 and abs(pts[0][1] - pts[-1][1]) <= 1e-6:
        return None
    longest = 0.0
    for i in range(n - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        L = (dx * dx + dy * dy) ** 0.5
        if L > longest:
            longest = L
    if longest < DOOR_LEAF_MIN or longest >= DOOR_LEAF_MAX:
        return None
    return round(longest, 2)


def run(name):
    from run_building import load_profile
    p = load_profile(name)
    msp = ezdxf.readfile(p.dxf).modelspace()
    cands = []
    for e in msp:
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != p.wall_layer:
            continue
        raw = [tuple(q[:2]) for q in e.get_points()]
        if len(raw) < 3 or not C._in_x_range(raw, p):
            continue
        if abs(raw[0][0] - raw[-1][0]) <= 1e-6 and abs(raw[0][1] - raw[-1][1]) <= 1e-6:
            continue
        cands.append([(a / 1000.0, b / 1000.0) for a, b in raw])
    ow, nw = collections.Counter(), collections.Counter()
    for pts in cands:
        o = old_rule(pts)
        if o is not None:
            ow[o] += 1
    for d in G.detect_doors(cands, None, p):
        nw[round(d["w"], 2)] += 1
    no, nn = sum(ow.values()), sum(nw.values())
    print("%-6s 旧%4d -> 新%4d (-%d)   新门宽%s" % (name, no, nn, no - nn, dict(sorted(nw.items()))))
    if no:
        drop = {k: v for k, v in ow.items() if k not in nw}
        if drop:
            print("        被否掉的旧门宽: %s" % dict(sorted(drop.items())))


names = sys.argv[1:]
if not names:
    names = [n for n in sorted(os.listdir(ROOT))
             if n.startswith("c") and n[1:].isdigit() and n not in FROZEN]
for nm in names:
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        print("%-6s 失败: %s" % (nm, e))
