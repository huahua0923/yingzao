# -*- coding: utf-8 -*-
"""把「文档宣称的阈值」与「代码里的真值」对上 —— 门禁④（值漂移）的引擎。

## 为什么单独一个文件

`算法与流程总览.md` 里**不止一张**阈值表：§3「阈值总表」（5 列）、
§2.3「关键常量」（3 列）、§2.4（3 列）。**同一批常量在多张表里各写一遍**
（实测 `SLAB_RATIO` / `CURVE_MIN_R` / `DOOR_LEAF_MIN/MAX` 两边都有）。
那是**宣称值**那一侧。**宣称值会过期**，而「文档说 0.6、代码是 0.8」这种事，
屏幕上两处都好看，只有机器比得出来。

★ 所以**按表头认列、不按 §3 认表**：写死「只读 §3」会让另两张表
  **整个不被核到**，而输出照样写「30 行、20 行比过」—— 读的人会以为阈值都核过了。
  实测这一处漏掉了 14 行（30 → 44），是「量不到 ≠ 没问题」的正面案例
  （memory: gauge-coverage-invisible-in-summary）。

这里只做一件事：**读宣称值 → 去全仓把真值找出来 → 逐行给判决。**

## 真值住在哪（四种，缺一种就会假红）

实测踩过：只扫模块级 `Assign`，于是把 `wall_min` 报成 MISSING —— 而它是
`BuildingProfile` 的**逐栋字段**，真值在 `profiles/j6.py` 的**关键字实参**里。
所以真值有四个来源，逐个找：

    MODULE_CONST   `SLAB_RATIO = 1.0`            模块级赋值
    KWARG          `BuildingProfile(wall_min=0.08)`  调用实参（逐栋配置）
    INLINE_LIT     `if rect_share >= 0.30`       内联字面量（**不是常量，是隐患**）
    （都没有）      ⇒ MISSING

## 三条自我约束（否则这把尺子会被学会忽略）

1. **宁可说「量不了」，不许造假红。** 值栏有 `max(外,内) + 0.05` 这种表达式、
   有 `verify_floor B` 这种函数级判据、有 `配对重叠` 这种描述 —— 机器比不了。
   判 `UNVERIFIABLE` 并**写明理由**。假红和假绿一样坏：红三次没人管，第四次真红也没人看。
   （本项目一把尺子曾把 4 条真值全报成 MISSING，只因真值住在关键字实参里。）
2. **量纲不一致单独成一类。** §3 写 `30000 mm`、代码 `30000` ⇒ 数值同，MATCH。
   §3 写 `30 m`、代码 `30000` ⇒ 差 1000 倍。这未必是代码错（可能文档换了单位），
   所以判 `UNIT_SCALE` 而不判 DRIFT，并把两个数都打出来。
3. **★ 分母必须写出来。**「30 行比了 20 行」和「30 行全对」在汇总里长得一模一样。
   返回结构带 `counts` ＋ `unverifiable_reasons`，量不了的**按理由分组计数**。

## ★ 全绿证明不了这把尺子能红

`--selftest` 用**阳性对照**：改坏 §3 一个值 ⇒ 必须 DRIFT；改单位 ⇒ 必须 UNIT_SCALE；
改一个不存在的常量名 ⇒ 必须 MISSING；删掉整节 ⇒ 必须报「表没抽到」。
四条都不通过就红 —— 只验「干净时是绿的」等于没验。
"""
from __future__ import annotations

import sys
import ast
import io
import os
import re

#: kb/ 的上一级 = 仓根
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECTION3 = os.path.join(ROOT, "算法与流程总览.md")

#: 表头里认这两个列名 —— 常量列与值列。**不写死列号**：
#: 本仓的阈值表至少有两种形状（§3 是 5 列带「类别/出处/防什么」，§2.3 是 3 列），
#: 写死列号就会**只认得出其中一张**，而另一张会安静地不被核到。
# 中文日志不设编码必糊字；★ 更要紧的是：Windows 管道 stdout 默认 GBK，
# 而本文件会打「↔」这类字符 ⇒ 打印时自己崩、退出码非 0，调用方读成「判据红了」。
# 见 kb/gate.py 同一段落，以及 backend/checks/kg_citation.py。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_HDR_CONST = ("常量", "阈值", "参数", "符号", "名称")
_HDR_VAL = ("值", "数值", "取值", "默认值")

#: 扫常量时跳过的目录：归档/依赖/产物/前端，都不是生产 Python
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".orig", "_scratch", "data",
              "frontend", ".venv", "venv", "kb"}

#: 量纲差这些倍数 ⇒ 判 UNIT_SCALE 而不是 DRIFT（1000=mm↔m，100=%↔小数）
_SCALE_FACTORS = (1000.0, 100.0)

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

#: 不宜当常量名（描述、函数级判据、含中文/空格）
_NOT_A_NAME = re.compile(r"[\s一-鿿]")

_TABLE_CACHE: dict | None = None


# ---------------------------------------------------------------- §3 解析

def parse_tables(path: str | None = None, text: str | None = None) -> list[dict]:
    """把总览里**所有**「常量 → 值」形状的表都抽出来，逐行带**它属于哪张表**。

    ★ 为什么走「按表头认列」而不是「按 §3 认表」：本仓实测有两张阈值表 ——
      §3「阈值总表」（5 列，带类别/出处/防什么）与 §2.3「关键常量」（3 列），
      `SLAB_RATIO` / `CURVE_MIN_R` / `DOOR_LEAF_MIN/MAX` 等**两边各写一遍**。
      只认 §3 的写法会让另一张表**整个不被核到**，而输出照样写「30 行、20 行比过」——
      读的人会以为阈值都核过了。这就是「量不到 ≠ 没问题」
      （memory: gauge-coverage-invisible-in-summary）。

    抽不到返回空 —— 调用方必须把它当**红的**：表没了和表是空的在屏幕上一样。
    """
    if text is None:
        text = io.open(path or SECTION3, encoding="utf-8", errors="replace").read()
    rows: list[dict] = []
    heading = ""
    cols: dict[str, int] | None = None
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
            cols = None
            continue
        if not line.startswith("|"):
            cols = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        bare = [c.strip("`").strip() for c in cells]
        if cols is None:
            ci = next((k for k, c in enumerate(bare) if c in _HDR_CONST), None)
            vi = next((k for k, c in enumerate(bare) if c in _HDR_VAL), None)
            if ci is None or vi is None:
                continue                      # 不是阈值表（如「维度|classify|…」那张）
            cols = {"const": ci, "val": vi,
                    "cat": next((k for k, c in enumerate(bare) if c in ("类别", "维度")), None),
                    "src": next((k for k, c in enumerate(bare) if c in ("出处", "来源", "文件")), None),
                    "why": next((k for k, c in enumerate(bare) if c in ("防什么", "作用", "说明", "备注")), None)}
            continue
        if set("".join(cells)) <= set("-: "):  # |---|---| 分隔行
            continue
        g = lambda k: (cells[cols[k]].strip() if cols.get(k) is not None
                       and cols[k] < len(cells) else "")
        c = g("const").strip("`").strip()
        if not c or set(c) <= set("-: "):
            continue
        rows.append({"table": heading, "cat": g("cat"), "const": c, "val": g("val"),
                     "src": g("src"), "why": g("why"), "line": i})
    return rows


def parse_section3(path: str | None = None, text: str | None = None) -> list[dict]:
    """只要 §3「阈值总表」那一张（其余表的行仍在 `parse_tables` 里，不丢）。"""
    return [r for r in parse_tables(path=path, text=text) if r["table"].startswith("3")]


def expand_names(cell: str) -> list[str]:
    """`DOOR_LEAF_MIN/MAX` → [DOOR_LEAF_MIN, DOOR_LEAF_MAX]；`JAMB_LEN/W` → [JAMB_LEN, JAMB_W]。

    ★ 反引号要**逐段**剥：§3 原文有 `` `BIG_WALL` / `BIG_KEEP` `` 这种写法，
      只剥首尾会让名字带上反引号 —— 实测据此产出了两条假红。
    """
    cell = cell.strip()
    if "/" not in cell:
        return [cell.strip().strip("`")]
    parts = [x.strip().strip("`") for x in cell.split("/")]
    head = parts[0]
    prefix = head.rsplit("_", 1)[0] + "_" if "_" in head else ""
    out = [head]
    for x in parts[1:]:
        out.append(x if ("_" in x or not prefix) else prefix + x)
    return out


def parse_values(cell: str) -> list[float] | None:
    """`0.6 / 3.0 m` → [0.6, 3.0]；`2.0 m` → [2.0]；表达式/描述 → None。"""
    body = cell.strip().lstrip("≤≥<>±≈").strip()
    if re.search(r"[（(]", body):          # max(外,内) + 0.05 之类
        return None
    if re.search(r"[一-鿿]", body):        # 含中文 ⇒ 是描述不是数
        return None
    nums = [float(x) for x in _NUM_RE.findall(body)]
    return nums or None


# ---------------------------------------------------------------- 全仓真值表

def _truth_table(repo: str | None = None) -> dict:
    """一次走全仓，收三种真值来源。**走全仓** —— 按文件名猜位置会造假红
    （本仓实伤：`detect_doors` 不在 `openings.py` 而在 `geometry.py:1408`）。"""
    root = repo or ROOT
    consts: dict[str, list[tuple[str, int, float]]] = {}
    kwargs: dict[str, list[tuple[str, int, float]]] = {}
    inline: dict[str, list[tuple[str, int, float, str]]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                tree = ast.parse(io.open(p, encoding="utf-8", errors="replace").read())
            except (OSError, SyntaxError):
                continue
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):                 # MODULE_CONST
                    for t in node.targets:
                        v = _lit(node.value)
                        if isinstance(t, ast.Name) and v is not None:
                            consts.setdefault(t.id, []).append((rel, node.lineno, v))
                elif isinstance(node, ast.keyword):              # KWARG（逐栋 profile）
                    v = _lit(node.value)
                    if node.arg and v is not None:
                        kwargs.setdefault(node.arg, []).append((rel, node.lineno, v))
                elif isinstance(node, ast.Compare):              # INLINE_LIT
                    for left, op, right in zip([node.left] + list(node.comparators),
                                               node.ops, node.comparators):
                        for nm, lit in ((left, right), (right, left)):
                            if isinstance(nm, ast.Name):
                                v = _lit(lit)
                                if v is not None:
                                    opstr = type(op).__name__.replace("Gt", ">").replace(
                                        "Lt", "<").replace("GtE", ">=").replace("LtE", "<=")
                                    inline.setdefault(nm.id, []).append(
                                        (rel, node.lineno, v, opstr))
    return {"consts": consts, "kwargs": kwargs, "inline": inline}


def _lit(node) -> float | None:
    try:
        v = ast.literal_eval(node)
    except Exception:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _table(repo: str | None = None) -> dict:
    global _TABLE_CACHE
    if _TABLE_CACHE is None:
        _TABLE_CACHE = _truth_table(repo)
    return _TABLE_CACHE


# ---------------------------------------------------------------- 判决

def compare(row: dict, table: dict) -> dict:
    """一行一判决。verdict ∈ MATCH / DRIFT / UNIT_SCALE / AMBIGUOUS / MISSING / UNVERIFIABLE。"""
    names = expand_names(row["const"])
    vals = parse_values(row["val"])
    out = {"row": row, "verdict": "UNVERIFIABLE", "detail": "", "pairs": [], "how": ""}

    if any(_NOT_A_NAME.search(n) or not n for n in names):
        out["detail"] = "常量栏是描述或函数级判据，不是可解析的常量名"
        return out
    if vals is None:
        out["detail"] = "值栏是表达式或描述，非字面量"
        return out
    if len(names) != len(vals):
        out["detail"] = "常量 %d 个、值 %d 个，对不上" % (len(names), len(vals))
        return out

    verdicts: set[str] = set()
    hows: set[str] = set()
    for n, want in zip(names, vals):
        kind, hits = _resolve(n, table)
        if not hits:
            verdicts.add("MISSING")
            out["pairs"].append({"name": n, "want": want, "got": None, "where": None})
            continue
        hows.add(kind)
        distinct = sorted({h[2] for h in hits})
        if len(distinct) > 1:
            verdicts.add("AMBIGUOUS")
            out["pairs"].append({"name": n, "want": want, "got": distinct,
                                 "where": ", ".join("%s:%d" % (h[0], h[1]) for h in hits[:6])})
            continue
        got = distinct[0]
        pair = {"name": n, "want": want, "got": got,
                "where": "%s:%d" % (hits[0][0], hits[0][1])}
        if kind == "INLINE_LIT":
            pair["note"] = "★ 内联字面量、非具名常量：%d 处各写一遍（%s）" % (
                len(hits), ", ".join("%s:%d" % (h[0], h[1]) for h in hits[:3]))
        elif kind == "KWARG":
            # 逐栋配置：只有手写 profile 显式带这个 kwarg，其余楼由 detect_params 探测
            # ⇒ 「与 N 栋一致」≠「全库都这样」，说清楚是几栋。
            pair["note"] = "逐栋配置：%d 处显式写（%s）；其余楼由 detect_params 探测" % (
                len(hits), ", ".join("%s:%d" % (h[0], h[1]) for h in hits[:4]))
        if abs(got - want) <= 1e-9 * max(1.0, abs(want)):
            verdicts.add("MATCH")
        else:
            ratio = (got / want) if want else 0.0
            if any(abs(ratio - s) < 1e-6 or abs(ratio - 1.0 / s) < 1e-6 for s in _SCALE_FACTORS):
                verdicts.add("UNIT_SCALE")
                pair["note"] = "相差 %g 倍 —— 量纲/单位不一致，未必是代码错" % ratio
            else:
                verdicts.add("DRIFT")
        out["pairs"].append(pair)

    for v in ("AMBIGUOUS", "MISSING", "DRIFT", "UNIT_SCALE", "MATCH"):
        if v in verdicts:
            out["verdict"] = v
            break
    out["how"] = "+".join(sorted(hows))
    out["detail"] = {
        "MATCH": "一致", "DRIFT": "宣称值与代码真值不等",
        "MISSING": "三种来源都找不到这个常量（可能改名/搬走，也可能只在文档里活着）",
        "AMBIGUOUS": "同名常量在多处取了不同的值",
        "UNIT_SCALE": "数值差一个单位倍数",
    }.get(out["verdict"], "")
    return out


def _resolve(name: str, table: dict) -> tuple[str, list]:
    """按可信度找真值：模块常量 > 关键字实参 > 内联字面量。"""
    for kind, key in (("MODULE_CONST", "consts"), ("KWARG", "kwargs"), ("INLINE_LIT", "inline")):
        hits = table[key].get(name)
        if hits:
            return kind, hits
    return "NONE", []


def audit(repo: str | None = None, section3_text: str | None = None) -> dict:
    """全表对账。**分母写出来** —— 比了几行、几行量不了、按什么理由量不了。

    ★ 抽的是**所有**阈值表，不只是一张：抽漏一张 = 那张表整个不被核到，
      而输出照样好看（见 `parse_tables` 的说明）。
    """
    rows = parse_tables(text=section3_text)
    table = _table(repo)
    results = [compare(r, table) for r in rows]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    reasons: dict[str, int] = {}
    for r in results:
        if r["verdict"] == "UNVERIFIABLE":
            reasons[r["detail"]] = reasons.get(r["detail"], 0) + 1
    per_table: dict[str, dict[str, int]] = {}
    for r in results:
        t = r["row"]["table"] or "(无标题)"
        per_table.setdefault(t, {})
        per_table[t][r["verdict"]] = per_table[t].get(r["verdict"], 0) + 1
    return {"rows": rows, "results": results, "counts": counts, "per_table": per_table,
            "unverifiable_reasons": reasons, "total": len(rows),
            "compared": sum(counts.get(v, 0) for v in
                            ("MATCH", "DRIFT", "UNIT_SCALE", "AMBIGUOUS", "MISSING"))}


# ---------------------------------------------------------------- 自检

def selftest() -> int:
    """四条刑具，**每条都要能红**。全绿证明不了这把尺子能红。"""
    base_text = io.open(SECTION3, encoding="utf-8", errors="replace").read()
    fails: list[str] = []

    base = audit(section3_text=base_text)
    if base["total"] == 0:
        fails.append("T0 一张阈值表都没抽到 —— 尺子接不上被测对象")
    if sum(base["counts"].values()) != base["total"]:
        fails.append("T0 判决数与行数不等 —— 有行被静默丢掉")

    # T1 改坏一个值 ⇒ 必须 DRIFT，且指到那一行
    t1 = audit(section3_text=base_text.replace("| `SLAB_RATIO` | 1.0 |", "| `SLAB_RATIO` | 9.9 |"))
    d1 = [r for r in t1["results"] if r["verdict"] == "DRIFT" and r["row"]["const"] == "SLAB_RATIO"]
    if not d1:
        fails.append("T1 把 SLAB_RATIO 的 1.0 改成 9.9 ⇒ 没报 DRIFT（此判据恒绿）")

    # T2 改单位 ⇒ 必须 UNIT_SCALE，不许误报 DRIFT
    t2 = audit(section3_text=base_text.replace("| `CURVE_MIN_R` | 2.0 m |", "| `CURVE_MIN_R` | 2000 m |"))
    v2 = next((r["verdict"] for r in t2["results"] if r["row"]["const"] == "CURVE_MIN_R"), None)
    if v2 != "UNIT_SCALE":
        fails.append("T2 把 2.0 m 改成 2000 m ⇒ 判成 %s，应为 UNIT_SCALE（量纲类没分开）" % v2)

    # T3 改成一个不存在的常量名 ⇒ 必须 MISSING，不许静默当 UNVERIFIABLE
    t3 = audit(section3_text=base_text.replace("| `SLAB_RATIO` | 1.0 |", "| `NO_SUCH_CONST_XYZ` | 1.0 |"))
    if not any(r["verdict"] == "MISSING" and r["row"]["const"] == "NO_SUCH_CONST_XYZ"
               for r in t3["results"]):
        fails.append("T3 换成一个不存在的常量名 ⇒ 没报 MISSING")

    # T4 逐段剥反引号：`BIG_WALL` / `BIG_KEEP` 两段都要干净
    got = expand_names("`BIG_WALL` / `BIG_KEEP`")
    if got != ["BIG_WALL", "BIG_KEEP"]:
        fails.append("T4 逐段剥反引号失败：得到 %r（实测据此类产出了假红）" % (got,))

    # T5 ★ 回归：总览里有**两张**阈值表（§3 五列、§2.3 三列），两张都要抽到并**都比过**。
    #    只认 §3 的写法会让 §2.3 整个隐形，而输出照样写「20 行比过」——
    #    读的人以为阈值都核过了。所以「抽到」和「比过」都要断言。
    if len(base["per_table"]) < 2:
        fails.append("T5 只抽到 %d 张阈值表 —— 总览里有两张（§2.3 关键常量 ＋ §3 阈值总表），"
                     "少的那些行会**整个不被核到**" % len(base["per_table"]))
    for t, tc in base["per_table"].items():
        if sum(tc.get(v, 0) for v in ("MATCH", "DRIFT", "UNIT_SCALE",
                                      "AMBIGUOUS", "MISSING")) == 0:
            fails.append("T5 表「%s」抽到了 %d 行，但一行都没比过（判据空转）"
                         % (t, sum(tc.values())))

    if fails:
        print("--selftest 红：%d 条刑具没通过" % len(fails))
        for f in fails:
            print("   · " + f)
        return 1
    print("--selftest 绿：6 条刑具全部能红（T0 阴性对照 / T1 改值→DRIFT / "
          "T2 改单位→UNIT_SCALE / T3 换名→MISSING / T4 逐段剥反引号 / "
          "T5 两张以上阈值表都抽到且都比过）；基线 %d 张表 %d 行、%d 行能比"
          % (len(base["per_table"]), base["total"], base["compared"]))
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    a = audit()
    if a["total"] == 0:
        print("红：§3 阈值总表一行都没抽到 —— 表没了或改了形，不是「没有阈值」")
        return 1
    c = a["counts"]
    print("阈值表：%d 张、共 %d 行；能机器比的 %d 行，量不了的 %d 行"
          % (len(a["per_table"]), a["total"], a["compared"], a["total"] - a["compared"]))
    for t, tc in sorted(a["per_table"].items()):
        n = sum(tc.values())
        print("   · %-22s %d 行（比过 %d）"
              % (t[:22], n, sum(tc.get(v, 0) for v in ("MATCH", "DRIFT", "UNIT_SCALE",
                                                       "AMBIGUOUS", "MISSING"))))
    for v in ("MATCH", "DRIFT", "UNIT_SCALE", "AMBIGUOUS", "MISSING", "UNVERIFIABLE"):
        if c.get(v):
            print("   %-13s %d" % (v, c[v]))
    if a["unverifiable_reasons"]:
        print("   量不了的理由：")
        for k, n in sorted(a["unverifiable_reasons"].items(), key=lambda x: -x[1]):
            print("      %2d × %s" % (n, k))
    if c.get("MATCH"):
        # ★ 「20 行全对」看不出来路：得说明每条是**被什么来源**核实的。
        #   靠关键字实参核到的（逐栋 profile）和靠模块常量核到的，可信度不一样。
        way: dict[str, int] = {}
        for r in a["results"]:
            if r["verdict"] == "MATCH":
                way[r["how"] or "?"] = way.get(r["how"] or "?", 0) + 1
        print("   核实来源：" + "、".join(
            "%s %d" % ({"MODULE_CONST": "模块常量", "KWARG": "逐栋实参",
                        "INLINE_LIT": "内联字面量",
                        "MODULE_CONST+INLINE_LIT": "常量+内联"}.get(k, k), n)
            for k, n in sorted(way.items(), key=lambda x: -x[1])))
    inline = [r for r in a["results"] if any("内联字面量" in (p.get("note") or "")
                                             for p in r["pairs"])]
    if inline:
        print("   ★ 以下阈值在代码里是**内联字面量**、没有单一源（改一次要改多处）：")
        for r in inline:
            for p in r["pairs"]:
                if p.get("note", "").startswith("★"):
                    print("      %s：%s" % (p["name"], p["note"]))
    bad = [r for r in a["results"] if r["verdict"] in ("DRIFT", "AMBIGUOUS", "MISSING")]
    if bad:
        print()
        for r in bad:
            row = r["row"]
            print("  ✗ [%s] %s「%s」宣称 %s —— %s"
                  % (r["verdict"], row["cat"], row["const"], row["val"], r["detail"]))
            for p in r["pairs"]:
                print("        %s: 宣称 %s，代码 %s  @ %s%s"
                      % (p["name"], p["want"], p["got"], p["where"],
                         ("  ← " + p["note"]) if p.get("note") else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
