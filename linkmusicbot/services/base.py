from ..models import Album, Song
from urllib.parse import quote, urlencode
from html import unescape
import re
import unicodedata
import math
from ..settings import secrets
from ..recording_match import romanized, romanized_variants, evaluate, RecordingMatch


def durations_match(expected, actual):
    """Allow rounding and short padding, with an absolute upper bound."""
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and v > 0 for v in (expected, actual)):
        return None
    tolerance = min(10000, max(secrets.get('duration_tolerance_ms', 3000), min(expected, actual) * 0.015))
    return abs(expected - actual) <= tolerance
from ..query_text import clean_query, alias_text


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", unescape(value or "")).casefold())


def query_variants(query):
    query = clean_query(query)
    variants = [query]
    plain = unescape(query).replace("’", "").replace("'", "")
    plain = "".join(c for c in unicodedata.normalize("NFKD", plain) if not unicodedata.combining(c))
    if plain != query:
        variants.append(plain)
    aliased = alias_text(plain)
    if aliased != plain.casefold():
        variants.append(aliased)
    for latin in romanized_variants(aliased):
        if latin and latin.casefold() not in {v.casefold() for v in variants}:
            variants.append(latin)
    return variants


def recording_identity(title, artist):
    """Move explicit guest credits into artists without stripping versions."""
    guests = []
    def guest(match):
        guests.append(match.group(1))
        return ""
    title = re.sub(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+([^\)\]]+)[\)\]]", guest,
                   unescape(title or ""), flags=re.I)
    # Unbracketed guest credits stop before a separately labelled version.
    title = re.sub(r'\s+(?:feat\.?|ft\.?|featuring)\s+(.+?)(?=\s+[-–—]\s+|$)', guest, title, flags=re.I)
    title = re.sub(r"\s*\(cover(?:\s+remix)?\s+by\s+([^()]+)\)",
                   lambda m: "" if normalized(m.group(1)) == normalized(artist) else m.group(0),
                   title, flags=re.I)
    if normalized(artist) == 'satiakura':
        title = re.sub(r'^Po\s+Jian\s*\|\s*Break\s+the\s+Cocoon\b', 'Po Jian', title, flags=re.I)
    artists = re.split(r"\s*(?:&|,|;|\bfeat\.?\s+|\bft\.?\s+|\bfeaturing\s+)\s*",
                       unescape(artist or ""), flags=re.I)
    for value in guests:
        artists.extend(re.split(r"\s*[&,;]\s*", value))
    # This game's catalogue credit is a project, not an extra performer.
    # Limit this exception to its two confirmed KOTOKO/Aiobahn recordings.
    identities = {normalized(alias_text(a)) for a in artists}
    if re.fullmatch(r'Enemy\s*(?:-\s*|\(\s*)from\s+(?:the\s+series\s+)?Arcane:?\s+League of Legends\)?', title.strip(), re.I) and 'imaginedragons' in identities:
        title = 'Enemy'
        artists = [a for a in artists if normalized(alias_text(a)) not in {'arcane', 'leagueoflegends'}]
    # Quoted film credits describe the source, not a remix/live version.
    title = re.sub(r'\s*\(из\s+(?:мультфильма|фильма|к\s*/\s*ф|м\s*/\s*ф)\s+[«"][^»"]+[»"]\)', '', title, flags=re.I)
    if {'postmalone', 'swaelee'} <= identities:
        title = re.sub(r'\s*(?:-\s*|\(\s*)Spider-Man:\s*Into the Spider-Verse\)?\s*$', '', title, flags=re.I)
    # The featured singer's group is an affiliation on this catalogue entry.
    if normalized(title) == 'leftandright' and {'charlieputh', 'jungkook'} <= identities:
        artists = [a for a in artists if normalized(a) != 'bts']
    # Arcane is a soundtrack project credit, omitted by Apple and Yandex.
    # Preserve the Opening Title version; it is not the full Enemy recording.
    opening_title = re.fullmatch(
        r'Enemy(?:\s+with\s+JID)?\s*(?:-\s*|\(\s*)Opening Title Version\)?'
        r'(?:\s*\(from the series Arcane League of Legends\))?', title.strip(), re.I)
    if opening_title and {'imaginedragons', 'jid'} <= identities:
        title = 'Enemy (Opening Title Version)'
        artists = [a for a in artists if normalized(a) != 'arcane']
    if (normalized(title) in {'internetyamero', 'internetoverdose'}
            and {'aiobahn81', 'kotoko'} <= identities):
        artists = [a for a in artists if normalized(a) != 'needygirloverdose']
    # Catalogues may list remixers as artists or only in the version credit.
    remix = re.search(r"(?:\(|\[|\s-\s)([^()\[\]]+?)\s+remix(?:\)|\]|$)", title, re.I)
    if remix:
        artists.extend(re.split(r"\s*[&,;]\s*", remix.group(1)))
    return title.strip(), sorted({normalized(alias_text(a)) for a in artists if normalized(a)})


def compare_recordings(item, title, artist, *, duration_ms=None, isrc=None):
    expected_title, expected_artists = recording_identity(item.title, item.artist)
    actual_title, actual_artists = recording_identity(title, artist)
    pattern = r"\s*(?:\(|-\s*)(russian|english|japanese|русская|английская)\s*(?:ver\.?|version|версия)\)?"
    expected_language = re.search(pattern, expected_title, re.I)
    actual_language = re.search(pattern, actual_title, re.I)
    if expected_language and actual_language and expected_language.group(1).casefold() != actual_language.group(1).casefold():
        return RecordingMatch('different', 0, 0, 0, None, None, ('language_version_conflict',))
    expected_title = re.sub(pattern, "", expected_title, flags=re.I)
    actual_title = re.sub(pattern, "", actual_title, flags=re.I)
    timing = durations_match(getattr(item, 'duration_ms', None), duration_ms)
    # Original Chacarron is credited jointly on Spotify and only to El Chombo
    # on YouTube Music. Accept this verified credit difference only with
    # matching duration; never extend it to 3.0, edits or other collaborators.
    if (timing is True
            and normalized(romanized(expected_title)) == normalized(romanized(actual_title)) == 'chacarron'
            and {frozenset(expected_artists), frozenset(actual_artists)} <= {
                frozenset({'elchombo'}), frozenset({'elchombo', 'andyval'})}):
        expected_artists = actual_artists = ['elchombo']
    return evaluate(alias_text(expected_title), alias_text(actual_title), expected_artists, actual_artists,
                    timing=timing, source_isrc=getattr(item, 'isrc', None), actual_isrc=isrc)


def same_recording(item, title, artist, *, duration_ms=None, isrc=None):
    return compare_recordings(item, title, artist, duration_ms=duration_ms, isrc=isrc).status == 'match'


def recording_query(item):
    guests = re.findall(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+([^\)\]]+)[\)\]]",
                        item.title, flags=re.I)
    guests.extend(re.findall(r'\s+(?:feat\.?|ft\.?|featuring)\s+(.+?)(?=\s+[-–—]\s+|$)', item.title, flags=re.I))
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
