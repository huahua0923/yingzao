# -*- coding: utf-8 -*-
"""建筑档案（building profile）——每栋楼一张配置表。

「构件自动识别」的核心难点：4 栋楼用 4 种绘图约定。把差异集中到 BuildingProfile，
识别引擎只读 profile，不关心是哪栋楼。

扩展点：
  - classify（classify.py）：不同楼的门/墙/柱判定方式不同（理化楼用 LWPOLYLINE 点数，
    六教用 LINE+ARC + INSERT）。目前 classify.py 只实现理化楼基线。
"""
from dataclasses import dataclass


@dataclass
class BuildingProfile:
    name: str          # 建筑代号，如 "lihua" / "j6"
    title: str         # 中文名
    dxf: str           # 源 DXF 绝对路径
    rooms: str         # 房间 JSON（rooms.json）绝对路径
    out_dir: str       # 楼层 JSON 输出目录

    # 坐标变换：CAD 毫米坐标 → 本地米坐标
    offset: float      # 每层沿 Y 的平移量（毫米）
    cx: float          # 中心 X（毫米）
    cy: float          # 中心 Y（毫米）

    # 图层约定（不同楼命名不同）
    wall_layer: str    # 墙/门/台阶共用的图层
    column_layer: str  # 结构柱图层

    # 构件分类：按多段线点数区分门 / 台阶 / 墙
    door_min_points: int   # 点数 ≥ 此值 → 门
    stair_points: int      # 点数 == 此值 → 台阶

    # 墙皮配对
    wall_min: float        # 双线墙最小厚度（米）
    wall_max: float        # 双线墙最大厚度（米）
    wall_extend: float     # 墙段沿走向外延量（米）
    wall_fallback: float   # 无配对墙段单边厚度（米）

    # 门
    door_w_single: float   # 单扇门宽（米）
    door_w_double: float   # 双扇门宽（米）
    door_depth: float      # 门洞深（米）

    # 楼板轮廓
    outline_buf: float     # 墙中心线缓冲半径（米）
    open_r: float          # 开运算半径（米）
    parapet_margin: float  # 轮廓外判定余量（米）

    # 层高
    layer_height: float    # 层高（米）
    slab: float            # 楼板厚（米）

    # 可选：轮廓闭运算半径（米）。LINE 墙（c006）角点/门洞把墙带断开成几十段不相连的碎带，
    # union 后仍 MultiPolygon，max(area) 只留最大一翼 → 足迹塌成 314㎡。close_r>0 时先 buffer
    # 桥接再回缩成封闭足迹。0=不闭运算（LWPOLYLINE 楼有填充矩形已闭合）。默认 0 不破坏基线。
    outline_close_r: float = 0.0

    # 可选：X 隔离区间（毫米）。DXF 里多栋并排/重复复制时，只取主列。
    # None = 不隔离（沿用整幅 X 范围，如理化楼）。
    x_range: tuple = None  # (x_min_mm, x_max_mm)

    # 可选：阶梯状楼（塔楼+裙楼）每层平面 Y 中心（毫米），按楼层号索引。
    # 阶梯楼的各层平面在图纸上以「非均匀间距」上下排布（裙楼宽、塔楼窄，两序列交错），
    # 单 offset 无法表示，故直接存每层 Y 中心。None = 均匀楼（楼层 i 在 cy + i*offset）。
    floor_ys: list = None

    # 可选：阶梯楼「两列」布局（裙楼+塔楼分列 X，X 是唯一能区分两列的判据），如六教 C006。
    # 每层一个 [cx, cy, x_min, x_max]（毫米）：
    #   cx/cy    = 该层平面中心（to_local 用它把该层居中到本地原点，塔楼/裙楼各自居中→塔楼自然居中裙楼）
    #   x_min/max= 该层墙体 X 区间（floor_of 用 X 先判列，列内再按 Y 最近取层）
    # None = 单列楼（用 floor_ys 或均匀 offset）。
    floor_plans: list = None

    # 可选：构件分类器选择。"lwpolyline" = 理化楼基线（墙/门/台阶共用图层，按 LWPOLYLINE 点数区分）；
    # "line" = 六教 C006（墙 = LINE 双线，门 = INSERT 块，柱 = INSERT 块）。默认 lwpolyline 不破坏基线。
    classifier: str = "lwpolyline"

    # 可选：外观样式（外墙/屋顶颜色、屋顶形式），dict 直通 emit_spec 的 "style"。
    # None = 用 standard.STYLE_DEFAULT（红砖坡顶）。
    style: dict = None

    # 可选：阶梯楼「过渡层」——楼板全宽、但建筑墙体只占其中窄条（如六教第 7 层：
    # 裙楼屋面全宽 + 塔楼从中耸起，屋面女儿墙稀疏、纯闭运算会塌成蕾丝足迹）。
    # {floor_index: {"slab_from": 源楼层(楼板轮廓复用该层), "wall_x": [x0,x1] 毫米(只取该 X 区间的墙)}}。
    # None = 无过渡层。默认 None 不破坏基线。
    transition: dict = None

    # 可选：多翼/阶梯楼「统一 footprint」。这类楼低层的墙 union 碎片化（c009 F0 21 片、
    # F1 39 片），derive_walls_and_outline 里 max(area) 只留最大一翼 → 轮廓塌成小片、
    # 质心横漂（低层错位）。设 True 后，recognize 先在所有楼层里挑「轮廓面积最大（墙最
    # 完整）」的一层当基准，全楼复用该轮廓（外墙环带/窗/房间过滤/slab 全部同源）。
    # 默认 False 不破坏理化楼等逐层各自推导的基线。
    outline_unify: bool = False

    # 可选：仅统一「指定楼层子集」的 footprint（阶梯楼裙楼）。阶梯楼（六教 C006）裙楼 F0-F5
    # 应同一 U 形 footprint，但上层裙楼（F4/F5）中央区墙少 → derive 塌成小轮廓；塔楼 F7-F10
    # 又是独立小 footprint，不能用 outline_unify=True 全楼统一（会把塔楼盖成裙楼轮廓）。
    # 此字段列出要统一的楼层号（如 [0,1,2,3,4,5]），reference_outline_for 只在子集内挑「面积
    # 最大」的一层当基准，其余层（塔楼/过渡层）照常各自推导。优先于 outline_unify=True。
    # None = 不启用子集统一。默认 None 不破坏基线。
    outline_unify_floors: list = None

    # 可选：line 约定下单线墙（无平行近邻）的可见厚度（米）。双线配对后剩余的孤线
    # （门垛/短段/女儿墙）没有厚度信息，按此最小可见厚度渲染，不冒充有厚度的墙。
    single_wall_t: float = 0.10

    # 可选：该楼「真实墙厚」集合（米），从图纸双线墙间距直方图读出（如 C006 实测
    # 60/120/240/270/350/380mm）。配对出的中间值（两皮来自不同墙的误配对 artifact，如
    # 300/340/360mm）会 snap 到最近真实墙厚并 recenter，消除「有的墙很厚」。
    # None = 不 snap（保持原始配对厚度，不破坏 LWPOLYLINE 基线）。默认 None。
    wall_thicknesses: list = None

    # 可选：外墙真实墙厚（米）。理化楼等「外墙 = 8 点单线外皮折线」的楼，外墙无内皮线可
    # 配对读厚，改用门垛实测墙厚直接往建筑内侧单向 buffer 成实体墙。默认 0.24（理化楼门垛实测）。
    outer_wall_t: float = 0.24

    # 可选：True = 按点数分门/台阶（理化楼：门 ≥ door_min_points 点、含「闭合」的双门符号、
    # 台阶 == stair_points 点；门宽按 16 点=单门 door_w_single / 23 点=双门 door_w_double，
    # 门洞挖进墙）。False = 通用几何判定（不闭合 + 门扇线跨度），不破坏他楼基线。默认 False。
    door_by_points: bool = False

    # 可选：True = 薄墙配对时额外识别「斜墙 / 曲墙」。默认配对(pair_wall_faces)把每段按
    # |dx|>=|dy| 塞进水平/垂直两桶, 斜段与弧离散出的短弦会被直接丢弃 → 曲墙识别不出来。
    # 开启后, 轴对齐段仍走原配对(逐段等价), 剩下的斜段交给 curve_walls.pair_curved_faces
    # 用线段自身方向配对(同 wall_min/wall_max 间距、投影重叠 >0.3m)。
    # 默认 False: 无斜墙/曲墙的楼一个字节都不变。
    pair_curved: bool = False


# ---- 坐标助手（纯函数，只依赖 profile 的变换参数） ----

def to_local(p, x, y, f):
    """CAD 毫米坐标 → 本地米坐标（f 为楼层号）。"""
    if p.floor_plans:
        cx, cy, _, _ = p.floor_plans[f]
        return ((x - cx) / 1000.0, (y - cy) / 1000.0)
    fy = p.floor_ys[f] if p.floor_ys else (f * p.offset + p.cy)
    return ((x - p.cx) / 1000.0, (y - fy) / 1000.0)


def floor_of(p, x, y):
    """CAD 毫米坐标 → 楼层号。

    阶梯楼两列（floor_plans 给定，如六教裙楼+塔楼）：X 先判列（塔楼/裙楼 X 区间互斥），
    列内再按 Y 最近取层；X 落在所有区间外（两列间隙的零星墙）→ 兜底全层按 Y 最近。
    阶梯楼单列（floor_ys 给定）：取与 y 最近的楼层中心。
    均匀楼：楼层 i 平面中心在 Y = cy + i*offset，故 f = round((y - cy)/offset)。
    （若只 round(y/offset)，当 cy > offset/2 时整栋楼楼层会整体 +1，如第一教学楼。）
    """
    if p.floor_plans:
        cands = [(i, plan) for i, plan in enumerate(p.floor_plans) if plan[2] <= x <= plan[3]]
        if cands:
            return min(cands, key=lambda t: abs(y - t[1][1]))[0]
        return min(range(len(p.floor_plans)), key=lambda i: abs(y - p.floor_plans[i][1]))
    if p.floor_ys:
        return min(range(len(p.floor_ys)), key=lambda i: abs(y - p.floor_ys[i]))
    return round((y - p.cy) / p.offset)


def in_floor_x_range(p, x):
    """实体 X 中心是否落在楼栋有效 X 区间（供分类器在 floor_plans 两列布局下过滤间隙墙）。
    floor_plans 优先（各层 X 区间并集），否则用 x_range，均无则全保留。"""
    if p.floor_plans:
        return any(plan[2] <= x <= plan[3] for plan in p.floor_plans)
    if p.x_range:
        return p.x_range[0] <= x <= p.x_range[1]
    return True


# ---- 注册表 ----

_PROFILES = {}


def register(p):
    _PROFILES[p.name] = p
    return p


def get_profile(name):
    try:
        return _PROFILES[name]
    except KeyError:
        raise KeyError(
            f"未注册的 building profile: {name}（已注册: {list(_PROFILES)}）"
            f"——请先 import recognizer.profiles"
        )
