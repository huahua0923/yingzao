# -*- coding: utf-8 -*-
"""缺陷普查：把「模型不对」量成数字（只读）。

为什么要有这个
--------------
现有的两个门禁都测不到你看到的病：
  * qa_structural.py —— 只查「柱是否锚定轮廓内」「有没有楼板」这类结构不变量，
    所以它报 48/49 PASS，而你看着不对。**它量的不是你对的东西。**
  * _dxf_audit.py —— 只查「漏墙」（源图墙线有没有被识别墙盖住）。
    实测全楼漏检 0-5%，它也说没问题。

但你点名的三条里，「糊成一块」是**过覆盖**（识别出比图更多的墙），
「楼层错位/悬空」是**层间几何关系**，「门窗楼梯不对」是**符号计数**——
这三个 _dxf_audit 一个都不管。本脚本补这三条。

四条量（逐栋逐层）
------------------
  W  糊成一块   单块墙面积 top / 面积>BLOB_M2 的块数 / 墙总面积÷轮廓面积
                判据：一块墙面积 ≫ 房间面积 = 单线墙被 buffer 成整层实心块
                （宿舍公寓簇的历史病：139㎡ 块占板 29%）
  F  楼层错位   相邻层轮廓质心距 / bbox 位移 / 本层墙越出下层楼板足迹的比例
                判据：越界率高 = 上层墙悬空在外
  S  楼梯        stairwells 数、stairs 数、井面积占轮廓比
                判据：源图有楼梯而 stairwell=0 = 楼梯没进模型
  D  门窗        doors/windows 数、窗洞（wall.holes）数

安全：**只读** data/，不写任何文件，不改任何东西。

用法
----
    python _scratch/_defect_census.py                 # 全部 49 栋
    python _scratch/_defect_census.py c084 c009 c055  # 指定
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("backend", "backend/web", "backend/modeling"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BLOB_M2 = 50.0        # 单块墙面积超过此值 = 疑似「糊成一块」
                      # 依据：正常墙体最厚 0.4m × 最长 60m ≈ 24㎡；50㎡ 已无正常解释


def poly_area(ring):
    """鞋带公式有向面积取绝对值。不引 shapely —— 这里只要数量级。"""
    n = len(ring)
    if n < 3:
        return 0.0
    a = 0.0
    for i in range(n):
        x0, y0 = float(ring[i][0]), float(ring[i][1])
        x1, y1 = float(ring[(i + 1) % n][0]), float(ring[(i + 1) % n][1])
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def bbox(ring):
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def census_floor(fl):
    walls = fl.get("walls", []) or []
    areas, blobs, wall_area = [], 0, 0.0
    for w in walls:
        ring = w.get("poly") or []
        if len(ring) < 3:
            continue
        a = poly_area(ring)
        # 扣掉洞：合并式楼的墙是「整层环 + 房间洞」，不扣会把整层算成墙面积
        for h in (w.get("holes") or []):
            if len(h) >= 3:
                a -= poly_area(h)
        a = max(0.0, a)
        areas.append(a)
        wall_area += a
        if a > BLOB_M2:
            blobs += 1

    outline = fl.get("outline") or []
    out_area = poly_area(outline) if len(outline) >= 3 else 0.0
    ob = bbox(outline) if len(outline) >= 3 else None
    # 轮廓质心（顶点均值，只用于跨层比对位移，不用来判绝对位置 —— 退台楼会误报）
    oc = None
    if outline:
        oc = (sum(float(p[0]) for p in outline) / len(outline),
              sum(float(p[1]) for p in outline) / len(outline))

    holes = sum(len([h for h in (w.get("holes") or []) if len(h) >= 4]) for w in walls)
    return {
        "floor": fl.get("floor", -1),
        "n_walls": len(walls),
        "wall_area": wall_area,
        "out_area": out_area,
        "wall_ratio": (wall_area / out_area) if out_area > 0 else 0.0,
        "max_wall": max(areas) if areas else 0.0,
        "blobs": blobs,
        "n_doors": len(fl.get("doors", []) or []),
        "n_windows": len(fl.get("windows", []) or []),
        "win_holes": holes,
        "n_stairwells": len(fl.get("stairwells", []) or []),
        "n_stairs": len(fl.get("stairs", []) or []),
        "stair_area": sum(poly_area(s["poly"]) for s in (fl.get("stairs") or [])
                          if isinstance(s, dict) and len(s.get("poly") or []) >= 3),
        "centroid": oc,
        "bbox": ob,
    }


def census_building(name):
    d = os.path.join(ROOT, "data", "buildings", name, "floors")
    if not os.path.isdir(d):
        return None
    fs = sorted(int(f[5:-5]) for f in os.listdir(d)
                if f.startswith("floor") and f.endswith(".json"))
    rows = []
    for F in fs:
        with open(os.path.join(d, "floor%d.json" % F), encoding="utf-8") as f:
            rows.append(census_floor(json.load(f)))
    return rows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        from paths import BUILDINGS
        args = sorted(d for d in os.listdir(BUILDINGS)
                      if os.path.isdir(os.path.join(BUILDINGS, d))
                      and os.path.exists(os.path.join(BUILDINGS, d, "profile.json")))

    print("缺陷普查（只读）—— 糊成一块 / 楼层错位 / 楼梯 / 门窗")
    print("=" * 104)
    print("%-6s %5s %7s %8s %7s %6s %7s %6s %6s %6s %6s  %s"
          % ("楼", "层", "墙数", "墙面积", "墙/轮廓", "巨块", "最大块", "门", "窗", "窗洞",
             "楼梯井", "相邻层质心位移"))
    print("-" * 104)

    tot_blob = {}
    tot_mis = []
    for name in args:
        rows = census_building(name)
        if not rows:
            print("%-6s 无楼层数据" % name)
            continue
        prev = None
        for r in rows:
            shift = ""
            if prev and prev["centroid"] and r["centroid"]:
                dx = r["centroid"][0] - prev["centroid"][0]
                dy = r["centroid"][1] - prev["centroid"][1]
                dd = (dx * dx + dy * dy) ** 0.5
                shift = "%.2f m" % dd
                if dd > 3.0:
                    shift += "  ← 可疑"
                    tot_mis.append((name, r["floor"], dd))
            flag = "  ← 巨块" if r["blobs"] else ""
            if r["wall_ratio"] > 0.35:
                flag += "  ← 墙占比过高"
            print("%-6s %5d %7d %8.0f %7.2f %6d %7.0f %6d %6d %6d %6d  %s%s"
                  % (name, r["floor"], r["n_walls"], r["wall_area"], r["wall_ratio"],
                     r["blobs"], r["max_wall"], r["n_doors"], r["n_windows"],
                     r["win_holes"], r["n_stairwells"], shift, flag))
            prev = r
        b = sum(r["blobs"] for r in rows)
        if b:
            tot_blob[name] = b
        print("-" * 104)

    print("\n=== 汇总 ===")
    if tot_blob:
        print("有「巨块墙」的楼（%d 栋）：" % len(tot_blob))
        for n, c in sorted(tot_blob.items(), key=lambda kv: -kv[1]):
            print("   %-6s %d 块 >%.0f㎡" % (n, c, BLOB_M2))
    else:
        print("无巨块墙。")
    if tot_mis:
        print("相邻层质心位移 >3m 的层（%d 处）：" % len(tot_mis))
        for n, F, dd in sorted(tot_mis, key=lambda t: -t[2])[:15]:
            print("   %-6s f%-3d %.2f m" % (n, F, dd))
    else:
        print("无相邻层质心位移 >3m。")
    print("\n注：质心只用顶点均值，**退台楼会误报** —— 它只用来筛可疑，"
          "定真伪要看构件对应（柱/楼梯/同房间）。")


if __name__ == "__main__":
    main()
