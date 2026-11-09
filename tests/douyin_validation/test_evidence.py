# tests/douyin_validation/test_evidence.py
import hashlib
import importlib.util
from pathlib import Path


def load_evidence():
    path = Path(__file__).resolve().parents[2] / "tools/douyin_validation/evidence.py"
    spec = importlib.util.spec_from_file_location("douyin_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed_fixture(module, base):
    # Fictitious fixture for validator tests, never a real platform report.
    report = module.new_report()
    directory = base / "evidence"
    directory.mkdir()
    artifact = directory / "unit-fixture.txt"
    artifact.write_text("FICTITIOUS UNIT TEST ONLY\n", encoding="utf-8")
    value = hashlib.sha256(artifact.read_bytes()).hexdigest()
    report["source_revision"] = "a" * 40
    report["reviewed_by"] = "unit-test-reviewer"
    report["accounts_tested"] = 2
    report["interaction_metrics"] = ["like_count"]
    for name in module.REQUIRED:
        report["checks"][name] = {
            "status": "passed", "observed_at": "2026-11-09T12:00:00+08:00",
            "authorization_ref": "unit-test-only", "summary": "Fixture only",
            "evidence": [{"path": "evidence/unit-fixture.txt", "sha256": value}]
        }
    return report, artifact


def test_new_report_is_blocked(tmp_path):
    module = load_evidence()
    problems = module.issues(module.new_report(), tmp_path)
    assert any("source_revision" in text for text in problems)
    assert any("publish" in text for text in problems)


def test_fixture_passes_then_tampering_fails(tmp_path):
    module = load_evidence()
    report, artifact = completed_fixture(module, tmp_path)
    assert module.issues(report, tmp_path) == []
    artifact.write_text("changed", encoding="utf-8")
    assert any("sha256" in text for text in module.issues(report, tmp_path))


def test_escaped_path_and_no_real_metric_are_blocked(tmp_path):
    module = load_evidence()
    report, artifact = completed_fixture(module, tmp_path)
    report["checks"]["publish"]["evidence"][0]["path"] = "../outside.txt"
    report["interaction_metrics"] = []
    problems = module.issues(report, tmp_path)
    assert any("publish" in text for text in problems)
    assert any("interaction_metrics" in text for text in problems)


def test_naive_time_and_one_account_are_blocked(tmp_path):
    module = load_evidence()
    report, artifact = completed_fixture(module, tmp_path)
    report["accounts_tested"] = 1
    report["checks"]["publish"]["observed_at"] = "2026-11-09T12:00:00"
    problems = module.issues(report, tmp_path)
    assert any("accounts_tested" in text for text in problems)
    assert any("observed_at" in text for text in problems)
