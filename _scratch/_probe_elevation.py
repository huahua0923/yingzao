# -*- coding: utf-8 -*-
"""DXF 里有没有立面图/剖面图？—— 这是「有立面图更好」的前置问题。

长期目标：只有平面图 → 模型；有立面图 → 高准确率模型。
合成窗现在是**沿外墙等距瞎排**的（win_spacing 均分），立面图若在同一张 DXF 里，
就能读出真实窗位/窗高/层高分段，把「合成」换成「实测」。

本探针只读，不改任何数据。扫描：
  1. 文字实体里含 立面/剖面/标高/ELEVATION/SECTION 的（中文图纸的主要线索）
  2. 图层名里的立面线索
  3. 各实体类型分布，看有没有非平面的第二套图纸
"""
import os
import re
import sys
import glob
import json
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d\backend\web")
sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, r"D:\gym3d")

import ezdxf  # noqa: E402
import run_step  # noqa: E402

KEYS = ["立面", "剖面", "标高", "ELEVATION", "SECTION", "正立面", "侧立面", "背立面"]
LAY = re.compile(r"(立面|剖面|elev|section)", re.I)


def scan(name):
    p = run_step.load_profile(name)
    if not os.path.exists(p.dxf):
        return None
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    hits = collections.Counter()
    samples = []
    layers = set()
    n = 0
    for e in msp:
        n += 1
        layers.add(e.dxf.layer)
        if e.dxftype() in ("TEXT", "MTEXT"):
            t = e.dxf.text if e.dxftype() == "TEXT" else e.text
            t = re.sub(r"\\[A-Za-z][^;]*;", "", t or "")
            for k in KEYS:
                if k in t:
                    hits[k] += 1
                    if len(samples) < 6:
                        samples.append(t.strip()[:40])
                    break
    lay_hits = sorted(l for l in layers if LAY.search(l))
    return {"n": n, "hits": dict(hits), "samples": samples, "lay": lay_hits,
            "nlayers": len(layers)}


names = sys.argv[1:] or sorted(
    d for d in os.listdir(r"D:\gym3d\data\buildings")
    if os.path.isdir(os.path.join(r"D:\gym3d\data\buildings", d, "floors")))

tot = collections.Counter()
found = []
for i, nm in enumerate(names, 1):
    try:
        r = scan(nm)
    except Exception as ex:  # noqa: BLE001
        print("[%2d/%d] %-8s 读取失败 %s: %s" % (i, len(names), nm, type(ex).__name__, ex))
        continue
    if r is None:
        continue
    for k, v in r["hits"].items():
        tot[k] += v
    tag = "★" if r["hits"] else " "
    print("[%2d/%d] %-8s 实体%6d 图层%3d %s 文字命中%s%s"
          % (i, len(names), nm, r["n"], r["nlayers"], tag,
             r["hits"] or "无", ("  图层:" + ",".join(r["lay"])) if r["lay"] else ""))
    if r["hits"]:
        found.append((nm, r))
    sys.stdout.flush()

print("\n=== 汇总 ===")
print("命中关键词总数:", dict(tot) or "0")
print("含立面线索的楼:", len(found), "/", len(names))
for nm, r in found[:10]:
    print(" ", nm, r["hits"], "样例:", r["samples"][:3])
