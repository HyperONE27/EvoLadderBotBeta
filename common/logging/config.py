# packages/logging/config.py
import logging
import os
import sys
import structlog
from typing import Optional

def configure_structlog(
    service_name: str = "unknown-service",
    json_logs: bool = os.getenv("ENV", "dev").lower() in ("prod", "staging"),
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper(),
) -> None:
    """
    Configure structlog once at startup.
    - Pretty console in dev, JSON in prod.
    - Binds global fields like service name.
    - Quiets noisy 3rd-party loggers.
    """
    level = getattr(logging, log_level, logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,          # ← crucial for request/command context
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,             # nice tracebacks
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if json_logs:
        processors = shared_processors + [structlog.processors.JSONRenderer()]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty(), sort_keys=True)
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.WriteLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bind once-per-process context (appears in every log line)
    structlog.get_logger().bind(
        service=service_name,
        env=os.getenv("ENV", "dev"),
        # version=os.getenv("APP_VERSION", "dev"),  # optional
    )

    # Silence noisy libs (discord.py, aiohttp, etc.)
    for logger_name in (
        "discord", "discord.client", "discord.gateway", "discord.http",
        "aiosqlite", "httpx", "httpcore", "uvicorn", "uvicorn.access",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)