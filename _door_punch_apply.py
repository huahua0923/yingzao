# -*- coding: utf-8 -*-
"""把「新门判据 + 门洞挖穿」外科式地应用到已交付楼层（不动轮廓/房间/窗/柱/楼梯井）。

背景
----
交付链 = recognize() -> _wall_thin_force.py。内墙由后者从 DXF 重新配对生成，
它不认识门，所以内墙上的门洞会被冲掉；而 recognize 的内墙又是「粗环 blob」不可用。
整栋重跑 recognize 会连带改掉窗数等无关量，爆炸半径大。

本脚本只做用户报的两件事：
  1) 门判据换成 _hinge_leaf（不再把「墙垛/窗户」当门 —— 用户「不能把窗户识别成门」）
  2) 按 _door_boxes 算出的门洞盒把门洞从墙上挖穿（用户「门夹在墙里看不到」）
门来自 `_tmp_<name>_door`（recognize 临时产物，同一坐标系，轮廓对称差已验 0）。
墙在交付层上就地挖洞，其余字段一字不动。

安全
----
默认干跑（只报不写）。`--apply` 才写盘，且先整层备份到 .orig/before_doorpunch_<ts>/。
写入前逐层过门槛，任一条不过该层跳过（不写）。

用法: python _door_punch_apply.py <name> [--apply]
"""
import os, sys, glob, json, shutil, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import Polygon, box, Point
from shapely.ops import unary_union

NAME, APPLY = None, False
for _a in sys.argv[1:]:
    if _a == "--apply":
        APPLY = True
    else:
        NAME = _a
NAME = NAME or "c019"

ROOT = r"D:\gym3d\data\buildings\%s" % NAME
FD = os.path.join(ROOT, "floors")
TMP = r"D:\gym3d\_tmp_%s_door" % NAME

MIN_PART_AREA = 0.03    # 与 _wall_thin_batch 建墙同一碎屑门槛
SLIVER_ABS = 1.5        # 逐层「非门洞的额外损失」上限(㎡)：只应来自 <0.03㎡ 的切角碎屑
                        # （实测 0.39~0.70㎡ ≈ 20 块边角；真门洞 6.6~9.8㎡，量级分明）
MAX_LOSS_PCT = 8.0      # 兜底上限：门洞占比不可能超过此值
BIG_WALL = 5.0          # 面积 ≥ 此值的墙，挖洞后须仍保留 ≥ 80% 面积
BIG_KEEP = 0.80


def W(w):
    P = Polygon(w["poly"])
    if not P.is_valid:
        P = P.buffer(0)
    for h in w.get("holes") or []:
        if len(h) >= 3:
            H = Polygon(h)
            if H.is_valid and not H.is_empty:
                P = P.difference(H)
    return P


def solid_area(walls):
    return sum(W(w).area for w in walls)


def punch(wall, boxU, alloc):
    """挖洞后的新墙列表（0/1/多块）。洞 = gap 不是 hole：盒深 > 墙厚，结果通常是断成两段。

    id 必须唯一：门洞把一片墙切成多块后，若各块共用同一个 id，build_walls 会把
    windows[].wallId 匹配到**每一块**（窗被复制到所有碎片上）。故面积最大的一块继承原
    id（保住窗归属），其余各块从 alloc 取新 id；原本就没 id 的墙（_wall_thin_batch 重建的
    内墙，schema 违约）一律补一个。
    """
    P = W(wall)
    if P.is_empty:
        return []
    Q = P.difference(boxU).buffer(0)
    if Q.is_empty:
        return []
    parts = [G for G in ([Q] if Q.geom_type == "Polygon" else list(Q.geoms))
             if G.area > MIN_PART_AREA]
    parts.sort(key=lambda G: -G.area)
    out = []
    for k, G in enumerate(parts):
        nw = dict(wall)
        if k == 0 and wall.get("id"):
            pass                                  # 最大块继承原 id（窗归属不变）
        else:
            nw["id"] = "x%d" % alloc[0]
            alloc[0] += 1
        nw["poly"] = [[round(x, 3), round(y, 3)] for x, y in G.exterior.coords][:-1]
        nw["holes"] = [h for h in
                       ([[round(x, 3), round(y, 3)] for x, y in ring.coords][:-1]
                        for ring in G.interiors)
                       if len(h) >= 4]
        out.append(nw)
    return out


def cut_stats(walls, doors):
    """返回 (门总数, 门心不在任何墙内数, 沿墙走向 ±0.4m 都出墙数)。"""
    P = [W(w) for w in walls]
    nc = nt = 0
    for d in doors:
        if any(Q.contains(Point(d["x"], d["y"])) for Q in P):
            continue
        nc += 1
        ok = True
        for sgn in (1, -1):
            q = (Point(d["x"] + sgn * 0.4, d["y"]) if d["horiz"]
                 else Point(d["x"], d["y"] + sgn * 0.4))
            if any(Q.contains(q) for Q in P):
                ok = False
                break
        if ok:
            nt += 1
    return len(doors), nc, nt


def big_wall_kept(old_walls, new_walls):
    """面积 ≥ BIG_WALL 的旧墙，挖洞后须仍保留 ≥ BIG_KEEP 面积（防止门洞盒把它整个吃掉）。"""
    bad = []
    for w in old_walls:
        A = W(w)
        if A.area < BIG_WALL:
            continue
        kept = sum(A.intersection(W(nw)).area for nw in new_walls)
        if kept < BIG_KEEP * A.area:
            bad.append((w.get("id"), round(A.area, 2), round(kept, 2)))
    return bad


def main():
    if not os.path.isdir(TMP):
        print("缺少临时产物 %s —— 先跑 python _run_c019_tmp.py %s" % (TMP, NAME))
        return 1
    print("=== %s  门判据换新 + 门洞挖穿  [%s] ===" % (NAME, "APPLY" if APPLY else "DRY-RUN"))
    bk = os.path.join(ROOT, ".orig", "before_doorpunch_" + time.strftime("%Y%m%d_%H%M%S"))
    if APPLY:
        os.makedirs(bk, exist_ok=True)

    acc = dict(d_old=0, d_new=0, c_old=0, c_new=0, ok=0, skip=0)
    for fp in sorted(glob.glob(os.path.join(FD, "floor*.json"))):
        bn = os.path.basename(fp)
        F = int(bn[5:-5])
        tfp = os.path.join(TMP, bn)
        if not os.path.exists(tfp):
            print("  F%-2d 跳过: 临时层缺失" % F)
            acc["skip"] += 1
            continue
        fl = json.load(open(fp, encoding="utf-8"))
        new_doors = (json.load(open(tfp, encoding="utf-8")).get("doors") or [])
        boxes = [box(float(d["bx0"]), float(d["by0"]), float(d["bx1"]), float(d["by1"]))
                 for d in new_doors if all(k in d for k in ("bx0", "by0", "bx1", "by1"))]
        if not new_doors or not boxes:
            print("  F%-2d 跳过: 新门缺门洞盒" % F)
            acc["skip"] += 1
            continue

        old_doors = fl.get("doors") or []
        a0 = solid_area(fl["walls"])
        boxU = unary_union(boxes)
        # 门洞该挖掉的面积（= 各墙与门洞盒的交）——这是唯一「被授权」的损失
        removed = 0.0
        for w in fl["walls"]:
            P = W(w)
            if not P.is_empty:
                removed += P.intersection(boxU).area
        alloc = [0]     # 本层 id 分配器：新 id 形如 x0, x1, ...（与 w<F>-n / win<F>-n 不冲突）
        new_walls = []
        for w in fl["walls"]:
            parts = punch(w, boxU, alloc)
            for part in parts:
                if not part.get("id"):
                    part["id"] = "x%d" % alloc[0]
                    alloc[0] += 1
                new_walls.append(part)
        a1 = solid_area(new_walls)
        loss = 100.0 * (a0 - a1) / a0 if a0 else 0.0
        sliver = (a0 - a1) - removed          # 多损失的只应是 <0.03㎡ 碎屑
        bad = big_wall_kept(fl["walls"], new_walls)
        _, _, c_old = cut_stats(fl["walls"], old_doors)
        nd, _, c_new = cut_stats(new_walls, new_doors)
        ok = (sliver <= SLIVER_ABS and loss <= MAX_LOSS_PCT) and not bad and new_walls

        acc.update(d_old=acc["d_old"] + len(old_doors), d_new=acc["d_new"] + nd,
                   c_old=acc["c_old"] + c_old, c_new=acc["c_new"] + c_new)
        print("  F%-2d | 门 %3d->%3d 挖穿 %2d/%2d->%2d/%2d | 墙 %3d->%3d 实心%8.2f->%8.2f㎡"
              " (门洞%6.2f 碎屑%+.3f, -%.2f%%) | %s%s"
              % (F, len(old_doors), nd, c_old, max(len(old_doors), 1), c_new, max(nd, 1),
                 len(fl["walls"]), len(new_walls), a0, a1, removed, sliver, loss,
                 "PASS" if ok else "SKIP", (" 大墙被吃:%s" % bad) if bad else ""))
        if not ok:
            acc["skip"] += 1
            continue
        acc["ok"] += 1
        if APPLY:
            if not os.path.exists(os.path.join(bk, bn)):
                shutil.copy2(fp, os.path.join(bk, bn))
            fl["walls"] = new_walls
            fl["doors"] = new_doors
            json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)

    print("\n合计: 层 %d 通过 / %d 跳过" % (acc["ok"], acc["skip"]))
    print("      门 %d -> %d" % (acc["d_old"], acc["d_new"]))
    print("      门洞挖穿 %d/%d (%.0f%%) -> %d/%d (%.0f%%)"
          % (acc["c_old"], acc["d_old"], 100.0 * acc["c_old"] / max(acc["d_old"], 1),
             acc["c_new"], acc["d_new"], 100.0 * acc["c_new"] / max(acc["d_new"], 1)))
    if APPLY:
        print("备份 -> %s" % bk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
