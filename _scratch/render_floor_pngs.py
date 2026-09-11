# -*- coding: utf-8 -*-
"""批量把每栋楼的 DXF 逐层渲染成 PNG（每层一张，本地米坐标），
供与立体模型（GLB/楼层轮廓）对比，排查错位与漏识别。

每层一张图（单面板，坐标与 3D 模型一致、均以该层几何中心为原点）：
  灰 = DXF 真墙；橙 = 门符号；红 = 识别轮廓（= 立体模型的楼板 footprint）。
  左上角标 coverage（真墙被识别墙覆盖比例，长度口径）。

保存到 data/buildings/<name>/plans/floor{F}.png（每栋一个 plans 目录）。

用法:
  python -u render_floor_pngs.py            # 全部楼（48 栋）
  python -u render_floor_pngs.py c006 c009  # 指定楼
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = r"D:\gym3d"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "recognizer"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_building import load_profile
import compare_floors as cf
from shapely.geometry import Polygon

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

BASE = r"D:\gym3d\data\buildings"


def render_building(name):
    p = load_profile(name)
    raw = cf.raw_walls_per_floor(p)
    floors_dir = p.out_dir
    plan_dir = os.path.join(os.path.dirname(p.out_dir), "plans")
    os.makedirs(plan_dir, exist_ok=True)

    floor_files = sorted(
        [f for f in os.listdir(floors_dir)
         if f.startswith("floor") and f.endswith(".json")],
        key=lambda s: int(s[5:-5]))

    for ff in floor_files:
        F = int(ff[5:-5])
        with open(os.path.join(floors_dir, ff), encoding="utf-8") as f:
            g = json.load(f)
        raw_walls = raw.get(F, {}).get("walls", [])
        raw_doors = raw.get(F, {}).get("doors", [])
        outline = g.get("outline")
        if not outline:
            continue
        rec_walls = g.get("walls", [])
        cov, _, oa, _ = cf._metric(raw_walls, rec_walls, outline)

        fig, ax = plt.subplots(figsize=(9, 7))
        cf._draw_walls(ax, raw_walls, "#666666", 1.0, 0.85)
        cf._draw_walls(ax, raw_doors, "#e0943c", 1.0, 0.5)
        cf._draw_walls(ax, [w["poly"] for w in rec_walls if w["type"] in ("outer", "inner")],
                       "#3a6ea5", 0.5, 0.9, fill="#9db8d9")
        ax.add_patch(plt.Polygon(outline, closed=True, fill=False,
                                 edgecolor="#d0342c", lw=2.2))
        ax.set_aspect("equal")
        ax.set_title(f"{name} · {p.title} · F{F}  (轮廓红={oa:.0f}㎡"
                     f" 覆盖={None if cov is None else round(cov, 2)})", fontsize=12)
        fig.tight_layout()
        out = os.path.join(plan_dir, f"floor{F}.png")
        fig.savefig(out, dpi=100)
        plt.close(fig)
    return len(floor_files)


def main():
    names = sys.argv[1:]
    if not names:
        names = sorted(d for d in os.listdir(BASE)
                       if os.path.isdir(os.path.join(BASE, d))
                       and os.path.exists(os.path.join(BASE, d, "profile.json")))
    ok, fail = [], []
    N = len(names)
    for i, name in enumerate(names, 1):
        sys.stdout.write(f"[{i}/{N}] {name:6s} ...")
        sys.stdout.flush()
        try:
            n = render_building(name)
            sys.stdout.write(f"\r[{i}/{N}] {name:6s} OK {n} 层\n")
            sys.stdout.flush()
            ok.append(name)
        except Exception as e:
            sys.stdout.write(f"\r[{i}/{N}] {name:6s} FAIL {type(e).__name__}: {e}\n")
            sys.stdout.flush()
            fail.append(name)
    print(f"\n汇总: 成功 {len(ok)} / 失败 {len(fail)}")
    if fail:
        print("失败:", ", ".join(fail))


if __name__ == "__main__":
    main()
