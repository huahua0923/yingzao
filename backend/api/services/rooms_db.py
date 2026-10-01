# -*- coding: utf-8 -*-
"""房间库（PostgreSQL / lihua_twin）的**连通状态**。

三条设计，都不是随手的：

1. **不是开机探针。** PG 是可选的（`settings.db_required` 默认 False），
   管理台其余九屏都不依赖它。开机探针会把"PG 没起"升级成"管理台起不来" ——
   正好把两个不相干的故障捆成一个。所以按需探。
2. **探一次缓存 10 秒。** `/api/capabilities` 是页面加载时第一批发出的请求；
   PG 挂着的时候，"每次加载等满超时"和"报一句 PG 不通"是同一件事的两种代价，
   而前者会让整个管理台看起来是卡住了 —— 屏幕上分不出"卡"和"没数据"。
3. **探不到就说探不到，不冒充"零"。** 返回里 `state` 只有 `ok` / `down` 两个值，
   `down` 一定带 `reason`。调用方不许把 `down` 渲染成 `0 条` —— 那是假话，
   而且会把该出现的警告横幅吞掉（见 memory: gauge-coverage-invisible-in-summary）。
"""
from __future__ import annotations

import time

# 连不上最多等 2 秒。没有这个上限，黑洞 PG 会一直占着线程池的线程，
# 排在后面的管理台请求只能干等。
CONNECT_TIMEOUT_S = 2
CACHE_TTL_S = 10.0

# {时间戳, 结果}。进程内缓存，`force=True` 可绕过。
_cache: tuple[float, dict] | None = None


def _probe_uncached(cfg) -> dict:
    try:
        import psycopg            # noqa: PLC0415 —— 懒导入：服务器 venv 里没有它也得能起
    except ImportError as e:
        return {"state": "down", "reason": "未安装 psycopg（%s）" % type(e).__name__}

    try:
        params = cfg.db_params()
    except RuntimeError as e:
        # 口令为空。这是**配置缺失**，不是"库挂了" —— 理由要分开写，
        # 否则部署方会去查数据库，而该查的是 .env。
        return {"state": "down", "reason": str(e)}

    try:
        # ★ 只连是不够的：库在恢复中时 TCP 连得上而查询会失败。
        #   所以真发一条 `SELECT 1`，拿它的结果当判据。
        with psycopg.connect(connect_timeout=CONNECT_TIMEOUT_S, **params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as e:  # noqa: BLE001 —— 任何异常都只表示"这一刻连不上"
        # 只回类型名 + 一句话，不回堆栈：栈里有本机路径，而这一屏是给局域网看的。
        return {"state": "down",
                "reason": "%s: %s" % (type(e).__name__, str(e).strip()[:200])}
    return {"state": "ok", "reason": None}


def state(cfg, *, force: bool = False) -> dict:
    """房间库此刻通不通。

    返回 `{"state": "ok"|"down", "reason": str|None, "checked_ago_s": float}`。
    `checked_ago_s` 必须一起给出去：这是一个**有时间的快照**，不是终值 ——
    读它的人要知道自己看的是几秒前的数（见 memory: in-flight-snapshot-read-as-final）。
    """
    global _cache
    now = time.monotonic()
    if force or _cache is None or (now - _cache[0]) > CACHE_TTL_S:
        _cache = (now, _probe_uncached(cfg))
    stamp, result = _cache
    return {**result, "checked_ago_s": round(now - stamp, 1)}
