# -*- coding: utf-8 -*-
"""受影响楼栋 wall 形态(只读): floor JSON 内墙段数/外墙段数 + rooms。"""
import json, glob, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
AFFECT = ["c017","c026","c043","c044","c045","c046","c054","c055","c056","c057",
          "c072","c073","c079","c080","c083","c084","c085","c086","c109",
          "ny27","ny28","ny29"]
for name in AFFECT:
    fd = r"data/buildings/%s/floors" % name
    if not os.path.isdir(fd):
        continue
    for F in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        fl = json.load(open(F, encoding="utf-8"))
        out = sum(1 for w in fl["walls"] if w["type"] == "outer")
        inn = sum(1 for w in fl["walls"] if w["type"] == "inner")
        # 最大内墙poly是否带房洞(hole)
        holewall = 0
        for w in fl["walls"]:
            if w["type"] == "inner" and (w.get("holes") or []):
                holewall += 1
        print("%s F%-2s 外墙=%d 内墙=%d 内墙带洞=%d 房=%d 井=%d" % (
            name, os.path.basename(F)[5:-5], out, inn, holewall,
            len(fl.get("rooms", [])), len(fl.get("stairwells", []))))
        break  # 只看F0
