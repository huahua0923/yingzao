# -*- coding: utf-8 -*-
r"""**从源图现读出楼栋档案**，写进 `rebuild/构件库/楼栋.json`（只增/只改本脚本点名的楼栋）。

为什么要它（2026-10-17）：剩下 65 栋楼，逐栋手抄 keep_layers 既不现实也一定会抄错 ——
而抄错的症状是「识别读到 0 条墙线」/「台账读不到房间号」，**不报错**，最后建出一栋空房子
（铁律 018：同一个量不许有两个来源；铁律 183：一个错法换个函数还会再犯）。
所以档案里凡是**图上写着的事实**（层名、图层名、画法）一律从图上现读，脚本只写「怎么读」。

写什么：
  · title/src_dxf/output/sheet_mode
  · keep_layers —— 墙/柱/轴线/Defpoints/面积/房间号/用途/单位，**只收图上真有的层**
  · drop_layers —— 固定的丢弃清单（各图通用）
  · drawing     —— 全部 `auto`（柱/门/梯的画法逐层现认，见 redraw/recognize 里的 auto 分支）
  · door_carve  —— true（这批图的墙线连续穿过门洞；若墙本来就断，抠洞是空操作）
  · **不写 floor_names / basement** —— 由 `building._derive_floors()` 从标题栏现读

用法：
    python -I rebuild/tools/author_profiles.py c009 c022 c025 --dry
    python -I rebuild/tools/author_profiles.py c009 c022 c025
    python -I rebuild/tools/author_profiles.py c024 --stem c024=C024-宗岳楼（计算站楼）

退出码：0 全部写成 · 2 参数错 / 找不到源图 / 前缀有歧义 · 4 有楼栋**没读到**该有的层
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SRC_DIR = r"D:\项目\gym3d\材料\dxf_output"
PROF = os.path.join(os.path.dirname(HERE), "构件库", "楼栋.json")

DROP = ["1图框", "2注释", "0", "WINDOW_TEXT", "9搬迁", "8说明", "面积分区"]


def _stems():
    return [f[:-4] for f in os.listdir(SRC_DIR) if f.lower().endswith(".dxf")]


def _resolve(bid, stems, overrides):
    """楼栋 id → 源图文件名（前缀匹配；不唯一就报错，**不猜**）。"""
    if bid in overrides:
        return overrides[bid]
    hit = [s for s in stems if s.split("-")[0].lower() == bid.lower()]
    if len(hit) != 1:
        raise SystemExit("★ %s 匹配到 %d 个源图 %s —— 用 --stem %s=<文件名> 指定"
                         % (bid, len(hit), hit, bid))
    return hit[0]


def _census(path):
    """图层 → 各类实体数。一次读全图（这 105 张图里最大的一两万实体，读一遍几秒）。"""
    import ezdxf
    doc = ezdxf.readfile(path)
    cnt = {}
    for e in doc.modelspace():
        d = cnt.setdefault(e.dxf.layer, {"n": 0})
        d["n"] += 1
        t = e.dxftype()
        d[t] = d.get(t, 0) + 1
    return cnt


def _door_census(path, wall):
    """墙层上的门：两种画法各数一遍（符号 / 开启弧），并按证据选一种 `doors` 口径。

    符号判据（2026-10-17 对 63 栋普查后定的，三条同时满足）：
      · **带弧**：至少一段 bulge ≠ 0 —— 实测真门符号 100% 有开启弧，假符号 0%；
        C114 的 580 个 6 点族（725×440）**全无弧**，只按下面两条会被当成 580 扇门。
      · **近方形**：短边/长边 ≥ 0.5 —— 门符号含门扇+开启弧，是方的；
        窗是**贴墙的长条**（实测 C025/C028 2250×250、C114 2100×300）。
      · 等墙向长边 ∈ [600, 2500] mm。
      `doors_min_pts` 取**出现 ≥ 20 次的点数族里最小的那个**：同一栋楼里单扇/双扇/不同宽度
      用不同点数，要的是「能从多少点起算」，不是最多的那一族。

    选哪种画法（**写进档案，不留给 auto 去猜**）：
      · 一边不到另一边的 1/4 ⇒ 那一边是零星的，按多的那种建
        （C022 124:0、C072 810:3、C112 30:155、C004 0:84 都是这种形状）；
      · 同量级 ⇒ `symbols`（符号判据更硬：带弧 + 近方形 + 宽度窗口）；
      · 两边都没有 ⇒ `auto`（跑起来会如实打 0）。
      这挡住一个真实隐患：只有 2~6 根杂弧、却有几百个符号的楼（C022/C018/C103/C072…），
      原先的「弧优先」会只建出 2~6 扇门而**不报错**。
    """
    from collections import Counter
    from ezdxf import bbox as BB
    import ezdxf
    doc = ezdxf.readfile(path)
    fam = Counter()
    arcs = Counter()
    widths = []                     # (点数, 等墙向长边 mm) —— 定了 min_pts 之后再取
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "ARC" and e.dxf.layer == wall:
            arcs[round(float(e.dxf.radius))] += 1
            continue
        if t != "LWPOLYLINE" or e.dxf.layer != wall:
            continue
        pts = e.get_points()
        n = len(pts)
        if n < 6:
            continue
        if not any(abs(float(p[4])) > 1e-6 for p in pts):
            continue                          # 没有开启弧 ⇒ 不是门符号
        bb = BB.extents([e])
        if not bb.has_data:
            continue
        w = bb.extmax.x - bb.extmin.x
        h = bb.extmax.y - bb.extmin.y
        lo, hi = sorted((w, h))
        if not (600.0 <= hi <= 2500.0) or hi <= 0 or (lo / hi) < 0.5:
            continue
        fam[n] += 1
        widths.append((n, round(hi, 1)))
    strong = [n for n, c in fam.items() if c >= 20]
    min_pts = min(strong) if strong else None
    sym = sum(c for n, c in fam.items() if min_pts and n >= min_pts)
    # 本楼门的**名义净宽** = 过筛符号的等墙向长边（jamb=0 时两者相等）。
    # build3d 的自检拿它逐樘对账：认到的宽度必须来自**图上量到的那些族**，
    # 而不是默认的 1100/2400（那组数是 c005/c001 的，套到别的楼每层都会红）。
    wset = sorted({w for n, w in widths if min_pts and n >= min_pts})[:16]
    # 弧窗口：**常见**半径（≥20 根）才算门弧；零星 2~6 根不参与选口径
    common = [r for r, c in arcs.items() if c >= 20 and 300 <= r <= 3000]
    win = None
    if common:
        win = [round(min(common) * 0.9, 1), round(max(common) * 1.1, 1)]
    n_arc = sum(c for r, c in arcs.items() if win and win[0] <= r <= win[1])
    if not sym and not n_arc:
        mode = "auto"
    elif not n_arc or n_arc < 0.25 * sym:
        mode = "symbols"          # 弧是零星的（杂弧/弧墙）：符号说了算（C022 124:0、C072 810:3）
    elif not sym or sym < 0.25 * n_arc:
        mode = "arcs"             # 符号是零星的：弧说了算（C112 30:155、C004 0:84）
    else:
        mode = "symbols"          # 两者同量级：符号的判据更硬（带弧+近方形+宽度窗口）
    return {"min_pts": min_pts, "fam": dict(sorted(fam.items())), "sym": sym,
            "arcs": dict(sorted(arcs.items())), "win": win, "n_arc": n_arc, "mode": mode,
            "widths": wset}


def _pick(cnt, pred, prefer_text=False):
    """候选层里取实体数最多的那一层；`prefer_text` 时按 TEXT+MTEXT 数排。"""
    cand = [n for n in cnt if pred(n)]
    if not cand:
        return None
    if prefer_text:
        return max(cand, key=lambda n: cnt[n].get("TEXT", 0) + cnt[n].get("MTEXT", 0))
    return max(cand, key=lambda n: cnt[n]["n"])


def _keep_layers(cnt):
    wall = _pick(cnt, lambda n: "墙体" in n) or _pick(cnt, lambda n: n.endswith("墙"))
    col = _pick(cnt, lambda n: "柱" in n)
    axis = _pick(cnt, lambda n: "轴线" in n)
    area = _pick(cnt, lambda n: "面积" in n and "分区" not in n, prefer_text=True)
    room = _pick(cnt, lambda n: "房间号" in n, prefer_text=True)
    keep = [x for x in (wall, col, axis, "Defpoints" if "Defpoints" in cnt else None,
                        area, room) if x]
    # ★ 2026-10-18：原来每种只留**一层**（`_pick` 取文字最多的那层）⇒ 图上同时有
    #   「7使用单位 + 8功能」时，功能层被**静默丢掉**；台账里用途整列为空，症状与
    #   「源图没画用途」同形（铁律 158）。实测 11 栋受影响：c007 丢 `8功能`(164)、
    #   c009 丢 `9调整单位`(127)、c059~c065 丢 `7用途类型`(133~288)、c063 丢 `8房间用途`(14)。
    #   用途/单位是**人写标注**、不是几何 ⇒ 全留，由 `a1/rooms.py` 的配对闸去选。
    for k in ("用途", "单位", "功能", "名称"):
        for n in sorted(cnt, key=lambda n: (-(cnt[n].get("TEXT", 0) + cnt[n].get("MTEXT", 0)), n)):
            if k in n and n not in keep:
                keep.append(n)
    return keep


def main(argv):
    dry = "--dry" in argv
    argv = [a for a in argv if a != "--dry"]
    overrides = {}
    while "--stem" in argv:
        i = argv.index("--stem")
        k, _, v = argv[i + 1].partition("=")
        overrides[k] = v
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        print(__doc__)
        return 2

    stems = _stems()
    with open(PROF, encoding="utf-8") as f:
        prof = json.load(f)
    rc = 0
    rows = []
    for bid in argv:
        # ★ 2026-10-17：原来一条楼栋解析失败（如 C024 有两个同前缀源图）会 **SystemExit**，
        #   而写盘在循环之后 ⇒ 前面 62 栋读出来的档案**一起作废**（一行都没写）。
        #   一栋出错只该废一栋：记下来、跳过、最后 rc=4。
        try:
            stem = _resolve(bid, stems, overrides)
        except SystemExit as e:
            print(str(e))
            rc = 4
            continue
        path = os.path.join(SRC_DIR, stem + ".dxf")
        cnt = _census(path)
        keep = _keep_layers(cnt)
        wall = keep[0] if keep else None          # `_keep_layers` 第一项就是墙层
        dc = _door_census(path, wall) if wall else {"min_pts": None, "fam": {}, "sym": 0,
                                                    "arcs": {}, "win": None, "n_arc": 0,
                                                    "mode": "auto"}
        min_pts, fam = dc["min_pts"], dc["fam"]
        has_area = any("面积" in n for n in keep)
        has_room = any("房间号" in n for n in keep)
        if not (has_area and has_room):
            print("★ %s 缺台账层（面积=%s 房间号=%s）—— 档案照写，但台账会是空的"
                  % (bid, has_area, has_room))
            rc = 4
        dw = {"columns": "auto", "doors": dc["mode"], "stairs": "auto"}
        if dc["mode"] == "arcs" and dc["win"]:
            # 这批图的开启弧半径不都在默认的 650~1700 里（C004F1 实测 567、C020 600/730、
            # C075 500、C023 500）⇒ 窗口按**图上真有的常见半径**写，不留默认值去漏门。
            dw["doors_arc_r_mm"] = dc["win"]
            dw["doors_open_mm"] = [float(r) for r in
                                   sorted({r for r, c in dc["arcs"].items()
                                           if c >= 20 and dc["win"][0] <= r <= dc["win"][1]})][:16]
            dw["doors_open_tol"] = 10.0
        elif dc["widths"]:
            dw["doors_open_mm"] = [float(w) for w in dc["widths"]]
            dw["doors_open_tol"] = 10.0
        if min_pts:
            # ★★ 2026-10-17：`redraw.DOOR_MIN_PTS` 默认 16 是照 c005/c001 那批图定的
            #   （16 点单门 + 23 点双门）。这批图里有 6~15 点的门符号族 ⇒ 不写就**一扇门都不认**
            #   （c025/c028/c114 实测 0 樘，c041 每层 2~3 樘），而症状与「源图没画门」同形。
            #   另外这几个开关**必须一起写**：只降点数不筛形状，窗（贴墙长条）会被当成门抠全高洞口。
            dw.update({"doors_min_pts": min_pts,
                       "doors_jamb_mm": 0.0,
                       "doors_width_mm": [600.0, 2500.0],
                       "doors_shape_ratio": 0.5,
                       "doors_need_arc": True})
        prof[bid] = {
            "title": stem.split("-", 1)[1] if "-" in stem else stem,
            "src_dxf": path,
            "sheet_mode": "auto",
            "keep_layers": keep,
            "drop_layers": list(DROP),
            "output": bid,
            "drawing": dw,
            "door_carve": True,
            # 2026-10-17 用户令：**屋顶的电梯塔楼、楼梯塔楼都不建**（女儿墙照旧）
            "roof_stair": False,
        }
        rows.append((bid, stem, len(keep), ", ".join(keep),
                     "门=%s 符号 %d（族 %s，最少 %s 点） 弧 %d（窗 %s）"
                     % (dc["mode"], dc["sym"], fam, min_pts, dc["n_arc"], dc["win"])))

    w = max(len(r[0]) for r in rows) if rows else 4
    for bid, stem, n, keep, door in rows:
        print("%-*s %-30s keep %d : %s\n%s  %s" % (w, bid, stem, n, keep, " " * w, door))
    if dry:
        print("（--dry：没有写盘）")
        return rc
    with open(PROF, "w", encoding="utf-8", newline="\n") as f:
        json.dump(prof, f, ensure_ascii=False, indent=1)
    print("写 %s：新增/更新 %d 栋（其余条目一字未动）" % (PROF, len(rows)))
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
