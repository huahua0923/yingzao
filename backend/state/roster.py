# -*- coding: utf-8 -*-
"""判据名册 —— 全仓有哪些「判据类」文件，谁登记过、谁必须收编。

**为什么需要它。** 没有一条判据能回答「还有哪些判据没人知道」。具体到本仓，
这个问题有一个立刻要用的形态：`_scratch/` 里上千项中间产物中**哪几个其实是
系统件、必须收编**。这件事此前靠人眼看，而人眼会漏。

产出：`data/_meta/criteria_roster.json`（判据 C3 读它）。

用法：
    python -u backend/state/roster.py             扫描并落盘
    python -u backend/state/roster.py --print     只打印，不写
    python -u backend/state/roster.py --selftest  刑具（证明这把尺子会红）

## ★ 两个坑，都是本文件自己踩过才改的，别改回去

**① 候选不能按文件名筛。** 第一版按 `check|gate|audit|verify|…` 筛，
   结果 `_scratch/_import_graph_gap.py`（一条真门禁）**一个关键词都不沾，
   静默从名册里消失** —— 名册看着完整，缺的那个不会喊。
   ⇒ 改成**正向形状匹配**：只按**位置 + 后缀**认（`_scratch` 下的 .py/.md、
   仓库根的 `_*.py`/`qa_*.py`）。枚举「我不要什么」永远追不上命名习惯。

**② 引用必须解析 AST，不能 grep。** 第二版用 `文件名 in 文件字节` 判引用，
   于是**注释和文档串里那句「实测见 `_scratch/_a0_jog_census.py`」被算成一条引用**，
   一次性探针被报成「必须收编」（42 个，真值两位数都不到），
   而且配了句**假话**：「搬走会让那些引用静默失效」——
   对一条注释而言搬走只是注记指空，**不打断任何调用**。
   ⇒ 代码引用与散文提及**分成两档**，代码档走 `ast`（memory:
   substring-count-is-not-code-fact 记着同一族坑）。

**③ 元工具自己不许当引用者，且这把尺子有已知盲区。** 第二版还有一个自伤：
   本文件刑具里的夹具串 `want = "_scratch/_import_graph_gap.py"` 被算成「代码引用」，
   于是把一个**从未被调用过**的文件报成「搬走会让那些调用静默失效」。
   ⇒ 索引时跳过本文件自己（`SELF_REL`）。
   ⇒ 更要紧的是它暴露了尺子的**真实边界**：按名引用只看得见「代码里提到过」，
     **看不见「hook 按路径调」或「人照文档跑」**。本仓真有这样的东西（门禁）。
     所以配一份**人手登记** `PINNED`（带理由、宁少不多）补这个盲区 ——
     与归档三闸的第③闸（明令不碰清单）是同一样东西，只是这里变成机器可读的。
   ⇒ 由此，`一次性探针` 的准确含义是「**代码里没人按名引用它**」，
     **不是**「没人用它」。输出里必须这么写，否则下一个人会照它删东西。

**④ 引用不止「字符串字面量」一种写法 —— 漏掉的是最常见的那种。** 第三版代码档
   只搜字符串常量（`ast.Constant`），于是 `qa_defect_census.py:67` 的
   `import _defect_census as C` **一条都搜不到** —— 那行里根本没有
   `_defect_census.py` 这个字符串。后果：`_scratch/_defect_census.py` 被判成
   「一次性探针」（= 可以随 `_scratch` 搬走），而真搬走，根门禁
   `qa_defect_census.py` 会在 import 行**当场炸**。
   ⇒ **少报的方向恰好是最危险的方向** —— 它让「搬了就断」看起来像「可以搬」。
   ⇒ 而它的自检夹具**只摆了字符串字面量这一种形态**，所以这条坏法在整个自检里
     是隐形的（memory: fixture-shape-must-copy-real-artifact）。
   ⇒ 出路：引用提取与**解析**整个搬去 `backend/state/references.py`（一个文件一件事）。
     那里按 import 的形态（裸名 / 点路径 / 相对）算出它到底指哪个文件：
     裸名按本仓实测的 sys.path 次序找；点路径与相对路径直接算；
     算不出、且末段与某候选重名的，进 `unresolved` —— 并把处置从
     「一次性探针」降成「待拍板」（拿不准就不许说它可以搬）。

**⑤ 索引按**文件名**建键，同名候选会并成一条。** 旧版 `names = {p.name for p in
   cands}` 把路径压成文件名，两个同名候选共用一份 `code_refs`。
   ⇒ 索引一律按 **rel 路径**建键。

**⑥ 「候选自己不算引用自己」写成了「**候选之间**都不算引用者」（第四版，2026-09-24）。**
   建索引时那一行是 `if rel in cand_files or rel == SELF_REL: continue`，
   注释写的是「候选自己不算引用自己」—— **注释说「自己」，代码干的是「所有候选」**。
   于是**候选与候选之间的引用整段是瞎的**。
   ⇒ ④ 修完，`_scratch/_defect_census.py` 在全库扫描里**仍然**是「一次性探针」——
     因为它的引用者 `qa_defect_census.py` 本身就是候选（根 `qa_*.py`）。
     ④ 的自检夹具用的是 `qa_defect_census.py` 这个名字，但夹具里它**不在候选集里**，
     所以夹具过了、真库不过 —— **又是夹具与真产物不同形**（同 ④ 的教训，隔了一层）。
   ⇒ 出路：只跳过 `SELF_REL`；「自己引用自己」改在**命中时**排除（`h != rel`）。
   ⇒ 教训一句：**④ 是「少一种引用形态」，⑥ 是「少一类引用者」——
     同一句话（「谁引用了它」）的两半都不完整，而两次都由同一个夹具的疏漏放了过去。**
     修完第一半时**必须重跑真库**，否则「修好了」只是夹具说的。

**⑦ 已知量不到：`_scratch` **内部**的引用。** `SCAN_SKIP` 里有 `_scratch`，
   所以 `_scratch/A.py` 引用 `_scratch/B.py` 时本尺子看不见（`all_py` 也跳过它）。
   ⇒ 对「谁该收编」这个问题**通常不影响**：它们是一起搬走的，引用随树一起保留。
   ⇒ **例外是那 3 个被收编的文件**（留下、其余搬走）—— 反向引用者会断。
     2026-09-24 逐个 AST 查过 `_scratch`（去掉备份/作业目录），只有 **2 处**，
     且两处**都在要搬走的树里**：`_probe_band_ab.py:28` 的
     `from _area_audit import dxf_area_table`、`_area_audit_par.py:37` 起子进程
     `os.path.join("_scratch", "_area_audit.py")`。仓库内留下的引用者：无。
   ⇒ 所以收编不受影响；但**移出后的那份树里，这两处会断** —— 它们退休了，
     不是「搬坏了」。这件事要写进归档文档，别让下一个人以为是故障。
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from paths import ROOT  # noqa: E402
from state import references as _refs  # noqa: E402

#: ★ 手写。改了**扫描范围 / 分类规则 / 分档**就 +1。跟语义走，不跟行数走。
#: v2 = 2026-09-24 引用提取从「只搜字符串字面量」改成走 `references.py` 的解析
#:      （补上 import 一路；见文件头 ④）。**这条改了，名册的数就会变**，
#:      而变的方向是「红得更准」。
#:      v4（2026-09-24）：删掉「已登记」一档（它把注释当成引用，还排在真引用前面，
#:      把 `_scratch/_area_audit.py` 的真引用盖住了）。见 `_dispose` 的说明。
#: v5（2026-09-24）：`PINNED` 重写 —— 原来登记的 2 条已随 2a 收编进系统（收编后
#:      它们**在代码里查得到引用**，无需人手登记），空出来的位置换成 4 个**根目录散件**：
#:      `_glb_only.py`（README.md:233 明令要跑的生产命令）、`_freshness.py`（产物新鲜度
#:      门禁）、`_probe_doorbox_equiv.py` / `_test_curve_pair.py`（算法与流程总览.md:490,492
#:      记为单测）。四条均由**文档里的引用**证实，不是看名字猜的 ——
#:      原先把它们判成「待拍板」只是因为它们长得像探针。
#:      ⇒ 分档变化：待拍板 4 → 0，必须收编 16 → 20。
CRITERION_VERSION = 5

OUT = ROOT / "data" / "_meta" / "criteria_roster.json"
SCRATCH = ROOT / "_scratch"

#: 走索引时**不看**的目录：`_scratch` 是候选自己所在处（不自己引用自己），
#: `data` 是产物（引用它不算代码引用），其余是缓存/版本库。
SCAN_SKIP = {".git", "node_modules", "__pycache__", "_scratch", ".orig", "data", ".venv"}

#: `_scratch` 里的**产物目录**（不是代码）：备份、建模作业、老资料、影像。
#: 名字前缀匹配 —— 这些确实只有几种约定，且落在里面的东西一眼可知是产物。
SCRATCH_SKIP_PREFIX = ("_bak", "su_jobs", "legacy", "_imagery", "_c001_sheets")

#: 索引时按内容读的文本后缀。
TEXT_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".html", ".md", ".json",
            ".ps1", ".cmd", ".sh", ".txt", ".yml", ".yaml", ".toml")

#: 代码后缀（走 AST / 字符串字面量）；其余按散文算。
#: ★ `.js/.html` 这些**不 import**，只按路径字符串引用 `.py`，所以走字符串那一路。
CODE_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".html")

_JS_STR_RE = re.compile(r"""["'`]([^"'`\n]{0,240})["'`]""")

#: 本文件自己（相对仓库根）。**建索引时要跳过它。**
#: ★ 为什么：这是个**元工具** —— 它提到文件名是为了**分类**它们，不是**使用**它们。
#:   第一版没跳，于是它自己刑具里的夹具字符串
#:   `want = "_scratch/_import_graph_gap.py"` 被算成一条**代码引用**，
#:   把一个从未被调用过的文件报成「搬走会让那些调用静默失效」—— 又是一句假话。
#:   与跳过 `_scratch`（候选自己不引用自己）是同一条道理。
SELF_REL = "backend/state/roster.py"

#: ★★ 人手登记：**已知**在代码之外被使用的东西（hook / 定时任务 / 人按文档跑）。
#: 这是补这把尺子的**已知盲区**：按名引用只看得见"代码里提到过"，
#: 看不见"某个 hook 按路径调"或"人照文档跑"。本仓归档三闸的第③闸
#: （明令不碰清单）本来就是人写的，这里把它变成机器可读的一份。
#: ⚠ 条目必须**带理由**，且**宁少不多** —— 它是补盲区，不是给人开后门。
#:
#: ★ 2026-09-24 换了一批，三条都记在案：
#:   ① **原两条（`_scratch/_import_graph_gap.py`、`_scratch/README.md`）已收编进系统**
#:      （`backend/checks/_import_graph_gap.py`、`docs/归档三闸.md`），盲区本身消失了 ⇒ 撤登记。
#:      （`_scratch/` 里那两份成了退休副本，判成「一次性探针」是对的。）
#:   ② **原来判「待拍板」的那四个，逐个查完发现全是**真资产**，不是探针**：
#:      三个在文档里被**明令叫人跑**（`README.md:233` 是一条生产命令），
#:      一个自称门禁。⇒ 全部登记。**这是"人拍板"该有的产出** ——
#:      拍板不是让它继续躺着，是给它一个能引用的理由。
#:   ③ ⚠ 这个名单**曾经有第二份实现**：`_scratch/_archive_root.py` 的 `KEEP` 集合，
#:      判的正是同一件事（哪些根脚本留、哪些当一次性）。两份名单必然漂
#:      （memory: one-judgement-many-implementations）。那个脚本随 `_scratch/` 一起退休，
#:      此后**只认这一份**。
PINNED: dict[str, str] = {
    "_glb_only.py":
        "**文档里明令人跑的生产命令**：README.md:233 `python -u _glb_only.py <name>`"
        "（「出 GLB（不重跑 recognize）」）；另有 _scratch/_glb_rollout_singlemin.sh:11 调它",
    "_freshness.py":
        "**产物新鲜度门禁**（本文件 docstring 自述；只读、退出码给门禁用）——"
        "代码里无人 import，与 _import_graph_gap.py 同一类，不是探针",
    "_probe_doorbox_equiv.py":
        "**单测**：算法与流程总览.md:490 记「`_door_boxes` 等价性单测」—— 名字像 probe，实际是回归资产",
    "_test_curve_pair.py":
        "**单测**：算法与流程总览.md:492 记「弧配对单测」—— 同上，名字骗人",
}


def sha12(data: bytes) -> str:
    """「这是哪把尺子」的指纹规则 —— **全仓只有这一份**。

    ★ 为什么由**生产者**持有：C 层（`backend/checks/system.py`）要拿它比对，
      而比对规则若各写一份，长度改成 16 而校验那边没改，指纹永远对不上 ——
      C3 会天天报「名册是旧尺子量的」，而真因是两份规则不一致
      （memory: one-judgement-many-implementations）。
      名字不带下划线是有意的：**就是给别处用的**。
    """
    return hashlib.sha256(data).hexdigest()[:12]


def _sha12(path: Path) -> str:
    return sha12(path.read_bytes())


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


# ── 候选：按**位置 + 后缀**认，不按文件名 ──────────────────────────

def _candidates() -> list[Path]:
    """所有**可能是判据**的文件。

    ★ 正向形状匹配（见文件头 ①）：`_scratch` 下的 .py，加顶层一层的 .md
      （README 那种成文判据），加仓库根的 `_*.py` / `qa_*.py`。
      **不按文件名关键词筛** —— 那会让不沾关键词的真门禁静默消失。
    """
    out: list[Path] = []
    for p in sorted(ROOT.glob("*.py")):
        if p.name.startswith("_") or p.name.startswith("qa_"):
            out.append(p)
    if SCRATCH.is_dir():
        for dirpath, dirnames, filenames in os.walk(SCRATCH):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(SCRATCH_SKIP_PREFIX)]
            depth = len(Path(dirpath).relative_to(SCRATCH).parts)
            for fn in filenames:
                if fn.endswith(".py") or (fn.endswith(".md") and depth <= 1):
                    out.append(Path(dirpath) / fn)
    return out


# ── 代码引用的提取（AST / JS 字符串）────────────────────────────────

def _ref_index(cands: list[Path]):
    """走一遍仓库，一次性建出「谁被按名引用」的索引。

    ★ 必须**一趟建索引**，不许每个候选各走一遍仓库：候选上百个，
      逐个扫全仓是 O(候选 × 全仓)，慢到没法进门禁。
      而且一趟读一遍顺带保证各档用的是同一份读数。

    ★ 索引**按 rel 路径建键**（文件头 ⑤）：按文件名建键会把同名候选并成一条。
    ★ `.py` 走 `_refs.file_refs`（字符串路径 + import 解析两路齐上）；
      `.js/.html` 只有字符串一路（前端按路径字符串引用）；
      其余后缀一律按散文算。

    返回 (索引, 解析不动的文件清单)。
    索引形状：{候选 rel: {"code": [...], "prose": [...], "unres": [...]}}
    """
    def rel_of(p: Path) -> str:
        return str(p.relative_to(ROOT)).replace(os.sep, "/")

    cand_files = {rel_of(p) for p in cands}
    cand_by_name: dict[str, list[str]] = {}
    cand_by_stem: dict[str, list[str]] = {}
    for p in cands:
        cand_by_name.setdefault(p.name, []).append(rel_of(p))
        cand_by_stem.setdefault(p.stem, []).append(rel_of(p))

    # 解析要用「仓库里真有那些 .py」这份现实 —— 少了它，副本与真件分不开（见 references.py）
    all_py = _refs.repo_py_files(ROOT, SCAN_SKIP)
    idx = {rel: {"code": [], "imp": [], "prose": [], "unres": []} for rel in cand_files}
    unreadable: list[str] = []

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP]
        for fn in filenames:
            if not fn.endswith(TEXT_EXT):
                continue
            p = Path(dirpath) / fn
            try:
                rel = str(p.relative_to(ROOT)).replace(os.sep, "/")
            except ValueError:
                continue
            # ★ 只跳过**自己**，不跳过「别的候选」。
            #   原先写的是 `rel in cand_files or rel == SELF_REL`，注释却写「候选自己不算
            #   引用自己」—— 注释说「自己」，代码干的是「所有候选」，于是**候选之间的引用
            #   整个是瞎的**。实测代价：`_defect_census.py` 的引用者 `qa_defect_census.py`
            #   本身就是候选（根 `qa_*.py`）⇒ 那条 `import` 被跳过 ⇒ 名册仍判它「一次性
            #   探针」= 可以搬，而真搬走根门禁当场炸。**少报的方向恰好是最危险的方向。**
            #   自己引用自己仍要排除，但那是**命中时**的事（见下面 `h != rel`）。
            kind = ("py" if fn.endswith(".py")
                    else "js" if fn.endswith(CODE_EXT) else "text")
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                unreadable.append(rel)
                continue
            miss = _absorb(rel, txt, kind, idx, cand_by_name, cand_by_stem,
                           all_py, cand_files)
            if miss:
                unreadable.append(rel)
    return idx, unreadable


def _absorb(rel: str, txt: str, kind: str, idx: dict, by_name: dict,
            by_stem: dict, all_py: set[str], cand_files: set[str]) -> bool:
    """把**一份**文件里的引用吸收进索引。返回 True 表示「量不到这份」。

    ★ 抽出来是为了能只喂一份假文本就验到「谁算引用者」这条判断 ——
      原来它埋在扫全仓的循环里，而**它正是出过事的那一行**（见下）。
    ★ 跳过规则**只跳过 roster.py 自己**（`SELF_REL`）。
      原先写的是 `rel in cand_files or rel == SELF_REL`，注释却写「候选自己不算引用自己」
      —— 注释说「自己」，代码干的是「所有候选」，于是**候选之间的引用整个是瞎的**。
      实测代价：`_defect_census.py` 的引用者 `qa_defect_census.py` 本身就是候选
      （根 `qa_*.py`）⇒ 那条 `import` 被跳过 ⇒ 名册仍判它「一次性探针」= 可以搬，
      而真搬走，根门禁会在 import 行当场炸。**少报的方向恰好是最危险的方向。**
      ⇒ 自己引用自己仍要排除，但那是**命中时**的事（下面 `h != rel`），不是整份跳过。
    """
    if rel == SELF_REL:
        return False     # 元工具自己会扫到自己这份清单（见 SELF_REL）
    if kind == "py":
        got = _refs.file_refs(rel, txt, by_name, by_stem, all_py, cand_files)
        if got is None:
            return True
        imp = set(got.get("imported") or ())
        for h in got["hits"]:
            if h in idx and h != rel:            # 自己引用自己不算（文件里提自己的名）
                idx[h]["code"].append(rel)
                if h in imp:
                    idx[h]["imp"].append(rel)    # ★ 真 import：搬走必断
        for u in got["unresolved"]:
            for c_rel in by_stem.get(u.rsplit("/", 1)[-1], []):
                if c_rel != rel:
                    idx[c_rel]["unres"].append("%s -> %s" % (rel, u))
        return False
    if kind == "js":
        lits = [m.group(1) for m in _JS_STR_RE.finditer(txt)]
        for n, rels in by_name.items():
            if any(n in s for s in lits):
                for c_rel in rels:
                    if c_rel != rel:
                        idx[c_rel]["code"].append(rel)
        return False
    raw = txt.encode("utf-8")                    # .md / .json / .ps1 … 一律按散文
    for n, rels in by_name.items():
        if n.encode("utf-8") in raw:
            for c_rel in rels:
                if c_rel != rel:
                    idx[c_rel]["prose"].append(rel)
    return False


def _dispose(rel: str, name: str,
             code: list[str], prose: list[str],
             unres: list[str] | None = None,
             imp: list[str] | None = None) -> tuple[str, str]:
    """**纯函数**：给定读数，返回 (处置, 理由)。

    抽出来是为了让刑具④能只喂几个假读数就验到分支表 ——
    否则验一条 `if` 得先扫全仓（4 GB），那种刑具没人会跑，跑了也没人信。
    ★ 分支**有顺序**，顺序本身是判据：
      人手登记 > 代码引用 > **拿不准** > 探针。
    ★ `imp` = 其中**真走 import** 的那几处（`code` 的子集）。
      理由里必须分开报：import 命中是「搬走当场断」，字面量命中可能是调用参数、
      也可能只是一句给人看的文案（不断链，但会指向不存在的路径）。
      **本尺子分辨不了字面量的性质**（要数据流），所以不许在理由里写成「调用」。
    ★ `unres` = 有 import 可能指它、但解析不出归属（见 references.py）。
      这一档**必须挡在「一次性探针」前面** —— 探针的语义是「搬走不会断链」，
      而拿不准的时候我们没有资格说这句话。宁可让它变成「待拍板」多问一句。

    ★ 2026-09-24 删掉了原先排第二档的 **「已登记」**（判据引擎 `backend/checks/*.py`
      里**提到过**它就算数）。那一档是**文本事实冒充代码事实**：
      判据是「这个文件名出现在 `backend/checks/*.py` 的字节里」，
      于是我在 `sources.py` 里写一句注释「`_area_audit.py` 见 `_scratch/`」
      也算「已登记」—— 而注释不是调用（memory: substring-count-is-not-code-fact）。
      更坏的是**它排在「代码引用」前面**，把真引用盖住了：
      `_scratch/_area_audit.py` 明明被 `checks/sources.py` 的 `SCRIPT_REL` 和
      `api/services/area_audit.py` 真的按名引用，却先被这档接走 ⇒ 名册看上去
      「已登记，不必搬」，而 `_scratch/` 一移走它就连不上了。
      ⇒ 出路不是把这一档修准，是**整档删掉**：被引擎真的引用，就会走「代码引用」，
        处置同样落到「必须收编」；只剩散文提名的，本来就该老实待在「探针」里。
      ⚠ 删档后处置会变，`criterion_version` 随之 +1（铁律 24）。
    """
    in_scratch = rel.startswith("_scratch/")
    if rel in PINNED:
        return "必须收编", ("**人手登记**（代码里查不到引用 ⇒ 本尺子的已知盲区，"
                            "见文件头 ③）：%s" % PINNED[rel])
    if code:
        n_imp = len(imp or ())
        why = "被 %d 处**代码**按名引用（不是注释）：%s" % (len(code), "、".join(code[:3]))
        if n_imp:
            why += "；其中 **%d 处是 import**（搬走当场断链）" % n_imp
        if len(code) > n_imp:
            why += ("；其余 %d 处只是**字符串/注释里点了名** —— 那类搬走不断链，"
                    "但文案会指向一个不存在的路径（「注记指空」），得跟着改。"
                    "★ 字面量是调用参数还是纯文案，本尺子分辨不了。"
                    % (len(code) - n_imp))
        return "必须收编", why
    if unres:
        return "待拍板", ("有 %d 处 import **可能**指它、但解析不出归属 ⇒ "
                          "说不清它是不是被引用，就不许说它可以搬：%s"
                          % (len(unres), "、".join(unres[:3])))
    if in_scratch:
        why = ("`_scratch/` 以外没有**代码**按名引用它"
               "（≠ 没人用它：hook/人手不在此尺子量程内）")
        if prose:
            why += ("（只在 %d 处散文/文档里被提到：%s）"
                    % (len(prose), "、".join(prose[:2])))
        return "一次性探针", why
    # ★ 这里**必须给一个非空处置**。原先返回 `""`，而 main() 打印时又写成「待拍板」、
    #   分档时也把它并进「待拍板」—— 同一个事实两份写法：JSON 里读作「没有处置」，
    #   屏幕上读作「待拍板」。key 在 `disposition` 上的消费者拿到 `""`，
    #   多半当成「无」静默丢掉（memory: dual-representation-shadowed-control、
    #   template-string-prints-undefined 同族：**「不知道」不许长得像「没有」**）。
    return "待拍板", "在仓库根、也没有**代码**按名引用 —— 要人拍板"


def build() -> dict:
    cands = _candidates()
    idx, unreadable = _ref_index(cands)

    entries = []
    for p in cands:
        rel = str(p.relative_to(ROOT)).replace(os.sep, "/")
        in_scratch = rel.startswith("_scratch/")
        # ★ 数数要用**全量**、落盘才截断：把截断后的列表喂给 `_dispose`，
        #   理由里那句「被 N 处代码按名引用」就被 6 卡住了 ——
        #   20 处引用会印成「6 处」，而屏幕上完全看不出来（量程切掉了待检对象）。
        code, imp = idx[rel]["code"], idx[rel]["imp"]
        prose, unres = idx[rel]["prose"], idx[rel]["unres"]
        disp, why = _dispose(rel, p.name, code, prose, unres, imp)
        entries.append({
            "path": rel,
            "kind": "scratch" if in_scratch else "root",
            "disposition": disp,
            "why": why,
            "code_refs": code[:6],
            "import_refs": imp[:6],
            "prose_refs": prose[:6],
            "unresolved_refs": unres[:6],
        })
    return {"entries": entries, "unreadable_files": unreadable}


# ── 刑具：证明这把尺子**会红** ─────────────────────────────────────

def selftest() -> int:
    """已知答案，有红有绿。绿灯不值钱，能红才值钱。"""
    checks: list[tuple[str, bool, str]] = []

    # ① 文档串里的文件名 **不许**被算成代码引用（这正是我犯过的错）
    lits = _refs.str_literals(ast.parse('"""实测见 `_scratch/_a0_jog_census.py`。"""'
                                        '\nimport os\n'))
    hit = any("_a0_jog_census.py" in s for s in lits)
    checks.append(("① 文档串里的文件名不算代码引用", not hit,
                   "取到的代码字符串 = %r" % (lits,)))

    # ② 真调用里的文件名 **必须**被算成代码引用（回归：别把旧能力弄丢）
    lits = _refs.str_literals(ast.parse(
        'import os,subprocess\nP=os.path.join("_scratch","_defect_census.py")\n'))
    hit = any("_defect_census.py" in s for s in lits)
    checks.append(("② os.path.join 里的文件名算代码引用", hit,
                   "取到的代码字符串 = %r" % (lits,)))

    # ③ 候选**不许**按文件名筛：判据是「按位置+后缀的形状」，不是「名字里有没有关键词」。
    #    ★ 这一条原来钉在一个**具体文件**上（`_scratch/_import_graph_gap.py`），
    #      而那个文件 2026-09-24 被收编进 `backend/checks/` 了 —— 钉具体路径的判据
    #      会在文件搬走时**变成一句空话**（它恰好在 `_scratch/` 移出后无从验证）。
    #      改成钉**形状规则**本身：磁盘上有多少符合条件的，名册里就得有多少，
    #      两边逐项对齐。这样 `_scratch/` 整个移出后它依然在量同一件事。
    #    ⚠ 底下的走盘**是有意抄一份的**（不是忘了 DRY）：它的用处正是「独立重述一遍
    #      规则」，好让 `_candidates()` 改形状时这里当场红。合成一个函数就叫它闭嘴了。
    rels = {str(p.relative_to(ROOT)).replace(os.sep, "/") for p in _candidates()}
    want: set[str] = {str(p.relative_to(ROOT)).replace(os.sep, "/")
                      for p in ROOT.glob("*.py")
                      if p.name.startswith("_") or p.name.startswith("qa_")}
    if SCRATCH.is_dir():
        for dirpath, dirnames, filenames in os.walk(SCRATCH):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(SCRATCH_SKIP_PREFIX)]
            depth = len(Path(dirpath).relative_to(SCRATCH).parts)
            for fn in filenames:
                if fn.endswith(".py") or (fn.endswith(".md") and depth <= 1):
                    want.add(str((Path(dirpath) / fn).relative_to(ROOT))
                             .replace(os.sep, "/"))
    checks.append(("③ 候选是「位置的形状」，磁盘上有多少名册里就得有多少",
                   rels == want,
                   "漏 %r；多 %r" % (sorted(want - rels)[:3], sorted(rels - want)[:3])))

    # ④ 人手登记的必须落到「必须收编」—— 它的全部意义就是补「代码里查不到」这个盲区，
    #    所以**代码引用为空**时更必须成立。把分支顺序写反（先判 code）⇒ 这条红。
    #    ★ 样本取 PINNED 的**第一条**，而 PINNED 里四条**全是**代码零引用的根文件
    #      （`_glb_only.py` 等）：样本若换成有引用的，这条会被 "代码引用" 那半段
    #      替它过，等于没测到 PINNED 这一档。
    pin_rel = next((r for r, _ in PINNED.items()), "")
    disp, _why = _dispose(pin_rel, os.path.basename(pin_rel), [], [])
    checks.append(("④ 人手登记的必须收编（代码零引用时更是）", disp == "必须收编",
                   "样本 %r 得到 %r（PINNED 里有 %d 条）"
                   % (pin_rel, disp, len(PINNED))))

    # ⑤ 阴性对照：同样零引用、但**不在** PINNED 的探针 **不许**也变成「必须收编」
    #    —— 没有这条，④ 可能只是「凡零引用皆收编」这条更粗的规则在替它过。
    disp2, why2 = _dispose("_scratch/_fake_probe_xyz.py", "_fake_probe_xyz.py",
                           [], [])
    hit = "静默失效" in why2
    checks.append(("⑤ 阴性对照：未登记的零引用探针不许被收编",
                   disp2 == "一次性探针" and not hit,
                   # ★ 这句话必须**两个方向都念得通**：第一版写死成「理由里出现…」，
                   #   跑绿时它也在报假话（与 template-string-prints-undefined 同族：
                   #   定死的串不反映当下状态）。
                   "得到 %r；理由里%s「静默失效」那句假话"
                   % (disp2, "★有" if hit else "没有")))

    # ── ⑥…⑫ 夹具世界：照**真产物**的形状摆 ────────────────────────
    # ★ 这些形状一条都不能少 —— 上一版夹具只摆了字符串字面量，
    #   于是 import 那一路坏掉时整个自检是绿的（见文件头 ④）。
    #   每个用例后面括注的都是本仓**真实**的那一处。
    fix_cand = {
        "_scratch/_defect_census.py",              # 真例：被根门禁 import
        "qa_defect_census.py",                     # ★ 真例：**它自己也是候选**（根 qa_*.py）
        "_scratch/_head_glb/glb_common.py",        # 真例：backend/modeling/ 那份的副本
        "_scratch/_backup_x/outline.py",           # 真例：backend/recognizer/ 那份的副本
        "_scratch/_newfix/classify_line.py",       # 真例：与 backend 那份同 stem，撞车来源
        "_scratch/weird/geometry.py",              # 构造：同名但解析不到 → unresolved
        "_render_common.py",                       # 真例：裸名 + 调用方就在仓库根
        "_scratch/_fake_probe_xyz.py",             # 阴性对照
    }
    fix_all = fix_cand | {
        "backend/modeling/glb_common.py",          # 解析要认得这些**非候选**的真件
        "backend/recognizer/outline.py",
        "backend/recognizer/classify_line.py",     # ★ 真例：末段与候选同名，但它是**属性**
        "_scratch/_newfix/shim.py",                # 让 `_newfix` 成为本仓可导入的顶层名
    }
    by_name: dict[str, list[str]] = {}
    by_stem: dict[str, list[str]] = {}
    for r in fix_cand:
        b = os.path.basename(r)
        by_name.setdefault(b, []).append(r)
        by_stem.setdefault(b[:-3], []).append(r)

    def refs(importer, text):
        return _refs.file_refs(importer, text, by_name, by_stem, fix_all, fix_cand)

    cases = [
        ("⑥ 裸名 import 走 _scratch（④ 漏掉的那个真例）",
         refs("qa_defect_census.py", "import _defect_census as C\n"),
         ["_scratch/_defect_census.py"]),
        ("⑦ 裸名 import 先找调用方自己目录（同目录真件胜副本）",
         refs("backend/modeling/su_spec.py", "from glb_common import MeshBuilder\n"),
         []),
        ("⑧ 相对 import 不许落到 _scratch 的备份副本",
         refs("backend/recognizer/floor.py", "from . import outline as OUT\n"),
         []),
        ("⑨ 点路径 import 同上",
         refs("_wall_thin_batch.py",
              "from backend.recognizer import outline as OUT\n"),
         []),
    ]
    for title, got, want_hits in cases:
        hits = got["hits"] if got else None
        checks.append((title, hits == want_hits,
                       "得到 %r，期望 %r" % (hits, want_hits)))

    # ★ 夹具分辨力自检：若这几个用例的期望**全同**，这套夹具证明不了任何东西。
    distinct = {tuple(w) for _t, _g, w in cases}
    if len(distinct) < 2:
        print("★刑具自己坏了：⑥…⑨ 的期望全同（%s），它分辨不了任何东西" % distinct)
        return 3

    got = refs("zzz.py", "import os\nX = 1\n")
    checks.append(("⑩ 阴性对照：真零引用的文件不许报出任何命中",
                   got is not None and got["hits"] == [] and got["unresolved"] == [],
                   "得到 %r" % (got,)))

    got = refs("zzz_probe.py", "from _newfix import geometry as G\n")
    checks.append(("⑪ 解析不出、但末段与候选重名 → 必须进 unresolved",
                   got is not None and got["unresolved"] == ["_newfix/geometry"],
                   "得到 %r" % (got,)))

    disp3, why3 = _dispose("_scratch/weird/geometry.py", "geometry.py",
                           [], [], ["zzz_probe.py -> _newfix/geometry"])
    checks.append(("⑫ 拿不准 ⇒ 待拍板，不许叫它一次性探针",
                   disp3 == "待拍板" and "一次性探针" not in why3,
                   "得到 %r" % disp3))

    # ⑬⑭ 是**真跑出来的两条噪声**（第一版全库扫描把它们报成了「疑似引用」）：
    #     噪声的下场是「一个总在喊的通道被人学会忽略」，所以它们和漏报一样要修。
    got = refs("_wall_thin_batch.py",
               "from recognizer.classify_line import classify_line\n")
    checks.append(("⑬ `from mod import 同名属性` 不许凭空造出子模块",
                   got is not None and got["hits"] == [] and got["unresolved"] == [],
                   "得到 %r（假子模块 recognizer/classify_line/classify_line）" % (got,)))

    got = refs("_wall_thin_batch.py", "from shapely.geometry import Polygon\n")
    checks.append(("⑭ 第三方包前缀（shapely）不许因末段撞名而报疑似",
                   got is not None and got["hits"] == [] and got["unresolved"] == [],
                   "得到 %r（末段 geometry 撞上了候选）" % (got,)))

    # ⑮⑯ 引用者**自己是不是候选** —— 这条判断原来埋在扫全仓的循环里，
    #     而它正是出过事的那一行：`rel in cand_files` 把候选之间的引用整段跳过了。
    idx = {r: {"code": [], "imp": [], "prose": [], "unres": []} for r in fix_cand}
    _absorb("qa_defect_census.py", "import _defect_census as C\n", "py",
            idx, by_name, by_stem, fix_all, fix_cand)
    got_code = idx["_scratch/_defect_census.py"]["code"]
    checks.append(("⑮ 引用者**本身也是候选**时，这条引用必须算数",
                   got_code == ["qa_defect_census.py"],
                   "得到 %r，期望 %r" % (got_code, ["qa_defect_census.py"])))

    idx = {r: {"code": [], "imp": [], "prose": [], "unres": []} for r in fix_cand}
    _absorb(SELF_REL, "import _defect_census as C\n", "py",
            idx, by_name, by_stem, fix_all, fix_cand)
    n_self = sum(len(v["code"]) + len(v["prose"]) + len(v["unres"]) for v in idx.values())
    checks.append(("⑯ 元工具自己（SELF_REL）仍然整份不算引用者",
                   n_self == 0, "从 %s 吸到 %d 条" % (SELF_REL, n_self)))

    # ⑰ 处置**不许是空串**：空串在 JSON 里读作「没有处置」，而屏幕/分档又把它叫
    #    「待拍板」—— 同一个事实两份写法，按 key 读的消费者会把这类静默丢掉。
    #    ★ 样本必须挑一个**不在 PINNED** 的根文件，否则它量的是 PINNED 那一档，
    #      跟「空串」这条规则无关。（原来借的 `_probe_doorbox_equiv.py` 2026-09-24
    #      被收进 PINNED，这条当场转红 —— 红得对：它已经不在量那件事了。）
    disp4, _w = _dispose("_zz_unpinned_root.py", "_zz_unpinned_root.py", [], [])
    checks.append(("⑰ 根目录散件的处置不许是空串（空=没有 vs 待拍板 是两回事）",
                   disp4 == "待拍板",
                   "得到 %r（空串会让按 disposition 读的人静默丢掉它）" % disp4))

    # ⑱ 阳性/阴性一对：**「被提到」不等于「被引用」**。
    #    这一对是 v4 删掉「已登记」那一档的回归防线。那个档的判据是
    #    「文件名出现在 backend/checks/*.py 的字节里」，于是
    #    ① 我在 sources.py 里写一句注释也算数（文本事实冒充代码事实）；
    #    ② 它排在「代码引用」**前面**，把 `_scratch/_area_audit.py` 的真引用盖住了
    #       ⇒ 名册说它「已登记」，`_scratch/` 一移走，`checks/sources.py:31` 当场断。
    #    ★ 两个方向都要：只验「提到不算」会放过「真引用也不算」这把刀。
    d_mention, w_mention = _dispose("_scratch/zz_comment_only.py", "zz_comment_only.py",
                                    [], ["backend/checks/system.py"])
    d_coderef, _w2 = _dispose("_scratch/_area_audit.py", "_area_audit.py",
                              ["backend/checks/sources.py",
                               "backend/api/services/area_audit.py"], [])
    checks.append(("⑱ 引擎里**提到过** ≠ 已登记；**真按名引用**才算必须收编",
                   d_mention == "一次性探针" and d_coderef == "必须收编",
                   "只被提到得到 %r（须为一次性探针）；有代码引用得到 %r（须为必须收编）"
                   % (d_mention, d_coderef)))

    # ⑲ import 与「字符串里点名」必须分开报 —— 这两者的后果不同：
    #    import 命中 = 搬走当场 ImportError；字面量命中可能只是文案（断不了链，
    #    但文案会指向不存在的路径）。**混成一档会让人以为两个都得靠改代码解决。**
    #    2026-09-24 实测依据：`_purpose_color_guard.py` 那 3 处「引用」逐条看下去
    #    全是错误信息/文档串里点了名，一处调用都没有。
    idx = {r: {"code": [], "imp": [], "prose": [], "unres": []} for r in fix_cand}
    _absorb("qa_defect_census.py", "import _defect_census as C\n", "py",
            idx, by_name, by_stem, fix_all, fix_cand)
    imp_yes = idx["_scratch/_defect_census.py"]["imp"]

    idx = {r: {"code": [], "imp": [], "prose": [], "unres": []} for r in fix_cand}
    _absorb("zz_literal_only.py",
            'MSG = "见 _scratch/_defect_census.py 的说明"\n', "py",
            idx, by_name, by_stem, fix_all, fix_cand)
    e = idx["_scratch/_defect_census.py"]
    imp_no = e["imp"]
    checks.append(("⑲ import 命中与「字符串里点名」必须分开报",
                   imp_yes == ["qa_defect_census.py"] and imp_no == []
                   and e["code"] == ["zz_literal_only.py"],
                   "import 形态得到 %r；字面量形态得到 imp=%r code=%r"
                   "（字面量那档不许冒充 import）" % (imp_yes, imp_no, e["code"])))

    ok = True
    for title, passed, note in checks:
        print("%-4s %-52s %s" % ("OK" if passed else "★红", title, note))
        ok = ok and passed
    print("\n--selftest %s ①…⑲" % ("全过" if ok else "★有红：尺子坏了，别信它的数"))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    known = ("--print", "--selftest")
    bad = [a for a in argv if a.startswith("-") and a not in known]
    if bad:
        print("不认识的开关：%s\n可用：%s" % ("、".join(bad), "、".join(known)))
        return 2
    if "--selftest" in argv:
        return selftest()

    built = build()
    entries = built["entries"]
    tally: dict[str, int] = {}
    for e in entries:
        tally[e["disposition"]] = tally.get(e["disposition"], 0) + 1
    payload = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "criterion_version": CRITERION_VERSION,
        "source_sha256_12": _sha12(Path(__file__)),
        "root": str(ROOT),
        "tally": tally,
        "unreadable_files": built["unreadable_files"],
        "entries": entries,
    }
    print("名册：%d 条  %s" % (len(entries), tally))
    if built["unreadable_files"]:
        # ★ 量不到的要能被看见，不许静默：这些文件里有没有引用，本尺子答不了。
        print("  ⚠ %d 个文件解析不动、没量到（它们引用了什么，本尺子不知道）：%s"
              % (len(built["unreadable_files"]), built["unreadable_files"][:5]))
    for e in entries:
        if e["disposition"] in ("必须收编", "待拍板"):
            print("  [%-8s] %-52s %s"
                  % (e["disposition"], e["path"], e["why"]))
    if "--print" in argv:
        print("（--print：没落盘）")
        return 0
    _atomic_json(OUT, payload)
    print("已写 %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
