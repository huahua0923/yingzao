# -*- coding: utf-8 -*-
"""判据清单跑器 —— 一个闸 = 一张 `CHECKS` 表 + 每条判据一个函数。

闸只写两件事：
  ① 顶部 `CHECKS = [("⑪", "名称", 函数), …]`（编号用 `_verdict` 认得的 ①–⑳）
  ② 每条函数「怎么量、什么算过」

本文件负责：逐条打印一行、汇总判词、定 rc、把每条折成 `_verdict` 的 item 形状。
★ **不碰** `_out/*.json`：每个闸的 JSON 形状各不一样（`demo/sys.html` 现读字段名），
  写盘一律回调闸自己的 `_write`/`finish`；跑器只交出 `报告`（rc / lines / items）。

一条判据函数的返回值（三选一）：
  · `True` / `False`
  · `结果(ok, 实测, 判词)` —— 实测是给人看的一格字，如 `"754/754"`
  · `结果(ok, 实测, 判词, 证据=[…])` —— 证据只报不判，缩进打印
  · 抛 `没量到("原因")` ⇒ 本条 ⚠（不算过、也不假报红 —— 铁律 199）
  · 抛其它异常 ⇒ 本条 ✗，判词写 `崩溃: …`（把「崩了」与「没量到」分开）

整闸 rc：全 ✓ ⇒ 0；有 ✗ ⇒ 1；一条都没量到 ⇒ 4。
"""
import sys
import traceback
import unicodedata


class 没量到(Exception):
    """这一条**没量到**（缺件、缺基线、没读数）—— 不当成过。"""

    def __init__(self, why):
        super().__init__(why)
        self.why = str(why)


class 参数:
    """一条判据用到的**一个**参数：名｜阈值｜真源｜实测｜修法。

    ★ 为什么单独一类：判据红了只说「不对」，说不出「哪个参数不对、真源在哪、
      该改哪一步」。带了参数的判据在 ✗/⚠ 时把这几样并排印出来 ⇒
      红一行 = 直接读出图错在哪个参数、差多少、改哪个文件。
    """

    __slots__ = ("名", "阈值", "真源", "实测", "修法")

    def __init__(self, 名, 阈值="", 真源="", 实测="", 修法=""):
        self.名 = str(名)
        self.阈值 = str(阈值)
        self.真源 = str(真源)
        self.实测 = str(实测)
        self.修法 = str(修法)

    def dict(self):
        """给 `_out/*.json` 的稳定形状（台账页按这几个键读）。"""
        return {"name": self.名, "limit": self.阈值, "source": self.真源,
                "measured": self.实测, "fix": self.修法}

    def 行(self):
        s = "⚙ %s = %s" % (self.名, self.阈值 or "—")
        if self.真源:
            s += "  ← %s" % self.真源
        if self.实测:
            s += "  （实测 %s）" % self.实测
        return s


class 结果:
    """一条判据的结论。`ok` 只许 True/False（⚠ 由 `没量到` 抛出来表达）。

    `参数=[参数(...), …]` 可选：这条判据比对的每一个阈值/基线都列上。
    """

    __slots__ = ("ok", "实测", "判词", "证据", "读数", "参数")

    def __init__(self, ok, 实测="", 判词="", 证据=None, 读数=None, 参数=None):
        self.ok = bool(ok)
        self.实测 = str(实测)
        self.判词 = str(判词)
        self.证据 = list(证据 or [])
        self.读数 = 读数 or {}
        self.参数 = list(参数 or [])


class 报告:
    """一轮跑完的结果：`rc` / 全部打印行 `lines` / `_verdict` 形状的 `items`。"""

    __slots__ = ("gate", "rc", "lines", "items", "rows", "extra")

    def __init__(self, gate, rc, lines, items, rows, extra=None):
        self.gate = gate
        self.rc = rc
        self.lines = lines
        self.items = items
        self.rows = rows
        self.extra = extra or {}


def _宽(s):
    """显示宽度：CJK 记 2 格（只用于对齐，不影响判词）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, n):
    return s + " " * max(0, n - _宽(s))


def _item(编号, 名称, r, 状态, fix_of=None):
    """折成 `_verdict` 的 item 形状（矩阵/页面只认这一种）。"""
    st = {"✓": "pass", "✗": "fail", "⚠": "unmeasured"}[状态]
    return {
        "rule": 编号,
        "status": st,
        "text": ("%s：%s" % (名称, r.判词)) if r.判词 else 名称,
        "fix": fix_of(编号) if fix_of else "",
        "floor": "",
        "evidence": r.实测,
        # ★ 参数化：红了才知道「哪个参数、真源在哪、实测多少」。绿的时候也落盘
        #   （页面/台账要能反查），但**不打印** —— 打印只在 ✗/⚠ 时展开。
        "params": [p.dict() for p in r.参数],
    }


def 跑(gate, checks, log=None, 宽=30, fix_of=None, extra=None):
    """按 `CHECKS` 顺序逐条跑，一行一条。

    `log(s)` 默认 print；闸把自己的 `log` 传进来，打印行就同时进 `run.txt`。
    `fix_of(编号)` 可选：把 `_verdict.FIX_RULES[闸名]` 映射带进来。
    `extra` 可选：闸自己的读数（`_out/*.json` 的附加字段）原样合并进 `报告`。
    """
    out = log or (lambda s: print(s, flush=True))
    lines = []
    _cur = {"row": None}

    def emit(s):
        lines.append(s)
        out(s)

    rows, items = [], []
    n_ok = n_bad = n_skip = 0

    emit("")
    emit("%s —— %d 条判据" % (gate, len(checks)))
    emit("─" * 78)
    for 编号, 名称, fn in checks:
        try:
            r = fn()
        except 没量到 as e:
            r, 状态 = 结果(None, "—", e.why), "⚠"
        except Exception as e:                                        # noqa: BLE001
            detail = traceback.format_exc().strip().splitlines()[-1]
            r, 状态 = 结果(False, "崩溃", "%s: %s" % (type(e).__name__, e),
                           证据=[detail]), "✗"
        else:
            if r is True or r is False:
                r = 结果(bool(r))
            elif isinstance(r, tuple) and r and isinstance(r[0], bool):
                r = 结果(*r)
            elif not isinstance(r, 结果):
                raise TypeError("判据 %s 的返回值 %r 认不出（要 bool / 结果 / 没量到）"
                                % (编号, r))
            状态 = "✓" if r.ok else "✗"

        if 状态 == "✓":
            n_ok += 1
        elif 状态 == "✗":
            n_bad += 1
        else:
            n_skip += 1
        row = _item(编号, 名称, r, 状态, fix_of)
        rows.append(row)
        items.append(row)
        emit("  %-2s %s %s  %s  %s" % (编号, _pad(名称, 宽), _pad(r.实测, 12),
                                      状态, r.判词))
        for e in r.证据:
            emit("       · %s" % e)
        # ★ 参数化：**只有红/没量到时**才展开参数 —— 绿的时候一行就走，
        #   否则 16 条判据 × 每个 2~4 个参数，又变回上百行（用户原话：不要上千行）。
        if 状态 != "✓":
            for p in r.参数:
                emit("       " + p.行())
                if p.修法:
                    emit("         修：%s" % p.修法)

    rc = 4 if (n_ok == 0 and n_bad == 0) else (1 if n_bad else 0)
    emit("─" * 78)
    if rc == 0:
        emit("%s 总判 : PASS（%d/%d 条）%s"
             % (gate, n_ok, len(checks),
                ("  · 另有 %d 条没量到" % n_skip) if n_skip else ""))
    elif rc == 4:
        emit("%s 总判 : SKIP(rc=4) —— %d 条全部**没量到**（不算过、也不假报红）"
             % (gate, n_skip))
    else:
        emit("%s 总判 : FAIL（%d 条红 / %d 条没量到 / 共 %d 条）"
             % (gate, n_bad, n_skip, len(checks)))
        for row in rows:
            if row["status"] == "fail":
                emit("  ✗ %s %s" % (row["rule"], row["text"]))

    return 报告(gate, rc, lines, items, rows, extra)


def 从argv(默认, argv=None):
    """`--out <路径>`：原来各闸自己扫 argv，统一到这里。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    return argv[argv.index("--out") + 1] if "--out" in argv else 默认
