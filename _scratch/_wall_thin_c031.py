# -*- coding: utf-8 -*-
"""R11/R12 原型: c031 墙解融(薄墙重建)——把单图层宿舍平面从"整层blob+房洞"
重建成"逐条开放中心线 buffer 成 0.24m 薄内墙", 排除 0.85-1.1m 的闭合设备块。

只处理 c031(用户点名"墙体太厚"的原型), 逐层 .orig 备份, 逐层数值验收,
不通过自动回滚该层。仅改 walls 键; rooms/doors/stairs/stairwells/outline 不动。
验收不变量(每层):
  A 内墙条数 > 8 (原来=1)
  B 净覆盖面积 <= 24% 楼板 (原来 29%+)
  C 每个内墙 poly 不超 outline 40%(无 blob)
  D 门心到最近内墙距离: >70% 门 < 0.6m (门贴在真墙上)
"""
import json, glob, os, sys, math, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import floor_of, to_local
from shapely.geometry import Polygon, LineString, box
from shapely.ops import unary_union

NAME = "c031"
HF = 0.12          # buffer 半径 -> 0.24m 内墙
FIX_GAP = 0.4      # 首尾距>此=开放线(墙), <=此=闭合(设备块,排除)

p = load_profile(NAME)
doc = ezdxf.readfile(p.dxf)
walls_dxf, doors, stairs, cols = classify.classify(doc.modelspace(), p)

# 每层 DXF 墙线分组
raw_by_floor = {}
for w in walls_dxf:
    cx = sum(a for a, b in w) / len(w); cy = sum(b for a, b in w) / len(w)
    F = int(round(floor_of(p, cx, cy)))
    raw_by_floor.setdefault(F, []).append(w)

floors_dir = r"D:\gym3d\data\buildings\%s\floors" % NAME
bak_dir = r"D:\gym3d\data\buildings\%s\.orig\floors.before_wallthin" % NAME
os.makedirs(bak_dir, exist_ok=True)

results = []
for fp in sorted(glob.glob(os.path.join(floors_dir, "floor*.json")), key=lambda s: int(s.split("floor")[-1][:-5])):
    F = int(os.path.basename(fp)[5:-5])
    fl = json.load(open(fp, encoding="utf-8"))
    if not os.path.exists(os.path.join(bak_dir, os.path.basename(fp))):
        shutil.copy2(fp, os.path.join(bak_dir, os.path.basename(fp)))

    oline = Polygon(fl["outline"])
    outline_area = oline.area
    raw = raw_by_floor.get(F, [])
    open_lines = []
    n_fix = 0
    for w in raw:
        loc = [to_local(p, a, b, F) for a, b in w]
        if len(loc) < 2:
            continue
        d = math.hypot(loc[0][0] - loc[-1][0], loc[0][1] - loc[-1][1])
        if d > FIX_GAP:
            open_lines.append(LineString(loc))
        else:
            n_fix += 1

    if not open_lines:
        print("%s F%d: 无开放墙线, 跳过" % (NAME, F)); continue

    # buffer 开放线 -> 薄墙; union 相接
    try:
        buffs = [ln.buffer(HF, cap_style=2, join_style=2) for ln in open_lines]  # cap=2 flat, join=2 mitre
        inner = unary_union(buffs)
        if inner.geom_type == "Polygon":
            polys = [inner]
        elif inner.geom_type == "MultiPolygon":
            polys = list(inner.geoms)
        else:
            polys = []
        # 只保留与 outline 相交且在楼内的实体; 切成独立 wall[]
        new_inner = []
        for P in polys:
            if not P.is_valid:
                P = P.buffer(0)
            Pc = P.intersection(oline.buffer(0.01))
            if Pc.is_empty:
                continue
            if Pc.geom_type == "Polygon":
                new_inner.append(Pc)
            elif Pc.geom_type == "MultiPolygon":
                new_inner.extend(list(Pc.geoms))
    except Exception as e:
        print("%s F%d: buffer 失败 %s -> 回滚跳过" % (NAME, F, e)); continue

    def poly_to_wall(P):
        P = P.buffer(0)
        ext = list(P.exterior.coords)[:-1]
        ext = [[round(x, 3), round(y, 3)] for x, y in ext]
        return {"type": "inner", "poly": ext, "holes": [], "thickness": round(2 * HF, 2),
                "height": fl.get("height", 4.2) if False else None}

    # 过滤: 面积过小的碎片去掉
    walls_new = []
    for P in new_inner:
        if P.area < 0.05:
            continue
        wd = poly_to_wall(P)
        wd["height"] = 4.2
        walls_new.append(wd)

    # ---- 验收 ----
    inner_area = sum(P.area for P in new_inner if P.area)
    cover = 100 * inner_area / outline_area if outline_area else 999
    # C: 单 poly 超 outline 40%?
    big = sum(1 for P in new_inner if P.area > 0.40 * outline_area)
    # D: 门贴墙
    doors_good = 0; ndoors = len(fl.get("doors", []))
    if ndoors:
        doorwalls = unary_union([Polygon(wd["poly"]) for wd in walls_new]) if walls_new else None
        for dd in fl["doors"]:
            if doorwalls is not None and doorwalls.distance(__import__("shapely.geometry", fromlist=["Point"]).Point(dd["x"], dd["y"])) < 0.6:
                doors_good += 1
        dgood_pct = 100 * doors_good / ndoors
    else:
        dgood_pct = 100

    ok = (len(walls_new) > 8) and (cover <= 24) and (big == 0) and (dgood_pct >= 70)
    results.append((F, len(raw), len(open_lines), n_fix, len(walls_new),
                    round(inner_area, 0), round(cover, 1), big, round(dgood_pct, 0), ok))

    if ok:
        # 保留原有外/女儿墙, 替换 inner
        keep = [w for w in fl["walls"] if w["type"] != "inner"]
        fl["walls"] = keep + walls_new
        json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        status = "PASS-写入"
    else:
        status = "FAIL-回滚(备份保留)"

    print("%s F%d: DXF开放线=%d 设备块=%d 重建内墙=%d 净面积=%.0f(%.1f%%) 大blob=%d 门贴墙=%.0f%%  %s"
          % (NAME, F, len(open_lines), n_fix, len(walls_new), inner_area, cover, big, dgood_pct, status))

print("汇总: 通过并写入 %d 层; 备份在 %s" % (sum(1 for r in results if r[-1]), bak_dir))
