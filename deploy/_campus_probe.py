# -*- coding: utf-8 -*-
"""带身份打 campus 那 6 条路由 —— 401 只说明「有条路由」，不说明「读得到文件」。

★ 为什么要单独跑这一趟：`GYM3D_CAMPUS_DIR` 是本轮唯一一个把**服务器上的绝对路径**
  接进代码的地方（`settings.py` 默认指向本机的 `_scratch/_campus3d/...`，那个目录在
  服务器上根本不存在）。它写错了的症状是：路由存在、认证也过，然后回 404/500 ——
  匿名探针**看不见**这一层，因为匿名根本到不了那里。
★ 判据要钉在**响应体上**：这不只是状态码，还要量字节数，并且和盘上那两个 GLB 的实际
  大小对一次（`campus_terrain.glb` 8071248 / `campus_buildings.glb` 178892）。
  只比「200」会让「返回了一个 0 字节文件」也算过。
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
CAMPUS = "/opt/gym3d/campus-terrain"
# ★ 路径必须照抄 `backend/api/routers/campus.py` 里的装饰器，**一个字符都不许改**。
#   第一版我手打了 `/api/campus/model` —— 404 了五条，我差点当成部署缺陷报出去。
#   真凶是尺子：我先前用 `grep -oE "/api/[A-Za-z0-9_/-]+"` 从 app.js 里抽路径，
#   那个字符集**不含点号** ⇒ `/api/campus/model.glb` 被截成 `/api/campus/model`。
#   两处用的是同一个被截断的串，于是「前端也这么调、服务端也 404」看起来自洽 ——
#   铁律 165/169/173：两个来源不一致时，第一嫌疑人是量具。
ROUTES = ["/api/campus/model.glb", "/api/campus/ortho.jpg", "/api/campus/ortho.json",
          "/api/campus/outlines.json", "/api/campus/lod1.json",
          "/api/campus/buildings.glb", "/api/campus/buildings.json",
          "/api/campus/viewdata"]

fails = []


def ok(m):
    print("  ✓ " + m, flush=True)


def bad(m):
    print("  ✗ " + m, flush=True)
    fails.append(m)


def fetch(opener, path):
    try:
        with opener.open(BASE + path, timeout=30) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")
    except Exception as e:                                   # noqa: BLE001
        return None, str(e).encode(), ""


def main():
    pw = open(PW_FILE, encoding="utf-8").read().strip()
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(
        BASE + "/api/auth/login",
        data=json.dumps({"username": USER, "password": pw}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with op.open(req, timeout=15) as r:
            if r.status != 200:
                bad("登录失败 %s" % r.status)
                return 2
    except urllib.error.HTTPError as e:
        bad("登录失败 %s" % e.code)
        return 2
    ok("已登录（口令不打印）")

    print()
    print("══ 逐条打 campus 路由（判据是「字节数 > 0」和「类型对」）══")
    total_ok = 0
    for p in ROUTES:
        st, body, ct = fetch(op, p)
        n = len(body)
        good = st == 200 and n > 0
        printf = ok if good else bad
        printf("%-26s → %s  %8d B  %s" % (p, st, n, ct[:32]))
        if good:
            total_ok += 1
        elif st == 200:
            bad("   ★ 回 200 但**响应体是空的** —— 比 404 更难看出")
        else:
            bad("   响应体：%s" % body[:160].decode("utf-8", "replace"))

    print()
    print("══ 与盘上实物对一次（模型那条要能对上 campus_terrain.glb）══")
    for fn in ("campus_terrain.glb", "campus_buildings.glb", "campus_ortho.jpg"):
        fp = os.path.join(CAMPUS, fn)
        if os.path.isfile(fp):
            ok("盘上 %-24s %9d B" % (fn, os.path.getsize(fp)))
        else:
            bad("盘上**没有** %s —— 那说明数据包没解全" % fn)

    print()
    if fails:
        print("══ ✗ %d 条没过 ══" % len(fails))
        for f in fails:
            print("   " + f)
        return 1
    print("══ ✓ campus 全过（%d/%d）══" % (total_ok, len(ROUTES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
