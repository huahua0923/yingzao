# -*- coding: utf-8 -*-
"""电梯井**图例**识别（GB/T 50104：井道矩形 + 一对交叉对角线）。

## 为什么要单开这条判据（2026-09-14 实测，c006）

原实现 `floor.detect_elevator_shafts` 只认「**墙 union 里的矩形洞**」。c006 实测它
**一条真井都收不到，反而收了 1 间卫生间**——因为电梯图例的 X 对角线画在
`4.2墙体` 图层上，被 `classify_line` 当墙候选 **buffer 成实心块**（识别结果里那块
`(-7.47,6.81) 宽2.80 高3.65` 就是它），**井被自己填死**，union 里当然没有洞。
判据尺寸窗 [1.0,2.0]×[1.5,3.0] 本身没问题：实测 3 口真井是 1.39×1.85、1.01×1.65、
1.01×1.65，全在窗内——**错的是找的对象，不是阈值**。

## 判据（规则优先，不靠阈值调参）

一对**交叉对角线**同时满足：
  · 两条长度相近（相对差 ≤ `LEG_LEN_RTOL`）
  · 两条**中点重合**（距 ≤ `LEG_MID_TOL`）
  · 交叉角在 `[LEG_ANG_MIN, LEG_ANG_MAX]`
  · 各自**非轴对齐**（与轴夹角 ≥ `LEG_SKEW_MIN`）——轴对齐的是普通墙段
  · 长度在 `[LEG_MIN_LEN, LEG_MAX_LEN]`
井 bbox = 四条端点（其实是两条线的四个端点）的外包围。

★ 采用本判据的前提是**尺度无关**：它只在"长度/距离/角度"上比较，所以同一份逻辑
既能用于 `classify_line` 的模型空间 mm（`scale=0.001`），也能用于 `floor.py` 的
局部米（`scale=1.0`）。两侧**必须同式**，否则"剔掉的线"与"认下的井"对不上。

## 与楼梯的区别（别把楼梯的 X 也认成井）

楼梯平面上也常有交叉线（"不上人"符号、梯段起止线），故加**井尺寸合理性**：
短边 ≥ `WELL_MIN_SIDE`、长边 ≤ `WELL_MAX_SIDE`、长短比 ≤ `WELL_MAX_RATIO`。
实测电梯井 1.39×1.85（比 1.33）与 1.01×1.65（比 1.63）通过；楼梯井 2.8×2.8 不通过。
"""
import math

LEG_MIN_LEN = 1.2          # 对角线长下限（米）
LEG_MAX_LEN = 5.0          # 上限
LEG_LEN_RTOL = 0.10        # 两条对角线长度相对差上限
LEG_MID_TOL = 0.30         # 两条对角线中点距上限（米）
LEG_ANG_MIN = 40.0         # 交叉角下限（度）
LEG_ANG_MAX = 140.0        # 上限（超过 140 近似共线，不是 X）
LEG_SKEW_MIN = 15.0        # 与坐标轴夹角下限（度）——轴对齐的留给普通墙
WELL_DEDUP_R = 1.2         # 同井去重半径（米）：井间距最小 2.4m，取一半
WELL_MIN_SIDE = 0.8        # 井短边下限（米）
WELL_MAX_SIDE = 4.0        # 井长边上限（米）
WELL_MAX_RATIO = 3.0       # 井长短比上限


def _mid(a, b):
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def _ang(a, b):
    """线段与 x 轴的夹角，归一化到 [0,180)。"""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0


def wells_from_legend(pts_list, scale=1.0):
    """从 2 点线段里配对出电梯井图例。

    `pts_list`: `[[(x0,y0),(x1,y1)], ...]`，单位任意（用 `scale` 换算米）。
    `scale`: 坐标 × scale = 米（mm 坐标传 0.001，已是米传 1.0）。

    返回 `(wells, used)`：
      · `wells` = `[{"cx","cy","x0","y0","x1","y1","w","d"}]`，**原坐标单位**
        （即未乘 scale），与输入同坐标系，调用方不必再换算。
      · `used`  = `set(索引)`，**所有**参与了 X 配对的对角线下标。去重只影响
        `wells` 列表，不影响 `used`——被合并掉的那对仍然是符号线，一样要从墙里剔。
    """
    cands = []
    for i, p in enumerate(pts_list):
        if p is None or len(p) != 2:
            continue
        (x0, y0), (x1, y1) = p[0], p[1]
        L = math.hypot(x1 - x0, y1 - y0) * scale
        if not (LEG_MIN_LEN <= L <= LEG_MAX_LEN):
            continue
        g = _ang((x0, y0), (x1, y1))
        # 到「最近坐标轴」的角度偏差：竖直线 g=90 → 0，水平线 g=0/180 → 0，45 度斜线 → 45。
        # 原判据 min(g, 180-g) 对竖直线恒为 90 → **永不剔除**（2026-09-16 实测写出条目）。
        _dev = abs(((g + 45.0) % 90.0) - 45.0)
        if _dev < LEG_SKEW_MIN:
            continue
        cands.append((i, (x0, y0), (x1, y1), L, g))

    used = set()
    raw = []
    for a in range(len(cands)):
        ia, a0, a1, La, ga = cands[a]
        for b in range(a + 1, len(cands)):
            ib, b0, b1, Lb, gb = cands[b]
            if abs(La - Lb) > LEG_LEN_RTOL * max(La, Lb):
                continue
            ma, mb = _mid(a0, a1), _mid(b0, b1)
            if math.hypot(ma[0] - mb[0], ma[1] - mb[1]) * scale > LEG_MID_TOL:
                continue
            da = abs(ga - gb) % 180.0
            da = min(da, 180.0 - da)
            if not (LEG_ANG_MIN <= da <= LEG_ANG_MAX):
                continue
            xs = [a0[0], a1[0], b0[0], b1[0]]
            ys = [a0[1], a1[1], b0[1], b1[1]]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            sw, sd = (x1 - x0) * scale, (y1 - y0) * scale
            lo, hi = min(sw, sd), max(sw, sd)
            if lo < WELL_MIN_SIDE or hi > WELL_MAX_SIDE or hi / max(lo, 1e-9) > WELL_MAX_RATIO:
                continue
            used.add(ia)
            used.add(ib)
            raw.append({"cx": ma[0], "cy": ma[1], "x0": x0, "y0": y0,
                        "x1": x1, "y1": y1, "w": sw, "d": sd})

    wells = []
    for w in sorted(raw, key=lambda w: (-w["cy"], w["cx"])):
        if any(math.hypot(w["cx"] - k["cx"], w["cy"] - k["cy"]) * scale < WELL_DEDUP_R
               for k in wells):
            continue
        wells.append(w)
    return wells, used


# —— 跨层归一 ————————————————————————————————————————————————————————
FLOOR_TOL = 0.60      # 同一口竖井在各层允许的位置偏差（米）——井间距最小 2.4m
FLOOR_OFF_TOL = 0.25  # 超过它 = 该层「错层」嫌疑（只报警，不改数）


def _cx(w):
    """井心 X —— 兼容两种口径：图例井 `cx/cy`（`wells_from_legend`）与交付井 `x/y`。"""
    return w.get("cx", w.get("x", 0.0))


def _cy(w):
    return w.get("cy", w.get("y", 0.0))


def group_by_floor(per_floor):
    """把逐层的井聚成**竖井**（跨层归一）。

    `per_floor`: `{层号: [井, ...]}`（各井同坐标系；要求 `to_local` 对这批层同原点，
    c006 实测 F1–F10 井位逐位相同，故成立）。井可用图例口径（cx/cy）或交付口径（x/y）。

    返回 `(shafts, report)`：
      · `shafts` = `[{"cx","cy","w","d","floors":{层:井}, "holes":[层], "offsets":[(层,偏移)]}]`
      · `report` = 每口井一行的人类可读结论（贯通 / 缺 / 漏 / ★偏）
    """
    allw = [(F, w) for F in sorted(per_floor) for w in per_floor[F]]
    shafts = []
    for F, w in allw:
        for s in shafts:
            if math.hypot(_cx(w) - s["cx"], _cy(w) - s["cy"]) <= FLOOR_TOL:
                s["floors"][F] = w
                n = len(s["floors"])
                s["cx"] = sum(_cx(x) for x in s["floors"].values()) / n
                s["cy"] = sum(_cy(x) for x in s["floors"].values()) / n
                break
        else:
            shafts.append({"cx": _cx(w), "cy": _cy(w), "floors": {F: w}})
    floors = sorted(per_floor)
    report = []
    for s in shafts:
        have = sorted(s["floors"])
        off = [(F, round(math.hypot(_cx(w) - s["cx"], _cy(w) - s["cy"]), 3))
               for F, w in s["floors"].items()
               if math.hypot(_cx(w) - s["cx"], _cy(w) - s["cy"]) > FLOOR_OFF_TOL]
        holes = [F for F in range(have[0], have[-1] + 1) if F not in s["floors"]] if have else []
        missing = [F for F in floors if F not in s["floors"]]
        s["holes"], s["offsets"], s["missing"] = holes, off, missing
        # 宽度取**众数**（同一口井各层识别宽度可能差几厘米；众数=最一致的那个）
        wv = {}
        for w in s["floors"].values():
            k = (round(w.get("w", 0), 2), round(w.get("d", 0), 2))
            wv[k] = wv.get(k, 0) + 1
        s["w"], s["d"] = max(wv.items(), key=lambda kv: kv[1])[0] if wv else (0.0, 0.0)
        mark = []
        if off:
            mark.append("★偏 " + " ".join("F%d(%.2f)" % o for o in off))
        if holes:
            mark.append("漏 " + " ".join("F%d" % F for F in holes))
        elif missing:
            mark.append("缺 " + " ".join("F%d" % F for F in missing))
        report.append("井 (%7.2f,%7.2f) w%.2f d%.2f  覆盖 %2d/%d 层  %s"
                      % (s["cx"], s["cy"], s["w"], s["d"], len(have), len(floors),
                         "  ".join(mark) if mark else "贯通 ✓"))
    return shafts, report
