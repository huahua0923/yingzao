# -*- coding: utf-8 -*-
"""批量生成 37 栋公寓的 profile.json。

比 detect_params 多两件事：
  1. offset 粗聚类——楼层间距 63.5~127m，楼层内墙 Y 散布 <35m，用 gap=35000 聚类后取
     中位间距做 offset，避免楼梯/子墙小簇造成 8000 之类的短周期误判。
  2. x_range 隔离——图纸常把同层画两遍（首层单独 + 塔楼叠层），或两栋并排。
     classify._in_x_range 只留主列，防止首层双副本把墙/门/井画到另一栋（GLB bbox 撑成两栋）。
     副本间隔 340~1350m（大间隙）或 50~105m，用 gap=50000 切分，按实体数取主副本。

用法: python batch_profiles.py [--dry-run]
"""
import json
import os
import statistics
import sys
from collections import Counter

import ezdxf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DXF_DIR = r"D:\dxf_output"
BUILD_DIR = r"D:\gym3d\data\buildings"

APARTMENTS = {
    "c017": ("C017-芙蓉园9号公寓", "芙蓉园9号公寓"),
    "c018": ("C018-芙蓉园8号公寓", "芙蓉园8号公寓"),
    "c019": ("C019-芙蓉园7号公寓", "芙蓉园7号公寓"),
    "c029": ("C029-芙蓉园1号公寓", "芙蓉园1号公寓"),
    "c030": ("C030-芙蓉园2号公寓", "芙蓉园2号公寓"),
    "c031": ("C031-芙蓉园3号公寓", "芙蓉园3号公寓"),
    "c032": ("C032-芙蓉园4号公寓", "芙蓉园4号公寓"),
    "c033": ("C033-芙蓉园5号公寓", "芙蓉园5号公寓"),
    "c034": ("C034-芙蓉园6号公寓", "芙蓉园6号公寓"),
    "c043": ("C043-青年教师公寓1号楼", "青年教师公寓1号楼"),
    "c044": ("C044-青年教师公寓2号楼", "青年教师公寓2号楼"),
    "c045": ("C045-青年教师公寓3号楼", "青年教师公寓3号楼"),
    "c046": ("C046-榕树园公寓", "榕树园公寓"),
    "c054": ("C054-银杏园1号公寓", "银杏园1号公寓"),
    "c055": ("C055-银杏园2号公寓", "银杏园2号公寓"),
    "c056": ("C056-银杏园3号公寓", "银杏园3号公寓"),
    "c057": ("C057-银杏园4号公寓", "银杏园4号公寓"),
    "c059": ("C059-珙桐园1号公寓", "珙桐园1号公寓"),
    "c060": ("C060-珙桐园2号公寓", "珙桐园2号公寓"),
    "c061": ("C061-珙桐园3号公寓", "珙桐园3号公寓"),
    "c062": ("C062-珙桐园4号公寓", "珙桐园4号公寓"),
    "c063": ("C063-珙桐园5号公寓", "珙桐园5号公寓"),
    "c064": ("C064-珙桐园6号公寓", "珙桐园6号公寓"),
    "c065": ("C065-珙桐园7号公寓", "珙桐园7号公寓"),
    "c072": ("C072-松林园1号公寓", "松林园1号公寓"),
    "c073": ("C073-松林园2号公寓", "松林园2号公寓"),
    "c079": ("C079-香樟园1号公寓", "香樟园1号公寓"),
    "c080": ("C080-香樟园2号公寓", "香樟园2号公寓"),
    "c083": ("C083-香樟园3号公寓", "香樟园3号公寓"),
    "c084": ("C084-香樟园4号公寓", "香樟园4号公寓"),
    "c085": ("C085-香樟园5号公寓", "香樟园5号公寓"),
    "c086": ("C086-香樟园6号公寓", "香樟园6号公寓"),
    "c109": ("C109-十公寓", "十公寓"),
    "c116": ("C116-筇竹园公寓", "筇竹园公寓"),
    "ny27": ("NY27-人才公寓1栋", "人才公寓1栋"),
    "ny28": ("NY28-人才公寓2栋", "人才公寓2栋"),
    "ny29": ("NY29-人才公寓3栋", "人才公寓3栋"),
}

STYLE = {
    "facade": "#a4533d",
    "inner": "#cfc9bd",
    "roof": "#6b5a4a",
    "roofType": "flat",
    "parapet": "#6a4a40",
    "glass": "#789cb8",
    "door": "#8a5a38",
}

WALL_KEYWORDS = ("墙体", "4.2", "4墙", "4.3", "封墙")
COL_KEYWORDS = ("结构柱", "4.1柱", "柱")

ALGO_DEFAULTS = {
    "door_min_points": 10, "stair_points": 5,
    "wall_min": 0.08, "wall_max": 0.35, "wall_extend": 0.15, "wall_fallback": 0.15,
    "door_w_single": 1.1, "door_w_double": 2.4, "door_depth": 0.5,
    "outline_buf": 0.15, "open_r": 0.35, "parapet_margin": 0.5,
    "layer_height": 4.2, "slab": 0.2,
}


def cluster_1d(vals, gap):
    """一维排序去重后按 gap 聚类，返回 [[...], [...]]（每簇为取值列表，按首值升序）。"""
    v = sorted(set(round(x) for x in vals))
    if not v:
        return []
    out = [[v[0]]]
    for x in v[1:]:
        if x - out[-1][-1] > gap:
            out.append([x])
        else:
            out[-1].append(x)
    return out


def detect_offset(centroid_ys, fine_gap=3000, coarse_gap=35000):
    """两段聚类：先细聚类(3000)得子簇中心，再粗聚类(35000)得楼层中心，取中位间距=offset。"""
    fine = cluster_1d(centroid_ys, fine_gap)
    fine_centers = [statistics.median(c) for c in fine]
    coarse = cluster_1d(fine_centers, coarse_gap)
    floor_centers = [round(statistics.median(c)) for c in coarse]
    if len(floor_centers) < 2:
        return None
    gaps = [floor_centers[i + 1] - floor_centers[i] for i in range(len(floor_centers) - 1)]
    real = [g for g in gaps if g >= 50000]
    if not real:
        return None
    return int(round(statistics.median(real)))


def n_floors_spanned(ent_ys, coarse_gap=35000):
    """实体 Y 值跨多少个粗楼层簇。"""
    fine = cluster_1d(ent_ys, 3000)
    fine_centers = [statistics.median(c) for c in fine]
    coarse = cluster_1d(fine_centers, coarse_gap)
    return len(coarse)


def detect(dxf_path, name, title):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    layer_etype = Counter()
    for e in msp:
        t = e.dxftype()
        if t == "LWPOLYLINE":
            layer_etype[e.dxf.layer] += 1

    wall_layer = max([l for l in layer_etype if any(k in l for k in WALL_KEYWORDS)],
                     key=lambda l: layer_etype[l], default="")
    column_layer = max([l for l in layer_etype
                        if any(k in l for k in COL_KEYWORDS) and l != wall_layer],
                       key=lambda l: layer_etype[l], default="")

    ents = []  # (cx, cy, pts)
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wall_layer:
            pts = [tuple(p[:2]) for p in e.get_points()]
            if len(pts) < 2:
                continue
            ents.append((sum(p[0] for p in pts) / len(pts),
                         sum(p[1] for p in pts) / len(pts), pts))
    if not ents:
        return {"error": "墙层无 LWPOLYLINE（可能 LINE 约定）"}

    xs = [e[0] for e in ents]

    # X 副本：gap=50000 切分，主副本 = 跨越楼层数最多的簇
    xcl = cluster_1d(xs, 50000)
    x_cluster_ent = []  # (lo, hi, ents)
    for cl in xcl:
        lo, hi = cl[0], cl[-1]
        seg = [e for e in ents if lo <= e[0] <= hi]
        x_cluster_ent.append((lo, hi, seg))
    x_cluster_ent.sort(key=lambda c: (-n_floors_spanned([e[1] for e in c[2]]), -len(c[2])))

    x_range = None
    multi_copy = False
    main_ents = ents
    if len(x_cluster_ent) >= 2:
        main_ents = x_cluster_ent[0][2]
        all_x = [p[0] for e in main_ents for p in e[2]]
        x_range = [round(min(all_x)), round(max(all_x))]
        multi_copy = True

    # offset / cx / cy 一律只用主副本内实体（避免多副本把 cx 拉成中点、cy 被另一副本污染）
    fxs = [e[0] for e in main_ents]
    fys = [e[1] for e in main_ents]
    offset = detect_offset(fys)
    cx = round(statistics.median(fxs), 1)
    fine = cluster_1d(fys, 3000)
    fine_centers = [statistics.median(c) for c in fine]
    coarse = cluster_1d(fine_centers, 35000)
    cy = round(statistics.median(coarse[0]), 1) if coarse else round(statistics.median(fys), 1)

    return {
        "name": name, "title": title, "dxf": dxf_path,
        "wall_layer": wall_layer, "column_layer": column_layer,
        "offset": offset, "cx": cx, "cy": cy,
        "x_range": x_range, "multi_copy": multi_copy,
        "n_ent": len(ents), "n_x_cluster": len(x_cluster_ent),
        "y_floors": n_floors_spanned(fys),
    }


def build_profile(d):
    prof = {
        "name": d["name"], "title": d["title"], "dxf": d["dxf"],
        "wall_layer": d["wall_layer"], "column_layer": d["column_layer"],
        "offset": d["offset"], "cx": d["cx"], "cy": d["cy"],
        "rooms": rf"D:\gym3d\data\buildings\{d['name']}\rooms.json",
        "out_dir": rf"D:\gym3d\data\buildings\{d['name']}\floors",
    }
    if d.get("x_range"):
        prof["x_range"] = d["x_range"]
    prof.update(ALGO_DEFAULTS)
    prof["style"] = STYLE
    return prof


def main():
    dry = "--dry-run" in sys.argv
    rows = []
    for name, (dxf_name, title) in APARTMENTS.items():
        dxf_path = os.path.join(DXF_DIR, dxf_name + ".dxf")
        if not os.path.exists(dxf_path):
            print(f"[跳过] {name}: DXF 缺失")
            continue
        d = detect(dxf_path, name, title)
        if "error" in d:
            print(f"[错误] {name}: {d['error']}")
            continue
        rows.append((name, d))
        xr = f"[{d['x_range'][0]},{d['x_range'][1]}]" if d["x_range"] else "-"
        print(f"[{name}] offset={d['offset']} cy={d['cy']} 柱={d['column_layer'] or '-'} "
              f"多副本={d['multi_copy']} X簇={d['n_x_cluster']} x_range={xr} "
              f"Y粗层={d['y_floors']} 实体={d['n_ent']}")

        if not dry:
            out_dir = os.path.join(BUILD_DIR, name)
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "profile.json"), "w", encoding="utf-8") as f:
                json.dump(build_profile(d), f, ensure_ascii=False, indent=1)

    print(f"\n共 {len(rows)} 栋" + ("（dry-run）" if dry else ""))


if __name__ == "__main__":
    main()
