# -*- coding: utf-8 -*-
"""`/api/meta` 的数据来源：开发机实时求值，服务器读冻结产物。

为什么要分两路
--------------
`console_meta.spec_defaults()` 为了「不复制一份默认值」会在调用期 import
`build_standard_glb` —— 于是拖进 trimesh / numpy / mapbox_earcut / shapely。
这在本机没问题，在**刻意不装重依赖**的服务器 venv 上必炸，而 `/api/meta`
是控制台首屏第一个请求 —— 不处理就是首屏 500 白屏。

所以：
    settings.compute = 1  → 实时求值（权威真值）；失败回退冻结产物并告警
    settings.compute = 0  → 只读 data/_meta/console_meta.json（构建期冻结）

`compute=0` 时做**字段白名单投影**：去掉每个阶段的 `script` / `args`，
`runnable` 统一置空。阶段表照常显示「做过没有」，只是没有运行按钮 ——
前端因此不需要为两种模式写两套渲染逻辑。

本模块在模块级只 import 标准库 + settings，可在只服务 venv 里安全导入。
"""
import json
import logging
from typing import Any

from ..settings import Settings, get_settings

log = logging.getLogger("gym3d.meta")

#: compute=0 投影时从阶段定义里摘掉的字段（会泄漏本机路径/命令行）
_STRIPPED_STAGE_KEYS = ("script", "args")

META_RELPATH = "_meta/console_meta.json"

#: `/api/meta` 载荷的顶层键（**不含**传输标记）—— **这个元组的唯一出处就在这里**，
#: `freeze_meta.py` 的构建期门禁拿它去核 `build_payload()`。
#: ★ 为什么要一个声明：这份载荷在**三个地方**各手抄过一份
#:   （这里是活的；`freeze_meta.build_payload()` 是冻结那份；`backend/web/control.py`
#:    retired 的 8130 那份）。手抄的份数一多，**漏一个字段是不报错的** ——
#:   屏幕上「这个字段本来就没有」与「这一份没带」长得一样（铁律 16）。
#:   所以：一份活的 + 一份冻结的，两边都对着这个元组核，差一个键就报出来。
#: ★ **传输标记不在这个元组里，而且两条路各有一个**：活的由 `load_meta` 补
#:   `_source="live"`，冻结的由 `freeze_meta` 补 `_frozen={...}`
#:   （`project_for_service` 会把它剥掉）。核键集时要把它们单独认出来 ——
#:   否则「多了一个 `_source`」会被报成契约不符（实测第一版就这么写的，假红）。
META_PAYLOAD_KEYS = ("profile", "spec", "styleKeys", "pipeline",
                     "specDefaults", "runnable", "selfCheck")

#: 允许出现在载荷顶层、但**不属于**上面契约的传输标记。
META_TRANSPORT_KEYS = ("_source", "_frozen")


class MetaUnavailable(RuntimeError):
    """冻结元数据缺失或损坏 —— 服务器上这是**部署缺陷**，不该静默降级。

    宁可 503 报清楚「没冻结」，也不要返回半份数据让前端白屏且无从排查。
    """


def _frozen_path(settings: Settings):
    return settings.resolved_data_dir / META_RELPATH


def _read_frozen(settings: Settings) -> dict[str, Any]:
    path = _frozen_path(settings)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise MetaUnavailable(
            "缺少冻结元数据 %s。请在**本机**（有全套依赖的机器）跑一次 "
            "`python freeze_meta.py`，再把 data/_meta/ 一起同步到服务器。" % path
        ) from exc
    except (OSError, ValueError) as exc:
        raise MetaUnavailable("冻结元数据 %s 读取失败: %s" % (path, exc)) from exc


def _self_check(console_meta) -> dict[str, Any]:
    """取启动自检的**结构化**结论；**取不到也要带回一栏**（不许静默消失）。

    ★ 为什么它必须在这里、而不是只往服务器 stderr 印：用户第 5 条要的是
      「写在后台、我后面能修改」—— 那「哪些键改了生不生效」就必须**在页面上看得见**。
      判据印在日志里，等于用户手上没有它（本仓铁律 46 的同族：结论到不了该到的地方）。
    ★ 为什么失败**不往上抛**：抛出去会被 `load_meta` 当成「实时求值失败」⇒
      整页回退冻结产物 —— 那是**一个自检坏掉把整页拖下水**，比它要报的问题更糟。
      所以这里自吞，但**不静默**：错误原文进 `selfCheck`，页面上是「没量到」，
      与「量到且干净」不是同一行字（铁律 16）。
    """
    try:
        return console_meta.self_check_cached()
    except Exception as exc:  # noqa: BLE001 — 见 docstring：不抛，但必须留痕
        return {"状态": "读失败",
                "错误": "%s: %s" % (type(exc).__name__, exc),
                "含义": "启动自检这一趟**没跑起来**，不是「元数据干净」"}


def _live() -> dict[str, Any]:
    """本机实时求值：直接问 console_meta。

    只在 compute=1 时调用。重依赖（trimesh 等）在这里、且只在这里被拖进来。
    """
    import os
    import sys

    web_dir = str(_repo_root() / "backend" / "web")
    if web_dir not in sys.path:
        sys.path.insert(0, web_dir)
    import console_meta  # noqa: PLC0415 — 刻意延迟，服务器上不该走到这

    payload = {
        "profile": console_meta.PROFILE_GROUPS,
        "spec": console_meta.SPEC_GROUPS,
        "styleKeys": console_meta.STYLE_KEYS,
        "pipeline": console_meta.PIPELINE,
        "specDefaults": console_meta.spec_defaults(),
        "runnable": console_meta.runnable_ids(),
        # 判据的结论跟判据一起上页面（见 `_self_check`）。
        "selfCheck": _self_check(console_meta),
    }
    # 与声明核对。**只告警、不抛**：抛出去会被 `load_meta` 当成「实时求值失败」
    # 整页回退冻结产物 —— 一个字段对不上不该把整页拖下水。
    # 真正拦得住的地方是构建期（`freeze_meta.gate()` 里那条判据），这里是同一份
    # 契约的运行时那一半：两边都对着同一个元组核，才叫「一个判断一处声明」。
    if tuple(payload) != META_PAYLOAD_KEYS:
        log.warning(
            "/api/meta 的顶层键与 META_PAYLOAD_KEYS 不一致：实际 %s，声明 %s。"
            "（漏字段是不报错的 —— 页面上「本来就没有」与「这份没带」同形，"
            "所以这一句必须出声。）",
            tuple(payload), META_PAYLOAD_KEYS,
        )
    return payload


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[3]


def project_for_service(payload: dict[str, Any]) -> dict[str, Any]:
    """只服务模式的投影：摘掉能执行/能泄漏本机信息的字段。纯函数，便于单测。"""
    out = {k: v for k, v in payload.items() if k != "_frozen"}

    stages = []
    for stage in out.get("pipeline") or []:
        clean = {k: v for k, v in stage.items() if k not in _STRIPPED_STAGE_KEYS}
        clean["runnable"] = False      # 与顶层 runnable 空列表保持一致
        stages.append(clean)
    out["pipeline"] = stages
    out["runnable"] = []
    return out


def load_meta(settings: Settings | None = None) -> dict[str, Any]:
    """返回 `GET /api/meta` 的 data 字段（含来源标记 `_source`）。

    ★ `_source` 是 `"live"` 或 `"frozen"`，**必须带着**：下面那条回退是**静默的**
      （只写一行日志），而投影后的结果与实时那份在屏幕上分不开的部分正是最要紧的 ——
      `project_for_service` 会把 `runnable` 置成空列表，于是
      「实时求值、但这台机器一条都不可跑」与「实时求值**失败**、回退到冻结产物」
      这两件事在屏幕上同形。前者是事实，后者是故障。
      ⇒ 不靠 `runnable` 空不空去猜（那是代理判据，铁律 18：自洽的数不是证据），
        在**产生这个数的地方**把它标出来。
    """
    settings = settings or get_settings()

    if settings.compute:
        try:
            out = _live()
        except Exception as exc:  # noqa: BLE001 — 回退是有意的，但必须留下痕迹
            log.warning(
                "GYM3D_COMPUTE=1 但实时求值失败（%s: %s），回退冻结产物。"
                "若这是本机，说明 console_meta 或建模层有问题；"
                "若是服务器，说明 GYM3D_COMPUTE 该设成 0。",
                type(exc).__name__, exc,
            )
        else:
            out["_source"] = "live"
            return out

    out = project_for_service(_read_frozen(settings))
    out["_source"] = "frozen"
    return out


def provenance(settings: Settings | None = None) -> dict[str, Any] | None:
    """冻结产物的生成信息（给 /api/health 与排障用）；无产物返回 None。"""
    settings = settings or get_settings()
    try:
        return _read_frozen(settings).get("_frozen")
    except MetaUnavailable:
        return None
