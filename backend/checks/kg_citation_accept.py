# -*- coding: utf-8 -*-
"""C4 的验收器 —— 两种跑法，各证明一件 `--selftest` 证明不了的事。

为什么单独一个文件：`kg_citation.py` 是**只读**判据（跑进 `runner.py --all`），
它自己的 13 条自检喂的是**内存里造的载荷**。那证明的是「给了红载荷它会红」，
**没**证明「真红的时候它会拿到红载荷」—— 中间还隔着 `_run`（子进程、编码、cwd、超时）
这一整段。两截分开验才算尺子验过（memory: verifier-needs-its-own-falsifier）。

    python -m backend.checks.kg_citation_accept --diff       # 进表只多这一行
    python -m backend.checks.kg_citation_accept --falsify    # 真改坏一条 evidence

**为什么放在 `backend/checks/` 而不是 `_scratch/`**：`_scratch/` 按计划要整体搬出仓库
（P3）。验收证据跟着搬走 = 到期作废。放这儿，谁 clone 下来都能把这两条重跑一遍。

## `--diff` 怎么算「只多这一行」

同一份 census 结果跑两遍 `run_all`，一遍正常、一遍**在内存里**把
`system.CHECKS["c4"]` 摘掉（不碰盘上任何文件）。然后逐字段比对：

  · **独立字段**（`verdict`/`blockers`/`meta`/`scope`…）必须逐字段相同
  · **派生字段**（`counts`/`by_floor`）必须变得**恰好一致** —— 它们是 `Report`
    从 findings 现算的，要求它们"不变"是错的（我第一版就这么错过了）；
    要断言的是"恰好 +2 pass、且多出来的两条就是新增那两条"

## `--falsify` 改的是 `kb/kb.json`，不是知识源

它是构建产物（`build_kb.py` 随时能重出）。全程：备份 → 把一条 evidence 的行号顶到
十万以外 → 量 → 逐字节还原 → `cmp` ＋ sha12 双验。**两个方向都验过才算数。**

★ 顺带一条实测：改坏 `kb.json` 会让 **C4.instances 也红**，理由是 derive 腿②
（源内容指纹变了而计数一个没变）—— 那正是只有它看得见的一档。两个判据互相印证。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):          # ★ Windows 管道默认 GBK，中文必炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
KBJSON = ROOT / "kb" / "kb.json"
BAK = ROOT / "_scratch" / "_kb_json_falsify.bak"
PY = sys.executable
DERIVED = {"findings", "counts", "by_floor"}
#: 改坏的目标形状：`"evidence": "文件:行号"`。挑行号是因为**越界是静默失效的典型**。
_LINE_EV = re.compile(rb'"(evidence|at)":\s*"([^"]+\.(?:py|md|json)):(\d+)"')


def _sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def _child(argv: list[str]) -> tuple[int, str]:
    """跑一个子进程，**两头都归一到 utf-8**（子进程 env ＋ 父进程解码）。"""
    p = subprocess.run([PY, "-u"] + argv, cwd=str(ROOT), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out + err


# ── ① 进表只多这一行 ──────────────────────────────────────

def mode_diff() -> int:
    sys.path.insert(0, str(ROOT))
    from backend.checks import system
    from backend.paths import DATA
    from backend.state import census

    state = census.compute()
    print("census 现算一份（built_at=%s，criterion_version=%s）"
          % (state.get("built_at"), state.get("criterion_version")))
    full = system.run_all(DATA, state=state).as_dict()
    saved = system.CHECKS.pop("c4")
    try:
        base = system.run_all(DATA, state=state).as_dict()
    finally:
        system.CHECKS["c4"] = saved

    ok = True
    nf, nb = len(full["findings"]), len(base["findings"])
    print("findings：全量 %d 条，基线 %d 条，多出来 %d 条" % (nf, nb, nf - nb))
    if full["findings"][:nb] != base["findings"]:
        print("  ✗ 基线那 %d 条不是全量报告的前缀 —— C4 动了别人的结论" % nb)
        ok = False
    else:
        print("  ✓ 基线 %d 条逐字段相同，且是全量报告的前缀" % nb)
    added = full["findings"][nb:]
    if [f["check"] for f in added] != ["C4.edges", "C4.instances"]:
        print("  ✗ 多出来的不是恰好 C4.edges ＋ C4.instances：%s"
              % [f["check"] for f in added])
        ok = False
    else:
        print("  ✓ 多出来的恰好两条：%s"
              % "、".join("%s=%s" % (f["check"], f["status"]) for f in added))

    indep = sorted((set(full) | set(base)) - DERIVED)
    bad = [k for k in indep if full.get(k) != base.get(k)]
    for k in bad:
        print("  ✗ 独立字段 %r 变了：%s ≠ %s"
              % (k, json.dumps(full.get(k), ensure_ascii=False)[:300],
                 json.dumps(base.get(k), ensure_ascii=False)[:300]))
        ok = False
    if not bad:
        print("  ✓ %d 个独立字段（verdict/blockers/meta/scope…）逐字段相同" % len(indep))

    d = {k: v for k, v in
         ((k, full["counts"].get(k, 0) - base["counts"].get(k, 0))
          for k in set(full["counts"]) | set(base["counts"])) if v}
    if d == {"pass": 2}:
        print("  ✓ counts 恰好 +2 pass（%s → %s）"
              % (json.dumps(base["counts"], ensure_ascii=False),
                 json.dumps(full["counts"], ensure_ascii=False)))
    else:
        print("  ✗ counts 的变化不是「恰好 +2 pass」：%s" % d)
        ok = False
    diff_b = [(b, len(full["by_floor"].get(b, [])), len(base["by_floor"].get(b, [])))
              for b in sorted(set(full["by_floor"]) | set(base["by_floor"]))
              if full["by_floor"].get(b, []) != base["by_floor"].get(b, [])]
    if (len(diff_b) == 1 and diff_b[0][0] == "整栋" and diff_b[0][2] + 2 == diff_b[0][1]
            and full["by_floor"]["整栋"][-2:] == added):
        print("  ✓ by_floor 只有 '整栋' 那格变了（%d→%d），多出来的就是新增两条"
              % (diff_b[0][2], diff_b[0][1]))
    else:
        print("  ✗ by_floor 的变化不干净：%s" % diff_b)
        ok = False

    ev = added[0].get("evidence", {}) if added else {}
    if not ev.get("n_edges") or not ev.get("ruler", {}).get("gate_sha12"):
        print("  ✗ C4.edges 证词缺边数或尺子指纹：%s" % json.dumps(ev, ensure_ascii=False)[:300])
        ok = False
    else:
        print("  ✓ C4.edges 证词：%s 条边 / %s 条红 / 退出码 %s\n     %s\n     尺子 %s"
              % (ev["n_edges"], ev.get("n_fails"), ev.get("exit"),
                 json.dumps(ev.get("subs"), ensure_ascii=False),
                 json.dumps(ev["ruler"], ensure_ascii=False)))
    r2 = (added[1].get("evidence", {}) if len(added) > 1 else {}).get("ruler") or {}
    if not r2.get("readable") or not r2.get("self_sha12"):
        print("  ✗ C4.instances 证词里没有实例层产物自己的尺子指纹")
        ok = False
    else:
        print("  ✓ C4.instances 证词：产物 self=%s / 楼栋 %s / 源指纹 %d 项"
              % (r2.get("self_sha12"), r2.get("universe"), len(r2.get("src_sha") or {})))
    print("\n%s  verdict：全量=%s（摘掉 C4 后 %s）" % ("★ 通过" if ok else "★ 不通过",
                                                     full["verdict"], base["verdict"]))
    return 0 if ok else 1


# ── ② 真改坏一条 evidence ─────────────────────────────────

def mode_falsify() -> int:
    orig = KBJSON.read_bytes()
    before = _sha12(orig)
    print("改前 kb/kb.json sha12 = %s（%d 字节）" % (before, len(orig)))
    m = _LINE_EV.search(orig)
    if not m:
        print("✗ kb.json 里没有 `文件:行号` 形状的 evidence ⇒ 本对照证不了，先查载荷形状")
        return 2
    victim = m.group(0)
    broken = victim.replace((":%s" % m.group(3).decode()).encode(), b":100000")
    print("改坏目标：%s = %s:%s → :100000"
          % (m.group(1).decode(), m.group(2).decode(), m.group(3).decode()))

    BAK.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KBJSON, BAK)
    ok = True
    try:
        tmp = KBJSON.with_suffix(".json.tmp")
        tmp.write_bytes(orig.replace(victim, broken, 1))
        os.replace(tmp, KBJSON)

        rc_gate, _ = _child(["kb/gate.py"])
        rc_c4, out_c4 = _child(["-m", "backend.checks.kg_citation"])
        print("\n── 改坏之后 ──\nkb/gate.py 退出码 %s\nC4 单跑 退出码 %s" % (rc_gate, rc_c4))
        for line in out_c4.splitlines():
            if line.strip():
                print("    " + line.strip()[:190])
        if rc_gate == 0:
            print("✗ 门禁自己没红")
            ok = False
        if rc_c4 == 0:
            print("✗ C4 仍然绿 ⇒ 图谱红了而 C4 说没事")
            ok = False
        else:
            print("✓ C4 跟着红了")

        print("\n── 总表（runner.py --all）──")
        t0 = time.time()
        rc_fleet, out_fleet = _child(["backend/checks/runner.py", "--all", "--json"])
        try:
            fleet = json.loads(out_fleet[out_fleet.index("{"):out_fleet.rindex("}") + 1])
        except (ValueError, IndexError) as ex:
            print("✗ 总表输出读不出 JSON：%s" % ex)
            fleet = None
        if fleet:
            rows = [f for f in fleet["findings"] if f["check"].startswith("C4")]
            print("退出码 %s（%.1fs）verdict=%s 计数=%s" % (rc_fleet, time.time() - t0,
                                                          fleet["verdict"],
                                                          json.dumps(fleet["counts"], ensure_ascii=False)))
            for f in rows:
                print("   %-16s %-8s %s" % (f["check"], f["status"], f["detail"][:110]))
            if len(rows) != 2:
                print("✗ 总表里 C4 不是 2 行：%d" % len(rows))
                ok = False
            elif not any(f["status"] == "gap" for f in rows):
                print("✗ 总表里 C4 两行都没红 ⇒ 改坏没进总表")
                ok = False
            else:
                print("✓ 总表里 C4 翻了红")
            # ★ 「退出码非 0」这条判据在本仓**已经恒为 1**（38 条与 C4 无关的老 GAP），
            #   所以它证明不了 C4。诚实的形式是「那一行 pass→gap」，上面已断言。
            if rc_fleet == 0:
                print("（注：总表退出码 0 —— 说明本仓当前没有别的红）")
    finally:
        KBJSON.write_bytes(orig)

    again = KBJSON.read_bytes()
    print("\n── 还原之后 ──\ncmp：%s   sha12 %s → %s"
          % ("逐字节相同" if again == orig else "★ 不同 ★", before, _sha12(again)))
    if again != orig:
        print("✗ 没还原成原样 —— 从 %s 拷回去" % BAK)
        return 1
    rc2, out2 = _child(["-m", "backend.checks.kg_citation"])
    print("C4 单跑 退出码 %s" % rc2)
    if rc2 != 0:
        print("✗ 还原之后 C4 还红 ⇒ 判据咬住不放（假红）")
        ok = False
    else:
        print("✓ 还原之后回绿 —— 两个方向都验过")
    # ★ 改坏窗口里那次 `runner --all` 会把**红快照**写进 data/_meta/checks/fleet.json。
    #   不重出的话，盘上躺着一份"C4 是 gap"的旧产物，下次读的人会以为现在就是红的。
    rc3, _ = _child(["backend/checks/runner.py", "--all", "--json"])
    print("重出总表快照：退出码 %s（把上面那次红快照覆盖回当前状态）" % rc3)
    print("\n%s  备份留在 %s（kb.json 是构建产物，随时 `python -u kb/build_kb.py` 重出）"
          % ("★ 通过" if ok else "★ 不通过", BAK))
    return 0 if ok else 1


_MODES = {"--diff": mode_diff, "--falsify": mode_falsify}


def main(argv: list[str]) -> int:
    for a in argv:
        if a not in _MODES:
            print("只认 %s（本仓不认 --help，见铁律 9）" % "、".join(sorted(_MODES)),
                  file=sys.stderr)
            return 2
    bad = 0
    for a in argv:
        print("=" * 70 + "\n%s\n" % a)
        bad += 0 if _MODES[a]() == 0 else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["--diff"]))
