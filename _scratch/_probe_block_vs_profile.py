# -*- coding: utf-8 -*-
"""现存 profile.json 里的 cx，究竟等于哪一块？还是两块的中点？

用来判断「拒绝猜」是否过火：
  - 若多数 = 某一块的 cx → 人工当时就是选块，拒绝猜正确
  - 若 = 两块中点      → 说明中点也能用，拒绝猜过火（可能性：两块是同一层的副本）
"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\recognizer")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import detect_params as dp  # noqa: E402

BUILDINGS = r"D:\gym3d\data\buildings"

print("%-7s %-11s %-11s %-11s %-11s %s" % ("楼", "档里cx", "块0 cx", "块1 cx", "中点", "判定"))
print("-" * 78)
for name in sorted(os.listdir(BUILDINGS)):
    pj = os.path.join(BUILDINGS, name, "profile.json")
    if not os.path.exists(pj):
        continue
    prof = json.load(open(pj, encoding="utf-8"))
    dxf = prof.get("dxf")
    if not dxf or not os.path.exists(dxf):
        continue
    d = dp.detect(dxf, name, prof.get("title", ""))
    if not d.get("multi_column"):
        continue
    bl = d["column_blocks"]
    p_cx = prof.get("cx")
    c0 = bl[0]["cx"]
    c1 = bl[1]["cx"] if len(bl) > 1 else None
    mid = round((min(b["x_range"][0] for b in bl) + max(b["x_range"][1] for b in bl)) / 2, 1)

    def near(a, b):
        return a is not None and b is not None and abs(a - b) < 1.0

    verdict = []
    if near(p_cx, c0):
        verdict.append("=块0")
    if near(p_cx, c1):
        verdict.append("=块1")
    if near(p_cx, mid):
        verdict.append("=中点")
    if prof.get("x_range"):
        verdict.append("档里有x_range")
    print("%-7s %-11s %-11s %-11s %-11s %s"
          % (name, p_cx, c0, c1, mid, " ".join(verdict) or "?? 都不等"))
