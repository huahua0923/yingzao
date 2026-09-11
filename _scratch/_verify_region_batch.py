# -*- coding: utf-8 -*-
"""A2 批处理发射器的差分测试：与现有 MeshBuilder 逐点/逐面比对。

判据不是「看起来一样」
----------------------
GLB 的字节由 verts/faces 的**顺序**和**浮点位模式**共同决定。所以这里比三样：
  1. 顶点数、面数相同
  2. 数组**逐位**相同（用 view(np.uint64) 比位模式，不是 == 比数值 ——
     NaN/-0.0 这类用 == 会骗人）
  3. 面下标**逐个**相同（顺序错了但集合对了，渲染会静默变样）

比「只比朝向」强的地方：顺序错、顶点插错位置、颜色错位，这里全都会暴露。

安全：只读 data/，不写任何文件。

用法
----
    python _scratch/_verify_region_batch.py c055 c019 c114 c006
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from glb_common import (MeshBuilder, _clean, _triangulate, _split_t_junctions, g2)  # noqa: E402


# ============================================================ 批处理发射器
def _cap_winding(T, y, flip_args, ny):
    """盖面三角的翻转标志，与 _face_ok 逐项同序的数组版。

    flip_args: (i0,i1,i2) —— tri_f 的实参下标顺序。顶面 (0,1,2)、底面 (0,2,1)。
    """
    px, py, pz = T[:, :, 0], np.full(T.shape[:2], y), -T[:, :, 1]
    i0, i1, i2 = flip_args
    ux, uy, uz = px[:, i1] - px[:, i0], py[:, i1] - py[:, i0], pz[:, i1] - pz[:, i0]
    wx, wy, wz = px[:, i2] - px[:, i0], py[:, i2] - py[:, i0], pz[:, i2] - pz[:, i0]
    return ((uy * wz - uz * wy) * 0.0
            + (uz * wx - ux * wz) * ny
            + (ux * wy - uy * wx) * 0.0) < 0


def _ring_block(coords, y0, y1, hole):
    """一个环的顶点(4/段)与面(2/段)。返回 (verts, faces) 或 None。

    面下标是**块内局部**下标，由调用方加基址。
    """
    pts = [(float(x), float(y)) for x, y in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    n = len(pts)
    if n < 3:
        return None

    P = np.asarray(pts, dtype=np.float64)
    j = np.arange(n)
    k = (j + 1) % n
    # 顺序累加：np.cumsum 与 Python 左到右逐位相同（已由 _verify_meshbuilder 实测）
    a2 = np.cumsum(P[:, 0] * P[k, 1] - P[k, 0] * P[:, 1])[-1]
    s = 1.0 if a2 > 0 else -1.0
    if hole:
        s = -s

    Q = P[k]
    ex, ey = Q[:, 0] - P[:, 0], Q[:, 1] - P[:, 1]
    L = np.hypot(ex, ey)
    keep = L >= 1e-9
    m = int(keep.sum())
    if m == 0:
        return None

    with np.errstate(divide="ignore", invalid="ignore"):
        nx = s * ey / L
        ny = -s * ex / L

    p, q = P[keep], Q[keep]
    # 每段 4 顶点：q0=(p,y0) q1=(q,y0) q2=(q,y1) q3=(p,y1)，x 取原值、z 取 -y
    V = np.empty((m, 4, 3), dtype=np.float64)
    V[:, 0, 0], V[:, 0, 1], V[:, 0, 2] = p[:, 0], y0, -p[:, 1]
    V[:, 1, 0], V[:, 1, 1], V[:, 1, 2] = q[:, 0], y0, -q[:, 1]
    V[:, 2, 0], V[:, 2, 1], V[:, 2, 2] = q[:, 0], y1, -q[:, 1]
    V[:, 3, 0], V[:, 3, 1], V[:, 3, 2] = p[:, 0], y1, -p[:, 1]
    V = V.reshape(-1, 3)

    # quad 的 _face_ok(q0, q1, q2, n)
    ux, uy, uz = V[0::4, 0], V[0::4, 1], V[0::4, 2]
    vx, vy, vz = V[1::4, 0], V[1::4, 1], V[1::4, 2]
    wx, wy, wz = V[2::4, 0], V[2::4, 1], V[2::4, 2]
    ux, uy, uz = vx - ux, vy - uy, vz - uz
    wx, wy, wz = wx - V[0::4, 0], wy - V[0::4, 1], wz - V[0::4, 2]
    flip = ((uy * wz - uz * wy) * nx[keep]
            + (uz * wx - ux * wz) * 0.0
            + (ux * wy - uy * wx) * (-ny[keep])) < 0

    base = np.arange(m)[:, None] * 4
    q0, q1, q2, q3 = base[:, 0], base[:, 0] + 1, base[:, 0] + 2, base[:, 0] + 3
    nf = np.where(flip[:, None],
                  np.stack([q0, q2, q1], 1),
                  np.stack([q0, q1, q2], 1))
    ns = np.where(flip[:, None],
                  np.stack([q0, q3, q2], 1),
                  np.stack([q0, q2, q3], 1))
    F = np.empty((m, 2, 3), dtype=np.int64)
    F[:, 0] = nf
    F[:, 1] = ns
    return V, F.reshape(-1, 3)


def emit_regions(items):
    """items: [(region, y0, y1, col)] -> (verts, colors, faces)，顺序与逐个 add_region 相同。"""
    Vb, Cb, Fb = [], [], []
    nv = nf = 0

    for region, y0, y1, col in items:
        if region is None or region.is_empty:
            continue
        polys = region.geoms if region.geom_type == "MultiPolygon" else (region,)
        for poly in polys:
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            for g in _clean(poly):
                tris = _triangulate(g)
                if g.interiors:
                    tris = _split_t_junctions(tris)

                if tris:
                    T = np.asarray(tris, dtype=np.float64)
                    k = len(T)
                    # 顶点：每三角 6 个，顺序 top(3) 后 bot(3)
                    V = np.empty((2 * k, 3, 3), dtype=np.float64)
                    V[0::2, :, 0], V[0::2, :, 1], V[0::2, :, 2] = T[:, :, 0], y1, -T[:, :, 1]
                    V[1::2, :, 0], V[1::2, :, 1], V[1::2, :, 2] = T[:, :, 0], y0, -T[:, :, 1]
                    V = V.reshape(-1, 3)

                    idx = np.arange(k)[:, None] * 6
                    ti = np.concatenate([idx + 0, idx + 1, idx + 2], 1)
                    bi = np.concatenate([idx + 3, idx + 4, idx + 5], 1)
                    ft = _cap_winding(T, y1, (0, 1, 2), 1.0)
                    fb = _cap_winding(T, y0, (0, 2, 1), -1.0)
                    tf = np.where(ft[:, None], ti[:, [0, 2, 1]], ti)
                    # tri_f(b0, b2, b1) 默认 -> [b0,b2,b1]；翻转 -> [b0,b1,b2]
                    bf = np.where(fb[:, None], bi[:, [0, 1, 2]], bi[:, [0, 2, 1]])

                    F = np.empty((2 * k, 3), dtype=np.int64)
                    F[0::2] = tf
                    F[1::2] = bf
                    F = F.reshape(-1, 3)

                    Vb.append(V); Fb.append(F + nv)
                    Cb.append(np.tile(np.asarray(col, dtype=np.uint8), (len(V), 1)))
                    nv += len(V); nf += len(F)

                for hole_flag, ring in ([(False, g.exterior)]
                                        + [(True, h) for h in g.interiors]):
                    r = _ring_block(ring.coords, y0, y1, hole_flag)
                    if r is None:
                        continue
                    V, F = r
                    Vb.append(V); Fb.append(F + nv)
                    Cb.append(np.tile(np.asarray(col, dtype=np.uint8), (len(V), 1)))
                    nv += len(V); nf += len(F)

    if not Vb:
        return (np.zeros((0, 3)), np.zeros((0, 3), np.uint8), np.zeros((0, 3), np.int64))
    return np.concatenate(Vb), np.concatenate(Cb), np.concatenate(Fb)


# ============================================================ 差分
def emit_scalar(items):
    """走**现有** MeshBuilder，逐项 add_region —— 真值。"""
    b = MeshBuilder()
    for region, y0, y1, col in items:
        b.add_region(region, y0, y1, col)
    return (np.asarray(b.verts, dtype=np.float64),
            np.asarray(b.colors, dtype=np.uint8),
            np.asarray(b.faces, dtype=np.int64))


def bits(a):
    return a.view(np.uint64) if a.dtype == np.float64 else a


def check(name, floors=(0, 1, 3)):
    import json
    from shapely.geometry import Polygon

    d = os.path.join(ROOT, "data", "buildings", name, "floors")
    if not os.path.isdir(d):
        print("[%s] 无 floors，跳过" % name)
        return None

    items = []
    for F in floors:
        fp = os.path.join(d, "floor%d.json" % F)
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8") as f:
            floor = json.load(f)
        for w in floor.get("walls", []):
            try:
                poly = Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4])
            except Exception:
                continue
            if poly.is_empty or poly.area <= 0:
                continue
            col = (154, 162, 176) if w.get("type") == "outer" else (128, 132, 142)
            # 三个高度段，模拟 build_walls 的下墙裙 / 窗带 / 上过梁
            items.append((poly, 0.30, 1.20, col))
            items.append((poly, 1.20, 3.00, col))
            items.append((poly, 3.00, 4.20, col))
        # 楼板：带洞路径（走 _split_t_junctions）
        outline = floor.get("outline")
        if outline:
            try:
                slab = Polygon(outline)
                sw = floor.get("stairwells") or []
                if sw and floor.get("floor", 0) > 0:
                    from shapely.geometry import box
                    for s in sw:
                        slab = slab.difference(box(s["x0"], s["yBot"], s["x1"], s["yTop"]))
                items.append((slab, 0.0, 0.15, (236, 230, 220)))
            except Exception:
                pass

    if not items:
        print("[%s] 没凑出几何" % name)
        return None

    vs, cs, fs = emit_scalar(items)
    vn, cn, fn = emit_regions(items)

    ok = True
    if vs.shape != vn.shape:
        print("  ✗ 顶点数 %s vs %s" % (vs.shape, vn.shape)); ok = False
    elif not np.array_equal(bits(vs), bits(vn)):
        bad = int((bits(vs) != bits(vn)).any(1).sum())
        print("  ✗ 顶点位模式不符 %d/%d" % (bad, len(vs))); ok = False
    if fs.shape != fn.shape:
        print("  ✗ 面数 %s vs %s" % (fs.shape, fn.shape)); ok = False
    elif not np.array_equal(fs, fn):
        bad = int((fs != fn).any(1).sum())
        print("  ✗ 面下标不符 %d/%d" % (bad, len(fs))); ok = False
    if cs.shape != cn.shape or not np.array_equal(cs, cn):
        print("  ✗ 顶点色不符"); ok = False

    print("[%-5s] %7d 顶点 / %7d 面  %s"
          % (name, len(vn), len(fn), "✓ 逐位一致" if ok else "✗ 有差异"))
    return (ok, len(vn), len(fn))


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["c055", "c019", "c114", "c006"]
    print("批处理发射器 vs 现有 MeshBuilder（逐位差分）\n" + "=" * 64)
    bad = 0
    tv = tf = 0
    for n in names:
        r = check(n)
        if r:
            tv += r[1]; tf += r[2]
            bad += 0 if r[0] else 1
    print("=" * 64)
    if tv == 0:
        print("✗ 空转：一个顶点都没比到，本测试无效。")
        return 2
    if bad:
        print("✗ %d 栋有差异 —— 批处理发射器与现有实现不等价。" % bad)
        return 1
    print("✓ 共 %d 顶点 / %d 面，逐位、逐序一致。" % (tv, tf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
