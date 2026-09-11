# -*- coding: utf-8 -*-
"""按 _scratch/_MANIFEST*.json 把归档文件全部还原回原位。默认干跑，--apply 真移。

覆盖三批：_MANIFEST.json(根脚本) / _MANIFEST_DEBRIS.json(根碎片) / _MANIFEST_DEBRIS2.json(data·backend碎片)
"""
import os, sys, json, glob, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
D = os.path.dirname(os.path.abspath(__file__))
ap = "--apply" in sys.argv
tot = done = miss = 0
for mf in sorted(glob.glob(os.path.join(D, "_MANIFEST*.json"))):
    M = json.load(open(mf, encoding="utf-8"))
    items = M.get("moved", [])
    print("\n== %s (%d) ==" % (os.path.basename(mf), len(items)))
    for it in items:
        tot += 1
        if not os.path.exists(it["dst"]):
            print("  缺失: %s" % it["name"]); miss += 1; continue
        if os.path.exists(it["src"]):
            print("  已存在(不覆盖): %s" % it["name"]); continue
        if ap:
            os.makedirs(os.path.dirname(it["src"]), exist_ok=True)
            shutil.move(it["dst"], it["src"]); done += 1
print("\n%s %d / %d（缺失 %d）" % ("已还原" if ap else "待还原", done if ap else tot - miss, tot, miss))
