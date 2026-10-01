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
        sheet_floors={int(k): [int(v) for v in vs] for k, vs in cfg["sheet_floors"].items()}
        if cfg.get("sheet_floors") else None,
        floor_ys=[float(v) for v in cfg["floor_ys"]] if cfg.get("floor_ys") else None,
        floor_y_bands=[tuple(float(q) for q in b) for b in cfg["floor_y_bands"]]
        if cfg.get("floor_y_bands") else None,
        floor_plans=[tuple(float(v) for v in plan) for plan in cfg["floor_plans"]]
        if cfg.get("floor_plans") else None,
        # 帧对齐附加平移 —— 与 run_building.load_profile 同一行（两条通道必须都带，
        # 否则同一份档案在批量路与控制台路上给出不同几何；见该键在 BuildingProfile 里的注释）。
        frame_shift={str(k): [float(q) for q in v] for k, v in cfg["frame_shift"].items()}
        if cfg.get("frame_shift") else None,
        classifier=cfg.get("classifier", "lwpolyline"),
        style=cfg.get("style"),
        transition={int(k): v for k, v in cfg["transition"].items()}
        if cfg.get("transition") else None,
        outline_unify=bool(cfg.get("outline_unify", False)),
        outline_unify_floors=[int(v) for v in cfg["outline_unify_floors"]]
        if cfg.get("outline_unify_floors") else None,
        outdoor_steps={int(k): [tuple(float(q) for q in r) for r in rs]
                       for k, rs in cfg["outdoor_steps"].items()
                       if str(k).lstrip("-").isdigit()}
        if cfg.get("outdoor_steps") else None,
        roof_rooms={int(k): [str(v) for v in vs] for k, vs in cfg["roof_rooms"].items()
                    if str(k).lstrip("-").isdigit()}
        if cfg.get("roof_rooms") else None,
        keep_courtyard_holes=bool(cfg.get("keep_courtyard_holes", False)),
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


def _recognize_fingerprint(name):
    """重识别的**增量指纹**：DXF + profile + 识别链源码（backend/recognizer/*.py）。

    为什么值得做：`full --all` 里识别是绝对大头（49 栋 882s，其中 GLB 只要 74s）——
    而**没改识别链、没改 DXF、没改 profile** 的楼根本不需要重识别（产物会逐字节相同）。
    实测（2026-09-16）：一批 `full` 882.4s，其中真正需要重识别的只有 12 栋。

    取"源码 mtime+size"而不是 git hash：本仓库工作区常带未提交改动（git hash 会假绿）。
    """
    import hashlib
    h = hashlib.sha1()
    pj = os.path.join(BUILDINGS, name, "profile.json")
    for f in (pj, os.path.join(BUILDINGS, name, "rooms.json")):
        try:
            st = os.stat(f)
            h.update(("%s|%d|%d;" % (os.path.basename(f), st.st_size, int(st.st_mtime))).encode())
        except OSError:
            h.update(b"missing;")
    try:
        import run_building
        cfg = json.load(open(pj, encoding="utf-8"))
        dxf = cfg.get("dxf")
        if dxf and os.path.exists(dxf):
            st = os.stat(dxf)
            h.update(("%s|%d|%d;" % (os.path.basename(dxf), st.st_size, int(st.st_mtime))).encode())
    except Exception:  # noqa: BLE001
        pass
    rdir = os.path.join(ROOT, "backend", "recognizer")
    for f in sorted(os.listdir(rdir)):
        if f.endswith(".py"):
            st = os.stat(os.path.join(rdir, f))
            h.update(("%s|%d|%d;" % (f, st.st_size, int(st.st_mtime))).encode())
    return h.hexdigest()


def _cache_path(name):
    return os.path.join(BUILDINGS, name, ".recognize_cache.json")


def step_recognize(p, force=False):
    from recognizer import recognize
    os.makedirs(os.path.dirname(p.rooms), exist_ok=True)
    if not os.path.exists(p.rooms):
        with open(p.rooms, "w", encoding="utf-8") as f:
            json.dump([], f)
    fp = _recognize_fingerprint(p.name)
    cf = _cache_path(p.name)
    if not force and os.path.exists(cf) and os.path.exists(os.path.join(p.out_dir, "floor0.json")):
        try:
            old = json.load(open(cf, encoding="utf-8")).get("fingerprint")
        except Exception:  # noqa: BLE001
            old = None
        if old == fp:
            print(f"[recognize] {p.name} **跳过**（增量：DXF/profile/识别链都没变）")
            return
    floors = recognize(p)
    spec = os.path.join(os.path.dirname(p.out_dir), "spec.json")
    print(f"[recognize] {p.name} 楼层数={len(floors)}  spec 已写入 {spec}")
    try:
        json.dump({"fingerprint": fp}, open(cf, "w", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    # ★ 只有**真跑了识别**才盖章。上面的增量跳过分支 `return` 在盖章之前，
    #   所以「跳过」不会刷新生成时间 —— 没生成就没时间，这是有意的。
    from gen_stamp import stamp as _stamp
    _stamp(p.name, "floors", base=os.path.dirname(p.out_dir), n=len(floors),
           by="run_step.recognize")


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
    from gen_stamp import stamp_file as _stamp_file
    _stamp_file(p.name, "glb", bsg.OUT, base=out_parent, by="run_step.glb",
                windows=bool(include_windows), skip_floors=sorted(bsg.SKIP_FLOORS))


CONFIG = os.path.join(ROOT, "config", "pipeline.json")


def load_flow_config():
    """读 config/pipeline.json（成图阶段与视图清单都在这里，改配置不用改代码）。

    为什么读文件而不是写死在代码里：渲染是「渲染→看→调参→再渲染」这个循环里的一步，
    一次要出四五张图。写死在代码里 ⇒ 想换个机位/加一张图就得改 .py，而改 .py 又会
    让识别增量指纹失效（指纹含 backend/recognizer/*.py）⇒ 顺手触发一次全量重识别。
    配置在数据侧，改它零代价。
    """
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def step_render(name, only=None):
    """按 config/pipeline.json 的「成图」段渲染 GLB 三视图。

    ★ 路径一律先 abspath 再交给 Blender：实测过相对 `--out` 会被 Blender 解析到
      **它自己的进程 CWD**（那一趟落在 `C:\\`），而三次渲染 RC 全 0、图全在仓库外 ——
      「图出来了」与「图在我以为的地方」在 RC 那一行长得一模一样。
    """
    import subprocess
    cfg = load_flow_config()
    r = cfg.get("成图") or {}
    if not r:
        print("[render] config/pipeline.json 里没有「成图」段", file=sys.stderr)
        return 1
    bdir = os.path.join(BUILDINGS, name)
    sub = {"name": name, "building_dir": bdir, "root": ROOT}

    def expand(s):
        return os.path.abspath(os.path.normpath(s.format(**sub)))

    glb = expand(r["glb"]) if r.get("glb") else os.path.join(bdir, f"{name}-building.glb")
    if not os.path.exists(glb):                       # 注册表楼（理化楼）落在 DATA 根
        alt = os.path.join(DATA, f"{name}-building.glb")
        if os.path.exists(alt):
            glb = alt
    if not os.path.exists(glb):
        print(f"[render] 找不到 GLB: {glb}", file=sys.stderr)
        return 1
    out_dir = expand(r["out_dir"])
    os.makedirs(out_dir, exist_ok=True)
    script = os.path.join(ROOT, r["script"])
    blender = r.get("blender") or "blender"
    if not os.path.exists(blender):
        blender = "blender"                            # 配置里的路径失效时退回 PATH
    res = r.get("res", "1600x1200")

    print(f"[render] {name}  GLB={glb}  ({os.path.getsize(glb)} B)")
    print(f"[render] 输出目录={out_dir}  视图 {len(r.get('views') or [])} 档")
    bad = []
    for v in (r.get("views") or []):
        if only and v["id"] not in only:
            continue
        out = os.path.join(out_dir, f"{v['id']}.png")
        cmd = [blender, "-b", "-P", script, "--",
               "--glb", glb, "--out", out, "--view", v["view"], "--res", res]
        if v.get("flat"):
            cmd.append("--flat")
        logf = os.path.join(out_dir, f"render_{v['id']}.log")
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        with open(logf, "w", encoding="utf-8") as f:
            f.write((p.stdout or "") + "\n--- stderr ---\n" + (p.stderr or ""))
        ok = p.returncode == 0 and os.path.exists(out)
        size = os.path.getsize(out) if os.path.exists(out) else 0
        print(f"[render] {v['id']:<11} {v['label']:<22} "
              f"{'OK ' if ok else 'FAIL'} {size:>9} B  {out}")
        if not ok:
            bad.append(v["id"])
    if bad:
        print(f"[render] ★ 失败 {len(bad)} 档: {bad}（日志在同目录 render_*.log）", file=sys.stderr)
        return 1
    return 0


def _default_glb_windows():
    """`glb_windows` 的**唯一**默认值来源 —— `build_standard_glb.INCLUDE_SYNTHETIC_WINDOWS`。

    ★ 为什么不在这里写个字面量 `True`：这个键今天**已经有三个默认值**
      （模块常量 True / 本函数早先"缺档"分支 False / SU 那条路 `_cfg.get("glb_windows", True)`），
      再抄一个进来就是**第四个** —— 而「两个地方写同一个数，一致证明不了它是对的」（铁律 18）。
      这里只读**唯一那份**定义：`backend/modeling/build_standard_glb.py` 的模块常量
      （本文件导入时的 `ensure_sys_path("modeling", "nav")` 已把那个目录挂上 sys.path）。
    ★ 取不到时回落到 True，**并且要出声**：「取不到」与「取到 True」在屏幕上不许长得一样
      （铁律 23b / 46：一条恒绿的腿与一条没跑过的腿，在屏幕上都不是"故障"，是"没有这一行"）。
    """
    try:
        import build_standard_glb as bsg
        return bool(getattr(bsg, "INCLUDE_SYNTHETIC_WINDOWS", True))
    except Exception as e:                                          # noqa: BLE001
        print("[glb档] 取不到模块默认（%s: %s）⇒ 按 True 出口" % (type(e).__name__, e),
              file=sys.stderr)
        return True


def glb_opts_from_profile(name):
    """未在命令行指定时，回落到该楼 profile.json 的 GLB 导出档位键。

    为什么要有这一步：控制台「导出合成窗」开关写的就是 `glb_windows`，而控制台调
    `run_step.py <name> glb` 是**不带第三个参数**的 —— 没有这个回落，开关写了档
    却不生效，重出 GLB 会静默把窗全剥掉。
    `skip_floors`（要从模型里剔除的层号，0 基）同理，由控制台档案驱动。

    ★ 下面这句 2026-09-26 已改口，原话留在这里当证据（它是本仓那句假告警的源头）：
      原话：「load_profile 逐键读取，**识别层不认这两个键，所以它们只影响这里**。」
      前半句是真的（它们确实不是 `BuildingProfile` 字段），**后半句是假的**：
        · `glb_windows` 还被 `backend/modeling/su_spec_floors_fleet.py` 里那句
          `G.INCLUDE_SYNTHETIC_WINDOWS = ...` 读去 —— 那是**造 SU / 交付 .skp** 的那条路；
        · `skip_floors` 还被 `build_index.py` 的 `exported_floors` 读去算
          `data/buildings/index.json` 的 `floors` 列（c103 `floors=5 / floors_total=6` 的来路）。
      ⇒ 教训一句话：**「这个函数不读它」和「全仓没人读它」是两件事**，
        而把前者写成后者时，屏幕上完全看不出来 —— 本文件这句注释就是活的样本：
        它被 `console_meta._delivery_channels()` 的通道表当成依据，那张表因此少了 2 条通道，
        告警于是印出「只由控制台的 GLB 导出读」。（同一句话还抄在 `backend/checks/builtin.py`
        的 `check_a8` 里与 `run_step.py` 本函数里，两处都改过。）
      ★ 引用别处一律用**符号名**（`G.INCLUDE_SYNTHETIC_WINDOWS` / `exported_floors` /
        `check_a8`），**不写行号** —— 行号会随编辑漂移，而漂了之后"那一行还在吗"照样绿
        （铁律 31：常量编辑的文件一律用符号锚点）。

    ★ 2026-09-26 修：**「缺档」不是「关窗」，而且档案有两处。**
      实测（本次，仅理化楼一栋）：`data/buildings/lihua/profile.json` **不存在**
      —— 理化楼是注册表楼，它的 `dir` 就是 `data` 根；而 `load_profile` 为它走的是
      「楼档案 → 覆盖档 `data/<名>-profile.json` → 注册表」**三级**回落，
      本函数以前**只有第一级**。后果两条，都落在这一个楼身上：
        · 缺档 ⇒ 直接返回 `windows=False` ⇒ 控制台「重出 GLB」会把它 **313 扇合成窗
          全部剥掉**（实测 `data/floors/floor*.json` 313 扇窗 100% `synthetic`；
          而 SU 那条路缺键取 True ⇒ **同一栋楼：页面/su 开窗、控制台出的 GLB 无窗**）。
        · `console.put_profile` 对登记表楼写的是覆盖档 `data/<名>-profile.json`，
          而本函数**从不读它** ⇒ 理化楼在控制台上那个「导出合成窗」开关**是死的**
          （勾了不生效，且不报错 —— 死旋钮的典型形态）。
      ⇒ 现在两处档案按 `load_profile` 的同一条链读；并且「键不在」也按**模块默认**，
        不再等同于 False（"没写" ≠ "写了 false"）。
      ★ 今天**零行为变化**（修完实测）：96 份楼档案的 `glb_windows` 是 **96/96 全 True**，
        盘上 `data/*-profile.json` **一个都没有** ⇒ 唯一变的读数就是理化楼
        （`False → True`，即那 313 扇窗回来）。这一点必须**量**：整批 A/B 见
        `_scratch/_probe_glb_opts_ab.py`（逐楼比新旧两套规则，差异集必须恰好 = {lihua}）。
    """
    opts = {"windows": _default_glb_windows(), "skip_floors": ()}
    pjson = os.path.join(BUILDINGS, name, "profile.json")
    if not os.path.exists(pjson):
        # 覆盖档：登记表楼（理化楼）在控制台上改的档位写在这里，不在 buildings/ 下。
        pjson = os.path.join(DATA, "%s-profile.json" % name)
    if not os.path.exists(pjson):
        print("[glb档] %s 楼档案与覆盖档都没有 ⇒ 按模块默认（合成窗%s）"
              % (name, "开" if opts["windows"] else "关"), file=sys.stderr)
        return opts
    try:
        with open(pjson, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:                                          # noqa: BLE001
        print("[glb档] %s 的 %s 读不动（%s）⇒ 按模块默认" % (name, pjson, e),
              file=sys.stderr)
        return opts
    if "glb_windows" in d:                    # 键不在 = 没写过 ⇒ 别把它读成"关"
        opts["windows"] = bool(d.get("glb_windows"))
    opts["skip_floors"] = tuple(int(v) for v in (d.get("skip_floors") or []))
    return opts


def main():
    if len(sys.argv) < 3:
        print("用法: python run_step.py <name> <recognize|glb|render|full> [windows|nowindows]"
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
        if step == "render":
            rc = step_render(name)
            if rc:
                return rc
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
