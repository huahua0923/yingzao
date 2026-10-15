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
  ⑫ 同一 `(层, 类)` 内多边形**互不重叠**（共面 ⇒ 在 SU 里会互相切面，切出的碎面导出后不成组）。
  ⑬ 每层 `COL` 条数 == 该层源图柱块 `_FZHK`/`_YZHK` 的 `INSERT` 数。
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
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = r"D:\项目\cdut3d"
SU = os.path.join(ROOT, "rebuild", "06_su")
CONT = os.path.join(SU, "contours")
IDX = os.path.join(CONT, "index.json")
RAW = os.path.join(ROOT, "rebuild", "01_cad", "raw")
PARAM = os.path.join(ROOT, "rebuild", "构件库", "参数.json")
HERE = os.path.dirname(os.path.abspath(__file__))
RUNDIR = os.path.join(HERE, "_out")
JSON_OUT = os.path.join(RUNDIR, "J-10.8-00.json")
_LOG = []
_MEAS = {}

LAYERS = ("WALL", "COL", "LIFT", "SLAB", "DOOR", "STAIR", "LINTEL",
          "PARAPET", "ROOF_STAIR", "ROOF_STEP", "ROOF")
# ★ 2026-10-15 加 `ROOF`（塔楼屋面板，十→十一）：`build3d.py:957` 早就建了它，
#   但 `export_contours.py` 的枚举里没有 ⇒ 它一直没被发出去、正式件顶上 911 m² 是空的
#   （用户「楼板要画」）。这条判据是**进 SU 之前的接口门**，枚举不跟着长，
#   下游按类全失效且**不报错**（铁律 158）。
# 逐块高度不同的类 —— 只有它们可以带 `h`。**这是声明**：上游若合法地需要别的类逐块拉伸，
# 连同理由一起加进来，不许默默放宽成「带了就带了」。
# ★ 2026-10-15 加 `LINTEL`（门头墙），理由：它的 `h = 层高 − 门洞高`、底面恒在门洞高上，
#   逐块由 `parts_lib.lintel_module` 算出来带着走 —— 与 `STAIR` 同型（不是放宽，是同一种件）。
H_CLASSES = ("STAIR", "LINTEL")
FLOORS = ["地下1层"] + ["%d层" % n for n in range(1, 12)]
COL_BLOCKS = ("_FZHK", "_YZHK")
DOOR_BLOCK = "$DORLIB2D$"

RES_MM = 25.0                        # 与 recognize.py::RES 同源（栅格分辨率）
EDGE_MIN_MM = RES_MM / 4.0           # 6.25   —— 实测最短边 12.0000 mm
AREA_MIN_MM2 = RES_MM * RES_MM / 4.0     # 156.25 —— 实测最小面积 1250.000 mm²
Z_SLOP_MM = 1.0                      # 只兜浮点尾数，不放宽「相对/绝对」这条
OVERLAP_EPS_MM2 = 1.0                # 万分之一平米；比它小的重叠算浮点噪声

BLIND = [
    "量不到「SU 建得对不对」（单位/朝上轴/逐层层带/顶部三件标高/导出朝向）——那是 J-10.8-02 的事",
    "量不到「判断本身对不对」：墙认错了没有、楼梯井归并对不对、门位置准不准；"
    "⑬ 只覆盖柱这一类的**条数**（不是位置）",
    "门：源件 $DorLib2D$ 按块、这里按环 ⇒ 两把尺子不同源，只打印不判",
    "EDGE_MIN_MM / AREA_MIN_MM2 的来源是本仓当前这份数据的分布；上游若合法地产生更小的件，"
    "两个常数要连着读数一起改，不许只改常数",
    "⑮ 的 JSON 与 DXF 是同一段代码写的 ⇒ 只抓写出过程丢件，抓不到判断本身错",
    "② 比的是同一段代码写的两份自报表 ⇒ 抓 index 过期，抓不到两份一起错",
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


def src_col_counts():
    """源图逐层柱块 `INSERT` 数（⑬ 的**件外参照**）。"""
    return {fl: _insert_names(os.path.join(RAW, fl + ".dxf"), COL_BLOCKS) for fl in FLOORS}


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


def judge(data, src_col, dxf_by, meas=None):
    """返回违反串列表（空 = 合格）。**只读 `data`**，件侧一个数都不落盘。"""
    bad = []
    idx_by = {r.get("floor"): r for r in data["_index"]}

    for fl in FLOORS:                                                  # ②
        bad += _head_bad(fl, data[fl], idx_by.get(fl))

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
                bad.append("③ %s/%s 的 layer=%r 不在十一类枚举里" % (fl, pid, lay))
                continue
            per_cls[lay] = per_cls.get(lay, 0) + 1

            z = pr.get("z")                                            # ④
            if not isinstance(z, (int, float)) or not math.isfinite(float(z)):
                bad.append("④ %s/%s 的 z=%r 不是有限数" % (fl, pid, z))
            elif not (-Z_SLOP_MM <= float(z) <= h_mm + Z_SLOP_MM):
                bad.append("④ %s/%s 的 z=%.1f mm 不在 [0, %.1f] —— 十有八九把**绝对**标高写进来了"
                           "（两个原点相加，实测总高 50.5 → 90.5 m）" % (fl, pid, float(z), h_mm))

            if pr.get("h") is not None:                                # ⑤
                hv = pr["h"]
                if lay not in H_CLASSES:
                    bad.append("⑤ %s/%s 的 layer=%s 带了 `h=%r` —— 只有 %s 可以逐块给高度，"
                               "其余各类带了就会盖掉按层常数"
                               % (fl, pid, lay, hv, list(H_CLASSES)))
                elif not isinstance(hv, (int, float)) or not math.isfinite(float(hv)) \
                        or float(hv) <= 0:
                    bad.append("⑤ %s/%s 的 h=%r 不是有限正数" % (fl, pid, hv))

            if pr.get("holes"):                                        # ⑥
                bad.append("⑥ %s/%s 带了 %d 个洞 —— SU 侧抠洞三条路全不通，洞必须在 Python 侧切掉"
                           % (fl, pid, len(pr["holes"])))

            ring = pr.get("ring") or []
            if any(not isinstance(c, (int, float)) or not math.isfinite(float(c))
                   for p in ring for c in p):                          # ⑦
                bad.append("⑦ %s/%s 的环上有非有限数（nan/inf 落盘后浏览器 JSON.parse 抛错 ⇒ 白屏）"
                           % (fl, pid))
                continue

            body = [tuple(float(c) for c in p) for p in ring]           # ⑧
            while len(body) > 1 and body[0] == body[-1]:
                body.pop()          # 上游有意保留的**收口点**，先剥掉再判，不许报成重复点
            dup = [i for i in range(len(body) - 1) if body[i] == body[i + 1]]
            if dup:
                bad.append("⑧ %s/%s 的环上有 %d 处相邻重复点（第一处在下标 %d）—— "
                           "SU 建不出长度 0 的边 ⇒ 静默少一张面 / 甚至自旋挂死"
                           % (fl, pid, len(dup), dup[0]))
            if len(body) != len(set(body)):
                bad.append("⑧ %s/%s 的环上有**非相邻**重复点（%d 个点只有 %d 个互异）"
                           % (fl, pid, len(body), len(set(body))))

            rr = clean_ring(body)                                      # ⑨ = SU 口径
            if len(rr) < 3:
                bad.append("⑨ %s/%s 按 SU 口径只剩 %d 个互异点（<3 建不出面）" % (fl, pid, len(rr)))
                continue
            try:
                from shapely.geometry import LinearRing                # ⑩
                if not LinearRing(rr + [rr[0]]).is_simple:
                    bad.append("⑩ %s/%s 的环自交（8 字/蝴蝶结），SU 成不了面或出歪面" % (fl, pid))
            except Exception as e:                                     # noqa: BLE001
                bad.append("⑩ %s/%s 判自交时抛异常：%s" % (fl, pid, e))
            ar = ring_area(rr)                                         # ⑪
            a_min.append(ar)
            if ar < AREA_MIN_MM2:
                bad.append("⑪ %s/%s 的环面积 %.3f mm² < %.2f（阈值 = RES²/4；实测最小 1250.000）"
                           % (fl, pid, ar, AREA_MIN_MM2))
            em = min(math.hypot(rr[(i + 1) % len(rr)][0] - rr[i][0],
                                rr[(i + 1) % len(rr)][1] - rr[i][1]) for i in range(len(rr)))
            e_min.append(em)
            if em < EDGE_MIN_MM:
                bad.append("⑪ %s/%s 的最短边 %.3f mm < %.2f（阈值 = RES/4；实测最短 12.0000）"
                           % (fl, pid, em, EDGE_MIN_MM))
            if lay == "COL":
                col_n += 1

        bad += _overlap_bad(fl, d["polys"])                            # ⑫

        s = src_col.get(fl)                                            # ⑬
        if s is None:
            bad.append("⑬ %s 的源图柱块数**没量到**（源图不在或读不开）—— 不许当成相等" % fl)
        elif col_n != s:
            bad.append("⑬ %s 的 COL 条数 %d ≠ 源图柱块 INSERT 数 %d（差 %+d）"
                       % (fl, col_n, s, col_n - s))

        by = dxf_by.get(fl)                                            # ⑮
        want = {}
        for pr in d["polys"]:
            want[pr["layer"]] = want.get(pr["layer"], 0) + 1 + len(pr.get("holes") or [])
        if by is None:
            bad.append("⑮ %s 的 contours/<层>.dxf 读不到（两份件本应同源）" % fl)
        elif by != want:
            bad.append("⑮ %s 的 JSON 逐类 %s ≠ DXF 闭合环 %s（同一段代码写出的两份件不同源）"
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
    return bad


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
        by.setdefault(pr["layer"], []).append(pr)
    out = []
    n = 0
    for lay, arr in by.items():
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
                        out.append("⑫ %s/%s 与 %s 重叠 %.3f mm²（同层同类共面 ⇒ SU 里会互相切面）"
                                   % (fl, rings[i][0], rings[j][0], inter))
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


def _mut(data, fn, fl="1层", i=0):
    d = copy.deepcopy(data)
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


def _drop_one_col(d, fl="1层"):
    """从某层删掉**最后一条** COL（就地改，返回是否删掉了）。"""
    idx = [i for i, p in enumerate(d[fl]["polys"]) if p["layer"] == "COL"]
    if not idx:
        return False
    d[fl]["polys"].pop(idx[-1])
    return True


def _bad_units(d, fl="1层", v="m"):
    d[fl]["units"] = v


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


def main():
    try:
        data = load()
    except Missing as e:
        log("SKIP：%s —— 「没量到」，不算过、也不假报成 FAIL（铁律 199）" % e)
        return _write(4)

    src_col = src_col_counts()
    dxf_by = dxf_ring_counts()
    ndoor = src_door_total()

    log("入口件：%s" % CONT)
    log("  ★ 本闸量的是**进 SU 之前的输入**，与 J-10.8-01（参照件）/ -02（正式件）量的东西不同，"
        "三者都要留")
    log("  ★ 件外参照（⑬）：源图柱块 `%s*` 合计 %s 个；门块 `%s*` 合计 %d 个"
        "（**只打印不判** —— 源件按块、这里按环，两把尺子不同源）"
        % ("/".join(COL_BLOCKS), sum(v for v in src_col.values() if v) or "没量到",
           DOOR_BLOCK, ndoor))
    # ★ 字面的百分号必须写 `%%` —— 写 `1% 分位` 时 Python 把 `% ` 当转换符，
    #   报 `unsupported format character`，而且**崩在最后一行**（前面全跑完）⇒ 白跑一趟。
    log("  ★ 阈值来源（实测 `_scratch/probe_contract.py`，量的全部环）："
        "最短边 12.0000 mm、最小面积 1250.000 mm²、1%% 分位边长 25.00 mm(= RES)"
        " ⇒ 取 RES/4 = %.2f、RES²/4 = %.2f；SU 自己的容差 ≈ 0.0254 mm（小 246 倍，量的是另一件事）"
        % (EDGE_MIN_MM, AREA_MIN_MM2))

    f1 = judge(data, src_col, dxf_by, _MEAS) + param_bad()
    log("  ★ ⑯ 阈值真源：`参数.json::共用/环_最短边下限` 与闸内 `EDGE_MIN_MM` "
        "= %s" % ("一致（%.4f）" % EDGE_MIN_MM if not param_bad() else "★不一致，见判词"))
    log("C1 真件：%d 层 / %d 条环，判词 %d 条 ⇒ %s"
        % (_MEAS["floors"], _MEAS["polys"], len(f1), "放行" if not f1 else "★红了"))
    # ★ `⑫Σ` 汇总行**先印、且不占 20 条明细额度**：它是唯一带着**真数**的那几行，
    #   挤在明细后面就等于没印（判词总数 ≠ 违规个数，这两个数必须分开写 —— 铁律 174）。
    sums = [v for v in f1 if v.startswith("⑫Σ")]
    det = [v for v in f1 if not v.startswith("⑫Σ")]
    for v in sums:
        log("     - %s" % v)
    for v in det[:20]:
        log("     - %s" % v)
    if len(det) > 20:
        log("     …明细另有 %d 条（本条判词 %d = 明细 %d + 汇总 %d）"
            % (len(det) - 20, len(f1), len(det), len(sums)))
    log("  ★ ⑭ 规模（只报不判）：最大一层 %d 条（%s）；实测一次塞 8570 张面 ⇒ SU rc=127，4422 稳"
        % (_MEAS["max_per_floor"], _MEAS["max_per_floor_which"]))
    ok = not f1
    base = set(f1)

    log("\n---- 正对照（每一条都必须按预期变红，且理由要对上）----")
    fl_wall, _ = _first_of(data, "WALL")
    if fl_wall is None:
        log("  ★ 跳不过去：一条 WALL 都没有，正对照无处下手 ⇒ 本条对照**没量到东西**")
        return _write(1)

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
    c9 = ctl("C9 某层 COL 减一条",
             (lambda d: (_drop_one_col(d), d)[1])(copy.deepcopy(data)),
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
    ok = ok and all(ctls)
    log("\n正对照 %d/%d 按预期" % (sum(ctls), len(ctls)))

    log("\n===== 判词 =====")
    if ok:
        log("J-10.8-00 总判 : PASS —— 这份 contours SU 吃得下；"
            "这一趟没有花掉一次 SU 往返")
    else:
        log("J-10.8-00 总判 : FAIL —— ★ 别去跑 SU：上面每一条都会在 SU 里变成"
            "「静默少一张面 / 挂死 / 整体大 1000 倍」，且要花 3 分钟才看出来")
    return _write(0 if ok else 1)


def _write(rc):
    """落两样产物：run.txt（判词行原样）＋ json（顶层读数，台账页的第三路）。

    ★ 退出码**不在这里算** —— 由调用方递进来；`pass` 只是 `rc == 0` 的同一件事（铁律 18）。
    """
    os.makedirs(RUNDIR, exist_ok=True)
    with open(os.path.join(RUNDIR, "J-10.8-00.run.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(_LOG) + "\n")
    out = {"pass": rc == 0, "rc": rc}
    out.update(_MEAS)
    out["blind"] = list(BLIND)
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("  写出:", JSON_OUT)
    return rc


if __name__ == "__main__":
    sys.exit(main())
