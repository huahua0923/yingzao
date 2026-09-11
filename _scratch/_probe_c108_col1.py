# -*- coding: utf-8 -*-
"""列1 那块到底是第5层平面，还是屋顶/机房平面？按「房间号图层」的文字落位判定。

思路：房间号 MTEXT 按所在块的 X 归属列0/列1，再看它的楼层前缀（108-0N-xx）。
列1 若没有房号 → 它不是「可入住层」，是屋顶/机房类平面。
另附：面积图层的数值也一并看，交叉印证。
"""
import re
import sys
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf  # noqa: E402

DXF = r"D:\dxf_output\C108-网安楼.dxf"
doc = ezdxf.readfile(DXF)
msp = doc.modelspace()

COL_SPLIT = 1_500_000   # 列0 在 ~1.2e6，列1 在 ~1.87e6，取中间值分界


def clean(t):
    t = re.sub(r"\{\\[^}]*;", "", t or "")
    t = re.sub(r"\\[A-Za-z][^;]*;", "", t)
    return t.replace("}", "").replace("\\P", "|").strip()


def collect(layer):
    """每行 [(x,y,文本)]。MTEXT 用 insert 点；TEXT 同。"""
    out = []
    for e in msp:
        if e.dxf.layer != layer:
            continue
        if e.dxftype() == "MTEXT":
            t = clean(e.text)
        elif e.dxftype() == "TEXT":
            t = clean(e.dxf.text)
        else:
            continue
        if not t:
            continue
        try:
            p = e.dxf.insert
        except Exception:
            continue
        out.append((p.x, p.y, t))
    return out


for layer in ("6房间号", "5面积", "7使用单位", "8用途"):
    rows = collect(layer)
    c0 = [r for r in rows if r[0] < COL_SPLIT]
    c1 = [r for r in rows if r[0] >= COL_SPLIT]
    print("=== %s: 共 %d 条 | 列0 %d 条 / 列1 %d 条 ===" % (layer, len(rows), len(c0), len(c1)))
    if c0:
        print("   列0 样例:", [t for _, _, t in c0[:6]])
    if c1:
        print("   列1 样例:", [t for _, _, t in c1[:6]])
    print()

# 楼层前缀统计（只对房间号）
rooms = collect("6房间号")
pref = collections.Counter()
for _, _, t in rooms:
    m = re.match(r"(\d{3})-(\d{2})-", t)
    if m:
        pref[m.group(2)] += 1
    else:
        pref["(非标准 " + t[:14] + ")"] += 1
print("=== 房号楼层前缀统计 ===")
for k, v in sorted(pref.items()):
    print("   %-16s %d" % (k, v))

# 每个房间号的 X/Y，按列分组看它在哪块的哪一行
print("\n=== 列0 房号的 Y 分布（对应4个平面块）===")
ys = sorted(y for x, y, t in rooms if x < COL_SPLIT and re.match(r"\d{3}-\d{2}-", t))
if ys:
    bands = []
    for y in ys:
        if not bands or y - bands[-1][-1] > 20000:
            bands.append([y])
        else:
            bands[-1].append(y)
    for b in bands:
        print("   Y %8.0f ~ %8.0f  (%d 条房号)" % (b[0], b[-1], len(b)))

print("\n=== 列1 房号的 Y 分布 ===")
ys1 = sorted(y for x, y, t in rooms if x >= COL_SPLIT and re.match(r"\d{3}-\d{2}-", t))
if ys1:
    bands = []
    for y in ys1:
        if not bands or y - bands[-1][-1] > 20000:
            bands.append([y])
        else:
            bands[-1].append(y)
    for b in bands:
        print("   Y %8.0f ~ %8.0f  (%d 条房号)" % (b[0], b[-1], len(b)))
else:
    print("   列1 无标准房号")
