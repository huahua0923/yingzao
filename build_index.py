# -*- coding: utf-8 -*-
"""生成 data/buildings/index.json —— 建筑清单（网页选择器消费）。

扫描 data/buildings/*/profile.json，汇总每栋楼的中文名、楼层数、层高、数据目录；
并在最前插入理化楼基线（data/，房间数据来自 lihua_twin）。前端 building.html fetch 本清单渲染下拉框。

用法: python build_index.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = r"D:\gym3d\data"
BUILD = os.path.join(DATA, "buildings")


def count_floors(d):
    n = 0
    while os.path.exists(os.path.join(d, "floors", f"floor{n}.json")):
        n += 1
    return n


entries = []

# 理化楼基线（整栋立体模型查看器的默认建筑，房间数据来自 lihua_twin.rooms）
lihua_floors = count_floors(DATA)
if lihua_floors:
    entries.append({
        "name": "lihua", "title": "理化楼（基线）",
        "floors": lihua_floors, "layer_height": 4.2, "dir": "data",
    })

for name in sorted(os.listdir(BUILD)):
    prof = os.path.join(BUILD, name, "profile.json")
    if not os.path.isfile(prof):
        continue
    with open(prof, encoding="utf-8") as f:
        cfg = json.load(f)
    floors = count_floors(os.path.join(BUILD, name))
    if floors == 0:
        continue
    entries.append({
        "name": name, "title": cfg.get("title", name),
        "floors": floors, "layer_height": float(cfg.get("layer_height", 4.2)),
        "dir": f"data/buildings/{name}",
    })

out = os.path.join(BUILD, "index.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(entries, f, ensure_ascii=False, indent=1)
print(f"已生成 {out}：{len(entries)} 栋")
for e in entries:
    print(f"  {e['name']:6s} {e['floors']:2d}层  {e['title']}")
