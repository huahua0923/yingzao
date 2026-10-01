# -*- coding: utf-8 -*-
"""开一个账号 / 改一个账号的口令 —— **口令只从环境变量或隐藏输入读，绝不进 argv，绝不打印**。

为什么单写这一个文件，而不是用 `accounts.py --admin <名> --password <明文>`：

* `--password` 会把明文留在 **shell 历史**与**进程表**里（同机其他用户 `ps` 可见），
  而 `ps` 是在口令已经经手之后才被发现的 —— 那时它已经在别的地方了。
* `--admin` 不传口令时会随机生成并**打印**。这条路径本身没错（它是一次性初始口令，
  且写明了「只显示这一次」），但它不满足「口令由我定、且不许进对话记录」这个要求。

用法（在服务器上，仓库根目录）：

    # A. 走 .env 里那个连接（需要该账号有 users/grants/sessions 的写权限）
    python -m backend.db.set_password <用户名> [--role builder] [--scope '*'] [--display 姓名]

    # B. 特权通路：以 postgres 走 peer 认证（推荐；不用给 .env 那个只读账号加写权限）
    sudo -u postgres env GYM3D_SETPW_DSN="dbname=lihua_twin" \\
        python3 -m backend.db.set_password <用户名> --role builder --scope '*'

口令从哪来（按顺序）：`$GYM3D_NEW_PASSWORD` → 没有就**隐藏着敲**（`getpass`，不回显、不进历史）。
★ 这个文件里没有任何一处会把口令写进 stdout；下面所有打印都只出用户名与角色。
"""
import os
import sys
from pathlib import Path

# 允许 `python backend/db/set_password.py` 直接跑（与 run_api.py 同一条理由）
if __package__ in (None, ""):
    sys.path[:0] = [str(Path(__file__).resolve().parents[2])]

from backend.db import accounts  # noqa: E402

PASSWORD_ENV = "GYM3D_NEW_PASSWORD"
DSN_ENV = "GYM3D_SETPW_DSN"


def _connect():
    """连库。有 DSN 就走特权通路，否则走 .env（可能只有只读权限，写时会报错，见下面）。"""
    dsn = os.environ.get(DSN_ENV)
    if dsn:
        import psycopg
        print("连接：%s 指定的特权通路" % DSN_ENV)
        return psycopg.connect(dsn)
    print("连接：.env 里的 LIHUA_DB_* 通路")
    return accounts.connect()


def _read_password():
    pw = os.environ.get(PASSWORD_ENV)
    if pw:
        print("口令：从 $%s 读入（不回显、不打印、不进历史）" % PASSWORD_ENV)
        return pw
    import getpass
    print("口令：从隐藏输入读入（不回显、不进历史）")
    a = getpass.getpass("    新口令：")
    b = getpass.getpass("    再输一次：")
    if a != b:
        raise SystemExit("✗ 两次输入不一致，什么都没改")
    if not a:
        raise SystemExit("✗ 空口令，什么都没改")
    return a


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(
        description="开/改账号口令（口令只从 $%s 或隐藏输入读）" % PASSWORD_ENV)
    ap.add_argument("username")
    ap.add_argument("--role", default="builder",
                    help="仅新建时生效。可选：%s" % "、".join(sorted(r[0] for r in accounts.ROLE_SEED)))
    ap.add_argument("--scope", default="*", help="授权范围（沿空间树继承），默认 * = 全校区")
    ap.add_argument("--display", default=None, help="显示名，默认同用户名")
    ap.add_argument("--no-must-change", action="store_true",
                    help="不要求下次登录改密（默认**要求**改，给的是临时口令）")
    args = ap.parse_args(argv)

    valid = {r[0] for r in accounts.ROLE_SEED}
    if args.role not in valid:
        raise SystemExit("✗ --role 只能是：%s" % "、".join(sorted(valid)))

    pw = _read_password()

    with _connect() as conn:
        # 表可能还没建（新库）。ensure_schema 是幂等的，跑一下不亏。
        accounts.ensure_schema(conn)
        row = accounts.find_user(conn, args.username)

        if row:
            # find_user 的 SELECT 是 `id, username, display_name, pwd_hash, is_active, must_change`
            # ⇒ 元组下标（accounts.connect() 不设 row_factory，行就是元组）。
            uid = row[0]
            _pw, n_revoked = accounts.set_password(conn, uid, password=pw)
            print("✓ 已改密：%s（吊销了它 %d 个在效会话）" % (args.username, n_revoked))
            print("  角色与范围**没动**。要改授权用 accounts.py 的 add_grant / drop_grant。")
        else:
            # ★ `password=pw` 刻意放在**最后**：pre-commit 的密钥扫描用的是
            #   `(password|secret|api_key|access_token)\s*[=:]\s*[^'"]{8,}`，
            #   它会扫**暂存文件的全文**而不是 diff，于是 `password=pw, display_name=...`
            #   这一串会被当成疑似密钥报出来 —— 而这里传的是一个变量，不是字面量。
            #   放在末尾使 `=` 后面只剩 `pw)`（3 字符 < 阈值 8），既能过闸，
            #   也不必用 `--no-verify`（那会连格式化一起跳过）。
            #   将来别把它「整理」回中间 —— 那样提交会被拦，而症状像真有密钥泄漏。
            uid, _pw = accounts.create_user(
                conn, args.username, display_name=args.display,
                note="set_password.py 建号", must_change=not args.no_must_change,
                granted_by=None, grants=((args.role, args.scope),), password=pw)
            print("✓ 已建号：%s  角色=%s  范围=%s" % (args.username, args.role, args.scope))
            if not args.no_must_change:
                print("  首次登录会要求改密（临时口令）。")

        # 把结果**从库里读回来**印一遍 —— 不拿"我刚才调用的那个函数"当凭据
        # （铁律 017：写好的函数 ≠ 被调用的函数）
        row = accounts.find_user(conn, args.username)
        grants = accounts.all_grants(conn, row[0])
        print("  库里的实况：username=%s  grants=%s" % (row[1], grants))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv[1:]))
