# ResQ Demo Scenarios

ResQ includes 5 realistic incident scenarios for demonstrating the multi-agent incident response system. Each scenario simulates a different type of production failure.

## Running a Scenario

```bash
python demo/run_demo.py --scenario <number>
```

Example:
```bash
python demo/run_demo.py --scenario 1
```

---

## Scenario 1: Database Connection Pool Exhaustion

**What happens:**
The target service's database connection pool becomes exhausted due to a sudden traffic spike. All available connections are in use, and new requests must wait or fail.

**Symptoms:**
- Increasing request latency (P99 spikes from ~100ms to 5000ms+)
- Connection timeout errors in logs
- Error rate increases as requests fail
- CPU usage spikes from connection waiting threads

**Root cause:**
Traffic surge exceeds the configured connection pool size (max 500 connections).

**Agent investigation:**
- Log Analyzer finds connection timeout errors and pool exhaustion messages
- Metric Monitor correlates latency spike with error rate increase
- Coordinator identifies DB connection pool as the bottleneck
- Runbook Executor suggests increasing pool size and adding connection timeouts

**Files involved:**
- `target/app.py` — SQLite database with connection pooling simulation

---

## Scenario 2: Cache Failure

**What happens:**
The in-memory cache fails, causing all requests to hit the database directly. This creates a cache miss storm that overwhelms the database.

**Symptoms:**
- Cache hit rate drops from ~80% to 0%
- Database query latency increases significantly
- Error rate spikes as DB becomes overloaded
- Memory usage may increase from uncached data

**Root cause:**
Cache service becomes unavailable, forcing all requests to bypass cache and hit the database directly.

**Agent investigation:**
- Log Analyzer finds cache miss errors and increased DB query times
- Metric Monitor shows cache hit rate dropping to 0%
- Coordinator identifies cache failure as the root cause
- Runbook Executor suggests restarting cache service and implementing fallback

**Files involved:**
- `target/app.py` — In-memory cache with TTL

---

## Scenario 3: Message Queue Failure

**What happens:**
The message queue connecting two services (Order Service → Notification Service) fails. Orders are processed but notifications are never sent.

**Symptoms:**
- Queue connection errors in logs
- Message backlog grows (queue size increases)
- Notification service stops processing messages
- Error rate increases as queue publishes fail

**Root cause:**
Message queue connection is lost, breaking communication between Order Service and Notification Service.

**Agent investigation:**
- Log Analyzer finds queue connection timeout and "consumer disconnected" errors
- Metric Monitor shows queue errors increasing and queue size growing
- Coordinator identifies message queue failure as the root cause
- Runbook Executor suggests restarting queue service and implementing retry logic

**Files involved:**
- `target/app.py` — Message queue simulation

---

## Scenario 4: Memory Leak

**What happens:**
A memory leak in the service causes gradual memory consumption increase. Eventually the service is killed by the OOM (Out of Memory) killer or crashes.

**Symptoms:**
- Memory usage steadily increases over time
- Service becomes slower as memory pressure increases
- Eventually service crashes or is killed
- Error rate spikes just before crash

**Root cause:**
A bug in the service causes memory to be allocated but never freed, leading to gradual exhaustion.

**Agent investigation:**
- Log Analyzer finds OOM kill messages and memory-related errors
- Metric Monitor shows memory usage trending upward until crash
- Coordinator identifies memory leak as the root cause
- Runbook Executor suggests restarting service and fixing the memory leak

**Files involved:**
- `target/app.py` — Memory leak simulation

---

## Scenario 5: External API Dependency Failure

**What happens:**
The service depends on an external API (e.g., payment gateway, shipping service) that becomes unavailable. All requests that require this external call fail or timeout.

**Symptoms:**
- External API timeout errors in logs
- Increased latency for endpoints that call the external API
- Error rate increases for affected endpoints
- Circuit breaker may trip, blocking all external calls

**Root cause:**
External third-party API becomes unavailable, causing cascading failures in dependent services.

**Agent investigation:**
- Log Analyzer finds external API timeout and connection refused errors
- Metric Monitor shows latency spike for specific endpoints
- Coordinator identifies external API failure as the root cause
- Runbook Executor suggests implementing circuit breaker and fallback responses

**Files involved:**
- `target/app.py` — External API call simulation

---

## Demo Tips

1. **Run each scenario separately** to show different incident types
2. **Watch the terminal UI** to see agents investigate in real-time
3. **Check the timeline** to see the sequence of events
4. **Review the post-mortem** for the final incident report
5. **Compare scenarios** to show how ResQ handles different failure types

## Customization

Each scenario can be customized by modifying:
- Failure timing (when the incident starts)
- Severity (how bad the failure is)
- Duration (how long the failure lasts)
- Recovery (how the service recovers)

Edit the scenario functions in `target/app.py` to adjust these parameters.
