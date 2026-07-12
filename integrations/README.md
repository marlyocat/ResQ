# ResQ Integrations

Real integration layer for connecting ResQ to production applications.

## Overview

ResQ can now connect to real infrastructure:

```
Your App → SLS/Prometheus → ResQ Agents
       → GitHub/Local Repo → Source Indexer
       → Redis/Kafka/Postgres → Infrastructure Probes
       → Grafana/PagerDuty → Alert Webhook
```

## Setup

### 1. Environment Variables

Create `.env` file:

```bash
# Qwen API (required)
QWEN_API_KEY=your_key_here
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# SLS Logs (Alibaba Cloud)
ALIBABA_ACCESS_KEY_ID=your_key
ALIBABA_ACCESS_KEY_SECRET=your_secret
ALIBABA_REGION_ID=cn-hangzhou
SLS_PROJECT=your-project
SLS_LOGSTORE=your-logstore

# Prometheus Metrics
PROMETHEUS_URL=http://localhost:9090
PROMETHEUS_USERNAME=  # optional
PROMETHEUS_PASSWORD=  # optional

# Source Code (choose one)
SOURCE_LOCAL_PATH=/path/to/your/repo
# OR
SOURCE_GITHUB_URL=https://github.com/yourorg/yourapp
GITHUB_TOKEN=your_token  # for private repos

# Infrastructure (optional)
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql://user:pass@localhost:5432/db
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
RABBITMQ_URL=http://localhost:15672

# Webhook
RESQ_WEBHOOK_PORT=5001
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Basic Integration

```python
from integrations.config import ResQConfig
from integrations.prometheus_client import PrometheusClient
from integrations.source_indexer import SourceIndexer
from integrations.infrastructure_probes import InfrastructureProbes

# Load config
config = ResQConfig()

# Connect to Prometheus
prometheus = PrometheusClient(**config.prometheus_config)
metrics = prometheus.get_error_rate("my-app")

# Index source code
indexer = SourceIndexer(
    local_path=config.source_local_path,
    github_url=config.source_github_url,
    github_token=config.source_github_token,
)
indexer.index_local_repo()  # or indexer.index_github_repo()

# Probe infrastructure
probes = InfrastructureProbes()
redis_health = probes.probe_redis(config.redis_url)
db_health = probes.probe_postgresql(config.database_url)
```

### Alert Webhook

```python
from integrations.alert_webhook import AlertManager

manager = AlertManager()
manager.setup_webhook(port=5001)

def on_incident(alert):
    print(f"Incident: {alert['title']}")
    # Trigger ResQ investigation

manager.on_investigation(on_incident)
```

### Configuration Validation

```python
config = ResQConfig()
issues = config.validate()
if issues:
    print("Configuration issues:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("Configuration valid!")
    print(config.summary())
```

### OSS Report Storage

```python
from integrations.oss_client import OSSClient

# Initialize OSS client
oss = OSSClient()

# Upload incident report
report = {
    "incident_id": "INC-2026-001",
    "root_cause": "Database connection pool exhaustion",
    "findings": [...],
    "action_plan": [...],
}
key = oss.upload_report("INC-2026-001", report)
# Returns: incidents/2026-07-12/INC-2026-001.json

# Retrieve report
report = oss.get_report("INC-2026-001", date="2026-07-12")

# List all incidents for a date
incidents = oss.list_incidents("2026-07-12")
```

## Integration Status

| Integration | Status | Description |
|------------|--------|-------------|
| SLS Logs | ✓ Ready | Alibaba Cloud Log Service |
| Prometheus | ✓ Ready | Metrics collection |
| Source Indexer | ✓ Ready | Local + GitHub repos |
| Redis Probe | ✓ Ready | Cache health checks |
| PostgreSQL Probe | ✓ Ready | Database health checks |
| Kafka Probe | ✓ Ready | Message queue health |
| RabbitMQ Probe | ✓ Ready | Message broker health |
| Alert Webhook | ✓ Ready | Grafana, PagerDuty, etc. |
| OSS Storage | ✓ Ready | Report storage to Alibaba Cloud OSS |

## Next Steps

The agents need to be updated to use these integrations instead of the demo app. This will allow ResQ to:

1. Query real metrics from Prometheus
2. Read actual source code when analyzing errors
3. Check infrastructure health (Redis, DB, Kafka)
4. Receive real alerts from monitoring systems
