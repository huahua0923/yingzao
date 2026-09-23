# -*- coding: utf-8 -*-
"""并行批量执行器（轨道 B4）：N 栋楼 = N 个进程，每栋独立跑 `run_step.py`。

为什么是这个形状
----------------
单栋建 GLB 是**纯 CPU 的 Python 解释开销**（`_scratch/_b_prof.py` 实测 c017：逐段
shapely 取色 cum 6.36s = 39%、顶点发射 ≈2.2s = 11%、earcut 三角化 1.4s = 8%，
没有 IO 等待），所以按核开**进程**是线性收益；开线程受 GIL 限制等于没并。
全库 49 栋串行实测 467s ≈ 7.8 分钟，20 逻辑核 ⇒ 分钟级。

为什么按字节安全
----------------
每栋一个**独立进程**、读自己那栋的 `floors/`、写自己那栋的 GLB，进程间**零共享
状态**，序列化路径一个字没改。等价性不是这里说了算的：闸门在
`_scratch/_b_gate.py`（`--all --jobs 8 --tag par49` 与串行基线 `serial49` 逐字节比，
49/49 相同才算过）。本脚本**不自己写任何产物**（除了自己的日志），全部转发给
owner 脚本 `backend/web/run_step.py` —— 见 [[artifact-dir-ownership]]。

代价是内存：实测单栋峰值 372 MB（c006）~ **1773 MB（c054）**，`MeshBuilder` 里
顶点是 Python list（每顶点 3 个 float 对象），峰值比产物 GLB 大一个量级。
所以并发度不拍脑袋，按 1.9 GB/worker 跟物理内存算，算不过就拒绝。

`--jobs` 默认 8 是**量出来的拐点**，不是拍的（2026-09-13，全库 49 栋，同一份
代码、逐字节都比过）：

    jobs=1   墙钟 502.2s   单栋合计 499.6s   最慢单栋 32.8s
    jobs=8   墙钟  93.8s   单栋合计 604.1s (+21%)   最慢 41.6s   ← 5.35×
    jobs=12  墙钟  88.5s   单栋合计 847.3s (+70%)   最慢 59.3s   ← 只快 5%

★ 注意**单栋合计会涨**：并行不是免费的，各进程抢内存带宽/分配器，同一栋在
  jobs=12 下比串行慢 80%。12 并发只比 8 快 5%，却多烧 40% 的 CPU 秒 ⇒ 拐点在 8。
  别把"单栋合计变长"当成回归 —— 那是并行的成本，判据是**墙钟**和**产物字节**。

守卫（都是踩出来的，不是想出来的）
--------------------------------
1. **冻结四栋 c006/c009/c103/c104 默认不碰**（README 铁律 ⑥）。要跑得显式
   `--allow-frozen`，且仍不许 `recognize`/`full`。
2. **`recognize` / `full` 默认拒绝**，要 `--allow-recognize`。理由：`step_recognize`
   会**覆写 `floors/` 和 `spec.json`**，而 `data/` 不在 git、`.orig/` 是人工修复的
   **唯一来源**（铁律 ⑩）；实测 49 栋里 **47 栋**有 `.orig/`，`run_step.py` 自己不备份。
   `glb` 只读 floors、只写 GLB，没有这个风险，所以默认步是它。
3. **同一栋在一批里出现两次 → 拒绝**：两个进程同时写同一个 GLB，谁赢看调度，
   结果不可复现。
4. **并发数 × 1.9 GB 超过可用物理内存 → 拒绝**，并把算式打出来。
5. **每栋日志落盘**：`_scratch/_par_batch_out/<tag>/<楼>.log`，失败了有现场可查。
   ★ 子进程输出必须 `PYTHONIOENCODING=utf-8`，否则中文在 GBK 控制台被糊成乱码
   （[[gbk-mangled-log-units]]：从糊字里读出来的单位是猜的）。
6. **单实例锁**：两个批量器同时跑会互相踩 GLB。锁在 `_par_batch_out/.lock`。

用法
----
    python _par_batch.py glb --all --jobs 8              # 全库重出 GLB（不含冻结四栋）
    python _par_batch.py glb c017 c019 c046 --jobs 4
    python _par_batch.py glb --all --jobs 8 --dry-run    # 只列名单和内存算式，不跑
    python _par_batch.py recognize c017 --allow-recognize
    python _par_batch.py glb c055 --jobs 1               # 单栋串行（等价一次 run_step）
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BDIR = os.path.join(ROOT, "data", "buildings")
OUTROOT = os.path.join(ROOT, "_scratch", "_par_batch_out")
RUN_STEP = os.path.join(ROOT, "backend", "web", "run_step.py")

# 单栋耗时台账（**调度用**，不影响任何产物）：`step/name` → 秒（指数滑动平均）。
# 2026-09-16 加：全库 49 栋按**字母序**下发时，c006（最重，~40s）与 c103（~183s）
# 这种"重楼"会扎堆落在**最后一波**，8~14 个 worker 里只剩 1~2 个还在跑，
# CPU 空转（实测整批墙钟 523.6s，而各栋耗时之和远小于 523.6×jobs）。
# 改成**按历史耗时降序下发（LPT，最长作业优先）**：尾波被压平，墙钟 → 接近 Σ/jobs。
DUR_PATH = os.path.join(OUTROOT, "_durations.json")
_JOBS = [1]          # run_one 里判断"要不要掐 BLAS 线程"用

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 名单的**唯一来源**是 backend/paths.py（2026-09-14 收敛；原先这里与
# _wall_thin_batch.py、README、算法文档各写一份，c006 解冻后三处名单互相打架）。
sys.path.insert(0, os.path.join(ROOT, "backend"))
from paths import FROZEN_BUILDINGS as FROZEN  # noqa: E402

STEPS = ("recognize", "glb", "full")

# 单 worker 内存预算（MB）。取实测最大峰值 1773（c054）上浮一档：算少了自己被 OOM kill，
# 算多了只是并发保守一点。这个数**有出处**，改它必须同时改这里和注释里的实测值。
PEAK_MB_PER_WORKER = 1900
# 可用内存留出的余量：别把机器吃干净（还要跑编辑器/浏览器/控制台）。
RAM_HEADROOM = 0.80


def buildings():
    """有 floors/ 的楼（`_` 开头的内部目录不算）。"""
    return sorted(d for d in os.listdir(BDIR)
                  if not d.startswith("_") and os.path.isdir(os.path.join(BDIR, d, "floors")))


def has_orig(name):
    """该栋有没有 `.orig/`（人工修复的唯一来源，铁律 ⑩）。"""
    d = os.path.join(BDIR, name, ".orig")
    return os.path.isdir(d) and bool(os.listdir(d))


def _mem_mb():
    """(总物理内存 MB, 可用物理内存 MB)。失败返回 (-1, -1)。

    ★ 显式声明 restype/argtypes：`ctypes.windll.x.y()` 默认返回 c_int，
      64 位句柄会被截断（在 `_b_gate.py::_peak_mb` 上栽过，看着像"API 不存在"）。
    """
    import ctypes
    import ctypes.wintypes as wt

    class _MSX(ctypes.Structure):
        _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = k32.GlobalMemoryStatusEx
    fn.restype = wt.BOOL
    fn.argtypes = [ctypes.POINTER(_MSX)]
    m = _MSX()
    m.dwLength = ctypes.sizeof(_MSX)
    if not fn(ctypes.byref(m)):
        return -1.0, -1.0
    return round(m.ullTotalPhys / 2 ** 20, 1), round(m.ullAvailPhys / 2 ** 20, 1)


def resolve_names(a):
    """把 --all / 显式名单 + 各种守卫收敛成最终要跑的名单，或抛 SystemExit(2)。"""
    if a.all:
        # `--all` = 可安全批量的全集，**不含冻结四栋**。它们只能点名 + --allow-frozen。
        # 反过来做（--all 含四栋、再靠守卫拦下来）会让"加 --allow-frozen"变成条件反射，
        # 而这条守卫一旦成了反射就等于没有。跳过谁必须说出来（别静默少跑 4 栋）。
        names = [n for n in buildings() if n not in FROZEN]
        skipped = [n for n in buildings() if n in FROZEN]
        if skipped:
            print("--all 不含冻结四栋，已跳过：%s（要含请点名 + --allow-frozen）"
                  % " ".join(skipped))
    else:
        names = list(a.names)
    if not names:
        raise SystemExit("没指定楼。可跑的有：%s" % " ".join(buildings()))

    unknown = [n for n in names if not os.path.isdir(os.path.join(BDIR, n))]
    if unknown:
        raise SystemExit("不存在的楼：%s" % ", ".join(unknown))

    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise SystemExit(
            "名单里有重复：%s —— 同一栋两个进程会同时写同一个 GLB，谁赢看调度，"
            "结果不可复现。请去重。" % ", ".join(dup))

    if a.step in ("recognize", "full") and not a.allow_recognize:
        risky = [n for n in names if has_orig(n)]
        raise SystemExit(
            "拒绝：step=%s 会**覆写 floors/ 和 spec.json**。`data/` 不在 git，"
            "`.orig/` 是人工修复的唯一来源（铁律 ⑩），而 run_step.py 自己不备份。\n"
            "  这批里 %d/%d 栋有 .orig/：%s\n"
            "  真要跑请加 --allow-recognize，并先确认这些楼的 .orig/ 已归档。"
            % (a.step, len(risky), len(names), " ".join(risky) or "（无）"))

    frozen = [n for n in names if n in FROZEN]
    if frozen:
        if not a.allow_frozen:
            raise SystemExit(
                "拒绝：名单含冻结楼 %s（铁律 ⑥ FROZEN={c006,c009,c103,c104}）。\n"
                "  它们不是「一起跑一下就完事」的普通楼：c009 关 outline_unify 会墙数坍塌、"
                "c103/c104 是双翼楼特殊 profile。要跑请显式加 --allow-frozen，"
                "并单独确认。" % " ".join(sorted(frozen)))
        print("⚠ --allow-frozen：本次会碰冻结楼 %s" % " ".join(sorted(frozen)))

    if a.step == "glb":
        nofloor = [n for n in names if not os.path.isdir(os.path.join(BDIR, n, "floors"))]
        if nofloor:
            raise SystemExit("这些楼没有 floors/，glb 无从建起：%s" % ", ".join(nofloor))
    return names


def ram_guard(jobs, dry=False):
    total, avail = _mem_mb()
    need = jobs * PEAK_MB_PER_WORKER
    line = ("内存算式：%d 并发 × %d MB/worker = %d MB，可用 %.0f MB（总 %.0f MB）"
            % (jobs, PEAK_MB_PER_WORKER, need, avail, total))
    if avail < 0:
        print("⚠ 读不到物理内存，跳过内存守卫（%s）" % line)
        return
    if need > avail * RAM_HEADROOM:
        raise SystemExit(
            "拒绝：%s\n  超过可用量的 %.0f%%（=%.0f MB）。降 --jobs，"
            "或确认没有别的重活后加 --force-ram。"
            % (line, RAM_HEADROOM * 100, avail * RAM_HEADROOM))
    print(line + "  ✓ 余量 %.0f MB" % (avail - need))
    if dry:
        print("（--dry-run：到此为止，没有起任何进程）")


class _Lock:
    """单实例锁：两个批量器同时跑会互相踩同一批 GLB。"""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    info = json.load(fh)
            except Exception:                                      # noqa: BLE001
                info = {"pid": "?", "start": "?"}
            raise SystemExit(
                "拒绝：已有批量器在跑（%s，pid=%s）。锁文件 %s。\n"
                "  确认那个进程真没了，删掉锁文件再跑。"
                % (info.get("start", "?"), info.get("pid", "?"), self.path))
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(),
                       "start": datetime.datetime.now().isoformat(timespec="seconds")}, fh)
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


def load_durations():
    """读单栋耗时台账；坏了就当空表（调度优化，不值得为此中断整批）。"""
    try:
        with open(DUR_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return {k: float(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:                                              # noqa: BLE001
        return {}


def save_durations(dur, results):
    """把本批实测耗时并入台账（EMA α=0.5），供下次 LPT 排序。"""
    for r in results:
        k = "%s/%s" % (r.get("step", "?"), r["name"])
        old = dur.get(k)
        dur[k] = round(r["seconds"], 2) if old is None else round(0.5 * old + 0.5 * r["seconds"], 2)
    try:
        os.makedirs(OUTROOT, exist_ok=True)
        tmp = DUR_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dur, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, DUR_PATH)
    except OSError as e:
        print("⚠ 耗时台账写不进去（不影响本次结果）：%s" % e)


def order_names(names, step, mode="lpt", quiet=False):
    """下发顺序：默认按历史耗时**降序**（LPT）。

    · 顺序只影响"哪个 worker 先拿到哪栋"，**不影响任何产物**（每栋一个独立进程、
      读写自己的目录；`_b_gate.py` 已逐字节验过 serial49 == par49）。
    · 没历史的楼取"已知中位数"当权重 —— 比当成 0（排最后＝又一次尾波空转）稳。
    · **冷启动**（台账为空）用 DXF 体积当权重：解析 DXF 是识别期的大头，
      实测体积序与耗时序高度一致（c046 8.2MB 最慢、c006 7.0MB 次之、c103 5.9MB 第三）。
    """
    if mode != "lpt" or len(names) < 2:
        return names
    dur = load_durations()
    known = sorted(dur.get("%s/%s" % (step, n)) for n in names
                   if dur.get("%s/%s" % (step, n)) is not None)
    if known:
        med = known[len(known) // 2]
        w = lambda n: dur.get("%s/%s" % (step, n), med)          # noqa: E731
        src = "历史耗时（中位数 %.1fs 兜底）" % med
    else:
        w = _dxf_mb
        src = "冷启动：DXF 体积"
    scored = sorted(names, key=lambda n: -w(n))
    if not quiet:
        top = ", ".join("%s=%.1fs" % (n, w(n)) for n in scored[:6])
        print("下发顺序：LPT（%s，降序）  最重 6 栋：%s" % (src, top))
    return scored


_DXF_MB_CACHE = {}


def _dxf_mb(name):
    """profile.json 里 dxf 的兆字节数（读不到给 1.0，排中间）。只用于冷启动排序。"""
    if name not in _DXF_MB_CACHE:
        try:
            with open(os.path.join(BDIR, name, "profile.json"), encoding="utf-8") as fh:
                dxf = (json.load(fh) or {}).get("dxf") or ""
            _DXF_MB_CACHE[name] = os.path.getsize(dxf) / 2 ** 20 if os.path.isfile(dxf) else 1.0
        except Exception:                                          # noqa: BLE001
            _DXF_MB_CACHE[name] = 1.0
    return _DXF_MB_CACHE[name]


def run_one(name, step, tag, timeout):
    """一个子进程跑一栋一步。返回 dict（含 ok / seconds / log 路径 / 末行 JSON）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"       # ★ 不然中文日志在 GBK 控制台被糊掉
    # ★ 2026-09-16 多进程时**掐掉每个 worker 的 BLAS 线程池**：numpy/OpenBLAS/MKL 默认按
    #   逻辑核起线程，8~14 个 worker 各自再起 20 条 → 上百条线程抢 14 个物理核，
    #   看起来"CPU 利用率不高"（其实全在上下文切换）。本链是 shapely+纯 Python 为主，
    #   每 worker 单线程才是我们要的并行粒度；jobs=1 时不动，保留单栋的最快路径。
    if _JOBS[0] > 1:
        for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                  "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            env[k] = "1"
    t0 = time.time()
    p = subprocess.run([sys.executable, RUN_STEP, name, step],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    dt = time.time() - t0
    log = os.path.join(OUTROOT, tag, "%s.log" % name)
    with open(log, "w", encoding="utf-8") as fh:
        fh.write("$ run_step.py %s %s\n\n--- stdout ---\n%s\n--- stderr ---\n%s"
                 % (name, step, p.stdout, p.stderr))
    tail = ""
    for ln in reversed((p.stdout or "").strip().splitlines()):
        if ln.strip().startswith("{"):
            tail = ln.strip()
            break
    return {"name": name, "returncode": p.returncode, "seconds": round(dt, 2),
            "log": os.path.relpath(log, ROOT).replace("\\", "/"), "tail": tail,
            "ok": p.returncode == 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=STEPS, help="glb（默认推荐）/ recognize / full")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--all", action="store_true")
    # ★ 2026-09-17 改默认：**auto**（0 = 自动）。
    #   实测（本机 i5-13600KF 14C/20T + 64GB，全库 95 栋同一份代码）：
    #     jobs=8   墙钟 201.2s   CPU 56~75%   平均并发 7.95×
    #     jobs=14  墙钟  90.8s   CPU 86~93%   平均并发 13.77×   ← 2.2×
    #   老注释里"拐点在 8"是 2026-09-13 那批 49 栋、旧负载量出来的；现在负载更重、
    #   LPT 调度也更平，14 并发是真赚。auto 的取值 = min(逻辑核 × 0.75, 可用内存/1.9GB)，
    #   仍受下面"并发数 × 1.9GB 超可用内存 → 拒绝"那道守卫兜底。
    ap.add_argument("--jobs", type=int, default=0, help="0 = auto（默认）")
    ap.add_argument("--tag", default=None, help="日志目录名（默认按时间戳）")
    ap.add_argument("--timeout", type=int, default=1800, help="单栋超时秒数")
    ap.add_argument("--allow-frozen", action="store_true")
    ap.add_argument("--allow-recognize", action="store_true")
    ap.add_argument("--force-ram", action="store_true")
    ap.add_argument("--order", choices=("lpt", "name"), default="lpt",
                    help="下发顺序：lpt=按历史耗时降序（默认，压尾波）/ name=字母序")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.jobs < 1:                     # auto：min(逻辑核×0.75, 可用内存/1.9GB)，下限 4、上限 16
        total, avail = _mem_mb()
        by_cpu = int((os.cpu_count() or 8) * 0.75)
        by_ram = int(avail / PEAK_MB_PER_WORKER) if avail > 0 else 8
        a.jobs = max(4, min(16, by_cpu, by_ram))
        print("并发 auto = min(核×0.75=%d, 可用内存/1.9GB=%d) → **%d**"
              % (by_cpu, by_ram, a.jobs))
    names = resolve_names(a)
    if a.force_ram:
        print("⚠ --force-ram：跳过内存守卫")
        total, avail = _mem_mb()
        print("  内存：%d 并发 × %d MB/worker = %d MB，可用 %.0f MB（总 %.0f MB）"
              % (a.jobs, PEAK_MB_PER_WORKER, a.jobs * PEAK_MB_PER_WORKER, avail, total))
    else:
        ram_guard(a.jobs, dry=a.dry_run)
    if a.dry_run:
        print("step=%s  共 %d 栋：%s" % (a.step, len(names), " ".join(names)))
        return 0

    names = order_names(names, a.step, a.order)
    _JOBS[0] = a.jobs
    tag = a.tag or datetime.datetime.now().strftime("%m%d-%H%M%S")
    os.makedirs(os.path.join(OUTROOT, tag), exist_ok=True)
    print("step=%s  共 %d 栋  并发 %d  日志 %s"
          % (a.step, len(names), a.jobs, os.path.join(OUTROOT, tag)))

    done = {"n": 0}
    bad = []
    allres = []
    lock = threading.Lock()
    t_all = time.time()

    def _report(r):
        r["step"] = a.step
        allres.append(r)
        with lock:
            done["n"] += 1
            i = done["n"]
            if r["ok"]:
                print("[%2d/%2d] %-8s ✓ %6.1fs" % (i, len(names), r["name"], r["seconds"]))
            else:
                bad.append(r)
                print("[%2d/%2d] %-8s ✗ rc=%d %6.1fs  %s"
                      % (i, len(names), r["name"], r["returncode"], r["seconds"],
                         (r["tail"] or "")[:110]))
                print("            日志: %s" % r["log"])

    with _Lock(os.path.join(OUTROOT, ".lock")):
        if a.jobs == 1:
            for n in names:
                try:
                    _report(run_one(n, a.step, tag, a.timeout))
                except subprocess.TimeoutExpired:
                    _report({"name": n, "ok": False, "returncode": -9, "seconds": a.timeout,
                             "log": "-", "tail": "超时 %ds（--timeout 可调）" % a.timeout})
        else:
            # 线程池只是**等子进程**（真正干活的是子进程），所以 GIL 无害。
            import concurrent.futures as cf
            with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
                futs = {ex.submit(run_one, n, a.step, tag, a.timeout): n for n in names}
                for fu in cf.as_completed(futs):
                    n = futs[fu]
                    try:
                        _report(fu.result())
                    except subprocess.TimeoutExpired:
                        _report({"name": n, "ok": False, "returncode": -9,
                                 "seconds": a.timeout, "log": "-",
                                 "tail": "超时 %ds（--timeout 可调）" % a.timeout})

    wall = time.time() - t_all
    if allres:
        save_durations(load_durations(), allres)
    print("=" * 60)
    print("step=%s  tag=%s  共 %d 栋，失败 %d  墙钟 %.1fs  (jobs=%d)"
          % (a.step, tag, len(names), len(bad), wall, a.jobs))
    tot = sum(r["seconds"] for r in allres)
    slow = sorted(allres, key=lambda r: -r["seconds"])[:3]
    print("单栋耗时之和 %.1fs → 平均并发度 %.2f×（理想 %d×）；最慢 3 栋：%s"
          % (tot, tot / wall if wall else 0, a.jobs,
             ", ".join("%s=%.0fs" % (r["name"], r["seconds"]) for r in slow)))
    if bad:
        print("失败的楼：%s" % " ".join(r["name"] for r in bad))
        print("★ 失败的栋**没有重跑**，交付目录里还是上一次的产物 —— 别当成已完成。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
