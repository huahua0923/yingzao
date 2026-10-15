# -*- coding: utf-8 -*-
"""A1 侦察：**门/窗/洞口的画法全库普查**（写识别器之前先量分布，不许写死一个块名）。

背景（已实测，本轮复核）：105 份里**没有**独立门/窗/梯层；构件全在墙层里按**几何**认。
已确认的三种画法（三栋三样）：
  · C006：`$DorLib2D$*` 块（754 个，展开成 LINE+ARC = 门扇 + 开启弧），链里 `build8:242` **正是剔掉它**
  · C011：**13 顶点**闭合多段线（104 条），bbox 1000~1300 mm
  · C009：**14 顶点**闭合多段线（371 条），bbox 1150~1900 mm

本尺量四样（只读，不建）：
  ① 墙层里的 INSERT 块：块名前缀分布（门/窗库块？）
  ② 墙层里的多段线：顶点数直方图（封顶 30）
  ③ 墙层里「建筑洞口尺寸」多段线：顶点 ≥ MINV 且 bbox 两边都在 [MIN_MM, MAX_MM] 的条数
  ④ 全库任意层里块名/层名含「门/窗」的实体（找**人写的**门窗库）

★ 量具盲区（必须声明）：
  ① 只按 WALL_LAYERS（四种墙层名）过滤 ①②③；门画在别的层 ⇒ 全盲。
  ② ③ 的尺寸窗 [MIN_MM, MAX_MM] 与 MINV 是**判据参数**，不是从规范抄的；改参数会改数。
  ③ 只数「像洞口的几何块」，**不判它是不是门**、也不判开在哪面墙上（那是识别器 + 判据的活）。
  ④ ④ 的「门/窗」字样只扫**实体层名与块名**，不扫 MTEXT 正文（正文里写「门」不算）。

用法: python probe_openings.py <dxf目录> [--json out.json]
"""
import sys
import os
import json
import glob
import argparse
import collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import ezdxf

WALL_LAYERS = ("4.2墙体", "4墙体", "4.3封墙", "4.3新封墙")
MINV = 8            # 顶点数下限：墙线是 2 点、门符号是多点
MIN_MM, MAX_MM = 300, 3000   # 建筑洞口 bbox 边长窗（mm）：门 0.7~2.4 m、窗可更宽
OPEN_HINT = ("门", "窗", "DOOR", "WINDOW", "DorLib", "WinLib")


def one(path):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    blk = collections.Counter()          # 墙层块名前缀
    vtx = collections.Counter()          # 墙层多段线顶点数
    n_in_window = 0                      # 建筑尺寸的多点多段线（洞口候选）
    n_wall_ins = 0
    hint = collections.Counter()         # 任意层里含门/窗字样的层名或块名
    for e in msp:
        t = e.dxftype()
        lay = e.dxf.layer
        if any(h.lower() in lay.lower() for h in OPEN_HINT):
            hint["层:" + lay] += 1
        if t == "INSERT":
            nm = e.dxf.name or ""
            if any(h.lower() in nm.lower() for h in OPEN_HINT):
                hint["块:" + nm[:24]] += 1
        if lay not in WALL_LAYERS:
            continue
        if t == "INSERT":
            n_wall_ins += 1
            blk[(e.dxf.name or "")[:16]] += 1
        elif t in ("LWPOLYLINE", "POLYLINE"):
            pts = [(p[0], p[1]) for p in e.get_points()]
            nv = len(pts)
            vtx[min(nv, 30)] += 1
            if nv >= MINV:
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                w, h = max(xs) - min(xs), max(ys) - min(ys)
                if MIN_MM <= w <= MAX_MM and MIN_MM <= h <= MAX_MM:
                    n_in_window += 1
    return {"dxf": os.path.basename(path), "n_wall_ins": n_wall_ins,
            "wall_blocks": dict(blk.most_common(6)), "vtx": dict(sorted(vtx.items())),
            "n_open_cand": n_in_window, "hint": dict(hint.most_common(6))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=r"D:\项目\gym3d\材料\dxf_output")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, "*.dxf")))
    if not files:
        print("!! 目录无 *.dxf:", a.dir); return 2
    print("扫 %d 份 ...\n" % len(files))
    rows = []
    for i, f in enumerate(files, 1):
        try:
            r = one(f)
        except Exception as e:
            r = {"dxf": os.path.basename(f), "err": type(e).__name__}
        rows.append(r)
        if "err" in r:
            print("%3d %-42s !! %s" % (i, r["dxf"][:42], r["err"]))
        else:
            print("%3d %-42s 块%d 洞口候选%4d %s"
                  % (i, r["dxf"][:42], r["n_wall_ins"], r["n_open_cand"],
                     (list(r["wall_blocks"])[:2] if r["wall_blocks"] else "")))

    ok = [r for r in rows if "err" not in r]
    if not ok:
        print("!! 全读失败"); return 3
    withblk = [r for r in ok if r["wall_blocks"]]
    withcand = [r for r in ok if r["n_open_cand"] > 0]
    print("\n===== 汇总（分母 %d 份）=====" % len(ok))
    print("墙层有 INSERT 的栋     : %d" % len(withblk))
    print("墙层有洞口候选的栋     : %d   ← 多段线口径" % len(withcand))
    print("洞口候选总数           : %d" % sum(r["n_open_cand"] for r in ok))
    print("洞口候选数 Top12       :")
    for r in sorted(ok, key=lambda x: -x["n_open_cand"])[:12]:
        print("    %-42s %5d" % (r["dxf"][:42], r["n_open_cand"]))
    allblk = collections.Counter(k for r in withblk for k, v in r["wall_blocks"].items() for _ in range(v))
    print("墙层块名前缀 Top12     :", dict(allblk.most_common(12)))
    allhint = collections.Counter(k for r in ok for k, v in r.get("hint", {}).items() for _ in range(v))
    print("全库含门/窗字样 Top12  :", dict(allhint.most_common(12)))
    top = collections.Counter()
    for r in ok:
        for k, v in r["vtx"].items():
            top[int(k)] += v
    print("墙层多段线顶点数(封顶30):", dict(sorted(top.items())))
    if a.json:
        p = os.path.dirname(a.json)
        if p:
            os.makedirs(p, exist_ok=True)
        json.dump({"dir": a.dir, "n": len(ok), "minv": MINV, "win": [MIN_MM, MAX_MM],
                   "n_with_block": len(withblk), "n_with_cand": len(withcand),
                   "rows": rows}, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("写出:", a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
