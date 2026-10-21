# -*- coding: utf-8 -*-
"""判据 J-10.8-00 —— **入口门**：`contours/*.json` 能不能喂给 SketchUp。

★ 编号 `-00` 表示它在 `-01`（参照件）/`-02`（正式件）**之前**：它量的是**进 SU 之前的输入**，
  不是 SU 出来的件。三者量的东西**互不相同**，都要留着：
    · `-00` 本闸：这份 JSON **SU 吃不吃得下**（环闭合/互异点/共面/无洞/不重叠/规模/单位）；
    · `-01`    ：参照件 `05_build/c006_white.*` 对不对（拿 `build.json` 当参照）；
    · `-02`    ：正式件 `06_su/c006_su.obj` 对不对（拿**源件 DXF** 当参照，不读 `build.json`）。

★ 为什么要有这一道：现在的回路是
  `改上游 → export_contours（秒）→ 跑 SU 建面（11.6~22.3 s）→ 导出 OBJ/DAE（1~2 分钟）
   → -02 量 OBJ → 发现零长边/洞没抠 → 回上游改`，**一次往返 3 分钟起步**；
  而输入里的各类缺陷**有五类会让 SU 挂死或静默丢件**—— 实测挂死两次：
  一次 `rc=127`（一次塞 8570 张面）、一次 CPU 满转窗口无响应
  （`??层_DOOR 60/3xx`、`cpu_delta_6s=6.44`、`resp=False`、`ws=643.6MB`）。挂死连日志都读不全。
  上面那套检查**只依赖 JSON 自己** ⇒ 纯 Python、无 SU、无导出、**秒级**、且能点出**哪一层哪一条**。
  契约见 `rebuild/06_su/SU对CAD的数据要求.md`（SU 侧向上游提的要求，逐条带实测出处）。

★★ **三个同名的量，先分清再读文件**（铁律 174；2026-10-15 当场核过）：
    · `contours/<层名>.json` 的 `polys` 是**列表**（每条一个记录：`layer/z/ring/holes/id`，`h` 可选）；
    · `contours/index.json` 的 `polys` 是**条数**（int）；同一份 index 里的 `holes` 是**抠掉的洞数**，
      **不是**还留着的洞 —— 与记录级的 `holes` 不是一回事（本闸判的是后者「恒为空表」）；
    · `index.json::reopen_dxf` 是 `export_contours` **自己的自报值**；本闸 ⑮ 要**现在重读**一遍。

判据（①~⑯ 全部按 **SU 自己的口径**，不按「另一个库说得对不对」）：
  ① 十二份 `<层名>.json` + `index.json` 齐；缺 ⇒ **SKIP**（「没量到」不算过、也不假报红 —— 铁律 199）。
  ② 文件头与**两份件同源**：`units == "mm"`；`z0_m`/`h_m`/`push_mm`/条数/逐类条数 与 `index.json` 一致。
     ★ 实测：DXF 声明 `$INSUNITS=6`（米）而坐标是 mm ⇒ SU **认声明**，130.7 m 的平面导成 130700 m。
     ★ index 是**另跑一遍**写的自报表 ⇒ 上游改了、index 没重写，这一条就会红（那是真问题）。
  ③ 每条 `layer` ∈ 十一类枚举（2026-10-15 加 `LINTEL` 门头墙 九→十；同日晚加 `ROOF`
     塔楼屋面板 十→十一 —— 用户「楼板要画」）。
  ④ 每条 `z` 有限、且 ∈ `[0, h_m*1000 + 1]`（**相对本层底面**）。
     ★ 2026-10-19：`ROOF_ROOM` **例外**（+ 房间高）—— 屋面附属用房长在屋顶之上，
       见 `roof_room_z_extra_mm` 的说明；其余类照旧。
     ★ 实测：附属件写成**绝对**标高 ⇒ 女儿墙 84000 mm、总高从 50.5 变成 **90.5 m**（两个原点相加）。
  ⑤ `h` 只许出现在 `H_CLASSES`（逐块高度不同的那几类，当前只有 `STAIR`）；若出现必须有限且 > 0。
     ★ 实测：「楼梯直接建模块替换」后每级要从**自己的**底标高长到**自己那一级**；
       其余各类写了 `h` 就会盖掉按层常数，形制会变。
  ⑥ 每条 `holes` **恒为空表**。★ 实测：12 层 × 每一类包内足迹**逐位等于 gross**（洞一个没抠，
     `1层 WALL 5762.8 / 5652.5 / 5762.8`）；SU 侧三条抠洞路**全不通**（多环抛 `Not enough edges`
     / `add_edges` 抛 `ArgumentError` / 先画洞边再成面 = 实心 4.00 m² 对照 3.00）。
     `3层 COL 69.0 / 69.0 / 69.0` 是无洞类的反证（COL 本来就对）。
  ⑦ 环上**每个数**都 `isfinite`（铁律 123：`Infinity`/`NaN` 落盘后浏览器 `JSON.parse` 抛错 ⇒ 白屏）。
  ⑧ 去掉收口点之后，**相邻两点互异**，且不再出现首点。
     ★ 实测：`round(…, 1)`（0.1 mm）把两个不同的坐标圆成同一个数 ⇒ SU 建不出长度 0 的边
       ⇒ **静默少一张面**（`FACES built=4 fail=1`）；零长边还会让 SU **自旋**
       （6层 DOOR 第 6 个组转死，CPU ~93%、窗口无响应）。
     ★ 上游 `export_contours._dedup` **故意保留收口点**（首点会在末尾再出现一次，那是正常收口）
       ⇒ 判据必须先剥收口点再判相邻，**不许把合法的收口报成重复点**。
  ⑨ **SU 口径**下 ≥3 个互异点（照抄 `su_step2_build.rb::clean_ring`，不照抄 JSON 里的列表长度）。
     ★ 「环长」有两个同名的量（JSON 列表长度 / SU 洗完之后的点数），这里只认后者（铁律 174）。
     ★ 实测：`face_of()` 里 `rr.length < 3` 直接 `fail += 1`，那是**有计数的**，但要跑完 SU 才知道。
  ⑩ 环不自交（简单多边形）。★ 成不了面 / 出歪面。
  ⑪ 最短边 ≥ `EDGE_MIN_MM`、面积 ≥ `AREA_MIN_MM2`。
     ★ **阈值来源是实测不是拍的**：`rebuild/_scratch/probe_contract.py` 量了**全部环**
       （条数不在这里写死 —— 判词里印**现算**的那个，见 ⑭ 那一行）：
       最短边 **12.0000 mm**、最小面积 **1250.000 mm²**、1 分位边长 **25.00 mm**（= `RES`）。
     ★ SU 侧自己的容差是 **0.001 英寸 ≈ 0.0254 mm**（官方只承认 `Length#==` 有容差，
       数值是社区共识；比本闸的 6.25 mm 小 246 倍）⇒ 本闸卡的是「半个栅格像元」，
       不是「SU 的容差」，两道尺子量的是不同的事。
       取 `RES/4 = 6.25` 与 `RES²/4 = 156.25`（落在实测最小值之下 2 倍 / 8 倍）⇒ 不假红，
       但把「小于半个栅格像元」的东西挡在门外。★ 这两个常数与实测读数**绑在一起改**（见盲区）。
     ★★ **那个「实测最短边 12.0000 mm」已经不代表现在这一批环了**（2026-10-16 实测）：
       它早于 `LINTEL` 门头墙（2026-10-15 才加进枚举）⇒ 现在的全局最短边是 1 层两条
       `LINTEL` 的 **4.200 / 1.500 mm**。这不动摇 6.25 这条线本身（它是按 `RES` 推出来的，
       不是拿 12.0 推的），但**引 12.0 当依据就是引一个过期的观察**（铁律 018/174）。
       ⇒ 现读的对照见 `main()` 的**证据段**：本闸量的 ⑪ 条数 / 出件方自报的 `收边没治好` 条数，
         两个来源并列（**只报不判**；已知残差与其处置写在盲区）。
  ⑫ 同一 `(层, 类, z)` 内多边形**互不重叠**（共面 ⇒ 在 SU 里会互相切面，切出的碎面导出后不成组）。
     ★ 2026-10-19：分组由 `(层, 类)` 改成 `(层, 类, z)` —— `ROOF_ROOM` 的墙(z=屋顶面)
       与顶板(z=屋顶面+房间高) 投影必然重合，但**不在同一平面**，不是共面。
  ⑬ 每层 `COL` 条数 == 该层源图**柱的条数**：`_FZHK`/`_YZHK` 块 `INSERT` 数与
     **柱层（档案认定，退回「图层名含柱或以 COL 开头」）上 ≥3 点的 `LWPOLYLINE`** 数，**取多者**
     （与识别侧 `redraw.COL_MODE="auto"` 同一条规则）。
     ★★ 2026-10-19：原口径只数 `INSERT`。c079 的柱全画成**闭合多段线**
       （1839 条 / 0 个块）⇒ 参照恒 0、判词恒红，而件是对的 —— 那是量具的错
       （铁律 158：否定判词要先声明尺子对哪类元素不盲）。
     ★★ 这是本闸**唯一的件外独立参照**（`01_cad/raw/<层名>.dxf`），而且**入口这侧有真实层名**
       ⇒ 不用 `-02` 那套「有损层键求交」，一条等式即可。
       实测（2026-10-15）：**12/12 层相等**（1层 201/201、7层 30/30、地下1层 44/44 …）。
       ⇒ 它能在**跑 SU 之前**抓住「柱/墙认错了、漏建了」（用户报的「部分墙体缺失」那一类）。
  ⑭ 规模（**只报不判**）：一层条数上限对照实测的 `rc=127`（一次 8570 张面崩、4422 稳）。
  ⑮ 逐层 DXF **现在重读**，数闭合 `LWPOLYLINE` == JSON 条数
     （`export_contours` 复核① 的**常驻版**；与 index 里的 `reopen_dxf` 自报值不是一回事）。
     ★ **声明弱点**：两份件是**同一段代码**写的 ⇒ 只抓「写出过程丢件/截断」，抓不到「判断本身错」。
  ⑯ 本闸自己的阈值 `EDGE_MIN_MM` 与 `参数.json::共用/环_最短边下限` **现读现比**，不等即红；
     参数表读不到时报「没量到」，**不报成功**（铁律 018：一个数两处写，一致证明不了它对）。

量具：① `json` 读 `rebuild/06_su/contours/*.json` + `index.json`；② `ezdxf` 读
  `rebuild/01_cad/raw/*.dxf`（**只用柱块 INSERT 数**）与 `contours/*.dxf`（数闭合环）；
  ③ `shapely` 判自交与重叠。**一律现算，不读 `build.json`、不读 SU 的任何产物。**
量具盲区（声明）：
  · **量不到「SU 建得对不对」**：单位、朝上轴、逐层层带、顶部三件标高、导出朝向 —— 全在 `-02`。
  · **量不到「判断本身对不对」**：墙认错了没有、楼梯井归并对不对、门位置准不准。
    ⑬ 只覆盖**柱**这一类的**条数**（不是位置）。
  · **门**：源件 `$DorLib2D$` 按**块**、这里按**环** ⇒ 两把尺子不同源，**只打印不判**（同 `-02`）。
  · `EDGE_MIN_MM`/`AREA_MIN_MM2` 的来源是**本仓当前这一份数据**的分布；上游若合法地产生更小的件，
    这两个常数要**连着读数一起改**，不许只改常数。
  · ⑮ 的 JSON 与 DXF 同源 ⇒ 见上（同段代码写出的两份件互相印证不了判断本身）。
  · ② 比的是**同一段代码**写的两份自报表 ⇒ 抓「index 过期」，抓不到「两份一起错」。
正对照（必配，与 `-02` 同法：与 C1 基线**做差**，只看**这一条新添的**违反里有没有那个 marker —— 铁律 183）：
  · C1 真件 ⇒ 放行；
  · C2 插一个连续重复点 ⇒ ⑧；· C3 砍成 2 个互异点 ⇒ ⑨；· C4 `z` 越界 ⇒ ④；
  · C5 给非 STAIR 塞 `h` ⇒ ⑤；· C6 塞一个假洞 ⇒ ⑥；· C7 做成 8 字自交 ⇒ ⑩；
  · C8 缩成 1 mm² ⇒ ⑪；· C9 某层 COL 减一条 ⇒ ⑬；· C10 复制一条同类多边形 ⇒ ⑫；
  · C11 一个坐标写成 `nan` ⇒ ⑦；· C12 `units` 改成 `"m"` ⇒ ②；· C13 `layer` 改成 `"WAL"` ⇒ ③。
  十三条里任一条不按预期 ⇒ 判据没分辨力，作废。
三态：OK（rc=0） / FAIL（rc=1） / SKIP（rc=4）。
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = r"D:\项目\cdut3d"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _verdict as VD                                            # noqa: E402
import _items as I                                               # noqa: E402

# ★ 2026-10-19（用户「错误要能在页面上指出来」）：路径**只从** `_verdict.paths()` 来 ——
#   原来这里把 c006 的绝对路径写死，别的楼根本量不了。`--bid X` / `CDUT_BUILDING` / 默认 c006。
BID = VD.bid_from()
_P = VD.paths(BID)
SU = os.path.join(_P["root"], "06_su")
CONT = _P["contours"]
IDX = _P["index"]
RAW = _P["raw"]
PARAM = _P["params"]
DUIBI = _P["duibi"]
RUNDIR = os.path.join(HERE, "_out")
JSON_OUT = os.path.join(RUNDIR, "J-10.8-00.%s.json" % BID)
_LOG = []
_MEAS = {}

LAYERS = ("WALL", "COL", "LIFT", "SLAB", "DOOR", "STAIR", "LINTEL",
          "PARAPET", "ROOF_STAIR", "ROOF_STEP", "ROOF",
          # ★ 2026-10-18 加 `ROOF_ROOM`（屋面附属用房 = 出屋面楼梯间 + 电梯机房），
          #   理由：用户令「楼梯间和电梯房一块儿做」⇒ 顶部两件从实心盒改成
          #   **环带墙 + 顶板 + 门洞缺口**，两段高度不同、必须逐块带 `h`。
          "ROOF_ROOM")
# ★ 2026-10-15 加 `ROOF`（塔楼屋面板，十→十一）：`build3d.py:957` 早就建了它，
#   但 `export_contours.py` 的枚举里没有 ⇒ 它一直没被发出去、正式件顶上 911 m² 是空的
#   （用户「楼板要画」）。这条判据是**进 SU 之前的接口门**，枚举不跟着长，
#   下游按类全失效且**不报错**（铁律 158）。
# 逐块高度不同的类 —— 只有它们可以带 `h`。**这是声明**：上游若合法地需要别的类逐块拉伸，
# 连同理由一起加进来，不许默默放宽成「带了就带了」。
# ★ 2026-10-15 加 `LINTEL`（门头墙），理由：它的 `h = 层高 − 门洞高`、底面恒在门洞高上，
#   逐块由 `parts_lib.lintel_module` 算出来带着走 —— 与 `STAIR` 同型（不是放宽，是同一种件）。
H_CLASSES = ("STAIR", "LINTEL", "ROOF_ROOM")
# ★ 2026-10-19：层名表从**这栋楼的档案**现取（原来写死「地下1层 + 1..11 层」，
#   别的楼会去要 12 份不存在的文件 ⇒ 全红，而真原因是「尺子量错了楼」）。
FLOORS = VD.floors(BID)
COL_BLOCKS = ("_FZHK", "_YZHK")
# ★★ 2026-10-19（c079 诊断）：柱在源图里有**两种画法**——块 INSERT，或**多段线**。
#   c079 实测：`4.1结构柱` 上 **305 条 LWPOLYLINE（全部 closed=False、8 点交叉矩形）、
#   0 个 INSERT**；识别侧（`redraw.cols_lwpolyline`）收的是「柱层上 ≥3 点的所有多段线」。
#   而 ⑬ 只数 INSERT ⇒ 参照恒为 0，判词「COL 条数 ≠ 源图柱块数」是**量具错**不是件错
#   （铁律 158：否定判词必须先声明尺子对哪类元素不盲）。
COL_LAYER_HINTS = ("柱",)          # 图层名含「柱」即算柱层（如 `4.1结构柱`）
COL_LAYER_PREFIX = "COL"           # 或图层名以 COL 开头
DOOR_BLOCK = "$DORLIB2D$"

RES_MM = 25.0                        # 与 recognize.py::RES 同源（栅格分辨率）
EDGE_MIN_MM = RES_MM / 4.0           # 6.25   —— 实测最短边 12.0000 mm
AREA_MIN_MM2 = RES_MM * RES_MM / 4.0     # 156.25 —— 实测最小面积 1250.000 mm²
Z_SLOP_MM = 1.0                      # 只兜浮点尾数，不放宽「相对/绝对」这条
OVERLAP_EPS_MM2 = 1.0                # 万分之一平米；比它小的重叠算浮点噪声
# ④ `ROOF_ROOM` 的层高之外上界（mm）。`[None]` = 还没读；读到 None = 参数表读不到。
# 用单元素列表当缓存只为**只读一次盘**、且读不到时不伪装成 0（铁律 199）。
_RR_EXTRA_MM = [None]

BLIND = [
    "量不到「SU 建得对不对」（单位/朝上轴/逐层层带/顶部三件标高/导出朝向）——那是 J-10.8-02 的事",
    "量不到「判断本身对不对」：墙认错了没有、楼梯井归并对不对、门位置准不准；"
    "⑬ 只覆盖柱这一类的**条数**（不是位置）",
    "门：源件 $DorLib2D$ 按块、这里按环 ⇒ 两把尺子不同源，只打印不判",
    "EDGE_MIN_MM / AREA_MIN_MM2 的来源是本仓当前这份数据的分布；上游若合法地产生更小的件，"
    "两个常数要连着读数一起改，不许只改常数",
    "⑮ 的 JSON 与 DXF 是同一段代码写的 ⇒ 只抓写出过程丢件，抓不到判断本身错",
    "② 比的是同一段代码写的两份自报表 ⇒ 抓 index 过期，抓不到两份一起错",
    "⑪ 有**已知残差**（2026-10-16 用户裁定「就这样留着」）：1层 2 条 LINTEL 环最短边 4.200 / 1.500 mm "
    "< 6.25 —— 这是 `parts_lib.lintel_module` **自己已经声明**的（`对照.json::构件[].收边没治好` = 2），"
    "不是本闸量出来的新东西 ⇒ 本闸**故意维持红**：不白名单化、不动阈值、不拿「生成器已声明」去消项"
    "（铁律 137：名单一漏主体就永远绿）。证据段只把两条读数**并列**印出来",
]


class Missing(Exception):
    """「没量到」—— 转 SKIP，不算过、也不假报红（铁律 199）。"""


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    _LOG.append(s)


# ------------------------------------------------------------------ 量具

def _insert_names(path, prefixes):
    """数 `<path>` 里 `INSERT` 名以 `prefixes` 开头的条数。读不到 ⇒ `None`（**不填 0**）。"""
    import ezdxf
    if not os.path.exists(path):
        return None
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:                                            # noqa: BLE001
        log("  ★ 源图读不开：%s（%s）" % (path, e))
        return None
    return sum(1 for e in doc.modelspace()
               if e.dxftype() == "INSERT"
               and str(e.dxf.name).upper().startswith(prefixes))


def _is_col_layer(name):
    s = str(name or "").upper()
    return any(h.upper() in s for h in COL_LAYER_HINTS) or s.startswith(COL_LAYER_PREFIX)


def _col_layer_name():
    """楼栋档案认定的柱层名（与识别侧 `redraw.COL_LAYER` 同一来源）；认不到 ⇒ None。

    ★ 只在 `building.BID` 与本次 `BID` 一致时采信 —— 不一致说明有人没设
      `CDUT_BUILDING` 就用了 `--bid`，那时档案层名会指向**另一栋楼**，宁可退回启发式。
    """
    try:
        import building as _B
        if _B.BID == BID:
            return _B.layer("column", None)
    except Exception:                                       # noqa: BLE001
        pass
    return None


def _col_marks(path):
    """→ `(块 INSERT 数, 柱层多段线数)`；读不到 ⇒ `None`（**不填 0**）。

    ★ 两种画法都数、**取多者**（`src_col_counts`）—— 与识别侧 `redraw.COL_MODE="auto"`
      同一条规则。只数一种就是拿「另一种画法」当参照，恒不等（见上方常量注释）。
    ★★ 2026-10-19 二次修：**不能只数 `closed=True`**。c079 实测柱层上 305 条多段线
      **全部 `closed=False`**（8 个点：矩形画两遍、正反交叉），而 `redraw.cols_lwpolyline`
      收的是「该层上 ≥3 个点的**所有**多段线」并当闭合处理。尺子若比识别侧严一档，
      参照就是 0、判词恒红（这正是第一版修完仍红 6 条的原因）。
      ⇒ 判据与识别**同一档**：柱层 + 点数 ≥ 3，**不看 `closed`**。
    """
    import ezdxf
    if not os.path.exists(path):
        return None
    try:
        doc = ezdxf.readfile(path)
    except Exception:                                       # noqa: BLE001
        return None
    msp = doc.modelspace()
    ply = [e for e in msp if e.dxftype() == "LWPOLYLINE"]
    want = _col_layer_name()
    names = {e.dxf.layer for e in ply}
    cols = {want} if (want and want in names) else {n for n in names if _is_col_layer(n)}
    # ★ 2026-10-21：源图里同位置重复画两遍的柱不是两根柱。
    #   ⑬ 比的是“唯一柱位”与模型唯一柱件；之前数的是实体条数，
    #   生成器一旦去掉重复环，计数就假性少 4 根。
    wall_names = set()
    try:
        wl = _B.layer("wall", None)
        if wl:
            wall_names.add(str(wl))
    except Exception:                                       # noqa: BLE001
        pass
    if not wall_names:
        wall_names = {n for n in names if "墙" in str(n) or "WALL" in str(n).upper()}
    ins_keys, ins_pts, pl_keys, circ_keys = set(), [], set(), set()
    for e in msp:
        if e.dxftype() == "INSERT" and str(e.dxf.name).upper().startswith(COL_BLOCKS):
            p = e.dxf.insert
            ins_pts.append((float(p.x), float(p.y)))
            ins_keys.add((str(e.dxf.name).upper(),
                          round(float(p.x), 1), round(float(p.y), 1)))
        elif e.dxftype() == "LWPOLYLINE" and e.dxf.layer in cols:
            pts = [(round(float(x), 1), round(float(y), 1))
                   for x, y in e.get_points("xy")]
            if len(pts) >= 3:
                pl_keys.add(tuple(sorted(pts)))
        elif (e.dxftype() == "CIRCLE" and e.dxf.layer in wall_names
              and 100.0 <= float(e.dxf.radius) <= 1000.0):
            p = e.dxf.center
            circ_keys.add((round(float(p.x), 1), round(float(p.y), 1),
                           round(float(e.dxf.radius), 1)))
    n_circ = sum(
        1 for x, y, _r in circ_keys
        if not any((x - ix) ** 2 + (y - iy) ** 2 <= 500.0 ** 2
                   for ix, iy in ins_pts)
    )
    return len(ins_keys), len(pl_keys), n_circ


def src_col_counts():
    """源图逐层柱数（⑬ 的**件外参照**）：`INSERT` 与柱层闭合多段线**取多者**。"""
    out, detail = {}, {}
    for fl in FLOORS:
        mk = _col_marks(os.path.join(RAW, fl + ".dxf"))
        if mk is None:
            out[fl] = None
        else:
            out[fl], detail[fl] = max(mk[0], mk[1]) + mk[2], mk
    SRC_COL_DETAIL.clear()
    SRC_COL_DETAIL.update(detail)
    return out


SRC_COL_DETAIL = {}


def src_door_total():
    """源图门块总数（**只打印不判**：源件按块、这里按环，两把尺子不同源）。"""
    return sum(v for v in (_insert_names(os.path.join(RAW, fl + ".dxf"), DOOR_BLOCK)
                           for fl in FLOORS) if v)


def dxf_ring_counts():
    """`contours/<层>.dxf` 里**闭合** `LWPOLYLINE` 的条数，按图层分（⑮）。"""
    import ezdxf
    out = {}
    for fl in FLOORS:
        p = os.path.join(CONT, fl + ".dxf")
        if not os.path.exists(p):
            out[fl] = None
            continue
        try:
            doc = ezdxf.readfile(p)
        except Exception as e:                                        # noqa: BLE001
            log("  ★ contours DXF 读不开：%s（%s）" % (p, e))
            out[fl] = None
            continue
        by = {}
        for e in doc.modelspace():
            if e.dxftype() == "LWPOLYLINE" and e.closed:
                by[e.dxf.layer] = by.get(e.dxf.layer, 0) + 1
        out[fl] = by
    return out


def clean_ring(ring):
    """**SU 的口径** —— 照抄 `su_step2_build.rb::clean_ring`（去相邻重复 + 弹掉收口点）。

    ★ 必须照抄，不许自己发明：判据要和**被测的那一段程序**用同一个口径
      （铁律 158 的另一面 —— 尺子的口径必须与被测同源，否则红绿都不是被测的事）。
    """
    rr = []
    for p in ring:
        if not rr or rr[-1] != p:
            rr.append(p)
    while len(rr) > 1 and rr[0] == rr[-1]:
        rr.pop()
    return rr


def ring_area(pts):
    """鞋带公式取绝对值。`pts` = 不含收口点的互异点列（≥3 点）。"""
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1]
                   - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))) / 2.0


def load():
    """十二份件 + index。缺一份 ⇒ `Missing`（调用方转 SKIP）。"""
    if not os.path.isdir(CONT):
        raise Missing("contours 目录不在：%s" % CONT)
    data, missing = {}, []
    for fl in FLOORS:
        p = os.path.join(CONT, fl + ".json")
        if not os.path.exists(p):
            missing.append(fl)
            continue
        with open(p, encoding="utf-8") as f:
            data[fl] = json.load(f)
    if missing:
        raise Missing("缺 %d 份楼层件：%s" % (len(missing), missing))
    if not os.path.exists(IDX):
        raise Missing("index.json 不在：%s" % IDX)
    with open(IDX, encoding="utf-8") as f:
        data["_index"] = json.load(f)
    return data


# ------------------------------------------------------------------ 判

def _head_bad(fl, d, r):
    """② —— 文件头 + 与 `index.json` 自报表对账（index 是**另跑一遍**写的 ⇒ 会过期）。"""
    out = []
    if d.get("units") != "mm":
        out.append('② %s 的 `units` 是 %r，必须是 "mm"（SU 认声明 ⇒ 大 1000 倍不报错）'
                   % (fl, d.get("units")))
    pm = d.get("push_mm") or {}
    lack = [k for k in LAYERS if k not in pm]
    if lack:
        out.append("② %s 的 `push_mm` 少了 %s" % (fl, lack))
    if r is None:
        out.append("② index.json 里没有 %s 这一行" % fl)
        return out
    for k in ("z0_m", "h_m"):
        if float(r[k]) != float(d[k]):
            out.append("② %s 的 `%s` index=%r 而件里=%r（两份件不同源）" % (fl, k, r[k], d[k]))
    if int(r.get("polys", -1)) != len(d["polys"]):
        out.append("② %s 的条数 index=%s 而件里=%d（★ index 是旧的自报表）"
                   % (fl, r.get("polys"), len(d["polys"])))
    if (r.get("push_mm") or {}) != pm:
        out.append("② %s 的 `push_mm` 与 index 不一致：件 %s / index %s"
                   % (fl, pm, r.get("push_mm")))
    live = {}
    for pr in d["polys"]:
        live[pr.get("layer")] = live.get(pr.get("layer"), 0) + 1
    idx_live = {k: v for k, v in (r.get("per_layer") or {}).items() if v}
    if idx_live != live:
        out.append("② %s 的逐类条数 件 %s ≠ index %s（★ index 是旧的自报表）"
                   % (fl, sorted(live.items()), sorted(idx_live.items())))
    return out


_RULES = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧",
          "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮", "⑯")


def _scan(data, src_col, dxf_by, meas=None):
    """共用前置：把 ②–⑮ 的违反**按规则号分桶**，并按原顺序记一份 `ordered`。

    ★ 这一层只负责「量」：阈值、环闭合/自交/面积、`continue` 的分支**逐行照旧**。
      每条判据函数只从桶里取自己那一号 ⇒ 两处不各算一遍（铁律 018/174）。
    ★ 原来 `judge()` 的对外行为（返回违反串列表）由 `judge()` 从 `ordered` 原样交出。
    """
    ordered = []
    buckets = {r: [] for r in _RULES}

    def add(s):
        ordered.append(s)
        buckets[s[0]].append(s)

    idx_by = {r.get("floor"): r for r in data["_index"]}

    for fl in FLOORS:                                                  # ②
        for s in _head_bad(fl, data[fl], idx_by.get(fl)):
            add(s)

    n_poly, e_min, a_min = 0, [], []
    per_floor_n = {}
    for fl in FLOORS:
        d = data[fl]
        h_mm = float(d["h_m"]) * 1000.0
        per_cls, col_n = {}, 0
        per_floor_n[fl] = len(d["polys"])
        for pr in d["polys"]:
            n_poly += 1
            pid = pr.get("id") or "?"
            lay = pr.get("layer")
            if lay not in LAYERS:                                     # ③
                add("③ %s/%s 的 layer=%r 不在十一类枚举里" % (fl, pid, lay))
                continue
            per_cls[lay] = per_cls.get(lay, 0) + 1

            z = pr.get("z")                                            # ④
            z_hi = h_mm + Z_SLOP_MM
            if lay == "ROOF_ROOM":
                # 屋面附属用房**长在屋顶之上**：z 基准是 h_m，可以再高出房间高。
                _ex = _RR_EXTRA_MM[0]
                if _ex is None:              # 参数表读不到 ⇒ 只算一次，按原界判（不静默放宽）
                    _ex = roof_room_z_extra_mm()
                    _RR_EXTRA_MM[0] = _ex
                if _ex is not None:
                    z_hi += _ex
            if not isinstance(z, (int, float)) or not math.isfinite(float(z)):
                add("④ %s/%s 的 z=%r 不是有限数" % (fl, pid, z))
            elif not (-Z_SLOP_MM <= float(z) <= z_hi):
                add("④ %s/%s 的 z=%.1f mm 不在 [0, %.1f] —— 十有八九把**绝对**标高写进来了"
                    "（两个原点相加，实测总高 50.5 → 90.5 m）" % (fl, pid, float(z), z_hi))

            if pr.get("h") is not None:                                # ⑤
                hv = pr["h"]
                if lay not in H_CLASSES:
                    add("⑤ %s/%s 的 layer=%s 带了 `h=%r` —— 只有 %s 可以逐块给高度，"
                        "其余各类带了就会盖掉按层常数"
                        % (fl, pid, lay, hv, list(H_CLASSES)))
                elif not isinstance(hv, (int, float)) or not math.isfinite(float(hv)) \
                        or float(hv) <= 0:
                    add("⑤ %s/%s 的 h=%r 不是有限正数" % (fl, pid, hv))

            if pr.get("holes"):                                        # ⑥
                add("⑥ %s/%s 带了 %d 个洞 —— SU 侧抠洞三条路全不通，洞必须在 Python 侧切掉"
                    % (fl, pid, len(pr["holes"])))

            ring = pr.get("ring") or []
            if any(not isinstance(c, (int, float)) or not math.isfinite(float(c))
                   for p in ring for c in p):                          # ⑦
                add("⑦ %s/%s 的环上有非有限数（nan/inf 落盘后浏览器 JSON.parse 抛错 ⇒ 白屏）"
                    % (fl, pid))
                continue

            body = [tuple(float(c) for c in p) for p in ring]           # ⑧
            while len(body) > 1 and body[0] == body[-1]:
                body.pop()          # 上游有意保留的**收口点**，先剥掉再判，不许报成重复点
            dup = [i for i in range(len(body) - 1) if body[i] == body[i + 1]]
            if dup:
                add("⑧ %s/%s 的环上有 %d 处相邻重复点（第一处在下标 %d）—— "
                    "SU 建不出长度 0 的边 ⇒ 静默少一张面 / 甚至自旋挂死"
                    % (fl, pid, len(dup), dup[0]))
            if len(body) != len(set(body)):
                add("⑧ %s/%s 的环上有**非相邻**重复点（%d 个点只有 %d 个互异）"
                    % (fl, pid, len(body), len(set(body))))

            rr = clean_ring(body)                                      # ⑨ = SU 口径
            if len(rr) < 3:
                add("⑨ %s/%s 按 SU 口径只剩 %d 个互异点（<3 建不出面）" % (fl, pid, len(rr)))
                continue
            try:
                from shapely.geometry import LinearRing                # ⑩
                if not LinearRing(rr + [rr[0]]).is_simple:
                    add("⑩ %s/%s 的环自交（8 字/蝴蝶结），SU 成不了面或出歪面" % (fl, pid))
            except Exception as e:                                     # noqa: BLE001
                add("⑩ %s/%s 判自交时抛异常：%s" % (fl, pid, e))
            ar = ring_area(rr)                                         # ⑪
            a_min.append(ar)
            if ar < AREA_MIN_MM2:
                add("⑪ %s/%s 的环面积 %.3f mm² < %.2f（阈值 = RES²/4；实测最小 1250.000）"
                    % (fl, pid, ar, AREA_MIN_MM2))
            em = min(math.hypot(rr[(i + 1) % len(rr)][0] - rr[i][0],
                                rr[(i + 1) % len(rr)][1] - rr[i][1]) for i in range(len(rr)))
            e_min.append(em)
            if em < EDGE_MIN_MM:
                add("⑪ %s/%s 的最短边 %.3f mm < %.2f（阈值 = RES/4，不是拿某个实测值推的；"
                    "docstring ⑪ 里那个「实测最短 12.0000」早于 LINTEL 类，别再引它当依据）"
                    % (fl, pid, em, EDGE_MIN_MM))
            if lay == "COL":
                col_n += 1

        for s in _overlap_bad(fl, d["polys"]):                         # ⑫
            add(s)

        s = src_col.get(fl)                                            # ⑬
        if s is None:
            add("⑬ %s 的源图柱块数**没量到**（源图不在或读不开）—— 不许当成相等" % fl)
        elif col_n != s:
            _d = SRC_COL_DETAIL.get(fl)
            add("⑬ %s 的 COL 条数 %d ≠ 源图柱数 %d（差 %+d；源图 块 %s / 多段线 %s / 墙层圆 %s）"
                % (fl, col_n, s, col_n - s,
                   "?" if _d is None else _d[0], "?" if _d is None else _d[1],
                   "?" if _d is None else _d[2]))

        by = dxf_by.get(fl)                                            # ⑮
        want = {}
        for pr in d["polys"]:
            want[pr["layer"]] = want.get(pr["layer"], 0) + 1 + len(pr.get("holes") or [])
        if by is None:
            add("⑮ %s 的 contours/<层>.dxf 读不到（两份件本应同源）" % fl)
        elif by != want:
            add("⑮ %s 的 JSON 逐类 %s ≠ DXF 闭合环 %s（同一段代码写出的两份件不同源）"
                % (fl, sorted(want.items()), sorted(by.items())))

        log("  %-8s 条 %4d | 逐类 %s" % (fl, per_floor_n[fl],
                                         " ".join("%s%d" % (k, per_cls[k])
                                                  for k in LAYERS if per_cls.get(k))))

    if meas is not None:
        meas["floors"] = len(FLOORS)
        meas["polys"] = n_poly
        meas["max_per_floor"] = max(per_floor_n.values())
        meas["max_per_floor_which"] = max(per_floor_n, key=per_floor_n.get)
        # ★ 读数与常数一起落盘：改常数不看读数就是「两个地方写同一个数」（铁律 18/174）
        meas["edge_min_mm"] = round(min(e_min), 4) if e_min else None
        meas["area_min_mm2"] = round(min(a_min), 3) if a_min else None
        meas["EDGE_MIN_MM"] = EDGE_MIN_MM
        meas["AREA_MIN_MM2"] = AREA_MIN_MM2
        meas["col_ok_floors"] = sum(1 for fl in FLOORS
                                    if src_col.get(fl) is not None
                                    and src_col[fl] == sum(1 for p in data[fl]["polys"]
                                                           if p["layer"] == "COL"))
    return {"ordered": ordered, "buckets": buckets}


def judge(data, src_col, dxf_by, meas=None):
    """返回违反串列表（空 = 合格）。**只读 `data`**，件侧一个数都不落盘。

    ★ 对外签名**不变**（正对照 `ctl()` 与老调用者都还这么调）；真正的「量」在
      `_scan()` 里，本函数只把那一趟的 `ordered` 原样交出去 ⇒ 顺序与逐条文本都不变。
    """
    return list(_scan(data, src_col, dxf_by, meas)["ordered"])


def _overlap_bad(fl, polys, keep=20):
    """同一 `(层, 类)` 内任意两条环不许重叠。bbox 粗筛 + 精确求交。

    ★★ 这里曾经写 `cap=3` 并 `return` ⇒ 每层最多报 3 条。后果不是「日志短一点」，
       而是 **判词印出来的数是假的**：它印「违反 36 条」，读起来像真数，
       实际是 12 层 ×3 的**截断值**，真值 **1388 对**（差 **38 倍**，2026-10-15 实测）。
       量具分不开「正好 N」与「被截断」（铁律 197）⇒ 现在改成：
       **全量计数 `n`，只截断明细**，另出一条把**真数**写进判词的汇总行。
       判据的「有没有红」不受影响，但**读者能看出来的量级**变了。
    """
    from shapely.geometry import Polygon
    by = {}
    for pr in polys:
        # ★★ 2026-10-19：分组必须是 `(类, z)` —— **同平面**才谈得上互切。
        #   `ROOF_ROOM` 是「环带墙 z=4000 + 顶板 z=7000」两段，投影到平面上必然重合
        #   （顶板就盖在墙圈上）。原来只按类分组 ⇒ 5 对「墙-顶板」判成共面重叠，
        #   红得理直气壮却量错了平面（铁律 158）。
        by.setdefault((pr["layer"], round(float(pr.get("z") or 0.0), 3)), []).append(pr)
    out = []
    n = 0
    for (lay, zz), arr in by.items():
        rings = []
        for pr in arr:
            rr = clean_ring([tuple(float(c) for c in p) for p in pr["ring"]])
            if len(rr) < 3:
                continue
            xs = [p[0] for p in rr]
            ys = [p[1] for p in rr]
            rings.append((pr.get("id", "?"), rr, (min(xs), min(ys), max(xs), max(ys))))
        for i in range(len(rings)):
            for j in range(i + 1, len(rings)):
                a, b = rings[i][2], rings[j][2]
                if a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]:
                    continue
                try:
                    inter = Polygon(rings[i][1]).intersection(Polygon(rings[j][1])).area
                except Exception:                                     # noqa: BLE001
                    inter = 0.0
                if inter > OVERLAP_EPS_MM2:
                    n += 1
                    if len(out) < keep:
                        out.append("⑫ %s/%s 与 %s 重叠 %.3f mm²（同层同类**同 z=%.1f** 共面 ⇒ "
                                   "SU 里会互相切面）"
                                   % (fl, rings[i][0], rings[j][0], inter, zz))
    if n > keep:                       # ★ 只有真被截断了才出这行，而且数**是数出来的**
        # 前缀 `⑫Σ` 是给显示层认的：这一行**不受明细的 20 条上限约束**（见 main 里 C1 的打印）。
        # 它仍然以 `⑫` 开头 ⇒ 正对照按子串匹配 marker 照旧能中（C10 期望 `⑫`）。
        out.append("⑫Σ %s 同 (层,类) 内重叠**共 %d 对**（上面只列了前 %d 对）" % (fl, n, keep))
    return out


# ------------------------------------------------------------------ 正对照

def ctl(name, data, src_col, dxf_by, expect, base):
    """跑一条对照：**只看与 C1 基线的差**里有没有 `expect` 那些 marker（铁律 183）。"""
    fs = judge(data, src_col, dxf_by)
    new = [x for x in fs if x not in base]
    if not new:
        log("  %-30s → ★没动 ⇒ 这一条对这类坏数据没有分辨力" % name)
        return False
    hit = [x for x in new if any(e in x for e in expect)]
    if not hit:
        log("  %-30s → ★红了但理由不对（要 %s，实得 %s）"
            % (name, "/".join(expect), sorted({x.split()[0] for x in new})))
        return False
    log("  %-30s → ✔ %s（新增 %d 条）：%s" % (name, "/".join(expect), len(new), hit[0][:120]))
    return True


def _floor_for(data, lay=None):
    """正对照拿哪一层下手：**本楼真有的**第一个有 polys 的层（lay 给了就要求有该类）。

    ★ 2016-10-19（实为 2026-10-19）实测 c035/c036/c041：`_mut(..., fl="1层")` 写死 1 层，
      而这栋楼没有 `1层` ⇒ `KeyError: '1层'`，闸崩在落 verdict 之前，矩阵看到的是
      「闸没落 verdict」（铁律 199：崩了 ≠ 没量到 ≠ 通过；铁律 183：同一形状要一次改完）。
    """
    for fl in FLOORS:
        if fl not in data or not data[fl].get("polys"):
            continue
        if lay is None or any(p.get("layer") == lay for p in data[fl]["polys"]):
            return fl
    return None


def _mut(data, fn, fl=None, i=0):
    d = copy.deepcopy(data)
    fl = fl or _floor_for(d)
    if fl is None:
        raise RuntimeError("正对照无层可下手：本楼没有任何一层带 polys")
    fn(d[fl]["polys"][i], d[fl])
    return d


def _first_of(data, lay):
    """把**第一条** `lay` 类的记录挑出来改（找不到 ⇒ 返回 None，对照要报「没量到」）。"""
    for fl in FLOORS:
        for pr in data[fl]["polys"]:
            if pr["layer"] == lay:
                return fl, pr
    return None, None


def _set_h_on(d, lay, hv=50.0):
    """给某类**第一条**塞 `h`（就地改，返回是否改到了）。"""
    _fl, pr = _first_of(d, lay)
    if pr is None:
        return False
    pr["h"] = hv
    return True


def _drop_one_col(d, fl=None):
    """从某层删掉**最后一条** COL（就地改，返回是否删掉了）。"""
    fl = fl or _floor_for(d, "COL")
    if fl is None:
        return False
    idx = [i for i, p in enumerate(d[fl]["polys"]) if p["layer"] == "COL"]
    if not idx:
        return False
    d[fl]["polys"].pop(idx[-1])
    return True


def _add_fake_col(d, fl=None):
    """给某层塞一条假 COL；即使本楼没有 COL 也能验证 ⑬ 有分辨力。"""
    fl = fl or _floor_for(d)
    if fl is None:
        return False
    polys = d[fl].get("polys") or []
    src = next((p for p in polys if p.get("layer") == "WALL"), polys[0] if polys else None)
    if src is None:
        return False
    fake = copy.deepcopy(src)
    fake["layer"] = "COL"
    fake["id"] = "CTL-FAKE-COL"
    polys.append(fake)
    return True


def _bad_units(d, fl=None, v="m"):
    fl = fl or _floor_for(d)
    if fl is None:
        return False
    d[fl]["units"] = v
    return True


def _bowtie(pr, _d):
    """把环换成自交的「8 字」：对角连线交叉，面积不为 0 ⇒ 只该 ⑩ 红。"""
    xs = [p[0] for p in pr["ring"][:-1]]
    ys = [p[1] for p in pr["ring"][:-1]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pr["ring"] = [[x0, y0], [x1, y1], [x1, y0], [x0, y1], [x0, y0]]


def _tiny(pr, _d):
    """缩成 1 mm² 的小方块（最短边 1 mm、面积 1 mm²）⇒ 只该 ⑪ 红。"""
    x, y = pr["ring"][0]
    pr["ring"] = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]


def _copy_sibling(pr, d):
    """把环换成**同层同类**另一条的形状 ⇒ 两条完全重合 ⇒ 只该 ⑫ 红。"""
    # ★ 2026-10-19：⑫ 现在按 `(类, z)` 分组 ⇒ 对照也必须在**同一 z** 里挑兄弟，
    #   否则挑到别的平面上的块，⑫ 不会红，正对照会假装「判据没分辨力」。
    sib = [p for p in d["polys"]
           if p["layer"] == pr["layer"] and p is not pr and p.get("z") == pr.get("z")]
    if not sib:                    # 该平面只有一块 ⇒ 退回同类任意块（对照会报没红，看得见）
        sib = [p for p in d["polys"] if p["layer"] == pr["layer"] and p is not pr]
    if sib:
        pr["ring"] = [list(p) for p in sib[0]["ring"]]


def param_bad(edge=None, path=None):
    r"""⑯ 闸里自己的阈值必须与 `rebuild/构件库/参数.json` 里那一条**是同一个数**。

    ★ 为什么这条得是判据、不能只是一句注释（铁律 018「两个地方写同一个数，一致证明不了它是对的」）：
      `共用/环_最短边下限` 现在有**两个消费者** —— `parts_lib.heal_short_edges`（出件前收边）
      与本闸 ⑪（入口核）。两边各写一遍 6.25，会一直「看起来对」，直到有人只改一边：
        · 改闸不改库 ⇒ 出件仍按旧线收边、闸按新线判 ⇒ 红得莫名其妙（噪声，尚可忍）；
        · **改库不改闸 ⇒ 收得比判据松，闸恒绿**（真危险的方向，静默放行）。
      ⇒ 判据在这里**现读**参数表；不相等就报。参数表读不到时**报「没量到」**，
        不报成功（铁律 199：「崩了」与「没量到」不许同形）。
    """
    mine = EDGE_MIN_MM if edge is None else float(edge)
    src = PARAM if path is None else path
    try:
        with open(src, encoding="utf-8") as fh:
            v = json.load(fh)["构件"]["共用"]["环_最短边下限"]
    except Exception as e:                                             # noqa: BLE001
        return ["⑯ `参数.json` 的 `共用/环_最短边下限` **没量到**（%s: %s）——"
                "本闸的 %.2f 找不到真源可对，不许当它对" % (type(e).__name__, e, mine)]
    try:
        want = float(v["值"])
    except Exception as e:                                             # noqa: BLE001
        return ["⑯ `参数.json` 的 `共用/环_最短边下限` 读得出、但 `值` 取不出（%s）" % e]
    if abs(want - mine) > 1e-9:
        return ["⑯ 闸里 `EDGE_MIN_MM` = %.4f ≠ `参数.json::共用/环_最短边下限` = %.4f"
                "（相差 %.4f）—— 两处各写各的：收边与判据已经不是同一根线了"
                % (mine, want, mine - want)]
    return []


def roof_room_z_extra_mm(path=None):
    r"""④ 里 `ROOF_ROOM` 的**层高之外**上界：屋面附属用房长在屋顶之上。

    ★ 为什么不能拿层高卡它（2026-10-19 实测 c006）：11 层 `h_m = 4.0`，而附属用房的
      环带墙挂在 **屋顶面** `z = 4000`、顶板在 `z = 7000`（当时 = 4000 + 楼梯房高 3000；
      **2026-10-19 起全仓默认改 3500** ⇒ 重出的件是 `z = 7500`，两个数都得放行）。
      原判据只许 `z ∈ [0, h_m]` ⇒ 5 块顶板被判「写成绝对标高」，**是尺子量错了类**
      （铁律 158：否定判词先声明尺子对哪一类根本不适用）。
    ★ 数值与 `export_contours.py::_z_hi` **同源**：`参数.json::构件/顶部/楼梯房高`、
      `电梯机房高` 取大者（单位 mm）。读不到 ⇒ 返回 None，④ 按原界判（不静默放宽；
      且 ⑯ 也会因参数表读不到而红）。
    """
    src = PARAM if path is None else path
    try:
        with open(src, encoding="utf-8") as fh:
            lib = json.load(fh)["构件"]
        top = lib["顶部"]
        # ★★ 2026-10-19：与 `build3d.py` 同一口径 —— **按栋覆盖优先**
        #   （`构件/楼梯房高按栋/<栋id>`）。不读它 ⇒ c001 的附属用房顶板 3.5 m
        #   会被这条上界判成「写成绝对标高」，是尺子量错类（铁律 158/196）。
        _ovr = (((lib.get("楼梯房高按栋") or {}).get(BID) or {}).get("值"))
        _stair = float(_ovr) if _ovr is not None else float(top["楼梯房高"]["值"])
        return max(_stair, float(top["电梯机房高"]["值"]))
    except Exception:                                                   # noqa: BLE001
        return None


def declared_stub(path=None):
    r"""读**生成器自己声明的**「收边没治好」→ `(合计, [(层, 条数)…], {收边下限…})`。

    ★ 这是**另一个来源**，与本闸 ⑪ 量的东西**独立**：`parts_lib.lintel_module` 在出件前会
      `heal_short_edges` 把短于 `共用/环_最短边下限` 的边收掉，**收不掉的逐条计数**写进 `diag`
      （`parts_lib.py:668` 的 `"收边没治好"`），随 `rebuild/构件库/对照.json` 落盘。
      ⇒ 本闸 ⑪ 量的是**出件结果**、这里读的是**出件方的自报**，两把尺子两次读数（铁律 187）。

    ★ **只报不判，且绝不消项**：2026-10-16 用户裁定这 2 条**留着不修** ⇒ 本闸维持诚实红，
      这里印出来的东西只用来**说清红在哪、以及两条读数一不一致**。
      拿它去把 ⑪ 的违反抹掉，就等于「名字里漏掉主体 ⇒ 判据永远绿」（铁律 137）。

    ★ 读不到就返回 `(None, [], set())` —— **报「没量到」，不许当成 0**（铁律 199：
      「读不出来」与「一条都没有」不许同形）。
    """
    p = DUIBI if path is None else path
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:                                                  # noqa: BLE001
        return None, [], set()
    rows, tot, lo = [], 0, set()
    for c in d.get("构件") or []:
        if not isinstance(c, dict) or "收边没治好" not in c:
            continue
        n = int(c.get("收边没治好") or 0)
        tot += n
        if n:
            rows.append((c.get("层"), n))                              # 带上主语，免得只有总数
        if c.get("收边下限") is not None:
            lo.add(float(c["收边下限"]))
    return tot, rows, lo


# ---------------- 判据清单（一条一个函数，编号沿用 ①–⑯） ----------------
_GATE = "J-10.8-00"
_CTX = {}


def _ctx():
    """件 + 件外参照（**读盘一次**）。缺件 ⇒ `I.没量到`（转 SKIP，铁律 199）。"""
    if "data" in _CTX:
        return _CTX
    try:
        data = load()
    except Missing as e:
        raise I.没量到(str(e))
    _CTX.update(data=data, src_col=src_col_counts(), dxf_by=dxf_ring_counts())
    return _CTX


def _scan_ctx():
    """共用前置（②–⑮ 一次量完、按规则号分桶）。**只在第一条真正要量的判据里跑一次**。"""
    c = _ctx()
    if "scan" not in c:
        c["scan"] = _scan(c["data"], c["src_col"], c["dxf_by"], _MEAS)
    return c


def _vs(rule):
    """该规则号在这**同一趟**扫描里的违反串（不另算一遍 —— 铁律 018）。"""
    return _scan_ctx()["scan"]["buckets"][rule]


def _detail(vs, keep=20):
    """逐条明细照原格式打印；超过 `keep` 只折一行（不假报成「正好 N 条」—— 铁律 197）。"""
    for v in vs[:keep]:
        log("     - %s" % v)
    if len(vs) > keep:
        log("     …另有 %d 条（本规则共 %d 条）" % (len(vs) - keep, len(vs)))


def _say(vs, ok_text, keep=3):
    """一条判词：合格说 `ok_text`；红了把前几条理由带上，并写明**真数**。"""
    if not vs:
        return ok_text
    s = "；".join(vs[:keep])
    if len(vs) > keep:
        s += "；…共 %d 条" % len(vs)
    return s


def r01_件齐():
    _ctx()
    return I.结果(True, "%d 份 + index" % len(FLOORS),
                  "十二份 <层名>.json + index.json 齐（%s）" % BID,
                  参数=[I.参数(
                      "楼层件份数",
                      "%d 份 + index" % len(FLOORS),
                      "楼栋档案 building.py::profile(%s).floor_names + basement（VD.floors）"
                      " 与 contours/index.json" % BID,
                      "%d 份 + index" % len(FLOORS),
                      "补齐 contours/<层名>.json 与 contours/index.json 里缺的那一层后重跑本闸")])


def r02_文件头同源():
    vs = _vs("②")
    _detail(vs)
    n_units = sum(1 for v in vs if "`units`" in v)
    n_push = sum(1 for v in vs if "push_mm" in v)
    n_idx = len(vs) - n_units - n_push
    return I.结果(not vs, "%d 层同源" % len(FLOORS) if not vs else "%d 条" % len(vs),
                  _say(vs, "units==mm；z0_m / h_m / push_mm / 条数 / 逐类条数 与 index.json 一致"),
                  参数=[
                      I.参数("units", '"mm"',
                             "contours/<层名>.json::units（SU 认声明；DXF $INSUNITS 只是提示）",
                             "%d 层不符" % n_units,
                             "改 rebuild/tools/export_contours.py 的 units 写死为 \"mm\"（坐标已是 mm）"
                             "后重跑 export_contours 与本闸"),
                      I.参数("push_mm 覆盖", "%d 类全覆盖" % len(LAYERS),
                             "contours/<层名>.json::push_mm（键 = 闸内 LAYERS 全枚举）",
                             "%d 条缺/不符" % n_push,
                             "改 rebuild/tools/export_contours.py 补齐 push_mm 的类后"
                             "重跑 export_contours 与本闸"),
                      I.参数("与 index.json 同源", "z0_m / h_m / polys / per_layer 与件相同",
                             "contours/index.json::[floor].z0_m,h_m,polys,per_layer",
                             "%d 条不符" % n_idx,
                             "重跑 export_contours 让 index.json 跟着件重写，再重跑本闸"
                             "（index 是另跑一遍写的自报表，会过期）"),
                  ])


def r03_图层枚举():
    vs = _vs("③")
    _detail(vs)
    return I.结果(not vs, "0 条越界" if not vs else "%d 条" % len(vs),
                  _say(vs, "每条 layer ∈ 十一类枚举"),
                  参数=[I.参数(
                      "layer 取值域",
                      "%d 类枚举" % len(LAYERS),
                      "闸内常量 LAYERS（与 rebuild/tools/export_contours.py 发件的品类同源）",
                      "%d 条不在枚举内" % len(vs),
                      "改 rebuild/tools/export_contours.py 的 layer 映射后"
                      "重跑 export_contours 与本闸")])


def r04_z范围():
    vs = _vs("④")
    _detail(vs)
    _ex = roof_room_z_extra_mm()
    return I.结果(not vs, "0 条越界" if not vs else "%d 条" % len(vs),
                  _say(vs, "z 有限且 ∈ [0, h_m*1000 + 1]（ROOF_ROOM 另加房间高）"),
                  参数=[I.参数(
                      "z 允许区间",
                      "[0, h_m×1000 + %.1f]；ROOF_ROOM 再 + %s"
                      % (Z_SLOP_MM, ("%.0f" % _ex) if _ex is not None else "没读到"),
                      "contours/<层名>.json::h_m + 闸内常量 Z_SLOP_MM；ROOF_ROOM 加量来自"
                      " 参数.json::构件/顶部/楼梯房高|电梯机房高（按栋覆盖优先）",
                      "%d 条越界" % len(vs),
                      "改 rebuild/tools/export_contours.py 的 z 换算（必须是相对本层底面的 mm）"
                      "后重跑 export_contours 与本闸")])


def r05_h白名单():
    vs = _vs("⑤")
    _detail(vs)
    return I.结果(not vs, "0 条越界" if not vs else "%d 条" % len(vs),
                  _say(vs, "h 只许出现在 %s，且为有限正数" % (list(H_CLASSES),)),
                  参数=[I.参数(
                      "h 白名单",
                      "只许 %s" % (list(H_CLASSES),),
                      "闸内常量 H_CLASSES（与 export_contours.py / parts_lib 的逐块高度类同源）",
                      "%d 条越界" % len(vs),
                      "改 rebuild/tools/export_contours.py 的写入侧：非 H_CLASSES 的块不带 h；"
                      "确需逐块高度的类连同理由加进 H_CLASSES 后重跑 export_contours 与本闸")])


def r06_无洞():
    vs = _vs("⑥")
    _detail(vs)
    return I.结果(not vs, "0 条" if not vs else "%d 条" % len(vs),
                  _say(vs, "每条 holes 恒为空表"),
                  参数=[I.参数(
                      "holes",
                      "恒为空表（0 个洞）",
                      "rebuild/06_su/SU对CAD的数据要求.md（SU 侧三条抠洞路全不通，"
                      "洞必须在 Python 侧切掉）",
                      "%d 条带洞" % len(vs),
                      "改 rebuild/tools/export_contours.py / parts_lib.py 在 Python 侧把洞切掉后"
                      "重跑 export_contours 与本闸")])


def r07_环上有限数():
    vs = _vs("⑦")
    _detail(vs)
    return I.结果(not vs, "0 条" if not vs else "%d 条" % len(vs),
                  _say(vs, "环上每个数都 isfinite"),
                  参数=[I.参数(
                      "环上数值",
                      "全部 isfinite（无 nan/inf）",
                      "JSON 规范 + 铁律 123（Infinity/NaN 落盘后浏览器 JSON.parse 抛错 ⇒ 白屏）",
                      "%d 条带非有限数" % len(vs),
                      "改 rebuild/tools/export_contours.py 的坐标序列化（不可比的格写 null/剔除），"
                      "落盘后用另一语言解析器再读一遍，再重跑本闸")])


def r08_相邻互异():
    vs = _vs("⑧")
    _detail(vs)
    return I.结果(not vs, "0 条" if not vs else "%d 条" % len(vs),
                  _say(vs, "剥掉收口点后相邻两点互异，且不再出现首点"),
                  参数=[I.参数(
                      "相邻点互异",
                      "剥收口点后 0 处相邻重复、0 处非相邻重复",
                      "su_step2_build.rb::clean_ring 口径（收口点先剥掉，不许报成重复点）",
                      "%d 条违反" % len(vs),
                      "改 rebuild/tools/export_contours.py::_dedup 或上游识别"
                      "（别把不同坐标 round 成同一个数）后重跑 export_contours 与本闸")])


def r09_SU口径点数():
    vs = _vs("⑨")
    _detail(vs)
    return I.结果(not vs, "0 条" if not vs else "%d 条" % len(vs),
                  _say(vs, "按 SU 口径（clean_ring）≥3 个互异点"),
                  参数=[I.参数(
                      "SU 口径互异点数",
                      "≥ 3",
                      "su_step2_build.rb::clean_ring + face_of（rr.length < 3 ⇒ fail）",
                      "%d 条不足 3 点" % len(vs),
                      "改 rebuild/tools/export_contours.py / 识别侧，保证按 SU 口径 ≥3 个互异点后"
                      "重跑 export_contours 与本闸")])


def r10_不自交():
    vs = _vs("⑩")
    _detail(vs)
    return I.结果(not vs, "0 条" if not vs else "%d 条" % len(vs),
                  _say(vs, "环不自交（简单多边形）"),
                  参数=[I.参数(
                      "环自交",
                      "is_simple = True（简单多边形）",
                      "shapely.geometry.LinearRing.is_simple",
                      "%d 条自交" % len(vs),
                      "改识别 / rebuild/tools/export_contours.py 的环点序（8 字要拆或重排）后"
                      "重跑 export_contours 与本闸")])


def r11_最小边与面积():
    vs = _vs("⑪")
    _detail(vs)
    # ★★ 证据段（**只报不判**）：⑪ 的「最短边」违反里，有几条是**生成器自己已经声明治不好**的。
    #   2026-10-16 用户裁定「就这样留着」⇒ 本闸维持诚实红，这里只把**两个来源**并列出来（铁律 187），
    #   **不消项、不放行**（把它当白名单 = 铁律 137 的「名单漏掉主体 ⇒ 永远绿」）。
    _e11 = [v for v in vs if "最短边" in v]
    _dtot, _drows, _dlo = declared_stub()
    _MEAS["edge_lt_min_n"] = len(_e11)
    _MEAS["declared_stub_total"] = _dtot
    _MEAS["declared_stub_by_floor"] = [list(x) for x in _drows]
    if _dtot is None:
        log("  ★ 证据（只报不判）：⑪ 最短边违反 %d 条；生成器自报「收边没治好」= **没量到**"
            "（`对照.json` 读不到或没有该字段）⇒ 两条读数**无法对照**（铁律 199，不许当成 0）"
            % len(_e11))
    else:
        log("  ★ 证据（只报不判）：⑪ 最短边违反 %d 条；生成器自报「收边没治好」合计 %d 条 %s"
            "（逐层）；`收边下限` = %s ⇒ 两条读数 %s"
            % (len(_e11), _dtot, _drows or "（空）", sorted(_dlo) or "没读到",
               "一致" if len(_e11) == _dtot else "★不一致（两边各自都要查）"))
    em, am = _MEAS.get("edge_min_mm"), _MEAS.get("area_min_mm2")
    return I.结果(not vs,
                  "%s / %s" % (em if em is not None else "—", am if am is not None else "—"),
                  _say(vs, "最短边 ≥ %.2f mm、面积 ≥ %.2f mm²（实测最小边 %s、最小面积 %s）"
                       % (EDGE_MIN_MM, AREA_MIN_MM2,
                          em if em is not None else "—", am if am is not None else "—")),
                  参数=[
                      I.参数(
                          "最短边下限",
                          "%.4f mm" % EDGE_MIN_MM,
                          "闸内常量 EDGE_MIN_MM = RES_MM/4（RES_MM=%.1f）；真源"
                          " 参数.json::构件/共用/环_最短边下限（由 ⑯ 现读现比）" % RES_MM,
                          "%s mm" % (em if em is not None else "—"),
                          "改 rebuild/tools/parts_lib.py::heal_short_edges 与"
                          " 参数.json::构件/共用/环_最短边下限（两边一起改）后"
                          "重跑 export_contours 与本闸"),
                      I.参数(
                          "最小面积下限",
                          "%.2f mm²" % AREA_MIN_MM2,
                          "闸内常量 AREA_MIN_MM2 = RES_MM²/4（RES_MM=%.1f）" % RES_MM,
                          "%s mm²" % (am if am is not None else "—"),
                          "改识别 / rebuild/tools/export_contours.py 的环生成（碎面要并或丢）后"
                          "重跑 export_contours 与本闸"),
                  ])


def r12_不重叠():
    vs = _vs("⑫")
    # ★ `⑫Σ` 汇总行**先印、且不占明细额度**：它是唯一带着**真数**的那几行（铁律 174）。
    sums = [v for v in vs if v.startswith("⑫Σ")]
    det = [v for v in vs if not v.startswith("⑫Σ")]
    tot = 0
    for s in sums:
        m = re.search(r"共 (\d+) 对", s)
        if m:
            tot += int(m.group(1))
    if not sums:
        tot = len(det)              # 没有汇总行 ⇒ 明细就是全部（_overlap_bad 只在截断时出汇总行）
    for v in sums:
        log("     - %s" % v)
    _detail(det)
    return I.结果(not det, "%d 对" % tot if det else "0 对",
                  _say(det, "同一 (层, 类, z) 内多边形互不重叠"),
                  参数=[I.参数(
                      "重叠面积容差",
                      "≤ %.2f mm² 不算重叠" % OVERLAP_EPS_MM2,
                      "闸内常量 OVERLAP_EPS_MM2（万分之一平米；以下算浮点噪声）",
                      "%d 对重叠" % tot,
                      "改识别 / 建墙那一步：同 (层, 类, z) 的环不许叠（复制件要去重）后"
                      "重跑 export_contours 与本闸")])


def r13_柱条数():
    vs = _vs("⑬")
    _detail(vs)
    ok_n = _MEAS.get("col_ok_floors")
    return I.结果(not vs, "%s/%d 层" % (ok_n if ok_n is not None else "—", len(FLOORS)),
                  _say(vs, "每层 COL 条数 == 源图柱数（块 INSERT 与柱层多段线**取多者**）"),
                  参数=[I.参数(
                      "每层 COL 条数",
                      "== 源图柱数（块 INSERT 与柱层 ≥3 点多段线**取多者**）",
                      "%s 的 01_cad/raw/<层名>.dxf::块 _FZHK/_YZHK + 柱层 LWPOLYLINE" % BID,
                      "%s/%d 层相等" % (ok_n if ok_n is not None else "—", len(FLOORS)),
                      "改 rebuild/tools/redraw.py 的柱识别（COL_MODE=auto，两种画法都要数）后"
                      "重跑识别与 export_contours，再跑本闸")])


def r14_规模():
    _scan_ctx()
    mx = _MEAS.get("max_per_floor")
    which = _MEAS.get("max_per_floor_which")
    if mx is None:
        raise I.没量到("规模读数缺：没有任何一层量到条数")
    return I.结果(True, "%d 条/层" % mx,
                  "只报不判：最大一层 %d 条（%s）；实测一次塞 8570 张面 ⇒ SU rc=127，4422 稳"
                  % (mx, which),
                  参数=[I.参数(
                      "单层最大条数",
                      "只报不判（对照：8570 崩 / 4422 稳）",
                      "SU 实测记录与 rebuild/_scratch/probe_contract.py（8570 张面 ⇒ rc=127）",
                      "%d 条（%s）" % (mx, which),
                      "只报不判；单层接近 4422 时先查 export_contours 是否把同层块拆得太碎")])


def r15_DXF对账():
    vs = _vs("⑮")
    _detail(vs)
    return I.结果(not vs, "%d/%d 层" % (len(FLOORS) - len(vs), len(FLOORS)),
                  _say(vs, "逐层 DXF **现读**的闭合 LWPOLYLINE 数 == JSON 条数"),
                  参数=[I.参数(
                      "逐类闭合环数",
                      "JSON 逐类条数（含 holes 数）== DXF 闭合 LWPOLYLINE",
                      "contours/<层名>.dxf（现读的闭合 LWPOLYLINE）",
                      "%d/%d 层相等" % (len(FLOORS) - len(vs), len(FLOORS)),
                      "改 rebuild/tools/export_contours.py 写 JSON/DXF 的那一段"
                      "（两份件必须同源）后重跑 export_contours 与本闸")])


def r16_阈值真源():
    fs = param_bad()
    _detail(fs)
    return I.结果(not fs, "%.4f" % EDGE_MIN_MM,
                  _say(fs, "`参数.json::共用/环_最短边下限` 与闸内 EDGE_MIN_MM 一致（%.4f）"
                       % EDGE_MIN_MM),
                  参数=[I.参数(
                      "环_最短边下限",
                      "%.4f mm（闸内 EDGE_MIN_MM）" % EDGE_MIN_MM,
                      "参数.json::构件/共用/环_最短边下限",
                      ("没量到" if any("没量到" in v for v in fs)
                       else ("%d 处不一致" % len(fs) if fs
                             else "%.4f mm（与参数表一致）" % EDGE_MIN_MM)),
                      "只改一处：把 参数.json::构件/共用/环_最短边下限 或闸内 EDGE_MIN_MM"
                      "改成同一个数（并连读数一起改）后重跑本闸")])


CHECKS = [
    ("①", "12 份楼层件 + index 齐", r01_件齐),
    ("②", "文件头与 index 同源（units=mm）", r02_文件头同源),
    ("③", "layer ∈ 十一类枚举", r03_图层枚举),
    ("④", "z 有限且 ∈ [0, h_m·1000+1]", r04_z范围),
    ("⑤", "h 只许出现在 H_CLASSES 且有限正", r05_h白名单),
    ("⑥", "holes 恒为空表", r06_无洞),
    ("⑦", "环上每个数 isfinite", r07_环上有限数),
    ("⑧", "剥收口点后相邻两点互异", r08_相邻互异),
    ("⑨", "SU 口径 ≥3 个互异点", r09_SU口径点数),
    ("⑩", "环不自交（简单多边形）", r10_不自交),
    ("⑪", "最短边 ≥ EDGE_MIN、面积 ≥ AREA_MIN", r11_最小边与面积),
    ("⑫", "同 (层, 类, z) 内互不重叠", r12_不重叠),
    ("⑬", "每层 COL 条数 == 源图柱数", r13_柱条数),
    ("⑭", "规模（只报不判）", r14_规模),
    ("⑮", "JSON 条数 == contours DXF 闭合环", r15_DXF对账),
    ("⑯", "EDGE_MIN == 参数.json 真源", r16_阈值真源),
]


def main():
    _LOG.clear()
    try:
        c = _ctx()
    except I.没量到 as e:
        log("SKIP：%s —— 「没量到」，不算过、也不假报成 FAIL（铁律 199）" % e)
        return _write(4)

    data, src_col, dxf_by = c["data"], c["src_col"], c["dxf_by"]
    ndoor = src_door_total()

    log("入口件：%s" % CONT)
    log("  ★ 本闸量的是**进 SU 之前的输入**，与 J-10.8-01（参照件）/ -02（正式件）量的东西不同，"
        "三者都要留")
    _ins = sum(v[0] for v in SRC_COL_DETAIL.values())
    _pl = sum(v[1] for v in SRC_COL_DETAIL.values())
    _circ = sum(v[2] for v in SRC_COL_DETAIL.values())
    log("  ★ 件外参照（⑬）：源图柱块 `%s*` %d、柱层多段线(≥3点) %d、墙层圆(r100~1000) %d "
        "⇒ max(块,多段线)+圆 = %s"
        "（与识别侧 auto 同规）；门块 `%s*` 合计 %d 个（**只打印不判** —— 两把尺子不同源）"
        % ("/".join(COL_BLOCKS), _ins, _pl, _circ,
           sum(v for v in src_col.values() if v) or "没量到", DOOR_BLOCK, ndoor))
    # ★ 字面的百分号必须写 `%%` —— 写 `1% 分位` 时 Python 把 `% ` 当转换符，
    #   报 `unsupported format character`，而且**崩在最后一行**（前面全跑完）⇒ 白跑一趟。
    log("  ★ 阈值来源（实测 `_scratch/probe_contract.py`，量的全部环）："
        "最短边 12.0000 mm、最小面积 1250.000 mm²、1%% 分位边长 25.00 mm(= RES)"
        " ⇒ 取 RES/4 = %.2f、RES²/4 = %.2f；SU 自己的容差 ≈ 0.0254 mm（小 246 倍，量的是另一件事）"
        % (EDGE_MIN_MM, AREA_MIN_MM2))

    # ★ 总量读数由**同一份 `data`** 现算（铁律 174：不手打、不另读一遍）。
    _fls = [k for k in data if k != "_index"]
    log("C1 真件：%d 层 / %d 条环（逐条判词见下）"
        % (len(_fls), sum(len(data[k].get("polys") or []) for k in _fls)))

    # ★ 一条判据 = 一个函数；跑器逐条打印、汇总、定 rc，并把每条折成 `_verdict` 的 item 形状。
    rep = I.跑(_GATE, CHECKS, log=log, 宽=24)
    rc = rep.rc
    if rc == 4:
        return _write(4, items=rep.items)

    # ★ 正对照的基线 = **本趟同一份扫描**的 `ordered` + ⑯（不另算一遍 —— 铁律 174）。
    c = _ctx()
    if "scan" not in c:
        log("  ★ 共用扫描没跑出来 ⇒ 正对照无法进行（判据已在上面报红）")
        return _write(1, items=rep.items)
    base = set(c["scan"]["ordered"]) | set(param_bad())

    log("\n---- 正对照（每一条都必须按预期变红，且理由要对上）----")
    fl_wall, _ = _first_of(data, "WALL")
    if fl_wall is None:
        log("  ★ 跳不过去：一条 WALL 都没有，正对照无处下手 ⇒ 本条对照**没量到东西**")
        return _write(1, items=rep.items)

    c2 = ctl("C2 插一个连续重复点",
             _mut(data, lambda pr, _d: pr["ring"].insert(1, list(pr["ring"][0]))),
             src_col, dxf_by, ["⑧"], base)
    c3 = ctl("C3 砍成 2 个互异点",
             _mut(data, lambda pr, _d: pr.__setitem__("ring", [pr["ring"][0], pr["ring"][1]])),
             src_col, dxf_by, ["⑨"], base)
    c4 = ctl("C4 z 越界（写成绝对标高那类）",
             _mut(data, lambda pr, d: pr.__setitem__("z", d["h_m"] * 1000.0 + 40000.0)),
             src_col, dxf_by, ["④"], base)
    c5 = ctl("C5 给非 STAIR 塞 `h`",
             (lambda d: (_set_h_on(d, "WALL"), d)[1])(copy.deepcopy(data)),
             src_col, dxf_by, ["⑤"], base)
    c6 = ctl("C6 塞一个假洞",
             _mut(data, lambda pr, _d: pr.__setitem__("holes", [[[0, 0], [1, 0], [1, 1]]])),
             src_col, dxf_by, ["⑥"], base)
    c7 = ctl("C7 做成 8 字自交", _mut(data, _bowtie), src_col, dxf_by, ["⑩"], base)
    c8 = ctl("C8 缩成 1 mm²", _mut(data, _tiny), src_col, dxf_by, ["⑪"], base)
    c9 = ctl("C9 某层塞一条假 COL",
             (lambda d: (_add_fake_col(d), d)[1])(copy.deepcopy(data)),
             src_col, dxf_by, ["⑬"], base)
    c10 = ctl("C10 复制一条同类多边形", _mut(data, _copy_sibling), src_col, dxf_by, ["⑫"], base)
    c11 = ctl("C11 一个坐标写成 nan",
              _mut(data, lambda pr, _d: pr["ring"].__setitem__(
                  0, [float("nan"), pr["ring"][0][1]])),
              src_col, dxf_by, ["⑦"], base)
    c12 = ctl("C12 units 改成 \"m\"",
              (lambda d: (_bad_units(d), d)[1])(copy.deepcopy(data)),
              src_col, dxf_by, ["②"], base)
    c13 = ctl("C13 layer 改成 \"WAL\"",
              _mut(data, lambda pr, _d: pr.__setitem__("layer", "WAL")),
              src_col, dxf_by, ["③"], base)

    # C14 ★ 新加的 ⑯ **自己也要有伪证器**（铁律 137：判据无分辨力 = 没有这条判据）。
    #   三个方向都要：好输入不报、坏输入报、读不到时**报「没量到」而不是放行**。
    _c14 = (param_bad() == []
            and any(v.startswith("⑯") for v in param_bad(edge=EDGE_MIN_MM + 1.0))
            and any("没量到" in v for v in param_bad(path=PARAM + ".不存在")))
    log("  C14 ⑯ 的伪证器（好/坏/读不到三向）：%s" % ("按预期" if _c14 else "★没分辨力"))

    ctls = [c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, _c14]
    log("\n正对照 %d/%d 按预期" % (sum(ctls), len(ctls)))

    # ★ 正对照是判据的伪证器：任何一条不按预期 ⇒ 判据本身没有分辨力 ⇒ 整闸不许过
    #   （判词那条已在上面报红；这里只在「判据全绿但它们失灵」时补判 FAIL）。
    if not all(ctls):
        if rc == 0:
            rc = 1
        log("J-10.8-00 总判 : FAIL —— ★ 别去跑 SU：正对照未全部按预期 ⇒ 判据没有分辨力，判据作废")
        items = list(rep.items) + [{
            "rule": "⑰", "status": "fail",
            "text": "正对照未全部按预期：%d/%d 触发" % (sum(ctls), len(ctls)),
            "fix": "改算法", "floor": "",
            "evidence": "J-10.8-00 正对照表",
        }]
        return _write(rc, items=items)
    return _write(rc, items=rep.items)


def _write(rc, items=None):
    """落两样产物：run.txt（判词行原样）＋ verdict json（矩阵的原料）。

    ★ 退出码**不在这里算** —— 由调用方递进来（铁律 18）。
    ★ 三态（铁律 199）：rc==4 是「没量到」⇒ `pass=None`；不许写成 False，更不许写成 True。
    ★ `items` 传了就**用跑器交出来的那一份**（同一个量不许两个估计器 —— 铁律 174）。
    """
    os.makedirs(RUNDIR, exist_ok=True)
    pass_ = None if rc == 4 else (rc == 0)
    VD.emit("J-10.8-00", BID, pass_, rc, _LOG, blind=BLIND,
            files={"contours": CONT, "index": IDX, "raw": RAW,
                   "params": PARAM, "duibi": DUIBI},
            extra=dict(_MEAS), items=items)
    print("  写出:", JSON_OUT)
    return rc


if __name__ == "__main__":
    sys.exit(main())
