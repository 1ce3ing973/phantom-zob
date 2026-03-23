"""Filesystem path helpers for the Phantom backend."""

import os
import sys

# Ensure backend package root is importable when Millennium's working directory is not backend/.
_backend_dir = os.path.dirname(os.path.realpath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


def get_backend_dir() -> str:
    """Return the absolute path to the backend directory."""
    return os.path.dirname(os.path.realpath(__file__))


def get_plugin_dir() -> str:
    """Return the absolute path to the root plugin directory."""
    backend_dir = get_backend_dir()
    return os.path.abspath(os.path.join(backend_dir, ".."))


def backend_path(filename: str) -> str:
    """Return an absolute path to a file inside the backend directory."""
    return os.path.join(get_backend_dir(), filename)


def public_path(filename: str) -> str:
    """Return an absolute path to a file inside the public directory."""
    return os.path.join(get_plugin_dir(), "public", filename)

