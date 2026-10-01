# -*- coding: utf-8 -*-
"""统一响应信封 —— 所有 /api 路由回同一个形状。

    {"success": true,  "data": ..., "error": null, "meta": {...}}
    {"success": false, "data": null, "error": {"code": ..., "message": ...}, "meta": {...}}

为什么不是裸 JSON：前端只有**一条**解析路径（先看 success=true 才取 data），
不必为每个路由记住「这个错了是回 404 还是回 `{}`」。老控制台那种
「有的错回 HTML、有的错回空数组」是前端 bug 的常驻来源。

本模块**只依赖标准库**（同 settings.py 的硬要求），服务器 venv 里没有
ezdxf/shapely 也必须能 import。
"""
from typing import Any

from fastapi.responses import JSONResponse

# 错误码：机器可读，前端按它分支，不去 parse message。
ERR_BAD_REQUEST = "bad_request"
ERR_NOT_FOUND = "not_found"
ERR_COMPUTE_DISABLED = "compute_disabled"
# 403 的第二种：本进程**能**写，但这一份请求不是从本机来的。
# 刻意与 compute_disabled 分开：补救办法不一样（一个是改本机配置，
# 一个是换地址或配 token），前端要能分别说清楚。
ERR_LOCAL_ONLY = "local_only"
ERR_UPSTREAM = "upstream_error"
ERR_INTERNAL = "internal_error"

# ★ 权限的两个码，**刻意分成两个**（2026-10-01 加账号体系时定的）：
#   401 = 我不知道你是谁        ⇒ 下一步是去登录
#   403 = 我知道你是谁，但你不能 ⇒ 下一步是找管理员要授权（登录没用，登了还是这个）
#   合成一个码之后前端只能统一弹"无权限"，而这两个"下一步"完全不同。
#   ★ 与 ERR_LOCAL_ONLY 也刻意分开：那是"这台进程不给你写"（换地址/配 token 能解），
#     这是"你这个账号不许"（换地址没用）。
ERR_UNAUTHENTICATED = "unauthenticated"
ERR_FORBIDDEN = "forbidden"
# 429。★ 与 401 分开：401 的下一步是「再输一次」，429 的下一步是「等一会儿再输」
#   —— 合成一个码会让人**对着锁定的账号反复重试**，把手上的锁越撞越紧。
#   细节里必须带 `retry_after`，否则前端只能写一个"请稍后再试"（等于没说等多久）。
ERR_RATE_LIMITED = "rate_limited"


class ApiError(Exception):
    """业务错误。由 main.py 的异常处理器统一渲染成信封。

    路由里只管 raise，不管怎么变成 HTTP —— 唯一一处决定形状的地方，
    就不会出现「这个路由忘了带 success 字段」。
    """

    def __init__(self, status: int, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


def not_found(what: str, **detail: Any) -> ApiError:
    return ApiError(404, ERR_NOT_FOUND, what, detail or None)


def bad_request(message: str, **detail: Any) -> ApiError:
    return ApiError(400, ERR_BAD_REQUEST, message, detail or None)


def unauthenticated(message: str = "请先登录。", **detail: Any) -> ApiError:
    return ApiError(401, ERR_UNAUTHENTICATED, message, detail or None)


def forbidden(message: str, **detail: Any) -> ApiError:
    # ★ `detail` 里**必须**说清是哪条能力、哪个范围、以及这个人现在有什么
    #   —— 否则读的人只能自己猜，而猜出来的多半是同一个错的思路
    #   （本仓铁律 166④）。
    return ApiError(403, ERR_FORBIDDEN, message, detail or None)


def envelope(data: Any = None, error: dict | None = None,
             meta: dict | None = None) -> dict:
    return {"success": error is None, "data": data, "error": error, "meta": meta or {}}


def ok(data: Any, meta: dict | None = None) -> dict:
    """直接 return ok(...)，由 FastAPI 序列化。"""
    return envelope(data=data, meta=meta)


def error_json(err: ApiError) -> JSONResponse:
    body = {"code": err.code, "message": err.message}
    if err.detail is not None:
        body["detail"] = err.detail
    return JSONResponse(status_code=err.status, content=envelope(error=body))
