# -*- coding: utf-8 -*-
r"""全库"自交房间"逐间明细（**只读**，不跳过任何一间）—— 复核 `_fix_self_intersections.py` 的伴侣。

`_fix_self_intersections.py` 逐间判、逐间跳，所以"到底还剩几间、各是什么病"要看汇总。
本脚本把**当前盘上**所有自交的房间列出来，每间标 `可修 / 改区域 / 带孔 / 空面`。

★ 判据**直接引主脚本的常量**（`REGION_TOL` / `LOSS_TOL` / `REGION_CHANGE_OK`），本文件
  不再自带一份。2026-09-13 判例：本文件原先自己写着 `MAX_REL = 0.01`（面积差 ≤1% 就算"可修"），
  而主脚本早已换成「区域逐点不变（对称差 ≤1e-6 m²）」—— 于是它把 3 间"改区域"的房间
  报成"可修"，docstring 里"判据与主脚本完全一致"变成假话。**判据只能有一处实现。**
  （顺带：面积差也量错了对象 —— 该量**要落盘的那条环**，见主脚本 docstring ③。）

四类：
  · 可修   = `buffer(0)` 非空、无孔、且区域逐点不变 ⇒ 主脚本会改
  · 改区域 = 区域真变了（过 `REGION_TOL`）；在例外表里且损失对得上 ⇒ 主脚本`--allow-region-change` 下会改，否则"保住不改"
  · 带孔   = 修后带孔，交付 `poly` 表达不了 ⇒ 一律不改
  · 空面   = `buffer(0)` 为空（已经不是面了）
用法：python _scratch/_probe_selfint_refused.py [栋名…]
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BUILDINGS = os.path.join(ROOT, "data", "buildings")
sys.path.insert(0, os.path.join(ROOT, "_scratch"))
from shapely.geometry import Polygon                 # noqa: E402
from shapely.validation import explain_validity      # noqa: E402
import _fix_self_intersections as FX                 # noqa: E402  ★ 判据唯一来源

KINDS = ("可修", "改区域", "带孔", "空面")


def main():
    names = sys.argv[1:] or sorted(
        n for n in os.listdir(BUILDINGS)
        if os.path.isdir(os.path.join(BUILDINGS, n, "floors")))
    tot = dict.fromkeys(KINDS, 0)
    tot_area = dict.fromkeys(KINDS, 0.0)
    per_bld = {}
    need_human = []
    for name in names:
        fd = os.path.join(BUILDINGS, name, "floors")
        if not os.path.isdir(fd):
            continue
        blk = dict.fromkeys(KINDS, 0)
        det = []
        for fn in sorted(f for f in os.listdir(fd)
                         if f.startswith("floor") and f.endswith(".json")):
            doc = json.load(io.open(os.path.join(fd, fn), encoding="utf-8"))
            for i, r in enumerate(doc.get("rooms") or []):
                g = Polygon(r["poly"])
                if g.is_valid:
                    continue
                why = explain_validity(g)[:44]
                num = str(r.get("number"))
                b = g.buffer(0)
                if b.is_empty:
                    kind, note, sd = "空面", "", None
                    need_human.append("%s/%s #%d %s（空面）" % (name, fn, i, num))
                else:
                    parts = list(b.geoms) if b.geom_type == "MultiPolygon" else [b]
                    mainp = max(parts, key=lambda q: q.area)
                    # ★ 量与写同一件东西：交付 `poly` 只有单个外环（见主脚本 ③）
                    written = Polygon([[round(x, 9), round(y, 9)]
                                       for x, y in mainp.exterior.coords])
                    lost = sum(q.area for q in parts) - mainp.area
                    sd = written.symmetric_difference(b).area
                    note = "块%d/丢%.3f" % (len(parts), lost) if len(parts) > 1 else ""
                    if mainp.interiors:
                        kind = "带孔"
                        need_human.append("%s/%s #%d %s（带孔 %d 个，填孔会盖住别间）"
                                          % (name, fn, i, num, len(mainp.interiors)))
                    elif sd <= FX.REGION_TOL:
                        kind = "可修"
                    else:
                        kind = "改区域"
                        rec = FX.REGION_CHANGE_OK.get((name, fn, num))
                        if rec is not None and abs(sd - rec) <= FX.LOSS_TOL:
                            note += "  ★在例外表内(已批准 %.6f)" % rec
                        else:
                            need_human.append("%s/%s #%d %s" % (name, fn, i, num))
                blk[kind] += 1
                tot_area[kind] += g.area
                det.append((fn, i, num, g.area, sd, kind, note, why))
        if any(blk.values()):
            per_bld[name] = blk
            print("=== %s ===  %s" % (name, " / ".join("%s %d" % (k, blk[k]) for k in KINDS)))
            for fn, i, num, a, sd, kind, extra, why in det:
                print("   %s %-6s #%-3d %-14s %9.4f %s%s %s"
                      % ({"可修": "·"}.get(kind, "✗"),
                         fn.replace("floor", "F").replace(".json", ""),
                         i, num, a, kind,
                         "" if sd is None else "  对称差 %.6f" % sd,
                         extra + "  " + why if kind != "可修" else ""))
            for k in tot:
                tot[k] += blk[k]
    print("\n全库合计：%s（共 %d 间自交，%d 栋）"
          % (" / ".join("%s %d" % (k, tot[k]) for k in KINDS),
             sum(tot.values()), len(per_bld)))
    print("      可修那批面积合计 %.4f m²；改区域那批 %.4f m²"
          % (tot_area["可修"], tot_area["改区域"]))
    print("\n**需人看的 %d 间**（改区域且不在例外表内 / 带孔 / 空面）：" % len(need_human))
    for x in need_human:
        print("   %s" % x)


if __name__ == "__main__":
    main()
