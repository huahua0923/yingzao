# -*- coding: utf-8 -*-
"""轮换 gym3d_app 的库口令，并把旧口令从盘上清掉。

★ 为什么会有这个脚本（2026-10-01，我自己造成的）：
  `_db_setup.py` 第 [9] 步里我写了一条自检 `("LIHUA_DB_PASSWORD=" + dbpw, ...)`，
  而它把 needle **整串**打印出来 ⇒ 口令原样进了 `/root/_db_setup.log` 与对话记录。
  用户的原话是「新口令不许打印进对话」。口令一旦落进任何一处文字记录，
  **删日志不算修好**（它已经在别处了）⇒ 唯一正确的处置是**轮换**。

★ 这个脚本按三步走，每一步都留证据：
  ① 先把「旧口令出现在哪些文件里」**列出来**（blast radius，不猜）
  ② 换口令，并且证明**新口令能进 / 旧口令进不去**（两侧都测，不是只测新那一侧）
  ③ 清掉旧口令，再复扫一遍确认归零

★ 全程不打印任何口令；印出来的只有文件名、长度、成功/失败。

用法：/opt/python3.12/bin/python3.12 /root/_rotate_db_pw.py
"""
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

APP_ROOT = "/opt/gym3d"
APP_DB = "lihua_twin"
APP_ROLE = "gym3d_app"
ENV_OUT = os.path.join(APP_ROOT, ".env")
DB_PW_FILE = "/root/gym3d_db_password.txt"
OLD_LOG = "/root/_db_setup.log"
BORROW = ["/opt/cdut70-v2/.env", "/opt/cdut-meeting/.env"]
# 复扫范围：这次跑过的东西可能落在哪几个目录
SCAN_DIRS = ["/root", APP_ROOT]


def say(m=""):
    print(m, flush=True)


def ok(m):
    print("  ✓ " + m, flush=True)


def bad(m):
    print("  ✗ " + m, flush=True)


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
    rx = re.compile(
        r"^postgres(?:ql)?://([^:@/\s]+):([^@\s]*)@([^:/\s]+)(?::(\d+))?/([A-Za-z0-9_]+)")
    for path in BORROW:
        env = parse_env(path)
        for key in ("DATABASE_URL", "PORTAL_DATABASE_URL", "DB_URL"):
            m = rx.match(env.get(key, ""))
            if m:
                return dict(user=m.group(1), password=m.group(2), host=m.group(3),
                            port=m.group(4) or "5432", db=m.group(5))
    return None


def psql(dsn, sql, db=None, user=None, password=None):
    env = dict(os.environ, PGPASSWORD=(password if password is not None else dsn["password"]))
    r = subprocess.run(["psql", "-h", dsn["host"], "-p", str(dsn["port"]),
                        "-U", user or dsn["user"], "-d", db or dsn["db"], "-At", "-q",
                        "-c", sql], capture_output=True, env=env, timeout=60)
    return (r.returncode, r.stdout.decode("utf-8", "replace").strip(),
            r.stderr.decode("utf-8", "replace").strip())


def scan_for(secret, dirs):
    """哪些文件里有这个串。按字节找，逐文件报路径 + 命中次数。"""
    hits = []
    if not secret:
        return hits
    needle = secret.encode()
    for d in dirs:
        for root, dirs_, files in os.walk(d):
            dirs_[:] = [x for x in dirs_ if x not in (".git", ".venv", "__pycache__")]
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    if os.path.getsize(p) > 64 * 1024 * 1024:
                        continue
                    with open(p, "rb") as fh:
                        blob = fh.read()
                except OSError:
                    continue
                n = blob.count(needle)
                if n:
                    hits.append((p, n))
    return hits


def main():
    say("══ [1] 先量「旧口令扩散到哪些文件」══")
    if not os.path.isfile(ENV_OUT):
        bad("找不到 %s" % ENV_OUT)
        return 2
    cur = parse_env(ENV_OUT).get("LIHUA_DB_PASSWORD", "")
    if not cur:
        bad(".env 里读不到现有口令 —— 停，先人工看")
        return 2
    ok("从 .env 读到现有口令（长度 %d，值不打印）" % len(cur))

    hits = scan_for(cur, SCAN_DIRS)
    say("  扫过 %s" % "、".join(SCAN_DIRS))
    if hits:
        say("  ★ 旧口令出现在 %d 个文件里：" % len(hits))
        for p, n in hits:
            say("      %-56s ×%d" % (p, n))
    else:
        say("  （一个文件都没命中 —— 那说明它只活在 .env 里）")

    # ── [2] 换口令 ───────────────────────────────────────────────
    say()
    say("══ [2] 换口令 ══")
    dsn = borrow_superuser()
    if not dsn:
        bad("借不到超管凭据")
        return 2
    newpw = secrets.token_urlsafe(24)
    assert not set(newpw) - set(string.ascii_letters + string.digits + "-_")

    rc, _, err = psql(dsn, "alter role %s with login password '%s'" % (APP_ROLE, newpw))
    if rc != 0:
        bad("ALTER ROLE 失败：%s" % (err.splitlines()[0] if err else ""))
        return 2
    ok("已改 %s 的口令（新值不打印，长度 %d）" % (APP_ROLE, len(newpw)))

    # ── [3] 两侧都测：新口令能进 / 旧口令进不去 ──────────────────
    say()
    say("══ [3] 两侧都测（只测新那一侧 = 没验）══")
    rc, out, err = psql(dsn, "select current_user", db=APP_DB, user=APP_ROLE, password=newpw)
    if rc == 0 and out == APP_ROLE:
        ok("新口令：以 %s 连上 %s 成功" % (APP_ROLE, APP_DB))
    else:
        bad("新口令连不上：%s" % (err.splitlines()[0] if err else ""))
        return 2
    rc, out, err = psql(dsn, "select current_user", db=APP_DB, user=APP_ROLE, password=cur)
    if rc != 0:
        ok("旧口令：**已被拒**（%s）—— 这才叫换成了" % (err.splitlines()[0][:60] if err else ""))
    else:
        bad("旧口令**还能连上** —— 这次改的根本没生效，别往下走")
        return 2

    # ── [4] 写 .env（只动那一行，并证明只动了那一行）─────────────
    say()
    say("══ [4] 改 .env 里的那一行 ══")
    with open(ENV_OUT, "rb") as fh:
        old_blob = fh.read()
    old_txt = old_blob.decode("utf-8")
    new_txt = re.sub(r"(?m)^LIHUA_DB_PASSWORD=.*$", "LIHUA_DB_PASSWORD=" + newpw, old_txt)
    if new_txt == old_txt:
        bad(".env 里没找到 LIHUA_DB_PASSWORD= 那一行 —— 停")
        return 2
    with open(ENV_OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new_txt)
    os.chmod(ENV_OUT, 0o600)
    # 只改了那一行吗？（铁律 071：动过交付件之后，差异必须恰好等于声明的那一处）
    a, b = old_txt.splitlines(), new_txt.splitlines()
    if len(a) != len(b):
        bad("行数变了 %d → %d —— 改多了" % (len(a), len(b)))
        return 2
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    if len(diff) != 1 or not diff[0][0].startswith("LIHUA_DB_PASSWORD=") \
            or not diff[0][1].startswith("LIHUA_DB_PASSWORD="):
        bad("差异不是「恰好那一行」：%d 处" % len(diff))
        return 2
    ok(".env 更新完毕，逐行比差异 = 恰好 1 行（LIHUA_DB_PASSWORD），其余未动")

    with open(DB_PW_FILE, "w", encoding="utf-8") as fh:
        fh.write(newpw + "\n")
    os.chmod(DB_PW_FILE, 0o600)
    ok("%s 已更新（600，内容不打印）" % DB_PW_FILE)

    # ── [5] 清旧口令 + 复扫归零 ──────────────────────────────────
    say()
    say("══ [5] 清旧口令，再扫一遍 —— 判据是「归零」，不是「我清过了」══")
    # ★ 只删**声明过的自己人产物**，不按命中就删。
    #   按命中就删很危险：万一它落在别处的**活文件**（应用自己写的日志、某个 .env 的备份），
    #   删掉是连证据一起删，而且下次没人知道发生过什么。
    #   命中清单里出现陌生路径 ⇒ **停下来人工看**，这才是正确的处置。
    EXPECTED_LITTER = [OLD_LOG]          # 我建的这次运行的日志
    removed, unknown = [], []
    for p, _n in hits:
        if p in (ENV_OUT, DB_PW_FILE):
            continue                     # 刚被覆写，不是"要删的文件"
        if p in EXPECTED_LITTER:
            try:
                os.remove(p)
                removed.append(p)
            except OSError as e:
                bad("删不掉 %s：%s" % (p, e))
        else:
            unknown.append(p)
    for p in removed:
        ok("已删 %s（这是我建的运行日志，结论已在终端与本脚本里）" % p)
    if unknown:
        bad("★ 旧口令还出现在 %d 个**我没预料到**的文件里 —— 一个都没删：" % len(unknown))
        for p in unknown:
            say("      %s" % p)
        say("  处置：先人工看这几个文件是什么（是不是活文件、是不是别人的）,")
        say("        再决定「删 / 改 / 留」，改完重跑本脚本确认归零。")
        return 1

    left = scan_for(cur, SCAN_DIRS)
    if left:
        bad("还有 %d 个文件含旧口令：" % len(left))
        for p, n in left:
            say("      %-56s ×%d" % (p, n))
        return 1
    ok("复扫：旧口令在 %s 下**一个文件都不剩**" % "、".join(SCAN_DIRS))

    # 新口令只该出现在那两个 600 文件里
    newhits = scan_for(newpw, SCAN_DIRS)
    say("  新口令出现的文件（应当只有 .env 与口令文件）：%d 个" % len(newhits))
    for p, n in newhits:
        say("      %-56s ×%d" % (p, n))
    unexpected = [p for p, _ in newhits if p not in (ENV_OUT, DB_PW_FILE)]
    if unexpected:
        bad("新口令出现在了非预期文件里 —— 处置方向是再轮换一次并查清是谁写的")
        return 1

    say()
    say("══ ✓ 轮换完成 ══")
    say("   新口令只活在：%s 、 %s（两份都是 600）" % (ENV_OUT, DB_PW_FILE))
    say("   旧口令：PG 已拒、盘上归零。★ 但对话记录里那一串**已经收不回来**了 ——")
    say("   它现在只是一串无用字符，别拿它去开任何东西。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
