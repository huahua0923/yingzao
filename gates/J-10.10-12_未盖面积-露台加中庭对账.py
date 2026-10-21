# -*- coding: utf-8 -*-
r"""判据 J-10.10-12 —— **顶层「未盖」的每一平米都必须能点名到露台或中庭洞**。

为什么要有它（用户 2026-10-19「还有就是有的房间应该有屋顶，我们很多没有」）：
  2026-10-19 手算过一次 c001 5 层：板 1899.5 − 屋面 1461.0 = 438.4 = 露台 111.3 + 中庭屋面洞 327.1，
  差 0.0。**但那只是一次手算，没有闸** ⇒ 下一版改了任何一处，没有人会再算一遍
  （症状：件全链绿、屋顶静默少盖一片）。

判据（三条，各自落读数）：
  ① **顶层必须有 ROOF 记录**；没有 = 红（不是「没量到」——顶层本来就该有屋面板）。
  ② **总面积对账**：`plate − ROOF ≈ 露台 + 屋面挑空`，容差 `TOL_M2`。
       plate = 顶层轮廓里的 SLAB 面积 + 该层中庭洞面积（挑空.json 给的）。
       ★ 两个被减数来自**不同文件**（轮廓 vs 挑空识别），不是同源自查。
  ③ **逐房间对账**（这条才是用户问的那句）：只在**顶层楼板足迹内**判（楼板已经扣过
     中庭洞 ⇒ 洞里的面积本来就不在 `need` 里）：
       `need = 房间 ∩ 顶层楼板`；`res = need − ROOF − ROOF_ROOM`；
       · `res ≤ ROOM_TOL` ⇒ 有顶；
       · 标记 `露台` ⇒ 应无顶（露台，只报不判红）；
       · 其余 ⇒ **★该有顶却没有**（红，点名房间）。
     ★ 2026-10-19 实测为什么必须先与楼板求交：c001 房间 #28 是 952 m² 的**大分区**
       （绕全层一圈），它与楼板外的 411 m² 不重合；不夹这一刀时它的残余是 1.94 m²，
       而**残余 100% 落在楼板外**（在楼板内的残余 = 0.000 m²）⇒ 那不是缺顶，是分区环
       探出了板边（铁律 158：判据的参照物必须与被判对象同作用域）。
     房间环取自 `语义.json`（分区环），不许在本闸里重新分区（铁律 018/174）。

★ 盲区（铁律 158）：
  · 本闸**只认平面投影**。屋顶小间（楼梯房/电梯机房）自带顶板，但本闸不区分
    「结构性墙顶」与「屋面板块」—— 小间在 ROOF 记录里没有独立块时按被盖计。
  · `语义.json` 里的「房间」是**分区**，不是产权房间；一个开敞大空间会被算成一个。
  · 挑空.json 不存在（本栋无对照件）⇒ ② 的「中庭」项**记 未量到**，
    剩余面积一律不许悄悄归给「中庭」（铁律 199）。
  · 本闸不判屋顶坡度/天窗/女儿墙。

输出：gates/_out/J-10.10-12.<栋>.json + .run.txt（经 `_verdict.emit`）
用法：python -X utf8 -I gates/J-10.10-12_未盖面积-露台加中庭对账.py [--bid c001]
退出码：0 通过 · 1 红 · 4 没量到
"""
from __future__ import annotations

import json
import os
import sys

from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
TOOLS = os.path.join(CDUT, "rebuild", "tools")
for p in (TOOLS, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import _verdict as VD                                                # noqa: E402

GATE = "J-10.10-12"
TOL_M2 = 1.0          # 总面积对账容差：120 mm 板厚在斜边上的离散远小于 1 m²
ROOM_TOL = 1.0        # 单房间残余容差（m²）；c001 实测非露台房间残余 = 0.000 m²

BLIND = [
    "只认平面投影：屋顶小间自带顶板，本闸不把它们从 ROOF 里单列",
    "语义.json 的「房间」是分区不是产权房间；开敞大空间算作一间",
    "无 挑空.json 时中庭项记「未量到」，剩余面积不归因给中庭",
    "不判屋面坡度/天窗/女儿墙高度",
]

_LOG = []


def log(s):
    _LOG.append(s)
    print(s)


class Missing(Exception):
    pass


def _geom(rec):
    try:
        return Polygon(rec["ring"], rec.get("holes") or []).buffer(0)
    except Exception:                                                # noqa: BLE001
        return None


def _area(rec):
    g = _geom(rec)
    return 0.0 if g is None else g.area / 1e6


def _rings(recs):
    return [g for g in (_geom(r) for r in recs) if g is not None and not g.is_empty]


def load(bid):
    import building as B
    try:
        P = VD.paths(bid)                                             # 未知楼栋在这里就炸
    except KeyError:
        raise Missing("本仓档案（楼栋.json）里没有 %s —— 不是这栋量错了，是没这栋" % bid)
    idx = P["index"]
    if not os.path.exists(idx):
        raise Missing("轮廓 index 不在：%s（先跑 export_contours）" % idx)
    with open(idx, encoding="utf-8") as fh:
        floors = [f["floor"] for f in json.load(fh)]
    try:
        B.profile(bid)                                                # 档案必须在
    except KeyError:
        # ★ 2026-10-20：未知楼栋原来直接 KeyError 崩掉 ⇒ rc=1，与「量到不对」同形
        #   （铁律 199）。这里改成 Missing ⇒ rc=4「没量到」：本仓档案里没这栋，
        #   不是这栋的屋顶错了。
        raise Missing("本仓档案（楼栋.json）里没有 %s —— 不是这栋量错了，是没这栋" % bid)
    top = floors[-1]
    cont = {}
    for nm in floors:
        p = os.path.join(P["contours"], nm + ".json")
        if not os.path.exists(p):
            raise Missing("轮廓件不在：%s" % p)
        with open(p, encoding="utf-8") as fh:
            cont[nm] = json.load(fh)
    sem = void = None
    sp = os.path.join(P["root"], "02_recognize", "语义.json")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as fh:
            sem = json.load(fh)
    vp = os.path.join(P["root"], "02_recognize", "挑空.json")
    if os.path.exists(vp):
        with open(vp, encoding="utf-8") as fh:
            void = json.load(fh)
    return P, floors, top, cont, sem, void


def _sem_floor(sem, nm):
    for f in (sem or {}).get("层") or []:
        if f.get("层") == nm:
            return f
    return None


def _void_floor(void, nm):
    for f in (void or {}).get("层") or []:
        if f.get("层") == nm:
            return f
    return None


def _void_geoms(vf):
    out = []
    for d in (vf or {}).get("洞") or []:
        g = _geom({"ring": d.get("ring") or []})
        if g is not None and not g.is_empty:
            out.append(g)
    return out


def judge(bid):
    P, floors, top, cont, sem, void = load(bid)
    log("楼栋 %s · 顶层 %s · 轮廓 %s" % (bid, top, P["contours"]))
    bad = []
    # ★ 2026-10-20：「没量到」和「量到不对」分两张表（铁律 199）。
    #   原来 ② 的两条「未量到」串塞进 `bad` ⇒ rc 被收成 1（FAIL），
    #   读起来像「件坏了」，其实是「溯源文件不在」。现在归 `unmeasured` ⇒ rc=4。
    unmeasured = []
    meas = dict()

    # ① 顶层必须有 ROOF
    roof_recs = [r for r in cont[top]["polys"] if r.get("layer") == "ROOF"]
    roof_a = sum(_area(r) for r in roof_recs)
    meas["顶层ROOF块"] = len(roof_recs)
    meas["顶层ROOF_m2"] = round(roof_a, 1)
    log("① 顶层 ROOF：%d 块 %.1f m²" % (len(roof_recs), roof_a))
    if not roof_recs:
        bad.append("① 顶层 %s 没有任何 ROOF 记录 ⇒ 屋顶层没建出来" % top)

    # ② 总面积对账
    slab_a = sum(_area(r) for r in cont[top]["polys"] if r.get("layer") == "SLAB")
    vf = _void_floor(void, top)
    void_here = sum(d.get("洞_m2") or 0.0 for d in (vf or {}).get("洞") or [])
    rvf = _void_floor(void, "屋面")
    roof_void = sum(d.get("洞_m2") or 0.0 for d in (rvf or {}).get("洞") or [])
    sf = _sem_floor(sem, top)
    terr = sum(sf.get("露台") or []) if sf else None
    plate = slab_a + void_here
    un = plate - roof_a
    meas.update(顶层板_m2=round(plate, 1), 顶层楼板_m2=round(slab_a, 1),
                顶层中庭洞_m2=round(void_here, 1), 屋面洞_m2=round(roof_void, 1),
                露台_m2=None if terr is None else round(terr, 1), 未盖_m2=round(un, 1))
    log("② 板 %.1f（楼板 %.1f + 中庭洞 %.1f）− ROOF %.1f = **未盖 %.1f**"
        % (plate, slab_a, void_here, roof_a, un))
    if terr is None:
        log("   ★ 露台项 未量到（无 语义.json 或该层露台表）⇒ 不把差额归因")
    if void is None:
        if un > TOL_M2:
            log("   ★ 中庭项 未量到（无 挑空.json）⇒ 剩余面积不归因，② 判 未量到")
            unmeasured.append("② 未量到：无挑空证据，未盖 %.1f m² 无法归因（不是「相符」）" % un)
        else:
            log("   ★ 中庭项 未量到（无 挑空.json），但未盖 = 0 ⇒ 没有面积需要归因")
    else:
        exp = (terr or 0.0) + roof_void
        d = un - exp
        meas.update(未盖_应得_m2=round(exp, 1), 未盖_差_m2=round(d, 1))
        log("   应得 = 露台 %s + 屋面洞 %.1f = %.1f ⇒ 差 **%+.1f m²**（容差 %.1f）"
            % ("未量到" if terr is None else "%.1f" % terr, roof_void, exp, d, TOL_M2))
        if terr is None:
            unmeasured.append("② 未量到：露台表不在，应得面积少一项")
        elif abs(d) > TOL_M2:
            bad.append("② 顶层未盖 %.1f m² ≠ 露台 %.1f + 中庭 %.1f（差 %+.1f m²）"
                       % (un, terr, roof_void, d))

    # ③ 逐房间：只在顶层楼板足迹内判（板已扣中庭洞 ⇒ 洞里不算「该有顶」）
    top_slab = unary_union(_rings([r for r in cont[top]["polys"]
                                   if r.get("layer") == "SLAB"]))
    cover = unary_union(_rings(roof_recs + [r for r in cont[top]["polys"]
                                            if r.get("layer") == "ROOF_ROOM"]))
    rooms = (sf or {}).get("房间") or []
    if sf is None:
        unmeasured.append("③ 未量到：无 语义.json（先跑 语义识别）")
    elif not rooms:
        unmeasured.append("③ 未量到：%s 一个分区都没有（语义识别没认出层？）" % top)
    n_ok = n_terr = n_out = 0
    nope, terr_rooms, edge_max = [], [], 0.0
    for i, rm in enumerate(rooms, 1):
        g = _geom(rm)
        if g is None or g.is_empty:
            continue
        need = g.intersection(top_slab)
        if need.is_empty or need.area < 1e6:                          # < 1 m² 不看
            n_out += 1
            continue
        res = need.difference(cover)
        ra = res.area / 1e6
        if rm.get("露台"):
            n_terr += 1
            terr_rooms.append((i, need.area / 1e6, ra))
            continue
        if ra <= ROOM_TOL:
            n_ok += 1
            edge_max = max(edge_max, ra)                              # 只报「最大残余」
        else:
            nope.append((i, need.area / 1e6, ra))
    meas.update(房间_有顶=n_ok, 房间_露台=n_terr, 房间_无顶=len(nope),
                房间_不在板内=n_out, 最大残余_m2=round(edge_max, 3))
    log("③ 顶层房间 %d 间（板外 %d 间不计）：有顶 %d · 露台 %d · **无顶 %d** · "
        "有顶房间最大残余 %.3f m²（容差 %.1f）"
        % (n_ok + n_terr + len(nope), n_out, n_ok, n_terr, len(nope), edge_max, ROOM_TOL))
    for i, a, ra in terr_rooms:
        log("   露台 #%d：板内 %.1f m²，无屋面 %.1f m²（应无顶）" % (i, a, ra))
    for i, a, ra in sorted(nope, key=lambda t: -t[2])[:12]:
        bad.append("③ 顶层房间 #%d 板内 %.1f m²，其中 **%.1f m² 没有屋面** ⇒ 该有顶却没有"
                   % (i, a, ra))
    if len(nope) > 12:
        log("   …另有 %d 间无顶（总数 %d，上面只列 12）" % (len(nope) - 12, len(nope)))
    return bad, unmeasured, meas, P


def main():
    bid = VD.bid_from()
    try:
        bad, unmeasured, meas, P = judge(bid)
    except Missing as e:
        log("SKIP：%s —— 「没量到」，不算过也不假报 FAIL（铁律 199）" % e)
        VD.emit(GATE, bid, None, 4, _LOG, blind=BLIND)
        return 4
    for u in unmeasured:
        log("… " + u)
    for b in bad:
        log("✗ " + b)
    if bad:
        ok, rc = False, 1
        log("J-10.10-12 总判：FAIL —— %d 条（见上）" % len(bad))
    elif unmeasured:
        ok, rc = None, 4
        log("J-10.10-12 总判：未量到 —— %d 项缺（不算过，也不当坏件）" % len(unmeasured))
    else:
        ok, rc = True, 0
        log("J-10.10-12 总判：PASS —— 顶层每一平米都能点名")
    # ★ 条目自己给（铁律 174：同一个量不许两个估计器）。
    #   不传的话 `_verdict.parse_items` 会把本闸**报读数**的 ①②③ 行当红串 ——
    #   2026-10-20 实测：PASS/rc=0 的闸在 JSON 里留下 3 条假红（闸账因此记成红）。
    items = VD.items_from_strings(GATE, bad) + VD.items_unmeasured(GATE, unmeasured)
    VD.emit(GATE, bid, ok, rc, _LOG, blind=BLIND,
            files={"contours": P["contours"], "index": P["index"]}, extra=meas,
            items=items)
    return rc


if __name__ == "__main__":
    sys.exit(main())
