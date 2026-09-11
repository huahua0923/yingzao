# -*- coding: utf-8 -*-
"""结构体检 qa_structural.py — 楼层构件一致性「不变量门禁」。

专业判定依据（见 D:\\gym3d\\建模方法论·现状·缺口·专业优化路线.md 第三节）：
把「楼层错位排查·思路复盘.md」里人肉用的构件对应法固化成每次跑批必过的自动检查。
只读 floors/floor*.json，绝不改数据。

不变量清单（编号与文档对应）：
  I1  柱线在自身轮廓内        —— 柱中心跑到本层楼板轮廓外 = 悬空鳍（c103 F5 那类）
  I2  柱上下贯通（不悬空）     —— 上层的柱要么脚下有同轴柱，要么位于上层悬挑区（人工确认为转换/挑出）
  I3  房间都在本层轮廓内       —— 房间多边形外溢轮廓 = 怪胎房间（c103 每层 2800 点巨房那类）
  I4  内墙/隔墙不外溢         —— 墙身主体伸出外墙轮廓 >1.2m = 疑似室外构造（台阶/apron）混入墙 union
  I5  外扩带「空腔」提示       —— 下层比上层多出的轮廓带内无柱/无房/无内墙：疑似入口台阶/雨棚污染，或裙房屋面（正常可忽略）
  I6  天井/中庭孔洞登记        —— outline 内大孔：记录每层孔数/面积与跨层是否一致（回字楼）
  I7  同层重复柱               —— 同 (x,y) 多根柱 = 识别重复副本（无害但应知道）
  I8  体量堆叠登记             —— 逐层几何中心 vs F0：>3m 提示多翼/错列（INFO，非失败）
  I9  异形/弧面墙登记           —— 非正交斜段/疑似弧面墙（连续小转角多段）登记：
                                  弧面墙必须整体建模、窗沿弦/弧均布，不能按折线段当普通墙；
                                  斜墙（c103/c104 类）已知合法，仅 INFO 登记
  I10 柱在板外却在墙包络内      —— 一批柱落点超出楼板轮廓、却仍被墙凸包罩着：
                                  楼板疑似只盖了房间块、漏掉开放柱廊/柱区（c009 类），>10% 柱即 WARN
I1 严重度细分：地面层轮廓外柱=入口门廊/廊柱可能(WARN)；上层=悬空鳍(ERROR)。

用法：
  python qa_structural.py                 # 全部 data/buildings 楼，控制台只打汇总
  python qa_structural.py c103 c006       # 指定楼，打印该楼全部 ERROR/WARN
  python qa_structural.py --all-verbose   # 全部楼 + 每栋详情
逐栋完整报告写到 _qa/<name>_qa.txt。
"""
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

BASE = r"D:\gym3d\data\buildings"
QA_DIR = r"D:\gym3d\_qa"
TOL_COL = 0.3      # 柱是否在轮廓内 / 上下同轴 的容差(m)
TOL_DUP = 0.2      # 重复柱判定容差(m)
TOL_ROOM = 0.5     # 房间外溢轮廓容差(m)
WALL_OUT = 1.2     # 墙身主体伸出轮廓多少米算"疑似室外构造混入"
BAND_MIN_AREA = 30.0   # 外扩带面积下限(㎡) 才提示
BAND_MIN_W = 1.2       # 外扩带最小厚度(m)
CENT_SHIFT = 3.0       # 几何中心漂移提示阈值(m)
ATRIUM_AREA = 200.0    # 孔面积 ≥ 此值登记为天井/中庭


def _poly(coords):
    p = Polygon(coords)
    if not p.is_valid:
        p = p.buffer(0)
    return p


def under_recognized(floors):
    """欠识别判定：源图几乎没被识别成构件。
    判据(三重，避免误伤)：①每层平均实体墙 < 8 面 且 ②几乎无柱(avg<3，c027 类柱网满布的不算)
    且 ③板够大(>1500㎡，小塔楼不误伤)。
    例：c104 每层 2-6 面墙 + 0 柱撑 4000㎡、源 DXF 无结构柱层 → 待重建，其上 ERROR 是噪声不该判 FAIL；
    c027 墙也少(外墙常为少数长闭合环)但柱网 22/层 → 正常楼，不算。"""
    if not floors:
        return False
    plates = [_poly(g["outline"]).area for g in floors]
    mean_plate = sum(plates) / len(plates)
    wc = [sum(1 for w in g.get("walls", []) if w.get("type") != "parapet") for g in floors]
    mean_walls = sum(wc) / len(wc)
    cc = [len(g.get("columns", [])) for g in floors]
    mean_cols = sum(cc) / len(cc)
    return mean_walls < 8 and mean_cols < 3 and mean_plate > 1500


def load_floors(name):
    d = os.path.join(BASE, name, "floors")
    if not os.path.isdir(d):
        return []
    out = []
    for i in range(64):
        f = os.path.join(d, "floor%d.json" % i)
        if not os.path.isfile(f):
            break
        try:
            g = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if g.get("outline"):
            out.append(g)
    return out


# ---------- 单条 finding ----------
class Finding:
    def __init__(self, severity, inv, floor, msg, pos=None):
        self.severity = severity   # ERROR / WARN / INFO
        self.inv = inv             # I1..I8
        self.floor = floor
        self.msg = msg
        self.pos = pos             # (x,y) 可选

    def line(self):
        p = ("  @(%.2f, %.2f)" % self.pos) if self.pos else ""
        return "[%s] %s f%s %s%s" % (self.severity, self.inv, self.floor, self.msg, p)


# ---------- 各检查 ----------
def I1_col_in_own_outline(floors, fs):
    """柱脚下问一句(用户构件对应法)：板外柱是悬空鳍还是连续柱廊/转换？
    同 (x,y) 柱族只要"锚到"地面层(f0 有同轴柱=落基)或踩到某下层楼板 = 合法柱廊/转换/挑出，
        WARN 人工核即可(c006 门廊柱、c103 门廊柱同类)；柱族一路无柱无板直到起跳层才悬空
        = 真·悬空鳍(c103 F5、c009 f1)，ERROR 只在缺陷"起跳"层报一次(每柱族一条)，
        上面楼层同一悬空柱族的延续只合并成一条 INFO，不逐层逐根重复。"""
    order = sorted(floors, key=lambda x: x["floor"])
    # anchored = 已确认脚下有支撑的柱族(同轴下柱 或 下层板包住 或 落地面)。
    # f0 任何柱都立在地基/地面上 → 天然锚定该柱族(c006 门廊柱 f0 有同轴柱,整族合法)
    anchored = set()
    if order:
        g0 = order[0]
        anchored = {(round(c["x"] / TOL_DUP), round(c["y"] / TOL_DUP))
                    for c in g0.get("columns", [])}
    reported_jump = set()     # 已报过起跳的悬空柱族
    cont = {}                 # floor -> [(key,d)] 悬空柱族延续
    for g in order:
        fl = g["floor"]
        o = _poly(g["outline"])
        ob = o.buffer(TOL_COL)
        for c in g.get("columns", []):
            key = (round(c["x"] / TOL_DUP), round(c["y"] / TOL_DUP))
            pt = Point(c["x"], c["y"])
            if ob.contains(pt):
                anchored.add(key)
                continue
            d = o.exterior.distance(pt)
            if fl == 0:
                # 地面层：落在地上/地基，入口门廊/雨棚柱，人工确认即可
                fs.append(Finding("WARN", "I1", fl,
                                  "柱在自身轮廓外%.1fm(地面层:可能入口门廊/廊柱,人工核图纸)" % d,
                                  (c["x"], c["y"])))
                continue
            if key in anchored:
                # 同轴柱族已在下层锚定(落地柱廊或转换柱) → 合法柱廊的延续,人工核
                fs.append(Finding("WARN", "I1", fl,
                                  "柱在楼板轮廓外%.1fm但同轴柱族已锚定下层(通高门廊柱/转换,人工核)" % d,
                                  (c["x"], c["y"])))
                continue
            # 未锚定：查是否有下层楼板包住此点(= 脚踩下层板)
            on_slab = False
            for bg in order:
                if bg["floor"] >= fl:
                    break
                if _poly(bg["outline"]).buffer(TOL_COL).contains(pt):
                    on_slab = True
                    break
            if on_slab:
                anchored.add(key)
                fs.append(Finding("WARN", "I1", fl,
                                  "柱在楼板轮廓外%.1fm但脚下踩下层楼板(转换/挑出,人工核)" % d,
                                  (c["x"], c["y"])))
                continue
            # 真·悬空：柱族没落地也没落板。起跳层(首次出现)报 ERROR,上层同族只合并 INFO
            if key not in reported_jump:
                reported_jump.add(key)
                fs.append(Finding("ERROR", "I1", fl,
                                  "柱在楼板轮廓外%.1fm 且柱族无锚点无板(悬空鳍,缺陷起跳层)" % d,
                                  (c["x"], c["y"])))
            else:
                cont.setdefault(fl, []).append((key, d))
    for fl, items in sorted(cont.items()):
        n = len(items)
        fs.append(Finding("INFO", "I1", fl,
                          "悬空柱族延续 %d 根(同缺陷,已在起跳层报过,合并)" % n))


def I7_dup_columns(floors, fs):
    """同层重复柱按位置聚合到楼级：每处重复坐标报一次，注明出现在哪些层。"""
    loc_floors = {}   # (round x, round y) -> 楼层集合(出现重复的层)
    for g in floors:
        seen = set()
        for c in g.get("columns", []):
            key = (round(c["x"] / TOL_DUP), round(c["y"] / TOL_DUP))
            if key in seen:                       # 本层第二次同位置
                loc_floors.setdefault(key, set()).add(g["floor"])
            else:
                seen.add(key)
    for (kx, ky), flset in sorted(loc_floors.items()):
        fs.append(Finding("WARN", "I7", sorted(flset)[0],
                          "同位置重复柱(识别副本) @(%.2f,%.2f) 出现在楼层 %s" % (
                              kx * TOL_DUP, ky * TOL_DUP,
                              ",".join(map(str, sorted(flset))))))


def I2_col_through(floors, fs):
    """柱上下贯通(用户判据: 柱脚问下一层同位置有没有柱或板)。
    合法支撑 = 同轴下柱 **或** 脚下踩下层楼板(用户不变量原文"柱或明确的基础板")；
    只有两者皆无(悬空鳍/无支撑鳍, c103 F5 类)才报 WARN。改: 站下层板上的柱不再误报。
    跨层柱数抖动(均布楼识别不稳, c079 305/310/330…)聚合成楼级一条, 不逐柱刷屏。"""
    per_floor_cols = {}   # floor -> key 集合
    for g in floors:
        per_floor_cols[g["floor"]] = {(round(c["x"] / TOL_DUP), round(c["y"] / TOL_DUP))
                                      for c in g.get("columns", [])}
    floors_sorted = sorted(floors, key=lambda x: x["floor"])
    for a in range(len(floors_sorted) - 1):
        lo = floors_sorted[a]
        up = floors_sorted[a + 1]
        if not lo.get("columns") or not up.get("columns"):
            continue  # 某层没柱(可能只画部分层) → 无贯通信号，跳过避免噪音
        olo = _poly(lo["outline"]).buffer(TOL_COL)
        upo = _poly(up["outline"]).buffer(TOL_COL)
        lo_set = per_floor_cols[lo["floor"]]
        for c in up["columns"]:
            key = (round(c["x"] / TOL_DUP), round(c["y"] / TOL_DUP))
            if key in lo_set:
                continue
            pt = Point(c["x"], c["y"])
            if not upo.contains(pt):
                # 柱在自己楼层轮廓外 → I1 的悬空鳍/门廊柱判据负责，这里不重复报
                continue
            if not olo.contains(pt):
                # 柱在自己楼板内、脚下这层既无同轴柱也无板 → 上层内柱悬挑(退台/挑出),人工核
                fs.append(Finding("WARN", "I2", up["floor"],
                                  "上层内柱脚下无同轴柱也无下层板(退台/挑出,人工核) 下方f%d无板无柱" % lo["floor"],
                                  (c["x"], c["y"])))
            # 站下层板上(有板支撑) → 合法，不报
    # 楼级聚合：同脚印(同楼板面积)楼层组内柱数小幅抖动 = 均布楼识别不稳(吸柱候选)
    # 组间大落差(裙楼→塔楼 c006 30 vs 201 / c009 38 vs 168)是真结构或 I1/I8 已覆盖，不在此贴"识别不稳"
    groups = {}
    for g in floors_sorted:
        p = _poly(g["outline"])
        if not p or not p.is_valid:
            continue
        area = round(p.area)
        groups.setdefault(round(area / 20) * 20, []).append(g)
    for area_bucket, grp in groups.items():
        if len(grp) < 3:
            continue
        grp = sorted(grp, key=lambda x: x["floor"])
        counts = [len(g.get("columns", [])) for g in grp]
        mx, mn = max(counts), min(counts)
        if mx < 10 or mx - mn <= 10 or (mx - mn) / mx >= 0.4:
            continue
        fs.append(Finding("WARN", "I2", grp[0]["floor"],
                          "同脚印(~%dm²)楼层柱数小幅抖动 %d..%d(%s) — 均布楼柱网识别不稳,建议轴网吸柱"
                          % (area_bucket, mn, mx, "/".join(map(str, counts)))))


def I3_room_within_outline(floors, fs):
    for g in floors:
        fl = g["floor"]
        rooms = g.get("rooms", [])
        if not rooms:
            continue
        ob = _poly(g["outline"]).buffer(TOL_ROOM)
        for r in rooms:
            p = _poly(r["poly"])
            if p.is_empty or p.area <= 0:
                continue
            cut = p.difference(ob)
            if cut.area <= 0:
                continue
            frac = cut.area / p.area
            if frac > 0.25 or cut.area > 25:      # 大面积外溢 = 怪胎房间(楼层没裁进轮廓)
                fs.append(Finding("ERROR", "I3", fl,
                                  "房间大面积外溢楼板轮廓 %.0f%% (面积%.0f㎡) 房间%.0f㎡" % (
                                      frac * 100, cut.area, p.area),
                                  (p.centroid.x, p.centroid.y)))
            elif cut.area > 2 and frac > 0.05:     # 边缘贴外墙的微小溢出 = 轮廓取线偏移，无害
                fs.append(Finding("WARN", "I3", fl,
                                  "房间边缘微溢轮廓 %.0f%% (%.0f㎡,贴外墙偏移多半无害)" % (
                                      frac * 100, cut.area),
                                  (p.centroid.x, p.centroid.y)))


def I4_walls_not_outside(floors, fs):
    for g in floors:
        fl = g["floor"]
        o = _poly(g["outline"])
        ob = o.buffer(WALL_OUT)
        for w in g.get("walls", []):
            if w.get("type") == "parapet":
                continue
            p = _poly(w["poly"])
            if p.is_empty or p.area <= 0:
                continue
            cut = p.difference(ob)
            if cut.area > 0.15 * p.area and cut.area > 2.0:
                fs.append(Finding("WARN", "I4", fl,
                                  "墙身主体在轮廓外>%.1fm(疑似室外构造混入union) 外溢%.0f㎡" % (
                                      WALL_OUT, cut.area),
                                  (p.centroid.x, p.centroid.y)))


def I5_empty_dropband(floors, fs):
    """下层 outline 比上层多出的带；带内无柱无房无内墙 → 空腔提示。"""
    for a in range(len(floors) - 1):
        lo = floors[a]
        up = floors[a + 1]
        lo_o = _poly(lo["outline"])
        up_o = _poly(up["outline"])
        if lo_o.equals(up_o):
            continue
        band = lo_o.difference(up_o.buffer(TOL_COL))
        if band.is_empty:
            continue
        band_area = band.area
        # 厚度近似 = 面积/最长轴周长的一半太长，改用 bbox 里至少一个方向差
        lb, ub = lo_o.bounds, up_o.buffer(TOL_COL).bounds
        dw = max(ub[0] - lb[0], lb[2] - ub[2], ub[1] - lb[1], lb[3] - ub[3])
        if band_area < BAND_MIN_AREA or dw < BAND_MIN_W:
            continue
        cols = [Point(c["x"], c["y"]) for c in lo.get("columns", [])]
        rooms = [_poly(r["poly"]) for r in lo.get("rooms", [])]
        walls = [(_poly(w["poly"]), w.get("type")) for w in lo.get("walls", [])]
        has_struct = any(band.contains(p) or band.intersects(p) for p in cols)
        has_room = any(band.intersects(r) and band.intersection(r).area > 5 for r in rooms)
        has_inner = any(
            (typ in (None, "inner")) and band.intersection(p).area > 2 for p, typ in walls)
        if not has_struct and not has_room and not has_inner:
            fs.append(Finding("WARN", "I5", lo["floor"],
                              "外扩带空腔: 比上层多%.0f㎡ 厚%.1fm 无柱/房/内墙"
                              " (疑似入口台阶/apron污染; 若为裙房屋面则正常可忽略)" % (
                                  band_area, dw)))


def I6_atrium(floors, fs, verbose):
    for g in floors:
        fl = g["floor"]
        o = _poly(g["outline"])
        for hi, h in enumerate(o.interiors):
            hp = Polygon(h)
            if hp.area >= ATRIUM_AREA:
                if verbose:
                    fs.append(Finding("INFO", "I6", fl,
                                      "天井/中庭孔 #%d 面积%.0f㎡ x[%.1f..%.1f]y[%.1f..%.1f]" % (
                                          hi, hp.area, *hp.bounds)))


def I8_stacking(floors, fs, verbose):
    if not floors:
        return
    b0 = _poly(floors[0]["outline"]).bounds
    c0 = ((b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2)
    for g in floors:
        b = _poly(g["outline"]).bounds
        c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        dist = math.hypot(c[0] - c0[0], c[1] - c0[1])
        if dist > CENT_SHIFT:
            fs.append(Finding("WARN", "I8", g["floor"],
                              "几何中心距F0偏移%.1fm(多翼/错列? 对照包围盒看嵌套)" % dist, c))


# 方向量测:段方位角(度, 0-360), 两段间转角(-180..180)
def _heading(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360


def _turn(h1, h2):
    return (h2 - h1 + 180) % 360 - 180


def I10_col_beyond_plate_inside_hull(floors, fs):
    """楼板疑似漏盖开放柱区：柱落点在板轮廓外、却被墙凸包罩着 → 那批柱脚下本应有板。
    正常楼(凹形楼)柱都包在板里；c009 类"板只盖房间块"会命中。"""
    for g in floors:
        fl = g["floor"]
        cols = g.get("columns", [])
        walls = [(_poly(w["poly"])) for w in g.get("walls", []) if w.get("type") != "parapet"]
        if not cols or not walls:
            continue
        ob = _poly(g["outline"]).buffer(0.5)
        try:
            hull = unary_union(walls).convex_hull.buffer(2.0)
        except Exception:
            continue
        out = [c for c in cols if not ob.contains(Point(c["x"], c["y"]))
               and hull.contains(Point(c["x"], c["y"]))]
        if out and len(out) >= 3 and len(out) / len(cols) > 0.1:
            fs.append(Finding("WARN", "I10", fl,
                              "%d/%d 柱在板轮廓外却在墙包络内 → 楼板疑似只盖房间块,漏了开放柱廊/柱区" % (
                                  len(out), len(cols))))


def I9_irregular_walls(floors, fs):
    """异形/弧面墙登记：非正交斜墙 INFO；连续同向小转角多段 = 疑似弧面墙 WARN。
    弧面/曲墙（礼堂半圆后墙、门厅弧墙、圆环）若被当若干直线墙段: 配对碎、窗按段布、
    外轮廓呈多边形锯口 → 必须整体按弧建模。斜墙(c103/c104)已验证合法只登记。"""
    for g in floors:
        fl = g["floor"]
        ang_len = 0.0
        ang_seg = 0
        for w in g.get("walls", []):
            cs = w.get("poly", [])
            if len(cs) < 3:
                continue
            segs = [_heading(cs[i], cs[i + 1]) for i in range(len(cs) - 1)]
            # 斜向段: 偏离正交 > 5°(容差取正交±5)
            for i in range(len(cs) - 1):
                s = segs[i]
                near_ax = any(abs((s - a + 180) % 360 - 180) <= 5.0
                              for a in (0.0, 90.0, 180.0, 270.0))
                if not near_ax:
                    ang_seg += 1
                    ang_len += math.hypot(cs[i + 1][0] - cs[i][0], cs[i + 1][1] - cs[i][1])
            # 疑似弧面: >=8 段且转角序列同号、逐转 0.5~15°、弓高占比可观
            if len(segs) >= 7:
                turns = [_turn(segs[i], segs[i + 1]) for i in range(len(segs) - 1)]
                if turns and (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
                    ma = sum(abs(t) for t in turns) / len(turns)
                    if 0.5 <= ma <= 15.0:
                        ln = max(math.hypot(cs[0][0] - cs[-1][0], cs[0][1] - cs[-1][1]), 1e-9)
                        sag = 0.0
                        x0, y0, x1, y1 = cs[0][0], cs[0][1], cs[-1][0], cs[-1][1]
                        A, B, C = y1 - y0, x0 - x1, x1 * y0 - x0 * y1
                        den = math.hypot(A, B) or 1e-9
                        for (px, py) in cs[1:-1]:
                            sag = max(sag, abs(A * px + B * py + C) / den)
                        if sag > 0.04 * ln:
                            fs.append(Finding("WARN", "I9", fl,
                                              "疑似弧面/曲墙: %d段 长%.1fm 弓高%.1fm"
                                              " — 应整体建弧/曲面并按弧布窗,勿按折线段" % (
                                                  len(cs), ln, sag)))
        if ang_seg:
            fs.append(Finding("INFO", "I9", fl,
                              "斜向墙段 %d 处(约%.0fm, 斜墙/切角合法, 登记)" % (ang_seg, ang_len)))


def check_building(name, verbose):
    fs = []
    floors = load_floors(name)
    if not floors:
        return None, []
    for g in floors:
        if "floor" not in g:
            g["floor"] = int(g.get("floor", 0))
    I1_col_in_own_outline(floors, fs)
    I7_dup_columns(floors, fs)
    I2_col_through(floors, fs)
    I3_room_within_outline(floors, fs)
    I4_walls_not_outside(floors, fs)
    I5_empty_dropband(floors, fs)
    I6_atrium(floors, fs, verbose)
    I8_stacking(floors, fs, verbose)
    I9_irregular_walls(floors, fs)
    I10_col_beyond_plate_inside_hull(floors, fs)
    return floors, fs


def main():
    args = sys.argv[1:]
    verbose_all = "--all-verbose" in args
    args = [a for a in args if not a.startswith("--")]
    names = args or sorted(d for d in os.listdir(BASE)
                           if os.path.isdir(os.path.join(BASE, d))
                           and os.path.exists(os.path.join(BASE, d, "profile.json")))
    os.makedirs(QA_DIR, exist_ok=True)
    summary = []
    for name in names:
        floors, fs = check_building(name, verbose_all)
        if floors is None:
            summary.append((name, "-", "no floors", False))
            continue
        ur = under_recognized(floors)
        raw_errs = [f for f in fs if f.severity == "ERROR"]
        # 欠识别楼只有真产生了 ERROR 才降级：稀疏但内部自洽(0错误)的楼(低LOD壳/板房)
        # 本就 PASS，不该被误标"待重建"。有 ERROR 的 c104 类 = 识别残缺 → 噪声降 WARN 不判 FAIL。
        ua = ur and bool(raw_errs)
        if ua:
            for f in fs:
                if f.severity == "ERROR":
                    f.severity = "WARN"
                    f.msg = "(欠识别待重建) " + f.msg
            fs.append(Finding("INFO", "UA", 0,
                              "欠识别待重建：每层仅平均墙<8 面撑大板(源图可能缺墙/柱层)——其上告警是欠识别噪声，不判 FAIL"))
        errs = [f for f in fs if f.severity == "ERROR"]
        warns = [f for f in fs if f.severity == "WARN"]
        summary.append((name, len(floors), len(errs), len(warns), ua))
        # 写逐栋报告
        with open(os.path.join(QA_DIR, name + "_qa.txt"), "w", encoding="utf-8") as fh:
            fh.write("结构体检 qa_structural.py — %s (%d 层)\n" % (name, len(floors)))
            for g in floors:
                b = _poly(g["outline"]).bounds
                fh.write("  f%d bbox x[%.1f..%.1f] y[%.1f..%.1f] 柱%d 房%d\n" % (
                    g["floor"], b[0], b[2], b[1], b[3],
                    len(g.get("columns", [])), len(g.get("rooms", []))))
            fh.write("\n")
            if not fs:
                fh.write("(无 ERROR/WARN)\n")
            for f in fs:
                if f.severity != "INFO" or verbose_all:
                    fh.write(f.line() + "\n")
        # 控制台：指定楼或 all-verbose 打印详情
        if args or verbose_all:
            print("=" * 74)
            print("%s (%d 层)%s:" % (name, len(floors), "  [欠识别待重建]" if ur else ""))
            for f in fs:
                if f.severity != "INFO" or verbose_all:
                    print("  " + f.line())
    # 汇总
    print("\n" + "=" * 74)
    print("结构体检汇总 (ERROR=必改 WARN=人工核 UA=欠识别待重建不计FAIL)")
    print("%-6s %4s %7s %7s  %s" % ("楼", "层数", "ERROR", "WARN", "状态"))
    nerr = nwarn = nfail = 0
    for s in summary:
        if len(s) == 3:
            print("%-6s %4s  无 floors" % (s[0], "-"))
            continue
        name, nf, e, w, ur = s
        nerr += e; nwarn += w
        st = "UNDER欠识别" if ur else ("FAIL" if e else ("CAUTION" if w else "PASS"))
        if e and not ur:
            nfail += 1
        print("%-6s %4d %7d %7d  %s" % (name, nf, e, w, st))
    print("-" * 74)
    print("合计 ERROR=%d WARN=%d  FAIL 楼=%d/%d" % (nerr, nwarn, nfail, len(summary)))
    print("逐栋报告在 _qa/<楼>_qa.txt")


if __name__ == "__main__":
    main()
