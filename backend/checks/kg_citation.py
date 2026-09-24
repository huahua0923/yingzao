# -*- coding: utf-8 -*-
"""C4 图谱引用可核 —— 把 `kb/gate.py` 与 `kb/derive.py` 挂进系统检查。

## 这一条补的是哪条缝

A/B 层逐栋问几何，C0–C3 问账本、口径、龄期、名册。**没有一条问「知识图谱自己的边还对不对」**：
`kb/` 里 99 条边逐条指着 `文件:行` 或 `文件:符号`，源文件一改，指着的那句话就可能换了
—— 而这件事没有任何逐栋判据看得见（图纸全对、台账全对、图谱全错）。所以 C4 只做一件事：
**去跑图谱自己的门禁，把它的结论翻译成一条 Finding。**

## 为什么是一个独立文件而不是塞进 system.py

一件事一个文件（用户明令）。C4 的量具在 `kb/`（另一套目录、另一套自检），
system.py 只管 A/C 引擎自己的判据 —— 混在一起以后，"哪把尺子在量"又要靠人记。

## 「没跑成」与「跑成了且红」必须分开

本仓反复栽的那一族。所以这里**四个结局各有独立分支**，不许合并：

    exit 0 ＋ 能解析          ⇒ PASS
    exit≠0 ＋ 能解析有失败项  ⇒ GAP（把失败项逐条列出来）
    exit≠0 ＋ **没有失败项**  ⇒ UNAVAILABLE（★量具自己坏了：非 0 却报不出红在哪，
                                这种"红得没有理由"比红更糟，它不可下手）
    起不来／超时／输出不是 JSON ⇒ UNAVAILABLE（★不是 PASS）

## 两处编码陷阱（2026-09-24 实测，写在这里免得下次重踩）

  · `kb/gate.py` 曾**不重设 stdout**，在 Windows 的 GBK 管道下打印「④ 值漂移（阈值表 ↔ 代码）」
    时自己抛 `UnicodeEncodeError` 并以退出码 1 结束 ⇒ 调用方把**量具被环境噎住**读成
    「图谱红了」。已修（三处脚本 gate/values/build_kb 都补了 reconfigure）。
  · 本文件仍然**两头都设**：子进程 env 里显式给 `PYTHONIOENCODING=utf-8`，父进程按 utf-8 解。
    「一头对一头错」正是 trap-decoding-mojibake-eats-structure 的成因 ——
    报出来的错长在被测对象身上，而它其实长在管道上。

用法：

    python -m backend.checks.kg_citation --selftest     # 自检：四个结局各配一条对照
    python -m backend.checks.kg_citation                # 单独跑这一条（调试用）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .findings import Finding, Status

#: 手写版本号：改了"复核哪几条 / 怎么算不合格"才 +1（铁律 24）。
#: 与机械指纹（本文件 sha12）并存 —— 手写的会忘，机械的说不清语义。
CRITERION_VERSION = 1

_TIMEOUT_S = 300
#: `--run` 只读白名单那条纪律同样适用于这里：只跑**只读**的两个入口。
#: 新增命令要过 `kb/gate.py` 的 ⑦（写操作黑名单）之后才有资格出现在这里。
_GATE = ("kb/gate.py", "--json")
_DERIVE = ("kb/derive.py", "--check")

_NOTFOUND = "NOTFOUND"
_TIMEOUT = "TIMEOUT"


def repo_root() -> Path:
    """仓库根 —— 从 backend/paths.py 取，不在这里自己数 `..`（数错就是静默错路径）。"""
    from backend.paths import ROOT
    return Path(ROOT)


def _run(rel_argv: tuple[str, ...]) -> tuple[object, str]:
    """跑一条只读入口，回 (退出码 | NOTFOUND | TIMEOUT, 字节解码后的输出)。

    ★ 不用 shell（命令是本文件写死的常量，但这是全仓纪律，不开口子）；
    ★ 子进程 env 里显式给 utf-8；★ 起不来与跑不完各有独立哨兵，不与退出码 0 混。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"          # 两头都设：本文件按 utf-8 解，见模块头
    argv = [sys.executable, "-u"] + list(rel_argv)
    try:
        p = subprocess.run(argv, cwd=str(repo_root()), env=env, timeout=_TIMEOUT_S,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as ex:
        return _NOTFOUND, "命令起不来：%s" % ex
    except subprocess.TimeoutExpired:
        return _TIMEOUT, "超过 %d 秒未返回（★既可能是慢，也可能是它根本没在跑）" % _TIMEOUT_S
    blob = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    return p.returncode, (blob if blob.strip() else err)


def sub_status(sec) -> dict:
    """从一个「带 status 的小节」里取出**状态本身**。

    ★ 写成函数而不是在调用处 `len(...)`：那几个小节是 dict，
      `len(dict)` 数的是**键的个数** —— 屏幕上和真读数长得一样，而它什么也没量。
      （实测踩过：`len({"status","rows","compared","detail"})` = 4，
      被我读成「陈旧 4 处」。）
    ★ 「整节不见」与「那节说没查成」是**两回事**，所以 `present` 单列：
      · 节在、status 是 pass/gap          → 这节真的判过了
      · 节在、status 是别的（unavailable…）→ 判了但没量成 ⇒ 不许读成合格
      · 节根本不在（形状换过）             → 判据跟不上了 ⇒ 也不许读成合格
      合并成一句的坏处：报出来的原因会指错地方，而"指错地方"比不报更难查。
    """
    if not isinstance(sec, dict):
        return {"present": False, "status": None, "compared": None,
                "detail": "形状不是 dict：%s" % type(sec).__name__}
    return {"present": "status" in sec, "status": sec.get("status"),
            "compared": sec.get("compared"), "detail": (sec.get("detail") or "")[:200]}


def verdict_of(code, blob: str, label: str) -> tuple[Status, dict, str]:
    """纯函数：(退出码, 输出) → (状态, 证据, 一句话说明)。**自检就喂这个函数**，
    不去动仓库里的真文件 —— 但四个结局一个不少。"""
    if code in (_NOTFOUND, _TIMEOUT):
        return (Status.UNAVAILABLE, {"exit": code, "label": label},
                "%s 没跑成：%s ⇒ **这不是「没问题」**" % (label, blob[:200]))
    try:
        doc = json.loads(blob)
    except ValueError as ex:
        return (Status.UNAVAILABLE, {"exit": code, "label": label, "parse_error": str(ex)},
                "%s 的输出不是合法 JSON（%s）⇒ 读不出来，只能报「没量成」。"
                "★实测：这条曾经**只在红的时候**出现 —— 人机混排的提示行跟着 JSON 一起打到 "
                "stdout，消费方于是把「真有问题」读成「输出坏了」" % (label, ex))
    if not isinstance(doc, dict) or "fails" not in doc:
        return (Status.UNAVAILABLE, {"exit": code, "label": label, "keys": sorted(doc)[:12]},
                "%s 的 JSON 里没有 `fails` 字段（顶层键 %s）⇒ 产物换过形状了，本判据跟不上"
                % (label, "、".join(sorted(doc)[:12])))

    fails = doc.get("fails") or []
    traps = doc.get("traps") or {}
    pb = doc.get("playbook") or {}
    # ★ 这四个小节是**带 status 的 dict**，不是列表 —— 第一版我写 `len(...)`，
    #   量出来的是**键的个数**（stale 4 个键 → 报「陈旧 4」、dual 3 个键 → 「双源 3」）。
    #   屏幕上它长得跟一个真读数一模一样。**要状态就读状态，绝不数键。**
    subs = {k: sub_status(doc.get(k)) for k in ("stale", "dual", "value")}
    ev = {"exit": code, "label": label, "fails": fails[:12], "n_fails": len(fails),
          # ★ 边数必须进证据：只留 `n_fails` 的话，一份全绿的证词长这样
          #   `{"n_fails": 0, "edges": 0}` —— 「99 条边全核过」和「一条边都没核」
          #   在证据里长得一模一样（铁律 16 那一族）。
          "n_edges": len(doc.get("edges") or []),
          "subs": subs,
          "traps": {"present": traps.get("present"), "nodes": traps.get("nodes"),
                    "case_edges": traps.get("case_edges"),
                    "related_edges": traps.get("related_edges"),
                    "n_bare": len(traps.get("bare") or [])},
          "playbook": {"present": pb.get("present"), "families": pb.get("families"),
                       "edges": pb.get("edges"), "n_bare": len(pb.get("bare") or []),
                       "n_declared": len(pb.get("declared") or [])},
          "cmds": {"n": len(doc.get("cmds") or []),
                   "n_rejected": sum(1 for c in (doc.get("cmds") or []) if not c[1])},
          "ruler": {"gate_sha12": doc.get("self_sha12"),
                    "values_sha12": doc.get("values_sha12"),
                    "criterion_version": doc.get("criterion_version"),
                    "criterion_version_here": CRITERION_VERSION}}

    # ★ 「没查成」不许变成绿 —— 门禁的 `_fails` 只把 `gap` 收进失败项，
    #   所以一个小节若报出 pass/gap 以外的状态（例如某份依赖读不出来 → unavailable），
    #   **退出码仍会是 0、fails 仍是空**，读起来跟"全查过且全对"一模一样。
    #   这一道闸由 C4 把关，不改门禁（门禁负责判，C4 负责保证"判过了"是真的）。
    absent = [k for k, s in subs.items() if not s["present"]]
    not_measured = [k for k, s in subs.items() if s["present"] and s["status"] not in ("pass", "gap")]
    if (absent or not_measured) and not fails:
        return Status.UNAVAILABLE, ev, (
            "%s：%s%s ⇒ **不许把这读成合格**。判据没跑成的样子，"
            "和判据全过的样子就在同一行字上"
            % (label,
               "缺了这几节（产物形状换过，本判据跟不上）：%s；" % "、".join(absent)
               if absent else "",
               "报了「没查成」：%s" % "、".join("%s=%s" % (k, subs[k]["status"])
                                                for k in not_measured)
               if not_measured else ""))
    if not traps.get("present"):
        return Status.UNAVAILABLE, ev, (
            "%s：陷阱这一类**一次都没查过**（traps.json 不在盘上）⇒ 不是「没有陷阱」" % label)
    if not pb.get("present"):
        return Status.UNAVAILABLE, ev, (
            "%s：手册（症状→根因→处置）**状态未知** —— kb.json 里没有 playbook 这一节，"
            "先跑 `python -u kb/build_kb.py`" % label)

    if code == 0 and not fails:
        return Status.PASS, ev, (
            "%s：%d 条边全部核过；④值漂移 %s/%s、⑤双源 %s/%s、⑥陈旧 %s/%s（分子=比过的项）；"
            "陷阱 登记 %s 条（可核 %s＋%s，只有人记着 %s）；手册 %s 个家族（声明无锚点 %s，"
            "缺 evidence %s）；⑦命令 %s 条（拒登 %s）"
            % (label, ev["n_edges"],
               subs["value"]["status"], subs["value"]["compared"],
               subs["dual"]["status"], subs["dual"]["compared"],
               subs["stale"]["status"], subs["stale"]["compared"],
               ev["traps"]["nodes"], ev["traps"]["case_edges"], ev["traps"]["related_edges"],
               ev["traps"]["n_bare"], ev["playbook"]["families"],
               ev["playbook"]["n_declared"], ev["playbook"]["n_bare"],
               ev["cmds"]["n"], ev["cmds"]["n_rejected"]))
    if fails:
        head = "；".join(str(f)[:160] for f in fails[:4])
        return Status.GAP, ev, ("%s：%d 处红 ⇒ %s%s"
                                % (label, len(fails), head,
                                   "…" if len(fails) > 4 else ""))
    # ★ 非 0 却报不出失败项：量具自己坏了。这一档必须单独站着 ——
    #   「红得没有理由」不可下手，而它和「红得有理有据」在退出码上一模一样。
    return (Status.UNAVAILABLE, ev,
            "%s 退出码 %s 却一条失败项都没报 ⇒ **量具自身异常**，本判据不替它宣布合格也不要"
            "一个没有理由的红" % (label, code))


def instance_ruler() -> dict:
    """读实例层产物**自己写的**尺子指纹 —— 不去猜、不去重算。

    ★ 这里有一个刻意的选择：**即使 `--check` 报「陈旧」，也照读这份产物上的指纹**。
      因为要回答的问题正是「那份过期的数是哪把尺子量的」—— 读现算的指纹会答错题。
    """
    p = repo_root() / "data" / "_meta" / "kg_instances.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        return {"readable": False, "why": "%s: %s" % (type(ex).__name__, ex)}
    gf = doc.get("generated_from") or {}
    return {"readable": True, "self_sha12": doc.get("self_sha12"),
            "criterion_version": doc.get("criterion_version"),
            "src_sha": (gf.get("src_sha") or {}) if isinstance(gf.get("src_sha"), dict)
            else {"src_sha": gf.get("src_sha")},
            "universe": (doc.get("universe") or {}).get("n"),
            "totals": doc.get("totals")}


def check_c4(rep, data_dir, state=None) -> None:
    """C4：图谱的边还指着原处吗 ＋ 实例层是不是对着当前源派生的。

    `state` 不用（C4 不参与账本口径比较，只读图谱自己的产物）。
    """
    code, blob = _run(_GATE)
    st, ev, detail = verdict_of(code, blob, "图纸知识图谱的边（kb/gate.py）")
    rep.add(Finding(check="C4.edges", title="图谱引用可核（路径/行号/符号/值/双源/陈旧）",
                    status=st, detail=detail, evidence=ev,
                    measure="边（=文件:行 或 文件:符号 的引用）",
                    blocked_by=(detail if st == Status.UNAVAILABLE else "")))

    code2, blob2 = _run(_DERIVE)
    tail = blob2.strip().splitlines()[-1][:200] if blob2.strip() else ""
    ev2 = {"exit": code2, "check_out": tail, "ruler": instance_ruler()}
    ruler = ev2["ruler"]
    if code2 in (_NOTFOUND, _TIMEOUT):
        st2, detail2 = Status.UNAVAILABLE, (
            "实例层新鲜度没量成：%s ⇒ **这不是「实例是新的」**" % blob2[:160])
    elif code2 != 0:
        st2, detail2 = Status.GAP, (
            "★实例层是**旧尺子量的快照**：%s —— 源改过而没重跑 `kb/derive.py`，"
            "此时问图谱「c057 哪些层错位」拿到的是过期的楼栋·层"
            "（这份产物自称 self=%s，源指纹 %s）"
            % (tail, ruler.get("self_sha12"),
               json.dumps(ruler.get("src_sha"), ensure_ascii=False)[:160]))
    elif not tail or not ruler.get("readable"):
        # ★ 「命令跑成功了」和「它什么也没做」是同一行字（铁律 17）。
        #   exit 0 但一个字没打、或产物读不出来 ⇒ 没量成，不许给绿灯。
        st2, detail2 = Status.UNAVAILABLE, (
            "`derive.py --check` 退出码 0 却%s ⇒ 只能报「没量成」"
            % ("一个字都没打" if not tail else "产物读不出来：%s" % ruler.get("why")))
    else:
        st2, detail2 = Status.PASS, (
            "实例层与当前源逐条计数相同：%s（尺子 self=%s，源指纹 %d 项）"
            % (tail, ruler.get("self_sha12"), len(ruler.get("src_sha") or {})))
    rep.add(Finding(check="C4.instances", title="图谱实例层（机器派生的楼栋·层）是否对着当前源",
                    status=st2, detail=detail2, evidence=ev2,
                    measure="派生实例（楼栋·层的观察行）",
                    blocked_by=(detail2 if st2 == Status.UNAVAILABLE else "")))


# ── 自检：四个结局各一条对照，另加一条阴性对照 ──────────────

def _payload(**over) -> str:
    """造一份**与盘上真产物同形状**的门禁载荷。

    ★ 夹具的不是真形状，证的就是夹具那条链（memory: fixture-shape-must-copy-real-artifact）。
      第一版我造的假载荷里根本没有 `stale`/`dual`/`value`/`playbook` 这几节，
      于是"全绿"那条对照走的是**另一条分支**（被新加的"没查成"闸门拦下）。
      下面这份形状是照着 `kb/gate.py --json` 的实测输出抄的（键名、嵌套、字段类型）。
    """
    doc = {
        "edges": [{"status": "pass"}] * 99, "fails": [],
        "stale": {"status": "pass", "rows": [], "compared": 29, "detail": "29 个证据文件都比过"},
        "dual": {"status": "pass", "compared": 4, "detail": "4 个前缀逐键相等"},
        "value": {"status": "pass", "total": 44, "compared": 33, "counts": {"MATCH": 33},
                  "detail": "33/44 比过"},
        "traps": {"present": True, "nodes": 13, "case_edges": 16, "related_edges": 14,
                  "bare": [{"slug": "x"}]},
        "playbook": {"present": True, "families": 4, "edges": 36, "bare": [],
                     "declared": [{"slug": "y"}]},
        "cmds": [["python -u kb/ask.py x", True, "", "kb/playbook.json"]],
        "self_sha12": "abc", "values_sha12": "def", "criterion_version": 1,
    }
    doc.update(over)
    return json.dumps(doc, ensure_ascii=False)


def selftest() -> int:
    """★ 每条对照都要求**红在正确的分支上** —— 只要求"不是 PASS"的话，
    把 GAP 与 UNAVAILABLE 合并也能全绿，而那正是本文件最不该出的错。"""
    cases = [
        ("全绿", 0, _payload(), Status.PASS, "全部核过"),
        ("红且报得出红在哪", 1, _payload(fails=["边 kb/x.md:12：只有 385 行，边却指第 3300 行"]),
         Status.GAP, "第 3300 行"),
        # ★ 下面三条是「没查成不许变成绿」：门禁的 `_fails` 只收 gap，
        #   所以这几档在门禁那侧**退出码 0、fails 空**，与"全过"同形。
        ("④值漂移报 unavailable 而 fails 空", 0,
         _payload(value={"status": "unavailable", "detail": "values.py 导入失败"}),
         Status.UNAVAILABLE, "不许把这读成合格"),
        ("traps.json 不在盘上（这一类一次都没查过）", 0,
         _payload(traps={"present": False, "nodes": 0, "case_edges": 0,
                         "related_edges": 0, "bare": []}),
         Status.UNAVAILABLE, "一次都没查过"),
        ("kb.json 里没有 playbook 那一节", 0, _payload(playbook={"present": False}),
         Status.UNAVAILABLE, "状态未知"),
        # ★ 这一条要用**完整形状**的载荷去喂：四节都在、都报 pass，唯独退出码非 0
        #   且 fails 空。这才是「红得没有理由」——
        #   拿一份 `{"fails": []}` 去喂只会命中"形状换过"那条分支，证不到这一档。
        ("非 0 却报不出失败项 ⇒ 量具自身异常", 1, _payload(),
         Status.UNAVAILABLE, "量具自身异常"),
        ("载荷残缺（连小节都没有）⇒ 跟不上，不是合格", 1, json.dumps({"fails": []}),
         Status.UNAVAILABLE, "缺了这几节"),
        ("输出不是 JSON（人机混排的典型症状）", 0, "退出码=1：1 处待处理", Status.UNAVAILABLE,
         "不是合法 JSON"),
        ("起不来", _NOTFOUND, "", Status.UNAVAILABLE, "没跑成"),
        ("超时", _TIMEOUT, "", Status.UNAVAILABLE, "没跑成"),
        ("JSON 形状换过（没有 fails 字段）", 0, json.dumps({"edges": []}),
         Status.UNAVAILABLE, "没有 `fails` 字段"),
        ("小节形状换过（stale 成了列表）", 0, _payload(stale=["a", "b"]),
         Status.UNAVAILABLE, "不许把这读成合格"),
        ("阴性对照：真跑一次绿的，不许凭空红", None, None, Status.PASS, "全部核过"),
    ]
    bad = 0
    for label, code, blob, want, must_say in cases:
        if code is None:
            code, blob = _run(_GATE)
            if code != 0:
                print("  ✗ 阴性对照：真跑 kb/gate.py 退出码 %s（应当 0）—— "
                      "先把门禁修绿，本自检的前提才成立" % code)
                bad += 1
                continue
        st, ev, detail = verdict_of(code, blob, "探针")
        ok = st == want and must_say in detail
        # ★ 顺带钉住"证词里必须有边数"：否则一份全绿的证词可能是"一条边都没核"。
        if want == Status.PASS and not ev.get("n_edges"):
            ok = False
        print("  %s %s（要 %s 且说明里含 %r，实得 %s）"
              % ("✓" if ok else "✗", label, want.value, must_say, st.value))
        bad += 0 if ok else 1
    if bad:
        print("--selftest 红：%d 条对照没验成" % bad)
        return 1
    print("--selftest 绿：%d 条对照（四个结局各一条 ＋ 三种「没查成」＋ 形状换过两处 "
          "＋ 真跑一次阴性对照）；criterion_version=%d" % (len(cases), CRITERION_VERSION))
    return 0


def main(argv) -> int:
    """调试用入口。★本仓不认 `--help`（铁律 9）：不认识的 `-` 开头一律硬错，
    绝不"当没看见按默认跑"—— 默认跑的是全量。"""
    for a in argv:
        if a.startswith("-") and a != "--selftest":
            print("不认识的参数：%s（本仓只认 --selftest；不认 --help）" % a, file=sys.stderr)
            return 2
    if "--selftest" in argv:
        return selftest()

    from .findings import Report
    rep = Report(scope="kg")
    check_c4(rep, None)
    bad = 0
    for f in rep.findings:
        print("%-11s %s\n            %s" % (f.status.value.upper(), f.title, f.detail))
        bad += 0 if f.status == Status.PASS else 1
    print("（%d 条，非 PASS %d 条；criterion_version=%d）"
          % (len(rep.findings), bad, CRITERION_VERSION))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
