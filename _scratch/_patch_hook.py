# -*- coding: utf-8 -*-
"""给 pre-commit 钩子的密钥扫描**排除表**补三类误报（仓库内副本 + 全局模板各一份）。

背景：钩子的正则会把「从环境变量读口令」这一行当成疑似密钥：

    password = os.environ.get("LIHUA_DB_PASSWORD")     ← 值来自环境变量，不是字面量
    password=pwd,

而钩子自己给出的建议恰恰是「请用环境变量替代」—— 自相矛盾。补充的排除项：

    os[.]environ      Python 读环境变量（钩子已排除 JS 的 process.env.，缺 Python 对应项）
    os[.]getenv       Python 的另一种读法
    password[=:]password   把变量原样传下去的透传写法，不可能含字面量

**只放宽这三类**：字面量（password="hunter2"）照旧被拦。

换行必须保持 LF：钩子是 #!/bin/bash，CRLF 会让 Linux/每次执行报 bad interpreter。
所以这里用 newline="" 原样读写，不做任何转换。
"""
import sys
from pathlib import Path

MARKER = "|os\\.environ|os\\.getenv|password\\s*[=:]\\s*password"
ANCHOR = "|typeof password|typeof.*===.*string"

TARGETS = [
    Path(r"D:\gym3d\.git\hooks\pre-commit"),
    Path.home() / ".git-templates" / "hooks" / "pre-commit",
]


def patch(path):
    if not path.exists():
        return f"跳过（不存在）：{path}"
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    if MARKER in text:
        return f"已是补丁后状态：{path}"
    if ANCHOR not in text:
        return f"!! 找不到锚点，未改动：{path}"
    if "\r\n" in text:
        return f"!! 检测到 CRLF，拒绝改动（会弄坏 bash 脚本）：{path}"
    text = text.replace(ANCHOR, ANCHOR + MARKER, 1)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return f"已补丁：{path}"


for t in TARGETS:
    print(patch(t))

sys.exit(0)
