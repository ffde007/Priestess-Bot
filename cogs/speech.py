"""Talk mode: she reads her chat replies aloud in a voice channel, with her GPT-SoVITS voice.

/语音模块 (the deployer, see access.py, or the tray menu) starts or stops GPT-SoVITS; it also stops by itself
after SOVITS_IDLE_MINUTES with nobody in talk mode. /说话 (anyone) brings her into the voice
channel in talk mode, as long as no music is playing; while it lasts, music waits (and the
other way round, like the Siren radio). Replies to messages in the channel where talk mode was
started are read aloud, sentence by sentence: the next one is synthesized while one plays.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

import access
import config
from persona import line, who
from speech import SpeechEngine, SpeechError, sentences, speakable

log = logging.getLogger(__name__)

TOGGLE_CHOICES = [app_commands.Choice(name="开", value="on"), app_commands.Choice(name="关", value="off")]
ALONE_GRACE = 60  # seconds before leaving a voice channel nobody else is in
VOLUME = 1.0


@dataclass
class TalkSession:
    voice: discord.VoiceClient
    text_channel_id: int
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None


class Speech(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = SpeechEngine()
        self.sessions: dict[int, TalkSession] = {}
        self.idle_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self.idle_task = asyncio.create_task(self._idle_watch())

    async def cog_unload(self) -> None:
        if self.idle_task:
            self.idle_task.cancel()
        for guild_id in list(self.sessions):
            await self.end_talk(guild_id)
        await self.engine.close()

    # ---- state other parts of the bot ask about ------------------------------

    def active(self, guild_id: int) -> bool:
        return guild_id in self.sessions

    def listening(self, message: discord.Message) -> bool:
        """Whether her reply to this message will be read aloud."""
        session = self.sessions.get(message.guild.id) if message.guild else None
        return bool(session and session.text_channel_id == message.channel.id)

    def status_text(self) -> str:
        state = {"off": "已关闭", "starting": "正在启动……", "on": "运行中"}[self.engine.state]
        if self.engine.state == "on":
            state += f"（说话模式：{'开' if self.sessions else '关'}）"
        return state

    # ---- the voice module (GPT-SoVITS) -------------------------------------------

    async def start_module(self) -> str:
        return await self.engine.start()

    async def stop_module(self) -> bool:
        for guild_id in list(self.sessions):
            await self.end_talk(guild_id, line("talk_module_stopped"))
        return await self.engine.stop()

    async def _idle_watch(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                idle = time.monotonic() - self.engine.last_used
                if self.engine.state == "on" and not self.sessions and idle > config.SOVITS_IDLE_MINUTES * 60:
                    log.info("Voice module idle for %d min; stopping it", config.SOVITS_IDLE_MINUTES)
                    await self.engine.stop()
            except Exception:
                log.exception("Voice idle check failed")

    # ---- talk mode -----------------------------------------------------------------

    async def start_talk(self, member: discord.Member, text_channel: discord.abc.Messageable) -> str:
        """Join the member's voice channel in talk mode; her line for the reply."""
        if self.engine.state != "on":
            return line("talk_module_off")
        if not member.voice or not member.voice.channel:
            return line("need_voice", who=who(member, member.guild))
        guild = member.guild
        if guild.id in self.sessions:
            return line("talk_already")
        music = self.bot.get_cog("Music")
        player = music.players.get(guild.id) if music else None  # type: ignore[attr-defined]
        if player and (player.current or player.queue or player.radio):
            return line("talk_music_playing")
        if player:  # connected but idle: hand the voice connection over to talk mode
            music.players.pop(guild.id, None)  # type: ignore[union-attr]
            await player.destroy()

        voice = guild.voice_client
        if voice is None:
            voice = await member.voice.channel.connect(self_deaf=True)
        elif voice.channel != member.voice.channel:
            await voice.move_to(member.voice.channel)  # type: ignore[union-attr]
        session = TalkSession(voice=voice, text_channel_id=text_channel.id)  # type: ignore[arg-type, attr-defined]
        session.task = asyncio.create_task(self._speaker(guild.id, session))
        self.sessions[guild.id] = session
        greeting = line("talk_on")
        self.say_in(guild.id, greeting)
        return greeting

    async def end_talk(self, guild_id: int, farewell: str | None = None) -> bool:
        session = self.sessions.pop(guild_id, None)
        if not session:
            return False
        if session.task:
            session.task.cancel()
        if session.voice.is_connected():
            await session.voice.disconnect(force=True)
        self.engine.last_used = time.monotonic()  # the idle countdown starts now
        if farewell:
            channel = self.bot.get_channel(session.text_channel_id)
            if channel:
                await channel.send(farewell)  # type: ignore[union-attr]
        return True

    def say(self, message: discord.Message, text: str) -> None:
        if self.listening(message):
            self.say_in(message.guild.id, text)  # type: ignore[union-attr]

    def say_in(self, guild_id: int, text: str) -> None:
        session = self.sessions.get(guild_id)
        spoken = speakable(text)
        if session and spoken:
            session.queue.put_nowait(spoken)

    async def _speaker(self, guild_id: int, session: TalkSession) -> None:
        """Read queued replies one after another; synthesize the next sentence while one plays."""
        pauses = (self.engine.cfg or {}).get("pauses_seconds", {})
        try:
            while True:
                text = await session.queue.get()
                parts = sentences(text, pauses)
                if not parts:
                    continue
                pending = asyncio.create_task(self.engine.synthesize(parts[0][0]))
                for i, (_, pause) in enumerate(parts):
                    try:
                        wav = await pending
                    except SpeechError as e:
                        log.warning("Speech failed: %s", e)
                        await self._report_failure(session, e)
                        break
                    if i + 1 < len(parts):
                        pending = asyncio.create_task(self.engine.synthesize(parts[i + 1][0]))
                    await self._play(session.voice, wav)
                    if i + 1 < len(parts):
                        await asyncio.sleep(pause)
                else:
                    continue
                if not pending.done():
                    pending.cancel()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Talk mode speaker crashed in guild %s", guild_id)

    def _ffmpeg_options(self) -> str:
        post = self.engine.post_filter
        return "-vn -loglevel error" + (f' -af "{post}"' if post else "")

    async def _play(self, voice: discord.VoiceClient, wav: bytes) -> None:
        if not voice.is_connected():
            return
        fd, path = tempfile.mkstemp(prefix="priestess-", suffix=".wav")
        with os.fdopen(fd, "wb") as f:
            f.write(wav)
        finished = asyncio.Event()
        loop = asyncio.get_running_loop()
        try:
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(path, executable=config.ffmpeg_path(), options=self._ffmpeg_options()),
                volume=VOLUME,
            )
            voice.play(source, after=lambda error: loop.call_soon_threadsafe(finished.set))
            await finished.wait()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    async def _report_failure(self, session: TalkSession, error: SpeechError) -> None:
        channel = self.bot.get_channel(session.text_channel_id)
        if channel:
            await channel.send(line("talk_failed", error=error))  # type: ignore[union-attr]
        if not await self.engine.alive():
            self.engine.state = "off"

    # ---- commands ------------------------------------------------------------------

    @app_commands.command(name="语音模块", description="开启或关闭她的语音（GPT-SoVITS，占用显卡；仅部署者）")
    @app_commands.describe(开关="开 / 关（不填就看状态）")
    @app_commands.choices(开关=TOGGLE_CHOICES)
    @app_commands.guild_only()
    async def module(self, interaction: discord.Interaction, 开关: app_commands.Choice[str] | None = None):
        if not access.is_deployer(interaction.user.id):
            await interaction.response.send_message(line("deployer_only"), ephemeral=True)
            return
        if 开关 is None:
            await interaction.response.send_message(f"语音模块：{self.status_text()}", ephemeral=True)
            return
        if 开关.value == "off":
            owned = await self.stop_module()
            await interaction.response.send_message(
                line("voice_module_off") if owned else line("voice_module_off_external"), ephemeral=True
            )
            return
        await interaction.response.send_message(line("voice_module_starting"), ephemeral=True)
        try:
            await self.start_module()
        except SpeechError as e:
            await interaction.edit_original_response(content=line("voice_module_failed", error=e))
            return
        await interaction.edit_original_response(content=line("voice_module_ready"))

    @app_commands.command(name="说话", description="让她进入你的语音频道，把聊天回复读出来（需要先开启语音模块）")
    @app_commands.describe(开关="开 / 关（不填就切换）")
    @app_commands.choices(开关=TOGGLE_CHOICES)
    @app_commands.guild_only()
    async def talk(self, interaction: discord.Interaction, 开关: app_commands.Choice[str] | None = None):
        member = interaction.user
        assert isinstance(member, discord.Member)
        on = (开关.value == "on") if 开关 else not self.active(member.guild.id)
        if not on:
            ended = await self.end_talk(member.guild.id)
            await interaction.response.send_message(line("talk_off") if ended else line("talk_not_on"))
            return
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(await self.start_talk(member, interaction.channel))  # type: ignore[arg-type]

    # ---- leaving -------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        session = self.sessions.get(member.guild.id)
        if not session:
            return
        if member.id == self.bot.user.id and after.channel is None:  # type: ignore[union-attr]
            await self.end_talk(member.guild.id)
            return
        channel = session.voice.channel
        if before.channel == channel and after.channel != channel and all(m.bot for m in channel.members):  # type: ignore[union-attr]
            await asyncio.sleep(ALONE_GRACE)
            if self.sessions.get(member.guild.id) is session and all(m.bot for m in channel.members):  # type: ignore[union-attr]
                await self.end_talk(member.guild.id, line("alone_leave"))


async def setup(bot: commands.Bot) -> None:
    cog = Speech(bot)
    if not cog.engine.available:
        log.warning("Voice settings or GPT-SoVITS not found (%s); talk mode disabled.", config.VOICE_CONFIG)
        return
    await bot.add_cog(cog)
