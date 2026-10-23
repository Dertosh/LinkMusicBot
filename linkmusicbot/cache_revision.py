"""A search implementation change automatically makes persisted snapshots stale."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from .settings import secrets


@lru_cache(maxsize=1)
def search_revision():
    root = Path(__file__).parent
    files = [root / name for name in (
        'bot.py', 'library.py', 'query_text.py', 'recording_match.py', 'search_ranking.py',
        'presentation.py', 'security.py', 'text_encoding.py', 'youtube_music.py', 'settings.py',
        'cache_revision.py', 'progressive_inline.py', 'cover_photos.py',
    )] + sorted((root / 'services').glob('*.py'))
    lock = root.parent / 'requirements.lock'
    if lock.is_file():
        files.append(lock)
    digest = sha256()
    for path in files:
        digest.update(path.relative_to(root.parent).as_posix().encode())
        digest.update(path.read_bytes())
    digest.update(str(secrets.get('duration_tolerance_ms', 3000)).encode())
    return digest.hexdigest()
