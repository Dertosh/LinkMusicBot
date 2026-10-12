"""Environment-based deployment settings, with legacy config.py compatibility."""
import os
from importlib import import_module


def load_settings():
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
    }.items():
        if variable in os.environ:
            settings[key] = os.environ[variable]
    settings["youtube_search_limit"] = int(os.environ.get(
        "YOUTUBE_SEARCH_LIMIT", settings.get("youtube_search_limit", 100)))
    return settings


secrets = load_settings()
