# -*- coding: utf-8 -*-
r"""判据统一出口 —— **一栋楼 × 一条判据** 一份结构化读数（工作台矩阵的原料）。

为什么要有它（2026-10-19，用户「所有的参数都能看到和修改，而不是在黑盒中运行，
每个建筑的生成都是有依据的，有错误可以直接在页面上指出修改，从哪个方向修改」）：
  41 条判据原来各自：① 把 **c006 的绝对路径**写在文件头；② 只落 `run.txt`（散文）。
  ⇒ 别的楼量不了（矩阵是空的），页面也没法把红点定位成「哪层 / 哪块 / 往哪改」。
  本文件只做四件事，**不再有第五件**：
    ① 由 bid 现算这栋楼的件路径 —— 只认 `building.root_for()`，不许第二份；
    ② 定义 verdict 的字段（schema 见下）；
    ③ 规则号 → 修正方向（五类枚举，声明在 `FIX_RULES` 这一张表里）；
    ④ 落盘 `gates/_out/<闸>.<楼>.json` + `.run.txt`。

schema（`"schema": "cdut3d-verdict/1"`）::

    {
      "schema": "cdut3d-verdict/1",
      "gate": "J-10.8-00",
      "bid": "c006",
      "pass": false,              # 三态：true / false / null(=没量到)
      "rc": 1,
      "measured_at": "2026-10-19T00:00:00",
      "files": {"contours": "...", "index": "...", ...},
      "counts": {"red": 3, "unmeasured": 0},
      "items": [
        {"rule": "⑪", "status": "fail",
         "text": "3层 LINTEL 最短边 5.374 mm < 6.250",
         "fix": "既有已知红", "floor": "3层", "evidence": "contours/3层.json"}
      ],
      "blind": ["..."],
      "run_txt": "gates/_out/J-10.8-00.c006.run.txt"
    }

★ 铁律 199：「没量到」不许写成 0 / pass。`pass` 用 `None` 单独表达。
★ 铁律 018/174：路径只有一个估计器（`paths()`），闸里不许再拼一次 `rebuild/06_su/...`。
"""
from __future__ import annotations

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)                       # …\cdut3d
TOOLS = os.path.join(CDUT, "rebuild", "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

OUT = os.path.join(HERE, "_out")

# ★ 2026-10-19：矩阵用 `-I` 起子进程抓 stdout。`-I` 隐含 `-E` ⇒ **PYTHONIOENCODING 被忽略**，
#   管道里按 GBK 编码 ⇒ 第一行 `✗` 就 `UnicodeEncodeError`，闸崩在落 verdict 之前，
#   矩阵看到的是「没量到 rc=1」——症状与被测楼有问题**同形**（铁律 199）。
#   在唯一入口把它钉死成 utf-8：所有经 `_verdict` 的闸一次修完。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# 修正方向 —— **只有这五类**。页面上按这五类给下一步动作，不许临时造第六类。
FIX = ("改档案字段", "补足迹声明", "改源图", "改算法", "既有已知红")

# 规则号 → 修正方向。键是闸名；值是 {规则号: FIX 里的某一项}。
# ★ 这里写的是**这一类红通常该往哪改**；闸自己的参数/证据仍以 run.txt 为准。
FIX_RULES = {
    "J-10.8-00": {
        "①": "改算法",      # 件缺 ⇒ 那一步没跑成
        "②": "改算法",      # index 过期 ⇒ 重跑轮廓
        "③": "改算法",      # layer 不在枚举
        "④": "改算法",      # z 越界
        "⑤": "改算法",      # h 越界
        "⑥": "改算法",      # holes 非空
        "⑦": "改算法",      # 非有限数
        "⑧": "改算法",      # 重复点
        "⑨": "改算法",      # 互异点不足
        "⑩": "改算法",      # 自交
        "⑪": "既有已知红",  # 最短边/面积（有已声明的残差）
        "⑫": "改算法",      # 同类重叠
        "⑬": "改源图",      # 柱条数对不上源图 ⇒ 先看 keep_layers 与源图
        "⑮": "改算法",      # DXF 重读条数
        "⑯": "改档案字段",  # 闸阈值 vs 参数.json
        "⑰": "改算法",      # 正对照失灵 ⇒ 先修判据，不拿模型顶锅
    },
    "J-10.8-01": {
        "①": "改算法",
        "②": "改档案字段",  # 总高 vs top_m（档案/参数）
        "③": "改算法",      # 逐层 z 区间
        "④": "改源图",      # 墙足迹面积 vs 识别栅格
        "⑤": "改算法",      # 水密
        "⑥": "改算法",      # 楼板
        "⑦": "改源图",      # 门扇块
        "⑧": "改档案字段",  # 顶部附属声明
        "⑨": "改算法",      # 竖井
        "⑩": "补足迹声明",  # 退台屋面（mid_roofs / roof_step）
        "⑪": "改档案字段",  # 「无窗」声明过期
        "⑫": "改算法",      # 出件朝向
    },
    "J-10.9-07": {
        "①": "改算法",      # A1 ≠ A2（两个生成器的类集不一致）
        "②": "改算法",      # 六处点名
        "③": "改算法",      # 交付件里没有该类
    },
}
# 只报不判的规则（不改退出码）—— 矩阵里标 skip，不当红。
SKIP_RULES = {
    "J-10.8-00": {"⑭"},
    "J-10.9-07": {"⑥"},
}

# J-10.8-04（叠加比对）：两条红都指向「生成件与原始图对不上」。
#   ② 贴源：生成件多出来的边 ⇒ 识别/建墙那一步产出了图上没有的东西（改算法）。
#   ③ 覆盖：原始图上的线没盖上 ⇒ 可能漏识别，也可能原始件本身不干净 —— 先按改算法查。
FIX_RULES["J-10.8-04"] = {"②": "改算法", "③": "改算法"}


def bid_from(argv=None):
    """从 `--bid X` 取楼栋；没有就听 `CDUT_BUILDING`；都没有 = c006（历史默认）。

    ★ 用 parse_known_args：闸自己的 argparse 参数不会被这里吃掉。
    """
    import argparse
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--bid", default=os.environ.get("CDUT_BUILDING") or "c006")
    a, _ = ap.parse_known_args(sys.argv[1:] if argv is None else argv)
    return a.bid


def paths(bid=None):
    """这栋楼的件路径（**唯一估计器**）。缺的件不在这里造假路径，调用方自己判在不在。"""
    import building as B
    b = bid or bid_from()
    root = B.root_for(b)
    name = B.out_name(b)
    su = os.path.join(root, "06_su")
    su_obj = os.path.join(su, name + "_su.obj")
    fc_obj = os.path.join(su, name + "_fc.obj")
    # 交付件必须跟**已发布包**同源；SU 遗留件可能比当前包更旧。
    source_obj = None
    try:
        with open(os.path.join(CDUT, "packs", "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        row = next((x for x in (idx.get("packs") or []) if x.get("id") == b), None)
        src = ((row or {}).get("floors") or {}).get("source_model") or ""
        if src.lower().endswith(".glb"):
            candidate = os.path.join(CDUT, src[:-4] + ".obj")
            if os.path.isfile(candidate):
                source_obj = candidate
    except (OSError, ValueError):
        source_obj = None
    return {
        "bid": b,
        "root": root,
        "name": name,
        "raw": os.path.join(root, "01_cad", "raw"),
        "build": os.path.join(root, "05_build"),
        "build_json": os.path.join(root, "05_build", "build.json"),
        "glb": os.path.join(root, "05_build", name + "_white.glb"),
        "obj": os.path.join(root, "05_build", name + "_white.obj"),
        "contours": os.path.join(su, "contours"),
        "index": os.path.join(su, "contours", "index.json"),
        "fc_obj": fc_obj,
        "su_obj": su_obj,
        # 交付件：有 SU 出件就用它（c005/c006），否则用 FreeCAD 出件（其余楼）。
        # ★ 量的是哪一件必须写进 verdict.files，别让读者猜。
        "deliver": source_obj or (fc_obj if os.path.exists(fc_obj) else su_obj),
        # 参数与对照是**全校共用**的，不随楼变。
        "params": os.path.join(CDUT, "rebuild", "构件库", "参数.json"),
        "duibi": os.path.join(CDUT, "rebuild", "构件库", "对照.json"),
        "out": OUT,
    }


def floors(bid=None):
    """本楼层的层名表（地下在前，自下而上）—— 闸不许再写死 1..11。"""
    import building as B
    pr = B.profile(bid or bid_from())
    f = list(pr.get("floor_names") or [])
    base = pr.get("basement")
    return ([base] if base else []) + f


def fix_of(gate, rule):
    return FIX_RULES.get(gate, {}).get(rule)


def is_skip(gate, rule):
    return rule in SKIP_RULES.get(gate, set())


def parse_items(gate, lines):
    """把闸的散文行折成条目。**只认行首的规则号**（闸自己的失败串就是这么开头的）。

    红串 = 以规则号开头的行；「没量到 / SKIP」行单列；其余判 pass 的不进 items
    （矩阵的一格用 `pass` 说话，items 只解释红与没量到）。
    """
    import re
    # ★ 2026-10-19：闸把红串印成 `     - ⑪ …`（缩进 + 短横）⇒ 前缀要允许。
    pat = re.compile(r"^\s*(?:-\s*)?([①-⑳])\s*(.+)$")
    items = []
    for ln in lines:
        s = ln.rstrip()
        m = pat.match(s)
        if m:
            rule, text = m.group(1), m.group(2).strip()
            if is_skip(gate, rule):
                st = "skip"
            else:
                st = "fail"
            items.append({"rule": rule, "status": st, "text": text,
                          "fix": fix_of(gate, rule), "floor": _floor_of(text),
                          "evidence": ""})
            continue
        if ("没量到" in s or s.lstrip().startswith("SKIP")) and s.strip():
            items.append({"rule": "", "status": "unmeasured", "text": s.strip(),
                          "fix": "", "floor": _floor_of(s), "evidence": ""})
    return items


def _floor_of(text):
    import re
    m = re.search(r"(地下\d+层|\d+层)", text)
    return m.group(1) if m else ""


# 没有规则号前缀的失败串，按关键词归方向。**只收能分辨的**，认不出就留空（不许瞎猜）。
FIX_KEYWORDS = (
    ("总高", "改档案字段"),
    ("主体顶", "改档案字段"),
    ("窗图层", "改档案字段"),
    ("z_measured", "改算法"),
    ("z_by_class", "改算法"),
    ("z_extra", "改算法"),
    ("楼板", "改算法"),
    ("竖井", "改算法"),
    ("朝向", "改算法"),
    ("门扇", "改源图"),
    ("面积", "改源图"),
    ("退台", "补足迹声明"),
)
_RULES = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def infer_fix(gate, text):
    """失败串 → 修正方向。先认规则号，再认关键词；都认不出 = 空串（页面显示「待判」）。"""
    rule = text.strip()[:1]
    if rule in _RULES:
        f = fix_of(gate, rule)
        if f:
            return f
    for kw, f in FIX_KEYWORDS:
        if kw in text:
            return f
    return ""


def items_from_strings(gate, strs):
    """闸自己的失败串表 → items。★ 这是 `J-10.8-01` 这类把 `fails` 攒在列表里的闸的入口。"""
    out = []
    for s in strs or []:
        s = str(s).strip()
        if not s:
            continue
        rule = s[:1] if s[:1] in _RULES else ""
        out.append({"rule": rule, "status": "fail", "text": s,
                    "fix": infer_fix(gate, s), "floor": _floor_of(s), "evidence": ""})
    return out


def items_unmeasured(gate, strs):
    """闸自己的「没量到」串表 → items（status=unmeasured）。★ 与 `items_from_strings` 配对：
    「量到不对」和「没量到」必须分成两张表，不许都塞进 `fails` 里（铁律 199）。"""
    out = []
    for s in strs or []:
        s = str(s).strip()
        if not s:
            continue
        rule = s[:1] if s[:1] in _RULES else ""
        out.append({"rule": rule, "status": "unmeasured", "text": s,
                    "fix": "", "floor": _floor_of(s), "evidence": ""})
    return out


def emit(gate, bid, pass_, rc, lines, blind=(), files=None, extra=None, items=None):
    """落 `_out/<闸>.<楼>.json` + `.run.txt`，并（c006 时）同步写老文件名。

    ★ 老文件名是给既有文档/脚本看的；矩阵只读**带楼栋名**的那一份。
    ★ `items` 传了就**用传的**（闸自己有 `fails` 列表时比从散文里再解析一遍可靠 —— 铁律 174：
      同一个量不许有两个估计器）。
    """
    os.makedirs(OUT, exist_ok=True)
    items = list(items) if items is not None else parse_items(gate, lines)
    red = sum(1 for x in items if x["status"] == "fail")
    un = sum(1 for x in items if x["status"] == "unmeasured")
    run_txt = os.path.join(OUT, "%s.%s.run.txt" % (gate, bid))
    with open(run_txt, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    rec = {
        "schema": "cdut3d-verdict/1",
        "gate": gate,
        "bid": bid,
        "pass": pass_,
        "rc": rc,
        "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": files or {},
        "counts": {"red": red, "unmeasured": un},
        "items": items,
        "blind": list(blind),
        "run_txt": run_txt,
    }
    if extra:
        rec.update(extra)
    p = os.path.join(OUT, "%s.%s.json" % (gate, bid))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    if (bid or "c006") == "c006":
        with open(os.path.join(OUT, "%s.json" % gate), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        with open(os.path.join(OUT, "%s.run.txt" % gate), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    return rec
