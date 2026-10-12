"""Supported music services."""
from .apple_music import AppleMusic
from .base import ServiceHandler
from .spotify import Spotify
from .youtube import YouTube
from .yandex_music import YandexMusic

__all__ = ["AppleMusic", "ServiceHandler", "Spotify", "YouTube", "YandexMusic"]
