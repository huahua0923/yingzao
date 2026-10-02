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
from recognizer import outline as OUT  # noqa: E402

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
        # ★ 补上唯一一个「有消费者、但**当时核过的每一条**投递通道都不读」的键
        #   （2026-09-26 实测。⚠ 那时的通道表是 3 条，现在是 5 条 ——
        #    **条数是一次带时刻的测量**，要引用请读 `console_meta._delivery_channels()`
        #    此刻的返回，别抄这句话里的数字）。
        #   `recognize.py` 的 `p.outer_wall_t` 确实被读并覆写进 spec.json（门头过梁/门洞深），
        #   但**没有任何加载器把这个值送进去** ⇒ 它永远是 dataclass 默认 0.24。
        #   （「没有加载器送进来」是**这一行之前**的状态；这一行就是那个缺失的加载器 ——
        #    它加完之后，键从「一条通道都不读」变成「批量识别读、控制台写不进去」。）
        #   后果（实测，96 栋逐个数）：**全库 spec.json 的 outer_wall_t 都是 0.24**，
        #   而 recognize.py 自己的注释写着「理化楼门垛实测 0.24，**非标准默认 0.30**」
        #   ⇒ 今天等于「理化楼的口径被套在了所有楼上」，而这个旋钮在页面上改不动。
        #   回退值取 **0.24**（= dataclass 默认）⇒ 这一行**今天零行为变化**，
        #   只是让页面上那个旋钮第一次真的能改。
        #   ⚠ 95 栋该不该是 0.30 是**几何决定**，不在这条通道的范围里 —— 没动。
        outer_wall_t=cfg.get("outer_wall_t", 0.24),
        wall_thicknesses=[float(v) for v in cfg["wall_thicknesses"]] if cfg.get("wall_thicknesses") else None,
        door_w_single=cfg.get("door_w_single", 1.1), door_w_double=cfg.get("door_w_double", 2.4),
        door_depth=cfg.get("door_depth", 0.5),
        outline_buf=cfg.get("outline_buf", 0.15), open_r=cfg.get("open_r", 0.35),
        outline_close_r=cfg.get("outline_close_r", 0.0),
        label_nearest_max=cfg.get("label_nearest_max", 0.0),
        parapet_margin=cfg.get("parapet_margin", 0.5),
        layer_height=cfg.get("layer_height", 4.2), slab=cfg.get("slab", 0.2),
        x_range=tuple(cfg["x_range"]) if cfg.get("x_range") else None,
        # JSON 的键只能是字符串，楼层号在这里转回 int（sheet_shift/floor_of 都用 int 比对）
        sheet_floors={int(k): [int(v) for v in vs] for k, vs in cfg["sheet_floors"].items()}
        if cfg.get("sheet_floors") else None,
        floor_ys=[float(v) for v in cfg["floor_ys"]] if cfg.get("floor_ys") else None,
        floor_plans=[tuple(float(v) for v in plan) for plan in cfg["floor_plans"]] if cfg.get("floor_plans") else None,
        # 帧对齐附加平移（{"层号": [dx, dy]}，毫米）—— 见 BuildingProfile.frame_shift 的注释：
        # 这个键 2026-09-16 写进过档案但**当时没有任何加载器读它**（等于没写），2026-09-29 补上。
        # 加性：其余楼没有这个键 ⇒ None ⇒ 与「dataclass 里根本没这个字段」逐位同行为。
        frame_shift={str(k): [float(q) for q in v] for k, v in cfg["frame_shift"].items()}
        if cfg.get("frame_shift") else None,
        classifier=cfg.get("classifier", "lwpolyline"),
        style=cfg.get("style"),
        transition={int(k): v for k, v in cfg["transition"].items()} if cfg.get("transition") else None,
        outline_unify=bool(cfg.get("outline_unify", False)),
        outline_unify_floors=[int(v) for v in cfg["outline_unify_floors"]] if cfg.get("outline_unify_floors") else None,
        outdoor_steps={int(k): [tuple(float(q) for q in r) for r in rs]
                       for k, rs in cfg["outdoor_steps"].items()
                       if str(k).lstrip("-").isdigit()}
        if cfg.get("outdoor_steps") else None,
        roof_rooms={int(k): [str(v) for v in vs] for k, vs in cfg["roof_rooms"].items()
                    if str(k).lstrip("-").isdigit()}
        if cfg.get("roof_rooms") else None,
        keep_courtyard_holes=bool(cfg.get("keep_courtyard_holes", False)),
        pair_curved=bool(cfg.get("pair_curved", False)),
        rooms_from_floors=bool(cfg.get("rooms_from_floors", False)),
        room_seal=float(cfg.get("room_seal", 0.0)),
        room_grow_to_wall=float(cfg.get("room_grow_to_wall", 0.0)),
        room_route=str(cfg.get("room_route", "") or ""),
        tread_cluster_filter=bool(cfg.get("tread_cluster_filter", False)),
        atrium_rooms=cfg.get("atrium_rooms"),
        atrium_from=cfg.get("atrium_from"),
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
            area = OUT.floor_outline(g).area
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
    # ★ 生成时间由**生成方**盖章，落在 data/buildings/<name>/generated.json
    #   （为什么不写进产物本身、为什么不用 mtime：见 backend/gen_stamp.py 的头注）
    from gen_stamp import stamp as _stamp
    _stamp(name, "floors", base=os.path.dirname(p.out_dir), n=len(floors), by="run_building")
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
        # ★ 导出档位**从 profile.json 读**（2026-09-26 改口；此前这条路一个键都不读）。
        #   为什么必须读：控制台「导出合成窗」/「导出时剔除的层」两个开关写的都是 profile.json，
        #   而批量出图原先只设 DATA/OUT ⇒ 同一份档案，控制台重出会按它办、批量重出不认，
        #   c103 的 `skip_floors=[5]` 在批量路上是死的（实测全库只有 c103 设了本键）。
        #   ★ 口径照 `run_step.glb_opts_from_profile`（符号锚点，不写行号），但**有一处更宽**：
        #     那边 `bool(d.get("glb_windows"))` ⇒ **缺键 = False = 剥窗**，而本模块默认是 True、
        #     SU 那条路（`su_spec_floors_fleet`）缺键也是 True ⇒ 同一个键今天有**三个默认值**。
        #     这里取"缺键 = 不动模块默认"，免得给从没写过这个键的楼顺手把窗剥掉。
        _prof = {}
        _pj = os.path.join(bsg.DATA, "profile.json")
        if os.path.isfile(_pj):
            try:
                with open(_pj, encoding="utf-8") as _f:
                    _prof = json.load(_f)
            except Exception as _e:                                  # noqa: BLE001
                print("  ! profile.json 读不动（%s），本次按模块默认出图" % _e)
        if "glb_windows" in _prof:
            bsg.INCLUDE_SYNTHETIC_WINDOWS = bool(_prof["glb_windows"])
        _skip = tuple(int(v) for v in (_prof.get("skip_floors") or []))
        if _skip:
            bsg.SKIP_FLOORS = set(_skip)
            print("  按 profile.json 剔除楼层：%s" % sorted(bsg.SKIP_FLOORS))
        if "--windows" in sys.argv:                 # 显式意图：命令行压过档案
            bsg.INCLUDE_SYNTHETIC_WINDOWS = True
        bsg.main()
        from gen_stamp import stamp_file as _stamp_file
        _stamp_file(name, "glb", bsg.OUT, base=os.path.dirname(p.out_dir), by="run_building",
                    windows=bool(getattr(bsg, "INCLUDE_SYNTHETIC_WINDOWS", True)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
