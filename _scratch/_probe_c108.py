# -*- coding: utf-8 -*-
"""摸清 c108 网安楼的图纸结构，为建 profile.json 提供依据（只读）。

要回答：
  1. 图层有哪些？哪层是墙/柱/轴线？（识别靠图层名分派，认错了全盘皆错）
  2. 图纸范围多大？各层平面在哪儿？（offset/cx/cy 不是猜的，是从图上量的）
  3. 层数怎么定？（按 Y 聚类出楼层平面；或按房间号/面积标注里的楼层线索）
"""
import os
import re
import sys
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend\web")
sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, r"D:\gym3d")

import ezdxf  # noqa: E402

DXF = r"D:\dxf_output\C108-网安楼.dxf"
doc = ezdxf.readfile(DXF)
msp = doc.modelspace()

print("=== 图层 ===")
print("图层表:", sorted(l.dxf.name for l in doc.layers))

cnt = collections.Counter()
ext = {}
for e in msp:
    cnt[e.dxf.layer] += 1
    try:
        lo, hi = e.dxf.start, e.dxf.end
    except Exception:
        pass
print("\n=== 每层实体数 ===")
for k, v in cnt.most_common():
    print("  %-22s %6d" % (k, v))

print("\n=== 实体类型 ===")
tp = collections.Counter(e.dxftype() for e in msp)
for k, v in tp.most_common(12):
    print("  %-14s %6d" % (k, v))

print("\n=== 总范围 ===")
try:
    from ezdxf.bbox import extents
    lo, hi = extents(msp)
    print("  X %.0f ~ %.0f  (宽 %.0f mm = %.1f m)" % (lo.x, hi.x, hi.x - lo.x, (hi.x - lo.x) / 1000))
    print("  Y %.0f ~ %.0f  (高 %.0f mm = %.1f m)" % (lo.y, hi.y, hi.y - lo.y, (hi.y - lo.y) / 1000))
except Exception as ex:  # noqa: BLE001
    print("  取范围失败:", ex)

print("\n=== 文字线索（楼层/图号/房名 样张）===")
seen = []
for e in msp:
    if e.dxftype() in ("TEXT", "MTEXT"):
        t = (e.dxf.text if e.dxftype() == "TEXT" else e.text) or ""
        t = re.sub(r"\{\\[^}]*;", "", t)
        t = re.sub(r"\\[A-Za-z][^;]*;", "", t).replace("}", "").strip()
        if t and t not in seen:
            seen.append(t)
print("  去重文字 %d 条，前 25 条:" % len(seen))
for s in seen[:25]:
    print("   ", s[:60])

rooms = [s for s in seen if re.search(r"\d{2}-\d{2}-\d{2}|^\d{3,4}$", s)]
print("\n  像房号的:", rooms[:15])
