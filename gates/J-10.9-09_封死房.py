# -*- coding: utf-8 -*-
r"""判据 J-10.9-09：**封死房** —— 一间房四周都是墙、一处也贴不到门洞框。

为什么要有它（2026-10-18 用户「办公楼和理化楼的门少了，你识别一下」）：
  「门少了几樘」不能用「数门」证明 —— 图纸上本来有多少樘不是现成可数的。
  有分辨力的问法是：把**已认出来的门**也并进墙里（堵死），剩下的自由域被切成房间；
  某块房间**一处也贴不到任一门洞框** ⇒ 这间在模型上封死。点名到房间，不报个数了事。

判据
 ① 每层：墙带 ∪ 门洞框 = 堵死的墙网；楼板外框减掉它 ⇒ 自由域分区
    （面积 ≥ 2 m²；贴着最外框那一块是室外，剔掉）。
 ② 与任一门洞框距离 ≤ 100 mm 的块 = 有门；否则 = 封死房。
 ③ 封死房必须逐条出现在**声明** `rebuild/构件库/楼栋.json::<bid>.sealed_rooms` 里
    （条目 = 层 / 质心 / 面积 / 理由），容差 质心 1500 mm、面积 0.3 m²。
 ④ 反向：声明里的每一条都必须在读数里找得到 ⇒ 房间被修好后旧声明会**红**（白名单不许自己烂掉）。

量具：`redraw.geometry(层)::door_voids` + `build3d.wall_polys`；层名单取 `01_cad/raw/*.dxf`。
盲区（★先声明）：
 · 门洞框只来自**已认出的门** —— 画法没认出来的门，这里和模型上一样看不见；
   本闸**不替代**识别环节的判据（它只保证「认出来的门真的通到每个房间」）。
 · 只量平面：竖向的洞（楼梯间通高、天窗、挑空）不在本闸。
 · 面积 < 2 m² 不报：管井/壁龛与墙体空腔在这一档分不开。
 · 只测几何闭合，不测门的可用性（门后是不是墙、扇装不装得下是别的闸）。

三态：rc=0 PASS ／ rc=1 FAIL ／ rc=4 SKIP（raw DXF / 楼栋.json / build3d 不在）

用法：python -X utf8 -I gates/J-10.9-09_封死房.py --bid c004
"""
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT0 = r"D:\项目\cdut3d"
PROFILE = os.path.join(ROOT0, "rebuild", "构件库", "楼栋.json")
OUTD = os.path.join(HERE, "_out")

TOL_MM = 100.0            # 房间与门洞框的距离容差
MIN_AREA_M2 = 2.0         # 小于它的不报（管井/壁龛档）
MATCH_C_MM = 1500.0       # 声明/读数 质心匹配容差
MATCH_A_M2 = 0.3          # 声明/读数 面积匹配容差
LOG = []


def log(s):
    print(s)
    LOG.append(s)


def _rounds(rooms):
    return [{"层": fl, "质心": [round(c[0], 0), round(c[1], 0)],
             "面积_m2": round(a / 1e6, 2),
             "外框": [round(b[2] - b[0], 0), round(b[3] - b[1], 0)]}
            for fl, c, a, b in rooms]


def sealed_rooms_of(fl, shapely, Polygon, RD, B3):
    """一层的封死房：[(层, 质心(x,y), 面积 mm², bounds)]；没有门洞框时返回 None（量不了）。

    ★ 自由域只在**楼板轮廓** `v["plate"]` 里算。上一版拿「墙带外框 ±2 m 的盒子」减墙带，
      **盒子里的楼外空域也会被当成房间**：c005 3/4 层在 y≈72.8 m 处报出 8 间 18.5 m²
      「封死房」，而那里根本没有楼板（3 层平面 y 最大约 60 m）—— 是尺子自己造出来的。
    """
    v = RD.geometry(fl)
    wp = B3.wall_polys(v)
    rects = v.get("door_voids") or []
    if not rects:
        return None                      # 「没门洞框」≠「没封死房」，是**这把尺子量不了**
    plate = shapely.unary_union(B3.slab_polys(v))
    if plate.is_empty:
        return None                      # 没有楼板轮廓 ⇒ 分不清楼内楼外，量不了
    doors = [Polygon(r) for r in rects]
    W = shapely.unary_union(wp + doors)
    free = plate.difference(W)
    D = shapely.unary_union(doors).buffer(TOL_MM)
    out = []
    for g in getattr(free, "geoms", [free]):
        if g.is_empty or g.area < MIN_AREA_M2 * 1e6:
            continue
        if g.distance(D) > 1.0:          # D 已 buffer 过 TOL_MM，留 1 mm 给数值噪声
            c = g.centroid
            out.append((fl, (c.x, c.y), g.area, g.bounds))
    return out


def main():
    argv = sys.argv[1:]
    bid = argv[argv.index("--bid") + 1] if "--bid" in argv else "c006"
    os.environ["CDUT_BUILDING"] = bid
    sys.path.insert(0, os.path.join(ROOT0, "rebuild", "tools"))
    import building as B
    root = B.root_for(bid)
    os.environ["CDUT_REBUILD_ROOT"] = root
    # ★ building.ROOT 是 **import 时**从环境读一次就定死的；`redraw` 又写 `ROOT = B.ROOT`。
    #   本闸必须先 import building 才能问到 `root_for()`，所以问完要**重载一次**，
    #   否则 c004 会去读 c006 的根（实测报 `rebuild/01_cad/raw/1.dxf` 不存在）。
    import importlib
    importlib.reload(B)
    RAW = os.path.join(B.ROOT, "01_cad", "raw")
    out = argv[argv.index("--out") + 1] if "--out" in argv else \
        os.path.join(OUTD, "J-10.9-09_%s.json" % bid)

    log("J-10.9-09 · 封死房（楼栋 %s ｜ 根 %s）" % (bid, root))
    lack = [p for p in (PROFILE, RAW) if not os.path.exists(p)]
    raw_files = sorted(glob.glob(os.path.join(RAW, "*.dxf")))
    if lack or not raw_files:
        log("★ 没量到：缺 %s ⇒ SKIP(rc=4)"
            % ([os.path.basename(p) for p in lack] or [RAW]))
        return finish(4, out, {"bid": bid, "missing": len(lack) + (0 if raw_files else 1)})

    import shapely
    from shapely.geometry import Polygon
    import redraw as RD
    import build3d as B3

    prof = json.load(open(PROFILE, encoding="utf-8"))
    decl = (prof.get(bid) or {}).get("sealed_rooms") or []

    floors, unmeasurable = [], []
    for p in raw_files:
        fl = os.path.basename(p)[:-4]
        got = sealed_rooms_of(fl, shapely, Polygon, RD, B3)
        if got is None:
            unmeasurable.append(fl)
            continue
        floors.append((fl, got))
        log("  层 %-4s 门洞框 %3d ｜ **封死** %d"
            % (fl, len(RD.geometry(fl).get("door_voids") or []), len(got)))
        for fl2, c, a, b in got:
            log("      封死房 (%7.0f,%7.0f) 面积 %7.1f m2  外框 %.0f×%.0f"
                % (c[0], c[1], a / 1e6, b[2] - b[0], b[3] - b[1]))

    all_rooms = [r for _, rows in floors for r in rows]
    # ③ 读数里每一条都要有声明
    bad = []
    unused = list(range(len(decl)))
    for fl, c, a, b in all_rooms:
        hit = None
        for k, d in enumerate(decl):
            if d.get("层") != fl:
                continue
            dc = ((d["质心"][0] - c[0]) ** 2 + (d["质心"][1] - c[1]) ** 2) ** 0.5
            if dc <= MATCH_C_MM and abs(d["面积_m2"] - a / 1e6) <= MATCH_A_M2:
                hit = k
                break
        if hit is None:
            bad.append("未声明 层 %s 封死房 (%.0f,%.0f) %.1f m2 —— 一间房四面墙、一处门也贴不到"
                       % (fl, c[0], c[1], a / 1e6))
        else:
            unused.remove(hit)
    # ④ 声明里没被读数命中的 —— 房间修好了却还留着白名单
    for k in unused:
        d = decl[k]
        bad.append("声明过期 层 %s 质心 %s 面积 %s m2（理由：%s）—— 读数里已找不到这间封死房"
                   % (d.get("层"), d.get("质心"), d.get("面积_m2"), d.get("理由", "")))

    if unmeasurable:
        log("★ %s 层没有门洞框 ⇒ 该层本闸量不了（按「没门」建，另由识别环节的闸管）"
            % "、".join(unmeasurable))
    log("-" * 78)
    log("读数：%d 层 ｜ 封死房 %d 间 ｜ 声明 %d 条 ｜ 未声明 %d ｜ 声明过期 %d"
        % (len(floors), len(all_rooms), len(decl),
           sum(1 for x in bad if x.startswith("未声明")),
           sum(1 for x in bad if x.startswith("声明过期"))))
    for x in bad:
        log("  ✘ " + x)

    rc = 0 if not bad else 1
    log("判词：%s" % ("PASS —— 每间房都贴得到门洞框（或已声明是管井/竖井）" if rc == 0
                     else "FAIL —— %d 条不合规" % len(bad)))
    return finish(rc, out, {"bid": bid, "floors": _rounds(all_rooms),
                            "declared": decl, "violations": bad,
                            "unmeasurable": unmeasurable})


def finish(rc, out, readings):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"pass": rc == 0, "rc": rc, **readings, "log": LOG},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写出 %s（rc=%d）" % (out, rc))
    return rc


if __name__ == "__main__":
    sys.exit(main())
