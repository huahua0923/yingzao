# -*- coding: utf-8 -*-
r"""把 D-24（房间面片面积 ≠ 图上面积）的黄/红阈值由**全仓实测分布**现算，写进 参数.json。

为什么要有它（用户 2026-10-20「这个杂物间有 100 多平方，你把过道识别成杂物间了」）：
  包里每间房的 `poly` 是**整片连通空闲区**（楼板 − 墙带），`stated_m2` 是图上写的面积。
  两者本该同量级；实测是**双峰**：
    · 健康肩 1.00~1.40（5739 间，中位 1.22：面片按墙中线、图上按净面积，差 ~20% 是口径）
    · 空谷 1.40~2.00（11 间）
    · 坏簇 2.00 以上（531 间，3.0~4.0 有一个 392 间的大峰）⇒ 房间与走廊并在了一起。
  阈值取**谷**，不取分位：谷的位置是这份数据自己给的，分位只是「切掉多少人」。
    · 黄 = 健康肩的上沿：从 1.30 起按 0.05 宽扫，第一个「不足 0.1% 房」的区间下沿
    · 红 = 比值 p99（坏簇里最狠的那一截）
  ⚠ 相对标定只排序，不判对错；判词里必须带「面片 / 图上」两个原始数。

用法：
    python -X utf8 rebuild/tools/calibrate_room_area.py           # 只打印
    python -X utf8 rebuild/tools/calibrate_room_area.py --apply   # 写参数.json（LF 写盘）
"""
import argparse
import glob
import io
import json
import os
import sys

import numpy as np
from shapely.geometry import Polygon

CDUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACK = os.path.join(CDUT, "packs", "cdut-main")
PARAMS = os.path.join(CDUT, "rebuild", "构件库", "参数.json")
BIN = 0.05
EDGE0 = 1.30            # 健康肩起点（更小的比值是「面片比图上还小」，另一头，不在本判据）
SPARSE = 0.001          # 「空」= 占不到 0.1% 的房
Q_红 = 99.0


def ratios():
    """只取**一个分区一个房号**的房间。

    ★ 2026-10-20 第一版把「开敞区多房号共用一区」也算进来（包里记为 `numbers`）：
      c072/c073 每间公寓两个床号共用一区（图上面积按**单床**写），c036 三间共用一区。
      分母只有其中一个号的图上面积 ⇒ 全仓多出 384 间整整齐齐 3.07× 的「超标」——
      那是**分母错了**，不是房间错了（铁律 018/183：一个错法换张脸又来一遍）。
      多字区的正确分母是**区内全部房号的面积和**，包里没存（只留了第一个号的），
      所以本判据**不量**它们，并在输出里点名有多少间被排除。
    """
    v, where, n_multi = [], [], 0
    for f in glob.glob(os.path.join(PACK, "*", "baseline", "floors", "floor*.json")):
        try:
            with io.open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:                                                # noqa: BLE001
            continue
        bid = f[len(PACK) + 1:].split(os.sep)[0]
        for r in d.get("rooms") or []:
            st, poly = r.get("stated_m2"), r.get("poly")
            if not st or not poly or len(poly) < 3:
                continue
            if len(r.get("numbers") or ()) > 1:
                n_multi += 1
                continue
            a = Polygon(poly).area
            if a > 0:
                v.append(a / st)
                where.append((bid, d.get("floor"), r.get("number")))
    return np.asarray(v, float), where, n_multi


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    v, where, n_multi = ratios()
    n = len(v)
    print("排除「多房号共用一区」%d 间（分母不可靠，本判据不量）" % n_multi)
    if not n:
        print("★ 一间都量不到 ⇒ 不写阈值（没量到不是 0）")
        return 2
    # 黄：健康肩的上沿
    e = EDGE0
    while e < 10.0:
        c = int(((v >= e) & (v < e + BIN)).sum())
        if c < SPARSE * n:
            break
        e += BIN
    y = round(float(e), 2)
    # 红：单字区里的 p99。
    #   排除多字区之后**没有「坏簇」了**（第一版看到的 3.07× 大峰全是分母错），
    #   尾巴是长尾而不是双峰 ⇒ 按分位取最狠的 1%。
    r = round(float(min(max(np.percentile(v, Q_红), e + BIN), 50.0)), 2)
    print("样本 %d 间（%d 栋）· 中位 %.2f · p95 %.2f · p99 %.2f · 最大 %.1f"
          % (n, len({w[0] for w in where}), float(np.median(v)),
             float(np.percentile(v, 95)), r, float(v.max())))
    print("  健康肩上沿（黄）= %.2f  超它 %d 间（%.1f%%）" % (y, int((v >= y).sum()), 100.0 * (v >= y).mean()))
    print("  p99（红，单字区）= %.2f  超它 %d 间" % (r, int((v >= r).sum())))
    edges = [EDGE0 + BIN * k for k in range(int((10.0 - EDGE0) / BIN) + 1)]
    h, _ = np.histogram(v, bins=edges)
    print("  [%.2f,10] 每 %.2f 一格的房数（看谷在哪）：" % (EDGE0, BIN))
    line = []
    for lo, c in zip(edges, h):
        if c:
            line.append("%.2f:%d" % (lo, c))
    print("    " + "  ".join(line))
    out = {"房间面积_黄": y, "房间面积_红": r}
    if not a.apply:
        print("\n（预演，没写盘；加 --apply 写 参数.json）")
        return 0
    with io.open(PARAMS, encoding="utf-8") as fh:
        p = json.load(fh)
    p.setdefault("缺陷扫描", {}).update(out)
    with io.open(PARAMS, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("\n已写 %s（LF 写盘）：%s" % (PARAMS, json.dumps(out, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
