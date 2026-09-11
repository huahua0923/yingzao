# -*- coding: utf-8 -*-
"""GLB 装配分账：每个 build_* 函数各花多久。

背景
----
全量重出 49 栋 GLB = 448 分钟（≈9 分钟/栋），而整栋 recognize 只要 6.6 秒。
时间几乎全在这里。分账是为了回答「GPU 有没有用武之地」—— 顶点/面片的
批量变换是 GPU 强项，Python 逐构件循环不是。

安全
----
bsg.OUT 指到 _scratch 下，不覆盖真实 GLB。data/ 里的产物一个字节都不动。

用法
----
    python _scratch/_time_glb_phases.py c019 [c043 ...]
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTDIR = os.path.join(ROOT, "_scratch", "_glb_out")

PHASES = ["build_walls", "build_slab", "build_rooms", "build_columns", "build_doors",
          "build_entry_stairs", "build_indoor_stairs", "build_gable_roof", "load_floors"]


def time_one(name, do_windows):
    import importlib
    import build_standard_glb as bsg
    importlib.reload(bsg)          # 每栋重置累加器，互不污染

    from run_step import load_profile
    p = load_profile(name)

    timings = {}

    def wrap(fn_name):
        orig = getattr(bsg, fn_name)

        def timed(*a, **kw):
            t0 = time.time()
            try:
                return orig(*a, **kw)
            finally:
                timings[fn_name] = timings.get(fn_name, 0.0) + (time.time() - t0)
        timed.__name__ = fn_name
        setattr(bsg, fn_name, timed)

    for ph in PHASES:
        if hasattr(bsg, ph):
            wrap(ph)

    # 与 run_batch.py 完全一致的调用方式，只改输出位置
    bsg.DATA = os.path.dirname(p.out_dir)
    os.makedirs(OUTDIR, exist_ok=True)
    bsg.OUT = os.path.join(OUTDIR, "%s-building.glb" % name)
    bsg.INCLUDE_SYNTHETIC_WINDOWS = bool(do_windows)

    t0 = time.time()
    bsg.main()
    total = time.time() - t0

    size = os.path.getsize(bsg.OUT) / 1024.0 / 1024.0 if os.path.exists(bsg.OUT) else -1
    return total, size, timings


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_windows = "--windows" in sys.argv
    names = args or ["c019"]
    print("输出目录（临时）: %s\n" % OUTDIR)

    for name in names:
        total, size, timings = time_one(name, do_windows)
        covered = sum(timings.values())
        print("=" * 70)
        print("[%s] 总墙钟 %.1fs (%.1f 分钟)  产物 %.2f MB" % (name, total, total / 60, size))
        print("  已计时的阶段合计 %.1fs = 总时间的 %.1f%%" % (covered, 100.0 * covered / total))
        for ph, sec in sorted(timings.items(), key=lambda kv: -kv[1]):
            print("    %-22s %7.2fs  %5.1f%%" % (ph, sec, 100.0 * sec / total))
        print("    %-22s %7.2fs  %5.1f%%" % ("(未计时: 装配/导出等)",
                                              total - covered, 100.0 * (total - covered) / total))
        print()


if __name__ == "__main__":
    main()
