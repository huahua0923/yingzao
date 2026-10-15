# -*- coding: utf-8 -*-
"""判 18 张 NO_GRID：是「本来就没有多层平面图」还是「尺子漏了」。

★ 为什么要判：`wall_sweep2` 把 18 张记为 NO_GRID，而 NO_GRID 是**判词**不是事实。
  「找不到网格」这句话本身不带分辨力 —— 它把「图里没有」与「尺子看不见」印成同一个字（铁律 158）。
  本脚本把那个字拆开。

拆法：把 sheet_grid 的三个内部步骤（收框 → 并框 → 分类）**逐步印出来**，于是每个 NO_GRID 落进下面之一：
  ① `无图框层`     —— 尺子对该图全盲（盲区①），**判不了**，要另找量具；
  ② `图幅全落单`   —— 有图幅层、也有图幅，但**没有任何尺寸成列(≥2)** ⇒ 本来就是散图（详图/总平/单层）
                      ⇒ **不是尺子漏**，是「这楼就没有多层平面图」；
  ③ `有成列图幅`   —— 存在 ≥2 张同尺寸图幅落在同一列。**对 NO_GRID 的那张，这一条就等于「尺子漏」**
                      （尺子看得见网格却没选它）；对 OK 的那张，这只是「它本来就有网格」。

★ 正对照（必须）：同法跑 **C006**（已知 12 张真网格）。若 C006 也落进 ②/③，说明本诊断自己坏了。
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
OUT = Path(r"D:\项目\cdut3d\a1\_out\nogrid_adjudged.json")


def diagnose(dxf_path):
    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    layer = SG.find_frame_layer(msp, None)
    if not layer:
        return {"verdict": "①无图框层", "why": "本尺全盲（只认 1图框 层的闭合多段线）",
                "n_frames": 0, "n_sheets": 0, "sizes": {}}
    frames = SG.collect_frames(msp, layer)
    sheets = SG.merge_pairs(frames)
    sizes = collections.Counter(
        (round(s["bbox"][2] - s["bbox"][0]), round(s["bbox"][3] - s["bbox"][1])) for s in sheets)
    # 每个尺寸组内部，按 gridify 的列规则看最多能凑几列/每列几张
    by_size = collections.defaultdict(list)
    for s in sheets:
        by_size[(round(s["bbox"][2] - s["bbox"][0]), round(s["bbox"][3] - s["bbox"][1]))].append(s)
    best_cols = 0
    best_size = None
    for k, grp in by_size.items():
        kept = SG.gridify(grp, 2)
        ncols = len({s["col"] for s in kept})
        if len(kept) > best_cols:
            best_cols, best_size = len(kept), k
    v = {"layer": layer, "n_frames": len(frames), "n_sheets": len(sheets),
         "sizes": {"%.0fx%.0f" % k: n for k, n in sizes.most_common(6)},
         "max_grid_kept": best_cols, "max_grid_size": None if not best_size else "%.0fx%.0f" % best_size}
    if best_cols == 0:
        v["verdict"] = "②图幅全落单"
        v["why"] = "有图幅层与图幅，但无任何尺寸能凑成 ≥2 张同列 ⇒ 无多层平面图布局"
    else:
        v["verdict"] = "③有成列图幅"
        v["why"] = "存在 %d 张同尺寸图幅成列，classify 却未选中 ⇒ 尺子漏" % best_cols
    return v


def main():
    sw = json.loads(SWEEP.read_text(encoding="utf-8"))
    ng = [r["dxf"] for r in sw["rows"] if r["state"] == "NO_GRID"]
    print("NO_GRID %d 张，逐张拆开：\n" % len(ng))
    res = {}
    tally = collections.Counter()
    for name in ng:
        try:
            v = diagnose(SRC / name)
        except Exception as e:                              # noqa: BLE001
            v = {"verdict": "!!异常", "why": "%s: %s" % (type(e).__name__, e)}
        res[name] = v
        tally[v["verdict"]] += 1
        print("  %-32s %-12s 框%4d 图幅%3d  最大列数 %-3s  %s"
              % (name, v["verdict"], v.get("n_frames", -1), v.get("n_sheets", -1),
                 v.get("max_grid_kept", "-"), v.get("why", "")[:44]))
        print("        尺寸: %s" % v.get("sizes", {}))

    print("\n=== 正对照：C006（已知真网格 12 张）===")
    c = diagnose(SRC / "C006-第六教学楼（逸夫楼）.dxf")
    print("  C006: %s  框%4d 图幅%3d  最大列数 %s  尺寸 %s"
          % (c["verdict"], c["n_frames"], c["n_sheets"], c["max_grid_kept"], c["sizes"]))
    ctrl_ok = (c["verdict"] == "③有成列图幅" and c["max_grid_kept"] >= 10)
    print("  正对照 %s" % ("PASS（诊断在真网格上确实报出大网格）" if ctrl_ok
                          else "FAIL ⇒ 本诊断自己坏了，上面 18 条读数作废"))

    print("\n=== 汇总 ===")
    for k, v in tally.most_common():
        print("  %-12s %d" % (k, v))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"control_C006": c, "control_ok": bool(ctrl_ok), "rows": res},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n写出:", OUT)
    return 0 if ctrl_ok else 1


sys.exit(main())
