"""Public YouTube Music metadata, bounded and independent of Data API quota."""
from functools import partial
import re

import requests
from ytmusicapi import YTMusic

from .models import Song
from .security import check_budget


def video_music_metadata(identifier):
    """Accept only the requested official music video, never radio suggestions."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier):
        return None
    check_budget()
    with requests.Session() as session:
        session.trust_env = False
        session.request = partial(session.request, timeout=3)
        tracks = YTMusic(requests_session=session).get_watch_playlist(videoId=identifier, limit=1).get('tracks', [])
    check_budget()
    return next((track for track in tracks if track.get('videoId') == identifier
                 and track.get('videoType') in ('MUSIC_VIDEO_TYPE_ATV', 'MUSIC_VIDEO_TYPE_OMV')
                 and track.get('title') and track.get('artists')), None)


def search_music(query, limit=10):
    query = query.replace(' & ', ' ')
    check_budget()
    with requests.Session() as session:
        session.trust_env = False
        session.request = partial(session.request, timeout=3)
        client = YTMusic(requests_session=session)
        data = client.search(query, limit=min(limit, 20), ignore_spelling=True)
        # Some official top cards omit artists; resolve their public metadata.
        for entry in data:
            if (entry.get('videoType') == 'MUSIC_VIDEO_TYPE_OMV' and not entry.get('artists')
                    and re.fullmatch(r'[A-Za-z0-9_-]{11}', entry.get('videoId', ''))):
                check_budget()
                details = client.get_song(entry['videoId']).get('videoDetails', {})
                if details.get('author'):
                    entry['artists'] = [{'name': details['author']}]
                    entry['title'] = details.get('title') or entry.get('title')
    check_budget()
    candidates = []
    for entry in data:
        identifier = entry.get('videoId', '')
        artists = entry.get('artists') or []
        artist = ' & '.join(a.get('name', '') for a in artists if a.get('name'))
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier) or not artist or not entry.get('title'):
            continue
        if entry.get('videoType') not in ('MUSIC_VIDEO_TYPE_ATV', 'MUSIC_VIDEO_TYPE_OMV'):
            continue
        from .services.youtube import YouTube
        song = YouTube._snippet_song({'title': entry['title'], 'channelTitle': artist})
        if song is None:
            song = Song(entry['title'], artist, (entry.get('album') or {}).get('name', ''))
        song.service_links = {'YouTube': 'https://www.youtube.com/watch?v=' + identifier}
        candidates.append((entry.get('videoType') != 'MUSIC_VIDEO_TYPE_ATV', song))
    return [song for _, song in sorted(candidates, key=lambda item: item[0])][:limit]
