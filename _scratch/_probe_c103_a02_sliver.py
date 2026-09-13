# -*- coding: utf-8 -*-
r"""c103 A 翼 `103-A-0N-02` 自交修掉的那 0.3455 m² 到底是什么、落在谁身上（**只读**）。

背景（实测）：c103 全库唯一没过 SU 规格闸门的栋，卡点是 F2/F3/F4 三间
`103-A-0N-02`（3455 m² 那条），`buffer(0)` 取最大块会各丢 0.3455 m²。
而这三间正是"A 翼同号对"（F1–F4 各一对：同号一 1537、一 3455）里证据冲突的那条。
⇒ 「修这 0.3455」和「这两条同号房怎么处置」不是两个决定，是同一个决定的两面。
所以先把这 0.3455 量到实处，不靠措辞：

量四件事（逐层，F1 无自交也一并列出作对照）：
  ① 该层 `*02` 同号的两条房各多大、重叠多少（重算，不引用旧数）；
  ② 自交修掉的**那一块**（`buffer(0)` 里除最大块之外的碎块）的**面积与质心**；
  ③ 那一块**是否落在同层任何一间房里**（落谁身上、还是谁都不盖 = 成为空洞）；
  ④ 那一块与**另一条同号房**的关系（包含 / 被包含 / 相邻 / 相距多远）。

用法：python _scratch/_probe_c103_a02_sliver.py
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
FD = os.path.join(ROOT, "data", "buildings", "c103", "floors")

from shapely.geometry import Polygon                       # noqa: E402


def floors():
    out = []
    for fn in sorted(f for f in os.listdir(FD)
                     if f.startswith("floor") and f.endswith(".json")):
        out.append((fn, json.load(io.open(os.path.join(FD, fn), encoding="utf-8"))))
    return out


def main():
    for fn, doc in floors():
        rooms = doc.get("rooms") or []
        by = {}
        for i, r in enumerate(rooms):
            by.setdefault(str(r.get("number")), []).append((i, r))
        hits = [(k, v) for k, v in by.items() if k.endswith("-02")]
        if not hits:
            continue
        print("=== %s（%d 间房）===" % (fn, len(rooms)))
        for num, lst in sorted(hits):
            print("  ── %s 共 %d 条 ──" % (num, len(lst)))
            ps = []
            for i, r in lst:
                g = Polygon(r["poly"])
                ps.append((i, r, g))
                print("     #%-3d 面积 %10.4f  顶点 %3d  合法=%s  %s"
                      % (i, g.area, len(r["poly"]), g.is_valid,
                         ("自交：" + str(g.buffer(0).geom_type)) if not g.is_valid else ""))
            if len(ps) == 2:
                a, b = ps[0][2], ps[1][2]
                ov = a.intersection(b).area
                print("     两条重叠 %.4f m²（占小的 %.2f%%、占大的 %.2f%%）  质心距 %.2f m"
                      % (ov, 100 * ov / min(a.area, b.area), 100 * ov / max(a.area, b.area),
                         a.centroid.distance(b.centroid)))
            # ★ 自交那一块
            for i, r, g in ps:
                if g.is_valid:
                    continue
                bb = g.buffer(0)
                parts = list(bb.geoms) if bb.geom_type == "MultiPolygon" else [bb]
                parts.sort(key=lambda q: -q.area)
                main_ = parts[0]
                rest = parts[1:]
                lost = sum(q.area for q in rest)
                print("     #%d 自交：解成 %d 块，最大块 %.4f，其余 %d 块合计 **%.4f**（占 %.4f%%）"
                      % (i, len(parts), main_.area, len(rest), lost,
                         100 * lost / g.area if g.area else 0))
                # 那一块落在谁身上
                for j, q in enumerate(rest):
                    cx, cy = q.centroid.x, q.centroid.y
                    hosts = [(str(rr.get("number")), k)
                             for k, rr in enumerate(rooms)
                             if k != i and Polygon(rr["poly"]).is_valid
                             and Polygon(rr["poly"]).buffer(0).contains(q.buffer(0))]
                    print("        碎块%d 面积 %.4f 质心 (%.2f, %.2f)  完全落在：%s"
                          % (j + 1, q.area, cx, cy,
                             ("、".join("%s #%d" % h for h in hosts)) if hosts else
                             "**没有任何一间房** ⇒ 修完这一块成为地板空洞"))
                    # 与另一条同号房的关系
                    if len(ps) == 2:
                        other_i, other_r, other_g = ps[0] if ps[1][1] is r else ps[1]
                        d = other_g.distance(q)
                        print("        与另一条 %s 的关系：包含=%s 被包含=%s 相交面积 %.4f 最近距 %.3f m"
                              % (other_r.get("number"), other_g.contains(q.buffer(0)),
                                 q.buffer(0).contains(other_g), other_g.intersection(q.buffer(0)).area, d))
        print()


if __name__ == "__main__":
    main()
