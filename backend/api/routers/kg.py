# -*- coding: utf-8 -*-
"""图谱数据域：图谱里有什么 / 给一个说法，扩散激活出整条链。

引擎在 `kb/`（`build_kb.py` 打包 → `kb.json`；`ask.py` 是**唯一**查询入口；
`gate.py` 是图谱自己的门禁）。本路由只管 HTTP 形状 —— 取数与调命令都在
`services/kg.py`，**一个字都不重写**（memory: one-judgement-many-implementations）。

★ **两条路由都是 GET、都只读**，理由写死在这里：
  · `ask.py --run` 会跑判据并写 `data/_meta/kg_runs.json`；
  · `ask.py --pending` 会写 `kb/pending.json`。
  两条都是**写**操作，本域一个都不开放（要跑判据走 CLI）。这不是保守 ——
  「智能体唯一被允许执行的命令来源」那条约定靠的就是这个口子不在这里
  （`kb/README.md`「智能体流程」）。

★ 计划里写的是「挂**一条**只读路由」，落地成两条（`/kg` 与 `/kg/ask`）。
  理由与本仓既有的 `/checks/{registry,manifest,fleet}` 一族相同：**清单**与**查询**
  是两个分母、两种代价（前者读一个 JSON，后者起一次子进程），合成一条之后
  「清单取不到」和「查询失败」会在屏幕上长得一样 —— 而这两种错的处理方式完全不同。
  两条都不带动态路径段，所以没有 `/checks/{楼}` 那种「固定路径被当成楼号」的顺序坑。

★ `top` 收成字符串自己解析，**不用 `int` 类型的查询参数**：FastAPI 对类型不符回的是
  它自己的 422 形状，不走 `{success,data,error,meta}` 信封 —— 前端那条唯一的解析路径
  就会摔在一个没有 `success` 字段的 422 上，只能报「HTTP 422」这种说不出所以然的话。
"""
from fastapi import APIRouter

from ..deps import SettingsDep
from ..responses import bad_request, ok
from ..services import kg as K

router = APIRouter(tags=["kg"])


@router.get("/kg")
def inventory(cfg: SettingsDep) -> dict:
    """图谱里现在有什么：症状家族 / 陷阱 / 知识条目 ＋ 计数 ＋ 尺子指纹。

    ★ 这一屏回答的是「**图里有什么**」，不是「哪栋楼有问题」——
      楼栋·层那一侧在 `/kg/ask` 的 `instances` / `derived_instances` 里，
      因为「命中哪几栋」是**按说法**算出来的，没有说法就没有它。

    ★ 图谱自己的门禁结论**不在这里重算**（C4 那两行在
      `GET /api/checks/fleet` 的产物里，那条路由已经会读）。这里只回尺子指纹
      与去哪看门禁 —— 同一个结论两份实现 = 两份会漂的写法。
    """
    data = K.inventory(cfg)
    return ok(data, meta={
        "counts": data["counts"],
        "source": "kb/kb.json（build_kb.py 打包；本路由只读，不重算任何判据）",
        "gate_at": data["gate"]["url"],
    })


@router.get("/kg/ask")
def ask(cfg: SettingsDep, q: str = "", building: str = "", top: str = "3") -> dict:
    """给一个说法（可选带楼号），回**扩散激活**出来的整条链。

    返回的 `data` 与命令行 `python -u kb/ask.py "<说法>" --json` 的标准输出
    **是同一份 JSON**（原样透传，不重新塑形）—— 「页面与 CLI 同一份」这条验收
    就是靠它成立的。

    ★ **三态必须分开读**，别只挑字段：
      · `hit`        —— 图里有；`symptom` / `cause` / `fix` / `runs` / `traps` 都在
      · `unverified` —— 图里有，但这条只有人记着、仓内没有锚点（`unverifiable` 说明原因）
      · `miss`       —— **图里没有这个说法**，带 `nearest[]` 与 `register` 命令
    `miss` 不是「没问题」。这个域**不会**把它兜成空数组 —— 空数组会被读成「没事」，
    而实际是「没查过」（CLAUDE.md「空输出不是没有数据」）。

    ★ 本路由**不跑判据**（`--run` 会写 `data/_meta/kg_runs.json`，那是写操作）。
      `data.runs[]` 里给的是**可跑的命令与预期**，要跑请用 CLI 或后台别的入口。
    """
    try:
        top_n = int((top or "3").strip())
    except ValueError:
        raise bad_request("top 要一个整数（它只影响 miss 时回几条最近似的）",
                          top=top) from None
    data, transport = K.ask(cfg, q, building=building, top=top_n)
    return ok(data, meta=dict(transport, source="kb/ask.py --json（原样透传，只读）",
                              graph="kb/kb.json"))
