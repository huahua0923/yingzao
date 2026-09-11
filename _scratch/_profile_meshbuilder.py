# -*- coding: utf-8 -*-
"""MeshBuilder 的调用来源分账：736 万次 v() 到底是谁在调。

为什么非要查调用方
------------------
「把 v() 改成批量发射」听起来是一件事，实际取决于调用方长什么样：
  * add_box  —— 每次 8 顶点 + 6 个 quad，形状完全固定 -> 可以整批按数组算
  * add_region —— 顶点数随多边形变化，且和面交错发射 -> 得先聚成数组再补面
  * _extrude_ring —— 侧壁环，顶点数 = 环长 -> 同上
三者改法不同，占比决定先改哪个。所以先量，不猜。

安全
----
产物只写 _scratch，data/ 一个字节不动。

用法
----
    python _scratch/_profile_meshbuilder.py c055
"""
import cProfile
import importlib
import io
import os
import pstats
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTDIR = os.path.join(ROOT, "_scratch", "_glb_out")

# 想要「谁调用了它」的函数清单
TARGETS = ["v", "quad", "tri_f", "_face_ok", "add_box", "add_region", "_extrude_ring"]


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "c055"

    import build_standard_glb as bsg
    importlib.reload(bsg)
    from run_step import load_profile

    p = load_profile(name)
    bsg.DATA = os.path.dirname(p.out_dir)
    os.makedirs(OUTDIR, exist_ok=True)
    bsg.OUT = os.path.join(OUTDIR, "%s-building.glb" % name)
    bsg.INCLUDE_SYNTHETIC_WINDOWS = True

    buf = io.StringIO()
    pr = cProfile.Profile()
    t0 = time.time()
    pr.enable()
    try:
        bsg.main()
    finally:
        pr.disable()
    wall = time.time() - t0

    size = os.path.getsize(bsg.OUT) / 1024 / 1024 if os.path.exists(bsg.OUT) else -1
    print("\n[%s] 墙钟 %.1fs（含 cProfile 开销，真实值更低）  产物 %.2f MB" % (name, wall, size))

    st = pstats.Stats(pr, stream=buf)

    # ── 1. 按自身耗时排序的全表 ──────────────────────────────────
    buf.truncate(0), buf.seek(0)
    st.sort_stats("tottime").print_stats(20)
    print("\n" + "=" * 78)
    print("按自身耗时（tottime）前 20：")
    print("=" * 78)
    print(_table(buf))

    # ── 2. 目标函数的调用方分账 ──────────────────────────────────
    for t in TARGETS:
        buf.truncate(0), buf.seek(0)
        st.print_callers(t)
        txt = buf.getvalue().strip()
        if not txt:
            continue
        print("\n" + "-" * 78)
        print("谁在调用 %s()：" % t)
        print("-" * 78)
        # print_callers 输出形如:
        #   Ordered by: ...
        #   ncalls  tottime  cumtime  caller
        print(_callers(txt))


def _table(buf):
    """从 pstats 输出里截出表头 + 数据行。"""
    lines = buf.getvalue().splitlines()
    keep, started = [], False
    for ln in lines:
        if "ncalls" in ln:
            started = True
        if started:
            keep.append(ln)
    return "\n".join(keep[:24])


def _callers(txt):
    """print_callers 的原始输出很长，只留「调用方 + 次数 + 耗时」的关键列。"""
    out = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s or "Ordered by" in s or "Function" in s:
            continue
        # 形如:       1234    0.567    1.234    caller_module.py:12(func)
        parts = s.split(None, 3)
        if len(parts) >= 2:
            out.append("  " + s)
    return "\n".join(out[:14])


if __name__ == "__main__":
    main()
