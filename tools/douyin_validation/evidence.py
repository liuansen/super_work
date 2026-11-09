# tools/douyin_validation/evidence.py
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

REQUIRED = (
    "license", "runtime", "reference_link", "accounts", "publish",
    "reconcile", "schedule", "metrics", "limits"
)


def new_report() -> dict:
    return {
        "schema_version": 1,
        "source_url": "https://github.com/cv-cat/DouYin_Spider",
        "source_revision": "", "reviewed_by": "", "accounts_tested": 0,
        "interaction_metrics": [],
        "checks": {
            name: {"status": "unverified", "observed_at": "",
                   "authorization_ref": "", "summary": "未验证",
                   "evidence": []}
            for name in REQUIRED
        }
    }


def issues(report: dict, base: Path) -> list[str]:
    errors = []
    if report.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if report.get("source_url") != "https://github.com/cv-cat/DouYin_Spider":
        errors.append("source_url mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", str(report.get("source_revision", ""))):
        errors.append("source_revision requires verified 40-character commit SHA")
    if not str(report.get("reviewed_by", "")).strip():
        errors.append("reviewed_by required")
    count = report.get("accounts_tested")
    if type(count) is not int or count < 2:
        errors.append("accounts_tested must be at least 2")
    metrics = report.get("interaction_metrics")
    if (not isinstance(metrics, list) or not metrics
            or not all(isinstance(x, str) and x.strip() for x in metrics)):
        errors.append("interaction_metrics requires at least one observed real metric")
    evidence_root = (base / "evidence").resolve()
    checks = report.get("checks", {})
    if not isinstance(checks, dict):
        return errors + ["checks must be an object"]
    for name in REQUIRED:
        item = checks.get(name, {})
        if not isinstance(item, dict) or item.get("status") != "passed":
            errors.append(f"{name}: not passed")
            continue
        if not str(item.get("summary", "")).strip():
            errors.append(f"{name}: summary required")
        if not str(item.get("authorization_ref", "")).strip():
            errors.append(f"{name}: authorization_ref required")
        try:
            stamp = datetime.fromisoformat(item.get("observed_at", ""))
            if stamp.tzinfo is None:
                raise ValueError("Timezone required")
        except (TypeError, ValueError):
            errors.append(f"{name}: observed_at requires ISO time with offset")
        artifacts = item.get("evidence")
        if not isinstance(artifacts, list) or not artifacts:
            errors.append(f"{name}: evidence required")
            continue
        for artifact in artifacts:
            try:
                if not isinstance(artifact, dict):
                    raise ValueError("Invalid artifact")
                rel = Path(artifact["path"])
                target = (base / rel).resolve()
                if (rel.is_absolute() or ".." in rel.parts
                        or not target.is_relative_to(evidence_root)
                        or target.suffix not in {".md", ".json", ".txt"}
                        or not target.is_file()):
                    raise ValueError("Unsafe evidence path")
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual != artifact.get("sha256"):
                    errors.append(f"{name}: evidence sha256 mismatch")
            except (KeyError, TypeError, ValueError, OSError):
                errors.append(f"{name}: unsafe or missing evidence path")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "check"])
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.action == "init":
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(new_report(), stream, ensure_ascii=False, indent=2)
        print("UNVERIFIED report created; this is not a passed capability gate.")
        return 0
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("Report must be an object")
        errors = issues(report, args.report.parent)
    except (OSError, ValueError, TypeError) as exc:
        print(f"BLOCKED: invalid report ({type(exc).__name__})")
        return 2
    if errors:
        print("BLOCKED\n" + "\n".join(errors))
        return 2
    print("EVIDENCE STRUCTURE PASS; manual verification and user decision still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
