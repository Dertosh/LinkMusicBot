"""Normalize proven spelling equivalents without guessing a recording version."""
import re
import unicodedata
from html import unescape


def clean_query(value):
    """Remove search decoration and normalize spacing while preserving version markers."""
    value = unescape(value)
    value = re.sub(r"\b(?:official\s+)?(?:music\s+clip|music\s+video|lyrics?\s+video)\b", "", value, flags=re.I)
    value = re.sub(r"ляшки\s*такие\s*вкусня", "ляшкивкусня", value, flags=re.I)
    value = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", value)
    return " ".join(value.split()).strip()


def alias_text(value):
    """Normalize explicitly verified artist and title spelling equivalents."""
    value = unicodedata.normalize("NFKC", unescape(value)).casefold()
    value = re.sub(r'(?<!\w)(?:филипп\s+киркоров|(?:philipp|filipp)\s+kirkorov)(?!\w)', 'philipp kirkorov', value)
    # The same artist is credited in English on Apple and Russian on Spotify.
    value = re.sub(r'(?<!\w)(?:женя\s+любич|(?:jenia|zhenya|zhenia)\s+lubich)(?!\w)', 'jenia lubich', value)
    value = value.replace("'", "").replace("’", "").replace("`", "")
    value = re.sub(r"глюк(?:оза|oz[аa])|glukoza", "glukoza", value)
    value = re.sub(r"(?<!\w)(?:maksim|макsим)(?!\w)", "maksim", value)
    value = re.sub(r"(?<!\w)kid phenomenon from exile tribe(?!\w)", "kid phenomenon", value)
    value = re.sub(r"(?<!\w)александр\s+рыбак(?!\w)", "alexander rybak", value)
    value = re.sub(r"(?<!\w)александр\s+ревва(?!\w)", "артур пирожков", value)
    value = re.sub(r"(?<!\w)котик(?!\w)", "kotik", value)
    value = re.sub(r"(?<!\w)ленинград(?!\w)", "leningrad", value)
    value = re.sub(r'(?<!\w)league of legends music(?!\w)', 'league of legends', value)
    value = value.replace('ななひら', 'nanahira')
    value = value.replace('陳銳', 'ray chen')
    value = value.replace('宝鐘マリン', 'houshou marine')
    value = re.sub(r'(?<!\w)jung kook of bts(?!\w)', 'jung kook', value)
    value = value.replace('しぐれうい', 'ui shigure')
    value = re.sub(r"(?<!\w)shigure\s+ui(?!\w)", 'ui shigure', value)
    value = value.replace('ウィマーマ・サーガ', 'uima ma saga')
    value = re.sub(r"(?<!\w)uima[-\s]+ma\s+saga(?!\w)", 'uima ma saga', value)
    return re.sub(r"(?<!\w)(?:yolka|ёлка|elka)(?!\w)", "yolka", value)
