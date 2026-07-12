"""Integration configuration for ResQ.

Centralized configuration for all integrations.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, List
from dotenv import load_dotenv


class ResQConfig:
    """Configuration for ResQ integrations."""

    def __init__(self, config_path: Optional[str] = None):
        load_dotenv()

        self.config_path = config_path or os.getenv("RESQ_CONFIG_PATH", ".resq.json")
        self.config: Dict = {}

        if Path(self.config_path).exists():
            with open(self.config_path) as f:
                self.config = json.load(f)

    # ── SLS (Alibaba Cloud Log Service) ─────────────────────────────

    @property
    def sls_enabled(self) -> bool:
        return bool(os.getenv("ALIBABA_ACCESS_KEY_ID"))

    @property
    def sls_config(self) -> Dict:
        return {
            "access_key_id": os.getenv("ALIBABA_ACCESS_KEY_ID"),
            "access_key_secret": os.getenv("ALIBABA_ACCESS_KEY_SECRET"),
            "region": os.getenv("ALIBABA_REGION_ID", "cn-hangzhou"),
            "endpoint": os.getenv("SLS_ENDPOINT"),
            "project": os.getenv("SLS_PROJECT"),
            "logstore": os.getenv("SLS_LOGSTORE"),
        }

    # ── Prometheus ───────────────────────────────────────────────────

    @property
    def prometheus_enabled(self) -> bool:
        return bool(os.getenv("PROMETHEUS_URL"))

    @property
    def prometheus_config(self) -> Dict:
        return {
            "url": os.getenv("PROMETHEUS_URL", "http://localhost:9090"),
            "username": os.getenv("PROMETHEUS_USERNAME"),
            "password": os.getenv("PROMETHEUS_PASSWORD"),
        }

    # ── Source Code ──────────────────────────────────────────────────

    @property
    def source_local_path(self) -> Optional[str]:
        return os.getenv("SOURCE_LOCAL_PATH")

    @property
    def source_github_url(self) -> Optional[str]:
        return os.getenv("SOURCE_GITHUB_URL")

    @property
    def source_github_token(self) -> Optional[str]:
        return os.getenv("GITHUB_TOKEN")

    # ── Infrastructure ───────────────────────────────────────────────

    @property
    def redis_url(self) -> Optional[str]:
        return os.getenv("REDIS_URL")

    @property
    def database_url(self) -> Optional[str]:
        return os.getenv("DATABASE_URL")

    @property
    def kafka_servers(self) -> Optional[str]:
        return os.getenv("KAFKA_BOOTSTRAP_SERVERS")

    @property
    def rabbitmq_url(self) -> Optional[str]:
        return os.getenv("RABBITMQ_URL")

    # ── OSS (Report Storage) ─────────────────────────────────────────────

    @property
    def oss_enabled(self) -> bool:
        return bool(os.getenv("OSS_ENDPOINT"))

    @property
    def oss_config(self) -> Dict:
        return {
            "access_key_id": os.getenv("ALIBABA_ACCESS_KEY_ID"),
            "access_key_secret": os.getenv("ALIBABA_ACCESS_KEY_SECRET"),
            "endpoint": os.getenv("OSS_ENDPOINT"),
            "bucket_name": os.getenv("OSS_BUCKET_NAME", "resq-reports"),
            "region": os.getenv("ALIBABA_REGION_ID", "cn-hangzhou"),
        }

    # ── Qwen API ────────────────────────────────────────────────────

    @property
    def qwen_api_key(self) -> Optional[str]:
        return os.getenv("QWEN_API_KEY")

    @property
    def qwen_base_url(self) -> str:
        return os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

    @property
    def qwen_model(self) -> str:
        return os.getenv("QWEN_MODEL", "qwen-plus")

    # ── Webhook ─────────────────────────────────────────────────────

    @property
    def webhook_port(self) -> int:
        return int(os.getenv("RESQ_WEBHOOK_PORT", "5001"))

    # ── Infrastructure Map ───────────────────────────────────────────

    @property
    def infrastructure_map(self) -> Dict[str, str]:
        """Map of infrastructure component names to URLs."""
        infra = {}

        if self.redis_url:
            infra["redis"] = self.redis_url
        if self.database_url:
            infra["database"] = self.database_url
        if self.kafka_servers:
            infra["kafka"] = self.kafka_servers
        if self.rabbitmq_url:
            infra["rabbitmq"] = self.rabbitmq_url

        return infra

    # ── Validation ───────────────────────────────────────────────────

    def validate(self) -> List[str]:
        """Validate configuration and return list of issues."""
        issues = []

        if not self.qwen_api_key:
            issues.append("QWEN_API_KEY not set - Qwen API will be unavailable")

        if not self.sls_enabled and not self.prometheus_enabled:
            issues.append("No log/metrics source configured (SLS or Prometheus)")

        if not self.source_local_path and not self.source_github_url:
            issues.append("No source code configured (local path or GitHub URL)")

        return issues

    def summary(self) -> str:
        """Get configuration summary."""
        lines = ["ResQ Configuration Summary:", "=" * 40]

        # Qwen API
        lines.append(f"Qwen API: {'✓' if self.qwen_api_key else '✗'}")

        # Logs
        lines.append(f"SLS Logs: {'✓' if self.sls_enabled else '✗'}")

        # Metrics
        lines.append(f"Prometheus: {'✓' if self.prometheus_enabled else '✗'}")

        # Source Code
        if self.source_local_path:
            lines.append(f"Source (Local): ✓ {self.source_local_path}")
        elif self.source_github_url:
            lines.append(f"Source (GitHub): ✓ {self.source_github_url}")
        else:
            lines.append("Source: ✗")

        # Infrastructure
        infra = self.infrastructure_map
        if infra:
            lines.append(f"Infrastructure: {', '.join(infra.keys())}")
        else:
            lines.append("Infrastructure: ✗")

        # Webhook
        lines.append(f"Webhook Port: {self.webhook_port}")

        return "\n".join(lines)

    def save(self):
        """Save configuration to file."""
        config = {
            "prometheus": self.prometheus_config,
            "source": {
                "local_path": self.source_local_path,
                "github_url": self.source_github_url,
            },
            "infrastructure": self.infrastructure_map,
            "webhook_port": self.webhook_port,
        }

        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)
