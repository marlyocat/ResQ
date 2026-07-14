"""Alibaba Cloud CMS (Cloud Monitor Service) client.

Retrieves metrics and alarm history for monitored resources (e.g. the ECS
instance this app runs on). Uses the Tea-based alibabacloud_cms20190101 SDK
with real DescribeMetricLast / DescribeAlertHistoryList API calls.

Docs: https://www.alibabacloud.com/help/en/cms/developer-reference/api-cms-2019-01-01-describemetriclast
"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("flaskapp.cms")

try:
    from alibabacloud_cms20190101.client import Client as CmsClient
    from alibabacloud_cms20190101 import models as cms_models
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_tea_util import models as util_models
    CMS_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    CMS_SDK_AVAILABLE = False
    CmsClient = cms_models = open_api_models = util_models = None


class CMSClient:
    """Queries Cloud Monitor metrics via the Alibaba Cloud OpenAPI."""

    def __init__(self, config):
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not CMS_SDK_AVAILABLE:
                raise ImportError(
                    "alibabacloud_cms20190101 required: "
                    "pip install alibabacloud_cms20190101"
                )
            api_config = open_api_models.Config(
                access_key_id=self.config.access_key_id,
                access_key_secret=self.config.access_key_secret,
            )
            api_config.endpoint = f"metrics.{self.config.region_id}.aliyuncs.com"
            self._client = CmsClient(api_config)
            logger.info("CMS client initialized: %s", api_config.endpoint)
        return self._client

    def get_metric_last(
        self,
        metric_name: str,
        namespace: Optional[str] = None,
        dimensions: Optional[Dict[str, str]] = None,
        period: str = "60",
    ) -> List[Dict]:
        """DescribeMetricLast — most recent datapoints for a metric.

        Args:
            metric_name: e.g. "CPUUtilization", "memory_usedutilization".
            namespace:   CMS namespace, defaults to config.cms_namespace.
            dimensions:  e.g. {"instanceId": "i-xxxx"}.
            period:      aggregation period in seconds.
        """
        client = self._get_client()
        request = cms_models.DescribeMetricLastRequest(
            namespace=namespace or self.config.cms_namespace,
            metric_name=metric_name,
            period=period,
        )
        if dimensions:
            request.dimensions = json.dumps(dimensions)

        runtime = util_models.RuntimeOptions()
        response = client.describe_metric_last_with_options(request, runtime)

        body = response.body
        if not body or not getattr(body, "datapoints", None):
            return []
        try:
            return json.loads(body.datapoints)
        except (json.JSONDecodeError, TypeError):
            logger.warning("CMS returned non-JSON datapoints: %r", body.datapoints)
            return []

    def get_alarm_history(
        self,
        metric_name: Optional[str] = None,
        namespace: Optional[str] = None,
        page_size: int = 20,
    ) -> List[Dict]:
        """DescribeAlertHistoryList — recent triggered alarms."""
        client = self._get_client()
        request = cms_models.DescribeAlertHistoryListRequest(
            namespace=namespace or self.config.cms_namespace,
            metric_name=metric_name,
            page_size=page_size,
        )
        runtime = util_models.RuntimeOptions()
        response = client.describe_alert_history_list_with_options(request, runtime)

        body = response.body
        alarms = []
        if body and getattr(body, "alarm_history_list", None):
            for a in body.alarm_history_list:
                alarms.append(a.to_map() if hasattr(a, "to_map") else a)
        return alarms
