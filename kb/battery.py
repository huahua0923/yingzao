# -*- coding: utf-8 -*-
"""kb 的**总表**：一条命令把这一层该跑的全跑一遍，逐条打退出码。

为什么要有它（本仓铁律 25）：**闸门存在 ≠ 闸门被跑过**。
`kb/` 现在有 9 件东西各自能自检（自检 ＋ 刑具 ＋ 阳性对照），
一件一件手敲一遍，漏一件没人知道 —— 而「漏跑的那件」和「跑了且绿的那件」
在屏幕上长得一模一样。

用法（手解析 argv，不认 --help）：
    python -u kb/battery.py            # 全跑
    python -u kb/battery.py --quiet    # 只打结论表，中间输出全进日志
    退出码：0 = 全绿；1 = 有非预期的红；2 = 有**没量到**的（后端 8153 没起 / 没装 playwright）

★ 四条纪律，都来自踩过的坑：
  · 子进程输出**写文件**，不走 PIPE（铁律 14：PIPE 另一端没人读 → 死锁）；
  · `--quiet` 下每件仍要打「日志在哪」——「没输出」与「没跑」必须分开；
  · **表里只收跟踪文件**，一条 `_scratch/` 草稿都不收：
    草稿件不在 git 里 ⇒ 新克隆的仓里必然没有 ⇒ 要么整条消失、要么被读成「绿」
    （memory: gauge-coverage-invisible-in-summary）。它们本来也**只量草稿那一面**
    （`_kg_view_check.py` / `_kg_view_accept.py` 量的是 8155 那份草稿页），
    同一个面已有跟踪件在量（`backend/checks/kg_view_accept.py` 的 `--falsify`/`--walk`）
    ⇒ **同一个面不许有两份实现**（README 已按这条划界）。
  · 有些条今天是**预期红**的，要写进 `GAP_ALLOW`，但**预期红也要打出来**，不许静默放过。

★ 日志落在 `logs/kb_battery/`（`logs/` 已被 .gitignore 收掉）：
  它是跑出来的东西，不是交付件，别混进 `kb/` 被当成产物提交。
"""
import io
import os
import re
import subprocess
import sys
import time

KB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KB_DIR)
LOGDIR = os.path.join(ROOT, "logs", "kb_battery")

#: 允许为红的那几条：**点名**，不是「允许 exit 1」。
#    ★ 「允许 exit=1」是个 fail-open 的判据 —— 任何一条 GAP 都能冒充那条已知的
#      （memory: coverage-metric-invents-its-own-green）。所以这里写的是
#      **允许出现在输出里的那几行 GAP 的前缀**，多一条都算非预期红。
#    ★ 2026-09-24 已 `gate --record`（并逐条读过锚点视图：24 条指进 ask/build_kb/gate
#      的锚点**全是符号锚点**，各指各的，没有一条错位）⇒ 这张表**清空**。
#      ⚠ 下次为了让总表变绿而往这里加一行之前，先问：是「这条判据本来就该红」，
#        还是「我又在把它调绿」？后者会让总表变成一个永远绿的装饰品。
GAP_ALLOW = ()

#: ★ 「没量成」是一个**独立的结局**，不是「红」也不是「绿」（backend 没起 / 没装 playwright）。
#    K5 的四个模式用它当退出码 3；这里必须把它单列 —— 本仓栽过的那一族里，
#    「没量成」被读成「通过了」和「被读成失败了」各有一半。
PARTIAL = 3

#: (名字, argv, 备注, 预期退出码集合)
#    ★ 「预期为红」的那一条（`gate`）也在这里 —— 写的是**退出码集合**，
#      而不是「允许 exit 1」（见 GAP_ALLOW 那段：那是个 fail-open 的写法）。
CASES = [
    ("battery --selftest", ["kb/battery.py", "--selftest"], "总表自己的尺子（六格）", {0}),
    ("ask --selftest", ["kb/ask.py", "--selftest"], "查询引擎自检 T1–T15", {0}),
    ("ask_falsifier", ["kb/ask_falsifier.py"], "改坏**产物** kb.json 八处", {0}),
    ("ask_guard_falsifier", ["kb/ask_guard_falsifier.py"],
     "改坏**代码** ask.py 六处（守卫/多跳/分栏/回落/截断）", {0}),
    ("build_kb --check", ["kb/build_kb.py", "--check"], "产物 vs 源", {0}),
    ("build_kb --selftest", ["kb/build_kb.py", "--selftest"], "5 条刑具", {0}),
    ("gate", ["kb/gate.py"], "①②③④⑤⑥⑦⑪⑫ 全量复核", {0, 1}),
    ("gate --selftest", ["kb/gate.py", "--selftest"], "每条判据的阳性对照", {0}),
    ("derive --check", ["kb/derive.py", "--check"], "实例边 vs _qa 产物", {0}),
    ("values --selftest", ["kb/values.py", "--selftest"], "门禁④ 的取值与比对", {0}),
    # ── K5：**后台那一页**与 CLI 是不是同一份 JSON（要后端 8153 在跑）─────────
    #    ★ 这四个模式是「验收器本身」，它自己的刑具是 `--falsify`（排在第三个）。
    #      缺了这四个，整套 K5 就只剩「刑具能红」，而**没人拿它去量真的页面**。
    ("K5 --parity", ["-m", "backend.checks.kg_view_accept", "--parity",
                     "--base", "http://127.0.0.1:8153"], "页面读到的 JSON vs CLI", {0}),
    ("K5 --shapes", ["-m", "backend.checks.kg_view_accept", "--shapes"],
     "kg.js 声明的键 vs 载荷真有的键", {0}),
    ("K5 --falsify", ["-m", "backend.checks.kg_view_accept", "--falsify"],
     "前两个比较器能不能红", {0}),
    ("K5 --walk", ["-m", "backend.checks.kg_view_accept", "--walk"],
     "真开浏览器逐条画一遍（较慢）", {0}),
]


def gaps_in(text):
    """输出里那些 `……：GAP` 的行（判据自己报的红）。"""
    return [l.strip() for l in text.splitlines() if re.search(r"[：:]\s*GAP", l)]


def verdict(code, expect, txt, allow=()):
    """判一件：退出码在不在预期里 ＋ 有没有**没被点名**的 GAP。

    返回 `(ok, partial, problems)`。**单独一个函数**是为了它自己能被测 ——
    一张永远报绿的总表和一张真的总表在屏幕上长得一模一样
    （memory: saturated-criterion-has-no-resolution），所以下面有 `--selftest`。
    """
    stray = [g for g in gaps_in(txt) if not g.startswith(tuple(allow))]
    partial = code == PARTIAL and PARTIAL not in expect
    problems = []
    if code not in expect:
        problems.append("退出码 %d 不在 %s 里" % (code, sorted(expect)))
    if stray:
        problems.append("多出没有点名的 GAP %d 条（首条 %s）" % (len(stray), stray[0][:80]))
    return (not problems), partial, problems


def selftest():
    """总表自己的尺子：**六格，每一格都必须红/绿在指名的理由上**。

    ★ 阴性对照（最后一格）在场才算尺子 —— 只有「改坏会红」的话，
      一个恒红的判据也能满分（本仓栽过的：判据宽了会被学会忽略）。
    """
    cells = [
        # (说明, code, expect, 输出, allow, 期望 ok, 期望 partial, 期望 problems 里含什么)
        ("干净且退出码在预期里", 0, {0}, "① PASS\n② PASS", (), True, False, None),
        # ★ 输入要照**真输出的形状**抄（`名字：GAP（说明）`），不许凭印象编 ——
        #   我第一版写的是「① GAP 某处坏了」，没有那个冒号 ⇒ 判据按规格（`[：:]\s*GAP`）
        #   看不见它，于是这一格红在**夹具**上。红的时候先问夹具，再问代码。
        ("没被点名的 GAP ⇒ 必须红", 0, {0},
         "⑪ ASCII 引号当中文引号：GAP（量过 27 个文件）", (), False, False, "没有点名的 GAP"),
        ("已被点名的 GAP ⇒ 不算红", 0, {0},
         "⑪ ASCII 引号当中文引号：GAP（量过 27 个文件）",
         ("⑪ ASCII 引号当中文引号：GAP",), True, False, None),
        ("★ 只写了 GAP 三个字母、没有冒号 ⇒ **不进判据**（规格如此，不是漏检）", 0, {0},
         "① GAP 某处坏了", (), True, False, None),
        ("退出码 3 且不在预期里 ⇒ 记成没量成，不是红", 3, {0}, "起不来", (),
         False, True, "退出码 3"),
        ("★ 阴性对照：不接 GAP 字样的输出 ⇒ 必须绿（判据不许凭「看着像」报红）",
         0, {0}, "全部 PASS，无异常", (), True, False, None),
    ]
    bad = 0
    for i, (label, code, expect, txt, allow, want_ok, want_partial, must_say) in enumerate(cells, 1):
        ok, partial, problems = verdict(code, expect, txt, allow)
        why = []
        if ok != want_ok:
            why.append("ok=%s 应为 %s" % (ok, want_ok))
        if partial != want_partial:
            why.append("partial=%s 应为 %s" % (partial, want_partial))
        if must_say and not any(must_say in p for p in problems):
            why.append("problems 里没提到 %r（实得 %s）" % (must_say, problems))
        if not must_say and problems:
            why.append("本该无 problems，实得 %s" % problems)
        print("%s T%d %s" % ("✓" if not why else "✗", i, label))
        for w in why:
            print("     ✗ %s" % w)
        bad += 1 if why else 0
    print("尺子自检：%s（%d 格，%d 格不对）"
          % ("PASS" if not bad else "GAP", len(cells), bad))
    return 1 if bad else 0


def main():
    quiet = "--quiet" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("-") and a not in ("--quiet", "--selftest"):
            print("不认识的开关 %r（用法：… [--quiet|--selftest]）" % a)
            return 2
    if "--selftest" in sys.argv:
        return selftest()
    if not os.path.isdir(LOGDIR):
        os.makedirs(LOGDIR)

    print("=== kb 总表（%s）===" % time.strftime("%Y-%m-%d %H:%M:%S"))
    rows, unexpected, not_measured = [], [], []
    for name, argv, note, expect in CASES:
        log = os.path.join(LOGDIR, name.replace(" ", "_").replace("--", "") + ".log")
        t0 = time.time()
        with io.open(log, "wb") as fh:
            p = subprocess.run([sys.executable, "-u"] + argv, cwd=ROOT,
                               stdout=fh, stderr=subprocess.STDOUT,
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        secs = time.time() - t0
        txt = io.open(log, encoding="utf-8", errors="replace").read()
        gaps = gaps_in(txt)
        ok, partial, problems = verdict(p.returncode, expect, txt, GAP_ALLOW)
        if problems and not partial:
            unexpected.append((name, problems))
        if partial:
            not_measured.append((name, "退出码 3 = 没量成"))
        rows.append((name, p.returncode, ok, partial, secs, note, log, gaps, problems))

    for name, code, ok, partial, secs, note, log, gaps, problems in rows:
        mark = "⚠" if partial else ("✓" if ok else "✗")
        print("%s %-24s exit=%d  %5.1fs  %s" % (mark, name, code, secs, note))
        for g in gaps:
            print("     %s GAP %s" % ("·" if g.startswith(GAP_ALLOW) else "!", g[:130]))
        for pr in problems:
            print("     %s %s" % ("⚠" if partial else "✗", pr))
        if not quiet:
            txt = io.open(log, encoding="utf-8", errors="replace").read().strip().splitlines()
            for l in txt[-8:]:
                print("     | %s" % l[:150])
        print("     └ 日志 %s" % os.path.relpath(log, ROOT).replace("\\", "/"))

    print("\n=== 结论 ===")
    if unexpected:
        print("✗ %d 件非预期红：" % len(unexpected))
        for name, problems in unexpected:
            print("   · %s —— %s" % (name, "；".join(problems)))
    if not_measured:
        print("⚠ %d 件**没量成**（「没量成」不等于通过）：" % len(not_measured))
        for name, why in not_measured:
            print("   · %s —— %s（后端 8153 起了吗？playwright 装了没？）" % (name, why))
    green = len(rows) - len(unexpected) - len(not_measured)
    print("绿 %d / 共 %d 件（没量成 %d）" % (green, len(rows), len(not_measured)))
    if not unexpected and not not_measured:
        print("✓ %d 件全部落在预期内。" % len(rows))
    if GAP_ALLOW:
        print("★ 允许的 GAP 只有：%s —— `--record` 之后这张表要清空，"
              "否则它会变成一个永远红的背景噪声（memory: append-only-ledger-whole-table-assertion）。"
              % "、".join(GAP_ALLOW))
    if unexpected:
        return 1
    return 2 if not_measured else 0


if __name__ == "__main__":
    sys.exit(main())
