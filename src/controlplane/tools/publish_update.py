"""Publish a worker update (or arbitrary bytes) straight onto the broker, for negative testing.

  python -m controlplane.tools.publish_update --task-id <id> --status done
  python -m controlplane.tools.publish_update --task-id <id> --status done --update-id X --repeat 2
  python -m controlplane.tools.publish_update --raw 'not json'      # poison message -> DLQ
"""

from __future__ import annotations

import argparse
import json
import os
import uuid

import pika

from controlplane.config import BrokerSettings
from controlplane.messaging.topology import ROUTING_TASK_UPDATE, declare_topology


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--task-id")
    p.add_argument("--status", choices=["in_progress", "done", "failed"])
    p.add_argument("--update-id", default=None, help="idempotency key (default: random)")
    p.add_argument("--error", default=None)
    p.add_argument("--repeat", type=int, default=1, help="publish the same message N times")
    p.add_argument("--raw", default=None, help="publish this exact string instead of an update")
    args = p.parse_args(argv)

    if args.raw is not None:
        body = args.raw.encode()
    elif args.task_id and args.status:
        body = json.dumps(
            {
                "update_id": args.update_id or str(uuid.uuid4()),
                "task_id": args.task_id,
                "status": args.status,
                "error": args.error,
            }
        ).encode()
    else:
        p.error("give --task-id and --status, or --raw")

    broker = BrokerSettings(amqp_url=os.environ["AMQP_URL"])
    conn = pika.BlockingConnection(pika.URLParameters(broker.amqp_url))
    try:
        ch = conn.channel()
        declare_topology(ch, broker)
        ch.confirm_delivery()
        for _ in range(args.repeat):
            ch.basic_publish(
                broker.exchange,
                ROUTING_TASK_UPDATE,
                body,
                pika.BasicProperties(delivery_mode=2, content_type="application/json"),
                mandatory=True,
            )
        print(f"published {args.repeat}x: {body.decode()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
