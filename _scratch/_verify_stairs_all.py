# -*- coding: utf-8 -*-
"""全楼楼梯渲染体检：量「实际进 GLB 的踏步盒子」，不量公式。

修前基线：c103 踢面 0.323、c114 0.383、c022 0.420、c104 0.323。
修后应当全部落回 0.13~0.20（余量放到 0.215，见 build_standard_glb.RISER_MAX）。
"""
import json
import os
import sys

sys.path.insert(0, r"D:\gym3d\backend\modeling")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import build_standard_glb as bsg  # noqa: E402

B = r"D:\gym3d\data\buildings"


class Rec:
    def __init__(self):
        self.boxes = []

    def add_box(self, cx, cy, cz, w, h, d, rot_y=0.0, col=None):
        self.boxes.append((cy, h, d))

    def __getattr__(self, name):
        return lambda *a, **k: None


rows = []
for name in sorted(os.listdir(B)):
    d = os.path.join(B, name)
    if not os.path.isdir(os.path.join(d, "floors")):
        continue
    S = json.load(open(os.path.join(d, "spec.json"), encoding="utf-8"))
    bsg.DATA = d
    try:
        floors = bsg.load_floors()
    except Exception as e:                                  # noqa: BLE001
        print("%-6s 读楼层失败 %s" % (name, e))
        continue
    h = S["floor_h"]
    allr = []
    covered = True
    nwell = 0
    for i, fl in enumerate(floors):
        nwell += len(fl.get("stairwells") or [])
        if i == len(floors) - 1:
            continue
        r = Rec()
        try:
            bsg.build_indoor_stairs(r, fl, i * h, S, False)
        except Exception as e:                              # noqa: BLE001
            print("%-6s F%d 画楼梯炸了 %s" % (name, fl.get("floor"), e))
            covered = False
            break
        if not r.boxes:
            continue
        ys = [b[0] for b in r.boxes]
        if min(ys) < i * h - 0.01 or max(ys) > (i + 1) * h + 0.01:
            covered = False
        allr += [b[1] for b in r.boxes]
    if not allr:
        rows.append((name, nwell, None, None, "无踏步", True))
        continue
    lo, hi = min(allr), max(allr)
    # 只把**陡**当缺陷：踢面偏高是观感问题（楼梯像爬梯），偏低只是平缓。
    # 下界取 RISER_MIN（0.12），与 build_standard_glb 的判据同口径。
    bad = not (bsg.RISER_MIN <= lo and hi <= bsg.RISER_MAX)
    rows.append((name, nwell, lo, hi, "越界" if bad else "合规", covered))

print("%-6s %5s %9s %9s %6s %s" % ("楼栋", "井数", "最小踢面", "最大踢面", "判定", "层内覆盖"))
nb = 0
for name, nwell, lo, hi, verdict, covered in rows:
    if lo is None:
        print("%-6s %5d %9s %9s %6s %s" % (name, nwell, "-", "-", verdict, ""))
        continue
    if verdict == "越界":
        nb += 1
    print("%-6s %5d %9.3f %9.3f %6s %s"
          % (name, nwell, lo, hi, verdict,
             "OK" if covered else "**有踏步跑出层高**"))
print("\n越界 %d 栋" % nb)
