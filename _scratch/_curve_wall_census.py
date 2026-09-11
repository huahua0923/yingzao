# -*- coding: utf-8 -*-
"""弧形墙家底普查(只读): 统计各楼『墙体层』里的弧线要素有多少没被识别。

几何来源三类:
  A. ARC 实体(独立圆弧)
  B. LWPOLYLINE 带 bulge(凸度 != 0 的段)  —— 图上「一键画弧墙」的常见产物
  C. SPLINE / ELLIPSE
当前 classify 的墙线只吃『直线段』(2 点 LWPOLYLINE / 直线), 上面三类要么整体丢弃,
要么 bulge 段被当成直线弦 -> 弧墙变直线或整段消失。

用法: python _curve_wall_census.py [name ...]
"""
import os, sys, glob, collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]
import ezdxf

ROOT = r"D:\gym3d\data\buildings"


def wall_layers(dxf_path):
    """从 DXF 里找出所有『墙体』候选图层名(含 墙体/墙 字样)。"""
    doc = ezdxf.readfile(dxf_path)
    return {ly.dxf.name for ly in doc.layers if "墙" in ly.dxf.name}


import math

# 门弧(门扇开启弧)/柱装饰弧半径一般 0.5~1.5m; 真正的曲墙半径通常 >= 2m
DOOR_ARC_R = 2.0


def arc_len(e):
    """ARC/带 bulge 段的近似弧长(m)。"""
    r = e.dxf.radius / 1000.0
    a0 = e.dxf.start_angle
    a1 = e.dxf.end_angle
    sweep = (a1 - a0) % 360
    if sweep == 0:
        sweep = 360
    return r * math.radians(sweep)


def bulge_geom(p0, p1, b):
    """由弦两端点 + 凸度算 (半径, 弧长) [m]。b = tan(θ/4)。"""
    dx = (p1[0] - p0[0]) / 1000.0
    dy = (p1[1] - p0[1]) / 1000.0
    chord = math.hypot(dx, dy)
    if chord < 1e-9 or abs(b) < 1e-9:
        return None
    theta = 4.0 * math.atan(abs(b))          # 圆心角
    r = chord / (2.0 * math.sin(theta / 2.0))
    return r, r * theta


def census(name):
    d = os.path.join(ROOT, name)
    prof = os.path.join(d, "profile.json")
    if not os.path.exists(prof):
        return None
    import json
    p = json.load(open(prof, encoding="utf-8"))
    dxf = p.get("dxf")
    if not dxf or not os.path.exists(dxf):
        return name, None, "无DXF"
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    layers = wall_layers(dxf)
    n_arc = len_arc = 0          # 门弧(小半径)
    n_aw = len_aw = 0            # 曲墙 ARC(大半径)
    n_bg = len_bg = 0            # 门弧型 bulge 段
    n_bw = len_bw = 0            # 曲墙型 bulge 段
    n_spline = 0
    ex_aw = []
    for e in msp:
        lay = e.dxf.layer
        if lay not in layers and "墙" not in lay:
            continue
        t = e.dxftype()
        if t == "ARC":
            L = arc_len(e)
            r = e.dxf.radius / 1000.0
            if r >= DOOR_ARC_R:
                n_aw += 1
                len_aw += L
                if len(ex_aw) < 4:
                    ex_aw.append("r=%.2fm 弧长%.2fm" % (r, L))
            else:
                n_arc += 1
                len_arc += L
        elif t in ("SPLINE", "ELLIPSE"):
            n_spline += 1
        elif t == "LWPOLYLINE":
            pts = list(e.get_points("xyseb"))
            for i in range(len(pts) - 1):
                p0, p1 = pts[i], pts[i + 1]
                # DXF/ezdxf 约定: bulge 挂在「段的起点」顶点上(实测 make_path 验证)
                b = p0[4] if len(p0) > 4 else 0.0
                g = bulge_geom((p0[0], p0[1]), (p1[0], p1[1]), b)
                if not g:
                    continue
                r, L = g
                if r >= DOOR_ARC_R and L >= 0.5:
                    n_bw += 1
                    len_bw += L
                    if len(ex_aw) < 4:
                        ex_aw.append("bulge r=%.2fm 弧长%.2fm" % (r, L))
                elif L >= 0.2:
                    n_bg += 1
                    len_bg += L
    return name, (n_arc, len_arc, n_aw, len_aw, n_bg, len_bg, n_bw, len_bw, n_spline, ex_aw), None


names = sys.argv[1:] or sorted(
    os.path.basename(x) for x in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(x))
print("== 墙体层弧要素普查 (半径>=%.1fm 才算『曲墙』; 更小的是门扇开启弧) ==" % DOOR_ARC_R)
rows = []
for nm in names:
    r = census(nm)
    if r is None:
        continue
    name, data, err = r
    if err:
        print("%-7s %s" % (name, err))
        continue
    (n_arc, len_arc, n_aw, len_aw, n_bg, len_bg, n_bw, len_bw, n_sp, ex) = data
    rows.append((name, n_aw, len_aw, n_bw, len_bw, len_arc + len_bg, n_sp, ex))

print("\n%-7s %-16s %-16s %-12s %s" % ("楼", "曲墙ARC", "曲墙bulge", "门弧(参考)", "样例"))
for name, n_aw, len_aw, n_bw, len_bw, door, n_sp, ex in sorted(
        rows, key=lambda z: -(z[2] + z[4])):
    mark = "  <== 有曲墙" if (len_aw + len_bw) > 1.0 else ""
    print("%-7s %3d根/%-8.0fm %3d段/%-8.0fm %4.0fm  SPLINE=%d%s  %s"
          % (name, n_aw, len_aw, n_bw, len_bw, door, n_sp, mark, "; ".join(ex)[:56]))
tot = sum(1 for z in rows if (z[2] + z[4]) > 1.0)
print("\n有『真曲墙』的楼: %d 栋;  合计曲墙长度 %.0fm"
      % (tot, sum(z[2] + z[4] for z in rows)))
