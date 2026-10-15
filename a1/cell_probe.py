# -*- coding: utf-8 -*-
"""逐格探针：把 `classify` 选中的每一张图幅单独报「墙段数 + 覆盖率 + 是否量到」。

为什么必须逐格：`cov_min` 是**一个数**，它掉了 0.01 或掉了 100，从总数上看不出是哪一格。
实测 C105-图书馆 在旧列规则下 `cov_min=0.00`、新规则下 99.87 —— 只有逐格看才知道
那个 0.00 是**哪一张**、新规则下它变成了什么（同一张？还是被 NaN 滤掉换了一张？）。

用法: python cell_probe.py <dxf> [--margin 8000]
"""
import argparse
import collections
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent))
import sheet_grid as SG      # noqa: E402
import generic_wall as GW    # noqa: E402
import ezdxf                 # noqa: E402

MIN_SEG = 50


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf")
    ap.add_argument("--margin", type=float, default=8000.0)
    ap.add_argument("--layer", default=None)
    a = ap.parse_args()
    p = Path(a.dxf)
    if not p.is_file():
        p = Path(r"D:\项目\gym3d\材料\dxf_output") / a.dxf
    doc = ezdxf.readfile(str(p)); msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, a.layer)
    sheets = SG.merge_pairs(SG.collect_frames(msp, layer))
    modal, std, others = SG.classify(sheets)
    ALLW, ALLC, LABELS = GW.load_walls_and_cols_msp(msp)
    mids = [((s.bounds[0] + s.bounds[2]) / 2, (s.bounds[1] + s.bounds[3]) / 2) for s in ALLW]

    print("DXF %s   图框层 %s   图幅总 %d   选中标准图幅 %d   非标准 %d"
          % (p.name, layer, len(sheets), len(std), len(others)))
    print("选中尺寸 %s   全库墙段 %d\n" % (modal, len(ALLW)))
    print("%-4s %-9s %-9s %-9s %-9s %8s %10s %s" % ("#", "x0", "y0", "x1", "y1", "墙段", "覆盖率", "判"))
    lcs = []
    for i, c in enumerate(std):
        x0, y0, x1, y1 = c["bbox"]
        n = sum(1 for x, y in mids if x0 <= x <= x1 and y0 <= y <= y1)
        r, m, it, lc, nq, nu = GW.score_cell(ALLW, ALLC, x0, x1, y0, y1, a.margin)
        lcs.append(lc)
        tag = []
        if n < MIN_SEG:
            tag.append("空图框")
        if lc != lc:
            tag.append("★未量到(NaN)")
        elif lc < 99.999:
            tag.append("★覆盖不满")
        print("%-4d %-9.0f %-9.0f %-9.0f %-9.0f %8d %10s %s"
              % (i, x0, y0, x1, y1, n, "NaN" if lc != lc else "%.2f%%" % lc, " ".join(tag)))
    valid = [x for x in lcs if x == x]
    print("\n  有效格 %d / 选中 %d   覆盖min %s   覆盖满100 %s"
          % (len(valid), len(std), "—" if not valid else "%.2f%%" % min(valid),
             all(x >= 99.999 for x in valid) if valid else False))
    return 0


sys.exit(main())
