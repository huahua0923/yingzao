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
from shapely.geometry import Polygon, box, Point, LineString
from shapely.ops import nearest_points, unary_union

from .geometry import (
    derive_walls_and_outline, detect_doors, detect_stairwells, facade_windows, r2,
)
from .component_library import INNER_WALL_CENTROID_FACTOR, is_door_symbol_pts
from .profile import to_local, floor_of


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


def wall_pts_for_floor(F, walls, p, wall_x=None, wall_x_clip=None):
    """抽出一层的墙点列（本地米坐标）。用墙「质心 Y」判定楼层（旋转墙/阶梯楼比首点更稳）。

    wall_x：按质心 X 过滤（毫米，六教过渡层——裙楼屋面女儿墙是独立短墙，质心落塔楼区间外）。
    wall_x_clip：按 X 区间裁剪（米，理化楼顶层——翼楼女儿墙与塔楼外墙是同一条连续折线，
      只能裁剪不能按质心过滤）。
    """
    wall_pts = []
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        if abs(floor_of(p, cx, cy) - F) < 0.5:
            # 过渡层只取「建筑墙」X 区间（如六教第 7 层只留塔楼墙，弃裙楼屋面女儿墙）
            if wall_x is not None and not (wall_x[0] <= cx <= wall_x[1]):
                continue
            local = [to_local(p, x, y, F) for x, y in pts]
            if wall_x_clip is not None:
                wall_pts.extend(_clip_polyline_x(local, wall_x_clip[0], wall_x_clip[1]))
            else:
                wall_pts.append(local)
    return wall_pts


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


def detect_elevator_shafts(wall_geoms, p):
    """电梯井检测：墙 union 里的小矩形孔洞（短边 1.0~2.0m、长边 1.5~3.0m、长宽比 ≥1.3）。

    六教（c006）实测电梯井 = 1.23m×1.86m 的矩形洞，全 11 层同位置（竖井）。各层 to_local
    中心不同（裙楼/塔楼各自居中），故按「层内小矩形洞」检测，不跨层匹配。矩形长宽比
    （深/宽≥1.3）天然排除方形楼梯井（2.8×2.8）与管井（1.35×1.35），只留长条电梯井。
    返回 [{x, y, w, d}]（本地米：x/y=洞中心，w=短边，d=长边）。
    """
    if not wall_geoms:
        return []
    region = unary_union(wall_geoms)
    polys = [region] if region.geom_type == "Polygon" else list(region.geoms)
    shafts = []
    for po in polys:
        for h in po.interiors:
            hp = Polygon(h)
            minx, miny, maxx, maxy = hp.bounds
            w = maxx - minx
            d = maxy - miny
            sw, sd = min(w, d), max(w, d)
            if 1.0 <= sw <= 2.0 and 1.5 <= sd <= 3.0 and sd / sw >= 1.3:
                shafts.append({
                    "x": round(hp.centroid.x, 3),
                    "y": round(hp.centroid.y, 3),
                    "x0": round(minx, 3),
                    "y0": round(miny, 3),
                    "x1": round(maxx, 3),
                    "y1": round(maxy, 3),
                    "w": round(sw, 3),
                    "d": round(sd, 3),
                })
    return shafts


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
    for d in door_candidates:
        c = Point(d["x"], d["y"])
        if "bx0" in d:
            d["outer"] = box(d["bx0"], d["by0"], d["bx1"], d["by1"]).distance(outline.exterior) < DOOR_SYMBOL_FACE_TOL
        else:
            d["outer"] = c.distance(outline.exterior) < outer_wt + DOOR_CENTER_FACE_MARGIN
        half = d["w"] / 2
        cx, cy = d["x"], d["y"]
        if d["outer"]:
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
                  slab_outline=None, wall_x=None, wall_x_clip=None, outline_override=None):
    wall_pts = wall_pts_for_floor(F, walls, p, wall_x, wall_x_clip)
    # 门符号（门扇线 + 门垛的**闭合环**，与墙同图层）不是墙：它会被 buffer/双线配对成一块
    # ~0.9~1.5m × 0.10~0.24m 的假墙，正盖在门洞位置上 —— 用户报的「门有的夹在墙里看不到」
    # 根因（c019 首层 31 块）。这里在建墙前摘掉；符号本身仍留给 detect_doors 推门（判门只
    # 看折线形状，与墙无关），门窗判据不受影响。
    door_sym_pts = [pts for pts in wall_pts if is_door_symbol_pts(pts)]
    if door_sym_pts:
        wall_pts = [pts for pts in wall_pts if not is_door_symbol_pts(pts)]

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
    # line 约定（C006）：把楼板轮廓补齐到覆盖所有房间。房间边界是 DXF 实线（inner face），
    # 不是推断——半岛房间（如中央讲座厅）底部门洞 > close_r 时墙 union 漏出，用房间
    # 边界把半岛内部填回，不靠放大 close_r 推断。LWPOLYLINE 楼不启用（冻结基线）。
    if outline_override is None and getattr(p, "classifier", "lwpolyline") == "line" and rooms_polys:
        filled = unary_union([outline] + rooms_polys)
        if filled.geom_type == "MultiPolygon":
            filled = max(filled.geoms, key=lambda g: g.area)
        outline = Polygon(filled.exterior).simplify(0.2)
    # 过渡层楼板轮廓复用源楼层（全宽裙楼屋面），墙体仍按塔楼 outline 分类。
    # 但复用轮廓只有裙楼足迹：塔楼若压在裙楼轮廓的凹口/天井上方，塔墙就悬在楼板外
    # （c006 层6 实测 38.6% 塔墙面积露空）。楼板 = 裙楼足迹 ∪ 本层自身足迹，只增不减。
    if slab_outline is not None:
        merged = unary_union([slab_outline, outline]).buffer(0)
        if merged.geom_type == "MultiPolygon":
            merged = max(merged.geoms, key=lambda g: g.area)
        slab_poly = Polygon(merged.exterior)
    else:
        slab_poly = outline

    outer_band = outline.exterior.buffer(0.35, cap_style=2, join_style=2)

    # 门墙侧判定用「离最近墙更近」，不用「离轮廓更近」：内门摆动弧若指向较近立面，
    # 弧端 bbox 边会误判成墙侧（门面板浮离墙 ~1m）。墙 union 里门洞尚未挖，墙侧边点落在墙内（距离 0）。
    walls_union_for_door = unary_union(wall_geoms).buffer(0) if wall_geoms else None

    # 门：两类来源——
    #   LINE 约定（c006）：门=INSERT 块，classify_line 已把门编码成点列塞进 `doors` 参数
    #     （CAD 毫米）。这里 to_local 转本地米 + floor_of 过滤 + 点列跨度定朝向 + profile 定门宽。
    #   LWPOLYLINE 约定：doors 为空，门=墙折线几何符号，用 detect_doors 几何判定。
    #   各楼门符号画法不一（点数 3~17、有的带弧有的不带），几何判据只看「不闭合 + 门扇线跨度」。
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
    else:
        door_candidates = detect_doors(wall_pts + door_sym_pts, outline, p)

    # 门洞盒：外门挖外墙环带、内门挖内墙 union。两条门判据路径共用同一套盒（见 _door_boxes）。
    # 旧版整块被 door_by_points 关着，detect_doors 楼（c019 等 LWPOLYLINE 楼）从不挖洞——
    # 墙是连续的，门板被埋进实心墙里 = 用户报的「门有的夹在墙里看不到」。
    _door_boxes(door_candidates, outline, p, S)

    stairwells_json = detect_stairwells(F, walls, p)
    # 楼梯井同样过滤到 outline 内（首层双副本的另一栋井中心在 outline 外数百米）
    stairwells_json = [s for s in stairwells_json
                       if Point((s["x0"] + s["x1"]) / 2, (s["yBot"] + s["yTop"]) / 2).distance(outline) <= 1.0]

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

    if getattr(p, "classifier", "lwpolyline") == "line":
        # line 约定（C006）：外墙/内墙都用「实际墙矩形」，厚度读自双线配对（240/270/120/60/350/380mm），
        # 按厚度分桶 union，每桶 thickness = 该桶真实墙厚，不冒充统一 0.30/0.24。
        # 不用合成外环（outline.buffer(-outer_t) 会无视真实外墙线、把墙厚统一成 0.30m）。
        def _emit_group(geoms, wtype, thickness, subtract=None):
            nonlocal wid
            if not geoms:
                return
            region = unary_union(geoms).simplify(0.1).buffer(0)   # 清洗自交
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

        outer_geoms_ts = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                          if g.centroid.distance(outline.exterior) <= outer_t]
        inner_geoms_ts = [(g, t) for g, t in zip(wall_geoms, wall_ts)
                          if g.centroid.distance(outline.exterior) > outer_t]
        # 内墙减去外墙总区域：T 字口处内墙端头探进外墙矩形 → 同一片墙被外墙色+内墙色
        # 各画一遍（重叠）。减法让内墙止于外墙内侧面，重叠归零（几何上也是对的）。
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
        outer_boxes = [d["box"] for d in door_candidates if d.get("outer")]
        inner_boxes = [d["box"] for d in door_candidates if not d.get("outer")]

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
        outer_boxes = [d["box"] for d in door_candidates if d.get("outer")]
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
                           if g.distance(outline.exterior) > outer_t]
        else:
            inner_geoms = [g for g in wall_geoms
                           if g.centroid.distance(outline.exterior) > outer_t * INNER_WALL_CENTROID_FACTOR]
        if inner_geoms:
            inner_region = unary_union(inner_geoms).simplify(0.1).buffer(0)   # 清洗自交
            if getattr(p, "door_by_points", False):
                # 内墙减外墙合成环：内墙止于外墙内侧面，消除与外墙的 T 形重叠（不重复建设）
                inner_region = inner_region.difference(outer_ring).buffer(0)
            # 门洞挖进内墙：内门盒把内墙带切断成真实门洞（门 = gap 不是 hole）
            inner_boxes = [d["box"] for d in door_candidates if not d.get("outer")]
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
    windows_json = []
    for w in wall_entities:
        if w["type"] != "outer":
            continue
        for win in facade_windows(Polygon(w["poly"]), outline, S):
            win["id"] = f"win{F}-{len(windows_json)}"
            win["wallId"] = w["id"]
            win["synthetic"] = True
            windows_json.append(win)

    # 房间：剔除中心落在楼板轮廓外的（轮廓已补齐覆盖房间，正常全保留）
    rooms_json = []
    for r in rooms_data:
        if r.get("floor") != F:
            continue
        b = r["boundary"]
        if len(b) < 3:
            continue
        rp = Polygon(b)
        if not outline.contains(rp.centroid):
            continue
        rooms_json.append({
            "id": r.get("id"),
            "poly": r2(b),
            "purpose": r.get("purpose") or "",
            "number": r.get("number") or "",
        })

    # 结构柱按图来：图里画了哪层就哪层（columns_local 是 {floor: [柱]}，本层缺省为空）
    columns_json = [dict(c) for c in columns_local.get(F, [])]

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

    # 电梯井：墙 union 里的小矩形洞（竖井）。井道墙已在 wall_geoms 里（当内墙渲染），
    # 这里只补「楼板开洞」与「电梯门」所需的井道 bbox；门由 door_candidates 里落在井口的
    # $DorLib2D 承载，渲染层把贴井道的门当作电梯门。
    elevators_json = detect_elevator_shafts(wall_geoms, p)

    result = {
        "floor": F,
        "layer_height": float(S["floor_h"]),
        "outline": _dedupe(r2(slab_poly.exterior.coords)),
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
    if is_top:
        # 中央主体屋面：屋面板 + 女儿墙（由 outline 外扩生成，含北边）
        result["roof"] = {
            "roofT": float(S["roof_t"]),
            "parapetH": float(S["parapet_h"]),
            "parapetT": float(S["parapet_t"]),
        }
    return result
