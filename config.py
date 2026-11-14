import os
import shutil

from dotenv import load_dotenv

# .env wins over inherited variables: "重新启动" in the tray starts the new copy with the old
# copy's environment, which still holds the .env values from before any edit.
load_dotenv(override=True)


def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DEV_GUILD_ID = _int("DEV_GUILD_ID", 0)
# Servers she may be in (access.py). Anywhere else she leaves at once. Empty = no restriction.
ALLOWED_GUILD_IDS = {int(g) for g in os.getenv("ALLOWED_GUILD_IDS", "").replace(" ", "").split(",") if g}
DEFAULT_SOURCE = os.getenv("DEFAULT_SOURCE", "bilibili").strip().lower() or "bilibili"
DEFAULT_VOLUME = max(0, min(100, _int("DEFAULT_VOLUME", 50)))
IDLE_TIMEOUT = _int("IDLE_TIMEOUT", 300)

NETEASE_PROXY = os.getenv("NETEASE_PROXY", "").strip() or None
NETEASE_MUSIC_U = os.getenv("NETEASE_MUSIC_U", "").strip()
# Platforms searched, in order, for the same song when a NetEase track can't be played.
# YouTube is link-only (its search results can be anything), so it is never searched here.
NETEASE_FALLBACK = [
    s.strip().lower() for s in os.getenv("NETEASE_FALLBACK", "bilibili").split(",") if s.strip()
]

BILIBILI_SESSDATA = os.getenv("BILIBILI_SESSDATA", "").strip()
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "").strip() or None

MAX_PLAYLIST_ITEMS = 100

# ---- Game calendar (Playtime / 游时) ----
# Folder of Playtime; it is started once to sync, then closed. Empty or missing = feature off.
PLAYTIME_DIR = os.getenv("PLAYTIME_DIR", "").strip() or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Playtime-v0.2.0-windows-x64"
)
# Re-sync this often while the bot keeps running (0 = only when the bot starts).
PLAYTIME_REFRESH_HOURS = _int("PLAYTIME_REFRESH_HOURS", 24)
# Channel for event reminders and the daily digest (empty = no reminders).
CALENDAR_CHANNEL_ID = _int("CALENDAR_CHANNEL_ID", 0)
CALENDAR_GAMES = [
    g.strip() for g in os.getenv("CALENDAR_GAMES", "arknights-cn,endfield-cn").split(",") if g.strip()
]
# The daily posts, one per game (time left / starting soon / ending soon), bot machine's local time.
CALENDAR_DIGEST_TIME = os.getenv("CALENDAR_DIGEST_TIME", "09:00").strip()
# How far ahead the daily posts look, counting from tomorrow: things ending within
# CALENDAR_END_DAYS days are listed every evening until they end (3 = three reminders).
CALENDAR_END_DAYS = _int("CALENDAR_END_DAYS", 3)
CALENDAR_START_DAYS = _int("CALENDAR_START_DAYS", 1)
# Last-call alerts 24 h and 1 h before activities and exchange shops end.
CALENDAR_ALERTS = os.getenv("CALENDAR_ALERTS", "on").strip().lower() not in ("off", "0", "false", "no")
CALENDAR_PING_ROLE_ID = _int("CALENDAR_PING_ROLE_ID", 0)  # role to @ in reminders, 0 = none

# ---- Her voice (GPT-SoVITS, speech.py) ----
# Voice settings (model, reference clip, pauses, optional post_filter), see voices/example.json.
# Empty = voices/voice.json. Missing file = no voice.
VOICE_CONFIG = os.path.join(  # a relative path is relative to this folder
    os.path.dirname(os.path.abspath(__file__)),
    os.getenv("VOICE_CONFIG", "").strip() or "voices/voice.json",
)
# Reference text: clip = the clip's own words (t1: her intonation follows the clip too),
# none = empty (t4, reference-free: only the timbre is taken), empty = what VOICE_CONFIG says.
VOICE_PROMPT = os.getenv("VOICE_PROMPT", "").strip().lower()
# Stop GPT-SoVITS after this many minutes with nobody in talk mode (frees the GPU).
SOVITS_IDLE_MINUTES = _int("SOVITS_IDLE_MINUTES", 5)

# ---- Priestess chat (DeepSeek or Claude) ----
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
# The Anthropic SDK reads ANTHROPIC_API_KEY from the environment (load_dotenv puts .env there).
_has_anthropic_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
# deepseek | claude. Defaults to whichever key is set, DeepSeek first.
CHAT_PROVIDER = os.getenv("CHAT_PROVIDER", "").strip().lower() or (
    "deepseek" if DEEPSEEK_API_KEY else "claude" if _has_anthropic_key else ""
)
CHAT_ENABLED = (CHAT_PROVIDER == "deepseek" and bool(DEEPSEEK_API_KEY)) or (
    CHAT_PROVIDER == "claude" and _has_anthropic_key
)
CHAT_MODEL = os.getenv("CHAT_MODEL", "").strip() or (
    "deepseek-flash" if CHAT_PROVIDER == "deepseek" else "claude-opus-5-5"
)
CHAT_EFFORT = os.getenv("CHAT_EFFORT", "").strip() or "low"
# Channels where she answers every message, not only @mentions (needs the Message Content intent).
CHAT_CHANNEL_IDS = {int(c) for c in os.getenv("CHAT_CHANNEL_IDS", "").replace(" ", "").split(",") if c}
# Let her search the web for fresh information (news, game updates). With DeepSeek the bot
# calls DeepSeek's Search API itself (websearch.py): about US$0.001-0.002 a search.
CHAT_WEB_SEARCH = os.getenv("CHAT_WEB_SEARCH", "on").strip().lower() not in ("off", "0", "false", "no")
CHAT_SEARCH_MAX_USES = _int("CHAT_SEARCH_MAX_USES", 2)  # per message
CHAT_SEARCH_DAILY = _int("CHAT_SEARCH_DAILY", 20)  # per person per day; the deployer has no limit
# Live data from Google via SerpApi (serp.py, travel.py, lookup.py): flights, hotels, products,
# maps, Google Lens. Empty = off. The free plan has 250 searches a month; the bot stops at
# SERPAPI_MONTHLY_LIMIT, for everyone including the deployer.
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
SERPAPI_MONTHLY_LIMIT = _int("SERPAPI_MONTHLY_LIMIT", 230)
# A channel's conversation starts over after this many messages or this many idle seconds.
# Fewer messages = less history sent with every request.
CHAT_MAX_MESSAGES = _int("CHAT_MAX_MESSAGES", 40)
CHAT_IDLE_RESET = _int("CHAT_IDLE_RESET", 1800)
# Daily limits on messages that reach the chat API (0 = no limit). The deployer has none; a
# server's owner has no per-person limit; once the whole server's limit is hit, she only answers with set lines.
CHAT_USER_DAILY = _int("CHAT_USER_DAILY", 40)
CHAT_SERVER_DAILY = _int("CHAT_SERVER_DAILY", 500)
CHAT_MAX_INPUT_CHARS = _int("CHAT_MAX_INPUT_CHARS", 1500)
# Homework, essays, letters, code, translations and other long tasks: this many per person per day.
CHAT_TASKS_DAILY = _int("CHAT_TASKS_DAILY", 3)  # longer messages aren't sent to the API
# Short reactions ("哈哈", "？") answered with one of her app emojis instead of the API.
# logs/blocked.log keeps the text and speaker of blocked messages only when this is on.
LOG_BLOCKED_TEXT = os.getenv("LOG_BLOCKED_TEXT", "off").strip().lower() in ("on", "1", "true", "yes")
CHAT_STICKERS = os.getenv("CHAT_STICKERS", "on").strip().lower() not in ("off", "0", "false", "no")
STICKER_COOLDOWN = _int("STICKER_COOLDOWN", 5)
# DeepSeek balance (/余额): read every this many minutes to work out spending; the deployer
# gets a DM when it falls below BALANCE_WARN (in the account's currency, 0 = never).
BALANCE_CHECK_MINUTES = _int("BALANCE_CHECK_MINUTES", 30)
BALANCE_WARN = float(os.getenv("BALANCE_WARN", "").strip() or 10)  # seconds between stickers in one channel


def ffmpeg_path() -> str:
    """Use ffmpeg from PATH if present, otherwise the binary bundled with imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()
