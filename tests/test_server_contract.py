import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "rebuild" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

spec = importlib.util.spec_from_file_location("cdut3d_workbench_server", ROOT / "workbench" / "server.py")
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


def test_safe_join_rejects_parent_escape():
    assert server._safe_join(str(ROOT / "workbench" / "ui"), "../server.py") is None
    assert server._safe_join(str(ROOT / "workbench" / "ui"), "..\\server.py") is None


def test_safe_join_accepts_inside_file():
    joined = server._safe_join(str(ROOT / "workbench" / "ui"), "portal.html")
    assert joined is not None
    assert Path(joined).is_file()


def test_allowed_origin_accepts_same_host():
    assert server._allowed_origin("https://cdut3d.example.edu.cn", "cdut3d.example.edu.cn")
    assert server._allowed_origin("http://127.0.0.1:8150", "127.0.0.1:8150")


def test_allowed_origin_rejects_cross_site():
    assert not server._allowed_origin("https://evil.example", "cdut3d.example.edu.cn")
    assert not server._allowed_origin("null", "cdut3d.example.edu.cn")


def test_health_payload_shape():
    payload = server.health_payload()
    assert payload["service"] == "cdut3d"
    assert payload["version"] == server.APP_VERSION
    assert set(payload["checks"]) == {"ui", "workbench", "packs_index", "gate_output"}
