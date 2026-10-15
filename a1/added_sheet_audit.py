# -*- coding: utf-8 -*-
"""新规则比旧规则多选出来的那些图幅，**到底是真平面图还是空图框**？

背景：把 `gridify` 改成「列或行任一成条带即保留」后，全库几乎每栋都多出 ~1 张。
  +1 可能是两件完全不同的事，**必须分开**：
    (a) 找到了一张**真平面图**（旧规则因它 X 独特而丢了）⇒ 是**修对了**；
    (b) 吸进了一个**空图框/图签框**（与某一行同 Y 而已）⇒ 是**假阳性**，要收规则。
判据：数该图幅里的**墙实体**。真平面图必有墙，图签/说明框没有。

正对照：C006 多出来的那张应≈0 墙（已知是靠原点的图签框）。
"""
import collections
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
import sheet_grid as SG                                    # noqa: E402
import ezdxf                                               # noqa: E402

SRC = Path(r"D:\项目\gym3d\材料\dxf_output")
MINW = 50


def gridify_old(std, min_col=2):
    """旧规则：只按 X 聚列（原样抄自改前的 sheet_grid.gridify）。"""
    if not std:
        return []
    cols = []
    for s in sorted(std, key=lambda s: s["bbox"][0]):
        for c in cols:
            ov = max(0.0, min(s["bbox"][2], c["box"][2]) - max(s["bbox"][0], c["box"][0]))
            if ov > 0.5 * min(s["bbox"][2] - s["bbox"][0], c["box"][2] - c["box"][0]):
                c["box"] = (min(c["box"][0], s["bbox"][0]), min(c["box"][1], s["bbox"][1]),
                            max(c["box"][2], s["bbox"][2]), max(c["box"][3], s["bbox"][3]))
                c["m"].append(s)
                break
        else:
            cols.append({"box": s["bbox"], "m": [s]})
    cols = [c for c in cols if len(c["m"]) >= min_col]
    return [s for c in cols for s in c["m"]]


def wall_in(msp, bb):
    wl = {e.dxf.layer for e in msp if any(h in e.dxf.layer for h in ("墙体", "封墙", "4墙体"))}
    n = 0
    for e in msp:
        if e.dxf.layer not in wl:
            continue
        t = e.dxftype()
        try:
            if t == "LINE":
                x, y = ((e.dxf.start.x + e.dxf.end.x) / 2, (e.dxf.start.y + e.dxf.end.y) / 2)
            elif t == "LWPOLYLINE":
                p = list(e.get_points())
                if not p:
                    continue
                x, y = sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p)
            else:
                continue
        except Exception:                                   # noqa: BLE001
            continue
        if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]:
            n += 1
    return n


def audit(name):
    doc = ezdxf.readfile(str(SRC / name))
    msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    sheets = SG.merge_pairs(SG.collect_frames(msp, layer))

    def chosen(gridify):
        # 复刻 classify 的选择逻辑：按 (kept 张数, 面积) 选尺寸组
        by = collections.defaultdict(list)
        for s in sheets:
            by[(round(s["bbox"][2] - s["bbox"][0]), round(s["bbox"][3] - s["bbox"][1]))].append(s)
        best = None
        for k, grp in by.items():
            kept = gridify(grp)
            sc = (len(kept), k[0] * k[1])
            if kept and (best is None or sc > best[0]):
                best = (sc, k, kept)
        return [] if not best else best[2]

    old = chosen(gridify_old)
    new = chosen(SG.gridify)
    key = lambda s: tuple(round(v) for v in s["bbox"])
    said = {key(s) for s in old}
    added = [s for s in new if key(s) not in said]
    print("\n=== %s ===  旧 %d 张 → 新 %d 张" % (name, len(old), len(new)))
    for s in added:
        n = wall_in(msp, s["bbox"])
        b = s["bbox"]
        print("   多出 x[%.0f,%.0f] y[%.0f,%.0f]  %dx%d m 墙 %d  %s"
              % (b[0], b[2], b[1], b[3], (b[2] - b[0]) // 1000, (b[3] - b[1]) // 1000, n,
                 "★真平面图" if n >= MINW else "空图框/假阳性"))
    return len(added), sum(1 for s in added if wall_in(msp, s["bbox"]) >= MINW)


def main():
    names = sys.argv[1:] or [
        "C006-第六教学楼（逸夫楼）.dxf", "C001-砚湖图书馆.dxf", "C007-综合楼.dxf",
        "C019-芙蓉园7号公寓.dxf", "C022-第七教学楼（致远楼）.dxf", "C002-南翼楼.dxf",
        "C004F2-砚湖会议厅.dxf", "C066-珙桐餐厅.dxf", "L002-风景园林生态观测场.dxf",
    ]
    tot_add = tot_real = 0
    for n in names:
        a, r = audit(n)
        tot_add += a
        tot_real += r
    print("\n合计：多出 %d 张，其中真平面图 %d 张，空图框 %d 张" % (tot_add, tot_real, tot_add - tot_real))
    return 0


sys.exit(main())
