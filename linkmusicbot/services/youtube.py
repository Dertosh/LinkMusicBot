from json import loads
from html import unescape
import re
from urllib.parse import parse_qs, urlparse, urlencode
from requests.exceptions import HTTPError

from bs4 import BeautifulSoup

from ..settings import secrets
from ..models import Album, Song
from ..security import YOUTUBE_HOSTS, SearchQuota, QuotaExceeded, check_budget, fetch_text, valid_url
from .base import ServiceHandler, search_links, normalized, same_recording
from ..youtube_fetch import first_video


class YouTube(ServiceHandler):
    _PLAYLIST_PATH = "https://www.googleapis.com/youtube/v3/playlists"
    _SEARCH_PATH = "https://www.googleapis.com/youtube/v3/search"

    @staticmethod
    def _format_album_query(item):
        """Format a query for an Album."""
        return "{} {} full album".format(item.title, item.artist)

    @staticmethod
    def _format_song_query(item):
        """Format a query for a Song."""
        return "{} {} topic".format(item.title, item.artist)

    @staticmethod
    def _link_to_id(link):
        """Take a YouTube link and return a playlist ID."""
        return parse_qs(urlparse(link).query)["list"][0]

    @staticmethod
    def _playlist_link(playlist_data):
        """Get a playlist link from a data payload."""
        return "https://www.youtube.com/playlist?list={}".format(
            playlist_data["id"]["playlistId"]
        )

    @staticmethod
    def _video_link(video_data):
        """Get a video link from a data payload"""
        return "https://youtube.com/watch?v={}".format(video_data["id"]["videoId"])

    @staticmethod
    def service_name():
        """Return the name of YouTube."""
        return "YouTube"

    def __init__(self):
        """Initialize the class."""
        self._yt_token = secrets.get("youtube_token")
        self._search_quota = SearchQuota(secrets.get("youtube_search_limit", 100))

    def _get(self, url, params=None):
        """Get a URL with certain parameters."""
        check_budget()
        if url == self._SEARCH_PATH:
            self._search_quota.reserve()
        if params is None:
            params = {}

        params = dict(params, key=self._yt_token)
        try:
            response = loads(fetch_text(url, {"www.googleapis.com"}, params=params))
        except HTTPError as error:
            try:
                payload = error.response.json()
            except ValueError:
                raise error
            if self._quota_error(payload):
                raise QuotaExceeded("YouTube API quota exceeded") from None
            raise
        if self._quota_error(response):
            raise QuotaExceeded("YouTube API quota exceeded")
        return response

    @staticmethod
    def _quota_error(response):
        return any(error.get("reason") in {
            "quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"
        } for error in response.get("error", {}).get("errors", []))

    @staticmethod
    def _search_url(query):
        return "https://www.youtube.com/results?" + urlencode({"search_query": query})

    def _quota_fallback(self, query):
        try:
            return first_video(query)
        except Exception:
            return self._search_url(query)

    def album_to_link(self, album):
        return self._search_url(self._format_album_query(album))

    def search(self, query, n=2):
        response = self._get(self._SEARCH_PATH, {
            "part": "snippet", "maxResults": n, "q": query,
            "type": "video", "videoCategoryId": "10",
        })
        if "error" in response:
            raise ValueError("YouTube search unavailable")
        for entry in response.get("items", [])[:n]:
            snippet = entry["snippet"]
            song = Song(unescape(snippet["title"]), unescape(snippet["channelTitle"]), "")
            yield search_links(song, "YouTube", self._video_link(entry))

    def can_handle_link(self, link):
        """Return True if and only if this is a YouTube link."""
        return valid_url(link, YOUTUBE_HOSTS)

    def link_is_song(self, link):
        """Return True if a link is a song, and False if it's an album."""
        parsed_url = urlparse(link)
        if parsed_url.netloc.lower() in (
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
        ):
            return parsed_url.path == "/watch"
        return True  # youtu.be link

    def link_to_album(self, link):
        """Turn a YouTube link into an Album.

        Warning: This is super shaky, because it just takes a playlist and converts it. There will be plenty of
        unexpected behavior!
        """
        params = {"part": "snippet", "id": self._link_to_id(link)}
        response = self._get(self._PLAYLIST_PATH, params)
        if len(response["items"]) < 1:
            raise ValueError("Not an album: {!r}".format(link))

        return Album(
            response["items"][0]["snippet"]["title"], ""
        )  # empty artist because we really can't know

    def link_to_song(self, link):
        """Turn a YouTube link into a Song."""
        if not self.can_handle_link(link):
            raise ValueError("Invalid YouTube URL")
        parsed = urlparse(link)
        identifier = (parsed.path.strip("/") if parsed.hostname == "youtu.be"
                      else parse_qs(parsed.query).get("v", [""])[0])
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
            raise ValueError("Invalid YouTube video ID")
        response = self._get("https://www.googleapis.com/youtube/v3/videos",
                             {"part": "snippet", "id": identifier})
        for entry in response.get("items", []):
            song = self._snippet_song(entry.get("snippet", {}))
            if song is not None:
                song.service_links = {self.service_name(): link}
                return song
        # Unfortunately, this info is NOT provided by the API, so... we're doing more webscraping!
        page = BeautifulSoup(
            fetch_text(link, YOUTUBE_HOSTS), "html.parser"
        )
        title = artist = album = None
        for metadata in page.find_all("li", class_="watch-meta-item"):
            metadata_name = metadata.h4.string.strip()
            metadata_value = metadata.ul.li.string.strip()

            if metadata_name == "Song":
                title = metadata_value
            elif metadata_name == "Artist":
                artist = metadata_value
            elif metadata_name == "Album":
                album = metadata_value

        if None in (title, artist):
            raise ValueError("Not a song: {!r}".format(link))

        return Song(title, artist, album)

    @staticmethod
    def _snippet_song(snippet):
        title = unescape(snippet.get("title", ""))
        channel = unescape(snippet.get("channelTitle", ""))
        if channel.endswith(" - Topic"):
            return Song(title, channel[:-8], "") if title else None
        title = re.sub(r"\s*[\(\[]official\s+(?:(?:lyrics?|music)\s+)?(?:video|audio)[\)\]]\s*$",
                       "", title, flags=re.I)
        parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
        if len(parts) == 2 and channel and normalized(parts[0]) == normalized(channel):
            return Song(parts[1], parts[0], "")
        return None

    def song_to_link(self, song):
        query = self._format_song_query(song)
        try:
            response = self._get(self._SEARCH_PATH, {
                "part": "snippet", "maxResults": 10, "q": query, "type": "video",
            })
        except QuotaExceeded:
            return self._search_url(query)
        for entry in response.get("items", []):
            candidate = self._snippet_song(entry.get("snippet", {}))
            if candidate and same_recording(song, candidate.title, candidate.artist):
                return self._video_link(entry)
        return self._search_url(query)
