"""Environment-based deployment settings, with legacy config.py compatibility."""
import os
from importlib import import_module


def load_settings():
    """Merge local configuration and environment overrides with validated defaults."""
    try:
        settings = dict(import_module("config").secrets)
    except ModuleNotFoundError as error:
        if error.name != "config":
            raise
        settings = {}
    for key, variable in {
        "telegram_token": "TELEGRAM_BOT_TOKEN",
        "spotify_client_id": "SPOTIFY_CLIENT_ID",
        "spotify_client_secret": "SPOTIFY_CLIENT_SECRET",
        "youtube_token": "YOUTUBE_API_KEY",
        "spotify_redirect_uri": "SPOTIFY_REDIRECT_URI",
        "spotify_token_key": "SPOTIFY_TOKEN_KEY",
        "spotify_token_key_file": "SPOTIFY_TOKEN_KEY_FILE",
        "cover_storage_chat_id": "TELEGRAM_COVER_STORAGE_CHAT_ID",
    }.items():
        if variable in os.environ:
            settings[key] = os.environ[variable]
    settings["youtube_search_limit"] = int(os.environ.get(
        "YOUTUBE_SEARCH_LIMIT", settings.get("youtube_search_limit", 100)))
    settings['spotify_callback_port'] = int(os.environ.get('SPOTIFY_CALLBACK_PORT', settings.get('spotify_callback_port', 8080)))
    for key, variable, default in (
        ("cache_refresh_seconds", "MUSIC_CACHE_REFRESH_SECONDS", 43200),
        ("inline_result_limit", "INLINE_RESULT_LIMIT", 10),
        ("inline_debounce_ms", "INLINE_DEBOUNCE_MS", 600),
        ("duration_tolerance_ms", "MUSIC_DURATION_TOLERANCE_MS", 3000),
    ):
        settings[key] = int(os.environ.get(variable, settings.get(key, default)))
    if settings["cache_refresh_seconds"] < 60:
        raise ValueError("MUSIC_CACHE_REFRESH_SECONDS must be at least 60")
    if not 0 <= settings['duration_tolerance_ms'] <= 10000:
        raise ValueError('MUSIC_DURATION_TOLERANCE_MS must be between 0 and 10000')
    if not 1 <= settings["inline_result_limit"] <= 50:
        raise ValueError("INLINE_RESULT_LIMIT must be between 1 and 50")
    if not 100 <= settings["inline_debounce_ms"] <= 5000:
        raise ValueError("INLINE_DEBOUNCE_MS must be between 100 and 5000")
    return settings


secrets = load_settings()
