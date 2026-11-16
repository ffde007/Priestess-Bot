"""Who may do what, and which servers she may stay in.

Two different people:
- the deployer: the owner of the bot application in the Discord Developer Portal, i.e. whoever
  runs this copy with their own token and API keys. Only they can use the commands that act on
  the whole bot (/余额, /聊天统计, /语音模块, /同步活动, /推送提醒), and only they have no chat
  limits at all.
- a server's owner: her "博士" in that server. They aren't held to the per-person daily chat
  limit there, but the server-wide limit still applies to them.

ALLOWED_GUILD_IDS lists the servers she may be in. If someone adds her anywhere else, she
leaves at once and ignores everything from there. Empty = no restriction (then turn off
"Public Bot" in the Developer Portal so nobody else can invite her).
"""

from __future__ import annotations

import logging

import discord

import config

log = logging.getLogger(__name__)

_deployers: set[int] = set()


def set_deployer(app: discord.AppInfo | None) -> None:
    """Read the application's owner (and the team owner for a team-owned app) after login."""
    _deployers.clear()
    if app is None:
        log.warning("Couldn't read the application's owner: commands for the deployer are off.")
        return
    owner_id = app.team.owner_id if app.team else (app.owner.id if app.owner else None)
    if owner_id:
        _deployers.add(owner_id)
    log.info("Deployer: %s", ", ".join(map(str, _deployers)) or "none")


def is_deployer(user_id: int) -> bool:
    return user_id in _deployers


def deployer_ids() -> set[int]:
    return set(_deployers)


def guild_allowed(guild_id: int | None) -> bool:
    return guild_id is None or not config.ALLOWED_GUILD_IDS or guild_id in config.ALLOWED_GUILD_IDS


async def leave_if_not_allowed(guild: discord.Guild) -> bool:
    """Leave a server that isn't in ALLOWED_GUILD_IDS. True if she left (or tried to)."""
    if guild_allowed(guild.id):
        return False
    log.warning("Leaving server %s (%s): it isn't in ALLOWED_GUILD_IDS", guild.name, guild.id)
    try:
        await guild.leave()
    except discord.HTTPException as e:
        log.error("Couldn't leave server %s: %s", guild.id, e)
    return True
