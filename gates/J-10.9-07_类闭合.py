# -*- coding: utf-8 -*-
r"""判据 J-10.9-07：构件**类名闭合** —— 每一处枚举里都有它，且它真的到得了交付件。

★ 为什么要单开一条（2026-10-15，用户「你继续做」；病根是当天那个 `ROOF`）：
  链上「一个构件类」要被**七处**各自点名才算走通。七处里任何一处漏了，
  **都不报错**：②③④ 漏 = 静默丢件、按类全失效；⑦ 漏 = 那一类在页面上与墙撞色、
  连图例都不显示。今天真实发生过两次：`LINTEL`（门头墙）与 `ROOF`（塔楼屋面板）。
  `ROOF` 是**整整一站没发给 SU** —— `build3d.py:957` 早就把它建好了，
  `export_contours.py::_attach_recs` 里没有它，于是顶层 911 m² 一直是空的，
  而所有既有判据全绿。当时唯一的防线是 `rebuild/构件清单.md` §7.2 的**散文**
  （而且它还把处数记成了「三处」，现货是七处）。散文不是判据（铁律 7/137/158）。

  ⇒ 本判据把「七处一起改」这句**话**变成一条**能红的尺子**。

判据
 ① **上游分类集（两处独立生成）**：
    A1 = `build.json`（`build3d.py` 出件那趟落的账）→ `floors[].z_by_class` 的键
         ∪ `attach` 的键按**机械规则**还原出的类名（去 `n_` 前缀 / 去 `_m`/`_m2` 后缀 /
         去尾数字后大写：`roof_step7_m2` → `ROOF_STEP`）。
    A2 = `contours/index.json`（`export_contours.py` 出件那趟落的账）→ 逐层 `per_layer` 键并集。
    **A1 必须 = A2**（两个生成器说同一件事）；**A1 必须 = 标准**（下方 `STD`）。
 ② **六处点名解析**（②a ②b ③ ④ ⑥ ⑦）：每一处的类名集合**必须恰好等于** `STD`
    （少一个 = 洞；多一个 = 标准没跟着长）。⑤ 是**子集位**（顶部三件），只查 ⊆ `STD`。
 ③ **实到**：交付件 `rebuild/06_su/c006_su.obj` 的 `g` 组名里，`STD` 每一类都必须有 ≥1 组。
    ★★ **这一栏是 `export_contours.py::_attach_recs`（「发不发得出去」的唯一开关）的守卫** ——
       那个开关是一串 `if`，**没有**一张能被 ② 那种点名解析读到的清单，所以它只能**行为地**守：
       「枚举里有它、却一块都没到件」这件事，只有本栏看得见。`ROOF` 当年就是死在这一栏上。
 ④ **正对照 · 解析器有没有分辨力**（铁律 137：得喂过坏输入才准转绿）：
    对每一处、每一个它现读出来的类名，把该处源文本里那个类名**按整词删掉**
    （`\b` 边界 ⇒ 删 `ROOF` 不会误伤 `ROOF_STEP`），同一把解析器必须报缺它。
 ⑤ **正对照 · 实到那栏有没有分辨力**：喂三份**真出过这个毛病的旧件**
    （模型库里 `坏_没有门头墙.obj`、换门头墙之前的正式件、换楼梯模块之前的正式件），
    必须逐一点名它们缺的类。
 ⑥ **未登记位扫描（⚠ 只报不判）**：在 `rebuild/` `gates/` `demo/` `tools/` 的
    `*.py` / `*.rb` / `*.js` / `*.html` 里找「同一行出现 ≥4 个类名」的行；
    凡不在**登记位**也不在 **`NOT_ENUM` 白名单**里的，列出来给人看，**不改退出码**。
    ★ 为什么只报不判：这个形状命中的多半是散文与别的命名空间（审图图层名等），
      判红会产生大量假红；而假红会让人开始忽略这条闸（那就等于没有闸）。
      按用户口径「**只报不判要写明**」处理。

量具
 `rebuild/05_build/build.json`、`rebuild/06_su/contours/index.json`、
 `rebuild/06_su/c006_su.obj`、六处源文件的**文本**（`re` 扫，不 import、不执行）。

量具盲区（★先声明，再判）
 · 登记位是**手写**的七处。**新出现**一处硬编码类名表，本判据的 ② 看不见它 ——
   只有 ⑥（只报不判）与读日志的人能看见。这是本判据最大的一处盲。
 · ⑥ 的扫描只认「同一行 ≥4 个类名」。把类名**拆成多行**或写进数据结构就扫不到 ⇒
   「没报未登记位」**推不出**「没有未登记位」（铁律 158）。
 · ② 只比**集合**。`[A-Z_]+` 之外的写法（小写键、数字后缀、拼接字符串）解析不到，
   那种写法会让某处的集合变小 ⇒ 报**缺**（偏保守，是安全方向）；但若某处
   把类名写成完全不可解析的形状，集合会是空 ⇒ 本判据按「**没量到**」报 rc=4 单列，
   不与「判红」混（铁律 199）。
 · ③ 只判「有没有到」**不判「到得对不对」**：块数、位置、形状是
   `J-10.8-02`（SU 侧）与 `J-10.9-01/02/03`（构件库三条）的活。
 · `STD` 这份标准是**人写**的（唯一一份）。本判据**不**证明这 11 类是对的，
   只证明链上各处与它一致。

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（`build.json` / `contours/index.json` /
      `c006_su.obj` 任一不在，或某处解析不出类名 —— 「没量到」不是「判红」）
"""
import argparse
import collections
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = r"D:\项目\cdut3d"
OUTD = os.path.join(HERE, "_out")
OUT = os.path.join(OUTD, "J-10.9-07.txt")

BUILD = "rebuild/05_build/build.json"
CONT_IDX = "rebuild/06_su/contours/index.json"
OBJ = "rebuild/06_su/c006_su.obj"

#: **标准**：链上认的构件类。**唯一一份**（铁律 174：同名的量只许有一个）。
#: 加类时改这里 + `rebuild/构件清单.md` §7.2 那份处数清单，两处一起动。
STD = ("WALL", "COL", "LIFT", "SLAB", "DOOR", "STAIR",
       "LINTEL", "PARAPET", "ROOF_STAIR", "ROOF_STEP", "ROOF")
STDS = frozenset(STD)

#: 一处枚举位 = (编号, 人读名, 源文件, 起始标记, 起始括号, 收尾括号, full|subset)
SITES = (
    ("②a", "export_contours.py::PUSH_MM（层常数）", "rebuild/tools/export_contours.py",
     "PUSH_MM = {", "{", "}", "full"),
    ("②b", "export_contours.py::CLS_CN（人读名）", "rebuild/tools/export_contours.py",
     "CLS_CN = {", "{", "}", "full"),
    ("③", "su_step2_build.rb::BATCHES（SU 建组类名表）", "rebuild/06_su/su_step2_build.rb",
     "BATCHES = [", "[", "]", "full"),
    ("④", "gates/J-10.8-00::LAYERS", "gates/J-10.8-00_contours.py",
     "LAYERS = (", "(", ")", "full"),
    ("⑤", "gates/J-10.8-02::ATTACH（顶部三件）", "gates/J-10.8-02_su.py",
     "ATTACH = (", "(", ")", "subset"),
    ("⑥", "compare3d.py::KINDS", "rebuild/tools/compare3d.py",
     "KINDS = (", "(", ")", "full"),
    ("⑦", "demo/index.html::CLASS_STYLE（图例与配色）", "demo/index.html",
     "const CLASS_STYLE = {", "{", "}", "full"),
)

#: ⑥ 扫描的**白名单**：这些行命中「≥4 个类名」但不是类枚举，写上理由（不许空着）
NOT_ENUM = {
    "rebuild/tools/redraw.py":
        "审图 DXF 的**图层名**（`WALL/COL/DOOR/STAIR` 四类的一个**子集命名空间**），"
        "不是发给 SU 的类枚举",
    "rebuild/tools/review_index.py":
        "同一份审图说明的**散文**（写给人看的表头与说明）",
    "rebuild/tools/su_obj_to_glb.py":
        "docstring 里的**节点结构散文**；真正的开关是两条正则，命中不到就报错退出",
    "demo/build_pack.py":
        "`_MAIN_CLS` 是**故意的子集**（算塔楼顶标高只用主体 6 类）＋ `blind_spots` 散文",
    "gates/J-10.9-07_类闭合.py":
        "本判据自己：`STD` 就是那份标准的**唯一一份**，`SITES` / `NOT_ENUM` 是那张名册"
        "（即 ⑥ 的登记位来源本身，不是第九处枚举）",
}

#: ⑥ 扫描时跳过的目录（scratch 与归档不属于这条链）
SKIP_PARTS = ("_archive", "__pycache__", "_scratch")

#: ⑤ 三份**真出过这个毛病**的旧件 + 它们被点到名时**应缺**的类
OBJ_CTL = (
    ("rebuild/模型库/坏_没有门头墙.obj", ("LINTEL",),
     "模型库三个坏件之一：`LINTEL` 被整类删掉"),
    ("rebuild/06_su/_archive/su_before_doorfix_20261015/c006_su.obj", ("LINTEL", "ROOF"),
     "换门头墙之前那趟留下的正式件"),
    ("rebuild/_archive/06_su-c006-before-stairmodule-20261014/c006_su.obj", ("LINTEL", "ROOF"),
     "换楼梯模块之前那趟留下的正式件"),
)

BLIND = [
    "登记位是手写的七处；**新出现**一处硬编码类名表，② 看不见（只有只报不判的 ⑥ 与读日志的人看得见）",
    "⑥ 只认「同一行 ≥4 个类名」；拆成多行就扫不到 ⇒「没报未登记位」推不出「没有未登记位」",
    "② 只比集合，不比语义；类名写成不可解析的形状 ⇒ 该处按「没量到」报 rc=4",
    "③ 只判「有没有到」，不判「到得对不对」（块数/位置/形状归 J-10.8-02 与构件库三条）",
    "`STD` 是人写的唯一一份标准；本判据不证明这 11 类是对的，只证明各处与它一致",
]

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


def write(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(("\n".join(_LOG) + "\n").encode("utf-8").replace(b"\r\n", b"\n"))


def json_path(out_txt):
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


def rp(rel):
    return os.path.join(ROOT, rel.replace("/", os.sep))


def read_text(rel):
    with io.open(rp(rel), "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


# ----------------------------------------------------------------- 解析器（六处共用一把）
_RE_Q = re.compile(r'"([A-Z][A-Z0-9_]*)"')             # "WALL"
_RE_K = re.compile(r"(?m)^\s*([A-Z][A-Z0-9_]*)\s*:")   #   WALL:
_RE_W = re.compile(r"%w\[([^\]]*)\]")                  # %w[WALL COL]


def tokens(block):
    """从一段源码文本里取出**类名**（∩ `STD`）。

    ★ 只收两种形状：双引号串、行首 `KEY:`；外加 Ruby 的 `%w[...]`。
      散文里的裸类名（反引号/无引号）**不收** —— 收进来会把注释当成枚举。
    """
    t = set(_RE_Q.findall(block)) | set(_RE_K.findall(block))
    for grp in _RE_W.findall(block):
        t |= set(grp.split())
    return t & STDS


def slice_balanced(text, marker, op, cl):
    """从 `marker` 起做括号配平，返回含首尾括号的那一段。找不到返回 None。"""
    i = text.find(marker)
    if i < 0:
        return None
    j = text.find(op, i)
    if j < 0:
        return None
    d = 0
    for k in range(j, len(text)):
        if text[k] == op:
            d += 1
        elif text[k] == cl:
            d -= 1
            if d == 0:
                return text[j:k + 1]
    return None


def parse_site(src, marker, op, cl):
    """→ `(类名集合, 原始块)`；块取不到 ⇒ `(None, None)`（「没量到」）。"""
    blk = slice_balanced(src, marker, op, cl)
    if blk is None:
        return None, None
    return tokens(blk), blk


def strip_token(blk, cls):
    r"""按**整词**删掉一个类名。`\b` 保证删 `ROOF` 不会误伤 `ROOF_STEP`。"""
    return re.sub(r"\b%s\b" % cls, " ", blk)


# ----------------------------------------------------------------- ① 上游两个独立生成器
def attach_classes(keys):
    """`attach` 的键 → 类名，机械还原（不手打表）。

    `n_parapet`→PARAPET · `parapet_m`→PARAPET · `roof_step7_m2`→ROOF_STEP
    """
    out = set()
    for k in keys:
        s = re.sub(r"^n_", "", k)
        s = re.sub(r"_m2?$", "", s)
        s = re.sub(r"\d+$", "", s)
        out.add(s.upper())
    return out


def derive_upstream():
    """→ `(A1, A2, 原始读数)`；文件不在 ⇒ `(None, None, …)`。"""
    pb, pc = rp(BUILD), rp(CONT_IDX)
    if not (os.path.exists(pb) and os.path.exists(pc)):
        return None, None, {"build": os.path.exists(pb), "contours": os.path.exists(pc)}
    with io.open(pb, "r", encoding="utf-8") as fh:
        b = json.load(fh)
    a1 = set()
    for f in b.get("floors", []):
        a1 |= {k.upper() for k in f.get("z_by_class", {})}
    att = attach_classes(b.get("attach", {}))
    a1 |= att
    with io.open(pc, "r", encoding="utf-8") as fh:
        idx = json.load(fh)
    a2 = set()
    rows = idx if isinstance(idx, list) else idx.get("floors", [])
    for r in rows:
        a2 |= set(r.get("per_layer", {}))
    return a1, a2, {"n_floors_build": len(b.get("floors", [])), "attach": sorted(att),
                    "n_rows_contours": len(rows)}


# ----------------------------------------------------------------- ③ 实到（交付件）
_RE_G = re.compile(r"^g\s")
_RE_C = re.compile(r"__([A-Z][A-Z0-9_]*)")


def obj_roster(path):
    """→ `(g 行数, Counter)`；认不出的组名记进 `(未认出的组名)`。"""
    c = collections.Counter()
    n = 0
    if not os.path.exists(path):
        return None, None
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if not _RE_G.match(ln):
                continue
            n += 1
            m = _RE_C.search(ln)
            tok = m.group(1) if m else None
            c[tok if tok in STDS else "(未认出的组名)"] += 1
    return n, c


def missing_in(roster):
    return sorted(c for c in STD if roster.get(c, 0) <= 0)


# ----------------------------------------------------------------- ⑥ 只报不判：未登记位扫描
SCAN_DIRS = ("rebuild", "gates", "demo", "tools")
SCAN_EXT = (".py", ".rb", ".js", ".html")
_RE_ANY = re.compile(r"\b(%s)\b" % "|".join(sorted(STD, key=len, reverse=True)))


def scan_sites():
    """→ 未登记位的 `[(相对路径, 行号, 类名个数)]`。**只报不判。**"""
    reg = {s[2] for s in SITES}
    out = []
    for root in SCAN_DIRS:
        base = rp(root)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in SKIP_PARTS]
            for f in sorted(fn):
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                if not f.endswith(SCAN_EXT) or rel in reg or rel in NOT_ENUM:
                    continue
                with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
                    for i, ln in enumerate(fh, 1):
                        s = set(_RE_ANY.findall(ln))
                        if len(s) >= 4:
                            out.append((rel, i, len(s)))
    return out


# ----------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="J-10.9-07 构件类名闭合")
    ap.add_argument("--out", default=OUT, help="判词落盘路径")
    a = ap.parse_args(argv)
    bad, unmeasured = [], []
    rd = {"standard": list(STD)}

    log("=" * 78)
    log("J-10.9-07 构件**类名闭合**：七处枚举是否都知道同一批类，且它们真的到得了件")
    log("标准 STD（人写的唯一一份，%d 类）：%s" % (len(STD), " ".join(STD)))
    log("-" * 78)

    # ---- ① 上游两个独立生成器
    a1, a2, meta = derive_upstream()
    if a1 is None:
        log("★ 没量到：%s / %s 至少有一样不在（%s）" % (BUILD, CONT_IDX, meta))
        return finish(4, a.out, rd)
    rd["A1_build"], rd["A2_contours"] = sorted(a1), sorted(a2)
    log("① 上游分类集（两处**独立生成**的账）")
    log("   A1 `%s`（z_by_class 键 ∪ attach 机械还原）= %d 类" % (BUILD, len(a1)))
    log("      + attach 还原出：%s" % (" ".join(meta["attach"]) or "（无）"))
    log("   A2 `%s`（逐层 per_layer 键并集，%d 层）= %d 类"
        % (CONT_IDX, meta["n_rows_contours"], len(a2)))
    if a1 != a2:
        bad.append("① A1 ≠ A2：只在 build.json 里 %s ／ 只在 contours 里 %s（铁律 174）"
                   % (sorted(a1 - a2), sorted(a2 - a1)))
        log("   ✗ A1 ≠ A2：只在 build 里 %s ／ 只在 contours 里 %s"
            % (sorted(a1 - a2), sorted(a2 - a1)))
    else:
        log("   ✔ A1 = A2")
    if a1 != STDS:
        bad.append("① 上游类集 ≠ 标准：缺 %s ／ 多 %s（标准没跟着长，或某类被删）"
                   % (sorted(STDS - a1), sorted(a1 - STDS)))
        log("   ✗ 上游 ≠ 标准：缺 %s ／ 多 %s" % (sorted(STDS - a1), sorted(a1 - STDS)))
    else:
        log("   ✔ 上游 = 标准")

    # ---- ② 六处点名解析（含 ④ 正对照）
    log("-" * 78)
    log("② 登记位逐个点名解析（full = 必须恰好相等；subset = 只许是标准的一部分）")
    log("   %-4s %-46s %-6s %s" % ("位", "处", "读到", "判"))
    src_cache, ctl_bad, ctl_n = {}, 0, 0
    site_tok = {}
    for num, name, rel, marker, op, cl, kind in SITES:
        if rel not in src_cache:
            src_cache[rel] = read_text(rel) if os.path.exists(rp(rel)) else None
        src = src_cache[rel]
        if src is None:
            unmeasured.append("%s %s：源文件不在" % (num, rel))
            log("   %-4s %-46s %-6s ★ 没量到（源文件不在）" % (num, name, "—"))
            continue
        t, blk = parse_site(src, marker, op, cl)
        if not t:
            unmeasured.append("%s %s：起始标记 %r 取不到类名" % (num, rel, marker))
            log("   %-4s %-46s %-6s ★ 没量到（标记 %r 解析不出类名）" % (num, name, "—", marker))
            continue
        site_tok[num] = sorted(t)
        if kind == "subset":
            if t <= STDS:
                note = "子集 ✔（%s）" % " ".join(sorted(t))
            else:
                note = "✗ 出现标准外的类 %s" % sorted(t - STDS)
                bad.append("⑤ %s 里出现标准外的类：%s" % (rel, sorted(t - STDS)))
        else:
            if t == STDS:
                note = "✔ 全等"
            else:
                note = "✗ 缺 %s／多 %s" % (sorted(STDS - t), sorted(t - STDS))
                bad.append("%s %s：缺 %s ／ 多 %s"
                           % (num, name, sorted(STDS - t), sorted(t - STDS)))
        log("   %-4s %-46s %-6d %s" % (num, name, len(t), note))
        # ④ 正对照：逐类删掉，必须报缺
        for cls in sorted(t):
            ctl_n += 1
            t2 = tokens(strip_token(blk, cls))
            if cls in t2:
                ctl_bad += 1
                log("     ✗ 正对照：删掉 %s 后解析器仍读得到它 ⇒ 这一处没有分辨力" % cls)
    if ctl_bad:
        bad.append("④ 解析器正对照失败 %d / %d 条（判据没有分辨力，铁律 137）" % (ctl_bad, ctl_n))
    rd["site_tokens"] = site_tok
    rd["control_parser"] = {"n": ctl_n, "bad": ctl_bad}

    # ---- ③ 实到 + ⑤ 正对照
    log("-" * 78)
    log("③ 实到：交付件 `%s` 的 `g` 组名里，标准每一类都要有 ≥1 组" % OBJ)
    n_g, roster = obj_roster(rp(OBJ))
    if n_g is None:
        unmeasured.append("③ 交付件不在：%s" % OBJ)
        log("   ★ 没量到：件不在")
    else:
        miss = missing_in(roster)
        log("   g 行 %d；逐类 = %s"
            % (n_g, " ".join("%s%d" % (k, roster.get(k, 0)) for k in STD)))
        unk = roster.get("(未认出的组名)", 0)
        rd["obj"] = {"n_g": n_g, "by_class": {k: roster.get(k, 0) for k in STD},
                     "unknown": unk, "missing": miss}
        if unk:
            bad.append("③ 件里有 %d 个组名认不出类（标准外的类到了件里）" % unk)
            log("   ✗ 未认出的组名 %d 个" % unk)
        if miss:
            bad.append("③ 标准里有类**一块都没到件**：%s —— 枚举里有它、却没人发出去"
                       "（`export_contours.py::_attach_recs` 这一栏的守卫，铁律 158）" % miss)
            log("   ✗ 一块都没到件：%s" % miss)
        else:
            log("   ✔ %d 类全部到件" % len(STD))
        log("   ⑤ 正对照（喂真出过这个毛病的旧件，它必须点名缺了谁）")
        for rel, expect, why in OBJ_CTL:
            p = rp(rel)
            if not os.path.exists(p):
                log("     · %-58s ★ 件不在，跳过" % rel)
                continue
            _n2, r2 = obj_roster(p)
            got = tuple(missing_in(r2))
            hit = (got == tuple(sorted(expect)))
            log("     %s %-58s 读出缺 %s（要 %s）"
                % ("✔" if hit else "✘", rel, list(got), sorted(expect)))
            if not hit:
                bad.append("⑤ 正对照 %s 读出缺 %s，要的是 %s" % (rel, list(got), sorted(expect)))
            rd.setdefault("control_obj", []).append(
                {"piece": rel, "why": why, "got": list(got), "want": sorted(expect)})

    # ---- ⑥ 只报不判
    log("-" * 78)
    log("⑥ 未登记位扫描（⚠ **只报不判**，不改退出码；理由见文件头盲区）")
    un = scan_sites()
    rd["unregistered"] = [{"file": f, "line": i, "n": k} for f, i, k in un]
    if un:
        for f, i, k in un:
            log("   ⚠ %s:%d（%d 个类名）" % (f, i, k))
        log("   ⚠ 共 %d 行命中且不在登记位/白名单里 —— 请人判：是类枚举就该登记，"
            "不是就进白名单" % len(un))
    else:
        log("   （没有未登记的命中）")

    # ---- 收口
    log("=" * 78)
    if unmeasured:
        log("★ 没量到（**不是判红**，铁律 199）：")
        for x in unmeasured:
            log("   · " + x)
        log("J-10.9-07 总判 : SKIP（%d 条没量到）" % len(unmeasured))
        rd["unmeasured"] = unmeasured
        return finish(4, a.out, rd)
    log("J-10.9-07 总判 : %s" % ("PASS" if not bad else "FAIL（%d 条）" % len(bad)))
    for x in bad:
        log("  ✗ " + x)
    rd["n_violations"] = len(bad)
    return finish(0 if not bad else 1, a.out, rd)


if __name__ == "__main__":
    sys.exit(main())
