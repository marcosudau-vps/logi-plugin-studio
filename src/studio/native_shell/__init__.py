"""SDK-native Studio host; the legacy editor remains a separate entry point."""

from .coordinator import StudioCoordinator
from .window import NativeStudioShell

__all__ = ["StudioCoordinator", "NativeStudioShell"]
