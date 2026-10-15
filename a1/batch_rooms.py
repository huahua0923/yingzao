# -*- coding: utf-8 -*-
"""A1：把房间台账抽取（`rooms.py`）扫过 dxf_output 全库，量**台账覆盖率**。

★ 这一步补的是 A1 第四个缺口：前面墙/柱/门都在量**几何**，而「房间 + 面积」是**人写的台账**
  —— 它是 §10.1「按列算的面积 vs 台账/图纸面积，逐层对账」的**参考侧**。链建不出房间多边形，
  这条对账就无从谈起；本尺先把**参考侧**建出来（模型侧**不假装做了**）。

★ 正对照（`--pos`）：指名 C109-十公寓（实测 141 房间号 = 141 面积文字，全配、全解析）
  ⇒ 必须抽出 ≥1 行且**配对数为 0（没有超距离的）**；抽不出 ⇒ 本尺对「确有台账的图」都不响，
  否定判词不算证据。

★ 量具盲区（必须声明）：
  ① 只扫 `--dir` 里的 *.dxf；只认 `rooms.*_LAYERS` 列出的层名 —— 台账画在别的层（如 `0`）全盲。
  ② **「抽出 N 行」≠「这 N 行对」**：配对是**近邻**，`TOL` 之内可能配错而无声（`rooms` 盲区②）；
     面积是**人写数**，本身可能写错。⇒ 本尺**只报覆盖率与配对数，不给「台账正确」结论**。
  ③ 分母一律写明；「某栋 0 行」只等于「层名对不上」，**不**等于「这栋没有房间台账」。
  ④ 参数（层名表/TOL）与 `rooms.py` 同源；改那边会改这里的数。

用法: python batch_rooms.py <dxf目录> [--json out.json] [--pos <dxf>]
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
import rooms as R


def one(path):
    try:
        rows, st = R.load_rooms(path)
    except Exception as e:
        return {"dxf": os.path.basename(path), "err": "READ:%s" % type(e).__name__}
    floors = sorted({r["floor"] for r in rows if r["floor"]})
    a2 = [r["area_m2"] for r in rows if r["area_m2"] is not None]
    st = dict(st)
    st.update({"n_floor": len(floors), "floors": floors,
               "area_sum_m2": round(sum(a2), 2) if a2 else None})
    return {"dxf": os.path.basename(path), "stats": st}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=r"D:\项目\gym3d\材料\dxf_output")
    ap.add_argument("--json", default=None)
    ap.add_argument("--pos", default=None, help="正对照 DXF（确知有台账，必须抽出 ≥1 行且无拒配）")
    a = ap.parse_args()

    if a.pos:
        r = one(a.pos)
        print("=== 正对照 ===")
        print("  件 :", os.path.basename(a.pos))
        if "err" in r:
            print("  ✗ 读失败:", r["err"]); return 1
        st = r["stats"]
        print("  房间号 %d / 面积文字 %d / 配到 %d / 拒配 %d / 非数值 %d / 层 %d"
              % (st["n_id"], st["n_area_text"], st["n_joined"], st["n_far"],
                 st["n_nonnum"], st["n_floor"]))
        if st["n_joined"] < 1:
            print("  ✗ 正对照未触发 ⇒ 本尺对「确有台账的图」都不响，否定判词不算证据（盲区③）")
            return 1
        print("  ✓ 正对照触发（确有台账的图抽出房间行）")

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
            st = r["stats"]
            mark = "✓" if st["n_joined"] > 0 else ("·" if st["n_id"] == 0 else "!")
            print("%3d %-42s %s 房间号%5d 配到%5d 拒配%4d 非数值%4d 层%2d" %
                  (i, r["dxf"][:42], mark, st["n_id"], st["n_joined"],
                   st["n_far"], st["n_nonnum"], st["n_floor"]))

    ok = [r for r in res if "err" not in r]
    if not ok:
        print("!! 全读失败 ⇒ 判据无意义"); return 3
    hit = [r for r in ok if r["stats"]["n_joined"] > 0]
    noid = [r for r in ok if r["stats"]["n_id"] == 0]
    print("\n===== 汇总（分母 %d 份）=====" % len(ok))
    print("读失败                : %d" % len([r for r in res if 'err' in r]))
    print("无房间号层(本尺全盲)  : %d" % len(noid))
    print("抽出房间行的栋        : %d  ← **台账覆盖率**（不是台账正确率，盲区②）" % len(hit))
    print("房间号总条数          : %d" % sum(r["stats"]["n_id"] for r in ok))
    print("配到面积的总行数      : %d" % sum(r["stats"]["n_joined"] for r in ok))
    print("拒配(超配对距离/无)   : %d" % sum(r["stats"]["n_far"] for r in ok))
    print("在范围内但非数值      : %d  ← `{露台}` 这类，如实记 None" % sum(r["stats"]["n_nonnum"] for r in ok))
    print("配到用途/单位         : %d / %d" % (sum(r["stats"]["n_use"] for r in ok),
                                              sum(r["stats"]["n_unit"] for r in ok)))
    print("行数 Top10            :")
    for r in sorted(ok, key=lambda x: -x["stats"]["n_joined"])[:10]:
        st = r["stats"]
        print("    %-42s %5d 行 / %5d 号 / %2d 层 / 合计 %s m²" %
              (r["dxf"][:42], st["n_joined"], st["n_id"], st["n_floor"], st["area_sum_m2"]))
    fl = collections.Counter()
    for r in ok:
        for f in r["stats"]["floors"]:
            fl[f] += 1
    print("层段分布(前15)        :", dict(fl.most_common(15)))
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": a.dir, "n": len(ok), "n_hit": len(hit),
                   "sum_id": sum(r["stats"]["n_id"] for r in ok),
                   "sum_joined": sum(r["stats"]["n_joined"] for r in ok),
                   "rows": res},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
