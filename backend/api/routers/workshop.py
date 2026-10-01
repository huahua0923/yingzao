# -*- coding: utf-8 -*-
"""作业台数据域（原 `_scratch/_portal.py` 的 8144 页面，2026-09-25 收编进管理台）。

原页面是"上传（CAD/外观图）＋ 看结论 + 一键生产"三件事；这里一一对应，
但**页面本身不在这儿** —— 本进程只出 JSON 与文件，界面是
`frontend/admin/js/views/workshop.js`（原生视图，不是 iframe）。

★ 写/执行只有两条，都挂 `ComputeDep`（既有闸门，不另造第二套）：
    · `POST /workshop/upload` —— 往 `_inbox/` 落文件
    · `POST /workshop/run`    —— 起一个长活（`_system.py` / `_ref_import.py`）
  非回环来源一律 403（`deps.exec_denied_reason` 一处判定），这是本轮合并
  「局域网只读」的落地。只读的几条 GET 在局域网上照常可用。

★ **`/svc` 不搬**：它原先唯一的作用是把 8123/8130 两个子服务拉起来，
  那两个现在就在本进程里（`/building.html` 与 `#/console`）。
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response

from ..authz import require_cap
from ..deps import ComputeDep, SettingsDep
from ..responses import not_found, ok
from ..services import jobs, workshop

router = APIRouter(tags=["workshop"])

# ★ 本文件的路由**全部是搭建方专属**。
#   用户原话把搭建方的能力说成「输入 CAD 图 → 生成相关的东西 → 对流程进行管理」。
#   三个非搭建方角色里，回线管理员也有 `edit`（**限管线域**）⇒ 这里**不能**挂
#   `require_cap("edit")`（它不带范围），否则一个回线管理员就能跑建模管道。
#   只有 builder 的能力集里有 `manage`。
#   ★ 与 `ComputeDep` 是**叠加**（两条各自独立）：执行面闸答"这台进程许不许跑"，
#     权限面闸答"这个人许不许"。两个问题都要答，缺一条就是漏。
BUILDER_ONLY = [Depends(require_cap("manage"))]



# ── 只读 ──────────────────────────────────────────────────────────

@router.get("/workshop/status", dependencies=BUILDER_ONLY)
def ws_status(cfg: SettingsDep) -> dict:
    """楼栋状态表 + 两个队列的计数 + 正在跑的作业。

    ★ 每一列都可能**量不到**（没有 GLB 的楼 `glb_mb=null`、没跑过门禁的楼
      `qa_errors=null`）—— `null` 与 `0` 的差别由前端负责说清楚，
      服务端不许把量不到写成零（memory: gauge-coverage-invisible-in-summary）。
    """
    return ok(workshop.status(cfg))


@router.get("/workshop/refs", dependencies=BUILDER_ONLY)
def ws_refs(cfg: SettingsDep) -> dict:
    """外观图的两个队列：待入库（`_inbox/refs/`）与待判读（有图没结论的楼）。"""
    return ok(workshop.refs_pending(cfg))


@router.get("/workshop/jobs", dependencies=BUILDER_ONLY)
def ws_jobs(cfg: SettingsDep, limit: int = Query(10, ge=1, le=50)) -> dict:
    """最近的作业（含进程重启前落盘的终态）。"""
    return ok(jobs.listing(cfg, limit))


@router.get("/workshop/jobs/{job_id}", dependencies=BUILDER_ONLY)
def ws_job(job_id: str, cfg: SettingsDep) -> dict:
    """一个作业的当前状态。★ 找不到回 404，**不许回一个 state=running 的空壳**
    —— 那会让前端永远轮询一个不存在的作业（原 `control.js:359` 那个形状）。"""
    rec = jobs.get(cfg, job_id)
    if rec is None:
        raise not_found("没有这个作业：%s" % job_id, job=job_id)
    return ok(rec)


@router.get("/workshop/refimg/{filename}", dependencies=BUILDER_ONLY)
def ws_refimg(filename: str, cfg: SettingsDep) -> FileResponse:
    """待入库队列里的原图 / 已入库图（按文件名找，两处目录都查）。"""
    hit = workshop.resolve_refimg(cfg, filename)
    if hit is None:
        raise not_found("没有这张图：%s" % filename, file=filename)
    path, ctype = hit
    return FileResponse(str(path), media_type=ctype)


@router.get("/workshop/preview/{building}/{filename}", dependencies=BUILDER_ONLY)
def ws_preview(building: str, filename: str, cfg: SettingsDep) -> FileResponse:
    """速览图（`dxf_plan_fast/floorN.png`）。楼号与文件名先过正则，再拼路径。"""
    path = workshop.resolve_preview(cfg, building, filename)
    if not path.is_file():
        raise not_found("没有这张速览图", building=building, file=filename)
    return FileResponse(str(path), media_type="image/png")


@router.get("/workshop/task/{filename}", dependencies=BUILDER_ONLY)
def ws_task(filename: str, cfg: SettingsDep) -> Response:
    """给智能体的任务单（`_qa/tasks/<楼>.md`），原样出文本。

    ★ 用 `text/plain` 而不是原 8144 那样包成 `<pre>` 的 HTML：这一份内容是
      **产物文本**，让浏览器按文本渲染，就不需要我们把产物拼进 HTML 里
      （本仓对"产物内容当代码执行"是有戒心的，见 `dom.js` 的注释）。
    """
    path = workshop.resolve_task(cfg, filename)
    if not path.is_file():
        raise not_found("没有这份任务单", file=filename)
    with open(path, encoding="utf-8", errors="replace") as fh:
        return Response(content=fh.read(), media_type="text/plain; charset=utf-8")


@router.get("/workshop/su/{filename}", dependencies=BUILDER_ONLY)
def ws_su(filename: str, cfg: SettingsDep) -> FileResponse:
    """SU 复核页及其同名资源（`_scratch/su_jobs/`，脚本产出的本机产物）。

    ★ 已知面：`.html` 是按超文本托管的，与 8144 时期完全一样（页面里就是
      我们自己的复核页）。改这条要么动产出的页面、要么给它加 CSP，
      两件都不在本轮范围内 —— 写在这里是为了它是**已知**的，不是没想过。
    """
    path = workshop.resolve_su(cfg, filename)
    if not path.is_file():
        raise not_found("没有这个文件", file=filename)
    return FileResponse(str(path), media_type=workshop.refs.content_type_for(filename, "text/plain"))


# ── 写 / 执行（ComputeDep：非回环 403，`GYM3D_COMPUTE=0` 时也 403）────────

@router.post("/workshop/upload", dependencies=BUILDER_ONLY)
async def ws_upload(request: Request, cfg: ComputeDep,
                    name: str = Query("", max_length=200)) -> dict:
    """收一个上传（原 8144 `POST /upload`）。

    ★ 请求体是**文件本身**，不是 JSON —— 所以这里直接读原始 bytes，
      不走本仓那套 `{success,data,error,meta}` 的入参形状（**出参**仍然走信封）。
      文件名从查询参数来，落盘前过 `os.path.basename` + 长度检查 + 原子写。
    """
    body = await request.body()
    return ok(workshop.save_upload(cfg, name, body), meta={"bytes": len(body)})


@router.post("/workshop/run", dependencies=BUILDER_ONLY)
def ws_run(cfg: ComputeDep, mode: str = Query("", max_length=32)) -> dict:
    """起一个长活（原 8144 `POST /run`）。超时与并发由 `services.jobs` 统一管。

    ★ 冲突时回 **409 并点名**是哪个作业占着（不排队、不丢弃、不静默）。
    """
    return ok(workshop.start_run(cfg, mode), meta={"mode": mode})
