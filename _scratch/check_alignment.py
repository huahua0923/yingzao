# -*- coding: utf-8 -*-
"""楼层对齐诊断：逐栋计算跨层轮廓质心漂移，标出 >1m 的错位楼。

用法:
  python check_alignment.py            # 全部 data/buildings 下的楼，按漂移降序
  python check_alignment.py c043 c079  # 只查指定楼

判读口径（见 楼层对齐修复方案.md）：
  - X 漂移 > 1m → 首层/塔楼画在另一 X 列，或轮廓碎片化塌成小片（uniform 楼单一 cx 无法居中）。
  - Y 漂移 > 1m → 层间 Y 间距非均匀 / 双翼 / 阶梯楼质心误报。
  - F0 离原点 > 5m 但跨层漂移 < 1m → 整栋整体偏移（外观，非错位）。
  - 阶梯楼（塔楼比裙楼小）质心天然不同，漂移需对照包围盒判断塔楼是否居中/嵌套，不算真错位。
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import Polygon

BASE = r"D:\gym3d\data\buildings"
THRESHOLD = 1.0


def floor_centroids(name):
    fdir = os.path.join(BASE, name, "floors")
    if not os.path.isdir(fdir):
        return []
    out = []
    for fn in sorted(f for f in os.listdir(fdir) if re.match(r"floor\d+\.json$", f)):
        g = json.load(open(os.path.join(fdir, fn), encoding="utf-8"))
        o = g.get("outline")
        if not o:
            continue
        p = Polygon(o)
        out.append((fn, p.centroid, p.bounds))
    return out


def check(name):
    cents = floor_centroids(name)
    if not cents:
        return None
    xs = [c[1].x for c in cents]
    ys = [c[1].y for c in cents]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    off0 = (xs[0] ** 2 + ys[0] ** 2) ** 0.5
    return {"n": len(cents), "dx": dx, "dy": dy, "off0": off0,
            "worst": dx + dy, "cents": cents}


def main():
    names = sys.argv[1:]
    if not names:
        names = sorted(d for d in os.listdir(BASE)
                       if os.path.isdir(os.path.join(BASE, d))
                       and os.path.exists(os.path.join(BASE, d, "profile.json")))
    rows = []
    for n in names:
        r = check(n)
        if r:
            rows.append((n, r))
    rows.sort(key=lambda t: -t[1]["worst"])
    bad = [t for t in rows if t[1]["worst"] >= THRESHOLD]
    print("%-6s %4s %9s %9s %9s %s" % ("楼", "层数", "X漂移m", "Y漂移m", "F0离原点", "判定"))
    for n, r in rows:
        flag = ">> 错位" if r["worst"] >= THRESHOLD else ""
        print("%-6s %4d %9.2f %9.2f %9.2f %s" % (n, r["n"], r["dx"], r["dy"], r["off0"], flag))
    print("\n错位(>=1m): %d 栋 / 共 %d 栋" % (len(bad), len(rows)))
    if bad:
        print("错位清单:", ", ".join(n for n, _ in bad))


if __name__ == "__main__":
    main()
