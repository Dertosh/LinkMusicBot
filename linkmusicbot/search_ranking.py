"""Rank search results without changing the selected recording or its links."""
from html import unescape
import re
import unicodedata


VERSION = re.compile(r"\b(?:remix|mix|live|acoustic|instrumental|karaoke|tv\s*size|sped\s*up|slowed|remaster(?:ed)?|ремикс|лайв|акустика|караоке)\b", re.I)


def _normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", unescape(value)).casefold())


def search_rank(title, query):
    requested = VERSION.search(query)
    version = VERSION.search(title)
    base = re.sub(r"[\(\[]([^\)\]]*)[\)\]]",
                  lambda m: "" if VERSION.search(m.group(1)) or
                  re.match(r"\s*(?:feat\.?|ft\.?|featuring)\s", m.group(1), re.I)
                  else m.group(0), title)
    # Spotify often uses 'Song - Remix' instead of parentheses.
    base = re.sub(r"\s+[-–—]\s+.*$", "", base) if version else base
    base = _normalized(base)
    relevant = len(base) if base and base in _normalized(query) else 0
    preferred = (bool(version) and version.group().casefold() == requested.group().casefold()
                 if requested else not version)
    return relevant, int(preferred)


def rank_results(results, query):
    if "://" in query:
        return results
    return sorted(results, key=lambda item: search_rank(item.title, query), reverse=True)
