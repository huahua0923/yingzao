# -*- coding: utf-8 -*-
"""确认 c006 弧墙带真的进了模型(只读对比 交付 vs 临时)。

弧墙带的特征: 由 pair_arc_bands 生成的环形扇区离散化(矢高 10mm) → 顶点数多(半圆 ~66 点)、
壁厚 0.232~0.239m、沿弧总长可观。直墙块是 4 顶点矩形。

量每层: 顶点>=16 的墙(弧带候选)块数 / 总长 / 总面积 / 壁厚分布, 交付 vs 新。
"""
import os, sys, json, glob, collections, math
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d"]

TMP = r"D:\gym3d\_tmp_c006_arc"
DELIV = r"D:\gym3d\data\buildings\c006\floors"
NV_MIN = 16


def load(d):
    return {int(os.path.basename(f)[5:-5]): json.load(open(f, encoding="utf-8"))
            for f in glob.glob(os.path.join(d, "floor*.json"))}


def analyze(fl):
    n_arc = 0
    L = 0.0
    A = 0.0
    ts = collections.Counter()
    for w in fl.get("walls", []):
        q = w.get("poly") or []
        if len(q) < NV_MIN:
            continue
        n_arc += 1
        A += abs(sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1]
                   for i in range(len(q)))) / 2.0
        for i in range(len(q) - 1):
            L += math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1])
        ts[round(float(w.get("t", 0)), 2)] += 1
    return n_arc, L, A, ts


new, old = load(TMP), load(DELIV)
print("%-5s | %-16s | %-16s" % ("层", "交付: 弧块/弧长m/面积㎡", "新: 弧块/弧长m/面积㎡"))
tot_o = tot_n = 0.0
for F in sorted(new):
    no, Lo, Ao, to = analyze(old.get(F, {}))
    nn, Ln, An, tn = analyze(new[F])
    tot_o += Lo
    tot_n += Ln
    mark = "   <<< 新增弧墙" if nn > no else ""
    print("  F%-2d | %3d块 %7.1fm %7.1f㎡ | %3d块 %7.1fm %7.1f㎡%s"
          % (F, no, Lo, Ao, nn, Ln, An, mark))
print("  弧长合计: 交付 %.1f m -> 新 %.1f m" % (tot_o, tot_n))
last = sorted(new)[-1]
print("  顶层 F%d 新弧墙壁厚分布: %s" % (last, dict(analyze(new[last])[3])))
podium = [F for F in sorted(new) if F <= 5]
print("  裙楼 F0-F5 新壁厚分布: %s"
      % dict(sum((collections.Counter(analyze(new[F])[3]) for F in podium), collections.Counter())))
