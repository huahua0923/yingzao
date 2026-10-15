# -*- coding: utf-8 -*-
r"""A1：**梯（踏步）这一类构件**在通用链里的入口 —— 收锚 + 剔踏步，判据本身仍只有一处真源。

为什么单独一个模块（不是把逻辑写进 `generic_wall.py`）：
  ① 判据（`gates/J-09.2-A1d_treads.py`）要能**独立**调用这一层，才谈得上「量交付件本身」。
  ② 「在哪收锚」是一个**可测量的选择**（见下），与「踏步长什么样」不是一件事 —— 后者一律回
     `libs3d/c006/treadlib.py`（冻结基线、唯一真源），本模块**一个字几何规则都不重写**。

★ 来源与身份（这一行是怎么回来的）：
  冻结基线在**四处**都剔踏步 —— 建侧 `build6.py:191` / `build7.py:123` / `build8.py:169`，
  打分侧 `score6.py:112` / `score8.py:149`。`score6.py` 首行原话：「**参照侧也剔除踏步线**
  （与 build6 共用 treadlib，同一批复判据）」⇒ 模型侧与参照侧**必须是同一批线**。
  而 `a1/generic_wall.py` 自称「打分侧逐行照抄 score8.py」，却**只抄了 import、没抄那行调用**
  （铁律 17：写好的函数不等于被调用的函数）⇒ 通用化时丢了「剔踏步」，楼梯间里 270 mm 一道的
  踏步线被 `wire()` 当成墙身配起来。

★ 实测（C006，`gates/J-09.2-A1d_treads.py` 与 `_scratch/probe_tread.py` 同口径，精确并集）：
  墙输入含踏步 足迹 **4472.648 m²** → 剔后 **3765.317 m²**，Δ=**707.331 m²（15.81%）**，逐图幅 12/12 全正。

★ 「锚」的现实（全库实测，决定了这条判据在几栋上有牙）：
  · 锚 = 人写的 `上`/`下`。**全库只有 4 栋有**：C006（136，墙层内）/ C074（17）/ C113（5）
    / **C105（178，全在非墙层）**。
  · 冻结基线 `build8.py:160`、`score8.py:53` 都**只在墙层分支里**收锚 ⇒ 与它对齐是**默认口径**；
    `layers=None`（全层）是**放宽口径**，实测 C105 由 0 组变 125 组/1397 条 —— 那是**对基线的偏离**，
    故**不默认启用**，只由判据报数（盲区②）。
  · 房间台账那条路已实测死掉：全库用途层（`8房间用途` 等）里「楼梯」**0 条**（105 栋）。

★ 盲区（本模块不解决，只声明）：无锚的栋（101/105）几何候选一大堆却**无法确证**是楼梯
  （C001/C009/C011 无锚候选 79/143/66 组）⇒ 那里既不剔也不判。见判据的盲区①。
"""
import sys
import os

LIBS3D = r"D:\项目\libs3d\c006"
if LIBS3D not in sys.path:
    sys.path.insert(0, LIBS3D)
import treadlib as TL               # noqa: E402  ★ 冻结基线：唯一真源

# ★ 与 `generic_wall.WALL_LAYERS` 同名单（**默认收锚的层**，= 冻结基线口径）
ANCHOR_LAYERS = ("4.2墙体", "4墙体", "4.3封墙", "4.3新封墙")
LABEL_TXT = ("上", "下")

#: 最近一次 `drop_from()` 的读数（给链的日志与判据读；**不改返回值元数**，免得动 8 个调用点）
LAST = {}


def collect_labels(msp, layers=ANCHOR_LAYERS):
    """收 `上`/`下` 注释点。

    `layers` 给层名元组 ⇒ **只在那些层里收**（默认 = 冻结基线口径，`build8:160` 同款）；
    `layers=None` ⇒ **全层收**（放宽口径，实测 C105 178 条锚因此可见 —— 偏离基线，慎用）。
    """
    out = []
    for e in msp:
        if e.dxftype() not in ("TEXT", "MTEXT"):
            continue
        if layers is not None and e.dxf.layer not in layers:
            continue
        s = (e.dxf.text if e.dxftype() == "TEXT" else e.text) or ""
        if s.strip() in LABEL_TXT:
            p = e.dxf.insert
            out.append((p.x, p.y))
    return out


def detect(segs, labels):
    """→ (剔除下标集, 组列表)。**几何规则全在 `treadlib`**，这里只做集合化。"""
    groups = TL.detect_tread_groups(segs, labels)
    idx = set()
    for g in groups:
        idx.update(g["idx"])
    return idx, groups


def drop_from(segs, labels):
    """照 `build8.py:169-173` 的口径：检出什么就剔什么 → (保留的墙段, 剔除下标集, 组列表)。"""
    idx, groups = detect(segs, labels)
    kept = [s for i, s in enumerate(segs) if i not in idx]
    LAST.clear()
    LAST.update({"n_raw": len(segs), "n_drop": len(idx), "n_keep": len(kept),
                 "n_groups": len(groups), "n_labels": len(labels)})
    return kept, idx, groups
