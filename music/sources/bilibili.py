from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
from typing import Any

import aiohttp
from yarl import URL

import config
from music.sources.links import follow_short_link
from music.track import SourceError, Stream, Track

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
API = "https://api.bilibili.com"

URL_RE = re.compile(r"^https?://([a-z0-9-]+\.)*(bilibili\.com|b23\.tv|bili2233\.cn)/", re.I)
BVID_RE = re.compile(r"\b(BV[0-9A-Za-z]{10})\b")
AID_RE = re.compile(r"\bav(\d+)\b", re.I)

# Permutation used to derive the WBI mixin key (from Bilibili's web player).
MIXIN_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39,
    12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63,
    57, 62, 11, 36, 20, 34, 44, 52,
]


def _parse_duration(text: str | int | None) -> int | None:
    if isinstance(text, int):
        return text
    if not text:
        return None
    total = 0
    for part in str(text).split(":"):
        total = total * 60 + int(part or 0)
    return total


def _https(url: str | None) -> str | None:
    if url and url.startswith("//"):
        return "https:" + url
    return url


class BilibiliSource:
    name = "bilibili"

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._mixin_key: str | None = None
        self._mixin_expires = 0.0

    def matches_url(self, url: str) -> bool:
        return bool(URL_RE.match(url)) or bool(BVID_RE.fullmatch(url.strip()))

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15))
            # Device cookies (buvid3, b_nut) come from the homepage, the same way a browser gets
            # them; without them the API answers with HTTP 412.
            try:
                async with self._session.get("https://www.bilibili.com/") as resp:
                    await resp.read()
            except aiohttp.ClientError:
                pass
            if config.BILIBILI_SESSDATA:
                self._session.cookie_jar.update_cookies(
                    {"SESSDATA": config.BILIBILI_SESSDATA}, response_url=URL("https://www.bilibili.com")
                )
        return self._session

    async def _get_json(
        self, url: str, params: dict[str, Any] | None = None, session: aiohttp.ClientSession | None = None
    ) -> Any:
        session = session or await self._get_session()
        async with session.get(url, params=params) as resp:
            if resp.status == 412:
                raise SourceError("Bilibili: 请求被风控拦截 (412)，请稍后再试或配置 BILIBILI_SESSDATA")
            data = await resp.json(content_type=None)
        if data.get("code") != 0:
            raise SourceError(f"Bilibili: {data.get('message') or data.get('code')}")
        return data.get("data")

    async def _signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._mixin_key or time.time() > self._mixin_expires:
            session = await self._get_session()
            # /nav returns code -101 when logged out but still includes wbi_img, so skip _get_json.
            async with session.get(f"{API}/x/web-interface/nav") as resp:
                nav = await resp.json(content_type=None)
            img = nav["data"]["wbi_img"]
            raw = "".join(u.rsplit("/", 1)[1].split(".")[0] for u in (img["img_url"], img["sub_url"]))
            self._mixin_key = "".join(raw[i] for i in MIXIN_TABLE)[:32]
            self._mixin_expires = time.time() + 3600
        params = {**params, "wts": int(time.time())}
        params = {k: re.sub(r"[!'()*]", "", str(v)) for k, v in sorted(params.items())}
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        params["w_rid"] = hashlib.md5((query + self._mixin_key).encode()).hexdigest()
        return params

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        params = await self._signed_params({"search_type": "video", "keyword": query, "page": 1})
        data = await self._get_json(f"{API}/x/web-interface/wbi/search/type", params)
        if data.get("v_voucher"):
            raise SourceError("Bilibili: 搜索触发了人机验证，请稍后再试、直接发 BV 链接，或配置 BILIBILI_SESSDATA")
        tracks = []
        for item in (data.get("result") or [])[:limit]:
            title = html.unescape(re.sub(r"<[^>]+>", "", item.get("title", "")))
            tracks.append(
                Track(
                    source=self.name,
                    id=item["bvid"],
                    title=title,
                    page_url=f"https://www.bilibili.com/video/{item['bvid']}",
                    artist=item.get("author"),
                    duration=_parse_duration(item.get("duration")),
                    thumbnail=_https(item.get("pic")),
                    extra={"bvid": item["bvid"]},
                )
            )
        return tracks

    async def from_url(self, url: str) -> list[Track]:
        url = url.strip()
        if re.match(r"^https?://(b23\.tv|bili2233\.cn)/", url, re.I):
            session = await self._get_session()
            url = await follow_short_link(session, url, ("b23.tv", "bili2233.cn", "bilibili.com"))

        page: int | None = None
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if "p" in query and query["p"][0].isdigit():
            page = int(query["p"][0])

        if m := BVID_RE.search(url):
            params = {"bvid": m.group(1)}
        elif m := AID_RE.search(url):
            params = {"aid": m.group(1)}
        else:
            raise SourceError("Bilibili: 无法识别这个链接，请使用视频链接 (BV 号)")

        view = await self._get_json(f"{API}/x/web-interface/view", params)
        pages = view.get("pages") or [{"cid": view["cid"], "page": 1, "part": "", "duration": view.get("duration")}]
        if page is not None:
            pages = [p for p in pages if p["page"] == page] or pages[:1]
        multi = len(view.get("pages") or []) > 1

        tracks = []
        for p in pages[: config.MAX_PLAYLIST_ITEMS]:
            title = view["title"]
            if multi:
                title = f"{title} - P{p['page']} {p.get('part', '')}".rstrip()
            tracks.append(
                Track(
                    source=self.name,
                    id=f"{view['bvid']}:{p['cid']}",
                    title=title,
                    page_url=f"https://www.bilibili.com/video/{view['bvid']}" + (f"?p={p['page']}" if multi else ""),
                    artist=(view.get("owner") or {}).get("name"),
                    duration=p.get("duration") or view.get("duration"),
                    thumbnail=_https(view.get("pic")),
                    extra={"bvid": view["bvid"], "cid": p["cid"]},
                )
            )
        return tracks

    async def resolve(self, track: Track) -> Stream:
        bvid = track.extra["bvid"]
        cid = track.extra.get("cid")
        if cid is None:
            # Search results don't carry a cid; look up the first page.
            view = await self._get_json(f"{API}/x/web-interface/view", {"bvid": bvid})
            cid = track.extra["cid"] = view["cid"]

        params = await self._signed_params({"bvid": bvid, "cid": cid, "fnval": 16, "fourk": 1})
        data = await self._get_json(f"{API}/x/player/wbi/playurl", params)

        url = None
        dash = data.get("dash") or {}
        audios = list(dash.get("audio") or [])
        if (dash.get("flac") or {}).get("audio"):
            audios.append(dash["flac"]["audio"])
        if audios:
            best = max(audios, key=lambda a: a.get("bandwidth", 0))
            url = best.get("baseUrl") or best.get("base_url")
        elif data.get("durl"):
            url = data["durl"][0]["url"]
        if not url:
            raise SourceError("Bilibili: 没有找到可播放的音频流")
        return Stream(url=url, headers=HEADERS)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
