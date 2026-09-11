# -*- coding: utf-8 -*-
"""数据库连接参数的唯一来源。

口令**只从环境变量读，代码里不留默认值**。曾经这里写着默认口令，
结果它跟着源码进了版本库 —— 而默认口令一旦进过 git 历史，删提交也洗不掉，
只能轮换。所以现在的策略是：读不到就拒绝连接，让问题在启动时暴露，
而不是让一个「碰巧能连上」的弱口令悄悄兜底。

环境变量（可由仓库根的 .env 提供，见 .env.example）：
    LIHUA_DB_HOST      默认 localhost
    LIHUA_DB_PORT      默认 5432
    LIHUA_DB_USER      默认 postgres
    LIHUA_DB_NAME      默认 lihua_twin
    LIHUA_DB_PASSWORD  必填，无默认值
"""
import os
from pathlib import Path

# 仓库根的 .env。backend/db/db_config.py → parents[2] = 仓库根。
# 用原生路径拼接而不是写盘符：Windows 本机和 Linux 服务器共用同一份代码。
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"

_loaded_env = False


def load_env(path=ENV_FILE):
    """把 .env 里的键值读进 os.environ。

    极简实现（够用就好），刻意不引 python-dotenv —— Phase 0 的约束是「零行为变更」，
    不能为了读一个文件就往环境里塞新依赖。Phase 1 落 pydantic-settings 后，
    这个函数会被 settings.py 取代。

    规则：已存在的环境变量**不覆盖** —— 命令行显式导出的值优先于文件。
    """
    global _loaded_env
    if _loaded_env:
        return
    _loaded_env = True
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class MissingDbPassword(RuntimeError):
    """口令未配置。刻意用异常而不是 sys.exit，方便调用方决定怎么报错。"""


def db_params(**overrides):
    """返回 psycopg.connect() 的关键字参数。

    overrides 可以覆盖任一字段（例如 serve_rooms.py 需要指定 building）。
    口令为空时抛 MissingDbPassword —— 不静默降级成某个默认口令。
    """
    load_env()
    password = os.environ.get("LIHUA_DB_PASSWORD")
    if not password:
        raise MissingDbPassword(
            "未设置 LIHUA_DB_PASSWORD。请复制 .env.example 为 .env 并填入口令"
            "（.env 已被 .gitignore 排除），或在环境里导出该变量。"
        )
    params = dict(
        host=os.environ.get("LIHUA_DB_HOST", "localhost"),
        port=int(os.environ.get("LIHUA_DB_PORT", "5432")),
        user=os.environ.get("LIHUA_DB_USER", "postgres"),
        dbname=os.environ.get("LIHUA_DB_NAME", "lihua_twin"),
        password=password,
    )
    params.update(overrides)
    return params
