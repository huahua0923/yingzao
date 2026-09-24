# -*- coding: utf-8 -*-
"""kb/ask.py —— 图谱的**唯一**查询入口：给一个说法，扩散激活出整条链。

设计约束（与 kb/README.md「智能体流程」一节同源）：

  · **只读 kb.json。** 别名表只有 build_kb.py 一处实现；本文件绝不自己去索引
    playbook.json / traps.json —— 两个索引实现 = 一个判断两份写法，换一份说法必漂。
  · **三态必须分开**：hit / unverified / miss。`miss` 绝不回空数组 ——
    「图里没有」和「没问题」在屏幕上一模一样，而智能体会把空数组读成「没这回事」。
  · **命令只从图里来**：`--run` 只跑 kb.json 里登记过、且已过 kb/gate.py ⑦
    只读白名单的命令。不提供任何「把命令当参数传进来」的口子。
  · **判据结果留痕**：跑过的命令把 (命令, 退出码, 关键输出, 时刻, **尺子指纹**) 落
    data/_meta/kg_runs.json。没有尺子指纹，下次读到的数就分不清是哪把尺子量的。
  · **查不到的症状不许丢**：`--pending` 把它记进 kb/pending.json（谁/何时/什么症状/
    最像哪一条），把「下次还得猜一遍」变成「排队等人收」。
    ★ 生产队列只收**有人真报上来的**记录：`who` 里带「验收/自检/模拟/测试」的会被
    `append_pending` 直接拒（退出码 2）—— 那是**代码事实**，不是一句约定。
      验收要问「会不会被接受」，用 `--dry-run`：**一个字节都不写**，只回 0（接受）/ 2（拒）。

用法（本仓不认 --help：脚本靠 sys.argv 手解析，--help 会被静默当成查询词）：

  python -u kb/ask.py "楼层错位"            # 人看的排版
  python -u kb/ask.py "楼层错位" --json     # ★主接口：机器可执行的结构
  python -u kb/ask.py "楼层错位" --run      # 真跑图里登记的只读判据
  python -u kb/ask.py "c057 楼层错位"        # 带楼名 ⇒ 只挑与该楼有关的实例
  python -u kb/ask.py --list                # 已知症状 / 陷阱 / 知识条目
  python -u kb/ask.py "洞中洞" --pending --who 智能体A
  python -u kb/ask.py "洞中洞" --pending --dry-run   # 只问会不会被接受，不写盘
  python -u kb/ask.py --selftest            # 自检：阳性/阴性对照都要能红
"""
import io
import json
import os
import re
import shlex
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):          # 中文日志不设编码必糊字
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KB_DIR)
KB_JSON = os.path.join(KB_DIR, "kb.json")
#: 未收录症状的**追加**队列。★ `GYM3D_KB_PENDING` 只为**验收/自检**改道用，不是配置项：
#: 验收跑一遍就会往里塞几条模拟记录，而队列是「等人来收」的生产件 ——
#: 混进去之后，人分不清哪条是真有人报过的（实测：我自己跑 K2/K5 验收就塞了 4 条，
#: `who` 写着「智能体A/B」，看着跟真的上报一模一样）。
#: 默认值仍是那份生产文件，所以不设这个变量的日常用法一个字都没变。
#: 生产队列的**固定**路径。★ 守卫必须比它，**不许比 `PENDING`** ——
#: `PENDING` 会被 `GYM3D_KB_PENDING` 改道，改道之后 `PENDING` **就是**那个临时文件；
#: 拿「path == PENDING」当「这是生产队列」，等于「一改道，任何目标都成了生产队列」，
#: 于是验收永远写不进去 —— 而屏幕上那句拒词还会说「临时文件是等人来收的生产件」。
#: 实测：第一版就是这么写的，且自检那一格是**绿的**（它拿 tmp≠PENDING 验，验的是
#: 「不相等就放行」，与改道无关 ⇒ 空断言，bug 从它底下过去了）。
PROD_PENDING = os.path.join(KB_DIR, "pending.json")
PENDING = (os.environ.get("GYM3D_KB_PENDING") or PROD_PENDING)
#: `who` 里出现这些词 ⇒ 这条是**验收/自检**记录，不是有人报上来的症状。
#: ★ 上面那段注释原来说的是「请把 GYM3D_KB_PENDING 指到临时文件」—— 那是**一句约定**；
#: 而约定会被忘掉（实测就是忘掉的那一次）。本仓 gate ⑦ 自己的原话：
#: 「白名单是**代码事实**，不是注释里的君子协定」。所以这里落成判据。
SIM_WHO_MARKERS = ("验收", "自检", "模拟", "测试", "selftest", "fixture")
INSTANCES = os.path.join(ROOT, "data", "_meta", "kg_instances.json")
LEDGER = os.path.join(ROOT, "data", "_meta", "kg_runs.json")
GATE_PY = os.path.join(KB_DIR, "gate.py")

#: ★只读白名单**全仓只有一份**（`kb/gate.py:_READONLY_PREFIX`），这里**引它，不重抄**。
#:   原先本文件自己列了三个前缀的元组 —— 那就是同一判断的第二份实现，而两份只在
#:   「我改了一份、忘了另一份」时**当场分歧**：实测 2026-09-24，给 `scan_defects.py`
#:   那族唯一能逐条给实例的判据开了闸（gate ⑦ 放行），`--selftest` 的 T6 立刻红 ——
#:   拦得对，但它是靠「有人刚好跑了自检」才被发现的。改成导入之后，分歧在结构上不可能发生。
sys.path.insert(0, KB_DIR)
try:
    from gate import _READONLY_PREFIX as READONLY_PREFIX
except ImportError as _ex:                      # pragma: no cover - 只在文件被搬走时发生
    raise SystemExit("kb/ask.py 依赖同目录的 gate.py 取只读白名单，导入失败：%s" % _ex)

FLAGS = ("--json", "--list", "--run", "--pending", "--selftest", "--who", "--top",
         "--dry-run")
BUILDING_RE = re.compile(r"^[a-z]\d{3}[a-z]?\d*$")
SPLIT_RE = re.compile(r"[\s,，;；:：/、()（）\[\]【】]+")
RUN_TIMEOUT = 600

# 三个分支的优先次序 —— **只在权重相同时才用到**（次序保持原样：家族 → 陷阱 → 条目）。
BRANCH_RANK = {"family": 2, "trap": 1, "entry": 0}


def _branch_of(node):
    """节点 id → 它属于哪一支。**全文件只有这一处**做这个判断。

    索引里实测只有三种节点 id：`pb:<家族>` / `trap:<slug>` / 无前缀（条目 id）。
    判断写成一处，是为了让「按权重挑主命中」与「activated 怎么排」不可能各说各话。
    """
    if node.startswith("pb:"):
        return "family"
    if node.startswith("trap:"):
        return "trap"
    return "entry"



def sha12(path):
    import hashlib
    with io.open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:12]


def load_kb(path=KB_JSON):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


#: 带值的开关 —— 它们的**下一个 argv 是值，不是查询词**。
#: ★ 加新开关时**必须**同步加到这里：漏一个，它的值就会被并进查询串。
VALUE_FLAGS = ("--top", "--who")


def query_words(args):
    """从 argv 里挑出**查询词**：跳过开关，也跳过开关的值。

    ★ 为什么不能只写 `[a for a in args if not a.startswith("-")]`：那样只跳过了开关
      本身，**它的值照样留在里面**。实测 2026-09-24（HTTP 端点接上来、要和 CLI 逐字段
      比对时才看见）：`--top 3` 的值漏进去 ⇒ `query` 变成「楼层错位 3」，
      命中理由从「整串精确命中」降级成「词命中」。
      它**照旧 hit、照旧出结果**，所以这个漏在 CLI 上一直没被看见 ——
      「精确度少了一档」和「对」在屏幕上是同一行字。

    ★ 按**位置**跳，不按值相等跳：原来 `--who` 那段用 `w != args[i+1]` 去过滤，
      查询词里恰好也有同一个字符串时会被一起删掉（`"3 层" --top 3` 会把查询里的
      `3` 也删了）。位置法没有这个歧义。
    """
    out, i = [], 0
    while i < len(args):
        if args[i] in VALUE_FLAGS:
            i += 2                      # 开关本身 ＋ 它的值，一起跳过
            continue
        if not args[i].startswith("-"):
            out.append(args[i])
        i += 1
    return out


def building_in(words, query):
    """从命令行里认出被点名的楼。★必须先按 token 分一次：`"c027 楼层错位"` 在 shell 里
    是**一个** argv（有引号），只在空格分词的 words 上跑正则 ⇒ 认不出楼名 ⇒
    `_narrow` 静默不生效 —— 而屏幕上看起来「查是查到了」，只是实例那栏没挑楼。
    这正是本仓最防的那一类：**判据没生效和判据生效了，长得一样**。"""
    for w in words:
        if BUILDING_RE.match(w):
            return w
    for t in tokens(query):
        if BUILDING_RE.match(t):
            return t
    return None


def load_instances(path=None):
    """★实例层是**机器派生**的产物（kb/derive.py 写）。它不存在时**不许回空** ——
    「没派过」和「这个家族一处也没观察到」在屏幕上一模一样，而这两句话的含义正相反。
    所以回一个显式 UNAVAILABLE，并写清怎么把它造出来。"""
    path = path or INSTANCES
    if not os.path.exists(path):
        return {"state": "UNAVAILABLE",
                "reason": "%s 不存在 —— 还没跑过 kb/derive.py。"
                          "★这不是「一处也没观察到」，是**没量过**" % path,
                "how": "python -u kb/derive.py && python -u kb/derive.py --check"}
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def derived_for(inst, fslug, building=None):
    """家族 → 楼栋·层的**实测实例**（两条轴分开列，因为它们是两把不同的尺子量的）。

    ★ 「识别侧」与「几何侧」是两个独立的量具：code 轴来自 `_qa/defects.json`（识别/台账），
    flag 轴来自 `_qa/defect_<楼>.json` 的逐层实测。**两边都命中的楼**才是互相印证的那一档，
    所以 `both` 单独列出来，不把两条轴合并成一个数（合并就再也分不清是几把尺子量的）。
    """
    if inst.get("state") == "UNAVAILABLE":
        return inst
    codes, flags = inst.get("codes") or {}, inst.get("flags") or {}
    axis = {"codes": {}, "flags": {}}
    for b, v in (inst.get("buildings") or {}).items():
        # ★ 这里**不许**按 `report` 跳过整栋。`report` 是**几何侧**（flag 轴）有没有实测，
        #   而 code 轴来自 `_qa/defects.json`，覆盖全库 95 栋 —— 两边是两把不同的尺子。
        #   原先 `if v.get("report") is not True: continue` 写在两轴之间，等于拿几何侧的门票
        #   去挡识别侧的数据：9 栋（c001/c003/c007/c021/c023/c110/c112/c113/m282）的 10 条
        #   家族命中**静默不进实例栏**，而屏幕上与「一处也没观察到」长得一样（铁律 16）。
        #   所以：code 轴只看有没有 code，flag 轴只看有没有 obs；缺几何侧的在下面单列出来。
        if building and b != building:
            continue
        for k, cell in (v.get("codes_by_floor") or {}).items():
            for c, n in cell.items():
                if (codes.get(c) or {}).get("family") != fslug:
                    continue
                per = axis["codes"].setdefault(b, {})
                per[k] = per.get(k, 0) + n
        for k, cell in (v.get("obs") or {}).items():
            for fl in cell.get("flags") or []:
                if (flags.get(fl) or {}).get("family") != fslug:
                    continue
                per = axis["flags"].setdefault(b, {})
                per[k] = per.get(k, 0) + 1
    tot = inst.get("totals") or {}
    # ★ 「只被识别侧看见」的楼要单列：它们不是「两边都命中」那一档，也**不是干净的** ——
    #   是**几何侧没量过**（UNAVAILABLE ≠ PASS）。不单列，屏幕上会和「两边都印证了」混成一栏。
    only_code = sorted(set(axis["codes"]) - set(axis["flags"]))
    bld = inst.get("buildings") or {}
    return {"state": "ok", "family": fslug,
            "by_code": axis["codes"], "by_flag": axis["flags"],
            "both": sorted(set(axis["codes"]) & set(axis["flags"])),
            "by_code_geometry_unmeasured": [b for b in only_code
                                            if (bld.get(b) or {}).get("report") is not True],
            "n_buildings": len(set(axis["codes"]) | set(axis["flags"])),
            "n_floor_pairs": sum(len(v) for v in axis["codes"].values())
                             + sum(len(v) for v in axis["flags"].values()),
            "axis_note": "by_code = 识别/台账侧（_qa/defects.json，覆盖全库 95 栋）；"
                         "by_flag = 几何侧逐层实测（_qa/defect_<楼>.json，49 栋）。"
                         "两把尺子；both 里的楼是两边都命中、互相印证的；"
                         "by_code_geometry_unmeasured 里的楼**只有识别侧看见** —— "
                         "几何侧没量过（「没量过」≠「合格」）",
            "ruler_of_instances": {
                "criterion_version": inst.get("criterion_version"),
                "derive_self_sha12": inst.get("self_sha12"),
                "src_sha": (inst.get("generated_from") or {}).get("src_sha"),
                "note": "★这些实例是哪把尺子量的：derive.py 自指纹 + 每个源的内容指纹。"
                        "实例是派生快照 ⇒ 源一改就得重跑 derive.py，"
                        "否则读到的是**旧尺子量的数**"},
            "totals_note": "全库 %s 栋里 %s 栋有机器产物；其余 %s 栋是 UNAVAILABLE"
                           "（**没量过**，不是「合格」）"
                           % (tot.get("buildings"), tot.get("with_report"),
                              tot.get("unavailable"))}


def ruler(kb):
    """本次查询所依据的尺子指纹。★手写的版本号会忘，机械的 sha12 说不清语义，两个都要。"""
    src = kb.get("sources") or {}
    return {
        # ★ 三个版本号各有其主，名字里点明，不要只报一个（2026-09-24 修）：
        #   过去这里只有 `criterion_version`，而它装的是 **kb.json（打包器）** 的版本 ——
        #   手册语义从 3 改到 4 时它一动不动，于是它答不了「这份数是哪把尺子量的」。
        #   手写的那半指纹恰好被丢掉，只剩机械 sha12（铁律 24 要两个都在）。
        "criterion_version": kb.get("criterion_version"),
        "criterion_version_means": "kb.json 打包器（kb/build_kb.py:CRITERION_VERSION）",
        "playbook_criterion_version": kb.get("playbook_criterion_version"),
        "traps_criterion_version": kb.get("traps_criterion_version"),
        "kb_self_sha12": kb.get("self_sha12"),
        "gate_sha12": sha12(GATE_PY) if os.path.exists(GATE_PY) else None,
        # ★ 手册指纹：账本要记的「跑哪条命令、该期待什么」是 playbook.json 定的，
        #   而它不在上面三项里（self_sha12 是**生成器** build_kb.py 的指纹）——
        #   改完手册再跑一轮，旧条目会看起来仍然现行（铁律 24：产物要自证是哪把尺子量的）。
        #   ★ 机械的说「变了」，`playbook_criterion_version` 说「哪里变了」——缺一个都有洞。
        "playbook_sha12": src.get("playbook.json")}


# ── 扩散激活 ────────────────────────────────────────────────

def tokens(query):
    return [t for t in SPLIT_RE.split((query or "").strip().lower()) if t]


def seeds_of(alias, query):
    """给一个说法 → 起始激活节点。三级：整串精确 / 整串子串 / 逐词。"""
    out = {}
    q = (query or "").strip().lower()
    if not q:
        return out

    def light(term, node, w, why):
        if w > out.get(node, {}).get("weight", 0):
            out[node] = {"weight": w, "why": why}

    if q in alias:
        for node in alias[q]:
            light(q, node, 1.0, "整串精确命中「%s」" % q)
    # ★子串那一档**两边都要求 ≥2 字**：单字别名（如「墙」）会把任何含它的说法都点亮。
    #   实测：「漏墙」在某家族别名被抽掉后，被单字「墙」带得 hit 到一篇无关文档。
    #   ★注意要卡的是**term** 的长度，不只是 query 的 —— 这里正是 `term in q` 出的问题。
    #   单字别名仍可被**精确**命中（查「墙」就得「墙」）。
    for term, nodes in alias.items():
        if term == q or len(term) < 2 or len(q) < 2:
            continue
        if q in term or term in q:
            for node in nodes:
                light(term, node, 0.75, "整串近似「%s」" % term)
    for tok in tokens(query):
        if tok in alias:
            for node in alias[tok]:
                light(tok, node, 1.0, "词命中「%s」" % tok)
        if len(tok) < 2:
            continue
        for term, nodes in alias.items():
            if term != tok and len(term) >= 2 and (tok in term or term in tok):
                for node in nodes:
                    light(term, node, 0.6, "词近似「%s」（来自 %s）" % (term, tok))
    return out


def spread(kb, seeds):
    """在别名命中之上再走一跳。★双向：家族 → 它的陷阱；陷阱 → 引用它的家族。"""
    alias = (kb.get("index") or {}).get("alias") or {}
    traps = kb.get("traps") or {}
    families = kb.get("playbook") or {}
    out = dict(seeds)
    for node, info in list(seeds.items()):
        w = info["weight"]
        if node.startswith("pb:"):
            fam = families.get(node[3:]) or {}
            for slug in (fam.get("traps") or []):
                t = "trap:" + slug if not slug.startswith("trap:") else slug
                if w * 0.5 > out.get(t, {}).get("weight", 0):
                    out[t] = {"weight": w * 0.5,
                              "why": "家族 %s 登记的并列陷阱" % node[3:]}
        elif node.startswith("trap:"):
            slug = node[5:]
            for fslug, fam in families.items():
                if slug in (fam.get("traps") or []):
                    f = "pb:" + fslug
                    if w * 0.5 > out.get(f, {}).get("weight", 0):
                        out[f] = {"weight": w * 0.5,
                                  "why": "陷阱被家族 %s 登记（反向邻接）" % fslug}
    return out


def nearest(alias, query, n=3):
    """miss 时给的「最接近的几条」。绝不回空数组 —— 空数组会被读成「没这回事」。"""
    q = set((query or "").lower())
    scored = []
    for term, nodes in alias.items():
        if not term:
            continue
        t = set(term.lower())
        overlap = len(q & t)
        if not overlap:
            continue
        scored.append((overlap / max(1, len(q)), term, nodes))
    scored.sort(key=lambda r: (-r[0], r[1]))
    seen, out = set(), []
    for score, term, nodes in scored:
        node = nodes[0]
        if node in seen:
            continue
        seen.add(node)
        out.append({"node": node, "matched": term, "score": round(score, 3)})
        if len(out) >= n:
            break
    return out


def answer(kb, query, building=None, inst=None):
    alias = (kb.get("index") or {}).get("alias") or {}
    traps = kb.get("traps") or {}
    families = kb.get("playbook") or {}
    act = spread(kb, seeds_of(alias, query))

    # ★★ 主命中 = **三支里证据最强的那一支**，不是「家族先看」（2026-09-24 改）。
    #
    # 原先是一串 `if fam_hits: … if trap_hits: … if entry_hits:`：家族只要**有**命中就整支吃掉。
    # 后果是**精确命中的陷阱输给一个 0.5 的派生回指**。实测（345 个别名逐个量）：
    #   · 145 个别名上，陷阱的权重**严格高于**任何家族 —— 它们今天全被答成家族；
    #   · 其中 **83 个**，家族那一侧**只是**被 `spread()` 的「陷阱被家族 X 登记」
    #     这条派生边以半权（0.5）点亮的 —— **家族根本没声称这个词**，
    #     它亮，纯粹因为那条陷阱挂在它名下；只有 3 个是家族的近似命中被挤掉。
    #   典型：`饱和` 整串精确命中陷阱 `trap-saturated-criterion`（1.0），
    #   家族 `floor-misalign` 只有 0.5（派生）—— 而查 `饱和` 画出来的是**楼层错位**的链，
    #   于是 14 条陷阱里有 8 条的**内容谁都打不开**（每个别名都被家族占了）。
    # ⇒ 一族一户地比权重；**同权重时才看原来的次序**（家族 → 陷阱 → 条目）——
    #   全库只有 2 个词落在这一档，且都是整句长别名（真歧义，不硬判）。
    # ⇒ 这个 `order` **同时**是 `activated` 的次序：于是 `activated[0]` **就是**主命中，
    #   「凭什么答它」与「答的是哪一支」由**同一个比较**产生，不会各说各话。
    order = sorted(act.items(),
                   key=lambda kv: (-kv[1]["weight"], -BRANCH_RANK[_branch_of(kv[0])], kv[0]))
    fam_hits = [(v["weight"], k[3:], v["why"]) for k, v in order if k.startswith("pb:")]
    trap_hits = [(v["weight"], k[5:], v["why"]) for k, v in order if k.startswith("trap:")]
    entry_hits = [(v["weight"], k, v["why"]) for k, v in order
                  if not k.startswith(("pb:", "trap:"))]
    top_kind = _branch_of(order[0][0]) if order else None

    res = {"query": query, "building": building,
           "activated": [{"node": k, "weight": round(v["weight"], 3), "why": v["why"]}
                         for k, v in order],
           "families": [f for _, f, _ in fam_hits],
           "traps": [{"slug": t, "title": (traps.get(t) or {}).get("title") or "",
                      "masquerades_as": (traps.get(t) or {}).get("masquerades_as") or "",
                      "anchored": bool((traps.get(t) or {}).get("cases"))}
                     for _, t, _ in trap_hits],
           "entries": [{"slug": s, "title": ((kb.get("entries") or {}).get(s) or {}).get("title") or "",
                        "domain": ((kb.get("entries") or {}).get(s) or {}).get("domain") or ""}
                       for _, s, _ in entry_hits],
           "ruler": ruler(kb)}

    if top_kind == "family":
        fslug = fam_hits[0][1]
        fam = families.get(fslug) or {}
        pop = lambda k: [i for i in (fam.get(k) or []) if isinstance(i, dict)]  # noqa: E731
        res.update({"state": "hit", "hit_kind": "family", "family": fslug,
                    "title": fam.get("title") or "", "kind": fam.get("kind") or "",
                    "symptom": pop("symptoms"), "cause": pop("causes"),
                    "fix": pop("fixes"), "run": pop("runs"),
                    "instances": pop("instances"), "related": pop("related"),
                    "unverified": [u for u in (fam.get("unverified") or []) if isinstance(u, dict)],
                    # ★手工记的实例（instances）与机器派生的实例（derived_instances）
                    #   是两个证据档，**分开摆**：合并成一个数组就再也分不清
                    #   「有人这么说过」和「机器在 49 栋的产物里量到过」。
                    "derived_instances": derived_for(
                        load_instances() if inst is None else inst, fslug, building),
                    "next_action": _next(fam)})
        if building:
            res["instances"] = _narrow(res["instances"], building)
        return res

    if top_kind == "trap":
        t = trap_hits[0][1]
        anchored = bool((traps.get(t) or {}).get("cases"))
        res.update({"state": "hit" if anchored else "unverified", "hit_kind": "trap",
                    "trap": t, "title": (traps.get(t) or {}).get("title") or "",
                    "mechanism": (traps.get(t) or {}).get("mechanism") or "",
                    "guards": (traps.get(t) or {}).get("guards") or [],
                    "cases": (traps.get(t) or {}).get("cases") or [],
                    "unverifiable": (traps.get(t) or {}).get("unverifiable") or "",
                    "next_action": ("照 guards 里那几条动作做；本条有仓内锚点，可复核"
                                    if anchored else
                                    "★本条只有人记着、仓内无锚点 ⇒ 只可参考，不许当已核。"
                                    "要让它可复核，把它落成一条判据或一条实物证据")})
        return res

    if top_kind == "entry":
        s = entry_hits[0][1]
        row = (kb.get("entries") or {}).get(s) or {}
        res.update({"state": "hit", "hit_kind": "entry", "entry": s,
                    "title": row.get("title") or "", "domain": row.get("domain") or "",
                    "content": row.get("content") or "",
                    "next_action": "读本文对应章节；这条是域知识，**没有可跑判据** —— "
                                   "别把「读到了」当成「验过了」"})
        return res

    res.update({"state": "miss",
                "nearest": nearest(alias, query, 3),
                "already_pending": pending_seen(query),
                "register": "python -u kb/ask.py \"%s\" --pending --who <谁>" % (query or ""),
                "next_action": "图里没有这个说法 ⇒ 按 register 记进 kb/pending.json 排队等人收；"
                               "**不要**把它读成「没问题」"})
    return res


def _narrow(instances, building):
    hit = [i for i in instances if building in json.dumps(i, ensure_ascii=False)]
    others = [dict(i, _note="与本楼无关，列出以便对照") for i in instances if i not in hit]
    return hit + others if hit else instances


def _next(fam):
    runs = [r for r in (fam.get("runs") or []) if isinstance(r, dict) and r.get("cmd")]
    if not runs:
        return ("本家族没有登记可跑判据（见 unverified）⇒ 下一步：人工看图，"
                "并把新判据按 kb/README.md 的回写协议补进 playbook.json")
    r = runs[0]
    return ("跑 `%s`（写 %s）；期望：%s；读：%s"
            % (r["cmd"], r.get("writes") or "未写", r.get("expect") or "未写",
               r.get("read") or "未写"))


# ── 输出 ────────────────────────────────────────────────────

def render(ans):
    st = ans["state"]
    head = {"hit": "命中", "unverified": "命中但没有仓内锚点", "miss": "图里没有"}[st]
    L = ["【%s】%s" % (head, ans.get("title") or ans.get("query") or "")]
    if st == "miss":
        L.append("  最近似的 %d 条（都不是它）：" % len(ans["nearest"]))
        for n in ans["nearest"]:
            L.append("    · %s ← 「%s」 相似度 %s" % (n["node"], n["matched"], n["score"]))
        L.append("  登记：%s" % ans["register"])
        ap = ans.get("already_pending")
        if ap:
            L.append("  排队中：已被登记 %d 次（最近 %s 由 %s）—— 排队≠已认识，"
                     "在它落进 playbook 之前这里照样回 miss" % (ap["times"], ap["at"], ap["who"]))
        else:
            L.append("  排队中：无（这个说法还没人报过）")
        L.append("  ★「图里没有」不是「没问题」—— 回空数组会让下游以为没这回事")
        return "\n".join(L)
    if ans.get("family"):
        for label, key in (("症状", "symptom"), ("根因", "cause"), ("处置", "fix")):
            for i in ans.get(key) or []:
                L.append("  %s：%s" % (label, i.get("what") or ""))
                L.append("        证据 %s" % (i.get("evidence") or "（缺）"))
        for r in ans.get("run") or []:
            L.append("  ▸ 判据：%s" % r.get("cmd"))
            L.append("        写 %s；期望 %s" % (r.get("writes"), r.get("expect")))
        for i in ans.get("instances") or []:
            L.append("  实例：%s" % (i.get("what") or ""))
        L.extend(_render_derived(ans.get("derived_instances")))
        for i in ans.get("unverified") or []:
            L.append("  ◇声明无锚点：%s —— %s" % (i.get("what") or "", i.get("reason") or ""))
    if ans.get("trap"):
        L.append("  ⚠ %s：%s" % (ans.get("trap"), ans.get("mechanism") or ""))
        for c in ans.get("cases") or []:
            L.append("        实物：%s —— %s" % (c.get("where"), c.get("what")))
        if ans.get("unverifiable"):
            L.append("        ★%s" % ans["unverifiable"])
    for t in ans.get("traps") or []:
        L.append("  ⚠ %s（%s）%s" % (t["slug"], "有锚点" if t["anchored"] else "只有人记着",
                                     t["masquerades_as"]))
    for e in ans.get("entries") or []:
        L.append("  📖 %s（%s）" % (e["title"], e["domain"]))
    L.append("→ 下一步：%s" % ans.get("next_action"))
    return "\n".join(L)


def _render_derived(d):
    """机器派生实例的排版。★两条轴分开打，且**先说分母** —— 没有分母的绿勾和「没量过」
    长得一样（铁律 16）。UNAVAILABLE 单独成一档，不折进「0 处」。"""
    if not d:
        return []
    if d.get("state") == "UNAVAILABLE":
        return ["  ▨ 实测实例：**量不了** —— %s" % (d.get("reason") or ""),
                "        怎么造：%s" % (d.get("how") or "")]
    L = ["  ▨ 实测实例（机器派生）：%d 栋 / %d 个楼-层对"
         % (d.get("n_buildings") or 0, d.get("n_floor_pairs") or 0)]
    for label, key in (("识别/台账侧", "by_code"), ("几何侧逐层", "by_flag")):
        rows = d.get(key) or {}
        if not rows:
            L.append("      %s：0 栋（这一把尺子没量到，不是「没有」）" % label)
            continue
        L.append("      %s：" % label)
        for b, cell in sorted(rows.items()):
            ks = sorted(cell, key=lambda k: (k == "_cross_floor", k))
            L.append("        %s → %s" % (b, "、".join(
                "跨层" if k == "_cross_floor" else "F%s" % k for k in ks)))
    if d.get("both"):
        L.append("      ★两把尺子都命中（互相印证）：%s" % "、".join(d["both"]))
    if d.get("by_code_geometry_unmeasured"):
        L.append("      ⚠ 只有识别侧看见、几何侧**没量过**（≠ 合格，也≠ 两边印证）：%s"
                 % "、".join(d["by_code_geometry_unmeasured"]))
    L.append("      %s" % (d.get("totals_note") or ""))
    return L


def list_all(kb):
    fams = kb.get("playbook") or {}
    print("已知症状家族 %d 个：" % len(fams))
    for slug, fam in fams.items():
        n_run = len([r for r in (fam.get("runs") or []) if isinstance(r, dict)])
        print("  pb:%-24s %s（别名 %d，可跑判据 %d，声明无锚点 %d）"
              % (slug, fam.get("title") or "", len(fam.get("alias") or []), n_run,
                 len(fam.get("unverified") or [])))
    traps = kb.get("traps") or {}
    anchored = [t for t, v in traps.items() if v.get("cases")]
    print("陷阱 %d 条：有仓内锚点 %d / 只有人记着 %d"
          % (len(traps), len(anchored), len(traps) - len(anchored)))
    for t, v in traps.items():
        if not v.get("cases"):
            print("  ◆ %s %s" % (t, v.get("title") or ""))
    print("知识条目 %d 篇：%s" % (len(kb.get("entries") or {}),
                                "、".join(kb.get("order") or [])))
    print("别名 %d 个（能点亮手册节点 %d 个 / 陷阱节点 %d 个）"
          % (len((kb.get("index") or {}).get("alias") or {}),
             len([1 for v in ((kb.get("index") or {}).get("alias") or {}).values()
                  if any(str(x).startswith("pb:") for x in v)]),
             len([1 for v in ((kb.get("index") or {}).get("alias") or {}).values()
                  if any(str(x).startswith("trap:") for x in v)])))


# ── 写盘（原子写；只有两条路径，都在本文件） ────────────────

def atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, path)


PENDING_NOTE = ("未收录的症状/说法。★空数组 = 还没有人报过，"
                "不等于「没有未收录的症状」。收口时逐条落进 playbook.json。"
                "★登记**不等于**已经认识它 —— 队列不会被 ask.py 当知识读，"
                "所以在它落进 playbook 之前，同一个说法照样回 miss。")


def _pending_read(path):
    if not (os.path.exists(path) and os.path.getsize(path)):
        return {"_note": PENDING_NOTE, "pending": []}
    with io.open(path, encoding="utf-8") as fh:
        try:
            obj = json.load(fh)
        except ValueError:
            return {"_note": PENDING_NOTE, "pending": []}
    if not isinstance(obj, dict) or not isinstance(obj.get("pending"), list):
        return {"_note": PENDING_NOTE, "pending": []}
    return obj


def pending_seen(query, path=PENDING):
    """这个说法此前被登记过几次（含最近一条的时刻/登记人）。"""
    rows = [r for r in _pending_read(path).get("pending") or []
            if isinstance(r, dict) and r.get("query") == query]
    if not rows:
        return None
    last = rows[-1]
    return {"times": len(rows), "at": last.get("at"), "who": last.get("who")}


def _is_production_queue(path) -> bool:
    """这份 path 是不是那份**生产**队列。用 realpath 比 —— 相对路径/软链归一到同一份。

    ★ 比的是 `PROD_PENDING`（固定），**不是 `PENDING`**（会被改道）。理由见常量那段的注释。
    """
    try:
        return os.path.realpath(path) == os.path.realpath(PROD_PENDING)
    except OSError:
        return False


def pending_guard(who, path) -> str | None:
    """模拟记录不许进生产队列 ⇒ 回**拒的理由**，放行则回 None。

    ★ 抽成独立判据的理由有两个，都要紧：
      ① 「一条规则只许一份实现」—— 写入口与自检共用这一份，自检才**真的**在量写入口那道闸；
      ② 自检必须**能红**，而验「真署名不许被误拒」那一侧**不能真写生产队列**。
         判据与动作分开，两端就都量得到，且一个字节都不落到真队列上。
    """
    if not _is_production_queue(path):
        return None                       # 已改道（GYM3D_KB_PENDING）⇒ 一律放行
    hit = [m for m in SIM_WHO_MARKERS if m in (who or "")]
    if not hit:
        return None
    return ("拒绝写生产队列：`who` 里有「%s」—— 这条看着是**模拟/验收**记录，"
            "而 %s 是等人来收的生产件，混进去之后人分不清哪条是真有人报过的。"
            "验收/自检请把 GYM3D_KB_PENDING 指到临时文件再跑。"
            % ("、".join(hit), os.path.relpath(PROD_PENDING, ROOT)))


def append_pending(query, who, nearest_rows, path=PENDING):
    """写入口**唯一**，所以守卫卡在这儿（卡在 CLI 分支里，下一个调用者就绕过去了）。

    ★ 生产队列是「等人来收」的：模拟记录混进来之后，人分不清哪条是真有人报过的。
      加这条守卫之前它只是一句注释里的约定，而约定被忘过一次。
    """
    who = who or "未署名"
    why = pending_guard(who, path)
    if why:
        raise ValueError(why)
    obj = _pending_read(path)
    obj["pending"].append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "who": who,
                           "query": query,
                           "nearest": nearest_rows,
                           "state": "miss"})
    atomic_json(path, obj)
    return path


def argv_of(cmd):
    """命令 → argv。★**不经过 shell**：图谱是被审过的数据，但它毕竟是个文件，
    而 shell=True 会让文件里的一行变成一次注入。只许纯 argv 形，含 shell 元字符即拒。"""
    if not cmd:
        return None, "空命令"
    if any(c in cmd for c in ";&|<>$`\n(){}*?~"):
        return None, "含 shell 元字符，拒跑（本文件只接受纯 argv 形的命令）"
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        return None, "引号不成对：%s" % exc
    return (parts, None) if parts else (None, "解析成空 argv")


def run_registered(kb, ans, ledger=LEDGER):
    """★只跑图里登记过的命令。跑完留痕（含尺子指纹）。"""
    runs = ans.get("run") or []
    if not runs:
        return {"ran": 0, "note": "本家族没有登记可跑判据 —— 不跑任何东西，也不猜一条命令出来"}
    out = []
    print("将跑 %d 条（命令来自 kb.json，不是现编的）：" % len(runs))
    for r in runs:
        cmd = r.get("cmd") or ""
        print("  ▸ %s\n    声明的写盘副作用：%s" % (cmd, r.get("writes") or "（没写！）"))
        argv, why = argv_of(cmd)
        if argv is None:
            print("    ★拒跑：%s" % why)
            out.append({"cmd": cmd, "exit": "REFUSED", "seconds": 0.0, "tail": why,
                        "expect": r.get("expect") or "", "read": r.get("read") or "",
                        "writes": r.get("writes") or "", "evidence": r.get("evidence") or ""})
            continue
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=ROOT, timeout=RUN_TIMEOUT,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            code, blob = p.returncode, p.stdout.decode("utf-8", "replace")
        except FileNotFoundError as exc:            # ★「没跑起来」不许长得像「跑完了」
            code, blob = "NOTFOUND", "命令起不来：%s（★这不是「没有输出」）" % exc
        except subprocess.TimeoutExpired:
            code, blob = "TIMEOUT", "超过 %d 秒未返回（★这既可能是慢，也可能是它根本没在跑）" % RUN_TIMEOUT
        tail = "\n".join([l for l in blob.splitlines() if l.strip()][-6:])
        out.append({"cmd": cmd, "exit": code, "seconds": round(time.time() - t0, 1),
                    "tail": tail, "expect": r.get("expect") or "",
                    "read": r.get("read") or "", "writes": r.get("writes") or "",
                    "evidence": r.get("evidence") or ""})
        print("    退出码 %s，用时 %.1fs" % (code, time.time() - t0))
        for l in tail.splitlines():
            print("      | %s" % l)
    rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "query": ans.get("query"),
           "family": ans.get("family"), "ruler": ans.get("ruler"), "runs": out}
    if os.path.exists(ledger) and os.path.getsize(ledger):
        with io.open(ledger, encoding="utf-8") as fh:
            try:
                hist = json.load(fh)
            except ValueError:
                hist = None
    else:
        hist = None
    if not isinstance(hist, dict) or "runs" not in hist:
        hist = {"_note": "kb/ask.py --run 的判据结果留痕。★每条都带尺子指纹 —— "
                         "没有它，下次读到的数分不清是哪把尺子量的。",
                "runs": []}
    hist["runs"].append(rec)
    atomic_json(ledger, hist)
    return {"ran": len(out), "ledger": ledger, "results": out}


# ── 自检 ────────────────────────────────────────────────────

def selftest():
    """每条都要能红。★阴性对照一并做：无关说法不许点亮别的家族。"""
    fails = []
    kb = load_kb()
    grp = {"楼层错位": "floor-misalign", "骑墙": "room-outside-outline",
           "越界": "room-outside-outline", "外溢": "room-outside-outline",
           "漏墙": "missing-wall-blob", "糊块": "missing-wall-blob",
           "并块": "room-merged-duplicate", "房号重复": "room-merged-duplicate"}
    for q, fam in grp.items():
        a = answer(kb, q)
        if a["state"] != "hit":
            fails.append("T1 「%s」应当命中，实得 state=%s" % (q, a["state"]))
        elif a.get("family") != fam:
            fails.append("T1 「%s」应点亮 %s，实得 %s" % (q, fam, a.get("family")))
    for q in ("楼层错位", "漏墙", "并块"):
        a = answer(kb, q)
        w = "T2 「%s」(=%s)" % (q, a.get("family") or a.get("state"))
        if a.get("hit_kind") != "family":
            fails.append("%s 应当命中手册家族，实得 hit_kind=%s" % (w, a.get("hit_kind")))
        if not a.get("symptom") or not a.get("cause") or not a.get("fix"):
            fails.append("%s 的链不完整（症状/根因/处置三栏必须都有）" % w)
        if not a.get("next_action"):
            fails.append("%s 没有 next_action" % w)
        if not a.get("run") and not a.get("unverified"):
            fails.append("%s 既没有可跑判据、又没有如实声明无锚点" % w)

    m = answer(kb, "紫水晶大蒜量子")
    if m["state"] != "miss":
        fails.append("T3 无关说法应为 miss，实得 %s" % m["state"])
    if not m.get("nearest"):
        fails.append("T3 miss 回了空数组 —— 「图里没有」会被读成「没问题」")
    if not m.get("register"):
        fails.append("T3 miss 没给登记入口")

    u = answer(kb, "进度数")
    if u["state"] != "unverified":
        fails.append("T4 只有人记着的陷阱应给 unverified，实得 %s" % u["state"])

    neg = answer(kb, "漏墙")
    if neg.get("family") == "floor-misalign":
        fails.append("T5 阴性对照：说「漏墙」却点亮了楼层错位家族（扩散过头）")
    other = answer(kb, "楼层错位")
    if "missing-wall-blob" in (other.get("families") or []):
        fails.append("T5 阴性对照：说「楼层错位」却点亮了漏墙家族")

    cmds = [r.get("cmd") for f in (kb.get("playbook") or {}).values()
            for r in (f.get("runs") or []) if isinstance(r, dict)]
    if not cmds:
        fails.append("T6 图里一条可跑命令都没有 —— --run 将无事可做却可能报「成功」")
    for c in cmds:
        # ★ 前缀元组从 kb/gate.py 引（READONLY_PREFIX），本文件不重抄 —— 见文件头那段。
        if not str(c).startswith(READONLY_PREFIX):
            fails.append("T6 命令 %r 不在只读白名单前缀里（门禁⑦会拒，本文件也得拦）" % c)
        if argv_of(c)[0] is None:
            fails.append("T6 命令 %r 过不了 argv 解析（%s）—— 跑起来会被拒跑"
                         % (c, argv_of(c)[1]))
        if not any(c == (r.get("cmd") or "") for f in (kb.get("playbook") or {}).values()
                   for r in (f.get("runs") or []) if isinstance(r, dict)):
            fails.append("T6 命令 %r 不是从图里来的" % c)

    # T8 单字别名不许凭子串点亮（实测：「漏墙」曾被单字「墙」带得 hit 到一篇无关文档）。
    # ★两面都要测：同类探针既要求窄的那面**空**，也要求宽的那面**非空** ——
    #   只测「空」的话，把 seeds_of 整个改成 return {} 也能绿。
    if seeds_of({"墙": ["n1"]}, "漏墙"):
        fails.append("T8 单字别名「墙」凭子串点亮了 2 字查询「漏墙」—— 会命中无关节点")
    if not seeds_of({"漏墙率": ["n1"]}, "漏墙"):
        fails.append("T8 ≥2 字的子串匹配失效了（阳性对照：该亮的不亮）")

    # T9 实例层：★两件事必须分开 —— 「这个家族一处也没观察到」和「还没派过实例」。
    #   实测（本仓铁律 16）：空输出不是「没有数据」。所以这里既查**真稿**的形状，
    #   也查**缺稿**时不许折成 0，还要查渲染层不把 UNAVAILABLE 印成「0 栋」。
    real = answer(kb, "楼层错位", "c027")
    d = real.get("derived_instances") or {}
    if d.get("state") == "UNAVAILABLE":
        if not d.get("reason") or not d.get("how"):
            fails.append("T9 实例层缺失时没写清原因与补救（只回了一个空壳）")
    elif d.get("state") == "ok":
        listed = set(d.get("by_code") or {}) | set(d.get("by_flag") or {})
        if len(listed) != d.get("n_buildings"):
            fails.append("T9 实例层的 n_buildings=%s 与列出来的楼栋 %d 对不上"
                         % (d.get("n_buildings"), len(listed)))
        if not (d.get("ruler_of_instances") or {}).get("derive_self_sha12"):
            fails.append("T9 实例层没带尺子指纹 —— 下次读到的数分不清是哪把尺子量的")
        if "c027" in listed and "c027" not in (d.get("by_flag") or {}):
            fails.append("T9 带楼名查 c027 却把别的楼也列了进来（_narrow 没生效）")
    else:
        fails.append("T9 实例层 state=%r 既不 ok 也不 UNAVAILABLE（第三种状态没人认得）")

    miss_inst = load_instances(os.path.join(KB_DIR, "_no_such_instances.json"))
    if miss_inst.get("state") != "UNAVAILABLE":
        fails.append("T9 实例稿不存在时应回 UNAVAILABLE，实得 %r" % miss_inst.get("state"))
    md = derived_for(miss_inst, "floor-misalign")
    if md.get("state") != "UNAVAILABLE":
        fails.append("T9 实例稿缺失却被折算成了「0 栋」（%r）—— 没量过 ≠ 一处也没有" % md)
    txt = "\n".join(_render_derived(md))
    if "0 栋" in txt or "量不了" not in txt:
        fails.append("T9 渲染把「没量过」印成了「0 栋」（实测：屏幕上这两句一模一样）")

    # T9b ★两把尺子不许互相挡门。识别侧（code 轴）覆盖 95 栋，几何侧（flag 轴）只有 49 栋；
    #   本文件曾拿几何侧的门票 `if v["report"] is not True: continue` 去挡识别侧的数据，
    #   于是 9 栋的 10 条家族命中**静默不进实例栏** —— 而屏幕上与「一处也没观察到」长得一样。
    #   这条用**合成稿**（不依赖磁盘上恰好有几栋）：一栋有报告、一栋无报告，两栋都带同一 code。
    #   判据分两半，缺一半就等于没验：① 无报告那栋**必须出现在 by_code**；
    #   ② 它**必须被单列进 by_code_geometry_unmeasured**（不许混进「两边都印证」那一栏）。
    synth = {"state": "ok", "criterion_version": 9, "self_sha12": "deadbeefcafe",
             "generated_from": {"src_sha": {"synthetic": "0" * 12}},
             "totals": {"buildings": 2, "with_report": 1, "unavailable": 1},
             "codes": {"D7": {"family": "room-merged-duplicate"}},
             "flags": {},
             "buildings": {
                 "c901": {"report": True, "codes_by_floor": {"5": {"D7": 1}}, "obs": {}},
                 "c902": {"report": False, "state": "UNAVAILABLE", "reason": "合成",
                          "codes_by_floor": {"3": {"D7": 1}}},
             }}
    sd = derived_for(synth, "room-merged-duplicate")
    if "c902" not in (sd.get("by_code") or {}):
        fails.append("T9b 无几何报告的楼栋，识别侧命中被 `report` 挡掉了 —— "
                     "「几何侧没量过」不该让人看不见「识别侧看见了」")
    if "c902" not in (sd.get("by_code_geometry_unmeasured") or []):
        fails.append("T9b 只有识别侧看见的楼没被单列出来 —— "
                     "它会和「两把尺子互相印证」混成一栏（UNAVAILABLE ≠ PASS）")
    if "c901" in (sd.get("by_code_geometry_unmeasured") or []):
        fails.append("T9b 阳性对照：有报告的 c901 被误列进了「几何侧没量过」那栏")

    # T10 楼名认得出吗。★这条守的是**命令行层**：`"c027 楼层错位"` 带引号时是一个 argv，
    #    实测曾整段漏掉 ⇒ 实例栏不挑楼、而屏幕上「命中」照旧。两个方向都要测。
    for argv, want in ((['c027 楼层错位'], "c027"), (['c027', '楼层错位'], "c027"),
                       (['C027 楼层错位'], "c027"), (['楼层错位'], None),
                       (['dxf 楼层错位'], None), (['c0270x'], None)):
        got = building_in(argv, " ".join(argv))
        if got != want:
            fails.append("T10 `%s` 应认出楼名 %r，实得 %r"
                         % (" ".join(argv), want, got))

    # T11 主命中按**证据强弱**取，不按「家族先看」（2026-09-24 加；改之前 84 个别名答反）。
    #     ★两面都测：**精确命中的陷阱要赢**，而**家族自己的别名仍要赢**。
    #     只测前一面的话，把排序整个反过来（陷阱永远优先）也能绿 ——
    #     那不是修好了，是把同一个错换个方向（本仓栽过：只改一个方向 = 没改）。
    for q, want_kind, want_id in (("饱和", "trap", "trap-saturated-criterion"),
                                  ("一刀切", "trap", "trap-blanket-ban-illegal-polygon"),
                                  ("楼层错位", "family", "floor-misalign"),
                                  ("漏墙", "family", "missing-wall-blob")):
        a = answer(kb, q)
        got = a.get("hit_kind"), (a.get("trap") or a.get("family"))
        if got != (want_kind, want_id):
            fails.append("T11 「%s」应命中 %s %s，实得 %s %s"
                         % (q, want_kind, want_id, got[0], got[1]))
        # ★ 主命中必须**就是** activated[0]：两个次序各写一遍的话，
        #   报告里「凭什么答它」会和答案本身对不上（而那种错没人看得出来）。
        elif a.get("activated") and a["activated"][0]["node"] != (
                "pb:" + want_id if want_kind == "family" else "trap:" + want_id):
            fails.append("T11 「%s」的 activated[0]=%s 与主命中 %s 不是同一支"
                         % (q, a["activated"][0]["node"], want_id))
    # 阴性对照：家族那一侧在「饱和」上只是**派生回指**（半权），不许被当成主证据
    sat = answer(kb, "饱和")
    fw = [r["weight"] for r in (sat.get("activated") or [])
          if r["node"] == "pb:floor-misalign"]
    if fw and fw[0] >= 1.0:
        fails.append("T11 阴性对照：家族在「饱和」上竟然也是满权重（%.2f）—— "
                     "那这条词就是真歧义，判据得换成「点得准」以外的说法" % fw[0])

    tmp = os.path.join(KB_DIR, "_pending_selftest.json")
    try:
        for _ in range(2):
            append_pending("注入的症状", "自检", [{"node": "x", "score": 0.1}], path=tmp)
        with io.open(tmp, encoding="utf-8") as fh:
            obj = json.load(fh)
        if len(obj.get("pending") or []) != 2:
            fails.append("T7 pending 应追加（两次 = 2 条），实得 %d 条"
                         % len(obj.get("pending") or []))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    # T7b 守卫两端（★ 只调判据，一个字节都不落到真队列上）。比的是 **PROD_PENDING**。
    if not _is_production_queue(PROD_PENDING):
        fails.append("T7b 量不到东西：PROD_PENDING（%s）没被认成生产队列 —— "
                     "这一组刑具全是空跑，必须先让它指着真队列" % PROD_PENDING)
    else:
        if not pending_guard("K2 验收（模拟查询）", PROD_PENDING):
            fails.append("T7b 守卫没红：带「验收」的 who 打生产队列竟然放行")
        if pending_guard("现场巡检 张三", PROD_PENDING):
            fails.append("T7b 阴性对照：真实署名被误拒了 —— 判据宽成了「一律拒写」"
                         "（那队列就再也收不进任何东西，而屏幕上看着像「已收口」）")
    # 这一格只覆盖「不是生产路径就放行」，**与改道无关** —— 别把它当改道的证据用。
    if pending_guard("K2 验收", tmp):
        fails.append("T7b 非生产路径也该放行，却被拒了")

    # T7c ★ 改道的**真实形状**：一个真把 GYM3D_KB_PENDING 打开的子进程。
    #   为什么非开子进程不可：`PENDING` 在 import 时定值，进程内改不动 ——
    #   而「改道之后还能不能写」正是第一版守卫栽的那一面，且它在进程内**不可观测**：
    #   不设变量时 PROD_PENDING == PENDING，错的写法与对的写法表现完全一样。
    #   ⇒ 只有起一个带着环境变量的进程，才量得到这一面。
    probe = os.path.join(KB_DIR, "_pending_guard_probe.json")
    # ★ 用 `__file__`，不用硬编码的 "ask.py"：自检要量的是**它自己这个文件**。
    #   写死兄弟名的话，把它复制出去做对照实验时，它会跑去调那个**已经修好的**真文件 ——
    #   于是对照恒绿，量具自己把被测对象换掉了。
    ask_py = os.path.abspath(__file__)

    def _run_cli(who, pend_env, *extra):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        if pend_env is not None:
            env["GYM3D_KB_PENDING"] = pend_env
        return subprocess.run([sys.executable, "-u", ask_py, "注入的症状",
                               "--pending", *extra, "--who", who],
                              capture_output=True, env=env, cwd=ROOT)

    try:
        # ① 改道后必须**能写**（exit 0 且真的落盘）
        p = _run_cli("K2 验收（模拟查询）", probe)
        if p.returncode != 0:
            fails.append("T7c 改道失效：设了 GYM3D_KB_PENDING 仍被拒（exit=%d）—— 验收没法跑，"
                         "人只会去把这个守卫删掉。stderr=%s"
                         % (p.returncode, p.stderr.decode("utf-8", "replace").strip()[:160]))
        elif not os.path.exists(probe):
            fails.append("T7c 改道了却没落盘：exit=0 但 %s 没生成" % probe)
        # ② 反面：同一句命令、不设变量 ⇒ 必须被拒（拒在写之前，生产队列一个字节不动）
        q = _run_cli("K2 验收（模拟查询）", None)
        if q.returncode == 0:
            fails.append("T7c 反面没红：不设 GYM3D_KB_PENDING 时，模拟署名竟写进了**生产队列**")
        # ③ `--dry-run` 必须**一个字节都不写**（含真署名的形状 —— 守卫拦不住那种，
        #    所以「问一句」这件事本身必须是无副作用的）
        with open(PROD_PENDING, "rb") as fh:
            h0 = fh.read()
        d = _run_cli("现场巡检 张三", None, "--dry-run")
        with open(PROD_PENDING, "rb") as fh:
            h1 = fh.read()
        if d.returncode != 0:
            fails.append("T7c dry-run 该放行的却报了错（exit=%d）：%s"
                         % (d.returncode, d.stderr.decode("utf-8", "replace").strip()[:160]))
        if h0 != h1:
            fails.append("T7c dry-run 竟然写了盘 —— 生产队列字节变了（%d → %d）" % (len(h0), len(h1)))
    finally:
        if os.path.exists(probe):
            os.remove(probe)

    if fails:
        print("--selftest 红：%d 条" % len(fails))
        for f in fails:
            print("  ✗ %s" % f)
        return 1
    # ★ 这里**故意不写「N 组」**：那个数是手抄的，每加一条刑具就得记得改，
    #   而漏改的后果是「屏幕上少报了一档、覆盖看起来变小了」—— 这属于
    #   「手写的版本号会忘」（铁律 24）。改成把**名字逐条列出来**，加了什么一眼看得见。
    print("--selftest 绿：刑具全部能红 —— %d 个说法点亮正确的家族；miss 不空回；"
          "unverified 与 hit 分开；两条阴性对照；命令只从图里来、且必须是纯 argv "
          "（不经过 shell）；pending 是追加；单字别名不许凭子串点亮；"
          "实例层「没量过」≠「一处也没有」；两把尺子不许互相挡门；"
          "带引号的整句也要认出楼名；"
          "主命中按证据强弱取、且 activated[0] 与它同源" % len(grp))
    print("现表：家族 %d、陷阱 %d（只有人记着 %d）、别名 %d"
          % (len(kb.get("playbook") or {}), len(kb.get("traps") or {}),
             len([1 for v in (kb.get("traps") or {}).values() if not v.get("cases")]),
             len((kb.get("index") or {}).get("alias") or {})))
    return 0


def main():
    args = sys.argv[1:]
    for a in args:
        if a.startswith("-") and a not in FLAGS:
            print("不认识的开关 %r。本仓不认 --help（会被当成查询词）；"
                  "可用开关：%s" % (a, " ".join(FLAGS)))
            return 2
    if "--selftest" in args:
        return selftest()
    kb = load_kb()
    if "--list" in args:
        list_all(kb)
        return 0

    top = 3
    if "--top" in args:
        i = args.index("--top")
        try:
            top = max(1, int(args[i + 1]))
        except (IndexError, ValueError):
            print("--top 后面要给一个整数")
            return 2

    who = ""
    if "--who" in args:
        i = args.index("--who")
        who = args[i + 1] if i + 1 < len(args) else ""

    words = query_words(args)
    if not words:
        print(__doc__.strip().splitlines()[0])
        print("给一个说法试试：python -u kb/ask.py \"楼层错位\"")
        return 2

    query = " ".join(words)
    building = building_in(words, query)
    ans = answer(kb, query, building)

    if "--pending" in args:
        rows = ans.get("nearest") or nearest(
            (kb.get("index") or {}).get("alias") or {}, query, top)
        if ans["state"] != "miss":
            print("★这个说法图里是有的（state=%s，家族 %s）—— 不登记成「未收录」。"
                  "若你认为它该单列，请按回写协议补字段。"
                  % (ans["state"], ans.get("family")))
            return 0
        seen = pending_seen(query)
        # ★ `--dry-run`：把「会被接受还是会被拒」问出来，**一个字节都不写**。
        #   为什么必须有它：验「真署名不该被误拒」那一侧，唯一的做法就是真去写一次 ——
        #   而那次写入**会留在生产队列里**（实测：我用 `--who 现场巡检 张三` 验完，
        #   队列里就躺着一行「某真实巡检发现的说法」）。守卫拦不住它 ——
        #   它长得就是一条真记录，而守卫按设计只能拦「自称是模拟」的那种。
        #   ⇒ 出路不是把守卫写宽（宽了就拦不住真的），是给验收一条**不写盘**的问法。
        if "--dry-run" in args:
            why = pending_guard(who or "未署名", PENDING)
            print("【dry-run】目标 = %s（本次不写盘）" % PENDING)
            if why:
                print("  ⇒ 会被**拒**：%s" % why)
                return 2
            print("  ⇒ 会被**接受**：%s（%s）" % (query, who or "未署名"))
            return 0
        try:
            path = append_pending(query, who, rows)
        except ValueError as exc:
            print("✗ %s" % exc)
            return 2
        print("已登记到 %s：%s（%s）" % (path, query, who or "未署名"))
        if seen:
            print("★此前已有 %d 条同说法（最近 %s 由 %s 登记）—— 本轮照样追加，"
                  "**重复次数本身就是「这个症状有多常见」的证据**，不许去重抹掉。"
                  % (seen["times"], seen["at"], seen["who"]))
        print("★它现在**排着队**，不再需要下次再猜一遍。收口时落进 playbook.json —— "
              "★在落进去之前，同一个说法照样回 miss（排队 ≠ 已认识）。")
        return 0

    if "--run" in args:
        if ans["state"] != "hit":
            print("state=%s ⇒ 没有可跑判据（不猜命令）" % ans["state"])
            print(render(ans) if not ans.get("nearest") else "")
            return 0
        res = run_registered(kb, ans)
        if "--json" in args:
            print(json.dumps(dict(ans, run_result=res), ensure_ascii=False, indent=1))
        else:
            print("跑了 %d 条；留痕 → %s" % (res["ran"], res.get("ledger") or "无"))
            print("★退出码与 expect 的比对**留给人**：本文件只负责跑 + 记账，不替你宣布合格")
        return 0

    if "--json" in args:
        print(json.dumps(ans, ensure_ascii=False, indent=1))
    else:
        print(render(ans))
    return 0


if __name__ == "__main__":
    sys.exit(main())
