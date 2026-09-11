# -*- coding: utf-8 -*-
"""c006 第六教学楼（逸夫楼）房间提取：LINE 墙 + INSERT 门 + UTF-8 标注。

与 extract_rooms.py（理化楼 LWPOLYLINE 基线）并列。c006 关键差异：
  - 墙 = 2 点 LINE（双线墙皮），门 = INSERT 块 $DorLib2D$，柱 = INSERT 块 _FZHK/_YZHK。
  - 中文标注（用途/单位）是 UTF-8 编码（ODA 转换器写出），房间号/面积是 ASCII。
    默认 ezdxf 读成乱码，必须 encoding='utf-8'。
  - 阶梯「两列」布局（裙楼 + 塔楼分列 X），过渡层第 7 层楼板全宽、房间只在塔楼。

房间边界从识别引擎同一套几何推导（轮廓 - 墙区域，门洞用门盒补闭），保证与
floor JSON 完全一致；标注层按资产管理图国标层名数字前缀定位（5面积/6房间号/
7用途/8单位），与理化楼层名编码无关、天然免疫层名乱码。

用法:
  python backend/extract/extract_rooms_c006.py            # 写 data/buildings/c006/rooms.json
  python backend/extract/extract_rooms_c006.py --dry      # 只打印统计不写文件
"""
import json
import os
import re
import sys

sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, r"D:\gym3d")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import ezdxf
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union

from run_building import load_profile
from recognizer.classify_line import classify_line
from recognizer.geometry import derive_walls_and_outline
from recognizer.profile import to_local, floor_of

NAME = "c006"
ENCODING = "utf-8"       # c006 中文标注是 UTF-8（用途/单位）；房间号/面积 ASCII 不受影响
ID_BASE = 100000         # 房间 id 全局唯一偏移：理化楼基线用 1..118，c006 从 100000 起

MIN_ROOM_AREA = 1.0      # 封闭区域面积阈值(㎡)，小于当缝隙/井道噪声
DOOR_PLUG_DEPTH = 0.4    # 门盒深度(米)，补闭墙带上门洞缺口（墙带厚 0.3m，0.4 留裕量）

# 资产管理图国标层名：数字前缀 → 语义（层名中文因编码可能乱码，只认首字符数字）
LAYER_ROLE = {"5": "area", "6": "number", "7": "purpose", "8": "dept"}


def clean(s):
    """剥离 MTEXT 字体/换行控制码，压平空白。"""
    s = re.sub(r"\\[A-Za-z][^;]*;", "", s)   # \fSimSun|...; 等控制码
    s = s.replace("{", "").replace("}", "").replace("\\", "")
    return " ".join(s.split())


def read_labels(msp):
    """按数字前缀读标注层，返回 {role: [(x_cad, y_cad, text), ...]}。"""
    labels = {"area": [], "number": [], "purpose": [], "dept": []}
    for e in msp:
        if e.dxftype() != "MTEXT":
            continue
        l = e.dxf.layer or ""
        if not l or l[0] not in LAYER_ROLE:
            continue
        labels[LAYER_ROLE[l[0]]].append((e.dxf.insert.x, e.dxf.insert.y, clean(e.text)))
    return labels


def door_plugs(doors, F, p):
    """把 classify_line 的门点列（CAD 毫米）转成本层门盒补丁（本地米）。

    门点列由 _door_points 编码：质心=插入点，2 点=单扇、17 点=双扇，
    点列沿开启方向铺开（X=水平门）。门盒补丁沿开启方向宽 door_w、垂直墙方向厚 DOOR_PLUG_DEPTH。
    """
    plugs = []
    for pts in doors:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        if floor_of(p, cx, cy) != F:
            continue
        local = [to_local(p, x, y, F) for x, y in pts]
        xs = [q[0] for q in local]
        ys = [q[1] for q in local]
        horiz = (max(xs) - min(xs)) >= (max(ys) - min(ys))
        is_double = len(local) > 2
        w = p.door_w_double if is_double else p.door_w_single
        cxx = sum(xs) / len(xs)
        cyy = sum(ys) / len(ys)
        d = DOOR_PLUG_DEPTH
        plugs.append(box(cxx - w / 2, cyy - d / 2, cxx + w / 2, cyy + d / 2) if horiz
                     else box(cxx - d / 2, cyy - w / 2, cxx + d / 2, cyy + w / 2))
    return plugs


def floor_rooms(F, walls, doors, p):
    """第 F 层封闭房间多边形列表（本地米坐标）。

    与 recognize.py 同口径的过渡层 wall_x 过滤：第 7 层只取塔楼墙、弃裙楼屋面女儿墙。
    """
    wall_x = None
    tr = (p.transition or {}).get(F)
    if tr:
        wall_x = tr.get("wall_x")

    wall_pts = []
    for pts in walls:
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        if abs(floor_of(p, cx, cy) - F) < 0.5:
            if wall_x is not None and not (wall_x[0] <= cx <= wall_x[1]):
                continue
            wall_pts.append([to_local(p, x, y, F) for x, y in pts])

    outline, wall_geoms, _ = derive_walls_and_outline(wall_pts, p)
    if outline.is_empty:
        return []

    region = unary_union(wall_geoms) if wall_geoms else Polygon()
    for plug in door_plugs(doors, F, p):
        region = region.union(plug)

    interior = outline.difference(region)
    polys = [interior] if interior.geom_type == "Polygon" else list(interior.geoms)
    return [g for g in polys if g.area >= MIN_ROOM_AREA]


def label_in(poly, entries, F, p):
    """返回插入点落在 poly 内(含边界)的第一条标注文本。"""
    for x, y, t in entries:
        if floor_of(p, x, y) != F:
            continue
        lx, ly = to_local(p, x, y, F)
        if poly.covers(Point(lx, ly)):
            return t
    return None


def main():
    dry = "--dry" in sys.argv
    p = load_profile(NAME)

    doc = ezdxf.readfile(p.dxf, encoding=ENCODING)
    msp = doc.modelspace()
    walls, doors, _, _ = classify_line(msp, p)
    labels = read_labels(msp)

    floors = sorted({floor_of(p, sum(q[0] for q in pts) / len(pts),
                              sum(q[1] for q in pts) / len(pts))
                     for pts in walls})

    rooms = []
    for F in floors:
        polys = floor_rooms(F, walls, doors, p)
        for g in polys:
            number = label_in(g, labels["number"], F, p)
            # 只保留「有房间号」的封闭区域（其余是走廊/井道/屋面），与理化楼同口径
            if not number:
                continue
            cx, cy = g.centroid.x, g.centroid.y
            rooms.append({
                "building": NAME,
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

    # 稳定 id（全局唯一偏移 + 按楼层/房号排序）
    rooms.sort(key=lambda r: (r["floor"], r["number"]))
    for i, r in enumerate(rooms):
        r["id"] = ID_BASE + i + 1

    print(f"[c006] 共提取 {len(rooms)} 间房（有房号）")
    per_floor = {}
    for r in rooms:
        per_floor[r["floor"]] = per_floor.get(r["floor"], 0) + 1
    for F in sorted(per_floor):
        print(f"  第{F}层 {per_floor[F]} 间")
    print("\n样例（每层前 2 间）：")
    shown = set()
    for r in rooms:
        if r["floor"] in shown:
            continue
        shown.add(r["floor"])
        print(f"  [{r['id']}] F{r['floor']} {r['number']} 面积={r['area'] or '—'} "
              f"计算={r['area_m2']}㎡ 用途={r['purpose'] or '—'} 单位={r['dept'] or '—'}")

    if not dry:
        os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
        with open(p.rooms, "w", encoding="utf-8") as f:
            json.dump(rooms, f, ensure_ascii=False, indent=1)
        print(f"\n已写 {p.rooms}")


if __name__ == "__main__":
    main()
