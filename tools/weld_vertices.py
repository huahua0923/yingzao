# -*- coding: utf-8 -*-
r"""修模·第一刀：**焊接顶点**（无损）—— 主件 glb 进，焊接后的 glb 出。

★★ 这一刀为什么叫「焊接」而不是「补洞」——**实测**（`_scratch/_probe_修模.json`）：

   主件 `Tile_+003_+005`：5 片 / 8655 面，`is_watertight` **0/5**，洞 **450**、连通分量 **380**，
   **最大连通块只占 13.4%~34.6% 的面积**。

   | 做法 | 洞 | 分量 | 顶点位置集合 |
   |---|---|---|---|
   | 原样 | 450 | 380 | —— |
   | `merge_vertices()`（只并**完全重合**的点） | **450**（一点不减） | 380 | 逐位不变 |
   | `merge_vertices(digits_vertex=4)`（**0.1 mm** 内吸附） | **17** | **14** | 4/5 片逐位不变；`_L18_0uuuu0` 丢 **1** 个位置 |
   | `digits_vertex=3`（1 mm） | 17 | 14 | **4/5 片丢位置**（只剩 `_L19_0uuuu20` 逐位不变），共丢 **9** |
   | `digits_vertex=2`（10 mm） | **回升**（逐片 2→7 / 2→3 / **6→6** / 3→6 / 3→3） | **回升**（14→20） | **0/5** 逐位不变，共丢 **52**（5~20 个/片） |

   ★ **上表每个数都由 `_scratch/_probe_修模.json` 现算**（铁律 103/174：不许手打、同名的量只留一份）；
     2026-10-15 复核时**改掉过三个手打错的数**：`digits=3` 的丢位置片数（3/5 → 实为 **4/5**）、
     `digits=2` 的逐片洞数（漏了一片且把 `6→6` 误写成 `4→6`）、`digits=4` 丢位置的是**第 1 片**不是「第 5 片」。
     ⇒ 两个地方写同一个数、两处一致，**证明不了它是对的**（铁律 18）。

   ⇒ 那 96% 的「洞」是**导出时的浮点噪声把本该是同一个点的顶点推开了**，**不是屋顶上漏的洞**。
      `merge_vertices()` 不减一丝 ⇒ **glb 里根本没有完全重合的顶点**（噪声是连续分布的）。
   ⇒ 「补洞」的真实含义是**焊接**。`fill_holes()` 造面在这类开放面片上只会造出**跨立面的假面**。

★★ 容差 `DIGITS = 4`（0.1 mm）是**实测算出来的**，不是手打（铁律 103）：
   有损的那一侧（1 mm）离它只差**一个数量级** ⇒ **不许**为了「更干净」往上调。
   10 mm 那一档已经**明确有害**（洞数回升）。

★★ 本刀**不动 `_edit/`（步 1 的主件）**：修模是**可选的一步**，产物写 `_repair/<块>/`。
   依据（计划原话）：「★ 程序化预修模**不做** —— 那几刀最容易错，用户到手还得重改，能力应装进编辑器」。

★★ **「洞数下降」不是判据，是副产品** —— 删掉一半的面，洞数一样下降。
   本工具唯一的**无损判据**是：`verts_set_bitwise_same`（顶点位置集合**恰好**不变）
   ＋ `n_verts_lost == 0 ⇒ area_delta_m2 == 0.0`（面积逐位不变）。

用法：
    python tools/weld_vertices.py                      # 焊 `_edit/` 下全部块
    python tools/weld_vertices.py --blocks Tile_+003_+005
    python tools/weld_vertices.py --digits 4 --repair _repair

退出码：0 全部焊完且无结构异常 · 1 有块被拒或第二把尺子对不上 · 4 `_edit/` 下没有可焊的件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDIT = os.path.join(REPO, "_edit")
REPAIR = os.path.join(REPO, "过程/_repair")

# ★ 0.1 mm —— 实测算出的容差（铁律 103），依据见本文件 docstring 的对照表。
DIGITS = 4

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4


def log(*a):
    print(" ".join(str(x) for x in a))


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _topology(me):
    """(洞数, 边界边数, 连通分量数)。洞＝边界边的连通分量数；边界边＝只被 1 个面用的边。"""
    bi = trimesh.grouping.group_rows(me.edges_sorted, require_count=1)
    nh = int(len(trimesh.graph.connected_components(me.edges_sorted[bi], min_len=1))) if len(bi) else 0
    nc = int(len(trimesh.graph.connected_components(me.face_adjacency, min_len=1)))
    return nh, int(len(bi)), nc


def weld_one(me, digits: int):
    """焊一片。返回 (焊后网格, 读数)。★ 读数里带**无损判据**，不只带「洞少了几个」。"""
    s0 = set(map(tuple, me.vertices.tolist()))
    a0 = float(me.area)
    h0, be0, c0 = _topology(me)

    m2 = me.copy()
    if digits is None:
        m2.merge_vertices()
    else:
        m2.merge_vertices(digits_vertex=digits, merge_tex=True, merge_norm=True)

    s1 = set(map(tuple, m2.vertices.tolist()))
    a1 = float(m2.area)
    h1, be1, c1 = _topology(m2)

    return m2, {
        "n_v_before": int(len(me.vertices)), "n_v_after": int(len(m2.vertices)),
        "n_f_before": int(len(me.faces)), "n_f_after": int(len(m2.faces)),
        "n_holes_before": h0, "n_holes_after": h1,
        "n_boundary_edges_before": be0, "n_boundary_edges_after": be1,
        "n_components_before": c0, "n_components_after": c1,
        "verts_distinct_before": len(s0), "verts_distinct_after": len(s1),
        "n_verts_lost": int(len(s0) - len(s1)),          # 有几个**不同的位置**消失了
        "verts_set_bitwise_same": bool(s1 == s0),        # ★ 无损判据本体
        "area_m2_before": a0, "area_m2_after": a1,
        "area_delta_m2": a1 - a0,
        "is_watertight_after": bool(m2.is_watertight),
    }


def non_identity_nodes(sc):
    """★ 守卫：本工具**不用 `add_geometry` 重建场景**，也不许**静默丢**节点变换。
    若某节点带非单位变换而我们没法保住它 ⇒ **拒这一块**（铁律 137/158：不许静默丢件）。"""
    bad = []
    for n in sc.graph.nodes_geometry:
        try:
            T = sc.graph[n][0]
        except Exception:
            bad.append(str(n))
            continue
        if not np.allclose(np.asarray(T, dtype=float), np.eye(4), atol=0.0, rtol=0.0):
            bad.append(str(n))
    return bad


def do_block(blk_dir: str, digits: int, out_root: str) -> dict:
    blk = os.path.basename(blk_dir.rstrip("/\\"))
    src = os.path.join(blk_dir, blk + ".glb")
    rec = {"block": blk, "src": src, "errs": []}
    if not os.path.exists(src):
        rec["errs"].append("源件不在：%s" % src)
        return rec
    rec["src_bytes"] = os.path.getsize(src)
    rec["src_sha256"] = sha256_file(src)

    sc = trimesh.load(src, force="scene")
    bad = non_identity_nodes(sc)
    if bad:
        rec["errs"].append("节点带非单位变换 %s ⇒ 拒（本工具保不住它，不许静默丢）" % bad)
        return rec

    out = sc.copy()
    per = {}
    for name in list(out.geometry.keys()):
        m2, r = weld_one(out.geometry[name], digits)
        out.geometry[name] = m2                 # 原地换：保住节点结构与名字
        per[name] = r
    rec["per_piece"] = per

    outdir = os.path.join(out_root, blk)
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, blk + ".glb")
    out.export(dst)

    # ---- 第二把尺子：把**写出去的盘上件**重新读回来，与内存里的焊后场景逐片比（铁律 187）
    sc2 = trimesh.load(dst, force="scene")
    if set(sc2.geometry.keys()) != set(per.keys()):
        rec["errs"].append("重读的片名集合对不上：%s vs %s" % (sorted(sc2.geometry.keys()), sorted(per.keys())))
        return rec
    rt = {}
    for name, r in per.items():
        g2 = sc2.geometry[name]
        b1 = out.geometry[name].bounds
        b2 = g2.bounds
        rt[name] = {
            "n_v_match": int(len(g2.vertices)) == r["n_v_after"],
            "n_f_match": int(len(g2.faces)) == r["n_f_after"],
            "bbox_bitmatch": bool(np.array_equal(np.asarray(b1, dtype=float), np.asarray(b2, dtype=float))),
        }
    rec["roundtrip"] = rt
    rec["roundtrip_ok"] = all(v["n_v_match"] and v["n_f_match"] and v["bbox_bitmatch"] for v in rt.values())
    if not rec["roundtrip_ok"]:
        rec["errs"].append("重读对不上（焊接没落盘 / 落盘被改写）")
    rec["dst"] = dst
    rec["dst_bytes"] = os.path.getsize(dst)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="修模·第一刀：焊接顶点（无损）")
    ap.add_argument("--blocks", nargs="*", default=None, help="只焊这几个块（默认全部）")
    ap.add_argument("--digits", type=int, default=DIGITS, help="吸附到 1e-N 米（默认 %d = 0.1 mm）" % DIGITS)
    ap.add_argument("--repair", default=REPAIR, help="产物根目录（默认 %s）" % REPAIR)
    a = ap.parse_args()

    if not os.path.isdir(EDIT):
        log("★ `_edit/` 不在：%s ⇒ 还轮不到修模（rc=4，量不到）" % EDIT)
        return RC_NOGAUGE
    blocks = sorted(n for n in os.listdir(EDIT)
                    if os.path.isfile(os.path.join(EDIT, n, f"{n}.glb")))
    if a.blocks:
        blocks = [b for b in blocks if b in set(a.blocks)]
    if not blocks:
        log("★ 没有可焊的块（`_edit/<块>/<块>.glb` 一个都没有）⇒ rc=4")
        return RC_NOGAUGE

    log("源   %s" % EDIT)
    log("产物 %s" % a.repair)
    log("容差 digits=%s（= 1e-%s m）—— 实测算出，依据见 tools/weld_vertices.py docstring" % (a.digits, a.digits))

    recs, ok = [], True
    for i, blk in enumerate(blocks, 1):
        log("\n-- [%d/%d] %s --" % (i, len(blocks), blk))
        r = do_block(os.path.join(EDIT, blk), a.digits, a.repair)
        recs.append(r)
        if r.get("errs"):
            for e in r["errs"]:
                log("   ★ %s" % e)
            ok = False
            continue
        pp = r["per_piece"]
        nb, na = sum(v["n_holes_before"] for v in pp.values()), sum(v["n_holes_after"] for v in pp.values())
        cb, ca = (sum(v["n_components_before"] for v in pp.values()),
                  sum(v["n_components_after"] for v in pp.values()))
        lost = sum(v["n_verts_lost"] for v in pp.values())
        same = sum(1 for v in pp.values() if v["verts_set_bitwise_same"])
        area = max(abs(v["area_delta_m2"]) for v in pp.values())
        nf_changed = [k for k, v in pp.items() if v["n_f_before"] != v["n_f_after"]]
        log("   片 %d ｜ 洞 %d → %d ｜ 分量 %d → %d ｜ 顶点位置集合恰好不变 %d/%d（共丢 %d 个位置）"
            % (len(pp), nb, na, cb, ca, same, len(pp), lost))
        log("   面积最大变化 %.3e m² ｜ 面数变了的片 %s ｜ 重读对得上 ? %s"
            % (area, nf_changed or "无", r.get("roundtrip_ok")))
        if nf_changed:
            log("   ★ 面数变了 ⇒ 焊接**不许**动面（那是删面，不是焊接）")
            ok = False
        if not r.get("roundtrip_ok"):
            ok = False

    # 台账：基线与期望值必须来自**两次不同读数**（铁律 187）——源件哈希 + 产物哈希都记
    idx = os.path.join(a.repair, "_index.json")
    os.makedirs(a.repair, exist_ok=True)
    with open(idx, "wb") as f:                       # 字节层写盘（铁律 79）
        f.write(json.dumps({
            "tool": "tools/weld_vertices.py",
            "digits": a.digits,
            "tolerance_m": 10.0 ** (-a.digits),
            "edit_dir": EDIT, "repair_dir": a.repair,
            "n_blocks": len(recs), "blocks": [r["block"] for r in recs],
            "results": recs,
        }, ensure_ascii=False, indent=1).encode("utf-8"))

    log("\n台账 %s" % idx)
    log("块 %d 个 ｜ %s" % (len(recs), "全部无结构异常" if ok else "★ 有块不合格"))
    return RC_PASS if ok else RC_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
