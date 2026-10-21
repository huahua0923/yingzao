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

sys.path.insert(0, HERE)
import _verdict as VD                                            # noqa: E402
import _items as I                                               # noqa: E402

# ★ 2026-10-19：件路径**只从** `_verdict.paths()` 来（原来写死 c006 的相对路径）。
#   交付件：c005/c006 有 `_su.obj` 用它；其余楼只有 FreeCAD 的 `_fc.obj`，用它并记进 files。
BID = VD.bid_from()
_P = VD.paths(BID)
BUILD = _P["build_json"]
CONT_IDX = _P["index"]
OBJ = _P["deliver"]

#: **标准**：链上认的构件类。**唯一一份**（铁律 174：同名的量只许有一个）。
#: 加类时改这里 + `rebuild/构件清单.md` §7.2 那份处数清单，两处一起动。
# ★★ 2026-10-19：补 `ROOF_ROOM`（出屋面楼梯间+电梯机房）。`export_contours.py` 从
#   2026-10-18 起就发这一类、`PUSH_MM`/`CLS_CN` 两处枚举也都有它，**唯独这份标准没有**
#   ⇒ ② 那两处按 full 比会「多一类」判红，而 ③ 又对它全盲（不在 STD 里就根本不被要求）。
#   这正是本判据要防的那种漂移，却发生在它自己的量尺上（铁律 137/183）。
#   同一轮 `build3d.py::attach` 补了 `n_roof_room` 键，A1 才推得出这一类。
STD = ("WALL", "COL", "LIFT", "SLAB", "DOOR", "STAIR",
       "LINTEL", "PARAPET", "ROOF_STAIR", "ROOF_STEP", "ROOF", "ROOF_ROOM")
STDS = frozenset(STD)

#: 一处枚举位 = (编号, 人读名, 源文件, 起始标记, 起始括号, 收尾括号, full|subset)
SITES = (
    ("②a", "export_contours.py::PUSH_MM（层常数）", "rebuild/tools/export_contours.py",
     "PUSH_MM = {", "{", "}", "full"),
    ("②b", "export_contours.py::CLS_CN（人读名）", "rebuild/tools/export_contours.py",
     "CLS_CN = {", "{", "}", "full"),
    # ★★ 2026-10-19：这两处是**真·类枚举**（12 类全列），原先只在 ⑥ 里以 ⚠ 露头 ——
    #   而 ⑥ 只报不判 ⇒ 它们漂开了也不会红（本判据盲区第一条点名的就是这件事）。
    #   登记进 SITES 之后 ② 会逐位比对（缺/多都红），④ 正对照也逐类删一遍。
    ("②c", "contours_to_fc.py::CLASSES（CAD 要素类）",
     "rebuild/tools/contours_to_fc.py", "CLASSES = (", "(", ")", "full"),
    ("②d", "模型库/obj_text_metrics.py::STDS（组名解析）",
     "rebuild/模型库/obj_text_metrics.py", "STDS = (", "(", ")", "full"),
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
    "rebuild/tools/defect_scan.py":
        "`layers = (\"WALL\",\"COL\",\"STAIR\",\"LIFT\",\"LINTEL\")` 是**缺陷扫描的参照物子集**"
        "（只挑能贴附的构件），不是发给 SU 的类枚举；同文件另一行是解释它的散文",
    "rebuild/tools/overlay_check.py":
        "`COVER_KINDS` 是**覆盖面判据的参照子集**（5 类），同文件另一行是解释它的散文",
    "gates/J-10.10-08_顶部三个推的数对照2024实景.py":
        "只有 `log(\"… ROOF … PARAPET …\")` 一行**日志散文**，不是枚举",
    "gates/J-10.8-04_overlay.py":
        "文件头 docstring 的**散文**（写给人看的覆盖面说明），真正的表在 `overlay_check.py`",
    "demo/build_pack_bid.py":
        "`MAIN_CLS` 与 `demo/build_pack.py::_MAIN_CLS` 同一件事：**故意的子集**"
        "（算塔楼顶标高只用主体 6 类）",
    "demo/build_pack_c005.py":
        "同上：`MAIN_CLS` 是**故意的子集**（主体 6 类），与 `demo/build_pack.py` 同规",
    "demo/sys.html":
        "**生成出来的页面**（判据名册的 HTML 文本），里面的类名是散文",
    "gates/J-10.9-07_类闭合.py":
        "本判据自己：`STD` 就是那份标准的**唯一一份**，`SITES` / `NOT_ENUM` 是那张名册"
        "（即 ⑥ 的登记位来源本身，不是第九处枚举）",
}

#: ⑥ 扫描时跳过的目录（scratch 与归档不属于这条链）
# ★ 2026-10-19 补 `_bisect`：`rebuild/06_su/_bisect/*.rb` 是**一次性二分排错脚本**
#   （`head86.rb`/`head132.rb`/`partD.rb` 各带一份 `%w[...]` 类名表），不是发给 SU 的枚举，
#   也不被任何步骤调用。它们留在盘上是为了能复现当时那次二分，所以按 scratch 跳过，
#   而不是登记成第八/第九个必须与标准全等的位。
SKIP_PARTS = ("_archive", "__pycache__", "_scratch", "_bisect")

#: ⑤ 三份**真出过这个毛病**的旧件 + 它们被点到名时**应缺**的类
# ★★ 2026-10-19：标准加了 `ROOF_ROOM`（第 12 类）之后，这三份**旧件**里也都没有它
#   —— 正对照的「应缺」名单必须跟着标准走，否则会读出「多缺一个」判红，
#   而红的原因是**期望值没跟上**，不是件变坏了（铁律 018/174）。
OBJ_CTL = (
    ("rebuild/模型库/坏_没有门头墙.obj", ("LINTEL", "ROOF_STAIR"),
     "模型库三个坏件之一：`LINTEL` 被整类删掉（旧件同样没有 ROOF_ROOM）"),
    ("rebuild/06_su/_archive/su_before_doorfix_20261015/c006_su.obj",
     ("LINTEL", "ROOF", "ROOF_ROOM"),
     "换门头墙之前那趟留下的正式件"),
    ("rebuild/_archive/06_su-c006-before-stairmodule-20261014/c006_su.obj",
     ("LINTEL", "ROOF", "ROOF_ROOM"),
     "换楼梯模块之前那趟留下的正式件"),
)

BLIND = [
    "登记位是手写的七处；**新出现**一处硬编码类名表，② 看不见（只有只报不判的 ⑥ 与读日志的人看得见）",
    "⑥ 只认「同一行 ≥4 个类名」；拆成多行就扫不到 ⇒「没报未登记位」推不出「没有未登记位」",
    "② 只比集合，不比语义；类名写成不可解析的形状 ⇒ 该处按「没量到」报 rc=4",
    "③ 只判「有没有到」，不判「到得对不对」（块数/位置/形状归 J-10.8-02 与构件库三条）",
    "`STD` 是人写的唯一一份标准；本判据不证明这 12 类是对的，只证明各处与它一致",
    "③ 的期望集取自**轮廓件自己**（`index.json::per_layer` 计数>0）；若轮廓生成器整类漏发，"
    "这一条看不见（A1/A2 与标准三向比对能看见「类不在」，看不见「类在但 0 条」）",
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


def finish(rc, out, readings, rep=None):
    p = json_path(out)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # ★ 三态（铁律 199）：rc==4 是「没量到」⇒ pass=None，不许写成 False。
    pass_ = None if rc == 4 else (rc == 0)
    # ★ 2026-10-19：items 只从跑器来（一个估计器，铁律 174）。
    #   ⑥ 在 `_verdict.SKIP_RULES` 里本来就是 skip 规则 ⇒ 它的 ✓ 折成 skip（只报不判）。
    items = []
    for it in (rep.items if rep is not None else []):
        x = dict(it)
        if x["status"] == "pass" and VD.is_skip("J-10.9-07", x["rule"]):
            x["status"] = "skip"
        items.append(x)
    readings = dict(readings)
    readings["items"] = items
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"pass": pass_, "rc": rc, **readings, "blind": BLIND},
                  fh, ensure_ascii=False, indent=1)
    log("  rc=%d" % rc)
    log("  写出: %s" % p)
    write(out)
    # ★ 2026-10-19：统一出口（矩阵只读这一份）。
    VD.emit("J-10.9-07", BID, pass_, rc, _LOG, blind=BLIND,
            files={"build_json": BUILD, "index": CONT_IDX, "deliver": OBJ},
            extra={k: v for k, v in readings.items()
                   if not k.startswith("_") and k != "items"},
            items=items)
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
CLASS_ALIASES = {
    "ROOF_PODIUM": "ROOF",
    "PARAPET_PODIUM": "PARAPET",
    "ROOFPLAN_ROOF": "ROOF",
    "PARAPET_ROOFPLAN": "PARAPET",
    # build3d 的 n_roof_stair 与 export_contours 的 ROOF_ROOM 是同一批屋面附属用房。
    "ROOF_STAIR": "ROOF_ROOM",
}


def canon_class(name):
    cls = str(name or "").upper()
    return CLASS_ALIASES.get(cls, cls)


def attach_classes(keys):
    """`attach` 的键 → 类名，机械还原（不手打表）。

    `n_parapet`→PARAPET · `parapet_m`→PARAPET · `roof_step7_m2`→ROOF_STEP
    """
    out = set()
    for k, v in keys.items():
        if isinstance(v, (int, float)) and v <= 0:
            continue
        s = re.sub(r"^n_", "", k)
        s = re.sub(r"_m2?$", "", s)
        s = re.sub(r"\d+$", "", s)
        out.add(canon_class(s))
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
        a1 |= {canon_class(k) for k in f.get("z_by_class", {})}
    att = attach_classes(b.get("attach", {}))
    a1 |= att
    with io.open(pc, "r", encoding="utf-8") as fh:
        idx = json.load(fh)
    a2 = set()
    a2c = collections.Counter()          # ★ 2026-10-19：逐类**条数**（③ 判「该不该到件」用）
    rows = idx if isinstance(idx, list) else idx.get("floors", [])
    for r in rows:
        for k, v in (r.get("per_layer", {}) or {}).items():
            n = int(v or 0)
            if n > 0:
                a2.add(canon_class(k))
                a2c[canon_class(k)] += n
    return a1, a2, {"n_floors_build": len(b.get("floors", [])), "attach": sorted(att),
                    "n_rows_contours": len(rows), "a2_counts": dict(a2c)}


# ----------------------------------------------------------------- ③ 实到（交付件）
# ★ 2026-10-20：OBJ 分组行有两种写法 —— SU 的 `g Mesh41 G_1__WALL Model`
#   与 FreeCAD 那条交付链的 `o floor0__WALL`。模型库的好件 2026-10-20 已跟交付件换成
#   `c006_fc.obj`（`o` 写法），三个坏件由它派生 ⇒ 只认 `g` 时 ⑤ 正对照读出
#   「12 类全缺」，判词看着像「坏件坏了」，其实是**尺子对它认不出的形状静默**
#   （铁律 158/196）。两边都认，才算量的是同一件事。
_RE_G = re.compile(r"^(?:g|o)\s")
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
            # ★ 2026-10-17 块级隔离（每块一个组）后，同一 (层,类) 有几百个**同名**组，
            #   SU 导出时给重名追加流水号 ⇒ `G_1__WALL88`。流水号不是类名，
            #   只有「去掉尾部数字后正好命中标准类」才剥（标准类里没有数字结尾的）。
            if tok is not None and tok not in STDS:
                base = tok.rstrip("0123456789")
                if base in STDS:
                    tok = base
            c[tok if tok in STDS else "(未认出的组名)"] += 1
    return n, c


def missing_in(roster):
    return sorted(c for c in STD if roster.get(c, 0) <= 0)


def model_lib_expect():
    """模型库坏件的「应缺」= **好件现读**缺的类 ∪ {`LINTEL`}。→ `(集合, None)` 或 `(None, 原因)`

    ★ 2026-10-20：好件 2026-10-20 已跟交付件走，从 SU 的 `c006_su.obj` 换成 FreeCAD 的
      `c006_fc.obj`（`o` 写法）。旧登记值 `("LINTEL","ROOF_ROOM")` 是给 SU 那件写的 ——
      主语换了、期望值逐字不变，就成了「拿旧主语的期望读新主语」（铁律 196）；
      实测新坏件缺的是 `ROOF_STAIR`（fc 件本来就没有它），旧期望里没有 ⇒ 恒红。
      期望值只能从**好件自己**算（铁律 103/187），不许手打。
    """
    lib = rp("rebuild/模型库/件.json")
    try:
        with io.open(lib, "r", encoding="utf-8") as fh:
            good = json.load(fh)["好件"]["path"]
    except Exception as e:                                          # noqa: BLE001
        return None, "模型库 `件.json` 读不动：%s" % e
    _n, r = obj_roster(rp(good))
    if r is None:
        return None, "模型库好件不在：%s" % good
    return (frozenset(missing_in(r)) | {"LINTEL"}), None


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


# ----------------------------------------------------------------- 判据清单（一条一个函数）
_GATE = "J-10.9-07"
_CTX = {}      # 只取一次的原始读数（上游两个生成器的账）
_RD = {}       # 落进 JSON 的读数


def _upstream():
    """① 的原始读数，只取一次（③ 的期望集也用它）。文件不在 ⇒ 没量到。"""
    if "a1" in _CTX:
        return _CTX["a1"], _CTX["a2"], _CTX["meta"]
    if "up_missing" in _CTX:
        raise I.没量到(_CTX["up_missing"])
    a1, a2, meta = derive_upstream()
    if a1 is None:
        why = "%s / %s 至少有一样不在（%s）" % (BUILD, CONT_IDX, meta)
        log("★ 没量到：%s" % why)
        _CTX["up_missing"] = why
        raise I.没量到(why)
    _CTX.update(a1=a1, a2=a2, meta=meta)
    return a1, a2, meta


def c1_上游():
    a1, a2, meta = _upstream()
    bad = []
    _RD["A1_build"], _RD["A2_contours"] = sorted(a1), sorted(a2)
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
    if a1 - STDS:
        bad.append("① 上游出现标准外的类：%s（标准没跟着长）" % sorted(a1 - STDS))
        log("   ✗ 上游出现标准外的类：%s" % sorted(a1 - STDS))
    else:
        log("   ✔ 上游类集 ⊆ 标准（本楼不必 12 类全有）")
    _RD.setdefault("_bad", []).extend(bad)
    return I.结果(not bad, "A1 %d 类 / A2 %d 类" % (len(a1), len(a2)),
                  "；".join(bad) if bad else "A1 = A2，且无标准外类（标准 %d 类）" % len(STD),
                  参数=[
                      I.参数("A1 build.json 类集",
                             "= A2（%d 类）且 ⊆ STD（%d 类：%s）"
                             % (len(a2), len(STDS), " ".join(STD)),
                             "%s::floors[].z_by_class 键 ∪ attach 键机械还原" % BUILD,
                             " ".join(sorted(a1)),
                             "补 build3d.py 漏落的 z_by_class / attach 键，再重跑本闸"),
                      I.参数("A2 contours 类集",
                             "= A1（%d 类）且只数 count>0 的类（STD %d 类：%s）"
                             % (len(a1), len(STDS), " ".join(STD)),
                             "%s::逐层 per_layer 键并集" % CONT_IDX,
                             " ".join(sorted(a2)),
                             "补 export_contours.py 漏发的类，再重跑本闸"),
                      I.参数("标准 STD", "%d 类；A1/A2 只需是其子集：%s" % (len(STD), " ".join(STD)),
                             "本判据 STD（唯一一份）·须与 rebuild/构件清单.md §7.2 同步",
                             "标准外 %s" % sorted(a1 - STDS),
                             "加类时同改 STD 与 rebuild/构件清单.md §7.2，再重跑本闸"),
                  ])


def c2_登记位():
    bad, un = [], []
    log("② 登记位逐个点名解析（full = 必须恰好相等；subset = 只许是标准的一部分）")
    log("   %-4s %-46s %-6s %s" % ("位", "处", "读到", "判"))
    src_cache, ctl_bad, ctl_n = {}, 0, 0
    site_tok = {}
    for num, name, rel, marker, op, cl, kind in SITES:
        if rel not in src_cache:
            src_cache[rel] = read_text(rel) if os.path.exists(rp(rel)) else None
        src = src_cache[rel]
        if src is None:
            un.append("%s %s：源文件不在" % (num, rel))
            log("   %-4s %-46s %-6s ★ 没量到（源文件不在）" % (num, name, "—"))
            continue
        t, blk = parse_site(src, marker, op, cl)
        if not t:
            un.append("%s %s：起始标记 %r 取不到类名" % (num, rel, marker))
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
    _RD["site_tokens"] = site_tok
    _RD["control_parser"] = {"n": ctl_n, "bad": ctl_bad}
    _RD.setdefault("_bad", []).extend(bad)
    if un:
        _RD.setdefault("_unmeasured", []).extend(un)
        raise I.没量到("；".join(un))
    return I.结果(not bad, "%d 处 / 正对照 %d 条" % (len(site_tok), ctl_n),
                  "；".join(bad) if bad else
                  "登记位全部与标准一致（④ 正对照 %d/%d）" % (ctl_n - ctl_bad, ctl_n),
                  参数=[
                      I.参数("登记位类名集（full）",
                             "恰好 = STD（%d 类：%s）" % (len(STDS), " ".join(STD)),
                             "SITES 登记的源文件枚举块：%s"
                             % "、".join(sorted({s[2] for s in SITES})),
                             " ".join("%s:%d" % (k, len(v)) for k, v in sorted(site_tok.items())),
                             "把缺/多的那一处类名表补齐到 STD（源文件见 SITES[2]），再重跑本闸"),
                      I.参数("子集位（⑤ ATTACH）",
                             "⊆ STD（%d 类）" % len(STDS),
                             "gates/J-10.8-02_su.py::ATTACH（SITES 中 kind=subset 的位）",
                             " ".join(site_tok.get("⑤", [])) or "（没量到）",
                             "ATTACH 里混进 STD 之外的类 ⇒ 改 J-10.8-02_su.py::ATTACH，再重跑本闸"),
                      I.参数("④ 解析器正对照",
                             "%d 条逐类整词删除后必须全部报缺" % ctl_n,
                             "SITES 各源文件的枚举块原文（strip_token 后同一把 tokens() 重解析）",
                             "%d 条未报缺" % ctl_bad,
                             "查 tokens() 的引号/键/%w 三条正则能否区分该处写法，修好再重跑本闸"),
                  ])


def c3_实到():
    _a1, _a2, meta = _upstream()
    bad, un = [], []
    log("③ 实到：交付件 `%s` 的 `g`/`o` 组名里，**轮廓里至少发过 1 条**的类每一类都要有 ≥1 组" % OBJ)
    n_g, roster = obj_roster(rp(OBJ))
    _skip = []                       # 件不在时下面的结果行也要读得到（不是「全到件」）
    if n_g is None:
        un.append("③ 交付件不在：%s" % OBJ)
        log("   ★ 没量到：件不在")
    else:
        # ★★ 2026-10-19：原口径「标准里每一类都必须 ≥1 组」对**按楼栋开关**才出的类
        #   （`ROOF_ROOM`：只有档案 `roof_stair:true` 的楼才有）**恒红** —— 判词会把
        #   「这栋本来就没有这件」报成「枚举里有它却没人发出去」。
        #   ⇒ 期望集改成**轮廓件自己发过 ≥1 条**的那几类（独立读数，不是手打名单）；
        #     轮廓 0 条的类不要求到件，但**要印出来**（不静默）。
        _a2c = meta.get("a2_counts", {}) if meta else {}
        _want = [c for c in STD if int(_a2c.get(c, 0) or 0) > 0]
        _skip = [c for c in STD if int(_a2c.get(c, 0) or 0) <= 0]
        miss = sorted(c for c in _want if roster.get(c, 0) <= 0)
        if _skip:
            log("   · 轮廓 0 条、本楼不要求到件：%s" % " ".join(_skip))
        log("   g 行 %d；逐类 = %s"
            % (n_g, " ".join("%s%d" % (k, roster.get(k, 0)) for k in STD)))
        unk = roster.get("(未认出的组名)", 0)
        _RD["obj"] = {"n_g": n_g, "by_class": {k: roster.get(k, 0) for k in STD},
                      "unknown": unk, "missing": miss}
        # ★ 2026-10-19：其余 65 栋没有 `_su.obj`，交付件退回 FreeCAD 出件（`_fc.obj`）。
        #   实测 `rebuild/c001/06_su/c001_fc.obj` 里 `^g ` **0 条** ⇒ 这把按组名数类的
        #   尺子对它**全盲**。「一块都没到件」这时是尺子的否定，不是件的缺陷
        #   （铁律 158：否定判词必须先声明量具对哪几类元素不盲）⇒ 只许报没量到。
        if n_g == 0:
            un.append("③ 交付件 `%s` 里 `g` 组行 0 条 —— 本尺子按组名数类，"
                      "对无组出件全盲（不是件缺类）" % os.path.basename(OBJ))
            log("   ★ 没量到：件里 `g` 组 0 条（%s），按组名的尺子对它全盲"
                % os.path.basename(OBJ))
        else:
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
            if rel.startswith("rebuild/模型库/"):
                # 这件的**故意刺激**只有一个：整类删掉 LINTEL。
                # 它和当前好件之间还会有代际差（例如 ROOF_STAIR/ROOF_STEP），
                # 不把那些代际差冒充成“本次应缺”。
                expect = ("LINTEL",)
            _n2, r2 = obj_roster(p)
            got = tuple(missing_in(r2))
            # 正对照只要求“该缺的类确实被点名”；旧件还可能因为代际差异多缺几类，
            # 多缺不削弱这把尺子的分辨力。
            hit = set(expect).issubset(set(got))
            log("     %s %-58s 读出缺 %s（至少要缺 %s）"
                % ("✔" if hit else "✘", rel, list(got), sorted(expect)))
            if not hit:
                bad.append("⑤ 正对照 %s 读出缺 %s，要的是 %s" % (rel, list(got), sorted(expect)))
            _RD.setdefault("control_obj", []).append(
                {"piece": rel, "why": why, "got": list(got), "want": sorted(expect)})
    _RD.setdefault("_bad", []).extend(bad)
    if un:
        _RD.setdefault("_unmeasured", []).extend(un)
        raise I.没量到("；".join(un))
    return I.结果(not bad, "g/o 行 %d ／ 缺 %s" % (n_g, miss or "无"),
                  "；".join(bad) if bad else
                  ("没量到：%s" % "；".join(un)) if un else
                  "%d 类全部到件（%d 类不要求：轮廓 0 条）" % (len(STD), len(_skip)),
                  参数=[
                      I.参数("到件期望集",
                             "轮廓 per_layer 计数 >0 的类：%s（%d 类）"
                             % (" ".join(_want), len(_want)),
                             "%s::逐层 per_layer 条数" % CONT_IDX,
                             "缺 %s／0 条不要求到件 %s"
                             % (miss or "无", " ".join(_skip) or "无"),
                             "补 export_contours.py::_attach_recs 漏发的类，再重跑本闸"),
                      I.参数("交付件组名",
                             "期望 %d 类每类 ≥1 个 `g` 组" % len(_want),
                             "%s::`g` 行的 `__<类名>`" % OBJ,
                             "g 行 %d；%s"
                             % (n_g, " ".join("%s%d" % (k, roster.get(k, 0)) for k in STD)),
                             "让 SU 那站按 BATCHES 建组并导出该类的块，再重跑本闸"),
                      I.参数("⑤ 正对照旧件",
                             " ".join("%s→%s" % (os.path.basename(rel), " ".join(expect))
                                      for rel, expect, _why in OBJ_CTL),
                             "OBJ_CTL 三份历史件：%s"
                             % "、".join(rel for rel, _e, _w in OBJ_CTL),
                             "；".join("%s→缺 %s"
                                      % (os.path.basename(x["piece"]), " ".join(x["got"]))
                                      for x in _RD.get("control_obj", []))
                             or "（三份旧件都不在，已跳过）",
                             "旧件缺的类要与 OBJ_CTL 一致；不一致时查 obj_roster 的组名解析"
                             "或更正 OBJ_CTL 期望，再重跑本闸"),
                  ])


def c6_未登记位():
    log("⑥ 未登记位扫描（⚠ **只报不判**，不改退出码；理由见文件头盲区）")
    un = scan_sites()
    _RD["unregistered"] = [{"file": f, "line": i, "n": k} for f, i, k in un]
    if un:
        for f, i, k in un:
            log("   ⚠ %s:%d（%d 个类名）" % (f, i, k))
        log("   ⚠ 共 %d 行命中且不在登记位/白名单里 —— 请人判：是类枚举就该登记，"
            "不是就进白名单" % len(un))
    else:
        log("   （没有未登记的命中）")
    return I.结果(True, "%d 行" % len(un),
                  "只报不判：%d 行未登记命中（不改退出码）" % len(un),
                  参数=[
                      I.参数("扫描范围",
                             "%d 个目录 × %s" % (len(SCAN_DIRS), " ".join(SCAN_EXT)),
                             "scan_sites()::SCAN_DIRS / SCAN_EXT（跳过 %s）" % " ".join(SKIP_PARTS),
                             "未登记命中 %d 行" % len(un),
                             "是类枚举就登记进 SITES，不是就写进 NOT_ENUM 并写明理由"),
                      I.参数("命中阈值",
                             "同一行 ≥4 个标准类名（scan_sites 内的硬阈值）",
                             "_RE_ANY ∩ STD（%d 类）" % len(STDS),
                             "命中 %d 行" % len(un),
                             "拆成多行的类表本条扫不到；命中清单要人读，不能据此断定没有未登记位"),
                      I.参数("登记位 / 白名单",
                             "SITES %d 处 + NOT_ENUM %d 项" % (len(SITES), len(NOT_ENUM)),
                             "本判据 SITES / NOT_ENUM（⑥ 的排除名单来源）",
                             "未登记命中 %d 行" % len(un),
                             "新增登记位改 SITES；判为散文/子集的写进 NOT_ENUM（理由不许空着）"),
                  ])


CHECKS = [
    ("①", "上游分类集（两处独立生成）", c1_上游),
    ("②", "登记位逐个点名解析（含④正对照）", c2_登记位),
    ("③", "实到交付件（含⑤正对照）", c3_实到),
    ("⑥", "未登记位扫描（只报不判）", c6_未登记位),
]


# ----------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="J-10.9-07 构件类名闭合")
    ap.add_argument("--out", default=None, help="判词落盘路径（默认按楼栋名分文件）")
    # ★ 2026-10-19：`--bid` 由 `_verdict.bid_from()` 在模块级已经读过（路径已按它算好），
    #   这里收下只是为了不让严格 argparse 把矩阵跑挂。
    ap.add_argument("--bid", default=BID, help="楼栋 id（默认取 CDUT_BUILDING 或 c006）")
    a = ap.parse_args(argv)
    # ★ 2026-10-19：老默认 `_out/J-10.9-07.txt` 是**全校共用一份** ⇒ 矩阵一跑 67 栋，
    #   c001 的读数会把 c006 那份覆盖掉（「第二个楼的读数账会覆盖第一栋的」原样复发）。
    #   c006 保留老文件名（文档/脚本还指着它），其余楼一律 `<闸>.<楼>.txt`。
    if not a.out:
        a.out = OUT if BID == "c006" else os.path.join(OUTD, "J-10.9-07.%s.txt" % BID)

    _LOG.clear()
    _CTX.clear()
    _RD.clear()
    _RD["_bad"] = []
    _RD["_unmeasured"] = []

    log("=" * 78)
    log("J-10.9-07 构件**类名闭合**：七处枚举是否都知道同一批类，且它们真的到得了件")
    log("标准 STD（人写的唯一一份，%d 类）：%s" % (len(STD), " ".join(STD)))
    log("-" * 78)

    rep = I.跑(_GATE, CHECKS, log=log, 宽=34)
    rc = rep.rc

    rd = dict(_RD)
    rd["standard"] = list(STD)
    if rep.rc != 4:
        rd["n_violations"] = len(_RD.get("_bad") or [])
    else:
        rd["unmeasured"] = list(_RD.get("_unmeasured") or [])
    return finish(rc, a.out, rd, rep=rep)


if __name__ == "__main__":
    sys.exit(main())
