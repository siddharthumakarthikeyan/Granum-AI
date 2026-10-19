"""Managed compute catalogue and immutable table results."""

from .contracts import Manifest, PluginError
from .manager import PluginManager

__all__ = ["Manifest", "PluginError", "PluginManager"]
