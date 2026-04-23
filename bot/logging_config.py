import logging
import sys

try:
    from pythonjsonlogger.json import JsonFormatter
except ImportError:
    from pythonjsonlogger.jsonlogger import JsonFormatter  # type: ignore[no-redef]

from bot.secret_str import SecretStr, install_secret_encoder

SENSITIVE_FIELDS = frozenset({"private_key", "PRIVATE_KEY", "key", "api_key", "secret"})


class SensitiveFieldFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for field in SENSITIVE_FIELDS:
            if field in record.__dict__:
                record.__dict__[field] = "**"
        if isinstance(record.args, dict):
            record.args = {k: "**" if k in SENSITIVE_FIELDS else v for k, v in record.args.items()}
        return True


def configure_logging(level: str) -> None:
    install_secret_encoder()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveFieldFilter())
    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
