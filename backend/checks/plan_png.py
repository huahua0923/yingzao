# -*- coding: utf-8 -*-
"""CAD 速览图（`dxf_plan_fast/floorN.png`）**齐备且不陈旧** —— A10。

## 它替换的是什么

`check_a4` 里 CAD 那一件（`_ARTIFACTS` 的 `cad`）判的是**在不在**：
`any(dxf_plan_fast 下的 floorN.png)`。**一张都不剩**才算缺，其余一律算齐 ——
不判张数、不判新鲜度。于是下面两档在 A4 上**都是绿的**：

  · 6 层只有 5 张图（少的那张恰好是用户会去点的那一层）；
  · 图还是**上一版布局**渲染的（张数都对，内容全是错位的）。

A4 的职责是「五件产物在不在」，把它改成「齐不齐 / 陈不旧」会把**缺件**和**陈旧**
混成一句话 —— 那是本仓最忌讳的那类（两个不同的东西在屏幕上长得一样）。
所以：**A4 不动，这一条另立 A10，判的是同一个产物的另一件事。**

## 为什么必须有这条（c001 的现场）

2026-09-26 用户报「8140 上 `#/drawings/c001` 的 CAD 原图不对」。查下来那一栏
（`artifacts.py` 里 `CAD_DIR, CAD_LABEL = "dxf_plan_fast", "CAD 原图"`）**根本不是
CAD 原图**，是机器渲染的每层速览图。病根是一类**系统性缺口**：

  · 出图脚本 `_scratch/_gpu_png_batch.py` 读 `floors/floorN.json` 出图；
  · 但**出图这一步是带外手工跑的**，没有任何东西把 `floors/` 的重切与出图绑起来；
  · c001 在 2026-09-23 补了一层（`profile.json` 的注释里记着），`floors/` 于
    09-24 00:06~00:09 重切成 6 层，**而没人重出图** ⇒ 盘上留的还是旧布局的 5 张：
    `floor0.png` 是现在 F0+F1 两坨合在一起，`floor1..4.png` 是现在的 F2..F5
    （**整批错位一格**），F5 **从来没有过图**。
  · 全库扫下来 **33 / 95 栋**有同类病（4 栋尺寸级 + 29 栋墨迹级），已全部重出。

⇒ 结论：**「产物在不在」与「产物是不是用现在的输入算出来的」是两件事**，
而它们在没有这条判据时长得一模一样。

## 口径（本模块最要紧的一句）

层数**从 `floors/floorN.json` 数**：`for i in range(64)`，**遇到第一个缺号就停**
—— 与出图脚本 `prep()` 的枚举逐字同口径（`floors/` 里有编号空洞时，
出图脚本看得到哪几层，这里就必须看得到哪几层）。

**绝不读 `profile.json` 的 `floor_ys`。** 后者正是旧的只读审计器
（`_scratch/_plan_png_audit.py` ④「层数塌陷」那一条腿）瞎掉的地方：
`floor_plans` 制式的楼 `floor_ys` 是 `None` ⇒ **那条腿对它们从不下手**，
而屏幕上「没报」与「没问题」长得一样。
**制式无关的读数只有一个来源：`floors/` 目录本身。**
（`layout.floor_files` 故意不判连续性 —— 它的模块说明写着「那是各条检查自己的判据」，
所以这里的枚举自己写，路径仍走 `layout.building_dir` 的唯一契约。）

## 两条腿（为什么只有两条）

  ① **张数**：`floors/` 数到的层 vs `dxf_plan_fast/` 里的 `floorN.png`。
  ② **宽高比**：渲染器是「每层独立坐标框」⇒ `png 的高/宽` 必须等于该层线段 bbox
     的 `高/宽`。这是**内容**层面的判据，张数对得上时它也抓得住陈旧。

**故意不判 mtime**：按 mtime 判陈旧在本仓已被实测证伪（`check_a5` 的 docstring、
memory: delivery-glb-content-staleness：漏 28/48 栋），而且拷贝/还原会打乱它。
一个**只能当旁证**的判据写成 PASS/GAP，给出的是假绿和假红两种坏结局
（memory: verifier-needs-its-own-falsifier）——所以引擎里不放它。
`_scratch/_plan_png_stale.py` 里保留了它，那里标着「单独不判废」。

## 张数腿的**精确化**（别把这句读成「多加了一条判据」）

出图脚本对**线段为空的层不出图**（`prep()` 里 `if segs:` 那条闸门）。
所以「层数 N 却没 N 张图」要分开两种情况，它们在屏幕上完全同形：

  · **该出没出** ⇒ 缺件，GAP；          · **本来就不出**（那层的线段是空的）⇒ 不是缺陷。

第一版直接判 `n_floor != n_png`，会在「某层被重切成空」时**误报**。
现在判的是两张名单：
`missing = 线段非空、却没有图的层` / `orphan = 图的编号不在 floors 里的层`，
两个都非空任一 ⇒ GAP。**连续编号时它和 `n_floor != n_png` 完全等价**
（本仓实测：截至 2026-09-26，95 栋 456 层的编号**全部从 0 连续**，
线段为空的层 **0 个**）—— 这条精确化今天是空转的，留着是因为出图脚本的
那条闸门是真的（铁律 66：依赖关系要读源码，不许按同族推）。

## 自证（没有它，这把尺子跟恒真空壳长得一样）

    python -m backend.checks.plan_png --selftest

六条腿，两边都要过（铁律 26：只证「能绿」会漏掉「从不红」）：

  · 阳性 = **真盘上的 c001**（已修好：6 层 6 图，各层比例差 ≤ 6%）⇒ 必须 PASS。
  · 阴性甲 = 临时假楼，**3 层却只有 2 张图** ⇒ 必须 GAP，且点出缺的是第 2 层。
  · 阴性甲的反面 = 给同一个假楼**补上那张图**（比例也对）⇒ 必须**转成 PASS**。
    ★ 这一条是铁律 26 的「拆掉要验的那个变量」：它证明甲的红**来自那张缺图**，
      不是来自这个假楼的别的什么（端口 / 编号 / 读不到）。
  · 阴性乙 = 同一个假楼，png 的宽高比与层 json 的 bbox **差 3 倍** ⇒ 必须 GAP；
    再把 png 改回吻合 ⇒ 必须**转回 PASS**（否则「红」是这个假楼的常量）。
  · 阴性丙 = 同一个假楼，多一张**没有对应 json 的** `floor9.png` ⇒ 必须 GAP 且点名
    —— 与出图脚本 `drop_orphans()` 是同一条判据的两端（那边删、这边报）。
  · 腿⑤（不是状态，是**口径漂移守卫**）= 拿真盘 c001 的每一层，把本模块的 `segs_of`
    与 `_scratch/_gpu_png_batch.segs_of` **逐条比对**。导不进那个文件就明说**未执行**
    （铁律 46：不许把「没跑」印成旁白，也不许印成「过」）。

另有一条**用历史缺陷做的实测**（不属于 `--selftest`，是给报告用的）：
把 2026-09-26 修复前的 c001 现场在临时目录里复现（6 层 / 5 图 / F0 装的是别层的内容）
⇒ 本条**两条腿同时报红**（`missing=[5]` 且 `F0 比例差 1.9 倍`）。也就是说它抓的是
当年那个真实的报告缺陷，不是只在合成夹具上会红。

退出码：0 = 所有腿都过；2 = **尺子坏了**（与「发现有陈旧」不是一回事 ——
那条在这把尺子上是 `Status.GAP`，不是退出码）。
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import zlib
from pathlib import Path

from .findings import Finding, Report, Status
from .layout import building_dir

#: 检查编号与标题。注册表那边（`__init__.CHECK_REGISTRY`）另存一份元信息，
#: 两边都是**常量**、不各自往正文里抄一遍。
CHECK_ID = "A10"
TITLE = "CAD 速览图齐备且不陈旧"
MEASURE = "dxf_plan_fast 的张数（对 floors/floorN.json 数到的层）与宽高比（对该层线段 bbox）"

#: 比例偏差超过这个倍数才算「内容对不上」。
#: 实测噪声 ≤ 6%（c001 六个层，逐层 0.451/0.477、0.898/0.902、0.835/0.846 …），
#: 而真正的陈旧是 **4.3 倍**（c001 F0 修复前：json 0.451 vs png 1.952）——
#: 阈值取 1.35，两边都离得远。
ASPECT_TOL = 1.35
#: 线段少于这个数的层不参与比例判据（bbox 太瘦 ⇒ 比例不稳，宁可量不到）。
MIN_SEGS = 8
#: 与出图脚本的 `for i in range(64)` 同口径。
MAX_FLOORS = 64

_PNG_RE = re.compile(r"^floor(\d+)\.png$")


# ── 取段口径 ────────────────────────────────────────────────────────

def segs_of(floor: dict) -> list:
    """一层的线段 —— **逐字照抄 `_scratch/_gpu_png_batch.segs_of`**。

    ★ 为什么是「照抄」而不是「重新实现一个更干净的」：判据量的是**出图脚本
      手里那份线段**，不是「一层的几何应该是什么」。口径一旦分叉，
      量出来的就是另一件事（memory: fixture-shape-must-copy-real-artifact）。
      两边是否还一致由 `selftest` 的第 5 条腿**逐条比对**守着（见 `_selftest`）。
    """
    out = []
    for w in floor.get("walls") or []:
        pl = w.get("poly") or []
        cat = "parapet" if w.get("type") == "parapet" else "wall"
        for k in range(len(pl) - 1):
            out.append((pl[k][0], pl[k][1], pl[k + 1][0], pl[k + 1][1], cat))
    for d in floor.get("doors") or []:
        out.append((d["bx0"], d["by0"], d["bx1"], d["by1"], "door"))
    for r in floor.get("rooms") or []:
        pl = r.get("poly") or []
        for k in range(len(pl)):
            a, b = pl[k], pl[(k + 1) % len(pl)]
            out.append((a[0], a[1], b[0], b[1], "room"))
    return out


def bbox_of(segs) -> tuple | None:
    """线段集合的外框 `(宽, 高, 条数)`；空集或退化（宽或高为 0）回 `None`。"""
    if not segs:
        return None
    xs = [s[0] for s in segs] + [s[2] for s in segs]
    ys = [s[1] for s in segs] + [s[3] for s in segs]
    bw = max(xs) - min(xs)
    bh = max(ys) - min(ys)
    if bw <= 0 or bh <= 0:
        return None
    return (bw, bh, len(segs))


def png_size(p) -> tuple | None:
    """PNG 的 `(宽, 高)` —— **只读文件头**（1600×3124 的图解码要几十 MB，
    而这条判据要的只是比例）。不是 PNG / 截断 / 尺寸非正 都回 `None`。"""
    try:
        with open(p, "rb") as fh:
            h = fh.read(24)
    except OSError:
        return None
    if len(h) < 24 or h[:8] != b"\x89PNG\r\n\x1a\n" or h[12:16] != b"IHDR":
        return None
    w = int.from_bytes(h[16:20], "big")
    t = int.from_bytes(h[20:24], "big")
    if w <= 0 or t <= 0:
        return None
    return (w, t)


def aspect_ratio(want: float, got: float) -> float:
    """两边的比例差了几倍（≥1）。**纯函数，`selftest` 直接喂已知值考它。"""
    if want <= 0 or got <= 0:
        return 1.0
    return max(want, got) / min(want, got)


# ── 读数 ────────────────────────────────────────────────────────────

def floor_jsons(data_dir, name: str) -> list:
    """该栋的逐层 JSON `[(层号, Path)]` —— **遇到第一个缺号就停**。"""
    d = building_dir(data_dir, name) / "floors"
    out = []
    if not d.is_dir():
        return out
    for i in range(MAX_FLOORS):
        p = d / ("floor%d.json" % i)
        if not p.is_file():
            break
        out.append((i, p))
    return out


def pngs_of(data_dir, name: str) -> dict:
    """该栋 `dxf_plan_fast/` 里的速览图 `{层号: Path}`。目录不在就是空字典。

    只认 `floor<数字>.png` —— 出图脚本只会写这种名字，别的名字（`.bak`、
    中间产物）不该混进张数里（铁律 23：数产物之前先确定什么样算产物）。
    """
    d = building_dir(data_dir, name) / "dxf_plan_fast"
    out = {}
    if not d.is_dir():
        return out
    for p in d.iterdir():
        m = _PNG_RE.match(p.name)
        if m and p.is_file():
            out[int(m.group(1))] = p
    return out


def measure(data_dir, name: str) -> dict:
    """该栋的读数。**只读盘、不判状态**（判词在 `verdict` 里，只由这些数推出来）。"""
    r = {
        "name": name,
        "err": None,            # 非空 = 量不了（verdict 会翻成 UNAVAILABLE）
        "n_floor": 0,           # floors/ 数到的层数
        "n_png": 0,             # dxf_plan_fast/ 里的张数
        "n_seg_floor": 0,       # 线段非空的层数（= 出图脚本本该出图的张数）
        "missing": [],          # 线段非空却没有图的层号 ⇒ 缺件
        "orphan": [],           # 图号不在 floors 里的层号 ⇒ 孤儿图
        "empty_floors": [],     # 线段为空的层号（出图脚本本来就不为它出图）
        "png_no_seg": [],       # 有图但该层线段是空的（记进证据，不改状态，见 docstring）
        "aspect_bad": [],       # [(层号, json比例, png比例, 差几倍)]
        "aspect_skip": [],      # [(层号, 为什么没量)] —— 「没量」必须能被看见
        "floor_unreadable": [], # 读不动的 floor json
        "no_dir": False,        # 连 dxf_plan_fast/ 目录都没有
    }
    js = floor_jsons(data_dir, name)
    r["n_floor"] = len(js)
    if not js:
        r["err"] = ("没有 floors/floorN.json ⇒ **该有几张图量不到**"
                    "（这不是「没问题」）。见 A1/A4")
        return r

    pngs = pngs_of(data_dir, name)
    r["no_dir"] = not (building_dir(data_dir, name) / "dxf_plan_fast").is_dir()
    r["n_png"] = len(pngs)

    for i, jp in js:
        try:
            g = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            r["floor_unreadable"].append((i, "%s: %s" % (type(ex).__name__, ex)))
            continue
        if not isinstance(g, dict):
            r["floor_unreadable"].append((i, "不是对象"))
            continue
        segs = segs_of(g)
        if not segs:
            r["empty_floors"].append(i)
            if i in pngs:
                r["png_no_seg"].append(i)
            continue
        r["n_seg_floor"] += 1
        if i not in pngs:
            r["missing"].append(i)
            continue
        # ② 宽高比
        bb = bbox_of(segs)
        if bb is None:
            r["aspect_skip"].append((i, "该层 bbox 退化（宽或高为 0）"))
            continue
        if bb[2] < MIN_SEGS:
            r["aspect_skip"].append((i, "线段 %d 条 < MIN_SEGS %d" % (bb[2], MIN_SEGS)))
            continue
        sz = png_size(pngs[i])
        if sz is None:
            r["aspect_skip"].append((i, "png 文件头读不出宽高（截断/非 PNG）"))
            continue
        want = bb[1] / bb[0]
        got = sz[1] / sz[0]
        ratio = aspect_ratio(want, got)
        if ratio > ASPECT_TOL:
            r["aspect_bad"].append((i, round(want, 3), round(got, 3), round(ratio, 2)))

    r["orphan"] = sorted(k for k in pngs if k not in {i for i, _p in js})
    return r


def verdict(r: dict) -> tuple:
    """判词**只由数推出来**（铁律 44：判词不许写成字符串常量）。回 `(Status, 说明)`。"""
    if r["err"]:
        return Status.UNAVAILABLE, r["err"]
    if r["n_floor"] == 0:
        return Status.UNAVAILABLE, "floors 下没有 floorN.json ⇒ 该有几张图量不到"
    if r["n_seg_floor"] == 0 and not r["orphan"]:
        return Status.NOT_APPLICABLE, (
            "所有层（%d 层）的线段都是空的 ⇒ 出图脚本本来就不会为它们出图"
            "（`prep()` 里 `if segs:` 那条闸门）—— 没有可比的图" % r["n_floor"])

    bits = []
    if r["missing"]:
        bits.append("层数 %d vs 图 %d，**该出没出的层**：%s"
                    % (r["n_floor"], r["n_png"],
                       "、".join("F%d" % i for i in r["missing"][:8])
                       + ("…" if len(r["missing"]) > 8 else "")))
    if r["orphan"]:
        bits.append("**孤儿图**（编号不在 floors 里，出图脚本本不该有）：%s"
                    % "、".join("floor%d.png" % i for i in r["orphan"][:8]))
    if r["aspect_bad"]:
        f = r["aspect_bad"][0]
        bits.append("F%d 宽高比 json %.3f vs png %.3f（差 **%.1f 倍**）"
                    % (f[0], f[1], f[2], f[3])
                    + ("；共 %d 层对不上" % len(r["aspect_bad"])
                       if len(r["aspect_bad"]) > 1 else ""))
    # ★ 比例腿「一条都没量成」时不许给 PASS —— 「量不到」与「没问题」在屏幕上
    #   必须不是同一行字（findings.py 的模块说明；铁律 16）。
    n_need = len([1 for i in range(r["n_floor"])
                  if i not in r["empty_floors"]])
    n_skip = len(r["aspect_skip"] + r["floor_unreadable"])
    if not bits and n_skip and n_skip >= n_need:
        return Status.UNAVAILABLE, (
            "比例一列都没量成（%d 层全被跳过：%s）⇒ 图在、张数也对，"
            "但**内容那条腿没量到** —— 这不是「没问题」"
            % (n_skip, "；".join("%s" % w for _i, w in r["aspect_skip"][:3])
               + ("；%d 层 json 读不动" % len(r["floor_unreadable"])
                  if r["floor_unreadable"] else "")))

    if bits:
        return Status.GAP, "；".join(bits)
    ok = "层数 %d = 图 %d；%d 层的宽高比全部吻合（容差 %.2f 倍）" % (
        r["n_floor"], r["n_png"], r["n_floor"] - len(r["aspect_skip"])
        - len(r["floor_unreadable"]), ASPECT_TOL)
    if r["aspect_skip"] or r["floor_unreadable"]:
        ok += ("；另有 %d 层**没量到比例**（%s）"
               % (n_skip, "；".join(w for _i, w in r["aspect_skip"][:3])))
    return Status.PASS, ok


def _evidence(r: dict) -> dict:
    return {"n_floor": r["n_floor"], "n_png": r["n_png"],
            "n_seg_floor": r["n_seg_floor"], "missing": r["missing"],
            "orphan": r["orphan"], "empty_floors": r["empty_floors"],
            "png_no_seg": r["png_no_seg"],
            "aspect_bad": r["aspect_bad"], "aspect_skip": r["aspect_skip"],
            "floor_unreadable": r["floor_unreadable"]}


# ── 检查入口（形状与 builtin 的 check_aN 一致）───────────────────────

def check_a10(rep: Report, data_dir, name: str, **_kw) -> None:
    """A10：CAD 速览图齐备且不陈旧。详见模块 docstring。"""
    r = measure(data_dir, name)
    st, why = verdict(r)
    f = Finding(CHECK_ID, TITLE, st, why, measure=MEASURE,
                evidence=_evidence(r))
    if st == Status.UNAVAILABLE:
        f.blocked_by = why
    rep.add(f)


# ── 自证 ────────────────────────────────────────────────────────────

def _write_png(p: Path, w: int, h: int) -> None:
    """写一张**结构完整**的灰度 PNG（本判据只读它的 IHDR，但写全了
    往后真有人打开看图也不会坏）。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\x00" * w for _ in range(h))
    p.write_bytes(b"\x89PNG\r\n\x1a\n"
                  + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                  + chunk(b"IDAT", zlib.compress(raw, 1))
                  + chunk(b"IEND", b""))


#: 假楼用的墙线：一条 9 段的梳齿，bbox = 100 × 20（比例 0.200）。
#: 段数必须 ≥ MIN_SEGS，否则比例腿会被「线段太少」那条闸门跳过 ——
#: 那样这个阴性对照量到的就不是比例了（铁律 26）。
_COMB = [[0, 0], [0, 20], [25, 0], [25, 20], [50, 0], [50, 20],
         [75, 0], [75, 20], [100, 0], [100, 20]]


def _mk_fake(root: Path, name: str, floors: int) -> Path:
    """造一栋只带 `floors/floorN.json` 的假楼（每层都是那条 100×20 的梳齿）。"""
    b = root / "buildings" / name
    (b / "floors").mkdir(parents=True, exist_ok=True)
    (b / "dxf_plan_fast").mkdir(parents=True, exist_ok=True)
    for i in range(floors):
        (b / "floors" / ("floor%d.json" % i)).write_text(
            json.dumps({"floor": i, "walls": [{"type": "wall", "poly": _COMB}]},
                       ensure_ascii=False), encoding="utf-8")
    return b


def _run(data_dir, name: str):
    rep = Report(scope="building:%s" % name)
    check_a10(rep, data_dir, name)
    return rep.findings[0]


def _selftest(data_dir=None) -> int:
    """证明这把尺子**会红也会绿**。回 0 = 四条腿全过；2 = 尺子坏了。"""
    import shutil
    import tempfile

    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    print("==")
    print("A10 --selftest：阳性（真盘 c001）+ 阴性（假楼，两条腿各一条 + 一条反面）")
    print("==")
    rc = 0

    # ── 腿①：阳性对照 —— 真盘上的 c001（已修好）必须 PASS ────────────
    r = measure(data_dir, "c001")
    st, why = verdict(r)
    if r["err"]:
        print("  ✗ 阳性对照**未执行**：读不到 %s 的 c001（%s）"
              % (data_dir, r["err"]))
        print("    ⇒ 「没验」不是「验过了」（铁律 76）：这次没资格说尺子有分辨力")
        rc = 2
    else:
        print("  阳性 c001：层 %d / 图 %d / 线段非空的层 %d"
              % (r["n_floor"], r["n_png"], r["n_seg_floor"]))
        print("            漏图 %s · 孤儿图 %s · 比例对不上 %s · 比例没量到 %s"
              % (r["missing"], r["orphan"], r["aspect_bad"], r["aspect_skip"]))
        if st != Status.PASS:
            print("  ✗ 阳性对照没过：c001 是**已修好**的楼（6 层 6 图），"
                  "这里却判成 %s —— %s" % (st.value, why))
            rc = 2
        else:
            print("  ✓ 阳性对照：c001 判 %s（%s）" % (st.value, why))

    # ── 腿②③④：阴性对照用**临时假楼**，不碰真盘 ────────────────────
    tmp = Path(tempfile.mkdtemp(prefix="gym3d_a10_"))
    try:
        # 腿②：3 层却只有 2 张图 ⇒ 必须 GAP，且缺的是 F2
        b = _mk_fake(tmp, "zz_a10_short", floors=3)
        _write_png(b / "dxf_plan_fast" / "floor0.png", 100, 20)
        _write_png(b / "dxf_plan_fast" / "floor1.png", 100, 20)
        f = _run(tmp, "zz_a10_short")
        if f.status != Status.GAP or f.evidence.get("missing") != [2]:
            print("  ✗ 阴性甲没过：3 层 2 图应判 GAP 且 missing=[2]，"
                  "实际 %s / missing=%s —— %s"
                  % (f.status.value, f.evidence.get("missing"), f.detail))
            rc = 2
        else:
            print("  ✓ 阴性甲：3 层 2 图 → GAP，点出缺的是 F%s（%s）"
                  % (f.evidence["missing"], f.detail))

        # 腿③（反面）：把那张**缺的图补上** ⇒ 必须转成 PASS。
        #   ★ 这一条是铁律 26 的「拆掉要验的那个变量」：它证明甲的红来自那张缺图，
        #     不是来自这个假楼的别的什么（编号 / 读不到 / 端口）。
        _write_png(b / "dxf_plan_fast" / "floor2.png", 100, 20)
        f2 = _run(tmp, "zz_a10_short")
        if f2.status != Status.PASS:
            print("  ✗ 反面没过：补上第 3 张图后应转 PASS，实际 %s —— %s"
                  % (f2.status.value, f2.detail))
            rc = 2
        else:
            print("  ✓ 反面（拆掉变量）：补上 floor2.png → %s（%s）"
                  % (f2.status.value, f2.detail))

        # 腿④：同一栋楼，把 png 的宽高比改到差 3 倍 ⇒ 必须 GAP 且点名 F0
        #   层 json 的 bbox 是 100×20（比例 0.200），png 给 100×60（比例 0.600）
        #   ⇒ 差 3.00 倍 > ASPECT_TOL 1.35。
        _write_png(b / "dxf_plan_fast" / "floor0.png", 100, 60)
        f3 = _run(tmp, "zz_a10_short")
        bad = f3.evidence.get("aspect_bad") or []
        if f3.status != Status.GAP or [x[0] for x in bad] != [0]:
            print("  ✗ 阴性乙没过：比例差 3 倍应判 GAP 且点名 F0，实际 %s / %s —— %s"
                  % (f3.status.value, bad, f3.detail))
            rc = 2
        else:
            print("  ✓ 阴性乙：F0 比例差 %.1f 倍 → GAP（%s）"
                  % (bad[0][3], f3.detail))

        # 腿④的反面：把 png 改回吻合 ⇒ 必须转回 PASS（否则「红」是这个假楼的常量）
        _write_png(b / "dxf_plan_fast" / "floor0.png", 100, 20)
        f4 = _run(tmp, "zz_a10_short")
        if f4.status != Status.PASS:
            print("  ✗ 阴性乙的反面没过：比例改回吻合后应转 PASS，实际 %s —— %s"
                  % (f4.status.value, f4.detail))
            rc = 2
        else:
            print("  ✓ 阴性乙的反面：比例改回吻合 → %s" % f4.status.value)

        # 腿⑥：孤儿图 —— 图的编号没有对应的 `floorN.json` ⇒ 必须 GAP 且点名。
        #   ★ 这一条与出图脚本 `_scratch/_gpu_png_batch.drop_orphans()` 是同一条判据的
        #     两端：那边负责**删**，这边负责在删漏了/没删时报出来。
        _write_png(b / "dxf_plan_fast" / "floor9.png", 100, 20)
        f5 = _run(tmp, "zz_a10_short")
        if f5.status != Status.GAP or f5.evidence.get("orphan") != [9]:
            print("  ✗ 阴性丙没过：多出一张 floor9.png（无对应 json）应判 GAP 且 "
                  "orphan=[9]，实际 %s / orphan=%s —— %s"
                  % (f5.status.value, f5.evidence.get("orphan"), f5.detail))
            rc = 2
        else:
            print("  ✓ 阴性丙：孤儿图 floor9.png（无对应 json）→ GAP（%s）" % f5.detail)
        os.remove(b / "dxf_plan_fast" / "floor9.png")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ── 腿⑤：取段口径与**真出图脚本**逐条比对（只比一条已知为真的样本）──
    #   ★ 这是防「照抄的那份抄歪了 / 上游改了」的漂移守卫。导不进来就明说
    #     **未执行**（铁律 46：不许把「没跑」印成旁白，也不许印成「过」）。
    try:
        import importlib.util
        root = Path(__file__).resolve().parents[2]
        src = root / "_scratch" / "_gpu_png_batch.py"
        spec = importlib.util.spec_from_file_location("_a10_gpu_png_batch", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as ex:                                   # noqa: BLE001
        print("  ~ 腿⑤**未执行**：导不进 %s（%s: %s）⇒ 取段口径这次没被比对过"
              % ("_scratch/_gpu_png_batch.py", type(ex).__name__, ex))
    else:
        js = floor_jsons(data_dir, "c001")
        n_cmp = n_bad = 0
        for i, jp in js:
            g = json.loads(jp.read_text(encoding="utf-8"))
            mine, theirs = segs_of(g), mod.segs_of(g)
            n_cmp += 1
            if mine != theirs:
                n_bad += 1
                print("  ✗ 腿⑤：F%d 的线段与出图脚本不一致（我 %d 条 / 它 %d 条）"
                      % (i, len(mine), len(theirs)))
        if n_bad == 0 and n_cmp:
            print("  ✓ 腿⑤ 取段口径：c001 的 %d 层逐条相同（与 `_gpu_png_batch.segs_of`）"
                  % n_cmp)
        elif n_bad == 0:
            print("  ~ 腿⑤**未执行**：c001 没有可比的层")
        else:
            rc = 2

    print("==  ⇒ %s ==" % ("所有腿都过：这把尺子会红也会绿"
                           if rc == 0 else "尺子坏了，它出的数一律不算数"))
    return rc


def main() -> int:
    args = sys.argv[1:]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    bad = [a for a in args if a.startswith("-") and a != "--selftest"]
    if bad:
        # 铁律 9：不认识的开关一律退出，**不许忽略然后按默认全量跑**。
        print("不认识的开关：%s\n可用：--selftest 或 楼名 …" % "、".join(bad))
        return 2
    if "--selftest" in args:
        return _selftest()

    data_dir = Path(__file__).resolve().parents[2] / "data"
    names = [a for a in args if not a.startswith("-")]
    if not names:
        base = data_dir / "buildings"
        names = sorted(d.name for d in base.iterdir() if d.is_dir()) \
            if base.is_dir() else []
    print("A10 %s（%d 栋；口径：%s）" % (TITLE, len(names), MEASURE))
    n_bad = 0
    for n in names:
        f = _run(data_dir, n)
        if f.status in (Status.GAP, Status.WATCH, Status.UNAVAILABLE):
            n_bad += 1
        print("  [%-11s] %-7s %s" % (f.status.value.upper(), n, f.detail))
    print("不在 PASS 的：%d / %d" % (n_bad, len(names)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
