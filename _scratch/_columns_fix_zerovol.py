# -*- coding: utf-8 -*-
"""R11 空柱子修复: 移除零体积柱(w 或 d <= 0.001 -> BoxGeometry 体积=0 渲染不可见=空柱子)。

全 48 栋扫描结果: 仅 c044 存在(7 根: F0-F6 各 1 根 w=0.6,d=0.0)。
冻结楼 c006/c009/c103/c104 不在此列。
写前 .orig 备份整层目录; 仅改 columns 键, 墙/房/窗/门/楼梯不动。
"""
import json, glob, os, shutil, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ALL = sorted(os.listdir(r"D:\gym3d\data\buildings"))
FROZEN = {"c006", "c009", "c103", "c104"}

total_removed = 0
buildings_touched = []
for name in ALL:
    fd = r"D:\gym3d\data\buildings\%s\floors" % name
    if not os.path.isdir(fd):
        continue
    if name in FROZEN:
        continue
    bak = r"D:\gym3d\data\buildings\%s\.orig\floors.before_zerovol_fix" % name
    removed = 0
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        F = os.path.basename(fp)[5:-5]
        fl = json.load(open(fp, encoding="utf-8"))
        cols = fl.get("columns", [])
        keep, rm = [], []
        for c in cols:
            w = c.get("w", 0) or 0
            d = c.get("d", 0) or 0
            (rm if (w <= 0.001 or d <= 0.001) else keep).append(c)
        if rm:
            os.makedirs(bak, exist_ok=True)
            if not os.path.exists(os.path.join(bak, os.path.basename(fp))):
                shutil.copy2(fp, os.path.join(bak, os.path.basename(fp)))
            fl["columns"] = keep
            json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
            removed += len(rm)
    if removed:
        buildings_touched.append((name, removed))
        total_removed += removed

for name, n in buildings_touched:
    print("%s: 移除零体积柱 %d 根" % (name, n))
print("合计移除 %d 根; 冻结楼未动; 备份在 .orig/floors.before_zerovol_fix/" % total_removed)
