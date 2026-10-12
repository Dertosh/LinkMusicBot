"""Metadata-only YouTube search in a subprocess with a hard timeout."""
import json
import re
import subprocess
import sys


def first_video(query):
    process = subprocess.run([
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-plugin-dirs",
        "--flat-playlist", "--skip-download", "--no-warnings", "--no-progress", "--no-cache-dir",
        "--socket-timeout", "3", "--retries", "0", "--extractor-retries", "0",
        "--dump-single-json", "--", "ytsearch1:" + query,
    ], capture_output=True, text=True, timeout=6, check=True)
    entries = json.loads(process.stdout).get("entries", [])
    if not entries:
        raise ValueError("No YouTube fetch results")
    video = entries[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video.get("id", "")):
        raise ValueError("Invalid video ID")
    return "https://www.youtube.com/watch?v=" + video["id"]
