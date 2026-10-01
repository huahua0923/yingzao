# -*- coding: utf-8 -*-
"""GLB 网格构建纯工具：从 build_lihua_full.py 抽出，不读 DXF、不读文件（除 export）。

build_standard_glb.py 消费标准 floor JSON，这里只提供「多边形/盒子 → 三角形」的
纯函数，与查看器 building.html 同源，消除两路渲染的几何漂移。
"""
import math
import os

import mapbox_earcut as _earcut
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

# 批处理发射开关（轨道 B2，2026-09-13）。置 1 走 `_flush()` 攒起来整块发射。
#
# ★ 默认是 **关**（0），因为它实测是**净慢**的。别照着"批处理一定更快"的直觉把它打开：
#   全库 49 栋逐字节相同的闸门过了（`_b_gate_out/b2_off` vs `b2_on`：49/49 相同，
#   关的那次 `flush_emitted` 全 0、开的那次 20297 次），但隔离计时 6 栋
#   （c009/c017/c019/c046/c054/c055）合计 141.7s → 146.0s，**慢 3.1%**。
#   原因（c017 profile，16.3s）：`_flush`+`_ring_block`+`_cap_flip` 自身的数组开销
#   ≈3.0s，而它要省的标量发射（`v` 1.29s + `quad` 0.32s + `list.append` 0.6s）≈2.2s
#   —— 省的不够付机器的。真正的大头是 `wall_side_color.pick` 那段**逐段 shapely 探针**
#   （cum 6.36s = 39%），批处理碰不到它。
#   要让它转正，得先做 B1（verts/faces 数组化）把结尾那两次 `.tolist()`+`extend`
#   （0.435s+）消掉，再用同一把量具复测 —— 在那之前它就是一个**留着的回退口**，
#   不是默认路。判据永远是产物字节，开关只是把两条路并排比。
MESH_BATCH = os.environ.get("GYM3D_MESH_BATCH", "0") != "0"

# 按面配色的**批调 + 记忆**开关（2026-09-13）。默认开。
#
# 置 0 = `_extrude_ring`/`_ring_block` 逐字回到「逐段取色、边取边发」的老路 ——
# 这不是"另一种等价写法"，是老代码本身，所以它既是回退口又是 A/B 的基准
# （`_scratch/_sidecolor_ab.py` 就靠它做交错对照）。
#
# ★ 两条路产物**逐字节相同**，判据是 `_b_gate.py`，不是"没抛异常"：
#   已验 serial49（改前代码）== 批调 == 逐点，5 栋 sha256 与字节数全同。
SIDECOLOR_BATCH = os.environ.get("GYM3D_SIDECOLOR", "1") != "0"

# 材质色（与 building.html 同源）
C_WALL = [128, 132, 142]
C_SLAB = [236, 230, 220]
C_GLASS = [120, 156, 184]
C_FRAME = [194, 199, 206]
C_ROOF = [62, 66, 74]
C_STAIR = [208, 193, 152]
C_DOOR = [196, 150, 92]
C_COLUMN = [154, 162, 176]


def g2(bx, by):
    """DXF 本地 (x, y) → 世界 (x, -y)（y 轴翻转到 z）。"""
    return (bx, -by)


def _triangulate(poly):
    """对 shapely 多边形（可带洞 / MultiPolygon）做 ear-clip 三角化。

    返回 [(a, b, c), ...]，每个点是本地 (x, y) 元组。注意：shapely.ops.triangulate
    是对「顶点集」做 Delaunay 三角化（覆盖凸包），会填平凹形与洞——外墙带是 U 形、
    门洞是挖穿的 gap，用它会把门洞/中庭填成实墙。这里用 mapbox_earcut（真·带洞凹
    多边形三角化），保证三角形严格落在多边形内部、不填门洞。
    """
    if poly is None or poly.is_empty:
        return []
    if poly.geom_type == "MultiPolygon":
        out = []
        for g in poly.geoms:
            out.extend(_triangulate(g))
        return out
    if poly.geom_type != "Polygon":
        return []
    pts = []
    rings = []

    def _ring(coords):
        pts.extend((float(x), float(y)) for x, y in coords[:-1])
        rings.append(len(pts))

    _ring(poly.exterior.coords)
    for h in poly.interiors:
        _ring(h.coords)
    if not pts:
        return []
    verts = np.asarray(pts, dtype=np.float64)
    ring_idx = np.asarray(rings, dtype=np.int32)
    idx = _earcut.triangulate_float64(verts, ring_idx)
    out = []
    for i in range(0, len(idx), 3):
        a, b, c = int(idx[i]), int(idx[i + 1]), int(idx[i + 2])
        out.append(((pts[a][0], pts[a][1]), (pts[b][0], pts[b][1]), (pts[c][0], pts[c][1])))
    return out


def _clean(poly):
    """把多边形拆成若干「无重复/共线顶点」的 Polygon，**一块都不丢、形状不变**。

    为什么非做不可：盖面走 earcut 三角化、侧壁走 `_extrude_ring` 沿环拉，
    这两条路径必须**逐边吻合**，网格才闭合。而 earcut 会丢掉共线点，环却
    原样带着它 —— 那条边就只有侧壁用一次，成了开口。实测 c018 两个楼层
    6 万条环边里有 13 条对不上，simplify(0) 之后降到 0。
    容差 0 的 Douglas-Peucker 只删「恰好共线」的点，几何分毫不差。

    返回列表：simplify 理论上可能把自交多边形拆成 MultiPolygon，这里原样
    展开返回，绝不取最大块（那会静默吞掉几何）。
    """
    if poly is None or poly.is_empty:
        return []
    if not poly.is_valid:
        # 自交/自切多边形 earcut 铺不出盖面 → 盖面为空、侧壁却照拉一圈，
        # 一圈边全成了开口。buffer(0) 是 GEOS 的标准自愈操作。
        poly = poly.buffer(0)
        if poly.is_empty:
            return []
    s = poly.simplify(0, preserve_topology=True)
    if s.is_empty:
        s = poly
    if s.geom_type == "MultiPolygon":
        return [g for g in s.geoms if not g.is_empty]
    return [s] if s.geom_type == "Polygon" else []


def _split_t_junctions(tris):
    """消除 T 形接点：某个三角形的顶点落在另一个三角形边的**内部**时，
    把那条边在该点劈开，让两侧三角形的边逐段吻合。

    为什么非做不可：盖面走 earcut，侧壁走环。earcut 遇到**两个洞的边共线**
    时（c114 两口楼梯井的 yBot 相同、c006 两翼的井同一排）会把「洞底边 +
    中间实体 + 另一个洞底边」整条合并成一条长边。区域面积是对的，但边被
    拆成了「2→8」这一条，而环上是「2→4」「6→8」两条 —— 于是两条洞底边只有
    侧壁用到、长边只有盖面用到，一正一反共 4 条开口。实测 c114 每层 8 条、
    c006 共 56 条、c103 共 90 条，全都只出现在楼梯井层。

    做法：反复扫描，每次把「边上有内部顶点」的三角形从对顶点做扇形劈开。
    绕序不变（仍是 A,v1,v2,…,C 的顺序），面积与体积分毫不差。

    ⚠️ **只在带洞的多边形上调用**。理由有两条，缺一不可：
      · 正确性：合并只发生在**两个环之间**。同一个环内 `_clean` 已把共线点
        清干净，不可能再出现「顶点落在非相邻边上」（那本身就是自交，会被
        buffer(0) 修掉）。所以单环多边形的盖面边界天然就是环本身，无需处理。
      · 性能：本函数是 O(边数×顶点数)，每次 add_region 都跑一遍会拖垮全流程
        —— 实测 c114 从 2.9 s 涨到 13 分钟还没出结果。墙/房间/女儿墙绝大多数
        是单环（门是开在**外环**上的缺口，不是内环），跳过它们就没事了。
    """
    for _ in range(16):
        vset = set()
        for t in tris:
            vset.update(t)
        # 无向边 → 该边上位于内部的顶点（按参数排序）
        emap = {}
        for t in tris:
            for k in range(3):
                e = tuple(sorted((t[k], t[(k + 1) % 3])))
                emap.setdefault(e, None)
        cuts = {}
        for (P, Q) in emap:
            dx, dy = Q[0] - P[0], Q[1] - P[1]
            L2 = dx * dx + dy * dy
            if L2 < 1e-18:
                continue
            inside = []
            for V in vset:
                if V == P or V == Q:
                    continue
                tt = ((V[0] - P[0]) * dx + (V[1] - P[1]) * dy) / L2
                if tt <= 1e-9 or tt >= 1 - 1e-9:
                    continue
                if (V[0] - (P[0] + tt * dx)) ** 2 + \
                        (V[1] - (P[1] + tt * dy)) ** 2 > 1e-14:
                    continue
                inside.append((tt, V))
            if inside:
                inside.sort()
                cuts[(P, Q)] = [v for _, v in inside]
        if not cuts:
            return tris
        out = []
        for t in tris:
            hit = None
            for k in range(3):
                P, Q, opp = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
                pts = cuts.get(tuple(sorted((P, Q))))
                if pts:
                    seq = list(pts)
                    if (P, Q) != tuple(sorted((P, Q))):
                        seq.reverse()          # 让插入点按 P→Q 排
                    hit = (P, Q, opp, seq)
                    break
            if hit is None:
                out.append(t)
                continue
            P, Q, opp, seq = hit
            prev = P
            for v in seq:                      # 对顶点扇形劈开，绕序不变
                out.append((prev, v, opp))
                prev = v
            out.append((prev, Q, opp))
        tris = out
    return tris


def _side_colors(col_fn, A, n):
    """侧壁颜色：`col_fn` 有 `.batch()` 就**整环批调**，否则逐段调。

    A 是 (n,6) float64 的 `(lx0, ly0, lx1, ly1, nx, ny)`；返回值恒为「n 个 3 元整数
    列表」——两条路**同型**，`self.colors` 里不会混进 numpy 行（`export_glb` 走
    `np.asarray(self.colors, dtype=float)`，混型是自找麻烦）。

    为什么批调（2026-09-13）：`build_standard_glb._FaceSideColor` 的逐点版本占单栋
    建楼 41.6%，而其中一半是 `Point` 构造 + shapely 装饰器派发的**逐次调用固定开销**。
    批调把固定开销按环摊掉，实测 19~28×（三个楼逐点比对颜色全等）。
    ★ 实参顺序 (lx0,ly0,lx1,ly1,nx,ny) 是与 `.batch()` 的接口契约 ——
      `_extrude_ring` 与 `_ring_block` **必须一致**，改一处必须改另一处。
    """
    batch = getattr(col_fn, "batch", None)
    if batch is None:
        return [col_fn(*row.tolist()) for row in A]
    return batch(A).tolist()


def _face_ok(p0, p1, p2, n):
    """面朝向测试：cross(p1-p0, p2-p0)·n < 0 时说明绕序反了，要交换两个顶点。

    这里手写 float64 而不用 np.cross / np.dot，是因为 **np.cross 是纯 Python 包装**，
    内部要走 normalize_axis_tuple + moveaxis + broadcast_to。对 3 元素这种小数组，
    一次调用的固定开销实测 ~432µs（同一台机器上正常应是 ~5µs），比算术本身贵两个
    数量级。GLB 构建是逐面调用的，实测**整个建模流程 17.6 倍的时间**都花在这个包装上
    （16 万面：258.7s → 14.7s）。

    展开后是同一套 IEEE754 双精度乘减，求和顺序与 np.dot 一致（左到右），
    所以结果逐位相同、输出 GLB 字节不变（已用 c019 对交付件做过逐字节验证）。
    """
    ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    wx, wy, wz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
    return ((uy * wz - uz * wy) * n[0]
            + (uz * wx - ux * wz) * n[1]
            + (ux * wy - uy * wx) * n[2]) < 0


def _cap_flip(T, args, ny):
    """盖面三角的翻转标志 —— 与 `_face_ok(..., [0,±1,0])` 逐项同序的数组版。

    标量是 `(uy*wz-uz*wy)*n0 + (uz*wx-ux*wz)*n1 + (ux*wy-uy*wx)*n2 < 0`；盖面法线
    只有 y 分量（顶 [0,1,0] / 底 [0,-1,0]），所以 uy 与 wy **恒等于 0.0**（两端同标高）。
    这里仍把第 1、3 项按原样写全（连末尾那个 `* 0.0` 一起）而不是删掉：IEEE754 下
    `x*0.0` 给 ±0.0、加到结果上不变，求和顺序与标量逐位对齐；而万一某项算出 ±inf/NaN，
    `inf*0.0 = NaN` 会让**两边同样**地不翻转，删项则会让两边在 NaN 上分道扬镳。

    `args=(i0,i1,i2)` 是 `tri_f` 的实参顺序：顶面 (0,1,2)；底面标量写的是
    `tri_f(bot0, bot2, bot1, ...)` ⇒ args=(0,2,1)，取差时 u=第 i1 个−第 i0 个。
    T[:, :, 0] 是局部 x（世界 x 同名），T[:, :, 1] 是局部 y（世界 z = −y）。
    """
    px, pz = T[:, :, 0], -T[:, :, 1]
    i0, i1, i2 = args
    ux, uz = px[:, i1] - px[:, i0], pz[:, i1] - pz[:, i0]
    wx, wz = px[:, i2] - px[:, i0], pz[:, i2] - pz[:, i0]
    return ((0.0 * wz - uz * 0.0) * 0.0        # n0 = 0
            + (uz * wx - ux * wz) * ny         # n1 = ±1，唯一活着的一项
            + (ux * 0.0 - 0.0 * wx) * 0.0) < 0  # n2 = 0


def _ring_block(coords, y0, y1, hole, col, col_fn=None):
    """一个环的侧壁：顶点(4/段) + 颜色 + 面(2/段)，面下标是**块内局部**下标。

    与 `MeshBuilder._extrude_ring` 逐位等价，两处必须同步改（改了这里必须改那里）：

    · `a2` 用 `np.cumsum` —— 实测全库环上「cumsum vs 顺序累加」**0 处不同**
      （cumsum 本身就是顺序扫描，不是 `sum` 的成对求和），所以可以整块算。
    · `L` **逐段用 `math.hypot``，不能用 `np.hypot`**：实测 1426770 个环段里
      **106651 段（7.5%）两者差 1 ulp**。L 差一个 ulp 就会经 `nx,ny` 传进
      `_face_ok` 的 `<0` 判断 —— 落在阈值边上的面就翻过来了，字节跟着变。
      （方案里那份探针用的正是 `np.hypot`：它只跑了 4 栋，没踩到而已。）
    · `col_fn` 存在时**整环批调**（`_side_colors`）：只在 L≥1e-9 的段上取色，
      零长边既不产几何也不消耗一次取色；段序与标量完全一致。
    """
    pts = [(float(x), float(y)) for x, y in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()          # shapely 环首尾点重复，去掉免得出一条零长边
    n = len(pts)
    if n < 3:
        return None

    P = np.asarray(pts, dtype=np.float64)
    k = (np.arange(n) + 1) % n
    a2 = np.cumsum(P[:, 0] * P[k, 1] - P[k, 0] * P[:, 1])[-1]
    s = 1.0 if a2 > 0 else -1.0
    if hole:
        s = -s

    Q = P[k]
    ex, ey = Q[:, 0] - P[:, 0], Q[:, 1] - P[:, 1]
    L = np.array([math.hypot(a, b) for a, b in zip(ex.tolist(), ey.tolist())],
                 dtype=np.float64)
    keep = L >= 1e-9
    m = int(keep.sum())
    if m == 0:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        nx = (s * ey / L)[keep]
        ny = (-s * ex / L)[keep]
        # ↑ 先在**全量**上做除法再筛，与标量「逐段算 L、跳过零长边」的取值一致：
        #   被跳过的段其 nx/ny 根本没被用过，算成 inf/nan 也不进任何一行。

    p, q = P[keep], Q[keep]
    if col_fn is not None:
        if SIDECOLOR_BATCH:
            # 与 `_extrude_ring` 同一批实参、同一顺序：(lx0, ly0, lx1, ly1, nx, ny)
            A = np.column_stack([p[:, 0], p[:, 1], q[:, 0], q[:, 1], nx, ny])
            C = np.asarray(_side_colors(col_fn, A, m), dtype=np.uint8)
        else:
            # 老路（`GYM3D_SIDECOLOR=0`）：逐段取色 —— 与 `_extrude_ring` 的老路同序
            C = np.asarray([col_fn(*row) for row in
                            zip(p[:, 0].tolist(), p[:, 1].tolist(),
                                q[:, 0].tolist(), q[:, 1].tolist(),
                                nx.tolist(), ny.tolist())], dtype=np.uint8)
    else:
        C = np.tile(np.asarray(col, dtype=np.uint8), (m, 1))

    # 每段 4 顶点：q0=(p,y0) q1=(q,y0) q2=(q,y1) q3=(p,y1)；局部 (x,y) → 世界 (x,·,-y)
    V = np.empty((m, 4, 3), dtype=np.float64)
    V[:, 0, 0], V[:, 0, 1], V[:, 0, 2] = p[:, 0], y0, -p[:, 1]
    V[:, 1, 0], V[:, 1, 1], V[:, 1, 2] = q[:, 0], y0, -q[:, 1]
    V[:, 2, 0], V[:, 2, 1], V[:, 2, 2] = q[:, 0], y1, -q[:, 1]
    V[:, 3, 0], V[:, 3, 1], V[:, 3, 2] = p[:, 0], y1, -p[:, 1]
    V = V.reshape(-1, 3)

    # quad(q0,q1,q2,q3, [nx,0,-ny]) 的 _face_ok(q0,q1,q2)：u=q1-q0、w=q2-q0
    u0, u1, u2 = V[0::4, 0], V[0::4, 1], V[0::4, 2]
    v0, v1, v2 = V[1::4, 0], V[1::4, 1], V[1::4, 2]
    w0, w1, w2 = V[2::4, 0], V[2::4, 1], V[2::4, 2]
    ux, uy, uz = v0 - u0, v1 - u1, v2 - u2
    wx, wy, wz = w0 - u0, w1 - u1, w2 - u2
    flip = ((uy * wz - uz * wy) * nx
            + (uz * wx - ux * wz) * 0.0
            + (ux * wy - uy * wx) * (-ny)) < 0

    b0 = np.arange(m, dtype=np.int64)[:, None] * 4
    q0, q1, q2, q3 = b0[:, 0], b0[:, 0] + 1, b0[:, 0] + 2, b0[:, 0] + 3
    F = np.empty((m, 2, 3), dtype=np.int64)
    F[:, 0] = np.where(flip[:, None], np.stack([q0, q2, q1], 1),
                       np.stack([q0, q1, q2], 1))
    F[:, 1] = np.where(flip[:, None], np.stack([q0, q3, q2], 1),
                       np.stack([q0, q2, q3], 1))
    # ★ 颜色必须与顶点**逐行对齐**：每段 4 个顶点各要一份色，而上面算出来的 C 是
    #   「段」粒度的（m 行）—— 直接交出去会让 len(colors) = len(verts)/4，
    #   而 trimesh 遇到长度不齐**不报错、直接把 COLOR_0 整条丢掉**（实测：批处理那版
    #   GLB 里根本没有顶点色 accessor，文件小 19%，看着像"格式不同"其实是丢色）。
    #   第一次做就踩了这个坑，靠字节闸门抓出来 —— 判据是产物字节，不是"没抛异常"。
    return V, np.repeat(C, 4, axis=0), F.reshape(-1, 3)


class MeshBuilder:
    """累积顶点/面/顶点色的网格构建器。"""

    def __init__(self):
        self.verts = []
        self.faces = []
        self.colors = []
        # 待批的区域（B2）。空 = 无事可做；**顺序即交付顺序**，见 `_flush`。
        self._pending = []

    # ---------- 批处理发射 ----------
    def _flush(self):
        """把攒下的区域整块发射成顶点/面。

        为什么可以攒、为什么攒了还是逐位相同
        ------------------------------------
        交付字节由 verts/faces 的**顺序**与浮点位模式共同决定，所以攒不是"随便攒"：
        只有在「后面没有任何即时图元插进来」的前提下，攒起来一起发才与逐个发等价。
        这条约束由**入口自己守**——`v`/`quad`/`tri_f` 一进来先 `_flush()`，
        于是即时图元永远排在它前面那些区域的后面，相对顺序与标量逐字相同。

        为什么整块发就快：标量路是「每个三角 6 次 list.append + 每次 quad 现算一遍
        叉积」，全是 Python 解释开销；这里把整个多边形的三角化结果一次摆成数组，
        绕序判定是逐元素比较，顶点/面是 `np.stack`/`where`。

        ★ 每一处算术都**刻意**与标量同形（同顺序、同中间量），不是随手写的等价变形：
        差一个 ulp 就可能让 `_face_ok` 的 `<0` 翻向，交付件立刻变字节。
        """
        if not self._pending:
            return
        items, self._pending = self._pending, []

        Vb, Cb, Fb = [], [], []
        # ★ 面下标要加**全局**基址，不是本次 flush 内的局部计数：`_flush()` 会被调用
        #   多次（每个即时图元插进来就发一次），只按本次计数写，第二次起下标就会从 0
        #   重来 —— 顶点/颜色都对、只有面指向了别的顶点，渲染出来是一片错连的三角。
        #   （第一次做就踩了：477096 个三角里 425220 个下标错。）
        base = len(self.verts)
        nv = 0
        for region, y0, y1, col, col_side in items:
            polys = (region.geoms if region.geom_type == "MultiPolygon"
                     else (region,))
            for poly in polys:
                if poly.geom_type != "Polygon" or poly.is_empty:
                    continue
                for g in _clean(poly):
                    tris = _triangulate(g)
                    if g.interiors:              # 单环无需修（见 add_region 注释）
                        tris = _split_t_junctions(tris)
                    if tris:
                        T = np.asarray(tris, dtype=np.float64)
                        k = len(T)
                        # 顶点顺序：每个三角先顶(3)后底(3) —— 与标量同序（顶、底交替），
                        # 不是"所有顶再所有底"，抄错就是整体错位。
                        V = np.empty((2 * k, 3, 3), dtype=np.float64)
                        V[0::2, :, 0], V[0::2, :, 1], V[0::2, :, 2] = T[:, :, 0], y1, -T[:, :, 1]
                        V[1::2, :, 0], V[1::2, :, 1], V[1::2, :, 2] = T[:, :, 0], y0, -T[:, :, 1]
                        V = V.reshape(-1, 3)
                        idx = np.arange(k, dtype=np.int64)[:, None] * 6
                        ti = np.concatenate([idx + 0, idx + 1, idx + 2], 1)
                        bi = np.concatenate([idx + 3, idx + 4, idx + 5], 1)
                        ft = _cap_flip(T, (0, 1, 2), 1.0)
                        fb = _cap_flip(T, (0, 2, 1), -1.0)
                        # tri_f(a,b,c)：不翻 → [a,b,c]；翻 → [a,c,b]
                        F = np.empty((2 * k, 3), dtype=np.int64)
                        F[0::2] = np.where(ft[:, None], ti[:, [0, 2, 1]], ti)
                        # 底面标量是 tri_f(bot0, bot2, bot1)：不翻 → [0,2,1]，翻 → [0,1,2]
                        F[1::2] = np.where(fb[:, None], bi[:, [0, 1, 2]], bi[:, [0, 2, 1]])
                        Vb.append(V)
                        Cb.append(np.tile(np.asarray(col, dtype=np.uint8), (len(V), 1)))
                        Fb.append(F.reshape(-1, 3) + base + nv)
                        nv += len(V)

                    for hole_flag, ring in ([(False, g.exterior)]
                                            + [(True, h) for h in g.interiors]):
                        r = _ring_block(ring.coords, y0, y1, hole_flag, col, col_side)
                        if r is None:
                            continue
                        V, C, F = r
                        Vb.append(V)
                        Cb.append(C)
                        Fb.append(F + base + nv)
                        nv += len(V)

        if not Vb:
            return
        # 一次 extend 到底：`.tolist()` 是 float64/uint8 → Python 数值的原值往返，
        # 与标量路 append 进去的是同一批数，`export_glb` 里再 asarray 回来逐位不变。
        self.verts.extend(np.concatenate(Vb).tolist())
        self.colors.extend(np.concatenate(Cb).tolist())
        self.faces.extend(np.concatenate(Fb).tolist())

    # ---------- 基础图元 ----------
    def v(self, x, y, z, c):
        # ★ 即时图元一进来先把攒下的区域发掉，否则它的下标会插到那些区域**前面**，
        #   交付件顶点顺序整体错位（面还好、颜色跟着错位）。
        if self._pending:
            self._flush()
        self.verts.append([x, y, z])
        self.colors.append(c)
        return len(self.verts) - 1

    def quad(self, a, b, c, d, n, col):
        """四边形 a→b→c→d 劈成两个三角形，按法线 n 摆正朝向。

        ⚠️ 翻面必须**整块一起翻**：早先的写法是
            if _face_ok(...): b, c = c, b
            faces.append([a, b, c]); faces.append([a, c, d])
        把 b、c 换掉之后第二个三角形用的是**换过的 c**，等于 (a, b_old, d)。
        凸四边形上 (a,b,c) 与 (a,b,d) 绕向相同、与 reverse(a,b,c) 相反 —— 于是
        翻面时两个三角形朝向正好相反，这一对面在带符号体积里精确抵消成 0，
        渲染上则是有一半的面朝里（开背面剔除就穿帮，不开则受光发暗）。
        只在外环是 CCW 时才不触发，所以单测的正方形/L 形全过、一带洞就露馅。
        正确写法：翻面 = a→d→c→b，两个三角形取 (a,d,c) 与 (a,c,b)。
        """
        if self._pending:
            self._flush()          # 同 v()：即时图元必须排在已攒区域之后
        if _face_ok(self.verts[a], self.verts[b], self.verts[c], n):
            self.faces.append([a, c, b])
            self.faces.append([a, d, c])
        else:
            self.faces.append([a, b, c])
            self.faces.append([a, c, d])

    def tri_f(self, a, b, c, n, col):
        if self._pending:
            self._flush()          # 同 v()：即时图元必须排在已攒区域之后
        v = self.verts
        if _face_ok(v[a], v[b], v[c], n):
            b, c = c, b
        self.faces.append([a, b, c])

    # ---------- 挤出示意 ----------
    def add_prism(self, A, B, C, y0, y1, col):
        """三角柱：底面三点 A/B/C（世界 xy 平面坐标），从 y0 挤到 y1。"""
        lo = [self.v(A[0], y0, A[1], col), self.v(B[0], y0, B[1], col), self.v(C[0], y0, C[1], col)]
        hi = [self.v(A[0], y1, A[1], col), self.v(B[0], y1, B[1], col), self.v(C[0], y1, C[1], col)]
        self.tri_f(hi[0], hi[1], hi[2], [0, 1, 0], col)
        self.tri_f(lo[0], lo[2], lo[1], [0, -1, 0], col)
        P = [A, B, C]
        cx = (A[0] + B[0] + C[0]) / 3.0
        cz = (A[1] + B[1] + C[1]) / 3.0
        for i in range(3):
            j = (i + 1) % 3
            mx = (P[i][0] + P[j][0]) / 2.0
            mz = (P[i][1] + P[j][1]) / 2.0
            ox, oz = mx - cx, mz - cz
            L = math.hypot(ox, oz)
            if L < 1e-9:
                continue
            self.quad(lo[i], lo[j], hi[j], hi[i], [ox / L, 0, oz / L], col)

    def _extrude_ring(self, coords, y0, y1, col, hole=False, col_fn=None):
        """沿一个环把侧壁拉出来。hole=True 表示这是洞环（法线要朝洞里）。

        `col_fn(lx0, ly0, lx1, ly1, nx, ny) -> color` 让**每张侧面自己决定颜色**
        （= SU「材质是贴在面的某一侧上的」）。坐标与法向都是**局部米**（未过 g2），
        调用方直接拿它去和轮廓做内外判定即可；col_fn=None 时退化成整环同色 col。

        朝向由环的**有向面积**定，不靠「离质心远的方向」——后者对凹多边形会翻面
        （L 形墙的阴角处法线会指进实体里）。

        `s*(dy,-dx)` 这个组合的几何含义是「背离该环所围的那片区域」，**与环的
        绕向无关**（CCW 时内侧在左、CW 时内侧在右，取 s 后都朝外）。于是：
          · 外环围的是实体   → 背离它 = 指向实体外 → 直接用；
          · 洞环围的是空腔   → 背离空腔 = 指进实体里 → **必须取反**。
        早期版本漏了这一步取反，洞的侧壁法线整圈朝外，带洞多边形算出来的
        有向体积会偏大（单测：1×1 挖 0.5×0.5 得 1.0833，应为 0.75）。
        别指望 shapely 会把洞环规范化成 CW —— 实测传进去是 CCW 就原样保留。
        """
        pts = [(float(x), float(y)) for x, y in coords]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()          # shapely 环首尾点重复，去掉免得出一条零长边
        n = len(pts)
        if n < 3:
            return
        a2 = 0.0
        for i in range(n):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % n]
            a2 += ax * by - bx * ay
        s = 1.0 if a2 > 0 else -1.0
        if hole:
            s = -s
        if col_fn is None or not SIDECOLOR_BATCH:
            # ★ **老路**（无 col_fn 或 `GYM3D_SIDECOLOR=0`）：逐段算、逐段取色、边取边发。
            #   这一段是改动**前**的原文，逐字保留 —— 它同时是回退口和 A/B 的基准，
            #   所以宁可和下面重复四行发射代码，也不把两条路合并成一条"等价"写法
            #   （合并后 `SC_OFF` 就不再是老代码，A/B 量出来的倍率不作数）。
            for i in range(n):
                lx0, ly0 = pts[i]
                lx1, ly1 = pts[(i + 1) % n]
                ex, ey = lx1 - lx0, ly1 - ly0
                L = math.hypot(ex, ey)
                if L < 1e-9:
                    continue
                nx, ny = s * ey / L, s * -ex / L
                c = col_fn(lx0, ly0, lx1, ly1, nx, ny) if col_fn is not None else col
                p0, p1 = g2(lx0, ly0), g2(lx1, ly1)
                q = [self.v(p0[0], y0, p0[1], c), self.v(p1[0], y0, p1[1], c),
                     self.v(p1[0], y1, p1[1], c), self.v(p0[0], y1, p0[1], c)]
                self.quad(q[0], q[1], q[2], q[3], [nx, 0, -ny], c)
            return

        # 批调路：先把整环的有效段算成数组（把逐段取色的固定开销按环摊掉），
        # 再逐段发射。**发射顺序与老路逐字相同** —— 变的只是取色提前算完。
        segs = []
        for i in range(n):
            lx0, ly0 = pts[i]
            lx1, ly1 = pts[(i + 1) % n]
            ex, ey = lx1 - lx0, ly1 - ly0
            L = math.hypot(ex, ey)
            if L < 1e-9:
                continue
            segs.append((lx0, ly0, lx1, ly1, s * ey / L, s * -ex / L))
        cols = _side_colors(col_fn, np.asarray(segs, dtype=np.float64), len(segs))
        for (lx0, ly0, lx1, ly1, nx, ny), c in zip(segs, cols):
            p0, p1 = g2(lx0, ly0), g2(lx1, ly1)
            q = [self.v(p0[0], y0, p0[1], c), self.v(p1[0], y0, p1[1], c),
                 self.v(p1[0], y1, p1[1], c), self.v(p0[0], y1, p0[1], c)]
            self.quad(q[0], q[1], q[2], q[3], [nx, 0, -ny], c)

    def add_region(self, region, y0, y1, col, col_side=None):
        """任意（多）多边形区域从 y0 挤到 y1：只出「上下盖 + 边界侧壁」。

        `col_side` 见 `_extrude_ring`：给了就按面决定侧面颜色，上下盖仍用 col。

        老写法是三角化后**把每个三角形单独挤成一个棱柱**（每三角 8 个面）。相邻
        三角形的公共边会各自出一对朝内的面，那些面夹在实体内部、永远看不见，却
        是体积的大头：宿舍簇 55~74% 的墙是碎渣多边形，面数按三角数的 3 倍膨胀，
        实测把交付件从 726MB 撑到 2563MB（3.5 倍）。改成「盖面铺三角形 + 侧壁只
        沿真实边界环出四边形」后，面数只与「三角数 + 边界边数」成正比。

        几何本身不变：外部表面逐点相同，少掉的只是实体内部的接缝。

        B2 起本函数**默认只登记、不发射**（`MESH_BATCH`），真正的发射在 `_flush()`：
        判据是产物字节不变，机制见 `_flush` 的注释。`GYM3D_MESH_BATCH=0` 退回下面
        这段标量路，用于 A/B 与回退。
        """
        if region is None or region.is_empty:
            return
        if MESH_BATCH:
            self._pending.append((region, y0, y1, col, col_side))
            return
        polys = region.geoms if region.geom_type == "MultiPolygon" else (region,)
        for poly in polys:
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            for g in _clean(poly):
                tris = _triangulate(g)
                if g.interiors:                      # 单环无需修（见函数注释）
                    tris = _split_t_junctions(tris)
                for (ax, ay), (bx, by), (cx, cy) in tris:
                    A, B, C = g2(ax, ay), g2(bx, by), g2(cx, cy)
                    top = [self.v(p[0], y1, p[1], col) for p in (A, B, C)]
                    self.tri_f(top[0], top[1], top[2], [0, 1, 0], col)
                    bot = [self.v(p[0], y0, p[1], col) for p in (A, B, C)]
                    self.tri_f(bot[0], bot[2], bot[1], [0, -1, 0], col)
                self._extrude_ring(g.exterior.coords, y0, y1, col, col_fn=col_side)
                for hole in g.interiors:
                    self._extrude_ring(hole.coords, y0, y1, col, hole=True, col_fn=col_side)

    def add_slab(self, poly, y0, th, col=C_SLAB):
        """楼板：顶面 + 底面 + 侧壁。poly 可含洞（楼梯井已 difference）。

        侧壁此前只沿**外环**走，楼梯井的洞是没有侧壁的 —— 站在洞里往上看，
        楼板是一片没有厚度的纸。现在外环和每个洞环都拉侧壁（用 _extrude_ring
        按有向面积定向，外环朝外、洞环朝内）。
        """
        if poly is None or poly.is_empty:
            return
        if poly.geom_type == "MultiPolygon":
            # 楼梯井洞把楼板切成多块（斜墙楼常见）→ 逐块挤出
            for g in poly.geoms:
                self.add_slab(g, y0, th, col)
            return
        if poly.geom_type != "Polygon":
            return
        for g in _clean(poly):
            tris = _triangulate(g)
            if g.interiors:                          # 单环无需修（见函数注释）
                tris = _split_t_junctions(tris)
            for (ax, ay), (bx, by), (cx, cy) in tris:
                A, B, C = g2(ax, ay), g2(bx, by), g2(cx, cy)
                top = [self.v(p[0], y0 + th, p[1], col) for p in (A, B, C)]
                self.tri_f(top[0], top[1], top[2], [0, 1, 0], col)
                bot = [self.v(p[0], y0, p[1], col) for p in (A, B, C)]
                self.tri_f(bot[0], bot[2], bot[1], [0, -1, 0], col)
            self._extrude_ring(g.exterior.coords, y0, y0 + th, col)
            for hole in g.interiors:
                self._extrude_ring(hole.coords, y0, y0 + th, col, hole=True)

    # ---------- 窗 / 女儿墙 / 盒 ----------
    def add_glass(self, win, y0, S):
        """窗玻璃薄板（与 building.html addGlass 同源）：坐进窗框中央（墙厚中线），
        四周比窗洞内缩一框料厚 ft，旋转轴沿墙方向。"""
        ft = S.get("win_frame_t", 0.06)
        wall_t = S["outer_wall_t"]
        recess = wall_t / 2
        rot_y = math.atan2(win["dy"], win["dx"])
        cx = win["x"] + win["nx"] * recess
        cy = y0 + win["sill"] + win["h"] / 2
        cz = -win["y"] - win["ny"] * recess
        self.add_box(cx, cy, cz, win["w"] - 2 * ft, win["h"] - 2 * ft, S["glass_t"], rot_y, C_GLASS)

    def add_frame(self, win, y0, S, col=C_FRAME):
        """铝合金窗框（与 building.html addWindowFrame 同源）：四根框料围住窗洞，
        跨满墙厚、外皮齐平；厚度轴(Z)对齐内法线（凹墙内法线被翻转，不能固定 atan2(dy,dx)）。"""
        ft = S.get("win_frame_t", 0.06)
        wall_t = S["outer_wall_t"]
        half = win["w"] / 2
        sill_top = y0 + win["sill"]
        win_top = sill_top + win["h"]
        recess = wall_t / 2
        rot_y = math.atan2(win["nx"], -win["ny"])
        dx, dy = win["dx"], win["dy"]
        nx, ny = win["nx"], win["ny"]
        v_mid = (sill_top + win_top) / 2
        members = [
            (win["w"], ft, 0.0, win_top - ft / 2),   # 上框
            (win["w"], ft, 0.0, sill_top + ft / 2),  # 下框
            (ft, win["h"], -half + ft / 2, v_mid),   # 左框
            (ft, win["h"], +half - ft / 2, v_mid),   # 右框
        ]
        for w, h, along_off, v_c in members:
            cx = win["x"] + dx * along_off + nx * recess
            cz = -win["y"] - dy * along_off - ny * recess
            self.add_box(cx, v_c, cz, w, h, wall_t, rot_y, col)

    def add_parapet(self, poly, y0, S, col=C_ROOF, col_side=None):
        """沿轮廓外环向内一圈女儿墙（厚 parapet_t、高 parapet_h）。

        `col_side` 同 add_region：给了就按面的朝向定侧面颜色。女儿墙外皮与轮廓
        （= 外墙外皮）齐平，朝外那张面是立面的延续（该刷外墙色），压顶仍是 col ——
        与 build_walls 里翼楼那圈女儿墙同一口径，两处不能一个按面一个按墙类。

        ⚠️ 方向是**向内**，不是向外。轮廓量的是外墙外皮（ny27 实测：南墙 w0-17
        y[-8.76,-8.52]，轮廓就是 −8.76），女儿墙外皮跟它齐平才叫「立在墙上」；
        早先写成 `poly.buffer(th).difference(poly)`（整环落在轮廓之外），于是屋面
        （add_slab 铺满轮廓）边上凭空多出一圈**悬空外挑 parapet_t=0.5m** 的墙裙，
        立面图上屋顶沿口比外墙外皮鼓出半米（2026-09-12 视图查实，屋顶色三角
        100% 落在轮廓外）。

        做法：把轮廓**整体内缩**出内环，再用原轮廓挖掉内环，得到一圈闭合的实体
        环，最后交给 add_region 挤出。早先的写法是「每条轮廓边各自做一个盒子」：
        相邻盒子在阳角处按各自法线外移、**互不相接**，于是每个屋角都留一道
        豁口；同时相邻盒子在阴角处又整面重叠，同一张面被两组三角形各出一次。
        单测：一圈女儿墙 64 条边里 40 条不闭合。改成整环后闭合、拐角斜接。

        内缩用 mitre（join_style=2）取尖角，与建筑做法一致；但**必须给
        mitre_limit**：GEOS 默认上限是 5.0，遇到锐角会把角点沿角平分线甩出
        好几米（c018 翼楼屋面实测）。限值取 2.0：直角所需的斜接比是
        1/sin45° = 1.414，取 2.0 能让 90° 的楼角保持**尖角**（取 1.0 会把每个
        直角都倒角，楼一圈全是缺口），同时把锐角尖刺压到 ≤0.74 m。
        改小之前先想清楚这一点。
        """
        if poly is None or poly.is_empty:
            return
        if poly.geom_type == "MultiPolygon":
            for g in poly.geoms:
                self.add_parapet(g, y0, S, col, col_side=col_side)
            return
        if poly.geom_type != "Polygon" or poly.is_empty:
            return
        # ★ 2026-09-16 防御无效环：GEOS 的 difference 遇到自交/退化环会抛
        #   TopologyException（c103 修帧后 wingRoof 就踩到："side location conflict at
        #   -54.80,28.13"），一条屋面女儿墙把整栋楼的 GLB 全挂掉。先 make_valid/buffer(0)
        #   修形，再跳过空环 —— 修形只动几何表达、不动位置，屋面颜色/标高都不变。
        if not poly.is_valid:
            fixed = poly.buffer(0)
            if fixed.is_empty:
                return
            if fixed.geom_type == "MultiPolygon":
                for g in fixed.geoms:
                    self.add_parapet(g, y0, S, col, col_side=col_side)
                return
            poly = fixed
        th, h = S["parapet_t"], S["parapet_h"]
        inner = poly.buffer(-th, join_style=2, mitre_limit=2.0)
        if inner.is_empty or inner.area <= 0:
            # 比 2×parapet_t 还窄的翼楼屋面（实测 c009 两片 ≈0.45m 宽条）：内缩即消失，
            # 退化成整块 —— 宁可压满，也不再外挑（外挑会凭空长出建筑 bbox）。
            ring = poly
        else:
            ring = poly.difference(inner)
        if ring.is_empty:
            return
        self.add_region(ring, y0, y0 + h, col, col_side=col_side)

    def add_box(self, cx, cy, cz, w, h, d, rot_y=0.0, col=C_WALL):
        """轴对齐盒（可绕世界 Y 旋转），中心 (cx,cy,cz)，尺寸 (w,h,d)。

        w=沿本地 x，h=沿世界 y（高），d=沿本地 z；rot_y 把本地 x/z 转到世界 x/z，
        与 three.js BoxGeometry + rotation.y 约定一致。
        """
        hw, hh, hd = w / 2, h / 2, d / 2
        cr, sr = math.cos(rot_y), math.sin(rot_y)

        def P(x, y, z):
            return (cx + x * cr + z * sr, cy + y, cz - x * sr + z * cr)

        def N(x, y, z):
            return [x * cr + z * sr, y, -x * sr + z * cr]

        pts = [
            P(-hw, -hh, -hd), P(hw, -hh, -hd), P(hw, hh, -hd), P(-hw, hh, -hd),
            P(-hw, -hh, hd), P(hw, -hh, hd), P(hw, hh, hd), P(-hw, hh, hd),
        ]
        idx = [self.v(px, py, pz, col) for px, py, pz in pts]
        self.quad(idx[0], idx[4], idx[5], idx[1], N(0, -1, 0), col)   # 底
        self.quad(idx[3], idx[2], idx[6], idx[7], N(0, 1, 0), col)    # 顶
        self.quad(idx[4], idx[7], idx[6], idx[5], N(0, 0, 1), col)    # 前 +z
        self.quad(idx[0], idx[1], idx[2], idx[3], N(0, 0, -1), col)   # 后 -z
        self.quad(idx[0], idx[3], idx[7], idx[4], N(-1, 0, 0), col)   # 左 -x
        self.quad(idx[1], idx[5], idx[6], idx[2], N(1, 0, 0), col)    # 右 +x

    # ---------- 导出 ----------
    def export_glb(self, path):
        self._flush()          # ★ 收尾必发：不然最后一批区域（多半是女儿墙/屋面）全丢，
                              #   GLB 少一层而没有任何报错 —— 静默少几何。
        # ★ 顶点色必须与顶点等长。不等长时 trimesh **不报错**，只是把 COLOR_0 整条丢掉
        #   （批处理第一版就这么丢过一次，GLB 小 19% 却"看着正常"）。宁可在这里炸。
        if len(self.colors) != len(self.verts):
            raise ValueError(
                "顶点色与顶点不等长：%d vs %d —— trimesh 会静默丢弃整条 COLOR_0，"
                "别让它过去。" % (len(self.colors), len(self.verts)))
        mesh = trimesh.Trimesh(vertices=self.verts, faces=self.faces, process=False)
        # 顶点色是 sRGB 字节（#a4533d 等），但 glTF COLOR_0 按规范是「线性」空间；
        # 直接写 sRGB 字节会让 Blender 等规范实现把颜色当线性→再编码 sRGB，整体发白
        # （红砖 #a4533d 渲染成桃色 208,144,128）。这里先 sRGB→线性，规范查看器才显示原色。
        colors = np.asarray(self.colors, dtype=float)
        c = colors / 255.0
        lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        linear = (lin * 255.0).round().astype(np.uint8)
        mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=linear)
        mesh.visual.material = PBRMaterial(
            baseColorFactor=[1.0, 1.0, 1.0, 1.0], metallicFactor=0.0, roughnessFactor=1.0)
        mesh.export(path, file_type="glb")
        return mesh
