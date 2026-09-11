# -*- coding: utf-8 -*-
r"""给 pre-commit 钩子的密钥扫描**排除表**补误报项（仓库内副本 + 全局模板各一份）。

钩子的正则会把「口令的来源是变量/环境变量」这类**不含字面量**的行当成疑似密钥。
下面这些例子写成 `#` 注释而不是文档字符串 —— 钩子本来就排除注释行（注释是
说明，不是代码），写成 docstring 反而会被自己的扫描器拦下。

# 第一批（值来自环境变量 / 原样透传）：
#     password = os.environ.get("LIHUA_DB_PASSWORD")
#     password=pwd,
# 第二批（pydantic 声明默认空 / 从对象取值）：
#     db_password: str = Field("", validation_alias="LIHUA_DB_PASSWORD")
#     dbname=..., password=self.db_password,

而钩子自己给出的建议恰恰是「请用环境变量替代」—— 自相矛盾。

**只放宽这些**：真正的字面量照旧被拦 —— 自测里这两行必须仍然命中：
#     DB_PASSWORD = <一个字面量>
#     db_password: str = Field(<一个字面量>)

第二批的边界是「默认值恰好是空串」而不是「默认值是任意函数调用」：
一开始写成 `\w+\(`，自测发现它会把「Field 里塞了字面量」也整行放过 ——
那正是最该拦的形状。收紧成 `\w+\(""` 后只放过空默认值。
（POSIX ERE 不支持 `(?:…)` 非捕获组，所以直接用普通分组或字面量。）

换行必须保持 LF：钩子是 #!/bin/bash，CRLF 会让 Linux 报 bad interpreter。
所以用 newline="" 原样读写，并在写入前显式拒绝 CRLF。
"""
import sys
from pathlib import Path

# (锚点, 要追加的排除项) —— 按批次顺序追加，已存在则跳过，可重复执行
BATCHES = [
    (
        "|typeof password|typeof.*===.*string",
        "|os\\.environ|os\\.getenv|password\\s*[=:]\\s*password",
    ),
    (
        "|os\\.environ|os\\.getenv|password\\s*[=:]\\s*password",
        '|password\\s*:\\s*\\w+\\s*=\\s*\\w+\\(""|password\\s*[=:]\\s*(self|cls)\\.',
    ),
]

#: 早期版本的过宽排除项 → 收紧后的写法。已是过宽版本的钩子会被就地收紧。
TOO_BROAD = {
    "|password\\s*:\\s*\\w+\\s*=\\s*\\w+\\(|password\\s*[=:]\\s*(self|cls)\\.":
        '|password\\s*:\\s*\\w+\\s*=\\s*\\w+\\(""|password\\s*[=:]\\s*(self|cls)\\.',
}

TARGETS = [
    Path(r"D:\gym3d\.git\hooks\pre-commit"),
    Path.home() / ".git-templates" / "hooks" / "pre-commit",
]


def patch(path):
    if not path.exists():
        return [f"跳过（不存在）：{path}"]
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    if "\r\n" in text:
        return [f"!! 检测到 CRLF，拒绝改动（会弄坏 bash 脚本）：{path}"]

    notes = []
    for broad, tight in TOO_BROAD.items():
        if broad in text:
            text = text.replace(broad, tight, 1)
            notes.append("  已收紧过宽排除项")

    for anchor, addition in BATCHES:
        if addition in text:
            notes.append(f"  已是补丁后状态（跳过）")
            continue
        if anchor not in text:
            notes.append(f"!! 找不到锚点，本批未改动: {addition[:40]}…")
            continue
        text = text.replace(anchor, anchor + addition, 1)
        notes.append(f"  已追加排除项: {addition[:40]}…")

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return [f"补丁 {path}"] + notes


for t in TARGETS:
    for line in patch(t):
        print(line)

sys.exit(0)
