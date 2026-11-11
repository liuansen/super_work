from __future__ import annotations

import logging
import os
import secrets
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

# 已知的占位/默认密钥：生产环境使用它们等于把 JWT 签名与 Cookie 加密交给公众
_PLACEHOLDER_SECRET_KEYS = {"dev-only-change-me", "change-me", "CHANGE_ME_VIA_ENV_VAR", ""}
_KNOWN_PLACEHOLDER_SECRET_KEYS = _PLACEHOLDER_SECRET_KEYS - {""}

VALID_ENVIRONMENTS = ("development", "test", "production")


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
        # review P3：以下安全关键项此前不在映射表里，写在 YAML 会被静默丢弃，
        # 运维以为加固生效、实际只有环境变量才管用。
        "security.auth_rate_limit_per_minute": "auth_rate_limit_per_minute",
        "security.password_min_length": "password_min_length",
        "security.include_refresh_in_body": "include_refresh_in_body",
        "security.allow_private_model_endpoints": "allow_private_model_endpoints",
        "rate_limit.redis_url": "redis_url",
        "rate_limit.crawl_per_minute": "crawl_rate_limit_per_minute",
        "backup.enabled": "backup_enabled",
        "backup.dir": "backup_dir",
        "backup.keep": "backup_keep",
        "environment": "environment",
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
                elif prefix == "security" and not isinstance(value, dict):
                    # 安全项写错名字时不能静默丢弃，否则“以为加固了实际没生效”
                    logger.warning(
                        "config YAML 中的 %s 没有对应的设置项，已忽略（请改用环境变量或补充 yaml_key_map）",
                        full_key,
                    )
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

    # 安全兜底开关：仅允许 development/test 在默认密钥下启动（生产禁止）
    allow_insecure_defaults: bool = False

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
    # INF-4：默认只绑回环；容器部署用 --host 0.0.0.0 显式开放
    server_host: str = "127.0.0.1"
    server_port: int = 8000

    # CORS
    backend_cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # Security
    registration_enabled: bool = True
    # 认证限流：单 IP+用户名 每分钟最大尝试次数（进程内存实现，SEC-6）
    auth_rate_limit_per_minute: int = 10
    # 新注册用户密码最小长度（老用户登录不受影响）
    password_min_length: int = 8
    # 是否在登录/注册响应体中返回 refresh token（SEC-7 默认关闭，改用 HttpOnly Cookie）
    include_refresh_in_body: bool = False

    # 媒体素材 URL 抓取域名白名单（后缀匹配，逗号分隔）
    media_url_allowed_hosts: str = "xhscdn.com,xiaohongshu.com"

    # 模型端点连通性测试是否允许环回/私网地址（本地 LLM 部署需要）。
    # 多租户/公网部署应设为 False，防内网探测。
    allow_private_model_endpoints: bool = True

    # 分布式限流（可选）：设置后登录限流与抓取限速在多 worker 间共享计数
    redis_url: str = ""

    # 抓取限速：每账号每分钟最大抓取次数（0 = 停止抓取）
    crawl_rate_limit_per_minute: int = 5

    # SQLite 自动备份（VACUUM INTO，每 24h 一次；非 SQLite 后端自动跳过）
    backup_enabled: bool = True
    backup_dir: str = "./data/backups"
    backup_keep: int = 7

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
        if self.environment not in VALID_ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT 必须是 {'|'.join(VALID_ENVIRONMENTS)} 之一，当前为 {self.environment!r}"
            )

        # 开发/测试环境下密钥为空时生成进程内随机密钥：
        # 不再回退到公开的 "dev-only-change-me"，避免仓库默认值被原样带到真实部署。
        if self.secret_key == "" and self.environment in ("development", "test"):
            object.__setattr__(self, "secret_key", secrets.token_urlsafe(48))
            logger.info("未设置 SECRET_KEY，已为 %s 环境生成进程内随机密钥（重启后已签发令牌失效）", self.environment)

        if self.secret_key in _PLACEHOLDER_SECRET_KEYS:
            logger.warning(
                "Settings.secret_key 使用的是默认/占位密钥（%r）。"
                "JWT 签名与 Cookie 加密将基于公开字符串，任何拿到仓库代码的人都可以伪造登录态并解密 Cookie。"
                "请通过 SECRET_KEY / FERNET_KEY 环境变量或 .env 设置强随机密钥。",
                self.secret_key,
            )

        # 生产环境默认关闭注册（除非显式设置 registration_enabled=true）
        if (
            self.environment == "production"
            and "registration_enabled" not in self.model_fields_set
            and self.registration_enabled
        ):
            object.__setattr__(self, "registration_enabled", False)

        # review P2：生产环境默认收紧模型端点 SSRF 防护（默认 True 只为本地 Ollama 场景）。
        # 未显式配置时自动切换为 False，多租户/公网部署不再默认放行私网端点。
        if (
            self.environment == "production"
            and "allow_private_model_endpoints" not in self.model_fields_set
            and self.allow_private_model_endpoints
        ):
            object.__setattr__(self, "allow_private_model_endpoints", False)
            logger.info(
                "生产环境默认禁止模型端点访问私网/环回地址；"
                "如需连接内网 LLM，请显式设置 ALLOW_PRIVATE_MODEL_ENDPOINTS=true"
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

    @property
    def media_dir(self) -> Path:
        return self.storage_dir / "media"

    @property
    def exports_dir(self) -> Path:
        return self.storage_dir / "exports"

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    def assert_runtime_safety(self) -> None:
        """生产环境启动前的安全断言：拒绝使用公开占位密钥。

        - development/test：仅告警，不阻断（方便本地起服务）。
        - production：secret_key 为空/占位值时直接抛异常终止启动；
          设置 ALLOW_INSECURE_DEFAULTS=1 可显式豁免（仅限一次性迁移场景）。
        """
        if self.environment in ("development", "test"):
            if self.secret_key in _KNOWN_PLACEHOLDER_SECRET_KEYS:
                logger.warning(
                    "当前为 %s 环境且使用默认密钥 %r，仅供本地开发，切勿用于生产。",
                    self.environment,
                    self.secret_key,
                )
            return

        # review P3：allow_origins=["*"] + allow_credentials=True 等效于全站放开，
        # 生产环境必须使用具体域名。放在 ALLOW_INSECURE_DEFAULTS 豁免之前——
        # 该开关只为密钥轮换场景开洞，不应连带放过 CORS 全开。
        origins = [o.strip() for o in (self.backend_cors_origins or "").split(",") if o.strip()]
        if "*" in origins:
            raise RuntimeError(
                "生产环境拒绝启动：BACKEND_CORS_ORIGINS 不能为 '*'"
                "（allow_credentials=True 时会反射任意 Origin，等于全站可带凭据跨域）。"
                "请配置具体的前端域名，如 https://your-domain.com"
            )

        if self.allow_insecure_defaults:
            logger.warning(
                "ALLOW_INSECURE_DEFAULTS=1：已跳过生产密钥安全校验。"
                "该开关仅允许在密钥轮换等受控场景临时使用。"
            )
            return

        if self.secret_key in _PLACEHOLDER_SECRET_KEYS:
            raise RuntimeError(
                "生产环境拒绝启动：SECRET_KEY 未设置或仍为占位值"
                "（Fernet 加密密钥也由其派生，等于公开）。"
                "请通过环境变量 SECRET_KEY 提供 32 字节以上强随机密钥"
                "（可用 python -c \"import secrets; print(secrets.token_urlsafe(48))\" 生成），"
                "或为加密数据单独设置 FERNET_KEY。"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
