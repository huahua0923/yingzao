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
**这个目录由本阶段自带的前置 `_door_tmp_recognize.ensure()` 产出** —— 缺了就现出。
墙在交付层上就地挖洞，其余字段一字不动。

安全
----
默认干跑（只报不写）。`--apply` 才写盘，且先整层备份到 .orig/before_doorpunch_<ts>/。
写入前逐层过门槛，任一条不过该层跳过（不写）。

用法: python _door_punch_apply.py <name> [--apply]
"""
import os, sys, glob, json, shutil, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.recognizer import openings
import _wall_thin_batch as B
import _door_tmp_recognize

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
TMP = _door_tmp_recognize.tmp_dir(NAME)      # 只此一处定义，别在两边各写一份

MIN_PART_AREA = 0.03    # 与 _wall_thin_batch 建墙同一碎屑门槛
SLIVER_ABS = 1.5        # 逐层「非门洞的额外损失」上限(㎡)：只应来自 <0.03㎡ 的切角碎屑
                        # （实测 0.39~0.70㎡ ≈ 20 块边角；真门洞 6.6~9.8㎡，量级分明）
MAX_LOSS_PCT = 8.0      # 兜底上限：门洞占比不可能超过此值
BIG_WALL = 5.0          # 面积 ≥ 此值的墙，挖洞后须仍保留 ≥ 80% 面积
BIG_KEEP = 0.80


# 墙 dict → Polygon：走 openings 的同一份（先前这里自己写了一份，改一处漏一处）。
from backend.recognizer import openings                          # noqa: E402


def W(w):
    g = openings.wall_poly(w)
    return g if g is not None else Polygon()


def solid_area(walls):
    return sum(W(w).area for w in walls)


def punch(wall, boxes, alloc):
    """挖洞后的新墙列表（0/1/多块）。洞 = gap 不是 hole：盒深 > 墙厚，结果通常是断成两段。

    **几何交给 `openings.punch_walls`**（全仓唯一的挖洞实现）。这里只留本脚本特有的 id
    分配：跨层共用一个 alloc，新 id 形如 x0/x1…，与 w<F>-n / win<F>-n 不冲突。
    `punch_walls` 返回的碎块已按面积从大到小排，故 parts[0] 最大、继承原 id（窗归属不变）。

    ★ `boxes` 必须是**盒的列表**，不许传 union 之后的 MultiPolygon —— `punch_walls` 对每个
    元素做 `_snap_out`（取 `b.bounds`），对 MultiPolygon 取到的是**整体外接矩形**。
    c044 F1 实测：15.66㎡ 被折成 726.01㎡（46 倍），墙 234->112、实心 167.02->66.71㎡（−60%）、
    碎屑 +100.309㎡ —— 三层门槛拦住的是**这个折出来的大矩形**，不是真门洞。
    """
    P = W(wall)
    if P.is_empty:
        return []
    parts = openings.punch_walls([wall], boxes, MIN_PART_AREA)
    out = []
    for k, nw in enumerate(parts):
        if k == 0 and wall.get("id"):
            pass                                  # 最大块继承原 id（窗归属不变）
        else:
            nw["id"] = "x%d" % alloc[0]
            alloc[0] += 1
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
    # 前置产物：门与门洞盒来自一次 recognize。此前这一步**不在公共流程里**
    # （产出它的脚本 2026-09-14 被归档），于是 92 栋的门洞自那天起一次都没打过。
    # 现在本阶段自带前置：缺了就现出，不指望调用方记得先手工跑一个不在表里的脚本。
    if _door_tmp_recognize.ensure(NAME) != 0:
        print("前置失败：临时产物 %s 没产出 ⇒ 门洞这一步做不了" % TMP)
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
            parts = punch(w, boxes, alloc)     # 传**盒列表**，不传 boxU（见 punch 的 ★）
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
            # 墙被切成新段、门换成新盒 → **门宿主**（wallId 指向哪面墙）必须重登记：
            # 不重登记的话交付数据里的 wallId 指向已经不存在的墙（门禁 I11 会逐层报悬空门）。
            nd_host = openings.register_hosts(fl["doors"], fl["walls"], F)
            json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
            if nd_host:
                print("       (F%d 重登记宿主后仍悬空的门 %d 扇)" % (F, nd_host))

    print("\n合计: 层 %d 通过 / %d 跳过" % (acc["ok"], acc["skip"]))
    print("      门 %d -> %d" % (acc["d_old"], acc["d_new"]))
    print("      门洞挖穿 %d/%d (%.0f%%) -> %d/%d (%.0f%%)"
          % (acc["c_old"], acc["d_old"], 100.0 * acc["c_old"] / max(acc["d_old"], 1),
             acc["c_new"], acc["d_new"], 100.0 * acc["c_new"] / max(acc["d_new"], 1)))
    if APPLY:
        print("备份 -> %s" % bk)
        # 挖洞改了墙 → 楼梯**井道**（按墙四向扩出来的）失效，必须按新墙重算一次。
        # 井道是跨层量，得全楼写完再算（单一所有者 = B.refresh_shafts）。
        n_fl, n_g = B.refresh_shafts(NAME)
        if n_fl:
            print("   井道按新墙刷新 %d 层 / %d 口井 —— 楼板洞已变，需重建 GLB" % (n_fl, n_g))
    return 0


if __name__ == "__main__":
    sys.exit(main())
