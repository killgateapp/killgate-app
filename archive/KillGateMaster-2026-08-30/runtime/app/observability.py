"""Structured observability that preserves operational categories, not raw failures."""

import json
import logging
import os
import sys


class JsonFormatter(logging.Formatter):
    """Emit safe JSON records without exception text, traces, or provider details."""

    @classmethod
    def _redact_exception_values(cls, value: object) -> object:
        if isinstance(value, BaseException):
            return type(value).__name__
        if isinstance(value, tuple):
            return tuple(cls._redact_exception_values(item) for item in value)
        if isinstance(value, list):
            return [cls._redact_exception_values(item) for item in value]
        if isinstance(value, dict):
            return {
                key: cls._redact_exception_values(item)
                for key, item in value.items()
            }
        return value

    def format(self, record: logging.LogRecord) -> str:
        # ``LogRecord.getMessage`` expands logging arguments. Redact exception
        # instances first so ``logger.warning("failed: %s", exc)`` cannot emit
        # provider response details or server connection context.
        original_args = record.args
        record.args = self._redact_exception_values(original_args)
        try:
            message = record.getMessage()
        finally:
            record.args = original_args

        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }
        if record.exc_info:
            exception_type = record.exc_info[0]
            payload["exception_type"] = getattr(
                exception_type,
                "__name__",
                type(exception_type).__name__,
            )
        return json.dumps(payload, ensure_ascii=False)


def configure_observability() -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=dsn,
                environment=os.getenv("APP_ENV", "production"),
                traces_sample_rate=float(
                    os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")
                ),
                send_default_pii=False,
            )
        except Exception as exc:  # noqa: BLE001 - third-party SDK initialization must never block startup
            logging.getLogger(__name__).warning(
                "Sentry initialization failed (%s).", type(exc).__name__
            )
