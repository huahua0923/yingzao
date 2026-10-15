# -*- coding: utf-8 -*-
"""A1：把 sheet_grid 这把尺子扫过 dxf_output 全库，量**覆盖**——有多少楼的图幅能被自动定位。

用法: python batch_grid.py <dxf目录> [--json out.json]
输出一行一栋 + 末尾汇总（覆盖数 / 落进盲区的数 / 各自的尺寸）。
"""
import sys
import os
import json
import glob
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sheet_grid as SG


def one(path):
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        return {"dxf": os.path.basename(path), "err": "READ:%s" % type(e).__name__}
    msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    if not layer:
        return {"dxf": os.path.basename(path), "err": "NO_FRAME_LAYER"}
    frames = SG.collect_frames(msp, layer)
    sheets = SG.merge_pairs(frames)
    modal, std, others = SG.classify(sheets)
    cols = len({s["col"] for s in std})
    rows = max((s["row"] + 1 for s in std), default=0)
    return {"dxf": os.path.basename(path), "layer": layer,
            "n_frames": len(frames), "n_sheets": len(sheets),
            "modal": modal, "n_std": len(std), "n_other": len(others),
            "cols": cols, "max_rows": rows}


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else r"D:\项目\gym3d\材料\dxf_output"
    out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    files = sorted(glob.glob(os.path.join(d, "*.dxf")))
    print("扫 %d 份 DXF ...\n" % len(files))
    res = []
    for i, f in enumerate(files, 1):
        r = one(f)
        res.append(r)
        nm = r["dxf"]
        if "err" in r:
            print("%3d %-46s !! %s" % (i, nm[:46], r["err"]))
        else:
            ok = "✓" if r["n_std"] >= 2 else "·"
            print("%3d %-46s %s 图幅%2d 标准%2d(%dx%d) 其它%2d"
                  % (i, nm[:46], ok, r["n_sheets"], r["n_std"],
                     r["cols"], r["max_rows"], r["n_other"]))
    # 汇总
    good = [r for r in res if "err" not in r and r["n_std"] >= 2]
    errs = [r for r in res if "err" in r]
    weak = [r for r in res if "err" not in r and r["n_std"] < 2]
    print("\n===== 汇总 =====")
    print("总数        : %d" % len(res))
    print("定位到网格  : %d  (%.1f%%)" % (len(good), 100.0 * len(good) / max(len(res), 1)))
    print("未成网格    : %d" % len(weak))
    print("读/层失败   : %d" % len(errs))
    mod = collections.Counter(str(r.get("modal")) for r in good)
    print("命中尺寸分布:", dict(mod.most_common(6)))
    if out:
        p = os.path.dirname(out)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": d, "n": len(res), "n_grid": len(good), "n_weak": len(weak),
                   "n_err": len(errs), "rows": res}, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("写出:", out)
    return 0


sys.exit(main())
