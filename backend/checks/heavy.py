# -*- coding: utf-8 -*-
"""B 层检查 —— 要建模环境（ezdxf/shapely）与源 DXF，**逐栋起子进程**跑。

## 为什么是"调用"而不是"重写"

`qa_structural.py` 已经是一台成熟的不变量引擎（I1–I18 + `under_recognized`），
而且**用户明令不许改它**（"门禁是诚实的裁判，不许挪球门"）。所以这里一个字都不改
它，只做两件事：**调它**、**读它的报告**。判据只有一份实现
（memory: one-judgement-many-implementations）。

## 为什么必须逐栋隔离

全库跑曾在 c009 上被 `buffer(0)` 炸出的 MultiPolygon 抛异常**中断整轮**，于是
c009 之后的楼从来没被检查过，而汇总只报一句"崩在 c009"
（memory: qa-structural-fullrun-dies-at-c009）。逐栋起进程之后，c009 崩 →
它自己报 UNAVAILABLE，其余 94 栋照常出结论。

## 三件不许含糊的事

1. **报告必须是这一轮新写的**。同名的 `_qa/<楼>_qa.txt` 很可能是上一轮留下的，
   而"没有楼层"的楼**根本不写文件**（`main()` 里直接 continue）。若只看
   "文件在不在"，就会读到旧报告并给它一个绿灯
   （memory: resume-by-filename-stale-frames：按文件名认完成度会用旧帧）。
   所以比对运行前后的 mtime：没被重写 ⇒ UNAVAILABLE，**绝不读旧文件**。
   副作用要说明：本检查会覆写 `_qa/<楼>_qa.txt`（与全库跑同一份产物）。
2. **量的是不是同一棵树**。qa_structural 把 `BASE` 写死在源码里；这里从源码把它
   读出来，与本次要检查的 data_dir 对不上就报"量具指向别处"，**不静默照跑**
   —— 否则表面在检查 A 库、实际量的是 B 库，两边都不会报错
   （CLAUDE.md 铁律 16：量具坏了和被测对象是空的，在屏幕上长得一样）。
3. **欠识别不判 FAIL**。这是 qa_structural 自己的判定（`under_recognized`），
   本层**照抄它的结论，不重算**。
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

# 「本栋号段」的口径**只有一个定义处**（builtin.py：A9 与 B3 问的是同一件事）。
# 这里 import 它，不另抄一份 —— 抄一份的话只有一份会跟着规则走
# （memory: one-judgement-many-implementations）。
from .builtin import home_number_segment
from .findings import Finding, Report, Status, unavailable
from .layout import floor_files

SCRIPT_REL = "qa_structural.py"

# 报告行：`[WARN] I11 f2 门心压在墙里 37/39 道(门扇被墙吞) — 最低洞口残墙 15%  @(x, y)`
_LINE_RE = re.compile(
    r"^\[(?P<sev>ERROR|WARN|INFO)\]\s+(?P<inv>[A-Za-z0-9]+)\s+f(?P<floor>\d+)\s+"
    r"(?P<msg>.*?)(?:\s+@\((?P<x>-?[\d.]+),\s*(?P<y>-?[\d.]+)\))?$")
_HEADER_RE = re.compile(r"^结构体检\s+\S+\s+—\s+(?P<name>\S+)\s+\((?P<n>\d+)\s*层\)\s*$")
_BBOX_RE = re.compile(r"^\s+f(?P<floor>\d+)\s+bbox\s+.*?柱(?P<cols>\d+)\s+房(?P<rooms>\d+)\s*$")
# 汇总数据行：`c113      5      0     42  CAUTION`
_SUMMARY_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_-]+)\s+(?P<nf>\d+)\s+(?P<errs>\d+)\s+(?P<warns>\d+)\s+"
    r"(?P<st>PASS|CAUTION|FAIL|UNDER欠识别)\s*$")
_SRC_BASE_RE = re.compile(r'^BASE\s*=\s*r?["\'](?P<p>[^"\']+)["\']', re.M)
_SRC_QA_RE = re.compile(r'^QA_DIR\s*=\s*r?["\'](?P<p>[^"\']+)["\']', re.M)

# 欠识别标记：qa_structural 把 ERROR 降成 WARN 时会加这个前缀。
_UA_MARK = "(欠识别待重建)"

# 不变量 → 人话标题。**只用于显示**，权威文本是本条自带的 msg（跟着一起回给前端）。
# 这份表不会过期，因为 qa_structural.py 被用户明令冻结 —— 编号不会变。
# 表里没有的编号**照样上报**（标题原样用编号），不许因为"不认识"就把它丢掉。
_INV_TITLE = {
    "I1": "柱脚在自身轮廓/楼板内",
    "I2": "柱上下贯通",
    "I3": "房间外溢轮廓",
    "I4": "墙身伸出轮廓",
    "I5": "轮廓外空外扩带",
    "I6": "天井/中庭孔",
    "I7": "重复柱",
    "I8": "层间一致性",
    "I9": "墙线不规则",
    "I10": "柱在板外但在凸包内",
    "I11": "门洞宿主登记",
    "I17": "楼梯井",
    "I18": "逐层堆叠",
    "UA": "欠识别待重建",
}

_MAX_SAMPLES = 3          # 每条 (层, 不变量) 最多回几条样本，避免几百行灌满前端


def _script_path(data_dir) -> Path:
    return Path(data_dir).resolve().parent / SCRIPT_REL


def _hardcoded(src: str, rx) -> str | None:
    m = rx.search(src)
    return m.group("p") if m else None


def check_b1(rep: Report, data_dir, name: str, timeout_s: int = 600, **_kw) -> None:
    """结构不变量 I1–I18：起子进程跑 `qa_structural.py <楼>`，读回它的报告。"""
    title = "结构不变量 I1–I18（qa_structural）"
    script = _script_path(data_dir)
    if not script.is_file():
        rep.add(unavailable("B1", title, "找不到 %s" % script))
        return

    # ── 先确认它量的是同一棵树（见模块 docstring 第 2 条）──────────
    try:
        src = script.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        rep.add(unavailable("B1", title, "读不到脚本源码：%s" % ex))
        return
    hard_base = _hardcoded(src, _SRC_BASE_RE)
    qa_dir = _hardcoded(src, _SRC_QA_RE)
    if hard_base is None or qa_dir is None:
        rep.add(unavailable("B1", title,
                            "脚本里没找到 BASE/QA_DIR（格式变了）—— 不猜，如实报量不到"))
        return
    want = str(Path(data_dir).resolve() / "buildings")
    got = str(Path(hard_base).resolve())
    if os.path.normcase(want) != os.path.normcase(got):
        rep.add(unavailable("B1", title,
                            "量具指向别处：qa_structural.py 的 BASE 写死为 %s，"
                            "而本次要检查的是 %s —— 照跑就成了「在 A 库上量、报 B 库的数」"
                            % (got, want)))
        return

    report_p = Path(qa_dir) / ("%s_qa.txt" % name)
    before = _stamp(report_p)
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-u", str(script), name],
                           cwd=str(script.parent), timeout=timeout_s,
                           capture_output=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except subprocess.TimeoutExpired:
        rep.add(unavailable("B1", title,
                            "%d 秒没跑完就掐了。**这不等于它有问题**，只是这一轮没量成"
                            % timeout_s, measure="I1–I18 告警条数"))
        return
    except OSError as ex:
        rep.add(unavailable("B1", title, "起不了子进程：%s: %s" % (type(ex).__name__, ex)))
        return
    elapsed = round(time.time() - t0, 1)

    if p.returncode != 0:
        # 崩溃就是崩溃。c009 那类 `buffer(0)` 炸 MultiPolygon 会走到这里 ——
        # 而它现在只影响自己这一栋（这正是逐栋隔离要的效果）。
        rep.add(unavailable("B1", title,
                            "qa_structural 退出码 %d：%s"
                            % (p.returncode, _tail(p.stderr)),
                            measure="I1–I18 告警条数"))
        return

    after = _stamp(report_p)
    if after is None or after == before:
        # 没被重写。两种可能：这栋没有楼层（main 直接 continue，不写文件），
        # 或者写文件那步出了问题。**两种都不许回旧报告**。
        row = _summary_row(p.stdout, name)
        why = ("这台机器上它没写报告：%s" % row["st"] if row and row.get("st") == "no floors"
               else "跑完了却没重写 %s（本轮 before=%s after=%s）" % (report_p.name, before, after))
        rep.add(unavailable("B1", title, why + "；不读旧报告，如实报量不到",
                            measure="I1–I18 告警条数"))
        return

    try:
        text = report_p.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        rep.add(unavailable("B1", title, "报告写出来了却读不到：%s" % ex))
        return

    _emit(rep, name, title, text, p.stdout, report_p, elapsed)


# ── 报告 → Findings ─────────────────────────────────────────────

def _emit(rep: Report, name: str, title: str, text: str, stdout: str,
          report_p: Path, elapsed: float) -> None:
    head = _HEADER_RE.match(text.splitlines()[0] if text.splitlines() else "")
    groups: dict[tuple[int, str], list[dict]] = {}
    inv_order: list[str] = []
    clean = False
    ua = False
    header_floors = int(head.group("n")) if head else None
    # 报告里 header 写的楼名与本次要查的不一致 ⇒ 读到别人的报告了。这不是小事：
    # 文件名相同不代表内容是本栋（qa_structural 是按 name 拼路径的，但不排除
    # 目录里有人手工放错）。宁可报量不到，也不把别栋的结论挂到本栋头上。
    if head and head.group("name") != name:
        rep.add(unavailable("B1", title,
                            "报告里写的是 %s，而本次要查的是 %s —— 读串了，不采用"
                            % (head.group("name"), name)))
        return

    for line in text.splitlines():
        if line.startswith(("(无 ERROR/WARN)", "(无 ERROR")):
            clean = True
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        sev, inv = m.group("sev"), m.group("inv")
        msg = m.group("msg")
        if _UA_MARK in msg:
            ua = True
            msg = msg.replace(_UA_MARK, "").strip()
        if sev == "INFO":
            continue                      # 报告默认不写 INFO，真出现了也不是告警
        fl = int(m.group("floor"))
        groups.setdefault((fl, inv), []).append(
            {"severity": sev, "msg": msg,
             "pos": [float(m.group("x")), float(m.group("y"))] if m.group("x") else None})
        if inv not in inv_order:
            inv_order.append(inv)

    counts = {"ERROR": 0, "WARN": 0}
    for rows in groups.values():
        for r in rows:
            counts[r["severity"]] = counts.get(r["severity"], 0) + 1

    # 与脚本自己的汇总行对账：两把量具不一致时要说出来，不能挑一个信
    # （memory: criterion-invalidated-by-later-change 那类"两处数不一样"的坑）。
    row = _summary_row(stdout, name)
    xcheck = None
    if row and row.get("errs") is not None:
        if (row["errs"], row["warns"]) != (counts["ERROR"], counts["WARN"]):
            xcheck = {"report": {"error": counts["ERROR"], "warn": counts["WARN"]},
                      "summary_row": {"error": row["errs"], "warn": row["warns"]}}

    if not groups and not clean:
        rep.add(unavailable("B1", title,
                            "报告里既没有告警行、也没有『(无 ERROR/WARN)』一行 —— "
                            "多半是格式变了，不猜"))
        return

    # 逐层逐不变量 —— 这就是"每修一层就分析"要的粒度
    for (fl, inv), rows in sorted(groups.items()):
        n_err = sum(1 for r in rows if r["severity"] == "ERROR")
        n_warn = len(rows) - n_err
        label = _INV_TITLE.get(inv, inv)
        rep.add(Finding(
            check="B1", title="%s %s" % (inv, label),
            status=Status.GAP if n_err else Status.WATCH,
            floor=fl,
            detail="%s" % rows[0]["msg"] if len(rows) == 1
                   else "%s（同类共 %d 条）" % (rows[0]["msg"], len(rows)),
            measure="I1–I18 告警条数",
            evidence={"invariant": inv, "error": n_err, "warn": n_warn,
                      "samples": rows[:_MAX_SAMPLES],
                      "report": report_p.name,
                      "generated_unix": _stamp(report_p),
                      "elapsed_s": elapsed}))

    # 整栋结论一条
    if not groups:
        rep.add(Finding("B1", title, Status.PASS,
                        "qa_structural I1–I18 全过（%d 层）"
                        % (header_floors if header_floors is not None else 0),
                        floor=None, measure="I1–I18 告警条数",
                        evidence={"report": report_p.name,
                                  "generated_unix": _stamp(report_p),
                                  "elapsed_s": elapsed}))
    else:
        rep.add(Finding("B1", title,
                        Status.GAP if counts["ERROR"] else Status.WATCH,
                        ("欠识别待重建：%s 判它欠识别，其上 ERROR 已降级为 WARN，"
                         "本层照抄它的判定，不重算也不判 FAIL；" if ua else "")
                        + "ERROR %d / WARN %d，涉及 %d 层、%d 个不变量"
                        % (counts["ERROR"], counts["WARN"],
                           len({f for f, _ in groups}), len(inv_order)),
                        floor=None, measure="I1–I18 告警条数",
                        evidence={"error": counts["ERROR"], "warn": counts["WARN"],
                                  "invariants": inv_order, "under_recognized": ua,
                                  "report": report_p.name,
                                  "generated_unix": _stamp(report_p),
                                  "elapsed_s": elapsed,
                                  **({"xcheck": xcheck} if xcheck else {})}))

    if xcheck:
        rep.add(Finding("B1", "报告与汇总口径不一致", Status.WATCH,
                        "报告文件数 ERROR %d/WARN %d，脚本汇总行数 ERROR %d/WARN %d —— "
                        "两把量具不一致，先别信结论"
                        % (xcheck["report"]["error"], xcheck["report"]["warn"],
                           xcheck["summary_row"]["error"], xcheck["summary_row"]["warn"]),
                        measure="I1–I18 告警条数", evidence=xcheck))


def _stamp(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def _summary_row(stdout: str, name: str) -> dict | None:
    """从脚本的控制台汇总里取本栋那一行。

    只在**同一次运行**里，取的名字要与本次一致：这就是"是不是同一棵树的同一栋楼"
    的第二道确认。没有这一行（格式变了、或这栋无 floors）→ 回 None。
    """
    for line in (stdout or "").splitlines():
        m = _SUMMARY_RE.match(line.strip())
        if m:
            if m.group("name") != name:
                continue
            return {"nf": int(m.group("nf")), "errs": int(m.group("errs")),
                    "warns": int(m.group("warns")), "st": m.group("st")}
        if name in line and "无 floors" in line:
            return {"st": "no floors", "errs": None, "warns": None}
    return None


def _tail(s: str, n: int = 800) -> str:
    s = (s or "").strip()
    return s[-n:] if len(s) > n else s


# ── B2 轮廓环有效性（shapely 是参考实现）────────────────────────────

def check_b2(rep: Report, data_dir, name: str, **_kw) -> None:
    """逐层交付轮廓环是不是**有效简单多边形**。

    ## 为什么这条值得单列

    c009 的 f0 轮廓是 invalid 的（`Ring Self-intersection[14.998 23.488]`），
    `buffer(0)` 一修就变成 **MultiPolygon**，于是冻结的门禁 `qa_structural.py`
    在第 144 行 `o.exterior` 上抛 AttributeError —— **整栋楼没有任何结构门禁**。
    今天实测：`_qa/c009_qa.txt` 停在 2026-09-15，就是那次崩掉留下的。
    这是真缺陷，只不过原来是以"崩溃"的形态出现的（memory:
    qa-structural-fullrun-dies-at-c009）。

    ## 为什么必须用 shapely，不许自己写一个判自交的算法

    ★ 我先写过一个纯标准库版本，**然后用 shapely 当参考实现校准它**，结论是
    这把尺子两头都错（24 个样本实测）：

      · **漏**：c009 f0 明明 invalid，我的版本说"没有自交" —— 恰恰漏掉会崩的那个；
      · **假红**：9 例 shapely 判有效、我的版本报自交（c113 f1–f4、c001 f3、
        c015 f2、c009 f1）。机理已查明：环是**闭合写法**（首点==末点），
        末段长度为零，于是"首段 vs 倒数第二段"共享首点，我的方向判据把
        共端点当成了相交。

    这类"自己推一个几何判据"在本项目栽过不止一次（memory:
    proxy-geometry-false-defects 假几何报假缺陷）。所以这一条**只做参考实现的
    调用者**；没有 shapely 就如实报 UNAVAILABLE，绝不退回自制判据。

    判据分档：
      · 有效                              → PASS
      · invalid，但 `buffer(0)` 仍是 Polygon → WATCH（几何不干净，面积/包含类判据
        不可信；门禁当前能跑过去，别当成没事）
      · invalid 且 `buffer(0)` 给出 MultiPolygon/集合 → GAP：门禁整栋跑不了
    """
    try:
        from shapely.geometry import Polygon
        from shapely.validation import explain_validity
    except ImportError as ex:                          # noqa: BLE001
        rep.add(unavailable("B2", "轮廓环有效性", "本机没有 shapely（%s）" % ex,
                            measure="环有效性"))
        return

    files = floor_files(data_dir, name)
    if not files:
        rep.add(unavailable("B2", "轮廓环有效性", "没有楼层文件", measure="环有效性"))
        return

    bad_multi, bad_soft, ok = [], [], 0
    for F, p in files:
        try:
            g = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as ex:
            rep.add(Finding("B2", "轮廓环有效性", Status.UNAVAILABLE,
                            "F%d 读不了：%s" % (F, ex), floor=F, measure="环有效性"))
            continue
        ring = g.get("outline") or []
        if len(ring) < 3:
            bad_multi.append({"floor": F, "why": "轮廓点不足 3 个（%d）" % len(ring)})
            continue
        poly = Polygon(ring)
        if poly.is_valid:
            ok += 1
            continue
        why = explain_validity(poly)
        fixed = poly.buffer(0)
        kind = type(fixed).__name__
        row = {"floor": F, "why": why, "buffer0": kind,
               "area_before": round(poly.area, 1), "area_after": round(fixed.area, 1),
               "points": len(ring)}
        if kind != "Polygon":
            bad_multi.append(row)
        else:
            bad_soft.append(row)

    for row in bad_multi:
        rep.add(Finding("B2", "轮廓环有效性", Status.GAP,
                        "F%d 轮廓不是有效多边形（%s），且 buffer(0) 修出来的是 %s —— "
                        "qa_structural 会在 I1 上抛异常，**这栋楼等于没有结构门禁**。"
                        "要修的是轮廓几何本身（门禁是诚实的裁判，不许改它）"
                        % (row["floor"], row["why"], row.get("buffer0", "点不足")),
                        floor=row["floor"], measure="环有效性", evidence=row))
    for row in bad_soft:
        rep.add(Finding("B2", "轮廓环有效性", Status.WATCH,
                        "F%d 轮廓不是有效多边形（%s），buffer(0) 修回 %s；"
                        "面积 %s → %s ㎡。门禁能跑过去，但面积/包含类判据建立在一个"
                        "被静默修补过的环上，须人工核图纸"
                        % (row["floor"], row["why"], row["buffer0"],
                           row["area_before"], row["area_after"]),
                        floor=row["floor"], measure="环有效性", evidence=row))

    n = len(files)
    if not bad_multi and not bad_soft:
        rep.add(Finding("B2", "轮廓环有效性", Status.PASS,
                        "%d 层轮廓都是有效简单多边形（shapely 参考实现）" % n,
                        measure="环有效性", evidence={"floors": n}))
        return
    rep.add(Finding("B2", "轮廓环有效性",
                    Status.GAP if bad_multi else Status.WATCH,
                    "%d 层里 %d 层无效（其中 %d 层会崩门禁），%d 层有效"
                    % (n, len(bad_multi) + len(bad_soft), len(bad_multi), ok),
                    measure="环有效性",
                    evidence={"invalid_breaking_gate": [r["floor"] for r in bad_multi],
                              "invalid_repaired": [r["floor"] for r in bad_soft],
                              "valid": ok}))


# ── B3 图上房号 vs 台账房间 ────────────────────────────────────────
#
# ## 这条为什么必须存在
#
# A1/A2/A3/A9 量的都是**台账内部**的自洽（条数、字段形态、快照一致）。
# 它们都**看不见"图上还有一间，台账里根本没有它"** —— 台账自己不会喊少了谁。
# 实测（2026-09-23，c113 艺术楼）：图纸上印着 114 个本栋号，台账只有 97 个，
# 丢了 17 间（实验室/服装间/道具间/化妆间/储藏室/空调机房/工作室/专业教室…），
# 而这 17 间在 A1–A9 上**一条红都不亮**。是拿图纸当裁判才发现的。
#
# ## 为什么是"调用抽取器"，不是自己再写一遍
#
# 图上哪个号属于哪间房、哪一层、哪一层是"房号层"，规矩都在
# `backend/extract/extract_rooms_generic.py` 里，而且每条规矩都带实测来历：
# 层名语义按标记词判（`6房间号` 随楼可能叫别的）、文字要洗掉 `\A1;` 这类格式码、
# 标注点要用**文本几何中心**而不是 MTEXT 的 insert 锚点（锚点是附着点，
# 用它会漏掉约 10% 的匹配 —— memory: mtext-center-label-matching）。
# 在这里另抄一份，就是给自己埋一个新的不一致源：两份实现里只有一份跟着规则走，
# 屏幕上就会出现两句不一样的话（memory: one-judgement-many-implementations）。
# 所以本层**只调用**它的函数，一个字都不重写。
#
# ## 判据与分档
#
# **定档只用一条不含阈值的判据**：图上（本楼图幅内、本层层带内）印着的本栋房号，
# 台账里没有 ⇒ GAP。四类分类是**位置线索**，告诉人上哪儿看，**不定档**：
#
#   no_room          落在轮廓里、却不落在任何房间上 ⇒ 房间根本没抽出来（补抽）
#   label_lost       落在**别人的**房间里 ⇒ 一间房两个号，台账只留一个（查该叫什么）
#   outside          落在轮廓外 ⇒ 同样是图上印着、台账没有（附属/邻幅/野标注，看图标定）
#   format_mismatch  号在台账里，只是写法不同（`113-1-5` vs `113-01-05`）⇒ WATCH，修匹配
#
# ★ 为什么"在不在轮廓内"**不**用来定档（第一版拿它定过，把 17 间判成了 WATCH）：
#   轮廓本身正是被检查的对象（A7 逐层面积缺口、B2 环有效性）。拿一个同样在受检的
#   代量去给另一个结论定档，就是 memory: engine-gauge-failure-modes ②
#   「代理量代替真对象」—— 轮廓偏小时，真缺陷会被静默降成"在外面，未必是缺陷"。
#   实测 c113 的 17 间**全部**落在轮廓外，恰好说明降档会把这栋 **12.7%（17/134）**
#   的房间从 GAP 变成 WATCH。
# ★ 也没用"附近有没有面积标注"定档：试过，2.5m 半径下 113-04-06 与 113-02-36
#   两条假阴性（它们的面积标注在 2.5m 之外）。**凡靠我选的半径决定档位的判据，
#   都会把量程之外的待检对象静默放走**（铁律 18 附带那一条）。
#   所以面积/名称只进 evidence 当线索，并且**把距离一起写出来**。
#
# ## 阳性对照是**闸门**，不是合格证
#
# 变换（`to_local`/`floor_of`）取自 profile，是权威值，不需要从数据里反推。
# 所以这里做对照是为了证明**这份 profile 的层带/原点自抽取之后没被改过** ——
# 改过的话，台账里的号就会落不回自己那间（memory:
# criterion-invalidated-by-later-change）。对照不达标 ⇒ 报 UNAVAILABLE，不猜。
#
# ⚠️ 它**证明不了**层带当初就是对的：两边一起错时对照照样成立
# （铁律 18：两个地方写同一个数，「一致」证明不了它是对的）。别把这条当合格证。

_EXTRACTOR_REL = "backend/extract/extract_rooms_generic.py"

# 标定闸门。实测 c113 是 132/134 = 98.5%，而 0.90 这个门槛**必须在标定真坏时会红**
# —— runner.py 自检 ⑦ 里拿"层带整体平移 5m"的假数据验过（memory:
# verifier-needs-its-own-falsifier：改坏看它红不红）。
_CALIB_MIN_RATE = 0.90
# 样本太少时比例没有意义（3/3 = 100% 说明不了什么），直接不出结论。
_CALIB_MIN_SAMPLE = 10

# 图上"这个面积/名称标注是这一间的"的最近邻上限（CAD 毫米）。
# ★ 只作**线索**用（写进 evidence 给人看），判据本身不看它 —— 密集小房间楼
#   （c104）相邻房号只隔 1m 上下，最近邻会配错。所以配错只影响提示的可读性，
#   不影响结论对错；且距离与原样条数一并报出，不藏。
_B3_NEAR_MM = 2500.0
_B3_NEAR_N = 3


def _prep(ring):
    """交付环 → 可用的 shapely 多边形；无效环先自愈，救不回来回 None。

    ★ 自愈放在**建表时一次**，不放每次判点里：一是省（一次判点要对着几十个多边形），
      二是"这层几何本身不可信"只该被判断一次然后如实标出来（回 None），
      而不是每次判点都重算一遍、把结论埋进一个布尔值里。
    """
    try:
        from shapely.geometry import Polygon
        g = Polygon(ring)
        if not g.is_valid:
            g = g.buffer(0)
        return None if g.is_empty else g
    except Exception:                         # noqa: BLE001 —— 不可用的几何回 None，调用方会说出来
        return None


def _pt_in(geom, x: float, y: float) -> bool:
    """点是否落在交付多边形里。用 shapely 当参考实现。

    ★ 为什么不自己写射线法：B2 那一段已经证明过"自制几何判据两头都错"
      （memory: proxy-geometry-false-defects）。geom 为 None（几何不可用）时回 False，
      但调用方不许把它当成"不在里面" —— 那正是"量不到冒充没问题"。
    """
    if geom is None:
        return False
    try:
        from shapely.geometry import Point
        return bool(geom.covers(Point(x, y)))
    except Exception:                         # noqa: BLE001
        return False


def _geom_desc(g) -> str:
    """一句话描述一块交付多边形：面积 + 点数（多块时明说）。

    ★ 多块那一支不是多余的：`_prep` 对无效环走 `buffer(0)`，而它就是会把自交环
      炸成 MultiPolygon 的那一步（memory: qa-structural-fullrun-dies-at-c009）。
      MultiPolygon 没有 `.exterior`，不判一下这里当场 AttributeError。
    """
    ex = getattr(g, "exterior", None)
    if ex is None:
        return "一块 %.1f㎡ 的多边形（自交被 buffer(0) 炸成 %d 片）" % (
            g.area, len(getattr(g, "geoms", []) or []))
    return "一块 %.1f㎡ / %d 点的多边形" % (g.area, len(ex.coords))


def _norm(s: str) -> str:
    """房号的**规范化形**：按分隔符切段、每段去前导零、字母大写。

    只用来把「同一个号的两种写法」认出来（`113-1-5` vs `113-01-05`），
    **不用来合并不同的号** —— 段数、段值、顺序都必须对上。
    只按分隔符切，不按"非字母数字"切：c046 实测有房号整列是「卫」这种汉字，
    按字符类别切会把它切成空串，两个不同的中文号就会撞成同一个空形。
    """
    segs = [x for x in re.split(r"[\s\-_/.]+", (s or "").strip().upper()) if x]
    return "-".join((seg.lstrip("0") or "0") for seg in segs)


def _b3_gate(ok: int, bad: int, skip: int) -> str | None:
    """标定闸门：回 None = 可以出结论；否则回「为什么不能出结论」。

    ★ 单独成函数是为了能**直接喂它坏数据**验它会不会红（runner 自检 ⑦）。
      判据自己不能被自己的输入挡住——"量程把待检对象滤掉"是踩过的坑
      （铁律 18 附带那一条）。
    """
    n = ok + bad
    if n < _CALIB_MIN_SAMPLE:
        return ("阳性对照样本只有 %d 间（< %d，另有 %d 间图上找不到自己的号）："
                "样本少到比例没有意义时，比例好看也是巧合" % (n, _CALIB_MIN_SAMPLE, skip))
    rate = ok / float(n)
    if rate < _CALIB_MIN_RATE:
        return ("阳性对照 %.1f%%（%d/%d）低于 %.0f%%：台账里已有的号有 %d 间**落不回"
                "自己那间** —— 多半是 profile 的层带/原点在这次抽取之后被改过。"
                "此时『图上有、台账没有』根本分不出来，故不猜"
                % (rate * 100, ok, n, _CALIB_MIN_RATE * 100, bad))
    return None


# ── 「图幅外」那一半：滤掉了什么，必须连号带层一起交代 ────────────────
#
# ★ 这一节修的是一个**活假绿**（2026-09-23 对抗性复审实测，不是推测）：
#   B3 的"图上有没有"被两条过滤器（`in_floor_x_range` / `floor_of`）切过一刀，
#   而这两把尺**就是产出方 classify.py 用的那两把**（同一个 `recognizer.profile`）。
#   于是提取器裁掉哪一列，检查器就跟着看不见哪一列 —— **两边一起瞎**，
#   而屏幕上只写一句"图幅外滤掉 65 条"：滤掉了哪些号、里面有没有本栋的号，一个字都没有
#   （memory: gauge-coverage-invisible-in-summary）。
#   实测 c114（今天就在出 PASS）：房里号标注 130 条，图幅内 65、图幅外 65；
#   图幅外有 5 个带本栋号段的号（`114-01-09 / 114-02-10 / 114-04-01 / 114-04-03 /
#   114-04-13`）在台账里**一个都没有**，而 B3 报的是「图上 130 个房号（本楼图幅内、
#   层带内 65 条）**全部在台账里**」。**那句话按字面是假的。**
#   对照：c113 图幅外那 15 条是 `Y11xx`（真邻幅，用别的号段）—— 过滤在那里是**对的**。
#   所以错的不是过滤本身，是"滤掉多少、滤掉了哪些号"从不交代。

def _b3_dropped_evidence(out_frame_rows, out_band_rows) -> dict:
    """被两条过滤挡掉的号 —— **号、层、x 一起留下**，只留一个计数等于没交代。

    rows: `[(号, x, y, 层或 None)]`。图幅外那些的"层"只能当**线索**看：`floor_of`
    在 `floor_plans` 型楼上要靠 X 判列，而图幅外恰恰是 X 失效的地方（判不出时记 None）。
    """
    def pack(rows):
        by = {}
        for t, x, _y, F in rows:
            r = by.setdefault(t, {"labels": 0, "x": [x, x], "floors": set()})
            r["labels"] += 1
            r["x"][0] = min(r["x"][0], x)
            r["x"][1] = max(r["x"][1], x)
            if F is not None:
                r["floors"].add(F)
        return {t: {"labels": r["labels"],
                    "x_mm": [round(r["x"][0]), round(r["x"][1])],
                    "floors": sorted(r["floors"])}
                for t, r in sorted(by.items())}
    return {"out_of_frame_numbers": sorted({t for t, _x, _y, _F in out_frame_rows}),
            "out_of_frame_number_detail": pack(out_frame_rows),
            "out_of_bands_numbers": sorted({t for t, _x, _y, _F in out_band_rows}),
            "out_of_bands_number_detail": pack(out_band_rows)}


def _b3_frame_missing(rows, ledger_numbers, home_seg) -> dict:
    """图幅外/层带外、**带本栋号段**、台账里也没有的号 —— 逐个（带层）列出。

    ★ 判据（不含任何阈值）：号段是本栋的 ⇒ 这个号用的就是本栋的命名方式，
      图上印着而台账没有 —— 与图幅内那些"图上印着、台账没有"**是同一件事**，
      只是恰好画在 x_range 之外。不能因为"画在框外"就放过：那把尺是产出方与检查器
      **共用**的一把，它说"不算"的时候没有任何独立证据支持
      （CLAUDE.md 铁律 18：两处写同一个数，「一致」证明不了它是对的）。
    ★ 邻幅/别栋**不会误伤**：邻幅用的是别的号段（实测 c113 图幅外 15 条全是 `Y11xx`），
      不带本栋号段就一条都不报 —— 这也是判据用**号段**、不用"离得远不远"的原因：
      凡靠我选的半径/距离定档的判据，都会把量程之外的待检对象静默放走。
    ★ "台账里有没有"用 `_norm` 比：`114-1-9` 与 `114-01-09` 是同一个号，
      不这么比会把写法差异报成缺号（假红）。
    """
    led = {_norm(t) for t in ledger_numbers if t}
    numbers, by_floor, inst = set(), {}, 0
    for t, _x, _y, F in rows:
        if not t or not home_seg or t.split("-")[0] != home_seg:
            continue
        if _norm(t) in led:
            continue
        numbers.add(t)
        inst += 1
        by_floor.setdefault(F, set()).add(t)
    return {"numbers": sorted(numbers), "instances": inst,
            "by_floor": {k: sorted(v) for k, v in
                         sorted(by_floor.items(), key=lambda kv: (kv[0] is None, kv[0]))}}


def _b3_scope_text(labels_n, placed_n, out_frame, out_band) -> str:
    """图幅账 —— **分母要写在句子里**。

    ★ `labels_number=130` / `in_frame_in_band=65` / `dropped_out_of_frame=65`：
      只说"图上 130 个"，读的人就会把 130 当成分母读出"全部都核过了"。
      c114 的假绿正是这么读出来的。
    """
    if not out_frame and not out_band:
        return "图上 %d 个房号，全部落在本楼图幅内、层带内（%d 条）" % (labels_n, placed_n)
    return ("图上 %d 个房号，落在本楼图幅内、层带内的只有 %d 条：**图幅外滤掉 %d 条、"
            "层带外 %d 条**（滤掉的是哪些号见 evidence）"
            % (labels_n, placed_n, out_frame, out_band))


def _b3_calib_text(ledger_rows, ledger_nums, ok, bad, no_geom, skip) -> str:
    """阳性对照 —— **分母与"从没被试过的"都要写出来**。

    ★ 为什么：实测 c072/c073 台账 402 间、交付快照只有 98 间带几何，而 PASS 印的是
      「阳性对照 98/98」—— **76% 的台账从没被试过，屏幕上却是满分**
      （memory: gauge-coverage-invisible-in-summary：「没量过」和「全对」长得一样）。
      ★ 那 304 间是**从分母上凭空消失**的：标定循环里 `if not home: continue` 不计入
      `skip`，于是它既不是 ok/bad、也不是 skip，只留下一句漂亮的满分。所以这里把
      「本层快照没几何」单列成 `no_geom` 一起报（见 check_b3 的标定循环）。
    """
    tested = ok + bad
    untested = no_geom + skip
    head = ("台账 %d 行 / %d 个号，阳性对照试过 %d 间（%d 间落回自己那间、%d 间没落回）"
            % (ledger_rows, ledger_nums, tested, ok, bad))
    if untested <= 0:
        return head + "，台账每一间都被试过"
    return (head + "；另 %d 间**从来没被试过**：%d 间在本层快照里没有几何、"
            "%d 间在图幅内找不到自己的号" % (untested, no_geom, skip))


def _b3_thin_text(thin, need, cov) -> str:
    """薄层 —— PASS 句子里也要点名。

    ★ 这几层上"图上有、台账没有"根本量不了（快照没给够房间当分区底），
      不写出来，PASS 会被读成"连那几层也核过了"。
    """
    if not thin:
        return ""
    return ("另有 %d 层本层快照偏薄（%s）—— 那几层上『图上有、台账没有』量不了，按 A3 管"
            % (len(thin), "、".join("F%d(快照 %d 间/台账 %d 间)"
                                   % (F, cov.get(F, 0), need.get(F, 0))
                                   for F in sorted(thin))))


def _b3_classify(placed, ledger_numbers, geoms, outlines, norm_by_floor, thin=None):
    """把「图上有、台账没有」的号分成几类。**纯函数**（不读盘、不起进程）。

    自检直接喂它造好的输入（runner.py 自检 ⑦），所以这里不留任何 I/O。

    每行是 `(层, 号, 对照号或说明, 本地 x, 本地 y, 图纸 x, 图纸 y)` —— 图纸坐标一并带着，
    因为"就近的面积/名称标注"只能在图纸坐标里找（`_b3_hints`）。

    `thin` = `{层: 原因}`：**本层交付快照的几何不足以当分区的底**的层。这些层上
    「谁接住了它 / 谁也没接住」两句话都说不出口 —— 见下面那段注释。
    """
    out = {k: [] for k in ("no_room", "label_lost", "format_mismatch",
                           "outside", "thin_floor")}
    thin = thin or {}
    for F, x, y, t, dx, dy in placed:
        if t in ledger_numbers:
            continue                              # 台账有它 ⇒ 不是本条的活
        hit = None
        for num, g in geoms.get(F) or []:
            if _pt_in(g, x, y):
                hit = num
                break
        # ★ 本层快照几何不足时，**"谁也没接住它"这句话说不出口**，整支不结结论。
        #   实测 c009：台账 150 间，交付快照 F0/F1/F4 一间几何都没有（F2 8、F3 9）。
        #   那时"轮廓内有 43 个号没有房间接住"是**必然的**，不是缺陷；而它给出的
        #   操作建议是「这一间根本没抽出来，补抽」，把人指去重跑抽取 —— 真缺陷
        #   （逐层快照是空的）归 A3 管。**「量具没拿到那一层」和「那一层没问题」
        #   在屏幕上长得一模一样**（铁律 16），所以这里既不报红也不报绿，说量不到。
        # ★ 只卡这一支，不卡 `label_lost` / `outside`：后两句各自只依赖**已经拿到手**
        #   的东西（接住它的那块多边形 / 本层轮廓），跟快照缺不缺房间无关。一刀切
        #   把整层推成薄层，等于用一个量不到的理由把量得到的东西也一起丢掉
        #   —— 那是把"少报"当稳妥，和"多报"一样是错。
        if hit is not None:
            # 落在别人的房间里：先看是不是**同一个号的另一种写法**，别把排版当成丢号
            if _norm(hit) == _norm(t):
                out["format_mismatch"].append((F, t, hit, x, y, dx, dy))
            else:
                out["label_lost"].append((F, t, hit, x, y, dx, dy))
            continue
        o = outlines.get(F)
        if o is None:
            # ★ 本层轮廓不可用 ⇒ **分不出**轮廓内外。不许默认当成"在外面"了事 ——
            #   那会把一个"量不到"写成一条 WATCH 结论。标记写进对照位，人看得见。
            out["outside"].append((F, t, "本层轮廓不可用", x, y, dx, dy))
            continue
        if not _pt_in(o, x, y):
            out["outside"].append((F, t, None, x, y, dx, dy))
            continue
        if F in thin:
            out["thin_floor"].append((F, t, thin[F], x, y, dx, dy))
            continue
        m = (norm_by_floor.get(F) or {}).get(_norm(t))
        if m:
            out["format_mismatch"].append((F, t, m, x, y, dx, dy))
        else:
            out["no_room"].append((F, t, None, x, y, dx, dy))
    return out


def _b3_hints(p, labels, rows):
    """给丢号配「图上就近的面积/名称」。回 {层: {号: 一行说明}}。

    ★ 这是**线索不是判据**：密集小房间楼（c104）相邻房号只隔 1m 上下，最近邻会配错。
      所以距离与原样条数一并报出，不藏。它进 evidence 给人看，不参与定档。
    """
    from recognizer.profile import floor_of as _fo
    area_ent, purp_ent = labels.get("area") or [], labels.get("purpose") or []

    def near(entries, x, y, fl):
        ds = sorted((math.hypot(ex - x, ey - y), et) for ex, ey, et in entries
                    if _fo(p, ex, ey) == fl)
        if not ds or ds[0][0] > _B3_NEAR_MM:
            return ""
        d0 = ds[0][0] / 1000.0
        n = min(_B3_NEAR_N, sum(1 for d, _t in ds if d <= _B3_NEAR_MM))
        return "%s(%.1fm%s)" % (ds[0][1], d0, "" if n <= 1 else "／附近 %d 条" % n)

    out: dict[int, dict] = {}
    for F, t, _other, _x, _y, dx, dy in rows:
        # 线索要在**图纸坐标**里找（`labels` 存的是图纸毫米，`rows` 里两个坐标都带着）
        a, u = near(area_ent, dx, dy, F), near(purp_ent, dx, dy, F)
        bits = [b for b in (("面积 " + a) if a else "", ("名称 " + u) if u else "") if b]
        if bits:
            out.setdefault(F, {})[t] = "、".join(bits)
    return out


def check_b3(rep, data_dir, name: str, **_kw) -> None:
    """图上房号 vs 台账房间 —— **图上有的，台账里有没有**。"""
    title = "图上房号 vs 台账房间"
    mz = "图上房号对账"

    # ── ① 取抽取器当尺子（不重写它的任何判据）────────────────────
    root = Path(data_dir).resolve().parent
    for pth in (root, root / "backend", root / "backend" / "extract"):
        if str(pth) not in sys.path:
            sys.path.insert(0, str(pth))
    try:
        import extract_rooms_generic as EX
    except Exception as ex:                       # noqa: BLE001
        rep.add(unavailable("B3", title, "取不到房间抽取器：%s: %s" % (type(ex).__name__, ex),
                            measure=mz))
        return
    want = root / _EXTRACTOR_REL
    got = Path(getattr(EX, "__file__", "") or "")
    if os.path.normcase(str(want)) != os.path.normcase(str(got)):
        rep.add(unavailable("B3", title,
                            "import 到的不是这一个：想读 %s，实际 %s —— 尺子拿错了，不量"
                            % (want, got), measure=mz))
        return
    # 与 B1 同一条纪律：量具指向别处时不许照跑（否则在 A 库上量、报 B 库的数）。
    # ★ BUILDINGS 不在抽取器的命名空间里（它只 `from paths import ensure_sys_path`），
    #   真正被 load_profile 用的是 `paths.BUILDINGS` —— 这里必须去**那个**模块取，
    #   取不到就报量不到，不许当成"没有这条约束"跳过去。
    try:
        import paths as PATHS
        got_b = Path(str(PATHS.BUILDINGS)).resolve()
        # 坐标口径（层带判归属 / 图上毫米→本地米 / 图幅过滤）都只从 `recognizer.profile`
        # 取 —— 那是它们的**定义处**。抽取器只转手引出了其中两个
        # （`from recognizer.profile import to_local, floor_of`，**没有** in_floor_x_range），
        # 从定义处取就不会因为"它这轮少引了一个名字"而量错。
        from recognizer.profile import floor_of, to_local, in_floor_x_range
    except Exception as ex:                       # noqa: BLE001
        rep.add(unavailable("B3", title,
                            "取不到量具的坐标口径或库根（paths/recognizer.profile）：%s: %s"
                            % (type(ex).__name__, ex), measure=mz))
        return
    want_b = Path(data_dir).resolve() / "buildings"
    if os.path.normcase(str(want_b)) != os.path.normcase(str(got_b)):
        rep.add(unavailable("B3", title,
                            "量具指向别处：paths.BUILDINGS=%s，本次要查的是 %s"
                            % (got_b, want_b), measure=mz))
        return

    try:
        p = EX.load_profile(name)
    except Exception as ex:                       # noqa: BLE001
        rep.add(unavailable("B3", title, "profile 读不了：%s: %s" % (type(ex).__name__, ex),
                            measure=mz))
        return
    if not p.dxf or not Path(p.dxf).is_file():
        rep.add(unavailable("B3", title,
                            "找不到源图 %s —— 没有图就量不了『图上有没有』" % p.dxf,
                            measure=mz))
        return

    # ── ② 读图：标注走抽取器自己的层名解析与文字清洗 ─────────────
    try:
        import ezdxf
        msp = ezdxf.readfile(p.dxf, encoding=EX.ENCODING).modelspace()
        role_map = EX.layer_role_map(msp)
        role_map.update(EX.LAYER_ROLE_OVERRIDE.get(name, {}))
        labels = EX.read_labels(msp, role_map, EX.PURPOSE_DROP_AREA_LIKE.get(name))
    except Exception as ex:                       # noqa: BLE001
        rep.add(unavailable("B3", title, "读图失败：%s: %s" % (type(ex).__name__, ex),
                            measure=mz))
        return
    if not labels.get("number"):
        rep.add(unavailable("B3", title,
                            "图上一条房号标注都没读到（层名语义变了？）—— 不猜", measure=mz))
        return

    # ── ③ 图幅/层带两条过滤，滤掉多少**连号一起**说出来 ──────────
    # 邻幅的号天然不在台账里（实测 c113 F1 有 15 条 `Y11xx` 画在 x_range 之外），
    # 不先滤掉，每一个都会长成假缺陷；而假红会把真红一起淹掉。
    # ★ 但"滤掉多少"不等于"滤掉的都不是本栋的"（见本文件 _b3_dropped_evidence 那段）：
    #   所以这里把**号本身**留下来，后面 `_b3_frame_missing` 拿号段判一次，
    #   带本栋号段却不在台账里的必须说出来，不许随着过滤一起静默。
    placed, out_frame_rows, out_band_rows = [], [], []
    for x, y, t in labels["number"]:
        if not in_floor_x_range(p, x):
            out_frame_rows.append((t, x, y, floor_of(p, x, y)))
            continue
        F = floor_of(p, x, y)
        if F is None:
            out_band_rows.append((t, x, y, None))
            continue
        lx, ly = to_local(p, x, y, F)
        placed.append((F, lx, ly, t, x, y))
    out_frame, out_band = len(out_frame_rows), len(out_band_rows)
    dropped = _b3_dropped_evidence(out_frame_rows, out_band_rows)

    # ── ④ 台账与交付几何 ───────────────────────────────────────
    try:
        ledger = json.loads((Path(data_dir) / "buildings" / name / "rooms.json")
                            .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        rep.add(unavailable("B3", title, "台账读不了：%s: %s" % (type(ex).__name__, ex),
                            measure=mz))
        return
    if not isinstance(ledger, list):
        rep.add(unavailable("B3", title, "台账不是数组（形状变了）—— 不猜", measure=mz))
        return

    # ★ shapely 必须先确认在。缺了它 `_prep` 会把每个环都回成 None，于是所有号
    #   都被归进"轮廓不可用"→ 屏幕上是一排 WATCH，看着像查过了。
    #   那正是"量不到冒充结论"（铁律 16）。所以缺依赖就明说 UNAVAILABLE。
    try:
        import shapely                                        # noqa: F401
    except ImportError as ex:                                 # noqa: BLE001
        rep.add(unavailable("B3", title, "本机没有 shapely（%s）—— 判内外要用它当参考实现"
                            % ex, measure=mz))
        return
    geoms: dict[int, list] = {}
    outlines: dict[int, object] = {}
    for F, path in floor_files(data_dir, name):
        try:
            g = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as ex:
            # ★ 读不了就**说出来**：这一层会从对账里整层消失。若静默 continue，
            #   "这层没问题"和"这层没量过"在屏幕上长得一模一样（铁律 16）。
            rep.add(Finding("B3", title, Status.UNAVAILABLE,
                            "F%d 交付楼层读不了（%s），本层不参与对账" % (F, ex),
                            floor=F, measure=mz))
            continue
        rows = []
        for r in g.get("rooms") or []:
            poly = r.get("poly") or []
            pg = _prep(poly) if len(poly) >= 3 else None
            if pg is None:
                continue
            rows.append((str(r.get("number") or ""), pg))
        geoms[F] = rows
        ring = g.get("outline") or []
        outlines[F] = _prep(ring) if len(ring) >= 3 else None

    # ── ⑤ 阳性对照（闸门）─────────────────────────────────────
    ledger_numbers = {str(r.get("number") or "") for r in ledger}
    # ★ 图幅外那半：**带本栋号段、台账里也没有**的号，必须在**每一条**后续路径上都被说出来
    #   —— 它在闸门不过、薄层、PASS 三种出口里都算数，所以在这里就出结论（不放到分支里面）。
    # 定档 = **GAP**。为什么不是 WATCH：本条的定档规则是"图上印着、台账没有 ⇒ GAP"，
    #   这几个号完全满足它，唯一的"豁免理由"是画在图幅之外 —— 而图幅那把尺（`in_floor_x_range`）
    #   与产出方 classify.py 是**同一个函数**，它说"不算"时没有任何独立证据支持
    #   （CLAUDE.md 铁律 18；memory: criterion-invalidated-by-later-change 那类"两边同一个数"）。
    #   反过来的假设"它们是邻幅/别栋的号"是**可以用号段证伪的**：邻幅在实测里用别的号段
    #   （c113 的 `Y11xx`）。带本栋号段的号，图上印着而台账没有，就与本条要抓的缺陷同质。
    # ★ 不降级的第二个理由（第一版拿"轮廓内外"定档时已经栽过一次，理由完全相同）：
    #   拿一个**同样在受检之列**的代量给结论降档，真缺陷会被静默降成"画在框外，未必是缺陷"
    #   —— 而 c114 实测的真相是"图幅把本栋的第二份整层平面切在了框外"，正是要靠这一条抓出来的。
    home_seg, home_n = home_number_segment([str(r.get("number") or "") for r in ledger])
    frame_missing = _b3_frame_missing(
        out_frame_rows + out_band_rows, ledger_numbers, home_seg)
    fm_detail = {t: dropped["out_of_frame_number_detail"].get(t)
                 or dropped["out_of_bands_number_detail"].get(t) or {}
                 for t in frame_missing["numbers"]}
    if frame_missing["numbers"]:
        for F, ts in frame_missing["by_floor"].items():
            where = "层带外/层判不出" if F is None else "F%d" % F
            rep.add(Finding(
                "B3", "图幅外印着本栋号、台账里没有", Status.GAP,
                "%s 有 %d 个号是**本栋号段 `%s-*`、台账里一个都没有**：%s。" % (
                    where, len(ts), home_seg,
                    "、".join("%s(图上 x=%.0fmm)" % (t, (fm_detail.get(t) or {}).get(
                        "x_mm", [0])[0]) for t in ts)) +
                "这一档**不因『画在图幅外』而降级**：`in_floor_x_range` 与产出方 "
                "classify.py 是同**一个函数**，提取器裁掉哪一列、本条就跟着看不见哪一列"
                "（两边一起瞎），所以『滤掉多少条』从不等于『滤掉的都不是本栋的』。"
                "要分清的是两种可能、须对着图看：①台账漏了这几间；②图幅（x_range）切窄了。"
                "（既往实测例，供对照、**不是说本栋**：c114 图幅内 65 条 / 图幅外 65 条，"
                "逐层标注数 {0:10,1:16,2:13,3:12,4:11,5:3} 对 {0:11,1:17,2:13,3:11,4:10,5:3}"
                "—— 图幅外那一列是**同一栋的第二份整层平面**，正是第②种。）"
                "邻幅不会误伤：邻幅用别的号段（既往实测 c113 图幅外 15 条是 `Y11xx`，"
                "不带本栋号段即一条都不报）",
                floor=F, measure=mz,
                evidence={"kind": "frame_home_missing", "home_segment": home_seg,
                          "numbers": ts, "instances": len(ts),
                          "number_detail": {t: fm_detail.get(t) for t in ts},
                          "x_range": list(p.x_range) if p.x_range else None,
                          "out_of_frame": out_frame, "out_of_bands": out_band}))
    norm_by_floor: dict[int, dict] = {}
    for r in ledger:
        F = r.get("floor")
        if isinstance(F, int):
            norm_by_floor.setdefault(F, {})[_norm(str(r.get("number") or ""))] = \
                str(r.get("number") or "")
    # ★ `no_geom` 单列：台账里"本层快照根本没有它的几何"的那些间，原来只写一个 `continue`
    #   —— 于是它们**从分母上凭空消失**：既不是 ok/bad，也不是 skip，PASS 里那句
    #   「阳性对照 98/98」看不出台账其实是 402 间（memory:
    #   gauge-coverage-invisible-in-summary：「没量过」和「全对」长得一样）。
    ok = bad = skip = no_geom = 0
    for r in ledger:
        F = r.get("floor")
        t = str(r.get("number") or "")
        home = [g for num, g in (geoms.get(F) or []) if num == t]
        if not home:
            no_geom += 1                          # 该层快照没它的几何 ⇒ 不是本条的活
            continue
        cand = [(x, y) for (ff, x, y, tt, _dx, _dy) in placed if ff == F and tt == t]
        if not cand:
            skip += 1
            continue
        if any(_pt_in(g, cand[0][0], cand[0][1]) for g in home):
            ok += 1
        else:
            bad += 1
    why = _b3_gate(ok, bad, skip)
    if why:
        # ★ 这条 UNAVAILABLE 会污染整组结论（findings.rollup）—— 正是要的：
        #   标定不住时，「图上有、台账没有」这句根本读不出来，不能给绿灯。
        rep.add(unavailable("B3", title, why, measure=mz,
                            evidence={"calib_ok": ok, "calib_bad": bad,
                                      "calib_skip": skip, "calib_no_geometry": no_geom,
                                      "labels_number": len(labels["number"]),
                                      "dropped_out_of_frame": out_frame,
                                      "dropped_out_of_bands": out_band,
                                      **dropped}))
        return

    # ── ⑤-b 本层快照够不够当分区底（不够的层 B3 不结结论）─────────
    # ★ 为什么必须单列这一关：B3 的两句话（「谁接住了它」「谁也没接住」）都默认
    #   **交付快照 = 这层的分区**。快照缺房间时这两个默认都不成立，而屏幕上照样
    #   出结论。实测 c009：台账 150 间，快照 F0/F1/F4 零几何 → B3 报「43 间没抽出来，
    #   补抽」，把 A3 的毛病（快照空）说成抽取的毛病，还指了个错方向的操作。
    # ★ 门槛用「快照带几何的间数 ≥ 台账本层间数」，不用绝对数也不用比例：它问的是
    #   "快照有没有可能少给你房间"，与楼大（20 间还是 300 间）无关。数一并报出。
    need: dict[int, int] = {}
    for r in ledger:
        F = r.get("floor")
        if isinstance(F, int):
            need[F] = need.get(F, 0) + 1
    thin: dict[int, str] = {}
    for F in sorted(set(list(need) + list(geoms))):
        cov = len(geoms.get(F) or [])
        if cov < need.get(F, 0):
            thin[F] = ("本层快照只有 %d 间带几何，台账本层 %d 间 —— 快照少给了房间，"
                       "本层不结结论（这条归 A3 管）" % (cov, need.get(F, 0)))

    # ── ⑥ 分类 + 出结论 ───────────────────────────────────────
    res = _b3_classify(placed, ledger_numbers, geoms, outlines, norm_by_floor, thin)
    all_rows = [r for v in res.values() for r in v]
    hints = _b3_hints(p, labels, all_rows)

    # ★ 定档只用一条**不含阈值**的判据：图上（本楼图幅内、本层层带内）印着的房号，
    #   台账里没有 ⇒ GAP。四类分类是**位置线索**，用来告诉人上哪儿看，不定档。
    #
    #   为什么"在轮廓内/外"不该定档（第一版就是拿它定的，把 17 间判成了 WATCH）：
    #   轮廓本身正是被检查的对象之一（A7 逐层面积缺口、B2 环有效性）。
    #   拿一个同样在被检查的代理量去给另一个结论定档，就是
    #   memory: engine-gauge-failure-modes ②「代理量代替真对象」—— 轮廓偏小时，
    #   真缺陷会被静默降成"在轮廓外，未必是缺陷"。而这里实测 17/17 都在轮廓外，
    #   恰好说明降档会把**整栋 12.7% 的房间**（17/134）从 GAP 变成 WATCH。
    #
    #   也不用"附近有没有面积标注"定档：试过，2.5m 半径下 113-04-06 与 113-02-36
    #   两条假阴性（它们的面积标注在 2.5m 外）。**凡是靠我选的半径来决定档位的判据，
    #   都会把量程之外的对象静默放走**（铁律 18 附带那一条），所以面积/名称只作
    #   evidence 里的线索，明写距离，不参与定档。
    # ★ 措辞上的纪律：只写**观察到什么**，不写**为什么**。第一版给 label_lost 写的是
    #   「一间房两个号，台账只留了一个（抽取时一个标注配一个区域，先到的赢）」——
    #   那是一个**我没证过的机制**。实测 c019 F0 / c022 F2：接住 7 个、16 个号的
    #   那块多边形，图上每个号**都带着自己的面积与名称标注**（c019 那 8 个号各带一条
    #   28.75㎡ 的标注、排成两列；8×28.75≈227，正是台账给那块的面积）。所以真机制是
    #   **好几间被焊成一块**，不是"一间房两个号"。引擎没资格替人认定根因
    #   （memory: engine-gauge-failure-modes ②），只把两项观察并排摆出来。
    for kind, st, tail in (
            ("no_room", Status.GAP,
             "落在轮廓内、本层快照也有房间，却没有一间接住它 ⇒ 图上这一间没进台账。"
             "是**没抽出来**、还是**被并进了别的房间**，须对着图看"
             "（差异处理＝只记录，改不改等拍板）"),
            ("label_lost", Status.GAP,
             "落在**别人**的多边形里 ⇒ 要么那是一块**吞了不止一间**的多边形，"
             "要么这间房印了两个号。判它的办法是数**这块里有几条房号标注**"
             "（每间房图上都带自己的面积与名称），不数它叫什么"),
            ("outside", Status.GAP,
             "落在轮廓**外** ⇒ 一样是图上印着、台账没有。轮廓本身也在受检之列，"
             "所以这一档**不因「在外面」而降级**；是附属房、邻幅还是野标注，须对着图看"),
            ("format_mismatch", Status.WATCH,
             "号在台账里，**只是写法不同** ⇒ 修的是匹配，不是补房"),
            ("thin_floor", Status.UNAVAILABLE, "")):
        by_floor: dict[int, list] = {}
        for F, t, other, _x, _y, _dx, _dy in res[kind]:
            by_floor.setdefault(F, []).append((t, other))
        for F, rows in sorted(by_floor.items()):
            ts = sorted({t for t, _o in rows})
            if kind == "no_room":
                show = "、".join(
                    "%s%s" % (t, ("（%s）" % hints[F][t]) if hints.get(F, {}).get(t) else "")
                    for t in ts)
            elif kind == "label_lost":
                # ★ 把"接住它的那块有多大、本层台账共几间"一并摆出来 ——
                #   这是判"吞了不止一间"还是"一间房两个号"的**唯一可用证据**，
                #   而它不需要我选任何阈值（面积/点数/间数都是原样报出）。
                desc = {}
                for num, g in geoms.get(F) or []:
                    desc.setdefault(num, _geom_desc(g))
                show = "、".join(
                    "%s（那间台账记的是 %s%s）"
                    % (t, o or "(无号)",
                       "；%s" % desc[o] if o in desc else "")
                    for t, o in rows)
            elif kind == "outside":
                h = hints.get(F) or {}
                show = "、".join("%s%s" % (t, ("（%s）" % h[t]) if h.get(t) else "") for t in ts)
            elif kind == "thin_floor":
                show = "、".join(ts)
            else:
                show = "、".join("%s→%s" % (t, o) if o else t for t, o in rows)
            if kind == "thin_floor":
                # 这一档的原因**逐层不同**（快照几间 / 台账几间），所以不能共用 tail。
                tail = rows[0][1]
                head = "%d 个号本层不参与对账" % len(rows)
            else:
                head = "有 %d 个号%s" % (len(rows), {
                    "no_room": "落在轮廓内却没有对应房间",
                    "label_lost": "落在**别人**的房间里",
                    "outside": "落在轮廓外",
                    "format_mismatch": "与台账同号不同写法"}[kind])
            rep.add(Finding("B3", title, st,
                            "F%d %s：%s。%s" % (F, head, show, tail),
                            floor=F, measure=mz,
                            evidence={"kind": kind, "missing": ts,
                                      "instances": len(rows),
                                      "snapshot_rooms": len(geoms.get(F) or []),
                                      "ledger_rooms_floor": need.get(F, 0),
                                      "hint": (hints.get(F) or {})}))
    # 整栋一条。★ 数**不同的号**，另附**标签条数** —— 同一个号在图上写两遍
    #   （实测 113-01-12）会让两个数不一样，只报一个就是在报一个说不清的数。
    missing_nums = sorted({r[1] for v in res.values() for r in v})
    n_inst = sum(len(v) for v in res.values())
    # ★ 分母类的数一律**成对**写出：「台账几行」要配「几个号」（c114 是 64 行 / 62 个号，
    #   只报行数读的人对不上"号"）、「阳性对照几间」要配「台账共几间、另几间没试过」。
    ev = {"calib_ok": ok, "calib_bad": bad, "calib_skip": skip,
          "calib_rate": round(ok / float(ok + bad), 4),
          "calib_no_geometry": no_geom,
          "calib_untested": no_geom + skip,
          "labels_number": len(labels["number"]),
          "in_frame_in_band": len(placed),
          "dropped_out_of_frame": out_frame, "dropped_out_of_bands": out_band,
          "ledger_rows": len(ledger), "ledger_numbers": len(ledger_numbers),
          "ledger_rooms": len(ledger),          # 保留旧键名（历史产物/读的人按它找）
          "ledger_modal_segment": home_seg, "ledger_modal_n": home_n,
          "frame_home_missing": frame_missing["numbers"],
          "frame_home_missing_by_floor": frame_missing["by_floor"],
          "missing_numbers": missing_nums,
          "thin_floors": sorted(thin),
          "thin_reasons": {F: thin[F] for F in sorted(thin)},
          "counts": {k: len(v) for k, v in res.items()},
          **dropped}
    # ★ 有薄层**且那层上真有对不上的号**时，不给整栋结论：那些层上"图上有没有、
    #   台账有没有"根本量不了，此时再打一句"其余都对"就是拿量到的部分替量不到的部分
    #   背书（铁律 16）。逐层的 UNAVAILABLE 已经把层号和号都点名了，这里只说总量。
    # ★ 两个条件缺一不可。第一版只判 `if thin:`，于是 c017/c044/c072/c073 从 PASS
    #   掉成 UNAVAILABLE —— 那几栋的薄层上**一个对不上的号都没有**（图上印的号全在
    #   台账里），没有任何结论需要收回。**快照缺几何是 A3 的事；B3 只该在"我本来要
    #   说一句话、而这层没资格说"时才闭嘴**，否则就是把别人的缺陷当成自己的结论
    #   撤回 —— 屏幕上和真缺陷一样是红的（"少报"和"多报"同罪）。
    if res["thin_floor"]:
        tf = sorted({r[0] for r in res["thin_floor"]})
        rep.add(Finding("B3", title, Status.UNAVAILABLE,
                        "有 %d 层量不了（快照几何比台账少）：%s —— 这 %d 层上共有 %d 个"
                        "号对不了账，整栋不结总论"
                        % (len(tf), "、".join("F%d(%s)" % (F, thin[F].split("，")[0])
                                              for F in tf),
                           len(tf), len(res["thin_floor"])),
                        measure=mz, evidence=ev))
        return
    scope = _b3_scope_text(len(labels["number"]), len(placed), out_frame, out_band)
    calib = _b3_calib_text(len(ledger), len(ledger_numbers), ok, bad, no_geom, skip)
    thin_txt = _b3_thin_text(thin, need, {F: len(geoms.get(F) or []) for F in thin})
    # ★ 图幅外那半也算"对不上账"：不能因为 `frame_missing` 不在 `res` 的四个类里
    #   就让它落进 PASS（那正是这条假绿的形状 —— 逐层 GAP 已经发过了，整栋这句
    #   若还说"全部在台账里"，屏幕上就同时挂着两句互相打脸的话）。
    fm_n = len(frame_missing["numbers"])
    if not any(res.values()) and not fm_n:
        # ★ PASS 措辞的三条纪律（2026-09-23 修）：
        #   ①「图上 N 个」后面必须写**其中多少条被两条过滤滤掉了**（`_b3_scope_text`）；
        #   ② 阳性对照必须写**分母**，以及"另有多少间从来没被试过"（`_b3_calib_text`）——
        #      实测 c072/c073 台账 402 间、快照只有 98 间，原来印的是"阳性对照 98/98"，
        #      76% 的台账从没被试过却是满分；
        #   ③ 台账数**行数要配号数**（c114 是 64 行 / 62 个号），并点名**快照偏薄的层**。
        rep.add(Finding("B3", title, Status.PASS,
                        "。".join(x for x in (scope, "图上印着的号全部在台账里",
                                              calib, thin_txt) if x) + "。",
                        measure=mz, evidence=ev))
        return
    rep.add(Finding("B3", title,
                    Status.GAP if (res["no_room"] or res["label_lost"] or res["outside"])
                    or fm_n else Status.WATCH,
                    # ★ 四类全空时**不印那句"图上有 0 个号台账里没有"** —— 它字面上对，
                    #   但下一句马上说"另：图幅外印着 5 个"，两句并排会被读成自相矛盾。
                    #   这种时候整句就只说图幅外这一件（它就是本栋不 PASS 的原因）。
                    ((("图上有 %d 个号台账里没有（含重复标注共 %d 条）："
                       "轮廓内没抽出来的 %d、号被顶掉的 %d、轮廓外的 %d"
                       "（另：与台账同号不同写法 %d）。"
                       % (len(missing_nums), n_inst,
                          len(res["no_room"]), len(res["label_lost"]),
                          len(res["outside"]), len(res["format_mismatch"])))
                      if any(res.values()) else "")
                     + scope + "。" + calib + "。"
                     + (("另：**图幅外**印着 %d 个带本栋号段 `%s-*` 的号、台账里一个都没有"
                         "（%s）—— 见上面那条『图幅外印着本栋号、台账里没有』。"
                         % (fm_n, home_seg, "、".join(frame_missing["numbers"][:12])))
                        if fm_n else "")
                     + (thin_txt + "。" if thin_txt else "")),
                    measure=mz, evidence=ev))


# ── B4：图纸声明的楼层 vs 模型里的楼层 ────────────────────────────────
# 读数与判据在 floor_levels.py（单一实现，独立脚本 _scratch/_own_sheets_vs_model.py
# 也 import 它，不另抄一份）。
def check_b4(rep: Report, data_dir, name: str, **_kw) -> None:
    """图纸自带面积表声明的层数 vs 模型交付的层数。

    为什么这条要有：用户 2026-09-23 点了一句「水上图书馆，f0其实是两层」。
    查下去是**整层没进模型** —— c001 图上 6 层（`D1` + 1~5），模型 5 层，
    `D1`（6 间房、1540.50㎡、图号 C001-D1）压根不在。全库量下来 **17 栋**
    图纸层多于模型层，且成类：层号不是纯数字时（`D1`/`J11`/`H`）会被静默丢掉。

    ★ 这条只是"层数对不对"，**不替层数定值** —— 层数该怎么定由 B4 之外的
      定层规则负责；B4 的职责是**让不一致能被看见**，而不是悄悄对齐。
    """
    from . import floor_levels as FL

    title = "图纸声明的楼层 vs 模型楼层"
    mz = ("层数口径：**图纸侧**取该图 ACAD_TABLE 面积表里『图号前缀==本栋编号』的"
          "楼层标签去重（剔图册示例行 100.00㎡ 与『标准层』汇总行）；"
          "**模型侧**取 data/buildings/<楼>/floors/floorN.json 的个数。"
          "两个都是**层数**，不是面积。")

    try:
        r = FL.diagnose(data_dir, name)
    except Exception as ex:                      # noqa: BLE001
        rep.add(unavailable("B4", title, "量具自己崩了：%s: %s" % (type(ex).__name__, ex)))
        return

    out = r.get("outcome")
    if out == "unreadable":
        rep.add(unavailable("B4", title, r.get("why") or "量不到", measure=mz))
        return
    if out == "no_model":
        rep.add(Finding("B4", title, Status.WATCH,
                        "模型里没有层：%s（图纸声明 %d 层：%s）"
                        % (r.get("why"), r["n_drawing"], "、".join(r["labels"])),
                        measure=mz, evidence=r))
        return

    labels = "、".join(r["labels"])
    ev = {k: r.get(k) for k in ("labels", "n_drawing", "n_model", "floors",
                                "declared", "own_rows", "foreign_rows",
                                "dropped_template", "dropped_summary")}
    if out == "ok":
        rep.add(Finding("B4", title, Status.PASS,
                        "图纸 %d 层 == 模型 %d 层（图纸层号：%s）"
                        % (r["n_drawing"], r["n_model"], labels),
                        measure=mz, evidence=ev))
    elif out == "drawing_more":
        # ★ 措辞只说到证据为止：数量不等是**量出来的**，缺的是哪一层则**没有单义解**
        #   —— 图纸层号与模型层号之间没有通用的一一映射（c001 一层一框、c002 十层并排
        #   在一张表里），硬指一个层号就是编。所以只说"少了，至少一层没进模型"。
        rep.add(Finding("B4", title, Status.GAP,
                        "**图纸声明 %d 层，模型只有 %d 层**（图纸层号：%s）——"
                        "层数对不上，至少有一层没进模型。缺的是哪一层要逐层比对，"
                        "本条只报层数不等，不替定层规则下结论。"
                        % (r["n_drawing"], r["n_model"], labels),
                        measure=mz, evidence=ev))
    else:                                        # model_more
        rep.add(Finding("B4", title, Status.WATCH,
                        "模型 %d 层多于图纸声明的 %d 层（图纸层号：%s）"
                        "—— 可能是层带多切了，也可能是图纸面积表本身不全，需人看。"
                        % (r["n_model"], r["n_drawing"], labels),
                        measure=mz, evidence=ev))
