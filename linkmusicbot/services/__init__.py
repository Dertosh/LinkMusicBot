"""Supported music services."""
from .apple_music import AppleMusic
from .base import ServiceHandler
from .spotify import Spotify
from .youtube import YouTube

__all__ = ["AppleMusic", "ServiceHandler", "Spotify", "YouTube"]
