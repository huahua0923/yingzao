# -*- coding: utf-8 -*-
r"""cdut3d 建模工作台 —— 本地系统平台（2026-10-19）。

用户口径：「做成一个系统平台，所有参数都能看到和修改，不是黑盒中运行，
每个建筑的生成都有依据，有错误可以直接在页面上指出修改、从哪个方向修改。」

**只读优先**：页面上的每个数都现场从盘上读（档案 / 参数 / 判据 verdict / 包 manifest /
链上产物的存在性与时刻）。写只有两条口：`/api/params/save` 与 `/api/profile/save`，
都先**校验**再**备份**再**字节层原子替换**，最后**回读验一遍**。

启动：
    python -X utf8 -I workbench/server.py --port 8150
    （只绑 127.0.0.1；这不是公网服务）

安全：
  · 写请求必须同源；生产环境由 Nginx 终止 TLS 并保护管理端；
  · POST 必须是 application/json 或受控的上传请求；
  · bid 只许 `[A-Za-z0-9_]` 且必须在档案里存在 —— 不做任何路径拼接猜测；
  · 静态文件只在 `workbench/ui/` 里，`..` 与绝对路径一律拒。
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import hmac
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, unquote

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

APP_VERSION = "0.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))
CDUT = os.path.dirname(HERE)
VIEWER_MODE = os.environ.get("CDUT3D_MODE", "").strip().lower() == "viewer"
TOOLS = os.path.join(CDUT, "rebuild", "tools")
for _p in (TOOLS, HERE):          # HERE：quick3d.py 与本文件同目录（-I 不会自动加脚本目录）
    if _p not in sys.path:
        sys.path.insert(0, _p)

if VIEWER_MODE:
    B = None
    O = None
else:
    import building as B  # noqa: E402  唯一路径估计器（铁律 018/174）
    import overlay_check as O  # noqa: E402  叠加比对的**唯一实现**（闸 J-10.8-04 也调它）

UI = os.path.join(HERE, "ui")
GOUT = os.path.join(CDUT, "gates", "_out")
# ★ 2026-10-19 用户令：「建个库保存每个建筑每层的dxf」「建一个库把每个建筑房间统计放进去，
#   同时可以修改」。库由 `rebuild/tools/build_libraries.py` 生成；工作台只读库 + 写改动表。
DRAW_LIB_JSON = os.path.join(CDUT, "rebuild", "构件库", "图纸库.json")
ROOM_LIB_JSON = os.path.join(CDUT, "rebuild", "构件库", "房间库.json")
ROOM_OVR_JSON = os.path.join(CDUT, "rebuild", "构件库", "房间_改动.json")
ROOM_TOOL = os.path.join(CDUT, "rebuild", "tools", "build_libraries.py")
ROOM_EDIT_FIELDS = ("房间号", "用途", "单位", "图上面积_m2", "备注")
ZHANG = os.path.join(CDUT, "rebuild", "构件库")
PROFILE_JSON = os.path.join(ZHANG, "楼栋.json")
PARAM_JSON = os.path.join(ZHANG, "参数.json")
PACKS = os.path.join(CDUT, "packs", "cdut-main")
BACKUP = os.path.join(HERE, "_backup")
JOBS = os.path.join(HERE, "_jobs")
GATES = ("J-10.8-00", "J-10.8-01", "J-10.8-04", "J-10.9-07")

# ── 登录与只读服务 ────────────────────────────────────────────────────────────
# 账号口令只允许以 scrypt 派生值出现；默认口令 `cdut2026` 是用户指定，
# 生产可用 CDUT3D_AUTH_USER / CDUT3D_AUTH_PASSWORD_HASH 覆盖。
AUTH_USER = os.environ.get("CDUT3D_AUTH_USER", "cdut2026")
AUTH_PASSWORD_HASH = os.environ.get(
    "CDUT3D_AUTH_PASSWORD_HASH",
    "scrypt$16384$8$1$a047e2d97b545c9dc3fdca0d630c6816$"
    "bc618b26c36e4f59056cd28b0b8371aa9213ac15fbe366debbf73866cf95d560",
)
AUTH_COOKIE = "cdut3d_session"
AUTH_TTL_S = 12 * 3600
AUTH_LOGIN_WINDOW_S = 600
AUTH_LOGIN_MAX = 8
AUTH_DIR = os.path.join(HERE, "_auth")
AUTH_KEY_FILE = os.path.join(AUTH_DIR, "session.key")
_AUTH_SECRET = None
_AUTH_ATTEMPTS = {}
_AUTH_LOCK = threading.Lock()


def _scrypt_verify(password, encoded):
    try:
        kind, n, r, p, salt, want = encoded.split("$", 5)
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=salt.encode("ascii"),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(want)),
        )
        return hmac.compare_digest(got, bytes.fromhex(want))
    except (TypeError, ValueError):
        return False


def auth_verify(username, password):
    return hmac.compare_digest(str(username), AUTH_USER) and _scrypt_verify(password, AUTH_PASSWORD_HASH)


def _auth_secret():
    global _AUTH_SECRET
    if _AUTH_SECRET:
        return _AUTH_SECRET
    env = os.environ.get("CDUT3D_SESSION_SECRET")
    if env:
        _AUTH_SECRET = env.encode("utf-8")
        return _AUTH_SECRET
    os.makedirs(AUTH_DIR, exist_ok=True)
    try:
        with open(AUTH_KEY_FILE, "rb") as f:
            raw = f.read().strip()
    except OSError:
        raw = secrets.token_hex(32).encode("ascii")
        with open(AUTH_KEY_FILE, "wb") as f:
            f.write(raw)
        try:
            os.chmod(AUTH_KEY_FILE, 0o600)
        except OSError:
            pass
    _AUTH_SECRET = raw
    return _AUTH_SECRET


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def auth_issue_token(username):
    payload = ("%s|%d|%s" % (username, int(time.time()) + AUTH_TTL_S,
                             secrets.token_hex(8))).encode("utf-8")
    sig = hmac.new(_auth_secret(), payload, hashlib.sha256).digest()
    return _b64e(payload) + "." + _b64e(sig)


def auth_check_token(token):
    try:
        payload_s, sig_s = token.split(".", 1)
        payload = _b64d(payload_s)
        sig = _b64d(sig_s)
        want = hmac.new(_auth_secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, want):
            return None
        username, exp_s, _nonce = payload.decode("utf-8").split("|", 2)
        if username != AUTH_USER or int(exp_s) < int(time.time()):
            return None
        return username
    except (ValueError, UnicodeDecodeError, TypeError):
        return None


def auth_redirect_target(raw):
    p = raw or "/"
    if not p.startswith("/") or p.startswith("//") or "\r" in p or "\n" in p:
        return "/"
    return p

# 平台上的叫法 —— 2026-10-19 用户「重新起个名字，你写在系统里面」。
# ★ 编号仍是真身（判据文件、verdict、文档都用它）；页面**先给人话，再给编号**。
GATE_INFO = {
    "J-10.8-00": {"名": "轮廓可用", "副": "进 SU 之前：闭合、无洞、不自交、不重叠"},
    "J-10.8-01": {"名": "形体正确", "副": "白模从网格量：总高、层区间、面积、水密"},
    "J-10.8-04": {"名": "叠加比对", "副": "生成轮廓 vs 原始 CAD：贴源率 / 覆盖率"},
    "J-10.9-07": {"名": "构件齐全", "副": "每类构件处处点名，且真的到交付件"},
}
FIX = ("改档案字段", "补足迹声明", "改源图", "改算法", "既有已知红")

# 五个方向**各自是什么**（2026-10-19 用户「你怎么判断呢？是不是没有办法在系统体现」）。
# 页面把这张表印在每个方向组的标题下，并把「动什么 / 改完跑哪步」一起给出。
FIX_INFO = {
    "改档案字段": {"说明": "档案里写的这个数与实测不符", "动": "楼栋.json / 参数.json 的那个字段",
               "后": "按 IMPACT 表从受影响的第一步重跑"},
    "补足迹声明": {"说明": "档案缺一条退台/屋顶足迹，算法没有依据", "动": "楼栋.json 的 roof_step / mid_roofs",
              "后": "从「建件」重跑"},
    "改源图": {"说明": "识别读到的与源 DXF 对不上，先分清是图错还是读法错", "动": "01_cad 源图或识别参数",
             "后": "从「识别」重跑"},
    "改算法": {"说明": "尺子对、件不对——生成或导出那一步的代码问题", "动": "rebuild/tools 下的共用步骤",
             "后": "从出问题的那一步重跑（全楼共用）"},
    "既有已知红": {"说明": "已声明并接受的残差，不再修", "动": "不改", "后": "保留读数"},
    "待判": {"说明": "闸没给出可分辨的方向，需要人看证据再定", "动": "先看 items 里的层/块", "后": "定了再改"},
}

# 档案字段 → 需要重跑的步骤（页面「从哪个方向改」的落点）
IMPACT = {
    "src_dxf": ["切图幅", "导出图幅", "识别", "建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包", "层号对账"],
    "basement": ["切图幅", "导出图幅", "识别", "建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包", "层号对账"],
    "floor_names": ["切图幅", "导出图幅", "识别", "建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包", "层号对账"],
    "top_floor": ["建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包", "层号对账"],
    "keep_layers": ["识别", "建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包"],
    "drop_layers": ["识别", "建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包"],
    "drawing": ["识别", "建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包"],
    "door_carve": ["建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包"],
    "podium_roof": ["建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包"],
    "roof_stair": ["建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包"],
    "roof_step_parapet": ["建件", "轮廓", "FreeCAD", "GLB", "逐块清单", "装包"],
    "title": ["装包"],
    "scope": ["装包"],
}
BID_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,32}-\d{1,6}$")   # `start_run` 起的就是 `<bid>-NNN`
QUICK = os.path.join(HERE, "_quick")          # 上传的 CAD → 快速立体块
# 只读挂载：现成查看器（demo/，含本地 three.js）与已装好的包（packs/）
# ★ 2026-10-20 合并后台时补两段：
#   `/过程/` —— `demo/compare.html` 两个标签的原页按相对路径取
#     `../过程/_layers/layers_c006/*.glb`（约 174 MB），不挂这一段两页都会 404；
#   `/rebuild/` —— 查看器「参照件·整栋含屋面」那一层取 `../rebuild/05_build/c006_white.glb`。
#   两段都只读、都只在本机 127.0.0.1 上（`_safe_join` 挡住 `..` / 绝对路径）。
MOUNTS = (("/demo/", os.path.join(CDUT, "demo")),
          ("/packs/", os.path.join(CDUT, "packs")),
          ("/reality/", os.path.join(CDUT, "reality")),
          ("/process/", os.path.join(CDUT, "过程")),
          ("/过程/", os.path.join(CDUT, "过程")),
          ("/rebuild/", os.path.join(CDUT, "rebuild")))

# ── 合并 8800 流程台（2026-10-20 用户令：8800 与 8150 合成一个后台）──────────────
# ★ 只这里 import 它的**函数**，不复制实现：`collect()` / `trial_run()` 仍是流程台的
#   唯一一份（铁律 018/174：两个同名的量必须死掉一个）。8800 那个进程随后停掉。
_PIPE_PATH = os.path.join(CDUT, "pipeline", "server.py")
if VIEWER_MODE:
    PIPE = None
else:
    _pipe_spec = importlib.util.spec_from_file_location("cdut_pipeline_app", _PIPE_PATH)
    if _pipe_spec is None or _pipe_spec.loader is None:
        raise RuntimeError("流程台代码不在：%s" % _PIPE_PATH)
    PIPE = importlib.util.module_from_spec(_pipe_spec)
    _pipe_spec.loader.exec_module(PIPE)


def _safe_join(base, rel):
    """把用户给的一段落路径拼到 base 下；**不在 base 里就返回 None**。

    判定用 realpath 后的前缀比对 —— `..\\..\\x`、`/etc/passwd`、`C:\\Windows` 都走这一条。
    """
    base_real = os.path.realpath(base)
    p = os.path.realpath(os.path.join(base_real, rel))
    if p == base_real or p.startswith(base_real + os.sep):
        return p
    return None


def _allowed_origin(origin, host):
    """判断写请求是否同源；允许通过环境变量额外放行部署域名。"""
    if not origin:
        return True
    u = urlparse(origin)
    if not u.scheme or not u.netloc:
        return False
    if host and u.netloc.lower() == host.lower():
        return True
    extra = os.environ.get("CDUT3D_ALLOWED_ORIGINS", "")
    allowed = {x.strip().rstrip("/").lower() for x in extra.split(",") if x.strip()}
    return origin.rstrip("/").lower() in allowed


def health_payload():
    """返回不依赖重建链的业务健康快照。"""
    if VIEWER_MODE:
        checks = {
            "login": os.path.isfile(os.path.join(UI, "login.html")),
            "viewer": os.path.isfile(os.path.join(UI, "viewer.html")),
            "info": os.path.isfile(os.path.join(UI, "space.html")),
            "packs_index": os.path.isfile(os.path.join(CDUT, "packs", "index.json")),
            "demo": os.path.isfile(os.path.join(CDUT, "demo", "building.html")),
        }
    else:
        checks = {
            "ui": os.path.isfile(os.path.join(UI, "portal.html")),
            "workbench": os.path.isfile(os.path.join(UI, "app.js")),
            "packs_index": os.path.isfile(os.path.join(CDUT, "packs", "index.json")),
            "gate_output": os.path.isdir(GOUT),
        }
    return {
        "ok": all(checks.values()),
        "service": "cdut3d",
        "version": APP_VERSION,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
    }


def quick3d_save(name, blob):
    """收一张 DXF → 快速立体块 JSON。**只读源件、只写 `_quick/`**，不碰正式链。"""
    import quick3d
    os.makedirs(QUICK, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(name))[:80] or "upload.dxf"
    qid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + \
        hashlib.sha256(blob).hexdigest()[:8]
    src = os.path.join(QUICK, qid + ".dxf")
    with open(src, "wb") as f:
        f.write(blob)
    d = quick3d.parse(src)                       # 解析失败抛 ValueError，前端看到原因
    d["original_name"] = safe
    with open(os.path.join(QUICK, qid + ".json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    return {"ok": True, "id": qid, "name": safe,
            "counts": d["counts"], "bbox": d["bbox"], "model": "/quick/%s.json" % qid}


def flow():
    """十步流程 + 参数影响面 —— 页面「流程」页的唯一数据源（不抄第二份）。"""
    import run_chain_bid as RC
    root = B.root_for("c006")
    # ★ `need` 在 _steps 里是**一个路径串**（不是列表）：直接 list() 会拆成一个个字符，
    #   页面上就变成「D · : · \ · 项 …」。这里显式归一成列表。
    steps = [{"name": n, "cmd": c,
              "need": [need] if isinstance(need, str) else list(need or [])}
             for n, c, need in RC._steps("c006", root)]
    return {"schema": "cdut3d-flow/1",
            "steps": steps,
            "impact": IMPACT,
            "gate_of_step": {
                "建件": "形体正确",
                "轮廓": "轮廓可用",
                "装包": "构件齐全"}}


# ---------------------------------------------------------------- 读盘
def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _load_or(p, default=None):
    """件不在 / 读不成 ⇒ 给默认值。★ 库与改动表可能是**第一次**写（文件还不存在），
    不能像必读件那样抛 FileNotFoundError —— 那会把「还没有」报成 500。"""
    try:
        return _load(p)
    except (OSError, ValueError):
        return default


def _mtime(p):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")
    except OSError:
        return None


def _piece(p):
    """一个产物：在不在 / 多少 / 什么时候。目录给文件数。**缺了就诚实说缺**。"""
    if not os.path.exists(p):
        return {"path": p, "exists": False}
    if os.path.isdir(p):
        n, b = 0, 0
        for r, _d, fs in os.walk(p):
            for f in fs:
                n += 1
                try:
                    b += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
        return {"path": p, "exists": True, "dir": True, "files": n,
                "bytes": b, "mtime": _mtime(p)}
    return {"path": p, "exists": True, "bytes": os.path.getsize(p), "mtime": _mtime(p)}


def _profiles():
    d = _load(PROFILE_JSON)
    return {k: v for k, v in d.items() if isinstance(v, dict) and k not in ("schema",)}


def _out_name(bid):
    """出件名前缀 —— 只读档案里的 `output`，**不触发** `building.profile()` 的层表推导。

    ★ 2026-10-19 实测：`B.out_name()` 走 `profile()`，对没写 `floor_names` 的楼会去开 DXF
      推层表（0.48 s/栋）⇒ 总览一次 67 栋要 32 s，页面卡在「读盘中…」。
      这里只取 `output` 字段，与推导无关；推导留给单栋页（只开一栋）。
    """
    return ((_profiles().get(bid) or {}).get("output")) or bid


def _write_json_full(path, obj):
    """整份原子写 + 备份 + 回读（改动表是本台自己的格式，不需要 `_write_json` 的定点替换）。"""
    b = (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    tmp = path + ".tmp-workbench"
    with open(tmp, "wb") as f:
        f.write(b)
    if json.loads(open(tmp, "rb").read().decode("utf-8")) != obj:
        os.unlink(tmp)
        raise ValueError("回读不一致：写盘被什么改过")
    bak = _backup(path) if os.path.exists(path) else None
    os.replace(tmp, path)
    return bak


def library(what):
    """两个库的现场读数。库不在 ⇒ 如实说「还没建」，不编空表。

    ★ 每栋补一个 `名称`（楼栋.json 的 `title`）：库文件只记路径/数字，楼名在档案里；
      页面要显示「编号 + 建筑名」，就地在出口补，别让前端再拼第二个来源。
    """
    if what == "draw":
        d = _load_or(DRAW_LIB_JSON)
        if not isinstance(d, dict):
            return {"schema": "cdut3d-drawing-library/1", "状态": "还没建库",
                    "楼栋": {}, "合计": {"楼栋": 0, "层": 0, "缺文件": 0}}
    elif what == "rooms":
        d = _load_or(ROOM_LIB_JSON)
        if not isinstance(d, dict):
            return {"schema": "cdut3d-room-library/1", "状态": "还没建库",
                    "楼栋": {}, "合计": {}}
    else:
        raise ValueError("库只有 draw / rooms")
    prof = _profiles()
    for bid, b in (d.get("楼栋") or {}).items():
        if isinstance(b, dict):
            b["名称"] = (prof.get(bid) or {}).get("title") or ""
    return d


def save_room(payload):
    """改一间房（人工覆盖）。写 `房间_改动.json`，再重建 `房间库.json` 的合并视图。

    ★ 改动与算得值**分开存**：算得值每次跑链都会变，改动写在覆盖表里才不会丢。
    """
    bid = str(payload.get("bid") or "").strip()
    floor = str(payload.get("层") or "").strip()
    no = str(payload.get("房间号") or "").strip()
    fields = payload.get("字段") or {}
    if bid not in _profiles():
        raise ValueError("楼栋不存在：%s" % bid)
    if not isinstance(fields, dict) or not fields:
        raise ValueError("没有要改的字段")
    bad = [k for k in fields if k not in ROOM_EDIT_FIELDS]
    if bad:
        raise ValueError("只能改 %s（给了 %s）" % ("/".join(ROOM_EDIT_FIELDS), "/".join(bad)))
    room = _load_or(ROOM_LIB_JSON) or {}
    fl = ((room.get("楼栋") or {}).get(bid) or {}).get("层", {}).get(floor)
    if not fl:
        raise ValueError("这栋的这层没有房间表：%s %s" % (bid, floor))
    if not any(str(r.get("房间号")) == no for r in (fl.get("房间") or [])):
        raise ValueError("这一层没有这个房间号：%s" % no)
    for k, v in fields.items():
        if k == "图上面积_m2":
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ValueError("面积必须是数")
        elif not isinstance(v, str):
            raise ValueError("%s 必须是字符串" % k)

    ovr = _load_or(ROOM_OVR_JSON) or {"schema": "cdut3d-room-overrides/1", "改动": {}}
    key = "%s|%s|%s" % (bid, floor, no)
    cur = dict(ovr.setdefault("改动", {}).get(key) or {})
    cur.update(fields)
    cur["_人"] = "workbench"
    cur["_时刻"] = datetime.datetime.now().isoformat(timespec="seconds")
    ovr["改动"][key] = cur
    bak = _write_json_full(ROOM_OVR_JSON, ovr)

    p = subprocess.run([sys.executable, "-I", ROOM_TOOL, "--房间"],
                       cwd=CDUT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise ValueError("重建房间库失败 rc=%d：%s" % (p.returncode, (p.stderr or p.stdout)[-500:]))
    fresh = _load_or(ROOM_LIB_JSON) or {}
    row = None
    for r in ((((fresh.get("楼栋") or {}).get(bid) or {}).get("层", {}).get(floor) or {}).get("房间") or []):
        if str(r.get("房间号")) == no:
            row = r
            break
    return {"ok": True, "kept": fields, "backup": bak, "row": row,
            "改动条数": len(ovr.get("改动") or {}),
            "说明": "改动只盖在房间库的合并视图上；源件 02_recognize/房间表.json 不动。"}


_GEOM_CACHE = {}
_GEOM_LOCK = threading.Lock()
_GEOM_CAP = 250000          # 返回的顶点上限（超过就截断并如实标 `截断`）


def raw_dxf_file(bid, floor):
    """同一层的**原始图**（`01_cad/raw/<层>.dxf`，从 src_dxf 按窗裁出来的那份）。

    ★ 层名仍然先过 `dxf_file()` 的白名单（contours/index.json），两边用同一个名单，
      否则「原始图有、生成件没有」的层会从这条路漏进任意路径。
    ★ 原始图不一定在（有的栋没留 raw）⇒ 这里如实抛 KeyError，前端显示「没有原始图」，
      不许拿生成件冒充原始件。
    """
    dxf_file(bid, floor)                                # 只借它的层名/路径校验
    cdir = os.path.realpath(os.path.join(B.root_for(bid), "01_cad", "raw"))
    p = os.path.realpath(os.path.join(cdir, floor + ".dxf"))
    if not p.startswith(cdir + os.sep) or not os.path.isfile(p):
        raise KeyError("原始图不在：%s %s" % (bid, floor))
    return p


def dxf_geom(bid, floor, kind="gen"):
    """一层 DXF → 浏览器能画的折线（只取几何，不取文字）。

    ★ 为什么在服务端解析：DXF 是文本但浏览器里没有 CAD 内核；c006 一层 1 MB、c105 一层 15 MB，
      把原文件丢给前端等于要求它自带解析器。这里用 ezdxf 在盘上读一次，按层压成折线，
      前端只管 canvas 画。
    ★ kind：gen = 06_su/contours 的生成件；raw = 01_cad/raw 的原始件。两者同一坐标系，
      前端叠加即可看出生成件哪里偏离了原图。
    ★ 缓存按 (路径, mtime, size)：同一层连点两次不重复解析；文件一变键就变，不会拿旧读数。
    ★ 盲区写在这里：只画 LINE / LWPOLYLINE / POLYLINE / ARC / CIRCLE 与 INSERT 展开一层；
      文字（房间号/面积）不画 —— 「看不见字」不是「图上没有字」。
    """
    if kind not in ("gen", "raw"):
        raise ValueError("kind 只有 gen / raw")
    p = raw_dxf_file(bid, floor) if kind == "raw" else dxf_file(bid, floor)
    st = os.stat(p)
    key = (kind, p, st.st_mtime_ns, st.st_size)
    with _GEOM_LOCK:
        hit = _GEOM_CACHE.get(key)
    if hit is not None:
        return hit

    import ezdxf                                    # 重依赖，按需导入
    doc = ezdxf.readfile(p)

    def aci_hex(c):
        return {1: "#d32f2f", 2: "#f9a825", 3: "#2e7d32", 4: "#00838f", 5: "#1565c0",
                6: "#ad1457", 7: "#444444", 8: "#757575", 9: "#9e9e9e"}.get(c, "#666666")

    try:
        layer_aci = {l.dxf.name: l.dxf.color for l in doc.layers}
    except Exception:
        layer_aci = {}
    layers = {}
    lines = []
    bbox = [None, None, None, None]
    n_pts = 0
    truncated = False

    def add(name, pts):
        nonlocal n_pts, truncated
        if len(pts) < 4:
            return
        if n_pts + len(pts) // 2 > _GEOM_CAP:
            truncated = True
            return
        n_pts += len(pts) // 2
        L = layers.setdefault(name, {"名": name, "条": 0,
                                     "色": aci_hex(layer_aci.get(name, 7))})
        L["条"] += 1
        for i in range(0, len(pts), 2):
            x, y = pts[i], pts[i + 1]
            if bbox[0] is None or x < bbox[0]:
                bbox[0] = x
            if bbox[1] is None or y < bbox[1]:
                bbox[1] = y
            if bbox[2] is None or x > bbox[2]:
                bbox[2] = x
            if bbox[3] is None or y > bbox[3]:
                bbox[3] = y
        lines.append([name] + [round(v, 2) for v in pts])

    def emit(e):
        t = e.dxftype()
        lay = e.dxf.layer
        if t == "LINE":
            s, en = e.dxf.start, e.dxf.end
            add(lay, [s.x, s.y, en.x, en.y])
        elif t in ("LWPOLYLINE", "POLYLINE"):
            # ★★ 2026-10-19 用户「为啥门搞成折线？」——**是这里画的**：
            #   原先按顶点直接连成折线，**丢掉 bulge（组码 42，弧段）** ⇒ 源图里带弧的
            #   门符号在页面上全变成直线弦。源件本身没坏（`raw` 里 bulge 都在）。
            #   改走 ezdxf 自己的 `make_path().flattening(1.0)`：与 ARC/CIRCLE 同一把尺，
            #   弧按真实弧长展开（1 mm 弦高容差）；OCS/closed/宽度段都由它处理。
            from ezdxf.path import make_path
            pts = []
            try:
                for v in make_path(e).flattening(1.0):
                    pts += [v.x, v.y]
            except Exception:                       # 展开不了 ⇒ 退回顶点（弧成弦，但至少不丢线）
                if t == "LWPOLYLINE":
                    for x, y, *_rest in e.get_points():
                        pts += [x, y]
                else:
                    for v in e.vertices:
                        pts += [v.dxf.location.x, v.dxf.location.y]
            add(lay, pts)
        elif t in ("CIRCLE", "ARC"):
            from ezdxf.path import make_path
            pts = []
            for v in make_path(e).flattening(1.0):
                pts += [v.x, v.y]
            add(lay, pts)
        elif t == "INSERT":
            for sub in e.virtual_entities():        # 只展开一层（门/柱块），不递归
                if sub.dxftype() != "INSERT":
                    emit(sub)

    for e in doc.modelspace():
        if truncated:
            break
        try:
            emit(e)
        except Exception:                           # 单个图元画不出不拖垮整层
            continue

    # 绝大多数图层用的是默认色（ACI 7）⇒ 全画成一路深灰，图层开关就分不清。
    # 默认色的层按名字稳定地分一套色板（同一层每次都是同色）；显式配过色的层原样保留。
    palette = ["#1565c0", "#d32f2f", "#2e7d32", "#ad1457", "#f9a825",
               "#00838f", "#6a1b9a", "#ef6c00", "#455a64", "#00897b"]
    dflt = sorted((L for L in layers.values() if L["色"] == aci_hex(7)),
                  key=lambda z: z["名"])
    for i, L in enumerate(dflt):
        L["色"] = palette[i % len(palette)]

    out = {"ok": True, "bid": bid, "floor": floor, "kind": kind, "bbox": bbox,
           "截断": truncated, "点数": n_pts,
           "层": sorted(layers.values(), key=lambda z: -z["条"]),
           "线": lines}
    with _GEOM_LOCK:
        _GEOM_CACHE.clear()                         # 只留最新一层，别把 67 栋都攒在内存里
        _GEOM_CACHE[key] = out
    return out


_CMP_CACHE = {}
_CMP_LOCK = threading.Lock()


def dxf_compare(bid, floor):
    """一层的叠加比对（用户 2026-10-19：「叠加比对后，你要作为判据」）。

    ★ 只调 `overlay_check.compare_floor`，**不在服务端另算一份距离**（铁律 174）。
      闸 J-10.8-04 调的是同一个函数 ⇒ 页面上的数与判据里的数必然同源。
    ★ 缓存键含**两份件**的 (mtime_ns, size)：改任何一份，键就变，不会拿旧读数。
    ★ 件缺 ⇒ `ok=false` + `why`，前端显示「没量到」，不许显示成 0 或 100%。
    """
    p = dxf_file(bid, floor)                       # bid/层名先过白名单
    raw_p = os.path.join(B.root_for(bid), "01_cad", "raw", floor + ".dxf")
    parts = [p]
    if os.path.isfile(raw_p):
        parts.append(raw_p)
    key = tuple((x, os.stat(x).st_mtime_ns, os.stat(x).st_size)
                for x in parts)
    with _CMP_LOCK:
        hit = _CMP_CACHE.get(key)
    if hit is not None:
        return hit
    rec = O.compare_floor(bid, floor, B.root_for(bid))
    with _CMP_LOCK:
        _CMP_CACHE.clear()                         # 只留最新一层
        _CMP_CACHE[key] = rec
    return rec


def dxf_file(bid, floor):
    """一层的 DXF 真源路径 —— bid / 层名都先对索引，再做 realpath 前缀复核。

    ★ 层名来自 URL，绝不能直接拼路径：先拿它去 `contours/index.json` 的**名单**里比对，
      对上了才拼；拼完再 realpath 确认仍在 contours/ 里（防 `..\\` 与盘符写法）。
    """
    if bid not in _profiles():
        raise KeyError("楼栋 %s" % bid)
    cdir = os.path.join(B.root_for(bid), "06_su", "contours")
    idx = _load_or(os.path.join(cdir, "index.json"), []) or []
    names = {str(f.get("floor")) for f in idx if isinstance(f, dict)}
    if floor not in names:
        raise KeyError("这一层不在图纸库里：%s %s" % (bid, floor))
    p = os.path.realpath(os.path.join(cdir, floor + ".dxf"))
    base = os.path.realpath(cdir)
    if not (p == base or p.startswith(base + os.sep)) or not os.path.isfile(p):
        raise KeyError("这层的 DXF 不在：%s %s" % (bid, floor))
    return p


# ---------------------------------------------------------------- 照片比对
# ★ 2026-10-19 用户令：「你把这对别（比对）也写到 8150，不对就可以随时指出」。
#   读数**只从 compare_photo.py 落的件里读**（rebuild/_work/photo_<栋>[_rotNNN].json），
#   页面不自己算一遍 —— 两处算同一个数，一致证明不了它对（铁律 018）。
#   「重跑」是后台起同一个脚本；跑完页面刷新就是新件，不缓存。
PHOTO_WORK = os.path.join(CDUT, "rebuild", "_work")
PHOTO_TOOL = os.path.join(TOOLS, "compare_photo.py")
PHOTO_RE = re.compile(r"^photo_([A-Za-z0-9_]+?)(?:_rot(\d{1,3}))?\.json$")
PHOTO_WHAT = ("map", "zoom")


def _photo_files():
    """盘上已有的比对件 → {bid: [{rot, file, path, mtime}...]}，新的在前。"""
    out = {}
    if not os.path.isdir(PHOTO_WORK):
        return out
    for fn in os.listdir(PHOTO_WORK):
        m = PHOTO_RE.match(fn)
        if not m:
            continue
        p = os.path.join(PHOTO_WORK, fn)
        if not os.path.isfile(p):
            continue
        out.setdefault(m.group(1), []).append(
            {"rot": int(m.group(2)) if m.group(2) else None, "file": fn, "path": p,
             "mtime": _mtime(p)})
    for v in out.values():
        v.sort(key=lambda x: x["mtime"] or "", reverse=True)
    return out


def _photo_png(bid, rot, what):
    """图片文件名由 bid/rot/what **算出来**，绝不接 URL 里的路径（同 dxf_file 的口径）。"""
    if what not in PHOTO_WHAT:
        raise KeyError("图只有 %s" % "/".join(PHOTO_WHAT))
    if not BID_RE.match(bid or ""):
        raise KeyError("楼栋 %r" % (bid,))
    name = "photo_%s%s_%s.png" % (bid, "" if rot is None else "_rot%03d" % int(rot), what)
    p = _safe_join(PHOTO_WORK, name)
    if p is None or not os.path.isfile(p):
        raise KeyError("%s 没有这张图" % name)
    return p


def photo_index():
    """哪些栋有比对件。**没件的栋也列出来** —— 页面要有「跑一次」的入口。"""
    files = _photo_files()
    prof = _profiles()
    rows = []
    for bid in sorted(set(files) | set(prof)):
        fs = files.get(bid) or []
        rows.append({"bid": bid, "title": (prof.get(bid) or {}).get("title") or "",
                     "有": bool(fs),
                     "件": [{"rot": f["rot"], "file": f["file"], "mtime": f["mtime"]}
                            for f in fs]})
    return {"ok": True, "工作目录": PHOTO_WORK, "行": rows,
            "有件的栋": sum(1 for r in rows if r["有"]), "总栋": len(rows)}


def photo(bid, rot=None):
    if not BID_RE.match(bid or "") or bid not in _profiles():
        raise ValueError("楼栋不存在：%r" % (bid,))
    if rot not in (None, ""):
        try:
            rot = int(float(rot))
        except (TypeError, ValueError):
            raise ValueError("rot 必须是整数")
        if not 0 <= rot <= 359:
            raise ValueError("rot 取 0~359")
    else:
        rot = None
    files = _photo_files().get(bid) or []
    if rot is not None:
        files = [f for f in files if f["rot"] == rot]
    if not files:
        return {"ok": True, "bid": bid, "有": False,
                "说明": "盘上还没有这栋%s的比对件 —— 点「跑一次」生成（约 20 s）"
                        % (" rot %d°" % rot if rot is not None else "")}
    f = files[0]
    try:
        d = _load(f["path"])
    except (OSError, ValueError) as e:
        return {"ok": True, "bid": bid, "有": False, "说明": "件读不成：%s" % e}
    # 绝对路径不出网（DSM 路径是本机目录）；图改成服务端算出来的 URL
    d.pop("dsm", None)
    d.pop("dom", None)
    d["热点图"] = None
    d["热点放大图"] = None
    d["_件"] = {"file": f["file"], "rot": f["rot"], "mtime": f["mtime"]}
    d["_图"] = {}
    for w in PHOTO_WHAT:
        try:
            _photo_png(bid, f["rot"], w)
        except KeyError:
            d["_图"][w] = None
            continue
        d["_图"][w] = ("/api/photo/img?bid=%s%s&what=%s"
                       % (bid, "" if f["rot"] is None else "&rot=%d" % f["rot"], w))
    d["_其它"] = [{"rot": x["rot"], "file": x["file"]} for x in files[1:4]]
    # ★ 成功路径也要显式给「有」：前端按它分「读数」与「还没跑」两条路（没这个键=假）。
    d["有"] = True
    d["ok"] = True
    return d


def start_photo(payload):
    """后台起 compare_photo.py。**与 start_run 同一套 JOB_STATE**，但 id 前缀不同。

    故意不合并成同一个函数：链的任务和量具的任务「跑完该看什么」不同，
    硬合会把 start_run 的主语悄悄换掉（铁律 196）。
    """
    bid = payload.get("bid")
    if not bid or not BID_RE.match(bid) or bid not in _profiles():
        raise ValueError("楼栋不存在：%r" % (bid,))
    rot = payload.get("rot")
    if rot in (None, ""):
        rot = None
    else:
        try:
            rot = int(float(rot))
        except (TypeError, ValueError):
            raise ValueError("rot 必须是整数")
        if not 0 <= rot <= 359:
            raise ValueError("rot 取 0~359")
    busy = [j for j, s in JOB_STATE.items()
            if s.get("kind") == "photo" and s["status"] == "running"]
    if busy:
        raise ValueError("已经有一次比对在跑：%s" % busy[0])
    cmd = [sys.executable, "-X", "utf8", "-I", PHOTO_TOOL, "--bid", bid]
    if rot is not None:
        cmd += ["--rot", str(rot)]
    os.makedirs(JOBS, exist_ok=True)
    with JOBS_LOCK:
        JOB_N[0] += 1
        jid = "photo-%03d" % JOB_N[0]
        log = os.path.join(JOBS, jid + ".log")
        fh = open(log, "wb")
        p = subprocess.Popen(cmd, cwd=CDUT, stdout=fh, stderr=subprocess.STDOUT,
                             env=dict(os.environ))
        JOB_STATE[jid] = {"id": jid, "kind": "photo", "bid": bid, "from": "照片比对",
                          "rot": rot, "pid": p.pid, "log": log,
                          "started": datetime.datetime.now().isoformat(timespec="seconds"),
                          "status": "running", "rc": None, "cmd": cmd,
                          "_p": p, "_fh": fh}

    def _watch():
        rc = p.wait()
        fh.close()
        s = JOB_STATE.get(jid) or {}
        s["status"] = "ok" if rc == 0 else "fail"
        s["rc"] = rc
        s["ended"] = datetime.datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=_watch, daemon=True).start()
    return {"ok": True, "job": jid, "cmd": " ".join(cmd), "log": log, "rot": rot}


def _steps(bid):
    """链的步骤与「跑完必须存在的件」——**从 run_chain_bid 取，不在这里抄第二份**。"""
    import run_chain_bid as RC
    root = B.root_for(bid)
    out = []
    for name, _cmd, need in RC._steps(bid, root):
        x = _piece(need)
        x.update({"name": name, "ok": x["exists"]})
        out.append(x)
    return out


def _pack(bid):
    pdir = os.path.join(PACKS, bid)
    mp = os.path.join(pdir, "manifest.json")
    if not os.path.exists(mp):
        return {"exists": False, "dir": pdir}
    m = _load(mp)
    arts = m.get("artifacts") or []
    tot = sum(a.get("bytes") or 0 for a in arts)
    newest = None
    for a in arts:
        p = os.path.join(pdir, a.get("path") or "")
        t = _mtime(p)
        if t and (newest is None or t > newest):
            newest = t
    # ★ 2026-10-19：「包过期」要比的是**源件**，不是包里的副本。副本的 mtime 是复制时刻，
    #   与 created_at 差一两秒 ⇒ 刚装完的包被判过期（实测 67 栋误报 20 栋）。
    #   真问题只有一个：源件在包生成**之后**又变过（+60 s 容差，抵掉复制耗时）。
    root = B.root_for(bid)
    name = _out_name(bid)
    srcs = [os.path.join(root, "05_build", "build.json"),
            os.path.join(root, "06_su", "contours", "index.json"),
            os.path.join(root, "06_su", name + "_catalog.json"),
            os.path.join(root, "06_su", name + "_fc.obj")]
    newest_src = None
    for p in srcs:
        t = _mtime(p)
        if t and (newest_src is None or t > newest_src):
            newest_src = t
    stale = False
    if m.get("created_at") and newest_src:
        try:
            made = datetime.datetime.fromisoformat(m["created_at"]).replace(tzinfo=None)
            src = datetime.datetime.fromisoformat(newest_src)
            stale = (src - made).total_seconds() > 60
        except ValueError:
            stale = False
    return {"exists": True, "dir": pdir, "created_at": m.get("created_at"),
            "package_sha256": m.get("package_sha256"), "n_artifacts": len(arts),
            "bytes": tot, "newest_artifact": newest, "newest_source": newest_src,
            "stale": stale,
            "schema": m.get("schema"), "lod": (m.get("lod") or {}).get("level")}


def _why(vg, limit=3, cut=120):
    """把这条判据「为什么红」翻成人话：直接给 items 里的原句（带实测数与阈值）。

    ★ 2026-10-19 用户原话：「很多是红色的叉叉，但不知道具体原因」——
      总览矩阵原来只带 pass/条数，红格点开才知道原因。这里把 fail/unmeasured 的
      `text`（本身已是「哪一层哪一件 / 实测多少 / 阈值多少」）截断后带上，
      矩阵里每格直接印第一句，其余进悬浮。
    """
    fails, un = [], []
    for it in vg.get("items") or []:
        st = it.get("status")
        t = (it.get("text") or "").strip()
        if not t:
            continue
        t = t.replace("**", "").replace("`", "")
        if len(t) > cut:
            t = t[:cut].rstrip() + "…"
        if st == "fail":
            fails.append(t)
        elif st == "unmeasured":
            un.append(t)
    return (fails + un)[:limit]


def _verdicts(bid):
    out = {}
    for g in GATES:
        p = os.path.join(GOUT, "%s.%s.json" % (g, bid))
        if not os.path.exists(p):
            out[g] = {"pass": None, "missing": True,
                      "note": "没跑过（或闸没落 verdict）", "items": [], "counts": {}}
            continue
        v = _load(p)
        v["missing"] = False
        out[g] = v
    return out


def overview():
    prof = _profiles()
    bids = sorted(prof)
    rows = []
    fc = {k: {"栋": set(), "条": 0} for k in FIX + ("待判",)}
    for b in bids:
        v = _verdicts(b)
        red = sum(int((v[g].get("counts") or {}).get("red") or 0) for g in GATES)
        un = sum(int((v[g].get("counts") or {}).get("unmeasured") or 0) for g in GATES)
        for g in GATES:
            for it in v[g].get("items") or []:
                if it.get("status") != "fail":
                    continue
                d = it.get("fix") or "待判"
                slot = fc.setdefault(d, {"栋": set(), "条": 0})
                slot["栋"].add(b)
                slot["条"] += 1
        rows.append({
            "bid": b, "title": prof[b].get("title") or "",
            # ★ 缺 floor_names ≠ 0 层：那栋的层表是运行时从标题栏现读的（building.floor_names），
            #   这里不为了填表去开 67 份 DXF（慢且又一次估计）⇒ 诚实留 None，页面显示「—」。
            "floors": len(prof[b]["floor_names"]) if prof[b].get("floor_names") else None,
            "basement": prof[b].get("basement"),
            "pack": _pack(b),
            "gates": {g: {"pass": v[g].get("pass"),
                          "red": (v[g].get("counts") or {}).get("red"),
                          "unmeasured": (v[g].get("counts") or {}).get("unmeasured"),
                          "missing": v[g].get("missing"),
                          "measured_at": v[g].get("measured_at"),
                          "note": v[g].get("note"),
                          "why": _why(v[g])} for g in GATES},
            "red": red, "unmeasured": un,
        })
    # 跨楼汇总：哪个方向涉及多少栋 / 多少条 —— 页面用它排「先修哪一类」
    fix_counts = [{"方向": k, "栋": len(fc[k]["栋"]), "条": fc[k]["条"]}
                  for k in FIX + ("待判",) if fc.get(k) and fc[k]["条"]]
    fix_counts.sort(key=lambda x: (-x["栋"], -x["条"]))   # 先修涉及面最大的
    return {"schema": "cdut3d-workbench-overview/1",
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "gates": list(GATES), "gate_info": GATE_INFO,
            "fix": list(FIX), "fix_info": FIX_INFO, "fix_counts": fix_counts,
            "bids": rows}


def building(bid):
    prof = _profiles()
    if bid not in prof:
        raise KeyError(bid)
    root = B.root_for(bid)
    return {"schema": "cdut3d-workbench-building/1",
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "bid": bid, "title": prof[bid].get("title") or "",
            "profile": prof[bid],
            "root": root, "out_name": B.out_name(bid),
            "floors": B.floor_names(bid),
            "steps": _steps(bid), "pack": _pack(bid),
            "verdicts": _verdicts(bid), "gate_info": GATE_INFO, "fix_info": FIX_INFO,
            "params": _load(PARAM_JSON),
            "impact": IMPACT}


# ---------------------------------------------------------------- 写盘（校验 → 备份 → 原子 → 回读）
def _backup(path):
    os.makedirs(BACKUP, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACKUP, "%s.%s.bak" % (os.path.basename(path), ts))
    shutil.copy2(path, dst)
    return dst


_WS = " \t\r\n"


def _skip(t, i):
    while i < len(t) and t[i] in _WS:
        i += 1
    return i


def _str_end(t, i):
    """`t[i]` 是引号；返回 (解码后的键, 收尾后的下标)。"""
    j = i + 1
    while j < len(t):
        c = t[j]
        if c == "\\":
            j += 2
            continue
        if c == '"':
            return json.loads(t[i:j + 1]), j + 1
        j += 1
    raise ValueError("字符串没闭合")


def _val_end(t, i):
    """一个值的结束下标（只认边界，不解释语义）。"""
    i = _skip(t, i)
    c = t[i]
    if c == '"':
        return _str_end(t, i)[1]
    if c in "{[":
        depth, j = 0, i
        while j < len(t):
            ch = t[j]
            if ch == '"':
                _, j = _str_end(t, j)
                continue
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        raise ValueError("括号没闭合")
    j = i
    while j < len(t) and t[j] not in ",]}\r\n\t ":
        j += 1
    return j


def _span(t, i, keys):
    """`keys` 指向的值在原文里的 [起, 止)。同键重复时取**最后一个**（与 json.loads 一致）。"""
    i = _skip(t, i)
    if not keys:
        return i, _val_end(t, i)
    k = keys[0]
    if t[i] == "{" and isinstance(k, str):
        hit = None
        i = _skip(t, i + 1)
        while t[i] != "}":
            key, i = _str_end(t, i)
            i = _skip(t, i)
            if t[i] != ":":
                raise ValueError("缺冒号")
            i += 1
            if key == k:
                hit = _span(t, i, keys[1:])
            i = _skip(t, _val_end(t, i))
            if t[i] == ",":
                i = _skip(t, i + 1)
        if hit is None:
            raise KeyError(k)
        return hit
    if t[i] == "[" and isinstance(k, int):
        n = 0
        i = _skip(t, i + 1)
        while t[i] != "]":
            if n == k:
                return _span(t, i, keys[1:])
            i = _skip(t, _val_end(t, i))
            if t[i] == ",":
                i = _skip(t, i + 1)
            n += 1
        raise KeyError(k)
    raise KeyError(k)


def _write_json(path, obj, keys):
    """**只替换 `keys` 指向的那一个值**，其余字节原样保留。

    ★ 2026-10-19 实测：整份 `indent=1` 重排会毁掉真源格式 —— 参数.json 是 CRLF、
      楼栋.json 的数组是同行紧凑写的；同值保存一次就把 646 行整份改写（铁律 079
      的另一半：字节层写盘还不够，**格式也得是原来的**）。
    ★ 临时件 + 回读比对 + 备份 + os.replace 照旧（铁律 187）。
    """
    raw = open(path, "rb").read()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = raw[len(bom):].decode("utf-8")
    s, e = _span(text, 0, keys)
    v = obj
    for k in keys:
        v = v[k]
    # 原文这个值是**跨行**写的（如 区间 = 三行数组）⇒ 新值也得跨行，且续行缩进
    # 要跟原文同一列（参数.json 是 1 空格/层）。原文就是同行的 ⇒ 紧凑写。
    old = text[s:e]
    if "\n" in old:
        ls = text.rfind("\n", 0, s) + 1
        base = text[ls:s]
        base = base[:len(base) - len(base.lstrip(" \t"))]
        nl = "\r\n" if "\r\n" in text else "\n"   # 参数.json 是 CRLF，别混进去
        tok = json.dumps(v, ensure_ascii=False, indent=1)
        tok = tok.replace("\n", nl + base)
    else:
        tok = json.dumps(v, ensure_ascii=False)
    out = bom + (text[:s] + tok + text[e:]).encode("utf-8")
    tmp = path + ".tmp-workbench"
    with open(tmp, "wb") as f:
        f.write(out)
    got = json.loads(open(tmp, "rb").read()[len(bom):].decode("utf-8"))
    if got != obj:
        os.unlink(tmp)
        raise ValueError("回读不一致：写盘被什么改过")
    bak = _backup(path)
    os.replace(tmp, path)
    return bak


def save_param(payload):
    bld, name, field = payload.get("构件"), payload.get("参数"), payload.get("字段")
    val = payload.get("值")
    root = _load(PARAM_JSON)
    node = (root.get("构件") or {})
    if bld not in node or name not in node[bld]:
        raise ValueError("参数不存在：%s/%s" % (bld, name))
    leaf = node[bld][name]
    if field not in ("值", "标注", "出处", "作用", "区间", "单位"):
        raise ValueError("字段只能改 值/标注/出处/作用/区间/单位")
    warns = []
    if field == "值":
        if not isinstance(val, (int, float, str, bool)):
            raise ValueError("值的类型不对")
        rng = leaf.get("区间")
        if isinstance(val, (int, float)) and not isinstance(val, bool) and \
                isinstance(rng, list) and len(rng) == 2:
            if not (rng[0] <= val <= rng[1]):
                raise ValueError("超出档案区间 %s：%s" % (rng, val))
            span = (rng[1] - rng[0]) or 1
            if abs(val - rng[0]) < span * 0.02 or abs(val - rng[1]) < span * 0.02:
                warns.append("贴着区间端点（%s）—— 改之前先确认出处那一句还成立" % rng)
        if leaf.get("标注") == "实测":
            warns.append("这个值标的是「实测」；手改后请把「标注」改成「假设」，否则依据与值打架")
    elif field == "标注":
        if val not in ("实测", "假设", "规范", "旧规范", "待坐实"):
            raise ValueError("标注只能是 实测/假设/规范/旧规范/待坐实")
    elif field == "区间":
        if not (isinstance(val, list) and len(val) == 2 and all(isinstance(x, (int, float)) for x in val)):
            raise ValueError("区间必须是两个数")
        cur = leaf.get("值")
        if isinstance(cur, (int, float)) and not isinstance(cur, bool) and not (val[0] <= cur <= val[1]):
            warns.append("当前值 %s 不在新区间里 —— 这会让新的约束当场不成立" % cur)
    elif field == "单位":
        if not isinstance(val, str) or not val.strip():
            raise ValueError("单位必须是非空字符串")
    else:
        if not isinstance(val, str):
            raise ValueError("%s 必须是字符串" % field)
    old = leaf.get(field)
    leaf[field] = val
    bak = _write_json(PARAM_JSON, root, ["构件", bld, name, field])
    return {"ok": True, "old": old, "new": val, "backup": bak, "warnings": warns,
            "impact": ["参数是全校共用的：改后**所有楼栋**都要重跑"
                       "（至少 建件→轮廓→FreeCAD→GLB→逐块清单→装包）"],
            "rerun": "python -X utf8 -I rebuild/tools/run_batch.py --from 建件 <bids>"}


def save_profile(payload):
    bid = payload.get("bid")
    field = payload.get("字段") or ""
    val = payload.get("值")
    if not bid or not BID_RE.match(bid) or bid not in _profiles():
        raise ValueError("楼栋不存在：%r" % (bid,))
    root = _load(PROFILE_JSON)
    p = root[bid]
    keys = [x for x in field.split(".") if x]
    if not keys or keys[0] not in p:
        raise ValueError("字段不存在：%s" % field)
    node = p
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict) or k not in node:
            raise ValueError("字段路径不通：%s" % field)
        node = node[k]
    cur = node[keys[-1]]
    if type(cur) is not type(val) and not (isinstance(cur, (int, float)) and isinstance(val, (int, float))):
        raise ValueError("类型不对：原 %s，给 %s" % (type(cur).__name__, type(val).__name__))
    if keys[-1] in ("floor_names", "keep_layers", "drop_layers"):
        if not isinstance(val, list) or not all(isinstance(x, str) and x.strip() for x in val):
            raise ValueError("%s 必须是非空字符串数组" % keys[-1])
    old = cur
    node[keys[-1]] = val
    bak = _write_json(PROFILE_JSON, root, [bid] + keys)
    step0 = (IMPACT.get(keys[0]) or ["建件"])[0]
    return {"ok": True, "old": old, "new": val, "backup": bak,
            "impact": IMPACT.get(keys[0]) or ["建件"],
            "rerun": "python -X utf8 -I rebuild/tools/run_chain_bid.py %s --from %s"
                     % (bid, step0)}


# ---------------------------------------------------------------- 跑链（后台）
JOBS_LOCK = threading.Lock()
JOB_STATE = {}
JOB_N = [0]


def start_run(payload):
    bid = payload.get("bid")
    step = payload.get("from") or "切图幅"
    if not bid or not BID_RE.match(bid) or bid not in _profiles():
        raise ValueError("楼栋不存在：%r" % (bid,))
    running = [j for j, s in JOB_STATE.items() if s["bid"] == bid and s["status"] == "running"]
    if running:
        raise ValueError("这栋已经在跑：%s" % running[0])
    if len([s for s in JOB_STATE.values() if s["status"] == "running"]) >= 2:
        raise ValueError("同时最多跑 2 栋（FreeCAD 暂存区按楼栋分开，但 CPU 只有一颗）")
    os.makedirs(JOBS, exist_ok=True)
    with JOBS_LOCK:
        JOB_N[0] += 1
        jid = "%s-%03d" % (bid, JOB_N[0])
        log = os.path.join(JOBS, jid + ".log")
        cmd = [sys.executable, "-X", "utf8", "-I",
               os.path.join(TOOLS, "run_chain_bid.py"), bid, "--from", step]
        fh = open(log, "wb")
        p = subprocess.Popen(cmd, cwd=CDUT, stdout=fh, stderr=subprocess.STDOUT,
                             env=dict(os.environ))
        JOB_STATE[jid] = {"id": jid, "bid": bid, "from": step, "pid": p.pid,
                          "log": log, "started": datetime.datetime.now().isoformat(timespec="seconds"),
                          "status": "running", "rc": None, "cmd": cmd,
                          "_p": p, "_fh": fh}

    def _watch():
        rc = p.wait()
        fh.close()
        s = JOB_STATE.get(jid) or {}
        s["status"] = "ok" if rc == 0 else "fail"
        s["rc"] = rc
        s["ended"] = datetime.datetime.now().isoformat(timespec="seconds")

    threading.Thread(target=_watch, daemon=True).start()
    return {"ok": True, "job": jid, "cmd": " ".join(cmd), "log": log}


def job_info(jid, tail=200):
    s = JOB_STATE.get(jid)
    if not s:
        # ★ jid 的**整段**都要限制（原来只查 `split("-")[0]`，后半截可以带 `..\\..\\`）。
        if not JOB_ID_RE.match(jid or ""):
            raise KeyError(jid)
        p = os.path.join(JOBS, jid + ".log")
        if not os.path.exists(p):
            raise KeyError(jid)
        s = {"id": jid, "status": "unknown", "log": p}
    lines = []
    if os.path.exists(s.get("log") or ""):
        with open(s["log"], encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-int(tail):]
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    out["tail"] = "".join(lines)
    return out


# ---------------------------------------------------------------- 判据科普页
# ★ 2026-10-20 用户令：「判据太多、太复杂、看不懂，做成科普，旁边配图解释为什么用这个判据」。
#   这里把 18 个检测器**并成 8 组问句**（每组回答一个人会问的问题），页面每张卡一个 SVG 图。
#   ★ 归组只改「怎么讲」，不改「怎么量」：每组的红/黄数仍逐条来自 `gates/_out/defects.<bid>.json`，
#     页面不许手打数（铁律 174）。
CRITERIA = [
    {"k": "对图", "问答": "图上画了的，件里都有吗？",
     "为什么": "模型是照图纸建的：图上没有的墙不许自己长出来，图上有墙的地方不许空着；"
              "图上画了柱、门、梯，件里也不能是 0。",
     "怎么量": "把件里的墙线叠回原图，量「原图被盖住的比例」（覆盖）和「件贴在原图上的比例」（贴源）；"
              "没盖住的点按原因分成四类只算一次：1 m 内什么都没有=**漏墙**、"
              "300 mm~1 m=**偏了**、成排等距等长线=**台阶（不是墙）**、贴着门扇=**门洞边（不是墙）**；"
              "生成件上离源线 >300 mm 的点=**多墙**。"
              "再逐类数件里的构件，为 0 时回源图确认那一类到底画没画（画了=漏认，没画=图的事实）。",
     "ids": ["D-19", "D-20", "D-21", "D-22", "D-23", "D-02", "D-05", "D-06", "D-11"]},
    {"k": "门", "问答": "每扇门都开在墙上吗？",
     "为什么": "门是墙上的一个洞：门扇要贴着墙、洞口要打穿墙，门头墙要沿同一道墙铺过去。",
     "怎么量": "门扇到墙/柱/梯/过梁的距离；门洞与墙带的交；门头墙是否沿门所在那道墙。",
     "ids": ["D-04", "D-01", "D-03", "D-16"]},
    {"k": "楼梯", "问答": "楼梯是楼梯，不是一堵墙吗？",
     "为什么": "踏步是一级一级的台阶，不是墙；梯段上行方向也不能画反。",
     "怎么量": "踏步线不许进 WALL 层；梯段方向与源图箭头/标高比对。",
     "ids": ["D-14"]},
    {"k": "楼板屋顶", "问答": "每个房间头顶都有楼板或屋顶吗？",
     "为什么": "房间不能露天；挑空该开的地方要开，不该开的地方不能是整块板。",
     "怎么量": "每层 SLAB∪ROOF 盖住该层房间并集的比例；挑空区与源图空洞比对。",
     "ids": ["D-09", "D-15", "D-10"]},
    {"k": "接缝", "问答": "墙和墙接上了吗？层和层对齐了吗？",
     "为什么": "外墙不闭合会漏风漏光，层号错位会让整层房间挂到隔壁层。",
     "怎么量": "墙带外环闭合检查；房间面与层号对账。",
     "ids": ["D-07", "D-08"]},
    {"k": "新鲜度", "问答": "我看的是刚生成的那一版吗？",
     "为什么": "工具或图纸改过、件没重跑，读数就是在看旧件——所有别的判据同时失效。",
     "怎么量": "建件/轮廓/GLB 的时刻必须新于工具与源图。",
     "ids": ["D-12"]},
    {"k": "实景", "问答": "和航拍照片对得上吗？",
     "为什么": "图纸可能错、可能旧；2024 年航拍是唯一独立的外部证据。",
     "怎么量": "件在照片坐标系里的位置/高度与楼体轮廓比对；没有锚点就写「没量到」。",
     "ids": ["D-18"]},
    {"k": "参数", "问答": "这些数有真值，还是假设？",
     "为什么": "墙厚、门高这类数是假设值时，不能说「件错了」，只能说「没有证据」。",
     "怎么量": "每个参数带标注（实测/规范/假设/待坐实）；假设值只出提示，不出红。",
     "ids": ["D-13"]},
]


def _unmeasured(item):
    """这一条到底量没量到？

    ★ 2026-10-20 改：原先只认 `未量到` 开头，把 `检测器缺：door_skin`（D-03）与
      `需人看 / 需影像`（D-05 / D-14）都算成「量了且 0 条」——楼梯卡因此印「已量·全绿」，
      而 D-14 一次都没量过（铁律 158/199：没量到不许长成绿）。
      `闸 …：pass` 算量到了（闸跑过且过）。
    """
    st = str(item.get("状态") or "")
    return st.startswith("未量到") or st.startswith("检测器缺") or "需人看" in st


def criteria_summary():
    """逐组现算读数：扫 `gates/_out/defects.<bid>.json`，按组汇总红/黄/提示/未量栋次。"""
    per = {}
    packs = 0
    have = set()
    # 有包但没档案的栋必须点名：没量到 ≠ 全绿（铁律 199）。
    packdir = os.path.join(CDUT, "packs", "cdut-main")
    total = sum(1 for b in os.listdir(packdir)
                if os.path.isdir(os.path.join(packdir, b))) if os.path.isdir(packdir) else 0
    for fn in sorted(os.listdir(GOUT)) if os.path.isdir(GOUT) else []:
        if not (fn.startswith("defects.") and fn.endswith(".json")):
            continue
        try:
            with open(os.path.join(GOUT, fn), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:                                     # noqa: BLE001
            continue
        packs += 1
        have.add(fn[len("defects."):-len(".json")])
        for item in d.get("条") or []:
            t = per.setdefault(item.get("id"), {"红": 0, "黄": 0, "提示": 0, "未量": 0, "例": []})
            for x in item.get("findings") or []:
                lv = x.get("级别")
                if lv in ("红", "黄", "提示"):
                    t[lv] += 1
                    if lv != "提示" and len(t["例"]) < 2:
                        t["例"].append("%s %s：%s" % (item.get("id"), x.get("层"),
                                                      str(x.get("读数") or "")[:60]))
            if _unmeasured(item):
                t["未量"] += 1
    out = []
    for c in CRITERIA:
        row = {"k": c["k"], "问答": c["问答"], "为什么": c["为什么"], "怎么量": c["怎么量"],
               "ids": c["ids"], "红": 0, "黄": 0, "提示": 0, "未量": 0, "例": [],
               "未量条": [], "按条": []}
        for i in c["ids"]:
            t = per.get(i)
            if not t:
                row["未量条"].append(i)
                continue
            for key in ("红", "黄", "提示", "未量", "例"):
                if key == "例":
                    row[key] += t[key][:1]
                else:
                    row[key] += t[key]
            if t["未量"]:
                row["未量条"].append(i)
            if t["红"] or t["黄"] or t["提示"]:
                # ★ 一条检测器吞掉整组的读数时必须点名：240 条黄全来自 D-11，
                #   那不是 240 个错误，是**一把该重审的尺子**（用户问「判据有没有必要」）。
                row["按条"].append({"id": i, "红": t["红"], "黄": t["黄"], "提示": t["提示"]})
        row["按条"].sort(key=lambda x: -(x["红"] * 1000 + x["黄"]))
        out.append(row)
    missing = sorted(b for b in os.listdir(packdir)
                     if os.path.isdir(os.path.join(packdir, b)) and b not in have) \
        if os.path.isdir(packdir) else []
    # ★ 检测器条数现读目录，不手打（2026-10-20 D-17 拆成 5 条后 18 → 22，页面上的数跟着变）
    try:
        with open(os.path.join(CDUT, "rebuild", "构件库", "缺陷库.json"), encoding="utf-8") as f:
            _cat = json.load(f).get("条") or []
        n_cat = len(_cat)
        # ★ 编号旁边印人话：用户 2026-10-20「判据晦涩，别人看不懂」。
        #   页面上的「D-19 红3」换成「D-19 漏墙（源图有墙，件里 1 m 内没有）红3」。
        names = {e["id"]: e.get("名") or "" for e in _cat}
    except Exception:                                     # noqa: BLE001
        n_cat, names = None, {}
    # ★ 判据病历：每条改过几次、最近一次错在哪、有没有反例。页面直接印，
    #   让「这条判据凭什么可信」有据可查（用户 2026-10-20「判据出问题以后有没有再修改」）。
    ledger = {}
    try:
        with open(os.path.join(CDUT, "rebuild", "构件库", "判据账本.json"), encoding="utf-8") as f:
            for k, v in (json.load(f).get("条") or {}).items():
                rev = v.get("修订") or []
                ledger[k] = {
                    "改过": len(rev),
                    "最近": ("%s：%s" % (rev[-1].get("日期"), rev[-1].get("错在哪"))) if rev else "",
                    "反例": len(v.get("反例") or []),
                    "量具": bool(v.get("量具")),
                    "现状": v.get("现状") or "",
                }
    except Exception:                                     # noqa: BLE001
        ledger = {}
    for row in out:
        row["账本"] = {i: ledger[i] for i in row["ids"] if i in ledger}
        for a in row["按条"]:
            a["名"] = names.get(a["id"], "")
    return {"packs": packs, "总包": total, "无档案": missing, "组": out,
            "条数": n_cat, "账本": ledger, "名典": names}


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "cdut3d-workbench/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):      # 安静：只留错误
        code = str(a[1]) if len(a) > 1 else ""
        if code.isdigit() and int(code) >= 400:
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))

    def _json(self, obj, code=200, extra_headers=None):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for key, value in (extra_headers or []):
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _err(self, code, msg):
        self._json({"ok": False, "error": msg}, code)

    def _same_origin(self):
        return _allowed_origin(self.headers.get("Origin"), self.headers.get("Host") or "")

    def _cookies(self):
        out = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k] = v
        return out

    def _session_user(self):
        return auth_check_token(self._cookies().get(AUTH_COOKIE, ""))

    def _authed(self):
        return bool(self._session_user())

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _session_cookie(self, username):
        token = auth_issue_token(username)
        secure = (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (
            AUTH_COOKIE, token, AUTH_TTL_S, "; Secure" if secure else "")

    def _clear_cookie(self):
        return "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % AUTH_COOKIE

    def _client_ip(self):
        forwarded = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return forwarded or (self.client_address[0] if self.client_address else "?")

    def _login_allowed(self):
        now = time.time()
        ip = self._client_ip()
        with _AUTH_LOCK:
            cutoff = now - AUTH_LOGIN_WINDOW_S
            bucket = [t for t in _AUTH_ATTEMPTS.get(ip, []) if t >= cutoff]
            _AUTH_ATTEMPTS[ip] = bucket
            return len(bucket) < AUTH_LOGIN_MAX

    def _login_failed(self):
        with _AUTH_LOCK:
            _AUTH_ATTEMPTS.setdefault(self._client_ip(), []).append(time.time())

    def _login_succeeded(self):
        with _AUTH_LOCK:
            _AUTH_ATTEMPTS.pop(self._client_ip(), None)

    def _body(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("POST 只收 application/json")
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 2 * 1024 * 1024:
            raise ValueError("请求体大小不对")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _raw(self, limit=200 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            raise ValueError("上传件大小不对（%d 字节）" % n)
        return self.rfile.read(n)

    def do_GET(self):
        try:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/live":
                return self._json({"ok": True, "service": "cdut3d", "version": APP_VERSION})
            if u.path == "/health":
                payload = health_payload()
                return self._json(payload, 200 if payload["ok"] else 503)
            if u.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return

            public = {
                "/login", "/login/", "/login.html", "/login.css", "/login.js",
                "/assets/logo.svg", "/assets/campus-hero.webp",
            }
            if u.path in ("/login", "/login/", "/login.html"):
                if self._authed():
                    return self._redirect("/")
                return self._page(os.path.join(UI, "login.html"))
            if u.path in public:
                return self._static(u.path)
            if not self._authed():
                if u.path.startswith("/api/"):
                    return self._err(401, "请先登录")
                return self._redirect("/login?next=" + quote(self.path, safe=""))

            if u.path in ("/info", "/info/"):
                return self._page(os.path.join(UI, "space.html"))

            if VIEWER_MODE:
                allowed = (u.path in ("/", "/viewer", "/viewer/")
                           or u.path.startswith("/demo/")
                           or u.path.startswith("/packs/")
                           or u.path.startswith("/reality/")
                           or u.path.startswith("/assets/")
                           or u.path in ("/space.css", "/space.js", "/building-status.json"))
                if not allowed:
                    return self._err(404, "服务器只提供三维模型浏览")
                if u.path in ("/", "/viewer", "/viewer/"):
                    return self._page(os.path.join(UI, "viewer.html"))

            if u.path == "/api/overview":
                return self._json(overview())
            if u.path == "/api/building":
                return self._json(building(q.get("bid") or ""))
            if u.path == "/api/params":
                return self._json(_load(PARAM_JSON))
            if u.path == "/api/job":
                return self._json(job_info(q.get("id") or "", q.get("tail") or 200))
            if u.path == "/api/flow":
                return self._json(flow())
            if u.path == "/api/library":
                return self._json(library(q.get("what") or "draw"))
            if u.path == "/api/dxf/geom":
                return self._json(dxf_geom(q.get("bid") or "", q.get("floor") or "",
                                           q.get("kind") or "gen"))
            if u.path == "/api/dxf/compare":
                return self._json(dxf_compare(q.get("bid") or "", q.get("floor") or ""))
            if u.path == "/api/photo":
                if q.get("bid"):
                    return self._json(photo(q.get("bid") or "", q.get("rot")))
                return self._json(photo_index())
            if u.path == "/api/photo/img":
                p = _photo_png(q.get("bid") or "", q.get("rot"), q.get("what") or "")
                b = open(p, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            if u.path == "/api/dxf":
                p = dxf_file(q.get("bid") or "", q.get("floor") or "")
                b = open(p, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/dxf")
                # 文件名带中文（3层.dxf）⇒ RFC 5987 的 filename*，别用裸 filename=。
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''%s"
                                 % quote(os.path.basename(p), safe=""))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            if u.path.startswith("/quick/"):
                return self._mount(QUICK, u.path[len("/quick/"):])
            # ── 唯一入口（2026-10-20 用户令「合成一个入口」）────────────────
            # `/` 是六标签入口页；工作台挪到 `/admin`（它自己的 /app.js、/style.css
            # 仍按绝对路径从静态根取，所以只多这一个整页路由就够）。
            if u.path in ("/admin", "/admin/"):
                return self._page(os.path.join(UI, "index.html"))
            if u.path in ("/buildings", "/buildings/"):
                return self._page(os.path.join(UI, "buildings.html"))
            # ── 合并进来的 8800 流程台（2026-10-20）──────────────────────────
            # 页面路由用 `/pipeline/*`：根 `/` 归工作台，流程台自己的导航已改成这一套。
            if u.path in ("/pipeline", "/pipeline/"):
                return self._page(os.path.join(CDUT, "pipeline", "index.html"))
            if u.path in ("/pipeline/flow", "/pipeline/flow/"):
                return self._page(os.path.join(CDUT, "pipeline", "flow.html"))
            if u.path in ("/pipeline/floors", "/pipeline/floors/"):
                return self._page(os.path.join(CDUT, "pipeline", "floors.html"))
            if u.path in ("/pipeline/pages", "/pipeline/pages/"):
                return self._page(os.path.join(CDUT, "pipeline", "pages.html"))
            # 一页两个标签：同机位对照 / 分层显隐（原两页原样 iframe 托管）
            if u.path in ("/compare", "/compare/"):
                return self._page(os.path.join(CDUT, "demo", "compare.html"))
            # ── 判据科普页（2026-10-20 用户令：判据太多太复杂，做成科普 + 配图）──────────
            if u.path in ("/criteria", "/criteria/"):
                return self._page(os.path.join(UI, "criteria.html"))
            if u.path == "/api/criteria":
                return self._json(criteria_summary())
            if u.path == "/api/state":
                return self._json(PIPE.collect())
            if u.path.startswith("/files/"):
                return self._pipe_file(u.path[len("/files/"):])
            # ★ 中文前缀（`/过程/`）在 URL 里是百分号编码的 ⇒ 先解一层再比前缀。
            dec = unquote(u.path)
            for pre, base in MOUNTS:
                if dec.startswith(pre):
                    return self._mount(base, dec[len(pre):])
            if u.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            return self._static(u.path)
        except KeyError as e:
            return self._err(404, "没有这件：%s" % e)
        except ValueError as e:     # 参数不合法（如 bid 不在档案里、rot 越界）不是服务端故障
            return self._err(400, str(e))
        except Exception as e:                                    # noqa: BLE001
            traceback.print_exc()
            return self._err(500, "%s: %s" % (type(e).__name__, e))

    def do_POST(self):
        try:
            if not self._same_origin():
                return self._err(403, "跨源写请求被拒")
            u = urlparse(self.path)
            if u.path == "/api/login":
                if not self._login_allowed():
                    return self._err(429, "登录尝试过于频繁，请稍后再试")
                body = self._body()
                username = str(body.get("username") or "")
                password = str(body.get("password") or "")
                if not auth_verify(username, password):
                    self._login_failed()
                    return self._err(401, "账号或密码不正确")
                self._login_succeeded()
                return self._json(
                    {"ok": True, "user": AUTH_USER,
                     "redirect": auth_redirect_target(body.get("next"))},
                    200, [("Set-Cookie", self._session_cookie(AUTH_USER))],
                )
            if u.path == "/api/logout":
                self._body() if (self.headers.get("Content-Length") or "0") != "0" else None
                return self._json(
                    {"ok": True}, 200,
                    [("Set-Cookie", self._clear_cookie())],
                )
            if not self._authed():
                return self._err(401, "请先登录")
            if VIEWER_MODE:
                return self._err(404, "服务器只提供三维模型浏览")
            # 上传件走原始字节（X-File-Name + octet-stream）；其余接口才按 JSON 解。
            if u.path == "/api/quick3d":
                name = unquote(self.headers.get("X-File-Name") or "upload.dxf")
                return self._json(quick3d_save(name, self._raw()))
            body = self._body()
            if u.path == "/api/params/save":
                return self._json(save_param(body))
            if u.path == "/api/profile/save":
                return self._json(save_profile(body))
            if u.path == "/api/room/save":
                return self._json(save_room(body))
            if u.path == "/api/run":
                return self._json(start_run(body))
            if u.path == "/api/photo/run":
                return self._json(start_photo(body))
            # 流程台的「试算」：实现仍在 `pipeline/server.py::trial_run`（同一把锁）
            if u.path == "/api/try":
                if not PIPE._TRIAL_LOCK.acquire(blocking=False):
                    return self._err(429, "已有一次试算在跑")
                try:
                    return self._json(PIPE.trial_run(body.get("edits") or {}))
                finally:
                    PIPE._TRIAL_LOCK.release()
            return self._err(404, "没有这个接口")
        except ValueError as e:
            return self._err(400, str(e))
        except Exception as e:                                    # noqa: BLE001
            traceback.print_exc()
            return self._err(500, "%s: %s" % (type(e).__name__, e))

    def _page(self, p):
        """发一个整页（流程台四页 / `/compare`）：**不猜路径**，调用方给绝对文件名。"""
        try:
            with open(p, "rb") as f:
                b = f.read()
        except OSError:
            return self._err(404, "页面不在：%s" % p)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _pipe_file(self, rel):
        """流程台的 `/files/` —— 只读项目根以下（与 `pipeline/server.py::_file` 同一口径）。

        ★ 大件（`_layers` 里那份 146 MB 的 `reality_local.glb`）**边读边发**，
          不先 `read()` 进内存 —— 流程台原实现是整读，合并后顺手改了。
        """
        p = _safe_join(CDUT, unquote(rel or ""))
        if p is None:
            return self._err(403, "路径不合法")
        if not os.path.isfile(p):
            return self._err(404, "没有这个文件")
        ctype = PIPE.MIME.get(os.path.splitext(p)[1].lower()) \
            or mimetypes.guess_type(p)[0] or "application/octet-stream"
        size = os.path.getsize(p)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(p, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def _mount(self, base, rel):
        """只读挂载（demo/packs/process/rebuild）：**按真实路径**确认落在 base 里。

        ★ 2026-10-19 安全评审：原来只按 `/` 拆开找 `..`。Windows 把 `\\` 也当分隔符，
          `..\\..\\x` 整段不会等于 `..` ⇒ 照样穿出去。现在 realpath 后比对前缀，
          反斜杠 / 绝对路径 / 盘符三种写法一并挡住。
        ★ 2026-10-20 部署评估：原来整件 read() 进内存，139 MB 的 GLB 每个并发请求
          都会再占一份内存。现在只 stat + 流式发送，并带 ETag 支持 304。
        """
        rel = unquote(rel or "")
        p = _safe_join(base, rel)
        if p is None:
            return self._err(403, "路径不合法")
        if not os.path.isfile(p):
            return self._err(404, "没有这个文件")
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".mjs": "application/javascript; charset=utf-8",
                 ".json": "application/json; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png",
                 ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                 ".glb": "model/gltf-binary", ".gltf": "model/gltf+json",
                 ".bin": "application/octet-stream",
                 ".dxf": "application/dxf",
                 ".obj": "text/plain; charset=utf-8"}.get(
                     os.path.splitext(p)[1].lower(), "application/octet-stream")
        return self._send_file(p, ctype)

    def _send_file(self, p, ctype):
        """流式发送文件；ETag 让大模型可复用浏览器缓存。"""
        st = os.stat(p)
        etag = '"%x-%x"' % (st.st_mtime_ns, st.st_size)
        inm = self.headers.get("If-None-Match") or ""
        if etag in {x.strip() for x in inm.split(",")}:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
        self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(st.st_size))
        self.end_headers()
        with open(p, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def _static(self, path):
        if path in ("", "/", "/index.html"):
            path = "/portal.html"        # 唯一入口（六标签）；工作台在 /admin
        rel = path.lstrip("/")
        p = _safe_join(UI, rel)
        if p is None:
            return self._err(403, "路径不合法")
        if not os.path.isfile(p):
            return self._err(404, "没有这个文件")
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".json": "application/json; charset=utf-8",
                 ".svg": "image/svg+xml", ".png": "image/png"}.get(
                     os.path.splitext(p)[1].lower(), "application/octet-stream")
        return self._send_file(p, ctype)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("CDUT3D_PORT", "8150")))
    ap.add_argument("--host", default=os.environ.get("CDUT3D_HOST", "127.0.0.1"))
    ap.add_argument("--version", action="version", version=APP_VERSION)
    a = ap.parse_args(argv)
    os.makedirs(UI, exist_ok=True)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print("cdut3d %s  http://%s:%d/   （Ctrl+C 停）" % (APP_VERSION, a.host, a.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("停了")


if __name__ == "__main__":
    main()
