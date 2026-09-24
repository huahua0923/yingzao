# -*- coding: utf-8 -*-
"""按名引用：谁**真的**引用了这个文件 —— 名册与门禁共用的一份实现。

★ 为什么单独一个文件：这是「搬文件会不会静默断链」那条判据的**唯一读取路径**。
  它曾有一处严重缺陷（2026-09-24 实测，gym3d）：只搜**字符串字面量**，
  于是 `qa_defect_census.py:67` 的 `import _defect_census as C` 完全看不见 ——
  名册把 `_scratch/_defect_census.py` 判成「一次性探针」（= 可以随 `_scratch` 搬走），
  而真搬走，根门禁会在 import 行**当场炸**。
  ⇒ **少报的方向恰好是最危险的方向**：它让「搬了就断」看起来像「可以搬」。

★ 引用的形态有三种，缺一不可：
  ① 字符串里的路径（`os.path.join("_scratch","_area_audit.py")`）
  ② import 语句（`import X` / `from X import Y`）—— 就是当初漏掉的那一种
  ③ 前端 JS 里的字符串（调用方处理）
  ⇒ 当初的自检夹具**只摆了①**，所以②的坏法在整个自检里是隐形的
    （memory: fixture-shape-must-copy-real-artifact）。

★ 两种**假阳性**同样致命（会反过来把副本当成被引用的真件，无端挡住该搬的东西）：
  · **同 stem 撞车**：`_scratch/_newfix/geometry.py` 与 `backend/recognizer/geometry.py`
    同叫 geometry，而引用者写的是 `from backend.recognizer import geometry`。
  · **同目录同名**：`_scratch/_head_glb/glb_common.py` 与 `backend/modeling/glb_common.py`，
    引用者裸写 `from glb_common import …`，靠 `sys.path.insert(0, dirname(__file__))` 解析。
  ⇒ 出路是**解析**，不是配对：按 import 的形态算出它到底指哪个文件。
    算不出就**说不算不出**（进 `unresolved`），不许「找不到就当没引用」。

★ 所谓解析，依据是本仓**实测**的 sys.path 用法，不是猜：脚本先把自己所在目录
  插到 `sys.path[0]`，再插 `backend` / `backend/web` / 仓库根 / `_scratch`。
  这个次序写在 `SYS_PATH_ROOTS` 里，是**声明**，不是魔法。

★ `unresolved` 只收**可能与我们有关**的：前缀得是本仓可导入的顶层名。
  否则 `from shapely.geometry import …` 会因为末段也叫 geometry 而天天误报 ——
  一个总在喊的通道，下场是被人学会忽略（memory: append-only-ledger-whole-table-assertion）。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

#: 裸模块名的搜索次序，相对仓库根。顺序即本仓脚本 `sys.path` 的插入次序。
#: ★ 调用方**自己的目录**排在最前 —— 这不是随手加的，是本仓的实测写法
#:   （`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`）。
#:   少了它，`backend/modeling/su_spec.py` 的 `from glb_common import …` 会被
#:   算到 `_scratch/_head_glb/glb_common.py` 那份**副本**头上。见 `roots_for`。
SYS_PATH_ROOTS = ("", "backend", "backend/web", "_scratch")


def roots_for(importer_rel: str, level: int) -> tuple[str, ...]:
    """这条 import 该在哪些目录下找它的模块（目录前缀，相对仓库根）。

    相对 import（level>=1）在 `import_intents` 里**已经算成绝对路径**了，
    所以这里只需要空前缀；绝对/裸名则按 Python 的顺序：调用方自己的目录最前。
    """
    if level:
        return ("",)
    return (os.path.dirname(importer_rel),) + SYS_PATH_ROOTS


# ── 语法层：这份源码引用了哪些模块 ────────────────────────────────

def str_literals(tree: ast.AST) -> list[str]:
    """**代码用的**字符串常量；排除文档串。"""
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                            ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_ids.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in doc_ids]


def _pkg_dir(importer_rel: str, level: int) -> str:
    """相对 import（level>=1）的基目录：1 = 本包，2 = 上一级，依此类推。"""
    d = os.path.dirname(importer_rel)
    for _ in range(max(0, level - 1)):
        d = os.path.dirname(d)
    return d


def _join(base: str, dotted: str) -> str:
    mid = dotted.replace(".", "/") if dotted else ""
    return "/".join(x for x in (base, mid) if x)


def import_intents(node: ast.AST, importer_rel: str) -> list[tuple[str, list[str]]]:
    """一条 import 语句**打算**拿到什么：`[(模块路径, [可能取出的子模块名…]), …]`。

    · `import a.b.c` → `[("a", []), ("a/b", []), ("a/b/c", [])]`
      （Python 会把 `a`、`a.b`、`a.b.c` 依次绑定，三个都是真引用）
    · `from a.b import c, d` → `[("a/b", ["c", "d"])]`
      （`c` 可能是 `a/b/c.py` 这个**子模块**，也可能只是 `a/b` 里的一个**属性**
        —— 静态分不清。所以不在这里赌：交给解析那一层，父模块若落到一个普通
        `.py`，它就**不可能**有子模块，那两个名字只能是属性。）
    """
    out: list[tuple[str, list[str]]] = []
    if isinstance(node, ast.Import):
        for a in node.names:
            parts = a.name.split(".")
            for i in range(1, len(parts) + 1):
                out.append((_join("", ".".join(parts[:i])), []))
        return out
    if not isinstance(node, ast.ImportFrom):
        return out
    lvl = node.level or 0
    base = _pkg_dir(importer_rel, lvl) if lvl else ""
    mod = node.module or ""
    out.append((_join(base, mod), [a.name for a in node.names]))
    return out


# ── 解析层：把模块路径落到「仓库里真有的那个文件」 ──────────────────

def _resolve(path_no_ext: str, roots: tuple[str, ...],
             cand_files: set[str], all_py: set[str]) -> tuple[str | None, str]:
    """返回 `(命中的候选 rel | None, 形态)`。

    形态 ∈ {`hit_mod` 候选普通 .py, `hit_pkg` 候选 __init__.py,
            `real_mod` 非候选普通 .py, `real_pkg` 非候选 __init__.py, `none`}。
    ★ 区分 mod 与 pkg 是有用的：落到普通 .py 就**不可能有子模块**，
      于是 `from mod import attr` 里的 attr 不必再当成子模块去探（否则
      `from recognizer.classify_line import classify_line` 会凭空造出一个
      `recognizer/classify_line/classify_line`，然后被报成「解析不出」）。
    """
    for r in roots:
        p = "/".join(x for x in (r, path_no_ext) if x)
        q = p + ".py"
        if q in cand_files:
            return q, "hit_mod"
        if q in all_py:
            return None, "real_mod"
        q = p + "/__init__.py"
        if q in cand_files:
            return q, "hit_pkg"
        if q in all_py:
            return None, "real_pkg"
    return None, "none"


def repo_py_files(root: Path, skip: set[str]) -> set[str]:
    """仓库里全部 .py 的 rel 路径（正斜杠）—— 解析用的「现实」。

    名字里带 repo_ 前缀是有意的：它是**全库**的，不只是候选的。
    少收一份，副本与真件就分不开，假阳性立刻回来。
    """
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fn.endswith(".py"):
                p = Path(dirpath) / fn
                out.add(str(p.relative_to(root)).replace(os.sep, "/"))
    return out


def repo_top_names(all_py: set[str]) -> set[str]:
    """本仓**可导入的顶层名**（按 `SYS_PATH_ROOTS` 各自的根来数）。

    用来挡掉第三方包：`from shapely.geometry import …` 的 `shapely` 不在里面，
    所以哪怕末段撞上我们某个候选的名字，也不会被报成「解析不出的疑似引用」。
    """
    tops: set[str] = set()
    for r in SYS_PATH_ROOTS:
        pre = (r + "/") if r else ""
        for rel in all_py:
            if pre and not rel.startswith(pre):
                continue
            rest = rel[len(pre):]
            if not rest:
                continue
            segs = rest.split("/")
            head = segs[0]
            tops.add(head[:-3] if (len(segs) == 1 and head.endswith(".py")) else head)
    return tops


# ── 对外：一个文件按代码引用了哪些候选 ──────────────────────────────

def file_refs(importer_rel: str, text: str, cand_by_name: dict,
              cand_by_stem: dict, all_py: set[str],
              cand_files: set[str]) -> dict | None:
    """本文件按**代码**引用到的候选 rel。

    返回 `{"hits": [...], "unresolved": [...], "imported": [...]}`；
    解析不动 → `None`（= 量不到，不许当成「里面没有」，否则一个读不了的文件
    会让它引用的东西被误判成探针）。

    ★ `imported` 是 `hits` 的**子集**：命中途径是 import 语句的那些。
      `hits - imported` 全部来自字符串字面量。**这两者要分开报**，因为它们的
      后果完全不同：
        · import 命中 ⇒ 那个文件一搬走，这一行**当场 ImportError**（会断）；
        · 字面量命中 ⇒ 可能是 `subprocess`/`os.path.join` 的**参数**（也会断），
          也可能只是 `"…见 _scratch/_area_audit.py"` 这样一句**给人看的文案**
          （不断链，但搬走后这句话指向一个不存在的路径 —— 是「注记指空」）。
      ★ 字面量这一半，**本尺子分辨不了**是调用还是文案（那要数据流，静态做不准）。
        所以不许在理由里写成「调用」—— 只说「按名出现」，把分辨的事留给看的人。
        （2026-09-24 实测：`_purpose_color_guard.py` 被 3 处「引用」，
          逐条看下去全是**错误信息/文档串**里点了名，一处调用都没有。）
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None

    hits: set[str] = set()
    imported: set[str] = set()

    # ① 字符串里的路径：字面量里出现候选的**文件名**即算。
    #    （路径拼接写法认得出；`import` 写法认不出 —— 那正是 ② 要补的。）
    lits = str_literals(tree)
    if lits:
        for name, rels in cand_by_name.items():
            if any(name in s for s in lits):
                hits.update(rels)

    # ② import 语句：**解析**到哪个文件才算哪个。
    tops = repo_top_names(all_py)
    unresolved: set[str] = set()

    def probe(path: str, roots: tuple[str, ...]) -> str:
        """探一条模块路径。返回形态（`hits` / `unresolved` 就地更新）。"""
        got, kind = _resolve(path, roots, cand_files, all_py)
        if got is not None:
            hits.add(got)
            imported.add(got)
        elif kind == "none":
            head = path.split("/")[0]
            # 有斜杠的，前缀得是本仓可导入的顶层名；否则那是第三方包（如 shapely）
            if "/" not in path or head in tops:
                if path.rsplit("/", 1)[-1] in cand_by_stem:
                    unresolved.add(path)
        return kind

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # `ast.Import` 没有 level（只有 ImportFrom 有），拿属性要用 getattr
        roots = roots_for(importer_rel, getattr(node, "level", 0) or 0)
        for mod_path, names in import_intents(node, importer_rel):
            kind = probe(mod_path, roots)
            if kind in ("real_mod", "hit_mod"):
                continue   # 普通 .py 不是包 ⇒ 下头的名字只能是属性，不是子模块
            for nm in names:
                probe(_join(mod_path, nm), roots)

    return {"hits": sorted(hits), "unresolved": sorted(unresolved),
            "imported": sorted(imported)}
