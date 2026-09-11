# -*- coding: utf-8 -*-
"""数字孪生建模控制台后端。

网页控制台（frontend/control.html）的 API + 静态托管：
  GET  /                               → control.html
  GET  /node_modules/...               → three.js（importmap 用，防穿越）
  GET  /data/...                       → GLB / floor / spec 等产物（防穿越）
  GET  /api/buildings                  → 楼栋列表（批次 + 注册表）
  GET  /api/buildings/<name>/profile   → 档案 JSON
  PUT  /api/buildings/<name>/profile   → 写回档案 JSON
  GET  /api/buildings/<name>/spec      → 规格 JSON
  PUT  /api/buildings/<name>/spec      → 写回规格 JSON
  POST /api/buildings/<name>/run       → 起一个 job 跑某阶段（见 console_meta.PIPELINE）
  GET  /api/jobs/<id>                  → 轮询 job 日志/状态
  GET  /api/meta                       → 参数与流程元数据（单一事实源，见 console_meta）
  GET  /api/buildings/<name>/status    → 逐阶段产物现状（完成/过期）

仅监听 127.0.0.1（本地工具，不对外）。运行:
  python control.py     → 浏览器打开 http://127.0.0.1:8130/
"""
import dataclasses
import glob
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\gym3d")
sys.path.insert(0, r"D:\gym3d\backend")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import console_meta  # noqa: E402  参数/流程元数据（单一事实源）

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(DIR, "..", ".."))
FRONTEND = os.path.join(ROOT, "frontend")
DATA = os.path.join(ROOT, "data")
BUILDINGS = os.path.join(DATA, "buildings")
NODE_MODULES = os.path.join(ROOT, "node_modules")
RUN_STEP = os.path.join(DIR, "run_step.py")

HOST = os.environ.get("CONTROL_HOST", "127.0.0.1")
PORT = int(os.environ.get("CONTROL_PORT", "8130"))

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# 可跑的阶段一律以 console_meta.PIPELINE 为唯一事实源（含全部 11 个阶段），
# 旧的 recognize|glb|full 三个是它的子集，控制台前端的旧按钮继续可用。
VALID_STEPS = tuple(console_meta.runnable_ids())

# job 状态表: jobId -> {"name", "step", "scope", "log": [...], "code", "done", "proc"}
JOBS = {}
JOBS_LOCK = threading.Lock()


def _safe_static(rel, root, path):
    """防目录穿越的静态文件托管；成功返回字节串，失败返回 None。"""
    if ".." in rel:
        return None
    full = os.path.normpath(os.path.join(root, path))
    if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
        return None
    with open(full, "rb") as f:
        return f.read()


def _norm(o):
    if isinstance(o, tuple):
        return [_norm(x) for x in o]
    if isinstance(o, list):
        return [_norm(x) for x in o]
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    return o


def _profile_to_json(p):
    return _norm(dataclasses.asdict(p))


def _registry_profiles():
    import recognizer.profiles  # noqa: F401  导入即注册 lihua / j6
    from recognizer.profile import _PROFILES
    return _PROFILES


def _building_names():
    names = []
    if os.path.isdir(BUILDINGS):
        for d in sorted(os.listdir(BUILDINGS)):
            if os.path.exists(os.path.join(BUILDINGS, d, "profile.json")):
                names.append(d)
    return names


def _count_floors(out_dir):
    return len(glob.glob(os.path.join(out_dir, "floor*.json")))


# 楼层资产缓存：key=(name, F, kind) → bytes；kind ∈ {"png", "dxf"}
_FLOOR_CACHE = {}


def _floor_png(name, F):
    """渲染 name 楼 F 层 DXF 平面图为 PNG bytes（进程内缓存，墙黑/门红/柱蓝/梯绿）。"""
    key = (name, F, "png")
    if key in _FLOOR_CACHE:
        return _FLOOR_CACHE[key]
    import run_step
    from vision.render_floor import render_floor_png
    p = run_step.load_profile(name)
    png = render_floor_png(p, F)
    _FLOOR_CACHE[key] = png
    return png


def _entity_points(e):
    """从 DXF 实体提取定位点（用于 floor_of 判楼层）。"""
    t = e.dxftype()
    if t == "LWPOLYLINE":
        return [tuple(p[:2]) for p in e.get_points()]
    if t == "LINE":
        return [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
    if t == "INSERT":
        return [(e.dxf.insert.x, e.dxf.insert.y)]
    if t in ("TEXT", "MTEXT"):
        return [(e.dxf.insert.x, e.dxf.insert.y)]
    if t in ("ARC", "CIRCLE"):
        return [(e.dxf.center.x, e.dxf.center.y)]
    return None


def _floor_dxf(name, F):
    """把源 DXF 拆出 F 层实体，写独立 DXF，返回 bytes（缓存）。"""
    key = (name, F, "dxf")
    if key in _FLOOR_CACHE:
        return _FLOOR_CACHE[key]
    import run_step
    import ezdxf
    from recognizer.profile import floor_of
    p = run_step.load_profile(name)
    src = ezdxf.readfile(p.dxf)
    out = ezdxf.new()
    msp = out.modelspace()
    n = 0
    for e in src.modelspace():
        pts = _entity_points(e)
        if not pts:
            continue
        cx = sum(x for x, y in pts) / len(pts)
        cy = sum(y for x, y in pts) / len(pts)
        if floor_of(p, cx, cy) != F:
            continue
        msp.add_entity(e.copy())
        n += 1
    if n == 0:
        return None
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmp.close()
    out.saveas(tmp.name)
    with open(tmp.name, "rb") as f:
        data = f.read()
    os.remove(tmp.name)
    _FLOOR_CACHE[key] = data
    return data


def _spec_path(name, out_dir):
    parent = os.path.dirname(out_dir)
    try:
        is_batch = os.path.commonpath([BUILDINGS, parent]) == BUILDINGS
    except ValueError:
        is_batch = False
    return os.path.join(parent if is_batch else DATA, "spec.json")


def _glb_rel(name, out_dir):
    parent = os.path.dirname(out_dir)
    try:
        is_batch = os.path.commonpath([BUILDINGS, parent]) == BUILDINGS
    except ValueError:
        is_batch = False
    if is_batch:
        return f"buildings/{name}/{name}-building.glb"
    return f"{name}-building.glb"


def _building_ctx(name):
    """该楼的路径上下文：{parent, floors_dir, glb}。

    parent = 产物根（批次楼 data/buildings/<name>，注册表楼 data），
    console_meta.PIPELINE 里 produces 的相对路径都相对它（`buildings/` 开头的相对 DATA）。
    """
    pjson = os.path.join(BUILDINGS, name, "profile.json")
    cfg = {}
    if os.path.exists(pjson):
        try:
            with open(pjson, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}
    out_dir = cfg.get("out_dir")
    dxf = cfg.get("dxf")
    if not out_dir or not dxf:
        reg = _registry_profiles()
        rp = reg.get(name)
        if not out_dir:
            out_dir = rp.out_dir if rp else os.path.join(BUILDINGS, name, "floors")
        if not dxf and rp:
            dxf = rp.dxf
    parent = os.path.dirname(out_dir)
    glb = os.path.join(parent, f"{name}-building.glb")
    return {"parent": parent, "floors_dir": out_dir, "glb": glb, "dxf": dxf}


def _resolve_artifact(name, rel):
    """把 PIPELINE.produces 里的相对模板解析成绝对路径。"""
    rel = rel.format(name=name)
    if rel.startswith("buildings/"):
        return os.path.join(DATA, *rel.split("/"))
    return os.path.join(_building_ctx(name)["parent"], *rel.split("/"))


def _floors_mtime(floors_dir):
    """全部 floor*.json 里最新的 mtime；无楼层返回 None。"""
    if not os.path.isdir(floors_dir):
        return None
    ms = [os.path.getmtime(f) for f in glob.glob(os.path.join(floors_dir, "floor*.json"))]
    return max(ms) if ms else None


def glb_is_stale(floors_dir, glb_path):
    """GLB 是否早于它自己的上游（最新 floor*.json）—— 即「改过楼层但没重出模型」。

    这是列表页要的粗判据：全仓 33/49 栋属于这种情况（模型是墙解融**之前**的产物），
    看一眼就能决定要不要重出，不用逐栋点进去。缺任一端都返回 False（无从判断≠过期）。

    **盲区（已知，无法用 mtime 解决）**：任何文件复制/还原都会刷新目标 mtime，
    于是「把旧 GLB 拷回去」看起来就是新鲜的。c022 就是活例——它的交付件仍是
    blob 时代产物（81,874 三角），但 2026-09-10 从 .orig 拷回时 mtime 被刷新，
    本判据报「不过期」。要根治得在建 GLB 时把源楼层指纹写进档案，
    属于引擎侧改动，未做。所以：**判「过期」可信，判「不过期」不可全信**。
    """
    fm = _floors_mtime(floors_dir)
    if fm is None or not os.path.exists(glb_path):
        return False
    return os.path.getmtime(glb_path) < fm


def building_status(name):
    """逐阶段产物现状 —— 「流程化」的核心：一眼看出这栋楼走到哪、哪一步过期了。

    过期判据是**逐阶段的**，用该阶段自己的上游真值（console_meta.PIPELINE.upstream）：
      · upstream='dxf'     → 产物 mtime 早于源 DXF = 图纸更新了但没重跑
      · upstream='floors'  → 产物 mtime 早于最新 floor*.json = 楼层改了但没重出
                             （那批「GLB 过期」正是这一类）
      · upstream=None      → 无产物或只读，不判过期
    inplace 阶段（thin / doorpunch 就地改写楼层）没有独立产物，done/stale 置 None ——
    报「已完成」会是假信号（floor0.json 早在 recognize 时就存在了）。
    """
    ctx = _building_ctx(name)
    fm = _floors_mtime(ctx["floors_dir"])
    dxf = ctx.get("dxf")
    dm = os.path.getmtime(dxf) if dxf and os.path.exists(dxf) else None
    up_m = {"floors": fm, "dxf": dm, "source": dm, None: None}

    stages = []
    for s in console_meta.PIPELINE:
        up = up_m.get(s.get("upstream"))
        inplace = bool(s.get("inplace"))
        arts = []
        for rel in s.get("produces", []):
            fp = _resolve_artifact(name, rel)
            if os.path.exists(fp):
                m = os.path.getmtime(fp)
                arts.append({"rel": rel.format(name=name), "exists": True,
                             "size": os.path.getsize(fp), "mtime": int(m),
                             "stale": None if inplace else bool(up and m < up)})
            else:
                arts.append({"rel": rel.format(name=name), "exists": False,
                             "size": 0, "mtime": None, "stale": None})
        if inplace:
            done = stale = None      # 无法从产物推断，前端显示「就地改写」
        else:
            done = bool(arts) and all(a["exists"] for a in arts)
            stale = bool(arts) and any(a["stale"] for a in arts)
        stages.append({
            "id": s["id"], "no": s["no"], "label": s["label"],
            "scope": s.get("scope"), "writes": s.get("writes", False),
            "slow": s.get("slow", False), "runnable": s.get("runnable", False),
            "danger": s.get("danger"), "desc": s.get("desc", ""),
            "whyManual": s.get("why_manual"), "script": s.get("script"),
            "inplace": inplace, "upstream": s.get("upstream"),
            "artifacts": arts, "done": done, "stale": stale,
        })
    glb_m = os.path.getmtime(ctx["glb"]) if os.path.exists(ctx["glb"]) else None
    return {
        "name": name,
        "floorsMtime": int(fm) if fm else None,
        "dxfMtime": int(dm) if dm else None,
        "glbMtime": int(glb_m) if glb_m else None,
        "glbStale": bool(fm and glb_m and glb_m < fm),
        "nFloors": _count_floors(ctx["floors_dir"]),
        "stages": stages,
    }


def list_buildings():
    out = []
    for name in _building_names():
        pjson = os.path.join(BUILDINGS, name, "profile.json")
        try:
            with open(pjson, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}
        out_dir = cfg.get("out_dir") or os.path.join(BUILDINGS, name, "floors")
        style = cfg.get("style") or {}
        out.append({
            "name": name, "title": cfg.get("title", name), "source": "batch",
            "classifier": cfg.get("classifier", "lwpolyline"),
            "roofType": style.get("roofType", "gable"),
            "floors": _count_floors(out_dir),
            "glb": os.path.exists(os.path.join(BUILDINGS, name, f"{name}-building.glb")),
            "glbRel": f"buildings/{name}/{name}-building.glb",
            "spec": os.path.exists(os.path.join(BUILDINGS, name, "spec.json")),
            "dxfPlan": os.path.exists(os.path.join(BUILDINGS, name, "dxf_plan", "index.html")),
            "compare": os.path.exists(os.path.join(BUILDINGS, name, "compare.html")),
            "glbStale": glb_is_stale(out_dir, os.path.join(BUILDINGS, name, f"{name}-building.glb")),
        })
    # 注册表楼（理化楼等）——仅收录 dxf 真实存在的（j6 占位路径不存在，自动排除）
    for name, p in _registry_profiles().items():
        if not os.path.exists(p.dxf):
            continue
        override = os.path.join(DATA, f"{name}-profile.json")
        if os.path.exists(override):
            with open(override, encoding="utf-8") as f:
                cfg = json.load(f)
            out_dir = cfg.get("out_dir") or p.out_dir
            style = cfg.get("style") or {}
            classifier = cfg.get("classifier", p.classifier)
        else:
            out_dir, style, classifier = p.out_dir, p.style or {}, p.classifier
        out.append({
            "name": name, "title": p.title, "source": "registry",
            "classifier": classifier,
            "roofType": style.get("roofType", "gable"),
            "floors": _count_floors(out_dir),
            "glb": os.path.exists(os.path.join(DATA, f"{name}-building.glb")),
            "glbRel": f"{name}-building.glb",
            "spec": os.path.exists(os.path.join(DATA, "spec.json")),
            "dxfPlan": os.path.exists(os.path.join(
                os.path.dirname(out_dir), "dxf_plan", "index.html")),
            "compare": os.path.exists(os.path.join(os.path.dirname(out_dir), "compare.html")),
            "glbStale": glb_is_stale(out_dir, os.path.join(DATA, f"{name}-building.glb")),
        })
    return out


def get_profile(name):
    pjson = os.path.join(BUILDINGS, name, "profile.json")
    if os.path.exists(pjson):
        with open(pjson, encoding="utf-8") as f:
            return json.load(f)
    override = os.path.join(DATA, f"{name}-profile.json")
    if os.path.exists(override):
        with open(override, encoding="utf-8") as f:
            return json.load(f)
    reg = _registry_profiles()
    if name in reg:
        return _profile_to_json(reg[name])
    return None


def put_profile(name, obj):
    pjson = os.path.join(BUILDINGS, name, "profile.json")
    if os.path.exists(pjson):
        target = pjson
        existing = {}
        try:
            with open(pjson, encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        # 合并：只覆盖前端传回的键，避免丢高级字段。
        # 但合并写有个副作用：**键永远删不掉** —— 前端把「层序倒置」的 floor_ys 清空后，
        # 合并会把旧值原样搬回来，「留空=不启用」于是失效。
        # 约定 null = 显式关闭：前端清空某字段时传 null，这里把它删掉。
        # （消费端一律 cfg.get(k) 真值判断，null 与键不存在完全等价，已逐处核对。）
        # 注意用 `is None` 而非假值判断：glb_windows=false 必须保留。
        merged = {**existing, **obj}
        for k in [k for k, v in merged.items() if v is None]:
            del merged[k]
        with open(target, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=1)
        return target
    # 注册表楼：写覆盖档案 data/<name>-profile.json（不改 profiles/*.py）
    target = os.path.join(DATA, f"{name}-profile.json")
    with open(target, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return target


def get_spec(name):
    reg = _registry_profiles()
    if name in reg:
        sp = os.path.join(DATA, "spec.json")
    else:
        sp = os.path.join(BUILDINGS, name, "spec.json")
    if not os.path.exists(sp):
        return None
    with open(sp, encoding="utf-8") as f:
        return json.load(f)


def put_spec(name, obj):
    reg = _registry_profiles()
    sp = os.path.join(DATA, "spec.json") if name in reg else os.path.join(BUILDINGS, name, "spec.json")
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return sp


def stage_argv(name, step, windows):
    """构造阶段的命令行（不含解释器）。返回 None = 未知阶段。

    recognize/glb/full 继续走 run_step.py —— 它是「档案加载优先级 + 输出路径覆盖」的
    唯一正确实现（批次楼写 <name>/，注册表楼写 data/），绕开它会写错地方。
    其余阶段直接调根目录脚本，参数来自 console_meta.PIPELINE 的 args 模板。
    """
    st = console_meta.get_stage(step)
    if step in ("recognize", "glb", "full"):
        return [RUN_STEP, name, step] + (["windows"] if windows else [])
    if st is None or not st.get("runnable"):
        return None
    script = os.path.join(ROOT, *st["script"].split("/"))
    return [script] + [a.format(name=name) for a in st.get("args", [])]


def job_conflict(name, step):
    """返回第一个冲突的进行中 job；无冲突返回 None。

    串行规则（比原来只比 name 更强）：
      · 同楼不并发（两个阶段同时写 floor*.json 会互相顶掉）
      · 全仓阶段（sweep / index）与任何任务都不并发 —— build_index 读楼层时
        若另一楼在写，索引会记下半成品
    """
    st = console_meta.get_stage(step) or {}
    new_all = st.get("scope") == "all"
    with JOBS_LOCK:
        for j in JOBS.values():
            if j["done"]:
                continue
            if new_all or j.get("scope") == "all" or j["name"] == name:
                return j
    return None


def start_job(name, step, windows):
    """后台线程跑 subprocess，逐行收集日志；返回 jobId。"""
    job_id = uuid.uuid4().hex[:12]
    argv = stage_argv(name, step, windows)
    argv = [sys.executable] + argv
    st = console_meta.get_stage(step) or {}
    job = {"name": name, "step": step, "scope": st.get("scope"),
           "log": [], "code": None, "done": False, "proc": None}
    with JOBS_LOCK:
        JOBS[job_id] = job

    def _run():
        try:
            # cwd 固定为仓库根：根目录脚本里有大量相对路径（dxf_plan/、data/…），
            # 继承控制台的启动目录会在别处启动时写错位置。
            proc = subprocess.Popen(
                argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            job["proc"] = proc
            for line in proc.stdout:
                job["log"].append(line.rstrip("\n"))
            proc.wait()
            job["code"] = proc.returncode
        except Exception as e:  # noqa: BLE001
            job["log"].append(f"[control] 启动失败: {type(e).__name__}: {e}")
            job["code"] = -1
        finally:
            job["done"] = True

    threading.Thread(target=_run, daemon=True).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, status=200, ctype="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(body, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ---- 路由 ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self._serve_file(os.path.join(FRONTEND, "control.html"), "text/html; charset=utf-8")
            elif path == "/control.js":
                # 控制台脚本拆成独立文件（HTML 已 700+ 行，再堆会超 800 行上限）
                self._serve_file(os.path.join(FRONTEND, "control.js"),
                                 "text/javascript; charset=utf-8")
            elif path == "/favicon.ico":
                self._json({"success": False, "error": "not found"}, 404)
            elif path.startswith("/node_modules/"):
                rel = path[len("/node_modules/"):]
                body = _safe_static(rel, NODE_MODULES, rel)
                if body is None:
                    self._json({"success": False, "error": "not found"}, 404)
                else:
                    ctype = "text/javascript; charset=utf-8" if rel.endswith(".js") \
                        else "application/octet-stream"
                    self._send(body, 200, ctype)
            elif path.startswith("/data/"):
                rel = path[len("/data/"):]
                body = _safe_static(rel, DATA, rel)
                if body is None:
                    self._json({"success": False, "error": "not found"}, 404)
                else:
                    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
                    _IMG = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                            "webp": "image/webp", "gif": "image/gif"}
                    ctype = ("application/json; charset=utf-8" if ext == "json"
                             else "text/html; charset=utf-8" if ext == "html"
                             else "model/gltf-binary" if ext == "glb"
                             else _IMG.get(ext, "application/octet-stream"))
                    self._send(body, 200, ctype)
            elif path == "/api/meta":
                # 参数化 + 流程化的单一事实源：全部档案字段、全部规格字段、完整阶段链
                self._json({"success": True, "error": None, "data": {
                    "profile": console_meta.PROFILE_GROUPS,
                    "spec": console_meta.SPEC_GROUPS,
                    "styleKeys": console_meta.STYLE_KEYS,
                    "pipeline": console_meta.PIPELINE,
                    "specDefaults": console_meta.spec_defaults(),
                    "runnable": console_meta.runnable_ids(),
                }})
            elif path == "/api/buildings":
                self._json({"success": True, "data": list_buildings(), "error": None})
            elif path.startswith("/api/buildings/"):
                rest = path[len("/api/buildings/"):]
                # 楼层资产：/api/buildings/<name>/floor/<F>.png | .dxf
                m = re.match(r"^([A-Za-z0-9_-]+)/floor/(\d+)\.(png|dxf)$", rest)
                if m:
                    name, F, ext = m.group(1), int(m.group(2)), m.group(3)
                    data = _floor_png(name, F) if ext == "png" else _floor_dxf(name, F)
                    if data is None:
                        self._json({"success": False, "error": "无此层"}, 404)
                    else:
                        self._send(data, 200, "image/png" if ext == "png" else "application/dxf")
                    return
                # 逐阶段产物现状（哪一步做完、哪一步过期）
                m = re.match(r"^([A-Za-z0-9_-]+)/status$", rest)
                if m:
                    name = m.group(1)
                    if not NAME_RE.match(name):
                        self._json({"success": False, "error": "非法楼栋名"}, 400)
                        return
                    self._json({"success": True, "data": building_status(name), "error": None})
                    return
                if rest.endswith("/profile"):
                    name = rest[:-len("/profile")]
                elif rest.endswith("/spec"):
                    name = rest[:-len("/spec")]
                else:
                    self._json({"success": False, "error": "not found"}, 404)
                    return
                if not NAME_RE.match(name):
                    self._json({"success": False, "error": "非法楼栋名"}, 400)
                    return
                if rest.endswith("/profile"):
                    obj = get_profile(name)
                    self._json({"success": obj is not None, "data": obj, "error": None},
                               200 if obj is not None else 404)
                else:
                    obj = get_spec(name)
                    self._json({"success": obj is not None, "data": obj, "error": None},
                               200 if obj is not None else 404)
            elif path.startswith("/api/jobs/"):
                job_id = path[len("/api/jobs/"):]
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                if job is None:
                    self._json({"success": False, "error": "job 不存在"}, 404)
                    return
                self._json({"success": True, "data": {
                    "running": not job["done"], "done": job["done"],
                    "code": job["code"], "log": "\n".join(job["log"]),
                }, "error": None})
            else:
                self._json({"success": False, "error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            print(f"[control] GET {path} -> {type(e).__name__}: {e}", file=sys.stderr)
            self._json({"success": False, "error": "服务器内部错误"}, 500)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        try:
            if path.startswith("/api/buildings/"):
                rest = path[len("/api/buildings/"):]
                if rest.endswith("/profile"):
                    name = rest[:-len("/profile")]
                elif rest.endswith("/spec"):
                    name = rest[:-len("/spec")]
                else:
                    self._json({"success": False, "error": "not found"}, 404)
                    return
                if not NAME_RE.match(name) or body is None:
                    self._json({"success": False, "error": "非法请求"}, 400)
                    return
                if rest.endswith("/profile"):
                    target = put_profile(name, body)
                    self._json({"success": True, "data": {"wrote": target}, "error": None})
                else:
                    target = put_spec(name, body)
                    self._json({"success": True, "data": {"wrote": target}, "error": None})
            else:
                self._json({"success": False, "error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            print(f"[control] PUT {path} -> {type(e).__name__}: {e}", file=sys.stderr)
            self._json({"success": False, "error": f"服务器内部错误: {e}"}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body() or {}
        try:
            if path.startswith("/api/buildings/") and path.endswith("/run"):
                name = path[len("/api/buildings/"):-len("/run")]
                if not NAME_RE.match(name):
                    self._json({"success": False, "error": "非法楼栋名"}, 400)
                    return
                step = body.get("step")
                if step not in VALID_STEPS:
                    self._json({"success": False,
                                "error": f"step 必须为 {VALID_STEPS}"}, 400)
                    return
                windows = bool(body.get("windows"))
                clash = job_conflict(name, step)
                if clash:
                    self._json({"success": False,
                                "error": f"{clash['name']}/{clash['step']} 正在跑，"
                                         f"请等它完成再发起（同楼与全仓阶段都串行）"}, 409)
                    return
                job_id = start_job(name, step, windows)
                self._json({"success": True, "data": {"jobId": job_id}, "error": None})
            else:
                self._json({"success": False, "error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            print(f"[control] POST {path} -> {type(e).__name__}: {e}", file=sys.stderr)
            self._json({"success": False, "error": "服务器内部错误"}, 500)

    def _serve_file(self, full, ctype):
        with open(full, "rb") as f:
            body = f.read()
        self._send(body, 200, ctype)

    def log_message(self, fmt, *args):
        pass  # 静默访问日志


if __name__ == "__main__":
    warns = console_meta.self_check()
    for w in warns:
        print(f"  [元数据告警] {w}", file=sys.stderr)

    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"数字孪生建模控制台 -> http://{HOST}:{PORT}/")
    print(f"  楼栋: {len(list_buildings())} 栋（批次 + 注册表）")
    print(f"  阶段: {len(console_meta.PIPELINE)} 个"
          f"（控制台可跑 {len(VALID_STEPS)}：{'、'.join(VALID_STEPS)}）")
    n_prof = sum(len(g['fields']) for g in console_meta.PROFILE_GROUPS)
    n_spec = sum(len(g['fields']) for g in console_meta.SPEC_GROUPS)
    print(f"  参数: 档案 {n_prof} 项 + 规格 {n_spec} 项"
          + (f"（{len(warns)} 条元数据告警见上）" if warns else "，元数据自检干净"))
    srv.serve_forever()
