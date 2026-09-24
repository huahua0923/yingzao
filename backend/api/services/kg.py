# -*- coding: utf-8 -*-
"""知识图谱数据域 —— 图谱自己的清单 ＋「扩散激活」查询（**只读**）。

引擎在 `kb/`：`build_kb.py` 把 `src/*.md` ＋ `playbook.json` ＋ `traps.json` 打包成
`kb.json`；`ask.py` 是**唯一**查询入口（别名索引与扩散激活只有它一份实现）；
`gate.py` 是图谱自己的门禁（逐条边复核路径 / 行号 / 符号 / 值漂移 / 双源 / 陈旧 /
只读白名单）。本模块是它在 HTTP 层的那一层：**只读产物、只调那一条命令，一个字都不重写**。

四条约束（与 `kb/README.md` 的「智能体流程」一节同源）：

1. **三态原样透传**：`hit` / `unverified` / `miss` 不合并、不兜底。`miss` 带
   `nearest[]` 与 `register` 命令 —— 「图里没有」和「没问题」在屏幕上长得一样
   （铁律 16 的同族）。后端要是替前端补一个空数组，等于把「没查过」说成「没事」。
2. **只读**：`ask.py --run` 会跑判据并写 `data/_meta/kg_runs.json`，`--pending` 会写
   `kb/pending.json` —— 两条都是**写**操作。本域一个都不开放：HTTP 只做 `--json`
   查询，要跑判据走 CLI（`python -u kb/ask.py "<说法>" --run`）。
   ★ 这句话**有实现兜着**（2026-09-24 安全评审逼出来的）：`ask.py` 的开关是**与位置无关**
   识别的（`"--run" in args`），而本模块把用户敲的词原样当一个 argv 递进去 ⇒
   `?building=--run&q=…` 会让一次只读查询变成一次真跑判据 + 写台账。
   ⇒ 两道：`_switch_like()` 在边界上**拒**（并说清理由），argv 里位置参数前插 `--`
   让那个词**结构上不可能**成为开关（`kb/ask.py:split_at_dashdash`）。
3. **门禁结论不在这里重算**：C4 那两行已经在 `data/_meta/checks/fleet.json` 里，
   `GET /api/checks/fleet` 已经会读（`services/checks.py`）。本域只报**尺子指纹**
   并指明去哪看门禁 —— 同一个结论两份实现 = 两份会漂的写法
   （memory: one-judgement-many-implementations）。
4. **形状不认识就不当数据**：子进程可能吐 traceback、可能被超时打断。`ask()` 先验
   形状（是 dict ＋ `state` 在三态内 ＋ `ruler` 在），不满足就如实报错 ——
   绝不把半截东西当查询结果渲染出去。「退出码 0」与「输出能当结论」是两件事。

★ 清单为什么直接读 `kb.json` 而不起子进程：那就是 `ask.py` 读的同一份产物
  （`build_kb.py` 原子写），投影几个字段不构成第二份实现；而 `ask` 那条**必须**走
  子进程 —— 扩散激活有且只有 `ask.py` 一处实现。
★ 指纹规则不自己写第二份：取 `backend.state.roster.sha12`（全仓一份，C3 也用它）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..responses import ApiError, bad_request

GRAPH_NAME = "kb.json"
ASK_NAME = "ask.py"
GATE_NAME = "gate.py"

# 三态 —— 抄的是 `ask.py` 的**契约**（`kb/README.md`「智能体流程」一节写的那个 JSON
# 形状），不是从它的实现里猜的。多出来一个状态在这里就是「后端不认识它」⇒ 报错，
# 不硬塞进三档 —— 硬塞会让新状态**静默**变成「命中」或「查不到」其中之一。
STATES = ("hit", "unverified", "miss")

# 查询超时。本机实测 `ask.py "<词>" --json` 冷启动 ≈120ms（python 启动 ＋ 读 14ms 的
# kb.json）。60s 不是"跑得动"的余量，是留给杀毒/磁盘偶发卡顿的；超时**真的终止
# 子进程**并如实报 504，不假装查完了。
_ASK_TIMEOUT_S = 60
# `--top` 只影响 miss 时回几条最近似的，夹住不动正确性；但**夹了要说**
# （响应 meta 里回 `top_clamped_from`）—— 悄悄夹住会让调用方以为它要的就是这个数。
_MAX_TOP = 20
_QUERY_MAX_CHARS = 200
_BUILDING_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,31}$")
#: 长得像开关的词（`-x` / `--x`）。★ 判据与 `kb/ask.py` 的开关识别**同形**：
#: 那边是 `a.startswith("-")`，这里要求 `-` 后面还跟一个字母 —— 单独一个 `-`
#: （中文说法里可能出现的连字符）不算开关，不许误拒。
_SWITCH_RE = re.compile(r"^--?[A-Za-z]")


def _switch_like(word: str) -> bool:
    """这个词会被 `kb/ask.py` 当成开关吗。

    ★ 为什么本域必须在**边界**上先拒一次：`ask.py` 的开关是**与位置无关**地识别的
      （`"--run" in args`），而本模块把用户敲的词原样当**一个 argv** 递给它。
      实测（`_scratch/_sec_review_argv_probe.py`）：`building=--run` 那条 argv 里
      `--run` 是**独立的一项** ⇒ `ask.py` 照收 ⇒ 一次 GET 会真跑判据并写
      `data/_meta/kg_runs.json`；换成 `--pending` 则写 `kb/pending.json` ——
      而本路由的约定白纸黑字写着「两条都是写操作，本域一个都不开放」。
    ⇒ 两层：这里**拒**（并告诉人为什么），`kb/ask.py` 那边用 `--` 让这个词
      **结构上不可能**变成开关。两层都要 —— 只靠 `--`，被拒的理由就没人说了；
      只靠拒，将来多一个调用方就又漏一次。
    """
    return bool(_SWITCH_RE.match(word or ""))


def _kbdir(cfg) -> Path:
    return Path(cfg.root) / "kb"


def _sha12_of(path: Path) -> str | None:
    """借 `backend.state.roster.sha12` 那一份规则 —— **不自己写第二份指纹**。

    取不到就回 None，由调用方如实说「取不到」；**不换一种算法顶上** ——
    换了之后对不上，屏幕上看起来正好像「文件改了」（铁律 18 的同族）。
    """
    try:
        root = str(Path(__file__).resolve().parents[3])
        if root not in sys.path:
            sys.path.insert(0, root)
        from backend.state.roster import sha12 as _rule
    except Exception:
        return None
    try:
        return _rule(path.read_bytes())
    except OSError:
        return None


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


# ── 图谱产物 ──────────────────────────────────────────────────────────

def read_graph(cfg) -> tuple[dict, dict]:
    """读 `kb/kb.json`（图谱的打包产物）。回 `(payload, 产物信息)`。

    「文件不在」与「文件在但读不了」分开报 —— 原子写之前 `json.dump` 直写会留
    0 字节文件，那是本项目真实发生过的故障（memory: atomic-artifact-write）。
    两者报同一个错，下次就得靠猜。
    """
    p = _kbdir(cfg) / GRAPH_NAME
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        raise ApiError(404, "kg_graph_missing",
                       "图谱还没打包：kb/%s 不在" % GRAPH_NAME,
                       {"file": "kb/" + GRAPH_NAME, "how": "python -u kb/build_kb.py"}) from None
    except OSError as ex:
        raise ApiError(500, "kg_graph_unreadable",
                       "图谱产物读不出来：kb/%s" % GRAPH_NAME,
                       {"file": "kb/" + GRAPH_NAME, "error": str(ex)}) from ex
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ApiError(500, "kg_graph_corrupt",
                       "图谱产物损坏（不是 UTF-8 JSON）：kb/%s" % GRAPH_NAME,
                       {"file": "kb/" + GRAPH_NAME, "bytes": len(raw),
                        "error": str(ex)}) from ex
    # 形状验一道：只有顶层是对象还不够 —— 名字对得上的空对象同样读不出东西来
    # （「产物在」和「产物有内容」是两件事）。
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        raise ApiError(500, "kg_graph_corrupt",
                       "图谱产物形状不对（顶层缺少 entries）",
                       {"file": "kb/" + GRAPH_NAME,
                        "top_keys": sorted(payload)[:24] if isinstance(payload, dict) else None})
    st = p.stat()
    return payload, {"file": GRAPH_NAME, "dir": "kb", "bytes": st.st_size,
                     "mtime_iso": _iso(st.st_mtime)}


def inventory(cfg) -> dict:
    """图谱的清单：症状家族 / 陷阱 / 知识条目 ＋ 计数 ＋ 尺子指纹 ＋ 门禁去哪看。

    ★ 计数一律**数出**来，不写死：`--list` 印的那几个数（别名 17、可跑判据 1、
      声明无锚点 1）在这里逐族现算，页面对不上就是红。
    """
    kb, art = read_graph(cfg)
    pb = kb.get("playbook") or {}
    traps = kb.get("traps") or {}
    entries = kb.get("entries") or {}
    alias = (kb.get("index") or {}).get("alias") or {}

    families = []
    for fid, f in sorted(pb.items()):
        if not isinstance(f, dict):
            continue
        families.append({
            "id": fid,
            "title": f.get("title") or fid,
            "kind": f.get("kind"),
            "aliases": len(f.get("alias") or []),
            "symptoms": len(f.get("symptoms") or []),
            "causes": len(f.get("causes") or []),
            "fixes": len(f.get("fixes") or []),
            # ★ 字段名是 `runs`（带 s）—— 就是 `--list` 印的「可跑判据 N」
            "runs": len(f.get("runs") or []),
            # 「声明无锚点」是**诚实性**那一栏，不是缺陷栏（kb/README.md 的约定）
            "declared_no_anchor": len(f.get("unverified") or []),
            "traps": list(f.get("traps") or []),
            # ★ 左栏要**点得亮**：点一下必须真的查到这一条。别名表是"能点亮这个节点"
            #   的那份表，所以点它；存疑的说法（自己拼标题、截半句）都不是同一个东西。
            #   取到几个由 `aka` 自己带着 —— 页面不猜、不截。
            "aka": [a for a in (f.get("alias") or []) if isinstance(a, str)],
        })

    trap_rows = []
    for slug, t in sorted(traps.items()):
        if not isinstance(t, dict):
            continue
        # 与 ask.py 的判据**同式**（kb/ask.py `anchored = bool(traps.get(t).get("cases"))`）。
        # 两处各写一份的话，页面的「有锚点 12 / 只有人记着 2」会和 CLI 的 `--list` 对不上，
        # 而对不上的时候没人知道是哪边错。
        anchored = bool(t.get("cases"))
        trap_rows.append({
            "slug": slug,
            "title": t.get("title") or slug,
            "masquerades_as": t.get("masquerades_as") or "",
            "domains": list(t.get("domain") or []),
            "anchored": anchored,
            "unverifiable": t.get("unverifiable") or "",
            "aka": [a for a in (t.get("alias") or []) if isinstance(a, str)],
        })

    entry_rows = [{"id": eid, "slug": e.get("slug"), "title": e.get("title") or eid,
                   "domain": list(e.get("domain") or [])}
                  for eid, e in sorted(entries.items()) if isinstance(e, dict)]

    n_anchored = sum(1 for t in trap_rows if t["anchored"])
    return {
        "families": families,
        "traps": trap_rows,
        "entries": entry_rows,
        "counts": {
            "families": len(families),
            "traps": len(trap_rows),
            "traps_anchored": n_anchored,
            "traps_human_only": len(trap_rows) - n_anchored,
            "entries": len(entry_rows),
            "aliases": len(alias),
        },
        "ruler": _ruler(kb, cfg),
        "gate": {
            "url": "%s/checks/fleet" % cfg.api_prefix,
            "rows": ["C4.edges", "C4.instances"],
            "note": ("图谱自己的门禁结论**不在这里重算**：它已经落在 "
                     "data/_meta/checks/fleet.json，由上面那条路由读出来。"
                     "同一个结论两份实现 = 两份会漂的写法。"),
        },
        "source": dict(art, generated_by="kb/build_kb.py（原子写）"),
    }


def _ruler(kb: dict, cfg) -> dict:
    """这份产物是哪把尺子量的。

    ★ `criterion_version` 这个名字在本仓有**三个**出处（打包器 `kb/build_kb.py` /
    手册 `kb/playbook.json` / 陷阱表 `kb/traps.json`），所以一个都不许省 ——
    过去这里只报裸名那一个，于是页面印着 `criterion v1`，而真正决定结论的手册语义
    改到 v4 了它一动不动（`trap-same-field-name-different-artifact`，2026-09-24 修）。

    ★ 键名与 `kb/ask.py:ruler()` **逐字相同**，「谁是谁」的那句话也**取自产物**
    （`criterion_version_means`）—— 一个判断只许有一个出处：两处各写一遍，
    改了一处另一处照旧指着老名字，而这件事**不报错**。
    改这里的字段名就要同时改 `kb/ask.py:ruler`，`kg_view_accept.py --parity` 会红。
    """
    return {
        "version": kb.get("version"),
        "criterion_version": kb.get("criterion_version"),
        "criterion_version_means": kb.get("criterion_version_means"),
        "playbook_criterion_version": kb.get("playbook_criterion_version"),
        "traps_criterion_version": kb.get("traps_criterion_version"),
        "kb_self_sha12": kb.get("self_sha12"),
        "manifest_sha12": kb.get("manifest_sha12"),
        "gate_sha12": _sha12_of(_kbdir(cfg) / GATE_NAME),
        "sources": len(kb.get("sources") or {}),
    }


# ── 查询（扩散激活） ──────────────────────────────────────────────────

def _shape_problem(d: Any) -> str | None:
    """`ask.py` 的 JSON 该长什么样 —— 回 None 表示形状对。"""
    if not isinstance(d, dict):
        return "顶层不是对象（%s）" % type(d).__name__
    if d.get("state") not in STATES:
        return "state=%r 不在三态 %s 内" % (d.get("state"), list(STATES))
    if not isinstance(d.get("ruler"), dict):
        return "没有 ruler（分不清这个结论是哪把尺子量的）"
    if d.get("state") == "miss" and not isinstance(d.get("nearest"), list):
        return "state=miss 却不带 nearest[]（「查不到」必须带最近似的几条）"
    return None


def ask(cfg, q: str, building: str = "", top: int = 3) -> tuple[dict, dict]:
    """给一个说法，回 `ask.py --json` 的**原样**载荷 ＋ 传输层事实。

    ★ 回的是原样载荷（不改字段、不包一层）：**「页面与 CLI 同一份 JSON」这条验收
      本来就靠它成立**；在这里重新塑形，等于给同一份数据造第二个形状。
    """
    q = (q or "").strip()
    if not q:
        raise bad_request("缺查询词 q（一个说法，例如「楼层错位」）",
                          hint="GET %s/kg/ask?q=%s" % (cfg.api_prefix, "楼层错位"))
    if len(q) > _QUERY_MAX_CHARS:
        raise bad_request("查询词太长（上限 %d 字）" % _QUERY_MAX_CHARS, got=len(q))
    # ★ 开关形的词先拒（理由见 `_switch_like`）：它是命令行的开关位置，不是说法。
    #   整串与逐个词都查 —— 整串决定**此刻**会不会被当成开关，逐词是防调用方改成分词传参。
    for w in [q] + q.split():
        if _switch_like(w):
            raise bad_request(
                "查询词里不许出现开关形的词：%r —— 那是命令行的开关位置，不是说法"
                % w, q=q)
    b = (building or "").strip()
    if _switch_like(b):
        raise bad_request("楼号不许是开关形的词：%r（本域只做只读查询，"
                          "`--run`/`--pending` 一律走命令行）" % b, building=building)
    if b and not _BUILDING_RE.match(b):
        raise bad_request("楼号只接受字母数字与 -_（最多 32 位）", building=building)

    top_clamped_from = None
    if top > _MAX_TOP:
        top_clamped_from, top = top, _MAX_TOP
    elif top < 1:
        top_clamped_from, top = top, 1

    script = _kbdir(cfg) / ASK_NAME
    if not script.is_file():
        raise ApiError(500, "kg_engine_missing", "找不到图谱查询入口：kb/%s" % ASK_NAME)

    # ★ `--` 之后一律是查询词：没有它，`?q=--list` 会让「查一个说法」当场变成「列症状表」
    #   （两者都 exit 0，屏幕上分不出来 —— 实测 `_scratch/_sec_review_argv_probe.py` ②）。
    argv = [sys.executable, "-u", str(script), "--json", "--top", str(top), "--"]
    # 楼号**当一个词传**，不拼进查询串：ask.py 自己从词里认楼号
    # （kb/ask.py:main 的 `query = " ".join(words)` ＋ `building_in(words, query)`），
    # 在这里替它拼串就等于在本模块里复制一份它的解析规则。
    if b and b not in q:
        argv.append(b)
    argv.append(q)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")   # 不设必糊字（memory: gbk-mangled-log-units）
    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=str(cfg.root), env=env, timeout=_ASK_TIMEOUT_S,
                           capture_output=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as ex:
        raise ApiError(504, "kg_ask_timeout",
                       "查询超时（%ds）—— 子进程已被终止，**这不是「图里没有」**。"
                       "要复现请用命令行：python -u kb/ask.py %r --json"
                       % (_ASK_TIMEOUT_S, q)) from ex
    except FileNotFoundError as ex:
        raise ApiError(500, "kg_engine_missing", "命令起不来（解释器或脚本不在）：%s" % ex) from ex
    elapsed_ms = int((time.time() - t0) * 1000)

    out = p.stdout or ""
    err = (p.stderr or "").strip()
    try:
        ans = json.loads(out)
    except json.JSONDecodeError:
        # ★ 输出读不出 JSON ⇒ 如实报错，**绝不把 stdout 当结论渲染出去**。
        raise ApiError(502, "kg_ask_bad_output",
                       "查询输出不是 JSON（退出码 %s）—— 后端不当结论用" % p.returncode,
                       {"exit": p.returncode, "stderr_head": err[:400],
                        "stdout_head": out[:400]}) from None
    problem = _shape_problem(ans)
    if problem:
        raise ApiError(502, "kg_ask_bad_shape", "查询结果的形状不认识：%s" % problem,
                       {"exit": p.returncode, "stderr_head": err[:300],
                        "keys": sorted(ans)[:30] if isinstance(ans, dict) else None})
    return ans, {
        "exit": p.returncode,
        "elapsed_ms": elapsed_ms,
        "top": top,
        "top_clamped_from": top_clamped_from,
        "stderr_head": err[:300] or None,
        # 给人复现用：回**原样的 argv 列表**，不拼成一行 shell 串。
        # 拼串就得处理引号/负号，而那句拼出来的话一旦和真实 argv 不一致，照它复现
        # 就会得到一个**不同的查询** —— 第一版就撞上了（引号落到了 `--json` 后面，
        # 屏幕上看着像句正常的命令）。列表没有这个面。
        # ★ 回的是**真的那条 argv**，`--` 也在里面 —— 少一个元素，照它复现就会
        #   得到一个不同的东西（这正是本字段存在的理由）。
        "argv": ["python", "-u", "kb/ask.py", "--json", "--top", str(top), "--"]
                + ([b] if b else []) + [q],
    }
