# -*- coding: utf-8 -*-
"""临时探针：根 README 的行锚点指向哪一行、那一行现在是什么。

用法：从**仓库根**跑（下面用的是相对路径 `kb/kb.json`、`README.md`）：
    python -u _scratch/_readme_anchor_probe.py

为什么写成文件而不是 `python -c "…"`：`-c` 里的 `\\d` 经 Git Bash 传一层会被吃掉，
正则于是匹配不到东西、**退回空输出** —— 而空输出和「没有锚点」长得一模一样
（铁律 16）。这个探针本身就是为了不靠 shell 传正则。
"""
import io
import re

txt = io.open("kb/kb.json", encoding="utf-8").read()
root = io.open("README.md", encoding="utf-8").read().splitlines()

# 锚点在 kb.json 里是以 `"README.md:151"` 这种**字符串**出现的，先找出每个上下文
for m in sorted(set(re.findall(r"README\.md:(\d+)", txt)), key=int):
    n = int(m)
    cur = root[n - 1].strip()[:70] if n <= len(root) else "<越界>"
    print("README.md:%-4s 现在指的是 | %s" % (n, cur))

# 每个锚点是被谁引用的（前后各取 120 字符看归属）
print("\n--- 归属 ---")
for m in re.finditer(r'"[^"]*README\.md:(\d+)[^"]*"', txt):
    a, b = max(0, m.start() - 150), m.end() + 30
    print("…%s…\n" % txt[a:b].replace("\n", " "))
