# -*- coding: utf-8 -*-
"""K5 验收器 —— 后台图谱视图读到的，与命令行是不是**同一份 JSON**。

判据原话：**「后台视图 | 与 CLI 同一份 JSON；页面对不上即红」**。
页面那一侧读的是 `GET /api/kg` 与 `GET /api/kg/ask`（`backend/api/routers/kg.py`），
所以这个脚本就是那句话的机械形态。

    python -m backend.checks.kg_view_accept --parity --base http://127.0.0.1:8153
    python -m backend.checks.kg_view_accept --falsify          # 证明这套比较**能红**
    python -m backend.checks.kg_view_accept --shapes           # 页面**声明**的键 vs 载荷真有的键
    python -m backend.checks.kg_view_accept --walk             # 真开浏览器，逐条画一遍

★ 退出码：`0` 量过且通过 ｜ `1` 量过且不通过 ｜ `2` 参数不对 ｜ `3` **没量成**。
  `3` 是后端起不来 / 没装 playwright / 浏览器起不来。**它必须与 `1` 分开** ——
  本仓栽过的那一族里，"没量成"被读成"通过了"和"被读成失败了"各有一半。

## 四个模式各自盖不住什么（所以四个都要）

| 模式 | 量什么 | **盖不住** |
|---|---|---|
| `--parity` | 页面读到的 JSON vs CLI 的 JSON | 值对了但**画不出来** |
| `--shapes` | `kg.js` 里声明的键 vs 载荷真有的键 | 键对上了但**值的形状**对不上 |
| `--walk` | 浏览器里**真的画出来了**（29 个节点逐条） | 画得对不对（那要人看） |
| `--falsify` | 前两个比较器**能不能红** | 页面 |

★ `--shapes` 与 `--walk` 是两个层次，**不是重复**：实测过 `mechanism` 是一个**字符串**，
  而渲染器把它喂给了列表那一支 ⇒ 查任何陷阱整页白屏。
  `--shapes` 当时是**绿的**（键在不在它对，值的形状它看不见），
  只有真跑浏览器才发现。⇒ **声明得对 ≠ 画得出来。**

★ `--walk` 的耗时主要由**环境**决定，不是本程序：实测本机单次要 1~1.5 分钟，
  其中首屏那 9 秒是"新建 loopback 连接"的开销（同一台机器上，热连接取 `js/app.js`
  的 ttfb 只有 **1.4ms**）。别把它当成"页面慢"报出去 —— 那是量具所在环境的性质。
## `--parity` 比的是哪两份

**清单**：页面读 `/api/kg`，人对 CLI 读 `python -u kb/ask.py --list`。这两边必须逐数相同。
`--list` 是给人看的中文文本，没有 JSON 模式 —— 所以这里**逐个正则去挖数**。
★ 挖不到就**硬红**，绝不当"这一行没有"。本仓栽过的那一族（空输出 / 截断 / 量具没接上）
  长得和"全对"一模一样，所以「正则没命中」必须报成故障而不是跳过。
★ 这不是"同源比对"：一边是 JSON 投影（`services/kg.py`），一边是文本渲染（`ask.py`），
  两条不同的代码路径。同源比对恒绿（memory: same-source-comparison-always-green），
  那种恒等式证明不了任何东西。

**查询**：页面读 `/api/kg/ask`，参考值用**接口自己报的 `meta.argv`** 重跑一遍。
这不是左手比右手 —— 它同时验两件真事：
  ① 接口把 `ask.py --json` 的载荷**原样透传**（没有在服务层重新塑形）；
  ② `meta.argv` 那句命令行**是可复现的**（照它敲一遍能拿到同一个答案）。
★ 这正是 2026-09-24 抓到 `--top` 的值漏进查询串的那个比法：当时接口报
  `--top 3` 却把 `3` 当查询词，重跑一遍立刻对不上。

## `--falsify` 为什么必须有

一个永远说"相同"的比较器，与"真的相同"在屏幕上长得一模一样。
所以这里喂它四种**已知不同**的输入，要求它在**那一处**报出来（顶层 / 嵌套 / 键缺失），
外加两条阴性对照：**相同的输入必须回空**（回不空 = 比较器自己坏了）。

★ 默认基址 8153 是**临时测试实例**的口（`GYM3D_PORT=8153`）；8140 是常在的那个。
  比之前先确认那个口上跑的是**当前源码** —— 否则量的是旧进程，而屏幕上毫无差别
  （memory: 铁律 24 同族：这份数是旧尺子量的 / 它是对的，长得一样）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):          # ★ Windows 管道默认 GBK，中文必炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
DEFAULT_BASE = os.environ.get("GYM3D_ACCEPT_BASE", "http://127.0.0.1:8153")


class Unavailable(Exception):
    """**没量成** —— 与「量出来是坏的」是两件事，退出码也不同（3 vs 1）。

    本仓的老毛病正是这两件在屏幕上长得一样（铁律 16 的镜像）。
    连不上后端、后端回的不是信封、没装 playwright、浏览器起不来：都归这里。
    """
_TIMEOUT = 60

#: 四类查询各挑一条，三态**都要走到** —— 只验 `hit` 等于没验
#: （`miss` 与 `unverified` 是两套分支，`miss` 还带 `nearest[]`）。
CASES = [
    ("楼层错位", "", 3),          # hit
    ("楼层错位", "c057", 5),      # hit ＋ 带楼号（楼号当一个词传，不并进查询串）
    ("中文乱码", "", 3),          # unverified（只有人记着的陷阱）
    ("洞中洞", "", 3),            # miss（必须带 nearest[]，不许回空数组）
]
CLAMP_CASE = ("楼层错位", "", 99)  # top 超过上限 ⇒ 夹住，且 meta 要如实报夹过

#: `--list` 的四行数字。★ 每条都是**锚定行首行尾**的，挖不到就是故障。
_RE_FAM = re.compile(r"^\s{2}pb:(\S+)\s+.*（别名 (\d+)，可跑判据 (\d+)，声明无锚点 (\d+)）\s*$")
_RE_TRAPS = re.compile(r"^陷阱 (\d+) 条：有仓内锚点 (\d+) / 只有人记着 (\d+)\s*$")
_RE_ENTRIES = re.compile(r"^知识条目 (\d+) 篇：")
_RE_ALIAS = re.compile(r"^别名 (\d+) 个")


# ── 比字段（递归，带路径）──────────────────────────────────────────────

def diff(cli, api, path: str = "$") -> list[str]:
    """逐字段比，回**带路径**的差异清单。空列表 = 逐字段相同。

    ★ 必须递归：2026-09-24 那次真缺陷，顶层 `query` 变了、嵌套的
      `activated[0].why` 也跟着降级（「整串精确命中」→「词命中」）。
      只比顶层会**只看见一半**，而"看见一半"与"全对"在汇总行里长得一样。
    """
    out: list[str] = []
    if isinstance(cli, dict) and isinstance(api, dict):
        for k in sorted(set(cli) | set(api)):
            if k not in cli:
                out.append("%s.%s：CLI 没有这一项，页面多给了" % (path, k))
            elif k not in api:
                out.append("%s.%s：页面少了这一项（CLI 有）" % (path, k))
            else:
                out += diff(cli[k], api[k], "%s.%s" % (path, k))
    elif isinstance(cli, list) and isinstance(api, list):
        if len(cli) != len(api):
            out.append("%s：长度 CLI %d / 页面 %d" % (path, len(cli), len(api)))
        for i, (x, y) in enumerate(zip(cli, api)):
            out += diff(x, y, "%s[%d]" % (path, i))
    elif isinstance(cli, bool) or isinstance(api, bool):
        # ★ bool 是 int 的子类，`True == 1` 为真 —— 不先拦下来，true/false 与 1/0
        #   会被判成"相同"（本仓踩过同族的坑：`is` 与 `==` 在这条路上不是一回事）。
        if cli is not api:
            out.append("%s：CLI %r / 页面 %r" % (path, cli, api))
    elif isinstance(cli, (int, float)) and isinstance(api, (int, float)):
        if cli != api:
            out.append("%s：CLI %r / 页面 %r" % (path, cli, api))
    elif cli != api:
        out.append("%s：CLI %r / 页面 %r" % (path, cli, api))
    return out


# ── 取数 ──────────────────────────────────────────────────────────────

def _quote(s: str) -> str:
    """`encodeURIComponent` 的等价物 —— 与页面里那条链接**逐字相同**的编码。

    ★ `safe=''` 不能省：默认值 `safe='/'` 会把斜杠留成裸斜杠，
    而页面编出来的是 `%2F`。查询词里带 `/`（房号、层号、`file:行`）时两边就不是同一个 URL 了，
    于是走查量的是一个**用户点不到的**地址 —— 而它照样画得出东西，照样绿。
    """
    return urllib.parse.quote(s, safe="")


def _get(base: str, path: str) -> tuple[dict, str]:
    """回 `(信封, 状态描述)`。**连接失败也是一种结果**，要如实说。"""
    url = base.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as ex:             # 4xx/5xx 也带信封，照样读
        raw, status = ex.read(), ex.code
    except Exception as ex:
        return {}, "连不上 %s：%s" % (url, ex)
    try:
        env = json.loads(raw.decode("utf-8"))
    except Exception as ex:
        return {}, "%s 回的体子不是 JSON：%s（前 120 字节 %r）" % (url, ex, raw[:120])
    # ★ 解析成功 ≠ 拿到信封。实测（2026-09-24，把基址指到 8144 那台不提供 admin UI 的服务）：
    #   它回的是**纯文本 `404`**，`json.loads("404")` **合法**，得到整数 404，
    #   于是这里一路放行，直到 `env.get("success")` 抛出
    #   `AttributeError: 'int' object has no attribute 'get'` ——
    #   一个连不上的服务被报成**本程序的崩溃**，而屏幕上是一段 traceback，
    #   既不是「没量成」也不是「量出来是坏的」（铁律 16 的镜像：
    #   「量具坏了」和「被测对象是空的」长得一样；这里还多一层 ——
    #   **「体子能解析」和「体子是信封」也是两件事**）。
    #   裸数字 / 裸字符串 / 数组一律按"不是信封"处理，回故障而不是崩。
    if not isinstance(env, dict):
        return {}, "%s 回的体子是 %s，不是信封对象（前 120 字节 %r）" % (
            url, type(env).__name__, raw[:120])
    return env, "HTTP %s" % status


def _transport_dead(note: str) -> bool:
    """这个故障是「后端没在那儿」还是「后端答了但答的是坏话」。

    `_get` 成功拿到信封时 note 落成 `HTTP 200/4xx/5xx`；连不上、体子不是 JSON、
    不是信封时 note 是一句人话。**判据就是 note 开不开始于 "HTTP"** ——
    读不到信封 ⇒ 没量成（退出码 3）；拿到信封但 `success:false` ⇒ 后端是活的，
    那是一条**真结论**，该记进 bad（退出码 1）。

    ★ 这个区分不是洁癖：一条 `--parity` 报"对拍失败"却其实是后端没起，
      读到的人会去查数据 —— 而数据一个字都没错。
    """
    return not note.startswith("HTTP")


def _child(argv: list[str]) -> tuple[int, str, str]:
    p = subprocess.run([PY, "-u"] + argv, cwd=str(ROOT), capture_output=True,
                       timeout=_TIMEOUT, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p.returncode, p.stdout or "", p.stderr or ""


def parse_list(text: str) -> tuple[dict, list[str]]:
    """把 `ask.py --list` 的中文文本挖成数。回 `(数, 故障)`。

    ★ 「没挖到」回故障、不回零值：`0 个家族` 与 `这一行我读不懂` 必须分得开。
    """
    fams, traps, entries, aliases, prob = {}, None, None, None, []
    for ln in text.splitlines():
        m = _RE_FAM.match(ln)
        if m:
            fams[m.group(1)] = {"aliases": int(m.group(2)), "runs": int(m.group(3)),
                                "declared_no_anchor": int(m.group(4))}
            continue
        m = _RE_TRAPS.match(ln)
        if m:
            traps = {"traps": int(m.group(1)), "anchored": int(m.group(2)),
                     "human_only": int(m.group(3))}
            continue
        m = _RE_ENTRIES.match(ln)
        if m:
            entries = int(m.group(1))
            continue
        m = _RE_ALIAS.match(ln)
        if m:
            aliases = int(m.group(1))
    if not fams:
        prob.append("`--list` 里一个家族行都没认出来（格式变了？那就改这个脚本，别放过）")
    for name, v in (("陷阱行", traps), ("知识条目行", entries), ("别名行", aliases)):
        if v is None:
            prob.append("`--list` 里没认出%s —— 数不出来 ≠ 是 0" % name)
    return {"families": fams, "traps": traps, "entries": entries, "aliases": aliases}, prob


# ── 模式一：对拍 ──────────────────────────────────────────────────────

def mode_parity(base: str) -> int:
    bad = 0

    # ① 清单
    print("=" * 74 + "\n① 清单：页面 GET /api/kg  vs  CLI `ask.py --list`\n")
    env, note = _get(base, "/api/kg")
    if not env.get("success"):
        # 读不到清单 = **没量成**（不是"量出来对不上"）。两者的退出码必须分开，
        # 否则"后端起没起"会伪装成"对拍失败"，去看对拍结论的人就白查一场。
        raise Unavailable("%s —— %s"
                          % (note, (env.get("error") or {}).get("message", "没有信封")))
    api = env["data"]
    rc, out, err = _child(["kb/ask.py", "--list"])
    if rc != 0:
        print("✗ CLI `--list` 退出码 %s：%s" % (rc, err.strip()[:300]))
        return 1
    txt, prob = parse_list(out)
    for p in prob:
        print("✗ %s" % p)
    bad += len(prob)
    if prob:
        return 1                                    # 量具没接上，后面的数不许当结论

    rows = [
        ("家族数", txt["families"] and len(txt["families"]), api["counts"]["families"]),
        ("陷阱数", txt["traps"]["traps"], api["counts"]["traps"]),
        ("有锚点", txt["traps"]["anchored"], api["counts"]["traps_anchored"]),
        ("只有人记着", txt["traps"]["human_only"], api["counts"]["traps_human_only"]),
        ("知识条目", txt["entries"], api["counts"]["entries"]),
        ("别名", txt["aliases"], api["counts"]["aliases"]),
    ]
    for label, cli_v, api_v in rows:
        good = cli_v == api_v
        bad += 0 if good else 1
        print("  %s %-10s CLI %-5s 页面 %-5s" % ("✓" if good else "✗", label, cli_v, api_v))
    for fid, cli_f in sorted(txt["families"].items()):
        got = next((f for f in api["families"] if f["id"] == fid), None)
        if got is None:
            print("  ✗ 家族 %s：CLI 有，页面没有" % fid)
            bad += 1
            continue
        for k in ("aliases", "runs", "declared_no_anchor"):
            if cli_f[k] != got[k]:
                print("  ✗ 家族 %s 的 %s：CLI %s / 页面 %s" % (fid, k, cli_f[k], got[k]))
                bad += 1
    print("  （尺子：kb %s · gate %s）" % (api["ruler"]["kb_self_sha12"],
                                          api["ruler"]["gate_sha12"]))

    # ② 查询：四类 ＋ 一条夹住的
    print("\n" + "=" * 74 + "\n② 查询：页面 GET /api/kg/ask  vs  照 meta.argv 重跑 CLI\n")
    for q, b, top in CASES + [CLAMP_CASE]:
        label = "q=%s%s  top=%d" % (q, "  building=%s" % b if b else "", top)
        env, note = _get(base, "/api/kg/ask?q=%s&building=%s&top=%d"
                         % (urllib.request.quote(q), b, top))
        if not env.get("success"):
            if _transport_dead(note):
                raise Unavailable("%s —— %s" % (label, note))
            print("  ✗ %s —— %s：%s" % (label, note,
                                        (env.get("error") or {}).get("message", "没有信封")))
            bad += 1
            continue
        page, meta = env["data"], env["meta"]
        # 形状：接口自己报的 argv 必须是那个形状（楼号独立成词、不并进查询串）
        want = ["-u", "kb/ask.py", "--json", "--top", str(meta.get("top"))]
        want += ([b] if b else []) + [q]
        if meta.get("argv", [None] * 2)[1:] != want:
            print("  ✗ %s 的 argv 形状不对：页面报 %r / 应 %r"
                  % (label, (meta.get("argv") or [None])[1:], want))
            bad += 1
        rc, out, err = _child((meta["argv"] or [])[1:])
        if rc != 0:
            print("  ✗ %s：照 argv 重跑退出码 %s：%s" % (label, rc, err.strip()[:200]))
            bad += 1
            continue
        try:
            cli = json.loads(out)
        except json.JSONDecodeError:
            print("  ✗ %s：重跑的 stdout 不是 JSON：%r" % (label, out[:160]))
            bad += 1
            continue
        d = diff(cli, page)
        state = page.get("state")
        extra = []
        if state == "miss" and not page.get("nearest"):
            extra.append("state=miss 却不带 nearest[] —— 「图里没有」不许长得像「没问题」")
        if top > 20 and meta.get("top_clamped_from") != top:
            extra.append("top 被夹了（%s→%s）却没说 —— 悄悄夹住会让调用方以为它要的就是这个数"
                         % (top, meta.get("top")))
        if d or extra:
            bad += 1
            print("  ✗ %s  state=%s" % (label, state))
            for line in (d + extra)[:12]:
                print("      %s" % line)
        else:
            print("  ✓ %-34s state=%-10s 逐字段相同（%d ms）"
                  % (label, state, meta.get("elapsed_ms") or -1))
    # ③ 左栏点一下：**主命中是否是它自己**。
    #
    # ★ 这条判据**被我自己放松过一次、又收回来了**，过程记在这儿（铁律 23 / 24 的形状）：
    #   前一版只问「这个词点亮的节点集里**有没有**它」—— 量出来 **18 / 18 全绿**，
    #   于是"左栏每条都点得亮"当成结论用了。而真值（收严之后同一次实测）：
    #   **14 条陷阱里有 8 条，主命中根本不是它**（`饱和` → 家族 楼层错位、
    #   `代理几何` → 家族 房间骑墙外溢、`一刀切` → 家族 漏墙与糊块…）。
    #   它们**确实在激活集里**，只是引擎把某个家族排在了前面 ——
    #   于是点左栏那一条，中栏画出来的是**另一个节点**的链。
    #   ⇒ 「在激活集里」是**弱档**，它答不了"点了打开的是不是那一条"这个问题。
    #     收严成：`hit_kind` 那一支 ＋ 它的 id 字段（family/trap/entry）**逐字等于**该节点。
    #   ⇒ 弱档的数**照样打印**（别把它藏起来）：两个数并排，"少了多少"才看得见。
    print("\n" + "=" * 74 + "\n③ 左栏：每条 `aka` 点下去，引擎的**主命中**是不是它自己\n")
    targets = ([("pb:" + f["id"], f["title"], f["aka"]) for f in api["families"]]
               + [("trap:" + t["slug"], t["title"], t["aka"]) for t in api["traps"]])
    n_open = n_lit_only = n_noaka = 0
    unopened = []
    for node, title, aka in targets:
        if not aka:
            n_noaka += 1
            print("  · %-46s 没有别名 ⇒ 左栏如实画成不可点（有理由，不是假链接）" % node[:46])
            continue
        word = aka[0]
        env, _ = _get(base, "/api/kg/ask?q=%s&top=3" % urllib.request.quote(word))
        d = env.get("data") or {}
        act = d.get("activated") or []
        lit = any(a.get("node") == node for a in act)
        # 主命中：按 hit_kind 取它那一支的 id 字段（**不用哨兵值**：拼不出来就是 None，
        # 而不是造一个"看着像节点"的字符串 —— 哨兵会被下游当成一个真的键，本仓栽过）。
        primary = primary_node(d)
        if not lit:
            # 点了**没反应**：这一档没有任何借口，直接红。
            bad += 1
            print("  ✗ %s：用别名 %r 点，state=%s、激活集里根本没有它（%s）"
                  % (node, word, d.get("state"), [a.get("node") for a in act]))
        elif primary == node:
            n_open += 1
        else:
            n_lit_only += 1
            # ★ 判红（2026-09-24）：引擎的排序修好之后，这一档已经**没有借口**了 ——
            #   左栏每一条链接都是拿它自己的别名去查的，主命中就必须是它自己。
            #   再出现"开到别处"，就是排序回退了，或者新加的那一条它的别名
            #   被另一个节点抢走了 —— 两种都该当场红，而不是打一行字放过去。
            bad += 1
            unopened.append((node, word, primary, d.get("state")))
    weak = n_open + n_lit_only
    print("  %s 主命中就是自己 %d / %d（**点亮但开到别处** %d，没有别名 %d）"
          % ("✓" if not bad else "✗", n_open, len(targets), n_lit_only, n_noaka))
    print("  · 只看「在不在激活集里」的话：%d / %d —— ★ **这个数不许当「点得准」用**"
          % (weak, weak + n_noaka))
    if n_lit_only:
        print("\n  ★ 打不开自己 %d 条 —— 点下去会画成**别的节点**（不是点了没反应）："
              % n_lit_only)
        for node, word, primary, st in unopened:
            print("      %-38s 用 %-16r → 主命中 %s（state=%s）"
                  % (node[:38], word, primary or "（没有主命中）", st))
        print("    ⇒ 页面**不假装它们点得准**：左栏每条链接都带 `?of=<节点 id>`，")
        print("      打开后主命中若不是它，中栏顶出一条「你点的是 A，引擎打开的是 B」")
        print("      （这一条要单独验 —— 见 `--falsify` 后那段「③ 的判据」）。")
        print("    ⇒ 但页面如实说**不等于**这一档可以被放过：链接本身就是错的。")

    # ★ 条目没有别名，但**条目 id 本身就是查询词**（页面就靠这条把条目做成链接）。
    #   这是量出来的、不是猜的，所以在这儿立成常设判据；哪天它不再成立，页面
    #   那些链接就会变成"点了没反应"的假链接 —— 而这个检查会当场红。
    n_entry = 0
    for e in api["entries"]:
        env, _ = _get(base, "/api/kg/ask?q=%s&top=1" % urllib.request.quote(e["id"]))
        d = env.get("data") or {}
        if d.get("hit_kind") != "entry":
            bad += 1
            print("  ✗ 条目 id %r 查回来是 state=%s kind=%s（页面拿它当链接用）"
                  % (e["id"], d.get("state"), d.get("hit_kind")))
        else:
            n_entry += 1
    print("  %s 条目用 id 直接查得动 %d / %d" % ("✓" if not bad else "✗", n_entry,
                                                len(api["entries"])))
    # ★ 「页面为什么不许把 `trap:<slug>` 前缀拼回去当链接」—— 这件事我**先量错了一次**，
    #   记在这儿免得后人重走：我原先的判据是「逐个量前缀形式点不点得到自己」，
    #   量出来 **14 / 14 全中**，看着是满分 —— 而它**是饱和的，答不了它被派去回答的问题**。
    #   真因（同一次实测）：**裸词 `trap` 一个词就点亮全部 14 条陷阱 ＋ 4 个家族**
    #   （`ask.py` 的别名索引除了手工别名，还从 slug 里自动切词，每条 slug 都带 `trap-`）。
    #   于是任何含 `trap` 三个字母的查询都"点得到自己" —— 这不是解析对了，
    #   是**待检对象整个落进了判据的饱和区**。
    #   ⇒ 判据换成有分辨力的那条：**激活集是不是干净的**（前缀 18 条 vs 别名 3 条），
    #     并把"饱和"这件事本身测出来报出去。
    WORD = "trap"                      # 可能的退化别名
    env, _ = _get(base, "/api/kg/ask?q=%s&top=3" % urllib.request.quote(WORD))
    sat = [a.get("node") for a in ((env.get("data") or {}).get("activated") or [])]
    n_all = len(api["traps"]) + len(api["families"])
    if len(sat) >= len(api["traps"]):
        print("  ★ 判据自曝：裸词 %r 点亮 %d 个节点（含全部 %d 条陷阱）——"
              % (WORD, len(sat), len(api["traps"])))
        print("     所以「前缀形式点得到自己」是**饱和判据**，不许当证据用；"
              "判据改用「激活集干净不干净」。")
    pref_dirty = aka_clean = 0
    for t in api["traps"]:
        slug, aka = t["slug"], (t.get("aka") or [None])[0]
        e1, _ = _get(base, "/api/kg/ask?q=%s&top=3" % urllib.request.quote("trap:" + slug))
        e2, _ = _get(base, "/api/kg/ask?q=%s&top=3" % urllib.request.quote(aka or slug))
        n1 = len((e1.get("data") or {}).get("activated") or [])
        n2 = len((e2.get("data") or {}).get("activated") or [])
        pref_dirty += n1
        aka_clean += n2
    print("  · 同一个陷阱两种点法点亮多少节点（越少越准）："
          "前缀 %d 个/条，别名 %d 个/条 —— 页面用别名（别名由上面 ③ 逐条守着）"
          % (pref_dirty // max(1, len(api["traps"])), aka_clean // max(1, len(api["traps"]))))

    print("\n%s" % ("★ 对拍通过" if not bad else "★ 对拍不通过：%d 处" % bad))
    return 1 if bad else 0


# ── 模式二：证明这套比较能红 ──────────────────────────────────────────

def primary_node(d: dict) -> str | None:
    """载荷的主命中落在哪个节点；`None` = 没有主命中（miss / 只有兜底）。

    ★ 只有**一份**实现：③ 用它判"点得准不准"，刑具也用它证明"判得出来"。
      两份实现的话，刑具绿的是它自己那份，而线上跑的是另一份（本仓栽过）。
    """
    hk = (d or {}).get("hit_kind")
    if hk == "family" and d.get("family"):
        return "pb:" + d["family"]
    if hk == "trap" and d.get("trap"):
        return "trap:" + d["trap"]
    if hk == "entry":
        return d.get("entry") or None
    return None


def mode_falsify() -> int:
    print("=" * 74 + "\n比较器刑具（每种都要求**在那一处**报出来）\n")
    bad = 0
    base = {"state": "hit", "query": "楼层错位", "nearest": [],
            "activated": [{"node": "pb:floor-misalign", "why": "整串精确命中"}]}

    def check(name: str, cli, api, want_path: str) -> None:
        nonlocal bad
        d = diff(cli, api)
        hit = any(line.startswith(want_path) for line in d)
        print("  %s %-28s %s" % ("✓" if hit else "✗", name,
                                 ("⇒ %s" % d[0][:70]) if d else "★ 一条都没报出来"))
        bad += 0 if hit else 1

    # 阴性对照：相同必须回空。回不空 = 比较器自己坏，后面几条都不算数。
    d0 = diff(base, json.loads(json.dumps(base)))
    print("  %s %-28s %s" % ("✓" if not d0 else "✗", "阴性对照（逐字段相同）",
                             "回空" if not d0 else "★ 回了 %d 条：%s" % (len(d0), d0[0])))
    bad += 0 if not d0 else 1

    check("顶层字段变了", base, {**base, "query": "3 楼层错位"}, "$.query")
    check("嵌套列表元素变了", base,
          {**base, "activated": [{"node": "pb:floor-misalign", "why": "词命中"}]},
          "$.activated[0].why")
    check("页面少了嵌套的键", base, {**base, "activated": [{"node": "pb:floor-misalign"}]},
          "$.activated[0].why")
    check("长度不同", base, {**base, "activated": []}, "$.activated：长度")
    check("true 与 1 不许混", {**base, "ok": True}, {**base, "ok": 1}, "$.ok")
    # ★ 反过来的那半：改的是 `query`，差异**不许**指到 `nearest` 头上。
    #   只看"报出来了"不看"报在哪儿"，等于允许它瞎指 —— 瞎指的差异清单没人敢信。
    d1 = diff(base, {**base, "query": "3 楼层错位"})
    off = [x for x in d1 if x.startswith("$.nearest")]
    print("  %s %-28s %s" % ("✓" if not off else "✗", "只报那一处、不许乱指",
                             "差异只有 %d 条、都不在 nearest" % len(d1) if not off
                             else "★ 指到了 $.nearest：%s" % off[0]))
    bad += 0 if not off else 1

    # 文本侧：`--list` 的挖掘器
    print("\n  `--list` 挖掘器：")
    good_txt = ("已知症状家族 1 个：\n"
                "  pb:floor-misalign  楼层错位（别名 17，可跑判据 1，声明无锚点 1）\n"
                "陷阱 14 条：有仓内锚点 12 / 只有人记着 2\n"
                "知识条目 9 篇：a\n别名 345 个（能点亮手册节点 79 个 / 陷阱节点 147 个）\n")
    t, p = parse_list(good_txt)
    ok = (not p and t["families"]["floor-misalign"]["aliases"] == 17 and t["aliases"] == 345)
    print("   %s 正常文本挖得出            ⇒ %s" % ("✓" if ok else "✗", p or "无故障"))
    bad += 0 if ok else 1
    t2, p2 = parse_list(good_txt.replace("别名 345 个", "别名 346 个"))
    print("   ✓ 数字串改了也照挖（差值由调用方报）⇒ 别名=%s" % t2["aliases"])
    bad += 0 if t2["aliases"] == 346 else 1
    t3, p3 = parse_list(good_txt.replace("陷阱 14 条：有仓内锚点 12 / 只有人记着 2\n", ""))
    hit3 = any("陷阱行" in x for x in p3)
    print("   %s 少一行要**硬红**不许当 0     ⇒ %s" % ("✓" if hit3 else "✗", p3 or "无故障"))
    bad += 0 if hit3 else 1
    t4, p4 = parse_list("完全换了一种格式\n")
    hit4 = any("一个家族行都没认出来" in x for x in p4)
    print("   %s 格式整体变了也要硬红         ⇒ %s" % ("✓" if hit4 else "✗", p4 or "无故障"))
    bad += 0 if hit4 else 1

    # ③ 那条判据自己的刑具。
    #
    # ★ 要刑的就是**我犯过的那一次**：只问"在不在激活集里"，于是"开到别处"被读成"点得准"。
    #   下面第一条载荷就是那个缺陷的形状 —— `activated` 里**明明有**它（旧判据会绿），
    #   而 `hit_kind` 指向的是**另一个节点**（新判据必须红）。
    #   一个刑具如果不能把"我修掉的那个错"判红，它证明的是别的东西（memory: verifier-needs-its-falsifier）。
    print("\n  ③ 的判据（主命中 vs 只是被点亮）：")
    TRAP = "trap:saturated-criterion"
    FAM = "pb:floor-misalign"
    cases = [
        # (名字, 载荷, 节点, 期望 primary_node 是否等于该节点)
        ("激活集里有它、主命中却是别的（就是那个缺陷）",
         {"hit_kind": "family", "family": "floor-misalign",
          "activated": [{"node": TRAP}, {"node": FAM}]}, TRAP, False),
        ("主命中真是它自己", {"hit_kind": "trap", "trap": "saturated-criterion"}, TRAP, True),
        ("同一份载荷、拿家族当目标就该算准", {"hit_kind": "family", "family": "floor-misalign"}, FAM, True),
        ("miss 没有主命中", {"hit_kind": None, "state": "miss"}, TRAP, False),
        ("条目那一支", {"hit_kind": "entry", "entry": "图线-线型-线宽"}, "图线-线型-线宽", True),
    ]
    for name, payload, node, want in cases:
        got = (primary_node(payload) == node)
        print("   %s %-38s ⇒ 主命中 %s（判%s）" % ("✓" if got == want else "✗", name[:38],
                                                 primary_node(payload) or "无",
                                                 "准" if got else "不准"))
        bad += 0 if got == want else 1
    print("   ✓ 第 1 条是**阴性对照的反面**：旧判据在它上面全绿 —— 证明这条判据有分辨力")

    print("\n%s" % ("★ 刑具全部按预期报出来" if not bad else "★ 有 %d 条刑具没报出来" % bad))
    return 1 if bad else 0


_MODES = ("--parity", "--falsify", "--shapes", "--walk")


# ── 模式三：形状普查 —— 每一条能查到的说法，载荷里有没有页面画不出来的字段 ──
#
# ★ 这一节是被**实测**逼出来的，两个缺陷都是它先发现的，而不是我想到的：
#   · 逐条走完 29 个节点（4 家族 + 14 陷阱 + 9 条目 + 1 miss + 1 带楼号）才发现
#     **6 条陷阱直接白屏**（`(items || []).map is not a function`）；
#   · 9 篇知识条目每篇都在页面上写「还有 3 个字段本页没画」。
#   ★ 而我先前**只走"每态一条"**（4 条）时，这两件**一件都没报出来** ——
#     一次抽样在屏幕上是"全绿"。这就是本仓那条老话的又一例：
#     **判据全绿先问它是不是在全部样本上都取极值**（memory: saturated-criterion-…）。
#
# 页面自己就有这杆秤（`leftoverBlock` 会报「还有 N 个字段本页没画」），
# 缺的只是**有人把每一条都走一遍**。这个模式就是那个"有人"：不需要浏览器，
# 它读 `kg.js` 里那两个**静态字面量**（`ORDER` / `DRAWN`）与真实载荷逐条对。
#
# ★ 解析失败**必须硬红**：正则没命中就返回空集合的话，每个字段都会被报成"没画"
#   （满屏假红）或者反过来恒绿 —— 两种都是"量具坏了长得像结论"。所以下面既查
#   "解析出来的键够不够多"，也查"这次到底走过了几支"。
_JS = ROOT / "frontend" / "admin" / "js" / "views" / "kg.js"


def _api_inventory(base: str) -> dict:
    """取页面左栏读的那一份清单。失败**硬停** —— 拿空清单继续量等于量了个寂寞。

    ★ 抛 `Unavailable` 而**不是** `SystemExit`：这两件事要能分开，
      而且分开的地方只该有一处（`main()`）——
      否则每加一个模式就多一次「该回 1 还是该回 3」的临场判断。
    """
    env, note = _get(base, "/api/kg")
    if not env.get("success"):
        raise Unavailable("★ 读不到 %s/api/kg：%s" % (base, note))
    return env["data"]


def _js_keys(name: str) -> tuple[set[str], bool]:
    """从 `kg.js` 的字面量里读出被画/被排序的键名。返回 (键集合, 是否用了 ...ORDER)。"""
    src = _JS.read_text(encoding="utf-8")
    # 先丢掉整行注释：注释里出现引号会把键名污染成假键（铁律 23：grep 数的是文本事实）
    body = "\n".join(l for l in src.split("\n") if not l.strip().startswith("//"))
    pat = (r"const ORDER = \[(.*?)\];" if name == "ORDER"
           else r"const DRAWN = new Set\(\[(.*?)\]\);")
    m = re.search(pat, body, re.S)
    if not m:
        raise SystemExit("★ 读不出 kg.js 的 %s 字面量 —— 它改了写法？"
                         "这条判据宁可停在这儿，也不许拿空集合继续量。" % name)
    return set(re.findall(r"'([^']+)'", m.group(1))), "...ORDER" in m.group(1)


def mode_shapes(base: str) -> int:
    api = _api_inventory(base)
    words: list[tuple[str, str]] = []          # (说法, 说明)
    for f in api["families"]:
        if f.get("aka"):
            words.append((f["aka"][0], "家族 %s" % f.get("id")))
    for t in api["traps"]:
        if t.get("aka"):
            words.append((t["aka"][0], "陷阱 %s" % t.get("slug")))
    for e in api["entries"]:
        words.append((e["id"], "条目 %s" % e["id"]))
    for q, b, _ in CASES:                      # miss 那一支必须走到，它有自己的字段
        words.append(((b + " " + q) if b else q, "对拍用例"))
    # 说法去重（条目 id 与家族别名不会撞，但用例可能重复）
    seen, uniq = set(), []
    for w, why in words:
        if w not in seen:
            seen.add(w)
            uniq.append((w, why))

    drawn, spread = _js_keys("DRAWN")
    order, _ = _js_keys("ORDER")
    if not spread:
        raise SystemExit("★ kg.js 的 DRAWN 不再用 ...ORDER 展开 —— 请先核它对不对，"
                         "再改这个脚本。")
    handled = drawn | order
    if len(handled) < 20:
        raise SystemExit("★ 只读出 %d 个键，明显没解析对 ⇒ 不许据此下结论。" % len(handled))

    print("页面声明画得出来的键：%d 个（ORDER %d ＋ DRAWN %d）\n" % (len(handled), len(order), len(drawn)))
    print("逐条走：")
    branches: dict[tuple, int] = {}
    allkeys: set[str] = set()
    miss: list[tuple[str, str, list[str]]] = []
    for w, why in uniq:
        env, _ = _get(base, "/api/kg/ask?q=%s&top=3" % urllib.request.quote(w))
        d = (env.get("data") or {})
        if not d:
            miss.append((w, why, ["接口没给 data"]))
            continue
        keys = set(d)
        allkeys |= keys
        br = (d.get("state"), d.get("hit_kind"))
        branches[br] = branches.get(br, 0) + 1
        gone = sorted(k for k in keys if k not in handled)
        if gone:
            miss.append((w, why, gone))

    print("  走过 %d 条说法，共 %d 个字段，落在 %d 支上：%s"
          % (len(uniq), len(allkeys),
             len(branches),
             "、".join("%s/%s×%d" % (k[0], k[1], v) for k, v in sorted(branches.items(), key=str))))
    if len(branches) < 4:
        print("  ✗ 只走到 %d 支 —— 四个分支（家族 / 陷阱 / 条目 / miss）必须都走到，"
              "否则这一轮的'全画得出'是**没走到**，不是没问题" % len(branches))
        return 1
    if miss:
        print("  ✗ %d 条说法有页面画不出来的字段（页面会把它塞进「还有 N 个字段本页没画」）："
              % len(miss))
        for w, why, gone in miss[:25]:
            print("      %-26s %-28s %s" % (w[:26], why[:28], "、".join(gone)))
        print("\n★ 形状普查不通过：%d 处" % len(miss))
        return 1
    print("  ✓ 每条说法的每个字段，页面都声明画得出来（0 处漏画）")
    print("\n★ 形状普查通过")
    return 0



# ── 模式四：渲染走查 —— 每一条说法在**浏览器里**画出来了吗 ────────────────
#
# ★ 为什么非要有这一支（前两支都盖不住它）：
#   `--parity` 比的是 **JSON**，`--shapes` 比的是**页面声明的键名**。两样都不是"画出来了"。
#   实测（2026-09-24）：`mechanism` 在陷阱载荷里是**一段散文**，而渲染器把它喂给了列表那一支
#   ⇒ 查任何一条陷阱，整页只剩「视图加载失败 / (items || []).map is not a function」。
#   而 `--shapes` 是**绿的** —— 它只看键在不在 DRAWN 里，看不见**值的形状**。
#   ⇒ 一个键名对得上、值形状对不上的载荷，会安静地白屏。只有真跑一遍浏览器才知道。
#
# ★ 走法要**走全**，不许抽样：先前只走"每态一条"（4 条）时，6 条陷阱白屏**一条都没报出来**。
#   一次抽样在屏幕上是全绿（memory: saturated-criterion-has-no-resolution）。
#
# ★ 导航用 `location.hash = …` 而**不是** `page.goto(…)`：这是**页面自己的**跳转方式
#   （搜索框就这么干），会走 `hashchange → route → render` 这条真路。
#   而且 `page.goto('#/kg/x')` 是**同文档跳转**，浏览器**不会重新 import 模块** ——
#   上一版我用它，于是改了 `kg.js` 之后量到的还是**旧模块**，白跑两轮（铁律 24 同族）。
#: 注入页面一次的跳转器。**抽出来是因为要跳上百次**，而每次重新写一遍等待逻辑
#: 就是每次重新给"多久算画完了"下赌注 —— 同一个赌注写两遍，必然只有一份跟着 bug 修。
#:
#: ★ `data-walk` 那一手是**去竞态**的，不是保险丝：
#:   `location.hash = h` 到 `hashchange` 处理函数跑起来之间，**旧的那一栏还在 DOM 里**。
#:   只等「`.kg-mid` 存在且有字」的话，可能在**上一问的页面上**取样并判绿 ——
#:   而那个绿是"上一个节点画得对"，与当前节点无关。给旧的那一栏盖个戳，
#:   等一个**没有戳**的新栏（`mount()` 每次都新建元素，戳不会遗传）。
#:
#: ★ 同时盯 panic，而且是**边等边盯**（实测逼出来的，见下）：
#:   渲染抛错时 `.kg-mid` **永远不会出现** —— 异常穿出 `paint()`，被**路由层**的 catch
#:   接住，由 `app.js:142 paintPanic()` 挂进 `#main`，而 `.kg-mid` 是 `paint()` 内部的节点。
#:   于是"只等中栏"的探针每个坏节点都要**等满 10 秒**（实测 14 条陷阱 = 6 分 10 秒），
#:   更糟的是报出来的理由是「等了 10 秒也没画出中栏」—— **跪对了，理由说错了**，
#:   而真正的原因（`(items || []).map is not a function`）就印在屏幕上那个 panic 里。
#:   这和先前 miss 那一支我要求 `.kg-title` 是**同一形状的错**：结论对，指的原因不对。
#:
#: ★ 选择器里那个 `.chk-panic` 我是**先猜错了一次**才写上的：第一版只盯 `.kg-panic`
#:   （`kg.js` 自己的类），结果 14 条陷阱全报"也没有 panic" —— 因为跨视图那个兜底
#:   用的是 `chk-` 前缀的类（`app.js` 的 `paintPanic`）。**"没找到"和"不存在"
#:   又一次长得一样**（铁律 16），所以这里把三样都列上，少一样都可能漏掉一种死法。
WALK_JS = """
window.__walkTo = async (hash) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  for (const el of document.querySelectorAll('.kg-mid, .kg-panic, .chk-panic')) {
    el.setAttribute('data-walk', '1');
  }
  location.hash = hash;
  for (let i = 0; i < 200; i++) {
    await sleep(50);
    const p = document.querySelector('.chk-panic, .kg-panic');
    if (p && !p.hasAttribute('data-walk')) {
      return { panic: (p.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200) };
    }
    const m = document.querySelector('.kg-mid');
    if (m && !m.hasAttribute('data-walk') && (m.textContent || '').length) {
      await sleep(80);                    // 再放一拍：中栏画完时右栏可能还在路上
      return { ok: true };
    }
  }
  return { timeout: true };
};
"""


def mode_walk(base: str) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:                       # noqa: BLE001
        # ★ 量不了**不许**当通过：`ImportError` 与"全画得出来"在屏幕上长得一样。
        # 但**也不许**和"量出来是坏的"共用一个退出码 ——
        # 「这一条没量成」与「这一条量出来是坏的」要能被人从退出码上分开
        # （本仓 `findings.Status` 里 `UNAVAILABLE ≠ FAIL` 就是这个道理）。
        print("  ✗ 没装 playwright ⇒ **这一条没量成**（不是通过）：%s" % exc)
        print("      装法：pip install playwright && playwright install chromium")
        return 3

    try:
        inv = _api_inventory(base)
    except Unavailable as exc:                     # 后端起不来 —— 同样是"没量成"
        print("  ✗ %s" % exc)
        return 3
    targets = []
    for f in inv.get("families") or []:
        if f.get("aka"):
            targets.append(("fam", "pb:" + f["id"], f["aka"][0]))
    for t in inv.get("traps") or []:
        if t.get("aka"):
            targets.append(("trap", "trap:" + t["slug"], t["aka"][0]))
    for e in inv.get("entries") or []:
        targets.append(("entry", e["id"], e["id"]))
    # miss 那一支复用 CASES 里那个词 —— 换个词就是换了待检对象，
    # 而两支用不同的词会让"对拍绿 / 走查红"变成无法解释的分歧。
    targets.append(("miss", None, CASES[3][0]))
    targets.append(("scoped", "pb:floor-misalign", CASES[1][1] + " " + CASES[1][0]))

    print("逐条走 %d 个节点（家族 / 陷阱 / 条目 / miss / 带楼号）…" % len(targets))
    bad, seen = [], {}
    with sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception as exc:                   # noqa: BLE001
            print("  ✗ 浏览器起不来 ⇒ **这一条没量成**（不是通过）：%s" % exc)
            print("      装法：playwright install chromium")
            return 3
        page = br.new_page()          # 新上下文 = 空缓存 ⇒ 模块一定是重新取的
        page.add_init_script(WALK_JS)
        # 一次加载，之后全靠 hash 跳 —— 与用户点链接的路径逐字相同。
        # ★ 「改过 kg.js 要拿到新模块」这件事，靠的是**这里的 `br.new_page()`（空缓存）**，
        #   不是下面那个 `?b=`。我先前把 `?b=` 写成"破缓存"，那是错的：
        #   文档 URL 上的查询串**不会**传给 ES 模块 —— 模块的导入说明符是按**模块自己**
        #   的 URL 解析的，与文档的查询串无关。`?b=` 留着只当"这次是第几跑"的记号。
        #   真正踩过的坑是**同文档跳转**：`page.goto('#/kg/x')` 或复用同一个 page
        #   连跳两次，都不会重新 import，于是量到的是**上一个版本的模块**（铁律 24 同族）。
        page.goto("%s/?b=%d#/kg/%s" % (base, time.time_ns() % 100000,
                                       _quote(targets[0][2])),
                  wait_until="domcontentloaded")
        page.wait_for_selector(".kg-mid", timeout=20000)
        for kind, node, word in targets:
            of = ("?of=%s" % _quote(node)) if node else ""
            got = page.evaluate(
                """async ([hash]) => {
                     const r = await window.__walkTo(hash);
                     if (r.panic) return { panicText: r.panic };
                     if (r.timeout) return { dead: true };
                     const mid = document.querySelector('.kg-mid');
                     return {
                       dead: false, panicText: null,
                       text: mid.textContent,
                       banner: mid.querySelectorAll('.kg-banner').length,
                       body: document.body.textContent || '',
                       title: (document.querySelector('.kg-title') || {}).textContent || '',
                     };
                   }""",
                ["#/kg/%s%s" % (_quote(word), of)])
            why = []
            # ★ 三种返回**互斥**，所以统一用 `.get` 读：少一个键时是"这一支没走"，
            #   而 `got["dead"]` 会当场抛 KeyError —— 量具自己把结论崩掉，
            #   屏幕上是一段 traceback，不是"哪一条坏了"（我写这段时就先崩了一次）。
            if got.get("panicText"):
                why.append("渲染抛错：%s" % got["panicText"][:110])
            elif got.get("dead"):
                why.append("等了 10 秒也没画出中栏，也没有 panic")
            else:
                if len(got["text"]) < 300:
                    why.append("中栏只有 %d 字" % len(got["text"]))
                if not got["banner"] and kind != "miss":
                    why.append("没有三态横幅")
                if re.search(r"items \|\| \[\]\)\.map|视图加载失败|is not a function",
                             got["body"]):
                    why.append("渲染抛错")
                left = re.findall(r"还有 \d+ 个字段本页没画", got["body"])
                if left:
                    why.append(left[0])
            seen[kind] = seen.get(kind, 0) + 1
            tag = "✓" if not why else "✗"
            print("  %s %-6s %-22s %s" % (tag, kind, word[:22],
                                          got.get("title", "")[:30] if not why
                                          else "；".join(why)))
            if why:
                bad.append((kind, word, why))

        # 两个对照：**点得准就不许说话，故意指错就必须喊** —— 只测一面的话，
        # `intentBlock` 写成 `return null`（永远不说）或 `return div`（永远说）都能绿。
        print("\n  intentBlock 两个方向：")
        ctl = page.evaluate(
            """async ([ok, wrong]) => {
                 const count = () => document.querySelectorAll('.kg-intent').length;
                 await window.__walkTo(ok);
                 const quiet = count();
                 await window.__walkTo(wrong);
                 const loud = count();
                 const txt = (document.querySelector('.kg-intent') || {}).textContent || '';
                 return { quiet, loud, txt: txt.replace(/\\s+/g, ' ').slice(0, 90) };
               }""",
            ["#/kg/%s?of=%s" % (_quote("楼层错位"), _quote("pb:floor-misalign")),
             "#/kg/%s?of=%s" % (_quote("楼层错位"),
                                _quote("trap:trap-grep-counts-comments-as-code"))])
        ok_first = ctl["quiet"] == 0
        ok_second = ctl["loud"] >= 1
        print("   %s 点得准 ⇒ 一个字都不说（实得 %d 条）"
              % ("✓" if ok_first else "✗", ctl["quiet"]))
        print("   %s 故意指错 ⇒ 必须喊出来（实得 %d 条：%s）"
              % ("✓" if ok_second else "✗", ctl["loud"],
                 ctl["txt"][:60] if ctl["loud"] else "—"))
        if not (ok_first and ok_second):
            bad.append(("intentBlock", "对照", ["说不说话的方向反了"]))
        page.close()
        br.close()

    need = {"fam", "trap", "entry", "miss"}
    if not need <= set(seen):
        print("\n  ✗ 只走到 %s —— 四支必须都走到，否则'全画得出'是**没走到**"
              % sorted(seen))
        return 1
    if bad:
        print("\n★ 渲染走查不通过：%d 处" % len(bad))
        for kind, word, why in bad[:20]:
            print("   %-6s %-22s %s" % (kind, word[:22], "；".join(why)))
        return 1
    print("\n★ 渲染走查通过：%d 个节点，支数 %s，0 处白屏/漏画"
          % (len(targets), "、".join("%s×%d" % (k, v) for k, v in sorted(seen.items()))))
    return 0


def main(argv: list[str]) -> int:
    """手解析 argv：**本仓不认 `--help`**（它会被当成查询词/楼号，见铁律 9）。

    退出码：`0` 量过且通过 ｜ `1` 量过且不通过 ｜ `2` 参数不对 ｜
    `3` **没量成**（后端起不来 / 没装 playwright / 浏览器起不来）。
    ★ 后两档必须分开：把"没量成"混进"不通过"里，本仓栽过不止一次。
    """
    try:
        return _dispatch(argv)
    except Unavailable as exc:
        print("✗ 没量成：%s" % exc, file=sys.stderr)
        return 3


def _dispatch(argv: list[str]) -> int:
    base, mode, i = DEFAULT_BASE, "--parity", 0
    while i < len(argv):
        a = argv[i]
        if a in _MODES:
            mode = a
        elif a == "--base":
            if i + 1 >= len(argv):
                print("--base 后面要跟一个 URL", file=sys.stderr)
                return 2
            base, i = argv[i + 1], i + 1
        elif a.startswith("--base="):
            base = a.split("=", 1)[1]
        else:
            print("只认 --parity / --falsify / --shapes / --walk / --base URL / --base=URL"
                  "（本仓不认 --help，见铁律 9）", file=sys.stderr)
            return 2
        i += 1
    if mode == "--falsify":
        return mode_falsify()
    print("基址 %s" % base)
    if mode == "--shapes":
        return mode_shapes(base)
    if mode == "--walk":
        return mode_walk(base)
    return mode_parity(base)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
