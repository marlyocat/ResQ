"""Alibaba Cloud SLS (Simple Log Service) client.

Two responsibilities:

1. Ship this app's structured logs to an SLS LogStore in near real time
   (PutLogs API), via a non-blocking background flush thread so request
   latency is never gated on the network.
2. Query logs back from SLS (GetLogs API) for the /api/logs endpoint.

Uses the official aliyun-log-python-sdk.
Docs: https://www.alibabacloud.com/help/en/sls/developer-reference/
"""

import atexit
import logging
import queue
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger("flaskapp.sls")

try:
    from aliyun.log import LogClient, LogItem, PutLogsRequest, GetLogsRequest
    SLS_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional dependency
    SLS_SDK_AVAILABLE = False
    LogClient = LogItem = PutLogsRequest = GetLogsRequest = None


class SLSClient:
    """Ships logs to and queries logs from Alibaba Cloud SLS."""

    def __init__(self, config):
        self.config = config
        self._client = None
        self._enabled = config.sls_enabled and SLS_SDK_AVAILABLE

        # Background shipping pipeline
        self._buffer: "queue.Queue[dict]" = queue.Queue(maxsize=10000)
        self._flush_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._batch_size = 100
        self._flush_interval = 2.0  # seconds
        self._dropped = 0
        self._shipped = 0

        if config.sls_enabled and not SLS_SDK_AVAILABLE:
            logger.warning(
                "SLS configured but aliyun-log-python-sdk not installed. "
                "Install with: pip install aliyun-log-python-sdk"
            )

    # ── Lifecycle ───────────────────────────────────────────────────────
    def _get_client(self):
        if self._client is None:
            if not SLS_SDK_AVAILABLE:
                raise ImportError(
                    "aliyun-log-python-sdk required: pip install aliyun-log-python-sdk"
                )
            self._client = LogClient(
                self.config.sls_endpoint,
                self.config.access_key_id,
                self.config.access_key_secret,
            )
            logger.info("SLS client initialized: %s", self.config.sls_endpoint)
        return self._client

    def start(self):
        """Start the background flush thread (idempotent)."""
        if not self._enabled or self._flush_thread is not None:
            return
        self._flush_thread = threading.Thread(
            target=self._flush_loop, name="sls-flush", daemon=True
        )
        self._flush_thread.start()
        atexit.register(self.stop)
        logger.info("SLS log shipping started")

    def stop(self):
        """Flush remaining logs and stop the background thread."""
        if self._flush_thread is None:
            return
        self._stop.set()
        self._flush_thread.join(timeout=5)
        self._drain_and_ship()  # best-effort final flush

    # ── Shipping (PutLogs) ──────────────────────────────────────────────
    def ship(self, record: Dict[str, str]):
        """Enqueue a structured log record for shipping. Never blocks/raises."""
        if not self._enabled:
            return
        try:
            self._buffer.put_nowait(record)
        except queue.Full:
            self._dropped += 1  # shed load rather than block the request path

    def _flush_loop(self):
        while not self._stop.is_set():
            time.sleep(self._flush_interval)
            self._drain_and_ship()

    def _drain_and_ship(self):
        batch: List[dict] = []
        while len(batch) < self._batch_size:
            try:
                batch.append(self._buffer.get_nowait())
            except queue.Empty:
                break
        if not batch:
            return
        try:
            self._put_logs(batch)
            self._shipped += len(batch)
        except Exception as e:  # noqa: BLE001 - never let logging crash the app
            logger.error("SLS put_logs failed (%d records lost): %s", len(batch), e)
            self._dropped += len(batch)

    def _put_logs(self, records: List[dict]):
        client = self._get_client()
        log_items = []
        for rec in records:
            item = LogItem()
            ts = rec.pop("_epoch", None)
            item.set_time(int(ts) if ts is not None else int(time.time()))
            item.set_contents([(str(k), str(v)) for k, v in rec.items()])
            log_items.append(item)

        request = PutLogsRequest(
            project=self.config.sls_project,
            logstore=self.config.sls_logstore,
            topic=self.config.sls_topic,
            source=self.config.sls_source or None,
            logitems=log_items,
        )
        client.put_logs(request)

    # ── Querying (GetLogs) ──────────────────────────────────────────────
    def query(
        self,
        query: str = "*",
        lookback_minutes: int = 30,
        lines: int = 100,
    ) -> List[dict]:
        """Query recent logs back from SLS. Raises on API/config errors."""
        if not SLS_SDK_AVAILABLE:
            raise ImportError("aliyun-log-python-sdk not installed")
        if not (self.config.sls_project and self.config.sls_logstore):
            raise ValueError("SLS_PROJECT / SLS_LOGSTORE not configured")

        client = self._get_client()
        to_ts = int(datetime.utcnow().timestamp())
        from_ts = int((datetime.utcnow() - timedelta(minutes=lookback_minutes)).timestamp())

        request = GetLogsRequest(
            project=self.config.sls_project,
            logstore=self.config.sls_logstore,
            fromTime=from_ts,
            toTime=to_ts,
            topic="",
            query=query,
            line=lines,
            offset=0,
            reverse=True,  # newest first
        )
        response = client.get_logs(request)

        results: List[dict] = []
        for log in response.get_logs():
            entry = {"_time": datetime.utcfromtimestamp(log.get_time()).isoformat() + "Z"}
            for content in log.get_contents():
                entry[content.get_key()] = content.get_value()
            results.append(entry)
        return results

    # ── Introspection ───────────────────────────────────────────────────
    def stats(self) -> Dict[str, object]:
        return {
            "enabled": self._enabled,
            "sdk_available": SLS_SDK_AVAILABLE,
            "shipped": self._shipped,
            "dropped": self._dropped,
            "queued": self._buffer.qsize(),
        }


class SLSLogHandler(logging.Handler):
    """A logging.Handler that forwards records to SLS via SLSClient.ship()."""

    def __init__(self, sls_client: SLSClient):
        super().__init__()
        self.sls_client = sls_client

    def emit(self, record: logging.LogRecord):
        try:
            payload = {
                "_epoch": int(record.created),
                "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            # Attach any structured extras passed via logger(..., extra={"fields": {...}})
            fields = getattr(record, "fields", None)
            if isinstance(fields, dict):
                for k, v in fields.items():
                    payload[k] = v
            self.sls_client.ship(payload)
        except Exception:  # noqa: BLE001 - handler must never raise
            self.handleError(record)
