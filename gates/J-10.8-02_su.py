# -*- coding: utf-8 -*-
"""判据 J-10.8-02 —— **正式件**（SketchUp 出的 `rebuild/06_su/c006_su.obj`）。

★ 与 `J-10.8-01` **不共用尺子**：那一份量参照件，参照物取自本仓自己的 `build.json`。
  本判据**一个字节都不读** `rebuild/05_build/build.json`（同源盲区：参照物与被测量出自
  同一个约定，约定错了它也看不见 —— 铁律 137/187/192）。正式件的参照只有两处，都在件之外：
  **源件 DXF**（`rebuild/01_cad/raw/*.dxf`，12 张）与**件自己的文本**。

★★ 参照物为什么是**柱块网格**而不是墙层外框（2026-10-13 第一版就栽在这）：
  第一版拿每张图 `4.2墙体` 图层的**外框**当墙脚，当场判 `1层 = 152650×83640`，
  而件是 `129300×84000` ⇒ 差 18%，看着像「件少建了一块」。**是尺子错了**：
  1层的 `4.2墙体` 图层里另有 **237 个非墙图元**（x 两侧各外扩约 11.9 m、242 条 LINE，
  中位长 2.19 m —— 室外散水/台阶/坡道那一类），2/3层同图层却只有 128940。
  ⇒ 改用 **`_FZHK`/`_YZHK` 柱块 INSERT 的**插入点**外框**：12 张图互相对齐（柱网同坐标）、
  且 INSERT 不含线状标注。实测逐层对得上，差恒为 **+600 mm**（件把墙厚算进去了）：
  ```
  层        源件柱网格(mm)     件侧 COL 带(mm)
  1–6层   128700 × 83400    129300 × 84000
  7层     108700 × 83400    109300 × 84000
  8–11层   45900 ×  19200     46500 ×  19800
  ```
  ★ 换来的是：**同一条尺子**（柱块）既当「柱数分母」（⑤）又当「平面参照」（②③⑪）。

★★ 件侧的**层键是有损的**（2026-10-13 实测，这条决定了 ⑤⑥⑪ 的写法）：
  OBJ 里 `g` 名长这样：`Mesh1 __1__WALL Model` / `Mesh7126 G_7__ROOF_STEP Model`。
  **`地下1层` 和 `1层` 都被压成同一个层键 `1`** —— SU 的 OBJ 导出把非 ASCII 字符丢掉了，
  `地下1层_COL` 与 `1层_COL` 于是同名。实测：层键 `'1'` 的 COL 组数 = **245 = 44(地下1层) + 201(1层)**，
  承重带 `[−3.50, 4.00] m` 也正好是两层摞在一起。
  ⇒ **不许拿层键当层号**。分层一律按**量出来的承重带**与源件的**名义层带**
  （`地下1层 [−3.5, 0]`、`n层 [4(n−1), 4n]`）**求交**配对：一个层键可以吃掉两个源层。
  ★ 这是**件本身的性质，不是判据的退让** —— 谁按 `g` 名分层，谁就会把 B1 和 1F 并成一层。

判据：
  ① 源件可读：12 张 dxf 都能打开、都能在柱块 INSERT 上量到柱网。缺一张 ⇒ **SKIP**
     （「没量到」不许当绿，也不许假报成 FAIL —— 铁律 199）。
  ② **单位**：件平面外框比柱网外框，在 `{1 mm, 0.001 m, 25.4 inch}` 里解；解不出或多解 ⇒ 红。
     ★ 盲区（**声明**）：纯几何解不出「数字是英寸」与「数字是毫米但大了 25.4 倍」——
     这两件事在几何上**完全同形**，只能靠 ⑩ 的声明去分。
  ③ **朝上轴**：三轴各当一次「高度」，剩下两轴排序后与柱网比 —— 对得上的才是高度轴，**不预设** Y/Z。
     解不出、或**多于一个轴**解得开（平面与高度同量级 ⇒ 分不开）⇒ 红。
  ④ **总高**：高度区间 ≈ `[B1高, 地上总高 + 4.0] m`。
     ★ 上界**不再写死**：`地上总高 = 11 × 层高`，层高取自 `rebuild/构件库/参数.json` 的
       `构件.共用.层高`（唯一真源）。★ 层高是**口径决定**（2026-10-15 用户令 3.5 m），
       不是实测数 ⇒ 本闸量的是「件与**声明的口径**是否自洽」，**不是**「件与影像是否相符」
       （影像那一半是**缺口**，写在 `参数.json` 的 `出处` 里，不在这里假装量过，铁律 199）。
     ★ 专抓两个真踩过的坑：附属件标高写成**绝对**值 ⇒ 84.0 m；单位当英寸读 ⇒ 3 284 m。
  ⑤ **逐层柱数**：件每个**层键**的 **`COL` 组数**（`g` 行数，**不是面数**）== 它所配到的
     源层柱块 INSERT 数**之和**（一个层键配到两个源层就是两层之和）。分母独立于本仓任何生成物。
  ⑥ **层距**：每个层键的承重带高 ≥ 3.0 m；层带**底** ≈ 它所配到的**最低**源层的名义层底（±0.25 m）；
     并且 **12 个源层必须各被配到恰好一次**（配重了/漏了都红 —— 这条替代了「层键数 == 12」）。
  ⑦ **顶部三件**：`PARAPET`/`ROOF_STAIR`/`ROOF_STEP` 各 ≥ 1 组。★ **两类分开判**：
     · `PARAPET`/`ROOF_STAIR` 长在**顶上** ⇒ 顶 ∈ `[地上总高, 地上总高 + 4.0]` m；
     · `ROOF_STEP`（台阶屋面）**不在顶上**（README §8 实测 `7层/ROOF_STEP z=27880.0mm`）
       ⇒ 顶必须落在**楼层边界**（**层高的整数倍** ±0.3）上，且 ≤ 女儿墙底（不许钻出去）。
     ★ 这里的「组 N 个」是 **`g` 行（SU 的 mesh）数**，**不是** SketchUp 里的组数：
     一个组里有两块互不相连的子实体 ⇒ 导出成 **2 个 `g` 行**。实测件里
     `Mesh7126/Mesh7127 G_7__ROOF_STEP`、`Mesh7129/Mesh7130 G_11__ROOF_STAIR`、
     `Mesh7128 G_11__PARAPET` ⇒ 读到 2/2/1 **不是**建重了，所以 ⑦ **不查「恰好 1 个」**。
     先前「三件都要落在顶上区间」是**错的期望**：那时「ROOF_STEP 顶到 7层顶」被当成违反，
     其实它落在 7层顶**就是对的**（0 基索引把它的读数搅成了 [24.00, 44.00]，连「顶在哪」都读错）。
     ★ 3.5 m 口径下 7层顶 = 24.50 m（层高 4.0 时是 28.00 m）—— 本闸**跟着参数表走**，
     不钉死任一个数（钉死就是「两个地方写同一个数」，铁律 018）。
  ⑧ **网格健全**：面里的 `f` 索引不许越界、面不许少于 3 点、相邻两顶点不许**指向同一个坐标**。
     ★ `f` 索引是 **1 基**的（OBJ 规范）—— 按 0 基读会让**每个面错位一个顶点**，
     症状是「层带莫名跨界 4 m」「末一个面索引越界」，全都**看着像件的毛病**。
     ★ 零长边的真坑：`round(…, 0.1 mm)` 把两个点圆成同一个数 ⇒ SU 的 `add_face`
     建不出长度 0 的边 ⇒ **静默少一张面**。★ shapely 的 `is_valid/is_simple` 对重复顶点判 True
     ⇒ 要用**下游程序**的口径，不是另一个库的口径。
  ⑨ **无 `nan`/`inf`**（铁律 123）。
  ⑩ **`EXPORT.md` 里管着 OBJ 的那一行**必须同时写出**实测出来的**单位与**实测出来的**朝上轴。
     ★ 必须**指到那一行**，不是「整篇里出现过这个词」—— 实测：`EXPORT.md` 同时写着
     `# File units = millimeters`（OBJ 行）和 `<unit meter="0.0254" name="inch">`（DAE 行），
     按整篇找词，把件放大 25.4 倍也照样绿（这一版就是这么漏过去的）。
  ⑪ **逐层柱网**：每个层键 `COL` 带的平面外框 ≈ 它所配到的源层里**最大**那个的柱网，
     **判绝对差 ≤ 700 mm**（**不判百分比**）。
     ★ 层键吃两层时（`'1'` = B1 + 1F），拿最大那个当参照是**两边的界**：件不能比它的最大分块小，
     也不该超出并集（B1 柱网 87.3×56.1 严格含在 1F 的 128.7×83.4 里 ⇒ 并集就是 1F 那个）。
     ★★ **为什么必须是绝对差**：源件柱块 INSERT 打的是柱**心**，件画的是柱**面** ⇒ 每边多半个
     柱宽，实测 12 层 × 两轴**恒为 +600 mm**（129300−128700、84000−83400、109300−108700、
     46500−45900、19800−19200）。同一个物理量在大屋面上是 0.47%、在小塔楼上就是 **3.13%**
     ⇒ 按 2% 卡会把塔楼 4 层（8~11层）**假红 3.1%**（铁律 18：拿相对量去量一个绝对量）。
量具：① ezdxf 读 12 张源图（柱块 INSERT 插入点外框 + 块名计数）；② **纯文本**读
  `c006_su.obj`（`v`/`g`/`f`），**不经 trimesh / 不经 Blender**；③ 读 `EXPORT.md` 文本。
  **件侧几何一律由 `v` 行现算**，bbox/逐层带/逐类计数都不落盘、不缓存（否则正对照只是在改缓存）。
量具盲区（声明）：
  · **高度本身没有源件参照**：12 张 DXF 是平面图，没有任何标高信息 ⇒ ④⑥ 的基准来自
    「12 张图 ⇒ 地上 11 层 + B1」+ 层高规则，**本来就不是我量出来的**；
    而且**层高本身也是口径决定**（参数表 `共用/层高`，2026-10-15 用户令 3.5 m）
    ⇒ ④ 只查「件顶是否落在**声明的**口径上」，**不查那个口径对不对**。
    ★ 真值侧的那把尺子是**影像（DSM）**，不是本闸 —— 它给出裙房 27.9 m / 塔楼 47.5 m，
    与 3.5 m 口径下的 24.5 / 38.5 m **有差**；这差是**缺口**，写在 `参数.json` 的 `出处` 里。
  · **女儿墙 1.2 m / 楼梯房 3.0 m / 台阶屋面**是**假设值** ⇒ ⑦ 只查「在顶上区间 / 落在楼层边界」。
  · ⑤⑪ 的配对靠**层带求交**：两层被整体对调且柱数相同（2/3/4层都是 197）时看不见。这条**承认**。
  · **门**：源件 `$DorLib2D$` 按**块**计，件侧 `DOOR` 按**组**计 ⇒ 两把尺子不同源，
    **不相等也不该相等**，只打印不判。
  · **窗**：源件 12 层图层并集里没有窗图层 ⇒ 不查（反证在 `J-10.8-01` ⑪）。
  · **`上`/`下`（136 个 TEXT，全在 `4.2墙体`）**：SU 的 DXF 导入**丢纯文字** ⇒ 件侧整类全盲
    ⇒ **不拿它当分母**（铁律 158）。
  · 不判**曲面 / 洞口位置 / 绕竖轴转向**；绕高度轴的旋转**在 ②③⑪ 里是不可见的**（平面排序后比）。
正对照（必配，每一条都必须按预期变红，**且变红的理由要对得上那一条**）：
  ★ 判据：与 C1 的基线**做差**，只看**这一条新添的**违反里有没有那个 marker
    —— 否则真件一旦本来就有红，所有对照都会「继承」同一个理由而全部显示变红（铁律 183）。
  · C1 真件 ⇒ **放行**；
  · C2 **高度拉伸到平面同量级** ⇒ ③ 必红（「分不开」那一支有分辨力）；
  · C3 **单位 ×25.4** ⇒ ⑩ 必红（×25.4 **就是**英寸假设本身，几何分不开 ⇒ 只能靠声明）；
  · C4 **截断到 60% 行**（复现导出中途被杀的半截件）⇒ ⑤/⑥/⑦ 至少一条红；
  · C5 **掉某个层键的 `COL` 组** ⇒ ⑤ 必红；
  · C6 **把顶层抬高 10 m** ⇒ ④/⑥ 必红（★ 位移必须按 `fac` 从米换成**文件单位**，
    件是 mm ⇒ 直接加 `10.0` 只挪 10 mm，判据不动，会误判成「判据没分辨力」）；
  · C7 **抹掉顶部三件** ⇒ ⑦ 必红；
  · C8 **造一条零长边**（相邻两顶点同坐标）⇒ ⑧ 必红；
  · C9 **塞一个 `nan`** ⇒ ⑨ 必红；
  · C10 **`EXPORT.md` 的 OBJ 行改成英寸**（只改内存文本）⇒ ⑩ 必红；
  · C11 **件 y↔z 对调但声明不动**（件合法地变成 z 朝上，声明仍说 Y）⇒ ⑩ 必红；
  · C12 **件单位 ×1000** ⇒ ② 必红（落在候选之外）；
  · C13 **`f` 索引整体 +1**（复现「按 0 基读」那个错法）⇒ ⑧ 必红。
  十三条里任一条不按预期 ⇒ 判据没分辨力，作废。
三态：OK（rc=0） / FAIL（rc=1） / SKIP（rc=4：源件或件读不到 —— 「没量到」，不算过、也不假报成 FAIL）。
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = r"D:\项目\cdut3d"
RAW = os.path.join(ROOT, "rebuild", "01_cad", "raw")
SU = os.path.join(ROOT, "rebuild", "06_su")
OBJ = os.path.join(SU, "c006_su.obj")
EXPMD = os.path.join(SU, "EXPORT.md")
HERE = os.path.dirname(os.path.abspath(__file__))
RUNDIR = os.path.join(HERE, "_out")
JSON_OUT = os.path.join(HERE, "_out", "J-10.8-02.json")
_LOG = []
# ★ 顶层读数：台账页 `demo/sys.html` 每条判据要三路独立读数（json 的 pass ／ run.txt 的 rc ／
#   判词行）。本闸原先只落 run.txt ⇒ 页面上「顶层字段」一节空着。这里只**搬运本闸已经算出来的量**，
#   一个数都不新造。`_MEAS` 只由 C1（真件）那次 judge 填 —— 正对照跑的是改过的顶点，
#   让它们写进来就等于拿伪造件冒充交付件的读数（铁律 192）。
_MEAS = {}
# ★ 盲区：**照抄 docstring 里已声明的那几条**（「量具盲区（声明）」一节），一条不增一条不减。
#   页面把 `blind` 当顶层字段印出来 —— 盲区清单离开 run.txt 也得跟着 json 走，否则读 json 的人
#   会把「本闸量不到的东西」当成「本闸说它没问题」（铁律 158）。
BLIND = [
    "高度本身没有源件参照（12 张 DXF 是平面图）；层高本身也是口径决定（参数表 共用/层高）"
    " ⇒ ④⑥ 只查「件是否落在**声明的**口径上」，不查那个口径与影像是否相符（真值侧看 DSM）",
    "女儿墙 1.2 m / 楼梯房 3.0 m / 台阶屋面的标高是**假设值** ⇒ ⑦ 只查「在顶上区间 / 落在楼层边界」",
    "⑤⑪ 的配对靠层带求交：两层被整体对调且柱数相同（2/3/4 层都是 197）时看不见",
    "门：源件 $DorLib2D$ 按块、件侧 DOOR 按组 ⇒ 两把尺子不同源，不相等也不该相等，只打印不判",
    "窗：源件 12 层图层并集里没有窗图层 ⇒ 不查",
    "上/下（136 个 TEXT，全在 4.2墙体）：SU 导入丢纯文字 ⇒ 件侧整类全盲，不拿它当分母",
    "不判曲面 / 洞口位置 / 绕竖轴转向；绕高度轴的旋转在 ②③⑪ 里不可见（平面排序后比）",
]

UNITS = ((1.0, "mm"), (0.001, "m"), (25.4, "inch"))
UNIT_WORDS = {"mm": ("millimeter", "毫米"), "m": ("meter", "米"),
              "inch": ("inch", "英寸")}
TOL_UNIT = 0.015        # 相对：件平面 vs 柱网（件比柱网多半个墙厚，实测 +0.5~0.7%）
# ★ ⑪ 的尺子必须判**绝对差**，不能判百分比。柱块的 INSERT 打的是柱**心**，件画的是柱**面**
#   ⇒ 件每边多半个柱宽；实测 12 层 × 两轴**恒为 +600 mm**：
#   129300−128700、84000−83400、109300−108700、46500−45900、19800−19200。
#   同一个物理量，在大屋面上是 0.47%、在小塔楼上就是 3.13% ⇒ **百分比是错的量具**：
#   按 2% 卡会把塔楼 4 层判红（铁律 18：两个地方写同一个数证明不了它是对的——
#   这里连"同一个数"都不是，是拿相对量去量一个绝对量）。
TOL_PLAN_MM = 700.0     # mm：逐层 COL 带 vs 该层柱网（恒 +600 mm，留 100 mm 富余）
TOL_BOT = 0.25          # m：层底标高
MIN_BAND = 3.0          # m：一个层键的承重带至少要有这么高
# ★★ 2026-10-15：层高改成**从参数表读**，不再在本文件里写死 4.0。
#   原来下面三处（`Z_TOP_MIN/MAX`、`NOM`、⑦ 的楼层边界）各写一份 4.0 —— 与
#   `rebuild/构件库/参数.json::构件.共用.层高` 构成**两个估计器**（铁律 018/174）。
#   后果不是「慢」，是**静默**：层高一改（2026-10-15 用户令 4.0 → 3.5），本闸仍按 4.0 判，
#   判词与件对不上却照样全绿 —— 这正是「两个地方写同一个数，一致证明不了它是对的」。
#   ★ 代价（铁律 28）：参数表若读不到（文件缺/键改名），本闸**在 import 期就死**，
#     表现是 rc≠0 而不是 rc=4 —— 与「件不在」那种 SKIP 分开看（铁律 199）。
_PARAM_JSON = os.path.join(ROOT, "rebuild", "构件库", "参数.json")
_pj = json.load(open(_PARAM_JSON, encoding="utf-8"))["构件"]
STOREY_M = float(_pj["共用"]["层高"]["值"]) / 1000.0     # m：地上层高（唯一真源 = 参数表）
B1_M = 3.5              # m：地下层层高。★ 这一条**还不在参数表里** ⇒ 只能写死；是已知缺口
CANON = ["地下1层"] + ["%d层" % n for n in range(1, 12)]   # 源件标高序（唯一独立次序）
N_FLOORS = len(CANON) - 1                                 # 地上层数 = 11（由源件次序数出，不另写）
TOP_M = N_FLOORS * STOREY_M                                # 地上总高
Z_TOP_SLACK = 4.0       # m：顶上三件（女儿墙 1.2 / 楼梯房 3.0）都该落在这段里；本闸只卡区间
Z_TOP_MIN, Z_TOP_MAX = TOP_M, TOP_M + Z_TOP_SLACK
# ⑦ 台阶屋面（ROOF_STEP）**不在顶上**：README §8 实测它落在 7层→8层 的梯段处
#   （`7层/ROOF_STEP z=27880.0mm`）。要求它落在顶上区间里是**错的期望**。
#   正确的判据：顶必须落在某个楼层边界上（**层高的整数倍**，±0.3），且**严格低于女儿墙底**。
STEP_ON_BOUNDARY = 0.3
COL_BLOCKS = ("_FZHK", "_YZHK")
DOOR_BLOCK = "$DORLIB2D$"
ATTACH = ("PARAPET", "ROOF_STAIR", "ROOF_STEP")
STRUCT = ("WALL", "COL")
NOM = {"地下1层": (-B1_M, 0.0)}
for _n in range(1, N_FLOORS + 1):
    NOM["%d层" % _n] = (STOREY_M * (_n - 1), STOREY_M * _n)


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


# ---------------------------------------------------------------- 源件侧（dxf）

def ent_pts(e):
    t = e.dxftype()
    if t == "LINE":
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    if t == "LWPOLYLINE":
        return [(p[0], p[1]) for p in e.get_points("xy")]
    if t in ("CIRCLE", "ARC"):
        c, r = e.dxf.center, e.dxf.radius
        return [(c.x - r, c.y - r), (c.x + r, c.y + r)]
    return []


def src_read(raw=RAW):
    """读 12 张源图：**柱块网格**（mm）+ 柱块数 + 门块数 + `4.2墙体` 外框（只用于说明尺子的坑）。

    读不到 ⇒ 那一项 `None`（「没量到」），**不填 0**（铁律 199：没量到与真的是 0 不许同形）。
    """
    import ezdxf
    grid, col, wall, doors = {}, {}, {}, 0
    files = sorted(fn for fn in os.listdir(raw) if fn.lower().endswith(".dxf"))
    for fn in files:
        sheet = os.path.splitext(fn)[0]
        try:
            doc = ezdxf.readfile(os.path.join(raw, fn))
        except Exception as e:                                     # noqa: BLE001
            log("  ★ %s 读不到：%s" % (sheet, e))
            grid[sheet] = col[sheet] = wall[sheet] = None
            continue
        xs, ys, n, wp = [], [], 0, []
        for e in doc.modelspace():
            t = e.dxftype()
            if t == "INSERT":
                nm = str(e.dxf.name).upper()
                if nm.startswith(COL_BLOCKS):
                    xs.append(e.dxf.insert.x)
                    ys.append(e.dxf.insert.y)
                    n += 1
                if nm.startswith(DOOR_BLOCK):
                    doors += 1
            elif e.dxf.layer == "4.2墙体":
                wp += ent_pts(e)
        grid[sheet] = None if not xs else (max(xs) - min(xs), max(ys) - min(ys))
        col[sheet] = n
        wall[sheet] = None if not wp else (max(p[0] for p in wp) - min(p[0] for p in wp),
                                           max(p[1] for p in wp) - min(p[1] for p in wp))
    return {"files": files, "grid": grid, "col": col, "wall": wall, "doors": doors}


# ---------------------------------------------------------------- 件侧（obj）

GRP = re.compile(r"^Mesh(\d+)\s+(.*?)\s+Model$", re.I)


def split_group(name):
    """`Mesh7126 G_7__ROOF_STEP Model` / `Mesh1 __1__WALL Model` → `("7", "ROOF_STEP")`。

    ★ 两代命名并存（带 `G_` / 不带），且中文被 SU 丢掉（`地下1层` 与 `1层` 都成 `1`）
      ⇒ 一律**按分隔符切**，不按位置/下标猜（按形状取字段）。层号**不可信**，只当键用。
    """
    m = GRP.match(name)
    stem = (m.group(2) if m else name).strip()
    parts = [p for p in stem.split("__") if p]
    if not parts:
        return "", "?"
    flo = re.sub(r"^G_", "", parts[0])
    return (flo, parts[-1]) if len(parts) >= 2 else ("", parts[0])


def read_obj(path):
    """纯文本读 OBJ。`g` 行**全保留**（7130 条）：面挂在**组**上，组挂在 (层键,类) 上。

    ★ `f` 索引是 **1 基**（OBJ 规范）：`- 1` 之后才是列表下标；负数是「从末尾数」。
      按 0 基读 ⇒ 每个面错位一个顶点 ⇒ 层带跨界、末面「索引越界」，全都像件的毛病。
    ★ 第一版还把同名的组并成一个 (层,类) 键 ⇒ ⑤ 数出来的是**面数**而不是**组数**，
      两个都像个数、都恒绿。**组数必须来自独立清单**（这里 = `g` 行）。
    """
    verts, groups, faces, bad = [], [], [], []
    cur = -1
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            if line.startswith("v "):
                p = line.split()
                if len(p) < 4:
                    bad.append("第 %d 行 v 列数不足：%r" % (ln, line[:60]))
                    continue
                try:
                    xyz = (float(p[1]), float(p[2]), float(p[3]))
                except ValueError:
                    bad.append("第 %d 行 v 不是数（nan/inf？）：%r" % (ln, line[:60]))
                    continue
                if any(not math.isfinite(c) for c in xyz):
                    bad.append("第 %d 行 v 有 nan/inf：%r" % (ln, line[:60]))
                verts.append(xyz)
            elif line.startswith("g "):
                groups.append(split_group(line[2:].strip()))
                cur = len(groups) - 1
            elif line.startswith("f "):
                try:
                    raw = [int(t.split("/")[0]) for t in line.split()[1:]]
                except ValueError:
                    bad.append("第 %d 行 f 不是索引：%r" % (ln, line[:60]))
                    continue
                idx = tuple((i - 1) if i > 0 else (len(verts) + i) for i in raw)
                faces.append((cur, idx))
    return {"verts": verts, "groups": groups, "faces": faces, "bad": bad, "path": path}


def bounds(pts):
    if not pts:
        return None
    return [[min(p[i] for p in pts) for i in range(3)],
            [max(p[i] for p in pts) for i in range(3)]]


def mesh_bad(m, cap=5):
    """⑧：索引越界 / 面不足 3 点 / 相邻两顶点**指向同一个坐标**（含闭合那对）。"""
    v = m["verts"]
    out = []
    for g, idx in m["faces"]:
        if any(i < 0 or i >= len(v) for i in idx):
            out.append("组 %s 的 f 行索引越界（v 只有 %d 个）：%s"
                       % (m["groups"][g], len(v), idx[:6]))
        elif len(idx) < 3:
            out.append("组 %s 面不足 3 点：%s" % (m["groups"][g], idx[:6]))
        else:
            for a in range(len(idx)):
                b = (a + 1) % len(idx)
                if v[idx[a]] == v[idx[b]]:
                    out.append("组 %s 上 %s 与 %s 同坐标 %s"
                               % (m["groups"][g], idx[a], idx[b], v[idx[a]]))
                    break
        if len(out) >= cap:
            break
    return out


# ---------------------------------------------------------------- 解 单位 / 朝上轴

def solve_frame(bb, ref_mm):
    """逐轴试：哪个轴当「高度」时，剩下两轴**排序后**能与柱网对上（平面可转 90°，故排序后比）。

    返回 `(ok_axes, hits)`：`ok_axes` = 解得开的轴；`hits` = [(轴, 单位, 系数, 误差)]。
    **不返回 best** —— 要判「分不开」就得看得见全部解。
    """
    ext = [bb[1][i] - bb[0][i] for i in range(3)]
    pw, ph = sorted(ref_mm, reverse=True)
    hits = []
    for k in range(3):
        pair = sorted([ext[i] for i in range(3) if i != k], reverse=True)
        if pair[1] <= 0:
            continue
        for f, un in UNITS:
            err = max(abs(pair[0] / (pw * f) - 1.0), abs(pair[1] / (ph * f) - 1.0))
            if err <= TOL_UNIT:
                hits.append(("xyz"[k], un, f, err))
    return sorted({h[0] for h in hits}), hits


# ---------------------------------------------------------------- 判

def judge(m, src, doc, meas=None):
    """返回违反串列表（空 = 合格）。件侧几何**全部**从 `m["verts"]` 现算。

    ★ `meas` 是**只读搬运用的空桶**（默认 None）：C1 调用时递进来，把下面已经算出来的量原样
      抄进去落 json；正对照（C2~C13）不递 ⇒ 它们改过的顶点读数**不会**冒充真件。判定逻辑不受它影响。
    """
    bad = []
    bb = bounds(m["verts"])
    if bb is None:
        return ["④ 件里一个 `v` 都没有（不是空件就是没读到）"]

    grids = [g for g in src["grid"].values() if g]
    if len(grids) != 12:
        bad.append("① 只量到 %d/12 张图的柱网（读不到的层：%s）"
                   % (len(grids), [s for s, g in src["grid"].items() if not g]))
        return bad
    ref_mm = (max(g[0] for g in grids), max(g[1] for g in grids))

    # ②③ 单位 / 朝上轴
    axes, hits = solve_frame(bb, ref_mm)
    ext = ["%.0f" % (bb[1][i] - bb[0][i]) for i in range(3)]
    if not axes:
        bad.append("② 单位解不出：件三轴 %s 对不上柱网 %s（候选 %s）"
                   % (ext, ["%.0f" % x for x in ref_mm], [u for _, u in UNITS]))
        return bad
    if len(axes) > 1:
        bad.append("③ 朝上轴**分不开**：%d 个轴都解得开（件三轴 %s 与柱网 %s 同量级）⇒ %s"
                   % (len(axes), ext, ["%.0f" % x for x in ref_mm], hits))
        return bad
    ax = axes[0]
    k = "xyz".index(ax)
    units = {h[1] for h in hits}
    if len(units) != 1:
        bad.append("② 单位**分不开**：同一条轴上 %s 都成立" % sorted(units))
        return bad
    unit, fac = hits[0][1], hits[0][2]
    plan = sorted([(bb[1][i] - bb[0][i]) / fac / 1000.0 for i in range(3) if i != k],
                  reverse=True)
    zlo, zhi = bb[0][k] / fac / 1000.0, bb[1][k] / fac / 1000.0
    log("  ② 单位 = **%s**（平面 %.1f×%.1f m vs 柱网 %.0f×%.0f mm，误差 %.2f%%）"
        % (unit, plan[0], plan[1], ref_mm[0], ref_mm[1], hits[0][3] * 100.0))
    log("  ③ 朝上轴 = **%s**（三轴各当一次高度，只有它剩下的两轴对得上柱网 ⇒ 不是预设的）" % ax)

    # ④ 总高（区间上界 = 地上总高 + 4.0 m，地上总高由参数表的层高算出，不写死）
    if not (Z_TOP_MIN <= zhi <= Z_TOP_MAX):
        bad.append("④ 件顶到 **%.2f m**，不在 [%.1f, %.1f]（= 11 × 层高 %.2f m 起 4 m）"
                   " —— 单位/轴错，或附属件标高用了绝对标高"
                   % (zhi, Z_TOP_MIN, Z_TOP_MAX, STOREY_M))
    if abs(zlo - (-B1_M)) > TOL_BOT:
        bad.append("④ 件底 **%.2f m**，应 ≈ −%.2f m（地下一层）" % (zlo, B1_M))

    if meas is not None:                       # ★ 只搬运，不判定
        meas["unit"] = unit
        meas["up_axis"] = ax
        meas["bbox_m"] = [round(zlo, 3), round(zhi, 3)]     # 件包围盒的高度区间 [底, 顶]（m）

    # 逐层键 / 逐类 现算：组数（独立清单）+ 带范围
    per = {}
    for key in m["groups"]:
        per.setdefault(key, {"g": 0, "n": 0,
                             "lo": [float("inf")] * 3, "hi": [float("-inf")] * 3})["g"] += 1
    for gi, idx in m["faces"]:
        if gi < 0:
            continue
        d = per[m["groups"][gi]]
        d["n"] += 1
        for i in idx:
            if 0 <= i < len(m["verts"]):
                p = m["verts"][i]
                for c in range(3):
                    d["lo"][c] = min(d["lo"][c], p[c])
                    d["hi"][c] = max(d["hi"][c], p[c])

    def zbnd(key, classes=STRUCT):
        lo, hi = float("inf"), float("-inf")
        for (f, c), d in per.items():
            if f == key and c in classes and d["n"] and d["lo"][k] != float("inf"):
                lo, hi = min(lo, d["lo"][k]), max(hi, d["hi"][k])
        return (None, None) if lo == float("inf") else (lo / fac / 1000.0, hi / fac / 1000.0)

    keys = sorted({f for f, _ in per},
                  key=lambda f: (zbnd(f)[0] if zbnd(f)[0] is not None else 1e9))
    log("  件里量到 **%d** 个层键：%s" % (len(keys), keys))
    log("     ★ 层键是**有损**的：`地下1层` 与 `1层` 都被 SU 压成 `1` ⇒ 分层按承重带求交，不按名字")

    # ⑤⑥⑪ 的配对：按「量出来的承重带」∩「源件名义层带」，> 0.5 m 才算配到
    pair, band_bad = {}, []
    for f in keys:
        z0, z1 = zbnd(f)
        if z0 is None:
            band_bad.append("⑥ 层键 %r 没有承重构件组（WALL/COL），量不到承重带" % f)
            continue
        pair[f] = [s for s in CANON if min(z1, NOM[s][1]) - max(z0, NOM[s][0]) > 0.5]
    log("  配对（层键 ← 源层）：%s" % {f: pair.get(f, []) for f in keys})

    claimed = {}
    for f, got in pair.items():
        for s in got:
            claimed.setdefault(s, []).append(f)
    for s in CANON:
        if s not in claimed:
            band_bad.append("⑥ 源层 %s 没有任何层键配到它（漏了一层）" % s)
        elif len(claimed[s]) > 1:
            band_bad.append("⑥ 源层 %s 被 %d 个层键同时配到 —— 层带重叠" % (s, len(claimed[s])))
    for f, got in pair.items():
        if not got:
            z = zbnd(f)
            band_bad.append("⑥ 层键 %r 的承重带 [%.2f, %.2f] m 配不到任何源层"
                            % (f, z[0] or 0.0, z[1] or 0.0))

    for f in keys:
        z0, z1 = zbnd(f)
        if z0 is None:
            continue
        if (z1 - z0) < MIN_BAND:
            band_bad.append("⑥ 层键 %r 承重带只有 %.2f m 高（墙柱应是整层高）" % (f, z1 - z0))
        if pair.get(f):
            want = min(NOM[s][0] for s in pair[f])
            if abs(z0 - want) > TOL_BOT:
                band_bad.append("⑥ 层键 %r 承重带底 %.2f m ≠ 它配到的层应有 %.2f m"
                                % (f, z0, want))
        log("     层键 %-8r 承重带 [%7.2f, %7.2f] m ← %s" % (f, z0, z1, pair.get(f, [])))

    # ⑤ 逐层柱数（**组数**，按配到的源层求和）
    src_col = [src["col"].get(s) for s in CANON]
    if any(v is None for v in src_col):
        bad.append("⑤ 源件柱块数没量全：%s" % list(zip(CANON, src_col)))
    else:
        log("  ⑤ 源件逐层柱块 INSERT = %s（独立合计 %d）" % (src_col, sum(src_col)))
        got_all = [per.get((f, "COL"), {}).get("g", 0) for f in keys]
        want_all = [sum(src["col"][s] for s in pair.get(f, [])) for f in keys]
        log("  ⑤ 件侧逐层 COL 组数     = %s（合计 %d）" % (got_all, sum(got_all)))
        log("  ⑤ 按配对求和应得       = %s（合计 %d）" % (want_all, sum(want_all)))
        for f, g, w in zip(keys, got_all, want_all):
            if g != w:
                bad.append("⑤ 层键 %r 的 COL **组**数 %d ≠ 它配到的 %s 柱块之和 %d"
                           % (f, g, pair.get(f, []), w))

    # ⑪ 逐层柱网（COL 带 vs 配到的源层里最大那个）
    # ★ 判**绝对差**，不判百分比：柱块的插入点是柱**心**，件画的是柱**面** ⇒ 每边多半个柱宽，
    #   实测 12 层 × 两轴**恒为 +600 mm**（129300−128700、84000−83400、46500−45900…）。
    #   同一个物理原因，在大屋面上是 0.47%、在小塔楼上就是 3.13% ⇒ **百分比是错的量具**：
    #   按 2% 卡，塔楼 4 层会假红（铁律 18：两个地方写同一个数∝拿相对量去量一个绝对量）。
    for f in keys:
        d = per.get((f, "COL"))
        if not d or not d["n"]:
            bad.append("⑪ 层键 %r 没有 COL 组" % f)
            continue
        if not pair.get(f):
            continue
        ref_s = max(pair[f], key=lambda s: (src["grid"][s][0] * src["grid"][s][1])
                    if src["grid"][s] else 0)
        g = src["grid"][ref_s]
        if not g:
            continue
        pw = sorted([(d["hi"][c] - d["lo"][c]) / fac for c in range(3) if c != k], reverse=True)
        rp = sorted([g[0], g[1]], reverse=True)
        dd = max(abs(pw[0] - rp[0]), abs(pw[1] - rp[1]))
        log("  ⑪ 层键 %-5r 柱网 %.0f×%.0f mm vs 源图 %-8s %.0f×%.0f mm（差 %+.0f mm）"
            % (f, pw[0], pw[1], ref_s, rp[0], rp[1],
               (pw[0] - rp[0]) if abs(pw[0] - rp[0]) >= abs(pw[1] - rp[1])
               else (pw[1] - rp[1])))
        if dd > TOL_PLAN_MM:
            bad.append("⑪ 层键 %r 的柱网 %.0f×%.0f mm vs 源图 %s 的 %.0f×%.0f mm（差 %.0f mm，"
                       "超过半个柱宽的 %d mm）" % (f, pw[0], pw[1], ref_s, rp[0], rp[1], dd, TOL_PLAN_MM))
    bad += band_bad

    # ⑦ 顶部三件
    # ★ 两类判据**不可合并**（铁律 196：收口共用函数时主语被悄悄换掉）：
    #   · PARAPET / ROOF_STAIR 长在**顶上** ⇒ 顶 ∈ [地上总高, 地上总高 + 4.0]；
    #   · ROOF_STEP（台阶屋面）**不长在顶上** —— README §8 实测它落在 7层→8层 的梯段处
    #     （`7层/ROOF_STEP z=27880.0mm`，3.5 m 口径下 7层顶 = 24.50 m）。
    #     先前「三件都要落在顶上」是**错的期望**；
    #     那条「顶到 7层顶」的读数本身是 0 基索引的假象，改对索引后它变成 [24.00, 44.00]。
    #   · ROOF_STEP 判两层：① 顶落在**楼层边界**（**层高的整数倍** ±0.3）上——它就该落在
    #     7层顶，正是 README §8 记的 `7层/ROOF_STEP z=27880.0mm`；② 顶 ≤ 女儿墙底（不许钻出去）。
    #     ★ 先前那条「件侧量不出、只能看关系」的说法**是错的**：它来自按 0 基读 `f` 索引的
    #     假读数（那时量到 [24.00, 44.00]）。改对索引后实测 [27.88, 28.00]（层高 4.0 时）——
    #     尺子坏的时候「量不出」和「量出来是错的」长得一模一样（铁律 199）。
    #   ★ 层高的整数倍**不是本文件取的**：`STOREY_M` 来自参数表（铁律 018/174）。
    ptop = None
    for cls in ATTACH:
        ks = sorted({f for (f, c), d in per.items() if c == cls and d["n"]})
        if not ks:
            bad.append("⑦ 顶部 %s 一件都没有（源图没有屋顶图 ⇒ 是按规则推的，但不许推完不建）" % cls)
            continue
        zb = min(per[(f, cls)]["lo"][k] for f in ks) / fac / 1000.0
        zt = max(per[(f, cls)]["hi"][k] for f in ks) / fac / 1000.0
        log("  ⑦ %-10s 组 %d 个，标高 [%.2f, %.2f] m"
            % (cls, sum(per[(f, cls)]["g"] for f in ks), zb, zt))
        if cls == "ROOF_STEP":
            # 台阶屋面自己那一层**能**量（改对 1 基索引后 = [27.88, 28.00] @层高4.0）。
            near = min(abs(zt - STOREY_M * n) for n in range(0, N_FLOORS + 4))
            if near > STEP_ON_BOUNDARY:
                bad.append("⑦ %s 顶到 %.2f m，不落在任何楼层边界上"
                           "（最近的 %.2f m 层高边界差 %.2f m）"
                           % (cls, zt, STOREY_M, near))
            if ptop is not None and zt > ptop + 1e-6:
                bad.append("⑦ %s 顶到 %.2f m，**钻出了女儿墙底** %.2f m（台阶屋面不该是全楼最高处）"
                           % (cls, zt, ptop))
        else:
            if not (Z_TOP_MIN <= zt <= Z_TOP_MAX):
                bad.append("⑦ %s 顶到 %.2f m，不在 [%.1f, %.1f]（= 11 × 层高 %.2f m 起 4 m）"
                           "（不在顶上，或标高是两个原点相加）"
                           % (cls, zt, Z_TOP_MIN, Z_TOP_MAX, STOREY_M))
            if cls == "PARAPET":
                ptop = zb

    # ⑧⑨
    bad += ["⑨ %s" % b for b in m["bad"][:3]]
    zs = mesh_bad(m)
    if zs:
        bad.append("⑧ %s" % zs[0])

    # ⑩ EXPORT.md **管着 OBJ 的那一行** vs 实测
    if doc is None:
        bad.append("⑩ 读不到 EXPORT.md（README §1 要求写明导出器 + 单位 + 朝上轴）")
    else:
        # ★ 必须**认全名**（含 `.obj`）。先前只匹配裸词干 `c006_su`，于是
        #   `| c006_su.skp | … | SU 内部 **Z 朝上** |` 和 `.dae` 行都被吸进来
        #   ⇒ 判据读的**不是**管着 OBJ 的那一行（铁律 192：参照物必须与交付件同作用域）。
        #   症状：C3（单位 ×25.4）与 C11（y↔z 对调）都「★没动」——因为选中行里的
        #   「毫米/英寸/Z 朝上」是隔壁那一行的字，单位怎么改它都不动。
        objname = os.path.basename(OBJ)
        row = [ln.strip() for ln in doc.splitlines() if objname in ln]
        if not row:
            bad.append("⑩ EXPORT.md 里没有一件一行是写给 %s 的（README §1 要求）" % objname)
        else:
            low = " | ".join(row).lower()
            if not any(w in low for w in UNIT_WORDS[unit]):
                bad.append("⑩ 管着 OBJ 的那一行没写出**实测单位** «%s»（会找 %s）：%s"
                           % (unit, UNIT_WORDS[unit], row[0][:90]))
            up = "%s 朝上" % ax.upper()
            if up.lower() not in low and ("%s_UP" % ax.upper()).lower() not in low:
                bad.append("⑩ 管着 OBJ 的那一行没写出**实测的**朝上轴 «%s»：%s" % (up, row[0][:90]))
    log("  ⑩ 实测 = %s / %s 朝上；EXPORT.md **管着 OBJ 的那一行**是**不同源的另一处**，对不上就红"
        % (unit, ax.upper()))
    if meas is not None:                       # ★ 只搬运，不判定
        meas["n_layer_keys"] = len(keys)
        meas["col_groups_total"] = sum(per.get((f, "COL"), {}).get("g", 0) for f in keys)
        meas["src_col_total"] = sum(v for v in src["col"].values() if v)
    return bad


# ---------------------------------------------------------------- 正对照（改顶点，不改缓存）

def permute(m, perm):
    out = copy.deepcopy(m)
    out["verts"] = [tuple(p[i] for i in perm) for p in m["verts"]]
    return out


def scale(m, f):
    out = copy.deepcopy(m)
    out["verts"] = [tuple(c * f for c in p) for p in m["verts"]]
    return out


def stretch_axis(m, f, k):
    """只把高度轴拉长 `f` 倍 —— 让平面与高度同量级 ⇒ 朝上轴分不开。"""
    out = copy.deepcopy(m)
    out["verts"] = [tuple((c * f if i == k else c) for i, c in enumerate(p))
                    for p in m["verts"]]
    return out


def shift_key(m, key, dz, k):
    out = copy.deepcopy(m)
    if key is None:
        return out
    idxs = {i for g, idx in m["faces"] if m["groups"][g][0] == key for i in idx}
    for i in idxs:
        if 0 <= i < len(out["verts"]):
            p = list(out["verts"][i])
            p[k] += dz
            out["verts"][i] = tuple(p)
    return out


def drop_class(m, key, cls):
    """把某个层键下的某一类**整组**去掉（组簿与面一起改，否则 ⑤ 数不到变化）。"""
    out = copy.deepcopy(m)
    drop = {i for i, (f, c) in enumerate(m["groups"]) if f == key and c == cls}
    if not drop:
        return out
    remap, keep = {}, []
    for i, key_i in enumerate(m["groups"]):
        if i not in drop:
            remap[i] = len(keep)
            keep.append(key_i)
    out["groups"] = keep
    out["faces"] = [(remap[g], idx) for g, idx in m["faces"] if g in remap]
    return out


def drop_classes(m, classes):
    out = copy.deepcopy(m)
    keep = [i for i, (f, c) in enumerate(m["groups"]) if c not in classes]
    remap = {old: i for i, old in enumerate(keep)}
    out["groups"] = [m["groups"][i] for i in keep]
    out["faces"] = [(remap[g], idx) for g, idx in m["faces"] if g in remap]
    return out


def main():
    for p in (OBJ, EXPMD):
        if not os.path.exists(p):
            log("SKIP：%s 不在（正式件还没出）" % p)
            _write(4)
            return 4
    src = src_read(RAW)
    n_ok = sum(1 for g in src["grid"].values() if g)
    if len(src["files"]) != 12 or n_ok != 12:
        log("SKIP：源件 %d 张 dxf、柱网量到 %d 张 —— 「没量到」，不算过、也不报成 FAIL（铁律 199）"
            % (len(src["files"]), n_ok))
        _write(4)
        return 4
    log("源件：12 张 dxf")
    for s in CANON:
        g, c, w = src["grid"][s], src["col"][s], src["wall"][s]
        log("   %-8s 柱网 %-16s 柱块 %3d    `4.2墙体`外框 %s"
            % (s, ("%.0f×%.0f" % g) if g else "没量到", c or 0,
               ("%.0f×%.0f" % w) if w else "没量到"))
    log("  ★ 尺子的坑（2026-10-13 实测）：`4.2墙体` 图层**不纯** —— 1层外框 152650 比 2/3层"
        "的 128940 多 23710 mm，多出来的是室外散水/台阶/坡道那类图元（x 两侧各外扩约 11.9 m、"
        "242 条 LINE，中位长 2.19 m）。⇒ **参照一律用柱块 INSERT 的插入点外框**，不用任何图层 bbox")
    log("  ★ 门块 `%s*` = %d 个：**只打印不判**（源件按块、件侧按组，两把尺子不同源）"
        % (DOOR_BLOCK, src["doors"]))
    log("  ★ 「上/下」(136 个 TEXT，全在 `4.2墙体`)：SU 导入丢纯文字 ⇒ 件侧**整类全盲**，"
        "不拿它当分母（铁律 158）")

    m = read_obj(OBJ)
    doc = open(EXPMD, encoding="utf-8", errors="replace").read()
    log("件：%s —— v=%d · f=%d · g=%d（`g` 行全保留：组数要来自独立清单，不能拿面数顶替）"
        % (os.path.basename(OBJ), len(m["verts"]), len(m["faces"]), len(m["groups"])))
    # ★ 顶层读数（只搬运）：面数 / `g` 行数 —— 真件侧最直接的两把数
    _MEAS["faces"] = len(m["faces"])
    _MEAS["groups"] = len(m["groups"])

    f1 = judge(m, src, doc, _MEAS)
    log("C1 真件：违反 %d 条 ⇒ %s" % (len(f1), "放行" if not f1 else "★红了"))
    for v in f1:
        log("     - %s" % v)
    ok = not f1
    base = set(f1)

    # 正对照要点哪一层：先解一次轴（**只用来选层键**，不参与判断）
    axes, hits = solve_frame(bounds(m["verts"]),
                             (max(g[0] for g in src["grid"].values() if g),
                              max(g[1] for g in src["grid"].values() if g)))
    k = "xyz".index(axes[0]) if axes else 1
    # ★ 顶点坐标是**文件单位**，不是米：`fac` = 文件单位/mm（mm⇒1、m⇒0.001、inch⇒25.4）。
    #   先前 `shift_key(m, keytop, 10.0, k)` 把「10 m」直接当成 10 个文件单位加进去 ——
    #   件是 mm ⇒ 只挪了 **10 mm**，判据当然不动（症状：⑤ 里的标高从 44.00 变成 44.01，
    #   而承重带 [40.00, 44.00] 显示上像是没变）。这是**尺子换算**的错，不是判据的错。
    fac = hits[0][2] if hits else 1.0
    dz10m = 10.0 * 1000.0 * fac        # 10 m 换成文件单位
    zb = {}
    for g, idx in m["faces"]:
        f = m["groups"][g][0]
        for i in idx:
            if 0 <= i < len(m["verts"]):
                v = m["verts"][i][k]
                if f not in zb or v < zb[f]:
                    zb[f] = v
    order = sorted(zb, key=lambda f: zb[f])
    key3 = order[2] if len(order) > 2 else None
    keytop = order[-1] if order else None
    log("\n---- 正对照（每一条都必须按预期变红，且理由要对上）----")
    log("   ★ 判据：与 C1 的基线**做差**，只看这一条**新添的**违反里有没有那个 marker")

    def ctl(name, mm, expect, doc2=None):
        nonlocal ok
        fs = judge(mm, copy.deepcopy(src), doc2 if doc2 is not None else doc)
        new = [x for x in fs if x not in base]
        right = any(any(e in x for e in expect) for x in new)
        ok = ok and right
        log("  %-32s → %s（新增 %d 条，要 %s）%s"
            % (name, "✔红" if new else "★没动", len(new), "/".join(expect),
               "" if not new else new[0]))
        if new and not right:
            log("      ★ 红的理由不对：要 %s，实得 %s"
                % ("/".join(expect), sorted({x.split()[0] for x in new})))
        elif not new:
            log("      ★ 这一条没让判据动起来 ⇒ 它对这类坏件没有分辨力")

    # ★★ 2026-10-15 修：这里原先是 `stretch_axis(m, 84000.0 / 50500.0, k)` ——
    #   `50 500` 是**4.0 m 档那件的老总高**，手打进来的一个常数。层高改成 3.5 m 后件只有
    #   45 000 mm 高，于是拉出来是 **74.85 m**，与平面两轴（129.3 / 84.0）**都不等**
    #   ⇒ 三轴里照样只有一个解得开 ⇒ ③ **根本没红** ⇒ 这条对照**静默失去分辨力**，
    #   而它正是用来证明「③ 分不开那一支有分辨力」的那一条（铁律 137/183）。
    #   实测那一趟的判词：`C2 → ✔红（要 ③）★ 红的理由不对：实得 ['④','⑤','⑥','⑦','⑪']`，
    #   顶到 **69.03 m** = 45 000×1.6634 − 3 500×1.6634（正是 84 000/50 500 这个老比值）。
    #   改成**从件自己现算**：目标 = 该件两个平面轴里**较小的**那个 ⇒ 高度与平面同量级，
    #   朝上轴必「分不开」（铁律 018/174：同一个数不许在两处各写一遍，第二处会悄悄停在老口径）。
    _bb2 = bounds(m["verts"])
    _ext2 = [_bb2[1][i] - _bb2[0][i] for i in range(3)]
    _tgt2 = sorted([_ext2[i] for i in range(3) if i != k])[0]
    ctl("C2 高度拉伸到 %.0f mm（平面同量级）" % _tgt2,
        stretch_axis(m, _tgt2 / _ext2[k], k), ["③"])
    ctl("C3 单位 ×25.4（= 英寸假设本身）", scale(m, 25.4), ["⑩"])
    ctl("C12 单位 ×1000", scale(m, 1000.0), ["②"])

    # C4 截断：真把前 60% 行写成临时件再读（复现导出中途被杀那次的半截件）
    tmp = tempfile.mkdtemp(prefix="j10802_")
    try:
        with open(OBJ, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        half = os.path.join(tmp, "trunc.obj")
        with open(half, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lines[: int(len(lines) * 0.6)])
        ctl("C4 截断到 60%", read_obj(half), ["④", "⑤", "⑥", "⑦"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ctl("C5 掉层键 %r 的 COL 组" % key3, drop_class(m, key3, "COL"), ["⑤"])
    ctl("C6 顶层键 %r 抬高 10 m" % keytop, shift_key(m, keytop, dz10m, k), ["④", "⑥"])
    ctl("C7 抹掉顶部四件", drop_classes(m, ATTACH), ["⑦"])

    def c8(mm):
        out = copy.deepcopy(mm)
        g, idx = out["faces"][0]
        out["verts"][idx[1]] = out["verts"][idx[0]]     # 第二个点与第一个点同坐标 = 零长边
        return out
    ctl("C8 造一条零长边", c8(m), ["⑧"])

    def c9(mm):
        out = copy.deepcopy(mm)
        out["bad"] = list(mm["bad"]) + ["第 1 行 v 有 nan/inf：'v nan nan nan'"]
        return out
    ctl("C9 塞一个 nan", c9(m), ["⑨"])

    def c13(mm):
        """`f` 索引整体 +1 ⇒ 复现「按 0 基读」那个错法（每个面错位一个顶点）。"""
        out = copy.deepcopy(mm)
        out["faces"] = [(g, tuple(i + 1 for i in idx)) for g, idx in mm["faces"]]
        return out
    ctl("C13 f 索引整体 +1（0 基错法）", c13(m), ["⑧"])

    d2 = "\n".join(ln.replace("millimeters", "inches").replace("毫米", "英寸")
                   if "c006_su.obj" in ln else ln for ln in doc.splitlines())
    if d2 == doc:
        log("  %-32s → ★跳过（在 OBJ 那一行里没找到要改的单位词）⇒ 这条对照没量到东西"
            % "C10 OBJ 行改成英寸")
        ok = False
    else:
        ctl("C10 OBJ 行改成英寸（只改内存）", m, ["⑩"], doc2=d2)

    # C11 件 y↔z 对调、声明不动 ⇒ 件合法地成了 z 朝上，只有 ⑩ 该红（③ 不该红，它不预设轴）
    fs11 = judge(permute(m, (0, 2, 1)), src, doc)
    new11 = [x for x in fs11 if x not in base]
    right11 = bool(new11) and all("⑩" in x for x in new11)
    ok = ok and right11
    log("  %-32s → %s（新增 %d 条，要 ⑩ 且只要 ⑩）%s"
        % ("C11 件对调 y↔z、声明不动", "✔红" if new11 else "★没动", len(new11),
           "" if not new11 else new11[0]))
    if new11 and not right11:
        log("      ★ 红的理由不对：要「只有 ⑩」，实得 %s" % sorted({x.split()[0] for x in new11}))

    log("\n===== 判词 =====")
    log("J-10.8-02 总判 :", "PASS" if ok else "FAIL")
    rc = 0 if ok else 1
    _write(rc)
    return rc


def _write(rc):
    """落两样产物：run.txt（判词行，原样）＋ json（顶层读数，页面第三路）。

    ★ 退出码**不在这里算** —— 由调用方把 `rc` 递进来，`pass` 只是 `rc == 0` 的同一件事，
      免得两处各写一遍「什么算过」（铁律 18）。
    """
    os.makedirs(RUNDIR, exist_ok=True)
    with open(os.path.join(RUNDIR, "J-10.8-02.run.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    # ★ 第三路读数：本闸**真正量到**的顶层字段。`pass` 与退出码同源（rc==0），其余是上面已算出的量。
    out = {"pass": rc == 0, "rc": rc}
    out.update(_MEAS)
    out["blind"] = list(BLIND)
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    json.dump(out, open(JSON_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  写出:", JSON_OUT)


if __name__ == "__main__":
    sys.exit(main())
