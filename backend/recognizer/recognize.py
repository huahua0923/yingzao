# -*- coding: utf-8 -*-
"""识别入口：读 DXF → 分类构件 → 逐层组装 → 写 floors/floor{N}.json。"""
import json
import os
import ezdxf

from shapely.geometry import Polygon

from .classify import classify
from .floor import extract_floor, reference_outline_for, wall_pts_for_floor, unify_floor_set, outline_for_floor
from .geometry import derive_walls_and_outline
from .profile import floor_of, to_local
from .standard import STANDARD, emit_spec


def localize_columns(columns_raw, p, S):
    """结构柱按图来：图里画了哪层就哪层，返回 {floor: [柱]}。
    柱中心取自 CAD 包围盒中心，宽深取自包围盒实际尺寸（classify_line 已按 INSERT
    xscale/yscale 编码真实边长，如 600mm），不再用标准值 0.5m、也不假设贯通全高复制到每层。"""
    by_floor = {}
    for x0, y0, x1, y1 in columns_raw:
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        f = floor_of(p, cx, cy)
        x, y = to_local(p, cx, cy, f)
        # 过渡层（slab_from 复用裙楼楼板）的柱画在「源楼层 Y」（裙楼平面），与塔楼墙不在同一
        # DXF Y 列（c006 第7层柱在裙楼 cy=89295、墙在塔楼 cy=84494，差 4.8m）→ 柱按源楼层 cy
        # 居中，与楼板同源，否则柱比塔楼墙/楼板整体偏 4.8m。
        tr = (p.transition or {}).get(f)
        if tr and tr.get("slab_from") is not None and p.floor_plans:
            src_cy = p.floor_plans[tr["slab_from"]][1]
            y = (cy - src_cy) / 1000.0
        # 屋顶设备副块（电梯机房/水箱柱）画在塔楼 X 列、Y 却落在裙楼楼层区间（c006 第11层），
        # localY 达 125~181m，远超任何真实柱位（最大楼 c103 也只有 84m）→ 丢弃，否则 GLB
        # 长出一根 181m 的悬空柱带。阈值 100m 在「真实最大 84m」与「副块 125m」之间，安全。
        if abs(x) > 100.0 or abs(y) > 100.0:
            continue
        by_floor.setdefault(f, []).append({
            "x": round(x, 3),
            "y": round(y, 3),
            "w": round((x1 - x0) / 1000.0, 3),
            "d": round((y1 - y0) / 1000.0, 3),
        })
    return by_floor


def recognize(p):
    """对 p（BuildingProfile）执行完整识别，返回楼层号列表。"""
    doc = ezdxf.readfile(p.dxf)
    msp = doc.modelspace()

    if getattr(p, "classifier", "lwpolyline") == "line":
        from .classify_line import classify_line
        walls, doors, stairs, columns_raw = classify_line(msp, p)
    else:
        walls, doors, stairs, columns_raw = classify(msp, p)

    os.makedirs(p.out_dir, exist_ok=True)
    # 清掉旧楼层文件：层数修正后（c103 11→6、c104 10→5）会残留 floor6~10.json，
    # 污染 compare_floors 逐层比对与 building.html 渲染（读到僵尸层）
    for stale in os.listdir(p.out_dir):
        if stale.startswith("floor") and stale.endswith(".json"):
            os.remove(os.path.join(p.out_dir, stale))
    # 用「质心」判定楼层（旋转墙/阶梯楼比首点更稳；两列布局需 X 判列）
    def _floor_of_pts(pts):
        return floor_of(p, sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))

    floors = sorted({_floor_of_pts(pts) for pts in walls}
                    | {_floor_of_pts(pts) for pts in doors})

    columns_local = localize_columns(columns_raw, p, STANDARD)
    top = max(floors)

    # 多翼/阶梯楼统一 footprint（profile.outline_unify，默认 False 不启用）：低层墙 union
    # 碎片化时 derive_walls_and_outline 的 max(area) 只留最大一翼 → 轮廓塌成小片、质心横漂
    # （c009 F0 21 片/F1 39 片 → 低层错位 54m）。全楼层里挑「轮廓面积最大」的一层当基准
    # （墙最完整，c009 为顶层 F5），全楼复用该轮廓，消除低层塌陷。逻辑抽到 reference_outline_for，
    # 与 extract_rooms_generic.py 共用，防止渲染/房间两路漂移。
    ref_F, reference_outline = reference_outline_for(p, walls, floors)
    unify_set = unify_floor_set(p, floors)

    geoms = {}
    outline_cache = {}
    for F in floors:
        slab_outline = None
        wall_x = None
        wall_x_clip = None
        tr = (p.transition or {}).get(F)
        if tr:
            src = tr.get("slab_from")
            if src is not None and src in outline_cache:
                # 复用源楼层楼板轮廓（全宽）。塔楼居中于裙楼 → 楼板应落在过渡层本地原点。
                # 仅当源/过渡层同 X 列（聚类噪声导致的 cy 微差）才按 cy 差平移；不同 X 列
                # （塔楼/裙楼分列画，如 c006 六教）cy 差是列间绘图偏移，不平移（否则楼板漂）。
                src_cx = p.floor_plans[src][0] if p.floor_plans else p.cx
                tr_cx = p.floor_plans[F][0] if p.floor_plans else p.cx
                if src_cx == tr_cx:
                    src_cy = p.floor_plans[src][1] if p.floor_plans else p.cy
                    tr_cy = p.floor_plans[F][1] if p.floor_plans else p.cy
                    dy = (src_cy - tr_cy) / 1000.0
                else:
                    dy = 0.0
                slab_outline = Polygon([(x, y + dy) for x, y in outline_cache[src]])
            wall_x = tr.get("wall_x")
            wall_x_clip = tr.get("wall_x_clip")
        # 统一 footprint：只在 unify_floor_set 的楼层子集里应用基准轮廓（阶梯楼裙楼统一、
        # 塔楼各自独立）；按 cy 差平移到本层本地坐标（见 outline_for_floor）。
        override = outline_for_floor(p, ref_F, reference_outline, F) if F in unify_set else None
        geom = extract_floor(F, walls, doors, stairs, columns_local, p, STANDARD, F == top,
                             slab_outline=slab_outline, wall_x=wall_x, wall_x_clip=wall_x_clip,
                             outline_override=override)
        if geom is None:
            print(f"[{p.name} floor {F}] 空轮廓（无墙），跳过")
            continue
        geoms[F] = geom
        outline_cache[F] = geom["outline"]
        print(f"[{p.name} floor {F}] 墙={len(geom['walls'])} 窗={len(geom['windows'])} "
              f"房间={len(geom['rooms'])} 门={len(geom['doors'])} 柱={len(geom['columns'])} "
              f"电梯={len(geom.get('elevators', []))} 台阶={len(geom['stairs'])} "
              f"楼梯井={len(geom['stairwells'])}"
              + (" 屋顶=有" if "roof" in geom else ""))

    if not geoms:
        raise SystemExit(f"[{p.name}] 所有楼层空轮廓，识别失败")

    # 顶层可能因空轮廓被跳过 → 取实际识别到的最高层
    top = max(geoms)

    # 阶梯结构：顶层是中央主体，翼楼屋面在下一层顶部（= 顶层楼板底部）。
    # 翼楼屋面楼板 = 下一层满 footprint outline − 顶层中央主体 outline，写入顶层 roof.wingRoof。
    if top > 0 and (top - 1) in geoms and "roof" in geoms[top]:
        try:
            wing = (Polygon(geoms[top - 1]["outline"]).buffer(0)
                    .difference(Polygon(geoms[top]["outline"]).buffer(0)))
            if not wing.is_empty:
                polys = [wing] if wing.geom_type == "Polygon" else list(wing.geoms)
                wing_roof = [
                    [[round(x, 3), round(y, 3)] for x, y in g.exterior.coords]
                    for g in polys if g.area >= 2.0   # 过滤两轮廓边界微错位产生的碎屑
                ]
                if wing_roof:
                    geoms[top]["roof"]["wingRoof"] = wing_roof
        except Exception as e:
            print(f"[{p.name}] 翼楼屋面计算失败（跳过）: {e}")

    for F, geom in geoms.items():
        out = os.path.join(p.out_dir, f"floor{F}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(geom, f, ensure_ascii=False, indent=1)

    # 前端 fetch 的规格（数据驱动查看器与 GLB 同源防漂移）。
    # 外墙厚是每栋楼 profile 的固有参数（理化楼门垛实测 0.24，非标准默认 0.30），
    # 覆盖进 spec 使门头过梁/门洞深与真实墙厚一致，避免「过梁比墙宽」。
    overrides = {}
    if getattr(p, "outer_wall_t", None) is not None:
        overrides["outer_wall_t"] = p.outer_wall_t
    emit_spec(os.path.join(os.path.dirname(p.out_dir), "spec.json"), getattr(p, "style", None), overrides)
    return floors
