# -*- coding: utf-8 -*-
r"""「已入库的 .py」import 了「存在但没入库的本地模块」—— 全仓扫一遍（只读）。

为什么需要它
------------
同一个病在本仓已经犯过**三次**，每次都是"看着齐全、一 clone 就缺件"：
  ① `backend/recognizer/` 有 4 个模块从没入库（98880dd 修）
  ② `frontend/site/` 只入库了一半，html 引用不存在的 js（9649a65 修）
  ③ `backend/checks/` 整个包没入库 + `backend/api/` 16 个文件只入库 3 个（本次）
前两次都是**碰巧人工发现**的。人工发现不是判据 —— 判据是"把 import 图展开，
逐个问它在不在版本库里"。本脚本就干这一件事。

它查什么、不查什么
------------------
  查：`import X` / `from X import ...` 里，X（或 X 的前缀）能解析成本仓的一个
      **磁盘上存在的 .py**，而那个文件 **git 不跟踪** ⇒ 报「缺件」。
  不查：第三方库（不落在本仓路径上）、`_scratch/` 里自己写的一次性探针
      （那本来就故意不入库，见 algorithm-overview 的归档约定）。

只报文字，不改任何东西。退出码：有缺件 = 1，没有 = 0（给门禁用）。
用法：python backend/checks/_import_graph_gap.py
      python backend/checks/_import_graph_gap.py --selftest

★ 2026-09-24：本文件由 `_scratch/` 收编进 `backend/checks/`（门禁归门禁）。
  收编时改了一处 —— `ROOT` 少算了一层：原来在 `_scratch/` 下是 `parents[1] = 仓库根`，
  搬深一层后 `parents[1]` 变成 `backend/`，**不报错，只是把 `backend/` 当仓库根**，
  于是 `git ls-files` 在错的目录里跑、扫出 0 个文件还照样打 ✓。
  ⇒ 凡「从 `__file__` 反推仓库根」的脚本，搬位置都要重数层数并**重跑一遍**看数变没变。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# 本仓的模块根：**不再手维护白名单**。
#
# ★ 这里原来写的是一个 PKG_ROOTS 元组（backend/recognizer/…）。第一版跑出来是
#   "✓ 没有缺件" —— 而它当时正漏着 `import _render_common as RC`（被已入库的
#   `_dxf_png_batch.py` 引用、模块本身没入库）：`_render_common` 不在那个元组里，
#   **待检对象被量程滤掉了**，于是给出了一个漂亮的绿灯。
#   这正是本仓记过的那类假绿（memory: vacuous-test-assertions「量程滤掉待检对象」）。
#   手维护的名单必然不全 ⇒ 必然假绿 ⇒ 绿灯被学会忽略（同 A8 那条注释里的道理）。
#   改成：把仓内所有 .py 反建成「模块名 → 文件」的索引，谁来问都能查到。
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "data",
              "_scratch", ".claude"}
_NON_MODULE = {"setup", "conftest"}

IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))")

#: ★★ 2026-09-24 修：**相对 import 整类看不见**（本脚本第四次栽在同一个病上）。
#:
#: 原判据是「按行正则 `from X import` / `import X`」，于是：
#:   ① `from . import system as system_mod` 这条线**根本匹配不上** ——
#:      正则那段是 `[A-Za-z_][\w.]*`，点号不在里面，`from .` 当场断在这里；
#:   ② 底下那句 `if mod.startswith("."): continue  # 相对 import：本仓文件必同在库里`
#:      因此是**死代码**，而且它的前提是反的 —— `from . import system` 里的
#:      `system.py` 恰恰是**最容易没入库**的那个（新加的模块，同包其它文件早入了库）。
#: 实测后果（就在写这段的时候）：`backend/checks/__init__.py:292` 是**已入库**文件，
#: 它 `from . import system as system_mod`，而 `backend/checks/system.py` **没入库** ——
#: 本脚本照报「✓ 没有缺件」。**它漏掉的正好是它被造出来要抓的那一类。**
#: ⇒ 换掉按行正则，改**解析 AST**：相对/多行/括号换行/别名 一并解决
#:   （memory: substring-count-is-not-code-fact —— 判代码事实要解析，不要数文本）。
#: ⇒ 并且**解析不了的文件要出声**：安静跳过 = 「没量过」长得像「没问题」。


def local_modules() -> dict[str, str]:
    """仓内所有 .py 反建成 模块名 → 路径。

    `backend/foo/bar.py` 同时登记为 `backend.foo.bar` 和 `foo.bar`
    （跑脚本时 backend/ 常在 sys.path 上，两种写法都合法）；
    仓根的 `baz.py` 登记为 `baz`。
    """
    idx: dict[str, str] = {}
    for p in Path(".").rglob("*.py"):
        parts = p.parts
        if any(seg in _SKIP_DIRS for seg in parts):
            continue
        rel = str(p).replace("\\", "/")
        stem = rel[:-3].replace("/", ".")
        if stem.split(".")[-1] in _NON_MODULE:
            continue
        idx.setdefault(stem, rel)
        if rel.startswith("backend/"):
            idx.setdefault(stem[len("backend."):], rel)
        elif "/" not in rel:
            idx.setdefault(stem, rel)
    return idx


def tracked() -> set[str]:
    # ★ 用 bytes 接、显式按 utf-8 解。Windows 上 `text=True` 走 locale(GBK)，
    #   仓里有中文文件名就会 UnicodeDecodeError 崩在**读文件名**这一步
    #   （屏幕上是 threading 的报错，指不到真正的原因）。git 里文件名是 UTF-8。
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True)
    return {s for s in out.stdout.decode("utf-8", errors="replace").split("\0") if s}


def resolve(mod: str, idx: dict[str, str]) -> str | None:
    """模块名 → 本仓磁盘文件路径；解析不到本仓文件就回 None（= 第三方或不存在）。

    `import a.b.c` 逐级缩短去查（`a.b.c` → `a.b` → `a`），因为包的 __init__ 也算。
    """
    parts = mod.split(".")
    for k in range(len(parts), 0, -1):
        hit = idx.get(".".join(parts[:k]))
        if hit:
            return hit
    return None


def _pkg_dir(rel: str, level: int) -> str | None:
    """相对 import（`from . import x`，level 个点）的基目录。

    `backend/checks/__init__.py` + level 1 → `backend/checks`
    level 2 → `backend`；仓根散脚本（没有包）→ None（相对 import 本就不合法）。
    """
    if rel.endswith("/__init__.py"):
        d = rel[: -len("/__init__.py")]
    elif "/" in rel:
        d = rel.rsplit("/", 1)[0]
    else:
        return None
    for _ in range(max(0, level - 1)):
        if "/" not in d:
            return None
        d = d.rsplit("/", 1)[0]
    return d


def _cand_files(base: str, dotted: str) -> list[str]:
    """`base/dotted` 可能的落盘形态：`base/a/b.py` 或 `base/a/b/__init__.py`。"""
    p = "/".join(x for x in (base, dotted.replace(".", "/") if dotted else "") if x)
    return [p + ".py", p + "/__init__.py"]


def scan_imports(rel: str, text: str) -> tuple[list[str], list[str]]:
    """一份源码里的 import 目标：`(本仓模块名/路径, 解析不动的说明)`。

    绝对写法返回**模块名**（交给 `resolve` 走索引）；相对写法返回**已定位的文件
    路径候选**（前面带 `=`，调用方直接查盘），因为相对 import 的正确解释依赖
    引用者自己所在的包，索引里没有这个上下文。
    """
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as ex:
        return [], ["%s: %s" % (rel, ex.__class__.__name__)]
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            lvl = getattr(node, "level", 0) or 0
            mod = node.module or ""
            if not lvl:
                if mod:
                    out.append(mod)
                continue
            base = _pkg_dir(rel, lvl)
            if base is None:
                continue
            if mod:
                out.extend("=" + c for c in _cand_files(base, mod))
            for a in node.names:
                if a.name == "*":
                    continue
                sub = (mod + "." + a.name) if mod else a.name
                out.extend("=" + c for c in _cand_files(base, sub))
    return out, []


def main() -> int:
    tr = tracked()
    idx = local_modules()
    srcs = sorted(p for p in tr if p.endswith(".py") and not p.startswith("_scratch/"))
    print("扫描已入库的 .py：%d 个；仓内可解析模块名：%d 个" % (len(srcs), len(idx)))

    gaps: dict[str, set[str]] = {}
    bad: list[str] = []
    gone: list[str] = []
    n_imp = n_local = 0
    for f in srcs:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError as ex:
            # ★ 两种「量不到」要分开写，否则屏幕上分不清是哪种（用户会以为是自己写错了）：
            #   · 磁盘上根本没有 = git 里记着、这次改动删了还没提交（`D` 状态）
            #   · 有文件但读不了 = 真·异常
            if Path(f).exists():
                bad.append("%s: %s" % (f, ex.__class__.__name__))
            else:
                gone.append(f)
            continue
        targets, parse_bad = scan_imports(f, text)
        bad.extend(parse_bad)
        for mod in targets:
            n_imp += 1
            if mod.startswith("="):                  # 相对 import：路径已定位
                hit = next((c for c in (mod[1:],) if Path(c).is_file()), None)
            else:
                hit = resolve(mod, idx)
            if hit is None:                          # 第三方 / 不存在 —— 不是本脚本的事
                continue
            n_local += 1
            if hit not in tr:
                gaps.setdefault(hit, set()).add(f)

    print("import 总数 %d 条，其中解析到仓内文件的 %d 条" % (n_imp, n_local))
    if gone:
        print("⚠ git 里有、磁盘上已不在的 .py：%d 份（改了没提交的删除）—— "
              "它们的 import 不计入：%s"
              % (len(gone), "、".join(sorted(gone)[:4])))
        if len(gone) > 4:
            print("     …另有 %d 份" % (len(gone) - 4))
    if bad:
        # ★ 「没量过」不许长得像「没问题」：解析不了的文件要自己报出来。
        print("⚠ 有 %d 份文件没量到（解析失败/读不了）—— 它们的 import 不计入上面的数："
              % len(bad))
        for b in bad[:8]:
            print("     %s" % b)
        if len(bad) > 8:
            print("     …另有 %d 份" % (len(bad) - 8))
    if not gaps:
        print("✓ 没有「已入库文件 import 未入库模块」的缺件")
        # ★ 有量不到的文件时**不许报 ✓ 也不许退 0** —— 「没量过」与「没问题」
        #   在屏幕上长得一样，而这是本脚本第一版栽过的那个坑（假绿）。
        return 1 if (bad or gone) else 0
    print("✗ 有 %d 个模块：磁盘上有、git 不跟踪，却被已入库的文件 import" % len(gaps))
    for hit in sorted(gaps):
        who = sorted(gaps[hit])
        print("   %s" % hit)
        for w in who[:6]:
            print("       ← %s" % w)
        if len(who) > 6:
            print("       ← …另有 %d 处" % (len(who) - 6))
    return 1


def selftest() -> int:
    """刑具：证明 `scan_imports` **会**认出相对 import —— 而不是只会在屏幕上写 ✓。

    ★ 这四条对应的是真缺陷的四种形态，少一条都放跑过一类：
      ① 相对 import 的正体（就是当初整类看不见的那种）；
      ② 相对 import 带模块名（`from .findings import X`）；
      ③ 多行括号 import（按行正则时代的漏网形态）；
      ④ 仓根散脚本里的相对 import —— **不许**造出假阳性（它本就不合法）。
    ★ 缺一份**阳性对照**的刑具只证明"改坏会红"，不证明"真错在时会有反应"；
      这里 ① 就是阳性对照：它必须**认出**那条目标。
    """
    cases = [
        ("① from . import system（当初整类看不见）",
         "backend/checks/__init__.py", "from . import system as m\n",
         "=backend/checks/system.py"),
        ("② from .findings import Report",
         "backend/checks/__init__.py", "from .findings import Report\n",
         "=backend/checks/findings.py"),
        ("③ 多行括号 import（按行正则漏网）",
         "backend/checks/x.py", "from . import (\n    alpha,\n    beta,\n)\n",
         "=backend/checks/beta.py"),
        ("④ from ..state import roster（上跳一级）",
         "backend/checks/x.py", "from ..state import roster\n",
         "=backend/state/roster.py"),
    ]
    ok = True
    for title, rel, src, want in cases:
        got, _bad = scan_imports(rel, src)
        hit = want in got
        # ★ 这一句必须先在括号里拼好再进 `%`。写成
        #   `"认出 %s" if hit else "没认出 %s（%r）" % (want, got)` 时，
        #   `%` 比条件表达式结合得紧 ⇒ **真分支那条根本没被格式化**，
        #   屏幕上印出字面量 `认出了 %s`，而四个用例**全报 OK** ——
        #   断言在报假话（同族：template-string-prints-undefined）。
        note = ("认出了 %s" % want) if hit else ("**没认出** %s（得到 %r）"
                                                % (want, got))
        print("%-4s %-44s %s" % ("OK" if hit else "★红", title, note))
        ok = ok and hit

    # ⑤ 阴性对照：仓根散脚本里的相对 import 不该被认成任何本仓文件
    got, _bad = scan_imports("zz_root_script.py", "from . import anything\n")
    clean = not [g for g in got if g.startswith("=")]
    print("%-4s %-44s %s" % ("OK" if clean else "★红",
                             "⑤ 阴性对照：仓根散脚本的相对 import 不许造假阳性",
                             "得到 %r" % (got,)))
    ok = ok and clean

    # ⑥ 阴性对照：第三方绝对 import 不该造出目标（交给 resolve 回 None）
    got, _bad = scan_imports("backend/checks/x.py", "import shapely.geometry\n")
    print("%-4s %-44s %s" % ("OK" if got == ["shapely.geometry"] else "★红",
                             "⑥ 绝对 import 只交模块名，不擅自定位",
                             "得到 %r" % (got,)))
    ok = ok and got == ["shapely.geometry"]

    print("\n--selftest %s ①…⑥" % ("全过" if ok else "★有红：闸门坏了，别信它的绿灯"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
