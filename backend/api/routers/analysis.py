# -*- coding: utf-8 -*-
"""分析数据域：面积对账（图纸自带面积表 ↔ 模型逐层楼板面积）。

读路径回的是**带时间戳的快照**（最后一次跑对账脚本的结果），不是此刻的真实。
前端必须把快照时间显示出来 —— 归档报告只反映 copy 那刻
（memory: qa-baseline-is-copy-time-not-rerun）。把快照当实时展示，就是在帮它撒谎。

现算（refresh）是写操作：挂 compute 门禁，且走子进程 —— 算它要 ezdxf + shapely，
只在全功能的本机上有。
"""
from fastapi import APIRouter

from ..deps import BuildingName, ComputeDep, SettingsDep
from ..responses import not_found, ok
from ..services import area_audit

router = APIRouter(tags=["analysis"])


@router.get("/analysis/area")
def area_fleet(cfg: SettingsDep) -> dict:
    """全库对账排名 + 无法对账清单 + 数据来源（哪份日志、什么时候跑的）。"""
    return ok(area_audit.fleet(cfg.root))


@router.get("/analysis/area/{name}")
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
