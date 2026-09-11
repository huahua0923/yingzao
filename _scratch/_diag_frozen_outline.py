# -*- coding: utf-8 -*-
# 已套X区间裁剪(与 classify._in_x_range 同口径)
"""冻结4栋「弧墙缺口是轮廓驱动」的根因诊断(只读, 不写任何文件)。

背景: c006/c009/c103/c104 的墙层弧墙有大量采样点落在**交付 outline 之外**
(c009 1111m / c006 522m / c104 164m / c103 40m)。轮廓外 = 模型里根本没有那块,
再怎么改配对也盖不住。先把「轮廓为什么盖不住墙」量化出来。

三件事:
 A. 逐层对比 **墙层实际内容的包围盒/面积** vs **交付 outline 的包围盒/面积**
    —— 交付轮廓明显小于墙内容 = 轮廓过窄(冻结/统一过头), 这是主嫌。
 B. 逐层列出弧墙在域外的长度与**越界距离**(中位/最大), 越界越远越可能是轮廓塌陷。
 C. 交付轮廓跨层是否被**统一**了(逐层几何哈希), 以及层数/floor_ys 是否与图纸一致。

用法: python _diag_frozen_outline.py [c006 c009 c103 c104]
"""
import sys, os, json, glob, math, hashlib
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from shapely.geometry import Polygon, Point, MultiPoint
from shapely.ops import unary_union
from shapely.prepared import prep

from run_building import load_profile
from backend.recognizer.profile import floor_of, to_local, in_floor_x_range

ROOT = r"D:\gym3d\data\buildings"


def _ent_cx(e):
    """实体 X 包围盒中心(mm); 取不到返回 None。与 classify._in_x_range 同口径。"""
    t = e.dxftype()
    try:
        if t == "LINE":
            xs = [float(e.dxf.start.x), float(e.dxf.end.x)]
        elif t == "ARC":
            xs = [float(q[0]) for q in e.flattening(50.0)]
        elif t == "LWPOLYLINE":
            xs = [float(q[0]) for q in e.get_points("xyseb")]
        elif t == "POLYLINE":
            xs = [float(v.dxf.location.x) for v in e.vertices]
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    return (min(xs) + max(xs)) / 2.0 if xs else None


def wall_content_points(p):
    """墙层全部实体的采样点(mm)。返回 [(x, y)]。

    弧用 1mm 离散(不依赖 flattening 的 segments=4 下限), 直段只取端点。
    """
    from ezdxf.path import make_path
    out = []
    doc = ezdxf.readfile(p.dxf)
    for e in doc.modelspace():
        if e.dxf.layer != p.wall_layer:
            continue
        _cx = _ent_cx(e)
        if _cx is not None and not in_floor_x_range(p, _cx):
            continue          # 与 classify._in_x_range 同口径
        t = e.dxftype()
        try:
            if t == "LINE":
                out.append((float(e.dxf.start.x), float(e.dxf.start.y)))
                out.append((float(e.dxf.end.x), float(e.dxf.end.y)))
            elif t == "ARC":
                for q in e.flattening(50.0):
                    out.append((float(q[0]), float(q[1])))
            elif t == "LWPOLYLINE":
                pts = list(e.get_points("xyseb"))
                has_bulge = any(len(q) > 4 and abs(q[4]) > 1e-9 for q in pts)
                if has_bulge:
                    for q in make_path(e).flattening(50.0):
                        out.append((float(q.x), float(q.y)))
                else:
                    for q in pts:
                        out.append((float(q[0]), float(q[1])))
            elif t == "POLYLINE":
                for v in e.vertices:
                    out.append((float(v.dxf.location.x), float(v.dxf.location.y)))
        except Exception:  # noqa: BLE001
            continue
    return out


def load_floors(name, fdir=None):
    fdir = fdir or os.path.join(ROOT, name, "floors")
    fl = {}
    for fp in sorted(glob.glob(os.path.join(fdir, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl[F] = json.load(open(fp, encoding="utf-8"))
    return fl


def outline_of(fl):
    o = fl.get("outline")
    if not o or len(o) < 3:
        return None
    P = Polygon(o)
    if P.is_empty or not P.is_valid:
        P = P.buffer(0)
    return None if P.is_empty else P


def diag(name):
    from _curve_delivered_check import curve_points_mm
    p = load_profile(name)
    fl = load_floors(name)
    if not fl:
        print("%s: 无楼层 JSON" % name)
        return
    arcs, _other = curve_points_mm(p)
    cpts = wall_content_points(p)

    # 逐层: 墙内容点 bbox/面积(用 0.3m 缓冲并集当粗包络), 交付 outline bbox/面积
    print("\n===== %s (墙层 %r) =====" % (name, p.wall_layer))
    per = {}
    orphan = 0
    for (x, y) in cpts:
        try:
            F = int(round(floor_of(p, x, y)))
        except Exception:  # noqa: BLE001
            orphan += 1
            continue
        per.setdefault(F, []).append((x, y))
    print("  墙层点数 %d, 未定位 %d; 定位到 %d 层" % (len(cpts), orphan, len(per)))
    print("  %-4s %-28s %-28s %s" % ("层", "墙内容 bbox(m, 本地)", "交付outline bbox(m)", "判定"))
    for F in sorted(set(per) | set(fl)):
        pts = per.get(F, [])
        if pts:
            LX = [to_local(p, x, y, F) for (x, y) in pts]
            cw = max(a for a, _ in LX) - min(a for a, _ in LX)
            ch = max(b for _, b in LX) - min(b for _, b in LX)
            cb = (min(a for a, _ in LX), min(b for _, b in LX), cw, ch)
        else:
            cb = None
        O = outline_of(fl[F]) if F in fl else None
        if O is not None:
            ox0, oy0, ox1, oy1 = O.bounds
            ob = (ox0, oy0, ox1 - ox0, oy1 - oy0)
        else:
            ob = None
        if cb and ob:
            dw = ob[2] - cb[2]
            dh = ob[3] - cb[3]
            tag = "轮廓小 %.1f x %.1f m" % (-dw, -dh) if dw < -0.5 or dh < -0.5 else \
                  ("轮廓大 %.1f x %.1f m" % (dw, dh) if dw > 2.0 or dh > 2.0 else "吻合")
        else:
            tag = "缺数据"
        f1 = ("宽%.1f x 高%.1f @(%.1f,%.1f)" % (cb[2], cb[3], cb[0], cb[1])) if cb else "-"
        f2 = ("宽%.1f x 高%.1f @(%.1f,%.1f)" % (ob[2], ob[3], ob[0], ob[1])) if ob else "-"
        print("  %-4d %-28s %-28s %s" % (F, f1, f2, tag))

    # 交付轮廓是否被跨层统一
    sig = {}
    for F in sorted(fl):
        O = outline_of(fl[F])
        if O is None:
            continue
        h = hashlib.md5(("%.3f|%.0f|%.0f|%.0f|%.0f" % (O.area, *O.bounds)).encode()).hexdigest()[:8]
        sig.setdefault(h, []).append(F)
    dup = {h: v for h, v in sig.items() if len(v) > 1}
    print("  交付轮廓几何: %d 个互异; 被复用的: %s"
          % (len(sig), ", ".join("层%s 同一轮廓" % v for v in dup.values()) or "无"))
    for F in sorted(fl):
        O = outline_of(fl[F])
        if O is not None:
            print("      层%-3d 轮廓 顶点%-4d 面积%8.1f㎡ %d洞"
                  % (F, len(fl[F]["outline"]), O.area, len(fl[F].get("outline_holes") or [])))

    # 弧墙域外长度 + 越界距离
    print("  -- 弧墙域外明细 --")
    outs = {}
    for (x, y, d) in arcs:
        try:
            F = int(round(floor_of(p, x, y)))
        except Exception:  # noqa: BLE001
            continue
        if F not in fl:
            continue
        O = outline_of(fl[F])
        if O is None:
            continue
        lx, ly = to_local(p, x, y, F)
        pt = Point(lx, ly)
        if O.contains(pt):
            continue
        dist = O.boundary.distance(pt)
        k = outs.setdefault(F, [0.0, 0.0, 0.0])   # [域外长度, 中位距离(累加用), 最大距离]
        k[0] += d
        k[1] += d * dist
        k[2] = max(k[2], dist)
    if not outs:
        print("     无(全部弧点都在交付轮廓内)")
    for F in sorted(outs, key=lambda f: -outs[f][0]):
        L, wsum, dmax = outs[F]
        print("     层%-3d 域外 %7.1fm  平均越界 %5.2fm  最远 %5.2fm"
              % (F, L / 1000.0, (wsum / L) if L else 0.0, dmax))
    print("     （越界距离大 = 轮廓塌陷/缺翼; 越界距离小(~0.2m) = 仅轮廓缓冲差, 属正常）")


def main():
    for nm in (sys.argv[1:] or ["c006", "c009", "c103", "c104"]):
        diag(nm.strip())


if __name__ == "__main__":
    main()
