# -*- coding: utf-8 -*-
r"""严格 JSON 落盘 —— 让「没量到」写成 `null`，不让它变成裸 `NaN`。

为什么要有它（铁律 123 的原文症状，2026-10-12 在本仓实测到）：
  `gates/_out/J-09.2-A1.json` 里有 **4 个裸 `NaN`**（`rows[*].lcs[*]`）。
  来源是**有意的**：`a1/generic_wall.py:257` 对「一条墙线取样点都没有」的图幅
  **故意**返回 NaN，因为「没量到」≠「量到 0」（0.0 会把好件报成坏件）。
  **判据的设计意图是对的，错的是编码**：

    ① Python 的 `json.loads` **默认吃** `NaN`（`allow_nan=True`）⇒ 我自己读得回来，
       **量不出自己写的件是坏件**；
    ② 浏览器 `JSON.parse` / Node / Go / Rust **一律抛错** ⇒ 前端白屏。
       实测：`node -e "JSON.parse(...)"` 在 `J-09.2-A1.json` 上报
       `Unexpected token 'N' ... is not valid JSON`。
  ⇒ **不可比格一律写 `None`**（本模块 `sanitize`），落盘后再用**另一实现**读一遍
    （`tools/lint_json_strict.py`）。

用法（调用方）::

    import jsonstrict
    jsonstrict.dump(payload, "gates/_out/xxx.json")     # 字节层写盘 + allow_nan=False
"""
import json
import math
import os

__all__ = ["sanitize", "dump", "dumps", "count_nonfinite"]


def sanitize(o):
    """逐层**重建**一份，把不可比的浮点（`nan` / `±inf`）换成 `None`。

    ★ 不改原对象（不可变约定）—— 返回新结构，调用方手里那份读数不受影响。
    ★ `isinstance` 也收 `np.float64` 这类 **float 子类**（它们会自己进 JSON）；
      `np.float32` 不是 float 子类，本函数**认不出**它 —— 但那种值本来就
      过不了 `json` 的序列化器，会在 `dump` 当场抛，不会静默落成坏件。
    """
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    return o


def dumps(o, **kw):
    """`json.dumps` 的严格版：先 `sanitize`，再 `allow_nan=False` 兜底。"""
    kw.setdefault("ensure_ascii", False)
    kw.setdefault("indent", 1)
    # ★ 这一句是**声明**不是**守卫**：`sanitize` 已经把所有 float 实例（含 `np.float64`
    #   这类子类）都收了 ⇒ 走 `dump()` 的正路它**到不了**。真正有牙的是 `dump()` 里的
    #   回读校验（自测第 ④ 档）。留着它是为了：谁绕过 `sanitize` 直接调 `dumps()`，
    #   也不会静默写出裸常量。★ 别再为它编一档「会抛」的自测 —— 编得出的是假档。
    kw["allow_nan"] = False
    return json.dumps(sanitize(o), **kw)


def _reject_const(name):
    """严格读法的回调：**只在** NaN/Infinity/-Infinity 三处被调用。"""
    raise ValueError("落盘的件里有裸 %s —— 严格解析器读不回" % name)


def dump(o, path):
    """写盘 + **当场回读校验**。返回 (写出的字节数, 洗掉的不可比格数)。

    ★ **字节层**写盘（铁律 79：文本模式在 Windows 上把 LF 翻成 CRLF，+1 字节/行）。
    ★ 回读是铁律 123 那句「落盘后**用另一解析器再读一遍**」的落实 ——
      用 `parse_constant` 当严格开关（Python 默认 `allow_nan=True` 会**吃**掉裸 NaN，
      所以「写的人自己读得回」证明不了什么）。回读失败 ⇒ 抛，**不留一个假绿的件**。

    返回值第 1 项给日志用；第 2 项是**原对象里不可比格的个数**（= 洗掉并写成 `null` 的格数）。
    ★ 别改成「数洗完那份里的 `None`」—— 那会把**本来就该是 `null` 的格**（如
      `cov_min: None` = 一格都没量到）也算进去，印出去是个**看着像结论、其实口径不对**的数
      （2026-10-12 本仓当场犯过：数了原对象 ⇒ 恒 0）。
    """
    n = count_nonfinite(o)          # ★ 在洗之前数 —— 洗完之后原对象没被改，但数法必须对口径
    clean = sanitize(o)
    text = dumps(clean) + "\n"
    data = text.encode("utf-8")
    p = os.path.dirname(path)
    if p:
        os.makedirs(p, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    with open(path, "rb") as f:
        back = f.read().decode("utf-8")
    json.loads(back, parse_constant=_reject_const)      # ★ 回读校验，失败即抛
    if "\r\n" in back:
        raise ValueError("写出的 %s 里出现了 CRLF —— 字节层写盘被改回去了？" % path)
    return len(data), n


def count_nonfinite(o):
    """数一遍结构里有多少个不可比的浮点（`nan` / `±inf`）叶子。"""
    if isinstance(o, float):
        return 0 if math.isfinite(o) else 1
    if isinstance(o, dict):
        return sum(count_nonfinite(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return sum(count_nonfinite(v) for v in o)
    return 0


def _selftest():
    """正对照（铁律 137/183）：喂**构造好的**样本，验每一道守卫真的会响。

    ★ 判据是「与期望相符」—— 不是「跑通了」。夹具写系统临时目录，不落本仓。
    """
    import os as _os
    import tempfile
    d = tempfile.mkdtemp(prefix="jsonstrict_selftest_")
    nbad = 0

    def case(ok, what, detail=""):
        nonlocal nbad
        nbad += 0 if ok else 1
        print("  %s %-34s %s" % ("✓" if ok else "✗ ← 守卫不对", what, detail))

    # ① 实翻车那一格的形状：nan 必须变成 null，且回读得住
    p = _os.path.join(d, "nan.json")
    nb, n = dump({"lcs": [100.0, float("nan"), float("inf"), float("-inf")]}, p)
    back = open(p, "rb").read().decode("utf-8")
    case(n == 3, "① 三个不可比格都数到了", "数到 %d（期望 3）" % n)
    case(back.count("null") == 3 and "NaN" not in back and "Infinity" not in back,
         "① 都写成了 null，没留裸常量", back.replace("\n", " ")[:52])
    case("\r\n" not in back, "① 字节层写盘（LF，不是 CRLF）", "CRLF 数 = %d" % back.count("\r\n"))
    case(json.loads(back) == {"lcs": [100.0, None, None, None]},
         "① 严格读法能读回、值与期望相等", repr(json.loads(back)))

    # ② ★ 钉住我当场犯过的那个计数错：`None` 本来就在的格**不许**算进「洗掉几格」
    p2 = _os.path.join(d, "count.json")
    _nb, n2 = dump({"a": float("nan"), "b": None, "c": [1.0, None, float("nan")]}, p2)
    case(n2 == 2, "② 计数只算不可比格（None 不算）",
         "数到 %d（期望 2：一个 nan + 一个列表里的 nan；那俩 null 是本来就有的）" % n2)

    # ③ 序列化失败时**不许留半成品**（半写出的 json 就是个假绿的件）
    #    ★ 第一版这一档想测 `allow_nan=False` 那条兜底，用的是 `class Sneaky(float)` ——
    #      而 `Sneaky` **就是** float 的子类、`sanitize` 认得它 ⇒ 那条通路根本走不到，
    #      测了个测不出东西的档（自己给自己发绿灯）。改成测**真的**会发生的那种失败。
    p3 = _os.path.join(d, "nofile.json")
    try:
        dump({"bad": {1, 2, 3}}, p3)             # set 不是 JSON 类型 ⇒ 必须抛
        case(False, "③ 序列化失败必须抛", "★ 没抛")
    except TypeError as e:
        case(not _os.path.exists(p3), "③ 失败时不留半成品文件",
             "抛了 %s；文件%s" % (type(e).__name__, "没生成 ✓" if not _os.path.exists(p3) else "★ 还在"))

    # ④ 回读校验真的在跑：把 dump 出的件改坏，回读那一关必须发现
    p3 = _os.path.join(d, "tamper.json")
    dump({"y": [1.0, float("nan")]}, p3)
    with open(p3, "wb") as f:                       # 把 null 换回裸 NaN
        f.write(open(p3, "rb").read().replace(b"null", b"NaN"))
    bad = open(p3, "rb").read().decode("utf-8")
    try:
        json.loads(bad, parse_constant=_reject_const)
        case(False, "④ 回读校验有牙", "★ 裸 NaN 竟然读过去了")
    except ValueError:
        case(True, "④ 回读校验有牙", "裸 NaN 被回读拦下")

    print("\n自测：%d 档不通过（期望 0）⇒ %s"
          % (nbad, "本件有牙" if not nbad else "**自身有问题，别再拿它落盘**"))
    return 1 if nbad else 0


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv:
        _sys.exit(_selftest())
    print(__doc__)
    _sys.exit(0)
