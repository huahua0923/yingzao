# -*- coding: utf-8 -*-
"""单层组装：把分类好的构件 + 通用几何算法，组装成一层的标准化 JSON。

v2 schema（唯一几何源，building.html 与 build_standard_glb.py 共用）：
  walls[]   唯一墙源，{id, type(outer|inner|parapet), thickness, height, poly}
  windows[] 外墙窗开口，{id, wallId, x, y, w, h, sill, horiz, dx, dy, nx, ny}
  columns[] 结构柱（每层同 footprint，columns_local 已算好）
  doors[]   {x, y, w, h, horiz, outer}（门 = 墙被切断的 gap，门板渲染时再画）
  roof      仅顶层：{roofT, parapetH, parapetT}（中央主体屋面 + 女儿墙由 outline 生成）

关键语义（见标准方案）：
  - 门 = gap 不是 hole：门盒深 > 墙厚，difference 把墙切成两段，holes 不再输出。
  - 女儿墙 = 中央主体由顶层 outline 外扩生成；翼楼屋面女儿墙是轮廓外的真实墙段，
    保留实测厚度、贴本层楼板标高（type=parapet, level=slab）。
"""
import json
import math
import re
from shapely.geometry import Polygon, box, Point, LineString
from shapely.ops import nearest_points, unary_union

from .geometry import (
    derive_walls_and_outline, detect_doors, detect_stairwells, facade_windows, r2,
)
from .component_library import (DOOR_LEAF_MAX, DOOR_LEAF_MIN, INNER_WALL_CENTROID_FACTOR,
                                is_door_symbol_pts)
from .profile import to_local, floor_of, sheet_shift, frame_center
from . import elevator as EV
from . import openings
from . import outline as OUT
from . import stairs as _stairs


def _is_arc_door_triple(L):
    """三点是否为 classify.`_arc_doors` 还原的「门弧」`[贴墙端, 弧心, 扇尖]`。

    判据 = 与 geometry._hinge_leaf 同构，只是点数为 3：**以中间点为顶点的两条边等长且
    垂直**。这是对 classify 构造不变量的复核（非 door_by_points 的楼里 `doors` 只可能装
    这种三点），不成立就退回旧的 bbox 跨度口径 —— 只兜底，不静默丢门。
    """
    if len(L) != 3:
        return False
    (x0, y0), (x1, y1), (x2, y2) = L
    a = math.hypot(x0 - x1, y0 - y1)
    b = math.hypot(x2 - x1, y2 - y1)
    if not (DOOR_LEAF_MIN <= a < DOOR_LEAF_MAX):
        return False
    if abs(a - b) > 0.1 * max(a, b):
        return False
    dot = (x0 - x1) * (x2 - x1) + (y0 - y1) * (y2 - y1)
    return abs(dot) <= 0.1 * a * b


def _door_wall_horiz(local):
    """门扇所在墙的朝向 = 门符号 bbox 长轴（即门宽方向）。

    门宽（单门 1.1 / 双门 2.4）远大于门深 + 摆动弧（约 1.2~1.3），故 bbox 长轴
    就是门宽方向：长轴沿 X → 门洞横跨 X → 墙水平 → horiz=True。

    旧「短段法」找第一个 0.05~0.35m 的段当「墙厚段（垂直墙）」，但门符号顶点序列里
    第一个短段是「门垛 0.15m」（沿墙走向=门宽方向，不是墙厚），方向语义整个反了——
    实测 158 扇门判反 86 扇（54%），横墙门洞挖成竖墙门洞。bbox 长轴法实测 0 误判。
    """
    xs = [q[0] for q in local]
    ys = [q[1] for q in local]
    return (max(xs) - min(xs)) >= (max(ys) - min(ys))


def _mode_axis(local, axis):
    """门扇线坐标 = 墙中线（门垛外皮~内皮 span 的中线）。

    门符号在该轴的层级：外皮 / 门扇线(墙中线) / 内皮 / 弧顶。弧顶伸进房间 ~1.2m，
    与门垛组间隔远大于墙厚(0.24)，是离群值。门垛组 = 弧顶之外的三层，其 min/max 的
    中线就是墙中线（外皮+内皮）/2。用「最大 gap」自动定位弧顶在哪一侧（南立面弧顶
    在 y 大侧、北立面在 y 小侧），不依赖朝向。
    """
    vals = sorted(set(round(q[axis], 3) for q in local))
    if len(vals) < 3:
        return (vals[0] + vals[-1]) / 2
    gaps = [(vals[i + 1] - vals[i], i) for i in range(len(vals) - 1)]
    maxgap, gi = max(gaps)
    if maxgap > 0.3:                 # 弧顶 gap 远大于墙厚，能可靠拆出离群弧顶
        group = vals[1:] if gi == 0 else vals[:gi + 1]   # 去掉孤立的弧顶那一侧
        return (group[0] + group[-1]) / 2
    return (vals[0] + vals[-1]) / 2


def _dedupe(coords):
    """去掉相邻重复点（r2 四舍五入可能把极近点折叠成同一点，产生零长边 → GLB 除零）。
    只删中间的相邻重复，保留首尾闭合点（shapely 环要求闭合，Polygon(shell,holes) 才合法）。"""
    out = []
    for p in coords:
        if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


def _clean_emit(poly):
    """把合并墙多边形清洗成「可发射」的有效多边形列表。

    关键：r2（3 位小数 ≈ 1mm）取整可能让 buffer(0) 清洗过的多边形重新自交
    （楼梯井洞边距 < 1mm 时，取整把两条几乎重合的边折叠成交叉）→ 先取整、
    再 buffer(0) 兜底，保证 triangulate 拿到的多边形有效、不丢墙。"""
    if poly is None or poly.is_empty:
        return []
    ext = [tuple(q) for q in r2(poly.exterior.coords)]
    ints = [[tuple(q) for q in r2(i.coords)] for i in poly.interiors]
    p2 = Polygon(ext, ints)
    if not p2.is_valid:
        p2 = p2.buffer(0)
    if p2.is_empty:
        return []
    if p2.geom_type == "MultiPolygon":
        return [q for q in p2.geoms if q.area >= 0.05]
    return [p2] if p2.area >= 0.05 else []


def _clip_polyline_x(pts, x0, x1):
    """把墙折线裁到 X 区间 [x0,x1]（本地米）。

    阶梯楼（中间高两侧低）顶层墙常是一条跨满全宽的连续折线（翼楼屋面女儿墙 + 塔楼外墙
    共用一段），按质心过滤会误伤塔楼外墙、按「点在区间外就丢整条」又丢掉塔楼那半。
    这里用竖板 box 把折线裁成若干段，塔楼部分保留、翼楼部分切掉，只裁方向、不丢塔楼。
    """
    cut = LineString(pts).intersection(box(x0, -1e6, x1, 1e6))
    if cut.is_empty:
        return []
    geoms = [cut] if cut.geom_type == "LineString" else list(cut.geoms)
    out = []
    for g in geoms:
        if g.geom_type != "LineString" or g.length < 1e-6:
            continue
        out.append([(round(q[0], 6), round(q[1], 6)) for q in g.coords])
    return out


def stair_boxes_of(F, walls, p):
    """本层楼梯井的**踏步包围盒**（本地米）。井由 `detect_stairwells` 从**原始线**算 ——
    与下游（建体/门禁/剔除）同一个实现，且不吃 wall_x/wall_x_clip 的裁剪（见其 docstring）。"""
    out = []
    for s in detect_stairwells(F, walls, p):
        b = box(s["x0"], s["yBot"], s["x1"], s["yTop"])
        if b.area > 0:
            out.append(b)
    return out


def in_stair_keep_band(pt, boxes, r):
    """点是否落在「出屋面楼梯间围合带」＝踏步盒**外** r 内。

    同一判据用两次（一处实现，防漂移）：
      · `wall_pts_for_floor`：带内的线即使被 wall_x 排除也**保留**（围合墙是真构件）；
      · `extract_floor` 的布窗循环：带内的墙**不布合成窗**（合成窗是「DXF 无窗时沿立面等距
        生成」的补救，只该给建筑立面；出屋面楼梯间是屋面构筑物，图上本就没有窗，布了＝臆造）。
    ⚠️ 盒**内**不算：那是踏步线（I17 口径 a) 定义的假墙），既不留也不布窗。
    """
    return any((not b.contains(pt)) and pt.distance(b) <= r for b in boxes)


def in_stair_enclosure(pt, boxes, r):
    """点是否属于「出屋面楼梯间围合体」＝距踏步盒 r 内（**含盒内**）。

    与 `in_stair_keep_band` 差一个 `contains`：线层面盒内＝踏步线（弃），墙层面盒内＝
    **U 形围合墙环抱踏步盒**（三边包住井，质心落在盒内）—— 用带版会漏挡这批墙的合成窗。
    只用于布窗闸：围合墙属屋面构筑物，不布合成窗。
    """
    return any(pt.distance(b) <= r for b in boxes)


def wall_pts_for_floor(F, walls, p, wall_x=None, wall_x_clip=None, keep_near_stairs_m=None):
    """抽出一层的墙点列（本地米坐标）。用墙「质心 Y」判定楼层（旋转墙/阶梯楼比首点更稳）。

    wall_x：按质心 X 过滤（毫米，六教过渡层——裙楼屋面女儿墙是独立短墙，质心落塔楼区间外）。
    wall_x_clip：按 X 区间裁剪（米，理化楼顶层——翼楼女儿墙与塔楼外墙是同一条连续折线，
      只能裁剪不能按质心过滤）。
    keep_near_stairs_m：**具名口子**（铁律⑱），只对 wall_x 生效。wall_x 的本意是弃裙楼屋面
      **女儿墙**，但它按质心 X 一刀切，会把同层**出屋面楼梯间的围合墙**一起弃掉 ——
      而那些是真构件：c006 F6 实测 6 口裙楼井 3m 内 0 面墙（同楼 F5 同位置 6~12 面），
      仓库自己的不变量 I17 就报「f6 楼梯井 6/8 口围合不足（最低 0.00）」。
      ⇒ 质心落在**踏步盒外**此距离内的线即使被 wall_x 排除也保留。
      参照物是**本层井的踏步盒**，不是放宽 X 区间：女儿墙离每口井都远（c006 实测最近的
      扩出量 2.17m，女儿墙在 10m 外），所以本口子**只捞回楼梯间、不捞回女儿墙**。
      ⚠️ 「盒内」的线仍然丢 —— 那是**踏步线**（I17 口径 a) 自己就这么定义：「踏步盒内碎片墙
      = 假墙」）。第一版写成「距盒 ≤R 就留」，把踏步线一起捞了回来：c006 F6 实测多出 32 面
      盒内薄条（长短 22~54m、厚 0.118，实测是踏步线折成的锯齿条）共 49.81㎡，其中 8 面被判成
      `outer` 而自动布了 48 扇合成窗（窗 34→86），且有一条外露踏步条把 outline 撑大 0.69㎡。
      围合墙在盒**外**、踏步线在盒**内**，两者必须分开。
    """
    boxes = None
    if wall_x is not None and keep_near_stairs_m:
        boxes = stair_boxes_of(F, walls, p)
    wall_pts = []
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        # floor_of 可能返回 None（profile.floor_y_bands 判定"窗口外、不属于任何层"）
        _f = floor_of(p, cx, cy)
        if _f is not None and abs(_f - F) < 0.5:
            # 过渡层只取「建筑墙」X 区间（如六教第 7 层只留塔楼墙，弃裙楼屋面女儿墙）
            if wall_x is not None and not (wall_x[0] <= cx <= wall_x[1]):
                # ⚠️ 距离必须在**同一坐标系**里量：cx,cy 是原始 CAD 毫米，boxes 是本地米。
                # 第一版漏了 to_local ⇒ 距离差 1000 倍 ⇒ 豁免恒 0 条（探针假绿过一轮）。
                # ⚠️ 只豁免**盒外**的线：`box.contains` 把盒内（踏步线）排掉；
                #    `distance(b) <= R` 是「盒外 R 内」（点在盒内时 distance 也是 0，
                #    靠 contains 先排除，两者不能只取一个）。
                pt = Point(*to_local(p, cx, cy, F))
                if boxes is None or not in_stair_keep_band(pt, boxes, keep_near_stairs_m):
                    continue
            local = [to_local(p, x, y, F) for x, y in pts]
            if wall_x_clip is not None:
                wall_pts.extend(_clip_polyline_x(local, wall_x_clip[0], wall_x_clip[1]))
            else:
                wall_pts.append(local)
    return wall_pts


def _drop_tread_clusters_local(pts_list, cell=1.5, min_n=6, max_len=2.0):
    """**短线密集簇 = 踏步线/装饰线组**（本地米坐标版，见 extract_floor 的调用点）。

    判据：长度 < max_len 的线按 cell 网格分箱，某箱 >= min_n 条 => 整箱剔除。
    双线墙每堵仅 2 条平行线、单条长墙 1 条，达不到 min_n，不误删。
    """
    import collections as _c
    import math as _m
    if len(pts_list) < min_n:
        return pts_list
    grid = _c.defaultdict(list)
    for i, pts in enumerate(pts_list):
        if len(pts) < 2:
            continue
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        L = _m.hypot(x1 - x0, y1 - y0)
        if L < 1e-6 or L >= max_len:
            continue
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        grid[(int(_m.floor(mx / cell)), int(_m.floor(my / cell)))].append(i)
    drop = set()
    for _k, v in grid.items():
        if len(v) >= min_n:
            drop.update(v)
    if not drop:
        return pts_list
    return [pts for i, pts in enumerate(pts_list) if i not in drop]

def expand_shared_sheets(p, walls, doors, stairs, columns):
    """按 profile.sheet_floors 把「一张图描述多层」的图元**复制**进目标图带。

    在**原始 CAD 几何**这一层做，而不是去改 floor_of：全仓有二十多处按楼层筛图元（墙 / 门 /
    楼梯 / 柱 / 房间 / 渲染 / 审计），逐个改是大面积风险；在这里复制一份之后，下游所有
    floor_of/to_local 调用点、轮廓推导、门洞盒、楼梯井、GLB 搭建**一行都不用动**。
    sheet_floors 为 None 时原样返回，其余 48 栋逐字节不变。

    返回 (walls, doors, stairs, columns)，全是新列表，不改入参。
    """
    if not p.sheet_floors:
        return walls, doors, stairs, columns

    def _centroid(pts):
        return (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))

    def _expand_pts(items):
        """按「质心落在哪个图带」分组，再把各源带复制到它的目标带。"""
        out = list(items)
        by_sheet = {}
        for pts in items:
            by_sheet.setdefault(floor_of(p, *_centroid(pts)), []).append(pts)
        for src, targets in p.sheet_floors.items():
            for dst in targets:
                dx, dy = sheet_shift(p, src, dst)
                for pts in by_sheet.get(src, ()):
                    out.append([(x + dx, y + dy) for x, y in pts])
        return out

    def _expand_cols(items):
        out = list(items)
        by_sheet = {}
        for c in items:
            by_sheet.setdefault(floor_of(p, (c[0] + c[2]) / 2.0, (c[1] + c[3]) / 2.0), []).append(c)
        for src, targets in p.sheet_floors.items():
            for dst in targets:
                dx, dy = sheet_shift(p, src, dst)
                for c in by_sheet.get(src, ()):
                    out.append((c[0] + dx, c[1] + dy, c[2] + dx, c[3] + dy) + tuple(c[4:]))
        return out

    return (_expand_pts(walls), _expand_pts(doors), _expand_pts(stairs),
            _expand_cols(columns))


def unify_floor_set(p, floors):
    """返回要统一 footprint 的楼层集合（空集 = 不统一）。

    outline_unify_floors（子集，如阶梯楼裙楼 F0-F5）优先于 outline_unify=True（全楼）。
    塔楼/过渡层不在子集里，各自独立推导轮廓，不会被裙楼基准覆盖。
    """
    if p.outline_unify_floors is not None:
        return {F for F in floors if F in p.outline_unify_floors}
    if getattr(p, "outline_unify", False):
        return set(floors)
    return set()


UNIFY_REF_AREA_GUARD = 0.70


def _outside_cost(cands, T):
    """统一集合各层墙落在轮廓 T 之外的面积占比之和（越小 = 这层轮廓越能盖住大家）。"""
    tot = 0.0
    for _F, _o, geoms in cands:
        a = out = 0.0
        for g in geoms:
            if g is None or g.is_empty or g.area <= 1e-9:
                continue
            a += g.area
            out += g.area - g.intersection(T).area
        tot += (out / a) if a > 0 else 1.0
    return tot


def reference_outline_for(p, walls, floors):
    """outline_unify：多翼/阶梯楼统一 footprint 的「基准轮廓」。

    候选 = 统一集合里轮廓面积 ≥ 面积最大者 70% 的层（排除碎片化塌成的怪轮廓），在其中
    挑「各层墙落在轮廓外的比例之和最小」的一层。返回 (基准层号, 该层轮廓)。

    为什么不是「面积最大」：面积只是「墙最完整」的**代理**指标，面积接近时会抛硬币。
    c006 加弧墙带后 F0=5699.3㎡ 险胜 F2=5694.4㎡（差 0.09%），但两层形状对称差 1120㎡
    （边界沿线均值摆动 1.3m，是 outline_close_r 闭运算的噪声，非真实建筑差异）——基准层
    从 F2 翻成 F0，F2~F5「轮廓外墙体」从 0.5% 涨到 10%。换成直接最小化真正要保的不变量后，
    同一批数据 c006 总越界 42.0%→16.3%，c072/c073 各降 0.5%，其余 17 栋基准层与数值不变。

    轮廓已是本地米坐标（各层 to_local 都居中到本地原点），跨层复用无需平移。
    供 recognize.py（渲染）与 extract_rooms_generic.py（房间提取）共用，防止两路漂移
    （此前房间提取直接调 derive_walls_and_outline，低层碎片化 → 轮廓塌成小片 → 房间全丢）。
    统一范围由 unify_floor_set 决定（子集优先于全楼），调用方据此只对子集层应用 override。
    """
    subset = unify_floor_set(p, floors)
    if not subset:
        return None, None
    cands = []
    for F in sorted(subset):
        tr = (p.transition or {}).get(F)
        wall_x = tr.get("wall_x") if tr else None
        o, geoms, _ = derive_walls_and_outline(wall_pts_for_floor(F, walls, p, wall_x), p)
        if o is None or o.is_empty:
            continue
        cands.append((F, o, [g for g in geoms if g is not None and not g.is_empty]))
    if not cands:
        return None, None
    max_area = max(o.area for _F, o, _g in cands)
    pool = [c for c in cands if c[1].area >= UNIFY_REF_AREA_GUARD * max_area] or cands
    best = min(pool, key=lambda c: _outside_cost(cands, c[1]))
    return best[0], best[1]


def outline_for_floor(p, ref_F, ref_outline, F):
    """统一 footprint：直接复用基准轮廓，不平移。

    基准轮廓由 wall_pts_for_floor(ref_F) 算出，已是 ref_F 的本地坐标——to_local 把每层
    都居中到该层 floor_plans (cx, cy) 上，即本地原点 = 该层中心。目标层 F 的 to_local 同样
    居中到 F 的本地原点，故「同一 footprint」在两层本地坐标里都落在原点附近，直接复用即可，
    无需按 cy 差平移。曾按 (cy[ref]-cy[F])/1000 平移——那是在「同一点在两个不同本地系」间
    换坐标，而这里要的是「同形状落到每层各自中心」，两码事，平移会把裙楼轮廓甩出 -540m。
    前提：floor_plans cy 必须是几何中心（墙质心会因中央区墙多少上下漂 ~3m，见 profile 注释）。
    ref_outline=None 返回 None。
    """
    return ref_outline


# ── 电梯井「符号族闸门」（2026-09-16）────────────────────────────────────────────
# 井道是少数几个独立核心筒，物理上**不可能沿外墙成串重复**。全库 49 栋只读复算实测：
#   真值楼 20 栋（c006=3 / c009=1 / c022=2 / c027=1 / c030~c033=1 / c056=1 / c057=2 /
#   c061~c065=1 / c079=2 / c080,c083~c086=3 / c104=1）：单层 1~6 台，同尺寸族最大 = 2。
#   误检楼 2 栋：c046 = 82 台（族 1.08×2.76 有 24 个）、c103 = 138 台（族 1.20×3.00 有 128 个）。
#   两者都是外墙上 1.08 / 1.20m 深的**凹槽带被短墙逐段封口**形成的格子，
#   尺寸窗 [1.0,2.0]×[1.5,3.0] 与真井（1.20×1.95 / 1.10×2.10 / 1.30×2.40）**完全重叠**，
#   所以尺寸阈值判不掉；能区分的是「成族重复」这一符号特征。
#   另实测「贴外皮」也不能当硬闸门：c046 是 0.00~0.178m，但 c027 / c030~c033 的真井就是 0.20m，
#   只差 22mm；「井壁厚度」同样重叠（c027 真井 [0.10,0.10,0.20,0.21] vs c046 [0.12,0.12,0.24,0.24]）。
# 放行只能走 profile 具名口子（与 transition.wall_x / outdoor_steps 同一套哲学）：
#   profile["elevator_well_gate"] = false            → 关掉闸门
#   profile["elevator_well_gate"] = {"max_per_floor": n, "family_max": m}
WELL_MAX_PER_FLOOR = 8     # 实测真值上限 6（c080/c083~c086=3、c006=3），留一档余量
WELL_FAMILY_MAX = 2        # 实测真值楼「同尺寸族」最大 = 2
WELL_SIZE_BIN = 0.05       # m，(短边,长边) 分箱粒度


def _well_size_families(out):
    """按 (短边, 长边) 以 WELL_SIZE_BIN 分箱，返回 {分箱键: 台数}。"""
    fam = {}
    for s in out:
        key = (round(s["w"] / WELL_SIZE_BIN), round(s["d"] / WELL_SIZE_BIN))
        fam[key] = fam.get(key, 0) + 1
    return fam


def _well_symbol_family_gate(out, p, src):
    """候选井的「符号族闸门」：成族重复 ⇒ 判为图样符号 → 返回 []（并打印告警）。

    只影响「电梯」这一个构件：楼层 JSON 里不再写这些井，GLB 也就不再画井口/井壁。
    真井（20 栋、族 ≤2）走不到这条分支，逐字节不变。
    """
    if not out:
        return out
    cfg = getattr(p, "elevator_well_gate", None)
    if cfg is False:
        return out
    if isinstance(cfg, dict):
        max_n = int(cfg.get("max_per_floor", WELL_MAX_PER_FLOOR))
        max_fam = int(cfg.get("family_max", WELL_FAMILY_MAX))
    else:
        max_n, max_fam = WELL_MAX_PER_FLOOR, WELL_FAMILY_MAX
    fam = _well_size_families(out)
    top = max(fam.values())
    if len(out) <= max_n and top <= max_fam:
        return out
    k, n = max(fam.items(), key=lambda kv: kv[1])
    xs = [s["x"] for s in out]
    ys = [s["y"] for s in out]
    print(u"    [%s] 疑似符号族（%s）：%d 台 / 同尺寸族最大 %d 台 (%.2f×%.2f)，"
          u"bbox x[%.1f,%.1f] y[%.1f,%.1f] → 全部不收（要放行见 profile.elevator_well_gate）"
          % (p.name, src, len(out), n, k[0] * WELL_SIZE_BIN, k[1] * WELL_SIZE_BIN,
             min(xs), max(xs), min(ys), max(ys)))
    return []


def detect_elevator_shafts(wall_geoms, p, legend=None):
    """电梯井检测：**图例井优先，无图例才退回墙洞井**（规则优先于几何）。

    ① 图例井（`legend`，`elevator.wells_from_legend` 配对交叉对角线得来）：**主判据**。
       GB/T 50104 规定电梯井画「井道矩形 + 一对交叉对角线」——这是**规则**，不设尺寸阈值。
       c006 实测 33 部 = 11 层 × 3 部，逐层位置逐位相同，且与图例井洞完全重合。
    ② 墙洞井：墙 union 里的小矩形孔洞（短边 1.0~2.0m、长边 1.5~3.0m、长宽比 ≥1.3）。
       **只在 ① 为空时启用**（该楼不画 X 图例 / 简画）。这一路是**几何**判据，c006 实测
       它会误收核心筒楼梯井（F6 报 `(-22.04,8.55) 1.59×3.00`，紧挨真楼梯井 `(-21.13,8.19)`）
       —— 所以**不能与 ① 并集**：有图例时它多报，就是假阳性。

    ★ 旧版只有 ② 且**没有图例**，在 c006 上一条真井都收不到：X 对角线被当墙 buffer 成
    实心块把井填死（那条路现由调用方在 `derive_walls_and_outline` 前摘线打通，见
    `extract_floor`），它便只看得见闭合空腔，于是把 1 间卫生间当井收下。
    ★ ① 非空时若 ② 在别处另有报，只**打印**不交付——留给人工判读，不污染数据。

    返回 [{x, y, x0, y0, x1, y1, w, d}]（本地米：x/y=井心，w=短边，d=长边）。
    越界过滤 `|x|>100 或 |y|>100` 与 recognize.py 对**柱**的同源同式：图纸上别处的平面
    （c006 F10 混进了底部 D1 地下室带，井在 y=142）会被 `floor_of` 算进本层，不是本层构件。
    """
    holes = _wall_hole_shafts(wall_geoms)
    if legend:
        out = [{
            "x": round(w["cx"], 3), "y": round(w["cy"], 3),
            "x0": round(w["x0"], 3), "y0": round(w["y0"], 3),
            "x1": round(w["x1"], 3), "y1": round(w["y1"], 3),
            "w": round(w["w"], 3), "d": round(w["d"], 3),
        } for w in legend]
        extra = [h for h in holes
                 if not any(math.hypot(h["x"] - w["x"], h["y"] - w["y"]) < 0.5 for w in out)]
        if extra:
            print(u"    [%s] 图例未覆盖的墙孔洞 %d 处（仅打印，不并入电梯）：%s"
                  % (p.name, len(extra),
                     u" ".join(u"(%.1f,%.1f)%.2fx%.2f" % (e["x"], e["y"], e["w"], e["d"])
                               for e in extra)))
        out = _well_symbol_family_gate(out, p, u"图例X配对")
    else:
        out = _well_symbol_family_gate(holes, p, u"墙孔洞")
    return [s for s in out if abs(s["x"]) <= 100.0 and abs(s["y"]) <= 100.0]
    return [s for s in out if abs(s["x"]) <= 100.0 and abs(s["y"]) <= 100.0]


def _wall_hole_shafts(wall_geoms):
    """墙 union 里的「电梯井尺寸」矩形孔洞。纯几何兜底，见 `detect_elevator_shafts`。"""
    if not wall_geoms:
        return []
    region = unary_union(wall_geoms)
    polys = [region] if region.geom_type == "Polygon" else list(region.geoms)
    out = []
    for po in polys:
        for h in po.interiors:
            hp = Polygon(h)
            minx, miny, maxx, maxy = hp.bounds
            sw, sd = min(maxx - minx, maxy - miny), max(maxx - minx, maxy - miny)
            if 1.0 <= sw <= 2.0 and 1.5 <= sd <= 3.0 and sd / sw >= 1.3:
                out.append({
                    "x": round(hp.centroid.x, 3), "y": round(hp.centroid.y, 3),
                    "x0": round(minx, 3), "y0": round(miny, 3),
                    "x1": round(maxx, 3), "y1": round(maxy, 3),
                    "w": round(sw, 3), "d": round(sd, 3),
                })
    return out


# —— 门洞盒（两条门判据路径共用）——————————————————————————————————————
DOOR_SYMBOL_FACE_TOL = 0.25   # door_by_points：门符号 bbox 到轮廓 < 此值 → 外门
DOOR_CENTER_FACE_MARGIN = 0.20  # detect_doors：门心到轮廓 < 外墙厚 + 此值 → 外门


def _door_boxes(door_candidates, outline, p, S):
    """给每扇门算「门洞盒」d["box"]，并回写 bx0/by0/bx1/by1（渲染层据此补门头过梁）。

    外门判定两条路径分开：
      - door_by_points（理化楼）：门符号 bbox 到轮廓 < DOOR_SYMBOL_FACE_TOL。
        bbox 的「墙侧」边 = 门开启线，贴在墙中线上（距轮廓 ≈ 半墙厚 0.12~0.15m）；
        内墙门 bbox 距轮廓 > 0.4m。旧「质心在 outer_band(0.35) 内」被摆动弧坑了——
        弧把质心沿法向内推 ~0.22m，南立面 5 扇门质心距轮廓 0.36~0.37 > 0.35 被误判
        inner，门洞没挖进外墙、门框悬空。
      - detect_doors（LWPOLYLINE 楼）：无 bbox，用门心距轮廓 < 外墙厚 + 余量。
        c019 实测外门 0.13~0.40m、内门 ≥1.5m，阈值 0.44 正落在空档里，不会误伤内门。

    盒中心：外门沿外法向外移 (dist - depth/2)，使盒外缘对齐外轮廓、向内挖满 depth。
    门扇贴外墙，摆动弧使门质心内移 ~0.3m，若盒仍以质心为中心会只切到合成环带的内半，
    留外墙皮残片封死门洞。内门以门心居中即可。

    盒深 = max(外墙厚, 内墙厚) + 0.05：> 墙厚才把墙带切断成真实门洞（门 = gap），
    而非只在墙皮留个凹。渲染层再用 bx0..by1 把门顶~墙顶那段 gap 填回成门头过梁。
    """
    outer_wt = getattr(p, "outer_wall_t", S["outer_wall_t"])
    depth = max(outer_wt, S["inner_wall_t"]) + 0.05
    shell = OUT.outline_shell(outline)          # 多块楼层没有单数 .exterior
    for d in door_candidates:
        c = Point(d["x"], d["y"])
        if "bx0" in d:
            d["outer"] = box(d["bx0"], d["by0"], d["bx1"], d["by1"]).distance(shell) < DOOR_SYMBOL_FACE_TOL
        else:
            d["outer"] = c.distance(shell) < outer_wt + DOOR_CENTER_FACE_MARGIN
        half = d["w"] / 2
        cx, cy = d["x"], d["y"]
        # `onwall`（门弧门）= 门心已在墙中线上，**不吸附**：吸附是给质心口径的门补的，
        # 对门弧门只会把盒沿墙滑走（见 floor.py 门弧分支里的实测说明）。
        if d["outer"] and not d.get("onwall"):
            facade = nearest_points(outline.boundary, c)[0]
            vx, vy = facade.x - c.x, facade.y - c.y
            dist = (vx * vx + vy * vy) ** 0.5
            if dist > 1e-6:
                k = (dist - depth / 2) / dist
                cx, cy = c.x + vx * k, c.y + vy * k
        if d["horiz"]:   # 墙水平（门扇横跨 X）→ 盒宽 X、深 Y
            d["box"] = box(cx - half, cy - depth / 2, cx + half, cy + depth / 2)
        else:            # 墙竖直（门扇横跨 Y）→ 盒宽 Y、深 X
            d["box"] = box(cx - depth / 2, cy - half, cx + depth / 2, cy + half)
        d["bx0"], d["by0"], d["bx1"], d["by1"] = d["box"].bounds


def extract_floor(F, walls, doors, stairs, columns_local, p, S, is_top,
                  slab_outline=None, wall_x=None, wall_x_clip=None, outline_override=None,
                  keep_near_stairs_m=None):
    wall_pts = wall_pts_for_floor(F, walls, p, wall_x, wall_x_clip,
                                  keep_near_stairs_m=keep_near_stairs_m)

    # 短线密集簇（斜向楼梯踏步线画在墙体图层上）**不建墙** —— 2026-09-14 c006 实测：
    # 八角厅四角的斜向楼梯踏步线被当墙收下，F0-F3 各有 17~25 块墙偏离图纸墙 0.5~2.7m。
    # 注意**只**在这里剔：detect_stairwells 读的是原始 `walls`（本函数下方），
    # 若在 classify_line 里剔，楼梯井会被一起剔没（实测井 8 -> 4）。
    if getattr(p, "tread_cluster_filter", False):
        _n0 = len(wall_pts)
        wall_pts = _drop_tread_clusters_local(wall_pts, cell=1.5, min_n=6, max_len=2.0)
        if _n0 != len(wall_pts):
            print("    [%s F%d] 短线密集簇（踏步/装饰线）不建墙：%d -> %d"
                  % (p.name, F, _n0, len(wall_pts)))
    # 门符号（门扇线 + 门垛的**闭合环**，与墙同图层）不是墙：它会被 buffer/双线配对成一块
    # ~0.9~1.5m × 0.10~0.24m 的假墙，正盖在门洞位置上 —— 用户报的「门有的夹在墙里看不到」
    # 根因（c019 首层 31 块）。这里在建墙前摘掉；符号本身仍留给 detect_doors 推门（判门只
    # 看折线形状，与墙无关），门窗判据不受影响。
    door_sym_pts = [pts for pts in wall_pts if is_door_symbol_pts(pts)]
    if door_sym_pts:
        wall_pts = [pts for pts in wall_pts if not is_door_symbol_pts(pts)]

    # 电梯井**图例**（GB/T 50104：井道矩形 + 一对交叉对角线）。X 对角线画在**墙体图层**上，
    # 不摘掉就会和墙一起被 buffer 成一块 ~2.8×3.6m 的实心假墙，**把井自己填死** —— c006
    # 实测原判据（找墙 union 里的矩形洞）因此一条真井都收不到，反收了 1 间卫生间（那间才是
    # 真洞）。所以这里**先配对、再剔除**：同一份判据一次产出井位与要剔的线（见 elevator.py）。
    # ★ 这是**具名口子**不是放宽判据：只剔「成对交叉」的斜线，单条斜墙一律保留
    #   （全库 20 栋有真斜墙，见记忆 a-rootcause-curve-rollout）。
    elev_legend, elev_used = EV.wells_from_legend(wall_pts)
    if elev_used:
        wall_pts = [pts for i, pts in enumerate(wall_pts) if i not in elev_used]

    # 房间（rooms.json 已按 floor 存本地坐标边界）——提前载入：line 约定用它把楼板轮廓
    # 补齐到覆盖所有房间（半岛房间门洞缺口 > close_r 会漏出）。
    with open(p.rooms, encoding="utf-8") as f:
        rooms_data = json.load(f)
    rooms_polys = []
    for r in rooms_data:
        if r.get("floor") != F:
            continue
        b = r["boundary"]
        if len(b) < 3:
            continue
        rp = Polygon(b)
        if not rp.is_valid:
            rp = rp.buffer(0)
        if not rp.is_empty:
            rooms_polys.append(rp)

    # 统一墙几何 → union → 楼板轮廓（无轴对齐/双线配对假设，斜墙/单线墙/双线墙全兼容）
    derived_outline, wall_geoms, wall_ts = derive_walls_and_outline(wall_pts, p, is_top=is_top)
    # 多翼/阶梯楼统一 footprint（recognize.outline_unify）：outline_override 是全楼复用
    # 基准轮廓。墙 union 碎片化时逐层 max(area) 会塌成单翼小片；用覆盖轮廓替换 outline，
    # 但 wall_geoms 仍按本层墙几何算（内墙判定照常），外墙环带/窗/房间过滤/slab 全改用它。
    outline = outline_override if outline_override is not None else derived_outline
    if outline.is_empty:
        return None
    # **室外台阶**（profile.outdoor_steps，逐层给出本地米矩形 [x0,y0,x1,y1]）：不属于楼板，
    # 也不建墙。判例（2026-09-15 用户）：「室外的就是室外台阶」—— c006 F0 东西两侧各一处
    # 室外大台阶（9.3m 深平台 + 7 级 0.35m 踏步，外沿 x=±59.95 只是一条边线、没有第二皮）。
    # 为什么写成 profile 具名口子而不是自动判据：自动判据（≥3 条等距平行线 + 两端围合）
    # 在 c006 会同时命中**室内楼梯间与中庭大台阶**（实测每层 2~6 处），把室内楼板挖掉 ——
    # 宁可具名，不可误伤（与 transition.wall_x 同一套做法）。
    _steps = (getattr(p, "outdoor_steps", None) or {}).get(F)
    if _steps:
        cut = unary_union([box(float(a), float(b), float(c), float(d))
                           for a, b, c, d in _steps])
        _n_wall = len(wall_geoms)
        if wall_ts is not None:
            _keep = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                     if not cut.contains(g.centroid)]
            wall_geoms = [g for g, _ in _keep]
            wall_ts = [t for _, t in _keep]
        print("    [%s F%d] 室外台阶 %d 处不建模：墙 %d→%d 块"
              % (p.name, F, len(_steps), _n_wall, len(wall_geoms)))
    # 并排多栋副本（图纸把同层画两遍，如公寓首层左右各一栋，间距 341m）：derive 的
    # max(area) 只让 outline 留一栋，但 wall_geoms 仍含另一栋的墙（质心在数百米外），
    # 会被内墙判据（质心距轮廓 >0.225m）误收进本层 → GLB bbox 被撑成两栋。只保留
    # 质心在 outline 内（或贴边 <1m）的墙，弃掉另一栋。单楼/既有楼质心距 outline 均 <1m，不受影响。
    if wall_ts is not None:
        keep = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                if g.centroid.distance(outline) <= 1.0]
        wall_geoms = [g for g, _ in keep]
        wall_ts = [t for _, t in keep]
    else:
        wall_geoms = [g for g in wall_geoms if g.centroid.distance(outline) <= 1.0]
    # 同源过滤另一栋副本的墙点：门（detect_doors 从 wall_pts 推）与楼梯井也源自墙，
    # 首层双副本时若只过滤 wall_geoms，门/井仍会画到另一栋 → GLB bbox 仍被撑成两栋。
    def _near(pts):
        return Point(sum(q[0] for q in pts) / len(pts),
                     sum(q[1] for q in pts) / len(pts)).distance(outline) <= 1.0

    wall_pts = [pts for pts in wall_pts if _near(pts)]
    door_sym_pts = [pts for pts in door_sym_pts if _near(pts)]
    # ★★ 2026-09-15 **停用「轮廓 ∪ 房间边界 → 再填实」**（用户判据：「楼板应该由外沿线封闭拉出」）：
    #   这段是当时为了补半岛房间（门洞比 close_r 大时墙 union 漏出）加的，代价是
    #   `blocks_to_outline` 对每块**再把外环填实一遍** —— 两面墙交接的凹角因此鼓出一个三角
    #   （实测 c006 F1/F4 各层两块 17.6/15.8㎡，`x[29.0,37.2] y[−35.2,−27.3]` 及镜像，
    #   图纸外沿线上没有这个三角），而且它会把上层来的正确轮廓冲回墙法
    #   （识别层 F1 5845.9 → 交付层 5901.4；F0 更惨：正确轮廓 6452 被冲成 3786，东半栋丢了）。
    #   现在轮廓的唯一来源 = `derive_walls_and_outline`（c006 已改成「外沿折线各自闭合再并」），
    #   这里不再动它。房间是否落在轮廓内由下游 `outline.contains(...)` 自己判。
    _ = rooms_polys  # 保留变量（房间过滤仍在用），只是不再拿它改轮廓
    # ★ 屋面补块（profile.roof_rooms = {层: [房号]}）：**下层是该房间、本层图上没有楼板**的地方要封顶。
    #   判例 c006 八角厅：1~4 层是房间（多媒体教室×3 + 报告厅），5 层（F4）图上什么都没有 ——
    #   它就是八角厅的屋面（图纸面积表也证实：4 层 5880.48 → 5 层 5350.10，差的 530.4㎡ 正是八角厅
    #   那一块）。外沿轮廓法只认外墙外皮，这块钱不会自己出现 ⇒ 按房号把它的面并进轮廓。
    #   并进来之后 GLB/SU 的 `build_slab` 会按「上面有没有楼层」自动切成**屋面色**（F5 不含这块）。
    _roofnums = (getattr(p, "roof_rooms", None) or {}).get(F) or \
        (getattr(p, "roof_rooms", None) or {}).get(str(F)) or []
    for _rn in _roofnums:
        for _r in rooms_data:
            if str(_r.get("number")) != str(_rn):
                continue
            _b = _r["boundary"]
            if len(_b) < 3:
                continue
            _rp = Polygon(_b)
            if not _rp.is_valid:
                _rp = _rp.buffer(0)
            if _rp.is_empty:
                continue
            _n0 = outline.area
            outline = unary_union([outline, _rp]).buffer(0)
            print("    [%s F%d] 屋面补块（封顶）%s：+%.1f㎡"
                  % (p.name, F, _rn, outline.area - _n0))
    # 过渡层楼板轮廓复用源楼层（全宽裙楼屋面），墙体仍按塔楼 outline 分类。
    # 但复用轮廓只有裙楼足迹：塔楼若压在裙楼轮廓的凹口/天井上方，塔墙就悬在楼板外
    # （c006 层6 实测 38.6% 塔墙面积露空）。楼板 = 裙楼足迹 ∪ 本层自身足迹，只增不减。
    if slab_outline is not None:
        merged = unary_union([slab_outline, outline]).buffer(0)
        blocks = OUT.blocks_of(merged)      # 楼板 = 裙楼足迹 ∪ 本层足迹，两块都留
        slab_poly = OUT.blocks_to_outline(blocks) if blocks else outline
    else:
        slab_poly = outline

    ol_shell = OUT.outline_shell(outline)   # 多块楼层没有单数 .exterior，统一走外壳线
    outer_band = ol_shell.buffer(0.35, cap_style=2, join_style=2)

    # 门墙侧判定用「离最近墙更近」，不用「离轮廓更近」：内门摆动弧若指向较近立面，
    # 弧端 bbox 边会误判成墙侧（门面板浮离墙 ~1m）。墙 union 里门洞尚未挖，墙侧边点落在墙内（距离 0）。
    walls_union_for_door = unary_union(wall_geoms).buffer(0) if wall_geoms else None

    # 门：两类来源——
    #   LINE 约定（c006）：门=INSERT 块，classify_line 已把门编码成点列塞进 `doors` 参数
    #     （CAD 毫米）。这里 to_local 转本地米 + floor_of 过滤 + 点列跨度定朝向 + profile 定门宽。
    #   LWPOLYLINE 约定：门=墙折线几何符号，用 detect_doors 几何判定；若图纸另用**门弧**画法，
    #     classify 会把弧还原成三点塞进 `doors`，两条证据并集（见下）。
    #   各楼门符号画法不一（点数 3~17、有的带弧有的不带），几何判据只看「不闭合 + 门扇线跨度」。
    # 非 door_by_points 的楼里 `doors` 只装 classify 从墙层 ARC 还原的「门弧三点」——
    # 它与「墙折线几何符号」是**两套互补证据**（同一栋楼两种画法混用），所以下面 detect_doors
    # 照跑不误，结果是并集；duplicate 由 openings 的宿主注册去重。
    arc_doors = bool(doors) and not getattr(p, "door_by_points", False)
    door_candidates = []
    if doors:
        for pts in doors:
            cx = sum(q[0] for q in pts) / len(pts)
            cy = sum(q[1] for q in pts) / len(pts)
            if floor_of(p, cx, cy) != F:
                continue
            L = [to_local(p, x, y, F) for x, y in pts]
            # 屋顶设备副块（电梯机房/水箱门）画在塔楼 X 列、Y 落在裙楼楼层区间（c006 第11层），
            # localY 达 ~136m → 丢弃，否则 GLB 长出一根悬空门带（同 localize_columns 的 >100m 过滤）。
            if abs(sum(q[0] for q in L) / len(L)) > 100.0 or abs(sum(q[1] for q in L) / len(L)) > 100.0:
                continue
            npt = len(L)
            xs = [q[0] for q in L]
            ys = [q[1] for q in L]
            if not getattr(p, "door_by_points", False) and _is_arc_door_triple(L):
                # 门弧三点 [贴墙端, 弧心, 扇尖]：门宽 = 扇线长(半径)，门心 = **贴墙端与弧心的
                # 中点**（正落在墙中线上）。不能用三点质心 —— 质心沿墙法向内移 r/3，
                # 内门盒(深 0.35m)于是切不到墙，门洞挖不穿、门夹在墙里。
                (xw, yw), (xh, yh), _tip = L
                door_candidates.append({
                    "x": round((xw + xh) / 2, 3), "y": round((yw + yh) / 2, 3),
                    "w": round(math.hypot(xw - xh, yw - yh), 3),
                    "horiz": abs(xw - xh) >= abs(yw - yh),
                    # 门弧还原出的门心**本来就落在墙中线上**（铰点与门垛都在墙上，取中点即
                    # 墙中线）。而 `_door_boxes` 的「外门沿外法向外移」是给**质心口径**的门
                    # 补的：那类门心被摆动弧沿法向内推了 ~0.3m，盒居中只切到墙内半、留外墙
                    # 皮封死门洞。对门弧门，这个补偿必须**关掉** —— c009 F2 实测 4 扇外门被
                    # 吸附沿**墙方向**(与 nearest_points 连线是斜的)滑走 0.127~0.167m，盒只剩
                    # 63% 压在墙上，门洞切偏、门心仍被墙包住(buried_doors>0 = 用户报的
                    # 「门夹在墙里看不到」)。居中时盒内 100% 是墙(0.29×0.75=0.2175㎡)，一刀穿透。
                    "onwall": True,
                })
                continue
            if getattr(p, "door_by_points", False):
                # 理化楼：门宽按点数（16 点=单门 door_w_single、23 点=双门 door_w_double），
                # 朝向按短段法（门符号带摆动弧，bbox 方向会判错）。
                w = p.door_w_single if npt <= 16 else p.door_w_double
                horiz = _door_wall_horiz(L)
            else:
                horiz = (max(xs) - min(xs)) >= (max(ys) - min(ys))
                # 门宽从图读：classify_line 把 INSERT abs(xscale) 编进点列跨度（毫米→米）
                w = round((max(xs) - min(xs)) if horiz else (max(ys) - min(ys)), 3)
            bx0, by0 = min(xs), min(ys)
            bx1, by1 = max(xs), max(ys)
            if getattr(p, "door_by_points", False):
                # 门位置 = 门所在墙的中心线（门扇线），不是门符号质心/bbox 边。
                # 门符号 = 门扇线 + 门垛（外皮/内皮两条）+ 摆动弧（伸进房间 ~1.2m），
                # bbox 深度方向两条边是「外皮边（门垛南）」与「弧顶」，取离墙 union 更近的
                # 那条会定位到外皮边（距离 0）→ 门中心落到外皮而非墙中线，门洞盒往外偏
                # 半墙厚，只挖外墙外半、内半残留 0.065m 假过梁（「门洞没挖穿」根因）。
                # 门扇线 = 门符号里点数最多的水平/竖直线（众数，墙中线），用它定位门中心。
                if horiz:
                    wx = (bx0 + bx1) / 2
                    wy = _mode_axis(L, 1)
                else:
                    wy = (by0 + by1) / 2
                    wx = _mode_axis(L, 0)
                cx, cy = round(wx, 3), round(wy, 3)
            else:
                cx, cy = round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3)
            door_candidates.append({
                "x": cx, "y": cy,
                "w": w,
                "horiz": horiz,
                "bx0": round(bx0, 3), "by0": round(by0, 3),
                "bx1": round(bx1, 3), "by1": round(by1, 3),
            })
    if not doors or arc_doors:
        door_candidates += detect_doors(wall_pts + door_sym_pts, outline, p)

    # 门洞盒：外门挖外墙环带、内门挖内墙 union。两条门判据路径共用同一套盒（见 _door_boxes）。
    # 旧版整块被 door_by_points 关着，detect_doors 楼（c019 等 LWPOLYLINE 楼）从不挖洞——
    # 墙是连续的，门板被埋进实心墙里 = 用户报的「门有的夹在墙里看不到」。
    _door_boxes(door_candidates, outline, p, S)

    stairwells_json = detect_stairwells(F, walls, p)
    # 楼梯井同样过滤（首层双副本的另一栋井中心在参考轮廓外数百米）。
    # ⚠️ 参照物必须是 `slab_poly`（本层**楼板**足迹），不是 `outline`（本层**自身**足迹）：
    #    井是埋在本层楼板里的，而过渡层的这两个量不是一回事 —— c006 F6 因
    #    `transition.wall_x` 只裁塔楼列，`outline` = 925.1㎡ 的塔楼，而楼板 = 裙楼∪塔楼
    #    （= 交付的 outline 字段，5700.5㎡）。按 `outline` 过滤时，裙楼屋面那 6 口
    #    出屋面楼梯井（四角 + 左右中腰，离塔楼 10.1~43.1m）被整批丢掉，只剩塔楼 2 口：
    #    落盘 F6 楼梯井 8→2，裙楼屋面楼板不挖洞、6 部楼梯在屋面上被盖住
    #    —— 正是用户要的「屋顶要有楼梯间」消失。改用 `slab_poly` 后 8 口井心距离全 0.000m。
    #    非过渡层 slab_poly ≡ outline（:473-478），逐位不变；全库只有 c006 有 transition。
    #    距离容差 1.0m 未动 —— 修的是参照物，不是放宽判据。
    stairwells_json = [s for s in stairwells_json
                       if Point((s["x0"] + s["x1"]) / 2, (s["yBot"] + s["yTop"]) / 2).distance(slab_poly) <= 1.0]

    stair_steps = []
    for pts in stairs:
        if floor_of(p, pts[0][0], pts[0][1]) != F:
            continue
        L = [to_local(p, x, y, F) for x, y in pts]
        stair_steps.append((max(abs(q[0]) for q in L), min(q[1] for q in L)))
    stair_steps.sort(key=lambda s: -s[1])

    # 每层墙几何：合并为「外墙闭合环 + 内墙带（房间洞保留）」两片，消除数千段 2 点墙皮线
    # 碎片化（前端每段一个 mesh → 卡顿 + 窗布不满 + 墙角缺口）。
    #   外墙 = 轮廓边界内缩 outer_wall_t 的闭合环（始终闭合、贴合轮廓，供布窗与上色）；
    #   内墙 = 不贴外轮廓的真实墙段 union（房间洞保留，不填实房间内部）。
    outer_t = S["outer_wall_t"]
    wall_entities = []
    wid = 0

    if (getattr(p, "classifier", "lwpolyline") == "line"
            or not getattr(p, "door_by_points", False)):
        # ★ 统一方案（用户 2026-09-12：「建筑的做法全部用一个方案，没有特殊」）：
        # 外墙/内墙都用**图上配对出的实际墙矩形**，厚度读自双线间距（240/300/120…），按厚度
        # 分桶 union，每桶 thickness = 该桶真实墙厚，不冒充统一 0.30/0.24，也不用合成外环
        # （`outline.buffer(-outer_t)` 会无视图上真实外墙线、把墙厚统一成 0.30m —— 就是
        # 「你不能臆想的创造墙」的那一圈）。
        # 内墙减外墙总区域：T 字口处内墙端头探进外墙矩形，不减法就会两色各画一遍（重复建设）。
        def _emit_group(geoms, wtype, thickness, subtract=None):
            nonlocal wid
            if not geoms:
                return
            # 化简容差必须小于墙厚，否则 Douglas-Peucker 把**薄墙自身**当噪声抹掉：
            # 0.10 厚的单线墙（single_wall_t）对弦的偏差正好 = 0.10 = 旧硬编码容差，
            # 于是一条 15m×0.10 的实心墙被压成 25mm 的锯齿发丝（面积 0.75㎡→0.19㎡，
            # 外立面「破了」）。按本桶真实墙厚取 1/4，且不超过原来的 0.1。
            region = unary_union(geoms).simplify(min(0.1, thickness / 4.0)).buffer(0)   # 清洗自交
            if subtract is not None:
                region = region.difference(subtract).buffer(0)     # 内墙减去外墙区域，消除 T 字口重叠
            if region.is_empty:
                return
            for poly in ([region] if region.geom_type == "Polygon" else list(region.geoms)):
                for cp in _clean_emit(poly):
                    wall_entities.append({
                        "id": f"w{F}-{wid}", "type": wtype,
                        "thickness": round(thickness, 3),
                        "height": round(S["wall_h"], 3),
                        "poly": _dedupe(r2(cp.exterior.coords)),
                        "holes": [h for interior in cp.interiors
                                  if len(h := _dedupe(r2(interior.coords))) >= 4],
                    })
                    wid += 1

        def _emit_by_thickness(geoms_ts, wtype, subtract=None):
            buckets = {}
            for g, t in geoms_ts:
                buckets.setdefault(round(t, 2), []).append(g)
            for k in sorted(buckets):
                _emit_group(buckets[k], wtype, k, subtract)

        # ★ 外墙判定：质心距轮廓壳 <= outer_t + 0.25（2026-09-14 c006 实测）。
        #   原阈值 outer_t(0.30) 对**内凹角**太紧：外墙带质心离壳 ≈ 半墙厚(0.15)，但在中央翼
        #   与两翼交界那种内凹处，轮廓壳绕开、质心距离 >0.30 → 真外墙被刷成内墙色
        #   （实测每层 5~8 块，位置 (30.2,15.6)/(-30.3,15.6)/(17.4,-9.8) 一带）。
        #   T 形内墙的质心在房间中部、离壳远（>1m），放宽到 +0.25 不会把它误收成外墙。
        _outer_tol = outer_t + 0.25
        outer_geoms_ts = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                          if g.centroid.distance(ol_shell) <= _outer_tol]
        inner_geoms_ts = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                          if g.centroid.distance(ol_shell) > _outer_tol]
        outer_region_all = unary_union([g for g, _ in outer_geoms_ts]).buffer(0) if outer_geoms_ts else None
        _emit_by_thickness(outer_geoms_ts, "outer")
        _emit_by_thickness(inner_geoms_ts, "inner", subtract=outer_region_all)
    elif getattr(p, "door_by_points", False):
        # 理化楼：外墙在图上画成「两条 8 点周边折线」（单线，无厚度信息，合起来是完整楼板
        # 周长，buffer 0.15 → 0.30 厚带，质心=楼中心）+ 少量贴轮廓的双皮外墙矩形；内墙是
        # 双皮线（0.30 承重 / 0.24 隔墙）+ L/U 形 3/4 点单线墙。外墙/内墙只能靠「墙边界与
        # 楼板轮廓是否共享一条长边」分：外墙外边缘 = 轮廓边界（共享十几~上百米），内墙只在
        # 两端点接触轮廓（共享长 < 1m）。旧「几何最近距 ≤0.30」会把两端贴外墙、横贯全楼的
        # 0.30 承重内墙（最近距 0）误收进外墙；旧「质心距 ≤0.30」因外墙是 140m 周边折线
        # （质心=楼中心）把真外墙全漏成内墙。tol=0.10 经 diag 验证：外墙面积 91.8㎡ ≈
        # 理论 87.2㎡（周长×0.30），tol 放大到 0.20 会误收 0.10~0.20m 处的内墙。
        facade_bnd = outline.boundary.buffer(0.10)
        outer_geoms_ts = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                          if g.boundary.intersection(facade_bnd).length >= 1.0]
        inner_geoms_ts = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                          if g.boundary.intersection(facade_bnd).length < 1.0]
        # 门弧门(onwall)：门心**在墙中线上**，它的盒该挖的是「它所在的那面墙」，而外/内是按
        # 「贴不贴轮廓」分的 —— 两者会不一致（c009 F2 实测 4 扇：有门的墙被判成 inner、门却
        # 被判成 outer，盒只从外墙带里减 → 内墙没挖 → 门心仍被墙包住 = 用户报的「门夹在墙里」）。
        # 故 onwall 盒**两个区域都挖**：它居中在墙中线上，挖到哪面墙都是正确的门洞。
        onwall_boxes = [d["box"] for d in door_candidates if d.get("onwall")]
        outer_boxes = [d["box"] for d in door_candidates if d.get("outer")] + onwall_boxes
        inner_boxes = [d["box"] for d in door_candidates if not d.get("outer")] + onwall_boxes

        def _emit_real(geoms_ts, wtype, subtract=None, boxes=None):
            nonlocal wid
            if not geoms_ts:
                return
            buckets = {}
            for g, t in geoms_ts:
                buckets.setdefault(round(t, 2), []).append(g)
            for k in sorted(buckets):
                # 不 simplify：0.10m 薄墙（楼梯井/翼楼边）会被 simplify(0.1) 折叠成三角形
                # （丢顶点、面积减半）。buffer(0) 已能清自交，r2 取整 + _clean_emit 兜底顶点。
                region = unary_union(buckets[k]).buffer(0)
                if subtract is not None:
                    region = region.difference(subtract).buffer(0)
                if boxes:
                    region = region.difference(unary_union(boxes)).buffer(0)
                if region.is_empty:
                    continue
                for poly in ([region] if region.geom_type == "Polygon" else list(region.geoms)):
                    for cp in _clean_emit(poly):
                        wall_entities.append({
                            "id": f"w{F}-{wid}", "type": wtype,
                            "thickness": round(k, 3),
                            "height": round(S["wall_h"], 3),
                            "poly": _dedupe(r2(cp.exterior.coords)),
                            "holes": [h for interior in cp.interiors
                                      if len(h := _dedupe(r2(interior.coords))) >= 4],
                        })
                        wid += 1

        outer_region = unary_union([g for g, _ in outer_geoms_ts]).buffer(0) if outer_geoms_ts else None
        _emit_real(outer_geoms_ts, "outer", boxes=outer_boxes)
        _emit_real(inner_geoms_ts, "inner", subtract=outer_region, boxes=inner_boxes)
    else:
        # LWPOLYLINE 约定（其它楼原路径不变）：外墙 = 轮廓内缩 0.30m 的合成闭合环带（供布窗与上色），
        # 内墙 = 不贴外轮廓的真实墙段 union（房间洞保留，不填实房间内部）。
        outer_ring = outline.difference(outline.buffer(-outer_t, join_style=2))   # mitre 避免圆角顶点爆炸
        outer_ring = outer_ring.buffer(0)   # 清洗 union/simplify 产生的自交（否则 triangulate 出错/丢墙）
        # 门洞挖进外墙环带：外门盒把外墙带切断成真实门洞（门 = gap 不是 hole）
        # onwall（门弧门）盒同样要挖外墙带，理由见上面 line 分支里的实测说明。
        onwall_boxes = [d["box"] for d in door_candidates if d.get("onwall")]
        outer_boxes = [d["box"] for d in door_candidates if d.get("outer")] + onwall_boxes
        if outer_boxes:
            outer_ring = outer_ring.difference(unary_union(outer_boxes)).buffer(0)
        if not outer_ring.is_empty:
            for poly in ([outer_ring] if outer_ring.geom_type == "Polygon" else list(outer_ring.geoms)):
                for cp in _clean_emit(poly):
                    wall_entities.append({
                        "id": f"w{F}-{wid}",
                        "type": "outer",
                        "thickness": round(outer_t, 3),
                        "height": round(S["wall_h"], 3),
                        "poly": _dedupe(r2(cp.exterior.coords)),
                        "holes": [h for interior in cp.interiors
                                  if len(h := _dedupe(r2(interior.coords))) >= 4],
                    })
                    wid += 1
        # 内墙判定默认用「质心距轮廓」而非面积带：外墙贴轮廓（质心 ≈ wall_fallback 半墙厚处），
        # 内墙质心远离轮廓。旧面积带 0.35m 比外墙环带 0.30m 宽，会在 0.30~0.35m 造出
        # 「判为外墙却被丢弃、且超出环带覆盖」的死区（c027 F7 的 2 点墙 0 覆盖根因）。
        # 质心判据无死区；T 形内墙端头虽连外墙、质心仍在房间中部，不会被误判外墙。
        if getattr(p, "door_by_points", False):
            # 理化楼：外墙是「双皮线」，两皮各 buffer 0.15m 成两条 0.30m 带。内皮几何最近距
            # outline.exterior ≈ 0.09~0.24m，但质心距 0.38m+（长墙质心落在中点，非垂直距离），
            # 旧「质心距 > 0.225」会把内皮整条收进内墙 → 与合成外环 [0,0.30] 重叠，外墙内墙
            # 重复建设（标准：外墙=外立面可见的墙、内墙=其余，二者互不重叠）。改用「几何最近距
            # > outer_t」判内墙：外墙双皮（最近距 ≤ outer_t）整体排除，再减合成外环兜底，重叠归零。
            inner_geoms = [g for g in wall_geoms
                           if g.distance(ol_shell) > outer_t]
        else:
            inner_geoms = [g for g in wall_geoms
                           if g.centroid.distance(ol_shell) > outer_t * INNER_WALL_CENTROID_FACTOR]
        if inner_geoms:
            inner_region = unary_union(inner_geoms).simplify(0.1).buffer(0)   # 清洗自交
            if getattr(p, "door_by_points", False):
                # 内墙减外墙合成环：内墙止于外墙内侧面，消除与外墙的 T 形重叠（不重复建设）
                inner_region = inner_region.difference(outer_ring).buffer(0)
            # 门洞挖进内墙：内门盒把内墙带切断成真实门洞（门 = gap 不是 hole）
            # onwall（门弧门）盒同样要挖内墙带，理由见上面 line 分支里的实测说明。
            inner_boxes = ([d["box"] for d in door_candidates if not d.get("outer")]
                           + onwall_boxes)
            if inner_boxes:
                inner_region = inner_region.difference(unary_union(inner_boxes)).buffer(0)
            for poly in ([inner_region] if inner_region.geom_type == "Polygon" else list(inner_region.geoms)):
                for cp in _clean_emit(poly):
                    wall_entities.append({
                        "id": f"w{F}-{wid}",
                        "type": "inner",
                        "thickness": round(S["inner_wall_t"], 3),
                        "height": round(S["wall_h"], 3),
                        "poly": _dedupe(r2(cp.exterior.coords)),
                        "holes": [h for interior in cp.interiors
                                  if len(h := _dedupe(r2(interior.coords))) >= 4],
                    })
                    wid += 1

    # 外墙窗：沿合并后的外墙闭合环外立面布窗（合成数据，DXF 无窗；GLB 消费，
    # 前端 building.html 按同算法 facadeWindows 实时布窗，参数面板可调）。
    # synthetic 标记：这些窗不是 DXF 实线推导的，是 facade_windows 沿外墙直段等距生成的
    # 合成窗，GLB / 前端默认不渲染，用户可在参数面板显式打开。
    # ⚠️ 具名口子捞回的墙（＝wall_x 弃掉的那片裙楼屋面里、踏步盒 2.5m 内的墙）**不布窗**。
    #    它们是**出屋面楼梯间**（屋面构筑物，不是建筑立面），c006 图纸上是光板双线墙、
    #    没有任何窗符号 —— 布合成窗就是臆造（实测不挡：6 个楼梯间各长出 8~10 扇，F6 窗 34→78，
    #    还贴在 27m 折线墙的中线上）。塔楼**原有**的楼梯间立面窗不动（它们在 wall_x 区间内，
    #    不属于本口子），所以这条闸只作用于本口子自己的范围。
    fcx, fcy = frame_center(p, F)
    stair_band = stair_boxes_of(F, walls, p) if keep_near_stairs_m else None

    def _gate_recovered(wpoly):
        if stair_band is None or wall_x is None:
            return False
        c = wpoly.centroid
        if wall_x[0] <= c.x * 1000.0 + fcx <= wall_x[1]:
            return False
        return in_stair_enclosure(c, stair_band, keep_near_stairs_m)

    windows_json = []
    for w in wall_entities:
        if w["type"] != "outer":
            continue
        if _gate_recovered(Polygon(w["poly"])):
            continue
        for win in facade_windows(Polygon(w["poly"]), outline, S):
            win["id"] = f"win{F}-{len(windows_json)}"
            win["wallId"] = w["id"]
            win["synthetic"] = True
            windows_json.append(win)

    # 房间：剔除中心落在楼板轮廓外的（轮廓已补齐覆盖房间，正常全保留）
    rooms_json = []
    _bad_rooms = []                  # 修形也救不回来、被丢掉的房号（会打印）
    for r in rooms_data:
        if r.get("floor") != F:
            continue
        b = r["boundary"]
        if len(b) < 3:
            continue
        rp = Polygon(b)
        if not outline.contains(rp.centroid):
            continue
        # ★ 2026-09-16 **地下层房间不上地面层**（c017 6 间 / c022 1 间实测）：这批图纸把
        #   「地下1层（D1）」平面与地上各层画在同一张图上，房号带 `-D1-`；提取时按"质心落在
        #   本层轮廓内"过滤会把地下室房间混进首层 —— QA 的 I3 报「房间外溢楼板轮廓」
        #   （c022 F0 22-D1-01 外溢 95㎡/8%、c104 F4 同类 130㎡/21%）。本模型不建地下层
        #   （GLB 从 z=0 起），故直接剔除；要建地下层时另开一层。
        if re.search(r"-D\d", str(r.get("number") or "")):
            continue
        # ★ 交付前**修形**（2026-09-17）：`r2(b)` 把坐标压到 2 位小数，会把
        #   密集顶点（c104 这间 5473 点、c041 147 点）压成自交环 —— 下游 SU 规格
        #   做「房间 vs 地垫」包含判定时 GEOS 直接抛 TopologyException
        #   （实测 c041「41-01-05」、c104「104-C-02-02」）。这里以**落盘结果**为准
        #   验一次：不合法就 buffer(0) 自愈（多块取最大块），仍不合法就把小数位放宽
        #   到 3、4 位，都不行才丢这一间（丢的会打印，绝不静默）。
        poly_out = None
        for _prec in (2, 3, 4):
            try:
                _cand = [[round(x, _prec), round(y, _prec)] for x, y in b]
                _q = Polygon(_cand)
            except Exception:                                      # noqa: BLE001
                continue
            if _q.is_valid and _q.exterior.is_simple:
                poly_out = _cand
                break
            _fx = _q.buffer(0)
            if _fx.geom_type == "MultiPolygon":
                _fx = max(_fx.geoms, key=lambda z: z.area)
            if _fx.is_empty or _fx.geom_type != "Polygon":
                continue
            b = list(_fx.exterior.coords)
        if poly_out is None:
            _bad_rooms.append(r.get("number") or "?")
            continue
        rooms_json.append({
            "id": r.get("id"),
            "poly": poly_out,
            "purpose": r.get("purpose") or "",
            "number": r.get("number") or "",
        })

    # 结构柱按图来：图里画了哪层就哪层（columns_local 是 {floor: [柱]}，本层缺省为空）
    # ★ 2026-09-16 **按轮廓过滤柱**（c103 判例）：顶层退台时，图纸那样层图里往往把**整栋的柱**
    #   都画着（c103 F5 218 根与 F4 同数），而本层楼板只有 3572㎡（F4 是 6642㎡）⇒ 124 根柱
    #   落在板外 5~30m，QA 的 I1 报「悬空鳍」41 条 ERROR（ERROR=必改，全库 3 栋 FAIL 里有它）。
    #   口径与墙一致（extract_floor 上面那条：质心离轮廓 ≤1.0m 才算本层构件）—— 首层入口门廊柱
    #   一般只外溢 0.3~0.5m，不会被误杀。
    columns_json = [dict(c) for c in columns_local.get(F, [])
                    if Point(c["x"], c["y"]).distance(outline) <= 1.0]

    doors_json = []
    for d in door_candidates:
        # 门洞盒（_door_boxes）给两条门判据路径都回写了 bx0..by1，故两者都带门头过梁；
        # 保留下面的存在性守卫，兼容外部构造的、没走门洞盒的门 dict。
        entry = {
            "x": float(d["x"]), "y": float(d["y"]), "w": float(d["w"]),
            "h": float(S["door_h"]),
            "horiz": bool(d["horiz"]),
            "outer": bool(d.get("outer", outer_band.contains(Point(d["x"], d["y"])))),
        }
        if "bx0" in d:
            entry.update({
                "bx0": float(d["bx0"]), "by0": float(d["by0"]),
                "bx1": float(d["bx1"]), "by1": float(d["by1"]),
            })
        doors_json.append(entry)
    # 楼梯井道 `shaft` 不在这里算：它是**跨层**量（同一口井各层取并集，见
    # `stairs.attach_shafts_to_floors`），逐层算完就写会把并集切碎。
    # 单一所有者 = `recognize.recognize()` 在全部楼层就绪后调一次。

    # 宿主墙登记（BIM 的 hosted element）：门记「我开在哪面墙上」。
    # 没有这条，墙一重建洞就悬空；有了它，门禁就能量「洞口是否落在宿主墙上」。
    n_orphan_door = openings.register_hosts(doors_json, wall_entities, F)
    if n_orphan_door:
        print("    [%s F%d] 悬空门 %d 个（无宿主墙，已记 unresolved）" % (p.name, F, n_orphan_door))

    # 电梯井：图例井（X 对角线配对，上面已产）∪ 墙洞井。井道墙已在 wall_geoms 里（当内墙
    # 渲染），这里只补「楼板开洞」与「电梯门」所需的井道 bbox；门由 door_candidates 里落在
    # 井口的 $DorLib2D 承载，渲染层把贴井道的门当作电梯门。
    elevators_json = detect_elevator_shafts(wall_geoms, p, elev_legend)

    # 轮廓交付：单块 = `outline`（历史编码，QA 直读）；多块 = `outline` 写成「钥匙孔」
    # 单环（块间加窄桥，好让只认单环的 QA 看得见整层）+ `outline_parts` 精确分块。
    # 单块楼层不写 outline_parts → 产物与历史逐字节一致（键序也保持原位）。
    # 读一律走 `outline.floor_outline(fl)`（它优先取精确块，不碰窄桥）。
    # ⚠️ **室外台阶的楼板切除放在最后一步**：轮廓在 extract_floor 里经过「房间并集补齐」
    # （line 约定）与「过渡层 slab 并集」两道 union→blocks→填外环，提前切会被后一步的
    # 「填外环」把缺口重新填回来（c006 F0 实测：提前切东侧那块，切完 6215.8㎡，最终产物
    # 又是 6351.6㎡ —— 东西两侧只有一侧真正切掉）。所以切在交付前、所有 union 之后。
    if _steps:
        _cut = unary_union([box(float(a), float(b), float(c), float(d))
                            for a, b, c, d in _steps])
        _ba, _bb = slab_poly.area, outline.area
        slab_poly = slab_poly.difference(_cut)
        if not slab_poly.is_valid:
            slab_poly = slab_poly.buffer(0)
        outline = outline.difference(_cut)
        if not outline.is_valid:
            outline = outline.buffer(0)
        print("    [%s F%d] 室外台阶 %d 处不进楼板：slab %.1f→%.1f㎡（轮廓 %.1f→%.1f㎡）"
              % (p.name, F, len(_steps), _ba, slab_poly.area, _bb, outline.area))
    _of = OUT.outline_fields(slab_poly, norm=lambda cs: _dedupe(r2(cs)),
                             ctx="%s F%d" % (p.name, F))
    if _bad_rooms:
        print("    [%s F%d] ⚠ 房间边界自愈失败、已丢弃 %d 间：%s"
              % (p.name, F, len(_bad_rooms), " ".join(_bad_rooms[:6])))
    result = {
        "floor": F,
        "layer_height": float(S["floor_h"]),
        "outline": _of["outline"],
        "rooms": rooms_json,
        "walls": wall_entities,
        "windows": windows_json,
        "columns": columns_json,
        "doors": doors_json,
        "elevators": elevators_json,
        "stairs": [{"hw": float(round(hw, 3)), "nosing": float(round(nosing, 3))}
                   for hw, nosing in stair_steps],
        "stairwells": stairwells_json,
    }
    if _of["outline_parts"]:
        result["outline_parts"] = _of["outline_parts"]
    if is_top:
        # 中央主体屋面：屋面板 + 女儿墙（由 outline 外扩生成，含北边）
        result["roof"] = {
            "roofT": float(S["roof_t"]),
            "parapetH": float(S["parapet_h"]),
            "parapetT": float(S["parapet_t"]),
        }
    return result
