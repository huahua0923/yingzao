# -*- coding: utf-8 -*-
r"""沙盘（**不碰 data/**）：把 c103 房间多边形里的自交用 buffer(0) 修掉，看管道能不能过。

问的问题只有一个：c103 卡住的原因**只是**自交，还是修完自交还会被「房间嵌套」拦下？
答案决定处置方案 —— 若只是自交，修 11 个多边形就通；若嵌套也拦，就得先决定删哪一条同号房。

做法：
  ① 把 `data/buildings/c103/` 下的 floors/ + profile.json + spec.json + rooms.json
     复制到 `_scratch/_tmp_c103_fixprobe/`（**只读源目录**，一个字节都不改）；
  ② 副本里逐层把 `Polygon(r["poly"]).is_valid == False` 的房换成 `buffer(0)` 的最大块；
  ③ 猴子补丁 `FF.building_dir` 指向副本，跑完整管道。
副本是沙盘产物，跑完保留（`_scratch/` 不是交付目录），可复核。
"""
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
sys.path.insert(0, os.path.join(ROOT, "backend", "modeling"))
sys.path.insert(0, os.path.join(ROOT, "backend"))

SRC = os.path.join(ROOT, "data", "buildings", "c103")
DST = os.path.join(ROOT, "_scratch", "_tmp_c103_fixprobe")

import build_standard_glb as G          # noqa: E402
import su_spec_floors as SF             # noqa: E402
import su_spec_floors_fleet as FF       # noqa: E402
from shapely.geometry import Polygon    # noqa: E402
from shapely.validation import explain_validity  # noqa: E402

# ---- ① 复制 ----
if os.path.isdir(DST):
    shutil.rmtree(DST)
os.makedirs(DST)
for f in ("profile.json", "spec.json", "rooms.json"):
    p = os.path.join(SRC, f)
    if os.path.exists(p):
        shutil.copy2(p, os.path.join(DST, f))
shutil.copytree(os.path.join(SRC, "floors"), os.path.join(DST, "floors"))

# ---- ② 修自交 ----
fixed = 0
for fn in sorted(f for f in os.listdir(os.path.join(DST, "floors"))
                 if f.startswith("floor") and f.endswith(".json")):
    fp = os.path.join(DST, "floors", fn)
    doc = json.load(io.open(fp, encoding="utf-8"))
    n_fix = 0
    for r in (doc.get("rooms") or []):
        g = Polygon(r["poly"])
        if g.is_valid:
            continue
        why = explain_validity(g)[:50]
        b = g.buffer(0)                     # 修法：buffer(0)，取最大块
        if b.geom_type == "MultiPolygon":
            b = max(b.geoms, key=lambda q: q.area)
        r["poly"] = [[round(x, 6), round(y, 6)] for x, y in b.exterior.coords]
        r["_fixprobe"] = "buffer(0): " + why
        n_fix += 1
        fixed += 1
    if n_fix:
        tmp = fp + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, fp)
        print("  %s 修了 %d 个自交多边形" % (fn, n_fix))
print("副本共修 %d 个\n" % fixed)

# ---- ③ 沙盘跑管道 ----
FF.building_dir = lambda name: DST
# ★ 必须先照真入口把**该栋实际用到的用途**注入色表，否则父类那 13 个默认键不够用，
#   跑到最后会拿「用途不在配色表里」把你拦住 —— 那是探针漏了一步，不是 c103 的病。
with io.open(FF.PALETTE, encoding="utf-8") as f:
    _pal = json.load(f)
_used = FF.used_purposes(os.path.join(DST, "floors"))
_col, _fam = FF.palette_for(_used, _pal)
SF.PURPOSE_COLOR, SF.PURPOSE_FAMILY = _col, _fam
print("沙盘注入用途色 %d 种" % len(_col))
G.DATA = DST
G.OUT = os.path.join(ROOT, "_scratch", "su_jobs", "_c103_fixprobe_spec.json")
G.INCLUDE_SYNTHETIC_WINDOWS = True
G.SKIP_FLOORS = set()
G.MeshBuilder = FF.FleetFloorRecorder
try:
    G.main()
    print("\n沙盘结果：通过 ✅ —— 说明 c103 卡住的**只有自交**，嵌套不拦管道")
except Exception as e:                                        # noqa: BLE001
    msg = str(e)
    kind = ("房间嵌套/同号重复" if "落在" in msg and "间房里" in msg
            else "GEOS 自交" if "GEOS" in msg
            else "其他")
    print("\n沙盘结果：仍不过 ❌ [%s]\n  %s: %s" % (kind, type(e).__name__, msg))
