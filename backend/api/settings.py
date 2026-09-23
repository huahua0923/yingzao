# -*- coding: utf-8 -*-
"""配置的唯一来源。

**这个模块就是「可上服务器」的地基**，它必须满足两条硬要求：

1. **模块级零重依赖。** 只能 import pydantic / pydantic-settings / 标准库。
   服务器 venv 里没有 ezdxf / shapely / trimesh，import 本模块必须照样成功 ——
   这是「只服务」模式第一道防线能被验证的前提（Phase 6 验收：
   `python -c "import backend.api.settings"` 在干净 venv 里必须过）。
2. **不出现任何盘符、端口、口令的字面量。** 仓库根由 `__file__` 推导，
   开发机在 `D:\\gym3d`、服务器在 `/opt/gym3d`，同一份代码两边都能跑。

配置来源优先级：**环境变量 > .env 文件 > 这里的默认值**。
.env 不进版本库（见 .gitignore），键清单见仓库根的 .env.example。
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根：本文件是 backend/api/settings.py，往上三级就是根。
# 刻意用 __file__ 推导而不是配一个 GYM3D_ROOT 环境变量 —— 少一个必须配对的变量，
# 就少一处「换台机器就忘了改」的故障点。要覆盖仍然可以用 GYM3D_ROOT。
_DEFAULT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GYM3D_",
        env_file=str(_DEFAULT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",          # 环境里多出来的键不要炸
        # 空值当作「没配」而不是「配了个空字符串」：.env.example 的留白键
        # （`GYM3D_LEGACY_ROOMS_PORT=`）原样复制过去也应当能跑。
        env_ignore_empty=True,
        populate_by_name=True,   # 允许用字段名（而非别名）赋值
        case_sensitive=False,
    )

    # ── 路径 ────────────────────────────────────────────────────────
    root: Path = _DEFAULT_ROOT
    data_dir: Path | None = None          # 默认 <root>/data
    frontend_dist: Path | None = None     # 默认 <root>/frontend/dist
    # 源 DXF 目录：**只有本机建模需要**，服务器留空（留空时相关阶段直接标记为不可跑）
    dxf_dir: Path | None = None

    # ── 能力开关：本进程是全功能控制台，还是只读服务器 ──────────────
    # True  = 本机（可跑管道 / 可改参数 / 可下 DXF）
    # False = 服务器（写接口一律 403 compute_disabled）
    compute: bool = True
    env: Literal["dev", "prod"] = "dev"

    # ── HTTP ────────────────────────────────────────────────────────
    # 默认 8140 而不是 8130：8130 是过渡期老 control.py 的端口，
    # 两者不能撞车（Phase 2 靠双跑对拍验证新旧一致，见计划）。
    # Phase 6 老服务下线后，把 .env 里的 GYM3D_PORT 改回 8130 即可，
    # 不用改代码 —— nginx 反代指到哪就是哪。
    host: str = "127.0.0.1"
    port: int = 8140
    api_prefix: str = "/api"
    cors_origins: str = ""                # 逗号分隔；prod 同源部署不需要 CORS
    log_level: str = "info"

    # ── 过渡期：老 stdlib 服务的端口（Phase 6 下线后连同字段一起删）──
    # 刻意**不给默认值**：端口只存在于 .env，代码里不留数字字面量。
    # 不设 = 老服务拒绝启动 —— 逼部署方显式确认，而不是「碰巧跑在某个端口上」。
    legacy_console_port: int | None = None   # backend/web/control.py
    legacy_rooms_port: int | None = None     # backend/db/serve_rooms.py
    # 房间台账后台（backend/db/serve_rooms_admin.py）：**会写库**的管理页，只在本机跑。
    # 同样刻意不给默认值 —— 端口只存在于 .env。
    rooms_admin_port: int | None = None      # backend/db/serve_rooms_admin.py
    # 台账后台**单独**的监听地址：刻意不复用 GYM3D_HOST。
    # 查看器是要给局域网看的（HOST=0.0.0.0），而管理页能改数据库，不该跟着一起对外。
    # 想从别的机器管，就显式设 GYM3D_ROOMS_ADMIN_HOST=0.0.0.0 **并且**设 GYM3D_ADMIN_TOKEN，
    # 否则服务拒绝启动（见 serve_rooms_admin.py）。
    rooms_admin_host: str = "127.0.0.1"

    # ── 数据库（PostgreSQL / lihua_twin）────────────────────────────
    # 别名不带 GYM3D_ 前缀：沿用既有部署环境里的 LIHUA_DB_* 变量名，
    # 免得为了「配置整洁」把服务器上already在用的变量全改一遍。
    db_host: str = Field("localhost", validation_alias="LIHUA_DB_HOST")
    db_port: int = Field(5432, validation_alias="LIHUA_DB_PORT")
    db_user: str = Field("postgres", validation_alias="LIHUA_DB_USER")
    db_name: str = Field("lihua_twin", validation_alias="LIHUA_DB_NAME")
    db_password: str = Field("", validation_alias="LIHUA_DB_PASSWORD")
    # prod 下置 1：缺口令直接拒绝启动，而不是拖到第一次查询才 500
    db_required: bool = Field(False, validation_alias="LIHUA_DB_REQUIRED")

    # ── 建模作业（仅 compute=True 时有意义）─────────────────────────
    job_timeout_s: int = 7200             # 单阶段超时；现状服务完全没有超时，卡死会永久占锁
    job_max_concurrency: int = 1
    job_persist: bool = True              # 日志与状态落盘 data/_jobs/，进程重启后能报出孤儿作业

    # ── 敏感值（服务器留空）─────────────────────────────────────────
    deepseek_api_key: str = ""
    admin_token: str = ""                 # 留空 = 完全交给 nginx 的 auth_basic

    # ── 派生路径与开关 ──────────────────────────────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir or (self.root / "data")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_frontend_dist(self) -> Path:
        return self.frontend_dist or (self.root / "frontend" / "dist")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def db_params(self, **overrides) -> dict:
        """psycopg.connect() 的关键字参数。

        口令为空时抛错而不是静默降级成某个默认口令 —— 这个项目曾经把默认口令
        写进源码，结果它跟着代码存在了很久；默认口令一旦进过版本库，删提交洗不掉，
        只能轮换。所以这里宁可让调用方明确地失败。
        """
        if not self.db_password:
            raise RuntimeError(
                "未设置 LIHUA_DB_PASSWORD：复制 .env.example 为 .env 并填入口令，"
                "或在环境里导出该变量。"
            )
        params = dict(
            host=self.db_host, port=self.db_port, user=self.db_user,
            dbname=self.db_name, password=self.db_password,
        )
        params.update(overrides)
        return params

    # ── 启动期校验：能在这里拦住的，绝不拖到运行期 ──────────────────

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.is_prod and self.db_required and not self.db_password:
            raise ValueError(
                "GYM3D_ENV=prod 且 LIHUA_DB_REQUIRED=1，但 LIHUA_DB_PASSWORD 为空。"
                "生产环境拒绝以无口令状态启动。"
            )
        if self.job_max_concurrency < 1:
            raise ValueError("GYM3D_JOB_MAX_CONCURRENCY 必须 >= 1")
        if self.job_timeout_s < 1:
            raise ValueError("GYM3D_JOB_TIMEOUT_S 必须 >= 1")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。改了 .env 要生效就重启进程（配置本就该在启动时定死）。"""
    return Settings()
