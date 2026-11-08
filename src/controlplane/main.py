"""Process entry point: `python -m controlplane`."""

from __future__ import annotations

import logging
import os

import uvicorn

from controlplane.api.app import create_app
from controlplane.config import Settings
from controlplane.logging_config import configure_logging


def main() -> None:
    settings = Settings.from_env()
    listener = configure_logging(settings.log_level)
    try:
        app = create_app(settings)
        uvicorn.run(
            app,
            host=os.environ.get("HOST", "0.0.0.0"),  # nosec B104 - container-internal bind
            port=int(os.environ.get("PORT", "8000")),
            log_config=None,  # keep our async JSON logging; don't let uvicorn reconfigure it
        )
    finally:
        logging.getLogger(__name__).info("shutting down")
        listener.stop()


if __name__ == "__main__":
    main()
