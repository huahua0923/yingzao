# -*- coding: utf-8 -*-
"""探针：逐栋打印每层墙在 DXF 里的 X/Y 范围，判断楼层排布类型。

类型判定：
  - 所有层 X 范围一致、Y 均匀 → uniform（正常，对齐问题多半是上层轮廓碎片化 → outline_unify）
  - F0 X 明显宽/窄于上层 → 首层裙楼/塔楼（阶梯楼）
  - 某层 X 跨两段（另一副本） → 多副本，需 narrow x_range
用法: python _probe_layout.py c079 c083 ...
"""
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend")

import ezdxf
from recognizer.classify import classify
from recognizer.classify_line import classify_line
from recognizer.profile import floor_of
from run_building import load_profile


def probe(name):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    if getattr(p, "classifier", "lwpolyline") == "line":
        walls, _, _, _ = classify_line(msp, p)
    else:
        walls, _, _, _ = classify(msp, p)
    per = defaultdict(list)
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        per[floor_of(p, cx, cy)].append((cx, cy))
    out = []
    for f in sorted(per):
        xs = [q[0] for q in per[f]]
        ys = [q[1] for q in per[f]]
        out.append((f, min(xs), max(xs), min(ys), max(ys), len(per[f])))
    return out


if __name__ == "__main__":
    for name in sys.argv[1:]:
        try:
            r = probe(name)
            # 判类型
            xs_uniq = sorted(set((a, b) for _, a, b, _, _, _ in r))
            widths = [b - a for _, a, b, _, _, _ in r]
            print("=== %s  层数=%d  X宽=%s" % (name, len(r), "/".join("%.0f" % w for w in widths)))
            for f, x0, x1, y0, y1, n in r:
                print("   F%d: X[%d..%d] w=%.0f  Y[%d..%d] h=%.0f  墙=%d" % (f, x0, x1, x1 - x0, y0, y1, y1 - y0, n))
        except Exception as e:
            print("=== %s ERR %s: %s" % (name, type(e).__name__, e))
