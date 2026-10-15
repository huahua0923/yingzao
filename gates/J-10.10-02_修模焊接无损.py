# -*- coding: utf-8 -*-
r"""J-10.10-02 · 修模第一刀（**焊接顶点**）**无损**

兑现的是什么：方案 md §10.9 那张表第 1 行「**可复现**」在「改现成」口径下的最近邻 ——
「同一主件 → 同一刀 → 结果在容差内一致」。★ 但本闸量的**不是**「重跑一致」，
而是**更强的一条**：**这一刀根本不该改变几何**（顶点位置集合逐位不变、面数不变）。

--------------------------------------------------------------------------------
【量具】工具 `tools/weld_vertices.py`（`merge_vertices(digits_vertex=4)`）。
  量的是 `_edit/<块>/<块>.glb`（步 1 的主件）与 `_repair/<块>/<块>.glb`（本刀产物）**逐片**比：
    · `n_f`：面数**必须逐片相等**（焊接不许动面 —— 动面就是删面/加面，那是另一把刀）
    · `verts_set_bitwise_same`：顶点位置**集合**是否**恰好**相等（焊接只做 dedup + 重排索引）
    · `n_verts_lost`：有几个**不同的位置**消失了（量化吸附的代价）
    · `area_delta_m2`：总面积变化
    · `n_holes` / `n_components`：**副产品**，按「不许回升」判
  ★ **本闸自己用 trimesh 重算**，**不采信** `_repair/_index.json` 里工具的自评数（铁律 187）。
  ★ 阈值 `MAX_LOST_PER_PIECE = 1` 是**实测算出来的**，不是理论值 —— 见【正对照】与
    `_scratch/_probe_修模.json`：digits=4 时 5 片里 4 片丢 0 个、1 片丢 1 个。
    重测方法：`python _scratch/_probe_修模.py master --weld`，看 `n_verts_lost` 那一列。

【量具盲区】★ 本闸**只判「无损」，不判「焊得对不对」**：
  · 0.1 mm 内的两点**该不该**合并，本闸**没有任何独立依据** —— 它只保证「吸了就吸了、没碰别的」。
  · 「洞数」这把尺子**对删面型的破坏全盲**（删掉一半面，洞数照样下降）⇒ 所以才必须另配
    「面数逐片相等」这条**独立**约束；两条**不许合并成一个 bool**（铁律 174）。
  · **不量外部精度**：焊完相对 DOM/DSM 的偏差，本闸一个字都不给结论。
  · 面数相同、位置集合相同，仍可能有**顶点被重排后 UV 接错**⇒ 本闸只核 UV 通道**在不在**，
    不核它接得对不对（接错要看渲染图，属人判）。
  · 只量 `_repair/` 里**已经生成的块**；`_edit/` 里有而 `_repair/` 里没有的块 ⇒ 报 `only_in_edit`。

【正对照】（必配，四条，每条落读数不落 bool 了事）：
  甲 **空白对照**：**不焊**（原样）⇒ 洞数必须**不下降**。若原样就已经「洞更少」，说明这把尺子**恒绿**。
  乙 **幂等**：拿 `_repair/` 的产物**再焊一遍** ⇒ 洞数**不许再降**、面数不变、位置集合**恰好**不变。
  丙 **焊过头**：`digits=2`（10 mm）⇒ 洞数必须**回升**。
     ★ **只量一片**（`sorted(d)[0]`，本趟实测 = `Tile_+003_+005_L18_0uuuu0`：原样 113 → 0.1 mm **2** → 10 mm **7**）。
       别把整块的逐片数写进这里 —— 那不是这条对照量到的东西（铁律 174：同名的量只留一份）。
       全块逐片读数在 `tools/weld_vertices.py` docstring 的对照表里（由 `_probe_修模.json` 现算）。
     ⇒ 证明这把尺子分得开「焊到位」与「焊糊了」。
  丁 **量不到**：`_repair/` 不存在 ⇒ **rc=4**（与 rc=1「做错了」是两件事）。

三态：`RC_PASS=0 / RC_FAIL=1 / RC_NOGAUGE=4`。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
EDIT = os.path.join(REPO, "_edit")
REPAIR = os.path.join(REPO, "_repair")

GID = "J-10.10-02"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

# ★ 实测算出的上限（铁律 103）：digits=4（0.1 mm）时，5 片里 4 片丢 0 个位置、1 片丢 1 个。
#   重测：`python _scratch/_probe_修模.py master --weld` → 看 `n_verts_lost` 列。
MAX_LOST_PER_PIECE = 1
# ★ 焊过头那一档（正对照丙）：digits=2 = 10 mm。实测洞数回升。
DIGITS_TOO_COARSE = 2

_LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


def _write_json(rc, **kv):
    d = {"pass": rc == 0, "rc": rc}
    d.update(kv)
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, GID + ".json")
    with open(p, "wb") as f:                       # 字节层写盘（铁律 79）
        f.write(json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
    log("  写出:", p)


# ------------------------------------------------------------------ 读数（本闸自己算）

def _topology(me):
    bi = trimesh.grouping.group_rows(me.edges_sorted, require_count=1)
    nh = int(len(trimesh.graph.connected_components(me.edges_sorted[bi], min_len=1))) if len(bi) else 0
    nc = int(len(trimesh.graph.connected_components(me.face_adjacency, min_len=1)))
    return nh, int(len(bi)), nc


def read_pieces(glb_path):
    """读一个 glb → `{片名: 网格}`。"""
    sc = trimesh.load(glb_path, force="scene")
    return dict(sc.geometry)


def piece_readings(me):
    """单片读数。★ 与工具里同一个口径，但**这里独立重算一遍**（铁律 187）。"""
    nh, nbe, ncomp = _topology(me)
    b = np.asarray(me.bounds, dtype=float)
    return {
        "n_v": int(len(me.vertices)), "n_f": int(len(me.faces)),
        "n_holes": nh, "n_boundary_edges": nbe, "n_components": ncomp,
        "verts_distinct": len(set(map(tuple, me.vertices.tolist()))),
        "area_m2": float(me.area),
        "has_uv": getattr(me.visual, "uv", None) is not None,
        "bbox": b.tolist(),
    }


def compare_block(blk):
    """`_edit/<blk>` vs `_repair/<blk>` 逐片比。读数全部本闸自己算。"""
    src = os.path.join(EDIT, blk, blk + ".glb")
    dst = os.path.join(REPAIR, blk, blk + ".glb")
    r = {"block": blk, "src": src, "dst": dst, "errs": []}
    if not os.path.exists(src):
        r["errs"].append("主件不在：%s" % src)
        return r
    if not os.path.exists(dst):
        r["errs"].append("产物不在（本块没焊）：%s" % dst)
        return r

    a = read_pieces(src)
    b = read_pieces(dst)
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    r["only_in_edit"], r["only_in_repair"] = only_a, only_b

    same = sorted(set(a) & set(b))
    per, bad = {}, []
    for name in same:
        ra, rb = piece_readings(a[name]), piece_readings(b[name])
        # 位置集合是否恰好不变：比对**去重后的顶点列表**（排序后逐位比 tuple）
        sa = sorted(set(map(tuple, a[name].vertices.tolist())))
        sb = sorted(set(map(tuple, b[name].vertices.tolist())))
        rec = {
            "n_f_before": ra["n_f"], "n_f_after": rb["n_f"],
            "n_holes_before": ra["n_holes"], "n_holes_after": rb["n_holes"],
            "n_components_before": ra["n_components"], "n_components_after": rb["n_components"],
            "verts_distinct_before": ra["verts_distinct"], "verts_distinct_after": rb["verts_distinct"],
            "n_verts_lost": ra["verts_distinct"] - rb["verts_distinct"],
            "verts_set_bitwise_same": bool(sa == sb),
            "area_m2_before": ra["area_m2"], "area_m2_after": rb["area_m2"],
            "area_delta_m2": rb["area_m2"] - ra["area_m2"],
            "uv_before": ra["has_uv"], "uv_after": rb["has_uv"],
            "bbox_bitmatch": bool(np.array_equal(np.asarray(ra["bbox"]), np.asarray(rb["bbox"]))),
        }
        # 六条**独立**的硬约束（不许合并成一个 bool，铁律 174）
        if rec["n_f_after"] != rec["n_f_before"]:
            bad.append("%s：面数变了 %d→%d（焊接不许动面）" % (name, rec["n_f_before"], rec["n_f_after"]))
        if rec["n_verts_lost"] > MAX_LOST_PER_PIECE:
            bad.append("%s：丢了 %d 个顶点位置 > 实测上限 %d" % (name, rec["n_verts_lost"], MAX_LOST_PER_PIECE))
        if rec["n_verts_lost"] == 0 and rec["area_delta_m2"] != 0.0:
            bad.append("%s：没丢位置却有面积变化 %.3e m²" % (name, rec["area_delta_m2"]))
        if not rec["bbox_bitmatch"]:
            bad.append("%s：包围盒不逐位相同" % name)
        if rec["n_holes_after"] > rec["n_holes_before"]:
            bad.append("%s：洞数回升 %d→%d" % (name, rec["n_holes_before"], rec["n_holes_after"]))
        if rec["uv_before"] and not rec["uv_after"]:
            bad.append("%s：UV 通道丢了" % name)
        per[name] = rec

    r["pieces"] = per
    r["n_pieces"] = len(per)
    r["n_holes_before"] = sum(v["n_holes_before"] for v in per.values())
    r["n_holes_after"] = sum(v["n_holes_after"] for v in per.values())
    r["n_components_before"] = sum(v["n_components_before"] for v in per.values())
    r["n_components_after"] = sum(v["n_components_after"] for v in per.values())
    r["max_verts_lost"] = max((v["n_verts_lost"] for v in per.values()), default=None)
    r["worst_area_delta_m2"] = max((abs(v["area_delta_m2"]) for v in per.values()), default=None)
    r["n_bbox_bitmatch"] = sum(1 for v in per.values() if v["bbox_bitmatch"])
    r["errs"].extend(bad)
    if only_a:
        r["errs"].append("只在主件里：%s" % only_a)
    if only_b:
        r["errs"].append("只在产物里：%s" % only_b)
    if not per:
        r["errs"].append("没有任何同名片可比")
    return r


# ------------------------------------------------------------------ 正对照

def positive_controls(blk):
    """四条正对照。★ 每条不只落 bool，落**读数**（学 J-07.9.4-03 的 controls 段）。"""
    ctl = []

    def rec(case, expect, fired, **kw):
        ctl.append(dict(case=case, expect=expect, fired=bool(fired), **kw))

    src = os.path.join(EDIT, blk, blk + ".glb")
    dst = os.path.join(REPAIR, blk, blk + ".glb")

    def _one_piece(p):
        if not os.path.exists(p):
            return None
        d = read_pieces(p)
        # 取**片最多的那个**做对照，名字按字典序定死，可复现
        k = sorted(d)[0]
        return k, d[k]

    # 甲 空白对照：**什么都不做**不许让读数变好。
    #   ★ 若「不焊」与「焊后」洞数相同 ⇒「洞数下降」这个读数在本件上是**空的**（恒绿）。
    one = _one_piece(src)
    two = _one_piece(dst)
    if one:
        k, m = one
        h_raw = _topology(m)[0]
        h_w = _topology(two[1])[0] if two else None
        rec("甲 空白对照：不焊", "不焊不许有改善 ⇒ 焊后必须**严格更少**",
            (h_w is not None) and (h_raw > h_w), piece=k,
            n_holes_raw=h_raw, n_holes_welded=h_w)

    # 乙 幂等：拿产物再焊一遍 ⇒ 不许再降；面数不变；位置集合恰好不变
    if two:
        k, m = two
        h0, _, c0 = _topology(m)
        s0 = set(map(tuple, m.vertices.tolist()))
        m2 = m.copy()
        m2.merge_vertices(digits_vertex=4, merge_tex=True, merge_norm=True)
        h1, _, c1 = _topology(m2)
        s1 = set(map(tuple, m2.vertices.tolist()))
        fired = (h1 == h0) and (len(m2.faces) == len(m.faces)) and (s1 == s0)
        rec("乙 幂等：产物再焊一遍", "洞不再降 ＋ 面数不变 ＋ 位置集合恰好不变",
            fired, piece=k, holes=(h0, h1), faces=(len(m.faces), len(m2.faces)),
            verts_set_same=bool(s1 == s0), n_verts_lost=len(s0) - len(s1))

    # 丙 焊过头：digits=2（10 mm）⇒ 洞数必须**回升** ⇒ 证明尺子分得开「到位」与「糊了」
    if one:
        k, m = one
        h_raw = _topology(m)[0]
        m3 = m.copy()
        m3.merge_vertices(digits_vertex=DIGITS_TOO_COARSE, merge_tex=True, merge_norm=True)
        h3 = _topology(m3)[0]
        m4 = m.copy()
        m4.merge_vertices(digits_vertex=4, merge_tex=True, merge_norm=True)
        h4 = _topology(m4)[0]
        rec("丙 焊过头：10 mm", "洞数回升（> 0.1 mm 那一档）",
            h3 > h4, piece=k, holes_0p1mm=h4, holes_10mm=h3, holes_raw=h_raw)

    # 丁 量不到：**真的**走一遍「目录不在」那条分支（不是 `not isdir(随便编的路径)` 这种恒真式）
    bogus = os.path.join(REPO, "_本趟故意指向的不存在目录")
    rec("丁 量不到：目录不在", "`_repair/` 不在 ⇒ 归 `repair` 分支（⇒ rc=4，不是 rc=1）",
        _rc_missing_dirs(EDIT, bogus) == "repair" and _rc_missing_dirs(bogus, REPAIR) == "edit",
        probe_dir=bogus, got_repair=_rc_missing_dirs(EDIT, bogus),
        got_edit=_rc_missing_dirs(bogus, REPAIR))
    return ctl


# ------------------------------------------------------------------ 主

def _rc_missing_dirs(edit_dir, repair_dir):
    """「量不到」的判定 —— ★ **本仓只有这一处**（铁律 174：两个同名的量必须死掉一个）。
    `main()` 用它，正对照丁也用它（丁因此**真的**走了一遍那条分支，不是恒真式）。"""
    if not os.path.isdir(edit_dir):
        return "edit"
    if not os.path.isdir(repair_dir):
        return "repair"
    return None


def _skip(reason, **kv):
    log("★ %s ⇒ 量不到（rc=4）" % reason)
    log("===== 判词 =====")
    log("%s 总判 : SKIP（量不到 —— 这一步还没做，不是做错了）" % GID)
    _write_json(4, reason=reason, edit_dir=EDIT, repair_dir=REPAIR,
                n_blocks_measured=0, blocks=[], controls=[],
                blind=["`_repair/` 缺席 ⇒ 本趟**没有量到**任何东西（rc=4，与 rc=1 是两件事）"], **kv)
    return 4


def main() -> int:
    miss = _rc_missing_dirs(EDIT, REPAIR)
    if miss == "edit":
        return _skip("主件目录不存在：%s" % EDIT)
    if miss == "repair":
        return _skip("修模产物目录不存在：%s（本刀还没跑）" % REPAIR)

    blocks = sorted(n for n in os.listdir(REPAIR)
                    if os.path.isfile(os.path.join(REPAIR, n, f"{n}.glb")))
    if not blocks:
        return _skip("`_repair/` 下没有产物（`*.glb` 一个都没有）")

    log("主件 %s" % EDIT)
    log("产物 %s" % REPAIR)
    log("判定：面数逐片不变 ＋ 顶点位置集合恰好不变（每片最多丢 %d 个位置）＋ 洞数不许回升"
        % MAX_LOST_PER_PIECE)

    ok, recs = True, []
    for i, blk in enumerate(blocks, 1):
        log("\n-- [%d/%d] %s --" % (i, len(blocks), blk))
        r = compare_block(blk)
        recs.append(r)
        if r.get("errs"):
            for e in r["errs"]:
                log("   ★ %s" % e)
            ok = False
            continue
        log("   片 %d ｜ 洞 %d → %d ｜ 分量 %d → %d ｜ 包围盒逐位同 %d/%d"
            % (r["n_pieces"], r["n_holes_before"], r["n_holes_after"],
               r["n_components_before"], r["n_components_after"], r["n_bbox_bitmatch"], r["n_pieces"]))
        log("   每片最多丢位置 %s ｜ 最大面积变化 %.3e m² ｜ 位置集合恰好不变的片 %d/%d"
            % (r["max_verts_lost"], r["worst_area_delta_m2"],
               sum(1 for v in r["pieces"].values() if v["verts_set_bitwise_same"]), r["n_pieces"]))

    ctl = positive_controls(blocks[0])
    n_fired = sum(1 for c in ctl if c["fired"])
    for c in ctl:
        log("   正对照%s %s ｜ 读数 %s" % ("✓" if c["fired"] else "★没红！", c["case"],
                                        {k: v for k, v in c.items() if k not in ("case", "expect", "fired")}))
    ok = ok and n_fired == len(ctl)

    log("\n===== 判词 =====")
    log("焊接无损：块 %d 个，面数不变 ＋ 位置集合逐位不变（≤%d 个/片）＝ %s"
        % (len(blocks), MAX_LOST_PER_PIECE, "PASS" if ok else "FAIL"))
    log("正对照 %d/%d 按预期" % (n_fired, len(ctl)))
    log("%s 总判 :" % GID, "PASS" if ok else "FAIL")

    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")

    rc = RC_PASS if ok else RC_FAIL
    _write_json(rc,
                edit_dir=EDIT, repair_dir=REPAIR,
                n_blocks_measured=len(blocks), blocks=blocks,
                n_pieces=sum(r.get("n_pieces") or 0 for r in recs),
                holes_before=sum(r.get("n_holes_before") or 0 for r in recs),
                holes_after=sum(r.get("n_holes_after") or 0 for r in recs),
                components_before=sum(r.get("n_components_before") or 0 for r in recs),
                components_after=sum(r.get("n_components_after") or 0 for r in recs),
                max_lost_per_piece_limit=MAX_LOST_PER_PIECE,
                max_verts_lost=max((r.get("max_verts_lost") or 0) for r in recs) if recs else None,
                worst_area_delta_m2=max((r.get("worst_area_delta_m2") or 0.0) for r in recs) if recs else None,
                n_controls=len(ctl), n_controls_fired=n_fired, controls=ctl,
                results=[{k: v for k, v in r.items() if k != "pieces"} for r in recs],
                blind=["只判「无损」，**不判「焊得对不对」**：0.1 mm 内两点该不该合并，本闸无独立依据",
                       "「洞数」对**删面型**破坏全盲（删一半面洞也降）⇒ 靠「面数逐片相等」这条独立约束补",
                       "不量外部精度：焊完相对 DOM/DSM 的偏差本闸不给结论",
                       "只核 UV 通道在不在，不核重排后 UV 接得对不对（后者要看渲染图，属人判）",
                       "只量 `_repair/` 里已生成的块；`_edit/` 里有而 `_repair/` 里没有的 ⇒ 报告里点名",
                       "`_repair/` 缺席 ⇒ rc=4（量不到），与 rc=1（做错了）是两件事"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
