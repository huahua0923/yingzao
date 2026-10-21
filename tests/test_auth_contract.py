import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "rebuild" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

spec = importlib.util.spec_from_file_location("cdut3d_auth_server", ROOT / "workbench" / "server.py")
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


def test_default_password_hash_verifies_only_given_credentials():
    assert server.auth_verify("cdut2026", "cdut2026")
    assert not server.auth_verify("cdut2026", "wrong")
    assert not server.auth_verify("other", "cdut2026")


def test_session_token_round_trip_and_tamper_rejected():
    token = server.auth_issue_token("cdut2026")
    assert server.auth_check_token(token) == "cdut2026"
    payload, signature = token.split(".", 1)
    tampered = payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    assert server.auth_check_token(tampered) is None


def test_login_redirect_target_is_local_only():
    assert server.auth_redirect_target("/info") == "/info"
    assert server.auth_redirect_target("//evil.example/") == "/"
    assert server.auth_redirect_target("https://evil.example/") == "/"


def test_login_page_and_assets_exist():
    ui = ROOT / "workbench" / "ui"
    assert (ui / "login.html").is_file()
    assert (ui / "login.css").is_file()
    assert (ui / "login.js").is_file()
    assert (ui / "assets" / "campus-hero.webp").is_file()
    assert (ui / "assets" / "logo.svg").is_file()
