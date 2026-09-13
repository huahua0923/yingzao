# -*- coding: utf-8 -*-
r"""全库 SU 分层规格闸门普查（唯一所有者，产物 `_scratch/_qa_selfint/fleet_census_*.txt`）。

做什么：对 `data/buildings/` 下**每个有 floors/ 的栋**跑一遍
`python backend/modeling/su_spec_floors_fleet.py <name> -o _scratch/su_jobs/_<name>_floors_spec.json`，
记 `rc`（0 过 / 1 不过）与不过时的验收原文，按栋名排序列出。

三条约定：
  · `-o` 走**固定路径**（`_scratch/su_jobs/_<name>_floors_spec.json`）—— `name` 字段派生自
    `-o` 文件名，路径一变产物就不可比（README 铁律 ⑮）；本脚本不改这个路径。
  · **并行**跑（默认 4 路）：每栋写自己的 `-o`，互不撞；`data/` 全程只读。
  · 输出格式与 2026-09-13 之前那份普查逐行同构（`<name> rc=<n>`），便于两批直接对账。

理化楼（`lihua`）不在本普查内 —— 它在 `data/floors` 不在 `data/buildings` 下，另有
**逐字节复现门**（sha256 `c67ba3e8a19a…`）单独看着它。

用法：
  python _scratch/_su_fleet_census.py                      # 全库，4 路并行
  python _scratch/_su_fleet_census.py c103 ny27 --jobs 2   # 只看几栋
"""
import argparse
import concurrent.futures as cf
import io
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"D:\gym3d"
B = os.path.join(ROOT, "data", "buildings")
FLEET = os.path.join(ROOT, "backend", "modeling", "su_spec_floors_fleet.py")
OUTDIR = os.path.join(ROOT, "_scratch", "su_jobs")
REPORT = os.path.join(ROOT, "_scratch", "_qa_selfint", "fleet_census_after_c103.txt")


def spec_out(name):
    """★ 固定输出路径（铁律 ⑮）—— 不要参数化，改了就不与原普查可比。"""
    return os.path.join(OUTDIR, "_%s_floors_spec.json" % name)


def run_one(name):
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, FLEET, name, "-o", spec_out(name)],
                           capture_output=True, timeout=3600)
        rc, txt = p.returncode, p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return name, None, "超时（3600s）", time.time() - t0
    # ★ 只在 rc!=0 时收失败原文：rc=0 的栋也会印「✗ F1 楼板 10/1」这类**放宽提示**
    #   （多块楼板是交付几何本来如此），抓进来会让人把通过当成没通过。
    bad = [] if rc == 0 else [ln.strip() for ln in (txt + "\n" + err).splitlines()
                              if ("验收不通过" in ln or "✗" in ln)]
    return name, rc, "\n".join(bad[:4]), time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()

    names = a.names or sorted(n for n in os.listdir(B)
                              if os.path.isdir(os.path.join(B, n, "floors")))
    print("=== 全库 SU 规格闸门普查（%d 栋，%d 路并行）===" % (len(names), a.jobs))
    res = {}
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for name, rc, why, dt in ex.map(run_one, names):
            res[name] = (rc, why, dt)
            print("  %-6s rc=%s  %5.1fs  %s" % (name, rc, dt, why.splitlines()[0] if why else ""))
    ok = [n for n in names if res[n][0] == 0]
    print("\n通过 %d / %d；不过：%s"
          % (len(ok), len(names), ", ".join(n for n in names if res[n][0] != 0) or "无"))
    print("总墙钟 %.1fs" % (time.time() - t0))

    with io.open(REPORT, "w", encoding="utf-8") as f:
        for n in names:
            f.write("%s rc=%s\n" % (n, res[n][0]))
        f.write("\n# 通过 %d / %d\n" % (len(ok), len(names)))
        for n in names:
            if res[n][1]:
                f.write("\n=== %s ===\n%s\n" % (n, res[n][1]))
    print("报告：%s" % REPORT)
    return 0 if len(ok) == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
