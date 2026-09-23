# -*- coding: utf-8 -*-
"""按楼层渲染「源 DXF + 识别结果」平面图 PNG（每层一张），并生成一栋一页 HTML gallery。

图例：灰细线=源 DXF 原始线稿（≈CAD 视图，门开启弧/梯踏步都在里面）
      灰实心=识别墙(out外/inner内/parapet)   红=识别门(外门深红/内门橙)
      绿块+浅条=识别楼梯井及跑向              蓝=识别柱
      紫虚线=交付房间边界(floors 的 rooms[].poly)，房号 ≤ROOM_LABEL_MAX 间时标在质心
标题带 门/楼梯井/柱/房间/面积 计数 —— 直接判断「门和楼梯识别到没有」，不用开 CAD。
★ 房间边界来自交付楼层文件，改了 rooms.json **必须补跑 backfill_floor_rooms.py**
  再重跑本脚本，否则这里画的还是旧快照（详见 [[floor-json-rooms-are-snapshot]]）。
图片源=该楼 floor JSON(识别主结果) + 源 DXF(wall_pts_for_floor 取该层原始墙线)。

输出: data/buildings/<name>/dxf_plan_recog/floor{F}.png + 该目录 index.html
      （**不写** dxf_plan/，那是 _dxf_cad_render.py 的忠实源图纸；**不写** 总目录。）
用法: python -u _dxf_png_batch.py [<name> ...]   (不带参数=全部楼)
"""
import os, sys, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path[:0] = [r"D:\gym3d\backend\web", r"D:\gym3d\backend", r"D:\gym3d"]
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import _render_common as RC
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian"]
plt.rcParams["axes.unicode_minus"] = False
from matplotlib.path import Path
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
from shapely.geometry import Polygon

BASE = r"D:\gym3d\data\buildings"

C_RAW = "#8a8a8a"
C_OUTER, C_INNER, C_PARAPET = "#202020", "#4a4a4a", "#7a7a7a"
C_DOOR_OUTER, C_DOOR_INNER = "#d81e06", "#f08c00"
C_STAIR, C_STAIR_EDGE = "#2e8b57", "#155c2e"
C_COL = "#3a6ea5"
C_OUTLINE = "#b00"
C_ROOM = "#7b1fa2"          # 房间边界（紫虚线）—— 与墙/门/梯/柱/轮廓的配色都不撞
ROOM_LABEL_MAX = 30         # 房间数 ≤ 此值才标房号；密楼层（如 c060 每层 44 间）只画边界免得糊成一片


def _ring_path(ring):
    xs = [float(p[0]) for p in ring]; ys = [float(p[1]) for p in ring]
    if (xs[0], ys[0]) != (xs[-1], ys[-1]):
        xs = xs + [xs[0]]; ys = ys + [ys[0]]
    return xs, ys


def _patch_poly(ax, poly, holes, fc, ec=None, lw=0.4, alpha=1.0, zorder=2):
    xs, ys = _ring_path(poly)
    verts = list(zip(xs, ys))
    codes = [Path.MOVETO] + [Path.LINETO] * (len(xs) - 2) + [Path.CLOSEPOLY]
    for h in holes or []:
        hx, hy = _ring_path(h)
        verts += list(zip(hx, hy))
        codes += [Path.MOVETO] + [Path.LINETO] * (len(hx) - 2) + [Path.CLOSEPOLY]
    ax.add_patch(mpatches.PathPatch(Path(verts, codes), facecolor=fc,
                                    edgecolor=ec if ec else fc, lw=lw,
                                    alpha=alpha, zorder=zorder))


def _draw_raw(ax, raw):
    """源 DXF 该层原始墙线（灰细线）。raw = [本地点列,...]"""
    segs = []
    for pl in raw:
        pts = [(float(a), float(b)) for a, b in pl]
        for i in range(len(pts) - 1):
            if pts[i] != pts[i + 1]:
                segs.append([pts[i], pts[i + 1]])
    if segs:
        ax.add_collection(LineCollection(segs, colors=C_RAW, lw=0.5,
                                         alpha=0.45, zorder=1))


def render_floor_png(name, F, fl, out_path, raw=None):
    ol = fl.get("outline")
    x0 = min(p[0] for p in ol); x1 = max(p[0] for p in ol)
    y0 = min(p[1] for p in ol); y1 = max(p[1] for p in ol)
    bx = (x1 - x0) or 1; by = (y1 - y0) or 1
    fig, ax = plt.subplots(figsize=(10.5, 10.5 * by / bx), dpi=110)
    ax.set_facecolor("white")
    if raw is not None:
        _draw_raw(ax, raw)                        # 1: 源线稿垫底
    if ol:
        xs, ys = _ring_path(ol)
        ax.plot(xs, ys, color=C_OUTLINE, lw=0.9, alpha=0.5, zorder=2)  # 轮廓
    for w in fl["walls"]:                          # 2: 识别墙实心
        t = w.get("type", "inner")
        fc = C_OUTER if t == "outer" else (C_PARAPET if t == "parapet" else C_INNER)
        _patch_poly(ax, w["poly"], w.get("holes") or [], fc, zorder=3)
    rooms = fl.get("rooms") or []
    for r in rooms:                                # 2.5: 房间边界（紫虚线）
        poly = r.get("poly") or []
        if len(poly) < 3:
            continue
        xs, ys = _ring_path(poly)
        ax.plot(xs, ys, color=C_ROOM, lw=0.7, alpha=0.9, ls="--", zorder=4)
    if 0 < len(rooms) <= ROOM_LABEL_MAX:           # 房号（质心用 representative_point，
        for r in rooms:                            # 凹多边形不会落到外面）
            poly = r.get("poly") or []
            num = (r.get("number") or "").strip()
            if not num or len(poly) < 3:
                continue
            try:
                c = Polygon(poly).buffer(0).representative_point()
                ax.text(c.x, c.y, num, fontsize=4.5, color=C_ROOM,
                        ha="center", va="center", zorder=7)
            except Exception:                                      # noqa: BLE001
                pass
    ns = 0
    for s in fl.get("stairwells", []):             # 3: 楼梯井
        ns += 1
        xa, xb, yb, yt = s["x0"], s["x1"], s["yBot"], s["yTop"]
        ax.add_patch(mpatches.Rectangle((xa, yb), xb - xa, yt - yb,
                     facecolor="#cfe8d0", edgecolor=C_STAIR_EDGE, lw=1.1,
                     alpha=0.85, zorder=4))
        for f in s.get("flights", []):
            fw = (f["x1"] - f["x0"]) * 0.5
            for sgn in (-0.5, 0.5):
                cx = (f["x0"] + f["x1"]) / 2 + sgn * fw
                ax.plot([cx, cx], [yb + 0.05, yt - 0.05], color=C_STAIR,
                        lw=2.0, alpha=0.75, zorder=5)
    for s in fl.get("stairs", []):
        if isinstance(s, dict) and s.get("poly"):
            _patch_poly(ax, s["poly"], [], C_STAIR, alpha=0.8, zorder=4)
            ns += 1
    segs_o, segs_i = [], []
    nd = 0
    for d in fl.get("doors", []):                  # 4: 门红线
        nd += 1
        hw = d["w"] / 2
        if d.get("horiz"):
            seg = [(d["x"] - hw, d["y"]), (d["x"] + hw, d["y"])]
        else:
            seg = [(d["x"], d["y"] - hw), (d["x"], d["y"] + hw)]
        (segs_o if d.get("outer") else segs_i).append(seg)
    if segs_o:
        ax.add_collection(LineCollection(segs_o, colors=C_DOOR_OUTER, lw=2.4, zorder=6))
    if segs_i:
        ax.add_collection(LineCollection(segs_i, colors=C_DOOR_INNER, lw=1.8, zorder=6))
    nc = 0
    for c in fl.get("columns", []):                # 5: 柱
        nc += 1
        ax.add_patch(mpatches.Rectangle((c["x"] - c["w"] / 2, c["y"] - c["d"] / 2),
                     c["w"], c["d"], facecolor=C_COL, edgecolor="#1c3c57",
                     lw=0.3, zorder=5))
    ax.set_xlim(x0 - 0.6, x1 + 0.6); ax.set_ylim(y0 - 0.6, y1 + 0.6)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    # 面积一律印**轮廓真实面积**：旧写法 `area~{(x1-x0)*(y1-y0)}` 是包围盒，
    # c006 首层印 10805 而真实 5698.7（虚高 90%）。见铁律 17「量什么就写什么」。
    area_m2 = RC.outline_area_m2(fl)
    ax.set_title(f"{name}  {F+1}层  |  door={nd}  stairwell={ns}  col={nc}  "
                 f"rooms={len(fl.get('rooms', []))}  "
                 f"轮廓面积={area_m2 if area_m2 is not None else '?'}m2",
                 fontsize=9, color="#222", pad=6)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.15, facecolor="white")
    plt.close(fig)


def _gallery_html(name, floors):
    """每层一图。★ 楼层号显示一律 F+1（铁律 5：内部 0 基、显示 1 基）——
    旧写法 `F{F}` 让本页成为全仓唯一把首层写成「F0」的地方，与 A 页/对照页两套口径。"""
    fd = os.path.join(BASE, name, "floors")
    rows = []
    for F in floors:
        fj = os.path.join(fd, f"floor{F}.json")
        extra = ""
        try:
            fl = json.load(open(fj, encoding="utf-8"))
            extra = RC.caption_counts_html(RC.floor_counts(fl), F, RC.mtime_str(fj))
        except Exception:  # noqa: BLE001
            extra = ""
        rows.append(
            f'<figure data-floor="{F}"><img loading="lazy" src="floor{F}.png" '
            f'alt="{name} {F + 1}层">'
            f'<figcaption>{name} · {F + 1}层{extra}</figcaption></figure>')
    rows = "".join(rows)
    return ("<!DOCTYPE html><html lang=zh><head><meta charset=utf-8>"
            f"<title>{name} 每层平面图</title><style>"
            "body{font-family:sans-serif;background:#eef0f3;margin:0;padding:16px}"
            "h1{font-size:17px;color:#222;margin:4px 0 6px}"
            "p.leg{font-size:12px;color:#555;margin:0 0 12px}"
            "a{color:#0366d6;text-decoration:none}"
            "figure{display:inline-block;vertical-align:top;background:#fff;"
            "border:1px solid #d4d8dd;border-radius:6px;padding:8px;margin:0 12px 14px 0}"
            "img{width:640px;height:auto;border:1px solid #e0e3e7}"
            "figcaption{font-size:12px;color:#333;margin-top:5px;text-align:center}"
            + RC.CSS_EXTRA +
            "</style></head><body>"
            f"<h1>{name} · 每层一图（每层一个文件）</h1>"
            f"<p class=leg>灰细线=源DXF原图 · 灰实心=识别墙 · 红=识别门 · 绿块=识别楼梯井 · "
            f"蓝=识别柱 · <span style=\"color:#7b1fa2\">紫虚线=交付房间边界</span>。"
            f"标题有 door/楼梯井/房间计数，可直接判断识别结果，无需开CAD。</p>"
            f"<p><a href=\"../_dxf_index.html\">← 总目录</a></p>" + rows
            # 页面在 <楼>/dxf_plan_recog/ 下 → floors 在上一级
            + RC.freshness_script("../floors/", floors) + "</body></html>")


def main():
    names = sorted(d for d in os.listdir(BASE)
                   if os.path.isdir(os.path.join(BASE, d, "floors")))
    if sys.argv[1:]:
        names = [n for n in names if n in sys.argv[1:]]
    tot = 0; failed = []
    import run_step, ezdxf
    from recognizer import classify
    from recognizer.floor import wall_pts_for_floor
    for i, name in enumerate(names, 1):
        fd = os.path.join(BASE, name, "floors")
        floors = sorted(int(os.path.basename(f)[5:-5])
                        for f in glob.glob(os.path.join(fd, "floor*.json")))
        # 源 DXF（一次读，逐层切原始墙线）
        p = raw = None
        try:
            p = run_step.load_profile(name)
            walls_r, _, _, _ = classify.classify(ezdxf.readfile(p.dxf).modelspace(), p)
        except Exception as e:  # noqa: BLE001
            failed.append((name, "*", f"DXF源读取失败 {str(e)[:80]}"))
        # 输出到 dxf_plan_recog（识别叠加图），**不是** dxf_plan —— dxf_plan 归
        # _dxf_cad_render.py 所有，装的是白底黑线的忠实**源图纸**。本脚本画的是
        # 「灰细线源线稿 + 识别结果叠加」，写进 dxf_plan 会顶掉源图纸
        # （2026-09-10 事故：跑 c006 后该栋源图纸变成叠加图，用户「源图纸不对了」）。
        od = os.path.join(BASE, name, "dxf_plan_recog")
        os.makedirs(od, exist_ok=True)
        ok = 0
        for F in floors:
            fp = os.path.join(fd, f"floor{F}.json")
            try:
                fl = json.load(open(fp, encoding="utf-8"))
                if p is not None:
                    raw = wall_pts_for_floor(F, walls_r, p)
                render_floor_png(name, F, fl, os.path.join(od, f"floor{F}.png"), raw)
                ok += 1
            except Exception as e:  # noqa: BLE001
                failed.append((name, F, str(e)[:90]))
        tot += ok
        with open(os.path.join(od, "index.html"), "w", encoding="utf-8") as f:
            f.write(_gallery_html(name, floors))
        print(f"[{i}/{len(names)}] {name:6s} {ok}/{len(floors)} 层", flush=True)
    # 不再写总目录 _dxf_index.html：总目录归 _dxf_cad_render.py 所有（它用 A|B 并排模板、
    # 带中文楼名，且自带「单栋调试不写总目录」的保护）。本脚本以前只按本次处理的楼重建总目录，
    # 于是 `python _dxf_png_batch.py c006` 会把 48 栋的总目录覆盖成只剩 c006
    # （2026-09-10 事故，用户「原来是对的，现在不对了」）。
    print(f"\n=== 完成: {tot} 张 PNG / {len(names)} 栋 / 失败 {len(failed)} ===")
    for nm, F, err in failed[:30]:
        print(f"  FAIL {nm} F{F}: {err}")


if __name__ == "__main__":
    main()
