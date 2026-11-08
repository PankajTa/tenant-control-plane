import io
import json
import logging

from controlplane.logging_config import configure_logging


def test_logs_are_json_and_written_by_the_listener_thread():
    buf = io.StringIO()
    listener = configure_logging("INFO", stream=buf)
    try:
        log = logging.getLogger("t")
        log.info("hello %s", "world", extra={"task_id": "abc"})
        try:
            raise ValueError("kaput")
        except ValueError:
            log.exception("failed")
    finally:
        listener.stop()  # flushes the queue
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert lines[0]["message"] == "hello world" and lines[0]["task_id"] == "abc"
    assert lines[0]["level"] == "INFO" and lines[0]["ts"].endswith("Z")
    assert "ValueError: kaput" in lines[1]["exception"]
