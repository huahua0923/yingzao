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
    python -u kb/gate.py --selftest      # 十一条刑具，每条都要能红
    python -u kb/gate.py --record        # 记下证据文件的内容指纹（kb/evidence-lock.json）
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
CRITERION_VERSION = 2

_FLAGS = ("--selftest", "--record", "--anchors", "--json")

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

def collect_edges(payload: dict | None = None) -> list[dict]:
    """图谱里所有**可复核的边**：每条带 `src`（谁在宣称）＋ `evidence`（据什么）。

    两个来源：`kb.json` 的识别映射边、`kb/traps.json` 的陷阱实物证据。
    两处的 `evidence` 走**同一套**复核（路径/行号/符号），不放宽 ——
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
    edges.extend(collect_trap_edges()[0])
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


def collect_trap_edges() -> tuple[list[dict], list[dict]]:
    """返回 `(可核的陷阱证据边, 无锚点的陷阱)`。

    ★ 第二个返回值不是装饰：**「只有人记着」本身就是信息**。
      一条陷阱没有仓内锚点 ⇒ 它不可复核、会随人走。把它静默丢掉，
      输出就会说「12 条陷阱全部有据」；数出来才叫诚实
      （`UNAVAILABLE ≠ PASS` 的同一条道理）。
    """
    if not os.path.exists(TRAPS):
        return [], []
    d = json.loads(io.open(TRAPS, encoding="utf-8").read())
    edges: list[dict] = []
    bare: list[dict] = []
    for slug, t in (d.get("traps") or {}).items():
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
# ★ 分母必须写出来：**只量 `kb/` 内的自有文件**。仓内其他文件一次都没量过 ——
#   「没量过」和「干净」在屏幕上必须不是同一行字（与 ①②③ 的 N/A 同理）。

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
                out.append({"line": i, "col": j + 1, "text": line.strip()[:96]})
    return out


def _kb_sources(suffix: str) -> list[str]:
    """`kb/` 下所有该后缀的文件（相对 ROOT 的 posix 路径）。"""
    return sorted(os.path.relpath(p, ROOT).replace(os.sep, "/")
                  for p in glob.glob(os.path.join(KB, "**", "*" + suffix), recursive=True)
                  if os.path.isfile(p))


def check_cjk_quotes() -> dict:
    """⑪：ASCII 引号被当中文引号用 ⇒ 红。三档的分工见上面那段注释。"""
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
    n = len(mds) + len(pys) + len(jss)
    return {"status": "gap" if (hits or bad_json) else "pass",
            "checked": n, "md": len(mds), "py": len(pys), "json": len(jss),
            "hits": hits, "bad_json": bad_json,
            "detail": "%d 个文件（md %d 宽档 / py %d 严档 / json %d 只判能解析）；命中 %d 处"
                      % (n, len(mds), len(pys), len(jss), len(hits) + len(bad_json))}


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
    for name, path in (("kb/traps.json", TRAPS), ("kb/playbook.json", PLAYBOOK)):
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
        ok, why = readonly_ok(c["cmd"])
        if ok and not (c.get("writes") or "").strip():
            # ★ 「只读」不许是空话：白名单是按前缀放的，而这些盘上脚本**会写报告**。
            #   没写 `writes` 的条目 = 副作用没人知道 ⇒ 拒登（不是警告）。
            ok, why = False, "没写 writes —— 判据命令的写盘副作用必须写明"
        cmd_rows.append((c["cmd"], ok, why, c.get("src") or ""))
    _te, bare = collect_trap_edges()
    cjk = check_cjk_quotes()
    pb_edges, pb_bare, pb_declared = collect_playbook_edges(payload)
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
            "cmds": cmd_rows, "edge_files": files, "cjk": cjk,
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
    print("⑪ ASCII 引号当中文引号：%s（量过 %d 个文件：md %d 宽档 / py %d 严档 / json %d 只判能解析）"
          % (_LABEL[cq["status"]], cq["checked"], cq["md"], cq["py"], cq["json"]))
    print("     （★ 只量 kb/ 内的自有文件；**仓内其他文件一次都没量过** —— 不是「干净」）")
    for h in cq["hits"]:
        print("     ✗ %s:%d col%d [%s档] %s" % (h["file"], h["line"], h["col"], h["band"], h["text"]))
    for b in cq["bad_json"]:
        print("     ✗ JSON 解析不了：%s" % b)

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


# ── 自检：十一条刑具，每条都要能红 ──────────────────────────

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
    print("--selftest 绿：**11 条**刑具全部能红（①路径 ②行号 ③符号+注释不算 ④接上 ⑤非空转 "
          "⑥改一字节即红+无表即说量不了 ⑦写操作被拒/只读放行 ⑧陷阱分两栏 ⑨手册三栏 "
          "⑩re-baseline 差异报告只报真变动的文件、且打出锚点此刻指到的内容 "
          "⑪引号两档各自能红+掩码生效+分母非零"
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
    if not os.path.exists(KBJSON):
        say.write("红：%s 不在。先跑 python -u kb/build_kb.py\n" % KBJSON)
        return 1
    res = run()
    as_json = "--json" in argv
    if as_json:
        json.dump({"edges": res["edges"], "stale": res["stale"], "dual": res["dual"],
                   "value": res["value"], "cmds": res["cmds"], "traps": res["traps"],
                   "cjk": res["cjk"],
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
