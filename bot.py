import asyncio
import logging
import sys

import discord
from discord import app_commands
from discord.ext import commands

import access
import config
from persona import line

log = logging.getLogger("musicbot")


class Tree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # A server not in ALLOWED_GUILD_IDS gets nothing, even in the moment before she leaves.
        return access.guild_allowed(interaction.guild_id)


class MusicBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()  # includes guilds + voice_states
        # Message Content is needed for CHAT_CHANNEL_IDS, and for @mentions of the bot's role:
        # Discord only sends the text of messages that mention the bot user itself, and the
        # bot's managed role has the same name, so people often pick it from the @ list.
        # It's dropped again in setup_hook if the portal switch is off.
        intents.message_content = True
        # No pings unless a message asks for them (the calendar's role ping does): song titles
        # are shown in plain messages, and a video titled "@everyone" must not ping anyone.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            tree_cls=Tree,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def setup_hook(self) -> None:
        access.set_deployer(self.application)
        flags = self.application.flags if self.application else None
        if not (flags and (flags.gateway_message_content or flags.gateway_message_content_limited)):
            # Discord refuses the connection if a privileged intent is asked for but not enabled.
            # Login has happened but the gateway hasn't connected yet, so it can still be dropped.
            self._connection._intents.message_content = False
            log.warning(
                "Message Content Intent is off in the Developer Portal: she can't read messages that "
                "@ her role instead of her%s.", ", or CHAT_CHANNEL_IDS channels" if config.CHAT_CHANNEL_IDS else ""
            )
        await self.load_extension("cogs.music")
        await self.load_extension("cogs.chat")
        await self.load_extension("cogs.calendar")
        await self.load_extension("cogs.balance")
        await self.load_extension("cogs.speech")
        await self.load_extension("cogs.help")
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), config.DEV_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take a while to show up)", len(synced))

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await access.leave_if_not_allowed(guild)

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        # The @mention prefix only exists so mentions are parsed; chat (cogs/chat.py) handles the
        # text, so "@普瑞赛斯 嗨" not being a prefix command isn't an error.
        if not isinstance(exception, commands.CommandNotFound):
            await super().on_command_error(context, exception)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        for guild in list(self.guilds):
            await access.leave_if_not_allowed(guild)
        if not config.ALLOWED_GUILD_IDS and len(self.guilds) > 1:
            log.warning(
                "She is in %d servers and ALLOWED_GUILD_IDS is empty: every server shares your API "
                "keys and the daily limits. List the ones you allow in ALLOWED_GUILD_IDS.", len(self.guilds)
            )
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name=line("presence"))
        )


MUTEX_NAME = "Local\\PriestessMusicBot"
ERROR_ALREADY_EXISTS = 183


def claim_single_instance() -> int | None:
    """A named mutex, held while the bot runs (console or tray). None if another copy has it.

    Two copies would log in with the same token and fight over the voice connection.
    """
    import ctypes

    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO)
    if claim_single_instance() is None:
        sys.exit("普瑞赛斯已经在运行了（看看右下角的托盘图标）。")
    if not config.DISCORD_TOKEN:
        sys.exit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    log.info("Using ffmpeg at %s", config.ffmpeg_path())
    bot = MusicBot()
    asyncio.run(bot.start(config.DISCORD_TOKEN))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
