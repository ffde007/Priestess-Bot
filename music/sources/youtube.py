from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
from typing import Any

import yt_dlp

import config
from music.track import SourceError, Stream, Track

log = logging.getLogger(__name__)

URL_RE = re.compile(r"^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be)/", re.I)
FORMAT = "bestaudio/best"
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
LIST_ID_RE = re.compile(r"[A-Za-z0-9_-]{2,64}")
# Only these yt-dlp extractors may run. Anything else (consent or redirect pages, the generic
# extractor) could make the bot fetch a URL a chat member chose, such as a local service.
EXTRACTORS = ["youtube", "youtube:tab", "youtube:search"]
# YouTube's player JS must be solved by a JS runtime; Node is the most common one. Without
# one, yt-dlp still tries (deprecated, some formats missing) and may stop working any time.
JS_RUNTIMES = ("node", "deno")


def canonical_url(url: str) -> str | None:
    """A rebuilt https://www.youtube.com watch or playlist URL, or None for any other link.

    Users paste many shapes (youtu.be, m., music., shorts, &list=). Only the video or playlist
    ID is taken from them, so nothing else in the link reaches yt-dlp.
    """
    parsed = urllib.parse.urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https"):
        return None
    query = urllib.parse.parse_qs(parsed.query)
    path = parsed.path.rstrip("/")
    video = None
    if host == "youtu.be":
        video = path.lstrip("/")
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        if path == "/watch":
            video = (query.get("v") or [""])[0]
        elif m := re.fullmatch(r"/(?:shorts|live|embed)/([^/]+)", path):
            video = m.group(1)
        elif path == "/playlist":
            playlist = (query.get("list") or [""])[0]
            if LIST_ID_RE.fullmatch(playlist):
                return f"https://www.youtube.com/playlist?list={playlist}"
            return None
    if video and VIDEO_ID_RE.fullmatch(video):
        return f"https://www.youtube.com/watch?v={video}"
    return None


class YouTubeSource:
    name = "youtube"

    def __init__(self) -> None:
        self._base_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "allowed_extractors": EXTRACTORS,
            "js_runtimes": {name: {} for name in JS_RUNTIMES},
        }
        if config.YOUTUBE_COOKIES:
            self._base_opts["cookiefile"] = config.YOUTUBE_COOKIES
        if not any(shutil.which(name) for name in JS_RUNTIMES):
            log.warning(
                "Neither Node.js nor Deno was found: YouTube links may fail to play (other sources "
                "are fine). Install Node.js from https://nodejs.org/ and restart."
            )

    def matches_url(self, url: str) -> bool:
        return bool(URL_RE.match(url))

    def _extract(self, target: str, **opts: Any) -> dict[str, Any]:
        try:
            with yt_dlp.YoutubeDL({**self._base_opts, **opts}) as ydl:
                return ydl.extract_info(target, download=False)
        except yt_dlp.utils.DownloadError as e:
            message = str(e).removeprefix("ERROR: ")
            raise SourceError(f"YouTube: {message}") from e

    def _to_track(self, entry: dict[str, Any]) -> Track:
        video_id = entry.get("id") or ""
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise SourceError("YouTube: 链接里有无法识别的视频")
        url = f"https://www.youtube.com/watch?v={video_id}"  # never a URL taken from the response
        thumbnail = entry.get("thumbnail")
        if not thumbnail and entry.get("thumbnails"):
            thumbnail = entry["thumbnails"][-1].get("url")
        return Track(
            source=self.name,
            id=video_id,
            title=entry.get("title") or video_id,
            page_url=url,
            artist=entry.get("channel") or entry.get("uploader"),
            duration=entry.get("duration"),
            thumbnail=thumbnail,
        )

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        info = await asyncio.to_thread(self._extract, f"ytsearch{limit}:{query}", extract_flat="in_playlist")
        return [self._to_track(e) for e in info.get("entries") or [] if e and VIDEO_ID_RE.fullmatch(e.get("id") or "")]

    async def from_url(self, url: str) -> list[Track]:
        # A watch URL that also carries &list= plays just that video (the list ID is dropped).
        url = canonical_url(url)
        if not url:
            raise SourceError("YouTube: 只支持视频链接和播放列表链接")
        info = await asyncio.to_thread(
            self._extract, url, extract_flat="in_playlist", playlistend=config.MAX_PLAYLIST_ITEMS
        )
        if info.get("_type") == "playlist":
            return [self._to_track(e) for e in info.get("entries") or [] if e and VIDEO_ID_RE.fullmatch(e.get("id") or "")]
        return [self._to_track(info)]

    def _extract_for_playback(self, url: str) -> tuple[dict[str, Any], str]:
        url = canonical_url(url) or ""
        if "/watch?v=" not in url:
            raise SourceError("YouTube: 只能播放视频链接")
        with yt_dlp.YoutubeDL({**self._base_opts, "format": FORMAT, "noplaylist": True}) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as e:
                raise SourceError(f"YouTube: {str(e).removeprefix('ERROR: ')}") from e
            sanitized = ydl.sanitize_info(info)
        fd, path = tempfile.mkstemp(prefix="musicbot-", suffix=".info.json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sanitized, f)
        return info, path

    async def resolve(self, track: Track) -> Stream:
        info, info_path = await asyncio.to_thread(self._extract_for_playback, track.page_url)
        if not info.get("url"):
            os.remove(info_path)
            raise SourceError("YouTube: 没有找到可播放的音频流")
        # Fill in details that flat playlist extraction leaves out.
        track.duration = track.duration or info.get("duration")
        track.thumbnail = track.thumbnail or info.get("thumbnail")
        # googlevideo rejects ffmpeg's own HTTP requests (403), so let yt-dlp's downloader fetch
        # the audio and pipe it to ffmpeg. --load-info-json reuses this extraction.
        cmd = [
            sys.executable, "-m", "yt_dlp", "--load-info-json", info_path,
            "-f", FORMAT, "-o", "-", "--quiet", "--no-warnings", "--no-part", "--no-cache-dir",
        ]
        return Stream(url=info["url"], pipe_cmd=cmd, temp_files=[info_path])

    async def close(self) -> None:
        pass
