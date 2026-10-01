# -*- coding: utf-8 -*-
"""房间台账域：`/api/rooms` / `/api/floors` / `/api/summary` / `/api/path`。

原 `backend/db/serve_rooms.py`（8123，stdlib 服务）的四条接口搬进本进程，
**路径名一字不改**。这不是顺手：`frontend/building.html` 用**文档相对**路径取数
（`fetch(API_BASE + '/api/rooms?...')`，`API_BASE` 默认空串 ⇒ 同源），而那个页面同时
挂在本进程根下 ⇒ 那两条请求天然落到本路由上，**页面一行都不用改**。
改名就得回去改那个 127KB 的页面，而它里面 `/api/rooms` 与 `/api/path` 各有多处调用点。

四条纪律，都不是随手的：

1. **handler 一律 `def`，不许 `async def`。** psycopg 是同步驱动：在 `async def` 里连库
   会把**整个事件循环**按住，而合并之后那个循环还要同时服务管理台轮询与 GLB 流 ——
   一栋楼的房间查询就能让整站卡住。`def` 由 FastAPI 丢进线程池，互不牵连。
2. **`connect_timeout` 必须给。** 黑洞 PG（TCP 连得上但不应答）会让线程一个接一个吊在
   那里，排在后面的管理台请求只能干等。上限**只在 `services/rooms_db.py` 定义一次**，
   这里 import 它 —— 两处各写一个 2 秒，两处一致也证明不了它是对的（铁律 18）。
3. **PG 的问题一律 503，绝不裸 500。** `ERR_UPSTREAM` 这个码在 `responses.py` 里躺着
   没人用，就是给这一族留的。裸 500 的意思是「服务端坏了」，而 PG 没起是「上游没就绪」
   —— 对调用方的下一步完全不同（一个报障，一个等会儿重试）。口令没配（`RuntimeError`）
   也走 503：那属于**配置缺失**，不该被读成「代码坏了」，否则查错方向整个反掉
   （`rooms_db.py` 对这一点有同样的分岔）。
4. **`/api/path` 单独处理、懒加载。** `backend/nav/build_path.py` 在**模块作用域** import
   `PIL.Image` 与 `shapely`，而 `requirements-server.txt` **刻意排除**这两样（服务器只服务、
   不建模）。模块级 import 会让 `import backend.api.main` **直接失败** —— 崩掉的正是本项目
   号称最硬的那道防线（settings.py 的硬要求 1）。所以它在 handler 内懒加载：缺依赖回
   **503 并点名缺的是哪个模块**，不许 500、也不许静默回一条空路径
   —— 空路径在页面上就是「这两间房之间走不通」，那是**假话**。

`building` 参数**刻意不加 pattern 约束**：它只进 SQL 的参数位（`%s`），不做任何路径或
字符串拼接，注入面为零；而 legacy 的 `/api/rooms?building=X` 对 X 没有任何限制，
加了 pattern 反而会把合法楼号挡在 422 上（本仓铁律：新增的判据不许把该放过的拦掉）。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Query

from ..authz import SEP, PrincipalDep, require_cap, require_scope, visible
from ..deps import SettingsDep
from ..responses import ERR_UPSTREAM, ApiError, bad_request, not_found, ok
from ..services.rooms_db import CONNECT_TIMEOUT_S

router = APIRouter(tags=["rooms"])

# ── 权限（批次 2，2026-10-01）────────────────────────────────────────
#
# ★ 本文件是**唯一**一条"节点在 query 里"的域，所以它不用
#   `require_cap(..., scope_param=...)`（那个只读路径参数），而是在 handler 里
#   用 `require_scope(p, node)` ＋ `visible(p, rows, key)`。两种写法的分工与理由
#   写在 `authz.require_scope` 与 `authz.visible` 的 docstring 里。
#
# ★ 这四条原来**一条闸都没有**：任何登录账号问 `/api/rooms`（不带参数）会拿到
#   **全校区 10562 个房间**，含 `purpose`（用途）与 `dept`（使用单位）—— 那正是
#   用户说的"要账号密码才能看"的东西。所以本文件的验收判据是**两条**：
#   ①范围外的账号拿到 403 或空集 ②范围内的账号拿到**只有那几行**。
#   只验①的话，一个恒回空集的坏实现也能全绿。
#
# ★ 能力闸（`require_cap("view")`，不传范围）与范围核（`require_scope`）**都要**：
#   前者答"这个角色能不能读台账"，后者答"能读哪几栋"。少前者 ⇒ 一个只有 edit
#   却没有 view 的角色（今天不存在，但矩阵是可配的）能读；少后者 ⇒ 全校区。
_VIEW = [Depends(require_cap("view"))]

# 列清单就是**行序契约**：下面按 r[0..11] 取值，改这里的顺序就等于改所有取值。
# 所以照抄 `_scratch/_retired_20260925/serve_rooms.py` 的原样，别顺手排版。
ROOM_COLS = "id, building, floor, number, name, area_label, area_m2, purpose, dept, centroid_x, centroid_y, boundary"
FLOOR_COLS = "building, floor, gfa_m2, rooms_n, room_net_m2, room_label_m2, purposes"

# `backend/` 目录（本文件是 backend/api/routers/rooms.py）。
# 需要它是因为 `backend/nav/` **不是包**（底下没有 `__init__.py`），真入口是
# `backend/nav/build_path.py` 这个顶层模块，而它自己又 `from paths import DATA`
# （`backend/paths.py`）⇒ `backend/` 必须在 sys.path 上。只在懒加载那一步补，且幂等。
_BACKEND_DIR = str(Path(__file__).resolve().parents[2])


def _brief(prefix: str, e: BaseException) -> str:
    """给调用方看的一句话：类型名 + 截断后的原文。

    ★ 不回堆栈：栈里有本机路径，而这个服务是给局域网看的（与 `rooms_db.py` 同口径）。
    """
    return "%s：%s: %s" % (prefix, type(e).__name__, str(e).strip()[:200])


@contextmanager
def _cursor(cfg) -> Iterator[Any]:
    """一条用完自动关的 PG 游标；把**驱动层**的问题统一翻译成 503。

    ★ 只接 `psycopg.Error` 与连接期的异常，**别把 `ApiError` 一起接走** ——
      路由自己抛的 400/404 得原样穿过去，被这里包成 503 就等于把
      「你给的参数不对」说成「上游坏了」。
    """
    try:
        # 懒导入：服务器 venv 里没有 psycopg 时，本模块仍要能 import
        # （先例 backend/api/services/rooms_db.py、routers/components.py）。
        import psycopg  # noqa: PLC0415
    except ImportError as e:
        raise ApiError(503, ERR_UPSTREAM,
                       "本进程没装 psycopg，房间库不可用（%s）。"
                       % type(e).__name__) from e

    try:
        params = cfg.db_params()
    except RuntimeError as e:
        # 口令为空 ⇒ **配置缺失**，不是库挂了。照原话回，让部署方去查 .env。
        raise ApiError(503, ERR_UPSTREAM, str(e)) from e

    try:
        conn = psycopg.connect(connect_timeout=CONNECT_TIMEOUT_S, **params)
    except Exception as e:  # noqa: BLE001 —— 任何异常都只表示「这一刻连不上」
        raise ApiError(503, ERR_UPSTREAM, _brief("连不上房间库", e)) from e

    try:
        with conn.cursor() as cur:
            yield cur
    except psycopg.Error as e:
        raise ApiError(503, ERR_UPSTREAM, _brief("房间库查询失败", e)) from e
    finally:
        conn.close()


# ── 三个查询（照抄 `_scratch/_retired_20260925/serve_rooms.py:57-130` 的语义，只把连接交给 _cursor）────────

def _one(v: list[str] | None) -> str | None:
    """**一个查询参数的单一取值** —— 两条规则都是从老端的 `parse_qs` 抄来的。

    ★ 为什么不收成 `str | None` 直接让 FastAPI 填：它对非列表标量取**最后一个**，
      而老端 `parse_qs(...)[0]` 取**第一个**。两条后果都实测过（2026-09-25 对拍）：
      · 重复参数：`?floor=0&floor=1` 老端回 floor=0 的 **1394** 行、新端回 floor=1 的
        **1502** 行；`?building=lihua&building=c006` 老端 5 层、新端 11 层。
        两边都是**合法数据、只是对象不同** —— 没有任何报错会提示这种分歧，
        屏幕上就是一组看着正常的数字。搬家不该顺手改语义，所以照抄老端。
      · 空值：`parse_qs` 默认 `keep_blank_values=False`，`?floor=` 的空值**当场被丢掉**，
        于是与「没带这个参数」完全同形（老端 200 回**全库**，不是 400）。而 FastAPI
        把空串原样交进来 ⇒ 不归一的后果是「搬家把能用的变成 400」，页面上原本
        正常的一个链接突然报错。这一条我**先入为主写错过**：断言里写「空串 ⇒ 400」，
        是探针把我纠正过来的（先量老端，再定断言）。
    ★ 只认**空串**、不认空白：`?floor=%20`（一个空格）老端是 400（`int(" ")` 抛），
      这里同样 400 —— 空串与空白是两回事，一起放掉就又改了行为。
    ★ **调用它的那五个参数必须写成 `= Query(None)`，不能只写 `= None`。** 这不是风格：
      FastAPI 对**裸的** `list[str]` 注解不当查询参数，当**请求体字段**；GET 没有 body，
      于是它安静地取默认值 —— 参数一个都没绑上，而接口照回 200、照有数据（回的是全库）。
      2026-09-25 实测：改成裸 `list` 之后 24 条用例里 13 条变红，红的形状全是
      「老端 118 行 / 新端 8772 行」，而**没有任何一条报错**。
      这和上面 `from` 的 alias 是同一个坑：**参数名/形态不对，就是「被静默忽略、路径照跑」**。
    """
    if not v:
        return None
    return None if v[0] == "" else v[0]


def _room_rows(cfg, floor, building) -> list[dict]:
    where, params = [], []
    if floor is not None:
        where.append("floor=%s")
        params.append(floor)
    if building:
        where.append("building=%s")
        params.append(building)
    sql = "SELECT %s FROM rooms" % ROOM_COLS
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY building, floor, number"

    with _cursor(cfg) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out = []
    for r in rows:
        b = r[11]
        if isinstance(b, str):          # 兜底：JSONB 被当字符串返回时
            b = json.loads(b)
        out.append({
            "id": r[0], "building": r[1], "floor": r[2], "number": r[3], "name": r[4],
            "area_label": r[5], "area_m2": r[6], "purpose": r[7], "dept": r[8],
            "centroid_x": r[9], "centroid_y": r[10], "boundary": b,
        })
    return out


def _floor_rows(cfg, building) -> list[dict]:
    """楼层级面积：**建筑面积 = 外墙外围（不扣楼梯电梯井）；房间净面积 = 墙内皮**。

    `rooms` 表回答「这间多大」，本表回答「这层/这栋多大」—— 数字孪生两问都要，
    且两个口径**不许混用**（见 `floor_areas` 表自己的列名 gfa_m2 / room_net_m2）。
    """
    sql = "SELECT %s FROM floor_areas" % FLOOR_COLS
    params = []
    if building:
        sql += " WHERE building=%s"
        params.append(building)
    sql += " ORDER BY building, floor"

    with _cursor(cfg) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out = []
    for r in rows:
        pu = r[6]
        if isinstance(pu, str):
            pu = json.loads(pu)
        out.append({"building": r[0], "floor": r[1], "gfa_m2": r[2], "rooms_n": r[3],
                    "room_net_m2": r[4], "room_label_m2": r[5], "purposes": pu})
    return out


def _summary(cfg, building) -> dict | None:
    """单体汇总：整栋建筑面积、房间净面积、房间数、用途分布、楼层数。

    没有楼层数据 ⇒ 回 `None`，由调用处转成 404 —— **不是**回一份全 0 的汇总：
    0 m² 是「量出来是 0」，而这里的真相是「这栋楼不在库里」，两件事
    （本仓铁律：`量不到` 与 `没问题` 在屏幕上必须不是同一行字）。
    """
    floors = _floor_rows(cfg, building)
    if not floors:
        return None
    purposes: Counter = Counter()
    for f in floors:
        purposes.update(f["purposes"] or {})
    return {
        "building": building,
        "floors_n": len(floors),
        "gfa_m2": round(sum(f["gfa_m2"] or 0 for f in floors), 2),
        "room_net_m2": round(sum(f["room_net_m2"] or 0 for f in floors), 2),
        "room_label_m2": round(sum(f["room_label_m2"] or 0 for f in floors), 2),
        "rooms_n": sum(f["rooms_n"] or 0 for f in floors),
        "purposes": dict(purposes.most_common()),
        "floors": floors,
    }


# ── 路由 ────────────────────────────────────────────────────────────────────

@router.get("/rooms", dependencies=_VIEW)
def rooms(cfg: SettingsDep, p: PrincipalDep,
          floor: list[str] | None = Query(None),
          building: list[str] | None = Query(None)) -> dict:
    """逐间：面积 + 用途 + 使用单位 + 边界多边形。

    ★ `floor` 收成 **str 再自己转**，不用 `int | None`：交给 FastAPI 做类型校验时，
      非整数会回 **422 且不是本仓信封**（`{"detail":[...]}` 是 FastAPI 的原生形状），
      而 `building.html` 只有一条解析路径（先看 `success`）。
    ★ 两个参数都收成 **list** 再自己取第一个 —— 见 `_one` 的 docstring：
      空串与重复参数这两件事上，FastAPI 的默认取值和老端**不一样**。

    ★ 权限两问（2026-10-01 批次 2）：
      · 显式给了 `building` ⇒ **核那一栋**，不给就 403（而不是"过滤成空"）——
        因为"你问了一栋你没有的楼"与"那栋楼没有房间"是两件事，回空列表会让
        调用方以为后者（老端对空集就是回空列表，这个语义不许混进来）。
      · 没给 `building` ⇒ 是**全库查询**，按范围**逐行过滤**。这一支是重点：
        原来它会原样发出全校区 10562 行。
    """
    floor = _one(floor)
    building = _one(building)
    floor_i = None
    if floor is not None:
        try:
            floor_i = int(floor)
        except ValueError:
            raise bad_request("floor 必须是整数") from None

    if building:
        require_scope(p, building)
    data = _room_rows(cfg, floor_i, building)
    if not building:
        data = visible(p, data, lambda r: r["building"])
    return ok(data, meta={"total": len(data), "floor": floor_i, "building": building})


@router.get("/floors", dependencies=_VIEW)
def floors(cfg: SettingsDep, p: PrincipalDep,
           building: list[str] | None = Query(None)) -> dict:
    """逐层：建筑面积（外墙外围）/ 房间净面积（墙内皮）/ 用途分布。

    某栋没有数据时回**空列表 + total=0**（而不是 404）—— 这是 legacy 的行为，
    刻意保留：这个接口的语义是「列出满足条件的层」，一个都没有就是空集。
    ★ `building` 收成 list 再取第一个，理由与 `/api/rooms` 同（见 `_one`）。
    ★ 权限口径与 `/api/rooms` **逐字相同**（显式给了就核那一栋、没给就逐行过滤）——
      两条接口同一件事两个口径，正是本仓记过的那一族（一个判断四份实现）。
    """
    b = _one(building)
    if b:
        require_scope(p, b)
    data = _floor_rows(cfg, b)
    if not b:
        data = visible(p, data, lambda r: r["building"])
    return ok(data, meta={"total": len(data), "building": b})


@router.get("/summary", dependencies=_VIEW)
def summary(cfg: SettingsDep, p: PrincipalDep,
            building: list[str] | None = Query(None)) -> dict:
    """整栋汇总 + 逐层。`building` 必填（不填无法确定哪一栋），缺 ⇒ 400。

    ★ 这里**故意不套** `_one` 的「空串 = 没给」那一半：老端对 `/api/summary?building=`
      是 **400**（它自己写着「空 = 缺」），与 `/api/rooms` 的「空 = 全库」相反。
      两条接口同一件事两个结论看着别扭，但那正是老端的行为 —— 搬家的目标是**一样**，
      不是**好看**；顺手统一就等于一次没量过的行为改动。另一半（重复参数取第一个）
      照旧适用，所以走 `_one(…)` 之后再判空。
    """
    b = _one(building)
    if not b:
        raise bad_request("缺少 building 参数")
    # ★ `building` 必填 ⇒ 这一条**只**核那一栋，没有"逐行过滤"那一支。
    #   顺序是**先核后查**：反过来会让"这栋楼你没有权限"和"这栋楼不在库里"
    #   在时间上分不出来（后者要连一次库），而两条该给的下一步不同。
    require_scope(p, b)
    data = _summary(cfg, b)
    if data is None:
        raise not_found("该楼没有楼层面积数据：%s" % b)
    return ok(data)


def _compute_path():
    """懒加载 `backend/nav/build_path.py` 的 `compute_path`，缺依赖 ⇒ 503。

    ★ 那三行 sys.path 一条都不能少，缺哪条都是 ModuleNotFoundError：
      · `_BACKEND_DIR` —— `nav/` 不是包，且 `build_path.py` 自己 `from paths import DATA`；
      · `ensure_sys_path("nav")` —— 用仓内既有的那条路（`_scratch/_retired_20260925/serve_rooms.py:32` 同款），
        不自己拼「nav 在哪」，免得两处各有一套说法（memory: 一个判断多份实现）。
    """
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)
    try:
        from paths import ensure_sys_path  # noqa: PLC0415
        ensure_sys_path("nav")
        from build_path import compute_path  # noqa: PLC0415
    except ImportError as e:
        missing = getattr(e, "name", None) or type(e).__name__
        raise ApiError(503, ERR_UPSTREAM,
                       "几何寻路不可用：本进程缺依赖 %s。"
                       "服务器部署用的 requirements-server.txt 刻意不含 PIL/shapely"
                       "（那是建模侧的依赖）；要在服务器上用它得单独装这两个包。"
                       % missing) from e
    return compute_path


def _node_of(src: str | None, building: str | None) -> str:
    """这次寻路问的是**哪栋楼**：显式 `building` 优先，否则从房间 id 的首段取。

    ★ 为什么要有一条"从 id 取"的规则，而不是"没给 building 就按默认楼"：
      `build_path.compute_path(building=None)` 的默认是**理化楼基线**（它自己的
      docstring 写着）。把那个默认值在这里再写一遍就是**同一个数写在两个地方**
      —— 两处一致也证明不了它是对的（铁律 018），而且 `compute_path` 哪天换默认，
      权限这边不会跟着动，症状是"闸放行了一栋它其实不该放行的楼"。
      房间 id 是 `楼|层|房号`（与 `room_key` 同形），首段就是权威答案。
    ★ 取不到（既没给 building、给的又是**裸房号**）⇒ 回空串 ⇒ `require_scope` 判否
      ⇒ **403，并且在 detail 里点名缺的是 `building`**。这是 fail-closed：
      不断言"那大概就是默认那栋"。裸房号那条路本来就是旧 CLI 的形状，
      `frontend/building.html` 走的是 id（`from_id`/`to_id`），不受影响。
    """
    if building:
        return building
    for x in (src,):
        if x and SEP in x:
            return x.split(SEP, 1)[0]
    return ""


@router.get("/path", dependencies=_VIEW)
def path(p: PrincipalDep,
         from_id: list[str] | None = Query(None),
         to_id: list[str] | None = Query(None),
         building: list[str] | None = Query(None),
         from_: list[str] | None = Query(None, alias="from"),
         to: list[str] | None = Query(None, alias="to")) -> dict:
    """同层/跨层几何寻路（A* 占用网格 + 楼梯井），回 3D 折线。

    两种入参：`from_id`+`to_id`（房间 id，**前端走这条**，id 全局唯一）与
    `from`+`to`（房号，留给 CLI 与旧链接 —— 房号不唯一，跨层会配错）。
    两个都给时以 id 为准（`by_id` 优先），与 legacy 一致。

    ★ 房号那条路**只加在 query 的别名上**：`from` 是 Python 关键字，签名里只能叫
      `from_`，靠 `alias="from"` 把它接回来。改名段（Query 参数名）不属于路由路径，
      但也别漏 —— 漏了就是「参数被静默忽略、路径照跑」，页面上看不出任何异常。
    ★ 五个参数一律 `_one`：这一条**老端是「空 = 缺」**（空 ⇒ 400），与 summary 同侧、
      与 rooms/floors 反侧 —— 但重复参数取第一个这半边对四条接口都适用。
    """
    from_id, to_id = _one(from_id), _one(to_id)
    building, from_, to = _one(building), _one(from_), _one(to)
    by_id = bool(from_id and to_id)
    src, dst = (from_id, to_id) if by_id else (from_, to)
    if not src or not dst:
        raise bad_request("缺少 from_id/to_id（或 from/to）参数")

    # ★ 顺序：**先核权限，后算路径**。反过来的话，一次越权请求会先把整层的
    #   占用网格读出来算一遍再被拒 —— 那是白花力气，而且"被拒"的耗时跟着数据量
    #   走，探测得出来哪栋楼大不大。
    # ★ 只核 `src` 那一侧就够：一条路径**在导航数据里**只属于一栋楼
    #   （`compute_path` 的 `building` 是单值参数，跨楼寻路根本不存在）。
    #   核两遍不是更安全，只是让"这条判据到底在防什么"变得含糊。
    require_scope(p, _node_of(src, building))

    compute_path = _compute_path()
    try:
        data = compute_path(src, dst, building, by_id)
    except ValueError as e:
        # 「这两间房有一间不在这个楼里」/「之间走不通」——都是**入参的问题**，回 400。
        raise bad_request(str(e)) from e
    return ok(data)
