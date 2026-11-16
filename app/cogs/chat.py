"""Chat with Priestess: @mention the bot (or talk in a CHAT_CHANNEL_IDS channel).

Each channel keeps one shared, append-only conversation with the chat model (DeepSeek or
Claude, both through the Anthropic Messages API). The system prompt and
tool list never change, so the prompt cache stays warm and earlier thinking blocks stay
valid; per-message context (who is speaking, the music player's state) goes into the user
turn instead. The conversation starts over when it gets long or goes quiet.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp
import anthropic
import discord
from discord import app_commands
from discord.ext import commands

import access
import config
import gamecal
import moderation
import siren_lore
import lookup
import serp
import stickers
import travel
import weather
import websearch
from cogs.music import Music, SearchView, VoiceError, choices_embed
from music.player import LoopMode
from music.track import SOURCE_LABELS, SourceError
from persona import CHAT_SYSTEM_PROMPT, line, who
from usage import Usage

log = logging.getLogger(__name__)

MAX_TOKENS = 8000  # thinking counts toward this as well as the reply
MAX_TOOL_ROUNDS = 5
# Models that accept server-side refusal fallbacks (fallbacks: "default").
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
DISCORD_LIMIT = 2000
DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
REPEAT_WINDOW = 120  # seconds: the same person repeating the same words is ignored
EMOJI_RETRY = 600  # seconds before looking up the app emojis again after finding none

# Short music requests answered with pre-written lines instead of an API call. They only
# match a whole message, so a song request inside a longer sentence still goes to the model.
_END = r"[吧呀啊呢哦嘛~～！!。.，,？?\s]*"
QUICK_PLAY_RE = re.compile(r"^(?:请|帮我|给我)?(?:放|来|播|点)(?:一)?[首个曲段](?P<q>.+)$")
QUICK_WANT_RE = re.compile(r"^(?:我)?想听(?P<q>.+)$")
QUICK_TAIL_RE = re.compile(r"(?:给我听|听听|好吗|可以吗|行吗)?" + _END + "$")
QUICK_NOT_A_SONG_RE = re.compile(r"^(?:你|我|他|她|它|点|些|什么|啥|歌)")
QUICK_NOW_RE = re.compile(r"^(?:现在)?(?:正)?在?放(?:的)?(?:是)?(?:什么|啥)(?:歌)?" + _END + "$")
QUICK_VOLUME_RE = re.compile(r"^音量(?:调到|调成|设为|设成|改成)?\s*(?P<n>\d{1,3})\s*%?" + _END + "$")
QUICK_RADIO = {
    True: re.compile(r"^(?:开|打开|开启|放|来点)(?:一下)?(?:塞壬)?电台" + _END + "$"),
    False: re.compile(r"^(?:关|关闭|关掉|停)(?:一下|掉)?(?:塞壬)?电台" + _END + "$"),
}
QUICK_CONTROLS = {
    "skip": re.compile(r"^(?:跳过|下一首|切歌|换一首|skip)" + _END + "$", re.I),
    "pause": re.compile(r"^(?:暂停|停一下|先停一下)" + _END + "$"),
    "resume": re.compile(r"^(?:继续|继续放|接着放)" + _END + "$"),
    "stop": re.compile(r"^(?:停止|别放了|不听了|全部停下)" + _END + "$"),
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "play_music",
        "description": (
            "在服务器的音乐播放器里点歌。说话人必须在语音频道里。"
            "query 是链接（Bilibili / 网易云 / YouTube）时直接加入队列；YouTube 只能用链接，不能按歌名搜索；"
            "是歌名或歌手时，会在频道里给说话人发一个搜索结果的选择列表，由对方自己挑，挑了才会播放。"
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "歌名、歌手或链接，按对方说的原样填写"},
                "source": {
                    "type": "string",
                    "enum": ["auto", "siren", "bilibili", "netease"],
                    "description": "搜索平台；对方没指定就用 auto。siren 是塞壬唱片（明日方舟官方曲库），对方想听明日方舟的歌时用它",
                },
                "play_next": {"type": "boolean", "description": "是否插队到下一首"},
            },
            "required": ["query", "source", "play_next"],
            "additionalProperties": False,
        },
    },
    {
        "name": "control_playback",
        "description": (
            "控制播放：skip 跳过当前歌曲，pause 暂停，resume 继续，stop 停止并清空队列，shuffle 打乱队列，leave 离开语音频道，"
            "radio_on 打开塞壬电台（队列放完后从塞壬唱片随机接着放，对方想一直听明日方舟的歌、让你随便放时用），radio_off 关掉电台。"
            "radio_on 要求说话人在语音频道里，其余要求说话人和机器人在同一个语音频道。"
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["skip", "pause", "resume", "stop", "shuffle", "leave", "radio_on", "radio_off"],
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_volume",
        "description": "设置音量，0 到 100 的整数。说话人必须和机器人在同一个语音频道。",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"percent": {"type": "integer", "description": "0-100"}},
            "required": ["percent"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_loop",
        "description": "设置循环模式：off 不循环，one 单曲循环，all 列表循环。说话人必须和机器人在同一个语音频道。",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["off", "one", "all"]}},
            "required": ["mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_music_status",
        "description": "查看播放器当前状态：正在播放的歌、进度、队列前 10 首、音量和循环模式。",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_weather",
        "description": "查询某个地方现在的天气和未来几天的预报。问天气、气温、要不要带伞之类的时候用它，不要用网页搜索查天气。",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "城市或地名，例如 北京、上海、Tokyo"},
                "days": {"type": "integer", "description": "预报天数，1 到 7；只问今天就填 1"},
            },
            "required": ["location", "days"],
            "additionalProperties": False,
        },
    },
]
TOOLS.append(
    {
        "name": "get_game_calendar",
        "description": (
            "查游戏活动日历（官方公告和 PRTS 整理的数据，每天同步）：正在进行、7 天内截止、即将开始的活动、寻访和兑换商店。"
            "问明日方舟、终末地、碧蓝航线、绝区零、NIKKE 的活动时间时先用它，查不到再用网页搜索。"
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "game": {
                    "type": "string",
                    "enum": ["arknights-cn", "endfield-cn", "azurlane-cn", "zzz-cn", "nikke-global", "all"],
                    "description": "arknights-cn 明日方舟，endfield-cn 终末地，azurlane-cn 碧蓝航线，zzz-cn 绝区零，nikke-global NIKKE",
                },
                "view": {
                    "type": "string",
                    "enum": ["ongoing", "ending", "upcoming"],
                    "description": "ongoing 正在进行，ending 7 天内截止，upcoming 即将开始",
                },
            },
            "required": ["game", "view"],
            "additionalProperties": False,
        },
    }
)
# Search for DeepSeek: the bot calls DeepSeek's Search/Fetch APIs itself (websearch.py), which
# is far cheaper than the built-in server search and lets the daily limit be enforced here.
# Long tasks (homework, letters, code, translations...): registered first, so the bot can keep
# them to CHAT_TASKS_DAILY per person per day.
TASK_TOOL: dict[str, Any] = {
    "name": "take_on_task",
    "description": (
        "接\"长活\"之前先调用它登记：替人做作业、写作文或信件、写代码、翻译或总结长文、写长篇故事。"
        "返回可以做还是今天的次数已经用完。闲聊、简单问答、几句话的小忙不用登记。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["homework", "writing", "code", "translation", "summary", "story", "other"],
                "description": "homework 作业、writing 作文或信件、code 代码、translation 翻译、summary 总结、story 故事、other 其他",
            },
            "summary": {"type": "string", "description": "这件活是什么，十个字以内"},
        },
        "required": ["kind", "summary"],
        "additionalProperties": False,
    },
}
SEARCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": (
            "联网搜索（DeepSeek 搜索引擎），返回几条网页的标题、来源、日期、链接和摘要。"
            "需要你不知道或可能已经过时的信息时用：新闻、游戏更新、现实中的事实。"
            "价格、机票、票务、汇率、比分、营业时间这类实时信息，即使没有专门的工具，也先用它搜。"
            "天气用 get_weather，游戏活动时间先用 get_game_calendar，闲聊和角色设定不要搜。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "简洁的搜索词（128 字以内）。可以用 site:域名、after:2026-11-01、\"精确短语\" 这类语法",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "读取一个网页的正文。对方发来链接想让你看看，或者某条搜索结果需要看全文时用。和 web_search 共用每天的次数。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "完整的 http(s) 网页链接"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
]
# Live flight and hotel prices (travel.py), when SERPAPI_KEY is set. They count as searches.
TRAVEL_TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_flights",
        "description": (
            "查机票的实时价格和航班（Google Flights）。对方问机票、航班、飞某地多少钱时用它，不要用 web_search。"
            "返回几班最合适和最便宜的航班（价格、航司、起降时间、经停、时长）和一个完整结果的链接。"
            "城市要换成机场代码，一个城市有几个机场就都写上，用逗号隔开：纽约 JFK,EWR,LGA；洛杉矶 LAX；"
            "北京 PEK,PKX；上海 PVG,SHA；东京 HND,NRT。日期按「[时间]」推算年份，已经过去的月份算明年。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "出发机场代码，几个用逗号隔开，例如 JFK,EWR,LGA"},
                "destination": {"type": "string", "description": "到达机场代码，例如 HND"},
                "depart_date": {"type": "string", "description": "出发日期 YYYY-MM-DD"},
                "return_date": {"type": "string", "description": "返程日期 YYYY-MM-DD；单程就填空字符串"},
                "adults": {"type": "integer", "description": "成人数，默认 1"},
                "nonstop": {"type": "boolean", "description": "是否只看直飞，默认 false"},
            },
            "required": ["origin", "destination", "depart_date", "return_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_hotels",
        "description": (
            "查酒店的实时价格（Google Hotels）。对方问住哪、酒店多少钱时用它，不要用 web_search。"
            "返回几家酒店的每晚价格、总价、评分和链接。日期按「[时间]」推算年份。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "地点或搜索词，例如 London Soho hotels、东京新宿 酒店"},
                "check_in": {"type": "string", "description": "入住日期 YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "退房日期 YYYY-MM-DD"},
                "adults": {"type": "integer", "description": "入住人数，默认 2"},
                "sort": {
                    "type": "string",
                    "enum": ["relevance", "price", "rating", "reviews"],
                    "description": "排序：relevance 默认、price 最便宜、rating 评分最高、reviews 评价最多",
                },
                "max_price": {"type": "integer", "description": "每晚最高价（美元），不限就填 0"},
            },
            "required": ["location", "check_in", "check_out"],
            "additionalProperties": False,
        },
    },
]

# More live data through SerpApi (lookup.py, travel.py), also only with SERPAPI_KEY.
TRAVEL_TOOLS += [
    {
        "name": "find_flight_dates",
        "description": (
            "查一段时间里哪几天飞某条航线最便宜（Google Flights 价格日历）。对方日期灵活、问「哪天飞最便宜」时用它。"
            "出发和到达各只填一个机场代码（纽约用 JFK）。返回最便宜的几个日期和价格。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "出发机场代码，只填一个，例如 JFK"},
                "destination": {"type": "string", "description": "到达机场代码，只填一个，例如 HND"},
                "start_date": {"type": "string", "description": "最早出发日期 YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "最晚出发日期 YYYY-MM-DD"},
                "trip_days": {"type": "integer", "description": "往返要玩几天；单程填 0"},
            },
            "required": ["origin", "destination", "start_date", "end_date", "trip_days"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_flight_deals",
        "description": (
            "从某个机场出发，现在去哪里的机票特别便宜（Google Flights 特价）。对方问「周末去哪玩便宜」「有什么特价机票」时用。"
            "返回目的地、往返价格、比平时便宜多少、日期和航司。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "出发机场代码，可以几个用逗号隔开，例如 PVG 或 JFK,EWR,LGA"},
                "length": {
                    "type": "string",
                    "enum": ["any", "weekend", "week", "two_weeks"],
                    "description": "旅行长度：any 不限、weekend 周末、week 一周、two_weeks 两周",
                },
                "dates": {"type": "string", "description": "出发日期范围，例如 2026-12-01,2026-12-31；不限就填空字符串"},
                "max_price": {"type": "integer", "description": "往返最高价（美元），不限填 0"},
            },
            "required": ["origin"],
            "additionalProperties": False,
        },
    },
]
LOOKUP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_products",
        "description": (
            "查商品在各家店的实时售价（Google Shopping，美国）。对方问某个东西多少钱、哪里买便宜、黑五值不值得买时用它，不要用 web_search。"
            "query 用英文型号或商品名效果最好，例如 Samsung 990 PRO 4TB。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "商品名或型号，最好用英文"},
                "max_price": {"type": "integer", "description": "最高价（美元），不限填 0"},
                "sort": {
                    "type": "string",
                    "enum": ["relevance", "price_low", "price_high"],
                    "description": "relevance 默认、price_low 从便宜到贵、price_high 从贵到便宜",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "look_at_image",
        "description": (
            "用 Google Lens 识别一张图：图里是什么、是哪个角色或作品、出自哪里、哪里能买到。"
            "你自己看不到图片。消息里的「[图片]」一行会给出这条消息（或它回复的那条消息）里图片的编号；"
            "对方问图里是什么、只发了图给你、或者想知道图的出处时，用它。只能识别这些图，别的图片和链接都不行。"
            "对方只是顺手分享、没问图的事，就不要用。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image": {"type": "integer", "description": "图片编号（「[图片]」那一行里的 1、2……）"},
                "question": {"type": "string", "description": "可选：对方想知道什么，几个关键词，例如 角色名字、在哪买"},
            },
            "required": ["image"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_places",
        "description": (
            "在 Google Maps 上找地方：餐厅、商店、景点等，返回评分、地址、此刻是否营业和营业时间、电话。"
            "对方问附近有什么好吃的、某家店现在开不开门、某地有什么推荐时用它。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "找什么，例如 ramen、Costco、咖啡店"},
                "location": {"type": "string", "description": "在哪里，例如 Shibuya Tokyo、上海静安"},
                "open_now": {"type": "boolean", "description": "是否只看现在营业的"},
                "min_rating": {"type": "number", "description": "最低评分（2 到 4.5），不限填 0"},
            },
            "required": ["query", "location"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_directions",
        "description": (
            "查路线和此刻路况下要多久（Google Maps）：开车、公共交通、步行或骑车。对方问从哪到哪要多久、怎么去时用它。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "出发地，越具体越好，例如 Tokyo Station 或某个地址"},
                "end": {"type": "string", "description": "目的地"},
                "mode": {
                    "type": "string",
                    "enum": ["best", "driving", "transit", "walking", "cycling"],
                    "description": "交通方式，不确定就用 best",
                },
            },
            "required": ["start", "end", "mode"],
            "additionalProperties": False,
        },
    },
]
SERP_TOOL_NAMES = {t["name"] for t in TRAVEL_TOOLS + LOOKUP_TOOLS}
# A reply saying she can't look something up, written without having tried a single tool.
GIVE_UP_RE = re.compile(r"查不了|查不到|办不到|没办法查|无法查|没法查|帮不上|看不见实时|没有.{0,8}(?:窗口|渠道|权限|途径)")
SEARCH_NUDGE = (
    "[系统] 你刚才说查不了，但还没有用 web_search 试过。先用 web_search 搜一下再回答。"
    "搜到了就照结果说；搜不到确切答案，就说出最接近的信息，并给一个能直接打开的查询链接。"
    "这条提示是机器人系统发的，不是对方说的话，回答时不要提到它。"
)
WEEKDAYS = "一二三四五六日"


@dataclass
class Conversation:
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_active: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SearchBudgetSpent(Exception):
    """The person's daily searches are used up and Claude's search tool can't be taken out."""


def _drop_from(conversation: Conversation, turn: dict[str, Any]) -> bool:
    """Remove a message's user turn and everything after it. Found by identity, not position:
    the history may have been started over since the turn was added."""
    for i, m in enumerate(conversation.messages):
        if m is turn:
            del conversation.messages[i:]
            return True
    return False


def _keep_as_text(conversation: Conversation, turn: dict[str, Any], reply: str) -> None:
    """Replace a message's unfinished exchange with the user turn and the reply as plain text.
    A paused search left in the history would need the search tool on every later request;
    plain text keeps what she said without it."""
    if _drop_from(conversation, turn):
        conversation.messages += [turn, {"role": "assistant", "content": reply}]


def _has_server_search(messages: list[dict[str, Any]]) -> bool:
    """Whether the history holds results from Claude's own web search."""
    for m in messages:
        content = m.get("content")
        if m.get("role") == "assistant" and isinstance(content, list):
            for block in content:
                kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                if kind in ("server_tool_use", "web_search_tool_result"):
                    return True
    return False


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.conversations: dict[int, Conversation] = {}
        self._http: aiohttp.ClientSession | None = None
        self.usage = Usage()
        # (channel, user) -> (last answered text, when); and who was already told they repeat.
        self._last_words: dict[tuple[int, int], tuple[str, float]] = {}
        self._spam_noted: set[tuple[int, int]] = set()
        self._last_sticker: dict[int, float] = {}  # channel -> when
        self._emojis: dict[str, discord.Emoji] = {}  # sticker number -> app emoji
        self._emojis_checked = float("-inf")
        self._turn_searches: dict[int, int] = {}  # message id -> searches made answering it
        if config.CHAT_PROVIDER == "deepseek":
            self._setup_deepseek()
        else:
            self._setup_claude()

    def _setup_deepseek(self) -> None:
        # DeepSeek serves an Anthropic-compatible Messages API, so the same client and tool
        # loop work; only the fields it documents are sent. It caches prompt prefixes itself.
        self.client = anthropic.AsyncAnthropic(api_key=config.DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        self.create = self.client.messages.create
        tools: list[dict[str, Any]] = [{k: v for k, v in t.items() if k != "strict"} for t in TOOLS] + [TASK_TOOL]
        if config.CHAT_WEB_SEARCH:
            tools += SEARCH_TOOLS
        if config.SERPAPI_KEY:
            tools += TRAVEL_TOOLS + LOOKUP_TOOLS
        self.tool_names = {t["name"] for t in tools}
        self.params = {
            "model": config.CHAT_MODEL,
            "max_tokens": MAX_TOKENS,
            "system": CHAT_SYSTEM_PROMPT,
            "tools": tools,
            "output_config": {"effort": config.CHAT_EFFORT},
            "thinking": {"type": "enabled"},
        }

    def _setup_claude(self) -> None:
        self.client = anthropic.AsyncAnthropic()
        self.create = self.client.beta.messages.create
        betas = ["thinking-binding-controls-2026-08-01"]
        tools: list[dict[str, Any]] = [*TOOLS, TASK_TOOL]
        if config.CHAT_WEB_SEARCH:
            # The dynamic-filtering search needs Opus/Sonnet 4.6 or newer; Haiku takes the basic one.
            search_type = "web_search_20250305" if "haiku" in config.CHAT_MODEL else "web_search_20260209"
            tools.append({"type": search_type, "name": "web_search", "max_uses": config.CHAT_SEARCH_MAX_USES})
        self.tool_names = {t["name"] for t in tools}
        self.params: dict[str, Any] = {
            "model": config.CHAT_MODEL,
            "max_tokens": MAX_TOKENS,
            "system": CHAT_SYSTEM_PROMPT,
            "tools": tools,
            "cache_control": {"type": "ephemeral"},
            "output_config": {"effort": config.CHAT_EFFORT},
            # The history is append-only, so nothing should ever be dropped; if a bug edits it,
            # degrade (drop stale thinking) instead of failing the request.
            "thinking": {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
        }
        if config.CHAT_MODEL in FALLBACK_MODELS:
            # If a safety classifier declines a benign message, retry on a recommended model.
            betas.append("server-side-fallback-2026-07-01")
            self.params["fallbacks"] = "default"
        self.params["betas"] = betas

    async def cog_unload(self) -> None:
        await self.client.close()
        if self._http and not self._http.closed:
            await self._http.close()

    async def http(self) -> aiohttp.ClientSession:
        """Session for the weather and search tools."""
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._http

    @property
    def music(self) -> Music:
        cog = self.bot.get_cog("Music")
        assert isinstance(cog, Music)
        return cog

    # ---- triggering ------------------------------------------------------

    def _addressed(self, message: discord.Message) -> bool:
        me = message.guild.me  # type: ignore[union-attr]
        if me in message.mentions or message.channel.id in config.CHAT_CHANNEL_IDS:
            return True
        # People sometimes @ the bot's managed role instead of the bot itself.
        return any(r.is_bot_managed() and r in me.roles for r in message.role_mentions)

    def _clean_text(self, message: discord.Message) -> str:
        me = message.guild.me  # type: ignore[union-attr]
        text = re.sub(rf"<@!?{me.id}>", "", message.content)
        for role in me.roles:
            if role.is_bot_managed():
                text = text.replace(role.mention, "")
        # Show other mentions as names rather than raw IDs.
        for user in message.mentions:
            text = re.sub(rf"<@!?{user.id}>", f"@{user.display_name}", text)
        return text.strip()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or not access.guild_allowed(message.guild.id):
            return
        if not self._addressed(message):
            return
        member = message.author
        assert isinstance(member, discord.Member)
        text = self._clean_text(message)
        if not text and not message.attachments and not message.content and message.guild.me not in message.mentions:
            # An @ of her role, without the Message Content intent: Discord sent no text at all.
            await self._reply(message, line("mention_unheard"))
            return
        # Everything up to the API call is answered for free, cheapest checks first.
        repeat = self._is_repeat(message, text)
        if hit := moderation.check(text):
            kind, word = hit
            moderation.record(kind, word, f"#{message.channel} · {member.display_name}", text)
            self.usage.count("blocked")
            if repeat:
                await self._spam_reply(message)
            else:
                await self._reply(message, line("chat_care" if kind == "care" else "chat_avoid"))
                self._remember(message, text)
            return
        # Music commands may rightly repeat ("跳过" twice, or again after joining voice).
        if text and await self._quick_command(message, text):
            self.usage.count("quick")
            return
        if repeat:
            await self._spam_reply(message)
            return
        if config.CHAT_STICKERS and not message.attachments:
            mood = stickers.match(text) or (random.choice(stickers.GREETING) if stickers.is_contentless(text) else None)
            if mood and await self._send_sticker(message, mood):
                self._remember(message, text)
                return
        if not text and not message.attachments:
            text = "（只是叫了你一声）"
        if config.CHAT_MAX_INPUT_CHARS and len(text) > config.CHAT_MAX_INPUT_CHARS:
            await self._reply(message, line("chat_too_long", n=len(text)))
            self._remember(message, text)
            return
        limited, notice = self._over_limit(member)
        if limited:
            if notice:
                await self._reply(message, notice)
            else:
                await self._react(message, "憔悴")  # already told today: just a tired look
            return
        # Counted right after the check, with no waiting in between: messages queued behind a
        # reply in progress (in any channel) already see this one, so the limits can't be overrun.
        self.usage.user(member.id, member.display_name)["messages"] += 1
        self.usage.count("messages")

        conversation = self.conversations.setdefault(message.channel.id, Conversation())
        async with conversation.lock:
            if (
                len(conversation.messages) >= config.CHAT_MAX_MESSAGES
                or time.monotonic() - conversation.last_active > config.CHAT_IDLE_RESET
            ):
                # Start over rather than trimming old turns: edits to the history would
                # invalidate the cache and every later thinking block.
                conversation.messages = []
            conversation.last_active = time.monotonic()
            turn = {"role": "user", "content": self._user_turn(message, text)}
            conversation.messages.append(turn)

            async with message.channel.typing():
                try:
                    reply = await self._respond(conversation, message)
                    self._remember(message, text)
                except anthropic.APIError as e:
                    # Drop the unanswered turn: a message the provider rejected would make every
                    # later request in this channel fail too. Not remembered, so it can be resent.
                    _drop_from(conversation, turn)
                    reply = self._api_error_line(e, message, text)
                else:
                    # Her own words go through the same list (a roundabout question, a search
                    # result). Only "avoid" words: a caring reply may well say 轻生 or 自杀.
                    if hit := moderation.check(reply, kinds=("avoid",)):
                        moderation.record("reply", hit[1], f"#{message.channel} · {member.display_name}", reply)
                        self.usage.count("blocked")
                        _drop_from(conversation, turn)
                        reply = line("chat_avoid")

        reply, mood = stickers.split_tag(reply)
        for chunk in split_message(reply):
            await self._reply(message, chunk)
        if speech := self.bot.get_cog("Speech"):
            speech.say(message, reply)  # type: ignore[attr-defined]  # read aloud in talk mode
        if mood and (emoji := await self._sticker_emoji(mood)):
            await message.channel.send(str(emoji))

    def _api_error_line(self, error: anthropic.APIError, message: discord.Message, text: str) -> str:
        if isinstance(error, anthropic.RateLimitError):
            return "……说得太快了，我有点跟不上。等一会儿再和我说话吧。"
        if isinstance(error, anthropic.APIConnectionError):
            return "信号断断续续的……我没能听清。再说一次？"
        if isinstance(error, anthropic.APIStatusError):
            log.error("Chat API error %s: %s", error.status_code, error.message)
            # DeepSeek turns down some topics itself ("Content Exists Risk").
            if error.status_code == 400 and "risk" in str(error.message).lower():
                moderation.record("provider", "-", f"#{message.channel} · {message.author.display_name}", text)
                self.usage.count("blocked")
                return line("chat_api_blocked")
        else:
            log.error("Chat API error: %s", error)
        return "嗯……有什么东西出错了。再给我一点时间。"

    async def _reply(self, message: discord.Message, content: str | None = None, **kwargs: Any) -> None:
        await message.reply(content, mention_author=False, allowed_mentions=discord.AllowedMentions.none(), **kwargs)

    def _is_repeat(self, message: discord.Message, text: str) -> bool:
        """The same person sending words she already answered, within REPEAT_WINDOW seconds.

        Only answered messages are remembered (see _remember), so resending after an error, or
        after she said "join a voice channel first", is never mistaken for spam.
        """
        last = self._last_words.get((message.channel.id, message.author.id))
        return bool(
            last and last[0] == text and time.monotonic() - last[1] < REPEAT_WINDOW and not message.attachments
        )

    def _remember(self, message: discord.Message, text: str) -> None:
        self._last_words[(message.channel.id, message.author.id)] = (text, time.monotonic())
        self._spam_noted.discard((message.channel.id, message.author.id))

    async def _spam_reply(self, message: discord.Message) -> None:
        """A short line the first time someone repeats themselves, then just a stare (a reaction)."""
        key = (message.channel.id, message.author.id)
        if key in self._spam_noted:
            await self._react(message, "盯")
            return
        self._spam_noted.add(key)
        await self._reply(message, line("chat_repeat"))

    def _over_limit(self, member: discord.Member) -> tuple[bool, str | None]:
        """(limited, line to send). The line goes out once a day per person, then only a reaction."""
        # The deployer has no limits. A server's owner (her 博士 there) skips the per-person limit
        # but not the server-wide one, which is what keeps other servers off the deployer's bill.
        if access.is_deployer(member.id):
            return False, None
        entry = self.usage.user(member.id, member.display_name)
        if config.CHAT_SERVER_DAILY and self.usage.today()["messages"] >= config.CHAT_SERVER_DAILY:
            key = "chat_server_limit"
        elif config.CHAT_USER_DAILY and entry["messages"] >= config.CHAT_USER_DAILY and member.id != member.guild.owner_id:
            key = "chat_user_limit"
        else:
            return False, None
        if entry["limited"]:
            return True, None
        entry["limited"] = True
        self.usage.save()
        return True, line(key, who=who(member, member.guild))

    # ---- stickers (app emojis) -------------------------------------------

    async def _sticker_emoji(self, mood: str) -> discord.Emoji | None:
        if not self._emojis and time.monotonic() - self._emojis_checked > EMOJI_RETRY:
            self._emojis_checked = time.monotonic()
            try:
                for emoji in await self.bot.fetch_application_emojis():
                    if number := stickers.number_of(emoji.name):
                        self._emojis[number] = emoji
                log.info("Found %d sticker emojis", len(self._emojis))
            except discord.HTTPException as e:
                log.warning("Couldn't fetch app emojis: %s", e)
        numbers = [n for n in stickers.STICKERS[mood] if n in self._emojis]
        return self._emojis[random.choice(numbers)] if numbers else None

    async def _react(self, message: discord.Message, mood: str) -> None:
        """A small answer: her sticker as a reaction on the message, instead of a new message."""
        if emoji := await self._sticker_emoji(mood):
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException as e:
                log.info("Couldn't add a reaction: %s", e)

    async def _send_sticker(self, message: discord.Message, mood: str) -> bool:
        """Answer with a sticker. False if there's no emoji for it (the message goes on as usual)."""
        now = time.monotonic()
        emoji = await self._sticker_emoji(mood)
        if emoji is None:
            return False
        if now - self._last_sticker.get(message.channel.id, float("-inf")) < config.STICKER_COOLDOWN:
            await self._react(message, mood)  # one just went out here: react instead of posting another
            return True
        self._last_sticker[message.channel.id] = now
        self.usage.count("stickers")
        await self._reply(message, str(emoji))
        return True

    # ---- quick commands (no API call) -------------------------------------

    async def _quick_command(self, message: discord.Message, text: str) -> bool:
        """Handle short, unambiguous music requests with pre-written lines. True if handled."""
        member = message.author
        assert isinstance(member, discord.Member)
        text = text.strip()

        async def reply(content: str | None = None, **kwargs: Any) -> None:
            await message.reply(content, mention_author=False, allowed_mentions=discord.AllowedMentions.none(), **kwargs)

        try:
            if m := QUICK_PLAY_RE.match(text) or QUICK_WANT_RE.match(text):
                query = QUICK_TAIL_RE.sub("", m.group("q")).strip()
                if not query or QUICK_NOT_A_SONG_RE.match(query):
                    return False  # "我想听你说话" is chat, not a song
                if not member.voice or not member.voice.channel:
                    raise VoiceError(line("need_voice", who=who(member, member.guild)))
                if self.music.resolver.is_link(query):
                    tracks = await self.music.resolver.find(query)
                    await reply(await self.music.add_tracks(member, message.channel, tracks, False))
                else:
                    # _offer_choices posts the list itself; its return value is for the model.
                    tracks_text = await self._offer_choices(member, message, query, None, False)
                    if tracks_text.startswith("在各个平台都没有搜到"):
                        await reply(line("search_none", query=query))
                return True

            if QUICK_NOW_RE.match(text):
                player = self.music.players.get(member.guild.id)
                if player and player.current:
                    await reply(embed=player.now_playing_embed())
                else:
                    await reply(line("nothing_playing"))
                return True

            radio = next((on for on, pattern in QUICK_RADIO.items() if pattern.match(text)), None)
            if radio is not None:
                await reply(await self.music.set_radio(member, message.channel, radio))
                return True

            action = next((a for a, pattern in QUICK_CONTROLS.items() if pattern.match(text)), None)
            if action is None and not QUICK_VOLUME_RE.match(text):
                return False
            player = self.music.player_for(member)
            if m := QUICK_VOLUME_RE.match(text):
                percent = max(0, min(100, int(m.group("n"))))
                player.set_volume(percent)
                await reply(line("volume", percent=percent))
            elif action == "skip":
                if not player.current:
                    await reply(line("nothing_playing"))
                else:
                    title = discord.utils.escape_markdown(player.current.title)
                    player.skip()
                    await reply(line("skipped", title=title))
            elif action == "pause":
                await reply(line("paused") if player.pause() else line("nothing_playing"))
            elif action == "resume":
                await reply(line("resumed") if player.resume() else line("not_paused"))
            elif action == "stop":
                player.stop()
                await reply(line("stopped"))
            return True
        except (VoiceError, SourceError) as e:
            await reply(str(e) if isinstance(e, VoiceError) else line("source_error", error=e))
            return True

    # ---- conversation ----------------------------------------------------

    def _user_turn(self, message: discord.Message, text: str) -> str:
        member = message.author
        assert isinstance(member, discord.Member)
        speaker = who(member, message.guild)
        speaker_line = "博士（服务器的主人）" if speaker == "博士" else f"{member.display_name}（客人）"

        voice = f"在语音频道「{member.voice.channel.name}」里" if member.voice and member.voice.channel else "不在语音频道"
        player = self.music.players.get(message.guild.id)  # type: ignore[union-attr]
        if player and player.current:
            c = player.current
            music = f"正在播放《{c.display}》（{c.label}），队列里还有 {len(player.queue)} 首"
            if siren_lore.is_personal(c.source, c.title, c.extra.get("album", ""), c.artist or ""):
                music += "（这首歌和你自己的经历有关）"
        elif player:
            music = f"什么都没在播放，队列里有 {len(player.queue)} 首"
        else:
            music = "你不在任何语音频道里，什么都没在放"

        now = datetime.now().astimezone()
        offset = now.strftime("%z")
        clock = (
            f"{now.year}年{now.month}月{now.day}日 星期{WEEKDAYS[now.weekday()]} {now:%H:%M}"
            f"（UTC{offset[:3]}:{offset[3:]}，机器人所在地的时间）"
        )

        attachments = self._attachment_lines(message)
        speech = self.bot.get_cog("Speech")
        if speech is not None and speech.listening(message):  # type: ignore[attr-defined]
            attachments += "\n[朗读] 你的这条回复会在语音频道里被读出来：说得口语、简短一点（三四句以内），不要放链接、列表和表情标记"
        if self._server_search() and self._searches_left(member) == 0:
            # So she knows why she can't search (_params_for takes the tool out or stops the reply).
            attachments += "\n[搜索] 对方今天的联网搜索次数已经用完了：这条消息不要搜索，凭你已经知道的回答（说明可能不是最新的）"
        return f"[时间] {clock}\n[说话人] {speaker_line}\n[语音] {voice}\n[音乐] {music}\n[消息] {text}{attachments}"

    def _server_search(self) -> dict[str, Any] | None:
        """Claude's own web search tool (the provider runs it), or None with DeepSeek."""
        return next((t for t in self.params.get("tools") or [] if str(t.get("type", "")).startswith("web_search_")), None)

    def _searches_left(self, member: discord.Member) -> int | None:
        """Web searches this person has left today; None = no limit."""
        if access.is_deployer(member.id) or not config.CHAT_SEARCH_DAILY:
            return None
        return max(0, config.CHAT_SEARCH_DAILY - self.usage.user(member.id)["searches"])

    def _params_for(self, conversation: Conversation, message: discord.Message) -> tuple[dict[str, Any], int | None, int]:
        """(request params, searches reserved for this request, how many of them count against the
        daily limit) for Claude's own web search. None reserved = no such tool (DeepSeek).

        Claude's search runs at the provider, so its limits are applied here, not when a tool
        runs: a request may search at most what's left of the per-message limit
        (CHAT_SEARCH_MAX_USES) and of the person's daily limit (CHAT_SEARCH_DAILY). Those
        searches are reserved (counted) before the request is sent, with no waiting since the
        check, so requests from other channels at the same time can't be handed the same ones;
        _tool_loop settles the reservation with what was actually used.
        With nothing left, the tool is taken out, but only while the channel's history has no
        results from it (the API may refuse the request otherwise, and needs the tool to resume a
        paused turn). When it can't be taken out:
        - daily limit used up: SearchBudgetSpent, and _tool_loop sends no request that could
          search, so the daily limit is a hard limit;
        - only the per-message limit used up: the tool stays with max_uses 1, which still fits in
          the daily limit (the per-message limit is soft in this one case).
        """
        search = self._server_search()
        if search is None:
            return self.params, None, 0
        member = message.author
        daily_left = self._searches_left(member)  # type: ignore[arg-type]  # None = no daily limit
        message_left = max(0, max(1, config.CHAT_SEARCH_MAX_USES) - self._turn_searches.get(message.id, 0))
        allow = message_left if daily_left is None else min(message_left, daily_left)
        tools = self.params["tools"]
        if allow == 0:
            if not _has_server_search(conversation.messages):
                return {**self.params, "tools": [t for t in tools if t is not search]}, 0, 0
            if daily_left == 0:
                raise SearchBudgetSpent
            allow = 1
        if allow >= search["max_uses"]:
            params = self.params
        else:
            params = {**self.params, "tools": [{**t, "max_uses": allow} if t is search else t for t in tools]}
        self._turn_searches[message.id] = self._turn_searches.get(message.id, 0) + allow
        daily = 0
        if daily_left is not None:
            daily = allow
            self.usage.user(member.id)["searches"] += allow
            self.usage.save()
        return params, allow, daily

    @staticmethod
    def _images(message: discord.Message) -> list[str]:
        """Image links in the message and in the message it replies to ("这是什么" as a reply to
        someone's picture), at most 4. look_at_image can only look at these, by number."""
        images = []
        sources = [message]
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            sources.append(message.reference.resolved)
        for m in sources:
            for a in m.attachments:
                if (a.content_type or "").startswith("image/"):
                    images.append(a.url)
            for e in m.embeds:
                if url := (e.image.url if e.image else None) or (e.thumbnail.url if e.thumbnail else None):
                    images.append(url)
        return images[:4]

    def _attachment_lines(self, message: discord.Message) -> str:
        """How many images there are (numbered for look_at_image; the links themselves aren't
        sent to the model), and a note about other files, which she can't open."""
        images = self._images(message)
        others = sum(1 for a in message.attachments if not (a.content_type or "").startswith("image/"))
        lines = ""
        if images:
            if "look_at_image" in self.tool_names:
                numbers = "、".join(str(i) for i in range(1, len(images) + 1))
                lines += f"\n[图片] {len(images)} 张，编号 {numbers}（你看不到图；要知道图里是什么，用 look_at_image 并给出编号）"
            else:
                lines += f"\n（附带了 {len(images)} 张图片，你看不到内容）"
        if others:
            lines += f"\n（附带了 {others} 个文件，你看不到内容）"
        return lines

    async def _respond(self, conversation: Conversation, message: discord.Message) -> str:
        try:
            return await self._tool_loop(conversation, message)
        finally:
            self._turn_searches.pop(message.id, None)

    async def _tool_loop(self, conversation: Conversation, message: discord.Message) -> str:
        texts: list[str] = []
        entry = self.usage.user(message.author.id)
        used_tools = nudged = False
        paused = False  # the last response paused mid-turn; the next one carries on from it
        turn = conversation.messages[-1]  # this message's user turn (on_message just added it)
        for round_no in range(MAX_TOOL_ROUNDS):
            try:
                params, reserved, daily = self._params_for(conversation, message)
            except SearchBudgetSpent:
                if round_no == 0:
                    # Her search results from earlier turns keep the search tool from being taken
                    # out: start the channel's conversation over (as after CHAT_MAX_MESSAGES) and
                    # answer without searching.
                    log.info("Chat: %s is out of searches; starting the conversation over without search", message.author)
                    conversation.messages = [turn]
                    params, reserved, daily = self._params_for(conversation, message)
                else:
                    # Out of searches in the middle of a reply: no request that could search goes
                    # out. What she has written so far is sent and kept as plain text; the
                    # unfinished search blocks are dropped so the history stays valid.
                    log.info("Chat: %s ran out of searches mid-reply; stopping", message.author)
                    reply = ("\n".join(texts) + "\n\n" if texts else "") + line("chat_search_spent")
                    _keep_as_text(conversation, turn, reply)
                    self.usage.save()
                    return reply
            # If the request fails, the reservation is kept: a search may already have been billed.
            response = await self.create(messages=conversation.messages, **params)
            self._count_tokens(entry, response.usage)
            used = getattr(getattr(response.usage, "server_tool_use", None), "web_search_requests", None) or 0
            # Settle the reservation: give back what wasn't used, or count what went over.
            if reserved is not None:
                self._turn_searches[message.id] = self._turn_searches.get(message.id, 0) + used - reserved
            entry["searches"] += used - daily
            # Append the full content (thinking blocks included) so the history stays append-only.
            conversation.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return "……这个话题，我们还是不要继续了。"
            new_texts = [b.text for b in response.content if b.type == "text" and b.text.strip()]
            # A paused response's continuation holds only what comes after it: add on to its text.
            texts = texts + new_texts if paused else new_texts
            paused = response.stop_reason == "pause_turn"
            if paused:
                continue  # a server-side search paused mid-turn; sending the history again resumes it
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if (
                    "web_search" in self.tool_names and not used_tools and not nudged
                    and GIVE_UP_RE.search("".join(texts))
                ):
                    # She said she can't look it up without trying: ask her to search first.
                    # This reply isn't sent; only the one after the search is.
                    nudged = True
                    log.info("Chat: she gave up without searching; asking her to search first")
                    conversation.messages.append({"role": "user", "content": SEARCH_NUDGE})
                    continue
                break
            used_tools = True
            results = []
            for block in tool_uses:
                if response.stop_reason == "tool_use":
                    content, is_error = await self._run_tool(block.name, block.input, message)
                else:  # cut off by max_tokens: the input may be incomplete
                    content, is_error = "没有执行：回复被截断了。", True
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
                )
            # Every tool_use needs its tool_result, even when we stop looping here.
            conversation.messages.append({"role": "user", "content": results})
            if response.stop_reason != "tool_use":
                break

        usage = response.usage
        searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", None)
        log.info(
            "Chat %s: in=%s cache_read=%s cache_write=%s out=%s searches=%s",
            response.model, usage.input_tokens, getattr(usage, "cache_read_input_tokens", None),
            getattr(usage, "cache_creation_input_tokens", None), usage.output_tokens, searches or 0,
        )
        self.usage.save()
        reply = "\n".join(texts) or "……"
        if paused:
            # Still paused after the last round: keep what she said, not the unfinished search.
            _keep_as_text(conversation, turn, reply)
        return reply

    @staticmethod
    def _count_tokens(entry: dict[str, Any], usage: Any) -> None:
        entry["input"] += (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", None) or 0)
        entry["cache_read"] += getattr(usage, "cache_read_input_tokens", None) or 0
        entry["output"] += usage.output_tokens or 0  # searches are counted in _tool_loop

    # ---- tools -----------------------------------------------------------

    async def _run_tool(self, name: str, args: dict[str, Any], message: discord.Message) -> tuple[str, bool]:
        member = message.author
        assert isinstance(member, discord.Member)
        try:
            if name == "play_music":
                return await self._tool_play(member, message, args), False
            if name == "get_music_status":
                return self._tool_status(member.guild), False
            if name == "get_game_calendar":
                try:
                    events, meta = gamecal.load()
                except gamecal.CalendarError as e:
                    return f"{e}，可以改用网页搜索。", True
                games = None if args["game"] == "all" else {args["game"]}
                return gamecal.describe(gamecal.select(events, games, args["view"]), meta), False
            if name == "get_weather":
                try:
                    return await weather.get_weather(await self.http(), args["location"], int(args["days"])), False
                except weather.WeatherError as e:
                    return str(e), True
            if name == "take_on_task":
                return self._tool_task(args, message)
            if name in ("web_search", "fetch_page") or name in SERP_TOOL_NAMES:
                return await self._tool_search(name, args, message)

            if name == "control_playback" and args["action"] in ("radio_on", "radio_off"):
                # set_radio returns her line; the model only needs to know what happened.
                await self.music.set_radio(member, message.channel, args["action"] == "radio_on")
                return ("塞壬电台已打开。" if args["action"] == "radio_on" else "塞壬电台已关闭。"), False

            player = self.music.player_for(member)
            if name == "control_playback":
                action = args["action"]
                if action == "skip":
                    if not player.current:
                        return "现在没有在播放，没什么可跳过的。", True
                    title = player.current.display
                    player.skip()
                    return f"已跳过《{title}》。", False
                if action == "pause":
                    return ("已暂停。", False) if player.pause() else ("现在没有在播放。", True)
                if action == "resume":
                    return ("已继续播放。", False) if player.resume() else ("现在没有暂停。", True)
                if action == "stop":
                    player.stop()
                    return "已停止播放并清空队列。", False
                if action == "shuffle":
                    player.shuffle()
                    return f"已打乱队列里的 {len(player.queue)} 首歌。", False
                if action == "leave":
                    self.music.players.pop(member.guild.id, None)
                    await player.destroy()
                    return "已离开语音频道。", False
            if name == "set_volume":
                percent = max(0, min(100, int(args["percent"])))
                player.set_volume(percent)
                return f"音量已设为 {percent}%。", False
            if name == "set_loop":
                player.loop_mode = LoopMode(args["mode"])
                return f"循环模式已设为 {args['mode']}。", False
            return f"没有这个工具：{name}", True
        except (VoiceError, SourceError) as e:
            return str(e), True
        except Exception:
            log.exception("Tool %s failed", name)
            return "执行时出错了。", True

    def _tool_task(self, args: dict[str, Any], message: discord.Message) -> tuple[str, bool]:
        """Count a long task against the person's daily allowance."""
        member = message.author
        entry = self.usage.user(member.id, member.display_name)
        limit = config.CHAT_TASKS_DAILY
        done = entry.get("tasks", 0)
        if limit and done >= limit:
            return (
                f"不能做：对方今天的 {limit} 次长活已经用完了。用你的口吻婉拒，让对方明天再来。"
            ), True
        entry["tasks"] = done + 1
        self.usage.save()
        log.info("Long task for %s: %s (%s), %d/%s today", member.display_name, args.get("summary"), args.get("kind"),
                 done + 1, limit or "∞")
        left = f"今天还剩 {limit - done - 1} 次" if limit else "不限次数"
        return f"可以做。这是对方今天的第 {done + 1} 次长活（{left}）。认真完成，最后记得加你口吻的免责声明。", False

    async def _tool_search(self, name: str, args: dict[str, Any], message: discord.Message) -> tuple[str, bool]:
        """Web search and the SerpApi lookups, within the daily (per person) and per-message limits."""
        member = message.author
        entry = self.usage.user(member.id, member.display_name)
        owner = access.is_deployer(member.id)
        if config.CHAT_SEARCH_DAILY and entry["searches"] >= config.CHAT_SEARCH_DAILY and not owner:
            return (
                f"没有搜：对方今天的 {config.CHAT_SEARCH_DAILY} 次联网搜索已经用完了。"
                "告诉对方明天再问，或者凭你已经知道的回答（说明可能不是最新的）。"
            ), True
        if self._turn_searches.get(message.id, 0) >= max(1, config.CHAT_SEARCH_MAX_USES):
            return "没有搜：这条消息已经搜过足够多次了，用已有的结果回答吧。", True
        image_url = ""
        if name == "look_at_image":
            # Only an image in this message (or the one it replies to), picked by number: what is
            # sent to SerpApi is always something someone shared here, never a link the model chose.
            images = self._images(message)
            try:
                number = int(args.get("image") or 0)
            except (TypeError, ValueError):
                number = 0
            if not 1 <= number <= len(images):
                return f"没有查：这条消息里没有第 {args.get('image')} 张图（一共 {len(images)} 张）。", True
            image_url = images[number - 1]
        target = " ".join(
            str(args[k]) for k in ("query", "url", "location", "start", "end", "question") if args.get(k)
        )
        if hit := moderation.check(target, kinds=("avoid",)):
            moderation.record("search", hit[1], f"#{message.channel} · {member.display_name}", target)
            return "没有搜：这是你不聊的话题。轻轻带过，换个话题。", True
        # Counted before the request (and kept if it fails: a timeout may still be billed), with
        # no waiting since the check, so searches running at once can't overrun the daily limit.
        self._turn_searches[message.id] = self._turn_searches.get(message.id, 0) + 1
        entry["searches"] += 1
        self.usage.save()
        try:
            if name == "web_search":
                result = await websearch.search(await self.http(), target, self._clean_text(message))
            elif name == "fetch_page":
                result = await websearch.fetch(await self.http(), target)
            elif name == "find_flights":
                result = await travel.find_flights(
                    args["origin"], args["destination"], args["depart_date"], args.get("return_date") or "",
                    int(args.get("adults") or 1), bool(args.get("nonstop")),
                )
            elif name == "find_hotels":
                result = await travel.find_hotels(
                    args["location"], args["check_in"], args["check_out"], int(args.get("adults") or 2),
                    args.get("sort") or "relevance", int(args.get("max_price") or 0),
                )
            elif name == "find_flight_dates":
                result = await travel.find_flight_dates(
                    args["origin"], args["destination"], args["start_date"], args["end_date"], int(args.get("trip_days") or 0)
                )
            elif name == "find_flight_deals":
                result = await travel.find_flight_deals(
                    args["origin"], args.get("length") or "", args.get("dates") or "", int(args.get("max_price") or 0)
                )
            elif name == "find_products":
                result = await lookup.find_products(
                    args["query"], int(args.get("max_price") or 0), args.get("sort") or "relevance"
                )
            elif name == "look_at_image":
                result = await lookup.look_at_image(image_url, args.get("question") or "")
            elif name == "find_places":
                result = await lookup.find_places(
                    args["query"], args.get("location") or "", bool(args.get("open_now")), float(args.get("min_rating") or 0)
                )
            else:
                result = await lookup.get_directions(args["start"], args["end"], args.get("mode") or "best")
        except (websearch.SearchError, serp.SerpError) as e:
            fallback = ""
            if name == "find_flights":
                link = travel.flights_link(args["origin"], args["destination"], args["depart_date"], args.get("return_date") or "")
                fallback = f" 可以给对方这个查询链接：{link}"
            return f"没有成功：{e}。{fallback}", True
        return result, False

    async def _tool_play(self, member: discord.Member, message: discord.Message, args: dict[str, Any]) -> str:
        source = None if args["source"] == "auto" else args["source"]
        if not member.voice or not member.voice.channel:
            raise VoiceError(line("need_voice", who=who(member, member.guild)))
        if not self.music.resolver.is_link(args["query"]):
            return await self._offer_choices(member, message, args["query"], source, args["play_next"])

        channel = message.channel
        tracks = await self.music.resolver.find(args["query"], source)
        player_before = self.music.players.get(member.guild.id)
        queued_before = len(player_before.queue) if player_before else 0
        playing = bool(player_before and player_before.current)

        await self.music.add_tracks(member, channel, tracks, args["play_next"])

        first = tracks[0]
        if len(tracks) > 1:
            result = f"已把 {len(tracks)} 首歌（来自 {first.label}）加入队列，第一首是《{first.display}》。"
        elif not playing and (args["play_next"] or queued_before == 0):
            result = f"马上开始播放《{first.display}》（{first.label}，{first.duration_text}）。"
        else:
            position = 1 if args["play_next"] else queued_before + 1
            result = f"《{first.display}》（{first.label}，{first.duration_text}）已加入队列第 {position} 位。"
        if note := first.extra.get("note"):
            result += f"（{note}）"
        return result

    async def _offer_choices(
        self, member: discord.Member, message: discord.Message, query: str, source: str | None, play_next: bool
    ) -> str:
        """Post a pick-one list under the user's message; the song plays once they pick."""
        self.music.ensure_not_talking(member.guild)
        tracks = await self.music.resolver.search_choices(query, source)
        if not tracks:
            return f"在各个平台都没有搜到「{query}」，没有发选择列表。"
        view = SearchView(self.music, member.id, tracks, play_next)
        view.message = await message.reply(
            line("choices_prompt", query=query),
            embed=choices_embed(tracks, query),
            view=view,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        listed = "；".join(f"{i}. {t.display}（{t.label}，{t.duration_text}）" for i, t in enumerate(tracks, 1))
        return (
            f"已经在频道里给对方发了一个选择列表，共 {len(tracks)} 个结果：{listed}。"
            "还没有开始播放，要等对方自己从列表里挑。可以用一两句话请对方挑选，或者顺口提一下你觉得像原曲的那个，"
            "但不要说已经在放了，也不要再把列表念一遍。"
        )

    def _tool_status(self, guild: discord.Guild) -> str:
        player = self.music.players.get(guild.id)
        if not player:
            return "你不在任何语音频道里，什么都没在放。"
        parts = []
        if player.current:
            c = player.current
            state = "已暂停" if player.paused_at else "正在播放"
            parts.append(f"{state}《{c.display}》（{c.label}），进度 {int(player.position)}/{c.duration or '?'} 秒")
        else:
            parts.append("什么都没在播放")
        if player.queue:
            upcoming = "；".join(f"{i}. {t.display}（{SOURCE_LABELS[t.source]}）" for i, t in enumerate(player.queue[:10], 1))
            parts.append(f"队列共 {len(player.queue)} 首：{upcoming}")
        else:
            parts.append("队列是空的")
        parts.append(f"音量 {int(player.volume * 100)}%，循环模式 {player.loop_mode.value}")
        return "。".join(parts) + "。"

    # ---- commands --------------------------------------------------------

    @app_commands.command(name="聊天统计", description="今天和最近 7 天的聊天用量（仅部署者）")
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction):
        if not access.is_deployer(interaction.user.id):
            await interaction.response.send_message(line("deployer_only"), ephemeral=True)
            return
        today = self.usage.today()

        def tokens(n: int) -> str:
            return f"{n / 10000:.1f} 万" if n >= 10000 else str(n)

        def limit(n: int, cap: int) -> str:
            return f"{n}/{cap}" if cap else str(n)

        embed = discord.Embed(title="聊天统计 · 今天", color=0x8E7CC3)
        embed.description = (
            f"发给 AI 的消息：**{limit(today['messages'], config.CHAT_SERVER_DAILY)}**\n"
            f"免费处理：表情 {today.get('stickers', 0)} · 点歌快捷指令 {today.get('quick', 0)} · "
            f"拦下的话题 {today.get('blocked', 0)}（见 logs/blocked.log）"
        )
        users = sorted(today["users"].values(), key=lambda u: u["messages"], reverse=True)
        rows = [
            f"**{discord.utils.escape_markdown(u.get('name', '?'))}** · 消息 {limit(u['messages'], config.CHAT_USER_DAILY)}"
            f" · 搜索 {limit(u['searches'], config.CHAT_SEARCH_DAILY)} · 长活 {limit(u.get('tasks', 0), config.CHAT_TASKS_DAILY)}"
            f" · 输入 {tokens(u['input'])}"
            f"（缓存命中 {tokens(u['cache_read'])}）· 输出 {tokens(u['output'])} tokens"
            for u in users[:15] if u["messages"] or u["searches"]
        ]
        embed.add_field(name="每个人", value="\n".join(rows)[:1024] or "今天还没有人和她聊天。", inline=False)

        totals = self.usage.totals(date.today() - timedelta(days=6))
        embed.add_field(
            name="最近 7 天合计",
            value=(
                f"消息 {totals['messages']} · 搜索 {totals['searches']} · 输入 {tokens(totals['input'])}"
                f"（缓存命中 {tokens(totals['cache_read'])}）· 输出 {tokens(totals['output'])} tokens\n"
                "-# 花了多少钱见 /余额"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    if not config.CHAT_ENABLED:
        log.warning("No DEEPSEEK_API_KEY or ANTHROPIC_API_KEY set; Priestess chat is disabled.")
        return
    log.info("Priestess chat: %s (%s)", config.CHAT_PROVIDER, config.CHAT_MODEL)
    await bot.add_cog(Chat(bot))
