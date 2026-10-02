# -*- coding: utf-8 -*-
"""图谱数据域：图谱里有什么 / 给一个说法，扩散激活出整条链 / 真跑一次判据。

引擎在 `kb/`（`build_kb.py` 打包 → `kb.json`；`ask.py` 是**唯一**查询入口；
`gate.py` 是图谱自己的门禁）。本路由只管 HTTP 形状 —— 取数与调命令都在
`services/kg.py`，**一个字都不重写**（memory: one-judgement-many-implementations）。

★ **2026-09-25 这里的事实变了，写清楚免得下一个人按旧注释办事**：
  原先本文件写着「本域一个写操作都不开放、要跑判据走 CLI」，靠的是
  「`--run` **没有 HTTP 通路**」这个更强的保证。**那个保证已经放弃** ——
  `--run` 现在挂在 `POST /kg/run` 上（P2 收编 8155 时用户拍板：按钮直接放页面上）。
  ⇒ 新的闸门是**「通路 ＋ 本机限定」**，不是没有通路：
      · `POST /kg/run` 挂 `ComputeDep`（`deps.exec_denied_reason`，**既有那一处判定**）；
      · 非回环来源一律 **403 `local_only`**（除非设了 `GYM3D_ADMIN_TOKEN` 且带对
        `X-Admin-Token`）；`GYM3D_COMPUTE=0` 时回 **403 `compute_disabled`**；
      · 只读的两条 GET 在局域网上照常可用 —— 这一片本来就是"给局域网看的"。
  ⇒ 页面那一侧必须**一开始就写明**（按钮置灰 + 后端自己那句话），
    不许"点了才发现 403"：`GET /capabilities` 会把同一次判定的结果给出来。
  ⇒ 另外两条仍然是**没有通路**的，别再照抄上面那段话把它们也开了：
    `ask.py --pending`（写 `kb/pending.json`）、`build_kb.py`（重打包）都只在 CLI。

★ `--run` 是**长活**（最坏 900 秒，且它真的写盘：`_qa/<楼>_qa.txt` 与
  `data/_meta/kg_runs.json`，都是引擎自己声明的产物）。⇒ 走 `services/jobs`
  （真超时 + 真并发上限 + 日志落文件），**不许裸挂 `subprocess`** ——
  合并成一个进程之后，卡住的是**管着所有屏**的那个进程。

★ `top` / `timeout_s` 都收成字符串自己解析，**不用 `int` 类型的查询参数**：
  FastAPI 对类型不符回的是它自己的 422 形状，不走 `{success,data,error,meta}` 信封 ——
  前端那条唯一的解析路径就会摔在一个没有 `success` 字段的 422 上，
  只能报「HTTP 422」这种说不出所以然的话。

★ **清单**与**查询**是两个分母、两种代价（前者读一个 JSON，后者起一次子进程），
  合并会让「清单取不到」和「查询失败」在屏幕上长得一样。所以分四条路由。
"""
from fastapi import APIRouter, Depends

from ..authz import require_cap
from ..deps import ComputeDep, SettingsDep
from ..responses import bad_request, not_found, ok
from ..services import jobs
from ..services import kg as K

router = APIRouter(tags=["kg"])

# ★ 本文件的路由**全部是搭建方专属**。
#   用户原话把搭建方的能力说成「输入 CAD 图 → 生成相关的东西 → 对流程进行管理」。
#   非搭建方角色「管线管理员」也有 `edit`（**限范围**）⇒ 这里**不能**挂
#   `require_cap("edit")`（它不带范围），否则一个只管几栋楼的账号就能跑建模管道。
#   只有 builder 的能力集里有 `manage`。
#   ★ 与 `ComputeDep` 是**叠加**（两条各自独立）：执行面闸答"这台进程许不许跑"，
#     权限面闸答"这个人许不许"。两个问题都要答，缺一条就是漏。
BUILDER_ONLY = [Depends(require_cap("manage"))]



@router.get("/kg", dependencies=BUILDER_ONLY)
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


@router.get("/kg/ask", dependencies=BUILDER_ONLY)
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

    ★ 本路由**不跑判据**（那是 `POST /kg/run`）；`data.runs[]` 里给的是**可跑的
      命令与预期**，是给"跑"那条路看的清单。
    """
    top_n = _top_param(top)
    data, transport = K.ask(cfg, q, building=building, top=top_n)
    return ok(data, meta=dict(transport, source="kb/ask.py --json（原样透传，只读）",
                              graph="kb/kb.json"))


@router.get("/kg/activation", dependencies=BUILDER_ONLY)
def activation(cfg: SettingsDep) -> dict:
    """**扩散激活那张图**（canvas 要的那份数据）：节点 / 边 / 缺口 / 两份机器层源。

    ★ 与 `/kg` 的区别：`/kg` 是**清单**（家族、陷阱、条目各几条），这一条是
      **图**（谁连谁、哪几个机器节点还没映射到症状）。前者的分母是"手册里有几条"，
      后者的分母是"图上画得出几个点"—— 合成一条之后，
      「清单读到了但图画不出来」在屏幕上没法说。

    ★ 节点与边在**服务端**算（理由见 `services/kg.py` 的 `graph()`）：
      图上有一层语义（机器码→症状的映射、以及**没映射的那些 = 缺口**），
      把它搬进第二个页面就是同一份判断的第二个实现。页面只负责**摆放**。

    ★ `missing` 与 `unmapped` 都要读：
      · `missing` 非空 ⇒ **机器层那份源整个不在**，图上的机器节点一个都没有
        （「缺文件」与「机器层本来就是空的」不是一回事）；
      · `unmapped` 是**缺口清单**，页面把它们画成虚线空心 —— 这是这张图存在的
        意义之一（`kb/kb.json` 的 anchor graph 那张图不画这个）。
    """
    data = K.graph(cfg)
    return ok(data, meta={
        "counts": data["counts"],
        "source": "kb/kb.json ＋ data/_meta/kg_instances.json（两份产物都只读，"
                  "不做任何重算；映射关系是产物里写好的 family 字段）",
        "missing": data["missing"],
    })


@router.post("/kg/run", dependencies=BUILDER_ONLY)
def kg_run(cfg: ComputeDep, q: str = "", building: str = "",
           top: str = "3", timeout_s: str = "") -> dict:
    """**真跑一次**图里登记的判据（`kb/ask.py --run`）。回一个作业，不是结果。

    ★ 这是**写/执行**：`ComputeDep` ⇒ 非回环来源 403（或 `GYM3D_COMPUTE=0` 时 403）。
      页面必须据 `GET /capabilities` **先置灰**，而不是点了才 403。

    ★ 它**不在这里等结果**：`--run` 最坏 900 秒，等出来的那次请求会拖住整个
      管理进程（合并之后所有屏共用一个事件循环）。⇒ 起作业、立刻回，
      轮询 `GET /kg/run/{job_id}`。作业的日志落在 `data/_jobs/<id>.log`。

    ★ `timeout_s` 只能把超时改**短**（本域上限 `RUN_TIMEOUT_S` = 900），
      夹了**会说**（回 `meta.timeout_clamped_from`）—— 悄悄夹住会让调用方
      以为它要的就是这个数。
    """
    top_n = _top_param(top)
    spec = K.run_spec(cfg, q, building=building, top=top_n,
                      timeout_s=_opt_int(timeout_s, "timeout_s"))
    job = jobs.start(cfg, mode="kg-run",
                     label="跑判据：%s" % spec["query"],
                     argv=spec["argv"], cwd=str(cfg.root),
                     timeout_s=spec["timeout_s"],
                     # ★ 这些跟着作业一起落盘：`run_report` 报"这一趟是拿哪个词跑的、
                     #   用的是哪个超时"，靠的就是它们。作业记录里缺了它，
                     #   事后只有一份日志和一个 pid。
                     extra={"query": spec["query"], "building": spec["building"],
                            "top": spec["meta"]["top"],
                            "cli": spec["meta"]["argv"],
                            "timeout_source": spec["timeout_source"]})
    return ok(job.public(), meta={
        "cli": spec["meta"]["argv"],
        "timeout_s": spec["timeout_s"],
        "timeout_source": spec["timeout_source"],
        "timeout_clamped_from": spec["timeout_clamped_from"],
        "top_clamped_from": spec["meta"].get("top_clamped_from"),
        "writes": "kb/ask.py --run 会写 _qa/<楼>_qa.txt 与 data/_meta/kg_runs.json"
                  "（引擎自己声明的产物，可重生成）",
        "poll": "%s/kg/run/%s" % (cfg.api_prefix, job.id),
    })


@router.get("/kg/run/{job_id}", dependencies=BUILDER_ONLY)
def kg_run_status(job_id: str, cfg: SettingsDep) -> dict:
    """一条 `--run` 作业的当前状态 **＋ 它到底跑出了什么**。

    ★ 找不到回 404，**不许回一个 state=running 的空壳** —— 那会让前端永远轮询
      一个不存在的作业（原 `control.js:359` 那个形状：一次失败让"运行中"永远为真）。

    ★ `data.run.outcome` 有七档，**七档必须分开读**（`services/kg.run_report`）：
      `running` / `ok` / `no_criteria` / `unparsable` / `bad_shape` / `timeout` / `lost`。
      `no_criteria`（引擎说这个说法本来就没有判据）与 `unparsable`（这次输出坏了）
      在屏幕上都是"没有结论"，但**补救办法相反**，所以后端不合并它们，
      页面也不许合并。
    """
    rec = jobs.get(cfg, job_id)
    if rec is None:
        raise not_found("没有这个作业：%s" % job_id, job=job_id)
    return ok(K.run_report(rec))


def _top_param(v: str) -> int:
    """`top` 这个查询参数。**不夹** —— 夹住是 `services/kg` 的事，那里会报出来
    （`top_clamped_from`）。夹在路由里的话，"夹过"这件事就没有出口了。
    """
    try:
        return int((v or "3").strip())
    except (AttributeError, ValueError):
        raise bad_request("top 要一个整数（它只影响 miss 时回几条最近似的）",
                          top=v) from None


def _opt_int(v: str, name: str) -> int | None:
    """可选整数：**空串 = 没给**（不是 0）—— 这两者在这一屏上必须分得开。

    ★ 空串**不许**落进 `int()` 去当 0：0 在 `services/kg.run_spec` 里是"不许"，
      于是"没给"会被报成"你给了个不合法的值"（本仓栽过同族的：`Number('')` 是 0）。
    """
    s = (v or "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        raise bad_request("%s 要一个整数秒（留空 = 用本域的缺省）" % name,
                          **{name: v}) from None
