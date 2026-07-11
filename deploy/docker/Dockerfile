FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Environment variables (set via docker-compose or -e flags)
# QWEN_API_KEY, ALIBABA_ACCESS_KEY_ID, ALIBABA_ACCESS_KEY_SECRET

CMD ["python", "main.py", "--incident", "demo/sample_incidents/high_cpu.json"]
