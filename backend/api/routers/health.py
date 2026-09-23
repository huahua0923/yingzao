# -*- coding: utf-8 -*-
"""健康检查与能力公告。

`/api/capabilities` 不是装饰：前端要能**先问再画**。
只读服务器上"编辑/重跑"按钮应当消失，而不是点下去回 403 —— 403 是兜底，
不是交互设计。这个路由就是那条"先问"的通道。
"""
from fastapi import APIRouter

from ..deps import SettingsDep
from ..responses import ok
from ..services import artifacts, area_audit

router = APIRouter(tags=["health"])


@router.get("/health")
def health(cfg: SettingsDep) -> dict:
    """探活。**不回任何路径**（探活接口常常被放到公网）。"""
    bdir = artifacts.buildings_dir(cfg.resolved_data_dir)
    return ok({
        "ok": True,
        "env": cfg.env,
        "compute": cfg.compute,
        "data_dir_present": bdir.is_dir(),
        "frontend_dist_present": cfg.resolved_frontend_dist.is_dir(),
    })


@router.get("/capabilities")
def capabilities(cfg: SettingsDep) -> dict:
    """能做/不能做什么，以及为什么。前端的按钮开关直接读它。"""
    bdir = artifacts.buildings_dir(cfg.resolved_data_dir)
    n = len([d for d in bdir.iterdir()
             if d.is_dir() and (d / "profile.json").is_file()]) if bdir.is_dir() else 0
    log = area_audit.find_log(cfg.root)
    return ok({
        "compute": cfg.compute,
        # 一个开关，两条语义：读永远可用；写只在 compute=True 时开。
        "read_enabled": True,
        "write_enabled": cfg.compute,
        "write_disabled_reason": None if cfg.compute else
        "本进程以只读方式运行（GYM3D_COMPUTE=0）",
        "buildings": n,
        "dxf_dir_configured": bool(cfg.dxf_dir),
        "area_audit_snapshot": (log.name if log else None),
        # 检查引擎的产物目录在不在 —— 前端据此决定"检查"那一屏有没有东西可看。
        "checks_artifact_dir_present": (cfg.resolved_data_dir / "_meta" / "checks").is_dir(),
        "endpoints": {
            "read": ["/api/health", "/api/capabilities", "/api/buildings",
                     "/api/buildings/{name}", "/api/buildings/{name}/artifacts",
                     "/api/buildings/{name}/floors",
                     "/api/buildings/{name}/floors/{floor}",
                     "/api/buildings/{name}/rooms", "/api/buildings/{name}/spec",
                     # 逐层图的名字是 floor<N>.png —— 不是 {floor}.png，也别写 <N>.png。
                     # 这三份写法曾经各写各的，坏了 URL 那一份（见 artifacts.floor_png_name）。
                     "/api/buildings/{name}/cad/floor<N>.png",
                     "/api/buildings/{name}/plan/floor<N>.png",
                     "/api/buildings/{name}/model.glb",
                     "/api/buildings/{name}/source.dxf",
                     "/api/components", "/api/analysis/area",
                     "/api/checks/registry", "/api/checks/{building}"],
            "write": ["/api/analysis/area/refresh/{name}",
                      "/api/checks/{building}/run"],
        },
    })
