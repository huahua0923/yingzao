# -*- coding: utf-8 -*-
"""18 张 NO_GRID 的**终结裁决表**：每张报「带墙的图幅数 / 总图幅数」。

判据（一条，与 gridify 无关）：一张图幅里墙实体 ≥50 条 ⇒ 它是一张**平面图**。
  · 带墙图幅 ≥2 ⇒ 这楼**真有多张平面图**，而 gridify 判它 NO_GRID ⇒ **尺子漏**（要修）；
  · 带墙图幅 ≤1 ⇒ **本来就无平面图序列**，NO_GRID 是真判词。

正对照：C006 应恰好 12 张带墙（链里写死的 12 张平面图）。
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
SWEEP = Path(r"D:\项目\cdut3d\a1\_out\wall_sweep3.json")
OUT = Path(r"D:\项目\cdut3d\a1\_out\nogrid_wall_table3.json")
MINW = 50


def ent_mid(e):
    t = e.dxftype()
    try:
        if t == "LINE":
            return ((e.dxf.start.x + e.dxf.end.x) / 2, (e.dxf.start.y + e.dxf.end.y) / 2)
        if t == "LWPOLYLINE":
            p = list(e.get_points())
            return None if not p else (sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p))
        if t in ("CIRCLE", "ARC"):
            return (e.dxf.center.x, e.dxf.center.y)
    except Exception:                                       # noqa: BLE001
        return None
    return None


def wall_sheets(path):
    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    if not layer:
        return None, [], 0
    sheets = SG.merge_pairs(SG.collect_frames(msp, layer))
    wl = {e.dxf.layer for e in msp if any(h in e.dxf.layer for h in ("墙体", "封墙", "4墙体"))}
    pts = [p for e in msp if e.dxf.layer in wl
           for p in [ent_mid(e)] if p is not None]
    n = []
    for s in sheets:
        bb = s["bbox"]
        n.append(sum(1 for x, y in pts if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]))
    return layer, n, len(pts)


def main():
    sw = json.loads(SWEEP.read_text(encoding="utf-8"))
    ng = [r["dxf"] for r in sw["rows"] if r["state"] == "NO_GRID"]
    print("每张 NO_GRID：带墙(≥%d)图幅数 / 总图幅数\n" % MINW)
    rows, tally = {}, collections.Counter()
    for name in ng:
        layer, n, tot = wall_sheets(SRC / name)
        k = sum(1 for v in n if v >= MINW)
        verdict = "★尺子漏" if k >= 2 else "真·无序列"
        tally[verdict] += 1
        rows[name] = {"n_wall_sheets": k, "n_sheets": len(n), "layer": layer,
                      "per_sheet": sorted(n, reverse=True)[:6], "verdict": verdict}
        print("  %-30s %2d / %-3d   %s   前几张:%s"
              % (name, k, len(n), verdict, sorted(n, reverse=True)[:5]))

    print("\n=== 正对照 C006（应恰 12 张带墙）===")
    layer, n, tot = wall_sheets(SRC / "C006-第六教学楼（逸夫楼）.dxf")
    k = sum(1 for v in n if v >= MINW)
    ctrl = (k == 12)
    print("  C006 带墙 %d / %d   %s" % (k, len(n), "PASS" if ctrl else "FAIL"))

    print("\n=== 汇总 ===")
    for kk, vv in tally.most_common():
        print("  %-12s %d" % (kk, vv))
    OUT.write_text(json.dumps({"control_C006_wall_sheets": k, "control_ok": ctrl, "rows": rows},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n写出:", OUT)
    return 0


sys.exit(main())
