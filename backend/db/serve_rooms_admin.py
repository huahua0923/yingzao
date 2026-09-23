# -*- coding: utf-8 -*-
"""房间台账后台 —— 网页管理每间房（本机服务，**会写库**）。

与 `serve_rooms.py`（8123，只读，给查看器用）是两件事，刻意分成两个进程：
管理页要写数据库，给它一个单独的口子和一个单独的端口，出问题不会连带把查看器弄挂。

    GET  /                             台账管理页 frontend/rooms-admin.html
    GET  /api/registry/stats           概览 + 逐楼房间数/层号列表
    GET  /api/registry/rooms           列表（楼/层/关键字/来源/含已删除/分页）
    GET  /api/registry/room?key=       单间 + 变更历史
    GET  /api/registry/export          导出 CSV（带 BOM，Excel 直接打开不乱码）
    POST /api/registry/edit            改一个字段
    POST /api/registry/add             新建一间房
    POST /api/registry/delete|restore  软删除 / 恢复
    POST /api/registry/revert          撤销某字段的人工值
    POST /api/registry/reimport        重抽：只重建机器层，人工层一个字不动

**安全**：默认只听本机。若把 GYM3D_HOST 设成 0.0.0.0（开放到局域网），则**必须**
同时设 GYM3D_ADMIN_TOKEN，否则拒绝启动 —— 一个能改数据库的接口不能匿名挂在网上。
设了 token 后，写操作要带 `X-Admin-Token` 头（或 ?token=，留给命令行用）。

运行：python backend/db/serve_rooms_admin.py   端口取 .env 的 GYM3D_ROOMS_ADMIN_PORT
"""
import csv
import io
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

from backend.api.settings import get_settings  # noqa: E402
from backend.db import rooms_registry as R  # noqa: E402
from paths import FRONTEND  # noqa: E402

_SETTINGS = get_settings()
# ★ 监听地址用 rooms_admin_host 而**不是** settings.host：查看器要挂到局域网上
#   （.env 里 GYM3D_HOST=0.0.0.0），可管理页能改数据库，不该跟着一起对外。
HOST = _SETTINGS.rooms_admin_host
PORT = _SETTINGS.rooms_admin_port
TOKEN = _SETTINGS.admin_token
HTML_FILE = "rooms-admin.html"

if PORT is None:
    raise SystemExit(
        "未设置 GYM3D_ROOMS_ADMIN_PORT，台账后台拒绝启动。端口只存在于 .env（见 .env.example）。"
    )
_LOOPBACK = HOST in ("127.0.0.1", "localhost", "::1")
if not _LOOPBACK and not TOKEN:
    raise SystemExit(
        "GYM3D_ROOMS_ADMIN_HOST=%s 会把台账后台暴露到本机之外，而 GYM3D_ADMIN_TOKEN 是空的 "
        "—— 拒绝启动。要么用 127.0.0.1，要么设一个 token。" % HOST
    )

CSV_COLS = ["building", "floor", "number", "name", "area_label", "area_m2", "purpose", "dept",
            "origin", "in_cad", "deleted", "manual_fields", "updated_at"]


def _conn():
    conn = R.connect()
    R.ensure_schema(conn)
    return conn


class Handler(BaseHTTPRequestHandler):
    server_version = "rooms-admin"

    # ---------------- 基础输出 ----------------

    def _send(self, body, ctype, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _ok(self, data):
        self._json({"success": True, "data": data, "error": None})

    def _err(self, msg, status=400):
        self._json({"success": False, "data": None, "error": str(msg)}, status)

    def _html(self):
        path = os.path.join(str(FRONTEND), HTML_FILE)
        if not os.path.isfile(path):
            self._err("管理页不存在：%s" % path, 500)
            return
        self._send(open(path, "rb").read(), "text/html; charset=utf-8")

    # ---------------- 鉴权 ----------------

    def _authed(self):
        if not TOKEN:
            return True                      # 只听本机时不需要 token
        got = self.headers.get("X-Admin-Token") or \
            (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
             .get("token", [None])[0])
        return got == TOKEN

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("请求体不是合法 JSON：%s" % e)

    # ---------------- 路由 ----------------

    def do_GET(self):  # noqa: N802
        p = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(p.query)
        one = lambda k, d=None: (qs.get(k) or [d])[0]  # noqa: E731
        try:
            if p.path in ("/", "/index.html"):
                self._html()
                return
            if not p.path.startswith("/api/registry/"):
                self._err("not found", 404)
                return
            conn = _conn()
            try:
                if p.path == "/api/registry/stats":
                    self._ok(R.stats(conn))
                elif p.path == "/api/registry/rooms":
                    self._ok(R.list_rooms(
                        conn, building=one("building"), floor=one("floor"), q=one("q"),
                        origin=one("origin"), include_deleted=one("include_deleted") == "1",
                        limit=int(one("limit", 200) or 200), offset=int(one("offset", 0) or 0)))
                elif p.path == "/api/registry/room":
                    key = one("key")
                    if not key:
                        self._err("缺少 key 参数")
                        return
                    room = R.get_room(conn, key)
                    if room is None:
                        self._err("台账里没有这间房：%s" % key, 404)
                        return
                    self._ok({"room": room, "history": R.history(conn, key)})
                elif p.path == "/api/registry/export":
                    self._export(conn, one("building"), one("format", "csv"))
                else:
                    self._err("not found", 404)
            finally:
                conn.close()
        except ValueError as e:
            self._err(e)
        except Exception as e:  # noqa: BLE001
            print("[rooms-admin] %s: %s" % (type(e).__name__, e), file=sys.stderr)
            self._err("服务器内部错误：%s" % e, 500)

    def _export(self, conn, building, fmt):
        rows = R.export_rows(conn, building)
        if fmt == "json":
            self._send(json.dumps({"success": True, "data": rows, "error": None},
                                  ensure_ascii=False, indent=1).encode("utf-8"),
                       "application/json; charset=utf-8", 200,
                       {"Content-Disposition": 'attachment; filename="rooms.json"'})
            return
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([R.CN.get(c, c) for c in CSV_COLS])
        for r in rows:
            w.writerow([r[c] for c in CSV_COLS])
        # BOM：没有它 Excel 会把中文读成乱码（Windows 上是默认行为）。
        # 用 chr(0xFEFF) 而不是把 BOM 抄进源码：字面量会被编辑器/工具链吃掉，转义写法
        # 又多一层"这层转义到底是谁解的"的歧义（我就把它写成了字面的反斜杠+ufeff，
        # 文件里看着完全正常）。chr() 没有这两种可能。
        body = (chr(0xFEFF) + buf.getvalue()).encode("utf-8")
        name = "rooms-%s.csv" % (building or "all")
        self._send(body, "text/csv; charset=utf-8", 200,
                   {"Content-Disposition": 'attachment; filename="%s"' % name})

    def do_POST(self):  # noqa: N802
        p = urllib.parse.urlparse(self.path)
        if not p.path.startswith("/api/registry/"):
            self._err("not found", 404)
            return
        if not self._authed():
            self._err("缺少或错误的 X-Admin-Token", 401)
            return
        try:
            b = self._body()
        except ValueError as e:
            self._err(e)
            return
        author = (b.get("author") or "").strip() or "web"
        note = b.get("note") or None
        conn = _conn()
        try:
            if p.path == "/api/registry/edit":
                self._ok(R.set_field(conn, b.get("key"), b.get("field"), b.get("value"),
                                     author, note))
            elif p.path == "/api/registry/revert":
                self._ok(R.revert_field(conn, b.get("key"), b.get("field"), author, note))
            elif p.path == "/api/registry/add":
                self._ok(R.add_room(conn, b.get("building"), b.get("floor"), b.get("number"),
                                    b.get("fields") or {}, author, note))
            elif p.path == "/api/registry/delete":
                self._ok(R.set_deleted(conn, b.get("key"), True, author, note))
            elif p.path == "/api/registry/restore":
                self._ok(R.set_deleted(conn, b.get("key"), False, author, note))
            elif p.path == "/api/registry/reimport":
                rep = R.import_cad(conn)
                self._ok({"imported": rep["imported"], "dup_groups": rep["dup_groups"],
                          "manual": R.merge_report(conn), "stats": R.stats(conn)})
            else:
                self._err("not found", 404)
        except (ValueError, KeyError) as e:
            self._err(e)
        except Exception as e:  # noqa: BLE001
            print("[rooms-admin] %s: %s" % (type(e).__name__, e), file=sys.stderr)
            self._err("服务器内部错误：%s" % e, 500)
        finally:
            conn.close()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print("房间台账后台已启动 -> http://%s:%d/" % (HOST, PORT))
    if not _LOOPBACK:
        print("  ⚠ 已绑定到 %s（本机之外可访问），token 校验已开启" % HOST)
    srv.serve_forever()
