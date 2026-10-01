# -*- coding: utf-8 -*-
"""健康检查与能力公告。

`/api/capabilities` 不是装饰：前端要能**先问再画**。
只读服务器上"编辑/重跑"按钮应当消失，而不是点下去回 403 —— 403 是兜底，
不是交互设计。这个路由就是那条"先问"的通道。

★ 三件事在这一版里改了做法，都是因为同一条毛病：**屏幕上好看的做法会自己过期**。

1. `write_enabled` 不再只读一个开关，而是问 `deps.exec_denied_reason` ——
   **和真正执行时用的是同一个函数**。于是"公告的"和"执行的"没法不一致：
   局域网打开页面时，按钮会和实际权限一起变成禁用，而不是点下去才 403。
2. `endpoints` 由框架的 openapi **现算**（不是遍历 `app.routes` —— 那条路在
   FastAPI 0.141 上是空的，理由写在 `_endpoint_index` 里）。上一版是手抄的两张表，
   文件头自己都承认抄漏了不报错（实测漏过 `/api/checks/manifest`、`/api/checks/fleet`）。
3. `rooms_db` 是**带时间的快照**（`checked_ago_s`），不是"永远为真"的字段。
"""
from fastapi import APIRouter, Request

from ..deps import (HTTP_METHODS, WRITE_METHODS, SettingsDep,
                    count_hidden_under, exec_denied_reason)
from ..responses import ok
from ..services import area_audit, artifacts, rooms_db

router = APIRouter(tags=["health"])

# 本页托管的工具 —— **这张表是手写的，而 `endpoints` 不是，差别是有意的**：
# `endpoints` 描述"路由有几条"，那能从 app.routes 现算；这张描述的是
# **"界面挂在哪、顶替了谁"**，机器推不出来（一个视图文件被 import 到几个地方、
# 它算不算一个"工具"，是人的决定）。
# `available` 由磁盘现查 ⇒ 视图还没写好的时候这一条会自己报"未就绪"，
# 而不是让导航栏点进去才发现是空的。
_TOOLS = [
    # id, 标签, 落点, 承载方式, 旧端口
    # ★ 8144 / 8155 只能写字面量：那两个服务（`_scratch/_retired_20260925/_portal.py`、
    #   `_scratch/_retired_20260925/_kg_view.py`）**本身就没进 git**，端口自然也从没进过 .env。
    #   写成配置项只会让"配置里有、文件里没有"这件事更难查。
    ("workshop", "作业台",   "/#/workshop",    "native", 8144),
    ("kg",       "图谱",     "/#/kg",          "native", 8155),
    ("console",  "建模控制台", "/#/console",    "native", None),   # None ⇒ 取 cfg.legacy_console_port
    ("building", "整栋三维",  "/building.html", "hosted", None),   # None ⇒ 取 cfg.legacy_rooms_port
]


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


def _endpoint_index(app, cfg) -> dict:
    """本进程的 API 路由清单 —— **从 openapi 现算**，不手抄。

    ★ 为什么是 openapi 而不是"遍历 `app.routes` 找 `APIRoute`"：
      **FastAPI 0.141 起 `include_router` 不把路由摊平进 `app.routes`**，
      而是挂一个 `_IncludedRouter`（它**没有** `.routes`，真路由在 `original_router`
      上，还带一个 `include_context`）。按老写法遍历，得到的是一张**空表**。
      2026-09-25 实测就是这样：`total` 报了 0，才看出来。
      （空表和"本来就没有路由"在屏幕上长得一模一样 —— 这两个计数就是为此留的。）
      openapi 是框架按**实际路由**生成的，天然应用 `include_in_schema=False`，
      并且不依赖任何私有属性，所以比对 `_IncludedRouter` 做递归稳。

    ★ `hidden`：排除规则排除了什么，**必须数出来**。不进 openapi 的路由不会出现在
      上面那张表里，这里是它们的条数（今天 = FastAPI 自己加的 `/api/docs` 与
      `/api/openapi.json` 两条）。这个数变了就说明有路由悄悄从清单里消失了 ——
      而不是「清单短了」和「本来就这么短」长得一样。
      ★ 它在**摊平后**的树上数（`deps.count_hidden_under`），不是 `app.routes`：
        同一个 0.141 的变化让 `app.routes` 里只剩 FastAPI 自己那两条，
        照老写法遍历会**恒等于 2** —— 哪个路由器里再藏一条隐藏路由都不会露出来。
        而且摊平**必须带上父级前缀**，否则这里的 `startswith(pre)` 一筛全掉、
        这个数**恒为 0**（2026-09-25 实测就是这么坏的：屏幕上「一个都没排除」
        与「排除规则根本没生效」完全同形）。
        摊平与「算不算进清单」各只有一份实现（都在 deps.py，且带刑具），
        这里直接调它，免得两处各有一套说法。
    """
    pre = cfg.api_prefix.rstrip("/") + "/"
    read, write = [], []
    for path, ops in app.openapi().get("paths", {}).items():
        if not path.startswith(pre):
            continue
        if not {m.lower() for m in ops} & HTTP_METHODS:
            continue
        (write if {m.upper() for m in ops} & WRITE_METHODS else read).append(path)
    hidden = count_hidden_under(app.routes, pre)
    return {
        "read": sorted(read), "write": sorted(write),
        "total": len(read) + len(write),
        "hidden": hidden,
        # 分栏（read/write）按 HTTP 方法分。★ 它**不**证明"这条会不会改数据" ——
        # 方法与语义不总是一一对应（一个 POST 可以是纯查询）。真正管这件事的是
        # deps.py 的执行闸门；`main.py` 的启动期断言保证每条写路由都挂着它。
        "split_by": "http_method",
        "authoritative": f"{cfg.api_prefix}/openapi.json",
    }


def _tools(cfg, front_admin) -> list[dict]:
    """四个集成工具的落点与就绪状态。`available` 是**磁盘现查**。"""
    out = []
    for tid, label, path, kind, legacy in _TOOLS:
        if legacy is None:
            legacy = (cfg.legacy_console_port if tid == "console"
                      else cfg.legacy_rooms_port)
        if kind == "native":
            ready = (front_admin / "js" / "views" / f"{tid}.js").is_file()
        else:
            ready = (cfg.root / "frontend" / "building.html").is_file()
        out.append({"id": tid, "label": label, "path": path, "kind": kind,
                    "port_legacy": legacy, "available": ready})
    return out


@router.get("/capabilities")
def capabilities(request: Request, cfg: SettingsDep) -> dict:
    """能做/不能做什么，以及为什么。前端的按钮开关直接读它。"""
    bdir = artifacts.buildings_dir(cfg.resolved_data_dir)
    n = len([d for d in bdir.iterdir()
             if d.is_dir() and (d / "profile.json").is_file()]) if bdir.is_dir() else 0
    log = area_audit.find_log(cfg.root)

    # ★ 这个请求**自己**就是从那个浏览器发来的，所以拿它问"能不能执行"
    #   得到的就是那个浏览器能不能执行。前端不必自己判 location.hostname
    #   —— 那是同一个判断的第二份实现，两份迟早会不一致。
    denied = exec_denied_reason(request, cfg)
    return ok({
        "compute": cfg.compute,
        # 读永远可用；写要看「本机吗」和「compute 开着吗」两件事，理由分开给。
        "read_enabled": True,
        "write_enabled": denied is None,
        "write_disabled_reason": denied[1] if denied else None,
        "write_disabled_code": denied[0] if denied else None,
        "admin_token_configured": bool(cfg.admin_token),
        "buildings": n,
        "dxf_dir_configured": bool(cfg.dxf_dir),
        "area_audit_snapshot": (log.name if log else None),
        # 检查引擎的产物目录在不在 —— 前端据此决定"检查"那一屏有没有东西可看。
        "checks_artifact_dir_present": (cfg.resolved_data_dir / "_meta" / "checks").is_dir(),
        "tools": _tools(cfg, cfg.root / "frontend" / "admin"),
        # 房间库是个**可选**依赖，这里报的是"此刻通不通"，带了时间戳。
        "rooms_db": rooms_db.state(cfg),
        "endpoints": _endpoint_index(request.app, cfg),
    })
