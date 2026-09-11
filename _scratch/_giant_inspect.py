# -*- coding: utf-8 -*-
"""c026 F0 / c018 F0 / c034 F1 巨墙取证(只读): 巨墙与 outline 关系、墙类型构成。"""
import sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon

for name, F in [("c026", 0), ("c018", 0), ("c034", 1)]:
    fp = r"D:\gym3d\data\buildings\%s\floors\floor%d.json" % (name, F)
    fl = json.load(open(fp, encoding="utf-8"))
    ol = Polygon(fl["outline"])
    print("==== %s F%d  outline=%.1fm²  walls=%d  doors=%d rooms=%d" %
          (name, F, ol.area, len(fl["walls"]), len(fl.get("doors", [])), len(fl.get("rooms", []))))
    from collections import Counter
    print("  类型构成:", dict(Counter(w["type"] for w in fl["walls"])))
    for w in fl["walls"]:
        try:
            P = Polygon(w["poly"])
            a = P.area
        except Exception:
            a = 0
        if a > 0.10 * ol.area:
            sim = 100 * a / ol.area
            # 是否接近 outline 环(=整层外框)?
            print("  大墙[%s] %dm² = %.0f%% outline | holes=%d | thickness=%s" %
                  (w["type"], round(a), sim, len(w.get("holes", [])), w.get("thickness")))
