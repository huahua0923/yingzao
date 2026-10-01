# -*- coding: utf-8 -*-
"""账号/角色/授权/会话 —— **在真库上跑**的自检。

## 为什么每条反面判据都要配一条正面判据

本仓铁律 153：**一个"永远拒"的闸能通过全部阴性对照。** 只验"外键拒掉了非法值"，
一个 `FOREIGN KEY ... REFERENCES 不存在的表` 或写反的 CHECK 也会全绿。
所以每一组都是成对的：
  拒的必须拒   ← 阴性
  **该放的必须放** ← 阳性（这才是分辨力所在）

## 为什么这套必须清理干净、而且要断言清理真的删到了行

本仓铁律 029：用真库跑验收，必须**同时**断言「前后计数相同」与「清理真的删到了行」。
只断言前者，一个"什么都没插进去"的坏脚本也会通过（前后都是 0）。

命令行：python backend/db/accounts_selftest.py
退出码：0 全过 / 1 有失败
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))
sys.path.insert(0, _HERE)

import psycopg  # noqa: E402
import accounts as A  # noqa: E402

# 自检用的账号一律带这个前缀，清理时只删它们 —— 不会碰到真账号
PREFIX = "_selftest_"

_fails = []
_n = 0


def check(name, cond, detail=""):
    global _n
    _n += 1
    if cond:
        print("  ✓ %s" % name)
    else:
        print("  ✗ %s   %s" % (name, detail))
        _fails.append(name)


# SQLSTATE → 是哪一类错。★ 判"被拒了"必须指名是哪一条约束拒的：
#   只判"抛错了"的话，一条列名写错的语句（42703=列不存在）也会让它全绿。
SQLSTATE = {
    "23503": "外键违反",
    "23505": "唯一违反",
    "23514": "CHECK 违反",
    "23502": "非空违反",
}


def expect_raise(conn, name, fn, want=None):
    """反面判据：这段**必须抛错**，且要抛的是**指定的那一种**。

    ★ 两个坑（本仓都栽过）：
      1. 不判 SQLSTATE ⇒ 任何错误都能让它通过；
      2. 不 rollback ⇒ 上一条失败把事务打挂，**后面每条都必然报 `current transaction
         is aborted`**，于是全部"被拒"看上去都成立了 —— 那是假绿。
    """
    global _n
    _n += 1
    try:
        fn()
        conn.commit()
    except psycopg.Error as exc:
        code = exc.sqlstate
        kind = SQLSTATE.get(code, "SQLSTATE %s" % code)
        conn.rollback()                        # ★ 立刻归位，别让事务带着伤往下走
        if want and code != want:
            print("  ✗ %s —— 拒是拒了，但**拒错了原因**：期望 %s(%s)，实际 %s(%s)"
                  % (name, SQLSTATE.get(want, "?"), want, kind, code))
            _fails.append(name)
            return
        print("  ✓ %s（%s，SQLSTATE %s）" % (name, kind, code))
        return
    except Exception as exc:                                   # noqa: BLE001
        conn.rollback()
        print("  ✗ %s —— 抛的不是数据库错，是 %s：%s" % (name, type(exc).__name__, exc))
        _fails.append(name)
        return
    print("  ✗ %s —— **没有被拒**，这条闸是装饰" % name)
    _fails.append(name)


def cleanup(conn):
    """删掉自检造的一切。返回删掉的行数，供断言。"""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE user_id IN "
                    "(SELECT id FROM users WHERE username LIKE %s)", (PREFIX + "%",))
        n_sess = cur.rowcount
        cur.execute("DELETE FROM grants WHERE user_id IN "
                    "(SELECT id FROM users WHERE username LIKE %s)", (PREFIX + "%",))
        n_grant = cur.rowcount
        cur.execute("UPDATE room_manual SET author_user_id = NULL "
                    "WHERE author_user_id IN (SELECT id FROM users WHERE username LIKE %s)",
                    (PREFIX + "%",))
        n_rm = cur.rowcount
        cur.execute("DELETE FROM users WHERE username LIKE %s", (PREFIX + "%",))
        n_user = cur.rowcount
    conn.commit()
    return {"sessions": n_sess, "grants": n_grant, "room_manual": n_rm, "users": n_user}


def main():
    with A.connect() as conn:
        # ---- 0. 起手先清干净（上一趟跑崩留下的），并记住基线
        cleanup(conn)
        base_users = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        base_grants = conn.execute("SELECT count(*) FROM grants").fetchone()[0]
        base_sessions = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        base_manual = conn.execute(
            "SELECT count(*) FROM room_manual WHERE author_user_id IS NOT NULL").fetchone()[0]

        print("\n【1】建表与角色字典")
        A.ensure_schema(conn)
        for t in ("users", "roles", "grants", "sessions", "auth_log"):
            check("表 %s 存在" % t,
                  conn.execute("SELECT to_regclass('public.%s')" % t).fetchone()[0] is not None)
        got = dict(conn.execute("SELECT code, name FROM roles").fetchall())
        expect = {c: n for c, n, _d, _r in A.ROLE_SEED}
        check("四个角色齐全且名字与用户原话一致", got == expect, "库里=%s" % got)
        check("能力矩阵里 builder 含 manage", "manage" in A.ROLE_CAPS["builder"])
        check("★ 没有哪个角色的能力集里出现未知档",
              all(set(v) <= set(A.CAPS) for v in A.ROLE_CAPS.values()),
              str(A.ROLE_CAPS))

        print("\n【2】口令：哈希不是明文，验密两个方向都要对")
        pw = "Test-Pw-12345"
        h = A.hash_password(pw)
        check("口令没被明文写进哈希串", pw not in h, h[:40])
        check("哈希带算法与参数（以后调参不废旧口令）", h.startswith("scrypt$%d$%d$%d$" % (
            A.SCRYPT_N, A.SCRYPT_R, A.SCRYPT_P)), h[:30])
        check("★ 正确口令 ⇒ 通过（阳性）", A.verify_password(pw, h) is True)
        check("错口令 ⇒ 不通过（阴性）", A.verify_password(pw + "x", h) is False)
        check("空口令 ⇒ 不通过", A.verify_password("", h) is False)
        check("哈希串损坏 ⇒ 不通过而不是抛异常", A.verify_password(pw, "垃圾") is False)
        check("同口令两次哈希不同（加了盐）", A.hash_password(pw) != h)

        print("\n【3】账号与授权")
        uid, pw1 = A.create_user(conn, PREFIX + "alice", display_name="自检A",
                                 password=pw, grants=(("admin", "c006"), ("viewer", "c001")))
        row = A.find_user(conn, PREFIX + "alice")
        check("插进去读得回来", row is not None and row[0] == uid)
        check("库里存的不是明文口令", pw not in row[3])
        g = A.all_grants(conn, uid)
        check("两条授权都在", sorted(g) == [("admin", "c006"), ("viewer", "c001")], str(g))
        check("user_id 是**新**的（不是撞上老账号）", uid > 0)
        expect_raise(conn, "同名账号再建 ⇒ 被 UNIQUE 拒",
                     lambda: A.create_user(conn, PREFIX + "alice", password=pw,
                                           grants=(("viewer", "*"),)), want="23505")
        expect_raise(conn, "角色码不在字典里 ⇒ 被外键拒",
                     lambda: A.create_user(conn, PREFIX + "carol", password=pw,
                                           grants=(("学工处", "*"),)), want="23503")
        expect_raise(conn, "重复的 (账号,角色,范围) ⇒ 被 UNIQUE 拒",
                     lambda: conn.execute(
                         "INSERT INTO grants (user_id, role_code, scope_node) "
                         "VALUES (%s,%s,%s)", (uid, "admin", "c006")), want="23505")
        expect_raise(conn, "空用户名 ⇒ 被 CHECK 拒",
                     lambda: conn.execute(
                         "INSERT INTO users (username, pwd_hash) VALUES (%s, %s)",
                         ("   ", A.hash_password(pw))), want="23514")
        expect_raise(conn, "指向不存在的账号建会话 ⇒ 被外键拒",
                     lambda: conn.execute(
                         "INSERT INTO sessions (token_hash, user_id, expires_at) "
                         "VALUES (%s, %s, now() + interval '1 hour')",
                         ("deadbeef", 99999999)), want="23503")
        check("★ 合法授权仍然放行（阳性；若上面几条把事务打挂了，这条会红）",
              conn.execute("SELECT count(*) FROM grants WHERE user_id = %s", (uid,)
                           ).fetchone()[0] == 2)
        A.create_user(conn, PREFIX + "bob", password=pw, grants=(("viewer", "c006"),))
        n = conn.execute("SELECT count(*) FROM grants g JOIN users u ON u.id=g.user_id "
                         "WHERE u.username LIKE %s", (PREFIX + "%",)).fetchone()[0]
        check("bob 的授权真的落库了（3 条）", n == 3, "实际 %d" % n)

        # ★★ 2026-10-01 补：【3】上面每一条**都显式传了 `grants`**
        #   ⇒ `create_user` 的**默认值那一支从来没被走过**，而
        #     `python backend/db/accounts.py --init --admin <用户名>`（开**第一个**搭建方）
        #     恰恰不传 grants —— 它吃的就是这个默认值。
        #   实测那个默认值当时写成了 `(("*", "builder"),)`：`(角色码, 范围)` **顺序反了**，
        #   role_code 落成 `"*"`，撞 `grants_role_code_fkey` ⇒ **开号命令当场崩**
        #   （退出码 1，不是静默），而那时库里一个账号都没有 ⇒ 谁也登不进来。
        #   45 条判据全绿，因为 45 条都绕开了这一支。
        #   ⇒ 判据要钉**两样**：① 顺序（角色码在前）② 它**真落进库了**（不是在内存里）。
        #   （同族：铁律 066「清单里那条要什么资源只能从源码读出来」+ 铁律 151
        #     「我扫完了的作用域是我自己写的那条 glob」—— 覆盖的边界由**调用形态**决定，
        #     不由"我读过这个函数"决定。）
        uid_d, _pw_d = A.create_user(conn, PREFIX + "dave", password=pw)
        gd = A.all_grants(conn, uid_d)
        check("★ 不传 grants ⇒ 默认给 builder@*（元组顺序不能反）",
              sorted(gd) == [("builder", "*")],
              "实际 %r，期望 [('builder', '*')]" % (sorted(gd),))
        check("★ 默认授权真的落进库（不是只在内存里）",
              conn.execute("SELECT role_code, scope_node FROM grants WHERE user_id=%s",
                           (uid_d,)).fetchone() == ("builder", "*"))

        print("\n【4】★ author_user_id 外键 —— 拒的拒、放的放")
        rk = conn.execute("SELECT room_key FROM room_manual LIMIT 1").fetchone()
        if rk is None:
            check("room_manual 里有一条可用来试的记录", False, "表是空的，这组验不了")
        else:
            rk = rk[0]
            before = conn.execute("SELECT author_user_id FROM room_manual WHERE room_key=%s",
                                  (rk,)).fetchone()[0]
            expect_raise(conn, "非法 author_user_id ⇒ 被外键拒",
                         lambda: conn.execute(
                             "UPDATE room_manual SET author_user_id = 99999999 "
                             "WHERE room_key = %s", (rk,)), want="23503")
            # ★ 阳性：合法 id 必须放得进去，否则上面那条"拒"可能只是因为列写错了
            conn.execute("UPDATE room_manual SET author_user_id = %s WHERE room_key = %s",
                         (uid, rk))
            conn.commit()
            got = conn.execute("SELECT author_user_id FROM room_manual WHERE room_key=%s",
                               (rk,)).fetchone()[0]
            check("★ 合法 author_user_id ⇒ 放行（阳性，这才证明外键是活的）", got == uid,
                  "写进去读回来是 %r" % (got,))
            check("老数据的 author 文本列**没被动过**",
                  conn.execute("SELECT author FROM room_manual WHERE room_key=%s",
                               (rk,)).fetchone()[0] is not None)
            conn.execute("UPDATE room_manual SET author_user_id = %s WHERE room_key = %s",
                         (before, rk))
            conn.commit()

        print("\n【5】会话：建 / 读回 / 过期 / 吊销 / 停用")
        tok = A.create_session(conn, uid, client_ip="127.0.0.1", user_agent="selftest")
        th = A._token_hash(tok)
        check("库里存的是哈希，不是 cookie 原文",
              conn.execute("SELECT count(*) FROM sessions WHERE token_hash=%s", (th,)
                           ).fetchone()[0] == 1 and tok != th)
        s = A.load_session(conn, tok)
        check("★ 有效 cookie ⇒ 读得回来（阳性）", s and s["user_id"] == uid, str(s))
        check("乱编的 cookie ⇒ 读不到", A.load_session(conn, "not-a-real-token") is None)
        check("空 cookie ⇒ 读不到", A.load_session(conn, "") is None)
        A.revoke_session(conn, tok)
        check("登出后同一个 cookie ⇒ 读不到", A.load_session(conn, tok) is None)
        check("会话行**还在**（置位不是删行，好审计）",
              conn.execute("SELECT count(*) FROM sessions WHERE token_hash=%s", (th,)
                           ).fetchone()[0] == 1)
        tok2 = A.create_session(conn, uid)
        conn.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (uid,))
        conn.commit()
        check("账号停用后，**手里有效的 cookie 也失效**", A.load_session(conn, tok2) is None)
        conn.execute("UPDATE users SET is_active = TRUE WHERE id = %s", (uid,))
        conn.commit()
        check("★ 账号启用回来 ⇒ cookie 又有效（阳性）", A.load_session(conn, tok2) is not None)

        print("\n【6】清理，并且断言**真的删到了行**")
        removed = cleanup(conn)
        check("清掉了自检账号（>0 行）", removed["users"] >= 2, str(removed))
        check("清掉了自检会话（>0 行）", removed["sessions"] >= 2, str(removed))
        check("清掉了自检授权（>0 行）", removed["grants"] >= 3, str(removed))
        after_users = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        after_grants = conn.execute("SELECT count(*) FROM grants").fetchone()[0]
        after_sessions = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        after_manual = conn.execute(
            "SELECT count(*) FROM room_manual WHERE author_user_id IS NOT NULL").fetchone()[0]
        check("★ 计数回到基线（users）", after_users == base_users,
              "%d → %d" % (base_users, after_users))
        check("★ 计数回到基线（grants）", after_grants == base_grants,
              "%d → %d" % (base_grants, after_grants))
        check("★ 计数回到基线（sessions）", after_sessions == base_sessions,
              "%d → %d" % (base_sessions, after_sessions))
        check("★ 计数回到基线（room_manual.author_user_id）",
              after_manual == base_manual, "%d → %d" % (base_manual, after_manual))
        check("★ 最后一次清理是空跑（干净收尾）", all(v == 0 for v in cleanup(conn).values()))

    print("\n" + "=" * 60)
    print("共 %d 条判据，失败 %d 条 %s"
          % (_n, len(_fails), "⇒ 全过 ✓" if not _fails else "⇒ " + "; ".join(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    # ★ 本文件判词是中文 + `✓`，Windows 控制台默认 GBK ⇒ 第一句 print 就
    #   `UnicodeEncodeError`（2026-10-01 实测），屏幕上看着像"这个自检坏了"。
    #   同一段四行在 `backend/api/authz.py` / `backend/api/deps.py` 里都有
    #   —— 同族共有的那一步，这个文件原来漏了（铁律 168）。
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
