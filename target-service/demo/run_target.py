"""One command to start the flaskapp target for a ResQ TUI demo.

Starts the Flask app on :5000 with an incident scenario, then starts the load
simulator. Leave this running, and in a SEPARATE terminal launch ResQ's
terminal UI (which polls localhost:5000):

    cd <path-to>/ResQ
    python demo/resq_terminal.py

The app degrades ~15s after start and stays degraded, so ResQ will detect the
incident whenever its UI is running.

Usage:
    python demo/run_target.py               # scenario 1, port 5000
    python demo/run_target.py --delay 10    # trigger the incident sooner
"""

import argparse
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def start_app(delay: int):
    env = dict(os.environ, SCENARIO="1", FAILURE_DELAY=str(delay), PORT="5000")
    return subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py")], env=env)


def start_load(after: float = 3.0):
    time.sleep(after)
    return subprocess.Popen([sys.executable, os.path.join(HERE, "load_sim.py")])


def main():
    parser = argparse.ArgumentParser(description="flaskapp target for ResQ TUI demo")
    parser.add_argument("--delay", type=int, default=15,
                        help="seconds until the incident is injected (default 15)")
    args = parser.parse_args()

    print("=" * 60)
    print("  flaskapp target — ResQ TUI demo")
    print("=" * 60)
    print(f"  App:  http://localhost:5000   (incident in ~{args.delay}s)")
    print("  Now, in another terminal, launch the ResQ terminal UI:")
    print("      cd <path-to>/ResQ && python demo/resq_terminal.py")
    print("=" * 60)

    procs = [start_app(args.delay)]
    threading.Thread(target=lambda: procs.append(start_load()), daemon=True).start()

    try:
        procs[0].wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
