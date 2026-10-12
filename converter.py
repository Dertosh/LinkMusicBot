"""Compatibility imports. New code should use linkmusicbot.models/services."""
from linkmusicbot.models import Album, Song
from linkmusicbot.services import AppleMusic, ServiceHandler, Spotify, YouTube, YandexMusic

__all__ = ["Album", "Song", "AppleMusic", "ServiceHandler", "Spotify", "YouTube", "YandexMusic"]
