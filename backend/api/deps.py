# -*- coding: utf-8 -*-
"""路由共用的依赖与路径参数类型。

两条纪律写在这里，写一次：

1. **楼号参数一律走 `BuildingName`** —— 它把 `{name}` 限死在 `^[A-Za-z0-9_-]+$`。
   路径拼接是这个环节唯一的注入面：`/api/buildings/../..%2fetc` 这类串
   在拼接前就被 FastAPI 挡成 422，而不是靠每个 handler 记得 `..` 检查。
2. **写操作一律挂 `require_compute`** —— 服务器（GYM3D_COMPUTE=0）上写接口回
   403 `compute_disabled`，且是**路由级**依赖，不是 handler 里的一句 if：
   忘挂依赖的后果是 422 之前的 403 缺失，一眼能看出来；忘记写 if 的后果是静默放行。

同样只依赖标准库 + fastapi/pydantic。
"""
from typing import Annotated

from fastapi import Depends, Path

from .responses import ERR_COMPUTE_DISABLED, ApiError
from .settings import Settings, get_settings

# 楼号：c113 / c012f1 / ny27 这类。刻意**不允许**点号与斜杠，
# 备份文件（profile.json.bak-bands-20260917）因此天生不在可寻址空间内。
BuildingName = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,32}$")]

# 楼层号：0..99（个别楼 F11+）。上界给足但不接受负数/字符串。
FloorIndex = Annotated[int, Path(ge=0, le=99)]


def settings() -> Settings:
    """进程内单例（get_settings 自带 lru_cache）。"""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings)]


def require_compute(cfg: SettingsDep) -> Settings:
    """写接口的门。compute=0（服务器）时抛 403，而不是静默变成只读。

    为什么抛错而不是"假装成功"：只读服务器收到一个本意要改数据的请求，
    如果回 200，调用方会以为改成了 —— 那是最坏的一种静默失败。
    """
    if not cfg.compute:
        raise ApiError(
            403, ERR_COMPUTE_DISABLED,
            "本进程以只读方式运行（GYM3D_COMPUTE=0），写操作不可用。"
            "要改数据请连本机全功能控制台。",
            {"compute": False, "env": cfg.env},
        )
    return cfg


ComputeDep = Annotated[Settings, Depends(require_compute)]
