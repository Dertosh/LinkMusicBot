"""Compatibility import; new code should use linkmusicbot.security."""
from linkmusicbot.security import (
    APPLE_HOSTS, YOUTUBE_HOSTS, MAX_BYTES, QueryGuard, SearchQuota,
    check_budget, fetch_text, request_budget, valid_url,
)
