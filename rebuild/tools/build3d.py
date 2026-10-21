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
（2026-10-16 用户裁定「按甲定案 · 重算整条链」= **4.0 m** ⇒ 层表顶 44.0 m、含顶上三件 47.0 m）；
地下 **B1 = 3.5 m**（−3.5…0，硬编码在下面的 `BASEMENT_M`，**不是**参数表里的层高）。
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
sys.path.insert(0, HERE)
import building as B                                                     # noqa: E402
import redraw as RD                                                      # noqa: E402
import recognize as R                                                    # noqa: E402
import parts_lib as PL                                                   # noqa: E402

# ★ 2026-10-17：数据根 / 楼层表 / 出件名 / 门与顶层的画法改从楼栋档案读
#   （不设环境变量 = c006，FLOORS 与 TOP_M 与改之前逐位相同）。
ROOT = B.ROOT
_DRAW = B.profile().get("drawing", {})
DOOR_MODE = _DRAW.get("doors", "block")
OUT = os.environ.get("CDUT_OUT_DIR") or os.path.join(ROOT, "05_build")
# ★ 2026-10-19：`CDUT_TRIAL=1` = 8800 页面的「试算」——出件落沙盒目录，
#   **不写对照表、不调 Blender**（那两件都会碰真源或别人的读数账）。
TRIAL = os.environ.get("CDUT_TRIAL") == "1"
OUT_NAME = B.out_name()
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

# ★★ 2026-10-15（#5A 补漏）：`共用/层高` **早就在参数表里**，可本行一直写着字面量 `4.0`
#   —— 参数表与本行构成两个估计器（铁律 018/174），而且 `J-10.9-05` 当时**看不见它**
#   （那份名单 `CONST` 里没有「层高」这条）⇒ 闸全绿而真源根本没被读。这是「判据名单漏掉主体
#   则永远绿」的原样重演（铁律 137/183）。现在名单已补上这一条，字面量不许再回来。
#   ★ 2026-10-16 用户裁定「按甲定案 · 重算整条链」⇒ 层高回 **4.0 m**（参数表现值 = 4000）。
#     （2026-10-15 那版「明令 3.5 m」已作废。）⇒ 只改参数表一处即可重出。
STOREY_M = float(PL.p("共用", "层高")) / 1000.0   # ★ 层高参数（地上）—— 唯一真源 = 参数表
BASEMENT_M = 3.5          # ★ 地下室层高（−3.5…0）★ 这一条**还没进参数表**（见 EXPORT 的未决条）

# ★ 示意值（源图没有；集中在这三行，便于一处改）
SLAB_M = 0.12             # 楼板厚
STEP_H_M = 0.20           # 入口台阶/平台统一高度（用户 2026-10-21 口径）
CANOPY_T_M = 0.20         # 台阶上方雨檐厚度
CANOPY_Z_M = 3.00         # 雨檐底标高（相对本层地面）
DOOR_H = 2.1              # 门扇高
DOOR_T = 0.05             # 门扇厚**名义值**（★ 现在只写进 build.json 的 schematic；几何不再用它，
                          #   门扇厚度改由源图实测：两长边间距 20~60 mm，实测恒 37.5 mm）
DOOR_LEAF_MIN_M2 = 0.008  # 门扇**真实足迹**下限；源图实测 0.0189~0.0274 m²，此处留足余量
DOOR_LEAF_MAX_M2 = 1.5    # 上限：比这大就不是一扇门了
DOOR_PAIR_MIN_MM = 20.0   # 退路：两条平行门扇线**成一对**的间距下限（窄于 20 mm 不是门扇）
DOOR_PAIR_MAX_MM = 60.0   # 上限（源图门扇厚实测 37.5 mm，两边留余量）
# ★★ 2026-10-21（c116 用户「不要把门补到这么厚，做成打开的，和墙成 90 度，
#   门厚 30 mm」）：展示件统一把门扇画成**开启 90°**，从墙面向室内伸出，
#   门扇厚度按用户口径固定 30 mm。铰链端 / 开启侧由门洞与墙带现算，不手填坐标。
DOOR_OPEN_T_MM = 30.0
DOOR_OPEN_MAX_SPAN_MM = 1200.0
# ★★ 2026-10-18 门洞**跨墙深度**只许由**墙**定，不许由门的画法定。
#   症状（用户「为啥门上的墙你做成这个样子，不和六教一样」）：c004 南面 3 樘大门，
#   门符号框 2400×1320（1320 = 双扇开启弧的进深），`门洞 ∩ 墙带` 在入口那块**连成一片**的
#   墙网上保住 2.6 m² ⇒ 门洞抠掉 1.3 m 深、门头墙又原样补回来 1.3 m 深的一块厚板。
#   c006 那边墙线在门处断开，门头墙是**逐扇量墙厚**造的（中位 0.348 m²）—— 两种画法不该长出两种房子。
#   判据：跨墙深度 > 局部墙带宽的 DOOR_VOID_MAX_RATIO 倍 ⇒ 夹到「局部墙带宽」，
#   窗口位置取**墙材最多**的那一段（滑窗，不拍坐标）。墙带宽 = 2·面积/周长：
#   c004 实测外墙网 408 mm、角柱 206 mm（与轮廓 2A/P 中位 373 同量级）。
DOOR_VOID_MAX_RATIO = 1.5
DOOR_PAIR_LEN_TOL = 0.02  # 成对的两条线长度差上限（比例）
DOOR_DUP_IOU = 0.2       # 同一扇门被源图画了两遍（实测错开 1.4 mm / 21.6 mm）⇒ 超此比例只留一片。
                         # 为什么是 0.2：实测「真·两片不同的叶」重叠恒 **0%**，
                         # 而源图重复画的两遍重叠 **42%**（错开 21.6 mm）与 **96%**（错开 1.4 mm）
                         # ⇒ 合法与重复之间是空的，取 0.2 不会误并真门。

# ★★ 2026-10-15 第三条路：「扇线＋开启弧」型单扇门（实测坐实，见 `door_polys` 的 ③）。
#   值一律从参数表读（#5A 口径：这里不许再留第二份字面量）。
DOOR_ARC_ON    = int(PL.p("门", "门扇_线弧_补建"))       # 开关【假设】0/1
DOOR_ARC_T_MM  = float(PL.p("门", "门扇_线弧_名义厚"))   # 名义厚【假设】mm
# ★ 2026-10-20（c106 实测）：门必须挂在本层墙带上。图右侧 15 樘「门」离最近墙 18~28 m，
#   是画在 `4.2墙体` 层上的门窗表样例符号（17 个 1 m 方块），不是这栋楼的门。
DOOR_OFF_WALL_MM = float(PL.p("门", "扇离墙_上限"))      # 假设 mm

# ★ `door_polys` 每次调用的账（**每层算完就覆盖**，调用方读它打日志）。
#   为什么要有：修法里含两个「丢掉」的决定（辅助线、近重合叶）。判据只量重叠，
#   量不出「被丢掉」，所以必须让调用方有地方读到这个数（铁律 174：不静默）。
DOOR_AUDIT = {}
RISER_M = 0.15            # 踏步抬升（旧「薄板」版用的示意值；已被楼梯模块取代，只留作兜底参照）
TREAD_H = 0.05            # 踏步板厚（同上）
STAIR_PAR_GAP_MM = 6000.0  # 【实测】同一梯间两跑的 par 中心相距上限 —— 12 层全量：同井 ≤ 3128.0，跨井 ≥ 78510.0
STAIR_OFF_OVL = 0.8        # 【实测】两跑「并排」的判据：off 区间重叠 ≥ 短者的此比例（同井实测恒 1.000）
# ★★ 跨层借形（2026-10-16）的对齐容差：**同一个量不另立一个数**（铁律 018/103）。
#   「同一根梯井里两跑的错位」与「同一根梯井在相邻两层的错位」是同一个量 ——
#   都是「同一个梯井内部的错位」。实测：1层 西侧那根井，本跑中点 (117910.0, 62786.5)
#   到 2层 同一井中点 (115640.0, 64706.0) 相距 **2973 mm**；跨井最近 78.5 m。
#   ⇒ 直接沿用已经实测定的 6000（2973 的 2.0 倍、78510 的 1/13.1），不手打一个新阈值。
STAIR_ALIGN_MM = STAIR_PAR_GAP_MM

# ★★ 2026-10-18 用户令「楼梯上的开始是从门开始，很多楼梯现在是反着的」——
#   「本梯间的门」的判定半径 = **1.5 × 梯段宽**（梯段宽是实测值，不另立一个手打的数）。
#   为什么是「梯段宽」这个尺度：梯间的门开在**平台外沿那堵墙**上，平台进深 ≈ 一跑梯段宽，
#   门洞中心到「踏步包络+200」的锚区边 ⇒ 约 1.0~1.3 个梯段宽；隔墙另一侧房间的门
#   还要再隔一道房间进深。c004 实测（层1/2/3，离锚区）：最近门 1849/2456/1849…
#   —— 1.5×1880 = 2820 刚好把梯门收进来、把邻室门留在外面。
#   ★ 这一段是**规则**不是实测：梯段宽各楼不同，半径跟着走；哪栋楼翻错了先看这个数。
STAIR_DOOR_PAD_W = 1.5

# ★★ 梯间清空（2026-10-16 用户令「现在楼梯间就要比较的干净，只要是楼梯，就是刚才的
#   样子，没有其他的墙之类的」）—— 凡是落进**楼梯模块包络**里的墙/板，从墙带与楼板里扣掉。
#   ★ 为什么包络要**先内缩**再扣（不内缩就是错的，不是风格问题）：
#     实测 10层：梯段包络东沿 **62430**、梯井围合墙内表面 **62400** ⇒ 梯段比围栏还外探 30 mm。
#     按原包络硬扣 = 把**围合墙**削出一道 30 mm 的边 —— 正是 `J-10.8-00` 盯的「最短边」，
#     也就是「清梯间」这个动作会去破坏「墙闭合」那条判据。
#     内缩量取 50（> 30）⇒ 围合墙**一分不削**；而梯间里的假墙离包络边都 ≥ 1 m ⇒ 照样扣净。
#   ★ 这一条**先量后改**（`_scratch/probe_stair_clean_effect.py`，10层，同 PAD=50）：
#     墙带 122.11 → 115.81 m²（块 8 → 8，无 <0.05 m² 残块）；
#     围合墙那一圈（包络外 200 mm 环带）2.20 → 2.20 m² —— 不动；
#     楼板 916.94 → 900.94 m²（正好 16.00 m² = 3.20 × 5.00 的井口），最短边 180.3 mm 不变；
#     <60 mm 的边 358 → 354（少 4 条，**一条没多**）。
STAIR_CLEAR_PAD_MM = 50.0

# ★ 清空区那一刀会在结果环上留下**极短的边**：清空区的边界是**从楼梯包络推出来的矩形**，
#   与墙的真实几何无关 —— 它会从「离某个墙顶点 0.99~5.7 mm」的地方切过去，留下一小条墙。
#   实测（`_scratch/probe_staircut_edge_ab.py`，同输入开关两趟、同一把尺子）：
#     开关关上 = 2 条 < 6.25 mm 的环（就是用户裁定「留着」的两条 1层 LINTEL 收边）；
#     开关打开 = 12 条 ⇒ **这一刀新增 10 条**（1层 3.500/5.400、2–4层 0.990、5–6层 3.536/0.990、7层 5.700）。
#   ★ 把边界挪开**治不了**：7层那条边界附近的墙顶点分别在 0.714/5.714/10.0/13.0 mm，
#     间距（3~4.3 mm）小于阈值窗（6.25 mm）⇒ 平移边界只能把残条换个长度，避不开。
#   ⇒ 处置：**把短于「本仓自己声明的环_最短边下限」的边塌掉**（删掉该边的一个端点）。
#   代价（铁律 028）：被塌掉的顶点最多**移动这一个阈值（6.25 mm）**，而且只作用在
#     **这一刀切出来的**多边形上（开关关上时一个顶点都不动 —— 上面那个 A/B 就是它的守卫）。
#   这条阈值**不新立**：直接读 `参数.json::共用/环_最短边下限`（闸 `J-10.8-00` ⑯ 断言它与
#   闸内常数一致的那个值）—— 「细到这个程度就不算实体」是本仓已有的口径（铁律 018）。
RING_EDGE_MIN_MM = float(PL.p("共用", "环_最短边下限"))

# ★★ 2026-10-19：**零面积多边形不算实体**（拉伸前就丢，逐个记账）。
#   症状（实测 c006）：1/3/4/7 层各有一块 `wall` 是「3 点、面积 0.0 m²」的退化三角形，
#   拉出来是 8 个退化面 ⇒ 整层墙网格 `is_watertight=False`，闸 `J-10.8-01` ⑤ 报
#   「墙网格不水密」，而件里**看不出是哪一块**（旧口径连查都不查无内环的块 —— 铁律 137/158）。
#   ⇒ 判据只有一条：面积小于「最短边下限的平方」的块，连一块实体都撑不起来。
#   代价（铁律 028）：被丢的块合计面积 < 39.06 mm²，且**逐个落账**（`extrude_repair`），不静默。
EXTRUDE_AREA_MIN_MM2 = RING_EDGE_MIN_MM ** 2      # 6.25² = 39.06 mm²

# ★★ 2026-10-17：**裁梯块用的边界的量化步长（mm）**。
#   症状：`J-10.8-00` ⑫ 实测 `1层/F01-STAIR-157 与 158 重叠 48.976 mm²` —— 两块的
#   共同边一个在 96798.5308023、另一个在 96798.5（相差 0.0308 mm），沿 1590 mm 拉开
#   就是 49 mm² 的细条。**这不是墙画错了，是布尔运算把边界算到了墙顶点的浮点尾巴上**
#   （`126529.9997921` 这类坐标本来就是 126530）。量化回 0.1 mm 网格，两条边就重合。
#   ★ 只作用在**真被墙裁过的**梯块上；没相交的块一个顶点都不动。
#   ★ 步长必须远小于 `RING_EDGE_MIN_MM`（6.25 mm），否则量化本身会造出短边（⑪）。
CLIP_SNAP_MM = 0.1

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
# ★★ 2026-10-19 用户裁「全仓 3.5」⇒ 加**按栋覆盖**（与 `层高按栋` 同形）：
#   `构件/楼梯房高按栋/<栋id>` 有这一格就用它，没有就逐位退回 `顶部/楼梯房高`（默认 3000）。
#   右值里保留 `PL.p("顶部","楼梯房高")` 是**故意的**：闸 `J-10.9-05` ① 用 AST 认这个调用，
#   而默认值就是它 —— 覆盖只是另一条更具体的来源，不是第二个真源。
#   ★ 实际用了多少写进 `build.json::参数覆盖`（`参数来源` 仍如实记**表原值**，
#     两者不是同一个量，混在一起就回到「两个估计器」——铁律 018/174）。
_ROOF_STAIR_OVR = ((PL.load().get("构件") or {}).get("楼梯房高按栋") or {}).get(B.BID)
ROOF_STAIR_H = float((_ROOF_STAIR_OVR or {}).get("值", PL.p("顶部", "楼梯房高"))) / 1000.0
PARAM_OVERRIDE = ({"顶部/楼梯房高": {"值": float(_ROOF_STAIR_OVR["值"]),
                                    "来源": "构件/楼梯房高按栋/%s" % B.BID}}
                  if _ROOF_STAIR_OVR else {})

# ★★ 2026-10-18 用户令「楼梯间和电梯房一块儿做；有的顶楼它是没有楼梯的，就不要做这个东西」
#   ⇒ 顶部这两件**从实心盒改成结构体**：环带墙 + 顶板 + 门洞缺口。
#   为什么改：原先 `roof_stair_polys()` 是 `_extrude(zone_box, TOP_M, 3.0)` ——
#   一个 bbox 直接实心拉 3 m，出 24 个面，看着像盒子不像房子（用户「就是没有」）。
#   ★ **做不做由源件说**：顶层识别件里有 `stair_zones` 才建楼梯间、有 `lifts` 才建机房；
#     两样都没有 ⇒ 这件传回空表，**不出件也不报错**（那是「这栋没有」，不是「我没量到」）。
#   ★★ 这**覆盖** 2026-10-17 那条「不要屋顶的电梯塔楼了」—— 那条当时针对的是实心盒。
ROOF_ROOM_T      = float(PL.p("顶部", "屋面房间墙厚")) / 1000.0   # 环带墙厚【假设】
ROOF_LIFT_H      = float(PL.p("顶部", "电梯机房高")) / 1000.0     # 电梯机房高【假设】
ROOF_ROOM_DOOR_W = float(PL.p("顶部", "屋面房间门宽")) / 1000.0   # 门洞净宽【假设】
ROOF_ROOM_DOOR_H = float(PL.p("顶部", "屋面房间门高")) / 1000.0   # 门洞净高【假设】
#   ★ 2026-10-19：楼梯间外皮改从墙带内洞取（见 `_drawn_room_outer`）。这条是**抓错房间的闸**：
#     房间外皮最多比梯段锚区大出 2.0 m；超过 ⇒ 认到的不是这间房（实测 5层同一个墙带里
#     有个 952 m² 的大堂也包住锚区中心，第一版就把楼梯间建成 56×37 m 的整层罩子）。
ROOF_ROOM_MAX_GROW_M = 2.0

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

# (层名, z底 m, 层高 m)  —— 层名不再写死：档案说几层就几层（c006 = 11 层 + 地下1层）
_GROUND = B.floor_names()
# ★ 2026-10-17：地下层**名字**也从档案读（c006「地下1层」/ C001「D1」）。
#   原来写死「地下1层」⇒ 别的楼档案写 D1 时 windows.json 与本文件的层名对不上。
_BASE = B.profile().get("basement")


def _ground_heights(names):
    """地上**逐层**层高（m）。真源仍是参数表：`构件/层高按栋/<栋id>`。

    ★ 2026-10-19（用户令「你先改001，看看怎么改，窗户不管」）：原先每层都取
      `共用/层高` 一个数（4000），而 c001 的用户手建件 `ts4.skp` 实测首层板
      底 **6000**、其上各层 4000（水平面标高 6000/6600 一片 11753 m²，10.6/10.8、
      14.6/14.8、18.6/18.8、22.6/22.8 各有 200 mm 厚板）——一层一个数。
      这不是「再立一个估计器」：没有按栋条目的楼栋**逐位**退回 `共用/层高`，
      c005/c006 的 FLOORS 与改之前一模一样（4.0 在二进制里是精确值，累加不变）。
      条数对不上**抛异常**，不猜（铁律 199：「没写」与「写错了」不许同形）。
    """
    blk = (PL.load().get("构件") or {}).get("层高按栋") or {}
    spec = blk.get(B.BID)
    if not spec:
        return [STOREY_M] * len(names)
    vals = [float(v) / 1000.0 for v in spec["值"]]
    if len(vals) != len(names):
        raise AssertionError(
            "参数.json 构件/层高按栋/%s 给了 %d 个层高，而档案 floor_names 是 %d 层 %s"
            % (B.BID, len(vals), len(names), names))
    return vals


_H = _ground_heights(_GROUND)
_Z, _z = [], 0.0
for _h in _H:
    _Z.append(_z)
    _z += _h
FLOORS = (([(_BASE, -BASEMENT_M, BASEMENT_M)] if _BASE else [])
          + [(nm, _Z[i], _H[i]) for i, nm in enumerate(_GROUND)])
TOP_FLOOR = B.top_floor()                    # 顶层名（c006「11层」/ c005「5层」）
TOP_M = sum(_H)                              # 地上总高（女儿墙/楼梯房另加，不在此）
# 地上层**顶**标高（m，相对 ±0）：`_Z[i] + _H[i]`。7→8 台阶屋面/裙房屋面取它，
# 不再写 `7 * STOREY_M` —— 那句话只在「每层同高」时等于层顶。
_GROUND_TOP = [_Z[i] + _H[i] for i in range(len(_H))]
# ★ 2026-10-17：`build.json::scope` 是**声明**，随楼栋走。原来这句话写死在出件那一段里，
#   做 c005 时它照样印着「12 层」「7→8 台阶屋面」—— 声明与件不符（铁律 017/018）。
#   档案没写 scope 的楼栋（c006）逐字退回原句 ⇒ c006 的 build.json 一个字节都不变。
SCOPE = B.profile().get("scope") or (
    "墙+柱+楼板+门扇+楼梯(示意)+竖井(净尺寸客观/壁厚假设)+女儿墙(推)"
    "+顶楼楼梯房(推)+7→8台阶屋面(影像实测为真屋面)；"
    "**窗：源件无窗图层（12 层只有 0/3轴线/4.1结构柱/4.2墙体/5面积/6房间号/7用途/8单位/Defpoints）⇒ 无窗可建**；"
    "**一楼入口独立雨篷：源件与 2024 影像两处都查过，没有**——入口处的突出体是 1–7 层的体量，已在墙里")


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
    """任意几何 → 单块 Polygon 列表。

    ★ 2026-10-21：墙轮廓拉直后，布尔差集可能返回 Polygon / MultiPolygon /
    GeometryCollection 的混合。旧版只摊平 MultiPolygon，GeometryCollection
    会原样流进 `_drop_short_edges`，随后读 `.exterior` 当场崩溃。
    这里递归摊平，只保留有面积的 Polygon；非面几何明确丢弃。
    """
    if p is None or p.is_empty:
        return []
    if p.geom_type == "Polygon":
        return [p] if p.area > 0 else []
    if p.geom_type in ("MultiPolygon", "GeometryCollection"):
        out = []
        for part in p.geoms:
            out.extend(_split(part))
        return out
    return []


_TERRACE_CACHE = None
_TERRACE_MTIME = 0.0


def terrace_polys(floor):
    """该层标了**「露台」**的分区 → 多边形列表。

    从哪来：`02_recognize/语义.json`（`recognize_semantics.py` 把源图 `5面积` 层的
    「露台」文字挂到 `楼板 − 墙带` 的分区上）。**本函数不判露台**，只读识别结果。

    ★ 为什么顶层要拿它扣屋面（2026-10-19 用户「阳台、屋檐」+ ts4 交叉验证）：
      c001 5 层两处露台各 55.7 m²（13.4×4.7 m），图上写得明明白白；手建件 ts4 在这
      两处**上方没有任何水平面**（无屋顶），识别件却把整层楼板 1899.5 m² 原样拉成
      屋面板 ⇒ 露台被盖成了一间房。这是「识别件每层整块板」与「真建筑」最大的差别之一。

    ★ 盲区：缺 `语义.json` ⇒ 返回空并**印一行**（不许静默当成「本栋没有露台」）；
      只处理**顶层**（下层的露台，上一层多半本来就没盖到，实测 c001 4 层露台即属此类）。
    """
    global _TERRACE_CACHE, _TERRACE_MTIME
    if _TERRACE_CACHE is None:
        p = os.path.join(ROOT, "02_recognize", "语义.json")
        _TERRACE_CACHE = {}
        _TERRACE_MTIME = os.path.getmtime(p) if os.path.exists(p) else 0.0
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
                for fl in d.get("层") or []:
                    ps = [_poly(r["ring"]) for r in (fl.get("房间") or []) if r.get("露台")]
                    _TERRACE_CACHE[fl.get("层")] = [q for q in ps if q is not None]
            except Exception as e:                                     # noqa: BLE001
                print("★ 露台识别读取失败（%s）⇒ 顶层不扣露台" % e)
        else:
            print("★ 露台识别缺件（%s）⇒ 顶层不扣露台" % p)
    # ★ 静默过期闸：源图改了而语义表没重跑 ⇒ 露台还是旧的那几块（件会全绿）。
    _dxf = os.path.join(ROOT, "01_cad", "raw", "%s.dxf" % floor)
    if _TERRACE_MTIME and os.path.exists(_dxf) and os.path.getmtime(_dxf) > _TERRACE_MTIME:
        print("★ 露台识别**过期**：%s 比 %s 新 ⇒ 先跑 recognize_semantics.py" % (_dxf, "语义.json"))
    return _TERRACE_CACHE.get(floor) or []


_VOID_CACHE = None
_VOID_MTIME = 0.0


def _void_table():
    """读 `02_recognize/挑空.json`（`recognize_voids.py` 从**对照件**量出来的）。

    ★ 本函数不判挑空：源 DXF 没有任何标注能给出挑空（无该图层），唯一证据是对照件。
      缺件/读失败都**印一行**，不许静默当成「本栋没有挑空」（铁律 158）。
    """
    global _VOID_CACHE, _VOID_MTIME
    if _VOID_CACHE is None:
        p = os.path.join(ROOT, "02_recognize", "挑空.json")
        _VOID_CACHE = {"层": {}, "屋面": []}
        _VOID_MTIME = os.path.getmtime(p) if os.path.exists(p) else 0.0
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
                for fl in d.get("层") or []:
                    ps = [_poly(h["ring"]) for h in (fl.get("洞") or [])]
                    ps = [q for q in ps if q is not None]
                    if fl.get("层") == "屋面":
                        _VOID_CACHE["屋面"] = ps
                    elif ps:
                        _VOID_CACHE["层"][fl.get("层")] = ps
                ref = (d.get("读法") or {}).get("对照件")
                if ref and os.path.exists(ref) and os.path.getmtime(ref) > _VOID_MTIME:
                    print("★ 挑空识别**过期**：%s 比 %s 新 ⇒ 先跑 recognize_voids.py"
                          % (ref, "挑空.json"))
            except Exception as e:                                     # noqa: BLE001
                print("★ 挑空识别读取失败（%s）⇒ 楼板不扣挑空" % e)
        else:
            print("★ 挑空识别缺件（%s）⇒ 楼板不扣挑空" % p)
    return _VOID_CACHE


def void_polys(floor):
    """该层**楼板**要扣的挑空（只读识别结果）。"""
    return list(_void_table()["层"].get(floor) or [])


def roof_void_polys():
    """**屋面**自己的挑空 —— 与楼板洞分开：
    ts4 屋面洞 327.1 m² 比 5 层楼板洞 428.5 m² 小，拿楼板洞当屋面洞会多开 101 m²。"""
    return list(_void_table()["屋面"] or [])


def wall_polys(v):
    """墙带（外环 + 内洞）→ 多边形列表。

    ★★ 2026-10-18 用户「办公楼那三个是台阶」（弹窗定案：V 符号是门，外侧踏步是台阶）：
      c004 南侧入口的**踏步**也画在 `4.2墙体` 层上（x=34980..47820，y=19920..21020
      三圈 + 外沿到 19295），被当成墙带后拉成 2 m 高的实心墙，正堵在三个 2.4 m 大门外面。
      档案 `楼栋.json::<bid>.台阶` 逐条给 mm 框，命中区域从墙带里扣掉。
    ★ 盲区（铁律 158）：**没写进档案的台阶**仍会被当成墙建出来；这份名单只能由人指认后补。
      扣完只剩最外一圈薄墙时是**对的**（实测该处墙厚 19295..21295 里 2000 是踏步）。
    """
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
    out = [p for p in out if p.area > 0]
    try:
        steps = B.profile().get("台阶") or []
    except Exception:                      # 探针里没设楼栋/没档案 ⇒ 不扣，不吞错
        steps = []
    # ★ 档案里写的是**扁四元组** `[x0,y0,x1,y1]`（mm），不是四点多边形 ——
    #   第一版拿 `_poly()` 去解，它对四个数返回 None ⇒ 一块也没扣掉（实测 c004 重建后
    #   y=20500/20900 仍整幅是墙）。用 `sg.box` 解四元组，解不了就报出来，不静默跳过。
    _sq = []
    for s in steps:
        r = s.get("rect")
        if not r:
            continue
        if len(r) == 4 and all(isinstance(x, (int, float)) for x in r):
            _sq.append(sg.box(float(r[0]), float(r[1]), float(r[2]), float(r[3])))
        else:
            q = _poly(r)
            if q is not None and not q.is_empty:
                _sq.append(q)
    if _sq:
        S = unary_union(_sq)
        out = [q for p in out for q in _split(p.difference(S))
               if not q.is_empty and q.area > 0]
    return out


_COLUMN_MANUAL_CACHE = {"mtime": None, "data": None}


def _column_manual(bid=None):
    import building as _B
    path = os.path.join(os.path.dirname(_B.PROFILE), "柱人工校正.json")
    try:
        mtime = os.path.getmtime(path)
        if _COLUMN_MANUAL_CACHE["mtime"] != mtime:
            with open(path, encoding="utf-8") as source:
                _COLUMN_MANUAL_CACHE["data"] = json.load(source)
            _COLUMN_MANUAL_CACHE["mtime"] = mtime
    except OSError:
        return {}
    root = _COLUMN_MANUAL_CACHE["data"] or {}
    return ((root.get("楼栋") or {}).get(bid or _B.BID) or {})


def col_polys(v, floor=None):
    """柱块折线 → 多边形列表，并应用**独立的**人工校正表。

    自动规则不猜“哪根柱不存在”。人工调试表只记录人工决定：
      · exclude：按楼层 + 柱中心 20 mm 容差排除；
      · add：人工补一个矩形柱。
    该表不写入参数.json，也不进入统一需求。
    """
    out = []
    for pts, _cl in v["cols"]:
        p = _poly(pts)
        if p is not None:
            out.append(p)
    if not floor:
        return out
    manual = _column_manual()
    excluded = 0
    if manual.get("exclude"):
        kept = []
        rows = [r for r in manual["exclude"] if str(r.get("floor")) == str(floor)]
        for poly in out:
            c = poly.centroid
            hit = any(
                math.hypot(c.x - float(row["center"][0]), c.y - float(row["center"][1])) <= 20.0
                for row in rows
                if isinstance(row.get("center"), list) and len(row["center"]) == 2
            )
            if hit:
                excluded += 1
            else:
                kept.append(poly)
        out = kept
    added = 0
    for row in manual.get("add") or []:
        if str(row.get("floor")) != str(floor):
            continue
        try:
            cx, cy = float(row["center"][0]), float(row["center"][1])
            w, d = float(row["size_mm"][0]), float(row["size_mm"][1])
            out.append(sg.box(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2))
            added += 1
        except (KeyError, TypeError, ValueError, IndexError):
            print("  ★ 柱人工新增记录不完整，已跳过：%r" % (row,))
    if excluded or added:
        print("  ▷ %s 柱人工校正：排除 %d 根 / 新增 %d 根" % (floor, excluded, added))
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


# ★ 顶层「塔楼 vs 裙房屋面」切分的三个常数（**只对 `podium_roof=true` 的楼栋生效**）
ROOF_LABEL_R_MM = 200.0    # 房间名锚点外扩：MTEXT 的 insert 压在墙线上（实测 r=0 命中 0 个，
                           #   r=100/200 时 17 个名各命中一个分区、0 落空）——240 的墙挡得住
ROOF_ZONE_PAD_MM = 300.0   # 屋面开敞区外扩一圈（墙厚 240 + 容差），把这圈的墙一并判进屋面
ROOF_MIN_RATIO = 2.0       # 屋面判据：面积 ≥ **最大「有房间」分区** 的 2 倍（不手打面积）


def top_roof_zone(v, sp, wp, floor):
    """顶层（裙房屋面那一层）里**不属于塔楼**的那一块 → (zone, 读数)。

    为什么要它（2026-10-17，用户「第五层，说错了」）：源图的 5 层图幅**把裙房屋面
    和塔楼画在同一张平面里**（165 条墙线覆盖整栋轮廓），于是 `plate` 是整栋 ⇒ 建出来的
    顶层满铺。实测：5 层房间名 17 个全在中部，两侧各 ~464 m² 无任何房间、无内墙。

    判据（全部现算，铁律 018/103 —— 不手打任何面积）：
      ① 分区 = 楼板 − 墙带（连通开敞区，>1 m²）；
      ② 每个 `6房间号` 文字锚点外扩 200 mm，命中的分区 = 塔楼内的房间；
      ③ 屋面区 = 没被任何房间名命中、且面积 ≥ 2 × 最大命中分区 的分区；
      ④ 屋面区外扩 300 mm 并与整栋轮廓求交，再**扣掉所有非屋面分区的 300 mm 外扩**
         —— 这样塔楼一侧的墙（包括贴着走廊/竖井的墙）不会被人为切掉；
      ⑤ 返回空 ⇒ 调用方**不切**，按原样建（并打印读数，不静默）。
    """
    blind = {"层": floor, "结果": "缺件"}
    layer = next((L for L in (B.profile().get("keep_layers") or []) if "房间号" in L), None)
    path = os.path.join(B.ROOT, "01_cad", "raw", "%s.dxf" % floor)
    if not layer or not os.path.exists(path):
        blind["blind_spot"] = "缺房间名图层或 raw DXF（%s）⇒ 顶层不切" % path
        return None, blind
    import ezdxf
    from shapely.geometry import Point
    pts = [e.dxf.insert for e in ezdxf.readfile(path).modelspace()
           if e.dxftype() in ("TEXT", "MTEXT") and e.dxf.layer == layer]
    regs = [g for g in _split(unary_union(sp).difference(unary_union(wp))) if g.area > 1e6]
    if not pts or not regs:
        blind.update({"结果": "无房间名或无分区", "房间名": len(pts), "分区": len(regs),
                      "blind_spot": "顶层不切"})
        return None, blind
    tagged = set()
    for q in pts:
        b = Point(q.x, q.y).buffer(ROOF_LABEL_R_MM)
        for i, g in enumerate(regs):
            if g.intersects(b):
                tagged.add(i)
    if not tagged:
        blind.update({"结果": "房间名一个也没投中分区", "房间名": len(pts), "分区": len(regs),
                      "blind_spot": "顶层不切"})
        return None, blind
    a_max = max(regs[i].area for i in tagged)
    roof_i = [i for i, g in enumerate(regs)
              if i not in tagged and g.area >= ROOF_MIN_RATIO * a_max]
    diag = {"层": floor, "房间名": len(pts), "分区": len(regs), "命中分区": len(tagged),
            "最大命中分区_m2": round(a_max / 1e6, 2), "屋面分区": len(roof_i)}
    if not roof_i:
        # ★ 兜底（2026-10-20，c005 实测）：分区法在这栋**切不出来** —— 墙带只把楼板分成 2 块，
        #   最大那块 1738.8 m² 被 17 个房间名一起命中（两翼与塔楼之间那道墙在 5 层图幅上
        #   就是屋面边线，没有围合），于是「屋面区」判 0，件退回整层满铺 ——
        #   两翼被盖成 16~20 m 的**空壳**（有板、有 20 m 的屋面和女儿墙、没有墙），
        #   用户看到的就是「五楼只有中间的」。改用**同一条识别链**已经分好的区
        #   （`02_recognize/语义.json` 的 `房间[]` 环，不另算一遍：铁律 018/196）。
        plate = unary_union([p for p in (_poly(s) for s in v["plate"]) if p is not None])
        z2, d2 = _roof_zone_from_semantics(floor, plate)
        diag.update(d2)
        if z2 is not None:
            diag["结果"] = "切（兜底）"
            return z2, diag
        diag.update({"结果": "无屋面区（不切）"})
        return None, diag
    rf = unary_union([regs[i] for i in roof_i])
    plate = unary_union([p for p in (_poly(s) for s in v["plate"]) if p is not None])
    keep = unary_union([g for i, g in enumerate(regs) if i not in roof_i]).buffer(ROOF_ZONE_PAD_MM)
    zone = rf.buffer(ROOF_ZONE_PAD_MM)
    if not plate.is_empty:
        zone = zone.intersection(plate)
    zone = zone.difference(keep)
    diag.update({"屋面_m2": round(rf.area / 1e6, 2),
                 "切出_m2": round(zone.area / 1e6, 2),
                 "结果": "切" if not zone.is_empty else "切完为空（不切）"})
    if zone.is_empty:
        # 同上兜底（切完为空的情形，判据同 `if not roof_i` 那一支）
        z2, d2 = _roof_zone_from_semantics(floor, plate)
        diag.update(d2)
        if z2 is not None:
            diag["结果"] = "切（兜底）"
            return z2, diag
    return (zone if not zone.is_empty else None), diag


def _roof_zone_from_semantics(floor, plate):
    """`top_roof_zone` 的兜底：直接读 `02_recognize/语义.json` 的分区环判屋面区。

    返回 `(zone | None, 读数)`。**不另算一遍分区** —— 用的是同一条链 `recognize_semantics.py`
    落的盘（铁律 018/196：两处各算一套，漂了看不出来）。
    """
    p = os.path.join(B.ROOT, "02_recognize", "语义.json")
    if not os.path.exists(p):
        return None, {"兜底": "语义.json 不在 ⇒ 不切"}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return None, {"兜底": "语义.json 读不了（%s）⇒ 不切" % e}
    fl = next((x for x in (d.get("层") or []) if x.get("层") == floor), None)
    if not fl:
        return None, {"兜底": "语义.json 里没有 %s ⇒ 不切" % floor}
    rs = [r for r in (fl.get("房间") or []) if r.get("ring")]
    lab = [r for r in rs if r.get("已标注")]
    un = [r for r in rs if not r.get("已标注")]
    if not lab or not un:
        return None, {"兜底": "语义分区 %d 块·已标注 %d·未标注 %d ⇒ 不切"
                              % (len(rs), len(lab), len(un))}
    geo = {}
    for r in rs:
        g = _poly(r["ring"])
        if g is not None:
            geo[id(r)] = g
    lab = [r for r in lab if id(r) in geo]
    un = [r for r in un if id(r) in geo]
    if not lab or not un:
        return None, {"兜底": "语义分区的环解析不出来 ⇒ 不切"}
    ar = lambda r: geo[id(r)].area
    a_max = max(ar(r) for r in lab)
    roof = [r for r in un if ar(r) >= ROOF_MIN_RATIO * a_max]
    if not roof:
        return None, {"兜底": "未标注区里没有 ≥ 2×最大已标注分区（%.1f m²）的 ⇒ 不切"
                              % (a_max / 1e6)}
    rf = unary_union([geo[id(r)] for r in roof])
    keep = unary_union([geo[id(r)] for r in rs if id(r) in geo and r not in roof])
    keep = keep.buffer(ROOF_ZONE_PAD_MM)
    zone = rf.buffer(ROOF_ZONE_PAD_MM)
    if plate is not None and not plate.is_empty:
        zone = zone.intersection(plate)
    # ★ 做减法的一侧负责塌短边（铁律 183）；上游 `top_roof_zone` 原支路没塌，是因为
    #   那里后面紧跟 `podium_roof_parts` 自己做减法也自己塌。兜底这条路**同样**交给它，故此处不塌。
    zone = zone.difference(keep)
    return (zone if not zone.is_empty else None), {
        "兜底": "语义分区切",
        "兜底_已标注": len(lab), "兜底_屋面区": len(roof),
        "兜底_屋面_m2": round(rf.area / 1e6, 2),
        "兜底_切出_m2": round((zone.area / 1e6) if zone is not None else 0.0, 2),
    }


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


def _open_door_leaves(rect, W):
    """一个门洞 → **开启 90°** 的门扇片（厚 30 mm）。

    门洞矩形给出沿墙向净宽；墙带给出墙厚与两个墙面。门扇从**墙面**向室内
    法向伸出，长度 = 单扇净宽。开启侧优先取源图门符号探出的那一侧，
    再以「与墙带重叠面积最小」兜底；宽洞按 `DOOR_OPEN_MAX_SPAN_MM` 等分。
    """
    p = _poly(rect)
    if p is None or p.is_empty or W is None or W.is_empty:
        return []
    rr = p.minimum_rotated_rectangle
    if rr.geom_type != "Polygon":
        return []
    pts = list(rr.exterior.coords)[:4]
    if len(pts) != 4:
        return []
    edges = []
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        edges.append((((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5, a, b))
    edges.sort(key=lambda e: e[0])
    short, va, vb = edges[0]
    width, ua, ub = edges[-1]
    if short <= 0 or width <= 0:
        return []
    nx, ny = (vb[0] - va[0]) / short, (vb[1] - va[1]) / short
    ux, uy = -ny, nx
    c = p.centroid
    probe = sg.LineString([(c.x - 3000 * nx, c.y - 3000 * ny),
                           (c.x + 3000 * nx, c.y + 3000 * ny)])
    inter = probe.intersection(W)
    segs = [inter] if inter.geom_type == "LineString" else list(getattr(inter, "geoms", []))
    best = None
    for s in segs:
        if (s.geom_type != "LineString" or s.length <= 0
                or s.length > DOOR_OPEN_MAX_SPAN_MM or len(s.coords) < 2):
            continue
        if best is None or s.distance(c) < best.distance(c):
            best = s
    if best is None:
        return []
    p0, p1 = best.coords[0], best.coords[-1]
    f0 = (p0[0] - c.x) * nx + (p0[1] - c.y) * ny
    f1 = (p1[0] - c.x) * nx + (p1[1] - c.y) * ny
    wc = (f0 + f1) / 2.0
    # wc = 墙带中心相对门洞中心的法向偏移；门洞中心在哪一侧，门就朝哪一侧开。
    inferred = 1 if wc <= 0 else -1
    uv = [((x - c.x) * ux + (y - c.y) * uy) for x, y in p.exterior.coords]
    u0 = min(uv)
    n_leaf = max(1, int(math.ceil(width / DOOR_OPEN_MAX_SPAN_MM)))
    step = width / n_leaf
    out = []
    half_t = DOOR_OPEN_T_MM / 2.0
    for i in range(n_leaf):
        a_u = u0 + i * step
        b_u = a_u + step
        preferred_hinge = a_u if i == 0 else (b_u if i == n_leaf - 1 else a_u)
        choice = None
        for side in (inferred, -inferred):
            face = max(f0, f1) if side > 0 else min(f0, f1)
            for hinge_u in (a_u, b_u):
                corners = [
                    (c.x + (hinge_u - half_t) * ux + face * nx,
                     c.y + (hinge_u - half_t) * uy + face * ny),
                    (c.x + (hinge_u + half_t) * ux + face * nx,
                     c.y + (hinge_u + half_t) * uy + face * ny),
                    (c.x + (hinge_u + half_t) * ux + (face + side * step) * nx,
                     c.y + (hinge_u + half_t) * uy + (face + side * step) * ny),
                    (c.x + (hinge_u - half_t) * ux + (face + side * step) * nx,
                     c.y + (hinge_u - half_t) * uy + (face + side * step) * ny),
                ]
                q = sg.Polygon(corners)
                if not q.is_valid:
                    continue
                ov = q.intersection(W).area
                score = (round(ov, 3), 0 if side == inferred else 1,
                         0 if hinge_u == preferred_hinge else 1)
                if choice is None or score < choice[0]:
                    choice = (score, q)
        if choice is not None and DOOR_LEAF_MIN_M2 <= choice[1].area / 1e6 <= DOOR_LEAF_MAX_M2:
            out.append(choice[1])
    return out


def door_polys(v, walls=None):
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

    # ★★ 2026-10-21：有门洞框时，直接按洞口生成**开启 90°、厚 30 mm** 的门扇。
    #   这比继续修补「关门姿态」的 50 mm 板更符合用户口径，也避免门板凹在墙厚中间。
    _rects = v.get("door_voids") or []
    if _rects:
        try:
            _W = unary_union(walls) if walls is not None else unary_union(wall_polys(v))
        except Exception:                                 # noqa: BLE001
            _W = None
        if _W is not None and not _W.is_empty:
            _opened = []
            for _r in _rects:
                _opened.extend(_open_door_leaves(_r, _W))
            if _opened:
                DOOR_AUDIT.clear()
                DOOR_AUDIT.update({
                    "seg": 0, "dup_seg": 0, "closed": 0, "paired": 0,
                    "arc_line": 0, "dropped": 0, "near_dup": 0,
                    "off_wall": 0, "off_wall_max_m": None,
                    "voids": len(_rects), "open90": len(_opened),
                    "open_t_mm": DOOR_OPEN_T_MM,
                })
                return _opened

    segs, seen = [], set()
    n_dup = 0
    # ★ 2026-10-18：`door_leaf_lines` 是 `redraw._leaf_lines` 现算的「关门姿态」扇线
    #   （符号/开启弧画法的门只有多点多段线，本函数的 `len(pts)!=2` 会把它们全丢掉 ⇒
    #   全库 66 栋门扇 0 片）。块路径没有这一项（块自带两点扇线），故为空表。
    _all_pts = [p for p, _c in v["doors"]] + list(v.get("door_leaf_lines") or [])
    for pts in _all_pts:
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
    # ★ 2026-10-20：门扇必须挂在**本层墙带**上（c106 的 15 樘门窗表样例在楼外 18~28 m）。
    #   参照物是本层墙带并集（与 `door_voids` 同一份）；算不出墙带时**不丢**、记 `off_wall=None`
    #   ——「量不到」不许当成「离墙远」（铁律 199）。
    n_off = 0
    try:
        _wu = unary_union(walls) if walls is not None else unary_union(wall_polys(v))
    except Exception:                                     # noqa: BLE001
        _wu = None
    if _wu is not None and not _wu.is_empty:
        far = []
        for p in keep:
            if p.distance(_wu) > DOOR_OFF_WALL_MM:
                n_off += 1
                far.append(round(p.distance(_wu) / 1000.0, 1))
            else:
                far.append(None)
        keep = [p for p, d in zip(keep, far) if d is None]
        DOOR_AUDIT["off_wall"] = n_off
        DOOR_AUDIT["off_wall_max_m"] = max([d for d in far if d is not None], default=None)
    else:
        DOOR_AUDIT["off_wall"] = None
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

# ★ 梯间清空的**落位包络**（mm 多边形）：`stair_steps` 每落一座就 append 一块，
#   调用方（`main()`）用前先 `STAIR_ENV[:] = []` —— 同 `STAIR_DIAG` 的口径。
#   ★ 为什么不把它当返回值加进 `stair_steps` 的返回契约：返回值是
#     `[(polygon, z_rel_m, h_m)]`，被 `gates/J-10.8-01` 的自检和 `export_contours`
#     的调用链都按三元组解包（`for poly, zrel, hm in ...`）⇒ 改契约要连带改三处。
#     包络是**副作用式的记账**，和 `STAIR_DIAG`/`RAIL_DIAG`/`LINTEL_AUDIT` 同一路数。
STAIR_ENV = []
# ★ 梯间清空的**记账**（铁律 158：判词不许静默 —— 扣了多少、扣没扣到，必须看得见）。
STAIR_CLEAR_DIAG = []
# ★ 2026-10-17：梯块裁墙的逐层读数（`clip_steps_to_walls`）。与清空区**分开记账** ——
#   清空区是「墙被削了多少」，这里是「梯子伸进墙里多少」，两件事合一个表就分不清谁干的。
STAIR_CLIP_DIAG = []
# ★ 顶层裙房屋面切分的**记账**（切了几块、多少 m²、为什么没切 —— 铁律 158 不许静默）
ROOF_DIAG = []
# ★ 2026-10-20 屋面平面层的**记账**（`roof_plan_split`：塔外多少 m² 墙带改成了女儿墙）。
ROOF_PLAN_DIAG = []
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


def _offspan(r):
    """一跑的 off 区间（沿走向的两端）。"""
    os_ = [d["off"] for d in r]
    return (min(os_), max(os_))


def _parcen(r):
    """一跑的 par 中心（梯段宽方向的中点）。"""
    return sum(d["par"] for d in r) / len(r)


def _well_geom(segs):
    r"""一层踏步线 → 该层各梯间的**形制**：[{"mid": (x,y), "w": 梯段宽, "gap": 梯井宽}]。

    ★ 与 `stair_steps` 里的分组**同一把尺子**（`_flight_runs` + 同角度 + off 并排 + par 邻近），
      只是不落位，只回答「这一层每根梯井长什么样」。给**跨层借形**用：入口层的图被折断线
      截短（实测 1层 西侧那根井只有 5 条踏步线、最长 1590 mm，而 2层 同一根井是 15 条线、
      2620 mm）⇒ 这一层量出来的梯段宽/井宽/锚区同时偏小，双跑就铺不下，只能退回单跑
      （爬到半层、**到不了上一层**）。梯井是竖向贯通的构件，形制该按同一根井在别层量到的定。
    ★ 长度量（梯段宽/梯井宽）可以跨层直接用：它们是**标量**、与基向量无关；
      中点用**世界坐标**按身份匹配（铁律 194），不按值比大小。
    """
    runs = _flight_runs(segs)
    n = len(runs)
    if not n:
        return []
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if abs(runs[i][0]["ang"] - runs[j][0]["ang"]) > 1e-6:
                continue
            (a0, a1), (b0, b1) = _offspan(runs[i]), _offspan(runs[j])
            if min(a1, b1) - max(a0, b0) < STAIR_OFF_OVL * min(a1 - a0, b1 - b0):
                continue
            if abs(_parcen(runs[i]) - _parcen(runs[j])) > STAIR_PAR_GAP_MM:
                continue
            ra, rb = find(i), find(j)
            if ra != rb:
                parent[ra] = rb
    wells = {}
    for i in range(n):
        wells.setdefault(find(i), []).append(i)
    out = []
    for idxs in wells.values():
        ref = max((runs[i] for i in idxs), key=len)     # 参考跑 = 线最多（画得最全）的那一跑
        basis = _basis(ref[0]["ang"])
        pc = sum(d["par"] for d in ref) / len(ref)
        w = max(d["L"] for d in ref)
        gap = WELL_GAP_MM
        others = [runs[i] for i in idxs if runs[i] is not ref]
        if others:
            far = min((sum(d["par"] for d in r) / len(r) for r in others),
                      key=lambda q: abs(q - pc))
            gap = max(60.0, abs(far - pc) - w)
        mid = _xy(basis, (ref[0]["off"] + ref[-1]["off"]) / 2.0, pc)
        out.append({"mid": (float(mid[0]), float(mid[1])), "w": float(w), "gap": float(gap)})
    return out


def stair_steps(v, h, alt=None):
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
      `alt` = 可选的**相邻楼层**读数 `{"wells": _well_geom(...), "zones": [box, …]}`，
      只在本层铺不下双跑时用来**借形**（见下面的「跨层借形」与 `STAIR_ALIGN_MM`）。
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

        # ★★ 跨层借形（2026-10-16，用户报「楼梯还是不对」的那个病灶）：
        #   入口层（1层）的源图**每座梯间只画一跑，而且被折断线截短** —— 实测那两座退回
        #   单跑的井：本层锚区 par 只 2050 mm 宽（同一根井在 2层 是 6880），本跑最长线
        #   1590 mm（2层 是 2620）。于是 `breadth = 2w + gap = 3300` 放不进 2050 ⇒ 底下
        #   那道硬闸退回**单跑** ⇒ `k=11 级 × riser 159.091 = 1750 = 半层` ⇒ 那两座梯
        #   **爬不到上一层**（这就是用户在图里看到的那两座"断头梯"）。
        #   ⇒ 梯井是**竖向贯通构件**：本层 par 装不下双跑时，按世界中点最近（按身份，
        #     铁律 194）取邻层**同一根井**的 (梯段宽, 梯井宽) 与它的锚区，重算 breadth
        #     与 par_ok；触发条件与旧的单跑兜底**逐字相同** ⇒ 另外 64 座梯间一位不动。
        #   ★ 借不到就**不借**（照旧退回单跑），并逐条记账 —— 不许静默（铁律 158）。
        if alt is not None and par_ok is not None and (par_ok[1] - par_ok[0]) < breadth - 2.0:
            _pt = sg.Point(_mid[0], _mid[1])
            _aw, _dd = None, None
            for _c in (alt.get("wells") or []):
                _d = ((_c["mid"][0] - _mid[0]) ** 2 + (_c["mid"][1] - _mid[1]) ** 2) ** 0.5
                if _d <= STAIR_ALIGN_MM and (_dd is None or _d < _dd):
                    _aw, _dd = _c, _d
            _az = None
            for _zp in (alt.get("zones") or []):
                _dz = _zp.distance(_pt)
                if _dz <= STAIR_ALIGN_MM and (_az is None or _dz < _az[1]):
                    _az = (_zp, _dz)
            if _aw is None or _az is None:
                # ★ 2026-10-17 C005：邻层**一个井都没有**时 `_dd` 是 None，旧写法
                #   `"%.0f" % _dd` 会 TypeError 把整层建件打崩（4层实测）。判词分三档：
                #   借到了 / 有井但太远（报距离）/ 压根没井。
                _s_aw = "有" if _aw is not None else (
                    "无（最近 %.0f mm > %.0f）" % (_dd, STAIR_ALIGN_MM)
                    if _dd is not None else "无（邻层无井）")
                STAIR_DIAG.append(
                    "★ 跨层借形**没借到**：本层锚区 par 只 %.1f 宽 < 双跑 %.1f（本跑中点 %.1f,%.1f）"
                    "；邻层同井%s、锚区%s ⇒ 保持旧行为（退回单跑）"
                    % (par_ok[1] - par_ok[0], breadth, _mid[0], _mid[1],
                       _s_aw, "无" if _az is None else "有"))
            else:
                _zp, _dz = _az
                _pc2 = basis[0][0] * _aw["mid"][0] + basis[0][1] * _aw["mid"][1]
                _xs, _ys = _zp.exterior.coords.xy
                _ps2 = [basis[0][0] * _x + basis[0][1] * _y for _x, _y in zip(_xs, _ys)]
                STAIR_DIAG.append(
                    "跨层借形：本层锚区 par [%.1f, %.1f]（宽 %.1f）装不下双跑 %.1f"
                    "（本跑 w=%.0f，中点 %.1f,%.1f）⇒ 借邻层同一根井（中点距 %.0f mm，锚区距 %.0f mm）"
                    "：w=%.0f gap=%.0f breadth=%.0f，par_ok=[%.1f, %.1f]"
                    % (par_ok[0], par_ok[1], par_ok[1] - par_ok[0], breadth, w, _mid[0], _mid[1],
                       _dd, _dz, _aw["w"], _aw["gap"], 2.0 * _aw["w"] + _aw["gap"],
                       min(_ps2), max(_ps2)))
                pool = [_zp]
                pc, w, gap = _pc2, _aw["w"], _aw["gap"]
                breadth = 2.0 * w + gap
                par_ok = (min(_ps2), max(_ps2))

        # ★★ 2026-10-18 用户令「楼梯上的开始是从门开始，很多楼梯现在是反着的」。
        #   本模块的「底」是 `s0`：第一跑**从 `s0` 沿 +n̂ 逐级抬升**（见下面第一跑循环）。
        #   旧排序 `key = (outa<=1.0, _ci<2, round(inside))` 里，两个老锚点
        #   `ref[0].off` 与 `ref[-1].off - span` 的 `inside` 逐位相同（各自都铺满锚区）
        #   ⇒ 靠 `>` 取先者，**永远**落在 off 小的那一端 —— 与门开在哪一头毫无关系。
        #   门开在另一头的梯间于是整座反着（用户看到的「反着的楼梯」）。
        #   判据只有一条：**第一级踏步离本梯间最近的门洞多远**（mm，越小越好），
        #   只量**沿跑方向**（off）——「反着」说的是沿跑方向；
        #   双跑铺在 par 哪一侧（pdir）不由门定（门在首层平台端，与两跑都相邻，
        #   拿它去判 par 侧会把整跑翻到「离别人的门近」的那一边）。
        #   ★ 无近门 ⇒ 恒 0.0，与旧行为**逐位相同**（只有真被挡住的梯间才可能翻）。
        _door_off = []
        for _r in (v.get("door_voids") or []):
            _q = _poly(_r)
            if _q is None or _q.is_empty:
                continue
            _c = _q.centroid
            _pt = sg.Point(_c.x, _c.y)
            if any(zp.buffer(STAIR_DOOR_PAD_W * w).contains(_pt) for zp in pool):
                _door_off.append(basis[1][0] * _c.x + basis[1][1] * _c.y)

        def _near_door(b0, b1):
            """**底部第一级踏步**的 off 区间 `[b0, b1]` 到最近门洞的**沿跑**间隙（mm）；无近门 = 0.0。"""
            if not _door_off:
                return 0.0
            return min(max(b0 - d, 0.0, d - b1) for d in _door_off)

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

        # ★ 迭代次序 = **优先级**（`key >` 取先者）：`fdir=+1` 先于 `-1`、`pdir=+1` 先于 `-1`
        #   ⇒ 门距并列时**逐位退回旧落位**，没门的梯间一位不动（2026-10-18）。
        best = None
        for fdir, pdir in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            q0 = (pc - w / 2.0) if pdir > 0 else (pc - breadth + w / 2.0)
            for _ci, s0c in enumerate(cand_s):
                # ★ 2026-10-18：`fdir` = **第一跑往哪头抬**。`+1` = 老写法（底部在 s0，
                #   平台落在 `[s0+span, s0+span+w]`，+off 端）；`-1` = 整座关于
                #   `s_mid = s0 + span/2` 镜像 ⇒ 底部在 **s0+span** 那头、平台落到 `[s0-w, s0]`。
                #   ★ 为什么要这一维：两个老锚点 `ref[0].off` 与 `ref[-1].off - span` 只差
                #   `跑长 - span`（c004 实测 600 mm）—— **它们翻不了面**，底部永远在 off 小的一端。
                #   c004 2层 东侧梯间实测：门洞在 off 27585，本跑 off 到 26430 ⇒ 门在**远端**
                #   （离踏步包络 1045 mm，是本层最近的一樘门），而底部被钉在 23130 那头 ⇒
                #   整座反着。没有 fdir 这一维，「从门起」这条判据连表达的余地都没有。
                if fdir > 0:
                    _o0, _o1 = s0c, s0c + span + w
                    _b0, _b1 = s0c, s0c + g
                else:
                    _m2 = 2.0 * s0c + span
                    _o0, _o1 = _m2 - (s0c + span + w), _m2 - s0c
                    _b0, _b1 = _m2 - (s0c + span), _m2 - (s0c + span - g)
                box = _rect(basis, _o0, _o1, q0, q0 + breadth)
                inside = sum(box.intersection(zp).area for zp in pool) if pool else box.area
                outa = box.difference(zunion).area if zunion is not None else 0.0
                # ★ `inside` 取整到 1 mm² 再进 key：两个候选位之间的 ins 差常只到浮点最低位
                #   （实测两区候选逐位相同、只差 1 ULP）⇒ 不取整就会靠噪声翻面（铁律 194）。
                #   1 mm² 对 6 m 级的楼梯摆位没有分辨力，取整丢掉的不是判据。
                # ★ 2026-10-18：「从门起」这一项排在 `round(inside)` **之前**，但排在
                #   `_ci < 2` **之后** —— 两个老锚点的 inside 逐位相同，先比门距正好只翻
                #   该翻的那一刀；锚区自带的候选位（`_ci >= 2`）仍排在两位老锚点之后，
                #   旧的「装得下 → 贴着参考跑 → 比相交面积」三级次序一位不动。
                #   ★ `key` 取 **max** ⇒ 门距必须**取负**：我要的是「离门近」，不是「离门远」。
                #     （2026-10-18 第一版漏了这个负号，实测门距 4155 → 4755 **反向翻**，
                #      被「从门起」那行读数当场逮住 —— 读数先于肉眼：单看几何它是一条合法的楼梯。）
                key = (outa <= 1.0, _ci < 2, -round(_near_door(_b0, _b1)), round(inside))
                if best is None or key > best[0]:
                    best = (key, s0c, pdir, q0, fdir)
        _, s0, pdir, p0, fdir = best

        # ---- `fdir` 镜像的**唯一一处**：`+1` 原样；`-1` 关于 `s_mid = s0 + span/2` 镜像 ----
        #   下面所有沿 off 的区间都过这一道 ⇒ 生成、包络、读数不会各镜像各的（铁律 018/174）。
        _SM2 = 2.0 * s0 + span

        def _sb(a, b):
            return (a, b) if fdir > 0 else (_SM2 - b, _SM2 - a)

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
        # ★ `_foot` = 这一座楼梯的**落位包络**（两跑 + 中间平台的全部水平投影）。
        #   算一次、两处用：① 下面「装不下」判据拿它比锚区；② 记进 `STAIR_ENV` 供
        #   `main()` 清梯间。**不另写一遍同样的 `_rect`**（铁律 018：两个地方写同一个量，
        #   一致证明不了它是对的；哪天落位口径改了，两份会各自漂走）。
        _foot = _rect(basis, *_sb(s0, s0 + span + w), p0, p0 + breadth)
        if zunion is not None:
            _fbox = _foot
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

        # ---- 梯间清空的记账：把这一座的**包络**落进 `STAIR_ENV` ----
        #   ★ 落位到这里才**定形**（`p0`/`breadth` 可能被上面的单跑兜底改过，`s0` 也可能
        #     被候选位搜索改过）⇒ 包络必须在这里记，不能早记（早记就是把搜索前的候选当落位）。
        #   ★ 记的是**包络矩形**不是「踏步的并集」：两者在本模块里逐位相同（`span = k*g`
        #     且平台正好铺满 `[s0+span, s0+span+w]`），但矩形是**现算的**、不依赖并集是不是
        #     刚好严密（铁律 194：同一个量有两个估计器时，别拿一个去过滤另一个）。
        STAIR_ENV.append(_foot)

        # ---- 栏杆：**不建**（2026-10-16 用户明令「就是只要踏步和平台就行，不要那么复杂」）----
        #   旧版先算 `_rail_edges`，再按栏杆站位把每级踏步**两侧各让出栏杆宽**，最后
        #   还在两级交界处补 `k+1` 块立杆（`_rail_blocks`）——一层梯间 33 块踏步/平台
        #   配 52 块栏杆。现在整段拿掉：`rail_edges` 空 ⇒ `f1`/`f2` 就是**整段梯段宽**
        #   （1490 mm，不再内缩 50），也不再生成立杆。
        #   `_rail_edges` / `_rail_blocks` 两个函数体**原样留着不删**：将来要恢复栏杆
        #   只改这一处，不必重写（那段站位/问墙逻辑是踩过坑的，见各自 docstring）。
        rail_edges, n_side, n_walled = [], 0, 0
        f1 = [p0, p0 + w]
        f2 = [p0 + w + gap, p0 + breadth]

        # ---- 第一跑：从 s0 起，沿 +n̂ 逐级抬升 ----
        # ★★ 2026-10-16 改形（用户「楼梯还不对」＋「你截屏给我看看楼梯的样子」）：
        #   旧写法 `(p, 0.0, (j+1)*riser)` —— 底标高写死 0、高度写到**本级的顶**
        #   ⇒ 每一级都是**从楼面长上来的实心块**，整跑并成一坨楔形体（渲染图里那块
        #   大平斜面就是它的底），看不出是楼梯。
        #   新写法照 gym3d 的口径（`gym3d/backend/modeling/build_standard_glb.py:884-888`
        #   的 `flight()`）：一级 = 一块 **踏面深 × 踢面高** 的板，**坐在自己那一级的高程上**
        #   ⇒ 顶面标高与旧写法**逐级相同**（`j*riser + riser == (j+1)*riser`），
        #     只有块底降到本级高程，soffit 变锯齿，下面一格一格是空的。
        #   `k / riser` 仍由层高现算（`k = round(h/2/RISER_TARGET)`、`riser = h/(2k)`）
        #   ⇒ 层高变了照样自动跟。平台/栏杆不动。
        for j in range(k):
            box = _rect(basis, *_sb(s0 + j * g, s0 + (j + 1) * g), f1[0], f1[1])
            for p in _split(box):
                if p.area > 0:
                    out.append((p, round(j * riser / 1000.0, 4), round(riser / 1000.0, 4)))
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
                box = _rect(basis, *_sb(s0 + span, s0 + span + w), _qa, _qb)
                for p in _split(box):
                    if p.area > 0:
                        out.append((p, zl, hl))
        # ---- 第二跑：与第一跑反向（折返），从半层高再往上爬 k 级 ----
        # ★ 只有 `two_flight` 才建第二跑：单跑兜底时 `p0 + w + gap > p0 + breadth`，
        #   照建会得到一个绕反的假实体（`_rect` 不校验 p0 < p1，错了也不报）。
        if two_flight:
            for j in range(k):
                box = _rect(basis, *_sb(s0 + span - (j + 1) * g, s0 + span - j * g),
                            f2[0], f2[1])
                for p in _split(box):
                    if p.area > 0:
                        # 同第一跑：本级 = 一块「踏面深 × 踢面高」的板，坐在自己的高程上
                        # （顶面 = half + (j+1)*riser，与旧写法逐级相同）
                        out.append((p, round((half + j * riser) / 1000.0, 4),
                                    round(riser / 1000.0, 4)))
        # ---- 栏杆：不建（用户令「只要踏步和平台」）⇒ 这里不再 append 立杆块 ----
        _rblk = []
        RAIL_DIAG.append({"边": n_side, "贴墙": n_walled, "立栏": len(rail_edges),
                          "块": len(_rblk),
                          "合并级数": int(round(float(PL.p("楼梯", "栏杆合并级数")))),
                          "问墙": int(round(float(PL.p("楼梯", "栏杆_问墙")))),
                          "墙带": ("空" if walls_u is None or walls_u.is_empty else "有")})
        # ★ 形制读数（对照.json 的「我们建的」一列）：逐梯间落一行，页面不重算。
        #   `踏面档` 记的是**这一跑实际用的是实测还是参数档** —— 切了档必须看得出来。
        _bb0, _bb1 = _sb(s0, s0 + g)          # 底部第一级踏步（已过镜像）—— 与落位同一把尺子
        STAIR_FACT.append({
            "层": _CUR["层"], "中点_xy": [round(_mid[0], 1), round(_mid[1], 1)],
            "踏面_mm": round(g, 3), "踢面_mm": round(riser, 3), "级数_每跑": k,
            "踏面源": ("参数档" if _gov_on else "实测"),
            "梯段宽_mm": round(w, 1), "梯井宽_mm": round(gap, 1),
            "梯段水平投影_mm": round(span, 1), "平台厚_mm": round(land_t, 1),
            "两跑": bool(two_flight), "栏杆_侧": n_side, "栏杆_贴墙": n_walled,
            "栏杆_块": len(_rblk),
            "梯间总宽_mm": round(breadth, 1), "半层高_mm": round(half, 1),
            # ★ 2026-10-18「从门起」的读数：第一级踏步到最近门洞的沿跑间隙。
            #   `None` = 本梯间**没有**近门（不是「门正好在踏步上」）—— 两件事不许同形（铁律 199）。
            "门距_mm": (round(_near_door(_bb0, _bb1), 1) if _door_off else None),
            # 旧排序会选的那一端（`anchor_s[0]`，`fdir=+1`、`pdir=+1`、`_ci=0`、`inside` 并列
            # ⇒ 先者）的门距 —— 两个数不相等就是**这一座被翻了**，翻没翻不必另猜。
            "门距_旧_mm": (round(_near_door(anchor_s[0], anchor_s[0] + g), 1)
                          if _door_off else None),
            "梯段起向": fdir,
            "近门_个": len(_door_off)})
    return out


# ★ 2026-10-19：女儿墙环带的「短边塌掉」记账（落 `build.json::parapet_edge_fix`）。
#   为什么会有短边：环带 = 外轮廓减内缩 200 mm 的那一圈；轮廓本身是栅格出来的，
#   相邻两块板的接缝处，一块的内缩边与另一块的外边只差 **3~5 mm**（实测 7 层
#   3.002 / 5.004 mm）⇒ 环带收口时留下一个亚栅格短桩。闸 `J-10.8-00` ⑪ 卡 6.25 mm
#   （= RES/4），这两条就是它唯一剩下的红。
#   阈值**不新立**：`RING_EDGE_MIN_MM`（参数表 `共用/环_最短边下限`）。
PARAPET_EDGE_FIX = {"环_块": 0, "删短边点": 0, "塌短边面积_m2": 0.0, "原样留_块": 0}


def parapet_ring(polys):
    """一块（组）楼板**外轮廓**向内收 `PARAPET_T` 的环带 —— 女儿墙的**唯一算法**。
    ★ 2026-10-17：原先只在 `parapet_polys(v)` 里，顶层收窄到塔楼后，裙房屋面要按
      它自己的轮廓另算一圈；两处各写一份就会漂（铁律 018/174）⇒ 抽出来共用。
    ★ 2026-10-19：收口后按 `RING_EDGE_MIN_MM` 塌掉亚栅格短边（见 `PARAPET_EDGE_FIX`）。
      参照件与正式件都走这一个函数 ⇒ 两边仍是同一把尺子。
    """
    ring = []
    for p in polys:
        q = p.buffer(-PARAPET_T * 1000.0, join_style=2)   # 2 = mitre：直角，不用圆角
        r = p if (q.is_empty or q.area <= 0) else p.difference(q)
        ring.extend(_split(r))
    return _rails_clean([x for x in ring if x.area > 0])


def _rails_clean(rails):
    """女儿墙环带**收口后的最后一道塌边**（唯一做法，见 `PARAPET_EDGE_FIX`）。

    ★★ 2026-10-19 实测：只在 `parapet_ring` 里塌一次**不够**。裙房屋面那条路是
      「环带 − 塔楼轮廓」（`podium_roof_parts`），减法本身会在接缝处再造出一条
      3~5 mm 短桩（7层 PARAPET-005/013）⇒ 谁做减法，谁就得在**减法之后**再塌一遍。
      这就是「修好一个错法只算改了一半，同形状换函数仍会再犯」（铁律 183）。
    """
    out, rec = _drop_short_edges(rails)
    PARAPET_EDGE_FIX["环_块"] += len(rails)
    PARAPET_EDGE_FIX["删短边点"] += rec["删短边点"]
    PARAPET_EDGE_FIX["塌短边面积_m2"] = round(
        PARAPET_EDGE_FIX["塌短边面积_m2"] + rec["塌短边面积_m2"], 6)
    PARAPET_EDGE_FIX["原样留_块"] += rec["原样留着_块"]
    return out


def parapet_polys(v):
    """女儿墙：顶层楼板**外轮廓**向内收 `PARAPET_T` 的环带。
    ★ 源图无女儿墙（无屋顶图）⇒ 这是**按规则推**的，不是照图建的。
    """
    return parapet_ring(slab_polys(v))


def podium_roof_trim(v, sp, wp, floor):
    """顶层裙房屋面切分 —— **唯一定义处**（build3d 主循环与 export_contours 都调它）。

    返回 (sp', wp', 读数)；不适用（非顶层 / 楼栋没开 `podium_roof`）时原样返回并给 None。
    铁律 018/174：参照件与正式件必须走同一把尺子 —— 两处各算一遍必然漂。
    """
    if not (B.profile().get("podium_roof") and floor == TOP_FLOOR):
        return sp, wp, None
    rz, diag = top_roof_zone(v, sp, wp, floor)
    if rz is None:
        return sp, wp, diag
    sp2 = [g for g in _split(unary_union(sp).difference(rz)) if g.area > 1e6]
    wp2 = [g for g in _split(unary_union(wp).difference(rz)) if g.area > 1e6]
    if not (sp2 and wp2):
        return sp, wp, dict(diag, 结果="切完塔楼为空（不切）")
    return sp2, wp2, diag


def roof_plan_split(v, sp, wp, floor):
    """「**屋面平面**」层：塔楼以外不是楼层，是屋面 —— **唯一定义处**（build3d 与 export_contours 都调它）。

    2026-10-20 用户定案（「第六教学楼裙楼只有六层，六层上面就是屋顶」）：
      c006 的 `7层` 图幅画的是**裙房屋面平面** + 中央塔楼的第 7 层。
      证据（本仓实测）：该层塔楼外 WALL 268.1 m²、DOOR **0** 樘、COL 0 —— 没有门的房间不是房间；
      塔外的 `SLAB` 4339.1 m² 就是屋面板，`ROOF_STEP` 4338.5 m² 与它同址（同一个屋面被画了两遍）。

    判据与做法：
      · 塔楼足迹 = **下一层**（`塔楼层`）的楼板并集，现算，不手画矩形；
      · 塔外**墙带 → 女儿墙**（1.2 m，基面 = 本层底 = 屋面标高），塔内墙带照旧建 4 m；
      · 楼板**整块保留**（塔外是屋面、塔内是楼面，本来就是同一块板）；
      · 塔外门/门头/柱/梯：实测为 0 或毫米级；梯若在塔外按原位落（屋面检修梯），不改；
      · 塔外的板 = **屋面**（类 `ROOF`，半透明时与其它屋面一起收掉），塔内的板 = 楼面（`SLAB`）。
    返回 `(sp_塔内, wp_塔内, extras)`；`extras = {"女儿墙", "屋面板", "读数"}`。
    没写 `roof_plans` 的楼栋原样返回 + None（调用方判 `extras is None`）。
    """
    cfg = (B.profile().get("roof_plans") or {}).get(floor)
    if not cfg:
        return sp, wp, None
    tname = cfg.get("塔楼层")
    if not tname:
        raise RuntimeError("楼栋档案 roof_plans[%s] 没写「塔楼层」—— 塔楼足迹不许猜" % floor)
    tv = RD.geometry(tname)
    # ★ `slab_polys`/`wall_polys` 返回的**已经是 Polygon**（别再过一遍 `_poly(点列)`，
    #   `_poly` 只吃点列 —— 传 Polygon 会把它当序列取坐标，静默出错）。
    tower = unary_union(list(slab_polys(tv)))
    if tower.is_empty:
        raise RuntimeError("roof_plans[%s]：塔楼层 %s 的楼板为空 ⇒ 切不出塔楼足迹" % (floor, tname))
    wu = unary_union(list(wp))
    if wu.is_empty:
        return sp, wp, {"女儿墙": [], "屋面板": [], "读数":
                        {"层": floor, "塔楼层": tname, "结果": "本层墙带为空（不切）"}}
    # ★ 做减法的人负责在**减法之后**塌短边（铁律 183，见 `_rails_clean` 的说明）：
    #   不塌的话接缝处的 1 mm 级残片会被 `_rec` 判成「无声丢件」直接抛断言。
    par = _rails_clean([g for g in _split(wu.difference(tower)) if g.area > 1e6])
    win = [g for g in _split(wu.intersection(tower)) if g.area > 1e6]
    if not win:
        # 塔内一片墙都不剩 ⇒ 不是「屋面层」，是足迹判错了 —— 宁可停下，不静默出空楼。
        raise RuntimeError("roof_plans[%s]：按 %s 的楼板切完，塔楼内墙带为 0 块"
                           "（塔楼足迹 %s）" % (floor, tname, [round(x / 1000.0, 1) for x in tower.bounds]))
    su = unary_union(list(sp))
    sp_in = [g for g in _split(su.intersection(tower)) if g.area > 1e6] if not su.is_empty else []
    sp_roof = _rails_clean([g for g in _split(su.difference(tower)) if g.area > 1e6]) \
        if not su.is_empty else []
    if not sp_in:
        raise RuntimeError("roof_plans[%s]：楼板在塔楼足迹内为 0 块 ⇒ 塔楼那一层没有地面" % floor)
    diag = {"层": floor, "塔楼层": tname,
            "塔楼足迹_m": [round(x / 1000.0, 2) for x in tower.bounds],
            "墙带_切前_m2": round(_area_m2(list(wp)), 2),
            "墙带_塔内_m2": round(_area_m2(win), 2),
            "改女儿墙_m2": round(_area_m2(par), 2),
            "改女儿墙_块": len(par),
            "屋面板_m2": round(_area_m2(sp_roof), 2),
            "屋面板_块": len(sp_roof),
            "楼板_塔内_m2": round(_area_m2(sp_in), 2)}
    return sp_in, win, {"女儿墙": par, "屋面板": sp_roof, "读数": diag}


# ★★ 2026-10-20 用户令「综合楼旁边有个楼没有楼顶，你把这些相同的问题都处理一下」：
#   根因 = `export_contours._attach_recs` 只在**顶层**出 ROOF/PARAPET；下层任何
#   「本层有板、上一层没盖住」的翼楼/退台，除非楼栋档案点名（`mid_roofs` /
#   `podium_roof` / `roof_plans`），否则头上是一个洞。这里补一条**通用的**规则。
#
#   判据（全仓 105 栋扫描 2026-10-20 实测定阈；判据代码见
#   `过程/_scratch/scan_missing_roofs.py`，与本函数同一套读数）：
#     · 未覆盖块 = 下层抠后楼板 − 上层抠后楼板，按块切；面积 ≥ 8 m²；
#     · **居民证据**：本层 `02_recognize/语义.json` 里**已标注、非露台**房间环
#       与这块的交面积 ≥ 30%（未标注分区按构造铺满整板，拿它当证据是恒真）；
#     · **外沿证据**：这块的边界落在下层楼板外轮廓上的长度占比 ≥ 15%
#       （中庭/内院的边界全在上层楼板的洞圈上，不碰外沿 ⇒ 0）；
#     · **围合证据**：边界落在本层墙带（300 mm）内的长度占比 ≥ 50%。
#   露台另按 `露台: true` 直接扣掉 —— 露台按设计就是露天。
LOW_ROOF_MIN_M2 = 8.0
LOW_ROOF_ROOM = 0.30
LOW_ROOF_OUTER = 0.15
LOW_ROOF_WALL = 0.50
LOW_ROOF_DIAG = []


def _sem_room_polys(floor):
    """`02_recognize/语义.json` 某层的房间环 → `[(poly|None, 露台, 已标注)]`。

    缺件/读不了返回 **None**（与「这层没有房间」= 空表分开，铁律 199）。
    不另算一套分区：用 `recognize_semantics.py` 落的盘（铁律 018/196）。
    """
    p = os.path.join(B.ROOT, "02_recognize", "语义.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    fl = next((x for x in (d.get("层") or []) if str(x.get("层")) == str(floor)), None)
    if fl is None:
        return []
    out = []
    for r in fl.get("房间") or []:
        g = _poly(r.get("ring") or [])
        out.append((g, bool(r.get("露台")), bool(r.get("已标注"))))
    return out


def lower_roof_pieces(slab_lo, slab_hi, floor, wall_lo=None):
    """下层**缺的那块屋面** —— 唯一定义处（build3d 与 export_contours 都调它）。

    返回 `(pieces, 读数)`；不适用时返回 `([], 读数)`，读数是给人/给账看的一句为什么。
    ★ 两块板都是**抠后楼板**（build3d 的 `V_SLAB` = export 的 `_SLAB_BY_FLOOR`），
      与 7→8 台阶屋面同一口径；墙带也是源图原样（两处都传 `wall_polys`）。
    """
    a = unary_union(list(slab_lo)) if slab_lo else None
    if a is None or a.is_empty:
        return [], {"层": floor, "结果": "下层无板（不补）"}
    b = unary_union(list(slab_hi)) if slab_hi else None
    d = a.difference(b).buffer(0) if (b is not None and not b.is_empty) else a
    if d.is_empty:
        return [], {"层": floor, "结果": "上层全盖住（不补）"}
    rs = _sem_room_polys(floor)
    if rs is None:
        return [], {"层": floor, "结果": "语义.json 缺件 ⇒ 不补（不许当「没有房间」）"}
    # 露台按设计露天 ⇒ 先扣掉，别给它盖顶
    ter = [g for g, t, _ in rs if t and g is not None]
    if ter:
        d = d.difference(unary_union(ter)).buffer(0)
        if d.is_empty:
            return [], {"层": floor, "结果": "整块都是露台（不补）"}
    a_bnd = a.boundary.buffer(1.0)
    wall = None
    if wall_lo:
        wu = unary_union(list(wall_lo))
        if not wu.is_empty:
            wall = wu.buffer(300.0)
    out, rows = [], []
    for g in _split(d):
        if g.area < LOW_ROOF_MIN_M2 * 1e6:
            continue
        rr = 0.0
        for rg, t, lab in rs:
            if lab and not t and rg is not None:
                rr += g.intersection(rg).area
        ratio = rr / g.area
        bnd = g.boundary
        outer = (bnd.intersection(a_bnd).length / bnd.length) if bnd.length > 0 else 0.0
        ws = (bnd.intersection(wall).length / bnd.length) if (wall is not None and bnd.length > 0) else 0.0
        row = {"层": floor, "面积_m2": round(g.area / 1e6, 2),
               "标房占比": round(ratio, 3), "外沿占比": round(outer, 3),
               "墙界占比": round(ws, 3),
               "足迹": [round(v / 1000.0, 2) for v in g.bounds]}
        if ratio >= LOW_ROOF_ROOM and outer >= LOW_ROOF_OUTER and ws >= LOW_ROOF_WALL:
            out.append(g)
            row["结果"] = "补屋面"
        else:
            row["结果"] = "不补（证据不足）"
        rows.append(row)
    return out, {"层": floor, "块": rows,
                 "结果": ("补 %d 块 · %.1f m²" % (len(out), _area_m2(out))) if out else "无（不补）"}


def lower_roof_skip(lo, hi, names):
    """这条相邻层对是否**已被别的机制**处理（有则返回机制名，通用规则不许再补一块）。

    ★ 与 `lower_roof_pieces` 一样是**唯一定义处**：build3d 与 export_contours 同调。
    """
    prof = B.profile()
    for e in prof.get("mid_roofs") or []:
        if str(e.get("层")) == str(lo):
            return "mid_roofs"
    rp = prof.get("roof_plans") or {}
    # 上层是「屋面平面」⇒ 那一层的板本身就是屋面；本层是屋面平面 ⇒ 屋面也已经在它身上。
    if hi in rp or str(hi) in rp or lo in rp or str(lo) in rp:
        return "roof_plans"
    if prof.get("podium_roof") and names and str(hi) == str(names[-1]):
        return "podium_roof"
    if str(lo) == "7层" and str(hi) == "8层" and not (rp.get("7层") or rp.get(7)):
        return "roof_step7"
    return ""


def podium_roof_parts(slab_lo, slab_hi):
    """裙房屋面：(板 = 下一层楼板 − 顶层楼板, 女儿墙环带 = 屋面外缘减塔楼)。

    位置全部现算，不画矩形、不手打面积。
    """
    a = unary_union(slab_lo)
    b = unary_union(slab_hi)
    d = a.difference(b).buffer(0) if (not a.is_empty and not b.is_empty) else a
    rp = [g for g in _split(d) if g.area > 1e6]
    rails = []
    for p in rp:
        for g in parapet_ring([p]):
            rails.extend(_split(g.difference(b)) if not b.is_empty else [g])
    # ★ 减法之后再塌一次：`parapet_ring` 里那次塌的是**减塔楼之前**的环，减法会再造短桩。
    return rp, _rails_clean([x for x in rails if x.area > 0])


def roof_step_rails(plate_polys, tower):
    """7→8 台阶屋面**边缘的女儿墙环带**：屋面板外缘内收 `PARAPET_T`，再减掉塔楼轮廓。

    ★ 2026-10-18 用户定案（「保留墙，屋面上加女儿墙」）：7 层翼楼外墙**维持 4.0 m**
      （实测 5/6/7 层墙外包框同为 129.0×83.7 m、墙面积 443/442/382 m² ⇒ 那是真外墙，
      不是立在屋面上的女儿墙），只在**屋面顶（7×层高）**沿翼楼外缘补 1.2 m 女儿墙。
    ★ 本函数是**唯一算法**：build3d 与 export_contours 都调它（铁律 018/174）。
    """
    rails = []
    for p in plate_polys:
        for g in parapet_ring([p]):
            if tower is not None and not tower.is_empty:
                rails.extend(_split(g.difference(tower)))
            else:
                rails.append(g)
    out = [x for x in rails if x.area > 0]
    # ★★ 2026-10-18 实测：内收 + 减塔楼这一步会在环上留一条 3.245 mm 的斜边
    #   （7层 PARAPET-005/012，各 26.9 m²：板边界上有 1.8 mm 的台阶，
    #    内收 250 mm 后被放大成一条 2.7×1.8 mm 的斜边）。楼板本身没有短边
    #   （ROOF_STEP 7 个环实测 0 条），所以这一条是**本函数造出来的**，
    #   按本仓「细到 6.25 mm 不算实体」那条线塌掉（`RING_EDGE_MIN_MM`，与 J-10.8-00 ⑯ 同源）。
    return _rails_clean(out) if out else out


def _zone_box(z):
    try:
        x0, y0, x1, y1 = float(z[0]), float(z[1]), float(z[2]), float(z[3])
    except Exception:
        return None
    return sg.box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def roof_stair_polys(v):
    """顶楼楼梯房：位置 = 顶层**楼梯锚区**（客观，来自源件文字锚）；高是假设值。"""
    return [b for b in (_zone_box(z) for z in v["zones"]) if b is not None and b.area > 0]


def _door_notch(outer, t_mm, w_mm):
    """在房间外皮**最长的那条边**正中间切一个门洞缺口（宽 `w_mm`、深过墙厚）。

    ★ 为什么是「缺口」不是「洞」：本仓出件是**多边形拉伸**，没有布尔减（洞写进记录就恒空，
      见 `export_contours.py::_rec` 的实测）。源图的门也是「墙线在门处断开」——
      跟着同一种形制走，墙在门那儿断开，不是墙上凿个方孔。
    """
    x0, y0, x1, y1 = outer.bounds
    eps = 1.0                                  # mm：切穿外皮，免留一条零宽薄边
    if (x1 - x0) >= (y1 - y0):
        xc = (x0 + x1) / 2.0
        return sg.box(xc - w_mm / 2.0, y0 - eps, xc + w_mm / 2.0, y0 + t_mm + eps)
    yc = (y0 + y1) / 2.0
    return sg.box(x0 - eps, yc - w_mm / 2.0, x0 + t_mm + eps, yc + w_mm / 2.0)


def _room_shell(outer, t_mm, w_mm, h_m):
    """一块房间外皮 → (环带墙多边形表, 顶板外皮, 墙高 m)。做不出来返回 None。"""
    inner = outer.buffer(-t_mm, join_style=2)
    if inner.is_empty or inner.area <= 0:
        return None
    ring = outer.difference(inner).difference(_door_notch(outer, t_mm, w_mm))
    walls = [g for g in _split(ring) if g.area > 1.0]
    if not walls:
        return None
    return (walls, [outer], h_m)


def _drawn_room_outer(v, zone_box, t_mm):
    """楼梯锚区 → **源件画出来的那间房的外皮**（墙带内洞 = 房间内空，外扩一个墙厚）。

    ★★ 2026-10-19 用户「你继续比对 st4 和 c001 改对啊」：c001 5层图上，楼梯间的墙是墙带上的
      **一个洞**（实测 `wall[3] 洞[4]`：7.03×2.73 m = 16.1 m²，包住梯段锚区中心）。
      而 `stair_zones` 只是**梯段的活动范围**（4.6×2.96 m = 13.6 m²）——
      拿它当房间，屋面附属用房会建小一圈（ts4 同位置是一座大得多的塔楼）。
      改用「洞 + 一个墙厚」⇒ 房间外皮 = 图上那圈墙的外表面。
    ★ 只认**把锚区中心包住的最小洞**：同一条墙带上有 29 个洞（走廊/大堂/各房间），
      洞口 952 m² 的大堂也包得住中心，但那是另一间房 ⇒ 取面积最小的那个。
      一个洞都找不到 ⇒ 返回 None，调用方退回锚区框（与改前逐位相同，零回归）。
    """
    c = zone_box.centroid
    reach = zone_box.buffer(ROOF_ROOM_MAX_GROW_M * 1000.0)
    best = None
    for _shell, holes in (v.get("walls") or []):
        for h in (holes or []):
            try:
                inner = sg.Polygon(h)
            except Exception:                                          # noqa: BLE001
                continue
            if not inner.is_valid:
                inner = inner.buffer(0)
            if inner.is_empty or inner.geom_type != "Polygon":
                continue
            if not inner.contains(c):
                continue
            # ★ 面积最小的那个洞可能仍是**另一间房**（大堂、走廊都包得住中心）⇒ 再加一道距离闸：
            #   房间不许比锚区大出 ROOF_ROOM_MAX_GROW_M 以外。
            if not reach.contains(inner):
                continue
            if best is None or inner.area < best.area:
                best = inner
    if best is None or best.area <= 0:
        return None
    outer = best.buffer(t_mm, join_style=2)
    if outer.is_empty or outer.geom_type != "Polygon":
        return None
    return outer


def roof_room_parts(v):
    """屋面附属用房 → **结构体**（环带墙 + 顶板 + 门洞缺口）。

    ★★ 2026-10-18 用户令「楼梯间和电梯房一块儿做；有的顶楼它是没有楼梯的，就不要做这个东西」。
       ⇒ 做不做**由源件说**：`stair_zones` 有就建楼梯间、`lifts` 有就建电梯机房；
         两样都没有 ⇒ 这里返回空表 —— 那是「这栋顶楼没有这件」，不是「我没量到」。
    ★ 轮廓是客观的：楼梯间优先取**图上画出来的房间外皮**（见 `_drawn_room_outer`），
      图上没画单洞环带时才退回顶层 `stair_zones`（源件文字锚 + 梯段）；
      机房取 `lifts`（源件墙层上的闭合矩形 = 井道内空）外扩一个墙厚。
    ★ 高度、墙厚、门洞全是**假设值**（参数表 `构件/顶部`），必须与「照图建的」分开看。
    """
    t_mm = ROOF_ROOM_T * 1000.0
    w_mm = ROOF_ROOM_DOOR_W * 1000.0
    out = {"stairs": [], "lift_rooms": []}
    for z in (v.get("zones") or []):
        b = _zone_box(z)
        if b is None or b.area <= 0:
            continue
        outer = _drawn_room_outer(v, b, t_mm) or b
        shell = _room_shell(outer, t_mm, w_mm, ROOF_STAIR_H)
        if shell is not None:
            out["stairs"].append(shell)
    rects = [_poly(r) for r in (v.get("lifts") or [])]
    rects = [p for p in rects if p is not None and p.area > 0]
    if rects:
        core = unary_union(rects).buffer(t_mm, join_style=2)   # 井道内空 → 机房外皮
        # ★★ 2026-10-18：**逐根井道出机房**，不是拿并集整个当一间。
        #   实测 11层三根井道并集是 **MultiPolygon**（3 块互不相连，最近两块也隔 0.28 m）——
        #   整块当一间时 `_door_notch` 按**并集包围盒**的最长边切门，那一刀落在两块之间的空处，
        #   三面墙上**一个门洞都没有**（而顶板又会因为 MultiPolygon 拉伸抛错而被静默吞掉）。
        #   逐块做 ⇒ 门洞落在**每根井道自己的墙**上。每根井道各是一间机房，这是源件给的分块。
        for part in _split(core):
            shell = _room_shell(part, t_mm, w_mm, ROOF_LIFT_H)
            if shell is not None:
                out["lift_rooms"].append(shell)
    return out


def lift_voids(v):
    """竖井**井道内空**多边形（源件墙层上的闭合矩形）。这是客观量，井壁由它内缩得到。"""
    out = []
    for rect in v["lifts"]:
        p = _poly(rect)
        if p is not None:
            out.extend(_split(p))
    return out


def door_voids(v, walls=None, diag=None):
    """**门洞** → 多边形列表（只从墙带里扣，楼板不因门开洞）。

    ★★ 2026-10-17 C005 的必要性：c006 的源图**墙线在门处断开**（实测 1 层 116 樘门 bbox 内
      0 条墙线穿过），所以那边 `carve` 只喂井道内空就够了；C005 的墙线**连续穿过门洞**
      （1264 条墙层折线一路画过去）⇒ 不显式抠，门就是墙上一块实心混凝土。
    ★ 为什么先与墙带求交再抠：门符号的 bbox 含**门扇 + 开启弧**，短边 1220~1320 mm，
      而墙只有 240 mm。直接拿 bbox 抠会把门边的房间/邻墙也削掉一截；
      取 `门洞 ∩ 墙带` ⇒ 被扣掉的**只有墙**，且门头墙（同一块足迹）能原样补回来。
    ★ 返回 `[]` 是「本图墙线已断，无需抠」（c006），不是「没量到」——调用方按 `door_mode` 分辨。
    """
    rects = v.get("door_voids") or []
    if not rects:
        return []
    W = unary_union(walls) if walls else None
    out = []
    for r in rects:
        p = _poly(r)
        if p is None:
            continue
        if W is not None and not W.is_empty:
            p = p.intersection(W)
        for q in _split(p):
            q = _punch_across(q, W, diag, ref=p)   # ★ 跨墙方向必须**打穿**整条墙带（见函数 docstring）
            out.append(_clamp_door_across(q, walls, diag))
    return [x for x in out if x.area > 0]


def _span_on(q, line, c, vx, vy):
    """q 在**跨墙线**上自己占的跨度（mm）；质心那段量不到 ⇒ None。

    ★ 与 `_punch_across` 里的墙带读数用**同一条线、同一个坐标系**（铁律 197）。
    """
    inter = q.intersection(line)
    segs = [inter] if inter.geom_type == "LineString" else list(getattr(inter, "geoms", []))
    for s in segs:
        if s.geom_type != "LineString":
            continue
        p0, p1 = s.coords[0], s.coords[-1]
        s0 = (p0[0] - c.x) * vx + (p0[1] - c.y) * vy
        s1 = (p1[0] - c.x) * vx + (p1[1] - c.y) * vy
        lo, hi = min(s0, s1), max(s0, s1)
        if lo - 1e-6 <= 0.0 <= hi + 1e-6:
            return hi - lo
    return None


def _punch_across(q, W, diag=None, ref=None):
    """门洞沿**跨墙**方向补到这一处墙带的整个厚度（把洞口打穿）。

    ★★ 2026-10-19（用户报「005 没有显示，透明的时候才看得到，X=49103 Y=47175」实测根因）：
      `门洞框 ∩ 墙带` 只取到**框自己那一段**（c005 三层中位 275 / 265.5 / 265.5 mm），
      而墙带是**源图线按笔宽栅格化 + 闭核**出来的，比框两边各胖 25~35 mm
      （三层逐樘量：32/30/35 樘**每一樘**都留墙皮，中位 25/35/35 mm）。
      ⇒ 洞口上方留一圈墙皮：门扇（y 0~2.1）与门头墙（y 2.1~层高）都藏在墙皮**后面**，
        不点「墙体半透明」就看不见。GLB 实测：门洞框内 y=1.5 处墙材 z 区间
        [-47.080,-47.055]（25 mm），门扇在 [-47.225,-47.175] —— 正好躲在它后面。
      ★ 量法不拍常数：过洞口质心沿跨墙方向取一条线，与**未抠的墙带**求交，
        取**含质心那一段**，把洞口跨墙方向撑到这段两端；沿墙方向一个字不动。
      ★ 量不到（质心不在墙里 / 那段比洞口还短）⇒ 原样返回（宁可不动，也不静默扩大洞口）。
      ★ 记账：`跨墙打穿` 块数 + `墙皮最厚`（铁律 158：拦住的/改动的都要能读出来）。
    ★★ 2026-10-20（用生成 DXF 反查 c004 1 层时发现）：**方向必须取自门洞框 `ref`，不能取自
      `q`**。`q` 是「门洞框 ∩ 墙带」，在墙带端头只剩一条**沿墙 20 mm、跨墙 275 mm** 的薄片；
      它的「长边」是跨墙方向 ⇒ u/v 互换，`_span_on` 于是沿**墙的方向**量出 1510 的跨度，
      把洞口往墙里捅进 1470 mm。实测 c004 1 层每樘门都这样：53710~55220、57570~59085、
      59388~60895 三块 1.5 m 的假洞口把走廊墙整段吃了（门头墙因此连成一条肥板）。
      门洞框 `ref` 的长边才是「沿墙方向」——洞口该往哪边打穿，只有它说了算（铁律 197）。
      ★ 但 `ref` **近方形**（长宽比 < 1.5）时回到 `q` 的长边——那时 ref 的长边可能是跨墙的，
        取它会犯同一个错；`q` 是「框∩墙带」，墙带 300 厚必然沿墙拉长（c005/c001 走这条）。
      另加护栏：跨墙补的量不许超过洞口长边的一半（那是墙皮，不是洞口）。
    """
    if q.is_empty or q.geom_type != "Polygon" or W is None or W.is_empty:
        return q
    # ★ 方向取 `ref` **仅在它的长宽比够明显时**（门宽 : 门框深 ≥ 1.5）；`ref` 近方形时
    #   长边可能是跨墙那条，取它会和旧错法同形。近方形 ⇒ 退回 `q` 的长边（q 是「框∩墙带」，
    #   墙带 300 厚 ⇒ q 一定沿墙拉长），c005/c001 那族符号门因此**逐位不变**。
    _rq = q.minimum_rotated_rectangle
    r = _rq
    if ref is not None and not ref.is_empty:
        _rr = ref.minimum_rotated_rectangle
        _ep = list(_rr.exterior.coords)[:4]
        _el = sorted((((_ep[i][0] - _ep[(i + 1) % 4][0]) ** 2
                       + (_ep[i][1] - _ep[(i + 1) % 4][1]) ** 2) ** 0.5
                      for i in range(4)), reverse=True)
        if _el[0] >= 1.5 * max(_el[1], 1e-9):
            r = _rr
    pts = list(r.exterior.coords)[:4]
    es = []
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        es.append((((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5, a, b))
    lo_e = max(es, key=lambda e: e[0])
    L = lo_e[0] or 1.0
    ux, uy = (lo_e[1][0] - lo_e[2][0]) / L, (lo_e[1][1] - lo_e[2][1]) / L
    vx, vy = -uy, ux                                    # 跨墙方向
    # ★ 量跨度的那条线必须过**被抠的那块** `q`（墙里的那一片），过 `ref` 中心可能落进房间。
    c = q.centroid if q.geom_type == "Polygon" else r.centroid
    if not q.contains(c):
        c = q.representative_point()
    # 沿墙跨度只取 `q` 自己的（不许拿门洞框的——那会把墙补到洞口两侧去）；
    # 方向 u/v 才取自 `ref`。跨墙厚度由下面在**同一条线上**实测（`_span_on`）。
    _qpts = list(q.exterior.coords)
    _pu = [((x - c.x) * ux + (y - c.y) * uy) for x, y in _qpts]
    a0, a1 = min(_pu), max(_pu)
    line = sg.LineString([(c.x - 1500 * vx, c.y - 1500 * vy),
                          (c.x + 1500 * vx, c.y + 1500 * vy)])
    inter = line.intersection(W)
    segs = [inter] if inter.geom_type == "LineString" else list(getattr(inter, "geoms", []))
    best = None
    for s in segs:
        if s.geom_type != "LineString":
            continue
        p0, p1 = s.coords[0], s.coords[-1]
        s0 = (p0[0] - c.x) * vx + (p0[1] - c.y) * vy
        s1 = (p1[0] - c.x) * vx + (p1[1] - c.y) * vy
        lo, hi = min(s0, s1), max(s0, s1)
        if lo - 1e-6 <= 0.0 <= hi + 1e-6:
            best = (lo, hi)
            break
    if best is None:
        return q
    # ★★ 2026-10-19 第二错（用户指认 X=23730 Y=37375 仍在墙里）：原先拿**最小外接矩形**的
    #   跨墙厚（b1-b0）当「洞口厚度」去和墙带比。这块洞口外接矩形厚 300、墙带也 300
    #   ⇒ add=0 直接返回；可**洞口自己在跨墙线上只有 275**（墙带相对门框偏了 25：
    #   带 37255..37555，洞口 37280..37555）⇒ 墙皮照旧留着。
    #   铁律 197：两个估计器不许串用 —— 这里必须用**同一条线上**实测的跨度。
    sq = _span_on(q, line, c, vx, vy)
    if sq is None:
        return q
    add = (best[1] - best[0]) - sq
    if add <= 1.0:                       # 墙带不比洞口厚 ⇒ 本来就没墙皮
        return q
    # ★ 2026-10-20 护栏：跨墙补的量是**墙皮**（全仓实测中位 25~35 mm），不可能是一个门宽。
    #   `add` 超过洞口长边的一半 ⇒ 这条线量到的不是墙厚，是沿墙的一整段 —— 宁可不动。
    if add > 0.5 * max(L, 1.0):
        return q
    nb0, nb1 = best
    strip = sg.Polygon([
        (c.x + a0 * ux + nb0 * vx, c.y + a0 * uy + nb0 * vy),
        (c.x + a1 * ux + nb0 * vx, c.y + a1 * uy + nb0 * vy),
        (c.x + a1 * ux + nb1 * vx, c.y + a1 * uy + nb1 * vy),
        (c.x + a0 * ux + nb1 * vx, c.y + a0 * uy + nb1 * vy)])
    # ★ 只往**墙带里**补：扩出来的块再与未抠的墙带求交，绝不把洞口伸进房间/邻墙。
    keep = [g for g in _split(unary_union([q, strip]).intersection(W))
            if g.geom_type == "Polygon" and g.area > 0]
    poly = max(keep, key=lambda g: g.area) if keep else None
    if diag is not None and poly is not None:
        diag["跨墙打穿"] = diag.get("跨墙打穿", 0) + 1
        diag["墙皮最厚"] = max(diag.get("墙皮最厚", 0.0), round(add, 1))
    # 兜底：结果不得比原洞口小（小了说明这一刀把洞口削掉了 ⇒ 宁可不动）
    return poly if (poly is not None and poly.area >= q.area * 0.999) else q


def _band_width(p):
    """墙块的**平均带宽**（mm）= 2·面积/周长 —— 「这一处的墙有多厚」的现算读数。

    为什么不是「沿法向扫一条线」：墙带是**连成一片的网**（c004 一层 5 块里最大一块
    外框 70.4×18.2 m），任意一条扫线都会穿过转角/相邻墙段，量出 720~2030 的假厚度；
    而 2A/P 对一条长墙给的就是**带宽本身**（实测：外墙网 408、角柱 206、轮廓中位 373）。
    盲区：转角处与柱墩上偏胖（面积/周长都被短边抬高）—— 只用来**夹深度上限**，不当作厚度真值。
    """
    return (2.0 * p.area / p.length) if p.length > 0 else 0.0


def _clamp_door_across(q, walls, diag=None):
    """把一块门洞在**跨墙方向**夹到局部墙厚上（见 `DOOR_VOID_MAX_RATIO` 那段）。

    沿墙方向一个字不动（洞口宽仍是源图给的净宽）；跨墙方向若比局部墙带宽得多，
    就在这块墙上滑一个「墙带宽」的窗口，取**窗内墙材最多**的位置 —— 不拍坐标、不拍经验值。
    量不到墙（walls 空 / 带宽非正）或本来就不厚 ⇒ **原样返回**（宁可不动，也不静默丢门）。
    """
    if q.is_empty or not walls:
        return q
    # ★★ 2026-10-18 c004 三个大门：传进来的 q 已经是 `门洞框 ∩ 墙材`，**不再二次夹厚**。
    #   实测：南入口那三樘 2.4 m 大门，门洞框压在 21030..21625（597 深，含入口平台与墙），
    #   本函数拿整块墙网的 2A/P≈386 当墙厚，把门洞夹到 21030..21373，
    #   留下 21373..21625 一道 252 的实墙 —— 门外看有洞，进去 340 mm 撞墙。
    #   夹厚的本意是「别让门符号 bbox 削到房间」，但求交已经保证剩下的全是墙；
    #   门要通，就得把它压在下面的墙整块打穿。真正隔开的平行墙在 `_split` 那一步
    #   就是另起一块，不会被这块牵连。
    #   守门的是闸不是这里：`gates/J-10.9-09_封死房.py` + 门头墙闸。
    if diag is not None:
        diag["不夹厚"] = diag.get("不夹厚", 0) + 1
    return q


def _clamp_door_across_old(q, walls, diag=None):
    """（2026-10-18 之前的实现，保留做对照，不再调用；见上。）"""
    if q.is_empty or not walls:
        return q
    x0, y0, x1, y1 = q.bounds
    along_x = (x1 - x0) >= (y1 - y0)
    across = (y1 - y0) if along_x else (x1 - x0)
    # 本块门洞压在**哪一块墙**上（重叠面积最大者）—— 厚度只从那一块量
    best, best_a = None, 0.0
    for w in walls:
        if not q.intersects(w):
            continue
        a = q.intersection(w).area
        if a > best_a:
            best, best_a = w, a
    tk = _band_width(best) if best is not None else 0.0
    if tk <= 0 or across <= DOOR_VOID_MAX_RATIO * tk:
        return q
    step = max(tk / 8.0, 25.0)
    lo, hi = (y0, y1) if along_x else (x0, x1)
    best_off, best_ov = None, -1.0
    t = lo
    while t <= hi - tk + 1e-6:
        band = (sg.box(x0 - 1.0, t, x1 + 1.0, t + tk) if along_x
                else sg.box(t, y0 - 1.0, t + tk, y1 + 1.0))
        a = q.intersection(band).area
        if a > best_ov:
            best_ov, best_off = a, t
        t += step
    if best_off is None:
        return q
    band = (sg.box(x0 - 1.0, best_off, x1 + 1.0, best_off + tk) if along_x
            else sg.box(best_off, y0 - 1.0, best_off + tk, y1 + 1.0))
    r = q.intersection(band)
    if r.is_empty or r.area <= 0:
        return q
    if diag is not None:
        diag["夹厚"] = diag.get("夹厚", 0) + 1
        diag["夹厚_由_mm"] = diag.get("夹厚_由_mm", 0.0) + across
        diag["夹厚_到_mm"] = diag.get("夹厚_到_mm", 0.0) + tk
    return r


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


def step_polys(v):
    """入口台阶/平台外框（已从墙掩膜剔除，统一 20 cm 高）。"""
    out = []
    for rect in v.get("steps") or []:
        p = _poly(rect)
        if p is not None and p.area > 0:
            out.extend(_split(p))
    return out


# ★ 门头墙的**记账**（同 `STAIR_DIAG` 的道理）：补出来的缺口里几个没门、几个超限被丢。
#   用户报的「门上面的缺失」如果修不干净，这里必须留下**读数**而不是一片安静（铁律 158）。
LINTEL_AUDIT = []


def lintel_module(v, h, doors=None, floor=None, seed=None):
    """门头墙 → `[(poly, z_rel_m, h_m)]`（契约与 `stair_steps` 逐字段相同）。

    ★ 本函数**只喂不算**：几何全在 `parts_lib.lintel_module`（那边有完整的推导与出处）。
      这里负责的是——从源图把**墙带**与**门扇**取出来递进去。
      `doors` 允许外部传进来复用（`door_polys` 有 `DOOR_AUDIT` 记账副作用，
      每个消费者每层只该调**一次**）。
    ★ `floor` 只为了记账可读：`LINTEL_AUDIT` 里每一条必须说得出是**哪一层**，
      否则「这一层漏了 7 扇」在汇总表里找不到主语（铁律 174）。
    ★ `seed`（2026-10-18）：调用方按**门洞**构造的板（`door_voids` 的产物）。
      必须**递进去**、不许在返回后拼 —— 拼在外面的话，`对照.json` 量的还是缺口法那一路，
      交付件里却多了这批板（c055 实测：件里每扇都有，账上只认 16/181）。
    """
    out, diag = PL.lintel_module(wall_polys(v),
                                 doors if doors is not None else door_polys(v),
                                 float(h) * 1000.0,
                                 seed_plates=seed)
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


def _stair_clear_cut():
    """本次落位的那几座楼梯 → 清空区多边形列表（mm），= 包络并集**内缩** `STAIR_CLEAR_PAD_MM`。

    ★ 返回 `None` 与返回 `[]` 是**两句不同的话**（铁律 199）：
      · `None` = 本层**没有楼梯**（`STAIR_ENV` 空）⇒ 无从谈清空，调用方不该印「已清 0 m²」；
      · `[]`  = 有楼梯、但内缩后清空区是空的 ⇒ 真的没扣到东西，**必须记账报出来**。
    ★ 为什么要内缩见 `STAIR_CLEAR_PAD_MM`（不内缩会削到围合墙，10层实测差 30 mm）。

    ★ 为什么不直接 `buffer(-PAD)` 就完事：shapely 的布尔运算会在结果环上留下**重复顶点**
      （实测 10层：`min_edge` 出现 0.0 mm 的一条边，而它**不是**新削出来的口子 ——
      `simplify(0.0, preserve_topology=True)` 也去不掉，因为它本来就是零长度）。
      这类零长度边会一路带进 `export_contours` 的 0.1 mm 栅格取整、再进闭环判据。
      ⇒ 在这里把**相邻重复顶点**删掉，让下游拿到的是干净的环。
    """
    if not STAIR_ENV:
        return None
    try:
        # ★ `join_style=2` = mitre（直角）—— 同 `parapet_polys` 的理由：默认是**圆角**，
        #   那样内缩后的扣除区四角会变成圆弧，等于把梯间四角**削出一个弧形缺口**
        #   （本该是方正的一块被抠成圆角）。
        u = unary_union(STAIR_ENV).buffer(-STAIR_CLEAR_PAD_MM, join_style=2)
    except Exception as e:                       # 包络退化（零宽/自交）—— 说出来，别退成静默
        STAIR_CLEAR_DIAG.append({"层": _CUR["层"], "包络块": len(STAIR_ENV),
                                 "清空区块": None, "清空区_m2": None,
                                 "★": "清空区算不出（包络并集失败：%s）⇒ 本层**没清**" % e})
        return []
    parts = [x for x in (_dedupe_ring(q) for q in _split(u)) if x.area > 0]
    if not parts:
        STAIR_CLEAR_DIAG.append({"层": _CUR["层"], "包络块": len(STAIR_ENV),
                                 "清空区块": 0, "清空区_m2": 0.0,
                                 "★": "清空区为空（包络内缩 %.0f mm 后没了）⇒ 本层**没清**"
                                      % STAIR_CLEAR_PAD_MM})
    return parts


def stair_alt(prev_v):
    """跨层借形的**邻层读数**（= 本层的上一层几何）→ `alt` 字典，或 `None`（没有上一层）。

    ★ 为什么要单独成一个函数：`main()`（参照件）与 `export_contours`（正式件的轮廓）
      都必须拿**同一个** `alt`。两边各写一份，就会出现「参照件借了上一层、正式件没借」
      —— 两个估计器（铁律 018/174），而症状是两边楼梯形状不同（实测正式件原先就**没传 alt**）。
    """
    if prev_v is None:
        return None
    return {"wells": _well_geom(prev_v.get("treads") or []),
            "zones": [sg.box(_z[0], _z[1], _z[2], _z[3])
                      for _z in (prev_v.get("zones") or [])]}


def stair_and_clear(v, h, alt=None):
    """一趟楼梯落位 → `(逐级块, 清空区多边形列表)`。

    ★★ **两个产物必须同源**（2026-10-16 梯间清空）：清空区就是**这一趟落位**的包络内缩。
      调用方**不许**自己再调一次 `stair_steps` 去算清空区 —— 那样在「本层装不下双跑、
      借了上一层」的楼层上，扣的是**没借形那个盒子**，墙按 A 盒扣、梯画在 B 盒。
    ★ 返回 `(steps, None)`：`steps` 非空但 `None` = 有楼梯却没算出清空区（已记账，见
      `STAIR_CLEAR_DIAG`）；`steps` 空 = 本层本来就没梯。
    """
    STAIR_ENV[:] = []
    steps = list(stair_steps(v, h, alt=alt))
    return steps, _stair_clear_cut()


def _snap_ring_mm(p, step=None):
    """把多边形顶点量化到 `step` mm 网格 → 新多边形；失败返回 None。

    ★ 只用于**裁出来的**梯块（见 `CLIP_SNAP_MM`）。失败（量化后自交/退化）返回 None，
      调用方保留原样并记数 —— **宁可留一条 0.03 mm 的错位，也不许悄悄丢掉一块实体**。
    """
    st = CLIP_SNAP_MM if step is None else float(step)

    def _q(ring):
        c = [(round(float(x) / st) * st, round(float(y) / st) * st) for x, y in ring.coords]
        if len(c) > 1 and c[0] == c[-1]:
            c = c[:-1]
        return c

    try:
        q = _dedupe_ring(sg.Polygon(_q(p.exterior), [_q(r) for r in p.interiors]))
    except Exception:
        return None
    if q.is_empty or not q.is_valid or q.area <= 0:
        return None
    return q


def clip_steps_to_walls(steps, walls):
    """把逐级梯块**扣掉墙带** —— 楼梯不许穿墙（2026-10-17 用户令「楼梯还有破坏墙面的情况」）。

    ★ 为什么不是「把墙再往里削」：`_stair_clear_cut()` 已经按包络**内缩 50 mm** 削过墙，
      而梯块本身仍是足尺 ⇒ 实测 c005 1 层有 **30 mm** 的边压在围合墙上（`WALL-002`
      x 56730–56760）。再往里削墙 = 用**削墙**掩盖**梯子越界**，墙的厚度从此不是图纸的了。
      正确方向是反过来：**墙不动，梯块裁到墙边**。
    ★ 两边（参照件 `main()` 与正式件 `export_contours`）必须调**同一个函数**，
      否则又成两个估计器（铁律 018/174）。
    ★ 返回 `(新 steps, 读数)`；读数字段：`相交块` / `裁掉_m2` / `碎块` / `消失块`。
      全部由 shapely 实算，不手打。
    """
    diag = {"相交块": 0, "裁掉_m2": 0.0, "碎块": 0, "消失块": 0,
            "量化块": 0, "量化未用": 0}
    if not steps or not walls:
        out = list(steps or [])
        if out:
            _align_steps(out, diag)
        return out, diag
    wu = unary_union(walls)
    if wu.is_empty:
        out = list(steps)
        _align_steps(out, diag)
        return out, diag
    out = []
    for poly, zrel, hm in steps:
        if not poly.intersects(wu):
            out.append((poly, zrel, hm))
            continue
        diag["相交块"] += 1
        before = poly.area
        q = poly.difference(wu)
        if q.is_empty:
            diag["消失块"] += 1
            diag["裁掉_m2"] += before / 1e6
            continue
        parts = _split(q)
        if not parts:
            diag["消失块"] += 1
            continue
        if len(parts) > 1:
            diag["碎块"] += 1
        for part in parts:
            if part.area <= 1.0:              # < 1 mm²：布尔运算的碎渣，不是梯级
                continue
            # ★★ 2026-10-17：裁出来的新边界会带**零点几毫米**的残边（shapely 从墙顶点旁边
            #   擦过去），而 `J-10.8-00` ⑪ 的判据是「最短边 ≥ 6.25 mm」。用**本仓既有的**
            #   `_drop_short_edges`（同一个阈值、同一个函数），不另立一个数。
            #   只在**真裁过**的块上做；没相交的块一个顶点都不动。
            fixed, _d = _drop_short_edges([part])
            if len(fixed) == 1:
                part = fixed[0]
            # ★★ 2026-10-17：再量化到 `CLIP_SNAP_MM` 网格 —— 相邻梯块的共同边本来是
            #   同一个数，布尔运算会把它算成 96798.5308023 vs 96798.5（差 0.03 mm），
            #   沿 1590 mm 就是 49 mm² 重叠（⑫ 红）。量化后重新对齐成同一条边。
            sn = _snap_ring_mm(part)
            if sn is not None:
                part = sn
                diag["量化块"] = diag.get("量化块", 0) + 1
            else:
                diag["量化未用"] = diag.get("量化未用", 0) + 1
            diag["裁掉_m2"] += (before - part.area) / 1e6
            out.append((part, zrel, hm))
    diag["裁掉_m2"] = round(diag["裁掉_m2"], 4)
    # ★★ 2026-10-17：**同层共面梯块不许互相压**（`J-10.8-00` ⑫）。
    #   来源不只是「被墙裁过的块」——双跑梯的梯段/平台是**旋转 + 布尔**算出来的，
    #   共同边会落在 126529.9997921 / 96798.5308023 这种浮点尾巴上，
    #   与隔壁块的整数边（126530.0 / 96798.5）差 0.03 mm，沿 1590 mm 就是 49 mm²。
    #   处置：**成对量化到 `CLIP_SNAP_MM` 网格**再判；量化后仍相交才退回「后一块减前一块」。
    _align_steps(out, diag)
    return out, diag


def _align_steps(out, diag, max_mm2=500.0):
    """同层共面梯块的对齐/去重叠（原地改 `out` 里的多边形）。"""
    byz = {}
    for i, (_p, z, _h) in enumerate(out):
        byz.setdefault(round(float(z), 3), []).append(i)
    for idxs in byz.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                pi, pj = out[i][0], out[j][0]
                if not pi.bounds[2] > pj.bounds[0] or not pj.bounds[2] > pi.bounds[0]:
                    continue
                if not pi.bounds[3] > pj.bounds[1] or not pj.bounds[3] > pi.bounds[1]:
                    continue
                inter = pi.intersection(pj)
                if inter.is_empty or inter.area <= 0:
                    continue
                diag["压块对"] = diag.get("压块对", 0) + 1
                si, sj = _snap_ring_mm(pi), _snap_ring_mm(pj)
                if si is not None and sj is not None:
                    pi2, pj2 = si, sj
                    if pi2.intersection(pj2).area <= 0:
                        out[i] = (pi2, out[i][1], out[i][2])
                        out[j] = (pj2, out[j][1], out[j][2])
                        diag["量化对齐"] = diag.get("量化对齐", 0) + 1
                        continue
                if inter.area <= max_mm2:
                    q = pj.difference(pi)
                    parts = _split(q)
                    if parts:
                        parts, _d = _drop_short_edges(parts)
                    if len(parts) == 1:
                        out[j] = (parts[0], out[j][1], out[j][2])
                        diag["去重叠块"] = diag.get("去重叠块", 0) + 1
                        continue
                diag["未去重叠"] = diag.get("未去重叠", 0) + 1


def _dedupe_ring(p):
    """去掉**相邻重复顶点**（含首尾闭合那一对），返回同形的 Polygon。"""
    def _clean(ring):
        c = [(float(x), float(y)) for x, y in ring.coords]
        o = [c[0]]
        for q in c[1:]:
            if abs(q[0] - o[-1][0]) > 1e-9 or abs(q[1] - o[-1][1]) > 1e-9:
                o.append(q)
        if len(o) > 1 and abs(o[0][0] - o[-1][0]) <= 1e-9 and abs(o[0][1] - o[-1][1]) <= 1e-9:
            o.pop()
        return o
    ext = _clean(p.exterior)
    if len(ext) < 3:
        return p                                   # 退化了就原样返回，别造一个空 polygon 出来
    holes = [h for h in (_clean(r) for r in p.interiors) if len(h) >= 3]
    return sg.Polygon(ext, holes)


def _collapse_short(c, tau):
    """闭合环坐标表 → 把**短于 tau 的边**逐一塌掉（删掉该边的一个端点）。

    → `(新坐标表, 删了几个点, 被删的最长短边 mm)`
    ★ 删哪一个：选「删掉之后新边**更长**」的那个端点 —— 否则会把短边连锁推到下一条边上去。
    ★ 每删一个点，环就少一个顶点；删到环不足 3 点或没有短边为止（最多 `len(c)` 轮）。
    """
    c = list(c)
    m = len(c)
    if m < 4:
        return c, 0, 0.0
    n, longest = 0, 0.0
    for _ in range(m):
        k = len(c)
        if k < 4:
            break
        hit = None
        for i in range(k):
            a, b = c[i], c[(i + 1) % k]
            d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            if d < tau:
                hit, longest = i, max(longest, d)
                break
        if hit is None:
            break
        i, j = hit, (hit + 1) % k
        pa, na = c[(i - 1) % k], c[(i + 2) % k]
        if _seg(pa, na) >= _seg(pa, c[j]):        # 删 i 留 j：新边 pa—c[j]
            del c[i]
        else:                                     # 删 j 留 i：新边 c[i]—na
            del c[j]
        n += 1
    return c, n, round(longest, 3)


def _seg(a, b):
    return ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5


def _drop_short_edges(polys):
    """把环上**短于 `RING_EDGE_MIN_MM` 的边**塌掉 → `(新多边形列表, 读数)`。

    ★ 只允许用在「**清空区那一刀切出来的**」多边形上（扣完墙带/楼板的结果）——
      那一刀的边界是从**楼梯包络**推出来的矩形，与墙的真实几何无关；它会从离某个墙顶点
      零点几毫米的地方切过去，于是墙被剜下一小条，那条残条的边就是 0.99~5.7 mm。
      把边界挪开治不了（顶点间距 3~4.3 mm < 阈值窗 6.25 mm，平移只能换个长度），见
      `RING_EDGE_MIN_MM` 的注释与 `_scratch/probe_staircut_edge_ab.py` 的 A/B。
    ★ 代价（铁律 028）：删点后环会**局部挪动**，单点最多移 `RING_EDGE_MIN_MM` 量级；
      这个阈值**不是新立的**，就是本仓「细到这个程度不算实体」那条线（`参数.json`），
      闸 `J-10.8-00` ⑯ 断言过它与闸内常数一致。读数里把**面积变化**报出来，别只印「清干净了」。
    ★ 保守兜底：哪个多边形塌完之后环 < 3 点或自交，就**原样留着它**（宁可留一条短边，
      也不许悄悄丢一块实体）—— 并记数。
    """
    out = []
    drop = bad = 0
    a0, a1 = 0.0, 0.0
    for p in polys:
        a0 += p.area
        rings = []
        for ring in [p.exterior] + list(p.interiors):
            c = [(float(x), float(y)) for x, y in ring.coords]
            if len(c) > 1 and c[0] == c[-1]:
                c = c[:-1]
            c, _n, _l = _collapse_short(c, RING_EDGE_MIN_MM)
            drop += _n
            if len(c) < 3:
                break
            rings.append(c)
        else:
            q = _dedupe_ring(sg.Polygon(rings[0], rings[1:]))
            if q.is_valid and q.area > 0:
                out.append(q)
                a1 += q.area
                continue
        bad += 1
        out.append(p)
        a1 += p.area
    rec = {"删短边点": drop, "塌短边面积_m2": round((a0 - a1) / 1e6, 6),
           "原样留着_块": bad}
    return out, rec


# 拉伸修复记账（模块级 → 落 `build.json::extrude_repair`）
EXTRUDE_REPAIR = {"候选": 0, "重修_块": 0, "重修_面积变化_m2": 0.0, "仍坏_块": 0,
                  "丢退化_块": 0, "丢退化_mm2": 0.0}
EXTRUDE_REPAIR_EPS_M = 0.0005      # 0.5 mm = RES/50，远低于「细到这个程度不算实体」的 6.25 mm
# ★★ 2026-10-19：不水密的块**逐块记账**（封顶 `EXTRUDE_BAD_MAX` 条，落
#   `build.json::extrude_bad`）。原先只有四个计数、没有「坏的是哪一块、坏在哪」，
#   闸 ⑤ 报「1/3/4/7 层墙不水密」而件里**看不出是哪一块** —— 判词有、证据没有（铁律 158）。
EXTRUDE_BAD = []
EXTRUDE_BAD_MAX = 20


def _note_extrude_bad(q, m, h, where):
    """不水密的块记一条（封顶 `EXTRUDE_BAD_MAX`）。只记读数，不改几何。"""
    if len(EXTRUDE_BAD) >= EXTRUDE_BAD_MAX:
        return
    c = [(float(x), float(y)) for x, y in q.exterior.coords]
    dup = sum(1 for i in range(len(c) - 1) if c[i] == c[i + 1])
    EXTRUDE_BAD.append({
        "where": where or "?",
        "面积_m2": round(q.area / 1e6, 4),
        "高_m": round(h, 3),
        "外环点": len(c) - 1, "重复点": dup,
        "洞": len(q.interiors),
        "valid": bool(q.is_valid),
        "simple": bool(q.exterior.is_simple),
        "面": int(m.faces.shape[0]),
    })


def _extrude_one(q, h, T, where=""):
    """单块拉伸；带内环的块若拉出**不水密**，按 0.5 mm 缩-放修一次拓扑再拉。

    ★ 为什么需要（2026-10-19 实测 c079 1层）：墙带那块外环带 **24 个内环**，其中 4 对
      内环互相相交 ⇒ trimesh 的封盖三角化留下非流形边 ⇒ `is_watertight=False`，
      闸 J-10.8-01 ⑤ 整层红。合成数据 1~24 个**互不相交**的内环拉出来都水密
      （`_scratch/probe_holes_n.py`）⇒ 不是「洞多了不行」，是「洞相交了不行」。
      `buffer(-ε).buffer(ε)` 把相交的两环并成一条（实测 24 → 20 环），可见几何不动
      （0.5 mm 在 6.25 mm 的实体线以下）；面积变化**落账**，不静默。
    ★★ 2026-10-19 改：**每一块都查**（原注释说「无内环的块没有实测过失败」—— 那句话
      在 2026-10-19 被证伪：`候选=0` 却仍有 1/3/4/7 层墙不水密 ⇒ 坏的正是**无内环**的块，
      而旧口径连查都不查、更不修。铁律 137/158：判据名单漏掉主体则永远绿）。
      每块一次 `is_watertight` 是 O(面数)，全栋几千块可忽略。
      坏块**逐块落账**（`EXTRUDE_BAD`），否则闸只说「整层不水密」、看不出是哪一块。
    """
    m = trimesh.creation.extrude_polygon(q, height=h, transform=T)
    if m.is_watertight:
        return m
    EXTRUDE_REPAIR["候选"] += 1
    _note_extrude_bad(q, m, h, where)
    try:
        q2 = q.buffer(-EXTRUDE_REPAIR_EPS_M).buffer(EXTRUDE_REPAIR_EPS_M)
    except Exception:                                   # noqa: BLE001
        EXTRUDE_REPAIR["仍坏_块"] += 1
        return m
    if q2.is_empty:
        EXTRUDE_REPAIR["仍坏_块"] += 1
        return m
    m2 = None
    for q3 in _split(q2):
        try:
            mm = trimesh.creation.extrude_polygon(q3, height=h, transform=T)
        except Exception:                               # noqa: BLE001
            continue
        m2 = mm if m2 is None else trimesh.util.concatenate([m2, mm])
    if m2 is not None and m2.is_watertight:
        EXTRUDE_REPAIR["重修_块"] += 1
        EXTRUDE_REPAIR["重修_面积变化_m2"] += q2.area - q.area
        return m2
    EXTRUDE_REPAIR["仍坏_块"] += 1
    return m


def _extrude(polys, z0, h, where=""):
    """一批多边形 → 一个合并水密网格。

    ★ 顺序：**先把多边形缩到米（×0.001），再按米拉伸 height=h，最后抬到 z0 米**。
      第一版把「mm 拉伸(height=h) → 整体 ×0.001」写反了 ⇒ 每层只 4 mm 高、整栋塌成 47 mm
      煎饼；而当时印的 `z_max 44.00` 是从层表**声明**出来的、不是网格量出来的，所以**看着对**。
      ⇒ 单位换算只允许出现在拉伸**之前**的一处；高度一律以网格实测为准（见 main 的 z_measured）。
    """
    T = trimesh.transformations.translation_matrix([0.0, 0.0, z0])
    ms = []
    n_fail = 0
    for p in polys:
        # ★★ 2026-10-18：**MultiPolygon 必须在这里摊平**。`extrude_polygon` 只吃单块，
        #   喂 MultiPolygon 会抛，而旧的裸 `except: continue` 把这一块**静默吞掉** ——
        #   症状正是电梯机房「只有墙、没有顶板」（3 根井道并成的 core 是 MultiPolygon）。
        #   铁律 17/158：坏在调用处，却在别处不出声。摊平放在这里 ⇒ 所有调用方一起修。
        for q0 in _split(p):
            # ★★ 2026-10-19：退化块（面积 < 6.25² mm²）**不是实体**，拉出来只有退化面
            #   ⇒ 整层不水密。丢在这里（所有调用方一起修），面积逐个落账。
            if q0.area <= EXTRUDE_AREA_MIN_MM2:
                EXTRUDE_REPAIR["丢退化_块"] += 1
                EXTRUDE_REPAIR["丢退化_mm2"] = round(
                    EXTRUDE_REPAIR["丢退化_mm2"] + q0.area, 3)
                continue
            try:
                q = _sh_scale(q0, xfact=0.001, yfact=0.001, origin=(0.0, 0.0))   # mm → m
                m = _extrude_one(q, h, T, where=where)   # ★ 不水密的块在这里修拓扑（见该函数）
                if m is not None:
                    ms.append(m)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                if n_fail <= 3:
                    print("  ★ _extrude 跳过一块（%s · z0=%.1f h=%.2f）：%s"
                          % (q0.geom_type, z0, h, e))
    if n_fail:
        print("  ★ _extrude 共跳过 %d 块（z0=%.1f h=%.2f）—— 这几块**没有出件**" % (n_fail, z0, h))
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
    V_SLAB = {}        # 层名 → 抠后楼板多边形（裙房屋面直接用这一份，不另算）
    V_SLAB_NOVOID = {}  # 层名 → **未扣挑空**的楼板（顶层屋面板的基板，见顶层那一段）
    for _fi, (name, z0, h) in enumerate(FLOORS):
        v = RD.geometry(name)
        V[name] = v
        # ★★ 跨层借形的邻层读数（= 本层的**上一层**，`FLOORS` 自下而上）：
        #   梯井是竖向贯通构件 —— 入口层图被折断线截短时，本层的梯段宽/井宽/锚区
        #   同时偏小，双跑铺不下。这里先备好上一层的形制与会锚区，交给 `stair_steps`
        #   在**本层装不下双跑**时用（顶层没有上一层 ⇒ alt=None ⇒ 行为与旧版逐位相同）。
        #   代价（铁律 28）：每层多一次 `_well_geom`（O(跑数²) 的配对，实测各层跑数 ≤ 30）
        #     ⇒ 相对整层的挤出/合并可忽略；`RD.geometry(上一层)` 会**提前**触发一次该层
        #     的 analyze（有指纹缓存，主循环走到它时命中缓存，不重算）。
        _alt = None
        if _fi + 1 < len(FLOORS):
            _un = FLOORS[_fi + 1][0]
            _uv = V.get(_un) or RD.geometry(_un)
            _alt = stair_alt(_uv)      # ★ 与 `export_contours` **同一处**算（原先两边各写一份）
        _CUR["层"], _CUR["h_m"] = name, h      # 形制读数要能点名是哪一层
        if name == TOP_FLOOR:
            v11 = v
        # ★ 井道先抠出来：墙带上那 3 个闭合矩形**整块都是墙**（实测在墙带内占比 1.00），
        #   照原样拉伸 = 竖井成了实心混凝土块、楼板也没有井口。抠出井道内空后，
        #   井壁作为**独立节点**（可点名、可数），楼板才有贯穿的井口。
        _lift_v = lift_voids(v)
        # ★ 2026-10-17 C005：门洞显式抠（c006 的 `door_voids` 恒返回 []，这一行对 c006 无副作用）。
        wp0 = wall_polys(v)
        _dvd = {}                      # 门洞夹厚读数（铁律 158：夹了几块、从多厚夹到多厚要留字）
        _door_v = door_voids(v, wp0, diag=_dvd)
        if v.get("door_widths"):
            _bad = [w for w in v["door_widths"]
                    if not any(abs(w - t) <= RD.DOOR_OPEN_TOL for t in RD.DOOR_OPEN_MM)]
            print("%-8s 门洞 %3d 樘（净宽读数 %s）%s"
                  % (name, len(v["door_widths"]), sorted(set(v["door_widths"])),
                     ("★ 自检不合格 %d 樘：%s" % (len(_bad), _bad[:8])) if _bad else ""))
        # 井道内空要**贯穿楼板**；门洞只抠墙 ⇒ 两个清单分开传（`voids` 只给墙用）
        voids = _lift_v + _door_v
        # ★★ 梯间清空（2026-10-16 用户令「现在楼梯间就要比较的干净，只要是楼梯，就是刚才的
        #   样子，没有其他的墙之类的」）—— 三步：
        #     ① 楼梯**先落位**：`stair_steps` 落位时把这一座的包络 append 进 `STAIR_ENV`；
        #     ② 包络并集**内缩 PAD** 当清空区（内缩的代价/理由是硬的，见 `STAIR_CLEAR_PAD_MM`）；
        #     ③ 从**墙带**和**楼板**里扣掉 —— 梯井的**围合墙**离包络边 ≥ 1 m，不在清空区里，
        #        所以梯间仍然有界；扣掉的是梯间**里面**的假墙和盖住井口的板。
        #   ★ `stair_steps` 这里**只调一次**：原先是下面出件时才调；现在提前调、出件复用
        #     `_steps`。调两次不只是白算一遍落位 —— 它会把同一座包络 append **两遍**。
        #   ★ 走 `stair_and_clear`（同源取两个产物）—— 见它的 docstring：不许分两趟算。
        _steps, _cut = stair_and_clear(v, h, alt=_alt)
        _void = _cut or []          # None（本层没梯）/ []（有梯没清到）都退化成「不扣」
        _wp1 = carve(wp0, voids)
        _cwp = carve(_wp1, _void)
        cp = col_polys(v, floor=name)
        lp = lift_polys(v)
        stp = step_polys(v)
        _sp0 = slab_polys(v)
        _sp1 = carve(_sp0, _lift_v)          # ★ 楼板只扣井道，不扣门洞
        _csp = carve(_sp1, _void)
        dp = door_polys(v)
        # ★ 记账（铁律 158：不许静默）—— 扣了多少、块数有没有被切碎，逐层落盘。
        #   `None` 与 `[]` 在这里就是两句不同的话：前者「本层没楼梯」，后者「有梯没扣到」。
        _diag = {
            "层": name,
            "包络块": len(STAIR_ENV),
            "清空区块": (None if _cut is None else len(_cut)),
            "清空区_m2": (None if not _cut else round(sum(p.area for p in _cut) / 1e6, 3)),
            "墙带扣掉_m2": round(_area_m2(_wp1) - _area_m2(_cwp), 3),
            "楼板扣掉_m2": round(_area_m2(_sp1) - _area_m2(_csp), 3),
        }
        # ★ 塌短边**只在真扣了东西的层上做**（`_void` 空时一个顶点都不动 ⇒ 拿它当 A/B 的「关」）。
        if _void:
            wp, _diag["塌墙带"] = _drop_short_edges(_cwp)
            sp, _diag["塌楼板"] = _drop_short_edges(_csp)
        else:
            wp, sp = _cwp, _csp
        _diag["墙带块"] = [len(_wp1), len(wp)]
        # ★★ 2026-10-19 挑空（对照件识别；用户定案「按 ts4 补全」）：
        #   楼板扣；`V_SLAB_NOVOID` 是扣之前的板 —— 顶层屋面板要它：屋面洞（327.1 m²）
        #   比 5 层楼板洞（428.5 m²）小，拿已扣过的 `sp` 当基板会把屋面洞整个吃掉。
        V_SLAB_NOVOID[name] = sp
        _vv = void_polys(name)
        if _vv:
            sp = _drop_short_edges(carve(sp, _vv))[0]
            _diag["挑空_m2"] = round(_area_m2(_vv), 3)
            _diag["挑空块"] = [len(_vv), len(sp)]
        _diag["楼板块"] = [len(_sp1), len(sp)]
        # ★★ 2026-10-17 理化楼（c005）顶层＝**裙房屋面**：顶层只占中央塔楼，两侧没房间的
        #   大块是**下一层的屋面**。判据见 `top_roof_zone`（现算，不手打面积/不画矩形）。
        if B.profile().get("podium_roof") and name == TOP_FLOOR:
            sp, wp, _rdiag = podium_roof_trim(v, sp, wp, name)
            if _rdiag is not None:
                ROOF_DIAG.append(_rdiag)
                _diag["屋面切分"] = _rdiag
        # ★★ 2026-10-20 用户令「第六教学楼裙楼只有六层，六层上面就是屋顶」：
        #   档案写了 `roof_plans` 的图幅（c006「7层」）是**裙房屋面平面** + 塔楼那一层。
        #   塔外墙带改判女儿墙（1.2 m，基面 = 本层底），塔内照旧；楼板整块不动。
        sp, wp, _rp = roof_plan_split(v, sp, wp, name)
        _par_rp, _sp_roof, _rpdiag = [], [], None
        if _rp is not None:
            _par_rp, _sp_roof, _rpdiag = _rp["女儿墙"], _rp["屋面板"], _rp["读数"]
            ROOF_PLAN_DIAG.append(_rpdiag)
            _diag["屋面平面"] = _rpdiag
            print("▷ %s 屋面平面：塔楼 %s · 塔内墙带 %.1f m² · 塔外 %.1f m² 改女儿墙（%d 块）"
                  "· 屋面板 %.1f m²（%d 块，类 ROOF）"
                  % (name, _rpdiag.get("塔楼层"), _rpdiag.get("墙带_塔内_m2", 0),
                     _rpdiag.get("改女儿墙_m2", 0), _rpdiag.get("改女儿墙_块", 0),
                     _rpdiag.get("屋面板_m2", 0), _rpdiag.get("屋面板_块", 0)))
        # ★★ 2026-10-17 用户令「楼梯还有破坏墙面的情况」：梯块**裁到墙边**（墙不动）。
        #   必须在 `wp` 定稿之后做（前面刚被清空区削过、顶层又被裙房屋面切过）。
        _steps, _clip = clip_steps_to_walls(_steps, wp)
        if _clip["相交块"] or _clip["碎块"] or _clip["消失块"] or _clip.get("压块对"):
            _diag["梯穿墙"] = _clip
            STAIR_CLIP_DIAG.append(dict(_clip, 层=name))
        V_SLAB[name] = sp          # ★ 裙房屋面要用**逐位相同**的抠后楼板（不再算第二遍）
        STAIR_CLEAR_DIAG.append(_diag)
        parts = []
        # ★ 2026-10-15：`ptags` 与 `parts` **一一对应**（同长、同序）。加它是为了让下面能
        #   逐类量 z —— 原先每层只留一个聚合 `z_measured`，于是「梯栏杆按设计越层 0.9 m」
        #   与「墙偷偷高了 0.9 m」在 build.json 里**长得一模一样**，判据只能报一句
        #   「z 实测 ≠ 声明」（铁律 137/158：判据名单漏掉主体则永远绿）。
        ptags = []
        _slab_h = STEP_H_M if name == FLOORS[0][0] else SLAB_M
        for polys, tag, hh in ((wp, "wall", h), (cp, "col", h), (lp, "lift", h),
                               (sp, "slab", _slab_h), (dp, "door", DOOR_H)):
            m = _extrude(polys, z0, hh, where="%s/%s" % (name, tag))
            if m is not None:
                scene.add_geometry(m, node_name="%s_%s" % (name, tag),
                                   geom_name="%s_%s" % (name, tag))
                parts.append(m)
                ptags.append(tag)
        if stp:
            _sm = _extrude(stp, z0, STEP_H_M, where="%s/roof_step" % name)
            if name == FLOORS[0][0]:
                _cm = _extrude(stp, z0 + CANOPY_Z_M, CANOPY_T_M,
                               where="%s/roof_step_canopy" % name)
                if _sm is not None and _cm is not None:
                    _sm = trimesh.util.concatenate([_sm, _cm])
                elif _cm is not None:
                    _sm = _cm
            if _sm is not None:
                scene.add_geometry(_sm, node_name="%s_roof_step" % name,
                                   geom_name="%s_roof_step" % name)
                parts.append(_sm)
                ptags.append("roof_step")
        # 屋面平面层的屋面板：塔外那块板**是屋面**（类 ROOF），板顶 = 本层底 + 板厚。
        if _sp_roof:
            mr = _extrude(_sp_roof, z0, SLAB_M, where="%s/roofplan_roof" % name)
            if mr is not None:
                scene.add_geometry(mr, node_name="%s_roofplan_roof" % name,
                                   geom_name="%s_roofplan_roof" % name)
                parts.append(mr)
                ptags.append("roofplan_roof")
                zmax = max(zmax, float(mr.bounds[1][2]))
        # 屋面平面层的女儿墙：**基面 = 本层底**（屋面标高），不是本层顶。
        if _par_rp:
            mp = _extrude(_par_rp, z0, PARAPET_H, where="%s/parapet_roofplan" % name)
            if mp is not None:
                scene.add_geometry(mp, node_name="%s_parapet_roofplan" % name,
                                   geom_name="%s_parapet_roofplan" % name)
                parts.append(mp)
                ptags.append("parapet_roofplan")
                zmax = max(zmax, float(mp.bounds[1][2]))

        # 门头墙：**逐块**拉伸（每块的底标高都是门洞高、高度 = 层高 − 门洞高，
        # 但块与块之间可以不同 ⇒ 与楼梯同理，不许按「一层一个常数」拉）
        # ★ 2026-10-17 C005：源图墙线不断 ⇒ `lintel_module`（靠「墙上缺口」找门洞）量不到，
        #   判词会如实报「无缺口」。门头墙在这里**由门洞本身构造**：被抠掉的那块墙足迹
        #   从门洞高补到层高 —— 覆盖由构造保证，不靠扫描。
        #   ★★ 2026-10-18：这批板**必须递进模块**（`seed=`），不许在返回后拼 ——
        #   拼在外面时记账量不到它们（c055 实测 有门头 16/181，件里却全有）。
        lt = lintel_module(v, h, dp, floor=name, seed=_door_v)
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
        # ★ 用上面已经算好的 `_steps`（本层**只落位这一次**）—— 见 `voids` 那一段的说明。
        tms = []
        for poly, zrel, hm in _steps:
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
        # ★★ 2026-10-19：屋面板**扣掉露台**（`terrace_polys`，语义识别给的）。
        #   楼板 `sp` 照旧整块 —— 露台要有地面，只是头上不能有顶。
        if name == TOP_FLOOR and sp:
            # ★★ 屋面基板：有**屋面洞**时用未扣挑空的板（否则 5 层的洞会把屋面洞吃掉）。
            _rv = roof_void_polys()
            _rsp = V_SLAB_NOVOID.get(name, sp) if _rv else sp
            _te = terrace_polys(name)
            if _te:
                _tu = unary_union(_te)
                _rsp = [g for p in _rsp for g in _split(p.difference(_tu))]
                _diag["露台_m2"] = round(_area_m2(_te), 3)
                _diag["露台块"] = [len(_te), len(_rsp)]
            if _rv:
                _ru = unary_union(_rv)
                _rsp = [g for p in _rsp for g in _split(p.difference(_ru))]
                _diag["屋面挑空_m2"] = round(_area_m2(_rv), 3)
                _diag["屋面挑空块"] = [len(_rv), len(_rsp)]
            mr = _extrude(_rsp, TOP_M - SLAB_M, SLAB_M)
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
        # ★★ 2026-10-19（c079 诊断）：⑨「抠后守恒」原先拿 `A_lift_void_m2` 当「墙被挖掉多少」，
        #   可那个数是**井道+门洞原始多边形的面积和**（74.84 m²），不是墙实际少了多少
        #   （实测 64.80 m² —— 有些洞画在墙带外/与墙不重叠，还有些互相重叠）。
        #   ⇒ 三个读数分开落盘，各是各的话（铁律 018 / 174：两个同名的量必须死掉一个）：
        #     · `A_void_raw_m2`         井+门洞多边形面积和（= 旧 `A_lift_void_m2`，保留兼容）
        #     · `A_void_in_wall_m2`     其中**真落在墙带上**的那部分（与墙带求交，现算）
        #     · `A_wall_cut_by_voids_m2` 墙带抠前 − 抠后（真差值，抠楼梯之前）
        _u_wp0 = unary_union(wp0) if wp0 else None
        _u_void = unary_union(voids) if voids else None
        A_void_in_wall = (round(_u_void.intersection(_u_wp0).area / 1e6, 2)
                          if (_u_wp0 is not None and _u_void is not None) else 0.0)
        # ★ 与 `A_void_in_wall` **同一口径（并集面积）**算差值：若墙块之间本身有重叠，
        #   拿「逐块面积和」相减会把这部分重叠也算成「被挖掉」，与求交那个数对不上。
        _u_wp1 = unary_union(_wp1) if _wp1 else None
        A_cut = (round((_u_wp0.area - _u_wp1.area) / 1e6, 2)
                 if (_u_wp0 is not None and _u_wp1 is not None) else 0.0)   # `_wp1 = carve(wp0, voids)`
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
            "n_entrance_step": len(stp), "A_entrance_step_m2": _area_m2(stp),
            "n_door_void": len(_door_v), "A_door_void_m2": _area_m2(_door_v),
            # ★ 门洞跨墙深度被夹的门数（见 `DOOR_VOID_MAX_RATIO`）；0 也必须印出来
            "n_door_void_夹厚": int(_dvd.get("夹厚", 0)),
            "n_lift": len(lp), "n_lift_void": len(voids),
            "A_wall_m2": Aw, "A_col_m2": Ac, "A_slab_m2": As, "A_door_m2": Ad,
            "A_lift_m2": Al, "A_lift_void_m2": Av,
            # ★ 2026-10-19：井+门洞的三个口径分开记（旧 `A_lift_void_m2` 是**原始多边形和**，
            #   拿它当「墙少了多少」会凭空多出几平方，见上面注释）
            "A_void_raw_m2": Av,
            "A_void_in_wall_m2": A_void_in_wall,
            "A_wall_cut_by_voids_m2": A_cut,
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
    # ★ 台阶屋面女儿墙的读数先给零：没有 7/8 层的楼栋**不建**它，但 `build.json` 里这两个
    #   字段照样要有（缺字段与「建了 0 段」在读数上不是一回事，铁律 199）。
    n_rail_step, A_rail_step = 0, 0.0
    # ★★ 2026-10-18 层间退台屋面（用户「006 的八角楼为啥没有楼顶」）：
    #   档案里 `mid_roofs` 声明「哪一层的顶是屋面 + 足迹」（足迹来自实景读数），
    #   几何仍用与 7→8 **同一个** `_slab_carved` 现算，不手画任何板。
    #   为什么不是「所有相邻层两两相减都加」：实测 1→2（1982.9 m²/12 块）、
    #   4→5（500.6 m²/1 块）、6→7（21.3 m²/6 条）里只有 4→5 的八角厅那块有影像
    #   支撑（312 m² @16.38 m），其余是闭运算吹大的假象（见本段 2097-2102 的影像读数）。
    n_roof_mid, A_roof_mid = 0, 0.0
    _mid_ents = B.profile().get("mid_roofs") or []

    def _slab_carved(nm):
        """某层的**抠后楼板**（与楼层循环里量 `A_slab_m2` 的那一串刀逐位相同）。

        ★★ 2026-10-17 修（铁律 174/192：同一个量不许有两个估计器；参照物必须与
          交付件同作用域）：本块原来拿 `slab_polys` **未抠洞**的板相减 ⇒ 4468.80 m²，
          而判据 `J-10.8-01` ⑩ 的参照是 `A_slab_m2`（**三刀之后**）相减 = 4354.49 m²，
          相对差 **2.63% > 容差 2%** ⇒ 那条判据恒红（就是 `C1` 最后剩下的一条）。
          实测（本趟，同一份 `build.json`）：
            7层 未抠洞 5386.30 → 抠后 5249.54（与 `A_slab_m2` 逐位相同）
            8层 未抠洞  916.94 → 抠后  895.05（同上）
            未抠洞相减 4468.80 ／ 抠后相减 4353.94 ／ 闸参照 4354.49
          ⇒ 「楼板面积」这个名字在本仓只留**一个**定义：台阶屋面跟着 `A_slab_m2` 走。
          代价（铁律 28）：本块 4468.80 → 4353.94 m²（−114.86 = −2.57%），
            等于把那 114.86 m² 改判为「井/梯间开洞处不收屋面」—— 与楼层板口径一致。
        """
        _vv = V[nm]
        _i = [n for n, _z, _h in FLOORS].index(nm)
        _hh = FLOORS[_i][2]
        _a = None
        if _i + 1 < len(FLOORS):
            _nx = FLOORS[_i + 1][0]
            _a = stair_alt(V.get(_nx) or RD.geometry(_nx))
        _wo = lift_voids(_vv)
        _st, _cl = stair_and_clear(_vv, _hh, alt=_a)
        _cc = _cl or []
        _ps = carve(carve(slab_polys(_vv), _wo), _cc)
        if _cc:
            _ps = _drop_short_edges(_ps)[0]
        return _ps

    # ★★ 2026-10-20：档案把「7层」判成**屋面平面**时，这里**不许**再补一块 28 m 的台阶屋面。
    #   那一块是「7 层是真楼层」的假设造出来的：它和 24 m 的屋面板同址（实测 4338.5 ≈ 4339.1 m²），
    #   叠在一起正好把 6 层的屋顶抬到 7 层高 —— 就是用户说的「裙楼只有六层」被做成了七层。
    #   屋面由 7 层的 SLAB（板顶 24.12 m）+ `roof_plan_split` 的女儿墙负责。
    if "7层" in V and "8层" in V and not (B.profile().get("roof_plans") or {}).get("7层"):
        from shapely.ops import unary_union as _uu

        a = _uu(_slab_carved("7层"))
        b = _uu(_slab_carved("8层"))
        d = a.difference(b).buffer(0) if (not a.is_empty and not b.is_empty) else a
        rp = [g for g in _split(d) if g.area > 1e6]
        n_roof_step, A_roof_step = len(rp), _area_m2(rp)
        _z7 = _GROUND_TOP[6]                                  # 7层顶（逐层累加；同高时 = 7×层高）
        m = _extrude(rp, _z7 - SLAB_M, SLAB_M)                 # 板顶 = 7层顶
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
              % (n_roof_step, A_roof_step, _z7))
        # ★ 2026-10-18 用户定案（保留 7 层外墙、只在屋面上加女儿墙）—— 开关在楼栋档案
        #   `roof_step_parapet`；高度/厚度仍走参数表 `顶部/女儿墙高、厚`（唯一真源）。
        if B.profile().get("roof_step_parapet", False):
            _rails = roof_step_rails(rp, b)
            n_rail_step, A_rail_step = len(_rails), _area_m2(_rails)
            m2 = _extrude(_rails, _z7, PARAPET_H)              # 基面 = 屋面顶
            if m2 is not None:
                scene.add_geometry(m2, node_name="parapet_roof_step",
                                   geom_name="parapet_roof_step")
                zmax = max(zmax, float(m2.bounds[1][2]))
            print("台阶屋面女儿墙 %d 段 · %.1f m²（高 %.1f m，基面 %.1f m）"
                  % (n_rail_step, A_rail_step, PARAPET_H, _z7))

    # ---- 层间退台屋面（楼栋档案 `mid_roofs` 声明）
    # ★ 足迹（bbox，mm）只用来**限定**「下层板 − 上层板」那一块 —— 不手画板。
    #   几何仍与 7→8 同一条路：`_slab_carved` 相减 → `_split` → `_extrude`。
    if _mid_ents:
        _names = [n for n, _z, _h in FLOORS]
        for _e in _mid_ents:
            _lo = _e["层"]
            _i = _names.index(_lo)
            if _i + 1 >= len(_names):
                raise RuntimeError("mid_roofs：%s 是顶层，上方没有楼层可比（下层板−上层板）"
                                   % _lo)
            _hi = _names[_i + 1]
            _a = unary_union(_slab_carved(_lo))
            _b = unary_union(_slab_carved(_hi))
            _d = _a.difference(_b).buffer(0) if (not _a.is_empty and not _b.is_empty) else _a
            _fp = [float(v) for v in _e["足迹"]]
            _d = _d.intersection(sg.box(_fp[0], _fp[1], _fp[2], _fp[3]))
            _rp = [g for g in _split(_d) if g.area > 1e6]
            _z0, _hh = FLOORS[_i][1], FLOORS[_i][2]
            _m = _extrude(_rp, _z0 + _hh - SLAB_M, SLAB_M)      # 板顶 = 本层顶
            if _m is not None:
                _nm = "roof_mid%02d" % _i
                scene.add_geometry(_m, node_name=_nm, geom_name=_nm)
                zmax = max(zmax, float(_m.bounds[1][2]))
            n_roof_mid += len(_rp)
            A_roof_mid += _area_m2(_rp)
            print("层间退台屋面 %s：%d 块 · %.1f m²（板顶 %.2f m，足迹 [%.0f,%.0f]-[%.0f,%.0f]）"
                  % (_lo, len(_rp), _area_m2(_rp), _z0 + _hh,
                     _fp[0], _fp[1], _fp[2], _fp[3]))

    # ---- 裙房屋面（c005：顶层只占中央塔楼，其余是**下一层**的屋面）
    # ★ 依据是源图自己的面积：F0~F3 各 1853.85 m²，F4 只有 921.31 m²（≈一半）
    #   ⇒ 5 层是中央塔楼，四层屋顶就是裙房屋面。**位置**由「下一层楼板 − 顶层楼板」现算，
    #   不是手画的矩形；**板厚/女儿墙高**沿用参数表的假设值（源图无屋顶图）。
    n_podium, A_podium, n_rail_podium = 0, 0.0, 0
    if B.profile().get("podium_roof") and len(_GROUND) >= 2:
        rp, rails = podium_roof_parts(V_SLAB[_GROUND[-2]], V_SLAB[_GROUND[-1]])
        n_podium, A_podium = len(rp), _area_m2(rp)
        zr = FLOORS[-1][1]                          # 板顶 = 裙房顶 = 顶层底（逐层累加）
        m = _extrude(rp, zr - SLAB_M, SLAB_M)
        if m is not None:
            scene.add_geometry(m, node_name="roof_podium", geom_name="roof_podium")
            zmax = max(zmax, float(m.bounds[1][2]))
        n_rail_podium = len(rails)
        m2 = _extrude(rails, zr, PARAPET_H)
        if m2 is not None:
            scene.add_geometry(m2, node_name="parapet_podium", geom_name="parapet_podium")
            zmax = max(zmax, float(m2.bounds[1][2]))       # ztot 在下一段统一 = zmax
        print("裙房屋面 %d 块 · %.1f m²（板顶 %.1f m）｜女儿墙 %d 段"
              % (n_podium, A_podium, zr, n_rail_podium))

    # ---- 下层翼楼/退台屋面（**通用规则**，见 `lower_roof_pieces` 的说明）
    # ★★ 2026-10-20：用户「综合楼旁边有个楼没有楼顶」的根因就在这里 —— 顶层以外
    #   任何「本层有板、上层没盖住」的地方，以前**没有任何机制**补屋面。
    _lr_names = [n for n, _z, _h in FLOORS]
    n_roof_low, A_roof_low, n_rail_low, A_rail_low = 0, 0.0, 0, 0.0
    for _i in range(len(_lr_names) - 1):
        _lo, _hi = _lr_names[_i], _lr_names[_i + 1]
        if FLOORS[_i][1] < 0:
            LOW_ROOF_DIAG.append({"层": _lo, "上层": _hi,
                                  "结果": "地下层顶（地面就是屋面，不补）"})
            continue
        _skip = lower_roof_skip(_lo, _hi, _lr_names)
        if _skip:
            LOW_ROOF_DIAG.append({"层": _lo, "上层": _hi,
                                  "结果": "已由 %s 处理（不补）" % _skip})
            continue
        _lr, _ldiag = lower_roof_pieces(
            V_SLAB.get(_lo) or [], V_SLAB.get(_hi) or [], _lo,
            wall_polys(V.get(_lo) or RD.geometry(_lo)))
        LOW_ROOF_DIAG.append(dict(_ldiag, 上层=_hi))
        if not _lr:
            continue
        _zhi = FLOORS[_i + 1][1]              # 板顶 = 上层层底 = 本层顶
        _m = _extrude(_lr, _zhi - SLAB_M, SLAB_M)
        if _m is not None:
            _nm = "roof_low_%s" % _lo
            scene.add_geometry(_m, node_name=_nm, geom_name=_nm)
            zmax = max(zmax, float(_m.bounds[1][2]))
        _rails = roof_step_rails(_lr, unary_union(V_SLAB.get(_hi) or []))
        if _rails:
            _m2 = _extrude(_rails, _zhi, PARAPET_H)
            if _m2 is not None:
                _nm2 = "parapet_low_%s" % _lo
                scene.add_geometry(_m2, node_name=_nm2, geom_name=_nm2)
                zmax = max(zmax, float(_m2.bounds[1][2]))
        n_roof_low += len(_lr)
        A_roof_low += _area_m2(_lr)
        n_rail_low += len(_rails)
        A_rail_low += _area_m2(_rails)
        print("下层屋面 %s（顶 %.2f m）：%d 块 · %.1f m²｜女儿墙 %d 段"
              % (_lo, _zhi, len(_lr), _area_m2(_lr), len(_rails)))

    # ---- 第三批：女儿墙 + 顶楼楼梯房（★ 规则推导，源图没有；单独成节点，便于分辨）
    ztot = zmax
    n_parapet = n_rs = n_lr = 0
    # ★★ 2026-10-19（c079 诊断）：`attach` 里的高度原先写的是**参数值**（`ROOF_STAIR_H`=3.0），
    #   可这栋档案 `roof_stair:false` ⇒ 一个都没建 ⇒ 闸 J-10.8-01 ② 按 24.0+3.0=27.0 去比
    #   实测 25.2，判红，而件其实是对的（铁律 018：声明值与建出来的值是两个量）。
    #   ⇒ 这里改成记**实际建出来的高度**：没建就是 0.0，建了就是那一壳的墙高。
    _rs_h = _lr_h = 0.0
    if v11 is not None:
        pp = parapet_polys(v11)
        # ★★ 2026-10-17 用户令「**不要屋顶的电梯塔楼了**」⇒ 顶层楼梯房/电梯机房默认**不建**。
        #   档案写 `"roof_stair": true` 才建（c006/c005 这两个已交付件显式写着 true，
        #   它们的行为一字不变；新做的楼一律不带）。女儿墙照旧建 —— 用户只说不要塔楼。
        # ★★ 2026-10-18：顶部两件改成**结构体**（环带墙 + 顶板 + 门洞缺口），
        #   不再是 `_extrude(zone_box, TOP_M, 3.0)` 的实心盒。做不做由源件说（见 `roof_room_parts`）。
        rr = roof_room_parts(v11) if B.profile().get("roof_stair", False) else \
            {"stairs": [], "lift_rooms": []}
        n_parapet = len(pp)
        n_rs = len(rr["stairs"])
        n_lr = len(rr["lift_rooms"])
        m = _extrude(pp, TOP_M, PARAPET_H)
        if m is not None:
            scene.add_geometry(m, node_name="parapet", geom_name="parapet")
            ztot = max(ztot, float(m.bounds[1][2]))
        for tag, shells in (("roof_stair", rr["stairs"]), ("roof_lift", rr["lift_rooms"])):
            for i, (walls, slabs, hh) in enumerate(shells):
                if tag == "roof_stair":
                    _rs_h = max(_rs_h, float(hh))
                else:
                    _lr_h = max(_lr_h, float(hh))
                mw = _extrude(walls, TOP_M, hh)                       # 墙
                if mw is not None:
                    scene.add_geometry(mw, node_name="%s_wall_%d" % (tag, i),
                                       geom_name="%s_wall_%d" % (tag, i))
                    ztot = max(ztot, float(mw.bounds[1][2]))
                mb = _extrude(slabs, TOP_M + hh, SLAB_M)              # 顶板
                if mb is not None:
                    scene.add_geometry(mb, node_name="%s_slab_%d" % (tag, i),
                                       geom_name="%s_slab_%d" % (tag, i))
                    ztot = max(ztot, float(mb.bounds[1][2]))
        print("女儿墙 %d 环带 · 出屋面楼梯间 %d 个（墙 %.1f 假设）· 电梯机房 %d 个（墙 %.1f 假设）"
              % (n_parapet, n_rs, ROOF_STAIR_H, n_lr, ROOF_LIFT_H))

    obj = os.path.join(OUT, "%s_white.obj" % OUT_NAME)
    glb = os.path.join(OUT, "%s_white.glb" % OUT_NAME)
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
        # ★ 2026-10-17：`basement_m` 跟着档案走。原来无条件写 BASEMENT_M（3.5），
        #   而 c005 **没有地下室**（档案 `basement: null`）⇒ 件里最低标高是 0，记账却写 −3.5，
        #   下游 `su_obj_to_glb.py::_exp_hi_mm` 会拿 −3.5 当期望值 ⇒ 件是对的也报红。
        "storey_m": STOREY_M,
        # ★ 2026-10-19：地上层高改**逐层**（c001 首层 6.0、其余 4.0）。`storey_m` 仍是
        #   参数表 `共用/层高`（闸 J-10.9-05 盯它、无按栋条目的楼栋退回它）；逐层值另记一份，
        #   顺序 = `floor_names`，z 相对 ±0。下游对账（`demo/build_pack_bid.py`）按这张表比。
        "floor_h_m": [round(v, 4) for v in _H],
        "floor_z0_m": [round(v, 4) for v in _Z],
        "basement_m": BASEMENT_M if B.profile().get("basement") else 0.0, "top_m": TOP_M,
        "z_max_m": round(ztot, 3),
        "z_max_main_m": round(zmax, 3),
        "building": {"id": B.BID, "title": B.profile().get("title"),
                     "top_floor": TOP_FLOOR, "n_floors": len(_GROUND),
                     "src_dxf": os.path.basename(B.profile().get("src_dxf") or "")},
        # ★★ 2026-10-19：高度一律记**实际建出来的值**（没建=0.0），参数表的假设值另记在
        #   `schematic` 里 —— 两者不是同一个量（c079：参数 3.0 / 建 0.0 / 女儿墙 1.2）。
        #   `n_roof_room` 是本轮新增的**类名锚**：`ROOF_ROOM` 由 export_contours 出、
        #   由 SU 建，但此前 `attach` 里没有任何键能机械推出这个类名 ⇒ A1(件) 少一类、
        #   与 A2(轮廓) 对不上（铁律 17/158：少了的那一类正好是判据看不见的那一类）。
        #   ★ 别写 `roof_lift_m`/`n_roof_lift`：那两个键会机械还原成 `ROOF_LIFT` 类，
        #     而轮廓件里这两个件都归 `ROOF_ROOM` ⇒ 又多一类对不上。
        "attach": {"parapet_m": (PARAPET_H if n_parapet > 0 else 0.0),
                   "roof_stair_m": _rs_h,
                   # ★★ 2026-10-19（c006 ② 实测 47.120 vs 声明 47.0）：屋面附属用房到件顶
                   #   不只是**墙高** —— 顶板再压 SLAB_M。闸 J-10.8-01 ② 拿 `attach` 里最高的
                   #   那一份去算件顶，少了这 0.12 ⇒ 件「冒头」0.12 m 被判红，而件是对的。
                   #   这与 `roof_stair_m` 同源（都是**建出来的**高度），不做则 0.0。
                   "roof_room_m": ((max(_rs_h, _lr_h) + SLAB_M) if (n_rs + n_lr) > 0 else 0.0),
                   "n_parapet": n_parapet, "n_roof_stair": n_rs,
                   "n_roof_room": n_rs + n_lr,
                   "roof_step7_m2": round(A_roof_step, 2), "n_roof_step7": n_roof_step,
                   # ★ 2026-10-17：裙房那两个键**只在开了裙房屋面的楼栋上出现**。
                   #   无条件写上（c006 恒 0）会让 `J-10.9-07` 的「attach 机械还原」
                   #   多还原出 ROOF_PODIUM / PARAPET_PODIUM 两个类 ⇒ 类集 11 → 13，判红。
                   #   「没有这个面」与「这个面 0 块」在账上是两件事，别用一个 0 盖过去。
                   **({"n_roof_podium": n_podium, "roof_podium_m2": round(A_podium, 2),
                       "n_parapet_podium": n_rail_podium}
                      if B.profile().get("podium_roof") else {})},
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
        # ★ 2026-10-19：按栋覆盖的**实际取值**（与 `参数来源` 记的表原值分开）。
        "参数覆盖": PARAM_OVERRIDE,
        "参数表": "rebuild/构件库/参数.json（唯一真源）",
        "schematic": {"slab_m": SLAB_M, "door_h": DOOR_H, "door_t": DOOR_T,
                      "riser_m": RISER_M, "tread_h": TREAD_H,
                      "parapet_h": PARAPET_H, "parapet_t": PARAPET_T,
                      "roof_stair_h": ROOF_STAIR_H, "lift_t_mm": LIFT_T_MM},
        "scope": SCOPE,
        "floors": rows,
        # ★ 梯间清空的记账（2026-10-16）：逐层「包络几块、扣了墙/板多少 m²、块数有没有被切碎」。
        #   判词不许静默（铁律 158）——「扣了 0 m²」与「本层没楼梯」在这里是两句不同的话。
        "stair_clear": STAIR_CLEAR_DIAG,
        # ★ 顶层裙房屋面切分的记账（2026-10-17）：切了几块、多少 m²、为什么没切。
        "roof_split": ROOF_DIAG,
        # ★ 7→8 台阶屋面上的女儿墙（2026-10-18 用户定案）：**只在档案开了这个开关时写**。
        #   ★ 不塞进 `attach`：`gates/J-10.9-07` 会把 attach 的键**机械还原成类名**，
        #     多一个键就多出一个件里没有的类 ⇒ 判红（这与「多写一个读数」不是一回事）。
        **({"roof_step_parapet": {"n": n_rail_step, "m2": round(A_rail_step, 2),
                                  "h_m": PARAPET_H, "base_m": round(_GROUND_TOP[6], 3)}}
           if B.profile().get("roof_step_parapet", False) else {}),
        # ★ 2026-10-18 层间退台屋面：**只在档案声明了才写**（与 roof_step_parapet 同规）。
        **({"mid_roofs": {"n": n_roof_mid, "m2": round(A_roof_mid, 2)}}
           if _mid_ents else {}),
        # ★★ 2026-10-20 通用下层屋面（用户「综合楼旁边有个楼没有楼顶」）：**每栋都写** ——
        #   「扫了、没有缺的」与「没扫」在账上必须是两句话（铁律 199）。
        "lower_roofs": {"n": n_roof_low, "m2": round(A_roof_low, 2),
                        "n_rails": n_rail_low, "m2_rails": round(A_rail_low, 2),
                        "diag": LOW_ROOF_DIAG},
        # ★ 2026-10-19：拉伸修复的账（见 `_extrude_one`）。**四个数都印** ——
        #   「候选 0」与「候选 24 但都修好了」是两句不同的话（铁律 158）。
        "extrude_repair": dict(EXTRUDE_REPAIR),
        # ★ 2026-10-19：**坏的是哪一块**（封顶 20 条，见 `_note_extrude_bad`）。
        #   「仍坏_块=3」说不出是哪三块；闸 ⑤ 只能报「整层不水密」（铁律 158）。
        "extrude_bad": list(EXTRUDE_BAD),
        # ★ 2026-10-19：女儿墙环带塌短边的账（见 `PARAPET_EDGE_FIX`）。**空账也要印**——
        #   「没塌过」与「没量到」不是一句话（铁律 158）。
        "parapet_edge_fix": dict(PARAPET_EDGE_FIX),
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

    # ★ 顶层裙房屋面切分：**必须印**（切了多少、为什么没切）——「没切」与「没量到」两句话。
    if ROOF_DIAG:
        print("★ 顶层裙房屋面切分 %d 层：" % len(ROOF_DIAG))
        for _d in ROOF_DIAG:
            print("   %s" % json.dumps(_d, ensure_ascii=False))

    # ★ 梯间清空的记账：**每层一行**，包括「本层没楼梯」和「有梯没扣到」两种。
    print("★ 梯间清空记账 %d 层（扣除区 = 梯段包络内缩 %.0f mm）："
          % (len(STAIR_CLEAR_DIAG), STAIR_CLEAR_PAD_MM))
    for _d in STAIR_CLEAR_DIAG:
        _m = _d.get("清空区_m2")
        print("   %-6s 包络 %s 块｜清空区 %s（%s m²）｜墙带扣 %+.2f m² 块 %s｜楼板扣 %+.2f m² 块 %s%s"
              % (_d.get("层"), _d.get("包络块"),
                 "—" if _d.get("清空区块") is None else _d.get("清空区块"),
                 "—" if _m is None else "%.2f" % _m,
                 _d.get("墙带扣掉_m2") or 0.0, _d.get("墙带块") or "—",
                 _d.get("楼板扣掉_m2") or 0.0, _d.get("楼板块") or "—",
                 ("　★ " + _d["★"]) if _d.get("★") else ""))

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
            tot_thin += int(_d.get("收边没治好") or 0)
            # ★★ 2026-10-16 换过一版打印：旧口径的键（缺口/含门/无门/清边前/缝合后清边丢/超限丢）
            #   在逐扇门构造里**已经不存在**，`_d.get(...) or 0` 会把它们印成一整排 **0** ——
            #   读起来像「量到 0」，其实是「没这个键」（铁律 199：崩了与没量到要分开写；
            #   铁律 196：主语被换了，形状还照抄着）。
            #   ⇒ 只印**新构造真的往里写**的键，并且把 `漏因` 逐层摆出来（那才是「哪里出错了」的答案）。
            # ★ 铁律 174/194：`漏了` 与 `漏因` 是**同一个量的两个估计器**（一个按板并集量覆盖、
            #   一个按逐扇门的处置计数），它们不等（1层实测 87 vs 109）—— 两个都印出来、
            #   点明是哪个，别让读者以为「漏因加起来就是漏的扇数」。
            _why = _d.get("漏因") or {}
            print("   %-8s 门扇 %3d 有门头 %3d 漏 %d ｜ 漏因(逐扇归因 %d) %s ｜ 量到洞口 %s 块 %d"
                  " ｜ 清边丢块 %d 丢面积 %.0f mm² 裂块 %d ｜ 收边治好 %d 没治好 %d"
                  % (_d.get("层"), _l, _c, int(_d.get("漏了") or 0),
                     sum(int(t) for t in _why.values()),
                     json.dumps(_why, ensure_ascii=False),
                     _d.get("量到洞口"), int(_d.get("块") or 0),
                     int(_d.get("清边丢块") or 0), float(_d.get("清边丢面积_mm2") or 0.0),
                     int(_d.get("清边裂块") or 0),
                     int(_d.get("收边治了") or 0), int(_d.get("收边没治好") or 0)))
        # ★ 漏掉的门逐一报形状：`[距墙 mm, 距最近够大的门头块 mm, 门扇面积 mm²]`
        for _d in LINTEL_AUDIT:
            _ms = _d.get("漏明细_距墙_距块_面积") or []
            if _ms:
                print("     漏明细 %s%s（贴墙 %d=门洞未开 / 离墙 %d=源图无墙）：%s"
                      % (_d.get("层"), "（仅前 20 条）" if _d.get("漏明细_截断") else "",
                         int(_d.get("漏_贴墙") or 0), int(_d.get("漏_离墙") or 0),
                         "; ".join("d墙%.0f d块%.0f S%.0f @(%d,%d)" % tuple(m) for m in _ms)))
        print("   Σ 门扇 %d 有门头 %d ⇒ **漏 %d**（清边丢块合计 %d；收边没治好合计 %d）"
              % (tot_l, tot_c, tot_lost, tot_drop, tot_thin))
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
        # ★ 2026-10-18「从门起」的读数：有近门的梯间有几座、其中几座**被翻了**。
        #   「没近门」必须印成「没近门」，不许印 0（0 会被读成「门正好贴着第一级」）。
        _nd = [r for r in STAIR_FACT if r["门距_mm"] is not None]
        _fl = [r for r in _nd
               if r["门距_旧_mm"] is not None and abs(r["门距_mm"] - r["门距_旧_mm"]) > 1e-6]
        print("   ★ 「从门起」：%d/%d 座梯间有近门；其中 %d 座**被翻**（旧落位离门更远）"
              " —— 门距 %s → %s mm"
              % (len(_nd), len(STAIR_FACT), len(_fl),
                 sorted({r["门距_旧_mm"] for r in _fl}) or "—",
                 sorted({r["门距_mm"] for r in _fl}) or "—"))
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
        if TRIAL:
            raise RuntimeError("试算不写对照表（那是这一栋的读数账，不能被试算覆盖）")
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
    if os.path.exists(BLENDER) and not TRIAL:
        bp = os.path.join(OUT, "to_blend.py")
        with open(bp, "w", encoding="utf-8", newline="\n") as f:
            f.write("import bpy\n"
                    "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
                    "bpy.ops.import_scene.gltf(filepath=r'%s')\n"
                    "bpy.ops.wm.save_as_mainfile(filepath=r'%s')\n"
                    % (glb, os.path.join(OUT, "%s_white.blend" % OUT_NAME)))
        r = subprocess.run([BLENDER, "-b", "-P", bp], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        tail = (r.stdout or "")[-400:]
        print("Blender rc=%d %s" % (r.returncode, "OK" if r.returncode == 0 else tail))
    else:
        print("★ Blender 不在 %s ⇒ 跳过 .blend" % BLENDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
