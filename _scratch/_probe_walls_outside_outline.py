# -*- coding: utf-8 -*-
"""交付模型自洽性: 有多少「交付墙」落在「交付轮廓」之外(只读)。

墙面积占比高 = 轮廓没盖住真墙(楼板缺覆盖, 墙悬空); 接近 0 = 轮廓与墙自洽。
这是个通用不变量, 可并入 qa_structural。

用法: python _probe_walls_outside_outline.py [c006 c009 ...]
"""
import sys, os, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

from shapely.geometry import Polygon
from shapely.prepared import prep

ROOT = r"D:\gym3d\data\buildings"


def report(nm, only=None):
    d = os.path.join(ROOT, nm, "floors")
    if not os.path.isdir(d):
        print("  %s: 无 floors" % nm)
        return
    print("===== %s =====" % nm)
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json")),
                     key=lambda s: int(os.path.basename(s)[5:-5])):
        F = int(os.path.basename(fp)[5:-5])
        if only and F not in only:
            continue
        fl = json.load(open(fp, encoding="utf-8"))
        o = fl.get("outline") or []
        if len(o) < 3:
            print("  层%-3d 无轮廓" % F)
            continue
        O = Polygon(o)
        if not O.is_valid:
            O = O.buffer(0)
        # 必须用「面积差」而不是「质心是否在轮廓内」: 环状外墙(足迹+室内洞)的质心
        # 天然落在自己的洞里, 用质心判会把每一层的整圈外墙都误报成「轮廓外」。
        Ob = O.buffer(0.01)
        Op = prep(Ob)
        tot = out = 0.0
        nout = 0
        for w in fl.get("walls", []):
            try:
                G = Polygon(w["poly"], w.get("holes") or [])
            except Exception:  # noqa: BLE001
                continue
            if G.is_empty:
                continue
            if not G.is_valid:
                # 自交/退化环会让 GEOS intersection 直接抛 TopologyException 中断整轮扫描
                G = G.buffer(0)
            if G.is_empty:
                continue
            a = G.area
            tot += a
            if Op.contains(G.representative_point()):
                outsider = max(0.0, a - G.intersection(Ob).area)
            else:
                outsider = a
            if outsider > 0.05 * a:
                nout += 1
            out += outsider
        pct = (100.0 * out / tot) if tot else 0.0
        flag = "  <== 轮廓没盖住墙" if pct > 5.0 else ""
        print("  层%-3d 墙%4d 墙面积%8.1f ㎡  轮廓外 %3d 条 %7.1f ㎡ = %5.1f%%%s"
              % (F, len(fl.get("walls", [])), tot, nout, out, pct, flag))
        if pct > 5.0:
            ox0, oy0, ox1, oy1 = O.bounds
            print("       轮廓 bbox X[%.1f,%.1f] Y[%.1f,%.1f] 面积%.1f㎡ 顶点%d"
                  % (ox0, ox1, oy0, oy1, O.area, len(o)))
            det = []
            for w in fl.get("walls", []):
                try:
                    G = Polygon(w["poly"], w.get("holes") or [])
                except Exception:  # noqa: BLE001
                    continue
                if G.is_empty:
                    continue
                if not G.is_valid:
                    G = G.buffer(0)
                if G.is_empty:
                    continue
                if Op.contains(G.representative_point()):
                    outsider = max(0.0, G.area - G.intersection(Ob).area)
                else:
                    outsider = G.area
                if outsider > 0.05 * G.area:
                    c = G.centroid
                    det.append((outsider, w.get("type", "?"), G.area, c.x, c.y))
            for (o_a, ty, ga, cx, cy) in sorted(det, reverse=True)[:8]:
                print("         在外 %6.1f㎡ (共%6.1f㎡) %-5s 质心(%.1f,%.1f)"
                      % (o_a, ga, ty, cx, cy))


for nm in (sys.argv[1:] or ["c006", "c009", "c103", "c104"]):
    report(nm.strip())
