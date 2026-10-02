# -*- coding: utf-8 -*-
"""建模控制台数据域：元数据 / 楼清单 / 逐阶段现状 / 楼层资产 / 作业 / 档案规格 / 跑阶段。

原 `backend/web/control.py`（8130）那套 API 搬到 `/api/console/*`。取数、判过期、
构造命令行全在 `services/console.py` —— 本文件只管 HTTP 形状（信封、状态码、
谁挂闸门），**一个字都不重写**（memory: one-judgement-many-implementations）。

★ 四条写在这里的规矩，都是本仓踩过的：

1. **查询参数收字符串、自己解析**，不用 `int` / `bool` 注解 —— FastAPI 对类型不符
   回的是它自己的 422 形状（`{"detail": ...}`），不走 `{success,data,error,meta}`，
   而前端唯一的解析路径（`js/api.js` 的 `api()`）只会把它读成"HTTP 422"，
   说不出是哪个参数错了。先例：`routers/kg.py` 的 `?top=` / `?timeout_s=`。
   ★ **例外（有意保留）**：`BuildingName` / `FloorIndex` 这类**路径**参数仍走
   FastAPI 的 pattern 校验（回 422）。全仓既有写法就是这样（`buildings.py` /
   `checks.py`），而且那 422 说的是"这个名字不在我可寻址的范围里"，与
   "没有这栋楼"是两件事（`main.py:172-176` 那段就是这个理由）。不为此另造一套。
2. **写/执行挂 `ComputeDep`**（`deps.require_compute`）：`PUT profile|spec`、
   `POST run`。一次判断、两个分支（`compute=0` ⇒ `compute_disabled`；非回环 ⇒
   `local_only`），**不另造写闸门**。
3. **`jobs/<id>` 回日志文本，不回那条路径** —— `Job.public()["log"]` 是盘上路径
   （作业记录自己要记它），直接发到屏幕上就是"一个看起来像日志的字符串"。
   截断要说：`jobs.log_tail` 回 `(文本, 被截字节数)`，截了多少原样报出去。
4. **本域的分母要点名**：`GET /console/buildings` 的 `counts` / `registry.note` /
   `registry.skipped_no_dxf` 三个一起读 —— 本机 96 栋，缺 recognizer 依赖或
   `GYM3D_COMPUTE=0` 的机器上是 95 栋。**"少的那一栋是拿不到"与"它不存在"
   必须在屏幕上不是同一行字**（铁律 16）。

★ `meta` 的失败路径**不在这里 catch**：`meta_source.MetaUnavailable` 由 `main.py`
  上的一条异常处理统一翻成 503。理由：读 meta 的有三处（`meta` / `status` /
  构造阶段命令），在调用处各 catch 一次就是"名单式判断"，**漏一处就退化成 500**
  （铁律 29：400/500 的分界只许有一个出处）。
"""
from fastapi import APIRouter, Depends, Response

from ..authz import require_cap
from ..deps import BuildingName, ComputeDep, FloorIndex, SettingsDep
from ..responses import ERR_UPSTREAM, ApiError, bad_request, not_found, ok
from ..services import console as C
from ..services import jobs, meta_source

router = APIRouter(tags=["console"])

# ★ 本文件的路由**全部是搭建方专属**。
#   用户原话把搭建方的能力说成「输入 CAD 图 → 生成相关的东西 → 对流程进行管理」。
#   非搭建方角色「管线管理员」也有 `edit`（**限范围**）⇒ 这里**不能**挂
#   `require_cap("edit")`（它不带范围），否则一个只管几栋楼的账号就能跑建模管道。
#   只有 builder 的能力集里有 `manage`。
#   ★ 与 `ComputeDep` 是**叠加**（两条各自独立）：执行面闸答"这台进程许不许跑"，
#     权限面闸答"这个人许不许"。两个问题都要答，缺一条就是漏。
BUILDER_ONLY = [Depends(require_cap("manage"))]



# ── 元数据 / 楼清单 ───────────────────────────────────────────────

@router.get("/console/meta", dependencies=BUILDER_ONLY)
def console_meta(cfg: SettingsDep) -> dict:
    """参数表 + 阶段表 + 兜底默认值（`services/console.meta` 的转发）。

    ★ `data._source` 要读：`"live"` = 本机实时问 `console_meta`；
      `"frozen"` = 回退到冻结产物 `data/_meta/console_meta.json`（**这是回退，
      不是常态**）。两态的 `pipeline` 形状一样、`runnable` 都可能为空 ——
      不看 `_source` 就分不开（`meta_source.load_meta` 里有详说）。
    ★ `meta.frozen` 是那份冻结产物的生成信息（`provenance`），回退时它就是
      "这份参数表是什么时候冻的"的唯一答案；无产物时是 `None`（不是空对象）。
    """
    data = C.meta(cfg)
    return ok(data, meta={
        "source": data.get("_source"),
        "frozen": meta_source.provenance(cfg),
        "stages": len(data.get("pipeline") or []),
        "runnable": C.runnable_ids(cfg),
    })


@router.get("/console/buildings", dependencies=BUILDER_ONLY)
def console_buildings(cfg: SettingsDep) -> dict:
    """控制台的楼清单 = 批次楼（`data/buildings/*/profile.json`）＋ 注册表楼。

    ★ 与 `GET /api/buildings`（`services/artifacts.list_buildings`）**不是同一条**：
      那一条只枚举批次目录，看不到 lihua（注册表楼，也是原控制台首屏默认选中的那栋）。
      两条路由的分母本来就不一样，合成一条会把这个差抹掉。
    ★ 字段名是 `floor_count`（数字）而**不是** `floors` —— 8140 的 `/api/buildings`
      用 `floors` 装**数组**，原 `control.js:193` 却把它当数字拼「N 层」。
      一个词两个意思正是本轮要收的账，所以这边的名字说得清。
    ★ **取文件的地址一律读 `links`**，不要拿 `glbRel` 自己拼：`glbRel` 是给人看的
      相对位置（批次楼 `buildings/<名>/...`、注册表楼 `<名>-building.glb` 两套形状），
      而 `links` 是服务端按**真实挂载**算出来的；拼错了就是一个必然 404 的地址。
    """
    data = C.list_buildings(cfg)
    reg = data["registry"]
    return ok(data, meta={
        "counts": data["counts"],
        "registry": {"available": reg["available"], "note": reg["note"],
                     "error": reg["error"],
                     # 这两个数就是「剔掉了什么」：占位路径（源图不在本机）
                     # 与"同名批次目录盖住了注册表那条"。空数组 = 真的没有，
                     # 而不是"这个筛子坏了"。
                     "skipped_no_dxf": reg["skipped_no_dxf"],
                     "shadowed_by_batch": reg["shadowed_by_batch"]},
        # 档案损坏是**逐栋**的：不能因为一栋坏了就整张列表打不开
        # （读旧格式数据的地方都要回答"加了必填字段会怎样"，这里是"档案坏了会怎样"）。
        "broken_profiles": data["broken_profiles"],
        "note": "counts.total 就是这一屏的分母；注册表拿不到时它少的是"
                "「拿不到」而不是「不存在」",
    })


@router.get("/console/status/{name}", dependencies=BUILDER_ONLY)
def console_status(name: BuildingName, cfg: SettingsDep) -> dict:
    """逐阶段产物现状 —— 「流程」那一屏的全部数据。

    ★ `inplace` 阶段（thin / doorpunch 就地改写楼层）的 `done` 与 `stale` 都是
      `None`：它们没有独立产物，`floor0.json` 在 recognize 时就存在了，
      报"已完成"会是假信号。`null` 不是 `false`，前端要分开读。
    ★ `glbStale` 的盲区写在服务层（`glb_is_stale`）：mtime 看不出一份**被拷回来的
      旧 GLB**。要真判新旧得现码重出比 sha256（本仓另有那一条判据）。
    """
    return ok(C.status(cfg, name))


# ── 楼层资产 ──────────────────────────────────────────────────────

@router.get("/console/floor/{name}/{F}.png", dependencies=BUILDER_ONLY)
def console_floor_png(name: BuildingName, F: FloorIndex, cfg: SettingsDep) -> Response:
    """该楼 F 层的识别平面图（墙黑/门红/柱蓝/梯绿）。**现算**，所以是长活。

    ★ 两条取图路是**同一个函数**产出的：先发构建期预渲染的
      `plans/recog_floor<F>.png`，只在缺失或比真输入旧时才现场渲染。于是
      "服务器上没装 ezdxf/matplotlib"只在**需要现算**时才成为问题 ——
      这种情况回 **503**（说得出补救办法）而不是 500（那是"我们的错"）。
    ★ 这一条**不挂 ComputeDep**：它是 GET、只读、不写盘（渲染结果只进内存缓存）。
      它不是"执行面"——`compute=0` 的机器上它照样该能出图（走预渲染那一支）。
    """
    _require_building(cfg, name)
    return _binary(_floor_png(cfg, name, F),
                   "image/png",
                   "F%d 层画不出来" % F,
                   "这栋楼没有 F%d 层的识别图：预渲染图不在 `plans/` 里，"
                   "而现算这一支要 ezdxf + matplotlib。"
                   "换一栋、或换一个层号（`floors` 徽章上是这栋真有楼层数）。" % F)


@router.get("/console/floor/{name}/{F}.dxf", dependencies=BUILDER_ONLY)
def console_floor_dxf(name: BuildingName, F: FloorIndex, cfg: SettingsDep) -> Response:
    """把源 DXF 拆出 F 层实体写一个独立 DXF 回给你（「下载本层」那个按钮）。

    ★ 这一条**必须**懒 import（服务层里就是懒的）：它要 `ezdxf` ＋
      `recognizer.profile.floor_of`，而 `requirements-server.txt` 刻意不含它们。
      模块级 import 的话，缺依赖时崩的是**整个管理台**（`import backend.api.main`
      直接失败）—— 那正是本项目号称最硬的那道防线。缺依赖 ⇒ 503，
      让"这条路走不通"与"整个服务起不来"分开。
    ★ 回 `None` = 这一层**一个实体都没有**（不是"文件没生成"）：404 且明说，
      不许回一个 0 字节的 DXF —— 0 字节的文件在屏幕上是个"下载成功了"。
    """
    _require_building(cfg, name)
    return _binary(_floor_dxf(cfg, name, F),
                   "application/dxf",
                   "F%d 层没有实体" % F,
                   "这栋楼的 F%d 层在这个 DXF 里一个实体都没有"
                   "（不是「文件还没生成」——那个是 200 加一份空文件）。" % F)


def _floor_png(cfg, name: str, F: int) -> bytes | None:
    """懒 import 那一支：缺依赖 ⇒ 503（`ImportError` 在服务层是"这台机器没装"）。"""
    try:
        return C.floor_png(cfg, name, F)
    except (ImportError, ModuleNotFoundError) as ex:
        raise _missing_dep(ex, "平面图现算") from ex


def _floor_dxf(cfg, name: str, F: int) -> bytes | None:
    try:
        return C.floor_dxf(cfg, name, F)
    except (ImportError, ModuleNotFoundError) as ex:
        raise _missing_dep(ex, "拆层 DXF") from ex


def _missing_dep(ex: Exception, what: str) -> ApiError:
    """缺依赖 ⇒ **503**（不是 500）。500 说的是"我们的错"，而这是"这台机器没装"，
    两者的补救办法相反。`ERR_UPSTREAM` 是 `responses.py` 里为这种"下游/环境不满足"
    备着的码（原先是没人用）。"""
    return ApiError(503, ERR_UPSTREAM,
                    "%s要这台机器装 ezdxf/shapely（本进程缺 %s）。"
                    "服务器上这是预期的：这一条路只在装齐依赖的本机可用；"
                    "预渲染好的平面图不受影响。"
                    % (what, type(ex).__name__),
                    {"error": str(ex), "hint": "pip install -r requirements.txt"})


def _binary(data: bytes | None, media_type: str, what: str, why: str) -> Response:
    """bytes ⇒ 响应；`None` ⇒ 404 并**把原因说全**。

    ★ 为什么不回空响应体：空文件在浏览器里是"下载成功、打开是空的"，
      它在屏幕上与"后端这条路坏了"长得一样（铁律 16）。
    """
    if data is None:
        raise not_found(what, why=why)
    return Response(content=data, media_type=media_type)


def _require_building(cfg, name: str) -> None:
    """先判楼存不存在，再谈楼层 —— 两个 404 的理由**不一样**，不许合并。

    ★ 不先判的话，`run_step.load_profile(不存在的楼)` 抛出来的东西会被兜底异常
      处理翻成 500「未处理异常」：明明是个"没有这栋楼"，屏幕上却写成"我们的错"。
    """
    if not C.building_exists(cfg, name):
        raise not_found("没有这栋楼：%s" % name, building=name)


# ── 档案 / 规格 ───────────────────────────────────────────────────

@router.get("/console/profile/{name}", dependencies=BUILDER_ONLY)
def console_profile(name: BuildingName, cfg: SettingsDep) -> dict:
    """读档案：批次目录 → 覆盖档案 → 注册表。

    ★ 注册表那一步失败回 **503**（不是 404）：404 断言"没有这栋楼"，
      而实际是"它可能在注册表里、而本进程读不到" —— 我们**没查过**。
      补救办法相反：换楼号 vs 装依赖。
    """
    return ok(C.get_profile(cfg, name))


@router.put("/console/profile/{name}", dependencies=BUILDER_ONLY)
def console_put_profile(name: BuildingName, obj: dict, cfg: ComputeDep) -> dict:
    """写档案（**写操作**，故挂 ComputeDep）。

    ★ 批次楼是**合并写**：只覆盖传回来的键。约定 **`null` = 显式删掉这个键**
      （判空用 `is None` 而不是假值 —— `glb_windows=false` 必须留得住）。
    ★ 注册表楼写的是**覆盖档案** `data/<名>-profile.json`，**不改**
      `recognizer/profiles/*.py`。
    ★ 形如 `{"楼号"}` 之外的 JSON（数组、标量）会被 FastAPI 挡成它自己的 422 ——
      这是本文件里**唯一**一处非信封形状，因为它来自**请求体**而不是查询串。
      已知、且窄：前端只会发 JSON 对象（`js/api.js` 的 `post/put` 自己 stringify
      一个对象），手写 curl 发个数组才会撞上。写在这里，免得下一个人以为
      "本域每条路都是信封"。
    """
    target = C.put_profile(cfg, name, obj)
    return ok({"name": name, "written": target},
              meta={"merge": "批次楼是合并写（只覆盖传回来的键）；"
                             "`null` 表示删除该键"})


@router.get("/console/spec/{name}", dependencies=BUILDER_ONLY)
def console_spec(name: BuildingName, cfg: SettingsDep) -> dict:
    """读规格。**没有这个文件回空对象**（不是 404）："规格还没有"是常态
    （识别时按档案 style 生成），而这一屏是**表单** —— 404 会让整个表单打不开。
    `meta.exists` 才是"盘上到底有没有那份文件"。"""
    data = C.get_spec(cfg, name)
    path = C.spec_path(cfg, name)
    return ok(data, meta={"path": str(path), "exists": path.is_file(),
                          "keys": len(data)})


@router.put("/console/spec/{name}", dependencies=BUILDER_ONLY)
def console_put_spec(name: BuildingName, obj: dict, cfg: ComputeDep) -> dict:
    """写规格（**写操作**）。空对象 `{}` 是合法输入（= 清空），不是"没给"。"""
    target = C.put_spec(cfg, name, obj)
    return ok({"name": name, "written": target}, meta={"keys": len(obj)})


# ── 执行 ──────────────────────────────────────────────────────────

@router.post("/console/run", dependencies=BUILDER_ONLY)
def console_run(cfg: ComputeDep, building: str = "", step: str = "",
                windows: str = "") -> dict:
    """跑一个阶段（**执行**，故挂 ComputeDep）。回一个作业，**不是结果**。

    ★ 它**不在这里等**：`job_timeout_s` 的缺省是 7200 秒，等出来的那次请求会
      拖住整个管理进程（合并之后所有屏共用一个事件循环）。⇒ 起作业、立刻回，
      轮询 `GET /console/jobs/<id>`。
    ★ `windows` 收字符串：`"1"/"true"/"yes"/"on"` = 要窗口，空串 = 不要，
      **别的值一律 400**（不许悄悄当 false —— 那会让"我明明传了"变成"它没开"）。
    ★ 409 有两档，都点名：`job_busy`（槽位被占，说清是哪个作业在跑）、
      `stage_not_runnable`（这个阶段不能从这儿跑，附 `why_manual`）。
    """
    if not building:
        raise bad_request("要一个楼号", building=building)
    name = building.strip()
    if not C.NAME_RE.match(name):
        # 形状不对在这里就拒：`start_run` 里那句会回 400 但理由含糊，
        # 而"楼号形状不对"与"没有这栋楼"是两件事。
        raise bad_request("楼号形状不对（只接受字母/数字/下划线/连字符）",
                          building=building)
    job = C.start_run(cfg, name, (step or "").strip(), _windows(windows))
    return ok(job, meta={
        "cli": job.get("argv"),
        "timeout_s": job.get("timeout_s"),
        "poll": "%s/console/jobs/%s" % (cfg.api_prefix, job["id"]),
        "note": "作业的日志落在盘上（`Job.log`），`jobs/<id>` 那条路由会把它读成文本回给你",
    })


def _windows(v: str) -> bool:
    """`windows` 这个开关。**不许**默许没说的话（见上面 `console_run` 的 docstring）。"""
    s = (v or "").strip().lower()
    if s in ("", "0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    raise bad_request("windows 只认 1/true/yes/on（要窗口）或空/0/false/no/off"
                      "（不要窗口）", windows=v)


@router.get("/console/jobs/{job_id}", dependencies=BUILDER_ONLY)
def console_job(job_id: str, cfg: SettingsDep) -> dict:
    """一条作业的当前状态 **＋ 它的日志文本**。

    ★ 找不到回 **404**，不许回一个 `state=running` 的空壳 —— 那会让前端永远轮询
      一个不存在的作业（原 `control.js:359` 那个形状：一次失败让"运行中"永远为真、
      所有按钮永久禁用）。`job_id` 的形状在 `jobs.get` 里判（那里是它拼路径的
      唯一一处），形状不对 = 这里没有这个作业。
    ★ `state` 与"这一趟跑出了什么"是**两个问题**：`state` 说进程怎么样
      （running / ok / failed / timeout），而控制台这一屏只要前者 ——
      后者的七档在 `/api/kg/run/<id>` 上（那要看懂 `--run` 的 JSON）。
      **超级不用**：不要把 `exit_code=0` 当成"这个阶段产出了东西"，
      产没产出看 `GET /console/status/<楼>` 的 `artifacts`（铁律 20）。
    """
    rec = jobs.get(cfg, job_id)
    if rec is None:
        raise not_found("没有这个作业：%s" % job_id, job=job_id)
    text, truncated = jobs.log_tail(rec.get("log"))
    lines = text.splitlines()
    return ok(dict(rec, log_tail="\n".join(lines[-400:]),
                   log_lines=len(lines),
                   log_truncated_bytes=truncated),
              meta={"log_path": rec.get("log"),
                    # ★ `log_tail` / `log_truncated_bytes` 是**这一条路由加的**，
                    #   不是作业记录里的字段：盘上那份 `<id>.json` 里只有 `log`
                    #   这个**路径**。截断了要说（`yield` 一份被切掉开头的日志，
                    #   与一份本来就短的日志，在屏幕上必须不是同一行字）。
                    "tail_limit": jobs.LOG_TAIL_BYTES,
                    "lines_shown": min(len(lines), 400)})


# ── 开关登记表（「哪些是公共流程、哪些是单独流程」）────────────────

@router.get("/console/branches", dependencies=BUILDER_ONLY)
def console_branches(cfg: SettingsDep) -> dict:
    """读 `config/branches.json` —— 54 行开关，每行 `kind` 三档。

    ★ 这一条答的就是用户那句「哪些是单独的流程」：**`kind=单独` 就是单独流程**。
      事实源是**仓里的那个文件**，不是本仓代码里任何一张表 —— 所以它可改、可换、
      可 diff（`_说明` 那一节把这件事写在文件自己头上）。
    ★ 读不到回 **503**，不回空表：`rows: []` 与「54 行一条都不剩」在屏幕上长得
      一模一样，而补救办法相反（去补部署 vs 去查为什么被清空）。铁律 16。
    ★ `meta` 里那三个数（`sha12` / `bytes` / `total`）是给下面那条 PUT 用的
      **乐观锁**：页面拿到的 `sha12` 与写回时盘上的不一样 ⇒ 说明期间有人（或
      生成器）动过它。见 PUT 的 `expect_sha12`。
    """
    t = C.branch_table(cfg)
    # 现值列不上屏：54 行 × 10 列的原始值对"改哪一条"没用，而且 `_字段` 已经
    # 把每一列的含义写在文件里了。要看的四个（c006 / consumers / n_consumers /
    # loaders）留在行里，页面按需取。
    return ok({"rows": t["rows"]},
              meta={"path": t["path"], "sha12": t["sha12"], "bytes": t["bytes"],
                    "total": t["total"], "counts": t["counts"],
                    "authored_fields": t["authored_fields"],
                    "measured_fields": t["measured_fields"],
                    "kinds": t["kinds"], "note": t["note"],
                    "source": "config/branches.json（仓里的文件，不是代码里的表）"})


@router.put("/console/branches/{key}", dependencies=BUILDER_ONLY)
def console_put_branch(key: str, obj: dict, cfg: ComputeDep,
                       expect_sha12: str = "") -> dict:
    """改**某一行的人写四列**（**写操作**，故挂 ComputeDep）。

    收的 body 是那四列的一个子集：`label` / `kind` / `step` / `why`。
    现量列（`c006` / `consumers` / `n_consumers` / `loaders` …）**改不了** ——
    生成器每次重跑都会重写它们，页面上改会"看起来成功了、其实下次就被冲掉"
    ⇒ 传进来就是错的用法，**400 并点名**（不静默丢弃）。

    ★ `expect_sha12`（查询参数，字符串，规矩 1）：非空时必须等于**写之前那一刻**
      盘上的 sha12，不等回 **409** 并把两侧 sha 都报出来。这是防"页面开着的时候
      生成器重跑了一遍"—— 没有它，用户在旧表上改的一行会**盖在**新表上，
      而屏幕上写着"已保存"。空 = 不做这个检查（脚本/curl 用）。

    ★ 状态码分工（规矩 2 的一条延伸，只在这一处决定）：
      · 404 = 表里没这个 key；400 = 请求本身不合规矩（多带/空值/kind 不认）；
      · 409 = 表在**我读它之后**被人动过（乐观锁冲突，**不是我错了**）；
      · 503 = 表读不到 / 不在（量具坏了，不是"没有开关"）；
      · 500 = 写完之后自验没过（已回滚，`detail.rollback_ok` 说回滚成没成）。
    """
    t = C.branch_table(cfg)                        # 顺带把 503 的处置复用一处
    if expect_sha12 and expect_sha12 != t["sha12"]:
        # code 用**本路由自己的名**，不加进 responses.py 的 ERR_* 表：本仓 409 一律
        # 这样（`pair_stale` / `check_running` / `stage_not_runnable` / `job_busy`）——
        # 409 的语义是"撞上了什么"，前端要能按 code 分开说话，而共用一个
        # `conflict` 就等于让四种完全不同的补救办法长得一样（铁律 29 的反面用法）。
        raise ApiError(409, "branches_stale",
                       "表的 sha12 在页面打开之后变了（页面上是 %s，盘上现在是 %s）"
                       "⇒ 拒绝覆盖。刷新页面再改 —— 你在旧表上改的这一行会盖在新表上，"
                       "而屏幕上会写着「已保存」。" % (expect_sha12, t["sha12"]),
                       {"expect": expect_sha12, "actual": t["sha12"],
                        "path": t["path"], "bytes": t["bytes"]})
    r = C.put_branch(cfg, key, obj)
    return ok(r, meta={"path": t["path"], "checked_sha12": bool(expect_sha12),
                       "authored_fields": t["authored_fields"]})
