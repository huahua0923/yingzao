# -*- coding: utf-8 -*-
"""c108 的平面图排布：X/Y 聚类分出「块」，再判定是单列(靠 offset)还是多列(要 floor_plans)。

detect_params 只给了一个 offset/cx/cy，前提是「全楼各层沿 Y 等距重复」。
c108 墙层 X 跨 732m 远超单栋尺度，说明图纸是横向并排多块 —— 那种情况必须给
floor_plans 逐层 [cx,cy,xmin,xmax]，否则识别会把隔壁块的墙也算进本层。
"""
import sys
import collections
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf  # noqa: E402

DXF = r"D:\dxf_output\C108-网安楼.dxf"
WALL = "4.2墙体"
GAP_X = 20000.0    # 块间 X 间隔 >20m 才算换块
GAP_Y = 20000.0

doc = ezdxf.readfile(DXF)
msp = doc.modelspace()

boxes = []
for e in msp:
    if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == WALL:
        pts = [tuple(p[:2]) for p in e.get_points()]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append((min(xs), max(xs), min(ys), max(ys)))

print("墙 LWPOLYLINE:", len(boxes))
if not boxes:
    sys.exit(1)


def cluster(vals, gap):
    """把区间按间隔并成簇，返回 [(lo,hi), ...]。"""
    vals = sorted(vals)
    out = [[vals[0][0], vals[0][1]]]
    for lo, hi in vals[1:]:
        if lo - out[-1][1] > gap:
            out.append([lo, hi])
        else:
            out[-1][1] = max(out[-1][1], hi)
    return [(round(a), round(b)) for a, b in out]


xcols = cluster([(b[0], b[1]) for b in boxes], GAP_X)
print("\n=== X 向分块（间隔>%dm）: %d 块 ===" % (GAP_X / 1000, len(xcols)))
for i, (lo, hi) in enumerate(xcols):
    print("  列%d: X %8d ~ %8d  宽 %7.1f m" % (i, lo, hi, (hi - lo) / 1000))

for i, (lo, hi) in enumerate(xcols):
    sub = [b for b in boxes if b[0] >= lo - 1 and b[1] <= hi + 1]
    yrows = cluster([(b[2], b[3]) for b in sub], GAP_Y)
    print("\n=== 列%d 内 Y 分块（%d 个墙实体）: %d 行 ===" % (i, len(sub), len(yrows)))
    for j, (y0, y1) in enumerate(yrows):
        # 该行内 X/墙数
        bx = [b for b in sub if b[2] >= y0 - 1 and b[3] <= y1 + 1]
        if not bx:
            continue
        x0 = min(b[0] for b in bx)
        x1 = max(b[1] for b in bx)
        print("    行%-2d: Y %8d ~ %8d 高 %6.1f m | X %8d~%8d 宽 %6.1f m | 墙 %d"
              % (j, y0, y1, (y1 - y0) / 1000, x0, x1, (x1 - x0) / 1000, len(bx)))

# 楼层间距核对：把每一行块按 Y 中心排序，看相邻差
rows_all = []
for i, (lo, hi) in enumerate(xcols):
    sub = [b for b in boxes if b[0] >= lo - 1 and b[1] <= hi + 1]
    for y0, y1 in cluster([(b[2], b[3]) for b in sub], GAP_Y):
        bx = [b for b in sub if b[2] >= y0 - 1 and b[3] <= y1 + 1]
        if bx:
            rows_all.append({"col": i, "y0": y0, "y1": y1, "yc": (y0 + y1) // 2,
                             "x0": min(b[0] for b in bx), "x1": max(b[1] for b in bx),
                             "n": len(bx)})
rows_all.sort(key=lambda r: (r["col"], r["yc"]))
print("\n=== 逐行汇总（供写 floor_plans / floor_ys 用）===")
for r in rows_all:
    print("  列%d yc=%8d  X %.0f~%.0f  (%.1f m 宽)  墙%3d"
          % (r["col"], r["yc"], r["x0"], r["x1"], (r["x1"] - r["x0"]) / 1000, r["n"]))

json.dump(rows_all, open(r"D:\gym3d\_scratch\_c108_blocks.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n已写 _scratch/_c108_blocks.json")
