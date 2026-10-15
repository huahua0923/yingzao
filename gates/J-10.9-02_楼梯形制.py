# -*- coding: utf-8 -*-
r"""判据 J-10.9-02：建出来的楼梯形制，是不是我们**声明过**的那个形制。

★ 用户 2026-10-15 报「**楼梯样式不对**」。返工把楼梯做成「实心台阶 + 平台 + 梯井 + 栏杆」，
  量出来的每个数（踏面/踢面/级数/梯段宽/梯井宽/平台厚）落进 `对照.json` 的 `楼梯形制`。
  本闸**不重写任何数**：只拿 `参数.json` 里**人声明过的区间**去核 `对照.json` 里的读数。

判据
 ① 参照件同趟：`对照.json` 的 `生成时刻`/磁盘时刻不许早于 `contours/1层.json` 的磁盘时刻 − 600 s。
 ② 读数落在参数表声明的**实测区间**内：`踏面 / 踢面 / 级数_每跑 / 梯段宽 / 梯井宽 / 平台厚`
    × 66 行。超界要**指名**（层 + 中点坐标 + 读数 + 区间），并分开写清是超上限还是落下限。
    ★ 2026-10-15：某字段 `区间` 为 `null` = **参数表刻意不声明它** ⇒ 该字段**只记读数、不判红**，
      并把字段名印进 `未声明字段`（不许静默跳到下一个字段）。依据与代价见 BLIND 最后一条。
 ②b 读数落在**待坐实档**的区间内：`踏面_规范档 [260,320]`、`级数_规范区间 [3,18]`。
    —— 这两档的 `值` 是 null（我们**拒绝**把查不到的规范数填成值），只有区间是声明；
       本闸照它核，核不过就是核不过（区间是声明，不是抄来的原文）。
 ③ 行内自洽（**两条恒等式**，都只用同一行里的数）：
      (a) `级数_每跑 × 踏面_mm == 梯段水平投影_mm`
      (b) `两跑 ⇒ 2 × 梯段宽_mm + 梯井宽_mm == 梯间总宽_mm`
    —— 这两条抓「读字段时串了位」：一行里三个数互相兜不住，就说明有一个不是这一行的。
 ④ 层覆盖：12 层每层至少 1 行；每行 `层` 必须出现在 `contours/` 的层名单里。
 ⑤ 步距合规：`2 × 踢面 + 踏面` 必须落在 `参数.json::楼梯/步距_2踢面加踏面` 声明的区间里
    （那一档的区间**写在 `值` 上**、不在 `区间` 字段 —— 两种形状在本仓并存，取时看形状）。
 ⑤b 来源标注不脱钩：每行 `踏面源` 必须逐字等于 `参数.json::楼梯/踏面.标注`。
    —— 「件说自己这数是实测来的、而参数表标它假设」比数字超界更坏：数字错看得见，**来源错看不见**。
 ⑥ 判词不静默：超界清单与最值（最宽梯段/最大梯井/步距范围）写进日志头与 json；
    「有 N 行超界」不许被一次「行数对上了」抹掉。

量具
 `构件库/对照.json::楼梯形制`（逐梯间一行，`parts_lib` 现算）；`构件库/参数.json::构件.楼梯`
 （唯一真源）；层名单取自 `06_su/contours/*层.json` 的文件名。

量具盲区（★先声明，再判）
 · 「超界」= 读数超出**参数表声明的区间**，**不等于违反规范**。区间是我们自己声明的选型范围
   （如 `梯段宽 [1000,1800]`）：读数 2620 说明「件比声明宽」或「声明写窄了」，
   两种都是**人要做决定**的事，本闸只负责把它举起来。
 · `参数.json` 里有、`对照.json` 的楼梯行里**没有对应读数**的那几条，本闸**核不到**，
   逐条列在日志的「未覆盖参数」一行：`栏杆高_梯段` / `栏杆高_平台` / `栏杆高_白模` /
   `平台宽_规范下限` / `栏杆宽` / `栏杆合并级数` …。**栏杆在这套件里只有「几条、几块」，没有高度读数。**
 · 不核 z 向：平台标高、梯井是否**贯通**、栏杆有没有真落在踏步前缘线上 —— 全盲
   （楼梯行里只有平面数与层高，没有标高）。
 · 不核源图：本闸只比「件 vs 参数表」，源图那一侧是 `J-10.8-00` / `J-09.2-A1d` 与 `mk_duizhao_md` 的活。
 · ★ **本闸分不开「真有一跑 2.6~2.9 m 宽」与「这一格里两座梯间被并成了一座」**：
   两条路都会让读数落到声明区间外。层内梯间数在 12 层里从 **1 到 10** 不等（见判词那一行），
   而 `mk_duizhao_md.py:260-269` 已经把「多半是并组」写在人读的 `对照.md` 里 —— 那是**带 hedge 的猜测**，
   本闸不把它升成判词，也不替它把区间放宽（放宽区间等于把这条红描掉）。

正对照（每条必须**因该因**而红；`新增 N 条` 是相对 C1 基线的**差集**，铁律 183）
 C1 真件            —— 基线
 C2 一行梯段宽改 9999  —— ③b 红（★2026-10-15 改口：`梯段宽` 已不声明区间 ⇒ ② 按设计不响；
                          单跑行连 ③b 也没有 ⇒ 单跑行的脏 `梯段宽` 本闸抓不到，见 BLIND）
 C2b 一行踢面改 9999   —— ② 与 ⑤ 红（② 这一支的正对照 —— C2 改口后它就没有了）
 C3 一行级数改 12      —— ③a 红（恒等式断，③b 不动）
 C4 一行踏面源改「假设」—— ⑤b 红（件的来源标注与参数表脱钩）
 C5 对照.json 不在     —— SKIP(rc=4)，另起一个**真进程**跑一遍验 rc
 C6 生成时刻改旧       —— ① 红
 C7 梯段宽区间加回 [1000,1800] —— ② 红（验 2026-10-15 新增的「`区间: null` ⇒ 只记读数」那一支
                                    是活的：抽掉不红、加回就红，两头都量到）

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（对照.json / 参数.json / contours 不在）
"""
import glob
import json
import os
import subprocess
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
CONTOURS = os.path.join(ROOT, "rebuild", "06_su", "contours")
PARAM = os.path.join(ROOT, "rebuild", "构件库", "参数.json")
DUIZHAO = os.path.join(ROOT, "rebuild", "构件库", "对照.json")
OUTD = os.path.join(HERE, "_out")
OUT = os.path.join(OUTD, "J-10.9-02.run.txt")

BLIND = [
    "「超界」= 超出参数表声明的区间，不等于违反规范；区间是我们自己声明的选型范围，超了要人做决定",
    "栏杆只有「几条/几块」，没有高度读数 ⇒ 栏杆高_梯段/平台/白模、平台宽_规范下限、栏杆宽、栏杆合并级数 核不到",
    "不核 z 向：平台标高、梯井是否贯通、栏杆是否落在踏步前缘线上，全盲",
    "只比「件 vs 参数表」，源图那一侧不在本闸",
    "件的读数里**只有 `踏面源` 一个来源字段**（梯井宽/平台厚/梯段宽/踢面/级数都没有）⇒ "
    "标注脱钩只有踏面这一条核得到；`平台厚` 在参数里标的是「假设」，件里没有字段证明它是按假设建的",
    "★ 读数落到区间外有两种成因：真有一跑 2.6~2.9 m 宽，或这一格里两座梯间被并成了一座；"
    "本闸只报「件与声明的选型范围不一致」，**不判成因**，也不因此放宽区间",
    "★ 2026-10-15 起 `梯段宽` / `梯井宽` 的 `区间` 是 `null`（**不声明**）⇒ ② 那一支对这两个字段"
    "只记读数、不判红。**这不是把红描掉**：那个区间是照**单独一跑**手打的选型（1470 / 120），"
    "而逐跑读数是 1470–2910 / 60–508 —— 手打的数代表不了集合（铁律 103）。"
    "★ **代价**：**「两座梯间并成了一座」这个真缺陷以后不再红**，只剩「每层梯间数」那一行"
    "（12 层里从 1 到 10 不等）给人读；裁定见 `rebuild/交付口径与判据审计.md` §4.2",
]

# 读数键 → 参数.json 键（两套键名并存，逐字对照，不是笔误）
FIELDS = (("踏面_mm", "踏面"), ("踢面_mm", "踢面"), ("级数_每跑", "级数_每跑"),
          ("梯段宽_mm", "梯段宽"), ("梯井宽_mm", "梯井宽"), ("平台厚_mm", "平台厚"))
# 待坐实档：这些键**没有值、只有区间**（本身的这条事实也要核）
SOFT = (("踏面_mm", "踏面_规范档"), ("级数_每跑", "级数_规范区间"))
# 参数里有、件里没有 ⇒ 本闸核不到（声明出来，不当过）
UNCOVERED = ("栏杆高_梯段", "栏杆高_平台", "栏杆高_白模", "平台宽_规范下限",
             "栏杆宽", "栏杆_贴墙容差", "栏杆合并级数")
FRESH_SLACK_S = 600
MILE = 1.0

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


def write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(("\n".join(_LOG) + "\n").encode("utf-8").replace(b"\r\n", b"\n"))


def json_path(out_txt):
    if out_txt == OUT:
        return os.path.join(OUTD, "J-10.9-02.json")
    if out_txt.endswith(".run.txt"):
        return out_txt[:-len(".run.txt")] + ".json"
    return os.path.splitext(out_txt)[0] + ".json"


def finish(rc, out, readings):
    p = json_path(out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"pass": rc == 0, "rc": rc, **readings, "blind": BLIND},
                  fh, ensure_ascii=False, indent=1)
    log("  rc=%d" % rc)
    log("  写出: %s" % p)
    write(out)
    return rc


def rng_of(par_row):
    """参数的区间 —— **两种形状在本仓并存**：`踏面` 的区间在 `区间` 字段、
    `步距_2踢面加踏面` 的区间在 `值` 上。取之前先看形状，不按名字猜、不按下标取。
    """
    v, r = par_row.get("值"), par_row.get("区间")
    if isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        return list(v), "值"
    if isinstance(r, list) and len(r) == 2:
        return list(r), "区间"
    return None, None


def judge(rows, par, layers, fr):
    fs = []
    S = par["构件"]["楼梯"]

    if not fr["是否新"]:
        fs.append("① 对照.json（生成时刻 %s、mtime %s）比 contours（%s）旧 —— 参照件停在上一趟"
                  % (fr["对照生成时刻"], fr["对照_mtime"], fr["contours_mtime"]))

    # ② 实测区间
    #   ★ 2026-10-15：`区间` 不是二元表（`null`）= **参数表刻意不声明这一条** ⇒ 只记读数、
    #     不判红，并把字段名收进 `未声明字段` 一起印出来 —— 不许静默跳过下一个字段（那叫悄悄绿）。
    #     ★ 这与「放宽区间」不是一回事：放宽是「声明了、声得宽」，这里是「压根不声明」，
    #       json 里长得不一样（`区间: [a,b]` vs `区间: null`）。依据与代价见 BLIND 最后一条。
    undeclared = []
    for f, pn in FIELDS:
        rg = S[pn].get("区间")
        if not (isinstance(rg, list) and len(rg) == 2):
            undeclared.append(pn)
            continue
        lo, hi = rg
        for r in rows:
            if not (lo <= r[f] <= hi):
                fs.append("② %s@(%d,%d) %s=%.2f 超出参数.json::楼梯/%s 声明的区间 [%s, %s]（%s）"
                          % (r["层"], r["中点_xy"][0], r["中点_xy"][1], f, r[f], pn, lo, hi,
                             "超上限" if r[f] > hi else "落下限"))

    # ②b 待坐实档
    for f, pn in SOFT:
        lo, hi = S[pn]["区间"]
        for r in rows:
            if not (lo <= r[f] <= hi):
                fs.append("②b %s@(%d,%d) %s=%.2f 超出 %s 的区间 [%s, %s]"
                          "（这一档 值=null：**没有坐实原文**，区间是声明）"
                          % (r["层"], r["中点_xy"][0], r["中点_xy"][1], f, r[f], pn, lo, hi))

    # ③ 两条行内恒等式
    for r in rows:
        d1 = abs(r["级数_每跑"] * r["踏面_mm"] - r["梯段水平投影_mm"])
        if d1 > MILE:
            fs.append("③a %s@(%d,%d) 级数 %s × 踏面 %s = %.1f ≠ 梯段水平投影 %.1f（差 %.1f）"
                      % (r["层"], r["中点_xy"][0], r["中点_xy"][1], r["级数_每跑"],
                         r["踏面_mm"], r["级数_每跑"] * r["踏面_mm"],
                         r["梯段水平投影_mm"], d1))
        if r["两跑"]:
            d2 = abs(2 * r["梯段宽_mm"] + r["梯井宽_mm"] - r["梯间总宽_mm"])
            if d2 > MILE:
                fs.append("③b %s@(%d,%d) 2×%.0f + %.0f = %.0f ≠ 梯间总宽 %.0f（差 %.1f）"
                          % (r["层"], r["中点_xy"][0], r["中点_xy"][1], r["梯段宽_mm"],
                             r["梯井宽_mm"], 2 * r["梯段宽_mm"] + r["梯井宽_mm"],
                             r["梯间总宽_mm"], d2))

    # ④ 层覆盖
    got = {}
    for r in rows:
        got[r["层"]] = got.get(r["层"], 0) + 1
    for lay in layers:
        if lay not in got:
            fs.append("④ %s 一行楼梯读数都没有 —— 这一层的梯**没量到**（不与「合规」同形）" % lay)
    for lay in got:
        if lay not in layers:
            fs.append("④ %s 有 %d 行读数，但 contours/ 里没有这一层" % (lay, got[lay]))

    # ⑤ 步距（参数档的区间长在 `值` 上 —— rng_of 返回的是 ((lo,hi), 取处)，解包要分两层）
    rng, rng_where = rng_of(S["步距_2踢面加踏面"])
    step_bad, step_lo, step_hi = 0, None, None
    if rng is None:
        lo = hi = None
        fs.append("⑤ 步距_2踢面加踏面 没有可用的区间（值/区间都不是二元表）⇒ 量不到")
    else:
        lo, hi = rng
        vals = [2 * r["踢面_mm"] + r["踏面_mm"] for r in rows]
        step_lo, step_hi = min(vals), max(vals)
        for r in rows:
            v = 2 * r["踢面_mm"] + r["踏面_mm"]
            if not (lo <= v <= hi):
                step_bad += 1
                fs.append("⑤ %s@(%d,%d) 2×踢面 + 踏面 = %.1f 超出 [%s, %s]"
                          % (r["层"], r["中点_xy"][0], r["中点_xy"][1], v, lo, hi))

    # ⑤b 来源标注不脱钩（件的读数里只有 `踏面源` 一个来源字段）
    want_src = S["踏面"]["标注"]
    src_bad = 0
    for r in rows:
        if r.get("踏面源") != want_src:
            src_bad += 1
            fs.append("⑤b %s@(%d,%d) 踏面源＝%r，参数.json::楼梯/踏面.标注＝%r —— 来源标注脱钩"
                      % (r["层"], r["中点_xy"][0], r["中点_xy"][1], r.get("踏面源"), want_src))

    return fs, {
        "行数": len(rows), "层数": len(got), "层": sorted(got),
        "未声明字段_只记读数": undeclared,
        "梯段宽_min": min(r["梯段宽_mm"] for r in rows),
        "梯段宽_max": max(r["梯段宽_mm"] for r in rows),
        "梯井宽_min": min(r["梯井宽_mm"] for r in rows),
        "梯井宽_max": max(r["梯井宽_mm"] for r in rows),
        "踏面集合": sorted({r["踏面_mm"] for r in rows}),
        "级数集合": sorted({r["级数_每跑"] for r in rows}),
        "步距区间_声明": [lo, hi], "步距区间_取自": rng_where,
        "步距_实测": [step_lo, step_hi], "步距超界行": step_bad,
        "踏面源_声明": want_src, "踏面源_集合": sorted({str(r.get("踏面源")) for r in rows}),
        "标注脱钩行": src_bad,
        "单跑行": sum(1 for r in rows if not r["两跑"]),
        "每层梯间数": got,
        "未覆盖参数": list(UNCOVERED),
    }


def main():
    global DUIZHAO, CONTOURS
    argv = sys.argv[1:]
    out = argv[argv.index("--out") + 1] if "--out" in argv else OUT
    if "--duizhao" in argv:
        DUIZHAO = argv[argv.index("--duizhao") + 1]
    if "--contours" in argv:
        CONTOURS = argv[argv.index("--contours") + 1]

    _LOG.clear()
    log("J-10.9-02 · 楼梯形制是不是我们声明过的那个（对照 %s）" % DUIZHAO)

    files = sorted(glob.glob(os.path.join(CONTOURS, "*层.json")))
    lack = [p for p in (DUIZHAO, PARAM) if not os.path.exists(p)] + ([] if files else [CONTOURS])
    if lack:
        log("★ 没量到：缺 %d 件 —— %s ⇒ SKIP(rc=4)"
            % (len(lack), [os.path.basename(m) for m in lack]))
        return finish(4, out, {"n_missing": len(lack),
                               "missing": [os.path.basename(m) for m in lack]})

    dz = json.load(open(DUIZHAO, "r", encoding="utf-8"))
    par = json.load(open(PARAM, "r", encoding="utf-8"))
    rows = dz["楼梯形制"]
    layers = [os.path.basename(p)[:-5] for p in files]
    t_dz, t_c = os.path.getmtime(DUIZHAO), os.path.getmtime(os.path.join(CONTOURS, "1层.json"))
    fr = {"是否新": (t_dz + FRESH_SLACK_S) >= t_c,
          "对照生成时刻": str(dz.get("生成时刻") or ""),
          "对照_mtime": datetime.fromtimestamp(t_dz).strftime("%Y-%m-%d %H:%M:%S"),
          "contours_mtime": datetime.fromtimestamp(t_c).strftime("%Y-%m-%d %H:%M:%S")}
    log("  ① 对照生成时刻 %s ｜ 对照 mtime %s ｜ contours mtime %s ⇒ %s"
        % (fr["对照生成时刻"], fr["对照_mtime"], fr["contours_mtime"],
           "同趟" if fr["是否新"] else "★参照件停在上一趟"))
    log("  读数 %d 行 ｜ contours %d 层 ｜ 参数.json「楼梯」%d 条"
        % (len(rows), len(files), len(par["构件"]["楼梯"])))
    log("-" * 78)

    base, head = judge(rows, par, layers, fr)
    log("  ⑥ 判词 : 梯间 %d 行 / %d 层（单跑 %d 行）｜梯段宽 %s–%s ｜梯井宽 %s–%s"
        % (head["行数"], head["层数"], head["单跑行"], head["梯段宽_min"], head["梯段宽_max"],
           head["梯井宽_min"], head["梯井宽_max"]))
    log("     踏面 %s ｜ 级数 %s" % (head["踏面集合"], head["级数集合"]))
    log("     步距(2踢面+踏面) 实测 %s vs 声明 %s（取自 `%s`）⇒ 超界 %d 行"
        % (head["步距_实测"], head["步距区间_声明"], head["步距区间_取自"], head["步距超界行"]))
    log("     踏面源 %s vs 参数标注 %s ⇒ 脱钩 %d 行"
        % (head["踏面源_集合"], head["踏面源_声明"], head["标注脱钩行"]))
    log("     每层梯间数（★层与层之间**不等**是「并组」与「真宽」之外的另一条线索，本闸不判成因）：%s"
        % "、".join("%s:%d" % (k, head["每层梯间数"][k]) for k in sorted(head["每层梯间数"])))
    log("  ⑤ 未覆盖参数（参数里有、件的读数里没有 ⇒ 本闸核不到）：%s"
        % "、".join(head["未覆盖参数"]))
    log("  ② 未声明字段（`参数.json` 里 `区间` 为 null ⇒ **只记读数、不判红**）：%s"
        % ("、".join(head["未声明字段_只记读数"]) or "（没有 —— 六个字段都声明了区间）"))
    log("C1 真件 ⇒ 违反 %d 条" % len(base))
    for x in base:
        log("    " + x)
    bad = list(base)

    def ctl(name, fs_, want):
        new = [x for x in fs_ if x not in base]
        # ★ 标签不许只取首字符：本闸有 `③a`/`③b`/`⑤b` 这种带字母的号，
        #   取 `x[0]` 会把「红对了因」报成「红错了因」（第一版就是这么错的）。
        got = sorted({x.split(" ")[0] for x in new})
        ok = bool(new) and got == sorted(want)
        log("  对照 %-20s → %s（新增 %d 条，要 %s，实得 %s）"
            % (name, "✔红" if ok else "✘没红/红错因", len(new), "".join(want), "".join(got) or "—"))
        if not ok:
            bad.append("对照 %s 没按预期红（要 %s，实得 %s，新增 %d 条）"
                       % (name, "".join(want), "".join(got) or "无", len(new)))

    r2 = json.loads(json.dumps(rows))
    r2[0]["梯段宽_mm"] = 9999.0
    # ★ 2026-10-15 改口：`梯段宽` 的 `区间` 已是 `null`（不声明）⇒ ② **按设计**不再响，
    #   这条只该红 ③b（行内恒等式 2×梯段宽+梯井宽 == 梯间总宽 被带断）。
    #   ★ 这就是「不声明」的代价之一，写在旁边：**单跑行（本轮 2 行）连 ③b 也没有**
    #     ⇒ 单跑行的 `梯段宽` 若是脏数，本闸**一条都抓不到**（已声明在 BLIND 里）。
    ctl("C2 梯段宽改 9999", judge(r2, par, layers, fr)[0], ["③b"])
    r2b = json.loads(json.dumps(rows))
    r2b[0]["踢面_mm"] = 9999.0
    # ★ C2b（2026-10-15 新增）：② 这一支**也得有一条自己的正对照** —— C2 改口后它就没有了。
    #   `踢面` 的区间仍是 [120,175]，读 9999 同时把步距 2×踢面+踏面 顶出 [560,630] ⇒ ② 与 ⑤ 都红。
    ctl("C2b 踢面改 9999", judge(r2b, par, layers, fr)[0], ["②", "⑤"])
    r3 = json.loads(json.dumps(rows))
    r3[0]["级数_每跑"] = 12
    ctl("C3 级数改 12", judge(r3, par, layers, fr)[0], ["③a"])
    r4 = json.loads(json.dumps(rows))
    r4[0]["踏面源"] = "假设"
    ctl("C4 踏面源改假设", judge(r4, par, layers, fr)[0], ["⑤b"])
    fr6 = dict(fr)
    fr6["是否新"] = False
    ctl("C6 参照件改旧", judge(rows, par, layers, fr6)[0], ["①"])
    # ★ C7（2026-10-15 新增）：把 `梯段宽` 的 `区间` 从 `null`（不声明）**加回**成二元表 ⇒ ② 必须
    #   **当场红**。这是「读到 null 就 continue」那段代码的**刀口**：加回红、抽掉不红，两头都验到，
    #   才证得了它接上了。只验「真件不红」会与「这段代码根本没跑」同形
    #   （铁律 137：判据要有分辨力，就得喂确有缺陷的输入）。
    par7 = json.loads(json.dumps(par))
    par7["构件"]["楼梯"]["梯段宽"]["区间"] = [1000, 1800]
    ctl("C7 梯段宽区间加回", judge(rows, par7, layers, fr)[0], ["②"])

    tmp = os.path.join(OUTD, "_stair_skip_probe.txt")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.abspath(__file__),
                        "--duizhao", os.path.join(ROOT, "rebuild", "构件库", "_no_such.json"),
                        "--out", tmp], cwd=ROOT, capture_output=True, env=env)
    log("  对照 %-20s → %s（rc=%d，要 4）"
        % ("C5 对照.json 不在", "✔" if r.returncode == 4 else "✘", r.returncode))
    if r.returncode != 4:
        bad.append("对照 C5 对照.json 不在时没 SKIP（rc=%d，要 4）" % r.returncode)

    log("-" * 78)
    log("J-10.9-02 总判 : %s" % ("PASS" if not bad else "FAIL（%d 条）" % len(bad)))
    for x in bad:
        log("  ✗ " + x)

    readings = dict(head)
    readings.update(fr)
    readings["n_violations"] = len(bad)
    return finish(0 if not bad else 1, out, readings)


if __name__ == "__main__":
    sys.exit(main())
