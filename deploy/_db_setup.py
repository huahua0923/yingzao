# -*- coding: utf-8 -*-
"""服务器侧：建角色 → 建库 → 灌 dump → 对账 → 清演示号 → 写 .env → 建第一个搭建方。

★ 凭据从哪来（零改动，2026-10-01 实测）：
  这台机的 `pg_hba.conf` 只有 md5（第 84 行 `local all all md5`），**没有 peer/trust**
  ⇒ `su - postgres -c psql` 会直接要口令，而 root 没有那个口令。
  计划里原本要临时插一行 `local all postgres trust` 开个窗口 —— 实测**不需要**：
  同机兄弟应用的 .env 里就有能连上的超级用户凭据（`/opt/cdut70-v2/.env` 的
  `DATABASE_URL` 与 `/opt/cdut-meeting/.env` 的 `DATABASE_URL`，实测 current_user=postgres、
  rolsuper=true）。⇒ 那个「改共享配置、用完还原」的窗口整个取消：
  在**一台别人的应用也在用的**服务器上，少动一个文件就少一个能把全机 PG 锁在门外的动作。

★ 这个脚本**从不打印任何口令**：口令只写进两个 600 的 root 文件，路径会打印、内容不会。

用法：/opt/python3.12/bin/python3.12 /root/_db_setup.py [--dry-run]
退出码：0 全过；非 0 = 倒在那一步（trap 写在包装 shell 里）
"""
import gzip
import os
import re
import secrets
import string
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except (AttributeError, OSError):
    pass

# ── 常量 ────────────────────────────────────────────────────────────
APP_ROOT = "/opt/gym3d"
APP_DB = "lihua_twin"
APP_ROLE = "gym3d_app"
SVC_USER = "gym3d"
DUMP_GZ = "/root/lihua_twin.sql.gz"
EXPECT = "/root/expected_counts.txt"
ENV_OUT = os.path.join(APP_ROOT, ".env")
DB_PW_FILE = "/root/gym3d_db_password.txt"
BOOT_PW_FILE = "/root/gym3d_builder_password.txt"
CAMPUS_DIR = "/opt/gym3d/campus-terrain"
DATA_DIR = "/opt/gym3d/data"
BOOT_USER = "builder"
API_PORT = 8141

# ★ 用户 2026-10-01 定死：**不要域名，直接 IP:8141**。所以是 0.0.0.0:8141 对外，
#   不套 nginx（这台机上 nginx 本来也没在跑，实测 inactive）。
API_HOST = "0.0.0.0"

BORROW = ["/opt/cdut70-v2/.env", "/opt/cdut-meeting/.env"]

# 本机 lihua_twin 的行数基准（deploy/_expected_counts 里那份是给人看的，这里再嵌一份，
# 但**对账读的是盘上那份文件** —— 嵌一份只用来核对文件本身没被改过）
DEMO_USERS = ("admin", "c006admin", "viewer")

FAILED = []


def say(msg=""):
    print(msg, flush=True)


def ok(msg):
    print("  ✓ " + msg, flush=True)


def bad(msg):
    print("  ✗ " + msg, flush=True)
    FAILED.append(msg)


def die(msg):
    print("  ✗ " + msg, flush=True)
    raise SystemExit(2)


# ── .env 解析（只为读键值，不执行任何东西）─────────────────────────
def parse_env(path):
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                out.setdefault(k.strip(), v)
    except OSError:
        pass
    return out


def borrow_superuser():
    """从兄弟应用的 .env 里借一个超管 DSN。返回 dict；**绝不打印口令**。"""
    rx = re.compile(
        r"^postgres(?:ql)?://([^:@/\s]+):([^@\s]*)@([^:/\s]+)(?::(\d+))?/([A-Za-z0-9_]+)")
    for path in BORROW:
        env = parse_env(path)
        for key in ("DATABASE_URL", "PORTAL_DATABASE_URL", "DB_URL"):
            url = env.get(key, "")
            m = rx.match(url)
            if not m:
                continue
            d = dict(user=m.group(1), password=m.group(2), host=m.group(3),
                     port=m.group(4) or "5432", db=m.group(5))
            d["src"] = "%s :: %s" % (path, key)
            return d
    return None


def psql(dsn, sql, db=None, user=None, password=None, quiet=True):
    """跑一条 SQL，返回 (rc, stdout, stderr)。dsn = 借来的超管凭据。"""
    u = user or dsn["user"]
    dbn = db or dsn["db"]
    env = dict(os.environ, PGPASSWORD=(password if password is not None else dsn["password"]))
    args = ["psql", "-h", dsn["host"], "-p", str(dsn["port"]), "-U", u, "-d", dbn, "-At"]
    if quiet:
        args.append("-q")
    args += ["-c", sql]
    r = subprocess.run(args, capture_output=True, env=env, timeout=600)
    return (r.returncode, r.stdout.decode("utf-8", "replace").strip(),
            r.stderr.decode("utf-8", "replace").strip())


def must(dsn, sql, what, **kw):
    rc, out, err = psql(dsn, sql, **kw)
    if rc != 0:
        die("%s 失败：%s" % (what, err.splitlines()[0] if err else "(无输出)"))
    return out


def main(argv):
    dry = "--dry-run" in argv

    # ── [1] 借凭据 ────────────────────────────────────────────────
    say("══ [1] 借一个能建库的凭据（零改动，不碰 pg_hba.conf）══")
    dsn = borrow_superuser()
    if not dsn:
        die("兄弟应用的 .env 里借不到能连 PG 的 DATABASE_URL")
    ok("凭据来自 %s（口令不打印）" % dsn["src"])
    out = must(dsn, "select current_user || '|' || "
                    "(select rolsuper from pg_roles where rolname = current_user)::text",
               "试连")
    ok("连接成功：current_user|rolsuper = %s" % out)
    if not out.endswith("|true"):
        die("借到的账号不是超级用户（%s）—— 建库需要超管" % out)

    ver = must(dsn, "show server_version", "读版本")
    enc = must(dsn, "select pg_encoding_to_char(encoding) || '|' || datcollate || '|' || "
                    "datctype from pg_database where datname='template1'", "读 template1")
    ok("服务器 PG %s；template1 = %s" % (ver, enc))

    # ── [2] 前置检查 ──────────────────────────────────────────────
    say()
    say("══ [2] 前置检查（不合就停，不猜）══")
    if not os.path.isdir(APP_ROOT):
        die("%s 不存在 —— 先跑 _setup_server.sh" % APP_ROOT)
    ok("仓库在 %s" % APP_ROOT)
    if not os.path.isfile(DUMP_GZ):
        die("找不到 %s —— 先把 lihua_twin.sql.gz 传上来" % DUMP_GZ)
    ok("dump 在 %s（%d 字节）" % (DUMP_GZ, os.path.getsize(DUMP_GZ)))
    if not os.path.isfile(EXPECT):
        die("找不到对账基准 %s" % EXPECT)
    n_exp = 0
    with open(EXPECT, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and "|" in line:
                n_exp += 1
    ok("对账基准有 %d 张表" % n_exp)
    if not os.path.isdir(os.path.join(APP_ROOT, ".venv")):
        die("%s/.venv 不存在 —— 先跑 _setup_server.sh" % APP_ROOT)
    ok("venv 在 %s/.venv" % APP_ROOT)

    exists = must(dsn, "select 1 from pg_database where datname='%s'" % APP_DB, "查库")
    if exists:
        # ★ 半途失败过的库要能重来，但「重来」不许变成「砸掉别人的库」。
        #   所以 --reset 只在**属主确实是本应用角色**时才动手 —— 这条判据是身份，不是名字。
        owner = must(dsn, "select pg_get_userbyid(datdba) from pg_database "
                          "where datname='%s'" % APP_DB, "读库属主")
        if "--reset" not in argv:
            die("库 %s 已经存在（属主 %s）—— 本脚本默认不覆盖。"
                "确认可以清掉再带 --reset 重跑" % (APP_DB, owner))
        if owner != APP_ROLE:
            die("--reset 被拒：库 %s 的属主是 **%s**，不是 %s "
                "—— 那多半是别人的库，我不动它" % (APP_DB, owner, APP_ROLE))
        ok("--reset：库 %s 属主确为 %s，先断连接再删" % (APP_DB, APP_ROLE))
        must(dsn, "select pg_terminate_backend(pid) from pg_stat_activity "
                  "where datname='%s' and pid <> pg_backend_pid()" % APP_DB, "断连接")
        must(dsn, "drop database %s" % APP_DB, "删库")
        ok("已删（上一次多半倒在中途，这是重来不是覆盖）")
    ok("库 %s 尚不存在（可以建）" % APP_DB)

    if dry:
        say()
        say("  --dry-run：到此为止，一个字节都没写。")
        return 0

    # ── [3] 系统用户 ──────────────────────────────────────────────
    say()
    say("══ [3] 建系统用户 %s（systemd 用它跑服务）══" % SVC_USER)
    r = subprocess.run(["id", "-u", SVC_USER], capture_output=True)
    if r.returncode == 0:
        ok("%s 已存在" % SVC_USER)
    else:
        r = subprocess.run(["useradd", "--system", "--home-dir", APP_ROOT,
                            "--shell", "/sbin/nologin", SVC_USER],
                           capture_output=True)
        if r.returncode != 0:
            die("useradd 失败：%s" % r.stderr.decode("utf-8", "replace")[:200])
        ok("已建 %s（system 用户，home=%s，不许登录）" % (SVC_USER, APP_ROOT))

    # ── [4] 角色 ──────────────────────────────────────────────────
    say()
    say("══ [4] 建数据库角色 + 口令 ══")
    # 口令用 token_urlsafe：只有 [A-Za-z0-9_-]，不带引号/反斜杠，
    # 直接嵌进 CREATE ROLE 的字符串里没有转义问题（仍然断言一次，防将来换生成器）
    dbpw = secrets.token_urlsafe(24)
    assert not set(dbpw) - set(string.ascii_letters + string.digits + "-_"), "口令里有不安全的字符"
    assert "'" not in dbpw and "\\" not in dbpw

    have = must(dsn, "select 1 from pg_roles where rolname='%s'" % APP_ROLE, "查角色")
    if have:
        must(dsn, "alter role %s with login password '%s'" % (APP_ROLE, dbpw), "改角色口令")
        ok("角色 %s 已存在 —— 改了它的口令（幂等）" % APP_ROLE)
    else:
        must(dsn, "create role %s with login password '%s'" % (APP_ROLE, dbpw), "建角色")
        ok("已建角色 %s" % APP_ROLE)

    # ★ 为什么是**可写**角色，不是计划里那个只读的 gym3d_ro：
    #   登录本身就要写库 —— `accounts.py` 会 `INSERT INTO sessions` / `INSERT INTO auth_log`，
    #   锚定还要写 `building_anchors`，而且运行期还会执行 `CREATE TABLE IF NOT EXISTS`。
    #   给只读权限 ⇒ **登录都进不去**。范围仍然圈死在**这一个库**里：
    #   这台机同时托着 cdut-meeting / coze-agents，所以**不做** REASSIGN OWNED 这类跨库动作。
    with open(DB_PW_FILE, "w", encoding="utf-8") as fh:
        fh.write(dbpw + "\n")
    os.chmod(DB_PW_FILE, 0o600)
    ok("口令写进 %s（600，内容不打印）" % DB_PW_FILE)

    # ── [5] 建库 ──────────────────────────────────────────────────
    say()
    say("══ [5] 建库 %s ══" % APP_DB)
    tpl_enc, tpl_col, tpl_ctype = enc.split("|")
    must(dsn, "create database %s owner %s encoding '%s' template template0 "
              "lc_collate '%s' lc_ctype '%s'"
         % (APP_DB, APP_ROLE, tpl_enc, tpl_col, tpl_ctype), "建库")
    got = must(dsn, "select pg_encoding_to_char(encoding) || '|' || datcollate "
                    "from pg_database where datname='%s'" % APP_DB, "核库")
    ok("已建 %s（owner=%s）：%s   ← 与 template1 同口径" % (APP_DB, APP_ROLE, got))

    # ★ 灌之前先把 schema 的 CREATE 给出去：`public` 在 PG13 里默认就给了 PUBLIC，
    #   但这台机要是被加固过就没有了 —— 而 gym3d_app 运行期还要 `CREATE TABLE IF NOT EXISTS`。
    must(dsn, "grant all on schema public to %s" % APP_ROLE, "授权 schema", db=APP_DB)
    ok("GRANT ALL ON SCHEMA public TO %s" % APP_ROLE)

    # ── [6] 灌 dump（以 gym3d_app 身份灌，对象就归它）──────────────
    say()
    say("══ [6] 灌 dump ══")
    # ★ 用 gym3d_app 而不是 postgres 去灌：dump 是 `--no-owner` 的，
    #   对象归「执行灌库的那个角色」。以 gym3d_app 灌 ⇒ 它拥有全部表，
    #   运行期不需要再补一堆授权（补授权那条路容易漏一张表，而漏了只在某条路由上炸）。
    say("  以 %s 身份灌（对象归它，省掉一整轮补授权）" % APP_ROLE)
    cmd = ("gzip -dc %s | psql -h %s -p %s -U %s -d %s -v ON_ERROR_STOP=1 -q"
           % (DUMP_GZ, dsn["host"], dsn["port"], APP_ROLE, APP_DB))
    env = dict(os.environ, PGPASSWORD=dbpw)
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, env=env, timeout=1800)
    so = r.stdout.decode("utf-8", "replace").strip()
    se = r.stderr.decode("utf-8", "replace").strip()
    if so:
        say("  stdout: " + so[:500])
    if r.returncode != 0:
        say("  stderr: " + se[:1500])
        die("灌库失败（rc=%d）。★ ON_ERROR_STOP=1 是故意的：宁可停在这里，"
            "也不要带着错误往下走" % r.returncode)
    if se:
        say("  stderr（非致命提示）: " + se[:600])
    ok("灌完，psql rc=0")

    # ── [7] 对账：行数逐表比 ──────────────────────────────────────
    say()
    say("══ [7] 对账（服务器 ←→ 本机基准）══")
    expect = {}
    with open(EXPECT, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and "|" in line:
                t, n = line.rsplit("|", 1)
                expect[t.strip()] = int(n)

    srv_tables = must(dsn, "select table_name from information_schema.tables "
                           "where table_schema='public' order by 1", "列表", db=APP_DB)
    srv_tables = [t for t in srv_tables.splitlines() if t.strip()]
    say("  服务器 %d 张表 / 基准 %d 张表" % (len(srv_tables), len(expect)))
    ok("表名集合一致" if set(srv_tables) == set(expect) else "★ 表名集合不一致")

    say("  %-18s %10s %10s   %s" % ("表", "服务器", "本机基准", "判定"))
    n_bad = 0
    for t in sorted(set(srv_tables) | set(expect)):
        got = must(dsn, 'select count(*) from public."%s"' % t, "数 %s" % t, db=APP_DB)
        g = int(got)
        e = expect.get(t)
        if e is None:
            verdict = "★ 基准里没有这张表"
            n_bad += 1
        elif g == e:
            verdict = "一致"
        else:
            verdict = "★ 不一致（差 %+d）" % (g - e)
            n_bad += 1
        say("  %-18s %10d %10s   %s" % (t, g, e if e is not None else "-", verdict))
    if n_bad:
        bad("对账有 %d 处不一致 —— 先查清楚再继续" % n_bad)
    else:
        ok("★ %d 张表行数**逐表一致**" % len(expect))

    # ── [8] 清演示号 ──────────────────────────────────────────────
    say()
    say("══ [8] 清掉三个演示号 ══")
    say("  为什么：它们是我在开发期建的，口令进过对话记录（用户原话「新口令不许打印进对话」）")
    before = must(dsn, "select count(*) from users", "数 users", db=APP_DB)
    casc = must(dsn, "select "
                     "(select count(*) from grants where user_id in "
                     " (select id from users where username in ('%s'))) || ' 条 grants / ' || "
                     "(select count(*) from sessions where user_id in "
                     " (select id from users where username in ('%s'))) || ' 条 sessions'"
                % ("','".join(DEMO_USERS), "','".join(DEMO_USERS)),
                "预数将被级联删掉的行", db=APP_DB)
    say("  删之前 users=%s；会级联带走：%s" % (before, casc))
    say("  （`grants.granted_by` 那三行实测是 NULL，不会挡；room_history/room_manual/"
        "building_anchors 里指向这三个号的实测都是 0 行）")
    out = must(dsn, "delete from users where username in ('%s') returning username"
               % "','".join(DEMO_USERS), "删演示号", db=APP_DB)
    say("  删掉：%s" % (out.replace("\n", ", ") or "(一行都没删到 —— 可疑)"))
    after = must(dsn, "select count(*) from users", "复查 users", db=APP_DB)
    left = must(dsn, "select count(*) from users where username in ('%s')"
                % "','".join(DEMO_USERS), "复查演示号", db=APP_DB)
    if left != "0":
        bad("还有 %s 个演示号没删掉" % left)
    else:
        ok("users %s → %s，三个演示号剩 %s 个" % (before, after, left))
    # ★ 留下的是「历史」不是「账号」：auth_log 没有外键，那 210 行登录取证记录**故意不删**
    nlog = must(dsn, "select count(*) from auth_log", "数 auth_log", db=APP_DB)
    ok("auth_log 保留 %s 行（登录取证历史，无外键、不指向活账号）" % nlog)

    # ── [9] 写 .env ───────────────────────────────────────────────
    say()
    say("══ [9] 写 %s ══" % ENV_OUT)
    mem = must(dsn, "show max_connections", "读 max_connections")
    env_txt = """# 校园数字孪生平台 · 服务器配置  —— 自动生成于 2026-10-01，口令由脚本生成、不入库不入 git
# ★ 这个文件是 600、属主 %(svc)s。它**不在 git 里**（.gitignore 已挡）。
GYM3D_ROOT=%(root)s
GYM3D_DATA_DIR=%(data)s
GYM3D_CAMPUS_DIR=%(campus)s

# ── 对外形态：用户 2026-10-01 定「不要域名，用 8141」──
#    所以直挂 0.0.0.0:8141，不套 nginx（这台机上 nginx 本来也没在跑，实测 inactive）。
#    ★ 好处不止是省一层：直挂时 TCP 对端就是真实客户端地址，
#      `client_is_loopback()` 才量得准；反代到 127.0.0.1 会让它对谁都返回"是回环"。
GYM3D_HOST=%(host)s
GYM3D_PORT=%(port)d
GYM3D_API_PREFIX=/api
GYM3D_ENV=prod
GYM3D_LOG_LEVEL=info
GYM3D_CORS_ORIGINS=

# ── 两道闸，都必须显式写（默认值不是安全那一侧）──────────────────
# ★ compute 默认是 **True**，而 `deps.py` 里 `if not cfg.compute` 排在回环判断**之前**
#   ⇒ 置 0 才是把执行面整条关死的那一个开关。它不误伤门户页的写入：
#   `require_cap` 完全不读 cfg.compute，`POST /api/portal/anchors` 挂的是
#   `require_cap("manage")`，没有 require_compute ⇒ 搭建方在服务器上照样能锚定。
GYM3D_COMPUTE=0
# ★ loopback_breakglass 默认是 **True**，命中就直接给全校区全能力的 builder。
#   服务器上必须是 0，否则「从本机发来的请求」等于无条件超级权限。
GYM3D_LOOPBACK_BREAKGLASS=0
# ★ 必须 0：对外是**明文 HTTP**（IP:8141，没有 TLS）。置 1 会让浏览器不回传 cookie，
#   症状是「登录页面能开、点了没反应」，而服务端一切正常（auth.py:413 secure=...）。
#   将来上了 443/HTTPS 再改成 1。
GYM3D_SESSION_COOKIE_SECURE=0

# ── 数据库 ────────────────────────────────────────────────────
# ★ 账号是**可写**的（不是只读）：登录本身就要写 sessions/auth_log，
#   锚定要写 building_anchors，运行期还要 CREATE TABLE IF NOT EXISTS。
#   权限范围只圈在 %(dbname)s 这一个库里。
LIHUA_DB_HOST=localhost
LIHUA_DB_PORT=5432
LIHUA_DB_USER=%(role)s
LIHUA_DB_NAME=%(dbname)s
LIHUA_DB_PASSWORD=%(dbpw)s
LIHUA_DB_REQUIRED=1
""" % dict(svc=SVC_USER, root=APP_ROOT, data=DATA_DIR, campus=CAMPUS_DIR,
           host=API_HOST, port=API_PORT, role=APP_ROLE, dbname=APP_DB, dbpw=dbpw)

    old = None
    if os.path.isfile(ENV_OUT):
        with open(ENV_OUT, "rb") as fh:
            old = fh.read()
        say("  ⚠ %s 已存在（%d 字节）—— 先备份再覆盖" % (ENV_OUT, len(old)))
        bkp = ENV_OUT + ".bak-" + __import__("time").strftime("%Y%m%d-%H%M%S")
        with open(bkp, "wb") as fh:
            fh.write(old)
        ok("备份到 %s" % bkp)

    with open(ENV_OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(env_txt)
    os.chmod(ENV_OUT, 0o600)
    # 读回来核：文件里确实有那几把闸，且都在关的那一侧
    #
    # ★★ 2026-10-01 我自己在这里踩了一次，记在最前面：
    #   原来最后一条写的是 `("LIHUA_DB_PASSWORD=" + dbpw, "库口令写进去了")`，
    #   而打印用的是 `needle` **本身** ⇒ `ok("%s（%s）" % (needle, why))`
    #   把**口令原样**印进了日志、也印进了对话。
    #   用户的原话是「新口令不许打印进对话」；口令一旦进过任何一处文字记录，
    #   就只剩轮换一条路（删日志不够 —— 它已经在别处了）。
    #   ⇒ 规矩：**凡是「读完核对」这一类的打印，被判的那个值必须先经过一次「只比不印」**。
    #   下面把「字面量键」和「秘密值」拆成两段：前者可以整串印，后者只印长度与结论。
    literals = [
        ("GYM3D_COMPUTE=0", "执行面关死（deps.py 里它排在回环判断之前）"),
        ("GYM3D_LOOPBACK_BREAKGLASS=0", "回环破窗关死（默认是 True，必须显式关）"),
        ("GYM3D_SESSION_COOKIE_SECURE=0", "明文 HTTP 下 cookie 能回传（置 1 会静默登不上）"),
        ("LIHUA_DB_USER=" + APP_ROLE, "用的是应用角色，不是 postgres"),
        ("LIHUA_DB_NAME=" + APP_DB, "连的是这个库"),
        ("LIHUA_DB_REQUIRED=1", "prod 缺库口令时拒绝启动"),
    ]
    for needle, why in literals:
        if needle in back:
            ok("%s   （%s）" % (needle, why))
        else:
            bad("%s **没写进去** —— %s" % (needle, why))

    # 秘密值这一条：**只比不印**。印出来的只有「长度」和「一致 / 不一致」。
    got_pw = ""
    for line in back.splitlines():
        if line.startswith("LIHUA_DB_PASSWORD="):
            got_pw = line.split("=", 1)[1]
            break
    if got_pw == dbpw:
        ok("LIHUA_DB_PASSWORD 与生成值逐字符相同（值不打印；长度 %d）" % len(dbpw))
    elif got_pw:
        bad("LIHUA_DB_PASSWORD 写进去了，但与生成值**不一致**（值不打印）")
    else:
        bad("LIHUA_DB_PASSWORD 没写进去（值不打印）")
    ok("%s 已写（%d 字节，600）" % (ENV_OUT, len(back)))

    # ── [10] 属主 ─────────────────────────────────────────────────
    say()
    say("══ [10] 把 %s 交给 %s ══" % (APP_ROOT, SVC_USER))
    r = subprocess.run(["chown", "-R", "%s:%s" % (SVC_USER, SVC_USER), APP_ROOT],
                       capture_output=True)
    if r.returncode != 0:
        die("chown 失败：%s" % r.stderr.decode("utf-8", "replace")[:200])
    ok("chown -R %s:%s %s" % (SVC_USER, SVC_USER, APP_ROOT))
    r = subprocess.run(["chmod", "600", ENV_OUT], capture_output=True)
    ok(".env 权限再钉一次 600（chown 之后）")

    # ── [11] 第一个搭建方 ─────────────────────────────────────────
    say()
    say("══ [11] 建第一个搭建方账号（否则没人能建号）══")
    say("  计划原话：「删完要留一个能登进去的搭建方，否则没人能建账号」")
    boot_pw = secrets.token_urlsafe(18)
    with open(BOOT_PW_FILE, "w", encoding="utf-8") as fh:
        fh.write(boot_pw + "\n")
    os.chmod(BOOT_PW_FILE, 0o600)
    ok("临时口令写进 %s（600，内容不打印；首次登录会强制改密）" % BOOT_PW_FILE)

    venv_py = os.path.join(APP_ROOT, ".venv", "bin", "python")
    env11 = dict(os.environ, GYM3D_NEW_PASSWORD=boot_pw, PYTHONIOENCODING="utf-8")
    r = subprocess.run([venv_py, "-m", "backend.db.set_password", BOOT_USER,
                        "--role", "builder", "--scope", "*",
                        "--display", "搭建方"],
                       capture_output=True, cwd=APP_ROOT, env=env11, timeout=180)
    so = r.stdout.decode("utf-8", "replace").strip()
    se = r.stderr.decode("utf-8", "replace").strip()
    for line in so.splitlines():
        say("  " + line)
    if se:
        say("  stderr: " + se[:800])
    if r.returncode != 0:
        bad("建号失败（rc=%d）—— 服务起来了也登不进去" % r.returncode)
    else:
        ok("建号 rc=0")

    # 从库里读回来当凭据（不拿"我刚调用的那个函数"当证据，铁律 017）
    out = must(dsn, "select u.username || ' | ' || u.display_name || ' | active=' "
                    "|| u.is_active::text || ' | must_change=' || u.must_change::text "
                    "|| ' | ' || g.role_code || ' @ ' || g.scope_node "
                    "from users u join grants g on g.user_id = u.id "
                    "where u.username = '%s'" % BOOT_USER, "读回账号", db=APP_DB)
    if out:
        ok("库里的实况：%s" % out)
    else:
        bad("库里查不到 %s —— 建号那条路没真写进去" % BOOT_USER)

    left_users = must(dsn, "select string_agg(username, ', ' order by id) from users",
                      "最终账号清单", db=APP_DB)
    ok("服务器上最终账号：[%s]" % left_users)

    # ── 收尾 ──────────────────────────────────────────────────────
    say()
    if FAILED:
        say("══ ✗ 有 %d 处没通过 ══" % len(FAILED))
        for f in FAILED:
            say("   · " + f)
        return 1
    say("══ ✓ 建库这一阶段全过 ══")
    say("   库      %s @ localhost:5432   角色 %s（可写，仅本库）" % (APP_DB, APP_ROLE))
    say("   .env    %s（600）" % ENV_OUT)
    say("   口令①   %s（库账号，600）" % DB_PW_FILE)
    say("   口令②   %s（%s 的临时口令，600，首次登录强制改密）" % (BOOT_PW_FILE, BOOT_USER))
    say("   ★ 上面两处口令**内容不打印**：要取用请在服务器上 `cat`，用完删掉。")
    say("   PG max_connections = %s" % mem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
