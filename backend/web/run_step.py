# -*- coding: utf-8 -*-
"""单栋单步执行器（供网页控制台 subprocess 调用）。

用法:
  python run_step.py <name> <step> [windows]
    step: recognize | glb | full
    windows: 任意非空 = 导出合成窗（仅 glb/full 生效）

档案加载优先级（与前端「参数」面板读写一致）:
  1. data/buildings/<name>/profile.json 存在 → run_building.load_profile（批次楼，48 栋）
  2. data/<name>-profile.json 存在        → 覆盖注册表档案（理化楼改参数后落盘于此）
  3. 否则 → recognizer.profiles.get_profile(name)（注册表只读基线）

打印人类可读日志；最后一行输出 JSON 供控制台解析: {"ok": true|false, ...}。
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 路径引导：从本文件位置推导（backend/web/run_step.py → 上两级 = 仓库根），不写盘符。
sys.path.insert(0, os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))    # backend/
from paths import DATA as _DATA, ROOT as _ROOT, ensure_sys_path  # noqa: E402

ensure_sys_path("modeling", "nav")     # 各阶段脚本（build_standard_glb 等）在这些目录

ROOT = str(_ROOT)
DATA = str(_DATA)
BUILDINGS = os.path.join(DATA, "buildings")


def profile_from_cfg(cfg):
    """把 profile JSON（与 run_building.load_profile 同构）转成 BuildingProfile。

    类型转换与 run_building.load_profile 保持一致（tuple/list/float/int 显式归一），
    用于注册表楼（理化楼）的覆盖档案落盘后重新加载。"""
    from recognizer.profile import BuildingProfile
    return BuildingProfile(
        name=cfg["name"], title=cfg["title"],
        dxf=cfg["dxf"], rooms=cfg["rooms"], out_dir=cfg["out_dir"],
        offset=float(cfg["offset"]), cx=float(cfg["cx"]), cy=float(cfg["cy"]),
        wall_layer=cfg["wall_layer"], column_layer=cfg.get("column_layer", ""),
        door_min_points=cfg.get("door_min_points", 10),
        stair_points=cfg.get("stair_points", 5),
        door_by_points=cfg.get("door_by_points", False),
        wall_min=cfg.get("wall_min", 0.08), wall_max=cfg.get("wall_max", 0.35),
        wall_extend=cfg.get("wall_extend", 0.15), wall_fallback=cfg.get("wall_fallback", 0.15),
        single_wall_t=cfg.get("single_wall_t", 0.10),
        wall_thicknesses=[float(v) for v in cfg["wall_thicknesses"]]
        if cfg.get("wall_thicknesses") else None,
        door_w_single=cfg.get("door_w_single", 1.1), door_w_double=cfg.get("door_w_double", 2.4),
        door_depth=cfg.get("door_depth", 0.5),
        outline_buf=cfg.get("outline_buf", 0.15), open_r=cfg.get("open_r", 0.35),
        outline_close_r=cfg.get("outline_close_r", 0.0),
        parapet_margin=cfg.get("parapet_margin", 0.5),
        layer_height=cfg.get("layer_height", 4.2), slab=cfg.get("slab", 0.2),
        x_range=tuple(cfg["x_range"]) if cfg.get("x_range") else None,
        floor_ys=[float(v) for v in cfg["floor_ys"]] if cfg.get("floor_ys") else None,
        floor_plans=[tuple(float(v) for v in plan) for plan in cfg["floor_plans"]]
        if cfg.get("floor_plans") else None,
        classifier=cfg.get("classifier", "lwpolyline"),
        style=cfg.get("style"),
        transition={int(k): v for k, v in cfg["transition"].items()}
        if cfg.get("transition") else None,
        outline_unify=bool(cfg.get("outline_unify", False)),
        outline_unify_floors=[int(v) for v in cfg["outline_unify_floors"]]
        if cfg.get("outline_unify_floors") else None,
    )


def load_profile(name):
    pjson = os.path.join(BUILDINGS, name, "profile.json")
    if os.path.exists(pjson):
        import run_building
        return run_building.load_profile(name)
    override = os.path.join(DATA, f"{name}-profile.json")
    if os.path.exists(override):
        with open(override, encoding="utf-8") as f:
            return profile_from_cfg(json.load(f))
    import recognizer.profiles  # noqa: F401  导入即注册 lihua / j6
    from recognizer.profile import get_profile
    return get_profile(name)


def step_recognize(p):
    from recognizer import recognize
    os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
    if not os.path.exists(p.rooms):
        with open(p.rooms, "w", encoding="utf-8") as f:
            json.dump([], f)
    floors = recognize(p)
    spec = os.path.join(os.path.dirname(p.out_dir), "spec.json")
    print(f"[recognize] {p.name} 楼层数={len(floors)}  spec 已写入 {spec}")


def step_glb(p, include_windows, skip_floors=()):
    import build_standard_glb as bsg
    bsg.INCLUDE_SYNTHETIC_WINDOWS = include_windows
    bsg.SKIP_FLOORS = {int(v) for v in skip_floors}
    out_parent = os.path.dirname(p.out_dir)
    try:
        is_batch = os.path.commonpath([BUILDINGS, out_parent]) == BUILDINGS
    except ValueError:  # 不同盘符兜底
        is_batch = False
    if is_batch:
        # 批次楼：out_dir = data/buildings/<name>/floors → GLB 落在 data/buildings/<name>/
        bsg.DATA = out_parent
        bsg.OUT = os.path.join(bsg.DATA, f"{p.name}-building.glb")
    else:
        # 注册表楼（理化楼）：out_dir = data/floors → GLB 落在 data/ 根
        bsg.DATA = DATA
        bsg.OUT = os.path.join(DATA, f"{p.name}-building.glb")
    bsg.main()


def glb_opts_from_profile(name):
    """未在命令行指定时，回落到该楼 profile.json 的 GLB 导出档位键。

    为什么要有这一步：控制台「导出合成窗」开关写的就是 `glb_windows`，而控制台调
    `run_step.py <name> glb` 是**不带第三个参数**的 —— 没有这个回落，开关写了档
    却不生效，重出 GLB 会静默把窗全剥掉。
    `skip_floors`（要从模型里剔除的层号，0 基）同理，由控制台档案驱动。
    load_profile 逐键读取，识别层不认这两个键，所以它们只影响这里。
    """
    opts = {"windows": False, "skip_floors": ()}
    pjson = os.path.join(BUILDINGS, name, "profile.json")
    if not os.path.exists(pjson):
        return opts
    try:
        with open(pjson, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return opts
    opts["windows"] = bool(d.get("glb_windows"))
    opts["skip_floors"] = tuple(int(v) for v in (d.get("skip_floors") or []))
    return opts


def main():
    if len(sys.argv) < 3:
        print("用法: python run_step.py <name> <recognize|glb|full> [windows|nowindows]"
              "  （不写则读 profile.json 的 glb_windows / skip_floors）", file=sys.stderr)
        return 2
    name, step = sys.argv[1], sys.argv[2]
    opts = glb_opts_from_profile(name)
    if len(sys.argv) > 3:
        a = sys.argv[3].lower()
        if a in ("1", "true", "windows"):
            include_windows = True
        elif a in ("0", "false", "nowindows"):
            include_windows = False
        else:
            print(f"第三个参数只认 windows/nowindows，收到 {sys.argv[3]!r}", file=sys.stderr)
            return 2
    else:
        include_windows = opts["windows"]
    try:
        p = load_profile(name)
        if step in ("recognize", "full"):
            step_recognize(p)
        if step in ("glb", "full"):
            step_glb(p, include_windows, opts["skip_floors"])
        print(json.dumps({"ok": True, "name": name, "step": step}, ensure_ascii=False))
        return 0
    except SystemExit as e:
        print(json.dumps({"ok": False, "name": name, "step": step,
                          "error": f"SystemExit: {e}"}, ensure_ascii=False))
        return 1
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(json.dumps({"ok": False, "name": name, "step": step,
                          "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
