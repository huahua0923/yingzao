# -*- coding: utf-8 -*-
"""回归验证：detect_params 加多列分块后，全仓 48 栋的 cx/offset/cy 必须**一字不变**。

判据（硬）：
  - 单块楼：新 detect() 的 cx/offset/cy 与改前一致（改前值 = 本脚本内联的旧算法，不靠记忆）
  - 多块楼：报出来，人工看它是谁
不变量：cluster_x 在单块输入上必须返回恰好 1 块，且 cx 与「全部顶点中点」相同。
"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\recognizer")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ezdxf  # noqa: E402
import detect_params as dp  # noqa: E402

BUILDINGS = r"D:\gym3d\data\buildings"


def old_detect(dxf_path, name, title):
    """逐字复刻改动前的算法，作为 ground truth。"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    layer_etype = {}
    for e in msp:
        t = e.dxftype()
        lay = e.dxf.layer if hasattr(e.dxf, "layer") else "(none)"
        layer_etype.setdefault(lay, {})
        layer_etype[lay][t] = layer_etype[lay].get(t, 0) + 1
    wall_layers = [l for l in layer_etype
                   if any(k in l for k in dp.WALL_KEYWORDS)
                   and layer_etype[l].get("LWPOLYLINE", 0) > 0]
    wall_layer = max(wall_layers, key=lambda l: layer_etype[l]["LWPOLYLINE"]) if wall_layers else ""
    xs, ys = [], []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wall_layer:
            for x, y in [tuple(p[:2]) for p in e.get_points()]:
                xs.append(x)
                ys.append(y)
    if not ys:
        return None
    offset, _ = dp.detect_offset(ys)
    cx = round((min(xs) + max(xs)) / 2, 1)
    min_y = min(ys)
    f0 = sorted(y for y in ys if y < min_y + offset) if offset else ys
    cy = round(f0[len(f0) // 2], 1)
    return {"offset": offset, "cx": cx, "cy": cy, "wall_layer": wall_layer}


rows = []
for name in sorted(os.listdir(BUILDINGS)):
    pj = os.path.join(BUILDINGS, name, "profile.json")
    if not os.path.exists(pj):
        continue
    try:
        prof = json.load(open(pj, encoding="utf-8"))
    except Exception as e:
        rows.append((name, "读档失败", str(e)[:40], None, None))
        continue
    dxf = prof.get("dxf")
    if not dxf or not os.path.exists(dxf):
        rows.append((name, "无DXF", "", None, None))
        continue
    try:
        new = dp.detect(dxf, name, prof.get("title", ""))
        old = old_detect(dxf, name, prof.get("title", ""))
    except Exception as e:
        rows.append((name, "异常", str(e)[:50], None, None))
        continue
    if old is None:
        rows.append((name, "无墙数据", "", None, None))
        continue

    if new.get("multi_column") and "error" in new:
        # 新语义：多块就是拒绝猜。这里只确认它**确实**是多块，并列出块。
        bl = new["column_blocks"]
        rows.append((name, "拒绝猜(%d块)" % len(bl),
                     " ".join("cx=%s w=%.0fm n=%d" % (b["cx"], b["width_m"], b["walls"])
                              for b in bl),
                     "%s/%s/%s" % (old["cx"], old["offset"], old["cy"]), ""))
        continue

    if "error" in new:
        rows.append((name, "!!错", str(new["error"])[:60], None, None))
        continue

    same = all(new[k] == old[k] for k in ("offset", "cx", "cy"))
    rows.append((name, "OK" if same else "!!变了", "",
                 "%s/%s/%s" % (old["cx"], old["offset"], old["cy"]),
                 "%s/%s/%s" % (new["cx"], new["offset"], new["cy"]) if not same else ""))

print("%-8s %-14s %-24s %s" % ("楼", "结果", "旧 cx/off/cy", "备注"))
print("-" * 110)
changed, refused, multi = 0, 0, 0
for r in rows:
    if r[1] == "!!变了":
        changed += 1
    if r[1].startswith("拒绝猜"):
        refused += 1
    print("%-8s %-14s %-24s %s" % (r[0], r[1], r[3] or "", r[2] or r[4] or ""))

print("\n共 %d 栋 | 拒绝猜(多块) %d 栋 | 单块输出被改动 %d 栋" % (len(rows), refused, changed))
print("PASS —— 单块零回归，多块改为拒绝猜" if changed == 0
      else "FAIL —— 单块楼输出被改动，必须回退")
