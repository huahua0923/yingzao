# -*- coding: utf-8 -*-
"""c009 首层墙层原始实体普查(只读): 是「图上本来就少」还是「分类阶段被丢了」。

_probe_c009_floor0 显示首层只分类出 151 条墙折线/1063m, 而 1~5 层各 763~888 条/~4000m。
本探针按楼层桶统计 **墙层上全部原始实体**(不过分类器), 按类型/闭合/顶点数/面积分布,
判断首层是:
  (a) 图上确实画得少(开放式柱廊/架空层)
  (b) 画成填充实心块(涂黑), 被 classify 当"楼板填充"剔除
  (c) 用了别的实体类型(LINE/POLYLINE/HATCH), 分类器不认

用法: python _probe_c009_raw.py [c009]
"""
import sys, os, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend", r"D:\gym3d\backend\web"]

import ezdxf
from run_building import load_profile
from backend.recognizer.profile import floor_of, to_local, in_floor_x_range

nm = sys.argv[1] if len(sys.argv) > 1 else "c009"
p = load_profile(nm)
doc = ezdxf.readfile(p.dxf)

per = collections.defaultdict(lambda: collections.Counter())
per_len = collections.defaultdict(float)
lwp_shape = collections.defaultdict(collections.Counter)
skipped = collections.Counter()

for e in doc.modelspace():
    if e.dxf.layer != p.wall_layer:
        continue
    t = e.dxftype()
    # 取质心
    try:
        if t == "LINE":
            xs = [float(e.dxf.start.x), float(e.dxf.end.x)]
            ys = [float(e.dxf.start.y), float(e.dxf.end.y)]
        elif t == "ARC":
            q = list(e.flattening(50.0))
            xs = [float(a[0]) for a in q]; ys = [float(a[1]) for a in q]
        elif t in ("LWPOLYLINE",):
            q = list(e.get_points("xyseb"))
            xs = [float(a[0]) for a in q]; ys = [float(a[1]) for a in q]
        elif t == "POLYLINE":
            xs = [float(v.dxf.location.x) for v in e.vertices]
            ys = [float(v.dxf.location.y) for v in e.vertices]
        else:
            skipped[t] += 1
            continue
    except Exception:
        skipped[t] += 1
        continue
    if not xs:
        continue
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    if not in_floor_x_range(p, cx):
        skipped["X区间外:" + t] += 1
        continue
    F = int(round(floor_of(p, cx, cy)))
    per[F][t] += 1
    if t == "LWPOLYLINE":
        q = list(e.get_points("xyseb"))
        per[F]["折叠点数%d" % 0] += 0
        lwp_shape[F][(len(q), bool(e.closed))] += 1
        # 近似面积(鞋带)
        loc = [to_local(p, float(a[0]), float(a[1]), F) for a in q]
        n = len(loc)
        if n >= 3:
            A = abs(sum(loc[i][0] * loc[(i + 1) % n][1] - loc[(i + 1) % n][0] * loc[i][1]
                        for i in range(n))) / 2.0
        else:
            A = 0.0
        per_len[F] += 0
        if A >= 4.0:
            per[F]["LWP_大面积块"] += 1
        elif A >= 0.5:
            per[F]["LWP_中块"] += 1

print("== %s 墙层原始实体按层统计(不过分类器) ==" % nm)
ks = sorted(per)
allt = sorted({t for F in ks for t in per[F]})
print("  %-4s %s" % ("层", " ".join("%-16s" % t for t in allt)))
for F in ks:
    print("  %-4d %s" % (F, " ".join("%-16d" % per[F][t] for t in allt)))
print("\n  被跳过(非墙层/取不到几何/X区间外): %s" % dict(skipped))
print("\n  -- LWPOLYLINE 形状分布(顶点数, 闭合) 前 8 --")
for F in ks:
    top = lwp_shape[F].most_common(8)
    print("     层%-3d %s" % (F, ", ".join("%d点%s x%d" % (n, "闭合" if c else "开口", k)
                                          for (n, c), k in top)))
