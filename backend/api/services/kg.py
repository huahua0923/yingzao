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
2. **写操作各有各的口，但只许有一个写入口**：`ask.py --run` 跑判据并写
   `data/_meta/kg_runs.json` 与 `_qa/<楼>_qa.txt`，`--pending` 写 `kb/pending.json`
   —— 两条都是**写**。
   ★ 2026-09-25（P2 收编 8155，用户拍板）起，`--run` **有** HTTP 口子：
   `POST /kg/run`，挂在 `ComputeDep` 那个执行面闸门（`deps.exec_denied_reason`）上，
   回一个作业 id 就走，不在这里等结果。原先「`--run` **没有** HTTP 通路」那个更强的
   保证**已经放弃**，口径换成「通路 ＋ 本机限定」；`--pending` **仍然没有**通路。
   ⇒ 下面那两道边界守卫（拒 ＋ `--`）不是"因为只读"才存在，而是因为
   **一次只读查询不许被一个词偷偷变成写** —— 那会绕过闸门。
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
from . import jobs

GRAPH_NAME = "kb.json"
ASK_NAME = "ask.py"
GATE_NAME = "gate.py"
#: 扩散激活那张图（网页 canvas）的两份**机器层**来源。kb.json 那份是策展层。
INSTANCES_REL = "data/_meta/kg_instances.json"
PENDING_REL = "kb/pending.json"

#: `--run` 这条长活的上限（秒）。★ 900 是**从原文抄来的**，不是新定的：
#: 8155 那份页面（`_scratch/_retired_20260925/_kg_view.py:` POST `/api/ask`）用的就是 900。
#: 现在它走 `services.jobs`（真超时 + 真并发上限），而这套机制的缺省是
#: `cfg.job_timeout_s`（7200，给重建整栋三维那种活留的）⇒ 必须按作业覆盖，
#: 否则这条闸门对图谱这一支等于不存在。
RUN_TIMEOUT_S = 900
#: `kb/ask.py` 在「这个说法没有可跑判据」时打的那句话（`ask.py:1466`）。
#: ★ 它**就是**这一档的判据，所以抄成常量而不是在解析里现拼字符串：
#:   同一句话写两遍，改了一处另一处照旧匹配不上，而匹配不上会**退化成**
#:   「输出解析不出来」—— 一个看着更严重、其实指错方向的结论。
NO_CRITERIA_MARK = "没有可跑判据"

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
      `--run` 是**独立的一项** ⇒ `ask.py` 照收 ⇒ 一次只读的 `GET /kg/ask` 会真跑判据
      并写 `data/_meta/kg_runs.json`；换成 `--pending` 则写 `kb/pending.json`。
      ★ 别把它读成"反正现在也有 `POST /kg/run` 了"：那条是**同一个执行面闸门**
      （`ComputeDep`）下**有意开的**入口，这条是绕过它的**暗门** ——
      两条路的分界恰恰是"谁有权执行"，暗门让那个分界形同虚设。
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


def query_argv(cfg, q: str, building: str = "", top: int = 3,
               do_run: bool = False) -> tuple[list, dict]:
    """把「一个说法」变成递往 `kb/ask.py` 的**子命令 argv**（不含解释器）＋ 元信息。

    ★ 回的是 `kb/ask.py` 那一串，**解释器由调用方加**：只读查询走 `subprocess.run`
      要自带 `[sys.executable, "-u"]`，长活走 `services.jobs.start`（它自己加）——
      把解释器缝进返回值里，就得让 `jobs` 去切列表（`argv[2:]`），
      而那种"按下标认识自己"的写法改一次头就静默错位。

    ★ **两处调用共用这一份**：只读查询（`ask()`）与长活 `--run`（`run_spec()`）。
      各拼一遍的代价不是重复，是**漏**：`--` 那道防线（见下）只需要其中一个忘了写，
      注入面就回来了 —— 而"另一个地方写对了"在屏幕上一点都看不出来
      （本仓铁律 29：一个判断只许有一个实现）。

    ★ `--` 之后一律是查询词：没有它，`?q=--list` 会让「查一个说法」当场变成「列症状表」
      （两者都 exit 0，屏幕上分不出来 —— 实测 `_scratch/_sec_review_argv_probe.py` ②）。
      `--run` 这个开关**加在 `--` 之前**：词永远只是词，成不了开关。
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
                "查询词里不许出现开关形的词：%r —— 那是命令行的开关位置，不是说法。"
                "（要真跑判据请用本域的跑判据入口，它把 `--run` 加在 `--` 之前，"
                "你敲的词永远只是词。）" % w, q=q)
    b = (building or "").strip()
    if _switch_like(b):
        raise bad_request("楼号不许是开关形的词：%r（楼号只能是字母数字）" % b,
                          building=building)
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

    argv = [str(script), "--json", "--top", str(top)]
    if do_run:
        argv.append("--run")
    argv.append("--")
    # 楼号**当一个词传**，不拼进查询串：ask.py 自己从词里认楼号
    # （kb/ask.py:main 的 `query = " ".join(words)` ＋ `building_in(words, query)`），
    # 在这里替它拼串就等于在本模块里复制一份它的解析规则。
    if b and b not in q:
        argv.append(b)
    argv.append(q)
    return argv, {"q": q, "building": b, "top": top,
                  "top_clamped_from": top_clamped_from,
                  # 给人复现用：**原样的 argv 列表**（`--` 与 `--run` 都在里面），
                  # 解释器写成 `python`。少一个元素，照它复现就会得到一个不同的东西。
                  "argv": ["python", "-u", "kb/ask.py", "--json", "--top", str(top)]
                          + (["--run"] if do_run else []) + ["--"]
                          + ([b] if b else []) + [q]}


def ask(cfg, q: str, building: str = "", top: int = 3) -> tuple[dict, dict]:
    """给一个说法，回 `ask.py --json` 的**原样**载荷 ＋ 传输层事实。

    ★ 回的是原样载荷（不改字段、不包一层）：**「页面与 CLI 同一份 JSON」这条验收
      本来就靠它成立**；在这里重新塑形，等于给同一份数据造第二个形状。
    """
    argv, meta = query_argv(cfg, q, building=building, top=top, do_run=False)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")   # 不设必糊字（memory: gbk-mangled-log-units）
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-u"] + argv, cwd=str(cfg.root), env=env,
                           timeout=_ASK_TIMEOUT_S,
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
    # 给人复现用：回**原样的 argv 列表**（由 `query_argv` 给的那一份），不拼成一行
    # shell 串。拼串就得处理引号/负号，而那句拼出来的话一旦和真实 argv 不一致，
    # 照它复现就会得到一个**不同的查询** —— 第一版就撞上了（引号落到了 `--json`
    # 后面，屏幕上看着像句正常的命令）。列表没有这个面。
    return ans, dict(meta, exit=p.returncode, elapsed_ms=elapsed_ms,
                     stderr_head=err[:300] or None)


# ── 扩散激活那张图（canvas 要的那份数据） ────────────────────────────
#
# ★ 为什么节点与边在**后端**算（而不是像 8155 那样在页面里拼）：图上有一层语义 ——
#   「机器数出来的缺陷码 / 实测旗映射到哪个症状」「哪些还没映射（**缺口**）」。
#   把那一支搬进第二个页面就是**同一份判断的第二个实现**，两边必然漂
#   （memory: one-judgement-many-implementations）。现在这里是产物的**投影**，
#   `frontend/admin/js/views/kg.js` 只负责**摆放**（放射布局 = 表现，不是判断）。
#   投影只读 `kb/kb.json` 与 `data/_meta/kg_instances.json`，**不重算任何判据**：
#   映射关系（`family` 字段）是 `kb/build_kg_instances.py` 写进产物的那一份。

#: 短名的取法（与 8155 那份页面 `_scratch/_retired_20260925/_kg_view.html` 的 `shortTitle` 同式）。
_SHORT_PAREN_RE = re.compile(r"（.*?）")


def _short_title(t: Any) -> str:
    """家族标题的短名：去掉全角括号里的补语、截 14 字。纯展示规则。"""
    return _SHORT_PAREN_RE.sub("", str(t or ""))[:14]


def _read_json_rel(cfg, rel: str) -> tuple[Any, str | None]:
    """读一份本机 JSON 产物 → `(载荷, 问题)`。问题非 None ⇒ 载荷是 None。

    ★ 「文件不在」与「在但读不动」分开说（`read_graph` 同一个理由），而且
      **绝不回空对象兜底**：空对象在屏幕上与"这一节本来就是空的"长得一样
      （铁律 16），而这两件事的补救办法完全不同（跑生成脚本 vs 修那个文件）。
    """
    p = Path(cfg.root) / rel
    if not p.is_file():
        return None, "缺 %s" % rel
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        return None, "%s 读不动：%s: %s" % (rel, type(ex).__name__, ex)


def graph(cfg) -> dict:
    """扩散激活那张图：节点 / 边 / **缺口** ＋ 两份机器层源的可用性。

    节点 id 的三种前缀（`fam:` / `trap:` / `ent:`）与
    `frontend/admin/js/views/kg.js:wordFor()` 认的那三种**逐字一致** ——
    前缀拼错的话，图上点一个节点会跳到别的家族，而**那种错不报错**。
    """
    kb, art = read_graph(cfg)
    pb = kb.get("playbook") or {}
    tr = kb.get("traps") or {}
    en = kb.get("entries") or {}
    inst, inst_problem = _read_json_rel(cfg, INSTANCES_REL)
    pend, pend_problem = _read_json_rel(cfg, PENDING_REL)
    I = inst if isinstance(inst, dict) else {}

    nodes: list = []
    edges: list = []
    seen: set = set()

    def add(nid: str, label: Any, kind: str, **extra) -> None:
        if nid in seen:
            return
        seen.add(nid)
        nodes.append(dict(id=nid, label=label, kind=kind, **extra))

    def link(a: str, b: str, kind: str) -> None:
        edges.append({"a": a, "b": b, "kind": kind})

    def field(v: Any, key: str) -> Any:
        """一条 what/cmd 之类的值：认 dict 就取那个键，认不出就回 None。

        ★ 与 8155 那边 `c.what` 的宽松程度对齐（那里取不到就是 `undefined`，
          键整个不进 JSON）。这里取不到就 `None` —— 同样是"没有这个字段"。
        """
        return v.get(key) if isinstance(v, dict) else None

    for slug, f in pb.items():
        if not isinstance(f, dict):
            continue
        fid = "fam:" + slug
        add(fid, _short_title(f.get("title")), "symptom",
            slug=slug, full=f.get("title") or slug)
        for kind, key, cname in (("cause", "causes", "根因"), ("fix", "fixes", "处置"),
                                 ("run", "runs", "命令")):
            for j, c in enumerate(f.get(key) or []):
                nid = "%s:%s:%d" % (kind, slug, j)
                add(nid, cname, kind, full=field(c, "cmd" if kind == "run" else "what"))
                link(fid, nid, kind)

    for k, t in tr.items():
        add("trap:" + k, field(t, "title") or k, "trap",
            slug=k, full=field(t, "mechanism"))
    for slug, f in pb.items():
        if not isinstance(f, dict):
            continue
        for t in (f.get("traps") or []):
            # 认不出的坑**不画一条悬空的边**（8155 那边同样是"只在已存在的节点上连"）。
            if ("trap:" + str(t)) in seen:
                link("fam:" + slug, "trap:" + str(t), "trap")

    for k, e in en.items():
        if not isinstance(e, dict):
            continue
        eid = "ent:" + k
        add(eid, e.get("title") or k, "entry", slug=k,
            full=" / ".join(str(x) for x in (e.get("standard") or [])))
        for r in (e.get("recognition") or []):
            if not isinstance(r, dict) or not r.get("drafting"):
                continue
            gid = "geom:" + str(r["drafting"])
            # ★ `noimpl` 是这一格的**诚实性**标记（声明了但仓内没有实现/锚点），
            #   与"这一格是空的"不是一回事 —— 悬停时要看得出来。
            add(gid, r["drafting"], "geom", full=r.get("criterion") or "",
                noimpl=not r.get("evidence"))
            link(eid, gid, "geom")

    def machine(rows: Any, kind: str, prefix: str, head: str) -> None:
        """机器层：缺陷码 / 实测旗。**没映射到症状的那几个就是图上的缺口。**"""
        if not isinstance(rows, dict):
            return
        for key, v in rows.items():
            if not isinstance(v, dict):
                continue
            fam = v.get("family")
            n = v.get("n")
            if kind == "code":
                full = ("缺陷码 %s（%s）%s 行" % (key, v.get("group") or "", n))
            else:
                full = ("实测旗 %s ×%s" % (key, n))
            full += (" → " + fam) if fam else " → ★还没映射到任何症状"
            add(prefix + str(key), key, kind, n=n, mapped=bool(fam), full=full)
            if fam and ("fam:" + str(fam)) in seen:
                link(prefix + str(key), "fam:" + str(fam), kind)

    machine(I.get("codes"), "code", "code:", "缺陷码")
    machine(I.get("flags"), "flag", "flag:", "实测旗")

    orphans = [n for n in nodes if n["kind"] in ("code", "flag") and not n.get("mapped")]
    by_kind: dict = {}
    for n in nodes:
        by_kind[n["kind"]] = by_kind.get(n["kind"], 0) + 1
    pending_rows = pend.get("pending") if isinstance(pend, dict) else None

    return {
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "nodes": len(nodes), "edges": len(edges),
            "orphans": len(orphans),
            # 分母逐类打出来：只报总数的话，"某一类整个没画出来"看不出来
            # （铁律 23：判据全绿先问它在全部样本上是不是取极值）。
            "by_kind": by_kind,
        },
        # ★ 缺口**逐条列出来**，不只给一个数：一个数没法回答"缺的是谁"，
        #   而这张图的存在意义之一就是让缺口看得见（canvas 把它们画成虚线空心）。
        "unmapped": [{"id": n["id"], "label": n["label"], "kind": n["kind"],
                      "full": n.get("full")} for n in orphans],
        # 两份机器层源的可用性：`None` = 读到了。★ 读不到时**上面那些机器节点
        # 一个都不会有** —— 「缺文件」与「机器层本来就是空的」在屏幕上必须分开。
        "missing": {k: v for k, v in
                    (("instances", inst_problem), ("pending", pend_problem)) if v},
        "pending": {
            "state": "ok" if isinstance(pending_rows, list) else ("missing" if pend_problem else "empty"),
            "note": pend_problem or "",
            "rows": [r for r in (pending_rows or [])][:50],
            "n": len(pending_rows) if isinstance(pending_rows, list) else None,
        },
        "source": dict(art, generated_by="kb/build_kb.py（原子写）",
                       instances=INSTANCES_REL, pending=PENDING_REL),
    }


# ── `--run`：真跑图里登记的判据（长活，走 services.jobs） ─────────────

def run_spec(cfg, q: str, building: str = "", top: int = 3,
             timeout_s: int | None = None) -> dict:
    """`--run` 那条长活的规格：子命令 argv（不含解释器）＋ 解析好的超时 ＋ 元信息。

    ★ **为什么不在这里 `subprocess.run`**：这条命令跑的是判据，最坏 900 秒，而且
      它真的会写盘（`_qa/<楼>_qa.txt`、`data/_meta/kg_runs.json` —— 都是引擎自己
      声明的副作用）。裸挂在请求处理里 = 把管理台所有屏一起拖住，且没有真超时、
      没有并发上限（`settings.py` 里那两个"声明了却没执行"的设置）。
      ⇒ 走 `services.jobs`：真超时、真并发、日志落文件（铁律 14：PIPE 不抽干 = 死锁）。

    ★ `timeout_s` **只能缩短**：给了就用（夹到 `[1, RUN_TIMEOUT_S]`），没给就是
      `RUN_TIMEOUT_S`。夹了**要说**（回 `timeout_clamped_from`）—— 悄悄夹住会让
      调用方以为它要的就是这个数（与 `top_clamped_from` 同一个理由）。

    ★ 回 `timeout_source`，并**原样带进作业的 extra**：这个作业的超时是**本域
      自己的 `RUN_TIMEOUT_S`**，不是 `settings.job_timeout_s`（那个是 7200）。
      不写下来，事后只看作业记录会以为"它按设置的缺省跑的"
      （铁律 24 的同族：产物要知道自己是哪把尺子量的）。
    """
    argv, meta = query_argv(cfg, q, building=building, top=top, do_run=True)
    clamped_from = None
    if timeout_s is None:
        limit, source = RUN_TIMEOUT_S, "kg_run_default"
    else:
        try:
            limit = int(timeout_s)
        except (TypeError, ValueError):
            raise bad_request("timeout_s 要一个整数秒（上限 %d）" % RUN_TIMEOUT_S,
                              timeout_s=timeout_s) from None
        if limit < 1:
            raise bad_request("timeout_s 至少 1 秒（它只能把超时改**短**，"
                              "不许把一个长活变成不判超时）", timeout_s=timeout_s)
        if limit > RUN_TIMEOUT_S:
            clamped_from, limit = limit, RUN_TIMEOUT_S
        source = "caller"
    return {"argv": argv, "timeout_s": limit, "timeout_source": source,
            "timeout_clamped_from": clamped_from,
            "meta": meta, "query": meta["q"], "building": meta["building"]}


#: 读日志尾巴这件事**不在这里实现** —— 它是 `jobs.log_tail`（上限也在那边
#: `jobs.LOG_TAIL_BYTES`）。控制台的 `jobs/<id>` 读的是**同一批**日志文件，
#: 两份实现会出现"这里截在 512KB、那里截在别处"，而两边都不报这件事
#: （memory: one-judgement-many-implementations）。


def parse_tail_json(text: str) -> Any:
    """从 stdout 里取**最后一个 JSON 对象**；取不到回 None。

    ★ `--run` 时 `ask.py` 先往 stdout 打「将跑 N 条…／退出码 x」这些**给人看**的行，
      最后才打 JSON（`kb/ask.py:1471`）⇒ `json.loads(整个 stdout)` 必然失败，
      而失败**长得像「图里没有」**（铁律 16：量具坏了与被测对象是空的，屏幕上一样）。
      所以退一步找**最后一个从行首开始的 `{`** —— `indent=1` 的 JSON 只有顶层那个
      `{` 落在第 0 列，所以这个锚点是唯一的。
    ★ 解析不出来就回 None，由调用方**如实说"读不出 JSON"**，绝不兜成一个空结果。
    """
    try:
        return json.loads(text)
    except ValueError:
        pass
    i = text.rfind("\n{")
    if i < 0:
        return None
    try:
        return json.loads(text[i + 1:])
    except ValueError:
        return None


#: 一条 `--run` **跑出了什么**。★ `outcome` 与作业层的 `state` 是**两个问题**：
#: `state` 说"进程怎么样"（running / ok / failed / timeout），`outcome` 说"这次
#: 有没有拿到结论"。合成一个字段的后果是：一个退出码 0、输出却读不出来的跑，
#: 会被"退出码 0"盖成一切正常（铁律 20：形式检查通过、语义没发生）。
RUN_OUTCOMES = ("running", "ok", "no_criteria", "unparsable", "bad_shape",
                "timeout", "lost")

_OUTCOME_WHY = {
    "running": "还在跑。★这一档不是「没有结论」，是「还没跑完」—— 页面应当继续轮询。",
    "ok": "拿到了 `run_result`（真跑出了结论）。退出码与状态另看 `state`/`exit_code`。",
    "no_criteria": "引擎原话是「没有可跑判据（不猜命令）」—— 这个说法**本身**没有"
                   "登记判据（`state` 不是 hit）。★不是「没查过」，也不是「没问题」。",
    "unparsable": "有输出但**读不出 JSON** ⇒ 这次跑没得出结论。原始输出在下面，"
                  "原样给你，不当结论用。",
    "bad_shape": "JSON 读出来了，但没有 `run_result` 一节 ⇒ 形状不认识，不当结论用。",
    "timeout": "到点被杀（超时）。★这不是「没问题」，是「没跑完」。",
    "lost": "作业记录读不出来（进程重启且终态 JSON 损坏）⇒ 这一趟没有结论可看。",
}
# ★ 档位与说辞必须一一对上。少了哪一句，`.get(outcome, "")` 会**静默**给一个空字符串
#   （屏幕上就是"没有理由"），而"我漏写了一档"与"这一档本来就没原因"长得一样。
#   所以在**导入时**就把它吵出来，不是在渲染时兜底。
if set(_OUTCOME_WHY) != set(RUN_OUTCOMES):
    raise RuntimeError(
        "RUN_OUTCOMES 与 _OUTCOME_WHY 对不上（多=%s 少=%s）—— 每一档都要有一句"
        "自己的话，否则那一档在屏幕上没有理由"
        % (sorted(set(RUN_OUTCOMES) - set(_OUTCOME_WHY)),
           sorted(set(_OUTCOME_WHY) - set(RUN_OUTCOMES))))


def run_report(rec: dict) -> dict:
    """一份作业记录 → 这条 `--run` **到底跑出了什么**。回 `dict(rec, run={...})`。

    ★ 档位必须分得开，因为它们**补救办法不同**：
      · `running`     —— 还没跑完（页面继续轮询，**不许**说成"读不出结论"）
      · `ok`          —— JSON 里有 `run_result`（真跑出了结论）
      · `no_criteria` —— 引擎明说没有可跑判据（`state != hit`，`ask.py` 一行 JSON 都不打）
      · `unparsable`  —— 有输出、读不出 JSON
      · `bad_shape`   —— JSON 读得出、但没有 `run_result`
      · `timeout`     —— 作业层判的超时
      · `lost`        —— 作业记录本身坏了
      ★ 把 `no_criteria` 与 `unparsable` 合成一行字，正是本仓最恨的那种安静假话
        （前者是"这个说法本来就没有判据"，后者是"这次输出坏了，去看日志"）；
        而把 `running` 混进 `unparsable` 更坏 —— 一次正常的中间态会被报成故障。
      ⇒ 所以 `state == "running"` **先判**，且不读日志（那份文件此刻还在长）。
    """
    state = rec.get("state")
    lines: list = []
    truncated = None
    obj = None
    if state == "running":
        outcome = "running"
    elif state == "lost":
        # 记录读不动（`jobs._read_persisted` 判的）—— 别再拿日志去解析，那只会
        # 把"记录坏了"说成"输出读不出来"，指错方向。
        outcome = "lost"
    else:
        text, truncated = jobs.log_tail(rec.get("log"))
        obj = parse_tail_json(text)
        if state == "timeout":
            outcome = "timeout"
        elif obj is None:
            outcome = "no_criteria" if NO_CRITERIA_MARK in text else "unparsable"
        elif isinstance(obj.get("run_result"), dict):
            outcome = "ok"
        else:
            outcome = "bad_shape"
        lines = [l for l in text.splitlines() if l.strip()]
    run_result = obj.get("run_result") if isinstance(obj, dict) else None
    run_result = run_result if isinstance(run_result, dict) else None
    return dict(rec, run={
        "outcome": outcome,
        # 每一档的话在导入时已确认存在，这里不必再兜底（兜底会掩盖漏写的档）。
        "why": _OUTCOME_WHY[outcome],
        # ★ 结论与原始输出**一起给**：只给结论的话，一个 `ok` 也看不出引擎当时
        #   打了哪些"退出码 x"的行；只给输出的话，前端得自己解析（= 第二份实现）。
        "json": obj if isinstance(obj, (dict, list)) else None,
        "results": run_result.get("results") if run_result else None,
        "ledger": run_result.get("ledger") if run_result else None,
        # 原始输出的最后 40 行：解析不出来时它就是唯一的证据，
        # 所以**一直带**，不是只在出错时才带。`running` 时日志还在长 ⇒ 空。
        "raw_tail": "\n".join(lines[-40:]),
        "raw_lines": len(lines),
        "log_truncated_bytes": truncated,
        # 这个作业的超时是**哪个数、谁定的**。★ 不写下来的话，事后只看作业记录
        #   会以为"它按设置里的缺省跑的"（那个缺省是 7200，不是这个数）。
        "timeout_s": rec.get("timeout_s"),
        "timeout_source": rec.get("timeout_source") or "unknown",
        "exit_code": rec.get("exit_code"),
    })
