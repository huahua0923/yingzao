# -*- coding: utf-8 -*-
"""数组版绕序判定 vs 标量 _face_ok：在**真实楼层几何**上逐面比对。

为什么必须在真数据上比
----------------------
判定式是我推导出来的。推导再漂亮也只是纸上的：真实 DXF 里全是凹多边形、
带洞、共线点、1e-9 级细长碎片 —— 正是符号最容易翻车的地方。所以判据不是
「公式看起来对」，而是「拿 c055 首层的每一片墙、每一个环，逐面跑两遍，
布尔值全等」。

保底：本脚本**只读**，不写任何产物，也不 import 会被改的 MeshBuilder 发射路径
（只借 _face_ok 这个纯函数当真值）。

三层比对
--------
  1. 盖面三角朝向   数组版 vs 标量 _face_ok            —— 必须全等
  2. 侧壁四联朝向   数组版 vs 标量 _face_ok            —— 必须全等
  3. 化简式交叉验证 侧壁 cross·n 是否等于 Δy·s·L        —— 只报不符数，作旁证

用法
----
    python _scratch/_verify_meshbuilder.py c055 c019 c114 c006
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from glb_common import _clean, _triangulate, _split_t_junctions, _face_ok, g2  # noqa: E402


# ---------------------------------------------------------------- 数组版判定
def cap_winding_vec(tris, y0, y1, up=True):
    """盖面三角的翻转标志，数组版。等价于逐面 _face_ok(..., [0,±1,0])。

    顶点排布照抄 add_region：
        顶面  v(ax, y1, -ay) v(bx, y1, -by) v(cx, y1, -cy)   n=[0, 1, 0]
        底面  v(ax, y0, -ay) v(bx, y0, -by) v(cx, y0, -cy)   n=[0,-1,0]
              但 tri_f 的实参顺序是 (bot0, bot2, bot1)
    """
    T = np.asarray(tris, dtype=np.float64)          # (n,3,2)
    if T.size == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)

    y = y1 if up else y0
    px, py, pz = T[:, :, 0], np.full(T.shape[:2], y), -T[:, :, 1]

    if up:
        i0, i1, i2 = 0, 1, 2                        # tri_f(t0, t1, t2, [0,1,0])
        ny = 1.0
    else:
        i0, i1, i2 = 0, 2, 1                        # tri_f(b0, b2, b1, [0,-1,0])
        ny = -1.0

    ux = px[:, i1] - px[:, i0]
    uy = py[:, i1] - py[:, i0]
    uz = pz[:, i1] - pz[:, i0]
    wx = px[:, i2] - px[:, i0]
    wy = py[:, i2] - py[:, i0]
    wz = pz[:, i2] - pz[:, i0]

    # 与 _face_ok 逐项同序：n = [0, ny, 0]，所以只有中间一项非零。
    # 仍写全三项，是为了和标量式字面对应，不靠「反正另外两项是 0」省事。
    val = ((uy * wz - uz * wy) * 0.0
           + (uz * wx - ux * wz) * ny
           + (ux * wy - uy * wx) * 0.0)
    return val < 0


def cap_winding_scalar(tris, y0, y1, up=True):
    """标量真值：逐面调 _face_ok，顶点构造与 add_region 完全一致。"""
    out = []
    y = y1 if up else y0
    for (ax, ay), (bx, by), (cx, cy) in tris:
        A, B, C = g2(ax, ay), g2(bx, by), g2(cx, cy)
        top = [(p[0], y, p[1]) for p in (A, B, C)]
        if up:
            out.append(_face_ok(top[0], top[1], top[2], [0, 1, 0]))
        else:
            out.append(_face_ok(top[0], top[2], top[1], [0, -1, 0]))
    return np.asarray(out, dtype=bool)


def ring_winding_vec(pts, y0, y1, s, skip):
    """侧壁四联的翻转标志，数组版。等价于逐段 quad(...) 里的 _face_ok。

    q0=(p0x, y0, -p0y) q1=(p1x, y0, -p1y) q2=(p1x, y1, -p1y)，n=[nx, 0, -ny]。
    """
    p = pts
    q = np.roll(p, -1, axis=0)
    ex, ey = q[:, 0] - p[:, 0], q[:, 1] - p[:, 1]
    L = np.hypot(ex, ey)
    with np.errstate(divide="ignore", invalid="ignore"):
        nx = s * ey / L
        ny = -s * ex / L

    qx0, qy0, qz0 = p[:, 0], np.full(len(p), y0), -p[:, 1]
    qx1, qy1, qz1 = q[:, 0], np.full(len(p), y0), -q[:, 1]
    qx2, qy2, qz2 = q[:, 0], np.full(len(p), y1), -q[:, 1]

    ux, uy, uz = qx1 - qx0, qy1 - qy0, qz1 - qz0
    wx, wy, wz = qx2 - qx0, qy2 - qy0, qz2 - qz0

    val = ((uy * wz - uz * wy) * nx
           + (uz * wx - ux * wz) * 0.0
           + (ux * wy - uy * wx) * (-ny))
    flip = val < 0
    flip[skip] = False                              # 跳过的段不发面，标志无意义
    return flip, L


def ring_winding_scalar(pts, y0, y1, s, L, skip):
    """标量真值：逐段调 _face_ok。"""
    n = len(pts)
    out = []
    for i in range(n):
        if skip[i]:
            out.append(False)
            continue
        ex, ey = pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1]
        nx, ny = s * ey / L[i], s * -ex / L[i]
        p0, p1 = g2(pts[i][0], pts[i][1]), g2(pts[(i + 1) % n][0], pts[(i + 1) % n][1])
        q = [(p0[0], y0, p0[1]), (p1[0], y0, p1[1]),
             (p1[0], y1, p1[1]), (p0[0], y1, p0[1])]
        out.append(_face_ok(q[0], q[1], q[2], [nx, 0, -ny]))
    return np.asarray(out, dtype=bool)


def prep_ring(coords):
    """照抄 _extrude_ring 的开头：去重复尾点、算有向面积、定 s。"""
    pts = [(float(x), float(y)) for x, y in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return None
    a2 = 0.0
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        a2 += ax * by - bx * ay
    s = 1.0 if a2 > 0 else -1.0
    P = np.asarray(pts, dtype=np.float64)
    # 顺序累加 vs np.cumsum：验证 cumsum 与 Python 左到右求和逐位相同
    j = np.arange(len(pts))
    k = (j + 1) % len(pts)
    a2_np = np.cumsum(P[:, 0] * P[k, 1] - P[k, 0] * P[:, 1])[-1]
    return P, s, a2, a2_np


# ---------------------------------------------------------------- 跑
def check_building(name, floors=(0, 1, 5, 9)):
    import json
    d = os.path.join(ROOT, "data", "buildings", name, "floors")
    if not os.path.isdir(d):
        print("[%s] 无 floors 目录，跳过" % name)
        return None

    n_cap = n_ring = 0
    bad_cap = bad_ring = bad_simpl = 0
    bad_a2 = 0
    y0, y1 = 0.0, 4.2

    for F in floors:
        fp = os.path.join(d, "floor%d.json" % F)
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8") as f:
            floor = json.load(f)

        for w in floor.get("walls", []):
            from shapely.geometry import Polygon
            try:
                poly = Polygon(w["poly"], [h for h in (w.get("holes") or []) if len(h) >= 4])
            except Exception:
                continue
            if poly.is_empty or poly.area <= 0:
                continue
            for g in _clean(poly):
                tris = _triangulate(g)
                if g.interiors:
                    tris = _split_t_junctions(tris)
                if not tris:
                    continue

                for up in (True, False):
                    v = cap_winding_vec(tris, y0, y1, up)
                    s_ = cap_winding_scalar(tris, y0, y1, up)
                    n_cap += len(v)
                    bad_cap += int((v != s_).sum())

                for is_hole, ring in [(False, g.exterior)] + [(True, h) for h in g.interiors]:
                    r = prep_ring(ring.coords)
                    if r is None:
                        continue
                    P, s, a2, a2_np = r
                    if a2 != a2_np:
                        bad_a2 += 1
                    s = -s if is_hole else s
                    n = len(P)
                    q = np.roll(P, -1, axis=0)
                    ex, ey = q[:, 0] - P[:, 0], q[:, 1] - P[:, 1]
                    L = np.hypot(ex, ey)
                    skip = L < 1e-9
                    v, _ = ring_winding_vec(P, y0, y1, s, skip)
                    sc = ring_winding_scalar(P, y0, y1, s, L, skip)
                    n_ring += int((~skip).sum())
                    bad_ring += int((v != sc).sum())
                    # 旁证：推导出的化简式说 cross·n = Δy·s·L，故翻转标志应恒等于
                    # 「Δy·s < 0」，与环的形状/长度无关。这不是生产路径，只是第三只眼
                    # —— 若它与前两者不符，说明我的推导有问题，即使碰巧通过也要查。
                    if (~skip).any():
                        simpl = np.zeros(len(v), dtype=bool)
                        simpl[~skip] = (y1 - y0) * s < 0
                        bad_simpl += int((simpl != sc).sum())

    print("[%-5s] 盖面 %7d 面 不符 %d | 侧壁 %7d 段 不符 %d | 化简式旁证不符 %d | "
          "a2 顺序累加不符 %d"
          % (name, n_cap, bad_cap, n_ring, bad_ring, bad_simpl, bad_a2))
    return bad_cap, bad_ring, bad_a2 + bad_simpl, n_cap, n_ring


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["c055", "c019", "c114", "c006"]
    print("数组版 vs 标量 _face_ok（真几何逐面比对）\n" + "=" * 72)
    tot_bad = tot_cap = tot_ring = 0
    for n in names:
        r = check_building(n)
        if r:
            tot_bad += r[0] + r[1] + r[2]
            tot_cap += r[3]
            tot_ring += r[4]
    print("=" * 72)
    # 空转必须判失败。第一版把楼层路径写错，一片几何都没读到却打出「全部一致」
    # —— 一个永远会通过的测试比没有测试更糟，因为它给的是假信心。
    if tot_cap == 0 or tot_ring == 0:
        print("✗ 空转：盖面 %d 面 / 侧壁 %d 段 —— 根本没读到几何，本测试无效。"
              % (tot_cap, tot_ring))
        return 2
    if tot_bad:
        print("✗ 共 %d 处不符 —— 数组版判定式与标量不等价，不许上生产。" % tot_bad)
        return 1
    print("✓ 共 %d 个盖面 / %d 段侧壁，逐面一致。" % (tot_cap, tot_ring))
    return 0


if __name__ == "__main__":
    sys.exit(main())
