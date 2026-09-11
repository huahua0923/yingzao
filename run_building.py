# -*- coding: utf-8 -*-
"""单栋独立管道：读 data/buildings/<name>/profile.json → 构 BuildingProfile → recognize → 校验。

与 recognizer.profiles 注册表解耦，各楼互不干扰（并行代理各跑各的）。
校验通过标准：
  - floors/floor{N}.json 全部能 json.load
  - 每层 walls 非空、outline 面积>0、无 NaN/Inf
  - 楼层数 >= 2
用法:
  python run_building.py <name>          # 跑识别 + 校验
  python run_building.py <name> --glb    # 追加生成 GLB
"""
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 路径从本文件位置推导，代码里不出现盘符（开发机在 D 盘、服务器在 /opt）。
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "backend"))       # paths.py / recognizer
from paths import BUILDINGS  # noqa: E402

from shapely.geometry import Polygon


def load_profile(name):
    path = os.path.join(str(BUILDINGS), name, "profile.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    from recognizer.profile import BuildingProfile
    return BuildingProfile(
        name=cfg["name"], title=cfg["title"],
        dxf=cfg["dxf"], rooms=cfg["rooms"], out_dir=cfg["out_dir"],
        offset=float(cfg["offset"]), cx=float(cfg["cx"]), cy=float(cfg["cy"]),
        wall_layer=cfg["wall_layer"], column_layer=cfg.get("column_layer", ""),
        door_min_points=cfg.get("door_min_points", 10),
        stair_points=cfg.get("stair_points", 5),
        wall_min=cfg.get("wall_min", 0.08), wall_max=cfg.get("wall_max", 0.35),
        wall_extend=cfg.get("wall_extend", 0.15), wall_fallback=cfg.get("wall_fallback", 0.15),
        single_wall_t=cfg.get("single_wall_t", 0.10),
        wall_thicknesses=[float(v) for v in cfg["wall_thicknesses"]] if cfg.get("wall_thicknesses") else None,
        door_w_single=cfg.get("door_w_single", 1.1), door_w_double=cfg.get("door_w_double", 2.4),
        door_depth=cfg.get("door_depth", 0.5),
        outline_buf=cfg.get("outline_buf", 0.15), open_r=cfg.get("open_r", 0.35),
        outline_close_r=cfg.get("outline_close_r", 0.0),
        parapet_margin=cfg.get("parapet_margin", 0.5),
        layer_height=cfg.get("layer_height", 4.2), slab=cfg.get("slab", 0.2),
        x_range=tuple(cfg["x_range"]) if cfg.get("x_range") else None,
        floor_ys=[float(v) for v in cfg["floor_ys"]] if cfg.get("floor_ys") else None,
        floor_plans=[tuple(float(v) for v in plan) for plan in cfg["floor_plans"]] if cfg.get("floor_plans") else None,
        classifier=cfg.get("classifier", "lwpolyline"),
        style=cfg.get("style"),
        transition={int(k): v for k, v in cfg["transition"].items()} if cfg.get("transition") else None,
        outline_unify=bool(cfg.get("outline_unify", False)),
        outline_unify_floors=[int(v) for v in cfg["outline_unify_floors"]] if cfg.get("outline_unify_floors") else None,
        pair_curved=bool(cfg.get("pair_curved", False)),
    )


def _has_nan(o):
    if isinstance(o, float):
        return math.isnan(o) or math.isinf(o)
    if isinstance(o, list):
        return any(_has_nan(x) for x in o)
    if isinstance(o, dict):
        return any(_has_nan(v) for v in o.values())
    return False


def validate(name, floors):
    problems = []
    if len(floors) < 2:
        problems.append(f"楼层数 {len(floors)} < 2，offset 可能错了")
    for F in floors:
        fp = os.path.join(str(BUILDINGS), name, "floors", f"floor{F}.json")
        if not os.path.exists(fp):
            problems.append(f"floor{F}.json 缺失")
            continue
        with open(fp, encoding="utf-8") as f:
            g = json.load(f)
        if _has_nan(g):
            problems.append(f"floor{F} 含 NaN/Inf")
        if not g.get("walls"):
            problems.append(f"floor{F} walls 空")
        try:
            area = Polygon(g["outline"]).area
            if area <= 0:
                problems.append(f"floor{F} outline 面积={area}")
        except Exception as e:
            problems.append(f"floor{F} outline 非法: {e}")
    return problems


def main():
    name = sys.argv[1]
    do_glb = "--glb" in sys.argv
    from recognizer import recognize
    p = load_profile(name)

    # 房间文件缺失时补空数组（避免 floor.py open() 崩）
    os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
    if not os.path.exists(p.rooms):
        with open(p.rooms, "w", encoding="utf-8") as f:
            json.dump([], f)

    floors = recognize(p)
    problems = validate(name, floors)
    print("\n" + "=" * 60)
    print(f"[{name}] 楼层数={len(floors)}  校验问题={len(problems)}")
    for pr in problems:
        print("  ✗ " + pr)
    if not problems:
        print("  ✓ PASS")
    print("=" * 60)

    if do_glb and not problems:
        sys.path.insert(0, os.path.join(_ROOT, "backend", "modeling"))
        import build_standard_glb as bsg
        # 让 GLB 生成器消费本楼 floors/spec
        bsg.DATA = os.path.dirname(p.out_dir)
        bsg.OUT = os.path.join(bsg.DATA, f"{name}-building.glb")
        if "--windows" in sys.argv:
            bsg.INCLUDE_SYNTHETIC_WINDOWS = True   # 合成窗默认不进 GLB，加 --windows 才导出
        bsg.main()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
