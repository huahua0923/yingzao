# -*- coding: utf-8 -*-
"""启动入口：`python -u backend/api/run_api.py`

端口/地址只从 settings（环境变量 > .env > 默认）来，**代码里不写死数字**。
生产用 PM2 起这个文件（`instances:1, exec_mode:'fork'` —— 多进程会让
带内存缓存的产物索引各算各的，且没有共享状态可依赖）。

用法（不要加 --help 探参数，本文件只认 --reload 一个开关）：
    python -u backend/api/run_api.py              # 正常启动
    python -u backend/api/run_api.py --reload     # 开发：改代码自动重载
"""
import os
import sys
from pathlib import Path

# 允许 `python backend/api/run_api.py` 直接跑（否则包级相对 import 会失败）。
if __package__ in (None, ""):
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]

import uvicorn  # noqa: E402

from backend.api.settings import get_settings  # noqa: E402


def main() -> int:
    # Windows 控制台默认 GBK，中文日志会变糊字（memory: gbk-mangled-log-units）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    cfg = get_settings()
    reload = "--reload" in sys.argv[1:]
    print("=" * 68)
    print("  gym3d 建模后台  http://%s:%d/" % (cfg.host, cfg.port))
    print("  接口文档        http://%s:%d/api/docs" % (cfg.host, cfg.port))
    print("  模式            compute=%s env=%s（compute=0 时写接口 403）"
          % (cfg.compute, cfg.env))
    print("  数据目录        %s" % cfg.resolved_data_dir)
    print("=" * 68)
    # 传 import 字符串而不是 app 对象：`--reload` 要求字符串（子进程要能自己
    # import），两种模式用同一条路径，就不会出现"开发能跑、上线挂掉"的分叉。
    uvicorn.run("backend.api.main:app", host=cfg.host, port=cfg.port,
                reload=reload, log_level=cfg.log_level, access_log=True)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
