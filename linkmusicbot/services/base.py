from ..models import Album, Song
from urllib.parse import quote, urlencode
from html import unescape
import re
import unicodedata


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", unescape(value or "")).casefold())


def recording_identity(title, artist):
    """Move explicit guest credits into artists without stripping versions."""
    guests = []
    def guest(match):
        guests.append(match.group(1))
        return ""
    title = re.sub(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+([^\)\]]+)[\)\]]", guest,
                   unescape(title or ""), flags=re.I)
    artists = re.split(r"\s*(?:&|,|;|\bfeat\.?\s+|\bft\.?\s+|\bfeaturing\s+)\s*",
                       unescape(artist or ""), flags=re.I)
    for value in guests:
        artists.extend(re.split(r"\s*[&,;]\s*", value))
    return title.strip(), sorted({normalized(a) for a in artists if normalized(a)})


def same_recording(item, title, artist):
    expected_title, expected_artists = recording_identity(item.title, item.artist)
    actual_title, actual_artists = recording_identity(title, artist)
    return bool(expected_artists) and expected_artists == actual_artists and normalized(expected_title) == normalized(actual_title)


def recording_query(item):
    guests = re.findall(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+([^\)\]]+)[\)\]]",
                        item.title, flags=re.I)
    title, _ = recording_identity(item.title, item.artist)
    return " ".join([title, item.artist, *guests]).strip()


def search_links(item, source, link):
    term = f"{item.title} {item.artist}".strip()
    item.service_links = {
        "Apple Music": "https://music.apple.com/us/search?" + urlencode({"term": term}),
        "Spotify": "https://open.spotify.com/search/" + quote(term, safe=""),
        "YouTube": "https://www.youtube.com/results?" + urlencode({"search_query": term}),
        "Яндекс Музыка": "https://music.yandex.ru/search?" + urlencode({"text": term}),
    }
    item.service_links[source] = link
    return item


class ServiceHandler:
    """Parent class for processing and returning links of various services."""

    @staticmethod
    def service_name():
        """Get the name of the service."""
        raise NotImplementedError()

    def album_to_link(self, album):
        """Take an Album and return a link."""
        raise NotImplementedError()

    def can_handle_link(self, link):
        """Returns True if and only if the class can handle the provided link."""
        raise NotImplementedError()

    def link_is_song(self, link):
        """Returns True if the link is a song, False if it is an album."""
        raise NotImplementedError()

    def link_to_album(self, link):
        """Take a link and return an Album."""
        raise NotImplementedError()

    def link_to_object(self, link):
        """Take a link and return an Album or a Song."""
        return (
            self.link_to_song(link)
            if self.link_is_song(link)
            else self.link_to_album(link)
        )

    def link_to_song(self, link):
        """Take a link and return a Song."""
        raise NotImplementedError()

    def song_to_link(self, song):
        """Take a Song and return a link."""
        raise NotImplementedError()

    def object_to_link(self, obj):
        """Take a Song or Album and return a link."""
        return (
            self.song_to_link(obj) if isinstance(obj, Song) else self.album_to_link(obj)
        )
