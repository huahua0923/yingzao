# -*- coding: utf-8 -*-
"""对单层做「真缺墙 vs 平移错位 vs 双副本」判别。

在 0 偏移下漏墙率高时，扫一组候选平移量 (dx,dy)：若把源墙采样点平移后覆盖率
能大幅回升(>75%)→ 是整体错位/对错副本(offset 即错位量)，不是缺墙。
平移仍无法覆盖的源点 = 该区域真没识别出墙(真漏)。
用法: python -u _dxf_gapcheck.py <name> <F0> [F1 ...]
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import json
import shapely.geometry as sg
import _dxf_audit as A          # 复用 _walls_geom / _source_wall_points / _thin_core
import run_step, ezdxf

BASE = r"D:\gym3d\data\buildings"
WALL_DIST = 0.40
MAXP = 600                       # 每个候选层最多采样的源点
OFFSETS = [(round(dx, 2), round(dy, 2))
           for dx in range(-3, 4) for dy in range(-3, 4)]  # step1m ±3m


def gapcheck(name, F):
    p = run_step.load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    fj = os.path.join(BASE, name, "floors", f"floor{F}.json")
    fl = json.load(open(fj, encoding="utf-8"))
    ol = fl.get("outline")
    box = (min(q[0] for q in ol), min(q[1] for q in ol),
           max(q[0] for q in ol), max(q[1] for q in ol))
    cov = A._walls_geom(fl)
    if cov is None or cov.is_empty:
        print(f"{name} {F+1}层: 无识别墙几何")
        return
    src = A._source_wall_points(doc, p, F, box)
    if len(src) < 40:
        print(f"{name} {F+1}层: 源墙点太少 {len(src)}，跳过")
        return
    step = max(1, len(src) // MAXP)
    pts = src[::step]
    def cover(dx, dy):
        hit = 0
        for (x, y) in pts:
            if cov.distance(sg.Point(x - dx, y - dy)) <= WALL_DIST:
                hit += 1
        return hit / len(pts)
    c0 = cover(0.0, 0.0)
    best = (c0, 0, 0)
    for dx, dy in OFFSETS:
        if dx == 0 and dy == 0:
            continue
        c = cover(dx, dy)
        if c > best[0]:
            best = (c, dx, dy)
    tag = ""
    if c0 >= 0.85:
        tag = "OK 基本对齐"
    elif best[0] >= 0.75:
        tag = f"平移错位/对错副本  (偏移 ({best[1]:+.1f},{best[2]:+.1f})m 后覆盖 {best[0]*100:.0f}%)"
    elif best[0] >= 0.45:
        tag = (f"部分错位兼漏墙：平移最优 ({best[1]:+.1f},{best[2]:+.1f})m 仅 {best[0]*100:.0f}%，"
               f"其余为真缺墙")
    else:
        tag = "真缺墙（平移救不回，源墙大段没识别出来）"
    print(f"{name} 第{F+1}层: 源点{len(pts)} 覆盖0偏移{c0*100:.0f}% | {tag}")


def main():
    name = sys.argv[1]
    for Fs in sys.argv[2:]:
        for F in [int(x) for x in Fs.split(",")]:
            try:
                gapcheck(name, F)
            except Exception as e:  # noqa: BLE001
                print(f"{name} F{F} ERR {str(e)[:120]}")


if __name__ == "__main__":
    main()
