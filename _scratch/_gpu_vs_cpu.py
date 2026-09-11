# -*- coding: utf-8 -*-
"""GPU 到底能不能加速几何计算 —— 在真实规模上实测。

规模取自 c055（最大的一栋）的实测数字：7,359,312 顶点 / 2,981,516 面。

三种计时口径，区别很重要：
  CPU        —— numpy，数据在内存里
  GPU(含搬运) —— 数据要 H2D 传上去、算完 D2H 传回来（「CPU 代码 + GPU 加速器」的诚实成本）
  GPU(常驻)   —— 数据本来就在显存里（整个流水线都在 GPU 上跑时的真实成本）

只有第三种才是「GPU-native 架构」下的性能。逐项打印，因为整轮跑很久。
"""
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NV, NT = 7_359_312, 2_981_516


def bench(fn, n=3, warmup=1, label=""):
    for _ in range(warmup):
        fn()
    best = float("inf")
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    best *= 1000.0
    print("  %-16s %9.1f ms" % (label, best), flush=True)
    return best


def main():
    import cupy as cp
    print("cupy %s | %s" % (cp.__version__,
                            cp.cuda.runtime.getDeviceProperties(0)["name"].decode()))
    print("规模: 顶点 %d / 面 %d" % (NV, NT), flush=True)

    rng = np.random.default_rng(0)
    V = rng.random((NV, 3))
    F = rng.integers(0, NV, size=(NT, 3)).astype(np.int32)
    N = rng.random((NT, 3)) * 2 - 1
    M = np.eye(4, dtype=np.float64)
    M[:3, 3] = (1.0, 2.0, 3.0)

    print("上传一次……", flush=True)
    Vg, Fg, Ng, Mg = cp.asarray(V), cp.asarray(F), cp.asarray(N), cp.asarray(M)
    cp.cuda.runtime.deviceSynchronize()

    res = []

    # ---------------------------------------------------------------- 1
    print("\n1. 面法线（gather 3 顶点 + 叉积）—— 随机访存，CPU 缓存不友好", flush=True)

    def f_cpu():
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        u, w = b - a, c - a
        n = np.empty_like(u)
        n[:, 0] = u[:, 1] * w[:, 2] - u[:, 2] * w[:, 1]
        n[:, 1] = u[:, 2] * w[:, 0] - u[:, 0] * w[:, 2]
        n[:, 2] = u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]
        return n

    def f_gpu_resident():
        a, b, c = Vg[Fg[:, 0]], Vg[Fg[:, 1]], Vg[Fg[:, 2]]
        u, w = b - a, c - a
        n = cp.empty_like(u)
        n[:, 0] = u[:, 1] * w[:, 2] - u[:, 2] * w[:, 1]
        n[:, 1] = u[:, 2] * w[:, 0] - u[:, 0] * w[:, 2]
        n[:, 2] = u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]
        cp.cuda.runtime.deviceSynchronize()
        return n

    def f_gpu_transfer():
        V2, F2 = cp.asarray(V), cp.asarray(F)
        a, b, c = V2[F2[:, 0]], V2[F2[:, 1]], V2[F2[:, 2]]
        u, w = b - a, c - a
        n = cp.empty_like(u)
        n[:, 0] = u[:, 1] * w[:, 2] - u[:, 2] * w[:, 1]
        n[:, 1] = u[:, 2] * w[:, 0] - u[:, 0] * w[:, 2]
        n[:, 2] = u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]
        cp.cuda.runtime.deviceSynchronize()
        return cp.asnumpy(n)

    res.append(("面法线 (gather+叉积)",
                bench(f_cpu, label="CPU numpy"),
                bench(f_gpu_transfer, label="GPU 含搬运"),
                bench(f_gpu_resident, label="GPU 常驻")))

    # ---------------------------------------------------------------- 2
    print("\n2. 绕序判定 + 翻转（面朝向修正，逐面条件分支）", flush=True)

    def o_cpu():
        a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
        u, w = b - a, c - a
        d = ((u[:, 1] * w[:, 2] - u[:, 2] * w[:, 1]) * N[:, 0]
             + (u[:, 2] * w[:, 0] - u[:, 0] * w[:, 2]) * N[:, 1]
             + (u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]) * N[:, 2])
        bad = d < 0
        out = F.copy()
        out[bad, 1], out[bad, 2] = F[bad, 2], F[bad, 1]
        return out

    def o_gpu_resident():
        a, b, c = Vg[Fg[:, 0]], Vg[Fg[:, 1]], Vg[Fg[:, 2]]
        u, w = b - a, c - a
        d = ((u[:, 1] * w[:, 2] - u[:, 2] * w[:, 1]) * Ng[:, 0]
             + (u[:, 2] * w[:, 0] - u[:, 0] * w[:, 2]) * Ng[:, 1]
             + (u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]) * Ng[:, 2])
        idx = cp.where(d < 0)[0]
        out = Fg.copy()
        tmp = out[idx, 1].copy()
        out[idx, 1] = out[idx, 2]
        out[idx, 2] = tmp
        cp.cuda.runtime.deviceSynchronize()
        return out

    def o_gpu_transfer():
        V2, F2, N2 = cp.asarray(V), cp.asarray(F), cp.asarray(N)
        a, b, c = V2[F2[:, 0]], V2[F2[:, 1]], V2[F2[:, 2]]
        u, w = b - a, c - a
        d = ((u[:, 1] * w[:, 2] - u[:, 2] * w[:, 1]) * N2[:, 0]
             + (u[:, 2] * w[:, 0] - u[:, 0] * w[:, 2]) * N2[:, 1]
             + (u[:, 0] * w[:, 1] - u[:, 1] * w[:, 0]) * N2[:, 2])
        idx = cp.where(d < 0)[0]
        out = F2.copy()
        tmp = out[idx, 1].copy()
        out[idx, 1] = out[idx, 2]
        out[idx, 2] = tmp
        cp.cuda.runtime.deviceSynchronize()
        return cp.asnumpy(out)

    res.append(("绕序判定+翻转",
                bench(o_cpu, label="CPU numpy"),
                bench(o_gpu_transfer, label="GPU 含搬运"),
                bench(o_gpu_resident, label="GPU 常驻")))

    # ---------------------------------------------------------------- 3
    print("\n3. 顶点去重（排序类；用 int64 键，CPU/GPU 都能走快路径）", flush=True)
    Q = np.clip(np.round(V * 10000), 0, 2**20 - 1).astype(np.int64)
    key = (Q[:, 0] << 42) | (Q[:, 1] << 21) | Q[:, 2]
    keyg = cp.asarray(key)

    def u_cpu():
        return np.unique(key, return_inverse=True)

    def u_gpu_resident():
        r = cp.unique(keyg, return_inverse=True)
        cp.cuda.runtime.deviceSynchronize()
        return r

    def u_gpu_transfer():
        kg = cp.asarray(key)
        r = cp.unique(kg, return_inverse=True)
        cp.cuda.runtime.deviceSynchronize()
        return cp.asnumpy(r[0])

    res.append(("顶点去重 (int64 键)",
                bench(u_cpu, n=2, label="CPU numpy"),
                bench(u_gpu_transfer, n=2, label="GPU 含搬运"),
                bench(u_gpu_resident, n=2, label="GPU 常驻")))

    # ---------------------------------------------------------------- 4
    print("\n4. 顶点 4x4 变换（稠密矩阵乘，GPU 的教科书场景）", flush=True)

    def m_cpu():
        Vh = np.empty((NV, 4))
        Vh[:, :3] = V
        Vh[:, 3] = 1.0
        return Vh @ M.T

    def m_gpu_resident():
        Vh = cp.empty((NV, 4), dtype=cp.float64)
        Vh[:, :3] = Vg
        Vh[:, 3] = 1.0
        r = Vh @ Mg.T
        cp.cuda.runtime.deviceSynchronize()
        return r

    res.append(("顶点变换 4x4",
                bench(m_cpu, label="CPU numpy"),
                None,
                bench(m_gpu_resident, label="GPU 常驻")))

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 62, flush=True)
    print("%-22s %12s %14s %12s %8s" % ("运算", "CPU", "GPU(含搬运)", "GPU(常驻)", "加速比"))
    print("-" * 62)
    for name, cpu, xfer, resi in res:
        xs = "%12.1f ms" % xfer if xfer is not None else " " * 12
        rs = "%12.1f ms" % resi if resi is not None else " " * 12
        sp = "%7.1fx" % (cpu / resi) if resi else " " * 8
        print("%-22s %9.1f ms %s %s %s" % (name, cpu, xs, rs, sp))

    nb = NV * 3 * 8 + NT * 3 * 4
    print("\n数据体积: %.1f MB（顶点 %.0f MB + 面索引 %.0f MB）"
          % (nb / 1e6, NV * 3 * 8 / 1e6, NT * 3 * 4 / 1e6))
    t0 = time.perf_counter(); _ = cp.asarray(V); cp.cuda.runtime.deviceSynchronize()
    h2d = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter(); _ = cp.asnumpy(Vg)
    d2h = (time.perf_counter() - t0) * 1000
    print("实测 H2D(顶点) %.1f ms / D2H(顶点) %.1f ms -> 往返 %.1f ms"
          % (h2d, d2h, h2d + d2h))
    print("这是「CPU 代码 + GPU 加速器」每次交互都要交的固定税。")


if __name__ == "__main__":
    main()
