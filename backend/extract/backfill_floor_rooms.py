# -*- coding: utf-8 -*-
"""把 rooms.json 回填进 floors/floor*.json 的 rooms[]（房间点击几何），不重识别。

机理：recognize() 在 extract_floor 里读 p.rooms 生成本层 rooms_json（见 floor.py 房间段：
对每间 rooms_data 中 floor==F 且 outline.contains(质心) 的房间，写 {id,poly,purpose,number}）。
当 rooms.json 是在 floor JSON 生成**之后**才补齐（如宿舍公寓簇此前 rooms.json=[]），
floor JSON 的 rooms[] 仍是空 → 3D 查看器点不到房间。本脚本对既有楼层文件做同样的
注入，**不动 walls/outline/windows/doors**，避免重识别带来的墙漂移。

用法:
  python backend/extract/backfill_floor_rooms.py c031            # 回填并写回
  python backend/extract/backfill_floor_rooms.py c031 --verify   # 只打印将注入数, 不写
  python backend/extract/backfill_floor_rooms.py c031 --floors-dir .orig/floors.before_rooms  # 指定楼层目录(验证用)
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon, Point

DATA = r"D:\gym3d\data\buildings"


def backfill_floors(name, floors_dir=None, verify=False):
    """把某楼 rooms.json 回填进 floors/*.json 的 rooms[]。返回 (回填数, 逐层 dict)。
    floors_dir 默认 <楼>/floors；verify=True 只统计不写。"""
    d = os.path.join(DATA, name)
    fd = floors_dir or os.path.join(d, "floors")
    rp = os.path.join(d, "rooms.json")
    if not os.path.exists(rp):
        return 0, {}
    rooms = json.load(open(rp, encoding="utf-8"))
    if not rooms:
        return 0, {}
    total_add = 0
    by_floor = {}
    for F in sorted({r.get("floor") for r in rooms if "floor" in r}):
        fp = os.path.join(fd, f"floor{F}.json")
        if not os.path.exists(fp):
            continue
        fl = json.load(open(fp, encoding="utf-8"))
        o = Polygon(fl["outline"])
        existing = {(r.get("number"), r.get("purpose")) for r in fl.get("rooms", [])}
        add = []
        for r in rooms:
            if r.get("floor") != F or "boundary" not in r:
                continue
            b = r["boundary"]
            if len(b) < 3:
                continue
            p = Polygon(b).buffer(0)
            if p.is_empty or not p.is_valid or not o.contains(p.centroid):
                continue
            key = (r.get("number"), r.get("purpose"))
            if key in existing:
                continue
            add.append({
                "id": r.get("id"),
                "poly": [[round(x, 2), round(y, 2)] for x, y in b],
                "purpose": r.get("purpose") or "",
                "number": r.get("number") or "",
            })
        if add:
            fl["rooms"] = fl.get("rooms", []) + add
            if not verify:
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(fl, f, ensure_ascii=False)
            by_floor[F] = len(add)
            total_add += len(add)
    return total_add, by_floor


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name = args[0] if args else None
    if not name:
        print("用法: backfill_floor_rooms.py <楼> [--verify] [--floors-dir DIR]")
        return 1
    verify = "--verify" in sys.argv
    d = os.path.join(DATA, name)
    fd = os.path.join(d, "floors")
    for a in sys.argv[1:]:
        if a.startswith("--floors-dir="):
            fd = os.path.join(d, a.split("=", 1)[1])
    total_add, by_floor = backfill_floors(name, floors_dir=fd, verify=verify)
    print(f"[{name}] 回填 {total_add} 间 (逐层 {by_floor})  "
          + ("(模拟, 未写)" if verify else "(已写)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
