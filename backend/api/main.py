# -*- coding: utf-8 -*-
"""建模后台 —— HTTP 层（FastAPI）。

**前后端分离**：本进程只出 JSON 与文件，不出 HTML。前端的静态页由
`frontend/admin/` 独立部署（开发期本进程顺手挂一份；生产期交给 nginx）。
分界就是一条：**后端不认识页面长什么样**，换前端不用改后端。

挂载顺序有讲究（下面这份就是**实际注册次序**，一边加东西一边核对它）：
  1. `/api/*`           路由
  2. `/data/buildings`  产物静态目录挂载，＋ 几条**窄到文件名**的 `/data/**` 路由
                        （`su/`、`floors/`、`spec.json`、根级 GLB）—— 页面真要的那几条，
                        一条不多；**绝不挂整个 `/data`**（那会端出 `_meta/**`、`refs/**`）
  3. `/building.html`   整栋三维页（原 8123 那个），**根级单文件路由** —— 它内部全是
                        文档相对路径，挂到子路径下会全 404
  4. `/site`            前台（`frontend/site/`）静态目录，只读呈现
  5. `/`                后台（`frontend/admin/`）静态页（**最后**挂，否则它会抢走 /api 的路径）

老端口**已全部退役**（P5，2026-09-25），能力都在**本进程**里 —— 是并进来，不是
「双跑对拍再下线」：8130 建模控制台 → `/api/console/*`；8123 房间 API →
`/api/rooms|floors|summary|path`；8144 作业台 → `/api/workshop/*`；
8155 图谱草稿页并掉（不留第二份面）→ `/api/kg/*`。
⇒ 还在盘上但**别起**：`backend/web/control.py`（8130，已被 `/api/console/*` 取代）、
`backend/db/serve_rooms_admin.py`（8124，**会写库**，不在本轮范围）。
⇒ 已经删掉（原文件留档在 `_scratch/_retired_20260925/`）：`backend/db/serve_rooms.py`、
`_scratch/_portal.py`、`_scratch/_kg_view.py`、`_scratch/_kg_view.html`。
起老服务 = 同一件事有两份执行面互不知情（本仓栽过：两个实例并存，谁也不报错）。
本进程默认 8140（端口/地址只在 settings 里，代码不写死数字）。
"""
from __future__ import annotations

import json
import logging
import re

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .authz import (AuthGate, PrincipalDep, ScopedStatic, assert_caps_gated,
                    audit_denied, cap_plane_gate, describe, require_cap,
                    require_scope, sees)
from .deps import AssetFileName, GlbFileName, assert_writes_gated
from .responses import (ERR_FORBIDDEN, ERR_INTERNAL, ERR_UPSTREAM, ApiError,
                        envelope, error_json, not_found)
from .routers import (analysis, auth, buildings, campus, checks, compare,
                      components, console, health, kg, portal, rooms,
                      sitecheck, tiles, workshop)
from .services import meta_source
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

    # ── 权限闸门（**必须在 CORS 之前 add**）───────────────────────
    # ★ Starlette 的 `add_middleware` 是 `insert(0, ...)`，展开时**后加的在外层**。
    #   所以"想让 CORS 在最外面（401/403 也带上 CORS 头，Vite 那边才读得到错误原因）"
    #   ⇒ 代码上就得**先 add AuthGate、后 add CORS**。顺序反了不会报错，
    #   只会让跨域下的 401 变成浏览器里的 `CORS error` —— 而真正的原因看不到。
    #   （prod 同源部署时 `origins` 为空、CORS 不挂，AuthGate 就是最外层。）
    app.add_middleware(AuthGate)

    # CORS：dev 下前端可能跑在 Vite(5173)，需要跨域；prod 同源部署则为空。
    origins = cfg.cors_origin_list
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins,
                           allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    # ── 异常 → 统一信封 ──────────────────────────────────────────
    @app.exception_handler(ApiError)
    async def _api_error(req: Request, exc: ApiError) -> JSONResponse:
        # ★ 拒绝的**第二条出口**（第一条是 `authz._deny`，走 `AuthGate` /
        #   `ScopedStatic` 那两条裸 ASGI 路，它们不抛异常、够不着这里）。
        #   两条出口都调同一个 `audit_denied`，判据只此一份。
        if exc.status in (401, 403, 503):
            audit_denied(req.scope, exc.status, exc.code)
        return error_json(exc)

    @app.exception_handler(meta_source.MetaUnavailable)
    async def _meta_gone(_req: Request, exc: meta_source.MetaUnavailable) -> JSONResponse:
        """参数表两路都取不到 ⇒ **503**，不是 500（`ERR_UPSTREAM`）。

        ★ 为什么在这里接、不在路由里接：读 meta 的有**三处**（`/console/meta`、
          `status` 的逐阶段表、构造阶段命令）—— 在调用处各 catch 一次就是
          "名单式判断"，**漏一处就退化成 500**（铁律 29：400/500 的分界是
          "谁的错"这个语义判断，语义判断只许有一个出处）。
        ★ 503 而不是 500：这是"这台机器上两份参数表都没有"（实时求值失败 ＋
          冻结产物不在），补救办法是补产物或配环境，不是"我们的代码坏了"。
        """
        return JSONResponse(status_code=503, content=envelope(error={
            "code": ERR_UPSTREAM,
            "message": "拿不到参数表（本机实时求值失败，且冻结产物也没有）：%s" % exc,
            "detail": {"hint": "本机跑 `python -u freeze_meta.py`"
                               "重建 data/_meta/console_meta.json"},
        }))

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
    # 账号与授权排在最前 —— 它是唯一一个**不依赖任何业务数据**的域：
    # PG 里只有 users/roles/grants/sessions，没有一栋楼。所以"服务器上先跑空壳"
    # 那一步（计划里的分层原则）跑的就是这一条线。
    app.include_router(auth.router, prefix=cfg.api_prefix)
    app.include_router(health.router, prefix=cfg.api_prefix)
    app.include_router(buildings.router, prefix=cfg.api_prefix)
    app.include_router(components.router, prefix=cfg.api_prefix)
    app.include_router(analysis.router, prefix=cfg.api_prefix)
    app.include_router(checks.router, prefix=cfg.api_prefix)
    # 图谱域：两条 GET 只读（清单 ＋ 扩散激活查询）＋ 一条 `POST /kg/run`。
    # ★ `--run` **有** HTTP 口子了（2026-09-25 起）：口径是**「通路 ＋ 本机限定」**，
    #   不是"没有通路"（非回环 403 `local_only`，除非带对 `X-Admin-Token`）；
    #   `--pending` 仍然没有。理由写在 routers/kg.py 的文件头。
    app.include_router(kg.router, prefix=cfg.api_prefix)
    # 房间台账域：`/api/rooms|floors|summary|path`（原 backend/db/serve_rooms.py，8123）。
    # ★ 路径**不带** `/buildings/{n}/` 前缀，与既有 `/api/buildings/{n}/rooms`（产物里的
    #   识别结果）是**两回事**：那一条读盘上的 JSON，这一条读 PG。刻意不合并 ——
    #   合并就得在同一个 handler 里分叉出两个数据源，且 8123 那个页面用的是
    #   文档相对路径 `/api/rooms?...`，改名就得回去改那个 127KB 的页面。
    app.include_router(rooms.router, prefix=cfg.api_prefix)
    # 作业台域：上传（CAD/外观图）+ 一键生产/门禁 + 看结论（原 `_scratch/_portal.py`
    # 的 8144 页面）。★ 写/执行两条挂 `ComputeDep`；`/svc`（拉起 8123/8130）
    # **刻意没搬** —— 那两个服务现在就在本进程里，留着它只会是个假开关。
    app.include_router(workshop.router, prefix=cfg.api_prefix)
    # 建模控制台域（原 `backend/web/control.py`，8130）：元数据 / 楼清单 / 逐阶段现状 /
    # 楼层资产 / 作业 / 档案规格 / 跑阶段。★ 它**不是** `/api/buildings` 的改名版：
    # 那一条只枚举批次目录（看不到注册表楼 lihua），分母不一样，所以是**自己的**
    # 一条数据路由（理由写在 `services/console.list_buildings` 的 docstring）。
    # ★ 读的长（`floor/*.png` 现算是秒级），写/执行两条挂 ComputeDep。
    app.include_router(console.router, prefix=cfg.api_prefix)
    # 影像比对域：高德卫星 ↔ 本机照片（配对是**算出来的**：照片 EXIF 是 WGS-84，
    # 瓦片是 GCJ-02，差 ~360 m，见 services/compare.py 的文件头）。
    # ★ 三条**全是只读 GET**，所以都不挂 ComputeDep —— 没有写口就不装执行面闸门
    #   （本仓规矩：能不能写只由 deps.exec_denied_reason 一处判）。
    # ★ 出图只认清单里的键，请求方**给不出路径**（`?path=` 等于开一条按任意路径读盘的面）。
    app.include_router(compare.router, prefix=cfg.api_prefix)
    # 校区地形域：真地形 DTM ＋ 真影像正射 → 一份自含贴图的 GLB（外加数据层
    # 与两张洞底截图）。★ 三条**全是只读 GET** —— 没有写口就不挂执行面闸门。
    # ★ 它读的是 `settings.resolved_campus_dir`（默认落在 `_scratch/` 下，见 settings.py
    #   里那个字段的注释）：服务器上没有那个目录 ⇒ 404 并**明说找的是哪个目录**。
    # ★ 与其它域不同：它的 JSON 走 `FileResponse` 直发原字节，**不套信封** ——
    #   套了就要重新序列化一遍，浮点写法会变（`4.800000000000001`），
    #   于是发出去的字节就不再是盘上那份交付件了（理由在 routers/campus.py 文件头）。
    app.include_router(campus.router, prefix=cfg.api_prefix)
    # 外业校核域（`/api/site/*` ＋ `/api/annotations*`）：把「建好的模型」贴回
    # 「真实的正射影像」上看外形，外加上人工圈问题的写口。
    # ★ 与 campus 域的关系：campus 发的是**校区整体**那几份交付件，这一域发的是
    #   **逐栋**的正射裁切 ⊕ 模型足迹 —— 同一张大图（`理工DOM.tif`，EPSG:4544）
    #   的两种用法。正射**只读**：本域一个字节都不往 `D:\理工数据\` 写。
    # ★ 权限按域分派：读 `view`；写锚点/写标注**两条叠加**
    #   （`ComputeDep` 答"这台进程许不许跑" ＋ `require_cap("manage")` 答"这个人许不许"）。
    #   ★ 后果写下来：`GYM3D_COMPUTE=0` 的只读服务器上写口一律 403 `compute_disabled`
    #   —— 那是对的（服务器按设计只读，锚点由本机控制台写），但页面上要原样显示这句话。
    # ★ 出图那条**先 JSON 后 PNG** 分成两条：页面拿 JSON 判三态，
    #   `state !== "ok"` 时**根本不会去设 `<img src>`** ⇒ 「无锚点」结构上不可能
    #   被画成一张空图。（同族记在 admin/views/compare.js 的文件头：
    #   404 与 409 在 `onerror` 下分不开。）
    # ★ 模块文件叫 `routers/sitecheck.py`，**不叫 `routers/site.py`** ——
    #   本函数里有一行局部变量 `site = cfg.root / "frontend" / "site"`，
    #   同名会让这一句报 `UnboundLocalError`（2026-10-02 实测，建 app 时当场炸）。
    app.include_router(sitecheck.router, prefix=cfg.api_prefix)

    # 校园数字孪生平台 · 门户域（`/api/portal/*`）。★ 这是**新系统**（门户页 `/portal/`）
    # 自己的数据面：总览 + 管理模块清单 + 体块↔楼栋锚点（身份层）。
    # ★ 它读库（`building_anchors`），所以**每一条都有闸**，且 PG 不通时降级成
    #   `state:"down"` 而**不是 0** —— 理由写在 routers/portal.py 文件头纪律 2。
    # ★ 与 campus 域的关键差别：campus 的几何走 `FileResponse` 直发原字节（不套信封），
    #   portal 的**全是派生小 JSON**，套统一信封（`ok(...)`）—— 两处的取舍不同，
    #   因为一处是"交付件原样"，一处是"接口答案"。
    app.include_router(portal.router, prefix=cfg.api_prefix)

    # 2024 实景 3D Tiles（`/api/tiles/*`）—— 门户页那块"世界底"。
    # ★ 只有它可以不套信封（走 FileResponse 直发字节），理由同 campus 域：
    #   10.4 MB 的 tileset.json 与 48,701 个 .glb 都是**交付件原件**，
    #   重新序列化一遍就不是盘上那一份了。
    # ★ 规模是个风险，不是个细节：单人浏览一遍校区会拉起成百上千个小请求，
    #   而 `gym3d-api` 是 **single worker 的 uvicorn**。§五 第 5 关要求先量
    #   P50/P95 再决定它要不要走 nginx —— 在那之前，这条路由就是那条待量路径。
    app.include_router(tiles.router, prefix=cfg.api_prefix)

    # ── 产物静态目录（GLB 走这里；生产交给 nginx）──────────────
    bdir = _buildings_dir(cfg)
    if bdir.is_dir():
        # ★ 2026-10-01 批次 2：**整目录挂载必须逐段核范围**。
        #   在这之前它是这条数据面上最大的一处裸奔：任何登录账号
        #   `GET /data/buildings/c001/rooms.json` 就能整栋拉走（含 purpose 用途、
        #   dept 使用单位 —— 正是用户说的"要账号密码才能看"）。
        #   把 `/api/buildings/*` 全部纳管而这里照旧敞着，就是**安全表演**：
        #   清册会印「已纳管」，一个红字都没有，而同一份数据换个 URL 就出得去。
        #   ⇒ `ScopedStatic` 取 URL 首段当空间树节点（`/data/buildings/c006/…`
        #     ⇒ 节点 `c006`），核不出范围回 403。
        app.mount("/data/buildings",
                  ScopedStatic(FreshStatic(directory=str(bdir)),
                               root_path="/data/buildings"), name="data")

    # ── 前端（最后挂）────────────────────────────────────────────
    # ★ 两条线分挂两个前缀，别把「管理」和「呈现」塞进同一个挂载点：
    #   · /site  = **前台**（frontend/site/）只读呈现 —— 给人看这栋楼长什么样
    #   · /admin = **后台**（frontend/admin/）管理面 —— 改参数、跑阶段、核检查
    #   · /      = **首页**（frontend/home/）—— 一屏一栋：原图 ⇄ 模型
    #   （2026-10-02 落地了原注释里那句「生产期 nginx 里让 / 指前台、/admin 指后台」；
    #    本机没有 nginx，这两件事由下面的挂载次序直接实现。）
    #
    # ★ `/site` 这个**挂载点必须留着**，即使 `/` 与 `/admin/` 已经各归各位：
    #   首页的 `/site/site.css`、`/site/js/dom.js`、`/site/js/api.js`、
    #   `/site/js/viewer.js`、`/site/vendor/three/**` 全从这里取。
    #   拆了它 = 首页样式和三维一起没，而屏幕上只是「没样式」+ 一块空白，不报错。
    site = cfg.root / "frontend" / "site"
    if site.is_dir():
        # ★ 裸 `/site`（不带尾斜杠）**进不了**下面这个挂载点，会一路落到最后那个
        #   `/` 挂载上，被它当成相对路径去找名为 `site` 的文件 ⇒
        #   `{"detail":"Not Found"}`（FastAPI 的 404 形状）。而 `/site` 正是文档与
        #   README 里写的**前台地址** —— 手敲进来、或从别处点过来，第一眼就是这个 404。
        #   （挂载自己的 `html=True` 确实会补尾斜杠，但**前提是请求先到它手上**；
        #    这里的问题恰恰是请求没到它手上。）
        #   ⇒ 登记一条**只做跳转**的路由，注册次序排在 `/` 挂载之前，先命中本尊。
        #   2026-09-24 实测：改前 `GET /site` = 404，改后 307 → `/site/` = 200。
        # ★ 2026-10-02：靶子从 `/site/` 换成 `/` —— 前台的「门」已经并进首页，
        #   老地址不许 404，但也不该再把访客送回那份旧目录页。
        #   注意**只换裸 `/site` 这一条**：`/site/` 与 `/site/**` 一个字节不动
        #   —— 首页的样式与三维脚本就挂在它们上面（见上）。
        @app.get("/site", include_in_schema=False)
        def _site_slash() -> RedirectResponse:
            return RedirectResponse(url="/", status_code=307)

        app.mount("/site", FreshStatic(directory=str(site), html=True), name="site")

    # ── 校园数字孪生平台门户（另一个系统）──────────────────────────
    # ★ 这是用户在 2026-10-01 要的那个"新做的系统"，**由另一个 claude 负责**，
    #   与建模侧（`/`首页 + `/admin/`后台 + `/site`素材）**各改各的、互不越界**。
    #   2026-10-02 只重排了建模侧的根挂载，这里**一行没碰** —— 证法是对
    #   `main.py.bak-20261002` 逐行 diff，全部差异只有三处 hunk（`/site` 的 307 靶子、
    #   `/admin` 与 `/` 两个挂载点、启动那条流程漂移自检），门户这几条路由一字未动。
    #   ★ 同一天 `frontend/portal/**` 确实在动 —— 那是**数字孪生那个会话**改的
    #   （它们正在做「退役 three 展板、世界改走 Cesium 实景」），与这里无关；
    #   「那一侧在动」与「我动了那一侧」是两件事，别把前者的 mtime 读成后者的证据。
    #   **这里故意不写「变了 N 个文件」** —— 那是个会过期的计数：10:02 量是 3 个，
    #   10:24 就已经是 4 个（多出 `portal.css`）。手打的数只在清单变长那一刻才出声，
    #   而在那之前它读起来像「已经查清了」。要比就现场比：
    #     cd /d/gym3d && sha256sum -c _scratch/_portal_baseline_20261002.sha256 | grep -v ': OK$'
    # ★ 裸 `/portal`（不带尾斜杠）进不了下面那个挂载点，会一路落到最后的 `/` 挂载上、
    #   被当成相对路径去找名为 `portal` 的文件 ⇒ 404。这与 `/site` 是同一个坑，
    #   修法也同一条：登记一条**只做跳转**的路由，注册次序排在 `/` 挂载之前。
    portal_dir = cfg.root / "frontend" / "portal"
    if portal_dir.is_dir():
        @app.get("/portal", include_in_schema=False)
        def _portal_slash() -> RedirectResponse:
            return RedirectResponse(url="/portal/", status_code=307)

        # ★ `FreshStatic` 自带 `Cache-Control: no-cache` —— 门户页恰恰不能白屏，
        #   改了 js/css 刷新一次就该看到（与 `/site` 同）。
        # ★ 外壳公开、数据受闸：`/api/portal/*` 已全部挂能力闸，
        #   `PROTECTED_PREFIXES = ("/api/", "/data/")` 把数据面圈住了，
        #   `/portal/**` 不在里面 —— 这与旧后台是**同一套路**，authz.py 一行都不用改。
        #   页面对未登录者是"一块登录屏"，拿不到任何一条数据。
        app.mount("/portal", FreshStatic(directory=str(portal_dir), html=True),
                  name="portal")

    # ── 整栋三维（原 8123 那个页面）的托管 ──────────────────────────
    # ★ 它挂在**根级** `building.html`（不能放 `/viewer/` 之类的前缀下）：
    #   页面内部一律用**文档相对**路径取数 —— `fetch('data/buildings/index.json')`、
    #   `loadSpec('data')`、`data/su/<楼>.json` —— 挂到子路径下这些全会 404。
    #   放根上，它们天然落到 `/data/**`，与下面的窄挂载对上，一行都不用改。
    #   （本仓栽过「iframe 自己制造基址难题」，这里就是那次结论的落地：不改页面的相对路径。）
    # ★ 用**一条路由**而不是 `app.mount("/", ...)`：`html=True` **不会**补 `.html`
    #   （starlette 只试 index.html / 404.html），所以挂载点救不了单文件。
    building_page = cfg.root / "frontend" / "building.html"
    if building_page.is_file():
        @app.get("/building.html", include_in_schema=False)
        def _building_page() -> FileResponse:
            return FileResponse(str(building_page), media_type="text/html")

    # 页面要的静态依赖，**按需窄到文件名**（一条不多）。★ 绝不挂整个 `/data`：
    # 那会把 `data/_meta/**`（检查产物）与 `data/refs/**` 一并端出去。
    # 三条来源都是实测出来的，不是照抄清单：
    #   · `/data/buildings`（**已挂**）← index.json 里 96 条全部，含每栋的 spec/floors
    #     与 `glb: "data/buildings/<楼>/<楼>-building.glb"` ⇒ 根级那 3 个散 GLB 不必挂
    #   · `data/su/<楼>.json`     ← `loadSuSpec()`（building.html:2001）
    #   · `data/floors/floor<N>.json` + `data/spec.json` ← lihua 基线那条 `"dir": "data"`
    #
    # ★ 为什么是**窄路由**而不是 `app.mount("/data/su", ...)` —— 挂目录 = 把那个目录
    #   **此刻和以后**的一切都端出去。实测枚举过（2026-09-25，但步骤反了：是先挂了
    #   才去数的 —— 枚举本该在挂之前做）：
    #     `data/su/` 顶层 98 项 = 97 份 `<楼>.json` ＋ `.orig/`（备份树，此刻是**空**目录）
    #                              ＋ `_meta.json`（40KB 清单：每份规格的 sha256
    #                              ＋ **生成脚本的仓库内路径**）
    #   而页面只 `fetch('data/su/<楼>.json')`，名字取自 index.json；清单与 `.orig`
    #   它一次都不读（building.html:193 提到 `_meta.json`，但那在**注释**里，不是请求）。
    #   ⇒ 窄成"只有页面真要的那一种文件名"：首字符不许是 `_` / `.`，于是 `.orig` 与
    #     `_meta.json` **天然落在可寻址空间之外** —— 不靠"现在那里恰好没东西"。
    #     空目录今天无害；明天谁往里放一份备份，挂目录的写法会**在没人改这行代码的
    #     情况下**开始可读它。（本仓铁律：排除规则排除了什么，必须数出来 ——
    #     这里的"数"就是 `_PAGE_ASSET` 这个 pattern：它就是可寻址空间的定义。）
    #
    # ★ 坏名字回 **422**（FastAPI 的 pattern 校验），不是 404，这一条是有意的：
    #   "这个名字不在我可寻址的范围里"和"这里没有这个文件"是**两件**事。混成一个
    #   404 会让"穿越被挡住"和"文件恰好不存在"在屏幕上长得一样（铁律 16：
    #   量具坏了与被测对象是空的，长得一样）。文件在范围内、盘上没有 ⇒ 才 404。
    #   pattern 本体不写在这里 —— 它是 `deps.AssetFileName`，理由与那个坑写在那一处。
    def _serve_page_asset(sub: str, fname: str) -> FileResponse:
        path = cfg.resolved_data_dir / sub / fname
        if not path.is_file():
            raise not_found("页面依赖里没有这个文件", sub=sub, name=fname)
        return FileResponse(str(path), media_type="application/json")

    # ── 权限（2026-10-01 批次 2）：这几条**文件名里带楼号**，逐段核 ──────
    #
    # ★ 为什么这几条不能只挂一个 `require_cap("view")` 就完事：
    #   它们服务的正是"某一栋楼"的产物（`su/<楼>.json`、`<楼>-building.glb`），
    #   不核范围 = 一个只覆盖 c006 的账号能拿到 c001 的规格与模型。
    #   而它们的楼号**藏在文件名里**，不是路径段 —— `scope_param=` 取不到，
    #   只能自己从 fname 里取（与 `ScopedStatic` 取首段是同一件事，两条通路）。

    def _legacy_owners() -> tuple:
        """哪些楼把产物**直接放在 `data/` 根下**（而不是 `data/buildings/<楼>/`）。

        `index.json` 里 `"dir": "data"` 的那几条 —— 今天只有 `lihua`（理化楼基线）。
        `/data/spec.json` 与 `/data/floors/floor<N>.json` 只属于它们：路由接受
        任意 `floor<N>.json`，而盘上只有这一份，**文件名里没有楼号**。
        ★ 不在这里写死 `"lihua"`：写死就是同一个事实的第二处实现，而 `index.json`
          换了基线之后这里不会跟着动 —— 症状是"闸放行了一栋它不该放行的楼"，
          而屏幕上什么都不显示（铁律 018）。
        """
        idx = cfg.resolved_data_dir / "buildings" / "index.json"
        try:
            rows = json.loads(idx.read_text(encoding="utf-8"))
        except OSError as exc:                      # 读不到 ⇒ 空集，下面按"谁都不给"处理
            print("[authz] 读不到 %s（%s）⇒ /data/spec.json 与 /data/floors/* "
                  "只对全校区范围的账号开放" % (idx, exc))
            return ()
        return tuple(r["name"] for r in rows if r.get("dir") == "data")

    def _legacy_ok(p) -> bool:
        """`/data/spec.json` 与 `/data/floors/*` 能不能给这个账号看。

        规则：**看得见任意一个"根下产物"的归属楼**就给。空集（index 读不到）
        ⇒ 退到"要全校区范围"，与上面那行 print 是同一句话的两种出口。
        """
        owners = _legacy_owners()
        return sees(p, "*") if not owners else any(sees(p, o) for o in owners)

    @app.get("/data/su/{fname}", include_in_schema=False,
             dependencies=[Depends(require_cap("view"))])
    def _su_spec(fname: AssetFileName, p: PrincipalDep) -> FileResponse:
        # `su/<楼>.json` —— 楼号就是去掉 `.json` 的那一段。
        # ★ 只剥**结尾那一个** `.json`，不用 `rsplit(".",1)[0]`：后者对
        #   `c006.extra.json` 会给出 `c006.extra`，它既不是楼号也不报错。
        #   反正两者都判否（fail-closed），但要的是**一个想得清的规则**。
        require_scope(p, re.sub(r"\.json$", "", fname))
        return _serve_page_asset("su", fname)

    @app.get("/data/floors/{fname}", include_in_schema=False,
             dependencies=[Depends(require_cap("view"))])
    def _floors_json(fname: AssetFileName, p: PrincipalDep) -> FileResponse:
        # `floor<N>.json` —— **文件名里没有楼号**，它属于 `dir == "data"` 那几栋。
        if not _legacy_ok(p):
            raise ApiError(403, "forbidden",
                           "这份账号的范围不覆盖任何一栋「产物放在 data/ 根下」的楼。",
                           dict(p.brief(), required_cap="view",
                                note="floor<N>.json 不带楼号，归属见 index.json 的 dir 字段"))
        return _serve_page_asset("floors", fname)

    spec_json = cfg.resolved_data_dir / "spec.json"
    if spec_json.is_file():
        @app.get("/data/spec.json", include_in_schema=False,
                 dependencies=[Depends(require_cap("view"))])
        def _spec_json(p: PrincipalDep) -> FileResponse:
            if not _legacy_ok(p):
                raise ApiError(403, "forbidden",
                               "这份账号的范围不覆盖任何一栋「产物放在 data/ 根下」的楼。",
                               dict(p.brief(), required_cap="view"))
            return FileResponse(str(spec_json), media_type="application/json")

    # ★ 根级 GLB：`data/<楼>-building.glb`。上面那段注释里写着「根级那 3 个散 GLB
    #   不必挂」—— **那句话对 95 栋成立，对第 96 栋是错的**：
    #   `index.json` 里 lihua 是**唯一**一条 `"dir": "data"`，它的 GLB 就躺在
    #   `data/` 根下（`data/lihua-building.glb`），而 `/data/buildings` 那个挂载
    #   覆盖不到它。2026-09-25 实测：这一条加上之前 `GET /data/lihua-building.glb`
    #   是 **404**，而建模控制台那一屏正好会去取它（行里的 `links.glb`）。
    #   ⇒ 把"从 95 条推广到 96 条"的那一步补回来。
    # ★ 仍然是**窄规则**（`deps.GlbFileName`：单段 ＋ `.glb` 后缀），不是挂整个 `/data`
    #   —— 根下那些目录（`_meta/`、`refs/`）与别的单段文件（`spec.json`、
    #   `<楼>-profile.json`）各有各的路由负责，这一条一个都不多开。
    def _glb_owner(fname: str) -> str:
        """`data/<…>.glb` 归**哪栋楼** —— 从名册里反查，取**最长**的那个匹配。

        规则：去掉 `.glb`，然后找名册里满足 `stem == 名` 或 `stem.startswith(名 + "-")`
        的那个**最长**的名（`lihua-building` ⇒ 名 `lihua`）。
        ★ 用 `名 + "-"` 而不是裸前缀：本仓真有 `c004f1`/`c008f1` 这类楼号，
          裸前缀会让 `c004` 也"匹配"上 `c004f1`（铁律：前缀匹配必须带分隔符）。
        ★ 名册**现读** `index.json`，不写死任何一个楼号 —— 写死就是第二个来源。

        ⇒ 反查不出来就回空串，由调用方按 **fail-closed** 处置。
        """
        stem = fname[:-4] if fname.endswith(".glb") else fname
        idx = cfg.resolved_data_dir / "buildings" / "index.json"
        try:
            rows = json.loads(idx.read_text(encoding="utf-8"))
        except OSError:
            return ""
        hit = ""
        for r in rows:
            n = r.get("name") or ""
            if n and (stem == n or stem.startswith(n + "-")) and len(n) > len(hit):
                hit = n
        return hit

    @app.get("/data/{fname}", include_in_schema=False,
             dependencies=[Depends(require_cap("view"))])
    def _root_glb(fname: GlbFileName, p: PrincipalDep) -> FileResponse:
        # ★ 权限（2026-10-01 批次 2）：根级 GLB 里 **`lihua-building.glb` 是那一栋楼
        #   的模型本体** —— 不核范围的话，"只看得见 c006" 的账号能把这栋楼的完整
        #   几何下走，而 `/data/buildings/**` 那半边已经全锁上了。
        # ★ 另外两个（`j6-walls.glb` / `j6-deci05.glb`）实测**反查不出楼号**：
        #   `j6` 是"六教"的另一种叫法，而名册里那一栋叫 `c006` —— 名册里没有 `j6`，
        #   所以这条规则对它们回空串。**不许**在这里补一个 `j6 → c006` 的映射：
        #   那是我从"六教"这两个字推出来的，不是从数据里读出来的（铁律 018）。
        #   按 fail-closed 处置 ⇒ 只有**全校区范围**的账号能取它们。
        #   代价：本机不受影响（回环 = 搭建方@`*`）；哪天真要按栋发这两个，
        #   正确的做法是让产出它们的那一步把楼号写进文件名，不是在这里猜。
        owner = _glb_owner(fname)
        if owner:
            require_scope(p, owner)
        elif not sees(p, "*"):
            raise ApiError(403, ERR_FORBIDDEN,
                           "这个文件名反查不出楼号（名册里没有对应的楼），"
                           "只对全校区范围的账号开放。",
                           dict(p.brief(), required_cap="view", name=fname))
        path = cfg.resolved_data_dir / fname
        if not path.is_file():
            # 名字在可寻址范围内、盘上没有 ⇒ 404（与"名字不在范围内"的 422 分开，
            # 理由见上面 `_PAGE_ASSET` 那段）。
            raise not_found("根级没有这个文件", name=fname)
        return FileResponse(str(path), media_type="model/gltf-binary")

    # ── 建模后台：挪到 /admin/（2026-10-02 根挂载重排）───────────────
    # 改前是反过来的：admin 挂在 `/`，而 `/admin` 与 `/admin/` 两条都 307 回 `/`。
    # 于是「首页」这个位置被后台占着，访客打开网址第一眼看到的是管理面。
    # 现在把两个位置**各归各位**：`/` 给首页，`/admin/` 给后台。
    #
    # ★ 旧注释里那句话是错的，别再照着它推理：「不能把 admin 挂到 /admin，
    #   那页的样式与脚本全是相对路径，换到 /admin/ 下会连带全 404」——
    #   相对路径（`app.css`、`js/app.js`）只在**文档 URL 不带尾斜杠**时才会
    #   解析错。下面那条 307 正是保证文档 URL 永远是 `/admin/`，于是
    #   `app.css` → `/admin/app.css`、`./views/x.js` → `/admin/views/x.js`，
    #   两条都落在本挂载点里，一个文件都不用改。
    #   （`console.js` 里唯一的跨根引用是 `await import('/site/js/viewer.js')`，
    #    写的是**根绝对**，本来就不受影响。）
    admin = cfg.root / "frontend" / "admin"
    if admin.is_dir():
        # ★ 这条 307 是**承重的**：省了它，`/admin`（不带尾斜杠）就成了文档 URL，
        #   上面说的那批相对路径会全部解析到根上 ⇒ 全 404 且不报错。
        @app.get("/admin", include_in_schema=False)
        def _admin_slash() -> RedirectResponse:
            return RedirectResponse(url="/admin/", status_code=307)

        # ★ **必须在最后那个 `/` 挂载之前注册**：Starlette 按注册次序匹配，
        #   晚注册的 `/` 会把 `/admin/**` 静默吃掉（首页的静态目录里找不到
        #   `admin/app.css`，回 404，而屏幕上只是「样式没了」）。
        app.mount("/admin", FreshStatic(directory=str(admin), html=True), name="admin")

    # ── 首页（最后一挂，否则它抢走 /api 与 /data）────────────────────
    # ★ 必须是**最后**一个挂载点：`/` 会匹配一切尚未命中的路径。
    #   放在 `/site`、`/portal`、`/admin`、`/building.html`、`/data/**` 之前，
    #   上面这些全都进不来 —— 而失败的样子是「接口 404」，不是「挂载顺序错了」。
    home = cfg.root / "frontend" / "home"
    if home.is_dir():
        app.mount("/", FreshStatic(directory=str(home), html=True), name="home")
    elif admin.is_dir():
        # 首页目录还没做出来时，`/` 不许变成 404 —— 退回后台（改前的行为）。
        app.mount("/", FreshStatic(directory=str(admin), html=True), name="admin")
    else:
        @app.get("/")
        def _no_front() -> dict:
            return envelope(data={"hint": "前端目录 frontend/home 与 frontend/admin 都不存在"},
                            error=None)

    # ── 启动期断言（最后做，此时路由已全）───────────────────────────
    # 每一条写路由都必须挂着 require_compute（执行面闸门），否则**拒绝启动**。
    # 理由见 deps.py：违反这条纪律的后果是"少一道 403"，从外面看不出来。
    # `extra_gate=is_cap_gated`：账户域（`/api/auth/**`）的闸是 `require_cap` 而不是
    # `require_compute` —— 登录/建号/授权不是 compute 动作，而且 `login` **必须**
    # 让局域网打进来（挂 require_compute 会让它永远 403，即账号体系从装上的那天起
    # 就登不上去）。别的域一个都没放宽，理由见 deps.CAP_PLANE_PREFIXES。
    assert_writes_gated(app, extra_gate=cap_plane_gate)

    # 受保护前缀（/api/** 与 /data/**）下的每一条**写路由**至少要有一道闸
    # （`require_cap` 或 `require_compute`），否则拒绝启动。★ 读路由**不**拒绝，
    # 只**印出来** —— 见 authz.auth_inventory 的 docstring：一次全上闸会让你
    # 当天就用不了，而"没闸"与"有闸但放行"在屏幕上长得一样，所以必须有那份清册。
    # 清册本身由 assert_caps_gated **自己印**（print），这里不再抄一遍 ——
    # 同一个数印两处，改一处就会对不上（CLAUDE.md 铁律 18）。
    assert_caps_gated(app)

    # ★ break-glass 必须可见（settings.py 里那条注释的落点）：一个"连自己有没有开
    #   都不知道"的后门，比有后门更糟。
    # ★ 2026-10-01 改成 **print**，原文是 `(log.warning if 开 else log.info)(...)`。
    #   实测（8231，`GYM3D_LOOPBACK_BREAKGLASS=0` 起）：日志里**一个字都没有** ——
    #   `describe()` 确实被调了，但那句注释许的"印在启动日志里"只在**开着**那一半成立。
    #   原因是 `log = logging.getLogger("gym3d.api")` 这个 logger 没人配过 handler，
    #   `log.info` 无声丢弃；只有 WARNING+ 会被 `logging.lastResort` 兜住印到 stderr。
    #   ⇒ 于是"关着"这个状态**没有出口**，而它恰恰是要被确认的那一个
    #     （部署到服务器前，你要能一眼看到自己确实关上了）。
    #   用 print 与紧邻上面的清册同一个通道，两处都保证可见。
    print(describe(cfg))

    # ── 流程定义漂移（`config/pipeline.json` ⇄ `PIPELINE_FALLBACK`）───────────
    # 判据在 `console_meta.pipeline_drift()`，这里只负责**印出来** ——
    # 一个没人印的自检等于没有自检：判词写在一个没有出口的通道上，与"没有这条
    # 判据"在屏幕上完全一样（本仓记过这个形状）。
    # ★ 用 print 与上一行 `describe(cfg)` 同一个通道：`log.info` 在这条链路上
    #   没有 handler，会被静默丢弃（紧上面那两段注释就是为这个从 log 改成 print 的）。
    # ★ `console_meta` 是 `backend/web/` 下的**顶层模块**（那个目录没有
    #   `__init__.py`），import 它得先把 backend/web 挂上 sys.path —— 复用本仓
    #   已有的那一步（`services/console.py:_ensure_console_paths`），
    #   不在这里再写第二份路径魔法。
    # ★ **「没量到」与「量到是干净的」必须分开印**：后者只印一行 ✓ 不多说话，
    #   前者必须自己出声。否则「我没查」会安静地读成「查过了、没有」。
    try:
        from .services.console import _ensure_console_paths

        _ensure_console_paths(cfg)
        import console_meta                                      # noqa: PLC0415
        drift = console_meta.pipeline_drift()
    except Exception as e:                                       # noqa: BLE001
        print("  [流程漂移] ★ 没量到（import 或求值失败）：%s: %s" % (type(e).__name__, e))
    else:
        if drift:
            for _w in drift:
                print("  [流程漂移] " + _w)
        else:
            print("  [流程漂移] ✓ 回落与 config/pipeline.json 的阶段 id 逐条相同")

    return app


def _buildings_dir(cfg):
    return cfg.resolved_data_dir / "buildings"


app = create_app()
