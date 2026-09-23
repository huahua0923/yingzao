# -*- coding: utf-8 -*-
"""楼梯 —— 全仓唯一的「楼梯井 ↔ 墙」模块（对标 `openings.py` 之于门）。

## 为什么要有这个模块

楼梯井现在的定义是 `geometry.detect_stairwells` 给出的**踏步线包围盒**：只框住一列
踏步，不含休息平台，也**完全没有问过墙**。于是：

  · 假墙：踏步线被 `pair_wall_faces` 贪心配成 0.3m 厚的「墙」，把井塞满
    （`stair-tread-fake-walls`）。剔除规则在 `geometry._stair_tread_indices` /
    `_stair_midline_indices`，但**只在配对前生效**；已落盘的楼层是旧结果，仍旧带假墙。
  · 井太小：包围盒只到踏步外缘，楼板洞按它挖 → 洞比真实井道小一圈，休息平台没洞。
  · 井不真：包围盒四边大部分落在空地上（实测 ny27 围合率 0.07），
    因为它是「踏步的盒子」而不是「井道的盒子」。

## 判据

**井道 = 踏步包围盒沿四向扩到最近的实体墙内皮**（`shaft_of`）。这是**还原**不是臆造：
边界取自图上真实存在的墙。四向都扩不到墙 → 这口井围合不起来，返回 None，
调用方登记 `unresolved`，**不渲染楼梯**。

⚠️ **楼梯间天然开一侧**：人要从走廊进楼梯间，所以四向里总有一个方向（通常是休息平台
外侧那条短边）没有墙，只有门垛。实测 c027 每口井恰好 1 个空向 —— 这是**正常**，不是缺陷。
判「井不真」看围合率（有 1 个空向时理论上限约 1 − W/2(W+D) ≈ 0.84），**空向 ≥2 才可疑**。

**实体墙** = 排除「碎片」的墙。碎片 = 面积小 + 最窄边 ≤0.35m + 最长边 ≤3.2m
（踏步假墙 0.3×1.2、窗台线、门符号残渣都是这个形状）。
⚠️ 围合率必须用**实体墙**量：井 bbox 本来就是踏步的包围盒，假墙正压在这条周长上，
用全部墙量会得到恒为 1.00 的**自证**结果（同 P2 挖穿率最初的自证错误）。

## 自证陷阱（照抄 P2 的教训）

`enclosure_rate(shaft, solid)` 量的必须是**交付的墙**与**扩后的井**；
拿 `detect_stairwells` 的原始包围盒 + 全部墙去量，两个量互相定义，测出来永远好看。
"""
import math

from shapely.geometry import Point, box as _box
from shapely.ops import unary_union

from . import openings

FRAG_MIN_SIDE = 0.35          # 碎片：最短边上限
FRAG_MAX_SIDE = 3.2           # 碎片：最长边上限
FRAG_MAX_AREA = 1.2           # 碎片：面积上限
SHAFT_MAX_GROW = 4.0          # 井道四向最多扩多少米
SHAFT_COVER = 0.55            # 边被墙盖住多少算「这条边有墙」
SHAFT_TOL = 0.06              # 采样点到墙的距离容差（m）
SHAFT_STEP = 0.05             # 四向搜索步长（m）


TREAD_PITCH_MIN = 0.22         # 踏步级距下限（m）：GB/T 50104 踏步宽 220~300
TREAD_PITCH_MAX = 0.35         # 上限（含休息平台前的最后一级）
PITCH_TOL = 0.06               # 级距均匀性容差（±）
MIN_FLIGHT_STEPS = 4           # 少于 4 级不成跑
MIN_FLIGHT_RUN = 1.5           # 跑长（y 跨度）下限
# 踏步线自身的长度区间（= 梯段净宽）。上限 2026-09-16 由 3.0 提到 4.2：
# c114 的**出屋面梯间**图上就是一跑到底（踏步线长 3.62m），卡在 3.0 会让整条梯段被弃，
# 顶层那口井消失（体检报「F5 楼梯井消失」）。下限 0.8 不动（＜0.8 是门垛/窗台）。
TREAD_LEN_MIN = 0.8
TREAD_LEN_MAX = 4.2
WELL_JOIN_GAP = 0.80           # 两列梯段相距多近算同一口井（含 60mm 中缝）
# 同一「跑带」里，踏步线跨度与**跑带代表跨度**的两端差上限（m）。
# （原 `COL_TOL = 0.25` 于 2026-09-14 废弃：它对被**剖断符号截短**的踏步线不免疫，
#   见 `_columns` 的 docstring。放宽到 0.80 的边界依据也在那里。）
BAND_TOL = 0.80


def _segs_from(walls, axis="x", with_idx=False):
    """原始折线 → 踏步候选段 `(a0, a1, b[, idx])`。

    `axis` 是**踏步线自身的走向**，也就是「跑」的垂直方向：
      · `axis="x"` 踏步是水平线 → 跑沿 y 走（ny27/c027/c103 都是这种）
      · `axis="y"` 踏步是竖直线 → 跑沿 x 走（东⻄向梯段，旧实现完全看不见）

    ⚠️ 旧实现只收水平段（`abs(dx) >= abs(dy)`），**东西向的梯段一律漏检**。
    这里两种都收，返回统一成 `(a0, a1, b)`：a = 踏步线自己的跨度，b = 跑向坐标。
    `with_idx=True` 时多带一个原始下标，供 `tread_indices` 回指折线。
    """
    out = []
    for i, pts in enumerate(walls or []):
        if len(pts) != 2:
            continue
        (x0, y0), (x1, y1) = pts[0], pts[1]
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        if axis == "x":
            if dy > 0.02 or not (TREAD_LEN_MIN <= dx <= TREAD_LEN_MAX):
                continue
            out.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2, i) if with_idx
                       else (min(x0, x1), max(x0, x1), (y0 + y1) / 2))
        else:
            if dx > 0.02 or not (TREAD_LEN_MIN <= dy <= TREAD_LEN_MAX):
                continue
            out.append((min(y0, y1), max(y0, y1), (x0 + x1) / 2, i) if with_idx
                       else (min(y0, y1), max(y0, y1), (x0 + x1) / 2))
    return out


def _columns(segs):
    """把短段聚成**跑带**（一条梯段上的全部踏步线）。`x0/x1` 是跑带的外包围。

    这是本模块最要紧的一处判据，三个坑都踩过：

    1. 旧实现（`detect_stairwells`）按「中心距 ≤3.0m」并段，于是**楼梯两侧 240mm 的
       墙双线**（本身也是 0.8~3.0m 的水平 2 点段，中心离梯段 1.6m）被吃成踏步 ——
       ny27 F0 井宽被撑成 6.54m，真实梯段只有 2.46m。
    2. 改成「重叠 ≥50% 短者」也不行：列一旦长宽，后面任何段都能凑够「自身一半」
       而被吞进来（传递性膨胀）。实测把 x[-18.9,-16.5] 与 x[-14.7,-12.3] 之间
       的 27 条全并成一列。
    3. **两端各自相差 ≤`COL_TOL`**（2026-09-14 废弃）：它假设「同一跑的踏步线等长」，
       而这条假设**被剖断符号打破** —— 详见下。

    ## 为什么要改（2026-09-14 实测，用户报「楼梯样式不对，缺中间休息层」）

    楼梯平面图上，跑得太长的梯段会用**剖断符号**（Z 字形折断线）横穿，被穿过的几条
    踏步线就**变短**。实测 c006 F1 左翼那部双跑楼梯的下半跑，13 条线里 4 条被截：

        完整   [-36.78,-35.31]  1.47m   （9 条）
        截短   [-36.78,-35.41]  1.37m
        截短   [-36.78,-35.88]  0.90m
        截短   [-36.15,-35.31]  0.84m
        截短   [-36.62,-35.31]  1.31m

    两端差达 0.63m ≫ `COL_TOL`(0.25) ⇒ 被判成**三个不同的列**，每列只有 1~4 条，
    全都不足 `MIN_FLIGHT_STEPS`(4) ⇒ **整条下半跑被丢弃**。结果那部双跑楼梯只剩
    上半跑 ⇒ `type="straight"`、井宽 1.47m（真实 3.06m）⇒ 渲染时既没有第二跑、
    也没有休息平台（用户看到的就是这个）。

    4. **区间交叠 + 中心距**（2026-09-14 当日先采用、当日废弃）：交叠 ≥0.20 挡不住
       **休息平台边线** —— 平台上那条线横跨两跑（ny27 F0 实测 `x[-16.83,-14.37]`，
       长 2.46m = 两跑之和），它与两跑各自交叠满额、中心距只差 0.63m ⇒ 把两跑并成
       一列；两跑的跑向坐标又逐一相同，`_all_runs` 的 `set()` 去重后只剩一套 ⇒
       **井退化成 `straight`，每井少一跑**（ny27 36→18 梯段、c027 31→23）。

    ## 现判据

    与列的**代表跨度**两端各自相差 ≤ `BAND_TOL`。代表 = 列内**出现次数最多**的那条
    跨度（众数）：踏步线是同一跑里重复最多的图元，众数**天然就是完整踏步线**的跨度，
    被剖断截短的少数线、横跨双跑的平台线都动不了它。

    为什么非「众数 + 两端差」不可（两个反例都是实测）：
      · 只比**中心**（或只比交叠）：平台线中心距跑带 0.63m，照样并进来 ⇒ 过度合并。
        两端差对它是 1.26m，一眼挡掉。
      · 只跟**首条**线比（旧 `COL_TOL` 的写法）：c006 首条若正好是被截断的那条，
        整跑就散了。众数不看谁先来。
    阈值 `BAND_TOL = 0.80` 的边界：需 ≥ c006 实测最大截短差 0.63m；须 < 两跑中心距
    下限「梯段净宽 1.05 + 中缝 0.06」≈1.11m（两端差是它的两倍，更宽裕）。
    0.63 < 0.80 < 1.11 ⇒ 两种形态分得开。

    ⚠️ 本判据的**副作用**（不是 bug）：两处**跑带宽相同**的楼梯（典型就是左右对称
    的两部）会被并进同一列。一列本来就可以含多处梯段，由 `_all_runs` 各自成链即可。
    **不要**为了"分开它们"去动这里的键。

    ⚠️ `x0/x1` 随合并**取并集**（不是首条线的原值）：`flights_of` 拿它当梯段足迹，
    取并集才等于跑带真实外包围。判据**只**看 `rep`，并集撑大不会反过来放宽判据
    （坑 2/4 都是"拿并集/累积量当钥匙"造成的传递膨胀）。
    """
    cols = []
    for s in sorted(segs, key=lambda s: (round(s[0], 3), round(s[1], 3), s[2])):
        x0, x1, y = s[0], s[1], s[2]
        key = (round(x0, 3), round(x1, 3))
        for c in cols:
            r0, r1 = c["rep"]
            if abs(x0 - r0) > BAND_TOL or abs(x1 - r1) > BAND_TOL:
                continue
            c["cnt"][key] = c["cnt"].get(key, 0) + 1
            if c["cnt"][key] > c["cnt"][c["rep"]]:
                c["rep"] = key                      # 更常见的跨度升为代表
            c["x0"], c["x1"] = min(c["x0"], x0), max(c["x1"], x1)
            c["ys"].append(y)
            c["items"].append((y, s[3] if len(s) > 3 else None))
            break
        else:
            cols.append({"rep": key, "cnt": {key: 1}, "x0": x0, "x1": x1, "ys": [y],
                         "items": [(y, s[3] if len(s) > 3 else None)]})
    for c in cols:                                      # `rep` 是内部钥匙，不外露
        del c["rep"], c["cnt"]
    return cols


def _all_runs(ys):
    """一列里的**所有**均匀踏步链（原 `_longest_run` 只返回最长的那一条）。

    ★ 为什么要「所有」（2026-09-14 实测根因，c006）：
    `_columns` 的列键是**踏步线自身的坐标跨度**。对竖踏步线（`axis="y"`）那就是
    **梯段宽度** —— 而左右对称的两部楼梯，梯段宽度完全相同 ⇒ **被并进同一列**。
    旧写法一列只取一条最长链，于是列里混着两处梯段时**只留一处，另一处整部丢掉**。
    实测 c006 F1：左 x 跑向 [-52.85,-49.61] 成跑，右 [+49.61,+52.85] 的候选线与左
    **逐位对称**（各 62 条、同样两列各 13 级），却在 `_runs_of` 输出里**一条都没有**；
    改成取所有链后 F1 的井 5 → 8 部且左右对称（F1–F6 每层都补回 3 部）。
    ⚠️ `_columns` 的键**不改**：同一跑内所有踏步线跨度确实相同，那正是它要的。
    错的只是「一列至多一条链」这个隐含假设 —— 一列里可以有多处梯段。

    判据与旧 `_longest_run` 逐条相同（级距 0.22~0.35 ± `PITCH_TOL`、≥`MIN_FLIGHT_STEPS`
    级；`MIN_FLIGHT_RUN` 由 `_runs_of` 判），只是**重复取到取不出为止**；
    各链互不共用元素，避免同一条链被反复产出。取「最长」而非「第一个可行」是为了
    让同一处梯段的抓取不受列内杂线顺序影响（图纸里一跑踏步上下常挂栏杆/扶手/平台边，
    要求整列均匀会让整跑被否掉 —— 实测 ny27 F0 井全灭；这也是旧实现只取最长链的原因）。
    """
    ys = sorted(set(round(float(y), 3) for y in ys))
    taken = [False] * len(ys)
    out = []
    while True:
        best, best_used = [], []
        for i in range(len(ys)):
            if taken[i]:
                continue
            run, used = [ys[i]], [i]
            for j in range(i + 1, len(ys)):
                if taken[j]:
                    continue
                gap = ys[j] - run[-1]
                if gap < TREAD_PITCH_MIN - PITCH_TOL:
                    continue                      # 贴太近（双线/重复），跳过不并入
                if gap > TREAD_PITCH_MAX + PITCH_TOL:
                    break                         # 断带
                if len(run) == 1 or abs(gap - (run[-1] - run[0]) / (len(run) - 1)) <= PITCH_TOL:
                    run.append(ys[j])
                    used.append(j)
            if len(run) > len(best):
                best, best_used = run, used
        if len(best) < MIN_FLIGHT_STEPS:
            break                                 # 剩下的都凑不成跑
        out.append(best)
        for k in best_used:
            taken[k] = True
    return out


def _runs_of(walls):
    """(axis, 列, 均匀链) 三元组 —— **一列可产出多条**（见 `_all_runs` 的根因）。
    识别与剔除共用同一遍扫描。

    「成跑」三条缺一不可：≥`MIN_FLIGHT_STEPS` 级、跑长 ≥`MIN_FLIGHT_RUN`、
    级距落在 0.22~0.35m（级距与级数由 `_all_runs` 保证，跑长在此判）。墙双线只有
    2 级（被第一条挡掉），退一万步就算凑够 4 条，级距（0.24m 的倍数、不匀）也过不了第三条。
    """
    out = []
    for axis in ("x", "y"):
        for c in _columns(_segs_from(walls, axis, with_idx=True)):
            for run in _all_runs(c["ys"]):
                if run[-1] - run[0] >= MIN_FLIGHT_RUN:
                    out.append((axis, c, run))
    return out


def tread_indices(walls):
    """哪些折线是**踏步线** —— 配对成墙之前必须先剔掉。

    踏步线本身是 2 点短线、间距 0.3m 落在墙厚窗口内，`pair_wall_faces` 会把相邻两条
    贪心配成 0.3m 厚的「墙」把楼梯井塞满（`stair-tread-fake-walls`）。

    这是「哪条线是踏步」的**唯一实现**：识别（`wells_of`）与剔除
    （`geometry._stair_tread_indices`）共用一份判据，避免两处漂移。
    ⚠️ 旧实现只收水平段，**东西向梯段的踏步线一直漏剔**，被配成假墙。
    """
    idx = set()
    for _axis, c, run in _runs_of(walls):
        keep = {round(float(v), 3) for v in run}
        idx |= {i for b, i in c["items"] if i is not None and round(float(b), 3) in keep}
    return frozenset(idx)


def flights_of(walls):
    """原始墙线 → 梯段列表（两个走向都收）。普查、识别、踏步剔除三处共用这一份判据。

    每项 `{axis, x0, x1, y0, y1, steps, pitch}`：`axis` 是**踏步线走向**
    （`"x"` = 水平踏步/跑沿 y；`"y"` = 竖直踏步/跑沿 x），方框是梯段的**脚步足迹**。
    """
    out = []
    for axis, c, run in _runs_of(walls):
        n = len(run)
        a0, a1, b0, b1 = c["x0"], c["x1"], run[0], run[-1]
        box = ({"x0": a0, "x1": a1, "y0": b0, "y1": b1} if axis == "x"
               else {"x0": b0, "x1": b1, "y0": a0, "y1": a1})
        out.append(dict(box, axis=axis, steps=n,
                        pitch=round((b1 - b0) / (n - 1), 3)))
    return sorted(out, key=lambda f: (f["x0"], f["y0"], f["axis"]))


def wells_of(walls, outline=None):
    """原始墙线 → 楼梯井列表（与旧 `detect_stairwells` 同构的 dict，另加 `axis`）。

    一口井 = **跑长区间重叠、且垂直于跑向只隔 ≤0.8m** 的一组梯段（双跑的两列中间
    只隔一道 60mm 中缝）。井的包围盒取**梯段自身**的并集 —— 不含休息平台，也不含
    两侧的墙；平台与井壁由 `shaft_of` 沿四向扩到实体墙时一并还原（那是「还原」不是
    臆造）。「跑长」与「垂直」随 `axis` 互换：`axis="x"`（水平踏步）跑沿 y，
    `axis="y"`（竖直踏步/东西向梯段）跑沿 x。
    """
    out = []
    all_fs = flights_of(walls)
    for axis in ("x", "y"):
        fs = [f for f in all_fs if f["axis"] == axis]
        run = (lambda f: (f["y0"], f["y1"])) if axis == "x" else (lambda f: (f["x0"], f["x1"]))
        perp = (lambda f: (f["x0"], f["x1"])) if axis == "x" else (lambda f: (f["y0"], f["y1"]))
        groups = []
        for f in fs:
            fr0, fr1 = run(f)
            fp0, fp1 = perp(f)
            for g in groups:
                # ⚠️ 逐条比，**不比合并后的包围盒**：拿累加区间比会让边距越并越松，
                # 一串本来互不相干的梯段被链式吞成一口巨井（同 `_columns` 踩过的坑）。
                if not all(min(gr1, fr1) - max(gr0, fr0) >= 0.5 * min(gr1 - gr0, fr1 - fr0)
                           and max(gp0, fp0) - min(gp1, fp1) <= WELL_JOIN_GAP
                           for gr0, gr1, gp0, gp1 in g["ms"]):
                    continue                               # 跑长不重叠 / 垂直离太远 → 不是同一口井
                g["ms"].append((fr0, fr1, fp0, fp1))
                g["fs"].append(f)
                g["r0"], g["r1"] = min(g["r0"], fr0), max(g["r1"], fr1)
                g["p0"], g["p1"] = min(g["p0"], fp0), max(g["p1"], fp1)
                break
            else:
                groups.append({"r0": fr0, "r1": fr1, "p0": fp0, "p1": fp1,
                               "ms": [(fr0, fr1, fp0, fp1)], "fs": [f]})

        for g in groups:
            # 列序：踏步线沿垂直方向排列，按垂直向中点排序（straight/double 的判定无关方向）
            cols = sorted(g["fs"], key=lambda f: (perp(f)[0] + perp(f)[1]) / 2)
            nf = len(cols)
            stype = "straight" if nf == 1 else ("double" if nf == 2 else "bifurcated")
            if axis == "x":
                bx0, bx1 = g["p0"], g["p1"]
                by0, by1 = g["r0"], g["r1"]
            else:
                bx0, bx1 = g["r0"], g["r1"]
                by0, by1 = g["p0"], g["p1"]
            # 每跑给**完整方框**：消费方按 axis 取「垂直向范围」（x 向跑取 y、y 向跑取 x）。
            fl = [{"x0": f["x0"], "x1": f["x1"], "y0": f["y0"], "y1": f["y1"]}
                  for f in cols]
            out.append({
                "x0": round(bx0, 3), "x1": round(bx1, 3),
                "yBot": round(by0, 3), "yTop": round(by1, 3),
                "steps": max(f["steps"] for f in cols),
                "pitch": round(sum(f["pitch"] for f in cols) / nf, 3),
                "type": stype,
                "axis": axis,
                "flights": fl,
            })
    # 两个走向各跑一遍：同一口井理论上只会在一个走向里成链；万一两边都命中（斜向
    # 梯段的两种分解），按脚印 IoU>0.7 去重，保留级数多的那个。
    keep = []
    for w in sorted(out, key=lambda s: -s["steps"]):
        if any(_iou(w, k) > 0.7 for k in keep):
            continue
        keep.append(w)
    return sorted(keep, key=lambda s: (s["x0"], s["yBot"]))


def _iou(a, b):
    ix = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    iy = min(a["yTop"], b["yTop"]) - max(a["yBot"], b["yBot"])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    ua = (a["x1"] - a["x0"]) * (a["yTop"] - a["yBot"])
    ub = (b["x1"] - b["x0"]) * (b["yTop"] - b["yBot"])
    return inter / max(ua + ub - inter, 1e-9)


def is_fragment(g):
    """碎片（踏步线/窗台线/门符号被配出来的细长小片），不是承重墙。"""
    if g is None or g.is_empty:
        return False
    bx0, by0, bx1, by1 = g.bounds
    a, b = bx1 - bx0, by1 - by0
    return g.area < FRAG_MAX_AREA and min(a, b) <= FRAG_MIN_SIDE and max(a, b) <= FRAG_MAX_SIDE


def solid_union(walls):
    """实体墙（排除碎片）的并集。井道围合只能用这个量。

    **女儿墙不算**：`type=="parapet"` 是退台屋面上沿外缘的一圈矮墙（recognize 的
    `add_terrace_parapets` 出的），离楼梯间常有十几米。它若进了并集，`measure` 的
    外扩取墙会把井道框一路撑到屋面边、围合率虚高（假绿）。屋面矮墙不是井道围合墙。
    """
    ps = []
    for w in walls or []:
        if w.get("type") == "parapet":
            continue
        g = openings.wall_poly(w)
        if g is None or is_fragment(g):
            continue
        ps.append(g)
    if not ps:
        return None
    u = unary_union(ps)
    return u if u.is_valid else u.buffer(0)


def _cover(seg_pts, u, tol=SHAFT_TOL):
    if not seg_pts:
        return 0.0
    hit = sum(1 for p in seg_pts if u.distance(Point(p)) <= tol)
    return hit / len(seg_pts)


def _seg(x0, y0, x1, y1, n):
    return [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]


def _grow(rect, u, axis, sign, max_grow=SHAFT_MAX_GROW,
          cover=SHAFT_COVER, step=SHAFT_STEP):
    """把 rect 沿 axis('x'|'y') 的 sign(+1/-1) 一侧往外扩到最近的实体墙。

    返回扩出的距离（0 表示这条边本来就有墙）；扩不到返回 None。

    `max_grow` 是**不含**的上界：`d == max_grow` 不算探到（`shaft_of` 沿跑向拿「跑长」
    当上界，而平台与梯段等深显然是走到了下一个空间而不是平台外沿）。
    """
    bx0, by0, bx1, by1 = rect.bounds
    if axis == "y":
        edge = by1 if sign > 0 else by0
        n = max(2, int((bx1 - bx0) / 0.25))
        probe = lambda d: _seg(bx0, edge + sign * d, bx1, edge + sign * d, n)
    else:
        edge = bx1 if sign > 0 else bx0
        n = max(2, int((by1 - by0) / 0.25))
        probe = lambda d: _seg(edge + sign * d, by0, edge + sign * d, by1, n)

    if _cover(probe(0.0), u) >= cover:
        return 0.0
    d = step
    while d < max_grow - 1e-9:
        if _cover(probe(d), u) >= cover:
            return d
        d += step
    return None


def _run_axis(well):
    """井的**跑向轴**（梯段往哪边爬）。`axis` 是踏步线走向 = 跑向的垂直方向：
    `axis="x"`（水平踏步）跑沿 y；`axis="y"`（竖直踏步）跑沿 x。
    缺 `axis` 的旧数据按 `"x"`（跑沿 y）—— 与 `build_standard_glb._frame` 同一约定。
    """
    return "y" if (well.get("axis") or "x") == "x" else "x"


def _run_span(well, run_axis):
    """跑长（沿跑向的净长，米）。"""
    return (well["yTop"] - well["yBot"]) if run_axis == "y" else (well["x1"] - well["x0"])


def shaft_of(well, solid, max_grow=SHAFT_MAX_GROW, cover=SHAFT_COVER):
    """踏步包围盒 → 井道矩形。

    返回 `(shaft, sides)`：`shaft` 是扩后的矩形（扩不到的方向保持原边），
    `sides` 是四向的扩出距离（None = 这个方向没墙）。`solid` 为 None 时返回 (None, {})。

    **跑向的扩距另有一个上限 = 本井跑长**（`_run_span`）。沿跑向扩是去找休息平台，
    平台深度不可能超过梯段本身的长度；超过就说明探到的不是平台边而是**走廊对面的墙**。
    实测 c027 F3：井 +x 侧（走廊开口侧、本就没有井壁）一路探到 3.6m 外走廊对面的墙上，
    井被撑成 9.35m 宽、围合率反而升到 0.94 —— 楼板洞挖进走廊，比不挖更糟。
    垂直跑向的扩是找井道两侧的墙（井可以很宽），不设这个上限。
    """
    if solid is None:
        return None, {}
    r = _box(well["x0"], well["yBot"], well["x1"], well["yTop"])
    if r.area <= 0:
        return None, {}
    run_axis = _run_axis(well)
    lim = {"x": max_grow, "y": max_grow}
    lim[run_axis] = min(max_grow, _run_span(well, run_axis))
    sides = {}
    # 先纵后横：纵边用原始 x 跨度找墙，横边再用扩后的 y 跨度找墙（顺序影响结果，
    # 这里是唯一的一处顺序约定，改要一起改）。
    for axis, sign in (("y", 1), ("y", -1), ("x", 1), ("x", -1)):
        d = _grow(r, solid, axis, sign, lim[axis], cover)
        sides["%s%s" % ("+" if sign > 0 else "-", axis)] = d
        if d:
            bx0, by0, bx1, by1 = r.bounds
            if axis == "y":
                by1, by0 = (by1 + d, by0) if sign > 0 else (by1, by0 - d)
            else:
                bx1, bx0 = (bx1 + d, bx0) if sign > 0 else (bx1, bx0 - d)
            r = _box(bx0, by0, bx1, by1)
    return r, sides


def enclosure_rate(shaft, solid, step=0.10):
    """井道周长被**实体墙**盖住的比例。必须在扩后的井上量（见模块头「自证陷阱」）。"""
    if solid is None or shaft is None or shaft.area <= 0:
        return 0.0
    bx0, by0, bx1, by1 = shaft.bounds
    pts = []
    n = max(2, int((bx1 - bx0) / step))
    for i in range(n + 1):
        x = bx0 + (bx1 - bx0) * i / n
        pts += [(x, by0), (x, by1)]
    n = max(2, int((by1 - by0) / step))
    for i in range(n + 1):
        y = by0 + (by1 - by0) * i / n
        pts += [(bx0, y), (bx1, y)]
    return _cover(pts, solid)


def measure(wells, walls, step=0.10):
    """一口井一次算清：井道 / 四向 / 围合率 / 假墙数。返回与 wells 同序的 list。

    每项 `{shaft, sides, enc, enc_raw, frag, frag_shaft, area_before, area_after}`：
      · `enc` 扩后井道的围合率（判据）；`enc_raw` 原始包围盒的围合率（仅作对照，
        低是常态，因为包围盒是踏步盒子不是井道盒子）
      · `frag` **踏步盒内**的碎片墙数（判据）。这是唯一能干净分开好坏的量：踏步线被配成
        的假墙按构造落在踏步盒里；而扩后的井道会合法地吞进楼梯口两侧的门垛
        （0.95×0.10）、平台墙 —— 拿井道量会把它们一起冤枉成假墙（c027 F3 实测：
        踏步盒 0 / 井道 2~3，后者全是真墙）。
      · `frag_shaft` 井道内的碎片墙数（仅作对照，不作判据）
    """
    solid = solid_union(walls)
    ps = [g for g in (openings.wall_poly(w) for w in walls or []) if g is not None]
    allu = unary_union(ps) if ps else None
    frags = [g for g in ps if is_fragment(g)]
    out = []
    for w in wells or []:
        r0 = _box(w["x0"], w["yBot"], w["x1"], w["yTop"])
        shaft, sides = shaft_of(w, solid)
        out.append({
            "shaft": shaft,
            "sides": sides,
            "enc": round(enclosure_rate(shaft, solid, step), 3),
            "enc_raw": round(enclosure_rate(r0, solid, step), 3),
            "enc_any": round(enclosure_rate(r0, allu, step), 3),
            "frag": sum(1 for g in frags if g.intersects(r0)),
            "frag_shaft": sum(1 for g in frags
                              if shaft is not None and g.intersects(shaft)),
            "area_before": round(r0.area, 3),
            "area_after": round(shaft.area, 3) if shaft is not None else 0.0,
        })
    return out


def attach_shafts(wells, walls):
    """给每口井挂上**井道矩形** `shaft`（就地不改，返回新列表）。

    为什么非要挂进交付数据：`x0/x1/yBot/yTop` 是**踏步包围盒** —— 不含休息平台，也不含
    「这一层没画出来」的那一半。楼板洞直接按它挖就会盖住井口。实测 c027 顶层：该层只识别到
    到达的那一跑（3.6×2.5），洞跟着只有一半，从上往下看西侧半口井是实心板。
    井道是**还原**（四向扩到图上真实存在的墙），不是臆造；与 `measure` 共用同一个
    `shaft_of`，不存在第二份判据。

    扩不到墙的方向保留原边 —— 那正是走廊进楼梯间的开口侧，**本就该保留楼板**（往外扩
    会在走廊上开洞）。`shaft_of` 返回 None（一口墙都没找到）时不挂键，消费方回退到包围盒。
    """
    solid = solid_union(walls)
    out = []
    for w in wells or []:
        nw = dict(w)
        shaft, _sides = shaft_of(w, solid)
        if shaft is not None and not shaft.is_empty and shaft.area > 0:
            bx0, by0, bx1, by1 = shaft.bounds
            nw["shaft"] = {"x0": round(bx0, 3), "x1": round(bx1, 3),
                           "yBot": round(by0, 3), "yTop": round(by1, 3)}
        out.append(nw)
    return out


VERT_CONTAIN = 0.5            # 跨层配井：交集占**较小**盒的比例
VERT_OUTLIER = 0.60           # 组内某层盒与「多数盒」某条边差超过此值 → 判离群层，不参与并集
VERT_FRAME_TOL = 0.30         # **同平面**各层的轮廓原点须一致到此值以内，否则拒绝跨层并集
VERT_PLAN_TOL = 0.30          # 「同平面」判据：两层轮廓 bbox 宽/高之差上限（m）
VERT_PLAN_AREA = 0.10         # 「同平面」判据：两层轮廓 bbox 面积相对差上限
VERT_FILL_CONTAIN = 0.60      # 竖向补井：本层轮廓 ∩ 井盒 ≥ 该比例 ⇒ 本层这个位置就是同一口竖井


def _outline_poly(fl):
    """该层轮廓多边形（判「井位是否落在本层轮廓内」用）；拿不到返回 None。"""
    o = fl.get("outline") or []
    if len(o) < 3:
        return None
    try:
        from shapely.geometry import Polygon
        p = Polygon(o)
        return p if p.is_valid else p.buffer(0)
    except Exception:                                              # noqa: BLE001
        return None


def _contain_ratio(a, b):
    """交集 / min(面积)。跨层配井要的是「小的那个基本落在大的里面」。

    不能用 IoU：顶层只认出半个井时 IoU = 9.0/29.9 = 0.30 会被漏掉，而「半个井完全落在
    整口井里」恰恰是该配的信号。`a` / `b` 是 `(x0, y0, x1, y1)`。
    """
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    m = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return (ix * iy) / m if m > 0 else 0.0


def _outline_anchor(fl):
    """该层的**轮廓外形** `(minx, miny, w, h)` —— 判「是不是同平面」用的量。

    ⚠️ **不要拿它当「坐标原点」使**（2026-09-12 c009 修正）。各层轮廓**本就该不同**：退台楼、
    多翼楼、连体楼每层脚印都不一样，左下角当然不一样。之前就是拿左下角当原点去判「坐标系
    漂移」，于是把「轮廓差异」误当「offset 标错」—— c009 的 offset 实测正确，5 组竖井却被
    整组拒掉，还刷了一句方向错误的诊断（判据本身用错了量，见《算法与流程》§5.4 与风险 8）。

    正确的用法：先用它把跨层配对按**同平面**切成子组（`_same_plan`），再在子组内部比锚点 ——
    同平面的各层轮廓必须逐点重合，此时原点才真的**应该**一致，差> `VERT_FRAME_TOL` 才是漂移。
    """
    o = fl.get("outline") or []
    if not o:
        return None
    xs = [q[0] for q in o]
    ys = [q[1] for q in o]
    x0, y0 = min(xs), min(ys)
    return (x0, y0, max(xs) - x0, max(ys) - y0)


def _same_plan(a, b):
    """两个轮廓外形是不是**同一个平面**（同一张标准层的图）。

    判据：宽、高各差 ≤ `VERT_PLAN_TOL`，且外接矩形面积相对差 ≤ `VERT_PLAN_AREA`。

    只看**外接矩形包络**，不比顶点集合 —— 同构平面在识别里常常差一个顶点就不"同构"了，
    可那不妨碍「这一层的井该和那一层一样大」；反过来退台楼逐层面积差动辄几成，宽高差必然
    超过 0.30m，会被正确判成不同平面。c009 实测各层外接矩形面积
    8079 / 4932 / 5185 / 5186 / 3797 ㎡ —— F3 与 F4 判同平面（差 0.02%），其余各自成组。
    """
    if a is None or b is None:
        return False
    if max(abs(a[2] - b[2]), abs(a[3] - b[3])) > VERT_PLAN_TOL:
        return False
    aa, ab = a[2] * a[3], b[2] * b[3]
    m = max(aa, ab)
    return bool(m > 0) and abs(aa - ab) / m <= VERT_PLAN_AREA


def _split_same_plan(mem, anchors):
    """把一组跨层配对的井按「同平面」切成若干子组（并查集取传递闭包）。

    取闭包而不是逐个找第一个同平面的：三种平面混在一组时（裙楼 + 塔楼 + 过渡层），
    逐个找会让结果依赖遍历顺序，「谁和谁算一层」变得不可预测。闭包是唯一确定的划分。
    """
    n = len(mem)
    par = list(range(n))

    def _find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if _same_plan(anchors[mem[i][0]], anchors[mem[j][0]]):
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    par[ri] = rj
    subs = {}
    for i in range(n):
        subs.setdefault(_find(i), []).append(mem[i])
    return list(subs.values())


def _union_into(mem, anchors, per):
    """对**同平面**的一组成员取井道并集并就地写回；返回 False 表示坐标系漂移，整组拒绝。

    护栏③ 的正确形态：只在同平面组内比轮廓原点。同平面各层的轮廓必须逐点重合，所以原点差
    > `VERT_FRAME_TOL` 就是真的漂移（`profile.offset` 标错）。此时**宁可退回逐层井道**——
    绝不「补偿」：补偿只会把藏在 profile 里的错盖住（c057 各层漂 0.446m，并集 8.33m 对上每层
    真实的 6.10m 井，六层全挖错，就是这么被漏掉的）。
    """
    an = [anchors[fi] for fi, _wi, _b in mem if anchors[fi] is not None]
    if len(an) >= 2:
        mx = sorted(a[0] for a in an)[len(an) // 2]
        my = sorted(a[1] for a in an)[len(an) // 2]
        if max(max(abs(a[0] - mx), abs(a[1] - my)) for a in an) > VERT_FRAME_TOL:
            return False

    # 护栏②：剔除离群层（多数派才参与取并集；全是离群就退回全员并集）
    med = [sorted(b[k] for _f, _w, b in mem)[len(mem) // 2] for k in range(4)]
    keep = [m for m in mem
            if max(abs(m[2][k] - med[k]) for k in range(4)) <= VERT_OUTLIER] or mem
    u = {"x0": round(min(b[0] for _f, _w, b in keep), 3),
         "x1": round(max(b[2] for _f, _w, b in keep), 3),
         "yBot": round(min(b[1] for _f, _w, b in keep), 3),
         "yTop": round(max(b[3] for _f, _w, b in keep), 3)}
    for fi, wi, _b in mem:                            # 离群层**也**发给它：同一口井
        per[fi][wi][0]["shaft"] = dict(u)
    return True


def attach_shafts_to_floors(floors):
    """**一栋楼**的井道：逐层扩到墙（`attach_shafts`），再跨层取并集统一 `shaft`。

    井道是**竖向棱柱** —— 同一口井在每层的位置与大小必须一样。可踏步线只画在画了梯段的
    楼层：顶层常常只画到「到达」的那一跑（c027 顶层只有 3.6×2.5 的一半），`wells_of` 于是
    只认出半个井，`attach_shafts` 扩到的那圈墙也只是半个，楼板洞跟着只挖一半，从上往下看
    西侧半口井被实心板盖住。这是**识别的锅，不是图的锅** —— 图上那半口井和下面几层完全一样。
    所以口径取跨层并集：配对上的各层 `shaft` 都换成组内并集。并集只由各层**自己探到的墙**
    围出来，仍属还原，没有新几何。

    **三条护栏**（都对实测故障，见《算法与流程》§5.4）：
      ① 一口井每层最多进一个组 —— 贪心按重叠率降序配，合并前查重。并查集只挡「直接比对
         的那一对」同层，仍会 A–B–C 传递链把**同层两口井**并进一组（c026 F4/F5 的井1井2
         被链成一个 8.88m 的盒，切穿楼梯 −x 侧的墙）。
      ② 离群层不参与并集 —— 某条边偏离多数值 > `VERT_OUTLIER` 的层多半探错了（c062 F0 探出
         −y 4.0、其余五层一致 5.8），并集会把这一层的错摊给全楼。但**仍发给它**并集盒：
         它是同一口井，只是自己那一层没量准。
      ③ 坐标系漂移就整组拒绝并集 —— **同平面**的各层轮廓必须逐点重合，原点差 >
         `VERT_FRAME_TOL` 说明 offset 标错，并集必然错。**宁可退回逐层井道并报警，也不去
         「补偿」**：补偿只会把藏在 profile 里的错盖住（c057 就是这么被漏掉的）。
         2026-09-12 修正：判「漂移」前**先按同平面切子组**（`_split_same_plan`）—— 原先直接
         拿轮廓左下角当原点比，而各层轮廓本就该不同（退台/多翼），于是把「轮廓差异」误当
         「offset 标错」：c009 的 offset 实测正确，5 组竖井却被整组拒掉并刷出错误诊断。

    就地改 `floors[i]["stairwells"]`；返回合并出的井道组数。**必须在墙定稿之后、写盘之前
    调一次**（逐层算完就写会把并集切碎），调用口见 `_wall_thin_batch.refresh_shafts`。
    """
    per, anchors = [], []
    for fl in floors or []:
        solid = solid_union(fl.get("walls") or [])
        items = []
        for w in fl.get("stairwells") or []:
            shaft, _sides = shaft_of(w, solid)
            box_ = None
            if shaft is not None and not shaft.is_empty and shaft.area > 0:
                box_ = shaft.bounds                      # (x0, y0, x1, y1)
            elif w.get("x1", 0) > w.get("x0", 0):
                box_ = (w["x0"], w["yBot"], w["x1"], w["yTop"])   # 扩不到墙：退回踏步盒
            items.append((w, box_))
        per.append(items)
        anchors.append(_outline_anchor(fl))

    cells = []                                            # (floor_i, well_j, box)
    for fi, items in enumerate(per):
        for wi, (_w, b) in enumerate(items):
            if b is not None:
                cells.append((fi, wi, b))

    # 配对：先算出所有跨层候选对，再**按重叠率降序贪心**（一口井只认最像的那口）
    pairs = []
    for i in range(len(cells)):
        for j in range(i + 1, len(cells)):
            if cells[i][0] == cells[j][0]:
                continue                                  # 同层两口井是两口井，永不配
            r = _contain_ratio(cells[i][2], cells[j][2])
            if r >= VERT_CONTAIN:
                pairs.append((r, i, j))
    pairs.sort(key=lambda t: -t[0])

    owner = [None] * len(cells)
    groups = []                                           # {"floors": set, "cells": [idx]}
    for _r, i, j in pairs:
        gi, gj = owner[i], owner[j]
        if gi is None and gj is None:
            groups.append({"floors": {cells[i][0], cells[j][0]}, "cells": [i, j]})
            owner[i] = owner[j] = len(groups) - 1
        elif gi is not None and gj is not None:
            if gi == gj:
                continue
            a, b = groups[gi], groups[gj]
            if a["floors"] & b["floors"]:                 # 合并会把同层两口井塞进一组 → 不合并
                continue
            a["floors"] |= b["floors"]
            a["cells"] += b["cells"]
            for c in b["cells"]:
                owner[c] = gi
            b["cells"] = []                               # 已并走，标识为空组
        else:
            k, g = (i, gj) if gi is None else (j, gi)
            if cells[k][0] in groups[g]["floors"]:
                continue                                  # 该组已有这一层的井 → 这口井另立门户
            groups[g]["floors"].add(cells[k][0])
            groups[g]["cells"].append(k)
            owner[k] = g
    for c, g in enumerate(owner):
        if g is None:                                     # 没配上任何跨层对应：自成一户
            groups.append({"floors": {cells[c][0]}, "cells": [c]})
            owner[c] = len(groups) - 1

    n_skip = 0
    n_used = 0
    n_split = 0
    n_fill = 0
    for g in groups:
        mem = [cells[c] for c in g["cells"]]
        if not mem:
            continue
        # 护栏③（2026-09-12 改）：先按「同平面」把本组切成子组 —— 只有同平面的层才共享一个
        # 坐标系，也才谈得上「井该一样大」。不同平面（退台 / 多翼 / 连体）各算各的：它们本就
        # 不该被跨层并集拉到一起，也**不报警**（轮廓不同是正常的，不是 offset 标错）。
        subs = _split_same_plan(mem, anchors) if len(mem) > 1 else [mem]
        if len(subs) > 1:
            n_split += 1
        for sub in subs:
            if not _union_into(sub, anchors, per):
                n_skip += 1
                continue
            if len(sub) > 1:
                n_used += 1
            # ★★ 2026-09-16 竖向贯通（用户判据：「井是竖向棱柱 —— 图纸漏画也要贯通」）。
            #   底层平面按制图规定只画「起步几级 + 45° 剖断线」（c006 一层翼井：5 级 /
            #   级距 0.270 / 跑长 1.08 < MIN_FLIGHT_RUN 1.5），顶层常常只画「到达」一跑，
            #   出屋面梯间踏步线又可能长于 3.0m（c114）—— 这几种图上**有梯段**却认不出井，
            #   那一层整口井消失，体检就报「楼梯井消失」（实测 c006 F0 6 口、c114 F5 1 口）。
            #   口径：已成组（≥2 层）的井 = 真井；把它补给**其余各层**，条件是
            #   「本层轮廓 ∩ 井盒 ≥ VERT_FILL_CONTAIN × 盒面积」——人能从这层进这口井。
            #   护栏（都是实测反例）：塔楼相对裙楼（c006 F7~F10 的翼井盒落在塔楼轮廓外）、
            #   退台（c103 F5 南半块已无此块）都不满足包含判据 ⇒ 不补（宁缺勿造）。
            if len(sub) >= 2:
                _bbox = [b for _f, _wi, b in sub]
                u = {"x0": min(b[0] for b in _bbox), "x1": max(b[2] for b in _bbox),
                     "yBot": min(b[1] for b in _bbox), "yTop": max(b[3] for b in _bbox)}
                wbox = _box(u["x0"], u["yBot"], u["x1"], u["yTop"])
                if wbox.area > 0:
                    members = {fi for fi, _wi, _b in sub}
                    ref = per[sub[0][0]][sub[0][1]][0]
                    for fi, fl in enumerate(floors or []):
                        if fi in members:
                            continue
                        poly = _outline_poly(fl)
                        if poly is None or poly.is_empty:
                            continue
                        if wbox.intersection(poly).area < VERT_FILL_CONTAIN * wbox.area:
                            continue
                        if any(abs((w.get("x0") or 0) - u["x0"]) < 0.6
                               and abs((w.get("yBot") or 0) - u["yBot"]) < 0.6
                               for w in (fl.get("stairwells") or [])):
                            continue                      # 该层这个位置已经有井，别重复
                        add = {k: v for k, v in ref.items() if k != "shaft"}
                        add["shaft"] = dict(u)
                        fl.setdefault("stairwells", []).append(add)
                        n_fill += 1

    if n_skip:
        print("   ⚠ 跨层井道并集跳过 %d 组：**同平面**各层轮廓原点相差 > %.2fm（局部坐标系逐层"
              "漂移，多半是 profile.offset 标错）—— 已保留逐层井道，请先修 profile"
              % (n_skip, VERT_FRAME_TOL))
    if n_split:
        print("   · 跨层井道并集按平面拆成子组：%d 组（组内各层非同平面 —— 退台/多翼/连体楼"
              "属正常，不报警）" % n_split)
    if n_fill:
        print("   · 楼梯井竖向贯通：按「本层轮廓包含井盒」补给 %d 处（本层图上没画出井符号）"
              % n_fill)
    return n_used


def unresolved_wells(wells, walls, min_enc=0.45):
    """围合不起来的井（扩不到墙 / 井道围合率低于门槛）→ 调用方登记 unresolved，不渲染。"""
    out = []
    for i, m in enumerate(measure(wells, walls)):
        if m["shaft"] is None:
            out.append((i, "no_shaft"))
        elif m["enc"] < min_enc:
            out.append((i, "enc=%.2f" % m["enc"]))
    return out
