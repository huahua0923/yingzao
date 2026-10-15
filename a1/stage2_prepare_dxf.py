# -*- coding: utf-8 -*-
"""**stage 2 的一步**：把墙层多段线闭合，产出 `out.dxf` 交给下游消费（§7.9.4 结论 2 / §7.10 CAD 行）。

为什么要有这一层（而不是让下游直接调 `tools/cad_close_walls.py`）：
  · `cad_close_walls` 只管**搬运**（起 AutoCAD、写 .scr、回读）；
  · **「接进链」的判据在别处** —— 是「下游拿到的那份 DXF **确实变了、且不是坏的**」。
    这一步就把后半句做实：**产出件必须当场上游载入一次**（`load_walls_and_cols`），
    载不动就返回六态里的 `NO_ARTIFACT`，**不让下游拿到一个「跑通了但读不进」的 dxf**。
    （铁律 199：`rc=0` 且无可用产出物 = 静默成功，最危险的一类。）

★ 为什么不改源件：源件在 `gym3d/材料/dxf_output/`，是**别的项目的地基**。
  本步一律**复制到自己目录里**改，产出 `out.dxf`，源件字节不动。

★ 本步**不判对错**（对错在 `gates/J-07.9.4-02_wallclose_downstream.py`）。

用法（库）:  from stage2_prepare_dxf import prepare;  r = prepare(src, outdir)
用法（命令行）: python a1/stage2_prepare_dxf.py <src.dxf> <outdir> [--tol 480] [--prefix 4.2]
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import generic_wall as GW      # noqa: E402
import cad_close_walls as CC   # noqa: E402

# 六态同上（`chain/chain.py`）；本步只可能产出这四态
OK = CC.OK
FAIL_RC = CC.FAIL_RC
TIMEOUT = CC.TIMEOUT
NO_ARTIFACT = CC.NO_ARTIFACT
SKIP = CC.SKIP


def prepare(src_dxf, outdir, tol_mm=CC.DEFAULT_TOL_MM, prefix="4.2"):
    """跑一步。成功时返回 dict，**一定带 `out_dxf`（下游要消费的路径）**与 `downstream`（载入实测）。

    返回的 `state` 是六态词汇；`downstream` 只在 `state == OK` 时非空。
    """
    r = CC.close_walls(src_dxf, outdir, tol_mm=tol_mm, prefix=prefix)
    if r["state"] != OK:
        return r
    # ★ 产出件必须**当场被下游载入一次** —— 这一步才是「接进链」与「只跑了个 exe」的分界
    try:
        segs, cols, _label = GW.load_walls_and_cols(r["out_dxf"])
        quads, residual = GW.wire(segs)
    except Exception as e:
        return {**r, "state": NO_ARTIFACT,
                "detail": "out.dxf 产出了但**下游载不动**：%s: %s"
                          % (type(e).__name__, str(e)[:120])}
    r["out_dxf"] = os.path.abspath(r["out_dxf"])
    r["downstream"] = {"n_segs": len(segs), "n_quads": len(quads),
                       "resid_len": round(sum(x.length for x in residual), 3),
                       "quad_area": round(sum(q.area for q in quads), 3),
                       "n_cols": len(cols)}
    return r


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("outdir")
    ap.add_argument("--tol", type=float, default=CC.DEFAULT_TOL_MM)
    ap.add_argument("--prefix", default="4.2")
    a = ap.parse_args()
    r = prepare(a.src, a.outdir, a.tol, a.prefix)
    print("state=%s  rc=%s  %ss  点名 %s 条" % (r["state"], r.get("rc"), r.get("secs"), r.get("picked")))
    if r.get("before"):
        print("  闭合前:", r["before"], "→ 闭合后:", r.get("after", "没量到"))
    if r.get("downstream"):
        print("  下游载入:", r["downstream"])
        print("  ★ 供下游消费的产出件:", r["out_dxf"])
    if r["state"] != OK:
        print("  detail:", r.get("detail"))
    return 0 if r["state"] == OK else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
