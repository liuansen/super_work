# tests/douyin_validation/test_baseline.py
import importlib.util
from pathlib import Path
import pytest


def load_baseline():
    path = Path(__file__).resolve().parents[2] / "tools/douyin_validation/baseline.py"
    spec = importlib.util.spec_from_file_location("douyin_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_excludes_secrets_and_detects_changes(tmp_path):
    module = load_baseline()
    root = tmp_path / "project"
    src = root / "backend/app"
    src.mkdir(parents=True)
    (src / "sample.py").write_text("value = 1\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=never-copy", encoding="utf-8")
    out = tmp_path / "baseline"
    module.capture(root, out)
    assert not (out / "files/.env").exists()
    assert module.check(root, out) == []
    (src / "sample.py").write_text("value = 2\n", encoding="utf-8")
    assert module.check(root, out) == ["changed: backend/app/sample.py"]
    with pytest.raises(FileExistsError):
        module.capture(root, out)


def test_detects_added_and_removed_source(tmp_path):
    module = load_baseline()
    root = tmp_path / "project"
    src = root / "frontend/src"
    src.mkdir(parents=True)
    old = src / "old.ts"
    old.write_text("export {};", encoding="utf-8")
    out = tmp_path / "baseline"
    module.capture(root, out)
    old.unlink()
    (src / "new.ts").write_text("export {};", encoding="utf-8")
    assert module.check(root, out) == [
        "added: frontend/src/new.ts", "removed: frontend/src/old.ts"
    ]
