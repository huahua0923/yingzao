# -*- coding: utf-8 -*-
r"""spec 普查「改前 vs 改后」逐栋 diff（**只读**）。

为什么要有这个：
  2026-09-13 修 535 间自交房间（19 栋 / 65 层）后，必须是「**只有修过的那几栋**的 spec 变了、
  没修的栋逐字节不变」，才能说这次改动**范围可控**。此前只对 lihua / ny27 两栋做过单点比对
  —— 两栋**不够**：lihua 根本不在本次修复名单里（`data/floors` 不在 `data/buildings` 下），
  所以它"不变"是**必然的、不提供信息**。全库逐栋比才是证据。

判据：
  ① `spec_pre/` 里有的每一项，与 `su_jobs/` 同名文件比 sha256；相同 ⇒ 逐字节不变。
  ② 不同的，深挖第一处差异路径（顶层键 / parts 下标 / 具体字段）——用来回答
     "spec 到底含不含房间几何"这个反复被误判的问题：**不猜，看路径。**

用法：
  python _scratch/_probe_spec_census_diff.py                # 全库逐栋
  python _scratch/_probe_spec_census_diff.py c006 ny27      # 只看指定栋（深挖差异）
"""
import hashlib
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
PRE = os.path.join(ROOT, "_scratch", "_qa_selfint", "spec_pre")
NOW = os.path.join(ROOT, "_scratch", "su_jobs")
MAX_PATHS = 12          # 每栋最多列几条差异路径


def sha(fp):
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def walk(a, b, path, out):
    """把 a/b 的第一处差异路径收进 out（最多 MAX_PATHS 条）。"""
    if len(out) >= MAX_PATHS:
        return
    if type(a) is not type(b):
        out.append("%s：类型 %s → %s" % (path, type(a).__name__, type(b).__name__))
        return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append("%s.%s：新增" % (path, k))
            elif k not in b:
                out.append("%s.%s：删除" % (path, k))
            else:
                walk(a[k], b[k], "%s.%s" % (path, k), out)
            if len(out) >= MAX_PATHS:
                return
        return
    if isinstance(a, list):
        if len(a) != len(b):
            out.append("%s：长度 %d → %d" % (path, len(a), len(b)))
        for i in range(min(len(a), len(b))):
            walk(a[i], b[i], "%s[%d]" % (path, i), out)
            if len(out) >= MAX_PATHS:
                return
        return
    if a != b:
        sa, sb = repr(a), repr(b)
        if len(sa) > 60:
            sa = sa[:60] + "…"
        if len(sb) > 60:
            sb = sb[:60] + "…"
        out.append("%s：%s → %s" % (path, sa, sb))


def main():
    want = set(sys.argv[1:])
    if not os.path.isdir(PRE):
        print("✗ 没有改前备份目录 %s" % PRE)
        return 2
    files = sorted(f for f in os.listdir(PRE) if f.endswith(".json"))
    if want:
        files = [f for f in files if any(w in f for w in want)]
    # ★ 改前**没有**、改后**有**的（新增）——不列出来就会得出"49/49 逐字节相同"这种
    #   看着干净、实际漏掉主角的结论。2026-09-13 判例：c103 改前没过闸门 ⇒ 没写盘 ⇒
    #   `spec_pre/` 里没有它；不列新增，c103 这次的 spec 变化就被静默跳过了。
    new = [] if want else sorted(f for f in os.listdir(NOW)
                                 if f.endswith(".json") and not os.path.isfile(os.path.join(PRE, f)))
    same = diff = miss = 0
    print("=== spec 普查 diff（改前 %s / 改后 %s）===" % (PRE, NOW))
    print()
    for f in new:
        print("＋ %-34s 改前**不存在**、改后新出（%d 字节）"
              % (f, os.path.getsize(os.path.join(NOW, f))))
    if new:
        print()
    for f in files:
        fa = os.path.join(PRE, f)
        fb = os.path.join(NOW, f)
        if not os.path.isfile(fb):
            print("✗ %-34s 改后**不存在**（本次没重跑？）" % f)
            miss += 1
            continue
        sa, sb = sha(fa), sha(fb)
        if sa == sb:
            same += 1
            continue
        diff += 1
        print("★ %-34s %s\n   %s" % (f, sa[:12], sb[:12]))
        try:
            A = json.load(io.open(fa, encoding="utf-8"))
            B = json.load(io.open(fb, encoding="utf-8"))
        except Exception as e:                                   # noqa: BLE001
            print("   （解析失败，只看 sha：%s）" % e)
            print()
            continue
        out = []
        walk(A, B, "", out)
        for p in out[:MAX_PATHS]:
            print("     %s" % (p or "(根)"))
        print()
    print("合计：逐字节相同 %d / **不同 %d** / 改后缺失 %d / **新增 %d**（改前 %d 份）"
          % (same, diff, miss, len(new), len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
