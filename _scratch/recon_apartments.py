# -*- coding: utf-8 -*-
r"""37 栋公寓侦查：实体类型 / 图层 / LWPOLYLINE&LINE 的 Y 聚类(楼层+OFFSET) / 中心。
只输出写 BuildingProfile 需要的关键字段。公寓 DWG 已转 DXF 到 D:\dxf_output。"""
import os
import sys
import ezdxf
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DXF_DIR = r"D:\dxf_output"

# 公寓文件名（按 D:\学校建筑 实际清单）
APARTMENTS = [
    "C017-芙蓉园9号公寓", "C018-芙蓉园8号公寓", "C019-芙蓉园7号公寓",
    "C029-芙蓉园1号公寓", "C030-芙蓉园2号公寓", "C031-芙蓉园3号公寓",
    "C032-芙蓉园4号公寓", "C033-芙蓉园5号公寓", "C034-芙蓉园6号公寓",
    "C043-青年教师公寓1号楼", "C044-青年教师公寓2号楼", "C045-青年教师公寓3号楼",
    "C046-榕树园公寓",
    "C054-银杏园1号公寓", "C055-银杏园2号公寓", "C056-银杏园3号公寓", "C057-银杏园4号公寓",
    "C059-珙桐园1号公寓", "C060-珙桐园2号公寓", "C061-珙桐园3号公寓",
    "C062-珙桐园4号公寓", "C063-珙桐园5号公寓", "C064-珙桐园6号公寓", "C065-珙桐园7号公寓",
    "C072-松林园1号公寓", "C073-松林园2号公寓",
    "C079-香樟园1号公寓", "C080-香樟园2号公寓", "C083-香樟园3号公寓",
    "C084-香樟园4号公寓", "C085-香樟园5号公寓", "C086-香樟园6号公寓",
    "C109-十公寓", "C116-筇竹园公寓",
    "NY27-人才公寓1栋", "NY28-人才公寓2栋", "NY29-人才公寓3栋",
]


def y_clusters(ys, gap=5000):
    """Y(mm) 排序去重后按 gap 聚类，返回每簇中心 + 相邻间距。"""
    wy = sorted(set(round(y) for y in ys))
    if not wy:
        return [], []
    clusters = [[wy[0]]]
    for y in wy[1:]:
        if y - clusters[-1][-1] > gap:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    centers = [sum(c) / len(c) for c in clusters]
    gaps = [round(centers[i + 1] - centers[i]) for i in range(len(centers) - 1)]
    return centers, gaps


for name in APARTMENTS:
    path = os.path.join(DXF_DIR, name + ".dxf")
    if not os.path.exists(path):
        print(f"\n===== {name}  [DXF 缺失] =====")
        continue
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    etypes = Counter()
    layers = Counter()
    layer_types = {}
    lw_x, lw_y = [], []
    ln_x, ln_y = [], []
    inserts = Counter()
    for e in msp:
        t = e.dxftype()
        etypes[t] += 1
        lay = e.dxf.layer if hasattr(e.dxf, "layer") else "(none)"
        layers[lay] += 1
        layer_types.setdefault(lay, Counter())[t] += 1
        if t == "LWPOLYLINE":
            try:
                for x, y in [tuple(p[:2]) for p in e.get_points()]:
                    lw_x.append(x)
                    lw_y.append(y)
            except Exception:
                pass
        elif t == "LINE":
            ln_x += [e.dxf.start.x, e.dxf.end.x]
            ln_y += [e.dxf.start.y, e.dxf.end.y]
        elif t == "INSERT":
            inserts[e.dxf.name] += 1

    print(f"\n===== {name} =====")
    print(f"  实体: {dict(etypes.most_common())}")
    wall_layers = [(l, c) for l, c in layers.most_common()
                   if any(k in l for k in ("墙", "WALL", "柱", "COL", "墙体"))]
    print(f"  墙/柱候选图层: {wall_layers[:12]}")
    print(f"  Top图层: {[(l, c) for l, c in layers.most_common(8)]}")

    if lw_x:
        cx = (min(lw_x) + max(lw_x)) / 2
        cents, gaps = y_clusters(lw_y)
        print(f"  LWPOLYLINE: X[{min(lw_x):.0f},{max(lw_x):.0f}] 宽{(max(lw_x)-min(lw_x))/1000:.0f}m "
              f"Y[{min(lw_y):.0f},{max(lw_y):.0f}]")
        print(f"    cx={cx:.0f}  Y聚类={len(cents)}层 中心={[round(c) for c in cents]} 间距={gaps}")
    else:
        print("  LWPOLYLINE: 无")

    if ln_x:
        cx = (min(ln_x) + max(ln_x)) / 2
        cents, gaps = y_clusters(ln_y)
        print(f"  LINE: X[{min(ln_x):.0f},{max(ln_x):.0f}] 宽{(max(ln_x)-min(ln_x))/1000:.0f}m "
              f"Y[{min(ln_y):.0f},{max(ln_y):.0f}]")
        print(f"    cx={cx:.0f}  Y聚类={len(cents)}层 中心={[round(c) for c in cents]} 间距={gaps}")
    else:
        print("  LINE: 无")

    if inserts:
        print(f"  INSERT块: {dict(inserts.most_common(8))}")
