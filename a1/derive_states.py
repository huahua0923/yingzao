# -*- coding: utf-8 -*-
"""从一次扫库 JSON 里**事后**推内容闸状态（不动扫库本身，省一次 17 分钟）。

`sweep4` 跑的是加 `n_real` 之前启动的那一版 ⇒ JSON 里有 `n_real` / `per_sheet_wall` 但没有
`plan_state`。本脚本按同一判据（墙段 ≥50 才算真平面图）补算，并把**两把尺子的分歧**单独列出来。

判词分三层，互不盖章：
  几何闸 `state`      : 几何上凑没凑出 ≥2 张同尺寸图幅的条带
  内容闸 `plan_state` : 这些图幅里**真有**几张带墙的平面图
  ⇒ 分歧件（几何 OK 但真图 <2）必须逐件报，不能并进 OK 的总数里。
"""
import collections
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

MIN_SEG = 50
SWEEP = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\项目\cdut3d\a1\_out\wall_sweep4.json")
OUT = SWEEP.with_name(SWEEP.stem + "_planstate.json")


def plan_state(n):
    return "PLANS_OK" if n >= 2 else ("SINGLE" if n == 1 else "NO_PLAN")


def main():
    d = json.loads(SWEEP.read_text(encoding="utf-8"))
    rows = d["rows"]
    print("读:", SWEEP.name, " 共", len(rows), "份")

    geo = collections.Counter(r["state"] for r in rows)
    print("\n=== 几何闸 state ===")
    for k, v in geo.most_common():
        print("  %-12s %d" % (k, v))

    ok = [r for r in rows if r["state"] == "OK"]
    ps = collections.Counter(plan_state(r["n_real"]) for r in ok)
    print("\n=== 内容闸 plan_state（仅几何 OK 的 %d 份）===" % len(ok))
    for k, v in ps.most_common():
        print("  %-10s %d" % (k, v))

    nseg = sum(r["n_real"] for r in ok)
    nsh = sum(r["n_sheets"] for r in ok)
    print("\n  真平面图 %d 张 / 图幅 %d 张（空模板框 %d 张，占 %.1f%%）"
          % (nseg, nsh, nsh - nseg, 100.0 * (nsh - nseg) / max(nsh, 1)))

    dis = [r for r in ok if plan_state(r["n_real"]) != "PLANS_OK"]
    print("\n=== ★ 分歧件：几何 OK 但内容闸不过（%d 份）===" % len(dis))
    for r in sorted(dis, key=lambda r: r["n_real"]):
        print("  %-40s %-9s 图幅%2d 真%d 逐张墙段%s"
              % (r["dxf"][:40], plan_state(r["n_real"]), r["n_sheets"], r["n_real"],
                 sorted(r["per_sheet_wall"], reverse=True)[:6]))

    # 覆盖不满的，也要看它们是不是真图引起的
    cov_lt = [r for r in ok if not r.get("cov_all100")]
    print("\n=== 覆盖不满（%d 份）===" % len(cov_lt))
    for r in sorted(cov_lt, key=lambda r: (r["cov_min"] is None, r["cov_min"])):
        print("  %-40s 覆盖min %8s 真%2d/%d 未量到%d"
              % (r["dxf"][:40], "—" if r["cov_min"] is None else "%.2f%%" % r["cov_min"],
                 r["n_real"], r["n_sheets"], r["n_unmeasured"]))

    OUT.write_text(json.dumps(
        {"src": str(SWEEP), "geo_states": dict(geo), "plan_states": dict(ps),
         "n_real_total": nseg, "n_sheets_total": nsh, "disagree": [r["dxf"] for r in dis]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n写出:", OUT)
    return 0


sys.exit(main())
