"""Alibaba Cloud OSS connector for ResQ.

Uploads incident reports to OSS for storage and retrieval.
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path


class OSSClient:
    """Client for Alibaba Cloud Object Storage Service."""

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        access_key_secret: Optional[str] = None,
        endpoint: Optional[str] = None,
        bucket_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.access_key_id = access_key_id or os.getenv("ALIBABA_ACCESS_KEY_ID")
        self.access_key_secret = access_key_secret or os.getenv("ALIBABA_ACCESS_KEY_SECRET")
        self.endpoint = endpoint or os.getenv("OSS_ENDPOINT")
        self.bucket_name = bucket_name or os.getenv("OSS_BUCKET_NAME", "resq-reports")
        self.region = region or os.getenv("ALIBABA_REGION_ID", "cn-hangzhou")

        self._client = None

    def _get_client(self):
        """Lazy-initialize OSS client."""
        if self._client is None:
            try:
                import oss2
                auth = oss2.Auth(self.access_key_id, self.access_key_secret)
                self._client = oss2.Bucket(auth, self.endpoint, self.bucket_name)
            except ImportError:
                raise ImportError("oss2 package required: pip install oss2")
        return self._client

    def upload_report(self, incident_id: str, report: Dict) -> str:
        """Upload an incident report to OSS."""
        client = self._get_client()

        # Create structured path: incidents/YYYY-MM-DD/incident_id.json
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"incidents/{date_str}/{incident_id}.json"

        # Serialize report
        report_json = json.dumps(report, indent=2, default=str)

        # Upload to OSS
        client.put_object(key, report_json)

        print(f"[OSS] Uploaded report: {key}")
        return key

    def upload_html_report(self, incident_id: str, html_content: str) -> str:
        """Upload an HTML report to OSS."""
        client = self._get_client()

        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"incidents/{date_str}/{incident_id}.html"

        client.put_object(key, html_content, headers={"Content-Type": "text/html"})

        print(f"[OSS] Uploaded HTML report: {key}")
        return key

    def get_report(self, incident_id: str, date: Optional[str] = None) -> Optional[Dict]:
        """Retrieve an incident report from OSS."""
        client = self._get_client()

        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        key = f"incidents/{date}/{incident_id}.json"

        try:
            result = client.get_object(key)
            content = result.read().decode("utf-8")
            return json.loads(content)
        except Exception as e:
            print(f"[OSS] Failed to retrieve report: {e}")
            return None

    def list_incidents(self, date: Optional[str] = None) -> List[str]:
        """List incident IDs for a given date."""
        client = self._get_client()

        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        prefix = f"incidents/{date}/"
        incidents = []

        for obj in oss2.ObjectIterator(client, prefix=prefix):
            if obj.key.endswith(".json"):
                incident_id = Path(obj.key).stem
                incidents.append(incident_id)

        return incidents

    def health_check(self) -> bool:
        """Check if OSS is accessible."""
        try:
            client = self._get_client()
            client.get_bucket_info()
            return True
        except Exception:
            return False
