"""Explainable recording similarity. Scores are evidence scores, not probabilities."""
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
import re
import unicodedata
from anyascii import anyascii


def romanized(value):
    return ' '.join(anyascii(unicodedata.normalize('NFKC', unescape(value or ''))).split())


def romanized_variants(value):
    # Both i and y are used for Cyrillic й in real catalogue spellings.
    original = romanized(value)
    alternative = romanized(re.sub('й', 'y', value or '', flags=re.I))
    return list(dict.fromkeys([original, alternative]))


def words(value, transliterate=False):
    value = unicodedata.normalize('NFKC', unescape(value or '')).casefold()
    if transliterate:
        value = romanized(value).casefold()
    return re.findall(r'[^\W_]+', value.replace('’', '').replace("'", ''))


def compact(value, transliterate=False):
    return ''.join(words(value, transliterate))


def artist_signatures(artists):
    variants = [romanized_variants(a) for a in artists]
    return [Counter(compact(v[index]) for v in variants) for index in (0, -1)]


VERSION = re.compile(r'\b(?:remix|mix|edit|live|acoustic|instrumental|karaoke|cover|opening|tv|sped|slowed|remaster(?:ed)?|ремикс|микс|лайв|акустика|инструментал|караоке|кавер|ускоренн\w*|замедленн\w*)\b', re.I)


@dataclass(frozen=True)
class RecordingMatch:
    status: str
    score: float
    title_percent: float
    artist_percent: float
    duration_match: object
    isrc_match: object
    reasons: tuple


def evaluate(expected_title, actual_title, expected_artists, actual_artists, timing=None,
             source_isrc=None, actual_isrc=None):
    native_exact = bool(compact(expected_title)) and compact(expected_title) == compact(actual_title)
    left, right = words(expected_title), words(actual_title)
    left_ascii, right_ascii = words(expected_title, True), words(actual_title, True)
    translit_exact = bool(left_ascii) and compact(expected_title, True) == compact(actual_title, True)
    order_exact = bool(left) and Counter(left) == Counter(right) and len(left) >= 2
    common = sum((Counter(left_ascii) & Counter(right_ascii)).values())
    overlap = common / max(len(left_ascii), len(right_ascii), 1)
    similarity = SequenceMatcher(None, ' '.join(left_ascii), ' '.join(right_ascii)).ratio()
    title_score = 1.0 if native_exact or order_exact else 0.98 if translit_exact else (overlap+similarity)/2
    native_artists = bool(expected_artists) and expected_artists == actual_artists
    expected_variants = artist_signatures(expected_artists)
    actual_variants = artist_signatures(actual_artists)
    translit_artists = bool(expected_artists) and any('' not in a and a == b for a in expected_variants for b in actual_variants)
    artist_overlap = max(sum((a & b).values()) / max(sum(a.values()), sum(b.values()), 1) for a in expected_variants for b in actual_variants)
    artist_score = 1.0 if native_artists else 0.98 if translit_artists else artist_overlap
    isrc = (source_isrc.casefold() == actual_isrc.casefold()
            if isinstance(source_isrc, str) and source_isrc and isinstance(actual_isrc, str) and actual_isrc else None)
    evidence = [(title_score, 0.55), (artist_score, 0.35)]
    if timing is not None:
        evidence.append((int(timing), 0.10))
    score = round(100*sum(v*w for v,w in evidence)/sum(w for _,w in evidence), 1)
    def result(status, *reasons):
        return RecordingMatch(status, score, round(title_score*100, 1), round(artist_score*100, 1), timing, isrc, reasons)
    if timing is False:
        return result('different', 'duration_conflict')
    if isrc is False:
        return result('unverified', 'different_isrc_requires_review')
    if not (native_artists or translit_artists):
        return result('unverified', 'incomplete_or_different_performer_credits')
    # Never fuzzy-match away a named version or a remix credit.
    if not native_exact and (VERSION.search(expected_title) or VERSION.search(actual_title)):
        return result('unverified', 'version_requires_exact_match')
    if isrc is True:
        return result('match', 'same_isrc', 'performers_match')
    if not native_artists and timing is not True:
        return result('unverified', 'transliterated_performers_need_metadata')
    if native_exact or order_exact:
        return result('match', 'title_words_match', 'performers_match')
    if translit_exact and timing is True:
        return result('match', 'transliterated_title_match', 'duration_and_performers_match')
    if timing is True and min(len(left_ascii), len(right_ascii)) >= 3 and overlap >= 0.85:
        return result('match', 'title_words_overlap', 'duration_and_performers_match')
    return result('unverified', 'insufficient_title_or_metadata_evidence')
