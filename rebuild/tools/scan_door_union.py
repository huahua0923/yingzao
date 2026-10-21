# -*- coding: utf-8 -*-
"""**门补收扫描**：不改任何包，只量「按补收口径每栋会多认几樘门、多在哪」。

1. 调用方：**没有生产文件 import 它**，只在命令行手动跑（2026-10-18 由我执行）。
   已有件都不做这件事：`audit_components.py` 量的是「各画法各认到几樘」（不含重叠判重）、
   `compare3d.py` 比的是两份三维出件，`scan_*` 无同名件。故新建本件。
2. 只读、不写任何文件。
3. 读：`rebuild/构件库/楼栋.json`（dict，键=bid，字段 drawing/keep_layers/src_dxf）、
   `rebuild/<bid>/01_cad/raw/<层>.dxf`（DXF，无日期字段）。
4. 用户指令：「c004 的门不对」→ 口径「改通用逻辑，全库先扫一遍看会多收多少」

判据**复用生产件** `redraw.doors_for_floor(..., union=True/False)` —— 不另写一份
（旧口径 = 档案画法一种；新口径 = 档案画法 + 另种画法与它不重叠的门）。两列并排打印：

  bid   旧口径 84 → 新口径 87 (+3)   逐层 1:+3
  ★ 末行汇总；退出码 0（本件只量，不判红）。

用法：
  python -I rebuild/tools/scan_door_union.py               # 全部楼栋
  python -I rebuild/tools/scan_door_union.py c004 c105     # 指定楼栋
"""
from __future__ import annotations

import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import ezdxf                                                       # noqa: E402

BASE = os.path.dirname(os.path.dirname(HERE))                      # D:\项目\cdut3d
REBUILD = os.path.join(BASE, "rebuild")
PROF = os.path.join(REBUILD, "构件库", "楼栋.json")


def scan(bid):
    """一栋：返回 (旧数, 新数, 逐层[(层, 旧, 新, [(x,y)…补收门中心])])。"""
    raw = os.path.join(REBUILD, bid, "01_cad", "raw")
    if not os.path.isdir(raw):
        return None
    os.environ["CDUT_BUILDING"] = bid
    os.environ["CDUT_REBUILD_ROOT"] = os.path.join(REBUILD, bid)
    import building as B
    import redraw as RD
    B.BID = bid
    RD = importlib.reload(RD)          # 门参数是模块级常量、import 时读的 ⇒ 必须 reload

    floors = sorted(f[:-4] for f in os.listdir(raw) if f.lower().endswith(".dxf"))
    rows, n_old, n_new = [], 0, 0
    for f in floors:
        p = os.path.join(raw, f + ".dxf")
        doc = ezdxf.readfile(p)
        old = RD.doors_for_floor(doc, p, f, union=False, verbose=False)[0]
        new = RD.doors_for_floor(doc, p, f, union=True, verbose=False)[0]
        n_old += len(old)
        n_new += len(new)
        extra = new[len(old):] if len(new) > len(old) else []
        ctr = []
        for pts, _closed in extra:
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            ctr.append((round((min(xs) + max(xs)) / 2), round((min(ys) + max(ys)) / 2)))
        rows.append((f, len(old), len(new), ctr))
    return n_old, n_new, rows


def main(argv):
    bids = [a for a in argv if not a.startswith("--")]
    prof = json.load(open(PROF, encoding="utf-8"))
    if not bids:
        bids = [b for b in sorted(prof)
                if isinstance(prof.get(b), dict) and prof[b].get("src_dxf")]
    t_old = t_new = 0
    lines = []
    for b in bids:
        try:
            r = scan(b)
        except Exception as e:                                     # noqa: BLE001
            print("%-6s ★崩 %s: %s" % (b, type(e).__name__, e))
            continue
        if not r:
            print("%-6s 没有 01_cad/raw" % b)
            continue
        o, n, rows = r
        t_old += o
        t_new += n
        diff = n - o
        per = " ".join("%s:+%d" % (f, nn - oo) for f, oo, nn, c in rows if nn > oo)
        print("%-6s 旧 %4d → 新 %4d (%+d)   逐层 %s"
              % (b, o, n, diff, per or "-"))
        for f, oo, nn, c in rows:
            if c:
                lines.append("       %s %s 补收 %d 樘：%s"
                             % (b, f, len(c), " ".join("(%d,%d)" % xy for xy in c)))
    print("\n".join(lines))
    print("\n合计：旧口径 %d 樘 → 补收后 %d 樘（+%d）" % (t_old, t_new, t_new - t_old))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
