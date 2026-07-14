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
from core.report_generator import ReportGenerator
from core.baseline import SingleAgentBaseline, score_run, build_comparison
from core.communication import MessageBus
from core.negotiation import run_negotiation_round

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("resq")


class ResQSwarm:
    """Orchestrates the multi-agent incident response workflow."""

    def __init__(self, qwen_client: QwenClient, sls_client=None, negotiate: bool = True):
        self.log_analyzer = LogAnalyzer(qwen_client, sls_client=sls_client)
        self.metric_monitor = MetricMonitor(qwen_client)
        self.coordinator = Coordinator(qwen_client)
        self.runbook_executor = RunbookExecutor(qwen_client)
        self.postmortem_writer = PostMortemWriter(qwen_client)
        self.negotiate = negotiate  # run the inter-agent negotiation round
        self.message_bus = MessageBus()

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

        log_hypotheses = log_result.get("hypotheses", [])
        metric_hypotheses = metric_result.get("hypotheses", [])

        # Phase 1.5: Inter-agent negotiation (dialogue to resolve disagreements)
        if self.negotiate:
            logger.info("Phase 1.5: Inter-agent negotiation")
            log_hypotheses, metric_hypotheses, dialogue = await run_negotiation_round(
                self.log_analyzer, self.metric_monitor,
                log_hypotheses, metric_hypotheses,
                message_bus=self.message_bus,
            )
            results["negotiation"] = {
                "dialogue": dialogue,
                "revised_log_hypotheses": log_hypotheses,
                "revised_metric_hypotheses": metric_hypotheses,
                "message_log": self.message_bus.get_message_log(),
            }
            logger.info(
                "Negotiation outcome: disagreement=%s converged=%s",
                dialogue["disagreement_detected"], dialogue["converged_after_negotiation"],
            )

        # Phase 2: Coordinator arbitration
        logger.info("Phase 2: Coordinator arbitration")
        arbitration = await self.coordinator.arbitrate(
            log_hypotheses=log_hypotheses,
            metric_hypotheses=metric_hypotheses,
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


BASELINE_ACC_PATH = "demo/baseline_all.json"


def _render_incident_block(incident_id: str, comparison: dict) -> str:
    """Render one incident's 3-way comparison as a markdown subsection."""
    s = comparison["single_agent"]
    n = comparison["multi_agent_naive"]
    m = comparison["multi_agent_negotiated"]
    d = comparison["deltas"]
    dlg = comparison.get("negotiation_dialogue", {})

    def row(label, key):
        return f"| {label} | {s[key]} | {n[key]} | {m[key]} | {d.get(key, '—')} |"

    if dlg:
        resolved = "resolved correctly" if m["diagnostic_accuracy"] == 1.0 and \
            m["diagnostic_accuracy"] > n["diagnostic_accuracy"] else (
            "unchanged" if m["diagnostic_accuracy"] == n["diagnostic_accuracy"] else "changed")
        conflict_note = (
            f"*Agents initially disagreed on the root cause: "
            f"**{dlg.get('disagreement_detected', '—')}**. "
            f"Diagnostic accuracy: naive arbitration **{n['diagnostic_accuracy']}** "
            f"→ after negotiation **{m['diagnostic_accuracy']}** ({resolved}).*"
        )
    else:
        conflict_note = ""

    return "\n".join([
        f"### {incident_id} — ground truth: {comparison['ground_truth_root_cause']}",
        "",
        conflict_note,
        "",
        "| Metric | Single-Agent | Multi (naive) | Multi (negotiated) | Δ (negot − single) |",
        "|--------|:------------:|:-------------:|:------------------:|:------------------:|",
        row("Diagnostic Accuracy (0–1)", "diagnostic_accuracy"),
        row("Hypotheses Generated", "hypotheses_generated"),
        row("Evidence Quality (grounded claims)", "evidence_quality"),
        row("Post-Mortem Completeness (0–1)", "postmortem_completeness"),
        row("Time to Diagnosis (s)", "time_to_diagnosis_s"),
        "",
        f"- **Single-agent identified:** {s['identified_root_cause'] or '(none)'}",
        f"- **Multi-agent (naive) identified:** {n['identified_root_cause'] or '(none)'}",
        f"- **Multi-agent (negotiated) identified:** {m['identified_root_cause'] or '(none)'}",
        "",
    ])


def _render_results_section(accumulator: dict) -> str:
    """Render the full Results section body from all accumulated incidents."""
    intro = (
        "*Generated by `python main.py --baseline-comparison <incident.json>`. Each incident "
        "runs the identical logs+metrics through a one-call single-agent baseline and the ResQ "
        "multi-agent swarm, scored on identical metrics.*"
    )
    blocks = [_render_incident_block(iid, comp) for iid, comp in accumulator.items()]
    return intro + "\n\n" + "\n".join(blocks)


def _update_results_doc(incident_id: str, comparison: dict,
                        doc_path: str = "docs/baseline_comparison.md",
                        acc_path: str = BASELINE_ACC_PATH):
    """Accumulate this incident's result and re-render the '## Results' section (idempotent per incident)."""
    import os
    acc = {}
    if os.path.exists(acc_path):
        try:
            with open(acc_path, "r", encoding="utf-8") as f:
                acc = json.load(f)
        except (json.JSONDecodeError, OSError):
            acc = {}
    acc[incident_id] = comparison
    with open(acc_path, "w", encoding="utf-8") as f:
        json.dump(acc, f, indent=2)

    rendered = _render_results_section(acc)
    if not os.path.exists(doc_path):
        return
    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    marker = "## Results"
    start = content.find(marker)
    if start == -1:
        content = content.rstrip() + f"\n\n## Results\n\n{rendered}\n"
    else:
        after = content.find("\n## ", start + len(marker))
        head = content[:start + len(marker)]
        tail = content[after:] if after != -1 else ""
        content = f"{head}\n\n{rendered}\n\n{tail.lstrip(chr(10))}" if tail else f"{head}\n\n{rendered}\n"

    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Updated results doc: {doc_path}")


async def run_baseline_comparison(incident_path: str):
    """Run the same incident through single-agent and multi-agent pipelines and score both."""
    import os
    with open(incident_path, "r") as f:
        incident_data = json.load(f)

    incident_id = incident_data.get("incident_id", os.path.basename(incident_path))
    ground_truth = incident_data.get("ground_truth", {})
    if not ground_truth.get("keywords"):
        logger.warning(
            "Incident has no 'ground_truth.keywords' — diagnostic accuracy cannot be scored."
        )

    qwen_client = QwenClient()

    # 1. Single-agent baseline
    logger.info("Running SINGLE-AGENT baseline (one Qwen call)...")
    single_agent = SingleAgentBaseline(qwen_client)
    t0 = time.time()
    single_out = await single_agent.handle_incident(incident_data)
    single_elapsed = time.time() - t0
    single_score = score_run("single_agent", single_out, single_elapsed, ground_truth)

    # 2. Multi-agent swarm WITHOUT negotiation (naive arbitration)
    logger.info("Running MULTI-AGENT swarm (naive arbitration, no negotiation)...")
    swarm_naive = ResQSwarm(qwen_client, negotiate=False)
    t0 = time.time()
    naive_out = await swarm_naive.handle_incident(incident_data)
    naive_elapsed = time.time() - t0
    naive_score = score_run("multi_agent_naive", naive_out, naive_elapsed, ground_truth)

    # 3. Multi-agent swarm WITH inter-agent negotiation
    logger.info("Running MULTI-AGENT swarm (with negotiation round)...")
    swarm_negotiated = ResQSwarm(qwen_client, negotiate=True)
    t0 = time.time()
    negotiated_out = await swarm_negotiated.handle_incident(incident_data)
    negotiated_elapsed = time.time() - t0
    negotiated_score = score_run("multi_agent_negotiated", negotiated_out,
                                 negotiated_elapsed, ground_truth)
    dialogue = negotiated_out.get("negotiation", {}).get("dialogue", {})

    comparison = build_comparison(single_score, naive_score, negotiated_score, ground_truth)
    comparison["negotiation_dialogue"] = dialogue

    # Persist artifacts first, so a console/encoding hiccup can't lose results.
    out_json = f"demo/baseline_results_{int(time.time())}.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)
    logger.info(f"Comparison saved to {out_json}")
    _update_results_doc(incident_id, comparison)

    # Console table (ASCII-only for Windows cp1252 consoles).
    print("\n" + "=" * 82)
    print("  BASELINE COMPARISON -- Single vs Multi-Agent (naive) vs Multi-Agent (negotiated)")
    print("=" * 82)
    print(f"  Ground-truth root cause: {comparison['ground_truth_root_cause']}")
    print(f"  Negotiation: disagreement={dialogue.get('disagreement_detected')}, "
          f"converged={dialogue.get('converged_after_negotiation')}")
    print("-" * 82)
    print(f"  {'Metric':<32}{'Single':>11}{'Multi-naive':>13}{'Multi-negot':>13}{'Delta':>10}")
    print("-" * 82)
    labels = [
        ("Diagnostic Accuracy (0-1)", "diagnostic_accuracy"),
        ("Hypotheses Generated", "hypotheses_generated"),
        ("Evidence Quality", "evidence_quality"),
        ("Post-Mortem Completeness (0-1)", "postmortem_completeness"),
        ("Time to Diagnosis (s)", "time_to_diagnosis_s"),
    ]
    for label, key in labels:
        print(f"  {label:<32}{single_score[key]:>11}{naive_score[key]:>13}"
              f"{negotiated_score[key]:>13}{comparison['deltas'][key]:>10}")
    print("=" * 82 + "\n")

    return comparison


async def main():
    parser = argparse.ArgumentParser(description="ResQ — Multi-Agent Incident Response Swarm")
    parser.add_argument("--incident", type=str, help="Path to incident JSON file (static logs)")
    parser.add_argument("--sls-incident", type=str,
                        help="Path to incident JSON file with SLS config (fetches live logs from Alibaba Cloud SLS)")
    parser.add_argument("--baseline-comparison", type=str, nargs="?",
                        const="demo/sample_incidents/high_cpu.json",
                        help="Run single-agent vs multi-agent comparison on an incident JSON "
                             "(default: demo/sample_incidents/high_cpu.json)")
    args = parser.parse_args()

    if args.baseline_comparison:
        await run_baseline_comparison(args.baseline_comparison)
        return

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

        # Generate HTML incident report
        rg = ReportGenerator()
        report_path = "demo/incident_report.html"
        rg.generate(incident_data, results, report_path)
        logger.info(f"Incident report generated: {report_path}")
    elif args.incident:
        with open(args.incident, "r") as f:
            incident_data = json.load(f)

        swarm = ResQSwarm(qwen_client)
        results = await swarm.handle_incident(incident_data)

        output_file = f"demo/results_{int(time.time())}.json"
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to {output_file}")

        # Generate HTML incident report
        rg = ReportGenerator()
        report_path = "demo/incident_report.html"
        rg.generate(incident_data, results, report_path)
        logger.info(f"Incident report generated: {report_path}")
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
