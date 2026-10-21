# -*- coding: utf-8 -*-
"""Probe live and dependency-aware health endpoints after deployment."""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch_json(url: str, timeout: float = 5.0) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8150")
    ap.add_argument("--timeout", type=float, default=5.0)
    args = ap.parse_args(argv)
    base = args.base.rstrip("/")
    results = {}
    ok = True
    for name in ("live", "health"):
        try:
            status, payload = fetch_json(f"{base}/{name}", args.timeout)
        except (URLError, TimeoutError, OSError) as exc:
            status, payload = 0, {"error": str(exc)}
        results[name] = {"status": status, "payload": payload}
        ok = ok and status == 200 and payload.get("ok") is True
    print(json.dumps({"ok": ok, "results": results}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
