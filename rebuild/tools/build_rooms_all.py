# -*- coding: utf-8 -*-
"""批量跑 `build_rooms.py`：一栋一个子进程，**逐栋如实记 rc / 耗时 / 房间数**。

为什么要有这个批跑器（不是循环一行 shell）：
  · `build_rooms.py` 的数据根靠 `CDUT_BUILDING` 选（`building.ROOT` 已跟随它推导）；
    在 shell 里裸循环很容易漏掉环境变量 ⇒ 名义跑 c072、实际跑 c006（2026-10-19 实测过一次）。
  · 单栋失败必须**单独记 rc 与末行**，不许整批同生共死，也不许把「没跑成」写成「0 间」。
  · 与 `run_batch.py` 的分工：那个跑**整链**（run_chain_bid）；本件只跑房间识别这一件。

落盘：`rebuild/构件库/房间_批量.json`
    {"生成": ISO, "合计": {跑, 成, 败, 房间, 秒, 失败清单}, "楼栋": {bid: {rc, 秒, 房间, 末行, 状态}}}

用法：
    python -X utf8 -I rebuild/tools/build_rooms_all.py            # 所有还没有房间表的楼
    python -X utf8 -I rebuild/tools/build_rooms_all.py --重跑      # 全部重跑（含已有的）
    python -X utf8 -I rebuild/tools/build_rooms_all.py --只 c072 c065
    python -X utf8 -I rebuild/tools/build_rooms_all.py --并行 4
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REBUILD = os.path.dirname(HERE)
LIB = os.path.join(REBUILD, "构件库")
PROFILE = os.path.join(LIB, "楼栋.json")
OUT = os.path.join(LIB, "房间_批量.json")
TOOL = os.path.join(HERE, "build_rooms.py")

sys.path.insert(0, HERE)
import building as B  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _dump(p, obj):
    b = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    tmp = p + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(b)
    os.replace(tmp, p)


def _bids():
    return sorted((_load(PROFILE, {}) or {}).keys() - {"schema", "说明"})


def _table(bid):
    return os.path.join(B.root_for(bid), "02_recognize", "房间表.json")


def _count(bid):
    d = _load(_table(bid))
    if not isinstance(d, dict) or not isinstance(d.get("层"), list):
        return None
    return sum(len(f.get("房间") or []) for f in d["层"])


def _run_one(bid, timeout=1800):
    t0 = time.time()
    env = dict(os.environ)
    env["CDUT_BUILDING"] = bid
    env.pop("CDUT_REBUILD_ROOT", None)          # 让 building.ROOT 跟 BID 走
    try:
        p = subprocess.run([sys.executable, "-X", "utf8", "-I", TOOL],
                           cwd=os.path.dirname(REBUILD), env=env, timeout=timeout,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (p.stdout or "") + (p.stderr or "")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        return {"rc": -9, "秒": round(time.time() - t0, 1), "房间": None,
                "末行": "超时 %d s" % timeout, "状态": "超时"}
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    last = lines[-1] if lines else ""
    n = _count(bid) if rc == 0 else None
    if rc != 0:
        st = "失败"
    elif n is None:
        st = "成了但读不到表"                   # ★ 不许读成「0 间」
    elif n == 0:
        st = "表在、0 间"
    else:
        st = "成"
    return {"rc": rc, "秒": round(time.time() - t0, 1), "房间": n,
            "末行": last[-300:], "状态": st}


def main(argv):
    only = None
    if "--只" in argv:
        i = argv.index("--只") + 1
        only = []
        while i < len(argv) and not argv[i].startswith("--"):
            only.append(argv[i]); i += 1
    rerun = "--重跑" in argv
    par = 4
    if "--并行" in argv:
        par = max(1, int(argv[argv.index("--并行") + 1]))

    bids = only if only else _bids()
    if not rerun and not only:
        bids = [b for b in bids if not os.path.isfile(_table(b))]

    print("批跑 build_rooms：%d 栋，并行 %d" % (len(bids), par))
    res = {"生成": _now(), "楼栋": {}}
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=par) as ex:
        futs = {ex.submit(_run_one, b): b for b in bids}
        for k, f in enumerate(cf.as_completed(futs), 1):
            b = futs[f]
            try:
                r = f.result()
            except Exception as e:                       # noqa: BLE001
                r = {"rc": -1, "秒": 0, "房间": None, "末行": repr(e), "状态": "崩了"}
            res["楼栋"][b] = r
            print("[%d/%d] %-8s %-8s rc=%-3d %6.1fs 房间=%s"
                  % (k, len(bids), b, r["状态"], r["rc"], r["秒"],
                     "—" if r["房间"] is None else r["房间"]))

    ok = [b for b, r in res["楼栋"].items() if r["rc"] == 0]
    bad = [b for b, r in res["楼栋"].items() if r["rc"] != 0]
    rooms = sum((r["房间"] or 0) for r in res["楼栋"].values())
    res["合计"] = {"跑": len(bids), "成": len(ok), "败": len(bad),
                    "房间": rooms, "秒": round(time.time() - t0, 1),
                    "失败清单": bad}
    _dump(OUT, res)
    print("合计：成 %d / 败 %d / 房间 %d / %.0f s ⇒ %s"
          % (len(ok), len(bad), rooms, time.time() - t0, OUT))
    if bad:
        print("  失败：" + " ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
