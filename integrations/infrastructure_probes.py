"""Infrastructure probes for ResQ.

Probes for checking health of Redis, Kafka, PostgreSQL, and other infrastructure.
"""

import os
import socket
from typing import Optional, Dict, List
from datetime import datetime


class InfrastructureProbes:
    """Probes for infrastructure health checks."""

    def __init__(self):
        self.connections: Dict[str, object] = {}

    # ── Redis ────────────────────────────────────────────────────────

    def probe_redis(self, url: Optional[str] = None) -> Dict:
        """Check Redis health."""
        url = url or os.getenv("REDIS_URL", "redis://localhost:6379")

        try:
            import redis
            client = redis.Redis.from_url(url, socket_timeout=2)
            ping = client.ping()
            info = client.info("memory")

            return {
                "healthy": True,
                "ping": ping,
                "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
                "connected_clients": info.get("connected_clients", 0),
                "blocked_clients": info.get("blocked_clients", 0),
            }
        except ImportError:
            return {"healthy": False, "error": "redis package not installed"}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    # ── PostgreSQL ───────────────────────────────────────────────────

    def probe_postgresql(self, url: Optional[str] = None) -> Dict:
        """Check PostgreSQL health."""
        url = url or os.getenv("DATABASE_URL", "postgresql://localhost:5432/postgres")

        try:
            import psycopg2
            conn = psycopg2.connect(url, connect_timeout=2)
            cursor = conn.cursor()
            cursor.execute("SELECT version(), current_database(), current_user")
            version, database, user = cursor.fetchone()

            # Get active connections
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
            active_connections = cursor.fetchone()[0]

            cursor.execute("SELECT count(*) FROM pg_stat_activity")
            total_connections = cursor.fetchone()[0]

            cursor.close()
            conn.close()

            return {
                "healthy": True,
                "version": version,
                "database": database,
                "user": user,
                "active_connections": active_connections,
                "total_connections": total_connections,
            }
        except ImportError:
            return {"healthy": False, "error": "psycopg2 package not installed"}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    # ── Kafka ────────────────────────────────────────────────────────

    def probe_kafka(self, bootstrap_servers: Optional[str] = None) -> Dict:
        """Check Kafka health."""
        bootstrap_servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

        try:
            from kafka import KafkaAdminClient
            admin = KafkaAdminClient(
                bootstrap_servers=bootstrap_servers.split(","),
                request_timeout_ms=2000,
            )

            topics = admin.list_topics()
            consumer_groups = admin.list_consumer_groups()

            return {
                "healthy": True,
                "topics_count": len(topics),
                "topics": topics[:10],  # First 10 topics
                "consumer_groups_count": len(consumer_groups),
            }
        except ImportError:
            return {"healthy": False, "error": "kafka-python package not installed"}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    # ─ RabbitMQ ─────────────────────────────────────────────────────

    def probe_rabbitmq(self, url: Optional[str] = None) -> Dict:
        """Check RabbitMQ health."""
        url = url or os.getenv("RABBITMQ_URL", "http://localhost:15672")

        try:
            import requests
            response = requests.get(f"{url}/api/healthchecks/node", timeout=2)

            if response.status_code == 200:
                data = response.json()
                return {
                    "healthy": data.get("status") == "ok",
                    "checks": data.get("checks", []),
                }
            else:
                return {"healthy": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    # ── Generic TCP ──────────────────────────────────────────────────

    def probe_tcp(self, host: str, port: int, timeout: int = 2) -> Dict:
        """Check if a TCP port is reachable."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()

            return {
                "healthy": result == 0,
                "host": host,
                "port": port,
            }
        except Exception as e:
            return {"healthy": False, "host": host, "port": port, "error": str(e)}

    # ── HTTP Endpoint ────────────────────────────────────────────────

    def probe_http(self, url: str, timeout: int = 2) -> Dict:
        """Check if an HTTP endpoint is reachable."""
        try:
            import requests
            response = requests.get(url, timeout=timeout)

            return {
                "healthy": 200 <= response.status_code < 400,
                "status_code": response.status_code,
                "response_time_ms": round(response.elapsed.total_seconds() * 1000, 2),
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    # ── Multi-Probe ──────────────────────────────────────────────────

    def probe_all(self, config: Dict[str, str]) -> Dict[str, Dict]:
        """Probe multiple infrastructure components."""
        results = {}

        for name, url in config.items():
            if "redis" in name.lower():
                results[name] = self.probe_redis(url)
            elif "postgres" in name.lower() or "database" in name.lower():
                results[name] = self.probe_postgresql(url)
            elif "kafka" in name.lower():
                results[name] = self.probe_kafka(url)
            elif "rabbit" in name.lower():
                results[name] = self.probe_rabbitmq(url)
            elif url.startswith("http"):
                results[name] = self.probe_http(url)
            else:
                # Try TCP probe
                host, port = url.rsplit(":", 1)
                results[name] = self.probe_tcp(host, int(port))

        return results
