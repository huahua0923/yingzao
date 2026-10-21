# -*- coding: utf-8 -*-
r"""本地倾斜摄影定位台：只读加载已有 3D Tiles，并把人工确定的楼栋位置写回本地 JSON。

启动：
    python tools/reality_locator_server.py

默认读取：
    3D Tiles: D:\项目\gym3d\gym3d\_scratch\_fly2024_tiles
    Cesium:   F:\理工数据\理工模型-3Dtile\CesiumViewer\Cesium

可用环境变量覆盖：
    CDUT_REALITY_TILES / CDUT_CESIUM_HOME / CDUT_REALITY_LOCATOR_PORT
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pyproj import Transformer


REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "rebuild" / "构件库" / "楼栋.json"
PAGE = REPO / "demo" / "reality-locator.html"
LOCATIONS = REPO / "过程" / "_scratch" / "reality_locations.json"
DEFAULT_TILES = Path(r"D:\项目\gym3d\gym3d\_scratch\_fly2024_tiles")
DEFAULT_CESIUM = Path(r"F:\理工数据\理工模型-3Dtile\CesiumViewer\Cesium")

TILES_ROOT = Path(os.environ.get("CDUT_REALITY_TILES", DEFAULT_TILES)).resolve()
CESIUM_ROOT = Path(os.environ.get("CDUT_CESIUM_HOME", DEFAULT_CESIUM)).resolve()
TO_4544 = Transformer.from_crs("EPSG:4326", "EPSG:4544", always_xy=True)


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _safe_file(root: Path, relative: str) -> Path | None:
    candidate = (root / unquote(relative)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "cdut3d-reality-locator/1"

    def log_message(self, fmt, *args):
        print("[locator] " + (fmt % args))

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value):
        self._send(status, _json_bytes(value), "application/json; charset=utf-8")

    def _file(self, path: Path):
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() in (".glb", ".b3dm", ".pnts", ".i3dm"):
            content_type = "application/octet-stream"
        try:
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            with path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except BrokenPipeError:
            return

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(PAGE)
        if path == "/api/config":
            return self._json(200, {
                "tileset_url": "/tiles/tileset_shallow.json",
                "coord_epsg": 4544,
                "tiles_root": str(TILES_ROOT),
            })
        if path == "/api/buildings":
            data = json.loads(PROFILE.read_text(encoding="utf-8"))
            rows = [
                {"id": key, "title": value.get("title") or key}
                for key, value in data.items()
                if isinstance(value, dict) and "output" in value
            ]
            rows.sort(key=lambda row: row["id"])
            return self._json(200, rows)
        if path == "/api/locations":
            if not LOCATIONS.exists():
                return self._json(200, {})
            return self._json(200, json.loads(LOCATIONS.read_text(encoding="utf-8")))
        if path.startswith("/tiles/"):
            target = _safe_file(TILES_ROOT, path[len("/tiles/"):])
            return self._file(target) if target else self._json(404, {"error": "tile not found"})
        if path.startswith("/cesium/"):
            target = _safe_file(CESIUM_ROOT, path[len("/cesium/"):])
            return self._file(target) if target else self._json(404, {"error": "cesium asset not found"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/location":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1024 * 1024:
            return self._json(413, {"error": "invalid body size"})
        try:
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            building_id = str(raw.get("building_id", "")).strip()
            if not building_id or not all(ch.isalnum() or ch == "_" for ch in building_id):
                raise ValueError("building_id 只认字母、数字、下划线")
            lon = float(raw["lon"])
            lat = float(raw["lat"])
            height = float(raw["height"])
            if not (-180 <= lon <= 180 and -90 <= lat <= 90 and -1000 <= height <= 10000):
                raise ValueError("经纬度或高程超范围")
            x4544, y4544 = TO_4544.transform(lon, lat)
            record = dict(raw)
            record.update({
                "building_id": building_id,
                "lon": lon,
                "lat": lat,
                "height": height,
                "x_4544": x4544,
                "y_4544": y4544,
            })
            values = {}
            if LOCATIONS.exists():
                values = json.loads(LOCATIONS.read_text(encoding="utf-8"))
            values[building_id] = record
            LOCATIONS.parent.mkdir(parents=True, exist_ok=True)
            temp = LOCATIONS.with_suffix(".tmp")
            temp.write_bytes(_json_bytes(values))
            temp.replace(LOCATIONS)
            return self._json(200, record)
        except Exception as error:
            return self._json(400, {"error": str(error)})


def main() -> int:
    parser = argparse.ArgumentParser(description="本地倾斜摄影楼栋定位台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CDUT_REALITY_LOCATOR_PORT", "8151")))
    args = parser.parse_args()
    if not PAGE.is_file():
        raise SystemExit(f"页面不存在：{PAGE}")
    if not (TILES_ROOT / "tileset_shallow.json").is_file():
        raise SystemExit(f"瓦片清单不存在：{TILES_ROOT / 'tileset_shallow.json'}")
    if not (CESIUM_ROOT / "Cesium.js").is_file():
        raise SystemExit(f"Cesium 不存在：{CESIUM_ROOT / 'Cesium.js'}")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"实景定位台 http://{args.host}:{args.port}/")
    print(f"3D Tiles {TILES_ROOT}")
    print(f"Cesium   {CESIUM_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
