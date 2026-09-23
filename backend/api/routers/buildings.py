# -*- coding: utf-8 -*-
r"""楼栋数据域：清单 / 单栋详情 / 逐层几何 / 二进制产物（图、模型、源图）。

两处刻意的取舍：

1. **二进制一律 FileResponse，不 read_bytes。** GLB 单栋 2.3GB，
   读进内存就是一次自杀。FileResponse 走 sendfile/分块，并且支持 Range
   （starlette 已实现），前端拖动三维模型时才不会重下整个文件。
   上线后这些 URL 应当由 nginx 直接 sendfile 接管（见重构方案·后端前端.md），
   本路由是开发期的等价物。
2. **PNG 的 URL 带 .png 后缀**，但路由参数是整段 `{filename}` 再正则校验 ——
   FastAPI 的路径参数只能匹配**整段**，写 `/{floor}.png` 不会被解析成 int。
   用正则 fullmatch 反而更严：`floor(\d{1,2})\.png` 天然排除 `..` 和任意路径。
"""
import re

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..deps import BuildingName, FloorIndex, SettingsDep
from ..responses import ApiError, not_found, ok
from ..services import artifacts as A
from ..services.artifacts import FLOOR_PNG_RE

router = APIRouter(tags=["buildings"])

# ★ 正则从 artifacts 那份取，**不在这里另写一遍**：这条路由校验的文件名，
#   必须跟"盘上文件名"和"floors 接口回给前端的 URL"是同一个形状。
#   三份各写各的那次，坏的是 URL 那一份（永远是 400），而路由这份看不出来。
_PNG_RE = re.compile(FLOOR_PNG_RE)


def _floor_from_filename(filename: str) -> int:
    m = _PNG_RE.match(filename or "")
    if not m:
        raise ApiError(400, "bad_filename",
                       "只接受 floor<N>.png，收到 %r" % (filename,))
    return int(m.group(1))


@router.get("/buildings")
def list_buildings(cfg: SettingsDep) -> dict:
    rows = A.list_buildings(cfg.resolved_data_dir)
    return ok(rows, meta={"count": len(rows)})


@router.get("/buildings/{name}")
def one_building(name: BuildingName, cfg: SettingsDep) -> dict:
    dd = cfg.resolved_data_dir
    A.require_building(dd, name)
    return ok({
        "name": name,
        "profile": A.profile_public(dd, name),
        "artifacts": A.inventory(dd, name),
        "floors": A.floors_summary(dd, name),
        "spec": A.spec(dd, name),
    })


@router.get("/buildings/{name}/artifacts")
def building_artifacts(name: BuildingName, cfg: SettingsDep) -> dict:
    return ok(A.inventory(cfg.resolved_data_dir, name))


@router.get("/buildings/{name}/floors")
def floors(name: BuildingName, cfg: SettingsDep) -> dict:
    rows = A.floors_summary(cfg.resolved_data_dir, name)
    return ok(rows, meta={"count": len(rows)})


@router.get("/buildings/{name}/floors/{floor}")
def floor_detail(name: BuildingName, floor: FloorIndex, cfg: SettingsDep) -> dict:
    g = A.floor_full(cfg.resolved_data_dir, name, floor)
    return ok(g, meta={"building": name, "floor": floor})


@router.get("/buildings/{name}/rooms")
def building_rooms(name: BuildingName, cfg: SettingsDep) -> dict:
    rows = A.rooms(cfg.resolved_data_dir, name)
    per: dict[int, int] = {}
    for r in rows:
        per[r.get("floor")] = per.get(r.get("floor"), 0) + 1
    return ok(rows, meta={"count": len(rows),
                          "per_floor": {str(k): v for k, v in sorted(
                              per.items(), key=lambda kv: (kv[0] is None, kv[0]))}})


@router.get("/buildings/{name}/spec")
def building_spec(name: BuildingName, cfg: SettingsDep) -> dict:
    return ok(A.spec(cfg.resolved_data_dir, name))


@router.get("/buildings/{name}/profile")
def building_profile(name: BuildingName, cfg: SettingsDep) -> dict:
    return ok(A.profile_public(cfg.resolved_data_dir, name))


# ── 二进制 ────────────────────────────────────────────────────────

@router.get("/buildings/{name}/cad/{filename}")
def cad_png(name: BuildingName, filename: str, cfg: SettingsDep) -> FileResponse:
    """CAD 忠实渲染 —— 原图长什么样。后台的"看图"左栏。"""
    F = _floor_from_filename(filename)
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "cad", F)
    return FileResponse(p, media_type=mt)


@router.get("/buildings/{name}/plan/{filename}")
def plan_png(name: BuildingName, filename: str, cfg: SettingsDep) -> FileResponse:
    """识别结果图 —— 认成了什么样。和 CAD 原图并排看，差异一眼可见。"""
    F = _floor_from_filename(filename)
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "plan", F)
    return FileResponse(p, media_type=mt)


@router.get("/buildings/{name}/model.glb")
def model_glb(name: BuildingName, cfg: SettingsDep) -> FileResponse:
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "model")
    return FileResponse(p, media_type=mt)


@router.get("/buildings/{name}/source.dxf")
def source_dxf(name: BuildingName, cfg: SettingsDep) -> FileResponse:
    """源图。只在本机（dxf_dir 配了、文件在）才有 —— 服务器上明确回 404 并说明原因。"""
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "dxf")
    return FileResponse(p, media_type=mt,
                        filename=p.name)
