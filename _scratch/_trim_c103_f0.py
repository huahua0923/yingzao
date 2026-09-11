# -*- coding: utf-8 -*-
"""c103 F0 收平：把底层 F0 的轮廓/外环收到与 F1 同深(79.5m)，柱/窗/门同步收。

背景(见会话分析)：
- c103 F0 在 DXF 的墙体层上被入口台阶/apron 符号撑大，外环 y 到 -45.9/+44.8(=90.8m 深)，
  而 F1-4 是 79.5m 深(y[-39.6,40.0])，X 同为 ±84.5 → GLB 里 F0 底下一圈"鼓"。
- 实测 F0 内墙与 F1 完全同构(逐墙面积几乎相等)，说明真实 F0 平面≈F1；
  内墙藏在不透明楼层实体盒内不可见；F0/F1 的窗都挂在唯一外环墙(id w0-0/w1-0)上。
- 方案(最小改动、渲染安全)：
  1. outline 与 outer 外环  <- F1 outline(同深 79.5，保留 id w0-0 => 窗洞仍正确挖)
  2. 跨界大内墙 w0-1/w0-2/w0-13 丢弃(shapely 裁剪必碎成 6-7 片、渲染器要单环，且不可见)
  3. 柱/窗/门/房间/电梯/楼梯：保留位于 F1 区域内的自身元素，越界(离区界>0.5m)丢弃

幂等(可重复跑)。改前原文件备份到 floor0.json.orig。
"""
import json
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import shapely.geometry as sg

FL0 = r"D:\gym3d\data\buildings\c103\floors\floor0.json"
FL1 = r"D:\gym3d\data\buildings\c103\floors\floor1.json"
MARG = 0.5  # 允许窗/门中心贴立面(在轮廓线上)仍保留；超出 0.5m 视为属于被裁掉的裙边


def main():
    f0 = json.load(open(FL0, encoding="utf-8"))
    f1 = json.load(open(FL1, encoding="utf-8"))
    R = sg.Polygon(f1["outline"])
    assert not R.is_empty and R.geom_type == "Polygon", "F1 outline 必须为单环"
    print("F1 区域  area=%.0f bbox=[%.1f,%.1f,%.1f,%.1f]" % (R.area, *R.bounds))

    n0 = {k: len(f0.get(k, [])) for k in
          ["walls", "columns", "windows", "doors", "rooms", "elevators", "stairwells"]}

    # 备份原文件
    shutil.copyfile(FL0, FL0 + ".orig")
    g = dict(f0)

    # 1) outline & outer 外环 <- F1
    g["outline"] = [list(c) for c in R.exterior.coords]
    kept_walls = []
    outer_seen = False
    for w in f0["walls"]:
        if w.get("type") == "outer":
            w = dict(w, poly=[list(c) for c in R.exterior.coords])  # 保留 id w0-0
            outer_seen = True
            kept_walls.append(w)
        else:
            p = sg.Polygon(w["poly"])
            if p.within(R):  # 完全在区域内才留
                kept_walls.append(w)
    g["walls"] = kept_walls
    assert outer_seen, "F0 找不到 outer 外墙"

    # 2) 柱/窗/门/房间/电梯/楼梯：按是否在 F1 区域内过滤
    def in_region_pt(x, y):
        return R.buffer(MARG).contains(sg.Point(x, y))

    def in_region_poly(coords):
        return sg.Polygon(coords).within(R.buffer(MARG))

    g["columns"] = [c for c in f0["columns"] if R.contains(sg.Point(c["x"], c["y"]))]
    g["windows"] = [w for w in f0["windows"] if in_region_pt(w["x"], w["y"])]
    g["doors"] = [d for d in f0["doors"] if in_region_pt(d["x"], d["y"])]
    g["rooms"] = [r for r in f0["rooms"] if in_region_poly(r["poly"])]
    g["elevators"] = [e for e in f0["elevators"]
                      if in_region_pt((e["x0"] + e["x1"]) / 2, (e["y0"] + e["y1"]) / 2)]
    g["stairwells"] = [s for s in f0["stairwells"]
                       if in_region_pt((s["x0"] + s["x1"]) / 2, (s["yBot"] + s["yTop"]) / 2)]

    # 3) outline bbox 复核
    xs = [p[0] for p in g["outline"]]; ys = [p[1] for p in g["outline"]]
    ob = [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]

    json.dump(g, open(FL0, "w", encoding="utf-8"), ensure_ascii=False)
    n1 = {k: len(g.get(k, [])) for k in n0}
    print("完成。F0 outline bbox=%s  (原 y[-45.9..44.8] → 应=%.2f..%.2f)"
          % (ob, R.bounds[1], R.bounds[3]))
    for k in n0:
        if n0[k] != n1[k]:
            print("  %-11s %d -> %d" % (k, n0[k], n1[k]))


if __name__ == "__main__":
    main()
