"""Animated custom emoji decoration for bot messages.

Admin sends a message with custom animated emoji → bot captures IDs → stores in
Supabase custom_emojis table → decorate() wraps line-leading emoji in
<tg-emoji emoji-id="..."> tags so premium clients see animated versions,
non-premium clients see the plain fallback emoji.

Usage:
    await emoji_fx.load()           # on startup / after capture
    text = emoji_fx.decorate(text)  # before sending with parse_mode="HTML"
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_EMOJI_MAP: dict[str, str] = {}        # fallback_char -> custom_emoji_id
_LEADING_RE: re.Pattern | None = None

_VS_RE = re.compile(r"[︎️]")  # variation selectors


# Default keyword hints — bot auto-assigns these when capturing emoji
KEYWORD_HINTS: dict[str, str] = {
    "🛒": "sell",      "🛍️": "buy",       "🔍": "search",
    "💰": "money",     "💳": "pay",       "⭐": "star",
    "✅": "verified",  "❌": "cancel",    "⚠️": "warning",
    "🔥": "hot",       "🏆": "trophy",    "👤": "profile",
    "🏪": "shop",      "🤝": "deal",      "👍": "trust",
    "📦": "delivery",  "🎉": "congrats",  "🏅": "badge",
    "📊": "stats",     "🔗": "link",      "📋": "list",
    "👑": "king",      "🌅": "morning",   "🃏": "card",
    "⚙️": "admin",     "❓": "help",      "📢": "announce",
    "🚀": "fast",      "✨": "magic",     "🎊": "party",
    "🔨": "ban",       "🔇": "mute",      "🌊": "flood",
    "🏠": "home",      "⏰": "timeout",   "🙋": "request",
    "🎬": "capture",   "🔒": "secure",    "💎": "premium",
    "📅": "date",      "🆔": "id",        "🛡️": "shield",
    "🎁": "gift",      "💸": "discount",  "🔔": "alert",
    "🚨": "scam",      "🙏": "please",    "💬": "chat",
}


def _norm(ch: str) -> str:
    return _VS_RE.sub("", ch or "")


async def load() -> None:
    """Load custom emoji mappings from Supabase into memory."""
    from db import get_custom_emojis
    global _EMOJI_MAP, _LEADING_RE

    items = await get_custom_emojis()
    emoji_map: dict[str, str] = {}

    for item in items:
        fb  = (item.get("fallback") or "").strip()
        cid = (item.get("custom_id") or "").strip()
        if not fb or not cid:
            continue
        # Index all variant forms so lookups are consistent
        for form in {fb, _norm(fb), _norm(fb) + "️"}:
            if form:
                emoji_map.setdefault(form, cid)

    _EMOJI_MAP = emoji_map

    if emoji_map:
        alts = "|".join(re.escape(ch) for ch in sorted(emoji_map, key=len, reverse=True))
        _LEADING_RE = re.compile(rf"^\s*({alts})")
    else:
        _LEADING_RE = None

    logger.info("emoji_fx loaded: %d custom emojis", len(_EMOJI_MAP))


reload = load


def decorate(text: str) -> str:
    """Wrap line-leading known emoji with <tg-emoji> tags (HTML parse mode).

    Lines whose first non-space character is a mapped emoji get that emoji
    replaced with an animated custom-emoji token. Other lines are unchanged.
    Plain-emoji fallback is preserved inside the tag for non-premium clients.
    """
    if not text or not _LEADING_RE or not _EMOJI_MAP:
        return text
    if "<tg-emoji" in text:
        return text  # already decorated

    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        m = _LEADING_RE.match(line)
        if not m:
            out.append(line)
            continue
        ch  = m.group(1)
        cid = _EMOJI_MAP.get(ch) or _EMOJI_MAP.get(_norm(ch))
        if not cid:
            out.append(line)
            continue
        token = f'<tg-emoji emoji-id="{cid}">{ch}</tg-emoji>'
        out.append(line[: m.start(1)] + token + line[m.end(1) :])
    return "\n".join(out)


def h(text: str) -> str:
    """Escape user-provided text for safe HTML embedding."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def entities_to_html(text: str, entities) -> str:
    """Convert Telegram message text + entities list to HTML.

    Preserves custom_emoji (animated), bold, italic, underline,
    strikethrough, spoiler, and code entities. Everything else is
    HTML-escaped plain text. Handles emoji whose codepoints sit above
    U+FFFF (they count as 2 UTF-16 units in Telegram offsets).
    """
    if not entities:
        return h(text)

    # Build UTF-16 offset → Python string index mapping
    utf16_to_idx: dict[int, int] = {}
    utf16_pos = 0
    for idx, ch in enumerate(text):
        utf16_to_idx[utf16_pos] = idx
        utf16_pos += 2 if ord(ch) > 0xFFFF else 1
    utf16_to_idx[utf16_pos] = len(text)

    result: list[str] = []
    prev_end = 0

    for ent in sorted(entities, key=lambda e: e.offset):
        start = utf16_to_idx.get(ent.offset, ent.offset)
        end   = utf16_to_idx.get(ent.offset + ent.length, ent.offset + ent.length)
        result.append(h(text[prev_end:start]))
        chunk = text[start:end]
        et = ent.type

        if et == "custom_emoji":
            cid = getattr(ent, "custom_emoji_id", "") or ""
            result.append(f'<tg-emoji emoji-id="{cid}">{h(chunk)}</tg-emoji>')
        elif et == "bold":
            result.append(f"<b>{h(chunk)}</b>")
        elif et == "italic":
            result.append(f"<i>{h(chunk)}</i>")
        elif et == "underline":
            result.append(f"<u>{h(chunk)}</u>")
        elif et == "strikethrough":
            result.append(f"<s>{h(chunk)}</s>")
        elif et == "code":
            result.append(f"<code>{h(chunk)}</code>")
        elif et == "spoiler":
            result.append(f'<span class="tg-spoiler">{h(chunk)}</span>')
        else:
            result.append(h(chunk))
        prev_end = end

    result.append(h(text[prev_end:]))
    return "".join(result)
