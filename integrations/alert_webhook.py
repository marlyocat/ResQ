"""Alert webhook receiver for ResQ.

Receives alerts from monitoring systems (Grafana, PagerDuty, etc.)
and triggers incident investigation.
"""

import os
import json
import threading
from datetime import datetime
from typing import Optional, Dict, List, Callable
from flask import Flask, request, jsonify


class AlertWebhook:
    """Webhook server for receiving alerts."""

    def __init__(self, port: Optional[int] = None):
        self.port = port or int(os.getenv("RESQ_WEBHOOK_PORT", "5001"))
        self.app = Flask(__name__)
        self.handlers: List[Callable] = []
        self._setup_routes()

    def _setup_routes(self):
        """Setup webhook routes."""

        @self.app.route("/webhook/alert", methods=["POST"])
        def receive_alert():
            """Receive alert from monitoring system."""
            alert_data = request.json

            if not alert_data:
                return jsonify({"error": "No alert data"}), 400

            # Normalize alert format
            normalized = self._normalize_alert(alert_data)

            # Call all registered handlers
            for handler in self.handlers:
                try:
                    handler(normalized)
                except Exception as e:
                    print(f"Alert handler error: {e}")

            return jsonify({"status": "received", "alert_id": normalized.get("id")})

        @self.app.route("/webhook/health", methods=["GET"])
        def health():
            return jsonify({"status": "ok"})

    def _normalize_alert(self, alert_data: Dict) -> Dict:
        """Normalize alert from various formats."""
        # Grafana format
        if "title" in alert_data and "message" in alert_data:
            return {
                "id": alert_data.get("ruleId", alert_data.get("title")),
                "source": "grafana",
                "title": alert_data.get("title"),
                "message": alert_data.get("message"),
                "severity": alert_data.get("severity", "unknown"),
                "timestamp": datetime.utcnow().isoformat(),
                "labels": alert_data.get("labels", {}),
                "annotations": alert_data.get("annotations", {}),
            }

        # PagerDuty format
        if "messages" in alert_data:
            messages = alert_data.get("messages", [])
            if messages:
                msg = messages[0]
                return {
                    "id": msg.get("id"),
                    "source": "pagerduty",
                    "title": msg.get("summary"),
                    "message": msg.get("description"),
                    "severity": msg.get("severity", "unknown"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "labels": msg.get("labels", {}),
                }

        # Generic format
        return {
            "id": alert_data.get("id", alert_data.get("alert_id")),
            "source": alert_data.get("source", "unknown"),
            "title": alert_data.get("title", alert_data.get("summary")),
            "message": alert_data.get("message", alert_data.get("description")),
            "severity": alert_data.get("severity", "unknown"),
            "timestamp": alert_data.get("timestamp", datetime.utcnow().isoformat()),
            "labels": alert_data.get("labels", {}),
            "raw": alert_data,
        }

    def on_alert(self, handler: Callable):
        """Register an alert handler."""
        self.handlers.append(handler)

    def start(self, blocking: bool = False):
        """Start the webhook server."""
        if blocking:
            self.app.run(host="0.0.0.0", port=self.port)
        else:
            thread = threading.Thread(
                target=self.app.run,
                kwargs={"host": "0.0.0.0", "port": self.port},
                daemon=True,
            )
            thread.start()


class AlertManager:
    """Manages alerts and triggers investigations."""

    def __init__(self):
        self.alerts: List[Dict] = []
        self.webhook: Optional[AlertWebhook] = None
        self.investigation_callback: Optional[Callable] = None

    def setup_webhook(self, port: Optional[int] = None):
        """Setup webhook receiver."""
        self.webhook = AlertWebhook(port)
        self.webhook.on_alert(self._handle_alert)
        self.webhook.start(blocking=False)

    def _handle_alert(self, alert: Dict):
        """Handle incoming alert."""
        self.alerts.append(alert)
        print(f"[AlertManager] Received alert: {alert.get('title')}")

        if self.investigation_callback:
            self.investigation_callback(alert)

    def on_investigation(self, callback: Callable):
        """Register investigation callback."""
        self.investigation_callback = callback

    def get_recent_alerts(self, limit: int = 10) -> List[Dict]:
        """Get recent alerts."""
        return self.alerts[-limit:]

    def clear_alerts(self):
        """Clear all alerts."""
        self.alerts.clear()
