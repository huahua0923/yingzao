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

    return {
        "profile": console_meta.PROFILE_GROUPS,
        "spec": console_meta.SPEC_GROUPS,
        "styleKeys": console_meta.STYLE_KEYS,
        "pipeline": console_meta.PIPELINE,
        "specDefaults": console_meta.spec_defaults(),
        "runnable": console_meta.runnable_ids(),
    }


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
    """返回 `GET /api/meta` 的 data 字段。"""
    settings = settings or get_settings()

    if settings.compute:
        try:
            return _live()
        except Exception as exc:  # noqa: BLE001 — 回退是有意的，但必须留下痕迹
            log.warning(
                "GYM3D_COMPUTE=1 但实时求值失败（%s: %s），回退冻结产物。"
                "若这是本机，说明 console_meta 或建模层有问题；"
                "若是服务器，说明 GYM3D_COMPUTE 该设成 0。",
                type(exc).__name__, exc,
            )

    return project_for_service(_read_frozen(settings))


def provenance(settings: Settings | None = None) -> dict[str, Any] | None:
    """冻结产物的生成信息（给 /api/health 与排障用）；无产物返回 None。"""
    settings = settings or get_settings()
    try:
        return _read_frozen(settings).get("_frozen")
    except MetaUnavailable:
        return None
