"""SerpApi client shared by the live-data tools (travel.py, lookup.py).

https://serpapi.com — the free plan has 250 searches a month. Every lookup is counted in
data/serpapi_usage.json before it's sent, and the bot stops at SERPAPI_MONTHLY_LIMIT. Lookups
sent elsewhere with the same key aren't counted, so SerpApi's own dashboard has the last word.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import aiohttp

import config

log = logging.getLogger(__name__)

API = "https://serpapi.com/search.json"
USAGE_FILE = Path(__file__).parent / "data" / "serpapi_usage.json"


class SerpError(Exception):
    """A user-facing reason the lookup didn't work."""


def _month() -> str:
    return date.today().strftime("%Y-%m")


def _load() -> dict:
    """The monthly counts. A damaged file stops lookups rather than starting over from 0."""
    try:
        text = USAGE_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise SerpError("读不了查询次数的记录") from e
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data
    except ValueError as e:
        log.error("%s is damaged (%s); lookups are off until it's fixed or deleted", USAGE_FILE, e)
        raise SerpError("查询次数的记录损坏了") from e


def used_this_month() -> int:
    return int(_load().get(_month(), 0))


def _reserve_one() -> None:
    """Check the monthly limit and count one lookup, with no waiting in between: lookups
    running at the same time each see the others' counts, so the limit can't be overrun."""
    data = _load()
    if int(data.get(_month(), 0)) >= config.SERPAPI_MONTHLY_LIMIT:
        raise SerpError(f"这个月的实时查询次数（{config.SERPAPI_MONTHLY_LIMIT} 次）已经用完了")
    data[_month()] = int(data.get(_month(), 0)) + 1
    try:
        USAGE_FILE.parent.mkdir(exist_ok=True)
        USAGE_FILE.write_text(json.dumps(data), encoding="utf-8")
    except OSError as e:
        raise SerpError("记不下查询次数") from e


async def search(params: dict) -> dict:
    """One SerpApi request (params include the engine and its localization). {} when Google
    found nothing."""
    if not config.SERPAPI_KEY:
        raise SerpError("没有配置 SERPAPI_KEY")
    # Counted before the request and kept even if it fails: a timeout may still be billed.
    _reserve_one()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            async with session.get(API, params={**params, "api_key": config.SERPAPI_KEY}) as resp:
                data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as e:
        raise SerpError(f"连不上查询服务（{e.__class__.__name__}）") from e
    if not isinstance(data, dict):
        raise SerpError("查询服务返回了看不懂的内容")
    if error := data.get("error"):
        log.warning("SerpApi %s error: %s", params.get("engine"), error)
        if "hasn't returned any results" in str(error):
            return {}
        raise SerpError(str(error)[:200])
    # SerpApi doesn't bill repeats it serves from its cache, but the response doesn't say which
    # ones those were: every lookup is counted, so the monthly limit errs on the safe side.
    return data
