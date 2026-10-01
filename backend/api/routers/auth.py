# -*- coding: utf-8 -*-
"""登录 / 登出 / 改密 / 账号管理 —— 权限骨架的 HTTP 面。

## 谁在闸后面

本文件里**每一条**路由都自己声明了它要什么（`require_cap`），除了三条有意公开的：
`login` / `session` / `logout`。理由写在那三条各自的 docstring 里。
其余路由**不靠中间件兜底** —— 中间件只是"忘了声明"的保险，不是代替声明的东西
（本仓铁律：执行侧必须自己过闸；闸在别处而执行侧不调它 = fail-open）。

## 会话怎么走

    POST /api/auth/login   ⇒ 服务端建一行 sessions，Set-Cookie 里放随机串
    Cookie 属性            ⇒ HttpOnly（JS 读不到）+ SameSite=Lax（挡跨站携带）+ Path=/
    服务端                  ⇒ 库里只存 sha256(随机串)，**原文不落库**
    POST /api/auth/logout  ⇒ `revoked_at` 置位（**不删行**，好审计）+ 清 cookie

★ 为什么是服务端会话而不是 JWT：内网单进程（PM2 `instances:1`）。JWT 的好处是
  无状态，而它的代价是**吊销困难** —— "把某人踢下线"要等到过期才生效，
  而"停用账号要立刻生效"正是这类系统最基本的要求之一。

## 限流：为什么现在就做

CLAUDE.md 明令「公开 API 加频率限制」，而**登录是唯一一条不需要身份就能打的
写接口** —— 不限流的话，一个字典就能把全校账号试一遍。
★ 诚实地说清它的边界：计数在**进程内存**里 ⇒ 重启即清零、多进程不共享。
  本进程是 `instances:1` fork，所以够用；哪天要横向扩，这一块必须挪到 Redis/PG
  （写在这里，免得将来有人以为它是分布式的）。
"""
import threading
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ..authz import ROLE_CAPS, PrincipalDep, current_principal, require_cap
from ..deps import SettingsDep
from ..responses import ERR_BAD_REQUEST, ERR_RATE_LIMITED, ApiError, ok
from ..settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


# ── 输入模型 ────────────────────────────────────────────────────────

# 口令下限。★ 12 而不是 8：内网、无短信二次验证、账号名全校可猜（拼音），
#   8 位在字典面前不值一提。上限 200 防有人拿超长串当 DoS 打 scrypt。
PW_MIN = 12
PW_MAX = 200


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=PW_MAX)


class ChangePwIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=PW_MAX)
    new_password: str = Field(min_length=PW_MIN, max_length=PW_MAX)


class CreateUserIn(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=200)
    role_code: str
    scope_node: str = Field(default="*", max_length=200)
    password: str | None = Field(default=None, max_length=PW_MAX)


class GrantIn(BaseModel):
    role_code: str
    scope_node: str = Field(default="*", max_length=200)


class ActiveIn(BaseModel):
    active: bool


class ResetPwIn(BaseModel):
    password: str | None = Field(default=None, max_length=PW_MAX)


# ── 限流 ────────────────────────────────────────────────────────────

# (窗口秒数, 窗口内允许的失败次数)。★ 两个维度各一条：
#   按 IP    —— 挡"一台机器试很多账号"
#   按用户名 —— 挡"很多机器试同一个账号"
# 只做一条都会漏一半：前者漏掉分布式撞一个账号，后者漏掉单机遍历全校。
LIMITS = {"ip": (300, 10), "user": (900, 5)}
_HITS: dict[tuple, list] = {}
_LOCK = threading.Lock()


def _too_many(kind: str, key: str) -> int:
    """返回还需等待的秒数；0 = 放行。★ 过期条目**顺手清掉**，
    否则这个字典会随着被试过的用户名无限长（一个能被攻击者撑大的内存表）。"""
    window, cap = LIMITS[kind]
    now = time.time()
    with _LOCK:
        for k in [k for k, v in _HITS.items() if not v or now - v[-1] > window]:
            _HITS.pop(k, None)
        hits = [t for t in _HITS.get((kind, key), []) if now - t < window]
        if len(hits) >= cap:
            return int(window - (now - hits[0])) + 1
        _HITS[(kind, key)] = hits
    return 0


def _record_failure(kind: str, key: str) -> None:
    with _LOCK:
        _HITS.setdefault((kind, key), []).append(time.time())


def _clear(kind: str, key: str) -> None:
    with _LOCK:
        _HITS.pop((kind, key), None)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


# ── 公开的三条 ──────────────────────────────────────────────────────

@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, cfg: SettingsDep) -> dict:
    """登录。★ 这是唯一一条**不需要身份**就能打的写接口，所以它自己带限流。

    ★ 失败时**不区分**"没这个账号"与"口令不对"，对外同一句话：
      区分开就等于送人一个"这个账号存在"的探测器。
      （耗时也不区分 —— 见 `accounts.authenticate` 里那条假哈希。）
    """
    ip = _client_ip(request)
    wait = _too_many("ip", ip) or _too_many("user", body.username.lower())
    if wait:
        raise ApiError(429, ERR_RATE_LIMITED,
                       "登录尝试过于频繁，请 %d 秒后再试。" % wait, {"retry_after": wait})

    from backend.db import accounts as A
    with A.connect() as conn:
        user = A.authenticate(conn, body.username, body.password, client_ip=ip)
        if user is None:
            _record_failure("ip", ip)
            _record_failure("user", body.username.lower())
            raise ApiError(401, "unauthenticated",
                           "用户名或口令不对。",
                           {"hint": "连续多次失败会暂时锁定；忘了口令找搭建方重置。"})
        _clear("ip", ip)
        _clear("user", body.username.lower())
        token = A.create_session(conn, user["user_id"], client_ip=ip,
                                 user_agent=request.headers.get("user-agent"))
        grants = A.all_grants(conn, user["user_id"])

    _set_session_cookie(response, cfg, token, A.SESSION_HOURS * 3600)
    return ok({"username": user["username"], "display_name": user["display_name"],
               "must_change": user["must_change"],
               "grants": [{"role_code": r, "scope_node": s} for r, s in grants]})


@router.get("/session")
def session(request: Request, cfg: SettingsDep) -> dict:
    """「我现在是谁」—— 前端每次开页面都要问。

    ★ **必须公开**：未登录时它要能正常回一句"未登录"，而不是 401。
      回 401 的话前端只能把 401 当"未登录"处理，而 401 同时还是"会话过期"
      和"账号被停用" —— 三种情况一个码，前端只能统一弹"请登录"，
      而那会把人引去做一件没用的事（他本来就是登录着的）。
    ★ 这里**不 raise**：identity 取不到就回 `logged_in: false`，这是本路由的正常输出。

    ★ **不回 `break_glass`**（2026-10-01 改）。原来两个分支都回
      `cfg.loopback_breakglass` —— 那是"开关开着吗"，而这是一条**公开**路由，
      ⇒ 局域网上任何一个没登录的人都能问出"这台机器的回环旁路开着没有"。
      这句话本身就是情报：它告诉对方"从这台机器本机打进去就能当搭建方"，
      于是下一步就是去找一个 SSRF 或一条本机代理。
      ⇒ 改成只回**"你这次是不是走旁路进来的"**（`brief()` 里已有 `via`），
      匿名分支干脆不提这个字段。开关状态留在启动日志里印（`authz.describe()`），
      那儿只有能看日志的人看得到 —— 而"后门要让人看得见"的要求由它满足，
      不需要再对外广播一遍。
    """
    from ..authz import AuthBackendUnavailable, principal_of
    try:
        p = principal_of(request, cfg)
    except AuthBackendUnavailable as exc:
        # ★ 库挂了要**说出来**。混成 `logged_in:false` 的话，界面会说"请登录"，
        #   而人刚登录过 —— 他会一遍遍重登，而真问题是数据库。
        raise ApiError(503, "auth_backend_unavailable",
                       "身份服务暂时不可用（连不上账号库）。这不是口令问题。",
                       {"cause": str(exc)[:300]}) from exc
    if p is None:
        return ok({"logged_in": False})
    from backend.db import accounts as A
    with A.connect() as conn:
        grants = [{"role_code": r, "scope_node": s}
                  for r, s in A.all_grants(conn, p.user_id)] if p.user_id else \
                 [{"role_code": "builder", "scope_node": "*"}]
    # ★ `via`（在 brief() 里）就是前端要的那个语义：`"loopback"` 表示这次是旁路进来的。
    return ok(dict(p.brief(), logged_in=True, grants=grants,
                   must_change=p.must_change))


@router.post("/logout")
def logout(request: Request, response: Response, cfg: SettingsDep) -> dict:
    """登出。★ **公开**且**幂等**：没登录时点它也该是成功，不是 401。

    ★ 为什么撤销会话用 `revoked_at` 置位而不是 DELETE：留痕。
      "他什么时候登出的"和"这个 cookie 是被撤销的还是从来不存在"是两件事，
      删了行就分不出来了 —— 而分不出来的方向是**错判成"伪造的 cookie"**。
    """
    token = request.cookies.get(cfg.session_cookie)
    if token:
        from backend.db import accounts as A
        with A.connect() as conn:
            # ★ **先读身份、再吊销**。吊销之后这个会话就查不到了，而"谁登出的"
            #   正是这张表存在的理由 —— 2026-10-01 实测：每一行 `logout` 的
            #   `username` 都是 NULL，因为这一句**压根没传**（`A.log` 的
            #   `username` 是可选参数，默认 None ⇒ 漏传不报错、不抛异常，
            #   屏幕上只看得到一列空值，读起来像"这是系统自己登的"）。
            sess = A.load_session(conn, token)
            A.revoke_session(conn, token)
            A.log(conn, "logout", client_ip=_client_ip(request),
                  username=(sess or {}).get("username"),
                  user_id=(sess or {}).get("user_id"))
    response.delete_cookie(cfg.session_cookie, path="/")
    return ok({"logged_out": True})


# ── 需要身份的 ──────────────────────────────────────────────────────

@router.post("/password")
def change_password(body: ChangePwIn, request: Request, response: Response,
                    cfg: SettingsDep, p: PrincipalDep) -> dict:
    """自己改密。**必须先验旧口令** —— 否则一个被偷走的会话就能把口令改掉，
    把小偷变成主人，而真正的主人再也进不来。

    ★ 回环身份（`user_id is None`）没有账号，改不了密 —— 明说，别静默成功。
    """
    if p.user_id is None:
        raise ApiError(400, ERR_BAD_REQUEST,
                       "当前是**本机直通**身份（break-glass），没有账号可改。"
                       "请先用账号登录，或让搭建方给你开一个号。")
    if body.new_password == body.old_password:
        raise ApiError(400, ERR_BAD_REQUEST, "新口令与旧口令相同，没有意义。")
    _check_pw_strength(body.new_password, p.username)

    from backend.db import accounts as A
    with A.connect() as conn:
        row = A.find_user(conn, p.username)
        if row is None or not A.verify_password(body.old_password, row[3]):
            A.log(conn, "password", username=p.username, user_id=p.user_id,
                  detail="旧口令不对", client_ip=_client_ip(request), ok=False)
            raise ApiError(401, "unauthenticated", "旧口令不对。")
        A.change_own_password(conn, p.user_id, body.new_password)
        A.log(conn, "password", username=p.username, user_id=p.user_id,
              detail="本人修改", client_ip=_client_ip(request))
        # ★ 改密**踢掉所有会话之后**，当前这一个也失效了。给他换一个新的，
        #   免得他改完密立刻被踢到登录页 —— 那看起来像"改密把账号搞坏了"。
        token = A.create_session(conn, p.user_id, client_ip=_client_ip(request))
    _set_session_cookie(response, cfg, token, A.SESSION_HOURS * 3600)
    return ok({"changed": True, "did_change_required": True})


@router.get("/roles")
def list_roles(_p: PrincipalDep) -> dict:
    """角色字典 + 每个角色有哪些能力。**任何人登录后都能读** ——
    界面上"我这号能干什么"要它。不含任何账号信息。

    ★ 名字**从库里读**，不在这里再抄一份。抄一份的话，改名的那个动作
      只会改到 `ROLE_SEED`，而这个接口会继续回旧名字 —— 界面上"角色"这一栏
      与授权页那一栏对不上，且两边都"有出处"（本仓铁律 018）。
    """
    from backend.db import accounts as A
    with A.connect() as conn:
        return ok(A.list_roles(conn))


# ── 账号管理（只有「搭建方」= 有 manage 的人）─────────────────────────

# ★ 这几条统一挂 `require_cap("manage")`。**不做范围检查**（scope_param=None）：
#   账号管理是"全校级"的动作，"哪个学院能开号"这种需求如果真出现，
#   再加范围维度 —— 现在加就是给自己造一个没人用的开关。
#   （YAGNI；但口径写在这里，免得后来人以为是漏了。）
admin_only = Annotated[Any, Depends(require_cap("manage"))]


@router.get("/users")
def users(_p: PrincipalDep, _a: admin_only) -> dict:
    from backend.db import accounts as A
    with A.connect() as conn:
        return ok({"users": A.list_users(conn), "roles": A.list_roles(conn)})


@router.post("/users")
def create_user(body: CreateUserIn, request: Request,
                p: PrincipalDep, _a: admin_only) -> dict:
    """开号。★ 口令**只在这一条响应里出现一次** —— 库里只有哈希，找不回来。

    ★ 目标范围：本机 break-glass 身份的 `user_id` 是 None，而 `granted_by` 是外键。
      传 None 是**对的**（"不是某个账号建的"），别硬凑一个 id。
    """
    if body.role_code not in ROLE_CAPS:
        raise ApiError(400, ERR_BAD_REQUEST,
                       "不认识的角色码 %r。" % body.role_code,
                       {"known": sorted(ROLE_CAPS)})
    if body.password:
        _check_pw_strength(body.password, body.username)

    from backend.db import accounts as A
    try:
        with A.connect() as conn:
            uid, pw = A.create_user(conn, body.username, password=body.password,
                                    display_name=body.display_name or body.username,
                                    note=body.note, must_change=True,
                                    granted_by=p.user_id,
                                    grants=((body.role_code, body.scope_node),))
            A.log(conn, "grant", username=body.username, user_id=uid,
                  detail="建号 %s@%s" % (body.role_code, body.scope_node),
                  client_ip=_client_ip(request))
    except Exception as exc:                                     # noqa: BLE001
        # ★ 唯一约束撞车是**最常见的用户错误**，要给人话，不要给 500。
        if "unique" in str(exc).lower() or "23505" in str(exc):
            raise ApiError(409, "conflict", "用户名 %r 已经有人用了。" % body.username) from exc
        raise
    return ok({"id": uid, "username": body.username, "password": pw,
               "note": "口令只显示这一次，请立刻交给本人；他首次登录会被要求改密。"})


@router.post("/users/{uid}/active")
def set_active(uid: int, body: ActiveIn, request: Request,
               p: PrincipalDep, _a: admin_only) -> dict:
    """启用 / 停用。★ 停用会**同时吊销该账号全部会话**（见 accounts.set_active）——
    只改一个布尔值的话，他手里那个 cookie 还能继续用，而界面上写着"已停用"。"""
    from backend.db import accounts as A
    with A.connect() as conn:
        if body.active is False and uid == p.user_id:
            raise ApiError(400, ERR_BAD_REQUEST,
                           "不能停用自己 —— 那会让你立刻失去管理权限，且没人能救回来。")
        n = A.set_active(conn, uid, body.active)
        A.log(conn, "grant" if body.active else "revoke", user_id=uid,
              detail="%s（吊销会话 %d 个）" % ("启用" if body.active else "停用", n),
              client_ip=_client_ip(request))
    return ok({"id": uid, "active": body.active, "revoked_sessions": n})


@router.post("/users/{uid}/password")
def reset_password(uid: int, body: ResetPwIn, request: Request,
                   _p: PrincipalDep, _a: admin_only) -> dict:
    """重置口令（搭建方发号/救人用）。同样只显示一次，且对方下次登录必须改。"""
    from backend.db import accounts as A
    with A.connect() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = %s", (uid,)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", "没有这个账号。", {"id": uid})
        pw, n = A.set_password(conn, uid, body.password)
        A.log(conn, "password", username=row[0], user_id=uid,
              detail="由搭建方重置（吊销会话 %d 个）" % n, client_ip=_client_ip(request))
    return ok({"id": uid, "password": pw, "revoked_sessions": n,
               "note": "口令只显示这一次。"})


@router.post("/users/{uid}/grants")
def add_grant(uid: int, body: GrantIn, request: Request,
              p: PrincipalDep, _a: admin_only) -> dict:
    """加一条授权 (账号, 角色, 范围)。"""
    if body.role_code not in ROLE_CAPS:
        raise ApiError(400, ERR_BAD_REQUEST, "不认识的角色码 %r。" % body.role_code,
                       {"known": sorted(ROLE_CAPS)})
    from backend.db import accounts as A
    with A.connect() as conn:
        n = A.add_grant(conn, uid, body.role_code, body.scope_node, granted_by=p.user_id)
        A.log(conn, "grant", user_id=uid,
              detail="+%s@%s" % (body.role_code, body.scope_node),
              client_ip=_client_ip(request))
    return ok({"added": n, "user_id": uid, "role_code": body.role_code,
               "scope_node": body.scope_node})


@router.delete("/users/{uid}/grants")
def drop_grant(uid: int, role_code: str, scope_node: str, request: Request,
               _p: PrincipalDep, _a: admin_only) -> dict:
    """撤一条授权。★ 范围节点走**查询串**而不是路径段：范围节点里含 `|`
    （`c006|3|301`），放进路径段会被百分号编码，两边一旦编解码不一致就是
    "撤了一条不存在的授权" —— 而 `DELETE ... rowcount 0` **不报错**，
    屏幕上写着"已撤销"（本仓记过：撤销与"确认没东西可撤"必须分开，铁律 54）。
    """
    from backend.db import accounts as A
    with A.connect() as conn:
        n = A.drop_grant(conn, uid, role_code, scope_node)
        A.log(conn, "revoke", user_id=uid, detail="-%s@%s" % (role_code, scope_node),
              client_ip=_client_ip(request))
    if n == 0:
        raise ApiError(404, "not_found",
                       "这条授权本来就不存在（没有任何一行被删）——"
                       "不是「撤掉了」，是「从来没有」。",
                       {"user_id": uid, "role_code": role_code, "scope_node": scope_node})
    return ok({"removed": n})


# ── 小零件 ──────────────────────────────────────────────────────────

def _set_session_cookie(response: Response, cfg: Settings, token: str,
                        max_age: int) -> None:
    """★ 四个属性各有各的理由，少一个就是一种具体攻击：
        httponly  —— JS 读不到 ⇒ XSS 偷不走会话
        samesite  —— 跨站请求不带 ⇒ 挡 CSRF（本仓同时只做只读 GET，双保险）
        secure    —— 只在 HTTPS 上发。内网多为 HTTP，所以**做成配置**而不是写死 True
                     （写死 True 的话内网登录会静默失效：Set-Cookie 被浏览器丢掉，
                      表现为"登录成功但立刻又是未登录"）
        path="/"  —— 否则 /api 的 cookie 到 /data 就不带了
    """
    response.set_cookie(cfg.session_cookie, token, max_age=max_age,
                        httponly=True, samesite="lax", secure=cfg.session_cookie_secure,
                        path="/")


def _check_pw_strength(pw: str, username: str) -> None:
    """口令强度。★ 只拦真正会被字典命中的那几类，不做花哨规则：
    长度够 + 不等于用户名 + 不是纯数字/纯字母 + 不是常见弱口令。
    ★ 判据里**不含**"必须有大写+符号"那一套 —— 它会把人逼去写 `Abc12345!`
    这种同样在字典里的东西，而真正的长度要求被绕过去了。"""
    if len(pw) < PW_MIN:
        raise ApiError(400, ERR_BAD_REQUEST,
                       "口令至少 %d 位（现在是 %d 位）。" % (PW_MIN, len(pw)))
    low = pw.lower()
    if low == username.lower() or username.lower() in low:
        raise ApiError(400, ERR_BAD_REQUEST, "口令里不许包含用户名。")
    kinds = sum(bool(f(pw)) for f in (str.isdigit, str.isalpha, str.islower,
                                      str.isupper, lambda s: not s.isalnum()))
    if kinds < 2:
        raise ApiError(400, ERR_BAD_REQUEST, "口令太简单（至少要混用两种字符）。")
    WEAK = ("password", "12345678", "qwerty", "admin123", "abc12345",
            "11111111", "cdut1234", "lihua123")
    if any(w in low for w in WEAK):
        raise ApiError(400, ERR_BAD_REQUEST, "这个口令在常见弱口令表里。")
