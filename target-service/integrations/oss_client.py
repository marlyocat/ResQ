"""Alibaba Cloud OSS (Object Storage Service) client.

Stores and retrieves reports / artifacts produced by the app.
Adapted from ResQ's integrations/oss_client.py.

Uses the official oss2 SDK.
Docs: https://www.alibabacloud.com/help/en/oss/developer-reference/python-sdk
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("flaskapp.oss")

try:
    import oss2
    OSS_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    OSS_SDK_AVAILABLE = False
    oss2 = None


class OSSClient:
    """Client for Alibaba Cloud Object Storage Service."""

    def __init__(self, config):
        self.config = config
        self._bucket = None

    def _get_bucket(self):
        if self._bucket is None:
            if not OSS_SDK_AVAILABLE:
                raise ImportError("oss2 package required: pip install oss2")
            if not self.config.oss_endpoint:
                raise ValueError("OSS_ENDPOINT not configured")
            auth = oss2.Auth(self.config.access_key_id, self.config.access_key_secret)
            self._bucket = oss2.Bucket(
                auth, self.config.oss_endpoint, self.config.oss_bucket_name
            )
            logger.info(
                "OSS bucket initialized: %s (%s)",
                self.config.oss_bucket_name, self.config.oss_endpoint,
            )
        return self._bucket

    def upload_report(self, report_id: str, report: Dict) -> str:
        """Upload a JSON report. Returns the OSS object key."""
        bucket = self._get_bucket()
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"reports/{date_str}/{report_id}.json"
        bucket.put_object(key, json.dumps(report, indent=2, default=str))
        logger.info("OSS uploaded report: %s", key)
        return key

    def get_report(self, report_id: str, date: Optional[str] = None) -> Optional[Dict]:
        """Retrieve a JSON report by id (and optional YYYY-MM-DD date)."""
        bucket = self._get_bucket()
        date = date or datetime.utcnow().strftime("%Y-%m-%d")
        key = f"reports/{date}/{report_id}.json"
        try:
            result = bucket.get_object(key)
            return json.loads(result.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("OSS get_report failed for %s: %s", key, e)
            return None

    def list_reports(self, date: Optional[str] = None) -> List[str]:
        """List report ids stored for a given date (default: today, UTC)."""
        bucket = self._get_bucket()
        date = date or datetime.utcnow().strftime("%Y-%m-%d")
        prefix = f"reports/{date}/"
        ids = []
        for obj in oss2.ObjectIterator(bucket, prefix=prefix):
            if obj.key.endswith(".json"):
                ids.append(Path(obj.key).stem)
        return ids

    def health_check(self) -> bool:
        """Return True if the bucket is reachable."""
        try:
            self._get_bucket().get_bucket_info()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("OSS health_check failed: %s", e)
            return False
