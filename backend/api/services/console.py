# -*- coding: utf-8 -*-
"""建模控制台数据域（原 `backend/web/control.py` 的 8130 页面，2026-09-25 收编进管理台）。

**这一份是从 `control.py` 搬过来的**，不是重写：`_building_ctx` / `_resolve_artifact` /
`glb_is_stale` / `building_status` / `list_buildings` / `get|put_profile` /
`get|put_spec` / `stage_argv` 的语义逐条照抄，只有三处**刻意**不同，都写在下面。

★ 三处刻意不同（都是"搬进长活进程"才暴露出来的）：

  1. **楼层缓存有界**。原 `control.py:126` 的 `_FLOOR_CACHE` 是无界字典 —— 在那个
     短命的 stdlib 控制台里无所谓，在这里（管着所有屏的那个进程）就是泄漏：
     一张楼层 PNG 几百 KB、一份 DXF 可能上 MB，而 key 是 (楼, 层, kind)，
     全库 95 栋 × 层数 × 2 足够把它撑到几个 GB。改成 LRU 限容（`_CACHE_MAX`），
     逐出的是**缓存**不是产物，下一次问会重算。

  2. **执行走 `services.jobs`，不裸挂 subprocess**。原 `start_job` 是
     `Thread + Popen(stdout=PIPE)` —— 铁律 14 那个形状（PIPE 不抽干会死锁），
     而且它声明的超时/并发上限**一个都没实现**（`settings.py:91-92` 写了
     `job_timeout_s=7200` / `job_max_concurrency=1`，这里才是它们真正生效的地方，
     `jobs.start` 两样都管，冲突时回 409 并**点名**是谁占着槽位）。
     ⇒ 附带一条代价，明说：`job_max_concurrency` 现在是**全进程共用一个槽位**
       （控制台、作业台、跑判据三者抢同一个），比原来"只比同名或全仓"严格得多。
       这是 `settings.py` 里那个值本来的意思，不是新发明的规矩。

  3. **注册表楼要能"说拿不到"**（见 `registry_profiles`）—— 这一条是列表分母的事，
     写在那个函数里。

搬运时**逐条对着 `control.py` 核过**、且刻意**不改**的几处（免得下一个人以为是漏了）：
  · `status()` 的 stage 里**不带 `script`**（control.py 带）。理由：`control.js` 从来
    没读过它（grep 过：`renderFlow` 只用 `label/no/scope/writes/slow/danger/desc/
    artifacts/runnable/whyManual/inplace/stale/done`），而它是本机路径 ——
    `meta_source` 那份投影（`_STRIPPED_STAGE_KEYS`）本来也是为"别泄漏本机路径"
    才摘它的。少一个字段比多一个字段安全，且没人用。
  · **`meta()` 不加进程内缓存**：实测 `load_meta` 首调 1.54s（全是 trimesh/numpy 的
    import），**第二次 0.000s**（`console_meta.spec_defaults()` 自己 memo 了）。
    加一层缓存只会多一个"meta 是什么"的出处。`status()`/`stage_argv()` 每次请求都
    调它，代价已实测为零。
  · **`GET /api/console/meta` 会把 `script` / `args` 发给局域网**（compute=1 时
    `_live()` 原样返回，投影只在 compute=0 生效）。这是**已知且接受**的：读得到命令行
    不等于跑得起来（执行面非回环一律 403），而再写一份"给局域网看的投影"就是
    第二个"什么能发出去"的出处 —— 那正是本轮在收的那类账。
  · `job_conflict`（`control.py:496`）**没有搬**：它的规则被 `jobs.start` 的
    `job_max_concurrency` 完全覆盖（且更严），搬过来就是同一判断的第二份实现。
  · `_spec_path`（`control.py:223`）**定义了没人调用**（grep 全文件只有定义那一行）。
    没搬，也没动它 —— 记在这里是因为它是"写好的函数 ≠ 被调用的函数"的又一例。

★ 与 `meta_source` 的分工：**参数表/阶段表不在本文件里**。`meta()` 直接转发
  `meta_source.load_meta()`（那是 P0 建好的单一真源：本机实时问 `console_meta`，
  `compute=0` 的服务器读冻结产物 `data/_meta/console_meta.json`）。
  本文件**不 import `console_meta`** —— 一 import 就等于绕开了那套两路逻辑。
  ⚠ 2026-09-25 搬运时的实测：`meta_source` 当时**一处调用方都没有**（写好了、有冻结
  产物、有 `freeze_meta.py`，但没人调它）—— 典型的"写好的函数不等于被调用的函数"。
  控制台就是它的调用点。
"""
from __future__ import annotations

import dataclasses
import glob
import json
import logging
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..responses import ERR_INTERNAL, ERR_UPSTREAM, ApiError, bad_request, not_found
from ..settings import Settings
from . import jobs, meta_source

log = logging.getLogger("gym3d.console")

#: 楼号/阶段 id 的形状。与 `deps.BuildingName` 的 pattern 同一份规则，
#: 路由那侧还有一道 FastAPI 的 Path 校验（422）；这里是给**内部调用**兜底的
#: （例如 stage id 从查询参数来，走的是普通 str）。
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

#: 走 `run_step.py` 的三个老阶段。它们**不在** `console_meta.PIPELINE` 里
#: （`full` 尤其不是），但 8130 的按钮一直在用，且 `run_step.py` 是
#: 「档案加载优先级 + 输出路径覆盖」的唯一正确实现 —— 绕开它会写错地方。
RUN_STEP_STEPS = ("recognize", "glb", "full")

#: 楼层资产缓存上限（条目数）。理由见模块头第 1 条。
_CACHE_MAX = 8
_FLOOR_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()

#: 注册表（`recognizer.profile._PROFILES`）**只记成功**。失败不缓存 ——
#: 装上依赖之后应该能立刻好起来，缓存一次失败会让它一直是坏的。
_REGISTRY: dict | None = None


# ── 路径 ──────────────────────────────────────────────────────────

def _data(cfg: Settings) -> Path:
    return cfg.resolved_data_dir


def _buildings(cfg: Settings) -> Path:
    return _data(cfg) / "buildings"


def _run_step(cfg: Settings) -> Path:
    return cfg.root / "backend" / "web" / "run_step.py"


def _ensure_console_paths(cfg: Settings) -> None:
    """把控制台那几个兄弟目录挂上 `sys.path`。

    用的是本仓**唯一**那份实现（`backend/paths.py` 的 `ensure_sys_path`）——
    以前每个脚本各写一遍 `sys.path.insert(0, r"D:\\gym3d")`，换个机器就废。
    还差一个 `backend/web`（`run_step` / `console_meta` 就在那儿）。
    """
    from backend.paths import ensure_sys_path      # 仓根在 path 上（run_api.py 挂的）

    ensure_sys_path("modeling", "nav")
    web = str(cfg.root / "backend" / "web")
    if web not in sys.path:
        sys.path.insert(0, web)


def _opt_json(path: Path) -> tuple[Any, str | None]:
    """读一个**可以不存在**的 JSON：回 `(对象, 错因或 None)`。

    ★ 不沿用 `artifacts.read_json`：那个对"不存在"是抛 404 的（它服务的路由
      本来就要求文件在）。这里 profile.json / spec.json 都可能没有。
    ★ 但**损坏**与**不存在**必须分开：损坏时回一句错因，由调用方写到屏幕上
      （"这栋的档案读不了"与"这栋用默认值"在屏幕上不许长得一样）。
    """
    if not path.is_file():
        return {}, None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, json.JSONDecodeError) as ex:
        return {}, "%s: %s" % (type(ex).__name__, ex)


def registry_profiles(cfg: Settings) -> tuple[dict | None, str | None]:
    """`recognizer.profile._PROFILES` —— **懒 import**，且**失败要说**。

    ★ 为什么必须懒：`import recognizer.profiles` 会把 `ezdxf` + `shapely`
      一起拖进来（`recognizer/recognize.py` 模块级就 import 它们）。服务器 venv
      刻意不装（`requirements-server.txt`），模块级 import 就等于**服务器上
      `import backend.api.main` 直接失败** —— 崩的是整个管理台十一屏，
      不只是控制台这一屏。先例：`routers/components.py` 的同款懒 import。

    ★ 为什么失败要回一个**错因串**而不是回空字典：这一条决定的正是
      「注册表楼（lihua）算不算在列表里」。回空字典，屏幕上是"95 栋"，
      而真值是"95 栋 ＋ 1 栋我拿不到"—— 两个都印成 95 就分不开了
      （铁律 16：量不到与没问题必须是两行不同的字）。
    """
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY, None
    try:
        _ensure_console_paths(cfg)
        import recognizer.profiles          # noqa: F401  导入即注册 lihua / j6
        from recognizer.profile import _PROFILES

        _REGISTRY = dict(_PROFILES)
        return _REGISTRY, None
    except Exception as ex:  # noqa: BLE001 —— 依赖缺失是**预期**的一种，不是崩溃
        return None, "%s: %s" % (type(ex).__name__, ex)


def registry_listed(cfg: Settings) -> tuple[dict, str | None]:
    """注册表里**本机真的可用**的那些（源图纸在盘上）。回 `({name: profile}, err|None)`。

    ★ 为什么要把「在注册表里」与「源图在本机」分成两个问题 —— 这是 8130 的真缺陷：
      注册表里 **j6 的 `dxf` 是一个占位路径**（本机不存在）。`control.py` 的列表
      确实把这类剔掉了（`if not os.path.exists(p.dxf): continue`），但它的
      `put_profile` / `put_spec` 只判 `name in reg` —— 于是给 j6 写规格会落到
      `data/spec.json`，而那正是 **lihua 共用**的那一份（2MB 的 `lihua-building.glb`
      就是按它出的），也就是**交付件**。一个列表里看不见、也选不中的名字，
      能把别人家的交付件改掉，而屏幕上没有任何提示。
      ⇒ 全仓**一条**规则：列得出来的楼才可读可写。列表、`building_exists`、
        规格归属，三处都用这一个函数（不是三处各写一遍 `name in reg`）。
    """
    reg, err = registry_profiles(cfg)
    if reg is None:
        return {}, err
    return {n: p for n, p in reg.items() if os.path.exists(p.dxf)}, None


def _data_url(cfg: Settings, path: Path) -> str | None:
    """盘上路径 → 本服务**今天真能取到**它的 URL；取不到回 None。

    ★ 为什么要挡一道：8130 是从**仓库根**发文件的，`data/` 下什么都取得；合并进来
      之后只有这几个挂载点（`/data/buildings` 整目录 ＋ 三条窄路由 ＋ `/data/` 根下
      的 `.glb`）。让 URL 由"路径落在哪个挂载点里"算出来，就不会出现
      `links` 里躺着一个必然 404 的地址 —— 那种地址比没有更糟：用户会以为文件丢了。
    ★ 一处实现：这些 URL 的形状只在这里定，前端不拼字符串（8130 那版前端硬写
      `data/buildings/<名>/dxf_plan/index.html`，对注册表楼就指错了地方）。
    """
    root = _data(cfg)
    for sub in ("buildings",):
        try:
            rel = path.resolve().relative_to((root / sub).resolve())
        except ValueError:
            continue
        return "/data/%s/%s" % (sub, rel.as_posix())
    # 根级散文件（lihua 这类注册表楼的 `<名>-building.glb` 就在 data/ 根下）。
    # 只放行根下**一级**文件 —— `data/_meta/**`、`data/refs/**` 进不来（铁律 12）。
    if path.parent.resolve() == root.resolve():
        return "/data/%s" % path.name
    return None


#: 列表行要报「有没有」的产物，以及它们相对**产物根**（`dirname(out_dir)`）的位置。
#: 与 `console_meta.PIPELINE` 里同名阶段的 `produces` 是同一套相对路径
#: （`glb`=96 栋都有、`dxfPlan`/`compare`=49 栋有、`spec` 全部都有）。
#: ⇒ 走 `_resolve_artifact`，不再手写 `d / "dxf_plan" / "index.html"`：
#:   手写的那一份与 `status()` 用的那一份**会在 out_dir 被覆盖时分开**，
#:   而分开不会报错 —— 屏幕上只是列表说"有"、流程说"没有"。
_ROW_ARTIFACTS = {
    "glb": "{name}-building.glb",
    "spec": "spec.json",
    "dxfPlan": "dxf_plan/index.html",
    "compare": "compare.html",
}


def _url_if_exists(cfg: Settings, path: Path) -> str | None:
    """文件在 ⇒ 给 URL；不在 ⇒ None（**不给**一个必然 404 的地址）。"""
    return _data_url(cfg, path) if path.is_file() else None


def _links(cfg: Settings, arts: dict[str, Path], has_orphan: bool = False) -> dict:
    """这一行**能点的 URL**（服务端拼好，前端不拼）。

    ★ `has_orphan`：产物**在**、但本服务没为它开通路（`data/dxf_plan/` 与
      `data/compare.html` 都在 `data/` 根下，而 `/data/` 根下只放行 `.glb`）。
      这时**不许**给一个必然 404 的 URL —— 那比不给更糟，用户会以为是文件丢了。
      给一句话，让屏幕自己说"有产物、但这里取不到"（铁律 16）。
    """
    return {
        "glb": _url_if_exists(cfg, arts["glb"]),
        "dxfPlan": _url_if_exists(cfg, arts["dxfPlan"]),
        "compare": _url_if_exists(cfg, arts["compare"]),
        "note": ("dxf_plan / compare 的产物在 data/ 根下，本服务没有为它们开通路"
                 "（8130 是从仓库根发文件的）—— 要看请走命令行"
                 if has_orphan else None),
    }


def _registry_row(cfg: Settings, name: str, p: Any) -> dict:
    """注册表楼的一行。路径上下文照 `control.py:387-411` 那一支。"""
    override, _err = _opt_json(_data(cfg) / ("%s-profile.json" % name))
    out_dir = Path(override.get("out_dir") or p.out_dir)
    style = override.get("style") or (p.style or {})
    classifier = override.get("classifier") or p.classifier
    parent = out_dir.parent
    arts = {k: _resolve_artifact(cfg, name, rel, parent)
            for k, rel in _ROW_ARTIFACTS.items()}
    # 产物**在**、但通路不在（`data/dxf_plan/`、`data/compare.html` 都在 data/ 根下，
    # 而根下只放行 `.glb`）。给一句说明，不给一个必然 404 的地址。
    orphan = any(arts[k].is_file() and _data_url(cfg, arts[k]) is None
                 for k in ("dxfPlan", "compare"))
    return {
        "name": name,
        "title": p.title,
        "source": "registry",
        "classifier": classifier,
        "roofType": style.get("roofType", "gable"),
        # ★ 字段名是 floor_count 而**不是** floors：8140 的 `/api/buildings` 用 `floors`
        #   装**数组**，8130 原来在同名路由上装**数字**（`control.js:193` 拿它拼
        #   `b.floors + ' 层'`）—— 一个词两处两个意思，正是本轮要收掉的那类账。
        #   两个数出自同一个 `_count_floors`（下面），只是这里的名字说得清。
        "floor_count": _count_floors(out_dir),
        "glb": arts["glb"].is_file(),
        "glbRel": "%s-building.glb" % name,
        "spec": arts["spec"].is_file(),
        "dxfPlan": arts["dxfPlan"].is_file(),
        "compare": arts["compare"].is_file(),
        "glbStale": glb_is_stale(out_dir, arts["glb"]),
        "links": _links(cfg, arts, has_orphan=orphan),
    }


# ── 楼栋列表 ──────────────────────────────────────────────────────

def _count_floors(out_dir: Path) -> int:
    if not out_dir.is_dir():
        return 0
    return len(glob.glob(str(out_dir / "floor*.json")))


def list_buildings(cfg: Settings) -> dict:
    """控制台的楼清单 = **批次楼**（`data/buildings/*/profile.json`）＋ **注册表楼**。

    ★ 这不是改名工程。8140 的 `services/artifacts.py:list_buildings` 只枚举
      `data/buildings/*/profile.json`，因此**看不到 lihua**；而 lihua 恰好是
      8130 首屏默认选中的那一栋。两边的分母本来就不一样，合成一条路由会把这个差
      抹掉，所以控制台有自己的一条。

    ★ 分母一律印出来（`counts`）：`compute=0` 的机器上注册表拿不到，总数就是 95；
      本机是 96。屏幕上**必须能看出少的那一栋是"拿不到"而不是"不存在"**。
    """
    bdir = _buildings(cfg)
    rows, broken = [], []
    if bdir.is_dir():
        for d in sorted(bdir.iterdir()):
            if not (d / "profile.json").is_file():
                continue
            cfg_obj, err = _opt_json(d / "profile.json")
            if err:
                broken.append({"name": d.name, "error": err})
            out_dir = Path(cfg_obj.get("out_dir") or (d / "floors"))
            parent = out_dir.parent
            style = cfg_obj.get("style") or {}
            arts = {k: _resolve_artifact(cfg, d.name, rel, parent)
                    for k, rel in _ROW_ARTIFACTS.items()}
            rows.append({
                "name": d.name,
                "title": cfg_obj.get("title") or d.name,
                "source": "batch",
                "classifier": cfg_obj.get("classifier") or "lwpolyline",
                "roofType": style.get("roofType", "gable"),
                "floor_count": _count_floors(out_dir),
                "glb": arts["glb"].is_file(),
                # 信息字段：产物相对 data/ 的位置（前端提示文字用）。**取文件的 URL
                # 一律读 `links`** —— 这里这个字符串不代表一定能取到。
                "glbRel": "buildings/%s/%s-building.glb" % (d.name, d.name),
                "spec": arts["spec"].is_file(),
                "dxfPlan": arts["dxfPlan"].is_file(),
                "compare": arts["compare"].is_file(),
                "glbStale": glb_is_stale(out_dir, arts["glb"]),
                "links": _links(cfg, arts),
            })

    # 注册表：只收「源图真在盘上」的那些（`registry_listed`，与写口同一把尺子）。
    listed, err = registry_listed(cfg)
    reg_rows, shadowed = [], []
    for name, p in listed.items():
        if any(r["name"] == name for r in rows):
            shadowed.append(name)       # 同名批次目录会盖住注册表那条，要能看见
            continue
        reg_rows.append(_registry_row(cfg, name, p))
    # ★ 剔掉了什么要**数出来**：占位路径（j6 的 dxf 本机不存在）不进列表，
    #   而"没有这一栋"与"这一栋的源图不在本机"在屏幕上必须是两行不同的字。
    raw, _rerr = registry_profiles(cfg)
    skipped = sorted(set(raw or {}) - set(listed))

    out_rows = rows + reg_rows
    return {
        "rows": out_rows,
        "counts": {"batch": len(rows), "registry": len(reg_rows), "total": len(out_rows)},
        "registry": {
            # 「读不到注册表」与「注册表里没有这栋楼」是两件事，`available` 只管前者。
            "available": raw is not None,
            "error": err,
            # 拿不到时这一句要顶到屏幕上（"少的那几栋不是我漏了"）。
            "note": ("注册表可用" if raw is not None
                     else "注册表拿不到（本机缺 recognizer 的依赖）——"
                          "下面这份清单**不含**注册表楼"),
            "skipped_no_dxf": skipped,
            "shadowed_by_batch": shadowed,
        },
        "broken_profiles": broken,
    }


# ── 路径上下文与产物 ──────────────────────────────────────────────

def _building_ctx(cfg: Settings, name: str) -> dict:
    """该楼的路径上下文：`{parent, floors_dir, glb, dxf}`。

    `parent` = 产物根（批次楼 `data/buildings/<名>`，注册表楼 `data`），
    阶段表里 `produces` 的相对路径都相对它（`buildings/` 开头的相对 `data`）。
    """
    cfg_obj, _err = _opt_json(_buildings(cfg) / name / "profile.json")
    out_dir, dxf = cfg_obj.get("out_dir"), cfg_obj.get("dxf")
    if not out_dir or not dxf:
        reg, _rerr = registry_profiles(cfg)
        rp = (reg or {}).get(name)
        if not out_dir:
            out_dir = str(rp.out_dir) if rp else str(_buildings(cfg) / name / "floors")
        if not dxf and rp:
            dxf = rp.dxf
    parent = Path(out_dir).parent
    return {"parent": parent, "floors_dir": Path(out_dir),
            "glb": parent / ("%s-building.glb" % name), "dxf": dxf}


def _resolve_artifact(cfg: Settings, name: str, rel: str,
                      parent: Path | None = None) -> Path:
    """把阶段表 `produces` 里的相对模板解析成绝对路径。

    `parent` 只是**省一次 IO** 的入口（列表页已经在手上有它了）；不给就现问
    `_building_ctx`。无论走哪条路，解析规则只有这一份。
    """
    rel = rel.format(name=name)
    if rel.startswith("buildings/"):
        return _data(cfg).joinpath(*rel.split("/"))
    if parent is None:
        parent = _building_ctx(cfg, name)["parent"]
    return parent.joinpath(*rel.split("/"))


def _floors_mtime(floors_dir: Path) -> float | None:
    if not floors_dir.is_dir():
        return None
    ms = [os.path.getmtime(f) for f in glob.glob(str(floors_dir / "floor*.json"))]
    return max(ms) if ms else None


def _upstream_mtime(stage: dict, up_m: dict) -> float | None:
    """阶段的上游 mtime —— **未登记的 upstream 键报错，不许静默返回 None**。

    旧写法 `up_m.get(stage.get("upstream"))`：键没登记时静默返回 None ⇒
    `bool(up and m < up)` 恒 False ⇒ `stale` 恒 False ⇒「改了楼层没重出」被判成
    「新鲜」，而屏幕上一切正常（与 NaN 让判据恒不触发同族）。
    这里是 `control.py:upstream_mtime` 同一处判断的第二份 —— 那一份还能顺带查
    `console_meta.UPSTREAM_KEYS` 这张登记表，**这一份刻意不 import console_meta**
    （模块级会把 trimesh/numpy/shapely 拖进只服务 venv，见 meta_source 文件头），
    所以只查本文件这张取值表自身的键集（它就是登记表的镜像；不一致会在
    `console_meta.self_check()` 里被点名，两个消费侧都会在启动时看到那行告警）。
    """
    key = stage.get("upstream")
    if key not in up_m:
        raise ApiError(
            500, ERR_INTERNAL,
            "阶段 %s 的 upstream=%r 没有登记在上游取值表里（%r）—— "
            "过期判据会静默判「不过期」，先登记再跑"
            % (stage.get("id"), key, tuple(up_m)))
    return up_m[key]


def glb_is_stale(floors_dir: Path, glb_path: Path) -> bool:
    """GLB 是否早于它自己的上游（最新 floor*.json）—— 「改过楼层但没重出模型」。

    缺任一端都回 False（无从判断 ≠ 过期）。

    **盲区（已知，mtime 解决不了）**：任何复制/还原都会刷新目标 mtime，于是
    「把旧 GLB 拷回去」看起来就是新鲜的（c022 是活例）。所以这条判据：
    **判「过期」可信，判「不过期」不可全信** —— 屏幕上那句话也是这么写的。
    """
    fm = _floors_mtime(floors_dir)
    if fm is None or not glb_path.is_file():
        return False
    return os.path.getmtime(glb_path) < fm


def building_exists(cfg: Settings, name: str) -> bool:
    """这栋楼**是不是真的存在**（批次目录 / 覆盖档案 / **列得出来的**注册表条目）。

    ★ 为什么值得一个函数：8130 的 `put_profile` 对任何形状合法的名字都会
      写盘（注册表楼那条分支直接 `open(data/<名>-profile.json,'w')`），
      于是一个手滑的名字（`c0010`）会在 `data/` 下**静静地多出一个文件**。
      控制台是写接口，写的又正好是交付目录 —— 名字先得是栋楼。
    ★ 为什么用 `registry_listed` 而不是 `name in _PROFILES`：注册表里的 **j6**
      是个占位条目（源图本机不存在）。按 `name in reg` 判，`put_spec("j6")` 会写到
      **lihua 共用**的 `data/spec.json` 上 —— 一个列表里看不见的名字改到交付件。
      列得出来才可写：列表与写口用**同一条**规则（见 `registry_listed`）。
    """
    if (_buildings(cfg) / name / "profile.json").is_file():
        return True
    if (_data(cfg) / ("%s-profile.json" % name)).is_file():
        return True
    listed, _err = registry_listed(cfg)
    return name in listed


def status(cfg: Settings, name: str) -> dict:
    """逐阶段产物现状 —— 「流程」那一屏的全部数据。

    过期判据是**逐阶段的**，用该阶段自己的上游（`PIPELINE[].upstream`）：
      · `dxf`    → 产物早于源图纸 = 图纸更新了但没重跑
      · `floors` → 产物早于最新 `floor*.json` = 楼层改了但没重出（"GLB 过期"那批）
      · `None`   → 无产物或只读，不判过期
      · 其余取值 → **报错**（见 `_upstream_mtime`）：这里曾经是 `up_m.get()`，
                   未登记的键静默 None ⇒ stale 恒 False ⇒ 假绿
    `inplace` 阶段（thin / doorpunch 就地改写楼层）没有独立产物，`done`/`stale`
    一律置 `None` —— 报「已完成」会是假信号（`floor0.json` 早在 recognize 时就存在了）。

    ★ 阶段表来自 `meta_source.load_meta()`（不是本文件 import console_meta）：
      `compute=0` 时它给的是**投影后**的那份（没有 script/args、runnable 全 False），
      而 `produces` 仍在 —— 于是服务器上这一屏照样能显示"哪一步做过"，
      只是没有运行按钮。前端因此不需要为两种模式写两套渲染。
    """
    if not building_exists(cfg, name):
        raise not_found("没有这栋楼：%s" % name, building=name)
    ctx = _building_ctx(cfg, name)
    fm = _floors_mtime(ctx["floors_dir"])
    dxf = ctx.get("dxf")
    dm = os.path.getmtime(dxf) if dxf and os.path.exists(dxf) else None
    up_m = {"floors": fm, "dxf": dm, "source": dm, None: None}

    stages = []
    for s in meta_source.load_meta(cfg).get("pipeline") or []:
        up = _upstream_mtime(s, up_m)
        inplace = bool(s.get("inplace"))
        arts = []
        for rel in s.get("produces") or []:
            fp = _resolve_artifact(cfg, name, rel)
            if fp.exists():
                m = os.path.getmtime(fp)
                arts.append({"rel": rel.format(name=name), "exists": True,
                             "size": fp.stat().st_size, "mtime": int(m),
                             "stale": None if inplace else bool(up and m < up)})
            else:
                arts.append({"rel": rel.format(name=name), "exists": False,
                             "size": 0, "mtime": None, "stale": None})
        if inplace:
            done = stale = None
        else:
            done = bool(arts) and all(a["exists"] for a in arts)
            stale = bool(arts) and any(a["stale"] for a in arts)
        stages.append({
            "id": s["id"], "no": s["no"], "label": s["label"],
            "scope": s.get("scope"), "writes": s.get("writes", False),
            "slow": s.get("slow", False), "runnable": s.get("runnable", False),
            "danger": s.get("danger"), "desc": s.get("desc", ""),
            "whyManual": s.get("why_manual"),
            "inplace": inplace, "upstream": s.get("upstream"),
            "artifacts": arts, "done": done, "stale": stale,
        })
    glb_m = os.path.getmtime(ctx["glb"]) if ctx["glb"].exists() else None
    return {
        "name": name,
        "floorsMtime": int(fm) if fm else None,
        "dxfMtime": int(dm) if dm else None,
        "glbMtime": int(glb_m) if glb_m else None,
        "glbStale": bool(fm and glb_m and glb_m < fm),
        "nFloors": _count_floors(ctx["floors_dir"]),
        "stages": stages,
    }


# ── 档案 / 规格 ───────────────────────────────────────────────────

def get_profile(cfg: Settings, name: str) -> dict:
    """读档案：批次目录 → 覆盖档案 → 注册表。

    ★ 注册表那一步失败要**说拿不到**（503），**不许**回 404 ——
      404 的意思是"没有这栋楼"，而实际是"这栋楼在注册表里，但本进程读不到它"。
      两者的补救办法相反（换楼号 vs 装依赖/换机器）。
    ★ **读**用注册表原样（`registry_profiles`），**写/可操作性**用
      `registry_listed` —— 这一处不对称是有意的：j6 的占位条目**档案读得到**
      （那是注册表里的事实），但它源图不在本机，所以列不出来、也写不了。
      两句话各说各的事实，比合成一个含糊的"存在/不存在"更准。
    """
    batch = _buildings(cfg) / name / "profile.json"
    if batch.is_file():
        obj, err = _opt_json(batch)
        if err:
            raise ApiError(500, "profile_corrupt",
                           "这栋楼档案损坏（JSON 解析失败）：%s" % batch.name,
                           {"file": str(batch), "error": err})
        return obj
    override = _data(cfg) / ("%s-profile.json" % name)
    if override.is_file():
        obj, err = _opt_json(override)
        if err:
            raise ApiError(500, "profile_corrupt",
                           "覆盖档案损坏（JSON 解析失败）：%s" % override.name,
                           {"file": str(override), "error": err})
        return obj
    reg, rerr = registry_profiles(cfg)
    if reg is None:
        # ★ 措辞要**同时覆盖两种可能**：名字真的不存在，或者它在注册表里而本进程
        #   读不到。回 404 = 断言"没有这栋楼"，可我们**没查过**（铁律 16 的
        #   「量不到 ≠ 没有」）；回 503 = 说得出补救办法（装依赖 / 换机器）。
        raise ApiError(503, "registry_unavailable",
                       "拿不到注册表，**无法确认**「%s」是否存在（本机缺 recognizer "
                       "的依赖）：%s" % (name, rerr),
                       {"name": name, "error": rerr})
    if name in reg:
        return _norm(_asdict(reg[name]))
    raise not_found("没有这栋楼：%s" % name, building=name)


def _asdict(obj: Any) -> Any:
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj


def _norm(o: Any) -> Any:
    """元组 → 列表（JSON 里没有元组），其余原样。照 `control.py:_norm`。"""
    if isinstance(o, (tuple, list)):
        return [_norm(x) for x in o]
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    return o


def put_profile(cfg: Settings, name: str, obj: dict) -> str:
    """写档案。

    批次楼：**合并写**（只覆盖前端传回的键，别丢高级字段）。
      ★ 合并写的副作用是**键永远删不掉** —— 前端把「层序倒置」的 floor_ys 清空，
        旧值会被原样搬回来，「留空=不启用」于是失效。约定 **`null` = 显式关闭**：
        消费端一律 `cfg.get(k)` 真值判断，null 与"键不存在"完全等价（已逐处核对）。
      ★ 判空用 `is None` 而不是假值：`glb_windows=false` 必须保留。
    注册表楼：写覆盖档案 `data/<名>-profile.json`（**不改** `recognizer/profiles/*.py`）。
    """
    if not building_exists(cfg, name):
        raise not_found("没有这栋楼：%s（写档案不会替你把楼建出来）" % name, building=name)
    batch = _buildings(cfg) / name / "profile.json"
    if batch.is_file():
        existing, _err = _opt_json(batch)
        merged = {**existing, **obj}
        for k in [k for k, v in merged.items() if v is None]:
            del merged[k]
        target = batch
    else:
        target = _data(cfg) / ("%s-profile.json" % name)
        existing, _err = _opt_json(target)
        merged = obj
    _archive_then_write(target, name, existing, merged)
    return str(target)


def _archive_then_write(target: Path, name: str, old: dict, new: dict) -> None:
    """覆盖档案前**留档 + 逐键记账**，然后才原子写。

    ★ 为什么（2026-09-26 追出来的教训）：c006 的 `glb_windows` 在 09-26 09:13:47 被从
      `false` 翻成 `true`（单键改动，Δ = 恰好 1 字节），而**全仓没有任何代码给这个键赋值**
      ⇒ 只能是"被往 profile.json 里写"改的。可这条路当时**就地覆盖、无备份、无日志**，
      于是"谁翻的"**在盘上查不出来** —— 查不出来本身才是缺陷：交付件不可追、不可回滚。
    ★ 留档落点用本仓既有纪律，`backend/paths.py` 里写明的 `.orig/before_<用途>_<时间戳>/`
      （只增不减；`backend/checks/builtin.py` 出问题时也指名让用户去 `.orig/` 比对）。
    ★ 日志只记**变了的键**（`键: 旧 → 新`）—— 把整份档案抄进日志没人看，要的是"这一次改了哪几个"。
    """
    changed = {k: (old.get(k, "<缺>"), new.get(k, "<删>"))
               for k in set(old) | set(new) if old.get(k) != new.get(k)}
    if not changed:
        return
    if target.is_file():
        import shutil
        import time
        d = target.parent / ".orig" / ("before_控制台改档案_%s" % time.strftime("%Y%m%d_%H%M%S"))
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, d / target.name)
        log.warning("改档案 %s：%d 个键变了；旧档 → %s", name, len(changed),
                    str(d.relative_to(target.parent.parent)))
    else:
        log.warning("改档案 %s：新建（盘上没有旧档）", name)
    for k in sorted(changed):
        log.warning("  改档案 %s · %s: %r → %r", name, k, changed[k][0], changed[k][1])
    _write_json(target, new)


def spec_path(cfg: Settings, name: str) -> Path:
    """这栋楼的规格文件在哪儿 —— **只有这一份实现**。

    ★ 规则：**规格跟着产物根走**（`dirname(out_dir)/spec.json`），也就是
      `console_meta.PIPELINE` 里 `recognize` 阶段那一件产物 `spec.json` 的位置。
      ⇒ 列表页的 `spec` 徽章、流程页的 `recognize` 产物、规格表单读写，
        **三处由构造保证一致**（都走 `_resolve_artifact`）。
    ★ 8130 那版这里有**两条**规则：`get_spec`/`put_spec` 按「是不是注册表楼」
      （`name in reg` → `data/spec.json`），而 `_spec_path`（另一个函数）按
      「parent 在不在 `data/buildings` 里」。对 lihua 两者恰好同值，所以从没暴露；
      但它们不是同一条判据 —— 那种"恰好同值"正是铁律 18 说的东西。
    ★ lihua 那种注册表楼：out_dir = `data/floors` ⇒ parent = `data`
      ⇒ `data/spec.json`（与 8130 落在同一个文件上，行为不变）。
    """
    return _resolve_artifact(cfg, name, "spec.json")


def get_spec(cfg: Settings, name: str) -> dict:
    """读规格。**没有这个文件回空对象**（不是 404）—— 见下面那段。"""
    if not building_exists(cfg, name):
        raise not_found("没有这栋楼：%s" % name, building=name)
    sp = spec_path(cfg, name)
    if not sp.is_file():
        # ★ 回空对象而不是 404：规格"还没有"是常态（识别时按档案 style 生成），
        #   而且这一屏是个表单 —— 404 会让表单整个打不开。前端据 `exists` 说话。
        return {}
    obj, err = _opt_json(sp)
    if err:
        raise ApiError(500, "spec_corrupt",
                       "规格文件损坏（JSON 解析失败）：%s" % sp.name,
                       {"file": str(sp), "error": err})
    return obj if isinstance(obj, dict) else {}


def put_spec(cfg: Settings, name: str, obj: dict) -> str:
    if not building_exists(cfg, name):
        raise not_found("没有这栋楼：%s（写规格不会替你把楼建出来）" % name, building=name)
    sp = spec_path(cfg, name)
    sp.parent.mkdir(parents=True, exist_ok=True)
    _write_json(sp, obj)
    return str(sp)


def _write_json(path: Path, obj: Any) -> None:
    """原子写（临时文件 + `os.replace`）。

    ★ 为什么不 `open(...,'w'); json.dump(...)`：直写中途失败会留下**半截 JSON**，
      而本仓对"产物损坏"的报错是有的（`read_json` 那一支），说明这事真发生过。
      原子写让"写了一半"在盘上不存在。
    """
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ── 楼层资产（图 / DXF）────────────────────────────────────────────

def _cache_get(key: tuple) -> bytes | None:
    hit = _FLOOR_CACHE.get(key)
    if hit is not None:
        _FLOOR_CACHE.move_to_end(key)
    return hit


def _cache_put(key: tuple, value: bytes) -> None:
    _FLOOR_CACHE[key] = value
    _FLOOR_CACHE.move_to_end(key)
    while len(_FLOOR_CACHE) > _CACHE_MAX:
        _FLOOR_CACHE.popitem(last=False)


def floor_png(cfg: Settings, name: str, F: int) -> bytes | None:
    """该楼 F 层的识别平面图（墙黑/门红/柱蓝/梯绿）。取不到回 None。

    ★ 先发**构建期预渲染**的 `plans/recog_floor{F}.png`，只在缺失或比它的
      **真输入**（源 DXF / profile.json）旧时才现算 —— 两条路是**同一个函数**
      产出的（`vision.render_floor.render_floor_png`），内容一致，区别只在哪儿渲染：
        · 现算要 ezdxf + matplotlib，服务器（`GYM3D_COMPUTE=0`）刻意不装 ⇒ 必 500；
        · 预渲染图是文件，服务器只要会发文件。
    ★ 判据**不含** `floors/*.json`：`render_floor_png` 全程读 DXF + profile、
      **不读**楼层 JSON，拿它当判据会把本来有效的预渲染图一律判成旧的而退回现算
      —— 那正是这个功能要解决的 500。与 `prerender_floor_png.is_fresh()` 同一套判据。
    """
    key = (name, F, "png")
    hit = _cache_get(key)
    if hit is not None:
        return hit
    _ensure_console_paths(cfg)
    import run_step

    p = run_step.load_profile(name)
    pre = Path(p.out_dir).parent / "plans" / ("recog_floor%d.png" % F)
    deps = [p.dxf, str(_buildings(cfg) / name / "profile.json")]
    try:
        t_pre = os.path.getmtime(pre)
        fresh = all((not os.path.exists(d)) or t_pre >= os.path.getmtime(d) for d in deps)
    except OSError:
        fresh = False
    if fresh:
        data = pre.read_bytes()
    else:
        from vision.render_floor import render_floor_png

        data = render_floor_png(p, F)
    _cache_put(key, data)
    return data


def _entity_points(e: Any) -> list | None:
    """从 DXF 实体提取定位点（给 `floor_of` 判楼层用）。照 `control.py`。"""
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


def floor_dxf(cfg: Settings, name: str, F: int) -> bytes | None:
    """把源 DXF 拆出 F 层实体写独立 DXF，返回 bytes。该层没有实体则 None。

    ★ 这条要 ezdxf + `recognizer.profile.floor_of` —— 服务器上装不了。
      **懒 import 在这里**（不是模块级），于是缺依赖时是"这一条路走不通"，
      而不是"整个管理台起不来"。缺依赖时让 ImportError 冒到路由，
      由路由换成 503（不许 500 —— 500 说的是"我们的错"，而这是"这台机器没装"）。
    """
    key = (name, F, "dxf")
    hit = _cache_get(key)
    if hit is not None:
        return hit
    _ensure_console_paths(cfg)
    import ezdxf
    import run_step
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
        cx = sum(x for x, _y in pts) / len(pts)
        cy = sum(y for _x, y in pts) / len(pts)
        if floor_of(p, cx, cy) != F:
            continue
        msp.add_entity(e.copy())
        n += 1
    if n == 0:
        return None
    import tempfile

    fd, tmp = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    try:
        out.saveas(tmp)
        data = Path(tmp).read_bytes()
    finally:
        # ★ 临时文件一定要清：`control.py` 那版是 `delete=False` + 正常路径 remove，
        #   中途抛就留在盘上了。这里用 try/finally（清理失败也不影响返回值）。
        try:
            os.remove(tmp)
        except OSError:
            pass
    _cache_put(key, data)
    return data


# ── 元数据 / 阶段 / 执行 ───────────────────────────────────────────

def meta(cfg: Settings) -> dict:
    """参数表 + 阶段表 + 兜底默认值。**转发** `meta_source`，不自己求值。

    转发而不是重算的理由写在模块头：`meta_source` 是「本机实时 / 服务器读冻结」
    这两路的唯一实现。绕开它，服务器上首屏第一个请求就是 500。
    """
    return meta_source.load_meta(cfg)


def _stage(cfg: Settings, step: str) -> dict | None:
    for s in meta(cfg).get("pipeline") or []:
        if s.get("id") == step:
            return s
    return None


def runnable_ids(cfg: Settings) -> list[str]:
    """这一台机器上**能跑的**阶段 id。`compute=0` 时是空列表（投影已置 False）。"""
    return [s["id"] for s in (meta(cfg).get("pipeline") or []) if s.get("runnable")]


def stage_argv(cfg: Settings, name: str, step: str, windows: bool) -> list | None:
    """构造阶段的命令行（不含解释器）。None = 这个阶段不可跑（需命令行）。

    `recognize` / `glb` / `full` 继续走 `run_step.py` —— 它是「档案加载优先级 +
    输出路径覆盖」的唯一正确实现（批次楼写 `<名>/`，注册表楼写 `data/`），
    绕开它会**写错地方**。其余阶段直接调根目录脚本，参数来自阶段表的 `args` 模板。
    """
    if not NAME_RE.match(step or ""):
        raise bad_request("阶段 id 形状不对", step=step)
    st = _stage(cfg, step)
    if step in RUN_STEP_STEPS:
        argv = [str(_run_step(cfg)), name, step]
        return argv + (["windows"] if windows else [])
    if st is None or not st.get("runnable") or not st.get("script"):
        return None
    return [str(cfg.root.joinpath(*st["script"].split("/")))] + \
        [a.format(name=name) for a in (st.get("args") or [])]


def start_run(cfg: Settings, name: str, step: str, windows: bool) -> dict:
    """起一个阶段作业。回作业的公开形状（**不是结果**）。

    ★ 长活，一律走 `services.jobs`：真超时（`job_timeout_s`）＋真并发上限
      （`job_max_concurrency`，到顶回 **409 并点名**是谁占着）。**不裸挂 subprocess**
      —— 合并成一个进程之后，被卡住的是管着所有屏的那个进程。

    ★ 串行规则比 8130 更严，这是**有意的**：8130 的 `job_conflict` 只在
      「同楼」或「全仓阶段」时冲突，于是 `c001/thin` 与 `c002/thin` 会并发，
      实际并发度 2。现在全进程一个槽位（就是 `settings.job_max_concurrency=1`
      本来的意思）。代价写在屏幕上：409 的说明会点名是哪个作业占着。
    """
    if not building_exists(cfg, name):
        raise not_found("没有这栋楼：%s" % name, building=name)
    argv = stage_argv(cfg, name, step, windows)
    if argv is None:
        st = _stage(cfg, step) or {}
        if not st:
            raise bad_request("没有这个阶段：%s" % step, step=step)
        raise ApiError(409, "stage_not_runnable",
                       "「%s」不能从这里跑：%s" % (st.get("label", step),
                                                  st.get("why_manual") or "需走命令行"),
                       {"step": step, "why_manual": st.get("why_manual")})
    job = jobs.start(cfg, mode="console",
                     label="%s · %s" % (name, (st := _stage(cfg, step) or {}).get("label", step)),
                     argv=argv, cwd=cfg.root,
                     extra={"building": name, "step": step, "windows": bool(windows)})
    return job.public()


# ── 开关登记表（流程 / 判据）───────────────────────────────────────
#
# 这一节服务的是「哪些是公共流程、哪些是单独流程」这个问题：**事实源是
# `config/branches.json`**，不是代码里某张表。54 行开关，每行 `kind` 三档 ——
# `公共` = 全库走同一条规则；`单独` = 某条**支线**流程、必须逐栋决定（**这一批就是
# 「单独流程」**）；`死键` = 载入后无人读。
#
# ★★ 「单独 / 公共」这个判断**推不出来**，别拿取值分布去纠正它：登记表自己的
#    `_字段.kind` 记着实测 —— 两者不符 38/54 行（`cx` 96 栋里 94 个不同值却是公共，
#   `door_min_points` 95 栋全用同一个值却是单独）。它是**人写的语义判断**。
#
# 四条写在这里的规矩，都是本仓踩过的：
#
# 1. **本文件不 import `console_meta`** —— 与本节其余部分同一条理由：那一份有
#    live / frozen 两条路（`meta_source` 管着）。而登记表是**仓里的配置文件**，
#    两条路上都在、内容同一份 ⇒ 直读才是对的，绕过去反而会造出第二份判断。
# 2. **人写四列与现量列要分开报**（`AUTHORED_FIELDS` / `MEASURED_FIELDS`）。
#    前者**本文件就是事实源**（生成器 `_scratch/_gen_branches.py` 重跑时先读回它）；
#    后者每次重跑都重写 ⇒ 页面必须把它们标成**只读**，否则用户改的那一下会被
#    下一次重跑静默冲掉 —— 而「我改的没生效」与「我没改」在屏幕上长得一样。
# 3. **写盘只许动那四列，其余逐字节不许变**。用的是「读 → 改 → 同一个序列化器
#    重新 dump → 写字节」。这条**是量出来的、不是推的**：现行文件的
#    `json.loads → json.dumps(ensure_ascii=False, indent=1)` 往返实测**逐字节相同**
#    （96683 B / sha12 `b4cd30bcbbe6`，2026-09-26 实测）⇒ 写回的差异**恰好**等于
#    我声明改的那一处（铁律 69/78）。
# 4. **落地前留档，落地后自验，验不过回滚并吵出来**（铁律 35：回滚失败与回滚成功，
#    差别必须落在退出码/状态码上，不能只印一句「已还原」）。
#
# ★ 缓存：改完这个文件**不用**手动清 `console_meta` 的 `self_check` 缓存 ——
#   `self_check_cached()` 自己盯着 `_registry_stamp()`（mtime_ns + size）。
#   这句话写在这里，是因为「谁负责失效」是本仓反复出错的地方（铁律 22）。

#: **人写的四列** —— 这个文件自己说了算，生成器重跑会先读回它。
AUTHORED_FIELDS = ("label", "kind", "step", "why")
#: `kind` 的合法取值。生成器有一份同名判断（`_gen_branches.py:KIND_OK`）；
#: 两份**同时**存在是有意的：这里拦"用户从页面上打字打错"，那边拦"盘上被手改坏"。
#: ★ 但它俩必须**一致** —— 不一致时页面会放行一个生成器拒收的值，
#:   而生成器拒收是**拒绝写盘**（退出码 2），屏幕上是"保存成功了、表却没变"。
KIND_OK = ("公共", "单独", "死键")


def branches_path(cfg: Settings) -> Path:
    """`config/branches.json` 的位置。取路径**只有这一处**（拼错就是一个必然 404 的地址）。"""
    return cfg.root / "config" / "branches.json"


def _same_serializer(obj: Any) -> bytes:
    """把登记表序列化回**与生成器同一个形态**，让往返可以逐字节比对。

    这里的 `ensure_ascii=False, indent=1` 是**抄生成器的**（`_gen_branches.py` 里
    `OUT.write_bytes(json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))`）。
    改这里就必须同步改那边 —— 两边不一致时，写回的字节与生成器写回的形态**长得
    完全一样**（都是合法 JSON），只有逐字节比对才看得出来。
    """
    return json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")


def branch_table(cfg: Settings) -> dict:
    """读登记表 → 页面要的整块。

    ★ **读不到要吵**（503），不许回一张空表：`rows: []` 与「这 54 行一条都不剩」
      在屏幕上长得一模一样，而结论相反（铁律 16）。
    ★ `counts` 里的分母**从实物数**，不写死 —— 本仓记过许多次「写死的条数过期了
      不报错」（铁律 50）。
    """
    import hashlib

    p = branches_path(cfg)
    if not p.is_file():
        raise ApiError(503, ERR_UPSTREAM,
                       "开关登记表不在：%s。它是**仓里的配置文件**，"
                       "缺了就是这份部署不完整 —— 不是「一条开关都没有」。" % p,
                       {"path": str(p), "hint": "确认 config/branches.json 已随仓部署"})
    try:
        raw = p.read_bytes()
        obj = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ApiError(503, ERR_UPSTREAM,
                       "开关登记表读不了（%s: %s）。这是**量具坏了**，"
                       "不是「没有开关」。" % (type(ex).__name__, ex),
                       {"path": str(p)}) from ex

    rows = obj.get("开关")
    if not isinstance(rows, list):
        raise ApiError(503, ERR_UPSTREAM,
                       "开关登记表里 `开关` 不是数组（是 %s）⇒ 版式对不上，"
                       "页面不作数。" % type(rows).__name__, {"path": str(p)})

    measured = sorted({k for r in rows if isinstance(r, dict) for k in r}
                      - set(AUTHORED_FIELDS) - {"key"})
    counts: dict[str, int] = {}
    for r in rows:
        if isinstance(r, dict):
            k = r.get("kind") or "(空)"
            counts[k] = counts.get(k, 0) + 1
    # ★ 别把 `死键` 读成「流程」：它载入后无人读，不属于任何一条流程。
    #   这一句同时给页面用（前端不许自己复述这个判断，铁律 one-judgement-many-implementations）。
    note = ("`kind=单独` 的就是「单独流程」—— 必须逐栋决定的那一批。"
            "⚠ 别读成「取值因楼而异」：那是**另一个量**（登记表自己实测两者不符 38/54 行）。"
            "`死键` 不属于任何流程（载入后无人读）。")
    return {
        "path": str(p),
        "sha12": hashlib.sha256(raw).hexdigest()[:12],
        "bytes": len(raw),
        "authored_fields": list(AUTHORED_FIELDS),
        "measured_fields": measured,
        "kinds": list(KIND_OK),
        "counts": counts,
        "total": len(rows),
        "rows": rows,
        "note": note,
    }


def put_branch(cfg: Settings, key: str, patch: dict) -> dict:
    """改登记表里**某一行的人写四列** → `{written, changed, sha_before, sha_after, backup}`。

    ★ 只认那四列，**多一个键就 400 并点名** —— 不静默丢弃。理由是这一屏的整个意义
      就是「用户改的能落地」：悄悄丢掉一个键，屏幕上写的是「已保存」，
      而盘上什么都没变（铁律 40 那一族的形状）。
    ★ 现量列**改不了**（生成器每次重跑都会重写它们）⇒ 传进来就是错的用法，同样点名。
    ★ 一个字段都没变 ⇒ **不写盘**（也就不动 mtime）。「保存成功了」与
      「这次保存没改任何东西」在屏幕上必须不是同一行字。
    """
    import hashlib
    import time

    p = branches_path(cfg)
    table = branch_table(cfg)                      # 顺带把「读不了」的处置复用一处
    rows = table["rows"]
    idx = next((i for i, r in enumerate(rows)
                if isinstance(r, dict) and r.get("key") == key), None)
    if idx is None:
        raise not_found("登记表里没有这个开关：%s" % key, key=key)

    bad_auth = sorted(set(patch) - set(AUTHORED_FIELDS))
    if bad_auth:
        raise bad_request(
            "只收人写四列（%s）；收到改不了的：%s。现量列由生成器每次重跑重写，"
            "页面上改它们会看起来成功了、其实下次就被冲掉。"
            % ("/".join(AUTHORED_FIELDS), "、".join(bad_auth)),
            rejected=bad_auth, editable=list(AUTHORED_FIELDS))

    row = rows[idx]
    changed: dict[str, list] = {}
    for f in AUTHORED_FIELDS:
        if f not in patch:
            continue
        v = patch[f]
        if not isinstance(v, str):
            raise bad_request("`%s` 要是字符串（收到 %s）" % (f, type(v).__name__),
                              field=f)
        v = v.strip()
        if f == "kind" and v not in KIND_OK:
            raise bad_request("`kind` 只认 %s（收到 %r）" % ("/".join(KIND_OK), v),
                              field="kind", allowed=list(KIND_OK))
        if f in ("label", "step", "kind") and not v:
            # ★ 四个都空 ⇒ 生成器会把这一行当成「没写过」而退回它的种子表
            #   （`_gen_branches.load_authored` 那句 `if not any(vals): continue`）。
            #   所以这三个**不许空**；`why` 可以为空。
            raise bad_request("`%s` 不许为空（四列全空会被生成器当成「这一行没写过」而退回种子表）"
                              % f, field=f)
        old = row.get(f)
        if old != v:
            changed[f] = [old, v]

    before = p.read_bytes()
    sha_before = hashlib.sha256(before).hexdigest()[:12]
    if not changed:
        return {"key": key, "written": False, "changed": {},
                "sha_before": sha_before, "sha_after": sha_before, "backup": None,
                "note": "一个字段都没变 ⇒ **没有写盘**（这份文件连 mtime 都没动）"}

    # ★ 留档：时间戳带秒，同名再撞就退一位（不覆盖别人刚留的那一份）。
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-page-" + stamp)
    n = 0
    while bak.exists():
        n += 1
        bak = p.with_name("%s.bak-page-%s-%d" % (p.name, stamp, n))
    bak.write_bytes(before)

    new_obj = json.loads(before.decode("utf-8"))   # 重新读一份，别改 `table` 里那份引用
    for r in new_obj["开关"]:
        if isinstance(r, dict) and r.get("key") == key:
            r.update({f: v[1] for f, v in changed.items()})
            break
    out = _same_serializer(new_obj)
    p.write_bytes(out)

    # ★ 自验两条一起：① 改的那一处**真的在**；② **除了它，其余逐字节相同**。
    #   只验①是不够的（写错整份也能让①成立）；只验②也是不够的（一处都没改时它照样绿）。
    #   ★ 验②是**往返证明**：把改回去的那一版再用**同一把尺子**序列化，与本趟起手的
    #     字节逐位比 —— 而不是「我比对了大小」。它与铁律 79 里那条修引擎的往返证明
    #     是同一个动作（那里的指纹是 23775/baaedc6fd8ce，这里是大 96 KB 的登记表）。
    verify_err = None
    try:
        back = json.loads(p.read_bytes().decode("utf-8"))
        got = next((r for r in back["开关"]
                    if isinstance(r, dict) and r.get("key") == key), None)
        ok_fields = got is not None and all(
            got.get(f) == v[1] for f, v in changed.items())
        probe = json.loads(p.read_bytes().decode("utf-8"))
        for r in probe["开关"]:
            if isinstance(r, dict) and r.get("key") == key:
                for f, v in changed.items():
                    r[f] = v[0]
                break
        ok_rest = _same_serializer(probe) == before
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        ok_fields = ok_rest = False
        verify_err = "%s: %s" % (type(ex).__name__, ex)

    if not (ok_fields and ok_rest):
        # 回滚。★ 回滚**自己也要验**：还原后必须与本趟起手的字节逐位相同，
        #   验不过就回一个说得出这件事的状态码（铁律 35）。
        try:
            p.write_bytes(before)
            rolled = p.read_bytes() == before
        except OSError:
            rolled = False
        raise ApiError(500, ERR_INTERNAL,
                       "写登记表后自验没过（改的那处=%s，其余逐字节未动=%s%s）⇒ 已回滚。"
                       "回滚本身：%s。" % (
                           ok_fields, ok_rest,
                           "" if verify_err is None else "，自验自身抛了 " + verify_err,
                           "成功" if rolled else "**也失败了**"),
                       {"key": key, "changed": changed, "rollback_ok": rolled,
                        "backup": str(bak)})

    return {"key": key, "written": True, "changed": changed,
            "sha_before": sha_before,
            "sha_after": hashlib.sha256(out).hexdigest()[:12],
            "backup": str(bak),
            "note": "只动了这一行的人写四列；现量列与其余 53 行逐字节未变（已自验）"}
