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
from shapely.geometry import Polygon as SPoly
from shapely.geometry import box as sbox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
import build3d as B3          # noqa: E402  （只用它的提取器与常数，不跑 main）
import redraw as RD           # noqa: E402

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

# 层的**稳定 ASCII 号**（`id` 用）：地下1层→B1、1层→F01 … 11层→F11
FID = dict([("地下1层", "B1")] + [("%d层" % i, "F%02d" % i) for i in range(1, 12)])

# 剖分台账（**不是注释**：跑完要能报出「剖了几条、多出几条」，否则「修好了」没有读数支撑）
STATS = {"cut_in": 0, "cut_out": 0, "holes": 0}


def _rel_z(name, z_abs_mm):
    """绝对标高 → **本层相对标高**。

    ★★ 2026-10-13 实测踩过：记录里的 `z` 是**相对本层底面**的（SU 脚本写 `zbase + pr["z"]`，
       `zbase = z0*1000`）。第一版把**绝对**标高写进去 ⇒ 女儿墙落到 **84000 mm**
       （40 m 层底 + 44 m 绝对），台阶屋面落到 **51880 mm** —— 两个原点相加。
       症状：SU 日志与 `BBOX_mm size=[…, 90500.0]` 都「正常」，只有总高从 50.5 m 变成 90.5 m
       才露出来（铁律 174：两个同名的量必须死掉一个 —— 这里就是「记录 z」这一个量只能有一个原点）。
    """
    z0, h = _FLOOR[name]
    zrel = z_abs_mm - z0 * 1000.0
    if not (-1.0 <= zrel <= h * 1000.0 + 1.0):
        raise AssertionError(
            "%s 的相对标高 %.1f mm 不在 [0, %.0f] 内 —— 十有八九又把绝对标高写进来了（两个原点）"
            % (name, zrel, h * 1000.0))
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


def _attach_recs(name):
    """顶部三件（女儿墙 / 顶楼楼梯房 / 7→8 台阶屋面）——**与参照件调同一批 build3d 函数**，
    所以「判断」只做一次，两边不会各推一套。挂在它们所属的楼层上：
    女儿墙与楼梯房挂 11层（基面 = TOP_M），台阶屋面挂 7层。
    """
    out = []
    if name == "11层":
        v = _v(name)
        # ★★ 塔楼屋面板（2026-10-15 用户「楼板要画」补）—— **与 `build3d.py:957` 逐字同源**：
        #    同一个 `carve(slab_polys(v), lift_voids(v))`，同一个 `TOP_M − SLAB_M`。
        #    少抠井道 / 换个 z，参照件与正式件就各说各话（铁律 018/174）。
        #    相对本层底面 = 层高 − 板厚 = 3380 mm；板顶正好停在层高线 38.5 m。
        out += _rec_many(B3.carve(B3.slab_polys(v), B3.lift_voids(v)), "ROOF",
                         z_mm=_rel_z(name, (B3.TOP_M - B3.SLAB_M) * 1000.0))
        # 女儿墙/楼梯房基面 = 顶层楼板顶 = B3.TOP_M（= 11 × 层高）。
        # ★ 别在这行写死一个数（原先写「44.0 m」）—— 2026-10-15 用户令层高 3.5 m ⇒ 这里是 38.5 m。
        z = _rel_z(name, B3.TOP_M * 1000.0)
        out += _rec_many(B3.parapet_polys(v), "PARAPET", z_mm=z)
        out += _rec_many(B3.roof_stair_polys(v), "ROOF_STAIR", z_mm=z)
    if name == "7层":
        # ★ 与 build3d.py 里那段的常数一致：只给 7→8 加板（另两处影像实测是空地，加了就是盖错）
        from shapely.ops import unary_union as _uu
        a = _uu(B3.slab_polys(_v("7层")))
        b = _uu(B3.slab_polys(_v("8层")))
        d = a.difference(b).buffer(0) if (not a.is_empty and not b.is_empty) else a
        rp = [g for g in B3._split(d) if g.area > 1e6]
        out += _rec_many(rp, "ROOF_STEP",
                         z_mm=_rel_z(name, (7 * B3.STOREY_M - B3.SLAB_M) * 1000.0))
    return out


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
          "ROOF_STAIR": "屋顶楼梯房", "ROOF_STEP": "台阶屋面", "ROOF": "屋面板"}


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
    if g is None or g.is_empty or not g.interiors:
        return [g] if (g is not None and not g.is_empty) else []
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
            ring = _dedup([[round(float(x), 1), round(float(y), 1)]
                           for x, y in pc.exterior.coords])
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


def _floor_recs(name, h):
    """一层的全部轮廓（判断的产物）。"""
    v = _v(name)
    voids = B3.lift_voids(v)
    doors = B3.door_polys(v)          # ★ 只调一次：它有 DOOR_AUDIT 记账副作用，调两次账就翻了
    recs = []
    for polys, layer in ((B3.carve(B3.wall_polys(v), voids), "WALL"),
                         (B3.col_polys(v), "COL"),
                         (B3.lift_polys(v), "LIFT"),
                         (B3.carve(B3.slab_polys(v), voids), "SLAB"),
                         (doors, "DOOR")):
        for p in polys:
            recs.extend(_rec(p, layer))
    for poly, zrel, hm in B3.stair_steps(v, h):      # 逐级：底标高 + **本块拉伸高度**都不一样
        recs.extend(_rec(poly, "STAIR", z_mm=zrel * 1000.0, h_mm=hm * 1000.0))
    # 门头墙：与楼梯同理，**逐块**自带底标高（= 门洞高）与拉伸高度（= 层高 − 门洞高）
    for poly, zrel, hm in B3.lintel_module(v, h, doors):
        recs.extend(_rec(poly, "LINTEL", z_mm=zrel * 1000.0, h_mm=hm * 1000.0))
    recs.extend(_attach_recs(name))                  # 女儿墙 / 楼梯房 / 7→8 台阶屋面
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
    for name, z0, h in B3.FLOORS:
        s0 = dict(STATS)
        recs = _floor_recs(name, h)
        cut = dict((k, STATS[k] - s0[k]) for k in STATS)
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
                "units": "mm", "push_mm": push, "polys": recs}
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
                     "reopen_dxf": by, "ok": bool(ok),
                     "door_audit": dict(B3.DOOR_AUDIT)})
        att = "".join(" %s%d" % (k.lower(), cnt[k])
                      for k in ("ROOF", "PARAPET", "ROOF_STAIR", "ROOF_STEP") if cnt[k])
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
        au = B3.DOOR_AUDIT
        if au:
            print("         门扇账：两点段 %d（源图重复去掉 %d）⇒ 闭合轮廓 %d ＋ 成对补 %d"
                  " ＋ 线弧型补 %d；孤立线丢 %d 段，近重合叶并掉 %d 片"
                  % (au["seg"], au["dup_seg"], au["closed"], au["paired"],
                     au["arc_line"], au["dropped"], au["near_dup"]))

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
