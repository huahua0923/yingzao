# -*- coding: utf-8 -*-
"""标准绑定工具：把 `规范/标准绑定.json` 里**声称已核**的条款，拿**正本 PDF 自己**验一遍，
   并从这份单一真源渲染 `规范/标准绑定.md`（数字只住一处，人读版由机器生成）。

为什么这样设计（沿用《模型包格式-v1.md》§2.1 已定死的结论，并与 `tools/modelpack.py` 同构）：
  · 参照必须在被测物之外 —— 「我说 p8 有一句‘高程中误差’」这件事，只能由**正本第 8 页自己**证实，
    不能由我再抄一遍来「自证」。
  · 每条判据配正对照 —— 判据 `gates/J-10.7-01_standard.py` 喂**错页/错词**，若照样绿，尺子无分辨力。

★ 本工具的盲区（否定判词只到这里）：
  它只证明「**核验词**出现在**标称页**」。它**不证明**我对该句的**解读与套用判定**正确 ——
  套用/不套用是人的判断，本工具不给它判据。核验词是**每条款抽样一个**，不是逐字比对全文。

用法：python tools/standard_bind.py [--json 规范/标准绑定.json] [--selftest]
  或  python tools/standard_bind.py --h-model 39.72 --h-real 47.57      # 跑 4.2.3 高度精度闸
  rc=0 全部已核条款在正本对应页找到核验词；rc=1 有条款对不上（或高度闸不过）；rc=4 没量到
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                            # tools → cdut3d
SPEC = os.path.join(ROOT, "规范")


def _open_pdf(path):
    try:
        import pymupdf
    except Exception:
        import fitz as pymupdf                          # 旧包名兜底
    return pymupdf.open(path)


def squash(s):
    """去掉所有空白再比 —— PDF 抠字常把空格摆得不稳，别让空白造出假红/假绿。"""
    return re.sub(r"\s+", "", s or "")


def load(json_path):
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def verify(bind, root=None):
    """逐条验「已核」条款：正本可开、页号在范围内、核验词出现在该页。

    返回 (rows, n_checked, n_bad, docs)。rows = [(条款, 错误串或 None)]。
    """
    root = root or ROOT
    docs = {}
    rows = []
    n_checked = n_bad = 0
    for c in bind["条款"]:
        if not c.get("已核"):
            continue
        n_checked += 1
        std = next((s for s in bind["正本"] if s["id"] == c["正本"]), None)
        if std is None:
            rows.append((c, "★ 找不到正本条目 %s" % c["正本"]))
            n_bad += 1
            continue
        fp = os.path.join(root, std["文件"])
        if not os.path.exists(fp):
            rows.append((c, "★ 正本文件不在：%s" % std["文件"]))
            n_bad += 1
            continue
        if fp not in docs:
            docs[fp] = _open_pdf(fp)
        doc = docs[fp]
        pg = c.get("pdf页")
        if not isinstance(pg, int) or pg < 1 or pg > doc.page_count:
            rows.append((c, "★ 页号 %r 超出正本范围 1..%d" % (pg, doc.page_count)))
            n_bad += 1
            continue
        text = squash(doc[pg - 1].get_text())
        if squash(c["核验词"]) in text:
            rows.append((c, None))
        else:
            rows.append((c, "★ 正本第 %d 页里没找到核验词 %r" % (pg, c["核验词"])))
            n_bad += 1
    return rows, n_checked, n_bad, docs


def selftest(bind, root=None):
    """正对照：把每条核验词配到一个**明显不含它**的页（封面），若仍报「找到」⇒ 尺子无分辨力。"""
    print("== 正对照（喂错误页）==")
    std = bind["正本"][0]
    fp = os.path.join(root or ROOT, std["文件"])
    if not os.path.exists(fp):
        print("   ★ 没量到：正本不在，正对照无法构造")
        return 4
    doc = _open_pdf(fp)
    p1 = squash(doc[0].get_text())
    cand = [c for c in bind["条款"]
            if c.get("已核") and c["pdf页"] != 1 and squash(c["核验词"]) not in p1]
    n_all = len([c for c in bind["条款"] if c.get("已核") and c["pdf页"] != 1])
    print("   把 %d 条核验词移到第 1 页（封面）验：%s"
          % (len(cand), "全部报未找到 ⇒ 尺子有分辨力 PASS" if len(cand) == n_all
             else "★ 有词在封面也被判『找到』⇒ FAIL"))
    return 0 if len(cand) == n_all else 1


def check_height(bind, h_model, h_real):
    """4.2.3 高度精度闸 —— 本规定里唯一当下可算的数值条款。

    ★ 传入的 h_real 必须是**已扣掉顶部附属设施**（女儿墙/楼梯房）的高度：
      条款原文「实际高度（……不含顶部建筑附属设施）」。本函数扣不掉，只能要求调用方先扣。
    """
    c = next((x for x in bind["条款"] if x["id"] == "SJZ3W-12/4.2.3"), None)
    if c is None or not c.get("限值"):
        print("★ 没量到：绑定里没有 4.2.3 的高度限值")
        return 4
    lim = c["限值"]
    diff = abs(h_model - h_real)
    if h_real <= 30.0:
        r = diff / h_real
        ok = r <= lim["小于等于30m_相对限"]
        crit = "H=%.2f m ≤30 ⇒ 相对 |Δ|/H = %.4f ≤ %.2f" % (h_real, r, lim["小于等于30m_相对限"])
    else:
        ok = diff <= lim["大于30m_绝对限_m"]
        crit = "H=%.2f m >30 ⇒ |Δ| = %.2f m ≤ %.1f m" % (h_real, diff, lim["大于30m_绝对限_m"])
    print("== 4.2.3 高度精度闸 ==")
    print("   模型高 %.2f / 实景高(已扣顶部附属) %.2f / 差 %.2f m" % (h_model, h_real, diff))
    print("   %s ⇒ %s" % (crit, "PASS" if ok else "FAIL"))
    print("   ★ 取位 %.1f m；实景高须由调用方先扣掉女儿墙/楼梯房，本闸扣不掉。" % lim["取位_m"])
    return 0 if ok else 1


def render_md(bind, rows, out_path):
    """从单一真源生成人读版。**数字不在这里手打**，一律从 JSON 取。"""
    def cell(s):
        # 表格单元格：去空白 + 把竖线转义（条款原文含 `|Δ|` 这类绝对值号，会把表撑破）
        return squash(s).replace("|", "\\|")

    L = ["# 标准绑定（自动生成，勿手改）", "",
         "> 由 `tools/standard_bind.py` 从 `规范/标准绑定.json` 渲染。",
         "> 要改口径改 JSON，**不要改这一份**。", ""]
    L += ["## 正本（本机实有）", ""]
    for s in bind["正本"]:
        L.append("- **%s**：%s（%s，%s 页）" % (s["id"], s["名"], s["发布"], s["pdf页数"]))
        L.append("  - 文件 `%s`" % s["文件"])
        cp = s.get("副本")
        if cp:
            L.append("  - 副本：`%s`（%s，%s 页）" % (cp["文件"], cp["说明"], cp["pdf页数"]))
    L.append("")
    L += ["## 条款：数值 / 出处 / 套用", "",
          "| 条款 | 正本页 | 内容 | 限值 | 套用 | 理由 |",
          "|---|---|---|---|---|---|"]
    for c in bind["条款"]:
        pg = c.get("pdf页")
        pg = "p%s" % pg if pg else "—（未核）"
        lim = c.get("限值")
        lim = "；".join("%s=%s" % (k, v) for k, v in lim.items()) if lim else "—"
        mark = "" if c.get("已核") else "★未核 "
        L.append("| `%s` | %s | %s | %s | %s | %s |"
                 % (c["id"], pg, cell(mark + c["内容"]), cell(lim),
                    cell(c.get("套用", "—")), cell(c.get("理由", "—"))))
    L.append("")
    L += ["## 未核 · 方向引用（本机无正本 ⇒ 不引条款号）", ""]
    for u in bind.get("未核_方向引用", []):
        L.append("- **%s** %s —— %s" % (u["id"], u["名"], u["说明"]))
    L.append("")
    L += ["## 本闸的盲区", "",
          "只验「核验词出现在标称页」；**不验**我对该句的解读与套用判定。",
          "核验词是每条款**抽样**一个，非逐字比对。", ""]
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(SPEC, "标准绑定.json"))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--h-model", type=float, default=None, help="模型高 m（4.2.3 用）")
    ap.add_argument("--h-real", type=float, default=None, help="实景高 m，**已扣顶部附属**（4.2.3 用）")
    a = ap.parse_args()
    if not os.path.exists(a.json):
        print("★ 没量到：绑定文件不在 %s" % a.json)
        return 4
    bind = load(a.json)
    if a.selftest:
        return selftest(bind)

    if (a.h_model is None) != (a.h_real is None):
        print("★ 没量到：4.2.3 要两个高度（模型高 + 已扣附属的实景高），只给了一个")
        return 4
    h_rc = 0
    if a.h_model is not None:
        h_rc = check_height(bind, a.h_model, a.h_real)
        print()

    rows, n_checked, n_bad, docs = verify(bind)
    if n_checked == 0:
        print("★ 没量到：一条「已核」条款都没有（正本都没验，等于没绑定）")
        return 4
    print("== 逐条核正本（%d 条已核）==" % n_checked)
    for c, err in rows:
        print(("  ✔ %-18s p%-3s 核验词 %r 命中" % (c["id"], c["pdf页"], c["核验词"]))
              if err is None else "  ✘ %-18s %s" % (c["id"], err))
    for d in docs.values():
        d.close()

    md = os.path.join(SPEC, "标准绑定.md")
    render_md(bind, rows, md)
    print("\n已核 %d / 未核 %d / 方向引用 %d；对不上 %d 条"
          % (n_checked, len(bind["条款"]) - n_checked,
             len(bind.get("未核_方向引用", [])), n_bad))
    print("写 %s" % md)
    print("★ 盲区：本工具只证「词在该页」，不证「套用判定对」——套用是人的判断，无自动判据。")
    return max(1 if n_bad else 0, h_rc)


if __name__ == "__main__":
    sys.exit(main())
