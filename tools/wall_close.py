# -*- coding: utf-8 -*-
"""按**交付口径**（实景三维 LOD1.3 = 棱柱体、外墙闭合、不表达门窗洞）把逐层件墙上的洞口补平。

★ 为什么需要它（全部实测，不是判断）：
  libs3d/c006 那条链按图纸线建墙，`build8.py::bridge_gaps` 的原文注释就是
  「**墙实体仍按图纸不补**」；它只给**门**造门头（`b8e.log`：门 754 扇 / 门头 754），
  **窗洞一个都不补**。⇒ 交付逐层件里量到 **709 条 ≥50 mm 的缝，逐条在
  z=1000 / z=2850 / z=3300 三个高度上问，**100% 是整层高的洞**、0 条有门头。
  用户判词：「墙与墙之间没有接上」。见 _scratch/probe_gap_height.py。

★ 判据（**只认「同一面墙被挖了个洞」**，不认「两堵墙之间空着」）：
    两块之间 50 ≤ 缝宽 ≤ GAP_MAX，且
      ① 两块在缝的两端**各自都有一张面**朝着对方（|n·û| ≥ FACE_DOT，且最近顶点离端点 ≤ NEAR）；
      ② 两张相望面的**墙厚一致**（|t_i − t_j| ≤ T_TOL）、**中线对齐**（|c_i − c_j| ≤ C_TOL）、
         竖向跨度一致（|h_i − h_j| ≤ H_TOL）；
      ③ 实测墙厚 ≤ T_MAX（"这是墙不是柱" 的绝对闸；build8 的 WALL_T = 240）。
    ⇒ 外廊柱（600 见方）与外墙（240 厚）在②或③当场被否掉 ⇒ **不补**，敞开的外廊不会被堵死。
      实测：F1 那四条 3000 mm 的外廊缝 **全被③拦下**（厚 600/2143 · 600/2380 · 600/838 · 600/600），
      其中「厚 600/600」（两根柱子相对）**只有③拦得住** ⇒ 这道闸是承重墙不是装饰。

★ 成对**不许只取最近邻**：一根墙垛**两头各有一扇窗**时，nearest 只把它跟最近的那一头配上
  ⇒ **另一扇窗永远漏着**。实测 F1：nearest 的补块（108 面 / 3.7 m²）是 all 的**真子集**
  （108/108 全在 all 的 732 面里），且对**图纸墙带**的命中率更低（29.9% vs 43.1%）。
  ⇒ 本工具取**全部成对**。

★ 但「全部成对」**只能算一趟**：补块自己是新的整层高块，会互相配
  （F1：一趟 183 根 → 拿补后件自己的块当候选复量 **225** 条 → 再补 → 越铺越大）。
  所以「一趟就是闭包」要**钉死候选**来量：`residual_on(原件, 补后件)` —— 把原件的墙当候选、
  补块永不进候选，实测原件的 198 面墙之间剩 **0** 条 ⇒ 一趟就是闭包，判据按构造终止。

★ 断面尺寸**全部量自实测端面**（厚 = 两片相望面的重叠宽度，高 = 两块竖向跨度之并）
  —— 不臆造门高 / 窗台高（2D 图里根本没有这些高度）。

★ 独立核（不是拿本工具的判据核自己）：把补块投到平面，量它落在**图纸 4.2墙体 240 宽墙带**
  里的面积占比。F1：补块 42.1 m²，落在墙带里 **49.1%**，而整层随机点只有 **7.70%**（尺子地板）。
  84 个补块**无一**离最近的图纸墙线超过 **750 mm**（中位 120 mm）⇒ 没有一块是凭空造墙。
  见 _scratch/verify_close_vs_dwg.py。

★ 本工具**不建墙、不改墙**，只做加法：把一根与两侧同厚同高的补块并进原件。

用法(命令行):
  python tools/wall_close.py <piece.glb> [--report] [--out x.glb] [--json x.json]
用法(模块):
  from wall_close import analyze, close          # 判据只有这一份，闸门也 import 它
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from shapely.geometry import Polygon as SPoly

GAP_MIN_MM = 50.0          # ≥50 mm 才算缝（<50 是发丝缝，屏幕上看不见）
GAP_MAX_MM = 6000.0        # >6 m 的当「厅/中庭」不补 —— ★ 决定，代价写进 json
WALL_MIN_RATIO = 0.80      # 竖向占层高 ≥80% 才算墙（门 2100/3600=58%、门头 1500/3600=42%）
FACE_DOT = 0.80            # 相望面：面法向与缝方向夹角余弦 ≥ 此值（≈37°）
NEAR_MM = 400.0            # 相望面最近顶点离缝端点上限
T_MIN_MM = 120.0           # 实测墙厚下限（比这薄是隔墙/线脚，不当外墙洞）
T_MAX_MM = 400.0           # 实测墙厚上限（比这厚是柱/墙垛，不是被挖洞的墙）
T_TOL = 60.0               # 两端墙厚差上限
C_TOL = 60.0               # 两端墙中线错位上限
H_TOL = 150.0              # 两端竖向跨度差上限
PAD_MM = 80.0              # 两端各多扫 80 mm 压进原件，保证并起来在屏幕上没缝
MERGE_MM = 100.0           # 同一扇窗会被两条边各判一次 ⇒ 按补块中心这么近就算同一根

# 独立校核（dwg_band_check）用的 DXF 口径 —— C006 那一张图；换栋换图要改这三行
DXF_PATH = r"D:\项目\gym3d\材料\dxf_output\C006-第六教学楼（逸夫楼）.dxf"
XB = {"L": 1013200.0, "R": 1482900.0}
Y0, Y1P = 47500.0, 135000.0

CRITERION = ("同一面墙被挖洞：缝 %.0f..%.0f mm 且两端相望面 厚∈[%.0f,%.0f] 同厚±%.0f "
             "同中线±%.0f 同跨度±%.0f" % (GAP_MIN_MM, GAP_MAX_MM, T_MIN_MM, T_MAX_MM,
                                          T_TOL, C_TOL, H_TOL))


def load(path):
    o = trimesh.load(path, force="scene")
    return o.dump(concatenate=True) if isinstance(o, trimesh.Scene) else o


def vertical_axis(m):
    """竖直轴不写死：按「跨度最小」认（逐层件 = 129 × 3.72 × 84 m；wall-only 件 Z 朝上）。"""
    b = m.bounds
    span = [float(b[1][k] - b[0][k]) for k in range(3)]
    return int(np.argmin(span)), span


def wall_components(m, vax, height):
    ps = [p for p in m.split(only_watertight=False) if len(p.vertices) > 3]
    out = []
    for p in ps:
        v = np.array(p.vertices, float)
        tri = np.array(p.triangles, float)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ln = np.linalg.norm(n, axis=1)
        ln[ln == 0] = 1.0
        out.append({"mesh": p, "v": v, "tri": tri, "n": n / ln[:, None],
                    "ext": float(v[:, vax].max() - v[:, vax].min()),
                    # ★ 量表面距用的副本：**剔掉零面积三角**。
                    #   零面积三角没有"面"，留着只会让 trimesh 的
                    #   `point_triangle_distance` 在重心坐标里 0/0 出 NaN（实测 F1 2 条、全楼 15 条）。
                    #   这是把**量具**擦干净，不是改墙：被剔的都是面积 0 的面，几何上不占任何位置。
                    "prox": trimesh.Trimesh(
                        vertices=v,
                        faces=np.asarray(p.faces)[
                            np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                                    tri[:, 2] - tri[:, 0]), axis=1) > 1e-6],
                        process=False)})
    for c in out:
        c["is_wall"] = c["ext"] >= WALL_MIN_RATIO * height
    return out


def _surf_mm(comp, P):
    """点 P 到该块**表面**的最短距离（mm）。量不出（退化三角 ⇒ NaN）返 +inf，由调用方决定怎么办。

    `comp["prox"]` 是剔掉零面积三角的副本（见 wall_components）；没有就退回 comp["mesh"]。
    """
    m = comp.get("prox")
    if m is None:
        m = comp["mesh"]
    d = float(trimesh.proximity.closest_point_naive(m, np.asarray(P, float)[None, :])[1][0])
    return d if np.isfinite(d) else float("inf")


def facing_span(comp, P, u, e1, e2):
    """该块在缝端点 P 处、朝着缝的那张面的 (厚向区间, 竖向区间)，**绝对坐标**。取不到返 None。

    ★ 必须给**绝对**坐标，不许相对 P：缝的两端 A、B 是「最近顶点对」，**两点可以不等高**
      （A 在上角、B 在下角），各自相对自己的 P 报的区间混起来 min/max，
      就是两个不同原点的量相加（铁律 174）—— 实测后果：竖向区间被撑成两层高，
      补块捅出层外，闸门的 B（包络）当场报 floor1..floor10 超出原件。
    """
    tri, n = comp["tri"], comp["n"]
    # 最近顶点的 ∞ 距离 ≤ NEAR（不是「三个顶点都在框里」—— 大面片会被后者漏掉）
    near = (np.abs(tri - P).max(axis=2)).min(axis=1) <= NEAR_MM
    keep = near & (np.abs(n @ u) >= FACE_DOT)
    if not keep.any():
        return None
    V = tri[keep].reshape(-1, 3)
    t, z = V @ e1, V @ e2            # 厚向、竖向，都是**世界**坐标的投影
    return (float(t.min()), float(t.max())), (float(z.min()), float(z.max()))


def analyze(m, pairing="all", walls=None):
    """量一件（内存里的 trimesh）：哪些缝该补、补成什么样。**不写盘、不改件**。

    pairing:
      "all"     —— 全部成对（**默认**）。★ 为什么不能用 nearest：一根墙垛两头各有一扇窗时，
                   nearest 只把它跟**最近的**那一头配上 ⇒ **另一扇窗永远漏着**。
                   实测 F1：nearest 的补块是 all 的**真子集**（108/108 全在 all 里，all 732 面）。
      "nearest" —— 每块只跟最近的另一块配。★ 实测**能收敛**（第 2 趟 0）但**补得太少**
                   （F1: 27 根 / 3.7 m²，all 183 根 / 41.4 m²），且对图纸墙带的命中率更低
                   （29.9% vs 43.1%）。保留只作对照，不是交付口径。

    walls: 只拿**这一批**块当候选（默认为 None = 用 m 自己分出来的墙块）。
           ★ 这是「一趟就是闭包」的**判据形式**：把「原件那几面墙」钉死当候选，
             补块永远不进候选 ⇒ 量「原件之间还有没有漏着的缝」这件事**按构造终止**。
             （不钉的话补块自己会互相配：F1 第 1 趟 183 → 复量 225 → 再补 → 越铺越大。）

    返回 dict: vax / height_mm / n_comps / n_walls / n_pairs / filled / skipped / n_unmeasured
    filled[i]["mesh"] 是那根补块（已摆在件内坐标）。
    """
    vax, span = vertical_axis(m)
    height = span[vax]
    comps = wall_components(m, vax, height)
    walls = [c for c in comps if c["is_wall"]] if walls is None else list(walls)
    pts = [c["v"] for c in walls]
    trees = [cKDTree(q) for q in pts]
    e2 = np.zeros(3)
    e2[vax] = 1.0

    n = len(walls)
    pairs = {}
    if pairing == "nearest":
        for i in range(n):
            best = (float("inf"), -1, None, None)
            for j in range(n):
                if i == j:
                    continue
                d, k = trees[j].query(pts[i], k=1)
                if not len(d):
                    continue
                q = int(np.argmin(d))
                if float(d[q]) < best[0]:
                    best = (float(d[q]), j, pts[i][q], pts[j][k[q]])
            d, j, A, B = best
            if j < 0 or not (GAP_MIN_MM <= d <= GAP_MAX_MM):
                continue
            key = (min(i, j), max(i, j))
            if key not in pairs or d < pairs[key][0]:
                pairs[key] = (d, i, j, A, B)     # ★ A 属于 **i**，消费端按这个 i 取块
    else:
        for i in range(n):
            for j in range(i + 1, n):
                d, k = trees[j].query(pts[i], k=1)
                if not len(d):
                    continue
                q = int(np.argmin(d))
                dv = float(d[q])
                if GAP_MIN_MM <= dv <= GAP_MAX_MM:
                    pairs[(i, j)] = (dv, i, j, pts[i][q], pts[j][k[q]])

    # ★ 顶点距 ≠ 表面距：补块补好后是**叠在**墙里的，它的端面顶点离墙的顶点还差 ~64 mm
    #   ⇒ 「刚补好的缝」会以 53~80 mm 的样子再报一次：补了又补、永不收敛
    #   （实测 nearest 配对：修前第 2 趟起每趟恒 +4 根，8 趟不收敛；修后第 2 趟 0）。
    #   候选缝一律回**表面距**复核：叠上了（≤GAP_MIN）就不算缝。这一条是收敛的充要条件。
    n_unmeasured = 0
    for key in list(pairs):
        d, i, j, A, B = pairs[key]
        A = np.asarray(A, float)
        B = np.asarray(B, float)
        di = _surf_mm(walls[i], B)
        dj = _surf_mm(walls[j], A)
        ds = min(di, dj)
        if not np.isfinite(ds):
            # 两侧都量不出表面距（退化三角 ⇒ trimesh 里 0/0 出 NaN）。
            # ★ 这**不许**当成「没缝」悄悄扔掉：退回顶点距，并把条数报出去（判据里看得见）。
            n_unmeasured += 1
            ds = d
        if GAP_MIN_MM <= ds <= GAP_MAX_MM:
            pairs[key] = (ds, i, j, A, B)
        else:
            del pairs[key]

    filled, skipped, by_c = [], [], {}
    for d, i, j, A, B in sorted(pairs.values(), key=lambda t: -t[0]):
        A = np.array(A, float)
        B = np.array(B, float)
        u = B - A
        u[vax] = 0.0
        L = float(np.linalg.norm(u))
        at = [round(x, 1) for x in A]
        if L <= 1.0:
            skipped.append({"d_mm": d, "why": "缝在竖直方向", "at": at})
            continue
        u = u / L
        e1 = np.cross(e2, u)
        e1 /= max(np.linalg.norm(e1), 1e-9)
        Si = facing_span(walls[i], A, u, e1, e2)
        Sj = facing_span(walls[j], B, u, e1, e2)
        if Si is None or Sj is None:
            skipped.append({"d_mm": d, "why": "一端取不到相望面", "at": at})
            continue
        ti, tj = Si[0][1] - Si[0][0], Sj[0][1] - Sj[0][0]
        ci, cj = (Si[0][0] + Si[0][1]) / 2.0, (Sj[0][0] + Sj[0][1]) / 2.0
        hi, hj = Si[1][1] - Si[1][0], Sj[1][1] - Sj[1][0]
        why = []
        if not (T_MIN_MM <= min(ti, tj)) or max(ti, tj) > T_MAX_MM:
            why.append("厚 %.0f/%.0f 不在墙的档" % (ti, tj))
        elif abs(ti - tj) > T_TOL:
            why.append("墙厚 %.0f≠%.0f" % (ti, tj))
        if abs(ci - cj) > C_TOL:
            why.append("中线错 %.0f" % (ci - cj))
        if abs(hi - hj) > H_TOL:
            why.append("竖向跨 %.0f≠%.0f" % (hi, hj))
        if why:
            skipped.append({"d_mm": d, "why": " / ".join(why), "at": at,
                            "t_mm": [round(ti, 1), round(tj, 1)]})
            continue
        lo1, hi1 = max(Si[0][0], Sj[0][0]), min(Si[0][1], Sj[0][1])
        if hi1 - lo1 < 0.6 * min(ti, tj):          # 厚向几乎不重叠 ⇒ 不是同一面墙
            skipped.append({"d_mm": d, "why": "墙厚区间不重叠", "at": at,
                            "t_mm": [round(ti, 1), round(tj, 1)]})
            continue
        # 竖向：两个**绝对**区间取并 —— 补块要盖满两端并起来的那一段
        lo2, hi2 = min(Si[1][0], Sj[1][0]), max(Si[1][1], Sj[1][1])
        if hi2 - lo2 <= T_MIN_MM:
            skipped.append({"d_mm": d, "why": "竖向区间退化", "at": at})
            continue
        # Si/Sj 是世界坐标下的绝对投影，而 T 只把局部 x/y 当**方向**（原点在 T[:3,3]）
        # ⇒ 必须先把 A 在 e1/e2 上的投影减掉，否则层标高会被加两遍（铁律 174 的另一半）。
        ax, az = float(A @ e1), float(A @ e2)
        poly = SPoly([(lo1 - ax, lo2 - az), (hi1 - ax, lo2 - az),
                      (hi1 - ax, hi2 - az), (lo1 - ax, hi2 - az)])
        prism = trimesh.creation.extrude_polygon(poly, height=L + 2 * PAD_MM)
        T = np.eye(4)
        T[:3, 0] = e1          # 局部 x → 厚向（原点已在 A）
        T[:3, 1] = e2          # 局部 y → 竖直（原点已在 A）
        T[:3, 2] = u           # 挤出方向 → 缝方向
        T[:3, 3] = A - u * PAD_MM
        prism.apply_transform(T)
        c = prism.centroid
        key = (round(c[0] / MERGE_MM), round(c[1] / MERGE_MM), round(c[2] / MERGE_MM))
        rec = {"d_mm": d, "at": at, "b": [round(x, 1) for x in (A + u * L)],
               "mesh": prism, "thick_mm": hi1 - lo1,
               "height_mm": hi2 - lo2, "t_mm": [round(ti, 1), round(tj, 1)]}
        if key not in by_c or rec["d_mm"] > by_c[key]["d_mm"]:
            by_c[key] = rec
    filled = list(by_c.values())
    return {"vax": vax, "height_mm": height, "n_comps": len(comps), "n_walls": len(walls),
            "n_pairs": len(pairs), "filled": filled, "skipped": skipped,
            "n_unmeasured": n_unmeasured}


def close(m):
    """补平一件。**只走一趟**（判据在原件上算一次，补块不进候选 ⇒ 按构造终止）。
    返回 (补后件, analyze 的 info)。filled 为空时原件原样返回。"""
    info = analyze(m)
    if not info["filled"]:
        return m, info
    return trimesh.util.concatenate([m] + [f["mesh"] for f in info["filled"]]), info


def residual_on(m_orig, m_closed, fills):
    """**闭包判据**：原件墙之间还剩几条**没被补块跨过去**的缝。应恒为 0。

    返回 (analyze 的 info, 残留列表)。

    ★ 这一条我写错过一次，记在这儿：第一版写成
        `analyze(补后件, walls=原件墙块)` —— 只量**原件墙↔原件墙**，
      补块是第三样东西、根本不进这个度量 ⇒ 缝还在原处，**183 条一条不少**。
      量「补上了没有」必须**去问补块**：缝的中点落不落在某根补块里。
    ★ 也不许拿补后件**自己的全部块**当候选：补块会互相配（F1 复量 225 条），
      那是补块重叠、不是没接上的墙。
    """
    vax, span = vertical_axis(m_orig)
    w = [c for c in wall_components(m_orig, vax, span[vax]) if c["is_wall"]]
    info = analyze(m_closed, pairing="all", walls=w)
    fms = [f["mesh"] for f in fills]
    boxes = [(np.asarray(q.bounds[0], float) - GAP_MIN_MM,
              np.asarray(q.bounds[1], float) + GAP_MIN_MM) for q in fms]
    out = []
    for f in info["filled"]:
        M = (np.asarray(f["at"], float) + np.asarray(f["b"], float)) / 2.0
        hit = False
        for k, (lo, hi) in enumerate(boxes):
            if np.all(M >= lo) and np.all(M <= hi) and _surf_mm({"mesh": fms[k]}, M) <= GAP_MIN_MM:
                hit = True
                break
        if not hit:
            out.append(f)
    return info, out


def dwg_band_check(m, fills, col, row, dxf=DXF_PATH, wall_t=240.0):
    """**独立校核**：补块的平面足迹落在**图纸 `4.2墙体` 墙带**里的面积占比。

    ★ 为什么这算独立：参考侧是 **DXF 文件**（图纸，另一条链的产物），不是本工具自己的判据
      —— 拿自己的判据核自己，判据错了两边一起错。
    ★ 符号**不许假设**：件内第二平面轴相对图纸 y 的符号由**原件自己的足迹**标定
      （原件是忠实的：它落在哪个符号的墙带里多，就取哪个）。写死符号会把整层镜像看不出来。

    返回 dict 或 None（取不到墙带 ⇒ 「没量到」，不许报 0）。
    """
    import ezdxf  # 局部 import：只有真跑这条校核时才需要
    from shapely.geometry import LineString, Point, Polygon as SP, box
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    vax, span = vertical_axis(m)
    keep = [k for k in range(3) if k != vax]
    ta = np.array(m.triangles, float)[:, :, keep]
    bb = box(ta[:, :, 0].min() - 3000, ta[:, :, 1].min() - 3000,
             ta[:, :, 0].max() + 3000, ta[:, :, 1].max() + 3000)
    doc = ezdxf.readfile(dxf)

    def band(sy):
        segs = []
        for e in doc.modelspace().query("LWPOLYLINE LINE"):
            if e.dxf.layer != "4.2墙体":
                continue
            if e.dxftype() == "LINE":
                raw = [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))]
            else:
                q = [(t[0], t[1]) for t in e.get_points()]
                raw = [(q[i], q[i + 1]) for i in range(len(q) - 1)]
                if e.closed and len(q) > 2:
                    raw.append((q[-1], q[0]))
            for (a1, c1) in raw:
                P = ((a1[0] - XB[col]), sy * (a1[1] - (Y0 + row * Y1P)))
                Q = ((c1[0] - XB[col]), sy * (c1[1] - (Y0 + row * Y1P)))
                ln = LineString([P, Q])
                if ln.intersects(bb):
                    segs.append(ln)
        if not segs:
            return None, 0, None
        return (unary_union([s.buffer(wall_t / 2, cap_style=2, join_style=2) for s in segs]),
                len(segs), segs)

    # ★ 标定与「原件落位」一律只用**墙块**（is_wall），不许拿整件：
    #   整件里楼板占绝大多数面积 ⇒ 足迹被板淹没，符号标定的信噪比差（实测 7.1% vs 0.1%，勉强分得开）。
    comps = wall_components(m, vax, span[vax])
    wt = [np.array(c["tri"], float)[:, :, keep] for c in comps if c.get("is_wall")]
    if not wt:
        return None
    wa = np.concatenate(wt, axis=0)
    orig = unary_union([SP(t) for t in wa if SP(t).is_valid and SP(t).area > 1.0])
    best = None
    for sy in (1, -1):
        bnd, ns, segs = band(sy)
        if bnd is None:
            continue
        fr = orig.intersection(bnd).area / max(orig.area, 1e-9)
        if best is None or fr > best[0]:
            best = (fr, sy, bnd, ns, segs)
    if best is None:
        return None
    _, sy, bnd, ns, segs = best
    tree = STRtree(segs)
    rng = np.random.default_rng(0)
    R = rng.uniform([bb.bounds[0], bb.bounds[1]], [bb.bounds[2], bb.bounds[3]], size=(40000, 2))
    floor = 100.0 * sum(1 for p in R if bnd.contains(Point(p))) / len(R)

    polys = []
    for f in fills:
        t = np.array(f["mesh"].triangles, float)[:, :, keep]
        polys += [SP(q) for q in t if SP(q).is_valid and SP(q).area > 1.0]
    base = {"sy": sy, "drawn_wall_lines": ns,
            "orig_on_band_pct": round(100.0 * best[0], 2),
            "random_floor_pct": round(floor, 2)}
    if not polys:
        # 没有补块不是错：拿它当**基线**（原件的墙足迹盖住图纸墙带多少）。补块那几个量记 None。
        base.update({"filler_area_m2": None, "blocks": 0, "on_band_pct": None,
                     "dist_to_drawn_line_mm": None, "note": "没有补块 ⇒ 只报墙足迹落位"})
        return base
    # 连通块（不是逐三角求和：盒子的顶+底两张面投到平面是**同一个矩形**，逐三角求和会 ×4）
    ptree = STRtree(polys)
    seen, blocks = set(), []
    for i in range(len(polys)):
        if i in seen:
            continue
        grp, seen = [i], seen | {i}
        k = 0
        while k < len(grp):
            q = polys[grp[k]].buffer(5.0)
            for j in ptree.query(q):          # ★ STRtree.query 给的是**下标**，不是几何
                j = int(j)
                if j not in seen and polys[j].intersects(q):
                    seen.add(j); grp.append(j)
            k += 1
        blocks.append(unary_union([polys[j] for j in grp]))
    tot = sum(g.area for g in blocks)
    ins = sum(g.intersection(bnd).area for g in blocks)
    ds = []
    for g in blocks:
        c0 = g.centroid
        idx = tree.query(Point(c0.x, c0.y))
        if len(idx):
            ds.append(min(segs[int(j)].distance(Point(c0.x, c0.y)) for j in idx))
    return {"sy": sy, "drawn_wall_lines": ns,
            "orig_on_band_pct": round(100.0 * best[0], 2),
            "filler_area_m2": round(tot / 1e6, 2), "blocks": len(blocks),  # noqa: E501
            "on_band_pct": round(100.0 * ins / max(tot, 1e-9), 1),
            "random_floor_pct": round(floor, 2),
            "dist_to_drawn_line_mm": {"median": round(float(np.median(ds)), 0) if ds else None,
                                      "max": round(float(np.max(ds)), 0) if ds else None,
                                      "over_2000": int(sum(1 for d in ds if d > 2000))}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dwg-col", choices=["L", "R"], default=None,
                    help="跑独立校核：本件对应图纸的哪一列（不给则不跑，json 里记「没量到」）")
    ap.add_argument("--dwg-row", type=int, default=None, help="本件对应图纸的哪一行（0 基）")
    a = ap.parse_args()

    m = load(a.glb)
    info = analyze(m)
    filled, skipped = info["filled"], info["skipped"]
    print("%s  竖轴=%s 层高=%.0f mm  块 %d（墙 %d）  墙↔墙缝 **%d 条**"
          % (os.path.basename(a.glb), "XYZ"[info["vax"]], info["height_mm"],
             info["n_comps"], info["n_walls"], info["n_pairs"]))
    vol = sum(abs(float(f["mesh"].volume)) for f in filled) / 1e9
    print("  补块 **%d 根**（补进去 %.2f m³）  跳过 %d 条" % (len(filled), vol, len(skipped)))
    hist = {}
    for s in skipped:
        k = s["why"].split(" /")[0]
        hist[k] = hist.get(k, 0) + 1
    for k in sorted(hist, key=lambda x: -hist[x])[:8]:
        print("      跳过 %-24s %d" % (k, hist[k]))
    for f in sorted(filled, key=lambda f: -f["d_mm"])[:6]:
        print("     补 %7.1f mm  厚 %.0f 高 %.0f  @(%.2f, %.2f, %.2f)"
              % (f["d_mm"], f["thick_mm"], f["height_mm"], *[x / 1000.0 for x in f["at"]]))
    ws = sorted(f["d_mm"] for f in filled)
    if ws:
        bkt = {}
        for w in ws:
            bkt[int(w // 500) * 500] = bkt.get(int(w // 500) * 500, 0) + 1
        print("  补块宽度分布（每 500 mm 一档）: " +
              "  ".join("%d:%d" % (k, bkt[k]) for k in sorted(bkt)))

    if a.report or not a.out:
        return 0
    cat, _ = close(m)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cat.export(a.out)
    chk = load(a.out)
    print("  写出 %s  面 %d → %d（+%d）"
          % (a.out, len(m.faces), len(chk.faces), len(chk.faces) - len(m.faces)))
    # ★ 补后量「原件之间还剩几条**没被补块跨过去**的」。应当 0。
    #   不许拿「补后件的全部块」当候选（补块互相配 = 225 条重叠）——
    #   也不许只钉死原件当候选（补块不进度量 = 183 条假漏）。见 residual_on 的注释。
    _, resid_l = residual_on(m, chk, filled)
    resid = len(resid_l)
    print("  复量        : 原件 %d 面墙之间，补后**没被补块跨过去**的缝 **%d 条**（应为 0）"
          % (info["n_walls"], resid))
    if a.json:
        doc = {"schema": "cdut3d-wallclose/1", "src": a.glb, "out": a.out,
               "vertical_axis": "XYZ"[info["vax"]], "height_mm": info["height_mm"],
               "criterion": CRITERION, "gaps_wall_wall": info["n_pairs"],
               "n_filled": len(filled), "n_skipped": len(skipped),
               "n_unmeasured": info["n_unmeasured"],
               "filled": [{k: f[k] for k in ("d_mm", "at", "thick_mm", "height_mm", "t_mm")}
                          for f in filled],
               "skipped": skipped,
               "added_volume_m3": round(vol, 3),
               "faces": {"before": int(len(m.faces)), "after": int(len(chk.faces))},
               "residual_after_close": resid,
               # ★ 独立校核的数**一律现算**（铁律 103：期望值由程序算出，不许手打）
               "independent_check": dwg_band_check(chk, filled, a.dwg_col, a.dwg_row)
               if a.dwg_col else {"note": "没给 --dwg-col/--dwg-row ⇒ 本条**没量到**（不是 0）"},
               "PENDING": ["补的是**外墙洞口的棱柱体**，按 LOD1.3「外墙闭合、不表达门窗洞」；"
                           "近景构件（门窗扇/雨篷/台阶）见方案 §6.8.5，本工具不做。"]}
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        open(a.json, "wb").write(
            json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8").replace(b"\r\n", b"\n"))
        print("  meta        :", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
