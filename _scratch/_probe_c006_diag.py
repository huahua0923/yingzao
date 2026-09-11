# -*- coding: utf-8 -*-
"""c006 弧墙内容度量: 「斜向墙段总长」(只读)。

柱子在 fl["columns"] 里, 不混入。墙若含斜向段(非 0°/90°), 只能是弧墙离散化或斜墙。
比较 交付 vs 新, 逐层给: 斜向段总长 / 斜向墙块数 / 其壁厚分布 / bbox。

用法: python _probe_c006_diag.py
"""
import os, sys, json, glob, math, collections
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TMP = r"D:\gym3d\_tmp_c006_arc"
DELIV = r"D:\gym3d\data\buildings\c006\floors"


def load(d):
    return {int(os.path.basename(f)[5:-5]): json.load(open(f, encoding="utf-8"))
            for f in glob.glob(os.path.join(d, "floor*.json"))}


def diag(fl):
    """返回 (斜段总长, 含斜段的墙块数, 每块 (顶点, thickness, 斜长, 质心), 壁厚分布)。"""
    L = 0.0
    blocks = []
    ts = collections.Counter()
    for w in fl.get("walls", []):
        q = w.get("poly") or []
        bl = 0.0
        for i in range(len(q) - 1):
            dx = abs(q[i + 1][0] - q[i][0])
            dy = abs(q[i + 1][1] - q[i][1])
            seg = math.hypot(dx, dy)
            if seg > 1e-9 and min(dx, dy) / seg > 0.02:      # 非轴对齐
                bl += seg
        if bl > 0.05:
            L += bl
            cx = sum(p[0] for p in q) / len(q)
            cy = sum(p[1] for p in q) / len(q)
            t = float(w.get("thickness", 0))
            blocks.append((len(q), t, bl, cx, cy))
            ts[round(t, 2)] += 1
    return L, blocks, ts


new, old = load(TMP), load(DELIV)
print("%-5s | %-30s | %-30s" % ("层", "交付: 斜段长/块数/壁厚", "新: 斜段长/块数/壁厚"))
for F in sorted(new):
    Lo, bo, tso = diag(old.get(F, {}))
    Ln, bn, tsn = diag(new[F])
    d = Ln - Lo
    print("  F%-2d | %7.1fm %3d块 %-18s | %7.1fm %3d块 %-18s | %+7.1fm"
          % (F, Lo, len(bo), str(dict(sorted(tso.items())))[:18],
             Ln, len(bn), str(dict(sorted(tsn.items())))[:18], d))
print("\n-- F2 斜墙块明细 (按斜长排序, 前 20) --")
Lo, bo, _ = diag(old[2])
Ln, bn, _ = diag(new[2])
print("  交付 %d 块:" % len(bo))
for nv, t, bl, cx, cy in sorted(bo, key=lambda x: -x[2])[:12]:
    print("     顶点%3d 厚%.2f 斜长%7.2fm 质心(%7.2f,%7.2f)" % (nv, t, bl, cx, cy))
print("  新 %d 块:" % len(bn))
for nv, t, bl, cx, cy in sorted(bn, key=lambda x: -x[2])[:12]:
    print("     顶点%3d 厚%.2f 斜长%7.2fm 质心(%7.2f,%7.2f)" % (nv, t, bl, cx, cy))
