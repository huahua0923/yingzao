# -*- coding: utf-8 -*-
"""c006 交付 vs 新: 逐层墙集合差分(只读) —— 看清弧墙带到底加/减了什么。

按「顶点数 + bbox 四至(取整到 cm)」做签名配对, 打印只在一边出现的墙:
  新增(新独有) / 删除(旧独有), 给出 顶点数/壁厚/长度/面积/bbox/质心。
同时打印墙 dict 的键名, 便于后续探针取字段。
"""
import os, sys, json, glob, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d"]

TMP = r"D:\gym3d\_tmp_c006_arc"
DELIV = r"D:\gym3d\data\buildings\c006\floors"


def load(d):
    return {int(os.path.basename(f)[5:-5]): json.load(open(f, encoding="utf-8"))
            for f in glob.glob(os.path.join(d, "floor*.json"))}


def sig(w):
    q = w.get("poly") or []
    xs = [p[0] for p in q]
    ys = [p[1] for p in q]
    return (len(q), round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2))


def peri(q):
    return sum(math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1]) for i in range(len(q) - 1))


def area(q):
    n = len(q)
    return abs(sum(q[i][0] * q[(i + 1) % n][1] - q[(i + 1) % n][0] * q[i][1] for i in range(n))) / 2.0


new, old = load(TMP), load(DELIV)
F = int(sys.argv[1]) if len(sys.argv) > 1 else 2
ow = {sig(w): w for w in old[F]["walls"]}
nw = {sig(w): w for w in new[F]["walls"]}

print("墙 dict 键名: %s" % sorted(new[F]["walls"][0].keys()))
print("\n=== F%d  旧 %d 块 -> 新 %d 块 ===" % (F, len(ow), len(nw)))
added = [nw[k] for k in nw if k not in ow]
removed = [ow[k] for k in ow if k not in nw]
print("\n-- 新增 %d 块 --" % len(added))
for w in sorted(added, key=lambda w: -area(w["poly"]))[:10]:
    q = w["poly"]
    cx = sum(p[0] for p in q) / len(q)
    cy = sum(p[1] for p in q) / len(q)
    print("   顶点%3d  %s=%s  长%7.2fm 面积%7.2f㎡  质心(%7.2f,%7.2f)"
          % (len(q), "t", w.get("t", w.get("thickness", w.get("w"))),
             peri(q), area(q), cx, cy))
print("\n-- 删除 %d 块 --" % len(removed))
for w in sorted(removed, key=lambda w: -area(w["poly"]))[:10]:
    q = w["poly"]
    cx = sum(p[0] for p in q) / len(q)
    cy = sum(p[1] for p in q) / len(q)
    print("   顶点%3d  长%7.2fm 面积%7.2f㎡  质心(%7.2f,%7.2f)"
          % (len(q), peri(q), area(q), cx, cy))
