"""Topics Priestess stays away from, checked locally before anything reaches the chat API.

The word list is blocked_words.txt next to this file (blocked_words.example.txt when there is
no blocked_words.txt yet), one word per line, under a section:
[回避] words she changes the subject on (politics, real-world conflicts, slurs, porn, fan wars);
[关心] words where someone may be hurting (self-harm), answered gently instead.
Matching ignores case, spaces, punctuation and traditional/simplified differences. The file is
re-read when it changes, so edits apply without restarting. Song titles are checked too.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import zhconv

import config

log = logging.getLogger(__name__)

WORDS_FILE = Path(__file__).parent / "blocked_words.txt"
EXAMPLE_FILE = Path(__file__).parent / "blocked_words.example.txt"
LOG_FILE = Path(__file__).parent / "logs" / "blocked.log"
MAX_LOG_BYTES = 1_000_000
SECTIONS = {"回避": "avoid", "关心": "care"}

_cache: tuple[float, dict[str, str]] | None = None  # (file mtime, normalized word -> kind)


def normalize(text: str) -> str:
    """Simplified Chinese, lowercase, letters/digits/CJK only ("台 独"/"臺獨" -> "台独")."""
    return re.sub(r"[\W_]+", "", zhconv.convert(text, "zh-cn").lower())


def _words() -> dict[str, str]:
    global _cache
    path = WORDS_FILE if WORDS_FILE.is_file() else EXAMPLE_FILE
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _cache and _cache[0] == mtime:
        return _cache[1]
    words: dict[str, str] = {}
    kind = "avoid"
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.split("#", 1)[0].strip()
        if not text:
            continue
        if text.startswith("[") and text.endswith("]"):
            kind = SECTIONS.get(text[1:-1].strip(), "avoid")
            continue
        if word := normalize(text):
            words[word] = kind
    _cache = (mtime, words)
    return words


def check(text: str, kinds: tuple[str, ...] = ("avoid", "care")) -> tuple[str, str] | None:
    """(kind, word) for the first listed word in the text, or None. "care" wins over "avoid"."""
    flat = normalize(text)
    if not flat:
        return None
    found = None
    for word, kind in _words().items():
        if kind in kinds and word in flat:
            if kind == "care":
                return kind, word
            found = found or (kind, word)
    return found


def record(kind: str, word: str, where: str, text: str) -> None:
    """Append a blocked message to logs/blocked.log, so the list can be tuned later.

    By default only the time, kind, matched word and channel are kept: these messages can be
    about someone's worst day ([关心]). LOG_BLOCKED_TEXT=on also keeps the speaker's name and
    the first 200 characters. The file is rotated at 1 MB (one old copy, blocked.log.1).
    """
    LOG_FILE.parent.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if config.LOG_BLOCKED_TEXT:
        snippet = " ".join(text.split())[:200]
    else:
        where, snippet = where.split(" · ", 1)[0], "-"
    try:
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            LOG_FILE.replace(LOG_FILE.with_name(LOG_FILE.name + ".1"))
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{stamp}\t{kind}\t{word}\t{where}\t{snippet}\n")
    except OSError:
        log.exception("Couldn't write %s", LOG_FILE)
