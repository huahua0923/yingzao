# -*- coding: utf-8 -*-
r"""修模·第二刀：**删退化面 ＋ 删悬浮物**（**有损**——真删面）。s1 焊接件进，s2 清洗件出。

★★ **本刀必须在 `tools/weld_vertices.py`（s1）之后跑**，理由实测（`_scratch/_probe_修模.json`）：

   主件 `Tile_+003_+005` **原样**：洞 450、连通分量 **380**、最大块只占 13.4%~34.6% 面积。
   **焊后**（0.1 mm）：洞 17、连通分量 **380 → 14**。
   ⇒ 那 366 个「分量」是**浮点噪声把本该相连的面扯开**造出来的，**不是悬浮物**。
   ⇒ ★ 谁在 `_edit/` 上直接判分量、按「保留最大块」删，**会砍掉交付件的 83%**（铁律 174：
     两个同名的量——「分量」在**未焊**与**已焊**上不是同一个量——必须让它死掉一个）。

★★ **阈值 `MIN_COMPONENT_M2 = 1.0` 是实测算出来的，不是挑的**（铁律 103）。
   焊后逐片分量普查（现算：`python tools/drop_floaters.py --census`）：

   | 片 | 分量数 | 最大块 | 次大块 | 最小的真件 | 悬浮物（<1 m²） |
   |---|---|---|---|---|---|
   | `_L18_0uuuu0` | 1 | 277.3589 | —— | —— | 0 个 |
   | `_L18_0uuuu1` | 2 | 263.9793 | 110.2882 | 110.2882 | 0 个 |
   | `_L18_0uuuu3` | 6 | 114.7109 | 11.5936 | **11.5936** | **4 个**：0.0598 / 0.0396 / 0.0177 / 0.0044 |
   | `_L19_0uuuu20` | 3 | 161.2504 | 109.4645 | 85.0595 | 0 个 |
   | `_L19_0uuuu21` | 2 | 306.6250 | 138.8718 | 138.8718 | 0 个 |

   ⇒ **真件最小 11.5936 m²，悬浮物最大 0.0598 m²，中间空着 194 倍**。
     阈值取 **1.0 m²**：往上留 11.6×、往下留 16.7× —— **两边各一个数量级余量**。
   ⇒ ★ **绝不能按「不是最大块就删」**：次大块里有 **138.87 m² 的整条立面**，
     按「留最大块」一刀下去，交付件里**真实存在**的立面就没了，而且**一声不响**。

★★ **退化面**（`area_faces == 0`，逐位 0）：实测 `_L18_0uuuu0` 有 **1** 个三角
   `[874, 874, 714]` —— **两个顶点索引相同**，面积恒 0。
   ★ 它对 `trimesh.graph.connected_components` **完全失明**（该面**不属于任何分量**）：
   本趟普查 `faces=2318` 而分量里只数到 `2317` ⇒ 「14 个分量」这句话**漏掉了它**（铁律 158）。
   删它**面积逐位不变**（0 m²），是**可证无损**的一刀。

★★ **结构守卫（把计划里那条正对照焊进工具）**：若某片的**最大分量**低于阈值
   ⇒ **拒这一片**（rc=1，不写盘）。最大分量是「这栋楼的主体」，它被删只可能意味着
   阈值/输入错了，不许静默删掉一栋楼。

用法：
    python tools/drop_floaters.py                       # 清洗 `_repair/` 下全部块
    python tools/drop_floaters.py --blocks Tile_+003_+005
    python tools/drop_floaters.py --min-m2 1.0 --clean _clean
    python tools/drop_floaters.py --census              # 只打印普查表，不写盘

退出码：0 全部清洗完且无结构异常 · 1 有片被拒或第二把尺子对不上 · 4 `_repair/` 下没有可洗的件
（★ 尤其：**还没跑 s1 焊接** ⇒ rc=4，不是 rc=1）。
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
CLEAN = os.path.join(REPO, "过程/_clean")

# ★ 1.0 m² —— 实测算出的阈值（铁律 103），依据见本文件 docstring 的普查表。
#   真件最小 11.5936、悬浮物最大 0.0598 ⇒ 阈值落在两者之间，两边各留一个数量级。
MIN_COMPONENT_M2 = 1.0

RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4


def log(*a):
    print(" ".join(str(x) for x in a))


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def components_with_areas(me):
    """逐分量 (面索引数组, 面积, 包围盒)，按面积降序。★ 另**单列**不属于任何分量的面。
    返回 (comps, orphan_faces)。铁律 158：量具对什么瞎，必须自己说出来，不能让它悄悄漏掉。"""
    comps = trimesh.graph.connected_components(me.face_adjacency, min_len=1)
    seen = np.zeros(len(me.faces), dtype=bool)
    out = []
    for c in comps:
        idx = np.asarray(c, dtype=np.int64)
        seen[idx] = True
        m = me.submesh([idx], append=True)
        out.append((idx, float(m.area), np.asarray(m.bounds, dtype=float)))
    orphan = np.where(~seen)[0]
    out.sort(key=lambda r: -r[1])
    return out, orphan


def clean_one(me, min_m2: float):
    """洗一片。返回 (洗后网格, 读数)。★ 读数里带**拒片理由**与**面积账**，不只带「删了几个」。"""
    n_f0 = int(len(me.faces))
    a0 = float(me.area)
    areas0 = np.asarray(me.area_faces, dtype=float)

    comps, orphan = components_with_areas(me)
    if not comps:
        return me, {"errs": ["这一片没有任何连通分量 ⇒ 拒（不是空片就是坏的）"]}

    largest_area = comps[0][1]
    if largest_area < min_m2:
        # ★ 结构守卫：最大分量＝这栋楼的主体。它低于阈值只可能是阈值/输入错了。
        return me, {"errs": ["最大分量才 %.4f m² < 阈值 %.4f m² ⇒ **拒这一片**"
                             "（最大分量是主体，删它=删楼；不许静默删）" % (largest_area, min_m2)]}

    # ---- 两把刀，分开记账 ------------------------------------------------
    # 刀一：退化面（面积**逐位**为 0）。可证无损：删掉后总面积逐位不变。
    deg = np.where(areas0 == 0.0)[0]
    keep = np.ones(n_f0, dtype=bool)
    keep[deg] = False

    # 刀二：悬浮物（分量面积 < 阈值）。★ 永远不碰最大分量（上面已守），此处再兜一次底。
    dropped = []
    for idx, area, bb in comps:
        if area >= min_m2:
            continue
        if area == largest_area:
            continue                                   # 兜底：语义上不可能走到这
        keep[idx] = False
        dropped.append({"n_faces": int(len(idx)), "area_m2": area,
                        "bbox_min": [float(x) for x in bb[0]],
                        "bbox_max": [float(x) for x in bb[1]]})

    dropped.sort(key=lambda d: -d["area_m2"])
    m2 = me.copy()
    if not keep.all():
        m2.update_faces(keep)                          # ★ 保 UV / 保材质（不用手搓 vertices/faces）
    m2.remove_unreferenced_vertices()

    n_f1 = int(len(m2.faces))
    a1 = float(m2.area)
    comps1, orphan1 = components_with_areas(m2)

    return m2, {
        "n_f_before": n_f0, "n_f_after": n_f1, "n_f_dropped": n_f0 - n_f1,
        "n_degenerate_dropped": int(len(deg)),
        "n_floaters_dropped": int(len(dropped)),
        "floaters": dropped,
        "n_comp_before": len(comps), "n_comp_after": len(comps1),
        "n_orphan_faces_before": int(len(orphan)), "n_orphan_faces_after": int(len(orphan1)),
        "area_before_m2": a0, "area_after_m2": a1,
        "floater_area_dropped_m2": float(sum(d["area_m2"] for d in dropped)),
        "degenerate_area_dropped_m2": float(sum(areas0[i] for i in deg)),
        "largest_comp_area_before": float(largest_area),
        "largest_comp_area_after": float(comps1[0][1]) if comps1 else 0.0,
        "largest_comp_kept": bool(comps1 and comps1[0][1] == largest_area),
    }


def non_identity_nodes(sc):
    """与 `tools/weld_vertices.py::non_identity_nodes` **同形**的守卫（保住节点变换，不许静默丢）。"""
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


def do_block(blk_dir: str, min_m2: float, out_root: str) -> dict:
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
        m2, r = clean_one(out.geometry[name], min_m2)
        if r.get("errs"):
            rec["errs"].extend(["%s：%s" % (name, e) for e in r["errs"]])
            return rec
        out.geometry[name] = m2                        # 原地换：保住节点结构与名字
        per[name] = r
    rec["per_piece"] = per

    outdir = os.path.join(out_root, blk)
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, blk + ".glb")
    out.export(dst)

    # ---- 第二把尺子：把**写出去的盘上件**重新读回来逐片比（铁律 187）
    sc2 = trimesh.load(dst, force="scene")
    if set(sc2.geometry.keys()) != set(per.keys()):
        rec["errs"].append("重读的片名集合对不上：%s vs %s" % (sorted(sc2.geometry.keys()), sorted(per.keys())))
        return rec
    rt = {}
    for name, r in per.items():
        g2 = sc2.geometry[name]
        rt[name] = {
            "n_f_match": int(len(g2.faces)) == r["n_f_after"],
            "area_match": bool(float(g2.area) == r["area_after_m2"]),
            "uv_present_after": bool(getattr(g2.visual, "uv", None) is not None),
        }
    rec["roundtrip"] = rt
    rec["roundtrip_ok"] = all(v["n_f_match"] and v["area_match"] for v in rt.values())
    if not rec["roundtrip_ok"]:
        rec["errs"].append("重读对不上（清洗没落盘 / 落盘被改写）")
    rec["dst"] = dst
    rec["dst_bytes"] = os.path.getsize(dst)
    return rec


def census(blocks, min_m2):
    """★ 只打印普查表，不写盘。本文件 docstring 那张表就是用这个现算的（铁律 103）。"""
    for blk in blocks:
        src = os.path.join(REPAIR, blk, blk + ".glb")
        if not os.path.exists(src):
            log("!! %s 不在（先跑 tools/weld_vertices.py）" % src)
            continue
        sc = trimesh.load(src, force="scene")
        log("== %s" % blk)
        for name in sorted(sc.geometry.keys()):
            comps, orphan = components_with_areas(sc.geometry[name])
            log("   %-26s faces=%d comps=%d orphan=%d"
                % (name, len(sc.geometry[name].faces), len(comps), len(orphan)))
            tiny = [c[1] for c in comps if c[1] < min_m2]
            legit = [c[1] for c in comps if c[1] >= min_m2]
            log("      真件 最小 %s ｜ 悬浮物 %d 个 最大 %s ｜ 空档 %s"
                % ("%.4f" % min(legit) if legit else "——",
                   len(tiny), "%.4f" % max(tiny) if tiny else "——",
                   "%.1f×" % (min(legit) / max(tiny)) if legit and tiny else "——"))


def main() -> int:
    ap = argparse.ArgumentParser(description="修模·第二刀：删退化面 ＋ 删悬浮物（有损）")
    ap.add_argument("--blocks", nargs="*", default=None, help="只洗这几个块（默认全部）")
    ap.add_argument("--min-m2", type=float, default=MIN_COMPONENT_M2,
                    help="分量面积阈值（默认 %.1f m² = 实测算出）" % MIN_COMPONENT_M2)
    ap.add_argument("--repair", default=REPAIR, help="s1 产物根目录（默认 %s）" % REPAIR)
    ap.add_argument("--clean", default=CLEAN, help="s2 产物根目录（默认 %s）" % CLEAN)
    ap.add_argument("--census", action="store_true", help="只打印普查表，不写盘")
    a = ap.parse_args()

    if not os.path.isdir(a.repair):
        log("★ `_repair/` 不在：%s ⇒ **还没跑 s1 焊接**，轮不到 s2（rc=4，量不到）" % a.repair)
        return RC_NOGAUGE
    blocks = sorted(n for n in os.listdir(a.repair)
                    if os.path.isfile(os.path.join(a.repair, n, f"{n}.glb")))
    if a.blocks:
        blocks = [b for b in blocks if b in set(a.blocks)]
    if not blocks:
        log("★ `_repair/` 下没有 s1 产物（`_repair/<块>/<块>.glb` 一个都没有）⇒ rc=4")
        log("  先跑：python tools/weld_vertices.py")
        return RC_NOGAUGE

    if a.census:
        census(blocks, a.min_m2)
        return RC_PASS

    log("源   %s（s1 焊接件）" % a.repair)
    log("产物 %s（s2 清洗件）" % a.clean)
    log("阈值 min_m2=%.4f m² —— 实测算出（真件最小 11.5936 / 悬浮物最大 0.0598），"
        "依据见 tools/drop_floaters.py docstring" % a.min_m2)

    recs, ok = [], True
    for i, blk in enumerate(blocks, 1):
        log("\n-- [%d/%d] %s --" % (i, len(blocks), blk))
        r = do_block(os.path.join(a.repair, blk), a.min_m2, a.clean)
        recs.append(r)
        if r.get("errs"):
            for e in r["errs"]:
                log("   ★ %s" % e)
            ok = False
            continue
        pp = r["per_piece"]
        nb, na = sum(v["n_f_before"] for v in pp.values()), sum(v["n_f_after"] for v in pp.values())
        nd = sum(v["n_degenerate_dropped"] for v in pp.values())
        nfl = sum(v["n_floaters_dropped"] for v in pp.values())
        fa = sum(v["floater_area_dropped_m2"] for v in pp.values())
        cb, ca = (sum(v["n_comp_before"] for v in pp.values()),
                  sum(v["n_comp_after"] for v in pp.values()))
        log("   片 %d ｜ 面 %d → %d（退化面 %d ＋ 悬浮物 %d 个 / %.4f m²）｜ 分量 %d → %d"
            % (len(pp), nb, na, nd, nfl, fa, cb, ca))
        log("   最大分量保住了 ? %s ｜ 重读对得上 ? %s"
            % (all(v["largest_comp_kept"] for v in pp.values()), r.get("roundtrip_ok")))
        if not r.get("roundtrip_ok"):
            ok = False

    idx = os.path.join(a.clean, "_index.json")
    os.makedirs(a.clean, exist_ok=True)
    with open(idx, "wb") as f:                       # 字节层写盘（铁律 79）
        f.write(json.dumps({
            "tool": "tools/drop_floaters.py",
            "min_component_m2": a.min_m2,
            "repair_dir": a.repair, "clean_dir": a.clean,
            "n_blocks": len(recs), "blocks": [r["block"] for r in recs],
            "results": recs,
        }, ensure_ascii=False, indent=1).encode("utf-8"))

    log("\n台账 %s" % idx)
    log("块 %d 个 ｜ %s" % (len(recs), "全部无结构异常" if ok else "★ 有块不合格"))
    return RC_PASS if ok else RC_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
