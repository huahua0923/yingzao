# -*- coding: utf-8 -*-
"""宿舍/公寓簇房间抽取普查 (R9 sizing): rooms.json空 + 有无面积/房号MTEXT + dry计数。只读。"""
import sys, os, json, glob
sys.path.insert(0, r"D:\gym3d")
sys.path.insert(0, r"D:\gym3d\backend")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile

def empty_rooms(name):
    p = os.path.join("data/buildings", name, "rooms.json")
    if not os.path.exists(p):
        return True
    try:
        return len(json.load(open(p, encoding="utf-8"))) == 0
    except Exception:
        return True

# 候选: rooms.json 空的楼
cands = []
for d in sorted(glob.glob("data/buildings/*")):
    n = os.path.basename(d)
    if os.path.isdir(d) and empty_rooms(n):
        cands.append(n)
print("rooms.json 空/缺 的楼:", cands)

# 对每栋查 MTEXT 标注层方案
def scheme(name):
    cfg = json.load(open(f"data/buildings/{name}/profile.json", encoding="utf-8"))
    dxf = cfg["dxf"]
    if not os.path.exists(dxf):
        return ("无DXF",)
    try:
        doc = ezdxf.readfile(dxf, encoding="utf-8")
    except Exception as e:
        return ("DXF错误:%s" % e,)
    msp = doc.modelspace()
    layers = set()
    for e in msp:
        if e.dxftype() == "MTEXT":
            layers.add(e.dxf.layer or "")
    return sorted(layers)

for n in cands:
    ly = scheme(n)
    # 关键层判断
    has_area = any(l.startswith("5") for l in ly)
    has_num = any(l.startswith("6") for l in ly)
    flag = "  <== 可抽(5面积+6房间号)" if (has_area and has_num) else "  无面积/房号方案"
    print(f"{n:6} 层数={len(ly):2d} MTEXT层={ly}{flag}")
