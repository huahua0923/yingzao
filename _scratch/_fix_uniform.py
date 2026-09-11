# -*- coding: utf-8 -*-
"""批量修复 uniform 楼楼层错位：加 outline_unify=True（上层墙稀疏→轮廓塌碎→质心漂移），
重跑识别并报告修复前后漂移。

用法: python -u _fix_uniform.py c083 c084 ...   （无参则跑内置 UNIFORM 清单）
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend")

from shapely.geometry import Polygon

# 探针确认：所有层 X 范围一致 / Y 均匀，上层墙少导致轮廓塌碎 → outline_unify
UNIFORM = [
    "c083", "c084", "c085", "c086",
    "c072", "c073",
    "c054", "c055",
    "c080", "c057", "c062", "c063",
    "c019",
]
BASE = r"D:\gym3d\data\buildings"


def drift(name):
    d = os.path.join(BASE, name, "floors")
    xs, ys = [], []
    for fn in sorted(f for f in os.listdir(d) if re.match(r"floor\d+\.json$", f)):
        g = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        o = g.get("outline")
        if not o:
            continue
        c = Polygon(o).centroid
        xs.append(c.x)
        ys.append(c.y)
    return (max(xs) - min(xs), max(ys) - min(ys)) if xs else (0, 0)


def main():
    names = sys.argv[1:] or UNIFORM
    from recognizer import recognize
    from run_building import load_profile

    ok, fail = [], []
    N = len(names)
    for i, name in enumerate(names, 1):
        before = drift(name)
        prof = os.path.join(BASE, name, "profile.json")
        cfg = json.load(open(prof, encoding="utf-8"))
        cfg["outline_unify"] = True
        json.dump(cfg, open(prof, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        try:
            p = load_profile(name)
            if not os.path.exists(p.rooms):
                os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
                json.dump([], open(p.rooms, "w", encoding="utf-8"))
            recognize(p)
            after = drift(name)
            sys.stdout.write("[%d/%d] %-6s 漂移 X:%.2f->%.2f Y:%.2f->%.2f %s\n" % (
                i, N, name, before[0], after[0], before[1], after[1],
                "OK" if after[0] < 1 and after[1] < 1 else "仍需处理"))
            sys.stdout.flush()
            ok.append(name)
        except Exception as e:
            sys.stdout.write("[%d/%d] %-6s FAIL %s: %s\n" % (i, N, name, type(e).__name__, e))
            sys.stdout.flush()
            fail.append(name)
    print("\n完成: 成功 %d / 失败 %d" % (len(ok), len(fail)))
    if fail:
        print("失败:", ", ".join(fail))


if __name__ == "__main__":
    main()
