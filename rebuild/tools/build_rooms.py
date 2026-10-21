# -*- coding: utf-8 -*-
r"""第六教学楼 · **房间表（模型侧）** —— 从图纸现算房间环，与图上 `5面积` 对账。

★ 与已有件的关系（Glob 实查，**不重复造**）：
  · `D:\项目\gym3d\a1\rooms.py`（+ `batch_rooms.py` + 闸 `J-09.2-A1c_rooms.py`）
    = **参考侧**：房号↔最近面积/用途/单位的**近邻**配对，扫 gym3d 全库 105 栋。
    **本件一行不改它、也不 import 它**（跨项目、作用域不同：它给全库目录账，本件给第六教学楼一栋的交付链）。
  · 它自己的注释写死了缺口：「模型侧还没建」—— **本件就是那块模型侧**。

★ **环从哪来**（本件的核心；这条路被证伪过两次，见 `rebuild/识别方案.md` §0.1/§0.2）：
  本图**没有**自带房间边界。`Defpoints` 层 33 条闭合多段线**面积全等于 0.96 m²** ⇒ 是一个重复摆放的
  固定符号，不是房间轮廓（已证伪）；`4.2墙体` 上的闭合多段线是竖井空洞 + 建筑外轮廓，也不是房间。
  ⇒ 房间只能**从墙缝出来**（工程界通行口径：房间 = 墙围合的区域）。做法借广联达 GTJ 那条：
  **墙 = 一对平行边线 + 读中间厚度**，于是

      **房间 = 楼面 plate −（墙带 ∪ 柱 ∪ 门堵）**

  · **墙带**：`4.2墙体` 上互相平行、沿向投影有重叠、间距 = `共用/墙厚` 的线对 → 两线之间的四边形；
  · **柱**：`4.1结构柱` 的 INSERT（块的真实尺寸在 insert 的 scale，块定义是单位块）；
  · **门堵**：`$DorLib2D$` INSERT 的包围盒 ∩ 墙带邻域 —— 不补则门洞把相邻房间**连通**成一块。

★ 墙厚**从参数表现读**（`共用/墙厚`，标注「实测」，出处=探针读数），本件不写死；同时把
  **本层现算的线对间距主峰**印在报表里与之并排 —— 两者不一致时**看得见**（铁律 018/174：
  同一个量不允许两个估计器各说各话）。

★ 配对**带闸**（不许裸最近邻 —— 该坑 `a1/rooms.py` 盲区②与闸 D 对照实测过：无闸会把一条
  479.6 m 外的文字**无声**贴到 78 个房间上）：
  ① **包含**：文字落点必须在环内（`intersects`，含恰在边上）；
  ② **唯一**：一条文字落进多个环 ⇒ 记**歧义**，不硬分；
  ③ **对账**：逐层报「环数 / 各类文字数 / 真配上数 / 未配对」，**对不上要点名，不许静默**。

★ 对什么瞎（写在明处，不假装没有）：
  · 墙**不是双线画**的图 ⇒ 线对配不出来 ⇒ 主峰占比塌掉 ⇒ **本件当场报红，不硬凑**（四级级联里该下沉）；
  · 只量平面（xy）。不是 TEXT/MTEXT 画的文字量不到；**读数 0 不许读成「这层没有房间」**；
  · 门堵只用块包围盒，**不判这个块是不是门**（块名前缀是本图的口径，换图要重认）。

★ 两个用途：
  ① **验算**：`5面积` 是人写的数（件外真值，铁律 192）⇒ 现算面积核它，对上就是**第三方盖章**；
  ② **出件**：环的顶点（外环 + 洞）随表落盘 ⇒ 下游**合成房间地板面片**做三维展示（每块可点选/按用途着色）。

用法：`python rebuild/tools/build_rooms.py [层名…]`
落盘：`rebuild/02_recognize/房间表.json`
"""
import collections
import glob
import hashlib
import heapq
import json
import math
import os
import re
import sys

import ezdxf
import numpy as np
import shapely
import shapely.geometry as sg
from ezdxf import bbox as _bbox
from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B                                # noqa: E402  —— 楼栋档案（CDUT_BUILDING）
import parts_lib as PL                              # noqa: E402
import recognize                                    # noqa: E402  —— 只为剔踏步（真踏步的唯一判据在那边）
import redraw                                       # noqa: E402

ROOT = B.ROOT                                       # 默认 rebuild/；c005 ⇒ rebuild/c005/
RAW = os.path.join(ROOT, "01_cad", "raw")
OUT = os.path.join(ROOT, "02_recognize", "房间表.json")

# ★ 2026-10-17：与 recognize/redraw 同一份认定（写死会让另一些楼读到 0 条墙线）
WALL_LAYER = B.layer("wall", "4.2墙体")
COL_LAYER = B.layer("column", "4.1结构柱")
DOOR_BLOCK = "$DorLib2D$"


def _kinds_from_profile():
    """台账四层名从档案的 `keep_layers` 里**按后缀认** —— 两个楼的层名不一样
    （c006 `7用途`/`8单位`，c005 `7使用单位`/`8用途`），写死一份就是把 c005 的
    「用途」读成空表（铁律 018：同一个量不许有两个来源）。"""
    keep = B.profile().get("keep_layers") or []
    out = {}
    for kind in ("面积", "房间号", "用途", "单位"):
        # ★ 2026-10-18：**一个 kind 可以有多层**（c009 同时有 `7使用单位` + `9调整单位`，
        #   c059~c065 同时有 `8房间用途` + `7用途类型`）。原来「不唯一就报错」⇒ 装包直接 rc=1，
        #   而错的不是图、是我把「一层」当成了一类。现在按层名**全收**，由 `LAYER2KIND` 合并归类。
        # ★ 2026-10-17：再放宽一档 —— 有的楼把层名写成 `7用途分类`（C001），后缀法读不到。
        #   先用后缀（最严）；后缀零命中才用「包含」，包含若仍非唯一就照旧报错（不猜）。
        # ★ 2026-10-18：`8功能` 是「用途」的另一种写法（c007，164 条）—— 只按「用途」二字找，
        #   这一层就**整层读不到**，台账用途为空而图上明明写着（铁律 158 盲区）。
        alias = ("用途", "功能") if kind == "用途" else (kind,)
        hit = [n for n in keep if any(n.endswith(a) for a in alias)]
        if not hit:
            hit = [n for n in keep if any(a in n for a in alias)]
        if len(hit) > 1 and kind in ("面积", "房间号"):
            # 面积/房间号说「多层」多半是**同名两套**（c046 的 `6房间号` + `6房间号2`），
            # 合并会把同一间房读两次 ⇒ 这两类仍然要唯一，不唯一就停下问人。
            raise SystemExit("楼栋档案 %s 的 keep_layers 里有 %d 个「%s」层：%s（只允许一个）"
                             % (B.BID, len(hit), kind, hit))
        if len(hit) > 1:
            print("★ %s 的「%s」保留层有 %d 个（%s）⇒ 合并读"
                  % (B.BID, kind, len(hit), " / ".join(hit)))
        if not hit:
            # ★ 2026-10-17：有的楼图上根本没有「使用单位」层（C105 只有 5面积/6房间号/7用途）。
            #   台账里 `dept` 本来就允许空 ⇒ 这两类是**可缺**的。
            # ★ 2026-10-17 C046：还有的楼**连面积层都没有**（C046 只有 6房间号/7使用单位）。
            #   面积文字常常就写在房间号层上（`17.50m` 形，见 `texts()` 的重分类）⇒ 面积层缺失
            #   不再是致命，但必须**喊一声**：若房间号层上也没有面积形状，房间容量就是空的，
            #   下游会如实报「0 间」（不是静默铺一片没名字的地面）。
            # ★ 2026-10-17 C015：还有图**没有房间号层**（C015 只有 5面积 + 8房间用途，
            #   房号可能写在墙体层的多行文字里，但那不是本工具认的形状）⇒ 也不再致命，
            #   台账照出、`name` 为空并大声报出来（「没有名字的房间」≠「没有房间」）。
            if kind in ("用途", "单位", "面积", "房间号") and not hit:
                if kind == "面积":
                    print("★ %s 的 keep_layers 里没有面积层 ⇒ 面积只能从房间号层的 "
                          "`17.50m` 形状现认（认不到就会是 0 间）" % B.BID)
                elif kind == "房间号":
                    print("★ %s 的 keep_layers 里没有房间号层 ⇒ 房间只能按面积落位、"
                          "没有名字（图上确实没画这个层）" % B.BID)
                out[kind] = None
                continue
            raise SystemExit("楼栋档案 %s 的 keep_layers 里找不到「%s」层：%s"
                             % (B.BID, kind, keep))
        out[kind] = list(hit)          # 一律**列表**（0/1/多层的形状统一，调用方不用分叉）
    return out


KINDS = _kinds_from_profile()
# 层名 → kind：一个 kind 可以对应多个层名（用途/单位），合并后都归到同一个 kind。
LAYER2KIND = dict((lay, k) for k, lays in KINDS.items() if lays for lay in lays)
TOL_M2 = 0.01                                       # 面积判「一致」的容差（m²）
TOL_REL = 0.01                                      # 面积判「一致」的相对容差（1%）—— 房间表用这个
CELL_M = 0.1                                        # 容量生长的栅格边长（m）
TAIL_MIN_M = 0.80                                   # 「尾巴」阈值（m）：窄于它的细条一律削掉（见剪尾）

# —— 线对（墙带）参数。都是**量具的形状参数**，不是图纸的量；改它们只影响配不配得出来 ——
FLATTEN_MM = 5.0                                    # 弧/带凸度多段线展平步长
MIN_LEN_MM = 500.0                                  # 只拿够长的线去配对（短渣不参与，免得糊掉间距分布）
PAR_TOL_DEG = 2.0                                   # 判「平行」的角差上限（★ 角按 180° 环处理，**没有角桶**：
                                                    #   分箱法已废，它把同一条水平线的两面线判进 0°/180° 两箱，永远配不上）
GAP_MIN_MM = 30.0                                   # 线对间距下限（挡住重合线）
GAP_MAX_MM = 1500.0                                 # 线对间距上限（挡住跨房间的远线对）
OVERLAP_MIN_MM = 200.0                              # 沿向投影重叠下限（重叠太短不算同一道墙的两边线）
# ★ 2026-10-16 **撤下** `PEAK_SHARE_MIN = 0.20`（原「主峰成立」判据）。撤下的实测理由：
#   它是**打字常数**（识别方案 §4：阈值一律不打字），而且正好落在刀口上 ——
#   2 层占比 0.199、7 层 0.181，都**恰在 0.20 之下** ⇒ 判否 ⇒ 不出环 ⇒ 这两层 **40 间房的文字全丢**
#   （2 层 34 间 / 7 层 6 间，文字数实测 34/34/34/34 与 6/6/6/6）。
#   而这两层 240 mm **就是众数**（380 对 / 282 对）—— 真墙在，只是被 270 mm 的**周期梳状族**
#   （270/540/810/1080/1350 mm）稀释了占比。⇒ 不是「没有墙」，是判据选错了量。
#   现改为**与参数表声明的墙厚对齐**（`PEAK_TOL_BINS`）：墙厚是**外部声明值**（`共用/墙厚`，有出处），
#   不是本件打的分数；`主峰占比` 降级为**读数**（照印，不再当闸）。**别再把这个常数加回来。**
PEAK_TOL_BINS = 1.0                                 # 主峰与「声明墙厚」允许差几格（量具形状参数）
BIN_MM = 10.0                                       # 间距直方图取整（主峰 = 众数格）

# ★ 2026-10-19（64 栋批跑实测）：`构件库/参数.json` 的 `共用/墙厚` 是**全仓一份**（c006 的 240），
#   但每栋楼的墙厚现算主峰是 60/80/100/120/200/300 mm 不等 ⇒ 50 栋被「主峰不在声明墙厚上」
#   判否、rc=0 却 0 间。判据没错（它拦的正是「主峰对不上」），错的是**参照物只有一份**。
#   现在墙厚**按栋取**：档案写了 `墙厚_mm` 就用它；没写就在本栋各层现算主峰，**≥80% 层一致**
#   才采用（`WALL_SRC` 记来源）；层间不一致照旧判否 —— 不把「量不出来」硬凑成一个数。
WALL_MM = None                                      # 本栋墙厚（mm）；None ⇒ 用参数表（旧行为）
WALL_SRC = "参数表"
# ★ 2026-10-20 c015 芙蓉综合楼：同一栋里各层主峰分别为 300/250/300（2/3 一致 < 80%）
#   ⇒ 按栋那一条拒绝采用，三层全落回 240，其中 1、3 层判否、0 间。
#   但「一栋只有一种墙厚」本身是假设，不是图纸事实。档案可写 `墙厚_mm_按层`
#   （逐层**实测主峰**，不是猜的数），该层就用自己的那一档；没写的层仍走 `WALL_MM`/参数表。
#   ★ 仍然守「主峰必须落在声明值上」（`PEAK_TOL_BINS`）：按层声明的是实测值，不是免检。
WALL_MM_BY_FLOOR = {}
                                                    # （旧 `BRIDGE_COLLINEAR` 随端帽法一起删：现在按最近点对补，
                                                    #   方向由两块自己的几何给出，不留这个空旋钮误导人）
BAND_EXTEND_MM = 0.0                                # 墙带沿轴两端各加长；默认 0，诊断期可用 `--extend` 扫
VALLEY_MIN_MM = 200.0                               # 缝谱里「接头缝簇 ↔ 洞口簇」的空档最小宽度；窄于此不闭（宁可不闭）
CAP_OVERRIDE = None                                 # 诊断用：`--cap=MM` 覆盖自动算出的洞口上限
BRIDGE_NOGATE = False                               # 诊断用：`--nogate` 关掉「必须有门块压着」那道闸

_CODE = re.compile(r"\\[A-Za-z]+[^;]*;")            # MTEXT 格式码：\A1;  \pxqc;  \fSimSun|b0|…;  \H0.7x;  \S2^ ;
_AREA = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*m")


# ----------------------------------------------------------------- 文字（与图上对账的那半）
def plain(s):
    """剥掉 MTEXT 格式码，留下人能读的字。"""
    s = _CODE.sub("", s or "").replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def parse_area(s):
    """`185.34m²` / `185.34m{\\H0.7x;\\S2^ ;}` → 185.34；解析不出 → None（如实记，不猜）。"""
    m = _AREA.search(s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def texts(doc):
    """四件套文字 → {类别: [{'文': str, 'xy': (x,y)}]}。

    ★ 2026-10-17 两处修正（C001 实测逼出来的，都是**量具读错了**，不是图上没字）：
      ① `xy` 取**文字包围盒中心**，不取 `insert`。MTEXT 是左上锚点（attachment 1），
         字向右铺 4 m 多 ⇒ 锚点会落在墙上（C001 4层 `01-04-22` 锚点正好压进 100 mm 隔墙，
         量的 50 mm 圆一个分区都碰不到，判词却是「文字没落进分区」）。
      ② 面积文字有时画在**房间号图层**上（C001 4层 `17.50m` 就在 `6房间号`）⇒
         形如 `17.50m` 的短语归到「面积」，否则会被当成第二间房（铁律 158：尺子要认得出的形状）。
    """
    from ezdxf import bbox as _bbox
    d = collections.defaultdict(list)
    _area_only = re.compile(r"^[0-9]+(?:\.[0-9]+)?\s*m$")
    for e in doc.modelspace():
        t = e.dxftype()
        if t not in ("TEXT", "MTEXT"):
            continue
        kind = LAYER2KIND.get(e.dxf.layer)
        if not kind:
            continue
        p = e.dxf.insert
        x, y = float(p.x), float(p.y)
        try:
            bb = _bbox.extents([e])
            if bb.has_data:
                x = (bb.extmin.x + bb.extmax.x) / 2.0
                y = (bb.extmin.y + bb.extmax.y) / 2.0
        except Exception:
            pass                                    # 量不到包围盒 ⇒ 退回锚点（不静默少字）
        s = plain(e.dxf.text if t == "TEXT" else e.text)
        if kind == "房间号" and _area_only.match(s):
            kind = "面积"
        d[kind].append({"文": s, "xy": (x, y)})
    return d


# ----------------------------------------------------------------- 图元 → 线段 / 块包围盒
SEG_FAIL = collections.Counter()        # 展平失败的图元类型 → 条数（读数，进 `rooms()` 的 meta）


def _flatten(e):
    """图元 → 点列。**必须有兜底**：`LWPolyline`/`Arc`/`Circle` 没有 `.flattening()`，
    c005 的墙全是 2 点 LWPOLYLINE ⇒ 原版每一条都抛异常、被 `except: continue` 吞掉，
    于是「0 线对 ⇒ 本层不出环」——**判词把量具瞎了说成图上没墙**（铁律 158）。
    现在按 ezdxf 的公共入口 `path.make_path()` 走，展平不开就计数，不静默。"""
    fn = getattr(e, "flattening", None)
    if fn is not None:
        return [(p[0], p[1]) for p in fn(FLATTEN_MM)]
    from ezdxf import path as _path
    return [(v.x, v.y) for v in _path.make_path(e).flattening(FLATTEN_MM)]


def segs_of_doc(doc, layer):
    """已读进内存的 DXF → 该图层所有图元展平成 LineString 列表。

    ★ 与 `segs_of(path, …)` 拆开，是为了让同一趟里**只读一次盘**：`rooms()` 已经读了 doc，
      生长屏障又要同一批线 —— 再 `ezdxf.readfile` 一遍等于把 12 张图各读两次。
    """
    out = []
    for e in doc.modelspace():
        if e.dxf.layer != layer:
            continue
        t = e.dxftype()
        if t == "LINE":
            a, b = e.dxf.start, e.dxf.end
            out.append(sg.LineString([(a.x, a.y), (b.x, b.y)]))
        elif t in ("LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"):
            try:
                pts = _flatten(e)
            except Exception:                        # noqa: BLE001 —— 展平失败就跳过，但**记账**
                SEG_FAIL[t] += 1
                continue
            for i in range(len(pts) - 1):
                if pts[i] != pts[i + 1]:
                    out.append(sg.LineString([pts[i], pts[i + 1]]))
    return out


def segs_of(path, layer):
    """该图层上所有图元 → LineString 列表（弧与带凸度的多段线**展平**，不丢曲线）。"""
    return segs_of_doc(ezdxf.readfile(path), layer)


def block_boxes(doc, prefix=None, layer=None):
    """INSERT → 包围盒多边形（**真几何范围**，交给 ezdxf 的 bbox 算）。

    ★ 为什么不能用「圆心 ± 半径」自己拼：块里的 `ARC` 是**圆上的一小段**，用整圆的盒去代表它，
      半径一大就炸 —— 实测 1层 有个门块的盒被算成 **274999 mm（275 m）**，左下角 x=-137985，
      整栋楼都在 x∈[17000,146000] 之外。这一个离群值把「洞口尺寸上限」带成 275 m，
      于是补洞 98487 条把楼面盖满、房间环从 33 掉到 5（铁律 174：一个被污染的量不许带飞判据）。
    ★ 块定义是单位块 ⇒ 真实尺寸在 insert 的 scale/rotation，而 `virtual_entities()` 已经烘进坐标。
    """
    out = []
    for e in doc.modelspace():
        if e.dxftype() != "INSERT":
            continue
        if prefix is not None and not (e.dxf.name or "").startswith(prefix):
            continue
        if layer is not None and e.dxf.layer != layer:
            continue
        try:
            b = _bbox.extents(list(e.virtual_entities()))
        except Exception:                            # noqa: BLE001 —— 单块解不出就少一个，如实计数
            continue
        if b.has_data:
            out.append(sg.box(b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y))
    return out


# ----------------------------------------------------------------- 线对 → 墙带
def wall_pairs(segments):
    """互相平行、沿向投影重叠、间距在区间内的线对。

    → 生成 `(si, sj, d, u, pi, pj)`：i 的投影区间 `pi`、j 的 `pj`（都投在 i 的方向轴上）、
      单位向量 `u`、间距 `d`。
    ★ 投影重叠必须按区间交算 —— 曾经写成 `si.intersection(sj.buffer(1.0))`（半径 1 mm），
      相距 ≥30 mm 的平行线永不相交 ⇒ 每对都被自己的过滤器吃掉，印出一条**假的「一双都没配出来」**
      （铁律 158：否定判词先证量具不盲）。
    ★ 方向角按 **180° 环**处理，**分箱法已废**（实测是它把墙漏掉的）：先前按
      `round(ang/5)*5` 分箱、再要求 `abs(ai-aj) ≤ 2°` —— 但**同一条水平线，画出方向不同就落两箱**：
      1层 910 条水平线里 440 条进 0° 箱、**235 条进 180° 箱**，而 |180-0| = 180 > 2 ⇒ 这两批
      **永远配不上**。后果是**同一道墙的两条面线分属两箱**（实测 y=49680 那批全在 180° 箱、
      y=49920 那批全在 0° 箱）⇒ 那道墙一条带都出不来 ⇒ 房间的边界上开一个口子。
      现在改成：按角排序 + 双指针扫 ±PAR_TOL_DEG（含跨 180° 的回绕），彻底没有箱边界。"""
    dat = []
    for s in segments:
        if s.length < MIN_LEN_MM:
            continue
        (x1, y1), (x2, y2) = s.coords[0], s.coords[-1]
        dat.append((s, math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0))
    if not dat:
        return
    dat.sort(key=lambda t: t[1])
    ang = [d[1] for d in dat]

    def emit(si, ai, sj, aj):
        u = (math.cos(math.radians(ai)), math.sin(math.radians(ai)))
        two = (math.cos(math.radians(aj)), math.sin(math.radians(aj)))
        if min(abs(u[0] * two[0] + u[1] * two[1]), 1.0) < math.cos(math.radians(PAR_TOL_DEG)):
            return None                       # 真平行度复核（挡住分箱放水）
        d = si.distance(sj)
        if d < GAP_MIN_MM or d > GAP_MAX_MM:
            return None
        pi, pj = _interval(si, u), _interval(sj, u)
        if min(pi[1], pj[1]) - max(pi[0], pj[0]) < OVERLAP_MIN_MM:
            return None
        return si, sj, d, u, pi, pj

    n = len(dat)
    for i in range(n):
        si, ai = dat[i]
        j = i + 1
        while j < n and ang[j] - ai <= PAR_TOL_DEG:      # 同侧
            r = emit(si, ai, dat[j][0], dat[j][1])
            if r:
                yield r
            j += 1
        j = 0
        while j < i and ang[j] + 180.0 - ai <= PAR_TOL_DEG:   # 跨 180° 回绕
            r = emit(si, ai, dat[j][0], dat[j][1])
            if r:
                yield r
            j += 1


def _interval(s, u):
    """线段在方向轴 u 上的投影区间 [t0, t1]（升序）。"""
    (x1, y1), (x2, y2) = s.coords[0], s.coords[-1]
    t = sorted((x1 * u[0] + y1 * u[1], x2 * u[0] + y2 * u[1]))
    return t


def _at(s, u, t):
    """线段 s 上「沿 u 的投影 == t」那个点。s 必须真的沿 u 有长度（退化则返回起点）。"""
    (x1, y1), (x2, y2) = s.coords[0], s.coords[-1]
    t1, t2 = x1 * u[0] + y1 * u[1], x2 * u[0] + y2 * u[1]
    if abs(t2 - t1) < 1e-9:
        return (x1, y1)
    f = (t - t1) / (t2 - t1)
    return (x1 + f * (x2 - x1), y1 + f * (y2 - y1))


def peak_of(pairs):
    """线对间距直方图 → (主峰 mm, 主峰占比, 候选对数)。**主峰 = 众数格**，不打字。"""
    ds = [d for _si, _sj, d, _u, _pi, _pj in pairs]
    if not ds:
        return None, 0.0, 0
    cnt = collections.Counter(round(d / BIN_MM) * BIN_MM for d in ds)
    top, n = cnt.most_common(1)[0]
    return float(top), n / len(ds), len(ds)


def spectrum_top(pairs, k=6):
    """间距直方图前 k 格 `[[mm, 对数], …]`。

    ★ 为什么判否时也要记：撤下的 `PEAK_SHARE_MIN` 当年判否 2 层/7 层，而读数里**谱是 null** ⇒
      「为什么否」在落盘件上**无从复核**，只能重跑。判否必须留下**证据**（铁律 192 的同一件事）。"""
    ds = [d for _si, _sj, d, _u, _pi, _pj in pairs]
    cnt = collections.Counter(round(d / BIN_MM) * BIN_MM for d in ds)
    return [[float(m), n] for m, n in cnt.most_common(k)]


def bands_from(pairs, thickness, extend=0.0):
    """线对 → 墙带多边形（两线之间的四边形，厚度 = 实测间距，不用表值）。

    ★ 带沿轴取的是两条线投影区间之**并（hull）**，不是之**交（overlap）** —— 实测定的，不是推的：
      同一道墙的两条面线在**接头处被各自剪裁**，长度并不相等（1层 918 对：端差每端 P50 60 mm /
      P75 316 mm / P90 885 mm）。取交 ⇒ 每条带**两端各缩掉一截** ⇒ 相邻两段之间裂开四五分米的缝
      ⇒ 墙带网络散成 **247 个孤立小块**（单块中位 0.59 m²）⇒ 楼面切不开、最大一块占 86%。
      取并之后，前后两段的并区间**彼此搭上**，网络才连得起来。
    ★ 间距闸：只收 `thickness` 量级上的对（0.5t~1.6t）。原来的 `GAP_MAX_MM=1500` 会把 810~1080 mm
      的远对一并收进来（P75/P90）——那是**一个走廊宽**，不是墙厚，配出来的带是假的。
    `extend`（mm）：两端各再加长这么多（默认 0，诊断期用 `--extend` 扫）。
    """
    lo_t, hi_t = thickness * 0.5, thickness * 1.6
    out = []
    for si, sj, d, u, pi, pj in pairs:
        if not (lo_t <= d <= hi_t):
            continue
        lo, hi = min(pi[0], pj[0]) - extend, max(pi[1], pj[1]) + extend
        if hi - lo < OVERLAP_MIN_MM:
            continue
        quad = [_at(si, u, lo), _at(si, u, hi), _at(sj, u, hi), _at(sj, u, lo)]
        p = sg.Polygon(quad)
        if p.is_valid and p.area > 0:
            out.append(p)
    return out


def _axis(q):
    """带块（四边形）→ (单位轴向量 u, 单位法向量 n, 中心 c)。轴取**最长边**的方向。

    用最长边而不是包围盒长边：带是四边形，斜着放时包围盒长边会被斜对角线带偏。"""
    c = list(q.exterior.coords)[:4]
    best, u = -1.0, (1.0, 0.0)
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        dx, dy = c[b][0] - c[a][0], c[b][1] - c[a][1]
        L = math.hypot(dx, dy)
        if L > best:
            best, u = L, (dx / L, dy / L)
    cen = (sum(v[0] for v in c) / 4.0, sum(v[1] for v in c) / 4.0)
    return u, (-u[1], u[0]), cen


def bridges(quads, gap_lo, gap_hi, thickness, door_boxes):
    """把墙带**被洞口打断**的两段接起来 —— 补出的那一条就是洞口那一格。

    ★ 判据**全部从实测取，门在机制里不参与**（门只用来对数：见 `stat`）。这一版是第四版，
      前三版为什么都不行，记账在此 ——
      · 拿门块包围盒直接当堵：盒横跨整个门斗，`盒 ∩ 带.buffer` 只贴断口啃两小条，洞口中段仍敞着；
      · 按**连通块**找接口：一间房的四道墙本来就是同一块（绕过其它三面墙连通）⇒ 门口两侧同块
        ⇒ 「要两块才补」自己把自己否了（只补上 21/116，最大一块 5593 m²）；
      · 按**门块包围盒**当定位与上限：实测 116 樘里 **35 樘「缝全超上限」、19 樘「补条不跨门」**
        —— 门块的盒是**门扇那一小条**，既盖不住洞口、也不在洞口中心，它当不了尺子。
      现在换掉尺子：**洞口本身就是墙带网络里的一道缝**，量缝即可，不必知道那是哪樘门。
      ① **缝宽闸** `(gap_lo, gap_hi]`：`gap_lo` = 接头缝簇的顶（比它小的已被闭运算合上）；
         `gap_hi` = 门块自己声明的宽度 P98 + 2×墙厚（L0 块表真值，见 `rebuild/识别方案.md` §0）。
      ② **共线闸**：洞口是**同一道墙**上断开的一格 ⇒ 两条带的轴必须平行（角差 ≤ PAR_TOL_DEG）、
         且中心线的**垂距 ≤ 墙厚**。没有这道闸，会把「隔一条走廊的两道平行墙」也接起来
         —— 实测 4层 由此多出 14 个假环（44 vs 面积文字 30）。
      ③ 补条的**宽** = 墙厚；补条的**长** = 两条带之间的实际距离（由几何给，不打字）。
    """
    stat = collections.Counter()
    # ★ 2026-10-19：缝谱分不出两簇时 `gap_lo/gap_hi` 可能是 None（junction_closer_r 的早退）
    #   ⇒ 这里先判 None 再比大小，否则 `None <= None` 直接 TypeError（c065 实测）。
    if not quads or gap_lo is None or gap_hi is None or gap_hi <= gap_lo:
        return [], stat
    cos_tol = math.cos(math.radians(PAR_TOL_DEG))
    ax = [_axis(q) for q in quads]
    tree = STRtree(quads)
    out = []
    seen = set()
    for i, qa in enumerate(quads):
        ua, na, ca = ax[i]
        for j in tree.query(qa.buffer(gap_hi)):
            if j <= i:
                continue
            d = qa.distance(quads[j])
            if d < gap_lo or d > gap_hi:
                continue
            ub, nb, cb = ax[j]
            if abs(ua[0] * ub[0] + ua[1] * ub[1]) < cos_tol:
                continue                             # 不平行 ⇒ 不是同一道墙
            dv = (cb[0] - ca[0], cb[1] - ca[1])
            if abs(dv[0] * na[0] + dv[1] * na[1]) > thickness:
                continue                             # 中心线错开超过一个墙厚 ⇒ 不是同一道墙
            pa, pb = nearest_points(qa, quads[j])
            g = math.hypot(pb.x - pa.x, pb.y - pa.y)
            if g <= 1e-9:
                continue
            ux, uy = (pb.x - pa.x) / g, (pb.y - pa.y) / g
            nx, ny = -uy, ux
            h = thickness / 2.0
            plug = sg.Polygon([(pa.x + nx * h, pa.y + ny * h), (pb.x + nx * h, pb.y + ny * h),
                               (pb.x - nx * h, pb.y - ny * h), (pa.x - nx * h, pa.y - ny * h)])
            if not plug.is_valid or plug.area <= 0:
                stat["成品退化"] += 1
                continue
            key = (round(pa.x, -2), round(pa.y, -2), round(pb.x, -2), round(pb.y, -2))
            if key in seen:                          # 同一道缝被两条不同的带重复量到 ⇒ 只补一次
                continue
            seen.add(key)
            out.append(plug)
            stat["补上"] += 1
    # —— 对数：门只在这儿出现（L0 块表：门块位置是零几何推理的现成真值）——
    door_union = unary_union(door_boxes) if door_boxes else None
    stat["樘"] = len(door_boxes)
    if door_union is not None:
        stat["门上有补条"] = sum(1 for b in door_boxes if any(p.intersects(b) for p in out))
        stat["补条没门"] = sum(1 for p in out if not p.intersects(door_union))
    return out, stat


# ----------------------------------------------------------------- 楼面
def plate_of(floor):
    """整层楼面外轮廓（`redraw.geometry` 给）→ 一个多边形；楼面为空 ⇒ None（如实报）。"""
    g = redraw.geometry(floor)
    plates = [sg.Polygon(c) for c in g["plate"] if len(c) >= 3]
    if not plates:
        return None
    u = unary_union([p if p.is_valid else p.buffer(0) for p in plates])
    return u if u.geom_type == "Polygon" else unary_union(list(getattr(u, "geoms", [])))


# ------------------------------------------------- 接头缝闭运算半径（缝谱空档现算，见 rebuild/识别方案.md §3-L2）
def junction_closer_r(block, cap_mm):
    """墙带网络里「**接头缝**」的闭运算半径（mm）—— 从实测缝谱的**空档**取，不打字。

    图纸把双线墙在**每个接头处也断开**（1层实测缝谱：120 / 240×3 / 364，随后一跳就是 1201 才是洞口），
    所以「取并集」出来的墙带网络在**接头上依旧互相分离** —— 并集永远合不上 120 mm 的缝
    ⇒ 楼面切不开、化成一大块（实测最大一块 5594 m²，占楼面 80%）。**这不是门的问题，是接头的问题。**

    做法（全部取自本层实测）：
      ① 量出**相邻两带块之间的最近距**（只量 `cap_mm` 之内的缝，远处的缝不参与比大小）；
      ② 排序后找**最大空档** —— 那就是「接头缝簇 ↔ 洞口簇」的分界（`g_低` / `g_高`）；
      ③ 半径取两档约束的**几何中值**：`2r` 必须**大于** `g_低`（合上接头缝）、
         **小于** `g_高`（不许把洞口也合上，洞口由 `bridges` 补）。
    ★ 只量缝的**几何**，不猜哪条是门；`cap_mm` 来自门块包围盒的 P95（见 `rooms`）。
    → `(r, g_低, g_高)`；缝谱分不出两簇（空档不够大）时返回 `(0, None, None)`，即不闭。
    """
    comps = PL.polys_of(block) if block.geom_type != "Polygon" else [block]
    if len(comps) < 2 or cap_mm <= 0:
        # ★ 2026-10-19：这里原来返回 3 元组，调用方按 4 元组解包 ⇒ 墙带并为**一整块**（没有接头缝
        #   可量）时直接 ValueError。以前被「主峰不在声明墙厚上」判否挡住了，从没走到；按栋取墙厚后
        #   第一次走到就崩（c065）。统一成 4 元组，缝谱给空表。
        return 0.0, None, None, []
    tree = STRtree(comps)
    gaps = []
    for i, c in enumerate(comps):
        for j in tree.query(c.buffer(cap_mm)):
            if j <= i:
                continue
            d = comps[i].distance(comps[j])
            if GAP_MIN_MM < d <= cap_mm:
                gaps.append(d)
    if len(gaps) < 3:
        return 0.0, None, None, gaps
    gaps.sort()
    k = max(range(len(gaps) - 1), key=lambda i: gaps[i + 1] - gaps[i])
    lo, hi = gaps[k], gaps[k + 1]
    if hi - lo < VALLEY_MIN_MM:                      # 空档不够宽 ⇒ 分不出两簇，宁可不闭（不硬凑）
        return 0.0, lo, hi, gaps
    r = math.sqrt((lo / 2.0) * (hi / 2.0))           # 两档约束的几何中值：2r 落在 (lo, hi) 正中对数位置
    return r, lo, hi, gaps


# --------------------------------------------- 生长屏障（墙线 → 加粗多边形）
def wall_barriers(path, doc, segs, t_mm):
    """**生长屏障** = `4.2墙体` 上识别到的每一条线（剔掉真踏步）按**半墙厚**加粗的多边形。

    ★ 为什么必须有它（2026-10-17，用户两句原话：「各个地板的样子还是不太正确」「地面不对」）：
      环 = 楼面 −（墙带 ∪ 柱 ∪ 门堵），而**墙带只由间距落在 [120,384] mm 的线对**构成；
      1 层实测 1153 条线对只有 **585** 条成带 —— 另外那 49% 的墙**一条都不在 block 里**，
      环于是跨墙合并：1 层 **76% 的楼面（5320.37 m²）是同一个环、装下 27 间房**。
      而 `grow_patches` 只判「格子在不在环内」，不看墙 ⇒ 27 间房在同一块空地上按容量
      互相冲波前 ⇒ 圆钝色块、45° 台阶、**横穿房间的假分界**。用户看到的就是这个。
      ⇒ 把墙线本身当**生长屏障**（栅格里记 `lab=-2`：既不算房间、也不算交通），
        每个种子就只能长进自己那间被墙围住的格子，分界自然落在墙上。

    ★ 踏步线必须剔掉：踏步也在 `4.2墙体` 层、间距 250–300 mm、长度落在带闸内，不剔会把楼梯
      切成一根根条子。判据**不在这里另写一套**：`recognize.tread_lines`（真踏步 = 成跑的那些线）
      + `recognize.drop_treads` 逐条对上，与本仓其它剔踏步处同一个源。
    ★ 半径取 `墙厚/2`：图里一堵墙是**两条面线**，各加粗半个墙厚后中间那道缝才闭合；
      取更小会留一条 ~130 mm 的通道，生长顺着它从一间房**漏**进另一间（症状＝细长色带穿墙）。
    ★ 量具盲区（写在这里，不假装没有）：屏障只认 `4.2墙体` 层的**线**；画在别的层上的墙、
      块里的墙（INSERT 不进来）都不算 ⇒ 那些地方仍会跨墙合并。层名/口径与本件 `WALL_LAYER` 同一个常数。
    """
    zones = recognize.stair_zones(path, doc=doc)
    treads = recognize.tread_lines(doc, zones) if zones else []
    pairs = [((s.coords[0][0], s.coords[0][1]), (s.coords[-1][0], s.coords[-1][1])) for s in segs]
    kept, n_drop = recognize.drop_treads(pairs, treads)
    polys = [sg.LineString(p).buffer(t_mm / 2.0, quad_segs=2) for p in kept]
    return unary_union(polys) if polys else None, \
        {"屏障线": len(kept), "剔踏步": n_drop, "梯区": len(zones)}


def close_barrier(geom, r):
    """屏障闭合：每道墙各自画出、**接头处本来就断着**（带网络也一样，1 层实测缝 ≤257 mm）。
    `r` 直接用本层 `junction_closer_r` 现算的那个半径 —— 与墙带**同一把尺子**，
    不另打一个数（否则同一件墙上两个阈值各说各话）。"""
    if geom is None or r <= 0:
        return geom
    return geom.buffer(r, join_style=2).buffer(-r, join_style=2).buffer(0)


def resolve_wall(floors):
    """本栋墙厚（mm）：档案 `墙厚_mm` 优先；没有就各层现算主峰，**≥80% 层一致**才采用。

    返回 (mm|None, 来源说明)。None = 不采用 ⇒ 照旧用参数表那一份（旧行为），该判否的照判否。
    ★ 为什么是「≥80% 层一致」而不是取众数就完：两三个峰值各占一半，说明**这栋图不是一套墙**，
      取哪个都是猜（铁律 174：两个同名的量必须死掉一个；这里宁可判否）。
    """
    prof = B.profile() or {}
    if prof.get("墙厚_mm"):
        return float(prof["墙厚_mm"]), "档案声明 墙厚_mm=%s" % prof["墙厚_mm"]
    peaks = []
    for f in floors:
        p = os.path.join(RAW, f + ".dxf")
        if not os.path.isfile(p):
            continue
        try:
            doc = ezdxf.readfile(p)
            peak, share, n = peak_of(list(wall_pairs(segs_of_doc(doc, WALL_LAYER))))
        except Exception as e:                           # noqa: BLE001 —— 一层崩了不拖垮整栋
            print("  ★ %s 现算主峰时崩了：%r（不计入一致性）" % (f, e))
            continue
        if peak:
            peaks.append((f, peak, share, n))
    if not peaks:
        return None, "各层都没配出线对 ⇒ 用参数表"
    cnt = collections.Counter(x[1] for x in peaks)
    top, n = cnt.most_common(1)[0]
    if n / len(peaks) >= 0.8:
        return float(top), "本栋现算（%d/%d 层一致，主峰 %.0f mm）" % (n, len(peaks), top)
    return None, ("层间主峰不一致（%s）⇒ 不采用，照参数表判否"
                  % " ".join("%s=%.0f" % (f, pk) for f, pk, _s, _n in peaks))


# ----------------------------------------------------------------- 环 = plate −（墙带 ∪ 柱 ∪ 门堵）
def rooms(floor, debug=False):
    """→ (房间环列表, 读数, doc, 生长屏障)。**这是本件的入口判据所在**：线对主峰不成立 ⇒ 环为空 ⇒ 该下沉。

    第 4 项 `生长屏障` 是加粗后的墙线多边形列表（见 `wall_barriers`），只给 `grow_patches` 用，
    **不进读数**（几何不可 JSON 化，且它不是交付物）。
    `debug=True` 时额外挂 `_faces_all`/`_quads`/`_plate` 三个中间量（只给绘图探针用，
    落盘的读数里**不带**它们 —— 交付件不许夹带调试物）。"""

    path = os.path.join(RAW, floor + ".dxf")
    doc = ezdxf.readfile(path)
    _per = WALL_MM_BY_FLOOR.get(floor)
    t_tab = float(_per if _per is not None else (WALL_MM if WALL_MM else PL.p("共用", "墙厚")))
    _src = ("档案 墙厚_mm_按层[%s]=%s" % (floor, _per)) if _per is not None else WALL_SRC
    min_m2 = float(PL.p("共用", "房间_面积下限"))

    segs = segs_of_doc(doc, WALL_LAYER)
    pairs = list(wall_pairs(segs))
    peak, share, n_pairs = peak_of(pairs)
    meta = {"墙厚_表": t_tab, "墙厚_来源": _src,
            "墙厚_现算主峰": peak, "主峰占比": round(share, 3), "线对": n_pairs,
            "间距谱_前6": spectrum_top(pairs),       # ★ 判否也要留下谱 —— 否则「为什么否」无从复核
            "线段_失败": dict(SEG_FAIL)}            # 展平失败的图元（>0 ⇒ 这把尺子对那类图元是瞎的）
    tab_bin = round(t_tab / BIN_MM) * BIN_MM
    if not pairs or peak is None:
        meta["判否"] = "一线对都没配出来（对数 %d）⇒ 本层不出环，该下沉 L3/L4" % n_pairs
        return [], meta, doc, None
    if abs(peak - tab_bin) > PEAK_TOL_BINS * BIN_MM:
        meta["判否"] = ("线对主峰不在声明的墙厚上（对数 %d / 主峰 %s / 表厚 %s / 占比 %.0f%%）"
                        "⇒ 本层不出环，该下沉 L3/L4") % (n_pairs, peak, t_tab, 100 * share)
        return [], meta, doc, None

    quads = bands_from(pairs, peak, extend=BAND_EXTEND_MM)
    band = unary_union(quads)
    plate = plate_of(floor)
    if plate is None:
        meta["判否"] = "楼面 plate 为空 ⇒ 本层不出环"
        return [], meta, doc, None

    cols = block_boxes(doc, layer=COL_LAYER)
    doors = block_boxes(doc, prefix=DOOR_BLOCK)
    # ★ 洞口上限**从门块自己声明的宽度取**（最长边 P98），不打字；取 P98 不取 max ——
    #   一个离群块不许带飞判据（174）。门块是 **L0 块表**（`rebuild/识别方案.md` §0），
    #   零几何推理的计数真值：门的物理宽度就是它能开出的洞口的上限。
    side = sorted(max(b.bounds[2] - b.bounds[0], b.bounds[3] - b.bounds[1]) for b in doors)
    cap_mm = side[int(0.95 * (len(side) - 1))] if side else 0.0
    open_hi = (side[int(0.98 * (len(side) - 1))] + 2.0 * t_tab) if side else 0.0
    if CAP_OVERRIDE is not None:
        open_hi = CAP_OVERRIDE
    # 先算缝谱（**不含补条**，补条会把缝填掉）→ 接头缝半径 + 缝谱下界；再据此补洞口。
    r, gap_lo, _g_hi, g_all = junction_closer_r(unary_union([band] + cols), max(open_hi, cap_mm))
    hist = collections.Counter(int(d // 100.0) * 100 for d in g_all)   # 缝谱粗直方图（只看分簇，不改判据）
    plugs, plug_stat = bridges(quads, gap_lo, open_hi, t_tab, doors)

    block = unary_union([band] + [c for c in cols if not c.is_empty] + plugs)
    # ★ 接头缝闭运算：墙带在**每个接头处也被断开**（1层实测 ≤ 257 mm），并集合不上 ⇒ 必须闭一次。
    #   半径从本层缝谱的**空档**现算（`junction_closer_r`），洞口由 `bridges` 负责 —— 两把尺子不许混。
    if r > 0:
        block = block.buffer(r, join_style=2).buffer(-r, join_style=2).buffer(0)
    # —— 生长屏障（墙线，剔踏步后加粗半墙厚）——
    barriers, bstat = wall_barriers(path, doc, segs, t_tab)
    barriers = close_barrier(barriers, r)          # ★ 不闭合 ⇒ 墙与墙接头处漏缝，环照样跨墙合并
    meta["生长屏障"] = bstat
    left = plate.difference(block)
    # ★★ 2026-10-17：**屏障也是硬边界**（用户令「色块分界不贴墙/圆钝」）。
    #   只把屏障用在生长里（不参与切环）实测只把悬空长边从 16.7% 压到 14.5% —— 因为
    #   **一个环里 27 间房**这件事本身没变，容量波前还是在同一块空地上互相切，切出来的
    #   仍是圆钝/45° 的分界。把屏障从楼面里减掉之后，环 = **墙围合出来的那些口袋**，
    #   每间房拿到的是它自己的墙面轮廓 ⇒ 分界就是墙。
    if barriers:
        left = left.difference(unary_union(barriers))
    faces = [p for p in PL.polys_of(left) if p.geom_type == "Polygon" and not p.is_empty]
    keep = [p for p in faces if p.area / 1e6 >= min_m2]
    slivers = [p for p in faces if p.area / 1e6 < min_m2]
    meta.update({"seg": len(segs), "带": len(quads), "柱": len(cols), "门块": len(doors),
                 "洞口上限_mm": round(open_hi), "补洞": len(plugs), "门逐樘": dict(plug_stat),
                 "缝谱下界_mm": None if gap_lo is None else round(gap_lo),
                 "接头缝半径_mm": round(r),
                 "缝谱": dict(sorted(hist.items())),
                 "楼面_m2": round(plate.area / 1e6, 1),
                 "面_全部": len(faces), "面_合格": len(keep), "碎面": len(slivers),
                 "碎面_m2": round(sum(p.area for p in slivers) / 1e6, 2)})
    if debug:
        meta["_faces_all"] = faces
        meta["_quads"] = quads
        meta["_plate"] = plate
    return keep, meta, doc, barriers


# ----------------------------------------------------------------- 配对（带闸）
def pair(rings, txts):
    """环 × 文字 的**带闸配对**：包含 + 唯一。→ (认领表, 歧义表, 未认领文字)。"""
    claim = collections.defaultdict(dict)            # 环下标 → {类别: [文字…]}
    amb = []
    orphan = collections.defaultdict(list)
    for kind, items in txts.items():
        for it in items:
            pt = sg.Point(*it["xy"])
            owners = [i for i, p in enumerate(rings) if p.intersects(pt)]
            if len(owners) == 1:
                claim[owners[0]].setdefault(kind, []).append(it)
            elif len(owners) > 1:
                amb.append({"类": kind, "文": it["文"], "xy": it["xy"], "落在环数": len(owners)})
            else:
                orphan[kind].append(it)
    return claim, amb, orphan


# ------------------------------------- 房间地板面片：墙=硬边界 · 图上面积=容量
def _runs_boxes(mask, x0, y0, cell):
    """布尔格阵 → **行游程矩形**的并集。**不简化**：并集面积 = 格数×cell² 严格相等，可复算。"""
    boxes = []
    h, w = mask.shape
    for j in range(h):
        row = mask[j]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
            boxes.append(sg.box(x0 + s * cell, y0 + j * cell, x0 + e * cell, y0 + (j + 1) * cell))
    return unary_union(boxes) if boxes else None


def _parts(p):
    """任意(多)面 → 单面列表。★ 行游程并集**经常是 MultiPolygon**（交通片尤其）——
    这里一律摊开，**不许**只取一块把其余的静默丢掉。"""
    return PL.polys_of(p) if p.geom_type != "Polygon" else [p]


def _nearest_inside(inside, x0, y0, xy, cell, reach=400):
    """文字点 → 最近的「环内」格 (j, i)；找不到给 None（调用方**报数**，不许静默）。"""
    h, w = inside.shape
    ci, cj = int((xy[0] - x0) / cell), int((xy[1] - y0) / cell)
    for rr in range(0, reach):
        for dj in range(-rr, rr + 1):
            for di in range(-rr, rr + 1):
                if max(abs(di), abs(dj)) != rr:
                    continue
                j, i = cj + dj, ci + di
                if 0 <= i < w and 0 <= j < h and inside[j, i]:
                    return j, i
    return None


def grow_patches(rings, claim, cell_m=CELL_M, barriers=None):
    """房间地板面片 = 在**每个环内部**按**容量**（图上面积）做多源生长切出来的片。

    ★ 为什么必须这么切（本趟实证，写给下一个改这里的人）：
      1层 33 条面积文字**合计只有 2956 m²**，而楼面 7006 m² —— **58% 的地面没有任何房间标注**
      （走廊/门厅/中庭/楼梯间）。先做过「把整块自由面强制分给种子」的分水岭法：一间 11.96 m² 的房
      抢到 333 m²（**28 倍**）—— 那 58% 被平摊到各家头上了。**错的不是方法，是题设。**
      ⇒ 容量 = 图纸自己写的面积（L2 的第三方真值）；墙 = **硬边界**（生长永不跨环）。
        吃满自己那份就停；环里剩下的格 = **交通空间**，单独成片。

    ★ 对账必须分两种情形报，否则是自证（铁律 192）：
      · 环比容量**小** ⇒ 贴墙自然停 ⇒ 算得面积是**真盖章**（`情形=墙定`）；
      · 环比容量**大** ⇒ 被容量裁停 ⇒ 面积对上是**平凡的**，必须连 `环内可容_m2` 一起报才看得见漏。

    ★ `barriers`（`wall_barriers()` 的输出，可省）＝**墙线当屏障**：落进屏障的格记 `lab=-2`，
      既不算房间、也不算交通。没有它，一个环里 27 间房就是在**同一块空地**上按容量冲波前
      ⇒ 圆钝色块 / 45° 台阶 / 假分界（2026-10-17 用户报的就是这个）。
      屏障**不改变环的形状**（环还是 plate − block）——它只挡生长，所以「墙定」片与环的关系一字不动。

    → (房间片列表, 交通片列表, 读数)
    """
    rooms_out, roads, stat = [], [], collections.Counter()
    bar_parts = PL.polys_of(barriers) if barriers is not None else []   # 屏障可能是一整块 MultiPolygon
    tree = STRtree(bar_parts) if bar_parts else None     # 一次建树，每个环只查自己那一框

    def _fields(p):
        ext = [(round(x, 1), round(y, 1)) for x, y in p.exterior.coords]
        return {"轮廓顶点数": len(ext), "中心xy": [round(p.centroid.x, 1), round(p.centroid.y, 1)],
                "轮廓xy_mm": [list(v) for v in ext],
                "洞xy_mm": [[(round(x, 1), round(y, 1)) for x, y in r.coords] for r in p.interiors]}

    for i, ring in enumerate(rings):
        a_ring = ring.area / 1e6
        got = claim.get(i, {})
        seeds = []
        for it in got.get("面积", []):
            a = parse_area(it["文"])
            if a:
                seeds.append({"面积": a, "xy": it["xy"], "房间号": None, "用途": None, "单位": None})
        # ★ 四件套在图上是**四条独立的 TEXT**，各带自己的 xy。按「环」取 `[0]` 会把**整环 27 间房**
        #   统统贴上同一个房号 —— 本趟就是这么错了一次（铁律 196：收口共用函数时主语被悄悄换掉）。
        #   改成**按点一对一贪心**：图上实测 房间号 650mm / 用途 1300mm / 单位 1950mm 严丝合缝；
        #   贪心保证**一对一**（174：同一个量的两个估计器，只能活下来一个）。
        for kind in ("房间号", "用途", "单位"):
            B = got.get(kind, [])
            cand = sorted((math.dist(s["xy"], b["xy"]), si, bj)
                          for si, s in enumerate(seeds) for bj, b in enumerate(B))
            taken_s, used_b = set(), set()
            for d, si, bj in cand:
                if si in taken_s or bj in used_b:
                    continue
                taken_s.add(si)
                used_b.add(bj)
                seeds[si][kind] = B[bj]["文"]
            stat["配_" + kind] += len(taken_s)       # ★ 必须 `+=`：`=` 会被下一个环覆盖，印出来是最后一环的数

        def _name(sd):
            return {k: sd[k] for k in ("房间号", "用途", "单位")}

        if not seeds:                                   # 无标注 ⇒ 整环就是交通空间
            roads.append({"属于环": i, "算得面积_m2": round(a_ring, 3), **_fields(ring)})
            stat["环_无标注→整环交通"] += 1
            continue
        if len(seeds) == 1 and a_ring <= seeds[0]["面积"] * (1 + 1e-9):
            # 贴墙自然停 ⇒ 整环就是这间房。用环本身出片（**无栅格台阶**，面积由墙定）
            a = seeds[0]["面积"]
            rooms_out.append({**_name(seeds[0]), "图上面积_m2": round(a, 3),
                              "算得面积_m2": round(a_ring, 3), "差_m2": round(a_ring - a, 3),
                              "情形": "墙定", "环内可容_m2": round(a_ring, 3), "同环房间数": 1,
                              "超出_m2": 0.0,
                              "种子xy": [round(seeds[0]["xy"][0], 1), round(seeds[0]["xy"][1], 1)],
                              **_fields(ring)})
            stat["墙定"] += 1
            continue
        # —— 环比容量大 / 被多间共用 ⇒ 上栅格，按容量切 ——
        # ★ 图纸坐标是 **mm** ⇒ 栅格边长也必须换成 mm（`CELL_M` 是米，这里 ×1000）。
        #   本行错过一次：拿 mm 的 bounds 除 0.1 ⇒ 网格 108 万 × 80 万格，numpy 报「要 7.53 TiB」。
        cell = cell_m * 1000.0
        x0, y0, x1, y1 = ring.bounds
        w = int(math.ceil((x1 - x0) / cell)) + 1
        h = int(math.ceil((y1 - y0) / cell)) + 1
        gx, gy = np.meshgrid(x0 + (np.arange(w) + 0.5) * cell, y0 + (np.arange(h) + 0.5) * cell)
        inside = shapely.contains_xy(ring, gx.ravel(), gy.ravel()).reshape(h, w)
        ca = cell * cell
        # ★★ 2026-10-17 **容量仍是面积上限**（这是面积对账的根，放开它 1 层实测 6 间房超差 >50%，
        #   教师活动室 64 m² 被算成 1334 m² —— 中央大厅被它吞了）。用户要的「分界贴墙」由
        #   **排队方式**（下面按清距的分水岭）拿回来，不靠放开容量。
        budget = [max(1, int(round(s["面积"] * 1e6 / ca))) for s in seeds]
        lab = np.full((h, w), -1, np.int32)              # -1 空格 · -2 屏障（墙线上）· ≥0 房号
        if tree is not None:
            # ★ 只把**这一框**里的墙线并起来再判，不拿全楼的屏障去扫每个格（12 层实测 2000 条线/层）。
            near = unary_union([bar_parts[i] for i in tree.query(sg.box(x0, y0, x1, y1))])
            if not near.is_empty:
                blocked = shapely.contains_xy(near, gx.ravel(), gy.ravel()).reshape(h, w)
                lab[blocked] = -2
                stat["格_屏障"] += int(blocked.sum())
        grow = inside & (lab == -1)                      # 可生长的格 = 环内 且 不在屏障上
        # ★★ 2026-10-17 **分水岭优先**（用户令「色块分界不贴墙/圆钝」）。
        #   两版旧法的病灶（实测 `demo/_shots/pads-plan-2026-10-17.png`）：
        #     · 4 邻域先进先出 → 等值线是**曼哈顿菱形**，两个种子相遇处是 45° 台阶（斜切）；
        #     · 按「到种子的欧氏距离」排 → 相遇处是**圆弧**（正是「圆钝色块」四个字）。
        #   现在按「**离墙多远**」排队（离墙越远越先占）：房间中央开阔、门洞是个**窄喉**，
        #   于是两间房的分界正好落在**门洞那条窄缝**上，走廊与房间的分界也落在门洞/洞口上
        #   —— 这就是分水岭（watershed）在平面图上的标准用法，分界**贴着通道走**，
        #   不再是从种子画圆。屏障仍是硬边界（只往 `grow` 里推），墙在的地方还是墙说了算。
        from scipy import ndimage as _ndi
        clear = _ndi.distance_transform_edt(grow)     # 到最近「非可生长格」的欧氏距离（格）
        stat["清距_max"] = round(float(clear.max()), 1)
        q = []
        # ★ 种子**先占地再放水**（marker-controlled）：不先占，邻居那盆水清距更高会先把
        #   种子自己那格抢走 ⇒ 这间房被挤成十几平米（1 层实测 6-B-01-10 图上 185.34 → 算得 17.64）。
        #   先占之后，种子格永不被别人抢，房至少有一块自己的芯。
        for k, s in enumerate(seeds):
            hit = _nearest_inside(grow, x0, y0, s["xy"], cell)
            if not hit:                                  # 种子恰好落在墙上 ⇒ 退回环内最近格（报数，不静默）
                hit = _nearest_inside(inside, x0, y0, s["xy"], cell)
                if hit:
                    stat["种子落进屏障"] += 1
            if not hit:
                stat["种子落不进环"] += 1
                continue
            if lab[hit[0], hit[1]] != -1:                 # 两个房号扎在同一格：后来的那个报出来
                stat["种子撞格"] += 1
                continue
            lab[hit[0], hit[1]] = k
            budget[k] -= 1
            for dj, di, _st in ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                                (1, 1, 1.4142135623730951), (1, -1, 1.4142135623730951),
                                (-1, 1, 1.4142135623730951), (-1, -1, 1.4142135623730951)):
                jj, i2 = hit[0] + dj, hit[1] + di
                if 0 <= jj < h and 0 <= i2 < w and grow[jj, i2] and lab[jj, i2] == -1:
                    heapq.heappush(q, (-float(clear[jj, i2]), _st, jj, i2, k))
        NB8 = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
               (1, 1, 1.4142135623730951), (1, -1, 1.4142135623730951),
               (-1, 1, 1.4142135623730951), (-1, -1, 1.4142135623730951))
        while q:
            _p, d, j, ii, k = heapq.heappop(q)
            if lab[j, ii] != -1 or budget[k] <= 0:
                continue
            lab[j, ii] = k
            budget[k] -= 1
            for dj, di, step in NB8:
                jj, i2 = j + dj, ii + di
                if 0 <= jj < h and 0 <= i2 < w and grow[jj, i2] and lab[jj, i2] == -1:
                    # 主键 = 离墙距离（远的先占）；次键 = 到种子的路长（同清距时选近的，块不外翻）
                    heapq.heappush(q, (-float(clear[jj, i2]), d + step, jj, i2, k))
        # —— 屏障带回填 ——
        # 屏障只该**挡生长**，不该在地面上留一条缝：生长结束后把屏障格按最近的四邻已标注格
        # 回填（房间/交通都可能）。一堵 240 墙的屏障带 480 宽 ⇒ 分界落在墙中心线，两边各退半步。
        # ★ 不回填的代价是实测出来的：1 层屏障占 784 m²，地垫并集从 5385.9 掉到 5139.6 m²
        #   （覆盖率 94.3% → 90.0%），用户看到的「地面有一块块空」正是它。
        # ★ 回填**只进 inside 的屏障格**，绝不进其它空格 —— 否则等于让房间穿过墙。
        n_bar = int((lab == -2).sum())
        while True:
            changed = False
            for dj, di in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                src = np.full_like(lab, -1)
                j0, j1 = max(0, dj), h + min(0, dj)
                i0, i1 = max(0, di), w + min(0, di)
                src[j0:j1, i0:i1] = lab[j0 - dj:j1 - dj, i0 - di:i1 - di]
                take = (lab == -2) & (src >= 0) & inside
                if take.any():
                    lab[take] = src[take]
                    changed = True
            if not changed:
                break
        stat["格_屏障回填"] += n_bar - int((lab == -2).sum())
        # —— 剪尾（2026-10-17）———————————————————————————————————————————————
        # 容量裁停切出来的那一截常是一条**细长尾巴**：从门洞钻进走廊、顺着走廊往前顶，
        # 直到面积花完才停。它不是墙围出来的，也不是分水岭分的，纯粹是「预算还没花完」画的。
        # `_scratch/_wshed_f1.png` 里从左中一路伸到右边的洋红细条就是它。
        # 做法＝**开运算再长回原片内**：窄于 TAIL_MIN_M 的细条整条消失，正常房间的厚度
        # （≥1.5 m）一点不少，墙角只被啃掉不到半个阈值。削掉的格落回 -1 ⇒ 算交通，不藏。
        if TAIL_MIN_M > 0:
            kk = max(1, int(round(TAIL_MIN_M / cell)))
            _yy, _xx = np.mgrid[-kk:kk + 1, -kk:kk + 1]
            _disk = (_xx * _xx + _yy * _yy) <= kk * kk
            n_tail = 0
            for k in range(len(seeds)):
                m = lab == k
                if not m.any():
                    continue
                opn = _ndi.binary_opening(m, structure=_disk)
                if not opn.any():
                    continue
                back = _ndi.binary_dilation(opn, structure=_disk) & m
                drop = m & ~back
                if drop.any():
                    lab[drop] = -1
                    n_tail += int(drop.sum())
            stat["格_剪尾"] += n_tail
        a_stated = sum(s["面积"] for s in seeds)
        for k, s in enumerate(seeds):
            m = lab == k
            if not m.any():
                stat["片为空"] += 1
                continue
            poly = _runs_boxes(m, x0, y0, cell)
            if poly is None or poly.is_empty:
                stat["片退化"] += 1
                continue
            a = s["面积"]
            a_calc = int(m.sum()) * ca / 1e6
            bits = _parts(poly)                          # 一片房**不该**是散的；散了就报出来
            big = max(bits, key=lambda p: p.area)
            rooms_out.append({**_name(s), "图上面积_m2": round(a, 3), "算得面积_m2": round(a_calc, 3),
                              "差_m2": round(a_calc - a, 3), "情形": "容量裁停",
                              "环内可容_m2": round(a_ring, 3), "同环房间数": len(seeds),
                              "超出_m2": round(a_ring - a_stated, 3),
                              "碎块": len(bits) - 1,
                              "碎块_m2": round(sum(p.area for p in bits if p is not big) / 1e6, 3),
                              "种子xy": [round(s["xy"][0], 1), round(s["xy"][1], 1)], **_fields(big)})
            if len(bits) > 1:
                stat["片是散的"] += 1
            stat["容量裁停"] += 1
        lab[(lab == -2) & inside] = -1                  # 回填不到的死角（墙交汇处）兜底算交通，不留洞
        road = inside & (lab == -1)
        if road.any():
            rp = _runs_boxes(road, x0, y0, cell)
            if rp is not None and not rp.is_empty:
                for q in _parts(rp):                     # 交通块本来就常是散的 ⇒ 一块一条
                    roads.append({"属于环": i, "算得面积_m2": round(q.area / 1e6, 3), **_fields(q)})
                stat["环内余格→交通片"] += 1
    return rooms_out, roads, stat


def build(floor):
    rings, meta, doc, barriers = rooms(floor)
    txts = texts(doc)
    claim, amb, orphan = pair(rings, txts)
    patches, roads, gstat = grow_patches(rings, claim, barriers=barriers)

    a = sorted(p.area / 1e6 for p in rings)
    wall = [r for r in patches if r["情形"] == "墙定"]
    cut = [r for r in patches if r["情形"] == "容量裁停"]

    def _agree(rs):
        return sum(1 for r in rs if r["图上面积_m2"]
                   and abs(r["差_m2"]) / r["图上面积_m2"] <= TOL_REL)

    no_area = [i for i, p in enumerate(rings) if not claim.get(i, {}).get("面积")]
    multi = [{"环": i, "间数": len(claim[i]["面积"])} for i in claim if len(claim[i].get("面积", [])) > 1]
    return {
        "层": floor,
        "环": len(rings),
        "环面积_m2": None if not a else {"min": round(a[0], 2), "中位": round(a[len(a) // 2], 2),
                                       "max": round(a[-1], 2), "合计": round(sum(a), 1)},
        "读数": meta,
        "文字数": {k: len(txts.get(k, [])) for k in KINDS},
        "配上": {k: sum(1 for r in patches if r.get(k)) for k in ("房间号", "用途", "单位", "图上面积_m2")},
        "房间": patches,                              # ★ 下游做地板面片直接用 `轮廓xy_mm`
        "交通空间": roads,                            # ★ 未标注的那 58%：走廊/门厅/中庭/楼梯间
        "生长": {
            "片_墙定": len(wall), "片_容量裁停": len(cut), "片_合计": len(patches),
            "墙定_面积一致": _agree(wall), "墙定_超差": len(wall) - _agree(wall),
            "容量裁停_面积一致": _agree(cut),
            "交通片": len(roads), "交通面积_m2": round(sum(r["算得面积_m2"] for r in roads), 1),
            "房间面积合计_m2": round(sum(r["图上面积_m2"] for r in patches if r["图上面积_m2"]), 1),
            "格_屏障": gstat.get("格_屏障", 0),      # 被墙线屏障挡掉的格数（读数：挡了多少地面，不判好坏）
            "逐档": dict(gstat),
        },
        "未配对": {
            "环_无面积文字": no_area,
            "环_多间房（已按容量切开）": multi,
            "文字_无主": {k: v for k, v in orphan.items() if v},
            "歧义": amb,
        },
        "交叉核": {"环面积合计_m2": round(sum(a), 1),
                   "图上面积合计_m2": round(sum(c for c in
                                            (parse_area(x["文"]) for x in txts.get("面积", [])) if c), 1)},
        # ★ 口径**只算「墙定」片**（贴墙自然停）：容量裁停片的面积对上是平凡的（容量就是图上面积），
        #   拿它充数＝自证（铁律 192）。裁停片的真实信息在 `生长` 里的「环内可容_m2 / 超出_m2」。
        "面积核对": {"口径": "只算「墙定」片（贴墙自然停）；容量裁停片单列在「生长」里",
                   "比对上": len(wall), "一致": _agree(wall), "超差": len(wall) - _agree(wall)},
    }


def fingerprint():
    """输入指纹：12 张图的 (名, 字节数, mtime) → sha256。**不是日期**，只用来判「同趟」。"""
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(RAW, "*.dxf"))):
        st = os.stat(p)
        h.update(("%s|%d|%d;" % (os.path.basename(p), st.st_size, int(st.st_mtime))).encode("utf-8"))
    return h.hexdigest()


# ----------------------------------------------------------------- 报表
def report(tables):
    print("%-8s %5s %5s %5s %5s %5s | %6s %6s %6s | %5s %5s %5s | 未配对（环无面积/文字无主/歧义）" %
          ("层", "环", "面积", "房间号", "用途", "单位", "墙厚表", "现算峰", "峰占比",
           "比上", "一致", "超差"))
    for t in tables:
        u = t["未配对"]
        r = t["读数"]
        pk = r.get("墙厚_现算主峰")
        print("%-8s %5d %5d %5d %5d %5d | %6s %6s %6s | %5d %5d %5d | %d / %d / %d" %
              (t["层"], t["环"], t["文字数"]["面积"], t["文字数"]["房间号"],
               t["文字数"]["用途"], t["文字数"]["单位"],
               r.get("墙厚_表"), ("%.0f" % pk) if pk else "—",
               ("%.0f%%" % (100 * r.get("主峰占比", 0))) if r.get("主峰占比") else "—",
               t["面积核对"]["比对上"], t["面积核对"]["一致"], t["面积核对"]["超差"],
               len(u["环_无面积文字"]),
               sum(len(v) for v in u["文字_无主"].values()), len(u["歧义"])))

    print("\n★ 判否的层（线对主峰不成立 ⇒ 该下沉 L3/L4，不硬凑）：")
    no = [t for t in tables if t["读数"].get("判否")]
    for t in no:
        print("   %-8s %s" % (t["层"], t["读数"]["判否"]))
    if not no:
        print("   （无）")

    print("\n★ 墙厚：表值 vs 本层现算主峰（不一致 ⇒ 同一个量两个估计器，必须点名）：")
    mism = [t for t in tables if t["读数"].get("墙厚_现算主峰") is not None
            and abs(t["读数"]["墙厚_现算主峰"] - t["读数"]["墙厚_表"]) > 1e-6]
    for t in mism:
        r = t["读数"]
        print("   %-8s 表 %.0f vs 现算主峰 %.0f（占比 %.0f%%，线对 %d）"
              % (t["层"], r["墙厚_表"], r["墙厚_现算主峰"], 100 * r["主峰占比"], r["线对"]))
    if not mism:
        print("   （无）")

    print("\n★ 三个现算阈值（全部从本层实测取，不许打字；空档=缝谱上接头缝簇与洞口簇的分界）：")
    for t in tables:
        r = t["读数"]
        if r.get("判否"):
            print("   %-8s —（判否，没走到缝环）" % t["层"])
            continue
        st = r.get("门逐樘", {})
        print("   %-8s 线对 %4d → 带 %4d｜缝宽闸 (%s, %s] mm → 补洞 %3d 条｜接头缝半径 %s mm"
              % (t["层"], r["线对"], r["带"], r["缝谱下界_mm"], r["洞口上限_mm"],
                 r["补洞"], r["接头缝半径_mm"]))
        if st:
            print("            └─ 对数（门是 L0 块表真值，只用来核机制，不参与判据）："
                  "门块 %s 樘｜补条压在门上的 %s 条｜补条上没门 %s 条｜成品退化 %s 条"
                  % (st.get("樘"), st.get("门上有补条"), st.get("补条没门"), st.get("成品退化")))

    print("\n★ 交叉核（两个独立来源：现算环面积合计 vs 图上 `5面积` 合计）：")
    for t in tables:
        c = t["交叉核"]
        print("   %-8s 环 %8.1f m² vs 图上 %8.1f m² ⇒ 差 %+9.1f"
              % (t["层"], c["环面积合计_m2"], c["图上面积合计_m2"],
                 c["环面积合计_m2"] - c["图上面积合计_m2"]))

    print("\n★ 房间表口径（墙 = 硬边界，图上 `5面积` = 容量；见 rebuild/识别方案.md §3-L2）：")
    for t in tables:
        if t["读数"].get("判否"):
            continue
        g = t["生长"]
        print("   %-8s 片 %3d = 墙定 %3d + 容量裁停 %3d｜交通片 %3d（%7.1f m²）"
              "｜图上面积合计 %7.1f m² / 楼面 %s m²"
              % (t["层"], g["片_合计"], g["片_墙定"], g["片_容量裁停"],
                 g["交通片"], g["交通面积_m2"], g["房间面积合计_m2"], t["读数"]["楼面_m2"]))
        print("            └─ ★★**真盖章只数「墙定」**：贴墙自然停 %d 间 → 面积（相对 %d%%）一致 %d 间、超差 %d 间"
              % (g["片_墙定"], int(TOL_REL * 100), g["墙定_面积一致"], g["墙定_超差"]))
        print("            └─ 容量裁停 %d 间：面积对上是**平凡**的（容量就是图上面积）⇒ 真信息是「环内可容」超出多少"
              % g["片_容量裁停"])
        if g["逐档"]:
            print("            └─ 逐档：%s" % g["逐档"])

    print("\n★ 环里塞了几间（**合并的显证**：一个环装下多间房 ⇒ 那几间没被墙隔开，靠容量切）：")
    for t in tables:
        if t["读数"].get("判否"):
            continue
        mm = t["未配对"]["环_多间房（已按容量切开）"]
        print("   %-8s 多间环 %2d 个（最多一个装 %s 间）｜无标注环 %d 个"
              % (t["层"], len(mm), max((m["间数"] for m in mm), default=0),
                 len(t["未配对"]["环_无面积文字"])))

    print("\n★ 容量裁停的片里「环内容得下 vs 图上合计」差得最多的（**漏的显证**，点名）：")
    rows = sorted(((r["超出_m2"], t["层"], r) for t in tables for r in t["房间"]
                   if r["情形"] == "容量裁停"), key=lambda z: z[0], reverse=True)
    for ex, fl, r in rows[:10]:
        print("   %-8s %-12s 图上 %7.2f  环内容得下 %8.2f  超出 %+9.2f m²  同环 %d 间"
              % (fl, r["房间号"] or "—", r["图上面积_m2"], r["环内可容_m2"], ex, r["同环房间数"]))
    if not rows:
        print("   （无）")

    print("\n★ 墙定片里的面积超差（相对 > %d%%，点名不汇总）：" % int(TOL_REL * 100))
    bad = [(t["层"], r) for t in tables for r in t["房间"]
           if r["情形"] == "墙定" and abs(r["差_m2"]) / r["图上面积_m2"] > TOL_REL]
    for fl, r in bad:
        print("   %-8s %-14s %-10s 图上 %8.2f  算得 %8.2f  差 %+7.3f m²  中心 %s" %
              (fl, r["房间号"] or "—", (r["用途"] or "—")[:8],
               r["图上面积_m2"], r["算得面积_m2"], r["差_m2"], r["中心xy"]))
    if not bad:
        print("   （无）")


def main(argv):
    global BAND_EXTEND_MM, CAP_OVERRIDE, BRIDGE_NOGATE   # noqa: PLW0603 —— 只为诊断期扫参数，不改别的
    global WALL_MM, WALL_SRC, WALL_MM_BY_FLOOR           # noqa: PLW0603
    for a in argv:
        if a.startswith("--extend="):
            BAND_EXTEND_MM = float(a.split("=", 1)[1])
        elif a.startswith("--cap="):
            CAP_OVERRIDE = float(a.split("=", 1)[1])
        elif a == "--nogate":
            BRIDGE_NOGATE = True
    floors = [a for a in argv if not a.startswith("--")] or \
             [os.path.splitext(os.path.basename(p))[0] for p in sorted(glob.glob(os.path.join(RAW, "*.dxf")))]
    WALL_MM, WALL_SRC = resolve_wall(floors)
    _by = (B.profile() or {}).get("墙厚_mm_按层") or {}
    WALL_MM_BY_FLOOR = {str(k): float(v) for k, v in _by.items()}
    print("★ 本栋墙厚：%s" % WALL_SRC)
    if WALL_MM_BY_FLOOR:
        print("★ 按层墙厚（档案声明，逐层覆盖）：%s"
              % " ".join("%s=%.0f" % (k, v) for k, v in sorted(WALL_MM_BY_FLOOR.items())))
    tables = [build(f) for f in floors]
    doc = {"指纹": fingerprint(), "墙厚_mm": WALL_MM, "墙厚_来源": WALL_SRC,
           "墙厚_mm_按层": WALL_MM_BY_FLOOR or None,
           "层数": len(tables), "层": tables}
    if "--no-write" in argv:
        print("（--no-write：本轮只读数，不落盘）")
    else:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
    report(tables)
    print("\n落盘 %s（指纹 %s…）" % (OUT, doc["指纹"][:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
