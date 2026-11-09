"""Support Hub backend package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("support-hub-backend")
except PackageNotFoundError:  # pragma: no cover - running from source without install
    __version__ = "0.0.0.dev0"
