# tools/douyin_validation/baseline.py
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOTS = (
    "backend/app", "backend/alembic", "frontend/src", "apis", "xhs_utils"
)
FILES = (
    "backend/alembic.ini", "frontend/package.json", "frontend/package-lock.json",
    "requirements.txt", "package.json", "package-lock.json", "main.py",
    "Dockerfile", "docker-compose.yml"
)
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".css", ".json", ".ini"}


def sources(root: Path) -> dict[str, Path]:
    root = root.resolve()
    result = {}
    for prefix in ROOTS:
        base = root / prefix
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(root)
            if any(part in {"node_modules", "__pycache__", "storage", ".venv"}
                   for part in rel.parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if not path.resolve().is_relative_to(root):
                raise ValueError("Source escaped project root")
            if path.suffix in SUFFIXES and not path.name.startswith(".env"):
                result[rel.as_posix()] = path
    for name in FILES:
        path = root / name
        if path.is_file() and not path.is_symlink():
            if not path.resolve().is_relative_to(root):
                raise ValueError("Source escaped project root")
            result[name] = path
    return result


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(root: Path, out: Path) -> None:
    selected = sources(root)
    out.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, path in sorted(selected.items()):
        target = out / "files" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[name] = digest(target)
    (out / "manifest.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def check(root: Path, out: Path) -> list[str]:
    old = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    current = {name: digest(path) for name, path in sources(root).items()}
    differences = []
    for name in sorted(old.keys() | current.keys()):
        if name not in old:
            differences.append(f"added: {name}")
        elif name not in current:
            differences.append(f"removed: {name}")
        elif old[name] != current[name]:
            differences.append(f"changed: {name}")
    return differences


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["capture", "check"])
    parser.add_argument("root", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.action == "capture":
        capture(args.root, args.out)
        print("Baseline captured; no business files changed.")
        return 0
    differences = check(args.root, args.out)
    print("\n".join(differences) if differences else "BASELINE MATCH")
    return int(bool(differences))


if __name__ == "__main__":
    raise SystemExit(main())
