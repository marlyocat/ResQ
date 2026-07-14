# ResQ Integrations (investigator side)

The investigator-side integration layer. Two modules:

| Module | Purpose |
|--------|---------|
| [`qwen_client.py`](qwen_client.py) | Async client for **Qwen Cloud** (qwen-plus via the DashScope OpenAI-compatible API) — powers every agent's reasoning. |
| [`alibaba_cloud.py`](alibaba_cloud.py) | Reads production logs from **Alibaba Cloud SLS** (`GetLogs`) to feed the Log Analyzer when running `main.py --sls-incident`. |

> The deployable backend and its full **SLS / OSS / ECS / CMS** usage live in
> [`../target-service/`](../target-service/) — that is the "backend running on
> Alibaba Cloud." This layer is the investigator side (Qwen + SLS log reads).

## Configuration

Set these in `.env` (see [`../.env.example`](../.env.example)):

```bash
# Qwen Cloud (required — all agent reasoning)
QWEN_API_KEY=your_key_here
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# Alibaba Cloud SLS (optional — only for `main.py --sls-incident`, live log reads)
ALIBABA_ACCESS_KEY_ID=your_key
ALIBABA_ACCESS_KEY_SECRET=your_secret
ALIBABA_REGION_ID=ap-southeast-3
```

## Usage

### Qwen client (used by every agent)

```python
from integrations.qwen_client import QwenClient

qwen = QwenClient()                       # reads QWEN_API_KEY from env
result = await qwen.analyze_with_context(
    system_prompt="You are a senior SRE...",
    user_input="Analyze these logs...",
)
print(result["raw_response"])
```

### SLS log fetch (live incident mode)

```python
from integrations.alibaba_cloud import AlibabaCloudIntegration
from datetime import datetime

sls = AlibabaCloudIntegration(region_id="ap-southeast-3")
logs = await sls.fetch_logs_for_incident(
    project="my-project",
    logstore="app-logs",
    incident_time=datetime.utcnow(),
    levels=["ERROR", "CRITICAL"],
    lookback_minutes=30,
)
```

Run the full pipeline against live SLS logs:

```bash
python main.py --sls-incident demo/sample_incidents/sls_incident.json
```
