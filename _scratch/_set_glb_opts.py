# -*- coding: utf-8 -*-
"""把 GLB 导出档位写进 49 栋 profile.json：glb_windows=true（导出合成窗）。

只动这一个键，其余原样保留（读改写，indent=1 与原格式一致）。
先备份到 _scratch/_profile_before_win/，便于一键还原。
c009 的 skip_floors 不在本步设 —— 隔离风险，等批量跑完再单独动。
"""
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

B = r"D:\gym3d\data\buildings"
BK = r"D:\gym3d\_scratch\_profile_before_win"
os.makedirs(BK, exist_ok=True)

names = sorted(d for d in os.listdir(B) if os.path.isdir(os.path.join(B, d)))
changed = same = 0
for n in names:
    pj = os.path.join(B, n, "profile.json")
    if not os.path.exists(pj):
        print("!! 无档案:", n)
        continue
    with open(pj, encoding="utf-8") as f:
        cfg = json.load(f)
    shutil.copy2(pj, os.path.join(BK, n + ".profile.json"))

    before = cfg.get("glb_windows", None)
    if before is True:
        same += 1
        continue
    cfg["glb_windows"] = True
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    changed += 1

print("49 栋中：新写入 glb_windows=true %d 栋，本来就是 true %d 栋" % (changed, same))
print("档案备份 →", BK)
print("已设 skip_floors 的楼：",
      [n for n in names
       if json.load(open(os.path.join(B, n, "profile.json"), encoding="utf-8")).get("skip_floors")])
