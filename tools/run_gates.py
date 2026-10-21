# -*- coding: utf-8 -*-
"""跑判据（分档 + 并行）。每条判据按**它自己声明的默认参数**跑，stdout 原样落 run.txt。

约定（与既有 run.txt 相同）：`python gates/<名>.py > gates/_out/<名>.run.txt 2>&1`，
各判据自己把 json 写到它 `--json` 的默认位。**不代它挑参数**。

★ **2026-10-14 追加一行**（本文件唯一的落盘改动）：run.txt = 判据 stdout **＋ 末尾一行由本
  运行器写的实测**（`--- run_gates 运行器实测（进程退出码，非被测件自报）: rc=N  …`）。
  为什么加：台账页 `demo/sys.html` 对每条判据取**三路互相独立**的读数，第二路是「run.txt 里的
  `rc=`」—— 而这一路原先**只有判据自己印才算有**，实测 18 条里有 6 条判词行根本不印 rc
  ⇒ 页上那一格恒显示「—（run.txt 里没有 rc=）」。由**运行器**写还更硬：它是**进程退出码**，
  不是自报。★ 顺带堵一个假报：有的判据会为**正对照的子进程**印 `rc=4`，若它自己不印 `rc=0`，
  页面会按「产物说 PASS 而 run.txt 里没有 0」读成「rc 非 0 而产物说 PASS」。
  ★ 追加行的措辞**避开**行首 `PASS`/`FAIL` 与「总判」二字 —— 那两处是第三路读数的正则。

★ 分档 —— 「改哪一块，才需要重跑哪一档」：
  档位表在 `tools/gate_tiers.py`（**唯一来源**，本文件与台账页都从那里 import）。
  **单条耗时一律不在这里写** —— 每跑一趟本脚本就把实测秒数落进
  `gates/_out/_ledger.json`（`rows[].secs`、`wall_s`）。要看现值：跑一趟、读那份 json；
  或 `python -c "import json;print(json.load(open('gates/_out/_ledger.json',encoding='utf-8')))"`。
  ★ 为什么不在 docstring 里写死：那两个数会漂（判据增减、机器负载），写死就是**同一个量的第二份副本**
    （铁律 174）—— 第一版正是这样，docstring 说 19.9 min 而实测已不是。
  其余未分档的判据归 `other`，只在**全量**里跑。

★ 并行：非 CAD 档**互不写同一件** ⇒ 并行；**CAD 三条必须串行**（AutoCAD 单实例 / 许可，
  并行会互相掐）。实现：一个线程池，CAD 三条**串成一个任务**占一个 worker，其余各占一个
  ⇒ 墙钟 ≈ max(CAD 串行, 其余并行)，而不是两者相加。

用法:
  python tools/run_gates.py                  # 全量（除 viewer；与旧行为一致）
  python tools/run_gates.py --quick          # 只跑快档（≈1 min）
  python tools/run_gates.py --cad            # 只跑 CAD 档（串行）
  python tools/run_gates.py --dxf            # 只跑 DXF 档
  python tools/run_gates.py --full           # 全量 **含 viewer**
  python tools/run_gates.py --tiers quick,dxf
  python tools/run_gates.py --jobs 8         # 并行度（默认 min(6, 核数)）
  python tools/run_gates.py A1e A1d          # 按名字片段挑（旧用法，仍可用）
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = r"D:\项目\cdut3d"
GATES = os.path.join(ROOT, "gates")
GOUT = os.path.join(GATES, "_out")

# ★ 档位表**不在这里写** —— 唯一来源是 `tools/gate_tiers.py`
#   （本文件与台账页两边都 import 它）。铁律 174：同一个量有两个同名的副本，必须死掉一个；
#   第一版就是在 run_gates.py 与 build_sys_page.py 里各写了一份，改档位要改两个地方。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import gate_tiers as _GT                                            # noqa: E402

TIER, ALL_TIERS = _GT.TIER, _GT.ALL_TIERS

# ---- 命名口径：run.txt 用**仓里已经在用的那个编号**，不是脚本全名 ----
_EXTS = (".run.txt", ".log", ".console.txt", ".json")
_existing = sorted({f[:-len(e)] for f in os.listdir(GOUT) for e in _EXTS if f.endswith(e)},
                   key=len, reverse=True) if os.path.isdir(GOUT) else []


def gate_id(stem):
    return next((e for e in _existing if stem.startswith(e)), stem.split("_")[0])


def gate_rel(stem):
    """返回该脚本在 `_out/` 里该落的**文件名**（编号 + **它已经用的那个扩展名**）。

    ★ 扩展名也要跟已有的走：`J-09.2-A1` 在仓里是 **`.log`** 不是 `.run.txt`。
      硬写 `.run.txt` ⇒ 多出一个同内容孤儿件，而 `build_sys_page` 按 `.run.txt` 优先挑
      ⇒ 页面改读新件、旧 `.log` 无人引用（判词一样，但**件数**对不上）。
    """
    gid = gate_id(stem)
    for e in _EXTS:
        if os.path.exists(os.path.join(GOUT, gid + e)):
            return gid + e
    return gid + ".run.txt"


def tier_of(fname):
    return _GT.tier_for(gate_id(fname[:-3]), is_viewer="viewer" in fname.lower())


# ---- 参数 ----
argv = sys.argv[1:]
jobs = min(6, os.cpu_count() or 4)
want = set()
picks = []
i = 0
while i < len(argv):
    a = argv[i]
    if a in ("--quick", "--cad", "--dxf"):
        want.add(a[2:])
    elif a == "--viewer":
        want.add("viewer")
    elif a == "--full":
        want.update(ALL_TIERS)
    elif a == "--tiers":
        i += 1
        want.update(x.strip() for x in argv[i].split(",") if x.strip())
    elif a == "--jobs":
        i += 1
        jobs = max(1, int(argv[i]))
    elif a in ("-h", "--help"):
        # ★ 不加这一支的代价（2026-10-13 实测踩到）：`--help` 落进 `picks`，被当成
        #   **文件名片段**去筛 ⇒ 一条都筛不到 ⇒ 报「这一档一条判据都没有」。
        #   判词把「你打错了开关」说成了「这一档是空的」—— 两句都不是真的
        #   （铁律 199：「没匹配上」与「没量到」不许同形）。
        print(__doc__)
        sys.exit(0)
    else:
        picks.append(a)
    i += 1
if not want:
    # ★ 默认 = **只有 quick**（2026-10-15 由 quick + dxf 收窄）。
    #   · CAD 档 2026-10-12 降出默认：它的定向臂在最终模型上 **Δ足迹 = 0.000 m²**
    #     （判据 J-07.9.4-03 实测），却占全量墙钟 **六成以上**、每趟冷启 **6 次 AutoCAD**
    #     ⇒ 见 `gate_tiers.py::CAD_DEMOTED`。
    #   · dxf 档 2026-10-15 降出默认：这 4 条量的是 **a1 通用链**，而交付件
    #     （`rebuild/06_su/c006_su.glb` → 包）那条链**一行都不 import 它**
    #     ⇒ 见 `gate_tiers.py::A1_DEMOTED` 与 `rebuild/交付口径与判据审计.md` §1/§2。
    #   ★ 代价（必须写在旁边，铁律 28）：这两条路断了，默认这趟**不会报**；
    #     要它们报就跑 `--dxf` / `--cad`（串行）/ `--full`。放进**周期性全量**，不进日常循环。
    want.add("quick")

_ALL_PY = sorted(f for f in os.listdir(GATES) if f.endswith(".py"))
# ★ 2026-10-20：下划线开头的是**共用件/编排件**，不是判据 —— 不许进档位。
#   实测：`_runner.py`（判据矩阵编排器，自己按楼栋跑一遍全部闸）被 `tier_of` 的默认值
#   判成 `other` 混进来 ⇒ 每趟 other 多跑 **505 s**，而且它的 rc 含义是「有楼有红」，
#   与「这条判据红了」**同形**（铁律 199）；`_items.py` / `_verdict.py` 是模块，
#   当脚本跑 rc=0，也是假条目。
#   ★ 代价（铁律 28）：真判据若起名下划线，会**不跑**。所以下面不静默 —— 点名印出来。
_HELPERS = [f for f in _ALL_PY if f.startswith("_")]
names = [f for f in _ALL_PY if not f.startswith("_")]
if _HELPERS:
    print("（非判据，下划线开头 · 不进档位：%s）" % ", ".join(_HELPERS))
if not names:
    print("★ 没量到：gates/ 里除共用件外一条判据都没有 ⇒ rc=4")
    sys.exit(4)
if picks:
    hit = [f for f in names if any(p.lower() in f.lower() for p in picks)]
    if not hit:
        # ★ 三件事**必须分开**（铁律 199：「打错了」「档不跑」「这档真空」同形会误读）：
        #   2026-10-15 实测踩到第三种 —— `run_gates.py J-10.9`（四条都在）报了
        #   「按名字片段一条都没筛到」，实情是名字**筛到了 4 条**、被后面的**档位**滤掉
        #   （它们是 other/viewer，而默认 want=quick+dxf）⇒ 判词把「档没跑」说成了「没有那条」。
        print("★ 没匹配上：按名字片段 %s 在 gates/ 里一条都没筛到（看用法：--help）⇒ rc=4"
              % picks)
        sys.exit(4)
    names = hit
tk = sorted({tier_of(f) for f in names})
names = [f for f in names if tier_of(f) in want]
if not names:
    if picks:
        print("★ 名字筛到 %d 条，但它们的档 %s **不在本次 want=%s 里** ⇒ 一条都没跑（不是「没有这条判据」）"
              % (len(hit), tk, sorted(want)))
        print("   要跑它们：python tools/run_gates.py --tiers %s %s"
              % (",".join(tk), " ".join(picks)))
    else:
        print("★ 没量到：这一档一条判据都没有（want=%s）⇒ rc=4" % sorted(want))
    sys.exit(4)

os.makedirs(GOUT, exist_ok=True)
_lock = threading.Lock()


def run_one(f):
    """跑一条，返回 (f, rc, 秒, 备注)。落盘规则与旧版一致（自 _Tee 的不重复写）。"""
    stem = f[:-3]
    out = os.path.join(GOUT, gate_rel(stem))
    t0 = time.time()
    # ★ 环境里塞 UTF-8：判据里的中文/希腊字母在 cp936 控制台上会炸在 print 上，
    #   那种炸是**量具**的错、不是被测件的错，会把真判词盖掉。
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.join(GATES, f)], cwd=ROOT,
                       capture_output=True, env=env)
    txt = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    # ★ 四条判据自己用 `_Tee` 落 run.txt（CAD/viewer 那四条）⇒ 它们的 stdout 在这里是**空**的。
    #   空就别写：写了就是一个 0 字节的**假件**，页面会把它当成「判词没留在盘上」的另一份。
    if txt.strip():
        with open(out, "wb") as fh:
            fh.write(txt.encode("utf-8").replace(b"\r\n", b"\n"))
        note = ""
    else:
        note = "（自己 _Tee 落盘 ⇒ 我这里不重复写）"
    # ★ 追加**运行器实测的退出码**（见 docstring 里 2026-10-14 那一段）。
    #   字节层写（铁律 079：文本模式会把 LF 翻成 CRLF）。四条自己 `_Tee` 落盘的判据
    #   也走这里 —— 只要那一份 run.txt 在盘上（`os.path.exists`），就在末尾补这一行。
    secs = time.time() - t0
    if os.path.exists(out):
        extra = ("\n--- run_gates 运行器实测（进程退出码，非被测件自报）: rc=%d  %.1fs  %s\n"
                 % (r.returncode, secs, f))
        with open(out, "rb") as fh:
            prev = fh.read().replace(b"\r\n", b"\n").rstrip(b"\n")
        with open(out, "wb") as fh:
            fh.write(prev + extra.encode("utf-8"))
    return (f, r.returncode, secs, note)


def run_cad_serial(fs):
    """CAD 档**串行**跑（AutoCAD 单实例）—— 整串占线程池里的**一个** worker。"""
    return [run_one(f) for f in fs]


cad = [f for f in names if tier_of(f) == "cad"]
others = [f for f in names if tier_of(f) != "cad"]

print("档位：%s ｜ 判据 %d 条 ｜ 并行度 %d（CAD 档串行占 1 个 worker）" %
      (",".join(sorted(want)), len(names), jobs))
print("-" * 78)

t_all = time.time()
results = {}
with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
    futs = {}
    if cad:
        futs[ex.submit(run_cad_serial, cad)] = "cad-serial"
    for f in others:
        futs[ex.submit(run_one, f)] = f
    for fu in cf.as_completed(futs):
        res = fu.result()
        # ★ 两种返回形状：CAD 那一串交回**列表**，其余单条交回**四元组** ⇒ 在这里归一，
        #   别让「串行任务」与「单条任务」在消费端长得不一样（第一版就是在这里 unpack 炸的）。
        if isinstance(res, tuple):
            res = [res]
        for f, rc, secs, note in res:
            results[f] = (rc, secs, note)
            with _lock:
                print("rc=%-3d %6.1fs  %-42s %s" % (rc, secs, f, note))

print("-" * 78)
print("墙钟合计 %.1fs（档位 %s）" % (time.time() - t_all, ",".join(sorted(want))))
print("\n===== 汇总（按 rc 降序、同 rc 按耗时降序）=====")
for f, (rc, secs, note) in sorted(results.items(), key=lambda z: (-z[1][0], -z[1][1])):
    print("  rc=%-3d %6.1fs  %s%s" % (rc, secs, "✗ " if rc else "  ", f))
n0 = sum(1 for rc, _, _ in results.values() if rc == 0)
print("  合 %d 条：rc=0 的有 %d 条" % (len(results), n0))

# ★ 把这一趟的**实测耗时**落盘。不落盘 ⇒ 档位表里的「≈ 几分钟」只能手打进 docstring，
#   那就成了同一个量的第二份副本（铁律 174）；页面读的是这份 json，不是 docstring。
#   ★ 件名以 `_` 开头 ⇒ 与 `_a0_tamper.json` 同族，消费端按「非判据件」滤掉。
led = {
    "spec": "每条判据**最近一次**实跑的实测耗时；页面/档位表的“≈分钟”**只许**引用这里",
    "runs": [{"tiers": sorted(want), "wall_s": round(time.time() - t_all, 1),
              "when": time.strftime("%Y-%m-%d %H:%M:%S")}],
    "rows": {},
}
for f, (rc, secs, _note) in results.items():
    led["rows"][gate_id(f[:-3])] = {"script": f, "tier": tier_of(f),
                                    "rc": rc, "secs": round(secs, 1),
                                    "when": time.strftime("%Y-%m-%d %H:%M:%S")}
# ★ **合并**而不是覆盖：`run_gates.py --dxf` 只跑 4 条，若整份盖掉，
#   上一趟 quick 那 6 条的读数就没了 ⇒ 页面会把「没跑过」和「跑过但没记」混成一个数
#   （铁律 197：量具分不开「正好 N」与「被截断」）。这里按**判据编号**逐条更新。
_lp = os.path.join(GOUT, "_ledger.json")
if os.path.exists(_lp):
    try:
        old = json.load(open(_lp, encoding="utf-8"))
    except Exception as e:                                          # noqa: BLE001
        print("★ 旧台账读不动（%s）⇒ 这一趟只记本趟：这一格的旧读数**丢了**，不是没有" % e)
        old = None
    if isinstance(old, dict) and isinstance(old.get("rows"), dict):
        old["rows"].update(led["rows"])
        old["runs"] = (old.get("runs") or [])[-19:] + led["runs"]
        led = old
with open(_lp, "w", encoding="utf-8") as fh:
    json.dump(led, fh, ensure_ascii=False, indent=1)

# ★ 2026-10-20：收口的 rc 也必须分三态（铁律 199）。
#   原来 `n0 == len(results) else 1` 把「有闸没量到（rc=4）」也报成 1 ——
#   于是 other 档「21 绿 + 1 没量到」读起来与「有闸红了」同形，看日志的人分不出
#   该不该去查件。现在：任何非 {0,4} 的 rc ⇒ 1；只有 4 ⇒ 4；全 0 ⇒ 0。
_nfail = sum(1 for rc, _, _ in results.values() if rc not in (0, 4))
_nskip = sum(1 for rc, _, _ in results.values() if rc == 4)
if _nfail:
    print("★ 本档 rc=1：%d 条量到不对（另有 %d 条没量到 —— 两者不是一回事）" % (_nfail, _nskip))
    sys.exit(1)
if _nskip:
    print("★ 本档 rc=4：%d 条没量到，其余 %d 条全绿 —— 「没量到」不算过，也不当红" % (_nskip, n0))
    sys.exit(4)
sys.exit(0)
