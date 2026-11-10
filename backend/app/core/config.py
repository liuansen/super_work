from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type
from urllib.parse import quote_plus

try:
    from pydantic.fields import FieldInfo
    from pydantic_settings import (
        BaseSettings,
        PydanticBaseSettingsSource,
        SettingsConfigDict,
    )
except ImportError:  # pragma: no cover - handled by dependency installation
    BaseSettings = object
    PydanticBaseSettingsSource = object
    SettingsConfigDict = dict
    FieldInfo = Any

logger = logging.getLogger(__name__)

# 项目根目录（backend/app/core/config.py -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_PLACEHOLDER_SECRET_KEYS = {"dev-only-change-me", "change-me", "CHANGE_ME_VIA_ENV_VAR", ""}


def _load_yaml_config() -> Dict[str, Any]:
    """Load YAML configuration files and flatten into env-var-style keys.

    Loading order (later values override earlier ones):
      1. config/default.yaml (always loaded if it exists)
      2. File specified by CONFIG_FILE environment variable

    Note: YAML values are applied as the LOWEST-priority source (below .env
    and process environment variables), see YamlConfigSettingsSource below.
    """
    try:
        import yaml
    except ImportError:
        return {}

    project_root = PROJECT_ROOT
    flat: Dict[str, Any] = {}

    # Mapping from nested YAML paths to Settings field names
    yaml_key_map = {
        "server.host": "server_host",
        "server.port": "server_port",
        "server.cors_origins": "backend_cors_origins",
        "database.type": "database_type",
        "database.sqlite_path": "database_sqlite_path",
        "database.mysql_host": "database_mysql_host",
        "database.mysql_port": "database_mysql_port",
        "database.mysql_user": "database_mysql_user",
        "database.mysql_password": "database_mysql_password",
        "database.mysql_database": "database_mysql_database",
        "security.secret_key": "secret_key",
        "security.fernet_key": "fernet_key",
        "security.registration_enabled": "registration_enabled",
        "security.media_url_allowed_hosts": "media_url_allowed_hosts",
        "scheduler.enabled": "scheduler_enabled",
        "scheduler.interval_seconds": "scheduler_interval_seconds",
        "frontend.serve_static": "frontend_serve_static",
        "frontend.build_dir": "frontend_build_dir",
    }

    def _flatten(data: Any, prefix: str = "") -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if full_key in yaml_key_map:
                    flat[yaml_key_map[full_key]] = value
                _flatten(value, full_key)

    # 1. Load config/default.yaml
    default_yaml = project_root / "config" / "default.yaml"
    if default_yaml.exists():
        with open(default_yaml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data:
                _flatten(data)

    # 2. Load CONFIG_FILE override
    config_file = os.environ.get("CONFIG_FILE")
    if config_file:
        config_path = Path(config_file)
        if not config_path.is_absolute():
            config_path = project_root / config_path
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    _flatten(data)

    return flat


if PydanticBaseSettingsSource is not object:

    class YamlConfigSettingsSource(PydanticBaseSettingsSource):
        """把 YAML 配置作为最低优先级设置源。

        pydantic-settings 的合并顺序为：
        init kwargs > 环境变量 > .env > file secrets > 自定义源（本源）
        这样保证 README 承诺的优先级：
        config/default.yaml < CONFIG_FILE < .env < 环境变量
        """

        def get_field_value(
            self, field: FieldInfo, field_name: str
        ) -> Tuple[Any, str, bool]:
            # 仅实现 __call__，此方法不会被调用到
            return None, field_name, False

        def __call__(self) -> Dict[str, Any]:
            return _load_yaml_config()

else:  # pragma: no cover - pydantic-settings 缺失时的兜底
    YamlConfigSettingsSource = None  # type: ignore[assignment, misc]


class Settings(BaseSettings):
    app_name: str = "Spider_XHS"
    api_title: str = "Spider_XHS Operations Platform"
    environment: str = "development"

    # Database
    database_url: str = ""
    database_type: str = "sqlite"
    database_sqlite_path: str = "./data/spider_xhs.db"
    database_mysql_host: str = "localhost"
    database_mysql_port: int = 3306
    database_mysql_user: str = "spider_xhs"
    database_mysql_password: str = "change_me"
    database_mysql_database: str = "spider_xhs"

    # Security
    secret_key: str = "dev-only-change-me"
    fernet_key: str = ""

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # CORS
    backend_cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # Security
    registration_enabled: bool = True

    # 媒体素材 URL 抓取域名白名单（后缀匹配，逗号分隔）
    media_url_allowed_hosts: str = "xhscdn.com,xiaohongshu.com"

    # 模型端点连通性测试是否允许环回/私网地址（本地 LLM 部署需要）。
    # 多租户/公网部署应设为 False，防内网探测。
    allow_private_model_endpoints: bool = True

    # Scheduler
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 60

    # Asset storage
    asset_storage_type: str = "local"

    # Frontend static serving
    frontend_serve_static: bool = False
    frontend_build_dir: str = "./frontend/dist"

    if hasattr(BaseSettings, "model_config"):
        model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # YAML 永远排在最后：环境变量 / .env 均可覆盖 YAML 值
        sources: Tuple[PydanticBaseSettingsSource, ...] = (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )
        if YamlConfigSettingsSource is not None:
            sources += (YamlConfigSettingsSource(settings_cls),)
        return sources

    def _resolve_project_path(self, value: str) -> Path:
        """相对路径统一锚定到项目根目录，避免依赖启动时 CWD。"""
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def model_post_init(self, __context: Any) -> None:
        if self.secret_key in _PLACEHOLDER_SECRET_KEYS:
            logger.warning(
                "Settings.secret_key 使用的是默认/占位密钥（%r）。"
                "JWT 签名与 Cookie 加密将基于公开字符串，任何拿到仓库代码的人都可以伪造登录态并解密 Cookie。"
                "请通过 SECRET_KEY / FERNET_KEY 环境变量或 .env 设置强随机密钥。",
                self.secret_key,
            )

        # Build database_url from component fields if not explicitly set
        if not self.database_url:
            if self.database_type == "mysql":
                object.__setattr__(
                    self,
                    "database_url",
                    "mysql+pymysql://{}:{}@{}:{}/{}?charset=utf8mb4".format(
                        quote_plus(self.database_mysql_user),
                        quote_plus(self.database_mysql_password),
                        self.database_mysql_host,
                        self.database_mysql_port,
                        self.database_mysql_database,
                    ),
                )
            else:
                # Backward compatibility: if the old default DB path exists but the
                # new YAML-configured path does not, use the old path so existing
                # installations keep their data without manual migration.
                sqlite_path = self._resolve_project_path(self.database_sqlite_path)
                old_default = self._resolve_project_path(
                    "./backend/app/storage/spider_xhs.db"
                )
                if sqlite_path != old_default and not sqlite_path.exists() and old_default.exists():
                    sqlite_path = old_default
                object.__setattr__(
                    self,
                    "database_url",
                    f"sqlite:///{sqlite_path}",
                )
        else:
            # database_url 显式提供时也解析其中的 sqlite 相对路径
            url = self.database_url
            if url.startswith("sqlite:///") and not Path(url[len("sqlite:///"):]).is_absolute():
                object.__setattr__(
                    self,
                    "database_url",
                    f"sqlite:///{self._resolve_project_path(url[len('sqlite:///'):])}",
                )

        object.__setattr__(
            self,
            "frontend_build_dir",
            str(self._resolve_project_path(self.frontend_build_dir)),
        )

    @property
    def storage_dir(self) -> Path:
        return PROJECT_ROOT / "backend" / "app" / "storage"


@lru_cache
def get_settings() -> Settings:
    return Settings()
