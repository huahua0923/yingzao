# -*- coding: utf-8 -*-
r"""**判据矩阵** —— 一次跑多栋楼 × 多条判据，把结果折成一张表。

为什么要有它（2026-10-19，用户「有错误可以直接在页面上指出修改，从哪个方向修改」）：
  闸原来是**一次量一栋（c006）**、判词只落在各自的 `run.txt` 里。66 栋重跑完之后
  「别的楼有没有问题」这个问题**没有尺子能回答**。本脚本只做编排：
    ① 按 bid 起子进程跑闸（闸自己经 `_verdict.paths()` 找件）；
    ② 读闸落的 verdict JSON（**没落 = 没量到**，不许当成 pass —— 铁律 199）；
    ③ 落 `gates/_out/matrix.json` + `matrix.html`。

用法::

    python -I gates/_runner.py --bids all
    python -I gates/_runner.py --bids c006 c005 --gates J-10.8-00,J-10.9-07
    python -I gates/_runner.py --bids all --jobs 2 --timeout 1200

退出码：0 全部 pass · 1 有 fail · 3 有「没量到」· 4 参数错
     ★ 三种状态分开：fail 与没量到**不许同形**（铁律 199）。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "_out")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(CDUT, "rebuild", "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

DEFAULT_GATES = ["J-10.8-00", "J-10.8-01", "J-10.8-04", "J-10.9-07"]


def _gate_path(gate):
    """闸名 → 文件。**只认唯一命中**；命中 0 或 >1 都报错（别猜）。"""
    hits = [f for f in os.listdir(HERE)
            if f.startswith(gate) and f.endswith(".py") and not f.startswith("_")]
    if len(hits) != 1:
        raise SystemExit("★ 闸名 %s 命中 %d 个文件：%s" % (gate, len(hits), hits))
    return os.path.join(HERE, hits[0])


def _all_bids():
    """有包的楼栋（`packs/cdut-main/<bid>/manifest.json` 在）。"""
    pdir = os.path.join(CDUT, "packs", "cdut-main")
    return sorted(d for d in os.listdir(pdir)
                  if os.path.exists(os.path.join(pdir, d, "manifest.json")))


def _run_one(gate, bid, timeout):
    gp = _gate_path(gate)
    env = dict(os.environ)
    env["CDUT_BUILDING"] = bid
    import building as B
    env["CDUT_REBUILD_ROOT"] = B.root_for(bid)
    t0 = datetime.datetime.now()
    try:
        p = subprocess.run([sys.executable, "-I", gp, "--bid", bid], cwd=CDUT, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        rc = p.returncode
        tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
        crashed = ""
    except subprocess.TimeoutExpired:
        rc, tail, crashed = -9, [""], "超时 %ds" % timeout
    jp = os.path.join(OUT, "%s.%s.json" % (gate, bid))
    cell = {"pass": None, "rc": rc, "red": None, "unmeasured": None,
            "run_txt": "", "crashed": crashed,
            "seconds": round((datetime.datetime.now() - t0).total_seconds(), 1)}
    if os.path.exists(jp) and os.path.getmtime(jp) >= t0.timestamp() - 1:
        with open(jp, encoding="utf-8") as f:
            v = json.load(f)
        cell.update({"pass": v.get("pass"), "red": v.get("counts", {}).get("red"),
                     "unmeasured": v.get("counts", {}).get("unmeasured"),
                     "run_txt": v.get("run_txt", "")})
    else:
        # ★ rc=0 但没落 verdict ≠ 通过；rc≠0 且没落 verdict = 闸自己崩了。
        cell["pass"] = None
        cell["note"] = "闸没落 verdict（%s）" % (crashed or "rc=%d" % rc)
    cell["tail"] = tail[0][:120] if tail else ""
    return cell


def _html(m, gates, bids):
    head = "".join("<th>%s</th>" % g for g in gates)
    rows = []
    for b in bids:
        tds = []
        for g in gates:
            c = m["cells"].get(g, {}).get(b)
            if not c:
                tds.append('<td class="na">—</td>')
            elif c["pass"] is True:
                tds.append('<td class="ok">✔</td>')
            elif c["pass"] is False:
                tds.append('<td class="bad">✗%s</td>' % (c.get("red") or ""))
            else:
                tds.append('<td class="unk" title="%s">?没量到</td>'
                           % (c.get("note") or c.get("crashed") or ""))
        rows.append("<tr><th>%s</th>%s</tr>" % (b, "".join(tds)))
    return ("<!doctype html><meta charset=utf-8><title>判据矩阵</title>"
            "<style>body{font:13px system-ui;margin:24px}"
            "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:3px 8px}"
            ".ok{background:#d7f5d7}.bad{background:#f7cfcf}.unk{background:#ffe9b8}"
            ".na{background:#eee;color:#888}</style>"
            "<h1>判据矩阵</h1><p>生成 %s ｜ 绿=过 红=判红 黄=没量到</p>"
            "<table><tr><th>楼栋</th>%s</tr>%s</table>"
            % (m["generated_at"], head, "".join(rows)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bids", nargs="+", default=["all"])
    ap.add_argument("--gates", default=",".join(DEFAULT_GATES))
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args(argv)

    bids = _all_bids() if a.bids == ["all"] else [b for b in a.bids if b != "all"]
    gates = [g.strip() for g in a.gates.split(",") if g.strip()]
    for g in gates:
        _gate_path(g)                      # 先验闸名，别跑到一半才发现拼错
    print("判据矩阵：%d 栋 × %d 条（并发 %d）" % (len(bids), len(gates), a.jobs))

    m = {"schema": "cdut3d-matrix/1",
         "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
         "gates": gates, "bids": bids, "cells": {g: {} for g in gates}}
    jobs = []
    with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        for g in gates:
            for b in bids:
                jobs.append((g, b, ex.submit(_run_one, g, b, a.timeout)))
        for g, b, f in jobs:
            c = f.result()
            m["cells"][g][b] = c
            sym = "✔" if c["pass"] is True else ("✗%s" % (c.get("red") or "")
                                                 if c["pass"] is False else "?")
            print("  %-7s %-9s %s  rc=%-4s red=%-4s un=%-4s %s"
                  % (b, g, sym, c["rc"], c.get("red"), c.get("unmeasured"),
                     c.get("note", "")[:40]))

    os.makedirs(OUT, exist_ok=True)
    jp = os.path.join(OUT, "matrix.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    hp = os.path.join(OUT, "matrix.html")
    with open(hp, "w", encoding="utf-8", newline="\n") as f:
        f.write(_html(m, gates, bids))

    n_ok = sum(1 for g in gates for b in bids if m["cells"][g][b]["pass"] is True)
    n_bad = sum(1 for g in gates for b in bids if m["cells"][g][b]["pass"] is False)
    n_unk = len(bids) * len(gates) - n_ok - n_bad
    print("\n==== 矩阵：%d 格 · pass %d · fail %d · 没量到 %d ===="
          % (len(bids) * len(gates), n_ok, n_bad, n_unk))
    print("写出:", jp)
    print("页面:", hp)
    if n_bad:
        return 1
    if n_unk:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
