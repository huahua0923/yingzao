# -*- coding: utf-8 -*-
"""楼梯井逐栋汇总(只读): 合理井(宽<=6m) vs 巨型井, 逐层。"""
import json, glob, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
MAXW = 6.0
for fd in sorted(glob.glob(r"data/buildings/*/floors")):
    name = os.path.basename(os.path.dirname(fd))
    sane = giant = 0
    floors = []
    for F in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        fl = json.load(open(F, encoding="utf-8"))
        s = g = 0
        for w in fl.get("stairwells", []):
            W = w["x1"] - w["x0"]
            if W > MAXW:
                g += 1
            else:
                s += 1
        sane += s
        giant += g
        fn = os.path.basename(F)[5:-5]
        floors.append("%s:(s%d/g%d)" % (fn, s, g))
    flag = " <== 有巨型井" if giant else ""
    print("%-6s 合理井=%2d 巨井=%2d 逐层=%s%s" % (name, sane, giant, ",".join(floors), flag))
