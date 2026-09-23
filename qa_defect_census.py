# -*- coding: utf-8 -*-
"""A0 · 缺陷普查 —— 把「模型不对」量成可数的清单（**只读**）。

为什么要有它
------------
现有两个门禁都测不到用户看到的病：
  * `qa_structural.py` 只查「柱是否锚定轮廓内」「有没有楼板」这类**结构不变量**，
    所以它报 48/49 PASS，而用户看着不对 —— **它量的不是用户对的东西**；
  * `_dxf_audit.py` 只查漏墙，实测全楼漏检 0-5%，它也说没问题。
「糊成一块」是过覆盖、「楼层错位/悬空」是层间几何、「门窗楼梯不对」是符号计数，
这三个前者一个都不管。本脚本把四类量汇成一张排名表 + 每栋一份 JSON。

四类量（逐栋逐层）
------------------
  M 漏墙     源图墙线采样点中被识别墙盖住的百分比               → `_dxf_audit.audit_building`
  W 糊块     **内墙**巨块数(>50㎡) / 最大块 / 墙面积÷轮廓面积 / 过覆盖比
             / 外墙环真厚 / 内墙面积占比（「只剩外壳」）
  F 错位     相邻层轮廓质心位移 / bbox 位移 / **本层墙越出下层楼板足迹的比例**
  S 符号     门/窗/窗洞/楼梯井/梯段 的交付计数（源图侧见下「未测」）

产物（**只写 `_qa/`，不动 `data/`**）
------------------------------------
  `_qa/defect_<楼>.json`    每栋：逐层四类量 + 命中的 flags + 栋级汇总
  `_qa/defect_ranking.md`   排名表（命中条数优先，再看漏墙率）

阈值与出处（全部写明来源，不许有来历不明的常数）
------------------------------------------------
  MISS_PCT=15    `_dxf_audit_report.py` 既有口径（只判别漏墙率≥15% 的层）
  BLOB_M2=50     `_defect_census.py`：正常墙最厚 0.4m × 最长 60m ≈ 24㎡，50㎡ 已无正常解释
                 ⚠️ **只用于内墙** —— 实测 7 栋的外墙环真厚 0.282~0.299m（净面积÷环周长），
                 是**正确厚度**；外墙环周长 180~1080m，拿 50㎡ 去卡它等于把设计当病。
                 首轮就是在这里误报了「每层一个巨块」，故拆成 blobs_inner / blobs_outer。
  THICK_M=0.60   外墙环真厚 > 此值判「外环偏厚」。依据：实测正常 0.282~0.299m，
                 0.60m 已是实测值的 2 倍（首轮取值，跑完看分布再定）
  INNER_MIN=0.02 内墙净面积÷轮廓面积 下限。依据：实测 c041 6.8% / c046 13%，
                 c009 仅 1.3%（「只剩外壳」）→ 2% 为判别线
  SHIFT_M=3      `_defect_census.py`：相邻层质心位移 >3m 判可疑
  RATIO=0.35     `_defect_census.py`：墙面积/轮廓面积 >0.35 判「墙占比过高」
  OVERHANG=5     首轮取值，**尚无实测依据**（排名用，非判据）；首轮跑完看分布再定

未测（诚实标注，不编数）
------------------------
  * 源图侧**窗符号数**：通用路径 `classify()` 把整个墙层都收进 `walls`（不按符号分门/梯，
    见 `classify.py` 文档串），窗块无独立图层，数不出来 → `src_win=null`。
  * 源图侧**楼梯符号位置**：同理需另建判据 → `src_stair=null`。
  二者是 A0 的下一步，不是本轮的遗漏。

用法
----
    python qa_defect_census.py                  # 全部楼（跳过无 floors 的）
    python qa_defect_census.py c046 c009       # 指定
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [ROOT, os.path.join(ROOT, "backend"),
                os.path.join(ROOT, "backend", "web"), os.path.join(ROOT, "_scratch")]
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import shapely.geometry as sg                                              # noqa: E402
import shapely.ops as so                                                   # noqa: E402

import _dxf_audit as A                                                     # noqa: E402
import _defect_census as C                                                 # noqa: E402
import run_step                                                            # noqa: E402

BASE = os.path.join(ROOT, "data", "buildings")
QA = os.path.join(ROOT, "_qa")

MISS_PCT = 15.0
BLOB_M2 = C.BLOB_M2          # 50.0，不复制成新常数，直接沿用草稿的值（只用于内墙）
THICK_M = 0.60               # 外墙环真厚上限（实测正常 0.282~0.299m）
INNER_MIN = 0.02             # 内墙净面积 ÷ 轮廓面积 下限
SHIFT_M = 3.0
RATIO = 0.35
OVERHANG = 5.0


def wall_blocks(fl):
    """把本层墙分成 (outer 环, inner)，各自算净面积（扣洞）与环周长。

    为什么要分：外墙环 = 整层圆周带，净面积 53~305㎡、周长 180~1080m，**真厚 0.28~0.30m**，
    是设计；内墙才可能是「单线墙被 buffer 成实心块」的病（BLOB_M2 的依据就是它）。
    """
    # ★ 2026-09-14 修：`parapet`（女儿墙）原先落进 `inner` 桶 —— 而它是**屋面外缘的环带**，
    #   净面积 = 周长 × 厚度（c006 F6 两道环各 73㎡），于是被 `BLOB_M2=50` 判成
    #   「内墙巨块x2」，把整层顶成 ERROR。同文件第 86-87 行的注释早就写明
    #   「外墙环 净面积 53~305㎡ 是设计」，只是那条豁免只给了 `type=="outer"`。
    #   ⇒ 环带（outer/parapet）与内墙分开判：环带看**厚度**，内墙才看**单块面积**。
    outer, parapet, inner = [], [], []
    for w in (fl.get("walls") or []):
        ring = w.get("poly") or []
        if len(ring) < 3:
            continue
        a = C.poly_area(ring)
        for h in (w.get("holes") or []):
            if len(h) >= 3:
                a -= C.poly_area(h)
        a = max(0.0, a)
        rec = (a, w)
        t = w.get("type")
        if t in ("outer", "parapet"):
            pg = _ring_poly(ring)
            L = pg.exterior.length if pg is not None else 0.0
            (outer if t == "outer" else parapet).append((rec, L))
        else:
            inner.append(rec)
    return outer, inner, parapet


# ---------------------------------------------------------------- 几何小工具
def _ring_poly(ring):
    if not ring or len(ring) < 3:
        return None
    try:
        pg = sg.Polygon([(float(p[0]), float(p[1])) for p in ring])
        return pg.buffer(0) if not pg.is_valid else pg
    except Exception:                                                      # noqa: BLE001
        return None


def walls_union(fl):
    """本层墙（扣洞后）的并集 —— 越界率的分母。"""
    geoms = []
    for w in (fl.get("walls") or []):
        outer = _ring_poly(w.get("poly"))
        if outer is None:
            continue
        for h in (w.get("holes") or []):
            hp = _ring_poly(h)
            if hp is not None:
                outer = outer.difference(hp)
        if not outer.is_empty:
            geoms.append(outer)
    return so.unary_union(geoms) if geoms else None


def overhang_pct(cur_union, prev_outline):
    """本层墙落在**下层**楼板足迹之外的比例（%）。上层墙悬空的直接量。"""
    if cur_union is None or cur_union.is_empty or not prev_outline:
        return None, None
    base = _ring_poly(prev_outline)
    if base is None or base.is_empty:
        return None, None
    try:
        out = cur_union.difference(base)
        return round(out.area / cur_union.area * 100, 1), round(out.area, 1)
    except Exception:                                                      # noqa: BLE001
        return None, None


# ---------------------------------------------------------------- 逐栋
def defect_of(name):
    floors_dir = os.path.join(BASE, name, "floors")
    if not os.path.isdir(floors_dir):
        return None
    fs = sorted(int(os.path.basename(f)[5:-5]) for f in glob.glob(
        os.path.join(floors_dir, "floor*.json")))
    if not fs:
        return None

    p = run_step.load_profile(name)
    try:
        miss = {r["F"]: r for r in A.audit_building(name)}
    except Exception as e:                                                 # noqa: BLE001
        print("  !! %s 漏墙率算不了: %s" % (name, str(e)[:70]))
        miss = {}
    src_buf_m2 = 2.0 * p.wall_fallback      # 源线按引擎自有名义厚 buffer 出的面积/m
    rows, prev = [], None
    for F in fs:
        with open(os.path.join(floors_dir, "floor%d.json" % F), encoding="utf-8") as f:
            fl = json.load(f)
        r = C.census_floor(fl)
        blk_outer, blk_inner, blk_parapet = wall_blocks(fl)
        outer_net = sum(a for (a, _w), _L in blk_outer)
        outer_len = sum(L for (_a, _w), L in blk_outer)
        outer_thick = round(outer_net / outer_len, 3) if outer_len else None
        # 女儿墙 = 屋面外缘环带：看**厚度**（净面积/环周长），不看单块面积 —— 同外墙环的道理。
        par_net = sum(a for (a, _w), _L in blk_parapet)
        par_len = sum(L for (_a, _w), L in blk_parapet)
        par_thick = round(par_net / par_len, 3) if par_len else None
        inner_net = sum(a for a, _w in blk_inner)
        blobs_in = sum(1 for a, _w in blk_inner if a > BLOB_M2)
        blobs_out = sum(1 for (a, _w), _L in blk_outer if a > BLOB_M2)
        blobs_par = sum(1 for (a, _w), _L in blk_parapet if a > BLOB_M2)
        max_in = max((a for a, _w in blk_inner), default=0.0)
        inner_share = (inner_net / r["out_area"]) if r["out_area"] else 0.0
        m = miss.get(F, {})
        u = walls_union(fl)
        oh_pct, oh_m2 = overhang_pct(u, (prev or {}).get("outline"))
        src_m = m.get("src_m")
        # 过覆盖比 = 识别墙面积 ÷ (源线长 × 2×wall_fallback) —— 分母用引擎自己的名义厚，
        # 不引入外来常数；≫1 即「识别出比源线所能支撑的更多的墙」（糊成一块的病征）。
        over = (round(r["wall_area"] / (src_m * src_buf_m2), 2)
                if src_m and src_buf_m2 else None)
        shift = None
        if prev and prev["centroid"] and r["centroid"]:
            dx = r["centroid"][0] - prev["centroid"][0]
            dy = r["centroid"][1] - prev["centroid"][1]
            shift = round((dx * dx + dy * dy) ** 0.5, 2)
        flags = []
        if m.get("miss_pct", 0) >= MISS_PCT:
            flags.append("漏墙>=%.0f%%" % MISS_PCT)
        if blobs_in:
            flags.append("内墙巨块x%d" % blobs_in)
        if outer_thick is not None and outer_thick > THICK_M:
            flags.append("外环厚%.2fm" % outer_thick)
        if par_thick is not None and par_thick > THICK_M:
            flags.append("女儿墙厚%.2fm" % par_thick)
        if r["out_area"] > 200 and inner_share < INNER_MIN:
            flags.append("只剩外壳(内墙%.1f%%)" % (inner_share * 100))
        if r["wall_ratio"] > RATIO:
            flags.append("墙占比>%.2f" % RATIO)
        if over is not None and over >= 3.0:
            flags.append("过覆盖%.1fx" % over)
        if shift is not None and shift > SHIFT_M:
            flags.append("层错位%.1fm" % shift)
        if oh_pct is not None and oh_pct >= OVERHANG:
            flags.append("越界%.0f%%" % oh_pct)
        rows.append(dict(
            F=F,
            # M 漏墙
            miss_pct=m.get("miss_pct"), miss_m=m.get("miss_m"), src_m=src_m,
            # W 糊块
            n_walls=r["n_walls"], wall_area=round(r["wall_area"], 1),
            out_area=round(r["out_area"], 1), wall_ratio=round(r["wall_ratio"], 3),
            blobs=r["blobs"], blobs_inner=blobs_in, blobs_outer=blobs_out,
            max_wall=round(r["max_wall"], 1), max_wall_inner=round(max_in, 1),
            outer_thick_m=outer_thick, inner_area=round(inner_net, 1),
            inner_share=round(inner_share, 3), over_ratio=over,
            # F 错位
            centroid_shift_m=shift, overhang_pct=oh_pct, overhang_m2=oh_m2,
            # S 符号（交付侧）
            n_doors=r["n_doors"], n_windows=r["n_windows"], win_holes=r["win_holes"],
            n_stairwells=r["n_stairwells"], n_stairs=r["n_stairs"],
            # 源图侧（本轮未测，见模块文档串）
            src_win=None, src_stair=None,
            flags=flags))
        prev = dict(r, outline=fl.get("outline"))
    nflag = sum(1 for r in rows if r["flags"])
    worst = max((r["miss_pct"] or 0) for r in rows) if rows else 0
    return dict(building=name, floors=len(rows), floors_flagged=nflag,
                max_miss_pct=worst,
                total_blobs=sum(r["blobs_inner"] for r in rows),
                min_inner_share=min((r["inner_share"] for r in rows), default=0),
                max_outer_thick_m=max((r["outer_thick_m"] or 0) for r in rows) if rows else 0,
                max_overhang_pct=max((r["overhang_pct"] or 0) for r in rows) if rows else 0,
                max_shift_m=max((r["centroid_shift_m"] or 0) for r in rows) if rows else 0,
                rows=rows)


# ---------------------------------------------------------------- 产物
def write_json(path, obj):
    """原子写：tmp + os.replace（直写会把交付文件截成 0 字节）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_ranking(results):
    """排名：先按「有 flag 的层数」降序，再看最大漏墙率 —— 不用加权综合分（避免编权重）。"""
    rank = sorted(results, key=lambda d: (-d["floors_flagged"], -d["max_miss_pct"],
                                          -d["total_blobs"]))
    L = ["# A0 缺陷排名（只读普查）",
         "",
         "> 生成：`python qa_defect_census.py`。**只写 `_qa/`，不动 `data/`。**",
         "> 排序：有 flag 的层数 ↓，再最大漏墙率 ↓。未加权 —— 权重没有任何依据可依。",
         "",
         "| # | 楼 | 层数 | 有flag层 | 最大漏墙% | 内墙巨块 | 最小内墙占比 | 外环最大厚m | 最大越界% | 最大错位m |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, d in enumerate(rank, 1):
        L.append("| %d | %s | %d | **%d** | %.1f | %d | %.1f%% | %.3f | %.1f | %.2f |"
                 % (i, d["building"], d["floors"], d["floors_flagged"],
                    d["max_miss_pct"], d["total_blobs"], d["min_inner_share"] * 100,
                    d["max_outer_thick_m"], d["max_overhang_pct"], d["max_shift_m"]))
    L += ["", "## 逐层明细（只列命中 flag 的层）", ""]
    for d in rank:
        hits = [r for r in d["rows"] if r["flags"]]
        if not hits:
            continue
        L += ["### %s（%d/%d 层命中）" % (d["building"], len(hits), d["floors"]), "",
              "| F | 漏墙% | 墙数 | 墙面积 | 墙/轮廓 | 内墙巨块 | 内墙最大块 | 内墙占比 | 外环厚m | 过覆盖 | 错位m | 越界% | 门 | 窗 | 梯井 | flags |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in hits:
            L.append("| %d | %s | %d | %.0f | %.2f | %d | %.0f | %.1f%% | %s | %s | %s | %s | %d | %d | %d | %s |"
                     % (r["F"], r["miss_pct"], r["n_walls"], r["wall_area"],
                        r["wall_ratio"], r["blobs_inner"], r["max_wall_inner"],
                        r["inner_share"] * 100, r["outer_thick_m"],
                        r["over_ratio"], r["centroid_shift_m"], r["overhang_pct"],
                        r["n_doors"], r["n_windows"], r["n_stairwells"],
                        "、".join(r["flags"])))
        L.append("")
    path = os.path.join(QA, "defect_ranking.md")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    os.replace(tmp, path)
    return rank, path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = args or sorted(d for d in os.listdir(BASE)
                           if os.path.isdir(os.path.join(BASE, d, "floors")))
    os.makedirs(QA, exist_ok=True)
    results = []
    for name in names:
        d = defect_of(name)
        if d is None:
            print("跳过 %s（无 floors）" % name)
            continue
        write_json(os.path.join(QA, "defect_%s.json" % name), d)
        results.append(d)
        print("%-7s 层%3d 有flag层%3d 最大漏墙%6.1f%% 巨块%3d 最大越界%5.1f%% 最大错位%5.2fm"
              % (name, d["floors"], d["floors_flagged"], d["max_miss_pct"],
                 d["total_blobs"], d["max_overhang_pct"], d["max_shift_m"]))
    rank, path = write_ranking(results)
    print("\n=== 排名（前 15）===")
    for i, d in enumerate(rank[:15], 1):
        print("%2d. %-7s 有flag层 %3d/%-3d 最大漏墙 %5.1f%% 巨块 %3d"
              % (i, d["building"], d["floors_flagged"], d["floors"],
                 d["max_miss_pct"], d["total_blobs"]))
    print("\n写好：_qa/defect_<楼>.json ×%d ；排名表 %s" % (len(results), path))


if __name__ == "__main__":
    main()
