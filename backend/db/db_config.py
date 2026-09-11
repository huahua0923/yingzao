# -*- coding: utf-8 -*-
"""数据库连接参数（兼容垫片）。

真正的唯一来源是 `backend/api/settings.py`；本模块只是把它包一层，
让老脚本继续 `from db_config import db_params` 而不必改动调用点。

**口令代码里不留默认值。** 这里曾经写着默认口令，结果它跟着源码存在了很久 ——
默认口令一旦进过版本库，删提交洗不掉，只能轮换。所以现在是：读不到就抛错，
让问题在启动时暴露，而不是让一个「碰巧能连上」的弱口令悄悄兜底。

环境变量（可由仓库根的 .env 提供，见 .env.example）：
    LIHUA_DB_HOST / LIHUA_DB_PORT / LIHUA_DB_USER / LIHUA_DB_NAME
    LIHUA_DB_PASSWORD  必填，无默认值
"""
import sys
from pathlib import Path


class MissingDbPassword(RuntimeError):
    """口令未配置。刻意用异常而不是 sys.exit，方便调用方决定怎么报错。"""


def _settings():
    """延迟 import：本模块被 sys.path 直接引到时，仓库根可能还没挂上。"""
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from backend.api.settings import get_settings
    return get_settings()


def db_params(**overrides):
    """返回 psycopg.connect() 的关键字参数。

    overrides 可覆盖任一字段（例如连管理库时传 dbname="postgres"）。
    口令为空时抛 MissingDbPassword —— 不静默降级成某个默认口令。
    """
    try:
        params = _settings().db_params()
    except RuntimeError as exc:              # settings 层抛的就是「口令为空」
        raise MissingDbPassword(str(exc)) from exc
    params.update(overrides)
    return params
