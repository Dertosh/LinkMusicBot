from ..models import Album, Song
from urllib.parse import quote, urlencode


def search_links(item, source, link):
    term = f"{item.title} {item.artist}".strip()
    item.service_links = {
        "Apple Music": "https://music.apple.com/us/search?" + urlencode({"term": term}),
        "Spotify": "https://open.spotify.com/search/" + quote(term, safe=""),
        "YouTube": "https://www.youtube.com/results?" + urlencode({"search_query": term}),
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
