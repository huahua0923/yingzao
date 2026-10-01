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

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..authz import SEP, PrincipalDep, require_cap, visible
from ..deps import BuildingName, FloorIndex, SettingsDep
from ..responses import ApiError, not_found, ok
from ..services import artifacts as A
from ..services.artifacts import FLOOR_PNG_RE

router = APIRouter(tags=["buildings"])

# ── 权限：本文件是**批次 2** 的第一块（2026-10-01）──────────────────
#
# ★ 为什么闸挂在**每一条**路由上，而不是 `APIRouter(dependencies=[...])` 一次挂满：
#   本文件里两条口径**不同** —— `/buildings`（清单）要"过闸 ＋ 在响应里**过滤行**"
#   （一个只覆盖 c006 的账号仍要能打开页面，只是清单里只剩 c006）；
#   而 `/buildings/{name}` 这类是"整条**拒绝**"。挂 router 级会顺手把清单也整条拒掉，
#   症状是"普通管理员登进来一片空白"，而这与"他没有授权"在屏幕上一模一样。
#
# ★ `scope_param="name"` 靠的是 FastAPI 路由匹配后填好的 `path_params`：名字对不上
#   就是**缺键**，缺键按"不给看"处理 —— 不会像声明成函数参数那样被静默当查询参数
#   收下（那样范围检查恒不生效而屏幕上一切正常）。理由写在 `require_cap` 的 docstring。
VIEW_NAME = [Depends(require_cap("view", scope_param="name"))]
# 逐层：节点是**复合**的 `楼|层`（与 room_key `楼|层|房号` 同形），所以用 `node=`
# 而不是 `scope_param=` —— 后者只能取一个路径参数，取不到层号。
VIEW_FLOOR = [Depends(require_cap("view", node=lambda pp: pp["name"] + SEP + pp["floor"]))]

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


@router.get("/buildings", dependencies=[Depends(require_cap("view"))])
def list_buildings(cfg: SettingsDep, p: PrincipalDep) -> dict:
    """名册。**按范围过滤行** —— 不筛的话，只覆盖 c006 的账号也拿到 93 栋。

    ★ 这里返回的 `count` 是**过滤后**的条数，不是盘上的条数：前端拿它当分母
      （"你在 N 栋里有权限"）。回盘上的 93 会让一个只该看到 1 栋的人以为
      "还有 92 栋我没看到"，而那是**假信息**（他知道有 93 栋，是我多说的）。
    """
    all_rows = A.list_buildings(cfg.resolved_data_dir)
    rows = visible(p, all_rows, lambda r: r["name"])
    return ok(rows, meta={"count": len(rows), "total_on_disk": len(all_rows)})


@router.get("/buildings/{name}", dependencies=VIEW_NAME)
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


@router.get("/buildings/{name}/artifacts", dependencies=VIEW_NAME)
def building_artifacts(name: BuildingName, cfg: SettingsDep) -> dict:
    return ok(A.inventory(cfg.resolved_data_dir, name))


@router.get("/buildings/{name}/floors", dependencies=VIEW_NAME)
def floors(name: BuildingName, cfg: SettingsDep) -> dict:
    rows = A.floors_summary(cfg.resolved_data_dir, name)
    return ok(rows, meta={"count": len(rows)})


@router.get("/buildings/{name}/floors/{floor}", dependencies=VIEW_FLOOR)
def floor_detail(name: BuildingName, floor: FloorIndex, cfg: SettingsDep) -> dict:
    g = A.floor_full(cfg.resolved_data_dir, name, floor)
    return ok(g, meta={"building": name, "floor": floor})


@router.get("/buildings/{name}/rooms", dependencies=VIEW_NAME)
def building_rooms(name: BuildingName, cfg: SettingsDep) -> dict:
    rows = A.rooms(cfg.resolved_data_dir, name)
    per: dict[int, int] = {}
    for r in rows:
        per[r.get("floor")] = per.get(r.get("floor"), 0) + 1
    return ok(rows, meta={"count": len(rows),
                          "per_floor": {str(k): v for k, v in sorted(
                              per.items(), key=lambda kv: (kv[0] is None, kv[0]))}})


@router.get("/buildings/{name}/spec", dependencies=VIEW_NAME)
def building_spec(name: BuildingName, cfg: SettingsDep) -> dict:
    return ok(A.spec(cfg.resolved_data_dir, name))


@router.get("/buildings/{name}/profile", dependencies=VIEW_NAME)
def building_profile(name: BuildingName, cfg: SettingsDep) -> dict:
    return ok(A.profile_public(cfg.resolved_data_dir, name))


# ── 二进制 ────────────────────────────────────────────────────────

@router.get("/buildings/{name}/cad/{filename}", dependencies=VIEW_NAME)
def cad_png(name: BuildingName, filename: str, cfg: SettingsDep) -> FileResponse:
    """CAD 忠实渲染 —— 原图长什么样。后台的"看图"左栏。"""
    F = _floor_from_filename(filename)
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "cad", F)
    return FileResponse(p, media_type=mt)


@router.get("/buildings/{name}/plan/{filename}", dependencies=VIEW_NAME)
def plan_png(name: BuildingName, filename: str, cfg: SettingsDep) -> FileResponse:
    """识别结果图 —— 认成了什么样。和 CAD 原图并排看，差异一眼可见。"""
    F = _floor_from_filename(filename)
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "plan", F)
    return FileResponse(p, media_type=mt)


@router.get("/buildings/{name}/model.glb", dependencies=VIEW_NAME)
def model_glb(name: BuildingName, cfg: SettingsDep) -> FileResponse:
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "model")
    return FileResponse(p, media_type=mt)


@router.get("/buildings/{name}/source.dxf", dependencies=VIEW_NAME)
def source_dxf(name: BuildingName, cfg: SettingsDep) -> FileResponse:
    """源图。只在本机（dxf_dir 配了、文件在）才有 —— 服务器上明确回 404 并说明原因。"""
    p, mt = A.resolve_binary(cfg.resolved_data_dir, name, "dxf")
    return FileResponse(p, media_type=mt,
                        filename=p.name)
