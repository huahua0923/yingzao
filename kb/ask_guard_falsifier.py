# -*- coding: utf-8 -*-
"""`kb/ask.py` 里那六道**代码级**守卫的刑具：把被测的那几行**真改坏**，要求对应的断言真的红。

（与 `kb/ask_falsifier.py` 分工：那一份改的是**产物** `kb/kb.json` 的内存副本，
这一份改的是**代码** `kb/ask.py` 本身 —— 一个验数据判据、一个验代码守卫，不重复。）

★ 为什么非做不可：T12 里六格是直接调 `_run_guard`，一格走调用点。把调用点那一行
  删掉、或把闸改成恒放行，**屏幕上照样可能全绿** —— 判据全绿先自问
  「它是不是在全部样本上都取极值」（memory: saturated-criterion-has-no-resolution）。
  同理 T14/T15（多跳 / 卫星 / 回落 / 截断）也都是「不改坏就分不出**它是不是在空转**」的格子。

★ 每一格都必须**红在指名的那一处**：`want` 是要在输出里出现的 `✗ T__` 前缀。
  只判 exit != 0 是不够的 —— 改坏一处可能让**别的**格子先崩（本仓实测过：
  让 ev: 节点走 entry 支，若分栏与 top_kind 各判一次，会先 IndexError 崩掉，
  屏幕上就看不到那条本该报出来的断言）。

★ 还原必须**自己验证**（铁律 35：回滚失败与回滚成功，差别必须落在退出码上）。
  路径一律绝对 Windows 形态、正斜杠 —— 不写 `/tmp`（MSYS 与原生 python 各解释各的）。

用法（不认 --help）：
    python -u kb/ask_guard_falsifier.py
"""
import hashlib
import io
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 仓库根从本文件位置推，**不写死 `D:/gym3d`** —— 写死的路径在新克隆/换机器上
#: 会静静地指向别处（本仓栽过：`GYM3D_SU_JOB_DIR` 写成反斜杠，十个 SU 实例全哑）。
KB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KB_DIR)
ASK = os.path.join(KB_DIR, "ask.py").replace("\\", "/")

#: (说明, 找什么, 换成什么, 要求红在哪一处)
CASES = [
    ("闸改成恒放行", '    judge = _judge or globals().get("READONLY_VERDICT")',
     '    return True, "假装放行"\n    judge = _judge or globals().get("READONLY_VERDICT")',
     "T12"),
    ("调用点不调闸",
     '        allowed, gate_why = _run_guard(cmd, r.get("writes") or "")',
     '        allowed, gate_why = True, "假装放行"', "T12"),
    # ── T14 多跳：把「最多走两跳」改成跳不动，共用一个陷阱的两族就再也碰不到面 ──
    ("多跳改成只走一跳", "MAX_HOPS = 2        # 最多走几跳", "MAX_HOPS = 1        # 最多走几跳",
     "T14"),
    # ── T15(a) 卫星不许当主命中：把「前缀像条目不等于产物里有这条」这一句拆掉 ──
    #    这一格改的正是那条判据的**前提**，所以它红了才说明这条判据真的在管这件事。
    ('卫星也当条目（"entry" 支不再回查产物）',
     '        if b == "entry" and k not in ents:', "        if False:", "T15"),
    # ── T15(b) 图不在 ⇒ 必须报 legacy：这一格把回落做成**静默**的，
    #    正是本仓栽过的那类（静默回退 ⇒「图没建好」与「图就长这样」同形）──
    ("回落不报 legacy（静默只走一跳）",
     'return _spread_legacy(kb, seeds), {"mode": "legacy", "hops": 1,',
     'return _spread_legacy(kb, seeds), {"mode": "graph", "hops": 1,', "T15"),
    # ── T15(c) 截断要报出截掉多少：把它改成静默不截断（亮多少算多少）──
    ("截断改成静默不截断", "    if len(act) > cap:", "    if False:  # 静默不截断",
     "T15"),
]


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


orig_sha = sha(ASK)
orig = io.open(ASK, encoding="utf-8").read()
print("改坏前 sha256 = %s" % orig_sha[:16])

bad = 0
for name, old, new, want in CASES:
    if orig.count(old) != 1:
        print("✗ 找不到锚点（%d 处）：%s" % (orig.count(old), name))
        bad += 1
        continue
    io.open(ASK, "w", encoding="utf-8", newline="").write(orig.replace(old, new))
    p = subprocess.run([sys.executable, "-u", ASK, "--selftest"], cwd=ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = (p.stdout or b"").decode("utf-8", "replace")
    fired = [l for l in out.splitlines() if l.strip().startswith("✗ " + want)]
    print("\n▸ %s：exit=%d，%s 报出 %d 条" % (name, p.returncode, want, len(fired)))
    for l in fired[:3]:
        print("   %s" % l.strip()[:150])
    if p.returncode == 0 or not fired:
        print("   ✗✗ 改坏了却不红（或红在别处）—— 这几格是摆设")
        bad += 1
    io.open(ASK, "w", encoding="utf-8", newline="").write(orig)
    if sha(ASK) != orig_sha:                     # ★ 还原要自己验证，且要影响退出码
        print("   ✗✗ 还原失败：sha256 %s ≠ %s" % (sha(ASK)[:16], orig_sha[:16]))
        bad += 1

print("\n还原后 sha256 = %s（原 %s）" % (sha(ASK)[:16], orig_sha[:16]))
p = subprocess.run([sys.executable, "-u", ASK, "--selftest"], cwd=ROOT,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print("还原后自检 exit=%d" % p.returncode)
if p.returncode != 0:
    bad += 1
print("结论：%s" % ("✓ %d 处都真的红在指名的那一处，且已逐字节还原" % len(CASES)
                  if not bad else "✗ %d 处不对" % bad))
sys.exit(1 if bad else 0)
