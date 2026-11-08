from __future__ import annotations

import logging
import os
import signal

from controlplane.config import BrokerSettings
from controlplane.logging_config import configure_logging
from worker_sim.config import parse_args
from worker_sim.worker import Worker


def main(argv: list[str] | None = None) -> None:
    cfg = parse_args(argv)
    listener = configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    try:
        worker = Worker(cfg, BrokerSettings.from_env())
        signal.signal(signal.SIGTERM, lambda *_: worker.stop())
        signal.signal(signal.SIGINT, lambda *_: worker.stop())
        logging.getLogger(__name__).info("starting worker with %s", cfg)
        worker.run()
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
