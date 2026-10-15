# -*- coding: utf-8 -*-
"""用**不依赖 gridify 的**另一条规则，直接量图幅排布 —— 破掉上一版的自证循环。

上一版（adjudge_nogrid.py）拿 `sheet_grid.gridify` 去判 `sheet_grid.classify` 的落空，
**两条用的是同一套列规则** ⇒ 那是在用坏尺子量坏尺子：`gridify` 只认「X 相交成列、且每列 ≥2」，
凡**单行排布**（N 张同尺寸、X 各不相交、Y 相同）在它眼里就是 N 个「1 张的列」⇒ 全被否 ⇒ 恒报「全落单」。
（同族铁律 192：参照物必须与被测件同作用域，用被测规则去证被测规则等于没证。）

本脚本改用**几何**直接量：对「最大同尺寸组」逐对判
  · 沿 X 分开（X 不重叠）而 Y 重合 ⇒ **同一行**
  · 沿 Y 分开（Y 不重叠）而 X 重合 ⇒ **同一列**
  · 两者都分开 ⇒ **棋盘/散点**
并给出「行数 × 列数」，与 gridify 无关。
"""
import collections
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
import sheet_grid as SG                                    # noqa: E402
import ezdxf                                               # noqa: E402

SRC = Path(r"D:\项目\gym3d\材料\dxf_output")
SWEEP = Path(r"D:\项目\cdut3d\a1\_out\wall_sweep2.json")
OUT = Path(r"D:\项目\cdut3d\a1\_out\layout_adjudged.json")


def xov(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def yov(a, b):
    return max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def layout_of(grp):
    """把一组同尺寸图幅按几何分行分列（与 gridify 无关）。"""
    rows, cols = [], []
    for s in sorted(grp, key=lambda s: -s["bbox"][3]):        # 从上到下
        b = s["bbox"]
        for r in rows:
            if yov(b, r["box"]) > 0.5 * min(b[3] - b[1], r["box"][3] - r["box"][1]):
                r["box"] = (min(r["box"][0], b[0]), min(r["box"][1], b[1]),
                            max(r["box"][2], b[2]), max(r["box"][3], b[3]))
                r["m"].append(s); break
        else:
            rows.append({"box": b, "m": [s]})
    for s in sorted(grp, key=lambda s: s["bbox"][0]):          # 从左到右
        b = s["bbox"]
        for c in cols:
            if xov(b, c["box"]) > 0.5 * min(b[2] - b[0], c["box"][2] - c["box"][0]):
                c["box"] = (min(c["box"][0], b[0]), min(c["box"][1], b[1]),
                            max(c["box"][2], b[2]), max(c["box"][3], b[3]))
                c["m"].append(s); break
        else:
            cols.append({"box": b, "m": [s]})
    return rows, cols


def diagnose(path):
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    if not layer:
        return {"verdict": "①无图框层", "n_frames": 0, "n_sheets": 0}
    frames = SG.collect_frames(msp, layer)
    sheets = SG.merge_pairs(frames)
    by = collections.defaultdict(list)
    for s in sheets:
        by[(round(s["bbox"][2] - s["bbox"][0]), round(s["bbox"][3] - s["bbox"][1]))].append(s)
    if not by:
        return {"layer": layer, "n_frames": len(frames), "n_sheets": 0, "verdict": "①无图幅"}
    k, grp = max(by.items(), key=lambda kv: len(kv[1]))
    rows, cols = layout_of(grp)
    nr, nc = len(rows), len(cols)
    multi = (len(grp) >= 3) and (nr >= 2 or nc >= 2)
    # 单行/单列也算网格 —— 这就是 gridify 看不见的那一类
    shape = "%d 行 × %d 列" % (nr, nc)
    single = nr * nc == len(grp)
    if not multi:
        v = "②真散图"
    elif single and (nr == 1 or nc == 1):
        v = "③单行/单列网格"          # ← gridify 必否、几何上是规整网格
    else:
        v = "④多行多列网格"
    return {"layer": layer, "n_frames": len(frames), "n_sheets": len(sheets),
            "grp_size": "%.0fx%.0f" % k, "n_grp": len(grp), "shape": shape,
            "rows": nr, "cols": nc, "verdict": v,
            "row_sizes": [len(r["m"]) for r in rows], "col_sizes": [len(c["m"]) for c in cols]}


def main():
    sw = json.loads(SWEEP.read_text(encoding="utf-8"))
    ng = [r["dxf"] for r in sw["rows"] if r["state"] == "NO_GRID"]
    res, tally = {}, collections.Counter()
    print("NO_GRID %d 张 —— 用几何直接量排布（不碰 gridify）：\n" % len(ng))
    for name in ng:
        try:
            v = diagnose(SRC / name)
        except Exception as e:                                # noqa: BLE001
            v = {"verdict": "!!异常", "err": "%s: %s" % (type(e).__name__, e)}
        res[name] = v
        tally[v["verdict"]] += 1
        print("  %-30s %-14s 图幅%3d  同尺寸组 %2d 张  %-11s 行内%s 列内%s"
              % (name, v["verdict"], v.get("n_sheets", -1), v.get("n_grp", -1),
                 v.get("shape", "-"), v.get("row_sizes"), v.get("col_sizes")))

    print("\n=== 正对照 C006（真 2×6 网格）===")
    c = diagnose(SRC / "C006-第六教学楼（逸夫楼）.dxf")
    print("  C006 %s  图幅%d  同尺寸组 %d 张  %s  行内%s 列内%s"
          % (c["verdict"], c["n_sheets"], c.get("n_grp", -1), c.get("shape"),
             c.get("row_sizes"), c.get("col_sizes")))
    ctrl_ok = c["verdict"] == "④多行多列网格" and c["cols"] == 2 and c["rows"] == 6
    print("  正对照 %s" % ("PASS（几何法认出 2×6）" if ctrl_ok else "FAIL ⇒ 本诊断坏了"))

    print("\n=== 汇总 ===")
    for k, v in tally.most_common():
        print("  %-14s %d" % (k, v))
    OUT.write_text(json.dumps({"control_C006": c, "control_ok": bool(ctrl_ok), "rows": res},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n写出:", OUT)
    return 0


sys.exit(main())
