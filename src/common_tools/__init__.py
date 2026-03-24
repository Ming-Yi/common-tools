from importlib.metadata import version

from .base_classes import SingletonMeta, StaticUtils
from .logger import Logging

__version__ = version("common-tools")

__all__ = [
    "Logging",
    "SingletonMeta",
    "StaticUtils",
]
