# -*- coding: utf-8 -*-
r"""c103「同号房」逐条清单（**只读**）—— 供处置定夺与事后复核。

背景（本段实测，不是推断）：
  · c103 的 `floors/` 每层都有**同号房**，但不是早先以为的"六层共 5 条"，
    而是 **42 对**（F1–F4 各 8 对、F5 10 对、F0 无）。
  · 分两种病，**处置结论相反**，所以必须分开看：
    - **B 翼 38 对 = 图纸多副本**：两条**完全不相交**（重叠 0.0%），面积近乎相同（平移出去的一份拷贝）。
      两份独立证据都指向 copy2（高下标那条）是真的：
        ① `rooms.json` 的 `boundary` 逐点等于 copy2（对称差 0.0000）、质心距 copy2 ~5 mm；
        ② 几何自洽——copy2 与"其余所有房间（含其它幽灵）"的交叠**精确为 0**，
           而 copy1 压别人 79.5~219.2 m²（等于压掉一整间）。房间是铺满楼板不重叠的。
    - **A 翼 4 对（F1–F4）= 部分重叠的两块**：1537 与 3422/3455 重叠 **73.25%**（四层稳定），
      **两条都压别人**（780.7 / 1189.7），**两条都不自洽**；而且 `rooms.json` 这一行
      **自己矛盾**：`boundary` 是 3422 那条（逐点相同），`area_m2` 却是 1543.42（≈1537 那条）。
      ⇒ 证据冲突，**不猜**。
  · F0 与 F5 **没有** A 翼对（README 早先写的"每层两条"不准）。

用法：python _scratch/_probe_c103_samenum.py [栋名，默认 c103]
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"


def clean(g):
    return g if g.is_valid else g.buffer(0)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "c103"
    base = os.path.join(ROOT, "data", "buildings", name)
    fd = os.path.join(base, "floors")
    from shapely.geometry import Polygon            # noqa: E402

    rj = json.load(io.open(os.path.join(base, "rooms.json"), encoding="utf-8"))
    rjs = rj if isinstance(rj, list) else (rj.get("rooms") or [])
    rj_by = {}
    for x in rjs:
        rj_by.setdefault((str(x.get("number")), x.get("floor")), x)

    out = []
    n_a = n_b = 0
    print("### %s 同号房逐条清单\n" % name)
    for fn in sorted(f for f in os.listdir(fd)
                     if f.startswith("floor") and f.endswith(".json")):
        doc = json.load(io.open(os.path.join(fd, fn), encoding="utf-8"))
        rooms = doc.get("rooms") or []
        fi = doc.get("floor")
        polys = [clean(Polygon(r["poly"])) for r in rooms]
        bynum = {}
        for i, r in enumerate(rooms):
            bynum.setdefault(str(r.get("number")), []).append(i)
        pairs = {n: ks for n, ks in bynum.items() if len(ks) >= 2}
        if not pairs:
            print("**F%d**（%s）无同号房\n" % (fi, fn))
            continue
        print("**F%d**（%s）同号 %d 对\n" % (fi, fn, len(pairs)))
        print("| 房号 | 翼 | 两条面积 (m²) | 重叠% | 压别人 (m²) | 质心距 (m) | rooms.json 站 |")
        print("|---|---|---|---|---|---|---|")
        for n in sorted(pairs):
            ks = pairs[n]
            if len(ks) > 2:
                print("| %s | ? | **%d 条**（非 2 条，本表不适用） | | | | |" % (n, len(ks)))
                continue
            k1, k2 = ks
            a, b = polys[k1], polys[k2]
            inter = a.intersection(b).area
            rel = inter / min(a.area, b.area) if min(a.area, b.area) else 0.0
            cd = a.centroid.distance(b.centroid)
            ob = []
            for k in (k1, k2):
                others = [polys[j] for j in range(len(polys)) if j not in (k1, k2)]
                ob.append(sum(clean(polys[k].intersection(o)).area for o in others))
            wing = "A" if "-A-" in n else ("B" if "-B-" in n else "?")
            n_a += 1 if wing == "A" else 0
            n_b += 1 if wing == "B" else 0
            row = rj_by.get((n, fi))
            side = "—（rooms.json 无此行）"
            if row and row.get("boundary"):
                rb = Polygon(row["boundary"])
                d = []
                for k, p in ((k1, a), (k2, b)):
                    try:
                        d.append("copy%d 差 %.4f/距 %.3f m" % (k, p.symmetric_difference(rb).area,
                                                              p.centroid.distance(rb.centroid)))
                    except Exception:                                # noqa: BLE001
                        d.append("copy%d 算不了" % k)
                side = "；".join(d) + "（area_m2=%s）" % row.get("area_m2")
            line = ("| %s | %s | %.3f / %.3f | %.1f%% | %.3f / %.3f | %.2f | %s |"
                    % (n, wing, a.area, b.area, 100 * rel, ob[0], ob[1], cd, side))
            print(line)
            out.append(line)
        print()
    print("\n合计：A 翼 %d 对 / B 翼 %d 对" % (n_a, n_b))


if __name__ == "__main__":
    main()
