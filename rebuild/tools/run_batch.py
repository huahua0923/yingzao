# -*- coding: utf-8 -*-
r"""**一批楼栋并行跑整链**，一栋一份日志，跑完打一张读数表。

为什么要有它（2026-10-17）：剩下 60 多栋楼，逐栋 `run_chain_bid.py` 要人守着；
但并行不是把 `run_chain_bid.py` 塞进线程池就行 —— 每栋楼的暂存区必须分开，
否则 FreeCAD 侧互相冲掉（见 `run_chain_bid.py` 里 `CDUT_FC_STAGE` 那段）。

调用方 ：没有人 `import` 它 —— 命令行驱动，`python -I rebuild/tools/run_batch.py <bid...>`；
         它自己按每个 bid 起一个 `rebuild/tools/run_chain_bid.py <bid>` 子进程。
读写的件：只写日志 `_scratch/<bid>_batch.log`；读 `packs/cdut-main/<bid>/manifest.json`
         的 mtime 与字节数（判「包是不是这一趟写的」），不写任何数据件。

判词口径（铁律 199：rc 与「真干成」不许同形）：
  · `rc` 只说明**进程**怎么了；`件` 一栏另看：包目录里的 `manifest.json` 在不在、是不是这一趟写的。
  · 一栋楼三态：`ok`（rc=0 且包是这一趟写的）/ `rc=N`（进程失败）/ `无件`（rc=0 但包没更新）。

用法：
    python -I rebuild/tools/run_batch.py c009 c022 c025 --jobs 3
    python -I rebuild/tools/run_batch.py --from 建件 c009 c022     # 透传给 run_chain_bid.py
    python -I rebuild/tools/run_batch.py --dry c009 c022

退出码：0 全部 ok · 4 有楼栋不是 ok
"""
from __future__ import annotations

import concurrent.futures as cf
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PASSTHROUGH = ("--from", "--to")


def _pack_manifest(bid):
    return os.path.join(CDUT, "packs", "cdut-main", bid, "manifest.json")


def _run_one(bid, extra, t0):
    logp = os.path.join(CDUT, "过程/_scratch", "%s_batch.log" % bid)
    with open(logp, "w", encoding="utf-8", newline="\n") as log:
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "run_chain_bid.py"), bid]
                           + extra, cwd=HERE, env=dict(os.environ),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        log.write(p.stdout or "")
        if p.stderr.strip():
            log.write("\n---- stderr ----\n" + p.stderr[-8000:] + "\n")
    man = _pack_manifest(bid)
    mt = os.path.getmtime(man) if os.path.exists(man) else 0
    if p.returncode != 0:
        state = "rc=%d" % p.returncode
    elif mt < t0:
        # rc=0 但包没被这一趟写过：与「跑成了」不许同形
        state = "无件"
    else:
        state = "ok"
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    # ★ 2026-10-17：原来报的是 `manifest.json` 的字节数 —— 那是几百字节，印出来是 `0.0 MB`，
    #   看着像「包是空的」。要量的是**包目录**的字节。
    tot = 0
    pdir = os.path.dirname(man)
    if mt:
        for dp, _dn, fns in os.walk(pdir):
            for fn in fns:
                try:
                    tot += os.path.getsize(os.path.join(dp, fn))
                except OSError:
                    pass
    return {"bid": bid, "state": state, "rc": p.returncode, "log": logp,
            "tail": lines[-1] if lines else "", "size": tot}


def main(argv):
    dry = "--dry" in argv
    jobs = 3
    if "--jobs" in argv:
        jobs = int(argv[argv.index("--jobs") + 1])
    extra = []
    for flag in PASSTHROUGH:
        if flag in argv:
            extra += [flag, argv[argv.index(flag) + 1]]
    bids = [a for a in argv if not a.startswith("--")]
    bids = [b for b in bids if b not in extra and not b.isdigit()]
    if not bids:
        print(__doc__)
        return 2
    if dry:
        print("将跑 %d 栋（并发 %d）：%s" % (len(bids), jobs, " ".join(bids)))
        for b in bids:
            print("  python -I rebuild/tools/run_chain_bid.py %s %s" % (b, " ".join(extra)))
        return 0

    t0 = time.time()
    rows = []
    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {ex.submit(_run_one, b, extra, t0): b for b in bids}
        for f in cf.as_completed(futs):
            r = f.result()
            rows.append(r)
            print("  %-6s %-5s rc=%-3d 包 %6.1f MB  %s"
                  % (r["bid"], r["state"], r["rc"], r["size"] / 1048576.0, r["tail"][:70]))

    rows.sort(key=lambda r: bids.index(r["bid"]))
    print("\n==== 批读数（%d 栋 · %.1f min）====" % (len(rows), (time.time() - t0) / 60.0))
    for r in rows:
        print("%-6s %-5s %s" % (r["bid"], r["state"], r["log"]))
    bad = [r for r in rows if r["state"] != "ok"]
    print("ok %d / 共 %d" % (len(rows) - len(bad), len(rows)))
    return 0 if not bad else 4


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
