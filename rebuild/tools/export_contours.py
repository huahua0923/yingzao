# -*- coding: utf-8 -*-
"""判断层 → SU 能吃的**闭合轮廓**（每层一份 JSON + 一份 DXF）。

## 为什么要有这一道（2026-10-13 实测过）

底图 `01_cad/raw/*.dxf` 里的墙是**两根线**（`4.2墙体` 的双皮）。SU 导进去只是把这两根线
**原样画出来** —— 中间那道缝它不会自己变成面，而且两皮在门窗洞处断开、在楼角交叉，
**围不成闭合环** ⇒ SU 不生成面 ⇒ 没有实体 ⇒ 导 OBJ 只有 **147 字节空文件**（实测）。

SU 只有一条规矩：**平面内闭合的环 → 一张面**。所以只要喂给它**闭合轮廓**，它就成图。

## 本脚本干的活

判断（哪两根线是一堵墙、板在哪、柱在哪）**已经在本仓做完**。这里只把**判断的结果**
摊成闭合轮廓 —— 而且**直接调 `build3d` 里那批提取器**，判断只做一次：
SU 拿到的是同一个判断的产物，与参照件同源同判，不另立一套。

    墙带 → wall_polys · 抠井道 → carve
    柱   → col_polys      井道壁 → lift_polys     门扇 → door_polys
    楼板 → slab_polys · 抠井道 → carve           楼梯 → stair_steps（逐级带标高）

## ★★ 第一版跑红记（别重犯）

第一版 `_rings()` 按 shapely `Polygon` 收件，而 `redraw.geometry()` 实际给的是：

    walls : [(shell_pts, [hole_pts, ...]), ...]   ← **原始点列元组**，不是 Polygon
    cols  : [(pts, closed), ...]
    plate : [[pt, ...], ...]                      ← 只有外环

⇒ `isinstance(g, sg.Polygon)` **全 False**，12 层每层写 0 个多边形，还判「正对照不过」；
那 67312 字节的文件**全是 `ezdxf.new(setup=True)` 的样板**（linetype/图层表），
一个实体都没有。★ 教训：**接口形状要量，不能照 docstring 猜**（docstring 只列了键名，
没写类型）—— 正对照当场把这件事抓出来了，这就是它存在的意义。

## ★★ 第二版跑红记：洞一个都没抠（2026-10-14，本轮交付件缺陷的根因）

用户报「部分墙体缺失 / 楼梯和电梯不对」。逐层逐类实测（`_scratch/_wall_compare.py`）：

    层/类        gross      net     包内足迹
    1层  WALL   5762.8    5652.5     5762.8     ← == gross
    8层  WALL     95.9      90.0       95.9     ← == gross
    3层  SLAB   5895.5    5889.6     5895.5     ← == gross
    3层  LIFT      5.9       2.3        5.9     ← == gross
    3层  COL      69.0      69.0       69.0     ← 无洞，本来就对

**12 层 × 每一类，包内件足迹逐位等于 gross** ⇒ 洞全没抠。根因是 SU 侧：
`add_face(外环)` 不会把已存在的闭合洞边当洞抠（旧版 `su_step2_build.rb:60` 那条断言是错的），
`add_face(外环, 洞…)` 多环抛异常，`add_edges` 也不劈面 —— 三条路都实测过。
`holes_cut=147` 这个计数**数的是 `add_edges` 成功次数，不是抠成的洞**（铁律 158）。

⇒ 修法：**本脚本先把洞切掉**（`_cut_holes`，水平割），`holes` 恒 `[]`；SU 只负责无洞环成面 + 拉伸。

## 出件

    rebuild/06_su/contours/<层名>.json   机器件：SU 脚本读这个（**无洞环** + 每层拉伸高度 + 名字）
    rebuild/06_su/contours/<层名>.dxf    人看的件：在 CAD/SU 里能直接打开核对
    rebuild/06_su/contours/index.json    汇总（每层件数、字节数、两道复核结果）

两份件**同一次写的环**，所以可以互为独立复核（DXF 重开数环 == JSON 重读数环）。

★ 单位必须显式写 `$INSUNITS=4`（毫米）：ezdxf 默认给 6（米），SU **认这个声明**，
  实测会把 130.7 m 的平面导成 130700 m（1000 倍，且不报错）。

用法：python rebuild/tools/export_contours.py
"""
import json
import os
import sys

import ezdxf
from shapely.geometry import LinearRing
from shapely.geometry import Polygon as SPoly
from shapely.geometry import box as sbox
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build3d as B3          # noqa: E402  （只用它的提取器与常数，不跑 main）
import redraw as RD           # noqa: E402
ROOT = B3.ROOT                # ★ 2026-10-17：随楼栋档案走（c006=rebuild/，c005=rebuild/c005/）

OUT = os.path.join(ROOT, "06_su", "contours")

# 每层的拉伸高度（mm）。SU 脚本照这个 pushpull。
PUSH_MM = {"WALL": None, "COL": None, "LIFT": None,    # None ⇒ 层高 h
           "SLAB": int(round(B3.SLAB_M * 1000)),
           "DOOR": int(round(B3.DOOR_H * 1000)),
           "STAIR": int(round(B3.TREAD_H * 1000)),
           # ★ LINTEL（门头墙）**每块自带 z 与 h**（h = 层高 − 门洞高，逐块不同）
           #   ⇒ 这个默认值**永远用不上**，写 None 只是让下面 `cnt` / `push_mm` / DXF 图层
           #   三处都自动带上它。与 STAIR 同型（那里 `TREAD_H` 也早被 per-record h 覆盖）。
           "LINTEL": None,
           # ★★ 2026-10-18 屋面附属用房（出屋面楼梯间 + 电梯机房）：**逐块自带 z 与 h**
           #   —— 墙在 TOP_M 长 `墙高`、顶板在 `TOP_M+墙高` 长板厚，两段高度不同。
           #   与 LINTEL 同型 ⇒ 这个默认值永远用不上，写 None 只为让 `cnt` / `push_mm` /
           #   DXF 图层三处自动带上它。做不做由源件说（`B3.roof_room_parts`，空表＝这栋没有）。
           "ROOF_ROOM": None,
           # ★★ 顶部三件：源图**没有**（无屋顶图/立面/剖面）⇒ 按规则推，**是假设值**，
           #    必须与「照图建的」分开看。判据里只查「块数 ≥ 1」，不查这些尺寸（见 05_build/README）。
           "PARAPET": int(round(B3.PARAPET_H * 1000)),        # 女儿墙 1.2 m
           "ROOF_STAIR": int(round(B3.ROOF_STAIR_H * 1000)),  # 顶楼楼梯房 3.0 m
           "ROOF_STEP": int(round(B3.SLAB_M * 1000)),         # 7→8 台阶屋面板厚 0.12 m
           # ★★ 2026-10-15 用户「楼板要画」⇒ 补 **塔楼屋面板**（第 11 类 `ROOF`）。
           #    `build3d.py:957` 早就建了它（`node_name="roof"`，`_extrude(sp, TOP_M−SLAB_M, SLAB_M)`
           #    = 38.38~38.50 m / 911 m²；`build.json` 11层 `z_by_class.roof` 也记着），
           #    **但本文件从来没把它发出去**（枚举里没有 `ROOF`）⇒ 正式件顶上 911 m² 是空的，
           #    只剩女儿墙与楼梯房悬在那儿 —— 用户点开「三维模型」一眼就看见了。
           #    与 `ROOF_STEP` **同型**：板顶 = 层高线（`11 × STOREY_M`），底 = 减去板厚。
           "ROOF": int(round(B3.SLAB_M * 1000))}               # 塔楼屋面板厚 0.12 m

_VCACHE = {}
_FLOOR = dict((n, (z0, h)) for n, z0, h in B3.FLOORS)
_TOP = B3.TOP_FLOOR                                  # c006 = 11层；c005 = 5层（档案给）

# 层的**稳定 ASCII 号**（`id` 用）：地下层→B1、第 i 个地上层→F0i。
# ★ 2026-10-17：从档案现建，不再写死 1..11（C001 只有 5 层、地下层名叫 D1）。
_FID_BASE = B3.B.profile().get("basement")
FID = dict(([( _FID_BASE, "B1")] if _FID_BASE else [])
           + [(nm, "F%02d" % (i + 1)) for i, nm in enumerate(B3.B.floor_names())])

# 剖分台账（**不是注释**：跑完要能报出「剖了几条、多出几条」，否则「修好了」没有读数支撑）
STATS = {"cut_in": 0, "cut_out": 0, "holes": 0}
# 逐层**已抠完的楼板**（= build3d 的 `V_SLAB`）。裙房屋面要拿「下一层楼板 − 顶层楼板」，
# 而下一层同样要清掉井道与梯间 —— 两边必须是同一份多边形（铁律 018/174）。
_SLAB_BY_FLOOR = {}
# 逐层**未扣挑空**的楼板（= `build3d` 的 `V_SLAB_NOVOID`）：顶层屋面板的基板。
# 屋面洞（327.1 m²）比 5 层楼板洞（428.5 m²）小，拿已扣过的板当基板会多开 101 m²。
_SLAB_NOVOID = {}
# ★ 2026-10-20：逐层门扇账。`build3d.door_polys` 的 `DOOR_AUDIT` 只存**最近一次**调用，
#   而本文件是「先把所有层算完、再逐层写盘」⇒ 写盘时读全局拿到的是**最后一层**的账
#   （c106 实测三层都印 23，实际 41/25/23）。这里按层名存快照，写盘与打印都读快照。
_FLOOR_AUDIT = {}


def _rel_z(name, z_abs_mm, z_hi_mm=None):
    """绝对标高 → **本层相对标高**。

    ★ 2026-10-18：`z_hi_mm` = 本层记录允许的**最高绝对标高**（默认 = 本层顶）。
      顶部附属件（出屋面楼梯间/电梯机房的**顶板**）合法地高出层高 —— 它的上限必须由
      **参数表里的房间高 + 板厚**算出来传进来，**不许**拿记录值自身当上限（那样闸就恒绿，铁律 137）。


    ★★ 2026-10-13 实测踩过：记录里的 `z` 是**相对本层底面**的（SU 脚本写 `zbase + pr["z"]`，
       `zbase = z0*1000`）。第一版把**绝对**标高写进去 ⇒ 女儿墙落到 **84000 mm**
       （40 m 层底 + 44 m 绝对），台阶屋面落到 **51880 mm** —— 两个原点相加。
       症状：SU 日志与 `BBOX_mm size=[…, 90500.0]` 都「正常」，只有总高从 50.5 m 变成 90.5 m
       才露出来（铁律 174：两个同名的量必须死掉一个 —— 这里就是「记录 z」这一个量只能有一个原点）。
    """
    z0, h = _FLOOR[name]
    zrel = z_abs_mm - z0 * 1000.0
    hi = h * 1000.0 if z_hi_mm is None else z_hi_mm
    if not (-1.0 <= zrel <= hi + 1.0):
        raise AssertionError(
            "%s 的相对标高 %.1f mm 不在 [0, %.0f] 内 —— 十有八九又把绝对标高写进来了（两个原点）"
            % (name, zrel, hi))
    return zrel


def _v(name):
    """`redraw.geometry` 的**进程内缓存**：顶部三件要用到 7/8/11 层的几何，
    而它们各自在主循环里也会被调一次 —— 不缓存就是白跑两遍栅格分析。"""
    if name not in _VCACHE:
        _VCACHE[name] = RD.geometry(name)
    return _VCACHE[name]


def _rec_many(polys, layer, z_mm=0.0):
    out = []
    for p in polys:
        out.extend(_rec(p, layer, z_mm))
    return out


def _attach_recs(name, cut=(), sp=None):
    """顶部两件（女儿墙 / 顶楼楼梯房）——**与参照件调同一批 build3d 函数**，
    所以「判断」只做一次，两边不会各推一套。挂在顶层（基面 = TOP_M）。
    7→8 台阶屋面不在这里（要等 8 层楼板落位），见 `_roof_step_recs`。

    ★ `cut` = 本层的**梯间清空区**（`_floor_recs` 那一趟落位的产物）—— 塔楼屋面板也要它：
      参照件那边的屋面板用的是 `sp`（已经清了梯间），本件不跟着清，就会出现
      「参照件屋面上有个井口、正式件没有」（铁律 018/174）。
      ★ 为什么是**传进来**而不是在这里现算：清空区必须与楼梯落位同源，不许第二次落位。
    """
    out = []
    if name == _TOP:
        v = _v(name)
        # ★★ 塔楼屋面板（2026-10-15 用户「楼板要画」补）—— **与 `build3d.py:957` 逐字同源**：
        #    同一个 `carve(slab_polys(v), lift_voids(v))`，同一个 `TOP_M − SLAB_M`。
        #    少抠井道 / 换个 z，参照件与正式件就各说各话（铁律 018/174）。
        #    相对本层底面 = 层高 − 板厚 = 3880 mm（层高 4.0 m 口径）；板顶正好停在层高线 44.0 m。
        _rp = sp if sp is not None else B3.carve(B3.carve(B3.slab_polys(v),
                                                         B3.lift_voids(v)), list(cut))
        if cut:                       # ★ 与参照件同一条件：真扣了东西才塌短边（见 B3._drop_short_edges）
            _rp = B3._drop_short_edges(_rp)[0]
        # ★★ 2026-10-19 屋面洞 —— **与 build3d 顶层同一条判据**：有屋面洞时，
        #   基板取 `_SLAB_NOVOID`（未扣楼板挑空），否则 5 层的洞会把屋面洞吃掉。
        _rv = B3.roof_void_polys()
        if _rv and _SLAB_NOVOID.get(name):
            _rp = _SLAB_NOVOID[name]
        # ★★ 2026-10-19 露台无顶 —— **与 `build3d.py` 的屋面板逐位同源**（同一个
        #   `B3.terrace_polys`）。露台要有楼板、不能有顶：楼板走 `sp`（不动），
        #   屋面板与它下面的女儿墙一起按露台开洞。少这一步 ⇒ 参照件屋顶有洞、
        #   正式件没有（铁律 018/174：同一个量不许两个口径）。
        _tp = B3.terrace_polys(name)
        if _tp:
            _tu = B3.unary_union(_tp)
            _rp = [g for q in _rp for g in B3._split(q.difference(_tu))]
        if _rv:
            _ru = B3.unary_union(_rv)
            _rp = [g for q in _rp for g in B3._split(q.difference(_ru))]

        out += _rec_many(_rp, "ROOF",
                         z_mm=_rel_z(name, (B3.TOP_M - B3.SLAB_M) * 1000.0))
        # 女儿墙/楼梯房基面 = 顶层楼板顶 = B3.TOP_M（= 11 × 层高）。
        # ★ 别在这行写死一个数 —— 它随参数表 共用/层高 变。2026-10-16 现口径 4.0 m ⇒ 这里是 44.0 m。
        z = _rel_z(name, B3.TOP_M * 1000.0)
        # ★ 2026-10-17 顶层收窄到塔楼后，女儿墙跟着**收窄后的楼板**走（塔楼屋面一圈）。
        out += _rec_many(B3.parapet_ring(_rp), "PARAPET", z_mm=z)
        # ★★ 2026-10-17 用户令「不要屋顶的电梯塔楼了」—— 与 `build3d.py` 同一开关（默认不建）；
        #   两处必须同源，否则参照件有塔楼、正式件没有（铁律 018）。
        if B3.B.profile().get("roof_stair", False):
            # ★★ 2026-10-18：实心盒 → **结构体**（环带墙 + 顶板 + 门洞缺口）。
            #   墙挂 z=TOP_M、高=`墙高`；顶板挂 z=TOP_M+墙高、高=板厚 —— 逐条带 `h`。
            #   做不做由源件说：`roof_room_parts` 空表＝这栋顶楼没有这件，**不出也不报错**。
            _rr = B3.roof_room_parts(v)
            _slab_h = round(B3.SLAB_M * 1000.0, 1)
            # ★ 顶板的最高绝对标高上限：由**参数表的房间高 + 板厚**定（不拿记录值自身当上限）。
            _z_hi = (B3.TOP_M + max(B3.ROOF_STAIR_H, B3.ROOF_LIFT_H) + B3.SLAB_M) * 1000.0
            for _walls, _slabs, _hh in (_rr["stairs"] + _rr["lift_rooms"]):
                for _p in _walls:
                    out.extend(_rec(_p, "ROOF_ROOM", z, h_mm=round(_hh * 1000.0, 1)))
                _z2 = _rel_z(name, (B3.TOP_M + _hh) * 1000.0, z_hi_mm=_z_hi)
                for _p in _slabs:
                    out.extend(_rec(_p, "ROOF_ROOM", _z2, h_mm=_slab_h))
        # ★ 裙房屋面（顶层只占塔楼时）：板 + 外围女儿墙都挂在顶层，基面 = 顶层底 − 一层。
        if B3.B.profile().get("podium_roof"):
            _names = [n for n, _z, _hh in B3.FLOORS]
            _i = _names.index(name)
            if _i >= 1:
                _pn = _names[_i - 1]
                # ★★ 2026-10-17：下一层楼板**不许在这里现算**。参照件用的是 `V_SLAB[下层]`
                #    = `carve(slab, 井道, 梯间清空)`，这里原先只抠井道、漏了梯间清空
                #    ⇒ 楼梯核那块 [55470,48630,58820,53770] 被当成「顶层没有、下层有」的
                #    屋面，凭空多出一块 3.35×5.14 m 的假板 + 假女儿墙（铁律 018/174）。
                #    楼层按 1→5 顺序算，下一层的板早已落位；宁可报错也不悄悄改用旧口径。
                _lo = _SLAB_BY_FLOOR.get(_pn)
                if _lo is None:
                    raise RuntimeError(
                        "裙房屋面：下一层 %s 的楼板还没落位（`_SLAB_BY_FLOOR` 缺键）——"
                        "楼层必须自下而上算；不许退回「只抠井道」的旧口径" % _pn)
                _rp2, _rails = B3.podium_roof_parts(_lo, _rp)
                # ★ 2026-10-19：层高改逐层后「顶层底」≠ `TOP_M − STOREY_M`（首层 6.0 时差 2 m）。
                #   一律从 FLOORS 取（`_FLOOR[name][0]`），不再用两个标量相减。
                _zp = _rel_z(name, float(_FLOOR[name][0]) * 1000.0)
                out += _rec_many(_rp2, "ROOF", z_mm=_zp)
                out += _rec_many(_rails, "PARAPET", z_mm=_zp)
    # ★ 7→8 台阶屋面**不在这里**：它要 8 层的板，而楼层是自下而上算的，
    #   走到 7 层时 8 层还没落位。见 `_roof_step_recs`（在 main 里所有层落位后算）。
    return out


def _roof_step_recs(all_recs):
    """7→8 台阶屋面板 + 女儿墙 —— **必须等两层楼板都落位之后再算**。

    ★★ 2026-10-18（铁律 018/174：同一个量不许有两个估计器）：本段原先在这里用
      **未抠洞**的 `slab_polys` 相减，而参照件 `build3d._slab_carved` 用的是
      「抠井道 + 抠梯间清空 + 塌短边」之后的板（2026-10-17 已按 `A_slab_m2` 对齐过一次，
      只改了 build3d 一侧）。实测同一栋 c006：

        未抠洞 板差 4468.80 m² / 2 块   ◄── 本件旧口径
        抠后   板差 4353.94 m² / 3 块   ◄── 参照件口径（本轮实测 4353.9）

      加上女儿墙后差异不再只是 2.6% 的面积：环带整圈跟着板走 ⇒
      旧口径 4 段 115.1 m²、参照件 3 段 133.7 m²（2026-10-18 实测）。
      ⇒ 本件一律取 `_SLAB_BY_FLOOR`（= 各层 `_sp`，与 build3d 同一串刀）。
    """
    rows = [r for r in all_recs if r[0] == "7层"]
    if not rows or "8层" not in _FLOOR:
        return 0
    a, b = _SLAB_BY_FLOOR.get("7层"), _SLAB_BY_FLOOR.get("8层")
    if a is None or b is None:
        raise RuntimeError("7→8 台阶屋面：7层/8层 的楼板还没落位（`_SLAB_BY_FLOOR` 缺键）"
                           "——不许退回「未抠洞」的旧口径")
    from shapely.ops import unary_union as _uu
    pa, pb = _uu(a), _uu(b)
    d = pa.difference(pb).buffer(0) if (not pa.is_empty and not pb.is_empty) else pa
    rp = [g for g in B3._split(d) if g.area > 1e6]
    # ★ 2026-10-19：层高逐层后「7 层顶」不再等于 `7 × 层高` ⇒ 从 FLOORS 现取。
    _z7mm = (float(_FLOOR["7层"][0]) + float(_FLOOR["7层"][1])) * 1000.0
    out = list(_rec_many(rp, "ROOF_STEP",
                         z_mm=_rel_z("7层", _z7mm - B3.SLAB_M * 1000.0)))
    if B3.B.profile().get("roof_step_parapet", False):
        # ★ 基面 = 屋面顶 = 7 层顶（与 build3d 的 `_GROUND_TOP[6]` 同一个量）。
        #   与 build3d **调同一个函数、喂同一对板**（铁律 018/174）。
        out += _rec_many(B3.roof_step_rails(rp, pb), "PARAPET",
                         z_mm=_rel_z("7层", _z7mm))
        # ★★ 2026-10-19：这段女儿墙是**楼层全部算完之后**才追加的 —— `_floor_recs` 里那道
        #   `_collapse_recs` 那时早就跑过了，环带被 `_cut_holes` 横切出的残边**没人收**。
        #   实测 7 层留下 3.002 / 5.004 mm 两条（`F07-PARAPET-005/013`，闸 `J-10.8-00` ⑪
        #   唯一的红；`_collapse_recs` 里加上 `PARAPET` 之所以没用，就是因为它压根没经手
        #   这两条 —— 铁律 183：同一形状换个**时机**还会再犯，不能只改名单）。
        out = _collapse_recs(out, ("PARAPET",))
    rows[0][4].extend(out)
    print("7→8 台阶屋面 %d 块 · %.1f m² ＋ 女儿墙 %d 段 · %.1f m²（取抠后楼板，与参照件同源）"
          % (len(rp), sum(g.area for g in rp) / 1e6,
             sum(1 for r in out if r["layer"] == "PARAPET"),
             sum(_ring_area_mm2(r["ring"]) / 1e6 for r in out if r["layer"] == "PARAPET")))
    return len(out)


def _mid_roof_recs(all_recs):
    """层间退台屋面（档案 `mid_roofs` 声明）——**与参照件 build3d 同一条路**（铁律 018/174）：
    下层板 − 上层板 ∩ 声明足迹；板顶 = 下层底 + 层高，厚 = `SLAB_M`。
    足迹只限定范围，不手画板；两层板一律取 `_SLAB_BY_FLOOR`（= 参照件 `V_SLAB` 的同一份）。
    """
    ents = B3.B.profile().get("mid_roofs") or []
    if not ents:
        return 0
    from shapely.geometry import box as _box
    from shapely.ops import unary_union as _uu
    names = [n for n, _z, _h in B3.FLOORS]
    n = 0
    for e in ents:
        lo = e["层"]
        i = names.index(lo)
        if i + 1 >= len(names):
            raise RuntimeError("mid_roofs：%s 是顶层，上方没有楼层可比" % lo)
        hi = names[i + 1]
        a, b = _SLAB_BY_FLOOR.get(lo), _SLAB_BY_FLOOR.get(hi)
        if a is None or b is None:
            raise RuntimeError(
                "层间退台屋面：%s/%s 的楼板还没落位（`_SLAB_BY_FLOOR` 缺键）"
                "——不许另调 `slab_polys` 重算（就是两个估计器）" % (lo, hi))
        d = _uu(a).difference(_uu(b)).buffer(0)
        fp = [float(v) for v in e["足迹"]]
        d = d.intersection(_box(fp[0], fp[1], fp[2], fp[3]))
        rp = [g for g in B3._split(d) if g.area > 1e6]
        z0, h = _FLOOR[lo]
        # ★ 2026-10-19：与 `_roof_step_recs` 同一个时机问题 —— 这几块板也是楼层算完之后
        #   才追加的，`_floor_recs` 那道 `_collapse_recs` 经不到它们。就地补收一次
        #   （没有短边时 `k=0`，一个点都不动）。
        out = _collapse_recs(
            _rec_many(rp, "ROOF", z_mm=_rel_z(lo, (z0 + h - B3.SLAB_M) * 1000.0)),
            ("ROOF",))
        rows = [r for r in all_recs if r[0] == lo]
        if not rows:
            raise RuntimeError("层间退台屋面：找不到 %s 的记录行" % lo)
        rows[0][4].extend(out)
        n += len(out)
        print("层间退台屋面 %s：%d 块 · %.1f m²（板顶 %.2f m）"
              % (lo, len(rp), sum(g.area for g in rp) / 1e6, z0 + h))
    return n


def _lower_roof_recs(all_recs):
    """**通用下层屋面** + 女儿墙 —— 判据与几何都在 `B3.lower_roof_pieces`（唯一定义处）。

    ★★ 2026-10-20：与参照件 `build3d.py` 的「下层翼楼/退台屋面」那一段**同一把尺子**：
      同一对抠后楼板（`_SLAB_BY_FLOOR` = `V_SLAB`）、同一份本层墙带、同一组阈值；
      挂在**下层**记录行上，相对标高 = 本层顶 − 板厚（与 `_mid_roof_recs` 同口径）。
      这里若另写一套判据，参照件与正式件就会各有各的屋顶（铁律 018/174）。
    """
    from shapely.ops import unary_union as _uu

    names = [n for n, _z, _h in B3.FLOORS]
    n = 0
    for i in range(len(names) - 1):
        lo, hi = names[i], names[i + 1]
        z0, h = _FLOOR[lo]
        if z0 < 0:
            continue                       # 地下层顶：地面就是屋面，不补
        if B3.lower_roof_skip(lo, hi, names):
            continue                       # 已有机制处理（mid_roofs / roof_plans / podium / 7→8）
        a, b = _SLAB_BY_FLOOR.get(lo), _SLAB_BY_FLOOR.get(hi)
        if a is None or b is None:
            raise RuntimeError(
                "下层屋面：%s/%s 的楼板还没落位（`_SLAB_BY_FLOOR` 缺键）"
                "——不许另调 `slab_polys` 重算（就是两个估计器）" % (lo, hi))
        rp, _d = B3.lower_roof_pieces(a, b, lo, B3.wall_polys(_v(lo)))
        if not rp:
            continue
        out = _rec_many(rp, "ROOF", z_mm=_rel_z(lo, (z0 + h - B3.SLAB_M) * 1000.0))
        rails = B3.roof_step_rails(rp, _uu(b))
        out += _rec_many(rails, "PARAPET", z_mm=_rel_z(lo, (z0 + h) * 1000.0))
        out = _collapse_recs(out, ("ROOF", "PARAPET"))
        rows = [r for r in all_recs if r[0] == lo]
        if not rows:
            raise RuntimeError("下层屋面：找不到 %s 的记录行" % lo)
        rows[0][4].extend(out)
        n += len(out)
        print("下层屋面 %s→%s：板 %d 块 · %.1f m² ＋ 女儿墙 %d 段 · %.1f m²（板顶 %.2f m）"
              % (lo, hi, len(rp), sum(g.area for g in rp) / 1e6,
                 len(rails), sum(g.area for g in rails) / 1e6, z0 + h))
    return n


def _dedup(pts):
    """去掉**连续重复点**（零长边）。

    ★★ 2026-10-13 实测：`round(…, 1)`（0.1 mm）会把两个原本不相等的坐标**圆成同一个数**
       —— `7层/ROOF_STEP` 件 0 的环尾就出现 `(105005.0, 62055.0)` 连着两次。
       shapely 说它 `is_valid / is_simple` 全 True（重复顶点不算自交），
       **SU 却成不了面**：`add_face` 建不出长度 0 的边 ⇒ 这条多边形静默丢掉一张面
       （本次 `FACES built=4 fail=1`，只丢在缩位之后才露头）。
    ★ 只去「相邻」重复，**闭合点保留**（首点会在末尾再出现一次，那是正常的收口）。
    """
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    return out


# 类的**人读名**（给 SU 组名 / 网页 / 本条记录的名字用；`layer` 那个 ASCII 键不动）
# ★ `LIFT` 的中文名 2026-10-15 由「电梯井」改成「竖井」：两把互不同源的尺子都说不通
#   （① 形状：1 层核心筒墙上闭合矩形只有 1389.4×1853.0 与 1008.0×1646.9×2，
#      全层扫描也没有 LINE 围成的 1.5–3.2 m 矩形；② 命名：12 层共 1099 条文字，
#      **无一条含「梯」或「井」**）⇒ 三个洞是管道井/竖井，本套图**没有客运电梯井**。
#   ★ ASCII 键**仍叫 LIFT**：改名要同时动 `compare3d` / `su_step2_build.rb` /
#     `J-10.8-00`+`J-10.8-01` 两个判据 / `demo/build_pack.py` / `demo/index.html` 配色，
#     是一次独立的、会碰判据的改动 —— 先只改**人读名**，别把两件事混在一趟里。
CLS_CN = {"WALL": "墙体", "COL": "柱", "LIFT": "竖井", "SLAB": "楼板",
          "DOOR": "门", "STAIR": "楼梯", "LINTEL": "门头墙", "PARAPET": "女儿墙",
          "ROOF_STAIR": "屋顶楼梯房", "ROOF_STEP": "台阶屋面", "ROOF": "屋面板",
          "ROOF_ROOM": "屋面附属用房"}


def _cut_holes(g, budget=100000):
    """带洞多边形 → **无洞**多边形列表（水平割）。

    ★★ 2026-10-14 坐实：**本轮交付件缺陷的根因就是洞一个都没抠** ——
       `_scratch/_wall_compare.py` 逐层逐类对照，包内件足迹**逐位等于 gross**
       （1层 WALL gross 5762.8 / net 5652.5 / 包内 5762.8；3层 LIFT 5.9 / 2.3 / 5.9；
       3层 COL 无洞 69.0 / 69.0 / 69.0 —— **COL 是唯一无洞的类，也唯一本来就对**，正是反证）。

    为什么不在 SU 里抠（三条路都实测过，全不通）：
      · `add_face(外环, 洞1, 洞2…)` 多环 ⇒ 抛 `Not enough edges` / `wrong number of values in array`；
      · `add_edges(洞环, true)` ⇒ 抛 `ArgumentError`（现行代码靠 rescue 回落到不带 weld 的那次）；
      · `add_face(外环)` 也不把已存在的闭合洞边当洞抠掉 ⇒ 出面是**实心 4.00 m²**（对照 3.00）。
      ★ 旧注释（`su_step2_build.rb:60`）「SU 成面时会自动把内部已有的闭合边当洞抠掉」**是错的**，
        而 `holes_cut=147` 这个计数数的是 `add_edges` 成功次数、不是抠成的洞 —— 铁律 158：
        判词必须声明量具对什么盲。

    ⇒ 唯一可靠的路：**在 Python 侧先把洞切掉**，喂给 SU 的每条环天然无洞。

    算法：取一条内环（洞）的 bbox 中心 y，用横贯线把多边形切成上下两半 ——
      洞的 bbox 中心 y **严格落在该洞内部** ⇒ 切开后该洞在两半里都变成**缺口**、
      不再是闭合内环。每次至少消掉一个洞 ⇒ 递归必然终止。
      实测规模：8443 条里只有 **69 条带洞**（148 个洞），剖完 8443 → 8715 条（+272）。

    ★ 面积守恒是**判据不是注释**：剖后各片之和必须等于剖前（铁律 187 —— 基线与期望
      来自两次不同读数：剖前取 shapely 的、剖后取各片之和）。
    """
    if g is None or g.is_empty:
        return []
    # ★★ 2026-10-17 C026 实测：布尔/求差的结果可能是 **GeometryCollection**（多边形夹着一点线/点），
    #   而下面第一句就读 `g.interiors` ⇒ `AttributeError: 'GeometryCollection' object has no
    #   attribute 'interiors'`，整栋在「轮廓」这一步炸掉。先摊平成 Polygon 再进来；
    #   集合里的线/点本来就不是面，丢掉不损失面（面积守恒判据在后面照旧会校验）。
    if g.geom_type in ("MultiPolygon", "GeometryCollection"):
        polys, st = [], [g]
        while st:
            q0 = st.pop()
            if q0.geom_type in ("MultiPolygon", "GeometryCollection"):
                st.extend(q0.geoms)
            elif q0.geom_type == "Polygon" and not q0.is_empty:
                polys.append(q0)
        return [r for p in polys for r in _cut_holes(p, budget=budget)]
    if not g.interiors:
        return [g]
    want = float(g.area)
    out, stack, guard = [], [g], 0
    while stack:
        guard += 1
        if guard > budget:
            raise AssertionError("剖分不收敛：%d 步 > %d" % (guard, budget))
        q = stack.pop()
        if q.geom_type in ("MultiPolygon", "GeometryCollection"):
            stack.extend(x for x in q.geoms
                         if x.geom_type in ("Polygon", "MultiPolygon"))
            continue
        if q.geom_type != "Polygon" or q.is_empty:
            continue
        if not q.interiors:
            out.append(q)
            continue
        r = q.interiors[0]
        ys = [pt[1] for pt in r.coords]
        y00 = (min(ys) + max(ys)) / 2.0
        x0, y0, x1, y1 = q.bounds
        big = max(x1 - x0, y1 - y0) + 10.0
        for piece in (q.intersection(sbox(x0 - big, y0 - big, x1 + big, y00)),
                      q.intersection(sbox(x0 - big, y00, x1 + big, y1 + big))):
            if not piece.is_empty:
                stack.append(piece)
    got = sum(float(p.area) for p in out)
    if abs(got - want) > max(1.0, want * 1e-9):
        raise AssertionError("剖分改了面积：%.3f → %.3f mm²" % (want, got))
    STATS["cut_in"] += 1
    STATS["cut_out"] += len(out)
    STATS["holes"] += len(g.interiors)
    return out


def _ring_area_mm2(c):
    """闭合环（首尾同点，或不闭合）的有向面积取绝对值，mm²。"""
    p = list(c)
    if len(p) > 1 and p[0] == p[-1]:
        p = p[:-1]
    n = len(p)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = p[i]
        x2, y2 = p[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _collapse_recs(recs, layers):
    """把**这几类**记录环上**短于 `B3.RING_EDGE_MIN_MM` 的边**塌掉 → 新记录表。

    ★★ 为什么在**记录这一层**还要再塌一遍（而 build3d 那边是在多边形那层塌的）：
      本件比参照件多一道 `_cut_holes` —— 它按洞的中线 y 把带洞多边形**横切一刀**。
      这条横切线是**人为的**，它靠某个墙顶点 2.5 mm 时，结果环上就留下一条
      3.536 mm（= 2.5·√2）的残边。实测 5/6 层各一条：
      `(52980,51305) → (52977.5,51307.5)`，前者是墙自己的角点，后者是横切线穿过
      45° 倒角的位置 ⇒ 多边形那层的塌短边**看不见它**（那时还没切）。
      ⇒ 只在记录层塌它，且**只给这几类**（= 真被梯间那一刀动过的）—— 其余类一个点不动。
    ★ 代价与边界（铁律 028/158）：塌掉的顶点最多移 `RING_EDGE_MIN_MM`（6.25 mm）。
      哪些环塌没了（环 < 4 点）就**原样留着**并记账；丢掉的面积当场对账，
      超过 1 mm² 就抛（不许无声丢件 —— 同 `_rec` 的口径）。
    """
    out, lost, ncut, darea = [], 0.0, 0, 0.0
    for r in recs:
        c0 = r.get("ring")
        if r.get("layer") not in layers or not c0:
            out.append(r)
            continue
        c = [[float(a), float(b)] for a, b in c0]
        if len(c) > 1 and c[0] == c[-1]:
            c = c[:-1]
        if len(c) < 4:
            out.append(r)
            continue
        a0 = _ring_area_mm2(c)
        c, k, _longest = B3._collapse_short([(x, y) for x, y in c],
                                            B3.RING_EDGE_MIN_MM)
        if k == 0:
            out.append(r)
            continue
        ncut += k
        _pre = [[float(x), float(y)] for x, y in c]      # ★ 圆整前的坐标（兜底用，见下）
        c = [[round(x, 1), round(y, 1)] for x, y in c]
        c = _dedup(c + [c[0]])                       # 闭合点保留（SU 那边自成闭合）
        # ★★ 2026-10-17：塌短边与圆整**都可能把顶点挪到非相邻边上**（入口闸 ⑩ 的判词是
        #   「环自交」）。1层实测：坏环在圆整那一步出现（`_split`/`_cut_holes` 出来
        #   is_simple=True、圆整到 0.1 mm 后 False）。这里做同一件事的兜底 —— 圆整坏了就
        #   退回未圆整的坐标；只对坏的那条生效（铁律 183：同形状换函数仍会再犯，所以
        #   `_rec` 与 `_collapse_recs` 两处都要堵）。
        if len(c) >= 4 and not LinearRing([tuple(q) for q in c] + [tuple(c[0])]).is_simple:
            c = _dedup(_pre + [_pre[0]])
        if len(c) < 4:
            lost += a0
            out.append(r)                            # 塌没了 ⇒ 原样留着
            continue
        darea += abs(a0 - _ring_area_mm2(c))
        q = dict(r)
        q["ring"] = c
        out.append(q)
    if lost > 1.0:
        raise AssertionError("_collapse_recs 丢掉了 %.3f mm² 的环（不该无声丢件）" % lost)
    STATS["塌短边_点"] = STATS.get("塌短边_点", 0) + ncut
    STATS["塌短边_面积mm2"] = round(STATS.get("塌短边_面积mm2", 0.0) + darea, 3)
    return out


def _dedup_contained_recs(recs):
    """删掉同层同类同 z 中 **≥99.5% 被更大环覆盖** 的重复/嵌套环。

    只处理“重复或完全包在更大同类环里”的情况；**部分相交不合并**
    （那可能是真实构件相交，必须继续报红让人看）。输出保持原记录顺序。
    """
    groups = {}
    for i, r in enumerate(recs):
        ring = r.get("ring") or []
        if len(ring) < 4:
            continue
        pts = ring[:-1] if ring[0] == ring[-1] else ring
        try:
            p = SPoly(pts)
            if not p.is_valid:
                p = p.buffer(0)
        except Exception:
            continue
        if p.is_empty:
            continue
        groups.setdefault((r.get("layer"), r.get("z")), []).append((i, p, p.area))
    drop = set()
    removed_area = 0.0
    for items in groups.values():
        if len(items) < 2:
            continue
        kept = []
        for i, p, area in sorted(items, key=lambda x: x[2], reverse=True):
            dup = False
            for _j, q, qa in kept:
                inter = p.intersection(q).area
                if inter > 0 and inter / max(min(area, qa), 1e-9) >= 0.995:
                    dup = True
                    break
            if dup:
                drop.add(i)
                removed_area += area
            else:
                kept.append((i, p, area))
    out = [r for i, r in enumerate(recs) if i not in drop]
    return out, len(drop), round(removed_area, 3)


def _union_layer_overlaps(recs, layers=("LIFT", "STAIR")):
    """把同层同类同 z 的井道/楼梯足迹做并集，消除共面重叠。

    井道和楼梯在源图里常见“同一块画两遍/大小环叠画”；对 SU 来说同一平面
    只能留一个外轮廓，否则会互相切面。并集后仍按独立连通块输出。
    """
    groups = {}
    for i, r in enumerate(recs):
        if r.get("layer") in layers:
            groups.setdefault((r.get("layer"), r.get("z")), []).append(i)
    replace = set()
    add = []
    unioned_groups = 0
    for (_layer, _z), idxs in groups.items():
        if len(idxs) < 2:
            continue
        polys = []
        ok = True
        for i in idxs:
            ring = recs[i].get("ring") or []
            pts = ring[:-1] if ring and ring[0] == ring[-1] else ring
            try:
                p = SPoly(pts)
                if not p.is_valid:
                    p = p.buffer(0)
                if p.is_empty:
                    ok = False
                    break
                polys.append(p)
            except Exception:
                ok = False
                break
        if not ok:
            continue
        merged = unary_union(polys)
        parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        if len(parts) >= len(idxs):
            continue
        base = recs[idxs[0]]
        for p in parts:
            for q in B3._split(p):
                if q.is_empty or q.area <= 0:
                    continue
                ring = [[round(float(x), 1), round(float(y), 1)]
                        for x, y in q.exterior.coords]
                rec = dict(base)
                rec["ring"] = _dedup(ring)
                add.append(rec)
        replace.update(idxs)
        unioned_groups += 1
    if not replace:
        return recs, 0
    out = [r for i, r in enumerate(recs) if i not in replace]
    out.extend(add)
    return out, unioned_groups


def _repair_bad_rings(recs):
    """把自交环用 buffer(0) 拆成简单环；拆不了就保留原样让判据报红。"""
    out, fixed = [], 0
    for r in recs:
        ring = r.get("ring") or []
        pts = ring[:-1] if ring and ring[0] == ring[-1] else ring
        try:
            simple = len(pts) >= 3 and LinearRing(
                [tuple(q) for q in pts] + [tuple(pts[0])]).is_simple
        except Exception:
            simple = False
        if simple:
            out.append(r)
            continue
        try:
            p = SPoly(pts)
            if not p.is_valid:
                p = p.buffer(0)
            parts = list(p.geoms) if hasattr(p, "geoms") else [p]
            made = []
            for q in parts:
                for z in B3._split(q):
                    rr = dict(r)
                    rr["ring"] = _dedup([
                        [round(float(x), 1), round(float(y), 1)]
                        for x, y in z.exterior.coords])
                    if len(rr["ring"]) >= 4:
                        made.append(rr)
            if not made:
                out.append(r)
            else:
                out.extend(made)
                fixed += 1
        except Exception:
            out.append(r)
    return out, fixed


def _rec(poly, layer, z_mm=0.0, h_mm=None):
    """一个 shapely 多边形 → 记录：**先剖成无洞**，每条记一个外环、`holes` 恒空。

    ★ 剖完再说 `_dedup`/短环丢弃 —— 而被丢掉的面积**不许静默**：这里当场对账
      （剖后各片面积之和 vs 真正写出去的那些环的面积之和）。

    ★ `h_mm`（2026-10-14 加）：**逐条的拉伸高度**。楼梯模块每一级的顶面标高不同，
      SU 那边若还按「一层一个常数」拉伸，就还是薄板不是踏步（见 su_step2_build.rb 第 158 行）。
      `h_mm=None` ⇒ 不写 `"h"`，下游退回按层的常数（其余各类的形制**一字未变**）。
    """
    out = []
    lost = 0.0
    for g in B3._split(poly):
        for pc in _cut_holes(g):
            _full = _dedup([[float(x), float(y)] for x, y in pc.exterior.coords])
            ring = _dedup([[round(float(x), 1), round(float(y), 1)]
                           for x, y in pc.exterior.coords])
            # ★★ 2026-10-17 修（入口闸 `J-10.8-00` ⑩ 的 2 条红）：`round(…, 1)` 会把顶点
            #   **挪到一条非相邻边上** ⇒ `LinearRing.is_simple=False`，判词「环自交」。
            #   实测定位（同一趟、逐段查）：`_split` / `_cut_holes` 出来的环 is_simple=True，
            #   **圆整到 0.1 mm 之后**变 False —— 病根在圆整，不在剖分。
            #   1层两条：`wp3[40]` 的第 48 片（728 点，顶点 325 落在边 323→324 上）、
            #   `wp3[42]` 的第 0 片（59 点，顶点 54 落在边 52→53 上），两处都在 x=131580.0。
            #   ⇒ 兜底：圆整坏了就退回**未圆整**的坐标（实测那一份 is_simple=True，
            #     而且是剖分自己的输出，不是新造的几何）。只对坏的那条生效 —— 1层 838 条
            #     环里其余 836 条一个字节不动（SU 的 `clean_ring` 照样能成面）。
            if len(ring) >= 4 and not LinearRing(
                    [tuple(q) for q in ring] + [tuple(ring[0])]).is_simple:
                # ★★ 2026-10-17：**先修**再退。圆整把一个顶点压到**非相邻边**上 ⇒
                #   `is_simple=False`，但那不是真自交，`buffer(0)` 能把退化的接触点清掉、
                #   面积一分不变（实测 1层 STAIR-157：2513100.0 → 2513100.0，
                #   边界从 96798.5308 归到 96798.5）。
                #   原先直接退回未圆整 ⇒ 0.03 mm 的浮点尾巴活到输出，与邻块（96798.5）
                #   拉开 49 mm² 重叠（`J-10.8-00` ⑫ 红）。修不成才退（下面的 `_full`）。
                _rep = None
                try:
                    _rep = SPoly(ring).buffer(0)
                except Exception:
                    _rep = None
                if (_rep is not None and not _rep.is_empty and _rep.is_valid
                        and _rep.geom_type == "Polygon"
                        and abs(_rep.area - pc.area) <= max(1.0, pc.area * 1e-4)):
                    ring = [[round(float(u), 1), round(float(v), 1)] for u, v in _rep.exterior.coords]
                    STATS["环圆整修复"] = STATS.get("环圆整修复", 0) + 1
                else:
                    ring = _full
            if len(ring) < 4:                  # 3 个不同点起；SU 自成闭合
                lost += float(pc.area)
                continue
            r = {"layer": layer, "z": round(float(z_mm), 1),
                 "ring": ring, "holes": []}
            if h_mm is not None:
                r["h"] = round(float(h_mm), 1)
            out.append(r)
    if lost > 1.0:
        raise AssertionError("_rec 丢掉了 %.3f mm² 的环（不该无声丢件）" % lost)
    return out


def _fix_rec_overlaps(recs, cls=("STAIR",), tol=0.1):
    """同层同类的记录**互相压住**时，把顶点吸到邻块边界上（只动 0.1 mm 以内）。

    ★★ 2026-10-17：`J-10.8-00` ⑫ 实测 `1层/F01-STAIR-157 与 158 重叠 48.976 mm²`。
    病根**不在**裁墙那一步（那一步之前两块一点不压）：`_rec` 把带洞多边形剖开时，
    其中一片的顶点带 `126529.9997921` / `96798.5308023` 这类浮点尾巴，
    与邻块的 `126530.0` / `96798.5` 差 0.03 mm，沿 1590 mm 就是 49 mm² 的细条。
    `_rec` 本来就把坐标圆整到 0.1 mm，但**圆整会让那条环自交** ⇒ 它退回未圆整的坐标
    （见 `_rec` 里 ⑩ 的兜底），于是 0.03 mm 的错位活到了这里。
    ⇒ 处置：用**同一份记录**的邻块作参照 `snap`（不比新立阈值，用 `_rec` 已有的 0.1 mm）；
      吸不上再退回「后一块减前一块」；两条都不成 ⇒ 记 `未修`，**不静默放过**。
    """
    from shapely.ops import snap as _snap
    diag = {"压块对": 0, "吸边": 0, "减法": 0, "未修": 0}
    for c in cls:
        idx = [i for i, r in enumerate(recs) if r["layer"] == c]
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, j = idx[a], idx[b]
                if abs(float(recs[i]["z"]) - float(recs[j]["z"])) > 1e-6:
                    continue
                pi = SPoly(recs[i]["ring"], recs[i]["holes"])
                pj = SPoly(recs[j]["ring"], recs[j]["holes"])
                if pi.intersection(pj).area <= 0:
                    continue
                diag["压块对"] += 1
                done = False
                for x, y in ((i, j), (j, i)):
                    q = _snap(SPoly(recs[x]["ring"], recs[x]["holes"]),
                              SPoly(recs[y]["ring"], recs[y]["holes"]), tol)
                    if q.is_empty or not q.is_valid:
                        continue
                    if q.intersection(SPoly(recs[y]["ring"], recs[y]["holes"])).area > 0:
                        continue
                    ring = [[round(float(u), 1), round(float(v), 1)] for u, v in q.exterior.coords]
                    if len(ring) >= 4 and LinearRing([tuple(t) for t in ring]).is_simple:
                        recs[x]["ring"] = ring
                        diag["吸边"] += 1
                        done = True
                        break
                if done:
                    continue
                q = pj.difference(pi)
                if isinstance(q, SPoly) and q.is_valid and q.area > 0:
                    ring = [[round(float(u), 1), round(float(v), 1)] for u, v in q.exterior.coords]
                    if len(ring) >= 4 and LinearRing([tuple(t) for t in ring]).is_simple:
                        recs[j]["ring"] = ring
                        diag["减法"] += 1
                        continue
                diag["未修"] += 1
    if diag["压块对"]:
        STATS["修重叠_吸边"] = STATS.get("修重叠_吸边", 0) + diag["吸边"]
        STATS["修重叠_减法"] = STATS.get("修重叠_减法", 0) + diag["减法"]
        STATS["修重叠_未修"] = STATS.get("修重叠_未修", 0) + diag["未修"]
    return recs


def _floor_recs(name, h):
    """一层的全部轮廓（判断的产物）。"""
    v = _v(name)
    # ★★ 2026-10-17 C005：门洞必须与参照件（build3d 主循环）用**同一批**洞口。
    #   本件原先只喂 `lift_voids`，于是 SU 那一路的门全是实心墙（墙带连续穿过门洞），
    #   而 white 件那一路已把门抠穿 —— 两个估计器（铁律 018/174）。
    #   楼板仍只扣井道（`_lift_v`），门洞只扣墙，与参照件逐字相同。
    wp0 = B3.wall_polys(v)
    _lift_v = B3.lift_voids(v)
    _door_v = B3.door_voids(v, wp0)
    voids = _lift_v + _door_v
    doors = B3.door_polys(v)          # ★ 只调一次：它有 DOOR_AUDIT 记账副作用，调两次账就翻了
    _FLOOR_AUDIT[name] = dict(B3.DOOR_AUDIT)   # 逐层快照（全局账在下一层会被覆盖）
    # ★★ 2026-10-16 梯间清空 + 跨层借形：**与参照件（build3d 主循环）同源**。
    #   两处原先各有各的口径：本件调 `stair_steps(v, h)` **不传 alt**，而参照件传了
    #   ⇒ 「本层装不下双跑、借了上一层」的楼层上，两边楼梯形状本来就不同（铁律 018/174：
    #     两个估计器）。现在两边一律走 `B3.stair_alt` + `B3.stair_and_clear`：
    #   同一趟落位同时给出 ① 逐级块 ② 该清空的梯间区（包络内缩）。
    #   ★ 次序要紧：清空区是**这一趟落位**的产物，不许另调一次 `stair_steps` 去算。
    _names = [n for n, _z, _hh in B3.FLOORS]
    _i = _names.index(name)
    alt = B3.stair_alt(_v(_names[_i + 1])) if _i + 1 < len(_names) else None
    steps, _clear = B3.stair_and_clear(v, h, alt=alt)
    cut = _clear or []               # None（本层没梯）/ []（有梯没清到）都退化成「不扣」
    _wp = B3.carve(B3.carve(wp0, voids), cut)
    _sp = B3.carve(B3.carve(B3.slab_polys(v), _lift_v), cut)
    if cut:
        # ★★ 与参照件同一个条件、同一个函数、同一个阈值：那一刀切出来的短边要塌掉。
        #   本件不塌 ⇒ 正式件轮廓里留着 10 条 < 6.25 mm 的边（闸 `J-10.8-00` ⑪ 当场报红），
        #   而参照件已经塌过 —— 两边又成了两个估计器（铁律 018/174/183）。
        _wp = B3._drop_short_edges(_wp)[0]
        _sp = B3._drop_short_edges(_sp)[0]
    # ★★ 2026-10-19 挑空 —— **与参照件 build3d 主循环逐位同源**（同一个 `B3.void_polys`）。
    #   顺序也照抄：塌短边 → 存未扣版的基板 → 扣挑空 → 裙房屋面切分。
    _SLAB_NOVOID[name] = _sp
    _vv = B3.void_polys(name)
    if _vv:
        _sp = B3._drop_short_edges(B3.carve(_sp, _vv))[0]
    # ★★ 2026-10-17 顶层裙房屋面切分 —— **与参照件同一个函数**（B3.podium_roof_trim），
    #    两边各算一遍必然漂（铁律 018/174；这一处就是刚刚实测漂过的）。
    _sp, _wp, _rdiag = B3.podium_roof_trim(v, _sp, _wp, name)   # 返回 (楼板, 墙, 读数)
    if _rdiag is not None:
        B3.ROOF_DIAG.append(_rdiag)
    # ★★ 2026-10-20 屋面平面层 —— **与参照件同一个函数**（`B3.roof_plan_split`）。
    #   c006「7层」：塔外墙带改女儿墙（基面 = 层底 = 24 m），塔内墙照旧 4 m；楼板整块不动。
    _sp, _wp, _rp = B3.roof_plan_split(v, _sp, _wp, name)
    _rp_recs = []
    if _rp is not None:
        B3.ROOF_PLAN_DIAG.append(_rp["读数"])
        for _p in _rp["女儿墙"]:
            _rp_recs.extend(_rec(_p, "PARAPET", z_mm=0.0))
        # 塔外的板 = 屋面（类 ROOF，板顶 = 层底 + 板厚）——与 build3d 同一个 `_sp` 切法。
        for _p in _rp["屋面板"]:
            _rp_recs.extend(_rec(_p, "ROOF", z_mm=0.0))
    # ★★ 2026-10-17：梯块裁到墙边（与参照件**同一个函数**，墙不动）。见
    #   `B3.clip_steps_to_walls` 的 docstring —— 30 mm 的越界就是这里量出来的。
    steps, _clip = B3.clip_steps_to_walls(steps, _wp)
    if _clip["相交块"] or _clip["碎块"] or _clip["消失块"] or _clip.get("压块对"):
        B3.STAIR_CLIP_DIAG.append(dict(_clip, 层=name))
    recs = []
    # ★★ 2026-10-18 用户「门在墙里面啊」/「要开洞」：源图的门是**关闭姿态**的一条线，
    #   画在墙**中心线**上；照抄成 50 mm 板 ⇒ 230 片门扇全部嵌在 300 mm 墙厚正中，
    #   看上去就是「门埋在墙里」。墙体在门处**已经抠穿**（实测沿扇轴 0/49 被墙挡），
    #   所以洞不用再开，要开的是**别拿一块板把洞堵上**：档案写 `door_leaf_solid: false`
    #   ⇒ 只出洞口、不出门扇实体（lintel 仍拿 `doors` 算，见下面 `lintel_module`）。
    _leaf_solid = B3.B.profile().get("door_leaf_solid", True)
    for polys, layer in ((_wp, "WALL"),
                         (B3.col_polys(v), "COL"),
                         (B3.lift_polys(v), "LIFT"),
                         (doors if _leaf_solid else [], "DOOR")):
        for p in polys:
            recs.extend(_rec(p, layer))
    _is_ground = name == B3.FLOORS[0][0]
    _slab_h = round(B3.STEP_H_M * 1000.0, 1) if _is_ground else None
    for p in _sp:
        recs.extend(_rec(p, "SLAB", h_mm=_slab_h))
    # ★★ 2026-10-21 统一流程：首层入口台阶/花台按 20 cm 高；其上方雨檐 20 cm 厚，
    #   雨檐底标高相对本层地面 3.0 m。首层楼板同步加厚到 20 cm，台面与楼面齐平。
    _stp = B3.step_polys(v)
    for p in _stp:
        recs.extend(_rec(p, "ROOF_STEP", h_mm=round(B3.STEP_H_M * 1000.0, 1)))
        if _is_ground:
            recs.extend(_rec(p, "ROOF_STEP",
                             z_mm=round(B3.CANOPY_Z_M * 1000.0, 1),
                             h_mm=round(B3.CANOPY_T_M * 1000.0, 1)))
    # 屋面平面层：塔外墙带改判的女儿墙（基面 = 层底，高 1.2 m）
    recs.extend(_rp_recs)
    for poly, zrel, hm in steps:                     # 逐级：底标高 + **本块拉伸高度**都不一样
        recs.extend(_rec(poly, "STAIR", z_mm=zrel * 1000.0, h_mm=hm * 1000.0))
    # 门头墙：与楼梯同理，**逐块**自带底标高（= 门洞高）与拉伸高度（= 层高 − 门洞高）
    # ★★ 2026-10-17 C005：`lintel_module` 靠「墙壁上的缺口」找门洞，而 C005 的墙线
    #   连续穿过门洞 ⇒ 它量不到（诊断如实报「无缺口」）。门头墙改由**门洞本身**构造：
    #   被抠掉的那块墙足迹从门洞高补到层高 —— 与参照件 build3d 主循环逐字相同。
    # ★★ 2026-10-18：种子板**递进模块**（不许在返回后拼）—— 记账与出件必须量同一批板。
    _lt = B3.lintel_module(v, h, doors, seed=_door_v)
    for poly, zrel, hm in _lt:
        recs.extend(_rec(poly, "LINTEL", z_mm=zrel * 1000.0, h_mm=hm * 1000.0))
    # ★ 本层楼板落位（= 参照件的 `V_SLAB[name]`）：上面所有顶层件要拿「下一层的板」，
    #   必须取这一份，不许另调 `slab_polys` 重算（铁律 018/174）。
    _SLAB_BY_FLOOR[name] = _sp
    recs.extend(_attach_recs(name, cut, _sp))        # 女儿墙 / 楼梯房 / 7→8 台阶屋面 / 裙房屋面
    if cut:
        # ★ 记录层的最后一道（只给被那一刀动过的层）：`_cut_holes` 的横切线也会削出残边，
        #   多边形那一层看不见它（那时还没切）—— 见 `_collapse_recs` 的说明。
        # ★★ 2026-10-19 补 `PARAPET`（铁律 183：修好一个错法只算改了一半）：
        #   女儿墙环带**本身就是带洞的环**（外圈减内缩 200 mm），所以它 100% 要被
        #   `_cut_holes` 横切；切完在 7 层留下 3.002 / 5.004 mm 两条残边
        #   （`F07-PARAPET-005/013`，闸 `J-10.8-00` ⑪ 唯一的红）。
        #   实测：多边形那一层已按 `RING_EDGE_MIN_MM` 塌过（`_rails_clean`），
        #   但记录的坐标是**切之后**才有的 ⇒ 只能在记录层再塌一次。
        recs = _collapse_recs(recs, ("WALL", "SLAB", "ROOF", "PARAPET", "LINTEL"))
    # ★★ 2026-10-17：**最后一道** —— 同层同类记录不许互相压（`J-10.8-00` ⑫）。
    #   必须放在 `_cut_holes` / `_collapse_recs` **之后**：那两步才会把 0.03 mm 的
    #   浮点错位变成真正的重叠（见 `_fix_rec_overlaps` 的说明）。
    recs = _fix_rec_overlaps(recs)
    return recs


def _write_dxf(recs, path):
    doc = ezdxf.new("R2013", setup=True)
    # ★★ 单位显式写 4 = 毫米；ezdxf 默认 6 = 米 ⇒ SU 会把整层放大 1000 倍
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    ms = doc.modelspace()
    for r in recs:
        for pts in [r["ring"]] + r["holes"]:
            pl = ms.add_lwpolyline(pts, close=True,
                                   dxfattribs={"layer": r["layer"]})
            if r["z"]:
                pl.dxf.elevation = r["z"]    # 楼梯逐级标高（ezdxf 里叫 elevation，不叫 elev）
    doc.saveas(path)


def _count_dxf(path):
    chk = ezdxf.readfile(path)
    by = {}
    for e in chk.modelspace():
        if e.dxftype() == "LWPOLYLINE" and e.closed:
            lay = e.dxf.layer
            by[lay] = by.get(lay, 0) + 1
    return by


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    bad = 0
    # ★ 2026-10-18：先把**所有楼层**的轮廓算完（`_SLAB_BY_FLOOR` 全部落位），
    #   再补 7→8 台阶屋面 —— 它要同时拿 7 层和 8 层的抠后楼板（铁律 018/174）。
    all_recs = []
    for name, z0, h in B3.FLOORS:
        s0 = dict(STATS)
        all_recs.append([name, z0, h, s0, _floor_recs(name, h)])
    # ★ 2026-10-20：7 层是**屋面平面**（档案 `roof_plans`）时，7→8 台阶屋面不存在 ——
    #   那块 28 m 的板与 24 m 的屋面板同址，叠起来就是把裙楼抬成七层。
    if not (B3.B.profile().get("roof_plans") or {}).get("7层"):
        _roof_step_recs(all_recs)
    # ★ 2026-10-18：层间退台屋面（档案 `mid_roofs`）——同样要等所有层的板落位。
    _mid_roof_recs(all_recs)
    # ★★ 2026-10-20：通用下层屋面（本层有板、上层没盖住、本层画着房间 ⇒ 补）。
    _lower_roof_recs(all_recs)
    for name, z0, h, s0, recs in all_recs:
        recs, _dedup_n, _dedup_area = _dedup_contained_recs(recs)
        recs, _union_n = _union_layer_overlaps(recs)
        recs, _repair_n = _repair_bad_rings(recs)
        # ★ `s0.get(k, 0)` 不是 `s0[k]`：`_floor_recs` 里会**新加**计数键（如「塌短边_点」），
        #   那一趟之前 s0 还没有这个键 ⇒ 直接取会 KeyError（2026-10-16 实测踩过一次）。
        cut = dict((k, STATS[k] - s0.get(k, 0)) for k in STATS)
        # ★ 每一条一个**稳定名字**（用户 2026-10-14 要的：他能指着某一块说「这块不对」）：
        #   `id`  = "F01-WALL-007"   程序点名用（ASCII，能进 SU 组名 → OBJ → GLB 节点名）
        #   `name` = "1层-墙体-007"   人念用
        #   按记录顺序编号 ⇒ 同一份上游判断下可复现（上游一改，编号才可能挪）。
        cnt = {}
        for r in recs:
            k = r["layer"]
            cnt[k] = cnt.get(k, 0) + 1
            r["id"] = "%s-%s-%03d" % (FID.get(name, name), k, cnt[k])
            r["name"] = "%s-%s-%03d" % (name, CLS_CN.get(k, k), cnt[k])
        push = dict((k, (int(round(h * 1000)) if v is None else v))
                    for k, v in PUSH_MM.items())
        data = {"floor": name, "z0_m": float(z0), "h_m": float(h),
                "units": "mm", "push_mm": push, "polys": recs,
                "dedup_removed": _dedup_n, "dedup_area_mm2": _dedup_area,
                "union_groups": _union_n, "ring_repairs": _repair_n}
        jpath = os.path.join(OUT, "%s.json" % name)
        dpath = os.path.join(OUT, "%s.dxf" % name)
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        _write_dxf(recs, dpath)

        # ---- 复核①：重开 DXF，逐层数闭合 LWPOLYLINE（环数 = 外环 + 各洞）----
        want = {}
        for r in recs:
            want[r["layer"]] = want.get(r["layer"], 0) + 1 + len(r["holes"])
        by = _count_dxf(dpath)
        # ---- 复核②：重读 JSON，独立再数一遍 ----
        with open(jpath, encoding="utf-8") as f:
            back = json.load(f)
        byj = {}
        for r in back["polys"]:
            byj[r["layer"]] = byj.get(r["layer"], 0) + 1 + len(r["holes"])

        ok = (by == want) and (byj == want) and want.get("WALL", 0) > 1
        if not ok:
            bad += 1
            print("      ★ want=%s" % sorted(want.items()))
            print("      ★ dxf =%s" % sorted(by.items()))
            print("      ★ json=%s" % sorted(byj.items()))
        cnt = dict((k, sum(1 for r in recs if r["layer"] == k)) for k in PUSH_MM)
        rows.append({"floor": name, "z0_m": float(z0), "h_m": float(h),
                     "polys": len(recs), "per_layer": cnt, "cut_in": cut["cut_in"],
                     "cut_out": cut["cut_out"], "holes": cut["holes"],
                     "push_mm": push, "dxf_bytes": os.path.getsize(dpath),
                     "json_bytes": os.path.getsize(jpath),
                     "dedup_removed": _dedup_n, "dedup_area_mm2": _dedup_area,
                     "union_groups": _union_n,
                     "ring_repairs": _repair_n,
                     "reopen_dxf": by, "ok": bool(ok),
                     "door_audit": dict(_FLOOR_AUDIT.get(name) or {})})
        att = "".join(" %s%d" % (k.lower(), cnt[k])
                      for k in ("ROOF", "PARAPET", "ROOF_STAIR", "ROOF_STEP", "ROOF_ROOM")
                      if cnt.get(k))
        # ★ 洞那一列已经**恒 0**（`holes` 恒空是本次修复的目的）—— 留着就是个永远绿的量具
        #   （铁律 137/158）。改成印**剖分台账**：带洞几条 / 几个洞 ⇒ 剖成几条。
        print("%-8s z0=%5.1f h=%.1f | 墙%3d 柱%3d 井%2d 板%3d 门%3d 梯%3d 过%3d%s "
              "| 剖 %d→%d(+%d)/%d洞 | %d 条 %7d 字节 %s"
              % (name, z0, h, cnt["WALL"], cnt["COL"], cnt["LIFT"],
                 cnt["SLAB"], cnt["DOOR"], cnt["STAIR"], cnt["LINTEL"], att,
                 cut["cut_in"], cut["cut_out"], cut["cut_out"] - cut["cut_in"],
                 cut["holes"], len(recs),
                 os.path.getsize(dpath), "ok" if ok else "★复核不过"))
        # ★ 门扇账（`build3d.door_polys` 每次调用写进 `B3.DOOR_AUDIT`）：
        #   修法里有三个「丢掉/合并」的决定，判据 ⑫ 只量「重叠」、量不出「被丢掉」
        #   ⇒ 这个数必须印出来，否则「门少了」这件事没人看得见（铁律 174/028）。
        # ★ 2026-10-20：这里以前读全局 `B3.DOOR_AUDIT`，而它只存**最后一层**的账
        #   ⇒ 逐层印出来的三行是同一组数（c106 实测三层都印 23，实际 41/25/23）。
        #   改成读这一行的 `door_audit`（与 JSON 落盘同一个数）。
        au = (rows[-1].get("door_audit") or {}) if rows else {}
        if au:
            if "voids" in au:
                print("         门扇账：门洞 %d ⇒ 开启 90° 门扇 %d 片（厚 %.0f mm）"
                      % (au["voids"], au["open90"], au.get("open_t_mm", 0.0)))
            else:
                _off = ("没量到（算不出墙带）" if au.get("off_wall") is None
                        else "%d 片（最远 %s m）" % (au["off_wall"], au.get("off_wall_max_m")))
                print("         门扇账：两点段 %d（源图重复去掉 %d）⇒ 闭合轮廓 %d ＋ 成对补 %d"
                      " ＋ 线弧型补 %d；孤立线丢 %d 段，近重合叶并掉 %d 片"
                      "，离墙超限丢 %s"
                      % (au["seg"], au["dup_seg"], au["closed"], au["paired"],
                         au["arc_line"], au["dropped"], au["near_dup"], _off))

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print("→ %s  (%d 层，复核不过 %d 层)" % (OUT, len(rows), bad))
    # ★ 剖分台账：这条读数就是「洞真的被切掉了」的凭据（SU 那侧不可能再抠洞）
    print("剖分：带洞 %d 条 / %d 个洞 ⇒ 剖成 %d 条（+%d）"
          % (STATS["cut_in"], STATS["holes"], STATS["cut_out"],
             STATS["cut_out"] - STATS["cut_in"]))
    return 4 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
