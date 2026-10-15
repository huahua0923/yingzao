# -*- coding: utf-8 -*-
"""A1：把通用柱加载（`cols.py`）扫过 dxf_output 全库，量**柱的覆盖率**。

★ 这是 A1 的第二个缺口（旧链只认 INSERT 块 ⇒ 覆盖 1/105）。本尺量：**105 份里有多少栋能建出柱**。

用法: python batch_cols.py <dxf目录> [--json out.json]
     [--pos <dxf>]   正对照：指名一份**确知有柱**的图，它必须建出 ≥1 块；建不出 ⇒ 判据没分辨力。

★ 量具盲区（必须声明）：
  ① 只按 `cols.COL_LAYERS` 的图层名过滤；柱画在别名外的层 ⇒ 全盲（「没找到」≠「没有」）。
  ② 报的是「建出几块足迹」不是「是不是柱」；LINE/ARC 画的柱**一律算没建出**（`unresolved` 列如实记）。
  ③ 只覆盖 `--dir` 里的 *.dxf；目录外不算。
  ④ **正对照给不出「漏了多少」**，只证明「这把尺在有柱的图上确实会响」。
"""
import sys
import os
import json
import glob
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cols as C


def one(path):
    try:
        polys, layer_hit, hits = C.load_cols(path)
    except Exception as e:
        return {"dxf": os.path.basename(path), "err": "READ:%s" % type(e).__name__}
    unres = {k: v for k, v in hits.items() if k.startswith("UNRESOLVED:")}
    return {"dxf": os.path.basename(path), "layer_hit": layer_hit,
            "n_polys": len(polys), "hits": dict(hits), "unresolved": unres}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=r"D:\项目\gym3d\材料\dxf_output")
    ap.add_argument("--json", default=None)
    ap.add_argument("--pos", default=None, help="正对照 DXF（确知有柱，必须建出 ≥1 块）")
    a = ap.parse_args()

    # ---- 正对照：先跑。建不出柱 ⇒ 尺子没分辨力，直接判失败（不往下看大面积统计） ----
    if a.pos:
        pr = one(a.pos)
        n = pr.get("n_polys", 0) if "err" not in pr else -1
        print("=== 正对照 ===")
        print("  件 :", os.path.basename(a.pos))
        print("  建出柱块 :", n, " 实体:", pr.get("hits"), " 层:", pr.get("layer_hit"), pr.get("err", ""))
        if n < 1:
            print("  ✗ 正对照未触发 ⇒ 本尺对「有柱的图」都不响，否定判词不算证据（盲区④）")
            return 1
        print("  ✓ 正对照触发（有柱的图确实建出柱）")

    files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
    if not files:
        print("!! 目录里没有 *.dxf:", a.dir)
        return 2
    print("\n扫 %d 份 DXF ...\n" % len(files))
    res = []
    for i, f in enumerate(files, 1):
        r = one(f)
        res.append(r)
        nm = r["dxf"]
        if "err" in r:
            print("%3d %-44s !! %s" % (i, nm[:44], r["err"]))
        else:
            mark = "✓" if r["n_polys"] > 0 else ("·" if not r["layer_hit"] else "!")
            print("%3d %-44s %s 层[%s] 柱块%4d  %s"
                  % (i, nm[:44], mark, ",".join(r["layer_hit"]) or "无",
                     r["n_polys"], r["unresolved"] or ""))

    # ---- 非空断言（遍历型判据先断言非空，见反模式「空集合恒绿」） ----
    ok = [r for r in res if "err" not in r]
    if not ok:
        print("!! 全部读失败 ⇒ 判据无意义")
        return 3

    built = [r for r in ok if r["n_polys"] > 0]
    haslay = [r for r in ok if r["layer_hit"]]
    nolay = [r for r in ok if not r["layer_hit"]]
    failed = [r for r in haslay if r["n_polys"] == 0]
    errs = [r for r in res if "err" in r]

    print("\n===== 汇总 =====")
    print("总数            : %d" % len(res))
    print("读失败          : %d" % len(errs))
    print("无柱层(全盲)    : %d" % len(nolay))
    print("有柱层          : %d" % len(haslay))
    print("  └ 建出柱 ≥1块 : %d  ← 通用柱覆盖率" % len(built))
    print("  └ 有层但建不出: %d" % len(failed))
    if failed:
        print("    ★ 有柱层却建不出（真缺口，逐张看画法）:")
        for r in failed[:20]:
            print("      %-44s %s" % (r["dxf"][:44], r["hits"]))
    lay = collections.Counter(l for r in ok for l in r["layer_hit"])
    print("命中柱层名分布  :", dict(lay.most_common()))
    tot_polys = sum(r["n_polys"] for r in ok)
    print("全库柱块总数    : %d" % tot_polys)
    unres = collections.Counter(k for r in ok for k in r["unresolved"])
    if unres:
        print("未决画法(不建)  :", dict(unres.most_common()))

    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": a.dir, "n": len(res), "n_built": len(built),
                   "n_nolayer": len(nolay), "n_haslayer": len(haslay),
                   "n_failed": len(failed), "rows": res},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
