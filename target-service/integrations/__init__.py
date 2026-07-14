"""Alibaba Cloud integration layer for the Flask target service.

Real SDK-backed clients for the four Alibaba Cloud resources this app uses:

    - SLS  (Simple Log Service)   -> sls_client.SLSClient
    - OSS  (Object Storage)       -> oss_client.OSSClient
    - ECS  (Elastic Compute)      -> ecs_client.ECSClient
    - CMS  (Cloud Monitor)        -> cms_client.CMSClient

Configuration for all of them is centralized in config.AlibabaConfig.
"""

from .config import AlibabaConfig

__all__ = ["AlibabaConfig"]
