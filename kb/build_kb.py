# -*- coding: utf-8 -*-
"""把 `kb/src/*.md` ＋ `src/manifest.json` 打成一份 `kb/kb.json`。

产物是**知识图谱的装载格式**，供三处读同一份：`kb/ask.py`（CLI 联想查询）、
后台可视化、以及将来的数字孪生域。

## 一个事实一份写法

    md 的 H1      →  title / slug      （build_kb 推，manifest 不许写）
    manifest.json →  domain/standard/tags/alias/keys/recognition/related（手工）
    md 正文       →  content           （build_kb 抄）
    traps.json    →  traps ＋ 别名      （同规矩：源在 traps.json，产物只抄一份并记源指纹）
    playbook.json →  playbook ＋ 别名   （同上：源在 playbook.json，产物只抄 families）
    build_kb.py   →  self_sha12        （机械指纹）

★ **别名表只有本文件一处实现。** `ask.py` 只读 `kb.json`，不许自己去索引
  `playbook.json` —— 两个索引实现 = 一个判断两份写法，换一份说法必漂。

manifest 里写 title 就会有两处标题，改一处必漂 —— 所以那一条由本文件从 md 推。

## 为什么要有 --check

`kb.json` 是**产物**，`src/*.md` 是**源**。源改了产物不重建，读的人就拿旧尺子量
（本仓铁律：『这份数是旧尺子量的』和『这份数是对的』在屏幕上长得一模一样）。
`--check` 只读地重建一遍，跟盘上那份逐字段比 —— 不一致就报出**是哪一个 slug 的
哪一个字段**变了，不只说一句「不一样」。

★ 它同时盯着 `self_sha12`：本文件自己改了，旧产物也算陈旧。这是**故意的** ——
  判据换了，旧产物就是旧尺子量的。

## 用法（本仓不用 argparse，靠 sys.argv 手解析；不认 --help）

    python -u kb/build_kb.py              # 写 kb/kb.json
    python -u kb/build_kb.py --check      # 只读复核，不一致 → 退出码 1
    python -u kb/build_kb.py --selftest   # 自检：阳性对照必须能红
    python -u kb/build_kb.py --json       # 打到 stdout，不落盘
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

# 中文日志不设编码必糊字；★ 更要紧的是：Windows 管道 stdout 默认 GBK，
# 而本文件会打「↔」这类字符 ⇒ 打印时自己崩、退出码非 0，调用方读成「判据红了」。
# 见 kb/gate.py 同一段落，以及 backend/checks/kg_citation.py。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

KB = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(KB, "src")
OUT = os.path.join(KB, "kb.json")
TRAPS = os.path.join(KB, "traps.json")
PLAYBOOK = os.path.join(KB, "playbook.json")

#: 手写版本号。判据语义（字段集、比对口径、指纹规则）改了才 +1。
#: 跟 `_self_sha12()` 是**两个**：手写的会忘，机械的说不清语义，缺一个都有洞。
CRITERION_VERSION = 1

#: 本文件只认这几个开关。认不出的 `-` 开头一律硬错 ——
#: 本仓有「传 --help 被当成楼名、按默认全量执行」的实伤，所以宁可不认也不猜。
_FLAGS = ("--check", "--selftest", "--json")


def slug(title: str) -> str:
    t = re.sub(r"[^\w一-鿿]+", "-", title).strip("-").lower()
    return t or "untitled"


def title_of(text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    return "untitled"


def sha12(data: bytes) -> str:
    """指纹规则 —— **全仓一份**（与 `backend/state/roster.py:sha12` 同义）。"""
    return hashlib.sha256(data).hexdigest()[:12]


def _self_sha12() -> str:
    with open(os.path.abspath(__file__), "rb") as fh:
        return sha12(fh.read())


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _hand_meta(path: str) -> dict:
    """源手册**自己声明的**判据版本 ＋ 它有哪些顶层键（供算「没进产物的键」）。

    ★ 为什么必须把版本带进产物（2026-09-24 发现，当时手册刚从 4 个家族扩到 12）：
      本仓 `criterion_version` 这个名字有**三个**出处 —— 本文件（打包器，
      `CRITERION_VERSION`=1）、`playbook.json`（手册语义）、`traps.json`（陷阱语义）。
      而 kb.json 过去**只带了打包器那一个** ⇒ `ask.py:ruler()` 每次都报
      `criterion_version: 1`：手册语义 3→4 改了，这个数**一动不动**，
      于是它答不了「这份数是哪把尺子量的」（铁律 24）。
      手写的那半（会忘、但能说清语义）恰好被丢掉，只剩机械 sha12 —— 两个都要。
      ⇒ 版本号按**源**带出来，`ruler()` 分开报、名字里点明属于谁。

    `keys` 是另一回事，别混为一谈：它只查**键**有没有进产物，而上面这个缺陷
    **恰好不会被它抓到** —— `criterion_version` 这个键在，装的是**另一个**制品的那份值。
    「键在」不等于「值在」（铁律 18 同族）。它防的是**将来**：源里新加一个键
    （`deprecated` 之类）时不许无声消失。
    """
    if not os.path.exists(path):
        return {"present": False, "criterion_version": None, "keys": []}
    full = json.loads(_read_text(path))
    return {"present": True, "criterion_version": full.get("criterion_version"),
            "keys": sorted(full)}


def build(src_dir: str | None = None,
          manifest_obj: dict | None = None,
          text_overrides: dict | None = None,
          self_sha: str | None = None,
          traps_obj: dict | None = None,
          traps_sha: str | None = None,
          playbook_obj: dict | None = None,
          playbook_sha: str | None = None) -> dict:
    """装出一份 payload。**不落盘** —— 落盘是 main 的事，这样 --check/--selftest 全程只读。

    text_overrides: {文件名: 正文}，供自检注入「改坏」的源，不碰磁盘。
    traps_obj/traps_sha: 同上，供自检注入「改坏」的陷阱表。
    playbook_obj/playbook_sha: 同上，供自检注入「改坏」的实战手册（families 映射）。
    """
    src = src_dir or SRC
    overrides = text_overrides or {}
    man = manifest_obj if manifest_obj is not None else json.loads(
        _read_text(os.path.join(src, "manifest.json")))

    entries: dict[str, dict] = {}
    order: list[str] = []
    sources: dict[str, str] = {}
    for fname in man["order"]:
        path = os.path.join(src, fname)
        if fname in overrides:
            text = overrides[fname]
        elif os.path.exists(path):
            text = _read_text(path)
        else:
            # 不静默跳过：manifest 点了名而盘上没有，是**漂**，要报出来。
            raise FileNotFoundError("manifest.order 点了 %s，但 %s 下没有它" % (fname, src))
        title = title_of(text)
        s = slug(title)
        if s in entries:
            raise ValueError("slug 撞车：%s 与 %s 都推成 %r" % (entries[s]["file"], fname, s))
        hand = man.get("entries", {}).get(fname)
        if hand is None:
            # 新加了 md 却忘了登记 ⇒ 报出来，不塞一个空条目（空条目会被读成「这篇没内容」）。
            raise KeyError("%s 在 manifest.entries 里没有登记" % fname)
        row = {"slug": s, "title": title, "file": fname}
        row.update({k: v for k, v in hand.items()})
        row["content"] = text
        entries[s] = row
        order.append(s)
        sources[fname] = sha12(text.encode("utf-8"))

    # 陷阱表：与 md 同规矩 —— **源在 traps.json，产物只抄一份**，并记源指纹。
    # ★ 两份写法会不会漂？会。但方式与 md 完全一样：源改了不重建，`--check` 就红
    #   （比对 `sources["traps.json"]`），门禁 ⑥ 那边另盯着这同一份文件的内容指纹。
    #   不额外造「比对两份副本」的判据 —— 那是同源比同源，恒绿（`trap-two-sources-agree-can-both-be-wrong`）。
    traps: dict = {}
    if traps_obj is not None:
        traps = traps_obj
        sources["traps.json"] = traps_sha if traps_sha is not None else ""
    elif os.path.exists(TRAPS):
        traps = (json.loads(_read_text(TRAPS)).get("traps") or {})
        sources["traps.json"] = sha12(_read_bytes(TRAPS))

    # 实战手册：**源在 playbook.json，产物只抄 `families`**（`_note` 留在源文件里）。
    families: dict = {}
    if playbook_obj is not None:
        families = playbook_obj
        sources["playbook.json"] = playbook_sha if playbook_sha is not None else ""
    elif os.path.exists(PLAYBOOK):
        families = (json.loads(_read_text(PLAYBOOK)).get("families") or {})
        sources["playbook.json"] = sha12(_read_bytes(PLAYBOOK))

    pmeta = _hand_meta(PLAYBOOK)
    tmeta = _hand_meta(TRAPS)
    payload = {
        "title": man["title"],
        "description": man["description"],
        "version": man["version"],
        "criterion_version": CRITERION_VERSION,
        # ★ 上面那个是**打包器**的版本；这两个是**源手册自己**声明的（见 _hand_meta）。
        #   三个都报，因为「哪把尺子量的」这件事，三个制品各有一份答案。
        "playbook_criterion_version": pmeta["criterion_version"],
        "traps_criterion_version": tmeta["criterion_version"],
        "self_sha12": self_sha if self_sha is not None else _self_sha12(),
        "manifest_sha12": sha12(json.dumps(man, ensure_ascii=False, sort_keys=True).encode("utf-8")),
        "sources": sources,
        "order": order,
        "entries": entries,
        "traps": traps,
        "playbook": families,
        "index": _index(entries, traps, families),
    }
    # 声明损失：源手册里**没进产物**的顶层键，逐文件列出来。
    # ★ 打包是**有损**的，而有损过去**无声**（`_note` / `_schema` 被丢掉，屏幕上看不出）。
    #   现在「丢了什么」由 源 ＋ 产物 机械算出来 ⇒ 源里一加键，`--check` 就指名报出来，
    #   逼人回答一次「这个键该不该进图」，而不是让它在传递途中蒸发。
    carried = set(payload)
    payload["dropped_keys"] = {
        f: sorted(k for k in m["keys"] if k not in carried)
        for f, m in (("playbook.json", pmeta), ("traps.json", tmeta))}
    return payload


def _index(entries: dict, traps: dict | None = None,
           families: dict | None = None) -> dict:
    """★神经网络的地基：给一个词，要知道该点亮哪些节点。

    `alias` 是**唯一的入口**：一个概念的所有叫法都收在这里。缺了别名，用户换个
    说法就查不到 —— 而「查不到」和「没有这个知识」在屏幕上一模一样，于是人只好回去猜。
    所以别名表必须比术语表宽：术语、俗称、错写、英文缩写都要收。

    **陷阱也进这张表**，节点名 `trap:<slug>`：陷阱是一等公民，换个说法也得查得到
    （「假红」「饱和」「没量成」……）。同一个词可以同时点亮条目和陷阱 ——
    那正是我们要的：一个说法往往既指向知识、又指向学它的那个坑。

    邻接（out/in）等 K1 有边了再出 —— 现在不占位：空邻接表会被读成「没有边」。

    ★ 迭代**必须 sorted**，不许直接遍历 `set`（2026-09-24 实测抓到）：
      直接 `for t in set(...)` 时，键的**插入顺序**随进程的哈希种子变 ——
      同一份源连build三次得到三个不同的 sha12（内容逐键相同，只有键序不同）。
      后果不是「难看」，是**指纹失效**：`sources`/`generated_from` 里 kb.json 的 sha12
      每次都变 ⇒ 下游（derive 腿②、门禁⑥）的「内容变了」再也分不清
      「源真的改了」还是「只是重建了一次」——判据被噪声喂到没人看（同族：
      memory `append-only-ledger-whole-table-assertion`）。
      ⇒ 这里是**唯一**的地方：词的顺序由 sorted 定，与哈希种子无关。
    """
    alias: dict[str, list[str]] = {}

    def light(term: str, node: str) -> None:
        if not term:
            return
        alias.setdefault(term, [])
        if node not in alias[term]:
            alias[term].append(node)

    for s, row in entries.items():
        for t in sorted(set(row.get("alias") or []) | {row["title"], s}):
            light(t, s)
    for tslug, trap in (traps or {}).items():
        node = "trap:" + tslug
        terms = set(trap.get("alias") or []) | {trap.get("title") or "", tslug}
        for term in sorted(terms):
            light(term, node)
    # 实战手册（playbook）同样进表，节点名 `pb:<slug>`：
    # ★ **症状的说法、根因的说法、处置的说法都当别名** —— 智能体手里往往只有其中一句
    #   （用户说「上面那层多出来一块」，处理的人说「重算 offset」），都得能点亮同一个家族。
    for fslug, fam in (families or {}).items():
        node = "pb:" + fslug
        terms = set(fam.get("alias") or []) | {fam.get("title") or "", fslug}
        for key in ("symptoms", "causes", "fixes"):
            for item in (fam.get(key) or []):
                if isinstance(item, dict) and item.get("what"):
                    terms.add(item["what"])
        for term in sorted(terms):
            light(term, node)
    return {"alias": alias}


def _diff(old: dict, new: dict) -> list[str]:
    """逐字段报出漂在哪 —— 只说「不一样」等于没说。"""
    out: list[str] = []
    for k in ("title", "description", "version", "criterion_version",
              "playbook_criterion_version", "traps_criterion_version", "dropped_keys",
              "self_sha12",
              "manifest_sha12", "sources", "order", "traps", "playbook", "index"):
        if old.get(k) != new.get(k):
            if k in ("self_sha12", "manifest_sha12", "sources"):
                out.append("%s 变了（源码/清单/尺子动过）" % k)
            elif k == "playbook":
                ov, nv = old.get("playbook") or {}, new.get("playbook") or {}
                gone = sorted(set(ov) - set(nv))
                add = sorted(set(nv) - set(ov))
                chg = sorted(s for s in set(ov) & set(nv) if ov[s] != nv[s])
                out.append("playbook 变了（少了 %s；多了 %s；改了 %s）"
                           % (gone or "无", add or "无", chg or "无"))
            elif k == "traps":
                ov, nv = old.get("traps") or {}, new.get("traps") or {}
                gone = sorted(set(ov) - set(nv))
                add = sorted(set(nv) - set(ov))
                chg = sorted(s for s in set(ov) & set(nv) if ov[s] != nv[s])
                out.append("traps 变了（少了 %s；多了 %s；改了 %s）"
                           % (gone or "无", add or "无", chg or "无"))
            elif k == "index":
                out.append("index 变了（别名表 ≠ 条目＋陷阱的别名）")
            else:
                out.append("%s: %r → %r" % (k, old.get(k), new.get(k)))
    oe, ne = old.get("entries") or {}, new.get("entries") or {}
    for s in sorted(set(oe) | set(ne)):
        if s not in oe:
            out.append("新增条目 %s" % s)
        elif s not in ne:
            out.append("条目没了 %s" % s)
        elif oe[s] != ne[s]:
            fields = [k for k in set(oe[s]) | set(ne[s]) if oe[s].get(k) != ne[s].get(k)]
            out.append("条目 %s 的字段变了：%s" % (s, ", ".join(sorted(fields))))
    return out


def write(payload: dict) -> None:
    """原子写：直写会截成 0 字节（memory: atomic-artifact-write）。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, OUT)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def check() -> int:
    if not os.path.exists(OUT):
        print("--check 红：产物 %s 不在。先跑 python -u kb/build_kb.py" % OUT)
        return 1
    old = json.loads(_read_text(OUT))
    new = build()
    drift = _diff(old, new)
    if drift:
        print("--check 红：产物与源不一致（%d 处）" % len(drift))
        for d in drift:
            print("   · " + d)
        print("   ⇒ 跑 python -u kb/build_kb.py 重建")
        return 1
    print("--check 绿：%d 篇 ＋ %d 条陷阱 ＋ %d 个家族 与源一致（criterion_version=%d, self=%s）"
          % (len(new["entries"]), len(new.get("traps") or {}),
             len(new.get("playbook") or {}),
             new["criterion_version"], new["self_sha12"]))
    return 0


def selftest() -> int:
    """九条刑具（T0–T9），**每条都要能红**。只验「干净时是绿的」等于没验。

    ★ 判据全绿先自问「它是不是在全部样本上都取极值」—— 所以这里每条都**故意造坏**，
      并要求它**在那一处**报出来。
    """
    base = build()
    fails: list[str] = []

    if _diff(base, base):
        fails.append("T0 自身比对不为空 —— 比对函数坏了")

    # T1 改源：正文改一个字
    t1 = build(text_overrides={"01-line-types.md": _read_text(os.path.join(SRC, "01-line-types.md")) + "\n改坏。\n"})
    d1 = _diff(base, t1)
    if not any("sources" in x for x in d1):
        fails.append("T1 改源正文 ⇒ 没报 sources 变化（此判据恒绿）")
    if not any("条目" in x for x in d1):
        fails.append("T1 改源正文 ⇒ 没报条目内容变化")

    # T2 改 manifest：把一个 key 的说法换掉
    man = json.loads(_read_text(os.path.join(SRC, "manifest.json")))
    man2 = json.loads(json.dumps(man, ensure_ascii=False))
    man2["entries"]["01-line-types.md"]["keys"] = ["被改坏的一条"]
    t2 = build(manifest_obj=man2)
    if not any("条目" in x for x in _diff(base, t2)):
        fails.append("T2 改 manifest ⇒ 没报条目变化（此判据恒绿）")

    # T3 改尺子：build_kb.py 自己的指纹变了 ⇒ 旧产物算陈旧
    t3 = build(self_sha="000000000000")
    if not any("self_sha12" in x for x in _diff(base, t3)):
        fails.append("T3 改本文件 ⇒ 没报尺子变了（此判据恒绿）")

    # T4 删一篇的登记 ⇒ 必须硬报，不许静默跳过
    man3 = json.loads(json.dumps(man, ensure_ascii=False))
    man3["entries"].pop("04-stair.md")
    try:
        build(manifest_obj=man3)
        fails.append("T4 漏登记一篇 ⇒ 没报错（会静默出空条目）")
    except KeyError:
        pass

    # T5 改陷阱表 ⇒ 必须报，且**点名少了哪一条**（只说「不一样」等于没说）
    t5 = build(traps_obj={"trap-x": {"title": "注入的陷阱", "alias": ["注入别名甲"],
                                     "cases": [{"where": "kb/gate.py:readonly_ok",
                                                "what": "对照"}]}},
               traps_sha="000000000000")
    d5 = _diff(base, t5)
    if not any("traps 变了" in x for x in d5):
        fails.append("T5 改陷阱表 ⇒ 没报 traps 变化（此判据恒绿）")
    if not any("少了" in x for x in d5):
        fails.append("T5 改陷阱表 ⇒ 没点名少了哪几条")
    # 别名索引必须真的把陷阱收进去：词 → trap:<slug>
    got = (t5["index"]["alias"].get("注入别名甲") or [])
    if got != ["trap:trap-x"]:
        fails.append("T5 陷阱别名没进索引：查到 %r（应为 ['trap:trap-x']）" % (got,))
    if not [k for k, v in base["index"]["alias"].items()
            if any(str(x).startswith("trap:") for x in v)]:
        fails.append("T5 现表里没有一个别名点亮陷阱节点 —— 陷阱没进索引")

    # T6 改实战手册 ⇒ 必须报，且**点名少了哪个家族**；症状/根因/处置的说法都要能点亮家族节点
    t6 = build(playbook_obj={"families-zh": {
        "title": "注入的家族", "alias": ["注入家族别名"],
        "symptoms": [{"what": "注入的症状", "evidence": "kb/README.md:146"}],
        "causes": [{"what": "注入的根因", "evidence": "kb/README.md:146"}],
        "fixes": [{"what": "注入的处置", "evidence": "kb/README.md:146"}]}},
        playbook_sha="000000000000")
    d6 = _diff(base, t6)
    if not any("playbook 变了" in x for x in d6):
        fails.append("T6 改手册 ⇒ 没报 playbook 变化（此判据恒绿）")
    if not any("少了" in x for x in d6):
        fails.append("T6 改手册 ⇒ 没点名少了哪些家族")
    for term in ("注入家族别名", "注入的症状", "注入的根因", "注入的处置"):
        got = (t6["index"]["alias"].get(term) or [])
        if got != ["pb:families-zh"]:
            fails.append("T6 手册说法没进索引：%r → %r（应为 ['pb:families-zh']）" % (term, got))
    if base.get("playbook") and not [1 for v in base["index"]["alias"].values()
                                     if any(str(x).startswith("pb:") for x in v)]:
        fails.append("T6 现表里没有别名点亮手册节点 —— 手册没进索引")

    # T7 源手册**自己声明的**判据版本必须真的带出来，且一改就点名报出。
    #    ★ 前半（真的带出来）是这条刑具最要紧的一半：只验「改了会报」的话，
    #      字段恒为 None 时 `_diff` 照样报「None → 5」，刑具是绿的而病还在（铁律 26）。
    pb_declared = json.loads(_read_text(PLAYBOOK)).get("criterion_version")
    if base.get("playbook_criterion_version") != pb_declared:
        fails.append("T7 产物里 playbook_criterion_version=%r，源手册声明的是 %r —— 没真的带出来"
                     % (base.get("playbook_criterion_version"), pb_declared))
    if pb_declared is None:
        fails.append("T7 源手册没写 criterion_version —— 手写的那半指纹不存在")
    tr_declared = json.loads(_read_text(TRAPS)).get("criterion_version")
    if base.get("traps_criterion_version") != tr_declared:
        fails.append("T7 产物里 traps_criterion_version=%r，源陷阱表声明的是 %r"
                     % (base.get("traps_criterion_version"), tr_declared))
    t7 = dict(base, playbook_criterion_version=(pb_declared or 0) + 1)
    if not any("playbook_criterion_version" in x for x in _diff(base, t7)):
        fails.append("T7 手册语义版本变了（3→4 这种）⇒ 没指名报出（此判据恒绿）")

    # T8 打包**有损**时不许无声：丢掉哪些键要由 源＋产物 算出来，且这一栏一改就点名报出。
    #    断言的是**实物**（`_note` 确实丢了、`traps` 确实没丢），不是拿同一个公式再算一遍 ——
    #    那会是同源比同源、恒绿（trap-two-sources-agree-can-both-be-wrong）。
    dk = base.get("dropped_keys") or {}
    if set(dk) != {"playbook.json", "traps.json"}:
        fails.append("T8 dropped_keys 没逐文件列出：%r" % sorted(dk))
    else:
        if "_note" not in (dk.get("traps.json") or []):
            fails.append("T8 traps.json 的 `_note` 明明没进产物，却没被列进 dropped_keys：%r"
                         % dk.get("traps.json"))
        if "traps" in (dk.get("traps.json") or []):
            fails.append("T8 `traps` 是进了产物的，却被列成丢弃：%r" % dk.get("traps.json"))
    t8 = dict(base, dropped_keys=dict(dk, **{
        "playbook.json": sorted(set(dk.get("playbook.json") or []) | {"deprecated"})}))
    if not any("dropped_keys" in x for x in _diff(base, t8)):
        fails.append("T8 有损清单变了 ⇒ 没报（此判据恒绿）")

    # T9 产物必须**逐字节可复现**（换一个进程、换一个哈希种子，字节必须一样）。
    #    ★ 来由：2026-09-24 实测，`_index` 直接遍历 `set` ⇒ 连build三次三个 sha12
    #      （内容逐键相同、只有键序不同）。指纹一旦每次重建都变，下游「内容变了」
    #      就分不清「源改了」还是「只是重建」，判据被噪声喂死。
    #    ★ 在**本进程内**比两次是没用的（同一个哈希种子，恒绿）⇒ 必须起子进程。
    #    ★ 同时配阴性对照：两个种子的 `hash()` 必须**不同** —— 若哪天哈希不再随机，
    #      上面那条比较就成了恒绿的摆设，这条对照会红着把它指出来（铁律 23(b)）。
    def _child(seed: str, expr: str) -> bytes:
        env2 = dict(os.environ, PYTHONHASHSEED=seed)
        return subprocess.run([sys.executable, "-u", "-c", expr],
                              cwd=os.path.dirname(os.path.abspath(__file__)),
                              env=env2, capture_output=True).stdout

    q = 'import io,json,sys;sys.path.insert(0,".");import build_kb;' \
        'sys.stdout.buffer.write(json.dumps(build_kb.build(), ensure_ascii=False,' \
        'indent=1).encode("utf-8"))'
    b0, b1 = _child("0", q), _child("1", q)
    if not b0 or not b1:
        fails.append("T9 子进程没产出内容（判据量不到目标 —— 不许当绿）")
    elif b0 != b1:
        fails.append("T9 同一份源、换哈希种子 ⇒ 产物字节不同（%d vs %d 字节）—— "
                     "产物不可复现，凡以它的 sha12 为指纹的判据都会随重建乱红"
                     % (len(b0), len(b1)))
    h0 = _child("0", "print(hash('资产图'))")
    h1 = _child("1", "print(hash('资产图'))")
    if h0 and h0 == h1:
        fails.append("T9 阴性对照：两个哈希种子下 hash() 相同 ⇒ 哈希没有被随机化，"
                     "上面那条比较是恒绿的摆设（判据失效却不报）")

    if fails:
        print("--selftest 红：%d 条刑具没通过" % len(fails))
        for f in fails:
            print("   · " + f)
        return 1
    n_trap = len(base.get("traps") or {})
    n_light = len([1 for v in base["index"]["alias"].values()
                   if any(str(x).startswith("trap:") for x in v)])
    n_fam = len(base.get("playbook") or {})
    n_pb = len([1 for v in base["index"]["alias"].values()
                if any(str(x).startswith("pb:") for x in v)])
    # ★ 手册还没建时**必须写出来**，不许让「0 家族」看起来像合格（`UNAVAILABLE` ≠ `PASS`）。
    fam_note = ("%d 个家族（%d 个别名能点亮手册节点）" % (n_fam, n_pb) if n_fam
                else "**未登记**（0 个家族）—— 症状→根因→处置 这条链一次都没查过")
    print("--selftest 绿：9 条刑具全部能红（含 T0/T9 阴性对照）；%d 篇，%d 个别名，"
          "%d 条陷阱（%d 个别名能点亮陷阱节点），手册 %s（手册语义 v%s／陷阱语义 v%s）"
          % (len(base["entries"]), len(base["index"]["alias"]), n_trap, n_light, fam_note,
             base.get("playbook_criterion_version"), base.get("traps_criterion_version")))
    return 0


def main(argv: list[str]) -> int:
    for a in argv:
        if a.startswith("-") and a not in _FLAGS:
            print("不认得的开关 %r；只支持 %s" % (a, " ".join(_FLAGS)))
            return 2
    if "--selftest" in argv:
        return selftest()
    if "--check" in argv:
        return check()
    if "--json" in argv:
        json.dump(build(), sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 0
    payload = build()
    write(payload)
    print("已写 %s：%d 篇，%d 字符，%d 别名，%d 条陷阱，%d 个家族（criterion_version=%d, self=%s）"
          % (OUT, len(payload["entries"]),
             sum(len(e["content"]) for e in payload["entries"].values()),
             len(payload["index"]["alias"]), len(payload.get("traps") or {}),
             len(payload.get("playbook") or {}),
             payload["criterion_version"], payload["self_sha12"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
