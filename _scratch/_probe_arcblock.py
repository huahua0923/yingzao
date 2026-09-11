# -*- coding: utf-8 -*-
"""定位「某个局部方块里的弧」到底卡在哪一步(只读)。

背景: c006 交付轮廓外有 588.8m 弧, 集中在 (±33,-36)/(±27,-36)/(±55,±10) 几块。
要分清是
  (a) 分类阶段就没认出(墙层上没实体 / 实体类型不认 / 被判成 blob 剔除), 还是
  (b) 认出来了, 但该层轮廓取自别的层(outline_unify 基准层不含它), 于是交付轮廓切掉它。
做法: 对指定层, 把「墙层原始实体」与「classify 出的墙」分别按给定方框计数,
      并报 classify 墙的细度(2A/P)与面积, 判断有没有被当 blob 剔掉。

用法: python _probe_arcblock.py c006 4 33,-36 -33,-36
      python _probe_arcblock.py c006 0 27,-36 -27,-36 55,10 -55,10 55,-10 -55,-10
"""
import sys, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from shapely.geometry import Polygon
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import floor_of, to_local, in_floor_x_range

nm, Fs = sys.argv[1], int(sys.argv[2])
boxes = []
for a in sys.argv[3:]:
    x, y = a.split(",")
    boxes.append((float(x), float(y)))

p = load_profile(nm)
doc = ezdxf.readfile(p.dxf)
R = 12.0   # 捕获半径(局部 m)

def box_of(px, py):
    """按局部坐标找所属方框(用局部近似: 减去 cx/该层 fy)。"""
    for (bx, by) in boxes:
        if math.hypot(px - bx, py - by) <= R:
            return (bx, by)
    return None

# --- 1. 原始墙层实体 ---
raw = collections.Counter()
raw_pts = collections.defaultdict(int)
for e in doc.modelspace():
    if e.dxf.layer != p.wall_layer:
        continue
    t = e.dxftype()
    try:
        if t == "LINE":
            xs = [float(e.dxf.start.x), float(e.dxf.end.x)]
            ys = [float(e.dxf.start.y), float(e.dxf.end.y)]
        elif t == "ARC":
            q = list(e.flattening(50.0))
            xs = [float(a[0]) for a in q]; ys = [float(a[1]) for a in q]
        elif t == "LWPOLYLINE":
            q = list(e.get_points("xyseb"))
            xs = [float(a[0]) for a in q]; ys = [float(a[1]) for a in q]
        elif t == "POLYLINE":
            xs = [float(v.dxf.location.x) for v in e.vertices]
            ys = [float(v.dxf.location.y) for v in e.vertices]
        else:
            raw["其他:" + t] += 1
            continue
    except Exception:
        raw["取几何失败:" + t] += 1
        continue
    if not xs:
        continue
    cxm = (min(xs) + max(xs)) / 2.0
    cym = (min(ys) + max(ys)) / 2.0
    if int(round(floor_of(p, cxm, cym))) != Fs:
        continue
    lx, ly = to_local(p, cxm, cym, Fs)
    b = box_of(lx, ly)
    if b is None:
        continue
    raw[(b, "有bulge" if (t == "LWPOLYLINE" and any(len(a) > 4 and abs(a[4]) > 1e-9 for a in e.get_points("xyseb"))) else t)] += 1

print("== %s 层%d  半径%.0fm 方框 %s ==" % (nm, Fs, R, boxes))
print("\n-- 1. 墙层原始实体(按方框 / 类型) --")
if not raw:
    print("   (空) 该层这些位置墙层上没有任何实体")
for k in sorted(raw, key=lambda k: (str(k[0]), str(k[1]))):
    print("   %-16s %-14s %d" % (str(k[0]), k[1], raw[k]))

# --- 2. classify 结果 ---
walls, doors, stairs, cols = classify.classify(doc.modelspace(), p)
print("\n-- 2. classify: 墙 %d / 门 %d / 楼梯 %d / 柱 %d --" % (len(walls), len(doors), len(stairs), len(cols)))

hitw = collections.defaultdict(list)
for w in walls:
    if len(w) < 3:
        continue
    cxm = sum(a[0] for a in w) / len(w)
    cym = sum(a[1] for a in w) / len(w)
    if int(round(floor_of(p, cxm, cym))) != Fs:
        continue
    lx, ly = to_local(p, cxm, cym, Fs)
    b = box_of(lx, ly)
    if b is None:
        continue
    P = Polygon([(a[0] / 1000.0, a[1] / 1000.0) for a in w]) if len(w) >= 3 else None
    thin = float("nan")
    if P is not None and not P.is_empty and P.length > 0.01:
        thin = 2 * P.area / P.length
    hitw[b].append((len(w), thin, P.area if P else 0.0))

print("\n-- 3. 落在方框内的 classify 墙(细度 2A/P, <=0.6 才算墙, >0.6 会被当 blob 剔) --")
if not hitw:
    print("   (空) classify 没在这些位置产出任何墙 -> 病灶在分类/识别阶段, 不在轮廓")
for b in sorted(hitw, key=str):
    L = hitw[b]
    print("   方框%-12s 共%d条" % (str(b), len(L)))
    for n, thin, ar in sorted(L, key=lambda t: -t[2])[:6]:
        print("      顶点%-4d 细度%6.2f 面积%7.2f㎡" % (n, thin, ar))
