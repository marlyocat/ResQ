"""Message Queue Simulator - simulates queue failures between services.

This creates two services that communicate via a message queue:
- Order Service: produces order events
- Notification Service: consumes and sends notifications

When the queue fails, both services log errors that ResQ can investigate.
"""

import queue
import threading
import time
import json
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp":"%(asctime)s","level":"%(levelname)s","service":"%(name)s","message":"%(message)s"}'
)

# Shared message queue (simulates Redis/RabbitMQ)
message_queue = queue.Queue(maxsize=100)
queue_healthy = True

order_logger = logging.getLogger("order-service")
notification_logger = logging.getLogger("notification-service")


def order_service():
    """Produces order events to the queue."""
    order_id = 1
    while True:
        if not queue_healthy:
            order_logger.error(
                f"Queue connection timeout - cannot publish order {order_id} "
                f"[file:demo/queue_simulator.py, func:order_service, line:35]"
            )
            time.sleep(2)
            continue

        try:
            event = {
                "order_id": order_id,
                "timestamp": datetime.now().isoformat(),
                "total": round(10 + (order_id * 5.5), 2),
                "status": "completed"
            }
            message_queue.put_nowait(event)
            order_logger.info(f"Order {order_id} published to queue")
            order_id += 1
            time.sleep(0.5)
        except queue.Full:
            order_logger.error(
                f"Queue full - message backlog growing "
                f"[file:demo/queue_simulator.py, func:order_service, line:50]"
            )
            time.sleep(1)


def notification_service():
    """Consumes order events and sends notifications."""
    while True:
        if not queue_healthy:
            notification_logger.error(
                "Queue consumer disconnected - cannot receive messages "
                "[file:demo/queue_simulator.py, func:notification_service, line:65]"
            )
            time.sleep(2)
            continue

        try:
            event = message_queue.get(timeout=2)
            notification_logger.info(
                f"Notification sent for order {event['order_id']} - ${event['total']}"
            )
        except queue.Empty:
            notification_logger.warning("No messages in queue")


def simulate_queue_failure(delay=10):
    """Simulate queue failure after delay."""
    global queue_healthy
    time.sleep(delay)
    print("\n[Queue Simulator] Simulating queue failure...")
    queue_healthy = False


def main():
    print("=" * 50)
    print("  Message Queue Simulator")
    print("=" * 50)
    print()
    print("Starting Order Service and Notification Service...")
    print("Queue failure will occur in 10 seconds")
    print()

    # Start services
    threading.Thread(target=order_service, daemon=True).start()
    threading.Thread(target=notification_service, daemon=True).start()

    # Schedule queue failure
    threading.Thread(target=simulate_queue_failure, args=(10,), daemon=True).start()

    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nQueue simulator stopped")


if __name__ == "__main__":
    main()
