# -*- coding: utf-8 -*-
"""三次扫库（sweep2 旧列规则 / sweep3 行列对称 / sweep4 行列对称+内容闸）逐栋对照。

重点不是「状态变没变」，而是**图幅集合变了没变**——`n_sheets` 相同也可能是**换了一批图幅**
（`classify` 按 (存留张数, 面积) 选尺寸组，规则一变，胜出的组可能整组换掉）。
覆盖率的移动只有在这个前提下才解释得通，否则就是在拿两个不同的集合比数。
"""
import collections
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE = Path(r"D:\项目\cdut3d\a1\_out")
S = {k: json.loads((BASE / ("wall_sweep%d.json" % k)).read_text(encoding="utf-8"))["rows"]
     for k in (2, 3, 4)}
BY = {k: {r["dxf"]: r for r in v} for k, v in S.items()}

print("=== 汇总三连 ===")
for k in (2, 3, 4):
    c = collections.Counter(r["state"] for r in S[k])
    print("  sweep%d  %s" % (k, dict(c.most_common())))

print("\n=== 图幅张数变了、或覆盖率变了的栋 ===")
print("%-38s %-16s %-16s %-16s" % ("dxf", "s2 张/覆盖", "s3 张/覆盖", "s4 张/覆盖"))
moved = []
for name in sorted(BY[4]):
    a, b, c = BY[2].get(name), BY[3].get(name), BY[4].get(name)
    if not (a and b and c):
        continue
    f = lambda r: "%s/%s" % (
        r.get("n_sheets", "-"),
        "—" if r.get("cov_min") is None else "%.2f" % r["cov_min"])
    if a.get("n_sheets") != c.get("n_sheets") or abs((a.get("cov_min") or 0) - (c.get("cov_min") or 0)) > 0.005 \
       or a["state"] != c["state"]:
        moved.append(name)
        print("%-38s %-16s %-16s %-16s %s→%s" % (name[:38], f(a), f(b), f(c), a["state"], c["state"]))

print("\n共 %d 栋有变。" % len(moved))

print("\n=== 覆盖不满的 6 栋：三连逐项 ===")
for name in ["C008F2-测试楼附楼.dxf", "C109-十公寓.dxf", "C105-图书馆.dxf",
             "C103-第十一教学楼（东1教）.dxf", "C104-第十二教学楼（东2教）.dxf",
             "C058-地质灾害防治与地质环境保护国家重点实验室.dxf"]:
    print("\n  %s" % name)
    for k in (2, 3, 4):
        r = BY[k].get(name, {})
        print("    sweep%d  %-10s 图幅%-3s 真%-3s IoU %-8s 覆盖min %-8s 未量到%s"
              % (k, r.get("state"), r.get("n_sheets"), r.get("n_real", "-"), r.get("iou"),
                 "—" if r.get("cov_min") is None else "%.2f" % r["cov_min"], r.get("n_unmeasured")))
    print("    sweep4 逐张墙段: %s" % sorted(BY[4][name].get("per_sheet_wall", []), reverse=True))
