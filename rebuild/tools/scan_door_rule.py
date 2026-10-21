# -*- coding: utf-8 -*-
"""**门判据影响面扫描**：不改任何件，只量「新判据每栋会多留几条墙、少当几条门」。

1. 调用方：**没有生产文件 import 它**，只在命令行手动跑（2026-10-19 由我执行）。
   已有件都不做这件事：`scan_door_union.py` 量的是「补收后多认几樘门」，
   `overlay_check.compare_floor` 量的是距离率（要跑全套采样，贵且不含分类计数）。
2. 只读、不写任何文件。
3. 读：`rebuild/构件库/楼栋.json`（dict，键=bid，字段 `drawing`）、
   `rebuild/<bid>/01_cad/raw/<层>.dxf`（DXF，无日期字段）。
4. 用户指令：「为啥门搞成折线？」→ 查出门符号判据把真墙链当门丢了，
   修完 c034 验证通过，**先扫全库有多大影响面再决定重不重建**。

判据**复用生产件** `door_rule.make_predicate`（唯一一份，与 recognize / overlay_check /
redraw 共用）。两列并排：老口径 = 「≥16 点」，新口径 = 档案 `drawing` 三项。
只数墙层 LWPOLYLINE 的分类，不读几何距离 ⇒ 秒级，不判红，退出码 0。

  bid   老当门 78 → 新当门 78   新留墙 +0   新丢门 -0   逐层 1:+0 2:+0 …

字段含义：
  · `新留墙` = 老口径当门跳过、新口径是真墙的折线数（**这些墙原来没进模型**）；
  · `新丢门` = 老口径当墙、新口径是门符号的折线数（原来被当墙体建进去了）。

用法：
  python -I rebuild/tools/scan_door_rule.py            # 全部楼栋
  python -I rebuild/tools/scan_door_rule.py c034 c005  # 指定楼栋
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CDUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(CDUT, "gates"))

import building as B                                                # noqa: E402
import door_rule as DR                                              # noqa: E402
import overlay_check as O                                           # noqa: E402


def _counts(path, is_door):
    """墙层 LWPOLYLINE 按 `is_door` 分类 → dict（四项分类计数）。

    ★ 不能只报「新墙数 − 老墙数」：新判据同时做两件事（多留真墙、少留门符号），
      净值会把两条方向相反的正事抵消成一个看着像回归的负号（2026-10-19 首版翻过车）。
    """
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    wall = O._layer_pick(Counter(e.dxf.layer for e in msp), "wall")
    out = {"门_老": 0, "门_新": 0, "墙_老": 0, "墙_新": 0,
           "都算墙": 0, "新留墙": 0, "新丢门": 0, "都算门": 0}
    for e in msp:
        if e.dxf.layer != wall or e.dxftype() != "LWPOLYLINE":
            continue
        p5 = list(e.get_points("xyb"))
        xs = [q[0] for q in p5]
        ys = [q[1] for q in p5]
        o = len(xs) >= 16
        n = is_door(xs, ys, any(abs(q[2]) > 1e-9 for q in p5))
        out["门_老"] += o
        out["门_新"] += n
        out["墙_老"] += not o
        out["墙_新"] += not n
        out["新留墙"] += (o and not n)
        out["新丢门"] += ((not o) and n)
        out["都算墙"] += ((not o) and (not n))
        out["都算门"] += (o and n)
    return out


def scan(bid):
    pr = B.profile(bid)
    draw = pr.get("drawing") or {}
    if draw.get("doors") != "symbols":
        return None                                  # 不跳门符号的图，新旧同口径
    new_is = DR.make_predicate(draw)
    root = B.root_for(bid)
    keep = drop = od = nd = 0
    per = []
    for f in ([pr["basement"]] if pr.get("basement") else []) + list(pr["floor_names"]):
        p = os.path.join(root, "01_cad", "raw", f + ".dxf")
        if not os.path.exists(p):
            per.append("%s:没料" % f)
            continue
        c = _counts(p, new_is)
        od += c["门_老"]
        nd += c["门_新"]
        keep += c["新留墙"]                          # 新留墙（老口径当门）= 原来没进模型的墙
        drop += c["新丢门"]                          # 新丢门（老口径当墙）= 原来被建成墙体的门符号
        per.append("%s:+%d/-%d" % (f, c["新留墙"], c["新丢门"]))
    return {"bid": bid, "老门": od, "新门": nd, "新留墙": keep, "新丢门": drop,
            "floor": per}


def main(argv):
    bids = argv[1:] or sorted(B.all_profiles())
    rows, skipped = [], 0
    for bid in bids:
        try:
            r = scan(bid)
        except Exception as exc:                     # 量不到必须出声（铁律 199）
            print("  ★ %-6s 没量到：%s: %s" % (bid, type(exc).__name__, exc))
            skipped += 1
            continue
        if r is None:
            skipped += 1
            continue
        rows.append(r)
        print("  %-6s 老当门 %3d → 新当门 %3d   新留墙 +%-3d  新丢门 -%-3d   %s"
              % (r["bid"], r["老门"], r["新门"], r["新留墙"], r["新丢门"],
                 " ".join(r["floor"])))
    print("\n===== 汇总 =====")
    hit = [r for r in rows if r["新留墙"] or r["新丢门"]]
    print("  扫了 %d 栋（跳过 %d 栋：非 symbols 或量不到）· 判据有差别的 %d 栋"
          % (len(rows), skipped, len(hit)))
    print("  合计 新留墙 +%d 条（原来没进模型的墙）· 新丢门 -%d 条（原来被建成墙体的门符号）"
          % (sum(r["新留墙"] for r in rows), sum(r["新丢门"] for r in rows)))
    if hit:
        print("  受影响（建议重建）：%s" % " ".join(r["bid"] for r in hit))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
