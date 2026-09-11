# -*- coding: utf-8 -*-
"""决定性验证：detect(--x-range) 能否复现人工手定的 cx？

17 栋多块楼的 profile.json 都已带 x_range（人工当时手工加的）。
若把该 x_range 喂回新代码能得回档案里的 cx/offset/cy，就证明
「自动检测 + 人工确认 x_range」这条路能替代当初的手工推导。
"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\recognizer")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import detect_params as dp  # noqa: E402

BUILDINGS = r"D:\gym3d\data\buildings"

print("%-7s %-12s %-12s %-10s %s" % ("楼", "档cx", "复现cx", "Δcx(m)", "offset/cy"))
print("-" * 72)
exact = near = miss = 0
for name in sorted(os.listdir(BUILDINGS)):
    pj = os.path.join(BUILDINGS, name, "profile.json")
    if not os.path.exists(pj):
        continue
    prof = json.load(open(pj, encoding="utf-8"))
    xr = prof.get("x_range")
    if not xr:
        continue
    dxf = prof.get("dxf")
    if not dxf or not os.path.exists(dxf):
        continue
    d = dp.detect(dxf, name, prof.get("title", ""), x_range=xr)
    if "error" in d:
        print("%-7s %-12s %s" % (name, prof.get("cx"), "ERR " + d["error"][:40]))
        miss += 1
        continue
    delta = abs(d["cx"] - prof.get("cx", 0))
    if delta < 1.0:
        exact += 1
        tag = "精确一致"
    elif delta < 1000.0:
        near += 1
        tag = ""
    else:
        miss += 1
        tag = "偏差大"
    off_ok = "off=%s/cy=%s" % (d["offset"], d["cy"])
    if d["offset"] != prof.get("offset"):
        off_ok += " (档 off=%s)" % prof.get("offset")
    print("%-7s %-12s %-12s %-10.3f %s %s"
          % (name, prof.get("cx"), d["cx"], delta / 1000.0, off_ok, tag))

print("\n精确一致 %d 栋 | 差<1m %d 栋 | 偏差大 %d 栋" % (exact, near, miss))
