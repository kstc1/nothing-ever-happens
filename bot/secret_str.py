"""Opaque wrapper for secrets (e.g. PRIVATE_KEY) with safe JSON encoding."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretStr:
    """Holds a sensitive string; avoid logging or serializing the raw value."""

    _value: str

    def get_secret_value(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "SecretStr(***)"


class _SecretEncoder(json.JSONEncoder):
    def default(self, obj: object) -> object:
        if isinstance(obj, SecretStr):
            return "**"
        return super().default(obj)


def install_secret_encoder() -> None:
    """Monkey-patch the default JSON encoder so json.dumps redacts SecretStr."""
    json._default_encoder = _SecretEncoder()  # type: ignore[attr-defined]
