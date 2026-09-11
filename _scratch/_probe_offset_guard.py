# -*- coding: utf-8 -*-
"""验证 offset 边界守卫：该响的响（c046/c054/c055 实测返回 8000=下界），
不该响的不响（c019/c006/c103 的 offset 虽然非标准但不是边界值）。"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\recognizer")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import detect_params as dp  # noqa: E402

B = r"D:\gym3d\data\buildings"
EXPECT_FIRE = {"c046", "c054", "c055"}
EXPECT_SILENT = {"c019", "c006", "c103", "c108", "c041"}

print("%-7s %-9s %-9s %-8s %s" % ("楼", "档offset", "探offset", "守卫", "备注"))
print("-" * 74)
bad = []
for name in sorted(os.listdir(B)):
    pj = os.path.join(B, name, "profile.json")
    if not os.path.exists(pj):
        continue
    prof = json.load(open(pj, encoding="utf-8"))
    dxf = prof.get("dxf")
    if not dxf or not os.path.exists(dxf):
        continue
    d = dp.detect(dxf, name, prof.get("title", ""), x_range=prof.get("x_range"))
    if "error" in d:
        continue
    fired = bool(d.get("offset_unreliable"))
    if name in EXPECT_FIRE and not fired:
        bad.append(name + " 应响没响")
    if name in EXPECT_SILENT and fired:
        bad.append(name + " 不应响却响了")
    if not (name in EXPECT_FIRE or name in EXPECT_SILENT):
        continue
    print("%-7s %-9s %-9s %-8s %s"
          % (name, prof.get("offset"), d["offset"],
             "响了" if fired else "静默", "OK"))

print("\n" + ("全部符合预期" if not bad else "!! " + "; ".join(bad)))
