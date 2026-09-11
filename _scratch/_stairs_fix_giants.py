# -*- coding: utf-8 -*-
"""R11 楼梯井清理: 移除"占楼宽>=40%"的走廊级假井(跨整栋的误判)。

受影响: c017 / c046 / c054 / c055 / c109
规则: 井宽 W = x1-x0; 若 W >= 0.40*outline_x_span 且 W>=8.0 -> 走廊墙链误判, 移除。
对照组(真楼梯井, <=8m, 楼宽占比<=14%, 跨层一致) 不碰:
   c026/c043/c056/c057/c072/c073/ny27-29/c018/c019/c031/c032/c033 ...
冻结楼(c006/c009/c103/c104)不在此列。
写前 .orig 备份整层目录。仅改 stairwells 键, 墙/房/柱/窗不动。
"""
import json, glob, os, sys, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FIX = ["c017", "c046", "c054", "c055", "c109"]
SHARE = 0.40
for name in FIX:
    fd = r"D:\gym3d\data\buildings\%s\floors" % name
    if not os.path.isdir(fd):
        print("%s: 无 floors 目录, 跳过" % name); continue
    # 备份
    bak = r"D:\gym3d\data\buildings\%s\.orig\floors.before_stairclean" % name
    os.makedirs(bak, exist_ok=True)
    tot_rm = tot_keep = 0
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        F = os.path.basename(fp)[5:-5]
        fl = json.load(open(fp, encoding="utf-8"))
        ox = max(p[0] for p in fl["outline"]) - min(p[0] for p in fl["outline"])
        if not os.path.exists(os.path.join(bak, os.path.basename(fp))):
            shutil.copy2(fp, os.path.join(bak, os.path.basename(fp)))
        keep, rm = [], []
        for w in fl.get("stairwells", []):
            W = w["x1"] - w["x0"]
            (rm if (W >= SHARE * ox and W >= 8.0) else keep).append(w)
        if rm:
            fl["stairwells"] = keep
            json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        tot_rm += len(rm); tot_keep += len(keep)
        if rm:
            print("%s F%-2s 移除走廊级井 %d 个 (保留 %d):" % (name, F, len(rm), len(keep)))
            for w in rm:
                print("      x%.1f-%.1f y%.1f-%.1f W%.1f (%.0f%%楼宽)" % (
                    w["x0"], w["x1"], w["yBot"], w["yTop"], w["x1"] - w["x0"], 100 * (w["x1"] - w["x0"]) / ox))
    print("%s 共移除 %d 假井, 保留 %d; 备份 -> %s" % (name, tot_rm, tot_keep, bak))
