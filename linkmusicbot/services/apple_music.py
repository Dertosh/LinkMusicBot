from html import unescape
import re
import unicodedata
from json import loads
from urllib.parse import parse_qs, urlparse, quote, urlencode

from bs4 import BeautifulSoup

from ..models import Album, Song
from ..security import APPLE_HOSTS, fetch_text, valid_url
from .base import ServiceHandler, same_recording, normalized, recording_query, compare_recordings
from ..search_ranking import search_rank


class AppleMusic(ServiceHandler):
    """ServiceHandler for Apple Music."""

    _BASE_SEARCH_URL = "https://itunes.apple.com/search"

    def _web_search(self, term, country='US'):
        """Public server-rendered search, independent of the iTunes index."""
        page = BeautifulSoup(fetch_text(f'https://music.apple.com/{country.lower()}/search',
                                        APPLE_HOSTS, params={'term': term}), 'html.parser')
        script = page.find('script', id='serialized-server-data')
        if script is None:
            return {'resultCount': 0, 'results': []}
        payload = loads(script.get_text())
        results, seen = [], set()
        for entry in payload.get('data', []):
            for section in entry.get('data', {}).get('sections', []):
                for item in section.get('items', []):
                    descriptor = item.get('contentDescriptor', {})
                    url = descriptor.get('url', '')
                    if descriptor.get('kind') != 'song' or not valid_url(url, APPLE_HOSTS) or url in seen:
                        continue
                    artists = [link.get('title', '') for link in item.get('subtitleLinks', [])
                               if '/artist/' in link.get('segue', {}).get('destination', {}).get('contentDescriptor', {}).get('url', '')]
                    if not artists and '·' in (item.get('subtitle') or ''):
                        artists = [item['subtitle'].split('·', 1)[1].strip()]
                    if not artists or not item.get('title'):
                        continue
                    seen.add(url)
                    results.append({'wrapperType': 'track', 'trackName': item['title'],
                                    'artistName': ' & '.join(artists), 'collectionName': '', 'trackViewUrl': url})
        return {'resultCount': len(results), 'results': results}

    @staticmethod
    def _large_artwork(url):
        parsed = urlparse(url)
        if not re.fullmatch(r"is[1-5]-ssl\.mzstatic\.com", parsed.hostname or ""):
            return url
        # Apple's CDN encodes requested image dimensions in the final path segment.
        return parsed._replace(path=re.sub(
            r"/\d+x\d+bb(?:-[0-9]+)?\.(jpg|png)$", r"/600x600bb.\1", parsed.path
        )).geturl()

    @staticmethod
    def _format_query(item):
        """Format a search query."""
        return recording_query(item)

    @staticmethod
    def service_name():
        """Name Apple Music."""
        return "Apple Music"

    def _search(
        self,
        term,
        country="US",
        media=None,
        entity=None,
        attribute=None,
        limit=50,
        lang="en_us",
        version=2,
        explicit=None,
    ):
        """Search iTunes."""
        query = {
            "term": term,
            "country": country,
            "limit": limit,
            "lang": lang,
            "version": version,
        }
        if explicit is not None:
            query["explicit"] = "Yes" if explicit else "No"
        for name, value in (
            ("media", media),
            ("entity", entity),
            ("attribute", attribute),
        ):
            if value is not None:
                query[name] = value
        return loads(fetch_text(self._BASE_SEARCH_URL, APPLE_HOSTS, params=query))

    def album_to_link(self, album):
        """Turn an Album into an Apple Music link."""
        search = self._search(
            self._format_query(album), media="music", entity="album", explicit=True
        )
        if search["resultCount"] < 1:
            raise ValueError("Couldn't find any album results for {!r}.".format(album))
        for item in search["results"]:
            if same_recording(album, item.get("collectionName", ""), item.get("artistName", "")):
                return item["collectionViewUrl"]
        raise ValueError("No matching Apple Music album")

    def can_handle_link(self, link):
        """Return True if and only if this is an Apple Music link."""
        return valid_url(link, APPLE_HOSTS)

    def link_is_song(self, link):
        """Return True if the link is a song, or False if it's an album."""
        queries = parse_qs(urlparse(link).query)
        return "/song/" in urlparse(link).path or "i" in queries

    @staticmethod
    def _artists(value):
        artists = value if isinstance(value, list) else [value]
        return " & ".join(unescape(artist["name"]) for artist in artists if artist)

    def _read_item(self, link, song):
        if not self.can_handle_link(link):
            raise ValueError("Invalid Apple Music URL")
        page = BeautifulSoup(fetch_text(link, APPLE_HOSTS), "html.parser")
        for script in page.find_all("script", type="application/ld+json"):
            try:
                data = loads(script.get_text())
            except ValueError:
                continue
            entries = data if isinstance(data, list) else data.get("@graph", [data])
            for entry in entries:
                recording = entry.get("audio") if entry.get("@type") == "MusicComposition" else entry
                if song and isinstance(recording, dict) and recording.get("@type") == "MusicRecording":
                    item = Song(unescape(recording["name"]),
                                self._artists(recording.get("byArtist")),
                                recording.get("inAlbum", {}).get("name", ""))
                    item.isrc = recording.get('isrcCode')
                    image = recording.get("inAlbum", {}).get("image") or recording.get("image")
                elif not song and entry.get("@type") == "MusicAlbum":
                    item = Album(unescape(entry["name"]), self._artists(entry.get("byArtist")))
                    image = entry.get("image")
                elif song and entry.get("@type") == "MusicAlbum":
                    # Older album URLs select a track through ?i=.
                    row = page.find(class_="is-deep-linked")
                    if row is None:
                        continue
                    item = Song(row.find(class_="table__row__headline").get_text(strip=True),
                                self._artists(entry.get("byArtist")), unescape(entry["name"]))
                    image = entry.get("image")
                else:
                    continue
                item.service_links = {self.service_name(): link}
                if isinstance(image, str):
                    item.cover_art = {"url": self._large_artwork(image)}
                return item
        raise ValueError("Apple Music metadata not found")

    def link_to_album(self, link):
        return self._read_item(link, song=False)

    def link_to_song(self, link):
        return self._read_item(link, song=True)

    def search(self, query, n=5):
        """Perform a search with a given query. Returns a list of Song or Album objects."""
        country = "JP" if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", query) else "US"
        search = self._search(
            query, country=country, media="music", entity="song", explicit=True,
            limit=max(20, n)
        )
        if not search.get("results") and country != "US":
            search = self._search(query, country="US", media="music", entity="song",
                                  explicit=True, limit=max(20, n))
        if not search.get('results'):
            try:
                search = self._web_search(query, country)
            except Exception:
                pass
        def rank(item):
            return search_rank(item.get("trackName", ""), query)
        seen = set()
        count = 0
        for item in sorted(search["results"], key=rank, reverse=True):
            identity = (normalized(item.get("trackName", "")), normalized(item.get("artistName", "")))
            if identity in seen:
                continue
            seen.add(identity)
            wrapper_type = item.get("wrapperType")
            if wrapper_type == "track":
                result = Song(
                    item["trackName"], item["artistName"], item["collectionName"]
                )
                result.duration_ms = item.get('trackTimeMillis')
            elif wrapper_type == "collection":
                result = Album(item["collectionName"], item["artistName"])
            else:
                continue
            term = self._format_query(result)
            result.service_links = {
                "Apple Music": item.get("trackViewUrl") or item.get("collectionViewUrl"),
                "Spotify": "https://open.spotify.com/search/" + quote(term, safe=""),
                "YouTube": "https://www.youtube.com/results?" + urlencode({"search_query": term}),
            }
            if item.get("artworkUrl100"):
                result.cover_art = {"url": self._large_artwork(item["artworkUrl100"])}
            yield result
            count += 1
            if count >= n:
                break

    def song_to_link(self, song):
        """Turn a Song into an Apple Music link."""
        country = "JP" if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", song.title + song.artist) else "US"
        search = self._search(
            self._format_query(song), country=country, media="music", entity="song", explicit=True
        )
        if not search.get("results") and country != "US":
            search = self._search(self._format_query(song), country="US",
                                  media="music", entity="song", explicit=True)
        def normalized(value):
            return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", unescape(value)).casefold())
        title, artist = normalized(song.title), normalized(song.artist)
        def rank(item):
            title_match = normalized(item.get("trackName", "")) == title
            artist_match = normalized(item.get("artistName", "")) == artist
            assessment = compare_recordings(song, item.get('trackName', ''), item.get('artistName', ''), duration_ms=item.get('trackTimeMillis'))
            return (assessment.score, title_match and artist_match, title_match, artist_match,
                    normalized(item.get("collectionName", "")) == normalized(song.album))
        matches = [item for item in search["results"]
                     if same_recording(song, item.get("trackName", ""), item.get("artistName", ""), duration_ms=item.get('trackTimeMillis'))]
        if not matches:
            try:
                matches = [item for item in self._web_search(self._format_query(song), country)['results']
                             if same_recording(song, item.get('trackName', ''), item.get('artistName', ''), duration_ms=item.get('trackTimeMillis'))]
            except Exception:
                pass
        if not matches:
            raise ValueError("No matching Apple Music recording")
        return max(matches, key=rank)["trackViewUrl"]
