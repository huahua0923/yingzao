# -*- coding: utf-8 -*-
"""门头墙（LINTEL）**板厚**量表 —— 用户报「有的门上的墙补得太厚了」的那把尺子。

## 为什么单独一把尺子

板厚 = `tk + 2·bite`（`tk` = 量出来的墙厚，`bite` = `门头墙_缝合` 30）。
正常板厚就是「这段墙的真厚 + 60」，所以**板厚超过本楼实际存在的墙厚**就是错，
而且错得看得见（用户就是看出来的）。J-10.9-01 量的是「板上/板下有没有门」，
**对厚度全盲** —— 板立成 1 m 厚的菱形它也照样 PASS（这就是它没拦住的原因）。

## 量法：内切半径，不是外接矩形短边

★ 2026-10-16 踩过：`minimum_rotated_rectangle().exterior` 的短边对**折弯/粘连**的环
会**高估**厚度（环一旦不是直矩形，外接矩形的短边就把拐弯也算进去）。
改用**内切半径**：二分找最大的 r 使 `ring.buffer(-r)` 为空 ⇒ 厚度 ≈ 2r（局部厚度）。
环带**重复的收尾点**（4 角矩形是 5 个点），先去掉再去 buffer（不去会让 buffer 退化）。

## ★★ 残件追查：试过并**否掉**的四把尺子（2026-10-16，铁律 028 —— 代价写在旁边）

用户报的「补得太厚」主干已修好，残下的是**每层同一批门**（1 层 0 处，2~6 层各 4~5 处：
tk=1022/900/875/855/725，触墙点逐层**同一个坐标**，跨层读数**逐位相同** ⇒ 是系统性的，
不是栅格噪声）。要让程序自己判出来，试过四条路，**全部实测否掉**：

| 尺子 | 读法 | 实测为什么不能用 |
|---|---|---|
| `--onwall` 板压墙比例 | 板面积里有多少落在栅格墙上 | 739 块中位 **4.8%**、无断层，而且最低那批里混着 tk=300 的**正常板** —— 正常板压在**洞口**上、底下本来就没墙 |
| `--srcwall` 板心到源图墙线 ÷ tk | 真板心该落在墙里（≈tk/2） | 739 块中位 **2.46**、无断层；最远的（7.51）反而是 tk=106 的正常板 |
| `--wallthick` 墙块厚分布 vs 板 tk | 板 tk 落在墙厚分布外就是病 | `wall_polys` 全楼只有 **204 块**、是**合并网络**：块内切半径量到的是**丁字接头团块**（p95=8000）⇒ 0/739 落在区间外，**零分辨力** |
| 板心离墙 / 板 MBR | 胖板的形状特征 | 那几块板的 MBR 是**方的**（1893×1893）⇒ 没有「短边 = 厚度向」可比，方向无意义 |

⇒ 共同的原因：**板的质心永远落在洞口上**（板就是补洞口的），所以任何在**板心**采样的尺子
  对墙都是瞎的（铁律 158）。要判必须**在门的触墙点 Q 上**量 —— 那个坐标只有建板那一步有。

★ 已经量实的**局部**结论（同一处、两把独立尺子，用户 2026-10-14 裁定「多把尺子只要目标一致
  就是资产」）：

| 触墙点（4 层） | 建板用的 tk | 同一法向上 W 的厚度 | 栅格最近墙段 | 板 MBR |
|---|---|---|---|---|
| (90905, 81461) | **900** | 406 | 125 | 1893×1893 |
| (50350, 61100) | **875** | 290 | 325 | 1893×1893 |
| (113310, 61100) | **855** | 290 | 325 | 1893×1893 |
| (121450, 35945) | **725** | 600 | 325 | 1893×1893 |

  ⇒ 两把尺子都说那儿的墙 ≈ 300 厚，建板那一步却用了 700~1022 ⇒ **板厚是墙厚的 ~3 倍**。
  5 处里 **3 处走「迈步法」**（那条带「墙占比 0.35」兜底的支路）、2 处走「缺口法」。
  下一步（**未做**，动的是建板那一段）：在 Q 上做**局部**交叉校验，而**不是**按整层分布裁阈值。

## 用法

    python rebuild/tools/lintel_thickness.py            # 全楼汇总 + 最厚的几块
    python rebuild/tools/lintel_thickness.py --floor 1层
    python rebuild/tools/lintel_thickness.py --json      # 只吐一行机器可读的汇总
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import numpy as np
import shapely.geometry as sg

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTOURS = os.path.join(ROOT, "06_su", "contours")
sys.path.insert(0, HERE)
import parts_lib as PL                                                  # noqa: E402

# ★ 两个数都**从代码里取**，不在这里手打（铁律 103/174：同一个量不许有两处副本）
BITE = PL._mm("门", "门头墙_缝合")
TK_MAX = PL._mm("门", "门头墙_墙厚上限")


def ring_pts(ring):
    """环去重（收尾点常与首点重合）→ 点列。"""
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def thickness(ring):
    """局部厚度 ≈ 2 × 内切半径（二分）。返回 mm；环退化返回 0。"""
    pts = ring_pts(ring)
    if len(pts) < 3:
        return 0.0
    g = sg.Polygon(pts)
    if not g.is_valid:
        g = g.buffer(0)
    if g.is_empty or g.geom_type != "Polygon":
        return 0.0
    lo, hi = 0.0, 4000.0
    for _ in range(24):                     # 4000/2^24 ≪ 0.01 mm，够
        mid = 0.5 * (lo + hi)
        if g.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return hi * 2.0


def floors():
    out = []
    for fn in sorted(os.listdir(CONTOURS)):
        if fn.endswith(".json") and not fn.startswith("index"):
            out.append(fn[:-5])
    return out


def read(floor):
    """→ [(tk_mm, 板厚_mm, 质心 x, 质心 y, id), …]（tk = 板厚 − 2·bite）。"""
    p = os.path.join(CONTOURS, "%s.json" % floor)
    with io.open(p, encoding="utf-8") as f:
        d = json.load(f)
    rows = []
    for r in d["polys"]:
        if r.get("layer") != "LINTEL":
            continue
        th = thickness(r["ring"])
        pts = ring_pts(r["ring"])
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        rows.append((th - 2.0 * BITE, th, cx, cy, r.get("id", "?")))
    return rows


def probe(floor, x, y, span=2500.0, cell=200.0):
    """★ 局部 ASCII 图：以 mm 坐标 (x, y) 为中心，把**识别出来的墙带**
    （栅格 mask —— 也就是 `_xsec` 真正切过去的那一份）与该处的板画在一张图里。

    用途：一块板量出 1022 mm 时，先看这里是「**一道厚墙**」还是
    「**两道墙被栅格连成了一片**」—— 前者板本来就该这么厚，后者才是错。
    图上：`#` 墙 ｜ `.` 空 ｜ `P` 板 ｜ `D` 板边界 ｜ `@` 探针中心 ｜ 上=+y。
    ★ 这是**诊断图**，不是判据（判据在 `gates/J-10.9-08`）。
    """
    import recognize as R
    a = R.analyze(floor)
    m = np.asarray(a["wmask"]) > 0
    ox, oy, res = a["geo"]
    with io.open(os.path.join(CONTOURS, "%s.json" % floor), encoding="utf-8") as f:
        d = json.load(f)
    pls = [sg.Polygon(ring_pts(r["ring"])) for r in d["polys"]
           if r.get("layer") == "LINTEL"]
    # ★ 真门（原始图纸的 `$DorLib2D$`）：与 `gates/J-10.9-08` 同一份取块实现。
    #   用来一眼分开两件事：「板压在门上但太厚」与「板底下**根本没有门**」。
    import redraw as RD
    src = os.path.join(os.path.dirname(CONTOURS), "..", "01_cad", "raw", floor + ".dxf")
    doors = []
    if os.path.exists(src):
        for g in RD.blocks_grouped_wcs(src, prefix=RD.DOOR_PREFIX):
            xs = [q[0] for _p, _c in g["polys"] for q in _p]
            ys = [q[1] for _p, _c in g["polys"] for q in _p]
            if xs:
                doors.append(sg.box(min(xs), min(ys), max(xs), max(ys)))
    n = int(round(span / cell))
    # ★ **原始图纸的墙线**：识别结果里没有、源图里有的地方印 `=` ——
    #   用来把「这处本来就没墙」与「这处的墙没被识别出来」分开（两种错法，改法完全不同）。
    raws = set()
    if os.path.exists(src):
        import ezdxf
        for e in ezdxf.readfile(src).modelspace():
            if e.dxf.layer != R.WALL_LAYER:
                continue
            t = e.dxftype()
            if t == "LINE":
                ps = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            elif t == "LWPOLYLINE":
                ps = [(p[0], p[1]) for p in e.vertices()]
            else:
                continue
            for px, py in ps:
                if abs(px - x) <= span + 1 and abs(py - y) <= span + 1:
                    raws.add((int(round((px - x) / cell)), int(round((py - y) / cell))))
    print("%s 局部 %s ｜ 中心 (%.0f, %.0f) ｜ 窗 ±%.0f mm ｜ 格 %.0f mm ｜ 栅格 %.1f mm"
          % (floor, os.path.basename(__file__), x, y, span, cell, res))
    print("     # 墙 ｜ . 空 ｜ W 墙＋板 ｜ P 板里(板下无墙) ｜ D 板边压墙 ｜ E 板边无墙 ｜ = 源图有墙线而识别结果没有")
    print("     ★ 真门内换一套：O 板里 / o 板边 / + 墙 / , 空 / ; 源图有线")
    print("     " + "".join(str(int(abs((x + i * cell) // 1000)) % 10) for i in range(-n, n + 1)))
    for j in range(n, -n - 1, -1):                    # 从 +y 往下印
        yy = y + j * cell
        row = []
        for i in range(-n, n + 1):
            xx = x + i * cell
            if i == 0 and j == 0:
                row.append("@")
                continue
            px, py = int(round((xx - ox) / res)), int(round((yy - oy) / res))
            w = (0 <= py < m.shape[0] and 0 <= px < m.shape[1] and bool(m[py, px]))
            pt = sg.Point(xx, yy)
            onp = any(g.exterior.distance(pt) < cell * 0.6 for g in pls)
            inp = any(g.covers(pt) for g in pls)
            raw = (i, j) in raws
            if any(bd.covers(pt) for bd in doors):     # 真门内换一套符号
                ch = "O" if inp else ("o" if onp else ("+" if w else
                     (";" if raw else ",")))
            elif w and inp:
                ch = "W"          # ★ 墙＋板（板底下真有墙）—— 旧符号 `P` 把这个盖住了
            elif inp:
                ch = "P"          # 板里、板下**不是**墙（板浮着的签名）
            elif w and onp:
                ch = "D"          # 板边压在墙上
            elif onp:
                ch = "E"          # ★ 板边、板下不是墙
            elif raw:
                ch = "="
            elif w:
                ch = "#"
            else:
                ch = "."
            row.append(ch)
        print("%5.0f" % yy + "".join(row))
    print("     每一格 = %.0f×%.0f mm ｜ 厚度定义见本文件 `thickness()` ｜ 真门 %d 樘在本窗内"
          % (cell, cell, sum(1 for bd in doors if bd.intersects(
              sg.box(x - span, y - span, x + span, y + span)))))
    # ★ ③ 窗内 INSERT 的**块内部线**（虚体）统计 —— 专治一个分不开的岔路：
    #   「这处没墙」是**源图本来就没有**，还是**墙只画在 `$DorLib2D$` 门块内部**
    #   （识别只栅格化模型空间的墙层实体 ⇒ 块内部的墙线与不存在同形）。
    #   判读：块内**长线**（≥500 mm，门扇本身 ~900~1000）成对出现并夹着一条带 ⇒ 墙在块里；
    #   块内只有一两根门扇线 ⇒ 源图确实没墙，板是凭空造的。两种改法完全不同。
    if os.path.exists(src):
        import ezdxf
        segs = []
        for e in ezdxf.readfile(src).modelspace():
            if e.dxftype() != "INSERT":
                continue
            p = e.dxf.insert
            if abs(p.x - x) > span + 2000 or abs(p.y - y) > span + 2000:
                continue
            try:
                vs = list(e.virtual_entities())
            except Exception:
                continue
            for v in vs:
                t = v.dxftype()
                try:
                    if t == "LINE":
                        a, b = v.dxf.start, v.dxf.end
                        segs.append(((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5)
                    elif t == "LWPOLYLINE":
                        ps = [(q[0], q[1]) for q in v.vertices()]
                        segs += [((ps[i + 1][0] - ps[i][0]) ** 2
                                  + (ps[i + 1][1] - ps[i][1]) ** 2) ** 0.5
                                 for i in range(len(ps) - 1)]
                except Exception:
                    continue
        long_segs = [L for L in segs if L >= 500.0]
        print("     ③ 窗内门块内部线：共 %d 根 ｜ ≥500 mm 的 %d 根 ｜ 最长 %.0f mm"
              % (len(segs), len(long_segs), max(segs) if segs else 0))
    # ★ ④ 这一点在**源图**里离墙有多远 —— 把两件完全不同的错法分开：
    #   「板底下源图本来就没墙」（板是凭空造的 ⇒ 该删板）与
    #   「板底下源图有墙、是识别/栅格丢了」（⇒ 该修上游，不能删板）。
    #   ★ 量的是**线段到点的距离**，不是顶点（顶点法对**穿过窗口的长边**全盲 —— 铁律 158：
    #     上一版就是只认顶点，所以「源图那里没墙」这句话本身站不住）。
    if os.path.exists(src):
        import ezdxf
        segs2, closed2 = [], []
        lim = span + 2000.0
        for e in ezdxf.readfile(src).modelspace():
            if e.dxf.layer != R.WALL_LAYER:
                continue
            t = e.dxftype()
            try:
                if t == "LINE":
                    a, b = e.dxf.start, e.dxf.end
                    if (abs(a.x - x) <= lim and abs(a.y - y) <= lim) or \
                       (abs(b.x - x) <= lim and abs(b.y - y) <= lim):
                        segs2.append(((a.x, a.y), (b.x, b.y)))
                elif t == "LWPOLYLINE":
                    ps = [(q[0], q[1]) for q in e.vertices()]
                    if any(abs(q[0] - x) <= lim and abs(q[1] - y) <= lim for q in ps):
                        segs2 += [(ps[i], ps[i + 1]) for i in range(len(ps) - 1)]
                        if e.closed:
                            closed2.append(ps)
            except Exception:
                continue
        _p0 = sg.Point(x, y)
        _d = min((sg.LineString(s).distance(_p0) for s in segs2), default=float("inf"))
        _in = sum(1 for ps in closed2 if sg.Polygon(ps).buffer(0).covers(_p0))
        print("     ④ 源图墙层：线段 %d 段 ｜ 该点到最近线段 %s mm ｜ 落在闭合墙多边形内 %d 个"
              % (len(segs2), ("%.0f" % _d) if _d != float("inf") else "∞", _in))
    # ★ ⑤ `wall_polys` 的并集 —— 建板那一步**真正用的那份墙**（铁律 192：判据的参照物
    #   必须与交付件同作用域）。图上的 `#` 是 `recognize.analyze` 的**栅格**，与这份
    #   多边形并集**不一定一致**：Q、tk、走带全是在**这一份**上量的。
    #   ⇒ 「栅格那儿没墙」与「建板那儿没墙」是两句话，别混（铁律 196）。
    import build3d as B3
    from shapely.ops import unary_union as _uu
    _win = sg.box(x - span, y - span, x + span, y + span)
    _wp = B3.wall_polys(RD.geometry(floor))
    _Wu = _uu(_wp)
    _p1 = sg.Point(x, y)
    print("     ⑤ wall_polys（建板用的那份墙）：该点在 W 内 %s ｜ 到 W 距离 %.0f mm ｜ 窗内块 %d"
          % (_Wu.covers(_p1), _Wu.distance(_p1),
             sum(1 for g in _wp if g.intersects(_win))))
    # ★ ⑥ 建板那一步报的墙厚，**在同一份 W 上独立重算一遍**（铁律 183：换个函数同一把尺子），
    #   法向取**离 Q 最近那块板**的厚度向（板本身就是这么造的）。用来分开两件完全不同的事：
    #     ① W 在这儿**真的**有 900 厚 ⇒ 病在更上游的**墙带提取**（板只是照实补）；
    #     ② W 没那么厚 ⇒ 病在**走带/量厚那一步**（同 W、另一个入口）。
    if pls:
        gq = max(pls, key=lambda g: thickness(list(g.exterior.coords)))   # 窗内**最厚**那块 = 可疑板
        _cs = list(gq.minimum_rotated_rectangle.exterior.coords)
        if _cs and _cs[0] == _cs[-1]:
            _cs = _cs[:-1]                          # 环的收尾点常与首点重合，去了再按 4 条边取
        _ed = sorted(((  ((_cs[(i + 1) % 4][0] - _cs[i][0]) ** 2
                          + (_cs[(i + 1) % 4][1] - _cs[i][1]) ** 2) ** 0.5,
                        _cs[i], _cs[(i + 1) % 4]) for i in range(4)), key=lambda z: z[0])
        _l1, _a1, _b1 = _ed[0]                      # 短边 = 厚度向
        _ux, _uy = (_b1[0] - _a1[0]) / _l1, (_b1[1] - _a1[1]) / _l1
        _ln = sg.LineString([(x - 6000 * _ux, y - 6000 * _uy), (x + 6000 * _ux, y + 6000 * _uy)])
        _iw = _Wu.intersection(_ln)
        # ★ ⑦ 同一条法向、过 Q 的**栅格**连通墙段长 —— 与 ⑥ 是**两把独立的尺子量同一件事**
        #   （用户 2026-10-14 裁定：多把尺子只要目标一致就是资产）。两把差几倍 ⇒ 可疑。
        #   沿 t 逐步判「这一点在不在墙格里」，取**离 t=0 最近的那一段**（Q 不在墙上也算，
        #   那样读出的就是「最近的一堵墙有多厚」）。
        step = max(res, 5.0)
        marks = []
        t = -6000.0
        while t <= 6000.0:
            px, py = int(round((x + t * _ux - ox) / res)), int(round((y + t * _uy - oy) / res))
            marks.append((t, 0 <= py < m.shape[0] and 0 <= px < m.shape[1] and bool(m[py, px])))
            t += step
        best, run0, prev_w = None, None, False
        for t, w in marks + [(None, False)]:
            if w and not prev_w:
                run0 = t
            if prev_w and not w:
                seg = (run0, t)
                d = 0.0 if run0 <= 0.0 <= t else min(abs(run0), abs(t))
                if best is None or d < best[0]:
                    best = (d, seg[1] - seg[0])
            prev_w = w
        print("     ⑥ W（建板那份）沿板厚度向：%.0f mm ｜ ⑦ 栅格同法向最近墙段：%s mm ｜ 板 %.0f×%.0f"
              % (_iw.length, ("%.0f" % best[1]) if best else "无", _ed[1][0], _ed[0][0]))
    return 0


def onwall(sample=50.0, top=15):
    """★ 每一块板「压在墙上的比例」—— 判据的刀口从这份分布里取，不手打阈值（铁律 103）。

    用途：把「板建在没墙的地方」与「板在墙上、只是量胖了」分开。前者该删板，后者该改薄。
    量法：板的外接框按 `sample` mm 打点，落在板内且在**栅格墙**上的比例。

    ★ 量具盲区（铁律 158）：这里用的是 `analyze` 的**栅格**墙，而建板那一步用的是
      `build3d.wall_polys` 的**多边形**墙 —— 两把尺子在同一处可能不一致（铁律 192），
      所以本行只是**诊断**；真要落成判据必须回到 `parts_lib` 里用同一个 `W`。
    """
    import recognize as R
    rows = []
    for f in floors():
        p = os.path.join(CONTOURS, "%s.json" % f)
        if not os.path.exists(p):
            continue
        a = R.analyze(f)
        m = np.asarray(a["wmask"]) > 0
        ox, oy, res = a["geo"]
        with io.open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        for r in d["polys"]:
            if r.get("layer") != "LINTEL":
                continue
            g = sg.Polygon(ring_pts(r["ring"]))
            if g.is_empty or not g.is_valid:
                continue
            minx, miny, maxx, maxy = g.bounds
            n_in = n_w = 0
            yy = miny
            while yy <= maxy:
                xx = minx
                while xx <= maxx:
                    if g.covers(sg.Point(xx, yy)):
                        n_in += 1
                        px, py = int(round((xx - ox) / res)), int(round((yy - oy) / res))
                        if 0 <= py < m.shape[0] and 0 <= px < m.shape[1] and m[py, px]:
                            n_w += 1
                    xx += sample
                yy += sample
            if n_in:
                rows.append((n_w / float(n_in), thickness(r["ring"]) - 2.0 * BITE,
                             f, r.get("id", "?"), g.area / 1e6))
    rows.sort()
    print("板 %d 块 ｜ 「板下是墙」的比例分位：" % len(rows))
    for q in (0, 5, 10, 25, 50, 75, 90, 100):
        i = min(len(rows) - 1, int(round(q / 100.0 * (len(rows) - 1))))
        print("   %3d%%  %5.1f%%" % (q, rows[i][0] * 100.0))
    # ★ 直方图（10 格）——分位会把**双峰**抹平，直方图能直接看出中间有没有断层
    hist = [0] * 10
    for r, *_ in rows:
        hist[min(9, int(r * 10.0))] += 1
    print("── 直方图（每格 10%）：")
    for k in range(10):
        print("   %3d~%3d%%  %4d  %s" % (k * 10, k * 10 + 10, hist[k],
                                          "#" * max(1, int(60.0 * hist[k] / max(1, len(rows)))) if hist[k] else ""))
    print("── 压墙比例最低的 %d 块（tk = 板厚 − 2×缝合）：" % top)
    for r, tk, f, rid, ar in rows[:top]:
        print("   %-8s %-18s 压墙 %5.1f%% ｜ tk=%7.1f ｜ 板面积 %6.2f m²"
              % (f, rid, r * 100.0, tk, ar))
    return 0


def srcwall(top=20):
    """★ 板心到**源图墙线**的距离 ÷ 板厚 —— 换一把尺子试试能不能把「凭空造的板」分开。

    上一把（「板压墙比例」）实测**分不开**：739 块里 650 块 < 10%，中位 4.8%，而且
    最低那批里混着 tk=300 的**正常板** —— 正常板压在**洞口**上、底下本来就没墙，
    所以「压墙比例」对好板也是低的 ⇒ 直方图**无断层**，没有可裁的刀口（铁律 103），
    已记废案，不许再拿它当判据。

    这一把的道理：真板是**墙带**造出来的，板心该落在墙里 ⇒ d ≈ tk/2（d/tk ≈ 0.5）；
    板造在**没有墙的过道里**，板心离最近的源图墙线就会远出好几个 tk。
    ★ 盲区（铁律 158）：只认**墙层**的 LINE/LWPOLYLINE；墙若画在块（INSERT）内部，
      本尺子看不见 ⇒ 本行只是**诊断**，不落成判据。
    """
    import recognize as R
    from shapely.strtree import STRtree
    rows = []
    for f in floors():
        p = os.path.join(CONTOURS, "%s.json" % f)
        src = os.path.join(os.path.dirname(CONTOURS), "..", "01_cad", "raw", f + ".dxf")
        if not (os.path.exists(p) and os.path.exists(src)):
            continue
        import ezdxf
        segs = []
        for e in ezdxf.readfile(src).modelspace():
            if e.dxf.layer != R.WALL_LAYER:
                continue
            t = e.dxftype()
            try:
                if t == "LINE":
                    a, b = e.dxf.start, e.dxf.end
                    segs.append(sg.LineString([(a.x, a.y), (b.x, b.y)]))
                elif t == "LWPOLYLINE":
                    ps = [(q[0], q[1]) for q in e.vertices()]
                    for i in range(len(ps) - 1):
                        segs.append(sg.LineString([ps[i], ps[i + 1]]))
            except Exception:
                continue
        if not segs:
            continue
        tree = STRtree(segs)
        with io.open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        for r in d["polys"]:
            if r.get("layer") != "LINTEL":
                continue
            pts = ring_pts(r["ring"])
            cx = sum(q[0] for q in pts) / len(pts)
            cy = sum(q[1] for q in pts) / len(pts)
            tk = thickness(r["ring"]) - 2.0 * BITE
            if tk <= 1.0:
                continue
            i = tree.nearest(sg.Point(cx, cy))
            g = segs[i] if isinstance(i, (int, np.integer)) else i   # shapely 1.8 返下标、2.x 返几何
            rows.append((g.distance(sg.Point(cx, cy)) / tk, g.distance(sg.Point(cx, cy)),
                         tk, f, r.get("id", "?")))
    rows.sort(reverse=True)
    print("板 %d 块（读源图 %d 层）｜  d/tk 的分位（d = 板心到最近源图墙线）：" % (len(rows), len(floors())))
    asc = sorted(x[0] for x in rows)
    for q in (0, 5, 25, 50, 75, 90, 95, 100):
        i = min(len(asc) - 1, int(round(q / 100.0 * (len(asc) - 1))))
        print("   %3d%%  d/tk = %5.2f" % (q, asc[i]))
    hist = [0] * 10
    for r0, *_ in rows:
        hist[min(9, int(r0))] += 1
    print("── 直方图（每格 1×tk）：")
    for k in range(10):
        print("   %d~%d tk  %4d  %s" % (k, k + 1, hist[k],
                                        "#" * max(1, int(60.0 * hist[k] / max(1, len(rows)))) if hist[k] else ""))
    print("── d/tk 最大的 %d 块：" % top)
    for r0, dd, tk, f, rid in rows[:top]:
        print("   %-8s %-18s d/tk=%5.2f ｜ d=%6.0f ｜ tk=%7.1f" % (f, rid, r0, dd, tk))
    return 0


def wallthick(top=15):
    """★**建板用的那份墙**（`build3d.wall_polys`）的厚度分布 —— 板厚该落在哪儿由它定。

    为什么要有这一条：`参数.json` 的 `门.墙厚` 一直是 `null`「待坐实」，量的是
    「门头墙的厚度方向尺寸」；而没有它，判「板补得太厚」就只能手打一个阈值（铁律 103 不许）。
    量法与**板**那一把完全相同（内切半径，本文件 `thickness()`），而且是同一份 W ——
    铁律 192：参照物必须与交付件同作用域。

    ★ 盲区（铁律 158）：内切半径量的是**块的最粗处**，墙的**丁字/十字接头**会把它喂胖；
      所以这份分布的上尾本来就宽，判据只能取它做**参照**，不能当「墙就该这么厚」。
    """
    import build3d as B3
    import redraw as RD
    vals, per = [], {}
    for f in floors():
        v = RD.geometry(f)
        a = [thickness(list(g.exterior.coords)) for g in B3.wall_polys(v)]
        a = [x for x in a if x > 1.0]
        per[f] = sorted(a)
        vals += a
    vals.sort()
    n = len(vals)
    print("全楼 wall_polys 块 %d ｜ 厚度（内切半径）分位：" % n)
    qs = (1, 5, 25, 50, 75, 90, 95, 99, 100)
    for q in qs:
        i = min(n - 1, int(round(q / 100.0 * (n - 1))))
        print("   %3d%%  %7.1f mm" % (q, vals[i]))
    if n:
        lo = vals[min(n - 1, int(round(0.05 * (n - 1))))]
        hi = vals[min(n - 1, int(round(0.95 * (n - 1))))]
        # ★ 判据的**分辨力**必须拿真缺陷喂一遍（铁律 137）：把这两个数按到板那一列上，
        #   看那 5 处厚板落不落在区间外、正常板会不会被误伤。
        bad, tot = [], 0
        for f in floors():
            p = os.path.join(CONTOURS, "%s.json" % f)
            if not os.path.exists(p):
                continue
            for tk, th, cx, cy, rid in read(f):
                tot += 1
                if tk < lo or tk > hi:
                    bad.append((tk, f, rid, cx, cy))
        bad.sort(reverse=True)
        print("── 板 tk 落在 [p5=%.0f, p95=%.0f] **之外**的：%d / %d 块" % (lo, hi, len(bad), tot))
        for tk, f, rid, cx, cy in bad[:top]:
            print("   %-8s %-18s tk=%7.1f  @(%.0f, %.0f)" % (f, rid, tk, cx, cy))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor")
    ap.add_argument("--json", action="store_true", help="只吐一行机器可读汇总")
    ap.add_argument("--top", type=int, default=5, help="最厚的几块（默认 5）")
    ap.add_argument("--over", type=float, default=None,
                    help="板厚超过这个数（mm）就报告块数 —— 阈值**从命令行给**，"
                         "不写进代码（正常板厚 = 本层墙厚 + 2×缝合，本楼墙厚中位 300 ⇒ 360）")
    ap.add_argument("--probe", nargs=2, metavar=("X", "Y"),
                    help="★ 局部 ASCII 图：以 (X, Y) 为中心看这一小块的墙带长什么样")
    ap.add_argument("--onwall", action="store_true",
                    help="★ 「板下是墙」的比例分布（诊断：把「板建在没墙处」与「板在墙上只是量胖」分开）")
    ap.add_argument("--srcwall", action="store_true",
                    help="★ 板心到源图墙线的距离 ÷ 板厚（诊断：凭空造的板会明显偏出）")
    ap.add_argument("--wallthick", action="store_true",
                    help="★ 建板那份墙（wall_polys）的厚度分布 + 板 tk 落在区间外的块")
    ap.add_argument("--span", type=float, default=2500.0, help="--probe 的半窗（mm）")
    ap.add_argument("--cell", type=float, default=200.0, help="--probe 每格（mm）")
    a = ap.parse_args()

    if a.onwall:
        return onwall(top=a.top)

    if a.srcwall:
        return srcwall(top=a.top)

    if a.wallthick:
        return wallthick(top=a.top)

    if a.probe:
        if not a.floor:
            print("--probe 要配 --floor")
            return 2
        return probe(a.floor, float(a.probe[0]), float(a.probe[1]), a.span, a.cell)

    fl = [a.floor] if a.floor else floors()
    allv, worst, nthick = [], [], 0
    for f in fl:
        if not os.path.exists(os.path.join(CONTOURS, "%s.json" % f)):
            print("★ 没有 %s" % f)
            continue
        rows = read(f)
        tks = [r[0] for r in rows]
        allv += tks
        if a.over is not None:
            nthick += sum(1 for th in [r[1] for r in rows] if th > a.over)
        worst += [(r[0], r[1], r[2], r[3], r[4], f) for r in rows]
        if not a.json:
            over = [t for t in tks if t > TK_MAX]
            print("%-8s 板 %3d ｜ tk 最小 %6.0f 中位 %6.0f 最大 %7.0f ｜ >墙厚上限(%d) %d 块"
                  % (f, len(rows), min(tks) if tks else 0,
                     sorted(tks)[len(tks) // 2] if tks else 0,
                     max(tks) if tks else 0, int(TK_MAX), len(over)))

    if not allv:
        return 2
    s = sorted(allv)
    over = sum(1 for t in s if t > TK_MAX)
    if a.json:
        # ★ 机器可读那一行：字段全是从读数算的，没有手打数（铁律 103）
        print(json.dumps({"板": len(s), "tk最小": round(s[0], 1),
                          "tk中位": round(s[len(s) // 2], 1), "tk最大": round(s[-1], 1),
                          "超墙厚上限": over, "墙厚上限": TK_MAX, "缝合": BITE},
                         ensure_ascii=False))
        return 0
    print("── 合计 板 %d ｜ tk 最小 %.0f 中位 %.0f 最大 %.0f ｜ 超墙厚上限 %d 块"
          % (len(s), s[0], s[len(s) // 2], s[-1], over))
    if a.over is not None:
        print("── 板厚 > %.0f mm 的：%d 块（阈值来自命令行，仅供同一把尺子前后对比）"
              % (a.over, nthick))
    print("── 最厚的 %d 块：" % a.top)
    for tk, th, cx, cy, rid, f in sorted(worst, reverse=True)[:a.top]:
        print("   %-8s %-18s tk=%7.1f 板厚=%7.1f  @(%.0f, %.0f)"
              % (f, rid, tk, th, cx, cy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
