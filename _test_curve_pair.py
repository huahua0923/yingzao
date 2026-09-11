# -*- coding: utf-8 -*-
"""curve_walls 单元自测(合成数据, 不碰任何真实数据)。

1) 轴桶与 geometry._flatten_wall_segments 逐段逐点一致(必须字节级等价)
2) 斜墙(45°两条平行线, 间距 0.24m)应配出 1 块墙, 厚度 ≈ 0.24
3) 同心双弧(半径 R 与 R-0.24, 各离散 0.25m)应配出一串梯形铺满弧带
4) 单条斜线(无配对)应落进 singles, 不产生墙
5) 反向重叠 < 0.3m 的两段不应配对
"""
import sys, math

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path[:0] = [r"D:\gym3d", r"D:\gym3d\backend"]

from backend.recognizer import geometry as G
from backend.recognizer import curve_walls as C

FAIL = []


def check(name, cond, extra=""):
    print("%-42s %s %s" % (name, "PASS" if cond else "FAIL", extra))
    if not cond:
        FAIL.append(name)


class P:
    wall_min, wall_max = 0.10, 0.35


p = P()

# ---- 1) 轴桶等价 ----
walls = [
    [(0.0, 0.0), (5.0, 0.0), (5.0, 3.0)],          # 轴对齐 L 形
    [(0.0, 0.0), (4.0, 3.0)],                        # 斜
    [(1.0, 1.0), (1.0, 4.0)],                        # 竖直
    [(0.0, 0.0), (0.05, 3.0)],                       # 微斜(0.05 > tol) -> 斜桶
    [(0.0, 0.0), (3.0, 0.01)],                       # 微斜(0.01 <= tol) -> 轴桶
    [(2.0, 2.0)],                                    # 单点
    [(2.0, 2.0), (2.0, 2.0)],                        # 零长
]
old = G._flatten_wall_segments(walls)
axis, diag = C._flatten_all_segments(walls)
check("轴桶 == 旧版 _flatten_wall_segments", old == axis,
      "old=%d axis=%d diag=%d" % (len(old), len(axis), len(diag)))

# ---- 2) 斜墙 ----
seg_lo = [(0.0, 0.0), (3.0, 3.0)]
d = 0.24 / math.sqrt(2)
seg_hi = [(0.0 + d, 0.0 - d), (3.0 + d, 3.0 - d)]     # 法向偏移 0.24m
rects, singles = C.pair_curved_faces([seg_lo, seg_hi], p)
check("45°斜墙配成 1 块", len(rects) == 1 and not singles,
      "rects=%d singles=%d" % (len(rects), len(singles)))
if rects:
    check("  斜墙厚度 ≈ 0.24", abs(rects[0][1] - 0.24) < 0.005, "t=%.4f" % rects[0][1])
    # 段长 = 3*sqrt(2) = 4.2426, 墙面积 = 4.2426 * 0.24 = 1.018
    check("  斜墙面积 ≈ L*T", abs(rects[0][0].area - 3 * math.sqrt(2) * 0.24) < 0.01,
          "area=%.4f" % rects[0][0].area)

# ---- 3) 同心双弧 ----
R, T = 10.0, 0.24
N = 40
a0, a1 = math.radians(0), math.radians(90)


def arc_line(r, n):
    return [(r * math.cos(a0 + (a1 - a0) * i / n), r * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


# 走真实链路: 折线 -> _flatten_all_segments 拆弦 -> 轴桶走旧配对 / 斜桶走新配对
arcs = [arc_line(R, N), arc_line(R - T, N)]
axis_arc, diag_arc = C._flatten_all_segments(arcs)
# 90° 弧上每条弦都是斜的, 但首尾各有一条恰好轴对齐(Δ=R(1-cos2.25°)=0.008m < 0.02),
# 按定义归轴桶 —— 旧函数也是这么分的, 所以这里允许 2N-4。
check("双弧拆弦(轴桶收下轴对齐的 4 条)",
      len(diag_arc) == 2 * N - 4 and len(axis_arc) == 4,
      "axis=%d diag=%d" % (len(axis_arc), len(diag_arc)))
recs, sgl = C.pair_curved_faces(diag_arc, p, angle_tol_deg=12.0)
# 每段弦只与正对的另一段弦配对: 相邻弦方向差 90/N=2.25°(在 12° 容差内), 但它到
# 本弦中点的垂距 ≈ 0.0075m < wall_min 0.10, 被挡掉; 正对弦垂距 = 0.24 ✓
check("双弧配出多块(梯形链)", len(recs) == len(diag_arc) // 2 and not sgl,
      "rects=%d singles=%d" % (len(recs), len(sgl)))
# 端到端: 两个桶的墙合并后应铺满整个 90° 环形扇面
r_axis, _ = G.pair_wall_faces(axis_arc, p)
tot_area = sum(r[0].area for r in recs) + sum(r[0].area for r in r_axis)
want = math.pi * (R ** 2 - (R - T) ** 2) / 4      # 90° 环形扇面面积
check("  弧带总面积接近理论", abs(tot_area - want) / want < 0.05,
      "got=%.3f want=%.3f (轴桶贡献 %.3f)" % (tot_area, want, sum(r[0].area for r in r_axis)))
if recs:
    ts = [r[1] for r in recs]
    check("  每块厚度 ∈ [0.10,0.35]", all(0.10 <= t <= 0.35 for t in ts),
          "min=%.3f max=%.3f" % (min(ts), max(ts)))

# ---- 4) 单条斜线 ----
r4, s4 = C.pair_curved_faces([[(0.0, 0.0), (5.0, 5.0)]], p)
check("孤立斜线 -> singles, 无墙", not r4 and len(s4) == 1)

# ---- 5) 重叠不足 ----
a5 = [(0.0, 0.0), (1.0, 0.0)]
b5 = [(0.0, 0.24), (1.0, 0.24)]          # 完全正对 -> 应配对
c5 = [(5.0, 0.0), (5.2, 0.0)]            # 与 a5 同线但错开 4m, 重叠 0
r5, s5 = C.pair_curved_faces([a5, c5], p)
check("错开的两段不配对", not r5 and len(s5) == 2)

# ---- 6) 完全平行的两条不同线但间距超限 ----
far = [(0.0, 2.0), (1.0, 2.0)]
r6, s6 = C.pair_curved_faces([a5, far], p)
check("间距 2m 超 wall_max 不配对", not r6 and len(s6) == 2)

print()
print("失败项: %s" % (", ".join(FAIL) if FAIL else "无"))
sys.exit(1 if FAIL else 0)
