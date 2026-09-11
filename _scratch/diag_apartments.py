# -*- coding: utf-8 -*-
"""聚焦墙层诊断：真实楼层 Y 聚类(间距=offset)、X 总跨度、X 大间隙副本切分。
只读墙层(4.2墙体)，输出每栋楼的真值，用于修正 batch_profiles 的 offset/x_range。"""
import os
import sys
import ezdxf
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DXF_DIR = r"D:\dxf_output"
APARTMENTS = [
    ("c017", "C017-芙蓉园9号公寓"), ("c018", "C018-芙蓉园8号公寓"), ("c019", "C019-芙蓉园7号公寓"),
    ("c029", "C029-芙蓉园1号公寓"), ("c030", "C030-芙蓉园2号公寓"), ("c031", "C031-芙蓉园3号公寓"),
    ("c032", "C032-芙蓉园4号公寓"), ("c033", "C033-芙蓉园5号公寓"), ("c034", "C034-芙蓉园6号公寓"),
    ("c043", "C043-青年教师公寓1号楼"), ("c044", "C044-青年教师公寓2号楼"), ("c045", "C045-青年教师公寓3号楼"),
    ("c046", "C046-榕树园公寓"),
    ("c054", "C054-银杏园1号公寓"), ("c055", "C055-银杏园2号公寓"), ("c056", "C056-银杏园3号公寓"),
    ("c057", "C057-银杏园4号公寓"),
    ("c059", "C059-珙桐园1号公寓"), ("c060", "C060-珙桐园2号公寓"), ("c061", "C061-珙桐园3号公寓"),
    ("c062", "C062-珙桐园4号公寓"), ("c063", "C063-珙桐园5号公寓"), ("c064", "C064-珙桐园6号公寓"),
    ("c065", "C065-珙桐园7号公寓"),
    ("c072", "C072-松林园1号公寓"), ("c073", "C073-松林园2号公寓"),
    ("c079", "C079-香樟园1号公寓"), ("c080", "C080-香樟园2号公寓"), ("c083", "C083-香樟园3号公寓"),
    ("c084", "C084-香樟园4号公寓"), ("c085", "C085-香樟园5号公寓"), ("c086", "C086-香樟园6号公寓"),
    ("c109", "C109-十公寓"), ("c116", "C116-筇竹园公寓"),
    ("ny27", "NY27-人才公寓1栋"), ("ny28", "NY28-人才公寓2栋"), ("ny29", "NY29-人才公寓3栋"),
]


def y_clusters(ys, gap=3000):
    """质心 Y 聚类(墙厚度~0.3m、房间纵向~3m，故 gap=3000 按楼层间大间隙切)。"""
    wy = sorted(set(round(y) for y in ys))
    if not wy:
        return [], []
    clusters = [[wy[0]]]
    for y in wy[1:]:
        if y - clusters[-1][-1] > gap:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    centers = [round(sum(c) / len(c)) for c in clusters]
    gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
    return centers, gaps


def x_copy_clusters(xs, gap=50000):
    """质心 X 大间隙(>50m)切分副本。返回 [(min,max,count)] 降序。"""
    wx = sorted(set(round(x) for x in xs))
    if not wx:
        return []
    clusters = [[wx[0]]]
    for x in wx[1:]:
        if x - clusters[-1][-1] > gap:
            clusters.append([x])
        else:
            clusters[-1].append(x)
    return sorted([(min(c), max(c), len(c)) for c in clusters], key=lambda c: -c[2])


for name, dxf_name in APARTMENTS:
    path = os.path.join(DXF_DIR, dxf_name + ".dxf")
    if not os.path.exists(path):
        print(f"===== {name} [缺失] =====")
        continue
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    # 墙层 = 含"墙体/4.2/4墙"且 LWPOLYLINE 最多的层
    ltype = Counter()
    for e in msp:
        t = e.dxftype()
        if t == "LWPOLYLINE":
            ltype[e.dxf.layer] += 1
    wall_layer = max([l for l in ltype if any(k in l for k in ("墙体", "4.2", "4墙"))], key=lambda l: ltype[l])

    xs, ys, vx = [], [], []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == wall_layer:
            pts = [tuple(p[:2]) for p in e.get_points()]
            if len(pts) < 2:
                continue
            xs.append(sum(p[0] for p in pts) / len(pts))
            ys.append(sum(p[1] for p in pts) / len(pts))
            vx += [p[0] for p in pts]

    cents, gaps = y_clusters(ys)
    xc = x_copy_clusters(xs)
    span = (max(vx) - min(vx)) / 1000 if vx else 0
    print(f"{name:5s} 墙层={wall_layer} 实体={len(xs)} 顶点X跨度={span:.0f}m "
          f"Y层={len(cents)} 中心={cents} 间距={gaps}")
    if len(xc) >= 2:
        print(f"       X副本簇(>50m切): {[(round(a/1000), round(b/1000), n) for a, b, n in xc]}")
    elif xc:
        print(f"       X单簇: [{round(xc[0][0]/1000)}, {round(xc[0][1]/1000)}]m")
