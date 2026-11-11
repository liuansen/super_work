"""密钥轮换脚本（SEC-1 / FIX_PLAN §3）。

用途：更换 SECRET_KEY / FERNET_KEY 前，把数据库中以 Fernet 加密的敏感字段
（账号 Cookie、模型 API Key、登录临时 Cookie）用旧密钥解密、新密钥重新加密。

必须遵守的操作顺序（详见 FIX_PLAN §3）：
1. 停应用，备份数据库（含 -wal/-shm）。
2. 先 --dry-run 确认计数，再实跑。
3. 实跑后再切换环境变量并启动应用；旧 JWT 全部失效，用户需重新登录。

用法示例：
    # 仅检查（不写库）：统计可解密/不可解密的行数
    ROTATE_OLD_SECRET=<旧SECRET> ROTATE_NEW_FERNET_KEY=<新FERNET_KEY> python scripts/rotate_secrets.py --old-secret --new-fernet-key --dry-run

    # 实际轮换
    ROTATE_OLD_SECRET=<旧SECRET> ROTATE_NEW_FERNET_KEY=<新FERNET_KEY> python scripts/rotate_secrets.py --old-secret --new-fernet-key

    # 旧密钥本身就是独立 FERNET_KEY 的场景
    ROTATE_OLD_FERNET_KEY=<旧KEY> ROTATE_NEW_FERNET_KEY=<新KEY> python scripts/rotate_secrets.py --old-fernet-key --new-fernet-key
"""
from __future__ import annotations

import argparse
import base64
import os
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _build_fernet(*, secret: str | None, fernet_key: str | None):
    from cryptography.fernet import Fernet

    if fernet_key:
        return Fernet(fernet_key.encode("utf-8"))
    if secret:
        return Fernet(_derive_fernet_key(secret))
    raise SystemExit("必须提供 --old-secret / --old-fernet-key / --new-fernet-key 之一")


def rotate(*, old_fernet, new_fernet, dry_run: bool, database_url: str | None) -> dict:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from backend.app.models import AccountCookieVersion, LoginSession, ModelConfig

    if database_url:
        engine = create_engine(database_url)
    else:
        from backend.app.core.database import engine

    report: dict = {}

    # (模型, 加密字段, 可空) —— 新增加密字段时在此登记
    targets = [
        (AccountCookieVersion, "encrypted_cookies", False),
        (ModelConfig, "encrypted_api_key", False),
        (LoginSession, "encrypted_temp_cookies", True),
    ]

    with Session(engine) as db:
        for model, field, nullable in targets:
            rows = db.scalars(select(model)).all()
            total = len(rows)
            reencrypted = 0
            skipped_empty = 0
            undecryptable = 0
            for row in rows:
                raw = getattr(row, field)
                if not raw:
                    if nullable:
                        skipped_empty += 1
                    else:
                        undecryptable += 1  # 非空但为空串：记为异常
                    continue
                try:
                    plaintext = old_fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
                except Exception:
                    undecryptable += 1
                    continue
                if not dry_run:
                    setattr(row, field, new_fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8"))
                    reencrypted += 1
                else:
                    reencrypted += 1
            report[model.__tablename__] = {
                "total": total,
                "reencrypted": reencrypted,
                "skipped_empty": skipped_empty,
                "undecryptable": undecryptable,
            }
        if not dry_run:
            db.commit()

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="轮换数据库中 Fernet 加密的敏感字段")
    # 密钥只从环境变量读取：命令行参数会进入 shell history 与
    # /proc/<pid>/cmdline（进程列表对所有本机用户可读），而轮换窗口内
    # 旧密钥仍然有效，等于把最敏感的凭据暴露在主机层面。
    parser.add_argument(
        "--old-secret", action="store_true",
        help="从环境变量 ROTATE_OLD_SECRET 读取旧 SECRET_KEY",
    )
    parser.add_argument(
        "--old-fernet-key", action="store_true",
        help="从环境变量 ROTATE_OLD_FERNET_KEY 读取旧 FERNET_KEY",
    )
    parser.add_argument(
        "--new-secret", action="store_true",
        help="从环境变量 ROTATE_NEW_SECRET 读取新 SECRET_KEY",
    )
    parser.add_argument(
        "--new-fernet-key", action="store_true",
        help="从环境变量 ROTATE_NEW_FERNET_KEY 读取新 FERNET_KEY（推荐）",
    )
    parser.add_argument("--database-url", help="覆盖数据库连接串，默认读应用配置")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args(argv)

    if any(
        value and "--" in value
        for value in (os.getenv("ROTATE_OLD_SECRET"), os.getenv("ROTATE_NEW_SECRET"))
    ):
        print("警告：检测到环境变量里疑似命令行参数，请勿把密钥写在命令行。")

    old_secret = os.getenv("ROTATE_OLD_SECRET") if args.old_secret else None
    old_key = os.getenv("ROTATE_OLD_FERNET_KEY") if args.old_fernet_key else None
    new_secret = os.getenv("ROTATE_NEW_SECRET") if args.new_secret else None
    new_key = os.getenv("ROTATE_NEW_FERNET_KEY") if args.new_fernet_key else None

    if args.old_secret and not old_secret:
        print("错误：--old-secret 需要环境变量 ROTATE_OLD_SECRET")
        return 2
    if args.new_fernet_key and not new_key:
        print("错误：--new-fernet-key 需要环境变量 ROTATE_NEW_FERNET_KEY")
        return 2

    old_fernet = _build_fernet(secret=old_secret, fernet_key=old_key)
    new_fernet = _build_fernet(secret=new_secret, fernet_key=new_key)

    if args.dry_run:
        print("[dry-run] 不会写入任何数据")
    else:
        print("警告：实跑前请确认已停应用并备份数据库（含 -wal/-shm 文件）。")
        answer = input("输入 yes 继续轮换: ").strip().lower()
        if answer != "yes":
            print("已取消")
            return 1

    report = rotate(
        old_fernet=old_fernet,
        new_fernet=new_fernet,
        dry_run=args.dry_run,
        database_url=args.database_url,
    )

    print("轮换结果：")
    for table, stats in report.items():
        print(f"  {table}: {stats}")
    bad = sum(stats["undecryptable"] for stats in report.values())
    if bad:
        print(f"注意：{bad} 行无法用旧密钥解密（可能已轮换过或已损坏），未改动。")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
