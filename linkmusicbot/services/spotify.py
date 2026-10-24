import re
from urllib.parse import urlparse

import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyClientCredentials

from ..settings import secrets
from ..models import Album, Song
from ..security import check_budget, valid_url
from .base import ServiceHandler, search_links, same_recording, query_variants, compare_recordings


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
        """Yield catalogue tracks with credits, duration, artwork, and their Spotify source URLs."""
        check_budget()
        response = self._spotify.search(query, type="track", limit=n)
        for track in response["tracks"]["items"][:n]:
            song = Song(track["name"], " & ".join(a["name"] for a in track["artists"]),
                        track["album"]["name"])
            song.duration_ms = track.get('duration_ms')
            song.isrc = track.get('external_ids', {}).get('isrc')
            images = track["album"].get("images", [])
            if images:
                song.cover_art = images[0]
            yield search_links(song, "Spotify", track["external_urls"]["spotify"])

    @staticmethod
    def _validated_id(link, kind):
        """Validate a Spotify URL and extract the requested resource identifier."""
        if not valid_url(link, {"open.spotify.com"}):
            raise ValueError("Invalid Spotify URL")
        match = re.fullmatch(r"/" + kind + r"/([A-Za-z0-9]{22})/?", urlparse(link).path)
        if match is None:
            raise ValueError("Invalid Spotify ID")
        return match.group(1)

    def _matched_link(self, item, kind):
        """Try bounded query variants and return the highest-scoring verified recording URL."""
        queries = [self._format_query(item), *query_variants(self._naive_query(item)), item.title]
        for query in dict.fromkeys(queries):
            check_budget()
            response = self._spotify.search(query, type=kind, limit=10)
            matches = []
            for entry in response[kind + "s"]["items"]:
                artist = " & ".join(a["name"] for a in entry.get("artists", []))
                assessment = compare_recordings(item, entry.get("name", ""), artist,
                                               duration_ms=entry.get('duration_ms'), isrc=entry.get('external_ids', {}).get('isrc'))
                if assessment.status == 'match':
                    matches.append((assessment.score, entry))
            if matches:
                entry = max(matches, key=lambda pair: (pair[0], pair[1].get('album', {}).get('name') == getattr(item, 'album', None)))[1]
                images = (entry.get("album", {}) if kind == "track" else entry).get("images", [])
                if item.cover_art is None and images:
                    item.cover_art = images[0]
                return entry["external_urls"]["spotify"]
        raise ValueError("No matching Spotify recording")

    def album_to_link(self, album):
        """Find the matching Spotify album using the shared catalogue matcher."""
        return self._matched_link(album, "album")

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
        item = Album(album["name"], " & ".join(a["name"] for a in album["artists"]))
        item.service_links = {self.service_name(): "https://open.spotify.com/album/" + self._validated_id(link, "album")}
        return item

    def link_to_song(self, link):
        """Convert a Spotify link into a Song."""
        check_budget()
        song = self._spotify.track(self._validated_id(link, "track"))
        item = Song(song["name"], " & ".join(a["name"] for a in song["artists"]), song["album"]["name"])
        item.duration_ms = song.get('duration_ms')
        item.isrc = song.get('external_ids', {}).get('isrc')
        images = song.get('album', {}).get('images', [])
        if images:
            item.cover_art = images[0]
        item.service_links = {self.service_name(): "https://open.spotify.com/track/" + self._validated_id(link, "track")}
        return item

    def song_to_link(self, song):
        """Find a Spotify track using verified recording metadata."""
        return self._matched_link(song, "track")
