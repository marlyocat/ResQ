"""ResQ Demo - single command that runs everything.

Usage:
    python demo/run_demo.py --scenario <1-5>

Scenarios:
    1 - Database Connection Pool Exhaustion
    2 - Cache Failure
    3 - Message Queue Failure
    4 - Memory Leak
    5 - External API Dependency Failure

Starts the target service, waits, triggers the incident, and shows
the terminal UI with the full agent investigation.
"""

import threading
import time
import sys
import os
import subprocess
import argparse

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCENARIOS = {
    1: "Database Connection Pool Exhaustion",
    2: "Cache Failure",
    3: "Message Queue Failure",
    4: "Memory Leak",
    5: "External API Dependency Failure",
}


def start_target_service(scenario):
    """Start the target Flask service in a background thread."""
    subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "..", "target", "app.py"),
         "--scenario", str(scenario)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_load_sim(delay=12):
    """Start the load simulator after a delay."""
    time.sleep(delay)
    subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "load_sim.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main():
    parser = argparse.ArgumentParser(description="ResQ Demo")
    parser.add_argument("--scenario", type=int, default=1, choices=[1, 2, 3, 4, 5],
                        help="Scenario number (1-5)")
    args = parser.parse_args()
    scenario = args.scenario

    print()
    print("  " + "=" * 50)
    print("  ResQ - Multi-Agent Incident Response")
    print("  " + "=" * 50)
    print(f"  Scenario {scenario}: {SCENARIOS[scenario]}")
    print("  " + "=" * 50)
    print()

    # Kill any existing services on port 5000
    if sys.platform == "win32":
        os.system('for /f "tokens=5" %a in (\'netstat -aon ^| findstr :5000 ^| findstr LISTENING\') do taskkill /F /PID %a >nul 2>&1')
    else:
        os.system("lsof -ti:5000 | xargs kill -9 2>/dev/null")

    print("  Starting target service...")

    # Start target service
    start_target_service(scenario)
    time.sleep(3)

    print("  Starting load simulator (incident in ~12s)...")

    # Start load simulator (will trigger after delay)
    threading.Thread(target=start_load_sim, args=(12,), daemon=True).start()

    print("  Launching terminal UI...")
    print()
    time.sleep(1)

    # Run the terminal UI (this blocks until investigation completes)
    from demo import resq_terminal
    resq_terminal.main()


if __name__ == "__main__":
    main()
