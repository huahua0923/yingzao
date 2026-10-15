# -*- coding: utf-8 -*-
r"""扫出 `%` 格式化字符串的**两个方向**的同形错 —— 两者都不报错、都要跑到才现形。

为什么要有这个工具（2026-10-12 实翻车两次，同一个形状）：
  · 写 `gates/J-07.9.4-03_residual_to_model.py` 时，在一句**有**格式参数的 print 里写了
    字面的 `100.00%` ⇒ `% ⇒` 被当成转换符 ⇒ **跑满 310 s、判词都印完了**，在最后一句
    `ValueError: unsupported format character` 上崩掉，json 没写成。
  · 修的时候又把两处 `%%` 写进了**没有**格式参数的 print ⇒ 一个字面印出 `100.00%%`。
  ⇒ 一个错法（`%` 的字面/转义比配）正反两面都犯过 ⇒ 抽成一把尺子（铁律 183）。

两把尺子分开记（不同性质，不合并）：
  【A 硬红】`左边是字符串字面量` 的 `%` 运算里，出现既不是 `%%`、也不构成合法转换的 `%`
          ⇒ 运行时**抛异常，类型取决于后面参数够不够**（2026-10-12 实测两种都出现）：
            · 参数还留在队列里 ⇒ `ValueError: unsupported format character`（实翻车那次）；
            · 参数刚好用尽 / 给的是空元组 ⇒ `TypeError: not enough arguments for format string`。
          两种都不报错、只在**跑到那一行**时才炸。★ 危险的是它藏在**某个分支里**：常走的分支吃掉
          大部分时间，判词照印，崩在最后一行 ⇒ 前面所有读数作废。退出码 = 1。
          （本尺子判的是**结构**：那里的 `%` 不是合法转换 ⇒ 迟早抛。不预测抛哪一种。）
  【B 软告警】字符串里有 `%%`，但它**根本不在任何 `%` 运算的左边** ⇒ 那 `%%` 会**原样印出**。
          （docstring / 帮助文本里写 `%%` 是有意的排版，不算错 ⇒ 本档只列、不判。）

用法: python tools/lint_pct_format.py [根目录] [--quiet]
     不进任何目录、只看显式给的根（默认本仓）；跳过 `.venv/`、`node_modules/`、`_archive/`。
"""
import ast
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# 合法转换：%[(key)][flags][width|*][.prec|*][长度修饰]转换符
CONV = re.compile(r"%(?:\([^)]*\))?[-+#0 ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?([diouxXeEfFgGcrsa%])")
SKIP_DIRS = {".venv", "venv", "node_modules", "_archive", ".git", "__pycache__", "_out"}
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def str_consts(n):
    """把 `%` 运算的**左操作数**摊平，取出其中的全部字符串字面量。"""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return [n]
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod):
        return str_consts(n.left) + str_consts(n.right)
    if isinstance(n, ast.JoinedStr):          # f-string：`%` 在里面就是字面量，不参与 % 格式
        return []
    return []


def docstring_nodes(tree):
    """所有 docstring 的 Constant 节点（B 档里要豁免它们）。"""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(n, clean=False)
            if d is not None and n.body and isinstance(n.body[0], ast.Expr) \
                    and isinstance(n.body[0].value, ast.Constant):
                out.add(id(n.body[0].value))
    return out


def scan_file(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    fmt_left = set()          # 出现在 `%` 运算左边的字面量节点
    hard, soft = [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod):
            for c in str_consts(n.left):
                fmt_left.add(id(c))
                s, i, bad = c.value, 0, None
                while True:
                    j = s.find("%", i)
                    if j < 0:
                        break
                    m = CONV.match(s, j)
                    if not m:
                        bad = (c.lineno, s[max(0, j - 44):j + 30].replace("\n", " "))
                        break
                    i = m.end()
                if bad:
                    hard.append(bad)
    docs = docstring_nodes(tree)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and "%%" in n.value and id(n) not in fmt_left and id(n) not in docs:
            soft.append((n.lineno, n.value.strip().replace("\n", " ")[:110]))
    return hard, soft, len(fmt_left)


def collect(targets):
    """把「目录」与「单个 .py」两种目标都摊平；★ 摊平后必须非空，否则尺子扫空集合恒绿。"""
    out = []
    for t in targets:
        if os.path.isfile(t):
            out.append(t)
            continue
        for dp, dns, fns in os.walk(t):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            out += [os.path.join(dp, fn) for fn in sorted(fns)
                    if fn.endswith(".py") and fn != os.path.basename(__file__)]
    return out


def main(argv):
    targets = [a for a in argv[1:] if not a.startswith("--")] or [DEFAULT_ROOT]
    files = collect(targets)
    if not files:
        # ★ 与 `empty-collection-gauge-is-always-green` 同族：扫到 0 个文件时报「干净」是**假绿**。
        print("★ 没量到任何 .py（目标 %s）⇒ 判「没量到」，不是「干净」" % (targets,))
        return 4
    nA = nB = nfiles = 0
    for p in files:
        try:
            hard, soft, nfmt = scan_file(p)
        except SyntaxError as e:
            print("  [语法错，跳过] %s: %s" % (p, e))
            continue
        if not nfmt and not soft:
            continue
        nfiles += 1
        for ln, ctx in hard:
            nA += 1
            print("A 硬红 %s:%d  行内出现既非 `%%%%` 也非合法转换的 `%%`\n     ...%s..." % (p, ln, ctx))
        for ln, ctx in soft:
            nB += 1
            print("B 告警 %s:%d  该串不参与 `%%` 运算，`%%%%` 会原样印出\n     %s" % (p, ln, ctx))
    print("\n扫了 %d 个 .py（其中 %d 个含 `%%` 格式面）⇒ A 硬红 %d 处（必须红，rc=1）／B 告警 %d 处（人看）"
          % (len(files), nfiles, nA, nB))
    return 1 if nA else 0


PCT2 = "%" * 2     # ★ 夹具里要写「两个百分号」，但不能让它以字面量出现在**本文件**里
                   #   —— 否则本尺子会把自己（这份自测）当 B 档点名。


def selftest():
    """正对照（铁律 137/183）：喂**构造好的**样本，逐档验有没有牙、有没有误报。

    ★ 判据是「每一档的 A/B 计数与期望是否相等」—— 不是「跑通了」。夹具写入系统临时目录，
      不落进本仓（本仓的 `.py` 复扫必须是 0 处，见 main）。
    """
    import tempfile
    cases = [
        # (名字, 夹具内容, 期望 A, 期望 B, 说明)
        ("fonly.py", "x = 1\nprint(f\"only fstring {x}\")\n",
         0, 0, "只有 f-string ⇒ 无 `%` 面，不该被算进 nfiles"),
        ("bareB.py", "print(\"a %s\" % 1)\nprint(\"bare 100" + PCT2 + " done\")\n",
         0, 1, "方向 B：不参与 `%` 运算的串里有 `%%` ⇒ 会原样印出（软告警）"),
        ("hardreal.py", "print(\"三臂同为 100.00% ⇒ 无分辨力\" % ())\n",
         1, 0, "方向 A：实翻车那一行的形状（`% ` 空格当 flag、`⇒` 不是转换符）"),
        ("legal.py", "print(\"覆盖率 %.2f" + PCT2 + " ⇒ 通过\" % (1,))\n",
         0, 0, "合法的 `%%` 与 `%.2f` ⇒ 一处也不许报（误报会让尺子被忽略）"),
        ("docstr.py", "def f():\n    \"\"\"写 100" + PCT2 + " 也是排版\"\"\"\n    return 1\n",
         0, 0, "docstring 里的 `%%` 是有意排版 ⇒ B 档豁免"),
    ]
    d = tempfile.mkdtemp(prefix="lint_pct_selftest_")
    nbad = 0
    for name, src, wa, wb, why in cases:
        p = os.path.join(d, name)
        open(p, "w", encoding="utf-8").write(src)
        hard, soft, _ = scan_file(p)
        ok = (len(hard) == wa and len(soft) == wb)
        nbad += 0 if ok else 1
        print("  %s %-11s A=%d(期望 %d) B=%d(期望 %d)  %s"
              % ("✓" if ok else "✗ ← 尺子不对", name,
                 len(hard), wa, len(soft), wb, why))
    # 空集合守卫：目录里一个 .py 都没有 ⇒ 必须 rc=4「没量到」，不是 rc=0「干净」
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                        os.path.join(d, "不存在的目录")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = (r.returncode == 4)
    nbad += 0 if ok else 1
    print("  %s 空目标          rc=%d(期望 4)  %s"
          % ("✓" if ok else "✗ ← 尺子不对", r.returncode,
             (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""))
    print("\n自测：%d 档不通过（期望 0）⇒ 本尺子 %s"
          % (nbad, "有牙" if not nbad else "**自身有问题，别再拿它出判词**"))
    return 1 if nbad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main(sys.argv))
