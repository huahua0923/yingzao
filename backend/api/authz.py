# -*- coding: utf-8 -*-
"""权限闸门 —— 谁能看什么、谁能改什么。

## 三个概念，拆开说

    身份  Principal      这份请求**是谁**。来源：回环 break-glass / 会话 cookie / 静态 token
    能力  CAPS           view < edit < manage，**高含低**
    范围  空间树节点      '*' 全校区 / 'c006' 楼 / 'c006|3' 层 / 'c006|3|301' 房

★ **能力与范围是两个正交的维度。** 一个"普通管理员"能不能看 c006，
  取决于**他有没有 c006 这个范围的授权**，与"他是普通管理员"无关。
  所以判权是 `allows(cap, target)` 一个函数，两样输入缺一不可。
  （行业做法一致：Azure Digital Twins 的 RBAC、Esri Indoors 的
   「Indoors User 只看不编」，都是"能力×范围"两维；见 memory
   `campus-digital-twin-platform` 里的对标结论。）

## 两道闸，分工不同 —— 都要有

  **第一道（粗、全局、fail-closed）**：`AuthGate` 中间件。
    不在公开名单里的 `/api/**` 与 `/data/**` 请求，**没有有效身份就 401**。
    它是"路由忘了声明"的兜底 —— 新增一条路由忘了挂能力闸，它默认也是**关**的。
    ★ 为什么不只靠"每条路由自己记得声明"：那是 fail-open —— 忘了声明 = 敞着门，
      而敞着门**从外面完全看不出来**（一个 200 和一个 200，屏幕上一样）。

  **第二道（细、逐路由）**：`require_cap(...)`，FastAPI 依赖。
    声明"这条路由要什么能力、范围取哪个路径参数"。

### ★ 为什么闸必须罩住 `/data/**`，不能只罩 `/api/**`

  本进程的数据面**不止** `/api/`：`/data/buildings`（整目录挂载）、`/data/su/{f}`、
  `/data/floors/{f}`、`/data/spec.json`、`/data/{f}.glb` 全是**裸挂载/裸路由**。
  `data/buildings/<楼>/rooms.json` 里就有 `purpose`（用途）与 `dept`（使用单位）
  —— 那正是"要账号才能看"的东西。只罩 `/api/` 的话，这些**不登录就能整栋拉走**，
  而且屏幕上一切正常。
  ★ 静态外壳（HTML/JS/CSS）**不罩**：登录页自己也得能加载。它们不含数据。

## break-glass（本机通道）—— 有意保留，且必须**看得见**

`db_required` 默认 False ⇒ PG 没起时本进程照常跑。账号存在 PG 里，所以
**PG 一挂谁都进不来，包括你自己** —— 而那正是你最需要进去的时刻。
⇒ 回环通道保留：本机（127.0.0.1）请求直接当 `builder@*`，**你今天的用法一点不变**；
只有局域网来的请求才走登录（那正是"账号密码"要挡的那三类人）。
这也正是 `require_compute` 多年来的做法，本模块把它**收进同一个身份函数**，
而不是在别处再判一次（本仓记过：一个判断四份实现，只有一份跟着规则走）。

★ 但它**不许是隐形的**：`describe()` 把它印在启动日志里。
  一个"连自己有没有开都不知道"的后门，比有后门更糟。
  开关：`GYM3D_LOOPBACK_BREAKGLASS=0`（真上公网前必须关）。

跑自检：`python -m backend.api.authz`
"""
import json
import secrets
import sys
import time
import weakref
from typing import Annotated, Callable, NamedTuple

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.routing import Mount

# ★ 直接 `python backend/api/authz.py` 跑末尾那段自检入口时，`__package__` 是空的
#   ⇒ 下面那句 `from .deps import …` 抛「attempted relative import with no known
#   parent package」。屏幕上像"这个文件坏了"，而它是好的 —— 计划书里那句跑法
#   也正是这么写的（铁律 168 同族：同族共有的那一步，缺了的那一个不报错、
#   只把原因说成别的）。这里把直接运行**转成** `-m`，两条跑法都通。
#   同一个守卫在 `deps.py` / `routers/portal.py` / `routers/tiles.py` 里各有一份。
if __package__ in (None, ""):
    import os as _os
    import subprocess as _sp
    import sys as _sys

    _root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    _mod = (_os.path.relpath(_os.path.abspath(__file__), _root)[:-3]
            .replace(_os.sep, ".").replace("/", "."))
    _sys.exit(_sp.call([_sys.executable, "-m", _mod, *_sys.argv[1:]], cwd=_root))

from .deps import (WRITE_METHODS, _gated_by_compute, _is_write_route,
                   iter_routes)
from .responses import (ERR_FORBIDDEN, ERR_UNAUTHENTICATED, ApiError,
                        error_json)
from .settings import Settings, get_settings

MODULE = __name__

# ── 能力 ────────────────────────────────────────────────────────────

# 高含低：manage ⇒ edit ⇒ view。**无 view 则无 edit/manage**（不许改看不见的东西）。
CAPS = ("view", "edit", "manage")

# 角色 → 能力。与 `backend/db/accounts.py` 的 `ROLE_CAPS` 是**同一件事的两份**。
#   ★ 为什么允许两份：判权要在**不连库**时也能算（break-glass 那条路不能连库）。
#     两份的风险是漂移 ⇒ 由 `accounts_selftest` 与 `authz._selftest` **两边各自**
#     断言"与对方逐条相同"，不一致就红。这是有意留的重复，不是疏忽。
ROLE_CAPS = {
    "builder":    ("view", "edit", "manage"),
    "admin":      ("view",),
    "line_admin": ("view", "edit"),
    "viewer":     ("view",),
}


def caps_of(role_code: str) -> tuple:
    """角色码 → 能力元组。**不认识的角色码返回空元组** —— fail-closed：
    字典里没有的名字，不许被当成"默认有点权限"（那正是"兜底把漏了一条
    变成安静地走默认"，CLAUDE.md 铁律 41）。"""
    return tuple(ROLE_CAPS.get(role_code, ()))


# ── 空间树：范围节点 ─────────────────────────────────────────────────

SEP = "|"           # 节点分隔符，与 room_key（`楼|层|房号`）同形


def node_covers(scope: str, target: str) -> bool:
    """`scope` 这个授权范围覆不覆盖 `target` 这个节点（**沿树向下继承**）。

    ★ 必须用**分隔符**判前缀，不能用 `scope.startswith(...)` 之外的单看：
      授权 `c006` 会因此错误地覆盖 `c006f1` —— 而本仓**真有**叫 c004f1 / c008f1
      的楼栋号（`data/buildings/index.json`）。带上 SEP 之后，`c006` 只覆盖
      `c006` 与 `c006|…`，不覆盖 `c006f1`。
    ★ `*` 是根，覆盖一切。`target` 为空 ⇒ **不覆盖**（不知道要看什么，就不给看）。
    """
    if not target:
        return False
    if scope == "*" or scope == target:
        return True
    return target.startswith(scope + SEP)


# ── 身份 ────────────────────────────────────────────────────────────

class Principal(NamedTuple):
    """这一份请求是谁。**不可变**（NamedTuple）—— 判权过程不许顺手改身份。"""

    user_id: int | None
    username: str
    roles: tuple
    caps: frozenset
    scopes: tuple
    via: str              # 'loopback' | 'session'
    must_change: bool

    def allows(self, cap: str, target: str | None = None) -> bool:
        """有没有 `cap` 这个能力，作用在 `target` 节点上。

        `target=None` ⇒ 这条路由**不做范围检查**（例如 `/api/auth/me`），
        此时只要有该能力即可。★ 这是有意开的口子，所以调用处必须**显式**传 None。
        传空串会被 `node_covers` 判否（"不知道看什么就不给看"）—— 两种写法
        效果相反，别顺手写成 `or ""`。
        """
        if cap not in self.caps:
            return False
        if target is None:
            return True
        return any(node_covers(s, target) for s in self.scopes)

    def brief(self) -> dict:
        """给人看的一句话摘要（进响应 detail，进日志）。"""
        return {"username": self.username, "roles": list(self.roles),
                "caps": sorted(self.caps), "scopes": list(self.scopes),
                "via": self.via}


# ── 集合路由：按范围**过滤**，不是挂个闸就完事 ──────────────────────

def sees(p: Principal, node: str) -> bool:
    """`p` 的范围覆不覆盖 `node`。**唯一**一处做这件事的地方。

    ★ 与之并列的 `p.allows(cap, target)` 是"能力 ＋ 范围"两样一起判；这里是
      只判范围、不带能力 —— 集合路由用它做**逐行**过滤（能力已由
      `require_cap("view")` 在路由层判过，不必每行再判一次）。
    """
    return any(node_covers(s, node) for s in p.scopes)


def visible(p: Principal, rows, key) -> list:
    """把 `rows` 过滤成 `p` 看得见的那部分；`key(row)` 给出这一行的空间树节点。

    ★★ 为什么集合路由**不能**只挂 `require_cap("view")` 不做过滤（2026-10-01 定，
      批次 2 的核心一笔）：
        `Principal.allows(cap, None)` 是**恒真**的（`target=None` = 这条路由不做
        范围检查，见它的 docstring）。于是只覆盖 `c006` 的账号来问 `/api/rooms`，
        会原样拿到**全校区** 10562 个房间 —— 而权限清册上那一条会印成「已纳管」。
        闸是真的、也是活的，**它只是量错了对象**。
        本仓铁律 153 记的是"一个永远拒的闸能通过全部阴性对照"；这里是它的镜像：
        **一个不量范围的闸能通过全部权限判据**。两者在屏幕上都印 ✓。
      ⇒ 集合路由的验收判据因此必须是两条：①没范围的账号拿到 **403 或空集**，
        ②有范围的账号拿到**只有那几行**（第二条才是分辨力所在）。

    ★ `*` 不另开快分支：`node_covers("*", x)` 本来就为真。开快分支就是给同一件事
      写第二份实现（memory: one-judgement-many-implementations）。
    ★ `key` 返回空串的行**会被丢掉**（`node_covers` 对空 target 判否）—— 这正是
      想要的：一行说不出自己属于哪栋楼，就不该借"我读过它"漏出去。
    """
    return [r for r in rows if sees(p, key(r))]


def require_campus_wide(cap: str = "view"):
    """要 `cap` 能力，且范围必须**覆盖整个校区**（节点 `*`）。

    ★ 给谁用：**集合型结论**。典型是 `GET /api/checks/fleet` —— 那是引擎对整个库
      跑一趟得出的报告，它的每一条判词、每一个分母都是"全库多少栋"。
      把它按范围切成几份发出去，屏幕上的数字就**不再是那句结论**了
      （"37 栋里 5 栋不过"被切成"1 栋里 0 栋不过"），而它打印出来一模一样。
      ⇒ 与其切，不如**整条拒绝**：这不是"你没权限看这几行"，是"这份结论对
        部分范围的人不成立"。
    ★ 判据钉在节点 `*` 上（不是"有没有 scope 含星号"这种字符串检查）：
      `node_covers` 是唯一一处定义"覆盖"的地方，这里复用它。
    """
    return require_cap(cap, node=lambda _pp: "*")


def require_scope(p: Principal, node: str) -> None:
    """在 handler 里核一个**查询参数**（或算出来）的节点 —— 不通过就 403。

    ★ 为什么需要它，而不是全用 `require_cap(..., scope_param=...)`：
      那个工厂读的是 `request.path_params`，**只认路径参数**。
      `/api/rooms?building=c006` 的楼号在 **query** 里，路径上是 `/api/rooms`
      —— 对那条路由来说 `scope_param="building"` 会取到**缺键**，于是
      `node_covers("", …)` 判否 ⇒ **对任何人都是 403**（包括搭建方）。
      那是"安全"的，但它是**恒拒**：屏幕上分不出"我没有这栋楼的权限"和
      "这条闸写错了"。本仓铁律 153 记的正是这个形状。

    ★ 403 的形状与 `require_cap` 那一支**逐字同形**（同一个码、同一组 detail 键）
      —— 前端只认一套，两条路径各回各的形状就得在客户端写第二个解析分支。
    """
    if not sees(p, node):
        raise ApiError(
            403, ERR_FORBIDDEN,
            "这份账号没有 view 权限%s。"
            % ("（请求的节点：%s）" % node if node else ""),
            dict(p.brief(), required_cap="view", required_scope=node))


class AuthBackendUnavailable(RuntimeError):
    """认不出身份，因为**库连不上** —— 与"你没登录"是两回事。"""


def _token_ok(request: Request, cfg: Settings) -> bool:
    """静态 `X-Admin-Token`。与 `deps._token_ok` 同形（同一个头、同一个配置键）。"""
    if not cfg.admin_token:
        return False
    got = request.headers.get("x-admin-token") or ""
    return secrets.compare_digest(got.encode("utf-8"),
                                  cfg.admin_token.encode("utf-8"))


def _breakglass(request: Request, cfg: Settings) -> bool:
    if not cfg.loopback_breakglass:
        return False
    from .deps import client_is_loopback        # 复用同一个判断，绝不重写一遍
    return client_is_loopback(request) or _token_ok(request, cfg)


def principal_of(request: Request, cfg: Settings) -> Principal | None:
    """**唯一**决定"这是谁"的地方。取不到 ⇒ None（调用方按 fail-closed 处理）。

    ★ 顺序：**先 break-glass，后会话**。本机来的请求不必带 cookie ——
      这正是"你今天的用法一点不变"。
    """
    cached = request.scope.get("lihua_principal")
    if cached is not None:
        return cached                      # 同一请求里第二道闸直接用，不重算

    if _breakglass(request, cfg):
        return Principal(None, "本机", ("builder",), frozenset(ROLE_CAPS["builder"]),
                         ("*",), "loopback", False)

    token = request.cookies.get(cfg.session_cookie)
    if not token:
        return None
    try:
        from backend.db import accounts as A
        with A.connect() as conn:
            sess = A.load_session(conn, token)
            if sess is None:
                return None
            grants = A.all_grants(conn, sess["user_id"])
    except Exception as exc:                # noqa: BLE001
        # ★ 连不上库 ⇒ 认不出身份 ⇒ **不放行**（fail-closed）。
        #   但这是 503 不是 401：401 会让人去查自己的密码，而真问题是库挂了。
        raise AuthBackendUnavailable(str(exc)) from exc

    roles = tuple(sorted({r for r, _s in grants}))
    caps = frozenset(c for r in roles for c in caps_of(r))
    scopes = tuple(sorted({s for _r, s in grants}))
    # ★ 有账号、没授权 ⇒ 返回一个**空身份**（caps 空、scopes 空），而不是 None。
    #   返回 None 会让错误码退化成 401「你没登录」，而事实是"你登录了、但没人给你授权"
    #   —— 这两句话指向的行动完全不同（前者去登录，后者去找管理员）。
    return Principal(sess["user_id"], sess["username"], roles, caps, scopes,
                     "session", sess["must_change"])


# ── 依赖 ────────────────────────────────────────────────────────────

def _settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(_settings)]


def current_principal(request: Request, cfg: SettingsDep) -> Principal:
    """这一份请求的身份。**没身份 ⇒ 401**（默认拒绝，不是默认放行）。

    ★ 401 与 403 必须分开：
      401 = 我不知道你是谁 → 去登录（登录能解决）
      403 = 我知道你是谁，但你不能做这件事 → 去找管理员要授权（登录解决不了）
      合成一个码，前端只能统一弹"无权限"，而两者该给的下一步完全不同。
    """
    try:
        p = principal_of(request, cfg)
    except AuthBackendUnavailable as exc:
        raise ApiError(503, "auth_backend_unavailable",
                       "身份服务暂时不可用（连不上账号库）。"
                       "**这不是你的密码有问题** —— 等库恢复后重试即可。",
                       {"cause": str(exc)[:300]}) from exc
    if p is None:
        raise ApiError(401, ERR_UNAUTHENTICATED, "请先登录。",
                       {"how": "POST /api/auth/login"})
    return p


PrincipalDep = Annotated[Principal, Depends(current_principal)]


# ── 第二道闸：能力关（逐路由声明）────────────────────────────────────

# ★ FastAPI 的依赖是**函数对象**。给每个闸函数打一个属性当凭证，启动期断言按它认
#   （与 `deps._gated_by_compute` 按函数同一性认是同一路数）。
GATE_MARK = "__lihua_cap_gate__"
# ★ 光有属性不算数，还要**在这个进程里真的被 `require_cap` 造出来过**：
#   否则一句 `setattr(f, GATE_MARK, {})` 就能骗过启动期断言 —— 那是"用形似冒充实质"
#   （memory: verification-form-vs-semantics）。
_GATES: "weakref.WeakSet" = weakref.WeakSet()


def require_cap(cap: str, scope_param: str | None = None,
                node: "Callable[[dict], str | None] | None" = None):
    """造一个"要 `cap` 能力、范围取自路径参数"的 FastAPI 依赖。

    `scope_param`：路径参数的**名字**（楼栋路由通常是 `"name"`）。
    `node`：要拼复合节点时用它（如 `lambda pp: pp["name"] + SEP + pp["floor"]`）。
    两个都不给 ⇒ **不做范围检查**（只要求登录 + 有这个能力）。

    ★ 为什么读 `request.path_params` 而不是在闸函数的签名里声明那个参数：
      那样每个闸的签名都不一样，`require_cap` 就写不成通用工厂；更要命的是
      路径参数名一旦和路由对不上，FastAPI 会把它当**查询参数**静默处理
      （不报错，值永远缺 ⇒ 范围检查恒不生效，而屏幕上一切正常）。
      `path_params` 是路由匹配后框架自己填的：名字对不上就是**缺键**，
      缺键我们按"不给看"处理（`node_covers("", …)` 为假）。
    """
    if cap not in CAPS:
        raise ValueError("未知能力 %r，只认 %s" % (cap, CAPS))

    def _gate(request: Request, cfg: SettingsDep) -> Principal:
        p = current_principal(request, cfg)
        target = None
        if node is not None:
            target = node(dict(request.path_params))
        elif scope_param is not None:
            target = request.path_params.get(scope_param)
        if not p.allows(cap, target):
            raise ApiError(
                403, ERR_FORBIDDEN,
                "这份账号没有 %s 权限%s。"
                % (cap, "（请求的节点：%s）" % target if target else ""),
                dict(p.brief(), required_cap=cap, required_scope=target))
        return p

    _gate.__name__ = "require_cap_%s%s" % (cap, "_" + scope_param if scope_param else "")
    _gate.__doc__ = ("要 %s 能力%s" % (cap, "，范围取自路径参数 %r" % scope_param)
                     if scope_param else "要 %s 能力（不做范围检查）" % cap)
    _gate.__qualname__ = "%s.<locals>.%s" % (MODULE, _gate.__name__)
    setattr(_gate, GATE_MARK, {"cap": cap, "scope_param": scope_param})
    _GATES.add(_gate)
    return _gate


def gate_marks(route) -> list:
    """这条路由的依赖树里挂了哪几个能力关（返回它们的凭证字典，可能为空）。"""
    out, stack = [], [route.dependant]
    while stack:
        dep = stack.pop()
        m = getattr(dep.call, GATE_MARK, None)
        if m is not None and dep.call in _GATES:
            out.append(m)
        stack.extend(dep.dependencies)
    return out


def is_cap_gated(route) -> bool:
    """★ 判的是 `dep.call in _GATES`（这个进程里真造出来过），不是"有属性"。"""
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        if getattr(dep.call, GATE_MARK, None) is not None and dep.call in _GATES:
            return True
        stack.extend(dep.dependencies)
    return False


def is_login_gated(route) -> bool:
    """依赖树里有没有 `current_principal` —— **认证**，不是授权。

    ★ 这是第三种闸，必须与上面那种分开数。`change_password` 要的就是它：
      一个**刚建好、还没拿到任何授权**的账号必须能改自己的口令
      （这正是"首次登录强制改密"那个流程的第一步）。给它挂 `require_cap("view")`
      会把这种人**锁在门外**，而屏幕上只是一句 403，看不出是"你还没被授权"
      还是"你不许改密码"。
    """
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        if dep.call is current_principal:
            return True
        stack.extend(dep.dependencies)
    return False


def _auth_plane_judge(route, path: str) -> bool:
    """账户域的判据。三档里任取其一，**每一种都写着理由**，不是"没挂闸也算过"：

      ① `PUBLIC_PATHS` 里点名的 —— `login` / `logout` / `session`。它们**必须**
         不登录可达：login 是"我还不是任何人"时唯一的入口，logout 未登录点它
         应当是幂等成功。这一条**只对点名的那几条**成立（不是整个前缀）。
      ② `require_cap(...)` —— 建号 / 停用 / 重置口令 / 授权，要 `manage`。
      ③ `current_principal` —— 只要求"你已登录"。就是本人改密：那一刻这个人
         **还没有任何能力**，但这件事必须做得到。
    ★ 一个都没有 ⇒ False ⇒ 启动被拒。账户域**不许**出现"谁都能打的写接口"。
    """
    if is_public_path(path):
        return True
    return is_cap_gated(route) or is_login_gated(route)


def _portal_plane_judge(route, path: str) -> bool:
    """门户域的判据：**只认** `require_cap(...)`（能力闸），**不认**"仅登录"。

    ★ 与账户域刻意不同，而且**必须是分派的、不能是把两把尺子 OR 起来**：
      账户域的判据里有 `is_login_gated` 那一档，若把它直接复用到门户域，
      一条只挂 `current_principal` 的门户写路由就会被**账户域那把尺子**放行
      —— 启动是绿的、清册印「已纳管」，而任何一个登录的人都能改楼栋身份。
      这正是本仓记过的「共用的判据段只在买侧成立」（铁律 155/162/166）。
    ★ 门户域不保留"仅登录"那一档，是因为它服务的那件事（本人改自己的口令）
      在门户域**不存在**：往平台写一条锚点 = 认领一栋楼的身份，
      它不是"本人对自己"的动作。
    """
    return is_cap_gated(route)


def cap_plane_gate(route, path: str) -> bool:
    """白名单域（`deps.CAP_PLANE_PREFIXES`）的写路由「算不算有闸」。**按域分派判据。**

    ★ `path` 是**拼好父级前缀的那一条**（`/api/auth/login`），由调用方
      (`deps.assert_writes_gated`) 传进来。**不许**改成 `route.path` 自己取：
      节点自带的那条是 `/auth/login`（FastAPI 在 `include_router` 时才拼前缀），
      拿它比这份名单**永远不成立** —— 而失败的方向是"白名单写了却照旧拒绝启动"，
      报错里印的又恰好是带前缀的那条，看起来完全对。

    ★ 前缀核对**不在这里**：`deps._gated` 里的
      `r.path.startswith(CAP_PLANE_PREFIXES)` 是另一半，两个条件 `and`。
      本函数的 `DOMAINS` 只说"我知道哪些域、各用什么尺子"，它与 `deps` 的白名单
      由 `_account_plane_selftest` **逐条对一次**（两个来源各算一次，不是抄一遍）。

    ★ 认不出域 ⇒ **False**（fail-closed）：白名单里加了新域却忘了在这里给判据，
      表现是"启动被拒"（响的），不是"门开着"（哑的）。
    """
    for pfx, judge in cap_plane_gate.DOMAINS:
        if path.startswith(pfx):
            return bool(judge(route, path))
    return False


# 白名单域 → 判据。★ **分派**，不是 `any(...)` 串起来（理由见本函数的 docstring）。
#   加一行 = 支持一个新域；漏加 = `cap_plane_gate` 认不出它 ⇒ 启动被拒（响的）。
cap_plane_gate.DOMAINS = (
    ("/api/auth/", _auth_plane_judge),
    ("/api/portal/", _portal_plane_judge),
)


# ── 第一道闸：中间件（fail-closed）───────────────────────────────────

# 不需要身份就能访问的路径（**前缀匹配**）。
# ★ 这份名单要短，每加一条都要问"它泄露了什么"。
# ★ 静态外壳（`/`、`/site`、`/building.html`、JS/CSS/GLB 之外的 HTML）**不在此列也不受闸**
#   —— 闸只认下面这两个前缀，其余路径直接放行。这是有意的：登录页自己得能加载。
PROTECTED_PREFIXES = ("/api/", "/data/")

PUBLIC_PATHS = (
    "/api/auth/login",      # 登录本身当然不能要求先登录
    "/api/auth/session",    # "我现在是谁" —— 前端每次开页面都要问；未登录回 logged_in=false
    "/api/health",          # 探活：部署脚本、PM2、curl 都要能问
    "/api/capabilities",    # 登录页要问"这台服务器现在什么姿势"
    "/api/openapi.json",    # 接口清单
    "/api/docs",            # 交互式文档（内网；要对外时再关）
    "/api/auth/logout",     # 登出：未登录时点它应当是幂等成功，不是 401
)


def is_public_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
               for p in PUBLIC_PATHS)


def is_protected_path(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p)
               for p in PROTECTED_PREFIXES)


# ── 越权留痕：两条拒绝出口**共用同一份** ────────────────────────────
#
# ★ 为什么有这个段（2026-10-01 实测）：`accounts.SCHEMA_SQL` 自己写着
#   「★ 越权尝试要记 —— 它是唯一能看出「有人在试」的地方」，而**整份代码里
#   一个写入口都没有** —— 端到端验收造了约 30 次真 403，`auth_log` 里
#   **一行 `denied` 都没有**。表建好了、枚举值定好了、**写的那一步不存在**。
#   （铁律 017「写好的函数 ≠ 被调用的函数」／铁律 46「那条最要紧的守卫
#     从来没跑过」的同一形状：它平时全绿，因为"没有行"和"没有异常"同形。）
#
# ★ 为什么落在这里、而不是每条路由里：拒绝有**两条出口** ——
#     `_deny`（本段下面）是 `AuthGate` 与 `ScopedStatic` 共同的漏斗，它们是
#       **裸 ASGI**，**不抛异常**，直接把信封发出去；
#     `main.py` 的 `_api_error` 是 FastAPI 异常处理器，罩的是路由/依赖里
#       `raise ApiError` 的那些（`require_cap` / `require_scope` / `current_principal`）。
#   两条出口，一份判据 —— 各写一遍就会漂移。

#: 每个 (来源 IP, 状态码) 一个令牌桶 —— **403 不许变成写放大**。
#: ★ 桶按 **IP** 分，不共用：一个嘈杂的浏览器不该把另一个 IP 那边的
#:   「有人在试」挤掉 —— 共用桶会让台账安静地只记下喊得最响的那一个。
#: ★ 桶空了**不是丢掉**：丢掉的次数会印在下一条成功写入的 `detail` 里。
#:   静默的限流读起来像「根本没发生」，而这里恰恰是「要看出有人在试」的地方。
_DENY_CAPACITY = 20.0
_DENY_REFILL_PER_SEC = 20.0 / 60.0
_DENY_BUCKETS: dict = {}
_DENY_MAX_BUCKETS = 1024


def _audit_token(key, now=None):
    """取一个写额。回**这次要报的「被压掉几次」**；被限流则回 `None`。

    ★ 为什么返回值不是布尔：被压掉的次数必须**印得出来**。返回 True/False 的话
      那几次就凭空消失了，而台账上看起来只是"拒绝不多"（铁律 62：分母为 0 的
      k/N 是最像结论的假数）。
    ★ `now` 只为**可测**而存在（自检喂一个假钟去驱动回填，不必真等 3 秒）。
      生产走默认值 = 真钟 —— 不测那个参数，测的就是它默认时的行为。
    """
    if now is None:
        now = time.monotonic()
    b = _DENY_BUCKETS.get(key)
    if b is None:
        if len(_DENY_BUCKETS) >= _DENY_MAX_BUCKETS:
            # 有界：按插入序淘汰最旧的那个（dict 保序），不引第三方 LRU。
            _DENY_BUCKETS.pop(next(iter(_DENY_BUCKETS)), None)
        # ★ 新桶**从满开始**（不是从空）。从空开始的话，一个 IP 的**头 20 次**
        #   拒绝恰好全部被压 —— 而"第一次试探"正是这张表最想记下的那一次。
        #   （自检的阳性那一支当场抓到的：它印出"前 0 次进"。）
        b = _DENY_BUCKETS[key] = [_DENY_CAPACITY, now, 0]
    b[0] = min(_DENY_CAPACITY, b[0] + (now - b[1]) * _DENY_REFILL_PER_SEC)
    b[1] = now
    if b[0] < 1.0:
        b[2] += 1
        return None
    b[0] -= 1.0
    n = b[2]
    b[2] = 0                                      # 只报一次，报完清零
    return n


def _client_ip_of(scope) -> str:
    client = scope.get("client")
    return (client[0] if client else "") or "?"


def _denied_detail(scope, status: int, code: str, dropped: int = 0) -> str:
    """一行给人看的留痕。**纯函数** —— 不碰库，所以自检能直接量它。"""
    p = scope.get("lihua_principal")
    who = p.brief() if p is not None else {"username": None, "via": "anon"}
    detail = "%s %s ⇒ %d %s | %s" % (
        scope.get("method", "?"), scope.get("path", "?"), status, code,
        json.dumps(who, ensure_ascii=False))
    if dropped:
        detail += " | 另有 %d 次拒绝因限流未记账" % dropped
    return detail


def _audit_write(scope, status: int, code: str, client_ip: str, p, dropped: int) -> None:
    """**唯一**落库点。**best-effort** —— 记账失败不许把 403 变成 500。

    ★ 为什么单独成函数：自检会把它换成**记录器**，这样自检既能验"这一支有没有
      真去记账"、又**不往真 `auth_log` 里插行**。
      2026-10-01 实测踩到过：自检里的 `ScopedStatic` 驱动会让 `_deny` 真的落库 ——
      连跑三趟自检，台账里凭空多了 **12 行** `denied`，client_ip 是假的 `10.0.0.9`，
      而它们和真的越权尝试**长得一模一样**（`10.0.0.9` 是 `_mk_scope` 的默认值）。
      ⇒ 夹具顺手覆写了共享的真实产物。判据"这一趟没写过库"必须由**换掉落库点**
        来保证，不能靠"我记得别跑那一支"。
    """
    try:
        from backend.db import accounts as A
        with A.connect() as conn:
            A.log(conn, "denied",
                  username=(p.username if p is not None else None),
                  user_id=(p.user_id if p is not None else None),
                  client_ip=client_ip, ok=False,
                  detail=_denied_detail(scope, status, code, dropped))
    except Exception as exc:                      # noqa: BLE001
        print("[authz] 越权留痕写失败（本次拒绝照常生效）：%s" % exc,
              file=sys.stderr)


def audit_denied(scope, status: int, code: str) -> None:
    """记一次拒绝（`auth_log.action = 'denied'`, `ok = False`）。

    ★ 401 也记。它绝大多数是噪声（浏览器还没登录），但"有人不带身份挨个试"
      恰恰只在 401 里看得见；噪声交给上面的桶压。**两类都记**、只在码上分开。
    ★ 经 `_audit_write` 落库（**不是**直接连库）—— 那一个是给自检留的换手点。
    """
    client_ip = _client_ip_of(scope)
    dropped = _audit_token((client_ip, status))
    if dropped is None:
        return
    _audit_write(scope, status, code, client_ip,
                 scope.get("lihua_principal"), dropped)


def _deny(scope, receive, send, status: int, err: ApiError):
    """把 `ApiError` 按**同一个信封**发回去（复用 `error_json`，不另写一份形状）。

    ★ 两条出口共用这一处留痕：`AuthGate`（401/503）与 `ScopedStatic`（401/403）
      都打这儿过 —— 而 `main.py` 的 `_api_error` 走不了这儿（那条是异常路径），
      所以它自己也调一次 `audit_denied`。
    """
    audit_denied(scope, status, err.code)
    return error_json(err)(scope, receive, send)


class ScopedStatic:
    """给 `StaticFiles` 包一层：URL 的**首段**当空间树节点，核不出范围就 403。

    ★ 为什么非得有它（批次 2 里最先要补的那一块）：
      `/data/buildings` 是**整目录挂载**，它绕开每一条 `/api/buildings/{name}` 的
      细闸。把那些 API 全部纳管、而这里照旧对**任何登录账号**服务，就是
      **安全表演** —— 同一份 `rooms.json`（含 `purpose` 用途 / `dept` 使用单位，
      正是"要账号才能看"的东西）换个 URL 就整栋拉得走。
      而屏幕上一切正常：清册会印「已纳管 14 条」，一个红字都没有。
      ⇒ 判据是"**同一次改动里** API 与数据面一起关"，不是"API 关了"。

    ★ 首段取不到（`/data/buildings/`、`/data/buildings/index.json`）⇒ 按**根节点**
      `*` 判：那是"这个目录里有什么"的清单，只有全校区范围的账号该看到。
      一个只覆盖 c006 的账号看到 93 条楼名清单，本身就是一次越权读数。

    ★ 为什么不判 `index.json` 这种**文件名**而是判首段：目录里 `c006/…` 是绝大多数，
      首段就是楼号；根下那几个散文件（`index.json`）本来就该只在全校区范围可见。
    """

    def __init__(self, app, root_path: str = ""):
        self.app = app
        self.root_path = root_path.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        p = scope.get("lihua_principal")
        if p is None:
            # 中间件没跑（这条路径不在受保护前缀下）—— 那是配置错了，不是"放行"。
            # 这里**必须**拒绝：静默放行会让整块数据面在任何一次前缀改动后无声敞开。
            await _deny(scope, receive, send, 401, ApiError(
                401, ERR_UNAUTHENTICATED,
                "这条数据面没经过认证闸（配置错误：路径不在受保护前缀下）。",
                {"how": "见 authz.PROTECTED_PREFIXES"}))
            return

        # ★ `Mount` 交给子 app 的 scope 长什么样 —— **实测**的（`_scratch/_b2_scopeprobe.py`，
        #   2026-10-01：真 `app.mount()` + TestClient，把子 app 收到的 scope 印出来）：
        #     `GET /data/buildings/c006/rooms.json`
        #        ⇒ scope["path"]      = '/data/buildings/c006/rooms.json'   ← **没剥**
        #          scope["root_path"] = '/data/buildings'
        #     `GET /data/buildings/` 与 `GET /data/buildings`（无斜杠）
        #        ⇒ 两者 path 都是 '/data/buildings/'，root_path 同上
        #   ★ 所以**节点完全靠下面这一次剥**（我原先那句「Mount 会把前缀从 path 里剥掉」
        #     是**错的**，靠它推就会拿到首段 `data` —— 空间树里没有这个节点 ⇒ 除全校区
        #     账号外一律 403：安全，但静默收窄，屏幕上读起来像「你没有权限」）。
        #   这个剥离与 Starlette 自己的 `staticfiles.get_route_path` 是同一个写法 ——
        #   顺着框架的约定，不自创；剥过就剥不动，所以两种形状下都对。
        path = scope.get("path") or ""
        root = (scope.get("root_path") or "").rstrip("/")
        if root and path.startswith(root):
            path = path[len(root):]
        node = path.lstrip("/").split("/", 1)[0] or "*"

        if not sees(p, node):
            await _deny(scope, receive, send, 403, ApiError(
                403, ERR_FORBIDDEN,
                "这份账号的范围不覆盖 %s。" % node,
                dict(p.brief(), required_cap="view", required_scope=node)))
            return
        await self.app(scope, receive, send)


class AuthGate:
    """第一道闸。**默认拒绝**：受保护前缀下、不在公开名单里的请求一律要有身份。

    ★ 为什么要有这一道，而不是"每条路由自己记得挂 `require_cap`"：
      漏挂的后果是**一条没有门的接口**，而它从外面完全看不出来。本仓对这件事有过
      教训 —— `assert_writes_gated` 的注释里写着：本来只写在注释里的纪律等于没有。
    ★ 为什么是纯 ASGI 而不是 `BaseHTTPMiddleware`：这里**不碰 body**，纯 ASGI
      少一层封装、没有 known 的流式问题，而且能把算出来的身份写回 `scope`
      给下游复用。CORS 那层照旧用 `add_middleware`（它要额外处理预检）。
    ★ 预检请求（OPTIONS）**直接放行**：它不带 cookie 也不带自定义头，放行不泄露
      任何东西；拦了反而让浏览器把真正的请求也发不出去（症状是"莫名跨域失败"）。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if (not is_protected_path(path) or is_public_path(path)
                or scope.get("method") == "OPTIONS"):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        cfg = get_settings()
        try:
            p = principal_of(request, cfg)
        except AuthBackendUnavailable as exc:
            await _deny(scope, receive, send, 503, ApiError(
                503, "auth_backend_unavailable",
                "身份服务暂时不可用（连不上账号库）。**这不是你的密码有问题**。",
                {"cause": str(exc)[:300]}))
            return
        if p is None:
            await _deny(scope, receive, send, 401, ApiError(
                401, ERR_UNAUTHENTICATED, "请先登录。",
                {"path": path, "how": "POST /api/auth/login 带上用户名与口令"}))
            return
        # ★ 把算出来的身份写回 scope，**让下游不必再算一次**。不写的话：
        #   同一个请求里中间件算一遍、`current_principal` 再算一遍 —— 两次连库、
        #   两次解析，两次之间账号可能刚被停用（"一个判断四份实现"的同族）。
        scope["lihua_principal"] = p
        await self.app(scope, receive, send)


# ── 启动期断言 + 清册 ────────────────────────────────────────────────

GATED = "已纳管"
WRITE_ONLY = "写路由（执行面闸）"
PUBLIC = "公开"
# ★ 第四种闸，2026-10-01 加账号体系时补的：`current_principal`（**认证**）。
#   代表路由是 `POST /api/auth/password`（本人改密）—— 它只要求"你已登录"，
#   不要求任何能力。少了这一档，它会被判成「一道闸都没有」而**拒绝启动**，
#   而屏幕上印的是一句"没挂 require_cap"— 读的人会去加 require_cap("view")，
#   把一个刚建好、尚无授权的账号锁在改密页外面（那正是"首次登录必须改密"的第一步）。
AUTH_ONLY = "仅需登录（认证闸）"
UNMANAGED = "尚未纳管"


def auth_inventory(app) -> dict:
    """给每条受保护路径归一个档，**并把清册打出来**。

    ★ 为什么要有这一份：`assert_writes_gated` 的注释里写着「没闸」和「有闸但放行」
      在屏幕上长得一样。这份清册就是那句话在这件事上的落地 —— 逐批纳管时，
      「本批纳管了哪几条、还剩哪几条」必须是**一个能数、能印、会缩减的数**，
      而不是我嘴里的进度。本仓铁律 151：「我扫完了」的作用域是我自己写的那条 glob。
    """
    rows = []
    for ref in iter_routes(app.routes):
        path = ref.path
        if not is_protected_path(path):
            continue
        if is_public_path(path):
            state = PUBLIC
        elif isinstance(ref.node, APIRoute) and is_cap_gated(ref.node):
            state = GATED
        elif isinstance(ref.node, APIRoute) and is_login_gated(ref.node):
            state = AUTH_ONLY
        elif isinstance(ref.node, APIRoute) and _is_write_route(ref.node) \
                and _gated_by_compute(ref.node):
            state = WRITE_ONLY
        elif isinstance(ref.node, Mount) and isinstance(
                getattr(ref.node, "app", None), ScopedStatic):
            # ★ 挂载点没有依赖树可查，所以它的细闸只能是**包在外面的 ASGI 层**
            #   （`ScopedStatic`）。2026-10-01 批次 2 加的这一档：在这之前它一直是
            #   UNMANAGED —— 而那意味着"API 全关了、数据面还敞着"，正是安全表演。
            #   判据钉在**类型**上，不是"它有个 app 属性"（形式≠语义）。
            state = GATED
        else:
            # ★ 别的挂载点（今天只有 `frontend/admin` 的 `/`）落到这里 ——
            #   它没有依赖树可查，靠的是**中间件**那道闸（静态外壳不罩）。
            #   所以它的档是"尚未纳管"（没有逐路由的细闸），但它**受第一道闸保护**。
            #   这个区别要印出来，否则读的人会以为它是敞的。
            state = UNMANAGED
        rows.append({
            "path": path, "state": state,
            "methods": sorted(getattr(ref.node, "methods", None) or []),
            "kind": type(ref.node).__name__,
            "handler": (getattr(ref.node, "endpoint", None).__qualname__
                        if isinstance(ref.node, APIRoute) else ""),
        })
    return {"rows": rows, "counts": _counts(rows)}


# ★ `PUBLIC_PATHS` 里**允许是写路由**的那几条 —— 单独一份，**不是重复**。
#   为什么必须有这一份：`is_public_path` 只认**路径**，而路径不区分方法。
#   为了让某个 GET 能匿名访问而往 `PUBLIC_PATHS` 加一条，会顺手把同一路径上的
#   POST 也放出去；那份名单越用越长，而"多放出去一个写接口"在屏幕上只是**多一行**。
#   所以写路由要公开，得在这里**再点一次名**（两处都跟上，才生效）。
#   今天这两条各有理由：`login` 是"我还不是任何人"时唯一的入口；
#   `logout` 未登录点它应当是**幂等成功**，回 401 只会让人以为"点了没反应"。
PUBLIC_WRITES = ("/api/auth/login", "/api/auth/logout")


def _write_ok(row: dict) -> bool:
    """这条**写路由**算不算「有闸」。四种状态里逐个点名，PUBLIC 要额外过一次名册。"""
    state = row["state"]
    if state in (GATED, AUTH_ONLY, WRITE_ONLY):
        return True
    return state == PUBLIC and row["path"] in PUBLIC_WRITES


def _counts(rows: list) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[r["state"]] = out.get(r["state"], 0) + 1
    return out


def assert_caps_gated(app) -> dict:
    """启动期断言 + 打清册。返回清册（自检要拿它核）。

    **硬的规则只有一条**：受保护前缀下的每条**写路由**必须至少有一道闸
    （能力关 或 执行面闸 `require_compute`）。少了就是「一条没有门的写接口」，
    拒绝启动。读路由**不**强制 —— 它们已被中间件罩住，只是还没有逐节点细闸，
    这属于逐批纳管的范围，所以只**印出来**，不拦。
    ★ 这条口径是写下来的口径，不是"恰好没拦"：写路由少一道闸 = 谁能写；
      读路由少一道细闸 = 谁能读**哪一栋**。前者必须当场拦，后者要按批推进
      且每一批都得看得见（清册）。
    """
    inv = auth_inventory(app)
    rows = inv["rows"]
    if not rows:
        raise RuntimeError(
            "受保护路径下一条路由都没摊出来 ⇒ 摊平失效或前缀写错了。"
            "此时下面那道判据查不到任何写路由，等于没有闸门 —— 宁可起不来。")

    # ★ 第二把尺子：要 openapi 也认得这些路径，否则可能只是我这边摊平少了东西。
    #   不重复实现 `deps` 那套核对的算法 —— 那边已经在 `create_app` 里跑过一次了
    #   （同一份 `app.routes`、同一把尺子），这里再写一遍就是第二份实现。
    # ★ 判据是**逐个状态点名**，不是"不是 UNMANAGED 就算过"。
    #   差别在 PUBLIC 这一档上：`PUBLIC_PATHS` 是**按路径**匹配的，而路径不区分
    #   方法 —— 为了让某个 GET 能匿名访问而往那份名单里加一条，会**顺手**把同一个
    #   路径上的 POST 也放出去。所以写路由要公开，必须在 `PUBLIC_WRITES` 里**再点
    #   一次名**；"不是 UNMANAGED"那种写法会让这次放松**静默生效**。
    bad = sorted("%s %s" % ("/".join(r["methods"]) or "?", r["path"])
                 for r in rows
                 if set(r["methods"]) & WRITE_METHODS and not _write_ok(r))
    if bad:
        raise RuntimeError(
            "这些写路由一道闸都没有（既没挂 require_cap、也没挂 require_compute、"
            "也没有 current_principal），拒绝启动：%s。"
            "见 backend/api/deps.py 纪律 2 与 backend/api/authz.py。"
            % "、".join(bad))

    counts = inv["counts"]
    print("[authz] 权限清册（受保护路径共 %d 条）：%s"
          % (len(rows), "、".join("%s %d" % (k, counts[k]) for k in
                                  (GATED, AUTH_ONLY, WRITE_ONLY, PUBLIC, UNMANAGED)
                                  if counts.get(k))))
    un = sorted("%s %s" % ("/".join(r["methods"]) or "?", r["path"])
                for r in rows if r["state"] == UNMANAGED)
    if un:
        print("[authz] 尚未纳管 %d 条（**受第一道闸保护**，但还没有逐节点细闸）：" % len(un))
        for line in un:
            print("          %s" % line)
    return inv


def describe(cfg: Settings) -> str:
    """启动日志里印的一行 —— **让后门看得见**（一个看不见的后门比有后门更糟）。"""
    if cfg.loopback_breakglass:
        return ("[authz] break-glass **开着**：来自 127.0.0.1 的请求直接当搭建方"
                "（全校区、全能力）；局域网请求走登录。"
                "真上公网前必须设 GYM3D_LOOPBACK_BREAKGLASS=0。")
    return "[authz] break-glass **关着**：包括本机在内一律走登录。"


# ── 自检：证明这两道闸**都能红** ─────────────────────────────────────
# 本仓铁律 153：一个「永远拒」的闸能通过**全部**阴性对照；分辨它和正确的闸，
# 唯一的方法是跑那一支「**本该放行**」的输入。所以下面每一组都成对。
# 跑法：`python -m backend.api.authz`

def _selftest() -> int:
    fails = []

    def ck(name, cond, detail=""):
        ck.n += 1
        print(("  ✓ " if cond else "  ✗ ") + name + ("" if cond else "   " + str(detail)))
        if not cond:
            fails.append(name)

    ck.n = 0

    print("\n【1】范围继承：沿树向下，但**不跨到同前缀的另一栋**")
    ck("'*' 覆盖一切", all(node_covers("*", t) for t in
                        ("c006", "c006|3", "c006|3|301", "pipe|A")))
    ck("'c006' 覆盖自己", node_covers("c006", "c006"))
    ck("'c006' 覆盖它的层", node_covers("c006", "c006|3"))
    ck("'c006' 覆盖它的房间", node_covers("c006", "c006|3|301"))
    ck("★ 'c006' **不**覆盖 'c006f1'（同前缀的另一栋）", not node_covers("c006", "c006f1"))
    ck("'c006' **不**覆盖 'c001'", not node_covers("c006", "c001"))
    ck("★ 房间范围**不**向上覆盖整栋（继承是单向的）", not node_covers("c006|3|301", "c006"))
    ck("★ target 为空 ⇒ 不给看（不是默认为真）", not node_covers("*", ""))
    ck("★ scope 为空 ⇒ 不给看（空授权不是万能钥匙）", not node_covers("", "c006"))

    print("\n【2】能力：高含低、未知角色 fail-closed")
    b = Principal(1, "u", ("builder",), frozenset(caps_of("builder")), ("*",), "session", False)
    ck("builder 有 manage", b.allows("manage", "c006"))
    ck("★ builder 也有 view（高含低）", b.allows("view", "c006"))
    v = Principal(2, "u", ("viewer",), frozenset(caps_of("viewer")), ("c006",), "session", False)
    ck("★ viewer 有 view —— 这一支是**本该放行**的那支", v.allows("view", "c006"))
    ck("viewer 没有 edit", not v.allows("edit", "c006"))
    ck("viewer 没有 manage", not v.allows("manage", "c006"))
    ck("★ viewer 越界看 c001 ⇒ 拒", not v.allows("view", "c001"))
    ck("未知角色 ⇒ 空能力（不是默认有权限）", caps_of("学工处") == ())
    ck("★ 空身份（有账号无授权）什么都看不了",
       not Principal(3, "u", (), frozenset(), (), "session", False).allows("view", "c006"))
    ck("target=None 时只查能力（/api/auth/me 那种）", v.allows("view", None))
    ck("★ target=None 也不能凭空生出能力", not v.allows("manage", None))

    print("\n【3】角色矩阵两边一致（authz ↔ db.accounts）")
    try:
        import os
        import sys
        sys.path.insert(0, os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..")))
        from backend.db import accounts as A
        ck("★ ROLE_CAPS 两边逐条相同", A.ROLE_CAPS == ROLE_CAPS,
           "db=%s\n            authz=%s" % (A.ROLE_CAPS, ROLE_CAPS))
        ck("★ CAPS 两边逐条相同", tuple(A.CAPS) == tuple(CAPS))
        ck("★ 角色字典两边同名", set(A.ROLE_CAPS) == set(ROLE_CAPS))
    except Exception as exc:                                    # noqa: BLE001
        ck("能 import backend.db.accounts 做交叉核对", False, repr(exc))

    print("\n【4】公开名单与受保护前缀")
    ck("/api/rooms 受保护", is_protected_path("/api/rooms"))
    ck("/api 本身受保护", is_protected_path("/api"))
    ck("★ /data/buildings/c006/rooms.json 受保护（**只罩 /api 会漏掉它**）",
       is_protected_path("/data/buildings/c006/rooms.json"))
    ck("/data/su/c006.json 受保护", is_protected_path("/data/su/c006.json"))
    ck("/data/lihua-building.glb 受保护", is_protected_path("/data/lihua-building.glb"))
    ck("★ /api/auth/login 公开（登录页自己得能提交）", is_public_path("/api/auth/login"))
    ck("★ /api/auth/logout 公开（未登录点登出要幂等成功，不是 401）",
       is_public_path("/api/auth/logout"))
    ck("★ /api/rooms 不公开", not is_public_path("/api/rooms"))
    ck("★ /api/auth 不等于 /api/auth/login", not is_public_path("/api/auth"))
    ck("静态外壳不受闸（登录页得能加载）", not is_protected_path("/index.html"))
    ck("静态外壳不受闸（JS/CSS）", not is_protected_path("/js/app.js"))
    ck("/building.html 不受闸", not is_protected_path("/building.html"))

    print("\n【5】闸的凭证按**函数同一性**认，且骗不过")
    g1, g2 = require_cap("view"), require_cap("view")
    ck("两次 require_cap 得到**不同**的函数对象", g1 is not g2)
    ck("★ 各自都在 _GATES 里（判据认的是对象身份）", g1 in _GATES and g2 in _GATES)

    def fake():
        """一个手工伪造的闸函数：属性对了，但它不是我造出来的。"""
    setattr(fake, GATE_MARK, {"cap": "manage", "scope_param": None})

    class _Dep:
        def __init__(self, call):
            self.call, self.dependencies = call, []

    class _Route:
        def __init__(self, call):
            self.dependant = _Dep(call)

    ck("★ 手工 setattr 的假闸 **骗不过**（这是判据的资格）",
       not is_cap_gated(_Route(fake)))
    ck("真闸认得出来", is_cap_gated(_Route(g1)))
    ck("gate_marks 印的是真闸", gate_marks(_Route(g1)) == [{"cap": "view",
                                                        "scope_param": None}])
    ck("★ 未知能力当场拒（写错一个字母不会静默变成'无要求'）",
       _raises(lambda: require_cap("veiw")))

    # ★ 从这里往后，每一段都会真的走到 `_deny`（`_middleware_selftest` 的 401、
    #   ScopedStatic 的 403 …），而 `_deny` 会去**真库**记一行 `denied`。
    #   2026-10-01 实测：连跑三趟自检，台账里凭空多了 **12 行** —— client_ip 是
    #   `10.0.0.9`（`_mk_scope` 的默认值），与真的越权尝试**长得一模一样**
    #   （夹具顺手覆写了共享的真实产物）。
    #   ⇒ 把**唯一的落库点**换成记录器：既验了"这一支真的去记账了"，又一行都不写。
    #     ★ 换手点的作用域必须罩住**第一个**会写的那一段，不是只罩我以为会写的那段 ——
    #       第一版只罩了 `_batch2_selftest`，量出来的数是"还是多了 2 行"。
    calls = []
    real_write = _audit_write
    globals()["_audit_write"] = lambda sc, st, code, ip, p, drop: calls.append(
        {"status": st, "code": code, "path": sc.get("path"), "ip": ip,
         "username": (p.username if p is not None else None), "dropped": drop})
    try:
        print("\n【6】中间件：证明它**既拦得住、也放得过**")
        _middleware_selftest(ck)

        print("\n【7】break-glass 开关真的能关（否则「本机用法不变」是句空话）")
        _breakglass_selftest(ck)

        print("\n【8】账户域那三把新尺子：每条都要有反证")
        _account_plane_selftest(ck)

        _batch2_selftest(ck)

        print("\n【10】自检**不写真台账**（换手点必须还回去）")
        # ★ 上面那段自检**自己**已经记了几条（9d 的 403/401 各支）—— 所以这里先清空，
        #   量的是**下面这一条**。不清空的话 `len(calls) == 1` 必然假红，
        #   而屏幕上看不出是"多记了"还是"我数错了范围"（铁律 050：先问作用域）。
        # ★ 这一段必须在 `try` **里面**：第一版写在 `finally` 后面，
        #   于是这两支又去打真库、`calls` 空着 —— 正是这一段要防的那件事。
        n_before = len(calls)
        calls.clear()
        _DENY_BUCKETS.clear()
        ck("★ 自检期间确实走了落库点（9d 那几支记了 %d 条 —— 换手点**接通了**，"
           "而不是我记了个寂寞）" % n_before, n_before > 0)
        audit_denied(_mk_scope("GET", "/api/rooms", "10.0.0.5"), 403, ERR_FORBIDDEN)
        ck("★ 而它**真的会去调用**落库点",
           calls == [{"status": 403, "code": ERR_FORBIDDEN, "path": "/api/rooms",
                      "ip": "10.0.0.5", "username": None, "dropped": 0}],
           "实际 %r" % (calls,))
        ck("★ 一次拒绝 **只**记一行（重复记账会把「有人在试」的次数虚高）",
           len(calls) == 1)
        _DENY_BUCKETS.clear()
    finally:
        globals()["_audit_write"] = real_write
    ck("★ 自检跑完，落库点已还原成真的（没还原的话，接下来的生产运行会一行都不记，"
       "而它同样是「全绿」）", _audit_write is real_write)

    print("\n" + "=" * 62)
    print("共 %d 条判据，失败 %d 条 %s"
          % (ck.n, len(fails), "⇒ 全过 ✓" if not fails else "⇒ " + "; ".join(fails)))
    return 1 if fails else 0


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:                        # noqa: BLE001
        return True
    return False


def _mk_scope(method: str, path: str, host: str) -> dict:
    return {"type": "http", "method": method, "path": path, "headers": [],
            "query_string": b"", "client": (host, 1234),
            "server": ("127.0.0.1", 8140), "scheme": "http",
            "root_path": "", "http_version": "1.1"}


def _call_gate(gated, method: str, path: str, host: str = "10.0.0.9"):
    """拿一个假的 ASGI 环境跑一次中间件，返回 (状态码, 解析后的响应体)。

    ★ 为什么要用假环境而不是 `TestClient`：中间件**在路由之前**，用真实 app 的话
      "被拦下"和"进到路由后自己报错"会混在一起 —— 而这两件事正是要分开的。
      这里用一个只有三条路由的空 app，路由体只 `return {"reached": True}`，
      所以 `reached` 出现 = **放行**、401 = **拦下**，两者不可能混淆。
    ★ `receive` 是**真的** ASGI receive（`Request` 构造时存了它，路由若读 body 会用到）；
      第一版我传了 `None`，那在"请求真进到路由"的分支上会炸 —— 而那正是要证明
      "放得过"的那一支（本仓铁律 153：不该放的那支才是有分辨力的那支）。
    """
    import json as _json

    import anyio
    got = {"status": 0, "raw": b"", "reached": False}

    async def recv():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            got["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            got["raw"] += msg.get("body", b"")

    async def go():
        await gated(_mk_scope(method, path, host), recv, send)

    anyio.run(go)
    try:
        body = _json.loads(got["raw"] or b"{}")
    except Exception:                        # noqa: BLE001
        body = {}
    return got["status"], body


def _middleware_selftest(ck) -> None:
    """★ 这一节是整套东西里最重要的一段。理由（本仓铁律 153）：

    一个「永远拒」的闸能通过**全部**阴性对照。所以要比的不只是"未登录被拦"，
    还要比"**公开的路径要放行**"；否则一个把所有人都挡在外面的坏闸也能全绿。
    四种输入各喂一次：
      ① 未登录打 /api/rooms          ⇒ 401，且信封形状/错误码/下一步都要对
      ② 未登录打 /api/auth/login     ⇒ **放行**（这一支才是分辨力所在）
      ③ 未登录打 /data/buildings/... ⇒ 401 —— 最容易漏的一条，它**不是 /api**
      ④ OPTIONS 预检                  ⇒ 放行（拦了浏览器会把真请求也发不出去）
    """
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/api/rooms")
    def _rooms() -> dict:
        return {"reached": True}

    @app.post("/api/auth/login")
    def _login() -> dict:
        return {"reached": True}

    @app.get("/data/buildings/{n}/rooms.json")
    def _data(n: str) -> dict:               # noqa: ARG001
        return {"reached": True}

    gated = AuthGate(app)

    # ① 阴性：未登录、非回环 ⇒ 必须 401，且**四样**都要对
    st, body = _call_gate(gated, "GET", "/api/rooms")
    ck("① 未登录打 /api/rooms ⇒ 401", st == 401, "实际 %s" % st)
    ck("① 信封是统一形状（success=False）", body.get("success") is False, body)
    ck("① 错误码是 unauthenticated（**不是** forbidden）",
       (body.get("error") or {}).get("code") == "unauthenticated", body)
    ck("① 401 里给出了下一步（去哪登录）",
       "login" in str((body.get("error") or {}).get("detail", "")), body)
    ck("① 被拦的请求**没有进到路由**（reached 不该出现）",
       "reached" not in body, body)

    # ② 阳性：公开路径必须**放过去** —— 这一支才是分辨力所在
    st, body = _call_gate(gated, "POST", "/api/auth/login")
    ck("★ ② 未登录打 /api/auth/login ⇒ **放行**（不是 401）", st != 401,
       "实际 %s" % st)
    ck("★ ② 而且真的走到了路由（reached=True）", body.get("reached") is True, body)

    # ③ 最重要的阴性：数据面不是 /api，只罩 /api 会漏
    st, _ = _call_gate(gated, "GET", "/data/buildings/c006/rooms.json")
    ck("★ ③ 未登录打 /data/buildings/.../rooms.json ⇒ 401"
       "（**只罩 /api 会漏这条**）", st == 401, "实际 %s" % st)

    # ④ 预检放行
    st, _ = _call_gate(gated, "OPTIONS", "/api/rooms")
    ck("④ OPTIONS 预检放行（拦了浏览器会把真请求也发不出去）", st != 401,
       "实际 %s" % st)

    # ⑤ 静态外壳不受闸 —— 登录页自己得能加载
    st, _ = _call_gate(gated, "GET", "/index.html")
    ck("★ ⑤ /index.html 不受闸（拦了的话登录页自己也打不开）", st != 401,
       "实际 %s" % st)
    st, _ = _call_gate(gated, "GET", "/js/app.js")
    ck("★ ⑤ /js/app.js 不受闸", st != 401, "实际 %s" % st)


def _breakglass_selftest(ck) -> None:
    """break-glass 是"本机用法一点不变"的**唯一**依据，所以两个方向都要验：
    开着时本机放行、局域网不放行；关掉时**本机也不放行**。
    ★ 只验"开着时本机放行"是不够的 —— 一个 `return True` 的常量也能全绿，
      而那正好就是"永远放行的闸"（铁律 153 的反面同样成立）。"""
    cfg = get_settings()
    saved = cfg.loopback_breakglass
    loop = Request(_mk_scope("GET", "/api/rooms", "127.0.0.1"), None)
    lan = Request(_mk_scope("GET", "/api/rooms", "192.168.1.50"), None)
    try:
        object.__setattr__(cfg, "loopback_breakglass", True)
        ck("★ 开着：本机 ⇒ 放行（**你今天的用法不变**）", _breakglass(loop, cfg))
        ck("★ 开着：局域网 ⇒ **不放行**（本机通道只认回环，不是「所有人」）",
           not _breakglass(lan, cfg))
        p = principal_of(loop, cfg)
        ck("★ 开着：本机身份 = builder@*（全校区全能力）",
           p is not None and p.via == "loopback" and p.allows("manage", "c006"), str(p))
        object.__setattr__(cfg, "loopback_breakglass", False)
        ck("★ 关掉：本机 ⇒ **也不放行**（开关是真的能关，不是装饰）",
           not _breakglass(loop, cfg))
        ck("关掉：局域网 ⇒ 不放行", not _breakglass(lan, cfg))
    finally:
        object.__setattr__(cfg, "loopback_breakglass", saved)


def _account_plane_selftest(ck) -> None:
    """★ 2026-10-01 新开的那个口子（账户域的写路由可以改用「认证闸/权限闸」）。

    这三把尺子（`is_login_gated` / `cap_plane_gate` / `_write_ok`）**都是新的**，
    而新尺子最常见的坏法是"恒真" —— 恒真的表现是**全部判据都过**，所以只跑阳性
    等于没跑（铁律 153：一个「永远拒」的闸能通过全部阴性对照；反过来，一个
    「永远放」的闸能通过全部阳性对照）。

    三件事各自要有反证：
      a) `cap_plane_gate` 对一条**什么依赖都没挂**的账户域写路由 ⇒ **False**
         （少了这条，账户域就成了"谁都能打的写接口"的免罚区）
      b) `cap_plane_gate` 对域外的路径 ⇒ **False**（白名单真的在限定作用域）
      c) `_write_ok` 对 `PUBLIC` 但**不在** `PUBLIC_WRITES` 里的写路由 ⇒ **False**
         （少了这条，往 `PUBLIC_PATHS` 加一条只为放行某个 GET，会**顺手**
           把同路径的 POST 也放出去）
    """
    from fastapi import APIRouter, Depends, FastAPI

    # ★ 白名单的**唯一定义**在 `deps`（该由它守），这里只是取来当尺子量一次：
    #   下面那条「真的落在白名单前缀里」就是在验"这份名单不是空的" ——
    #   名单一旦被改空，`cap_plane_gate` 的 a) 判据会退化成**恒真**
    #   （任何路径都不在空名单里，也就永远没有"域内没挂闸"这回事）。
    from .deps import CAP_PLANE_PREFIXES, assert_writes_gated

    def _route(path: str, prefix: str, dep=None):
        """造一条写路由；`dep` 给 None 就是**什么闸都没挂**。"""
        app = FastAPI()
        sub = APIRouter()
        if dep is None:
            def _open() -> dict:
                return {}
            sub.post("/w")(_open)
        else:
            def _closed(_g=Depends(dep)) -> dict:            # noqa: B008
                return {}
            sub.post("/w")(_closed)
        app.include_router(sub, prefix=prefix)
        return next(r for r in iter_routes(app.routes) if r.path.endswith("/w"))

    gated_dep = require_cap("view")

    # ★ 0) 两份域名单必须**逐条相同**：`deps` 的白名单（谁在口子范围内）与
    #   本文件 `cap_plane_gate.DOMAINS`（我知道哪些域、各用什么尺子）。
    #   两边各算一次，不是抄一遍 —— 白名单里加了新域而这里没给判据，
    #   表现是启动被拒（响的）；反过来这里多一个域则白名单外永远用不到。
    ck("★ 0) CAP_PLANE_PREFIXES 与 cap_plane_gate.DOMAINS 逐条相同",
       tuple(sorted(CAP_PLANE_PREFIXES)) == tuple(sorted(p for p, _ in cap_plane_gate.DOMAINS)),
       "deps=%s authz=%s" % (CAP_PLANE_PREFIXES,
                             tuple(p for p, _ in cap_plane_gate.DOMAINS)))

    # a) ★ 这**一条**是最要紧的：账户域里"谁都能打"的写路由必须被拦下
    r_open = _route("/w", "/api/auth")
    ck("★ a) 账户域 + **什么闸都没挂** ⇒ cap_plane_gate 为假"
       "（少了这条，账户域就成了免罚区）",
       not cap_plane_gate(r_open.node, r_open.path), r_open.path)
    ck("a) 而且它真的落在白名单前缀里（否则这条判据是空的）",
       r_open.path.startswith(CAP_PLANE_PREFIXES), r_open.path)

    # a2) 阳性对照：挂了 require_cap 的 ⇒ 真
    r_cap = _route("/w", "/api/auth", gated_dep)
    ck("★ a2) 账户域 + require_cap ⇒ 真（**本该放行**的那一支）",
       cap_plane_gate(r_cap.node, r_cap.path))

    # a3) 第三种闸：current_principal
    r_auth = _route("/w", "/api/auth", current_principal)
    ck("★ a3) 账户域 + current_principal（仅登录）⇒ 真",
       cap_plane_gate(r_auth.node, r_auth.path))
    ck("★ a3) 而它**不**算能力闸（两种闸要分得开）",
       not is_cap_gated(r_auth.node) and is_login_gated(r_auth.node))

    # a4) ★ 门户域：判据**分派**过去、且更严 —— 只认能力闸。
    #     这一组是"分派 vs 把两把尺子 OR 起来"的分界线：
    #     若改成 `any(_auth_plane_judge, _portal_plane_judge)`，
    #     下面那条"仅登录 ⇒ 假"会**当场红**。
    r_p_open = _route("/w", "/api/portal")
    ck("★ a4) 门户域 + 什么闸都没挂 ⇒ 假",
       not cap_plane_gate(r_p_open.node, r_p_open.path), r_p_open.path)
    r_p_cap = _route("/w", "/api/portal", gated_dep)
    ck("★ a4) 门户域 + require_cap ⇒ 真（**本该放行**的那一支）",
       cap_plane_gate(r_p_cap.node, r_p_cap.path))
    r_p_auth = _route("/w", "/api/portal", current_principal)
    ck("★ a4) 门户域 + current_principal（仅登录）⇒ **假**"
       "（与账户域刻意不同；OR 起来的写法会在这里红）",
       not cap_plane_gate(r_p_auth.node, r_p_auth.path))
    # a5) 认不出的域 ⇒ 假（fail-closed）
    r_x = _route("/w", "/api/authx")
    ck("★ a5) 前缀**像**账户域但不是（/api/authx）⇒ 假（fail-closed）",
       not cap_plane_gate(r_x.node, r_x.path))

    # b) ★ 白名单真的在限定作用域 —— **拿真的断言跑真的 app**，不是拼一份判据副本。
    #    （第一版我把这条写成 `not cap_plane_gate(...)`，当场红了：前缀检查
    #      本来就不在这个函数里，是 `deps` 那道 `and`。测单件只会测到我自己的
    #      复述 —— 而"复述通过的判据"证明不了被复述的那个东西（铁律 173）。）
    def _would_start(sub_prefix: str, dep) -> bool:
        """把这个 app 喂给**真的** `assert_writes_gated`，返回"它放不放行"。"""
        app = FastAPI()
        sub = APIRouter()
        if dep is None:
            def _o() -> dict:
                return {}
            sub.post("/w")(_o)
        else:
            def _c(_g=Depends(dep)) -> dict:                 # noqa: B008
                return {}
            sub.post("/w")(_c)
        app.include_router(sub, prefix=sub_prefix)
        try:
            assert_writes_gated(app, extra_gate=cap_plane_gate)
            return True
        except RuntimeError:
            return False

    ck("★ b) 域外（/api/console）+ 只有 require_cap ⇒ **拒绝启动**",
       not _would_start("/api/console", gated_dep))
    ck("★ b) 账户域 + 只有 require_cap ⇒ **放行**（阳性对照，否则 b) 是恒拒）",
       _would_start("/api/auth", gated_dep))
    ck("★ b) 账户域 + 什么闸都没挂 ⇒ **拒绝启动**"
       "（这条走的是真断言，不是上面那个单件判据）",
       not _would_start("/api/auth", None))
    ck("★ b) 门户域 + 只有 require_cap ⇒ **放行**",
       _would_start("/api/portal", gated_dep))
    ck("★ b) 门户域 + 只有 current_principal（仅登录）⇒ **拒绝启动**"
       "（这是分派与 OR 的分界线：OR 的写法会在这里绿）",
       not _would_start("/api/portal", current_principal))

    # c) 公开写路由必须**再点一次名**
    ck("★ c) /api/auth/login 在 PUBLIC_WRITES 里（它是公开的，但不许静默）",
       "/api/auth/login" in PUBLIC_WRITES)
    ck("★ c) 一条**假的**公开写路由 ⇒ _write_ok 为假"
       "（往 PUBLIC_PATHS 加一条 GET，不会顺手把同路径的 POST 放出去）",
       not _write_ok({"state": PUBLIC, "path": "/api/rooms", "methods": ["POST"]}))
    ck("c) 而真在名单里的公开写路由 ⇒ 真（阳性对照）",
       _write_ok({"state": PUBLIC, "path": "/api/auth/login",
                  "methods": ["POST"]}))
    ck("★ c) 未纳管的写路由 ⇒ 假（这一条本来就在，列出来防「改宽」)",
       not _write_ok({"state": UNMANAGED, "path": "/api/whatever",
                      "methods": ["POST"]}))
    ck("★ c) 已纳管的读路由也返回真 —— 这个判据只管写路由，调用方负责筛",
       _write_ok({"state": GATED, "path": "/api/rooms", "methods": ["GET"]}))


def _batch2_selftest(ck) -> None:
    """★ 批次 2（2026-10-01）：集合路由的**逐行过滤**与**数据面挂载**。

    这一节要证明的东西只有一句：**一个不量范围的闸，能通过全部权限判据**。
    证据就是 `Principal.allows(cap, None)` 恒真 —— 于是给 `/api/rooms` 挂一个
    不带 target 的 `require_cap("view")`，只覆盖 `c006` 的账号来问，会原样拿到
    **全校区 10562 个房间**，而权限清册上那一条印的是「已纳管」。

    所以这里的每一把尺子都要**两支**：
      · 本该拦下的那支（阴性）—— 单独跑它是全绿的，没有分辨力；
      · ★ **本该放行的那支**（阳性）—— 少了它，一个「永远拒」的坏闸同样全绿
        （铁律 153）。下面凡是有 ★ 的行就是这一支。
    """
    import anyio
    from starlette.requests import Request

    from .settings import get_settings

    cfg = get_settings()

    def _p(scopes, roles=("viewer",)):
        return Principal(7, "u", roles, frozenset(c for r in roles
                                                  for c in caps_of(r)),
                         tuple(scopes), "session", False)

    def _req(p, path="/api/x", host="10.0.0.9"):
        sc = _mk_scope("GET", path, host)
        sc["lihua_principal"] = p
        return Request(sc)

    v6 = _p(("c006",))            # 只覆盖 c006 的普通管理员
    vstar = _p(("*",), ("builder",))   # 全校区

    print("\n【9】批次 2：集合路由不能「挂个闸就完事」")
    ck("★ 前提（整个批次的出发点）：`allows(cap, None)` 对 v6 **恒真** —— "
       "不传 target 的能力关等于零效果",
       v6.allows("view", None))
    ck("而同一个 v6，带 target 时是拦得住的（这是上面那条的对照）",
       not v6.allows("view", "c001"))

    print("\n【9a】sees / visible：按范围**过滤行**，不是挂闸")
    ck("v6 看得见 c006", sees(v6, "c006"))
    ck("v6 看不见 c001", not sees(v6, "c001"))
    ck("★ 前缀不带分隔符不算覆盖（c006 ↛ c006f1，本仓真有 f1 楼层号）",
       not sees(v6, "c006f1"))
    ck("v6 看得见自己那栋的房间节点", sees(v6, "c006|3|301"))
    rows = [{"building": "c001", "id": "a"}, {"building": "c006", "id": "b"},
            {"building": "c006", "id": "c"}]
    got6 = visible(v6, rows, lambda r: r["building"])
    ck("v6 只拿到 c006 那两行（不是原样三行）",
       [r["id"] for r in got6] == ["b", "c"], got6)
    ck("★ **本该放行的那支**：全校区账号拿到**全部**三行"
       "（少了这条，`visible` 恒回空集也照样过上面那条）",
       [r["id"] for r in visible(vstar, rows, lambda r: r["building"])]
       == ["a", "b", "c"])
    empty = Principal(8, "u", (), frozenset(), (), "session", False)
    ck("★ 有账号、**无授权** ⇒ 一行都拿不到（空授权不是万能钥匙）",
       visible(empty, rows, lambda r: r["building"]) == [])
    ck("★ key 取不到（回空串）的行**丢掉**，不是保留",
       visible(vstar, [{"building": ""}], lambda r: r["building"]) == [])

    print("\n【9b】require_scope：核**查询参数**里的节点（两支都要）")
    ck("v6 + c006 ⇒ 放行（不抛）", not _raises(lambda: require_scope(v6, "c006")))
    ck("★ v6 + c001 ⇒ 403", _raises(lambda: require_scope(v6, "c001")))
    ck("★ v6 + 空串 ⇒ 403（取不到楼号时不许默认放行）",
       _raises(lambda: require_scope(v6, "")))
    ck("★ **本该放行的那支**：全校区 + c001 ⇒ 放行",
       not _raises(lambda: require_scope(vstar, "c001")))

    print("\n【9c】require_campus_wide：**整条拒绝**，不切片")
    wide = require_campus_wide()
    ck("★ v6 问全库结论 ⇒ 403（那个结论是「整个库跑一趟」得出的，"
       "按范围切成几份，屏幕上的数字就不再是那句话）",
       _raises(lambda: wide(_req(v6), cfg)))
    ck("★ **本该放行的那支**：全校区 ⇒ 过，并把身份回出来",
       wide(_req(vstar), cfg).username == "u")
    ck("★ 有 view 但范围只有 c006 的账号，在 `require_cap('view')` 下是**过**的"
       "—— 这正是为什么要单独造 `require_campus_wide`",
       require_cap("view")(_req(v6), cfg).username == "u")

    print("\n【9d】ScopedStatic：`/data/buildings` 那个**整目录挂载**的细闸")
    seen = {"hit": 0}

    class _Inner:
        async def __call__(self, scope, receive, send):
            seen["hit"] += 1
            await send({"type": "http.response.start", "status": 200,
                        "headers": []})
            await send({"type": "http.response.body", "body": b'{"ok":1}'})

    def _call_ss(p, path, root_path=""):
        """跑一次 `ScopedStatic`；返回 (状态码, 内层有没有被调到)。"""
        seen["hit"] = 0
        ss = ScopedStatic(_Inner(), root_path="/data/buildings")
        sc = _mk_scope("GET", path, "10.0.0.9")
        sc["root_path"] = root_path
        if p is not None:
            sc["lihua_principal"] = p
        got = {}

        async def recv():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(m):
            if m["type"] == "http.response.start":
                got["status"] = m["status"]

        anyio.run(lambda: ss(sc, recv, send))
        return got.get("status", 0), seen["hit"]

    # ★ 下面的 path/root_path 组合**是实测来的**，不是推的（`_scratch/_b2_scopeprobe.py`，
    #   2026-10-01，用真 `app.mount()` + TestClient 把子 app 收到的 scope 印出来）：
    #     `GET /data/buildings/c006/rooms.json`
    #         ⇒ scope["path"] = **'/data/buildings/c006/rooms.json'**（**没剥**）
    #           scope["root_path"] = '/data/buildings'
    #     `GET /data/buildings/` 与 `GET /data/buildings`（无斜杠）
    #         ⇒ 两者 path 都是 '/data/buildings/'、root_path 同上 ⇒ 节点 `*`
    #   ⇒ **节点完全靠 `root_path` 那一次剥**；剥不到就会拿到首段 `data`。
    #   这一条是这套东西里唯一的"框架行为"假设，所以它必须有实测出处。
    ck("★ 实测形状（path 未剥 + root_path=`/data/buildings`）⇒ c006 账号**放行**，"
       "且内层真的被调到",
       _call_ss(v6, "/data/buildings/c006/rooms.json", "/data/buildings") == (200, 1))
    ck("★ 实测形状 + c001 ⇒ c006 账号 **403**，且内层**一次都没被调**"
       "（「没调」与「调了但被内层拒」是两件事）",
       _call_ss(v6, "/data/buildings/c001/rooms.json", "/data/buildings") == (403, 0))
    ck("★ **本该放行的那支**：全校区 + c001 ⇒ 放行"
       "（少了它，「永远 403」的坏闸也全绿 —— 上面那条 c001 就是这么被骗过去的）",
       _call_ss(vstar, "/data/buildings/c001/rooms.json", "/data/buildings") == (200, 1))
    ck("★ 首段取不到（`/data/buildings/`）⇒ 按**根节点** `*` 判 ⇒ c006 账号 403",
       _call_ss(v6, "/data/buildings/", "/data/buildings") == (403, 0))
    ck("★ **本该放行的那支**：全校区 + 同一条 ⇒ 放行",
       _call_ss(vstar, "/data/buildings/", "/data/buildings") == (200, 1))
    ck("★ 这条数据面上**没有身份** ⇒ 401（不是 403、更不是放行）——"
       "它意味着路径不在受保护前缀里，是配置错误",
       _call_ss(None, "/data/buildings/c006/rooms.json",
                "/data/buildings") == (401, 0))
    # ★ 残余的一条：`root_path` 空 + path 未剥 ⇒ 首段取到 `data`，
    #   而空间树里**没有** `data` 这个节点 ⇒ 除全校区账号外一律 403。
    #   实测这个组合**走不到**（真挂载一定带 root_path）。留着它的理由：
    #   这是一条**安全但静默的收窄**（屏幕上是"你没有权限"，读起来像权限问题），
    #   哪天有人换掉挂载方式把它变成可达的，这两条判词会当场翻成红，
    #   而不是安静地只服务全校区账号。
    ck("★ 残余：root_path 空 + 未剥 ⇒ 节点退化成 `data` ⇒ **v6 那种账号 403**"
       "（安全，但静默收窄；实测当前不可达）",
       _call_ss(v6, "/data/buildings/c006/rooms.json") == (403, 0))
    ck("★ 而同一个残余形状下**全校区账号仍放行** —— 所以它是「只服务全校区」，"
       "不是「全部拒绝」（这两句的下一步动作不同）",
       _call_ss(vstar, "/data/buildings/c006/rooms.json") == (200, 1))

    # ── 【9e】拒绝留痕：**这几支不碰库** ──────────────────────────────
    #   为什么只量纯函数：本套自检**不许**依赖 PG（`db_required` 默认 False 是
    #   有意保留的性质）。所以这里量「配额怎么算」「留痕长什么样」，
    #   而「真的写进去了」由活 HTTP 那一趟量（`_scratch/_b2_e2e.py` + 查台账）。
    #   ⇒ 两处各管一半，**合起来**才是完整的判据（铁律 60：别把"没做"读成"0 个通过"）。
    print("\n【9e】越权留痕：配额算法与留痕文本（纯函数，不连库）")

    def _sc(ip, path="/api/buildings/c001", p=None, method="GET"):
        s = _mk_scope(method, path, ip)
        if p is not None:
            s["lihua_principal"] = p
        return s

    _DENY_BUCKETS.clear()
    got = [_audit_token(("10.0.0.1", 403)) for _ in range(25)]
    passed = sum(1 for g in got if g is not None)
    ck("★ 新桶容量 = %d：连打 25 次，前 %d 次进、其余被压"
       % (_DENY_CAPACITY, passed),
       passed == int(_DENY_CAPACITY))
    # 上面那支只量了「次数对不对」；**被压掉的那几次不消失**要单独量一次
    # （把桶打空 → 压 3 次 → 回填一个额 → 看下一条是否报数）。
    # ★ 用假钟驱动回填：真睡要 3 秒，而睡够多久这件事本身与被测逻辑无关 ——
    #   注入的那个 `now` **只改时钟、不改算术**（生产的 `now` 走默认值）。
    _DENY_BUCKETS.clear()
    t = 1000.0
    for _ in range(int(_DENY_CAPACITY)):
        _audit_token(("10.0.0.2", 403), now=t)
    for _ in range(3):
        _audit_token(("10.0.0.2", 403), now=t)     # 这 3 次被压
    t += 1.0 / _DENY_REFILL_PER_SEC * 1.01         # 正好回填出 1 个额
    nxt = _audit_token(("10.0.0.2", 403), now=t)
    ck("★ 压掉 3 次后，下一条成功写入带回 dropped=3（不是 0、也不是静默）",
       nxt == 3, "实际 %r" % (nxt,))
    t += 1.0 / _DENY_REFILL_PER_SEC * 1.01
    ck("★ 报过一次就清零：再下一条是 0（否则这一个数会被印在之后**每一条**上）",
       _audit_token(("10.0.0.2", 403), now=t) == 0)

    # ★ 桶按 IP 分开 —— 这是本段最要紧的一支：**共用桶会让台账安静地只记下
    #   喊得最响的那一个**，而另一个 IP 的「有人在试」一次都不会出现。
    _DENY_BUCKETS.clear()
    for _ in range(int(_DENY_CAPACITY) + 5):
        _audit_token(("10.0.0.9", 403))            # 把 A 打爆
    ck("★ **本该放行的那支**：A 打爆之后，B 的第一次仍然进得来"
       "（共用桶的话这里会是 None，而屏幕上只表现为「B 没在试」）",
       _audit_token(("10.0.0.8", 403)) == 0)

    _DENY_BUCKETS.clear()
    a403 = _sc("10.0.0.7", "/api/buildings/c001", v6)
    ck("★ 有身份 ⇒ 留痕里带上**是谁**（username/roles/scopes 都在）",
       '"username": "u"' in _denied_detail(a403, 403, ERR_FORBIDDEN),
       _denied_detail(a403, 403, ERR_FORBIDDEN)[:120])
    ck("★ 留痕里带上**打的是哪条路径、要什么码** —— 少了它，台账只说明"
       "「有人被拒过」，说不清「在试什么」",
       "/api/buildings/c001" in _denied_detail(a403, 403, ERR_FORBIDDEN)
       and ERR_FORBIDDEN in _denied_detail(a403, 403, ERR_FORBIDDEN))
    anon = _sc("10.0.0.7", "/api/rooms", None)
    ck("★ 没身份 ⇒ 留痕写 anon（**不是崩、也不是留个空**）",
       '"via": "anon"' in _denied_detail(anon, 401, ERR_UNAUTHENTICATED),
       _denied_detail(anon, 401, ERR_UNAUTHENTICATED)[:120])
    ck("★ dropped=0 时**不出现**那句限流说明（避免每一行都挂一句废话）",
       "限流" not in _denied_detail(a403, 403, ERR_FORBIDDEN))
    _DENY_BUCKETS.clear()


if __name__ == "__main__":
    import sys as _sys
    # ★ 判词全是中文 + `✓✗⇒`，Windows 控制台默认 GBK ⇒ `UnicodeEncodeError`。
    #   本仓栽过（铁律 168：同族 11 个脚本里 10 个调了、就一个没调，于是它的
    #   `UnicodeEncodeError` 在汇总表里印成了"口径认不出"，与"真有断言没过"长得一样）。
    #   这里 `errors="replace"`：编码失败也不许把一个判据的结论吞掉。
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(_sys.stderr, "reconfigure"):
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    _sys.exit(_selftest())
