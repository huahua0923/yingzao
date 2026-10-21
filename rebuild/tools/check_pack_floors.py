# -*- coding: utf-8 -*-
"""**装包后闸**：`baseline/floors/floor<k>.json` 到底对上了 `meta/blocks.json` 的哪一层。

调用方：
  · `run_chain_bid.py` 的步骤表 `_steps()`（第 44–67 行，装包之后加一步）——每栋楼跑链都过它；
  · 手工全库体检：`python -I rebuild/tools/check_pack_floors.py`（不传参=全部包）。
只读：`packs/cdut-main/*/manifest.json`、`meta/blocks.json`、`baseline/floors/*.json`。
（本文件是库里**第一件**读 `baseline_floor` 的判据：`demo/build_pack*.py` 只写不读。）

字段（合成示例，非生产数据）：
  manifest : {"artifacts":[{"role":"baseline_floor","path":"baseline/floors/floor0.json"},…]}
  blocks   : {"floors":[{"node":"floor0","z0_mm":0.0,
                         "blocks":[{"layer":"COL","ring":[0,0,600,0,600,600,0,600]}]}]}
  floor0   : {"floor":0,"columns":[{"x":-64.35,"y":-33.599,"w":0.6,"d":0.6}],
              "outline":[[-64.47,43.321],…],"rooms":[…]}

为什么要它（2026-10-18 用户「C006 出问题了，你看房屋使用的那个面和房间错开了」）：
  查看器 `nodeOfFloor(k)` 原先**按下标**取 `meta/blocks.json` 的 `floors[k].node`，
  而 `mk_catalog.py` 当时按**文件名**（`sorted(glob)`）排 ⇒ 字典序把「10层/11层」排到
  「1层」前面 ⇒ 一层房间色块被铺到十层板面上。两端都改成了**按 z0 自下而上**，本脚本
  就是这条口径的**独立判据**：不信排序代码，只拿基线柱心去清单里找。

尺子（**平移不变**的柱心票）：
  · 基线柱是查看器局部坐标（米）、清单柱是模型坐标（毫米），两者差一个平移 —— 由**这一对
    自己**现算平移再数命中（容差 120 mm），所以尺子对平移免疫，只对「层数错位」敏感。
  · 逐层命中率 ≥ 90% 才算对上（与查看器 `FRAME_HIT_MIN` 同口径）。
  · 全楼无柱的包（c017/c029 这类）柱尺子**失明**，换面积尺：基线 `outline` 面积 vs 该层
    SLAB 环面积之和（容差 15%）。面积也判不出 ⇒ 报「量不到」，**不当绿**（铁律 199），
    但**不拦链**（几何上确实无从分辨，例如 c029 六层逐层完全一样）。

顺带一条硬闸（与尺子无关、必须绿）：
  `meta/blocks.json` 的 `floors[]` 必须**按 z0_mm 单调不减** —— 这是查看器按下标取层的前提。

退出码：0 全部一致（含「量不到」但已点名）· 4 有包层号错位或 floors[] 没排序。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
PACKS = os.path.join(CDUT, "packs", "cdut-main")

TOL_M = 0.12          # 柱心容差（米）
HIT_MIN = 0.90        # 逐层命中率阈值（与查看器 FRAME_HIT_MIN 同口径）
AREA_TOL = 0.15       # 面积尺容差


def _ring_area(ring):
    xs, ys = ring[0::2], ring[1::2]
    n = len(xs)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        j = (i + 1) % n
        s += xs[i] * ys[j] - xs[j] * ys[i]
    return abs(s) / 2.0


def _cat_floor(f):
    """清单一层 → 柱心表（米）与 SLAB 面积（m²）。"""
    cols, slab = [], 0.0
    for b in f["blocks"]:
        if b["layer"] == "COL":
            xs, ys = b["ring"][0::2], b["ring"][1::2]
            cols.append(((min(xs) + max(xs)) / 2000.0, (min(ys) + max(ys)) / 2000.0))
        elif b["layer"] == "SLAB":
            slab += _ring_area(b["ring"]) / 1e6
    return cols, slab


def _poly_area(ring):
    s = 0.0
    for i in range(len(ring)):
        j = (i + 1) % len(ring)
        s += ring[i][0] * ring[j][1] - ring[j][0] * ring[i][1]
    return abs(s) / 2.0


def _base_floor(d):
    """基线一层 → 柱心表（米，查看器局部坐标）与 outline 面积（m²）。"""
    cols = [(c["x"], c["y"]) for c in (d.get("columns") or [])]
    ring = d.get("outline") or []
    return cols, (_poly_area(ring) if len(ring) >= 3 else 0.0)


def _vote(bcols, ccols):
    """平移对齐后数命中率（基线柱有多少能在清单里找到 120 mm 内的柱）。"""
    if not bcols or not ccols:
        return None
    bx = sum(p[0] for p in bcols) / len(bcols)
    by = sum(p[1] for p in bcols) / len(bcols)
    cx = sum(p[0] for p in ccols) / len(ccols)
    cy = sum(p[1] for p in ccols) / len(ccols)
    tx, ty = bx - cx, by - cy
    hit = 0
    for x, y in bcols:
        for X, Y in ccols:
            if abs(x - (X + tx)) <= TOL_M and abs(y - (Y + ty)) <= TOL_M:
                hit += 1
                break
    return hit / float(len(bcols))


def check(bid):
    P = os.path.join(PACKS, bid)
    man = json.load(open(os.path.join(P, "manifest.json"), encoding="utf-8"))
    bfs = sorted((a["path"] for a in man["artifacts"]
                  if a.get("role") == "baseline_floor"),
                 key=lambda p: int(p.split("floor")[-1].split(".")[0]))
    cat_fp = os.path.join(P, "meta", "blocks.json")
    if not os.path.isfile(cat_fp):
        return {"bid": bid, "skip": "无 blocks.json(单网格包)"}
    cat = json.load(open(cat_fp, encoding="utf-8"))
    raw = cat["floors"]
    cf = sorted(raw, key=lambda f: f.get("z0_mm") or 0.0)
    n, m = len(bfs), len(cf)
    if not n:
        return {"bid": bid, "skip": "无基线层件"}

    # ---- ★ 2026-10-18 硬闸：两套层号必须**逐个对得上**，不许再靠下标猜 ----
    #   用户「地下一楼也没有出来」的病根：基线份数 11、模型层节点 12（B1 在基线里**不存在**），
    #   查看器一句「多出来的只可能是没有基线件的地下层」把错位盖住 ⇒ B1 永远零色块。
    #   装包器现在逐份写 `node`（模型层节点名）；有它 ⇒ 按名字逐份比，没有（老包）⇒ 至少比份数。
    nd = sorted(((a["path"], a.get("node")) for a in man["artifacts"]
                 if a.get("role") == "baseline_floor"),
                key=lambda t: int(t[0].split("floor")[-1].split(".")[0]))
    by_node = all(v for _p, v in nd)
    if by_node:
        want = [f.get("node") for f in cf]
        got = [v for _p, v in nd]
        if got != want:
            return {"bid": bid, "n": n, "m": m, "status": "★层号对不上",
                    "nodes": got, "want": want}
    elif n != m:
        return {"bid": bid, "n": n, "m": m, "status": "★层数不等",
                "nodes": [v for _p, v in nd], "want": [f.get("node") for f in cf]}

    base = [_base_floor(json.load(open(os.path.join(P, p), encoding="utf-8")))
            for p in bfs]
    mdl = [_cat_floor(f) for f in cf]

    # ---- 最硬的一条：清单 floors[] 必须自下而上（查看器按下标取层的前提） ----
    zs = [f.get("z0_mm") or 0.0 for f in raw]
    sorted_ok = all(zs[i] <= zs[i + 1] for i in range(len(zs) - 1))

    # ---- 最优偏移：每个 off 要求**逐层**都过线（不是挑命中总数最多的） ----
    def score(off):
        hits = []
        for k in range(n):
            j = k + off
            if j >= m:
                return -1.0
            r = _vote(base[k][0], mdl[j][0])
            if r is None:
                return -1.0
            hits.append(r)
        return min(hits) if hits else -1.0

    cands = [off for off in range(0, m - n + 1) if score(off) >= HIT_MIN]
    # 有 `node` 时基线件与模型层**一对一**（装包器按同一串层序出件）⇒ 规则偏移恒 0；
    #   没有 `node` 的老包才沿用「多出来的只可能是没有基线件的地下层」这句启发式。
    off_rule = 0 if by_node else ((m - n) if m > n else 0)
    basis = "柱心票"
    if not cands:
        def score_a(off):
            worst = 1.0
            for k in range(n):
                j = k + off
                if j >= m:
                    return -1.0
                ba, ma = base[k][1], mdl[j][1]
                if ba <= 0 or ma <= 0:
                    return -1.0
                worst = min(worst, abs(ba - ma) / max(ba, ma))
            return 1.0 - worst
        cands = [off for off in range(0, m - n + 1) if score_a(off) >= 1.0 - AREA_TOL]
        basis = "面积尺"
    if not cands:
        return {"bid": bid, "n": n, "m": m, "off_rule": off_rule, "sorted_ok": sorted_ok,
                "status": "量不到", "basis": "柱+面积都判不出"}
    ok = off_rule in cands
    return {"bid": bid, "n": n, "m": m, "off_rule": off_rule, "sorted_ok": sorted_ok,
            "ok_offs": cands, "basis": basis,
            "status": "一致" if ok else "★不一致"}


def main(argv):
    want = [a for a in argv if not a.startswith("-")]
    bids = sorted(d for d in os.listdir(PACKS)
                  if os.path.isdir(os.path.join(PACKS, d))
                  and (not want or d in want))
    miss = [b for b in want if b not in bids]
    bad, unknown, good, skipped = [], [], 0, 0
    for b in bids:
        try:
            r = check(b)
        except Exception as e:                                     # noqa: BLE001
            print("%-6s ★崩 %s: %s" % (b, type(e).__name__, e))
            bad.append(b)
            continue
        if r.get("skip"):
            print("%-6s — %s" % (b, r["skip"]))
            skipped += 1
            continue
        if not r["sorted_ok"]:
            print("%-6s ★floors[] 没按 z0 排序（查看器按下标取层会错位）" % b)
            bad.append(b)
            continue
        if r["status"] == "一致":
            good += 1
            continue
        if r["status"] in ("★层号对不上", "★层数不等"):
            print("%-6s %s：基线 %s · 模型 %s"
                  % (b, r["status"], r.get("nodes"), r.get("want")))
        else:
            print("%-6s 基线%2d/清单%2d 规则丢%d 判出可丢%s（%s）"
                  % (b, r["n"], r["m"], r.get("off_rule"), r.get("ok_offs"), r.get("basis")))
        # ★ 任何**带星号**的判词都是红 —— 不许只有「★不一致」这一个字样进 bad
        #   （新加的两个判词不是这四个字，曾被算进「量不到」而 rc=0）。
        (bad if str(r["status"]).startswith("★") else unknown).append(b)
    print("\n合计 %d 包：一致 %d · 单网格跳过 %d · 不一致 %d %s · 量不到 %d %s"
          % (len(bids), good, skipped, len(bad), bad or "", len(unknown), unknown or ""))
    if miss:
        print("★ 点名的包里没有：%s" % miss)
        return 4
    return 4 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
