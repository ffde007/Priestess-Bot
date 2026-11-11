from __future__ import annotations

import asyncio
import logging
import os
import random
import shlex
import subprocess
import time
from collections import deque
from enum import Enum
from typing import TYPE_CHECKING

import discord

import config
import siren_lore
from music.track import SOURCE_COLORS, SourceError, Stream, Track, format_duration
from persona import line

if TYPE_CHECKING:
    from music.resolver import Resolver

log = logging.getLogger(__name__)

FFMPEG = config.ffmpeg_path()
RADIO_MEMORY = 60  # the radio doesn't repeat any of this many recent songs


class LoopMode(str, Enum):
    OFF = "off"
    ONE = "one"
    ALL = "all"


class PipedFFmpegAudio(discord.FFmpegPCMAudio):
    """FFmpeg reading from a feeder process's stdout; the feeder and temp files go away with it."""

    def __init__(self, stream: Stream):
        assert stream.pipe_cmd
        self._temp_files = stream.temp_files
        self._feeder = subprocess.Popen(
            stream.pipe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        super().__init__(self._feeder.stdout, executable=FFMPEG, pipe=True, options="-vn -loglevel error")

    def cleanup(self) -> None:
        super().cleanup()
        if self._feeder.poll() is None:
            self._feeder.kill()
        for path in self._temp_files:
            try:
                os.remove(path)
            except OSError:
                pass


def build_audio(stream: Stream, volume: float) -> discord.PCMVolumeTransformer:
    if stream.pipe_cmd:
        return discord.PCMVolumeTransformer(PipedFFmpegAudio(stream), volume=volume)

    # stream.url is always http(s): Stream checks it when it's made.
    # discord.py runs shlex.split() on these, so quote every value.
    before = ["-nostdin", "-reconnect 1", "-reconnect_streamed 1", "-reconnect_delay_max 5"]
    headers = {k.lower(): v for k, v in stream.headers.items()}
    if "user-agent" in headers:
        before.append(f"-user_agent {shlex.quote(headers['user-agent'])}")
    if "referer" in headers:
        before.append(f"-referer {shlex.quote(headers['referer'])}")
    if stream.proxy:
        before.append(f"-http_proxy {shlex.quote(stream.proxy)}")
    source = discord.FFmpegPCMAudio(
        stream.url, executable=FFMPEG, before_options=" ".join(before), options="-vn -loglevel error"
    )
    return discord.PCMVolumeTransformer(source, volume=volume)


class GuildPlayer:
    """Queue and playback loop for one guild."""

    def __init__(self, bot: discord.Client, guild: discord.Guild, resolver: Resolver, channel: discord.abc.Messageable):
        self.bot = bot
        self.guild = guild
        self.resolver = resolver
        self.channel = channel  # where "now playing" messages go
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.loop_mode = LoopMode.OFF
        self.volume = config.DEFAULT_VOLUME / 100
        self.started_at = 0.0
        self.paused_at: float | None = None
        # Siren radio: when the queue runs out, keep going with random Monster Siren songs.
        self.radio = False
        self._radio_recent: deque[str] = deque(maxlen=RADIO_MEMORY)

        self._wake = asyncio.Event()
        self._finished = asyncio.Event()
        self._skip_requested = False
        self._task = asyncio.create_task(self._run())

    @property
    def voice(self) -> discord.VoiceClient | None:
        return self.guild.voice_client  # type: ignore[return-value]

    @property
    def position(self) -> float:
        if not self.current:
            return 0
        end = self.paused_at or time.monotonic()
        return end - self.started_at

    def add(self, tracks: list[Track], *, front: bool = False) -> None:
        if front:
            self.queue[0:0] = tracks
        else:
            self.queue.extend(tracks)
        self._wake.set()

    def skip(self) -> None:
        self._skip_requested = True
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()

    def pause(self) -> bool:
        if self.voice and self.voice.is_playing():
            self.voice.pause()
            self.paused_at = time.monotonic()
            return True
        return False

    def resume(self) -> bool:
        if self.voice and self.voice.is_paused():
            self.voice.resume()
            if self.paused_at:
                self.started_at += time.monotonic() - self.paused_at
            self.paused_at = None
            return True
        return False

    def stop(self) -> None:
        self.queue.clear()
        self.loop_mode = LoopMode.OFF
        self.radio = False  # otherwise the radio would start the next song right away
        self.skip()

    def set_radio(self, on: bool) -> None:
        self.radio = on
        self._wake.set()  # start right away if nothing is queued

    def shuffle(self) -> None:
        random.shuffle(self.queue)

    def set_volume(self, percent: int) -> None:
        self.volume = percent / 100
        if self.voice and isinstance(self.voice.source, discord.PCMVolumeTransformer):
            self.voice.source.volume = self.volume

    async def destroy(self) -> None:
        self._task.cancel()
        self.queue.clear()
        self.current = None
        if self.voice:
            await self.voice.disconnect(force=True)

    async def _run(self) -> None:
        try:
            while True:
                if not self.queue and self.radio:
                    try:
                        track = await self.resolver.siren.random_track(set(self._radio_recent))
                    except SourceError as e:
                        log.warning("Radio couldn't pick a song: %s", e)
                        self.radio = False
                        await self.channel.send(line("radio_failed", error=e))
                        continue
                    track.extra["radio"] = True
                    self._radio_recent.append(track.id)
                    self.queue.append(track)
                if not self.queue:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=config.IDLE_TIMEOUT)
                    except asyncio.TimeoutError:
                        await self.channel.send(line("idle_leave"))
                        self.bot.dispatch("music_player_idle", self.guild.id)
                        return
                    continue

                track = self.queue.pop(0)
                # A NetEase track may have been swapped for a fallback; loop that one instead.
                finished = await self._play(track) or track
                self.current = None
                if not self._skip_requested:
                    if self.loop_mode is LoopMode.ONE:
                        self.queue.insert(0, finished)
                    elif self.loop_mode is LoopMode.ALL:
                        self.queue.append(finished)
                elif self.loop_mode is LoopMode.ALL:
                    self.queue.append(finished)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Player loop crashed in guild %s", self.guild.id)

    async def _resolve_with_fallback(self, track: Track) -> tuple[Track, Stream] | None:
        name = discord.utils.escape_markdown(track.display)
        try:
            return track, await self.resolver.resolve(track)
        except SourceError as e:
            error = str(e)
        except Exception:
            log.exception("Failed to resolve %s", track.page_url)
            error = line("resolve_failed")

        if track.source == "netease" and self.resolver.fallback:
            found = await self.resolver.find_alternative(track)
            if found:
                alt = found[0]
                await self.channel.send(
                    line(
                        "fallback",
                        title=name,
                        label=alt.label,
                        alt=discord.utils.escape_markdown(alt.title),
                        url=alt.page_url,
                    )
                )
                return found
            error += line("no_alternative")

        await self.channel.send(line("track_skipped", title=name, error=error))
        return None

    async def _play(self, track: Track) -> Track | None:
        """Play a track to the end. Returns the track actually played, which may be a fallback."""
        self._skip_requested = False
        if not self.voice or not self.voice.is_connected():
            # Disconnected (kicked or moved away); drop the queue.
            self.queue.clear()
            return None
        resolved = await self._resolve_with_fallback(track)
        if not resolved:
            self._skip_requested = True  # don't loop a track that can't play
            return None
        track, stream = resolved
        if self._skip_requested or not self.voice or not self.voice.is_connected():
            # Skipped or disconnected while the stream was being resolved.
            for path in stream.temp_files:
                try:
                    os.remove(path)
                except OSError:
                    pass
            return None

        self._finished.clear()
        loop = asyncio.get_running_loop()

        def after(error: Exception | None) -> None:
            if error:
                log.error("Playback error: %s", error)
            loop.call_soon_threadsafe(self._finished.set)

        self.current = track
        self.started_at = time.monotonic()
        self.paused_at = None
        # Picked once per play, so /nowplaying shows the same line as the announcement.
        await self.resolver.siren.ensure_catalog()
        track.extra["comment"] = siren_lore.track_comment(
            track.source, track.title, track.extra.get("album", ""), track.artist or ""
        )
        self.voice.play(build_audio(stream, self.volume), after=after)
        await self.channel.send(embed=self.now_playing_embed())
        await self._finished.wait()
        return track

    def now_playing_embed(self) -> discord.Embed:
        track = self.current
        if not track:
            return discord.Embed(description=line("nothing_playing"), color=0x5865F2)
        embed = discord.Embed(
            title=track.title[:256],
            url=track.page_url,
            color=SOURCE_COLORS.get(track.source, 0x5865F2),
            description=f"*{track.extra['comment']}*" if track.extra.get("comment") else None,
        )
        embed.set_author(name=line("radio_author") if track.extra.get("radio") else line("now_playing_author", label=track.label))
        if track.artist:
            embed.add_field(name="作者 / 歌手", value=track.artist[:1024])
        if album := track.extra.get("album"):
            embed.add_field(name="专辑", value=album[:1024])
        embed.add_field(name="时长", value=f"{format_duration(self.position)} / {track.duration_text}")
        if track.requester_id:
            embed.add_field(name="点歌人", value=f"<@{track.requester_id}>")
        if self.loop_mode is not LoopMode.OFF:
            embed.add_field(name="循环", value={"one": "单曲", "all": "列表"}[self.loop_mode.value])
        if intro := track.extra.get("album_intro"):
            # The official album description, fetched from Monster Siren when the song started.
            embed.add_field(name="专辑简介（塞壬唱片）", value=intro[:300], inline=False)
        if self.queue:
            embed.set_footer(text=f"队列中还有 {len(self.queue)} 首")
        elif self.radio:
            embed.set_footer(text="塞壬电台开着：放完会随机接下一首 · /电台 关 可以停下")
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        return embed
