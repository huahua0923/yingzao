# -*- coding: utf-8 -*-
r"""自交修复「改了多少间」× 「spec 变没变」对账表（**只读**）。

为什么必须有这一份：
  2026-09-13 修自交：**19 栋 / 65 层 / 535 间**（按 `.orig/floors.before_selfint/` 备份数）。
  但同一天的全库 spec 普查 diff（`_probe_spec_census_diff.py`）只有 **2 栋**（c006 / c009）
  的 spec 变了。**19 改 / 2 变**这个落差不能靠嘴解释，必须逐栋给出四个数：
    · rooms          该栋 `floors/*.json` 现盘房间数
    · still_invalid  现盘**仍然** is_valid=False 的（应只剩"保住不改"的 12 间）
    · changed        与 `.orig/floors.before_selfint/` 逐间比，`poly` 变了的间数
    · spec           该栋 spec 与改前是否逐字节相同（读 census_diff 的结果文件）
  判据：`changed > 0 而 spec 相同` 是**允许**的（房间坐标改了，但 spec 里落到 5 位小数后
  地垫几何没变 —— 例如 buffer(0) 只是把自触点拆开、点集没动）；但**必须逐栋看见**，不许笼统说
  "没影响"。反过来 `changed == 0 而 spec 变了` 才是有鬼。

用法：python _scratch/_probe_fix_scope.py
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
BUILDINGS = os.path.join(ROOT, "data", "buildings")
DIFF_DIR = os.path.join(ROOT, "_scratch", "_qa_selfint")


def diff_txt():
    """取**最新**的 spec_census_diff*.txt —— 2026-09-13 踩过：写死文件名会让本表
    一直读旧 diff（"spec 变了 2 栋"），而实际上重跑后是 49/49 逐字节相同。"""
    cand = [os.path.join(DIFF_DIR, f) for f in os.listdir(DIFF_DIR)
            if f.startswith("spec_census_diff") and f.endswith(".txt")]
    return max(cand, key=os.path.getmtime) if cand else None


def changed_specs():
    """从普查 diff 的结果文件里读"哪些 spec 变了"。"""
    out = set()
    p = diff_txt()
    if not p:
        return None
    for ln in io.open(p, encoding="utf-8"):
        if ln.startswith("★ "):
            nm = ln[2:].split()[0]
            out.add(nm[len("_"):-len("_floors_spec.json")])
    return out


def main():
    from shapely.geometry import Polygon                    # noqa: E402
    cs = changed_specs()
    if cs is None:
        print("✗ 先跑 _probe_spec_census_diff.py 生成 %s" % DIFF_TXT)
        return 2

    rows = []
    for n in sorted(os.listdir(BUILDINGS)):
        base = os.path.join(BUILDINGS, n)
        fd = os.path.join(base, "floors")
        bk = os.path.join(base, ".orig", "floors.before_selfint")
        if not os.path.isdir(fd) or not os.path.isdir(bk):
            continue
        tot = inv = ch = 0
        for fn in sorted(f for f in os.listdir(fd)
                         if f.startswith("floor") and f.endswith(".json")):
            cur = json.load(io.open(os.path.join(fd, fn), encoding="utf-8"))
            pre_fp = os.path.join(bk, fn)
            pre = (json.load(io.open(pre_fp, encoding="utf-8"))
                   if os.path.isfile(pre_fp) else None)
            rs = cur.get("rooms") or []
            tot += len(rs)
            for r in rs:
                if not Polygon(r["poly"]).is_valid:
                    inv += 1
            if pre:
                for ra, rb in zip(rs, pre.get("rooms") or []):
                    if ra["poly"] != rb["poly"]:
                        ch += 1
        rows.append((n, tot, ch, inv, n in cs))

    print("=== 自交修复范围对账（19 栋有 .orig/floors.before_selfint 备份）===")
    print()
    print("| 栋 | rooms | 与备份比对 **poly 变了** | 现盘**仍非法** | spec 与改前 |")
    print("|---|---|---|---|---|")
    for n, tot, ch, inv, sc in rows:
        print("| %s | %d | %d | %d | %s |" % (n, tot, ch, inv, "**变了**" if sc else "逐字节相同"))
    print()
    print("合计 %d 栋；poly 变了 %d 间；现盘仍非法 %d 间；spec 变了 %d 栋"
          % (len(rows), sum(r[2] for r in rows), sum(r[3] for r in rows),
             sum(1 for r in rows if r[4])))
    print()
    ghost = [r[0] for r in rows if r[2] > 0 and not r[4]]
    weird = [r[0] for r in rows if r[2] == 0 and r[4]]
    print("changed>0 但 spec 相同（允许，逐栋列出）：%s" % (", ".join(ghost) or "无"))
    print("changed==0 但 spec 变了（**有鬼，必须查**）：%s" % (", ".join(weird) or "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
