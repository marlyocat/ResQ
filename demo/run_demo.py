"""ResQ Demo — single command that runs everything.

Usage:
    python demo/run_demo.py

Starts the target service, waits, triggers the incident, and shows
the terminal UI with the full agent investigation.
"""

import threading
import time
import sys
import os
import subprocess

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def start_target_service():
    """Start the target Flask service in a background thread."""
    subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "..", "target", "app.py")],
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
    print()
    print("  ==================================================")
    print("  ResQ - Multi-Agent Incident Response")
    print("  ==================================================")
    print()

    # Kill any existing services on port 5000
    if sys.platform == "win32":
        os.system('for /f "tokens=5" %a in (\'netstat -aon ^| findstr :5000 ^| findstr LISTENING\') do taskkill /F /PID %a >nul 2>&1')
    else:
        os.system("lsof -ti:5000 | xargs kill -9 2>/dev/null")

    print("  Starting target service...")

    # Start target service
    start_target_service()
    time.sleep(3)

    print("  Starting load simulator (incident in ~12s)...")

    # Start load simulator (will trigger after delay)
    threading.Thread(target=start_load_sim, args=(12,), daemon=True).start()

    print("  Launching terminal UI...")
    print()
    time.sleep(1)

    # Run the terminal UI (this blocks until investigation completes)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "resq_terminal",
        os.path.join(os.path.dirname(__file__), "resq_terminal.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


if __name__ == "__main__":
    main()
