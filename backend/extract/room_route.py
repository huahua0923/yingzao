# -*- coding: utf-8 -*-
"""房间通路分派：**按图选路线**（主线=现推墙，支线=读交付墙）。

## 为什么要有这个模块

房间只有两条通路，此前是**整栋写死**在 profile 里（`rooms_from_floors` 真假），
而 2026-09-14 的实测证明**两条线各有胜负，谁都不是通解**：

| 楼 | 图上房号 | 主线 regen 命中 | 支线 single 命中 | 谁赢 |
|---|---|---|---|---|
| c033 | 143 | 71（且 F0 从 23 掉到 **3**） | **143 = 100%** | 支线大胜 |
| c034 | 180 | 63 | **158 = 88%** | 支线大胜 |
| c104 | 108 | 81 | 86 | 支线小胜 |
| c026 / c041 / c022 / c027 / c029 | — | 交付数 | **与主线逐层完全相同** | 平（换线无用） |
| c114 / c009 | — | 交付数 | 略降 | 主线小胜 |
| c103 / c116 / c006 | 189 / 89 / 221 | **191 / 83 / 205** | 111 / 35 / **27** | 主线大胜 |

⇒ 写死任何一条都会在这些楼上出事。**必须逐层按图判。**

## 判据：用图纸自己的房号当裁判

不猜、不调阈值 —— 图纸上每一层的房号是**现成的真值**（`read_labels` + `floor_of`，
与抽取器同源，不存在"第二套标定"）。哪条线把更多的图上房号**认领到互不相同的房间里**，
哪条线就更对。

评分主序 `hit` = |该线产出的房号集合 ∩ 图上该层房号集合|。
- 有上界（≤ 图上房号数）⇒ **不会奖励乱切**：把一间房劈成两半，另一半没有房号、
  末段会被 `if not number: continue` 丢掉，`hit` 一分不涨（c033 实测：候选 25~26 个
  → 最终 23/24 间，多出来的候选正是被这一条滤掉的）。
- 合并成巨块会被 `hit` 直接罚掉：一个 870㎡ 的巨块只认领 1 个房号。

次序 `waste` = 该层轮廓面积 − 有房号房间的面积和（越小越好）—— 罚"房间没铺满"。
末序偏好主线 `regen` —— 让 **35 栋满分楼的既有结果一位不变**（它们 `hit` 已经打满，
任何平手都落回主线，不会churn）。

## 与既有开关的关系

- `room_route: "auto"` → 逐层择优（本模块）；
- `room_route: "single"` ≡ `rooms_from_floors: true`（老写法仍认）；
- 都没有 → 主线 `regen`，行为与加本模块之前**逐字节相同**（老楼零影响）。

⚠️ 顺序：`single` 读的是**交付** `floors/floorN.json` 的墙，所以 `auto` 的楼必须
**先跑完内墙重建**再跑房间，否则读到的可能是粗环 blob（见 `floor_rooms_from_floors` 说明）。
"""

ROUTE_REGEN = "regen"      # 主线：floor_rooms()，从 DXF 现推墙
ROUTE_SINGLE = "single"    # 支线：floor_rooms_from_floors()，读交付 floors 的墙
DEFAULT_ROUTE = ROUTE_REGEN


def truth_by_floor(labels_number, floor_of, p):
    """图纸真值：{层: {房号, ...}}。房号空串不要（未标注），判不出层的不要。"""
    out = {}
    for x, y, t in labels_number:
        n = str(t or "").strip()
        if not n:
            continue
        f = floor_of(p, x, y)
        if f is None:
            continue
        out.setdefault(f, set()).add(n)
    return out


def score_one(polys, nums, truth, outline_area):
    """给一条线在某一层的产出打分。`nums` 是 assign_labels 的结果 {区域下标: 房号}。"""
    got = set(v for v in nums.values() if v)
    hit = len(got & truth)
    covered = 0.0
    for gi, g in enumerate(polys):
        if nums.get(gi):
            covered += float(g.area)
    waste = max(0.0, float(outline_area) - covered) if outline_area else 0.0
    big = max((float(g.area) for g in polys), default=0.0)
    return {
        "hit": hit,
        "waste": waste,
        "n": len(polys),
        "n_num": len(got),
        # 巨块占比：只用于打印，不进排序（排序里 blob 已被 hit/waste 覆盖）
        "blob_pct": round(100.0 * big / outline_area, 1) if outline_area else 0.0,
    }


def pick(cands, truth, outline_area):
    """`cands`: {路线名: (polys, nums)}。返回 (选中项, 全部打分表)。

    排序：hit 降 → waste 升 → 偏好主线。全部 `hit` 为 0（这层图纸没房号）时，
    按 waste → 主线，仍得到确定性的答案。
    """
    table = {}
    for rname, (polys, nums) in cands.items():
        s = score_one(polys, nums, truth, outline_area)
        s["route"] = rname
        s["polys"] = polys
        table[rname] = s
    if not table:
        return None, {}
    order = sorted(table.values(),
                   key=lambda s: (-s["hit"], round(s["waste"], 3),
                                  s["route"] != DEFAULT_ROUTE))
    best = order[0]
    return best, table


def why(best, table, truth_n):
    """一行可读的判词，落到抽取日志里，便于日后回溯"为什么这层选了这条线"。"""
    parts = []
    for s in sorted(table.values(), key=lambda s: (-s["hit"], s["route"])):
        parts.append("%s 命中%d/%d 浪费%.1f㎡ 房%d(%s)"
                     % (s["route"], s["hit"], truth_n, s["waste"], s["n"],
                        "巨块%.0f%%" % s["blob_pct"] if s["blob_pct"] >= 30 else "散"))
    return "%s ｜ %s" % (" ".join(parts), "胜出=" + best["route"])
