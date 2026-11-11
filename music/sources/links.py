"""Following share short links (b23.tv, 163cn.tv) without leaving the platform's own sites."""

from __future__ import annotations

import aiohttp
from yarl import URL

from music.track import SourceError

MAX_HOPS = 5


def host_allowed(url: URL, domains: tuple[str, ...]) -> bool:
    host = (url.host or "").lower()
    return url.scheme in ("http", "https") and any(host == d or host.endswith("." + d) for d in domains)


async def follow_short_link(
    session: aiohttp.ClientSession, url: str, domains: tuple[str, ...], proxy: str | None = None
) -> str:
    """The page a short link points to, following redirects one at a time.

    Every hop must stay on one of the given domains, so a link can't make the bot request
    another site (or a service on this computer).
    """
    current = URL(url)
    for _ in range(MAX_HOPS):
        if not host_allowed(current, domains):
            raise SourceError("这个短链接指向了不支持的网站")
        async with session.get(current, allow_redirects=False, proxy=proxy) as resp:
            location = resp.headers.get("Location")
            if resp.status not in (301, 302, 303, 307, 308) or not location:
                return str(current)
        current = current.join(URL(location))
    raise SourceError("这个短链接跳转太多次了")
