# -*- coding: utf-8 -*-
"""**逐层楼板的底面** —— 从 libs3d 自己那件**墙实体**（`c006_v8_f<k>_wall.glb`）重取，
不碰它那条链的任何脚本、不碰 DXF、不跑任何形态学闭运算。

为什么只改楼板（2026-10-13 侦察结论，逐条有 `file:line`）：
  · **墙**那条路本来就没有闭运算：`build8.py:516` = 配对平行线缝成四边形 + 未配对线走
    `LineString.buffer(WALL_T/2, cap_style=2, join_style=2)`（**斜接、平头**）⇒ 直角本来就是直角。
  · **楼板**那条路有：`build7.py:324` `_pn.buffer(r).buffer(-r)`，两次都吃默认 `join_style=round`
    ⇒ 形态学闭运算**把凹角磨圆**（凸角不受影响），r∈{200..800} mm。这就是用户说的
    「楼板直角处，还是有圆角」。
  · 交付的每层件里，板是**从 v7 借来的**（`color8.py:141` 取 `c006_v7_f_<k>.glb` 的 `s_` 节点），
    墙/门/梯/楼顶是另外的件 ⇒ **改板不牵动其它任何一件**。

★ **与冻结基线唯一的一处不同**（值见 `MIN_AREA_MM2`，理由是量出来的、不是猜的）：
  build7 `_plate` 用 `p.area >= 5e7`（50 m²）丢块，而它自己的注释写的是「丢掉 **4 m² 级**的圈壁空环」
  —— 常数是它自述意图的 12.5 倍。逐层实测「墙 − 板」的漏出量（量法同 `_scratch/_diag_slab_vs_v7.py`）：
      thr = 50 m²  ⇒ 第 1 层漏 **9.338 m²**（三块，落在 x 55.4~73.7 m / y 52.3~64.5 m 那片）
      thr =  1 m²  ⇒ 第 1 层漏 **0.008 m²**，其余 10 层 **0.000**
      thr = 0.01 m² ⇒ 同上（0.008 / 0.000），但块数翻倍且**并起来面积一字不差** ⇒ 多的是嵌套碎块
  故取 1 m²。**漏出量是判据、块数不是** —— 板可以比墙大（凸出看得见），不能比墙小（墙悬空）。

做法：墙实体的**平面投影**并起来，取各连通块的**外环**（外环填实 = 楼面；内部房间是洞，不是楼面的洞）。
没有闭运算 ⇒ 凹角保持直角。板的**竖向范围照抄被替换的那个 `s_` 节点**，不另立口径。

输出：**规范化棱柱表**（米），交给 `tools/prism_blender.py` 用 Blender 精确拉伸。

用法:
  python tools/slab_sharp.py [--out _gen/slab_prisms.json] [--floors 1] [--report _gen/slab_sharp_report.json]
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely import make_valid, union_all

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
LIBS3D = r"D:\项目\libs3d\c006"
MIN_AREA_MM2 = 1.0e6          # ★ 1 m²。**不是** build7 的 5.0e7（见下），这是本脚本唯一偏离基线的一处
N_FLOOR = 11


def wall_net(k):
    p = os.path.join(LIBS3D, "c006_v8_f%d_wall.glb" % k)
    if not os.path.exists(p):
        raise SystemExit("!! 缺墙实体 %s —— 它是本脚本**唯一**的底面来源" % p)
    return trimesh.load(p, force="mesh")


def v7_slab_band(k):
    """被替换的那个 `s_` 节点在 v7 件里的竖向范围（毫米）。找不到就返回 None（当错误处理）。"""
    p = os.path.join(LIBS3D, "c006_v7_f_%d.glb" % k)
    if not os.path.exists(p):
        return None
    scn = trimesh.load(p)
    geoms = scn.geometry if hasattr(scn, "geometry") else {"m": scn}
    # ★ 必须是 `s_` 而不是 `startswith("s")`：`st_*` 是**楼梯段**，也以 s 开头，
    #   第一版就这么写，竖带被楼梯撑到 1800 mm（实跑报 0..1800，板其实是 0..120）。
    zs = [g for nm, g in geoms.items() if nm.split("_")[0] == "s"]
    if not zs:
        return None
    b = np.array([g.bounds for g in zs])
    return float(b[:, 0, 2].min()), float(b[:, 1, 2].max())


JOIN_STYLE = 2          # mitre：只在**凹角**留直角。1=round（旧行为，弧）
MITRE_LIMIT = 1.0       # ★ 隐藏变量：默认 5.0 时 floor7 会塌成 5 块 1560 m²（实测），
                        #   1.0 才既保住单块（5350 m²）又保住直角（见 _scratch/_diag_close.py）
LEAK_TOL_MM2 = 1.0e3    # 「墙 − 板」容许量 = 1e-3 m²（1000 mm²）。板可以比墙大，不能比墙小
# build7 列表到 1500 为止；本脚本**往上续**到 2000 供「补足」搜索用（见 footprint 末段）
RADII = (200.0, 300.0, 400.0, 600.0, 800.0, 1000.0, 1200.0, 1400.0,
         1600.0, 1800.0, 2000.0)


def footprint(me, r):
    """墙实体 → 平面投影并集 → **斜接**闭运算（连通断开的墙网）→ 面积达标的各块外环。

    ① 为什么必须闭运算：外墙带上有窗洞/门洞，墙并集实测碎成 146~199 块，
       **光取并集的外环得到的是「墙簇」不是「楼面」**（第 1 层只出 922 m² / 应 ~7300 m²）。
    ② 为什么必须是斜接：闭运算**只磨圆凹角**，而凹角正好是用户看出来的那个圆角。
       同一半径下圆角/斜接的**面积只差 0.03%，但直角数 0 → 37**（_scratch/_diag_corners.py）。
    ③ 不用 `trimesh.path.polygons.projected`：它要 `rtree`，本机没装（实跑
       `ModuleNotFoundError`）——那是**量具缺件**、不是几何缺件。改用 `shapely.union_all`
       （GEOS 精确并集；29500 个三角形实测 1.6 s）。
    """
    tri = me.triangles[:, :, :2]
    if len(tri) == 0:
        return [], 0.0
    u = union_all([Polygon(t) for t in tri])
    if u.is_empty:
        return [], 0.0

    def closed(rr):
        q = u.buffer(rr, join_style=JOIN_STYLE, cap_style=2, mitre_limit=MITRE_LIMIT) \
             .buffer(-rr, join_style=JOIN_STYLE, cap_style=2, mitre_limit=MITRE_LIMIT)
        q = make_valid(q)
        cs = list(q.geoms) if q.geom_type == "MultiPolygon" else [q]
        filled = [Polygon(c.exterior) for c in cs if c.geom_type == "Polygon" and not c.is_empty]
        # ★ 必须先并一次再分：`make_valid` 会把一个带洞的多边形拆成「外块 + 落在洞里的块」，
        #   两者**嵌套**。直接逐个当楼面块 ⇒ 第 2 层出 36 块而**并起来面积一模一样**
        #   （5891.1 m² 一块 / 36 块同值）—— 多出来的 35 块全在别的块肚子里，
        #   进了 GLB 就是 35 个隐形实体。并一次即去嵌套。
        merged = union_all(filled) if filled else None
        if merged is None or merged.is_empty:
            return [], 0.0
        ms = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
        ps = [Polygon(c.exterior) for c in ms if c.geom_type == "Polygon" and not c.is_empty]
        ps = [p for p in ps if p.area >= MIN_AREA_MM2]
        return ps, max((p.area for p in ps), default=0.0)

    # ① 半径取法与 build7 同一判据**和同一常数**（「够用就好」的最小值），不另立口径
    _, ref = closed(2000.0)
    parts, r_used = closed(2000.0)[0], 2000.0
    for rr in RADII:
        c, ca = closed(rr)
        if ca >= 0.90 * ref:
            parts, r_used = c, rr
            break

    # ② ★ 但①的单条判据是「**最大块**够大就行」，会**外轮廓还没合上就收工**。
    #    第 1 层就是现场：r=800 时最大块已达 r=2000 的 92%（判据过），可中央大厅那圈墙
    #    有个 ~3~4 m 的洞口没合，楼面于是在建筑**正中央**缺了一块 23.0×23.9 m 的方形
    #    （422.9 m²）—— 上、下两层都盖着这块（第 2~4 层实测含中庭），只有第 1 层漏。
    #    v7 没漏，是因为它那条网的底面来自 `bridge_gaps(lines)`（**用 DXF 的线**沿墙向补缝），
    #    而本脚本的底面来源**只有墙实体**、拿不到那条线 ⇒ 只能靠把半径抬到能跨过洞口。
    #    补足的判据用两条**可测**的（不猜）：
    #      ① 楼面是**一块** —— 半径不够时墙网会碎成几十个「墙簇」，不是楼面
    #      ② 板**盖得住墙**（墙 − 板 ≤ LEAK_TOL）—— 这是那条真正的红线
    #    ★ 两条缺一不可：只查②时 r=200 也「漏 0」（碎块各自贴着墙，自然不漏），必须靠①挡掉。
    for rr in RADII:
        if rr < r_used:
            continue
        c, _ = closed(rr)
        if len(c) == 1 and _leak(u, c) <= LEAK_TOL_MM2:
            parts, r_used = c, rr
            break
    return parts, sum(p.area for p in parts) / 1e6, r_used, _leak(u, parts)


def _leak(u, parts):
    """「墙 − 板」的面积（mm²）。0 = 每堵墙都踩在板上。"""
    if not parts:
        return float("inf")
    return make_valid(u.difference(union_all(parts))).area


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(CDUT, "_gen", "slab_prisms.json"))
    ap.add_argument("--floors", default="all", help="all 或逗号分隔的层号（1..11）")
    ap.add_argument("--report", default=os.path.join(CDUT, "_gen", "slab_sharp_report.json"))
    a = ap.parse_args()

    ks = list(range(1, N_FLOOR + 1)) if a.floors == "all" else [int(x) for x in a.floors.split(",")]
    solids, rep = [], []
    for k in ks:
        band = v7_slab_band(k)
        if band is None:
            print("!! 第 %d 层：v7 件里找不到 `s_` 节点 ⇒ 竖向范围无从照抄，**跳过**（不猜）" % k)
            rep.append({"floor": k, "ok": False, "why": "no_s_node"})
            continue
        me = wall_net(k)
        parts, area_m2, r_used, leak = footprint(me, None)
        if not parts:
            print("!! 第 %d 层：墙实体投不出面积达标的底面 ⇒ 跳过" % k)
            rep.append({"floor": k, "ok": False, "why": "no_footprint"})
            continue
        z0, z1 = band
        for i, p in enumerate(parts):
            solids.append({"name": "f%d.slab%d" % (k, i),
                           "poly": [[round(x / 1000.0, 6), round(y / 1000.0, 6)]
                                    for x, y in p.exterior.coords],
                           "holes": [],
                           "z0": round(z0 / 1000.0, 6), "z1": round(z1 / 1000.0, 6)})
        print("  第 %2d 层  底面 %2d 块  合计 %8.2f m²  半径 %.0f mm  竖带 %.0f..%.0f mm  "
              "漏 %.3f m²  墙实体面 %d"
              % (k, len(parts), area_m2, r_used, z0, z1, leak / 1e6, len(me.faces)))
        rep.append({"floor": k, "ok": True, "parts": len(parts), "area_m2": round(area_m2, 2),
                    "r_mm": r_used, "z_mm": [z0, z1], "leak_mm2": round(leak, 1),
                    "wall_faces": len(me.faces)})

    json.dump({"units": "m", "solids": solids}, open(a.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)
    json.dump({"floors": rep}, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("合计 %d 块棱柱 → %s" % (len(solids), a.out))
    return 0 if solids and all(r["ok"] for r in rep) else 1


if __name__ == "__main__":
    sys.exit(main())
