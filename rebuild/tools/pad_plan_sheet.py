# -*- coding: utf-8 -*-
"""把交付包里**每层的房间地垫**与**模型自己的墙环**画在同一张平面图上，用来逐层核实
「色块是不是和模型叠在一起」。

为什么要出这张图：页面上色块铺在楼**内**，外墙不透明时**从外面根本看不见**（2026-10-17 用户要的
样子），所以「逐层核实地板对不对」只能走平面。三维截屏一次只能看一层、还要转视角；
平面图 12 层拼一张，一眼看完全部。

★ 与已有件的关系（Glob 实查，**不重复造**）：
  · `rebuild/tools/rooms_to_pack.py` = **生成**侧（房间表 → 包内 `baseline/floors/*.json`）；
  · `rebuild/tools/build_rooms.py`   = **识别**侧（图纸 → 房间表）。本件是**核验**侧：只读包、出图、不改包。
  · `gates/*.py` 里没有画地垫的（J-09.1.1 只量点选与限流）。

看图时按这三条判，不靠感觉：
  ① 该层地垫的轮廓应贴着模型墙环的**内侧**（离缝 ≈ 半个墙厚，不该大片空白、更不该越墙而出）；
  ② 每根柱心（绿点）应落在地垫内或刚好压在地垫边界上（柱子是房间之间的分隔）；
  ③ 裙房那几层（`floor0`…`floor6`）地垫该铺满裙房外廓；塔楼那几层（`floor7`…`floor10`）只铺塔楼。

两把尺子：本脚本**自己**从柱心按下标配对算平移（不读页面那个数），页面也在跑同一件事。
两个估计器目标一致时它们应当给出**同一个数** —— 打印出来对照。注意方向：**不一致就一定有一处错**，
一致只是必要不充分（铁律 018）。
"""
import json
import os
import sys
from collections import Counter

from PIL import Image, ImageDraw

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PACK = os.path.join(ROOT, "packs", "cdut-main", "c006")

W, H = 430, 300          # 每格像素
COLS = 4
PAD_ALPHA = 140          # 地垫填充透明度（墙环要压在上面看得清）
TOL_MM = 5.0             # 每层自证：柱心残差上限（与页面 `FRAME_TOL_MM` 同值同义）
MARGIN_MM = 3000         # 图边留白


def hue(s):
    h = 0
    for ch in str(s):
        h = (h * 31 + ord(ch)) % 360
    return h


def hsl2rgb(h, s=0.58, l=0.60):
    """与页面 `rcolor` 同一个色（`hsl(H,58%,60%)`）——两处各写一套必然漂，所以同式同参。"""
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c / 2
    seg = int(h // 60) % 6
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][seg]
    return tuple(int(255 * (v + m) + 0.5) for v in (r, g, b))


def rings_of(flat):
    """`ring` 是扁平 [x,y,x,y,…]（mm），首尾不闭 ⇒ 调用处补收尾点。"""
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]


def shift_of(base_cols, mdl_cols):
    """按**下标**配对柱心（按最近邻会全配成假对 —— 铁律 194），并做每层自证。"""
    if not base_cols or len(base_cols) != len(mdl_cols):
        return None
    dd = [((m["bbox"][0] + m["bbox"][2]) / 2 - c["x"] * 1000,
           (m["bbox"][1] + m["bbox"][3]) / 2 - c["y"] * 1000)
          for c, m in zip(base_cols, mdl_cols)]
    dx = sorted(p[0] for p in dd)[len(dd) // 2]
    dy = sorted(p[1] for p in dd)[len(dd) // 2]
    worst = max(((p[0] - dx) ** 2 + (p[1] - dy) ** 2) ** 0.5 for p in dd)
    return None if worst > TOL_MM else (dx, dy)


def _d_pt_seg(px, py, ax, ay, bx, by):
    """点到线段的距离（mm）。"""
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    if L2 == 0.0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    return ((px - (ax + t * vx)) ** 2 + (py - (ay + t * vy)) ** 2) ** 0.5


def wallhug_report(cat, fdir, dx, dy, min_edge=1000.0, tol=300.0):
    """每层「地垫的长边贴不贴墙」。

    判据（用户令「各个地板的样子还是不太正确」要能定罪，所以必须是一个**数**而不是感觉）：
      取该层每片地垫（`rooms` + `circulation`）中**长于 `min_edge`** 的边，量它的**中点**
      到该层**模型 WALL/PARAPET 环**的最近距离；> `tol` 的记为「悬空边」。
    合理解释：正确的地垫，房间与房间、房间与走廊之间由墙分开 ⇒ 长边几乎都该压在墙上。
      出现成片悬空长边 ⇒ 那条边是**分区算出来的分界，不是墙**（色块边界不贴模型）。
    ★ 这条判据对「10 cm 台阶」是瞎的（台阶每段都不到 1 m）—— 它专门抓**长的一条假分界**。
    """
    print("")
    print("每层地垫长边贴墙率（长边 = 边长 > %.1f m，悬空 = 边中点离最近墙 > %.2f m）"
          % (min_edge / 1000.0, tol / 1000.0))
    for f in cat["floors"]:
        node = f["node"]
        p = os.path.join(fdir, node + ".json")
        we = []
        for b in f["blocks"]:
            if b["layer"] not in ("WALL", "PARAPET") or not b.get("ring"):
                continue
            rr = rings_of(b["ring"])
            for i in range(len(rr)):
                ax, ay = rr[i]
                bx, by = rr[(i + 1) % len(rr)]
                we.append((ax, ay, bx, by))
        if not we or not os.path.exists(p):
            print("  %-8s 无墙环或无 baseline，跳过" % node)
            continue
        d = json.load(open(p, encoding="utf-8"))
        tot = free = 0
        frl = 0.0
        longest = (0.0, 0.0)
        for key in ("rooms", "circulation"):
            for r in (d.get(key) or []):
                poly = r.get("poly")
                if not poly or len(poly) < 3:
                    continue
                pts = [(x * 1000 + dx, y * 1000 + dy) for x, y in poly]
                for i in range(len(pts)):
                    ax, ay = pts[i]
                    bx, by = pts[(i + 1) % len(pts)]
                    L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
                    if L < min_edge:
                        continue
                    tot += 1
                    mx, my = (ax + bx) / 2, (ay + by) / 2
                    dd = min(_d_pt_seg(mx, my, *e) for e in we)
                    if dd > tol:
                        free += 1
                        frl += L
                        if L > longest[0]:
                            longest = (L, dd)
        if tot == 0:
            print("  %-8s 没有长边" % node)
            continue
        print("  %-8s 长边 %3d 条，悬空 %3d 条（%.1f%%，共 %.1f m，最长 %.2f m/离墙 %.2f m）"
              % (node, tot, free, 100.0 * free / tot, frl / 1000.0,
                 longest[0] / 1000.0, longest[1] / 1000.0))


def lay_ord(node):
    """层号：`floorK` = 第 K+1 层（0 基）；`B1` 排在最前，`roof*` 排最后。"""
    if node.startswith("floor") and node[5:].isdigit():
        return int(node[5:])
    return -1 if node.startswith("B1") else 10 ** 6


def main():
    # 用法：
    #   python pad_plan_sheet.py              只画全部层，拼成一张（每格 430x300）
    #   python pad_plan_sheet.py floor7 ...   只画点名的层，每格放大（看局部细节用）
    only = [a for a in sys.argv[1:] if a and not a.startswith("-")]
    cat = json.load(open(os.path.join(PACK, "meta", "blocks.json"), encoding="utf-8"))
    fdir = os.path.join(PACK, "baseline", "floors")
    if only:
        keep = [f for f in cat["floors"] if f["node"] in only]
        miss = [w for w in only if w not in [f["node"] for f in keep]]
        if miss:
            print("点名的层不在包里：" + " ".join(miss))
            return 3
        cat = dict(cat, floors=keep)
    globals()["W"], globals()["H"], globals()["COLS"] = (760, 520, min(2, len(cat["floors"]))) if only else (430, 300, COLS)

    votes, per_floor = [], {}
    for f in cat["floors"]:
        node = f["node"]
        p = os.path.join(fdir, node + ".json")
        if not os.path.exists(p):
            per_floor[node] = ("无 baseline 文件", None)
            continue
        d = json.load(open(p, encoding="utf-8"))
        mdl = [b for b in f["blocks"] if b["layer"] == "COL"]
        got = shift_of(d.get("columns") or [], mdl)
        if got is None:
            per_floor[node] = ("柱心对不上 %d/%d" % (len(d.get("columns") or []), len(mdl)), None)
            continue
        per_floor[node] = ("", got)
        votes.append((round(got[0] / 10), round(got[1] / 10), got))
    if not votes:
        print("配准失败：没有任何一层通过自证 ⇒ 一张也不画")
        return 2
    key = Counter((v[0], v[1]) for v in votes).most_common(1)[0][0]
    grp = [v[2] for v in votes if (v[0], v[1]) == key]
    dx = sum(g[0] for g in grp) / len(grp)
    dy = sum(g[1] for g in grp) / len(grp)
    print("本脚本现求的平移 D = %+.3f / %+.3f m（%d 层同意，另外 %d 层没投票）"
          % (dx / 1000, dy / 1000, len(grp), len(cat["floors"]) - len(grp)))
    for node, (why, _) in per_floor.items():
        if why:
            print("  - %-8s %s" % (node, why))

    wallhug_report(cat, fdir, dx, dy)

    order = sorted([f for f in cat["floors"]], key=lambda f: lay_ord(f["node"]))
    rows = (len(order) + COLS - 1) // COLS
    img = Image.new("RGB", (W * COLS, H * rows), (255, 255, 255))
    dr = ImageDraw.Draw(img, "RGBA")

    for idx, f in enumerate(order):
        node = f["node"]
        ox, oy = (idx % COLS) * W, (idx // COLS) * H
        # 平面框 = 该层**模型** SLAB+WALL 的包围盒（场地帧 mm）＋留白
        rel = [b for b in f["blocks"] if b["layer"] in ("SLAB", "WALL")]
        if not rel:
            dr.text((ox + 8, oy + 8), node + " 该层没有 SLAB/WALL", fill=(150, 0, 0))
            continue
        x0 = min(b["bbox"][0] for b in rel) - MARGIN_MM
        y0 = min(b["bbox"][1] for b in rel) - MARGIN_MM
        x1 = max(b["bbox"][2] for b in rel) + MARGIN_MM
        y1 = max(b["bbox"][3] for b in rel) + MARGIN_MM
        sc = min((W - 16) / (x1 - x0), (H - 34) / (y1 - y0))

        def to_px(X, Y, _ox=ox, _oy=oy, _x0=x0, _y0=y0, _sc=sc):
            return (_ox + 8 + (X - _x0) * _sc, _oy + 26 + (Y - _y0) * _sc)

        # ① 地垫：包帧 m -> 场地 mm（+D）-> 像素
        #   ★ 有 baseline 文件就铺，**不管它投没投票** —— 页面正是这么做的（`buildRooms` 第 2 趟铺
        #     `datas` 里**每一层**，只把没投票的层记名）。早先这里只铺投过票的层，于是 floor6
        #     在本图 p=0、在页面却有 43 片 ⇒ **两把尺子口径不一致**（正是铁律 018 那种「看着都对不上」）。
        npad = 0
        why, got = per_floor.get(node, ("无读数", None))
        if os.path.exists(os.path.join(fdir, node + ".json")):
            d = json.load(open(os.path.join(fdir, node + ".json"), encoding="utf-8"))
            for key, iscirc in (("rooms", False), ("circulation", True)):
                for r in (d.get(key) or []):
                    poly = r.get("poly")
                    if not poly or len(poly) < 3:
                        continue
                    pts = [to_px(px * 1000 + dx, py * 1000 + dy) for px, py in poly
                           if isinstance(px, (int, float)) and isinstance(py, (int, float))]
                    if len(pts) < 3:
                        continue
                    col = hsl2rgb(hue("交通空间" if iscirc else (r.get("purpose") or "未标")))
                    dr.polygon(pts, fill=col + (PAD_ALPHA,))
                    dr.line(pts + [pts[0]], fill=col + (255,), width=1)
                    npad += 1
        # ② 模型墙环（细深线，压在地垫上）
        for b in f["blocks"]:
            if b["layer"] not in ("WALL", "PARAPET") or not b.get("ring"):
                continue
            pts = [to_px(rx, ry) for rx, ry in rings_of(b["ring"])]
            if len(pts) >= 3:
                dr.line(pts + [pts[0]], fill=(30, 30, 30, 200), width=1)
        # ③ 柱心（绿点）
        for b in f["blocks"]:
            if b["layer"] != "COL":
                continue
            px, py = to_px((b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2)
            dr.ellipse([px - 1.7, py - 1.7, px + 1.7, py + 1.7], fill=(10, 110, 20))
        dr.rectangle([ox, oy, ox + W - 1, oy + H - 1], outline=(190, 190, 190))
        dr.text((ox + 8, oy + 7), "%s  pads=%d%s" % (node, npad, ("  [" + why + "]") if why else ""),
                fill=(0, 0, 0))

    out = os.path.join(ROOT, "demo", "_shots", "pads-plan-2026-10-17.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    print("写出 %s  (%d x %d, %d 层)" % (out, img.width, img.height, len(order)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
