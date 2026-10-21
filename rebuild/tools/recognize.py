# -*- coding: utf-8 -*-
"""从底图 DXF **识别**一层的墙体 → 重画成干净 DXF + 出审图 PNG。

为什么不是「手搓几何」：这里一个布尔运算、一个配对都不写。
  · 栅格化 + 连通域 = OpenCV/NumPy 的引擎；
  · 判厚薄只比一个数（等截面宽度 w = 2A/P）；
  · 出口是**闭合多段线**，给人和 SU/Blender 看。
上一轮翻车的是「自己配对双线、自己 buffer 闭运算」，那是几何构造；这里是识别。

识别原理（两句话）：
  把墙层每一条线按 STROKE 宽画进栅格当**墙**。墙的两皮线（间隔≈墙厚）夹出来的
  一条细带 = 一个连通域；房间是一个大域；室外是与图边相接的那个域。
  每个域量 w = 2A/P（mm）：墙带 w≈墙厚（数百 mm），房间 w≈数米 ⇒ 用 WALL_MAX 分开。

★ 分辨力当场可见：跑完打印 w 直方图；两峰分不开就说明判据没分辨力，不许当结论。
★ 反证：`--positive` 用**合成件**（已知的几条墙 + 一个房间）跑一遍，判据必须把它
  分成「墙 n 条 / 空 1 条」，且墙面积 = 手算值。合成件不通过 ⇒ 整份识别结果作废。

输出：
  rebuild/02_recognize/<层名>.json   逐域 {A,P,w,kind,label}
  rebuild/03_redraw/<层名>.dxf      重画的干净图（层 REDRAW-WALL / REDRAW-HOLE）
  rebuild/03_redraw/<层名>.png      审图：底图浅灰 + 判出的墙实色 + 逐段编号
用法：
  python rebuild/tools/recognize.py --floor 8层     # 单层
  python rebuild/tools/recognize.py --all           # 全部楼层，一个进程（实测 12 层 59.3 s → 41.3 s）
  python rebuild/tools/recognize.py --positive      # 反证：合成件必须通过
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import sys

import cv2
import numpy as np
import ezdxf
from ezdxf.math import bulge_to_arc

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import building as B                                                    # noqa: E402
import door_rule as DR                                                  # noqa: E402

# ★ 2026-10-17：数据根与「源图怎么画」改从楼栋档案读（不设环境变量 = c006，行为不变）。
ROOT = B.ROOT
RAW = os.path.join(ROOT, "01_cad", "raw")
OUT_REC = os.path.join(ROOT, "02_recognize")
OUT_RED = os.path.join(ROOT, "03_redraw")
_DRAW = B.profile().get("drawing", {})
STAIR_MODE = _DRAW.get("stairs", "anchor")      # anchor=图上写「上/下」；treads=没有锚点，靠几何
#                                          auto=先看有没有「上/下」锚点，没有就走几何（见 `_stair_mode`）
DOOR_MODE = _DRAW.get("doors", "block")         # block=INSERT；symbols=墙层上的多点多段线
DOOR_MIN_PTS = 16                               # 老口径兜底值（档案没写形状三项时才用）
# ★★ 2026-10-19：门符号判据**唯一一份**在 `door_rule.py`（与 redraw / overlay_check 共用）。
#   原先这里是写死的「≥16 点」，芙蓉园一族图（门 14 点、真墙链 22 点）会把墙当门丢掉。
_IS_DOOR = DR.make_predicate(_DRAW)
ACACHE = os.path.join(OUT_REC, "_acache")   # analyze() 的磁盘缓存（--no-acache 关掉）
ACACHE_ON = True

# ★ 2026-10-17：墙层名**逐栋不同**（`4.2墙体` 101 张图 / `4墙体` 5 张）⇒ 从源图现认
#   （档案 `wall_layer` 可覆盖）。写死的后果是另一些楼读到 0 条墙线、建出空房子。
WALL_LAYER = B.layer("wall", "4.2墙体")
RES = 25.0                 # mm / px
STROKE = 50.0              # 画线的总宽（mm）—— 够封住发丝缝，又不填死墙带
PAD = 2000.0               # 栅格外扩（mm），保证外圈能连通到边界
WALL_MAX = 600.0           # w < 此值 ⇒ 判墙（mm）
MIN_AREA = 0.05            # 域面积下限（m²），更小的当噪声丢
APPROX = 2.0               # 矢量化抽稀：RES 的倍数
WALL_GAP = 260.0           # 闭合核直径（mm）—— 把双线墙两皮之间的空档并成实心
TREAD_MAX = 3000.0         # 踏步线判据：短于此且中点落在锚区内（mm）


# ------------------------------------------------------------------ 层表（只此一份）
def raw_floors():
    """**该做哪几层，由输入目录说话**：`01_cad/raw/` 里有哪些 `<层名>.dxf`，就是哪些层。

    ★ 不在这里另立一张硬编码层名表 —— `build3d.FLOORS`、`lint_detached.FLOORS`、
      `su_step2_build.rb` 的 `ALL_FLOORS` 已经各有一份副本（同一个量的多份副本要死掉）。
      排序只为打印好看（地下1层 → 1..11层），**不构成第二处权威**。
    """
    names = [os.path.splitext(f)[0] for f in os.listdir(RAW) if f.endswith(".dxf")]

    def _key(n):
        if n.startswith("地下"):
            return (-1, 0)
        d = "".join(c for c in n if c.isdigit())
        return (0, int(d)) if d else (1, 0)

    return sorted(names, key=_key)


# ★★ 2026-10-18（用户「c004 的门和门上面的墙不对」）：「开启弧」画法的门符号**也在墙层上**。
#   实测 c004 1 层：26 条 r=1200 的 ARC + 26 条等长扇线（2 点折线，一端在弧心上）。
#   不剔的后果（同一处竖切 x=7480 实测）：弧 + 扇线把「门扇扫过的扇形」圈成一个细域
#   （w≈190 mm < WALL_MAX）⇒ 第二级「细空域补墙」把整块扇形并成墙 ⇒ 门那一竖的墙厚
#   240 → **1100 mm**；门头墙由门洞现算，跟着 240 → 435 mm —— 正是用户看到的「不对」。
#   剔掉后同一处只剩门线上 50 mm 的一条笔画，门洞两侧各回各的墙。
#   开关在**档案**：没有 `doors_arc_r_mm` 的楼（symbols 62 栋 / block 1 栋）整段不执行。
#   （判定本身在 `door_rule.door_symbol_geom`，这里不再留常量副本 —— 铁律 174。）


def door_symbol_geom(doc):
    """墙层上属于**门符号**的几何：开启弧 + 与弧配对的扇线。→ (弧键集, 扇线键集)

    ★ 2026-10-20：判据**已搬到 `door_rule.door_symbol_geom`**（唯一一份）——
      `overlay_check` 也要用它（覆盖判据把门扇线当成「原始墙」）。这里只把本栋档案递进去；
      口径逐字未改，调用方看到的仍是同一个函数名、同一份结果。
    """
    return DR.door_symbol_geom(doc, _DRAW)


# ------------------------------------------------------------------ 取墙层线段
def wall_segments(path, keep_circle=False, doc=None):
    """墙层线段。`doc` 给了就用，没给才自己读 —— 读一遍 DXF 实测 **0.31 s**，
    而 `analyze` 里三处（本函数 / `stair_zones` / `tread_lines`）用的是**同一份文件**。"""
    doc = ezdxf.readfile(path) if doc is None else doc
    _arc_keys, _leaf_keys = door_symbol_geom(doc)

    def _is_leaf(p, q):
        """这一**段**是不是扇线（判据全在 `door_symbol_geom`，这里只查表）。"""
        return (round(p[0], 1), round(p[1], 1),
                round(q[0], 1), round(q[1], 1)) in _leaf_keys

    segs = []
    for e in doc.modelspace():
        if e.dxf.layer != WALL_LAYER:
            continue
        t = e.dxftype()
        if t == "LINE":
            a, b = e.dxf.start, e.dxf.end
            if _leaf_keys and _is_leaf((a.x, a.y), (b.x, b.y)):
                continue
            segs.append(((a.x, a.y), (b.x, b.y)))
        elif t == "LWPOLYLINE":
            pts = list(e.get_points("xyseb"))
            # ★ 2026-10-17 同 ARC 那一处：`get_points` 给的是 **OCS**。镜像折线（extrusion
            #   非 (0,0,1)）同样会落到镜像另一侧；c105 六层实测 0 条镜像折线，c006 也全是
            #   单位 extrusion ⇒ 只有真碰上才转，默认路径逐字不变。
            #   盲区：反射下 bulge 的符号也该翻，这里**没有**翻（没有实例可验，不凭空写规则）。
            if tuple(e.dxf.extrusion) != (0.0, 0.0, 1.0):
                _o = e.ocs()
                pts = [(lambda w: (w[0], w[1]) + tuple(p[2:]))(_o.to_wcs((p[0], p[1], 0.0)))
                       for p in pts]
            # ★ 2026-10-17：`doors="symbols"` 的图（C005）把门画在**墙层**上（16/23 点多段线，
            #   带开启弧）。它们是门，不是墙：混进栅格会在房间里留下细弧、并把门洞糊住。
            #   8 点及以下的折线是 L 形墙链（实测 C005 有 10 条），不在此列。
            # ★ 2026-10-19：判据改用 `door_rule`（点数 + 宽度窗 + 近方形 + 必须带弧）。
            #   老写法 `len(pts) >= 16` 会把 22 点的真墙链当门丢掉（c034 2 层 40 条）。
            if DOOR_MODE == "symbols" and _IS_DOOR(
                    [p[0] for p in pts], [p[1] for p in pts],
                    any(abs(p[4]) > 1e-9 for p in pts)):
                continue
            # ★ 2026-10-18：开启弧画法的**扇线**也是门符号，不许当墙。
            #   ★ 判**逐段**不判整条折线：c004 把「柱子矩形 + 扇线」画在同一条 13 点折线里，
            #     按整条折线判（`len(pts)==2`）会把扇线漏掉 ⇒ 门洞被糊住。
            for i in range(len(pts) - 1):
                if _leaf_keys and _is_leaf(pts[i], pts[i + 1]):
                    continue
                segs.extend(_arc(pts[i], pts[i + 1]))
            if e.closed and len(pts) > 2 and not (_leaf_keys and _is_leaf(pts[-1], pts[0])):
                segs.extend(_arc(pts[-1], pts[0]))
        elif t == "ARC":
            # ★ 2026-10-18：半径落在档案弧窗内的 ARC = 门的**开启弧**，不是墙。
            if _arc_keys:
                _c = e.dxf.center
                if (round(_c[0], 1), round(_c[1], 1),
                        round(e.dxf.radius, 1)) in _arc_keys:
                    continue
            segs.extend(_arc_from_arc(e))
        elif t == "CIRCLE" and keep_circle:
            segs.extend(_circle(e))            # 全圆是**圆柱**，不是墙
    return segs


def _stair_mode(doc):
    """档案写 `stairs: "auto"` 时，按**这张图有没有锚点**现选 anchor / treads。

    ★ 为什么要它：65 栋楼逐栋手挑「这栋有没有写 上/下」不现实，而且挑错了不报错
      （锚点模式下找不到锚 ⇒ 0 个梯区 ⇒ 楼梯整段不建，看上去像「这层没楼梯」）。
      auto 的判据只有一条：墙层上有没有 `上`/`下` 的 TEXT。有就走锚点（锚点是源图自己写的），
      没有就走几何（踏步成跑）。两种后续判据都是原来那一份，不另写。
    ★ 读数必须打出来：选了什么、另一条路有多少读数 —— 不然「自动」就等于「不说」。
    """
    if STAIR_MODE != "auto":
        return STAIR_MODE
    n_anchor = 0
    for e in doc.modelspace():
        if e.dxf.layer == WALL_LAYER and e.dxftype() == "TEXT" \
                and e.dxf.text.strip() in ("上", "下"):
            n_anchor += 1
    mode = "anchor" if n_anchor else "treads"
    print("   ▷ 楼梯画法：锚点 %d 个 ⇒ 采用 %s" % (n_anchor, mode))
    return mode


def stair_zones(path, doc=None):
    """楼梯范围 = 锚（`上`/`下` 文字）附近那一团**短平行线**（踏步）的外包框。

    ★ 为什么要把踏步从墙里剔掉：踏步线在墙层上、彼此只隔 ~280 mm，栅格化后
      在踏步之间留下一堆细条 —— 形状与「240 厚的墙」一模一样，w 判据分不开。
      它们是**楼梯**这个独立构件，本来就该另算。这里靠锚定位，不靠形状。
    """
    doc = ezdxf.readfile(path) if doc is None else doc
    if _stair_mode(doc) == "treads":
        # ★ 2026-10-17 C005：图上**没有**「上/下」文字（0 个 TEXT；墙层 24 条 MTEXT 全是房间名）。
        #   改用纯几何：墙层里成跑的等距短线就是梯段，包络即锚区。
        #   ★ 盲区：这一步只给出**候选范围**；哪些线算踏步仍由 `tread_lines/group_flights`
        #     同一份判据决定（成跑 ≥4 条、步距 180~400、共享一端），这里不另判一次。
        segs = [s for s in wall_segments(path, doc=doc)
                if 100.0 < math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]) < TREAD_MAX]
        groups = group_flights(segs)
        keep = [g for g in groups if _same_length(g)]
        if len(keep) != len(groups):
            print("  剔异长假梯跑 %d 个（踏步线长度不成族，实为楔形/折断符号）"
                  % (len(groups) - len(keep)))
        return _merge_zones([_zone_of(g) for g in keep])
    anchors = []
    for e in doc.modelspace():
        if e.dxf.layer != WALL_LAYER or e.dxftype() != "TEXT":
            continue
        if e.dxf.text.strip() in ("上", "下"):
            p = e.dxf.insert
            anchors.append((p.x, p.y))
    if not anchors:
        return []
    lines = [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))
             for e in doc.modelspace()
             if e.dxf.layer == WALL_LAYER and e.dxftype() == "LINE"]
    ln = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in lines]
    # ★ 2026-10-15：把「只可能是踏步的短线」与它们的中点各算**一次**。
    #   旧写法在 `while` 里对**全部** lines 逐个走、且每轮重算中点 —— 1 层实测 41.3 万次
    #   `seg_dist` 调用（0.29 s，占该层冷跑的 21%）。挑短线这个判据（`Ln < 3000`）
    #   原式里本来就有，只是写在循环体内：搬到外面**被接受的 j 集合不变**，
    #   `short` 又是 `range(len(lines))` 的子序列 ⇒ 推栈次序也不变，
    #   而洪泛的最终集合只由可达性决定 ⇒ `inc` 逐元素相同。
    short = [k for k in range(len(lines)) if ln[k] < 3000.0]
    smid = [((lines[k][0][0] + lines[k][1][0]) / 2.0,
             (lines[k][0][1] + lines[k][1][1]) / 2.0) for k in short]

    def seg_dist(p, s):
        (ax, ay), (bx, by) = s
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        t = 0.0 if L2 < 1e-9 else max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / L2))
        return math.hypot(p[0] - (ax + t * vx), p[1] - (ay + t * vy))

    out = []
    used = set()
    for i, an in enumerate(anchors):
        if i in used:
            continue
        grp = [an]
        for j in range(i + 1, len(anchors)):
            if j not in used and (anchors[j][0] - an[0]) ** 2 \
                    + (anchors[j][1] - an[1]) ** 2 < 5000.0 ** 2:
                grp.append(anchors[j])
                used.add(j)
        used.add(i)
        gx = sum(p[0] for p in grp) / len(grp)
        gy = sum(p[1] for p in grp) / len(grp)
        # 从锚往外**一串**：只吃「短线」（踏步），一旦碰到长线（真墙）就停。
        inc = set()
        stack = [k for k in short if seg_dist((gx, gy), lines[k]) < 2500.0]
        while stack:
            k = stack.pop()
            if k in inc:
                continue
            inc.add(k)
            for t, j in enumerate(short):
                if j in inc:
                    continue
                if seg_dist(smid[t], lines[k]) < 900.0:
                    stack.append(j)
        if len(inc) < 3:
            continue
        xs = [p[0] for k in inc for p in lines[k]]
        ys = [p[1] for k in inc for p in lines[k]]
        out.append((min(xs) - 200.0, min(ys) - 200.0,
                    max(xs) + 200.0, max(ys) + 200.0))
    return out


def in_zone(x, y, zones):
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in zones)


def _arc(p0, p1):
    x0, y0, b = float(p0[0]), float(p0[1]), float(p0[4]) if len(p0) > 4 else 0.0
    x1, y1 = float(p1[0]), float(p1[1])
    if abs(b) < 1e-12:
        return [((x0, y0), (x1, y1))]
    # ★★ 2026-10-17 C105：`ezdxf.math.bulge_to_arc` 返回 **(center, 起始角, 终止角, 半径)**，
    #   这里原来按 `(center, r, sa, ea)` 拆 ⇒ 半径与两个角全错位。c006 的墙是 LINE，
    #   从不走 bulge ⇒ 这个错法一直没露头；c105 一层两条墙折线带 bulge 0.0047
    #   ⇒ 半径 202759 mm 被当成终止角，弧绕着 (106067, −101916) 扫了 20 万弧度，
    #   凭空在模型里造出 8856 段墙（整栋 y 范围 −101.9 → 120.3 m，实际只到 39.5 m）。
    (cx, cy), sa, ea, r = bulge_to_arc((x0, y0), (x1, y1), b)
    return _arc_pts(cx, cy, r, sa, ea)


def _arc_from_arc(e):
    # ★★ 2026-10-17 C105 实测：ARC 的 `center`/`start_angle`/`end_angle` 是 **OCS**，不是世界坐标。
    #   镜像画的弧（extrusion = (0,0,-1)）照抄 center.x ⇒ 落到**镜像的另一侧**：c105 一层 95 个、
    #   二层 30 个这样的弧，实测把整栋平面包围盒从 184 m 涨到 **441 m**（x 到 −217 m），
    #   症状不是报错，是模型里凭空多出一片墙、房间色块配准全挂。
    #   `redraw.door_arcs` 早就用 `e.ocs().to_wcs(...)` 改对了 —— 这里是同一个错法漏掉的一处
    #   （铁律 183：修好一个错法只算改了一半）。按**采样点**逐个转 WCS：镜像下扫描方向反过来
    #   无所谓，线段集合不变。
    c = e.dxf.center
    return _arc_pts(c.x, c.y, e.dxf.radius,
                    math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle),
                    ocs=e.ocs())


def _circle(e):
    c = e.dxf.center
    return _arc_pts(c.x, c.y, e.dxf.radius, 0.0, 2 * math.pi, ocs=e.ocs())


def _arc_pts(cx, cy, r, sa, ea, ocs=None):
    if ea < sa:
        ea += 2 * math.pi
    n = max(2, int(abs(ea - sa) * r / 60.0) + 1)      # 弦长≈60mm
    out = []
    pm = None
    for k in range(n + 1):
        a = sa + (ea - sa) * k / n
        p = (cx + r * math.cos(a), cy + r * math.sin(a))
        if ocs is not None:
            w = ocs.to_wcs((p[0], p[1], 0.0))
            p = (w[0], w[1])
        if pm is not None:
            out.append((pm, p))
        pm = p
    return out


# ------------------------------------------------------------------ 栅格化 + 连通域
def rasterize(segs, res=RES, stroke=STROKE, pad=PAD):
    xs = [p[0] for s in segs for p in s]
    ys = [p[1] for s in segs for p in s]
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    W = int(math.ceil((x1 - x0) / res)) + 1
    H = int(math.ceil((y1 - y0) / res)) + 1
    img = np.zeros((H, W), np.uint8)

    def px(p):
        return (int(round((p[0] - x0) / res)), int(round((p[1] - y0) / res)))

    t = max(1, int(round(stroke / res)))
    for a, b in segs:
        cv2.line(img, px(a), px(b), 255, thickness=t, lineType=cv2.LINE_8)
    return img, (x0, y0, res)


def components(img):
    bg = (img == 0).astype(np.uint8)
    n, lab = cv2.connectedComponents(bg, connectivity=4)
    return n, lab


def components_stats(img):
    """同 `components()` 的标注，**外加**逐域的 面积 / 外框 / 质心（一次遍历到手）。

    ★ 为什么必须换（2026-10-15 冷跑剖面，1 层 6.77 s）：旧写法对**每个域**都在整张
      18.7 Mpx 图上重扫 —— `np.nonzero` 51 次 = **2.23 s**、`ndarray.sum` = 1.09 s、
      `astype(int8)` = 0.60 s、比较/归约 1.13 s。而每个域真正占的地方只有它自己的外框。
    ★ `recs[].id` 直接写进 `02_recognize/*.json`，所以**编号必须与旧路逐位相同**：
      这不是嘴上保证的 —— 冷跑重算后与留档件逐字节比过（`--no-acache` 一趟，60 个文件全同）。
    """
    bg = (img == 0).astype(np.uint8)
    n, lab, st, cc = cv2.connectedComponentsWithStats(bg, connectivity=4)
    return n, lab, st, cc


def comp_metrics(mask, res, A_px=None):
    """量一个域：自由面积 A、周长 P、等截面宽度 w = 2A/P（mm）。

    ★ 面积取**像素个数**、周长取**格边数**——不是 contourArea/arcLength。
      为什么：环形域（外墙那一圈）用外轮廓的 contourArea 会把中间的房间算进去，
      面积虚高一个量级、w 直接飙到几米，环被误判成「空」。格边数把内外两层
      周长都算上，环的 w 才回到墙厚。

    ★ 回报的 w 已做**画线回补**：测量的是「被 STROKE 吃掉两边的自由带」，
      真墙厚 = 自由带宽 + STROKE。不补的话 240 的墙会被量成 ~175（系统性偏低），
      数字虽然还远小于 600 不影响分档，但报出去的厚度是假的。

    ★ `A_px` 可传入（`connectedComponentsWithStats` 已经数过像素个数）—— 省掉一次
      整图 `sum()`；不传就自己数。**量具只有这一份**，两条路走的是同一段代码。
    """
    A_px = int(mask.sum()) if A_px is None else int(A_px)
    if A_px == 0:
        return None
    c = mask.astype(np.int8)
    e = int((c[:, :-1] != c[:, 1:]).sum()) + int((c[:-1, :] != c[1:, :]).sum())
    if e == 0:
        return None
    A = A_px * res * res
    P = e * res
    return A, P, 2.0 * A / P + STROKE


# ------------------------------------------------------------------ 合成正对照
def _synth_room():
    """已知答案的合成件：外框 10000×6000 房间，墙厚 240；内部一道 240 厚隔墙。"""
    W, H, T = 10000.0, 6000.0, 240.0
    # 真实画法：内皮线**停在墙角**（不贯通全长）
    return W, H, T, [((0, 0), (W, 0)), ((0, H), (W, H)),        # 外皮：贯通
                     ((0, 0), (0, H)), ((W, 0), (W, H)),
                     ((T, T), (W - T, T)), ((T, H - T), (W - T, H - T)),   # 内皮：停在角
                     ((T, T), (T, H - T)), ((W - T, T), (W - T, H - T)),
                     # 中间隔墙（同一套双线，贯通内皮之间）
                     ((W / 2, T), (W / 2, H - T)), ((W / 2 + T, T), (W / 2 + T, H - T))]


def positive_case():
    """正对照：合成件跑**主识别那条码路**（solid_from_segs），比对**解析解**。

    ★ 期望值带 STROKE：描线是**居中**的，所以实心墙带 = 真墙厚 + STROKE。
      这不是误差、是这条链的**系统性偏置**（240 的墙会量成 ~290），
      所以它必须出现在期望值里 —— 若藏起来，正对照只会「看起来过了」。
      出口（建模用）若在意这 50 mm，按 STROKE 胀出来的一圈回缩即可。
    """
    W, H, T, segs = _synth_room()
    r = solid_from_segs(segs, quiet=True)
    s = STROKE / 2.0
    # 解析解：描线居中 ⇒ 每条墙面线各向外胀 s；房间 = 两皮**内边**之间
    room_w = W / 2 - 2 * T - 2 * s
    room_h = H - 2 * T - 2 * s
    exp_open = room_w * room_h / 1e6            # m²（★ 单位写在一处，别两处各写一遍）
    frame = (W + 2 * s) * (H + 2 * s) / 1e6
    exp = frame - 2 * exp_open
    got, openA = r["A_wall"], r["A_open"]
    print("== 合成正对照（实心版，跑主识别同一条码路）==")
    print("  判墙面积 %.3f m²（解析解 %.3f = 外框 %.3f − 2×房 %.3f）"
          % (got, exp, frame, exp_open))
    print("  判空面积 %.3f m²（解析解 %.3f = 2 × %.2f×%.2f）"
          % (openA, 2 * exp_open, room_w, room_h))
    print("  中轴墙厚 %.0f mm（真厚 240 + 画线 %.0f ≈ %d，栅格 ±1 px = ±%.0f）"
          % (r["thick"], STROKE, 240 + STROKE, RES))
    n_open = sum(1 for x in r["recs"] if x["kind"] == "open")
    # ★ 只判**面积与房间数**：这两样是出口（多边形）直接决定的东西，且解析解精确。
    #   墙厚**只报不判** —— 它是栅格化的副产品，实测系统性偏大 ~1 格（见上），
    #   拿它当闸只会把「尺子粗」误报成「识别坏」。
    ok = (abs(got - exp) / exp < 0.02
          and n_open == 2
          and abs(openA - 2 * exp_open) / (2 * exp_open) < 0.02)
    print("  对照明细：墙 %.3f/%.3f（%.2f%%）· 空 %.3f/%.3f（%.2f%%）· 房间数 %d/2"
          % (got, exp, 100 * abs(got - exp) / exp,
             openA, 2 * exp_open, 100 * abs(openA - 2 * exp_open) / (2 * exp_open),
             n_open))
    print("  正对照：%s" % ("PASS" if ok else "★ FAIL —— 识别结果不许当结论"))
    return 0 if ok else 1


def positive_bands():
    """旧版（连通域+厚薄）的正对照 —— 留档，说明那一版在合成件上是能过的。"""
    W, H, T, segs = _synth_room()
    img, geo = rasterize(segs)
    n, lab = components(img)
    walls, opens = [], []
    for i in range(1, n):
        m = (lab == i).astype(np.uint8)
        r = comp_metrics(m, geo[2])
        if r is None:
            continue
        A, _P, w = r
        if A / 1e6 < MIN_AREA:
            continue
        touch = (lab[0, :] == i).any() or (lab[-1, :] == i).any() \
            or (lab[:, 0] == i).any() or (lab[:, -1] == i).any()
        if touch:
            continue
        (walls if w < WALL_MAX else opens).append((A / 1e6, w))
    s = STROKE / 2.0
    ring = ((W - 2 * s) * (H - 2 * s)) - ((W - 2 * (T - s)) * (H - 2 * (T - s)))
    part = (T - 2 * s) * (H - 2 * (T - s))
    exp_wall = (ring + part) / 1e6
    got_wall = sum(a for a, _ in walls)
    print("== 旧版正对照（连通域+厚薄，留档）==")
    print("  判墙 %d 段（合计 %.3f m²）/ 判空 %d 个" % (len(walls), got_wall, len(opens)))
    print("  期望墙 ≈ %.3f m²（外墙环 %.3f + 隔墙 %.3f）"
          % (exp_wall, ring / 1e6, part / 1e6))
    ok = (len(opens) == 2 and walls
          and abs(got_wall - exp_wall) / exp_wall < 0.15)
    print("  正对照：%s" % ("PASS" if ok else "★ FAIL"))
    return 0 if ok else 1


# ------------------------------------------------------------------ 真踏步（梯段）
TREAD_ANG_TOL = 1.5              # 同一跑内，踏步线方向必须一致（度）
GO_MIN, GO_MAX = 180.0, 400.0    # 合理踏面进深（mm）—— 实测本套图恒 270.0
FLIGHT_SIDE_TOL = 80.0           # 「共享一条边」容差（mm）：折断线斜切后远端仍对齐
TREAD_MIN_LEN = 600.0            # 短于此的不是踏步，是填充/箭头碎线（实测 110.4 的条纹）
FLIGHT_MIN = 4                   # 一跑至少几条线（= 至少 3 级）才算梯段


def line_key(seg):
    """一条线 → 判据量 + 原坐标：长度 / 角度 / 法向位置 off / 沿向位置 par / 两端 lo,hi。

    方向**不分正负**（一条线正着画反着画是同一条）：角度一律取 `% 180`，
    比较时按圆的差（`min(d, 180-d)`），否则 0.1° 与 179.9° 会被当成两族。
    `lo`/`hi` = 两端点在**走向**上的投影（小的/大的）—— 折断线斜切后同一跑仍共享一端。
    """
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(dy, dx)) % 180.0
    ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    p0, p1 = x0 * ux + y0 * uy, x1 * ux + y1 * uy
    return {"L": L, "ang": ang, "off": -mx * uy + my * ux, "par": mx * ux + my * uy,
            "lo": min(p0, p1), "hi": max(p0, p1), "seg": ((x0, y0), (x1, y1))}


def _ang_diff(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def group_flights(segs):
    """踏步线按「一跑 = **平行 + 共享一条边 + 步距相等**」分组 ⇒ `[[seg,…], …]`。

    ★ 判据是实测逼出来的（2026-10-14，用户报「楼梯不对」时逐条核过）：

    ① 单靠「方向相同」不够：双跑楼梯的**两跑平行**，踏步线方向、法向步距都一样，
       只有**走向上的位置**不同。实测 3层西南角 A 跑 y=17745、B 跑 y=16155
       （两端各差 1590 mm）⇒ 靠 `lo`/`hi` 共享一端才分得开。
    ② 单靠「等长」不够：平面图按惯例用**折断线**截断上行那一跑，同一跑里长度从
       1590 一路被切到 531（实测 1层西南角），等长判据会把整跑毙掉。
       所以改用「**共享一条边**」：`|Δlo| ≤ 80` **或** `|Δhi| ≤ 80` 即可相邻。
    ③ 源图有**整条重复**的线（实测步距里出现 0.0 的那对）⇒ 先按 (角, off, lo, hi) 去重。
    ④ 并完簇还要按 `off` 梯级**断开**：两跑若被间接并到一起，梯级会出现一个
       远大于步距的空档 ⇒ 用 [GO_MIN, GO_MAX]=[180,400] 切断，得到逐跑的连续梯级。
    ⑤ 太短的线不是踏步而是**填充/箭头碎线**（实测区1 里 110.4 mm 的条纹）
       ⇒ 用 `TREAD_MIN_LEN` 先滤掉。

    返回每个跑一个 `[seg, …]`（≥ `FLIGHT_MIN` 条），线序**未排序**（由调用方按 off 排）。
    """
    cand, seen = [], set()
    for s in segs:
        if len(s) != 2:
            continue
        d = line_key(s)
        if d["L"] < TREAD_MIN_LEN:            # 600 mm：更短的必是填充/碎线
            continue
        k = (round(d["ang"], 1), round(d["off"], 1), round(d["lo"], 1), round(d["hi"], 1))
        if k in seen:
            continue
        seen.add(k)
        cand.append(d)
    n = len(cand)
    if n < FLIGHT_MIN:
        return []
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            A, B = cand[i], cand[j]
            if _ang_diff(A["ang"], B["ang"]) > TREAD_ANG_TOL:
                continue
            if abs(A["lo"] - B["lo"]) > FLIGHT_SIDE_TOL and \
               abs(A["hi"] - B["hi"]) > FLIGHT_SIDE_TOL:
                continue                       # 两端都不共享 ⇒ 不是同一跑
            ra, rb = find(i), find(j)
            if ra != rb:
                parent[ra] = rb

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(cand[i])
    out = []
    for part in groups.values():
        part.sort(key=lambda d: d["off"])
        run = [part[0]]
        for d in part[1:]:
            if GO_MIN <= d["off"] - run[-1]["off"] <= GO_MAX:
                run.append(d)
            else:
                if len(run) >= FLIGHT_MIN:
                    out.append([x["seg"] for x in run])
                run = [d]
        if len(run) >= FLIGHT_MIN:
            out.append([x["seg"] for x in run])
    return out


TREAD_EQ_TOL = 50.0              # 同一跑里「等长」的容差（mm）


def _same_length(flight):
    """一跑踏步线是否**成族等长** —— 真梯跑的唯一形状证据（2026-10-17 C005 实测）。

    ★ 为什么必须加这一条：`group_flights` 只要求「平行 + 共享一端 + 步距 180~400」，
      实测 1层两处 **4 条线、长 600/900/1200/1500、步距 300** 的楔形/折断符号
      完全满足那三条 ⇒ 被判成两跑梯段（1300×1900 的假梯，会把墙挖出洞）。
    ★ 判据：**过半**踏步线与最长者等长（±`TREAD_EQ_TOL`）。
      真跑实测 14/14、15/15 全等；假跑 4 条互不相等（1/4）⇒ 有分辨力。
      留「过半」不用「全等」：折断线会把一跑末尾几条截短（c006 实测 1590→531），
      但那只是少数，成族的主体仍在。
    ★ 只挂在 `treads`（几何）分支：c006 走 `anchor` 锚点路径，一字未动。
    """
    L = sorted((line_key(s)["L"] for s in flight), reverse=True)
    full = L[0]
    return sum(1 for x in L if abs(x - full) <= TREAD_EQ_TOL) * 2 >= len(L)


def _zone_of(flight):
    """一跑踏步线的外包框（外扩 200 mm）—— 与 `stair_zones` 锚点路径的出口**同形状**。"""
    xs = [p[0] for seg in flight for p in seg]
    ys = [p[1] for seg in flight for p in seg]
    return (min(xs) - 200.0, min(ys) - 200.0, max(xs) + 200.0, max(ys) + 200.0)


def _merge_zones(zones, tol=60.0):
    """把**同一座梯间**的几跑并成一个框：相交（或相距 ≤ tol）的外包框合并。

    ★ 为什么必须并（2026-10-17 C005 实测）：锚点路径给的是**一座梯间一个框**，
      几何路径天然是**一跑一个框**。直接交出去 ⇒ `build3d.stair_steps` 每跑都装不下
      双跑（`breadth = 2w + gap` ≈ 3.4 m > 单跑框 1.74~2.88 m）⇒ 三座梯间全退成单跑，
      每跑都从楼面爬到楼面（4.0 m 只 14 级 ⇒ 踢面 267 mm，陡得不像楼梯），
      日志原话「双跑退回单跑」。并成梯间框后 w≈1.74、gap≈0.48，双跑装得下。
    ★ 合并条件用**相交**而不是「任意邻近」：真踏步跑都是并排同跨的；
      实测 1~4 层三座梯间（7 跑）并成 3 框，5 层并成 1 框。
    """
    boxes = [list(z) for z in zones]
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if (a[0] - tol <= b[2] and b[0] - tol <= a[2] and
                        a[1] - tol <= b[3] and b[1] - tol <= a[3]):
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]),
                                max(a[2], b[2]), max(a[3], b[3])]
                    boxes.pop(j)
                    changed = True
                    break
            if changed:
                break
    return [tuple(b) for b in boxes]


def tread_lines(doc, zones):
    """墙层里**真正的踏步线** = `group_flights()` 认下的那些线（拍平）。

    ★★ 2026-10-14 重做 —— 用户报「楼梯不对 / 部分墙体缺失」的**共同根因**。
      旧判据（`redraw.geometry()` 与 `drop_treads()` 用的都是它）是
      「墙层 + 100<L<3000 + 中点在锚区内 ⇒ 算踏步」。楼梯间里除了踏步线还有
      **栏杆线、折断线、上下行箭头、起步处的短碎线**，它们全被算成踏步：
        · 实测 3层 西南角梯间：57 条「踏步」里只有 **28 条**是真的
          （真踏步 = 长 1470 mm、间距 270 mm、两跑各 14 条）；
        · 级数翻倍 ⇒ 逐级抬升时每级被当成两级，实测步距 70.4 mm
          （≈ 真踢面的一半：层高 4.0 m ÷ 26 级 = 153.85 mm，图上步距 270 mm ⇒ 一步两线）；
          ★ 2026-10-16 用户裁定「按甲定案 · 重算整条链」⇒ 层高**回到 4.0 m** ⇒ 上面那个
            4.0 m ÷ 26 级 = **153.85 mm** 就是今天的读数（2026-10-15 那版 3.5 m ÷ 22 级 =
            159.09 mm **已作废**）。本文件**不写死层高**（真源 = `构件库/参数.json` 的
            `共用/层高`，现读 = 4000 mm），这里只留读数。
        · 平面还多出一堆碎板 —— 这正是用户看到的「楼梯不对」；
        · 同一条判据在 `drop_treads()` 里会把**楼梯间里的短墙**
          （实测两条相距 240 mm、长 323 mm 的平行线＝一堵 240 厚墙）
          当踏步剔出墙集 ⇒ 墙上留洞 —— 这正是用户看到的「部分墙体缺失」。

    返回 `[((x0,y0),(x1,y1)), …]`，坐标是 DXF 原值（好让 `drop_treads` 逐条对上）。
    """
    cand = []
    if _stair_mode(doc) == "treads":
        # ★ 2026-10-17 C005：踏步是**墙层的 2 点多段线**，不是 LINE（图里一条 LINE 都没有）。
        #   取线源走 `wall_segments`（同一份展开规则），后面的成跑判据一字不改。
        src = [(s[0], s[1]) for s in wall_segments(None, doc=doc)]
    else:
        src = [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))
               for e in doc.modelspace()
               if e.dxf.layer == WALL_LAYER and e.dxftype() == "LINE"]
    for a, b in src:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if not (100.0 < L < TREAD_MAX):       # TREAD_MAX=3000 mm：更长的必是真墙
            continue
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        if not in_zone(mx, my, zones):
            continue
        cand.append((a, b))
    out = []
    for g in group_flights(cand):
        out.extend(g)
    return out


# ------------------------------------------------------------------ 剔踏步
def drop_treads(segs, treads):
    """把**踏步线**从墙线里剔出去（踏步间隔 ~270 mm，闭合成实心后会连成一整块）。

    ★ 2026-10-14：判据从「短线 + 中点在锚区内」换成**与 `tread_lines()` 逐条对上**。
      旧判据不动长线，但会把楼梯间里的**短墙**一并剔掉（实测 240 厚 / 323 长）
      ⇒ 墙上留洞（用户报「部分墙体缺失」）。只剔**真踏步**才是对的，步数与平面位置
      也都由同一份判据给出（铁律：同一件事不许两处各判一次）。
    ★ 不给 `treads` 就**报错**，不退回旧判据 —— 静默兜底会把这个洞重新吃回去。
    """
    if treads is None:
        raise ValueError("drop_treads 需要 treads（tread_lines() 的结果）；"
                         "旧的「短线+区内」判据会把楼梯间的短墙也剔掉")
    keys = set()
    for a, b in treads:
        keys.add((round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)))
        keys.add((round(b[0], 3), round(b[1], 3), round(a[0], 3), round(a[1], 3)))
    keep, drop = [], 0
    for a, b in segs:
        if (round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)) in keys:
            drop += 1
            continue
        keep.append((a, b))
    return keep, drop


# ------------------------------------------------------------------ analyze 的磁盘缓存
def _src_fp(floor, wall_max, gap):
    """缓存指纹 = 输入 DXF 的字节 + **本文件源码** + 两个入参。

    ★ 把 `__file__` 也 hash 进去，是为了让「改了判据常数（RES/STROKE/PAD/WALL_GAP/
      APPROX/WALL_MAX/TREAD_MAX…）却仍拿旧缓存」这种事**不可能发生** —— 那些常数全是
      本文件的模块级量，源码一动指纹就变。
    """
    h = hashlib.sha1()
    with open(os.path.join(RAW, floor + ".dxf"), "rb") as f:
        h.update(f.read())
    with open(os.path.abspath(__file__), "rb") as f:
        h.update(f.read())
    # ★ 2026-10-17：`STAIR_MODE` 来自楼栋档案（外部数据），不在本文件源码里 ——
    #   不并进指纹就会出现「改了档案的楼梯口径，analyze 仍命中旧缓存、锚区照旧 0」。
    # ★★ 2026-10-17 补 **整份 `drawing` 档案 + redraw.py 源码**：门的画法/点数/形状/弧窗
    #   全住在 redraw.py 的模块级常量里（读档案），而 analyze 缓存里存着**认出来的门**。
    #   只 hash 本文件 ⇒ 改了 `doors_min_pts` 仍命中旧缓存、门数照旧 0（C025 实测就是这样，
    #   症状与「源图没画门」同形）。两者都并进来，改哪儿缓存都必然重算。
    _rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "redraw.py")
    with open(_rd, "rb") as f:
        h.update(f.read())
    # ★ 2026-10-19：门符号判据搬进 door_rule.py —— 不并进指纹就会「改了门判据仍命中旧缓存」。
    _dr = os.path.join(os.path.dirname(os.path.abspath(__file__)), "door_rule.py")
    with open(_dr, "rb") as f:
        h.update(f.read())
    h.update(json.dumps(B.profile().get("drawing", {}), sort_keys=True,
                        ensure_ascii=False).encode("utf-8"))
    h.update(("%r|%r|%s" % (wall_max, gap, STAIR_MODE)).encode("utf-8"))
    return h.hexdigest()


def _acache_get(floor, wall_max, gap):
    """命中才返回；**指纹不符 / 读不出来一律喊出来**，绝不静默拿旧结果当新的。"""
    p = os.path.join(ACACHE, floor + ".npz")
    if not os.path.exists(p):
        return None
    try:
        z = np.load(p, allow_pickle=False)
        if str(z["fp"]) != _src_fp(floor, wall_max, gap):
            print("▷ analyze 缓存**指纹不符**：%s（输入 DXF 或 recognize.py 变过）→ 重算" % floor)
            return None
        out = {"wmask": z["wmask"],
               "geo": tuple(float(v) for v in z["geo"]),
               "recs": json.loads(str(z["recs"])),
               "zones": [tuple(v) for v in json.loads(str(z["zones"]))],
               "segs": [[tuple(q) for q in s] for s in json.loads(str(z["segs"]))],
               "segs_all": [[tuple(q) for q in s]
                            for s in json.loads(str(z["segs_all"]))],
               "A_wall": float(z["A_wall"]), "A_open": float(z["A_open"]),
               "thick": float(z["thick"]), "thick_max": float(z["thick_max"]),
               "gap": float(z["gap"])}
        print("▷ analyze **命中缓存**：%s（不是重新算的；指纹 %s…）"
              % (floor, str(z["fp"])[:8]))
        return out
    except Exception as exc:                       # 缓存坏了不能装作没发生
        print("▷ analyze 缓存**读不出来**（%s：%s）→ 重算" % (floor, exc))
        return None


def _jsonable(o):
    """numpy 标量 → Python 标量，**整数保持整数**。

    ★ 不能用 `default=float` 一把梭：`stair_zones` 的坐标若是 int，写成 json 会变成
      `58630.0`，于是 `02_recognize/<层>.json` 的 `stair_zones` 字段文本与「现算」那条
      路不一致 —— 缓存和现算必须产出一模一样的字节。
    """
    if hasattr(o, "dtype"):
        return (int(o) if str(o.dtype).startswith(("int", "uint")) else float(o))
    raise TypeError("不可序列化：%r" % (o,))


def _acache_put(floor, wall_max, gap, r):
    """落盘：先写 `.tmp` 再 `os.replace` —— 半截文件不会被下一次读成「缓存」。"""
    try:
        os.makedirs(ACACHE, exist_ok=True)
        tmp = os.path.join(ACACHE, floor + ".npz.tmp")
        with open(tmp, "wb") as f:
            np.savez_compressed(
                f, fp=_src_fp(floor, wall_max, gap),
                wmask=r["wmask"], geo=np.asarray(r["geo"], dtype=np.float64),
                A_wall=r["A_wall"], A_open=r["A_open"], thick=r["thick"],
                thick_max=r["thick_max"], gap=r["gap"],
                recs=json.dumps(r["recs"], ensure_ascii=False, default=_jsonable),
                zones=json.dumps([list(z) for z in r["zones"]], default=_jsonable),
                segs=json.dumps(r["segs"], default=_jsonable),
                segs_all=json.dumps(r["segs_all"], default=_jsonable))
        os.replace(tmp, os.path.join(ACACHE, floor + ".npz"))
    except Exception as exc:
        print("▷ analyze 缓存**写不进去**（%s：%s）—— 不影响本次结果" % (floor, exc))


# ------------------------------------------------------------------ 实心墙带（主识别）
def analyze(floor, wall_max=WALL_MAX, gap=WALL_GAP):
    """核心识别（实心版）：返回墙掩膜 wmask / 栅格定位 geo / 逐域 recs / 锚区 / 墙层线段。

    ★ 为什么不用「连通域 + 厚薄」那版当主识别（第一版就是它，实测废掉）：
      双线墙的**两皮之间那条空档**是一个自由域，而它在**建筑转角处是开口的**
      —— 实测 x=17567 竖扫，那条空档从 y=13180 一路到 y=100855 都跟室外同一个域
      （label 1）。于是「室外」把整圈墙带吞掉，凡漏气的地方墙就凭空消失
      （1 层左下整片没墙，就是这么来的）。

    ★ 改成**局部**判据：墙带 = 把墙线描粗 STROKE 后，用 WALL_GAP 的核做形态学闭合。
      两皮间隔 ~240 mm < 260 ⇒ 并成实心；房间是米级，闭不上。这判据**不看连通性**，
      所以转角漏不漏气都不影响它。
      闭合之后**剩下的**细空档（例如 350 间距的填充线之间 ~300 mm 的条纹）
      再按老办法判一次（w < WALL_MAX）补进掩膜 —— 两级，尺度不同，互补。

    ★ 磁盘缓存（2026-10-15 实测驱动）：analyze 单独跑 12 层 = **40.15 s**，而整条链
      recognize / redraw.geometry / build3d 各要一遍 ⇒ 同样的栅格化白烧 3 遍。
      这里落盘复用；命不命中都会打印一行，**不静默**。
    """
    if ACACHE_ON:
        hit = _acache_get(floor, wall_max, gap)
        if hit is not None:
            return hit
    src = os.path.join(RAW, floor + ".dxf")
    # ★ 整个文件只解析一次（实测 0.31 s / 遍）：这三处要的本来就是同一份文件。
    doc = ezdxf.readfile(src)
    segs_all = wall_segments(src, doc=doc)
    zones = stair_zones(src, doc=doc)
    if not segs_all:
        raise RuntimeError("★ 没量到：%s 墙层没有几何" % floor)
    # ★ 2026-10-14：踏步清单与剔踏步用**同一份**读数（tread_lines 现算一次传下去）。
    #   两处各判一次必然漂移；旧版就是两处各写了一版粗判据。
    treads = tread_lines(doc, zones)
    segs, n_tread = drop_treads(segs_all, treads)
    print("墙层线段 %d 条（剔踏步 %d 条 / 认下真踏步 %d 条）；楼梯锚区 %d 个 %s"
          % (len(segs_all), n_tread, len(treads), len(zones),
             [tuple(round(v) for v in z) for z in zones]))
    r = solid_from_segs(segs, wall_max=wall_max, gap=gap)
    r.update({"zones": zones, "segs": segs, "segs_all": segs_all})
    if ACACHE_ON:
        _acache_put(floor, wall_max, gap, r)
    return r


def solid_from_segs(segs, wall_max=WALL_MAX, gap=WALL_GAP,
                    res=RES, stroke=STROKE, pad=PAD, quiet=False):
    """`analyze` 的引擎（合成正对照直接喂它，保证正对照跑的是**同一条码路**）。"""
    img, (ox, oy, res) = rasterize(segs, res, stroke, pad)
    # ★ 核必须**奇数**：偶数尺寸的形态学核不以像素为中心，闭合会把墙带整体挪半格
    #   （合成件实测：偶数核 → 325 厚且偏心，奇数核 → 290 居中）
    k = max(1, int(round(gap / res)))
    if k % 2 == 0:
        k += 1
    # ★ 核必须**方形**（2026-10-19 用户「墙的拼接的地方为啥不是直角，X=87720 Y=23770」）：
    #   椭圆核对**凹角**填不满，转角被磨成 45° 倒角 —— 实测 c086 1 层该点
    #   (87700,23750)→(87775,23825) 一段 75 mm 斜边；全层 ≤150 mm 的 45° 段
    #   椭圆核 1581 个，方核 1090 个，且 ≥70 mm 的（肉眼可见的那种）**全消失**，
    #   剩下的都是 25 mm 一格的像素台阶（8 连通描边固有，不是病）。
    #   副作用实测（c086 1~4 层）：墙面积 −0.9%、中轴墙厚 300 mm 不变、域数不变。
    #   与 `redraw.plate_contours` 同一结论（那边早因「楼面四周一圈弧线」改成方核）。
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    solid = cv2.morphologyEx(img, cv2.MORPH_CLOSE, ker)

    # 第二级：闭合后残留的细空档
    # ★ 只在**每个域自己的外框**里量（2026-10-15）。等价性不是估计出来的：
    #   ① 面积 = `…WithStats` 数过的像素个数，与 `mask.sum()` 同一个量；
    #   ② 周长：域的所有像素都在自己外框内，而「恰好一边是本域」的相邻格对**必然**
    #      整个落在「外框各向外扩 1 格」的范围内（外扩在图边处裁掉 —— 原式本来也
    #      只在图内比相邻格，裁掉的那圈本就不计）⇒ 两式数到的是**同一批格对**；
    #   ③ 触边 ⇔ 外框贴到图边（域有像素在框里，框贴边就一定有像素贴边）；
    #   ④ 质心仍走 `nonzero`，但只在框里取、**加回框的偏移**再平均 —— 同一批整数、
    #      同一行主序 ⇒ 与整图取平均逐位相同。
    H, W = solid.shape
    n, lab, st, _ = components_stats(solid)
    recs = []
    extra = np.zeros_like(solid)
    for i in range(1, n):
        bx = int(st[i, cv2.CC_STAT_LEFT])
        by = int(st[i, cv2.CC_STAT_TOP])
        bw = int(st[i, cv2.CC_STAT_WIDTH])
        bh = int(st[i, cv2.CC_STAT_HEIGHT])
        sub = lab[by:by + bh, bx:bx + bw] == i
        y0e, y1e = max(0, by - 1), min(H, by + bh + 1)
        x0e, x1e = max(0, bx - 1), min(W, bx + bw + 1)
        r = comp_metrics(lab[y0e:y1e, x0e:x1e] == i, res,
                         A_px=int(st[i, cv2.CC_STAT_AREA]))
        if r is None:
            continue
        A, P, w = r
        ys, xs = np.nonzero(sub)
        cx = ox + float((xs + bx).mean()) * res
        cy = oy + float((ys + by).mean()) * res
        touch = by == 0 or bx == 0 or by + bh == H or bx + bw == W
        kind = "outside" if touch else ("thin" if w < wall_max else "open")
        if kind == "thin" or A / 1e6 < MIN_AREA:
            extra[by:by + bh, bx:bx + bw][sub] = 255    # 条纹空档 / 噪声毛刺：补进墙
        recs.append({"id": i, "A": A, "P": P, "w": w, "cx": cx, "cy": cy,
                     "kind": kind})
    wmask = cv2.bitwise_or(solid, extra)

    # 厚度量具：距离变换 → **中轴上的中位**直径（墙厚）。
    # ★ 不用最大值：墙与墙的丁字/转角处wmask 材料厚一倍（实测合成件上 max 给 460、
    #   而直墙只有 290）⇒ max 是「节点厚度」不是「墙厚」。中轴 + 中位把它压掉。
    thick, thick_max = ridge_thickness(wmask, res)
    A_wall = float((wmask > 0).sum()) * res * res / 1e6
    opens = [r for r in recs if r["kind"] == "open"]
    if not quiet:
        print("栅格 %dx%d；闭合核 %d px（%.0f mm）" % (img.shape[1], img.shape[0], k, gap))
        print("自由域 %d 个（室外 %d / 房间 %d / 条纹 %d）"
              % (n - 1, sum(r["kind"] == "outside" for r in recs),
                 len(opens), sum(r["kind"] == "thin" for r in recs)))
        hist = collections.Counter()
        for rr in opens:
            hist[min(int(rr["w"] // 500) * 500, 20000)] += 1
        print("房间等截面宽度 w=2A/P 直方图（500 mm 一档，末档>=20000）——"
              "若出现 <600 的峰说明「房间」和「墙」还没分开：")
        for key in sorted(hist):
            print("  %6s..%6s : %s" % (key, key + 500, "#" * min(hist[key], 70)))
        print("判墙面积 %.3f m²；中轴墙厚（中位）%.0f mm（最厚节点 %.0f mm）"
              % (A_wall, thick, thick_max))
    if A_wall <= 0.0:
        raise RuntimeError("★ 没量到：一条墙都没判出来 —— 不许当结论")
    return {"wmask": wmask, "geo": (ox, oy, res), "recs": recs,
            "A_wall": A_wall, "A_open": sum(r["A"] for r in opens) / 1e6,
            "thick": thick, "thick_max": thick_max, "gap": gap}


def ridge_thickness(wmask, res):
    """墙厚量具：距离变换的**中轴**上取中位（mm）。返回 (中位厚度, 最厚节点)。

    ★ 为什么不用 `2*dist.max()`：丁字口/转角处的材料是两条墙叠起来的，
      最大值量到的是**节点**（合成件实测 460），不是墙厚（290）。
    """
    if not wmask.any():
        return 0.0, 0.0
    d = cv2.distanceTransform(wmask, cv2.DIST_L2, 5)
    mx = cv2.dilate(d, np.ones((3, 3), np.uint8))
    ridge = (wmask > 0) & (d >= mx - 1e-6) & (d > 0)
    if not ridge.any():
        return 0.0, float(d.max()) * 2.0 * res
    return (float(np.median(d[ridge])) * 2.0 * res,
            float(d.max()) * 2.0 * res)



# ------------------------------------------------------------------ 旧版（连通域+厚薄）留档
def analyze_bands(floor, wall_max=WALL_MAX):
    """第一版识别（**已废**，留作对照）：连通域 + 等截面宽度判厚薄。

    实测废因：双线墙中间的细空档漏气 ⇒ 被「室外」吞掉（见 `analyze` 的说明）。
    """
    src = os.path.join(RAW, floor + ".dxf")
    segs = wall_segments(src)
    zones = stair_zones(src)
    print("墙层线段 %d 条；楼梯锚区 %d 个 %s"
          % (len(segs), len(zones), [tuple(round(v) for v in z) for z in zones]))
    if not segs:
        raise RuntimeError("★ 没量到：%s 墙层没有几何" % floor)
    img, (ox, oy, res) = rasterize(segs)
    n, lab = components(img)
    print("栅格 %dx%d，背景连通域 %d 个" % (img.shape[1], img.shape[0], n))

    recs = []
    n_stair = 0
    for i in range(1, n):
        m = (lab == i).astype(np.uint8)
        r = comp_metrics(m, res)
        if r is None:
            continue
        A, P, w = r
        if A / 1e6 < MIN_AREA:
            continue
        ys, xs = np.nonzero(m)
        cx = ox + float(xs.mean()) * res
        cy = oy + float(ys.mean()) * res
        touch = (lab[0, :] == i).any() or (lab[-1, :] == i).any() \
            or (lab[:, 0] == i).any() or (lab[:, -1] == i).any()
        kind = "outside" if touch else ("wall" if w < wall_max else "open")
        if kind == "wall" and in_zone(cx, cy, zones):
            kind = "stair"                      # 踏步，另算，不进墙
            n_stair += 1
        recs.append({"id": i, "A": A, "P": P, "w": w, "cx": cx, "cy": cy,
                     "kind": kind})
    print("其中判为楼梯踏步的 %d 条（已从墙里剔出）" % n_stair)
    hist = collections.Counter()
    for r in recs:
        if r["kind"] == "outside":
            continue
        hist[min(int(r["w"] // 100) * 100, 5000)] += 1
    print("等截面宽度 w=2A/P 直方图（100 mm 一档，末档>=5000；不含室外）:")
    for k in sorted(hist):
        print("  %5s..%5s : %s" % (k, k + 100, "#" * min(hist[k], 70)))

    walls = [r for r in recs if r["kind"] == "wall"]
    opens = [r for r in recs if r["kind"] == "open"]
    A_wall = sum(r["A"] for r in walls) / 1e6
    A_open = sum(r["A"] for r in opens) / 1e6
    print("判墙 %d 段（%.3f m²）/ 判空 %d 个（%.3f m²）/ 室外 %d"
          % (len(walls), A_wall, len(opens), A_open,
             len([r for r in recs if r["kind"] == "outside"])))
    if not walls:
        raise RuntimeError("★ 没量到：%s 一条墙都没判出来 —— 不许当结论" % floor)

    # 墙掩膜 → 闭合多段线（RETR_CCOMP：外环 + 洞）
    wmask = np.zeros_like(lab, np.uint8)
    for r in walls:
        wmask[lab == r["id"]] = 255
    return {"wmask": wmask, "geo": (ox, oy, res), "recs": recs,
            "zones": zones, "segs": segs, "walls": walls,
            "A_wall": A_wall, "A_open": A_open}


def recognize(floor, wall_max=WALL_MAX):
    r = analyze(floor, wall_max)
    wmask, geo, recs, segs_all = r["wmask"], r["geo"], r["recs"], r["segs_all"]
    A_wall, A_open = r["A_wall"], r["A_open"]
    os.makedirs(OUT_RED, exist_ok=True)
    dxf, n_poly = _write_dxf(floor, wmask, geo)
    png = _render_review(floor, segs_all, wmask, geo)

    os.makedirs(OUT_REC, exist_ok=True)
    meta = {"name": floor, "res": geo[2], "stroke": STROKE, "wall_max": wall_max,
            "gap": r["gap"], "segments": len(r["segs"]), "treads_dropped":
            len(segs_all) - len(r["segs"]), "wall_polys": n_poly,
            "thick_mm": round(r["thick"], 1), "thick_max_mm": round(r["thick_max"], 1),
            "area_wall_m2": round(A_wall, 3), "area_open_m2": round(A_open, 3),
            "regions": [{k: (round(v, 2) if isinstance(v, float) else v)
                         for k, v in rr.items()} for rr in recs],
            "stair_zones": [[round(v, 1) for v in z] for z in r["zones"]]}
    with open(os.path.join(OUT_REC, floor + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("写 %s" % os.path.join(OUT_REC, floor + ".json"))
    print("写 %s" % dxf)
    print("写 %s" % png)
    return 0


def _render_review(floor, segs, wmask, geo):
    """审图 PNG：底图浅灰线 + 判出的墙实色覆盖。给你框问题用。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    from matplotlib.collections import LineCollection
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    ox, oy, res = geo
    fig, ax = plt.subplots(figsize=(20, 14), dpi=110)
    ax.add_collection(LineCollection(segs, colors="#c9ccd1", linewidths=0.6))
    cnts, hier = cv2.findContours(wmask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    def sub(c):
        p = c[:, 0, :].astype(float) * res + [ox, oy]
        return list(map(tuple, p))

    n_outer = 0
    for j in range(len(cnts)):
        if hier[0][j][3] != -1:                    # 只从外环起
            continue
        # ★ 一个外环 + 它的所有洞，拼成**一条复合路径**再填。
        #   只填外环、丢掉洞 ⇒ 整层被涂红（这个坑已经踩过一次）。
        verts, codes = [], []
        for c in [cnts[j]] + [cnts[k] for k in _children(hier, j)]:
            q = sub(c)
            if len(q) < 3:
                continue
            verts += q + [q[0]]
            codes += [Path.MOVETO] + [Path.LINETO] * (len(q) - 1) + [Path.CLOSEPOLY]
        if verts:
            ax.add_patch(PathPatch(Path(verts, codes), facecolor="#d92b2b",
                                   alpha=0.5, edgecolor="#8c1010", linewidth=0.7))
            n_outer += 1
    ax.set_aspect("equal")
    ax.autoscale()
    ax.set_title("recognize %s  wall-polys=%d  (RED = judged wall, GREY = CAD linework)"
                 % (floor, n_outer), fontsize=13)
    ax.grid(True, lw=0.2, alpha=0.4)
    out = os.path.join(OUT_RED, floor + ".png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def _children(hier, j):
    """RETR_CCOMP 下第 j 个外环的洞（hierarchy = [Next, Prev, FirstChild, Parent]）。"""
    out = []
    k = hier[0][j][2]
    while k != -1:
        out.append(k)
        k = hier[0][k][0]
    return out


def _write_dxf(floor, wmask, geo):
    ox, oy, res = geo
    cnts, hier = cv2.findContours(wmask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    doc = ezdxf.new("R2013", setup=True)
    doc.layers.add("REDRAW-WALL", color=1)
    doc.layers.add("REDRAW-HOLE", color=3)
    ms = doc.modelspace()
    eps = APPROX
    nseg = 0
    for j, c in enumerate(cnts):
        ap = cv2.approxPolyDP(c, eps, True)
        if len(ap) < 3:
            continue
        hole = hier[0][j][3] != -1
        pts = [(ox + float(p[0][0]) * res, oy + float(p[0][1]) * res) for p in ap]
        ms.add_lwpolyline(pts, close=True,
                          dxfattribs={"layer": "REDRAW-HOLE" if hole else "REDRAW-WALL"})
        if not hole:
            nseg += 1
    path = os.path.join(OUT_RED, floor + ".dxf")
    doc.saveas(path)
    return path, nseg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor")
    ap.add_argument("--all", action="store_true",
                    help="全部楼层，**一个进程跑完**：每层省掉约 1.5 s 固定税"
                         "（实测 0.33 s 导入 + 1.30 s matplotlib 首次出字）")
    ap.add_argument("--positive", action="store_true")
    ap.add_argument("--no-acache", action="store_true",
                    help="不读也不写 analyze 的磁盘缓存（要一份「全部现算」的读数时用）")
    ap.add_argument("--wall-max", type=float, default=WALL_MAX)
    a = ap.parse_args()
    global ACACHE_ON
    if a.no_acache:
        ACACHE_ON = False
    if a.positive:
        rc1 = positive_case()
        print()
        rc2 = positive_bands()
        return max(rc1, rc2)
    if a.all:
        rc = 0
        for f in raw_floors():
            print("── %s" % f)
            rc = max(rc, recognize(f, a.wall_max))
        return rc
    if not a.floor:
        print("给 --floor / --all 或 --positive")
        return 2
    return recognize(a.floor, a.wall_max)


if __name__ == "__main__":
    sys.exit(main())
