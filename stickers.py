"""Priestess's sticker set: app emojis uploaded in the Discord Developer Portal (Emojis tab).

Each emoji is found by the number in its name (_20261102031217_309_15 -> 309), so a rename
keeps working as long as the number stays (e.g. laugh_309). Two uses:
- short reactions ("哈哈", "？", "好耶") are answered with a sticker instead of an API call;
- her own replies may end with a tag like [表情:无奈], which is swapped for the sticker.
"""

from __future__ import annotations

import random
import re

# Mood -> sticker numbers (one is picked at random).
STICKERS: dict[str, tuple[str, ...]] = {
    "无奈": ("279", "302"),  # a buttered head from a PvZ kernel-pult: stuck, can't do anything
    "没救了": ("296",),  # "人类没有了": reply to weird talk, "this one's hopeless"
    "思考": ("297",),
    "调皮": ("298",),
    "送花": ("299",),
    "让你飞起来": ("300",),  # someone's meme: brag again and I'll send you flying (a light threat)
    "憔悴": ("301",),  # a worn-out smile
    "吃惊": ("303",),
    "生气": ("304",),
    "哭哭": ("305",),
    "击掌": ("306",),
    "大笑": ("307",),
    "震惊": ("308",),
    "盯": ("309",),
}
# For a bare @ with nothing else, or a message that's only emoji / punctuation.
GREETING = ("思考", "盯")

_P = r"[~～。.，,…\s]*"  # trailing filler allowed after a trigger word
_RAW_TRIGGERS: list[tuple[str, str]] = [
    ("大笑", r"(?:哈|h|嘿嘿哈)+|笑死(?:我了)?|233+|草+|艹+|w{2,}|xswl|lol|lmao|xd"),
    ("思考", r"[?？]+|[嗯啊哈诶欸][?？]+|为什么|为啥|什么意思|啥意思|思考|🤔"),
    ("吃惊", r"真的假的|不会吧|[啊诶欸哇][!！]+|[!！]"),
    ("震惊", r"卧槽|我靠|我草|woc|wc|震惊|[!！]{2,}|😱|😨"),
    ("无奈", r"无语|无奈|服了|我服了|唉+|哎+|…+|\.{3,}|。{2,}|🙄"),
    ("没救了", r"离谱|抽象|发癫|难绷|绷不住了?|什么鬼|你在说什么|我是笨蛋|我是猪"),
    ("调皮", r"略+|嘿嘿|不告诉你|就不|😛|😝"),
    ("送花", r"谢谢(?:你)?|谢啦|多谢|爱你|我爱你|喜欢你|老婆|🌹|❤️?|♥"),
    ("让你飞起来", r"就这[?？]?|我(?:是)?无敌(?:了)?|我最强|我是天才|小菜一碟|太简单了|ez"),
    ("憔悴", r"(?:好|太)?累(?:了|死了)?|(?:好)?困(?:了|死了)?|加班|不想上班|上班好累|肝不动了?|熬夜"),
    ("生气", r"哼+|生气|讨厌|坏蛋|不理你了|😠|😡"),
    ("哭哭", r"呜+|哭了|哭哭|qaq|qwq|555+|难过|伤心|歪了|沉了|非酋|😭|😢"),
    ("击掌", r"好耶|耶+|nice|成功了|出了|出货了|欧皇|赢了|过了|击掌|🎉"),
    ("盯", r"盯+|👀|在吗|在不在|在[?？]"),
]
TRIGGERS = [(mood, re.compile(rf"(?:{pattern}){_P}", re.I)) for mood, pattern in _RAW_TRIGGERS]

TAG_RE = re.compile(r"\s*[\[【](?:表情)[:：]\s*(?P<mood>[^\]】]+?)\s*[\]】]\s*")
# A message with no words at all: custom emoji, unicode emoji, punctuation.
_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
_WORDISH_RE = re.compile(r"[\w一-鿿]")
_NUMBER_RE = re.compile(r"(?<!\d)(\d{3})(?!\d)")


def match(text: str) -> str | None:
    """The mood for a short reaction message, or None when it has real content."""
    text = text.strip()
    if len(text) > 12:
        return None
    for mood, pattern in TRIGGERS:
        if pattern.fullmatch(text):
            return mood
    return None


def is_contentless(text: str) -> bool:
    """Only emoji and punctuation (or nothing): nothing for the model to answer."""
    return not _WORDISH_RE.search(_CUSTOM_EMOJI_RE.sub("", text))


def split_tag(reply: str) -> tuple[str, str | None]:
    """Remove [表情:…] tags from a reply; return the text and the last known mood."""
    moods = [m.group("mood") for m in TAG_RE.finditer(reply) if m.group("mood") in STICKERS]
    text = TAG_RE.sub(" ", reply).strip()
    return text, (moods[-1] if moods else None)


def number_of(emoji_name: str) -> str | None:
    """The sticker number in an emoji's name, if it's one of ours."""
    known = {n for numbers in STICKERS.values() for n in numbers}
    return next((n for n in _NUMBER_RE.findall(emoji_name) if n in known), None)


def pick(mood: str) -> str:
    return random.choice(STICKERS[mood])
