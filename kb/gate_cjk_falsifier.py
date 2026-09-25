# -*- coding: utf-8 -*-
"""刑具：把 `kb/gate.py` ⑪ 第四档（仓内 .md 带基线）的**三条断言各自拆掉**，
看 `--selftest` 会不会红。

★ 为什么非做这一步不可：本仓记过「13 条自检全绿而 bug 活了一整轮」，也记过
  「阴性对照的前提没把要验的变量孤立出来 ⇒ 那条断言是**空的**（有别的项在替它把红点亮）」。
  **一条断言绿，不构成它测到了东西的证据** —— 把它比较的那个变量拆掉再跑，才算验过。

三条各自的「拆法」：
  S1 键里去掉「文件」这一维         ⇒ `_band_diff` 的 新增/命中 计数必须变红
  S2 拆掉尺子指纹判断             ⇒ 「尺子变了 ⇒ 整档判不了」必须红
  S3 清空排除清单                 ⇒ 「_scratch/ 下的 .md 不许算进来」必须红

每条的还原都按**字节**做，并在末尾核对 sha256；还原失败以非 0 退出码吵出来
（铁律 35：回滚失败与回滚成功，差别必须落在退出码上）。

用法：PYTHONIOENCODING=utf-8 python -u kb/gate_cjk_falsifier.py
退出码：0 三条全红且还原成功 / 1 有哪条**没红**（那条断言是空的）/ 2 刑具自己出错
"""
import hashlib
import io
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "kb", "gate.py")

CASES = [
    ("S1 键里去掉「文件」这一维",
     '        bucket = left.setdefault(h["file"], {})',
     '        bucket = left.setdefault("x", {})'),
    ("S2 拆掉尺子指纹判断",
     "    if ruler_was != ruler_now:",
     "    if False:"),
    ("S3 清空排除清单",
     '_REPO_MD_SKIP = (".git", "node_modules", "__pycache__", ".orig", "_scratch", ".claude")',
     "_REPO_MD_SKIP = ()"),
]


def run_selftest() -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-u", "kb/gate.py", "--selftest"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    orig = io.open(TARGET, "rb").read()
    sha0 = hashlib.sha256(orig).hexdigest()
    text = orig.decode("utf-8")

    rc_base, out_base = run_selftest()
    print("基线 --selftest 退出码 = %d（须为 0，否则下面「改坏变红」什么都证明不了）" % rc_base)
    if rc_base != 0:
        print(out_base[-1200:])
        return 2

    bad = []
    try:
        for name, old, new in CASES:
            if text.count(old) != 1:
                print("✗ %s：锚点命中 %d 次（须恰好 1 次）—— 改不进去的变异是**假绿**，"
                      "文件根本没变而报告会说「验收器漏了」" % (name, text.count(old)))
                bad.append(name)
                continue
            io.open(TARGET, "wb").write(text.replace(old, new, 1).encode("utf-8"))
            rc, out = run_selftest()
            red = rc != 0
            hits = [ln for ln in out.split("\n") if "T⑪repo" in ln or "T⑪ " in ln]
            print("%s ⇒ 退出码 %d %s" % (name, rc, "红 ✓" if red else "**没红 ✗**"))
            for ln in hits[:4]:
                print("       %s" % ln.strip()[:150])
            if not red:
                bad.append(name)
            io.open(TARGET, "wb").write(orig)
    finally:
        io.open(TARGET, "wb").write(orig)

    sha1 = hashlib.sha256(io.open(TARGET, "rb").read()).hexdigest()
    if sha1 != sha0:
        print("✗ 还原失败：%s != %s —— 盘上留着的是**改坏的那一版**" % (sha1, sha0))
        return 2
    print("还原核对：sha256 %s… 与起手时一致" % sha1[:16])

    rc_end, _ = run_selftest()
    if rc_end != 0:
        print("✗ 还原之后 --selftest 仍不绿（退出码 %d）" % rc_end)
        return 2
    print("还原之后 --selftest 退出码 = 0")

    if bad:
        print("✗ 有 %d 条变异**没让自检变红**：%s" % (len(bad), "、".join(bad)))
        print("  ⇒ 对应的断言是**空的**（有别的项在替它把红点亮），不是「代码没问题」。")
        return 1
    print("✓ 三条变异全部让 --selftest 变红 ⇒ 那三条断言各自真的在测东西。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
