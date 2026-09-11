# -*- coding: utf-8 -*-
"""同一栋楼：单跑 10 秒，批量扫里 490 秒 —— 差在哪？

现象
----
全量逐字节扫（一个长驻进程里连建 49 栋）算出 c084 = 490.1 s、c085 = 355.5 s。
把 c084 单独拎出来建，同一份代码，只要 **10.2 s**。同样的几何，差 48 倍。
更刺眼的是：c084 的墙比 c055 少一半还多（3007 vs 7413），墙×窗少 3 倍。

所以「这栋楼复杂」解释不了。候选是**进程随扫推进而退化**：内存碎片、
GEOS/trimesh 的全局池、Python 代际 GC 膨胀……

本脚本要回答的是形状，不是猜测
------------------------------
按**真实扫序**连建，逐栋记：
  * 墙钟
  * 当前工作集 RSS（不是 Peak ——要的是此刻）
  * gc 对象数 / gc 计数
  * **阶段分解**：墙 / 板 / 房间 / 门 / 柱 / 楼梯 / 导出 各占多少

读法：若某阶段耗时随已建栋数单调膨胀，就锁定它；若全阶段等比膨胀，
就是全局内存效应。两者修法完全不同（前者改算法，后者改进程模型）。

为什么不用 cProfile
------------------
490 秒的楼里几百万次小调用会被 cProfile 的每次调用开销放大到面目全非。
这里 perf_counter 包在**函数级**，开销可忽略。

安全
----
只读 data/，产物写 _scratch/_glb_tmp，建一个删一个（磁盘峰值 = 一个 GLB）。

用法
----
    python _scratch/_mem_growth.py --order c084        # 按扫序跑到 c084 为止
    python _scratch/_mem_growth.py --all               # 全 49 栋
    python _scratch/_mem_growth.py c080 c083 c084      # 指定几栋
"""
import ctypes
import gc
import importlib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TMP = os.path.join(ROOT, "_scratch", "_glb_tmp")

# 要分阶段计时的构建环节。名字必须与 build_standard_glb 里的函数同名。
PHASES = ["build_slab", "build_rooms", "build_walls", "build_doors", "build_columns",
          "build_entry_stairs", "build_indoor_stairs", "build_gable_roof", "export_glb"]
# 底层算子。调用次数多，但 perf_counter 相对其自身耗时极小。
OPS = ["add_region", "_extrude_ring", "add_box", "_clean", "_triangulate",
       "_split_t_junctions"]


class PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def _init_probe():
    """psapi 的默认 restype/argtypes 会把 HANDLE 当 32 位截断，结果恒为 0 —— 必须显式声明。"""
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    ps = ctypes.windll.psapi
    ps.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    ps.GetProcessMemoryInfo.restype = ctypes.c_int
    return k32, ps


K32, PS = (_init_probe() if os.name == "nt" else (None, None))


def rss_mb():
    """当前工作集（MB）。刻意不用 Peak —— 要的是此刻，不是历史最高。"""
    if K32 is None:
        return -1.0
    p = PMC()
    p.cb = ctypes.sizeof(PMC)
    if not PS.GetProcessMemoryInfo(K32.GetCurrentProcess(), ctypes.byref(p), p.cb):
        return -1.0
    return p.WorkingSetSize / 1048576.0


def instrument(bsg):
    """给构建环节装计时器。返回 {阶段: [秒, 次数]} 的活字典。"""
    import glb_common as gc
    acc = {}

    def wrap(obj, nm):
        orig = getattr(obj, nm)
        slot = acc.setdefault(nm, [0.0, 0])

        def timed(*a, **kw):
            t0 = time.perf_counter()
            try:
                return orig(*a, **kw)
            finally:
                slot[0] += time.perf_counter() - t0
                slot[1] += 1

        setattr(obj, nm, timed)

    for nm in PHASES + OPS:
        if hasattr(bsg, nm):
            wrap(bsg, nm)
        elif hasattr(gc.MeshBuilder, nm):
            wrap(gc.MeshBuilder, nm)
    return acc


def build(name):
    import build_standard_glb as bsg
    importlib.reload(bsg)
    from run_step import load_profile

    prof = load_profile(name)
    bsg.DATA = os.path.dirname(prof.out_dir)
    os.makedirs(TMP, exist_ok=True)
    bsg.OUT = os.path.join(TMP, "%s-building.glb" % name)
    bsg.INCLUDE_SYNTHETIC_WINDOWS = True
    return bsg


def run(names, verbose=False):
    print("%-3s %-7s %8s %9s %8s %8s %8s   %s"
          % ("#", "楼", "秒", "RSS MB", "gc物件", "gc计数", "ΔRSS", "阶段分解(秒)"))
    print("-" * 118)
    r0 = rss_mb()
    rows = []
    for i, name in enumerate(names, 1):
        gc.collect()
        rss_before = rss_mb()
        bsg = build(name)
        acc = instrument(bsg)
        t0 = time.time()
        bsg.main()
        dt = time.time() - t0
        if os.path.exists(bsg.OUT):
            os.remove(bsg.OUT)                 # 建一个删一个，别攒 2 GB
        r = rss_mb()

        parts = " ".join("%s=%.1f" % (k.replace("build_", ""), v[0])
                         for k, v in sorted(acc.items(), key=lambda kv: -kv[1][0])[:5])
        if verbose:
            parts = " ".join("%s=%.2f(%d)" % (k.replace("build_", ""), v[0], v[1])
                             for k, v in sorted(acc.items(), key=lambda kv: -kv[1][0])[:7])
        print("%-3d %-7s %8.1f %9.0f %8d %8s %+8.0f   %s"
              % (i, name, dt, r, len(gc.get_objects()), gc.get_count(), r - rss_before, parts),
              flush=True)
        rows.append((name, dt))
        del bsg, acc

    print("-" * 118)
    print("RSS: 起始 %.0f MB -> 结束 %.0f MB（涨 %.0f MB）" % (r0, rss_mb(), rss_mb() - r0))
    tot = sum(d for _, d in rows)
    print("合计 %.1f s = %.1f 分钟，平均 %.1f s" % (tot, tot / 60, tot / max(1, len(rows))))
    # 前后半段对比：若后半明显慢于前半，且与楼本身无关，就是累积退化
    h = len(rows) // 2
    if h:
        a = sum(d for _, d in rows[:h]) / h
        b = sum(d for _, d in rows[h:]) / max(1, len(rows) - h)
        print("前半 %d 栋均 %.1f s / 后半 %d 栋均 %.1f s  ->  %.2f×"
              % (h, a, len(rows) - h, b, b / a if a else 0))


def main():
    args = sys.argv[1:]
    verbose = "--verbose" in args
    args = [a for a in args if a != "--verbose"]
    if args and args[0] in ("--order", "--all"):
        from paths import BUILDINGS
        ns = sorted(d for d in os.listdir(BUILDINGS)
                    if os.path.isdir(os.path.join(BUILDINGS, d))
                    and os.path.exists(os.path.join(BUILDINGS, d, "profile.json")))
        if args[0] == "--order":
            names = ns[:ns.index(args[1]) + 1]
            print("按真实扫序连建 %d 栋（到 %s 为止）\n" % (len(names), args[1]))
        else:
            names = ns
            print("按真实扫序连建全部 %d 栋\n" % len(names))
    else:
        names = args or ["c080", "c083", "c084", "c085"]
    run(names, verbose)


if __name__ == "__main__":
    main()
