"""Helper to start Redis locally for the demo.

Usage:
    python demo/start_redis.py

This will:
1. Check if Redis is already running
2. If not, try to start it (requires redis-server in PATH)
3. Verify the connection
"""

import subprocess
import sys
import time

try:
    import redis
    client = redis.Redis(host='localhost', port=6379, socket_timeout=1)
    client.ping()
    print("✓ Redis is already running")
    sys.exit(0)
except (redis.ConnectionError, ImportError):
    pass

print("Starting Redis...")

# Try common Redis startup commands
commands = [
    ["redis-server", "--daemonize", "yes"],
    ["docker", "run", "-d", "-p", "6379:6379", "--name", "resq-redis", "redis"],
]

started = False
for cmd in commands:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"✓ Started Redis with: {' '.join(cmd)}")
            started = True
            break
    except (subprocess.TimeoutExpired, FileNotFoundError):
        continue

if not started:
    print("✗ Could not start Redis automatically.")
    print()
    print("Install Redis manually:")
    print("  Windows: https://github.com/tporadowski/redis/releases")
    print("  macOS:   brew install redis")
    print("  Linux:   sudo apt-get install redis-server")
    print()
    print("Or use Docker:")
    print("  docker run -d -p 6379:6379 redis")
    sys.exit(1)

# Wait for Redis to be ready
time.sleep(2)
try:
    client = redis.Redis(host='localhost', port=6379, socket_timeout=1)
    client.ping()
    print("✓ Redis is ready")
except redis.ConnectionError:
    print("✗ Redis started but not responding")
    sys.exit(1)
