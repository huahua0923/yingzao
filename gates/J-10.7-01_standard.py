# -*- coding: utf-8 -*-
"""判据 J-10.7-01 —— 标准绑定（出口门：往交付件上引的每一条标准，必须由**正本自己**证实）。

判据（§10.7「绑标准 · 用起来」）：
  ① `规范/标准绑定.json` 里每一条「已核」条款，其**核验词**必须出现在**正本 PDF 的标称页**；
  ② 同一次运行顺带渲染 `规范/标准绑定.md`（数字只住 JSON，人读版由机器出）。
量具（写明）：tools/standard_bind.py verify()；单位 = **对不上的条款数**；阈值 = 0（全命中）。
量具盲区（声明）：
  · 只证「**核验词**出现在**标称页**」；**不证**我对该句的**解读与套用判定**正确 —— 套用是人的判断。
  · 核验词是**每条款抽样一个**（非逐字比对全文）⇒ 能抓「页码/词址写错」，抓不到「同页另一句我不认」。
  · 只对 `已核==true` 的条款判；`未核` / `方向引用` 一律**不判**（不臆造页码）。
正对照（必配，每一条都必须按预期变红）：
  · C1 真绑定 ⇒ **放行**（10 条已核全命中，对不上 0）；
  · C2 把 4.2.3 的页改错（8→1，封面）⇒ **必红**；
  · C3 把 4.2.1 的核验词改成不存在的串 ⇒ **必红**；
  · C4 页号越界（4.3 页 9→9999）⇒ **必红**；
  · C5 正本文件指向不存在 ⇒ **必红**；
  · C6 条款引一个不存在的正本 id ⇒ **必红**；
  · C7 只验已核：把 4.4 的 已核 改 false ⇒ **不红、且已核计数 −1**（证明未核条不进判据）。
  · C8 高度精度 4.2.3 **数值闸有分辨力**：喂 (39.72, 47.57) ⇒ **必 FAIL**；喂 (44.0, 44.5) ⇒ **必 PASS**。
  八条里**任一条不按预期** ⇒ 判据没分辨力，作废。
三态：OK / FAIL / SKIP（前置缺件·正本不在 · 跑不动）。SKIP 不算过、也不假报成 FAIL。
"""
from __future__ import annotations

import copy
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, r"D:\项目\cdut3d\tools")
import standard_bind as SB  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "_out")
JSON_OUT = os.path.join(HERE, "_out", "J-10.7-01.json")
JSON = os.path.join(SB.SPEC, "标准绑定.json")
_LOG = []

# ★ 本闸自己**真正量到**的读数，逐格写入，最后统一落 json；不许编数 —— 没量到的格不写。
_RESULT = {}
# ★ 盲区：抄 docstring 里已声明的那三条（不另加、也不删）。
BLIND = [
    "只证「核验词出现在标称页」；不证我对该句的解读与套用判定正确——套用是人的判断",
    "核验词是每条款抽样一个（非逐字比对全文）⇒ 抓不到「同页另一句我不认」",
    "只对 已核==true 的条款判；未核 / 方向引用 一律不判（不臆造页码）",
]


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def n_bad_of(bind):
    _rows, checked, bad, docs = SB.verify(bind)
    for d in docs.values():
        d.close()
    return checked, bad


def main():
    if not os.path.exists(JSON):
        log("SKIP：绑定文件不在 %s" % JSON)
        return _finish(4)
    bind = SB.load(JSON)
    ok = True

    # ---- C1 真绑定 ⇒ 放行 ----
    checked, bad = n_bad_of(bind)
    log("C1 真绑定：已核 %d 条，对不上 %d 条 ⇒ %s" % (checked, bad, "放行" if bad == 0 else "★红了"))
    if checked == 0:
        log("★ 没量到：一条已核都没有")
        return _finish(4)
    ok = ok and bad == 0
    # ★ 本闸真正量到的读数（C1 这一路）
    _RESULT["checked"] = checked                          # 已核条款数
    _RESULT["bad"] = bad                                  # 对不上的条款数（本闸的量，阈 0）
    _RESULT["unchecked"] = len(bind["条款"]) - checked     # 未核条款数
    _RESULT["directional"] = len(bind.get("未核_方向引用", []))

    cases = []

    def mut(name, fn, expect_bad=True):
        b = copy.deepcopy(bind)
        fn(b)
        cases.append((name, b, expect_bad))

    # C2 错页：4.2.3 8 → 1
    def c2(b):
        next(c for c in b["条款"] if c["id"] == "SJZ3W-12/4.2.3")["pdf页"] = 1
    mut("C2 错页(4.2.3 页8→1)", c2)

    # C3 错词：4.2.1 核验词改不存在
    def c3(b):
        next(c for c in b["条款"] if c["id"] == "SJZ3W-12/4.2.1")["核验词"] = "ZZZ本页绝无此词ZZZ"
    mut("C3 错词(4.2.1 核验词改假)", c3)

    # C4 页越界：4.3 9 → 9999
    def c4(b):
        next(c for c in b["条款"] if c["id"] == "SJZ3W-12/4.3")["pdf页"] = 9999
    mut("C4 页越界(4.3 页9→9999)", c4)

    # C5 正本文件不存在
    def c5(b):
        b["正本"][0]["文件"] = "过程/_scratch/_std/不存在.pdf"
    mut("C5 正本文件不在", c5)

    # C6 条款引不存在的正本 id
    def c6(b):
        b["条款"][0]["正本"] = "NOPE-9999"
    mut("C6 正本 id 不存在", c6)

    log("\n---- 正对照（每一条都必须按预期变红）----")
    ctrl_fired = []                     # ★ 每条正对照「该红有没有红」的实测，进 json
    for name, b, expect_bad in cases:
        _chk, nb = n_bad_of(b)          # ★ 别叫 bad：它与 C1 的「真绑定对不上数」同名，
        fired = nb >= 1                 #   同名会让末行印出最后一次扰动( C6=1 )，看着像真绑定也有 1 条坏。
        ok = ok and fired
        ctrl_fired.append({"case": name, "fired": fired, "n_bad": nb})
        log("  %-24s → %s（对不上 %d 条）" % (name, "✔红" if fired else "★放行了", nb))
        if not fired:
            log("     ★该红没红")
    _RESULT["controls"] = ctrl_fired

    # C7 只验已核：4.4 置 false ⇒ 不红且计数 −1
    b7 = copy.deepcopy(bind)
    next(c for c in b7["条款"] if c["id"] == "SJZ3W-12/4.4")["已核"] = False
    c7_checked, c7_bad = n_bad_of(b7)
    fired7 = (c7_bad == 0) and (c7_checked == checked - 1)
    ok = ok and fired7
    _RESULT["c7_checked"] = c7_checked          # C7：4.4 置未核后的已核计数（应 = checked-1）
    log("  %-24s → %s（已核 %d→%d，对不上 %d）"
        % ("C7 未核不进判据(4.4)", "✔" if fired7 else "★", checked, c7_checked, c7_bad))

    # C8 高度闸的分辨力（喂两对数，一向一背）
    lo_fail = SB.check_height(bind, 39.72, 47.57)   # |Δ|=7.85 >3.0 ⇒ FAIL(1)
    hi_pass = SB.check_height(bind, 44.0, 44.5)     # |Δ|=0.5 ≤3.0 ⇒ PASS(0)
    fired8 = (lo_fail == 1 and hi_pass == 0)
    ok = ok and fired8
    _RESULT["c8_lo_rc"] = lo_fail               # C8：喂 (39.72,47.57) 高度闸的读数（应 1=FAIL）
    _RESULT["c8_hi_rc"] = hi_pass               # C8：喂 (44.0,44.5) 高度闸的读数（应 0=PASS）
    log("  %-24s → %s（7.85m 差 ⇒ rc=%d；0.5m 差 ⇒ rc=%d）"
        % ("C8 高度闸两向分辨", "✔" if fired8 else "★", lo_fail, hi_pass))

    log("\n已核 %d / 未核 %d / 方向引用 %d；对不上 %d 条"
        % (checked, len(bind["条款"]) - checked, len(bind.get("未核_方向引用", [])), bad))

    # 渲染人读版
    rows, _c, _b, docs = SB.verify(bind)
    for d in docs.values():
        d.close()
    SB.render_md(bind, rows, os.path.join(SB.SPEC, "标准绑定.md"))
    log("写 %s" % os.path.join(SB.SPEC, "标准绑定.md"))
    log("★ 盲区：只证「词在该页」，不证「套用判定对」——套用是人的判断，无自动判据。")

    log("\n===== 判词 =====")
    log("J-10.7-01 总判 :", "PASS" if ok else "FAIL")
    return _finish(0 if ok else 1)


def _write():
    os.makedirs(OUTDIR, exist_ok=True)
    with open(os.path.join(OUTDIR, "J-10.7-01.run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")


def _finish(rc):
    # ★ 所有 return 汇到这一个出口：退出码一字未改，只是顺手把第三路读数（json）补上。
    _write()
    _write_json(rc)
    return rc


def _write_json(rc):
    # ★ 为什么默认落盘、不加开关：台账页 demo/sys.html 靠 gates/_out/<编号>.json 的 `pass`
    #   取三路读数之一；本闸原先只落 run.txt ⇒ 那一路空。与 J-10.2-02 同口径、用 HERE 拼路径。
    os.makedirs(OUTDIR, exist_ok=True)
    doc = {"pass": rc == 0, "rc": rc}
    doc.update(_RESULT)          # ★ 只放真量到的读数；没量到的格不出现，不编数
    doc["blind"] = BLIND
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print("  写出:", JSON_OUT)


if __name__ == "__main__":
    sys.exit(main())
