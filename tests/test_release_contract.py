import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "scripts" / "release.py"
spec = importlib.util.spec_from_file_location("cdut3d_release", MODULE_PATH)
release = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(release)


def test_copy_and_verify_release(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "x.pyc").write_bytes(b"x")
    out = tmp_path / "out"
    rows = release.copy_release(src, out, ["a.txt"])
    assert rows == [
        {
            "path": "a.txt",
            "bytes": 5,
            "sha256": release.sha256_file(src / "a.txt"),
        }
    ]
    manifest = {
        "schema": "cdut3d-release/1",
        "files": rows,
    }
    (out / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert release.verify_release(out) == []


def test_verify_detects_missing_and_tampered(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.txt").write_text("hello", encoding="utf-8")
    rows = [{"path": "a.txt", "bytes": 5, "sha256": release.sha256_file(out / "a.txt")}]
    (out / "release-manifest.json").write_text(json.dumps({"files": rows}), encoding="utf-8")
    assert release.verify_release(out) == []
    (out / "a.txt").write_text("changed", encoding="utf-8")
    assert any("大小不符" in x for x in release.verify_release(out))


def test_iter_files_rejects_missing_path(tmp_path):
    try:
        list(release.iter_files(tmp_path, ["missing.txt"]))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing path must fail closed")


def test_verify_requires_manifest(tmp_path):
    assert release.verify_release(tmp_path) == ["release-manifest.json 不在"]


def test_iter_files_skips_cache_and_bytecode(tmp_path):
    (tmp_path / "good.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"x")
    (tmp_path / "bad.pyc").write_bytes(b"x")
    paths = [p.name for p in release.iter_files(tmp_path)]
    assert paths == ["good.txt"]


def test_build_release_with_small_manifest(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(release, "DISPLAY_PATHS", ["a.txt"])
    monkeypatch.setattr(release, "_git_commit", lambda _root: "deadbeef")
    out = tmp_path / "out"
    manifest = release.build_release(src, out, "display")
    assert manifest["profile"] == "display"
    assert manifest["git_commit"] == "deadbeef"
    assert manifest["file_count"] == 1
    assert (out / "release-manifest.json").is_file()
    assert release.verify_release(out) == []


def test_build_release_rejects_unknown_profile(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(release, "DISPLAY_PATHS", ["a.txt"])
    try:
        release.build_release(src, tmp_path / "out", "full")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown profile must fail closed")


def test_build_release_rejects_existing_destination(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(release, "DISPLAY_PATHS", ["a.txt"])
    try:
        release.build_release(src, out, "display")
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing destination must be rejected")


def test_verify_detects_bad_json_and_extra_file(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "release-manifest.json").write_text("{bad", encoding="utf-8")
    assert any("读不动" in x for x in release.verify_release(out))
    (out / "release-manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    (out / "extra.txt").write_text("x", encoding="utf-8")
    assert any("多出" in x for x in release.verify_release(out))


def test_verify_detects_hash_mismatch_same_size(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    p = out / "a.txt"
    p.write_text("hello", encoding="utf-8")
    rows = [{"path": "a.txt", "bytes": 5, "sha256": "0" * 64}]
    (out / "release-manifest.json").write_text(json.dumps({"files": rows}), encoding="utf-8")
    assert any("SHA-256 不符" in x for x in release.verify_release(out))


def test_main_build_and_verify(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(release, "DISPLAY_PATHS", ["a.txt"])
    monkeypatch.setattr(release, "_git_commit", lambda _root: None)
    assert release.main(["build", str(out), "--root", str(src)]) == 0
    assert "发布已生成" in capsys.readouterr().out
    assert release.main(["verify", str(out)]) == 0
    assert "全部一致" in capsys.readouterr().out


def test_main_build_reports_failure(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(release, "DISPLAY_PATHS", ["missing.txt"])
    assert release.main(["build", str(tmp_path / "out"), "--root", str(src)]) == 1
    assert "发布构建失败" in capsys.readouterr().err
