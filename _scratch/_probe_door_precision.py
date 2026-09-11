# -*- coding: utf-8 -*-
"""门识别精度探针(只读) —— 用户「不能把窗户识别成门 / 门夹在墙里看不到」的定标工具。

实测 c019/c034/c044 的墙层「不闭合折线」按形状分三类(全部 mm):
  A 真门符号 : 门扇线 + 门垛块; 含「等长且互相垂直、共享铰点」的两条扇线(闭位+开位)。
               例 c019 13 点(2 垛 + 2×1100), c034 14 点(2×750), c054 14 点(2×900)。
  B 墙垛/墙段: 4 点轴对齐闭合矩形(如 1480×240、630×120) —— 被 detect_doors 当 1.48/0.63m「门」,
               其顶点质心正落在墙里 → 用户看到的「门夹在墙里」。
  C 窗       : 240mm 厚 × 开口宽的细长矩形 + 玻璃/窗扇线(如 1000×240、1202×240),
               最长段被当门扇 → 用户说的「把窗户识别成门」。

候选判据(三条按序):
  1. 门扇 = 折线里**最长轴对齐段**(非轴对齐的是闭合对角/引线, c034 的 1134/1345、c019 的 849 全是它);
     仍须 ∈ [DOOR_LEAF_MIN, DOOR_LEAF_MAX)。
  2. 细长闭合环 = 不是门: 顶点串(含回边)围出的环面积 >= 0.5×凸包面积 且 凸包等效厚度 <= 0.45m。
  3. 4 个不同角点 + 全部边(含回边)轴对齐 + 短边 ∈ [0.08,0.45] → 墙垛/窗框矩形, 不是门。

用法: python _probe_door_precision.py [c019 c034 ...]   # 默认全部非冻结
"""
import sys, os, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from shapely.geometry import MultiPoint, Polygon
from backend.recognizer import classify as C
from backend.recognizer.component_library import DOOR_LEAF_MIN, DOOR_LEAF_MAX

ROOT = r"D:\gym3d\data\buildings"
FROZEN = {"c006", "c009", "c103", "c104"}
TOL = 0.02          # 轴对齐容差(m)
THIN_MAX = 0.45     # 判「细长环」的凸包等效厚度上限(m)
RING_RATIO = 0.5    # 环面积/凸包面积 大于它才算「围成环」
STUB_LO, STUB_HI = 0.08, 0.45


def shoelace(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def classify_pts(pts):
    """返回 (kind, leaf, note): kind ∈ door/stub/window/None。pts 已是本地米。"""
    n = len(pts)
    if n < 3:
        return None, 0.0, "点数<3"
    # 不同顶点
    uniq = []
    for q in pts:
        if not uniq or math.hypot(q[0] - uniq[-1][0], q[1] - uniq[-1][1]) > 1e-9:
            uniq.append(q)
    if len(uniq) >= 2 and math.hypot(uniq[0][0] - uniq[-1][0], uniq[0][1] - uniq[-1][1]) <= 1e-9:
        uniq = uniq[:-1]
    ring = list(uniq)
    segs = [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))] if len(ring) >= 3 else []
    axis = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs
            if min(abs(b[0] - a[0]), abs(b[1] - a[1])) <= TOL]
    leaf = max(axis) if axis else 0.0
    if leaf == 0.0:
        return None, 0.0, "无轴对齐段"

    # 3) 矩形墙垛/窗框: 4 个角点 + 全部边轴对齐 + 短边在 [0.08,0.45]
    if len(ring) == 4 and len(axis) == 4:
        xs = [q[0] for q in ring]
        ys = [q[1] for q in ring]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        short = min(w, h)
        if STUB_LO <= short <= STUB_HI:
            return "stub", leaf, "4点轴对齐矩形 短边%.2f" % short

    # 2) 细长闭合环(窗/异形块)
    if len(ring) >= 3:
        hull = MultiPoint(ring).convex_hull
        thin = (2 * hull.area / hull.length) if hull.length else 0.0
        if thin <= THIN_MAX:
            ra = shoelace(ring)
            if hull.area > 1e-9 and ra / hull.area >= RING_RATIO:
                return "window", leaf, "细长环 厚%.2f 环/包%.2f" % (thin, ra / hull.area)

    if not (DOOR_LEAF_MIN <= leaf < DOOR_LEAF_MAX):
        return None, leaf, "扇长%.2f 越界" % leaf
    return "door", leaf, ""


def run(name, verbose=False):
    from run_building import load_profile
    p = load_profile(name)
    msp = ezdxf.readfile(p.dxf).modelspace()
    kinds = collections.Counter()
    doors = collections.Counter()
    notes = collections.Counter()
    for e in msp:
        if e.dxftype() != "LWPOLYLINE" or e.dxf.layer != p.wall_layer:
            continue
        raw = [tuple(q[:2]) for q in e.get_points()]
        if len(raw) < 3 or not C._in_x_range(raw, p):
            continue
        if e.closed or (abs(raw[0][0] - raw[-1][0]) <= 1e-6 and abs(raw[0][1] - raw[-1][1]) <= 1e-6):
            continue
        pts = [(a / 1000.0, b / 1000.0) for a, b in raw]
        old = max(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                  for i in range(len(pts) - 1))
        if not (DOOR_LEAF_MIN <= old < DOOR_LEAF_MAX):
            continue
        kind, leaf, note = classify_pts(pts)
        kinds[kind or "None"] += 1
        if kind == "door":
            doors[round(leaf, 1)] += 1
        if verbose:
            notes[(kind or "None", note.split()[0] if note else "")] += 1
    print("%-6s 旧判门%4d ->  真门%4d  墙垛%4d  窗%4d  其他%4d   门宽%s"
          % (name, sum(kinds.values()), kinds["door"], kinds["stub"], kinds["window"], kinds["None"],
             dict(sorted(doors.items()))))
    return kinds


names = sys.argv[1:]
if not names:
    names = [n for n in sorted(os.listdir(ROOT))
             if n.startswith("c") and n[1:].isdigit() and n not in FROZEN]
for nm in names:
    try:
        run(nm)
    except Exception as e:  # noqa: BLE001
        print("%-6s 失败: %s" % (nm, e))
