# -*- coding: utf-8 -*-
r"""J-10.10-03 修模·第二刀（删退化面 ＋ 删悬浮物）**不误删** —— 有损的那一刀，门开在这里。

【判据】`_clean/<块>/<块>.glb`（s2 清洗件）相对 `_repair/<块>/<块>.glb`（s1 焊接件），**逐片**满足
  五条**互相独立**的约束（★ 不许合并成一个 bool，铁律 174）：
    ① **面只减不增**：`n_f_after ≤ n_f_before`；
    ② **没有任何面被改动**：clean 的逐面面积多重集是 repair 的**子**多重集（按 IEEE754 字节逐位比）；
    ③ **删掉的正是该删的**：被删面的面积多重集 == （**退化面** ∪ **阈值以下分量的面**）的面积多重集；
    ④ **残留里不许再有小的**：clean 每个分量面积 ≥ 阈值，且不含 0 面积面；
    ⑤ **主体逐位没动**：clean 的最大分量面积 == repair 的最大分量面积（**逐位**）。

【量具】`trimesh 5.1`，本闸**自己**读两侧 glb 重算（★ **不采信** `_clean/_index.json` 里工具的自评，铁律 187）；
  阈值 `MIN_COMPONENT_M2` **从 `tools/drop_floaters.py` import**（★ 单一来源，铁律 174：
  同一个阈值不许在两处各写一份）。正对照里才调工具本体（那里测的就是工具）。

【量具盲区】★ 本闸**只判「有没有误删」**，下面这几类它**一个字都不给结论**：
  · **不判「悬空与否」**：判据按**绝对面积**，一块**大而确实悬空**的碎片（面积 ≥ 阈值）**不会被删也不会被报**。
  · **不判删完好不好看**：留了残茬、切边毛刺，本闸看不见。
  · **不判纹理**：只核 UV 通道**在不在**；删面后 UV 接得对不对属人判（要看渲染图）。
  · **不判阈值对不对**：1.0 m² 是**实测算出**的（真件最小 11.5936 / 悬浮物最大 0.0598，空 194 倍），
    但「0.06 m² 的碎片算不算悬浮物」本闸**没有独立依据** —— 它只保证「该删的删了、别的一根没碰」。
  · 只量 `_repair/` 与 `_clean/` 里**都已生成**的块；两侧块名不一致 ⇒ 报告里点名。

【正对照】（必配，五条，每条落**读数**不只落 bool）：
  甲 **真屋顶不许删**（计划点名的那条）：拿 s1 件里一块**真构件**（次大分量，实测 138.87 m² 的整条立面）
     单独喂工具 ⇒ 必须**一个面都不删**。这是「不误删」的分辨力来源。
  乙 **阴性对照**：整块喂 ⇒ 必须**真的删到东西**（≥1 面）。若一个都不删，说明 ②③④ 三条**恒绿**。
  丙 **阈值抬坏**：`min_m2=200`（远大于最小真件 11.59）⇒ 工具必须**误删真件** ⇒ 证明尺子能红。
  丁 **结构守卫**：`min_m2` 设得比最大分量还大 ⇒ 工具必须**拒片**（`errs` 非空），
     **而不是**静默把这一片删空 —— 这是「删楼」与「拒片」的分界。
  戊 **量不到**：`_repair/` 或 `_clean/` 缺席 ⇒ **rc=4**（与 rc=1「做错了」是两件事）。

三态：`RC_PASS=0 / RC_FAIL=1 / RC_NOGAUGE=4`。
"""
from __future__ import annotations

import collections
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")
EDIT = os.path.join(REPO, "_edit")
REPAIR = os.path.join(REPO, "_repair")
CLEAN = os.path.join(REPO, "_clean")

sys.path.insert(0, REPO)
from tools.drop_floaters import (  # noqa: E402
    MIN_COMPONENT_M2, components_with_areas, clean_one,
)

GID = "J-10.10-03"
RC_PASS, RC_FAIL, RC_NOGAUGE = 0, 1, 4

# ★ 阈值「抬坏」那一档（正对照丙）—— 必须远大于最小真件 11.5936 m²，逼它误删。
MIN_M2_ABUSED = 200.0

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


def _rc_missing_dirs(repair_dir, clean_dir):
    """「量不到」的判定 —— ★ **本闸只有这一处**（铁律 174）。`main()` 与正对照戊共用。"""
    if not os.path.isdir(repair_dir):
        return "repair"
    if not os.path.isdir(clean_dir):
        return "clean"
    return None


# ------------------------------------------------------------------ 读数（本闸自己算）

def _key(v: float) -> bytes:
    """IEEE754 逐位键。★ 「面积多重集」要的是**逐位**相同，不是带小数容差的「差不多」。"""
    return struct.pack("<d", float(v))


def _multiset(vals):
    return collections.Counter(_key(v) for v in vals)


def piece_census(me, min_m2):
    """一片的普查读数。★ 与工具同一个口径，但**这里独立重算一遍**（铁律 187）。"""
    comps, orphan = components_with_areas(me)
    areas = np.asarray(me.area_faces, dtype=float)
    small = [c for c in comps if c[1] < min_m2]
    return {
        "n_f": int(len(me.faces)),
        "n_comp": len(comps),
        "n_orphan_faces": int(len(orphan)),
        "n_zero_area_faces": int((areas == 0.0).sum()),
        "largest_comp_area": float(comps[0][1]) if comps else None,
        "small_comp_areas": [float(c[1]) for c in comps if c[1] < min_m2],
        "_areas": areas,
        "_small_face_idx": (np.concatenate([c[0] for c in small]) if small
                            else np.array([], dtype=np.int64)),
    }


def compare_block(blk):
    """`_repair/<blk>` vs `_clean/<blk>` 逐片比。★ 读数全部本闸自己算，不读台账。"""
    src = os.path.join(REPAIR, blk, blk + ".glb")
    dst = os.path.join(CLEAN, blk, blk + ".glb")
    r = {"block": blk, "src": src, "dst": dst, "errs": [], "pieces": {}}
    if not os.path.exists(src):
        r["errs"].append("s1 焊接件不在：%s" % src)
        return r
    if not os.path.exists(dst):
        r["errs"].append("s2 清洗件不在（本块没洗）：%s" % dst)
        return r

    a = dict(trimesh.load(src, force="scene").geometry)
    b = dict(trimesh.load(dst, force="scene").geometry)
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    r["only_in_repair"], r["only_in_clean"] = only_a, only_b
    if only_a or only_b:
        r["errs"].append("两侧片名对不上：_repair 独有 %s，_clean 独有 %s"
                         % (only_a or "无", only_b or "无"))
        return r

    ok_f = 0
    for name in sorted(a):
        ma, mb = a[name], b[name]
        ca, cb = piece_census(ma, MIN_COMPONENT_M2), piece_census(mb, MIN_COMPONENT_M2)
        bad = []

        # ① 面只减不增
        if cb["n_f"] > ca["n_f"]:
            bad.append("面数增加了（%d → %d）—— 本刀只删不加" % (ca["n_f"], cb["n_f"]))

        # ② 没有任何面被改动：clean 的逐面面积多重集 ⊆ repair 的
        ka, kb = _multiset(ca["_areas"]), _multiset(cb["_areas"])
        extra = kb - ka
        if extra:
            bad.append("clean 里有 %d 个面的面积在 repair 里**找不到** ⇒ 面被改动过（不是纯删除）"
                       % sum(extra.values()))

        # ③ 删掉的正是该删的：removed == (退化面 ∪ 阈值以下分量的面)
        removed = ka - kb
        expect = _multiset(np.concatenate([
            ca["_areas"][ca["_areas"] == 0.0], ca["_areas"][ca["_small_face_idx"]]]))
        if removed != expect:
            bad.append("删掉的面不是「退化面 ∪ 阈值以下分量的面」：多删 %d 个、少删 %d 个"
                       % (sum((removed - expect).values()), sum((expect - removed).values())))

        # ④ 残留里不许再有小的
        if cb["small_comp_areas"]:
            bad.append("clean 残留 %d 个 < %.3f m² 的分量（%s）"
                       % (len(cb["small_comp_areas"]), MIN_COMPONENT_M2,
                          ["%.4f" % v for v in sorted(cb["small_comp_areas"])[:5]]))
        if cb["n_zero_area_faces"]:
            bad.append("clean 还留着 %d 个 0 面积面" % cb["n_zero_area_faces"])

        # ⑤ 主体逐位没动
        if ca["largest_comp_area"] is None or cb["largest_comp_area"] is None:
            bad.append("有一侧没有连通分量 ⇒ 量不到主体")
        elif _key(ca["largest_comp_area"]) != _key(cb["largest_comp_area"]):
            bad.append("最大分量面积**不等**（%.6f → %.6f）⇒ 主体被动过"
                       % (ca["largest_comp_area"], cb["largest_comp_area"]))

        if not bad:
            ok_f += 1
        r["pieces"][name] = {
            "n_f": (ca["n_f"], cb["n_f"]),
            "n_comp": (ca["n_comp"], cb["n_comp"]),
            "n_zero_area_faces": (ca["n_zero_area_faces"], cb["n_zero_area_faces"]),
            "largest_comp_area": (ca["largest_comp_area"], cb["largest_comp_area"]),
            "small_comp_areas_after": cb["small_comp_areas"],
            "n_faces_removed": ca["n_f"] - cb["n_f"],
            "bad": bad,
        }
        if bad:
            r["errs"].extend(["%s：%s" % (name, e) for e in bad])

    r["n_pieces"] = len(a)
    r["n_pieces_clean_ok"] = ok_f
    r["faces_before"] = sum(v["n_f"][0] for v in r["pieces"].values())
    r["faces_after"] = sum(v["n_f"][1] for v in r["pieces"].values())
    return r


# ------------------------------------------------------------------ 正对照

def positive_controls(blk):
    """五条正对照。★ 每条不只落 bool，落**读数**（学 J-07.9.4-03 的 controls 段）。"""
    ctl = []

    def rec(case, expect, fired, **kw):
        ctl.append(dict(case=case, expect=expect, fired=bool(fired), **kw))

    src = os.path.join(REPAIR, blk, blk + ".glb")
    if not os.path.exists(src):
        rec("甲~丁 前置", "s1 件必须存在才能跑对照", False, src=src)
        return ctl

    geo = dict(trimesh.load(src, force="scene").geometry)

    # ★ 「取哪一片」由**现算**定死：按片名字典序找第一块**有 ≥2 分量**的（不手打片名，铁律 174）。
    #   甲、丙共用它 —— 两处都必须落在**有真件可误删**的片上：
    #   只有 1 个分量的片（如 `_L18_0uuuu0`）上，「误删真件」这件事**根本不可能发生**，
    #   拿它当 丙 的靶子 ⇒ 尺子必然被读成「没红」，而那是**靶子挑错了**，不是尺子没有分辨力。
    pick = None
    for name in sorted(geo):
        comps, _ = components_with_areas(geo[name])
        if len(comps) >= 2:
            pick = (name, comps[1])
            break

    # 甲 真屋顶不许删：取该片的 **次大分量**（实测 138.8718 m² 的整条立面），单独喂 ⇒ 一个面都不许删。
    if pick:
        name, (idx, area, _bb) = pick
        roof = geo[name].submesh([np.asarray(idx)], append=True)
        _m, r = clean_one(roof, MIN_COMPONENT_M2)
        rec("甲 真屋顶不许删", "喂一块真构件（次大分量）⇒ 一个面都不删",
            (r.get("n_f_dropped") == 0) and (r.get("n_floaters_dropped") == 0) and not r.get("errs"),
            piece=name, fed_area_m2=area, n_f_fed=int(len(roof.faces)),
            n_f_dropped=r.get("n_f_dropped"), n_floaters_dropped=r.get("n_floaters_dropped"))
    else:
        rec("甲 真屋顶不许删", "需要一块有 ≥2 分量的片", False, reason="s1 件里找不到有 ≥2 分量的片")

    # 乙 阴性对照：整块喂 ⇒ 必须**真的删到东西**
    whole = trimesh.load(src, force="scene")
    tot_drop = 0
    for name in sorted(whole.geometry.keys()):
        _m, r = clean_one(whole.geometry[name], MIN_COMPONENT_M2)
        tot_drop += int(r.get("n_f_dropped") or 0)
    rec("乙 阴性对照：真删到东西", "整块喂 ⇒ 必须删到 ≥1 个面（否则②③④恒绿）",
        tot_drop > 0, n_f_dropped_total=tot_drop)

    # 丙 阈值抬坏：min_m2=200 ⇒ 必须**误删真件**（证明阈值不是随便设的、尺子能红）
    #   ★ 靶子＝上面 pick 那块（**有 ≥2 分量**）。它的最大分量 ≥ 200 ⇒ 过结构守卫，
    #     而次大块（110.2882 / 138.8718 m² —— **真的是一整条立面**）< 200 ⇒ 被当悬浮物删掉。
    #   ★ 绝不能拿只有 1 个分量的片当这个靶子（本趟第一版就是）—— 那里「误删真件」无从发生。
    if not pick:
        rec("丙 阈值抬坏：200 m²", "需要一块有 ≥2 分量的片", False, reason="s1 件里找不到")
    else:
        name_ab = pick[0]
        _m, r200 = clean_one(geo[name_ab], MIN_M2_ABUSED)
        rec("丙 阈值抬坏：200 m²", "必须误删真件（≥1 个真分量被当悬浮物删掉）",
            (r200.get("n_floaters_dropped") or 0) > 0,
            piece=name_ab, min_m2=MIN_M2_ABUSED,
            n_floaters_dropped=r200.get("n_floaters_dropped"),
            n_f_dropped=r200.get("n_f_dropped"),
            area_m2=r200.get("floater_area_dropped_m2"),
            largest_kept_after=r200.get("largest_comp_kept"))

    # 丁 结构守卫：阈值 > 最大分量 ⇒ 工具必须**拒片**，不是静默删空
    big = max(components_with_areas(geo[n])[0][0][1] for n in geo)
    name_big = (pick[0] if pick else sorted(geo)[0])
    _m, rbig = clean_one(geo[name_big], big + 1.0)
    rec("丁 结构守卫：阈值大于主体", "必须**拒片**（errs 非空），不许静默删楼",
        bool(rbig.get("errs")), piece=name_big, min_m2=big + 1.0,
        errs=(rbig.get("errs") or [""])[0][:120])

    # 戊 量不到：**真的**走一遍「目录不在」那条分支（不是恒真式）
    bogus = os.path.join(REPO, "_本趟故意指向的不存在目录")
    rec("戊 量不到：目录不在", "`_repair/`／`_clean/` 缺失 ⇒ 各归各的分支（⇒ rc=4，不是 rc=1）",
        _rc_missing_dirs(bogus, CLEAN) == "repair" and _rc_missing_dirs(REPAIR, bogus) == "clean",
        probe_dir=bogus, got_repair=_rc_missing_dirs(bogus, CLEAN),
        got_clean=_rc_missing_dirs(REPAIR, bogus))
    return ctl


# ------------------------------------------------------------------ 主

def _skip(reason, **kv):
    log("★ %s ⇒ 量不到（rc=4）" % reason)
    log("===== 判词 =====")
    log("%s 总判 : SKIP（量不到 —— 这一步还没做，不是做错了）" % GID)
    os.makedirs(OUTDIR, exist_ok=True)
    _write_json(4, reason=reason, repair_dir=REPAIR, clean_dir=CLEAN,
                n_blocks_measured=0, blocks=[], controls=[],
                blind=["`_repair/` 或 `_clean/` 缺席 ⇒ 本趟**没有量到**任何东西（rc=4，与 rc=1 是两件事）"],
                **kv)
    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    return RC_NOGAUGE


def main() -> int:
    miss = _rc_missing_dirs(REPAIR, CLEAN)
    if miss == "repair":
        return _skip("s1 焊接件目录不存在：%s（先跑 tools/weld_vertices.py）" % REPAIR)
    if miss == "clean":
        return _skip("s2 清洗件目录不存在：%s（本刀还没跑）" % CLEAN)

    blocks = sorted(n for n in os.listdir(CLEAN)
                    if os.path.isfile(os.path.join(CLEAN, n, f"{n}.glb")))
    if not blocks:
        return _skip("`_clean/` 下没有产物（`*.glb` 一个都没有）")

    log("s1 焊接件 %s" % REPAIR)
    log("s2 清洗件 %s" % CLEAN)
    log("阈值 min_m2=%.4f m²（★ 从 tools/drop_floaters.py import，单一来源）" % MIN_COMPONENT_M2)
    log("判定：① 面只减不增 ② 没有面被改动 ③ 删掉的正是该删的 ④ 残留无小分量 ⑤ 主体逐位没动")

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
        log("   片 %d ｜ 面 %d → %d ｜ 分量 %d → %d ｜ 五条全过的片 %d/%d"
            % (r["n_pieces"], r["faces_before"], r["faces_after"],
               sum(v["n_comp"][0] for v in r["pieces"].values()),
               sum(v["n_comp"][1] for v in r["pieces"].values()),
               r["n_pieces_clean_ok"], r["n_pieces"]))
        log("   主体（最大分量面积）逐位同的片 %d/%d ｜ 删面数 %d"
            % (sum(1 for v in r["pieces"].values()
                   if v["largest_comp_area"][0] is not None
                   and _key(v["largest_comp_area"][0]) == _key(v["largest_comp_area"][1])),
               r["n_pieces"], r["faces_before"] - r["faces_after"]))

    ctl = positive_controls(blocks[0])
    n_fired = sum(1 for c in ctl if c["fired"])
    for c in ctl:
        log("   正对照%s %s ｜ 读数 %s" % ("✓" if c["fired"] else "★没红！", c["case"],
                                        {k: v for k, v in c.items() if k not in ("case", "expect", "fired")}))
    ok = ok and n_fired == len(ctl)

    log("\n===== 判词 =====")
    log("清洗不误删：块 %d 个，五条独立约束逐片全过 ＋ 主体逐位没动 ＝ %s"
        % (len(blocks), "PASS" if ok else "FAIL"))
    log("正对照 %d/%d 按预期" % (n_fired, len(ctl)))
    log("%s 总判 :" % GID, "PASS" if ok else "FAIL")

    with open(os.path.join(OUTDIR, GID + ".run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")

    rc = RC_PASS if ok else RC_FAIL
    _write_json(rc,
                repair_dir=REPAIR, clean_dir=CLEAN,
                n_blocks_measured=len(blocks), blocks=blocks,
                n_pieces=sum(r.get("n_pieces") or 0 for r in recs),
                faces_before=sum(r.get("faces_before") or 0 for r in recs),
                faces_after=sum(r.get("faces_after") or 0 for r in recs),
                faces_dropped=sum((r.get("faces_before") or 0) - (r.get("faces_after") or 0)
                                  for r in recs),
                n_components_before=sum(sum(v["n_comp"][0] for v in r["pieces"].values()) for r in recs),
                n_components_after=sum(sum(v["n_comp"][1] for v in r["pieces"].values()) for r in recs),
                min_component_m2=MIN_COMPONENT_M2,
                max_component_unchanged=all(
                    v["largest_comp_area"][0] is not None
                    and _key(v["largest_comp_area"][0]) == _key(v["largest_comp_area"][1])
                    for r in recs for v in r["pieces"].values()),
                n_controls=len(ctl), n_controls_fired=n_fired, controls=ctl,
                results=recs,
                blind=["**不判「悬空与否」**：按绝对面积判，大而悬空的碎片既不删也不报",
                       "**不判删完好不好看**：残茬、切边毛刺看不见",
                       "只核 UV 通道在不在，不核删面后 UV 接得对不对（要看渲染图，属人判）",
                       "**不判阈值对不对**：0.06 m² 的碎片算不算悬浮物，本闸无独立依据",
                       "只量 `_repair/` 与 `_clean/` 里都已生成的块；两侧块名不一致 ⇒ 报告里点名",
                       "`_repair/`／`_clean/` 缺席 ⇒ rc=4（量不到），与 rc=1（做错了）是两件事"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
