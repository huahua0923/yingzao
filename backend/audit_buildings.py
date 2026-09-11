# -*- coding: utf-8 -*-
"""逐栋审计 12 栋楼的标准 floor JSON，发现结构性/几何性问题。

只读，不改数据。从「标准 floor JSON」里抽取不变量并打分，输出每栋楼的
异常清单（墙厚漂移 / 柱数异常 / 门窗缺失 / 楼层面积突变 / 顶层屋顶女儿墙缺失等）。

用法: python backend/audit_buildings.py [c006 c009 ...]
"""
import json
import glob
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = r"D:\gym3d\data"

# 标准墙厚（来自 recognizer/standard.py 的单点定义）
STD_OUTER = 0.30
STD_INNER = 0.24
THICK_TOL = 0.005  # 归一化后允许的浮点抖动


def load_floors(d):
    fs = sorted(glob.glob(os.path.join(d, "floors", "floor*.json")))
    if not fs:
        fs = sorted(glob.glob(os.path.join(d, "floor*.json")))
    out = []
    for f in fs:
        try:
            out.append(json.load(open(f, encoding="utf-8")))
        except Exception as e:
            print(f"  !! 读失败 {f}: {e}")
    return out


def poly_area(pts):
    if not pts or len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def audit(name, d):
    floors = load_floors(d)
    if not floors:
        print(f"[{name}] 无 floor JSON")
        return
    issues = []
    cols_by_floor = []
    win_by_floor = []
    door_by_floor = []
    area_by_floor = []
    thick_hist = Counter()
    outer_rings = 0
    top = floors[-1]

    for F in floors:
        n = F.get("floor", "?")
        cols = F.get("columns", [])
        wins = F.get("windows", [])
        doors = F.get("doors", [])
        outline = F.get("outline", [])
        cols_by_floor.append(len(cols))
        win_by_floor.append(len(wins))
        door_by_floor.append(len(doors))
        area_by_floor.append(round(poly_area(outline), 1))

        for w in F.get("walls", []):
            t = w.get("thickness", 0)
            thick_hist[round(t, 3)] += 1
            typ = w.get("type")
            if typ == "outer":
                outer_rings += 1
            # 墙厚漂移：非标准值且非 0（0 可能是缺省）
            if t > 0 and abs(t - STD_OUTER) > THICK_TOL and abs(t - STD_INNER) > THICK_TOL:
                issues.append(f"F{n} 墙厚漂移 {w.get('id')} type={typ} thick={t}")

    # 柱数异常：各层柱数不一致，或某层为 0
    if len(set(cols_by_floor)) > 1:
        issues.append(f"柱数逐层不一致 {dict(zip(range(len(floors)), cols_by_floor))}")
    if 0 in cols_by_floor:
        issues.append("存在无柱楼层")

    # 窗缺失
    if min(win_by_floor) == 0:
        issues.append(f"有楼层无窗 {win_by_floor}")
    if sum(win_by_floor) == 0:
        issues.append("整栋无窗")

    # 门缺失
    if sum(door_by_floor) == 0:
        issues.append("整栋无门")

    # 面积突变（相邻层面积差 > 25%）
    for i in range(1, len(area_by_floor)):
        a0, a1 = area_by_floor[i - 1], area_by_floor[i]
        if a0 > 0 and a1 > 0 and abs(a0 - a1) / max(a0, a1) > 0.25:
            issues.append(f"F{i-1}→F{i} 面积突变 {a0}→{a1}")

    # 顶层屋顶/女儿墙
    has_roof = "roof" in top
    parapets = [w for w in top.get("walls", []) if w.get("type") == "parapet"]
    if not has_roof:
        issues.append("顶层无 roof")
    if not parapets:
        issues.append("顶层无女儿墙(parapet)")

    rooms_total = sum(len(F.get("rooms", [])) for F in floors)
    print(f"[{name}] {len(floors)}层  墙厚分布{ {k:v for k,v in thick_hist.items()} }")
    print(f"   柱/层={cols_by_floor} 窗/层={win_by_floor} 门/层={door_by_floor}")
    print(f"   面积/层={area_by_floor} 房间合计={rooms_total}")
    if issues:
        print(f"   ⚠ {len(issues)} 个问题:")
        for i in issues[:12]:
            print(f"      - {i}")
    else:
        print("   ✓ 无明显结构异常")


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not names:
        names = ["lihua"] + sorted(
            os.path.basename(p)
            for p in glob.glob(os.path.join(DATA, "buildings", "*"))
            if os.path.isdir(p) and os.path.exists(os.path.join(p, "profile.json"))
        )
    for name in names:
        d = os.path.join(DATA, "buildings", name) if name != "lihua" else DATA
        audit(name, d)
        print()


if __name__ == "__main__":
    main()
