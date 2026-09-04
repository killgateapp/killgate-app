import json
import logging
import sys

from app.observability import JsonFormatter


def test_json_formatter_redacts_exception_arguments_and_tracebacks():
    sentinel = "synthetic-provider-detail-should-not-reach-logs"
    logger = logging.getLogger("killgate.tests.observability")

    try:
        raise RuntimeError(sentinel)
    except RuntimeError:
        record = logger.makeRecord(
            logger.name,
            logging.ERROR,
            "test_observability.py",
            1,
            "Provider failure: %s",
            (RuntimeError(sentinel),),
            sys.exc_info(),
        )

    payload = json.loads(JsonFormatter().format(record))

    assert payload == {
        "level": "ERROR",
        "logger": "killgate.tests.observability",
        "message": "Provider failure: RuntimeError",
        "exception_type": "RuntimeError",
    }
    assert sentinel not in json.dumps(payload)
    assert "Traceback" not in json.dumps(payload)
