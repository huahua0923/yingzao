# -*- coding: utf-8 -*-
"""只读探针：把 `kb/gate.py` ⑪ 的**宽档**判据铺到**全仓的 .md** 上，量清洞有多大。

★ 为什么是探针而不是新判据：**判据只许有一份实现**。这里直接 import
  `kb.gate._cjk_quote_hits`，量的是**同一把尺子**；将来扩 ⑪ 的名单时，用的是这份数。

★ 探针本身不写盘、不改任何东西。输出按顶层目录分组 —— 因为「扩到哪一层」是个决定，
  要先看见分母长什么样再定。

用法：PYTHONIOENCODING=utf-8 python -u kb/cjk_md_scope_probe.py
退出码：0 量到了（无论有没有命中）/ 2 探针自己出错
"""
import collections
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kb.gate import _cjk_quote_hits                      # noqa: E402  ← 同一把尺子

#: 不进扫描的形状。`_scratch/` 是**已判退役**的暂存区（P3 要整体移出仓外），
#: 把它算进来只会让基线随迁移churn；`.orig/` 同理。这两处的命中另行记账。
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".orig", "_scratch", ".claude"}


def main() -> int:
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                files.append(os.path.join(dirpath, fn))
    files.sort()

    per_top = collections.Counter()          # 顶层目录 → 命中处数
    per_top_files = collections.Counter()    # 顶层目录 → 文件数
    per_file = collections.Counter()
    total_files = len(files)

    for p in files:
        rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
        top = rel.split("/")[0] if "/" in rel else "(仓库根)"
        try:
            text = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            print("✗ 读不了 %s：%s" % (rel, exc))
            return 2
        hits = _cjk_quote_hits(text, wide=True)
        per_top_files[top] += 1
        if hits:
            per_top[top] += len(hits)
            per_file[rel] = len(hits)

    print("== 全仓 .md 的宽档命中（尺子＝kb/gate.py: ⑪ 那一份）==")
    print("量过 .md 文件 %d 个（已排除 %s）" % (total_files, "、".join(sorted(SKIP_DIRS))))
    print()
    print("%-28s %8s %8s" % ("顶层", "文件数", "命中处"))
    for top in sorted(per_top_files, key=lambda t: (-per_top.get(t, 0), t)):
        print("%-28s %8d %8d" % (top, per_top_files[top], per_top.get(top, 0)))
    print("%-28s %8d %8d" % ("合计", total_files, sum(per_top.values())))
    print()
    if per_file:
        print("有命中的文件（%d 个）：" % len(per_file))
        for rel in sorted(per_file, key=lambda r: (-per_file[r], r)):
            print("  %6d  %s" % (per_file[rel], rel))
    else:
        # ★ 「没量到」与「干净」不许同形（本仓铁律 16）。分母已经打在上面了。
        print("有命中的文件：0 个（分母见上 —— 这是量过之后的 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
