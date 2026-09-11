# -*- coding: utf-8 -*-
"""墙层上「超长实体」普查(只读): _in_x_range 只看 X 包围盒中心, 一条横跨整张图的
图框/轴线只要中心落进 x_range 就会被当墙收下, 两端远端几何一起进模型。
本探针列出墙层上 X 或 Y 跨度 > THR 的实体, 报类型/跨度/中心落在哪层。

用法: python _probe_long_ents.py c006 [c009]
"""
import sys, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from run_building import load_profile
from backend.recognizer.profile import floor_of, in_floor_x_range

THR = 60000.0   # 跨度阈值(mm) = 60m

for nm in (sys.argv[1:] or ["c006"]):
    p = load_profile(nm)
    doc = ezdxf.readfile(p.dxf)
    rows = []
    skipped_out = 0
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
                continue
        except Exception:  # noqa: BLE001
            continue
        if not xs:
            continue
        cxm = (min(xs) + max(xs)) / 2.0
        cym = (min(ys) + max(ys)) / 2.0
        sx, sy = max(xs) - min(xs), max(ys) - min(ys)
        if sx < THR and sy < THR:
            continue
        if not in_floor_x_range(p, cxm):
            skipped_out += 1
            continue
        rows.append((sy, sx, t, cxm, cym, int(round(floor_of(p, cxm, cym)))))
    print("\n===== %s  墙层超长实体(>%.0fm) =====" % (nm, THR / 1000))
    print("  被 x_range 挡掉 %d 条; 收下 %d 条" % (skipped_out, len(rows)))
    byF = collections.Counter(r[5] for r in rows)
    print("  按层: %s" % dict(sorted(byF.items())))
    for (sy, sx, t, cxm, cym, F) in sorted(rows, key=lambda r: -(r[0] + r[1]))[:12]:
        print("    层%-3d %-11s X跨%7.1fm Y跨%7.1fm 中心(%.0f,%.0f)m"
              % (F, t, sx / 1000, sy / 1000, cxm / 1000, cym / 1000))
