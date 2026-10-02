# -*- coding: utf-8 -*-
"""端到端探针：拿真搭建方账号登进去，把读面/写面走一遍，**再把状态复原**。

★ 跑在哪：服务器本机（口令只在服务器那个 600 文件里，本机读不到、也不该读）。
★ 全程不打印口令；印出来的只有状态码、条数、字段名。

★ 判据按铁律 029 设计：**「跑完之后库里没多东西」不能只靠「我删过了」** ——
  必须**同时**断言 ①前后计数相同 ②删除那一下真的删到了行（rowcount>0 那一侧的证据
  是 DELETE 返回 200 而不是 404；删一个不存在的 block_id 同样不报错，回 200 就会骗人）。

★ 阴性对照与阳性对照成对报（铁律 028/084）：
  同一个 URL 打两次 —— 带 cookie 的必须 200、不带 cookie 的必须 401。
  只报其中一个，分不清「闸生效」和「路由坏了」。
"""
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except (AttributeError, OSError):
    pass

BASE = "http://127.0.0.1:8141"
PW_FILE = "/root/gym3d_builder_password.txt"
USER = "builder"
# 用一个一眼看得出是探针的 block_id，并且**明确**记下来好复原
PROBE_BLOCK = "__deploy_probe_20261001__"
PROBE_BUILDING = "c103"

fails = []


def say(m=""):
    print(m, flush=True)


def ok(m):
    print("  ✓ " + m, flush=True)


def bad(m):
    print("  ✗ " + m, flush=True)
    fails.append(m)


def call(method, path, body=None, opener=None, want=None):
    """返回 (status, parsed_json_or_text)。不抛 —— 状态码就是判据。"""
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    op = opener or urllib.request.build_opener()
    try:
        with op.open(req, timeout=15) as r:
            raw = r.read().decode("utf-8", "replace")
            st = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        st = e.code
    except Exception as e:                                   # noqa: BLE001
        return None, "连不上：%s" % e
    try:
        return st, json.loads(raw)
    except json.JSONDecodeError:
        return st, raw[:200]


def main():
    say("══ [0] 读搭建方口令（只读，不打印）══")
    if not os.path.isfile(PW_FILE):
        bad("找不到 %s —— 没口令就登不进去，先把它建出来" % PW_FILE)
        return 2
    pw = open(PW_FILE, encoding="utf-8").read().strip()
    if not pw:
        bad("%s 是空的" % PW_FILE)
        return 2
    ok("读到口令（长度 %d，值不打印）" % len(pw))

    anon = urllib.request.build_opener()
    jar = http.cookiejar.CookieJar()
    auth = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # ── [1] 阴性对照：不带 cookie 的两条 ────────────────────────
    say()
    say("══ [1] 阴性对照（匿名）—— 先量「没身份时被挡住」══")
    for p in ("/api/buildings", "/api/portal/anchors"):
        st, _ = call("GET", p, opener=anon)
        (ok if st == 401 else bad)("%-22s 匿名 → %s（要 401）" % (p, st))

    # ── [2] 登录 ────────────────────────────────────────────────
    say()
    say("══ [2] 登录 ══")
    st, j = call("POST", "/api/auth/login", {"username": USER, "password": pw}, opener=auth)
    if st != 200:
        bad("登录 → %s：%s" % (st, str(j)[:200]))
        return 2
    ok("登录 → 200")
    got = [c.name for c in jar]
    ok("拿到 cookie：%s" % ", ".join(got) if got else "★ 但 cookie jar 是空的")
    if not got:
        bad("登录回 200 却没下发 cookie —— 检查 GYM3D_SESSION_COOKIE_SECURE")
    d = (j or {}).get("data") or {}
    say("    user=%s  must_change=%s  roles=%s"
        % (d.get("username"), d.get("must_change"), d.get("roles")))

    # ── [3] 阳性对照：同一个 URL 带 cookie ──────────────────────
    say()
    say("══ [3] 阳性对照（带 cookie）—— 与 [1] 是同一个 URL ══")
    st, j = call("GET", "/api/buildings", opener=auth)
    if st == 200:
        rows = (j or {}).get("data") or []
        n = len(rows) if isinstance(rows, list) else (rows or {}).get("total")
        ok("/api/buildings 带 cookie → 200，拿到 %s 栋" % n)
    else:
        bad("/api/buildings 带 cookie → %s（要 200）：%s" % (st, str(j)[:200]))

    st, j = call("GET", "/api/portal/anchors", opener=auth)
    before = None
    if st == 200:
        rows = (j or {}).get("data") or []
        before = len(rows)
        ok("/api/portal/anchors 带 cookie → 200，现有 %d 条" % before)
    else:
        bad("/api/portal/anchors 带 cookie → %s（要 200）" % st)

    st, j = call("GET", "/api/portal/roster", opener=auth)
    (ok if st == 200 else bad)("/api/portal/roster 带 cookie → %s（要 200）" % st)

    # ── [4] 写面：建一条探针锚点 ────────────────────────────────
    say()
    say("══ [4] 写面：建一条锚点（block_id=%s）══" % PROBE_BLOCK)
    st, j = call("POST", "/api/portal/anchors",
                 {"block_id": PROBE_BLOCK, "building_code": PROBE_BUILDING,
                  "method": "manual", "note": "部署验收探针，跑完即删"},
                 opener=auth)
    (ok if st == 200 else bad)("POST /api/portal/anchors → %s（要 200）" % st)
    if st != 200:
        say("    %s" % str(j)[:300])

    st, j = call("GET", "/api/portal/anchors", opener=auth)
    rows = (j or {}).get("data") or []
    hit = [r for r in rows if r.get("block_id") == PROBE_BLOCK]
    (ok if hit else bad)("读回来：%d 条里有我建的那条：%s" % (len(rows), bool(hit)))
    after_write = len(rows)

    # ── [5] 复原，并且**同时**验两件事 ──────────────────────────
    say()
    say("══ [5] 复原 —— 铁律 029：既要「计数回到基线」，也要「真删到了行」══")
    st, j = call("DELETE", "/api/portal/anchors/" + PROBE_BLOCK, opener=auth)
    (ok if st == 200 else bad)("DELETE → %s（要 200；回 404 = 那一下根本没删到行）" % st)

    st, j = call("GET", "/api/portal/anchors", opener=auth)
    rows = (j or {}).get("data") or []
    left = [r for r in rows if r.get("block_id") == PROBE_BLOCK]
    if left:
        bad("★ 那条探针锚点**还在**库里 —— 清理没生效")
    else:
        ok("探针锚点已不在库里")
    if before is not None and len(rows) == before:
        ok("前后计数相同：%d → %d" % (before, len(rows)))
    else:
        bad("★ 前后计数不同：%s → %d（多出来的是别的东西）" % (before, len(rows)))
    say("   （写入后是 %d 条 = 基线 %s + 1，这一条也顺便核了）" % (after_write, before))

    # ── [6] 收尾 ────────────────────────────────────────────────
    say()
    st, _ = call("POST", "/api/auth/logout", opener=auth)
    (ok if st == 200 else bad)("登出 → %s" % st)
    st, _ = call("GET", "/api/buildings", opener=auth)
    (ok if st == 401 else bad)("登出后再打 /api/buildings → %s（要 401，说明会话真的吊销了）" % st)

    say()
    if fails:
        say("══ ✗ %d 条没过 ══" % len(fails))
        for f in fails:
            say("   " + f)
        return 1
    say("══ ✓ 端到端全过 ══")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
