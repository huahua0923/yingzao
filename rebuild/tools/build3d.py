# -*- coding: utf-8 -*-
"""把 12 层重画平面**拉伸成三维白模**，出 OBJ / GLB / Blender .blend。

几何从哪来（**不自己判墙**）：
  · 墙   —— 直接吃 `redraw.geometry(floor)["walls"]`：**与审图同一个外环+内洞**，
    用户框出来的问题一旦改到重画，这里跟着改，不存在「两处各判一次墙」。
  · 柱   —— 同一份 `geometry()["cols"]`（`4.1结构柱` 的 INSERT 块展开）。
  · 楼板 —— `geometry()["plate"]`（墙带闭运算桥洞口→填洞→外环）＝整层楼面；顶层另加屋面板。
  · 门扇 —— `geometry()["doors"]` 里**两点直线**那一段（门扇线；开启弧是多点折线，不要）。
  · 楼梯 —— `geometry()["treads"]` 按连通簇聚成梯段，沿梯段方向排序后逐级抬升。
  · 拉伸 —— `trimesh.creation.extrude_polygon()`（库函数，多边形带洞 → 水密棱柱），
    本脚本只负责**摆高与装配**；出件由 Blender 无头导入 GLB 另存 .blend。

层高（**已裁定**）：地上 **11 层**，层高取自 `rebuild/构件库/参数.json` 的 `共用/层高`
（2026-10-15 用户令 = **3.5 m** ⇒ 地上总高 38.5 m）；地下 **B1 = 3.5 m**（−3.5…0）。
★ 层高是**参数表上的一个数**，改那里一处即可重出——本文件里**不许再写它的字面量**
（`gates/J-10.9-05_参数单一源.py` 会当场判红）。

★ 三样「示意值」（源图没有，是假设，**不是实测**，改这三个数即可重出）：
  `SLAB_M` 板厚 0.12 · `DOOR_H` 门扇高 2.1 · `RISER_M` 踏步抬升 0.15 + 踏步板厚 `TREAD_H`。
  ⇒ 门只有平面（无门高/无门洞），楼梯只用到踏步线的**平面次序**（踏高踏宽是假设）。
单位：源件 mm（INSUNITS=4）。三维里 1 单位 = 1 m（拉伸前 /1000），便于与标准对账。

★ 出件朝向：内部一律 **Z 朝上**；出 OBJ/GLB 前整场绕 X 转 −90°，使文件成为
  **Y 朝上**（glTF 规范 / SU / Blender 的默认口径）。判据 J-10.8-01 ⑫ 盯这一条。

输出：
  rebuild/05_build/build.json       每层实测账（墙/柱/板/门/踏步 面积、块数、z 区间）
  rebuild/05_build/c006_white.obj   出件（OBJ）
  rebuild/05_build/c006_white.glb   出件（GLB）
  rebuild/05_build/c006_white.blend 出件（Blender 场景，可打开精修）
用法：python rebuild/tools/build3d.py
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

import numpy as np
import shapely.geometry as sg
from shapely.affinity import scale as _sh_scale
from shapely.ops import unary_union
import trimesh

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import redraw as RD                                                      # noqa: E402
import recognize as R                                                    # noqa: E402
import parts_lib as PL                                                   # noqa: E402

OUT = os.path.join(ROOT, "05_build")
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

# ★★ 2026-10-15（#5A 补漏）：`共用/层高` **早就在参数表里**，可本行一直写着字面量 `4.0`
#   —— 参数表与本行构成两个估计器（铁律 018/174），而且 `J-10.9-05` 当时**看不见它**
#   （那份名单 `CONST` 里没有「层高」这条）⇒ 闸全绿而真源根本没被读。这是「判据名单漏掉主体
#   则永远绿」的原样重演（铁律 137/183）。现在名单已补上这一条，字面量不许再回来。
#   用户 2026-10-15 明令层高按 **3.5 m** 走（原 4.0）⇒ 只改参数表一处即可重出。
STOREY_M = float(PL.p("共用", "层高")) / 1000.0   # ★ 层高参数（地上）—— 唯一真源 = 参数表
BASEMENT_M = 3.5          # ★ 地下室层高（−3.5…0）★ 这一条**还没进参数表**（见 EXPORT 的未决条）

# ★ 示意值（源图没有；集中在这三行，便于一处改）
SLAB_M = 0.12             # 楼板厚
DOOR_H = 2.1              # 门扇高
DOOR_T = 0.05             # 门扇厚**名义值**（★ 现在只写进 build.json 的 schematic；几何不再用它，
                          #   门扇厚度改由源图实测：两长边间距 20~60 mm，实测恒 37.5 mm）
DOOR_LEAF_MIN_M2 = 0.008  # 门扇**真实足迹**下限；源图实测 0.0189~0.0274 m²，此处留足余量
DOOR_LEAF_MAX_M2 = 1.5    # 上限：比这大就不是一扇门了
DOOR_PAIR_MIN_MM = 20.0   # 退路：两条平行门扇线**成一对**的间距下限（窄于 20 mm 不是门扇）
DOOR_PAIR_MAX_MM = 60.0   # 上限（源图门扇厚实测 37.5 mm，两边留余量）
DOOR_PAIR_LEN_TOL = 0.02  # 成对的两条线长度差上限（比例）
DOOR_DUP_IOU = 0.2       # 同一扇门被源图画了两遍（实测错开 1.4 mm / 21.6 mm）⇒ 超此比例只留一片。
                         # 为什么是 0.2：实测「真·两片不同的叶」重叠恒 **0%**，
                         # 而源图重复画的两遍重叠 **42%**（错开 21.6 mm）与 **96%**（错开 1.4 mm）
                         # ⇒ 合法与重复之间是空的，取 0.2 不会误并真门。

# ★★ 2026-10-15 第三条路：「扇线＋开启弧」型单扇门（实测坐实，见 `door_polys` 的 ③）。
#   值一律从参数表读（#5A 口径：这里不许再留第二份字面量）。
DOOR_ARC_ON    = int(PL.p("门", "门扇_线弧_补建"))       # 开关【假设】0/1
DOOR_ARC_T_MM  = float(PL.p("门", "门扇_线弧_名义厚"))   # 名义厚【假设】mm

# ★ `door_polys` 每次调用的账（**每层算完就覆盖**，调用方读它打日志）。
#   为什么要有：修法里含两个「丢掉」的决定（辅助线、近重合叶）。判据只量重叠，
#   量不出「被丢掉」，所以必须让调用方有地方读到这个数（铁律 174：不静默）。
DOOR_AUDIT = {}
RISER_M = 0.15            # 踏步抬升（旧「薄板」版用的示意值；已被楼梯模块取代，只留作兜底参照）
TREAD_H = 0.05            # 踏步板厚（同上）
STAIR_PAR_GAP_MM = 6000.0  # 【实测】同一梯间两跑的 par 中心相距上限 —— 12 层全量：同井 ≤ 3128.0，跨井 ≥ 78510.0
STAIR_OFF_OVL = 0.8        # 【实测】两跑「并排」的判据：off 区间重叠 ≥ 短者的此比例（同井实测恒 1.000）

# ★★ 楼梯**模块**参数（2026-10-14 用户令「楼梯直接建模块替换」）—— 2026-10-15 #5A
#   「参数单一源」：**这四条现在一律从 `rebuild/构件库/参数.json` 读**。
#   原先它们在本行各写一份字面量（`=270.0` / `=120.0` / `=0.12` / `=150.0`），
#   而参数表里另有一份 ⇒ 两个估计器（铁律 018/174）：两边一致**证明不了**它是对的，
#   不一致要等 SU 的 `BBOX_mm` 才现形（而那时已经出完件了）。
#   ★ 名字一律保留：下面 40 多处引用**一行没改**；`export_contours.py:93-94` 还从本模块读
#     `PARAPET_H` / `ROOF_STAIR_H`，改名会连带改它。
#   ★ 代价（铁律 28）：读参数表这一步在 **import 期**执行 —— 参数表坏了是**当场死**（好事），
#     但「参数表坏了」与「脚本自己坏了」都表现为 rc≠0，要从 traceback 上分开。
RISER_TARGET_M = float(PL.p("楼梯", "踢面_目标")) / 1000.0   # 目标踏高【假设】= 反推级数的**输入**
GOING_MM       = float(PL.p("楼梯", "踏面"))                 # 踏面进深【实测】本套图恒 270.0
WELL_GAP_MM    = float(PL.p("楼梯", "梯井宽"))               # 双跑之间的梯井宽【兜底值】
LANDING_T_M    = float(PL.p("楼梯", "平台厚")) / 1000.0      # 平台板厚【假设】

# ★★ 顶部三件**源图没有**（无屋顶图/立面/剖面）⇒ 按规则推，是**假设**，必须与「照图建的」分开看。
#   2026-10-15 起三条落在 `参数.json::构件.顶部` —— 以前它们只活在这三行里，
#   **参数表上一条没有** ⇒ 对照页看不见「这三个数是推的」，而那正是最软的一段。
PARAPET_H    = float(PL.p("顶部", "女儿墙高")) / 1000.0   # 女儿墙高
PARAPET_T    = float(PL.p("顶部", "女儿墙厚")) / 1000.0   # 女儿墙厚（沿顶层楼板外轮廓向内收）
ROOF_STAIR_H = float(PL.p("顶部", "楼梯房高")) / 1000.0   # 顶楼楼梯房高（位置客观、**高是假设**）

# ★ 竖井（ASCII 键仍叫 `LIFT`）：源件在墙层上有**闭合矩形 = 井道内空轮廓**（每层 3 个、逐层同位，含地下1层）。
#   位置与井道净尺寸是**客观的**；**壁厚是假设值**（源图没有壁厚线）。井道顶/机房源图没有 ⇒ 不出。
LIFT_T_MM = float(PL.p("竖井", "井壁厚"))                 # 井壁厚【假设】

# ★★ 件的**参数来源**：把这几个参数的「值 + 标注」照抄进 `build.json`。
#   为什么要有它（铁律 018 的正面对策）：光在代码里「读同一个表」还是一种自证 ——
#   判据 `J-10.9-05` 要拿**两个独立读数**对账：`build.json`（出件那趟留下的）与
#   `参数.json`（判据当场读的）。两边不等 ⇒ 说明有东西在中间改了数（例如又混进一个
#   字面量、或参数表被改过而件没重出）——**这正是「两处一致」证明不了的那件事**。
#   `标注` 也一起记：`J-10.9-02` ⑤b 已经要求「件说自己是实测、表说是假设」这种脱钩要红。
_PARAM_SRC = (("共用", "层高"), ("楼梯", "踢面_目标"), ("楼梯", "踏面"), ("楼梯", "梯井宽"),
              ("楼梯", "平台厚"),
              ("顶部", "女儿墙高"), ("顶部", "女儿墙厚"), ("顶部", "楼梯房高"),
              ("竖井", "井壁厚"),
              ("门", "门扇_线弧_补建"), ("门", "门扇_线弧_名义厚"))
PARAM_PROV = {"%s/%s" % (c, n): {"值": PL.spec(c, n)["值"], "标注": PL.spec(c, n)["标注"]}
              for c, n in _PARAM_SRC}

# (层名, z底 m, 层高 m)
FLOORS = ([("地下1层", -BASEMENT_M, BASEMENT_M)]
          + [("%d层" % i, (i - 1) * STOREY_M, STOREY_M) for i in range(1, 12)])
TOP_M = 11 * STOREY_M     # 地上总高 = 11 × 层高（女儿墙/楼梯房另加，不在此）


# ------------------------------------------------------------------ 折线 → 多边形
def _poly(pts):
    """一串点 → 有效多边形（自交/退化用 buffer(0) 修；多块取最大）。"""
    if len(pts) < 3:
        return None
    try:
        p = sg.Polygon(pts)
        if not p.is_valid:
            p = p.buffer(0)
    except Exception:
        return None
    if p.is_empty:
        return None
    if p.geom_type == "MultiPolygon":
        p = max(p.geoms, key=lambda g: g.area)
    return p if (p.geom_type == "Polygon" and p.area > 0) else None


def _split(p):
    """任意多边形 → 单块列表（MultiPolygon 摊平）。"""
    if p is None or p.is_empty:
        return []
    return list(p.geoms) if p.geom_type == "MultiPolygon" else [p]


def wall_polys(v):
    """墙带（外环 + 内洞）→ 多边形列表。"""
    out = []
    for shell, holes in v["walls"]:
        try:
            p = sg.Polygon(shell, [h for h in (holes or [])])
        except Exception:
            p = _poly(shell)
        if p is None:
            continue
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty:
            continue
        out.extend(_split(p))
    return [p for p in out if p.area > 0]


def col_polys(v):
    """柱块折线 → 多边形列表（只留闭合出面的）。"""
    out = []
    for pts, _cl in v["cols"]:
        p = _poly(pts)
        if p is not None:
            out.append(p)
    return out


def slab_polys(v):
    """楼板轮廓：`geometry()["plate"]`（墙带闭运算桥洞口→填洞→外环）⇒ 整层楼面。
    ★ 不能拿墙带外环直接填洞：墙带在门窗处断开，实测填洞面积比 = 1.00（一点没填上）。
    ★ 盲区：内天井/中庭也是「洞」，会被一起填成楼板（不单独识别）。
    """
    out = []
    for shell in v["plate"]:
        p = _poly(shell)
        if p is not None:
            out.extend(_split(p))
    return out


def _seg_key(ls):
    """线段的无向规范化键（端点顺序无关；0.01 mm 取整）。"""
    a = (round(ls.coords[0][0], 2), round(ls.coords[0][1], 2))
    b = (round(ls.coords[-1][0], 2), round(ls.coords[-1][1], 2))
    return (a, b) if a <= b else (b, a)


def _parallel(a, b, tol=1e-3):
    """两条线是否平行（叉积按长度归一）。同向与反向都算平行。"""
    (x1, y1), (x2, y2) = a.coords[0], a.coords[-1]
    (u1, v1), (u2, v2) = b.coords[0], b.coords[-1]
    return abs((x2 - x1) * (v2 - v1) - (y2 - y1) * (u2 - u1)) <= tol * a.length * b.length


def door_polys(v):
    """门扇 → 多边形列表。

    ★★ 2026-10-15 改：以前是「门块里**每条两点直线**各自 buffer(DOOR_T/2) = ±25 mm」。
       这是**错的**，而且错得有两层：
         ① 一扇门在源图里是**一条 731.25 × 37.5 mm 的矩形**（缩放 1500 的门块）。
            旧法把**两条长边**各 buffer 成 50 mm 宽的条 ⇒ 两中心只差 37.5 mm
            ⇒ 相叠 12.5 mm，且门扇被建成 **87.5 mm 厚**（源图 37.5 mm，厚 2.3 倍）。
         ② 重叠是**同类内**的：`_split()` 只把**一个** MultiPolygon 摊平，
            从不给**一串**几何去重叠（铁律 196：形状抄了、主语没抄）。
        ⇒ 实测后果（`gates/J-10.8-00_contours.py` 判据 ⑫）：12 层共 **1388 对**门扇重叠。
        ⇒ 现在：先把同一层所有两点线段**缝成闭合轮廓**（`shapely.ops.polygonize`）——
          源图里一扇门的两条长边与端头**端点严格共点**，所以不需要块身份也能缝回来
          （`redraw.blocks_wcs` 走 `virtual_entities()`，块身份在那一层就丢了）。
          取**真实足迹**（面积落在 DOOR_LEAF_* 区间），厚度自然回到源图的 37.5 mm。

    ★★ 2026-10-15 又改（第二轮，实测驱动）：上一版把「缝不上的两点线」退回 buffer，
       结果 12 层还剩 **300 对** `退路×退路` 重叠。逐层量下来，缝不上的段有两类：
         · 长 **731.2** mm 且**有平行近邻**（40 条）⇒ 是**真门扇**，只是轮廓没闭合；
         · 长 **970 / 873 / 700 / 679** mm 且**一条近邻都没有**（28 条）⇒
           是门符号里的**辅助线**，实测离最近的叶 **1.3~7.6 m**（在房间中间，根本不在墙上）。
       还能量到源图把同一扇门**画了 3 遍**（同一段出现 x3）、以及**错开 1.4 mm 画两遍**。
       ⇒ 现在：① 逐字节相同的段**去重**；② 退路只认**成对**（平行、等长 2%、
          间距 20~60 mm）的两条线，用它们围出的**凸包**当门扇；③ 一条近邻都没有的
          一律**丢掉**（它们是辅助线，不是门）；④ 重叠超过一半的近重合叶只留一片。
       ★ 代价（铁律 028）：「丢掉」是个决定 —— 判据 ⑫ 只量「重叠」，量不出
         「一扇门被整条丢掉」。所以每次调用都把账记进 `DOOR_AUDIT`，
         由 `export_contours` 逐层印出来（不静默吞）。

    ★★ 2026-10-15 第三次改（第三条路）：上面那句「当辅助线丢掉」**判错了一半**。
       逐块实测（按块名取 `virtual_entities`——源流水线把块身份丢了，探针能拿回来）：
       全 12 层 754 个 `$DorLib2D$` 块里，`…00000002`(494) 与 `…00000130`(36) 是**矩形**双扇
       （每块 2 扇）；`…00000003`(188) 与 `…00000228`(36) 共 **224 块**画成
       「一条扇线 ＋ 一段弧」——扇线长只有四档 **970/870/700/680 mm**，且
       **弧半径与扇线长逐块精确相等（224/224）**，那就是开启弧 ⇒ **是门，不是辅助线**。
       ★ 上一轮拿「离最近的叶 1.3~7.6 m ⇒ 在房间中间」当判词是**参照物错**（铁律 192）：
         这种门画的是**开启状态**，扇线垂直于墙面、伸进房间，离别的门远本来就是常态。
       ⇒ 补出来的矩形进 `leaf`，由下面 ④ 去重；账里多一格 `arc_line`（不许静默）。
    """
    from shapely.ops import polygonize

    segs, seen = [], set()
    n_dup = 0
    for pts, _cl in v["doors"]:
        if len(pts) != 2:
            continue
        try:
            ls = sg.LineString(pts)
        except Exception:                                 # noqa: BLE001
            continue
        if ls.length <= 0:
            continue
        k = _seg_key(ls)
        if k in seen:                                     # 源图把同一扇门画了 N 遍
            n_dup += 1
            continue
        seen.add(k)
        segs.append(ls)

    leaf = []
    for p in polygonize(segs):
        if p.area <= 0:
            continue
        a = p.area / 1e6                                  # mm² → m²
        if DOOR_LEAF_MIN_M2 <= a <= DOOR_LEAF_MAX_M2:
            leaf.append(p)
    n_closed = len(leaf)                                  # 记账：闭合轮廓条数（配对/补弧之前）

    # 退路：轮廓缝不上、但**成对**的两条长边 ⇒ 凸包即门扇。一条近邻都没有的当辅助线丢掉。
    rest = [s for s in segs if 400.0 <= s.length <= 1800.0
            and not any(s.distance(p.boundary) < 1e-6 for p in leaf)]
    used, n_pair, n_drop = set(), 0, 0
    dropped = []                                          # ← 一条近邻都没有的那些段（③ 的候选）
    for i in range(len(rest)):
        if i in used:
            continue
        a = rest[i]
        hit = None
        for j in range(i + 1, len(rest)):
            if j in used:
                continue
            b = rest[j]
            if abs(a.length - b.length) > DOOR_PAIR_LEN_TOL * max(a.length, b.length):
                continue
            if not _parallel(a, b):
                continue
            d = a.distance(b)
            if not (DOOR_PAIR_MIN_MM <= d <= DOOR_PAIR_MAX_MM):
                continue
            hull = sg.MultiPoint(list(a.coords) + list(b.coords)).convex_hull
            if hull.geom_type != "Polygon":
                continue                                  # 共线 ⇒ 凸包退化成线，不是门扇
            if not (DOOR_LEAF_MIN_M2 <= hull.area / 1e6 <= DOOR_LEAF_MAX_M2):
                continue
            hit = (j, hull)
            break
        if hit is None:
            n_drop += 1
            dropped.append(a)
            continue
        used.add(i)
        used.add(hit[0])
        leaf.append(hit[1])
        n_pair += 1

    # ③ ★★ 2026-10-15 新增：「扇线＋开启弧」型**单扇门**（见 docstring 第三次改那一段）。
    #    这种门**没有闭合轮廓** ⇒ ① 收不到；而它在 ② 里必然是「一条近邻都没有」⇒ 被丢掉。
    #    ⇒ 沿扇线法向按**名义厚**张一个矩形（这批块本身没有厚度信息，量不出来）。
    #    ★ 矩形用四点自己拼、不用 buffer()：`cap_style` 的参数形状在各版 shapely 上不一致。
    n_arc = 0
    if DOOR_ARC_ON:
        half = DOOR_ARC_T_MM / 2.0
        for s in dropped:
            (x1, y1), (x2, y2) = s.coords[0], s.coords[-1]
            L = math.hypot(x2 - x1, y2 - y1)
            if L <= 0:
                continue
            nx, ny = -(y2 - y1) / L * half, (x2 - x1) / L * half
            q = sg.Polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
                            (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
            if not (DOOR_LEAF_MIN_M2 <= q.area / 1e6 <= DOOR_LEAF_MAX_M2):
                continue
            leaf.append(q)
            n_arc += 1

    # 源图把同一扇门错开 1.4 mm 画两遍 ⇒ 重叠超过一半的只留面积大的那片
    keep = []
    for p in sorted(leaf, key=lambda g: -g.area):
        dup = False
        for q in keep:
            if (p.bounds[2] <= q.bounds[0] or q.bounds[2] <= p.bounds[0]
                    or p.bounds[3] <= q.bounds[1] or q.bounds[3] <= p.bounds[1]):
                continue
            try:
                inter = p.intersection(q).area
            except Exception:                             # noqa: BLE001
                inter = 0.0
            if inter > DOOR_DUP_IOU * min(p.area, q.area):
                dup = True
                break
        if not dup:
            keep.append(p)

    DOOR_AUDIT.clear()
    DOOR_AUDIT.update({"seg": len(segs), "dup_seg": n_dup,
                       "closed": n_closed, "paired": n_pair,
                       "arc_line": n_arc, "dropped": n_drop,
                       "near_dup": len(leaf) - len(keep)})
    return [p for p in keep if p.area > 0]


def _basis(ang):
    """走向角（度）→ (走向单位向量 û, 法向单位向量 n̂)。off 沿 n̂、par 沿 û，与 recognize.line_key 同口径。"""
    ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    return (ux, uy), (-uy, ux)


def _xy(basis, o, p):
    (ux, uy), (nx, ny) = basis
    return (p * ux + o * nx, p * uy + o * ny)


def _rect(basis, o0, o1, p0, p1):
    """(off, par) 区间 → 平面矩形。四条边一律按 off/par 张成 ⇒ 与楼梯走向严格对齐。"""
    return sg.Polygon([_xy(basis, o0, p0), _xy(basis, o1, p0),
                       _xy(basis, o1, p1), _xy(basis, o0, p1)])


def _flight_runs(segs):
    """踏步线 → 跑列表：每跑 = 按 off 排好序的 line_key 列表（同 off 的重复线只留一条）。"""
    runs = []
    for g in R.group_flights(segs):
        ks = sorted((R.line_key(s) for s in g), key=lambda d: d["off"])
        keep = []
        for d in ks:
            if keep and abs(d["off"] - keep[-1]["off"]) < 1.0:
                continue                      # DXF 里整条重复的线（实测步距里出现 0.0 就是它）
            keep.append(d)
        if len(keep) >= 3:                    # ≥4 条线 = ≥3 级
            runs.append(keep)
    return runs


# ★ 楼梯模块的**记账**：撞上「双跑盒子越出锚区 ⇒ 退回单跑」那道闸的梯间在这里留一行。
#   铁律 158：判词不许静默 —— 退了就必须说退了，否则下一个人以为建的是双跑。
STAIR_DIAG = []

# ★ 栏杆的**记账**（2026-10-15）：每座梯间立了几条、因贴墙跳过几条、共几块。
#   铁律 158：跳过也必须说跳过 —— 否则下一个人以为栏杆本来就该少。
RAIL_DIAG = []

# ★★ 构件对照表的两组**形制读数**（2026-10-15，用户要的「构件库，可以比对」）：
#   `构件库/对照.json` 里「我们建的」那一列**不重算**，就是这里落下的读数 —— 页面只读它。
#   为什么不放到写 JSON 那一步再算：踏面/踢面/级数是**逐梯间**的（每座可不同），
#   出了 `stair_steps` 就没有 `k`/`g`/`riser` 这些中间量了；重算是第二个估计器（铁律 174）。
STAIR_FACT = []
SHAFT_FACT = []
_CUR = {"层": "", "h_m": 0.0}          # 当前正在建的那一层（读数要能点名是哪层）


def _rail_edges(basis, p0, w, gap, breadth, two_flight, s0, span, walls_u):
    r"""本梯间四条候选边里**真的立栏杆**的那几条 → `([(边, 朝向, 第几跑)], 边数, 贴墙数)`。

    ★ 为什么要把「站哪」与「建几何」**拆成两步**（2026-10-15 实测到的病）：栏杆是沿 par 铺的
      50 mm 窄带，而踏步块**横跨整个梯段宽** ⇒ 两者在平面上重叠。实测（入口闸 J-10.8-00 的 ⑫）：
      地下1层 61 对、8–11 层各 39 对，重叠面积恒 = 一个踏面 × 栏杆宽 = 270×50 = **13500 mm²**。
      判词是「同层同类共面 ⇒ SU 里会互相切面」—— 它在 SU 里真会让两块互切。
      ⇒ 踏步必须**在立栏的那一侧让出栏杆宽**（现实里踏步本来就不通到栏板里），
      所以顺序只能是：先定站位 → 按站位裁踏步 → 最后建栏杆。

    ★ 四条边逐条问墙：`side_is_walled` 说贴墙 ⇒ **不立**（立了就是把栏杆插进墙里，
      远看像多一道墙）；不贴墙 ⇒ 立。当前 `栏杆_问墙=0`（那把尺子在梯段上是瞎的，见参数.json）。
    """
    rail_t = PL._mm("楼梯", "栏杆宽")
    tol = PL._mm("楼梯", "栏杆_贴墙容差")
    ask_wall = bool(int(round(float(PL.p("楼梯", "栏杆_问墙")))))
    xy = lambda o, p: _xy(basis, o, p)                      # noqa: E731

    cands = [(p0, 1, 1), (p0 + w, -1, 1)]
    if two_flight:
        cands += [(p0 + w + gap, 1, 2), (p0 + breadth, -1, 2)]

    kept, walled = [], 0
    for pe, into, fl in cands:
        if ask_wall:
            probe = PL.rail_probe(pe, -into, tol, s0, s0 + span, xy)
            if PL.side_is_walled(probe, walls_u, tol):
                walled += 1
                continue
        kept.append((pe, into, fl))
    return kept, len(cands), walled


def _rail_blocks(basis, s0, span, g, k, riser, half, edges):
    r"""按**已定好的站位** `edges` 建栏杆 → `[(poly, z_rel_m, h_m)]`（与楼梯台阶同契约）。

    ★ 合并时底面取**这几级里最低那级的踏面顶**、高度补上跨过的高差 —— 这样块顶仍等于
      「最高那级踏面顶 + 栏杆高」，而块底不漏缝（只按最高那级取底会浮起一道台阶的空档）。
    """
    rail_h = PL._mm("楼梯", "栏杆高_白模")
    rail_t = PL._mm("楼梯", "栏杆宽")
    merge = max(1, int(round(float(PL.p("楼梯", "栏杆合并级数")))))
    xy = lambda o, p: _xy(basis, o, p)                      # noqa: E731

    blocks = []
    for pe, into, fl in edges:
        lo, hi = PL.rail_span(pe, into, rail_t)
        for j0 in range(0, k, merge):
            j1 = min(k, j0 + merge)
            if fl == 1:
                o0, o1 = s0 + j0 * g, s0 + j1 * g
            else:
                o0, o1 = s0 + span - j1 * g, s0 + span - j0 * g
            base = (j0 * riser) if fl == 1 else (half + j0 * riser)
            hh = rail_h + (j1 - j0) * riser
            # ★★ 参数次序：`rail_strips(off_a, off_b, par_lo, par_hi, …)` —— off 是**沿梯段的
            #   跑向**（o0/o1），par 是**梯段宽方向**上那 50 mm 的带（lo/hi）。
            #   第一版把两者写反了（270 传进 off），症状不是报错而是**栏杆转 90°**：
            #   实测 地下1层 栏杆成了 270(跑向) × 50(宽)，与踏步的 270(宽) × 50(跑向) 正交，
            #   于是同一片地方两条共面 ⇒ 入口闸 ⑫ 61 对重叠。轴对调不报错，只错形状。
            blocks += PL.rail_strips(o0, o1, lo, hi, base / 1000.0,
                                     hh / 1000.0, xy)
    return blocks


def stair_steps(v, h):
    r"""楼梯**模块** → `[(poly, z_rel_m, h_m)]`：每个梯间建一部双跑梯，逐级都是**实心块**。

    ★ 为什么重做（2026-10-14 用户报「楼梯不对」）：旧版把「墙层 ∩ 100<L<3000 ∩ 中点在锚区内」
      的线全当踏步，实测在 3层 西南梯间认下 57 条、其中真踏步只有 ~28 条 ⇒ 踏高被挤成 70 mm，
      平面还多出一圈碎板。现在踏步判据在 `recognize.group_flights` 里（要求同角度 + 共享一条边
      + 步距落在 [180,400]），实测 12 层共认下 964 条真踏步线。

    ★ 分得清「实测」与「假设」：
      实测 —— 每跑的**走向、梯段宽、平面位置、步距 270 mm**（全图恒定）；
      假设 —— **踏高**（`RISER_TARGET_M` 0.155）与**梯井宽**（只画一跑时的兜底 120 mm）。
      级数由层高**等分**定：k = round(h / 2 / RISER_TARGET) 级/跑，2k 级爬满层高，
      末级顶面正好落在层高线上（`2k·riser == h` 是构造出来的，不是凑的）。

    ★ 与源图的吻合度（实测复核）：3层 西南梯间 走向沿 x、梯段宽 1470、两跑相距 1590
      ⇒ 模块占地 3060 × 4710，与该锚区的实测 3060 × 4740 一致；
      该跑 14 条踏步线跨 13×270 = 3510，模块 13 级 × 270 = 3510 —— 两者同数。

    入参：`v["treads"]` = `[((x0,y0),(x1,y1)), …]`（DXF mm）；`h` = 层高 m。
    返回：`[(shapely.Polygon, z_rel_m, h_m)]`，`z_rel_m` 为该块**底面**相对层底的高度。
    """
    segs = [((float(s[0][0]), float(s[0][1])), (float(s[1][0]), float(s[1][1])))
            for s in (v.get("treads") or []) if len(s) == 2]
    runs = _flight_runs(segs)
    if not runs:
        return []

    # ---- 逐跑聚成**梯间**（并查集；判据 = 两跑「同角度 + 并排 + par 邻近」） ----
    # ★ 2026-10-14 实测换尺 —— 旧判据是「两跑**中点**相距 < 3000」，它把核心筒劈成了两座梯间：
    #   2层 中部核心筒那两跑的 off 区间**完全相同** (-117530.0, -113750.0)，par 中心相距 **3128.0**
    #   —— 只超旧阈值 128 mm ⇒ 并查集不并，同一座梯间被拆成两座「单跑梯间」。
    #   每座于是走 `others == []` 兜底（gap=120、breadth=2w+120=5360），各自围绕自己的 pc
    #   建一部**完整的双跑模块** ⇒ 两模块踏步块相距仅 388、重叠 2232；实测 2层 这类重叠对 **80 对**，
    #   重叠面积恒 **602640 mm²** ⇒ SU 把共面重叠多边形并成自交面 ⇒ 正式件 9 张
    #   「相邻顶点同坐标」的退化面（J-10.8-02 的 ⑧ 组，落在 2/3/4 层 STAIR）。
    #   换成一把有物理含义的尺子：**同角度** 且 **off 区间并排** 且 **par 中心邻近**。
    #   实测分档（12 层全量）：同井 |Δpar| ∈ {1585, 1588, 1590, 1734, 2962.7, 3128.0}；
    #   跨井 |Δpar| ≥ 78510.0 —— 那些跨井配对的 off 区间**也**相同，是楼**另一头**那座镜像梯间，
    #   所以只靠 off 重叠不足以分开，必须再加 par 邻近。阈值 6000 落在两档中间
    #   （距同井最大 1.9 倍、距跨井最小 13.1 倍）。
    #   ★ 「并对了」是可以验的：核心筒并成一座后 gap = |66270−63142| − 2620 = 508、breadth = 5748，
    #     第一跑落在 par [61832, 64452]、第二跑落在 [64960, 67580] —— 与那两跑**各自实测**的踏步线
    #     跨度逐位相同。旧写法只把钱花在其中一跑上，另一跑的位置却凭空多出一部梯。
    def _offspan(r):
        os_ = [d["off"] for d in r]
        return (min(os_), max(os_))

    def _parcen(r):
        return sum(d["par"] for d in r) / len(r)

    n = len(runs)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if abs(runs[i][0]["ang"] - runs[j][0]["ang"]) > 1e-6:
                continue                    # 不平行 ⇒ 不可能是同一座梯间的两跑
            (a0, a1), (b0, b1) = _offspan(runs[i]), _offspan(runs[j])
            if min(a1, b1) - max(a0, b0) < STAIR_OFF_OVL * min(a1 - a0, b1 - b0):
                continue                    # off 方向不错开 ⇒ 不是并排的两跑
            if abs(_parcen(runs[i]) - _parcen(runs[j])) > STAIR_PAR_GAP_MM:
                continue                    # par 方向离太远 ⇒ 是楼另一头的另一座梯间
            ra, rb = find(i), find(j)
            if ra != rb:
                parent[ra] = rb
    wells = {}
    for i in range(n):
        wells.setdefault(find(i), []).append(i)

    zones = [sg.box(z[0], z[1], z[2], z[3]) for z in (v.get("zones") or [])]
    h_mm = float(h) * 1000.0
    # 级数：层高按目标踏高等分给两跑 ⇒ 每跑 k 级，2k 级正好爬满 h。
    k = max(2, int(round(h_mm / (2.0 * RISER_TARGET_M * 1000.0))))
    riser = h_mm / (2.0 * k)                      # ⇒ riser·2k == h_mm（构造保证）
    half = riser * k                              # 中间平台标高 = 半层高
    land_t = min(LANDING_T_M * 1000.0, max(0.0, half - riser))

    zunion = unary_union(zones) if zones else None   # 本层锚区并集：判「模块装得下」用
    # ★ 栏杆问墙用：本层**墙带并集**（源图墙带，不 carve —— 栏杆只关心「这条边外面有没有墙」）
    walls_u = unary_union(wall_polys(v)) if v else None
    out = []
    for idxs in wells.values():
        ref = max((runs[i] for i in idxs), key=len)      # 参考跑 = 线最多（画得最全）的那一跑
        basis = _basis(ref[0]["ang"])
        gaps = [ref[i + 1]["off"] - ref[i]["off"] for i in range(len(ref) - 1)]
        g = sorted(gaps)[len(gaps) // 2] if gaps else GOING_MM   # 实测步距（中位数）
        # ★ `参数.json::楼梯/踏面_切规范档`（0/1，默认 0）= **开关**：置 1 就改用 `踏面_规范档`。
        #   为什么不做成「值可 null 的覆盖项」：`PL.p` 对 null 是**当场抛错**（那是给「数」定的
        #   防线，不许绕过），而开关的合法值恰好是 null ⇒ 只能另立一条 0/1 的开关。
        #   一改 `span = k*g` 跟着变 ⇒ 梯段可能顶到/够不到锚区，切完必须重跑并看 ⑫ 与越界告警。
        #   所以默认**必须**是 0；切了就在 stdout 打一行，免得「切了但没人看出来」。
        _gov_on = int(round(float(PL.p("楼梯", "踏面_切规范档"))))
        if _gov_on:
            _spec = PL.spec("楼梯", "踏面_规范档")
            if _spec["值"] is None:
                raise ValueError(
                    "楼梯/踏面_切规范档 已置 1，但 `踏面_规范档` 还是 null"
                    "（标的是「%s」）⇒ 先坐实再切；**不许悄悄退回实测**（那就成了切了没切一个样）"
                    "。出处：%s" % (_spec.get("标注"), _spec.get("出处")))
            print("    ★ 踏面按参数表切规范档：实测 %.4f → %.4f mm（span %.1f → %.1f）"
                  % (g, float(_spec["值"]), k * g, k * float(_spec["值"])))
            g = float(_spec["值"])
        # ★ 一跑的 `par` 是个**常数**：同一跑的踏步线跨度相同 ⇒ 中点沿自身方向的投影相同。
        #   所以梯段宽**不能**取 `max(par)-min(par)`（实测恒为 0，模块会退化成零宽的面）。
        #   要取**线长**：折断线只会把线切短 ⇒ 取最长的那条 = 满宽（实测 3层 西南 1470.0）。
        pc = sum(d["par"] for d in ref) / len(ref)   # 本跑的 par 中心
        w = max(d["L"] for d in ref)                 # 梯段宽（实测）
        span = k * g                                 # 一跑的水平投影长

        # 梯井宽：本梯间里另有跑就按**实测**间距（取最近的那一跑 = 双跑的另一跑），
        # 只有一跑就用兜底值。实测 3层 西南：两跑 par 中心相距 1590 = 1470 + 120。
        gap = WELL_GAP_MM
        others = [runs[i] for i in idxs if runs[i] is not ref]
        if others:
            far = min((sum(d["par"] for d in r) / len(r) for r in others),
                      key=lambda q: abs(q - pc))
            gap = max(60.0, abs(far - pc) - w)
        breadth = 2.0 * w + gap                      # 双跑 + 梯井的总宽

        # ---- 摆位：**两个方向一起搜** —— 沿 off 往哪端长（fwd）× 双跑铺在 par 哪一侧（pdir）----
        # ★ 为什么要加 pdir（2026-10-14 实测到的病）：旧版只搜 fwd，par 一侧**写死** `p0 = pc - w/2`
        #   ⇒ 模块只能往 par 正方向铺。1层 是入口层，源图**每座梯间只画了一跑**（实测 跑=10 锚区=10，
        #   每座梯间 `others` 全空 ⇒ 兜底 gap=120、breadth=3300），于是 1层 北西梯间实建盒子 par
        #   [97049.5, 100349.5]，而锚区 par 只到 98780 ⇒ 楼梯**穿出外墙 1569.5 mm**，
        #   成品 BBOX 从 84000 涨到 85350 —— 与 `su_obj_to_glb.py` 判词
        #   「平面尺寸对不上 129.3×85.3 m（期望 129.3×84.0）」逐位吻合。
        #   尺子只有一把：**占地与锚区相交面积**。铺不进去的那侧面积自然小 ⇒ 自动翻面；
        #   两侧都铺得进则面积并列，靠 `>` 取先者 ⇒ 先试 pdir=+1（= 旧版写法：参考跑就是
        #   **从本层地面起跑**的那一跑），旧行为一位不变。
        # ---- 本梯间的**归属锚区**（2026-10-15 实测到的病：整座模块会搬到别座梯间里去）----
        # 旧写法：候选位取自**全层所有锚区**、打分又是「与全层锚区的相交面积之和」
        # ⇒ 每座梯间都能整座搬进**另一座**梯间的锚区，只要那边 ins 高一点点。
        # 实测（3–7層 西侧那座，本跑 off[-50050.0,-46270.0]）：它自己的锚区 z04 与
        # 65 m 外 z09 的候选位 ins **逐位相同** —— 打印出来都是 3.5235239642e+07，
        # 只差最低位 1 ULP，`key >` 一比较就把整座模块从 x 46830.7 摆到 x 111660.0。
        # 3層 于是有**两份**同一座梯间（互差 260 mm）：54 对踏步互相重叠、面积恒 681200 mm²，
        # 入口闸 J-10.8-00 的红就是它。2層 同一座梯间却摆对了 —— ULP 的方向在那层翻了。
        # ⇒ 修法：先按「本跑中点落在哪个锚区」定归属，候选位与打分**只对本区**。
        #   本跑中点必须由 off/par 还原成世界坐标（`line_key` 只留 off/par/L，不留端点）。
        _mid = _xy(basis, (ref[0]["off"] + ref[-1]["off"]) / 2.0, pc)
        _mpt = sg.Point(_mid[0], _mid[1])
        own = [zp for zp in zones if zp.buffer(1.0).contains(_mpt)]
        if not own and zones:
            STAIR_DIAG.append(
                "★ 归属不安：本跑中点 (%.1f, %.1f) 不落在任何锚区内（锚区 %d 个）"
                "⇒ 退回全层锚区候选，可能与别座梯间抢位" % (_mid[0], _mid[1], len(zones)))
        pool = own if own else zones

        par_ok = None
        if pool:
            _ps = []
            for zp in pool:
                _xs, _ys = zp.exterior.coords.xy
                _ps += [basis[0][0] * _x + basis[0][1] * _y for _x, _y in zip(_xs, _ys)]
            if _ps:
                # ★ 注意这是**该层所有锚区的并集**的支撑区间，不是本梯间那一个 —— 所以它只能拦
                #   「整层级别」的离谱越界，拦不住「跑进隔壁房间」。真正挑位置的是上面那把尺子
                #   （相交面积），并集区间只是最后一道粗网。（本梯间的越界见 STAIR_DIAG 与探针。）
                par_ok = (min(_ps), max(_ps))

        # ★ 2026-10-14 实测到的第二处病：`s0` **写死在参考跑两端** ⇒ off 轴零自由度。
        #   7层 西侧梯间：锚区 off 长 6480，模块实占 off = span + w = 3510 + 2910 = 6420
        #   （**装得下**，两侧各余 30），可参考跑只画了 3780 ⇒ 从任一端往外长都多出 2640，
        #   实测越界 **2380.0 mm**（探针 stairzone：7层 最坏）。⇒ 把「锚区自己给出的对齐位」
        #   也放进候选：锚区 off 区间两端（含「远端 − 模块长」）。
        #   排序改成三级：**先「装得下」→ 再「仍贴着参考跑的老锚点」→ 再比相交面积**。
        #   这样：能装下就装下（修 7层 这类）；两个老锚点本来就装得下时，旧落位一位不变。
        anchor_s = (ref[0]["off"], ref[-1]["off"] - span)
        cand_s = list(anchor_s)
        for _zp in pool:
            _xs, _ys = _zp.exterior.coords.xy
            _os = [basis[1][0] * _x + basis[1][1] * _y for _x, _y in zip(_xs, _ys)]
            cand_s.append(min(_os))
            cand_s.append(max(_os) - (span + w))

        best = None
        for pdir in (1, -1):
            q0 = (pc - w / 2.0) if pdir > 0 else (pc - breadth + w / 2.0)
            for _ci, s0c in enumerate(cand_s):
                box = _rect(basis, s0c, s0c + span + w, q0, q0 + breadth)
                inside = sum(box.intersection(zp).area for zp in pool) if pool else box.area
                outa = box.difference(zunion).area if zunion is not None else 0.0
                # ★ `inside` 取整到 1 mm² 再进 key：两个候选位之间的 ins 差常只到浮点最低位
                #   （实测两区候选逐位相同、只差 1 ULP）⇒ 不取整就会靠噪声翻面（铁律 194）。
                #   1 mm² 对 6 m 级的楼梯摆位没有分辨力，取整丢掉的不是判据。
                key = (outa <= 1.0, _ci < 2, round(inside))
                if best is None or key > best[0]:
                    best = (key, s0c, pdir, q0)
        _, s0, pdir, p0 = best

        # ★ 硬闸：翻过面之后**仍**越出锚区就退回单跑（少一跑，总好过戳穿外墙），并逐条记账。
        #   上面那一步已经能翻面 ⇒ 正常情况走不到这里；走到了就是「这个梯间放不下双跑」这句话本身。
        two_flight = True
        if par_ok is not None and (p0 < par_ok[0] - 1.0 or p0 + breadth > par_ok[1] + 1.0):
            two_flight = False
            STAIR_DIAG.append(
                "单跑兜底：双跑盒子 par [%.1f, %.1f] 越出锚区 [%.1f, %.1f]（w=%.0f breadth=%.0f）"
                % (p0, p0 + breadth, par_ok[0], par_ok[1], w, breadth))
            p0 = pc - w / 2.0
            breadth = w

        # ★ 判词不许静默：搜完四条候选位后**仍然**装不下（模块比锚区大，如 1层 入口层
        #   东侧：锚区 2121×2050，模块要 6420×3300）⇒ 逐条记账，不假装它落对了。
        if zunion is not None:
            _fbox = _rect(basis, s0, s0 + span + w, p0, p0 + breadth)
            _out = _fbox.difference(zunion).area
            if _out > 1.0:
                STAIR_DIAG.append(
                    "★ 装不下：模块 off [%.1f, %.1f] × par [%.1f, %.1f]，越出本层锚区 %.0f mm²"
                    "（两跑=%s；锚区 %d 个）"
                    % (s0, s0 + span + w, p0, p0 + breadth, _out, two_flight, len(zones)))

        if pdir < 0 or not two_flight:
            print("    ★ 梯间 par 中心 %.1f：双跑%s（pdir=%+d；盒子 par [%.1f, %.1f]；锚区并集 %s）"
                  % (pc, "退回单跑" if not two_flight else "翻面", pdir, p0, p0 + breadth,
                     ("[%.1f, %.1f]" % par_ok) if par_ok else "无"))

        # ---- 栏杆**先定站位**（见 `_rail_edges` 的 docstring：踏步要让出栏杆宽，否则共面重叠）----
        rail_edges, n_side, n_walled = _rail_edges(basis, p0, w, gap, breadth,
                                                   two_flight, s0, span, walls_u)
        _rail_t = PL._mm("楼梯", "栏杆宽")
        f1 = [p0, p0 + w]
        f2 = [p0 + w + gap, p0 + breadth]
        for _pe, _into, _fl in rail_edges:
            _tg = f1 if _fl == 1 else f2
            if _into > 0:
                _tg[0] = _pe + _rail_t
            else:
                _tg[1] = _pe - _rail_t

        # ---- 第一跑：从 s0 起，沿 +n̂ 逐级抬升；每级都是**从楼面长上来的实心块** ----
        for j in range(k):
            box = _rect(basis, s0 + j * g, s0 + (j + 1) * g, f1[0], f1[1])
            for p in _split(box):
                if p.area > 0:
                    out.append((p, 0.0, round((j + 1) * riser / 1000.0, 4)))
        # ---- 中间平台：跨两跑，标高 = 半层高 ----（单跑兜底时 breadth == w ⇒ 只跨一跑）
        # ★ 平台的 par 分解**必须包含各跑的实际 par 区间端点**（`f1`/`f2`，已按栏杆站位裁过）。
        #
        #   第一版只按 (跑1) / (梯井) / (跑2) 拆三块 —— 治好了「平台侧块 vs 本跑末级踏步」那条**竖向接缝**
        #   （当时实测薄片 1620.0 × 0.034 = 27.664 mm²）。
        #   但**横向（沿 s 的那条）接缝**没治：平台的起边 `o = s0 + span` 与本跑末级踏步的远边
        #   `o = s0 + k*g` **在浮点里是同一根线**（`span = k*g`，同一次乘法），可两条线段的**端点不同**
        #   （踏步那条被栏杆裁成 `[p0+50, p0+w−50]`，平台那条是整段 `[p0, p0+w]`）。
        #   `export_contours` 把坐标取整到 0.1 mm 栅格（export_contours.py:269）⇒ **四个端点各圆一次**，
        #   落回两条相差 0.1 mm 的直线上 ⇒ 细片。
        #
        #   2026-10-15 实测（1層，闸 J-10.8-00 的 ⑫）：踏步×平台 **107.480 mm²**，
        #   细度 = 107.480 / 1520.1 = **0.0707 mm = 0.05·√2** —— 正是「各自独立圆到 0.1 栅格」
        #   的最大法向偏移。1層 两组（F01-STAIR-419×420、500×501），2/3/4 層各一组，
        #   另有栏杆条×平台 1.768/1.767 mm²（细度 0.05 mm）。
        #   ⇒ 处置：平台的 par 断点集合 = {整段端点} ∪ {`f1` 的两个端点} ∪ {`f2` 的两个端点}，
        #     于是那条**与踏步共用的子块**端点逐位相同 ⇒ 取整后仍是同一对点 ⇒ 交集面积严格 0。
        #
        #   代价（铁律 028，两次不同读数）：**平台环 196 → 456（+260）**，逐层
        #   地下1層 6→14、1層 22→50、2–4層 30→70、5–6層 24→56、7層 18→42、8–11層 3→7。
        #   ★ 旧值取自 `rebuild/_archive/before-parts-20261015-133022/06_su/contours/<层>.json`
        #     （那次留档用的就是**同一条三块规则**；栏杆不改平台分块 ⇒ 可比）。
        #   台阶/平台**面积一分不差**，只是平台的账再拆细；STAIR 环总数 1層 596、全 12 层 5502。
        #   ★ `f2` 在单跑兜底时是**反的**（`f2[0]=p0+w+gap > p0+breadth=p0+w`）⇒ 必须先夹到 [p0, p0+breadth]，
        #     否则会凭空多出一块跑出梯段宽的平台（`_rect` 不校验 p0<p1，错了也不报）。
        if land_t > 0:
            zl = round((half - land_t) / 1000.0, 4)
            hl = round(land_t / 1000.0, 4)
            _lo, _hi = p0, p0 + breadth
            _bp = sorted(({_lo, _hi, p0 + w, p0 + w + gap}
                          | {min(_hi, max(_lo, v)) for v in (f1[0], f1[1], f2[0], f2[1])}))
            for _qa, _qb in zip(_bp, _bp[1:]):
                if _qb - _qa <= 0:
                    continue                      # 单跑兜底：梯井那块宽度为 0，自动跳过
                box = _rect(basis, s0 + span, s0 + span + w, _qa, _qb)
                for p in _split(box):
                    if p.area > 0:
                        out.append((p, zl, hl))
        # ---- 第二跑：与第一跑反向（折返），从半层高再往上爬 k 级 ----
        # ★ 只有 `two_flight` 才建第二跑：单跑兜底时 `p0 + w + gap > p0 + breadth`，
        #   照建会得到一个绕反的假实体（`_rect` 不校验 p0 < p1，错了也不报）。
        if two_flight:
            for j in range(k):
                box = _rect(basis, s0 + span - (j + 1) * g, s0 + span - j * g,
                            f2[0], f2[1])
                for p in _split(box):
                    if p.area > 0:
                        out.append((p, round(half / 1000.0, 4),
                                    round((j + 1) * riser / 1000.0, 4)))
        # ---- 栏杆：按上面定好的站位建（踏步已在立栏那侧让出栏杆宽）----
        _rblk = _rail_blocks(basis, s0, span, g, k, riser, half, rail_edges)
        out.extend(_rblk)
        RAIL_DIAG.append({"边": n_side, "贴墙": n_walled, "立栏": len(rail_edges),
                          "块": len(_rblk),
                          "合并级数": int(round(float(PL.p("楼梯", "栏杆合并级数")))),
                          "问墙": int(round(float(PL.p("楼梯", "栏杆_问墙")))),
                          "墙带": ("空" if walls_u is None or walls_u.is_empty else "有")})
        # ★ 形制读数（对照.json 的「我们建的」一列）：逐梯间落一行，页面不重算。
        #   `踏面档` 记的是**这一跑实际用的是实测还是参数档** —— 切了档必须看得出来。
        STAIR_FACT.append({
            "层": _CUR["层"], "中点_xy": [round(_mid[0], 1), round(_mid[1], 1)],
            "踏面_mm": round(g, 3), "踢面_mm": round(riser, 3), "级数_每跑": k,
            "踏面源": ("参数档" if _gov_on else "实测"),
            "梯段宽_mm": round(w, 1), "梯井宽_mm": round(gap, 1),
            "梯段水平投影_mm": round(span, 1), "平台厚_mm": round(land_t, 1),
            "两跑": bool(two_flight), "栏杆_侧": n_side, "栏杆_贴墙": n_walled,
            "栏杆_块": len(_rblk),
            "梯间总宽_mm": round(breadth, 1), "半层高_mm": round(half, 1)})
    return out


def parapet_polys(v):
    """女儿墙：顶层楼板**外轮廓**向内收 `PARAPET_T` 的环带。
    ★ 源图无女儿墙（无屋顶图）⇒ 这是**按规则推**的，不是照图建的。
    """
    ring = []
    for p in slab_polys(v):
        q = p.buffer(-PARAPET_T * 1000.0, join_style=2)   # 2 = mitre：直角，不用圆角
        r = p if q.is_empty or q.area <= 0 else p.difference(q)
        ring.extend(_split(r))
    return [x for x in ring if x.area > 0]


def _zone_box(z):
    try:
        x0, y0, x1, y1 = float(z[0]), float(z[1]), float(z[2]), float(z[3])
    except Exception:
        return None
    return sg.box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def roof_stair_polys(v):
    """顶楼楼梯房：位置 = 顶层**楼梯锚区**（客观，来自源件文字锚）；高是假设值。"""
    return [b for b in (_zone_box(z) for z in v["zones"]) if b is not None and b.area > 0]


def lift_voids(v):
    """竖井**井道内空**多边形（源件墙层上的闭合矩形）。这是客观量，井壁由它内缩得到。"""
    out = []
    for rect in v["lifts"]:
        p = _poly(rect)
        if p is not None:
            out.extend(_split(p))
    return out


def lift_polys(v):
    """竖井井壁 = 井道矩形 − 内缩 `LIFT_T_MM` 的内空（环带）。

    ★ 源图只给井道**轮廓**、没给壁厚 ⇒ 壁厚是假设。报账时必须与井道内空**分列**
      （铁律 174：同一个量不许有两个估计器；这里「井道」与「井壁」是两个量，得分开放）。
    """
    out = []
    for p in lift_voids(v):
        q = p.buffer(-LIFT_T_MM, join_style=2)              # 2 = mitre：直角井壁
        r = p.difference(q) if (not q.is_empty and q.area > 0) else p
        out.extend(_split(r))
        # ★ 形制读数（对照.json 的「我们建的」一列）：**净尺寸是客观量、壁厚是假设**，
        #   两个量分开放（铁律 174）；判「是不是客运电梯井」的那句话在 `参数.json::竖井/判定`。
        _b = p.bounds
        _wg, _hg = _b[2] - _b[0], _b[3] - _b[1]
        SHAFT_FACT.append({
            "层": _CUR["层"], "净宽_mm": round(_wg, 1), "净高_mm": round(_hg, 1),
            "净面积_m2": round(p.area / 1e6, 3), "壁厚_mm": LIFT_T_MM,
            "壁厚源": PL.mark("竖井", "井壁厚"),
            "判定": PL.p("竖井", "判定"),
            "缩没了": bool(q.is_empty or q.area <= 0)})
    return [x for x in out if x.area > 0]


# ★ 门头墙的**记账**（同 `STAIR_DIAG` 的道理）：补出来的缺口里几个没门、几个超限被丢。
#   用户报的「门上面的缺失」如果修不干净，这里必须留下**读数**而不是一片安静（铁律 158）。
LINTEL_AUDIT = []


def lintel_module(v, h, doors=None, floor=None):
    """门头墙 → `[(poly, z_rel_m, h_m)]`（契约与 `stair_steps` 逐字段相同）。

    ★ 本函数**只喂不算**：几何全在 `parts_lib.lintel_module`（那边有完整的推导与出处）。
      这里负责的是——从源图把**墙带**与**门扇**取出来递进去。
      `doors` 允许外部传进来复用（`door_polys` 有 `DOOR_AUDIT` 记账副作用，
      每个消费者每层只该调**一次**）。
    ★ `floor` 只为了记账可读：`LINTEL_AUDIT` 里每一条必须说得出是**哪一层**，
      否则「这一层漏了 7 扇」在汇总表里找不到主语（铁律 174）。
    """
    out, diag = PL.lintel_module(wall_polys(v),
                                 doors if doors is not None else door_polys(v),
                                 float(h) * 1000.0)
    diag["层"] = floor
    LINTEL_AUDIT.append(diag)
    return out


def carve(polys, voids):
    """从一批多边形里抠掉洞口（井道内空）—— 井道要**贯穿楼板**，不能是实心块。"""
    if not voids or not polys:
        return list(polys)
    out = []
    for p in polys:
        q = p
        for vd in voids:
            if q.intersects(vd):
                q = q.difference(vd)
        out.extend(_split(q))
    return [x for x in out if x.area > 0]


def _extrude(polys, z0, h):
    """一批多边形 → 一个合并水密网格。

    ★ 顺序：**先把多边形缩到米（×0.001），再按米拉伸 height=h，最后抬到 z0 米**。
      第一版把「mm 拉伸(height=h) → 整体 ×0.001」写反了 ⇒ 每层只 4 mm 高、整栋塌成 47 mm
      煎饼；而当时印的 `z_max 44.00` 是从层表**声明**出来的、不是网格量出来的，所以**看着对**。
      ⇒ 单位换算只允许出现在拉伸**之前**的一处；高度一律以网格实测为准（见 main 的 z_measured）。
    """
    T = trimesh.transformations.translation_matrix([0.0, 0.0, z0])
    ms = []
    for p in polys:
        try:
            q = _sh_scale(p, xfact=0.001, yfact=0.001, origin=(0.0, 0.0))   # mm → m
            m = trimesh.creation.extrude_polygon(q, height=h, transform=T)
            ms.append(m)
        except Exception:
            continue
    return trimesh.util.concatenate(ms) if ms else None


def _area_m2(polys):
    return round(sum(p.area for p in polys) / 1e6, 2)      # mm² → m²


# ------------------------------------------------------------------ 主
def main():
    os.makedirs(OUT, exist_ok=True)
    scene = trimesh.Scene()
    rows = []
    zmax = -1e9
    # ★★ 2026-10-15 删掉了这里原先那段自查（原为「代码 `LIFT_T_MM` 与
    #   `参数.json::竖井/井壁厚` 必须相等，不等就抛」）。理由：单源之后它比的是
    #   **自己跟自己**（`LIFT_T_MM` 就是从那条参数读出来的）⇒ 恒等、**永远绿**。
    #   留着一道没有分辨力的闸，比删掉更坏 —— 看着像在守，实际什么都没守（铁律 137/158）。
    #   ★ 处置的代价（铁律 28）：「代码里哪天又混进一个字面量」这件事，`main()` 再也发现不了。
    #     改由两道承接：① 闸 `gates/J-10.9-05_参数单一源.py` **静态扫** `build3d.py` 源码；
    #     ② 本件把参数来源写进 `build.json::参数来源`，闸拿它与参数表当场对账（两个独立读数）。

    v11 = None
    V = {}
    for name, z0, h in FLOORS:
        v = RD.geometry(name)
        V[name] = v
        _CUR["层"], _CUR["h_m"] = name, h      # 形制读数要能点名是哪一层
        if name == "11层":
            v11 = v
        # ★ 井道先抠出来：墙带上那 3 个闭合矩形**整块都是墙**（实测在墙带内占比 1.00），
        #   照原样拉伸 = 竖井成了实心混凝土块、楼板也没有井口。抠出井道内空后，
        #   井壁作为**独立节点**（可点名、可数），楼板才有贯穿的井口。
        voids = lift_voids(v)
        wp0 = wall_polys(v)
        wp = carve(wp0, voids)
        cp = col_polys(v)
        lp = lift_polys(v)
        sp = carve(slab_polys(v), voids)
        dp = door_polys(v)
        parts = []
        # ★ 2026-10-15：`ptags` 与 `parts` **一一对应**（同长、同序）。加它是为了让下面能
        #   逐类量 z —— 原先每层只留一个聚合 `z_measured`，于是「梯栏杆按设计越层 0.9 m」
        #   与「墙偷偷高了 0.9 m」在 build.json 里**长得一模一样**，判据只能报一句
        #   「z 实测 ≠ 声明」（铁律 137/158：判据名单漏掉主体则永远绿）。
        ptags = []
        for polys, tag, hh in ((wp, "wall", h), (cp, "col", h), (lp, "lift", h),
                               (sp, "slab", SLAB_M), (dp, "door", DOOR_H)):
            m = _extrude(polys, z0, hh)
            if m is not None:
                scene.add_geometry(m, node_name="%s_%s" % (name, tag),
                                   geom_name="%s_%s" % (name, tag))
                parts.append(m)
                ptags.append(tag)

        # 门头墙：**逐块**拉伸（每块的底标高都是门洞高、高度 = 层高 − 门洞高，
        # 但块与块之间可以不同 ⇒ 与楼梯同理，不许按「一层一个常数」拉）
        lt = lintel_module(v, h, dp, floor=name)
        tln = []
        for poly, zrel, hm in lt:
            mt = _extrude([poly], z0 + zrel, hm)
            if mt is not None:
                tln.append(mt)
        if tln:
            mlin = trimesh.util.concatenate(tln)
            scene.add_geometry(mlin, node_name="%s_lintel" % name,
                               geom_name="%s_lintel" % name)
            parts.append(mlin)
            ptags.append("lintel")

        # 楼梯：逐级一个网格，最后并成一个节点（每级自带**底标高 + 拉伸高度**）
        tms = []
        for poly, zrel, hm in stair_steps(v, h):
            mt = _extrude([poly], z0 + zrel, hm)
            if mt is not None:
                tms.append(mt)
        n_step = len(tms)
        if tms:
            mstair = trimesh.util.concatenate(tms)
            scene.add_geometry(mstair, node_name="%s_stair" % name,
                               geom_name="%s_stair" % name)
            parts.append(mstair)
            ptags.append("stair")
            zmax = max(zmax, float(mstair.bounds[1][2]))

        # 顶层再加一块屋面板（板顶 = TOP_M，⚠ 停在层高线上，不把 z 区间顶出去）
        if name == "11层" and sp:
            mr = _extrude(sp, TOP_M - SLAB_M, SLAB_M)
            if mr is not None:
                scene.add_geometry(mr, node_name="roof", geom_name="roof")
                parts.append(mr)
                ptags.append("roof")

        if not parts:
            print("%-8s ★ 无实体" % name)
            continue
        zmax = max(zmax, max(float(m.bounds[1][2]) for m in parts))
        zlo = min(float(m.bounds[0][2]) for m in parts)
        zhi = max(float(m.bounds[1][2]) for m in parts)
        zmeas = [round(zlo, 3), round(zhi, 3)]
        # ★ 2026-10-15：逐类 z（键 = 类名，值 = 该类在本层的 [底, 顶] 并集）。
        #   契约：`ptags` 与 `parts` 必须**同长同序**（半路 append 忘带标签 ⇒ 当场抛，
        #   别让它静默少一类 —— 少的那一类正好是判据看不见的那一类，铁律 137）。
        if len(ptags) != len(parts):
            raise RuntimeError("%s ptags 与 parts 不同长：%d vs %d" % (name, len(ptags), len(parts)))
        zbc = {}
        for _tg, _mm in zip(ptags, parts):
            _lo, _hi = round(float(_mm.bounds[0][2]), 3), round(float(_mm.bounds[1][2]), 3)
            if _tg in zbc:
                zbc[_tg] = [min(zbc[_tg][0], _lo), max(zbc[_tg][1], _hi)]
            else:
                zbc[_tg] = [_lo, _hi]
        # 「谁把本层上界顶出声明」= 超出量最大的那一类。★ 这里**只记不判**：
        #   楼梯栏杆**按设计就是越过上层楼面**的（参数表 `构件/楼梯/栏杆高_白模`），
        #   所以「越层」本身不是错。判词在 J-10.8-01 —— 只许 `stair` 越，
        #   且越出的量必须等于参数表那个数（两个独立读数，铁律 018/174/192）。
        _over = sorted(((round(hi - (z0 + h), 3), tg) for tg, (lo, hi) in zbc.items()
                        if hi > z0 + h + 1e-6), key=lambda t: (-t[0], t[1]))
        mw = parts[0]
        Aw, Ac, As, Ad = _area_m2(wp), _area_m2(cp), _area_m2(sp), _area_m2(dp)
        Al, Av = _area_m2(lp), _area_m2(voids)
        rows.append({
            "floor": name, "z0": round(z0, 3), "h": round(h, 3), "z_measured": zmeas,
            # ★ 2026-10-15：把「哪一类顶出了本层声明」逐类落盘。
            #   `z_measured` 只是个聚合读数 —— 少了这三行，「梯栏杆按设计越层 0.9 m」
            #   与「墙偷偷高了 0.9 m」在 build.json 里长得**一模一样**（铁律 137/158）。
            "z_by_class": zbc,
            "z_extra_m": round(zmeas[1] - (z0 + h), 3),
            "z_extra_by": (_over[0][1] if _over else None),
            "n_wall": len(wp), "n_col": len(cp), "n_slab": len(sp), "n_door_leaf": len(dp),
            "n_door_block": len(v["doors"]), "n_step": n_step,
            "n_lift": len(lp), "n_lift_void": len(voids),
            "A_wall_m2": Aw, "A_col_m2": Ac, "A_slab_m2": As, "A_door_m2": Ad,
            "A_lift_m2": Al, "A_lift_void_m2": Av,
            "A_wall_uncarved_m2": _area_m2(wp0),
            "A_wall_recognized_m2": round(float(v["A_wall"]), 2),
            "faces_wall": int(mw.faces.shape[0]),
            "watertight_wall": bool(mw.is_watertight),
        })
        print("%-8s z[%.1f,%.1f] 量[%.2f,%.2f] 墙%3d(%.0f) 柱%3d(%.0f) 板%2d(%.0f) "
              "门扇%3d(%.0f) 井%2d(%.1f/空%.1f) 踏步%4d 水密=%s"
              % (name, z0, z0 + h, zmeas[0], zmeas[1], len(wp), Aw, len(cp), Ac,
                 len(sp), As, len(dp), Ad, len(lp), Al, Av, n_step,
                 parts[0].is_watertight))

    # ---- 收口：7层→8层 台阶的**屋面**（下层大底盘的顶）
    # ★ 为什么只收这一处：把 12 层的板两两相减，只有三处台阶（1→2 / 4→5 / 7→8）。
    #   拿 2024 DSM 逐处实测该区高度（位姿见 `_work/regbest_1层.json`）：
    #     7→8（4469 m²）影像中位 **26.0 m**、98% > 5 m ⇒ **真屋面**（模型 7层顶 28.0，同量级）；
    #     1→2（1102 m²）影像中位 8.3 m、各块 −0.9…19.0 m 互相打架 ⇒ **提取假象**（板被闭运算吹大），
    #     4→5（521 m²）影像中位 **4.3 m**（p10 −2.0）⇒ 也在**地面**上 ⇒ 同属假象。
    #   ⇒ 只给 7→8 加板；另两处**不加**（加了就是在影像明说「这儿是空地」的地方盖屋顶）。
    n_roof_step, A_roof_step = 0, 0.0
    if "7层" in V and "8层" in V:
        from shapely.ops import unary_union as _uu
        a = _uu(slab_polys(V["7层"]))
        b = _uu(slab_polys(V["8层"]))
        d = a.difference(b).buffer(0) if (not a.is_empty and not b.is_empty) else a
        rp = [g for g in _split(d) if g.area > 1e6]
        n_roof_step, A_roof_step = len(rp), _area_m2(rp)
        m = _extrude(rp, 7 * STOREY_M - SLAB_M, SLAB_M)        # 板顶 = 7层顶 = 7 × 层高
        if m is not None:
            scene.add_geometry(m, node_name="roof_step7", geom_name="roof_step7")
            zmax = max(zmax, float(m.bounds[1][2]))
        # ★ 影像读数（2026-10-15 用地基 464.66 m 的铺装面重重量过一遍，见
        #   `_scratch/dsm_ground_c006.py` ④ 与 `_scratch/dsm_roofs_c006.py`）：
        #   裙房那几块平屋面中位 **27.87~27.94 m**（4 块、合计 2143 m²），不是早先记的 26.0 m
        #   —— 旧那个数出自 `regbest_1层.json` 那套位姿，与现在这套（dE=1/dN=9、IoU 0.894）不同趟。
        #   层高 3.5 m 时本块板顶落在 24.5 m，比影像低 3.4 m；层高 4.0 m 时落在 28.0 m（差 0.1 m）。
        #   这条差**不在这里判**，只印出来（判词见参数表 `共用/层高` 的出处）。
        print("7→8 台阶屋面 %d 块 · %.1f m²（板顶 %.1f m；影像实测该区中位 27.9 m）"
              % (n_roof_step, A_roof_step, 7 * STOREY_M))

    # ---- 第三批：女儿墙 + 顶楼楼梯房（★ 规则推导，源图没有；单独成节点，便于分辨）
    ztot = zmax
    n_parapet = n_rs = 0
    if v11 is not None:
        pp, rp = parapet_polys(v11), roof_stair_polys(v11)
        n_parapet, n_rs = len(pp), len(rp)
        for polys, tag, hh in ((pp, "parapet", PARAPET_H),
                               (rp, "roof_stair", ROOF_STAIR_H)):
            m = _extrude(polys, TOP_M, hh)
            if m is not None:
                scene.add_geometry(m, node_name=tag, geom_name=tag)
                ztot = max(ztot, float(m.bounds[1][2]))
        print("女儿墙 %d 环带 · 顶楼楼梯房 %d 个（高 %.1f 假设）" % (n_parapet, n_rs, ROOF_STAIR_H))

    obj = os.path.join(OUT, "c006_white.obj")
    glb = os.path.join(OUT, "c006_white.glb")
    # ★★ 出件朝向（**规范口径**，不是随便写）：glTF 规范规定 **+Y 朝上**；OBJ 没有正式上轴，
    #   但 SU / Blender 的默认导入也是 **Y-up**。本脚本内部一律 **Z 朝上**（高度在 z），
    #   而 trimesh 是**原样**把内部坐标写进文件（不做 z-up→y-up）⇒ 谁**按规范读**谁就整栋躺倒。
    #   实测（Blender 5.2 无头读回）：修前 y=-47.0..3.5、z=15.0..99.0 ⇒ 高度跑到了 **−Y** 上，
    #   于是 render3d 的「正立面」实际是俯视、「俯视」实际是正立面（两张图对调，看着还挺像）。
    #   判据 J-10.8-01 ⑫ 专盯这一条（用**不经 trimesh** 的读者量，见该判据量具声明）。
    #   修法：出件前把整个场景绕 X 转 −90°（Z-up → Y-up）。此调用之后 scene 只用于写出，
    #   `build.json` 里的 z 仍是**模型内部**的高度，不受这行影响。
    scene.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2.0, [1, 0, 0]))
    # ★ OBJ/GLB 出件一律**字节层**写（铁律 79：文本模式写盘会把 LF 翻 CRLF）。trimesh 自管编码。
    scene.export(glb)
    scene.export(obj)
    meta = {
        "schema": "cdut3d-build3d/1",
        # ★★ 身份声明（2026-10-13 用户裁定）：本脚本拉的几何是**参照件**，不是正式交付件。
        #   正式件由用户在 SketchUp 里建（`rebuild/06_su/`）。之所以要机器可读地写死这一行：
        #   两份件长得像、文件名也像，谁在哪台机器上分不出来，就会拿错的那份去交。
        #   判据分工：`J-10.8-01` 量**本件**（尺子自检），正式件的判据另立。
        "role": "reference",
        "role_note": "参照件（Python 拉伸件）——由 CAD 底图+本仓代码生成的**对照物/尺子**，"
                     "**不是**正式交付件；正式件=用户在 SketchUp 里建的件，见 rebuild/06_su/",
        "storey_m": STOREY_M, "basement_m": BASEMENT_M, "top_m": TOP_M,
        "z_max_m": round(ztot, 3),
        "z_max_main_m": round(zmax, 3),
        "attach": {"parapet_m": PARAPET_H, "roof_stair_m": ROOF_STAIR_H,
                   "n_parapet": n_parapet, "n_roof_stair": n_rs,
                   "roof_step7_m2": round(A_roof_step, 2), "n_roof_step7": n_roof_step},
        "lifts": {"n_void": sum(int(r.get("n_lift_void") or 0) for r in rows),
                  "n_ring": sum(int(r.get("n_lift") or 0) for r in rows),
                  "A_void_m2": round(sum(float(r.get("A_lift_void_m2") or 0) for r in rows), 2),
                  "A_ring_m2": round(sum(float(r.get("A_lift_m2") or 0) for r in rows), 2),
                  "wall_t_m": LIFT_T_MM / 1000.0,
                  "note": "井道净尺寸/位置=源件客观；壁厚=假设"},
        "n_nodes": len(scene.geometry),
        "units": "m（源 mm 拉伸前 /1000）",
        # ★★ 2026-10-15 #5A：这几个几何参数的**值 + 标注**由出件那趟照抄下来
        #   ⇒ 判据 J-10.9-05 可以拿「件里记的」与「参数表现读的」两个**独立读数**对账。
        #   为什么要两个读数：光「代码从同一个文件读」还是自证（铁律 018）。
        "参数来源": PARAM_PROV,
        "参数表": "rebuild/构件库/参数.json（唯一真源）",
        "schematic": {"slab_m": SLAB_M, "door_h": DOOR_H, "door_t": DOOR_T,
                      "riser_m": RISER_M, "tread_h": TREAD_H,
                      "parapet_h": PARAPET_H, "parapet_t": PARAPET_T,
                      "roof_stair_h": ROOF_STAIR_H, "lift_t_mm": LIFT_T_MM},
        "scope": ("墙+柱+楼板+门扇+楼梯(示意)+竖井(净尺寸客观/壁厚假设)+女儿墙(推)"
                  "+顶楼楼梯房(推)+7→8台阶屋面(影像实测为真屋面)；"
                  "**窗：源件无窗图层（12 层只有 0/3轴线/4.1结构柱/4.2墙体/5面积/6房间号/7用途/8单位/Defpoints）⇒ 无窗可建**；"
                  "**一楼入口独立雨篷：源件与 2024 影像两处都查过，没有**——入口处的突出体是 1–7 层的体量，已在墙里"),
        "floors": rows,
    }
    with open(os.path.join(OUT, "build.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("\n主体顶参数 %.1f m（量 %.2f）；含附属总高实测 %.2f m" % (TOP_M, zmax, ztot))
    print("出件：%s\n      %s" % (obj, glb))
    # ★ 楼梯模块的记账要对用户可见（铁律 158：判词不许静默）。空表也要说「空」——
    #   「没有」与「没量到」是两句话。
    if STAIR_DIAG:
        print("★ 楼梯模块记账 %d 条：" % len(STAIR_DIAG))
        for _l in STAIR_DIAG:
            print("   " + _l)
    else:
        print("★ 楼梯模块记账 0 条：所有梯间双跑都铺进锚区了")

    # ★★ 门头墙的记账（铁律 158/174）：用户报的就是「门上面的缺失」，
    #    所以这里**必须**把「每扇门头顶有没有块」逐层印出来，包括漏了几扇、丢了几块。
    #    ★ 主语是**门扇**不是缺口 —— 「缺口 151 > 门扇 142」推不出「每扇门都有门头」。
    if LINTEL_AUDIT:
        print("★ 门头墙记账 %d 层（主语=门扇）：" % len(LINTEL_AUDIT))
        tot_l = tot_c = tot_lost = tot_drop = tot_thin = 0
        for _d in LINTEL_AUDIT:
            _l = int(_d.get("门扇") or 0)
            _c = int(_d.get("有门头") or 0)
            tot_l += _l
            tot_c += _c
            tot_lost += int(_d.get("漏了") or 0)
            tot_drop += int(_d.get("清边丢块") or 0)
            tot_thin += int(_d.get("清边致漏") or 0)
            print("   %-8s 门扇 %3d 有门头 %3d 漏 %d（清边前 %d ⇒ **清边致漏 %d**）"
                  " | 缺口 %d(含门 %d/无门 %d) 块 %d"
                  " | 清边丢块 %d 丢面积 %.0f mm² 裂块 %d（缝合后再丢 %d / %.0f mm²）"
                  " | 超限丢 %d"
                  % (_d.get("层"), _l, _c, int(_d.get("漏了") or 0),
                     int(_d.get("有门头_清边前") or 0), int(_d.get("清边致漏") or 0),
                     int(_d.get("缺口") or 0), int(_d.get("缺口含门") or 0),
                     int(_d.get("缺口无门") or 0), int(_d.get("块") or 0),
                     int(_d.get("清边丢块") or 0), float(_d.get("清边丢面积_mm2") or 0.0),
                     int(_d.get("清边裂块") or 0),
                     int(_d.get("缝合后清边丢块") or 0),
                     float(_d.get("缝合后清边丢面积_mm2") or 0.0),
                     int(_d.get("超限丢弃") or 0)))
        # ★ 漏掉的门逐一报形状：`[距墙 mm, 距最近够大的门头块 mm, 门扇面积 mm²]`
        for _d in LINTEL_AUDIT:
            _ms = _d.get("漏明细_距墙_距块_面积") or []
            if _ms:
                print("     漏明细 %s%s（贴墙 %d=门洞未开 / 离墙 %d=源图无墙）：%s"
                      % (_d.get("层"), "（仅前 20 条）" if _d.get("漏明细_截断") else "",
                         int(_d.get("漏_贴墙") or 0), int(_d.get("漏_离墙") or 0),
                         "; ".join("d墙%.0f d块%.0f S%.0f @(%d,%d)" % tuple(m) for m in _ms)))
        print("   Σ 门扇 %d 有门头 %d ⇒ **漏 %d**（其中清边致漏 %d；清边丢块合计 %d）"
              % (tot_l, tot_c, tot_lost, tot_thin, tot_drop))
    else:
        print("★ 门头墙记账 0 层：**没量到**（不是「没有」）")

    # ★ 楼梯形制：逐层印一行（踏面/踢面/级数/平台/栏杆），与 `参数.json` 的档并排看。
    #   铁律 158：这一列是「我们建的」，必须与「规范档」分开放，不许合成一个数。
    if STAIR_FACT:
        _gs = sorted({r["踏面_mm"] for r in STAIR_FACT})
        _rs = sorted({r["踢面_mm"] for r in STAIR_FACT})
        _ks = sorted({r["级数_每跑"] for r in STAIR_FACT})
        print("★ 楼梯形制 %d 座梯间：踏面 %s mm · 踢面 %s mm · 级数/跑 %s"
              " · 梯段宽 %s mm · 梯井宽 %s mm"
              % (len(STAIR_FACT), _gs, _rs, _ks,
                 sorted({r["梯段宽_mm"] for r in STAIR_FACT}),
                 sorted({r["梯井宽_mm"] for r in STAIR_FACT})))
        _nb = [r for r in STAIR_FACT if not r["两跑"]]
        if _nb:
            print("   ★ 其中退回**单跑**的 %d 座：%s"
                  % (len(_nb), "; ".join("%s@%s" % (r["层"], tuple(r["中点_xy"])) for r in _nb[:12])))
        print("   ★ 栏杆：%d 条立了（贴墙跳过 %d 条），共 %d 块"
              % (sum(r["栏杆_侧"] for r in STAIR_FACT),
                 sum(r["栏杆_贴墙"] for r in STAIR_FACT),
                 sum(r["栏杆_块"] for r in STAIR_FACT)))
    else:
        print("★ 楼梯形制 0 座：**没量到**（不是「没有梯」）")

    # ★ 竖井：净尺寸是客观量、壁厚是假设；「是不是电梯井」的判词必须印出来（不许静默绿）。
    if SHAFT_FACT:
        _u = sorted({(r["净宽_mm"], r["净高_mm"]) for r in SHAFT_FACT})
        _thin = [r for r in SHAFT_FACT if r["缩没了"]]
        print("★ 竖井 %d 个（%d 层 × 每层 %d 个）：净尺寸 %s mm · 壁厚 %.0f mm（%s）"
              % (len(SHAFT_FACT), len({r["层"] for r in SHAFT_FACT}),
                 len(SHAFT_FACT) // max(1, len({r["层"] for r in SHAFT_FACT})),
                 _u, LIFT_T_MM, SHAFT_FACT[0]["壁厚源"]))
        print("   ★ 判词：%s" % SHAFT_FACT[0]["判定"])
        if _thin:
            print("   ★ 壁厚内缩后**缩没了**的 %d 个（净尺寸小于 2×%.0f mm）" % (len(_thin), LIFT_T_MM))
    else:
        print("★ 竖井 0 个：**没量到**（不是「没有井」）")

    # ★ 构件对照表（页面只读它，数一律现算 —— 用户铁律）
    try:
        p, nb, ts = PL.write_duizhao([dict(_d) for _d in LINTEL_AUDIT],
                                     extra={"schema2": "门头墙逐层读数（build3d.py 现算）",
                                            "计数主语": "门扇（不是缺口）",
                                            "楼梯形制": [dict(_r) for _r in STAIR_FACT],
                                            "楼梯形制_schema": "逐梯间一行（build3d.stair_steps 现算）",
                                            "竖井": [dict(_r) for _r in SHAFT_FACT],
                                            "竖井_schema": "逐层逐个一行（build3d.lift_polys 现算）"})
        print("★ 对照表 %s（%d 字节 @ %s）" % (p, nb, ts))
    except Exception as _e:
        print("★ 对照表写失败：%s: %s" % (type(_e).__name__, _e))

    # ---- Blender 无头：导入 GLB 另存 .blend（给用户打开精修）
    if os.path.exists(BLENDER):
        bp = os.path.join(OUT, "to_blend.py")
        with open(bp, "w", encoding="utf-8", newline="\n") as f:
            f.write("import bpy\n"
                    "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
                    "bpy.ops.import_scene.gltf(filepath=r'%s')\n"
                    "bpy.ops.wm.save_as_mainfile(filepath=r'%s')\n"
                    % (glb, os.path.join(OUT, "c006_white.blend")))
        r = subprocess.run([BLENDER, "-b", "-P", bp], capture_output=True, text=True)
        tail = (r.stdout or "")[-400:]
        print("Blender rc=%d %s" % (r.returncode, "OK" if r.returncode == 0 else tail))
    else:
        print("★ Blender 不在 %s ⇒ 跳过 .blend" % BLENDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
