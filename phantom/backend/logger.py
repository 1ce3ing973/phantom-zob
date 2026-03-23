"""Shared logger instance for the Phantom plugin backend."""

import sys
from typing import Any

_LOGGER_INSTANCE: Any = None


def get_logger() -> Any:
    """Return a singleton PluginUtils.Logger instance, or a stderr fallback if unavailable."""
    global _LOGGER_INSTANCE
    if _LOGGER_INSTANCE is None:
        try:
            import PluginUtils  # type: ignore

            _LOGGER_INSTANCE = PluginUtils.Logger()
        except Exception:
            class _FallbackLogger:
                def log(self, message: str) -> None:
                    print(f"[Phantom] {message}", file=sys.stderr, flush=True)

                def warn(self, message: str) -> None:
                    print(f"[Phantom] WARN {message}", file=sys.stderr, flush=True)

                def error(self, message: str) -> None:
                    print(f"[Phantom] ERROR {message}", file=sys.stderr, flush=True)

            _LOGGER_INSTANCE = _FallbackLogger()
    return _LOGGER_INSTANCE


logger = get_logger()
