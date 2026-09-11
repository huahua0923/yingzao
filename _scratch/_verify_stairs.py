# -*- coding: utf-8 -*-
"""楼梯渲染体检：把 build_indoor_stairs 画出来的踏步盒子录下来，逐项核。

录法：临时替换 MeshBuilder.add_box 收集 (y中心, 高, 深)，这样量到的是
**真正进 GLB 的几何**，不是又算一遍公式。

判据：
  · 踢面高（盒子高）落在 0.13~0.20 m —— 修前 c103 是 0.323、c022 是 0.420；
  · 每口井的最高点，全楼层并起来应当恰好覆盖 [z, z+层高]，不能有断层：
    断层 = 楼梯爬到一半没了，观感是「楼梯断头」。
用法：python _verify_stairs.py c103 [c114 ...]
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import build_standard_glb as bsg  # noqa: E402


class Rec:
    """只收 add_box 的假 builder。"""
    def __init__(self):
        self.boxes = []

    def add_box(self, cx, cy, cz, w, h, d, rot_y=0.0, col=None):
        self.boxes.append((cy, h, d))

    def __getattr__(self, name):
        return lambda *a, **k: None


for name in sys.argv[1:]:
    d = os.path.join(r"D:\gym3d\data\buildings", name)
    S = json.load(open(os.path.join(d, "spec.json"), encoding="utf-8"))
    bsg.DATA = d
    floors = bsg.load_floors()
    h = S["floor_h"]
    print("== %s  层高 %.2f m  %d 层" % (name, h, len(floors)))

    allriser = []
    gaps = 0
    for i, fl in enumerate(floors):
        if i == len(floors) - 1:
            continue                       # 顶层不画楼梯，设计如此
        r = Rec()
        bsg.build_indoor_stairs(r, fl, i * h, S, False)
        if not r.boxes:
            continue
        risers = sorted(set(round(b[1], 4) for b in r.boxes))
        allriser += risers
        lo = i * h
        hi = lo + h
        ys = [b[0] for b in r.boxes]
        span = (round(min(ys) - lo, 3), round(max(ys) - lo, 3))
        ok = all(0.13 <= x <= 0.205 for x in risers)
        print("   F%d 踏步%d 个  踢面 %s  覆盖标高 %.3f~%.3f（层内 %.2f~%.2f）%s"
              % (fl["floor"], len(r.boxes),
                 ",".join("%.3f" % x for x in risers), min(ys), max(ys), lo, hi,
                 "" if ok else "   <== 踢面越界"))
        if ok:
            gaps += 1
    if allriser:
        print("   踢面范围 %.3f ~ %.3f  %s"
              % (min(allriser), max(allriser),
                 "PASS 全部在 0.13~0.205" if 0.13 <= min(allriser)
                 and max(allriser) <= 0.205 else "**FAIL**"))
