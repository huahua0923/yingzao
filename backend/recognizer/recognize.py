# -*- coding: utf-8 -*-
"""识别入口：读 DXF → 分类构件 → 逐层组装 → 写 floors/floor{N}.json。"""
import json
import os
import ezdxf

from shapely.geometry import LineString, Polygon, box

from .classify import classify
from .floor import (extract_floor, expand_shared_sheets, reference_outline_for,
                    wall_pts_for_floor, unify_floor_set, outline_for_floor)
from .geometry import derive_walls_and_outline
from .profile import floor_of, to_local
from . import outline as OUT
from . import stairs as _stairs
from .standard import STANDARD, emit_spec


PARAPET_T_DEFAULT = 0.24      # 图上实测：c006 裙楼屋面边缘双线间距 0.24m（采样 0.256/0.261）
PARAPET_MIN_AREA = 1.0        # 退台屋面小于此不围（轮廓碎屑）
PARAPET_MIN_SEG = 0.5         # 单段女儿墙面积下限
PARAPET_MIN_MID_M = 3.0       # 单段女儿墙中线长下限（米）—— 短于此是轮廓碎屑，不立墙
# 竖向贯通（电梯井同口径）：本层轮廓 ∩ 井盒 ≥ 该比例 ⇒ 这层这个位置就是同一口井。
# 与 `stairs.VERT_FILL_CONTAIN` 同一个数、同一个理由，取楼梯侧的定义做单一来源。
VERT_FILL_CONTAIN = _stairs.VERT_FILL_CONTAIN


def add_terrace_parapets(geoms, S, p):
    """（占位，正体在下方同名定义之后追加）"""
    return _add_terrace_parapets_impl(geoms, S, p)


def attach_elevators_to_floors(geoms):
    """电梯竖井**跨层并集**：同位置的井补到它覆盖到的每一层（建筑规定：竖井竖向贯通）。

    为什么需要：图纸上电梯井的 X 图例不是每层都画全（有的层只画轿厢、有的层只画门洞），
    实测 12 栋出现"电梯数各层不一致""相邻层井位不重合"。而竖井是竖向棱柱 —— 同一口井
    必须层层对齐、层层都在（楼梯井那边 `stairs.attach_shafts_to_floors` 早就是这么收的）。

    口径：按位置聚类（1.0m 网格，井位逐层偏差 <0.3m，网格不会误分/误合）；同簇出现在
    **≥2 层**即认定为真井，把它补到该簇覆盖到的每一层；尺寸取**最低那层**那次（图纸最全）。
    只 append `geoms[F]["elevators"]`，不动 outline/rooms/walls。
    """
    Fs = sorted(geoms)
    if len(Fs) < 2:
        return 0
    clusters = {}
    for F in Fs:
        for e in (geoms[F].get("elevators") or []):
            key = (round(e["x"] / 1.0), round(e["y"] / 1.0))
            clusters.setdefault(key, {})[F] = e
    # ⚠️ 1m 网格会把**同一口井**按 0.5m 的量化边界劈成两簇（实测 c022：补完后 F1 变成 4 台）⇒
    #   改成**带容差的连通聚类**（同层之间中心距 ≤1.2m 归并；井间最小 2.4m，不会误合）。
    import math as _m
    items = []
    for F in Fs:
        for e in (geoms[F].get("elevators") or []):
            items.append((F, e["x"], e["y"], e))
    parent = list(range(len(items)))

    def _find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _m.hypot(items[i][1] - items[j][1], items[i][2] - items[j][2]) <= 1.2:
                ra, rb = _find(i), _find(j)
                if ra != rb:
                    parent[ra] = rb
    clusters = {}
    for i, (F, _x, _y, e) in enumerate(items):
        clusters.setdefault(_find(i), {})[F] = e
    added = 0
    dropped = 0
    for _key, per in clusters.items():
        lo, hi = min(per), max(per)
        ref = per[lo]
        # ★★ 2026-09-16 竖向贯通改成**双向 + 轮廓包含**（与楼梯井同一口径，见
        #   `stairs.attach_shafts_to_floors` 里同名的「竖向贯通」段）：
        #   井道是竖向棱柱，图纸某层不画井符号是常态（只画门洞/轿厢，或整层省掉）。
        #   判据 = 「本层轮廓 ∩ 井盒 ≥ VERT_FILL_CONTAIN × 盒面积」⇒ 这层这个位置就是同一口井。
        #   · 补**上层**：原「补到顶」口径（实测 c041 F2→F5、c056 F2→F5 各少井）。
        #   · 补**下层**：电梯必须到地面（实测 c041 F0/F1、c085 F0→F1~F5 —— 这两栋一直被
        #     构件体检报「电梯数各层不一致」，就是只补上不补下）。
        #   护栏：塔楼相对裙楼、退台、连体处轮廓不覆盖 ⇒ 不补（宁缺勿造）。
        members = set(per)
        b = (ref.get("x0"), ref.get("y0"), ref.get("x1"), ref.get("y1"))
        if None in b:
            continue
        wbox = box(b[0], b[1], b[2], b[3])
        if wbox.is_empty or wbox.area <= 0:
            continue
        # span = 这口井"应该贯通到"的全部楼层 = 已经探到的层 ∪ 井盒落在其轮廓内的层
        span = sorted(members)
        for F in Fs:
            if F in members:
                continue
            ol = geoms[F].get("outline") or []
            if len(ol) < 3:
                continue
            try:
                fp = Polygon(ol)
                if not fp.is_valid:
                    fp = fp.buffer(0)
            except Exception:                                      # noqa: BLE001
                continue
            if fp.is_empty or wbox.intersection(fp).area < VERT_FILL_CONTAIN * wbox.area:
                continue
            span.append(F)
        # ★ 收口判据：井道是竖向棱柱 —— **只可能存在于一层**的"井"不是井，是墙洞误检。
        #   实测 c041 F2 多出来的那口（1.38×1.83 @(-20.6,-12.4)）在上下各层轮廓里都落不下去
        #   （该处是轮廓凹角），既补不上也贯通不了 ⇒ 删掉它，构件体检立刻不再报
        #   「F2 电梯数2≠下层1」。span ≥2 的照旧补层。
        if len(span) < 2:
            for F in sorted(members):
                lst = geoms[F].get("elevators") or []
                if ref in lst:
                    lst.remove(ref)
                    dropped += 1
            continue
        for F in span:
            if F in members:
                continue                      # 本层已经探到，别再补一遍
            geoms[F].setdefault("elevators", []).append(dict(ref))
            added += 1
    return added


def _add_terrace_parapets_impl(geoms, S, p):
    """给**中间退台屋面**补一圈女儿墙（`type="parapet"` 的墙）。

    为什么需要：`parapet` 这个墙类型**此前没有任何生产者** —— 全库 49 栋 0 面，而消费者有
    5 处（GLB `build_walls`、SU 配色 `su_spec_floors`、`qa_structural` 的墙计数口径、
    `_dxf_audit` 的墙面积、平面图 PNG 上色）。后果是中间退台屋面成了**裸楼板**：c006 的
    裙楼屋面（F6）5701㎡ 四周没有女儿墙，SU 里看就是一块大板悬在裙楼顶上（「楼板多出来了」）。

    口径（几何推导，不按楼号硬编码）：退台屋面 = 本层足迹 − **其上所有楼层足迹的并集**
    ＝暴露给天空的那部分；沿其**外环**内缩 t 的环带就是女儿墙（外皮与屋面边齐平）。
      · 顶层不做 —— 它的女儿墙由 GLB `add_parapet(top_ol, …)` 程序化生成；
      · 顶层**下一层**不做 —— GLB 的 `roof.wingRoof` 已给那块出板 + 女儿墙，再做会叠两层；
      · 首层退台必为空，自然跳过。

    厚度 `p.style["parapet_t"]`（c006 = 0.24，图上量的），缺省 `PARAPET_T_DEFAULT`；
    高度用 `S["parapet_h"]`（0.9），与 GLB 的程序化女儿墙同一个量。

    调用点：全部楼层就绪、`attach_shafts_to_floors` **之后**（女儿墙是屋面矮墙、不是井道
    围合墙 —— 见 `stairs.solid_union` 的过滤）、写盘之前。只 append `walls`，
    不动 `outline`/`outline_parts`/`rooms`/`windows`（所以轮廓与房间口径逐字节不变）。
    """
    Fs = sorted(geoms)
    if len(Fs) < 3:
        return 0
    t = float((getattr(p, "style", None) or {}).get("parapet_t") or PARAPET_T_DEFAULT)
    h = float(S.get("parapet_h") or 0.9)
    outl = {F: OUT.floor_outline(geoms[F]) for F in Fs}
    above, acc = {}, None
    for F in reversed(Fs):
        above[F] = acc
        if not outl[F].is_empty:
            acc = outl[F] if acc is None else acc.union(outl[F]).buffer(0)
    n = 0
    for F in Fs[:-2]:
        if above.get(F) is None or above[F].is_empty or outl[F].is_empty:
            continue
        terra = outl[F].difference(above[F]).buffer(0)
        if terra.is_empty or terra.area < PARAPET_MIN_AREA:
            continue
        walls = []
        for part in ([terra] if terra.geom_type == "Polygon" else list(terra.geoms)):
            if part.area < PARAPET_MIN_AREA:
                continue
            # 沿**外缘**内缩 t 的环带。**不要先填洞再内缩**：退台屋面是个环，填洞后的实心
            # 块在 H 形轮廓的窄颈处内缩会**碎成多块**，`difference` 把碎块之间的缝也留成
            # 墙体 —— 实测 c006 多出 76.3㎡ 的假墙（band 外框周长 831.79m、2A/L=0.42 而非
            # 0.24）。带洞的环自身内缩只会变细、不会碎。
            band = part.difference(
                part.buffer(-t, join_style=2, mitre_limit=2.0)).buffer(0)
            if band.is_empty:
                continue
            # ① 只留**沿屋面外缘**的那一圈。`part` 带洞 ⇒ `buffer(-t)` 会把洞**外扩** t，
            # 于是 band 里多出一圈沿上层主体（塔楼）边界的"洞缘带"；`difference` 与
            # `buffer` 的相互作用还会在塔楼四周留下锯齿状的切边（实测 c006 残留 25.8㎡
            # / 中线 106m）。用「距外缘 ≤1.2t」直接裁掉，判据就是女儿墙的定义本身。
            band = band.intersection(
                LineString(part.exterior).buffer(t * 1.2, join_style=2, mitre_limit=2.0)
            ).buffer(0)
            if band.is_empty:
                continue
            # ② 保险丝：把上层主体（塔楼）所在区块**连外皮一起**减掉。塔楼外墙脚没有女儿墙
            # （塔楼外墙本身就是竖向围护）。⚠ 必须用 `buffer(1.02t)` 而不是裸的 `above[F]`：
            # c006 的退台环与塔楼轮廓相通，塔楼边界本身就是 `part.exterior` 的一段 ⇒ band
            # 会贴着塔楼长出一条 0.24 宽的「洞缘带」，而它**在塔楼之外**，裸减塔楼减不掉
            # （实测残留 25.8㎡ / 中线 106m，段厚量出来也偏）。
            if above.get(F) is not None and not above[F].is_empty:
                band = band.difference(
                    above[F].buffer(t * 1.02, join_style=2, mitre_limit=2.0)).buffer(0)
                if band.is_empty:
                    continue
            for g in ([band] if band.geom_type == "Polygon" else list(band.geoms)):
                # 碎屑（轮廓凹角/锯齿处 2~3m 的小段）不立墙：`PARAPET_MIN_SEG` 判面积，
                # 再加一道中线长下限，短于 3m 的段一律丢。
                if g.area < PARAPET_MIN_SEG or g.length / 2 < PARAPET_MIN_MID_M:
                    continue
                walls.append({
                    "type": "parapet",
                    "poly": [[round(x, 3), round(y, 3)] for x, y in g.exterior.coords][:-1],
                    # **洞必须带上**：环带是「屋面外缘 − 内缩 t」，中间是塔楼/上层主体 ——
                    # 只留 exterior 就等于把整块屋面填成实心板（GLB/SU 都会长出一块盖住
                    # 裙楼屋面的 5701㎡ 大板）。下游 `build_walls` 的 parapet 分支已按
                    # ext+holes 建体，SU 的 `_add` 原生吃 interiors。
                    "holes": [[[round(x, 3), round(y, 3)] for x, y in hn.coords][:-1]
                              for hn in g.interiors],
                    "thickness": round(t, 2),
                    "height": h,
                })
        for i, w in enumerate(walls):
            w["id"] = "w%d-p%d" % (F, i)
        if walls:
            geoms[F].setdefault("walls", []).extend(walls)
            n += len(walls)
            print(f"[{p.name} F{F}] 屋面女儿墙 {len(walls)} 段（退台屋面 {terra.area:.1f}㎡）")
    return n


def localize_columns(columns_raw, p, S):
    """结构柱按图来：图里画了哪层就哪层，返回 {floor: [柱]}。
    柱中心取自 CAD 包围盒中心，宽深取自包围盒实际尺寸（classify_line 已按 INSERT
    xscale/yscale 编码真实边长，如 600mm），不再用标准值 0.5m、也不假设贯通全高复制到每层。

    第 5 位（可选）= 半径(mm)：>0 表示这根柱图上是 **CIRCLE**（圆柱，c009 Φ848），
    转成 JSON 的 `round`（半径，米），GLB 据此出圆柱而非方盒。老口径 4 元组 → round 缺省。
    """
    by_floor = {}
    for item in columns_raw:
        x0, y0, x1, y1 = item[:4]
        round_r = float(item[4]) if len(item) > 4 and item[4] else 0.0
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        f = floor_of(p, cx, cy)
        if f is None:          # floor_y_bands 窗口外（基础/剖面/别栋的图）→ 这棵柱不属于本楼
            continue
        x, y = to_local(p, cx, cy, f)
        # 过渡层（slab_from 复用裙楼楼板）的柱画在「源楼层 Y」（裙楼平面），与塔楼墙不在同一
        # DXF Y 列（c006 第7层柱在裙楼 cy=89295、墙在塔楼 cy=84494，差 4.8m）→ 柱按源楼层 cy
        # 居中，与楼板同源，否则柱比塔楼墙/楼板整体偏 4.8m。
        tr = (p.transition or {}).get(f)
        # ⚠️ 2026-09-15 停用：这条口径按「柱画在源层 Y 列」把 y 重算成 (cy - cy[src])，
        # 只对「同列 4.8m 微差」成立。c006 F6 现在用 slab_from=7，源层 F7 的 cy 与 F6 差
        # **135m**（东列不同图带）→ 重算把 30 根柱甩到 y=−135m、再被下面的 >100m 规则剔剩 2 根
        # （实测交付柱 2 根、坐标 (±54.4, −88.5)）。实测 F6 图上柱本来就画在**本层**图带
        # （本地 y −36.9~12.0，与墙同一列），直接 to_local 就对。
        if False and tr and tr.get("slab_from") is not None and p.floor_plans:
            src_cy = p.floor_plans[tr["slab_from"]][1]
            y = (cy - src_cy) / 1000.0
        # 屋顶设备副块（电梯机房/水箱柱）画在塔楼 X 列、Y 却落在裙楼楼层区间（c006 第11层），
        # localY 达 125~181m，远超任何真实柱位（最大楼 c103 也只有 84m）→ 丢弃，否则 GLB
        # 长出一根 181m 的悬空柱带。阈值 100m 在「真实最大 84m」与「副块 125m」之间，安全。
        if abs(x) > 100.0 or abs(y) > 100.0:
            continue
        # ★ 退化柱（2026-09-17，c020/c037/c044 逐带锚点差 1 的根因）：
        #   图纸里存在 **宽度为 0 的柱**（c020 F1 实测 w=0.000 / d=0.240），
        #   它进 floors JSON 会被算进"应得柱数"，但 SU 规格建不出零宽度实体 → 被丢弃，
        #   于是逐带锚点报「实得 14 != 应得 15」。这里在**交付前**剔掉退化柱
        #   （w 或 d < 0.05m；真实柱最小 0.24m 见 c020 实测），从源头对齐两侧口径。
        _w_mm, _d_mm = abs(x1 - x0), abs(y1 - y0)
        if min(_w_mm, _d_mm) < 50.0:
            continue
        col = {
            "x": round(x, 3),
            "y": round(y, 3),
            "w": round((x1 - x0) / 1000.0, 3),
            "d": round((y1 - y0) / 1000.0, 3),
        }
        if round_r > 0.0:
            # 只在真是圆柱时加键：49 栋里只有 c009 用 CIRCLE 画柱，其余楼的 floor JSON
            # 保持**逐字节不变**（否则全量重建都会多出一个 round:0.0，白白扩大改动面）。
            col["round"] = round(round_r / 1000.0, 3)
        by_floor.setdefault(f, []).append(col)
    return by_floor


def recognize(p):
    """对 p（BuildingProfile）执行完整识别，返回楼层号列表。"""
    # ★ 层高单点：profile.layer_height 覆盖 STANDARD["floor_h"]（2026-09-14 c006 实测）。
    #   此前识别只认 STANDARD 里的 4.2 —— profile 改成 3.5 也没用，**一重跑识别就回到 4.2**，
    #   整栋因此高 46.2m（应为 11×3.5=38.5）。墙高按同一关系 floor_h - slab_t 联动。
    S = dict(STANDARD)
    _lh = getattr(p, "layer_height", None)
    if _lh and abs(float(_lh) - float(S.get("floor_h", 4.2))) > 1e-9:
        _old = float(S["floor_h"])
        S["floor_h"] = float(_lh)
        S["wall_h"] = round(float(_lh) - float(S.get("slab_t", 0.2)), 3)
        print("[%s] 层高用 profile 的 %.2fm（标准默认 %.2fm），墙高 %.2fm"
              % (p.name, S["floor_h"], _old, S["wall_h"]))
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()

    if getattr(p, "classifier", "lwpolyline") == "line":
        from .classify_line import classify_line
        walls, doors, stairs, columns_raw = classify_line(msp, p)
    else:
        walls, doors, stairs, columns_raw = classify(msp, p)

    # 一张图描述多层（profile.sheet_floors，默认 None 不动）：把该图的构件复制进目标图带。
    # 必须在 _floor_of_pts/floors 之前 —— 复制出的构件质心已落在目标带，楼层集合才对。
    walls, doors, stairs, columns_raw = expand_shared_sheets(
        p, walls, doors, stairs, columns_raw)

    os.makedirs(p.out_dir, exist_ok=True)
    # 清掉旧楼层文件：层数修正后（c103 11→6、c104 10→5）会残留 floor6~10.json，
    # 污染 compare_floors 逐层比对与 building.html 渲染（读到僵尸层）
    for stale in os.listdir(p.out_dir):
        if stale.startswith("floor") and stale.endswith(".json"):
            os.remove(os.path.join(p.out_dir, stale))
    # 用「质心」判定楼层（旋转墙/阶梯楼比首点更稳；两列布局需 X 判列）
    def _floor_of_pts(pts):
        return floor_of(p, sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))

    floors = sorted({_floor_of_pts(pts) for pts in walls}
                    | {_floor_of_pts(pts) for pts in doors})
    floors = [F for F in floors if F is not None]   # 窗口外的杂项不进"交付楼层集合"

    # sheet_floors 的**键**只是「一张图的带号」，不是楼房层 —— 它的内容已经并进目标楼层，
    # 再留一个独立楼层就多出一个畸形层（c009 那个 1416㎡ 的圆厅底层，正是我们要修的病）。
    if p.sheet_floors:
        floors = [F for F in floors if F not in p.sheet_floors]

    # 交付层号必须**从 0 起连续**：只读门禁 qa_structural.load_floors() 从 floor0.json 顺序读、
    # 遇缺即停（"for i in range(64): if not isfile: break"）。层号不是 0 基时，门禁读到 0 层就
    # break → 本栋被判「无楼层」→ 全库汇总在打印处崩（unpack 4 元组，2026-09-12 c009 实测）。
    # 起因：c009 一张图描述两层（通高圆厅），floor0 被 sheet_floors 并走后交付从 floor1 起。
    # 这里只**喊**不改数据：层号是 profile 的口径（cy / floor_ys / sheet_floors 键），
    # 该动哪把旋钮只能由人判断（c009 = cy 上移一层 + sheet_floors 键改 -1，其余 49 栋 0 基）。
    if floors and floors[0] != 0:
        print("⚠ 交付层号不是 0 基连续：floors=%s —— 只读门禁 load_floors 会在 floor0 处"
              "遇缺即停，本栋会被判「无楼层」并崩掉全库汇总。请检查 profile 的 cy /"
              " floor_ys / sheet_floors 键口径。" % (floors[:4],))

    columns_local = localize_columns(columns_raw, p, S)
    top = max(floors)

    # 多翼/阶梯楼统一 footprint（profile.outline_unify，默认 False 不启用）：低层墙 union
    # 碎片化时 derive_walls_and_outline 的 max(area) 只留最大一翼 → 轮廓塌成小片、质心横漂
    # （c009 F0 21 片/F1 39 片 → 低层错位 54m）。全楼层里挑「轮廓面积最大」的一层当基准
    # （墙最完整，c009 为顶层 F5），全楼复用该轮廓，消除低层塌陷。逻辑抽到 reference_outline_for，
    # 与 extract_rooms_generic.py 共用，防止渲染/房间两路漂移。
    ref_F, reference_outline = reference_outline_for(p, walls, floors)
    unify_set = unify_floor_set(p, floors)

    geoms = {}
    outline_cache = {}
    for F in floors:
        slab_outline = None
        wall_x = None
        wall_x_clip = None
        keep_near_stairs_m = None
        tr = (p.transition or {}).get(F)
        if tr and tr.get("slab_full_width"):
            # ★ 楼板用**本层图的全宽轮廓**（2026-09-14 c006 F6 实测）：过渡层建墙时按 wall_x
            #   只留塔楼、弃裙楼女儿墙 —— 那对**墙**是对的；但**楼板**必须覆盖全宽，
            #   否则两翼屋顶敞着。旧做法是 `slab_from: 0` 复制 F0 的轮廓，量出来多 538㎡
            #   （F6 本层全宽 5418.5 vs F0/F5 的 5956.2）—— 那是臆造。
            _wp_all = wall_pts_for_floor(F, walls, p, None, None, None)
            _ol_all, _, _ = derive_walls_and_outline(_wp_all, p, is_top=(F == top))
            if _ol_all is not None and not _ol_all.is_empty:
                slab_outline = _ol_all
                print("  [%s F%d] 楼板用本层全宽轮廓 %.1f㎡（未被 wall_x 裁）"
                      % (p.name, F, float(_ol_all.area)))
        if tr:
            src = tr.get("slab_from")
            if src is not None:
                # ⚠️ 源层**可能还没算到**（本循环按楼层升序，F6 借 F7 就是前向引用）——
                # 原实现只在 `outline_cache` 里找，前向引用会静默不生效（F6 楼板退回自算 721.7）。
                # 缓存里没有就现场推一遍（与 reference_outline_for 同一路径、同一 wall_x 口径）。
                _src_ol = None
                if src in outline_cache:
                    _src_ol = OUT.floor_outline(outline_cache[src])
                else:
                    _tr_src = (p.transition or {}).get(src)
                    _o, _g, _ = derive_walls_and_outline(
                        wall_pts_for_floor(src, walls, p,
                                           (_tr_src or {}).get("wall_x")),
                        p, is_top=(src == top))
                    if _o is not None and not _o.is_empty:
                        _src_ol = _o
                if _src_ol is not None:
                    slab_outline = OUT.shift(_src_ol, 0.0, 0.0)
                # **不平移**（2026-09-15 c006 F6 实测踩坑）：to_local 把每层都居中到**本层**
                # floor_plans 的 (cx, cy)，所以「同一个 footprint」在各层本地坐标里都落在原点
                # 附近；再按 (cy[src]-cy[F]) 平移是「同一点在两个坐标系之间换坐标」，两码事。
                # c006 F6（东列 y=84494）借 F7（东列 y=219495）时，那段平移把塔楼楼板甩到
                # y=−135m（F6 轮廓 bbox y[−11.6,46.6]、柱心跑到 y=−88.5）。`outline_for_floor`
                # （统一 footprint 那条路）当年就是因为同一个错被改掉的，这里同步。
            wall_x = tr.get("wall_x")
            wall_x_clip = tr.get("wall_x_clip")
            keep_near_stairs_m = tr.get("keep_near_stairs_m")
            slab_only = bool(tr.get("slab_only"))
        else:
            slab_only = False
        # 统一 footprint：只在 unify_floor_set 的楼层子集里应用基准轮廓（阶梯楼裙楼统一、
        # 塔楼各自独立）；按 cy 差平移到本层本地坐标（见 outline_for_floor）。
        # `slab_only`（profile.transition 里给）：这层的**轮廓就用复用的楼板轮廓**，不再拿本层
        # 自算轮廓去并（并出来的都是本层图上叠画的裙楼女儿墙碎块）。c006 F6 = 7 层 = 塔楼那一片，
        # 图纸上同时还叠着裙楼屋面的女儿墙 → 自算+并集会把 x=−54.5/−39.7/29/42 四处碎块并进来
        # （1024.8㎡，真值 912.70㎡；三块共 104.8㎡ 且都在塔楼外）。
        if F in unify_set:
            override = outline_for_floor(p, ref_F, reference_outline, F)
        elif slab_only and slab_outline is not None:
            override = slab_outline
        else:
            override = None
        geom = extract_floor(F, walls, doors, stairs, columns_local, p, S, F == top,
                             slab_outline=slab_outline, wall_x=wall_x, wall_x_clip=wall_x_clip,
                             keep_near_stairs_m=keep_near_stairs_m,
                             outline_override=override)
        if geom is None:
            print(f"[{p.name} floor {F}] 空轮廓（无墙），跳过")
            continue
        geoms[F] = geom
        outline_cache[F] = geom
        print(f"[{p.name} floor {F}] 墙={len(geom['walls'])} 窗={len(geom['windows'])} "
              f"房间={len(geom['rooms'])} 门={len(geom['doors'])} 柱={len(geom['columns'])} "
              f"电梯={len(geom.get('elevators', []))} 台阶={len(geom['stairs'])} "
              f"楼梯井={len(geom['stairwells'])}"
              + (" 屋顶=有" if "roof" in geom else ""))

    if not geoms:
        raise SystemExit(f"[{p.name}] 所有楼层空轮廓，识别失败")

    # 顶层可能因空轮廓被跳过 → 取实际识别到的最高层
    top = max(geoms)

    # 阶梯结构：顶层是中央主体，翼楼屋面在下一层顶部（= 顶层楼板底部）。
    # 翼楼屋面楼板 = 下一层满 footprint outline − 顶层中央主体 outline，写入顶层 roof.wingRoof。
    if top > 0 and (top - 1) in geoms and "roof" in geoms[top]:
        try:
            wing = (OUT.floor_outline(geoms[top - 1]).buffer(0)
                    .difference(OUT.floor_outline(geoms[top]).buffer(0)))
            # ★ 2026-09-16：退台差集可能出**无效环**（自交），下游 add_slab/add_parapet 会抛
            #   TopologyException 把整栋 GLB 挂掉（c103 修帧后实测）。这里先修形再落盘。
            if not wing.is_empty and not wing.is_valid:
                wing = wing.buffer(0)
            if not wing.is_empty:
                polys = [wing] if wing.geom_type == "Polygon" else list(wing.geoms)
                wing_roof = [
                    [[round(x, 3), round(y, 3)] for x, y in g.exterior.coords]
                    for g in polys if g.area >= 2.0   # 过滤两轮廓边界微错位产生的碎屑
                ]
                if wing_roof:
                    geoms[top]["roof"]["wingRoof"] = wing_roof
        except Exception as e:
            print(f"[{p.name}] 翼楼屋面计算失败（跳过）: {e}")

    # 楼梯井道：踏步盒四向扩到墙，**再跨层取并集**（井道是竖向棱柱，同一口井每层一样大）。
    # 逐层算会把并集切碎 —— 顶层常常只画了到达的那一跑，只认出半个井，楼板洞跟着只挖一半。
    # 必须在全部楼层就绪、墙定稿之后、写盘之前调这一次（`_wall_thin_batch` 会换墙，换墙后
    # 它自己的 `refresh_shafts` 会再算一遍 —— 那才是**交付的墙**）。
    n_g = _stairs.attach_shafts_to_floors(list(geoms.values()))
    if n_g:
        print(f"[{p.name}] 楼梯井道 {n_g} 口（已跨层取并集）")

    # ★ 2026-09-16 **电梯竖井也按"竖向贯通"收口**（用户判据：按建筑规定，别死板描图）：
    #   图纸上电梯井符号（X 图例）不是每层都画全 —— 实测 c022/c027/c056/c057/c059/c080/
    #   c083~c086/c103 等 12 栋出现"电梯数各层不一致""相邻层井位不重合"，而**竖井是竖向棱柱**，
    #   同一口井必须层层对齐、层层都在（楼梯井那边 `attach_shafts_to_floors` 早就是这么做的）。
    #   口径：按位置聚类（1m 网格），同簇出现在 ≥2 层即认定是一口真井，把它补到该簇覆盖到的
    #   每一层；尺寸/朝向取最低那层那次（图纸最完整）。只 append `elevators`，不动其它字段。
    _added = attach_elevators_to_floors(geoms)
    if _added:
        print(f"[{p.name}] 电梯竖井补层 {_added} 处（跨层并集）")

    # 退台屋面女儿墙（**中间层**：顶层与顶层下一层已由 GLB 程序化出，见函数 docstring）
    add_terrace_parapets(geoms, S, p)

    # ★ 中庭开洞（2026-09-14 c006 八角厅实测）：通高中庭下面几层的楼板要挖穿。
    #   图纸证据：F0-F3 八角厅区域 232~241 条实体、F4 起只有 3~4 条 ⇒ 中庭 F0-F3，
    #   F4 的楼板是它的屋顶（用户判据：「F4 封顶」）。
    #   两个配置分工明确（不混用）：
    #     atrium_rooms {层: [房号]} → **挖洞**（该层图上有这个房间登记）
    #     atrium_from  {层: 源层}   → **只补围护墙、不挖洞**（封顶层图上不画八角厅）
    _atr = getattr(p, "atrium_rooms", None) or {}
    _atrf = getattr(p, "atrium_from", None) or {}
    for _F, geom in geoms.items():
        _nums = _atr.get(str(_F)) or _atr.get(_F) or []
        _src = _atrf.get(str(_F)) or _atrf.get(_F)
        _holes, _tag = [], []
        # ① 本层房号
        for _r in geom.get("rooms") or []:
            if _r.get("number") in _nums and len(_r.get("poly") or []) >= 3:
                _holes.append(_r["poly"])
                _tag.append(_r.get("number"))
        # ② 借源层几何（封顶层）
        if not _holes and _src is not None:
            _sg = geoms.get(int(_src))
            if _sg:
                _snums = _atr.get(str(_src)) or _atr.get(_src) or []
                for _r in _sg.get("rooms") or []:
                    if _r.get("number") in _snums and len(_r.get("poly") or []) >= 3:
                        _holes.append(_r["poly"])
                        _tag.append(_r.get("number"))
        _cap_only = bool(_src is not None) and not _nums      # 封顶层：不挖，只补墙
        if _holes and not _cap_only:
            geom["atrium_holes"] = _holes
            geom["atrium_room_nums"] = list(_tag)
            print("  [%s F%d] 中庭开洞 %d 处：%s" % (p.name, _F, len(_holes), ",".join(_tag)))
        if _holes and _cap_only:
            # 封顶层的围护墙：洞的外环就是那圈围护（图纸不画，但建筑上必须有）。
            # 反向量具证据：F4 楼板外环 16.9% 的点离最近墙 >0.35m、最远 26.36m。
            from shapely.geometry import Polygon as _PG
            _wt = float(S.get("outer_wall_t", 0.30))
            _n0 = len(geom.get("walls") or [])
            for _h in _holes:
                try:
                    _pg = _PG(_h)
                    if not _pg.is_valid:
                        _pg = _pg.buffer(0)
                    _ring = _pg.buffer(_wt / 2.0, join_style=2).difference(
                        _pg.buffer(-_wt / 2.0, join_style=2)).buffer(0)
                except Exception:
                    continue
                for _cp in ([_ring] if _ring.geom_type == "Polygon"
                            else list(getattr(_ring, "geoms", []))):
                    geom.setdefault("walls", []).append({
                        "id": "w%d-%d" % (_F, len(geom.get("walls") or [])),
                        "type": "outer",
                        "thickness": round(_wt, 3),
                        "height": round(float(S.get("wall_h", 3.3)), 3),
                        "poly": [[round(x, 4), round(y, 4)] for x, y in _cp.exterior.coords],
                        "holes": [],
                    })
            print("  [%s F%d] 封顶层补围护墙 %d 段（沿中庭洞外环，借 F%s 几何）"
                  % (p.name, _F, len(geom.get("walls") or []) - _n0, _src))


    for F, geom in geoms.items():
        out = os.path.join(p.out_dir, f"floor{F}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(geom, f, ensure_ascii=False, indent=1)

    # 前端 fetch 的规格（数据驱动查看器与 GLB 同源防漂移）。
    # 外墙厚是每栋楼 profile 的固有参数（理化楼门垛实测 0.24，非标准默认 0.30），
    # 覆盖进 spec 使门头过梁/门洞深与真实墙厚一致，避免「过梁比墙宽」。
    overrides = {}
    if getattr(p, "outer_wall_t", None) is not None:
        overrides["outer_wall_t"] = p.outer_wall_t
    # ★ 层高单点（2026-09-14 c006 实测）：识别用的 S["floor_h"]/["wall_h"] **必须**写进
    #   spec.json —— 否则下游（su_spec_floors_fleet / build_standard_glb）读 spec 时
    #   拿 STANDARD 兜底的 4.2，出现「floors 是 3.5、模型却是 4.2」两套层高
    #   （实测：11 层楼总高 46.2m，应为 11×3.5=38.5m）。
    overrides["floor_h"] = S["floor_h"]
    overrides["wall_h"] = S["wall_h"]
    # 注意：**不**把 style["parapet_t"] 抬进 overrides。GLB 的 `S["parapet_t"]`（现 0.5）
    # 管的是**顶层中央女儿墙**和**翼楼屋面女儿墙**——那两处图纸上没有平面（本套 DXF 无屋面
    # 平面图），改它就是臆造。退台屋面那圈有图纸依据（双线 0.24），厚度写在墙 poly 里
    # （几何自含），与 S 无关。
    emit_spec(os.path.join(os.path.dirname(p.out_dir), "spec.json"), getattr(p, "style", None), overrides)
    return floors
