# -*- coding: utf-8 -*-
"""给 classify.py 打「曲墙识别」补丁(弧要素离散化)。二进制写盘以保住 LF。

改动只有三处(不碰任何既有语义):
  1) 新增 math/CURVE_MIN_R/CURVE_STEP_MM/_seg_radius/_has_curve;
  2) 墙循环: 带「曲墙级」bulge 的 LWPOLYLINE 按弧离散(flattening)后再交下游;
     door_by_points 的点数判定仍在「原始点数」上做(离散只对判为墙的生效);
  3) 新增 ARC 实体循环: 墙层上半径 >= CURVE_MIN_R 的弧按弧离散当墙
     (半径更小的 = 门扇开启弧, 排除, 否则每个门长出墙)。
"""
import os, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = r"D:\gym3d\backend\recognizer\classify.py"
src = open(P, encoding="utf-8").read()
assert "\r" not in src, "classify.py 含 CRLF, 先处理"
assert "_has_curve" not in src, "似乎已打过补丁"

# ---- 1) 常量与工具函数, 插在 _in_x_range 之前 ----
HELPERS = '''import math

from ezdxf.path import make_path

# ---- 弧要素(曲墙) ----
# 图上「弧」有两种来源: ARC 实体, 以及 LWPOLYLINE 段上的 bulge(凸度)。
# 半径小于 CURVE_MIN_R 的弧 = 门扇开启弧 / 装饰弧(实测各楼门弧 0.5~1.5m), 不是墙;
# 半径 >= CURVE_MIN_R 的弧 = 曲墙(实测 c006 逸夫楼 8.3~12.4m、c041 26~29m、c103 16~24m)。
# 曲墙要按弧离散成密集短段再交下游: 默认路径 derive_walls_and_outline 本身方向无关
# (2 点线 buffer 后 union), 能吃任意方向段; 旧代码把 ARC 整体丢弃、把 bulge 段当直弦,
# 才是「曲墙识别不出来」的根因。
CURVE_MIN_R = 2.0        # 米: 判定「曲墙」而非「门弧」的半径阈值
CURVE_STEP_MM = 250.0    # 弧离散步长(mm): 0.25m 一段


def _seg_radius(p0, p1, bulge):
    """一段(两端点 + 凸度)的半径(图纸单位, 通常 mm)。非弧段返回 None。"""
    b = abs(bulge)
    if b < 1e-9:
        return None
    chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if chord < 1e-9:
        return None
    theta = 4.0 * math.atan(b)      # 圆心角
    s = math.sin(theta / 2.0)
    if s < 1e-9:
        return None
    return chord / (2.0 * s)


def _has_curve(e, min_r_mm=CURVE_MIN_R * 1000.0):
    """LWPOLYLINE 是否含「曲墙级」弧段(半径 >= min_r_mm)。"""
    try:
        pts = list(e.get_points("xyseb"))
    except Exception:
        return False
    for i in range(len(pts) - 1):
        b = pts[i][4] if len(pts[i]) > 4 else 0.0
        r = _seg_radius((pts[i][0], pts[i][1]), (pts[i + 1][0], pts[i + 1][1]), b)
        if r is not None and r >= min_r_mm:
            return True
    return False


def _flatten_curve(e, step_mm=CURVE_STEP_MM):
    """把带 bulge 的 LWPOLYLINE 离散成点列; 失败返回 None(调用方回退原顶点)。"""
    try:
        return [(float(q.x), float(q.y)) for q in make_path(e).flattening(step_mm)]
    except Exception:
        return None


'''
anchor1 = "def _in_x_range(pts, p):"
assert src.count(anchor1) == 1
src = src.replace(anchor1, HELPERS + anchor1)

# ---- 2) 墙循环 ----
OLD_WALL = '''        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == p.wall_layer:
            pts = [tuple(pt[:2]) for pt in e.get_points()]
            if len(pts) < 2:
                continue
            if not _in_x_range(pts, p):
                continue
            if by_points:
                lp = len(pts)
                if lp >= p.door_min_points:
                    doors.append(pts)
                elif lp == p.stair_points:
                    stairs.append(pts)
                else:
                    walls.append(pts)
            else:
                walls.append(pts)
'''
NEW_WALL = '''        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == p.wall_layer:
            raw = [tuple(pt[:2]) for pt in e.get_points()]
            if len(raw) < 2:
                continue
            if not _in_x_range(raw, p):
                continue
            if by_points:
                # 点数判定必须在「原始点数」上做: 离散会把点数翻十几倍, 否则墙会被判成门
                lp = len(raw)
                if lp >= p.door_min_points:
                    doors.append(raw)
                    continue
                if lp == p.stair_points:
                    stairs.append(raw)
                    continue
            if _has_curve(e):
                # 曲墙: 按弧离散成 0.25m 短段(LWPolyline 无 flattening, 走 ezdxf.path)
                tp = _flatten_curve(e)
                if tp and len(tp) >= 2:
                    walls.append(tp)
                continue
            walls.append(raw)

    # ARC 实体: 墙层上「曲墙级」半径的弧 = 曲墙(c006 逸夫楼 54 段圆弧外墙)。
    # 同一层上还画着门扇开启弧(半径 0.5~1.5m), 必须排除, 否则每扇门都长出一堵墙。
    for e in msp:
        if e.dxftype() != "ARC" or e.dxf.layer != p.wall_layer:
            continue
        if e.dxf.radius < CURVE_MIN_R * 1000.0:
            continue
        tp = [(float(q[0]), float(q[1])) for q in e.flattening(CURVE_STEP_MM)]
        if len(tp) < 2 or not _in_x_range(tp, p):
            continue
        walls.append(tp)
'''
assert src.count(OLD_WALL) == 1, "墙循环原文不匹配"
src = src.replace(OLD_WALL, NEW_WALL)

with open(P, "w", encoding="utf-8", newline="") as f:
    f.write(src)
print("已打补丁:", P)
print("CRLF:", src.count("\r"), " 行数:", src.count("\n"))
