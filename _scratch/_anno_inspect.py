# -*- coding: utf-8 -*-
"""扫楼 DXF 各图层：类型计数 + TEXT/MTEXT 样例，定位 单位/面积/用途/房间号/Defpoints 等标注图层。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend\vision",
                r"D:\gym3d\backend", r"D:\gym3d"]
import ezdxf, run_step
BASE = r"D:\gym3d\data\buildings"
names = sys.argv[1:] or ["c019", "c025", "c041"]
for name in names:
    try:
        p = run_step.load_profile(name)
        doc = ezdxf.readfile(p.dxf)
    except Exception as e:
        print(name, "ERR", e); continue
    from collections import Counter
    per = {}
    for e in doc.modelspace():
        t = e.dxftype()
        lay = e.dxf.layer if hasattr(e.dxf, "layer") else "?"
        per.setdefault(lay, Counter())[t] += 1
    print("\n=====", name, "=====")
    for lay in sorted(per):
        ts = dict(per[lay])
        txt = ts.get("TEXT", 0) + ts.get("MTEXT", 0)
        flag = "  <<<ANNO" if txt > 0 else ""
        print(f"  {lay:28s} {ts!r}{flag}")
