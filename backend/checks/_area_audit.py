# -*- coding: utf-8 -*-
"""全库面积对账（只读）：每栋 DXF 自带的面积表（0 图层 ACAD_TABLE） ↔ 模型逐层楼板面积。

口径说明：图纸表给的是**建筑面积**（按层，不含屋面）；模型 `floor_outline` 给的是**楼板足迹**
（含退台屋面/裙楼屋面这类"板上还要铺屋面"的块）。所以逐层差值要分两类看：
  · 纯楼层：两者应接近（差值 = 墙厚外皮口径 + 屋面块）
  · 顶层/过渡层：模型会把屋面块算进去，差值天然偏大
输出：每栋一张逐层对照 + 一张全库排名（平均/最大偏差、无法对账的栋）。
"""
import json
import os
import re
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = r"D:\gym3d"
sys.path[:0] = [os.path.join(ROOT, "backend", "web"),
                os.path.join(ROOT, "backend"), ROOT]

import ezdxf  # noqa: E402
from recognizer import outline as OUT  # noqa: E402

BUILDINGS = os.path.join(ROOT, "data", "buildings")


def clean(s):
    s = str(s)
    s = re.sub(r"\\[A-Za-z]+[^;]*;", "", s)
    return (s.replace("{", "").replace("}", "").replace("\\H0.7x;", "")
            .replace("\\S2^ ;", "2").replace("\\P", "|").strip())


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group(0)) if m else None


def dxf_area_table(dxf_path):
    """{楼层: (建筑面积㎡, 房间数)} —— 图纸自带面积表。读不到返回 {}。"""
    doc = ezdxf.readfile(dxf_path)
    out = {}
    for t in doc.modelspace():
        if t.dxftype() != "ACAD_TABLE":
            continue
        vals = []
        try:
            for v in t.virtual_entities():
                if v.dxftype() in ("TEXT", "MTEXT"):
                    vals.append(clean(v.dxf.text if v.dxftype() == "TEXT" else v.text))
        except Exception:
            continue
        d = {vals[i]: vals[i + 1] for i in range(0, len(vals) - 1, 2)}
        key = d.get("楼层")
        a = num(d.get("建筑面积", ""))
        if not key or a is None:
            continue
        if a <= 100.5 and a >= 99.5:      # 模板行（100.00/60.00 那种占位）
            continue
        try:
            k = int(key)
        except Exception:
            continue
        out[k] = (a, num(d.get("房间数", "")))
    return out


def model_floors(name):
    fp = os.path.join(BUILDINGS, name, "floors")
    if not os.path.isdir(fp):
        return {}
    res = {}
    for i in range(64):
        p = os.path.join(fp, "floor%d.json" % i)
        if not os.path.exists(p):
            break
        g = json.load(open(p, encoding="utf-8"))
        res[i] = OUT.floor_outline(g).area
    return res


def main():
    names = sorted(d for d in os.listdir(BUILDINGS)
                   if os.path.isdir(os.path.join(BUILDINGS, d)) and d != "_meta")
    only = sys.argv[1:] or None
    rows, no_table = [], []
    for name in names:
        if only and name not in only:
            continue
        prof_p = os.path.join(BUILDINGS, name, "profile.json")
        if not os.path.exists(prof_p):
            continue
        try:
            cfg = json.load(open(prof_p, encoding="utf-8"))
            dxf = cfg.get("dxf")
            if not dxf or not os.path.exists(dxf):
                no_table.append((name, "无 DXF"))
                continue
            tab = dxf_area_table(dxf)
            mod = model_floors(name)
            if not tab:
                no_table.append((name, "DXF 里没有面积表"))
                continue
            ds = []
            lines = []
            for k in sorted(tab):
                i = k - 1                      # 图纸"楼层"1 基 → 模型 F 0 基
                if i not in mod:
                    continue
                d = mod[i] - tab[k][0]
                ds.append(d)
                lines.append((k, tab[k][0], mod[i], d, tab[k][1]))
            if not ds:
                no_table.append((name, "面积表楼层与模型对不上"))
                continue
            avg = sum(ds) / len(ds)
            worst = max(ds, key=abs)
            rows.append((name, len(ds), avg, worst, lines))
        except Exception as exc:  # noqa: BLE001
            no_table.append((name, "读取失败:%s" % exc))
            traceback.print_exc()
    rows.sort(key=lambda r: -abs(r[2]))
    print("=" * 92)
    print("%-8s %4s %10s %10s   %s" % ("楼栋", "对数", "平均偏差", "最大偏差", "最大偏差那层"))
    print("-" * 92)
    for name, n, avg, worst, lines in rows:
        w = max(lines, key=lambda t: abs(t[3]))
        print("%-8s %4d %9.1f㎡ %9.1f㎡   F%d(图纸%.1f/模型%.1f)"
              % (name, n, avg, worst, w[0] - 1, w[1], w[2]))
    print("=" * 92)
    print("无法对账的楼 %d 栋：" % len(no_table))
    for name, why in no_table:
        print("   %-8s %s" % (name, why))
    big = [r for r in rows if abs(r[2]) > 200]
    print()
    print("★ 平均偏差 >200㎡ 的楼 %d 栋：%s" % (len(big), ", ".join(r[0] for r in big)))
    if only:
        for name, n, avg, worst, lines in rows:
            print()
            print("--- %s 逐层（图纸 vs 模型）" % name)
            for k, a, b, d, rooms in lines:
                print("   %s层 图纸 %8.2f  模型 %8.2f  差 %+8.1f   房间数 %s"
                      % (k, a, b, d, rooms))


if __name__ == "__main__":
    main()
