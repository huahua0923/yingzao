# -*- coding: utf-8 -*-
r"""把某栋 DXF 里一段 Y 窗口的墙折线画成 PNG（看图用，不做判断）。

为什么要有它：判「那一坨墙是**一层平面**还是**总平面图/详图**」只能看图。
量出来的数（墙条数、外接框）两种都可能长得像 —— 这是"代理量代替真对象"
的老坑，所以最后一步必须落到眼睛上。

用法（只认位置参数）：
  python _scratch/_view_region.py c001 0 250000
  出图 _scratch/_view_<name>_<y0>_<y1>.png
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "_scratch"), str(ROOT / "backend")]
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import ezdxf                                              # noqa: E402
import matplotlib                                         # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                            # noqa: E402
from matplotlib.collections import LineCollection          # noqa: E402
from run_building import load_profile                      # noqa: E402


def main() -> None:
    nm = sys.argv[1]
    y0, y1 = float(sys.argv[2]), float(sys.argv[3])
    p = load_profile(nm)
    doc = ezdxf.readfile(p.dxf, encoding="utf-8")
    msp = doc.modelspace()
    x0, x1 = (p.x_range or [None, None])

    segs = []
    for e in msp:
        if e.dxftype() != "LWPOLYLINE":
            continue
        pts = [(float(q[0]), float(q[1])) for q in e.get_points("xy")]
        if not pts:
            continue
        mx = sum(q[0] for q in pts) / len(pts)
        my = sum(q[1] for q in pts) / len(pts)
        if not (y0 <= my <= y1):
            continue
        if x0 is not None and not (x0 <= mx <= x1):
            continue
        segs += [[(pts[i][0] / 1000.0, pts[i][1] / 1000.0),
                  (pts[i + 1][0] / 1000.0, pts[i + 1][1] / 1000.0)]
                 for i in range(len(pts) - 1)]
    print("窗口 y[%.0f, %.0f] 内折线 %d 段" % (y0, y1, len(segs)))
    if not segs:
        return

    # 房号文字（层号字段 + 原文），单独标出来 —— "这层有图上房号"是它**是平面图**的
    # 最硬的证据（总平面图不会有 6-C-01 这种号）。
    labels = []
    for e in msp:
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        t = e.dxf.text if e.dxftype() == "TEXT" else e.text
        t = (t or "").strip()
        if not t:
            continue
        ix, iy = float(e.dxf.insert[0]), float(e.dxf.insert[1])
        if not (y0 <= iy <= y1):
            continue
        if x0 is not None and not (x0 <= ix <= x1):
            continue
        labels.append((ix / 1000.0, iy / 1000.0, t[:18]))

    fig, ax = plt.subplots(figsize=(20, 20))
    ax.add_collection(LineCollection(segs, colors="#333333", linewidths=0.4))
    for lx, ly, lt in labels:
        ax.plot(lx, ly, "r.", ms=2)
        ax.annotate(lt, (lx, ly), fontsize=4, color="#c02020")
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_title("%s  y[%.0f, %.0f]  segs=%d  labels=%d" % (nm, y0, y1, len(segs), len(labels)))
    op = ROOT / "_scratch" / ("_view_%s_%.0f_%.0f.png" % (nm, y0, y1))
    fig.savefig(op, dpi=110, bbox_inches="tight")
    print("已出 %s" % op)


if __name__ == "__main__":
    main()
