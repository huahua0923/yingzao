# -*- coding: utf-8 -*-
"""探针：按 classifier 提取「干净墙体」，输出每层墙体的真实 X/Y 中心与 X 区间。

用于诊断「楼层错位」：DXF 里每层平面并排画在不同 X 位置，而 profile 只有单 cx，
导致 to_local 后各层横移。本脚本给出该楼正确的 floor_plans（[cx, cy, x_min, x_max]）。

用法: python backend/probe_floors.py c009
"""
import json
import os
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import ensure_sys_path  # noqa: E402

ensure_sys_path()          # 仓库根也挂上（run_building 在根目录）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ezdxf
from run_building import load_profile
from recognizer.profile import floor_of


def wall_points(msp, p):
    """按 classifier 提取墙体多段线（CAD 毫米），返回每段的重心点。"""
    is_line = getattr(p, "classifier", "lwpolyline") == "line"
    if is_line:
        from recognizer.classify_line import classify_line
        walls, _, _, _ = classify_line(msp, p)
    else:
        from recognizer.classify import classify
        walls, _, _, _ = classify(msp, p)
    return walls


def main():
    name = sys.argv[1]
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf, encoding="utf-8")
    walls = wall_points(doc.modelspace(), p)

    # 按 floor_of 分桶，统计每层墙体重心 X/Y 与 X 区间
    import collections
    pts = collections.defaultdict(list)
    for seg in walls:
        cx = sum(q[0] for q in seg) / len(seg)
        cy = sum(q[1] for q in seg) / len(seg)
        f = floor_of(p, cx, cy)
        pts[f].append((cx, cy))

    print(f"[{name}] 墙段总数={len(walls)}  cx={p.cx} cy={p.cy} offset={p.offset}")
    print(f"  建议 floor_plans（每层 [cx, cy, x_min, x_max]，毫米）：")
    plans = []
    for f in sorted(pts):
        xs = [q[0] for q in pts[f]]
        ys = [q[1] for q in pts[f]]
        xc = sum(xs) / len(xs)
        yc = sum(ys) / len(ys)
        x0, x1 = min(xs), max(xs)
        plans.append((f, round(xc), round(yc), round(x0), round(x1)))
        print(f"    F{f}: 墙={len(pts[f]):4d}  cx={round(xc)}  cy={round(yc)}  x范围=[{round(x0)},{round(x1)}]")
    print("  json 片段：")
    print("  \"floor_plans\": " + json.dumps([[p[1], p[2], p[3], p[4]] for p in plans]))


if __name__ == "__main__":
    main()
