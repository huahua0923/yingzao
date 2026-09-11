# -*- coding: utf-8 -*-
"""逐层平面图比对：识别结果 vs DXF 原始墙，出 PNG + 数值覆盖率。

用户诉求：「画完后对每层截图生成平面图，再和 dxf 推导出的每层图比对，找到哪里错了」。

构件语义（关键）：
  - 真墙 = 2 点墙皮线（双线墙的一面）+ >=3 点闭合多边形（填充墙）。
  - 门符号 = >=3 点「不闭合」折线（leaf + swing arc，跨度多 <3m），识别器正确丢弃。
  - 覆盖率的「raw 墙」只算真墙，不含门符号。

三连图 / 层：
  左 = DXF 原始（灰=真墙，橙=门符号）
  中 = 识别结果（蓝=合并墙填充，红=楼板轮廓）
  右 = 叠加比对（灰真墙 + 红轮廓）
数值：coverage = 真墙中线被识别墙覆盖比例（长度口径，不受厚度归一化影响）。

用法:
  python compare_floors.py <name>      # 生成 data/buildings/<name>/plans/floor{F}.png
  python compare_floors.py <name> all  # 只打印数值，不画图
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "recognizer"))

import ezdxf
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from run_building import load_profile
from recognizer.classify import classify
from recognizer.profile import to_local, floor_of


def _is_closed(pts):
    first, last = pts[0], pts[-1]
    return abs(first[0] - last[0]) < 1e-6 and abs(first[1] - last[1]) < 1e-6


def raw_walls_per_floor(p):
    """从 DXF 直接拿每层原始构件（本地米坐标）：真墙 vs 门符号。"""
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()
    if getattr(p, "classifier", "lwpolyline") == "line":
        from recognizer.classify_line import classify_line
        walls, _, _, _ = classify_line(msp, p)
    else:
        walls, _, _, _ = classify(msp, p)
    by_floor = {}
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        F = floor_of(p, cx, cy)
        # 过渡层只比「建筑墙」X 区间（与 floor.extract_floor 同口径），
        # 否则裙楼屋面女儿墙（故意丢弃）会把覆盖率分母撑大、假性偏低。
        tr = (p.transition or {}).get(F)
        if tr and tr.get("wall_x") and not (tr["wall_x"][0] <= cx <= tr["wall_x"][1]):
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        d = by_floor.setdefault(F, {"walls": [], "doors": [], "slabs": []})
        # 与 recognizer/geometry.derive_walls_and_outline 同口径：
        #   - 2 点 = 墙皮线（真墙）
        #   - 3+ 点闭合且 area/length > 1.0 = 楼板/剖面填充（slab，比轮廓，不算墙）
        #   - 3+ 点闭合且 area/length <= 1.0 = 填充墙（真墙）
        #   - 3+ 点不闭合且跨度 < 3m = 门符号（leaf+arc）
        #   - 3+ 点不闭合且跨度 >= 3m = 带门洞缺口的墙折线（真墙，c041 常见）
        if len(pts) >= 3 and not _is_closed(local):
            xs = [q[0] for q in local]
            ys = [q[1] for q in local]
            span = max(max(xs) - min(xs), max(ys) - min(ys))
            if span < 3.0:
                d["doors"].append(local)
            else:
                d["walls"].append(local)
        elif len(pts) >= 3:
            poly = Polygon(local)
            if not poly.is_valid:
                # 自交/退化环（c104 裙楼 3959㎡ 楼板、c022 等）→ buffer(0) 清洗，
                # 与 geometry.derive_walls_and_outline 同口径；否则自交 slab 被误判成
                # 「真墙」计入分母，覆盖率假性偏低（c104 F0 0.912→0.99 的根因）。
                poly = poly.buffer(0)
            if poly.is_valid and poly.area / poly.length > 1.0:
                d["slabs"].append(local)   # 填充楼板 → 轮廓比对，不计入墙覆盖率
            else:
                d["walls"].append(local)
        else:
            d["walls"].append(local)
    return by_floor


def _draw_walls(ax, polylines, color, lw, alpha, fill=None):
    for pts in polylines:
        if len(pts) == 2:
            (x0, y0), (x1, y1) = pts
            ax.plot([x0, x1], [y0, y1], color=color, lw=lw, alpha=alpha,
                    solid_capstyle="round")
        elif len(pts) >= 3:
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            ax.add_patch(__import__("matplotlib").patches.Polygon(
                list(zip(xs, ys)), closed=True,
                fill=fill is not None, facecolor=fill or "none",
                edgecolor=color, lw=lw, alpha=alpha))


def _metric(raw_walls, rec_walls, outline):
    """长度口径覆盖率：真墙「中线」被识别墙（带洞）覆盖的比例。"""
    raw_lines = []
    for pts in raw_walls:
        if len(pts) == 2:
            raw_lines.append(LineString(pts))
        elif len(pts) >= 3:
            # 3+ 点闭合 = 填充墙多边形 → 闭环量周长；
            # 3+ 点不闭合 = 带门洞缺口的墙折线（c041/c025 常见）→ 按折线本身量，
            #   不能 [pts + pts[0]] 闭合成幽灵环，否则把门洞缺口桥接成假墙、覆盖率高估一半。
            if _is_closed(pts):
                raw_lines.append(LineString(list(pts) + [pts[0]]))
            else:
                raw_lines.append(LineString(pts))

    rec_geoms = []
    for w in rec_walls:
        if w["type"] not in ("outer", "inner"):
            continue
        holes = [h for h in (w.get("holes") or []) if len(h) >= 4]
        try:
            g = Polygon(w["poly"], holes)
            if not g.is_valid:
                g = g.buffer(0)   # 清洗自交，别把 1mm 级自交的墙整片丢弃
            if g.is_empty or g.area <= 0:
                continue
            rec_geoms.append(g)
        except Exception:
            pass
    rec_u = unary_union(rec_geoms) if rec_geoms else Polygon()

    total_len = sum(ln.length for ln in raw_lines)
    if total_len <= 0:
        return None, None, None, len(raw_walls)
    covered_len = sum(ln.intersection(rec_u).length for ln in raw_lines)
    coverage = covered_len / total_len

    # 反向：识别墙中线有多少落在真墙 0.2m 缓冲带内（多画检测）
    raw_buf = unary_union([ln.buffer(0.20) for ln in raw_lines])
    rec_hit = 0.0
    rec_len = 0.0
    for w in rec_walls:
        if w["type"] not in ("outer", "inner"):
            continue
        seg = LineString(list(w["poly"]) + [w["poly"][0]])
        rec_len += seg.length
        rec_hit += seg.intersection(raw_buf).length
    precision = rec_hit / rec_len if rec_len > 0 else 0.0

    outline_area = Polygon(outline).area
    return coverage, precision, outline_area, len(raw_walls)


def main():
    name = sys.argv[1]
    p = load_profile(name)
    raw = raw_walls_per_floor(p)

    floors_dir = p.out_dir
    plan_dir = os.path.join(os.path.dirname(p.out_dir), "plans")
    os.makedirs(plan_dir, exist_ok=True)

    floor_files = sorted(
        [f for f in os.listdir(floors_dir)
         if f.startswith("floor") and f.endswith(".json")],
        key=lambda s: int(s[5:-5]))

    print(f"=== {name} 逐层比对（真墙 vs 识别） ===")
    for ff in floor_files:
        F = int(ff[5:-5])
        with open(os.path.join(floors_dir, ff), encoding="utf-8") as f:
            g = json.load(f)
        raw_walls = raw.get(F, {}).get("walls", [])
        raw_doors = raw.get(F, {}).get("doors", [])
        rec_walls = g.get("walls", [])
        outline = g["outline"]
        cov, prec, oa, nraw = _metric(raw_walls, rec_walls, outline)
        print(f"  F{F}: 真墙={nraw:3d} 门符号={len(raw_doors):3d}  rec墙={len(rec_walls):3d}  "
              f"outline={oa:7.1f}㎡  覆盖率={None if cov is None else round(cov,3)}  "
              f"precision={None if prec is None else round(prec,3)}")

        if "all" in sys.argv:
            continue
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, axes = plt.subplots(1, 3, figsize=(19, 6.2))
        _draw_walls(axes[0], raw_walls, "#666666", 1.1, 0.8)
        _draw_walls(axes[0], raw_doors, "#e0943c", 1.1, 0.5)
        axes[0].set_title(f"F{F} DXF 原始 (真墙{nraw} 门{len(raw_doors)})")
        _draw_walls(axes[1], [w["poly"] for w in rec_walls
                              if w["type"] in ("outer", "inner")],
                    "#3a6ea5", 0.6, 0.9, fill="#9db8d9")
        axes[1].add_patch(plt.Polygon(outline, closed=True, fill=False,
                                      edgecolor="#d0342c", lw=2.5))
        axes[1].set_title(f"F{F} 识别结果 (墙{len(rec_walls)} 轮廓红)")
        _draw_walls(axes[2], raw_walls, "#888888", 1.3, 0.55)
        axes[2].add_patch(plt.Polygon(outline, closed=True, fill=False,
                                      edgecolor="#d0342c", lw=2.5))
        axes[2].set_title(f"F{F} 叠加 (coverage={None if cov is None else round(cov,3)})")
        for ax in axes:
            ax.set_aspect("equal")
        fig.suptitle(f"{name} · {p.title} · floor {F}  识别 vs DXF", fontsize=14)
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        out = os.path.join(plan_dir, f"floor{F}.png")
        fig.savefig(out, dpi=110)
        plt.close(fig)
        print(f"      → {out}")


if __name__ == "__main__":
    main()
