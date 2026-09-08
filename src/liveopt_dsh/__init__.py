"""DeepSeek Harness integration boundary for the existing LiveOpt runtime."""

from .config import ServiceConfig
from .service import LiveOptService

__all__ = ["LiveOptService", "ServiceConfig"]
__version__ = "0.1.0"

