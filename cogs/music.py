from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from music.player import GuildPlayer, LoopMode
from music.resolver import Resolver
from music.track import SourceError, Track, format_duration
from persona import line, who

log = logging.getLogger(__name__)

SOURCE_CHOICES = [
    app_commands.Choice(name="塞壬唱片（明日方舟官方）", value="siren"),
    app_commands.Choice(name="网易云音乐", value="netease"),
    app_commands.Choice(name="Bilibili", value="bilibili"),
]  # YouTube takes links only (pasted into query), so it isn't a search platform
LOOP_CHOICES = [
    app_commands.Choice(name="关闭", value="off"),
    app_commands.Choice(name="单曲循环", value="one"),
    app_commands.Choice(name="列表循环", value="all"),
]
RADIO_CHOICES = [
    app_commands.Choice(name="开", value="on"),
    app_commands.Choice(name="关", value="off"),
]
QUEUE_PAGE_SIZE = 10
PRIESTESS_COLOR = 0x8E7CC3
CHOICE_TIMEOUT = 60  # seconds a search-result list stays open


class VoiceError(Exception):
    """Why a member can't use the player right now (already a persona line)."""


def esc(text: str) -> str:
    return discord.utils.escape_markdown(text)


def added_message(tracks: list[Track], position: int) -> str:
    if len(tracks) == 1:
        t = tracks[0]
        where = line("where_next") if position == 1 else line("where_pos", pos=position)
        return line(
            "added_one",
            track=f"[{esc(t.display)}](<{t.page_url}>)",
            duration=t.duration_text,
            label=t.label,
            where=where,
        )
    return line("added_many", n=len(tracks), label=tracks[0].label)


def choices_embed(tracks: list[Track], query: str) -> discord.Embed:
    embed = discord.Embed(title=line("search_title", query=query)[:256], color=PRIESTESS_COLOR)
    embed.description = "\n".join(
        f"`{i + 1}.` [{esc(t.title)}](<{t.page_url}>) · {esc(t.artist or '')} `{t.duration_text}` · {t.label}"
        for i, t in enumerate(tracks)
    )[:4000]
    return embed


class SearchSelect(discord.ui.Select):
    def __init__(self, cog: Music, tracks: list[Track], play_next: bool):
        self.cog = cog
        self.tracks = tracks
        self.play_next = play_next
        options = [
            discord.SelectOption(
                label=f"{i + 1}. {t.title}"[:100],
                description=f"{t.label} · {t.artist or ''} · {t.duration_text}"[:100],
                value=str(i),
            )
            for i, t in enumerate(tracks)
        ]
        super().__init__(placeholder=line("search_placeholder"), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        track = self.tracks[int(self.values[0])]
        assert self.view is not None
        self.view.stop()  # chosen: don't fire the timeout message
        await interaction.response.edit_message(
            content=line("search_selected", title=esc(track.display)), embed=None, view=None
        )
        await self.cog.enqueue(interaction, [track], self.play_next)


class SearchView(discord.ui.View):
    """A pick-one list of search results that only the person who searched can use."""

    def __init__(self, cog: Music, owner_id: int, tracks: list[Track], play_next: bool):
        super().__init__(timeout=CHOICE_TIMEOUT)
        self.owner_id = owner_id
        self.message: discord.Message | None = None  # set after sending, for the timeout edit
        self.add_item(SearchSelect(cog, tracks, play_next))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(line("search_not_owner"), ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(content=line("choices_timeout"), embed=None, view=None)
            except discord.HTTPException:
                pass


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.resolver = Resolver()
        self.players: dict[int, GuildPlayer] = {}

    async def cog_unload(self) -> None:
        for player in list(self.players.values()):
            await player.destroy()
        self.players.clear()
        await self.resolver.close()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, "original", error)
        if isinstance(original, (SourceError, VoiceError)):
            message = line("source_error", error=original) if isinstance(original, SourceError) else str(original)
        else:
            log.exception("Command error", exc_info=original)
            message = line("generic_error")
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # ---- player access (shared with the chat cog) -------------------------

    def ensure_not_talking(self, guild: discord.Guild) -> None:
        """Music waits while she's in talk mode (cogs/speech.py), like the radio does the other way."""
        speech = self.bot.get_cog("Speech")
        if speech is not None and speech.active(guild.id):  # type: ignore[attr-defined]
            raise VoiceError(line("talk_blocks_music"))

    async def join(self, member: discord.Member, text_channel: discord.abc.Messageable) -> GuildPlayer:
        """Join the member's voice channel and return the guild's player."""
        if not member.voice or not member.voice.channel:
            raise VoiceError(line("need_voice", who=who(member, member.guild)))
        self.ensure_not_talking(member.guild)

        guild = member.guild
        channel = member.voice.channel
        voice = guild.voice_client
        if voice is None:
            await channel.connect(self_deaf=True)
        elif voice.channel != channel:
            player = self.players.get(guild.id)
            if player and player.current:
                raise VoiceError(line("busy_elsewhere", channel=voice.channel.mention))  # type: ignore[union-attr]
            await voice.move_to(channel)  # type: ignore[union-attr]

        player = self.players.get(guild.id)
        if player is None:
            player = self.players[guild.id] = GuildPlayer(self.bot, guild, self.resolver, text_channel)
        player.channel = text_channel
        return player

    def player_for(self, member: discord.Member) -> GuildPlayer:
        """The guild's player, if the member is in the same voice channel as the bot."""
        player = self.players.get(member.guild.id)
        if not player or not member.guild.voice_client:
            raise VoiceError(line("not_in_voice"))
        if not member.voice or member.voice.channel != player.voice.channel:  # type: ignore[union-attr]
            raise VoiceError(line("not_same_channel"))
        return player

    async def add_tracks(
        self, member: discord.Member, text_channel: discord.abc.Messageable, tracks: list[Track], play_next: bool
    ) -> str:
        """Queue tracks for a member and return the confirmation message."""
        player = await self.join(member, text_channel)
        for t in tracks:
            t.requester_id = member.id
        position = 1 if play_next else len(player.queue) + 1
        player.add(tracks, front=play_next)
        if player.current is None and position == 1 and len(tracks) == 1:
            message = line("play_now", title=esc(tracks[0].display))
        else:
            message = added_message(tracks, position)
        if len(tracks) == 1 and (note := tracks[0].extra.get("note")):
            message += f"\n-# {note}"
        return message

    # ---- helpers ---------------------------------------------------------

    def get_player(self, interaction: discord.Interaction) -> GuildPlayer | None:
        return self.players.get(interaction.guild_id or 0)

    async def require_player(self, interaction: discord.Interaction) -> GuildPlayer | None:
        assert isinstance(interaction.user, discord.Member)
        try:
            return self.player_for(interaction.user)
        except VoiceError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return None

    @staticmethod
    async def reply(interaction: discord.Interaction, content: str, ephemeral: bool = False) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)

    async def offer_choices(
        self, interaction: discord.Interaction, query: str, source: str | None, play_next: bool
    ) -> None:
        """Reply (privately) with a pick-one list of search results; picking queues the song."""
        if interaction.guild:
            try:
                self.ensure_not_talking(interaction.guild)
            except VoiceError as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return
        tracks = await self.resolver.search_choices(query, source)
        if not tracks:
            await interaction.followup.send(line("search_none", query=query), ephemeral=True)
            return
        view = SearchView(self, interaction.user.id, tracks, play_next)
        view.message = await interaction.followup.send(
            line("choices_prompt", query=query), embed=choices_embed(tracks, query), view=view, ephemeral=True, wait=True
        )

    async def enqueue(self, interaction: discord.Interaction, tracks: list[Track], play_next: bool) -> None:
        assert isinstance(interaction.user, discord.Member)
        try:
            message = await self.add_tracks(interaction.user, interaction.channel, tracks, play_next)  # type: ignore[arg-type]
        except VoiceError as e:
            await self.reply(interaction, str(e), ephemeral=True)
            return
        await self.reply(interaction, message)

    # ---- commands --------------------------------------------------------

    @app_commands.command(name="play", description="点歌：输入歌名，或 Bilibili / 网易云 / YouTube 链接（YouTube 只能用链接）")
    @app_commands.describe(query="歌名、关键词，或者歌曲 / 视频 / 歌单链接", source="搜索平台（发链接时会自动识别）", next="插队到下一首")
    @app_commands.choices(source=SOURCE_CHOICES)
    @app_commands.guild_only()
    async def play(
        self,
        interaction: discord.Interaction,
        query: str,
        source: app_commands.Choice[str] | None = None,
        next: bool = False,
    ):
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.voice:
            await interaction.response.send_message(line("need_voice", who=who(member, interaction.guild)), ephemeral=True)
            return
        source_name = source.value if source else None
        if not self.resolver.is_link(query):
            # A typed name is ambiguous (covers, same-name songs): let the user pick.
            await interaction.response.defer(thinking=True, ephemeral=True)
            await self.offer_choices(interaction, query, source_name, next)
            return
        await interaction.response.defer(thinking=True)
        tracks = await self.resolver.find(query, source_name)
        await self.enqueue(interaction, tracks, next)

    @app_commands.command(name="search", description="搜索歌曲并从结果中挑选")
    @app_commands.describe(query="歌名或关键词", source="搜索平台", next="插队到下一首")
    @app_commands.choices(source=SOURCE_CHOICES)
    @app_commands.guild_only()
    async def search(
        self,
        interaction: discord.Interaction,
        query: str,
        source: app_commands.Choice[str] | None = None,
        next: bool = False,
    ):
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self.offer_choices(interaction, query, source.value if source else None, next)

    @app_commands.command(name="电台", description="塞壬电台：队列放完后，从塞壬唱片随机接着放")
    @app_commands.describe(开关="开 / 关（不填就切换）")
    @app_commands.choices(开关=RADIO_CHOICES)
    @app_commands.guild_only()
    async def radio(self, interaction: discord.Interaction, 开关: app_commands.Choice[str] | None = None):
        member = interaction.user
        assert isinstance(member, discord.Member)
        player = self.players.get(member.guild.id)
        on = (开关.value == "on") if 开关 else not (player and player.radio)
        try:
            message = await self.set_radio(member, interaction.channel, on)  # type: ignore[arg-type]
        except VoiceError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await interaction.response.send_message(message)

    async def set_radio(self, member: discord.Member, text_channel: discord.abc.Messageable, on: bool) -> str:
        """Turn the Siren radio on (joining the member's voice channel) or off; the reply line."""
        if not on:
            player = self.players.get(member.guild.id)
            if not player or not player.radio:
                return line("radio_not_on")
            player.set_radio(False)
            return line("radio_off")
        player = await self.join(member, text_channel)
        if player.radio:
            return line("radio_already_on")
        player.set_radio(True)
        return line("radio_on") if player.current or player.queue else line("radio_on_now")

    @app_commands.command(name="skip", description="跳过当前歌曲")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        if not (player := await self.require_player(interaction)):
            return
        if not player.current:
            await interaction.response.send_message(line("nothing_playing"), ephemeral=True)
            return
        title = player.current.title
        player.skip()
        await interaction.response.send_message(line("skipped", title=esc(title)))

    @app_commands.command(name="pause", description="暂停播放")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction):
        if not (player := await self.require_player(interaction)):
            return
        await interaction.response.send_message(line("paused") if player.pause() else line("nothing_playing"))

    @app_commands.command(name="resume", description="继续播放")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction):
        if not (player := await self.require_player(interaction)):
            return
        await interaction.response.send_message(line("resumed") if player.resume() else line("not_paused"))

    @app_commands.command(name="stop", description="停止播放并清空队列")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction):
        if not (player := await self.require_player(interaction)):
            return
        player.stop()
        await interaction.response.send_message(line("stopped"))

    @app_commands.command(name="leave", description="让机器人离开语音频道")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction):
        if not (player := await self.require_player(interaction)):
            return
        self.players.pop(player.guild.id, None)
        await player.destroy()
        await interaction.response.send_message(line("left"))

    @app_commands.command(name="nowplaying", description="查看正在播放的歌曲")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.get_player(interaction)
        if not player or not player.current:
            await interaction.response.send_message(line("nothing_playing"), ephemeral=True)
            return
        await interaction.response.send_message(embed=player.now_playing_embed())

    @app_commands.command(name="queue", description="查看播放队列")
    @app_commands.describe(page="页码")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = 1):
        player = self.get_player(interaction)
        if not player or (not player.current and not player.queue):
            await interaction.response.send_message(line("queue_empty"), ephemeral=True)
            return
        pages = max(1, -(-len(player.queue) // QUEUE_PAGE_SIZE))
        page = min(page, pages)
        start = (page - 1) * QUEUE_PAGE_SIZE
        lines = []
        if player.current:
            c = player.current
            lines.append(f"{line('queue_now')} [{esc(c.display)}](<{c.page_url}>) `{c.duration_text}` · {c.label}\n")
        for i, t in enumerate(player.queue[start : start + QUEUE_PAGE_SIZE], start=start + 1):
            lines.append(f"`{i}.` [{esc(t.display)}](<{t.page_url}>) `{t.duration_text}` · {t.label}")
        if not player.queue:
            lines.append(line("queue_end"))
        total = sum(t.duration or 0 for t in player.queue)
        embed = discord.Embed(title=line("queue_title"), description="\n".join(lines)[:4000], color=PRIESTESS_COLOR)
        loop_text = {"off": "关闭", "one": "单曲循环", "all": "列表循环"}[player.loop_mode.value]
        embed.set_footer(
            text=f"第 {page}/{pages} 页 · 共 {len(player.queue)} 首 · 总时长 {format_duration(total)} · 循环：{loop_text}"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="调整音量 (0-100)")
    @app_commands.describe(percent="音量百分比")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 0, 100]):
        if not (player := await self.require_player(interaction)):
            return
        player.set_volume(percent)
        await interaction.response.send_message(line("volume", percent=percent))

    @app_commands.command(name="loop", description="设置循环模式")
    @app_commands.describe(mode="循环模式")
    @app_commands.choices(mode=LOOP_CHOICES)
    @app_commands.guild_only()
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        if not (player := await self.require_player(interaction)):
            return
        player.loop_mode = LoopMode(mode.value)
        await interaction.response.send_message(line(f"loop_{mode.value}"))

    @app_commands.command(name="shuffle", description="打乱队列顺序")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction):
        if not (player := await self.require_player(interaction)):
            return
        player.shuffle()
        await interaction.response.send_message(line("shuffled", n=len(player.queue)))

    @app_commands.command(name="remove", description="从队列中移除一首歌")
    @app_commands.describe(position="在 /queue 中的序号")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: app_commands.Range[int, 1]):
        if not (player := await self.require_player(interaction)):
            return
        if position > len(player.queue):
            await interaction.response.send_message(line("remove_out_of_range", n=len(player.queue)), ephemeral=True)
            return
        track = player.queue.pop(position - 1)
        await interaction.response.send_message(line("removed", title=esc(track.display)))

    # ---- events ----------------------------------------------------------

    @commands.Cog.listener()
    async def on_music_player_idle(self, guild_id: int) -> None:
        if player := self.players.pop(guild_id, None):
            await player.destroy()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        player = self.players.get(guild.id)
        if not player:
            return

        # The bot itself was disconnected (kicked, or channel deleted).
        if member.id == self.bot.user.id and after.channel is None:  # type: ignore[union-attr]
            self.players.pop(guild.id, None)
            await player.destroy()
            return

        # Leave when everyone else has left the bot's channel for a minute.
        voice = guild.voice_client
        if voice and before.channel == voice.channel and after.channel != voice.channel:
            if all(m.bot for m in voice.channel.members):  # type: ignore[union-attr]
                await asyncio.sleep(60)
                voice = guild.voice_client
                if voice and all(m.bot for m in voice.channel.members) and self.players.get(guild.id) is player:  # type: ignore[union-attr]
                    self.players.pop(guild.id, None)
                    await player.channel.send(line("alone_leave"))
                    await player.destroy()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
