"""Explicit live checks; never imported by unittest discovery or the bot."""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def is_direct(url):
    return not any(part in urlparse(url).path.split('/') for part in ('search', 'results'))


def main():
    parser = argparse.ArgumentParser(description='Run live music lookup checks without Telegram or SSH.')
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/live/search_cases.json')
    parser.add_argument('--title', help='Check a custom song instead of the fixture cases')
    parser.add_argument('--artist')
    parser.add_argument('--platforms', nargs='+', choices=['apple', 'spotify', 'yandex', 'youtube'], default=['apple', 'spotify', 'yandex', 'youtube'])
    parser.add_argument('--output', type=Path, default=ROOT / 'data/diagnostics/report.json')
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--channel-cases', action='store_true', help='Also check source videos from the artist-channel audit')
    parser.add_argument('--verify-metadata', action='store_true', help='Read direct result metadata and verify the selected recording')
    parser.add_argument('--candidates', action='store_true', help='Include up to 10 candidates per platform with similarity evidence')
    args = parser.parse_args()
    if args.title and not args.artist:
        parser.error('--title requires --artist')
    if not 1 <= args.timeout <= 120:
        parser.error('--timeout must be between 1 and 120 seconds')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Separate persistent API counter: no production catalogue is opened.
    os.environ['MUSIC_CACHE_PATH'] = str(args.output.parent / 'quota.sqlite3')
    logging.disable(logging.CRITICAL)
    from linkmusicbot.models import Song
    from linkmusicbot.settings import secrets
    from linkmusicbot.services import AppleMusic, Spotify, YandexMusic, YouTube
    from linkmusicbot.services.base import same_recording, compare_recordings
    from dataclasses import asdict
    from linkmusicbot.security import request_budget
    from linkmusicbot.youtube_music import search_music
    cases = ([{'title': args.title, 'artist': args.artist, 'platforms': args.platforms}]
             if args.title else json.loads(args.cases.read_text(encoding='utf-8')))
    if args.channel_cases:
        channel_cases = json.loads((ROOT / 'tests/live/youtube_channel_cases.json').read_text(encoding='utf-8'))
        cases.extend({'title': c['title'], 'artist': c['artist'], 'platforms': args.platforms,
                      'source_url': 'https://youtu.be/' + c['video']} for c in channel_cases)
    factories = {'apple': AppleMusic, 'spotify': Spotify, 'yandex': YandexMusic, 'youtube': YouTube}
    services = {}
    report = {'created': datetime.now(timezone.utc).isoformat(), 'results': []}
    for case in cases:
        song = Song(case['title'], case['artist'], '')
        song.duration_ms = case.get('duration_ms')
        song.isrc = case.get('isrc')
        if case.get('source_url'):
            source_row = {'title': song.title, 'artist': song.artist, 'platform': 'youtube_source', 'url': case['source_url']}
            try:
                with request_budget(args.timeout):
                    if 'youtube' not in services:
                        services['youtube'] = YouTube()
                    parsed = services['youtube'].link_to_song(case['source_url'])
                source_row['status'] = 'direct' if same_recording(song, parsed.title, parsed.artist) else 'mismatch'
                source_row['parsed'] = {'title': parsed.title, 'artist': parsed.artist}
            except Exception as error:
                source_row.update(status='error', error=type(error).__name__)
            report['results'].append(source_row)
            print(f"youtube_source: {song.title} — {source_row['status']}", flush=True)
        for platform in case.get('platforms', args.platforms):
            row = {'title': song.title, 'artist': song.artist, 'platform': platform}
            try:
                if platform == 'spotify' and not all(secrets.get(k) for k in ('spotify_client_id', 'spotify_client_secret')):
                    row['status'] = 'skipped'
                    row['reason'] = 'Missing Spotify credentials'
                else:
                    with request_budget(args.timeout):
                        if platform == 'youtube' and not secrets.get('youtube_token'):
                            candidates = search_music(f'{song.title} {song.artist}', 10)
                            matches = [c for c in candidates if same_recording(song, c.title, c.artist)]
                            row['provider'] = 'YouTube Music'
                            row['url'] = matches[0].service_links['YouTube'] if matches else None
                            row['status'] = 'direct' if matches else 'not_found'
                            row['candidates'] = [{'title': c.title, 'artist': c.artist, 'url': c.service_links['YouTube']} for c in candidates]
                        else:
                            if platform not in services:
                                services[platform] = factories[platform]()
                            url = services[platform].song_to_link(song)
                            from linkmusicbot.security import youtube_music_url
                            row.update(url=youtube_music_url(url) if platform == 'youtube' else url,
                                       status='direct' if is_direct(url) else 'search')
                            if args.verify_metadata and row['status'] == 'direct':
                                parsed = services[platform].link_to_song(row['url'])
                                row['parsed'] = {'title': parsed.title, 'artist': parsed.artist}
                                assessment = compare_recordings(song, parsed.title, parsed.artist,
                                    duration_ms=getattr(parsed, 'duration_ms', None), isrc=getattr(parsed, 'isrc', None))
                                row['match'] = asdict(assessment)
                                if assessment.status != 'match':
                                    row['status'] = 'mismatch'
                    if args.candidates and platform in services:
                        try:
                            with request_budget(args.timeout):
                                candidates = list(services[platform].search(song.title+' '+song.artist, n=10))
                            row['candidates'] = [{'title': candidate.title, 'artist': candidate.artist,
                                'url': getattr(candidate, 'service_links', {}).get(services[platform].service_name()),
                                'match': asdict(compare_recordings(song, candidate.title, candidate.artist,
                                    duration_ms=getattr(candidate, 'duration_ms', None), isrc=getattr(candidate, 'isrc', None)))}
                                for candidate in candidates]
                        except Exception as error:
                            row['candidate_error'] = type(error).__name__
            except Exception as error:
                # Exception messages can contain credentials/URLs; keep only the type.
                row.update(status='error', error=type(error).__name__)
            report['results'].append(row)
            print(f"{platform}: {song.title} — {row['status']}", flush=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Report: {args.output}')
    return int(any(r['status'] not in ('direct', 'skipped') for r in report['results']))


if __name__ == '__main__':
    raise SystemExit(main())
