# -*- coding: utf-8 -*-
r"""删掉 `floors/floor*.json` 里**几何完全重合、房号相同**的重复房间（唯一所有者）。

为什么要有这个（实测，不是猜）：
  · c041 第 0 层 12 间房其实是 6 间 —— `41-01-00` 等 6 个房号各出现**两次**，
    两份的 `poly` 逐点相同；**一份有用途、另一份 `purpose` 为空**。六层全中。
    后果：本层房间面积被算成两倍（754.21 m²，实际 377.10 m²），
    而且 SU 里会画出两片完全重合的地垫（共面 ⇒ 闪面）。
  · c103 同病，且量更大（F1~F4 每层 3096.6 m² 的重复面积）。
  · 注意：这两栋的 `rooms.json` **没有**重复（c041 实测 0 条），重复只存在于
    `floors/*.json` 的 `rooms[]` —— 而 SU 分层建模这条链读的正是 floors。

判据（宁可不删也不删错）：
  ① 房号 `number` 完全相同；
  ② 多边形**逐点**相同（去掉闭合末点后，正向/反向 + 任意起点旋转，取最小表示相等）
     —— 用坐标精确比较，不用 shapely：c103 有非法多边形会让 GEOS 抛 TopologyException。
  ③ 同一组里只留一条：**优先留有用途的那条**；都空则留第一条；
     若同组有**两条以上用途都非空且互不相同** ⇒ 该层**拒绝改写**（要人看，不猜）。

用法：
  python _scratch/_dedup_floor_rooms.py c041 c103            # 只报，不写（默认）
  python _scratch/_dedup_floor_rooms.py c041 c103 --apply    # 备份后改写
备份：`data/buildings/<name>/.orig/floors.before_dedup/floor*.json`（沿用 .orig 既有命名）。
写盘：先写 `.tmp` 再 `os.replace`（原子；直写会把交付文件截成 0 字节）。
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BUILDINGS = os.path.join(ROOT, "data", "buildings")


def canon(poly):
    """多边形的精确最小表示：去闭合末点 → 正/反向 → 各旋转 → 取最小元组。"""
    pts = [(round(float(x), 9), round(float(y), 9)) for x, y in poly]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return ()

    def rot(seq):
        i = min(range(len(seq)), key=lambda k: seq[k])
        return tuple(seq[i:] + seq[:i])

    return min(rot(pts), rot(pts[::-1]))


def read_indent(raw):
    m = re.search(r'\n(\s+)"', raw)
    return len(m.group(1)) if m else 1


def plan_floor(doc):
    """返回 (保留下标集合, 被删清单, 拒绝原因)。不写盘。"""
    rooms = doc.get("rooms") or []
    groups = {}
    for i, r in enumerate(rooms):
        groups.setdefault((str(r.get("number")), canon(r["poly"])), []).append(i)
    keep, dropped, refuse = [], [], []
    for key, idxs in groups.items():
        if len(idxs) == 1:
            keep.extend(idxs)
            continue
        withp = [i for i in idxs if (rooms[i].get("purpose") or "").strip()]
        if len(withp) > 1:
            pus = {(rooms[i].get("purpose") or "").strip() for i in withp}
            if len(pus) > 1:
                refuse.append((key[0], len(idxs), sorted(pus)))
                keep.extend(idxs)
                continue
        win = withp[0] if withp else idxs[0]
        keep.append(win)
        for i in idxs:
            if i != win:
                dropped.append((i, rooms[i].get("number"), rooms[i].get("purpose"),
                                Polygon_area(rooms[i]["poly"])))
    return sorted(keep), dropped, refuse


def Polygon_area(poly):
    """鞋带公式（不用 shapely：c103 有非法多边形）。"""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--apply", action="store_true", help="真写盘（默认只报）")
    a = ap.parse_args()

    total_drop = 0
    for name in a.names:
        base = os.path.join(BUILDINGS, name)
        fd = os.path.join(base, "floors")
        if not os.path.isdir(fd):
            print("✗ %s 没有 floors/ 目录" % name)
            continue
        print("=== %s ===" % name)
        files = [f for f in sorted(os.listdir(fd))
                 if f.startswith("floor") and f.endswith(".json")]
        for fn in files:
            fp = os.path.join(fd, fn)
            raw = io.open(fp, encoding="utf-8").read()
            doc = json.loads(raw)
            keep, dropped, refuse = plan_floor(doc)
            n0, n1 = len(doc.get("rooms") or []), len(keep)
            if refuse:
                print("  ✗ %s 有 %d 组「多条用途互不相同」的重复 —— 拒绝改写这一层：%s"
                      % (fn, len(refuse), refuse[:3]))
                continue
            if not dropped:
                print("  · %s  rooms=%d 无重复" % (fn, n0))
                continue
            a0 = sum(Polygon_area(doc["rooms"][i]["poly"]) for i in range(n0))
            a1 = sum(Polygon_area(doc["rooms"][i]["poly"]) for i in keep)
            print("  %s %s rooms %d → %d（删 %d 条），本层面积 %.2f → %.2f m²"
                  % ("✎" if a.apply else "·", fn, n0, n1, len(dropped), a0, a1))
            for i, num, pu, ar in dropped:
                print("        删 #%-3d %-12s 用途=%-10s %8.4f m²"
                      % (i, num, pu if pu else "(空)", ar))
            total_drop += len(dropped)
            if not a.apply:
                continue
            # ---- 备份（沿用 .orig 命名）----
            bk = os.path.join(base, ".orig", "floors.before_dedup")
            os.makedirs(bk, exist_ok=True)
            dst = os.path.join(bk, fn)
            if not os.path.exists(dst):
                with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
                    f.write(raw)
            # ---- 原子写 ----
            doc["rooms"] = [doc["rooms"][i] for i in keep]
            out = json.dumps(doc, ensure_ascii=False, indent=read_indent(raw))
            tmp = fp + ".tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(out)
            os.replace(tmp, fp)
    print("\n合计删除 %d 条重复房间%s" % (total_drop, "（已写盘）" if a.apply else "（未写盘，加 --apply 才写）"))


if __name__ == "__main__":
    main()
