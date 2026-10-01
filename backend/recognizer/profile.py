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

    # 可选：房号标注的「最近区域」兜底半径（米）。有些图的房号标注不画在房间内，
    # 而画在楼外（ny27 的六个房号排成一列落在南墙外），严格包含判据一个都配不上 → 房间全丢。
    # >0 时：严格包含失败的区域，退到「距离 <= 本值」的最近**未占用**标注（一对一）。
    # 默认 0 只用严格包含 —— c029 那类图有 422m 外的野标注，
    # 不封顶的最近归属会把它硬配到真房间上。
    label_nearest_max: float = 0.0

    # 可选：X 隔离区间（毫米）。DXF 里多栋并排/重复复制时，只取主列。
    # None = 不隔离（沿用整幅 X 范围，如理化楼）。
    x_range: tuple = None  # (x_min_mm, x_max_mm)

    # 可选：**一张图描述多层**时，把该图的图元并进哪些楼层。{源图带号: [目标楼层号, ...]}。
    # 作为键出现的图带**不再是独立楼层**（它描述的内容由目标楼层承载）。
    #
    # 为什么需要（c009 第九教学楼，2026-09-12 定案）：图纸里第 0 张图不是「一层」。它图上
    # 的房号同时有 `-A-01-H1/H2`（学术报告厅/新闻中心，一层）和 `-A-02-H3/H4`（其他仓库/
    # 泵房，二层）—— 圆厅是**通高二层**的大空间，所以一张图描述了两层。原先按「图带号 =
    # 楼层号」处理，这张图被当成一个畸形底层（轮廓只有圆厅的 1416㎡），于是用
    # `skip_floors:[0]` 把它整个剔出模型 —— 结果**把两个圆厅一起剔掉了**（用户实拍图里
    # 最显眼的西端椭圆大厅与东端弧形大厅）。正确做法：这张图的墙属于 1 层和 2 层。
    #
    # 并图**不需要重新对齐**：实测（_scratch/_c009_overlay01.py 叠图）第 0 张与第 1 张的
    # 局部坐标是同一套建筑坐标 —— 第 0 张的两个椭圆正落在第 1 张 A/C 分区的开间上。所以
    # 只需按 sheet_shift() 把该图图元平移进目标图带，to_local 得到的局部坐标与源图完全一致。
    #
    # **图带号 vs 交付层号（c009 定案时踩过）**：均匀楼的层号是 `f = round((y-cy)/offset)`，
    # 而 c009 的图带号恰好等于楼层号（第 1 张图 = 一层），于是 floor0 被并走后交付变成
    # floor1..floor5 —— **层号非 0 基**。只读门禁 `qa_structural.load_floors()` 从 floor0.json
    # 顺序读、遇缺即停，读到就 break → 本栋判「无楼层」→ 全库汇总崩在 unpack 4 元组。
    # 修法是把层号口径整体下移一层：`cy += offset`（于是 f = 图带号-1，floor0 = 一层，
    # 每个交付层的 frame_center 与本地坐标**逐字节不变**：frame_center_new(f) =
    # frame_center_old(f+1)），并把 sheet_floors 的键一起改成 -1:{0,1}。
    # 全库 49 栋只有 c009 需要这一步（其余都从 floor0 起）。
    # None = 一张图只对一层（其余 48 栋逐字节不变）。
    sheet_floors: dict = None

    # 可选：阶梯状楼（塔楼+裙楼）每层平面 Y 中心（毫米），按楼层号索引。
    # 阶梯楼的各层平面在图纸上以「非均匀间距」上下排布（裙楼宽、塔楼窄，两序列交错），
    # 单 offset 无法表示，故直接存每层 Y 中心。None = 均匀楼（楼层 i 在 cy + i*offset）。
    floor_ys: list = None

    # 可选：**每层的 Y 窗口**（CAD 毫米，[[y0,y1], ...]，与 floor_ys 同序）。
    # 为什么需要（2026-09-17 c020/c037/c044/c001 实测）：一张 DXF 里除了本楼各层平面，
    # 还常画着**基础平面图、剖面/立面图、另一栋的图、场地总平面** —— 与本楼平面共享
    # 同一段 X，但落在别的 Y 上。`floor_of` 只按"最近层中心"归属，这些杂项会被并进
    # 最近那层 → 表现为"一张图两块""首层楼板 3 块""柱多一根"，SU 规格的逐带锚点门禁直接判红。
    # 给了窗口：**窗口内**按最近中心归属；**窗口外**返回 None（不属于任何层，
    # 识别/房间提取/渲染三处都是 None 或 `!= F` 判定 → 自然丢弃）。None = 不启用（老楼逐字节不变）。
    floor_y_bands: list = None

    # 可选：阶梯楼「两列」布局（裙楼+塔楼分列 X，X 是唯一能区分两列的判据），如六教 C006。
    # 每层一个 [cx, cy, x_min, x_max]（毫米）：
    #   cx/cy    = 该层平面中心（to_local 用它把该层居中到本地原点，塔楼/裙楼各自居中→塔楼自然居中裙楼）
    #   x_min/max= 该层墙体 X 区间（floor_of 用 X 先判列，列内再按 Y 最近取层）
    # None = 单列楼（用 floor_ys 或均匀 offset）。
    floor_plans: list = None

    # 可选：**帧对齐附加平移**（CAD 毫米）：{"层号": [dx, dy]}。`to_local` 减去它；
    # `floor_of` 判归属**不受影响**（它走 `frame_center`，见那里的 docstring）。
    # 用途：层带原点（判归属要留在"图纸画在哪"）与局部坐标原点（要的是"建筑上的同一
    # 基准"）是两个量，图纸把各层画在图纸不同位置时它们差几米到几十米（实测 c027
    # 14.075m / c103 11.85m / c015 47m）。代数上它就是**逐位还原**：原点取均匀式
    # f*offset+cy 再减 (floor_ys[f] - (f*offset+cy))，结果恒等于 y - floor_ys[f]。
    # ★ 2026-09-29 实测交接，写在这里免得下一个人以为它在正常工作：
    #   这个机制 2026-09-16 自动写过一轮又全撤了（`_scratch/_revert_frame_shift.py`
    #   的 docstring：异形层会被配出垃圾解）；**今天全库 92 份档案里 0 份在用**；
    #   而且**两个加载器都没带这个键**（`run_building.load_profile` 与
    #   `run_step.profile_from_cfg` 实测都 0 命中）⇒ 写进 profile.json 等于没写。
    #   2026-09-29 给两个加载器各补了一行，并首次真用它：c011 记 D1 = **−1 层**
    #   （删 floor_ys 后层带原点变均匀式，靠它把各层拉回同一基准）。
    #   ⚠ 「两个加载器都带了」是**这一刻**的测量，不是性质；新增投递通道要回来核
    #     `backend/web/console_meta.py:_delivery_channels()`。
    frame_shift: dict = None

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

    # 可选：**室外台阶**（逐层给出本地米矩形 [x0, y0, x1, y1]）—— 不建墙、不进楼板。
    # 用途与判据（2026-09-15，六教 C006 F0 东西两侧的室外大台阶）：
    #   图上「9.3m 深平台 + 7 级 0.35m 踏步」，外沿只是一条**边线**（没有第二皮），
    #   但它的两侧挡墙是真墙 → 会在楼板轮廓里围出 U 形里腔（`Polygon(exterior)` 会填实），
    #   平面轮廓因此虚胖 588㎡。用户判例：「室外的就是室外台阶」。
    # 为什么不自动判：自动判据（≥3 条等距平行线 + 两端围合）在 c006 会同时命中**室内
    #   楼梯间与中庭大台阶**（实测每层 2~6 处）→ 把室内楼板挖掉。具名口子不可误伤。
    # None = 无。默认 None 不破坏其他楼基线。
    outdoor_steps: dict = None

    # 可选：**屋面补块**（`{层: [房号]}`）—— 下层是该房间、本层图上没有楼板的地方要封顶。
    # 判例 c006 八角厅：1~4 层是房间（6-C-01-05 … 6-C-04-05），5 层（F4）图上什么都没有，
    # 但那就是八角厅的屋面。按房号取面并进该层轮廓；GLB/SU 的 `build_slab` 会按
    # 「上面有没有楼层」把它切成**屋面色**。None = 无。
    roof_rooms: dict = None

    # 可选：**保留内院/天井内环**（默认 False = 历史口径，轮廓取外环填实）。
    # 回字形平面（c072/c073/c103/c009）的内院是真实存在的：填实会让楼板凭空多出整片面积，
    # 而图纸自带面积表里内院**不计面积**（实测 c072/c073 每层 +1200㎡ 正好是内院带）。
    # True ⇒ `blocks_to_outline(keep_holes=True)` + 交付写 `outline_holes`。
    keep_courtyard_holes: bool = False

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

    # 可选：True = 房间只读交付的 floors/floorN.json（墙 / 轮廓 / 门洞盒）——「单源墙」。
    # 背景（2026-09-11 ny27 复盘，见《算法与流程·对标四族·重构.md》§1）：同一栋楼曾有三套
    # 墙几何 —— recognize 的粗环 blob / _wall_thin_batch 的交付内墙 / 本模块又自推的一套。
    # 自推那套对「3+ 点、跨度 < 3m 的不闭合折线」按门符号丢弃，交付那套保留 → 单元内的短
    # 隔墙只存在于交付墙里；谁按交付墙去修房间边界，房间就被切成碎块（56㎡→3 块）。
    # 默认 False：不改变其余楼基线。**顺序铁律**：必须在内墙重建之后运行。
    rooms_from_floors: bool = False

    # 可选：单源墙模式下「定连通性」的封缝半径（米），0 = 不封。
    # 交付墙是**真厚薄墙**，两块墙在接头处往往差零点几米没接上（配对出的矩形只覆盖本段面的
    # 范围），自由空间就从缝里漏成一整块 —— ny27 F0 实测：不封缝时全层只有 **1 个**房间候选。
    # ③ 那套「假边」之所以能围出房间，是因为它对每条面线各 buffer 0.15，等于顺手做了闭运算。
    # 这里**只把膨胀用于判连通分量**，最终边界依旧裁在未膨胀的真墙身上 —— 不新增任何墙。
    # 取值靠实测的稳定性平台：ny27 F0 在 0.06–0.10 稳定 15 个分量（6 套 + 9 公共空间），
    # <0.06 欠封、≥0.12 过封（套内卫生间/厨房隔墙被切开，6 个房号会掉到子房间上）。
    room_seal: float = 0.0

    # 可选：单源墙模式下把房间边界贴回墙内皮的外扩量（米），0 = 不贴。
    # 房间候选的边界停在「墙区」外沿，而墙区比真墙宽，房间四周被削掉约一个外扩量。
    # 外扩后裁到「轮廓 − 交付墙身」：只朝墙侧长、被真墙身挡住，不越过图纸墙线、不新增墙。
    room_grow_to_wall: float = 0.0

    # 可选：房间通路分派（见 extract/room_route.py）。
    #   "regen"  = 主线，从 DXF 现推墙（不写 = 默认，等同历史行为）；
    #   "single" = 支线，读交付 floors/floorN.json 的墙（等同 rooms_from_floors=True）；
    #   "auto"   = **逐层按图择优** —— 两条线都算，用「图纸自己的房号」当裁判，
    #              谁把更多房号认领到互不相同的房间里就用谁。
    # 为什么需要（2026-09-14 实测）：两条线各有胜负，写死任何一条都会出事 ——
    #   c033 主线 F0 从 23 掉到 3、合计 33/143；支线 143/143。
    #   c006 支线 27/221、c116 支线 35/89；主线分别 205/221、83/89。
    #   c026/c041/c022/c027/c029 两条线**逐层完全相同**（换线无用，缺口在墙上）。
    # 未写此键的楼行为**逐字节不变**（老楼零影响）。
    room_route: str = ""

    # 短线密集簇过滤（斜向楼梯踏步线被当墙，见 classify_line._drop_tread_clusters）
    tread_cluster_filter: bool = False

    # 中庭开洞：{层号: [房号,...]} —— 通高中庭下面几层的楼板要挖穿（见 recognize 里的注释）
    atrium_rooms: dict = None

    # 中庭开洞（按几何）：{目标层: 源层} —— 目标层图纸上没登记房号时，借用源层的几何挖洞
    atrium_from: dict = None


# ---- 坐标助手（纯函数，只依赖 profile 的变换参数） ----

def frame_center(p, f):
    """第 f 层「本地原点」对应的 CAD 毫米坐标 —— 与 to_local 同一套口径。

    单独抽出来的唯一原因：sheet_shift() 要算「把图带 S 的图元挪到图带 F」的平移量，
    必须和 to_local 用**同一个** y 口径（floor_plans 的 cy / floor_ys[f] / f*offset+cy），
    否则并图后局部坐标会差一个常量，而这种错只有对着图才看得出来。

    ★ 2026-09-16 **帧对齐另加一层**（`profile.frame_shift`）：层带（判归属）必须留在
    "图纸画在哪"，而局部坐标要的是"建筑上的同一基准" —— 图纸把各层画在图纸不同位置时，
    这两个量会差几米到几十米（实测 c027 14.075m、c103 11.85m、c015 47m）。
    所以：`frame_center` 仍返回**层带原点**（floor_of 判归属照用，不动），
    `to_local` 再减 `frame_shift`（自动对齐脚本 `_scratch/_align_frames_auto.py` 写）。
    """
    if p.floor_plans:
        return float(p.floor_plans[f][0]), float(p.floor_plans[f][1])
    fy = p.floor_ys[f] if p.floor_ys else (f * p.offset + p.cy)
    return float(p.cx), float(fy)


def frame_shift(p, f):
    """该层的**帧对齐附加平移**（毫米）；没配就是 (0,0)。"""
    d = getattr(p, "frame_shift", None) or {}
    v = d.get(str(f), d.get(f))
    if not v:
        return 0.0, 0.0
    return float(v[0]), float(v[1])


def to_local(p, x, y, f):
    """CAD 毫米坐标 → 本地米坐标（f 为楼层号）。"""
    fx, fy = frame_center(p, f)
    sx, sy = frame_shift(p, f)
    return ((x - fx - sx) / 1000.0, (y - fy - sy) / 1000.0)


# X 区间判定容差（CAD 毫米）：真实墙线恰好画在区间边界上时，浮点尾数会超出界
# （实测 c006 西列东外皮 x=1142175.003 对区间上界 1142175.0）→ 严格比较会把这批
# 真实线丢掉。1mm 远小于任何设计尺寸，两列间隙 340m，不会串列。
RANGE_TOL_MM = 1.0


def sheet_shift(p, src, dst):
    """把「图带 src」的 CAD 图元平移到「图带 dst」需要加的 (dx, dy)（毫米）。

    均匀楼就是 (0, (dst-src)*offset)；阶梯楼按两层各自的原点算，所以这里一律走
    frame_center，不写死 offset。平移后 to_local(..., dst) 与 to_local(..., src) 恒等。
    """
    sx, sy = frame_center(p, src)
    dx_, dy_ = frame_center(p, dst)
    return dx_ - sx, dy_ - sy


def floor_of(p, x, y):
    """CAD 毫米坐标 → 楼层号。

    阶梯楼两列（floor_plans 给定，如六教裙楼+塔楼）：X 先判列（塔楼/裙楼 X 区间互斥），
    列内再按 Y 最近取层；X 落在所有区间外（两列间隙的零星墙）→ 兜底全层按 Y 最近。
    阶梯楼单列（floor_ys 给定）：取与 y 最近的楼层中心。
    均匀楼：楼层 i 平面中心在 Y = cy + i*offset，故 f = round((y - cy)/offset)。
    （若只 round(y/offset)，当 cy > offset/2 时整栋楼楼层会整体 +1，如第一教学楼。）
    """
    if p.floor_plans:
        cands = [(i, plan) for i, plan in enumerate(p.floor_plans)
                 if plan[2] - RANGE_TOL_MM <= x <= plan[3] + RANGE_TOL_MM]
        if cands:
            return min(cands, key=lambda t: abs(y - t[1][1]))[0]
        return min(range(len(p.floor_plans)), key=lambda i: abs(y - p.floor_plans[i][1]))
    # ★ 每层 Y 窗口（profile.floor_y_bands）：窗口外的实体**不属于任何层** → None。
    #   必须先判窗口再按最近中心归属，顺序反了会把窗口外的杂项归到最近层。
    _bands = getattr(p, "floor_y_bands", None)
    if _bands:
        for _i, _b in enumerate(_bands):
            if _b[0] <= y <= _b[1]:
                return _i
        return None
    if p.floor_ys:
        return min(range(len(p.floor_ys)), key=lambda i: abs(y - p.floor_ys[i]))
    return round((y - p.cy) / p.offset)


def in_floor_x_range(p, x):
    """实体 X 中心是否落在楼栋有效 X 区间（供分类器在 floor_plans 两列布局下过滤间隙墙）。
    floor_plans 优先（各层 X 区间并集），否则用 x_range，均无则全保留。

    ⚠️ 判据带 RANGE_TOL_MM 容差：**真实墙线画在区间边界上时浮点尾数会超出**
    （实测 c006 西列东外皮 x=1142175.003 vs 区间上界 1142175.0），严格比较会把
    这一批真实墙线整条丢掉 —— 而两列间隙 340m，1mm 容差不可能串列。
    """
    if p.floor_plans:
        return any(plan[2] - RANGE_TOL_MM <= x <= plan[3] + RANGE_TOL_MM
                   for plan in p.floor_plans)
    if p.x_range:
        return p.x_range[0] - RANGE_TOL_MM <= x <= p.x_range[1] + RANGE_TOL_MM
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
