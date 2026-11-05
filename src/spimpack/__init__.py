"""SPIM dataset packaging with pluggable output backends."""

from importlib.metadata import PackageNotFoundError, version

from .models import DatasetManifest

try:
    __version__ = version("spimpack")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = ["DatasetManifest"]
