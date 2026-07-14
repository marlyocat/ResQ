"""Centralized configuration for Alibaba Cloud integrations.

Loads credentials and per-service settings from environment variables
(via a .env file in development). Modeled on ResQ's integrations/config.py
but scoped to the four resources this Flask service uses.
"""

import os
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()


class AlibabaConfig:
    """Configuration for all Alibaba Cloud integrations used by the app."""

    # ── Shared credentials ──────────────────────────────────────────────
    @property
    def access_key_id(self) -> Optional[str]:
        return os.getenv("ALIBABA_ACCESS_KEY_ID")

    @property
    def access_key_secret(self) -> Optional[str]:
        return os.getenv("ALIBABA_ACCESS_KEY_SECRET")

    @property
    def region_id(self) -> str:
        return os.getenv("ALIBABA_REGION_ID", "cn-hangzhou")

    @property
    def has_credentials(self) -> bool:
        return bool(self.access_key_id and self.access_key_secret)

    # ── SLS (Simple Log Service) ────────────────────────────────────────
    @property
    def sls_endpoint(self) -> str:
        # Derive from region when not explicitly set.
        return os.getenv("SLS_ENDPOINT") or f"{self.region_id}.log.aliyuncs.com"

    @property
    def sls_project(self) -> Optional[str]:
        return os.getenv("SLS_PROJECT")

    @property
    def sls_logstore(self) -> Optional[str]:
        return os.getenv("SLS_LOGSTORE")

    @property
    def sls_topic(self) -> str:
        return os.getenv("SLS_TOPIC", "flaskapp")

    @property
    def sls_source(self) -> str:
        return os.getenv("SLS_SOURCE", "")

    @property
    def sls_enabled(self) -> bool:
        return bool(self.has_credentials and self.sls_project and self.sls_logstore)

    # ── OSS (Object Storage Service) ────────────────────────────────────
    @property
    def oss_endpoint(self) -> Optional[str]:
        return os.getenv("OSS_ENDPOINT")

    @property
    def oss_bucket_name(self) -> str:
        return os.getenv("OSS_BUCKET_NAME", "flaskapp-reports")

    @property
    def oss_enabled(self) -> bool:
        return bool(self.has_credentials and self.oss_endpoint)

    # ── ECS (Elastic Compute Service) ───────────────────────────────────
    @property
    def ecs_instance_id(self) -> Optional[str]:
        return os.getenv("ECS_INSTANCE_ID")

    @property
    def ecs_enabled(self) -> bool:
        return self.has_credentials

    # ── CMS (Cloud Monitor Service) ─────────────────────────────────────
    @property
    def cms_namespace(self) -> str:
        return os.getenv("CMS_NAMESPACE", "acs_ecs_dashboard")

    @property
    def cms_enabled(self) -> bool:
        return self.has_credentials

    # ── App ─────────────────────────────────────────────────────────────
    @property
    def port(self) -> int:
        return int(os.getenv("PORT", "8000"))

    # ── Introspection ───────────────────────────────────────────────────
    def enabled_map(self) -> Dict[str, bool]:
        return {
            "sls": self.sls_enabled,
            "oss": self.oss_enabled,
            "ecs": self.ecs_enabled,
            "cms": self.cms_enabled,
        }

    def validate(self) -> List[str]:
        """Return a list of human-readable configuration issues (empty = OK)."""
        issues: List[str] = []
        if not self.has_credentials:
            issues.append(
                "ALIBABA_ACCESS_KEY_ID / ALIBABA_ACCESS_KEY_SECRET not set — "
                "no Alibaba integrations will work."
            )
        if self.has_credentials and not (self.sls_project and self.sls_logstore):
            issues.append("SLS_PROJECT / SLS_LOGSTORE not set — log shipping disabled.")
        if self.has_credentials and not self.oss_endpoint:
            issues.append("OSS_ENDPOINT not set — report storage disabled.")
        return issues

    def summary(self) -> Dict[str, object]:
        """Structured configuration summary (safe to expose — no secrets)."""
        return {
            "region_id": self.region_id,
            "has_credentials": self.has_credentials,
            "integrations": self.enabled_map(),
            "sls": {"endpoint": self.sls_endpoint, "project": self.sls_project,
                    "logstore": self.sls_logstore},
            "oss": {"endpoint": self.oss_endpoint, "bucket": self.oss_bucket_name},
            "ecs": {"instance_id": self.ecs_instance_id},
            "cms": {"namespace": self.cms_namespace},
        }
