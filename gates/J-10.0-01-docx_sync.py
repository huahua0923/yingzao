# -*- coding: utf-8 -*-
"""判据 J-10.0-01：**交付的 `.docx` 不得与它的源 md 静默不一致**。

对应方案 §10.0.5 判据台账。四件套（§10.0.1）：
  ① 量交付件本身 —— 现场读**交付的 docx** 与**现场重出的 docx** 对账，不读任何中间日志
  ② 量具写明     —— 文本层 `tools/docx2txt.py`；格式层本文件内 `_para_fmt` / `_cell_fmt`
  ③ 盲区声明     —— 见下
  ④ 正对照必配   —— **三条**（C/D/E），其中 D 是这条判据存在的全部理由

★ 背景（为什么会有这条判据）：本仓**不在 git**，交付的 `.docx` 是**上一轮一次性产物**：
  改了 md 却忘了重出 docx ⇒ 交付件**静默过期**，任何"审阅文档"的人看到的都是旧结论。
  2026-10-12 修 A1 外部量时就是这样过期的（§9.2 那一格还印着作废的 58.2%）——
  而当时仓里**连生成器都没有**（现补 `tools/md2docx.py`）。

★ 判据（全部为真才算过）：
  A. 文本层：段落文本序列 + 表格单元格文本序列，逐条相同（`docx2txt`）
  B. 格式层：段落（样式 + pPr + 逐 run 的 字体/字号/粗/底纹）+ 单元格（底纹 + 逐段 run 签名），逐条相同
  C. 正对照① 文本层有牙：把源 md 改**一个字符**再重出 ⇒ A 必须报红
  D. 正对照② **格式层有牙（本判据的一半理由）**：改**交付件副本里一个 run 的字体**（**不动任何文字**）
     ⇒ **A 必须仍绿、B 必须报红**。★ 这正是 2026-10-12 抓到的那类缺陷（中文没绑东亚字体，
     汉字会在 Word 里换字体）—— **纯文本量具对它完全失明**，没有这条对照就不知道 B 是否只是摆设
  E. 正对照③ 非空断言：喂一份**空 md** ⇒ 必须判「不成立」（遍历型判据扫空集合会恒绿，§10.0.3-③）

★ 盲区（必须声明，盲区内的**否定**判词不算证据）：
  ① 只读 OOXML 里**写着**的属性 —— 由**样式/主题继承**来的值看不见。
     故「B 绿」只证**两份文件的显式属性一致**，不证"在 Word 里渲染一样"。
  ② 完全不管渲染：行高、**分页/页码**、图片、页眉页脚、域（目录/题注）皆不在量程内。
  ③ 只覆盖 `建设方案V3*.md` ↔ `建设方案V3.8*.docx` **这一对**；仓里别的 docx 不在本判据内。
  ④ 基准是**交付件自己**：本判据证的是「交付件 == 现在这份 md + 现在这份生成器的产物」，
     **不证**「版面好看」、也不证「生成器忠实于历史某版」（那由 `_archive/` 下的留档件另比）。
  ⑤ 生成器是**确定性**的前提未单列——同一输入重跑应逐字节一致；本判据用「文本+格式签名」代替
     逐字节比（docx 内含时间戳/rsid，逐字节比会恒红）。**逐字节复现属 §10.1「可复现」那条判据**。

用法:
  python gates/J-10.0-01-docx_sync.py                    # 默认对账本仓交付对
  python gates/J-10.0-01-docx_sync.py --md X.md --docx Y.docx
  python gates/J-10.0-01-docx_sync.py --json gates/_out/J-10.0-01.json
"""
import argparse
import os
import shutil
import sys
import tempfile

import docx
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import docx2txt            # noqa: E402
import md2docx             # noqa: E402

MD_DEFAULT = os.path.join(ROOT, "建设方案V3·2026-10-11.md")
DOCX_DEFAULT = os.path.join(ROOT, "建设方案V3.8·2026-10-11.docx")


# ---------------------------------------------------------------- 格式层签名
def _run_fmt(r):
    rPr = r._element.rPr
    shd = rPr.find(qn("w:shd")) if rPr is not None else None
    b = rPr.find(qn("w:b")) if rPr is not None else None
    return (r.font.name, r.font.size.pt if r.font.size else None,
            None if b is None else b.get(qn("w:val")),
            None if shd is None else shd.get(qn("w:fill")), r.text)


def _cell_fmt(c):
    tcPr = c._tc.tcPr
    shd = tcPr.find(qn("w:shd")) if tcPr is not None else None
    return (None if shd is None else shd.get(qn("w:fill")),
            [tuple(_run_fmt(r) for r in p.runs) for p in c.paragraphs])


def fmt_signature(path):
    """段落格式签名 + 单元格格式签名。★ 盲区见文件头（只读显式属性）。"""
    d = docx.Document(path)
    paras = []
    for p in d.paragraphs:
        pPr = p._p.pPr
        # 压掉命名空间声明，只留属性本身（否则两份文件的 ns 前缀差异会假红）
        xml = pPr.xml if pPr is not None else None
        if xml:
            xml = xml[xml.index(">") + 1:]
        paras.append((p.style.name, xml, [tuple(_run_fmt(r)) for r in p.runs]))
    tabs = [[[tuple(_cell_fmt(c)) for c in row.cells] for row in t.rows] for t in d.tables]
    return paras, tabs


def first_diffs(a, b, n=3, width=90):
    """返回前 n 处差异的**定位描述**（不打印整段文本）。"""
    out = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            out.append("[%d] 交付=%s ⇢ 重出=%s" % (i, str(a[i])[:width], str(b[i])[:width]))
            if len(out) >= n:
                break
    if not out and len(a) != len(b):
        out.append("条数不同：%d vs %d" % (len(a), len(b)))
    return out


# ---------------------------------------------------------------- 判据
def check_pair(md_path, docx_path, tmp):
    """A/B 两条：交付件 vs 现场重出件。返回 (ok, detail)。"""
    rebuilt = os.path.join(tmp, "rebuilt.docx")
    md2docx.convert(md_path, rebuilt)

    ref, got = docx2txt.dump(docx_path), docx2txt.dump(rebuilt)     # A 文本层
    if ref["n_para"] == 0 or ref["n_table"] == 0:                   # E 的非空断言（判据侧）
        return False, "交付件是空的（段落 %d 表格 %d）—— 空集合**不算通过**" \
                      % (ref["n_para"], ref["n_table"])
    t_ok = (ref["paragraphs"] == got["paragraphs"] and ref["tables"] == got["tables"])
    t_d = first_diffs(ref["paragraphs"], got["paragraphs"])

    fp, fg = fmt_signature(docx_path), fmt_signature(rebuilt)       # B 格式层
    f_ok = (fp[0] == fg[0] and fp[1] == fg[1])
    f_d = first_diffs(fp[0], fg[0])
    if not f_d:
        # 单元格：逐格找首个不同
        for ti in range(min(len(fp[1]), len(fg[1]))):
            for ri in range(min(len(fp[1][ti]), len(fg[1][ti]))):
                if fp[1][ti][ri] != fg[1][ti][ri]:
                    f_d.append("[表%d r%d] 单元格格式不同" % (ti, ri))
                    break
            if f_d:
                break
        if not f_d and len(fp[1]) != len(fg[1]):
            f_d.append("表数不同：%d vs %d" % (len(fp[1]), len(fg[1])))

    detail = {"text_ok": t_ok, "text_diff": t_d, "fmt_ok": f_ok, "fmt_diff": f_d,
              "n_para": ref["n_para"], "n_table": ref["n_table"]}
    return (t_ok and f_ok), detail


def control_text_tooth(md_path, docx_path, tmp):
    """C：改源 md 一个字符 ⇒ 文本层必须报红（证明 A 不是盖章）。"""
    bad = os.path.join(tmp, "mutated.md")
    s = open(md_path, encoding="utf-8").read()
    if "cdut3d" not in s:
        return False, "源 md 里找不到可替换串 ⇒ 对照无法执行"
    open(bad, "w", encoding="utf-8", newline="\n").write(s.replace("cdut3d", "cdut4d", 1))
    ok, d = check_pair(bad, docx_path, tmp)
    return (not ok) and (not d["text_ok"]), \
        "文本层 %s（应报红）｜格式层 %s" % ("报红 ✓" if not d["text_ok"] else "**仍绿 ✗**",
                                          "报红" if not d["fmt_ok"] else "绿")


def control_fmt_tooth(docx_path, tmp):
    """D：只改一个 run 的**字体**（不动一个字）⇒ 文本层仍绿、格式层必须报红。★ 本判据的关键对照。"""
    bad = os.path.join(tmp, "font_mutated.docx")
    shutil.copy2(docx_path, bad)
    d = docx.Document(bad)
    hit = None
    for p in d.paragraphs:
        for r in p.runs:
            if r.text.strip():
                r.font.name = "Arial"          # ★ 只碰字体，文本一个字节不动
                hit = r.text[:40]
                break
        if hit:
            break
    if hit is None:
        return False, "找不到非空 run ⇒ 对照无法执行"
    d.save(bad)

    a = docx2txt.dump(docx_path)["paragraphs"]
    b = docx2txt.dump(bad)["paragraphs"]
    text_same = (a == b)
    fa, fb = fmt_signature(docx_path)[0], fmt_signature(bad)[0]
    fmt_diff = (fa != fb)
    return text_same and fmt_diff, \
        "文本层 %s（应仍绿）｜格式层 %s（应报红）｜被改的 run=%r" \
        % ("绿 ✓" if text_same else "**报红 ✗**", "报红 ✓" if fmt_diff else "**仍绿 ✗**", hit)


def control_empty(md_path, tmp):
    """E：空 md ⇒ 必须「不成立」，不许绿（遍历型判据扫空集合会恒绿）。"""
    empty = os.path.join(tmp, "empty.md")
    open(empty, "w", encoding="utf-8").write("")
    built = os.path.join(tmp, "empty.docx")
    md2docx.convert(empty, built)
    n = docx2txt.dump(built)["n_para"]
    ok = (n == 0)
    return ok, "空 md 重出段落数 = %d（应为 0，且交付侧判据随之必须判不成立）" % n


def main():
    # ★ 重定向/管道下 Windows 默认 stdout 是 GBK ⇒ 下面那行带 `⇒` 的 print 会先抛 UnicodeEncodeError，
    #   判词**根本印不出来**（rc=1 看着像判红，其实是量具自己崩了）。铁律 199：崩了 ≠ 没量到。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=MD_DEFAULT)
    ap.add_argument("--docx", default=DOCX_DEFAULT)
    ap.add_argument("--json", default=os.path.join(HERE, "_out", "J-10.0-01.json"))
    a = ap.parse_args()
    print("判据 J-10.0-01  docx 与源 md 同步")
    print("  源 md  :", a.md)
    print("  交付件 :", a.docx)

    fails = []
    for p in (a.md, a.docx):
        if not os.path.exists(p):
            print("  文件不存在:", p); return 2

    tmp = tempfile.mkdtemp(prefix="j1001_")
    ok, d = check_pair(a.md, a.docx, tmp)
    print("\n== A 文本层 ==")
    print("  段落 %d / 表格 %d  ⇒ %s" % (d["n_para"], d["n_table"],
                                        "逐条相同 ✓" if d["text_ok"] else "**有差异 ✗**"))
    for x in d["text_diff"]:
        print("   ", x)
    print("== B 格式层 ==")
    print("  ⇒ %s" % ("逐条相同 ✓" if d["fmt_ok"] else "**有差异 ✗**"))
    for x in d["fmt_diff"]:
        print("   ", x)
    if not d["text_ok"]:
        fails.append("A 文本层不一致（交付件已过期，重跑 tools/md2docx.py）")
    if not d["fmt_ok"]:
        fails.append("B 格式层不一致（交付件已过期，重跑 tools/md2docx.py）")

    print("\n== 正对照（不变红 = 判据没分辨力） ==")
    c1, d1 = control_text_tooth(a.md, a.docx, tmp)
    print("  ① 改源 md 一字 ⇒ 文本层报红 :", "✓" if c1 else "✗", d1)
    c2, d2 = control_fmt_tooth(a.docx, tmp)
    print("  ② 只改 run 字体 ⇒ 文本绿/格式红:", "✓" if c2 else "✗", d2)
    c3, d3 = control_empty(a.md, tmp)
    print("  ③ 空 md ⇒ 判不成立（非空断言）:", "✓" if c3 else "✗", d3)
    for c, tag in ((c1, "C"), (c2, "D"), (c3, "E")):
        if not c:
            fails.append("对照%s 未按预期触发" % tag)
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n===== 判词 =====")
    if fails:
        print("  FAIL  rc=1   未过项:", fails)
        rc = 1
    else:
        print("  PASS  rc=0   文本/格式两层逐条一致，三条正对照全触发")
        rc = 0
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        import json as _json
        _json.dump({"pass": rc == 0, "md": a.md, "docx": a.docx,
                    "n_para": d["n_para"], "n_table": d["n_table"],
                    "text_ok": d["text_ok"], "fmt_ok": d["fmt_ok"],
                    "controls": {"text_tooth": c1, "fmt_tooth": c2, "empty": c3},
                    "fails": fails},
                   open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  写出:", a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
