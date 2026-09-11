# -*- coding: utf-8 -*-
"""c041 房间层号重映射: rooms.json 与各层 floor*.json 的 rooms[] 里 floor 由「倒置」改正。

真实层号 FF 来自房间号 XX-FF-NN(图纸权威) -> 模型层索引 floor = FF-1。
(等价于旧的 5-floor, 但按号码推导, 号码缺失的条目才退回反转。)

用法: python _c041_remap_rooms.py [--dry]
"""
import os, sys, json, glob, shutil, re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
NAME = "c041"
D = os.path.join(r"D:\gym3d\data\buildings", NAME)
DRY = "--dry" in sys.argv
N = len(sorted(glob.glob(os.path.join(D, "floors", "floor*.json"))))
RP = os.path.join(D, "rooms.json")


def new_floor(entry):
    m = re.match(r"^\s*\d+-(\d+)", str(entry.get("number") or ""))
    if m:
        ff = int(m.group(1))
        if 1 <= ff <= N:
            return ff - 1
    f = entry.get("floor")
    return (N - 1 - f) if isinstance(f, int) and 0 <= f < N else f


# 备份
if not DRY:
    bak = os.path.join(D, ".orig", "rooms.json.before_floorflip")
    if not os.path.exists(bak):
        shutil.copy2(RP, bak)

rs = json.load(open(RP, encoding="utf-8"))
chg = 0
for r in rs:
    nf = new_floor(r)
    if nf != r.get("floor"):
        r["floor"] = nf
        chg += 1
print("rooms.json: %d 条, floor 改写 %d 条" % (len(rs), chg))
import collections
print("  新 floor 分布:", dict(sorted(collections.Counter(r["floor"] for r in rs).items())))
if not DRY:
    json.dump(rs, open(RP, "w", encoding="utf-8"), ensure_ascii=False)

# 各层内嵌 rooms[] (若带 floor 字段)
for fp in sorted(glob.glob(os.path.join(D, "floors", "floor*.json"))):
    fl = json.load(open(fp, encoding="utf-8"))
    if not fl.get("rooms"):
        continue
    F = int(os.path.basename(fp)[5:-5])
    n = 0
    for r in fl["rooms"]:
        if "floor" in r and r["floor"] != F:
            r["floor"] = F
            n += 1
    if n and not DRY:
        json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    if n:
        print("  %s 内嵌 rooms[] floor 改写 %d 条" % (os.path.basename(fp), n))
print("DRY-RUN" if DRY else "已写盘")
