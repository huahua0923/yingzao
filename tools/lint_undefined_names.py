# -*- coding: utf-8 -*-
r"""扫出「模块级根本没定义、却被当全局名读」的名字 —— 这类笔误**只在跑到那一行时才炸**。

为什么要有它（2026-10-12，同一个文件连栽两次，同一个病根）：
  写 `gates/J-07.9.4-03_residual_to_model.py` 时，函数尾写了 `return RC`
  —— 本文件只有 `RC_PASS / RC_FAIL / RC_NOGAUGE` 三个模块常量，**没有 `RC`**。
  ⇒ `NameError`，而它**在最后一行**：
    · 第一趟：崩在判词之后、json 之前 ⇒ **判据的产出物丢了**（310 s 白跑）；
    · 第二趟：json **已经写出**、判词说 pass，进程却 rc=1 ⇒ **产出物与退出码不一致**
      （`pass: true` + 非零 rc，谁读哪一边就得出相反的结论）。
  ★ 两次都不是「逻辑错」，是**函数尾那段代码从来没被成功执行过**。
  ⇒ 靠眼睛看不出来（`RC` 与 `RC_PASS` 只差后缀），抽成尺子。

做法（`symtable`，标准库）：模块级收「已定义的名字」（赋值/import/def/class/for/with/except…）
∪ 内建名；再递归进每个函数/类作用域，凡是被当作**全局**读、而两边都没有的 ⇒ 报出来。

★ 声明读法：**只报不判**（本尺子是告警器，exit 1 表示「有可疑项」，不等于「一定崩」）——
  动态构造的名字（`globals()[...]`、`exec`、注入的 `__all__` 用法）会误报，看到就自己回盘核对。

用法: python tools/lint_undefined_names.py [根目录或文件...] [--quiet]
"""
import builtins
import os
import symtable
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SKIP_DIRS = {".venv", "venv", "node_modules", "_archive", ".git", "__pycache__", "_out"}
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def module_names(top):
    """模块级「已定义」的名字。只读 `top` 这一层（不含函数体里绑的局部名）。"""
    out = set()
    for sym in top.get_symbols():
        if sym.is_assigned() or sym.is_imported() or sym.is_namespace() \
                or sym.is_parameter() or sym.is_global():
            out.add(sym.get_name())
    return out


def walk(table, defined, path, hits):
    for sym in table.get_symbols():
        if sym.is_global() and not sym.is_assigned():
            nm = sym.get_name()
            if nm not in defined and not hasattr(builtins, nm):
                hits.append((path, table.get_lineno(), nm))
    for child in table.get_children():
        walk(child, defined, path + "." + child.get_name(), hits)


def scan_file(p):
    src = open(p, encoding="utf-8").read()
    top = symtable.symtable(src, p, "exec")
    hits = []
    walk(top, module_names(top), os.path.basename(p), hits)
    # 去重 + 只留每个名字的第一处
    seen, uniq = set(), []
    for c, ln, nm in sorted(hits, key=lambda x: x[1]):
        if nm not in seen:
            seen.add(nm)
            uniq.append((c, ln, nm))
    return uniq


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    targets = args or [DEFAULT_ROOT]
    files = []
    for t in targets:
        if os.path.isfile(t):
            files.append(t)
        else:
            for dp, dns, fns in os.walk(t):
                dns[:] = [d for d in dns if d not in SKIP_DIRS]
                files += [os.path.join(dp, fn) for fn in sorted(fns)
                          if fn.endswith(".py") and fn != os.path.basename(__file__)]
    nbad = 0
    if not files:
        # ★ 扫到 0 个文件时报「干净」是**假绿**（`empty-collection-gauge-is-always-green` 同族）。
        print("★ 没量到任何 .py（目标 %s）⇒ 判「没量到」，不是「干净」" % (targets,))
        return 4
    for p in files:
        try:
            hits = scan_file(p)
        except SyntaxError as e:
            print("  [语法错，跳过] %s: %s" % (p, e))
            continue
        for c, ln, nm in hits:
            nbad += 1
            print("  可疑 %s:%d  作用域 %s 把 `%s` 当全局名读，模块级与内建都没有它"
                  % (p, ln, c, nm))
    print("\n扫了 %d 个 .py ⇒ 可疑未定义名 %d 处（只报不判，须自己回盘核对动态名字）"
          % (len(files), nbad))
    return 1 if nbad else 0


def selftest():
    """正对照（铁律 137/183）：喂**构造好的**样本，验有没有牙、有没有误报。

    ★ 判据是「命中集与期望是否相等」—— 不是「跑通了」。夹具写系统临时目录，不落本仓。
    """
    import tempfile
    cases = [
        # (名字, 夹具内容, 期望命中的名字集合, 说明)
        ("realbug.py",
         "RC_PASS = 0\nRC_FAIL = 1\n\n\ndef run():\n    return RC\n",
         {"RC"}, "实翻车那一行的形状：文件只有 RC_PASS/RC_FAIL，`return RC` 只差一个后缀"),
        ("clean.py",
         "RC = 0\n\n\ndef run():\n    return RC\n",
         set(), "定义了 RC ⇒ 不许报（误报会让尺子被忽略）"),
        ("builtin.py",
         "def run():\n    return len([1, 2])\n",
         set(), "内建名不算未定义"),
        ("closure.py",
         "def outer():\n    v = 1\n\n    def inner():\n        return v\n    return inner\n",
         set(), "闭包变量不算未定义（作用域链要认）"),
        ("imported.py",
         "import os\n\n\ndef run():\n    return os.sep\n",
         set(), "`os` 在函数体里是全局名但在模块级 import 过 ⇒ 不许报"),
        ("loopvar.py",
         "for i in range(3):\n    pass\n\n\ndef run():\n    return i\n",
         set(), "模块级 for 变量算已定义"),
    ]
    d = tempfile.mkdtemp(prefix="lint_undef_selftest_")
    nbad = 0
    for name, src, want, why in cases:
        p = os.path.join(d, name)
        open(p, "w", encoding="utf-8").write(src)
        got = {nm for _c, _ln, nm in scan_file(p)}
        ok = (got == want)
        nbad += 0 if ok else 1
        print("  %s %-12s 命中 %-14s(期望 %-14s) %s"
              % ("✓" if ok else "✗ ← 尺子不对", name,
                 sorted(got) or "—", sorted(want) or "—", why))
    import subprocess
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                        os.path.join(d, "不存在的目录")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = (r.returncode == 4)
    nbad += 0 if ok else 1
    print("  %s 空目标        rc=%d(期望 4)  %s"
          % ("✓" if ok else "✗ ← 尺子不对", r.returncode,
             (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""))
    print("\n自测：%d 档不通过（期望 0）⇒ 本尺子 %s"
          % (nbad, "有牙" if not nbad else "**自身有问题，别再拿它出判词**"))
    return 1 if nbad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main(sys.argv))
