# -*- coding: utf-8 -*-
"""检查引擎的命令行入口 —— **没有智能体也能跑**。

    python -u backend/checks/runner.py                     # 全库 A 层（快，只读产物）
    python -u backend/checks/runner.py c113                # 一栋
    python -u backend/checks/runner.py c113 c009 c103      # 几栋
    python -u backend/checks/runner.py --all --heavy       # 全库 A+B（逐栋子进程，慢）
    python -u backend/checks/runner.py --audit-all         # 先把图纸里的逐层数取出来落盘
    python -u backend/checks/runner.py c113 --json         # 只打 JSON，给管道用

★ 本仓的脚本**不用 argparse**，靠 sys.argv 手解析（CLAUDE.md 铁律 9：传 --help 会被
当成楼名或直接忽略 → 按默认参数全量执行）。所以这里也手解析，且**开关只认白名单**，
剩下的位置参数才当楼名 —— 不认识以 `-` 开头的东西一律报错退出，绝不"忽略并跑全库"。

产物落在 `data/_meta/checks/<scope>.json`（原子写）。它同时是后台的读取源：
后台只读产物，不现场跑 B 层（一次 95 栋子进程要几十分钟，HTTP 请求等不起）。
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2])]   # 供 backend.checks 导入

from backend.checks import CHECK_REGISTRY, run_building_checks, run_fleet_checks  # noqa: E402
from backend.checks.findings import Verdict  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_REL = os.path.join("data", "_meta", "checks")

_FLAGS = {"--heavy", "--all", "--json", "--quiet", "--audit-all", "--selftest"}


def _parse(argv: list[str]) -> tuple[set[str], list[str]]:
    flags, names, bad = set(), [], []
    for a in argv:
        if a.startswith("-"):
            (flags.add(a) if a in _FLAGS else bad.append(a))
        else:
            names.append(a)
    if bad:
        # 不认识的开关 → 直接退出。**不许"忽略然后按默认跑全库"**
        # —— 铁律 9 记着两次这样受伤的事（--help 触发全库重投递）。
        raise SystemExit("不认识的开关：%s\n可用：%s"
                         % ("、".join(bad), "、".join(sorted(_FLAGS))))
    return flags, names


def _all_names() -> list[str]:
    base = DATA_DIR / "buildings"
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir()
                  if (d / "profile.json").is_file())


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _bar(counts: dict[str, int]) -> str:
    """一行红绿灯。**没量成必须能被看见**（UNAVAILABLE 单独一档，不并进 pass）。"""
    keys = ("pass", "watch", "gap", "unavailable", "na")
    return "  ".join("%s=%d" % (k, counts.get(k, 0)) for k in keys if counts.get(k))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    flags, names = _parse(sys.argv[1:])
    quiet = "--quiet" in flags or "--json" in flags

    if "--selftest" in flags:
        return _selftest()

    if "--audit-all" in flags:
        # 先把图纸里"只有画图人知道"的那两列取出来落成产物（A2/A7 的裁判）。
        from backend.checks import sources
        todo = names or _all_names()
        if not quiet:
            print("取图纸逐层数：%d 栋（跑 _area_audit.py，可能要几分钟）" % len(todo))
        t0 = time.time()
        payload = sources.refresh_detail(DATA_DIR, todo)
        if not quiet:
            print("落盘 %s（%d 栋，%.1fs）"
                  % (sources.detail_path(DATA_DIR), payload["count"], time.time() - t0))
        return 0

    heavy = "--heavy" in flags
    names = names or _all_names()
    if not names:
        print("没有可检查的楼（%s 下没有 profile.json）" % (DATA_DIR / "buildings"))
        return 2

    if len(names) == 1:
        rep = run_building_checks(DATA_DIR, names[0], heavy=heavy)
        scope = "building-%s" % names[0]
        payload = rep.as_dict()
    else:
        rep = run_fleet_checks(DATA_DIR, names, heavy=heavy)
        scope = "fleet"
        payload = rep.as_dict()
    payload["generated_unix"] = time.time()
    payload["generated_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
    payload["heavy"] = heavy
    out = DATA_DIR / "_meta" / "checks" / ("%s.json" % scope)
    _atomic_json(out, payload)

    if not quiet:
        _print_report(rep, names)
        print("产物：%s" % out)
    if "--json" in flags:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0 if payload["verdict"] != Verdict.FAIL.value else 1


def _print_report(rep, names: list[str]) -> None:
    d = rep.as_dict()
    print("=" * 74)
    print("检查引擎（系统自带）  范围 %s  %d 栋" % (d["scope"], len(names)))
    print("  结论 %s   交付拦阻：%s   计数 %s"
          % (d["verdict"].upper(), "有" if d["blockers"] else "无", _bar(d["counts"])))
    print("-" * 74)
    # 全库模式：一栋一行；单栋模式：逐条（含逐层）
    if d["scope"] == "fleet":
        wall = [f for f in d["findings"] if f["check"].startswith("fleet.check.")]
        rows = [f for f in d["findings"]
                if f["check"].startswith("fleet.") and not f["check"].startswith("fleet.check.")]
        if wall:
            print("逐条判据（全库）")
            for f in wall:
                cid = f["check"].rsplit(".", 1)[1]
                print("  [%-11s] %-4s %-14s %s"
                      % (f["status"], cid, f["title"], f["detail"][:60]))
            print("-" * 74)
        worst = {"gap": 0, "unavailable": 1, "watch": 2, "pass": 3, "na": 4}
        byt: dict[str, list] = {}
        for f in rows:
            byt.setdefault(f["status"], []).append(f)
        for st in sorted(byt, key=lambda s: worst.get(s, 9)):
            names_ = [f["title"] for f in byt[st]]
            print("[%s] %d 栋" % (st, len(names_)))
            for i in range(0, len(names_), 6):
                print("      " + " ".join(names_[i:i + 6]))
        # 把每栋的第一条原因也带一行，省得再去翻产物
        print("-" * 74)
        for f in rows:
            if f["status"] in ("gap", "watch", "unavailable"):
                print("  %-8s %-12s %s" % (f["title"], f["status"], f["detail"][:90]))
    else:
        for f in d["findings"]:
            loc = "F%s" % f["floor"] if f["floor"] is not None else "整栋"
            print("[%-11s] %-4s %-6s %s"
                  % (f["status"], f["check"], loc, f["title"]))
            if f["detail"]:
                print("              %s" % f["detail"])
            if f["measure"]:
                print("              口径：%s" % f["measure"])
        # ── 逐层验收单：一层一行（"建一层验一层"要看的就是这张）
        byf = d.get("by_floor") or {}
        floors = sorted((k for k in byf if k != "整栋"),
                        key=lambda k: int(k[1:]) if k[1:].isdigit() else 999)
        if floors:
            print("-" * 74)
            print("逐层验收单（一层一行；整栋级判据在最上面单列）")
            for k in floors + (["整栋"] if "整栋" in byf else []):
                rows = byf[k]
                tally: dict[str, int] = {}
                for r in rows:
                    tally[r["status"]] = tally.get(r["status"], 0) + 1
                bad = [r for r in rows if r["status"] in ("gap", "watch", "unavailable")]
                mark = ("✗" if any(r["status"] == "gap" for r in rows)
                        else "!" if any(r["status"] == "watch" for r in rows)
                        else "?" if any(r["status"] == "unavailable" for r in rows)
                        else "✓")
                head = "%s %-4s" % (mark, k)
                if bad:
                    print(head, "、".join("%s(%s)" % (r["check"], r["status"])
                                          for r in bad))
                else:
                    print(head, "全部通过（%d 项）" % len(rows))
    print("=" * 74)


def _selftest() -> int:
    """证明这台引擎**会红**。绿灯不值钱，能红才值钱（memory: verifier-needs-its-own-falsifier）。

    做法：临时造一栋"处处违反 A1/A3/A4"的假楼，跑一遍，断言它报 GAP；
    再造一栋合规假楼，断言它不报 GAP。两条都要过 ——
    只证"能红"会漏掉"永远红"，只证"能绿"会漏掉"从不红"。
    """
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix="gym3d_ck_"))
    data = tmp / "data"
    try:
        # ① 处处违反的假楼：没有台账、没有产物、楼层里房间是空的
        bad = data / "buildings" / "zz_bad"
        (bad / "floors").mkdir(parents=True)
        (bad / "profile.json").write_text("{}", encoding="utf-8")
        (bad / "rooms.json").write_text("[]", encoding="utf-8")
        (bad / "floors" / "floor0.json").write_text(
            json.dumps({"floor": 0, "outline": [[0, 0], [1, 0], [1, 1]], "rooms": []},
                       ensure_ascii=False), encoding="utf-8")
        r_bad = run_building_checks(data, "zz_bad")
        got_bad = r_bad.rollup()
        if got_bad != Verdict.FAIL.value:
            print("自检失败：处处违反的假楼竟没报 FAIL，得到 %s" % got_bad)
            return 1
        print("自检 ①  处处违反的假楼 → %s（%s）" % (got_bad, _bar(r_bad.counts())))

        # ② 结构上合规的假楼：五件齐、台账非空、楼层快照与台账一致。
        # ★ 预期它**只报一个** GAP：A6（不在 ID_BASE 白名单里）。
        #   这不是缺陷，是这个检查的正确行为 —— 本仓任何一栋**没被登进白名单**
        #   的楼，房间抽取链根本不会为它跑。所以判据写成"GAP 集合恰好等于 {A6}"：
        #   多了 ⇒ 有别的判据乱红；少了 ⇒ A6 这道闸门已经死了却没人发现
        #   （memory: vacuous-test-assertions：要能红才算测过）。
        good = data / "buildings" / "zz_good"
        (good / "floors").mkdir(parents=True)
        (good / "dxf_plan_fast").mkdir(parents=True)
        (good / "profile.json").write_text("{}", encoding="utf-8")
        (good / "rooms.json").write_text(
            json.dumps([{"floor": 0, "id": "1001", "number": "101"}]), encoding="utf-8")
        (good / "floors" / "floor0.json").write_text(
            json.dumps({"floor": 0, "outline": [[0, 0], [10, 0], [10, 10], [0, 10]],
                        "rooms": [{"floor": 0, "id": "1001"}]}), encoding="utf-8")
        (good / "spec.json").write_text("{}", encoding="utf-8")
        (good / "zz_good-building.glb").write_bytes(b"glTF")
        (good / "dxf_plan_fast" / "floor0.png").write_bytes(b"\x89PNG")
        r_good = run_building_checks(data, "zz_good")
        gaps = sorted(f.check for f in r_good.findings if f.status.value == "gap")
        if gaps != ["A6"]:
            print("自检失败：合规假楼的 GAP 集合应是 ['A6']（白名单外的楼本该被 "
                  "A6 拦住），实际 %s" % gaps)
            return 1
        print("自检 ②  结构合规但未登白名单的假楼 → %s（%s），"
              "只被 A6 拦下（符合预期）" % (r_good.rollup(), _bar(r_good.counts())))

        # ③ A3 的「层号自证」量具，两个方向都要试。
        # ★ 为什么非试不可：第一版写成"层号与房号不符 ⇒ 台账是旧账"，
        #   实测全库 12 个能解析的栋模态偏移**全是 +1**（floor 0 基 / 房号 1 基），
        #   于是那版会在 12 栋上全红而**一例真缺陷都抓不到**。
        #   所以这里造两栋：约定一致（不该红）与有一行偏离约定（该红）。
        def _mk(name, ledger):
            b = data / "buildings" / name
            (b / "floors").mkdir(parents=True)
            (b / "profile.json").write_text("{}", encoding="utf-8")
            (b / "rooms.json").write_text(json.dumps(ledger, ensure_ascii=False),
                                          encoding="utf-8")
            # F0 快照与台账一致（5 间）；F1 快照 0 间而台账有 ⇒ 计数对不上
            (b / "floors" / "floor0.json").write_text(
                json.dumps({"floor": 0, "outline": [[0, 0], [1, 0], [1, 1]],
                            "rooms": [{"floor": 0, "id": i} for i in range(5)]},
                           ensure_ascii=False), encoding="utf-8")
            (b / "floors" / "floor1.json").write_text(
                json.dumps({"floor": 1, "outline": [[0, 0], [1, 0], [1, 1]],
                            "rooms": []}, ensure_ascii=False), encoding="utf-8")
            return b

        def _row(F, num):
            return {"floor": F, "id": abs(hash(num)) % 10 ** 6, "number": num}

        # ③-a 约定一致：floor F 的房间号写 F+1 层（+1 是全库实测的约定），F1 有 2 间
        clean = [_row(0, "zz-A-01-%02d" % i) for i in range(5)]
        clean += [_row(1, "zz-A-02-00"), _row(1, "zz-A-02-01")]
        _mk("zz_wit_clean", clean)
        f = [x for x in run_building_checks(data, "zz_wit_clean").findings
             if x.check == "A3"]
        # ★ 一条判据一层一条结论，所以断言"**存在**一层报 gap"，不是"第一条是 gap"
        if not any(x.status.value == "gap" for x in f):
            print("自检失败：约定一致的台账应报 gap（计数确实对不上），实际 %s"
                  % ([x.status.value for x in f] or "无 A3 结论"))
            return 1
        if not any(x.floor == 0 and x.status.value == "pass" for x in f):
            print("自检失败：F0 逐层吻合却没出 pass 结论（逐层验收单会空着）")
            return 1
        print("自检 ③-a 约定一致的台账 → F0 pass、F1 gap（计数对不上，但不指控层序）")

        # ③-b 只把 F1 的一行房号写成 1 层（偏离本栋 +1 的约定）⇒ 应降为 watch 并点名
        dirty = clean[:-1] + [_row(1, "zz-A-01-77")]
        _mk("zz_wit_dirty", dirty)
        f = [x for x in run_building_checks(data, "zz_wit_dirty").findings
             if x.check == "A3"]
        hit = [x for x in f if x.status.value == "watch"]
        if not hit:
            print("自检失败：台账里有一行偏离本栋层号约定时，应报 watch（先查台账、"
                  "别 backfill），实际 %s" % [x.status.value for x in f])
            return 1
        if not any("zz-A-01-77" in x.detail for x in f):
            print("自检失败：watch 里没点名那一行，人无从下手：%s"
                  % "｜".join(x.detail[:80] for x in hit))
            return 1
        print("自检 ③-b 台账有一行偏离约定 → watch，且点名 zz-A-01-77")

        # ④ 图纸明细解析：`房间数` 那一列必须真能读出来。
        # ★ 这是刚修掉的真缺陷的回归守卫：_area_audit.py 打印的是 float（`21.0`），
        #   而原来的解析写成 `s.isdigit()` ⇒ 全库 93 栋的 drawing_rooms **全被读成 null**。
        #   测法就是拿**真输出格式**（带 `.0`）当输入 —— 用 `21` 去测会假绿。
        from backend.checks.sources import parse_detail
        txt = ("--- c113 逐层（图纸 vs 模型）\n"
               "   1层 图纸  6751.30  模型  3892.67  差  -2858.6   房间数 21.0\n"
               "   2层 图纸  5629.75  模型  3545.83  差  -2083.9   房间数 None\n")
        got = parse_detail(txt).get("c113") or []
        if len(got) != 2 or got[0]["drawing_rooms"] != 21:
            print("自检失败：图纸房间数没解析出来（真格式是 `21.0`，不是 `21`）：%s" % got)
            return 1
        if got[1]["drawing_rooms"] is not None:
            print("自检失败：图纸没写房间数时应为 None（不是 0）：%s" % got[1])
            return 1
        print("自检 ④ 图纸明细解析：`21.0`→21、`None`→None")

        # ⑤ A7 的**归类**：把"不可比"和"说不通"分开，两个方向都要试。
        # ★ 为什么非试不可：A7 归类前在 27 栋上亮，实测 40 层里有 34 层
        #   **结构上就不该比**（过渡层并集 / 分片楼）。若归类写坏了往"并集"那边漏，
        #   真缺陷会被静默标成"不可比"而放行 —— 那比不分类更坏。
        #   所以造两栋：并集层 → NA；对不上任何一层的 → WATCH。
        from backend.checks.builtin import _a7_kind, _fragment_base
        # 过渡层：本层楼板 5381 恰好等于本栋 F4/F5 的图纸面积 5350
        k, _n, _e = _a7_kind(5381.0, 6, {4: 5350.0, 5: 5350.0, 6: 913.0}, None)
        if k != "union":
            print("自检失败：楼板等于本栋别层图纸面积时应归为 union，得到 %s" % k)
            return 1
        # 说不通：2758 对 956，既不是别层的数、也不是干净整数倍之外的正常情形
        #   —— 这层 2758/956≈2.9 会落到 multi（整数倍是**线索**不是结论），
        #   所以真正要断言的是：**凡不能归为 union 的，状态绝不能是 NA**。
        k2, _n2, _e2 = _a7_kind(2758.0, 3, {3: 956.0}, None)
        if k2 == "union":
            print("自检失败：对不上任何一层的差值被误归为 union —— "
                  "真缺陷会被静默放行（比不分类更坏）")
            return 1
        # 分片：**两个方向**都要试。名字像 f1 但母栋不在库里 ⇒ 必须 None
        #   （★ 这里第一版写的是拿 `zz_bad` 去测 —— 那是个**空断言**：
        #    `zz_bad` 根本不匹配 `f\d+$`，所以它在"母栋检查写没写"两种情况下都返回 None，
        #    永远绿。要能红，就得拿一个**形状是分片、但母栋不存在**的名字去测。）
        if _fragment_base(data, "zz_nomotherf1") is not None:
            print("自检失败：名字像分片但母栋不在库里，仍被认成分片 —— "
                  "这会把普通楼硬说成附楼的比值偏小（拿猜测当事实）")
            return 1
        (data / "buildings" / "zz_mom").mkdir(parents=True, exist_ok=True)
        (data / "buildings" / "zz_mom" / "profile.json").write_text("{}",
                                                                    encoding="utf-8")
        if _fragment_base(data, "zz_momf1") != "zz_mom":
            print("自检失败：母栋真在库里时没认出来 —— 分片提示会整条失效")
            return 1
        print("自检 ⑤ A7 归类：并集层→union(NA)、对不上的→%s(WATCH)、"
              "分片要母栋**真在库里**（两个方向都试）" % k2)

        # ⑥ A9「房号字段是不是房号」——两个方向。
        # ★ 这条量的是**字段内容**，不是条数，所以夹具必须把"条数"做对：
        #   台账 4 间、快照也 4 间（A1/A3 全绿），只有房号那一列是坏的。
        #   这样才证明 A9 抓的是别人抓不到的东西；若夹具连条数都不对，
        #   红了也分不清是谁的功劳。
        def _mk9(name, nums):
            b = data / "buildings" / name
            (b / "floors").mkdir(parents=True, exist_ok=True)
            (b / "profile.json").write_text("{}", encoding="utf-8")
            (b / "rooms.json").write_text(
                json.dumps([{"floor": 0, "id": i, "number": t}
                            for i, t in enumerate(nums)], ensure_ascii=False),
                encoding="utf-8")
            (b / "floors" / "floor0.json").write_text(
                json.dumps({"floor": 0, "outline": [[0, 0], [1, 0], [1, 1]],
                            "rooms": [{"floor": 0, "id": i} for i in range(len(nums))]},
                           ensure_ascii=False), encoding="utf-8")

        _mk9("zz_a9_bad", ["卫", "卫", "卫生间", "花坛"])
        f9 = [x for x in run_building_checks(data, "zz_a9_bad").findings if x.check == "A9"]
        if not any(x.status.value == "gap" for x in f9):
            print("自检失败：房号整列都是『卫』这种名称时应报 gap，实际 %s"
                  % ([x.status.value for x in f9] or "无 A9 结论"))
            return 1
        _mk9("zz_a9_ok", ["113-01-01", "113-01-02", "113-01-03", "113-01-04"])
        f9 = [x for x in run_building_checks(data, "zz_a9_ok").findings if x.check == "A9"]
        if any(x.status.value in ("gap", "watch") for x in f9):
            print("自检失败：房号干净时不该报红，实际 %s"
                  % [(x.status.value, x.detail[:50]) for x in f9])
            return 1
        print("自检 ⑥ A9 房号字段：整列是名称→gap；干净号段→pass"
              "（且夹具的条数是对的，A1/A3 全绿，证明抓到的是别人抓不到的）")

        # ⑦ B3「图上房号 vs 台账房间」——**闸门**与**归类**分两段验。
        # ★ B3 是唯一一条"先得自己标定，标定不住就不出结论"的检查（见 heavy.py 的
        #   _b3_gate）。所以自检不能像别条那样只喂一种输入，得喂**坏数据**看它拦不拦。
        # ★ 闸门那段是纯标准库，任何机器都能跑；归类那段要 shapely（_pt_in 拿它当
        #   参考实现）。**没有 shapely 时返回失败，不许安静跳过** —— 跳过的自检就是
        #   空断言（memory: vacuous-test-assertions），屏幕上和"验过了"长得一样。
        from backend.checks import heavy as _H

        # ⑦-a 闸门：三个方向都得拦得住，一个合规的得不拦。
        for args, what in (((5, 5, 0), "阳性对照一半落不回"),
                           ((3, 0, 0), "样本低于下限"),
                           ((0, 0, 0), "一间都没标定上")):
            why = _H._b3_gate(*args)
            if why is None:
                print("自检失败：B3 闸门在「%s」时该拦却没拦（喂进去的是 %s）" % (what, args))
                return 1
        why = _H._b3_gate(95, 5, 0)
        if why is not None:
            print("自检失败：B3 闸门在阳性对照 95%%（95 对 / 5 错）时不该拦，实际拦了：%s" % why)
            return 1

        # ⑦-b 归类：四种结局各造一个，且**每种都造在只有它该命中的位置上**。
        try:
            import shapely                                     # noqa: F401
        except Exception as ex:                                # noqa: BLE001
            print("自检 ⑦-b **未运行**：本机没有 shapely（%s），B3 的归类逻辑本轮"
                  "没被验过 —— 因此不算通过，也不许说通过" % ex)
            return 1

        from shapely.geometry import Polygon

        def _sq(x0, y0, x1, y1):
            return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

        # 本层轮廓 20×10，但只有左半有一间房 ⇒ 右半是"轮廓内、谁也不接住"的地带。
        # 第 1 层轮廓给 None ⇒ 专测"分不出内外时不许默认当成在外面"。
        _geoms = {0: [("113-01-01", _sq(0, 0, 10, 10))]}
        _out = {0: _sq(0, 0, 20, 10), 1: None}
        _led = {"113-01-01"}
        _nbf = {0: {"113-1-1": "113-01-01"}, 1: {}}
        _placed = [
            (0, 5.0, 5.0, "113-01-09", 0.0, 0.0),     # 落在**别人**房里
            (0, 15.0, 5.0, "113-01-10", 0.0, 0.0),    # 轮廓内、谁也没接住
            (0, 25.0, 5.0, "113-01-11", 0.0, 0.0),    # 轮廓外
            (0, 5.0, 5.0, "113-1-1", 0.0, 0.0),       # 同号不同写法（落进了房里）
            (0, 15.0, 5.0, "113-1-1", 0.0, 0.0),      # 同号不同写法（本层快照没它的几何）
            (1, 5.0, 5.0, "113-02-77", 0.0, 0.0),     # 本层轮廓不可用
        ]
        _res = _H._b3_classify(_placed, _led, _geoms, _out, _nbf)
        _want = {"label_lost": 1, "no_room": 1, "outside": 2,
                 "format_mismatch": 2, "thin_floor": 0}
        _got = {k: len(v) for k, v in _res.items()}
        if _got != _want:
            print("自检失败：B3 归类期望 %s，实际 %s" % (_want, _got))
            for k, v in sorted(_res.items()):
                print("   %-16s %s" % (k, [r[1] for r in v]))
            return 1
        # ★ **薄层的刑具**：同一个输入，只把 F0 标成薄层，看是不是**恰好那两条**
        #   「轮廓内、谁也没接住」的搬去了 thin_floor，而 label_lost / outside /
        #   被多边形接住的那种 format_mismatch 原地不动。
        #   实测那 43 间假缺陷就是这一支造的（c009），所以它必须有能红的东西盯着。
        _res2 = _H._b3_classify(_placed, _led, _geoms, _out, _nbf,
                                thin={0: "本层快照只有 0 间带几何，台账本层 24 间"})
        _want2 = {"label_lost": 1, "no_room": 0, "outside": 2,
                  "format_mismatch": 1, "thin_floor": 2}
        _got2 = {k: len(v) for k, v in _res2.items()}
        if _got2 != _want2:
            print("自检失败：B3 薄层规则期望 %s，实际 %s —— 快照缺房间时"
                  "「谁也没接住它」这一支必须整支不发话，其余的必须照发"
                  % (_want2, _got2))
            for k, v in sorted(_res2.items()):
                print("   %-16s %s" % (k, [r[1] for r in v]))
            return 1
        # ★ 轮廓不可用那一档必须**和「在图幅外」分开**：两者都进 outside，但前者的
        #   对照位写着原因。混成一种，就是把"量不到"写成了一条合格结论。
        if not any(r[2] == "本层轮廓不可用" for r in _res["outside"]):
            print("自检失败：本层轮廓不可用时必须在对照位写明，不许和「在图幅外」混成一档")
            return 1
        # 规范化形的**反面**：c046 有整列是汉字的房号，两个不同的汉字号不许撞成一个。
        if _H._norm("113-1-1") != _H._norm("113-01-01"):
            print("自检失败：同一个号的两种写法应规范化成同一形，实际 %s / %s"
                  % (_H._norm("113-1-1"), _H._norm("113-01-01")))
            return 1
        if _H._norm("卫") == _H._norm("厕"):
            print("自检失败：两个不同的汉字房号撞成了同一形（c046 那种整列汉字的楼会误判）")
            return 1

        # ⑦-c 「本栋号段」的口径**只有一份**，而且**与 A9 报出来的是同一个**。
        # ★ 为什么要有这条：B3 判"图幅外那些号是不是本栋的"要用号段，A9 判"号段统不统一"
        #   也要用号段。两处各写一份的话只有一份会跟着规则走，屏幕上就会同时出现
        #   「本栋号段是 113-*」(A9) 与「本栋号段是 12-*」(B3) 两句相反的话
        #   （memory: one-judgement-many-implementations）。
        #   所以这里不是"再测一遍同一个函数"，而是**拿 A9 自己吐出来的数当参照**。
        _seg_nums = ["114-01-01", "114-01-02", "114-01-03", "花坛", "天台"]
        _mk9("zz_seg", _seg_nums)
        _f9 = [x for x in run_building_checks(data, "zz_seg").findings if x.check == "A9"]
        _a9seg = next((x.evidence.get("modal_segment") for x in _f9
                       if x.evidence.get("modal_segment")), None)
        if _a9seg != "114":
            print("自检失败：A9 报的本栋号段应是 `114`（5 行里 3 行），实际 %r"
                  " —— 夹具自己的前提就不成立" % _a9seg)
            return 1
        if _H.home_number_segment(_seg_nums)[0] != _a9seg:
            print("自检失败：B3 的号段口径（%r）与 A9 报的（%r）不一致 —— "
                  "同一件事必须只有一份实现" % (_H.home_number_segment(_seg_nums)[0], _a9seg))
            return 1
        if _H.home_number_segment([])[0] is not None:
            print("自检失败：台账一条号都没有时，号段应是 None（不是随便挑一个）")
            return 1

        # ⑦-d 图幅外那半 —— **这就是本次修的活假绿**。
        # 造两组号：本栋号段（必须报）与邻幅号段（**不许报**）。
        # ★ 不许报那半是阳性对照的反面：c113 图幅外那 15 条是真邻幅 `Y11xx`，
        #   过滤在那里是**对的** —— 判据若把邻幅也算进来，就是拿假红去淹真红。
        _led2 = {"114-01-01", "114-01-02"}
        _rows2 = [("114-01-09", 0, 0, 0),      # 本栋号段、台账没有 ⇒ 报
                  ("114-01-01", 0, 0, 0),      # 本栋号段、台账有   ⇒ 不报
                  ("114-1-1", 0, 0, 0),        # 同号异写（台账里是 114-01-01）⇒ 不报
                  ("Y1101", 0, 0, 0),          # 邻幅号段（c113 实测）⇒ 不报
                  ("花坛", 0, 0, 0)]           # 根本不是号 ⇒ 不报
        _fm = _H._b3_frame_missing(_rows2, _led2, "114")
        if _fm["numbers"] != ["114-01-09"]:
            print("自检失败：图幅外那半只该报 ['114-01-09']（邻幅 Y11xx、同号异写、非号都不许报），"
                  "实际 %s" % _fm["numbers"])
            return 1
        # 反面：号段判不出时**一个都不许报** —— 那会把别栋的号报成本栋缺号（假红）
        if _H._b3_frame_missing(_rows2, _led2, None)["numbers"]:
            print("自检失败：号段判不出（None）时不该报任何号")
            return 1

        # ⑦-e 被两条过滤滤掉的号 —— **要连号带层留下**，原来只有一个计数。
        # ★ 一个计数说不了"滤掉的里面有没有本栋的号"，而那正是 c114 假绿的藏身处。
        _de = _H._b3_dropped_evidence([("114-01-09", 1463725, 0, 0),
                                       ("Y1101", 2476626, 0, 1)],
                                      [("花坛", 900, 0, None)])
        if sorted(_de["out_of_frame_numbers"]) != sorted(["114-01-09", "Y1101"]):
            print("自检失败：图幅外的**号**没留下（只留了计数）：%s" % _de["out_of_frame_numbers"])
            return 1
        _d0 = _de["out_of_frame_number_detail"]["114-01-09"]
        if _d0["x_mm"] != [1463725, 1463725] or _d0["labels"] != 1 or _d0["floors"] != [0]:
            print("自检失败：图幅外那个号的复核信息不全（x/条数/层）：%s" % _d0)
            return 1
        if _de["out_of_bands_numbers"] != ["花坛"] or \
                _de["out_of_bands_number_detail"]["花坛"]["floors"] != []:
            print("自检失败：层带外的号没留下，或层判不出时硬安了一个层：%s" % _de)
            return 1

        # ⑦-f PASS 措辞里的**分母** —— c072/c073 那半。
        # ★ 实测：台账 402 间、交付快照只有 98 间带几何，原句印的是「阳性对照 98/98」——
        #   **76% 的台账从没被试过，屏幕上却是满分**（memory:
        #   gauge-coverage-invisible-in-summary）。所以断言"没被试过的那个数**必须**
        #   出现在句子里"：谁把分母去掉，这句就缺 304，当场红。
        _ct = _H._b3_calib_text(402, 402, 98, 0, 304, 0)
        for _need in ("402", "304", "98"):
            if _need not in _ct:
                print("自检失败：阳性对照那句没写清分母（缺 %s）：%s" % (_need, _ct))
                return 1
        if "从来没被试过" not in _ct:
            print("自检失败：有 304 间没被试过时必须明说，只写 98/98 会被读成满分：%s" % _ct)
            return 1
        # 反面：每一间都试过时，不许无中生有出一句"没被试过"，且要明说"每一间"
        _ct2 = _H._b3_calib_text(10, 10, 10, 0, 0, 0)
        if "从来没被试过" in _ct2:
            print("自检失败：每一间都试过时不该说'从来没被试过'：%s" % _ct2)
            return 1
        if "每一间" not in _ct2:
            print("自检失败：每一间都试过时要明说'每一间'：%s" % _ct2)
            return 1
        _sc = _H._b3_scope_text(130, 65, 65, 0)
        if "65" not in _sc or "滤掉" not in _sc:
            print("自检失败：图幅账没写出'滤掉多少条'（c114 就是 130 / 65 / 65）：%s" % _sc)
            return 1
        _tt = _H._b3_thin_text({0: "x", 4: "y"}, {0: 72, 4: 64}, {0: 26, 4: 0})
        for _need in ("F0", "F4", "72", "64", "26"):
            if _need not in _tt:
                print("自检失败：薄层那句没点名层号与两边的数（缺 %s）：%s" % (_need, _tt))
                return 1
        if _H._b3_thin_text({}, {}, {}) != "":
            print("自检失败：一层都不薄时不该多出一句话")
            return 1
        # ★ **路由判据**：光测纯函数不够 —— 若 check_b3 的 PASS 分支哪天被改回
        #   `"阳性对照 %d/%d" % (ok, ok+bad)` 而不调这三个函数，上面全绿，而屏幕上那句话
        #   又是满分（memory: fixture-line-never-enters-its-branch：夹具那行没走到它的分支）。
        #   所以再断言这两个分支**真的**经由它们出话。
        #   说明它证明什么、不证明什么：证明的是**路由**（这句话是从被测函数出来的），
        #   不证明句子本身对（那由上面几条断言管）。两条合起来才封住那个坑。
        _src = inspect.getsource(_H.check_b3)
        for _fn in ("_b3_scope_text(", "_b3_calib_text(", "_b3_thin_text(",
                    "_b3_frame_missing("):
            if _fn not in _src:
                print("自检失败：check_b3 没走 %s —— 纯函数测绿了，屏幕上那句话还是旧的" % _fn)
                return 1
        print("自检 ⑦ B3：闸门会拦坏标定（3/3 拦）、不拦好标定；归类四档各归各位，"
              "「轮廓不可用」不冒充「在图幅外」，且快照缺房间时"
              "「谁也没接住它」整支闭嘴（其余照发）；")
        print("          号段口径与 A9 同源、图幅外带本栋号段的号会报而邻幅 `Y11xx` 不报、"
              "滤掉的号连层带 x 留下、PASS 句子里写了分母与薄层")

        print("自检通过：这引擎会红（①⑥）、也不会乱红（②③④⑤⑦）、"
              "分得清「不可比」与「说不通」（⑤）、"
              "还分得清「标定不住」与「标定住了没毛病」（⑦）。")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
