import importlib.util
from pathlib import Path
from urllib.error import HTTPError, URLError

MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "scripts" / "healthcheck.py"
spec = importlib.util.spec_from_file_location("cdut3d_healthcheck", MODULE_PATH)
health = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(health)


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"ok": true}'


def test_fetch_json_ok(monkeypatch):
    monkeypatch.setattr(health, "urlopen", lambda *_a, **_k: _Response())
    status, payload = health.fetch_json("http://example/live")
    assert status == 200
    assert payload == {"ok": True}


def test_main_ok(monkeypatch, capsys):
    monkeypatch.setattr(health, "fetch_json", lambda *_a, **_k: (200, {"ok": True}))
    assert health.main(["--base", "http://example"]) == 0
    assert '"ok": true' in capsys.readouterr().out


def test_main_fails(monkeypatch):
    monkeypatch.setattr(health, "fetch_json", lambda *_a, **_k: (503, {"ok": False}))
    assert health.main(["--base", "http://example"]) == 1


def test_fetch_json_http_error_json(monkeypatch):
    class _Err:
        def read(self):
            return b'{"ok": false}'

        def close(self):
            return None

    def _raise2(*_args, **_kwargs):
        raise HTTPError("http://example/health", 503, "bad", {}, _Err())

    monkeypatch.setattr(health, "urlopen", _raise2)
    status, payload = health.fetch_json("http://example/health")
    assert status == 503
    assert payload == {"ok": False}


def test_fetch_json_http_error_raw(monkeypatch):
    class _Err:
        def read(self):
            return b"not-json"

        def close(self):
            return None

    def _raise(*_args, **_kwargs):
        raise HTTPError("http://example/health", 500, "bad", {}, _Err())

    monkeypatch.setattr(health, "urlopen", _raise)
    status, payload = health.fetch_json("http://example/health")
    assert status == 500
    assert payload == {"raw": "not-json"}


def test_main_network_error(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise URLError("down")

    monkeypatch.setattr(health, "fetch_json", _raise)
    assert health.main(["--base", "http://example"]) == 1
