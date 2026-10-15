# -*- coding: utf-8 -*-
"""方案 md → docx 生成器（2026-10-12 补：此前仓里**没有**生成器，
交付的 `.docx` 是上一轮一次性产物 ⇒ 改了 md 交付件就**静默过期**，谁也发现不了）。

用法: python tools/md2docx.py <in.md> <out.docx>

★★ 版面口径**全部从既有交付件逐项实测**得来（不是设计、不是猜）。2026-10-12 测过**两层**：
  · **文本层**（`tools/docx2txt.py` 抽段落/单元格文本逐条比）：够抓「生成器换了内容会不会变」。
  · **格式层**（`_scratch/peek_fmt.py` / `peek_xml.py` 直接读 OOXML 属性）：
    ★ 第一版只对齐了文本层，格式层一测就现形 —— **中文全都没有绑定东亚字体**：
    旧件每一个 run 都写着 `w:eastAsia="宋体"`，而 python-docx 的 `font.name=` **只写 ascii/hAnsi**，
    于是新版所有汉字在 Word 里会**回退到主题的东亚字体**（不是宋体）。**文本量具对此完全失明。**
    详见 `tools/docx2txt.py` 的「盲区」声明与 `gates/` 里那条判据。

实测契约（旧件 = `_archive/docx-before-dimcheck-v2-20261012-125932/`）：

| 构造 | 字体 | 字号 | 粗 | 其它 |
|---|---|---|---|---|
| 版面 | — | — | — | A4 21×29.7 cm；页边距 左 3.0 / 上右下 2.5 cm |
| 正文 Normal | 宋体 | 12 | 显式 `<w:b w:val="0"/>` | 段后 `w:after=120`（6 pt） |
| 正文加粗 | 宋体 | 12 | `<w:b/>` | — |
| 行内 `` `码` `` | Consolas | 11.5 | 显式 0 | — |
| 代码块 | Consolas | 10.5 | **不写 b** | 底纹 `F2F2F2`；段后 120 + 左缩进 283 twips，整块一段、行间真换行 |
| 标题 1/2/3/4 | 黑体 | **20 / 16 / 14 / 12** | `<w:b/>` + `color=000000` | ★ 字号是 **run 级**的，不是样式级 |
| 表头行 | 宋体 | 12 | `<w:b/>` | ★ 单元格底纹 `D9E2F3`（238 个表头格**全部**有） |
| 表格样式 | — | — | — | 一律 `Table Grid` |

★ 两个易漏点（都是这次量出来的）：
  ① 标题字号在 **run** 上（20/16/14/12），`styles.xml` 里还是 Word 默认的 14/13 —— 只看样式层会读错。
  ② 旧件把标题 run 的 `color` 显式写成 `000000`：Word 内建标题样式默认是**蓝色**
     ⇒ 不写这一笔，标题会在 Word 里变蓝。
  ③ 行内标记**只解析一层**：`` **…`x`…** `` 里层反引号**不会**被剥（旧件同此，
     见单元格 `**只留 `campus_id` 维度**` —— 量到旧件那里反引号是留着的）。
  ④ 标题里的行内标记：**切 run 但格式统一**（黑体的 `spatial_kernel` 仍是黑体 14 pt），标记本身剥掉。

★ 本脚本的**忠实性判据**（两条，缺一条都不算过）：
  1. 文本层：新旧两份各抽「段落文本序列 + 表格单元格文本序列」逐条比（`tools/docx2txt.py`）。
  2. 格式层：新旧两份各抽「段落样式 + 逐 run（字体,字号,粗,底纹）+ pPr」逐条比（`_scratch/cmp_fmt.py`）。

★★ 2026-10-12 追加（**可复现**）：此前本脚本**同输入 ⇒ 不同字节** —— python-docx 存盘时给
ZIP 每个条目盖上**当时的本地时间**（`ZipInfo.date_time`，2 秒粒度）。内部各件逐字节相同、
整包 sha256 却每次都变 ⇒ 归档说明里那句「同输入 ⇒ 同字节」**是假的**（D.9 那次"实测过"
只是两次跑撞进同一个 2 秒窗口的**假绿**）。修法：`_pin_zip()` 存盘后**重封一次**，把所有
条目的 `date_time` 钉成 `PIN_TS`。判据自带 `--selftest` **两档对照**（见 `_selftest`）：
钉了 ⇒ 两次相同（性质本身）／同一份 md 钉不同的 ts ⇒ **必须不同**（证明这性质不是白来的）。
"""
import os
import re
import sys
import zipfile

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: F401  （留作后续对齐用）
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor, Twips

INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")   # ★ 不含 `+`：`+ ` 续行（md 238 行，在围栏内）
                                             #    当列表符号会多切一段 —— 实测旧件是并进上一段
NUMBER = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
FENCE = re.compile(r"^\s*```")
HR = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
SEP_ROW = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

FONT_BODY, FONT_MONO, FONT_HEAD = "宋体", "Consolas", "黑体"
SZ_BODY, SZ_CODE_INLINE, SZ_CODE_BLOCK = 12.0, 11.5, 10.5
HEAD_PT = {1: 20.0, 2: 16.0, 3: 14.0, 4: 12.0}     # ★ run 级字号（styles.xml 里仍是默认值）
SHADE_CODE, SHADE_HEADER = "F2F2F2", "D9E2F3"
SPACING_AFTER = Twips(120)                          # 6 pt
CODE_INDENT = Twips(283)
_FONT_SLOTS = ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs")
PIN_TS = (1980, 1, 1, 0, 0, 0)                      # ZIP 纪元；钉死后整包可复现（见模块 docstring）


def _pin_zip(path, ts=PIN_TS):
    """把所有 ZIP 条目的时间戳钉成 `ts` ⇒ 同输入 ⇒ **同字节**。

    ★ 只重封容器，条目内容原样搬运（`compress_type` / `external_attr` / `create_system` 都照抄）。
    ★ 先写临时件再 `os.replace` —— 半写出的 docx 是个坏交付件。
    """
    tmp = path + ".pintmp"
    with zipfile.ZipFile(path) as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            ni = zipfile.ZipInfo(it.filename, date_time=tuple(ts))
            ni.compress_type = it.compress_type
            ni.external_attr = it.external_attr
            ni.internal_attr = it.internal_attr
            ni.create_system = it.create_system
            zout.writestr(ni, data)
    os.replace(tmp, path)


def _shd(rPr, fill):
    e = OxmlElement("w:shd")
    e.set(qn("w:val"), "clear")
    e.set(qn("w:fill"), fill)
    rPr.append(e)                                   # 旧件里 shd 排在 sz 之后，append 即在此位


def _stamp(run, font, pt, bold, fill=None, black=False):
    """给一个 run 打上**显式**字体/字号/粗体（旧件每个 run 都显式写，不靠样式继承）。

    ★ 四槽一起写（ascii/hAnsi/eastAsia/cs）：只写 ascii+hAnsi 的话，**中文会回退到主题东亚字体**。
    ★ `bold=None` ⇒ 连 `w:b` 元素都不写（旧件的代码块 run 就是这种）。
    """
    rPr = run._element.get_or_add_rPr()
    rf = rPr.get_or_add_rFonts()
    for slot in _FONT_SLOTS:
        rf.set(qn(slot), font)
    if bold is not None:
        run.font.bold = bold                        # True→<w:b/>  False→<w:b w:val="0"/>
    if black:
        run.font.color.rgb = RGBColor(0, 0, 0)
    run.font.size = Pt(pt)
    if fill:
        _shd(rPr, fill)


def _add_runs(p, text, *, head=None, base_bold=False):
    """把行内 `**粗**` / `` `码` `` 切成 run。
    head=级别 ⇒ 标题：**切 run 但格式统一**（黑体 + 该级别字号 + 粗 + 纯黑）。
    否则正文：宋体 12（`**` 处粗、`` ` `` 处 Consolas 11.5）。"""
    for part in INLINE.split(text):
        if not part:
            continue
        if head is not None:
            r = p.add_run(part[2:-2] if (len(part) > 4 and part[:2] == "**" and part[-2:] == "**")
                          else (part[1:-1] if (len(part) > 2 and part[0] == "`" and part[-1] == "`")
                                else part))
            _stamp(r, FONT_HEAD, HEAD_PT[head], True, black=True)
        elif len(part) > 4 and part[:2] == "**" and part[-2:] == "**":
            r = p.add_run(part[2:-2])
            _stamp(r, FONT_BODY, SZ_BODY, True)     # ★ 不加黑体：旧件正文粗体仍是宋体
        elif len(part) > 2 and part[0] == "`" and part[-1] == "`":
            r = p.add_run(part[1:-1])
            _stamp(r, FONT_MONO, SZ_CODE_INLINE, False)
        else:
            r = p.add_run(part)
            _stamp(r, FONT_BODY, SZ_BODY, base_bold)


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]        # ★ `<br>` 原样留（旧件 1800 格里实有 6 处字面量）


def _is_table(lines, i):
    return (lines[i].strip().startswith("|") and i + 1 < len(lines)
            and SEP_ROW.match(lines[i + 1]) and "-" in lines[i + 1])


def _cell_shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    e = OxmlElement("w:shd")
    e.set(qn("w:val"), "clear")
    e.set(qn("w:fill"), fill)
    tcPr.append(e)


def convert(md_path, out_path, ts=PIN_TS):
    lines = open(md_path, encoding="utf-8").read().split("\n")
    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = Cm(3.0)
    sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(2.5)
    nf = d.styles["Normal"].font
    nf.name = "宋体"
    nf.size = Pt(SZ_BODY)
    nf.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")   # ★ 不写这一笔，中文在 Word 里换字体

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i].rstrip()
        if not raw.strip():
            i += 1; continue

        if _is_table(lines, i):                       # —— 表格
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                if not SEP_ROW.match(lines[i]):
                    rows.append(_cells(lines[i]))
                i += 1
            ncol = max(len(r) for r in rows)
            t = d.add_table(rows=len(rows), cols=ncol)
            t.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci in range(ncol):
                    cell = t.cell(ri, ci)
                    if ri == 0:
                        _cell_shade(cell, SHADE_HEADER)
                    _add_runs(cell.paragraphs[0], row[ci] if ci < len(row) else "",
                              base_bold=(ri == 0))
            continue

        m = HEAD.match(raw)
        if m:                                          # —— 标题（run 级字号，见文件头契约表）
            lv = min(len(m.group(1)), 4)
            p = d.add_heading(level=lv)
            _add_runs(p, m.group(2), head=lv)
            i += 1; continue

        if HR.match(raw):                              # —— 分隔线：原样进 Normal
            p = d.add_paragraph(); p.paragraph_format.space_after = SPACING_AFTER
            _add_runs(p, raw.strip()); i += 1; continue

        mb, mn = BULLET.match(raw), NUMBER.match(raw)
        if mb or mn:                                   # —— 列表（样式自带缩进，不加段后距）
            mk = mb or mn
            p = d.add_paragraph(style="List Bullet" if mb else "List Number")
            _add_runs(p, mk.group(2))
            i += 1; continue

        if FENCE.match(raw):                           # —— 围栏代码块：整块一段，行间真换行
            i += 1
            blk = []
            while i < n and not FENCE.match(lines[i]):
                blk.append(lines[i].rstrip())
                i += 1
            i += 1
            if blk:
                p = d.add_paragraph()
                p.paragraph_format.space_after = SPACING_AFTER
                p.paragraph_format.left_indent = CODE_INDENT
                # ★ **一行一个 run**（旧件如此：除末行外每行 run 尾带一个 <w:br/>）。
                #   合成一个 run 文本读回来一样、渲染也一样，但 run 结构对不上 —— 格式层判据会红。
                for k, line in enumerate(blk):
                    tail = "\n" if k < len(blk) - 1 else ""
                    r = p.add_run(line + tail)         # add_run 把 \n 落成 <w:br/>，读回仍是 \n
                    _stamp(r, FONT_MONO, SZ_CODE_BLOCK, None, fill=SHADE_CODE)  # ★ 不写 w:b
            continue

        # —— 普通段落：合并连续非空、且不是特殊块的行（行间插一个空格）
        buf = []
        while i < n and lines[i].strip() and not (
                HEAD.match(lines[i].rstrip()) or HR.match(lines[i].rstrip())
                or BULLET.match(lines[i].rstrip()) or NUMBER.match(lines[i].rstrip())
                or FENCE.match(lines[i]) or _is_table(lines, i)
                or lines[i].strip().startswith("|")):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            p = d.add_paragraph()
            p.paragraph_format.space_after = SPACING_AFTER
            _add_runs(p, " ".join(buf))

    d.save(out_path)
    _pin_zip(out_path, ts)                          # ★ 钉死容器时间戳 ⇒ 同输入同字节
    return {"paragraphs": len(d.paragraphs), "tables": len(d.tables)}


def _sha(p):
    import hashlib
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _selftest():
    """正对照：必须**能变红**才算有牙（铁律 137/183）。夹具写系统临时目录，不落本仓。"""
    import tempfile
    d = tempfile.mkdtemp(prefix="md2docx_selftest_")
    md = os.path.join(d, "t.md")
    open(md, "wb").write("# 标题\r\n\r\n正文 `码` **粗**\r\n\r\n| A | B |\r\n|---|---|\r\n| 1 | 2 |\r\n"
                         .encode("utf-8"))
    nbad = 0

    def case(ok, what, detail=""):
        nonlocal nbad
        nbad += 0 if ok else 1
        print("  %s %-40s %s" % ("✓" if ok else "✗ ← 守卫不对", what, detail))

    a, b = os.path.join(d, "a.docx"), os.path.join(d, "b.docx")
    convert(md, a); convert(md, b)                   # 同一份 md，连出两次
    case(_sha(a) == _sha(b), "① 同输入 ⇒ 同字节（这就是被修的性质）",
         "%s / %s" % (_sha(a)[:12], _sha(b)[:12]))

    c = os.path.join(d, "c.docx"); convert(md, c, ts=(1999, 9, 9, 9, 9, 8))
    case(_sha(a) != _sha(c), "② 换 ts ⇒ 必须不同（证明①不是白来的）",
         "差在容器时间戳，内容同" if _sha(a) != _sha(c) else "★ 换了 ts 竟还一样")

    case(zipfile.ZipFile(a).read("word/document.xml")
         == zipfile.ZipFile(c).read("word/document.xml"),
         "② 两份的正文部件逐字节相同（差只在容器）", "word/document.xml 相同")

    case(not os.path.exists(a + ".pintmp"), "③ 不留半成品临时件", "无 .pintmp 残留")

    print("\n自测：%d 档不通过（期望 0）⇒ %s"
          % (nbad, "本件有牙" if not nbad else "**自身有问题**"))
    return 1 if nbad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if len(sys.argv) < 3:
        print("用法: python tools/md2docx.py <in.md> <out.docx>"); sys.exit(2)
    info = convert(sys.argv[1], sys.argv[2])
    print("写出 %s  段落 %d  表格 %d" % (sys.argv[2], info["paragraphs"], info["tables"]))
