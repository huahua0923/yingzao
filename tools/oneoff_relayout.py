# -*- coding: utf-8 -*-
"""一次性目录重构（2026-10-20）：把根目录散落的过程目录收进 `过程/`。

用法：
  python -I -X utf8 tools/oneoff_relayout.py plan     # 只列将改的行，不动
  python -I -X utf8 tools/oneoff_relayout.py apply    # 移动目录 + 改引用
  python -I -X utf8 tools/oneoff_relayout.py verify   # 查残留引用 + 目录位置

★ 只认**路径分段**：`_out` 前面必须是 / \\ " ' 空白 ( , = 或行首，后面同理。
  所以 `polys_out`、`run_chain_bid`、`cut_out` 一律不动。
★ 显式排除前面是 `gates/` 或 `rebuild/` 的：那是**它们目录里的**同名子目录，
  不是根目录这一份。
"""
import argparse
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = "过程"
# `a1` / `chain` 这两个名字太像普通词：`a1` 是变量名、`chain` 是英文单词。
# 它们只认**引号或斜杠夹住**的写法，其余一律不当路径。
NAMES = ["_out", "_work", "_gen", "_clean", "_flatten", "_repair",
         "_scratch", "_layers"]
TIGHT = ["a1", "chain"]

# 只改活代码；_scratch 里的一次性探针不碰（它们跟着目录一起搬走）
SCAN_DIRS = ["pipeline", "gates", "tools", "workbench", "demo", "rebuild/tools"]
EXT = (".py", ".js", ".mjs", ".html")
# 前面是这些的，不是根目录这一份：gates/ 与 rebuild/ 各有自己的同名子目录；
# gym3d 是**另一个仓**的路径，只读引用不搬。
SKIP_PRE = ("gates/", "rebuild/", "demo/", "gym3d", "gym3d/", "gym3d\\")
# 这两份是**生成给人读的说明页**，里面的 `_out/` 常是散文（「源码里点到的 _out/ 名字」），
# 不是可执行路径；改了只会把话改歪。
SKIP_FILES = ("demo/sys.html", "tools/build_sys_page.py")
SELF = "oneoff_relayout.py"

PRE = r"""(?:^|[\\/"'\s(,=])"""
# 后面只认斜杠或引号：`_out = ...`、`_out > 1`、`_out)` 都是变量，不是目录。
POST = r"""(?=[\\/"'])"""
PAT = re.compile(
    r"(?P<pre>" + PRE + r")(?P<name>" + "|".join(map(re.escape, NAMES)) + r")"
    + POST, re.M)
PAT_TIGHT = re.compile(
    r"""(?P<pre>[\\/"'])(?P<name>""" + "|".join(map(re.escape, TIGHT))
    + r""")(?=[\\/"'])""")


def target_files():
    out = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        for b, _ds, fs in os.walk(base):
            parts = b.replace("\\", "/").split("/")
            if "_scratch" in parts or "vendor" in parts:
                continue
            for f in fs:
                if f.endswith(EXT) and not f.startswith("lint_") and f != SELF:
                    out.append(os.path.join(b, f))
    for f in os.listdir(ROOT):
        if f.endswith(".py"):
            out.append(os.path.join(ROOT, f))
    keep = []
    for p in sorted(set(out)):
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        if rel not in SKIP_FILES:
            keep.append(p)
    return keep


# `os.path.join(<这些>(, …)*, "名字")` 才是**根目录**那份。
ROOT_ANCHOR = re.compile(r"os\.path\.join\(\s*(ROOT|CDUT|REPO|BASE)\b")
# 名称前面紧挨着的父段：`"gates", "_out"` / `"rebuild", "_work"` / `"a1", "_out"`
PARENT_SEG = re.compile(
    r"""["'](?:过程/)?(gates|rebuild|demo|gym3d|a1|chain|tools|pipeline)["']\s*,\s*$""")
# 这行是**路径语境**：join / sys.path / spec_from_file_location / open / Path。
# 没有它、后面又不带斜杠的字面量（`("_archive", "_scratch", …)` 这种名单）不算路径。
PATHISH = re.compile(r"os\.path\.join|sys\.path|spec_from_file_location|open\(|Path\(")
ANCHORS = ("ROOT", "CDUT", "REPO", "BASE")


def _def_rhs(text, var):
    m = re.search(r"^\s*%s\s*=\s*([^\n#]+)" % re.escape(var), text, re.M)
    return m.group(1) if m else None


def _hops(text, var, seen=()):
    """`var` 从**本文件**往上跳了几层 dirname()；解析不出来 → None。"""
    if var in seen:
        return None
    rhs = _def_rhs(text, var)
    if rhs is None:
        return None
    if "__file__" in rhs or re.search(r"[A-Za-z]:[\\/]", rhs):
        return rhs.count("dirname(")
    n = rhs.count("dirname(")
    # `ROOT = os.path.dirname(HERE)`：把 HERE 那一截的层数加进来。
    for other in ANCHORS + ("HERE", "ROOTDIR", "PROJ"):
        if other != var and re.search(r"\b%s\b" % re.escape(other), rhs):
            sub = _hops(text, other, seen + (var,))
            if sub is not None:
                return n + sub
    return None


def anchor_is_root(text, fpath, var):
    """锚变量是不是**项目根**。`rebuild/tools/x.py` 里 `ROOT = dirname(HERE)` 是
    `rebuild/`，不是根 —— 不核这一步，`os.path.join(ROOT, "_work")` 就会被搬到
    `过程/_work`，而它在 `rebuild/_work`（两个同名目录，铁律 192）。"""
    rhs = _def_rhs(text, var)
    if rhs is not None:
        lit = re.match(r"""^[rRuU]?["'](.*)["']\s*$""", rhs.strip())
        if lit:
            # 直接写死的绝对路：等于本项目根才算（`ROOT = r"D:\项目\cdut3d"` 是根，
            # `r"C:\Users\Administrator\_scratch"` 不是）。
            val = os.path.normcase(os.path.normpath(lit.group(1)))
            return val == os.path.normcase(os.path.normpath(ROOT))
    hops = _hops(text, var)
    if hops is None or fpath is None:
        return True
    depth = len([x for x in os.path.dirname(
        os.path.relpath(fpath, ROOT)).split(os.sep) if x])
    return hops >= depth + 1


def hits(text, fpath=None):
    """返回 (新文本, 命中列表)。命中 = (行号, 原名, 原行)。

    ★ 判据只看**本行**：往回切定长字符会跨到上一行，`HERE)`、另一条 join 的尾巴
      都会让下一行被误判（`os.path.join(CDUT, "a1")` 就是这样被整批跳过的）。
    """
    found = []

    def replay(m):
        start = m.start()
        # m.start() 落在 pre 的那个分隔符上（`/`、引号、空白…），
        # 所以要把它也算进来，否则 `gates/_out` 的前缀只剩 `gates`，排除失效。
        prev = text[max(0, start - 24):start + 1]
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", start)
        if line_end < 0:
            line_end = len(text)
        head = text[line_start:start]
        line = text[line_start:line_end].strip()
        name = m.group("name")

        if any(prev.endswith(p) for p in SKIP_PRE):
            return m.group(0)
        # 跨仓（gym3d）的路径只读不搬：整行带这个字样的，一个都不改。
        if "gym3d" in line:
            return m.group(0)
        # 不是**第一段**就不改：根目录那份永远写在路径开头。`../` / `./` 起始的除外。
        if (prev.endswith("/") or prev.endswith("\\")) and not (
                prev.endswith("../") or prev.endswith("./")):
            return m.group(0)
        # 锚在**本文件所在目录**：`os.path.join(os.path.dirname(__file__), "_out")` 是 gates/_out。
        if "__file__" in head:
            return m.group(0)
        # 绝对盘符路径（`r"C:\Users\...\_scratch"`）与根目录无关。
        if re.search(r"[A-Za-z]:[\\/]", head):
            return m.group(0)
        # `os.sep + "_out"` 是**通用分段判断**，不是指向根目录那一个。
        if re.search(r"os\.sep\s*\+\s*$", head):
            return m.group(0)
        # 父段是 gates/rebuild/demo/a1… ⇒ 那是它自己那个同名子目录。
        if PARENT_SEG.search(head):
            return m.group(0)
        # `os.path.join(<锚>, …)`：锚还得**真是项目根**（见 anchor_is_root）。
        jo = ROOT_ANCHOR.search(head)
        if "os.path.join(" in head:
            if not jo or not anchor_is_root(text, fpath, jo.group(1)):
                return m.group(0)
        # `./_gen/…` 是同级目录（`../_layers` 才是根目录那份，不在此列）。
        if prev.endswith("./") and not prev.endswith("../"):
            return m.group(0)
        # 名字得带斜杠往后走（`a1/gauge.py`），或整行是路径语境（join/sys.path）；
        # 否则 `("_archive", "_scratch", …)` 这种**分段名单**、`['a0','a1','a2']` 键名也会被改。
        after = text[m.end():m.end() + 1]
        if after not in ("/", "\\") and not PATHISH.search(head):
            return m.group(0)
        found.append((text.count("\n", 0, start) + 1, name, line[:110]))
        return m.group("pre") + DEST + "/" + name

    new = PAT.sub(replay, text)
    new = PAT_TIGHT.sub(replay, new)
    return new, found


def cmd_plan():
    total = 0
    per = {}
    for p in target_files():
        with open(p, encoding="utf-8", errors="replace") as f:
            t = f.read()
        _new, fnd = hits(t, p)
        if fnd:
            total += len(fnd)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            per[rel] = len(fnd)
    for k in sorted(per, key=lambda x: -per[x]):
        print("%4d  %s" % (per[k], k))
    print("合计 %d 处，%d 个文件" % (total, len(per)))
    for n in NAMES:
        p = os.path.join(ROOT, n)
        print("  %-10s %s" % (n, "在" if os.path.isdir(p) else "不在"))
    return 0


def cmd_apply():
    os.makedirs(os.path.join(ROOT, DEST), exist_ok=True)
    for n in NAMES:
        src = os.path.join(ROOT, n)
        dst = os.path.join(ROOT, DEST, n)
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.move(src, dst)
            print("搬", n)
        elif os.path.isdir(dst):
            print("已在", dst)
    nf = 0
    for p in target_files():
        with open(p, encoding="utf-8", errors="replace") as f:
            t = f.read()
        new, fnd = hits(t, p)
        if fnd and new != t:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            nf += 1
            print("改 %s（%d 处）" % (os.path.relpath(p, ROOT), len(fnd)))
    print("改动文件 %d 个" % nf)
    return 0


def cmd_verify():
    left = []
    for p in target_files():
        with open(p, encoding="utf-8", errors="replace") as f:
            t = f.read()
        _new, fnd = hits(t, p)
        if fnd:
            left.append((os.path.relpath(p, ROOT), len(fnd)))
    print("残留引用文件 %d 个" % len(left))
    for k, v in left[:20]:
        print("  %4d  %s" % (v, k))
    bad = []
    for n in NAMES:
        old = os.path.isdir(os.path.join(ROOT, n))
        new = os.path.isdir(os.path.join(ROOT, DEST, n))
        if old or not new:
            bad.append(n)
        print("  %-10s 新位置%s 旧位置%s" % (n, "有" if new else "无",
                                          "还在" if old else "已清"))
    print("结论：%s" % ("通过" if not left and not bad else "未通过"))
    return 0 if (not left and not bad) else 3


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["plan", "apply", "verify"])
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "apply": cmd_apply, "verify": cmd_verify}[a.mode]()


if __name__ == "__main__":
    sys.exit(main())
