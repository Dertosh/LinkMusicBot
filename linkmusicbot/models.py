class Album:
    """Class to represent an album."""

    def __init__(self, title, artist):
        """Initialize the album."""
        self.title = str(title)
        self.artist = str(artist)
        self.cover_art = None

    def __repr__(self):
        """Return a developer-readable representation of the music item."""
        return "Album({!r}, {!r})".format(self.title, self.artist)

    def __str__(self):
        """Return the item's human-readable title and artist description."""
        return "{} by {}".format(self.title, self.artist)


class Song:
    """Class to represent a song."""

    def __init__(self, title, artist, album):
        """Initialize the song."""
        self.title = str(title)
        self.artist = str(artist)
        self.album = str(album)
        self.cover_art = None

    def __repr__(self):
        """Return a developer-readable representation of the music item."""
        return "Song({!r}, {!r}, {!r})".format(self.title, self.artist, self.album)

    def __str__(self):
        """Return the item's human-readable title and artist description."""
        return "{} â€” {}".format(self.artist, self.title)
