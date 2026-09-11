# -*- coding: utf-8 -*-
"""R12 全 48 楼内墙现状复核(只读): 残留 blob / 巨墙 / 覆盖率统计。
不写任何文件。用于核验墙解融批量后的全盘状态。
"""
import sys, json, glob, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.errors import TopologicalError

ROOT = r"D:\gym3d\data\buildings"
FROZEN = {"c006", "c009", "c103", "c104"}

def union_safe(polys):
    ok = []
    for p in polys:
        try:
            q = Polygon(p)
            if q.is_valid and not q.is_empty and q.area > 1e-6:
                ok.append(q.buffer(0))
        except Exception:
            pass
    if not ok:
        return None
    try:
        return unary_union(ok)
    except Exception:
        return None

def floor_metrics(fl):
    ol = Polygon(fl["outline"]) if Polygon(fl["outline"]).is_valid else None
    if ol is None or ol.area < 1:
        return None
    inn = [w for w in fl["walls"] if w["type"] == "inner"]
    if not inn:
        return {"walls": 0, "cover": 0.0, "big": 0, "blob": False}
    U = union_safe([w["poly"] for w in inn])
    cov = 100 * U.area / ol.area if U else 0
    big = sum(1 for w in inn if Polygon(w["poly"]).area > 0.4 * ol.area)
    return {"walls": len(inn), "cover": cov, "big": big,
            "blob": len(inn) <= 5 and cov > 20}

tot_blob_floors = 0
tot_big_floors = 0
rows = []
for name in sorted(os.listdir(ROOT)):
    fd = os.path.join(ROOT, name, "floors")
    if not os.path.isdir(fd):
        continue
    fs = []
    blobf, bigf, maxcov = [], [], 0.0
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        try:
            fl = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        m = floor_metrics(fl)
        if m is None:
            continue
        maxcov = max(maxcov, m["cover"])
        if m["blob"]:
            blobf.append(F)
        if m["big"]:
            bigf.append(F)
        fs.append((F, m))
    tot_blob_floors += len(blobf)
    tot_big_floors += len(bigf)
    rows.append((name, len(fs), blobf, bigf, round(maxcov, 1)))

print("%-6s %-4s %-22s %-18s %s" % ("楼", "层", "残留blob层", "巨墙层", "最大内墙cover"))
for name, nf, blobf, bigf, maxcov in rows:
    flag = ""
    if name in FROZEN:
        flag = " [冻结-仅报]"
    elif blobf or bigf:
        flag = "  <== 仍有问题"
    print("%-6s %-4d blob=%s big=%s covMax=%.1f%%%s" % (name, nf,
          str(blobf) if blobf else "-", str(bigf) if bigf else "-", maxcov, flag))
print("\n汇总: 残留blob楼层=%d  残留巨墙楼层=%d" % (tot_blob_floors, tot_big_floors))
