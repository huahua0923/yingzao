# -*- coding: utf-8 -*-
"""作业台数据层（原 `_scratch/_portal.py` 的 8144 页面，2026-09-25 收编）。

搬过来的只有**能力**，页面本身用管理台的原生视图重写。三条搬的时候刻意改了：

1. **`/svc` 不搬**：它唯一的职责是拉起 8123（整栋三维）和 8130（建模控制台）——
   那两个现在就在**同一个进程**里，再留一个「拉起子服务」的按钮等于留一个
   永远显示「已在运行」的假开关。
2. **「量不到」与「零」分开**：原页面给没有 GLB 的楼打 `0M`、给没跑过门禁的楼打
   `未跑`（这一半是对的），`0M` 那一半把「没有产物」说成了「0 兆的产物」。
   这里一律回 `None`，由前端写「无产物」（memory: gauge-coverage-invisible-in-summary）。
3. **绝不自造写闸门**：上传与跑脚本两条是写/执行路由，闸门只有 `deps.require_compute`
   一处（先例 `analysis.py:50` / `checks.py:126`）。本模块只管「活怎么干」。

★ 楼栋清单**复用** `services.artifacts.list_buildings` —— 「库里有哪些楼」只许有一处
  实现（`data/buildings/*/profile.json`）。这里的每一列都是在那个集合上补出来的，
  不另起一份枚举。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from ..responses import ApiError, bad_request
from ..settings import Settings
from . import artifacts, jobs, refs

#: 页面上的按钮派给哪个脚本 —— 数据驱动，加模式只改这张表（照抄 `_scratch/_retired_20260925/_portal.py:41-46`）。
#: ★ 这些脚本在 `_scratch/` 里、**没进 git**（本仓约定：一次性本机脚本不入库）。
#:   所以 `start_run` 会先看它们在不在：不在就**明说「这台机器上没有这个脚本」**，
#:   而不是起一个立刻死掉、只留下一份空日志的作业（memory: executor-must-run-the-gate-itself）。
RUNNERS = {
    "all":    {"script": "_system.py", "arg": "all", "label": "全库跑一遍（生产+门禁+速览图）"},
    "check":  {"script": "_system.py", "arg": "check", "label": "只跑门禁"},
    "ingest": {"script": "_system.py", "arg": "ingest", "label": "归集 + DWG→DXF"},
    "refs":   {"script": "_ref_import.py", "arg": "--scan", "label": "外观图入库（按文件名认楼号）"},
}

# 文件名守卫：**逐条照抄 `_scratch/_retired_20260925/_portal.py:256-273`**，不新发明。
# ★ `_scratch/_retired_20260925/_portal.py:258` 那条 building 用的是 `^[\w\-]+$`；这里换成 `deps.BuildingName`
#   等价但更紧（同一个字符集 + 32 字符上限）—— 不是为了收紧而收紧，是为了
#   「楼号长什么样」全仓只有一处定义。预览图的文件名守卫原样保留。
_PREVIEW_BUILDING_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_PREVIEW_FILE_RE = re.compile(r"^[\w\-.]+\.png$")


# ── 路径（都由 Settings 推导，不写死 D:\gym3d）─────────────────────

def _inbox(cfg: Settings) -> Path:
    return Path(cfg.root) / "_inbox"


def _inbox_refs(cfg: Settings) -> Path:
    return _inbox(cfg) / "refs"


def _tasks(cfg: Settings) -> Path:
    return Path(cfg.root) / "_qa" / "tasks"


def _qa_dir(cfg: Settings) -> Path:
    return Path(cfg.root) / "_qa"


def _su_dir(cfg: Settings) -> Path:
    # ★ 仍读 `_scratch/su_jobs/`：SU 复核页是脚本产出的**本机产物**，不属交付件。
    #   `_scratch/` 整体移出仓外是另一件事，那时候这一行跟着改（写在明面上，免得
    #   下次有人以为它是漏改的旧路径）。
    return Path(cfg.root) / "_scratch" / "su_jobs"


def _script(cfg: Settings, name: str) -> Path:
    return Path(cfg.root) / "_scratch" / name


# ── 只读：状态与两个队列 ──────────────────────────────────────────

def _qa_errors(cfg: Settings, name: str):
    """`_qa/<楼>_qa.txt` 里的 `[ERROR]` 条数；**没有这份文件 = None（未跑）**。

    与 0 分开是这一列的全部意义：0 = 跑了且干净，None = 没跑过。
    """
    f = _qa_dir(cfg) / ("%s_qa.txt" % name)
    if not f.is_file():
        return None
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            return fh.read().count("[ERROR]")
    except OSError:
        return None


def _row(cfg: Settings, b: dict) -> dict:
    """在 `artifacts.list_buildings` 的行上补作业台要的那几列。

    ★ 这几列**现算、不进 `artifacts` 的缓存**：缓存键只覆盖 profile/rooms/floors，
      而 GLB 是另一个产物 —— 把现算的值和缓存里的 `has_model` 并排放，
      会出现「这一行说没有、那一列说有」。所以这里**不用** `has_model`，
      有无产物一律由下面这个 `glb_mb` 说了算（一处实现）。
    """
    name = b["name"]
    d = artifacts.building_dir(Path(cfg.resolved_data_dir), name)
    glb = d / ("%s-building.glb" % name)
    pv = d / "dxf_plan_fast"
    if glb.is_file():
        st = glb.stat()
        glb_mb = round(st.st_size / 1048576.0, 1)
        glb_at = time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime))
    else:
        glb_mb, glb_at = None, None            # 无产物 ≠ 0 兆字节
    if pv.is_dir():
        pngs = sorted(f for f in os.listdir(pv) if f.endswith(".png"))
        preview_png = len(pngs)
        # ★ 顺手给出**真实存在**的第一个文件名，让页面能给出一个点得开的链接。
        #   不这么做，前端就只能猜 `floor1.png` —— 而有的楼第一层不叫 floor1
        #   （层号从 0 起、或层是跳号的），猜出来的链接是 404，而 404 在屏幕上
        #   看着像「这栋楼没有速览图」。让知道答案的那一方给出答案。
        preview_first = pngs[0] if pngs else None
    else:
        preview_png, preview_first = None, None   # 没有速览图目录 ≠ 0 张
    return {
        "name": name, "title": b.get("title") or name,
        "floors": b.get("floor_count"), "rooms": b.get("rooms"),
        "glb_mb": glb_mb, "glb_at": glb_at,
        "qa_errors": _qa_errors(cfg, name), "preview_png": preview_png,
        "preview_first": preview_first,
    }


def _listing(path: Path):
    """列一个目录；**目录不存在 = None（量不到）**，不是空列表（零个）。"""
    if not path.is_dir():
        return None
    return sorted(os.listdir(path))


def status(cfg: Settings) -> dict:
    rows = [_row(cfg, b) for b in artifacts.list_buildings(Path(cfg.resolved_data_dir))]
    cur = jobs.active(cfg)
    su = _listing(_su_dir(cfg))
    return {
        "rows": rows,
        "inbox": _listing(_inbox(cfg)),
        "tasks": _listing(_tasks(cfg)),
        "running": bool(cur), "job": cur,
        # 未跑过的门禁数 / 有待办的楼数 —— 页面顶部那两个数由服务端算，
        # 免得前端各算一遍（一个判断多份实现）。
        "qa_missing": [r["name"] for r in rows if r["qa_errors"] is None],
        "su": [f for f in (su or []) if f.startswith("_su_") and f.endswith(".html")],
        "su_dir_present": su is not None,
        "modes": [{"mode": m, "label": v["label"],
                   "script_present": _script(cfg, v["script"]).is_file()}
                  for m, v in RUNNERS.items()],
    }


def refs_pending(cfg: Settings) -> dict:
    """外观图的两个队列 —— 判读环节的入口（照抄 `_scratch/_retired_20260925/_portal.py:100-126` 的形状）。

    待入库：`_inbox/refs/` 里还没进 `data/refs/` 的图（按文件名认楼号）
    待判读：已经有图、但还没有 facts.json 的楼（= 照片还没人看出结论）
    """
    buildings_dir = Path(cfg.resolved_data_dir) / "buildings"
    todo = []
    refs_in = _inbox_refs(cfg)
    for fn in _listing(refs_in) or []:
        fp = refs_in / fn
        if not fp.is_file() or os.path.splitext(fn)[1].lower() not in refs.IMG_EXT:
            continue
        g = refs.guess_building(fn)
        todo.append({"file": fn, "kb": round(fp.stat().st_size / 1024.0, 1),
                     "guess": g if refs.known_building(g, buildings_dir) else "",
                     "raw_guess": g})
    ref_root = Path(cfg.resolved_data_dir) / "refs"
    judged, pending = [], []
    for name in _listing(ref_root) or []:
        d = ref_root / name
        if not d.is_dir() or name.startswith("_"):
            continue
        if (d / "refs.json").is_file():
            (judged if (d / "facts.json").is_file() else pending).append(name)
    return {"inbox": todo, "pending": pending, "judged": judged,
            "inbox_dir_present": _listing(refs_in) is not None}


# ── 只读：文件出口 ────────────────────────────────────────────────

def resolve_refimg(cfg: Settings, filename: str):
    """待入库的用原名，已入库的用 `sha1_原名`，两处都按**文件名**找。

    回 `(Path, content_type)`；找不到回 None（由路由翻成 404）。
    """
    fn = os.path.basename(filename or "")
    if not fn or fn in (".", ".."):
        return None
    for d in (_inbox_refs(cfg), Path(cfg.resolved_data_dir) / "refs" / "_images"):
        f = d / fn
        if f.is_file():
            return f, refs.content_type_for(fn)
    return None


def resolve_preview(cfg: Settings, building: str, filename: str):
    """速览图：`data/buildings/<楼>/dxf_plan_fast/<floorN>.png`。

    ★ 两个正则**逐条照抄 `_scratch/_retired_20260925/_portal.py:258`**。注意 `dxf_plan_fast` 是**写死**的一段，
      不参与拼接 —— 楼号与文件名都先过后面的正则，所以 `..` 与斜杠进不来。
    """
    if not _PREVIEW_BUILDING_RE.match(building or ""):
        raise bad_request("楼号形状不对：%r" % building)
    if not _PREVIEW_FILE_RE.match(filename or ""):
        raise bad_request("速览图文件名形状不对：%r" % filename)
    return Path(cfg.resolved_data_dir) / "buildings" / building / "dxf_plan_fast" / filename


def resolve_task(cfg: Settings, filename: str) -> Path:
    """任务单 `_qa/tasks/<楼>.md`（原 8144 的「待办」链接）。"""
    return _tasks(cfg) / os.path.basename(filename or "")


def resolve_su(cfg: Settings, filename: str) -> Path:
    return _su_dir(cfg) / os.path.basename(filename or "")


# ── 写：上传 ──────────────────────────────────────────────────────

def save_upload(cfg: Settings, name: str, body: bytes) -> dict:
    """收一个上传。**图片进 `_inbox/refs/`，其余进 `_inbox/`**（照抄 8144 的分流）。

    为什么图片要分流：图片不是 CAD，混进 `_inbox/` 会被 `convert_dwg_to_dxf`
    当图纸去啃（`_scratch/_retired_20260925/_portal.py:284-287` 的原话）。
    """
    fn = os.path.basename(name or "")
    if not fn or fn in (".", "..") or len(fn) > 128:
        raise bad_request("文件名不能用：%r" % name)
    ext = os.path.splitext(fn)[1].lower()
    is_img = ext in refs.IMG_EXT
    dst_dir = _inbox_refs(cfg) if is_img else _inbox(cfg)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / fn
    # ★ 原子落盘：页面每 8 秒列一次 `_inbox/`，直写会让它列到一个**半截的文件**
    #   （缩略图裂开，且不报错）。tmp → os.replace 与 `_ref_import.save_refs` 同一套路。
    tmp = dst.with_name(dst.name + ".part")
    with open(tmp, "wb") as fh:
        fh.write(body)
    os.replace(tmp, dst)
    got = ""
    if is_img:
        g = refs.guess_building(fn)
        # 猜出来的楼号必须真的在库里；猜错比猜不出更坏（会把照片挂到别人家）
        if refs.known_building(g, Path(cfg.resolved_data_dir) / "buildings"):
            got = g
    return {"saved": fn, "bytes": len(body),
            "kind": "reference-image" if is_img else "cad",
            "building_guess": got,
            "next": ("python -u _scratch\\_ref_import.py \"_inbox\\refs\\%s\" "
                     "--bld %s --kind aerial" % (fn, got or "<楼号>"))
                    if is_img else "ingest"}


# ── 写：跑脚本 ────────────────────────────────────────────────────

def start_run(cfg: Settings, mode: str) -> dict:
    """起一个模式。并发/超时由 `services.jobs` 统一管，这里只管「派哪个脚本」。"""
    spec = RUNNERS.get(mode)
    if not spec:
        raise bad_request("没有这个模式：%r（有：%s）"
                          % (mode, "、".join(sorted(RUNNERS))))
    script = _script(cfg, spec["script"])
    if not script.is_file():
        # ★ 明说「这台机器上没有这个脚本」，而不是起一个立刻死掉、只留一份空日志的作业
        #   —— 后者在屏幕上是「已启动」，用户会一直等一个不存在的东西。
        raise ApiError(503, "script_missing",
                       "这个按钮要的脚本不在这台机器上：%s"
                       "（`_scratch/` 里的本机脚本未进 git，换台机器就没有）"
                       % script.name,
                       {"script": str(script), "mode": mode})
    job = jobs.start(cfg, mode=mode, label=spec["label"],
                     argv=[str(script), spec["arg"]], cwd=str(cfg.root),
                     extra={"script": spec["script"]})
    return job.public()
