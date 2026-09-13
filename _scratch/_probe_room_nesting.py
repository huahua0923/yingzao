# -*- coding: utf-8 -*-
r"""只读普查：`floors/floor*.json` 的 `rooms[]` 里有多少房间**嵌套/重叠**（不是重复副本）。

为什么需要这个：c103 的 SU 管道中止在
  `第 0 层地垫 #1（面积 1537.4470 m²）没有唯一落在哪间房里（落在 0 个房内）`
但 dry-run 的删副本脚本对它**零命中** —— 它的毛病不是「两份逐点相同」，
而是**一间 1537.447 m² 的大房间把其余 7 间（79.5~109.6 m²）整个包在里面**。
于是「每块地垫唯一落在一间房」这条判据在 c103 上天然不成立。

本探针回答三个问题（全库口径，不只看 c103）：
  ① 哪些楼、哪些层有「包含」关系（A ⊇ B，B 面积 99% 以上落在 A 内）？
  ② 容器房占本层楼板面积多少？（≈100% 说明它就是「整层当一间」的汇总行，不是真房间）
  ③ 有没有**部分重叠**（既不含也不被含，交叠 >10%）—— 那是另一种病，得单独看。

判据与阈值：
  · 包含：`A.intersection(B).area >= 0.99 * B.area`（B 几乎全在 A 里）。
  · 部分重叠：交叠面积 > 10% × min(area) 且不构成包含。
  · 一律用 `shapely`；多边形非法（自交）时 `buffer(0)` 后重试，并**如实记下动过手脚**
    （`buffer(0)` 会改几何，不能假装没发生）。
  · 面积口径用多边形自身的 `area`（局部坐标、米），与 SU 管道同源。

用法：python _scratch/_probe_room_nesting.py [楼名...]     # 不给名字=全库
只读：不改任何 data/ 下的文件。
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BUILDINGS = os.path.join(ROOT, "data", "buildings")
from shapely.geometry import Polygon        # noqa: E402
from shapely.validation import explain_validity  # noqa: E402


def poly_of(p, stats):
    """多边形，非法就 buffer(0) 重试；stats 记账（不掩盖）。"""
    g = Polygon(p)
    if g.is_valid:
        return g
    stats["invalid"] += 1
    stats["why"].add(explain_validity(g)[:60])
    return g.buffer(0)


def floor_outline_area(doc):
    """本层楼板面积：优先 outline，缺了就用外轮廓包络（只用于算占比）。"""
    for key in ("outline",):
        o = doc.get(key)
        if o and len(o) >= 3:
            return Polygon(o).buffer(0).area
    walls = doc.get("walls") or []
    ext = [w for w in walls if w.get("ext")]
    if ext:
        from shapely.ops import unary_union
        return unary_union([Polygon(w["ext"]).buffer(0) for w in ext]).area
    return 0.0


def scan_floor(doc, stats):
    rooms = doc.get("rooms") or []
    gs = [poly_of(r["poly"], stats) for r in rooms]
    contains, overlaps = [], []
    for i, a in enumerate(gs):
        if a.area <= 0:
            continue
        for j, b in enumerate(gs):
            if i == j or b.area <= 0:
                continue
            ia = a.intersection(b).area
            if ia <= 1e-6:
                continue
            if ia >= 0.99 * b.area and a.area > b.area:      # a ⊇ b
                contains.append((i, j, ia / b.area))
            elif ia > 0.10 * min(a.area, b.area):             # 部分重叠
                overlaps.append((i, j, ia, min(a.area, b.area)))
    return rooms, gs, contains, overlaps


def main():
    names = sys.argv[1:]
    if not names:
        names = sorted(n for n in os.listdir(BUILDINGS)
                       if os.path.isdir(os.path.join(BUILDINGS, n, "floors")))
    tot_nest = tot_ovl = tot_invalid = 0
    hit_buildings = []
    for name in names:
        fd = os.path.join(BUILDINGS, name, "floors")
        if not os.path.isdir(fd):
            continue
        lines = []
        for fn in sorted(f for f in os.listdir(fd)
                         if f.startswith("floor") and f.endswith(".json")):
            doc = json.load(io.open(os.path.join(fd, fn), encoding="utf-8"))
            stats = {"invalid": 0, "why": set()}
            rooms, gs, contains, overlaps = scan_floor(doc, stats)
            tot_invalid += stats["invalid"]
            if not contains and not overlaps:
                continue
            plate = floor_outline_area(doc)
            tot_nest += len(contains)
            tot_ovl += len(overlaps)
            lines.append("  %s  rooms=%d  楼板面积=%.1f m²%s"
                         % (fn, len(rooms), plate,
                            "  [非法多边形 %d 个已 buffer(0)：%s]"
                            % (stats["invalid"], "; ".join(sorted(stats["why"])))
                            if stats["invalid"] else ""))
            # 容器房：被它包住的间数 + 它自己的面积 + 占楼板比
            from collections import defaultdict
            inn = defaultdict(list)
            for i, j, frac in contains:
                inn[i].append((j, frac))
            for i in sorted(inn, key=lambda k: -gs[k].area):
                sub = inn[i]
                print("    ⊇ #%-2d %-14s 面积=%9.4f（占楼板 %5.1f%%）包住 %d 间：%s"
                      % (i, str(rooms[i].get("number")), gs[i].area,
                         100 * gs[i].area / plate if plate else -1, len(sub),
                         ", ".join("#%d(%s,%.1f m²)" % (j, rooms[j].get("number"), gs[j].area)
                                   for j, _ in sorted(sub, key=lambda t: -gs[t[0]].area))))
            for i, j, ia, mn in sorted(overlaps, key=lambda t: -t[2])[:5]:
                print("    ⧉ #%d(%s) ∩ #%d(%s) = %.4f（占小的 %.1f%%）—— 部分重叠"
                      % (i, str(rooms[i].get("number")), j, str(rooms[j].get("number")),
                         ia, 100 * ia / mn))
        if lines:
            hit_buildings.append(name)
            print("=== %s ===" % name)
            for L in lines:
                print(L)
    print("\n合计：包含关系 %d 对、部分重叠 %d 对、非法多边形 %d 个" % (tot_nest, tot_ovl, tot_invalid))
    print("有嵌套/重叠的楼 %d 栋：%s" % (len(hit_buildings), " ".join(hit_buildings)))


if __name__ == "__main__":
    main()
