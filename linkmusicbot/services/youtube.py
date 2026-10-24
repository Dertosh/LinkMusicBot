from json import loads
from html import unescape
import re
import os
from urllib.parse import parse_qs, urlparse, urlencode
from requests.exceptions import HTTPError

from ..settings import secrets
from ..models import Album, Song
from ..security import YOUTUBE_HOSTS, SearchQuota, QuotaExceeded, check_budget, fetch_text, valid_url
from .base import ServiceHandler, search_links, normalized, same_recording, recording_query, durations_match
from ..youtube_fetch import first_video
from ..youtube_music import search_music, video_music_metadata
from ..query_text import alias_text


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
        quota_path = os.environ.get("MUSIC_CACHE_PATH", "data/music.sqlite3") if self._yt_token else None
        self._search_quota = SearchQuota(secrets.get("youtube_search_limit", 100), path=quota_path)

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
                self._record_quota_error(url, payload)
                raise QuotaExceeded("YouTube API quota exceeded") from None
            raise
        if self._quota_error(response):
            self._record_quota_error(url, response)
            raise QuotaExceeded("YouTube API quota exceeded")
        return response

    def _record_quota_error(self, url, payload):
        """Persist an appropriate cooldown after a provider-reported search quota error."""
        if url != self._SEARCH_PATH:
            return
        reasons = {error.get("reason") for error in payload.get("error", {}).get("errors", [])}
        seconds = 86400 if reasons & {"quotaExceeded", "dailyLimitExceeded"} else 60
        self._search_quota.mark_exhausted(seconds)

    @staticmethod
    def _quota_error(response):
        """Recognize API quota and rate-limit errors in a YouTube response."""
        return any(error.get("reason") in {
            "quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"
        } for error in response.get("error", {}).get("errors", []))

    @staticmethod
    def _search_url(query):
        """Build an explicit public YouTube search URL."""
        return "https://www.youtube.com/results?" + urlencode({"search_query": query})

    def _quota_fallback(self, query):
        """Try public search when API quota is unavailable and retain a search URL on failure."""
        try:
            return first_video(query)
        except Exception:
            return self._search_url(query)

    def album_to_link(self, album):
        """Return a YouTube search URL for the requested full album."""
        return self._search_url(self._format_album_query(album))

    def _metadata_snippets(self, identifiers):
        """Batch-read up to fifty validated video IDs with snippet and duration metadata."""
        identifiers = list(dict.fromkeys(identifier for identifier in identifiers
                                         if isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier)))[:50]
        if not identifiers:
            return {}
        try:
            response = self._get('https://www.googleapis.com/youtube/v3/videos', {'part': 'snippet,contentDetails', 'id': ','.join(identifiers)})
            snippets = {}
            for item in response.get('items', []):
                if isinstance(item.get('id'), str) and item['id'] in identifiers:
                    snippet = dict(item.get('snippet', {}))
                    snippet['_duration_ms'] = self._duration_ms(item.get('contentDetails', {}).get('duration', ''))
                    snippets[item['id']] = snippet
            return snippets
        except Exception:
            return {}

    def _enrich_music_songs(self, songs):
        """Use Topic metadata to recover complete performer credits for music candidates."""
        identifiers = [parse_qs(urlparse(getattr(s, 'service_links', {}).get('YouTube', '')).query).get('v', [''])[0] for s in songs]
        metadata = self._metadata_snippets(identifiers)
        for song, identifier in zip(songs, identifiers):
            snippet = metadata.get(identifier, {})
            if snippet.get('channelTitle', '').endswith(' - Topic'):
                parsed = self._snippet_song(snippet)
                if parsed:
                    links = song.service_links
                    credits = parsed.artist.split(' & ')
                    if len(credits) != len(set(credits)):
                        parsed = self._music_recording(identifier) or song
                    parsed.service_links = links
                    self._artwork(parsed, snippet)
                    song = parsed
            yield song

    def search(self, query, n=2):
        """Yield music candidates using Data API search or public music search on quota exhaustion."""
        try:
            response = self._get(self._SEARCH_PATH, {
                "part": "snippet", "maxResults": n, "q": query,
                "type": "video", "videoCategoryId": "10",
            })
        except QuotaExceeded:
            for song in self._enrich_music_songs(search_music(query, n)):
                yield search_links(song, "YouTube", song.service_links["YouTube"])
            return
        if "error" in response:
            raise ValueError("YouTube search unavailable")
        entries = response.get('items', [])[:n]
        topic_ids = [entry.get('id', {}).get('videoId') for entry in entries
                     if isinstance(entry.get('id'), dict)
                     and entry.get('snippet', {}).get('channelTitle', '').endswith(' - Topic')]
        topic_ids = [identifier for identifier in topic_ids if isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier)]
        full_snippets = self._metadata_snippets(topic_ids)
        for entry in entries:
            if not isinstance(entry.get("id"), dict) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", entry["id"].get("videoId", "")):
                continue
            snippet = full_snippets.get(entry['id']['videoId'], entry.get("snippet", {}))
            song = self._snippet_song(snippet)
            if song is None:
                continue
            self._artwork(song, snippet)
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
            "music.youtube.com",
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
        try:
            response = self._get("https://www.googleapis.com/youtube/v3/videos",
                                 {"part": "snippet,contentDetails", "id": identifier})
        except Exception:
            response = {"items": []}
        nonmusic_rejected = False
        for entry in response.get("items", []):
            snippet = entry.get("snippet", {})
            song = self._snippet_song(snippet)
            category = snippet.get('categoryId')
            if category == '10':
                song = self._catalogue_cover(snippet, entry.get('contentDetails', {}).get('duration', '')) or song
                if song and snippet.get('description', '').startswith('Provided to YouTube by '):
                    credits = song.artist.split(' & ')
                    if len(credits) != len(set(credits)):
                        precise = self._music_recording(identifier)
                        if precise and normalized(precise.title) == normalized(song.title):
                            song = precise
            if song is None or (category is not None and category != '10'):
                try:
                    music = video_music_metadata(identifier)
                except Exception:
                    music = None
                if music is None and song is not None and re.search(r'\((?:ft|feat)\.?\s+', snippet.get('title', ''), re.I):
                    try:
                        confirmed = any(same_recording(song, candidate.title, candidate.artist)
                                        for candidate in search_music(recording_query(song), 5))
                        if confirmed:
                            music = {'confirmed_recording': True}
                    except Exception:
                        pass
                if music:
                    if song is None:
                        artist = ' & '.join(a.get('name', '') for a in music['artists'] if a.get('name'))
                        song = self._snippet_song({'title': music['title'], 'channelTitle': artist}) or Song(music['title'], artist, '')
                        header = re.split(r'\s+[-–—]\s+', snippet.get('title', ''), maxsplit=1)[0]
                        if normalized(alias_text(header)) == normalized(alias_text(song.artist)):
                            song.artist = header
                else:
                    song = None
                    if category is not None and category != '10':
                        nonmusic_rejected = True
            if song is not None:
                duration = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', entry.get('contentDetails', {}).get('duration', ''))
                if duration:
                    hours, minutes, seconds = (float(v or 0) for v in duration.groups())
                    song.duration_ms = int((hours * 3600 + minutes * 60 + seconds) * 1000)
                song.service_links = {**getattr(song, 'service_links', {}), self.service_name(): link}
                self._artwork(song, entry.get("snippet", {}))
                return song
        try:
            metadata = loads(fetch_text("https://www.youtube.com/oembed", YOUTUBE_HOSTS,
                                        params={"url": link, "format": "json"}))
            song = self._snippet_song({"title": metadata.get("title", ""),
                                       "channelTitle": metadata.get("author_name", "")})
            if song and not nonmusic_rejected:
                song.service_links = {self.service_name(): link}
                self._artwork(song, {"thumbnails": {"default": {"url": metadata.get("thumbnail_url", "")}}})
                return song
        except Exception:
            pass
        if not nonmusic_rejected:
            try:
                music = video_music_metadata(identifier)
                if music:
                    artist = ' & '.join(a.get('name', '') for a in music['artists'] if a.get('name'))
                    song = self._snippet_song({'title': music['title'], 'channelTitle': artist}) or Song(music['title'], artist, '')
                    song.service_links = {self.service_name(): link}
                    return song
            except Exception:
                pass
        raise ValueError("YouTube metadata does not establish song and performer")

    @staticmethod
    def _music_recording(identifier):
        """Read official music metadata for exactly the requested video ID."""
        try:
            music = video_music_metadata(identifier)
            if not music:
                return None
            song = Song(music['title'], ' & '.join(a['name'] for a in music['artists']), '')
            length = str(music.get('length', ''))
            if re.fullmatch(r'\d+:\d{2}(?::\d{2})?', length):
                total = 0
                for part in length.split(':'):
                    total = total*60+int(part)
                song.duration_ms = total*1000
            song.service_links = {'YouTube': 'https://www.youtube.com/watch?v='+identifier}
            return song
        except Exception:
            return None

    @staticmethod
    def _catalogue_cover(snippet, duration):
        """Resolve a group cover using uploader + group credits and duration."""
        match = re.fullmatch(r'(.+?)\s+[-–—]\s+.+?【([^【】]+?)\s+Cover】', unescape(snippet.get('title', '')), re.I)
        timing = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', duration)
        uploader = snippet.get('channelTitle', '').strip()
        description = snippet.get('description', '')
        # A generic reupload title is insufficient evidence of performer identity.
        if not match or not timing or not uploader or not re.search(r'\bVocalists:\s*[\s\S]*@'+re.escape(uploader)+r'(?![\w])', description, re.I):
            return None
        title, group = match.group(1).strip(), match.group(2).strip()
        seconds = [float(v or 0) for v in timing.groups()]
        duration_ms = int((seconds[0]*3600+seconds[1]*60+seconds[2])*1000)
        try:
            from .spotify import Spotify
            for candidate in Spotify().search(title+' '+group, n=5):
                credits = {normalized(alias_text(a)) for a in re.split(r'\s*[&,;]\s*', candidate.artist)}
                if (normalized(candidate.title) == normalized(title)
                        and {normalized(alias_text(group)), normalized(alias_text(uploader))} <= credits
                        and durations_match(duration_ms, getattr(candidate, 'duration_ms', None)) is True):
                    candidate.service_links = {'Spotify': candidate.service_links['Spotify']}
                    return candidate
        except Exception:
            pass
        return Song(title+' (Cover by '+group+')', group+' & '+uploader, '')

    @staticmethod
    def _duration_ms(value):
        """Parse an ISO 8601 video duration into milliseconds when supported."""
        match = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', value)
        if match:
            hours,minutes,seconds = (float(v or 0) for v in match.groups())
            return int((hours*3600+minutes*60+seconds)*1000)
        return None

    @staticmethod
    def _artwork(song, snippet):
        """Attach duration and the largest safe YouTube thumbnail from a snippet."""
        if snippet.get('_duration_ms'):
            song.duration_ms = snippet['_duration_ms']
        images = snippet.get("thumbnails", {})
        for size in ("maxres", "standard", "high", "medium", "default"):
            url = images.get(size, {}).get("url", "")
            if valid_url(url, {"i.ytimg.com"}):
                song.cover_art = {"url": url}
                break

    @staticmethod
    def _snippet_song(snippet):
        """Extract recording identity only when snippet credits establish the performer."""
        title = unescape(snippet.get("title", ""))
        channel = unescape(snippet.get("channelTitle", ""))
        if re.search(r'\bteaser\b|#shorts\b|\bOUT NOW\b|YouTube Music Weekend|全\d+曲|\b(?:interview|podcast|vlog|livestream)\b|\b(?:интервью|подкаст|стрим)\b', title, re.I):
            return None
        title = re.sub(r'\s*\(Prod(?:uced)?\.?\s+[^)]+\)', '', title, flags=re.I)
        title = re.sub(r'\s*[\(\[]премьера\s+клипа(?:\s+\d{4})?[\)\]]\s*$', '', title, flags=re.I)
        title = re.sub(r'\s+/\s+.+\s+(?:OP|ED|Opening|Ending)\s*$', '', title, flags=re.I)
        remix_cover = re.fullmatch(r'.+?\s+[-–—]\s+(.+?)\s*\(([^()]+?)\s+Cover Remix\)(?:\s+.+?\s*\[AMV\])?', title, flags=re.I)
        if remix_cover and normalized(remix_cover.group(2)) == normalized(channel.split(' - ')[0]):
            artist = remix_cover.group(2).strip()
            return Song(remix_cover.group(1).strip() + ' (Cover Remix by ' + artist + ')', artist, '')
        cover = re.fullmatch(r"(?:\[[^\]]+\]\s*)?(.+?)\s*\(cover\s+by\s+([^()]+)\)", title, flags=re.I)
        if cover and normalized(cover.group(2)) == normalized(channel):
            language = " (Russian Ver.)" if re.search(r"на\s+русском|\bRUS\b", title, re.I) else ""
            if re.search(r'на\s+английском|\bENG\b|\bEnglish\b', title, re.I) and not language:
                language = ' (English Ver.)'
            return Song(cover.group(1).strip() + language + " (Cover by " + cover.group(2).strip() + ")", channel, "")
        description = unescape(snippet.get("description", ""))
        if description.startswith("Provided to YouTube by ") and "Auto-generated by YouTube." in description:
            for line in description.splitlines():
                parts = line.split(" · ")
                if len(parts) >= 2 and normalized(parts[0]) == normalized(title):
                    return Song(parts[0], " & ".join(parts[1:]), "")
        if channel.endswith(" - Topic"):
            return Song(title, channel[:-8], "") if title else None
        official_channel = re.sub(r"\s+Official\s+YouTube$|VEVO$|Video$", "", channel, flags=re.I).strip()
        event_song = re.fullmatch(r'(.+?)\s*\((?:ft|feat)\.?\s+([^()]+)\)\s*\|\s*Worlds\s+\d{4}\s*[-–—]\s*(.+)', title, re.I)
        if event_song and normalized(alias_text(event_song.group(3))) == normalized(alias_text(official_channel)):
            guests = re.split(r',\s*(?:and\s+)?|\s+&\s+', event_song.group(2), flags=re.I)
            return Song(event_song.group(1).strip(), ' & '.join([channel, *[guest.strip() for guest in guests]]), '')
        japanese = re.fullmatch(r'【(?:オリジナル楽曲|オリジナル曲)】\s*(.+?)\s*/\s*(.+?)(?:【[^】]+】)?', title)
        if japanese:
            credits = re.split(r'\s+vs\.?\s+', japanese.group(2), flags=re.I)
            credits = [re.sub(r'\s*[(（]\s*\d+\s*[)）]', '', value).strip() for value in credits]
            if credits and all(normalized(alias_text(value)) == normalized(alias_text(official_channel)) for value in credits):
                return Song(japanese.group(1).strip(), channel, '')
        quoted = re.fullmatch(r'(.+?)\s*\|\s*["“](.+?)["”]\s*Music Video', title, flags=re.I)
        if quoted and normalized(alias_text(quoted.group(1))) == normalized(alias_text(official_channel)):
            return Song(quoted.group(2), quoted.group(1), "")
        decorated = re.fullmatch(r"(.+?)[『｢「](.+?)[』｣」]\s*(?:MUSIC\s+CLIP|MUSIC\s+VIDEO)", title, flags=re.I)
        if decorated and normalized(decorated.group(1)) == normalized(official_channel):
            return Song(decorated.group(2), decorated.group(1), "")
        title = re.sub(r"\s*[\(\[](?:official\s+(?:(?:lyrics?|music)\s+)?(?:video|audio)|official\s+lyrics?|lyrics?\s+video|официальный\s+клип)[\)\]]\s*$",
                       "", title, flags=re.I)
        title = re.sub(r'\s*[\(\[]official\s+(?:(?:music|lyric|lyrics)\s+)?(?:MV|video|audio|visualizer)[\)\]](?:\s*\[[^\]]+\])*\s*$', '', title, flags=re.I)
        title = re.sub(r"\s*\|\s*(?:AUDIO|OFFICIAL\s+AUDIO|OFFICIAL\s+MUSIC\s+VIDEO|LYRIC\s+VIDEO)\s*\|\s*$", "", title, flags=re.I)
        parts = re.split(r"\s*[-–—]\s+", title, maxsplit=1)
        artists = re.split(r'\s*(?:&|,|\bfeat\.?\s+|\bft\.?\s+|\bfeaturing\s+)\s*', parts[0], flags=re.I)
        def channel_matches(artist):
            identity = normalized(alias_text(artist))
            uploader = normalized(alias_text(official_channel))
            return identity == uploader or (identity == 'aiobahn81' and uploader == 'aiobahn')
        if len(parts) == 2 and channel and any(channel_matches(a) for a in artists):
            performer = ' & '.join(a.strip() for a in artists)
            bilingual = re.fullmatch(r'''["“'](.+?)["”']\s*[/|]\s*["“'](.+?)["”']''', parts[1])
            if bilingual:
                return Song(bilingual.group(1), performer, "")
            return Song(parts[1], performer, "")
        return None

    def song_to_link(self, song):
        # Official video metadata identifies the recording even when its intro
        # or credits make the clip longer than the catalogue audio track.
        """Prefer a matching official clip, then try verified audio and explicit search fallback."""
        try:
            videos = search_music(recording_query(song), 10, prefer_videos=True)
            identifiers = [parse_qs(urlparse(c.service_links['YouTube']).query).get('v', [''])[0]
                           for c in videos if getattr(c, 'video_type', None) == 'MUSIC_VIDEO_TYPE_OMV']
            snippets = self._metadata_snippets(identifiers) if identifiers else {}
            for candidate in videos:
                identifier = parse_qs(urlparse(candidate.service_links['YouTube']).query).get('v', [''])[0]
                label = snippets.get(identifier, {}).get('title', '')
                # YouTube Music also labels official audio uploads as OMV.
                if re.search(r'\b(?:official\s+audio|lyric(?:s)?\s+video|visualizer|live|concert)\b|официальное\s+аудио|концерт', label, re.I):
                    continue
                if (getattr(candidate, 'video_type', None) == 'MUSIC_VIDEO_TYPE_OMV'
                        and same_recording(song, candidate.title, candidate.artist)):
                    return candidate.service_links['YouTube']
        except Exception:
            pass
        query = self._format_song_query(song)
        try:
            response = self._get(self._SEARCH_PATH, {
                "part": "snippet", "maxResults": 10, "q": query, "type": "video",
            })
        except QuotaExceeded:
            response = {"items": []}
        topic_ids = [entry.get('id', {}).get('videoId') for entry in response.get('items', [])
                     if isinstance(entry.get('id'), dict) and entry.get('snippet', {}).get('channelTitle', '').endswith(' - Topic')]
        metadata = self._metadata_snippets(topic_ids)
        credit_checks = 0
        for entry in response.get("items", []):
            if not isinstance(entry.get("id"), dict) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", entry["id"].get("videoId", "")):
                continue
            full = metadata.get(entry['id']['videoId'], entry.get("snippet", {}))
            candidate = self._snippet_song(full)
            if candidate:
                self._artwork(candidate, full)
            if candidate and same_recording(song, candidate.title, candidate.artist, duration_ms=getattr(candidate, 'duration_ms', None)):
                return self._video_link(entry)
            if (candidate and entry['id']['videoId'] in metadata and credit_checks < 2
                    and normalized(candidate.title) == normalized(song.title)):
                credit_checks += 1
                precise = self._music_recording(entry['id']['videoId'])
                if precise and same_recording(song, precise.title, precise.artist,
                                              duration_ms=getattr(precise, 'duration_ms', None)):
                    return self._video_link(entry)
        # Search snippets may reference the official upload when it is absent
        # from the results. Treat references only as IDs to verify independently.
        references = []
        for entry in response.get('items', []):
            for identifier in re.findall(
                    r'official\s+(?:music\s+)?video\s*:\s*https://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])',
                    entry.get('snippet', {}).get('description', ''), re.I):
                if identifier not in references:
                    references.append(identifier)
        if not references:
            try:
                broader = self._get(self._SEARCH_PATH, {
                    'part': 'snippet', 'maxResults': 5,
                    'q': query.removesuffix(' topic'), 'type': 'video',
                })
                for entry in broader.get('items', []):
                    references.extend(re.findall(
                        r'official\s+(?:music\s+)?video\s*:\s*https://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])',
                        entry.get('snippet', {}).get('description', ''), re.I))
            except Exception:
                pass
        for identifier, snippet in self._metadata_snippets(references[:2]).items():
            candidate = self._snippet_song(snippet)
            if snippet.get('categoryId') == '10' and candidate and same_recording(song, candidate.title, candidate.artist):
                return 'https://www.youtube.com/watch?v=' + identifier
        try:
            for candidate in self._enrich_music_songs(search_music(self._format_song_query(song).removesuffix(" topic"), 10)):
                if same_recording(song, candidate.title, candidate.artist, duration_ms=getattr(candidate, 'duration_ms', None)):
                    return candidate.service_links["YouTube"]
        except Exception:
            pass
        return self._search_url(query)
