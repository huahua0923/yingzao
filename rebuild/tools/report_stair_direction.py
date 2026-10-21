# -*- coding: utf-8 -*-
r"""楼梯方向对账 —— 读图上的 `上/下` 文字锚，与**已建楼梯的几何方向**逐座比对。

为什么要有它（用户 2026-10-19「还有就是楼梯上楼的方向，这些 CAD 作图的规则你梳理一下」）：
  现在唯一在用的判据是「近门起跑」启发式（`build3d.stair_steps` / `_align_steps`）。
  c006 源图里有 **136 条** `上/下` 文字（68+68，都在 `4.2墙体`），代码**一条都没读**；
  c001 一条都没有。文字锚是比启发式更硬的证据，但**本步只报不翻**：
  翻方向会让已验收的楼梯全部重排（铁律 28），先量清楚「两边同意多少座」，再由人裁。

怎么判（不新造几何判据）：
  · 楼梯组：把 `06_su/contours/<层>.json` 里 `layer == "STAIR"` 的踏步块按 600 mm
    缓冲连通分组，一组 = 一座梯间。
  · 几何上行方向：踏步块 z 最低 20% 的形心 → z 最高 20% 的形心（这正是 `stair_steps`
    把踏步按 fdir 递增铺出来的结果）。
  · 文字：`01_cad/raw/<层>.dxf` 里 TEXT/MTEXT 文本恰为 `上` / `下` 的插入点。
    文字到**梯间踏步几何并集**的距离 <= `ATTACH_MM` 才可配；全局按距离升序**一对一**
    指派（一文字只用一次、一梯间每种字只用一次），没配上的计入 `杂散文字`。
  · **两种制图习惯并列量，不替用户选**：
      解释甲：`上` 写在**起步端**  ⇒ 上行方向 = 从 `上` 指向 `下`
      解释乙：`上` 写在**到达端**  ⇒ 上行方向 = 从 `下` 指向 `上`
    两端投影差 < 1 m ⇒ `分不开`（两个锚在同一头，方向定不了）。

★ 盲区（铁律 158）：
  · 只认**文字** `上/下`；箭头块、折断线一律不读（两张图都没找到箭头块）。
  · 文字与梯间的配对按**到几何的距离**且一对一，仍不是拓扑归属；输出里每条带
    `配距_mm`，超出 `ATTACH_MM` 的不会被悄悄配上，而是计入 `杂散文字`。
  · 本步**不修改任何几何**、不写 build.json、不参与建件；只看已出的件与源图。

输出：<根>/02_recognize/楼梯方向.json（字节层写盘，铁律 79）
用法：CDUT_BUILDING=c006 python -X utf8 -I rebuild/tools/report_stair_direction.py
退出码：0 完成（无论一致率多少）· 2 无轮廓件 · 3 无源 DXF
"""
from __future__ import annotations

import json
import math
import os
import sys

from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import building as B                                                     # noqa: E402

GROUP_MM = 600.0          # 踏步块连通分组缓冲
ATTACH_MM = 1200.0        # 文字到梯间**轮廓**的最大距离；超过 = 杂散，不配对
SPLIT_MM = 1000.0         # 两端投影差小于它 ⇒ 方向分不开
LOWP = 0.20               # 最低/最高 20% 的踏步用来定方向


def _texts(path):
    """源 DXF 里的 `上`/`下` → [(x_mm, y_mm, 字, 层)]。"""
    import ezdxf
    doc = ezdxf.readfile(path)
    out = []
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "TEXT":
            s = (e.dxf.text or "").strip()
        elif t == "MTEXT":
            s = (e.plain_text() or "").strip()
        else:
            continue
        if s not in ("上", "下"):
            continue
        p = e.dxf.insert
        out.append((float(p.x), float(p.y), s, e.dxf.layer))
    return out


def _stairs(recs):
    """STAIR 踏步块 → 梯间组 [[{z, g, cx, cy}, ...], ...]。"""
    bs = []
    for r in recs:
        try:
            g = Polygon(r["ring"], r.get("holes") or []).buffer(0)
        except Exception:                                                # noqa: BLE001
            continue
        if g.is_empty or g.area < 1.0:
            continue
        c = g.centroid
        bs.append(dict(z=float(r.get("z") or 0.0), g=g, cx=c.x, cy=c.y))
    if not bs:
        return []
    u = unary_union([b["g"].buffer(GROUP_MM) for b in bs])
    comps = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
    groups = []
    for comp in comps:
        blk = [b for b in bs if comp.contains(b["g"].representative_point())]
        if blk:
            groups.append(dict(blk=blk, geom=unary_union([b["g"] for b in blk])))
    return groups


def _axis(blk):
    """几何上行方向：低 z 形心 → 高 z 形心。返回 (ux, uy, cx, cy, zlo, zhi)。"""
    zs = sorted(b["z"] for b in blk)
    zlo, zhi = zs[0], zs[-1]
    if zhi - zlo < 300.0:
        return None
    k = max(1, int(round(len(blk) * LOWP)))
    lo, hi = blk[:k], blk[-k:]
    ax = sum(b["cx"] for b in hi) / len(hi) - sum(b["cx"] for b in lo) / len(lo)
    ay = sum(b["cy"] for b in hi) / len(hi) - sum(b["cy"] for b in lo) / len(lo)
    n = math.hypot(ax, ay)
    if n < 300.0:
        return None
    cx = sum(b["cx"] for b in blk) / len(blk)
    cy = sum(b["cy"] for b in blk) / len(blk)
    return ax / n, ay / n, cx, cy, zlo, zhi


def _pair(groups, texts):
    """文字 → 梯间**一对一指派**，距离量到梯间**几何并集**（不是形心）。

    ★ 2026-10-19 为什么改成这样：上一版按「离梯间中心最近」配对，1 层/7 层出现了
      跨 48 m 的配对（一跑梯的 `上` 被配到另一跑梯上）⇒ 对账数被虚增。现在：
      · 距离 = 文字点到该梯间所有踏步块并集的距离，> `ATTACH_MM` 一律不配；
      · 全局按距离升序贪心，一文字只用一次、一梯间每种字只用一次；
      · 没配上的一律计入 `杂散`（如实点名，不悄悄丢）。
    返回 ({(组下标, 字): (x, y, 字, 层, 距_mm)}, 杂散条数)。
    """
    from shapely.geometry import Point
    cand = []
    for gi, grp in enumerate(groups):
        for ti, t in enumerate(texts):
            d = grp["geom"].distance(Point(t[0], t[1]))
            if d <= ATTACH_MM:
                cand.append((d, gi, ti))
    cand.sort(key=lambda q: q[0])
    got, used_t = {}, set()
    for d, gi, ti in cand:
        t = texts[ti]
        if ti in used_t or (gi, t[2]) in got:
            continue
        used_t.add(ti)
        got[(gi, t[2])] = (t[0], t[1], t[2], t[3], round(d, 0))
    return got, len(texts) - len(used_t)


def run():
    P_cont = os.path.join(B.ROOT, "06_su", "contours")
    idx = os.path.join(P_cont, "index.json")
    if not os.path.exists(idx):
        print("★ 轮廓 index 不在：%s（先跑 轮廓 步）" % idx)
        return 2
    with open(idx, encoding="utf-8") as fh:
        floors = [f["floor"] for f in json.load(fh)]
    raw = os.path.join(B.ROOT, "01_cad", "raw")
    if not os.path.isdir(raw):
        print("★ 源 DXF 目录不在：%s（先跑 导出图幅）" % raw)
        return 3
    out_floors = []
    totals = dict(甲=0, 乙=0, 分不开=0, 无文字=0, 无几何=0, 杂散=0)
    for nm in floors:
        fp = os.path.join(raw, nm + ".dxf")
        cp = os.path.join(P_cont, nm + ".json")
        if not (os.path.exists(fp) and os.path.exists(cp)):
            print("★ %s 源 DXF/轮廓缺（%s / %s）⇒ 跳过本层" % (nm, fp, cp))
            continue
        txt = _texts(fp)
        ups = [t for t in txt if t[2] == "上"]
        dns = [t for t in txt if t[2] == "下"]
        with open(cp, encoding="utf-8") as fh:
            recs = [r for r in json.load(fh)["polys"] if r.get("layer") == "STAIR"]
        groups = _stairs(recs)
        got, stray = _pair(groups, txt)
        totals["杂散"] += stray
        rows = []
        for gi, grp in enumerate(groups):
            ax = _axis(grp["blk"])
            if ax is None:
                totals["无几何"] += 1
                continue
            ux, uy, cx, cy, zlo, zhi = ax

            def proj(pt):
                return (pt[0] - cx) * ux + (pt[1] - cy) * uy

            def pick(ch):
                q = got.get((gi, ch))
                if q is None:
                    return None
                return dict(u=round(proj(q), 1), 配距_mm=q[4], layer=q[3])

            a, b = pick("上"), pick("下")
            row = dict(梯间=gi + 1, 踏步块=len(grp["blk"]),
                       z_mm=[round(zlo, 1), round(zhi, 1)],
                       中心=[round(cx, 1), round(cy, 1)], 上行轴=[round(ux, 4), round(uy, 4)],
                       上=a, 下=b)
            if not a or not b:
                row["判"] = "无文字"
                totals["无文字"] += 1
            elif abs(a["u"] - b["u"]) < SPLIT_MM:
                row["判"] = "分不开"
                totals["分不开"] += 1
            else:
                # 甲：上在起步端 ⇒ 上行 = 上→下 ⇒ 沿上行轴，下的投影应更靠前
                jia = b["u"] > a["u"]
                row["判"] = "甲一致" if jia else "乙一致"
                totals["甲" if jia else "乙"] += 1
                row["两端投影差_mm"] = round(b["u"] - a["u"], 1)
            rows.append(row)
        out_floors.append(dict(层=nm, 文字=dict(上=len(ups), 下=len(dns)),
                               杂散文字=stray, 梯间=rows))

    total_rows = sum(len(f["梯间"]) for f in out_floors)
    out = dict(
        栋=B.BID,
        读法=dict(分组_mm=GROUP_MM, 配对_mm=ATTACH_MM, 两端可分_mm=SPLIT_MM,
                  低高比例=LOWP,
                  判法="甲：上在起步端，上行=上→下；乙：上在到达端，上行=下→上；本步只报不翻",
                  盲区="只认文字上/下，不读箭头/折断线；配到梯间**几何**且一对一，"
                       "仍不是拓扑归属；离几何 > 配对_mm 的文字计杂散"),
        合计=dict(梯间=total_rows, **totals),
        层=out_floors,
    )
    p = os.path.join(B.ROOT, "02_recognize", "楼梯方向.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:                                            # 字节层（铁律 79）
        fh.write(json.dumps(out, ensure_ascii=False, indent=1,
                            allow_nan=False).encode("utf-8"))

    print("楼栋 %s · 梯间 %d 座 · 文字 上 %d / 下 %d"
          % (B.BID, total_rows,
             sum(f["文字"]["上"] for f in out_floors),
             sum(f["文字"]["下"] for f in out_floors)))
    print("对账：甲一致 %d · 乙一致 %d · 分不开 %d · 无文字 %d · 无几何 %d · 杂散文字 %d"
          % (totals["甲"], totals["乙"], totals["分不开"], totals["无文字"],
             totals["无几何"], totals["杂散"]))
    for f in out_floors:
        if f["文字"]["上"] or f["文字"]["下"]:
            c = {}
            for r in f["梯间"]:
                c[r["判"]] = c.get(r["判"], 0) + 1
            print("  %-4s 上/下 %d/%d · 梯间 %d · %s"
                  % (f["层"], f["文字"]["上"], f["文字"]["下"], len(f["梯间"]), c))
    print("⇒ %s（只报不翻：本文件不参与建件）" % p)
    return 0


if __name__ == "__main__":
    sys.exit(run())
