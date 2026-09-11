# -*- coding: utf-8 -*-
"""R11/R12 宿舍公寓簇内墙解融批量(仅处理与 c031 同构的安全子集)。
前置(c031 验证过的假设): 非冻结 + 有薄外墙环(net outer<=14% outline, 且外墙带洞) + 内墙 blob
     (cover>20% 且 [条数<=8 或有单墙>楼板35%] —— 见 is_blob_floor())。
逐层 .orig 备份 -> 双线配对重建内墙 -> 数值验收 -> 不通过自动回滚该层。
安全门槛: 不符合前置的楼整栋跳过(不碰), 报告留给逐栋人工。冻结楼 c006/c009/c103/c104 永不碰。
验收(逐层，权威是 verify_floor() 的返回式): A 内墙条数>8  B 净覆盖<=20%  C 无单墙>楼板40%
     D 门贴墙>=85%(若该层有门)  E 房∩墙**均值<=10%**(若该层有房)
"""
import json, glob, os, sys, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import ezdxf
from run_building import load_profile
from backend.recognizer import classify
from backend.recognizer.profile import floor_of, to_local
from backend.recognizer import geometry as G
from backend.recognizer.component_library import is_door_symbol_pts
from backend.recognizer import curve_walls as CW
from shapely.geometry import Polygon, Point, LineString, box
from shapely.ops import unary_union

FROZEN = {"c006", "c009", "c103", "c104"}
ALL = sorted(os.listdir(r"D:\gym3d\data\buildings"))

def safe_union(polys):
    clean = []
    for P in polys:
        if P is None or P.is_empty:
            continue
        if not P.is_valid:
            P = P.buffer(0)
        if not P.is_valid or P.is_empty:
            continue
        clean.append(P)
    if not clean:
        return None
    try:
        U = unary_union(clean)
    except Exception:
        # 退而求其次逐个 buffer 后并
        U = None
        for P in clean:
            U = P if U is None else U.union(P.buffer(0))
    return U

def is_blob_floor(fl):
    inn = [w for w in fl["walls"] if w["type"] == "inner"]
    ol = Polygon(fl["outline"])
    if not inn or not ol.is_valid or ol.area < 1:
        return False
    U = safe_union([Polygon(w["poly"]) for w in inn])
    if U is None:
        return False
    cov = 100 * U.area / ol.area
    has_giant = any(Polygon(w["poly"]).area > 0.35 * ol.area for w in inn)
    return (cov > 20) and ((len(inn) <= 8) or has_giant)

def rebuild_floor(fl, p, raw, F):
    """返回新内墙列表; 失败返回 None。raw = 该层 DXF 墙线(已 to_local)。"""
    oline = Polygon(fl["outline"])
    outer = [w for w in fl["walls"] if w["type"] == "outer"]
    interior_mask = None
    if outer and outer[0].get("holes"):
        interior_mask = Polygon(outer[0]["holes"][0]).buffer(-0.01)
    if interior_mask is None:
        interior_mask = oline.buffer(-0.16)
    if not interior_mask.is_valid:
        interior_mask = interior_mask.buffer(0)
    # 楼梯踏步线/休息平台线（2 点水平短段，同 y 聚 >=4）与踏步端点连线不是墙：不剔除会
    # 与相邻踏步（间距 0.3m ∈ wall_min~wall_max）配成 0.3m 假墙塞满楼梯井（用户「楼梯识别成
    # 内墙」根因，同 _derive_paired_walls_and_outline 的剔除）。在「多段线粒度」先剔再拆段。
    _tread_idx = G._stair_tread_indices(raw)
    _mid_idx = G._stair_midline_indices(raw, _tread_idx)
    _keep = [loc for i, loc in enumerate(raw) if i not in _tread_idx and i not in _mid_idx]
    segs = G._flatten_wall_segments(_keep)
    if not segs:
        return None
    rects, singles = G.pair_wall_faces(segs, p)
    if getattr(p, "pair_curved", False):
        # 斜墙/曲墙(opt-in): 轴对齐段已由上面配走, 这里只吃斜段, 两边不重叠。
        # 厚度取两皮实测间距(该楼无 wall_thicknesses snap 时不冲突; 有 snap 的楼不启用本项)。
        _axis2, _diag = CW._flatten_all_segments(_keep)
        cr, cs = CW.pair_curved_faces(_diag, p)
        rects = list(rects) + list(cr)
        singles = list(singles) + list(cs)
    inner_walls = []
    rect_area = 0.0; total_area = 0.0
    for poly, t in rects:
        pc = poly.intersection(interior_mask).buffer(0)
        if pc.is_empty:
            continue
        for P in ([pc] if pc.geom_type == "Polygon" else list(pc.geoms)):
            if P.area > 0.03:
                rect_area += P.area
                inner_walls.append({"type": "inner",
                                    "poly": [[round(x, 3), round(y, 3)] for x, y in P.exterior.coords][:-1],
                                    "holes": [], "thickness": round(t, 2), "height": 4.2})
    for s in singles:
        pc = LineString(s).buffer(p.single_wall_t / 2).intersection(interior_mask).buffer(0)
        if pc.is_empty:
            continue
        for P in ([pc] if pc.geom_type == "Polygon" else list(pc.geoms)):
            if P.area > 0.03:
                inner_walls.append({"type": "inner",
                                    "poly": [[round(x, 3), round(y, 3)] for x, y in P.exterior.coords][:-1],
                                    "holes": [], "thickness": round(p.single_wall_t, 2), "height": 4.2})
    inner_walls = _punch_doors(inner_walls, fl)
    total_area = sum(Polygon(w["poly"]).area for w in inner_walls)
    rect_share = (rect_area / total_area) if total_area else 0
    return inner_walls, rect_share


def _punch_doors(inner_walls, fl):
    """把门洞从内墙里挖穿（门 = gap 不是 hole）。

    recognize 阶段 _door_boxes 已把「门洞盒」（深 = max(外墙厚,内墙厚)+0.05 > 墙厚）算好
    写在每个门的 bx0..by1。本函数把盒从重建出来的内墙上减掉 —— 否则 pair_wall_faces 配出的
    内墙是连续的，门板被封在实心墙里 = 用户报的「门有的夹在墙里看不到」。

    只在门带 bx0..by1 时生效：旧交付楼层没有这些字段 → 本函数是 no-op，改动不会波及
    未重识别的楼（当前仅 c006 带 bx0，而它在 FROZEN 里、永不进本脚本）。
    一次全局 difference 即可：盒落在墙上就切断，落在空处无副作用。
    """
    boxes = []
    for dd in fl.get("doors") or []:
        try:
            boxes.append(box(float(dd["bx0"]), float(dd["by0"]), float(dd["bx1"]), float(dd["by1"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not boxes:
        return inner_walls
    boxU = safe_union(boxes)
    if boxU is None:
        return inner_walls
    out = []
    for w in inner_walls:
        try:
            P = Polygon(w["poly"])
            if not P.is_valid:
                P = P.buffer(0)
            P = P.difference(boxU).buffer(0)
        except Exception:
            out.append(w)
            continue
        if P.is_empty:
            continue
        for Q in ([P] if P.geom_type == "Polygon" else list(P.geoms)):
            if Q.area <= 0.03:
                continue            # 与上面建墙同一面积门槛，避免门洞切出的碎屑
            nw = dict(w)
            nw["poly"] = [[round(x, 3), round(y, 3)] for x, y in Q.exterior.coords][:-1]
            nw["holes"] = [h for h in
                           ([[round(x, 3), round(y, 3)] for x, y in i.coords][:-1] for i in Q.interiors)
                           if len(h) >= 3]
            out.append(nw)
    return out


def verify_floor(fl, inner_walls, oline, ol_area):
    innerU = safe_union([Polygon(w["poly"]) for w in inner_walls]) if inner_walls else None
    inner_area = innerU.area if innerU else 0
    cover = 100 * inner_area / ol_area
    big = sum(1 for w in inner_walls if Polygon(w["poly"]).area > 0.4 * ol_area)
    otherU = safe_union([Polygon(w["poly"]) for w in fl["walls"] if w["type"] != "inner"]) if any(w["type"] != "inner" for w in fl["walls"]) else None
    if innerU is not None:
        wallU = innerU if otherU is None else safe_union([innerU, otherU])
    else:
        wallU = otherU
    nd = len(fl.get("doors", []))
    dgood_pct = 100
    if wallU is not None and nd:
        # <1.0m: 覆盖「门在洞中」直到 2m 双开门洞(中点距墙端<=1.0m); 真漏墙/浮门仍>1.0m 被拒
        dgood_pct = 100 * sum(1 for dd in fl["doors"] if wallU.distance(Point(dd["x"], dd["y"])) < 1.0) / nd
    ov_mean = 0
    rooms = [r for r in fl.get("rooms", []) if len(r.get("poly", [])) >= 3]
    if rooms and innerU is not None:
        vals = []
        for r in rooms:
            try:
                P = Polygon(r["poly"])
            except Exception:
                continue
            if P.is_valid and P.area > 0.5:
                vals.append(100 * P.intersection(innerU).area / P.area)
        ov_mean = sum(vals) / len(vals) if vals else 0
    ok = (len(inner_walls) > 8 and cover <= 20 and big == 0 and dgood_pct >= 85 and ov_mean <= 10)
    return ok, len(inner_walls), cover, big, dgood_pct, ov_mean

def wall_lines_by_floor(p, walls_dxf):
    """按楼层分墙线(本地米坐标)，并剔除「门符号」折线。

    门符号(门扇线 + 门垛的闭合环)和墙同图层，会被 pair_wall_faces 配成一块
    ~0.9~1.5m × 0.10~0.24m 的假墙，正盖在门洞位置上 —— 用户报的「门有的夹在墙里
    看不到」的根因(c019 每层约 285 块)。判门只看折线形状、不依赖这里，剔除不影响门识别。
    """
    out = {}
    for w in walls_dxf:
        cx = sum(a for a, b in w) / len(w)
        cy = sum(b for a, b in w) / len(w)
        F = int(round(floor_of(p, cx, cy)))
        loc = [(float(a), float(b)) for a, b in [to_local(p, a, b, F) for a, b in w]]
        if is_door_symbol_pts(loc):
            continue
        out.setdefault(F, []).append(loc)
    return out


def process(name):
    d = r"D:\gym3d\data\buildings\%s" % name
    fd = os.path.join(d, "floors")
    if not os.path.isdir(fd):
        return None, "无 floors"
    # 先找 blob 层(轻量, 不 classify): 无 blob 直接跳过
    blob_floors = []
    all_floors = []
    for fp in sorted(glob.glob(os.path.join(fd, "floor*.json"))):
        F = int(os.path.basename(fp)[5:-5])
        fl = json.load(open(fp, encoding="utf-8"))
        all_floors.append((fp, F, fl))
        if is_blob_floor(fl):
            blob_floors.append((fp, F))
    if not blob_floors:
        return None, "无blob层(已薄或异构, 跳过)"
    if not all_floors:
        return None, "无楼层"
    # 前置: 薄外墙环(用首层判断)
    first = all_floors[0][2]
    ol = Polygon(first["outline"])
    outers = [w for w in first["walls"] if w["type"] == "outer"]
    if not outers:
        return None, "无外墙类型(跳过-需逐栋分析)"
    try:
        onet = sum(Polygon(w["poly"]).area - sum(Polygon(h).area for h in w.get("holes", [])) for w in outers)
    except Exception:
        onet = 1e9
    if ol.is_valid and ol.area > 1 and onet / ol.area > 0.14:
        return None, "外墙net>14%或非薄环(跳过-需逐栋分析)"
    # 一次性 classify 并按层分墙线
    try:
        p = load_profile(name)
        doc = ezdxf.readfile(p.dxf)
    except Exception as e:
        return None, "DXF读失败 %s" % e
    msp = doc.modelspace()
    walls_dxf, doors, stairs, cols = classify.classify(msp, p)
    raw_by_floor = wall_lines_by_floor(p, walls_dxf)

    bak = os.path.join(d, ".orig", "floors.before_wallthin")
    os.makedirs(bak, exist_ok=True)
    ok_f, fail_f = [], []
    for fp, F in blob_floors:
        fl = json.load(open(fp, encoding="utf-8"))
        try:
            if not os.path.exists(os.path.join(bak, os.path.basename(fp))):
                shutil.copy2(fp, os.path.join(bak, os.path.basename(fp)))
            inner_walls, rect_share = rebuild_floor(fl, p, raw_by_floor.get(F, []), F)
            if inner_walls is None:
                fail_f.append((F, "无墙线")); continue
            olf = Polygon(fl["outline"])
            ok, nw, cover, big, dgood, ovm = verify_floor(fl, inner_walls, olf, olf.area)
            if not (ok and rect_share >= 0.30):
                fail_f.append((F, "nw=%d cov=%.0f%% big=%d door=%.0f%% ov=%.1f%% rect=%.0f%%"
                               % (nw, cover, big, dgood, ovm, 100 * rect_share)))
                continue
            keep = [w for w in fl["walls"] if w["type"] != "inner"]
            fl["walls"] = keep + inner_walls
            json.dump(fl, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
            ok_f.append((F, nw, cover))
        except Exception as e:
            fail_f.append((F, "异常:%s" % str(e)[:60]))
    return (ok_f, fail_f), None


if __name__ == "__main__":

    summary = []
    for name in ALL:
        if name in FROZEN:
            continue
        res, err = process(name)
        if err is not None:
            summary.append((name, "SKIP", err))
            continue
        ok_f, fail_f = res
        if ok_f:
            summary.append((name, "FIXED %d层" % len(ok_f),
                            "样例cover: " + ",".join("%.0f%%" % c for _, _, c in ok_f[:3])))
        else:
            summary.append((name, "SKIP", "全部blob层失败(已回滚)"))
        if fail_f:
            print("  %s 失败回滚层: %s" % (name, fail_f[:4]), flush=True)

    print("\n==== 批量结果 ====")
    for name, st, note in summary:
        print("%-6s %-12s %s" % (name, st, note))
