from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SOURCE_LABELS = {
    "youtube": "YouTube",
    "bilibili": "Bilibili",
    "netease": "网易云音乐",
    "siren": "塞壬唱片",
}

SOURCE_COLORS = {
    "youtube": 0xFF0000,
    "bilibili": 0xFB7299,
    "netease": 0xC20C0C,
    "siren": 0x23272A,
}


class SourceError(Exception):
    """A user-facing error raised while searching or resolving a track."""


@dataclass
class Track:
    source: str
    id: str
    title: str
    page_url: str
    artist: str | None = None
    duration: int | None = None  # seconds
    thumbnail: str | None = None
    requester_id: int | None = None
    # Source-specific data needed to resolve the stream later (e.g. Bilibili cid).
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def display(self) -> str:
        return f"{self.title} - {self.artist}" if self.artist else self.title

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)


@dataclass
class Stream:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    proxy: str | None = None
    # When set, this command writes the audio to stdout and ffmpeg reads it from a pipe
    # instead of fetching `url` itself.
    pipe_cmd: list[str] | None = None
    # Temporary files to delete once playback ends.
    temp_files: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # ffmpeg gets `url` as its input. Media URLs come from the platforms' APIs; anything but
        # http(s) (file:, concat:, a value starting with "-") could make it read local files.
        if not self.pipe_cmd and not self.url.lower().startswith(("https://", "http://")):
            raise SourceError("音源地址不是网址，没有播放")


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
