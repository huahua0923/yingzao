# -*- coding: utf-8 -*-
"""检查数据域：这台机器能跑哪几条检查 / 某栋楼的检查报告 / 跑一次。

判据本身在 `backend/checks/`（纯函数 + 注册表），这里**一个字都不重写** ——
路由只负责 HTTP 形状，取数、判陈旧、起子进程回读都在 services/checks.py。
一条判据只有一份实现（memory: one-judgement-many-implementations）。

三件事刻意做得不省事：

1. **三态说清楚**：产物不存在（404 `check_artifact_missing`，与「没有这栋楼」的
   `not_found` 是两个码）/ 陈旧（200 + `staleness.state=stale`）/ 新鲜。
   而且陈旧判据**原文写在响应里**（`staleness.criterion`）—— 后台不该替人下一个
   说不清来历的结论。
2. **「没跑」不等于「通过」**：产物只跑了 A 层时，`staleness.warnings` 会明说
   B 层那一轮没跑（报告里对应的是 unavailable，不是 pass）。这正是本项目
   反复栽的那条（memory: gauge-coverage-invisible-in-summary）。
3. **跑完回读**：POST 以**产物**为准，「命令返回 0」不作数；回读不过就报失败。
   B 层慢，所以超时**真的终止子进程**并回 504，明说产物没写成 —— 不假装跑完。

★ 权限/字段两面，按本仓既有做法：
  · 鉴权**照抄**既有 router，不自建：读用 `SettingsDep`，写用 `ComputeDep`
    （`require_compute` 是路由级依赖，compute=0 的服务器上写接口一律 403）。
  · 响应**只挑已知字段**（services.checks 的白名单投影），不透传产物原样。
    关于「报告里带楼栋编号与房间号」：产物里没有坐标；房间名来自图纸文字摘录，
    与 `/api/buildings/{name}/rooms` 回的是同一份抽取结果，而两条路由**同一把
    门禁**（本仓没有「模块白名单」这一层）。所以这里没开新的读取面 —— 要按号
    取名字走 rooms 那条，本路由不额外多带字段。
"""
from fastapi import APIRouter, Depends

from ..authz import (PrincipalDep, require_campus_wide, require_cap, sees,
                     visible)
from ..deps import BuildingName, ComputeDep, SettingsDep
from ..responses import ok
from ..services import artifacts as A
from ..services import checks as C

router = APIRouter(tags=["checks"])


# ★ 顺序有讲究：**固定路径必须写在 `/checks/{building}` 前面**。
#   楼号的 pattern 是 `[A-Za-z0-9_-]{1,32}`，`registry` / `manifest` 正好也匹配得上 ——
#   反过来注册的话，访问 /api/checks/manifest 会被当成「某栋叫 manifest 的楼」，
#   而且它**不报错**，只是回一句 404「没有这栋楼」，看着像数据问题不是路由问题。
#   新增任何固定子路径，一律加在这一段里。
@router.get("/checks/registry", dependencies=[Depends(require_cap("view"))])
def registry(cfg: SettingsDep) -> dict:
    """这台机器能跑哪几条检查：编号 / 标题 / A-B 层 / 是否逐栋 / 为什么有这条。

    数据**直接取引擎的 `CHECK_REGISTRY`**，这里不另留一份清单 —— 清单一旦有
    两份，就会有一份跟不上。另外附上 B 层在本机的可跑性（探测依赖，不 import）。
    """
    data = C.registry(cfg)
    return ok(data, meta={"count": len(data["checks"]),
                          "source": "backend/checks/CHECK_REGISTRY"})


@router.get("/checks/manifest", dependencies=[Depends(require_cap("view"))])
def manifest(cfg: SettingsDep, p: PrincipalDep) -> dict:
    """哪几栋楼已经有检查产物。

    给调用方一个"该问谁"的清单 —— 逐栋去撞 404 会在浏览器 console 里堆几十条
    红字（本机实测 95 栋只有 7 栋有产物），而红字多了就没人当真了。
    ★ 这里只说"产物在不在"，**一个字都不说检查结论**：结论只在产物里。
    ★ 权限（批次 2）：`buildings` 按范围逐行过滤，**`count` 跟着重算** ——
      不回全库的条数。这个清单的全部用途就是"该问谁"，在一个只覆盖 c006 的账号
      眼里"该问谁"的答案里不该出现 c001。回全库条数等于告诉他"还有 N 栋你看不到
      但有产物"，那是一句他会当成待办的信息。
    ★ `unrecognized`（反查不出楼号的文件名）对**非全校区**账号整块不发：
      那些名字**可能属于任何一栋楼**（正是因为它反查不出来）。要发就得先证明
      它属于你看得见的范围，而那条信息恰恰就是反查不出来的那个东西 ⇒ fail-closed。
      代价是这类账号看不到"有个文件认不出来"这条线索，而它只在**本机排查**时有
      用，本机走 break-glass（全校区），不受影响。
    """
    data = C.manifest(cfg)
    # ★ 覆盖掉 `C.manifest` 回的那个 `count`（= 盘上共几栋），不是并存两个数 ——
    #   两个都发，前端一定会显示错的那一个，而两个数在屏幕上长得一样。
    data["buildings"] = visible(p, data["buildings"], lambda b: b)
    data["count"] = len(data["buildings"])
    if not sees(p, "*"):
        data["unrecognized"] = []
        data["unrecognized_omitted"] = (
            "认不出来的文件名可能属于任何一栋楼 ⇒ 只对全校区范围的账号发")
    return ok(data, meta={"count": data["count"],
                          "source": "读产物目录（后台不现场跑检查）"})


@router.get("/checks/fleet", dependencies=[Depends(require_campus_wide())])
def fleet(cfg: SettingsDep) -> dict:
    """**全库级**检查报告（fleet.json）—— 引擎对整个库的那一次结论。

    ★ 与 `GET /api/checks/{楼}` 的分母**不同**，别当同一件事：
      · 本路由        = 全库一次跑完的那份，分母是**全库多少栋**
      · `/{楼}` 那条  = 单栋产物，分母是**那栋楼的层数**
      逐栋跑产物**不会**生成这一份（要全库跑，见 read_fleet 里写的命令）。
    """
    payload, stat = C.read_fleet(cfg)
    return ok({
        "scope": payload.get("scope"),
        "report": C.public_report(payload),
    }, meta={
        "artifact": {
            "file": C.fleet_artifact_name(),
            "dir": "/".join(("data",) + C.CHECKS_SUBDIR),
            "bytes": stat.st_size,
            "generated_iso": payload.get("generated_iso"),
            "heavy": payload.get("heavy"),
        },
        "point": "全库一次跑完的结论；分母是整个库，不是某一栋",
        "omitted": C.omitted_fields(),
        "source": "产物 JSON（后台只读产物，不现场跑）",
    })


@router.get("/checks/{building}",
            dependencies=[Depends(require_cap("view", scope_param="building"))])
def one_building(building: BuildingName, cfg: SettingsDep) -> dict:
    """某栋楼的检查报告。**只读产物**（不现跑：B 层几十分钟，HTTP 等不起）。

    调用方要能区分三件事：产物不存在（404 `check_artifact_missing`）/
    陈旧（`staleness.state=stale`）/ 新鲜（`fresh`）。
    """
    A.require_building(cfg.resolved_data_dir, building)   # 楼不存在 ⇒ 404 not_found
    payload, stat = C.read_artifact(cfg, building)
    stale = C.staleness(cfg, building, payload, stat)
    return ok({
        "building": building,
        "state": stale["state"],
        "report": C.public_report(payload),
        "staleness": stale,
    }, meta={
        "artifact": {
            "file": C.artifact_name(building),
            "dir": "/".join(("data",) + C.CHECKS_SUBDIR),
            "bytes": stat.st_size,
            "mtime_iso": stale["artifact_mtime_iso"],
            "generated_iso": stale["report_generated_iso"],
            "layer": payload.get("meta", {}).get("layer"),
            "heavy": payload.get("heavy"),
        },
        "omitted": C.omitted_fields(),
        "source": "产物 JSON（后台只读产物，不现场跑）",
    })


@router.post("/checks/{building}/run")
def run_checks(building: BuildingName, cfg: ComputeDep,
               heavy: bool = False) -> dict:
    """跑一次并落盘（**写操作**，故挂 ComputeDep）。

    `heavy=false`（默认）只跑 A 层，秒级；`heavy=true` 连 B 层一起，要
    ezdxf/shapely + 源 DXF，逐栋起子进程，可能几分钟 —— 所以有单飞锁
    （已在跑 ⇒ 409 `check_running`，不排队）和超时（超时 ⇒ 504，明说产物没写成）。

    跑完**回读产物**核对（generated_unix ≥ 本次开始时刻、scope 就是这栋），
    以此判定成败 —— 「命令返回 0」和「产物写出来了」是两件事。
    ★ 退出码 1 表示**检查到 GAP**，不是运行失败。
    """
    A.require_building(cfg.resolved_data_dir, building)
    res = C.run(cfg, building, heavy=heavy)
    return ok(res, meta={"mode": "live", "building": building,
                         "layer": res["layer"], "heavy": heavy})
