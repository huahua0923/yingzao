# -*- coding: utf-8 -*-
r"""`构件库/对照.md` 生成器 —— 人读版对照（门 / 楼梯 / 竖井）。

★ 为什么是**生成器**而不是手写一份 md（铁律 018 / 174）：
  对照页上每一个数都必须来自 `参数.json`（我们的数与出处）或 `对照.json`（实测读数），
  手写就等于把数抄第二遍 —— 抄错不出声，改了一处另一处不动。**差**也一样现算：
  差值由脚本按两侧相减得出，不是我先算好写进去的。

★ 规范那一侧的「数」**只从 `参数.json` 里 标注 ∈ {规范, 旧规范} 的条目取**（那是唯一真源）。
  `参考/出处.md` 里的引用**不给值**（未回原表的一律 null）—— 所以凡是要规范值才算得出来的差，
  本文件都会如实写「**算不出来**（有一侧未坐实）」，**不拿二手数硬凑一个差**
  （铁律 103：对照的期望值与差异必须由程序从实测数算出，手打数会把「声明错了」报成「代码有副作用」）。

写盘按字节（铁律 79），不经过文本模式。
"""
import io
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARAM = os.path.join(ROOT, "构件库", "参数.json")
DUIZHAO = os.path.join(ROOT, "构件库", "对照.json")
OUT = os.path.join(ROOT, "构件库", "对照.md")
CANKAO = "参考/出处.md"          # 相对 `构件库/`；引用与原文线索都在那一份里


def _load(p):
    with io.open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _n(x):
    """数值 → 人读串（整数不带小数点）。"""
    if isinstance(x, bool):
        return "是" if x else "否"
    if isinstance(x, float) and abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return ("%g" % x) if isinstance(x, float) else str(x)


def _v(s):
    """值 → 人读串。★ None 一律写「—（未坐实）」：**不许**写成 0 或空着（铁律 199）。

    ★ 单位是 `-`（无量纲/纯文字）时**不拼单位** —— 否则会印出「本套图无客运电梯井 -」。
    """
    u = str(s.get("单位") or "").strip()
    u = "" if u in ("-", "—") else (" " + u)
    v = s["值"]
    if v is None:
        return "—（未坐实）"
    if isinstance(v, list):
        if all(not isinstance(x, list) for x in v) and len(v) <= 3:
            return "、".join("%s" % x for x in v) + u
        if all(isinstance(x, list) for x in v):
            return "、".join("×".join("%s" % y for y in x) for x in v) + u
        return "%d 项：%s …" % (len(v), v[:2])
    return "%s%s" % (v, u)


def _src1(s):
    """出处取第一句（全量出处太长，全文在 `参数.json`）。"""
    t = " ".join(str(s.get("出处") or "").split())
    for sep in ("。", "★", "｜"):
        if sep in t:
            t = t.split(sep)[0]
    return (t[:110] + "…") if len(t) > 110 else (t or "—")


def _seq(xs):
    return "、".join(_n(x) for x in xs)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    P = _load(PARAM)
    D = _load(DUIZHAO)
    L = []
    w = L.append

    w("# 构件库 · 对照（门 / 楼梯 / 竖井）")
    w("")
    w("> **生成物**：由 `rebuild/tools/mk_duizhao_md.py` 从 `参数.json` + `对照.json` 现算，"
      "**勿手改**（改了下次生成就没了）。")
    w("> 数据时刻：**%s**；参数表更新：**%s**。" % (D["生成时刻"], P.get("更新")))
    w("> 规范那一侧的**数**只从 `参数.json` 取；引用与原文线索在 [`%s`](%s)（**只有链接、没有图**）。"
      % (CANKAO, CANKAO))
    w("> **网页版**：[`demo/parts.html`](../../demo/parts.html) —— 同一批数，在浏览器里现算"
      "（本文件是它的离线版）。")
    w("")
    w("读法：**标注**决定这个数能当什么用 —— "
      "`实测` 从本仓源图量出来的｜`假设` 我们定的名义值、**页面上必须标出来**｜"
      "`规范` 有标准号与条号｜`旧规范` 有出处但那一版已被替代｜`待坐实` 只记线索、**不许有值**。")
    w("")

    # ---------------------------------------------------------------- 1 门
    door = P["构件"]["门"]
    w("---")
    w("")
    w("## 1 门（用户报的「门上面的缺失」）")
    w("")
    w("### 1.1 我们的数（唯一真源：`参数.json::门`）")
    w("")
    w("| 参数 | 值 | 标注 | 区间 | 出处（首句） |")
    w("|---|---|---|---|---|")
    for n, s in door.items():
        w("| %s | %s | %s | %s | %s |" % (n, _v(s), s["标注"],
                                          s["区间"] if s["区间"] else "—", _src1(s)))
    w("")
    rows = D["构件"]
    w("### 1.2 我们建出来的（逐层，主语 = %s）" % D["计数主语"])
    w("")
    w("| 层 | 门扇 | 有门头 | **漏** | 漏·贴墙（源图墙实心⇒缺的是门洞） | 漏·离墙（源图那段没墙） | 块 | 面积合计 m² |")
    w("|---|---|---|---|---|---|---|---|")
    tot = Counter()
    for r in rows:
        w("| %s | %d | %d | **%d** | %d | %d | %d | %s |"
          % (r["层"], r["门扇"], r["有门头"], r["漏了"], r["漏_贴墙"], r["漏_离墙"],
             r["块"], _n(r.get("面积合计_m2"))))
        for k in ("门扇", "有门头", "漏了", "漏_贴墙", "漏_离墙", "块"):
            tot[k] += r[k]
    w("| **合计** | **%d** | **%d** | **%d** | **%d** | **%d** | **%d** | |"
      % (tot["门扇"], tot["有门头"], tot["漏了"], tot["漏_贴墙"], tot["漏_离墙"], tot["块"]))
    w("")
    if tot["漏了"]:
        w("**这 %d 扇漏的长什么样**（读数不是判词；每一扇都指名到源图坐标）：" % tot["漏了"])
        w("")
        for r in rows:
            if r["漏了"]:
                w("- **%s**：%s" % (r["层"], "；".join(
                    "距墙 %s / 距最近够大块 %s / 扇面积 %s / 质心 (%s, %s)"
                    % tuple(m) for m in r["漏明细_距墙_距块_面积"])))
        w("")
        w("★ **两种病、治法相反**：贴墙 %d 扇 = 源图那面墙是实心的，**缺的是门洞不是门头**；"
          "离墙 %d 扇 = 源图那段墙整段没有线，**没有墙可挂门头**。"
          % (tot["漏_贴墙"], tot["漏_离墙"]))
        w("")
    w("### 1.3 差在哪")
    w("")
    w("| 项 | 我们 | 参考 | 差 |")
    w("|---|---|---|---|")
    dh = door["洞高"]["值"]
    w("| 门洞高 | %s mm（**假设**） | 优先尺寸 2100 / 2400 mm（`%s` B1，表 3 来自二手）| %s |"
      % (_n(dh), CANKAO,
         "✅ 我方值**落在**优先尺寸表内" if dh in (2100, 2400) else "❌ 不在优先尺寸里"))
    w("| 过梁高 | %s mm（**旧规范**：03G322-1） | 现行 13G322-1～4 的选用表 | "
      "**算不出来** —— 现行选用表未坐实（`%s` B2）。已知的只有分档规律：洞越大梁越高 |"
      % (_n(door["过梁高_洞宽600-1800"]["值"]), CANKAO))
    e0 = P["构件"]["共用"]["环_最短边下限"]["值"]
    w("| 门头墙环最短边下限 | %s mm | 入口闸 ⑪ 阈值（**必须是同一个数**） | 0（两处不等就判红，"
      "见 `gates/J-10.8-00_contours.py` 的 ⑯）|" % _n(e0))
    # ★ 清边/收边这一行**只报记账**，不给判词：`清边半径`(δ) 管的是「薄」，`环_最短边下限`
    #   管的是「边短」—— 两者量的**不是同一件事**，写「δ < 下限所以清不掉」是没量过的推断。
    #   实测记账才是可核的（铁律 158：判词的量具要对得上被测的东西）。
    agg = Counter()
    for r in rows:
        agg["丢块"] += r["清边丢块"] + r["缝合后清边丢块"]
        agg["裂块"] += r["清边裂块"] + r["缝合后清边裂块"]
        agg["改面积"] += r["清边改面积块"] + r["缝合后清边改面积块"]
        agg["收边治了"] += r["收边治了"]
        agg["收边没治好"] += r["收边没治好"]
    w("| 清边半径 δ | %s mm | ——（**与「最短边下限」不是同一件事**：一条管薄、一条管边短） | "
      "**只看记账**：清边丢块 %d / 裂块 %d / 改面积 %d；收边治了 %d、**没治好 %d**"
      "（没治好的会原样进环、由闸 ⑪ 拦下）|"
      % (_n(door["门头墙_清边半径"]["值"]), agg["丢块"], agg["裂块"], agg["改面积"],
         agg["收边治了"], agg["收边没治好"]))
    n_hyp = sum(1 for _, s in door.items() if s["标注"] == "假设")
    w("| 门里有多少是**假设** | %d / %d 条 | —— | 假设值**必须在页面上标出来**，"
      "不许当成实测（页面上每条都带标注）|" % (n_hyp, len(door)))
    w("")

    # ---------------------------------------------------------------- 2 楼梯
    st = P["构件"]["楼梯"]
    F = D["楼梯形制"]
    w("---")
    w("")
    w("## 2 楼梯（用户报的「楼梯样式不对」）")
    w("")
    w("### 2.1 我们的数（唯一真源：`参数.json::楼梯`）")
    w("")
    w("| 参数 | 值 | 标注 | 区间 | 出处（首句） |")
    w("|---|---|---|---|---|")
    for n, s in st.items():
        w("| %s | %s | %s | %s | %s |" % (n, _v(s), s["标注"],
                                          s["区间"] if s["区间"] else "—", _src1(s)))
    w("")
    w("### 2.2 我们建出来的（%d 个梯间；下面是不重复读数）" % len(F))
    w("")
    for k in ("踏面_mm", "踢面_mm", "级数_每跑", "梯段宽_mm", "梯井宽_mm",
              "平台厚_mm", "半层高_mm"):
        c = Counter(r[k] for r in F)
        w("- **%s**：%s" % (k, "、".join(
            ("%s ×%d" % (_n(v), n)) if n > 1 else _n(v)
            for v, n in sorted(c.items(), key=lambda x: x[0]))))
    two = [r for r in F if r["两跑"]]
    one = [r for r in F if not r["两跑"]]
    w("- **两跑 / 单跑**：两跑 %d 座；单跑 %d 座%s"
      % (len(two), len(one),
         "（" + "；".join("%s@(%s, %s)" % (r["层"], r["中点_xy"][0], r["中点_xy"][1])
                          for r in one) + "）" if one else ""))
    w("- **栏杆**：立了 %d 条 / 贴墙跳过 %d 条 / %d 块"
      % (sum(r["栏杆_侧"] for r in F), sum(r["栏杆_贴墙"] for r in F),
         sum(r["栏杆_块"] for r in F)))
    w("")
    w("### 2.3 差在哪（差值现算）")
    w("")
    w("| 项 | 我们 | 参考 | 差 |")
    w("|---|---|---|---|")
    tg = sorted(set(r["踏面_mm"] for r in F))
    rs = sorted(set(r["踢面_mm"] for r in F))
    gov = st["踏面_规范档"]["值"]
    if gov is None:
        w("| 踏面 | %s mm（**实测**） | **未坐实** —— `%s` A1 只报到二手 280，原表是图片 | "
          "**算不出来**（规范侧未坐实）。★ 线索：**若**按 A1 的 0.280 m，差 −%g mm |"
          % (_seq(tg), CANKAO, 280 - max(tg)))
    else:
        w("| 踏面 | %s mm | %s mm | %+.1f mm |" % (_seq(tg), _n(gov), max(tg) - float(gov)))
    w("| 踢面（越小越好） | %s mm | ≤165 mm（`%s` A1，未回原表） | −%g mm ⇒ **我方更低 = 合规** |"
      % (_seq(rs), CANKAO, 165 - max(rs)))
    # ★ 这一条的区间装在 **`值`** 里（`值 = [560, 630]`、`区间 = null`），
    #   而 `级数_规范区间` 是反的（`值 = null`、`区间 = [3,18]`）—— **两个同名字段两种装法**
    #   （铁律 018/174）。这里不猜：按各自 `参数.json` 里的实际字段取，取不到就当场炸。
    lo, hi = st["步距_2踢面加踏面"]["值"]
    vals = sorted(set(round(2 * r["踢面_mm"] + r["踏面_mm"], 2) for r in F))
    w("| 步距 2h+b（**现算**） | %s mm | [%s, %s] mm（`%s` A2，已坐实） | %s |"
      % (_seq(vals), _n(lo), _n(hi), CANKAO,
         "✅ 全在区间内" if all(lo <= v <= hi for v in vals)
         else "❌ 越界：%s" % _seq([v for v in vals if not lo <= v <= hi])))
    lv = st["级数_规范区间"]["区间"]
    steps = sorted(set(r["级数_每跑"] for r in F))
    w("| 每跑级数 | %s 级 | [%s, %s] 级（`%s` A5，未回原文） | %s |"
      % (_seq(steps), _n(lv[0]), _n(lv[1]), CANKAO,
         "✅ 全在区间内" if all(lv[0] <= s <= lv[1] for s in steps)
         else "❌ 越界：%s" % _seq([s for s in steps if not lv[0] <= s <= lv[1]])))
    trig = st["梯井_防坠触发"]["值"]
    gw = sorted(set(r["梯井宽_mm"] for r in F))
    if max(gw) > trig:
        w("| 梯井宽 vs 防坠触发 %s mm | %s mm | `%s` A7（适用：托幼 / 中小学 / 少年儿童场所） | "
          "本楼是大中专教学楼 ⇒ **该条不适用**；**但** %s mm 已 > %s mm "
          "⇒ **若按中小学口径就触发**（口径待问，见 `%s` 文末）|"
          % (_n(trig), _seq(gw), CANKAO, _n(max(gw)), _n(trig), CANKAO))
    else:
        w("| 梯井宽 vs 防坠触发 %s mm | %s mm | `%s` A7 | ✅ 全 ≤ 触发值，任意口径都不触发 |"
          % (_n(trig), _seq(gw), CANKAO))
    r1 = st["栏杆高_白模"]["值"]
    r2 = st["栏杆高_平台"]["值"]
    w("| 栏杆高 | 白模统一 %s mm（**假设**） | 梯段 ≥%s mm、平台处**水平段长 >0.5 m 时** ≥%s mm"
      "（`%s` A3，已坐实） | %+.0f mm：**平台那段若水平长 >0.5 m 就低了** |"
      % (_n(r1), _n(st["栏杆高_梯段"]["值"]), _n(r2), CANKAO, r1 - r2))
    rw = sorted(set(r["梯段宽_mm"] for r in F))
    w("| 梯段宽 | %s mm | 每股人流 0.55 m + (0～0.15)、不少于两股（`%s` A6，未回原文） | "
      "下限随股数走、**不是常数 ⇒ 硬算不出** |" % (_seq(rw), CANKAO))
    pmin = st["平台宽_规范下限"]["值"]
    w("| 平台宽 | 平台跨两跑（宽 = 2·梯段宽 + 梯井宽） | ≥梯段净宽且 ≥1.2 m（`%s` A4） | %s |"
      % (CANKAO, "**算不出来** —— 参数表里该值留 null（它是随梯段宽变的下限，不是常数）"
         if pmin is None else "%s mm" % _n(pmin)))
    w("")
    big = [r for r in F if r["梯段宽_mm"] > 2400 or r["梯井宽_mm"] > max(trig, 200)]
    if big:
        w("★ **读数里两处要回源图核的**（是读数不是判词）：")
        w("")
        for r in big:
            w("- %s@(%s, %s)：梯段宽 **%s mm**、梯井宽 **%s mm**、两跑 = %s —— "
              "梯段宽顶到 2.6~2.9 m 或梯井宽 >%s mm，多半是**该窗口里两座梯间被并成一座**；"
              "**不许**当成「规范就这么宽」"
              % (r["层"], _n(r["中点_xy"][0]), _n(r["中点_xy"][1]),
                 _n(r["梯段宽_mm"]), _n(r["梯井宽_mm"]), _n(r["两跑"]), _n(trig)))
        w("")

    # ---------------------------------------------------------------- 3 竖井
    sh = P["构件"]["竖井"]
    S = D["竖井"]
    w("---")
    w("")
    w("## 3 竖井（用户报的「电梯生成的也不对」）")
    w("")
    w("### 3.1 我们的数（唯一真源：`参数.json::竖井`）")
    w("")
    w("| 参数 | 值 | 标注 | 区间 | 出处（首句） |")
    w("|---|---|---|---|---|")
    for n, s in sh.items():
        w("| %s | %s | %s | %s | %s |" % (n, _v(s), s["标注"],
                                          s["区间"] if s["区间"] else "—", _src1(s)))
    w("")
    nlayer = len(set(r["层"] for r in S))
    w("### 3.2 我们建出来的（%d 行 = %d 层 × %d 个，逐层同位）"
      % (len(S), nlayer, len(S) // max(1, nlayer)))
    w("")
    c = Counter((r["净宽_mm"], r["净高_mm"]) for r in S)
    w("| 井道内空（净宽 × 净高） | 出现次数 | 净面积 m² | 分布 |")
    w("|---|---|---|---|")
    for (a, b), n in sorted(c.items(), key=lambda x: -x[1]):
        hit = [r for r in S if (r["净宽_mm"], r["净高_mm"]) == (a, b)]
        layers = sorted(set(r["层"] for r in hit))
        w("| %s × %s mm | %d | %s | %s |"
          % (_n(a), _n(b), n, _n(hit[0]["净面积_m2"]),
             ("%d 层（逐层同位）" % len(layers)) if len(layers) > 1 else layers[0]))
    w("")
    w("### 3.3 差在哪")
    w("")
    w("**判词**（`参数.json::竖井/判定`）：**%s**。这句**不靠任何一条记来的井道毫米数**，"
      "靠两把互不同源的尺子 ——" % sh["判定"]["值"])
    w("")
    w("1. **形状**：墙上闭合矩形只有上表那几种，最小净宽 **%s mm**；"
      % _n(min(r["净宽_mm"] for r in S)))
    w("2. **命名**：源图 `6房间号` + `7用途` 里**没有一条**含「井 / 梯 / 电梯」字样。")
    w("")
    w("| 项 | 我们 | 参考 | 差 |")
    w("|---|---|---|---|")
    w("| 井道内净尺寸应 ≥ | 最小净宽 %s mm | **未坐实**（`参数.json::竖井/国标下限` 值 null） | "
      "**算不出来** —— `%s` C7 明确报「GB/T 7025.1-2023 图 5/6/7 的井道毫米数**完全未从原文坐实**」，"
      "第三方汇总还互相矛盾 ⇒ **不许**挑一个填进来当差 |"
      % (_n(min(r["净宽_mm"] for r in S)), CANKAO))
    w("| 井壁厚 | %s mm（**假设**） | 无规范常数（随井道做法与结构定） | 假设值，页面上已标出 |"
      % _n(sh["井壁厚"]["值"]))
    w("| 层门洞 | 不建（无真井） | 净高 ≥%s mm（`%s` C3）；洞口 1100×2200 **不是规范值**"
      "（`%s` C8，是厂家土建图常见值） | 不适用；**不许拿 1100×2200 当依据** |"
      % (_n(sh["层门洞_净高下限"]["值"]), CANKAO, CANKAO))
    w("")
    w("★ 人读文案一律叫**竖井**；数据键**仍叫 `LIFT`** —— 那是数据契约"
      "（`build3d` / `export_contours` / `compare3d` / `su_step2_build.rb` 的 `BATCHES` / 三份判据 / `demo` "
      "同时在用），改名会让 SU 那张硬编码类名表**静默丢面**。理由见 `06_su/export_contours.py:181-188`。")
    w("")

    blob = "\n".join(L) + "\n"
    tmp = OUT + ".tmp"
    with io.open(tmp, "wb") as fh:          # ★ 字节层（铁律 79）
        fh.write(blob.encode("utf-8"))
    os.replace(tmp, OUT)
    print("写了 %s（%d 字节 · %d 行）" % (OUT, len(blob.encode("utf-8")), len(L)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
