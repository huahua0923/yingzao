# -*- coding: utf-8 -*-
"""校园数字孪生平台 · 门户域：`/api/portal/*`。

这是**新系统**（门户页 `/portal/`）自己的数据面。它与旧后台（`frontend/admin/`）
共用同一套权限闸（`authz.py`），但**不复用旧后台的接口** —— 门户要的是"一个页面装下
校区总览 + 各类管理"，旧后台那些路由是**建模流水线**的接口，形状不一样。

四条纪律，都不是随手的：

1. **handler 一律 `def`，不许 `async def`。** psycopg 是同步驱动：在 `async def` 里连库
   会把整个事件循环按住，而那个循环还要同时服务 GLB 流与其它页面轮询。
   `def` 由 FastAPI 丢进线程池，互不牵连。（与 `routers/rooms.py` 同一条。）

2. **PG 不通 ⇒ 那一项报 `down` 并给 `reason`，绝不渲染成 0。**
   「库里 0 个锚点」与「没连上库」在屏幕上必须是两句不同的话 —— 后者渲染成 0
   会让运维去查"为什么锚点没了"，而该查的是数据库（铁律 144 那一族）。

3. **读路由逐行过滤，写路由要 `manage`。** `require_cap("view")` 只管"能不能读台账"，
   不管"能读哪几栋" —— 少了 `visible(...)` 这一道，一个只覆盖 c006 的账号
   会原样拿到全校区锚点，而权限清册上那条会印成「已纳管」（`authz.visible` 的 docstring
   就是为这件事写的）。

4. **★ 那条校区级权限口径的到期日就是本文件。**
   `routers/campus.py:35-45` 自己写着：「哪天往 viewdata 里加『点一下弹出这栋楼的用途』，
   这条口径就作废了 —— 那时必须逐栋过滤，而这句注释就是那个信号。」
   本文件正是那一天。处理方式是一个**决定**（写下来，不静默）：

       外形/几何      维持全校区 —— 校区轮廓本来就是给所有人看的，不构成信息泄露
       身份与内容     **逐栋过滤** —— 锚点（楼名）、楼层用途、房间台账，只看得到的

   所以锚点的读路由**必须**带 `visible`；而体块几何（模拟期在前端）不带。
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..authz import PrincipalDep, require_cap, visible
from ..deps import SettingsDep
from ..responses import ERR_UPSTREAM, ApiError, bad_request, ok

router = APIRouter(tags=["portal"])

_VIEW = [Depends(require_cap("view"))]
_MANAGE = [Depends(require_cap("manage"))]


# ── 库连接（懒加载 + 诚实降级）────────────────────────────────────────

def _anchors_mod():
    """懒导入 `backend.db.anchors`。

    ★ 为什么懒：它模块级 `import psycopg`，而服务器 venv 里 psycopg 不保证有
      （`rooms_db.py` 对同一件事也是懒导入）。模块级 import 会让 `import backend.api.main`
      **整个失败** —— 崩掉的正是本项目最硬的那道防线。
      缺依赖回 503 并**点名缺谁**，不许 500，也不许静默回空列表
      （空列表在页面上就是"一个锚点都没有"，那是假话）。
    """
    try:
        from backend.db import anchors as A      # noqa: PLC0415
    except ImportError as e:
        raise ApiError(503, ERR_UPSTREAM,
                       "锚点库不可用：未安装 psycopg（%s）" % type(e).__name__
                       ) from None
    return A


@contextmanager
def _conn(A) -> Iterator[Any]:
    """连库并把异常翻成 503（上游没就绪），绝不裸 500。"""
    try:
        conn = A.connect()
    except RuntimeError as e:                    # 口令没配 —— 配置缺失，不是代码坏了
        raise ApiError(503, ERR_UPSTREAM, "锚点库配置缺失：%s" % e) from None
    except Exception as e:                       # noqa: BLE001
        raise ApiError(503, ERR_UPSTREAM,
                       "锚点库连不上：%s: %s" % (type(e).__name__, str(e).strip()[:180])
                       ) from None
    try:
        yield conn
    finally:
        conn.close()


def _anchors_state(cfg, codes=None) -> dict:
    """锚点库此刻通不通 —— **不抛异常**，供总览页降级用。

    返回 `{"state": "ok"|"down", "reason": str|None, "stats": dict|None}`。
    ★ `state` 只有两个值，且 `down` 一定带 reason：调用方不许把 down 画成 0。

    ★ `codes` 是**调用者可见的楼栋**（路由层用 `visible()` 算好传进来）。
      不传 = 数全校 —— 只有平台自用/自检才该这么调。总览页那个统计**必须传**：
      它与同一屏上的 `/api/portal/anchors`（逐行过滤过）说的得是同一件事，
      否则一个只管 c006 的账号会在这儿读到全校的覆盖率。
    """
    try:
        A = _anchors_mod()
        with _conn(A) as conn:
            return {"state": "ok", "reason": None, "stats": A.stats(conn, codes)}
    except ApiError as e:
        return {"state": "down", "reason": e.message, "stats": None}
    except Exception as e:                       # noqa: BLE001
        return {"state": "down",
                "reason": "%s: %s" % (type(e).__name__, str(e).strip()[:180]),
                "stats": None}


# ── 名录（人写的，与几何无关）─────────────────────────────────────────

def _roster(cfg) -> list:
    """`data/buildings/index.json` 现读。**不缓存**：这是"此刻的"名录（铁律 50/73）。"""
    path = Path(cfg.root) / "data" / "buildings" / "index.json"
    if not path.is_file():
        return []
    raw = json.loads(path.read_bytes().decode("utf-8"))
    ent = raw if isinstance(raw, list) else raw.get("buildings", raw)
    return ent if isinstance(ent, list) else []


# ── 管理模块清单 ─────────────────────────────────────────────────────
#
# ★ 这是**平台的功能地图**，不是数据。它在这里定义、由前端渲染，两边只有一份。
#   `cap` 是"看这个模块至少要什么能力"：与 authz 的能力阶梯（view < edit < manage）同源。
#   `mock` 标明这一块的数据**还是模拟的** —— 页面上必须显式打标，
#   否则"样例数"会被读成"实测数"（本仓反复栽过：判词与读数必须印在一起）。
MODULES = [
    {"key": "overview", "name": "纵览驾驶舱", "cap": "view",
     "desc": "正射影像上的校区一张图：轮廓、占地与坐标", "mock": False},
    # ★ 三维单列一条（2026-10-01）：从前它是「总览」的本体（`isDoc('overview')` 为假）。
    #   用户要求纵览驾驶舱改用正射影像 ⇒ 三维如果还挂在总览上，它就没有入口了 ——
    #   那等于把已经做好的东西**删掉**，而不是换个位置。所以给它自己的模块。
    {"key": "campus3d", "name": "三维场景", "cap": "view",
     "desc": "体量关系：谁高谁矮、坡往哪边落、栋与栋的间距", "mock": False},
    # ★ 数据大屏（2026-10-01）：用户原话「点击大屏，**所有的房屋都在上面显示**」。
    #   它与「纵览驾驶舱」不是新旧两版，是两个用途：驾驶舱**用来查**（单条、坐标），
    #   大屏**用来看**（全校区一屏、全局口径同时说完）。两条都保留。
    {"key": "datascreen", "name": "数据大屏", "cap": "view",
     "desc": "全校区一张图：轮廓总量、高度口径与这份数据的覆盖边界", "mock": False},
    {"key": "building", "name": "建筑与空间", "cap": "view",
     "desc": "楼栋 → 楼层 → 房间，逐间看用途与使用单位", "mock": False},
    {"key": "facility", "name": "设施设备", "cap": "view",
     "desc": "电梯、空调机组、配电、水泵等设备的台账与状态", "mock": True},
    {"key": "pipeline", "name": "管网与回线", "cap": "edit",
     "desc": "井、通道、线以及回线 —— 走向、埋深、权属与巡检", "mock": True},
    {"key": "energy", "name": "能耗监测", "cap": "view",
     "desc": "分楼分项用电/用水曲线，同比环比与超限告警", "mock": True},
    {"key": "security", "name": "安全与门禁", "cap": "view",
     "desc": "门禁点位、消防设施、监控覆盖与告警事件", "mock": True},
    {"key": "pipeline_flow", "name": "数据与流程", "cap": "manage",
     "desc": "CD 图纸导入、派生任务与审批流程的管理", "mock": True},
    {"key": "iam", "name": "账号与权限", "cap": "manage",
     "desc": "账号、角色、授权范围（能力 × 范围两个维度）", "mock": False},
]


@router.get("/portal/overview")
def portal_overview(cfg: SettingsDep, p: PrincipalDep) -> dict:
    """门户首屏要的全部事实。**一次请求给完**，不搞成五个接口串行等。"""
    # ★★ 这两组数必须**逐行按范围过滤**，和 `/api/buildings`、`/api/portal/anchors`
    #   用同一把尺子。我原来这里读的是**全校**的名录与覆盖率 —— 后果不是"多印一个数"：
    #   viewer 明明有 `['*']`（全校），一个只管 c006 的账号**同样**会读到「93 栋」，
    #   而它这一屏的别的每一处都只说 1。同一屏上两套口径，读的人只能自己猜哪套算。
    #   （本轮实测：`/api/buildings` 回 92、这里回 93。）
    roster = visible(p, _roster(cfg), lambda e: str(e.get("name") or ""))
    floors = [e.get("floors") for e in roster if isinstance(e.get("floors"), int)]
    a = _anchors_state(cfg, [str(e.get("name")) for e in roster
                             if isinstance(e.get("name"), str)])
    return ok({
        "me": {
            "username": p.username,
            "roles": list(p.roles),
            "caps": sorted(p.caps),
            "scopes": list(p.scopes),
            "via": p.via,
            "must_change": p.must_change,
        },
        "roster": {
            "n_buildings": len(roster),
            "n_floors": sum(floors),
            "floor_hist": {str(k): floors.count(k) for k in sorted(set(floors))},
        },
        # ★ 锚点这一项：`state` 与 `stats` 一起给。down 的时候 stats 是 None
        #   （不是零）—— 前端渲染时必须分开画。
        "anchors": a,
        "modules": [m for m in MODULES if m["cap"] in p.caps],
    })


# ── 锚点 ─────────────────────────────────────────────────────────────

class AnchorIn(BaseModel):
    """建/改锚点的请求体。

    ★ 校验在**边界**上做完（CLAUDE.md：API 输入必须校验）。`method` 只认两档，
      `seed` **不许由 API 写** —— 那是脚本预置控制点用的，让人手点出来的一律是 `manual`。
    """
    block_id: str = Field(min_length=1, max_length=160)
    building_code: str = Field(min_length=1, max_length=64)
    method: Literal["manual", "outline_match"] = "manual"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=500)


@router.get("/portal/anchors", dependencies=_VIEW)
def list_anchors(p: PrincipalDep, cfg: SettingsDep) -> dict:
    """列锚点 —— **逐行按范围过滤**（见文件头纪律 3）。"""
    A = _anchors_mod()
    with _conn(A) as conn:
        rows = A.list_anchors(conn)
    # ★ 过滤的键是 `building_code`（空间树上的楼栋节点），不是 block_id。
    #   体块 id 不在空间树里，拿它当范围节点是核不出东西的。
    rows = visible(p, rows, lambda r: r["building_code"])
    return ok(rows, meta={"total": len(rows)})


@router.post("/portal/anchors", dependencies=_MANAGE)
def create_anchor(body: AnchorIn, p: PrincipalDep) -> dict:
    """建/改锚点。要 `manage`（搭建方）。"""
    A = _anchors_mod()
    with _conn(A) as conn:
        try:
            row = A.upsert_anchor(conn, body.block_id, body.building_code,
                                  method=body.method, confidence=body.confidence,
                                  set_by=p.user_id, note=body.note)
        except ValueError as e:
            conn.rollback()
            raise bad_request(str(e)) from None
    return ok(row)


@router.delete("/portal/anchors/{block_id}", dependencies=_MANAGE)
def delete_anchor(block_id: str, p: PrincipalDep) -> dict:
    """撤锚点。

    ★ 404 与 200 的分界是**有没有真删到行**（`rowcount > 0`），不是"有没有报错" ——
      删一个不存在的 block_id 同样不报错，回 200 会让调用方以为撤掉了（铁律 29）。
    """
    A = _anchors_mod()
    with _conn(A) as conn:
        hit = A.drop_anchor(conn, block_id)
    if not hit:
        raise ApiError(404, "not_found", "没有这个 block_id 的锚点：%s" % block_id)
    return ok({"block_id": block_id, "dropped": True})


# ── 前端拿名录（供锚点时选楼）────────────────────────────────────────

@router.get("/portal/roster", dependencies=_VIEW)
def portal_roster(cfg: SettingsDep, p: PrincipalDep,
                  q: str | None = Query(None, max_length=64)) -> dict:
    """93 栋名录（带范围过滤）。锚点工具靠它做"选一栋"。

    ★ 过滤的是**楼栋本身**（节点 = `name`）：看不到的楼不该出现在下拉里 ——
      否则下拉里能读到全校区楼名，而"看得见哪些楼"正是权限要管的东西。
    """
    rows = []
    for e in _roster(cfg):
        if not isinstance(e, dict) or not e.get("name"):
            continue
        rows.append({"code": str(e["name"]), "title": str(e.get("title") or e["name"]),
                     "floors": e.get("floors"), "layer_height": e.get("layer_height")})
    rows = visible(p, rows, lambda r: r["code"])
    if q:
        ql = q.strip().lower()
        rows = [r for r in rows if ql in r["code"].lower() or ql in r["title"].lower()]
    rows.sort(key=lambda r: r["code"])
    return ok(rows, meta={"total": len(rows)})


if __name__ == "__main__":                       # pragma: no cover
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    print("portal 模块清单 %d 条" % len(MODULES))
    for m in MODULES:
        print("   %-14s cap=%-7s %s" % (m["key"], m["cap"], m["name"]))
