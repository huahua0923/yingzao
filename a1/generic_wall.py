# -*- coding: utf-8 -*-
"""A1：**通用墙链** —— 从任意一栋的 DXF 出发，建墙、并按与 c006/score8 同口径打分。

与 c006 链的关系：打分侧（ref 栅格 / IoU / 墙线覆盖）**逐行照抄 score8.py**，
只把三处写死的东西换成**参数**：
  · 源 DXF         ← argv
  · 「层→图纸矩形」← `a1/sheet_grid.py` 自动定位（替掉写死的 `XBOX/XB/Y0/Y1`）
  · 段序剔段(json) ← 本脚本**不用**（新楼没有那份 json；缺了就是「不剔」，与 score8 的旧口径一致）
  · 剔踏步         ← **在链里做**（`a1/treads.py`，照冻结基线 `build8:169` / `score8:149` 的口径）。
                      ★ 这是**通用化时漏掉的一行**：`import treadlib` 抄了、调用没抄（铁律 17）
                      ⇒ C006 实测多出 707.331 m²（15.81%）「踏步当墙建」的假墙身。

★ 两个数分别是什么（**关键**）：
  · `IoU`  = 模型足迹 ∩ 参照足迹 / 并集。参照足迹由 `wire()`（把相距 40~400 mm 的平行墙线
             两两配成墙身）+ 未配线缓冲 ±120 得到 —— 与建墙**同一套规则**。
             ⇒ 这个数是**自洽性**（我的实现有没有忠实实现规则），**不是**「墙对不对」的真值判据。
  · `墙线覆盖` = DXF 里真实的墙线取样点，被模型足迹盖住的比例 —— 这个**不依赖 wire() 是否成立**，
             是更硬的一个数。**看通用化要看它，别只看 IoU。**

用法: python generic_wall.py <dxf> <grid.json> [--out out.glb] [--margin 8000]
"""
import sys
import os
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import ezdxf
import trimesh
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep
from PIL import Image, ImageDraw

H = 3600.0        # 层高（c006 值；只影响挤出高度，不影响 2D 判据）
WALL_T = 240.0    # 未配对线的缓冲墙厚（c006 值）
CELL = 50.0       # 栅格（c006 值）

# ★ 墙层名**不是唯一的**（全库实测：`4.2墙体` 101 份 / `4墙体` 5 份 / `4.3封墙` 1 / `4.3新封墙` 1；
#   **0 份没有任何墙层**）。旧链只认 `4.2墙体` ⇒ 那 5 栋 `4墙体` 的墙段为空、wire([]) 直接抛 IndexError。
WALL_LAYERS = ("4.2墙体", "4墙体", "4.3封墙", "4.3新封墙")

LIBS = r"D:\项目\libs3d\c006"
sys.path.insert(0, LIBS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import treads as TR    # noqa: E402  ★ 梯（踏步）：收锚 + 剔踏步（几何规则仍在冻结的 treadlib）
import cols as COLS   # noqa: E402  ★ 通用柱加载（多路）


# ---------------- 与 score8 逐行一致的几何工具 ----------------
def segs_of(e, out):
    t = e.dxftype()
    if t == "LINE":
        a, b = (e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)
        if a != b:
            out.append(LineString([a, b]))
    elif t == "LWPOLYLINE":
        p = [(q[0], q[1]) for q in e.get_points()]
        for k in range(len(p) - 1):
            out.append(LineString([p[k], p[k + 1]]))
        if e.closed and len(p) > 2:
            out.append(LineString([p[-1], p[0]]))
    elif t in ("ARC", "CIRCLE"):
        p = [(q.x, q.y) for q in e.flattening(40)]
        for k in range(len(p) - 1):
            out.append(LineString([p[k], p[k + 1]]))
    elif t == "ELLIPSE":
        p = [(q.x, q.y) for q in e.flattening(40)]
        for k in range(len(p) - 1):
            out.append(LineString([p[k], p[k + 1]]))
    elif t == "SPLINE":
        try:
            p = [(q.x, q.y) for q in e.flattening(40)]
            for k in range(len(p) - 1):
                out.append(LineString([p[k], p[k + 1]]))
        except Exception:
            pass


def wire(segs):
    """把相距 40~400 mm 的平行墙线两两配成墙身四边形；返回 (quads, 未配对/未盖到的线)。

    ★ 比 score8.py 的 wire() 多一步修正：原来只要一条线**有一部分**配上了就 `paired=True`，
      **没配上的那段尾巴就被丢掉**（既不进 quads、也不进 unp ⇒ 永不缓冲）。
      C006 的墙是长度整齐的双线，尾巴几乎为零，所以看不出来；C011 的**长墙**一配一部分，
      尾巴成米级 ⇒ 实测 c0r3 墙线覆盖掉到 78.0%。这里把「配上了的线的**未被四边形盖住的残段**」
      一并当未配对线交出去（下游会缓冲成墙）。**score8.py 里有同形缺陷，但那边的 ref 也用同一
      函数 ⇒ 在 IoU 里自己抵消；一旦换一栋、或拿真墙线来量，就现形。**

    ★ 另一处加固：**`len(segs) < 2` 直接返回**（空 → 返回空 + 空残段）。原版对空列表会在
      `V[:, 0]` 处抛 `IndexError: too many indices for array: array is 1-dimensional`。
      实测触发场景：**某个图幅矩形里一条墙线都没有**（如一张远处的详图/说明图幅）⇒ 该图幅 segs 空。
      全库 6 栋崩过（5 栋是墙层名 `4墙体`，1 栋 C105 是这种空图幅）。
    """
    if len(segs) < 2:
        return [], list(segs)
    A = np.array([s.coords[0] for s in segs]); B = np.array([s.coords[-1] for s in segs])
    V = B - A; L = np.hypot(V[:, 0], V[:, 1])
    with np.errstate(invalid="ignore"):
        U = V / L[:, None]
    ang = np.degrees(np.arctan2(U[:, 1], U[:, 0])) % 180.0
    quads, paired = [], np.zeros(len(segs), bool)
    owners = [[] for _ in segs]          # 每条线被哪些 quad 盖过
    for i in range(len(segs)):
        if not np.isfinite(L[i]) or L[i] < 1:
            continue
        dd = np.abs(((ang - ang[i] + 90.0) % 180.0) - 90.0)
        cand = np.where((dd < 2.0) & (np.arange(len(segs)) != i))[0]
        if len(cand) == 0:
            continue
        w = A[cand] - A[i]
        perp = np.abs(U[i, 0] * w[:, 1] - U[i, 1] * w[:, 0])
        ok = (perp >= 40) & (perp <= 400)
        if not ok.any():
            continue
        cand, perp = cand[ok], perp[ok]
        t0 = (A[cand] - A[i]) @ U[i]; t1 = (B[cand] - A[i]) @ U[i]
        lo = np.maximum(np.minimum(t0, t1), 0.0); hi = np.minimum(np.maximum(t0, t1), L[i])
        good = (hi - lo) >= 0.3 * np.minimum(L[i], L[cand])
        for k in np.where(good)[0]:
            j = cand[k]
            p1 = A[i] + U[i] * lo[k]; p2 = A[i] + U[i] * hi[k]
            Uj = U[j]
            q1 = A[j] + Uj * np.dot(p1 - A[j], Uj); q2 = A[j] + Uj * np.dot(p2 - A[j], Uj)
            g = Polygon([p1, p2, q2, q1])
            if g.is_valid and g.area > 1e3:
                quads.append(g); paired[i] = paired[j] = True
                owners[i].append(g); owners[j].append(g)

    # 残段：未配对整条 + 已配对但未被任何 quad 盖住的部分
    residual = []
    for i in range(len(segs)):
        if not paired[i]:
            residual.append(segs[i])
            continue
        rem = segs[i]
        for g in owners[i]:
            rem = rem.difference(g.buffer(1.0))
            if rem.is_empty:
                break
        if rem.is_empty:
            continue
        parts = rem.geoms if hasattr(rem, "geoms") else [rem]
        for p in parts:
            if p.geom_type == "LineString" and p.length >= 50:
                residual.append(p)
    return quads, residual




def load_walls_and_cols(dxf, drop_treads=True):
    doc = ezdxf.readfile(dxf)
    return load_walls_and_cols_msp(doc.modelspace(), drop_treads=drop_treads)


def load_walls_and_cols_msp(msp, drop_treads=True):
    ALLW = []
    for e in msp:
        if e.dxf.layer not in WALL_LAYERS:
            continue
        if e.dxftype() in ("INSERT", "TEXT", "MTEXT"):
            continue
        segs_of(e, ALLW)
    # ★ 注释由 `a1/treads.py` **一处**收（默认口径 = 冻结基线：只收墙层内的 `上`/`下`；
    #   实测全库只有 4 栋有锚，其中 C105 那 178 条全在非墙层 ⇒ 基线口径看不见，见该模块盲区）。
    LABELS = TR.collect_labels(msp)
    # ★ 柱改走**通用多路加载**（cols.py）：旧链只认 INSERT ⇒ 全库覆盖 1/105。
    #   通用加载实测覆盖 41/105（有柱层的 41 栋全建出；其余 64 栋 CAD 里根本没画柱）。
    ALLC, _lh, _hits = COLS.load_cols_from_msp(msp)
    # ★★ 剔踏步 —— 照冻结基线的口径（`build8.py:169-173` 建侧 / `score8.py:149` 参照侧）。
    #   这一行是本脚本**从 score8 逐行照抄时漏掉的那一行**（`import treadlib` 抄了、调用没抄，
    #   铁律 17）。漏掉时 C006 把楼梯间里 270 mm 一道的踏步线当墙身配起来，实测多出
    #   707.331 m²（15.81%）的假墙墙身。★ 模型侧与参照侧**必须取同一批线**（score6 首行原话）。
    #   `drop_treads=False` 只给判据取「原始墙输入」用（正对照/反事实），交付口径永远为 True。
    if drop_treads:
        ALLW, _drop_idx, _groups = TR.drop_from(ALLW, LABELS)
    return ALLW, ALLC, LABELS


def score_cell(segs, cols, x0, x1, y0, y1, marg, ref_segs=None, inflate=0.0):
    """一个图纸矩形：返回 (refA, modA, interA, linecov, nquad, nunp)。

    ★ `inflate` 是**正对照用的假件开关**（默认 0 = 交付件）。>0 时把**模型那一半**的每个墙身
      向外膨胀这么多 mm，而**参照那一半（refi）保持真件** ⇒ 同一把尺子上 IoU 必掉。
      这是 A1 出口门要求的「墙厚 2 倍假件」：传 `inflate=WALL_T/2`（240 mm）即名义墙厚 ×2。
      理由是 `refi` 与 `modi` 平时由**同一个 `fp` 列表**填出来 ⇒ 恒等 ⇒ IoU 恒 100%
      （只能证「实现忠实于规则」）。要证这把尺**逮得住背离规则的件**，必须只动 `modi`。
    """
    x0 -= marg; x1 += marg; y0 -= marg; y1 += marg
    W = int((x1 - x0) / CELL); Hp = int((y1 - y0) / CELL)

    def inbox(s):
        bx0, by0, bx1, by1 = s.bounds
        return bx0 <= x1 and bx1 >= x0 and by0 <= y1 and by1 >= y0

    segs = [s for s in segs if inbox(s)]
    # ★★ 「墙线覆盖」的**取样点来源必须能与模型输入分开**（`ref_segs`）：
    #   若取样点和建墙都用同一个 `segs`，这条判据就是**循环的** —— 少喂 90% 的墙线，
    #   模型与取样点一起变少，覆盖率**照样 100%**（本判据的正对照② 实测抓到：抽掉 90% 段仍 100.00%）。
    #   ⇒ 默认 `ref_segs = segs`（照旧）；要当**外部的覆盖率**用，就把「全量真墙线」作为 ref_segs 传进来。
    refs = segs if ref_segs is None else [s for s in ref_segs if inbox(s)]
    quads, unp = wire(segs)

    def P(x, y):
        return ((x - x0) / CELL, Hp - (y - y0) / CELL)

    def fillg(dr, geom):
        gs = geom.geoms if hasattr(geom, "geoms") else [geom]
        for g in gs:
            if g.geom_type == "Polygon":
                dr.polygon([P(x, y) for x, y in g.exterior.coords], fill=1)

    refi = Image.new("1", (W, Hp)); dr = ImageDraw.Draw(refi)
    for g in quads:
        fillg(dr, g)
    for s in unp:
        if s.length >= 50:
            fillg(dr, s.buffer(WALL_T / 2, cap_style=2, join_style=2))
    ccols = [c for c in cols if inbox(c)]
    for c in ccols:
        fillg(dr, c)

    # 墙线取样点（真实 DXF 墙线；不含柱）——用于「墙线覆盖」。取样自 `refs`（可与模型输入分开，见上）
    pts = []
    for s in refs:
        if s.length < 50:
            continue
        n = max(1, int(s.length / 200))
        for t in np.linspace(0, 1, n + 1):
            pts.append(s.interpolate(float(t), normalized=True))

    # 模型足迹 = 同一套 wire 规则的栅格（本脚本的「建」就是实现这条规则）
    modi = Image.new("1", (W, Hp)); dm = ImageDraw.Draw(modi)
    fp = []
    for g in quads:
        fp.append(g)
    for s in unp:
        if s.length >= 50:
            fp.append(s.buffer(WALL_T / 2, cap_style=2, join_style=2))
    for c in ccols:
        fp.append(c)
    for g in fp:
        fillg(dm, g.buffer(inflate, join_style=2) if inflate else g)

    R = np.array(refi, bool); M = np.array(modi, bool)
    inter = (R & M).sum(); refA = R.sum() * CELL * CELL / 1e6; modA = M.sum() * CELL * CELL / 1e6
    ia = inter * CELL * CELL / 1e6
    fpmod = unary_union([g for g in fp if g.is_valid]) if fp else None
    cov50 = 0
    if fpmod is not None:
        cov = prep(fpmod.buffer(50))
        cov50 = sum(1 for p in pts if cov.contains(p))
    # ★ 「没量到」≠「量到 0」：该图幅一条墙线取样点都没有时（远处详图/说明图幅），
    #   覆盖率**无定义**，返回 NaN，不要返回 0.0 —— 0.0 与「墙全漏」同形，会把好件报成坏件。
    lc = float("nan") if not pts else 100.0 * cov50 / len(pts)
    return refA, modA, ia, lc, len(quads), len(unp)


def build_glb(segs_all, cols_all, cells, out):
    """把每个图纸矩形的墙挤出成立体，落成 Scene（层名 c{col}r{row}）——供人工看/后续接渲染。"""
    scene = trimesh.Scene()
    z = 0.0
    for c in cells:
        x0, x1, y0, y1 = c["bbox"]
        segs = [s for s in segs_all if (s.bounds[0] <= x1 and s.bounds[2] >= x0
                                        and s.bounds[1] <= y1 and s.bounds[3] >= y0)]
        quads, unp = wire(segs)
        polys = [g for g in quads if g.is_valid and g.area > 1e3]
        polys += [s.buffer(WALL_T / 2, cap_style=2, join_style=2) for s in unp if s.length >= 50]
        if not polys:
            continue
        u = unary_union(polys)
        geoms = u.geoms if hasattr(u, "geoms") else [u]
        meshes = []
        for g in geoms:
            if g.geom_type != "Polygon" or g.area < 1e3:
                continue
            try:
                m = trimesh.creation.extrude_polygon(g, H)
            except Exception:
                continue
            m.apply_translation([0, 0, z])
            meshes.append(m)
        if meshes:
            nm = "c%dr%d" % (c["col"], c["row"])
            scene.add_geometry(trimesh.util.concatenate(meshes), node_name=nm, geom_name=nm)
        z += H
    scene.export(out)
    return len(scene.geometry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dxf"); ap.add_argument("grid")
    ap.add_argument("--out", default=None); ap.add_argument("--margin", type=float, default=8000.0)
    a = ap.parse_args()
    G = json.load(open(a.grid, encoding="utf-8"))
    cells = G["sheets"]
    ALLW, ALLC, LABELS = load_walls_and_cols(a.dxf)
    print("墙段 %d  柱 %d  「上/下」注释 %d  图纸矩形 %d"
          % (len(ALLW), len(ALLC), len(LABELS), len(cells)))
    # ★ 剔踏步读数（照 build8:174 那句的同一份信息）：原始 → 剔 → 墙输入
    print("  ★ 剔踏步：原始 %s → 剔 %s 条（%s 组）→ 墙输入 %d ；锚 %d"
          % (TR.LAST.get("n_raw", "—"), TR.LAST.get("n_drop", "—"),
             TR.LAST.get("n_groups", "—"), len(ALLW), len(LABELS)))
    tr = tm = ti = 0.0; lcs = []
    print("%-8s %9s %9s %9s %7s %7s" % ("图幅", "ref m²", "mod m²", "交 m²", "IoU", "墙线覆盖"))
    for c in cells:
        x0, y0, x1, y1 = c["bbox"]
        r, m, i, lc, nq, nu = score_cell(ALLW, ALLC, x0, x1, y0, y1, a.margin)
        tr += r; tm += m; ti += i; lcs.append(lc)
        print("%-8s %9.1f %9.1f %9.1f %6.1f%% %8s"
              % ("c%dr%d" % (c["col"], c["row"]), r, m, i,
                 100 * i / max(r + m - i, 1e-9), "—" if lc != lc else "%.1f%%" % lc))
    valid = [x for x in lcs if x == x]      # 去掉 NaN（没量到的图幅）
    print("\n★ 全楼：参照 %.1f m²  模型 %.1f m²  交集 %.1f m²  "
          "召回 %.1f%%  精确 %.1f%%  IoU %.1f%%  墙线覆盖 min %s（有效图幅 %d/%d）"
          % (tr, tm, ti, 100 * ti / max(tr, 1e-9), 100 * ti / max(tm, 1e-9),
             100 * ti / max(tr + tm - ti, 1e-9),
             "—" if not valid else "%.1f%%" % min(valid), len(valid), len(lcs)))
    if a.out:
        n = build_glb(ALLW, ALLC, cells, a.out)
        print("→ 立体件 %s（%d 个几何）" % (a.out, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
