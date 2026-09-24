# -*- coding: utf-8 -*-
"""C 层 · **系统级**判据 —— 问的是「这整个东西是不是一个系统」。

与 A/B 层的分界只有一条：**A/B 逐栋问，C 整库问。**
有些毛病**逐栋检查结构上就看不见**，不是没查到：

  · 整体与各栋之和**不相等** —— 每一栋单独看都对，合起来对不上。
  · **同一个事实有两个来源**，各自都自洽，互相不等。
  · 一个产物**比它上游还旧** —— 单看这一栋，文件都在、内容也对。
  · 判据自己**有没有被登记** —— 没有一条判据能检查"还有哪些判据没人知道"。

⇒ 这四条就是 C0–C3。**C0 是用户那句话的可执行版**：
「我总体感觉太杂乱，不像一个系统那么完整」（2026-09-24）。

**还有第五条，但它不住在这个文件里**：上面前四条问的都是**本仓产物之间**的关系，
没有一条问「知识图谱自己的边还指着原处吗」—— 图纸全对、台账全对、名册全对，
图谱仍然可能全错（`kb/` 里 99 条边指着 `文件:行`／`文件:符号`，源一改就可能指空）。
它就是 **C4**，实现在 `kg_citation.py`：不自己判，只跑图谱自己的门禁再把结论
翻译成 Finding（一把尺子一个实现）。

## 三条纪律（写在这里，改本文件前先读）

1. **不许在这里重新数一遍。** 所有计数一律取自 `backend/state/census.py`
   （唯一口径计算者）。本模块只做**比较**：拿已有的数互相比、跟第二个来源比、
   跟磁盘的 mtime 比。**一条判据只许一份实现**（memory:
   one-judgement-many-implementations）。
2. **口径（measure）必须写。** 本仓的「面积」有四个口径、「层数」有六个口径，
   混用一次就出过一个错结论。每个 Finding 的 `measure` 就是这句话的落地。
3. **量不到就报 UNAVAILABLE，绝不给绿灯。** 缺 `state.json`、缺 `index.json`、
   形状不是预期 —— 都是"没量成"，不是"没问题"。

## 为什么这几个函数收 `state` 参数

`census.compute()` 要遍历 2414 个 floor JSON，很贵。四个检查都要用同一份结果
⇒ `run_system_checks` **算一次、传进去**。传进来的仍然只是**磁盘读数**
（不是上一轮结论），所以"检查之间不共享状态"这条没有被破坏。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .findings import Finding, Report, Status, unavailable

# C4 的实现特意放在**独立文件**里：它的量具在 `kb/`（另一套目录、另一套自检），
# 而本模块只管 A/C 引擎自己的判据。混在一起以后，"哪把尺子在量"又要靠人记。
# ★ 它自带 `--selftest`（四个结局各一条对照），跑法：
#   `python -m backend.checks.kg_citation --selftest`
from .kg_citation import check_c4

#: 派生产物 → 它的**上游**。判据是**关系式**，不是阈值：
#: 「下游的 mtime 不得早于上游的最新产物」。**故意不设"容忍天数"** ——
#: 容忍天数是个魔法数，而"下游比上游旧"本身就已经是错的（memory:
#: criterion-key-missing-dimension 那族的教训：拿一个数去近似一个关系）。
DERIVED_PAIRS: tuple[tuple[str, str], ...] = (
    ("data/buildings/index.json", "data/buildings"),
    ("data/_meta/checks/fleet.json", "data/buildings"),
    ("data/_meta/area_audit_detail.json", "data/buildings"),
)

#: 登记表：一条判据要么在 CHECK_REGISTRY 里，要么在这里写明"一次性探针"。
ROSTER_REL = "data/_meta/criteria_roster.json"

#: 名册的**量具**。名册自己记着生成时的 `source_sha256_12`，这里拿磁盘现状跟它比
#: —— 见 `check_c3` 文档串「为什么不能只看 disposition」。
ROSTER_SRC_REL = "backend/state/roster.py"


# ── 小工具 ──────────────────────────────────────────────────────────

def _read_json(path: Path):
    """读 JSON。**读不到要抛，不许返回 None 让调用方当成空。**"""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _newest_mtime(root: Path) -> float | None:
    """目录树里最新的 mtime；量不到返回 None（不是 0）。"""
    newest: float | None = None
    if not root.exists():
        return None
    if root.is_file():
        return root.stat().st_mtime
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            try:
                m = os.path.getmtime(os.path.join(dirpath, fn))
            except OSError:
                continue
            if newest is None or m > newest:
                newest = m
    return newest


def _ts(m: float | None) -> str:
    return "—" if m is None else datetime.fromtimestamp(m).strftime("%Y-%m-%d %H:%M")


def _days(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return "?"
    return "%.1f" % ((b - a) / 86400.0)


# ── C0 · 系统完整性 ────────────────────────────────────────────────

def check_c0(rep: Report, data_dir: Path, state: dict) -> None:
    """**这个系统完整吗** —— 用户那句话的可执行版。

    只问四件逐栋检查**结构上问不到**的事：
      ① 账本（state.json）在不在场，且是不是**同一把尺子**量的；
      ② 整体与各栋之和是否相等；
      ③ 交付四件套（profile / 台账 / 逐层几何 / 模型）逐栋齐不齐；
      ④ 磁盘上的栋与账本里的栋是否**一一对应**（不许有孤儿，两边都不许）。
    """
    did = "C0.system_integrity"
    title = "系统完整性：账本 / 整体=各栋之和 / 交付四件套 / 无孤儿"
    measure = "计数（栋、层、文件），口径全部取自 state.json，不在本模块重数"

    # ① 账本在场，且是同一把尺子 ─────────────────────────────────
    # ★★ 必须读**磁盘上那份** state.json，不能读 `state` 入参。
    #   入参在 runner 路径下是 `census.compute()` **现算**的，而现算出来的
    #   criterion_version / source_sha256_12 **按构造必然等于现码**（两者同源）
    #   ⇒ 拿它比就是自己跟自己比，这条判据**恒绿**。
    #   而它存在的全部理由恰恰是铁律 24（「这份数是旧尺子量的」和
    #   「这份数是对的」在屏幕上长得一模一样）—— 守这个坑的那条判据，
    #   一度是唯一不会响的那条。实测抓到：屏上印着
    #   「state.json 的 criterion_version 与 sha256 与现码一致」，
    #   而那个文件从头到尾**没被打开过**。
    #   ⇒ 读文件；读不到就 UNAVAILABLE（量不到≠没问题），绝不 PASS。
    from backend.state import census
    expect_ver = census.CRITERION_VERSION
    expect_sha = census._self_sha12()
    try:
        ledger = json.loads(census.STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        rep.add(unavailable(did + ".ledger", "账本在场且是同一把尺子",
                            "读不到 %s（%s: %s）⇒ **这次没量到**，不是「没问题」。"
                            "先跑 `python -u backend/state/census.py`"
                            % (census.STATE_PATH, type(ex).__name__, ex),
                            measure=measure))
    else:
        got_ver = ledger.get("criterion_version")
        got_sha = ledger.get("source_sha256_12")
        if got_ver != expect_ver or got_sha != expect_sha:
            rep.add(Finding(check=did + ".ledger", title="账本与代码不是同一把尺子",
                            status=Status.GAP, measure=measure,
                            detail=("磁盘上 %s 是 criterion_version=%s / sha=%s 量的，"
                                    "而现码是 version=%s / sha=%s ⇒ "
                                    "**你正在读的数是旧尺子量的**，先重跑 "
                                    "`python -u backend/state/census.py`"
                                    % (census.STATE_PATH.name, got_ver, got_sha,
                                       expect_ver, expect_sha)),
                            evidence={"ledger": {"version": got_ver, "sha": got_sha},
                                      "code": {"version": expect_ver, "sha": expect_sha}}))
        else:
            rep.add(Finding(check=did + ".ledger", title="账本与代码是同一把尺子",
                            status=Status.PASS, measure=measure,
                            detail="磁盘上 state.json 的 criterion_version 与 sha256 "
                                   "与现码一致（v%s / %s）；账本路径与 built_at 见 evidence"
                                   % (got_ver, got_sha),
                            evidence={"ledger_path": str(census.STATE_PATH),
                                      "ledger_built_at": ledger.get("built_at")}))

    counts = state.get("counts") or {}
    per = state.get("per_building") or {}
    if not counts or not per:
        rep.add(unavailable(did, title,
                            "state.json 里没有 counts/per_building —— 账本形状不对，没法判完整性",
                            measure=measure))
        return

    def val(key: str) -> int | None:
        node = counts.get(key)
        return node.get("value") if isinstance(node, dict) else None

    # ② 整体 == 各栋之和 ────────────────────────────────────────
    rows = [(n, r) for n, r in per.items() if isinstance(r, dict)]
    for key, field, label in (
            ("floors_delivered", "floors_delivered", "交付层数"),
            ("buildings_dirs", None, "栋数"),
    ):
        total = val(key)
        if field is None:
            got = len(rows)
        else:
            got = sum(r.get(field) or 0 for _n, r in rows)
        ok = total == got
        rep.add(Finding(
            check="%s.rollup.%s" % (did, key),
            title="整体 == 各栋之和（%s）" % label,
            status=Status.PASS if ok else Status.GAP, measure=measure,
            detail=("全库 %s 与逐栋之和一致：%s" % (label, total) if ok else
                    "★ 全库 %s = %s，而逐栋加起来 = %s（差 %s）—— "
                    "每一栋单独看都对，合起来对不上。这不可能是某一栋的问题，"
                    "是**汇总口径或漏算**" % (label, total, got, (total or 0) - got)),
            evidence={"headline": total, "sum_of_buildings": got}))

    # ③ 交付四件套 ──────────────────────────────────────────────
    missing = {"profile": [], "rooms": [], "floors": [], "glb": []}
    for name, r in sorted(rows):
        if not r.get("has_profile"):
            missing["profile"].append(name)
        if not (r.get("rooms_in_rooms_json") or 0) > 0:
            missing["rooms"].append(name)
        if not (r.get("floors_delivered") or 0) > 0:
            missing["floors"].append(name)
        if not r.get("glb"):
            missing["glb"].append(name)
    parts = ["%s 缺 %d 栋" % (k, len(v)) for k, v in missing.items() if v]
    n_bad = len({n for v in missing.values() for n in v})
    if not parts:
        four_detail = "%d 栋四件套齐全" % len(rows)
    else:
        four_detail = "、".join(parts) + "（共 %d 栋不全，占 %d/%d）" % (n_bad, n_bad, len(rows))
        if missing["rooms"]:
            # 同一个毛病在 A1/A6 里也亮 —— 明说是同一批楼，否则红绿灯墙上
            # 会把它显示成三个毛病，人就会去修三遍（本仓 memory: 同因合并那一段）。
            four_detail += ("—— ★ 缺台账这 %d 栋与 A1/A6 亮的是**同一批楼**"
                            "（根因是没进 ID_BASE 白名单，房间抽取整条链不为它跑），"
                            "别当两件事修" % len(missing["rooms"]))
    rep.add(Finding(
        check=did + ".four_pieces", title="交付四件套齐备（profile/台账/逐层几何/模型）",
        status=Status.GAP if parts else Status.PASS, measure=measure,
        detail=four_detail,
        evidence={"missing": {k: v for k, v in missing.items() if v}}))

    # ④ 无孤儿（两个方向都要查）────────────────────────────────
    base = data_dir / "buildings"
    on_disk = sorted(d.name for d in base.iterdir() if d.is_dir()) if base.is_dir() else []
    in_ledger = sorted(per)
    only_disk = sorted(set(on_disk) - set(in_ledger))
    only_ledger = sorted(set(in_ledger) - set(on_disk))
    if only_disk or only_ledger:
        rep.add(Finding(check=did + ".orphan", title="磁盘的栋与账本的栋一一对应",
                        status=Status.GAP, measure=measure,
                        detail="磁盘多出 %d 个：%s；账本多出 %d 个：%s"
                               % (len(only_disk), only_disk[:6],
                                  len(only_ledger), only_ledger[:6]),
                        evidence={"only_on_disk": only_disk,
                                  "only_in_ledger": only_ledger}))
    else:
        rep.add(Finding(check=did + ".orphan", title="磁盘的栋与账本的栋一一对应",
                        status=Status.PASS, measure=measure,
                        detail="%d 个目录与账本逐一对上" % len(on_disk)))


# ── C1 · 口径自洽 ──────────────────────────────────────────────────

def check_c1(rep: Report, data_dir: Path, state: dict) -> None:
    """**同一个事实的多个来源必须相等。** 不等就红，并把**每一个值**都打出来。

    ★ 这条判据存在的理由不是形式主义：本仓实测「全库几层」有**六个**答案
      （456/12/1946/2414/468/642），**六个全是对的量具**，缺的是口径。
      其中 `data/buildings/index.json` 自己就写着**两个字段说同一件事**。
      ⇒ 所以这里不但比 census 与 index，还比 index **自己内部**的两个字段。
    """
    did = "C1.criterion_agreement"
    measure = "层数 / 条目数（同一事实的多个来源逐一对齐）"
    counts = state.get("counts") or {}

    def val(key: str):
        node = counts.get(key)
        return node.get("value") if isinstance(node, dict) else None

    # ① 登记过的分解必须加得起来 ────────────────────────────────
    for head, parts, label in (
            ("floors_all_in_buildings",
             ("floors_delivered", "floors_snapshot_orig_suffix",
              "floors_under_orig_component"), "buildings 下全部 floor*.json"),
            ("glb_all", ("glb_delivered_in_buildings", "glb_at_data_root"), "全部 GLB"),
    ):
        h = val(head)
        ps = [val(p) for p in parts]
        if h is None or any(p is None for p in ps):
            rep.add(unavailable(did + "." + head, "口径分解：%s" % label,
                                "口径 %s 或它的分项 %s 里有 null（量不到），没法对账"
                                % (head, list(parts)), measure=measure))
            continue
        s = sum(ps)
        rep.add(Finding(
            check="%s.decomp.%s" % (did, head),
            title="口径分解加得起来：%s" % label,
            status=Status.PASS if s == h else Status.GAP, measure=measure,
            detail=("%s = %d = %s" % (head, h, " + ".join(str(p) for p in ps)) if s == h
                    else "★ %s = %d 而分项之和 = %d（%s），差 %d"
                         % (head, h, s, " + ".join("%s=%s" % (p, v) for p, v in zip(parts, ps)), h - s)),
            evidence={"headline": h, "parts": dict(zip(parts, ps))}))

    # ② 全库层数：census 说了算，index.json 是第二个来源 ────────
    idx_path = data_dir / "buildings" / "index.json"
    delivered = val("floors_delivered")
    if not idx_path.is_file():
        rep.add(unavailable(did + ".floors.index", "全库层数：census vs index.json",
                            "没有 %s —— 第二个来源缺席，量不到" % idx_path.name,
                            measure=measure))
    else:
        try:
            entries = _read_json(idx_path)
        except (OSError, ValueError) as ex:
            rep.add(unavailable(did + ".floors.index", "全库层数：census vs index.json",
                                "读不动 %s：%s: %s" % (idx_path.name, type(ex).__name__, ex),
                                measure=measure))
            entries = None
        if isinstance(entries, list):
            # 顶层条目（理化楼那种 dir=="data"）与 buildings/ 下的栋分开算 ——
            # 但**不写死**：先按 dir 分，分不开就明说分不开。
            bld = [e for e in entries if isinstance(e, dict) and e.get("dir") != "data"]
            top = [e for e in entries if isinstance(e, dict) and e.get("dir") == "data"]
            if not bld:
                rep.add(unavailable(did + ".floors.index", "全库层数：census vs index.json",
                                    "index.json 里按 dir 分不出『栋』这一档（%d 条），"
                                    "别硬猜" % len(entries), measure=measure))
            else:
                sf = sum(e["floors"] for e in bld if isinstance(e.get("floors"), int))
                st = sum(e.get("floors_total", 0) for e in bld
                         if isinstance(e.get("floors_total"), int))
                # ★ 标签在这里就把 %d 插掉 —— 放进 dict 的**键**里再统一 `%` 是插不到的，
                #   而屏幕上会原样打出 `Σfloors(%d栋)=436`，看着像格式串写错了，
                #   实际是"这个数从来没被填进去过"（本仓 memory: 模板串印出 undefined）。
                sources = {"census.floors_delivered": delivered,
                           "index.json 的 Σfloors（%d 栋）" % len(bld): sf,
                           "index.json 的 Σfloors_total（%d 栋）" % len(bld): st}
                agree = len({v for v in (delivered, sf, st)}) == 1
                rep.add(Finding(
                    check=did + ".floors.index",
                    title="全库层数：census 与 index.json 必须相等",
                    status=Status.PASS if agree else Status.GAP, measure=measure,
                    detail=("三个来源一致：%s" % delivered if agree else
                            "★ 同一件事（全库几层）三个来源三个数：%s —— "
                            "index.json 是**派生副本**（mtime %s），census 是现算；"
                            "副本陈旧就是下一个『六个答案』"
                            % ("，".join("%s=%s" % kv for kv in sources.items()),
                               _ts(idx_path.stat().st_mtime))),
                    evidence={"sources": sources,
                              "index_mtime": _ts(idx_path.stat().st_mtime),
                              "index_top_level_entries": [e.get("name") for e in top],
                              "census_criterion_version": state.get("criterion_version")}))

            # ③ index.json **自己内部**两个字段说同一件事 ──────────
            bad = [(e.get("name"), e.get("floors"), e.get("floors_total"))
                   for e in bld if e.get("floors") != e.get("floors_total")]
            rep.add(Finding(
                check=did + ".floors.index_internal",
                title="index.json 内部：floors 与 floors_total 必须相等",
                status=Status.PASS if not bad else Status.GAP, measure=measure,
                detail=("逐栋一致（%d 栋）" % len(bld) if not bad else
                        "★ 同一份文件里两个字段说同一件事，却对不上（%d 栋）：%s"
                        % (len(bad), "；".join("%s floors=%s / floors_total=%s" % t for t in bad))),
                evidence={"mismatch": [{"name": n, "floors": f, "floors_total": t}
                                       for n, f, t in bad]}))
        elif entries is not None:
            rep.add(unavailable(did + ".floors.index", "全库层数：census vs index.json",
                                "index.json 顶层是 %s，不是 list —— 形状不是预期，不硬猜"
                                % type(entries).__name__, measure=measure))

    # ④ 两个房间口径并列登记，**不判谁对**，只把差摆出来 ────────
    # 台账（rooms.json）与交付层内的快照（floor JSON 的 rooms[]）是**两个不同的东西**，
    # 不要求相等；但差值大到位数上有意义时必须有人看见。
    rt, rf = val("rooms_total"), val("rooms_total_from_floors")
    if rt is None or rf is None:
        rep.add(unavailable(did + ".rooms", "两个房间口径的差",
                            "rooms_total=%s / rooms_total_from_floors=%s（有 null，量不到）"
                            % (rt, rf), measure="房间条目数（台账 vs 交付层快照）"))
    else:
        rep.add(Finding(
            check=did + ".rooms", title="两个房间口径的差（台账 vs 交付层快照）",
            status=Status.WATCH if abs(rt - rf) > 0 else Status.PASS,
            measure="房间条目数：台账 rooms.json 逐栋求和 vs 各层 floor JSON 内 rooms[] 逐层求和",
            detail=("台账 %d ／ 交付层 %d，差 %d —— 两者**本来就不是同一个东西**"
                    "（台账是全量快照，交付层是逐层几何的伴生数组），"
                    "差不为 0 只说明「有房间没进任何一层」，方向要用 C0/A3 分开看"
                    % (rt, rf, rt - rf)),
            evidence={"rooms_total": rt, "rooms_total_from_floors": rf}))


# ── C2 · 产物龄期 ──────────────────────────────────────────────────

def check_c2(rep: Report, data_dir: Path, state: dict) -> None:
    """**派生产物不得比它的上游还旧。**

    ★ 判据是**关系**不是阈值：不设"容忍天数"，只问「下游 mtime < 上游最新 mtime?」。
      魔法数会被下一个改这个文件的人当成可调参数，而这条关系是不可调的。
    ★ 数据来源是 `DERIVED_PAIRS`（登记表），**加一条产物 = 加一行**。
    """
    did = "C2.artifact_aging"
    measure = "mtime 关系（下游 vs 上游最新产物），不比绝对时间"
    pairs = []
    for down_rel, up_rel in DERIVED_PAIRS:
        down = data_dir.parent / down_rel
        up = data_dir.parent / up_rel
        if not down.exists():
            pairs.append({"down": down_rel, "up": up_rel, "verdict": "缺席"})
            continue
        dm = _newest_mtime(down)
        um = _newest_mtime(up)
        if dm is None or um is None:
            pairs.append({"down": down_rel, "up": up_rel, "verdict": "量不到",
                          "down_mtime": _ts(dm), "up_mtime": _ts(um)})
            continue
        pairs.append({"down": down_rel, "up": up_rel,
                      "verdict": "旧" if dm < um else "新",
                      "down_mtime": _ts(dm), "up_mtime": _ts(um),
                      "lag_days": round((um - dm) / 86400.0, 1)})

    stale = [p for p in pairs if p["verdict"] == "旧"]
    missing = [p for p in pairs if p["verdict"] == "缺席"]
    unmeas = [p for p in pairs if p["verdict"] == "量不到"]

    if unmeas:
        rec = Status.UNAVAILABLE
    elif stale:
        rec = Status.WATCH          # 陈旧是"该修"，不是"交付坏了"
    elif missing:
        rec = Status.WATCH
    else:
        rec = Status.PASS

    bits = []
    for p in stale:
        bits.append("%s 比 %s 旧 %.1f 天（%s vs %s）"
                    % (p["down"], p["up"], p["lag_days"], p["down_mtime"], p["up_mtime"]))
    for p in missing:
        bits.append("%s 不存在" % p["down"])
    for p in unmeas:
        bits.append("%s / %s 有一边量不到时间" % (p["down"], p["up"]))
    rep.add(Finding(
        check=did, title="派生产物不得比上游旧", status=rec, measure=measure,
        detail="；".join(bits) if bits else
               "%d 对产物的 mtime 关系全部正常（下游不早于上游）" % len(pairs),
        evidence={"pairs": pairs}))


# ── C3 · 判据名册 ──────────────────────────────────────────────────

def check_c3(rep: Report, data_dir: Path, state: dict) -> None:
    """**有哪些判据存在，谁登记过，这份名册还作不作数。**

    ★ 这条同时回答一个具体问题：`_scratch/` 那 1100 项里，
      **哪些文件其实是系统件、必须收编** —— 不靠人眼看，靠名册对账。
      名册由 `backend/state/roster.py` 生成（扫描 + 人拍板两列）。
      名册不在场 ⇒ **报 UNAVAILABLE**，不许因为"没名册"就给绿灯。

    ## 为什么不能只看 disposition（2026-09-24 自查）

    第一版这条判据**只**数「disposition 为空的条数」，红不了第二遍：
    名册的处置一旦不再有空串（那本身是修好的），这条就**恒绿** ——
    屏幕上一行 PASS，而它已经答不了它被派去回答的问题
    （memory: saturated-criterion-has-no-resolution / 空断言那族）。
    ⇒ 换成两个**能红**的量：①**名册是哪把尺子量的**（名册自记的
      `source_sha256_12` vs 磁盘上 `roster.py` 的现状 —— 改了量具没重跑，
      数就是旧尺子量的，而旧数与新数在屏幕上长得一样，铁律 24）；
      ②**名册指的路径还在不在**（文件改名/搬走而名册没重跑，条目就成了空指针）。
    ⇒ 处置「没拍板」仍数、仍留档，但它现在是**待看**，不是这条判据的全部。
    """
    did = "C3.criteria_roster"
    measure = "判据文件的登记对账（名册 vs 磁盘 vs 名册自记的量具指纹）"
    path = data_dir.parent / ROSTER_REL
    if not path.is_file():
        rep.add(unavailable(
            did, "判据名册对账",
            "没有 %s —— 名册还没生成，**这条量不到**。"
            "生成：`python -u backend/state/roster.py`（会列出全仓疑似判据文件，"
            "每条要人拍板『已登记』还是『一次性探针』）" % ROSTER_REL,
            measure=measure))
        return
    try:
        roster = _read_json(path)
    except (OSError, ValueError) as ex:
        rep.add(unavailable(did, "判据名册对账",
                            "读不动 %s：%s: %s" % (ROSTER_REL, type(ex).__name__, ex),
                            measure=measure))
        return
    entries = roster.get("entries") if isinstance(roster, dict) else None
    if not isinstance(entries, list):
        rep.add(unavailable(did, "判据名册对账",
                            "%s 里没有 entries 列表 —— 形状不是预期" % ROSTER_REL,
                            measure=measure))
        return

    # ① 名册是哪把尺子量的（指纹对不上 ⇒ 盘上的数是旧尺子量的）
    #    ★ 规则取自**生产者**（`roster.sha12`），不在这里再写一份摘要算法。
    from backend.state import roster as _roster
    src = data_dir.parent / ROSTER_SRC_REL
    try:
        cur = _roster.sha12(src.read_bytes())
    except OSError as ex:
        rep.add(unavailable(did, "判据名册对账",
                            "读不动 %s：%s —— 名册是不是**旧尺子**量的，这条量不到"
                            % (ROSTER_SRC_REL, type(ex).__name__), measure=measure))
        return
    recorded = roster.get("source_sha256_12")
    if not isinstance(recorded, str) or not recorded:
        rep.add(unavailable(did, "判据名册对账",
                            "名册里没有 source_sha256_12 —— 哪把尺子量的**这条量不到**"
                            "（缺这个字段的名册是旧版生成的，重跑一次即可）",
                            measure=measure))
        return

    # ② 名册指的路径还在不在（改名/搬走后名册就成了空指针）
    gone = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        rel = e.get("path")
        if isinstance(rel, str) and rel and not (data_dir.parent / rel).exists():
            gone.append(rel)

    undecided = [e.get("path") for e in entries if isinstance(e, dict)
                 and not e.get("disposition")]

    if recorded != cur:
        status, head = Status.GAP, (
            "★名册是**旧尺子**量的：它自记的量具指纹 %s，而 %s 现在是 %s"
            " ⇒ 上面每一条处置都可能不对。重跑：`python -u backend/state/roster.py`"
            % (recorded, ROSTER_SRC_REL, cur))
    elif gone:
        status, head = Status.GAP, (
            "★名册里有 %d 条指的文件已不在磁盘上（改名/搬走而名册没重跑）：%s"
            % (len(gone), "、".join(gone[:6])))
    elif undecided:
        status, head = Status.WATCH, (
            "%d 条里还有 %d 条没拍板（disposition 为空）：%s"
            % (len(entries), len(undecided), "、".join(str(x) for x in undecided[:6])))
    else:
        status, head = Status.PASS, (
            "%d 条判据全部登记过；名册指纹与 %s 一致（%s）"
            % (len(entries), ROSTER_SRC_REL, cur))

    rep.add(Finding(
        check=did, title="判据名册对账", status=status, measure=measure,
        detail=head,
        evidence={"total": len(entries), "undecided": len(undecided),
                  "missing_paths": gone,
                  "roster_sha12": recorded, "current_sha12": cur,
                  "roster_built_at": roster.get("built_at")}))


#: 编号 → 函数。**注册表那边（`__init__.CHECK_REGISTRY`）只存元信息，实现在这里。**
CHECKS = {"c0": check_c0, "c1": check_c1, "c2": check_c2, "c3": check_c3,
          "c4": check_c4}


def run_all(data_dir: Path, state: dict | None = None) -> Report:
    """跑完 C0–C4。`state` 不传就现算一份（census 是唯一口径计算者）。

    ★ C4 不看 `state`（它读的是图谱自己的产物），但同样收下这个参数 ——
    签名一致比"按需裁剪"重要：`run_all` 里的统一调度靠的就是四个参数同形。
    """
    passed_in = state is not None
    from backend.state import census            # C0 与 meta 都要用，无条件导入
    if state is None:
        state = census.compute()
    rep = Report(scope="system")
    for cid in sorted(CHECKS):
        try:
            CHECKS[cid](rep, data_dir, state)
        except Exception as ex:                        # noqa: BLE001
            # 量具自己崩了 ⇒ UNAVAILABLE，不是 PASS 也不是 GAP。
            rep.add(unavailable("C%s" % cid[1].upper(), "系统级判据 %s" % cid,
                                "量具自身崩溃：%s: %s" % (type(ex).__name__, ex)))
    rep.meta.update({
        "layer": "C",
        # ★ 两个「账本」必须**分开写名**：`state` 入参在 runner 路径下是现算的，
        #   它的 built_at 恒为 None（census.compute() 是纯函数），而 C0.ledger 读的是
        #   **磁盘上那份**。不分开写，载荷里「账本没写 built_at」与
        #   「本次是现算的」长得一模一样 —— 又是一处 template-string-prints-undefined。
        "census_source": "传入" if passed_in else "现算",
        "census_built_at": state.get("built_at"),
        "census_criterion_version": state.get("criterion_version"),
        "ledger_path": str(census.STATE_PATH),   # C0.ledger 读的就是它（恒有意义）
    })
    return rep


if __name__ == "__main__":
    # 单独跑 C 层（调试用）。正式入口是 `runner.py` 的全库航拍。
    # ★ 本文件用**相对导入**（与 `__init__.py` 一致），所以调用式必须是
    #   `python -m backend.checks.system`（在仓库根下跑），**不能**写成
    #   `python backend/checks/system.py` —— 那样 `__package__` 是 None，
    #   相对导入在**模块加载时**就炸，而报错信息会误导你去查 import 路径。
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from backend.paths import DATA
    r = run_all(DATA)
    d = r.as_dict()
    print("verdict=%s  %s" % (d["verdict"], d["counts"]))
    for f in r.findings:
        print("[%s] %s" % (f.status.value.upper(), f.title))
        if f.detail:
            print("     " + f.detail)
    # 退出码必须跟着结论走 —— 否则「红了」只活在打印里，
    # 而任何拿它进门禁的地方都会看到 0（本仓 memory: 退出码进不了门禁那族）。
    sys.exit(1 if d["verdict"] == "fail" else 0)
