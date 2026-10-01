# -*- coding: utf-8 -*-
"""路由共用的依赖与路径参数类型。

三条纪律写在这里，写一次：

1. **楼号参数一律走 `BuildingName`** —— 它把 `{name}` 限死在 `^[A-Za-z0-9_-]+$`。
   路径拼接是这个环节唯一的注入面：`/api/buildings/../..%2fetc` 这类串
   在拼接前就被 FastAPI 挡成 422，而不是靠每个 handler 记得 `..` 检查。
2. **写操作一律挂 `require_compute`** —— 它是**路由级**依赖，不是 handler 里的
   一句 if：忘挂依赖的后果是 403 完全缺失，一眼能看出来（`main.py` 里那条
   启动期断言就是替你看这一眼的）；忘记写 if 的后果是静默放行。
3. **执行面只对本机开放** —— 见 `require_compute` 的第 ② 道。三条纪律共用
   **一个**判断函数 `exec_denied_reason`，别在别处再判一次。

同样只依赖标准库 + fastapi/pydantic。
"""
import ipaddress
import secrets
from typing import Annotated, NamedTuple

from fastapi import Depends, Path, Request
from fastapi.routing import APIRoute

from .responses import ERR_COMPUTE_DISABLED, ERR_LOCAL_ONLY, ApiError
from .settings import Settings, get_settings

# 楼号：c113 / c012f1 / ny27 这类。刻意**不允许**点号与斜杠，
# 备份文件（profile.json.bak-bands-20260917）因此天生不在可寻址空间内。
BuildingName = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,32}$")]

# 楼层号：0..99（个别楼 F11+）。上界给足但不接受负数/字符串。
FloorIndex = Annotated[int, Path(ge=0, le=99)]

# 页面静态依赖的文件名：`data/su/<楼>.json`、`data/floors/floor<N>.json`。
# ★ 首字符不许是 `_` / `.` —— 这是**有意的排除**，不是顺手写的宽松规则：
#   `data/su/` 里除了 97 份规格，还躺着 `_meta.json`（40KB 清单，记着 sha256 与
#   生成脚本的仓库内路径）和一个 `.orig/`（备份树，此刻是空目录）。
#   页面只 `fetch('data/su/<楼>.json')`（building.html:2001），清单与备份树它一次都不读。
#   ⇒ 用这个类型，那两样**天然落在可寻址空间之外** —— 而不是靠"此刻那里恰好没东西"。
#     （空目录今天无害；明天谁往里放一份备份，不窄的写法会在**没人改代码的情况下**
#      开始可读它。本仓铁律：排除规则排除了什么，必须在输出里数出来。）
# ★ 必须定义在**模块级**：本仓文件普遍有 `from __future__ import annotations`，
#   注解会被推迟成字符串、在**模块作用域**求值 —— 若把 pattern 写成 `create_app()`
#   里的局部常量，求值时看不见它，抛 `PydanticUserError`。
#   ★ 而且它**不在 import 时报错**：`import backend.api.main` 照常成功，
#     第一次**真发请求**才 500。属于「起得来但不干活」那一族，只有探针能抓到。
AssetFileName = Annotated[
    str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.json$")]

# 根级 GLB：`data/<楼>.glb`（实测根下 3 个：`lihua-building.glb`、`j6-walls.glb`、
# `j6-deci05.glb`）。建模控制台的预览与整栋三维要它 —— `index.json` 里 lihua 是
# **唯一**一条 `"dir": "data"`，它的 GLB 就躺在 `data/` 根下，而 `/data/buildings`
# 那个挂载覆盖不到。
# ★ 与 `AssetFileName` 同一族的**窄规则**，理由也一样，两个方向都锁：
#   · **单段**（字符集里没有 `/`，也没有 `\`）⇒ `data/_meta/**`、`data/refs/**`
#     这些**目录**天然落在可寻址空间之外；
#   · **必须是 `.glb`** ⇒ 根下还躺着 `spec.json`、`<楼>-profile.json` 这些**单段**
#     文件名，它们各有各的路由负责；不锁后缀就等于顺手把它们也开了。
# ★ 首字符不许是 `.`（`..glb` 这类形状靠它挡掉），中段允许 `-`/`_`/数字
#   （`j6-deci05.glb` 就是）。
GlbFileName = Annotated[
    str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.glb$")]

# 会改数据的方法。`HEAD` / `OPTIONS` 不算 —— 它们由框架自己处理，
# 而且 `StaticFiles` 也认 `HEAD`。
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# HTTP 方法的全集（**小写**，与 openapi 里 operation 的键同形）。★ 只此一份：
# `health.py` 生成 endpoints 清单要按它筛（不筛的话 `parameters` / `summary` /
# `x-*` 这些**与操作同层**的键会被当成 HTTP 方法），`deps` 的交叉核对也要按它筛。
# 两处各写一份的结局是改一处漏一处 —— 而漏掉的那一处不会报错，只会少筛几条。
HTTP_METHODS = frozenset({
    "get", "put", "post", "delete", "options", "head", "patch", "trace",
})


def settings() -> Settings:
    """进程内单例（get_settings 自带 lru_cache）。"""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings)]


# ── 执行面闸门：三个小零件 + 一个判断 ────────────────────────────────

def _addr_is_loopback(host: str) -> bool:
    """地址串是不是回环。**解析不了就算不是**（fail-closed）。"""
    # IPv6 可能带 scope（`fe80::1%eth0`），先切掉再解析。
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    # ★ 双栈监听（`::`）下，IPv4 客户端会显示成 `::ffff:127.0.0.1`。那**就是**回环，
    #   但 `IPv6Address.is_loopback` 只认 `::1`，不认映射形式 —— 不摊平就会
    #   把本机请求判成远程，开发时莫名其妙地跑不了。
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def client_is_loopback(request: Request) -> bool:
    """这一份请求是不是从本机来的 —— **只看 TCP 对端地址**。

    ★ 不读 `Host`、不读 `X-Forwarded-For`：那两个是**请求方自己写的**，能伪造。
      唯一可信的是连接的对端地址（`request.client.host`）。
    ★ 取不到就当作**非本机**。`request.client` 在测试客户端与异常路径上都可能是
      `None`，那时放行等于把闸门开成默认姿势 —— 门禁的默认值只能是"不放行"。
    """
    client = request.client
    if client is None or not client.host:
        return False
    return _addr_is_loopback(client.host)


def _token_ok(request: Request, cfg: Settings) -> bool:
    """非本机时的第二个入口：带对 `X-Admin-Token` 也放行。

    没配 `GYM3D_ADMIN_TOKEN` ⇒ 局域网**严格只读**（这是默认姿势）。
    刻意**不**做成"必须配" —— 那会让部署方下次重启直接起不来，
    而"打不开页面"和"局域网不能执行"是两件事，不该捆在一起。
    """
    if not cfg.admin_token:
        return False
    got = request.headers.get("x-admin-token") or ""
    # 用 compare_digest 而不是 `==`：逐字符比较的耗时会漏出前缀信息。
    # 先 encode 再比，因为 compare_digest 收到非 ASCII 的 str 会抛 TypeError。
    return secrets.compare_digest(got.encode("utf-8"),
                                  cfg.admin_token.encode("utf-8"))


def exec_denied_reason(request: Request, cfg: Settings) -> tuple[str, str] | None:
    """**唯一**判断"这份请求能不能执行"的地方。能 ⇒ None；不能 ⇒ (错误码, 人话)。

    ★ 为什么单独抽出来：`/api/capabilities` 要**回答同一件事**（前端的按钮开关
      读它）。判断写两份的后果本仓记过 —— 同一屏上两句话，且只有一份跟着规则走
      （见 memory: one-judgement-many-implementations）。这里让"公告的"和"执行的"
      走同一个函数，它俩就没法不一致。
    """
    if not cfg.compute:
        return (ERR_COMPUTE_DISABLED,
                "本进程以只读方式运行（GYM3D_COMPUTE=0），写操作不可用。"
                "要改数据请连本机全功能控制台。")
    if not (client_is_loopback(request) or _token_ok(request, cfg)):
        # ★ 提示语按「token 配没配」分岔。配了还叫人去设 `GYM3D_ADMIN_TOKEN`，
        #   是让人去做一件**已经做过**的事 —— 他会以为没配成功，然后再去改一遍配置。
        #   同一句 403 里的"下一步"，必须跟着事实走。
        if cfg.admin_token:
            how = ("本机已配 GYM3D_ADMIN_TOKEN：带对 X-Admin-Token 头即可执行"
                   "（这一份请求没带，或带的值不对）。")
        else:
            how = ("要放开就设 GYM3D_ADMIN_TOKEN 并带上 X-Admin-Token 头"
                   "（当前没配 ⇒ 局域网严格只读）。")
        return (ERR_LOCAL_ONLY,
                "执行面仅限本机：改参数、跑阶段这类操作只接受来自 127.0.0.1 的请求。"
                "用 http://127.0.0.1:8140/ 打开即可；局域网访问是只读的。" + how)
    return None


def require_compute(request: Request, cfg: SettingsDep) -> Settings:
    """写/执行接口的门。两道，都要过，**理由分开说**。

    ① `compute=0`（服务器）⇒ 403 `compute_disabled`。
       为什么抛错而不是"假装成功"：只读服务器收到一个本意要改数据的请求，
       如果回 200，调用方会以为改成了 —— 那是最坏的一种静默失败。
    ② **来源不是本机** ⇒ 403 `local_only`。
       ★ 为什么需要第 ②：执行面过去是靠**进程与端口**隔开的 ——
       `backend/web/control.py` 只绑 127.0.0.1，而查看器按 `GYM3D_HOST=0.0.0.0`
       给局域网看。把六个端口合成一个进程之后，**那层隔离就没有了**：
       被邀请来"看"的那个 socket 同时也能"改"。②把这道墙按来源补回来 ——
       本机（127.0.0.1）行为完全不变，局域网一律只读。
       （`compute: bool = True` 是**默认值**，所以 ① 单独挡不住这件事。）

    两句理由分开，是因为补救办法不一样：①改本机配置，②换地址或配 token。
    合成一句"无权限"等于把"谁的错"摊平，调用方只能猜。
    """
    denied = exec_denied_reason(request, cfg)
    if denied is not None:
        code, msg = denied
        raise ApiError(403, code, msg, {
            "compute": cfg.compute,
            "client_loopback": client_is_loopback(request),
            "token_configured": bool(cfg.admin_token),
            "env": cfg.env,
        })
    return cfg


ComputeDep = Annotated[Settings, Depends(require_compute)]


# ── 启动期断言：把纪律 2 从"写在注释里"变成"起不来" ──────────────────

def _is_write_route(route: object) -> bool:
    return (isinstance(route, APIRoute)
            and bool(route.methods & WRITE_METHODS))


def _gated_by_compute(route: APIRoute) -> bool:
    """这条路由的依赖树里有没有 `require_compute`。

    按**函数同一性**比，不按名字比字符串 —— 改个名、包一层都不会骗过它。
    """
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        if dep.call is require_compute:
            return True
        stack.extend(dep.dependencies)
    return False


def _inner_routes(node: object) -> list | None:
    """容器节点 → 它的子路由表；叶子（普通 `Route`）返回 `None`。

    ★ 三个属性名都得试，**不是以防万一**：FastAPI 0.141 起 `include_router` 的结果
      变成了 `_IncludedRouter` —— 它**没有** `.routes`，真路由挂在
      `original_router.routes` 上，而且那些路径**不带**父级 prefix
      （子路由里是 `/rooms`，openapi 里是 `/api/rooms`）。
    """
    for attr in ("routes", "original_router", "router"):
        val = getattr(node, attr, None)
        if val is None:
            continue
        if isinstance(val, (list, tuple)):
            return list(val)
        sub = getattr(val, "routes", None)      # 形如 `.router.routes`
        if sub is not None:
            return list(sub)
    return None


def _child_path(ctx, node, fallback: str) -> str:
    """子路由的**完整**路径 —— 优先问框架自己。

    ★ `include_context.path_for(route)` 是框架给的答案（实测 `path_for(…/rooms)` →
      `/api/rooms`），比字符串拼接稳。拼接留在退路上，只在框架换名/换签名时用到。
    ★ 退路**不是静默的**：接错了会被 `assert_writes_gated` 的第二把尺子抓住
      （那边比的是**路径集合**，前缀少接一段立刻对不上 ⇒ 拒绝启动）。
      本仓对「静默回退」有过教训（memory: outline-bridge-silent-fallback），
      这里能这么写，是因为退化的结果**有一个能红的判据**兜着。
    """
    pf = getattr(ctx, "path_for", None)
    if callable(pf):
        try:
            return pf(node)
        except Exception:  # noqa: BLE001 —— 只可能因为框架换了签名，退回落拼接
            pass
    return fallback


def _is_published(node: object, ctx) -> bool:
    """这条路由会不会出现在 openapi 清单里。

    ★ **两个来源都要看**：路由自己的 `include_in_schema`，以及它所在那次
      `include_router` 的 `include_in_schema`（后者为 False ⇒ 整组子路由都不进清单）。
      只看前者会漏掉「整组被排除」这种排法，而漏掉的方向是**误报**：
      这里报 True、openapi 里却没有 ⇒ 交叉核对把好配置当成坏的。
    ★ 非 `APIRoute`（Starlette 的 `Route`、`Mount`）一律算「不进清单」：
      openapi 只由 APIRoute 生成，而 `/api/docs`、挂载点属于**在服务但不进清单**。
    """
    if not isinstance(node, APIRoute):
        return False
    if ctx is not None and getattr(ctx, "include_in_schema", True) is False:
        return False
    return getattr(node, "include_in_schema", True) is not False


class RouteRef(NamedTuple):
    """路由树里的一条路由：**完整路径** ＋ 节点 ＋ 会不会进清单。

    ★ 三者一起给出，是因为三个消费者要的正好是这三样，而「会不会进清单」这个
      判断只许有一份实现（`_is_published`）：启动期断言按它分「两把尺子都看得见」的
      那一部分，`health.py` 的 hidden 计数按它数「被筛掉的」。写两份的结局是
      同一件事两种说法，且只有一份跟着规则走（memory: one-judgement-many-implementations）。
    """
    path: str
    node: object
    published: bool


def iter_routes(routes, prefix: str = "") -> list[RouteRef]:
    """把路由树摊平成 `RouteRef`（含被 `_IncludedRouter` 套住的那七组）。

    ★ 为什么要摊平：FastAPI 0.141 起 `include_router` **不再把子路由放进
      `app.routes`**，而是挂一个 `_IncludedRouter`（真路由在 `original_router.routes`
      上）。照老写法遍历得到一张**空表** —— 2026-09-25 实测写路由数 0（真值 2），
      于是 `assert_writes_gated` **恒真**：不报错、服务照起，而它本该拦的那种路由
      （一条没挂 `require_compute` 的 POST）从外面完全看不出来。
    ★ 为什么要**接前缀**（`prefix` 参数与 `_child_path`）：子路由表里的路径是
      `/rooms`，**不带** `/api`。不接的后果不是报错，是两处**静默失效**：
      ① `health.py` 的 hidden 判据按 `/api/` 前缀筛 ⇒ **恒为 0** —— 同一个
      「判据恒定不触发」的坏法又长回来了，而它正是那个计数被写出来要防的东西；
      ② 写路由的报错信息给出 `/checks/{building}/run`，一个**打不开**的路径
      （真身是 `/api/checks/{building}/run`）⇒ 报错本身指错了地方。
      两处都是 2026-09-25 实测到的，不是假设。
    """
    out: list[RouteRef] = []
    for node in routes:
        ctx = getattr(node, "include_context", None)
        if ctx is not None:
            # `include_router` 的壳：子路由的路径**不带**父级 prefix，得单独算。
            for kid in _inner_routes(node) or []:
                full = _child_path(ctx, kid, ctx.prefix + getattr(kid, "path", ""))
                inner = None if isinstance(kid, APIRoute) else _inner_routes(kid)
                if inner:
                    out += iter_routes(inner, full)
                else:
                    out.append(RouteRef(full, kid, _is_published(kid, ctx)))
            continue
        path = prefix + getattr(node, "path", "")
        inner = None if isinstance(node, APIRoute) else _inner_routes(node)
        if inner:
            # 挂载点/子应用：它的子路由路径相对它自己，所以带着自己的路径往下走。
            out += iter_routes(inner, path)
        else:
            out.append(RouteRef(path, node, _is_published(node, None)))
    return out


def iter_apiroutes(routes) -> list[RouteRef]:
    """只要 `APIRoute` 的那些（叶子里的 `Mount` / Starlette `Route` 去掉）。"""
    return [r for r in iter_routes(routes) if isinstance(r.node, APIRoute)]


def count_hidden_under(routes, prefix: str) -> int:
    """在服务、路径在 `prefix` 下、但**不进** openapi 清单的路由条数。

    ★ 这是「排除规则排除了什么，必须在输出里数出来」的落地：endpoints 清单由
      openapi 生成、又按 `prefix` 筛过，那么被这两道筛掉的**有多少条**就得有个数。
      ★ 这个数变成 0 时必须是**真的没有**，而不是「筛子自己坏了」——
      2026-09-25 实测它曾经恒为 0（摊平出来的路径不带前缀，前缀一筛全掉），
      而屏幕上「一个都没排除」和「排除规则根本没生效」长得一模一样。
    ★ 口径（写出来，因为它决定这个数是什么意思）：只数 `prefix` 下的。挂载点
      （`/data/buildings`、`/site`、`/`）与 `/docs/oauth2-redirect` 不在 `/api/` 下，
      因此不在这个数里 —— 这是**口径**，不是漏数。改口径就得同时改这句话。
    """
    return sum(1 for r in iter_routes(routes)
               if r.path.startswith(prefix) and not r.published)


def _ops_from_openapi(app) -> set[tuple[str, str]]:
    """openapi 里所有 (路径, 方法) —— 与摊平各算各的，同一件事。

    ★ 比**集合**而不是比条数：条数相等而内容不同（我这边少一条、多一条）会被
      漏过去，那正是「两处一致证明不了它是对的」（铁律 18）。
    ★ 方法键在 openapi 里是小写，先归一成大写再比 —— 不归一的比较是
      **恒不相等**，看起来像「两套命名」，其实是自己跟自己过不去（铁律 13 同族）。
    """
    out: set[tuple[str, str]] = set()
    for path, ops in app.openapi().get("paths", {}).items():
        for m in ops:
            if m.lower() in HTTP_METHODS:
                out.add((path, m.upper()))
    return out


def _methods_of_all(node) -> set[str]:
    """这条路由声明的 HTTP 方法（**大写**），只留 `HTTP_METHODS` 里认得的。

    ★ 大写是给 `(路径, 方法)` 这个集合用的：openapi 那边的键是小写，`_ops_from_openapi`
      已经归一成大写，这里不同样归一的话两个集合**恒不相等** —— 屏幕上看起来像
      「两套命名各说各话」，其实只是大小写没对齐（铁律 13 同族：形态不一致的比较）。
    """
    return {m.upper() for m in (getattr(node, "methods", None) or ())
            if m.lower() in HTTP_METHODS}


# ★ 允许改用「权限闸」的路径前缀 —— **必须显式列出，且只能是白名单**。
#
#   2026-10-01 加账号体系时开的这个口子。为什么不是「两种闸哪个都行」：
#     `require_compute`（执行面闸）回答的是「这台进程许不许跑生成流程」，
#     `require_cap` 回答的是「这个人许不许做这件事」—— 两件事。
#   把任一条 compute 路由的闸换成 `require_cap("view")`（**最弱的一档**）之后，
#   一个只能看的账号就能跑建模管道，而**启动是绿的** —— 这正是这道断言存在的
#   全部理由，绝不能为了新加几条路由就把它放宽成恒真。
#   ⇒ 所以：**只有列在这里的域**才允许换闸；域外的一律照旧要 `require_compute`。
#   账户域是天然的例外：登录/建号/授权**不是** compute 动作，而且 `login` 恰恰
#   必须能让**局域网**（非回环）打进来说 —— 挂 `require_compute` 会让它永远 403，
#   即「账号体系从装上的那一天起就登不上去」，且屏幕上只是一句 local_only。
#   2026-10-01 追加 `/api/portal/`（校园数字孪生平台门户）。理由同族：往平台写一条
#   **锚点**（把某个体块认领成某栋楼）不是 compute 动作 —— 它是**数据登记**，
#   而登记它的正是"搭建方"这个人，人可能坐在校区里的另一台机器上。
#   挂 `require_compute` 会让它永远 403（非回环），即「这个平台从装上的那一天起
#   就点不了锚点」，而屏幕上只是一句 local_only。
#   ★ 两个域用的判据**不同**（门户不认"仅登录"那一档），见 `authz.portal_plane_gate`。
CAP_PLANE_PREFIXES = ("/api/auth/", "/api/portal/")


def assert_writes_gated(app, extra_gate=None) -> None:
    """启动期断言：**每一条**写路由都必须挂着 `require_compute`，否则拒绝启动。

    ★ 为什么值得在启动时大喊一声：纪律 2 原来**只写在注释里**，而违反它的后果
      不是报错 —— 是一条 POST 路由**没有门**，从外面完全看不出来（无非少一道 403）。
      这里把它变成「起不来」。`settings.py` 自己的话：「能在这里拦住的，绝不拖到运行期」。
    ★ 判据只认**类型**（`APIRoute`）与**依赖**两样东西，不认路由清单 ——
      清单会过期，类型不会（铁律 23：grep 数出来的是文本事实，不是代码事实）。
    ★ 两道，第二道是给第一道**自己**用的：反射摊平靠的是 FastAPI 的私有结构，
      哪天它再改名，第一道会**安静地**退化成恒真（这正是它上一次的坏法）。
      所以拿框架自己算出来的 openapi 当**第二把尺子**：两边不一致 ⇒ 宁可不启动。
      （这不是「两处一致就证明它对」——两把尺子的算法完全不同，一边是真路由表遍历，
        一边是 openapi 生成；不一致说明我这边少了东西。）
      ★ 比的是**路径集合**（`(路径, 方法)`）而不是条数：条数相同而内容不同会漏
      （铁律 18），而且路径集合顺带把「前缀接对没有」也验了 —— 少接一段 `/api`，
      两个集合立刻对不上，这正是 2026-09-25 那次静默失效的形状。
    ★ `extra_gate(node, path)`：另一把闸的判定函数（`authz.cap_plane_gate`），
      **只在 `CAP_PLANE_PREFIXES` 列出的前缀下**代替 `require_compute`。传进来的
      判据本身必须是按**函数同一性**认闸的那种（改个属性名骗不过去）。
      ★ 签名是 `(route_node, 完整路径)` 两参，**不是一参** —— 见下面 `_gated`
        里那段：「节点自带的那条路径」与「拼好前缀的那条」不是同一个字符串，
        而其中只有一个能和前缀白名单比得上。
      ★ 由调用方传而不是本模块 import `authz`：`authz` 已经 import 了本模块，
      反向 import 会成环。这个口子开得**窄**（一个可选参数 + 一条白名单常量），
      比搬走整道断言安全。
    """
    refs = iter_routes(app.routes)
    if not refs:
        raise RuntimeError(
            "路由树里一条路由都没摊出来 ⇒ 摊平逻辑失效（`_inner_routes` "
            "认不出 FastAPI 现在的容器类型）。此时下面这道判据查不到任何写路由，"
            "等于没有闸门 —— 宁可起不来。")

    mine = {(r.path, m) for r in refs if r.published for m in _methods_of_all(r.node)}
    theirs = _ops_from_openapi(app)
    if mine != theirs:
        raise RuntimeError(
            "路由摊平与 openapi 对不上：摊平 %d 条、openapi %d 条。"
            "只在摊平里：%s；只在 openapi 里：%s ⇒ 两边不是同一张表"
            "（可能是摊平失效，也可能是**前缀没接**）。拒绝启动。"
            % (len(mine), len(theirs),
               sorted(mine - theirs)[:8], sorted(theirs - mine)[:8]))

    write = [r for r in refs if _is_write_route(r.node)]

    def _gated(r) -> bool:
        if _gated_by_compute(r.node):
            return True
        # 白名单域 + 真有一把权限闸，两个都满足才算过。
        # ★ 两个条件是 `and`，缺一不可：白名单单独成立 ⇒ 域内忘挂闸也放行；
        #   判据单独成立 ⇒ 域外挂个 require_cap("view") 就能跑管道。
        # ★ `extra_gate` **必须收下两条路径**，不是客气：
        #   `r.path` 是拼好父级前缀的（`/api/auth/login`），而 `r.node.path`
        #   **不带**前缀（`/auth/login`，FastAPI 在 include 时才拼）。拿后者去比
        #   `/api/auth/` 的白名单**永远不成立** —— 2026-10-01 实测：表现为
        #   「白名单里明明写了，却照旧拒绝启动」，而屏幕上那条报错里的路径
        #   **是带前缀的**，看起来完全对（铁律 141：字段的名字不是它的定义）。
        return (extra_gate is not None
                and r.path.startswith(CAP_PLANE_PREFIXES)
                and bool(extra_gate(r.node, r.path)))

    bad = sorted({"%s.%s @ %s" % (r.node.endpoint.__module__,
                                  r.node.endpoint.__qualname__, r.path)
                  for r in write if not _gated(r)})
    if bad:
        raise RuntimeError(
            "这些写路由没有挂 require_compute（执行面闸门），拒绝启动：%s。"
            "写路由一律用 ComputeDep（见 backend/api/deps.py 的纪律 2）；"
            "只有 %s 这些域可以改用 require_cap 并显式传 extra_gate。"
            % ("、".join(bad), "、".join(CAP_PLANE_PREFIXES)))


# ── 刑具：证明上面那道闸门**能红** ────────────────────────────────────
# ★ 不为"多一个测试"，而为这道判据自己的资格：一个只会说 OK 的闸门，和一个根本
#   没接上的闸门，在屏幕上长得**一模一样**（2026-09-25 实测，它就是这样活了不知道
#   多久）。所以几件事都要跑，还要把数打出来：
#     ① 摊平真的穿过了 `_IncludedRouter`（找到 1 条，而不是 0 条）—— 判「接上没有」；
#     ② 挂了闸门的写路由 ⇒ 必须**放过**（否则是判据太宽，会把好路由也拦下来）；
#     ③ 没挂闸门的写路由 ⇒ 必须**拒绝启动**（这一条才是「能红」）；
#     ④ 它自己的两道守卫（摊平失效 / 两把尺子对不上）**各自**拆掉一次，都得红。
#   ★ 缺一不可：只做③会误以为判据随便怎么写都能红；只做②会误以为它一定拦得住；
#     不做④ 则「守卫自己哑了」这件事永远不会有人发现 —— 它上一次就是这么哑的。
#   跑法：`python -m backend.api.deps`

def _selftest() -> int:
    from fastapi import FastAPI              # noqa: PLC0415 —— 只在自检时用
    from fastapi import APIRouter, Depends

    def _guard(checked: bool) -> FastAPI:
        """造一个最小 app：`/api/w` 是 POST，`checked=True` 时挂上 ComputeDep。"""
        app = FastAPI()
        sub = APIRouter()
        if checked:
            @sub.post("/w")
            def _w_guarded(_cfg: ComputeDep) -> dict:
                return {}
        else:
            @sub.post("/w")
            def _w_open() -> dict:
                return {}
        app.include_router(sub, prefix="/api")
        return app

    open_app, guarded_app = _guard(False), _guard(True)

    # ① 摊平要穿得进去，**并且路径要带上父级前缀**。两条分开判，因为它们坏起来
    #    是两件事：穿不进去 ⇒ 表是空的（闸门恒真）；前缀没接上 ⇒ 表不空但**内容全错**
    #    （hidden 计数恒 0、报错给一个打不开的路径）。2026-09-25 实测坏的是后一种。
    refs = iter_routes(open_app.routes)
    paths = {r.path for r in refs}
    print("①a 摊平穿过 _IncludedRouter：数到 %d 条（要 ≥1）" % len(refs))
    print("①b 路径带父级前缀：/api/w 在 %r 里 ⇒ %s"
          % (sorted(paths), "/api/w" in paths))
    ok1 = len(refs) >= 1 and "/api/w" in paths

    # ② 挂了的要放过
    try:
        assert_writes_gated(guarded_app)
        print("② 挂了 ComputeDep 的写路由：放过 ✓")
        ok2 = True
    except RuntimeError as e:
        print("② 挂了 ComputeDep 的写路由：**被拦下了**（判据太宽）%s" % e)
        ok2 = False

    # ③ 没挂的必须拦
    try:
        assert_writes_gated(open_app)
        print("③ 没挂闸门的写路由：**放过了**（判据接不上 / 恒真）")
        ok3 = False
    except RuntimeError as e:
        print("③ 没挂闸门的写路由：拒绝启动 ✓ —— %s" % str(e).split("：")[-1][:60])
        ok3 = True

    # ④ 这道闸门自己还有几道守卫，**各自**拆一次看它会不会红，且**必须红在那条分支上**。
    #    ★ 只跑 ③ 不够：③ 走的是「依赖没挂」那条分支，而「摊平失效」「路径集合对不上」
    #      是另外几条分支，各自都可能悄悄哑掉。
    #    ★ 拆法（铁律 26）：把那个变量**换掉**再跑同一句断言，而不是另写一个夹具
    #      —— 另写的夹具很容易根本没走进那条分支（第一版我就写了个「隐藏写路由」的
    #      夹具，它在树和 openapi 里**同时**被排除，两边照样相等，一分钱没验到）。
    #    ★ 还要求它红在**指定的那句文案**上（`expect`）：只判「抛了 RuntimeError」
    #      是不够的 —— 一个夹具可能因为**别的原因**抛（第一版 ④a 就是这样：我以为
    #      在验「一条都没摊出来」，其实红的是交叉核对，因为 fixture app 自己那四条
    #      `/docs` 顶层路由让 refs 非空）。红了不等于红在那条分支上（铁律 36）。
    def _must_raise(fixup: dict, label: str, expect: str) -> bool:
        saved = {k: globals()[k] for k in fixup}
        globals().update(fixup)
        try:
            assert_writes_gated(guarded_app)
        except RuntimeError as e:
            hit = expect in str(e)
            print("④ %s：拒绝启动 %s —— %s"
                  % (label, "✓" if hit else "**但红在别处**（要含 %r）" % expect,
                     str(e)[:60]))
            return hit
        else:
            print("④ %s：**没红**（这道守卫是哑的）" % label)
            return False
        finally:
            globals().update(saved)

    ok4a = _must_raise({"iter_routes": lambda _routes, prefix="": []},
                       "拆掉摊平 ⇒ 一条都摊不出来", "一条路由都没摊出来")
    ok4b = _must_raise({"_inner_routes": lambda _node: None},
                       "拆掉子路由表 ⇒ 少了 /api/w", "只在 openapi 里")
    ok4c = _must_raise({"_ops_from_openapi": lambda _app: {("/api/__nope__", "GET")}},
                       "换掉交叉核对 ⇒ openapi 报一条不存在的路径", "只在摊平里")

    # ⑤ hidden 计数（`health.py` 用它数「被排除规则筛掉了什么」）。它**曾经恒为 0**
    #    —— 摊平出来的路径不带前缀，`/api/` 一筛全掉，而「一个都没排除」和
    #    「排除规则根本没生效」在屏幕上长得一模一样。所以两个方向都要跑：
    #    有一个隐藏路由 ⇒ 数到 1；没有 ⇒ 数到 0。
    hid = FastAPI()
    sub2 = APIRouter()

    @sub2.get("/hid", include_in_schema=False)
    def _h() -> dict:
        return {}

    @sub2.get("/vis")
    def _v() -> dict:
        return {}

    hid.include_router(sub2, prefix="/api")
    n_hid = count_hidden_under(hid.routes, "/api/")
    n_none = count_hidden_under(open_app.routes, "/api/")
    print("⑤ hidden 计数：有 1 条隐藏 ⇒ %d（要 1）；一条都没有 ⇒ %d（要 0）"
          % (n_hid, n_none))
    ok5 = (n_hid == 1 and n_none == 0)

    # ⑥ ★ 2026-10-01 新开的口子（`extra_gate` + `CAP_PLANE_PREFIXES`）。
    #    开这个口子**唯一**的危险是它被放宽成恒真，而"放宽"和"正常"在屏幕上
    #    长得一模一样。所以三条一起跑，缺一条这个口子就没被约束住：
    #      a) 白名单**域内** + 真有一把权限闸 ⇒ **放过**（否则新功能根本起不来）
    #      b) 同一条路由，**不**传 extra_gate ⇒ 必须**红**（白名单单独不算数）
    #      c) 同一条路由挪到域**外** ⇒ 传了 extra_gate 也必须**红**（判据单独不算数）
    #    ★ b/c 就是这道口子的两把锁：少了 b，"域内忘挂闸"也能过；
    #      少了 c，"任何地方挂个 require_cap('view')" 就能让管道跑起来。
    def _cap_app(prefix: str):
        """造一条只挂「权限闸」（桩）的写路由。返回 (app, 那把桩闸的函数对象)。"""
        def _stub_cap_gate() -> dict:
            return {}

        app = FastAPI()
        sub = APIRouter()

        @sub.post("/w")
        def _w_cap(_g=Depends(_stub_cap_gate)) -> dict:     # noqa: B008
            return {}

        app.include_router(sub, prefix=prefix)
        return app, _stub_cap_gate

    def _gated_by(fn):
        """按**函数同一性**认闸（与 `_gated_by_compute` 同路数）。

        ★ 收两个参数、且**用上第二个**：只认 `fn` 不看路径的桩，验证不了
          「白名单真的在限定作用域」——⑥c 之所以能红，靠的正是 deps 那侧自己
          拿 `r.path` 比了前缀，与这个桩无关。这里把 path 收下来只为**签名对齐**，
          免得桩比真件宽松、把真件的一个缺陷盖过去。
        """
        def _p(node, path) -> bool:              # noqa: ARG001
            stack = [node.dependant]
            while stack:
                d = stack.pop()
                if d.call is fn:
                    return True
                stack.extend(d.dependencies)
            return False
        return _p

    def _passes(app, gate) -> bool:
        try:
            assert_writes_gated(app, extra_gate=gate)
            return True
        except RuntimeError:
            return False

    inside, gate_in = _cap_app("/api/auth")
    outside, gate_out = _cap_app("/api/console")
    ok6a = _passes(inside, _gated_by(gate_in))
    ok6b = not _passes(inside, None)
    ok6c = not _passes(outside, _gated_by(gate_out))
    print("⑥a 白名单域内 + 有权限闸 ⇒ %s（要放过）" % ("放过 ✓" if ok6a else "**被拦**"))
    print("⑥b 域内但不传 extra_gate ⇒ %s（要拒绝）"
          % ("拒绝 ✓" if ok6b else "**放过了**（白名单单独就成立）"))
    print("⑥c 域外但传了 extra_gate ⇒ %s（要拒绝）"
          % ("拒绝 ✓" if ok6c else "**放过了**（判据单独就成立）"))

    allok = (ok1 and ok2 and ok3 and ok4a and ok4b and ok4c and ok5
             and ok6a and ok6b and ok6c)
    print("刑具 %s（①②③④a④b④c⑤⑥a⑥b⑥c 全绿，这几把尺子才算有资格）"
          % ("全绿 ✓" if allok else "**有红**"))
    return 0 if allok else 1


if __name__ == "__main__":
    import sys as _sys

    # ★ 本仓判词全是中文 + `✓✗⇒`，而 Windows 控制台默认 GBK ⇒ 第一句 print 就
    #   `UnicodeEncodeError`，屏幕上看着像"这个刑具坏了"。同一段四行在
    #   `backend/api/authz.py` / `backend/db/accounts.py` 里都有 —— 这里原来漏了
    #   （铁律 168：同族共有的那一步，少调的那一个）。
    for _s in (_sys.stdout, _sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

    _sys.exit(_selftest())
