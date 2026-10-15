# -*- coding: utf-8 -*-
"""A1：把通用洞口识别（`openings.py`）扫过 dxf_output 全库，量**门窗洞口的覆盖率**。

★ A1 第三个缺口（旧链 `build8:242` **主动剔掉** `$DorLib2D$` ⇒ 门一律不建）。本尺量：**105 份里
  有多少栋能识别出洞口几何**，并**分开报**「足迹块数」与「洞口簇数」（盲区④）。

★ 正对照（`--pos`）：指名一份**确知有门**的图（C109-十公寓 = 142 个人写门号，实测一一对应）
  ⇒ 必须识别出 ≥1 处；识别不出 ⇒ 本尺对「有门的图」都不响，否定判词不算证据（盲区②/⑤）。

★ 量具盲区（必须声明）：
  ① 只扫 `--dir` 里的 *.dxf；只认 `openings.OPEN_LAYERS` 四种墙层名（别的层全盲）。
  ② 「识别出洞口几何」≠「识别出的是门」——窗/柱/家具落在尺寸窗内一样算（`openings` 盲区⑤）；
     本尺**不给「门覆盖率」结论**，只给「洞口几何覆盖率」。门的那一条另有**外部量**尺
     （`check_doors_ext.py`，只用 C109 的人写门号）。**分母**一律写明。
  ③ 正对照只证明「尺子在确有门的图上会响」，**不给「漏了多少」**。
  ④ 参数（MINV/尺寸窗/弧半径窗）与 `openings.py` 同源；改那边会改这里的数。

用法: python batch_openings.py <dxf目录> [--json out.json] [--pos <dxf>]
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
import openings as O


def one(path):
    try:
        polys, layer_hit, hits = O.load_openings(path)
    except Exception as e:
        return {"dxf": os.path.basename(path), "err": "READ:%s" % type(e).__name__}
    nc, area = O.n_clusters(polys)
    unres = {k: v for k, v in hits.items() if k.startswith("UNRESOLVED:")}
    return {"dxf": os.path.basename(path), "layer_hit": layer_hit, "hits": dict(hits),
            "n_polys": len(polys), "n_clusters": nc, "area_m2": area / 1e6, "unresolved": unres}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=r"D:\项目\gym3d\材料\dxf_output")
    ap.add_argument("--json", default=None)
    ap.add_argument("--pos", default=None, help="正对照 DXF（确知有门，必须识别出 ≥1 处）")
    a = ap.parse_args()

    if a.pos:
        pr = one(a.pos)
        n = pr.get("n_clusters", 0) if "err" not in pr else -1
        print("=== 正对照 ===")
        print("  件 :", os.path.basename(a.pos))
        print("  洞口簇数 :", n, " 足迹", pr.get("n_polys"), " 实体:", pr.get("hits"), pr.get("err", ""))
        if n < 1:
            print("  ✗ 正对照未触发 ⇒ 本尺对「有门的图」都不响，否定判词不算证据（盲区③）")
            return 1
        print("  ✓ 正对照触发（确有门的图识别出洞口几何）")

    files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
    if not files:
        print("!! 目录无 *.dxf:", a.dir); return 2
    print("\n扫 %d 份 DXF ...\n" % len(files))
    res = []
    for i, f in enumerate(files, 1):
        r = one(f)
        res.append(r)
        if "err" in r:
            print("%3d %-42s !! %s" % (i, r["dxf"][:42], r["err"]))
        else:
            mark = "✓" if r["n_clusters"] > 0 else ("·" if not r["layer_hit"] else "!")
            print("%3d %-42s %s 墙层%d 簇%5d 足迹%5d" %
                  (i, r["dxf"][:42], mark, len(r["layer_hit"]), r["n_clusters"], r["n_polys"]))

    ok = [r for r in res if "err" not in r]
    if not ok:
        print("!! 全读失败 ⇒ 判据无意义"); return 3
    hit = [r for r in ok if r["n_clusters"] > 0]
    nolayer = [r for r in ok if not r["layer_hit"]]
    print("\n===== 汇总（分母 %d 份）=====" % len(ok))
    print("读失败               : %d" % len([r for r in res if 'err' in r]))
    print("无墙层(本尺全盲)     : %d" % len(nolayer))
    print("识别出洞口几何的栋   : %d  ← **洞口几何**覆盖率（不是门覆盖率，盲区②）" % len(hit))
    print("洞口簇总数           : %d" % sum(r["n_clusters"] for r in ok))
    print("足迹块总数           : %d" % sum(r["n_polys"] for r in ok))
    print("簇数 Top10            :")
    for r in sorted(ok, key=lambda x: -x["n_clusters"])[:10]:
        print("    %-42s %5d 簇 / %5d 足迹" % (r["dxf"][:42], r["n_clusters"], r["n_polys"]))
    unres = collections.Counter()
    for r in ok:
        for k, v in r["unresolved"].items():     # ★ 直接累加计数值，不展开成 range（会炸内存）
            unres[k] += v
    print("未决实体(不建)Top10  :", dict(unres.most_common(10)))
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": a.dir, "n": len(ok), "n_hit": len(hit),
                   "sum_clusters": sum(r["n_clusters"] for r in ok),
                   "sum_polys": sum(r["n_polys"] for r in ok), "rows": res},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
