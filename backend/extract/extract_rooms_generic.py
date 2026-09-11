# -*- coding: utf-8 -*-
"""通用房间提取器：按 profile.classifier 分派，兼容 LWPOLYLINE 与 LINE+INSERT 两套约定。

与 extract_rooms.py（理化楼硬编码基线）、extract_rooms_c006.py（六教专版）并列。
本脚本是「房间提取管线」的唯一通用入口，逐栋复用同一套几何 + 标注关联逻辑：

  - 墙/门几何：classifier=='line' → classify_line（墙=LINE 双线、门=INSERT 块）；
                否则 → classify（墙=LWPOLYLINE，门由 detect_doors 几何判定）。
  - 房间边界：outline（derive_walls_and_outline）- wall_geoms - 门洞补丁（门盒补闭）。
  - 标注层：按资产管理图国标层名「数字前缀」定位（5面积/6房间号/7用途/8单位），
    天然免疫 ODA 转换产生的层名乱码（代理项 surrogate）；中文编码 UTF-8。
  - 过渡层 wall_x 过滤：与 floor.py / recognize.py 同口径（如六教第 7 层只取塔楼墙）。

用法:
  python backend/extract/extract_rooms_generic.py c009            # 写该楼 rooms.json
  python backend/extract/extract_rooms_generic.py c009 --dry      # 只打印统计
  python backend/extract/extract_rooms_generic.py --all --dry     # 全楼普查
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import ensure_sys_path  # noqa: E402

ensure_sys_path()                    # 仓库根：run_building.py 等入口在这
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ezdxf
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union

from run_building import load_profile
from recognizer.geometry import derive_walls_and_outline, detect_doors
from recognizer.floor import reference_outline_for, unify_floor_set, outline_for_floor
from recognizer.profile import to_local, floor_of

ENCODING = "utf-8"   # ODA 转换器写出的教学楼 DXF 中文标注是 UTF-8（房间号/面积 ASCII 不受影响）

# 每楼房间 id 全局唯一偏移（理化楼基线 1..118；教学楼各占 100000 一段）
ID_BASE = {
    "c006": 100000, "c009": 200000, "c022": 300000, "c025": 400000,
    "c026": 500000, "c027": 600000, "c028": 700000, "c041": 800000,
    "c103": 900000, "c104": 1000000, "c114": 1100000, "c108": 1200000,
    # 宿舍/公寓簇（芙蓉园 c017-c034、西区公寓 c079-086、南苑 ny27-29 等面积图式：
    # 单线墙+MTEXT标注，无柱层）：id 段 2000000 起，每楼 10 万段防 DB 主键撞车
    "c031": 2000000, "c017": 2100000, "c018": 2200000, "c019": 2300000,
    "c029": 2400000, "c030": 2500000, "c032": 2600000, "c033": 2700000,
    "c034": 2800000, "c043": 2900000, "c044": 3000000, "c045": 3100000,
    "c046": 3200000, "c054": 3300000, "c055": 3400000, "c056": 3500000,
    "c057": 3600000, "c059": 3700000, "c060": 3800000, "c061": 3900000,
    "c062": 4000000, "c063": 4100000, "c064": 4200000, "c065": 4300000,
    "c072": 4400000, "c073": 4500000, "c079": 4600000, "c080": 4700000,
    "c083": 4800000, "c084": 4900000, "c085": 5000000, "c086": 5100000,
    "c109": 5200000, "c116": 5300000, "ny27": 5400000, "ny28": 5500000,
    "ny29": 5600000,
}

# 资产管理图国标层名数字前缀 → 语义。逐栋可能不同（如 c006 7=用途/8=单位；
# 理化楼老图 7=使用单位/8=用途），可在下方 LAYER_ROLE_OVERRIDE 覆盖。
LAYER_ROLE = {"5": "area", "6": "number", "7": "purpose", "8": "dept"}
LAYER_ROLE_OVERRIDE = {
    # 例：若某楼 7/8 语义颠倒，写 "c0xx": {"7": "dept", "8": "purpose"}
    # c009/c022 的图层是「7使用单位 / 8用途」（与 c006 的「7用途 / 8单位」相反），
    # 默认 LAYER_ROLE 按 c006 口径，故这两栋需颠倒 7/8。
    "c009": {"7": "dept", "8": "purpose"},
    "c022": {"7": "dept", "8": "purpose"},
    # c114（第十教学楼·启智楼）：无 7 层，唯一标注层「8房间用途」内容是房间用途
    #   （实验室/会议室/教研室/办公室），默认 8→dept 会错放「单位」列，改为 8→purpose。
    "c114": {"8": "purpose"},
    # c031（芙蓉园3号公寓）：层名 7使用单位 / 8房间用途（与 c006 的 7用途/8单位 相反），
    #   默认 LAYER_ROLE 会把 单位↔用途 互换，须颠倒。楼层 5面积/6房间号 语义不变。
    "c031": {"7": "dept", "8": "purpose"},
    # c104（第十二教学楼·东2教）：仅 7 层「使用单位」但内容是用途（多媒体教室/值班室等），
    #   默认 7→purpose 已正确，无需覆盖。
}

MIN_ROOM_AREA = 1.0
DOOR_PLUG_DEPTH = 0.4
# 标注点→房间多边形的容差（米）。房号 MTEXT 的 attachment_point=1(左上)：insert 是文本
# 左上角、文字向右下延展；锚点落在墙带（被 carve 掉）上、悬在房间多边形外 ~150mm。现在
# 已改用文本几何中心（mtext_center）当标注点，中心在房间内部，故只需很小的兜底容差
# （覆盖字宽估算误差）。0.2m 大容差会在密集小房间楼（c104）误匹配相邻房间（实测歧义 9）。
LABEL_TOL = 0.1


def clean(s):
    s = re.sub(r"\\[A-Za-z][^;]*;", "", s)
    s = s.replace("{", "").replace("}", "")
    s = s.replace("\\P", " ")  # MTEXT 段内换行 → 空格（如「教师工作室\P实验准备室」）
    s = s.replace("\\", "")
    return " ".join(s.split())


def mtext_center(e):
    """MTEXT 标注的几何中心（CAD 毫米）。attachment_point=1(左上) 时 insert 是文本左上角、
    文字向右下延展；房号锚点落在墙带（被 carve 掉）上、悬在房间多边形外 ~150mm。改用文本
    中心（锚点右移半宽、下移半高）→ 落点进入房间内部，无需大容差 buffer，避免密集小房间
    （c104）被大容差误匹配相邻房间。文本宽按可见字符数 × 字高 × 0.55 估算（CAD SHX 字宽
    高比 ≈ 0.55），高按行数 × 字高（房号单行，高 = char_height）。
    返回 (cx, cy, cleaned_text)。"""
    ap = e.dxf.attachment_point
    ch = e.dxf.char_height
    ins = e.dxf.insert
    lines = [clean(ln) for ln in (e.text or "").split("\\P")]
    n = max((len(ln) for ln in lines), default=0)
    W = n * ch * 0.55
    H = ch * max(len(lines), 1)
    x0, y0 = ins.x, ins.y
    # 水平：列 2/5/8 居中、3/6/9 右对齐、1/4/7 左对齐
    if ap in (2, 5, 8):
        cx = x0
    elif ap in (3, 6, 9):
        cx = x0 - W / 2
    else:
        cx = x0 + W / 2
    # 垂直：行 1/2/3 顶、4/5/6 中、7/8/9 底
    if ap in (1, 2, 3):
        cy = y0 - H / 2
    elif ap in (7, 8, 9):
        cy = y0 + H / 2
    else:
        cy = y0
    text = " ".join("".join(lines).split())
    return cx, cy, text


def read_labels(msp, role_map):
    """收集各语义层标注。role_map 键 = 精确层名；值 = area/number/purpose/dept。
    精确层名优先，其次层名数字前缀（老楼约定 5/6/7/8）。"""
    labels = {"area": [], "number": [], "purpose": [], "dept": []}
    for e in msp:
        if e.dxftype() != "MTEXT":
            continue
        l = e.dxf.layer or ""
        role = None
        if l in role_map:
            role = role_map[l]
        elif l and l[:1] in role_map:
            role = role_map[l[:1]]
        if not role:
            continue
        cx, cy, text = mtext_center(e)
        labels[role].append((cx, cy, text))
    return labels


def layer_role_map(msp):
    """按层名语义解析每层标注角色，免疫「7↔8 语义随楼颠倒」「8.2/9/双 8 层」等变体。
    数字前缀只是兜底（老楼固定 5/6/7/8 布局）；真实语义在层名里：
      房间号→number  面积→area  用途/功能/类型→purpose  使用单位/单位→dept
    返回 {精确层名: role}，只含本楼实际出现的 MTEXT 层。
    c006 等老楼层名（7用途/8使用单位）与这些规则天然一致，不回归。"""
    MARKERS = (("房间号", "number"), ("面积", "area"),
               ("使用单位", "dept"), ("单位", "dept"),
               ("用途", "purpose"), ("功能", "purpose"), ("类型", "purpose"))
    PREFIX = {"5": "area", "6": "number", "7": "purpose", "8": "dept"}
    seen = set()
    for e in msp:
        if e.dxftype() != "MTEXT":
            continue
        l = e.dxf.layer or ""
        if not l or l in seen:
            continue
        seen.add(l)
    out = {}
    for l in seen:
        role = None
        for marker, r in MARKERS:
            if marker in l:
                role = r
                break
        if role is None and l[:1] in PREFIX:
            role = PREFIX[l[:1]]
        if role:
            out[l] = role
    return out


def door_box(d, depth):
    """detect_doors 返回的 {x,y,w,horiz}（本地米）→ 门盒补丁。"""
    half = d["w"] / 2
    if d["horiz"]:
        return box(d["x"] - half, d["y"] - depth / 2, d["x"] + half, d["y"] + depth / 2)
    return box(d["x"] - depth / 2, d["y"] - half, d["x"] + depth / 2, d["y"] + half)


def door_plugs_insert(doors, F, p):
    """classify_line 的 INSERT 门点列（CAD 毫米）→ 本层门盒补丁（本地米）。"""
    plugs = []
    for pts in doors:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        if floor_of(p, cx, cy) != F:
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        xs = [q[0] for q in local]; ys = [q[1] for q in local]
        horiz = (max(xs) - min(xs)) >= (max(ys) - min(ys))
        is_double = len(local) > 2
        w = p.door_w_double if is_double else p.door_w_single
        cxx = sum(xs) / len(xs); cyy = sum(ys) / len(ys)
        d = DOOR_PLUG_DEPTH
        plugs.append(box(cxx - w / 2, cyy - d / 2, cxx + w / 2, cyy + d / 2) if horiz
                     else box(cxx - d / 2, cyy - w / 2, cxx + d / 2, cyy + w / 2))
    return plugs


def floor_walls(F, walls, p):
    """第 F 层墙折线（CAD 毫米，含过渡层 wall_x 过滤）→ 本地米坐标列表。"""
    wall_x = None
    tr = (p.transition or {}).get(F)
    if tr:
        wall_x = tr.get("wall_x")
    out = []
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        if abs(floor_of(p, cx, cy) - F) < 0.5:
            if wall_x is not None and not (wall_x[0] <= cx <= wall_x[1]):
                continue
            out.append([to_local(p, x, y, F) for x, y in pts])
    return out


def floor_rooms(F, walls, insert_doors, p, outline_override=None):
    wall_local = floor_walls(F, walls, p)
    outline, wall_geoms, _ = derive_walls_and_outline(wall_local, p)
    # outline_unify：多翼楼低层墙 union 碎片化 → 每层 max(area) 塌成小片，房间全丢。
    # 用全楼统一基准轮廓替代（与 recognize.py 同源），墙几何仍按本层算。
    if outline_override is not None:
        outline = outline_override
    if outline.is_empty:
        return []
    region = unary_union(wall_geoms) if wall_geoms else Polygon()
    if insert_doors is not None:
        for plug in door_plugs_insert(insert_doors, F, p):
            region = region.union(plug)
    else:
        for d in detect_doors(wall_local, outline, p):
            region = region.union(door_box(d, DOOR_PLUG_DEPTH))
    interior = outline.difference(region)
    polys = [interior] if interior.geom_type == "Polygon" else list(interior.geoms)
    return [g for g in polys if g.area >= MIN_ROOM_AREA]


def label_in(poly, entries, F, p):
    for x, y, t in entries:
        if floor_of(p, x, y) != F:
            continue
        lx, ly = to_local(p, x, y, F)
        if poly.buffer(LABEL_TOL).covers(Point(lx, ly)):
            return t
    return None


def run(name, dry):
    p = load_profile(name)
    doc = ezdxf.readfile(p.dxf, encoding=ENCODING)
    msp = doc.modelspace()

    is_line = getattr(p, "classifier", "lwpolyline") == "line"
    if is_line:
        from recognizer.classify_line import classify_line
        walls, insert_doors, _, _ = classify_line(msp, p)
    else:
        from recognizer.classify import classify
        walls, _, _, _ = classify(msp, p)
        insert_doors = None

    # 层名语义解析（标记词优先，覆盖 7↔8 颠倒/双 8 层/8.2 变体）；旧按数字前缀的口径仍作
    # 兜底（老楼 5/6/7/8 布局）。LAYER_ROLE_OVERRIDE 保留手工纠正位。
    role_map = layer_role_map(msp)
    role_map.update(LAYER_ROLE_OVERRIDE.get(name, {}))
    labels = read_labels(msp, role_map)

    floors = sorted({floor_of(p, sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
                     for pts in walls})

    ref_F, reference_outline = reference_outline_for(p, walls, floors)
    unify_set = unify_floor_set(p, floors)

    rooms = []
    floor_polys = {}   # F -> [房间多边形]（含无房号者，供歧义诊断）
    for F in floors:
        override = outline_for_floor(p, ref_F, reference_outline, F) if F in unify_set else None
        polys = floor_rooms(F, walls, insert_doors, p, outline_override=override)
        floor_polys[F] = polys
        for g in polys:
            number = label_in(g, labels["number"], F, p)
            if not number:
                continue
            cx, cy = g.centroid.x, g.centroid.y
            rooms.append({
                "building": name,
                "floor": F,
                "number": number,
                "name": None,
                "area": label_in(g, labels["area"], F, p),
                "area_m2": round(g.area, 2),
                "purpose": label_in(g, labels["purpose"], F, p),
                "dept": label_in(g, labels["dept"], F, p),
                "centroid": [round(cx, 2), round(cy, 2)],
                "boundary": [[round(x, 2), round(y, 2)] for x, y in g.exterior.coords],
            })

    # 歧义诊断（不写文件，只打印）：标注点被 ≥2 个房间覆盖会误配房号，应恒为 0。
    # 房间吃多标注 = 一个房间覆盖多个不同房号，多为内墙缺失致房间合并（几何问题，非标注问题）。
    buffered = {F: [g.buffer(LABEL_TOL) for g in polys] for F, polys in floor_polys.items()}
    ambig = 0
    for F in floors:
        for (x, y, t) in labels["number"]:
            if floor_of(p, x, y) != F:
                continue
            lx, ly = to_local(p, x, y, F)
            if sum(1 for g in buffered[F] if g.covers(Point(lx, ly))) > 1:
                ambig += 1
    room_eat = 0
    for F, polys in floor_polys.items():
        for gi, g in enumerate(polys):
            hits = set()
            for (x, y, t) in labels["number"]:
                if floor_of(p, x, y) != F:
                    continue
                lx, ly = to_local(p, x, y, F)
                if buffered[F][gi].covers(Point(lx, ly)):
                    hits.add(t)
            if len(hits) > 1:
                room_eat += 1
    if ambig or room_eat:
        print(f"  [歧义] 标注命中多房间={ambig} 房间吃多标注={room_eat}")

    rooms.sort(key=lambda r: (r["floor"], r["number"]))
    base = ID_BASE.get(name, 1000000)
    for i, r in enumerate(rooms):
        r["id"] = base + i + 1

    print(f"[{name}] 共提取 {len(rooms)} 间房（有房号）")
    per = {}
    for r in rooms:
        per[r["floor"]] = per.get(r["floor"], 0) + 1
    for F in sorted(per):
        print(f"  第{F}层 {per[F]} 间")

    if not dry and rooms:
        os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
        with open(p.rooms, "w", encoding="utf-8") as f:
            json.dump(rooms, f, ensure_ascii=False, indent=1)
        print(f"已写 {p.rooms}")
    return rooms


def main():
    argv = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv
    if "--all" in argv:
        names = sorted(ID_BASE)
    else:
        names = [a for a in argv if not a.startswith("--")] or list(ID_BASE)
    for name in names:
        if name not in ID_BASE:
            print(f"未知建筑 {name}（跳过），可用：{sorted(ID_BASE)}")
            continue
        run(name, dry)
        print()


if __name__ == "__main__":
    main()
