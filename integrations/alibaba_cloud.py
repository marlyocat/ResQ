"""Alibaba Cloud SLS integration for ResQ (investigator side).

Fetches production logs from Alibaba Cloud SLS (Simple Log Service) to feed the
Log Analyzer agent, using the official aliyun-log-python-sdk. Used by
`main.py --sls-incident`.

Note: the deployable backend and its full SLS/OSS/ECS/CMS usage live in
`target-service/` (that is the "backend running on Alibaba Cloud"). This module
is the investigator-side SLS reader only.
"""

import os
import logging
from typing import Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Alibaba Cloud SLS SDK (official Python SDK for Simple Log Service)
try:
    from aliyun.log.logclient import LogClient
    from aliyun.log.getlogsrequest import GetLogsRequest
    SLS_SDK_AVAILABLE = True
except ImportError:
    SLS_SDK_AVAILABLE = False
    logger.warning(
        "Alibaba Cloud SLS SDK not installed. Install with: "
        "pip install aliyun-log-python-sdk"
    )


# SLS endpoint patterns per region
SLS_ENDPOINTS = {
    "cn-hangzhou": "cn-hangzhou.log.aliyuncs.com",
    "cn-shanghai": "cn-shanghai.log.aliyuncs.com",
    "cn-beijing": "cn-beijing.log.aliyuncs.com",
    "cn-shenzhen": "cn-shenzhen.log.aliyuncs.com",
    "cn-qingdao": "cn-qingdao.log.aliyuncs.com",
    "cn-zhangjiakou": "cn-zhangjiakou.log.aliyuncs.com",
    "cn-hongkong": "cn-hongkong.log.aliyuncs.com",
    "ap-southeast-1": "ap-southeast-1.log.aliyuncs.com",
    "ap-southeast-3": "ap-southeast-3.log.aliyuncs.com",
    "us-west-1": "us-west-1.log.aliyuncs.com",
    "us-east-1": "us-east-1.log.aliyuncs.com",
    "eu-central-1": "eu-central-1.log.aliyuncs.com",
}


class AlibabaCloudIntegration:
    """Reads production logs from Alibaba Cloud SLS for the Log Analyzer agent."""

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        access_key_secret: Optional[str] = None,
        region_id: str = "cn-hangzhou"
    ):
        self.access_key_id = access_key_id or os.getenv("ALIBABA_ACCESS_KEY_ID")
        self.access_key_secret = access_key_secret or os.getenv("ALIBABA_ACCESS_KEY_SECRET")
        self.region_id = region_id

        if not self.access_key_id or not self.access_key_secret:
            logger.warning(
                "Alibaba Cloud credentials not set. Set ALIBABA_ACCESS_KEY_ID and "
                "ALIBABA_ACCESS_KEY_SECRET environment variables for full functionality."
            )

        self._sls_client = None

    def _get_sls_endpoint(self) -> str:
        """Get the SLS endpoint for the configured region."""
        return SLS_ENDPOINTS.get(
            self.region_id,
            f"{self.region_id}.log.aliyuncs.com"
        )

    def _init_sls_client(self):
        """Initialize the SLS client using the official aliyun-log-python-sdk."""
        if not SLS_SDK_AVAILABLE:
            raise ImportError(
                "Alibaba Cloud SLS SDK required. Install with: pip install aliyun-log-python-sdk"
            )

        endpoint = self._get_sls_endpoint()
        self._sls_client = LogClient(
            endpoint,
            self.access_key_id,
            self.access_key_secret
        )
        logger.info(f"SLS client initialized: {endpoint}")

    # ==================== SLS (Log Service) Integration ====================

    async def query_logs(
        self,
        project: str,
        logstore: str,
        query: str = "*",
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        lines: int = 100,
        offset: int = 0
    ) -> List[dict]:
        """
        Query logs from Alibaba Cloud SLS (Simple Log Service).

        Uses the official aliyun-log-python-sdk to execute GetLogs API calls.

        Alibaba Cloud API: GetLogs
        Documentation: https://www.alibabacloud.com/help/en/sls/developer-reference/api-sls-2020-12-30-getlogs

        This is the primary log source for the Log Analyzer agent.

        Args:
            project: SLS project name
            logstore: LogStore name within the project
            query: SLS query string (supports SLS query syntax, default "*" for all)
            from_time: Start time for query window (defaults to 1 hour ago)
            to_time: End time for query window (defaults to now)
            lines: Maximum number of log lines to return (default 100)
            offset: Offset for pagination (default 0)

        Returns:
            List of log entries, each as a dict with timestamp, level, message, etc.
        """
        if not self._sls_client:
            self._init_sls_client()

        from_ts = int(from_time.timestamp()) if from_time else int((datetime.utcnow() - timedelta(hours=1)).timestamp())
        to_ts = int(to_time.timestamp()) if to_time else int(datetime.utcnow().timestamp())

        logger.info(
            f"SLS Query: project={project}, logstore={logstore}, "
            f"query='{query}', from={from_ts}, to={to_ts}, lines={lines}"
        )

        request = GetLogsRequest(
            project=project,
            logstore=logstore,
            fromTime=from_ts,
            toTime=to_ts,
            topic="",
            query=query,
            line=lines,
            offset=offset,
            reverse=True  # Newest first for incident analysis
        )

        try:
            response = self._sls_client.get_logs(request)
            logs = response.get_logs()

            # Parse log entries into structured format
            parsed_logs = []
            for log in logs:
                entry = {
                    "timestamp": log.get_time(),
                    "source": "sls",
                    "index": log.get_source(),
                }
                # Each log entry has key-value pairs from SLS
                for content in log.get_contents():
                    entry[content.get_key()] = content.get_value()

                # Normalize common fields
                if "timestamp" not in entry or entry["timestamp"] == log.get_time():
                    entry["timestamp"] = datetime.utcfromtimestamp(log.get_time()).isoformat()

                parsed_logs.append(entry)

            logger.info(f"SLS returned {len(parsed_logs)} log entries")
            return parsed_logs

        except Exception as e:
            logger.error(f"SLS query failed: project={project}, logstore={logstore}, error={e}")
            raise

    async def fetch_logs_for_incident(
        self,
        project: str,
        logstore: str,
        incident_time: datetime,
        services: Optional[List[str]] = None,
        levels: Optional[List[str]] = None,
        lookback_minutes: int = 30
    ) -> List[dict]:
        """
        Fetch logs relevant to a specific incident.

        High-level convenience method that builds the right SLS query
        based on incident context.

        Args:
            project: SLS project name
            logstore: LogStore name
            incident_time: When the incident was detected
            services: Optional list of service names to filter
            levels: Optional list of log levels to include (e.g., ["ERROR", "CRITICAL"])
            lookback_minutes: How far back to look from incident time

        Returns:
            List of relevant log entries
        """
        from_time = incident_time - timedelta(minutes=lookback_minutes)
        to_time = incident_time + timedelta(minutes=15)  # Include 15 min after for recovery signals

        # Build SLS query
        query_parts = []
        if levels:
            level_filter = " OR ".join(f"level:{level}" for level in levels)
            query_parts.append(f"({level_filter})")
        if services:
            service_filter = " OR ".join(f"service:{svc}" for svc in services)
            query_parts.append(f"({service_filter})")

        query = " AND ".join(query_parts) if query_parts else "*"

        return await self.query_logs(
            project=project,
            logstore=logstore,
            query=query,
            from_time=from_time,
            to_time=to_time,
            lines=500
        )


# ==================== Alibaba Cloud usage (investigator side) ====================
# This module reads logs from SLS to feed the Log Analyzer agent.
#
# To run with real Alibaba Cloud SLS:
# 1. Set ALIBABA_ACCESS_KEY_ID and ALIBABA_ACCESS_KEY_SECRET
# 2. Install the SLS SDK: pip install aliyun-log-python-sdk
# 3. Set region_id to match your deployment region
# 4. Create an SLS project + logstore and ship your app's logs there
#    (the target-service/ app does exactly this — see target-service/integrations/)
