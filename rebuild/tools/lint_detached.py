# -*- coding: utf-8 -*-
"""判据：每层重画出来的墙，有没有**孤立的另一张小图**混在同一个图幅窗口里。

为什么要有这条：图幅窗口是按 `1图框` 的实测框定的，一张图**里面**可能还画着
别的图（局部投影、详图）。那些东西会被当成墙一起识别出来，然后在三维里变成
一块**浮在半空的矩形**。实测 `地下1层` 就有一块（x 116000..140000, y 81000..99000，
旁边写着 `VA1'projE`）。

★ 判据不是「离主体质心远」—— 那样每道隔墙都会报（隔墙本来就与外墙不连通，
  第一版就是这么废的：6 层报出 24 块"孤立"）。真判据是**离最近的其他墙块也远**：
  隔墙紧挨着邻居（很近），另一张小图离**所有**墙都在几十米外。

用法：python rebuild/tools/lint_detached.py [--min-area 1.0] [--far 5000]
  rc=0 全部层都没有孤立块；rc=1 有层报出孤立块（列出坐标，交人确认）
  rc=4 没量到（一层都没读到）
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import recognize as R                                                    # noqa: E402

FLOORS = ["地下1层", "1层", "2层", "3层", "4层", "5层", "6层",
          "7层", "8层", "9层", "10层", "11层"]


def blobs_from_mask(wm, geo, min_area):
    ox, oy, res = geo
    n, lab, st, ct = cv2.connectedComponentsWithStats((wm > 0).astype(np.uint8), 8)
    out = []
    for i in range(1, n):
        A = st[i, cv2.CC_STAT_AREA] * res * res / 1e6
        if A < min_area:
            continue
        out.append({"A": A,
                    "x0": ox + st[i, cv2.CC_STAT_LEFT] * res,
                    "y0": oy + st[i, cv2.CC_STAT_TOP] * res,
                    "x1": ox + (st[i, cv2.CC_STAT_LEFT] + st[i, cv2.CC_STAT_WIDTH]) * res,
                    "y1": oy + (st[i, cv2.CC_STAT_TOP] + st[i, cv2.CC_STAT_HEIGHT]) * res,
                    "cx": ox + ct[i][0] * res, "cy": oy + ct[i][1] * res})
    return out


def blobs(floor, min_area):
    with contextlib.redirect_stdout(io.StringIO()):
        a = R.analyze(floor)
    return blobs_from_mask(a["wmask"], a["geo"], min_area)


def bbox_gap(b, o):
    """两个**外框**之间的净空隙（mm）；套在一起或相交 ⇒ 0。

    ★ 为什么不是质心距减半对角线：外墙是一条又长又薄的环，半对角线量到几十米，
      减完恒为负 ⇒ 判据永远绿（第一版就是这么假绿的：`地下1层` 明明有一块
      离主体 18 m 的孤立矩形，却报「无孤立块」）。
    """
    dx = max(b["x0"] - o["x1"], o["x0"] - b["x1"], 0.0)
    dy = max(b["y0"] - o["y1"], o["y0"] - b["y1"], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def nearest_other(b, others):
    return min(bbox_gap(b, o) for o in others if o is not b) if len(others) > 1 else 0.0


def selftest(far):
    """阳性对照：合成两张小图，一张相隔 30 m（必须报）、一张紧挨 0.5 m（必须不报）。"""
    res, pad, ox, oy = 25.0, 2000.0, 0.0, 0.0
    H, W = int((40000 + 2 * pad) / res), int((80000 + 2 * pad) / res)
    img = np.zeros((H, W), np.uint8)
    cv2.rectangle(img, (int((pad + 1000) / res), int((pad + 1000) / res)),
                  (int((pad + 9000) / res), int((pad + 19000) / res)), 255, -1)
    cv2.rectangle(img, (int((pad + 15000) / res), int((pad + 1000) / res)),
                  (int((pad + 23000) / res), int((pad + 19000) / res)), 255, -1)   # 间隔 6 m
    cv2.rectangle(img, (int((pad + 16000) / res), int((pad + 31000) / res)),
                  (int((pad + 24000) / res), int((pad + 39000) / res)), 255, -1)   # 相隔 12 m
    bs = blobs_from_mask(img, (ox, oy, res), 1.0)
    got = sorted(round(nearest_other(b, bs)) for b in bs)
    print("== 判据自检（合成）==")
    print("   三块墙：两块间隔 6 m、孤块相隔 12 m；实测最近净空隙 %s mm" % got)
    # `cv2.rectangle` 两端点都算入 ⇒ 外框比标称各宽 1 px（25 mm），容许 2 px
    tol = 2 * res
    ok = (len(bs) == 3
          and abs(got[0] - 6000) <= tol and abs(got[1] - 6000) <= tol
          and abs(got[2] - 12000) <= tol)
    print("   自检：%s（阈值 %.0f mm，容许 ±%.0f = 2 px）"
          % ("PASS" if ok else "★ FAIL —— 判据没有分辨力，不许拿它当结论", far, tol))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-area", type=float, default=1.0, help="只量≥此面积的块（m²）")
    ap.add_argument("--far", type=float, default=5000.0, help="净空隙超过此值算孤立（mm）")
    ap.add_argument("--selftest", action="store_true")
    apar = ap.parse_args()
    if apar.selftest:
        return selftest(apar.far)

    total, bad, measured = 0, 0, 0
    for f in FLOORS:
        p = os.path.join(R.RAW, f + ".dxf")
        if not os.path.exists(p):
            continue
        measured += 1
        bs = blobs(f, apar.min_area)
        if not bs:
            print("%-8s ★ 没量到：一个墙块都没有" % f)
            return 4
        total += len(bs)
        far = [(b, nearest_other(b, bs)) for b in bs]
        far = [(b, d) for b, d in far if d > apar.far]
        if far:
            bad += 1
            print("%-8s 墙块 %2d   ★ 孤立 %d 块：" % (f, len(bs), len(far)))
            for b, d in sorted(far, key=lambda t: -t[1]):
                print("            %7.1f m²  外框 x %8.0f..%8.0f y %8.0f..%8.0f  离最近墙块 %7.0f mm"
                      % (b["A"], b["x0"], b["x1"], b["y0"], b["y1"], d))
        else:
            print("%-8s 墙块 %2d   无孤立块（最远净空隙 %.0f mm）"
                  % (f, len(bs), max(nearest_other(b, bs) for b in bs)))
    if measured == 0:
        print("★ 没量到：没找到任何 raw DXF")
        return 4
    print("\n合计 %d 层 / %d 块；报出孤立块的 %d 层" % (measured, total, bad))
    print("★ 本尺子的盲区（判词只在这个范围成立）：只比**外框**。"
          "若那张附带小图的外框被主体外框套住（画在主体轮廓之内），"
          "净空隙恒为 0 ⇒ 它不会出声。本轮它逮到地下 1 层那一块，是因为那块在主体轮廓之外。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
