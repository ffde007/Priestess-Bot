"""DeepSeek's Search and Fetch APIs, for the chat's web_search and fetch_page tools.

https://api-docs.deepseek.com/guides/search/ — US$0.75 per 1,000 successful requests each
(empty results aren't billed). The bot calls them itself and hands the model a trimmed
summary, instead of the model's built-in search pasting whole pages into the prompt (about
US$0.013 a search before). Results whose text is on the "avoid" word list are dropped.
"""

from __future__ import annotations

import logging
from datetime import datetime

import aiohttp

import config
import moderation

log = logging.getLogger(__name__)

BASE = "https://api.deepseek.com/v1/tools"
RESULTS = 5  # results handed to the model
SUMMARY_CHARS = 600  # of each result's summary
PAGE_CHARS = 4000  # of a fetched page
MIN_SCORE = 0.8  # rerank_score (0-3) below which a result is too loosely related to keep


class SearchError(Exception):
    """A user-facing reason the search or fetch didn't work."""


async def _post(session: aiohttp.ClientSession, path: str, body: dict) -> dict:
    headers = {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    try:
        async with session.post(f"{BASE}/{path}", json=body, headers=headers) as resp:
            data = await resp.json(content_type=None)
            if resp.status == 200:
                return data
            message = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
    except (aiohttp.ClientError, TimeoutError, ValueError) as e:
        raise SearchError(f"连不上 DeepSeek 的搜索服务（{e.__class__.__name__}）") from e
    log.warning("DeepSeek %s returned %s: %s", path, resp.status, message)
    reasons = {402: "DeepSeek 余额不足", 403: "这个网页不允许读取", 404: "这个网页读不出内容", 429: "搜索太频繁了"}
    raise SearchError(reasons.get(resp.status, f"搜索服务出错（{resp.status}）"))


def _date(value: str | None) -> str:
    if not value:
        return "日期不明"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return value[:10]


async def search(session: aiohttp.ClientSession, query: str, question: str = "") -> str:
    """Plain-text results for the model: title, site, date, link and a short summary each."""
    body: dict = {"query": query.strip()[:128], "count": RESULTS * 2}
    if question.strip():
        body["ori_question"] = question.strip()[:128]
    results = (await _post(session, "search", body)).get("results") or []
    kept = []
    for r in results:
        text = f"{r.get('title') or ''} {r.get('summary') or r.get('snippet') or ''}"
        if (r.get("rerank_score") or 0) < MIN_SCORE or moderation.check(text, kinds=("avoid",)):
            continue
        kept.append(r)
        if len(kept) == RESULTS:
            break
    if not kept:
        return f"搜索「{query}」没有找到合适的结果。"
    blocks = []
    for i, r in enumerate(kept, 1):
        summary = " ".join((r.get("summary") or r.get("snippet") or "").split())[:SUMMARY_CHARS]
        source = r.get("site_name") or ""
        blocks.append(f"{i}. {r.get('title') or '（无标题）'}（{source}，{_date(r.get('date'))}）\n{r.get('url')}\n{summary}")
    return f"搜索「{query}」的结果（日期是网页发布日期）：\n\n" + "\n\n".join(blocks)


async def fetch(session: aiohttp.ClientSession, url: str) -> str:
    """A web page's text (Markdown), trimmed, for the model."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise SearchError("只能读取 http 或 https 开头的网页链接")
    data = await _post(session, "fetch", {"url": url[:8192]})
    content = (data.get("content") or "").strip()
    if not content:
        raise SearchError("这个网页读不出内容")
    if hit := moderation.check(content[:PAGE_CHARS], kinds=("avoid",)):
        log.info("Fetched page %s mentions %r; not passed on", url, hit[1])
        raise SearchError("这个网页的内容涉及不聊的话题")
    cut = "\n……（后面还有，已省略）" if len(content) > PAGE_CHARS else ""
    return f"网页「{data.get('title') or url}」的内容：\n{content[:PAGE_CHARS]}{cut}"
