# -*- coding: utf-8 -*-
"""逐条边复核 —— 图谱的**门禁**。任一条失败即红。

## 为什么它是全案的心脏

图谱不抄值、只存边（`kb/README.md` 护栏 1）。**但边自己也会过期**：
文件被改名、行号被撑出范围、符号被删、值被改、散文与代码两份写法漂开。
这些**全都不报错**——引用一条不存在的行，读的人拿到的是「没事」，不是「坏了」。

所以每一条边都要能被机器复核，而且**复核的结论要分得清「过了」和「没量成」**
（`UNAVAILABLE ≠ PASS`，抄 `backend/checks/findings.py:27` 的词表，不另造一套）。

## 八条判据

    ① 路径可达     evidence 指的文件在盘上
    ② 行号在范围   `file:128` 的 128 ≤ 该文件实际行数（越界是静默失效的典型）
    ③ 符号真在     `file:SYM` 的 SYM 真在那个文件里 —— ★ 用 AST，**不许 grep**
    ④ 值漂移       §3 宣称值 vs 代码真值（委派 `values.py`，它自带阳性对照）
    ⑤ 双源一致     图层语义：prose（`kb/src/05,07`）↔ `LAYER_ROLE`（代码）
    ⑥ 陈旧即红     证据文件的**内容 sha12** 与登记时不同 ⇒ 依赖它的边全部待复核
    ⑦ --run 只读   登记的命令形里出现写操作 ⇒ 拒绝登记
    ⑪ ASCII 引号   `"` 被当成中文引号用（铁律 15）—— 见 `check_cjk_quotes`
    ⑫ 图 out/in    双向邻接由边派生，且**互为逆表**（手改任一侧即红）—— 见 `check_graph`

（编号从 ⑦ 跳到 ⑪：⑧⑨⑩ 是**刑具组**的号，不是判据号，保持原号免得与既往记录对不上。）

**陷阱（`kb/traps.json`）不是第八条判据**，它是**边的第二个来源**：陷阱的
`cases[].where` 与 `kb.json` 的 evidence 走同一套 ①②③。唯一多出来的是**分栏**：
**有锚点的**计入上面的边，**没锚点的**（`cases` 为空、写了 `unverifiable` 理由的）
单列出来报 —— 因为「只有人记着」和「有仓内锚点」在屏幕上必须不是同一行字
（同 `UNAVAILABLE ≠ PASS` 的道理）。`traps.json` 不在盘上 ⇒ 这一类**没被查过**，不是「没有陷阱」。

## 三条自我约束

1. **★ 分母必须写出来。** 「复核了 40 条边」和「40 条边全对」不许长得一样；
   更要紧的是 **「一条边都没复核」也不许长得像「全对」**（K1 阶段 playbook 还没建，
   ⑦ 的待检命令数就是 0 —— 必须明写 0，不是绿）。
2. **不许 grep。** `grep` 数的是文本事实，注释会被算成代码（本仓栽过三次）。
   判符号一律 `ast.parse`，注释与字符串天然看不见。
3. **按文件名猜位置会造假红。** 本仓实伤：`detect_doors` 不在 `openings.py` 而在
   `geometry.py:1408` —— 当时据此报了假红并已向用户更正。所以 ① 只认 evidence
   **自己写的**路径，找不到就报「不在盘上」，**不替它猜**。

## 用法（本仓不用 argparse；不认 --help）

    python -u kb/gate.py                 # 复核，有红则退出码 1
    python -u kb/gate.py --selftest      # 十二条刑具，每条都要能红
    python -u kb/gate.py --record        # 记下证据文件的内容指纹（kb/evidence-lock.json）
    python -u kb/gate.py --cjk-baseline  # 重登记 ⑪ 仓内 .md 档基线（会逐条打出新增命中）
    python -u kb/gate.py --json
"""
from __future__ import annotations

import ast
import glob
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile

# ★ 必须自己把 stdout 摆成 utf-8：本文件会打「④ 值漂移（阈值表 ↔ 代码）」这类字符，
#   而 Windows 的管道 stdout 默认是 GBK ⇒ **打印这行时自己崩**（实测：
#   `UnicodeEncodeError: 'gbk' codec can't encode character '↔'`，退出码 1）。
#   后果不是「报错」，是**假红**：调用方（backend/checks、CI）拿到退出码 1 与半截输出，
#   读成「图谱有问题」—— 而这正是本仓 trap-decoding-mojibake-eats-structure 的形状：
#   **量具被环境噎住，报出来的错却长在被测对象身上**。
#   两头都得管：这里设自己，调用方另设 PYTHONIOENCODING（见 backend/checks/kg_citation.py）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

KB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KB)
KBJSON = os.path.join(KB, "kb.json")
TRAPS = os.path.join(KB, "traps.json")
PLAYBOOK = os.path.join(KB, "playbook.json")
LOCK = os.path.join(KB, "evidence-lock.json")

#: 手写版本号。判据语义（复核哪几条、怎么算不合格）改了才 +1。与机械 sha12 并存。
#: v2（2026-09-24）：加 ⑪「ASCII 引号当中文引号」（铁律 15）。**这是一次语义变更** ——
#:   v1 量过的东西全部照旧，但「这份 gate 结果合格」的含义变了：v1 的绿勾不含引号这一项。
#:   所以凡是拿 v1 的结论当「全绿」的地方，都得知道它少量了一档（铁律 24：换了尺子的产物
#:   与对的产物在屏幕上一样）。
#: v3（2026-09-24）：加 ⑫「图 out/in 互为逆表」。同上：v2 的绿勾不含「产物里的双向邻接
#:   与边一致」这一项 —— 一份 v2 的 ``图: PASS`` 只能说那批边本身没错。
CRITERION_VERSION = 3

_FLAGS = ("--selftest", "--record", "--anchors", "--json", "--cjk-baseline")

#: `file:128` 还是 `file:SYM`：冒号后全是数字 ⇒ 行号，否则是符号名。
_EV_LINE = re.compile(r"^(?P<f>[^:]+):(?P<n>\d+)$")
_EV_SYM = re.compile(r"^(?P<f>[^:]+):(?P<s>[A-Za-z_][\w.\[\]\"'()（）\-]*)$")

#: 中文语义词 → 代码里的 role 名。这是**唯一的换算口径**，两边都往这里靠。
_ROLE_CN = {"面积": "area", "房间号": "number", "用途": "purpose", "单位": "dept",
            "使用单位": "dept", "房间用途": "purpose"}

#: ⑦ 写操作黑名单。★ 这是**黑名单**，不是证明 —— 老实说它挡不住「换个写法的写」，
#:   它挡的是本仓实际会手滑敲的那几个（一次 `--apply` 就能把人工修复冲掉）。
_WRITE_TOKENS = ("--apply", "--write", "--save", "--fix", "--commit", "-o", "--out",
                 "-w", ">", ">>", ">|")

#: ⑦ 只允许这些**只读**入口开头。改这条要连带说明为什么新入口是只读的。
#: ★ 2026-09-24 加 `python -u qa_`：`qa_structural.py` / `qa_defect_census.py` 的**真身
#:   在仓库根**（`backend/checks/qa_structural.py` 不存在 —— 那是 `heavy.py` 去调它的包装），
#:   而「漏墙 / 糊块 / 并块」这三类症状的判据**只活在这两个脚本的产物里**
#:   （`runner.py` 只包了 qa_structural 的 B1，包不到 census）。不放行 = 那三类症状
#:   在图谱里**没有可跑的判断**，只能靠人念 —— 那正是本图谱要消灭的东西。
#: ⚠ **但它们不是无副作用的**：两者都会写 `_qa/<楼>_qa.txt` / `_qa/defect_<楼>.json`
#:   （可重生成的报告，不碰交付物）。所以 ⑦ 另立一条硬要求：**每条 run 必须写 `writes`**，
#:   把副作用摆在登记表里 —— 「只读」不许是一句没人验的空话。
#: ★ 2026-09-24 再补 `python -u scan_`：`scan_defects.py` 是「并块 / 重复房号」这一族唯一
#:   能逐条给出实例的判据。**先修入口、再放行**：它原先单栋跑会把全库台账原子写覆盖成只剩
#:   该栋，现由 `out_paths()` 按范围分址（点名跑落 `defects_partial.json`，够不着全库那两份），
#:   并由 `--selftest` 的三条范围守卫 ＋「产物必须落在 `_qa/` 内」的断言卡住。
#:   ⚠ 与 `qa_*` 一样**不是无副作用的**：`writes` 必须写明落哪两份文件。
_READONLY_PREFIX = ("python -u backend/checks/", "python -u kb/", "python -u _qa/",
                    "python -u qa_", "python -u scan_")


# ── 共用小工具 ──────────────────────────────────────────────

def sha12(data: bytes) -> str:
    """指纹规则 —— **全仓一份**（与 `backend/state/roster.py:sha12`、`kb/build_kb.py` 同义）。"""
    return hashlib.sha256(data).hexdigest()[:12]


def _self_sha12() -> str:
    with open(os.path.abspath(__file__), "rb") as fh:
        return sha12(fh.read())


def _file_sha12(name: str) -> str:
    """同目录下某把尺子的指纹（用于报出**委派**出去的判据是哪一版）。"""
    data = _read_bytes("kb/" + name)
    return sha12(data) if data else "missing"


def _read_bytes(rel: str) -> bytes | None:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _read_text(rel: str) -> str | None:
    b = _read_bytes(rel)
    return None if b is None else b.decode("utf-8", errors="replace")


def _status():
    """借 `findings.py` 的**状态词表**，但不走 `backend.checks` 的 `__init__`
    （那里拖一堆重依赖，会让门禁因为无关原因挂掉）。
    一个事实一份写法：状态词只有那一处定义。"""
    p = os.path.join(ROOT, "backend", "checks", "findings.py")
    spec = importlib.util.spec_from_file_location("kg_status", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Status


# ── 边：从 kb.json 收来 ─────────────────────────────────────

def traps_table(payload: dict | None) -> dict:
    """这次复核用的**陷阱表**。产物里带了就以产物为准，没带才回落到盘上的 `traps.json`。

    ★ 为什么要这条规矩（2026-09-24 修）：原先 `collect_edges(payload)` 用 payload 判
      识别边、却**掉头去读盘上的 traps.json** 收陷阱边。后果不是报错，是**两份来源**：
      kb.json 一旦比 traps.json 旧（改了源忘了重建），①②③ 复核的是**文件里的**那批陷阱，
      而 ⑧ 报的条数也是文件里的那批 —— 屏幕上一片绿，**产物里那份陷阱表一次都没被核过**。
      与 `one-judgement-many-implementations` 同族：一个判断落成两份实现，而两份不会一起说话。
    ★ `traps: {}` 也算「带了」—— 它是「这个产物没有陷阱」这条**宣称本身**，
      不许被盘上的文件偷偷替换（那正是上面这条缺陷的镜像）。
    """
    if isinstance(payload, dict) and isinstance(payload.get("traps"), dict):
        return payload["traps"]
    if not os.path.exists(TRAPS):
        return {}
    return json.loads(io.open(TRAPS, encoding="utf-8").read()).get("traps") or {}


def collect_edges(payload: dict | None = None) -> list[dict]:
    """图谱里所有**可复核的边**：每条带 `src`（谁在宣称）＋ `evidence`（据什么）。

    三个来源：`kb.json` 的识别映射边、`traps.json`（或产物里的 `traps` 一节）、
    `playbook.json`（或产物里的 `playbook` 一节）。
    三处的 `evidence` 走**同一套**复核（路径/行号/符号），不放宽 ——
    陷阱的理由可以写得再漂亮，它的锚点照样要能在仓里指出来。
    """
    if payload is None:
        payload = json.loads(io.open(KBJSON, encoding="utf-8").read())
    edges: list[dict] = []
    for slug, e in (payload.get("entries") or {}).items():
        for i, rec in enumerate(e.get("recognition") or []):
            edges.append({"src": "%s.recognition[%d]" % (slug, i),
                          "what": rec.get("drafting") or "", "evidence": rec.get("evidence")})
        for rel in e.get("related") or []:
            edges.append({"src": "%s.related" % slug, "what": "关联代码", "evidence": rel})
    edges.extend(collect_trap_edges(traps_table(payload))[0])
    edges.extend(collect_playbook_edges(payload)[0])
    return edges


#: 手册一个家族里的六栏 —— **字段表写死**（`kb/README.md` 回写协议第 1 步：不许自造字段）。
#: 只列「承载锚点」的栏：`title`/`alias`/`kind` 是索引用的，不是宣称，不收成边。
_PB_ITEMS = ("symptoms", "causes", "fixes", "instances", "related", "runs")


def collect_playbook_edges(payload: dict | None) -> tuple[list[dict], list[dict], list[dict]]:
    """手册（症状→根因→处置→判据）的边。返回 `(可核边, 缺据的条, 声明无锚点的条)`。

    ★ 三栏，不是两栏 —— 手册与陷阱有一处不同：它**允许**如实写 `unverified[]`
      （只来自实战、仓里确实指不出来）。那是**声明**，不是漏写。
      但「声明无锚点」和「忘了写 evidence」必须落在**两个**栏里：
      前者是诚实，后者是缺陷。屏幕上长得一样，就等于把后者当成了前者
      （`UNAVAILABLE ≠ PASS` 的同一条道理）。
    """
    fams = (payload or {}).get("playbook") or {}
    edges: list[dict] = []
    bare: list[dict] = []
    declared: list[dict] = []
    for fslug, fam in fams.items():
        title = fam.get("title") or ""
        for key in _PB_ITEMS:
            for i, item in enumerate(fam.get(key) or []):
                src = "pb:%s.%s[%d]" % (fslug, key, i)
                if not isinstance(item, dict):
                    bare.append({"slug": fslug, "title": title,
                                 "reason": "第 %d 条 %s 不是对象" % (i, key)})
                    continue
                what = (item.get("what") or item.get("where") or item.get("cmd") or "")
                if not item.get("evidence"):
                    # ★ 缺 evidence 的条目**不许静默消失** —— 它长得像「已登记」，
                    #   实则没有地址可核（门禁 ①②③ 无从下手）。
                    bare.append({"slug": fslug, "title": title,
                                 "reason": "第 %d 条 %s 没写 evidence：%s"
                                           % (i, key, what[:40] or "(没写是什么)")})
                    continue
                edges.append({"src": src, "what": what, "evidence": item["evidence"]})
        for u in (fam.get("unverified") or []):
            u = u if isinstance(u, dict) else {}
            declared.append({"slug": fslug, "title": title,
                             "what": u.get("what") or "", "reason": u.get("reason") or "未写理由"})
    return edges, bare, declared


def collect_trap_edges(traps: dict | None = None) -> tuple[list[dict], list[dict]]:
    """返回 `(可核的陷阱证据边, 无锚点的陷阱)`。

    `traps` 不给 ⇒ 读盘上的 `traps.json`（自检用这一路，它把 TRAPS 指向临时文件）；
    给了 ⇒ 用它（`collect_edges` 就是这么把**产物里那份**递进来的，见 `traps_table`）。

    ★ 第二个返回值不是装饰：**「只有人记着」本身就是信息**。
      一条陷阱没有仓内锚点 ⇒ 它不可复核、会随人走。把它静默丢掉，
      输出就会说「12 条陷阱全部有据」；数出来才叫诚实
      （`UNAVAILABLE ≠ PASS` 的同一条道理）。
    """
    table = traps if traps is not None else traps_table(None)
    if not table:
        return [], []
    edges: list[dict] = []
    bare: list[dict] = []
    for slug, t in table.items():
        title = t.get("title") or ""
        cases = t.get("cases") or []
        if not cases:
            # 无锚点：**如实记下来**，但不 `continue` —— 它的 `related` 仍是可核的宣称，
            # 不能因为「这段没写证据」就把它那些边也一并免检（免责要按条，不按条块）。
            bare.append({"slug": slug, "title": title,
                         "reason": t.get("unverifiable") or "未写理由"})
        for i, c in enumerate(cases):
            # ★ case 没写 where **不许**顺着 check_edge 的 `None ⇒ N/A` 溜过去：
            #   那条 N/A 是给 `kb.json` 里「显式声明无实现」用的。陷阱的实物证据缺了地址，
            #   不是「声明无实现」，是「这条锚点根本没写」——它必须落进 bare 被**数出来**。
            if not c.get("where"):
                bare.append({"slug": slug, "title": title,
                             "reason": "第 %d 条 case 没写 where" % i})
                continue
            edges.append({"src": "trap:%s[%d]" % (slug, i),
                          "what": c.get("what") or "", "evidence": c.get("where")})
        # ★ `related` 也收成边。不收的后果是它变成**只看得见、没人核**的字段 ——
        #   一个「长得很像已被复核」的装饰（同 `UNAVAILABLE 被读成 PASS`）。
        for j, rel in enumerate(t.get("related") or []):
            if not rel:
                bare.append({"slug": slug, "title": title,
                             "reason": "第 %d 条 related 是空的" % j})
                continue
            edges.append({"src": "trap:%s.related[%d]" % (slug, j),
                          "what": "关联的边", "evidence": rel})
    return edges, bare


# ── ⑫ 图：边 → 双向邻接（out / in）──────────────────────────
#
# ★ 图**必须**由 `collect_edges()` 派生，不许另建一套边。理由是实的：
#   另建 = 一个事实两份写法（本仓栽过的坑：`one-judgement-many-implementations`）。
#   派生之后，「图里每一条边都被 ①②③ 核过它的锚点」是**结构性**的性质 ——
#   不靠人记得去核，也不可能出现「核过的那批」与「图里那批」不一致。
#
# ★ `out` 与 `in` 是**同一份 edges 的两个物化方向**（不是两份独立的边表）。
#   冗余在这里是**故意的**：⑫ 逐条要求两边互为逆表 ⇒ 手改任一侧当场红。

#: kind → 边权（0 < w ≤ 1）。★ 权重只在这一个地方出现 ——
#: 谁想调「陷阱比根因更该被点亮」，改这一行，改完 `gate.py --selftest` 与
#: `ask.py --selftest` 两个方向都会说话。
GRAPH_KINDS: dict[str, float] = {
    "并列陷阱": 0.5,   # 家族 ↔ 它登记的陷阱（原先 spread() 手写的正是这条，现在落成数据）
    "同族": 0.3,       # 两个家族共用一个陷阱（机器派生、对称、无锚点）
    "症状": 0.4, "根因": 0.4, "处置": 0.4, "实例": 0.4, "相关": 0.35,
    "判据": 0.6,       # 家族 → 可跑的命令节点 `run:<脚本>`
    "实物": 0.45,      # 陷阱 → 它的实物证据
    "识别": 0.5,       # 条目 → 识别判据的出处
}

#: 手册里带锚点的五栏 → kind。`runs` 不在表里：它指向 `run:` 节点，不指向锚点。
_PB_KIND = {"symptoms": "症状", "causes": "根因", "fixes": "处置",
            "instances": "实例", "related": "相关"}

_RUN_SCRIPT_RE = re.compile(r"\S+\.py")

#: 节点 id 前缀 → 类别。**全仓只有这一处**说「什么前缀是什么」——
#: `kb/ask.py:_branch_of` 那边判断「这个节点属于哪一支」时按同一套前缀分流。
_NODE_KINDS = {"pb:": "family", "trap:": "trap", "run:": "run", "ev:": "evidence"}


def node_kind(node: str) -> str:
    """节点 id → 类别。条目没有前缀（它就是 md 的 slug），所以兜底是 entry。"""
    for pre, k in _NODE_KINDS.items():
        if node.startswith(pre):
            return k
    return "entry"


def run_script(cmd: str) -> str | None:
    """从登记的命令里取出**脚本名**当 `run:` 节点的 id。取不出 ⇒ None（不许编）。"""
    m = _RUN_SCRIPT_RE.search(cmd or "")
    return os.path.basename(m.group(0)) if m else None


def graph_edges(payload: dict | None) -> dict:
    """把「带锚点的宣称」变成图的边。返回 `{nodes, edges, out, in, counts, skipped}`。

    **不落盘**：build_kb 拿它进产物，gate ⑫ 拿它复核产物 —— 同一份实现，两个调用方。
    """
    edges: list[dict] = []
    skipped: list[dict] = []

    def add(a: str, b: str, kind: str, label: str, src: str) -> None:
        edges.append({"from": a, "to": b, "kind": kind,
                      "w": GRAPH_KINDS[kind], "label": label, "src": src})

    for e in collect_edges(payload):
        src, what, ev = e.get("src") or "", e.get("what") or "", e.get("evidence")
        if src.startswith("pb:"):
            body = src[3:]
            fslug, rest = (body.split(".", 1) + [""])[:2]
            key = rest.split("[")[0]
            node = "pb:" + fslug
            if key == "runs":
                script = run_script(what)
                if script is None:
                    skipped.append({"src": src, "why": "命令里取不出脚本名：%s" % what[:60]})
                    continue
                add(node, "run:" + script, "判据", what, src)
                continue
            kind = _PB_KIND.get(key)
            if kind is None:
                skipped.append({"src": src, "why": "手册这一栏不在表里：%r" % key})
                continue
            if not ev:
                # ★ 「声明无实现 / 没写 evidence」不进图 —— 它没有可指的地址。
                #   但**要数出来**：静默丢掉会让「图里有 N 条边」读成「宣称就这么多」。
                skipped.append({"src": src, "why": "这条没有 evidence（无可指的锚点）"})
                continue
            add(node, "ev:" + ev, kind, what, src)
            continue
        if src.startswith("trap:"):
            body = src[5:]
            slug = body.split("[")[0].split(".")[0]
            kind = "相关" if ".related[" in body else "实物"
            if not ev:
                skipped.append({"src": src, "why": "陷阱这条锚点是空的"})
                continue
            add("trap:" + slug, "ev:" + ev, kind, what, src)
            continue
        # 条目（slug 无前缀）
        slug = src.split(".")[0]
        kind = "识别" if ".recognition[" in src else "相关"
        if not ev:
            # 显式声明「无实现」（如「资产图通常不画 ⇒ 引擎不需处理」）走的就是这一档。
            skipped.append({"src": src, "why": "这条 evidence 是 null（声明无实现）"})
            continue
        add(slug, "ev:" + ev, kind, what, src)

    # ── 结构边：家族 ↔ 陷阱（手册的 `traps` 栏）────────────────
    fams = (payload or {}).get("playbook") or {}
    # ★ 与 `collect_edges` 用的是**同一处**取表逻辑（`traps_table`）：
    #   两处各写一遍「产物优先还是文件优先」，就是同一个判断两份实现。
    traps = traps_table(payload)
    by_trap: dict[str, list[str]] = {}
    for fslug, fam in fams.items():
        for raw in (fam.get("traps") or []):
            tslug = raw[5:] if raw.startswith("trap:") else raw
            if tslug not in traps:
                # ★ 悬空引用：手册点了一个不存在的陷阱。原先 `spread()` 是**静默丢掉**的
                #   （那条边就没点亮过），所以这个缺陷一直没有人看见。
                skipped.append({"src": "pb:%s.traps" % fslug,
                                "why": "登记的陷阱不存在：%s" % raw})
                continue
            add("pb:" + fslug, "trap:" + tslug, "并列陷阱",
                (traps.get(tslug) or {}).get("title") or "", "pb:%s.traps" % fslug)
            by_trap.setdefault(tslug, []).append(fslug)

    # 同族：共用一个陷阱的两个家族。对称 ⇒ 每对**只存一条**（无序对，起点取小），
    # 反向由 `in` 表给出 —— 不重复存两条对称边（存两条的话「边数」会虚高一倍）。
    for tslug, owners in by_trap.items():
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                a, b = sorted((owners[i], owners[j]))
                add("pb:" + a, "pb:" + b, "同族", "共陷阱 %s" % tslug, "derived:shared-trap")

    # ── 物化 out / in（同一份 edges 的两个方向）────────────────
    # ★ 排序**必须**确定（同 `_index` 的教训）：直接遍历 dict/set，键序随哈希种子变，
    #   同一份源 build 两次得到两个 sha12 ⇒ 指纹失效。
    edges.sort(key=lambda e: (e["from"], e["to"], e["kind"]))
    out: dict[str, list] = {}
    rev: dict[str, list] = {}
    for e in edges:
        out.setdefault(e["from"], []).append(
            {"to": e["to"], "kind": e["kind"], "w": e["w"], "src": e["src"]})
        rev.setdefault(e["to"], []).append(
            {"from": e["from"], "kind": e["kind"], "w": e["w"], "src": e["src"]})
    nodes: dict[str, str] = {}
    for n in sorted(set(out) | set(rev)):
        nodes[n] = node_kind(n)
    counts: dict[str, int] = {}
    for e in edges:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    counts["_edges"] = len(edges)
    counts["_nodes"] = len(nodes)
    counts["_edges_no_anchor"] = sum(1 for e in edges if e["kind"] == "同族")
    return {"nodes": nodes, "edges": edges, "out": out, "in": rev,
            "counts": counts, "skipped": skipped}


def check_graph(payload: dict | None) -> dict:
    """⑫ 图（out / in）：四条。任一条不成立即 GAP。

    这里**不**重写边的锚点复核（那是 ①②③ 的活）—— 它只回答「这份物化有没有走样」：
      (a) out/in 逐条互为逆表（手改任一侧 ⇒ 红）；
      (b) 端点都在 `nodes` 里、类别合法、权重落在 (0,1]；
      (c) `edges` 与由本 payload 再派生一遍的结果**逐条相同**（手改了边表 ⇒ 红）；
      (d) 没有悬空引用 / 取不出脚本名这种「派生时被跳过」的条（有 ⇒ 数出来并红）。
    """
    g = (payload or {}).get("graph")
    if not g:
        return {"status": "unavailable", "detail":
                "kb.json 里没有 graph 一节 —— 图一次都没查过（先跑 kb/build_kb.py）",
                "nodes": 0, "edges": 0, "counts": {}}
    fails: list[str] = []
    edges = g.get("edges") or []
    out = g.get("out") or {}
    rev = g.get("in") or {}
    nodes = g.get("nodes") or {}

    # (a) 逆表
    fwd = {(e["from"], e["to"], e["kind"]) for e in edges}
    back = {(r["from"], r["to"], r["kind"]) for r in
            ({"from": n, "to": t["to"], "kind": t["kind"]} for n, lst in out.items() for t in lst)}
    miss_out = sorted(fwd - back)
    miss_edge = sorted(back - fwd)
    if miss_out:
        fails.append("edges 里有 %d 条没进 out（首条 %s）" % (len(miss_out), miss_out[0]))
    if miss_edge:
        fails.append("out 里有 %d 条不在 edges 里（首条 %s）" % (len(miss_edge), miss_edge[0]))
    # in 侧同样对一遍 —— 只对 out 等于「逆表」只查了一半
    fin = {(r["from"], r["to"], r["kind"]) for n, lst in rev.items() for r in
           ({"from": t["from"], "to": n, "kind": t["kind"]} for t in lst)}
    if fin != fwd:
        only_e = sorted(fwd - fin)[:2]
        only_i = sorted(fin - fwd)[:2]
        fails.append("in 表与 edges 不等（edges 独有 %s；in 独有 %s）" % (only_e, only_i))

    # (b) 端点 / 类别 / 权重
    dangling = sorted({n for e in edges for n in (e["from"], e["to"]) if n not in nodes})
    if dangling:
        fails.append("%d 个端点没登记在 nodes 里（首条 %s）" % (len(dangling), dangling[0]))
    bad_kind = sorted({e["kind"] for e in edges if e["kind"] not in GRAPH_KINDS})
    if bad_kind:
        fails.append("认不得的 kind：%s" % bad_kind)
    bad_w = [(e["from"], e["to"], e["w"]) for e in edges
             if not isinstance(e.get("w"), (int, float)) or not 0 < e["w"] <= 1]
    if bad_w:
        fails.append("权重不在 (0,1]：%s（首条）" % (bad_w[0],))
    bad_node_kind = sorted({k for k in nodes.values()
                            if k not in set(_NODE_KINDS.values()) | {"entry"}})
    if bad_node_kind:
        fails.append("认不得的节点类别：%s" % bad_node_kind)

    # (c) 再派生一遍。★ 这不是「同源比同源」：比的是**产物里那份物化**与
    #     **由产物当前内容重新派生的那批** —— 手改了 `edges` 而没改源 ⇒ 红。
    fresh = graph_edges(payload)
    if fresh["edges"] != edges:
        old = {(e["from"], e["to"], e["kind"]) for e in edges}
        new = {(e["from"], e["to"], e["kind"]) for e in fresh["edges"]}
        fails.append("edges 与再派生不等（产物独有 %s；再派生独有 %s）"
                     % (sorted(old - new)[:2], sorted(new - old)[:2]))

    # (d) 派生时被跳过的条。★ 数出来：跳过是**信息**（缺锚点/悬空引用），
    #     静默丢掉会让「图里有 N 条边」读成「宣称就只有这么多」。
    skipped = g.get("skipped") or []
    dangling_ref = [s for s in skipped if "不存在" in (s.get("why") or "")]
    if dangling_ref:
        fails.append("悬空引用 %d 条（首条 %s：%s）"
                     % (len(dangling_ref), dangling_ref[0]["src"], dangling_ref[0]["why"]))

    return {"status": "gap" if fails else "pass",
            "detail": "；".join(fails) if fails else
                      "%d 个节点 / %d 条边，out/in 互为逆表" % (len(nodes), len(edges)),
            "nodes": len(nodes), "edges": len(edges),
            "kinds": {k: v for k, v in sorted((g.get("counts") or {}).items())
                      if not k.startswith("_")},
            "no_anchor": (g.get("counts") or {}).get("_edges_no_anchor", 0),
            "skipped": skipped,
            "fails": fails}


# ── ① ② ③ ─────────────────────────────────────────────────

def _names_in(text: str) -> tuple[set[str], set[str]]:
    """这个文件里**真存在**的标识符，以及**真的**字符串常量（均排除文档串）。

    AST 走一遍：注释根本不在语法树里，字符串只在 Constant 节点里 —— 所以
    「注释里提了一嘴」不会被算成「实现了」。
    """
    names: set[str] = set()
    strs: set[str] = set()
    tree = ast.parse(text)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_ids.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in doc_ids:
                strs.add(node.value)
    return names, strs


def check_edge(edge: dict) -> dict:
    """① 路径 ② 行号 ③ 符号。返回 {status, code, detail}。"""
    ev = edge.get("evidence")
    if ev is None:
        # 显式声明「这条没有实现」—— 那是**声明**，不是失效，不许算红、也不许算绿。
        return {"status": "na", "edge": edge, "detail": "声明无实现"}
    if not isinstance(ev, str) or ":" not in ev:
        return {"status": "unavailable", "edge": edge,
                "detail": "evidence 不是 file:行 / file:符号 的形态：%r" % (ev,)}

    m = _EV_LINE.match(ev)
    if m:
        rel, n = m.group("f"), int(m.group("n"))
        data = _read_bytes(rel)
        if data is None:                                         # ①
            return {"status": "gap", "edge": edge, "detail": "文件不在盘上：%s" % rel}
        lines = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
        if n < 1 or n > lines:                                   # ②
            return {"status": "gap", "edge": edge,
                    "detail": "行号越界：%s 只有 %d 行，边却指第 %d 行" % (rel, lines, n)}
        return {"status": "pass", "edge": edge, "detail": "%s:%d" % (rel, n)}

    m = _EV_SYM.match(ev)
    if not m:
        return {"status": "unavailable", "edge": edge, "detail": "evidence 形态认不出：%r" % ev}
    rel, sym = m.group("f"), m.group("s")
    text = _read_text(rel)
    if text is None:                                             # ①
        return {"status": "gap", "edge": edge, "detail": "文件不在盘上：%s" % rel}
    try:
        names, strs = _names_in(text)
    except SyntaxError as exc:
        return {"status": "unavailable", "edge": edge,
                "detail": "%s 语法解析不了（%s），无法判符号" % (rel, exc.msg)}
    # `COMPONENTS["墙(wall)"]` → 先认容器名，再认那个键是不是真的字符串常量
    base = sym.split("[", 1)[0].split(".")[0]
    if base not in names:                                        # ③
        return {"status": "gap", "edge": edge,
                "detail": "符号不在 %s 里：%s（AST 全文件走遍，注释不算）" % (rel, sym)}
    if "[" in sym:
        for key in re.findall(r"[\[\"']([^\]\"']+)[\]\"']", sym):
            if key not in strs and not any(key in s for s in strs):
                return {"status": "gap", "edge": edge,
                        "detail": "%s 里没有这个字典键：%r" % (rel, key)}
    return {"status": "pass", "edge": edge, "detail": "%s:%s" % (rel, sym)}


# ── ⑤ 双源一致：图层语义 ────────────────────────────────────

def code_layer_roles(rel: str = "backend/extract/extract_rooms_generic.py") -> dict | None:
    """从代码里**解析**出 LAYER_ROLE 的字面量。解析不到返回 None（⇒ 判「量不了」）。"""
    text = _read_text(rel)
    if text is None:
        return None
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "LAYER_ROLE" for t in node.targets):
            try:
                v = ast.literal_eval(node.value)
            except ValueError:
                return None
            return {str(k): str(x) for k, x in v.items()} if isinstance(v, dict) else None
    return None


def prose_layer_roles() -> dict | None:
    """从散文两篇（`kb/src/05`、`07`）的表格里解析「数字前缀 → 中文语义」。

    ★ 两篇都读：只说一篇就等于**用一个源去核另一个源**，那两边同源必恒绿
      （memory: same-source-comparison-always-green）。这里是**真两条链**：
      散文是人写的，代码是机器执行的。
    """
    out: dict[str, set[str]] = {}
    hit = 0
    for rel in ("kb/src/05-dimension-annotation.md", "kb/src/07-asset-survey.md"):
        text = _read_text(rel)
        if text is None:
            continue
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            pref, sem = cells[0], cells[1]
            if not re.fullmatch(r"[\d\s/]+", pref):     # 只认「5」「7 / 8」这种前缀格
                continue
            cn = re.split(r"[（(]", sem)[0].strip()
            role = _ROLE_CN.get(cn)
            if not role:
                continue
            hit += 1
            for p in re.findall(r"\d", pref):
                out.setdefault(p, set()).add(role)
    return {k: v for k, v in out.items()} if hit else None


def check_dual_source() -> dict:
    code = code_layer_roles()
    prose = prose_layer_roles()
    if code is None or prose is None:
        return {"status": "unavailable", "compared": 0,
                "detail": "有一侧解析不出（code=%s / prose=%s），**不等于一致**"
                          % ("ok" if code else "空", "ok" if prose else "空")}
    divergent, compared = [], 0
    for p, roles in sorted(prose.items()):
        if p not in code:
            divergent.append("前缀 %s 散文有、代码没有" % p)
            continue
        compared += 1
        if roles != {code[p]}:
            divergent.append("前缀 %s：散文说 %s，代码是 %s"
                             % (p, "/".join(sorted(roles)), code[p]))
    for p in sorted(set(code) - set(prose)):
        divergent.append("前缀 %s 代码有、散文没写" % p)
    return {"status": "gap" if divergent else "pass", "compared": compared,
            "detail": "；".join(divergent) if divergent else "散文 %d 个前缀与代码一致" % compared}


# ── ⑪ ASCII 引号被当中文引号用（铁律 15）─────────────────────
#
# 为什么它够格当一条门禁：**这个缺陷在屏幕上看不出来。** `"` 和 `「」` 在编辑器里
# 几乎一样，眼睛扫过去完全正常 —— 本仓为此一天犯过六次，只有机器查得出来。
# 它的**破坏形态**尤其隐蔽：写在代码行上时，Python 看见的是夹在中间的**裸标识符**
# ⇒ `SyntaxError: Perhaps you forgot a comma?`，而报错指不到真正的原因。
#
# ★ 两档规则**不是**图省事，是因为「引号在这类文件里能干什么」根本不同：
#   · 代码档（`kb/*.py`）：ASCII 引号**两侧都是汉字** ⇒ 命中。
#     正常定界符左边是 `(`/`,`/`=`/空格，绝不会夹在一串汉字中间
#     ⇒ `x = "汉字"` 不命中，只有**写错了**的形态才命中。
#   · 散文档（`kb/**/*.md`）：掩掉 ``` 围栏与 `行内跨度` 后，**任一侧**是 CJK ⇒ 命中。
#     ★ 放宽的理由：md 不会被解释成语法，宽了**不会误伤代码**；而实测的漏网形态恰是
#       `把"C4 是 gap"的红快照` —— 一侧夹着拉丁词，窄规则看不见它。
#     ⇒ 代价是一条**约定**：md 里的命令/代码必须写进反引号跨度（现有文档都是这么写的）。
#       不符合就补反引号 —— 这条判据在 md 上就是按该约定量的。
#   · 数据档（`kb/*.json`）：**不套**引号规则，只要求能解析。两个理由：
#     ① 值里的中文引号与 md 同源（`kb.json` 的内容就是从 md 派生的），套规则 = 一条缺陷报两次；
#     ② 引号写坏在 JSON 里首先表现为**解析失败**，那比引号规则更接近要害。
#
# ★ 分母必须写出来。**四档各有各的分母**：
#   · `md` / `py` / `json` 三档量的是 **`kb/` 内的自有文件**；
#   · 第四档 `md-repo` 量的是**仓内 kb/ 之外的全部 .md**（实测 54 个文件 / 510 处），
#     **带基线**：基线内放行、新增即红。它跟前面三档的区别不是规则宽窄，是**存量**——
#     那 510 处散在 13 份历史台账与规划里，一次改不干净，而「永久全红」的判据会被学会忽略
#     （`append-only-ledger-whole-table-assertion`）。
#   · 两处**排除**必须说清：① `_REPO_MD_SKIP` 里的目录（含 `_scratch` / `.orig` ——
#     已判退役、要移出仓外，算进来只会让基线随迁移 churn），**排除掉几个文件要数出来**；
#     ② `kb/` 本身（已在前三档里，剔掉前缀是为了**两档互斥、同一处不被数两次**）。
#   ⇒ 「没量过」和「干净」在屏幕上必须不是同一行字（与 ①②③ 的 N/A 同理）。

_CJK_SPAN = re.compile(r"`[^`]*`")


def _is_han(ch: str) -> bool:
    return bool(ch) and 0x4E00 <= ord(ch) <= 0x9FFF


def _is_cjk(ch: str) -> bool:
    """汉字 ＋ 中日韩标点 ＋ 全角形式 —— 判「这个引号是不是被当成汉语标点用了」。"""
    return bool(ch) and (0x3000 <= ord(ch) <= 0x303F or 0x4E00 <= ord(ch) <= 0x9FFF
                         or 0xFF00 <= ord(ch) <= 0xFFEF)


def _cjk_quote_hits(text: str, wide: bool) -> list[dict]:
    """纯函数：给一段文本，回命中列表。**不碰盘** —— 所以自检能直接喂它夹具。"""
    out: list[dict] = []
    fence = False
    for i, line in enumerate(text.split("\n"), 1):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        # ★ 行内跨度换**等长**空格：只用来判邻字符，但保持列号不乱（报位置要准）。
        body = _CJK_SPAN.sub(lambda m: " " * len(m.group(0)), line) if wide else line
        for j, ch in enumerate(body):
            if ch != '"':
                continue
            left = body[j - 1] if j else ""
            right = body[j + 1] if j + 1 < len(body) else ""
            hit = ((_is_cjk(left) or _is_cjk(right)) if wide
                   else (_is_han(left) and _is_han(right)))
            if hit:
                # ★ `raw12` = **整行（去首尾空白）** 的 sha12，`text` 只是给人看的截断版。
                #   基线拿它当键 ⇒ 行号漂了不影响，而**内容一改键就对不上**
                #   （那正是我们要的：动到一条已有命中的行，就顺手把它改对）。
                out.append({"line": i, "col": j + 1, "text": line.strip()[:96],
                            "raw12": sha12(line.strip().encode("utf-8"))})
    return out


def _kb_sources(suffix: str) -> list[str]:
    """`kb/` 下所有该后缀的文件（相对 ROOT 的 posix 路径）。"""
    return sorted(os.path.relpath(p, ROOT).replace(os.sep, "/")
                  for p in glob.glob(os.path.join(KB, "**", "*" + suffix), recursive=True)
                  if os.path.isfile(p))


#: 仓内 `.md` 那一档**排除掉的目录** —— 排除了什么必须**在输出里数出来**
#: （铁律 23(b)：排除规则把真值排除了，比误报更坏，而且它一声不吭）。
#: `_scratch` / `.orig` 是**已判退役、要整体移出仓外**的暂存区：把它们算进来，
#: 基线会随迁移整批 churn，而那批 churn 会淹没新增的那一两处。
_REPO_MD_SKIP = (".git", "node_modules", "__pycache__", ".orig", "_scratch", ".claude")


def _repo_md_sources() -> list[str]:
    """除 `kb/` 之外的仓内所有 `.md`（相对 ROOT 的 posix 路径，已排序）。

    ★ 为什么单列一档而不是并进 `md` 档：`md` 档的分母是 `kb/`，
      而**仓内另外那几十个 .md 一次都没量过** —— 「没量过」与「干净」不许是同一行字。
      两档**互斥**（这里剔掉 `kb/` 前缀），所以同一个文件不会被数两次。
    """
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _REPO_MD_SKIP]
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), ROOT).replace(os.sep, "/")
            if not rel.startswith("kb/"):
                out.append(rel)
    return sorted(out)


#: ⑪ 的**仓内 .md 档**基线：既有命中登记在此，**只对新增报红**。
#:
#: ★ 为什么需要基线，而不是「把这批改干净就完了」：实测 510 处，散在 13 份
#:   **历史台账与规划**里 —— 手工清一遍只是把位置腾出来，而「永久全红」的判据
#:   会被学会忽略（`append-only-ledger-whole-table-assertion`）。基线让这道闸
#:   **从此以后有牙齿**：新增一处就红，清理掉的如实数出来。
#: ★ 键是 `(文件, 行内容 sha12)`，**不是行号** —— 行号会随编辑漂，而漂了照样指向别处
#:   （铁律 31）。代价是一条明说的约定：**动到一条已有命中的行，就得顺手把它改对**
#:   （内容一变，旧键对不上 ⇒ 按新增报红）。
#: ★ 基线自己带**尺子指纹**（`ruler_sha12` = 生成它那一刻 `gate.py` 的 sha12）：
#:   「这份基线是旧尺子量的」和「这份基线是对的」在屏幕上必须不是同一行字（铁律 24）。
CJK_BASELINE = os.path.join(KB, "cjk-quote-baseline.json")


def _band_diff(hits: list[dict], entry: dict) -> tuple[list[dict], int, int]:
    """纯函数：命中清单 vs 基线里那一档 ⇒ (新增, 命中基线的处数, 基线里已不存在的处数)。

    ★ 为什么要回**三个**数：只回「新增」的话，**基线被人悄悄删空**（闸门随之变哑）
      在屏幕上什么都不发生。清理掉的那一侧也要数出来 —— 它下降是好事，
      但**「好事」也得看得见**，否则「基线被清空」和「基线本来就小」同形。
    """
    left = {f: dict(d) for f, d in (entry or {}).items()}
    new, known = [], 0
    for h in hits:
        bucket = left.setdefault(h["file"], {})
        if bucket.get(h["raw12"], 0) > 0:
            bucket[h["raw12"]] -= 1
            known += 1
        else:
            new.append(h)
    cleaned = sum(v for d in left.values() for v in d.values())
    return new, known, cleaned


def load_cjk_baseline() -> tuple[dict | None, str]:
    """读基线 ⇒ (内容, 为什么读不到)。文件不在 = `None` ＋ 一句人话（不许当空基线）。"""
    if not os.path.exists(CJK_BASELINE):
        return None, "没有 %s" % os.path.relpath(CJK_BASELINE, ROOT).replace(os.sep, "/")
    try:
        return json.loads(io.open(CJK_BASELINE, encoding="utf-8").read()), ""
    except Exception as exc:
        return None, "%s 解析不了：%s" % (os.path.basename(CJK_BASELINE), str(exc)[:70])


def cjk_repo_band(hits: list[dict]) -> dict:
    """仓内 `.md` 档：带基线地判。**唯一**的分档处（打印与自检都读它的返回值）。"""
    base, why = load_cjk_baseline()
    ruler_now = _self_sha12()
    if base is None:
        # ★ 这一档**整档判不了**（不是「干净」）。`new` 故意留空、只留一句人话：
        #   把 510 处原封不动塞进 `new` 会淹掉屏幕 —— 而屏幕上真正该看见的是
        #   「先登记」这一句。数量另用 `blocked_hits` 带着，不丢。
        return {"state": "gap", "new": [], "known": 0, "cleaned": 0, "files": 0,
                "blocked": True, "blocked_hits": len(hits),
                "ruler": "unregistered", "ruler_now": ruler_now,
                "detail": "%s —— 这一档**判不了**（命中的 %d 处里，哪一处是新长的、"
                          "哪一处是本来就有的，分不开）。先跑 `--cjk-baseline` 登记"
                          % (why, len(hits))}
    entry = ((base.get("bands") or {}).get("md_repo") or {})
    new, known, cleaned = _band_diff(hits, entry)
    ruler_was = base.get("ruler_sha12") or "?"
    if ruler_was != ruler_now:
        # ★ 尺子换了 ⇒ 这份基线可能已经不是按同一把尺子量的。**红**，不是提示：
        #   「旧尺子量的」与「对的」同形，正是铁律 24 要防的那一件事。
        return {"state": "gap", "new": [], "known": 0, "cleaned": 0, "files": 0,
                "blocked": True, "blocked_hits": len(hits),
                "ruler": ruler_was, "ruler_now": ruler_now,
                "detail": "尺子变了（基线登记 %s，现在 %s）—— 这份基线可能已经不是"
                          "按同一把尺子量的 ⇒ 整档判不了（此刻命中的 %d 处**一处也没比**）。"
                          "确认没被漏检后跑 `--cjk-baseline` 重登记"
                          % (ruler_was, ruler_now, len(hits))}
    return {"state": "gap" if new else "pass", "new": new, "known": known,
            "cleaned": cleaned, "files": len(entry), "blocked": False,
            "blocked_hits": 0, "ruler": ruler_was, "ruler_now": ruler_now,
            "detail": "命中 %d 处＝基线内 %d ＋ **新增 %d**；基线里另有 %d 处已不存在"
                      "（清理掉了是好事，**也得看得见**）" % (len(hits), known, len(new), cleaned)}


def check_cjk_quotes() -> dict:
    """⑪：ASCII 引号被当中文引号用 ⇒ 红。**四**档的分工见上面那段注释。"""
    hits: list[dict] = []
    bad_json: list[str] = []
    mds, pys, jss = _kb_sources(".md"), _kb_sources(".py"), _kb_sources(".json")
    for rel in mds:
        for h in _cjk_quote_hits(_read_text(rel) or "", wide=True):
            hits.append(dict(h, file=rel, band="md"))
    for rel in pys:
        for h in _cjk_quote_hits(_read_text(rel) or "", wide=False):
            hits.append(dict(h, file=rel, band="py"))
    for rel in jss:
        try:
            json.loads(_read_text(rel) or "")
        except Exception as exc:                      # 解析不了 ⇒ 明说，不许当绿
            bad_json.append("%s：%s" % (rel, str(exc)[:80]))
    # ★ 第四档：**仓内 kb/ 之外的 .md**。它跟上面三档的区别不是规则宽窄，是
    #   **它对既有命中带基线**：这批（实测 510 处 / 13 份历史台账与规划）一次改不干净，
    #   而「永久全红」的判据会被学会忽略 ⇒ 基线内放行、**新增即红**。
    repo_files = _repo_md_sources()
    repo_hits: list[dict] = []
    for rel in repo_files:
        for h in _cjk_quote_hits(_read_text(rel) or "", wide=True):
            repo_hits.append(dict(h, file=rel, band="md-repo"))
    repo = cjk_repo_band(repo_hits)
    n = len(mds) + len(pys) + len(jss)
    gap = bool(hits or bad_json or repo["state"] != "pass")
    return {"status": "gap" if gap else "pass",
            "checked": n, "md": len(mds), "py": len(pys), "json": len(jss),
            "hits": hits, "bad_json": bad_json,
            "md_repo": len(repo_files), "repo": repo, "repo_hits": len(repo_hits),
            "detail": "%d 个文件（md %d 宽档 / py %d 严档 / json %d 只判能解析）；命中 %d 处；"
                      "另量仓内 .md %d 个／命中 %d 处（带基线：%s）"
                      % (n, len(mds), len(pys), len(jss), len(hits) + len(bad_json),
                         len(repo_files), len(repo_hits), repo["detail"])}


# ── ⑥ 陈旧：按**内容**指纹，不按 mtime ──────────────────────

def evidence_files(edges: list[dict]) -> list[str]:
    out: list[str] = []
    for e in edges:
        ev = e.get("evidence")
        if isinstance(ev, str) and ":" in ev:
            f = ev.rsplit(":", 1)[0].strip()
            if f and f not in out:
                out.append(f)
    return sorted(out)


def watched_files(edges: list[dict]) -> list[str]:
    """⑥ 要盯的文件 = 边指到的 ＋ **`traps.json` 自己**。

    ★ 为什么把 traps.json 也盯上：它**承载锚点**，改它 = 改判据。
      不盯的话，「悄悄删掉一条陷阱」「把 where 挪一指」在屏幕上什么都不发生
      —— 而它承载的正是「哪些坑已经被登记过」这件事。
      盯上之后，动它就必须 `--record` 重新登记（判据版本由 `criterion_version` 手写 +1），
      这道摩擦力是**故意的**。
    """
    out = evidence_files(edges)
    for name, path in (("kb/traps.json", TRAPS), ("kb/playbook.json", PLAYBOOK),
                       # ★ ⑪ 的基线也盯上：它**承载裁决**（哪些命中原谅、哪些不放）。
                       #   不盯的话，「往基线里悄悄塞 50 条」= 把闸门调哑，
                       #   而屏幕上什么都不发生（同族：`traps.json`）。
                       ("kb/cjk-quote-baseline.json", CJK_BASELINE)):
        # ★ 手册与陷阱一样**承载锚点**：改它 = 改判据。不盯的话，
        #   「悄悄删一个家族」「把某条的 evidence 挪一指」在屏幕上什么都不发生。
        if os.path.exists(path) and name not in out:
            out = sorted(out + [name])
    return out


def check_stale(files: list[str]) -> dict:
    """证据文件内容变了 ⇒ 依赖它的边**全部待复核**。

    ★ 按 **sha12 内容**比，不按 mtime：本仓实测 mtime 会漏（`delivery-glb-content-staleness`：
       mtime 漏了 28/48 栋），而且 git checkout 会把 mtime 全刷成当天 ——
       那样门禁会**天天全红**，下场是被学会忽略。
    """
    if not os.path.exists(LOCK):
        return {"status": "unavailable", "rows": [], "compared": 0,
                "detail": "没有 %s —— 未登记过基线，**不等于都新鲜**（跑 --record 建立）"
                          % os.path.basename(LOCK)}
    lock = json.loads(io.open(LOCK, encoding="utf-8").read())
    old = lock.get("files") or {}
    rows, compared = [], 0
    for rel in files:
        cur = _read_bytes(rel)
        if cur is None:
            rows.append((rel, "gap", "文件不在盘上"))
            continue
        cur12 = sha12(cur)
        if rel not in old:
            rows.append((rel, "unavailable", "不在登记表里，未核过"))
            continue
        compared += 1
        rows.append((rel, "pass" if old[rel] == cur12 else "gap",
                     "新鲜" if old[rel] == cur12 else "内容变了（登记 %s，现在 %s）"
                     % (old[rel], cur12)))
    bad = [r for r in rows if r[1] == "gap"]
    return {"status": "gap" if bad else "pass", "rows": rows, "compared": compared,
            "detail": "；".join("%s: %s" % (r[0], r[2]) for r in bad) if bad
                      else "%d 个证据文件与登记一致" % compared}


# ── ⑦ --run 白名单只读 ──────────────────────────────────────

def readonly_ok(cmd: str) -> tuple[bool, str]:
    """登记的判据命令**必须只读**。这是代码事实，不是注释里的君子协定。

    实测理由：`README.md` 铁律 9 写着「没有备份就别跑 recognize」——
    一次「顺手重跑」就能把人工修复冲掉（`_qa` 里 22 栋零台账是真缺陷）。
    """
    s = (cmd or "").strip()
    if not s:
        return False, "空命令"
    low = s.lower()
    for t in _WRITE_TOKENS:
        if t in low:
            return False, "含写操作标记 %r" % t
    if not low.startswith(_READONLY_PREFIX):
        return False, "入口不在只读白名单里（%s…）" % s[:40]
    return True, "只读"


def readonly_verdict(cmd: str, writes: str = "") -> tuple[bool, str]:
    """一条登记的判据命令**能不能跑** —— ★**唯一**的裁决处。

    登记侧（`run()` 那一列 `cmd_rows`）与执行侧（`kb/ask.py:run_registered`）都调它，
    所以两边**不可能给出不同判决**。这是 2026-09-24 安全评审逼出来的一件事：
    原先「能不能跑」只在登记侧判，而执行侧是「kb.json 里有什么跑什么」——
    **判断在一处、动作在另一处，而动作那一侧不调它**（铁律 20：形式检查通过、语义没发生）。
    更糟的是执行侧那份 `argv_of` 只挡 shell 元字符，`python -u -c "…"` 那种命令
    一个元字符都没有 ⇒ 它拦不住，而它也不在白名单里。

    ★ 「只读」不许是空话：白名单是按**前缀**放的，而这些盘上脚本**会写报告**。
      没写 `writes` 的条目 = 副作用没人知道 ⇒ 拒（不是警告）。
    """
    ok, why = readonly_ok(cmd)
    if ok and not (writes or "").strip():
        return False, "没写 writes —— 判据命令的写盘副作用必须写明"
    return ok, why


# ── 汇总 ────────────────────────────────────────────────────

def run(payload: dict | None = None) -> dict:
    # ★ 只读一次盘上那份 kb.json，两处共用 —— 两处各读一次会出现「边来自这份、
    #   命令来自那份」，而两者不一致时屏幕上完全看不出来。
    if payload is None:
        payload = json.loads(io.open(KBJSON, encoding="utf-8").read())
    edges = collect_edges(payload)
    edge_rows = [check_edge(e) for e in edges]
    files = watched_files(edges)
    stale = check_stale(files)
    dual = check_dual_source()
    value = _run_values()
    cmd_rows = []
    for c in _declared_commands(payload):
        # ★ 判决调 `readonly_verdict`（唯一裁决处），不在这里写第二遍 ——
        #   执行侧 `kb/ask.py:run_registered` 调的是同一个函数。
        ok, why = readonly_verdict(c["cmd"], c.get("writes") or "")
        cmd_rows.append((c["cmd"], ok, why, c.get("src") or ""))
    # ★ 用**产物里那份**陷阱表（`traps_table`）—— 与 ①②③ 收边时用的是同一份。
    #   这里若改回读文件，「边来自产物、条数来自文件」，两者不一致时屏幕上看不出来。
    _te, bare = collect_trap_edges(traps_table(payload))
    cjk = check_cjk_quotes()
    pb_edges, pb_bare, pb_declared = collect_playbook_edges(payload)
    graph = check_graph(payload)
    # ★ 单位要分清：**条数是条数、边数是边数**，混在一行里报就是量纲错
    #   （铁律 23(c)：判据的量纲必须是被判定量的量纲）。
    # ★★ 分档只许有**一个**判据：先前用两条正则分「实物锚点/关联」，而
    #   `trap:x.related[0]` 两条**都匹配** ⇒ 一条边被数进两档（28+13≠28）。
    #   换成一次分类，两档从同一个分类结果里取。
    kind = {"case": 0, "related": 0}
    scope = set()
    for e in edges:
        if not e["src"].startswith("trap:"):
            continue
        body = e["src"][5:]
        kind["related" if ".related[" in body else "case"] += 1
        scope.add(body.split("[")[0].split(".")[0])
    scope.update(b["slug"] for b in bare)
    return {"edges": edge_rows, "stale": stale, "dual": dual, "value": value,
            "cmds": cmd_rows, "edge_files": files, "cjk": cjk, "graph": graph,
            # ★ 陷阱分两栏报：**有锚点的**已并入上面的边，**没锚点的**单列。
            #   只报「12 条陷阱全部有据」就是把「只有人记着」抹平成了合格 ——
            #   与 UNAVAILABLE 被读成 PASS 是同一条错。
            "traps": {"present": os.path.exists(TRAPS), "nodes": len(scope),
                      "case_edges": kind["case"], "related_edges": kind["related"],
                      "bare": bare},
            # ★ 手册三栏：可核边（已并入 ①②③）／**缺 evidence 的**／**声明无锚点的**。
            #   后两栏必须各占一格 —— 混成一栏就是把「诚实」和「漏写」印成同一行字。
            "playbook": {"present": "playbook" in (payload or {}),
                         "families": len((payload or {}).get("playbook") or {}),
                         "edges": len(pb_edges), "bare": pb_bare, "declared": pb_declared},
            "self_sha12": _self_sha12(),
            # ★ ④ 是**委派**给 values.py 的尺子。委派出去的那把尺子换了，
            #   本文件的指纹不会变 —— 不报出来，读的人就分不清这份结果是谁量的
            #   （铁律 24：「这份数是旧尺子量的」和「这份数是对的」屏幕上一样）。
            "values_sha12": _file_sha12("values.py"),
            "criterion_version": CRITERION_VERSION}


def _run_values() -> dict:
    """④ 委派给 `values.py` —— 它自带阳性对照，判据不在这里重写（一份写法）。"""
    try:
        spec = importlib.util.spec_from_file_location(
            "kg_values", os.path.join(KB, "values.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        a = mod.audit()
        bad = [r for r in a["results"] if r["verdict"] in ("DRIFT", "AMBIGUOUS", "MISSING")]
        return {"status": "gap" if bad else ("pass" if a["total"] else "unavailable"),
                "total": a["total"], "compared": a["compared"],
                "counts": a["counts"],
                "detail": "；".join("%s %s" % (r["verdict"], r["row"]["const"]) for r in bad)
                          if bad else "%d 行比过，%d 行量不了" % (a["compared"],
                                                                a["total"] - a["compared"])}
    except Exception as exc:                                  # 量具自己崩 ⇒ 明说，不许当绿
        return {"status": "unavailable", "total": 0, "compared": 0, "counts": {},
                "detail": "values.py 跑不起来：%s" % exc}


def _declared_commands(payload: dict | None) -> list[dict]:
    """待登记的判据命令：`{cmd, writes, src}`。手册还没建 ⇒ **就是 0 条**。

    ★ 0 条必须打出来。`--run` 白名单一条都没查过，和「全查过、都只读」
      在屏幕上必须不是同一行字。
    """
    if payload is None:
        return []
    out: list[dict] = []
    for slug, e in (payload.get("entries") or {}).items():
        for g in (e.get("gauges") or []):
            if isinstance(g, dict) and g.get("cmd"):
                out.append({"cmd": g["cmd"], "writes": g.get("writes") or "", "src": slug})
    for fslug, fam in (payload.get("playbook") or {}).items():
        for i, r in enumerate(fam.get("runs") or []):
            if isinstance(r, dict) and r.get("cmd"):
                out.append({"cmd": r["cmd"], "writes": r.get("writes") or "",
                            "src": "pb:%s.runs[%d]" % (fslug, i)})
    return out


# ── 输出 ────────────────────────────────────────────────────

_LABEL = {"pass": "PASS", "gap": "GAP", "unavailable": "UNAVAILABLE", "na": "N/A"}


def _print(res: dict) -> None:
    rows = res["edges"]
    cnt: dict[str, int] = {}
    for r in rows:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    print("① ② ③ 边本身：%d 条" % len(rows))
    for k in ("pass", "na", "gap", "unavailable"):
        if cnt.get(k):
            print("     %-12s %d" % (_LABEL[k], cnt[k]))
    print("     （N/A = 明确声明「无实现」，不是失效也不是通过）")
    for r in rows:
        if r["status"] == "gap":
            print("     ✗ %s  %s → %s" % (r["edge"]["src"], r["edge"]["evidence"], r["detail"]))
        elif r["status"] == "unavailable":
            print("     ? %s  %s" % (r["edge"]["src"], r["detail"]))

    st = res["stale"]
    n_un = sum(1 for r in st["rows"] if r[1] == "unavailable")
    print("⑥ 陈旧：%s（比过 %d 个证据文件%s）"
          % (_LABEL[st["status"]], st.get("compared", 0),
             "；**另有 %d 个不在登记表里、未核过**" % n_un if n_un else ""))
    if st["status"] != "pass" and not [r for r in st["rows"] if r[1] != "pass"]:
        print("     " + st["detail"])       # 没有逐条可列时（如「根本没有登记表」）才印摘要
    # ★ 未登记/不在盘上/内容变了，**两档都要印**。原来只在 pass 档印 —— 于是
    #   「有 9 个文件从没核过」会被一句「内容变了」挡在屏幕外（`trap-unavailable-reads-as-pass`：
    #   坏的不是边界，是边界在报告上不显形）。
    for rel, s, why in st["rows"]:
        if s != "pass":
            print("     ? %s — %s" % (rel, why))

    du = res["dual"]
    print("⑤ 双源一致（图层语义）：%s（比过 %d 个前缀）" % (_LABEL[du["status"]],
                                                          du.get("compared", 0)))
    print("     " + du["detail"])

    va = res["value"]
    print("④ 值漂移（阈值表 ↔ 代码）：%s —— %s" % (_LABEL[va["status"]], va["detail"]))

    tr = res["traps"]
    if not tr["present"]:
        print("◇ 陷阱：**UNAVAILABLE** —— traps.json 不在盘上，这一类一次都没查过"
              "（「没查过」不等于「没有陷阱」）")
    else:
        print("◇ 陷阱：登记 %d 条；可核边 %d 条（实物锚点 %d ＋ 关联 %d）已并入上面的 ①②③；"
              "**只有人记着 %d 条**"
              % (tr["nodes"], tr["case_edges"] + tr["related_edges"],
                 tr["case_edges"], tr["related_edges"], len(tr["bare"])))
        for b in tr["bare"]:
            print("     ◆ %s（%s）—— %s" % (b["slug"], b["title"], b["reason"]))

    pb = res["playbook"]
    if not pb["present"]:
        print("◆ 手册：**UNAVAILABLE** —— kb.json 里没有 playbook 这一节"
              "（先跑 python -u kb/build_kb.py；**不是**「一个症状都没有」）")
    elif not pb["families"]:
        print("◆ 手册：**未登记**（0 个家族）—— 症状→根因→处置 这条链一次都没查过")
    else:
        print("◆ 手册：%d 个家族；可核边 %d 条已并入上面的 ①②③；"
              "**声明无锚点 %d 条**（诚实，单列）；**缺 evidence %d 条**（缺陷，必须补齐）"
              % (pb["families"], pb["edges"], len(pb["declared"]), len(pb["bare"])))
        for d in pb["declared"]:
            print("     ◇ %s（%s）—— %s：%s" % (d["slug"], d["title"], d["what"][:34], d["reason"]))
        for b in pb["bare"]:
            print("     ✗ %s（%s）—— %s" % (b["slug"], b["title"], b["reason"]))

    cq = res["cjk"]
    print("⑪ ASCII 引号当中文引号：%s（kb/ 内量过 %d 个文件：md %d 宽档 / py %d 严档 / "
          "json %d 只判能解析；命中 %d 处）"
          % (_LABEL[cq["status"]], cq["checked"], cq["md"], cq["py"], cq["json"],
             len(cq["hits"]) + len(cq["bad_json"])))
    for h in cq["hits"]:
        print("     ✗ %s:%d col%d [%s档] %s" % (h["file"], h["line"], h["col"], h["band"], h["text"]))
    for b in cq["bad_json"]:
        print("     ✗ JSON 解析不了：%s" % b)
    rp = cq["repo"]
    print("     ＋ 仓内 .md（kb/ 之外）：%s —— 量过 %d 个文件、命中 %d 处"
          % (_LABEL[rp["state"]], cq["md_repo"], cq["repo_hits"]))
    if rp["blocked"]:
        # ★ 「整档没比」必须与「比过、没有新增」**分开写**。两者都能让 status=gap，
        #   但一个是「尺子/基线不在」，另一个是「真长了东西」（铁律 16 的同族）。
        print("        ⚠ 本档**整档未比**：那 %d 处命中一处也没跟基线对过。" % rp["blocked_hits"])
    print("        %s" % rp["detail"])
    for h in rp["new"]:
        print("     ✗ [新增] %s:%d col%d %s" % (h["file"], h["line"], h["col"], h["text"]))
    # ★ 「没量过」与「干净」不许同形：把**排除掉的目录**和它们各自有几个 .md 数出来。
    skipped = []
    for d in _REPO_MD_SKIP:
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            k = sum(1 for dp, dn, fns in os.walk(p) for f in fns if f.lower().endswith(".md"))
            skipped.append("%s %d" % (d, k))
    print("        （排除清单：%s —— 这些目录里的 .md **一处都没量过**；"
          "没量到和干净不是同一行字）" % ("、".join(skipped) if skipped else "无"))

    gp = res["graph"]
    if gp["status"] == "unavailable":
        print("⑫ 图（out/in）：**UNAVAILABLE** —— %s" % gp["detail"])
    else:
        print("⑫ 图（out/in）：%s —— %s" % (_LABEL[gp["status"]], gp["detail"]))
        print("     " + "；".join("%s %d" % (k, v) for k, v in gp["kinds"].items()))
        if gp["no_anchor"]:
            print("     （其中 **%d 条没有锚点**：同族边是机器派生的对称关系，不指任何文件 —— "
                  "它单列在这里，不算「有据」那一档。★ 它**有** src，值是 `derived:shared-trap`，"
                  "别读成「这些边没有 src」）" % gp["no_anchor"])
        # ★ 未进图的条目**逐条印**：缺锚点/悬空引用被静默丢掉，图里就少一条边，
        #   而「图里有 N 条边」在屏幕上读起来像「宣称就只有这么多」（铁律 16）。
        for s in gp["skipped"]:
            print("     ○ 未进图 %s —— %s" % (s["src"], s["why"]))

    print("⑦ --run 只读：待登记命令 **%d** 条%s"
          % (len(res["cmds"]),
             "（一个都还没查过 —— 这不等于都安全）" if not res["cmds"] else ""))
    for cmd, ok, why, src in res["cmds"]:
        print("     %s %s  ← %s" % ("○" if ok else "✗", cmd, src))
        if not ok:
            print("        拒登：%s" % why)
    print("（尺子自指纹 gate=%s / values=%s，criterion_version=%d）"
          % (res["self_sha12"], res["values_sha12"], res["criterion_version"]))


def _fails(res: dict) -> list[str]:
    out: list[str] = []
    for r in res["edges"]:
        if r["status"] == "gap":
            out.append("边 %s：%s" % (r["edge"]["src"], r["detail"]))
    if res["stale"]["status"] == "gap":
        out.append("陈旧：%s" % res["stale"]["detail"])
    if res["dual"]["status"] == "gap":
        out.append("双源：%s" % res["dual"]["detail"])
    if res["value"]["status"] == "gap":
        out.append("值漂移：%s" % res["value"]["detail"])
    if res["graph"]["status"] == "gap":
        out.append("图：%s" % res["graph"]["detail"])
    elif res["graph"]["status"] == "unavailable":
        out.append("图：%s" % res["graph"]["detail"])
    for h in res["cjk"]["hits"]:
        out.append("引号 %s:%d col%d：ASCII 引号被当中文引号用（%s）"
                   % (h["file"], h["line"], h["col"], h["text"][:60]))
    for b in res["cjk"]["bad_json"]:
        out.append("引号：JSON 解析不了 —— %s" % b)
    if not res["traps"]["present"]:
        out.append("陷阱：%s 不在 —— 这一类没被查过（不是「没有陷阱」）" % TRAPS)
    pb = res["playbook"]
    if not pb["present"]:
        out.append("手册：kb.json 里没有 playbook 这一节 —— 状态未知（先跑 kb/build_kb.py）")
    # ★ 「缺 evidence」是**缺陷**（exit 1）；「声明无锚点」不是（它是诚实，单列报出）。
    #   两者混成一个判据 = 把漏写解放成诚实。
    for b in pb["bare"]:
        out.append("手册 %s：%s" % (b["slug"], b["reason"]))
    for cmd, ok, why, src in res["cmds"]:
        if not ok:
            out.append("--run 拒登 %r（%s）：%s" % (cmd, src, why))
    return out


def _ev_file(ev) -> str | None:
    if not isinstance(ev, str):
        return None
    m = _EV_LINE.match(ev) or _EV_SYM.match(ev)
    return m.group("f") if m else None


def anchor_view(edge: dict) -> str:
    """这条边的锚点**现在指到什么内容**。★行锚点只能证明那一行存在，
    要判它是不是还指着原来的那句话，只能把那一行打出来看。"""
    ev = edge.get("evidence")
    if not isinstance(ev, str):
        return "（无锚点）"
    m = _EV_LINE.match(ev)
    if m:
        rel, n = m.group("f"), int(m.group("n"))
        data = _read_bytes(rel)
        if data is None:
            return "%s —— ★文件不在盘上" % ev
        lines = data.decode("utf-8", "replace").splitlines()
        total = data.count(b"\n") + (0 if data.endswith(b"\n") else 1)
        if n < 1 or n > total:
            return "%s —— ★越界（只有 %d 行）" % (ev, total)
        return "%s → %s" % (ev, lines[n - 1].strip()[:110])
    m = _EV_SYM.match(ev)
    if m:
        return "%s → 符号 %s" % (ev, m.group("s"))
    return "%s —— ★形态认不出" % ev


def stale_anchors(rels, edges: list[dict] | None = None) -> list[dict]:
    """列出指进这些文件的每一条锚点、以及它**现在**指到的内容。"""
    edges = collect_edges() if edges is None else edges
    want = set(rels)
    return [{"src": e.get("src") or "?", "evidence": e.get("evidence"),
             "now": anchor_view(e)}
            for e in edges if _ev_file(e.get("evidence")) in want]


def changed_files(payload: dict, lock_path: str | None = None) -> list[str]:
    """相对上次登记，内容变了的证据文件。没有登记表时**全部**算变动（不许当「都没变」）。"""
    lock_path = LOCK if lock_path is None else lock_path
    old = {}
    if os.path.exists(lock_path):
        try:
            with io.open(lock_path, encoding="utf-8") as fh:
                old = json.load(fh).get("files") or {}
        except (ValueError, OSError):
            old = {}
    return sorted(rel for rel, sha in (payload.get("files") or {}).items()
                  if old.get(rel) != sha)


def record() -> int:
    """登记证据文件的内容指纹。原子写（直写会截成 0 字节）。

    ★ 改一个文件会**移动它后面所有行的行号**，而 ①②③ 只核「那一行存在」——
    改完 re-baseline 时若只打印一句「已登记 28 个」，等于把锚点错位**默默洗掉**。
    所以这里把指进变动文件的锚点逐条打印出来，让 re-baseline 变成一次**定向复核**。
    """
    edges = collect_edges()
    files = watched_files(edges)
    payload = {"criterion_version": CRITERION_VERSION, "self_sha12": _self_sha12(),
               "files": {rel: sha12(_read_bytes(rel)) for rel in files
                         if _read_bytes(rel) is not None}}
    changed = changed_files(payload)
    fd, tmp = tempfile.mkstemp(dir=KB, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, LOCK)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if changed:
        print("★相对上次登记，变动的证据文件 %d 个 —— 改文件会把行号**挪走**，"
              "下面逐条列出指进它们的锚点现在指到什么内容，请核对是否还指着原来那句话："
              % len(changed))
        for rel in changed:
            rows = stale_anchors([rel], edges)
            print("  %s（%d 条锚点指进来）" % (rel, len(rows)))
            for r in rows:
                print("      %-44s %s" % (r["src"][:44], r["now"]))
    else:
        print("（相对上次登记，证据文件内容一字未变）")
    print("已登记 %d 个证据文件 → %s" % (len(payload["files"]), LOCK))
    return 0


def rebaseline_cjk() -> int:
    """登记 ⑪ 仓内 `.md` 档的基线（`kb/cjk-quote-baseline.json`）。

    ★ 这是**一次要人读的动作**，不是「点一下」：它把此刻命中的每一处**按文件列出来**，
      并把**与旧基线相比新增的那几处单独列在最前面** —— 只打印一句「已登记 510 处」
      等于把新增的那一两处**默默洗进基线**（铁律 31：re-baseline 必须打印
      「现在指到什么」，不能只记一串指纹）。
    ★ 内容里**不写时刻**：基线该是 (命中, 尺子) 的纯函数，写进时间戳只会让
      「一字未改」也产生新内容，而那种 churn 会把真正的变动淹掉。
    """
    files = _repo_md_sources()
    hits: list[dict] = []
    for rel in files:
        for h in _cjk_quote_hits(_read_text(rel) or "", wide=True):
            hits.append(dict(h, file=rel, band="md-repo"))
    old, _ = load_cjk_baseline()
    old_entry = ((old or {}).get("bands") or {}).get("md_repo") or {}
    added, _known, cleaned = _band_diff(hits, old_entry)

    entry: dict[str, dict[str, int]] = {}
    for h in hits:
        b = entry.setdefault(h["file"], {})
        b[h["raw12"]] = b.get(h["raw12"], 0) + 1
    payload = {
        "criterion_version": 1,
        "ruler_sha12": _self_sha12(),
        "what": "⑪ 仓内 .md 档（kb/ 之外）的**既有命中基线**：基线内放行、新增即红。",
        "keys": "文件 → {整行(去首尾空白)的 sha12: 处数}；用内容不用行号（行号会漂，见铁律 31）",
        "excluded": list(_REPO_MD_SKIP),
        "counts": {"files": len(entry), "hits": len(hits),
                   "new_vs_old": len(added), "cleaned_vs_old": cleaned},
        "bands": {"md_repo": {f: dict(sorted(d.items())) for f, d in sorted(entry.items())}},
    }
    fd, tmp = tempfile.mkstemp(dir=KB, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, CJK_BASELINE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    print("⑪ 基线登记：仓内 .md 量过 %d 个文件、命中 %d 处，落在 %d 个文件里"
          % (len(files), len(hits), len(entry)))
    if not old:
        print("（首次登记 —— 没有旧基线可比，下面全部按「基线内」放行）")
    elif added:
        print("★ 相对旧基线**新增 %d 处** —— 这几处是本次真正要人看的东西，"
              "确认它们可以留在库里再签收：" % len(added))
        for h in added:
            print("   ✗ [新增] %s:%d col%d %s" % (h["file"], h["line"], h["col"], h["text"]))
    else:
        print("（相对旧基线**一处新增都没有**）")
    if old:
        print("基线里 %d 处已不存在（清理掉了是好事，但也要看得见）" % cleaned)
    print("已写入 %s（尺子 kb/gate.py sha12 = %s）"
          % (os.path.relpath(CJK_BASELINE, ROOT).replace(os.sep, "/"), payload["ruler_sha12"]))
    return 0


def anchors_report() -> int:
    """把全库锚点连同**它现在指到的内容**打一份出来。改过文档后跑一遍，肉眼即可核错位。"""
    by_file: dict[str, list[dict]] = {}
    for e in collect_edges():
        rel = _ev_file(e.get("evidence"))
        by_file.setdefault(rel or "（无锚点）", []).append(e)
    print("全部锚点 %d 条，落在 %d 个文件上（下面每行是「锚点 → 它此刻指到的内容」）："
          % (sum(len(v) for v in by_file.values()), len(by_file)))
    for rel in sorted(by_file):
        rows = by_file[rel]
        print("  %s（%d 条）" % (rel, len(rows)))
        for e in rows:
            print("      %-44s %s" % ((e.get("src") or "?")[:44], anchor_view(e)))
    return 0


# ── 自检：十二条刑具，每条都要能红 ──────────────────────────

def selftest() -> int:
    fails: list[str] = []

    # ① 路径不在盘上 ⇒ GAP
    r = check_edge({"src": "T1", "evidence": "no/such/file.py:1"})
    if r["status"] != "gap":
        fails.append("T① 不存在的路径 ⇒ %s（应为 gap）" % r["status"])

    # ② 行号越界 ⇒ GAP
    r = check_edge({"src": "T2", "evidence": "kb/gate.py:999999"})
    if r["status"] != "gap":
        fails.append("T② 行号越界 ⇒ %s（应为 gap）" % r["status"])

    # ③ 符号不在 ⇒ GAP；且**注释里提一嘴不算实现**
    r = check_edge({"src": "T3", "evidence": "kb/gate.py:NO_SUCH_SYMBOL_XYZ"})
    if r["status"] != "gap":
        fails.append("T③ 不存在的符号 ⇒ %s（应为 gap）" % r["status"])
    r = check_edge({"src": "T3b", "evidence": "kb/gate.py:_WRITE_TOKENS"})
    if r["status"] != "pass":
        fails.append("T③ 真存在的符号 ⇒ %s（应为 pass）" % r["status"])

    # ④ 值漂移由 values.py 自带阳性对照，这里只核它真接上了
    va = _run_values()
    if va["total"] == 0:
        fails.append("T④ values.py 一行都没比到 —— ④ 没接上")

    # ⑤ 双源：两侧都解析出来了才算比过
    du = check_dual_source()
    if du["status"] == "unavailable":
        fails.append("T⑤ 双源两侧解析不出：%s" % du["detail"])
    elif du.get("compared", 0) == 0:
        fails.append("T⑤ 双源比过 0 个前缀 —— 判据空转（会恒绿）")

    # ⑥ 陈旧：改一个字节 ⇒ 必须红
    # ★ 用**临时** lock 文件，绝不碰真的 evidence-lock.json ——
    #   自检把用户的基线写掉，是比漏检更坏的事故。
    global LOCK
    keep = LOCK
    tmp_lock = None
    try:
        fd, tmp_lock = tempfile.mkstemp(dir=KB, suffix=".lock")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"files": {"kb/gate.py": "000000000000"}}, fh)
        LOCK = tmp_lock
        st = check_stale(["kb/gate.py"])
        if st["status"] != "gap":
            fails.append("T⑥ 指纹与登记不符 ⇒ %s（应为 gap）" % st["status"])
        # ★ 边界：**不在登记表里**的文件必须显形，且不许计入 compared。
        #   2026-09-24 实测它就藏在屏幕上：新加的锚点指向新文件（归档副本等 9 个），
        #   ⑥ 报 GAP 时只印了那 3 个「内容变了」的，这 9 个「从没核过」一个都没露面。
        #   ⚠ 这一条必须待在**临时 lock 还挂着**的时候 —— 我第一次把它写在下面那一档之后，
        #   于是它跑在没有登记表的条件里，回 unavailable=0/compared=0，红了一条假红
        #   （夹具没走到被测那一步：memory `fixture-line-never-enters-its-branch`）。
        st = check_stale(["kb/gate.py", "kb/ask.py"])
        un = [r for r in st["rows"] if r[1] == "unavailable"]
        if len(un) != 1 or st["compared"] != 1:
            fails.append("T⑥ 未登记的文件必须显形且不计入 compared（实测 unavailable=%d "
                         "compared=%d，应为 1/1）" % (len(un), st["compared"]))
        LOCK = os.path.join(KB, "no-such-lock.json")
        st = check_stale(["kb/gate.py"])
        if st["status"] != "unavailable":
            fails.append("T⑥ 没有登记表 ⇒ %s（应为 unavailable，不是 pass）" % st["status"])
    finally:
        LOCK = keep
        if tmp_lock and os.path.exists(tmp_lock):
            os.unlink(tmp_lock)

    # ⑦ 白名单：写操作必须被拒，只读必须放行
    for bad in ("python -u backend/checks/qa_structural.py --apply",
                "python -u kb/ask.py -o out.json",
                "python -u backend/checks/runner.py --all > log.txt",
                "curl http://x"):
        if readonly_ok(bad)[0]:
            fails.append("T⑦ %r 被放行了（含写操作/非白名单入口）" % bad)
    if not readonly_ok("python -u backend/checks/qa_structural.py")[0]:
        fails.append("T⑦ 只读命令被误拒：%s" % readonly_ok("python -u backend/checks/qa_structural.py")[1])

    # ⑧ 陷阱：**有锚点的边被收上来** 且 **没锚点的被数出来**（不是被丢掉）
    #   ★ 阳性对照用临时 traps 文件：一条有 case、一条无 case，
    #     必须分别落进 (edges, bare) 两栏；只断言「收上来了」会让整条静默失效溜过去。
    global TRAPS
    keep_t = TRAPS
    tmp_t = None
    try:
        fd, tmp_t = tempfile.mkstemp(dir=KB, suffix=".traps")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"traps": {
                "t-with-anchor": {"title": "有锚点", "cases": [
                    {"where": "kb/gate.py:readonly_ok", "what": "对照用"}],
                    "related": ["kb/gate.py:_names_in"]},
                "t-no-anchor": {"title": "只有人记着", "cases": [],
                                "unverifiable": "暂无可核锚点",
                                "related": ["kb/gate.py:check_edge"]},
                "t-case-without-where": {"title": "有 case 但没写地址",
                                         "cases": [{"what": "只写了证明什么"}]}}}, fh)
        TRAPS = tmp_t
        e2, b2 = collect_trap_edges()
        # 2 条 case 边 ＋ 1 条 related 边（那 1 条来自**无锚点**的陷阱：
        # 免责按条不按条块 —— 「这段没写证据」不等于「它的关联边也可以免检」）
        if len(e2) != 3:
            fails.append("T⑧ 有锚点的陷阱+related ⇒ 收上 %d 条边（应为 3）" % len(e2))
        if not any(e["src"] == "trap:t-no-anchor.related[0]" for e in e2):
            fails.append("T⑧ 无锚点陷阱的 related 被一并免检了（应按条收边）")
        # ★ 「case 没写 where」必须落进 bare：顺着 `None ⇒ N/A`（声明无实现）溜过去
        #   就是本仓排第一的坑（没量成读成通过）。
        if [b["slug"] for b in b2] != ["t-no-anchor", "t-case-without-where"]:
            fails.append("T⑧ 无锚点/缺 where 的陷阱必须落进 bare，实得 %r" % [b["slug"] for b in b2])
        r = check_edge(e2[0]) if e2 else {"status": "?"}
        if r["status"] != "pass":
            fails.append("T⑧ 陷阱边没走 ①②③ 复核 ⇒ %s" % r["status"])
        # 空表（有 traps 键、一条都没有）⇒ 两栏都为空，不许假装有东西
        with io.open(tmp_t, "w", encoding="utf-8") as fh:
            json.dump({"traps": {}}, fh)
        e3, b3 = collect_trap_edges()
        if e3 or b3:
            fails.append("T⑧ 空 traps 表 ⇒ 收上 %d 边 %d 无锚（都应为 0）" % (len(e3), len(b3)))
    finally:
        TRAPS = keep_t
        if tmp_t and os.path.exists(tmp_t):
            os.unlink(tmp_t)

    # ⑨ 手册：六栏都收成边；**缺 evidence 的落 bare（缺陷）**、
    #   **`unverified[]` 落 declared（诚实）** —— 两栏混成一栏就是把漏写解放成诚实。
    fake = {"entries": {}, "playbook": {"f-1": {
        "title": "注入的家族", "kind": "symptom",
        "symptoms": [{"what": "注S", "evidence": "kb/gate.py:readonly_ok"},
                     {"what": "缺据的S"}],
        "causes": [{"what": "注C", "evidence": "kb/gate.py:NO_SUCH_XYZ"}],
        "fixes": [{"what": "注F", "evidence": "kb/gate.py:_names_in"}],
        "instances": [{"where": "c057 F1", "measured": "6.88m",
                       "evidence": "kb/gate.py:sha12"}],
        "related": [{"slug": "f-2", "evidence": "kb/gate.py:check_edge"}],
        "runs": [{"cmd": "python -u kb/ask.py x", "writes": "无",
                  "evidence": "kb/gate.py:main"}],
        "unverified": [{"what": "注U", "reason": "仓内无锚点"}]}}}
    pe, pbare, pdecl = collect_playbook_edges(fake)
    if len(pe) != 6:
        fails.append("T⑨ 手册六栏 ⇒ 收上 %d 条边（应为 6：症状1+根因+处置+实例+关联+判据）"
                     % len(pe))
    if [b["slug"] for b in pbare] != ["f-1"]:
        fails.append("T⑨ 缺 evidence 的条目必须落 bare，实得 %r" % [b["slug"] for b in pbare])
    if not any("symptoms" in b["reason"] for b in pbare):
        fails.append("T⑨ bare 的理由没点出是哪一栏哪一条（只说「有缺据的」等于没说）")
    if [d["what"] for d in pdecl] != ["注U"]:
        fails.append("T⑨ unverified[] 必须落 declared 单列，实得 %r" % [d["what"] for d in pdecl])
    if any("注U" in (b.get("reason") or "") for b in pbare):
        fails.append("T⑨ 声明无锚点的条目混进了「缺 evidence」那一栏")
    # 手册边必须真走 ①②③（不是收上来就算数）：坏符号红、好符号绿
    got = {r["edge"]["src"]: r["status"] for r in (check_edge(e) for e in pe)}
    if got.get("pb:f-1.causes[0]") != "gap":
        fails.append("T⑨ 手册里的坏符号没红（%s）—— 手册边没走 ①②③" % got.get("pb:f-1.causes[0]"))
    if got.get("pb:f-1.symptoms[0]") != "pass":
        fails.append("T⑨ 手册里的好符号没绿（%s）" % got.get("pb:f-1.symptoms[0]"))
    # ✅ 阳性对照：`cb()` 里的 cmd 认得出、缺 writes 的必须被拒
    f2 = {"entries": {}, "playbook": {"f-2": {"runs": [
        {"cmd": "python -u qa_structural.py c057", "writes": "无",
         "evidence": "kb/gate.py:readonly_ok"},
        {"cmd": "python -u qa_defect_census.py c057", "evidence": "kb/gate.py:readonly_ok"}]}}}
    c2 = _declared_commands(f2)
    if len(c2) != 2:
        fails.append("T⑨ 手册的 runs 没进待登记命令表（实得 %d 条）" % len(c2))
    if not readonly_ok("python -u qa_structural.py c057")[0]:
        fails.append("T⑨ 根目录 qa_ 脚本被误拒：%s"
                     % readonly_ok("python -u qa_structural.py c057")[1])
    if readonly_ok("python -u qa_defect_census.py c057 --apply")[0]:
        fails.append("T⑨ qa_ 前缀把写操作标记一起放行了")

    # 真表上：**条数必须报出来**（只有 0 条 = 没接上；0 条边不许静默当绿）
    if os.path.exists(TRAPS):
        e4, b4 = collect_trap_edges()
        if not e4:
            fails.append("T⑧ 真 traps.json 一条锚点边都收不上来 —— ⑧ 没接上")

    # ⑩ re-baseline 的差异报告：改了文件，必须**列出指进它的锚点现在指到什么**
    #    ★两面都要测：只改一个文件时必须**只报它**（既不能漏报、也不能全表皆红），
    #      而且锚点视图必须真的把「此刻指到的那行内容」打出来。
    keep_l = LOCK
    tmp_l = None
    try:
        edges10 = collect_edges()
        pay = {"files": {rel: sha12(_read_bytes(rel)) for rel in watched_files(edges10)
                         if _read_bytes(rel) is not None}}
        # ★夹具不许写死文件名。这条控制原先钉在 `kb/README.md` 上，而本文件当天
        #   把两条指进 README 的**行锚点**改成了代码**符号锚点** ⇒ README 从此不是
        #   被看的证据文件 ⇒ 控制当场红（「锚点视图无从测起」）。它红得对
        #   （判据缺夹具时不许静默当绿），但夹具绑死在某个文件上就会随文件一起漂。
        #   ⇒ 从**真表**里挑一个「至少 2 条锚点指进来」的注册文件当靶子。
        cand = [f for f in sorted(pay["files"]) if len(stale_anchors([f], edges10)) >= 2]
        if not cand:
            fails.append("T⑩ 真表里没有一个「≥2 条锚点指进来」的证据文件 —— 锚点视图无从测起")
        else:
            target = cand[0]
            fd, tmp_l = tempfile.mkstemp(dir=KB, suffix=".lock")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"files": dict(pay["files"], **{target: "000000000000"})}, fh)
            ch = changed_files(pay, tmp_l)
            if ch != [target]:
                fails.append("T⑩ 只改了 1 个文件（%s）却报变动 %r（漏报或误报都算没接上）"
                             % (target, ch))
            rows10 = stale_anchors([target], edges10)
            if len(rows10) < 2:
                fails.append("T⑩ 指进 %s 的锚点只列出 %d 条（挑它就是因为至少 2 条）"
                             % (target, len(rows10)))
            if not all(target in r["now"] and "→" in r["now"] for r in rows10):
                fails.append("T⑩ 锚点视图没把「此刻指到的内容」打出来：%r"
                             % [r["now"][:40] for r in rows10])
            # ★阴性对照必须配**与真值相同**的登记表：拿刚才那份坏表去比对，
            #   它当然还会报 kb/README.md —— 那是夹具写错了，不是判据错了。
            fd2, tmp_l2 = tempfile.mkstemp(dir=KB, suffix=".lock")
            with os.fdopen(fd2, "w", encoding="utf-8") as fh:
                json.dump({"files": dict(pay["files"])}, fh)
            ch_none = changed_files(pay, tmp_l2)
            os.unlink(tmp_l2)
            if ch_none:
                fails.append("T⑩ 一字未改却报变动 %r —— 差异报告会天天喊，喊三次就没人看"
                             % (ch_none,))
    finally:
        LOCK = keep_l
        if tmp_l and os.path.exists(tmp_l):
            os.unlink(tmp_l)

    # ⑪ ASCII 引号当中文引号（铁律 15）。**两档分开测**，理由：它们是两条规则
    #   （严档=两侧皆汉字 / 宽档=任一侧 CJK），只测一条 = 另一条没量过；而 md 那条
    #   恰是实测漏网的形态（`把"C4 是 gap"的红快照` —— 一侧夹着拉丁词，窄规则看不见）。
    #   ★ 每条阳性对照旁边都配一个**不许命中**的：判据宽了会比漏检更坏 ——
    #     它会开始误伤所有正常的中文字符串，然后被人学会忽略。
    md_fx = ("正文 把\"甲\"的写成引号\n"
             "`命令 \"参数\" 参数` ← 落在反引号跨度里，不许命中\n"
             "```\n代码块 \"A1\" 里的引号也不算\n```\n")
    h_md = _cjk_quote_hits(md_fx, wide=True)
    if len(h_md) != 2:
        fails.append("T⑪ 宽档（md）⇒ 命中 %d 处（应 2：一处引号对的左右两边）。"
                     "反引号跨度与围栏里各 0 —— 若为 4，就是掩码没生效" % len(h_md))
    py_fx = ("x = \"汉字\"                # ← 正常定界符，不许命中\n"
             "# 汉字\"甲\"汉字            # ← 写错了，必须命中两处\n")
    h_py = _cjk_quote_hits(py_fx, wide=False)
    if len(h_py) != 2:
        fails.append("T⑪ 严档（py）⇒ 命中 %d 处（应 2）。为 0 ⇒ 看不见写错的形态；"
                     ">2 ⇒ 它误伤了正常的中文字符串（那种判据会被学会忽略）" % len(h_py))

    # 真库：**分母不许是 0**（量到 0 个文件 = 空转恒绿），且三档都得有文件 ——
    # 某一档 0 个文件 = 那一档等于不存在，而它在屏幕上和「干净」一模一样。
    rq = check_cjk_quotes()
    if rq["checked"] == 0:
        fails.append("T⑪ 真库上量到 0 个文件 —— ⑪ 空转（会恒绿）")
    if not (rq["md"] and rq["py"] and rq["json"]):
        fails.append("T⑪ 有一档没量到文件（md %d / py %d / json %d）—— 那个档等于不存在"
                     % (rq["md"], rq["py"], rq["json"]))
    if rq["md_repo"] == 0:
        fails.append("T⑪ 第四档（仓内 .md）量到 0 个文件 —— 那一档等于不存在，"
                     "而它在屏幕上和「干净」一模一样")

    # ★ 第四档（仓内 .md，带基线）。**夹具的形状必须抄真产物**：真的在仓库根上放
    #   `.md`（README.md 就在根上），而不是塞给纯函数一个字符串 ——
    #   本仓实测过「13 条自检全绿而 bug 活了一轮」，成因就是夹具形状与真产物不同。
    #   ★ 三件事分开验，因为它们会**各自**坏：基线内放行 / 新增报红 / 排除清单生效。
    fx_line = "正文 把\"甲\"的写成引号"
    h_fx = _cjk_quote_hits(fx_line, wide=True)
    if len(h_fx) != 2:
        fails.append("T⑪repo 夹具行应命中 2 处（引号对的左右两边），实得 %d" % len(h_fx))
    else:
        k = h_fx[0]["raw12"]
        if k != h_fx[1]["raw12"]:
            fails.append("T⑪repo 同一行的两处命中 raw12 不同 —— 基线的键没按「行」算")
        hits_x = [dict(h, file="_qa/x.md") for h in h_fx]
        nm, kn, cl = _band_diff(hits_x, {"_qa/x.md": {k: 2}})
        if (len(nm), kn, cl) != (0, 2, 0):
            fails.append("T⑪repo 两处都在基线内却报 新增%d/命中%d/清理%d（应 0/2/0）"
                         % (len(nm), kn, cl))
        nm2, kn2, _ = _band_diff(hits_x + [dict(h_fx[0], file="_qa/y.md")],
                                 {"_qa/x.md": {k: 2}})
        if (len(nm2), kn2) != (1, 2):
            fails.append("T⑪repo 换了个文件的那一处没被报成新增（新增 %d / 命中 %d，"
                         "应 1/2）—— 键里少了「文件」这一维" % (len(nm2), kn2))
        nm3, _, cl3 = _band_diff([], {"_qa/x.md": {k: 2}})
        if (len(nm3), cl3) != (0, 2):
            fails.append("T⑪repo 基线被清空后「清理了 %d 处」没数出来 —— 那样「基线被"
                         "清空」和「基线本来就小」会同形（闸门变哑而屏幕上一片绿）" % cl3)
    #   ★ 尺子指纹那一支：**必须红**。这是铁律 24 的形态 ——
    #     「这份基线是旧尺子量的」与「这份基线是对的」在屏幕上必须不是同一行字。
    global CJK_BASELINE
    keep_cb = CJK_BASELINE
    tmp_cb = tmp_cb2 = ""
    try:
        one = [{"file": "_qa/x.md", "line": 1, "col": 1, "text": "t", "raw12": "aaaaaaaaaaaa"}]
        fd_c1, tmp_cb = tempfile.mkstemp(dir=KB, suffix=".json")
        with os.fdopen(fd_c1, "w", encoding="utf-8") as fh:
            # ★ 这一份基线里**命中是在的** —— 与下面那份只差 `ruler_sha12` 一个变量。
            #   第一版这里写的是空基线，于是「状态应为 gap」在**拆掉尺子判断之后照样绿**
            #   （空基线本来就报新增 ⇒ 恒 gap）—— 那条断言是空的。
            json.dump({"criterion_version": 1, "ruler_sha12": "000000000000",
                       "bands": {"md_repo": {"_qa/x.md": {"aaaaaaaaaaaa": 1}}}}, fh)
        CJK_BASELINE = tmp_cb
        rb = cjk_repo_band(one)
        if rb["state"] != "gap":
            fails.append("T⑪repo 尺子指纹对不上时状态仍为 %s（应为 gap）" % rb["state"])
        if "尺子变了" not in rb["detail"]:
            fails.append("T⑪repo 尺子对不上，但说明里没点出是尺子变了：%r" % rb["detail"][:60])
        if not rb["blocked"] or rb["new"]:
            # ★ 「整档没比」不许长得像「真长了东西」：真库上那 510 处若全塞进 `new`，
            #   屏幕会被淹掉，而最该看见的「先重登记」被埋在最下面。
            fails.append("T⑪repo 尺子对不上时没标成整档未比（blocked=%r / new %d 条）"
                         % (rb["blocked"], len(rb["new"])))
        fd_c2, tmp_cb2 = tempfile.mkstemp(dir=KB, suffix=".json")
        with os.fdopen(fd_c2, "w", encoding="utf-8") as fh:
            json.dump({"criterion_version": 1, "ruler_sha12": _self_sha12(),
                       "bands": {"md_repo": {"_qa/x.md": {"aaaaaaaaaaaa": 1}}}}, fh)
        CJK_BASELINE = tmp_cb2
        rb2 = cjk_repo_band(one)
        if (rb2["state"], rb2["known"], len(rb2["new"])) != ("pass", 1, 0):
            fails.append("T⑪repo 尺子对上且命中在基线内 ⇒ 应放行，实得 %s/命中%d/新增%d"
                         % (rb2["state"], rb2["known"], len(rb2["new"])))
    finally:
        CJK_BASELINE = keep_cb
        for p in (tmp_cb, tmp_cb2):
            if p and os.path.exists(p):
                os.unlink(p)

    #   ★ 盘上三件事：坏引号的新文件必须**在 new 里**／正确写法的新文件必须**不在**／
    #     排除目录里的必须**一处都不算**。第三条最要紧：排除规则坏了是**静默**的。
    #   ★★ 这一组**必须自己带一份基线**（空 bands ＋ 当前尺子指纹），不许借真库那一份：
    #      借的话，真库基线一旦是「尺子变了」的状态，整档就是 blocked、`new` 恒空 ⇒
    #      「坏引号没被抓」这条**假红**（代码是对的，错在夹具没把要验的变量孤立出来
    #      —— 本仓铁律 26 记的正是这个形状）。第一次跑就是这么红的。
    keep_cb2 = CJK_BASELINE
    tmp_cb3 = ""
    tmp_md = []
    try:
        fd_c3, tmp_cb3 = tempfile.mkstemp(dir=KB, suffix=".json")
        with os.fdopen(fd_c3, "w", encoding="utf-8") as fh:
            json.dump({"criterion_version": 1, "ruler_sha12": _self_sha12(),
                       "bands": {"md_repo": {}}}, fh)
        CJK_BASELINE = tmp_cb3
        fd_b, p_bad = tempfile.mkstemp(prefix="_tmp_cjk_bad_", suffix=".md", dir=ROOT)
        with os.fdopen(fd_b, "w", encoding="utf-8") as fh:
            fh.write(fx_line + "\n")
        fd_o, p_ok = tempfile.mkstemp(prefix="_tmp_cjk_ok_", suffix=".md", dir=ROOT)
        with os.fdopen(fd_o, "w", encoding="utf-8") as fh:
            # 阴性对照：正确写法（「」＋ 反引号跨度里的 ASCII 引号）不许被算成命中。
            fh.write("正文 把「甲」的写成引号，命令 `x \"y\" z` 落在反引号跨度里\n")
        fd_s, p_sk = tempfile.mkstemp(prefix="_tmp_cjk_skip_", suffix=".md",
                                      dir=os.path.join(ROOT, "_scratch"))
        with os.fdopen(fd_s, "w", encoding="utf-8") as fh:
            fh.write(fx_line + "\n")
        tmp_md = [p_bad, p_ok, p_sk]
        rq2 = check_cjk_quotes()
        got_new = {os.path.relpath(h["file"], ROOT).replace(os.sep, "/")
                   for h in rq2["repo"]["new"]}
        r_bad = os.path.relpath(p_bad, ROOT).replace(os.sep, "/")
        r_ok = os.path.relpath(p_ok, ROOT).replace(os.sep, "/")
        r_sk = os.path.relpath(p_sk, ROOT).replace(os.sep, "/")
        if r_bad not in got_new:
            fails.append("T⑪repo 盘上新长的坏引号没被抓（%s）—— 这一档没接上盘" % r_bad)
        if rq2["status"] != "gap":
            fails.append("T⑪repo 有新增命中时整体状态仍为 %s（应为 gap）" % rq2["status"])
        if r_ok in got_new:
            fails.append("T⑪repo 阴性对照被误报（「」与反引号跨度里的引号撞红了）——"
                         " 判据宽了会被学会忽略，比漏检更坏")
        if r_sk in got_new:
            fails.append("T⑪repo 排除清单没生效：_scratch/ 下的 .md 被算进来了（%s）"
                         " —— 排除规则坏了是**静默**的" % r_sk)
    finally:
        CJK_BASELINE = keep_cb2
        for p in tmp_md + ([tmp_cb3] if tmp_cb3 else []):
            if os.path.exists(p):
                os.unlink(p)

    # json 那一档的阳性对照：**把坏文件真放到 kb/ 下**再扫一遍（只喂函数不算接上了盘）。
    fd_j, tmp_j = tempfile.mkstemp(dir=KB, suffix=".json")
    try:
        with os.fdopen(fd_j, "w", encoding="utf-8") as fh:
            fh.write('{"a": "未闭合}')          # 引号没配平，json.loads 必抛
        rj = check_cjk_quotes()
        if not any(os.path.basename(tmp_j) in b for b in rj["bad_json"]):
            fails.append("T⑪ 盘上的坏 JSON 没被抓 —— json 那一档没接上盘")
        if rj["status"] != "gap":
            fails.append("T⑪ 有坏 JSON 时状态仍为 %s（应为 gap）" % rj["status"])
    finally:
        if os.path.exists(tmp_j):
            os.unlink(tmp_j)

    # ⑫ 图：派生 / 逆表 / 端点 / 权重 / 再派生 / 悬空引用。
    #   ★ 这一组分两半：**前半证明它绿**（阴性对照），**后半逐条证明它能红**。
    #     只测红 ⇒ 判据可能恒红（那不是严格，是坏了）；只测绿 ⇒ 正是本仓排第一的坑
    #     （`saturation`：全绿先问「它是不是在全部样本上都取极值」）。
    # 夹具把陷阱**放进 payload**（`traps_table` 的「产物优先」那一路），不碰真表 ——
    # 顺带证明这条取表规矩是通的。
    fake12 = {"entries": {"e-1": {"recognition": [
                  {"what": "识A", "evidence": "kb/gate.py:node_kind"}]}},
              "traps": {
                  "t-known": {"title": "对照陷阱",
                              "cases": [{"where": "kb/gate.py:readonly_ok", "what": "对照"}]},
                  "t-other": {"title": "另一个对照陷阱",
                              "cases": [{"where": "kb/gate.py:check_edge", "what": "对照"}]}},
              "playbook": {
                  "f-a": {"title": "家族A", "traps": ["trap:t-known"],
                          "symptoms": [{"what": "症状A", "evidence": "kb/gate.py:sha12"}],
                          "runs": [{"cmd": "python -u kb/ask.py x", "writes": "无",
                                    "evidence": "kb/gate.py:main"}]},
                  "f-b": {"title": "家族B", "traps": ["t-known"],
                          "symptoms": [{"what": "症状B", "evidence": "kb/gate.py:sha12"}]}}}
    g12 = graph_edges(fake12)
    # 九条：症状×2 ＋ 判据（run:ask.py）＋ 识别 ＋ 陷阱实物×2 ＋ 并列陷阱×2 ＋ 同族×1 = 9。
    # ⚠ 第一次我写的是 7 —— 漏了「陷阱的 cases 也收边」这一路（实测报 9）。
    #   数边的时候先分类打印，别心算（铁律 22：推出来的数要跟量出来的数对一次）。
    if len(g12["edges"]) != 9:
        fails.append("T⑫ 夹具应派生 9 条边，实得 %d（%r）"
                     % (len(g12["edges"]), sorted(e["kind"] for e in g12["edges"])))
    # 家族A 写的是 `trap:t-known`（带前缀），家族B 写的是 `t-known` —— 两种写法都必须
    # 落到同一个节点，否则「同族」这条派生边永远出不来（而且不会报错）。
    if not any(e["kind"] == "同族" for e in g12["edges"]):
        fails.append("T⑫ 两种陷阱写法（trap:x / x）没归到同一个节点 ⇒ 同族边生不出来")
    # run: 节点取的是**脚本名**，不是整条命令
    if not any(n == "run:ask.py" for n in g12["nodes"]):
        fails.append("T⑫ run: 节点没建出来（节点=%r）" % sorted(g12["nodes"])[:6])
    pay12 = dict(fake12, graph=g12)
    # ★ 阴性对照：**一字未改 ⇒ 必须绿**。它红了说明判据坏了，不是产物坏了。
    ok12 = check_graph(pay12)
    if ok12["status"] != "pass":
        fails.append("T⑫ 未改动的图 ⇒ %s（应为 pass）：%s" % (ok12["status"], ok12["detail"]))
    # ★ 没有 graph 一节 ⇒ **unavailable**，不许是 pass（「没量过」不是「干净」）
    if check_graph(fake12)["status"] != "unavailable":
        fails.append("T⑫ 产物里没有 graph 一节 ⇒ %s（应为 unavailable）"
                     % check_graph(fake12)["status"])

    def _mut12(what: str, want: str, fn) -> None:
        """改坏一处，要求**红且指名**。want 是那句话里必须出现的词。"""
        bad = json.loads(json.dumps(pay12))
        fn(bad["graph"])
        r = check_graph(bad)
        if r["status"] != "gap":
            fails.append("T⑫ %s ⇒ %s（应为 gap：%s）" % (what, r["status"], r["detail"]))
        elif want not in r["detail"]:
            fails.append("T⑫ %s 红了但没指名 %r：%s" % (what, want, r["detail"]))

    _mut12("out 里少一条边", "out", lambda g: g["out"].__setitem__(
        sorted(g["out"])[0], g["out"][sorted(g["out"])[0]][1:]))
    _mut12("in 里少一条边", "in", lambda g: g["in"].__setitem__(
        sorted(g["in"])[0], g["in"][sorted(g["in"])[0]][1:]))
    _mut12("edges 里多一条假边", "没进 out", lambda g: g["edges"].append(
        {"from": "pb:f-a", "to": "ev:假的", "kind": "症状", "w": 0.4,
         "label": "手加的", "src": "手加"}))
    _mut12("端点没登记在 nodes 里", "端点", lambda g: g["nodes"].pop("trap:t-known"))
    _mut12("权重越界", "权重", lambda g: g["edges"][0].__setitem__("w", 1.5))
    _mut12("认不得的 kind", "kind", lambda g: g["edges"][0].__setitem__("kind", "乱写"))
    # ★ 只改 label（from/to/kind 一字未动）⇒ 逆表两半全都还是绿的，
    #   只有「与再派生逐条相同」这一条能抓住它。这正是 (c) 存在的理由：
    #   它证明**产物里那份边表**才是被比的对象，而不是「out 与 in 互相对了一遍」。
    _mut12("只手改 edges 的标签", "再派生", lambda g: g["edges"][0].__setitem__(
        "label", "手改的"))

    # 悬空引用：手册点了一个不存在的陷阱 —— 原先 spread() 是**静默丢掉**这条边的
    dang = json.loads(json.dumps(fake12))
    dang["playbook"]["f-b"]["traps"] = ["t-不存在的"]
    gd = graph_edges(dang)
    if not [s for s in gd["skipped"] if "不存在" in s["why"]]:
        fails.append("T⑫ 悬空陷阱引用没落进 skipped（静默丢掉 = 那条边少一条而无人知）")
    rd = check_graph(dict(dang, graph=gd))
    if rd["status"] != "gap" or "悬空引用" not in rd["detail"]:
        fails.append("T⑫ 悬空陷阱引用 ⇒ %s / %s（应为 gap 且指名「悬空引用」）"
                     % (rd["status"], rd["detail"]))
    # ★ `traps_table` 的「产物优先」：带了 traps 节的 payload 不许被盘上的文件顶掉。
    #   这一条正是上面修掉的那个缺陷（判边用产物、取表读文件）。
    if traps_table({"traps": {}}) != {} or traps_table({}) == {}:
        fails.append("T⑫ traps_table 的产物优先没生效（空表 vs 没有这一节 分不开）")
    # 节点/脚本名的判法本身（一处判断，别处都跟着它）
    if (node_kind("pb:x"), node_kind("trap:x"), node_kind("run:a.py"),
            node_kind("制图标准总览")) != ("family", "trap", "run", "entry"):
        fails.append("T⑫ 节点类别判法不全（run:/entry 兜底那两格最容易漏）")
    if run_script("python -u kb/ask.py x") != "ask.py" or run_script("curl http://x") is not None:
        fails.append("T⑫ run_script 的取法不对（取不出时必须回 None，**不许编**）")

    if fails:
        print("--selftest 红：%d 条刑具没通过" % len(fails))
        for f in fails:
            print("   · " + f)
        return 1
    n_e, n_b = collect_trap_edges()
    if os.path.exists(KBJSON):
        _pb = json.loads(io.open(KBJSON, encoding="utf-8").read()).get("playbook") or {}
        n_f, n_pbe, n_pbb = len(_pb), len(collect_playbook_edges(
            {"entries": {}, "playbook": _pb})[0]), len(collect_playbook_edges(
            {"entries": {}, "playbook": _pb})[1])
        pb_note = ("手册 %d 个家族（可核边 %d 条，缺 evidence %d 条）" % (n_f, n_pbe, n_pbb)
                   if n_f else "手册 **未登记**（0 个家族）—— 症状→根因→处置 这条链一次都没查过")
    else:
        pb_note = "手册 **量不了**（kb.json 不在）"
    print("--selftest 绿：**12 条**刑具全部能红（①路径 ②行号 ③符号+注释不算 ④接上 ⑤非空转 "
          "⑥改一字节即红+无表即说量不了 ⑦写操作被拒/只读放行 ⑧陷阱分两栏 ⑨手册三栏 "
          "⑩re-baseline 差异报告只报真变动的文件、且打出锚点此刻指到的内容 "
          "⑪引号两档各自能红+掩码生效+分母非零、仓内 .md 档带基线（基线内放行/新增即红/"
          "排除清单生效/尺子变了整档未比）"
          "⑫图：未改即绿／无这一节即「量不了」／逆表两侧各能红／假边／悬空端点／权重／"
          "kind／只手改标签＋悬空陷阱引用"
          "；现表：陷阱可核边 %d 条、只有人记着 %d 条；%s" % (len(n_e), len(n_b), pb_note))
    return 0


def main(argv: list[str]) -> int:
    # `--json` 时 stdout 只许有 JSON：所有非 JSON 的字都走 stderr。
    say = sys.stderr if "--json" in argv else sys.stdout
    for a in argv:
        if a.startswith("-") and a not in _FLAGS:
            say.write("不认得的开关 %r；只支持 %s\n" % (a, " ".join(_FLAGS)))
            return 2
    if "--selftest" in argv:
        return selftest()
    if "--anchors" in argv:
        return anchors_report()
    if "--record" in argv:
        return record()
    if "--cjk-baseline" in argv:
        return rebaseline_cjk()
    if not os.path.exists(KBJSON):
        say.write("红：%s 不在。先跑 python -u kb/build_kb.py\n" % KBJSON)
        return 1
    res = run()
    as_json = "--json" in argv
    if as_json:
        json.dump({"edges": res["edges"], "stale": res["stale"], "dual": res["dual"],
                   "value": res["value"], "cmds": res["cmds"], "traps": res["traps"],
                   "cjk": res["cjk"], "graph": res["graph"],
                   "playbook": res["playbook"],
                   "fails": _fails(res),
                   "self_sha12": res["self_sha12"], "values_sha12": res["values_sha12"],
                   "criterion_version": res["criterion_version"]},
                  sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        _print(res)
    bad = _fails(res)
    if bad:
        # ★ `--json` 是**机器接口**，stdout 必须是**纯 JSON** —— 这条提示改走 stderr。
        #   实测（2026-09-24）：原来它跟着 JSON 一起打到 stdout，于是
        #   **只有红的时候** `json.loads(stdout)` 才会抛异常 —— 「解析失败」与
        #   「真有问题」撞在同一时刻，消费方（backend/checks、CI）只会报
        #   「输出不是合法 JSON」，真正的失败边一条也看不到。
        #   同族：trap-decoding-mojibake-eats-structure（量具被环境噎住，错长在被测对象身上）。
        (sys.stderr if as_json else sys.stdout).write(
            "\n退出码=1：%d 处待处理\n" % len(bad))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
