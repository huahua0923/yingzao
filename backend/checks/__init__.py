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
           "run_building_checks", "run_fleet_checks", "run_system_checks",
           "CHECK_REGISTRY"]


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
    "A10": ("CAD 速览图齐备且不陈旧", "A", True,
            "★ A4 里 CAD 那一件判的是**在不在**（`any(floor*.png)`）：一张不剩才算缺，"
            "少一张、或是上一版布局渲染的，A4 都是绿的。本条判同一个产物的另一件事。"
            "实测 c001 的现场：2026-09-23 补了一层、09-24 重切 `floors/`，"
            "**而出图是带外手工步骤、没人重跑** ⇒ 盘上 5 张图整批错位一格、F5 从没有过图，"
            "而全库 33/95 栋同病（4 栋尺寸级 + 29 栋墨迹级）。"
            "★ 层数**只从 `floors/floorN.json` 数**（遇到第一个缺号就停，与出图脚本同口径），"
            "**绝不读 `profile.json` 的 `floor_ys`** —— 旧审计器 `_plan_png_audit.py` ④ 正是"
            "读它，而 `floor_plans` 制式的楼那里是 `None` ⇒ 那条腿对它们从不下手。"
            "两条腿：①张数（线段非空的层 vs 图，另抓孤儿图）②宽高比 vs 该层线段 bbox。"
            "**故意不判 mtime**：按 mtime 判陈旧在本仓已被实测证伪（见 A5）。"),
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
    "B5": ("建好后墙级对账（①漏墙 ②多建/歪建 ③曲要素）", "B", True,
           "★ 以上 B1–B4 问的都是**台账内部**或**建之前**的事：B1 的 I1–I18 全部在"
           "**交付模型内部**成立（墙厚对、房间闭合、柱网齐），于是交付模型可以一整片墙"
           "都没建而 B1 全绿；B2 问轮廓环、B3 只对房号、B4 只对层数。**没有一条拿图纸当"
           "裁判去问『这一段墙到底建了没有』**。本条补的就是这一条：图纸墙线采样点与交付墙"
           "几何逐层对账，两个方向都问（①图纸有交付没有＝漏、②交付有而任何图层都找不到＝"
           "多建/歪建），外加 ③曲要素单列。判定看引擎扣掉「参考集把弧弦化」之后的档"
           "（①真实档 / ②E类），总账照样报出来。"),
    "B6": ("同一房号被标注两次（同层画了两份）", "B", True,
           "★ B1 的 I8/I1/I10 与 B3 报的都是**后果**（楼层几何中心相距 180 m、柱跑到"
           "轮廓外 179.7 m、图上有的台账没有），本条报**成因**：图上同一层被画了两份，"
           "而 `x_range` 把两份都收了进来。实测 c011（2026-09-29）：F0 的平面在左列"
           "（x≈1356930）与右列（x≈1536870）各一份，相隔 **180000 mm** 整，21 个房号"
           "**逐号同名**，墙 373/373 条 —— 四处症状一个根因。只量**模型收进来的范围**"
           "（`in_floor_x_range`）内的标注：右列本来就该被排除，排除它正是修法。"),
    # ── C 层：**系统级**，不逐栋（per_building=False）─────────
    # 与 A/B 的分界只有一条：**A/B 逐栋问，C 整库问**。
    # 有些毛病逐栋检查**结构上就看不见** —— 每一栋单独看都对、合起来对不上；
    # 或同一个事实有两个来源各自自洽。这就是 C 层存在的理由。
    "C0": ("系统完整性（账本/整体=各栋之和/四件套/无孤儿）", "C", False,
           "★ 用户那句「不像一个系统那么完整」的可执行版（2026-09-24）。"
           "只问四件逐栋问不到的事，不重复 A 层已经问过的。"),
    "C1": ("口径自洽（同一事实的多个来源必须相等）", "C", False,
           "★ 本仓实测「全库几层」有**六个**答案（456/12/1946/2414/468/642），"
           "**六个全是对的**，缺的是没写下来的口径。这条把分歧变成红。"),
    "C2": ("产物龄期（派生产物不得比上游旧）", "C", False,
           "判据是**关系**不是阈值：不设容忍天数，只问「下游 mtime < 上游最新 mtime?」。"),
    "C3": ("判据名册（哪些判据存在、谁登记过）", "C", False,
           "没有一条判据能检查「还有哪些判据没人知道」。"
           "同时算出 `_scratch/` 里哪些文件其实是系统件、必须收编 —— 不靠人眼看。"),
    "C4": ("图谱引用可核（`kb/` 的边还指着原处吗、实例层是不是对着当前源）", "C", False,
           "★ 补的是最后一条缝：图纸全对、台账全对、名册全对，**图谱仍然可能全错**。"
           "`kb/` 里 99 条边逐条指着「文件:行 / 文件:符号」，源一改那条边就可能指空 ——"
           "而 A/B 层逐栋看几何、C0–C3 看账本，**没有一条看得见这件事**。"
           "它不自己判，只去跑图谱自己的门禁（`kb/gate.py` ＋ `kb/derive.py`）"
           "再把结论翻译成 Finding —— 一把尺子一个实现。"),
    "C5": ("影像比对图「框 ↔ 图」对口（清单说的那块地，图上真的是那块地吗）", "C", False,
           "★ 补的是「一份产物**自己内部**的两半对不对得上」这一格 —— 前四条问的都是"
           "**产物之间**的关系，而 2026-09-25 那次漏检两半都在同一份清单里。"
           "校区大图与它的 `bbox` 是**两处各算一个值**，各自自洽、页面一片正常，"
           "实测沿经度差 **2 块瓦片 = 512 px ≈ 526 m**（11 个点位全偏）。"
           "它**只依赖 `bbox`** 就能重拼出该显示的那块地再逐像素比 ⇒ **旧清单也能直接红**，"
           "这既是它值钱的地方，也是它自带的阳性对照。"
           "跑法：`python -m backend.checks.compare_geo --selftest`。"),
    "C6": ("冻结载荷的出身（服务器读的那份 `console_meta.json` 是哪一版源码产的）", "C", False,
           "★ 补的是「**正在送给另一台机器的那份契约**还是不是当前源码产的」这一格。"
           "`data/_meta/console_meta.json` 是冻结载荷（服务器 venv 不带 trimesh/numpy，"
           "`compute=0` 那一路的帮助文字/阶段表/选项表全来自它），它会跟源码脱节 ——"
           "而**脱节之后服务照常 200、页面照常渲染**。实测 2026-09-26：它是 2026-09-11 产的，"
           "服务器端因此少 3 个阶段、整个 `selfCheck` 块都没有，**没有一条判据看得见**。"
           "摘要算法取自生产者：在子进程里调 `freeze_meta.source_hash()`，比较写在本判据里"
           "（与 C3 同形）。"
           "★ **不用生产者的 `--check`**：它先跑构建期门禁，门禁不过就返回 1、到不了比对分支"
           "（实测 2026-09-26 rc=1 是「门禁 18 条不过」，输出里 `--check:` 字样 0 处）"
           "⇒ 那个退出码同时背着两个判断，照抄会把「门禁不过」印成「载荷过期」，"
           "而刷新载荷也清不掉它。子进程没给出指纹时记 UNAVAILABLE，不是 GAP（铁律 16）。"),
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
    # 不指名时只跑**逐栋**的判据；C 层是系统级的，在这里跑没有意义。
    ids = which or tuple(c for c, m in CHECK_REGISTRY.items() if m[2])
    for cid in ids:
        if cid not in CHECK_REGISTRY:
            rep.add(unavailable(cid, "未知检查", "注册表里没有这条检查：%s" % cid))
            continue
        _title, tier, per_building, _why = CHECK_REGISTRY[cid]
        if not per_building:
            # ★ 显式登记为 NOT_APPLICABLE，而不是让它掉进"实现缺失"那条分支 ——
            #   「本来就不该在逐栋报告里出现」和「实现没写」是两件完全不同的事，
            #   屏幕上却长得一样（本仓反复栽的那一族）。C 层只在全库航拍里跑。
            rep.add(Finding(check=cid, title=_title, status=Status.NOT_APPLICABLE,
                            detail="系统级判据：逐栋报告里不跑，见 runner.py 全库航拍"))
            continue
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
    # 层级标签与全库航拍同规矩：由**真跑过的层**导出（被 UNAVAILABLE 挡住的那层不算跑过）。
    ran = sorted({CHECK_REGISTRY[f.check][1] for f in rep.findings
                  if f.check in CHECK_REGISTRY
                  and f.status != Status.NOT_APPLICABLE
                  and not (f.status == Status.UNAVAILABLE
                           and (f.detail or "").startswith("本轮只跑了"))})
    rep.meta.update({"layer": "".join(ran) or "**一层都没跑**", "building": name,
                     "tiers_ran": ran})
    return rep


def run_fleet_checks(data_dir, names: list[str], heavy: bool = False,
                     timeout_s: int = 600) -> Report:
    """全库航拍：逐栋跑**登记在册的**判据，再按检查编号压成红绿灯墙。

    `heavy=True` 时 **B 层也在内**（每栋一次子进程/DXF，慢）。

    ★ 这一段以前是假的（2026-09-24 实测）：`heavy` 形参**收了却一次没被读**，
      `ids` 只挑 `tier == "A"`，而 runner 拿到 `--heavy` 就把 `meta.layer` 写成
      `"A+B(逐栋) + C(系统级)"` ⇒ **产物在替一次没发生的检查作证**：全库 B 层
      （＝「建好后墙级对账」那条腿）**一次都没跑过**，而表上写着跑过、
      退出码也照样给。这正是本仓反复记的那一族（铁律 17「写好的函数不等于被调用的
      函数」＋铁律 20「形式检查通过、语义没发生」）。
    ⇒ 两条一起改：**B 层真的跑**；**层级标签一律由"真跑出来的层"导出**，
      不再由开关猜（`meta["tiers_ran"]`）。
    """
    from . import builtin
    heavy_mod = None
    tiers = ("A",)
    if heavy:
        # 只有真要跑 B 层才 import 它 —— A 层不该被拖上 ezdxf/shapely 的依赖。
        from . import heavy as heavy_mod
        tiers = ("A", "B")
    rep = Report(scope="fleet")
    ids = [c for c, (_t, tier, per, _w) in CHECK_REGISTRY.items()
           if tier in tiers and per]
    tiers_ran: set[str] = set()
    per_check: dict[str, list[tuple[str, Finding]]] = {}
    wall: dict[str, Finding] = {}
    for name in names:
        sub = Report(scope="building:%s" % name)
        for cid in ids:
            tier = CHECK_REGISTRY[cid][1]
            fn = getattr(builtin if tier == "A" else heavy_mod,
                         "check_%s" % cid.lower(), None)
            if fn is None:
                # 实现缺失 ⇒ 这个层**没跑**，标签里就不许算上它。
                continue
            tiers_ran.add(tier)     # 判据成立了就算"跑过"；崩了/UNAVAILABLE 由行里说
            try:
                fn(sub, data_dir, name, timeout_s=timeout_s)
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
        # ★ `len(s) >= 2` 这道下限也是实测加的：只亮**一栋**时，两条毫不相干的判据
        #   撞进同一个集合的概率高得离谱（实测两栋的航拍里，B5 的「曲要素盲区」与
        #   A9 的「房号字段」当场被凑成一对，屏幕上写着「与 A9 亮的是同一批 1 栋」）。
        #   一栋的巧合不携带任何信息 —— 拿它去提示"先查是不是一个根因"，只会教人
        #   学会不看这条提示。
        if len(s) >= 2 and len(s) < len(names) and wall[cid].status in (Status.GAP, Status.WATCH):
            groups.setdefault(s, []).append(cid)
    for s, cids in groups.items():
        if len(cids) < 2:
            continue
        for cid in cids:
            f = wall[cid]
            others = "/".join(c for c in sorted(cids, key=_check_sort_key) if c != cid)
            f.detail += "　⟵ 与 %s 亮的是**同一批 %d 栋**（状态也相同）：先查是不是一个根因，别当两件事修" % (others, len(s))
            f.evidence["same_cause_suspect"] = sorted(c for c in cids if c != cid)
    # ★ 层级标签的**唯一出处**：真被调用过的层。runner 只许读这个值去写 `meta["layer"]`，
    #   不许再看 `--heavy` 开关 —— 开关说的是"想跑什么"，这里说的是"真跑了什么"。
    rep.meta["tiers_ran"] = sorted(tiers_ran)
    return rep


def run_system_checks(data_dir, state: dict | None = None) -> Report:
    """C 层：**系统级**判据（整库问，不逐栋）。

    与逐栋检查的分界只有一条：**A/B 逐栋问，C 整库问。**
    有些毛病逐栋结构上看不见 —— 每一栋单独看都对、合起来对不上；
    或同一个事实有两个来源，各自自洽却互相不等。这条缝隙只有 C 层能堵。

    `state` 不传就现算一份 `census.compute()`（唯一口径计算者）。
    四个检查共用这一份，**不在这里重数**（C 层只做比较，不做计数）。
    """
    from . import system as system_mod
    return system_mod.run_all(data_dir, state=state)


def _check_sort_key(cid: str) -> tuple:
    """A1 < A2 < ... < A10 < B1（按层再按数字，不按字符串）。"""
    tier = cid[0]
    rest = cid[1:]
    num = int(rest) if rest.isdigit() else 99
    return (tier, num, cid)
