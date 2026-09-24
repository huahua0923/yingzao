# -*- coding: utf-8 -*-
"""kb/derive.py —— 图谱的 **instance 层**（机器派生）：把 `_qa` 的机器产物派生成
「症状家族 ──观察于──▶ 楼栋·层」，并用**逐条计数相同**卡住它。

为什么是这个形状（三条实测，不是推测）：

  · **两个轴，不是两份副本。** `_qa/defects.json` 是**识别侧**的缺陷记录（带 group/sev/msg/ids；
    ★ 行数与 code 全集**每次重扫都会变**，所以这里一个数都不写死 —— 现算见 `totals.defect_rows`
    与 `codes`。写死过的后果是实测的：那份台账曾比它描述的数据旧 10 天，而没人看得出来）；
    `_qa/defect_<楼>.json` 的 `rows[]` 是**几何侧**的逐层实测（键是 F/blobs/miss_pct/
    centroid_shift_m/`flags`）。两者**键完全不同、行数也不同**（c006：11 层 vs 60 条），
    所以不是「两处写同一个数」——不存在要不要一致的问题，它们是两条独立证据。
  · **flag → 家族走别名表，不另建一份映射。** `build_kb.py` 的 `index.alias` 是全仓唯一
    一份索引，derive 复用它（`ask.seeds_of`），不自己写第二份同义词表（一个事实一份写法）。
  · **映射不上的必须被数出来。** 走别名表点不到家族的 flag、以及 `CODE_FAMILY` 里没有的 code
    （现为 D1/D7/I3 三条具名口子），**不是「没有缺陷」**，是「图谱里还没有对应家族」——
    落进 `unmapped` 计数，绝不静默丢掉。处数一律现算，不写死。

★ 跨层行（`floor` 是 `null`）落在**识别侧**：13 行 = 10 条 D1 跨层重复房号/id、1 条 D2
「11/11 层汇总行」、1 条 D3「声明 6 层 / 实际 5 个文件」、1 条 D5「层号 [-1] 哨兵值」。
它们**不是任何一层**：写成 `0` 会凭空造出「F0 有 13 个缺陷」，写成 `-1` 会造出假楼层 F-1
（本仓栽过）。一律进 `_cross_floor` 桶并被计数。

★ `verify` 拆成**三条腿**，各配一条**只有它能看见**的对照（多腿判据最怕变成「红了就算过」）：

  | 腿 | 比什么 | 只有它能抓的 |
  |---|---|---|
  | ① `leg_reeval` | doc 与「按当前源重算」 | doc 陈旧／被改过 |
  | ② `leg_sha` | 源的**内容** sha12 | **条数一样而内容变了**（只比计数查不出这一档） |
  | ③ `leg_counts` | **直接数源列表** vs doc 的分组（含逐层桶） | 分组写错、跨层行被当成某一层 |

用法（本仓不认 --help：脚本靠 sys.argv 手解析，--help 会被静默当成楼名）：

  python -u kb/derive.py             # 派生并落 data/_meta/kg_instances.json
  python -u kb/derive.py --check     # 只读复核：产物与源逐条计数不同即退出 1
  python -u kb/derive.py --selftest  # 自检：三条腿各配一条只有它能看见的对照
  python -u kb/derive.py --json      # 打到 stdout，不落盘
"""
import copy
import io
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):          # 中文日志不设编码必糊字
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(KB_DIR)
sys.path.insert(0, KB_DIR)
sys.path.insert(0, ROOT)

import ask                                            # noqa: E402  别名表唯一实现（seeds_of）
from backend.state.roster import sha12                # noqa: E402  指纹规则全仓一份

KB_JSON = os.path.join(KB_DIR, "kb.json")
QA_DIR = os.path.join(ROOT, "_qa")
BUILDINGS = os.path.join(ROOT, "data", "buildings")
OUT = os.path.join(ROOT, "data", "_meta", "kg_instances.json")
FLAGS = ("--json", "--check", "--selftest")

# ★ `floor` 是 `null` 的行落这个桶。它故意**不是数字**：写成 0 会造出「F0 有 13 个缺陷」，
#   写成 -1 会造出假楼层 F-1。桶名不可能与真实层号撞。
CROSS = "_cross_floor"

# code → 家族 slug。**具名口子**：不在这里的 code 一律进 unmapped 并被计数，不许静默丢。
# ★ 每个映射的证据都是「该家族的 symptom 在 playbook 里挂的那个锚点」，不是凭 code 名猜。
CODE_FAMILY = {
    # ★ 证据指**产生它的代码**，不指台账行号：`_qa/defects.json` 每次全库重扫都整体重写，
    #   行号必然漂（2026-09-24 实测：旧 `:782` 是 D1，重扫后同号变成 c021 的 I9 行，
    #   而门禁 ② 只核「那一行存在」，指错了照样绿 —— 铁律 31）。
    #
    # ★ 2026-09-24 扩：这一档原只有 D1/D7/I3 三条，于是 21 个 code 里 18 个落进 unmapped
    #   （2512 行里 2458 行）—— 而**同一份 playbook 里那些家族早就写好了**，只是没人接上。
    #   现在每个 code 都指到一个**在册家族**，`family` 那栏不再有 None。
    # ★ 2026-09-24 再补：`QA` **接家族** `criterion-crashed`。它一行不是「质检行」，
    #   是**判据整栋崩溃**的痕迹：`qa_structural.py c009` 抛 AttributeError（I1 里
    #   `o.exterior` 撞上 MultiPolygon 轮廓），`scan_defects.py:scan` 兜住并记一行
    #   `code=QA, sev=INFO`，于是该栋**一条 I 码都没有** —— 与「18 条判据全过了」
    #   在汇总表上长得一模一样。这一行是全库口径里唯一能看见它的地方。
    "D1": ("room-merged-duplicate", "scan_defects.py:check_duplicates"),
    "D7": ("room-merged-duplicate", "scan_defects.py:check_merged_rooms"),
    "D0": ("room-merged-duplicate", "scan_defects.py:check_degenerate"),
    "I3": ("room-outside-outline", "qa_structural.py:I3_room_within_outline"),
    "D2": ("ledger-vs-delivery", "scan_defects.py:check_ledger_vs_floors"),
    "D3": ("ledger-vs-delivery", "scan_defects.py:check_floor_files"),
    "D5": ("ledger-vs-delivery", "scan_defects.py:check_ledger_sentinel"),
    "D8": ("ledger-vs-delivery", "scan_defects.py:check_ledger_area_mismatch"),
    "I1": ("column-and-slab-support", "qa_structural.py:I1_col_in_own_outline"),
    "I2": ("column-and-slab-support", "qa_structural.py:I2_col_through"),
    "I10": ("column-and-slab-support", "qa_structural.py:I10_col_beyond_plate_inside_hull"),
    "I7": ("column-duplicate", "qa_structural.py:I7_dup_columns"),
    "I11": ("door-host-broken", "qa_structural.py:I11_opening_hosts"),
    "I9": ("diagonal-and-curve-walls", "qa_structural.py:I9_irregular_walls"),
    "I17": ("stair-shaft-broken", "qa_structural.py:I17_stair_shaft"),
    "I4": ("outdoor-geometry-in-union", "qa_structural.py:I4_walls_not_outside"),
    "I5": ("outdoor-geometry-in-union", "qa_structural.py:I5_empty_dropband"),
    "I18": ("floor-misalign", "qa_structural.py:I18_stacking"),
    "I8": ("floor-misalign", "qa_structural.py:I8_stacking"),
    "D4": ("floor-misalign", "scan_defects.py:check_iso_group_rooms"),
    "QA": ("criterion-crashed", "scan_defects.py:scan"),
}

NOTE = ("图谱的 instance 层（机器派生）。两个轴：qa_defects = 识别侧缺陷记录（按 code、"
        "再按层分组），qa_reports = 几何侧逐层实测（按 flags 分组）。★unmapped 里的数不是"
        "「无缺陷」，是「图谱里还没有对应家族」—— 必须被数出来，不许静默为零。"
        "★" + CROSS + " 不是层：源里 floor=null 的行（跨层重复/整栋级）落这里。")


def load_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_sources():
    """读源。★同时记录每个源的 sha12 —— 没有它，「条数一样但内容变了」就查不出来。"""
    universe = sorted(p for p in os.listdir(BUILDINGS)
                      if os.path.isdir(os.path.join(BUILDINGS, p)))
    reports, src_sha = {}, {}
    for name in sorted(os.listdir(QA_DIR)):
        if name.startswith("defect_") and name.endswith(".json"):
            path = os.path.join(QA_DIR, name)
            doc = load_json(path)
            reports[doc["building"]] = doc
            src_sha["_qa/" + name] = sha12(io.open(path, "rb").read())
    dpath = os.path.join(QA_DIR, "defects.json")
    src_sha["_qa/defects.json"] = sha12(io.open(dpath, "rb").read())
    src_sha["kb/kb.json"] = sha12(io.open(KB_JSON, "rb").read())
    return {"universe": universe, "reports": reports, "defects": load_json(dpath),
            "alias": (load_json(KB_JSON).get("index") or {}).get("alias") or {},
            "src_sha": src_sha}


def fam_of_flag(alias, flag):
    """flag → 家族 slug。走别名表（`ask.seeds_of`），只认家族节点（`pb:`）。
    点不到家族 ⇒ None；点到**多个**家族 ⇒ 返回列表（那说明别名表在这里不稳，要被看见）。"""
    fams = sorted(n[3:] for n in ask.seeds_of(alias, flag) if str(n).startswith("pb:"))
    return fams[0] if len(fams) == 1 else (fams or None)


def _fam_str(fam):
    """★「点到两个家族」**不是**一个家族。落成普通字符串会让它混进 mapped 那一档
    （`family` 是个 list，`in fams` 判它不在、`startswith('★')` 判它不是 —— 两头都漏）。
    统一在有疑问的地方带 ★ 前缀，让 `_is_fam` 一眼归到 unmapped 里被计数。"""
    if isinstance(fam, list):
        return "★多家族:" + "/".join(fam)
    return fam


def _is_fam(fam):
    """这个 flag / code 真的落到了一个在册家族上吗（★开头的疑问值一律算没落）。"""
    return bool(fam) and not str(fam).startswith("★")


def _cell_fams(cell, alias):
    for f in cell["flags"]:
        fam = fam_of_flag(alias, f)
        cell["families"].extend(fam if isinstance(fam, list) else ([fam] if fam else []))


def build(raw):
    """纯函数：raw → doc。可被 selftest 用改过的 raw 反复调用。"""
    reports, defects, alias = raw["reports"], raw["defects"], raw["alias"]

    codes = {}
    for r in defects:
        sev = r.get("sev") or "?"
        row = codes.setdefault(r["code"], {"n": 0, "group": r.get("group") or "",
                                           "family": None, "evidence": None,
                                           "floor_null": 0, "sev": {}})
        row["n"] += 1
        row["floor_null"] += 1 if r.get("floor") is None else 0
        row["sev"][sev] = row["sev"].get(sev, 0) + 1
    for code, (fam, why) in CODE_FAMILY.items():
        if code in codes:
            codes[code]["family"], codes[code]["evidence"] = fam, why

    flags = {}
    for doc in reports.values():
        for r in doc.get("rows") or []:
            for f in r.get("flags") or []:
                fam = _fam_str(fam_of_flag(alias, f))     # ★点到多家族不是一个家族，见 _fam_str
                row = flags.setdefault(f, {"n": 0, "family": fam})
                row["n"] += 1
                if row["family"] != fam:                  # 同一 flag 两次点到不同家族 = 别名表不稳
                    row["family"] = "★不一致:%s/%s" % (row["family"], fam)

    buildings = {}
    for b in raw["universe"]:
        # 识别侧：逐层 code（★跨层行进 CROSS 桶，不许变成 F0）。
        # ★ 这一段**与有没有几何侧报告无关**，所以必须放在 `doc is None` 之前 ——
        #   `_qa/defects.json` 覆盖 95 栋，而几何侧报告只有 49 栋。原先它写在「有报告」分支里，
        #   另外 46 栋的识别侧缺陷**静默进不了图**（2026-09-24 实测：2512 行只有 928 行进得了图，
        #   是腿③「逐条计数不同」当场抓出来的 —— 断言比人先看见）。
        by_floor = {CROSS: {}}
        for r in defects:
            if r["building"] != b:
                continue
            k = CROSS if r.get("floor") is None else str(r.get("floor"))
            by_floor.setdefault(k, {})
            by_floor[k][r["code"]] = by_floor[k].get(r["code"], 0) + 1
        if not by_floor[CROSS]:
            by_floor.pop(CROSS)
        flat = {}
        for k, cell in by_floor.items():
            for c, n in cell.items():
                flat[c] = flat.get(c, 0) + n

        doc = reports.get(b)
        if doc is None:
            buildings[b] = {"report": False, "state": "UNAVAILABLE",
                            "reason": "_qa 下无 defect_%s.json —— 本栋在交付目录里，"
                                      "**几何侧**没有机器产物（「没量过」不等于「合格」）；"
                                      "识别侧的 code 见 codes_by_floor" % b,
                            "codes_by_floor": by_floor, "codes": flat}
            continue
        # 几何侧：逐层 flag
        obs = {}
        for r in doc.get("rows") or []:
            k = CROSS if r.get("F") is None else str(r.get("F"))
            obs.setdefault(k, {"flags": [], "families": []})["flags"].extend(r.get("flags") or [])
        for cell in obs.values():
            _cell_fams(cell, alias)
        buildings[b] = {"report": True, "floors_declared": doc.get("floors"),
                        "rows": len(doc.get("rows") or []), "obs": obs,
                        "codes_by_floor": by_floor, "codes": flat}

    n_flag = sum(v["n"] for v in flags.values())
    n_mapped = sum(v["n"] for v in flags.values() if _is_fam(v["family"]))
    tot = {"defect_rows": len(defects),
           "qa_rows": sum(len(d.get("rows") or []) for d in reports.values()),
           "qa_floors_declared": sum(d.get("floors") or 0 for d in reports.values()),
           "flag_instances": n_flag, "flag_mapped": n_mapped, "flag_unmapped": n_flag - n_mapped,
           "codes_mapped": sum(v["n"] for v in codes.values() if _is_fam(v["family"])),
           "floor_null_rows": sum(1 for r in defects if r.get("floor") is None),
           "buildings": len(raw["universe"]), "with_report": len(reports),
           "unavailable": len(raw["universe"]) - len(reports)}
    return {"criterion_version": 1, "_note": NOTE,
            "self_sha12": sha12(io.open(os.path.abspath(__file__), "rb").read()),
            "generated_from": {"src_sha": raw["src_sha"],
                               "qa_defects": "_qa/defects.json", "kb_alias": "kb/kb.json"},
            "universe": {"src": "data/buildings/*（与 backend/state/census.py 同一条形状："
                                "iterdir + is_dir，含分片楼 f1/f2）",
                         "n": len(raw["universe"]), "with_report": len(reports),
                         "without_report": len(raw["universe"]) - len(reports)},
            "totals": tot, "codes": codes, "flags": flags,
            "unmapped": {"codes": {c: v["n"] for c, v in codes.items() if not _is_fam(v["family"])},
                         "flags": {f: v["n"] for f, v in flags.items()
                                   if not _is_fam(v["family"])},
                         "why": "这些数在图谱里没有对应家族 ⇒ 只登记、只计数，不硬塞进任何家族"},
            "buildings": buildings}


# ── 三条腿（各配一条只有它能看见的对照）────────────────────────

REEVAL_KEYS = ("codes", "flags", "unmapped", "totals", "buildings", "universe")


def _diff_leaves(a, b, path, out):
    """把**每一处**不同的叶子路径收进 out。★ 只报「doc.codes 不一致」等于没说：
    修复的人还得自己找是哪一层、哪个字段；而只报「第一处」会漏掉最要紧的那个数
    （实测：多 1 行缺陷时，第一处是 `codes.D1.floor_null`，而真正要说的是
    `totals.defect_rows` 767→768）。"""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append("%s.%s（重算里有、doc 里没有）" % (path, k))
            elif k not in b:
                out.append("%s.%s（doc 里有、重算里没有）" % (path, k))
            elif a[k] != b[k]:
                _diff_leaves(a[k], b[k], "%s.%s" % (path, k), out)
        return
    out.append("%s（源 %r / doc %r）" % (path, b, a))


def leg_reeval(doc, raw):
    """腿①：doc 与按当前源重算的结果比 ⇒ 抓「产物是旧尺子量的」。"""
    fresh, out, CAP = build(raw), [], 4
    for k in REEVAL_KEYS:
        if doc.get(k) == fresh.get(k):
            continue
        hits = []
        _diff_leaves(doc.get(k), fresh.get(k), k, hits)
        out.append("腿① %s 与按当前源重算的不一致（%d 处）：%s%s"
                   % (k, len(hits), "；".join(hits[:CAP]),
                      "；…还有 %d 处" % (len(hits) - CAP) if len(hits) > CAP else ""))
    return out


def leg_sha(doc, raw):
    """腿②：源的**内容**指纹。★只有这条腿能看见「条数一样而内容变了」。"""
    got = (doc.get("generated_from") or {}).get("src_sha") or {}
    return ["腿② 源 %s 的内容指纹变了（登记 %s，现在 %s）—— 计数可能一个没变，"
            "但这条 doc 已经不是对着它派生的" % (f, got.get(f), h)
            for f, h in (raw["src_sha"] or {}).items() if got.get(f) != h]


def leg_counts(doc, raw):
    """腿③：**直接数源列表** vs doc 的分组。抓分组写错、抓跨层行被当成某一层。"""
    fails, defects = [], raw["defects"]
    want_flags = sum(len(r.get("flags") or []) for d in raw["reports"].values()
                     for r in (d.get("rows") or []))
    got_flags = sum(len(c.get("flags") or []) for v in doc.get("buildings", {}).values()
                    for c in (v.get("obs") or {}).values())
    if got_flags != want_flags:
        fails.append("腿③ 逐条计数不同：doc 的 obs 里数出 %d 处 flag，源里是 %d 处"
                     % (got_flags, want_flags))
    got_rows = sum(sum(v.get("codes", {}).values()) for v in doc.get("buildings", {}).values())
    if got_rows != len(defects):
        fails.append("腿③ 逐条计数不同：buildings[].codes 合计 %d 行，源 defects.json 是 %d 行"
                     % (got_rows, len(defects)))
    for b, v in (doc.get("buildings") or {}).items():
        doc_r = raw["reports"].get(b)
        if doc_r is None:
            continue
        # 几何侧逐层桶（源里 F 为 null 的行必须落 CROSS，写成某一层会让那层多出来）
        want = {}
        for r in doc_r.get("rows") or []:
            k = CROSS if r.get("F") is None else str(r.get("F"))
            want[k] = want.get(k, 0) + len(r.get("flags") or [])
        got = {k: len(c.get("flags") or []) for k, c in (v.get("obs") or {}).items()}
        if want != got:
            fails.append("腿③ %s 的几何侧逐层桶对不上：源 %s / doc %s" % (b, want, got))
        # 识别侧逐层桶
        wantc = {}
        for r in defects:
            if r["building"] != b:
                continue
            k = CROSS if r.get("floor") is None else str(r.get("floor"))
            wantc.setdefault(k, {})
            wantc[k][r["code"]] = wantc[k].get(r["code"], 0) + 1
        gotc = v.get("codes_by_floor") or {}
        if wantc != gotc:
            fails.append("腿③ %s 的识别侧逐层桶对不上：源 %s / doc %s（floor=null 的行必须在 %s"
                         "桶里，写成 F0 会造出假楼层）" % (b, wantc, gotc, CROSS))
        if v.get("report") is not True and not v.get("reason"):
            fails.append("腿③ %s 是 UNAVAILABLE 却没写 reason —— 「没量过」必须带原因" % b)
    t = doc.get("totals") or {}
    need = [("flag 分档", t.get("flag_mapped"), t.get("flag_unmapped"), t.get("flag_instances")),
            ("code 分档", t.get("codes_mapped"),
             sum((doc.get("unmapped") or {}).get("codes", {}).values()), len(defects)),
            ("楼栋分档", t.get("with_report"), t.get("unavailable"), t.get("buildings"))]
    for name, a, b, c in need:
        if None in (a, b, c) or a + b != c:
            fails.append("腿③ %s 不平：%s + %s ≠ %s（汇总行不写分母，「没量过」和「全对」"
                         "就会长得一样）" % (name, a, b, c))
    fams = set((load_json(KB_JSON).get("playbook") or {}).keys())
    for c, v in (doc.get("codes") or {}).items():
        if v.get("family") and v["family"] not in fams:
            fails.append("腿③ code %s 指向的家族 %r 不在 kb.json 里" % (c, v["family"]))
    for f, v in (doc.get("flags") or {}).items():
        fam = v.get("family")
        if fam and (str(fam).startswith("★") or fam not in fams):
            fails.append("腿③ flag %r 的家族指向 %r 不在 kb.json 里" % (f, fam))
    return fails


def verify(doc, raw):
    return leg_reeval(doc, raw) + leg_sha(doc, raw) + leg_counts(doc, raw)


# ── 自检 ────────────────────────────────────────────────────

def selftest():
    """★每条对照都在**单独一条腿**上断言：只要求「红了」的话，把某条腿删掉也照样绿。"""
    raw = load_sources()
    base = build(raw)
    fails = verify(base, raw)
    if fails:
        print("--selftest 红：基线就没过，后面的对照没有意义")
        for f in fails:
            print("  ✗ %s" % f)
        return 1

    def mut_raw(fn):
        r = copy.deepcopy(raw)
        fn(r)
        return r

    def mut_doc(fn):
        d = copy.deepcopy(base)
        fn(d)
        return d

    cases = []
    cases.append(("源里多出 1 行缺陷而 doc 不动 ⇒ 陈旧必须被发现",
                  mut_raw(lambda r: r["defects"].append(dict(r["defects"][0]))), base,
                  {"reeval": "defect_rows", "sha": None, "counts": "逐条计数"}))
    cases.append(("把一栋 UNAVAILABLE 悄悄改成有报告",
                  raw, mut_doc(lambda d: next(v.update(report=True, state="PASS")
                                              for v in d["buildings"].values()
                                              if v.get("report") is not True)),
                  {"reeval": "buildings", "sha": None, "counts": None}))
    cases.append(("从 flags 表里撕掉一个 flag",
                  raw, mut_doc(lambda d: d["flags"].pop(sorted(d["flags"])[0])),
                  {"reeval": "flags", "sha": None, "counts": None}))
    cases.append(("把源里 floor=null 的行挪成 F0（假楼层）",
                  raw, mut_doc(lambda d: _move_cross(d)),
                  {"reeval": "buildings", "sha": None, "counts": "识别侧逐层桶"}))
    cases.append(("把 D1 指到一个不存在的家族",
                  raw, mut_doc(lambda d: d["codes"]["D1"].update(family="不存在的家族")),
                  {"reeval": "codes", "sha": None, "counts": "不在 kb.json 里"}))
    cases.append(("源的**内容**变了而计数一个没变 ⇒ 只有腿②能看见这一档",
                  mut_raw(lambda r: r["src_sha"].update({"_qa/defects.json": "000000000000"})), base,
                  {"reeval": None, "sha": "指纹", "counts": None}))
    cases.append(("阴性对照：只改时刻与说明，三条腿都不许红",
                  raw, mut_doc(lambda d: d.update(generated_from=dict(d["generated_from"],
                                                                     at="1999-01-01"),
                                                  _note="改了说明")),
                  {"reeval": None, "sha": None, "counts": None}))

    legs = [("reeval", leg_reeval), ("sha", leg_sha), ("counts", leg_counts)]
    bad = 0
    for label, r, d, expect in cases:
        row = []
        for name, fn in legs:
            out = fn(d, r)
            want = expect[name]
            if want is None:
                if out:
                    row.append("✗腿%s 不该红却红了(%s)" % (name, out[0][:40]))
                    bad += 1
                continue
            if not out:
                row.append("✗腿%s 是哑的（改坏了没红）" % name)
                bad += 1
            elif not any(want in m for m in out):
                row.append("✗腿%s 红在别处（要找 %r）" % (name, want))
                bad += 1
            else:
                row.append("✓%s" % name)
        print("  %s  %s" % (" ".join(row), label))

    if bad:
        print("--selftest 红：%d 处没验成" % bad)
        return 1
    t = base["totals"]
    print("--selftest 绿：7 组对照、三条腿各自单独断言（含 1 组阴性对照：改时刻不许红）")
    print("现表：楼栋 %d（有报告 %d / UNAVAILABLE %d）；defects.json %d 行（%d code，"
          "家族能对上 %d 行 / 对不上 %d 行）；flags %d 处（命中家族 %d / 未命中 %d）；"
          "跨层行 %d；几何侧 %d 行"
          % (t["buildings"], t["with_report"], t["unavailable"], t["defect_rows"],
             len(base["codes"]), t["codes_mapped"], sum(base["unmapped"]["codes"].values()),
             t["flag_instances"], t["flag_mapped"], t["flag_unmapped"],
             t["floor_null_rows"], t["qa_rows"]))
    return 0


def _move_cross(doc):
    """把某栋识别侧的 CROSS 桶整个搬到 F0 —— 模拟「哨兵值被当分组键」。"""
    for v in doc["buildings"].values():
        cells = v.get("codes_by_floor") or {}
        if v.get("report") is True and CROSS in cells:
            for c, n in cells.pop(CROSS).items():
                cells.setdefault("0", {})
                cells["0"][c] = cells["0"].get(c, 0) + n
            v["codes"] = {c: sum(x.get(c, 0) for x in cells.values()) for c in v["codes"]}
            return


def atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, path)


def main():
    args = sys.argv[1:]
    for a in args:
        if a.startswith("-") and a not in FLAGS:
            print("不认识的开关 %r。本仓不认 --help；可用：%s" % (a, " ".join(FLAGS)))
            return 2
    if "--selftest" in args:
        return selftest()

    raw = load_sources()
    doc = build(raw)
    t = doc["totals"]
    if "--check" in args:
        if not os.path.exists(OUT):
            print("--check 红：%s 还不存在（先跑一次 python -u kb/derive.py）" % OUT)
            return 1
        fails = verify(load_json(OUT), raw)
        if fails:
            print("--check 红：%d 处" % len(fails))
            for f in fails:
                print("  ✗ %s" % f)
            return 1
        print("--check 绿：与源逐条计数相同（缺陷 %d 行 = 已映射 %d ＋ 未映射 %d；"
              "flags %d 处 = 命中 %d ＋ 未命中 %d；楼栋 %d = 有报告 %d ＋ UNAVAILABLE %d；"
              "跨层行 %d）"
              % (t["defect_rows"], t["codes_mapped"], sum(doc["unmapped"]["codes"].values()),
                 t["flag_instances"], t["flag_mapped"], t["flag_unmapped"],
                 t["buildings"], t["with_report"], t["unavailable"], t["floor_null_rows"]))
        return 0
    if "--json" in args:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0

    atomic_json(OUT, doc)
    print("已写 %s：楼栋 %d（有报告 %d / UNAVAILABLE %d）；缺陷 %d 行（%d 个 code，"
          "家族能对上 %d 行）；flags %d 处（%d 处能对上家族）；跨层行 %d"
          % (OUT, t["buildings"], t["with_report"], t["unavailable"], t["defect_rows"],
             len(doc["codes"]), t["codes_mapped"], t["flag_instances"], t["flag_mapped"],
             t["floor_null_rows"]))
    print("★ %d 行 code ＋ %d 处 flag 在图谱里没有对应家族 ⇒ 落在 unmapped 里被计数，"
          "不是「没有缺陷」" % (sum(doc["unmapped"]["codes"].values()), t["flag_unmapped"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
