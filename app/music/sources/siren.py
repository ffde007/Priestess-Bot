"""Monster Siren Records (塞壬唱片), Arknights' official label: official audio, no region locks.

The catalog (about a thousand songs) is small enough to keep in memory and search locally.
Search also understands the Chinese titles and character names in siren_lore, so "飞驰如光"
finds Speed of Light and "凯尔希" finds Kal'tsit's songs.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

import aiohttp

import siren_lore
from music.track import SourceError, Stream, Track

API = "https://monster-siren.hypergryph.com/api"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
URL_RE = re.compile(r"^https?://monster-siren\.hypergryph\.com/music/(\d+)", re.I)
CATALOG_TTL = 12 * 3600
# Words that only say "this is Arknights music"; dropped before matching titles.
LABEL_WORDS_RE = re.compile(r"明日方舟|塞壬唱片|塞壬|arknights|monster\s*siren|msr|ost|原声|bgm", re.I)


class SirenSource:
    name = "siren"

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._songs: list[dict[str, Any]] = []
        self._albums: dict[str, dict[str, Any]] = {}
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()
        self._intros: dict[str, str] = {}

    def matches_url(self, url: str) -> bool:
        return bool(URL_RE.match(url.strip()))

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=15)
            )
        return self._session

    async def _get(self, path: str) -> Any:
        session = await self._get_session()
        try:
            async with session.get(API + path) as resp:
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise SourceError(f"塞壬唱片: 网络错误 ({e.__class__.__name__})") from e
        if data.get("code") != 0:
            raise SourceError(f"塞壬唱片: {data.get('msg') or data.get('code')}")
        return data["data"]

    async def _catalog(self) -> list[dict[str, Any]]:
        async with self._lock:
            if not self._songs or time.time() - self._loaded_at > CATALOG_TTL:
                songs, albums = await asyncio.gather(self._get("/songs"), self._get("/albums"))
                self._albums = {a["cid"]: a for a in albums}
                self._songs = []
                for song in songs["list"]:
                    album = self._albums.get(song["albumCid"], {})
                    album_name = (album.get("name") or "").strip()
                    lore = siren_lore.lookup(song["name"], album_name)
                    self._songs.append(
                        {
                            **song,
                            "album_name": album_name,
                            "cover": album.get("coverUrl"),
                            "n_name": siren_lore.norm(song["name"]),
                            "n_album": siren_lore.norm(album_name),
                            "n_aliases": [siren_lore.norm(a) for a in (lore.aliases if lore else ())],
                            "n_chars": [siren_lore.norm(c) for c in (lore.characters if lore else ())],
                        }
                    )
                siren_lore.register_catalog([(s["name"], s["album_name"]) for s in self._songs])
                self._loaded_at = time.time()
            return self._songs

    async def ensure_catalog(self) -> None:
        """Load the catalog if needed, so siren_lore can recognise Siren songs from other platforms."""
        try:
            await self._catalog()
        except SourceError:
            pass

    def _to_track(self, song: dict[str, Any]) -> Track:
        return Track(
            source=self.name,
            id=song["cid"],
            title=song["name"],
            page_url=f"https://monster-siren.hypergryph.com/music/{song['cid']}",
            artist=" / ".join(song.get("artists") or []) or "塞壬唱片-MSR",
            thumbnail=song.get("cover"),
            extra={"album": song["album_name"], "album_cid": song["albumCid"]},
        )

    @staticmethod
    def _score(song: dict[str, Any], q: str) -> float:
        if song["n_name"] == q:
            return 100
        if q in song["n_aliases"]:
            return 90  # a Chinese title ("夜曲") is often another song's name too
        if song["n_album"] == q:
            return 80
        if len(q) < 2 or (q.isascii() and len(q) < 3):
            return 0
        if q in song["n_name"]:
            return 60
        if any(q in a for a in song["n_aliases"]):
            return 55
        if q in song["n_chars"]:
            return 50
        if q in song["n_album"]:
            return 40
        return 0

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        return [t for _, t in await self.search_scored(query, limit)]

    async def search_scored(self, query: str, limit: int = 5) -> list[tuple[float, Track]]:
        q = siren_lore.norm(LABEL_WORDS_RE.sub(" ", query)) or siren_lore.norm(query)
        if not q:
            return []
        songs = await self._catalog()
        scored = [(self._score(s, q), i, s) for i, s in enumerate(songs)]
        scored = [x for x in scored if x[0] > 0]
        # Best match first; within a score, keep the catalog's order (album track order).
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(score, self._to_track(s)) for score, _, s in scored[:limit]]

    async def random_track(self, exclude: set[str] = frozenset()) -> Track:
        """A random song for the radio: no instrumental duplicates, nothing played recently."""
        songs = [s for s in await self._catalog() if "instrumental" not in s["name"].lower()]
        fresh = [s for s in songs if s["cid"] not in exclude] or songs
        if not fresh:
            raise SourceError("塞壬唱片: 曲库是空的")
        return self._to_track(random.choice(fresh))

    async def from_url(self, url: str) -> list[Track]:
        m = URL_RE.match(url.strip())
        if not m:
            raise SourceError("塞壬唱片: 无法识别这个链接")
        for song in await self._catalog():
            if song["cid"] == m.group(1):
                return [self._to_track(song)]
        raise SourceError("塞壬唱片: 没有找到这首歌")

    async def album_intro(self, album_cid: str) -> str | None:
        if album_cid not in self._intros:
            try:
                detail = await self._get(f"/album/{album_cid}/detail")
                self._intros[album_cid] = (detail.get("intro") or "").strip()
            except SourceError:
                return None
        return self._intros[album_cid] or None

    async def resolve(self, track: Track) -> Stream:
        song = await self._get(f"/song/{track.id}")
        if not song.get("sourceUrl"):
            raise SourceError("塞壬唱片: 这首歌没有可播放的音频")
        if intro := await self.album_intro(track.extra.get("album_cid", "")):
            track.extra["album_intro"] = intro
        return Stream(url=song["sourceUrl"], headers={"User-Agent": UA})

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
