# -*- coding: utf-8 -*-
"""账号 / 角色 / 授权 / 会话 —— 校园数字孪生平台的**身份与权限**数据层（PostgreSQL / lihua_twin）。

## 为什么把「四个概念」拆开存

    身份   users      一个账号就是一个"人"。
    角色   roles      一组**能力**的名字（能干什么）。与"人"无关，是字典表。
    授权   grants     (账号, 角色, 范围节点) 三元组 —— **在哪**、以**什么身份**。
    会话   sessions   服务端会话。Cookie 里只有一个随机串，真身在这张表。

★ 关键：**能力（角色）与范围（空间节点）是两个正交的维度。**
  用户口述的四类人（搭建方 / 普通管理员 / 回线管理员 / 普通人）是**能力**；
  「哪个学院看哪几栋」是**范围**。把两者塞进一个字段，就会出现"给某人单开一个角色"
  这种没法维护的局面。所以 grants 是三元组，且**一个账号可以有多条**（多角色、多范围）。

★ 权限沿空间树**向下继承**（行业做法：Azure Digital Twins RBAC）：
  在 `c006` 上授权 ⇒ 自动覆盖 c006 的所有楼层与房间。判权时是"这条范围节点是不是
  **请求节点的祖先**"，不是相等。见 `backend/api/authz.py`。

## 为什么 password 只存哈希、会话只存哈希

密码用 scrypt（stdlib，无第三方依赖，CLAUDE.md 明令 scrypt/bcrypt）。格式自带参数，
以后调 N/r/p 时旧口令仍可验（verify 读的是**存下来的**参数，不是当前常量）。
会话同理：库里那一列叫 `token_hash`，**cookie 里的原文一个字节都不落库** ——
库被看到（备份、慢查询日志、误导出）也拿不到可用的会话串。

## 为什么 `author` 不接外键

`room_manual.author` / `room_history.author` 里躺着 `c103-读图补录`（16 行）、
`mutation-check`（1 行）—— 这是**来源标记**，不是账号。硬接 `REFERENCES users(username)`
会当场建不上（库里没有这几个"用户"），而更坏的做法是给它们补几个假用户：
那会把「这批数是读图补录来的」这件史实，改写成「有个叫 c103-读图补录的人改的」。
⇒ 改为**新增 `author_user_id` 列**接外键，老行留 NULL。**NULL 的含义是"非账号写入"**，
写进注释里，别让后来人以为它是"未知用户"。

命令行：
    python backend/db/accounts.py --init                 # 只建表 + 灌角色字典（幂等）
    python backend/db/accounts.py --init --admin zhangsan # 建表并开一个搭建方账号（口令随机，只打印一次）
    python backend/db/accounts.py --list                 # 列账号与授权
"""
import argparse
import base64
import hashlib
import hmac
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

import psycopg

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))
sys.path.insert(0, _HERE)
from db_config import db_params  # noqa: E402

# ---------------------------------------------------------------- 常量

# ★ 口令哈希参数**写死在这里，不许散落在调用点**：参数一变，全校账号一起失效。
#   验证时读的是**存下来的**参数（见 verify_password），所以以后调参不用重灌口令。
SCRYPT_N = 2 ** 14      # CPU/内存代价：128*N*r = 16 MiB，约 50~100 ms/次
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_LEN = 16

# 会话存活期。★ 内网办公场景，8 小时够一个工作日；过期就得重新登录，
#   而"重新登录"正是唯一能确定"人还在"的信号。
SESSION_HOURS = 8
# ★ cookie 名**不在这里**：唯一出处是 `backend/api/settings.py` 的 `session_cookie`
#   （`GYM3D_SESSION_COOKIE`）。2026-10-01 建账号体系时把原来这里那个常量删了 ——
#   同一个字符串两处各写一份，改一处漏一处**不报错**，只会让浏览器带着一个
#   服务端不认的 cookie 一直转圈（CLAUDE.md 铁律 18）。

# ★ 能力三档：高含低。**无 view 则无 edit/manage** —— 不许改看不见的东西。
CAPS = ("view", "edit", "manage")

# 角色字典。code 是**稳定标识**（进库、进断言、进 URL），name 是给人看的。
# ★ 这几个名字是**照抄用户原话**的，不许顺手改成"系统管理员"之类：
#   「回线管理员」这个词我还不知道确切所指（用户写「井、通道、线以及回线」，线与回线并列），
#   照抄原词，等问清楚再动。
ROLE_SEED = [
    ("builder",   "搭建方",     "输入 CAD 图并生成成果；管理账号与授权；跑生成流程", 10),
    ("admin",     "普通管理员", "查看授权范围内房屋的情况与使用情况", 20),
    ("line_admin", "回线管理员", "负责井、通道、线、回线的功能", 30),
    ("viewer",    "普通人",     "只能查看", 40),
]

# 角色 → 能力。★ 这张表是**代码**不是数据：它要被断言逐条核，且改动要过 code review。
#   放进数据库会让"谁把自己提权了"查不出来。
ROLE_CAPS = {
    "builder":    ("view", "edit", "manage"),
    "admin":      ("view",),
    "line_admin": ("view", "edit"),
    "viewer":     ("view",),
}


# ---------------------------------------------------------------- 建表

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  display_name  TEXT,
  pwd_hash      TEXT NOT NULL,
  pwd_algo      TEXT NOT NULL DEFAULT 'scrypt',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  must_change   BOOLEAN NOT NULL DEFAULT FALSE,  -- 首次登录必须改密（发号时置 TRUE）
  note          TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ,
  -- ★ 用户名不许有空串/空白：' ' 和 '' 会让"这个人是谁"在界面上看不出来
  CONSTRAINT users_username_not_blank CHECK (btrim(username) <> '')
);

CREATE TABLE IF NOT EXISTS roles (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  rank        INT NOT NULL DEFAULT 100   -- 只用于**列表排序**，不参与判权
);

-- 授权 = (账号, 角色, 范围节点)。范围节点是空间树上的一个节点 id：
--   '*'        全校区（根）
--   'c006'     一栋楼（覆盖它的全部楼层与房间）
--   'c006|3'   一层
--   'c006|3|301' 一间房
--   后期：'pipe|A'、'line|A-07' 等（管廊/管线树的节点，同一套判权逻辑）
CREATE TABLE IF NOT EXISTS grants (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_code  TEXT   NOT NULL REFERENCES roles(code),
  scope_node TEXT   NOT NULL DEFAULT '*',
  granted_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, role_code, scope_node)
);
CREATE INDEX IF NOT EXISTS idx_grants_user ON grants(user_id);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash   TEXT PRIMARY KEY,          -- sha256(cookie 原文)。原文不落库
  user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  client_ip    TEXT,
  user_agent   TEXT,
  revoked_at   TIMESTAMPTZ                -- 登出/踢下线：**置位**而不是删行，好审计
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_exp  ON sessions(expires_at);

-- 审计：登录成败、授权变更、越权尝试。★ 越权尝试要记 —— 它是唯一能看出"有人在试"的地方。
CREATE TABLE IF NOT EXISTS auth_log (
  id        BIGSERIAL PRIMARY KEY,
  at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  username  TEXT,
  user_id   BIGINT,
  action    TEXT NOT NULL,      -- login / logout / login_failed / grant / revoke / denied / password
  detail    TEXT,
  client_ip TEXT,
  ok        BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_auth_log_at ON auth_log(at);

-- 老表的 author 接账号：**加列不改造老列**（理由见模块 docstring）
ALTER TABLE room_manual  ADD COLUMN IF NOT EXISTS author_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE room_history ADD COLUMN IF NOT EXISTS author_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
"""


def connect():
    """连库。autocommit=False —— 与 rooms_registry.connect() 同一约定。"""
    conn = psycopg.connect(**db_params())
    conn.autocommit = False
    return conn


def ensure_schema(conn):
    """建表 + 灌角色字典。**幂等**，可反复跑。"""
    conn.execute(SCHEMA_SQL)
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO roles (code, name, description, rank)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (code) DO UPDATE
                 SET name = EXCLUDED.name,
                     description = EXCLUDED.description,
                     rank = EXCLUDED.rank""", ROLE_SEED)
    conn.commit()


# ---------------------------------------------------------------- 口令

def hash_password(password, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P):
    """`scrypt$N$r$p$salt_b64$dk_b64` —— 参数随哈希一起存，以后调参不废旧口令。"""
    if not password:
        raise ValueError("口令不许为空")
    salt = secrets.token_bytes(SALT_LEN)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                        n=n, r=r, p=p, dklen=SCRYPT_DKLEN)
    b64 = lambda b: base64.b64encode(b).decode("ascii")   # noqa: E731
    return "scrypt$%d$%d$%d$%s$%s" % (n, r, p, b64(salt), b64(dk))


def verify_password(password, stored):
    """校验。**任何异常都当"不通过"**（坏哈希、空值、格式不认识 ⇒ False，不抛给调用方）。"""
    try:
        algo, s_n, s_r, s_p, salt_b64, dk_b64 = str(stored).split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        want = base64.b64decode(dk_b64)
        got = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                             n=int(s_n), r=int(s_r), p=int(s_p), dklen=len(want))
    except Exception:
        return False
    return hmac.compare_digest(got, want)      # ★ 常量时间：不许用 ==


def random_password(nbytes=9):
    """发号时用的随机口令（12 个 url-safe 字符，约 72 bit）。"""
    return secrets.token_urlsafe(nbytes)


# ---------------------------------------------------------------- 账号

def create_user(conn, username, password=None, display_name=None,
                note=None, must_change=True, granted_by=None,
                # ★ 元组是 **(角色码, 范围)**，不是 (范围, 角色码)。
                #   这里原来写的是 `(("*", "builder"),)` —— 顺序反了，于是 role_code
                #   落成 `"*"`，撞 `grants_role_code_fkey`。后果不只是"这个默认值没用"：
                #   `main()` 里那条 `--init --admin <用户名>` **不带** grants，正是吃这个
                #   默认值 ⇒ **开第一个搭建方账号的命令直接崩**，而那时库里一个账号都没有
                #   ⇒ 谁也登不进这个系统。自检 45 条全过没抓住它，因为自检每次调用
                #   **都显式传了 grants**，这一支从头到尾没被走过。
                #   （本仓铁律 45/60：判据没覆盖的那一支，"通过"不说明任何事。）
                grants=(("builder", "*"),)):
    """开一个号并授权。返回 (user_id, 明文口令)。

    ★ 口令只在这一刻存在于内存里，**返回值是它唯一的出口** —— 库里只有哈希，
      所以要由调用方负责"只打印一次"。不传 password 就随机生成。
    """
    username = (username or "").strip()
    if not username:
        raise ValueError("用户名不许为空")
    pw = password or random_password()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO users (username, display_name, pwd_hash, note, must_change)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (username, display_name or username, hash_password(pw), note, must_change))
        uid = cur.fetchone()[0]
        for role_code, scope in grants:
            cur.execute(
                """INSERT INTO grants (user_id, role_code, scope_node, granted_by)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (uid, role_code, scope, granted_by))
    conn.commit()
    return uid, pw


def find_user(conn, username):
    return conn.execute(
        """SELECT id, username, display_name, pwd_hash, is_active, must_change
             FROM users WHERE username = %s""", (username,)).fetchone()


def all_grants(conn, user_id):
    """这个账号的全部授权：[(role_code, scope_node), ...]。"""
    return conn.execute(
        "SELECT role_code, scope_node FROM grants WHERE user_id = %s",
        (user_id,)).fetchall()


# ---------------------------------------------------------------- 登录

def authenticate(conn, username, password, client_ip=None):
    """校验用户名口令。**成功返回用户字典，失败返回 None**（不抛错、不区分原因）。

    ★ 三处刻意的设计：
      ① **用户名不存在与口令不对，对外是同一句话。** 区分开就等于送人一个
         "这个账号存在"的探测器。这里连耗时都尽量齐平（见 ②）。
      ② **账号不存在时也跑一次 scrypt**。不跑的后果是：不存在的账号**立刻**返回，
         存在的账号要等 ~80ms —— 攻击者用响应时间就能枚举出全校用户名。
         这是这类系统最典型的一个洞，而它在功能上**完全看不出来**。
      ③ **停用的账号返回 None**（与不存在同形），并在 auth_log 里留痕 ——
         停用是给管理员看的，不是给被停用的人看的。
    """
    row = find_user(conn, username)
    if row is None:
        # 拿一个固定的假哈希跑一次：耗时对齐，且**不**写任何东西
        verify_password(password, _DUMMY_HASH)
        log(conn, "login_failed", username=username, detail="无此账号",
            client_ip=client_ip, ok=False)
        return None
    uid, uname, display, pwd_hash, is_active, must_change = row
    if not verify_password(password, pwd_hash):
        log(conn, "login_failed", username=uname, user_id=uid, detail="口令不对",
            client_ip=client_ip, ok=False)
        return None
    if not is_active:
        log(conn, "login_failed", username=uname, user_id=uid, detail="账号已停用",
            client_ip=client_ip, ok=False)
        return None
    conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (uid,))
    conn.commit()
    log(conn, "login", username=uname, user_id=uid, client_ip=client_ip)
    return {"user_id": uid, "username": uname, "display_name": display,
            "must_change": must_change}


# ★ 一个**语法合法但谁也猜不到**的哈希，专供"账号不存在"那条分支对齐耗时用。
#   为什么在 import 时现造，而不是**手抄**一个 base64 常量：
#     手抄的那一版就是「两处写同一个数，一致证明不了它对」（CLAUDE.md 铁律 18）——
#     我把明文改一个字，它在屏幕上、在类型上、在任何静态检查里**都不会报错**，
#     只会在真登录时静默地变成"耗时没对齐"。现造则格式不可能错。
#   代价：import 时付一次 scrypt（约 80ms），而 accounts 是被惰性 import 的。
#   为什么不是"每次调用时现造"：那会让这条分支**更慢**（多一次加密），
#   耗时差反而朝反方向拉开 —— 修一个侧信道修出另一个。
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


# ---------------------------------------------------------------- 账号管理（搭建方用）

def set_password(conn, user_id, password=None):
    """改口令。返回明文口令（不传则随机生成）。

    ★ 顺带做两件事，**都不许省**：
      ① `must_change` 归位 —— 管理员替他设的临时口令，下次登录他还得改；
      ② **把这个账号的所有会话吊销**。改了口令却不踢掉已有会话，
         等于"改了密码但小偷还坐在屋里" —— 而屏幕上显示的是"改密成功"。
    """
    pw = password or random_password()
    conn.execute("UPDATE users SET pwd_hash = %s, must_change = TRUE, "
                 "updated_at = now() WHERE id = %s", (hash_password(pw), user_id))
    n = conn.execute("UPDATE sessions SET revoked_at = now() "
                     "WHERE user_id = %s AND revoked_at IS NULL", (user_id,)).rowcount
    conn.commit()
    return pw, n


def change_own_password(conn, user_id, new_password):
    """用户自己改密（**调用方必须先验过旧口令**）。改完同样踢掉其它会话。"""
    conn.execute("UPDATE users SET pwd_hash = %s, must_change = FALSE, "
                 "updated_at = now() WHERE id = %s",
                 (hash_password(new_password), user_id))
    conn.execute("UPDATE sessions SET revoked_at = now() "
                 "WHERE user_id = %s AND revoked_at IS NULL", (user_id,))
    conn.commit()


def set_active(conn, user_id, active):
    """启用 / 停用。★ 停用时**同时吊销全部会话** —— 只改 `is_active`
    靠 `load_session` 里那一条 `u.is_active` 兜住也行，但那要求每个读会话的
    地方都记得联表。两把锁守同一个东西时，**不能只有一把在内存里**
    （本仓 memory: two-locks-one-in-memory）。直接吊销是硬的那把。"""
    conn.execute("UPDATE users SET is_active = %s, updated_at = now() WHERE id = %s",
                 (bool(active), user_id))
    n = 0
    if not active:
        n = conn.execute("UPDATE sessions SET revoked_at = now() "
                         "WHERE user_id = %s AND revoked_at IS NULL", (user_id,)).rowcount
    conn.commit()
    return n


def add_grant(conn, user_id, role_code, scope_node, granted_by=None):
    return conn.execute(
        """INSERT INTO grants (user_id, role_code, scope_node, granted_by)
           VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
        (user_id, role_code, scope_node or "*", granted_by)).rowcount


def drop_grant(conn, user_id, role_code, scope_node):
    return conn.execute(
        "DELETE FROM grants WHERE user_id = %s AND role_code = %s AND scope_node = %s",
        (user_id, role_code, scope_node)).rowcount


def list_users(conn):
    """账号清单（含授权）。搭建方的账号管理页就是读这个。"""
    rows = conn.execute("""
        SELECT u.id, u.username, u.display_name, u.is_active, u.must_change,
               u.created_at::date::text,
               coalesce(u.last_login_at::date::text, ''),
               coalesce(string_agg(g.role_code || '@' || g.scope_node, ', '
                                   ORDER BY g.role_code, g.scope_node), '')
          FROM users u LEFT JOIN grants g ON g.user_id = u.id
         GROUP BY u.id ORDER BY u.id
    """).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "username": r[1], "display_name": r[2] or r[1],
            "is_active": r[3], "must_change": r[4], "created_at": r[5],
            "last_login_at": r[6],
            "grants": [{"role_code": p.split("@", 1)[0], "scope_node": p.split("@", 1)[1]}
                       for p in r[7].split(", ") if "@" in p],
        })
    return out


def list_roles(conn):
    return [{"code": r[0], "name": r[1], "description": r[2], "rank": r[3],
             "caps": list(ROLE_CAPS.get(r[0], ()))}
            for r in conn.execute(
                "SELECT code, name, description, rank FROM roles ORDER BY rank").fetchall()]


def log(conn, action, username=None, user_id=None, detail=None,
        client_ip=None, ok=True):
    """审计一行。★ 审计写失败**不许**把主流程带崩 —— 但也不许静默，所以打日志。"""
    try:
        conn.execute(
            """INSERT INTO auth_log (username, user_id, action, detail, client_ip, ok)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (username, user_id, action, detail, client_ip, ok))
        conn.commit()
    except Exception as exc:                                  # noqa: BLE001
        print("[accounts] 审计写入失败：%s" % exc, file=sys.stderr)


# ---------------------------------------------------------------- 会话

def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn, user_id, client_ip=None, user_agent=None, hours=SESSION_HOURS):
    """建会话，返回**cookie 原文**（只在这一次出现；库里只有 sha256）。"""
    token = secrets.token_urlsafe(32)
    conn.execute(
        """INSERT INTO sessions (token_hash, user_id, expires_at, client_ip, user_agent)
           VALUES (%s, %s, now() + %s::interval, %s, %s)""",
        (_token_hash(token), user_id, "%d hours" % hours, client_ip,
         (user_agent or "")[:300]))
    conn.commit()
    return token


# ★ `last_seen_at` 的刷新间隔。为什么需要这个常数：
#   `load_session` 每次都写一行再 commit，而一道闸要罩住 **每一个静态请求**
#   （一页三维要取几十个 GLB/JSON）。不节流的话，"看一眼楼"会变成几十次写盘 +
#   几十次 commit，而且是**并发**的 —— 那既慢、又把 sessions 表写成一个热点。
#   ★ 节流的代价是"最后活动时间"最多旧 5 分钟。这个字段只用于"这人还在不在"，
#     5 分钟的粒度绰绰有余；真正的安全判断（过期/吊销/停用）**一次都没少判**。
LAST_SEEN_REFRESH_MIN = 5


def load_session(conn, token):
    """用 cookie 原文换回 (user_id, username, 是否要改密)。过期/被吊销/账号停用 ⇒ None。

    ★ 三种失效**都要在这里判完**：过期看 `expires_at`、登出看 `revoked_at`、
      停用看 `u.is_active`。少判一个的后果是"登出了但 cookie 还能用"
      —— 而屏幕上一切正常（本仓铁律 144：「读不到」不是「一致」的同族）。
    """
    if not token:
        return None
    th = _token_hash(token)
    row = conn.execute(
        """SELECT s.user_id, u.username, u.must_change, u.is_active
             FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s
              AND s.revoked_at IS NULL
              AND s.expires_at > now()""", (th,)).fetchone()
    if not row or not row[3]:
        return None
    conn.execute(
        "UPDATE sessions SET last_seen_at = now() "
        "WHERE token_hash = %s AND last_seen_at < now() - %s::interval",
        (th, "%d minutes" % LAST_SEEN_REFRESH_MIN))
    conn.commit()
    return {"user_id": row[0], "username": row[1], "must_change": row[2]}


def revoke_session(conn, token):
    conn.execute(
        "UPDATE sessions SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL",
        (_token_hash(token),))
    conn.commit()


def sweep_sessions(conn, days=7):
    """清掉过期已久的会话行。★ 过期的**先别删**（还要用于"我什么时候登出过"的排查），
    只删过期超过 days 天的。"""
    n = conn.execute(
        "DELETE FROM sessions WHERE expires_at < now() - %s::interval",
        ("%d days" % days,)).rowcount
    conn.commit()
    return n


# ---------------------------------------------------------------- CLI

def _print_users(conn):
    rows = conn.execute("""
        SELECT u.id, u.username, u.display_name, u.is_active, u.must_change,
               u.last_login_at::date::text,
               coalesce(string_agg(g.role_code || '@' || g.scope_node, ', '
                                   ORDER BY g.role_code, g.scope_node), '（无授权）')
          FROM users u LEFT JOIN grants g ON g.user_id = u.id
         GROUP BY u.id ORDER BY u.id
    """).fetchall()
    if not rows:
        print("（一个账号都没有 —— 先跑 --init --admin <用户名>）")
        return
    print("%-4s %-16s %-12s %-6s %-8s %-12s %s"
          % ("id", "用户名", "显示名", "启用", "要改密", "上次登录", "授权"))
    for r in rows:
        print("%-4d %-16s %-12s %-6s %-8s %-12s %s"
              % (r[0], r[1], r[2] or "", "是" if r[3] else "否",
                 "是" if r[4] else "否", r[5] or "从未", r[6]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="账号 / 角色 / 授权 / 会话")
    ap.add_argument("--init", action="store_true", help="建表 + 灌角色字典（幂等）")
    ap.add_argument("--admin", metavar="用户名", help="开一个搭建方账号（口令随机，只打印一次）")
    ap.add_argument("--password", help="指定口令（不传则随机生成；★ 别把它写进任何文件）")
    ap.add_argument("--list", action="store_true", help="列出账号与授权")
    ap.add_argument("--sweep", action="store_true", help="清理过期已久的会话行")
    args = ap.parse_args(argv)

    with connect() as conn:
        if args.init:
            ensure_schema(conn)
            print("✓ 建表完成：users / roles / grants / sessions / auth_log（+ 两张老表新增 author_user_id）")
            for code, name, _d, rank in sorted(ROLE_SEED, key=lambda x: x[3]):
                print("   角色 %-11s %-6s 能力：%s"
                      % (code, name, "、".join(ROLE_CAPS.get(code, ())) or "（无）"))
        if args.admin:
            if not conn.execute("SELECT to_regclass('public.users')").fetchone()[0]:
                ensure_schema(conn)
            uid, pw = create_user(conn, args.admin, password=args.password,
                                  display_name=args.admin, note="初始搭建方账号")
            print()
            print("★ 账号已建，口令**只显示这一次**，请立刻记下（库里只有哈希，找不回来）：")
            print("     用户名：%s" % args.admin)
            print("     口令　：%s" % pw)
            print("   首次登录会要求改密。")
        if args.list or not (args.init or args.admin or args.sweep):
            _print_users(conn)
        if args.sweep:
            print("清理过期会话 %d 行" % sweep_sessions(conn))


if __name__ == "__main__":
    # 判词全中文，Windows 控制台默认 GBK ⇒ 不加这四行会在打印时炸
    # （本仓铁律 168 的同族；`errors="replace"` 保证编码失败也不吞结论）。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
