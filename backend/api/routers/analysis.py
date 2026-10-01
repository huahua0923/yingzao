# -*- coding: utf-8 -*-
"""分析数据域：面积对账（图纸自带面积表 ↔ 模型逐层楼板面积）。

读路径回的是**带时间戳的快照**（最后一次跑对账脚本的结果），不是此刻的真实。
前端必须把快照时间显示出来 —— 归档报告只反映 copy 那刻
（memory: qa-baseline-is-copy-time-not-rerun）。把快照当实时展示，就是在帮它撒谎。

现算（refresh）是写操作：挂 compute 门禁，且走子进程 —— 算它要 ezdxf + shapely，
只在全功能的本机上有。
"""
from fastapi import APIRouter, Depends

from ..authz import PrincipalDep, require_cap, visible
from ..deps import BuildingName, ComputeDep, SettingsDep
from ..responses import not_found, ok
from ..services import area_audit

router = APIRouter(tags=["analysis"])

# ★ 权限（2026-10-01 批次 2）：这一屏是**面积对账排名**，逐栋一行。
#   全库那份按范围逐行过滤；单栋那份核那一栋。
#
#   ★ 过滤之后 `counts` **必须跟着重算** —— 它是 `rows` 的汇总，不是另一份数据。
#     回全库的 counts 配过滤后的 rows，屏幕上就是「排名里 3 行，抬头写 92 栋」：
#     一个数讲你看得见的，另一个讲全库，而**两个都长得像结论**。
#     重算走 `area_audit.counts_of`（`fleet()` 自己也调它）—— **同一份实现**，
#     不在这里再写一遍那五条 sum。
#     （铁律 018：同一个数写在两个地方，两处一致也证明不了它是对的。）


@router.get("/analysis/area", dependencies=[Depends(require_cap("view"))])
def area_fleet(cfg: SettingsDep, p: PrincipalDep) -> dict:
    """全库对账排名 + 无法对账清单 + 数据来源（哪份日志、什么时候跑的）。

    ★ 权限：三处**都要**过滤，少一处就是一条缝 ——
      `rows`（逐栋排名）／`unauditable`（对不了账的楼，**同样带楼号**）／
      `per_floor`（**以楼号为键**的字典）。只过滤 `rows` 的话，
      「对不了账」那张表会把范围外的楼号原样报出来。
    ★ `source` / `hint` 不过滤：它们是「这份快照是哪来的」，不含楼号。
    """
    data = area_audit.fleet(cfg.root)
    data["rows"] = visible(p, data["rows"], lambda r: r["name"])
    data["unauditable"] = visible(p, data["unauditable"], lambda r: r["name"])
    kept = {r["name"] for r in data["rows"]}
    data["per_floor"] = {k: v for k, v in (data.get("per_floor") or {}).items()
                         if k in kept}
    # ★ 只有**本来就有** `counts` 时才重算。没有日志时 `fleet()` 回的那份
    #   **刻意不带 `counts`**（只有 `hint`），凭空补一个 `{0,0,0,0,0}` 会把
    #   「还没有对账日志」读成「对账过，全库 0 栋」—— 那正是本项目反复栽的
    #   「没量过与全对长得一样」。这一趟的职责是**按范围过滤**，不是顺手改形状。
    if "counts" in data:
        data["counts"] = area_audit.counts_of(data)
    return ok(data)


@router.get("/analysis/area/{name}",
            dependencies=[Depends(require_cap("view", scope_param="name"))])
def area_one(name: BuildingName, cfg: SettingsDep) -> dict:
    """单栋：从快照里取它的那行 + 逐层明细（若快照里带的话）。

    快照里没有这栋 ⇒ **明确说"快照里没有"**，而不是回一个 0 差值的行
    —— 后者会被前端画成"这栋完美"。这正是本项目反复栽的
    「没量过和全对长得一样」（memory: gauge-coverage-invisible-in-summary）。
    """
    data = area_audit.fleet(cfg.root)
    hit = next((r for r in data["rows"] if r["name"] == name), None)
    floors = (data.get("per_floor") or {}).get(name)
    if hit is None:
        why = next((u["why"] for u in data["unauditable"] if u["name"] == name),
                   None)
        if why:
            return ok({"name": name, "audited": False, "why": why,
                       "floors": floors or []},
                      meta={"source": data.get("source")})
        raise not_found("对账快照里没有这栋楼：%s" % name,
                        building=name, source=(data.get("source") or {}).get("file"))
    return ok({"name": name, "audited": True, **hit, "floors": floors or []},
              meta={"source": data.get("source")})


@router.post("/analysis/area/refresh/{name}")
def area_refresh(name: BuildingName, cfg: ComputeDep) -> dict:
    """现算一栋（写操作）。算完**不写共享日志** —— 只回给这一次调用。

    为什么不追加进那份全库日志：日志是"某次全库对账"的完整快照，
    往里插一行会让下一次读它的人拿到一份"一半旧一半新"的表，
    而且没有字段能标出哪行是哪次跑的。要更新全库表就跑全库脚本。
    """
    res = area_audit.refresh(cfg.root, name, cfg.job_timeout_s)
    return ok(res, meta={"mode": "live", "building": name})
