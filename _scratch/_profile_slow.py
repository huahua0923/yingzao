# -*- coding: utf-8 -*-
"""把「哪一步在烧时间」量成事实，而不是按嫌疑猜。

背景
----
全量基线上跑出两栋离群楼：c084 490 秒、c085 356 秒，而体积 4 倍的 c055 只要 39 秒。
这不是「大模型慢」，是算法在这两栋上退化了。但**退化成什么样不能猜** ——
候选有三：
  1. build_walls 里逐墙 × 逐窗的 shapely 布尔（墙数×窗数是平方级）
  2. _split_t_junctions（有洞才走，且注释里记过一次 2.9s→13min 的事故）
  3. _clean / simplify 在多碎片多边形上退化
三者修法完全不同，所以先量。

为什么不用 cProfile
------------------
cProfile 会给每次函数调用加常数开销。c055 那种 30 秒的楼还能看，490 秒的楼里
几百万次小调用会被放大得面目全非。这里用 perf_counter 包在**函数级**，
开销相对 490 秒可忽略，归因才可信。

安全
----
只读 data/，产物写 _scratch。不碰真实 GLB。

用法
----
    python _scratch/_profile_slow.py c084
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTDIR = os.path.join(ROOT, "_scratch", "_glb_out")


class Stat:
    __slots__ = ("n", "t")

    def __init__(self):
        self.n = 0
        self.t = 0.0


STATS = {}


def wrap(module, name, label=None):
    """把 module.name 包起来记次数与总耗时（含被调用的子调用）。"""
    label = label or name
    st = STATS.setdefault(label, Stat())
    orig = getattr(module, name)

    def timed(*a, **kw):
        t0 = time.perf_counter()
        try:
            return orig(*a, **kw)
        finally:
            st.n += 1
            st.t += time.perf_counter() - t0

    setattr(module, name, timed)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "c084"

    import glb_common as gc
    import build_standard_glb as bsg
    from run_step import load_profile

    p = load_profile(name)
    bsg.DATA = os.path.dirname(p.out_dir)
    os.makedirs(OUTDIR, exist_ok=True)
    bsg.OUT = os.path.join(OUTDIR, "%s-building.glb" % name)
    bsg.INCLUDE_SYNTHETIC_WINDOWS = True

    MB = gc.MeshBuilder
    wrap(gc, "_clean")
    wrap(gc, "_triangulate")
    wrap(gc, "_split_t_junctions")
    wrap(MB, "add_region")
    wrap(MB, "_extrude_ring")
    wrap(MB, "add_slab")
    wrap(MB, "add_box")
    wrap(MB, "add_glass")
    wrap(MB, "add_frame")
    wrap(MB, "add_parapet")
    wrap(MB, "export_glb")
    for ph in ("build_walls", "build_slab", "build_rooms", "build_columns", "build_doors",
               "build_entry_stairs", "build_indoor_stairs", "build_gable_roof",
               "load_floors", "main"):
        if hasattr(bsg, ph):
            wrap(bsg, ph)

    # shapely 侧的嫌疑：逐墙×逐窗的布尔与距离。
    # 注意**不要**包 Polygon.area —— 它是 C 层 property，包成函数后 `poly.area`
    # 会返回 bound method，下游 `poly.area < MIN_WALL_AREA` 直接 TypeError。
    # 属性取值本来也不是瓶颈。
    try:
        from shapely.geometry import Polygon as _P
        wrap(_P, "difference")
        wrap(_P, "distance")
        wrap(_P, "buffer")
        wrap(_P, "intersects")
    except Exception as e:                                   # noqa: BLE001
        print("shapely 包装失败：%s" % e)

    t0 = time.perf_counter()
    bsg.main()
    wall = time.perf_counter() - t0

    size = os.path.getsize(bsg.OUT) / 1024 / 1024 if os.path.exists(bsg.OUT) else -1
    print("\n" + "=" * 74)
    print("[%s] 总墙钟 %.1f s  产物 %.2f MB" % (name, wall, size))
    print("=" * 74)
    print("%-26s %12s %14s %8s" % ("函数", "调用次数", "总耗时 s", "占比"))
    print("-" * 74)
    for label, st in sorted(STATS.items(), key=lambda kv: -kv[1].t):
        if st.n == 0:
            continue
        print("%-26s %12d %14.2f %7.1f%%" % (label, st.n, st.t, 100.0 * st.t / wall))
    print("-" * 74)
    print("注意：这些是**含子调用**的累计耗时，会重叠（如 main 含 build_walls，")
    print("build_walls 含 add_region，add_region 含 _extrude_ring），看排名不看待和。")


if __name__ == "__main__":
    main()
