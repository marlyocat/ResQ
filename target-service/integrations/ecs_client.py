"""Alibaba Cloud ECS (Elastic Compute Service) client.

Provides infrastructure context: which compute instances exist and their
health/status. Uses the Tea-based alibabacloud_ecs20140526 SDK with real
DescribeInstances / DescribeInstanceStatus API calls.

Docs: https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-describeinstances
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger("flaskapp.ecs")

try:
    from alibabacloud_ecs20140526.client import Client as EcsClient
    from alibabacloud_ecs20140526 import models as ecs_models
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_tea_util import models as util_models
    ECS_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    ECS_SDK_AVAILABLE = False
    EcsClient = ecs_models = open_api_models = util_models = None


class ECSClient:
    """Queries ECS instances via the Alibaba Cloud OpenAPI."""

    def __init__(self, config):
        self.config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not ECS_SDK_AVAILABLE:
                raise ImportError(
                    "alibabacloud_ecs20140526 required: "
                    "pip install alibabacloud_ecs20140526"
                )
            api_config = open_api_models.Config(
                access_key_id=self.config.access_key_id,
                access_key_secret=self.config.access_key_secret,
            )
            api_config.endpoint = f"ecs.{self.config.region_id}.aliyuncs.com"
            self._client = EcsClient(api_config)
            logger.info("ECS client initialized: %s", api_config.endpoint)
        return self._client

    def list_instances(self, max_results: int = 50) -> List[Dict]:
        """DescribeInstances — list instances in the configured region."""
        client = self._get_client()
        request = ecs_models.DescribeInstancesRequest(
            region_id=self.config.region_id,
            max_results=max_results,
        )
        runtime = util_models.RuntimeOptions()
        response = client.describe_instances_with_options(request, runtime)

        instances = []
        body = response.body
        if body and body.instances and body.instances.instance:
            for inst in body.instances.instance:
                instances.append({
                    "instance_id": inst.instance_id,
                    "instance_name": inst.instance_name,
                    "status": inst.status,
                    "instance_type": inst.instance_type,
                    "region_id": inst.region_id,
                    "zone_id": inst.zone_id,
                    "public_ip": (inst.public_ip_address.ip_address
                                  if inst.public_ip_address else []),
                    "private_ip": (
                        inst.vpc_attributes.private_ip_address.ip_address
                        if inst.vpc_attributes and inst.vpc_attributes.private_ip_address
                        else []
                    ),
                    "creation_time": inst.creation_time,
                })
        return instances

    def instance_status(self, instance_ids: Optional[List[str]] = None) -> List[Dict]:
        """DescribeInstanceStatus — health/status for specific instances."""
        client = self._get_client()
        request = ecs_models.DescribeInstanceStatusRequest(
            region_id=self.config.region_id,
            instance_id=instance_ids,
        )
        runtime = util_models.RuntimeOptions()
        response = client.describe_instance_status_with_options(request, runtime)

        statuses = []
        body = response.body
        if body and body.instance_statuses and body.instance_statuses.instance_status:
            for s in body.instance_statuses.instance_status:
                statuses.append({
                    "instance_id": s.instance_id,
                    "status": s.status,
                })
        return statuses
