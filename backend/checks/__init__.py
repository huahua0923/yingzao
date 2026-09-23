# -*- coding: utf-8 -*-
"""系统自带检查 —— 判据长在系统里，智能体只是执行者。

## 为什么必须"长在系统里"

智能体是"人"：会累、会漏、会被上一轮的结论带跑、会在没数据时顺着话头编一个。
工程上的规矩是反过来的 —— **检查是"规"，不跑也得跑；红了就是红**，
不因为这一轮有没有智能体在看而改变。所以：

  · 每条检查是一个**纯函数**：输入是磁盘上的产物，输出是 `Finding`。
    没有智能体也能跑（`python -u backend/checks/runner.py c113`）。
  · 检查之间**不共享状态**，也不依赖上一轮结论 —— 每次都是从头量一遍。
  · **智能体不许自己判**：它只能调这里的检查，然后把结果讲给人听。
    一条判据只有一份实现（memory: one-judgement-many-implementations 那类坑）。

## 两层，为什么

  · **A 层（builtin）**：只要标准库。产物清单、房间台账、交付快照一致性、
    白名单成员、对账快照比对。**只服务模式（服务器上没有 ezdxf/shapely）也能跑**
    —— 服务器上的后台不能"因为装不起依赖所以什么都不检查"。
  · **B 层（heavy）**：要 ezdxf/shapely，且要读 DXF。**逐栋起子进程跑**
    （`isolation=True`）。这一条是血的教训：qa_structural 全库跑曾在 c009 上
    被 `buffer(0)` 炸出的 MultiPolygon 抛异常**中断整轮**，于是 c009 之后的楼
    从来没被检查过，而汇总只报了一句"崩在 c009"（memory: qa-structural-fullrun-dies-at-c009）。
    隔离之后，c009 崩 → 它自己报 UNAVAILABLE，其余楼照常出结论。

## 「没量成」不等于「通过」

见 findings.py。汇总时 UNAVAILABLE 会把整组拉成 INCOMPLETE，不给绿灯。
"""
from __future__ import annotations

from .findings import Finding, Report, Status, Verdict, unavailable

__all__ = ["Finding", "Report", "Status", "Verdict", "unavailable",
           "run_building_checks", "run_fleet_checks", "CHECK_REGISTRY"]


# 注册表：编号 → (标题, 层, 是否逐栋, 是否要外部进程)
# 说明写在每条检查自己的 docstring 里；这里只登记元信息，供前端列"这台机器能跑哪几条"。
CHECK_REGISTRY = {
    # ── A 层：标准库，永远能跑 ──────────────────────────────
    "A1": ("房间台账非空", "A", True,
           "profile 存在却没有一间房 —— 交付了 0 间，而图纸上写着有。"),
    "A2": ("逐层房间数 vs 图纸房间数", "A", True,
           "用图纸自带的面积表（ACAD_TABLE 的『房间数』列）当裁判。"),
    "A3": ("交付楼层的 rooms 快照与台账一致", "A", True,
           "floor JSON 里的 rooms[] 是**快照**，台账改了没补跑 backfill 就会不一致。"),
    "A4": ("产物齐备", "A", True,
           "逐层几何 / 模型 / 图纸渲染 / 规格 / 台账 各在不在。"),
    "A5": ("模型是否陈旧", "A", True,
           "★ 本条**故意**只报 UNAVAILABLE：按 mtime 判陈旧已被实测否掉"
           "（漏了 28/48 栋），真判据是现码重出比 sha256。"),
    "A6": ("房间号段白名单成员", "A", True,
           "读 extract_rooms_generic.py 的 ID_BASE（用 ast，不 import），"
           "不在表里 ⇒ 房间抽取整条链不会为它跑。"),
    "A7": ("逐层楼板面积 vs 图纸建筑面积", "A", True,
           "两个不同口径（足迹 vs 建筑面积），判据是同量级 + 逐层趋势，不是相等。"),
    "A8": ("配置项是否真的被加载器读取", "A", True,
           "profile.json 里写着的键，加载器是否真的传给了识别 —— 死配置是静默的。"),
    "A9": ("房号字段是不是房号", "A", True,
           "★ A1/A2/A3 量的都是**条数**，对『这一列装错了东西』完全无感。"
           "实测：c046 有 168 间的房号就是『卫』字本身，c113 F3 混进了 "
           "`14-*`/`06-*` 两个别的号段。"),
    # ── B 层：要建模环境，逐栋子进程 ────────────────────────
    "B1": ("结构不变量 I1–I18（qa_structural）", "B", True,
           "调 qa_structural.py，**不改它**（用户明令：门禁是诚实的裁判，不许挪球门）。"),
    "B2": ("轮廓环有效性", "B", True,
           "用 shapely 当参考实现判环是否有效。**不许自己写判自交的算法** —— "
           "实测自制版会漏掉 c009 的崩溃因、还会误报 9 例有效环。"),
    "B3": ("图上房号 vs 台账房间", "B", True,
           "★ A1/A2/A3/A9 量的都是**台账内部**的自洽（条数、字段形态、快照一致），"
           "看不见『图上还有一间、台账里根本没有它』—— 台账自己不会喊少了谁。"
           "实测 c113：图上印着 114 个本栋号，台账只有 97 个，丢的 17 间"
           "（实验室/服装间/道具间/化妆间/空调机房/专业教室…）在 A 层**一条红都不亮**。"
           "判据用抽取器自己的层名解析与文字清洗（不另写一份），"
           "并先把『台账里已有的号能不能落回自己那间』当闸门 —— 标定不住就报 UNAVAILABLE。"),
    "B4": ("图纸声明的楼层 vs 模型楼层", "B", True,
           "★ 用户点过一句「水上图书馆，f0其实是两层」，查下去是**整层没进模型**："
           "图上 6 层（D1 + 1~5），模型 5 层，D1 那层 6 间房压根不在。"
           "全库量下来 17 栋图纸层多于模型层，且**成类** —— 层号不是纯数字时"
           "（D1/J11/H）会被静默丢掉（`ROOM_RE` 的层号字段写死 `\\d{1,2}`）。"
           "本条的读数是图纸自带的面积表（外部真值），与 A2 同源但问的是层数。"),
}


def run_building_checks(data_dir, name: str, which: tuple[str, ...] | None = None,
                        heavy: bool = False, timeout_s: int = 600) -> Report:
    """跑一栋楼的检查。heavy=False 时只跑 A 层（不需要建模环境）。

    判据要的"外部数"由检查自己去 `sources.py` 读产物 —— 不从这里传进来。
    理由：传进来的东西可以是任何一环给的，读产物则谁都改不了（用户明令：
    判据长在系统里，"不是随时问智能体"）。
    """
    from . import builtin, heavy as heavy_mod
    rep = Report(scope="building:%s" % name)
    ids = which or tuple(CHECK_REGISTRY)
    for cid in ids:
        if cid not in CHECK_REGISTRY:
            rep.add(unavailable(cid, "未知检查", "注册表里没有这条检查：%s" % cid))
            continue
        _title, tier, _per, _why = CHECK_REGISTRY[cid]
        mod = builtin if tier == "A" else heavy_mod
        if tier == "B" and not heavy:
            # 明确登记为"这一轮没跑"，而不是静默缺席。
            # ★ 前端要能区分"跑了且过"和"这轮压根没跑"。
            rep.add(unavailable(cid, _title,
                                "本轮只跑了 A 层（heavy=False）；"
                                "要跑 B 层加 --heavy（需要 ezdxf/shapely + 源 DXF）"))
            continue
        fn = getattr(mod, "check_%s" % cid.lower(), None)
        if fn is None:
            rep.add(unavailable(cid, _title, "实现缺失：%s.check_%s" % (mod.__name__, cid.lower())))
            continue
        try:
            fn(rep, data_dir, name, timeout_s=timeout_s)
        except Exception as ex:                       # noqa: BLE001
            # 检查自己崩了 ⇒ 报 UNAVAILABLE（不是 PASS！也不是 GAP ——
            # 我们不知道是对是错，只有一个坏掉的量具）。
            rep.add(unavailable(cid, _title,
                                "量具自身崩溃：%s: %s" % (type(ex).__name__, ex)))
    rep.meta.update({"layer": "A+B" if heavy else "A", "building": name})
    return rep


def run_fleet_checks(data_dir, names: list[str], heavy: bool = False,
                     timeout_s: int = 600) -> Report:
    """全库航拍：只跑**不依赖单栋重活**的那些，用来做红绿灯墙。

    逐栋 B 层要 N 次子进程，全库跑请走 runner.py（它会落盘成产物）。
    """
    from . import builtin
    rep = Report(scope="fleet")
    ids = [c for c, (_t, tier, per, _w) in CHECK_REGISTRY.items() if tier == "A"]
    per_check: dict[str, list[tuple[str, Finding]]] = {}
    wall: dict[str, Finding] = {}
    for name in names:
        sub = Report(scope="building:%s" % name)
        for cid in ids:
            fn = getattr(builtin, "check_%s" % cid.lower(), None)
            if fn is None:
                continue
            try:
                fn(sub, data_dir, name)
            except Exception as ex:                   # noqa: BLE001
                sub.add(unavailable(cid, CHECK_REGISTRY[cid][0],
                                    "%s: %s" % (type(ex).__name__, ex)))
        # 把逐栋结论压成整栋一行，挂到全库报告上（不展开每条 finding，太大）
        rep.add(Finding(check="fleet." + name, title=sub.meta.get("title") or name,
                        status=(Status.GAP if sub.rollup() == Verdict.FAIL.value
                                else Status.UNAVAILABLE if sub.rollup() == Verdict.INCOMPLETE.value
                                else Status.WATCH if sub.rollup() == Verdict.WATCH.value
                                else Status.PASS),
                        detail="、".join(f.title for f in sub.findings
                                        if f.status in (Status.GAP, Status.WATCH,
                                                        Status.UNAVAILABLE))[:300],
                        evidence={"counts": sub.counts()}))
        for f in sub.findings:
            per_check.setdefault(f.check, []).append((name, f))

    # ── 再按**检查编号**压一遍：这才是给眼睛看的红绿灯墙 ──────────
    # ★ 为什么必须有这一层：一条判据在 95 栋上全亮时，"逐栋 95 行"等于没信息量
    #   —— 屏幕上永远是一片红，人就学会不看了（memory:
    #   append-only-ledger-whole-table-assertion：永久红的判据会被忽略）。
    #   按编号压成一行，才能看出"A6 亮 45 栋、A3 亮 13 栋"这种**有形状**的分布。
    for cid in sorted(per_check, key=_check_sort_key):
        rows = per_check[cid]
        title = CHECK_REGISTRY.get(cid, (cid,))[0]
        dist = {}
        for _n, f in rows:
            dist[f.status.value] = dist.get(f.status.value, 0) + 1
        bad = [(n, f) for n, f in rows
               if f.status in (Status.GAP, Status.WATCH, Status.UNAVAILABLE)]
        status = (Status.GAP if any(f.status == Status.GAP for _n, f in rows)
                  else Status.WATCH if any(f.status == Status.WATCH for _n, f in rows)
                  else Status.UNAVAILABLE if any(f.status == Status.UNAVAILABLE
                                                 for _n, f in rows)
                  else Status.PASS)
        # 按"原因"归并：同一个原因串下面的楼号列在一起（这才是可下手的形状）
        # ★ 计数必须**说清单位**：A1/A6 是整栋级，一条一栋；A2/A3 改成逐层出结论后，
        #   一条一层，一个楼可能贡献 11 条。屏幕上光写 "×48" 会被读成 48 栋
        #   —— 量具报了个对不上单位的数，比不报还坏。所以楼数与层数分开写。
        # 每格是 (楼名, 层, 状态)。★ 状态必须带上：同一个原因串下会混着
        # 不同状态（A9 实测 6 栋里 1 栋 gap、5 栋 watch），不带就分不出来。
        by_reason: dict[str, list[tuple[str, int | None, Status]]] = {}
        for n, f in bad:
            by_reason.setdefault(f.title, []).append((n, f.floor, f.status))
        parts = []
        for t, ns in sorted(by_reason.items(), key=lambda kv: -len(kv[1]))[:4]:
            b = len({n for n, _f, _s in ns})
            # ★★ 层数必须是**逐层结论的条数**，不能拿 `len(ns)` 充数 ——
            #   第一版就是拿 len(ns) 当层数，而 ns 里还夹着每栋一条的**整栋汇总行**
            #   （floor=None），于是 A7 打出"22栋(47层)"，而逐层结论实际只有 25 条：
            #   47 = 25 层 + 22 条汇总行。屏幕上完全看不出来 ——
            #   这正是我先修过一次的那个毛病（量具报了个单位对不上的数），
            #   只是藏得更深一层：单位分了"栋"和"层"，却把"条"当成了"层"。
            nf = len([1 for _n, f, _s in ns if f is not None])
            base = "%s×%d栋" % (t, b) if nf == 0 else "%s×%d栋(%d层)" % (t, b, nf)
            # ★ 同一个原因串下面可能**混着不同状态**（A9 实测：6 栋里 1 栋是 gap、
            #   5 栋是 watch，而整行标的是最严的 gap）。光看"×6栋"会以为 6 栋
            #   都是那个严重毛病 —— 又是一个"数没说清它是什么"。混着就把拆分写上，
            #   且按**栋**算最严状态，不按条数（条数里夹着整栋汇总行）。
            worst: dict[str, Status] = {}
            sev = {Status.GAP: 0, Status.WATCH: 1, Status.UNAVAILABLE: 2}
            for n, _f, st in ns:
                if n not in worst or sev.get(st, 9) < sev.get(worst[n], 9):
                    worst[n] = st
            st_n: dict[str, int] = {}
            for s in worst.values():
                st_n[s.value] = st_n.get(s.value, 0) + 1
            mix = ""
            if len(st_n) > 1:
                mix = "〔" + "、".join(
                    "%s %d栋" % (k, v) for k, v in
                    sorted(st_n.items(),
                           key=lambda kv: ({"gap": 0, "watch": 1,
                                            "unavailable": 2}.get(kv[0], 9), kv[0]))) + "〕"
            parts.append(base + mix)
        wall[cid] = rep.add(Finding(
            check="fleet.check." + cid, title=title, status=status,
            detail="；".join(parts) if bad else "全库无异常",
            measure=rows[0][1].measure,
            evidence={"dist": dist,
                      "affected": {t: sorted({n for n, _f, _s in ns})
                                   for t, ns in by_reason.items()},
                      "affected_floors": {t: ["%s:F%s" % (n, f) for n, f, _s in ns
                                              if f is not None]
                                          for t, ns in by_reason.items()}}))

    # ── 同因合并：两条判据亮的是**同一批楼** ⇒ 屏幕上看着是两个毛病，先查是不是一个 ──
    # ★ 这是 A1/A6 的实测：45 栋两边完全一致 —— 根因其实只有一个（不在 ID_BASE 白名单里，
    #   于是房间抽取整条链不为它跑，台账当然是空的）。不标出来，红绿灯墙会把
    #   "1 个根因"显示成"2 条判据挂了"，人就会去修两遍（而且第二遍无处下手）。
    # ★★ 但"集合相同"只是**同因的线索，不是同因本身** —— 第一版就栽在这：
    #   A5/A7/A8 都在 95 栋上亮，可三个原因毫不相干（A5 是**故意**永远 UNAVAILABLE，
    #   A7 是还没有图纸明细，A8 是加载器分叉）。集合相等把它们判成"同一个根因"，
    #   正是我反复栽的那种坑：**拿代理量（集合相等）代替真对象（原因相同）**。
    #   所以只对"确实量到了问题"的那两档（GAP/WATCH）提这个醒，且要求它**不是全库**
    #   —— 一条判据在每一栋上都亮，说明的是这条判据宽，不是大家同因。
    #   措辞也必须是"先查"而不是"就是"：引擎没有判根因的能力，别替人下结论。
    sets = {cid: frozenset(n for t, ns in f.evidence.get("affected", {}).items() for n in ns)
            for cid, f in wall.items()}
    groups: dict[frozenset, list[str]] = {}
    for cid, s in sets.items():
        if s and len(s) < len(names) and wall[cid].status in (Status.GAP, Status.WATCH):
            groups.setdefault(s, []).append(cid)
    for s, cids in groups.items():
        if len(cids) < 2:
            continue
        for cid in cids:
            f = wall[cid]
            others = "/".join(c for c in sorted(cids, key=_check_sort_key) if c != cid)
            f.detail += "　⟵ 与 %s 亮的是**同一批 %d 栋**（状态也相同）：先查是不是一个根因，别当两件事修" % (others, len(s))
            f.evidence["same_cause_suspect"] = sorted(c for c in cids if c != cid)
    return rep


def _check_sort_key(cid: str) -> tuple:
    """A1 < A2 < ... < A10 < B1（按层再按数字，不按字符串）。"""
    tier = cid[0]
    rest = cid[1:]
    num = int(rest) if rest.isdigit() else 99
    return (tier, num, cid)
