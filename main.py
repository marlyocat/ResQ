"""ResQ — Multi-Agent Incident Response Swarm

Main entry point for running ResQ incident response simulations.

Usage:
    python main.py --incident demo/sample_incidents/high_cpu.json
    python main.py --sls-incident demo/sample_incidents/sls_incident.json
"""

import asyncio
import argparse
import json
import logging
import time
from typing import Dict
from dotenv import load_dotenv

load_dotenv()

from integrations.qwen_client import QwenClient
from integrations.alibaba_cloud import AlibabaCloudIntegration, SLS_SDK_AVAILABLE
from agents.log_analyzer import LogAnalyzer
from agents.metric_monitor import MetricMonitor
from agents.coordinator import Coordinator
from agents.runbook_executor import RunbookExecutor
from agents.postmortem_writer import PostMortemWriter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("resq")


class ResQSwarm:
    """Orchestrates the multi-agent incident response workflow."""

    def __init__(self, qwen_client: QwenClient, sls_client=None):
        self.log_analyzer = LogAnalyzer(qwen_client, sls_client=sls_client)
        self.metric_monitor = MetricMonitor(qwen_client)
        self.coordinator = Coordinator(qwen_client)
        self.runbook_executor = RunbookExecutor(qwen_client)
        self.postmortem_writer = PostMortemWriter(qwen_client)

    async def handle_incident(self, incident_data: dict) -> dict:
        """
        Run the full incident response workflow.

        Args:
            incident_data: Dict with 'logs' and/or 'sls_config' and 'metrics' keys

        Returns:
            Full incident results including post-mortem
        """
        start_time = time.time()
        results = {}

        # Phase 1: Parallel diagnosis
        logger.info("Phase 1: Parallel diagnosis (Log Analyzer + Metric Monitor)")
        log_result, metric_result = await asyncio.gather(
            self.log_analyzer.analyze(incident_data),
            self.metric_monitor.analyze(incident_data)
        )
        results["log_analyzer"] = log_result
        results["metric_monitor"] = metric_result

        # Phase 2: Coordinator arbitration
        logger.info("Phase 2: Coordinator arbitration")
        arbitration = await self.coordinator.arbitrate(
            log_hypotheses=log_result.get("hypotheses", []),
            metric_hypotheses=metric_result.get("hypotheses", [])
        )
        results["coordinator"] = arbitration

        # Phase 3: Remediation
        logger.info("Phase 3: Runbook execution")
        execution = await self.runbook_executor.execute(arbitration.get("action_plan", {}))
        results["runbook_executor"] = execution

        # Phase 4: Post-mortem
        logger.info("Phase 4: Post-mortem generation")
        postmortem = await self.postmortem_writer.generate_postmortem(results)
        results["postmortem"] = postmortem

        elapsed = time.time() - start_time
        results["metadata"] = {
            "total_time_seconds": round(elapsed, 2),
            "agents_used": 5,
            "log_source": log_result.get("log_source", "unknown")
        }

        logger.info(f"Incident handled in {elapsed:.2f}s")
        return results


async def main():
    parser = argparse.ArgumentParser(description="ResQ — Multi-Agent Incident Response Swarm")
    parser.add_argument("--incident", type=str, help="Path to incident JSON file (static logs)")
    parser.add_argument("--sls-incident", type=str,
                        help="Path to incident JSON file with SLS config (fetches live logs from Alibaba Cloud SLS)")
    args = parser.parse_args()

    qwen_client = QwenClient()

    if args.sls_incident:
        if not SLS_SDK_AVAILABLE:
            logger.error(
                "SLS SDK not installed. Install with: pip install aliyun-log-python-sdk"
            )
            return

        # Initialize Alibaba Cloud SLS integration
        alibaba = AlibabaCloudIntegration()
        if not alibaba.access_key_id or not alibaba.access_key_secret:
            logger.error(
                "Alibaba Cloud credentials not set. Set ALIBABA_ACCESS_KEY_ID and "
                "ALIBABA_ACCESS_KEY_SECRET environment variables."
            )
            return

        logger.info(f"SLS integration enabled (region: {alibaba.region_id})")

        with open(args.sls_incident, "r") as f:
            incident_data = json.load(f)

        # Validate SLS config in incident data
        if "sls_config" not in incident_data:
            logger.error(
                "SLS incident file must contain 'sls_config' with project, logstore, etc."
            )
            return

        swarm = ResQSwarm(qwen_client, sls_client=alibaba)
        results = await swarm.handle_incident(incident_data)

        output_file = f"demo/results_sls_{int(time.time())}.json"
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to {output_file}")
    elif args.incident:
        with open(args.incident, "r") as f:
            incident_data = json.load(f)

        swarm = ResQSwarm(qwen_client)
        results = await swarm.handle_incident(incident_data)

        output_file = f"demo/results_{int(time.time())}.json"
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to {output_file}")
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
