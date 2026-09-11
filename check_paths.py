# -*- coding: utf-8 -*-
"""Phase 1 验收门禁：代码里不许有本机绝对路径、写死端口、写死回环地址。

为什么要有这个脚本
------------------
这套系统要从 Windows 开发机搬到 Linux 服务器。开发期留下的本机盘符、
`localhost:端口`、裸端口号之类字面量，在本机跑得好好的，一上服务器就是
`FileNotFoundError` 或连到自己的空端口 —— 而且往往要到部署当天才炸。

计划里这是 Phase 1 的唯一硬验收标准，且后续每个阶段都要复跑一遍防回归。
所以它做成可重复执行的脚本，而不是每次现敲带转义的 grep。

只查**代码**，不查注释
----------------------
`# 默认 8140 而不是 8130，因为……` 这类注释是应该存在的 —— 它解释了为什么
不那样写。把注释也算命中，门禁就会逼着人删掉最有价值的说明，然后被整体
忽略。所以：Python 用 `tokenize` 精确剥掉 `#` 注释；JS/TS/CSS/HTML 剥掉
`//` 与 `/* */`。**文档字符串保留检查** —— 老 control.py 的「运行：
http://127.0.0.1:8130」就写在 docstring 里，那是真实命中，该修。

用法
----
    python check_paths.py          # 退出码 0 = 通过，1 = 有未记录命中
"""
import io
import os
import re
import sys
import tokenize

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 被检查的目录/文件（相对仓库根）。只查**会跟着部署走**的代码。
TARGETS = ["backend", "frontend", "freeze_meta.py", "check_paths.py"]

#: 跳过：缓存、依赖、以及历史备份（备份是留档，不是运行代码）
SKIP_DIRS = {"__pycache__", "node_modules", "dist", ".git", "venv", ".venv"}
SKIP_SUFFIX = re.compile(r"\.(pyc|pyo|glb|png|jpg|jpeg|webp|dxf|dwg|zip|log)$")
SKIP_BACKUP = re.compile(r"\.(orig|before|bak)[^/\\]*$|\.bak$")

#: (规则名, 中文说明, 正则)
FORBIDDEN = [
    ("绝对路径", "Windows 盘符绝对路径",
     re.compile(r"[A-Za-z]:[\\/](?:gym3d|dxf_output|校庆)", re.I)),
    ("回环地址", "写死的回环地址 + 端口",
     re.compile(r"\b(?:localhost|127\.0\.0\.1):\d+")),
    ("裸端口", "裸端口字面量 8123/8130（过渡期老服务的端口）",
     re.compile(r"\b(?:8123|8130)\b")),
]

#: 本脚本自身会写满这些字面量（规则和说明里都得有），跳过不查。
SELF = os.path.abspath(__file__)

#: 已记录在案、经判断可以接受的例外：(相对路径, 规则名, 理由)。
#: 每一条都必须写清「为什么可以留」和「什么时候处理」，否则它就是噪音，
#: 而噪音会让门禁被整体忽略 —— 那比没有门禁更糟。
EXCEPTIONS = [
    ("backend/recognizer/profiles/lihua.py", "绝对路径",
     "理化楼图纸是仓外原始素材（校庆材料目录），本机专属、不进仓库；"
     "服务器 compute=0 永不读它。相对化要动已验证的基线楼，"
     "留到 Phase 5 与 profile.json 迁移一并做。"),
    ("backend/recognizer/profiles/j6.py", "绝对路径",
     "同上（六教图纸）。"),
]


def _strip_py_comments(source: str):
    """返回与 source 行数相同的行列表，Python 的 `#` 注释已被抹成空白。"""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None                      # 读不动就退化成「不剥注释」，宁可多报
    lines = source.splitlines()
    cut = {}                             # 行号(1-based) -> 该行注释起始列
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            cut[row] = min(cut.get(row, col), col)
    for row, col in cut.items():
        if 1 <= row <= len(lines):
            lines[row - 1] = lines[row - 1][:col]
    return lines


_C_STYLE = re.compile(r"//.*$|/\*.*?\*/")


def code_lines(path: str):
    """返回 (行号, 只含代码的文本) 序列。注释被剥掉，docstring 保留。"""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            source = fh.read()
    except OSError:
        return []

    if path.endswith(".py"):
        stripped = _strip_py_comments(source)
        if stripped is not None:
            return list(enumerate(stripped, 1))

    # 非 Python：逐行剥 // 与 /* */（够用即可，前端没有跨行 // 的场景）
    return [(i, _C_STYLE.sub("", line))
            for i, line in enumerate(source.splitlines(), 1)]


def iter_files():
    for target in TARGETS:
        path = os.path.join(ROOT, target)
        if os.path.isfile(path):
            yield path
            continue
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if SKIP_SUFFIX.search(name) or SKIP_BACKUP.search(name):
                    continue
                yield os.path.join(dirpath, name)


def _excused(rel: str, rule: str):
    """该 (文件, 规则) 组合是否是已记录例外？返回理由或 None。"""
    for exc_rel, exc_rule, reason in EXCEPTIONS:
        if rel == exc_rel and rule == exc_rule:
            return reason
    return None


def main():
    hits, excused = [], []
    scanned = 0
    for path in iter_files():
        if os.path.abspath(path) == SELF:
            continue
        scanned += 1
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for lineno, text in code_lines(path):
            for rule, label, pattern in FORBIDDEN:
                if not pattern.search(text):
                    continue
                reason = _excused(rel, rule)
                item = (rel, lineno, label, text.strip()[:100], reason)
                (excused if reason else hits).append(item)

    print("路径门禁：扫描 %d 个文件，%d 处命中（另有 %d 处已记录例外）"
          % (scanned, len(hits), len(excused)))

    if excused:
        print("\n已记录例外（不拦，但请确认理由仍然成立）：")
        for rel, lineno, label, text, reason in excused:
            print("  %s:%d  [%s]" % (rel, lineno, label))
            print("      理由: %s" % reason)

    if not hits:
        print("\n通过：没有未记录的本机绝对路径 / 写死端口 / 写死回环地址。")
        return 0

    print("\n未记录命中：")
    for rel, lineno, label, text, _ in hits:
        print("  %s:%d  [%s]\n      %s" % (rel, lineno, label, text))
    print("\n修法：路径走 backend/paths.py；端口/地址走 backend/api/settings.py（.env 是唯一出处）。")
    print("确实修不了的，在上面 EXCEPTIONS 里登记并写明理由与处理时机。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
