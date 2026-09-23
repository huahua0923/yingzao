# -*- coding: utf-8 -*-
"""A 层检查 —— **只要标准库**，因此只服务模式（服务器上没有 ezdxf/shapely）也能跑。

这不是"顺手做轻一点"，是硬要求：后台如果"因为装不起依赖所以什么都不检查"，
那它就是个展示框，不是检查。凡是够便宜的判据都放这一层。

每条检查的签名统一：`check_xx(rep, data_dir, name, timeout_s=...)`，
自己把 Finding 挂到 rep 上。**不许 raise** —— 崩了由 __init__ 兜成 UNAVAILABLE。

判据要用的"外部数"（图纸自己写的建筑面积/房间数）不从外面传进来，走
`sources.py` 读引擎自己产出的产物 —— 判据只认盘上的件，换个进程、换一天、
没人看着都得出同一结论（用户明令："不是随时问智能体"）。
"""
from __future__ import annotations

import ast
import json
import os
import re
import warnings
from collections import Counter
from pathlib import Path

from .findings import Finding, Report, Status, unavailable
from .layout import building_dir, floor_files

# ── 原始数据读取（这层不 import 任何建模模块）─────────────────────



def _json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        # 空/截断的 JSON 是真实故障（原子写之前 json.dump 直写会留 0 字节）。
        # 用哨兵区分"文件不在"和"文件坏了" —— 否则又是"量具坏了和对象是空的
        # 长得一样"（CLAUDE.md 铁律 16）。
        return _CORRUPT


_CORRUPT = object()


def _ledger(data_dir, name: str):
    """读台账。None = 读不出（文件不在/坏了）；[] = 真的 0 间。

    ★ 两者必须分开："读不出"和"真的没有"在屏幕上长得一模一样
    （铁律 16）。
    """
    rp = building_dir(data_dir, name) / "rooms.json"
    if not rp.exists():
        return None
    rooms = _json(rp)
    if rooms is _CORRUPT or not isinstance(rooms, list):
        return None
    return rooms




def _repo_root(data_dir) -> Path:
    """本仓根目录。

    ★ 从**本模块**的位置推，不从 data_dir 推。A6/A8 读的是**正在跑的这套代码**
    （ID_BASE 白名单、各加载器源码），它跟"数据放在哪个盘"没有任何关系。
    早先按 `data_dir` 的父目录推，后果是：把数据目录挪到别处、或拿临时夹具目录
    跑一遍，这两条就静默退回「读不到 ⇒ UNAVAILABLE」—— 该亮的闸门不亮了，
    而屏幕上只看得出"没量到"，看不出"量错了地方"（CLAUDE.md 铁律 16）。
    data_dir 那条路只作兜底（万一 backend/ 被拆走单独部署）。
    """
    mine = Path(__file__).resolve().parents[2]
    if (mine / _ID_BASE_SRC).is_file():
        return mine
    return Path(data_dir).resolve().parent


_ID_BASE_SRC = Path("backend") / "extract" / "extract_rooms_generic.py"


# ── A1 房间台账非空 ──────────────────────────────────────────────

def check_a1(rep: Report, data_dir, name: str, **_kw) -> None:
    """有 profile 却没有一间房。

    ★ 这条是 2026-09-23 全库量出来的：当时 95 栋里 **45 栋** rooms.json 是 `[]`。
    ★ 现况（2026-09-24 凌晨复量）：**22 栋**，其中 **18 栋**不在 `ID_BASE` 名单里
      （A6 同数）。差的 23 栋是 09-23 夜补名单补进去的 —— 所以**别把 45 当现况读**：
      本文件里这个数是**历史测量**，要现况就跑 A1/A6，引擎自己会数。
      （留这条痕是因为"45→22"正好证明了根因判断是对的：缺的是名单不是识别能力。）
    根因不是识别失败，是**名单**：`extract_rooms_generic.ID_BASE` 里没有它们，
    于是 run() 一次都没为它们跑过。此前一直被当成"识别不行"，
    其实是"压根没进过流程"。
    ★ 别在这条里举具体楼号当例子 —— 本文件写完当天就栽过：曾写"c113 就是其中一栋"，
      而 c113 的实际台账有 134 行、A6 也报"在表里"。名单是会变的（补登一栋就变），
      把楼号写进判据的说明里，**说明书会先于代码过期**。

    判据写成"台账为空 ⇒ GAP"而不是"台账为空 ⇒ WARN"，因为交付出去就是
    **0 间房**，而图纸上写着 21/36/23/… 间。这不是"可能有问题"，是确定的缺口。
    """
    d = building_dir(data_dir, name)
    prof = _json(d / "profile.json")
    if prof is _CORRUPT:
        rep.add(Finding("A1", "房间台账非空", Status.UNAVAILABLE,
                        "profile.json 解析失败（文件在但读不出）",
                        measure="房间条数", blocked_by="artifact_corrupt"))
        return
    rp = d / "rooms.json"
    if not rp.exists():
        rep.add(Finding("A1", "房间台账非空", Status.GAP,
                        "有 profile.json 却**没有 rooms.json** —— 交付 0 间房",
                        measure="房间条数", evidence={"rooms_json": None}))
        return
    rooms = _json(rp)
    if rooms is _CORRUPT:
        rep.add(Finding("A1", "房间台账非空", Status.GAP,
                        "rooms.json 解析失败（文件在但读不出；常见于非原子写被中断）",
                        measure="房间条数", evidence={"bytes": rp.stat().st_size}))
        return
    n = len(rooms) if isinstance(rooms, list) else 0
    if n == 0:
        # ★ 别把"根因是什么"留给读的人自己猜：A6 的白名单是**能自己查的**，
        #   查了再说话 —— 绝大多数就是这一条（2026-09-23 实测：A1 亮 45 栋、
        #   A6 亮 45 栋，**是同一批楼**；2026-09-24 复量为 22 栋 / 18 栋，
        #   差值来自当夜补名单。**两个数都是历史测量，现况请看本条的输出**）。
        #   写成"先查…"等于把一件已经量得出来的事推给人
        #   （memory: one-judgement-many-implementations）。
        why = "先查该楼号是否在 extract_rooms_generic.ID_BASE 里（见 A6）"
        ev = {"rooms": 0, "rooms_json_bytes": rp.stat().st_size}
        try:
            table = _read_id_base(_repo_root(data_dir) / _ID_BASE_SRC)
        except Exception:                                # noqa: BLE001
            table = None
        if table is not None:
            ev["in_id_base"] = name in table
            if name not in table:
                why = ("**根因已定位**：%s 不在 ID_BASE 白名单里（A6 同因）—— "
                       "房间抽取整条链一次都没为它跑过，所以台账必是空的。"
                       "修法不是重跑识别，是先把它登进白名单" % name)
        rep.add(Finding("A1", "房间台账非空", Status.GAP,
                        "rooms.json = [] —— 交付 0 间房。" + why,
                        measure="房间条数", evidence=ev))
        return
    per: dict[int, int] = {}
    for r in rooms:
        per[r.get("floor")] = per.get(r.get("floor"), 0) + 1
    rep.add(Finding("A1", "房间台账非空", Status.PASS, "台账 %d 间" % n,
                    measure="房间条数",
                    evidence={"rooms": n,
                              "per_floor": {str(k): v for k, v in sorted(
                                  per.items(), key=lambda kv: (kv[0] is None, kv[0]))}}))


# ── A6 房间号段白名单成员 ────────────────────────────────────────

def check_a6(rep: Report, data_dir, name: str, **_kw) -> None:
    """该楼号在不在 `ID_BASE` 里 —— 房间抽取整条链的总闸门。

    实现：用 `ast` **静态读** `extract_rooms_generic.py` 里的 `ID_BASE` 字面量，
    不 import 那个模块。理由：它 import ezdxf，一 import 就把本条检查踢出 A 层
    （服务器上跑不了），而这条恰恰是**最该在服务器上也亮着**的那一条。
    ast 读的是**真源码**，不是抄来的副本 —— 不存在"两处一致一起错"。
    """
    d = building_dir(data_dir, name)
    if not (d / "profile.json").is_file():
        rep.add(Finding("A6", "房间号段白名单成员", Status.NOT_APPLICABLE,
                        "没有 profile.json，不是建模楼", measure="名单成员"))
        return
    src = _repo_root(data_dir) / _ID_BASE_SRC
    try:
        table = _read_id_base(src)
    except Exception as ex:                            # noqa: BLE001
        rep.add(unavailable("A6", "房间号段白名单成员",
                            "读不到 ID_BASE（%s: %s）" % (type(ex).__name__, ex),
                            measure="名单成员"))
        return
    if table is None:
        rep.add(unavailable("A6", "房间号段白名单成员",
                            "ID_BASE 在源码里找不到（可能改名/挪走了）",
                            measure="名单成员"))
        return
    in_table = name in table
    rep.add(Finding("A6", "房间号段白名单成员",
                    Status.PASS if in_table else Status.GAP,
                    ("在表里，号段 id 基数=%d" % table[name]) if in_table else
                    "**不在 ID_BASE** ⇒ 房间抽取不会为它跑，交付必是 0 间房"
                    "（与 A1 是同一条根因的两端）",
                    measure="名单成员",
                    evidence={"in_id_base": in_table, "id_base_size": len(table)}))


def _read_id_base(src: Path) -> dict | None:
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "ID_BASE":
                    return ast.literal_eval(node.value)
    return None


# ── A3 交付楼层 rooms 快照与台账一致 ─────────────────────────────

def _a3_kind(got, exp) -> str:
    """对不上的"方向" —— 只是**往哪边看**的线索，不是"该跑哪个脚本"。"""
    if got is None:
        return "corrupt"
    if exp == 0:
        return "ledger-missing"
    if got == 0:
        return "snapshot-empty"
    return "file-ahead" if got > exp else "file-behind"


# 每种方向给的是"去查什么"。★ 措辞刻意**不写"就跑 backfill"** ——
# backfill 的动作是"以台账为准覆盖快照"，它只在**台账是权威**时才正确；
# 台账若不是权威，跑它就是用旧的盖新的。哪一种？要看下面那把独立量具。
_A3_KIND = {
    "file-behind": "文件比台账少：可能是台账改过而快照没跟上（该补跑），"
                   "也可能是台账里那一层是旧账（不该补跑）—— 见下面的『层号自证』。"
                   "★ 还有第三种，它让补跑变成**空操作**：台账里那些房间**几何上就"
                   "进不来**。回填是以本层轮廓为准注入的（`o.contains(房间质心)` 不过"
                   "就 `continue`），放不进就是『回填 0 间』—— 屏幕上与『没有可回填的』"
                   "长得一模一样。这一档 A 层量不了（本层只要标准库，没有多边形库），"
                   "判定要用回填器**自己**的模拟（别照这话写第二把尺）："
                   "`python backend/extract/backfill_floor_rooms.py <该栋> --verify`"
                   " ——它分三档报『轮廓空 / 边界退化 / 质心在轮廓外』，"
                   "三个数只要有一个非零，就不是『快照旧了』",
    "file-ahead": "文件比台账**多**：快照里有台账不知道的房间。跑 backfill 会用台账"
                  "**覆盖**掉它们，先查台账那一行是不是陈旧的汇总行、"
                  "或快照是不是从别层复制的（c104 F4 那类）",
    "snapshot-empty": "快照是空数组而台账有：要么快照从没建过（该补跑），"
                      "要么**台账那一行是废的**（c006 实测）—— 数字上长得一样，"
                      "必须看台账那一行的内容才能定",
    "ledger-missing": "台账里没有这一层的行 ⇒ 台账缺层，backfill 修不了，要补台账",
    "corrupt": "楼层 JSON 读不出来（0 字节/截断）⇒ 重出这一层",
}

# 房号里嵌着层号（memory: rooms-number-embeds-floor-no-crossfloor-match）：
# `6-A-05-00` = 6 栋 A 区 5 层 00 号。第三段就是它**自称**的层。
_NUM_FLOOR_RE = re.compile(r"^[^-]+-[^-]+-(\d{1,2})-")


def _number_floor(number) -> int | None:
    """从房号里读出它自称的层；读不出返回 None（不同栋命名法不同，读不出不算错）。"""
    if not isinstance(number, str):
        return None
    m = _NUM_FLOOR_RE.match(number.strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _ledger_floor_witness(rooms: list) -> dict:
    """台账的『层号自证』：把每行 `floor` 字段与它**自己房号里嵌的层号**比一比。

    ★ 这是本判据缺的第二把、**独立于计数**的量具：光比"文件几间/台账几间"
    判不出哪一边旧 —— 两个数字对不上，可能是文件旧也可能是台账旧，
    屏幕上完全一样（铁律 16 的同族：量具分不清的两种情形长得一模一样）。
    房号是自己写的，所以能当独立证人。

    ★★ 但**绝对层号差不是缺陷，是约定** —— 这一版差一点就栽在这：
    我第一版写成"层号与房号不符 ⇒ 台账是旧账"，然后实测发现
    **全库 12 个能解析的栋，模态偏移全是 +1，没有一个 0**
    （floor 字段 0 基，房号段 1 基：floor=4 ↔ `6-A-05-xx`）。
    于是那条判据会在 12 栋上全红、且**一例真缺陷都抓不到** ——
    又一个"拿代理量（绝对差≠0）代替真对象（偏离本栋自己的约定）"。
    正确的对象是：**偏离本栋模态偏移的那些行**。约定不判，偏离才判。

    返回 parsed / modal / anomaly（偏离模态偏移的行）。parsed<5 时
    `applicable=False`：这栋房号不含层，本量具**明说自己没量到**，
    不冒充分数（memory: gauge-coverage-invisible-in-summary）。
    """
    offsets: dict[int, int] = {}
    rows: list[tuple[int, int, dict]] = []
    for r in rooms:
        nf = _number_floor(r.get("number"))
        F = r.get("floor")
        if nf is None or not isinstance(F, int):
            continue
        off = nf - F
        offsets[off] = offsets.get(off, 0) + 1
        rows.append((F, off, r))
    parsed = len(rows)
    if parsed == 0:
        return {"applicable": False, "parsed": 0, "modal": None, "anomaly": []}
    # ★ 平手时取**较小**的偏移：全库实测模态恒为 +1，平手取 min 更稳，
    #   而且 tie 只在样本极少时出现（那种情况下 applicable 本来就会是 False）。
    modal = min((k for k, v in offsets.items() if v == max(offsets.values())))
    anomaly = [{"floor": F, "number": r.get("number"), "offset": off}
               for F, off, r in rows if off != modal]
    # ★ anomaly **不截断**：调用方要按 floor 查"这一层的台账行可不可疑"，
    #   截断过就会把某一层判成干净的 —— 正是"安静地漏掉"那类坑。
    #   要收缩体积在**写 evidence 时**收缩，不在量的这一端收缩。
    return {"applicable": parsed >= 5, "parsed": parsed, "modal": modal,
            "offset_hist": dict(sorted(offsets.items(), key=lambda kv: -kv[1])),
            "anomaly_n": len(anomaly), "anomaly": anomaly}


def check_a3(rep: Report, data_dir, name: str, **_kw) -> None:
    """`floors/floorN.json` 的 `rooms[]` 是**快照**，不是台账。

    台账改了（rooms.json）而没补跑 `backfill_floor_rooms.py`，楼层文件里就还是
    旧的那一份 —— 两个地方写着同一个事实，谁都不报错。
    这正是"两份写法会互相盖"那一族坑；判据是**逐层点数**，不是"看起来差不多"。

    ★ 但对不上**不等于"该跑 backfill"** —— 哪一边旧要看方向，而方向决定修法：
      · 文件 < 台账：台账改过、快照没跟上 ⇒ 补跑 backfill（这是"正常"的一边旧）。
      · 文件 > 台账：快照里**有台账不知道的房间**。这时台账那一行很可能是
        **陈旧的整栋汇总行**（c006 实测：它 rooms.json 里那行是改层序之前的旧账），
        或者快照本身是从别的层复制来的（c104 F4 = F3 平移副本）。
        ⇒ **直接跑 backfill 会用旧账把文件里真实的房间冲掉**，
          memory: c006-rooms-json-aggregate-pre-shift「★别对它跑 backfill」。
          所以这里只报"方向"和"先去查哪一边"，**不替人下结论说跑 backfill**。
      · 台账里干脆没有这一层的行 ⇒ 台账缺层，backfill 也修不了。
      · 快照是空数组而台账有 ⇒ 快照从没建过 ⇒ 补跑 backfill。
    """
    d = building_dir(data_dir, name)
    rooms = _json(d / "rooms.json")
    files = floor_files(data_dir, name)
    if not files:
        rep.add(Finding("A3", "交付楼层 rooms 快照一致", Status.UNAVAILABLE,
                        "没有 floors/floor*.json", measure="房间条数"))
        return
    if not isinstance(rooms, list):
        rep.add(unavailable("A3", "交付楼层 rooms 快照一致",
                            "没有可用的 rooms.json 台账，无从比对", measure="房间条数"))
        return
    want: dict[int, int] = {}
    for r in rooms:
        f = r.get("floor")
        want[f] = want.get(f, 0) + 1

    # ── 用第二把量具（房号里嵌的层号）先判"台账本身可不可信" ──────
    wit = _ledger_floor_witness(rooms)

    # ★ 一条判据**一层一条结论** —— 这是"建一层、验一层"的字面要求。
    #   原来整栋出一次结论，于是 134 间房的楼"验收单"上只有一行，
    #   哪一层好哪一层坏看不见（用户原话：一层一层的来，建好了验收）。
    bad: list[tuple[int, int | None, int, str]] = []
    for F, p in files:
        g = _json(p, {})
        got = None if g is _CORRUPT else len(g.get("rooms") or [])
        exp = want.get(F, 0)
        kind = _a3_kind(got, exp)
        if got == exp:
            rep.add(Finding("A3", "交付楼层 rooms 快照一致", Status.PASS,
                            "快照 %d 间 = 台账 %d 间" % (got, exp), floor=F,
                            measure="房间条数", evidence={"floor": F, "file": got,
                                                          "ledger": exp}))
            continue
        bad.append((F, got, exp, kind))
        # 这一层**证不证明台账的毛病**：看台账在这一层的行是不是偏离了本栋约定。
        # 只在"台账这层自己可疑"时才敢说方向，否则两种可能长得一样，不替人下结论。
        dirty_here = [a for a in wit["anomaly"] if a["floor"] == F]
        if wit["applicable"] and dirty_here:
            rep.add(Finding("A3", "交付楼层 rooms 快照一致", Status.WATCH,
                            "文件 %s 间 / 台账 %s 间；台账在这一层的行**自己可疑**：%s "
                            "—— 房号里嵌的层号与本栋其余行不一致（本栋约定偏移 %+d）。"
                            "先查台账这一行，**别跑 backfill**（它是以台账为准覆盖快照）"
                            % ("读不出" if got is None else got, exp,
                               "、".join(a["number"] for a in dirty_here[:4]),
                               wit["modal"]),
                            floor=F, measure="房间条数",
                            evidence={"floor": F, "file": got, "ledger": exp,
                                      "kind": kind, "suspect_ledger_rows": dirty_here}))
        else:
            rep.add(Finding("A3", "交付楼层 rooms 快照一致", Status.GAP,
                            "文件 %s 间 / 台账 %s 间。%s"
                            % ("读不出" if got is None else got, exp, _A3_KIND[kind]),
                            floor=F, measure="房间条数",
                            evidence={"floor": F, "file": got, "ledger": exp,
                                      "kind": kind}))

    # 台账层号自证：**整栋级**的一句话（它说的是台账这份文件，不是某一层）
    if bad and wit["applicable"]:
        rep.add(Finding("A3", "台账层号自证（房号里嵌的层号）",
                        Status.WATCH if wit["anomaly_n"] else Status.PASS,
                        ("台账 %d 行里 %d 行的房号自带层号偏离本栋模态偏移 %+d：%s"
                         "—— 这些行本身可疑")
                        % (wit["parsed"], wit["anomaly_n"], wit["modal"],
                           "、".join("F%s 的 %s" % (a["floor"], a["number"])
                                     for a in wit["anomaly"][:5]))
                        if wit["anomaly_n"] else
                        "台账 %d 行、约定偏移 %+d、无偏离行 ⇒ 台账这边看不出层序问题"
                        % (wit["parsed"], wit["modal"]),
                        measure="房号里嵌的层号 - 行层号",
                        evidence={"ledger_floor_witness":
                                  dict(wit, anomaly=wit["anomaly"][:20])}))
    elif bad:
        # 量不到就说量不到，不冒充分数（memory: gauge-coverage-invisible-in-summary）
        rep.add(Finding("A3", "台账层号自证（房号里嵌的层号）", Status.NOT_APPLICABLE,
                        "本栋房号不含层号段，这把量具**没量到**（%d 行均不可解析）"
                        % len(rooms),
                        measure="房号里嵌的层号 - 行层号",
                        evidence={"ledger_floor_witness":
                                  dict(wit, anomaly=wit["anomaly"][:20])}))


# ── A4 产物齐备 ─────────────────────────────────────────────────

# 每件产物一个判"在不在"的函数，**统一收 (data_dir, 楼名)** —— 不传目录。
# 传目录的写法正是"两个同名不同契约的 _floor_files"那类坑的温床：给错了不报错，
# 只是安静地回一个空结果。见 layout.py 的模块说明。
_ARTIFACTS = (
    ("floors", "逐层交付几何", lambda dd, n: bool(floor_files(dd, n))),
    ("model", "三维模型 GLB",
     lambda dd, n: (building_dir(dd, n) / ("%s-building.glb" % n)).is_file()),
    ("cad", "CAD 逐层渲染",
     lambda dd, n: any((building_dir(dd, n) / "dxf_plan_fast").glob("floor*.png"))
     if (building_dir(dd, n) / "dxf_plan_fast").is_dir() else False),
    ("spec", "建模规格", lambda dd, n: (building_dir(dd, n) / "spec.json").is_file()),
    ("rooms", "房间台账", lambda dd, n: (building_dir(dd, n) / "rooms.json").is_file()),
)


def check_a4(rep: Report, data_dir, name: str, **_kw) -> None:
    """这一步链该出的东西在不在。缺一件就是缺一件，不按"完成度百分比"糊。"""
    miss = [(k, lbl) for k, lbl, f in _ARTIFACTS if not f(data_dir, name)]
    have = [k for k, _l, f in _ARTIFACTS if f(data_dir, name)]
    if miss:
        rep.add(Finding("A4", "产物齐备", Status.GAP,
                        "缺：" + "、".join(lbl for _k, lbl in miss),
                        measure="产物件数",
                        evidence={"missing": [k for k, _l in miss], "have": have}))
        return
    rep.add(Finding("A4", "产物齐备", Status.PASS, "五件齐", measure="产物件数",
                    evidence={"have": have}))


# ── A5 模型陈旧（故意只报"量不到"）──────────────────────────────

def check_a5(rep: Report, data_dir, name: str, **_kw) -> None:
    """GLB 是不是用**当前**楼层几何出的。

    ★ 这条**故意**只回 UNAVAILABLE。为什么：按 mtime 比是个**已被证伪的量具** ——
    实测漏掉 28/48 栋（memory: delivery-glb-content-staleness）。真判据是
    "拿现码重出一次，按 sha256 比"。

    我把一条已知会骗人的判据写成 GAP/PASS，比不写更坏：它会给出假绿或假红，
    而两种都会让人不再去看真工具。所以这里唯一的正确输出是「量不到 + 该用哪个工具」。
    这是本项目的通则：**量具本身坏了，不许拿它出结论**（memory: 假几何报假缺陷）。
    """
    d = building_dir(data_dir, name)
    glb = d / ("%s-building.glb" % name)
    if not glb.is_file():
        rep.add(Finding("A5", "模型是否陈旧", Status.NOT_APPLICABLE,
                        "没有 GLB", measure="GLB 内容指纹"))
        return
    rep.add(unavailable(
        "A5", "模型是否陈旧",
        "本层不判定：mtime 比法已被实测证伪（漏 28/48 栋）。真判据 = "
        "现码重出一次再比 sha256 —— 见 memory: delivery-glb-content-staleness；"
        "要跑就走 B 层 `build_standard_glb.py`（会在交付目录写文件，须先留档）",
        measure="GLB 内容指纹", evidence={"glb_bytes": glb.stat().st_size}))


# ── A8 配置项是否真的被读取 ──────────────────────────────────────

# 同一份 profile.json 的**两个加载器**。判据不是"有没有人读"，而是
# "**两个加载器读的键是不是同一套**" —— 这才是当年 floor_y_bands 的真实病灶。
_LOADERS = (
    ("run_building.py", "load_profile", "批量通道 run_building.py"),
    (os.path.join("backend", "web", "run_step.py"), "profile_from_cfg",
     "老控制台通道 backend/web/run_step.py"),
)

_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", "data"})
_INDEX_CACHE: dict[str, tuple] = {}


def check_a8(rep: Report, data_dir, name: str, **_kw) -> None:
    """profile.json 的键，两个加载器是不是都读了。

    ★ 当年的事（记忆：`floor_y_bands` 那 36 栋）：同一份 profile，**两份加载器**
    —— `run_building.load_profile`（批量）与 `run_step.profile_from_cfg`（控制台）。
    键只喂给了控制台那份，于是"按图窗口过滤别栋/剖面图元"这套机制**对全库
    从来没生效过**，而没有任何报错：**读不到的配置和没配的配置长得一样。**

    所以这条检查有两问：
      ① **分叉**：本栋 profile 里，哪些键只被其中一个加载器读？—— 逐键报出。
      ② **死键**：哪些键**全仓 .py 里连字面量都没出现过**？—— 只在这一档报可疑。
    注意 ② 不能反过来用"消费者白名单"来做（早先就是这么写的，结果把
    `glb_windows`/`draw_kind` 误报成死键：它们由 SU 规格链/分类登记脚本消费，
    只是不在那份手维护的名单里）。**手维护的名单必然不全 ⇒ 必然假红 ⇒
    红灯被学会忽略**（memory: append-only-ledger-whole-table-assertion）。
    改成扫全仓字面量之后，"没人读"这个结论不依赖任何人的记性。
    """
    d = building_dir(data_dir, name)
    prof = _json(d / "profile.json")
    if not isinstance(prof, dict):
        rep.add(Finding("A8", "配置项是否真的被读取", Status.UNAVAILABLE,
                        "读不到 profile.json", measure="键名出现处"))
        return
    keys = [k for k in prof if not k.startswith("_")]
    if not keys:
        rep.add(Finding("A8", "配置项是否真的被读取", Status.NOT_APPLICABLE,
                        "profile 里没有任何非注释键", measure="键名出现处"))
        return

    root = _repo_root(data_dir)
    lits, missing = {}, []
    for rel, fn, _lbl in _LOADERS:
        got = _function_literals(root / rel, fn)
        if got is None:
            missing.append(rel)
        else:
            lits[rel] = got
    if missing:
        rep.add(unavailable("A8", "配置项是否真的被读取",
                            "读不到加载器源码（%s）—— 没有量具就不给结论"
                            % "、".join(missing), measure="键名出现处"))
        return

    index, meta = _literal_index(root)
    if not meta["files"]:
        rep.add(unavailable("A8", "配置项是否真的被读取",
                            "全仓 .py 一个字面量都没扫到（根目录找错了？）",
                            measure="键名出现处"))
        return
    if meta["unparsed_n"]:
        # 解析不了的文件是"没量到"的一部分：不许假装扫全了。
        rep.add(Finding("A8", "配置项是否真的被读取", Status.WATCH,
                        "有 %d 个 .py 解析不了（语法错/编码），死键判据对它们**没量到**：%s"
                        % (meta["unparsed_n"], "、".join(meta["unparsed"][:5])),
                        measure="键名出现处", evidence={"unparsed": meta["unparsed"]}))
        return

    # ① 分叉
    fleet_rel = _LOADERS[0][0]
    console_rel = _LOADERS[1][0]
    fleet_only = [k for k in keys if k in lits[fleet_rel] and k not in lits[console_rel]]
    console_only = [k for k in keys if k in lits[console_rel] and k not in lits[fleet_rel]]
    # ② 死键：全仓零提及
    dead = [k for k in keys if k not in index]
    # 扫的过程中撞见的、属于**别人文件**的告警（字符串里的无效转义）。
    # 不是本条判据的结论，但既然引擎看见了就说一句 —— 别吞（铁律：吞掉的东西要有人说话）
    esc = meta.get("bad_escapes") or []
    esc_note = ("；顺带：扫到 %d 个 .py 的字符串里有无效转义（%s），"
                "在 Python 3.12+ 会变成 SyntaxError"
                % (meta["bad_escapes_n"], "、".join(esc[:3]))) if esc else ""

    if fleet_only or console_only:
        # 两边**后果相反**，不许一句话说完 —— 缺的是哪条通道，决定它要不要紧：
        #   缺【批量】通道 ⇒ 建出交付件的就是它 ⇒ 该机制在交付里**从没生效过**。
        #   缺【控制台】通道 ⇒ 本栋**不丢**：A8 能走到这里，就说明
        #     <data>/buildings/<楼>/profile.json 是读得动的，而那正是控制台
        #     load_profile 走「委托给批量加载器」那一支的条件（run_step.py:87）。
        #     控制台既然委托，批量那边读到就够了。这一档只影响
        #     「注册表楼走覆盖档案 data/<楼>-profile.json」那条**当前没有楼在走**的路。
        bits = []
        if console_only:
            bits.append("**批量通道读不到**：%s（建出交付件的是批量通道 ⇒ "
                        "这套机制在交付里从没生效过。★ 但**别以为补上加载器就行**："
                        "实测（2026-09-24）把 floor_y_bands 接上后，有东西落在窗口外的"
                        "**6/6 栋全部直接崩**在 recognize.py 的 `sorted({…None…})` —— "
                        "`floor_of` 在窗口外是**故意**返回 None（「不属于任何层」），"
                        "而下游第一处消费就吃不掉它。要接它，先让 None 有归宿，"
                        "而且得逐处找还有没有别处把 None 当层号用；"
                        "**加载器不传这个键，正是流水线今天能跑的原因**）"
                        % "、".join(sorted(console_only)))
        if fleet_only:
            bits.append("控制台通道读不到：%s（**本栋不丢** —— 见下）"
                        % "、".join(sorted(fleet_only)))
        rep.add(Finding("A8", "配置项是否真的被读取", Status.WATCH,
                        "；".join(bits) + "。同一份 profile、两个加载器读的键不是同一套；"
                        "**要紧的只有「缺批量通道」那一档**，另一档本栋不丢（本栋有批量"
                        "档案 ⇒ 控制台委托给批量加载器）。"
                        "★ 别在这里写「躺了 N 栋」这类数：那是测量，会过期 —— "
                        "要数就数本条 WATCH 逐栋的楼号（历史笔记里的 36 是当时的测量）"
                        + esc_note,
                        measure="键名出现处",
                        evidence={"missing_in_batch": sorted(console_only),
                                  "missing_in_console": sorted(fleet_only),
                                  "loaders": [r for r, _f, _l in _LOADERS]}))
    if dead:
        rep.add(Finding("A8", "配置项是否真的被读取", Status.WATCH,
                        "这些键**全仓 .py 里连字面量都没出现**（扫了 %d 个文件）"
                        "—— 疑似死键：%s" % (meta["files"], "、".join(sorted(dead)))
                        + esc_note,
                        measure="键名出现处",
                        evidence={"zero_mention": sorted(dead),
                                  "scanned_files": meta["files"]}))
    if not fleet_only and not console_only and not dead:
        rep.add(Finding("A8", "配置项是否真的被读取", Status.PASS,
                        "%d 个键两个加载器都读，且全仓有字面量（扫了 %d 个文件）"
                        % (len(keys), meta["files"]) + esc_note,
                        measure="键名出现处"))


def _parse_quiet(path: Path):
    """ast.parse 一个**别人的**文件，并吞掉它自己源码里的告警。

    ★ 为什么必须吞：A8 要扫全仓 .py，`<unknown>:4: SyntaxWarning: invalid escape
    sequence '\\g'` 这种告警是**那个文件自己**的毛病（字符串里写了裸反斜杠），
    显示成 `<unknown>` 是因为 ast.parse 不给文件名。它属于那个文件，不属于检查引擎
    —— 但**不能因此当没看见**：名字照样收进 meta，由 A8 在结论里带一句
    （memory: silent-failure-needs-a-voice「吞掉的东西要有人说话」）。
    """
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None, False
    noisy = any("escape" in str(x.message) for x in w)
    return tree, noisy


def _function_literals(path: Path, fname: str) -> set[str] | None:
    """某个函数体内出现的所有字符串字面量。读不到/找不到就 None（=量不到）。

    用 ast 而不是"从 def 到下一个 def"的文本切法：文本切法会把相邻函数的键算进
    本函数（假绿），也会漏掉缩进不同的嵌套定义（假红）。
    """
    tree, _noisy = _parse_quiet(path)
    if tree is None:
        return None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == fname:
            return {x.value for x in ast.walk(n)
                    if isinstance(x, ast.Constant) and isinstance(x.value, str)}
    return None


def _walk_py(root: Path) -> list[tuple[str, int, int]]:
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in dns
                  if x not in _SKIP_DIRS and not x.startswith("_archive")]
        for f in fns:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((p, st.st_mtime_ns, st.st_size))
    return out


def _literal_index(root: Path) -> tuple[dict[str, list[str]], dict]:
    """全仓 .py 的字符串字面量索引：{字面量: [出现它的文件...]}。

    进程内缓存，键是"文件清单 + 每个文件的 mtime/size"—— 改过任何一个文件
    都会自动重扫。全库 718 个 .py 解析一次约 1.5 秒，逐栋重复扫是浪费，
    但**不能只按根目录缓存**（改了源码还拿旧索引 = 判据跟不上代码）。
    """
    files = _walk_py(root)
    fp = tuple(sorted(files))
    hit = _INDEX_CACHE.get(str(root))
    if hit and hit[0] == fp:
        return hit[1], hit[2]
    index: dict[str, list[str]] = {}
    unparsed = []
    noisy: list[str] = []
    for p, _m, _s in files:
        tree, esc = _parse_quiet(Path(p))
        if tree is None:
            unparsed.append(os.path.relpath(p, root))
            continue
        if esc:
            noisy.append(os.path.relpath(p, root))
        rel = os.path.relpath(p, root)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                index.setdefault(n.value, []).append(rel)
    meta = {"files": len(files), "unparsed": unparsed[:20], "unparsed_n": len(unparsed),
            "bad_escapes": sorted(noisy)[:20], "bad_escapes_n": len(noisy)}
    _INDEX_CACHE[str(root)] = (fp, index, meta)
    return index, meta


# ── A2 / A7 对账（用图纸自带面积表当裁判）────────────────────────

def check_a2(rep: Report, data_dir, name: str, **_kw) -> None:
    """逐层房间数 vs 图纸自带面积表的「房间数」列。

    ★ 这是本仓库最值钱的一把**外部**量具：数字不是我们算的，是画图人写的
    （DXF 里的 ACAD_TABLE，见 `_scratch/_area_audit.py::dxf_area_table`）。

    图纸数从 `sources`（引擎自己产出的逐层明细）来 —— A 层不许 import ezdxf，
    所以图纸里的数必须先被取出来落成产物。产物没有 ⇒ UNAVAILABLE，
    **不报 pass**：没对过账的楼不等于它对上了
    （memory: gauge-coverage-invisible-in-summary）。
    """
    d = building_dir(data_dir, name)
    rooms = _json(d / "rooms.json")
    if not isinstance(rooms, list) or not rooms:
        # 台账空 → 由 A1 报 GAP。这里不重复报同一个病，标 na。
        rep.add(Finding("A2", "逐层房间数 vs 图纸房间数", Status.NOT_APPLICABLE,
                        "台账为空（见 A1）", measure="房间条数"))
        return
    got: dict[int, int] = {}
    for r in rooms:
        got[r.get("floor")] = got.get(r.get("floor"), 0) + 1
    want = _drawing_rooms(data_dir, name)
    if want is None:
        rep.add(unavailable("A2", "逐层房间数 vs 图纸房间数",
                            "引擎还没有该楼的逐层明细（没跑过对账，或该图没有面积表）。"
                            "跑 `python -u backend/checks/runner.py --audit-all` 生成；"
                            "没量到不等于对上了",
                            measure="房间条数"))
        return
    # ★ 一层一条结论 —— 与 A3 同一个理由：验收单要能看出"哪一层没对上"。
    #   差值档位不是为了好看，是为了让人一眼分得出"少几间"和"整层没抽"：
    #   整层塌陷（缺一半以上）跟零头差异的修法完全不同。
    _MISSING_RATIO = 0.5
    nbad = 0
    for F in sorted(want):
        g, w = got.get(F, 0), want[F]
        if g == w:
            rep.add(Finding("A2", "逐层房间数 vs 图纸房间数", Status.PASS,
                            "台账 %d 间 = 图纸 %d 间" % (g, w), floor=F,
                            measure="房间条数",
                            evidence={"floor": F, "ledger": g, "drawing": w}))
            continue
        miss = w - g
        if miss > 0 and miss >= w * _MISSING_RATIO:
            # 缺一半以上：多半不是"少识别了几间"，是这一层整层没出来/被并块吃了。
            # 单独说清楚，因为两种病修法不同（memory: reco-accuracy-census 两病）。
            note = "**整层缺**（图纸 %d 间只抽到 %d 间）—— 先查这一层是不是整层塌陷/被并块吞了" \
                   % (w, g)
        elif miss > 0:
            note = "少 %d 间（漏抽）" % miss
        elif miss < 0:
            note = "多 %d 间（图纸没有的房 —— 可能是并块/合间，也可能把非房间当房间了）" % (-miss)
        else:
            note = ""
        nbad += 1
        rep.add(Finding("A2", "逐层房间数 vs 图纸房间数", Status.WATCH,
                        "台账 %d 间 / 图纸 %d 间：%s" % (g, w, note), floor=F,
                        measure="房间条数",
                        evidence={"floor": F, "ledger": g, "drawing": w,
                                  "delta": g - w}))
    # 汇总一行，但**状态跟着逐层走** —— 逐层有 WATCH 时这里绝不能是 PASS，
    # 否则验收单上会同时出现"逐层与图纸一致"和几条 WATCH，自相矛盾
    # （memory: one-judgement-many-implementations：同一屏两句话）。
    rep.add(Finding("A2", "逐层房间数 vs 图纸房间数",
                    Status.PASS if nbad == 0 else Status.WATCH,
                    ("逐层与图纸一致：%d 层 / %d 间" % (len(want), sum(want.values())))
                    if nbad == 0 else
                    ("%d/%d 层与图纸不符（合计台账 %d 间 / 图纸 %d 间）"
                     % (nbad, len(want), sum(got.values()), sum(want.values()))),
                    measure="房间条数",
                    evidence={"drawing_total": sum(want.values()),
                              "ledger_total": sum(got.values()),
                              "floors": len(want), "bad_floors": nbad}))


def _drawing_rooms(data_dir, name: str) -> dict[int, int] | None:
    """引擎产出的逐层明细 → {模型层: 图纸房间数}。

    「房间数」列没有写或写不出数字 ⇒ 该层不进字典（而不是补 0）：
    补 0 会让"图纸没写"和"图纸写了 0 间"变成同一个数。
    """
    from . import sources
    detail = sources.load_detail(data_dir)
    rows = (detail or {}).get(name) or []
    got = {int(r["model_floor"]): int(r["drawing_rooms"]) for r in rows
           if r.get("drawing_rooms") is not None}
    return got or None


# 楼板足迹 / 建筑面积 的合理量级区间。★ 判据是"同量级"，不是"相等"：
# 这本来就是两个口径（足迹含退台屋面块；建筑面积不含，且含公共面积摊派）。
_AREA_RATIO_LO, _AREA_RATIO_HI = 0.5, 2.0


def check_a7(rep: Report, data_dir, name: str, **_kw) -> None:
    """逐层**楼板足迹** vs 图纸**建筑面积**。

    ★ 口径必须写在结论里：这两个是不同的东西（足迹含退台屋面块，建筑面积不含），
    所以判据是"同量级 + 逐层趋势"，**不是相等**。混口径得出过错结论
    （memory: lihua-standardization-done ★面积四口径绝不许混用）。

    ★★ 量级用**比值**判，不用绝对差 —— 第一版是 `abs(delta) > 200㎡`，
    实测在 50 栋上全亮：一栋 6000㎡ 的楼差 4% 就是 240㎡，
    而 200㎡ 对 300㎡ 的小附楼又几乎是 100% 的偏差。**绝对阈值在大对象上恒触发**，
    于是 50 栋的红灯里没有一栋是"真的量级不对"。改成比值后只剩 8 栋，
    而且每一栋的比值本身就说得出理由。

    ★★★ 但比值仍然只是"哪里不一样"，不是"哪里不对"。全库 27 栋 40 层实测：
    **把每一层拿去和本栋其余层的图纸面积比一遍**之后，40 层里只有 6 层是
    说不通的，其余 34 层分属两类**结构上就不可比**的情形：

      · 过渡层楼板取并集（5 层）—— 模型[F] 恰好等于**本栋别层**的图纸面积
        （c006 F6 的 5381 = 图纸 F4/F5 的 5350；c114 F5 的 718 = 图纸 F0–F4 的 721）。
        楼板 = 裙楼足迹 ∪ 本层是**故意的**（不这么做塔楼会悬空，
        memory: transition-floor-slab-union），于是这一层的楼板本来就不是
        这一层的建筑面积。拿它俩比，是量具自己要错了东西。
      · 分片楼 / 首层（29 层）—— 图纸覆盖整栋而模型只建一翼（c004f1 那种），
        或首层模型只有室内轮廓而图纸含平台/雨棚。

    ⇒ 于是本判据不再只报一个比值，而是**报它是哪一类**：
      可比出来的（真差）继续 WATCH；结构上不可比的报 NOT_APPLICABLE 并说清原因。
    ★ 为什么必须做这一步：一条判据在 27 栋上亮、而其中 34 层根本不该比，
      它就会变成"永久红的判据" —— 人会学会不看它
      （memory: append-only-ledger-whole-table-assertion）。
      而 **NA 不是"洗白"**：它说的是"这一层本判据没在不该比的地方比"，
      真正的差仍然逐层 WATCH 出来，并且分片/并集这两种都**点得出是哪一层**。
    """
    d = building_dir(data_dir, name)
    files = floor_files(data_dir, name)
    if not files:
        rep.add(Finding("A7", "逐层楼板面积 vs 图纸建筑面积", Status.UNAVAILABLE,
                        "没有楼层文件", measure="楼板足迹(㎡) vs 建筑面积(㎡)"))
        return
    rows = _drawing_area(data_dir, name)
    if rows is None:
        rep.add(unavailable("A7", "逐层楼板面积 vs 图纸建筑面积",
                            "引擎还没有该楼的逐层明细（没跑过对账，或该图没有面积表）",
                            measure="楼板足迹(㎡) vs 建筑面积(㎡)"))
        return
    base = _fragment_base(data_dir, name)
    per, ratios, kinds = [], [], {}
    for F, p in files:
        g = _json(p, {}) or {}
        a = _shoelace(g.get("outline") or [])
        w = rows.get(F)
        per.append({"floor": F, "model_m2": round(a, 1), "drawing_m2": w})
        if w:
            ratios.append(a / w)
        if not w:
            continue
        r = a / w
        if _AREA_RATIO_LO <= r <= _AREA_RATIO_HI:
            rep.add(Finding("A7", "逐层楼板面积 vs 图纸建筑面积", Status.PASS,
                            "足迹 %.0f㎡ / 建筑面积 %.0f㎡ = %.2f 倍（同量级）"
                            % (a, w, r), floor=F,
                            measure="楼板足迹(㎡) vs 建筑面积(㎡)",
                            evidence={"floor": F, "model_m2": round(a, 1),
                                      "drawing_m2": round(w, 1), "ratio": round(r, 3)}))
            continue
        kind, note, ev = _a7_kind(a, F, rows, base)
        kinds[kind] = kinds.get(kind, 0) + 1
        st = Status.NOT_APPLICABLE if kind == "union" else Status.WATCH
        rep.add(Finding("A7", "逐层楼板面积 vs 图纸建筑面积", st,
                        "足迹 %.0f㎡ / 建筑面积 %.0f㎡ = **%.2f 倍**。%s"
                        % (a, w, r, note), floor=F,
                        measure="楼板足迹(㎡) vs 建筑面积(㎡)",
                        evidence=dict(ev, floor=F, model_m2=round(a, 1),
                                      drawing_m2=round(w, 1), ratio=round(r, 3))))
    if not per:
        rep.add(unavailable("A7", "逐层楼板面积 vs 图纸建筑面积", "没有可比的层",
                            measure="楼板足迹(㎡) vs 建筑面积(㎡)"))
        return
    med = sorted(ratios)[len(ratios) // 2] if ratios else None
    # ★ 真差 = 归类后仍然说不通的那些（over/under/multi）；union 是"不可比"，不计入。
    real_n = sum(kinds.get(k, 0) for k in ("over", "under", "multi"))
    ok = bool(ratios) and _AREA_RATIO_LO <= med <= _AREA_RATIO_HI and real_n == 0
    if ok:
        msg = "比值中位数 %.2f，%d 层全在同量级" % (med, len(ratios))
    else:
        bits = ["比值中位数 %s" % ("%.2f" % med if med is not None else "无")]
        if kinds.get("union"):
            bits.append("并集层 %d 层（本判据在该层不可比，已单列 NA）"
                        % kinds["union"])
        if real_n:
            bits.append("**说不通的 %d 层**（见逐层）" % real_n)
        if base:
            bits.append("本栋是 %s 的分片" % base)
        msg = "；".join(bits)
    rep.add(Finding("A7", "逐层楼板面积 vs 图纸建筑面积",
                    Status.PASS if ok else Status.WATCH, msg,
                    measure="楼板足迹(㎡) vs 建筑面积(㎡)",
                    evidence={"floors": per, "median_ratio": med,
                              "kinds": kinds, "unreconciled_floors": real_n}))


# 「楼板 = 裙楼足迹 ∪ 本层」的容差：模型[F] 与**本栋别层**的图纸面积差在这个
# 比例以内，就算"是同一个数"（并集把那一层的足迹带上来了）。
_AREA_UNION_TOL = 0.06
# 「本层楼板 = 图纸 × k」的容差与可能的倍数。
_AREA_MULT_TOL = 0.08
_AREA_MULT_KS = (2, 3, 4, 5)


def _fragment_base(data_dir, name: str) -> str | None:
    """本栋若是 `c004f1` 这种**分片**，返回母栋号 `c004`（库里确实存在才算）。

    ★ 为什么去查磁盘而不是看名字：光看名字是**猜**（`f1` 也可能是楼号的一部分），
      而"库里同时存在 c004"是**可查的事实**。差别落在结论上 ——
      能写「本栋是 c004 的一个分片（c004 也在库里）」，而不是
      「本栋可能是某楼的翼」：后者要读的人自己去猜，前者一句话就定了。
      这正是今天反复栽的"代理量代替真对象"的解法：把推测换成可查的。
    """
    m = re.match(r"^(?P<base>.+?)f\d+$", name)
    if not m:
        return None
    base = m.group("base")
    return base if (building_dir(data_dir, base) / "profile.json").is_file() else None


def _a7_kind(a: float, F: int, rows: dict[int, float],
             base: str | None) -> tuple[str, str, dict]:
    """把一个比值不对的层**归类**，返回 (类, 说给人听的话, 证据)。

    ★ 归类只靠**本栋自己的其余楼层**，不用任何绝对阈值：
      同一个 5381㎡ 在别栋可能是正常的，在这里之所以不可比，
      是因为它恰好等于本栋 F4/F5 的图纸面积。判据要能自证，不能靠外部常数。
    """
    w = rows.get(F) or 0
    # ① 过渡层并集：模型[F] 与**别层**的图纸面积相同，且那一层比本层大
    for j, dj in sorted(rows.items()):
        if j == F or not dj or dj <= w:
            continue
        if abs(a / dj - 1) <= _AREA_UNION_TOL:
            return ("union",
                    "本层楼板 **%.0f㎡** 恰好等于本栋**图纸 F%d** 的建筑面积（%.0f㎡）"
                    "—— 这是『楼板 = 裙楼足迹 ∪ 本层』的并集规则（不这么做塔楼会悬空）。"
                    "所以本判据在这一层**不可比**：它量的本来就不是这一层的建筑面积。"
                    % (a, j, dj),
                    {"kind": "union", "matches_floor": j, "matches_m2": round(dj, 1)})
    # ② 多块合并：模型 ≈ 图纸的整数倍。
    #    ★ 只报出来，**不算通过** —— 2.00 倍既可能是本层合并了多块楼板（正常），
    #      也可能是 c113 F3 那种**并块吞并**（真缺陷）。数字分不出这两种，
    #      所以不下结论，只把"整数倍"这个线索摆出来让人去看图（同 A3 的做法）。
    if w:
        for k in _AREA_MULT_KS:
            if abs(a / (w * k) - 1) <= _AREA_MULT_TOL:
                return ("multi",
                        "本层楼板 ≈ 图纸的 **%d 倍**（%.0f㎡ vs %.0f㎡）。"
                        "整数倍既可能是本层合并了多块楼板（退台/错层），"
                        "也可能是**并块把邻块吞了** —— 到图的这一层上看一眼轮廓就能定，"
                        "别只看数。" % (k, a, w),
                        {"kind": "multi", "multiple": k})
    # ③ 模型 < 图纸
    if a < w:
        if base:
            return ("under",
                    "模型 %.0f㎡ 只有图纸 %.0f㎡ 的 %.2f 倍。**本栋是 %s 的一个分片**"
                    "（%s 也在库里）—— 图纸覆盖整栋而本栋只建一翼，"
                    "这个比值偏小是**预期的**，不是这一层画错了。"
                    % (a, w, a / w, base, base),
                    {"kind": "under", "fragment_of": base})
        return ("under",
                "模型 %.0f㎡ 只有图纸 %.0f㎡ 的 %.2f 倍。先查两件事："
                "①%s的模型是不是只取了室内轮廓，而图纸的建筑面积含平台/雨棚/台阶；"
                "②本栋是不是别栋的翼/附楼，图纸覆盖整栋"
                % (a, w, a / w, "F%d 是首层" % F if F == 0 else "本层"),
                {"kind": "under"})
    # ④ 其余：模型比图纸大，且对不上本栋任何一层的图纸面积
    return ("over",
            "模型 %.0f㎡ 比图纸 %.0f㎡ **大 %.2f 倍**，且对不上本栋任何一层的图纸面积。"
            "先看这一层的轮廓是不是把退台/内院**填平**了，或把别的块**并**了进来"
            % (a, w, a / w if w else 0),
            {"kind": "over"})


def _drawing_area(data_dir, name: str) -> dict[int, float] | None:
    """引擎产出的逐层明细 → {模型层: 图纸建筑面积}。

    ★ 这里只取**图纸那一列**当裁判；模型那列由 A7 自己从楼层 JSON 现量
    （`_shoelace(outline)`）。理由：裁判的数与自己量的数必须来自两个地方，
    拿产物里现成的 model_m2 来比自己的 outline，等于用同一把尺子量两次。
    """
    from . import sources
    detail = sources.load_detail(data_dir)
    rows = (detail or {}).get(name) or []
    out = {int(r["model_floor"]): float(r["drawing_m2"]) for r in rows
           if r.get("drawing_m2") is not None}
    return out or None


def _shoelace(ring) -> float:
    """鞋带公式取绝对面积。本层不 import shapely，所以不做自交清洗 ——
    自交环会偏，但 A7 的判据是 200㎡ 量级，且在结论里写明了口径。"""
    n = len(ring)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0

# 本库 95 栋的既有房号命名**无一例外含数字**（`6-A-05-00`、`113-01-07`、`NY29-1-01`…）。
# 所以"一个数字都没有"就是"这里存的不是房号，是空间名"的强判据。
_HAS_DIGIT = re.compile(r"\d")
# 无数字的房号占比超过这个 ⇒ 已不是个别现象，是整列被当成了"名称列"。
_A9_NAME_RATE = 0.20
# 偏离本栋众数号段的占比超过这个 ⇒ 命名不统一，或有别的楼/别的层的号段混进来。
_A9_DRIFT_RATE = 0.20


# ── 「本栋号段」的**唯一定义处** ─────────────────────────────────────
# ★ 为什么要抽出来单独放（2026-09-23）：问"哪些号是本栋的命名"的地方不止 A9 一处 ——
#   B3 也要它（图幅外画着的号里，哪些是本栋的、哪些是邻幅的：实测 c113 邻幅用 `Y11xx`、
#   c114 的图幅外那一列用的是**同一个** `114-*`）。两处各写一份的话，只有一份会跟着规则走，
#   屏幕上就会出现两句不一样的话（memory: one-judgement-many-implementations）。
#   所以 B3 **import 这里的函数**，不另抄一份；runner.py 自检 ⑦-c 会拿 A9 自己报出来的
#   `modal_segment` 与它对比，改坏就红。
def number_segment_counts(nums) -> Counter:
    """房号第一段的计数表（`113-01-07` → 段 `113`）。

    只按 `-` 切，不按"非字母数字"切：c046 实测有整列是「卫」这种汉字，
    按字符类别切会把它切成空串，两个不同的中文号就会撞成同一个空形。
    空串不算号段；纯汉字的名字（`花坛`/`卫`）各自成为一个段，不影响众数。
    """
    return Counter(t.split("-")[0] for t in nums if t.strip())


def home_number_segment(nums) -> tuple:
    """**本栋号段** = 出现最多的第一段。回 `(段, 该段行数)`；没有可用的号时 `(None, 0)`。

    不按楼名猜段（楼名是 `c113`，台账里真正在用的写 `113-*`），也不看第二段 ——
    第二段是层号（`6-C-06-03` = 06 层 03 号），写法逐栋不同（0 基/1 基），
    拿它推楼层会跨层配错（memory: rooms-number-embeds-floor-no-crossfloor-match）。
    """
    segs = number_segment_counts(nums)
    if not segs:
        return None, 0
    return segs.most_common(1)[0]


def check_a9(rep: Report, data_dir, name: str, **_kw) -> None:
    """房号字段里存的**是不是房号**。

    ★ 为什么单独立一条：A1/A2/A3 量的全是**条数**（台账非空、逐层计数、快照与台账一致）。
      条数完全对得上，字段却可以是错的 —— 它们对"36 个桶里装的是 17 间房
      + 14 个表格小格 + 4 个别的字 + 一个面积串"**完全无感**。
      实测：c113 F3 台账 36 间、快照 36 间、图纸 18 间，三条计数判据各说各话，
      而真相在**字段内容**里 —— 这不是"数字不对"，是"这一列装错了东西"。

    两条子判据，都要能说清是哪种：
      ① **空间名当成房号**：`卫`(168 间!)、`卫生间`、`花坛`、`天台`、`待拆除搭建`。
         这些是**图纸上的名称**，被读进了房号列。房号不可能一个数字都没有。
      ② **号段不统一**：偏离本栋众数号段的房间占比过高（c113 有 37/134 是
         `12-*`/`14-*`/`06-*`，而本楼号段是 `113-*`）。
    ★ ②**不下结论**：号段偏离既可能是混入了别的楼/别的层的号段（缺陷），
      也可能是本栋本来就有两套命名（不是缺陷）。所以报出直方图让人去认，
      判据只负责"把它变得看得见"。
    """
    rooms = _ledger(data_dir, name)
    if rooms is None:
        rep.add(unavailable("A9", "房号字段是不是房号",
                            "台账读不出（文件不在/解析失败）；A1 已就此报过",
                            measure="房号字段"))
        return
    if not rooms:
        rep.add(Finding("A9", "房号字段是不是房号", Status.NOT_APPLICABLE,
                        "台账为空（0 间），本判据无从量起 —— 见 A1",
                        measure="房号字段", evidence={"rooms": 0}))
        return

    nums = [str(r.get("number") or "") for r in rooms]
    blank = sum(1 for t in nums if not t.strip())
    named = [t for t in nums if t.strip() and not _HAS_DIGIT.search(t)]
    # 空房号单独说：空不是"名"，是没读到
    if blank:
        rep.add(Finding("A9", "房号字段是不是房号", Status.WATCH,
                        "%d/%d 间的房号是**空串**（没读到房号，不是没有房号）"
                        % (blank, len(nums)), measure="房号字段",
                        evidence={"blank": blank, "rooms": len(nums)}))
    if named:
        hist = Counter(named).most_common(6)
        rate = len(named) / len(nums)
        st = Status.GAP if rate >= _A9_NAME_RATE else Status.WATCH
        rep.add(Finding("A9", "房号字段是不是房号", st,
                        "%d/%d 间的房号里**一个数字都没有**（%.0f%%）：%s —— "
                        "这些是图纸上的**名称**（卫生间/花坛/天台那种），被读进了房号列。"
                        "逐层房间数会因为它们虚高，而图纸的房间数不会"
                        % (len(named), len(nums), 100 * rate,
                           "、".join("%s×%d" % (k, v) for k, v in hist)),
                        measure="房号字段",
                        evidence={"named_n": len(named), "rooms": len(nums),
                                  "rate": round(rate, 3),
                                  "named_hist": dict(hist)}))
    segs = number_segment_counts(nums)
    top, n = segs.most_common(1)[0]
    drift = len(nums) - n
    rate = drift / len(nums)
    if rate > _A9_DRIFT_RATE:
        rep.add(Finding("A9", "房号字段是不是房号", Status.WATCH,
                        "本栋号段是 `%s-*`（%d/%d 间），另有 **%d 间（%.0f%%）**"
                        "用的是别的号段：%s。先认一认这些号段是"
                        "①别的楼/别的层的房间混进来了，还是②本栋本来就有两套命名 —— "
                        "两者在计数上长得一样，只能看号段本身"
                        % (top, n, len(nums), drift, 100 * rate,
                           "、".join("%s-*×%d" % (k, v)
                                     for k, v in segs.most_common(6) if k != top)),
                        measure="房号字段",
                        evidence={"modal_segment": top, "modal_n": n,
                                  "rooms": len(nums), "drift_n": drift,
                                  "segments": dict(segs.most_common(8))}))
    else:
        rep.add(Finding("A9", "房号字段是不是房号", Status.PASS,
                        "房号含数字、且 %d/%d 间同属 `%s-*` 号段"
                        % (n, len(nums), top), measure="房号字段",
                        evidence={"modal_segment": top, "rooms": len(nums)}))

