# -*- coding: utf-8 -*-
"""建模后台 —— HTTP 层（FastAPI）。

**前后端分离**：本进程只出 JSON 与文件，不出 HTML。前端的静态页由
`frontend/admin/` 独立部署（开发期本进程顺手挂一份；生产期交给 nginx）。
分界就是一条：**后端不认识页面长什么样**，换前端不用改后端。

挂载顺序有讲究：
  1. `/api/*`  路由
  2. `/data/*` 产物静态目录（GLB 等大文件；上线后由 nginx sendfile 接管）
  3. `/`       前端静态页（**最后**挂，否则它会抢走 /api 的路径）

老控制台（backend/web/control.py:8130）先不动，靠双跑对拍验证一致后再下线
（见「重构方案·后端前端.md」Phase 2 / Phase 6）。本进程默认 8140，与它不撞车。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .responses import ERR_INTERNAL, ApiError, envelope, error_json
from .routers import analysis, buildings, checks, components, health
from .settings import get_settings

log = logging.getLogger("gym3d.api")


class FreshStatic(StaticFiles):
    """静态文件加一条 `Cache-Control: no-cache`。

    ★ 不加会怎样：Starlette 只发 `last-modified` / `etag`，**不发 Cache-Control**，
      于是浏览器按启发式规则自己决定能缓存多久。开发期就是"改完代码刷新看不到新版"
      —— 而屏幕上只是旧的那一句话，**没有任何报错**（本仓今晚实测：改完 checks.js，
      浏览器还在跑旧的行）。这类"改完没生效却不报错"正是本仓反复栽的那一族。

    ★ 用 `no-cache` 而不是 `no-store`：**允许**缓存，但每次都拿 ETag 回源确认，
      命中就是 304、几乎不花带宽。`no-store` 会把 8.6MB 的 GLB 每次都重下一遍。
      交付件（GLB / 图纸）也吃这条：重出过的模型绝不该被浏览器的旧副本盖住
      （见 memory: delivery-glb-content-staleness —— mtime 曾漏掉 28/48 栋）。
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


TITLE = "gym3d 建模后台"
DESC = ("全库 95 栋的 CAD 原图 / 识别结果 / 逐层交付几何 / 构件库 / 面积对账，"
        "统一成一个只读优先的 HTTP 接口。前后端分离：本服务只回 JSON 与文件。")


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title=TITLE, description=DESC, version="0.1.0",
                  docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")

    # CORS：dev 下前端可能跑在 Vite(5173)，需要跨域；prod 同源部署则为空。
    origins = cfg.cors_origin_list
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins,
                           allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    # ── 异常 → 统一信封 ──────────────────────────────────────────
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError) -> JSONResponse:
        return error_json(exc)

    @app.exception_handler(Exception)
    async def _boom(_req: Request, exc: Exception) -> JSONResponse:
        # 未预期的错误也要是信封形状，否则前端那条唯一的解析路径会摔在
        # HTML 报错页上。日志留全（服务端），响应只给一句话 + 类型名：
        # 栈信息可能带本机路径，不该进响应体。
        log.exception("未处理异常")
        return JSONResponse(status_code=500, content=envelope(error={
            "code": ERR_INTERNAL,
            "message": "服务内部错误：%s" % type(exc).__name__,
        }))

    # ── 路由 ────────────────────────────────────────────────────
    app.include_router(health.router, prefix=cfg.api_prefix)
    app.include_router(buildings.router, prefix=cfg.api_prefix)
    app.include_router(components.router, prefix=cfg.api_prefix)
    app.include_router(analysis.router, prefix=cfg.api_prefix)
    app.include_router(checks.router, prefix=cfg.api_prefix)

    # ── 产物静态目录（GLB 走这里；生产交给 nginx）──────────────
    bdir = _buildings_dir(cfg)
    if bdir.is_dir():
        app.mount("/data/buildings", FreshStatic(directory=str(bdir)), name="data")

    # ── 前端（最后挂）────────────────────────────────────────────
    # ★ 两条线分挂两个前缀，别把「管理」和「呈现」塞进同一个挂载点：
    #   · /site  = **前台**（frontend/site/）只读呈现 —— 给人看这栋楼长什么样
    #   · /      = **后台**（frontend/admin/）管理面 —— 改参数、跑阶段、核检查
    #   （生产期 nginx 里让 / 指前台、/admin 指后台，见重构方案；本机先各挂一个前缀，
    #    因为 `/` 已经指着 admin，临时改根会把正在验后台的页面全打断。）
    site = cfg.root / "frontend" / "site"
    if site.is_dir():
        # ★ 裸 `/site`（不带尾斜杠）**进不了**下面这个挂载点，会一路落到最后那个
        #   `/`（admin）挂载上，被它当成相对路径去找名为 `site` 的文件 ⇒
        #   `{"detail":"Not Found"}`（FastAPI 的 404 形状）。而 `/site` 正是文档与
        #   README 里写的**前台地址** —— 手敲进来、或从别处点过来，第一眼就是这个 404。
        #   （挂载自己的 `html=True` 确实会补尾斜杠，但**前提是请求先到它手上**；
        #    这里的问题恰恰是请求没到它手上。）
        #   ⇒ 登记一条**只做跳转**的路由，注册次序排在 `/` 挂载之前，先命中本尊。
        #   2026-09-24 实测：改前 `GET /site` = 404，改后 307 → `/site/` = 200。
        @app.get("/site", include_in_schema=False)
        def _site_slash() -> RedirectResponse:
            return RedirectResponse(url="/site/", status_code=307)

        app.mount("/site", FreshStatic(directory=str(site), html=True), name="site")

    front = cfg.root / "frontend" / "admin"
    if front.is_dir():
        # ★ 前台顶部那个「后台」链接指向 `/admin/`，而管理面**挂在 `/`**，
        #   `/admin/` 没人认 ⇒ 404 —— 两个半边之间**唯一的那条链接是死的**。
        #   ⇒ 跳回 `/`。**不能**把 admin 也挂到 `/admin`：那页的样式与脚本全是
        #   相对路径（`app.css`、`js/app.js`），换到 `/admin/` 下会连带全 404；
        #   而 307 之后浏览器地址栏是 `/`，相对路径仍旧落在根上，一个都不用改。
        @app.get("/admin", include_in_schema=False)
        @app.get("/admin/", include_in_schema=False)
        def _admin_slash() -> RedirectResponse:
            return RedirectResponse(url="/", status_code=307)

        app.mount("/", FreshStatic(directory=str(front), html=True), name="admin")
    else:
        @app.get("/")
        def _no_front() -> dict:
            return envelope(data={"hint": "前端目录 frontend/admin 不存在"},
                            error=None)

    return app


def _buildings_dir(cfg):
    return cfg.resolved_data_dir / "buildings"


app = create_app()
