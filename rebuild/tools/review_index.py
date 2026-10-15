# -*- coding: utf-8 -*-
"""把 12 层的重画成果编成一份**给人审的清单** + 在图上把可疑处**框出来**。

用户的原话是「画好后给我看，**我框出问题**」—— 所以这一份的输出必须让人能
① 一眼看到每层判出了什么、② 直接看到机器自己就**已经怀疑**的地方（并标了坐标），
③ 知道去哪儿打开那份 dxf 在 CAD 里改。

输出：
  rebuild/04_review/审图说明.md           逐层清单 + 可疑处 + 怎么在 CAD 里改
  rebuild/04_review/<层名>_审图.png        原重画图 + 可疑处框（叠加，不改原图）
用法：python rebuild/tools/review_index.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                            # noqa: E402
from matplotlib.patches import Rectangle                                   # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import redraw as RD                                                        # noqa: E402
import lint_detached as LD                                                 # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

RED = os.path.join(ROOT, "03_redraw")
OUT = os.path.join(ROOT, "04_review")


def read_json(floor):
    p = os.path.join(ROOT, "02_recognize", floor + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        m = json.load(f)
    src = os.path.join(ROOT, "01_cad", "raw", floor + ".dxf")
    m["n_col"] = len(RD.blocks_wcs(src, layer=RD.COL_LAYER))
    m["n_door"] = len(RD.blocks_wcs(src, prefix=RD.DOOR_PREFIX))
    return m


def marks(floor, min_area=1.0, far=5000.0):
    """本层被判为「孤立的一小块」的墙（机器自己已经怀疑的地方）。"""
    bs = LD.blobs(floor, min_area)
    return [(b, LD.nearest_other(b, bs)) for b in bs
            if LD.nearest_other(b, bs) > far]


def annotate(floor, ms):
    """在原重画图上叠红虚框 —— ★ 必须与墙画在**同一个坐标系（mm）**里。

    第一版是 `imread` 那张 `_plan.png` 再叠框：imread 之后坐标轴是**像素**，
    框却按 mm 摆（x0≈116000）⇒ 被画到画布外，**图上没有框、程序也不报错**
    （静默假绿：文件写着「可疑处 1 处」而红框根本不存在）。
    所以这里改用 `redraw.draw()` 重画一遍（同一份实现），框直接落在 mm 数据坐标上。
    """
    fig, ax, _v = RD.draw(floor)
    for b, d in ms:
        ax.add_patch(Rectangle((b["x0"], b["y0"]), b["x1"] - b["x0"], b["y1"] - b["y0"],
                               fill=False, edgecolor="#d92b2b", linewidth=3.0,
                               linestyle=(0, (8, 5)), zorder=5))
        ax.annotate("★ 疑似另一张小图？\n%.1f m²，离主体 %.1f m" % (b["A"], d / 1000.0),
                    xy=(b["x0"], b["y0"]), xytext=(b["x0"], b["y0"] - 5000),
                    fontsize=13, color="#d92b2b", weight="bold",
                    va="top", ha="left", zorder=6)
    ax.set_title("%s · 审图（红虚框 = 机器自己标出的可疑处，不是判错）" % floor, fontsize=16)
    dst = os.path.join(OUT, "%s_审图.png" % floor)
    fig.savefig(dst, bbox_inches="tight")
    plt.close(fig)
    return dst


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = ["# C006 重画 · 审图说明（第一轮）", "",
             "**怎么用**：看 `04_review/<层名>_审图.png`；要改就打开 `03_redraw/<层名>_full.dxf`",
             "（图层 `WALL`/`COL`/`DOOR`/`STAIR`），在 CAD 里改完存回同名文件。", "",
             "| 层 | 判出墙面积 m² | 墙块 | 柱实体 | 门图元 | 剔除踏步线 | 墙厚中位 mm | 可疑处 |",
             "|---|---|---|---|---|---|---|---|"]
    n_mark = 0
    for f in LD.FLOORS:
        m = read_json(f)
        if m is None:
            lines.append("| %s | ★ 没量到 | | | | | | | |" % f)
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            ms = marks(f)
        n_mark += len(ms)
        note = "；".join("%.1f m²@(%.0f,%.0f) 离 %.1f m" % (b["A"], b["cx"], b["cy"], d / 1000)
                        for b, d in ms) or "—"
        lines.append("| %s | %.1f | %d | %d | %d | %d | %.0f | %s |"
                     % (f, m["area_wall_m2"], m["wall_polys"], m["n_col"],
                        m["n_door"], m["treads_dropped"], m["thick_mm"], note))
        if ms:
            annotate(f, ms)
    lines += ["", "## 这一版识别里，机器自己标出的可疑处", "",
              "只有 %d 处。它们**不是**判据报错，是机器主动说「这块跟主体不相连，像是同一张图纸上"
              "另外画的一张小图」。" % n_mark, "",
              "★ 若确认是附带小图（不是本层平面），在建模那一步按外框剔除即可 —— "
              "**在你确认之前，我不动它**（不臆造）。", ""]
    with open(os.path.join(OUT, "审图说明.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("写 %s" % os.path.join(OUT, "审图说明.md"))
    print("可疑处合计 %d 处" % n_mark)
    return 0


if __name__ == "__main__":
    sys.exit(main())
