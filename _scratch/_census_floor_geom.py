# -*- coding: utf-8 -*-
"""楼层数据几何普查：三角面暴涨到底是「墙变多」还是「单个多边形顶点爆炸」。

判据：
  · 墙多边形顶点数应在个位数~几十（双线配对成四边形，开洞后略多）
  · 若出现成百上千顶点的多边形 → 是融合块没解掉，几何有问题
  · 每层墙数应与图纸量级相符（几十~几百），不该上万
"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"


def stat(name):
    d = os.path.join(B, name, "floors")
    nw = nv = mx = 0
    nwin = ndoor = nroom = ncol = 0
    slabs = []
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json"))):
        fl = json.load(open(fp, encoding="utf-8"))
        for w in fl.get("walls") or []:
            nw += 1
            k = len(w.get("poly") or [])
            nv += k
            mx = max(mx, k)
        nwin += len(fl.get("windows") or [])
        ndoor += len(fl.get("doors") or [])
        nroom += len(fl.get("rooms") or [])
        ncol += len(fl.get("columns") or [])
        if fl.get("outline"):
            slabs.append(len(fl["outline"]))
    return nw, nv, mx, nwin, ndoor, nroom, ncol, slabs


print("%-6s %7s %6s %9s %8s %7s %6s %5s %s"
      % ("楼栋", "总墙数", "层数", "平均顶点", "最大顶点", "窗", "门", "房", "轮廓顶点"))
for name in ("c018", "c116", "c046", "c056", "c044", "c019", "c006"):
    d = os.path.join(B, name, "floors")
    if not os.path.isdir(d):
        continue
    nw, nv, mx, nwin, ndoor, nroom, ncol, slabs = stat(name)
    nf = len(slabs)
    print("%-6s %7d %6d %9.1f %8d %7d %6d %5d %s"
          % (name, nw, nf, (nv / nw if nw else 0), mx, nwin, ndoor, nroom,
             ("%d~%d" % (min(slabs), max(slabs))) if slabs else "-"))
