# -*- coding: utf-8 -*-
r"""全库"自交房间"逐间明细（**只读**，不跳过任何一间）—— 复核 `_fix_self_intersections.py` 的伴侣。

`_fix_self_intersections.py` 的判据是「该层有一间超限就整层不改」，所以它的报告里**看不到**
被跳过那层其余房间的情况。本脚本把 558 间**全部**列出来，每间标 `可修 / 超限 / 空面`，
让"22 栋全修"这句话到底能修多少间有确切数字。

判据与主脚本完全一致（MAX_REL=1%），只是不 break：
  · 可修 = buffer(0) 非空、且最大块面积相对变化 ≤ 1%
  · 超限 = 相对变化 > 1%（**要人看**：这不是细刺自交，是自相吞并，取最大块等于丢一半）
  · 空面 = buffer(0) 为空（已经不是面了）
用法：python _scratch/_probe_selfint_refused.py [栋名…]
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BUILDINGS = os.path.join(ROOT, "data", "buildings")
from shapely.geometry import Polygon                 # noqa: E402
from shapely.validation import explain_validity      # noqa: E402

MAX_REL = 0.01


def main():
    names = sys.argv[1:] or sorted(
        n for n in os.listdir(BUILDINGS)
        if os.path.isdir(os.path.join(BUILDINGS, n, "floors")))
    tot = {"可修": 0, "超限": 0, "空面": 0}
    tot_area = {"可修": 0.0, "超限": 0.0}
    per_bld = {}
    bad_layers = []
    for name in names:
        fd = os.path.join(BUILDINGS, name, "floors")
        if not os.path.isdir(fd):
            continue
        blk = {"可修": 0, "超限": 0, "空面": 0}
        det = []
        for fn in sorted(f for f in os.listdir(fd)
                         if f.startswith("floor") and f.endswith(".json")):
            doc = json.load(io.open(os.path.join(fd, fn), encoding="utf-8"))
            for i, r in enumerate(doc.get("rooms") or []):
                g = Polygon(r["poly"])
                if g.is_valid:
                    continue
                why = explain_validity(g)[:44]
                b = g.buffer(0)
                if b.is_empty:
                    blk["空面"] += 1
                    det.append((fn, i, r.get("number"), g.area, None, "空面", why))
                    continue
                parts = list(b.geoms) if b.geom_type == "MultiPolygon" else [b]
                mainp = max(parts, key=lambda q: q.area)
                rel = (mainp.area - g.area) / g.area if g.area else 0.0
                lost = sum(q.area for q in parts) - mainp.area
                kind = "可修" if abs(rel) <= MAX_REL else "超限"
                blk[kind] += 1
                tot_area[kind] += g.area
                det.append((fn, i, r.get("number"), g.area, rel, kind,
                            "块%d/丢%.3f" % (len(parts), lost) if len(parts) > 1 else "",
                            why))
                if kind == "超限":
                    bad_layers.append("%s/%s #%d %s" % (name, fn, i, r.get("number")))
        if any(blk.values()):
            per_bld[name] = blk
            print("=== %s ===  可修 %d / 超限 %d / 空面 %d" % (name, blk["可修"], blk["超限"], blk["空面"]))
            for fn, i, num, a, rel, kind, extra, why in det:
                print("   %s %-6s #%-3d %-14s %9.4f %s%s %s"
                      % ({"可修": "·", "超限": "✗", "空面": "✗"}[kind], fn.replace("floor", "F").replace(".json", ""),
                         i, num, a, kind,
                         "" if rel is None else "  %+.2f%%" % (100 * rel),
                         extra + "  " + why if kind != "可修" else ""))
            for k in tot:
                tot[k] += blk[k]
    print("\n全库合计：可修 %d / 超限 %d / 空面 %d（共 %d 间自交，%d 栋）"
          % (tot["可修"], tot["超限"], tot["空面"], sum(tot.values()), len(per_bld)))
    print("      可修那批面积合计 %.4f m²；超限那批 %.4f m²（**需人看**）"
          % (tot_area["可修"], tot_area["超限"]))
    print("\n需人看的 %d 间：" % len(bad_layers))
    for x in bad_layers:
        print("   %s" % x)


if __name__ == "__main__":
    main()
