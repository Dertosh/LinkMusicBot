"""Public Yandex Music metadata; no audio download or account credentials."""
import json
import re
import time
import unicodedata
from urllib.parse import urlencode, urlparse

from ..models import Album, Song
from ..security import check_budget, fetch_text, valid_url, normalize_query
from .base import ServiceHandler, search_links, same_recording, recording_query, compare_recordings, query_variants, recording_identity

YANDEX_HOSTS = {"music.yandex.ru", "music.yandex.com", "music.yandex.by", "music.yandex.kz"}


class YandexMusic(ServiceHandler):
    def __init__(self):
        self._retry_after = 0

    @staticmethod
    def service_name():
        return "Яндекс Музыка"

    def can_handle_link(self, link):
        return valid_url(link, YANDEX_HOSTS)

    def link_is_song(self, link):
        return "/track/" in urlparse(link).path

    def _get(self, path, params=None):
        check_budget()
        if time.monotonic() < self._retry_after:
            raise ValueError("Yandex metadata temporarily unavailable")
        try:
            response = json.loads(fetch_text("https://api.music.yandex.net" + path,
                                             {"api.music.yandex.net"}, params=params))
            if "error" in response or "result" not in response:
                raise ValueError("Yandex metadata request failed")
            return response["result"]
        except Exception:
            self._retry_after = time.monotonic() + 60
            raise

    @staticmethod
    def _id(value):
        value = str(value)
        if not re.fullmatch(r"[0-9]+", value):
            raise ValueError("Invalid Yandex ID")
        return value

    @staticmethod
    def _artists(data):
        return " & ".join(artist["name"] for artist in data.get("artists", []))

    def _song(self, data):
        albums = data.get("albums", [])
        title = data["title"]
        if data.get("version"):
            title += " (" + data["version"] + ")"
        song = Song(title, self._artists(data), albums[0]["title"] if albums else "")
        song.duration_ms = data.get('durationMs')
        identifier = self._id(data["id"])
        link = (f"https://music.yandex.ru/album/{self._id(albums[0]['id'])}/track/{identifier}"
                if albums else f"https://music.yandex.ru/track/{identifier}")
        self._cover(song, data.get("coverUri"))
        return search_links(song, self.service_name(), link)

    @staticmethod
    def _cover(item, uri):
        if isinstance(uri, str):
            link = (uri if uri.startswith("https://") else "https://" + uri).replace("%%", "600x600")
            if valid_url(link, {"avatars.yandex.net", "avatars.mds.yandex.net"}):
                item.cover_art = {"url": link}

    def _album(self, data):
        album = Album(data["title"], self._artists(data))
        self._cover(album, data.get("coverUri"))
        return search_links(album, self.service_name(), "https://music.yandex.ru/album/" + self._id(data["id"]))

    def link_to_song(self, link):
        if not self.can_handle_link(link):
            raise ValueError("Invalid Yandex Music URL")
        match = re.fullmatch(r"/(?:album/[0-9]+/)?track/([0-9]+)/?", urlparse(link).path)
        if match is None:
            raise ValueError("Invalid Yandex track URL")
        results = self._get("/tracks/" + match.group(1))
        if not results:
            raise ValueError("Yandex track not found")
        song = self._song(results[0])
        song.service_links = {self.service_name(): normalize_query(link)}
        return song

    def link_to_album(self, link):
        if not self.can_handle_link(link):
            raise ValueError("Invalid Yandex Music URL")
        match = re.fullmatch(r"/album/([0-9]+)/?", urlparse(link).path)
        if match is None:
            raise ValueError("Invalid Yandex album URL")
        album = self._album(self._get("/albums/" + match.group(1)))
        album.service_links = {self.service_name(): normalize_query(link)}
        return album

    def search(self, query, n=2):
        result = self._get("/search", {"text": query, "type": "track", "page": 0})
        for data in result.get("tracks", {}).get("results", [])[:n]:
            if data.get("available", True):
                yield self._song(data)

    @staticmethod
    def search_url(query):
        return "https://music.yandex.ru/search?" + urlencode({"text": query})

    @staticmethod
    def _normalized(value):
        return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())

    def _same_item(self, expected, actual):
        def matching_title(title):
            # Yandex puts editorial Eurovision notes in the version field.
            # Do not remove musical versions such as remix/live/video version.
            return re.sub(r"\s*\([^()]*\bПобедитель(?:ница)?\s+на\s+«?Евровидении-\d{4}»?\)\s*$",
                          "", title, flags=re.I)
        item = Song(matching_title(expected.title), expected.artist, "")
        item.duration_ms = getattr(expected, 'duration_ms', None)
        item.isrc = getattr(expected, 'isrc', None)
        return same_recording(item, matching_title(actual.title), actual.artist,
                              duration_ms=getattr(actual, 'duration_ms', None), isrc=getattr(actual, 'isrc', None))

    def song_to_link(self, song):
        term = recording_query(song)
        plain_term = re.sub(r"\s*(?:\(|-\s*)(?:russian|english|japanese)\s*(?:ver\.?|version)\)?", "", term, flags=re.I)
        try:
            for query in dict.fromkeys([term, song.title, plain_term, *query_variants(term)]):
                matches = [match for match in self.search(query, n=20) if self._same_item(song, match)]
                if matches:
                    matches.sort(key=lambda match: (
                        compare_recordings(song, match.title, match.artist, duration_ms=getattr(match, 'duration_ms', None)).score,
                        self._normalized(match.album) == self._normalized(song.album)), reverse=True)
                    return matches[0].service_links[self.service_name()]
            # Recent releases may exist in the artist catalogue before the
            # track search index includes them. Bound this fallback to two
            # verified artists and their first 100 tracks, within the budget.
            seen = set()
            for name in re.split(r'\s*[&;]\s*', song.artist)[:2]:
                artists = self._get('/search', {'text': name, 'type': 'artist', 'page': 0})
                for artist in artists.get('artists', {}).get('results', [])[:3]:
                    if recording_identity('', name)[1] != recording_identity('', artist.get('name', ''))[1]:
                        continue
                    identifier = self._id(artist['id'])
                    if identifier in seen:
                        break
                    seen.add(identifier)
                    catalogue = self._get('/artists/' + identifier + '/tracks', {'page': 0, 'page-size': 100})
                    matches = [self._song(data) for data in catalogue.get('tracks', [])[:100]
                               if data.get('available', True)]
                    matches = [match for match in matches if self._same_item(song, match)]
                    if matches:
                        matches.sort(key=lambda match: (
                            compare_recordings(song, match.title, match.artist, duration_ms=getattr(match, 'duration_ms', None)).score,
                            self._normalized(match.album) == self._normalized(song.album)), reverse=True)
                        return matches[0].service_links[self.service_name()]
                    break
        except Exception:
            pass
        return self.search_url(term)

    def album_to_link(self, album):
        term = f"{album.title} {album.artist}"
        try:
            matches = self._get("/search", {"text": term, "type": "album", "page": 0})
            results = matches.get("albums", {}).get("results", [])
            for data in results:
                match = self._album(data)
                if data.get("available", True) and self._same_item(album, match):
                    return match.service_links[self.service_name()]
        except Exception:
            pass
        return self.search_url(term)
