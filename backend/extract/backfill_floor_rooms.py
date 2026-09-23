# -*- coding: utf-8 -*-
"""把 rooms.json 回填进 floors/floor*.json 的 rooms[]（房间点击几何），不重识别。

机理：recognize() 在 extract_floor 里读 p.rooms 生成本层 rooms_json（见 floor.py 房间段：
对每间 rooms_data 中 floor==F 且 outline.contains(质心) 的房间，写 {id,poly,purpose,number}）。
当 rooms.json 是在 floor JSON 生成**之后**才补齐（如宿舍公寓簇此前 rooms.json=[]），
floor JSON 的 rooms[] 仍是空 → 3D 查看器点不到房间。本脚本对既有楼层文件做同样的
注入，**不动 walls/outline/windows/doors**，避免重识别带来的墙漂移。

用法:
  python backend/extract/backfill_floor_rooms.py c031            # 回填并写回
  python backend/extract/backfill_floor_rooms.py c031 --verify   # 只打印将注入数, 不写
  python backend/extract/backfill_floor_rooms.py c031 --floors-dir .orig/floors.before_rooms  # 指定楼层目录(验证用)
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon, Point

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))  # 仓库根
sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))        # backend/
from paths import BUILDINGS  # noqa: E402
from recognizer import outline as OUT  # noqa: E402

DATA = str(BUILDINGS)


def _key(r):
    """判重键：房号 + 用途，两侧都归一成字符串。

    ⚠️ 不能直接 `r.get("purpose")`：rooms.json 里没填用途的房是 **None**，而
    floor.py 写交付楼层时归一成 **""**（`r.get("purpose") or ""`）。None != ""，
    于是判重恒不命中，同一间房被反复追加（2026-09-12 实测 ny27 每层 6 间变 12 间、
    c041/c103 各层多出 5~8 个重复 id）。
    """
    return ((r.get("number") or ""), (r.get("purpose") or ""))


def _dedupe_by_id(rooms):
    """按 id 去重（保序）。房号可重复（一房多标），id 不会 —— 用 id 才不会误删真房间。

    修历史脏数据：早期版本判重键 None/"" 不匹配，把同一间房写了两遍。
    """
    seen, out = set(), []
    for r in rooms:
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        out.append(r)
    return out


def backfill_floors(name, floors_dir=None, verify=False,
                    refresh_purpose=False, report=None):
    """把某楼 rooms.json 回填进 floors/*.json 的 rooms[]。返回 (回填数, 逐层 dict)。
    floors_dir 默认 <楼>/floors；verify=True 只统计不写。

    `refresh_purpose=True`（2026-09-13 新增）：**只把已存在房间的 purpose 刷成
    rooms.json 的值，房间集合一个字不动**（不去重、不追加）。为什么必须有这个口子：
    本函数原设计只"补缺"（`if _key(r) in existing: continue`），够不着"房间在、用途
    却是空的/过时的"这类伤势 —— 而这正是层名角色映射改口径后的形态：floors 的
    rooms[] 早就有了，只有 purpose 要跟着 rooms.json 变。没有它就只能重跑 recognize，
    那会**重建几何**，对 c103/c104（冻结栋）和交付几何已经定型的楼都是不能碰的。

    ⚠️ 配对键是 **(floor, 房号)**，不是 `id`，也不是 `_key`：
      · `_key` 含 purpose = 正是要改的那个字段，拿它配对恒不命中，然后把这间房当新
        房间**追加一遍**（就是 `_key` 注释里那个 ny27 每层 6 间变 12 间的老坑）；
      · `id` 也不行 —— 实测 c027/c041/c104 的 floors id 与当前 rooms.json 的 id 对不上
        （c041 交集 34 间**全部**冲突），那是上一代 rooms.json 编的 id，按它配对会把
        用途**盖到别的房间**上，且一声不响。房号才是这间房的语义身份。

    返回值的元数不变（两个），刷新条数走 `report` 出参（`report["refreshed"]`）——
    另有两个 `_scratch/` 脚本按 `added, byf = backfill_floors(name)` 解包，不能动。
    """
    d = os.path.join(DATA, name)
    fd = floors_dir or os.path.join(d, "floors")
    rp = os.path.join(d, "rooms.json")
    if not os.path.exists(rp):
        return 0, {}
    rooms = json.load(open(rp, encoding="utf-8"))
    if not rooms:
        return 0, {}
    total_add = 0
    total_ref = 0
    by_floor = {}
    # ★ 放不进去的房间必须被**数出来**。原来那个 `continue` 是沉默的：c072 有 180 间
    #   台账房间质心落在轮廓外，本函数照样只打印「回填 0 间」——"一间都没要"和
    #   "根本没有可回填的"在屏幕上长得一模一样（memory: silent-failure-needs-a-voice）。
    #   分三档数，因为它们指向三种不同的病：
    #     no_outline —— 本层轮廓本身是空的 ⇒ **量具坏了**，此时"轮廓外"这个结论无意义
    #     degenerate —— 房间边界自交/退化，连形状都算不上
    #     outside    —— 轮廓有效而房间确实在轮廓外 ⇒ 识别问题，要人看
    skip = {"no_outline": 0, "degenerate": 0, "outside": 0}
    # 配对键 = (楼层, 房号)，**不是 id**。实测 2026-09-13：c027/c041/c104 的 floors
    # rooms[].id 与当前 rooms.json 的 id 对不上（c041 交集 34 间**全部**冲突、
    # c104 59 间里 51 间冲突）—— 那几栋 floors 是**上一代 rooms.json** 写的，而 id 是
    # `base + 排序后下标`，房间集合一变就全体错位。按 id 配对会把用途盖到**别的房间**上，
    # 而且一声不响。房号才是这间房的语义身份（查看器 roomMap 也是用房号比对的）。
    # 房号可重复（一房多标），故值是个列表，按出现顺序一对一消费。
    src_by_key = {}
    for r in rooms:
        k = (r.get("floor"), str(r.get("number")))
        src_by_key.setdefault(k, []).append(r)
    for F in sorted({r.get("floor") for r in rooms if "floor" in r}):
        fp = os.path.join(fd, f"floor{F}.json")
        if not os.path.exists(fp):
            continue
        fl = json.load(open(fp, encoding="utf-8"))
        o = OUT.floor_outline(fl)
        # 轮廓空 ⇒ 下面每间房都会被判成"轮廓外"，而那个结论**不是**关于房间的。
        # 实测（2026-09-24）：floor_outline 传进去一个 int（而不是 floor dict）时
        # 返回的就是空 Polygon + NaN bounds，且 is_valid 仍为 True —— 不抛异常、
        # 不报错，下游一路 contains()→False。所以这里必须自己喊。
        if o.is_empty:
            skip["no_outline"] += 1
            print("  F%d ⚠ 本层轮廓是空的（floor_outline 返回空多边形）——"
                  "这一层的『房间在轮廓外』**不作数**，先查轮廓" % F)
        if refresh_purpose:
            # ★ **只刷用途**：房间集合（有哪些房间）一个字都不动 —— 既不按 id 去重、
            #   也不追加 rooms.json 里多出来的房间。理由（铁律⑰「量什么就写什么」）：
            #   这次验证过的只有"既有房间的 purpose 应当等于 rooms.json 的 purpose"。
            #   去重与追加是**另一件事**（实测 c027 +14 / c041 +20 / c103 +14 / c104 +6、
            #   c103 每层剔重 8~10 条），没量过就不许顺手做掉 —— 那种"顺手"正是
            #   前几次把好楼改坏的路子。
            kept = fl.get("rooms") or []
            n_dup = 0
            add = []
            n_ref = 0
            n_unpair = 0
            used = {}
            for r in kept:
                k = (F, str(r.get("number")))
                bucket = src_by_key.get(k) or []
                i = used.get(k, 0)
                if i >= len(bucket):
                    n_unpair += 1
                    continue
                used[k] = i + 1
                new_p = bucket[i].get("purpose") or ""
                if (r.get("purpose") or "") != new_p:
                    r["purpose"] = new_p
                    n_ref += 1
            if n_unpair:
                print("  F%d ⚠ %d 间在 rooms.json 里找不到同房号 —— 未动它们的用途"
                      % (F, n_unpair))
            total_ref += n_ref
            if n_ref:
                if not verify:
                    # 原子写：直写 json.dump 会把交付楼层文件截成 0 字节。
                    tmp = fp + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(fl, f, ensure_ascii=False)
                    os.replace(tmp, fp)
                print("  F%d 刷新已有房间用途 %d 条" % (F, n_ref))
                by_floor[F] = (0, 0)
            continue
        kept = _dedupe_by_id(fl.get("rooms") or [])
        n_dup = len(fl.get("rooms") or []) - len(kept)
        fl["rooms"] = kept
        # 先刷已存在房间的 purpose（按 id 配对），**再**算 existing —— 顺序不能反：
        # existing 是 `_key`（含 purpose），刷新前算会让 `add` 把刚刷过的房间再追加一遍。
        n_ref = 0
        if refresh_purpose:
            for r in kept:
                s = src_by_id.get(r.get("id"))
                if s is None:
                    continue
                new_p = s.get("purpose") or ""
                old_p = r.get("purpose") or ""
                if old_p != new_p:
                    r["purpose"] = new_p
                    n_ref += 1
        total_ref += n_ref
        existing = {_key(r) for r in kept}
        add = []
        for r in rooms:
            if r.get("floor") != F or "boundary" not in r:
                continue
            b = r["boundary"]
            if len(b) < 3:
                continue
            p = Polygon(b).buffer(0)
            if p.is_empty or not p.is_valid:
                skip["degenerate"] += 1
                continue
            if not o.contains(p.centroid):
                skip["outside"] += 1
                continue
            if _key(r) in existing:
                continue
            add.append({
                "id": r.get("id"),
                "poly": [[round(x, 2), round(y, 2)] for x, y in b],
                "purpose": r.get("purpose") or "",
                "number": r.get("number") or "",
            })
        if add or n_dup or n_ref:
            fl["rooms"] = fl["rooms"] + add
            if not verify:
                # 原子写：直写 json.dump 会让中断/异常把交付楼层文件截成 0 字节。
                tmp = fp + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(fl, f, ensure_ascii=False)
                os.replace(tmp, fp)
            by_floor[F] = (len(add), n_dup)
            total_add += len(add)
            if n_dup:
                print("  F%d 剔除重复房间 %d 条（同 id 多写）" % (F, n_dup))
            if n_ref:
                print("  F%d 刷新已有房间用途 %d 条" % (F, n_ref))
    if report is not None:
        report["refreshed"] = total_ref
        report["skip"] = skip
    return total_add, by_floor


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name = args[0] if args else None
    if not name:
        print("用法: backfill_floor_rooms.py <楼> [--verify] [--floors-dir DIR]"
              " [--refresh-purpose]")
        return 1
    verify = "--verify" in sys.argv
    refresh = "--refresh-purpose" in sys.argv
    d = os.path.join(DATA, name)
    fd = os.path.join(d, "floors")
    for a in sys.argv[1:]:
        if a.startswith("--floors-dir="):
            fd = os.path.join(d, a.split("=", 1)[1])
    rep = {}
    total_add, by_floor = backfill_floors(name, floors_dir=fd, verify=verify,
                                          refresh_purpose=refresh, report=rep)
    print(f"[{name}] 回填 {total_add} 间 (逐层 {by_floor})  "
          + ("(模拟, 未写)" if verify else "(已写)"))
    # 「回填 0 间」必须能区分"没得可回填"和"有房间但一间都放不进去"。
    sk = rep.get("skip") or {}
    n_skip = sum(sk.values())
    if n_skip:
        print(f"[{name}] ⚠ 另有 {n_skip} 间台账房间没进快照："
              f"轮廓空 {sk.get('no_outline', 0)} 层 / 边界退化 {sk.get('degenerate', 0)} 间 / "
              f"质心在轮廓外 {sk.get('outside', 0)} 间")
        if sk.get("no_outline"):
            print(f"[{name}]   轮廓空的那几层，「房间在轮廓外」这个结论不作数 —— 先修轮廓再谈房间")
        if sk.get("outside"):
            print(f"[{name}]   质心在轮廓外 = 房间与轮廓对不上，属识别问题（要人看），"
                  f"不是回填能解决的")
    if refresh:
        print(f"[{name}] 顺带刷新已有房间用途 {rep.get('refreshed', 0)} 条"
              + ("（模拟，未写）" if verify else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
