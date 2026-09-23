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
用法：python _scratch/_import_graph_gap.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def main() -> int:
    tr = tracked()
    idx = local_modules()
    srcs = sorted(p for p in tr if p.endswith(".py") and not p.startswith("_scratch/"))
    print("扫描已入库的 .py：%d 个；仓内可解析模块名：%d 个" % (len(srcs), len(idx)))

    gaps: dict[str, set[str]] = {}
    n_imp = n_local = 0
    for f in srcs:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = IMPORT_RE.match(line)
            if not m:
                continue
            mod = (m.group(1) or m.group(2)).split(" as ")[0].strip()
            if not mod or mod.startswith("."):        # 相对 import：本仓文件必同在库里，跳过
                continue
            n_imp += 1
            hit = resolve(mod, idx)
            if hit is None:                            # 第三方 / 不存在 —— 不是本脚本的事
                continue
            n_local += 1
            if hit not in tr:
                gaps.setdefault(hit, set()).add(f)

    print("import 总数 %d 条，其中解析到仓内文件的 %d 条" % (n_imp, n_local))
    if not gaps:
        print("✓ 没有「已入库文件 import 未入库模块」的缺件")
        return 0
    print("✗ 有 %d 个模块：磁盘上有、git 不跟踪，却被已入库的文件 import" % len(gaps))
    for hit in sorted(gaps):
        who = sorted(gaps[hit])
        print("   %s" % hit)
        for w in who[:6]:
            print("       ← %s" % w)
        if len(who) > 6:
            print("       ← …另有 %d 处" % (len(who) - 6))
    return 1


if __name__ == "__main__":
    sys.exit(main())
