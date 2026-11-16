from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import aiohttp
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad

import config
from music.sources.links import follow_short_link
from music.track import SourceError, Stream, Track

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.164 Safari/537.36"
)
EAPI_HOST = "https://interface3.music.163.com"
EAPI_KEY = b"e82ckenh8dichen8"
APP_VERSION = "3.0.18"

URL_RE = re.compile(r"^https?://([a-z0-9-]+\.)*(music\.163\.com|163cn\.tv)/", re.I)
ID_RE = re.compile(r"(song|playlist|album)(?:\?id=|/)(\d+)")


def _eapi_encrypt(path: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.md5(f"nobody{path}use{text}md5forencrypt".encode()).hexdigest()
    data = f"{path}-36cd479b6b5-{text}-36cd479b6b5-{digest}"
    return AES.new(EAPI_KEY, AES.MODE_ECB).encrypt(pad(data.encode(), 16)).hex().upper()


class NeteaseSource:
    name = "netease"

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    def matches_url(self, url: str) -> bool:
        return bool(URL_RE.match(url))

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    async def _eapi(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        cookie = f"os=pc; appver={APP_VERSION}"
        if config.NETEASE_MUSIC_U:
            cookie += f"; MUSIC_U={config.NETEASE_MUSIC_U}"
        payload = {**payload, "header": json.dumps({"os": "pc", "appver": APP_VERSION, "requestId": "0"})}
        session = await self._get_session()
        try:
            async with session.post(
                EAPI_HOST + "/eapi/" + path.removeprefix("/api/"),
                data={"params": _eapi_encrypt(path, payload)},
                headers={"User-Agent": UA, "Referer": "https://music.163.com", "Cookie": cookie},
                proxy=config.NETEASE_PROXY,
            ) as resp:
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise SourceError(f"网易云音乐: 网络错误 ({e.__class__.__name__})") from e
        if data.get("code") not in (200, None):
            raise SourceError(f"网易云音乐: {data.get('message') or data.get('msg') or data.get('code')}")
        return data

    def _to_track(self, song: dict[str, Any]) -> Track:
        artists = " / ".join(a.get("name") or "" for a in song.get("ar") or song.get("artists") or [])
        album = song.get("al") or song.get("album") or {}
        duration_ms = song.get("dt") or song.get("duration")
        return Track(
            source=self.name,
            id=str(song["id"]),
            title=song.get("name") or str(song["id"]),
            page_url=f"https://music.163.com/song?id={song['id']}",
            artist=artists or None,
            duration=duration_ms // 1000 if duration_ms else None,
            thumbnail=album.get("picUrl"),
            # originCoverType: 1 = original recording, 2/3 = cover, 0 = unknown
            extra={"original": song.get("originCoverType") == 1, "popularity": song.get("pop") or 0},
        )

    async def _song_details(self, ids: list[int | str]) -> list[Track]:
        tracks: list[Track] = []
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            data = await self._eapi("/api/v3/song/detail", {"c": json.dumps([{"id": int(x)} for x in chunk])})
            by_id = {str(s["id"]): s for s in data.get("songs") or []}
            tracks.extend(self._to_track(by_id[str(x)]) for x in chunk if str(x) in by_id)
        return tracks

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        data = await self._eapi(
            "/api/cloudsearch/pc", {"s": query, "type": 1, "limit": limit, "offset": 0, "total": True}
        )
        return [self._to_track(s) for s in (data.get("result") or {}).get("songs") or []]

    async def from_url(self, url: str) -> list[Track]:
        if re.match(r"^https?://163cn\.tv/", url, re.I):
            session = await self._get_session()
            url = await follow_short_link(session, url, ("163cn.tv", "music.163.com"), proxy=config.NETEASE_PROXY)

        m = ID_RE.search(url.replace("#/", ""))
        if not m:
            raise SourceError("网易云音乐: 无法识别这个链接，支持单曲、歌单和专辑链接")
        kind, item_id = m.groups()

        if kind == "song":
            tracks = await self._song_details([item_id])
        elif kind == "playlist":
            data = await self._eapi("/api/v6/playlist/detail", {"id": item_id, "n": 100000, "s": 8})
            ids = [t["id"] for t in (data.get("playlist") or {}).get("trackIds") or []]
            tracks = await self._song_details(ids[: config.MAX_PLAYLIST_ITEMS])
        else:
            data = await self._eapi(f"/api/v1/album/{item_id}", {})
            tracks = [self._to_track(s) for s in data.get("songs") or []][: config.MAX_PLAYLIST_ITEMS]

        if not tracks:
            raise SourceError("网易云音乐: 没有找到歌曲")
        return tracks

    async def resolve(self, track: Track) -> Stream:
        data = await self._eapi(
            "/api/song/enhance/player/url/v1",
            {"ids": json.dumps([int(track.id)]), "level": "exhigh", "encodeType": "mp3"},
        )
        info = (data.get("data") or [{}])[0]
        if not info.get("url"):
            if info.get("code") == 404:
                raise SourceError(
                    "网易云音乐: 当前地区无法播放这首歌（版权或海外 IP 限制），可以配置 NETEASE_PROXY"
                )
            if info.get("fee") == 1:
                raise SourceError("网易云音乐: 这首歌需要 VIP，可以配置你自己账号的 NETEASE_MUSIC_U")
            raise SourceError("网易云音乐: 无法获取播放链接（可能需要购买或已下架）")
        if info.get("freeTrialInfo"):
            raise SourceError("网易云音乐: 这首歌只能试听片段，需要 VIP 或购买")
        return Stream(url=info["url"], headers={"User-Agent": UA}, proxy=config.NETEASE_PROXY)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
