"""Telegram result rendering, independent of music service requests."""
from hashlib import sha256
from telegram import (InlineKeyboardMarkup, InlineQueryResultArticle,
                      InputTextMessageContent, LinkPreviewOptions)
from .security import valid_url


def build_result(item, rows):
    markup = InlineKeyboardMarkup(rows)
    title = item.title[:256]
    description = item.artist[:256]
    message = f"🎵 {title}\n👤 {description}\n\n🎧 Слушать на платформах ↓"
    thumbnail = None
    if item.cover_art is not None and valid_url(
        item.cover_art["url"], {"i.scdn.co", "image-cdn-ak.spotifycdn.com", "avatars.yandex.net", "avatars.mds.yandex.net", "i.ytimg.com"}
        | {f"is{i}-ssl.mzstatic.com" for i in range(1, 6)}
    ):
        thumbnail = item.cover_art["url"]
    return InlineQueryResultArticle(
        id=sha256((title + "\0" + description).encode("utf-8")).hexdigest()[:32], title=title,
        description=description, thumbnail_url=thumbnail,
        input_message_content=InputTextMessageContent(
            message, link_preview_options=LinkPreviewOptions(is_disabled=True),
        ), reply_markup=markup,
    )
