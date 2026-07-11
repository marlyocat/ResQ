"""ResQ — Multi-Agent Incident Response Swarm

Main entry point for running ResQ incident response simulations.

Usage:
    python main.py --incident demo/sample_incidents/high_cpu.json
    python main.py --sls-incident demo/sample_incidents/sls_incident.json
    python main.py --baseline-comparison
"""

import asyncio
import argparse
import json
import logging
import time
from typing import Dict

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


async def run_baseline_comparison():
    """
    Run single-agent vs multi-agent comparison on the same incident.
    
    This is the key experiment demonstrating the value of multi-agent collaboration.
    """
    logger.info("=== BASELINE COMPARISON: Single-Agent vs Multi-Agent ===")
    
    # Load sample incident
    with open("demo/sample_incidents/high_cpu.json", "r") as f:
        incident_data = json.load(f)

    # === Single-Agent Baseline ===
    logger.info("Running single-agent baseline...")
    single_start = time.time()
    
    qwen_client = QwenClient()
    combined_prompt = """You are an incident response expert. Analyze the following logs AND metrics 
    to identify the root cause and propose a remediation plan."""
    
    combined_input = f"LOGS:\n{incident_data.get('logs', '')}\n\nMETRICS:\n{incident_data.get('metrics', '')}"
    
    single_response = await qwen_client.analyze_with_context(
        system_prompt=combined_prompt,
        user_input=combined_input
    )
    single_time = time.time() - single_start

    # === Multi-Agent (ResQ) ===
    logger.info("Running multi-agent ResQ swarm...")
    swarm = ResQSwarm(qwen_client)
    swarm_start = time.time()
    swarm_result = await swarm.handle_incident(incident_data)
    swarm_time = time.time() - swarm_start

    # === Comparison ===
    comparison = {
        "single_agent": {
            "time_seconds": round(single_time, 2),
            "response_length": len(single_response.get("raw_response", "")),
            "response": single_response.get("raw_response", "")[:500] + "..."
        },
        "multi_agent_resq": {
            "time_seconds": round(swarm_time, 2),
            "agents_used": 5,
            "hypotheses_generated": (
                len(swarm_result.get("log_analyzer", {}).get("hypotheses", [])) +
                len(swarm_result.get("metric_monitor", {}).get("hypotheses", []))
            ),
            "conflict_resolved": "coordinator_arbitration" in str(swarm_result.get("coordinator", {}))
        }
    }

    logger.info("\n" + "=" * 60)
    logger.info("BASELINE COMPARISON RESULTS")
    logger.info("=" * 60)
    logger.info(f"Single-Agent Time: {single_time:.2f}s")
    logger.info(f"Multi-Agent Time:  {swarm_time:.2f}s")
    logger.info(f"Multi-Agent Hypotheses: {comparison['multi_agent_resq']['hypotheses_generated']}")
    logger.info("=" * 60)

    # Save comparison
    with open("docs/baseline_comparison_results.json", "w") as f:
        json.dump(comparison, f, indent=2)
    
    logger.info("Results saved to docs/baseline_comparison_results.json")
    return comparison


async def main():
    parser = argparse.ArgumentParser(description="ResQ — Multi-Agent Incident Response Swarm")
    parser.add_argument("--incident", type=str, help="Path to incident JSON file (static logs)")
    parser.add_argument("--sls-incident", type=str,
                        help="Path to incident JSON file with SLS config (fetches live logs from Alibaba Cloud SLS)")
    parser.add_argument("--baseline-comparison", action="store_true",
                        help="Run single-agent vs multi-agent comparison")
    args = parser.parse_args()

    qwen_client = QwenClient()

    if args.baseline_comparison:
        await run_baseline_comparison()
    elif args.sls_incident:
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
