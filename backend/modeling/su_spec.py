# -*- coding: utf-8 -*-
"""GLB 管道 → SU 建体语汇(spec)：**同一个 main()，只换输出端**。

为什么要这么做，而不是另写一份 SU 建模：SU 里的楼必须和交付的 GLB 逐构件同源。
`build_standard_glb.main()` 里的楼层循环、三段墙、窗凹口挂靠判据、女儿墙内缩、
屋面标高……每一条都是踩过坑才定下来的（凹口按几何挂墙不认 wallId、女儿墙向内
不外挑、面侧配色要带 gap 二级判据）。重写一份 = 把这些坑再踩一遍。

做法：`SuRecorder` 继承 `MeshBuilder`，只覆盖 4 个几何入口 ——
  add_region / add_slab / add_prism / add_box
add_glass、add_frame、add_parapet 内部调的就是这 4 个，不用管。
于是把 `build_standard_glb.MeshBuilder` 换成 SuRecorder 再调 `main()`，
出来的就不是 GLB，而是「一串待挤出的多边形 + 每张侧面的颜色」。

坐标：`g2(bx, by) = (bx, -by)`，所以 SU 平面坐标 = shapely 平面坐标（无需换算），
高度直接就是 y0/y1（米）。`add_box` 是唯一要转的（它按 GLB 的世界轴给参数）。

用法: python backend/modeling/su_spec.py ny27 [-o 输出.json]
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
for p in (BACKEND, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shapely.geometry import Polygon                           # noqa: E402
from glb_common import MeshBuilder, _clean                      # noqa: E402
import build_standard_glb as G                                  # noqa: E402


def dedupe(coords):
    """去掉首尾重复点 + 连续重复点。

    必须跟 `_extrude_ring` 的取边顺序一致：它只跳过零长边，而零长边只来自
    连续重复点。这里先把重复点去掉，那么「我记的边」与「SU 会生成的侧壁」
    就一一对应，逐边上色才落得准。
    """
    pts = [(float(x), float(y)) for x, y in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    out = []
    for p in pts:
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def shoelace(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def hexc(c):
    return "#%02x%02x%02x" % (c[0], c[1], c[2]) if isinstance(c, (list, tuple)) else str(c)


class _Shim:
    """冒充 export_glb 的返回值（main() 会读 .bounds）。"""

    def __init__(self, lo, hi):
        self.bounds = (lo, hi)


class SuRecorder(MeshBuilder):
    """把 MeshBuilder 的几何入口换成「记一个待挤出的多边形」。"""

    last = None

    def __init__(self):
        super().__init__()          # build_standard_glb 收尾会读 b.faces/b.verts（GLB 口径，本路为空）
        self.parts = []
        self.out = None
        self.dropped = 0            # 绕过 4 个几何入口、直接吐三角/四边形的调用
        SuRecorder.last = self

    # 防「悄悄漏几何」：上面 4 个入口都覆盖了，add_region/add_slab/add_prism/add_box
    # 不可能走到 quad/tri_f；真走到了就只可能是 build_gable_roof 那条路（坡屋顶）。
    # 平顶楼这个数必须是 0，否则 SU 里的屋顶会缺一块而没人吭声。
    def quad(self, a, b, c, d, n, col):
        self.dropped += 1

    def tri_f(self, a, b, c, n, col):
        self.dropped += 1

    # ---- 内部 ----
    @staticmethod
    def _edges(pts, col, col_fn, hole):
        """按 `_extrude_ring` 逐字复刻的法向算法，逐边求颜色与法向。

        朝向由环的**有向面积**定（凹多边形的阴角处按质心法会翻面）；
        洞环要取反 —— 这两条都是 _extrude_ring 里踩过的坑，照抄不商量。

        法向为什么要一起带出来：SU 的面是**双面**的，材质贴在「面的某一侧」。
        GLB 那边这张侧壁只有一个颜色，那是**沿外法向**探出来的朝向色；到了 SU
        要把它贴到法向所指的那一侧，另一侧贴配对色 —— 这才等价于交付件里
        「这张面朝外是立面、朝内是室内」。
        """
        n = len(pts)
        if n < 3:
            return [], []
        a2 = 0.0
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            a2 += ax * by - bx * ay
        s = 1.0 if a2 > 0 else -1.0
        if hole:
            s = -s
        cols, norms = [], []
        for i in range(n):
            lx0, ly0 = pts[i]
            lx1, ly1 = pts[(i + 1) % n]
            ex, ey = lx1 - lx0, ly1 - ly0
            L = math.hypot(ex, ey)
            if L < 1e-9:
                continue
            nx, ny = s * ey / L, s * -ex / L
            cols.append(hexc(col_fn(lx0, ly0, lx1, ly1, nx, ny) if col_fn is not None else col))
            norms.append([round(nx, 5), round(ny, 5)])
        return cols, norms

    def _add(self, region, z0, z1, cap, col_side=None, kind="wall"):
        if region is None or getattr(region, "is_empty", True):
            return
        polys = region.geoms if region.geom_type == "MultiPolygon" else (region,)
        for poly in polys:
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            for g in _clean(poly):
                ext = dedupe(g.exterior.coords)
                if len(ext) < 3:
                    continue
                holes = [h for h in (dedupe(i.coords) for i in g.interiors) if len(h) >= 3]
                area = shoelace(ext) - sum(shoelace(h) for h in holes)
                # 逐边色只在 col_side 给了的时候才有意义。别在「整件单色」的部件上
                # 也硬塞一套色 + 法向：那样 SU 侧会拿配对色去贴单色构件的背面
                # （比如盖面恰好等于立面色的构件，背面会被贴成室内色）。
                if col_side is not None:
                    cols, norms = self._edges(ext, cap, col_side, False)
                    hcols, hnorms = [], []
                    for h in holes:
                        c, nn = self._edges(h, cap, col_side, True)
                        hcols.append(c)
                        hnorms.append(nn)
                else:
                    cols, norms, hcols, hnorms = [], [], [], []
                self.parts.append({
                    "kind": kind, "z0": round(z0, 5), "z1": round(z1, 5),
                    "ext": [[round(x, 5), round(y, 5)] for x, y in ext],
                    "holes": [[[round(x, 5), round(y, 5)] for x, y in h] for h in holes],
                    # 逐边色 + 逐边法向（同序）；整件单色时两者都是空的
                    "edgeCols": cols, "edgeN": norms,
                    "holeEdgeCols": hcols, "holeEdgeN": hnorms,
                    "cap": hexc(cap),
                    "vol": round(area * (z1 - z0), 6),
                    "nf": 2 + len(ext) + sum(len(h) for h in holes),
                })

    # ---- 覆盖 MeshBuilder 的 4 个几何入口 ----
    def add_region(self, region, y0, y1, col, col_side=None):
        self._add(region, y0, y1, col, col_side=col_side)

    def add_slab(self, poly, y0, th, col=None):
        self._add(poly, y0, y0 + th, G.C_SLAB if col is None else col, kind="slab")

    def add_prism(self, A, B, C, y0, y1, col):
        self._add(Polygon([(A[0], -A[1]), (B[0], -B[1]), (C[0], -C[1])]),
                  y0, y1, col, kind="prism")

    def add_box(self, cx, cy, cz, w, h, d, rot_y=0.0, col=None):
        """GLB 的盒 → SU 的挤出体。GLB 是 y 上；平面 y = -z_glb，故要翻一道。"""
        hw, hh, hd = w / 2.0, h / 2.0, d / 2.0
        cr, sr = math.cos(rot_y), math.sin(rot_y)

        def P(x, z):
            return (cx + x * cr + z * sr, -cz + x * sr - z * cr)

        ring = [P(-hw, -hd), P(hw, -hd), P(hw, hd), P(-hw, hd)]
        self._add(Polygon(ring), cy - hh, cy + hh, G.C_WALL if col is None else col, kind="box")

    # ---- 输出端：main() 会调它 ----
    def export_glb(self, path):
        parts = self.parts
        # 面侧配对色：墙的侧面在 GLB 里只有「朝外那一侧」的一个颜色，SU 的面是双面的，
        # 另一侧要贴配对色（朝外=立面 / 朝内=室内）。用与 main() 同一处 style 取色。
        S = G.load_spec() or {}
        st = S.get("style") or {}
        pair = [hexc(G.hex_to_rgb(st.get(k))) for k in ("facade", "inner")]
        spec = {
            "name": os.path.basename(path).replace(".su.json", "").replace(".json", ""),
            "src": G.DATA,
            "parts": parts,
            "meta": {
                "parts": len(parts),
                "vol": round(sum(p["vol"] for p in parts), 4),
                "nf": sum(p["nf"] for p in parts),
                "pair": pair,
                # 分层投递用：按 z0/floor_h 四舍五入分带（浮点除法直接整除分错层）
                "floor_h": S.get("floor_h", 4.2),
                "kinds": {k: sum(1 for p in parts if p["kind"] == k)
                          for k in sorted({p["kind"] for p in parts})},
            },
        }
        self.out = path
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        os.replace(tmp, path)
        # 给 main() 一个能读 .bounds 的替身
        xs = [p[0] for prt in parts for p in prt["ext"]]
        ys = [p[1] for prt in parts for p in prt["ext"]]
        zs = [prt[k] for prt in parts for k in ("z0", "z1")]
        if not parts:
            return _Shim((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        return _Shim((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default="ny27")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    G.DATA = os.path.join(ROOT, "data", "buildings", a.name)
    G.OUT = a.out or os.path.join(ROOT, "_scratch", "su_jobs", "_%s_su.json" % a.name)
    G.MeshBuilder = SuRecorder          # ★ 只换输出端，main() 里的建模逻辑一行不动
    try:
        G.main()
    finally:
        G.MeshBuilder = MeshBuilder
    b = SuRecorder.last
    parts = b.parts if b else []
    # 上面那行「三角形=0」是 GLB 口径的统计 —— 本路不建三角网，几何在这 4 个入口就被
    # 记成多边形了。真实规模看下面这行。
    print("[su] 部件 %d 个  预期体积 %.3f m³  预期面数 %d  漏记三角面 %d  面侧配对 %s" %
          (len(parts), sum(p["vol"] for p in parts), sum(p["nf"] for p in parts),
           b.dropped if b else -1, (G.load_spec() or {}).get("style", {}).get("facade")))
    print("→", G.OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
