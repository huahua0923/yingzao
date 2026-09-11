# -*- coding: utf-8 -*-
"""R10 批执行: 29 栋面积门通过的宿舍/公寓 + c041 重生成。
每栋 .orig 备份 -> extract_rooms_generic.run(写 rooms.json) -> backfill_floors(注入 floor rooms[])。
只写这些楼, 全量 DB 重载由调用方随后单独跑。输出 _rooms_batch_write.txt。
"""
import sys, os, json, shutil
sys.path.insert(0, r"D:\gym3d")
sys.path.insert(0, r"D:\gym3d\backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from backend.extract import extract_rooms_generic as E
from backend.extract.backfill_floor_rooms import backfill_floors

DATA = "data/buildings"
PASS = ["c017","c018","c019","c029","c030","c032","c034","c043",
        "c054","c055","c056","c057","c059","c060","c061","c062",
        "c063","c064","c065","c072","c073","c079","c080","c083",
        "c084","c085","c086","c109","c116", "c041"]   # c041 46->47

report = []
for name in PASS:
    d = os.path.join(DATA, name)
    orig = os.path.join(d, ".orig")
    # 1) 备份 (仅首次)
    if not os.path.isdir(os.path.join(orig, "floors.before_rooms")):
        os.makedirs(orig, exist_ok=True)
        if os.path.isdir(os.path.join(d, "floors")):
            shutil.copytree(os.path.join(d, "floors"), os.path.join(orig, "floors.before_rooms"))
        if os.path.exists(os.path.join(d, "rooms.json")):
            shutil.copy(os.path.join(d, "rooms.json"), os.path.join(orig, "rooms.json.before_rooms"))
    # 2) 提取写 rooms.json
    try:
        rooms = E.run(name, dry=False)
        n_rooms = len(rooms)
    except Exception as ex:
        report.append(f"[{name}] 提取失败: {ex}")
        print(f"[{name}] 提取失败: {ex}")
        continue
    # 3) 回填 floor rooms[]
    added, byf = backfill_floors(name)
    report.append(f"[{name}] rooms.json={n_rooms} 回填={added} 逐层={byf}")
    print(f"[{name}] rooms.json={n_rooms} 回填={added} 逐层={byf}")

with open("_rooms_batch_write.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print("\n=== 完成, 明细 _rooms_batch_write.txt ===")
