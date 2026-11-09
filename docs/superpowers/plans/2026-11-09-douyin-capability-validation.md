# 抖音接入能力验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改业务代码、不触发未授权平台操作的前提下，确认DouYin_Spider及获授权发布／指标接入能否支撑已批准的完整闭环，形成可审查的继续／停止结论。

**Architecture:** 本工作包只新增离线基线、证据检查工具及验证记录，工具不访问网络、不导入上游、不读取凭证。真实能力调查与操作证据独立收集，门槛程序只检查记录和文件完整性，最终仍需人工核验并由用户批准集成结论。

**Tech Stack:** Python标准库、pytest、Markdown与JSON；不增加生产依赖，不接入应用启动或数据库。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-11-09-douyin-operations-design.md`。
- 总体路线：`docs/superpowers/plans/2026-11-09-douyin-operations-implementation.md`。
- 当前不是Git仓库，不初始化、不提交、不使用worktree；以本地基线和 `git diff --no-index` 审查。
- 仅执行工作包A；通过前不得修改应用注册、业务代码、数据库、依赖锁文件或已有平台行为。
- 不为pytest导出 `DATABASE_URL`；本工作包测试不导入backend、不连接数据库。
- “真实平台发布需要用户对目标账号、具体成片和发布时间的明确授权。确认本需求文档不等于授权执行真实发布。”
- “发布失败或无法回收真实指标时，不擅自降级为人工发布、模拟数据或仅展示页面。”
- 下载的资料／归档放进各自新建空目录；工具脚本保持在工程 `tools/douyin_validation/`，不得在下载目录运行解释器或安装工具。
- 用Python处理上游资料时使用 `python -I`；先检查文件再执行任何经批准的上游代码。不得运行未知安装脚本、覆盖同名模块或把下载目录加进sys.path。
- 本工作包测试和记录是证据管理，不构成平台能力实现。门槛程序通过也不能代替真实平台验证。

---

## 文件与依赖顺序

| 新建文件 | 职责 |
| --- | --- |
| `tools/douyin_validation/baseline.py` | 建立／检查源码基线，不写业务文件 |
| `tests/douyin_validation/test_baseline.py` | 基线的离线行为测试 |
| `tools/douyin_validation/evidence.py` | 初始化与验证能力报告及证据文件哈希 |
| `tests/douyin_validation/test_evidence.py` | 报告门槛、路径和证据篡改测试 |
| `docs/superpowers/verification/douyin/source-review.md` | 上游来源、版本、许可、依赖与安全审查记录 |
| `docs/superpowers/verification/douyin/capability-report.json` | 能力门槛状态；初始全部unverified |
| `docs/superpowers/verification/douyin/evidence/` | 脱敏来源及能力证据，每项独立文件 |
| `docs/superpowers/verification/douyin/contracts.md` | 验证后冻结的外部行为与适配协议 |
| `docs/superpowers/verification/douyin/decision.md` | 明确的继续／停止结论和限制 |
| `.local/douyin-validation/baseline/` | 受保护源码副本与manifest，不上传 |

所有下述命令均在 `E:/code/super_work` 根目录运行。新建文件如已存在，先Read并比较，不能覆盖别人的实现或证据。

任务依赖：Task 1 → Task 2 → Task 3 → Task 4 → Task 5。它们组成同一能力门槛工作包，不拆成独立外部服务。

## Task 1：可复查的源码基线

**Files:**
- Create: `tools/douyin_validation/baseline.py`
- Test: `tests/douyin_validation/test_baseline.py`

**Interfaces:**
- Consumes: 工程根路径与基线输出目录，无数据库或配置读取。
- Produces: `capture(root: Path, out: Path) -> None`、`check(root: Path, out: Path) -> list[str]`。
- CLI: `baseline.py capture ROOT OUT` / `baseline.py check ROOT OUT`；capture拒绝覆盖，check有变动返回1。

- [ ] **Step 1：先创建离线失败测试。**

```python
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
```

- [ ] **Step 2：运行失败测试。**

```bash
python -m pytest tests/douyin_validation/test_baseline.py -v
```

预期：文件缺失导致失败；若导入环境错误而非缺少目标文件，先修复测试命令，不跳过RED步骤。

- [ ] **Step 3：新增完整基线工具。**

```python
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
```

基线只覆盖上述明确列表，不声称备份整个项目。它不包含数据库、配置秘密、上传文件、上游下载物和测试源码；生产实施前还需要单独备份业务库并记录现有测试。若工程源码本身已有内嵌秘密，仅本地保存并审查，不向用户或第三方发送副本。

- [ ] **Step 4：验证工具并捕获一次基线。**

```bash
python -m pytest tests/douyin_validation/test_baseline.py -v
```

预期：2 passed。

```bash
python -I tools/douyin_validation/baseline.py capture . .local/douyin-validation/baseline
```

预期：`Baseline captured; no business files changed.` 已有目录则停止，复用原manifest检查，不删除重建。

```bash
python -I tools/douyin_validation/baseline.py check . .local/douyin-validation/baseline
```

预期：`BASELINE MATCH`，退出0。

- [ ] **Step 5：审查交付。** 确认只新增工具／测试／本地基线，不改业务源码。不执行git add或commit。

## Task 2：诚实的能力报告门槛

**Files:**
- Create: `tools/douyin_validation/evidence.py`
- Test: `tests/douyin_validation/test_evidence.py`
- Generate: `docs/superpowers/verification/douyin/capability-report.json`

**Interfaces:**
- Consumes: JSON报告及同目录 `evidence/` 中的脱敏UTF-8文本证据。
- Produces: `new_report() -> dict`、`issues(report: dict, base: Path) -> list[str]`。
- CLI: `evidence.py init REPORT` / `evidence.py check REPORT`；init拒绝覆盖；check通过返回0，不完整返回2。
- `passed` 必须是真实观察；无权限、无法联网、不支持和未完成都不能写passed。

- [ ] **Step 1：先创建失败测试，测试中的虚构证据只留在tmp_path。**

```python
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
```

- [ ] **Step 2：运行RED。**

```bash
python -m pytest tests/douyin_validation/test_evidence.py -v
```

预期：缺少工具文件导致失败。

- [ ] **Step 3：新增完整报告工具。**

```python
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
```

- [ ] **Step 4：运行GREEN并初始化诚实报告。**

```bash
python -m pytest tests/douyin_validation/test_evidence.py -v
```

预期：4 passed。

```bash
python -I tools/douyin_validation/evidence.py init docs/superpowers/verification/douyin/capability-report.json
```

预期：创建全部unverified的报告，退出0，不进行网络访问。

```bash
python -I tools/douyin_validation/evidence.py check docs/superpowers/verification/douyin/capability-report.json
```

预期：`BLOCKED`，退出2，列出缺失项；这是正确的未验证状态，不通过改写报告伪造成功。

- [ ] **Step 5：审查工具边界。** 确认工具没有外部请求、backend导入、凭证读取或数据库副作用。记录本任务完成，但能力门槛仍未通过。

## Task 3：来源、许可与安全审查

**Files:**
- Create: `docs/superpowers/verification/douyin/source-review.md`
- Create as evidence: `docs/superpowers/verification/douyin/evidence/source-license.md`
- Update: `docs/superpowers/verification/douyin/capability-report.json`

**Interfaces:**
- Consumes: 用户提供的上游副本或能够取得的固定提交资料；不是可执行依赖。
- Produces: `source_revision`、license/runtime/limits的有依据结论，以及获准进入真实能力验证的决定。

- [ ] **Step 1：检查上游可访问性。** 优先只读获取README、LICENSE、依赖清单和文件目录。此前网络访问失败，不无限重试、不更改代理或安全设置来绕过限制；仍不可访问时请用户提供固定版本源码及其提交信息。
- [ ] **Step 2：隔离存放输入。** 每份归档／下载创建独立空目录，记录来源URL、取得时间、归档SHA256、固定commit、提供者和内容清单。解包拒绝绝对路径、`..`、symlink与超限文件；脚本始终留在 `tools/`，不从输入目录执行Python、Node或安装器。
- [ ] **Step 3：仅静态审查。** 核对许可证原文、README限制和依赖许可是否一致；记录签名JS、execjs、浏览器依赖、Node/Python版本、动态下载、子进程、安装钩子及未知二进制。无许可证或限制冲突标记blocked，不因“公开GitHub”推定可用。
- [ ] **Step 4：识别能力边界。** 根据真实源码列出作品链接入口、请求方式、账号要求、返回数据以及是否存在发布／指标接口。没有某功能明确写unsupported；发布可另行采用官方或其他获授权方式，但其来源与权限必须单独审查。
- [ ] **Step 5：写来源审查结论。** `source-review.md` 必须具有以下标题：来源与版本、许可证与使用限制、依赖与环境、运行副作用、可见能力、证据文件、允许的验证范围、阻断项。每项写观察事实和出处；缺资料写“未验证：缺少某项资料”，不留空标题。
- [ ] **Step 6：填写报告的已证实项目。** 只有审查证据支持时更新license/runtime/limits；authorization_ref引用本地审查授权记录，不包含凭证。文件SHA256用以下命令计算，将完整64位值写入对应evidence项：

```bash
python -I -c "from pathlib import Path; import hashlib; p=Path('docs/superpowers/verification/douyin/evidence/source-license.md'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
```

- [ ] **Step 7：退出检查。** 来源可核验且许可允许当前用途才继续；网络、许可或来源不足时交付blocked报告并停止，不实施业务模块。

本任务为调查与文档，不增加外部调用代码；因此不以假函数或假SDK演示许可／平台能力。

## Task 4：获授权真实能力验证与证据采集

**Files:**
- Create evidence: `evidence/reference-link.md`、`accounts.md`、`publish.md`、`reconcile.md`、`schedule.md`、`metrics.md`（均位于报告同目录的evidence内）
- Update: `docs/superpowers/verification/douyin/capability-report.json`

**Interfaces:**
- Consumes: Task 3批准的固定版本、明确的使用权限和测试账号／成片授权。
- Produces: reference_link/accounts/publish/reconcile/schedule/metrics的真实观察及具体限制。
- 当前不定义或实现SDK调用签名：必须先取得真实来源和文档，再编写与批准验证操作，不能用猜测接口执行。

- [ ] **Step 1：收齐最小输入。** 用户提供两个有权运营的测试账号、可研究的作品链接、明确可发布的成片／封面／文案和计划时间；通过安全方式提供授权信息，不把Cookie或Token粘贴进报告、脚本、命令行或日志。无输入则保持unverified，先交付已完成的离线部分。
- [ ] **Step 2：在执行前确认方案。** 展示采集来源、请求将发送到哪些服务、账号权限、媒体要求、费用与操作副作用；发布按具体账号、内容、时间逐次取得用户确认。不得自行发到第二个账号或删除测试作品。
- [ ] **Step 3：验证链接采集。** 使用获授权来源记录规范化作品ID、字段、采集时间、不可用字段及限制。手工构造的JSON、静态fixture和上游demo输出不能当作真实成功证据。
- [ ] **Step 4：验证两个账号身份与授权隔离。** 使用别名记录两个不同账号已确认的平台身份、授权范围、有效期及可识别的失效信号；证据中不放真实凭证和账号个人信息。避免为失效测试主动破坏正在使用的授权。
- [ ] **Step 5：验证媒体上传和系统发布。** 在批准的时间和账号执行一次明确授权发布，记录SDK／HTTP操作名称、脱敏请求字段、响应时间、作品ID／链接及后续确认。证据须区分上传完成、发起发布、平台接受、平台审核与可见性。平台公开作品链接的记录及交付仍按用户授权范围控制，不额外发布到其他服务。
- [ ] **Step 6：验证结果查询。** 只读查询本任务Step 5中的真实作品，确认作品ID及状态可对应；评估上游幂等键或请求标识。未知结果必须能保持未知；若平台无法对账，在结论中要求系统禁止不明结果自动重发。不要人为制造可能重复发布的超时请求来测试。
- [ ] **Step 7：验证定时可行性。** 记录授权有效期、媒体上传生命周期及到期可调用条件，判断工作台调度是否可行；原生无定时接口不等于不支持工作台定时。未经另一次明确授权不再发测试作品；完整调度／取消竞争在C使用fake adapter和clock测试，再做授权验收。
- [ ] **Step 8：验证真实指标。** 对获授权作品获取至少一种真实互动指标（如点赞、评论、分享，字段以实际接口为准），记录采集时间、字段原名、权限、0与缺失的区别、延迟及查询配额。播放量不替代“至少一种互动指标”的门槛；无指标不能填模拟数。
- [ ] **Step 9：脱敏与报告。** 每个证据文件包含：操作目的、账号别名／授权引用、来源版本、实际执行时间、输入摘要、观察结果、限制、脱敏字段清单和判定。必要原始响应只在本地安全存储，不交付；对外记录仅使用脱敏摘录。更新对应报告项，实际失败写failed，未执行写unverified，权限不够写blocked，不支持写unsupported。
- [ ] **Step 10：记录可用限制。** 将媒体格式、大小／时长／分辨率、Token周期、并发、刷新频率、费用、用途限制写入limits证据。只有真实验证达到两个账号与至少一种互动指标，才将accounts_tested及interaction_metrics更新为观察值。

以上步骤受外部平台权限和可用性约束，不承诺每步2—5分钟完成，也不承诺真实指标立即可见。涉及人工平台审核或异步指标延迟时报告等待状态，不轮询或重复发布制造结果。

## Task 5：冻结契约、判定门槛并交付

**Files:**
- Create: `docs/superpowers/verification/douyin/contracts.md`
- Create: `docs/superpowers/verification/douyin/decision.md`
- Update: `docs/superpowers/verification/douyin/capability-report.json`

**Interfaces:**
- Consumes: Tasks 3—4真实证据与报告。
- Produces: 经过人工核对的继续／停止决定，以及B逐步代码计划的明确输入。

- [ ] **Step 1：冻结契约。** `contracts.md` 逐项写明：
  1. 账号授权和身份验证的实际调用、凭证类型、scope、刷新／失效信号。
  2. 作品链接输入及规范化返回字段；不把完整上游dict泄漏给业务模块。
  3. 媒体格式与上传／发布顺序；封面是否必需、大小与时长等已核验限制。
  4. 发布调用的真实参数、返回类型、作品ID、错误类型和不明结果行为。
  5. 查询接口、幂等支持、取消能力及明确的不可支持项。
  6. 指标字段、可获取性、延迟、限流与批准的保守刷新频率。
  7. 每一条内部适配协议的Python签名、输入／返回类型、错误枚举和对应脱敏fixture路径。签名以验证结果制定；未验证不能用 `execute(**kwargs)` 或任意dict代替冻结。
  8. 依赖固定方式、许可证保留路径、安装审查及运行环境。
- [ ] **Step 2：建立判定。** `decision.md` 写入：硬门槛逐项证据、费用权限限制、许可结论、可用／不可用能力、基线是否变化、继续／停止及理由、用户需决定事项。只有所有必需项真实通过才可建议继续；否则明确停止，不生成生产接入代码。
- [ ] **Step 3：检查证据结构。**

```bash
python -I tools/douyin_validation/evidence.py check docs/superpowers/verification/douyin/capability-report.json
```

预期：资料齐全且真实验证均通过时退出0并提示人工核验；缺少任何项时退出2并列阻断。不能通过伪造passed来满足命令。

- [ ] **Step 4：运行离线回归并核对基线。**

```bash
python -m pytest tests/douyin_validation -v
```

预期：6 passed；测试fixture不产生真实能力证据。

```bash
python -I tools/douyin_validation/baseline.py check . .local/douyin-validation/baseline
```

预期：`BASELINE MATCH`。若变化，先定位来源，不能宣称未改业务代码；任务A不应产生变化。

若发现某个源文件变化，按manifest中的明确路径逐文件比较。例如检查主应用入口：

```bash
git diff --no-index -- .local/douyin-validation/baseline/files/backend/app/main.py backend/app/main.py
```

退出0为无差异，1为存在差异，大于1为工具／路径错误；不将1当作执行失败，不将错误当作无差异。本命令不要求当前是Git仓库。

- [ ] **Step 5：人工核验证据。** 代码通过只能证明结构和哈希完整；核对真实作品、真实指标、授权引用和许可事实。来源未知、fixture冒充真实响应或字段不一致必须驳回。
- [ ] **Step 6：交付并停在决策门。** 将脱敏source-review、capability-report、contracts、decision交给用户，明确实际完成、失败／未验证、费用与后续选择。用户确认继续后才编写B的逐步代码计划；不要自动开始账号／发布实现。

## 自查与完成标准

- [ ] 所有新增工具均有RED／GREEN；测试完全离线，不触发应用lifespan或平台调用。
- [ ] 任务1—2可在无账号环境运行；任务3—4缺资料／授权时诚实停止。
- [ ] 证据门槛不得使用测试中的虚构fixture；工具通过后仍需人工审查。
- [ ] 真正的上游版本、许可、发布及指标来源都可追溯；未验证接口没有被包装成已实现。
- [ ] 业务基线匹配，现有应用未被修改，未运行迁移，未提交代码。
- [ ] A通过或未通过均有可交付报告；A完成不等于B—D完成，也不等于完整运营应用已交付。
