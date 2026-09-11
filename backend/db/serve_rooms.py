# -*- coding: utf-8 -*-
"""理化楼房间数据后端。

静态托管 building.html（整栋立体模型查看器，消费标准 floor JSON），并提供
    GET /api/rooms?floor=N
从 PostgreSQL (lihua_twin.rooms) 读房间数据。

静态文件：building.html 会 fetch ../data/spec.json 与 ../data/floors/floor*.json，
因此 /data/ 路径下文件由本服务托管（JSON 已加 CORS 头）。

运行：python serve_rooms.py   端口取 .env 的 GYM3D_LEGACY_ROOMS_PORT（见 .env.example）
"""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(DIR, "..")))          # backend/（paths.py 在这）
sys.path.insert(0, os.path.normpath(os.path.join(DIR, "..", "..")))    # 仓库根（backend.api.settings 靠它）
from backend.api.settings import get_settings  # noqa: E402
from paths import DATA as _DATA, FRONTEND as _FRONTEND, ensure_sys_path  # noqa: E402

ensure_sys_path("nav")                 # 几何路径求解器 build_path.py 在 backend/nav
sys.path.insert(0, DIR)
from db_config import db_params  # noqa: E402

FRONTEND = str(_FRONTEND)
DATA = str(_DATA)
# 几何路径求解器（A* 占用网格 + 跨层楼梯井）：backend/nav/build_path.py，供 /api/path 使用
from build_path import compute_path  # noqa: E402

_SETTINGS = get_settings()
# 默认仅监听本机；需要局域网访问时显式设 GYM3D_HOST=0.0.0.0（并确保已设强口令）。
HOST = _SETTINGS.host
# 端口只从配置读：代码里不留数字字面量，.env 是唯一出处（见 .env.example）
PORT = _SETTINGS.legacy_rooms_port
if PORT is None:
    raise SystemExit(
        "未设置 GYM3D_LEGACY_ROOMS_PORT，房间服务拒绝启动。该端口只存在于 .env，"
        "Phase 6 下线本服务后即可删除。"
    )

HTML_FILE = "building.html"

ROOM_COLS = "id, building, floor, number, name, area_label, area_m2, purpose, dept, centroid_x, centroid_y, boundary"


def query_rooms(floor, building=None):
    conn = psycopg.connect(**db_params())
    try:
        where, params = [], []
        if floor is not None:
            where.append("floor=%s"); params.append(floor)
        if building:
            where.append("building=%s"); params.append(building)
        sql = f"SELECT {ROOM_COLS} FROM rooms"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY building, floor, number"
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        b = r[11]
        if isinstance(b, str):          # 兜底：若 JSONB 被当字符串返回
            b = json.loads(b)
        out.append({
            "id": r[0], "building": r[1], "floor": r[2], "number": r[3], "name": r[4],
            "area_label": r[5], "area_m2": r[6], "purpose": r[7], "dept": r[8],
            "centroid_x": r[9], "centroid_y": r[10], "boundary": b,
        })
    return out


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        body = open(os.path.join(FRONTEND, HTML_FILE), "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        """托管 /data/ 下静态文件（floor JSON / spec.json），防目录穿越。"""
        rel = path.lstrip("/")
        if not rel.startswith("data/"):
            return False
        full = os.path.normpath(os.path.join(DATA, rel[len("data/"):]))
        if os.path.commonpath([DATA, full]) != DATA or not os.path.isfile(full):
            return False
        body = open(full, "rb").read()
        ctype = "application/json; charset=utf-8" if full.endswith(".json") \
            else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/rooms":
                qs = urllib.parse.parse_qs(parsed.query)
                floor = qs.get("floor", [None])[0]
                building = qs.get("building", [None])[0]
                if floor is not None:
                    try:
                        floor = int(floor)
                    except ValueError:
                        self._json({"success": False, "data": None,
                                    "error": "floor 必须是整数"}, 400)
                        return
                data = query_rooms(floor, building)
                self._json({"success": True, "data": data, "error": None,
                            "meta": {"total": len(data), "floor": floor, "building": building}})
            elif parsed.path == "/api/path":
                qs = urllib.parse.parse_qs(parsed.query)
                src = (qs.get("from") or [None])[0]
                dst = (qs.get("to") or [None])[0]
                if not src or not dst:
                    self._json({"success": False, "data": None,
                                "error": "缺少 from/to 参数"}, 400)
                    return
                try:
                    self._json({"success": True, "data": compute_path(src, dst), "error": None})
                except ValueError as e:
                    self._json({"success": False, "data": None, "error": str(e)}, 400)
            elif parsed.path in ("/", "/index.html", "/building.html", "/floor1_3d.html"):
                self._html()
            elif parsed.path.startswith("/data/"):
                if not self._static(parsed.path):
                    self._json({"success": False, "data": None, "error": "not found"}, 404)
            else:
                self._json({"success": False, "data": None, "error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            print(f"[serve_rooms] {type(e).__name__}: {e}", file=sys.stderr)
            self._json({"success": False, "data": None, "error": "服务器内部错误"}, 500)

    def log_message(self, fmt, *args):
        pass  # 静默访问日志


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"理化楼房间后端已启动 -> http://{HOST}:{PORT}/")
    srv.serve_forever()
