# -*- coding: utf-8 -*-
"""c006 柱(INSERT块)按 Y 行聚类, 比较左右列(裙楼列/塔楼列)内各行的柱网X是否一致。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d")
import ezdxf
from run_building import load_profile

def main():
    p = load_profile("c006")
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    ins = []
    for e in msp:
        if e.dxftype() == "INSERT":
            x = e.dxf.insert.x
            y = e.dxf.insert.y
            if 1000000 < x < 1700000:
                ins.append((round(x), round(y)))
    print("c006 INSERT 总数(in X 1.0-1.7M):", len(ins))

    # 行聚类 (行间距约 135000)
    rows = sorted(set(y for _, y in ins))
    groups = []
    cur = []
    last = None
    for y in rows:
        if last is None or y - last < 50000:
            cur.append(y)
            last = y
        else:
            groups.append(cur)
            cur = [y]
            last = y
    if cur:
        groups.append(cur)

    def summary(xs):
        if not xs:
            return "0"
        xuniq = sorted(set(xs))
        n = len(xuniq)
        # 网格粗列: 跳变>2000 视为新列线
        lines = [xuniq[0]]
        for a, x in zip(xuniq, xuniq[1:]):
            if x - a > 2000:
                lines.append(x)
        step = []
        for a, x in zip(lines, lines[1:]):
            step.append(round((x - a) / 1000, 2))
        return "n=%d 列线=%s 步长=%s" % (n, [round(x / 1000, 2) for x in lines][:8], step[:6])

    for i, g in enumerate(groups):
        ym = sum(g) / len(g)
        left = [x for x, y in ins if y in g and x < 1300000]
        right = [x for x, y in ins if y in g and x >= 1300000]
        print("行%d Y中%.0f | 左(裙楼列): %s | 右(塔楼列): %s" % (
            i, ym, summary(left), summary(right)))

if __name__ == "__main__":
    main()
