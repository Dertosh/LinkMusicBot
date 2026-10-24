"""Rank search results without changing the selected recording or its links."""
from html import unescape
import re
import unicodedata
from difflib import SequenceMatcher
from .query_text import clean_query, alias_text
from .recording_match import romanized, romanized_variants
from urllib.parse import urlparse


VERSION = re.compile(r"\b(?:remix|mix|edit|live|acoustic|instrumental|karaoke|cover|tv\s*size|sped\s*up|slowed|remaster(?:ed)?|ремикс|лайв|акустика|караоке|кавер)\b", re.I)


def _normalized(value):
    """Build a compact comparison key using query cleanup and verified spelling aliases."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", alias_text(clean_query(value))).casefold())


def search_rank(title, query):
    """Rank title relevance and prefer original versions unless a version was requested."""
    requested = VERSION.search(query)
    version = VERSION.search(title)
    base = re.sub(r"[\(\[]([^\)\]]*)[\)\]]",
                  lambda m: "" if VERSION.search(m.group(1)) or
                  re.match(r"\s*(?:feat\.?|ft\.?|featuring)\s", m.group(1), re.I)
                  else m.group(0), title)
    # Spotify often uses 'Song - Remix' instead of parentheses.
    base = re.sub(r"\s+[-–—]\s+.*$", "", base) if version else base
    base = re.sub(r'\s*(?:[-–—]\s*)?[\(\[]*\s*prod\.?\s*by\s+[^)\]]+[)\]]*\s*$', '', base, flags=re.I)
    base = _normalized(base)
    query_text = _normalized(query)
    relevant = len(base) if base and base in query_text else 0
    if not relevant and query_text and base.startswith(query_text):
        relevant = 1
    preferred = (bool(version) and version.group().casefold() == requested.group().casefold()
                 if requested else not version)
    return relevant, int(preferred), -len(title)


def rank_results(results, query):
    """Order search candidates by relevance, artist match, version, and verified links."""
    if "://" in query:
        return results
    def rank(item):
        relevance, preferred, length = search_rank(item.title, query)
        artist = getattr(item, "artist", None) or getattr(item, "description", "") or ""
        artist_match = bool(artist) and _normalized(artist) in _normalized(query)
        links = list(getattr(item, 'service_links', {}).values())
        markup = getattr(item, 'reply_markup', None)
        if markup:
            links.extend(button.url for row in markup.inline_keyboard for button in row if button.url)
        confirmed = sum(not any(part in urlparse(url).path.split('/') for part in ('search', 'results')) for url in links if url)
        return relevance, int(artist_match), preferred, confirmed, length
    return sorted(results, key=rank, reverse=True)


def query_matches(title, artist, query):
    """Require each query token to match title or performer words across supported scripts."""
    def words(value, aliases=True):
        value = clean_query(value)
        value = unicodedata.normalize("NFKD", alias_text(value) if aliases else unescape(value)).casefold()
        value = "".join(c for c in value if not ("\u0300" <= c <= "\u036f"))
        value = value.replace("'", "").replace("’", "")
        return re.findall(r"[^\W_]+", value)
    requested = words(query)
    available = words(title + " " + artist) + words(title + " " + artist, aliases=False)
    for latin in romanized_variants(title+' '+artist):
        available.extend(words(latin, aliases=False))
    def matches(token, word):
        if word.startswith(token):
            return True
        latin_token = re.sub(r'\W+', '', romanized(token)).casefold()
        latin_word = re.sub(r'\W+', '', romanized(word)).casefold()
        if latin_token and latin_word.startswith(latin_token):
            return True
        if any(re.sub(r'\W+', '', w).casefold().startswith(re.sub(r'\W+', '', t).casefold())
               for t in romanized_variants(token) for w in romanized_variants(word) if t and w):
            return True
        return len(token) >= 5 and len(word) >= 5 and SequenceMatcher(None, token, word).ratio() >= 0.82
    return bool(requested) and all(any(matches(token, word) for word in available) for token in requested)
