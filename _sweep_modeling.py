# -*- coding: utf-8 -*-
"""建模缺陷全仓扫描 (R7)。只读，量化用户报的显示层缺陷：
  ① 墙覆盖/巨块(墙体太厚)  ② 房间数据(点不出信息)  ③ 柱缺失(空柱子)
输出逐栋表 + 命中楼集合。不写任何数据。
"""
import json, glob, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon
from shapely.ops import unary_union

B = "data/buildings"


def load_floors(code):
    d = os.path.join(B, code, "floors")
    out = []
    for fp in sorted(glob.glob(os.path.join(d, "floor*.json")),
                     key=lambda p: int(os.path.basename(p).split("floor")[-1].split(".")[0])):
        out.append(json.load(open(fp, encoding="utf-8")))
    return out


def rooms_json_count(code):
    p = os.path.join(B, code, "rooms.json")
    if not os.path.exists(p):
        return None
    try:
        return len(json.load(open(p, encoding="utf-8")))
    except Exception:
        return -1


def is_under(code):
    p = os.path.join(B, code, "profile.json")
    if os.path.exists(p):
        return bool(json.load(open(p, encoding="utf-8")).get("under_recognized"))
    return False


def wall_metrics(floors):
    """墙覆盖% (solid墙投影/楼板), 墙对象数, 是否有>30㎡单墙对象(巨块), 平均声明厚。"""
    covs = []
    solid_counts = []
    giant = 0
    decl = []
    for fl in floors:
        o = fl.get("outline")
        if not o:
            continue
        try:
            op = Polygon(o).buffer(0)
            if not op.is_valid or op.is_empty or op.area <= 0:
                continue
        except Exception:
            continue
        sp = op.area
        wa = 0.0
        n = 0
        for w in fl.get("walls", []):
            if w.get("type") == "parapet":
                continue
            n += 1
            try:
                p = Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4]).buffer(0)
                if p.is_valid and not p.is_empty:
                    wa += p.area
                    if p.area > 30:
                        giant += 1
                    decl.append(w.get("thickness") or 0)
            except Exception:
                pass
        if sp > 0 and n:
            covs.append(wa / sp)
            solid_counts.append(n)
    if not covs:
        return None
    return dict(
        cov_pct=round(100 * sum(covs) / len(covs)),
        cov_max=round(100 * max(covs)),
        nwall=max(solid_counts),
        giant=giant,
        decl=round(sum(decl) / max(len(decl), 1), 3),
    )


def col_summary(floors):
    cs = [len(f.get("columns", [])) for f in floors]
    return cs


rows = []
codes = sorted(os.listdir(B))
for c in codes:
    if not os.path.isdir(os.path.join(B, c)):
        continue
    try:
        floors = load_floors(c)
    except Exception as e:
        rows.append((c, "ERR", str(e)))
        continue
    if not floors:
        continue
    nf = len(floors)
    # 房间: floor json rooms
    fr = [len(f.get("rooms", [])) for f in floors]
    rooms_names = sum(1 for f in floors for r in f.get("rooms", []) if r.get("name"))
    rj = rooms_json_count(c)
    cols = col_summary(floors)
    col0 = sum(1 for x in cols if x == 0)
    wm = wall_metrics(floors)
    ur = is_under(c)
    rows.append((c, nf, fr, rooms_names, rj, cols, col0, wm, ur))

# ---- 输出 ----
print("楼   层 f-rooms(各层) f有名字 rj 柱数范围 柱=0层 墙cov%%max giant厚>30 声明厚 UR")
for r in rows:
    if r[0] == "ERR":
        print(r[0], r[1], r[2])
        continue
    c, nf, fr, rn, rj, cols, col0, wm, ur = r
    frs = "/".join(map(str, fr))
    colr = "%d..%d" % (min(cols), max(cols)) if cols else "-"
    wcov = (str(wm["cov_pct"]) + "/" + str(wm["cov_max"])) if wm else "-"
    gn = wm["giant"] if wm else 0
    dc = wm["decl"] if wm else 0
    urm = "UR" if ur else ""
    print("%-5s %2d %-10s %4d %3s %-8s %2d  %-7s %2d %.2f %s"
          % (c, nf, frs, rn, str(rj) if rj is not None else "-", colr, col0, wcov, gn, dc, urm))
