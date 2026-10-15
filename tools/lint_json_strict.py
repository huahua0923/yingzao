# -*- coding: utf-8 -*-
r"""尺子：扫出**不是严格 JSON** 的 `.json` 件 —— 重点是裸 `NaN` / `Infinity`。

为什么要有它（铁律 123，2026-10-12 在本仓实测到）：
  `gates/_out/J-09.2-A1.json` 的 `rows[*].lcs[*]` 里有 **4 个裸 `NaN`**
  （来自 `a1/generic_wall.py:257` 对「无取样点图幅」**有意**返回的 NaN）。
  症状是**读写不对称**：
    · Python `json.loads` **默认吃** `NaN`（`allow_nan=True`）⇒ 写的人和读的人
      都在 Python 里，**谁也量不出这是坏件**；
    · 浏览器 `JSON.parse` / Node / Go / Rust **一律抛错** ⇒ 前端白屏。
  实测（node 26，2026-10-12）：
      `JSON.parse(fs.readFileSync('gates/_out/J-09.2-A1.json'))`
      ⇒ `SyntaxError: Unexpected token 'N', ..."0.0,\n    NaN,\n"... is not valid JSON`
  最终页 `demo/sys.html` 读这些 json 摊字段 —— 这尺子就是它的上游守卫。

做法：`json.loads(text, parse_constant=raise)`。
  ★ `parse_constant` **只在** `NaN` / `Infinity` / `-Infinity` 三处被回调，
    所以拿它当探测器是**精确**的，不会把字符串里的 `"NaN"` 误报（见自测档 3）。
  ★ 另外收下 `JSONDecodeError`（其余语法错，如尾逗号、单引号）—— 一并报。

★ 声明的盲区（铁律 158）：
  ① 本尺子只认 **Python 解析器**能识别的不合法。它与浏览器 `JSON.parse` 的**其余**
     差异（若有）**没逐条量过** —— 只对 `NaN/Infinity` 这一族做了**双实现互证**（node 实测）。
  ② 只扫 `.json` 后缀的件；`.jsonl` / 内嵌在 `.md` 代码块里的 json **全盲**。
  ③ **只报不判语义**：`null` 合不合法是业务问题，本尺子不管 —— 它只说「这串能不能被
     严格解析器吃下」。
  ④ ★ **`_out` 目录不跳过** —— 第一版把它跟 `lint_undefined_names.py` 一样跳了，
     而**实翻车那个件就在 `gates/_out/` 下** ⇒ 尺子对自己**唯一**要量的那一格全盲，
     报「扫了 34 个 ⇒ 0 件坏」，rc=0、**假绿**（铁律 137/158 同族：
     参照物退化时守卫会放掉它唯一该护住的东西）。`gates/_out` 是**判据产物台账**、
     `a1/_out` 与 `chain/_out` 是**链的落盘读数** —— 都是交付面，不是临时目录。
     ⇒ 只跳真正的历史件与依赖目录（`_archive` / `.git` / `__pycache__` / 虚拟环境 /
     `node_modules`）；自测里有一档专门钉住这条（见 `selftest` 的「_out 子目录」）。
     真要用别的跳法：`--all`（几乎不跳）。

用法: python tools/lint_json_strict.py [根目录或文件...] [--all]
     python tools/lint_json_strict.py --selftest
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ★ `_out` **不在这里** —— 见 docstring ④。
SKIP_DIRS = {".venv", "venv", "node_modules", "_archive", ".git", "__pycache__"}
SKIP_ALWAYS = {".venv", "venv", "node_modules", ".git", "__pycache__"}
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NonFinite(Exception):
    """裸 NaN / Infinity / -Infinity —— 严格解析器不认，Python 默认却吃。"""


def _raise_const(name):
    raise NonFinite(name)


def strict_load(text):
    """严格读一遍。★ 这是本尺子的**唯一**量具 —— 不要退回默认的 `json.loads`。"""
    return json.loads(text, parse_constant=_raise_const)


def scan_file(p):
    """返回 (状态, 说明)。状态 ∈ {'ok', 'nan', 'syntax', 'read'}。"""
    try:
        raw = open(p, "rb").read()
    except OSError as e:
        return "read", str(e)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return "read", "不是 UTF-8：%s" % e
    # ★ UTF-8 BOM：Python 能过，浏览器 JSON.parse 会抛（U+FEFF 不是合法空白）
    bom = text.startswith("﻿")
    try:
        strict_load(text)
    except NonFinite as e:
        where = []
        for i, ln in enumerate(text.splitlines(), 1):
            s = ln.strip().rstrip(",")
            if s in ("NaN", "Infinity", "-Infinity") or s.endswith((": NaN", ": Infinity", ": -Infinity")):
                where.append(i)
        return "nan", ("裸 %s ×%d（行 %s）"
                       % (e, len(where) or 1, ",".join(map(str, where[:8])) or "?"))
    except json.JSONDecodeError as e:
        return "syntax", "第 %d 行第 %d 列：%s" % (e.lineno, e.colno, e.msg)
    if bom:
        return "syntax", "带 UTF-8 BOM —— Python 吃得下，浏览器 JSON.parse 抛（U+FEFF）"
    return "ok", ""


def gather(targets, keep_all):
    skip = SKIP_ALWAYS if keep_all else SKIP_DIRS
    files = []
    for t in targets:
        if os.path.isfile(t):
            files.append(t)
        else:
            for dp, dns, fns in os.walk(t):
                dns[:] = [d for d in dns if d not in skip]
                files += [os.path.join(dp, fn) for fn in sorted(fns) if fn.endswith(".json")]
    return files


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    keep_all = "--all" in argv
    targets = args or [DEFAULT_ROOT]
    files = gather(targets, keep_all)
    if not files:
        # ★ 扫到 0 个文件时报「干净」是**假绿**（`empty-collection-gauge-is-always-green` 同族）。
        print("★ 没量到任何 .json（目标 %s）⇒ 判「没量到」，不是「干净」" % (targets,))
        return 4
    nbad = 0
    for p in files:
        st, msg = scan_file(p)
        if st == "ok":
            continue
        nbad += 1
        tag = {"nan": "★裸常量", "syntax": "★语法错", "read": "★读不出"}[st]
        print("  %s %s —— %s" % (tag, p, msg))
    print("\n扫了 %d 个 .json ⇒ 不是严格 JSON 的 %d 件（跳过的目录：%s%s）"
          % (len(files), nbad,
             "全部" if keep_all else "、".join(sorted(SKIP_DIRS)),
             "；本趟 --all" if keep_all else ""))
    print("（本尺子只判「严格解析器吃不吃的下」；`null` 合不合法是业务问题，它不管）")
    return 1 if nbad else 0


def selftest():
    """正对照（铁律 137/183）：喂**构造好的**样本，验有没有牙、有没有误报。

    ★ 判据是「命中集与期望是否相等」—— 不是「跑通了」。夹具写系统临时目录，不落本仓。
    """
    import tempfile
    cases = [
        # (名字, 内容, 期望状态, 说明)
        ("nan.json", '{\n "lcs": [\n  100.0,\n  NaN\n ]\n}\n', "nan",
         "实翻车那一格的形状：数组里一个裸 NaN"),
        ("inf.json", '{\n "x": Infinity\n}\n', "nan", "裸 Infinity 同样不是严格 JSON"),
        ("neginf.json", '{\n "x": -Infinity\n}\n', "nan", "负号那一支也要认"),
        ("string_nan.json", '{\n "note": "value was NaN here"\n}\n', "ok",
         "★ 字符串里的字样不许报（误报会让尺子被忽略）"),
        ("null_ok.json", '{\n "lcs": [\n  100.0,\n  null\n ]\n}\n', "ok",
         "「没量到」写 null ⇒ 这才是对的编码，必须干净"),
        ("trailing.json", '{\n "a": 1,\n}\n', "syntax", "尾逗号：Python 与浏览器都抛，一并报"),
        ("single_quote.json", "{\n 'a': 1\n}\n", "syntax", "单引号不是 JSON"),
        ("clean.json", '{\n "pass": true,\n "n": 3\n}\n', "ok", "正常件必须干净"),
    ]
    d = tempfile.mkdtemp(prefix="lint_json_selftest_")
    nbad = 0
    for name, body, want, why in cases:
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(body.encode("utf-8"))
        got, msg = scan_file(p)
        ok = (got == want)
        nbad += 0 if ok else 1
        print("  %s %-20s 判 %-7s(期望 %-7s) %-42s %s"
              % ("✓" if ok else "✗ ← 尺子不对", name, got, want, why,
                 ("· " + msg) if msg else ""))
    # BOM 那一档单列（它不是「解析失败」，是「换个实现就失败」）
    p = os.path.join(d, "bom.json")
    with open(p, "wb") as f:
        f.write("﻿{\n \"a\": 1\n}\n".encode("utf-8"))
    got, msg = scan_file(p)
    ok = (got == "syntax")
    nbad += 0 if ok else 1
    print("  %s %-20s 判 %-7s(期望 syntax) %-42s %s"
          % ("✓" if ok else "✗ ← 尺子不对", "bom.json", got,
             "★ BOM：Python 吃得下、浏览器 JSON.parse 抛", msg))
    # ★ 钉住「`_out` 不许被跳过」—— 实翻车那个件正住在 `gates/_out/` 下。
    #   夹具摆成 <tmp>/gates/_out/nan.json，再用**目录**为参数跑一遍真 main()。
    import subprocess
    d2 = os.path.join(d, "gates", "_out")
    os.makedirs(d2, exist_ok=True)
    with open(os.path.join(d2, "under_out.json"), "wb") as f:
        f.write('{\n "x": NaN\n}\n'.encode("utf-8"))
    rr = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__), d],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    hit = "under_out.json" in (rr.stdout or "")
    ok = (rr.returncode == 1 and hit)
    nbad += 0 if ok else 1
    print("  %s %-20s rc=%d(期望 1) 命中=%s %s"
          % ("✓" if ok else "✗ ← 尺子不对", "_out 子目录", rr.returncode, hit,
             "★ 住在 `gates/_out/` 下的坏件必须被收（第一版正是跳了它 ⇒ 假绿）"))
    # 空目标 ⇒ rc=4（不能报「干净」）
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                        os.path.join(d, "不存在的目录")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = (r.returncode == 4)
    nbad += 0 if ok else 1
    print("  %s 空目标               rc=%d(期望 4)  %s"
          % ("✓" if ok else "✗ ← 尺子不对", r.returncode,
             (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""))
    # ★ 与**另一实现**互证：node 的 JSON.parse 是否与我的严格读法在「裸 NaN」上同判
    try:
        import shutil
        subprocess.run(["node", "-v"], capture_output=True, check=True)
        probe = os.path.join(d, "nan.json")
        code = ("const fs=require('fs');"
                "try{JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
                "console.log('OK')}catch(e){console.log('BAD')}")
        rr = subprocess.run(["node", "-e", code, probe],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
        ok = (rr.stdout.strip() == "BAD")
        nbad += 0 if ok else 1
        print("  %s node 互证（同一件，另一实现）%s 说 %s"
              % ("✓" if ok else "✗ ← 两实现打架", "nan.json", rr.stdout.strip() or "?"))
    except (OSError, subprocess.CalledProcessError):
        print("  — node 不可用 ⇒ 跳过互证（只影响「双实现」这一条，不影响上面的牙）")
    print("\n自测：%d 档不通过（期望 0）⇒ 本尺子 %s"
          % (nbad, "有牙" if not nbad else "**自身有问题，别再拿它出判词**"))
    return 1 if nbad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main(sys.argv))
