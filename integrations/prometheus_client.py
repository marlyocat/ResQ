"""Prometheus metrics connector for ResQ.

Connects to Prometheus to query real application metrics.
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict


class PrometheusClient:
    """Client for querying Prometheus metrics."""

    def __init__(
        self,
        url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.url = url or os.getenv("PROMETHEUS_URL", "http://localhost:9090")
        self.username = username or os.getenv("PROMETHEUS_USERNAME")
        self.password = password or os.getenv("PROMETHEUS_PASSWORD")
        self.session = requests.Session()

        if self.username and self.password:
            self.session.auth = (self.username, self.password)

    def query(self, promql: str, time: Optional[datetime] = None) -> Dict:
        """Execute an instant query."""
        params = {"query": promql}
        if time:
            params["time"] = time.timestamp()

        response = self.session.get(f"{self.url}/api/v1/query", params=params)
        response.raise_for_status()
        return response.json()

    def query_range(
        self,
        promql: str,
        start: datetime,
        end: datetime,
        step: str = "15s",
    ) -> Dict:
        """Execute a range query."""
        params = {
            "query": promql,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step,
        }

        response = self.session.get(f"{self.url}/api/v1/query_range", params=params)
        response.raise_for_status()
        return response.json()

    def get_metric(
        self,
        metric_name: str,
        labels: Optional[Dict[str, str]] = None,
        hours: int = 1,
    ) -> List[Dict]:
        """Get recent values for a metric."""
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items()) if labels else ""
        promql = f"{metric_name}{{{label_str}}}" if label_str else metric_name

        end = datetime.utcnow()
        start = end - timedelta(hours=hours)

        result = self.query_range(promql, start, end)

        if result.get("status") != "success":
            return []

        return result.get("data", {}).get("result", [])

    def get_error_rate(self, job: str, hours: int = 1) -> List[Dict]:
        """Get HTTP error rate for a job."""
        promql = f"""
        sum(rate(http_requests_total{{job="{job}",status=~"5.."}}[{hours}h]))
        /
        sum(rate(http_requests_total{{job="{job}"}}[{hours}h]))
        """
        return self.query_range(promql, datetime.utcnow() - timedelta(hours=hours), datetime.utcnow())

    def get_latency(self, job: str, percentile: float = 0.99, hours: int = 1) -> List[Dict]:
        """Get request latency percentile."""
        promql = f"""
        histogram_quantile({percentile},
            sum(rate(http_request_duration_seconds_bucket{{job="{job}"}}[5m])) by (le)
        )
        """
        return self.query_range(promql, datetime.utcnow() - timedelta(hours=hours), datetime.utcnow())

    def health_check(self) -> bool:
        """Check if Prometheus is reachable."""
        try:
            response = self.session.get(f"{self.url}/-/healthy")
            return response.status_code == 200
        except Exception:
            return False
