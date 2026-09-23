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
ERR_UPSTREAM = "upstream_error"
ERR_INTERNAL = "internal_error"


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
