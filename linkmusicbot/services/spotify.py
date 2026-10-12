import re
from urllib.parse import urlparse

import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials

from ..settings import secrets
from ..models import Album, Song
from ..security import check_budget, valid_url
from .base import ServiceHandler, search_links


class Spotify(ServiceHandler):
    """ServiceHandler for Spotify."""

    _PARENS_PATTERN = re.compile(r"\([^(]*\)")

    @staticmethod
    def _format_query(item):
        """Format a query from an item."""
        query = 'artist:"{}"'.format(item.artist)
        if isinstance(item, Song):
            query += ' track:"{}"'.format(item.title)
        elif isinstance(item, Album):
            query += ' album:"{}"'.format(item.title)
        return query

    @staticmethod
    def service_name():
        """Name Spotify."""
        return "Spotify"

    def __init__(self):
        """Initialize the Spotify instance."""
        self._spotify = spotipy.Spotify(
            requests_timeout=5, retries=0, status_retries=0,
            client_credentials_manager=SpotifyClientCredentials(
                client_id=secrets.get("spotify_client_id"),
                client_secret=secrets.get("spotify_client_secret"),
                cache_handler=MemoryCacheHandler(),
                requests_timeout=5,
            )
        )

    def _naive_query(self, item):
        """Format a less accurate but more forgiving query for an item."""
        return "{} {}".format(re.sub(self._PARENS_PATTERN, "", item.title), item.artist)

    def search(self, query, n=2):
        check_budget()
        response = self._spotify.search(query, type="track", limit=n)
        for track in response["tracks"]["items"][:n]:
            song = Song(track["name"], " & ".join(a["name"] for a in track["artists"]),
                        track["album"]["name"])
            images = track["album"].get("images", [])
            if images:
                song.cover_art = images[0]
            yield search_links(song, "Spotify", track["external_urls"]["spotify"])

    @staticmethod
    def _validated_id(link, kind):
        if not valid_url(link, {"open.spotify.com"}):
            raise ValueError("Invalid Spotify URL")
        match = re.fullmatch(r"/" + kind + r"/([A-Za-z0-9]{22})/?", urlparse(link).path)
        if match is None:
            raise ValueError("Invalid Spotify ID")
        return match.group(1)

    def album_to_link(self, album):
        """Convert an Album into a Spotify link.

        Also sets the album cover art, if un-set.
        """
        check_budget()
        search = self._spotify.search(self._format_query(album), type="album")
        if search["albums"]["total"] < 1:
            check_budget()
            search = self._spotify.search(self._naive_query(album), type="album")
            if search["albums"]["total"] < 1:
                raise ValueError(
                    "Couldn't find any album results for {!r}.".format(album)
                )
        if album.cover_art is None:
            images = search["albums"]["items"][0].get("images", [])
            if images:
                album.cover_art = images[0]
        return search["albums"]["items"][0]["external_urls"]["spotify"]

    def can_handle_link(self, link):
        """Return True if and only if this is a Spotify link."""
        return valid_url(link, {"open.spotify.com"})

    def link_is_song(self, link):
        """Return True if the Spotify link is a song, and False if it is an album"""
        return urlparse(link).path.startswith("/track/")

    def link_to_album(self, link):
        """Convert a Spotify link into an Album."""
        check_budget()
        album = self._spotify.album(self._validated_id(link, "album"))
        return Album(album["name"], album["artists"][0]["name"])

    def link_to_song(self, link):
        """Convert a Spotify link into a Song."""
        check_budget()
        song = self._spotify.track(self._validated_id(link, "track"))
        return Song(song["name"], song["artists"][0]["name"], song["album"]["name"])

    def song_to_link(self, song):
        """Convert a Song into a Spotify link.

        Also sets the song cover art, if un-set.
        """
        check_budget()
        search = self._spotify.search(self._format_query(song))
        if search["tracks"]["total"] < 1:
            check_budget()
            search = self._spotify.search(self._naive_query(song))
            if search["tracks"]["total"] < 1:
                raise ValueError(
                    "Couldn't find any song results for {!r}.".format(song)
                )
        if song.cover_art is None:
            images = search["tracks"]["items"][0]["album"].get("images", [])
            if images:
                song.cover_art = images[0]
        return search["tracks"]["items"][0]["external_urls"]["spotify"]
