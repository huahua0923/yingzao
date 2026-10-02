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

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "backend"))
from paths import DATA as _DATA_DIR  # noqa: E402
import gen_stamp  # noqa: E402

DATA = str(_DATA_DIR)
BUILD = os.path.join(DATA, "buildings")


def generated_of(name, base):
    """从生成时间账本读这栋楼的生成时间。

    账本由**生成方**写（`data/buildings/<name>/generated.json`，见 backend/gen_stamp.py），
    这里只读不算 —— 「清单是什么时候建的」和「模型是什么时候生成的」是两件事，
    拿前者冒充后者就是这个字段最容易犯的错。

    返回 `(head_at, head_source, parts)`：
      · `head_at` 头条取**模型**那一刻：GLB 优先，其次识别，再其次 SU 规格；
      · `head_source` 是那一刻的来源 —— `generator`（生成方当场盖）或
        `mtime-backfill`（从产物 mtime 推算的，**不是**生成时刻）；
      · 三者都缺 ⇒ `(None, None, {...全是 None})`，页面据此印「未记录」。
        ★ 不许兜底成今天：分母为 0 的 k/N 是最像结论的假数（铁律 60）。
    """
    led = gen_stamp.read(name, base)
    parts = {k: (led.get(k) or {}).get("at") for k in ("floors", "glb", "su")}
    for k in ("glb", "floors", "su"):
        c = led.get(k) or {}
        if c.get("at"):
            return c["at"], c.get("source"), parts
    return None, None, parts


def count_floors(d):
    n = 0
    while os.path.exists(os.path.join(d, "floors", f"floor{n}.json")):
        n += 1
    return n


def exported_floors(name, cfg, total):
    """模型里**实际导出**的层数 = 楼层文件数 − profile.skip_floors（c103 删了 6 层那种）。

    2026-09-16 加：全量进管线后清单要给 8123 用，页面按层号 fetch floorN.json，
    skip 掉的层不存在就该从层数里去掉，否则页面会去要一个没有的文件。
    """
    skip = {int(v) for v in (cfg.get("skip_floors") or [])}
    return len([i for i in range(total) if i not in skip])


def has_rooms(name):
    """该楼有没有**有效**房间数据 —— 新进的 46 栋还没做房间提取，
    它们的 `rooms.json` 是 `[]`（2 字节占位），别把空文件当成"有房间"。
    """
    p = os.path.join(BUILD, name, "rooms.json")
    if not os.path.isfile(p) or os.path.getsize(p) < 10:
        return False
    try:
        with open(p, encoding="utf-8") as f:
            return len(json.load(f) or []) > 0
    except Exception:                                              # noqa: BLE001
        return False


def room_count(name):
    p = os.path.join(BUILD, name, "rooms.json")
    try:
        with open(p, encoding="utf-8") as f:
            return len(json.load(f) or [])
    except Exception:                                              # noqa: BLE001
        return 0


entries = []

# 理化楼基线（整栋立体模型查看器的默认建筑，房间数据来自 lihua_twin.rooms）
lihua_floors = count_floors(DATA)
if lihua_floors:
    _a, _s, _p = generated_of("lihua", DATA)
    entries.append({
        "name": "lihua", "title": "理化楼（基线）",
        "floors": lihua_floors, "layer_height": 4.2, "dir": "data",
        "generated_at": _a, "generated_source": _s, "generated_parts": _p,
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
    _a, _s, _p = generated_of(name, os.path.join(BUILD, name))
    entries.append({
        "name": name, "title": cfg.get("title", name),
        "floors": exported_floors(name, cfg, floors),
        "floors_total": floors,
        "layer_height": float(cfg.get("layer_height", 4.2)),
        "dir": f"data/buildings/{name}",
        "rooms": has_rooms(name),
        "room_count": room_count(name),
        "glb": f"data/buildings/{name}/{name}-building.glb",
        "generated_at": _a, "generated_source": _s, "generated_parts": _p,
    })

out = os.path.join(BUILD, "index.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(entries, f, ensure_ascii=False, indent=1)
print(f"已生成 {out}：{len(entries)} 栋")
for e in entries:
    print(f"  {e['name']:6s} {e['floors']:2d}层  {e['title']}")
