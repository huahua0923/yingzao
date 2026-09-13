# -*- coding: utf-8 -*-
r"""c104 I3（房溢楼板）改前/改后 A/B（**只读，不碰 data/**）。

为什么要有这个：
  2026-09-13 修全库房间多边形自交（`_fix_self_intersections.py`，19 栋 535 间）后，
  `qa_structural.py` 报 **c104 FAIL 3**（3 个 ERROR 全是 I3、全在 f4）。c104 的 20 个房间
  多边形**被改过** ⇒ 必须先排除是本次改动造成的回归，才能说"数据修复零回归"。

做法（零风险）：`qa_structural.check_building` 内部只经 `load_floors(name)` 取数，
把它猴补丁成"从 `.orig/floors.before_selfint/` 读"，就得到**改前**的 I3 结果，
与现盘（改后）逐条比对。**一个文件都不动。**

判据：改前/改后的 ERROR / WARN 条数与位置**逐条相同** ⇒ 与本次改动无关（是既存病）。
用法：python _scratch/_probe_c104_i3_ab.py [栋名，默认 c104]
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
sys.path.insert(0, ROOT)
import qa_structural as Q        # noqa: E402


def make_before_loader(name, bk_dir):
    def load_before(_name):
        out = []
        for i in range(64):
            f = os.path.join(bk_dir, "floor%d.json" % i)
            if not os.path.isfile(f):
                break
            try:
                g = json.load(io.open(f, encoding="utf-8"))
            except Exception:                                    # noqa: BLE001
                continue
            if g.get("outline"):
                out.append(g)
        return out
    return load_before


def run(loader, name):
    Q.load_floors = loader
    floors, fs = Q.check_building(name, False)
    return floors, fs


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "c104"
    bk = os.path.join(ROOT, "data", "buildings", name, ".orig", "floors.before_selfint")
    if not os.path.isdir(bk):
        print("✗ %s 没有 .orig/floors.before_selfint/，无法做 A/B" % name)
        return 2
    orig_loader = Q.load_floors
    floors_a, fs_a = run(orig_loader, name)                        # 改后（现盘）
    floors_b, fs_b = run(make_before_loader(name, bk), name)       # 改前（备份）

    def tally(fs):
        e = [f for f in fs if f.severity == "ERROR"]
        w = [f for f in fs if f.severity == "WARN"]
        return e, w

    ea, wa = tally(fs_a)
    eb, wb = tally(fs_b)
    print("=== %s I3/全体 A/B ===" % name)
    print("  改后（现盘）：房 %d 间 / ERROR %d / WARN %d" %
          (sum(len(f.get("rooms") or []) for f in floors_a), len(ea), len(wa)))
    print("  改前（备份）：房 %d 间 / ERROR %d / WARN %d" %
          (sum(len(f.get("rooms") or []) for f in floors_b), len(eb), len(wb)))
    print()
    sa = set(x.line() for x in ea)
    sb = set(x.line() for x in eb)
    only_a = sorted(sa - sb)
    only_b = sorted(sb - sa)
    print("  ERROR 集合差：仅改后有 %d 条 / 仅改前有 %d 条" % (len(only_a), len(only_b)))
    for x in only_a:
        print("     仅改后有：%s" % x)
    for x in only_b:
        print("     仅改前有：%s" % x)
    if not only_a and not only_b:
        print("  ⇒ ERROR **逐条相同**：c104 的 FAIL 与本次自交修复**无关**（既存病，见 memory\n"
              "     `c104-f4-rooms-displaced-stale.md`：F4 十六间 = F3 同名整体 +2.11 m）")
    else:
        print("  ⚠️ ERROR 集合有差异 ⇒ 可能是本次改动引入的，需人工看")
    print()
    print("  改后 ERROR 明细：")
    for x in ea:
        print("     %s" % x.line())
    return 1 if only_a else 0


if __name__ == "__main__":
    sys.exit(main())
