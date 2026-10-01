# -*- coding: utf-8 -*-
"""构件库（Component Library）：11 栋教学楼 DXF→3D 识别过程中沉淀的「构件签名 + 判据 + 坑」。

设计意图（用户要求）：
  - 「把作图过程中的经验总结起来，下次再遇到就直接识别」——每个构件一条几何签名，
    新楼来了直接套用同名函数/常量；识别错了就改这里，而不是在识别代码里散落魔法数字。
  - 「有问题就更新构件库」——每处判据写清 WHY + 修过的具体案例，避免重蹈覆辙。

用法：
    from recognizer.component_library import (
        COMPONENTS, SLAB_RATIO, DOOR_LEAF_MIN, DOOR_LEAF_MAX,
        is_closed, is_slab, is_door, classify_inner_wall, cluster_floors, describe,
    )
    describe()

与识别代码的关系：
    geometry.py / floor.py / classify.py 里的魔法数字逐步迁到本库命名常量（单点维护）。
    当前已接线：SLAB_RATIO、DOOR_LEAF_MIN/MAX、门垛/门扇口径、内外墙 centroid 判据。
"""

import math

# =====================================================================
# 一、命名常量 —— 识别代码从这里取值，改一处全楼生效
# =====================================================================

# 楼板 vs 墙：闭合多边形 area/length（= 等价半厚）> 此值判为「填充区/楼板」，否则「墙」。
# 墙半厚 0.04~0.18m；楼板/剖面填充 1~数十 m。取 1.0 留足余量。
SLAB_RATIO = 1.0

# 门扇线长度区间（m）。门 = 不闭合折线且「最长段」∈ [min, max)。
# 下界 0.6 排除门垛短段（最长≈0.34）；上界 3.0 排除带门洞缺口的墙折线（最长≥3m）。
DOOR_LEAF_MIN = 0.6
DOOR_LEAF_MAX = 3.0

# 不闭合折线「跨度」判定门 vs 墙折线的分界（m）。
#   span < DOOR_SPAN_MAX → 门符号（leaf+arc）；span >= 则带门洞缺口的墙折线（c041 最长 45.7m）。
DOOR_SPAN_MAX = 3.0

# 门垛块（门框/门垛小方块）边长区间（m）——「闭合门符号」判据用。
DOOR_JAMB_MIN = 0.10
DOOR_JAMB_MAX = 0.40
# 闭合门符号整环 bbox 跨度上限（m）。超过即不是门符号（带门洞缺口的墙折线／房间边界／细长窗块）。
DOOR_SYMBOL_SPAN_MAX = 3.0
DOOR_SYMBOL_TOL = 1e-6          # 门符号判据的浮点容差(m)。图纸坐标是 mm 级大数(如 1265215),
                                # 除 1000 转米后相减会丢有效位 —— c034 的 100mm 门垛边算成
                                # 0.0999999999999, 卡在 DOOR_JAMB_MIN 下界外, 36 个门符号全被判否。

# 门垛（jamb）：门符号折线里的 0.24m 短段，最长≈0.34m，不是门扇。
# 实测门符号 bbox 跨度被门垛撑到 1.3m（=1.0m 门扇 + 2×0.15m），故门宽取「最长段」而非 bbox 跨度。
JAMB_LEN = 0.34
JAMB_W = 0.24

# 墙厚归一化（标准楼，见 standard.py）
WALL_T_OUTER = 0.30
WALL_T_INNER = 0.24

# 内外墙判据：内墙质心距轮廓 > outer_t * 此系数。质心判据无死区（旧面积带 0.35m 比外墙
# 环带 0.30m 宽，会在 0.30~0.35m 造出「判外墙却被丢弃、又超环带」的死区，c027 F7 覆盖 0 根因）。
INNER_WALL_CENTROID_FACTOR = 0.75

# 楼层聚类：墙层 Y 坐标聚成「一层」的最小间隔（mm）。层间距 135000~203520mm 远大于此，
# 屋顶女儿墙/踏步等子元素与主楼板高差 15000~45000mm 也小于此，故 30000 能干净分层。
# 顶点法比「质心法」更稳（每实体多顶点投票），gap 取 30000 合并屋顶子元素。
FLOOR_CLUSTER_GAP = 30000


# =====================================================================
# 二、构件签名表 —— 每个构件的识别规则 / 参数 / 坑（经验）
# =====================================================================

COMPONENTS = {
    "墙(wall)": {
        "signature": "墙层(4.2墙体/墙体)上 >=2 点的 LWPOLYLINE。2 点=墙皮线(双线墙的一面)；"
                     "3+ 点闭合且 area/length<=SLAB_RATIO=填充墙；3+ 点不闭合且 span>=3m=带门洞缺口墙折线。",
        "params": {"厚度": "120/200/240/300mm，识别后归一化 outer=0.30/inner=0.24",
                   "墙皮半厚": "p.wall_fallback=0.15m(2 点线 buffer 半墙厚)"},
        "pitfalls": [
            "双线墙两皮之间缝隙靠 g.buffer(0.05) 桥接，否则 union 后墙被拆成两条细线。",
            "点划线轴线/细线门弧不是墙：资产图不携带线宽，只能靠图层过滤 + 几何 span 区分。",
        ],
    },
    "楼板(slab)": {
        "signature": "闭合多边形 area/length > SLAB_RATIO(=1.0)。是剖面材料图例的「涂黑/45°斜线填充」"
                     "(混凝土/楼板断面)，不是墙。",
        "params": {"判据": "area/length > 1.0"},
        "pitfalls": [
            "填充区混进墙 union 会把轮廓撑成整片楼板 + 把真墙拆碎(c009/c114 根因)。",
            "无效多边形(自交)必须 buffer(0) 清洗：c104 裙楼 3959㎡ 楼板 is_valid=False，"
            "不洗就整片丢弃 → 轮廓塌掉。",
        ],
    },
    "门(door)": {
        "signature": "不闭合折线且「最长段」∈ [0.6, 3.0)m。点数 3~17、带/不带弧都算，唯一共性是"
                     "「不闭合 + 门扇线落在门宽区间」。",
        "params": {"门宽": "= 最长段(门扇线)，夹到 door_w_double 上限",
                   "门宽范围": "[DOOR_LEAF_MIN, DOOR_LEAF_MAX) = [0.6, 3.0)m"},
        "pitfalls": [
            "门宽取 bbox 跨度会错：门垛 0.24m 短段把 1.0m 门扇撑到 1.3m、2.26m 撑到 2.3m。取最长段。",
            "门垛本身(最长≈0.34m)落进 [0.6,3.0) 之外，天然排除。",
            "门 = 墙被切断的 gap，不是 hole：门盒深>墙厚，difference 把墙切成两段。",
        ],
    },
    "门垛(jamb)": {
        "signature": "门符号折线里的短段，长 0.24m、最长≈0.34m。是门洞两侧墙体的收头，不是独立门。",
        "params": {"长": "0.24m", "最长段": "≈0.34m"},
        "pitfalls": ["见 door：门宽别用 bbox 跨度，否则门垛污染跨度。"],
    },
    "柱(column)": {
        "signature": "柱层(4.2柱/柱)上的填充矩形(LWPOLYLINE 闭合)。取包围盒中心 + 标准宽深 0.5×0.5。",
        "params": {"宽深": "column_w=0.5 / column_d=0.5(标准值)"},
        "pitfalls": [
            "柱通常只画在首层(结构柱贯通全高的假设)；逐层同 footprint，别指望每层都画。",
            "六教 C006 柱=INSERT(块引用)，需单独分类器分支(classifier='line')。",
            "c025/c028/c104/c114 的 4.1结构柱 层【有定义但 0 实体】：柱画在墙层里或没画，"
            "column_layer='' 是对的，别盲目补 '4.1结构柱'（补了也是 0 柱）。",
        ],
    },
    "楼梯井(stairwell)": {
        "signature": "一列短水平段(踏步, 0.8~3.0m)按 y 聚类成跑，>=4 段算楼梯。跑数定类型："
                     "1=直跑 2=双跑平行 >=3=双分式。",
        "params": {"踏步段": "0.8 <= L <= 3.0m 且近乎水平(min(|dx|,|dy|)<=0.02)",
                   "聚类": "|Δy|<=0.35 且 |Δcx|<=3.0"},
        "pitfalls": [
            "顶层(无上层楼板)不画楼梯，楼梯井只剩楼板洞。",
            "假阳性：深度<1.5m 的浅薄带(「⊓」符号平行线/栏杆/立面线)会被误判成楼梯井，"
            "c114 每层 28~30 个假井、c103/c104/c022/c009/c027 均 36~146 个。"
            "过滤：yTop-yBot >= 1.5m(真井单跑≈3m)。",
        ],
    },
    "台阶(entry stair)": {
        "signature": "⊓ 形折线(5 点多段线)，GB/T 50104 楼梯踏步符号。入口台阶在层 0。",
        "params": {"踏步高": "0.15m/级"},
        "pitfalls": ["室内楼梯(双跑/双分)由 stairwell 选型渲染，与入口台阶不同源。"],
    },
    "女儿墙(parapet)": {
        "signature": "单线墙(无平行近邻) or 顶层轮廓外扩生成环。翼楼屋面女儿墙是轮廓外真实墙段。",
        "params": {"厚": "parapet_t=0.5m(生成环宽)", "高": "parapet_h=0.9m"},
        "pitfalls": ["女儿墙从顶层 outline 外扩 0.5m 生成(含北边)，别从外墙边缘启发式识别(会漏北边)。"],
    },
    "洁具(fixture)": {
        "signature": "圆 r≈0.6m(蹲位/洗手盆)。资产管理图常见。",
        "params": {"半径": "≈0.6m"},
        "pitfalls": ["本 11 栋教学楼的墙层里未发现独立洁具图层，暂未启用；遇资产管理图再开。"],
    },
    "弧墙(arc / curve wall)": {
        "signature": "墙层上的 ARC(r >= CURVE_MIN_R) / ELLIPSE / SPLINE，以及 LWPOLYLINE 自带的 bulge 段。"
                     "三种曲线按几何分三类：大半径 → 曲墙(离散后进 walls)；半径落门扇区间"
                     "(DOOR_LEAF_MIN~CURVE_MIN_R) → 门扇开启弧(进 doors，由 floor.py 还原成门)；"
                     "小尺寸整圆 / 椭圆 → 符号(丢并计数)。",
        "params": {"离散步长": "CURVE_STEP_MM=250mm",
                   "曲墙门槛": "CURVE_MIN_R(半径)；SYMBOL_ELLIPSE_MAX_MM=1000mm(符号长半轴)"},
        "pitfalls": [
            "旧代码只认 LWPOLYLINE/ARC ⇒ c009 一层(学术报告厅)整圈外弧全丢：那张图把弧墙画成"
            "**成对平行曲线**(ELLIPSE 长半轴 14.15/15.70m + SPLINE 48~110 控制点)，漏一条就"
            "墙 union 碎成 19 块、轮廓塌成 33.6×60.1m 的单翼(192.7㎡)、其余各翼的墙被"
            "『质心距 outline >1m』全部滤掉。",
            "门扇弧**绝不能塞进 walls**：0.75m 的半径段会在每扇门的位置长出一堵假墙，"
            "还会把轮廓 union 顶出去。改塞 doors。",
            "c113(艺术楼) 实测：小尺寸椭圆符号丢 33 条、门弧『两端贴墙状态相同』丢 7 条 ——"
            "两条都只影响门/符号，**不影响楼板面积**(四档对照实测)。",
        ],
    },
    "楼板轮廓(floor outline)": {
        "signature": "两条路径，按 profile.classifier 分：LWPOLYLINE 楼走"
                     "`_derive_buffer_walls_and_outline`(墙带各自 buffer → union → blocks_of 分块 → "
                     "每块外环填实 → 与图纸填充轮廓比大小)；classifier='line' 楼走"
                     "`derive_line_walls_and_outline`(polygonize 取『被墙围住的面』∪ 墙实体 → 再把 >=7 点"
                     "的外沿折线各自首尾闭合拉出，实测 c009 F7 912.7㎡ 与图纸面积表 912.70 分毫不差)。",
        "params": {"楼板填充判据": "闭合折线 area/length > SLAB_RATIO=1.0 → 当图纸自带填充(楼板足迹)，不当墙",
                   "封缝半径": "p.outline_close_r(闭运算桥接墙带缺口/门洞)",
                   "内院开关": "p.keep_courtyard_holes(只对回字形平面的内院/天井为 true)",
                   "0.55 判据": "墙轮廓 >= 0.55×填充轮廓 → 取墙轮廓，否则回落到填充轮廓"},
        "pitfalls": [
            "★ keep_courtyard_holes 误用 = 把**整片楼板当内院留空**。c113(艺术楼) 平面是椭圆剧场 + 斜翼，"
            "外皮画成 33 点闭合折线，读图路径把「闭合且 A/P>0.25」判成**皮线**去配对成薄墙环 ⇒ "
            "环内整片楼板成了 hole、>45% 被当内院留空 ⇒ 交付成一张蕾丝：F3 432.9㎡ vs 图纸面积表 "
            "3754.52(只有 12%)。改 false + outline_close_r=0.6 → 3548.3㎡(−5.5%)，五层全部改善。"
            "⇒ 该开关只给 c054/c072/c073 那种回字形内院用，**普通房间/大厅平面一律 false**。",
            "★ outline_close_r 是**悬崖不是平台**，不是可调旋钮：c113 实测 r<=0.6 时 F0 停在 3896㎡，"
            "r>=0.8 一跳就是 7323㎡(冲过真值 6751 的 +8.5%)—— 某个 r 上跨越了真实开口。"
            "**宁短勿长**：短了是少画板，长了是凭空补板(geometry 里『墙角凹进去的楼板还是多了点』判例)。",
            "★ 通高大厅/剧场类平面，缺口不是参数问题：c113 F0/F1/F2 的图上只有柱网 + 观众席排线，"
            "围合墙压根没画 ⇒ 半径扫到 2.0m 也只能到真值的 54~58%，而 F3/F4 却已 −5%。"
            "要补必须另立具名口子(把图纸自带填充当本层楼板标记)，不能靠调参数。",
            "★ 别把面积缺口归因于『剔除误杀』：c113 四档对照(关掉 137 条踏步 + 14 条洁具 + 3 条中缝)"
            "实测面积只差 0.1㎡ —— 剔除的是排线/洁具，本来就不参与围合。",
            "多块楼层的交付：`outline` 是桥接出的单环(钥匙孔) + `outline_parts`；消费者 `floor_outline` "
            "优先 parts，所以 0.10m 的脖子不会进模型；QA 读的是 raw `outline`(这就是钥匙孔存在的理由)。",
        ],
    },
}


# =====================================================================
# 三、外部量具 —— 用图纸自己写的话判『认对没认对』
# =====================================================================

GAUGES = {
    "图纸自带面积表": {
        "在哪": "DXF 里的 ACAD_TABLE(0 图层)，用 `t.virtual_entities()` 取 TEXT/MTEXT 成对读；"
                "现成读法见 `backend/checks/_area_audit.py`。字段：楼层 / 建筑面积 / 使用面积 / 房间数。",
        "用法": "python -u backend/checks/_area_audit.py <楼号>   # 逐层对照；不带参数 = 全库排名",
        "为什么": "模型算的是『楼板足迹』、表给的是『建筑面积』，口径不同(差在墙厚外皮与退台屋面块)，"
                  "所以判据是『同量级 + 逐层趋势』而非『相等』；但它能一票抓住 c113 F3 那种 12% 的塌陷。",
        "坑": "模板行(100.00 之类占位)要跳过；图纸『楼层』1 基、模型 F 0 基；表里没有的层别硬凑。",
    },
    "图纸自带填充(楼板标记)": {
        "在哪": "墙层上「闭合且 area/length > SLAB_RATIO」的折线 —— 是画图人自己标的『这块是楼板』。",
        "用法": "c113 实测 1795.0/2368.3/2368.3/1795.0/299.5㎡。",
        "为什么": "通高大厅那种『图上没有围合墙』的楼板，只有这条例线还留着。",
        "坑": "★ 不能无脑并进楼板：同一形状 1795.0㎡ 在 c113 的 F0 是观众厅地板(该算)、在 F3 是"
              "通高屋面/空腔(不该算)，并进去 F3 会 +42%。判『填充是地板还是屋面』目前没有可靠判据。",
    },
    "图纸自带房间数": {
        "在哪": "面积表的『房间数』列，逐层 21/36/23/18/15(c113)。",
        "用法": "与交付 rooms 数对比。★ 注意 c113 交付 rooms=0/0/0/0/0 —— 识别一间的房间都没出。",
        "为什么": "房间数是唯一能暴露『房间层没接上』的独立量具(见 memory: 写好的函数不等于被调用的函数)。",
        "坑": "房间数与面积一样，只说明『表说有几间』，不说明『识别到了几间』——两边都要报。",
    },
}


# =====================================================================
# 三、可直接调用的判定函数 —— 「下次直接识别」的入口
# =====================================================================

def is_closed(pts, tol=1e-6):
    """折线是否闭合（首尾点重合）。"""
    return abs(pts[0][0] - pts[-1][0]) <= tol and abs(pts[0][1] - pts[-1][1]) <= tol


def longest_segment(pts):
    """折线最长段长度（门扇线 = 折线里最长的一段）。"""
    best = 0.0
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        L = math.hypot(dx, dy)
        if L > best:
            best = L
    return best


def is_slab(poly):
    """闭合多边形是否判定为「填充区/楼板」（面积/周长 > SLAB_RATIO）。"""
    from shapely.geometry import Polygon
    g = poly if isinstance(poly, Polygon) else Polygon(poly)
    if not g.is_valid or g.area <= 0.001:
        return False
    return g.area / g.length > SLAB_RATIO


def is_door(pts):
    """折线是否判定为「门符号」：不闭合 + 门扇线(最长段) ∈ [DOOR_LEAF_MIN, DOOR_LEAF_MAX)。"""
    n = len(pts)
    if n < 3 or is_closed(pts):
        return False
    longest = longest_segment(pts)
    return DOOR_LEAF_MIN <= longest < DOOR_LEAF_MAX


def is_door_symbol_pts(pts, tol=1e-6, axis_tol=0.02):
    """闭合环是否是「门符号」（门扇线 + 1~2 个门垛块的闭合多段线）。本地米坐标。

    为什么需要它：宿舍/公寓的门符号是 **闭合** 环路（门扇线 + 门垛块 + 摆回起点），与墙同图层。
    这类环既被 detect_doors 当门收走（其「最长段 = 门扇线」口径恰与符号一致），又被当墙送进
    配对/缓冲 —— 于是在门的位置长出一堵 ~1.3m 假墙正好把门盖住（用户「门夹在墙里看不到」根因）。
    建墙前用本判据把符号摘掉即可，门的检出不受影响。

    判据（三条同时满足；实测 c019/c034/c044/c045/c054/c080/c027 等 30 栋，门宽 0.6~1.5m 全合理）：
      1. 含 1~2 个门垛块：连续 4~5 点回到起点、各边 ∈ [DOOR_JAMB_MIN, DOOR_JAMB_MAX]；
      2. 除门垛块外还有一条 **轴对齐** 长段 ∈ [DOOR_LEAF_MIN, DOOR_LEAF_MAX) —— 门扇线。
         必须轴对齐：闭合标志会在「末点→首点」补一条回边（c019 是 1.556m 斜边），比门扇线还长，
         不滤掉就会把它当门扇 → 宽度/朝向全错；
      3. 该长段方向 = 门垛块的「短边轴」（门垛长边轴 = 墙法向）—— 门洞沿墙走向。

    不会误吞窗户：窗户画法是「墙线上 3~4 条平行线 / 细长矩形」，没有门垛块，第 1 条就不成立。
    """
    n = len(pts)
    if n < 5:
        return False
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    if max(max(xs) - min(xs), max(ys) - min(ys)) > DOOR_SYMBOL_SPAN_MAX:
        return False
    # 找门垛块。只标记「边」不标记「顶点」——c019 的闭位门扇线两端正好落在两个门垛块的顶点上，
    # 按顶点标会把门扇线一起剔掉，只剩开启位那条。
    boxes, box_segs = [], set()
    i = 0
    while i < n:
        hit = 0
        for k in (4, 5):
            if i + k >= n or math.hypot(pts[i + k][0] - pts[i][0],
                                        pts[i + k][1] - pts[i][1]) > tol:
                continue
            sides = [math.hypot(pts[i + j + 1][0] - pts[i + j][0],
                                pts[i + j + 1][1] - pts[i + j][1]) for j in range(k)]
            if all(DOOR_JAMB_MIN - DOOR_SYMBOL_TOL <= s <= DOOR_JAMB_MAX + DOOR_SYMBOL_TOL
                       for s in sides[:4]):
                bx = [pts[i + j][0] for j in range(k)]
                by = [pts[i + j][1] for j in range(k)]
                boxes.append((min(bx), min(by), max(bx), max(by)))
                box_segs.update((i + j) % n for j in range(k))
                hit = k
                break
        i += hit if hit else 1
    if not (1 <= len(boxes) <= 2):
        return False
    bw = boxes[0][2] - boxes[0][0]
    bh = boxes[0][3] - boxes[0][1]
    short_is_x = bw <= bh          # 门垛短边轴 = 沿墙走向；长边轴 = 墙法向
    if len(boxes) == 2:
        c1 = ((boxes[0][0] + boxes[0][2]) / 2.0, (boxes[0][1] + boxes[0][3]) / 2.0)
        c2 = ((boxes[1][0] + boxes[1][2]) / 2.0, (boxes[1][1] + boxes[1][3]) / 2.0)
        dx, dy = c2[0] - c1[0], c2[1] - c1[1]
        if abs(dx) < tol and abs(dy) < tol:
            return False
        horiz = abs(dx) >= abs(dy)
        if horiz != short_is_x:
            return False
        gap = abs(dx) if horiz else abs(dy)
        ext = bw if horiz else bh
        w = gap - ext
        return DOOR_LEAF_MIN - DOOR_SYMBOL_TOL <= w < DOOR_LEAF_MAX + DOOR_SYMBOL_TOL
    for i in range(n):
        if i in box_segs:
            continue
        j = (i + 1) % n
        dx, dy = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
        if min(abs(dx), abs(dy)) > axis_tol:
            continue
        L = math.hypot(dx, dy)
        if ((abs(dx) >= abs(dy)) == short_is_x
                and DOOR_LEAF_MIN - DOOR_SYMBOL_TOL <= L < DOOR_LEAF_MAX + DOOR_SYMBOL_TOL):
            return True
    return False


def classify_inner_wall(geom, outline, outer_t):
    """内墙判定：质心距轮廓 > outer_t * INNER_WALL_CENTROID_FACTOR。
    质心判据无死区(旧面积带 0.35m 比外墙环带 0.30m 宽造死区)；T 形内墙端头连外墙、
    质心仍在房间中部，不会被误判外墙。"""
    return geom.centroid.distance(outline.exterior) > outer_t * INNER_WALL_CENTROID_FACTOR


def cluster_floors(ys, gap=FLOOR_CLUSTER_GAP):
    """楼层聚类：把墙层 Y 坐标(顶点级，mm)按 gap 聚成楼层，返回升序中心列表。
    层间距 135000~203520mm 远大于 gap；屋顶女儿墙/踏步与主楼板高差 15000~45000mm 小于 gap。
    顶点法比质心法更稳(每实体多顶点投票)。用于推导 profile.floor_ys（层数错的楼靠这个修正）。
    """
    ys = sorted(float(y) for y in ys)
    if not ys:
        return []
    clusters = [[ys[0]]]
    for y in ys[1:]:
        if y - clusters[-1][-1] <= gap:
            clusters[-1].append(y)
        else:
            clusters.append([y])
    return [sum(c) / len(c) for c in clusters]


def describe():
    """打印构件库全貌（检查 / 交接用）。"""
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for name, spec in COMPONENTS.items():
        print(f"\n[{name}]")
        print(f"  签名: {spec['signature']}")
        print(f"  参数: {spec['params']}")
        for pit in spec["pitfalls"]:
            print(f"  坑: {pit}")
    print(f"\n[楼层聚类] gap={FLOOR_CLUSTER_GAP}mm, 层间距 135~204m 远大于 gap")
    for name, spec in GAUGES.items():
        print(f"\n[量具 · {name}]")
        for k in ("在哪", "用法", "为什么", "坑"):
            if spec.get(k):
                print(f"  {k}: {spec[k]}")
    print("\n（量具的用法：先跑外部量具拿到『图纸说应该是多少』，再比模型 —— "
          "只有量具能红，结论才算数；见 memory: 覆盖率型判据自造假绿 / 假几何报假缺陷）")


if __name__ == "__main__":
    describe()
